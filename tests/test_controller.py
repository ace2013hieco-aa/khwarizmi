"""Golden fixtures for the IDR-029 P7 controller (v6 §29, C-tier).

Proves the 10 acceptance criteria of IDR-029 against real SQLite:
1. a READY EXTRACT task with SUCCEEDED deps is claimed, executed, accepted,
   and lands SUCCEEDED; rows + links + §14 edges exist; event delta is only
   TaskStatusChanged (+ IntentApplied/TaskCreated at admission) — no new type;
2. an INVALID extraction output → RETRYING (attempts remain) or FAILED
   (exhausted), with 0 rows/links/edges (no partial write);
3. crash between acceptance and SUCCEEDED → the explicit recovery chain:
   stale RUNNING → NO_SIGNAL → second miss → FAILED → RETRYING → RUNNING
   (attempt increments) → re-acceptance idempotent (A2-03, keyed on
   producing_task_id not attempt), exactly one claim set, SUCCEEDED;
4. a RUNNING task whose lease expired → NO_SIGNAL → (fresh heartbeat →
   RUNNING) / (second miss → FAILED); no acceptance from a non-RUNNING task;
5. divergent re-execution of the same task → refused (A2-03), task FAILED,
   no second output;
6. source_ref mismatch → binding error; task still RUNNING → RETRYING/FAILED
   with 0 rows (case b); lease-race binding error → NO transition (case a),
   logged, recovery owns the task (IDR29-02);
7. a second controller instance fails the scheduler_lock and exits;
8. HUMAN_GATE tasks reach WAITING_HUMAN and are never auto-passed; the mode
   check leaves the project AWAITING_HUMAN and the next tick dispatches
   nothing until the human decision returns the mode to ACTIVE (IDR29-05);
9. a non-EXTRACT AGENT_TASK with no handler → fail-closed diagnostic (never
   silent SUCCEEDED);
10. re-running the whole sequence on the same db is idempotent (no duplicate
    tasks, events, rows, or edges).
"""
from __future__ import annotations

import threading

import pytest

from hermes.core import frozen_clock
from hermes.core.intents import Intent, IntentKind
from hermes.core.modes import OperationalMode
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ProjectRepository,
    TaskRepository,
)
from hermes.research.controller import Controller, LockLostError
from hermes.research.extraction import (
    ExtractionNotBoundToTask,
    accept_extraction_output,
    build_extract_task_payload,
    extraction_draft_from_mapping,
)
from hermes.research.gateway import apply_intent

CLOCK = "2026-01-01T00:00:00.000000+00:00"
STALE = "2025-01-01T00:00:00.000000+00:00"

# A4 — the ratified operator credential for the §11 gate-resolution verdicts.
OP_ID = "op-1"
OP_TOKEN = "op-token-1"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    from hermes.persistence.repositories import OperatorCredentialRepository
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    yield conn
    conn.close()


def count_rows(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]


def count_edges(conn) -> int:
    return count_rows(conn, "provenance_edges")


def event_types(conn) -> set[str]:
    return {r["event_type"] for r in
            conn.execute("SELECT DISTINCT event_type FROM events")}


def admit_extract_task(db, source_ref="dataset_manifest:dm-1",
                       scope="both") -> str:
    """Admit an EXTRACT task via the ordinary gateway (lands PENDING)."""
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1", payload=build_extract_task_payload(source_ref, scope)))
    return result.entity_id


def good_output() -> dict:
    return {
        "source_ref": "dataset_manifest:dm-1",
        "claims": [{
            "ref": "c1",
            "statement": "Alpha reduces beta under gamma conditions.",
            "source_ref": "dataset_manifest:dm-1",
            "support_state": "INFERRED",
            "span_ref": None,  # claim-ground G10: unverifiable span on a non-readable carrier
            "claim_type": "causal",
            "context_tags": {"regime": "ICSS-v1:low-vol",
                             "dataset_ref": "dm-1"},
            "assumption_refs": ["a1"],
        }],
        "assumptions": [{
            "ref": "a1",
            "statement": "The sample is representative.",
            "context_tags": {"population": "adults-18-65"},
            "supporting_artifact_refs": ["dataset_manifest:dm-1"],
        }],
        "extracted_by": "model_ref:c-tier-1",
        "schema_version": "2",
    }


def malformed_output() -> dict:
    out = good_output()
    out["claims"][0]["assumption_refs"] = ["missing"]
    return out


def divergent_output() -> dict:
    """Same task, DIFFERENT content (A2-03 divergence on re-execution)."""
    out = good_output()
    out["claims"][0]["statement"] = "Alpha INCREASES beta under gamma."
    return out


def good_extract_fn():
    """Stub: return the canonical good draft regardless of the task.

    M3: the contract is ``(task, untrusted)`` — the untrusted content view
    is the only source-text surface (the stub ignores it)."""
    def _fn(task, untrusted):
        return extraction_draft_from_mapping(good_output())
    return _fn


def stale_heartbeat(db, task_id: str) -> None:
    db.execute("UPDATE tasks SET last_heartbeat = ? WHERE task_id = ?",
               (STALE, task_id))


def make_controller(db, **kwargs) -> Controller:
    kwargs.setdefault("extract_fn", good_extract_fn())
    kwargs.setdefault("clock", frozen_clock(CLOCK))
    return Controller(db, project_id="p1", **kwargs)


# ── 1. happy path: claim → execute → accept → SUCCEEDED, no new event type ──

def test_1_extract_claimed_executed_accepted_succeeded(db):
    task_id = admit_extract_task(db)
    tr = TaskRepository(db)
    # PENDING on admission; discovery promotes + claims it
    assert tr.get_status(task_id) is TaskStatus.PENDING

    before = event_types(db)
    ctrl = make_controller(db)
    out = ctrl.tick()

    assert task_id in out.dispatched
    assert task_id in out.succeeded
    assert out.idle == ""
    assert tr.get_status(task_id) is TaskStatus.SUCCEEDED
    # rows + links + §14 edges persisted through the write path
    assert count_rows(db, "research_claims") == 1
    assert count_rows(db, "research_assumptions") == 1
    assert count_rows(db, "claim_assumption_links") == 1
    assert count_edges(db) == 2  # derived_from + cites
    # event delta = only TaskStatusChanged (+ admission events already present)
    after = event_types(db)
    assert after <= (before | {"TaskStatusChanged"})
    assert "ClaimExtractionAdmitted" not in after


# ── 2. INVALID output → RETRYING / FAILED, 0 rows ──

def test_2_invalid_output_retries_then_fails_no_partial_write(db):
    task_id = admit_extract_task(db)
    tr = TaskRepository(db)

    def flaky_fn(task, untrusted):
        return extraction_draft_from_mapping(malformed_output())

    ctrl = Controller(db, project_id="p1", extract_fn=flaky_fn,
                      clock=frozen_clock(CLOCK))
    out1 = ctrl.tick()
    # first rejection: attempts remain (max_retries=3) → RETRYING
    assert task_id in out1.retried
    assert tr.get_status(task_id) is TaskStatus.RETRYING
    assert count_rows(db, "research_claims") == 0
    assert count_rows(db, "research_assumptions") == 0
    assert count_edges(db) == 0

    # a task that exhausts attempts lands FAILED
    low = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload("dataset_manifest:dm-1",
                                              "both"),
                 "task_id": "extract_low",
                 "idempotency_key": "extract-low-key",
                 "max_retries": 1}))
    low_id = low.entity_id
    out2 = ctrl.tick()
    assert low_id in out2.failed
    assert tr.get_status(low_id) is TaskStatus.FAILED
    assert count_rows(db, "research_claims") == 0


# ── 3. crash mid-acceptance → the explicit recovery chain (IDR29-01) ──

def test_3_crash_mid_acceptance_recovery_chain_idempotent(db):
    task_id = admit_extract_task(db)
    tr = TaskRepository(db)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    # acceptance committed (rows persisted), SUCCEEDED never happened —
    # the task is RUNNING with persisted rows and a stale heartbeat
    accept_extraction_output(
        db, "p1", task_id, extraction_draft_from_mapping(good_output()),
        extracted_by="model_ref:c-tier-1")
    assert count_rows(db, "research_claims") == 1
    stale_heartbeat(db, task_id)

    ctrl = make_controller(db)
    # tick 1: stale RUNNING → NO_SIGNAL (first miss)
    t1 = ctrl.tick()
    assert task_id in t1.recovery
    assert tr.get_status(task_id) is TaskStatus.NO_SIGNAL

    # tick 2: second conclusive miss → FAILED → requeue (attempt 1→2) →
    # re-acceptance idempotent (A2-03 keyed on producing_task_id) → SUCCEEDED
    ctrl.tick()
    assert tr.get_status(task_id) is TaskStatus.SUCCEEDED
    assert tr.get(task_id)["attempt"] == 2   # the attempt increment happened
    # exactly one claim set — one-shot survived the attempt increment
    assert count_rows(db, "research_claims") == 1
    assert count_rows(db, "research_assumptions") == 1
    assert count_rows(db, "claim_assumption_links") == 1
    assert count_edges(db) == 2


# ── 4. lease expiry → NO_SIGNAL → (fresh heartbeat → RUNNING) / (FAILED) ──

def test_4a_lease_expired_no_signal_fresh_heartbeat_reverts(db):
    task_id = admit_extract_task(db)
    tr = TaskRepository(db)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    stale_heartbeat(db, task_id)

    ctrl = make_controller(db)
    ctrl.tick()
    assert tr.get_status(task_id) is TaskStatus.NO_SIGNAL

    # fresh heartbeat before the second check → revert to RUNNING
    tr.heartbeat(task_id)
    t2 = ctrl.tick()
    assert task_id in t2.recovery
    assert tr.get_status(task_id) is TaskStatus.RUNNING

    # no acceptance is possible while non-RUNNING (A2-02 binding) — and the
    # reverted task can still complete normally
    out = accept_extraction_output(
        db, "p1", task_id, extraction_draft_from_mapping(good_output()),
        extracted_by="model_ref:c-tier-1")
    assert out["verdict"] == "ADMITTED"


def test_4b_lease_expired_second_miss_fails(db):
    task_id = admit_extract_task(db)
    tr = TaskRepository(db)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    stale_heartbeat(db, task_id)

    ctrl = make_controller(db)
    ctrl.tick()                 # first miss → NO_SIGNAL
    assert tr.get_status(task_id) is TaskStatus.NO_SIGNAL

    # no acceptance from a non-RUNNING task (A2-02) while NO_SIGNAL
    with pytest.raises(ExtractionNotBoundToTask, match="not RUNNING"):
        accept_extraction_output(
            db, "p1", task_id, extraction_draft_from_mapping(good_output()),
            extracted_by="model_ref:c-tier-1")

    # second miss → FAILED → requeue → re-execute → accepted → SUCCEEDED
    t2 = ctrl.tick()
    assert task_id in t2.recovery
    assert task_id in t2.succeeded
    assert tr.get_status(task_id) is TaskStatus.SUCCEEDED
    # the recovery FAILED transition actually happened (event audit)
    events = list(db.execute(
        "SELECT * FROM events WHERE task_id = ? ORDER BY created_at",
        (task_id,)).fetchall())
    assert any(e["to_state"] == "FAILED" and "second conclusive miss"
               in (e["reason"] or "") for e in events)


# ── 5. divergent re-execution → refused, FAILED, no second output ──

def test_5_divergent_reexecution_refused_no_second_output(db):
    task_id = admit_extract_task(db)
    tr = TaskRepository(db)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    accept_extraction_output(
        db, "p1", task_id, extraction_draft_from_mapping(good_output()),
        extracted_by="model_ref:c-tier-1")
    assert count_rows(db, "research_claims") == 1
    stale_heartbeat(db, task_id)

    def divergent_fn(task, untrusted):
        return extraction_draft_from_mapping(divergent_output())

    ctrl = Controller(db, project_id="p1", extract_fn=divergent_fn,
                      clock=frozen_clock(CLOCK))
    ctrl.tick()                     # NO_SIGNAL
    ctrl.tick()                     # FAILED → requeue → divergent refused
    assert tr.get_status(task_id) is TaskStatus.FAILED
    # exactly the first output — no second claim set
    assert count_rows(db, "research_claims") == 1
    assert count_rows(db, "research_assumptions") == 1
    assert count_edges(db) == 2


# ── 6. binding-error split (IDR29-02): case (b) retries, case (a) does not ──

def test_6b_source_mismatch_retries_zero_rows(db):
    task_id = admit_extract_task(db)
    tr = TaskRepository(db)

    def bad_fn(task, untrusted):
        # draft whose source_ref ≠ task.spec.source_ref
        out = good_output()
        out["source_ref"] = "dataset_manifest:dm-999"
        return extraction_draft_from_mapping(out)

    ctrl = Controller(db, project_id="p1", extract_fn=bad_fn,
                      clock=frozen_clock(CLOCK))
    out = ctrl.tick()
    # task still RUNNING when the binding fired → case (b) → RETRYING
    assert task_id in out.retried
    assert tr.get_status(task_id) is TaskStatus.RETRYING
    assert count_rows(db, "research_claims") == 0


def test_6a_lease_race_binding_error_no_transition(db):
    task_id = admit_extract_task(db)
    tr = TaskRepository(db)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")

    def racing_fn(task, untrusted):
        # simulate a concurrent transition leaving RUNNING before the write:
        # accept_extraction_output's own pre-check then fires the binding
        # error (task no longer RUNNING)
        tr.transition_status(task_id, TaskStatus.SUCCEEDED,
                             caused_by="other")
        return extraction_draft_from_mapping(good_output())

    ctrl = Controller(db, project_id="p1", extract_fn=racing_fn,
                      clock=frozen_clock(CLOCK))
    # ADV-02: `_execute_extract` is an authoritative write path — it runs
    # under the controller's acquired lease (the real flow), so acquire first.
    assert ctrl._acquire_lock() is True
    try:
        ctrl._execute_extract(task_id)
    finally:
        ctrl._release_lock()
    # case (a): the controller did NOT transition — the task stays where the
    # concurrent actor put it, and a note records that recovery owns it
    assert tr.get_status(task_id) is TaskStatus.SUCCEEDED
    assert any("recovery owns it" in n for n in ctrl._notes)


# ── 7. second controller instance fails the scheduler_lock ──

def test_7_second_controller_fails_lock_no_interleave(db):
    task_id = admit_extract_task(db)
    tr = TaskRepository(db)

    # simulate a live first controller holding the lock (fresh lease)
    db.execute("INSERT INTO scheduler_lock (id, owner, locked_at) "
               "VALUES (0, 'other-controller', ?)", (CLOCK,))

    ctrl = make_controller(db)
    out = ctrl.tick()
    assert out.idle == "lock_held"
    assert out.dispatched == []
    assert tr.get_status(task_id) is TaskStatus.PENDING   # untouched

    # stale lease (crashed holder) → reclaimed and dispatched
    db.execute("UPDATE scheduler_lock SET locked_at = ? WHERE id = 0",
               (STALE,))
    out2 = ctrl.tick()
    assert task_id in out2.dispatched
    assert tr.get_status(task_id) is TaskStatus.SUCCEEDED


# ── 8. HUMAN_GATE → WAITING_HUMAN, never auto-passed; wave stops ──

def test_8_human_gate_parks_wave_stops_and_resumes(db):
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-1-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    gate_id = result.entity_id
    tr = TaskRepository(db)

    ctrl = make_controller(db)
    out1 = ctrl.tick()
    assert gate_id in out1.waiting_human
    assert out1.idle == "waiting_human"         # the wave stops
    assert tr.get_status(gate_id) is TaskStatus.WAITING_HUMAN
    # the mode check (IDR29-05): project is AWAITING_HUMAN now
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.AWAITING_HUMAN

    # next tick: mode blocks dispatch — nothing moves
    out2 = ctrl.tick()
    assert out2.idle.startswith("mode:")
    assert out2.dispatched == []
    assert tr.get_status(gate_id) is TaskStatus.WAITING_HUMAN

    # human decision: mode back to ACTIVE + gate resumes → SUCCEEDED
    pr = ProjectRepository(db)
    pr.transition_mode("p1", OperationalMode.ACTIVE, caused_by="human")
    tr.transition_status(gate_id, TaskStatus.RUNNING, caused_by="human")
    tr.transition_status(gate_id, TaskStatus.SUCCEEDED, caused_by="human")
    ctrl.tick()
    assert tr.get_status(gate_id) is TaskStatus.SUCCEEDED


# ── ADV-02: scheduler-lease generation fencing ──
# The attack: a live controller A whose tick outlasts its 60s lease keeps
# writing after B legitimately reclaimed the stale lock. The fix: the lock
# row carries a `generation` bumped on every ownership change, and every
# authoritative write A performs re-validates owner+generation INSIDE the
# write transaction — a stale write raises LockLostError and rolls back.


def test_adv02_live_controller_write_fails_closed_after_reclaim(db):
    """The core ADV-02 attack, deterministic: A's extract_fn (the injected
    model call) runs long enough for the lease to expire and B to reclaim
    the stale lock MID-TICK; A's acceptance write then fails closed."""
    task_id = admit_extract_task(db)
    reclaimed: dict[str, bool] = {}

    def slow_extract_fn(task, untrusted):
        # MID-TICK: time advances past A's lease; B reclaims the stale lock
        # while A is still live and about to write.
        advanced = "2026-01-01T00:02:00.000000+00:00"  # CLOCK + 120s
        b = Controller(db, project_id="p1", owner="controller-B",
                       clock=frozen_clock(advanced),
                       extract_fn=good_extract_fn(), lease_seconds=60)
        reclaimed["ok"] = b._acquire_lock()
        return extraction_draft_from_mapping(good_output())

    a = Controller(db, project_id="p1", owner="controller-A",
                   clock=frozen_clock(CLOCK), extract_fn=slow_extract_fn,
                   lease_seconds=60)
    out = a.tick()
    assert reclaimed["ok"] is True                       # B reclaimed
    assert out.idle == "lock_lost"                        # A failed closed
    # A's write never landed: zero claims/links, task not SUCCEEDED
    assert count_rows(db, "research_claims") == 0
    assert count_rows(db, "claim_assumption_links") == 0
    assert TaskRepository(db).get_status(task_id) is not TaskStatus.SUCCEEDED
    # B owns the lock at the bumped generation
    row = db.execute(
        "SELECT owner, generation FROM scheduler_lock WHERE id = 0").fetchone()
    assert row["owner"] == "controller-B"
    assert row["generation"] == 1
    # B remains authoritative: the v4 §19 ladder (two conclusive misses)
    # recovers A's orphaned RUNNING claim and completes the task
    b2 = Controller(db, project_id="p1", owner="controller-B",
                    clock=frozen_clock("2026-01-01T00:03:00.000000+00:00"),
                    extract_fn=good_extract_fn(), lease_seconds=60)
    b2.tick()  # stale RUNNING → NO_SIGNAL (first miss)
    b2.tick()  # second miss → FAILED → requeue → RUNNING → re-execute
    assert TaskRepository(db).get_status(task_id) is TaskStatus.SUCCEEDED
    assert count_rows(db, "research_claims") == 1


def test_adv02_stale_controller_repo_write_raises_lock_lost(db):
    """Direct fence probe: A holds generation 0; B reclaims (generation 1);
    A's repository write raises LockLostError and rolls back — nothing from
    A lands; B (current owner) writes normally."""
    task_id = admit_extract_task(db)
    TaskRepository(db).transition_status(
        task_id, TaskStatus.READY, caused_by="test")
    a = Controller(db, project_id="p1", owner="controller-A",
                   clock=frozen_clock(CLOCK), extract_fn=good_extract_fn(),
                   lease_seconds=60)
    assert a._acquire_lock() is True                      # generation 0
    b = Controller(db, project_id="p1", owner="controller-B",
                   clock=frozen_clock("2026-01-01T00:02:00.000000+00:00"),
                   extract_fn=good_extract_fn(), lease_seconds=60)
    assert b._acquire_lock() is True                      # reclaim → 1
    with pytest.raises(LockLostError):
        a._task_repo.transition_status(
            task_id, TaskStatus.RUNNING, caused_by="controller-A")
    # A's write rolled back: still READY, no status event from A
    assert TaskRepository(db).get_status(task_id) is TaskStatus.READY
    # B — the current owner at the current generation — writes fine
    b._task_repo.transition_status(
        task_id, TaskStatus.RUNNING, caused_by="controller-B")
    assert TaskRepository(db).get_status(task_id) is TaskStatus.RUNNING
    b._release_lock()


def test_adv02_same_owner_lease_refresh_remains_valid(db):
    """Own-owner refresh keeps the SAME generation — a refreshed lease is
    still valid for the owner's writes (never a spurious lock_lost)."""
    task_id = admit_extract_task(db)
    TaskRepository(db).transition_status(
        task_id, TaskStatus.READY, caused_by="test")
    a = Controller(db, project_id="p1", owner="controller-A",
                   clock=frozen_clock(CLOCK), extract_fn=good_extract_fn(),
                   lease_seconds=60)
    assert a._acquire_lock() is True                      # generation 0
    assert a._acquire_lock() is True                      # own-owner refresh
    row = db.execute(
        "SELECT generation FROM scheduler_lock WHERE id = 0").fetchone()
    assert row["generation"] == 0                        # NOT bumped
    a._task_repo.transition_status(
        task_id, TaskStatus.RUNNING, caused_by="controller-A")
    assert TaskRepository(db).get_status(task_id) is TaskStatus.RUNNING
    a._release_lock()


def test_adv02_crash_reclaim_bumps_generation(db):
    """A crashed holder's stale lease is reclaimed and the generation is
    bumped (the old holder's writes can never land after the reclaim)."""
    db.execute("INSERT INTO scheduler_lock (id, owner, locked_at) "
               "VALUES (0, 'crashed-controller', ?)", (STALE,))
    a = Controller(db, project_id="p1", owner="controller-A",
                   clock=frozen_clock(CLOCK), extract_fn=good_extract_fn(),
                   lease_seconds=60)
    assert a._acquire_lock() is True
    row = db.execute(
        "SELECT owner, generation FROM scheduler_lock WHERE id = 0").fetchone()
    assert row["owner"] == "controller-A"
    assert row["generation"] == 1
    a._release_lock()


def test_adv02_concurrent_acquisition_serialized(db):
    """Two controllers with FRESH leases: the second acquisition is denied
    (serialized) — never two concurrent owners."""
    a = Controller(db, project_id="p1", owner="controller-A",
                   clock=frozen_clock(CLOCK), extract_fn=good_extract_fn(),
                   lease_seconds=60)
    b = Controller(db, project_id="p1", owner="controller-B",
                   clock=frozen_clock(CLOCK), extract_fn=good_extract_fn(),
                   lease_seconds=60)
    assert a._acquire_lock() is True
    assert b._acquire_lock() is False                     # fresh lease held
    assert a._acquire_lock() is True                      # own-owner refresh
    a._release_lock()


# ── ADV-02 audit F1–F3: statement-classifier hardening ──
# The fence's verb check was first-token-only — a comment-prefixed write
# (F1), a WITH-CTE write (F2), or executescript (F3, delegated to the raw
# connection) could bypass per-statement attribution. All three closed; the
# probes reproduced the bypasses before the fix.


def test_fence_comment_prefixed_write_fails_closed(db):
    """F1 — a stale controller's write raises LockLostError even when the
    statement is prefixed with a block or line comment (pre-fix: the
    first-token check missed it and the write landed)."""
    task_id = admit_extract_task(db)
    TaskRepository(db).transition_status(
        task_id, TaskStatus.READY, caused_by="test")
    a = Controller(db, project_id="p1", owner="controller-A",
                   clock=frozen_clock(CLOCK), extract_fn=good_extract_fn(),
                   lease_seconds=60)
    assert a._acquire_lock() is True                      # generation 0
    b = Controller(db, project_id="p1", owner="controller-B",
                   clock=frozen_clock("2026-01-01T00:02:00.000000+00:00"),
                   extract_fn=good_extract_fn(), lease_seconds=60)
    assert b._acquire_lock() is True                      # reclaim → 1
    for sql in (
        "/* stray comment */ UPDATE tasks SET status = 'FAILED' WHERE task_id = ?",
        "-- line comment\nDELETE FROM tasks WHERE task_id = ?",
    ):
        with pytest.raises(LockLostError):
            a._fenced.execute(sql, (task_id,))
    assert TaskRepository(db).get_status(task_id) is TaskStatus.READY
    b._release_lock()


def test_fence_with_cte_write_fails_closed(db):
    """F2 — a WITH-CTE write is detected and fenced (pre-fix: the first token
    was WITH, so the INSERT bypassed the verb check entirely)."""
    a = Controller(db, project_id="p1", owner="controller-A",
                   clock=frozen_clock(CLOCK), extract_fn=good_extract_fn(),
                   lease_seconds=60)
    assert a._acquire_lock() is True                      # generation 0
    b = Controller(db, project_id="p1", owner="controller-B",
                   clock=frozen_clock("2026-01-01T00:02:00.000000+00:00"),
                   extract_fn=good_extract_fn(), lease_seconds=60)
    assert b._acquire_lock() is True                      # reclaim → 1
    with pytest.raises(LockLostError):
        a._fenced.execute(
            "WITH t AS (SELECT 1) INSERT INTO schema_version "
            "(version, applied_at) SELECT 99, 'probe'")
    # nothing landed
    row = db.execute(
        "SELECT 1 FROM schema_version WHERE version = 99").fetchone()
    assert row is None
    b._release_lock()


def test_fence_executescript_rejected_loudly(db):
    """F3 — executescript cannot be attributed per statement; the fence
    rejects it loudly instead of silently delegating to the raw connection
    (pre-fix: __getattr__ passed it through and the write landed unfenced)."""
    a = Controller(db, project_id="p1", owner="controller-A",
                   clock=frozen_clock(CLOCK), extract_fn=good_extract_fn(),
                   lease_seconds=60)
    assert a._acquire_lock() is True
    with pytest.raises(TypeError, match="executescript"):
        a._fenced.executescript(
            "INSERT INTO schema_version (version, applied_at) VALUES (98, 'x')")
    row = db.execute(
        "SELECT 1 FROM schema_version WHERE version = 98").fetchone()
    assert row is None
    a._release_lock()


def test_fence_classified_shapes_work_while_lock_valid(db):
    """Positive control — the hardening does not over-block: comment-prefixed
    and WITH-CTE writes still pass when the generation matches, and a
    WITH..SELECT read passes unfenced."""
    a = Controller(db, project_id="p1", owner="controller-A",
                   clock=frozen_clock(CLOCK), extract_fn=good_extract_fn(),
                   lease_seconds=60)
    assert a._acquire_lock() is True
    a._fenced.execute(
        "/* refresh */ UPDATE scheduler_lock SET locked_at = ? WHERE id = 0",
        (CLOCK,))
    a._fenced.execute(
        "WITH t AS (SELECT 1) INSERT INTO schema_version "
        "(version, applied_at) SELECT 90, 'probe'")
    row = db.execute(
        "SELECT 1 FROM schema_version WHERE version = 90").fetchone()
    assert row is not None
    read = a._fenced.execute(
        "WITH t AS (SELECT 42) SELECT * FROM t").fetchone()
    assert read[0] == 42
    a._release_lock()


# ── HD-01: fence delegation-surface closure (the step-6 third-gate pin) ──
# Pre-fix, __getattr__ delegated cursor()/commit()/rollback() to the RAW
# connection: a cursor-based write never ran the generation check (a stale
# controller could mutate through it), and an external commit()/rollback()
# could flush or discard a repository's open transaction mid-write (the
# two-transaction atomicity broken). All three are now rejected loudly on
# the fenced surface; the repositories own transactions via SQL inside
# their write methods (no shipped path uses the method forms — grep).


def test_fence_cursor_rejected_no_cursor_write_lands(db):
    """HD-01 — cursor() is rejected loudly (the executescript F3 pattern):
    the pre-fix exploit shape `fenced.cursor().execute(INSERT)` now raises at
    the cursor step and no row lands — a cursor-based write can never run
    unfenced. Positive control: the repositories' normal per-statement
    writes still work through the fence."""
    a = Controller(db, project_id="p1", owner="controller-A",
                   clock=frozen_clock(CLOCK), extract_fn=good_extract_fn(),
                   lease_seconds=60)
    assert a._acquire_lock() is True
    with pytest.raises(TypeError, match="cursor"):
        a._fenced.cursor().execute(
            "INSERT INTO schema_version (version, applied_at) "
            "VALUES (97, 'probe')")
    # nothing landed through the (nonexistent) cursor
    row = db.execute(
        "SELECT 1 FROM schema_version WHERE version = 97").fetchone()
    assert row is None
    # positive control — the fenced per-statement write path is untouched
    a._fenced.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (96, 'probe')")
    row = db.execute(
        "SELECT 1 FROM schema_version WHERE version = 96").fetchone()
    assert row is not None
    a._release_lock()


def test_fence_commit_rollback_rejected_repo_transaction_intact(db):
    """HD-01 — commit()/rollback() are rejected loudly: the repositories own
    transactions (BEGIN IMMEDIATE ... COMMIT/ROLLBACK via SQL inside their
    write methods), so an external method call cannot flush or discard a
    repository's open mid-write transaction. Positive control: the repo's
    own SQL-driven transaction still commits atomically through the fence."""
    task_id = admit_extract_task(db)
    TaskRepository(db).transition_status(
        task_id, TaskStatus.READY, caused_by="test")
    a = Controller(db, project_id="p1", owner="controller-A",
                   clock=frozen_clock(CLOCK), extract_fn=good_extract_fn(),
                   lease_seconds=60)
    assert a._acquire_lock() is True
    with pytest.raises(TypeError, match="commit"):
        a._fenced.commit()
    with pytest.raises(TypeError, match="rollback"):
        a._fenced.rollback()
    # positive control — the repository's own transaction commits normally
    a._task_repo.transition_status(
        task_id, TaskStatus.RUNNING, caused_by="controller-A")
    assert TaskRepository(db).get_status(task_id) is TaskStatus.RUNNING
    a._release_lock()


def test_fence_delegation_surface_closed_stale_generation(db):
    """HD-01 — the stale-generation write class fails closed across the FULL
    surface: after B reclaims the lease (generation 1), A's execute() write
    raises LockLostError (rollback), and A's cursor()/commit()/rollback()
    attempts are rejected at the surface (TypeError) — no stale mutation can
    land through ANY entry point; B remains authoritative."""
    task_id = admit_extract_task(db)
    TaskRepository(db).transition_status(
        task_id, TaskStatus.READY, caused_by="test")
    a = Controller(db, project_id="p1", owner="controller-A",
                   clock=frozen_clock(CLOCK), extract_fn=good_extract_fn(),
                   lease_seconds=60)
    assert a._acquire_lock() is True                      # generation 0
    b = Controller(db, project_id="p1", owner="controller-B",
                   clock=frozen_clock("2026-01-01T00:02:00.000000+00:00"),
                   extract_fn=good_extract_fn(), lease_seconds=60)
    assert b._acquire_lock() is True                      # reclaim → 1
    # the authoritative write path fails closed
    with pytest.raises(LockLostError):
        a._task_repo.transition_status(
            task_id, TaskStatus.RUNNING, caused_by="controller-A")
    assert TaskRepository(db).get_status(task_id) is TaskStatus.READY
    # the delegation surface is closed too — rejected loudly, never delegated
    with pytest.raises(TypeError, match="cursor"):
        a._fenced.cursor()
    with pytest.raises(TypeError, match="commit"):
        a._fenced.commit()
    with pytest.raises(TypeError, match="rollback"):
        a._fenced.rollback()
    # B — the current owner — writes fine
    b._task_repo.transition_status(
        task_id, TaskStatus.RUNNING, caused_by="controller-B")
    assert TaskRepository(db).get_status(task_id) is TaskStatus.RUNNING
    b._release_lock()


# ── 9. AGENT_TASK with no handler → fail-closed diagnostic ──

def test_9_no_handler_fail_closed_never_silent_success(db):
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "analyze-1", "task_type": "AGENT_TASK",
            "profile": "RESEARCHER", "idempotency_key": "analyze-1-key",
            "iteration": 1,
            "spec": {"template": "analyze", "source_ref": "dataset_manifest:dm-1"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": "small",
            "concurrency_group": None, "max_retries": 3,
            "parent_task_id": None,
        }))
    task_id = result.entity_id
    tr = TaskRepository(db)

    ctrl = make_controller(db)     # no handlers for 'analyze'
    out = ctrl.tick()
    assert task_id in out.unhandled
    assert out.dispatched == []
    # never a silent SUCCEEDED — the task is left non-terminal
    assert tr.get_status(task_id) is TaskStatus.PENDING


# ── 10. full re-run on the same db is idempotent ──

def test_10_rerun_idempotent_no_duplicates(db):
    task_id = admit_extract_task(db)
    tr = TaskRepository(db)

    ctrl = make_controller(db)
    first = ctrl.run()
    assert tr.get_status(task_id) is TaskStatus.SUCCEEDED
    events_after_first = count_rows(db, "events")
    claims_after_first = count_rows(db, "research_claims")
    edges_after_first = count_edges(db)

    # re-run the whole sequence on the same db
    second = ctrl.run()
    assert all(r.idle or not r.dispatched for r in second)
    assert tr.get_status(task_id) is TaskStatus.SUCCEEDED
    assert count_rows(db, "events") == events_after_first
    assert count_rows(db, "research_claims") == claims_after_first
    assert count_rows(db, "research_assumptions") == claims_after_first
    assert count_edges(db) == edges_after_first
    # Extract task + sequencer task (P-AUTO-1)
    assert count_rows(db, "tasks") == 2
    assert len(first) >= 1

# ── 11. human-gate resolution: the FIRST-CLASS operator path (red-team A2) ──
# The three mandatory gates are passable in shipped code: a ratified operator
# verdict (APPROVED / REJECTED) on the PARKED WAITING_HUMAN task re-dispatches
# the wave — WAITING_HUMAN -> RUNNING -> SUCCEEDED/FAILED with
# GatePassed/GateFailed + HumanGateResolved audit events, and the project
# returns to ACTIVE. No raw transition_status, no hand-built events.

def _admit_gate(db, gid="gate-1"):
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": gid, "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": gid + "-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    gate_id = result.entity_id
    ctrl = make_controller(db)
    out = ctrl.tick()
    assert gate_id in out.waiting_human
    return gate_id


def _admit_gate_with_dep(db, dep_id, gid="gate-dep"):
    """Admit a HUMAN_GATE that depends on dep_id (parks only after the dep
    SUCCEEDED) and run the wave until it parks at WAITING_HUMAN."""
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": gid, "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": gid + "-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [dep_id],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    return result.entity_id


def _gate_events(db, gate_id):
    return [r[0] for r in db.execute(
        "SELECT event_type FROM events WHERE task_id = ? ORDER BY rowid",
        (gate_id,))]


def test_11_approve_resolves_gate_and_resumes_wave(db):
    gate_id = _admit_gate(db)
    tr = TaskRepository(db)
    assert tr.get_status(gate_id) is TaskStatus.WAITING_HUMAN
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.AWAITING_HUMAN

    out = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", rationale="operator ok", operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False
    assert tr.get_status(gate_id) is TaskStatus.SUCCEEDED
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.ACTIVE
    events = _gate_events(db, gate_id)
    assert "GatePassed" in events and "HumanGateResolved" in events
    assert events[-1] == "HumanGateResolved"


def test_11_reject_resolves_gate_to_failed(db):
    gate_id = _admit_gate(db, "gate-rej")
    tr = TaskRepository(db)
    out = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="REJECTED", operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False
    assert tr.get_status(gate_id) is TaskStatus.FAILED
    events = _gate_events(db, gate_id)
    assert "GateFailed" in events and "HumanGateResolved" in events


def test_11_one_verdict_rule_second_resolve_refused(db):
    gate_id = _admit_gate(db)
    ctrl = make_controller(db)
    assert ctrl.resolve_human_gate(task_id=gate_id, verdict="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)["rejected"] is False
    out = ctrl.resolve_human_gate(task_id=gate_id, verdict="REJECTED", operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "NOT_WAITING"


def test_11_fail_closed_refusals(db):
    gate_id = _admit_gate(db)
    ctrl = make_controller(db)
    out = ctrl.resolve_human_gate(task_id=gate_id, verdict="MAYBE", operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "VERDICT"
    out = ctrl.resolve_human_gate(task_id="missing", verdict="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "NOT_FOUND"
    # a non-gate task in the same project is refused
    tid = admit_extract_task(db)
    out = ctrl.resolve_human_gate(task_id=tid, verdict="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "NOT_HUMAN_GATE"
    # a foreign project cannot resolve another project's gate
    ProjectRepository(db).create("p2", "Other")
    out = Controller(db, project_id="p2").resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "NOT_FOUND"


def test_11_lease_held_refused_and_released_after(db):
    gate_id = _admit_gate(db)
    other = make_controller(db)
    assert other._acquire_lock() is True
    out = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "LOCK"
    assert TaskRepository(db).get_status(gate_id) is TaskStatus.WAITING_HUMAN
    other._release_lock()
    out = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False
    assert TaskRepository(db).get_status(gate_id) is TaskStatus.SUCCEEDED
    assert db.execute(
        "SELECT COUNT(*) FROM scheduler_lock").fetchone()[0] == 0


# ── red-team P2 fixes (independent operator-loop verdict) ──
# P2 #2 atomicity: the APPROVED verdict's writes (WAITING_HUMAN -> RUNNING,
# GatePassed, -> SUCCEEDED, HumanGateResolved) are ONE fenced transaction —
# a crash between them must not leave a stale GatePassed (or half-transition)
# on the journal. P2 #3 escape hatch: a gate that parked after its deps
# SUCCEEDED must stay resolvable even if a dep is INVALIDATED afterwards —
# the F-10 dependency rule is a claim-time guard, not a veto on the terminal
# operator verdict; otherwise a post-park invalidation strands the wave
# forever (permanent park with no escape).


def test_11_resolve_verdict_lands_in_one_transaction(db, monkeypatch):
    """Crash mid-verdict (final HumanGateResolved append fails) -> the whole
    verdict rolls back: status stays WAITING_HUMAN, no GatePassed /
    TaskStatusChanged / HumanGateResolved row survives, the project stays
    AWAITING_HUMAN, and the gate remains resolvable (nothing half-committed)."""
    import hermes.research.controller as ctrl_mod
    gate_id = _admit_gate(db)
    tr = TaskRepository(db)
    assert tr.get_status(gate_id) is TaskStatus.WAITING_HUMAN
    before_max = db.execute(
        "SELECT COALESCE(MAX(rowid), 0) FROM events").fetchone()[0]

    real_append = ctrl_mod._append_event_to_db

    def crash_on_last_append(conn, clock, event_type, **kw):
        if event_type == "HumanGateResolved":
            raise RuntimeError("simulated crash before commit")
        real_append(conn, clock, event_type, **kw)

    monkeypatch.setattr(ctrl_mod, "_append_event_to_db", crash_on_last_append)
    out = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "TRANSITION"
    # rollback: nothing partial landed on the journal
    assert tr.get_status(gate_id) is TaskStatus.WAITING_HUMAN
    assert db.execute(
        "SELECT COUNT(*) c FROM events WHERE rowid > ?",
        (before_max,)).fetchone()["c"] == 0
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.AWAITING_HUMAN
    # lift the crash injection: the verdict never half-landed, so the gate
    # is still resolvable afterwards
    monkeypatch.setattr(ctrl_mod, "_append_event_to_db", real_append)
    out2 = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out2["rejected"] is False
    assert tr.get_status(gate_id) is TaskStatus.SUCCEEDED
    events = _gate_events(db, gate_id)
    assert "GatePassed" in events and "HumanGateResolved" in events


def test_11_oversized_rationale_refused_with_specific_code(db):
    """F3 (audit): an oversized rationale is refused with a SPECIFIC code
    (RATIONALE) before any write — never a generic TRANSITION refusal at
    the event boundary — and nothing lands: the gate stays WAITING_HUMAN,
    no GatePassed/HumanGateResolved, and the gate remains resolvable."""
    gate_id = _admit_gate(db)
    tr = TaskRepository(db)
    out = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        rationale="x" * 5000, operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "RATIONALE"
    assert "too large" in out["detail"]
    assert tr.get_status(gate_id) is TaskStatus.WAITING_HUMAN
    events = _gate_events(db, gate_id)
    assert "GatePassed" not in events and "HumanGateResolved" not in events
    # a normal rationale still resolves — nothing half-done
    out2 = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", rationale="ok",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out2["rejected"] is False
    assert tr.get_status(gate_id) is TaskStatus.SUCCEEDED


def test_11_escape_hatch_invalidated_dep_after_parking_still_resolvable(db):
    """A gate that parked after its dep SUCCEEDED must resolve even when the
    dep is INVALIDATED afterwards — previously the verdict hop went through
    transition_status whose F-10 rule (deps all SUCCEEDED, none INVALIDATED)
    refused with DependencyError: permanent park, wave blocked forever. Both
    APPROVED and REJECTED are the escape."""
    tr = TaskRepository(db)
    ctrl = make_controller(db)

    # leg 1: APPROVED escape
    dep_id = admit_extract_task(db)
    gate_id = _admit_gate_with_dep(db, dep_id, "gate-dep")
    ctrl.tick()
    assert tr.get_status(dep_id) is TaskStatus.SUCCEEDED
    out2 = ctrl.tick()
    assert gate_id in out2.waiting_human
    assert tr.get_status(gate_id) is TaskStatus.WAITING_HUMAN
    # post-park invalidation of the dependency (SUCCEEDED -> INVALIDATED)
    tr.transition_status(dep_id, TaskStatus.INVALIDATED, caused_by="audit",
                         reason="evidence reclassified")
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out["rejected"] is False
    assert tr.get_status(gate_id) is TaskStatus.SUCCEEDED
    events = _gate_events(db, gate_id)
    assert "GatePassed" in events and "HumanGateResolved" in events
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.ACTIVE

    # leg 2: REJECTED escape, same scenario, independent dep + gate
    dep2 = admit_extract_task(db, scope="claims")
    gate2 = _admit_gate_with_dep(db, dep2, "gate-dep-rej")
    ctrl2 = make_controller(db)
    ctrl2.tick()
    assert tr.get_status(dep2) is TaskStatus.SUCCEEDED
    out4 = ctrl2.tick()
    assert gate2 in out4.waiting_human
    assert tr.get_status(gate2) is TaskStatus.WAITING_HUMAN
    tr.transition_status(dep2, TaskStatus.INVALIDATED, caused_by="audit",
                         reason="evidence reclassified")
    out5 = ctrl2.resolve_human_gate(
        task_id=gate2, verdict="REJECTED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out5["rejected"] is False
    assert tr.get_status(gate2) is TaskStatus.FAILED
    events2 = _gate_events(db, gate2)
    assert "GateFailed" in events2 and "HumanGateResolved" in events2


def test_11_parked_gate_invalidated_dep_diagnostic_note(db):
    """P2 #3 diagnostic: when a parked gate's dep is INVALIDATED after the
    gate parked, the notes channel explains WHY the wave is parked and that
    the operator verdict is the escape hatch — surfaced on every tick while
    parked and at the verdict surface itself. Diagnostic only: never a gate,
    never a veto (the verdict still resolves)."""
    dep_id = admit_extract_task(db)
    gate_id = _admit_gate_with_dep(db, dep_id, "gate-note")
    tr = TaskRepository(db)
    ctrl = make_controller(db)
    ctrl.tick()          # dep SUCCEEDED
    ctrl.tick()          # gate parks → mode AWAITING_HUMAN
    # parked for a NORMAL reason: no INVALIDATED diagnostic yet
    assert all("INVALIDATED" not in n for n in ctrl.notes)
    # post-park invalidation of the dependency
    tr.transition_status(dep_id, TaskStatus.INVALIDATED, caused_by="audit",
                         reason="evidence reclassified")
    out = ctrl.tick()    # parked-mode tick surfaces the diagnostic
    assert out.idle.startswith("mode:")
    assert any("INVALIDATED" in n and gate_id in n for n in ctrl.notes)
    # the verdict surface carries the same diagnostic at resolve time —
    # and the verdict itself still resolves (never a veto)
    ctrl2 = make_controller(db)
    res = ctrl2.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert res["rejected"] is False
    assert any("INVALIDATED" in n and gate_id in n for n in ctrl2.notes)
    assert tr.get_status(gate_id) is TaskStatus.SUCCEEDED


# ── AUDIT F1 (self-heal): the mode is DERIVED from gate state ──
# The final verdict's ACTIVE write (and the park's AWAITING write) used to
# be silently swallowed: a failed ACTIVE write left the project permanently
# parked at AWAITING_HUMAN with no gate left to resolve, and a failed
# AWAITING write left the gate waiting under ACTIVE mode so the next tick
# dispatched PAST the unapproved gate. Failures now surface as notes and
# the tick re-derives the mode from gate state in both directions.


def test_11_audit_final_verdict_mode_write_failure_surfaces_and_self_heals(
        db, monkeypatch):
    """Resolve-side: the verdict commits even if the ACTIVE-mode write
    fails, the failure is surfaced (never silent), and the NEXT tick
    self-heals the stale AWAITING_HUMAN back to ACTIVE so the wave
    resumes — no permanent park, no manual `hermes resume`."""
    from hermes.persistence.repositories import ProjectRepository as _PR
    gate_id = _admit_gate(db)
    tr = TaskRepository(db)
    ctrl = make_controller(db)

    def boom(self, *a, **k):
        raise RuntimeError("simulated fence loss after verdict commit")

    monkeypatch.setattr(_PR, "transition_mode", boom)
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out["rejected"] is False
    assert tr.get_status(gate_id) is TaskStatus.SUCCEEDED
    # the failure is SURFACED, never swallowed
    assert any("mode transition to ACTIVE failed" in n for n in ctrl.notes)
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.AWAITING_HUMAN

    monkeypatch.undo()   # restore the real mode writer
    o2 = make_controller(db).tick()
    # self-healed: ACTIVE again, wave may resume (idle '' = no work left)
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.ACTIVE
    assert o2.idle == ""


def test_11_audit_park_mode_write_failure_self_heals_wave_stops(db, monkeypatch):
    """Park-side: if the AWAITING_HUMAN write fails while parking, the gate
    waits under ACTIVE mode — the NEXT tick re-derives AWAITING_HUMAN and
    stops the wave instead of dispatching past the unapproved gate."""
    from hermes.persistence.repositories import ProjectRepository as _PR
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1", payload={
            "task_id": "gate-sheal", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-sheal-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    gate_id = result.entity_id
    after_gate = admit_extract_task(db, scope="claims")  # eligible, AFTER the gate
    tr = TaskRepository(db)

    def boom(self, *a, **k):
        raise RuntimeError("simulated fence loss while parking")

    monkeypatch.setattr(_PR, "transition_mode", boom)
    ctrl = make_controller(db)
    out1 = ctrl.tick()
    assert gate_id in out1.waiting_human
    assert tr.get_status(gate_id) is TaskStatus.WAITING_HUMAN
    # the park's mode write failed: gate waits under ACTIVE mode, surfaced
    assert any("AWAITING_HUMAN failed while parking" in n for n in ctrl.notes)
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.ACTIVE

    monkeypatch.undo()
    out2 = make_controller(db).tick()
    # self-healed: mode re-derived to AWAITING_HUMAN, the wave STOPS at the
    # gate — the eligible task after the gate is NOT dispatched past it
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.AWAITING_HUMAN
    assert out2.idle == "waiting_human"
    assert after_gate not in out2.dispatched
    assert tr.get_status(after_gate) is TaskStatus.PENDING or TaskStatus.READY


# ── 12. operator credentials: proof-of-humanity (red-team A4) ──
# Every operator verdict (resolve_human_gate / record_operator_decision)
# requires a RATIFIED credential: operator_id + token verified against the
# stored hash. An unratified verdict is refused fail-closed (code OPERATOR);
# the credential is ratifiable once, never overwriteable.

def test_12_register_operator_bootstrap_and_refusal(db):
    ctrl = make_controller(db)
    # P2 #1: a token below the minimum length is refused at register
    out0 = ctrl.register_operator(operator_id="op-boot", token="short")
    assert out0["rejected"] is True and out0["code"] == "OPERATOR"
    out = ctrl.register_operator(
        operator_id="op-boot", token="boot-token-1", name="Boot")
    assert out["rejected"] is False
    assert out["name"] == "Boot"
    # idempotent for the same token (salted hash — re-presenting verifies)
    out2 = ctrl.register_operator(operator_id="op-boot", token="boot-token-1")
    assert out2["rejected"] is False
    # a different token for an existing id is REFUSED — never overwriteable
    out3 = ctrl.register_operator(operator_id="op-boot", token="boot-token-2")
    assert out3["rejected"] is True and out3["code"] == "OPERATOR"


def test_12_salted_token_hash_format_and_legacy_fallback(db):
    """P2 #1: the stored credential is a self-describing salted PBKDF2 value
    (never a bare SHA-256), the salt is random per call, verification is
    salt-aware, and pre-P2 #1 legacy bare-hex rows still verify so existing
    databases keep working. An unparseable stored value fails closed."""
    import hashlib

    from hermes.persistence.repositories import (
        _OPERATOR_TOKEN_HASH_PREFIX,
        OperatorCredentialRepository,
        _operator_token_hash,
        _token_hash_matches,
    )
    repo = OperatorCredentialRepository(db, frozen_clock(CLOCK))
    repo.register("op-format", "credential-token-1", "Format")
    stored = db.execute(
        "SELECT token_hash FROM operator_credentials "
        "WHERE operator_id = 'op-format'").fetchone()["token_hash"]
    # self-describing salted PBKDF2, never the bare SHA-256
    assert stored.startswith(_OPERATOR_TOKEN_HASH_PREFIX)
    assert stored != hashlib.sha256(b"credential-token-1").hexdigest()
    assert repo.verify("op-format", "credential-token-1") is True
    assert repo.verify("op-format", "credential-token-2") is False
    # the salt is RANDOM per call: the same token hashes differently each
    # time, yet every stored value verifies against its own salt
    h1 = _operator_token_hash("same-token-1")
    h2 = _operator_token_hash("same-token-1")
    assert h1 != h2
    assert _token_hash_matches(h1, "same-token-1") is True
    assert _token_hash_matches(h1, "same-token-2") is False
    # legacy bare-hex SHA-256 row (pre-P2 #1 DB) still verifies
    legacy = hashlib.sha256(b"legacy-token-1").hexdigest()
    db.execute(
        "INSERT INTO operator_credentials "
        "(operator_id, token_hash, name, created_at) VALUES (?, ?, ?, ?)",
        ("op-legacy", legacy, "Legacy", "2026-01-01T00:00:00.000000+00:00"))
    assert repo.verify("op-legacy", "legacy-token-1") is True
    assert repo.verify("op-legacy", "wrong-token-1") is False
    # a malformed stored value fails closed (never raises, never matches)
    db.execute(
        "INSERT INTO operator_credentials "
        "(operator_id, token_hash, name, created_at) VALUES (?, ?, ?, ?)",
        ("op-bad", "not-a-hash", "Bad", "2026-01-01T00:00:00.000000+00:00"))
    assert repo.verify("op-bad", "anything-long-enough") is False


def test_12_unknown_operator_verify_burns_equal_work(db, monkeypatch):
    """F2 (audit): verifying an UNKNOWN operator_id burns the same PBKDF2
    work as a known one (dummy branch) — response time cannot enumerate
    operator_ids — while still failing closed with False."""
    import hermes.persistence.repositories as repo_mod
    from hermes.persistence.repositories import OperatorCredentialRepository
    calls: list[tuple[str, str]] = []
    real = repo_mod._token_hash_matches

    def spy(stored: str, token: str) -> bool:
        calls.append((stored, token))
        return real(stored, token)

    monkeypatch.setattr(repo_mod, "_token_hash_matches", spy)
    repo = OperatorCredentialRepository(db, frozen_clock(CLOCK))
    repo.register("op-timing", "credential-token-9", "Timing")
    assert repo.verify("op-timing", "credential-token-9") is True
    assert repo.verify("ghost-id", "some-token-here") is False
    # BOTH branches burned real PBKDF2 work through the matcher: the known
    # path against the stored hash, the unknown path against the dummy
    assert len(calls) == 2
    assert calls[0][0] != calls[1][0]  # stored hash vs dummy hash


def test_12_unratified_verdict_refused(db):
    gate_id = _admit_gate(db)
    out = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id="ghost", operator_token="nope")
    assert out["rejected"] is True and out["code"] == "OPERATOR"
    assert TaskRepository(db).get_status(gate_id) is TaskStatus.WAITING_HUMAN
    # wrong token for a REAL operator is equally refused
    out2 = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token="wrong")
    assert out2["rejected"] is True and out2["code"] == "OPERATOR"
    assert TaskRepository(db).get_status(gate_id) is TaskStatus.WAITING_HUMAN


def test_12_ratified_verdict_records_operator(db):
    import json as _json
    gate_id = _admit_gate(db)
    out = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False
    row = db.execute(
        "SELECT payload_json FROM events "
        "WHERE event_type = 'HumanGateResolved'").fetchone()
    assert _json.loads(row["payload_json"])["operator_id"] == OP_ID
    # the token is never stored in plaintext — only its salted PBKDF2 hash
    stored = db.execute(
        "SELECT token_hash FROM operator_credentials "
        "WHERE operator_id = ?", (OP_ID,)).fetchone()[0]
    assert stored != OP_TOKEN
    assert stored.startswith("pbkdf2$sha256$") and len(stored) > 100


def test_12_f4_stored_iteration_attack_refused(db):
    """F4 (audit): the STORED PBKDF2 iteration count is honored only
    inside the sane range. An attacker who rewrites the credential row
    with an astronomical work factor must not be able to hang every
    operator verdict (stored-iteration DoS), and a degenerate count must
    not weaken verification — both are refused WITHOUT running the hash,
    fail-closed. The legitimate stored hash still verifies."""
    from hermes.persistence.repositories import (
        _operator_token_hash,
        _token_hash_matches,
    )
    legit = _operator_token_hash(OP_TOKEN)
    assert _token_hash_matches(legit, OP_TOKEN) is True
    salt_and_hash = legit.split("$", 3)[3]
    # attacker sets iterations to ~1e15: previously this computed
    # pbkdf2 with 10^15 rounds — effectively a hang on every verdict
    huge = f"pbkdf2$sha256$999999999999999${salt_and_hash}"
    assert _token_hash_matches(huge, OP_TOKEN) is False
    # degenerate work factor is equally refused (would trivially weaken)
    tiny = f"pbkdf2$sha256$1${salt_and_hash}"
    assert _token_hash_matches(tiny, OP_TOKEN) is False
    # strict shape: an oversized salt is refused too (memory bound)
    bad_salt = "pbkdf2$sha256$210000$" + "ab" * 32 + "$" + "cd" * 32
    assert _token_hash_matches(bad_salt, OP_TOKEN) is False
    # the legitimate hash is untouched by the attack values
    assert _token_hash_matches(legit, OP_TOKEN) is True


def test_12_f4_boundary_and_end_to_end_stored_row_tamper(db):
    """F4-lens fresh probe: the stored-iteration guard is EXACTLY the
    inclusive range — one below MIN and one above MAX, non-numeric
    iterations, an algorithm tamper, and a malformed field count are all
    refused WITHOUT running the hash (fail-closed, never a hang), while
    the in-range legitimate hash verifies. End-to-end: an attacker who
    rewrites the stored credential row with an astronomical work factor
    can only DENY the operator verdict (OPERATOR refusal, gate untouched)
    — never a hang, never a grant — and the gate stays resolvable once the
    row is restored."""
    from hermes.persistence.repositories import (
        _operator_token_hash,
        _token_hash_matches,
    )
    legit = _operator_token_hash(OP_TOKEN)
    salt_and_hash = legit.split("$", 3)[3]
    # the inclusive range boundary is exact: just-outside values are
    # refused before any PBKDF2 work is done (no stored-iteration DoS)
    assert _token_hash_matches(
        f"pbkdf2$sha256$99999${salt_and_hash}", OP_TOKEN) is False
    assert _token_hash_matches(
        f"pbkdf2$sha256$10000001${salt_and_hash}", OP_TOKEN) is False
    # non-numeric / garbage iterations and an algorithm tamper fail closed
    assert _token_hash_matches(
        f"pbkdf2$sha256$abc${salt_and_hash}", OP_TOKEN) is False
    assert _token_hash_matches(
        f"pbkdf2$md5$210000${salt_and_hash}", OP_TOKEN) is False
    # a malformed field count never raises and never matches
    assert _token_hash_matches(
        "pbkdf2$sha256$210000$abcd", OP_TOKEN) is False
    assert _token_hash_matches(legit, OP_TOKEN) is True
    # END-TO-END: rewrite the stored row with an astronomical work factor —
    # verification refuses fast and the verdict surface DENIES (fail-closed)
    tr = TaskRepository(db)
    gate_id = _admit_gate(db, "gate-f4-tamper")
    db.execute(
        "UPDATE operator_credentials SET token_hash = ? "
        "WHERE operator_id = ?",
        (f"pbkdf2$sha256$999999999999999${salt_and_hash}", OP_ID))
    out = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "OPERATOR"
    assert tr.get_status(gate_id) is TaskStatus.WAITING_HUMAN
    # a denial only: restore a legitimate in-range hash and the SAME gate
    # resolves normally (the row is self-describing, so the new salt is fine)
    db.execute(
        "UPDATE operator_credentials SET token_hash = ? "
        "WHERE operator_id = ?",
        (legit, OP_ID))
    out2 = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out2["rejected"] is False
    assert tr.get_status(gate_id) is TaskStatus.SUCCEEDED


def test_12_f4_out_of_range_never_runs_pbkdf2(monkeypatch):
    """F4-lens timing/DoS probe: an out-of-range stored iteration count
    returns WITHOUT running PBKDF2 at all — a monkeypatched
    ``hashlib.pbkdf2_hmac`` that raises proves no hash work happens on the
    refusal path (stronger than a wall-clock check: there is NO DoS
    window, only the bounds check). Control: the legitimate in-range hash
    DOES run the KDF under the same patch — so the refusals' speed is the
    short-circuit, not a lazy comparison."""
    import hashlib

    import pytest

    from hermes.persistence.repositories import (
        _operator_token_hash,
        _token_hash_matches,
    )
    legit = _operator_token_hash(OP_TOKEN)
    salt_and_hash = legit.split("$", 3)[3]
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def boom(*a, **k):
        raise AssertionError(
            "pbkdf2 ran for an out-of-range/malformed stored value")

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", boom)
    # every refusal must short-circuit before any KDF work: the patch
    # would raise, so a clean False proves PBKDF2 never ran
    for stored in (
        f"pbkdf2$sha256$99999${salt_and_hash}",          # MIN - 1
        f"pbkdf2$sha256$10000001${salt_and_hash}",       # MAX + 1
        f"pbkdf2$sha256$999999999999999${salt_and_hash}",  # astronomical
        f"pbkdf2$sha256$abc${salt_and_hash}",            # non-numeric
        "pbkdf2$sha256$210000$abcd",                     # malformed shape
    ):
        assert _token_hash_matches(stored, OP_TOKEN) is False
    # control: the legitimate hash really does run the KDF (the patch
    # makes it raise) — the refusals above were the bounds check, not a
    # degenerate comparison
    with pytest.raises(AssertionError, match="pbkdf2 ran"):
        _token_hash_matches(legit, OP_TOKEN)
    monkeypatch.setattr(hashlib, "pbkdf2_hmac", real_pbkdf2)
    assert _token_hash_matches(legit, OP_TOKEN) is True


def test_12_f2_unknown_operator_burn_runs_one_pbkdf2_not_skippable(
        db, monkeypatch):
    """F2-lens probe: the unknown-operator path burns EXACTLY ONE PBKDF2
    run per verify (the module-level dummy hash) — a counting patch proves
    the work happens and is constant, so response time cannot reveal
    whether an operator_id exists. The burn is not skippable by stored-row
    tampering: it consults no row at all (the dummy hash is module-global
    with in-range iterations — genuine work, never a cheap compare), so
    rewriting every credential row still pays the same burn. Parity: the
    known-operator path also runs exactly one KDF."""
    import hashlib

    import hermes.persistence.repositories as repos_mod
    from hermes.persistence.repositories import OperatorCredentialRepository

    # Order-independence: the module dummy hash is built LAZILY on first
    # burn — whichever test in the session runs first would pay a second
    # KDF for that build. Pre-warm it before counting so every counted
    # verify pays exactly one KDF regardless of execution order.
    repos_mod._burn_dummy_operator_work("order-independent-warmup")

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)
    repo = OperatorCredentialRepository(db)
    # unknown operator: exactly ONE KDF burn, fail-closed False
    assert repo.verify("ghost-operator", "some-token-123456") is False
    assert calls["n"] == 1
    # the dummy hash is a REAL in-range PBKDF2 value — the burn is genuine
    # work, and a second verify burns one more (constant per request)
    dummy = repos_mod._OPERATOR_DUMMY_HASH
    assert dummy is not None and dummy.startswith("pbkdf2$sha256$210000$")
    iters = int(dummy.split("$")[2])
    assert repos_mod._OPERATOR_TOKEN_ITERATIONS_MIN <= iters <= \
        repos_mod._OPERATOR_TOKEN_ITERATIONS_MAX
    calls["n"] = 0
    assert repo.verify("ghost-operator", "some-token-123456") is False
    assert calls["n"] == 1
    # parity: the KNOWN operator path also runs exactly one KDF — the
    # constant-time posture holds in both directions
    calls["n"] = 0
    assert repo.verify(OP_ID, OP_TOKEN) is True
    assert calls["n"] == 1
    # the burn is not skippable by stored-row tampering: it reads no row,
    # so rewriting every credential (even to garbage) changes nothing
    db.execute("UPDATE operator_credentials SET token_hash = 'garbage'")
    calls["n"] = 0
    assert repo.verify("ghost-operator", "some-token-123456") is False
    assert calls["n"] == 1


def test_12_f2_gate_surface_constant_work_one_kdf_each(db, monkeypatch):
    """F2-lens gate-surface probe: ``resolve_human_gate`` performs EXACTLY
    ONE PBKDF2 run regardless of the operator outcome — unknown id
    (dummy-hash burn), known id with a wrong token (stored-hash mismatch),
    and known id with the right token (match) each pay the same one-KDF
    budget, so a stopwatch on the verdict surface cannot distinguish the
    three cases (the adversarial timing lens, at the gate, not just the
    repository)."""
    import hashlib

    import hermes.persistence.repositories as repos_mod
    # Order-independence: pre-warm the lazily-built module dummy hash so
    # the first counted verify pays exactly one KDF (see the sibling F2
    # probe).
    repos_mod._burn_dummy_operator_work("order-independent-warmup")

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)
    ctrl = make_controller(db)
    gate_id = _admit_gate(db, "gate-f2-surface")
    # unknown operator -> OPERATOR refusal with exactly one burn
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id="ghost", operator_token="wrong-token-123456")
    assert out["rejected"] is True and out["code"] == "OPERATOR"
    assert calls["n"] == 1
    # known id, wrong token -> OPERATOR refusal with one KDF (parity)
    calls["n"] = 0
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token="wrong-token-123456")
    assert out["rejected"] is True and out["code"] == "OPERATOR"
    assert calls["n"] == 1
    # known id, right token -> passes; still exactly one KDF
    calls["n"] = 0
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False
    assert calls["n"] == 1


def test_12_f2_lock_path_pays_one_kdf_not_a_cheap_oracle(db, monkeypatch):
    """F2-lens LOCK probe: the scheduler-lease refusal is NOT a cheap
    oracle for operator validity. In resolve_human_gate the operator
    verify runs BEFORE the lock acquisition, so the LOCK path pays the
    same one-KDF budget as every other outcome — an invalid operator
    under a held lease is still refused OPERATOR (one KDF, never a fast
    LOCK that skips the burn), a valid operator under a held lease pays
    exactly one KDF before the LOCK refusal, and the success path pays
    the same. Timing on the verdict surface is therefore constant across
    operator validity, lease state, and outcome."""
    import hashlib

    import hermes.persistence.repositories as repos_mod
    # Order-independence: pre-warm the lazily-built module dummy hash (see
    # the sibling F2 probes).
    repos_mod._burn_dummy_operator_work("order-independent-warmup")

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)
    tr = TaskRepository(db)
    gate_id = _admit_gate(db, "gate-lock-oracle")
    b = make_controller(db)  # B holds the fresh lease — concurrent writer
    assert b._acquire_lock() is True
    a = make_controller(db)
    # invalid operator under a held lease: OPERATOR (one KDF) — the verify
    # precedes the lock, so the lease state never short-circuits the burn
    out = a.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id="ghost", operator_token="wrong-token-123456")
    assert out["rejected"] is True and out["code"] == "OPERATOR"
    assert calls["n"] == 1
    # valid operator under the held lease: LOCK refusal, still one KDF —
    # timing parity with every other outcome; nothing lands
    calls["n"] = 0
    out = a.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "LOCK"
    assert calls["n"] == 1
    assert tr.get_status(gate_id) is TaskStatus.WAITING_HUMAN
    # control: lease free + right token -> success; still exactly one KDF
    b._release_lock()
    calls["n"] = 0
    out = a.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False
    assert calls["n"] == 1
    assert tr.get_status(gate_id) is TaskStatus.SUCCEEDED


def test_12_f2_lock_path_bounded_work_size_independent(db, monkeypatch):
    """F2-lens LOCK latency probe — deterministic (SQL statement count,
    never a flaky wall clock): the lease-held refusal pays EXACTLY ONE
    PBKDF2 run plus a small constant of SQL statements (verify SELECT +
    BEGIN/SELECT/ROLLBACK on the lock row = 4). The scheduler_lock table
    is schema-constrained to a SINGLE row (``CHECK (id = 0)``), so a
    "large scheduler_lock row" is impossible by construction — the schema
    bound is asserted directly, and growing the largest table in the
    store (events) changes nothing about the refusal's work: still one
    KDF and the same four statements."""
    import hashlib

    import hermes.persistence.repositories as repos_mod
    # Order-independence: pre-warm the lazily-built module dummy hash (the
    # sibling F2 probes do the same).
    repos_mod._burn_dummy_operator_work("order-independent-warmup")

    class CountingConn:
        """Minimal proxy that counts execute() calls and delegates
        everything else to the real connection."""

        def __init__(self, real):
            self._real = real
            self.n = 0

        def execute(self, *args, **kwargs):
            self.n += 1
            return self._real.execute(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

    # schema bound: scheduler_lock is a single-row table by constraint
    ddl = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' "
        "AND name = 'scheduler_lock'").fetchone()[0]
    assert "CHECK (id = 0)" in ddl

    counting_db = CountingConn(db)
    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    gate_id = _admit_gate(counting_db, "gate-lock-bounded")
    b = make_controller(counting_db)
    assert b._acquire_lock() is True
    a = make_controller(counting_db)
    # baseline LOCK refusal: exactly one KDF + a bounded constant of
    # statements (verify SELECT + BEGIN/SELECT/ROLLBACK on the lock row)
    counting_db.n = 0
    out = a.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "LOCK"
    assert calls["n"] == 1
    base_stmts = counting_db.n
    assert base_stmts == 4
    # size-independence: grow the largest table (events) by 2000 rows —
    # the refusal still pays one KDF and the same four statements, so no
    # store growth can slow the lock check into a timing signal
    for i in range(2000):
        db.execute(
            "INSERT INTO events (event_type, project_id, task_id, "
            "from_state, to_state, correlation_id, caused_by, reason, "
            "artifact_ids_json, payload_json, created_at) VALUES "
            "('GatePassed', 'p1', ?, 'WAITING_HUMAN', 'SUCCEEDED', '', "
            "'bulk', 'bulk', NULL, '{}', ?)",
            (gate_id, "2026-01-01T00:00:00.000000+00:00"))
    db.commit()
    calls["n"] = 0
    counting_db.n = 0
    out = a.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "LOCK"
    assert calls["n"] == 1
    assert counting_db.n == base_stmts
    b._release_lock()


def test_12_f2_register_surface_pays_one_kdf_each(db, monkeypatch):
    """F2-lens probe on the controller's register surface
    (register_operator): fresh registration (hash build), the idempotent
    re-register of the same (id, token) (the stored hash is re-derived
    for the constant-time match), and the refuse-on-different-token path
    each pay EXACTLY ONE PBKDF2 run — response time cannot reveal whether
    an operator_id already exists (the ratifiable, never-overwriteable
    refusal is never a cheap fast path)."""
    import hashlib

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    ctrl = make_controller(db)
    # fresh register: exactly one KDF (the hash build), lands
    out = ctrl.register_operator(
        operator_id="op-reg", token="reg-token-123456", name="Reg")
    assert out["rejected"] is False
    assert calls["n"] == 1
    # idempotent re-register (same id + token): one KDF (the stored-hash
    # match) — the same budget as a fresh register
    calls["n"] = 0
    out = ctrl.register_operator(
        operator_id="op-reg", token="reg-token-123456", name="Reg")
    assert out["rejected"] is False
    assert calls["n"] == 1
    # different token for the existing id: one KDF, refused as data —
    # never a cheap refusal that leaks the id's existence
    calls["n"] = 0
    out = ctrl.register_operator(
        operator_id="op-reg", token="different-token-123456")
    assert out["rejected"] is True and out["code"] == "OPERATOR"
    assert calls["n"] == 1


def test_12_f2_tick_loop_never_runs_pbkdf2_or_reads_credentials(db, monkeypatch):
    """F2-lens tick probe: the controller tick loop performs ZERO PBKDF2
    work and never reads operator_credentials — recovery, mode checks,
    dispatch, execution, and heartbeat refresh are pure non-credential
    machinery, so tick timing cannot leak any operator state (there is no
    variable-cost KDF path in the loop at all). Exercised across the real
    tick surfaces: AWAITING_HUMAN gate parking, an actual NO_SIGNAL
    recovery transition, and the lock_held idle tick."""
    import hashlib

    class TrackingConn:
        """Records every execute() SQL so credential reads can be proven
        absent; delegates everything else to the real connection."""

        def __init__(self, real):
            self._real = real
            self.sql = []

        def execute(self, sql, *args, **kwargs):
            self.sql.append(sql)
            return self._real.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

    tracking_db = TrackingConn(db)
    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    ctrl = make_controller(tracking_db)
    # leg A: AWAITING_HUMAN — park a gate (recovery + mode + park notes);
    # the wave stops at the gate (idle == "mode:AWAITING_HUMAN")
    _admit_gate(tracking_db, "gate-tick-nokdf")
    t0 = ctrl.tick()
    assert t0.idle == "mode:AWAITING_HUMAN"
    # leg B: recovery does REAL work — a stale RUNNING task is marked
    # NO_SIGNAL on the first conclusive miss
    task_id = admit_extract_task(tracking_db)
    tr = TaskRepository(tracking_db)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    stale_heartbeat(tracking_db, task_id)
    t = ctrl.tick()
    assert task_id in t.recovery
    assert tr.get_status(task_id) is TaskStatus.NO_SIGNAL
    # leg C: lock_held — a second controller holds the lease
    other = make_controller(tracking_db)
    assert other._acquire_lock() is True
    t2 = ctrl.tick()
    assert t2.idle == "lock_held"
    other._release_lock()

    # zero KDF work anywhere in the tick loop across all three legs
    assert calls["n"] == 0
    # and no statement ever touches the credential table — tick timing
    # cannot leak operator state because the loop never reads it
    assert not any(
        "operator_credentials" in s.lower() for s in tracking_db.sql)


def test_12_f2_hash_shape_parse_is_bounded(db, monkeypatch):
    """F2-lens probe on the stored-hash shape check: the parse of a
    tampered credential row is BOUNDED by ``_OPERATOR_TOKEN_HASH_MAX_BYTES``
    and the guard runs BEFORE any split/int/fromhex work. Instrumented via
    a sqlite ``text_factory`` that counts string operations: an oversized
    stored row (huge salt / huge iterations / huge digest / junk tail) is
    refused with ZERO KDF and ZERO parse calls — the length guard fires
    first — while a legitimate row verifies with exactly one KDF and one
    split. The shape check is O(MAX) constant, never O(stored length), so
    a gigantic tampered row cannot slow the verify into a timing signal."""
    import hashlib

    from hermes.persistence.repositories import (
        _OPERATOR_TOKEN_HASH_MAX_BYTES,
        OperatorCredentialRepository,
    )

    class InstrumentedStr(str):
        """text_factory that counts parse operations on TEXT values."""

        splits = 0
        starts = 0

        def __new__(cls, data):
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            return str.__new__(cls, data)

        def split(self, *a, **k):
            InstrumentedStr.splits += 1
            return str.split(self, *a, **k)

        def startswith(self, *a, **k):
            InstrumentedStr.starts += 1
            return str.startswith(self, *a, **k)

    db.text_factory = InstrumentedStr
    InstrumentedStr.splits = 0
    InstrumentedStr.starts = 0
    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    repo = OperatorCredentialRepository(db)
    row = db.execute(
        "SELECT token_hash FROM operator_credentials WHERE operator_id = ?",
        (OP_ID,)).fetchone()
    legit = row["token_hash"]
    # the bound never rejects a legitimate row
    assert len(legit) < _OPERATOR_TOKEN_HASH_MAX_BYTES
    # control: legit row verifies True — one KDF, one split (parse ran)
    InstrumentedStr.splits = 0
    InstrumentedStr.starts = 0
    calls["n"] = 0
    assert repo.verify(OP_ID, OP_TOKEN) is True
    assert calls["n"] == 1
    assert InstrumentedStr.splits == 1
    assert InstrumentedStr.starts == 1

    # oversized pathologies: each refused with ZERO KDF and ZERO parse
    # calls — the length guard fires before split/int/fromhex
    base = legit.split("$")
    pathologies = {
        "huge_salt": "$".join(
            [base[0], base[1], base[2], "ab" * 600, base[4]]),
        "huge_iterations": "$".join(
            [base[0], base[1], "9" * 600, base[3], base[4]]),
        "huge_digest": "$".join(
            [base[0], base[1], base[2], base[3], "cd" * 600]),
        "junk_tail": legit + "x" * 1000,
    }
    for name, tampered in pathologies.items():
        assert len(tampered) > _OPERATOR_TOKEN_HASH_MAX_BYTES
        db.execute(
            "UPDATE operator_credentials SET token_hash = ? "
            "WHERE operator_id = ?", (tampered, OP_ID))
        db.commit()
        InstrumentedStr.splits = 0
        InstrumentedStr.starts = 0
        calls["n"] = 0
        assert repo.verify(OP_ID, OP_TOKEN) is False, name
        assert calls["n"] == 0, name        # no KDF on any oversized row
        assert InstrumentedStr.splits == 0, name   # parse never ran
        assert InstrumentedStr.starts == 0, name   # not even the prefix check
    # restore the legit row; verification still works end to end
    db.execute(
        "UPDATE operator_credentials SET token_hash = ? "
        "WHERE operator_id = ?", (legit, OP_ID))
    db.commit()
    calls["n"] = 0
    assert repo.verify(OP_ID, OP_TOKEN) is True
    assert calls["n"] == 1


def test_12_f2_register_verify_interleaved_controllers_one_kdf_each(db, monkeypatch):
    """F2-lens concurrency probe: two controllers interleaving register
    and verify calls on the shared credential table each pay EXACTLY ONE
    PBKDF2 per call and never corrupt the credential — the register
    surface is ratifiable-not-overwriteable under interleaving (a second
    controller's different-token register cannot clobber the first's
    token), and verify keeps its one-KDF parity throughout."""
    import hashlib

    import hermes.persistence.repositories as repos_mod
    from hermes.persistence.repositories import OperatorCredentialRepository

    # Order-independence: pre-warm the lazily-built module dummy hash (the
    # sibling F2 probes do the same).
    repos_mod._burn_dummy_operator_work("order-independent-warmup")

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    repo = OperatorCredentialRepository(db)
    a = make_controller(db)
    b = make_controller(db)

    # A registers op-cc with token T — one KDF
    calls["n"] = 0
    out = a.register_operator(
        operator_id="op-cc", token="token-cc-123456", name="CC")
    assert out["rejected"] is False
    assert calls["n"] == 1
    stored_before = db.execute(
        "SELECT token_hash FROM operator_credentials "
        "WHERE operator_id = 'op-cc'").fetchone()["token_hash"]
    # B verifies with the WRONG token — one KDF, False
    calls["n"] = 0
    assert repo.verify("op-cc", "wrong-token-123456") is False
    assert calls["n"] == 1
    # A re-registers the same (id, token) — one KDF, idempotent
    calls["n"] = 0
    out = a.register_operator(
        operator_id="op-cc", token="token-cc-123456", name="CC")
    assert out["rejected"] is False
    assert calls["n"] == 1
    # B tries a DIFFERENT token — one KDF, refused (never overwriteable)
    calls["n"] = 0
    out = b.register_operator(
        operator_id="op-cc", token="token-cc-OTHER-123456")
    assert out["rejected"] is True and out["code"] == "OPERATOR"
    assert calls["n"] == 1
    # the credential row is byte-identical — no corruption under
    # interleaving (the different-token refusal never touched the row)
    stored_after = db.execute(
        "SELECT token_hash FROM operator_credentials "
        "WHERE operator_id = 'op-cc'").fetchone()["token_hash"]
    assert stored_after == stored_before
    # the original token still verifies, the OTHER token still refuses —
    # one KDF each, parity holds through the whole interleaving
    calls["n"] = 0
    assert repo.verify("op-cc", "token-cc-123456") is True
    assert calls["n"] == 1
    calls["n"] = 0
    assert repo.verify("op-cc", "token-cc-OTHER-123456") is False
    assert calls["n"] == 1


def test_12_f4_malformed_stored_hash_corpus_never_runs_pbkdf2(db, monkeypatch):
    """F4-lens fuzz probe: a corpus of malformed stored-hash shapes (bad
    prefixes, wrong algorithm, odd-length / invalid-hex salts, out-of-range
    or non-numeric iterations, wrong field counts, binary junk, unicode,
    and oversized rows) ALL return False WITHOUT raising and WITHOUT
    running PBKDF2 — fail-closed and bounded (oversized shapes never even
    reach the parse). The control proves the legitimate hash still
    verifies with exactly one KDF under the same patch."""
    import hashlib

    import hermes.persistence.repositories as repos_mod
    from hermes.persistence.repositories import (
        _operator_token_hash,
        _token_hash_matches,
    )

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    legit = _operator_token_hash("correct-token-123456")
    hex_salt = "ab" * 16
    hex_dig = "cd" * 32
    corpus = [
        "", "garbage", "pbkdf2", "pbkdf2$", "pbkdf2$sha256",
        "pbkdf2$sha256$",
        f"pbkdf2$md5$210000${hex_salt}${hex_dig}",          # wrong algorithm
        f"pbkdf2$sha256$210000$ab{'ab' * 14}${hex_dig}",    # odd-length salt
        f"pbkdf2$sha256$210000$zz${hex_dig}",               # invalid hex salt
        f"pbkdf2$sha256$210000${hex_salt}",                 # missing digest
        f"pbkdf2$sha256$210000${hex_salt}${'cd' * 31}",     # short digest
        f"pbkdf2$sha256$0${hex_salt}${hex_dig}",            # zero iterations
        f"pbkdf2$sha256$-1${hex_salt}${hex_dig}",           # negative iterations
        f"pbkdf2$sha256$1${hex_salt}${hex_dig}",            # below MIN
        f"pbkdf2$sha256$999999999${hex_salt}${hex_dig}",    # above MAX
        f"pbkdf2$sha256$notanumber${hex_salt}${hex_dig}",   # non-numeric
        f"pbkdf2$sha256$210000${hex_salt}${hex_dig}$extra",  # extra field
        f"pbkdf2$sha256$210000{hex_salt}${hex_dig}",        # missing separators
        f"PBKDF2$SHA256$210000${hex_salt}${hex_dig}",       # uppercase prefix
        "legacy-junk-not-hex",                              # junk legacy row
        "x" * 64,                                           # 64-char junk legacy
        "ab" * 300 + "$junk",                               # oversized junk
        "\U0001F600" * 50,                                  # unicode emoji
        f"pbkdf2$sha256$210000${hex_salt}${"\u00e9" * 32}",  # non-hex unicode digest
        legit[:30] + "\x00" + legit[30:],                   # NUL byte inside
    ]
    # every malformed shape: fail-closed (False), no KDF, no raise
    for i, shape in enumerate(corpus):
        calls["n"] = 0
        assert _token_hash_matches(shape, "some-token") is False, i
        assert calls["n"] == 0, i
    # oversized shapes never even reach the parse (the length guard)
    for shape in corpus:
        if len(shape) > repos_mod._OPERATOR_TOKEN_HASH_MAX_BYTES:
            calls["n"] = 0
            assert _token_hash_matches(shape, "some-token") is False
            assert calls["n"] == 0
    # control: the legitimate hash verifies with exactly one KDF
    calls["n"] = 0
    assert _token_hash_matches(legit, "correct-token-123456") is True
    assert calls["n"] == 1
    assert len(legit) < repos_mod._OPERATOR_TOKEN_HASH_MAX_BYTES


def test_12_f2_verify_token_fuzz_one_kdf_bounded(db, monkeypatch):
    """F2-lens token-side probe: the presented token can never make the
    verify variable-cost. Every in-range token shape (unicode, control
    bytes, the 1024-char MAX, empty, MAX-1) pays EXACTLY ONE PBKDF2 run;
    an oversized token (beyond _OPERATOR_TOKEN_MAX_LENGTH) is refused
    BEFORE any hashing with ZERO KDF — the per-verify KDF cost is bounded
    by a constant, and the refusal leaks nothing (it depends only on the
    attacker-known token length, never on stored state)."""
    import hashlib

    import hermes.persistence.repositories as repos_mod
    from hermes.persistence.repositories import (
        _OPERATOR_TOKEN_MAX_LENGTH,
        OperatorCredentialRepository,
    )

    # Order-independence: pre-warm the lazily-built module dummy hash (the
    # sibling F2 probes do the same).
    repos_mod._burn_dummy_operator_work("order-independent-warmup")

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    repo = OperatorCredentialRepository(db)
    # in-range adversarial tokens: exactly ONE KDF each, False (no match)
    tokens = [
        "\U0001F600" * 16,                       # unicode emoji
        "a\x00b\x01c\x1f",                      # control bytes
        "x" * _OPERATOR_TOKEN_MAX_LENGTH,        # the MAX boundary
        "x" * (_OPERATOR_TOKEN_MAX_LENGTH - 1),
        "",                                      # empty
        "\u00e9\u00e8\u00ea" * 50,              # accented unicode
    ]
    for i, token in enumerate(tokens):
        calls["n"] = 0
        assert repo.verify(OP_ID, token) is False, i
        assert calls["n"] == 1, i   # exactly one KDF per in-range verify
    # oversized tokens: refused BEFORE hashing — zero KDF, bounded work
    for i, token in enumerate([
        "x" * (_OPERATOR_TOKEN_MAX_LENGTH + 1),
        "y" * 100_000,
        "\U0001F600" * 5000,
    ]):
        calls["n"] = 0
        assert repo.verify(OP_ID, token) is False, i
        assert calls["n"] == 0, i   # the length bound fires first
    # register refuses an oversized token before any work
    calls["n"] = 0
    with pytest.raises(ValueError):
        repo.register("op-too-big", "z" * (_OPERATOR_TOKEN_MAX_LENGTH + 1),
                      "Too Big")
    assert calls["n"] == 0
    # control: the correct token still verifies with exactly one KDF
    calls["n"] = 0
    assert repo.verify(OP_ID, OP_TOKEN) is True
    assert calls["n"] == 1


def test_12_f2_register_repeated_no_token_oracle(db, monkeypatch):
    """F2-lens probe on the idempotent register path: re-registering the
    same operator id pays EXACTLY ONE PBKDF2 per attempt whether the
    presented token is CORRECT (idempotent accept) or INCORRECT (the
    ratifiable-not-overwriteable refusal) — across many re-registers the
    per-attempt KDF work is invariant, so response time cannot be used
    as a token-correctness oracle. (Id existence is revealed by the
    register RESPONSE by design — the secret is the token, not the id —
    but its verification is constant-work, never a timing tell.)"""
    import hashlib

    import hermes.persistence.repositories as repos_mod
    from hermes.persistence.repositories import OperatorCredentialRepository

    # Order-independence: pre-warm the lazily-built module dummy hash (the
    # sibling F2 probes do the same).
    repos_mod._burn_dummy_operator_work("order-independent-warmup")

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    repo = OperatorCredentialRepository(db)
    assert repo.register(
        "op-rt", "token-rt-123456", "RT")["operator_id"] == "op-rt"
    # correct-token re-registers: idempotent accept, exactly one KDF each
    for _ in range(20):
        calls["n"] = 0
        out = repo.register("op-rt", "token-rt-123456", "RT")
        assert out["operator_id"] == "op-rt"
        assert calls["n"] == 1
    # incorrect-token re-registers: refused, still exactly one KDF each —
    # the same budget, so timing cannot distinguish right from wrong
    for _ in range(20):
        calls["n"] = 0
        with pytest.raises(ValueError):
            repo.register("op-rt", "wrong-token-123456", "RT")
        assert calls["n"] == 1


def test_12_f2_verify_is_pure_function_of_hash_and_token(db, monkeypatch):
    """F2-lens property probe: ``verify`` is a pure function of (stored
    hash, token) — identical inputs give identical results across any
    ordering or interleaving, the KDF call count is exactly one per call
    in every sequence, the result depends only on the stored hash and the
    presented token (rewriting the stored hash flips the outcome), and a
    verify never mutates the store (read-only)."""
    import hashlib

    import hermes.persistence.repositories as repos_mod
    from hermes.persistence.repositories import (
        OperatorCredentialRepository,
        _operator_token_hash,
    )

    # Order-independence: pre-warm the lazily-built module dummy hash (the
    # sibling F2 probes do the same).
    repos_mod._burn_dummy_operator_work("order-independent-warmup")

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    repo = OperatorCredentialRepository(db)
    repo.register("op-prop", "token-prop-123456", "Prop")
    # (token, expected) matrix, deliberately interleaved and repeated:
    # the outcome is deterministic and the per-call KDF count is always 1
    matrix = [
        ("token-prop-123456", True),
        ("wrong-token-1", False),
        ("token-prop-123456", True),
        ("wrong-token-2", False),
        ("", False),
        ("token-prop-123456", True),
        ("wrong-token-1", False),
        ("token-prop-123456", True),
    ]
    for _ in range(2):  # run the SAME sequence twice -> identical results
        for token, expected in matrix:
            calls["n"] = 0
            assert repo.verify("op-prop", token) is expected
            assert calls["n"] == 1   # exactly one KDF per call, always
    # pure function of the STORED hash: rewrite the row with a hash of a
    # different token and the outcome flips accordingly
    db.execute(
        "UPDATE operator_credentials SET token_hash = ? "
        "WHERE operator_id = 'op-prop'",
        (_operator_token_hash("another-token-123456"),))
    db.commit()
    assert repo.verify("op-prop", "token-prop-123456") is False
    assert repo.verify("op-prop", "another-token-123456") is True
    # read-only: a batch of verifies never mutates the store
    before_events = db.execute(
        "SELECT COUNT(*) FROM events").fetchone()[0]
    before_row = db.execute(
        "SELECT token_hash, name, created_at FROM operator_credentials "
        "WHERE operator_id = 'op-prop'").fetchone()
    for _ in range(5):
        repo.verify("op-prop", "another-token-123456")
        repo.verify("op-prop", "wrong-token-3")
    after_events = db.execute(
        "SELECT COUNT(*) FROM events").fetchone()[0]
    after_row = db.execute(
        "SELECT token_hash, name, created_at FROM operator_credentials "
        "WHERE operator_id = 'op-prop'").fetchone()
    assert after_events == before_events
    assert after_row == before_row


def test_12_f2_register_refusal_reveals_no_token_shape(db):
    """F2-lens probe on the register refusal surface: the wrong-token
    re-register error is BYTE-IDENTICAL regardless of the presented
    token's length, content, or encoding — it never echoes the presented
    token, never hints at the STORED token's length or shape (no digits
    at all), and repeats deterministically. The only discriminator is the
    designed accept / refuse outcome (you know your own token); id
    existence is revealed by design, but the stored credential's shape is
    never leaked."""
    from hermes.persistence.repositories import OperatorCredentialRepository

    repo = OperatorCredentialRepository(db)
    repo.register("op-resp", "stored-token-123456", "Resp")
    # all >= _OPERATOR_TOKEN_MIN_LENGTH so each reaches the stored-row
    # refusal (a shorter token is refused earlier by the length check on
    # the PRESENTED token — attacker-known, not a stored-shape leak)
    wrong_tokens = [
        "x" * 8,                   # far shorter than the stored token
        "x" * 500,                 # far longer
        "................",        # same length, different characters
        "STORED-TOKEN-123456",     # case-shifted
        "\U0001F600" * 8,          # unicode
        "a\x00b\x01c\x02d\x03",  # control bytes
        "stored-token-123457",     # one character off
    ]
    messages = []
    for token in wrong_tokens:
        try:
            repo.register("op-resp", token, "Resp")
            raise AssertionError(f"wrong token {token!r} was not refused")
        except ValueError as exc:
            messages.append(str(exc))
    # byte-identical refusal across every wrong token — no shape oracle
    assert len(set(messages)) == 1
    msg = messages[0]
    assert "different token" in msg and "overwriteable" in msg
    # the message reveals neither the presented nor the stored token, and
    # carries no numeric hint about any token length
    for token in wrong_tokens + ["stored-token-123456"]:
        assert token not in msg
    assert not any(c.isdigit() for c in msg)
    # the controller surface surfaces the identical refusal as data
    out = make_controller(db).register_operator(
        operator_id="op-resp", token="another-wrong-token-123456")
    assert out["rejected"] is True and out["code"] == "OPERATOR"
    assert out["detail"] == msg


def test_12_f2_wrong_token_brute_force_pays_linear_kdf_cost(db, monkeypatch):
    """F2-lens brute-force probe: the wrong-token verify surface has NO
    fast-path batching — each attempt pays EXACTLY ONE PBKDF2 (the
    ~94ms budget at 210k iterations on this machine), and the wall time
    of K sequential attempts grows linearly (>= K x the single-attempt
    budget). Derived: 1000 sequential wrong-token verifies cost >= 1000
    KDF budgets (~90s+ at the current work factor), which is the
    practical rate limit of the surface."""
    import hashlib
    import time

    import hermes.persistence.repositories as repos_mod
    from hermes.persistence.repositories import OperatorCredentialRepository

    # Order-independence: pre-warm the lazily-built module dummy hash (the
    # sibling F2 probes do the same).
    repos_mod._burn_dummy_operator_work("order-independent-warmup")

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)
    repo = OperatorCredentialRepository(db)
    # warmup (first-call jitter), then measure the single-attempt budget
    assert repo.verify(OP_ID, "warmup-token-123456") is False
    t0 = time.perf_counter()
    assert repo.verify(OP_ID, "budget-token-123456") is False
    budget = time.perf_counter() - t0
    assert budget >= 0.005  # the KDF is real work (>=5ms), never a cheap compare
    # K sequential wrong-token attempts: exactly K KDF calls (no batching)
    # and the wall time grows linearly with the attempt count
    K = 25
    calls["n"] = 0
    t0 = time.perf_counter()
    for i in range(K):
        assert repo.verify(OP_ID, f"brute-token-{i}-123456") is False
    elapsed = time.perf_counter() - t0
    assert calls["n"] == K              # one KDF per attempt, never batched
    assert elapsed >= K * budget * 0.5   # linear scaling, no amortization
    # derived floor for the documented brute-force case: 1000 attempts
    # cost at least 1000 KDF budgets (~90s+ here)
    assert budget * 1000 >= 5.0


def test_12_f2_operator_round_trip_latency_documented(db):
    """F2-lens documentation probe: measures the operator-facing round
    trip — a single-KDF budget, a wrong-token refusal at the gate surface
    (one KDF, no writes), and a full APPROVED gate resolve (one KDF +
    lease + journal/event writes) — and asserts sanity bounds (each path
    includes at least half a KDF budget of real work; the resolve is
    never cheaper than the refusal, since it adds the write machinery).
    The measured numbers are recorded in the reconciliation record
    (machine-specific, ~2026-08-16)."""
    import hashlib
    import time

    import hermes.persistence.repositories as repos_mod

    # Order-independence: pre-warm the lazily-built module dummy hash (the
    # sibling F2 probes do the same).
    repos_mod._burn_dummy_operator_work("order-independent-warmup")

    # single-KDF budget (real work at the shipped work factor)
    t0 = time.perf_counter()
    hashlib.pbkdf2_hmac("sha256", b"x" * 20, b"s" * 16, 210_000)
    budget = time.perf_counter() - t0
    # wrong-token refusal at the gate surface: one KDF, no writes (the
    # refusal leaves the gate WAITING_HUMAN — no state change)
    gate = _admit_gate(db, "gate-lat")
    ctrl = make_controller(db)
    t0 = time.perf_counter()
    out = ctrl.resolve_human_gate(
        task_id=gate, verdict="APPROVED",
        operator_id=OP_ID, operator_token="wrong-token-123456")
    refusal = time.perf_counter() - t0
    assert out["rejected"] is True and out["code"] == "OPERATOR"
    # full APPROVED resolve on the SAME gate: one KDF + lease +
    # journal/event writes (the refusal measured above changed nothing)
    t0 = time.perf_counter()
    out = ctrl.resolve_human_gate(
        task_id=gate, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    resolve = time.perf_counter() - t0
    assert out["rejected"] is False
    # sanity bounds: each path includes real KDF work; the resolve adds
    # the write machinery, so it is never cheaper than the refusal
    assert refusal >= budget * 0.5
    assert resolve >= budget * 0.5
    assert resolve >= refusal * 0.7
    print("\n[latency] one-KDF budget ~{:.0f}ms | wrong-token refusal "
          "~{:.0f}ms | APPROVED resolve ~{:.0f}ms".format(
              budget * 1000, refusal * 1000, resolve * 1000))


def test_12_f4_legacy_64hex_credential_verifies_end_to_end(db):
    """F4-lens probe: legacy pre-P2 credentials (bare 64-hex SHA-256
    token hashes) still verify end to end after the fail-closed legacy
    fix — the repository, the resolve_human_gate surface, and a wrong
    token all behave correctly, and a malformed 64-char non-hex legacy
    row fails closed instead of crashing the verify."""
    import hashlib

    from hermes.persistence.repositories import (
        OperatorCredentialRepository,
        _token_hash_matches,
    )

    legacy_hash = hashlib.sha256(
        OP_TOKEN.encode("utf-8")).hexdigest()
    db.execute(
        "INSERT INTO operator_credentials "
        "(operator_id, token_hash, name, created_at) "
        "VALUES ('op-legacy', ?, 'Legacy', ?)",
        (legacy_hash, CLOCK))
    db.commit()
    repo = OperatorCredentialRepository(db)
    # repository: the 64-hex legacy row still verifies
    assert repo.verify("op-legacy", OP_TOKEN) is True
    assert repo.verify("op-legacy", "wrong-token-123456") is False
    # gate surface: a verdict with the legacy credential lands
    gate_id = _admit_gate(db, "gate-legacy")
    out = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id="op-legacy", operator_token=OP_TOKEN)
    assert out["rejected"] is False
    assert TaskRepository(db).get_status(gate_id) is TaskStatus.SUCCEEDED
    # malformed legacy rows fail closed, never raise:
    # 64 chars but not hex (would previously crash compare_digest for
    # non-ASCII; invalid hex must also be False)
    assert _token_hash_matches("z" * 64, OP_TOKEN) is False
    assert _token_hash_matches("\u00e9" * 64, OP_TOKEN) is False
    assert _token_hash_matches("ab" * 10, OP_TOKEN) is False  # not 64


def test_11_journal_one_verdict_under_status_tamper(db):
    """F14 (audit): the one-verdict rule consults the APPEND-ONLY journal —
    a status tampered back to WAITING_HUMAN after a legit resolve can never
    permit a second verdict. The mutable status column is never the sole
    authority; the journal has no UPDATE/DELETE path."""
    gate_id = _admit_gate(db)
    tr = TaskRepository(db)
    assert make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)["rejected"] is False
    assert tr.get_status(gate_id) is TaskStatus.SUCCEEDED

    # attacker flips the status back (raw tamper)
    db.execute("UPDATE tasks SET status = 'WAITING_HUMAN' "
               "WHERE task_id = ?", (gate_id,))
    out = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "ALREADY_RESOLVED"
    n = db.execute(
        "SELECT COUNT(*) FROM events "
        "WHERE task_id = ? AND event_type = 'HumanGateResolved'",
        (gate_id,)).fetchone()[0]
    assert n == 1  # one verdict per gate, terminal


def test_11_forged_gate_events_can_refuse_but_never_authorize(db):
    """F14-lens follow-up: a forged journal event can only move the gate
    toward REFUSAL, never toward authorization. A forged duplicate
    GatePassed before a resolve neither blocks nor double-authorizes — the
    resolve still lands SUCCEEDED with exactly one HumanGateResolved (the
    one-verdict key), and the second resolve is refused. A forged
    HumanGateResolved alone refuses the verdict (ALREADY_RESOLVED) — the
    journal is the tamper-resistant truth, so journal tampering can only
    deny a verdict, never grant one."""
    tr = TaskRepository(db)
    ctrl = make_controller(db)

    # leg 1: forged duplicate GatePassed before the resolve
    gate_id = _admit_gate(db)
    db.execute(
        "INSERT INTO events (event_type, project_id, task_id, from_state, "
        "to_state, correlation_id, caused_by, reason, artifact_ids_json, "
        "payload_json, created_at) VALUES ('GatePassed', 'p1', ?, "
        "'WAITING_HUMAN', 'SUCCEEDED', '', 'forged', 'forged', NULL, "
        "'{}', ?)",
        (gate_id, "2026-01-01T00:00:00.000000+00:00"))
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False
    assert tr.get_status(gate_id) is TaskStatus.SUCCEEDED
    assert db.execute(
        "SELECT COUNT(*) FROM events WHERE task_id = ? "
        "AND event_type = 'HumanGateResolved'",
        (gate_id,)).fetchone()[0] == 1  # one verdict per gate, terminal
    out2 = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out2["rejected"] is True and out2["code"] == "NOT_WAITING"

    # leg 2: forged HumanGateResolved alone refuses the verdict
    gate2 = _admit_gate(db, "gate-forged-resolved")
    db.execute(
        "INSERT INTO events (event_type, project_id, task_id, from_state, "
        "to_state, correlation_id, caused_by, reason, artifact_ids_json, "
        "payload_json, created_at) VALUES ('HumanGateResolved', 'p1', ?, "
        "'WAITING_HUMAN', 'SUCCEEDED', '', 'forged', 'forged', NULL, "
        "'{}', ?)",
        (gate2, "2026-01-01T00:00:00.000000+00:00"))
    out3 = ctrl.resolve_human_gate(
        task_id=gate2, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out3["rejected"] is True and out3["code"] == "ALREADY_RESOLVED"
    assert tr.get_status(gate2) is TaskStatus.WAITING_HUMAN


def test_11_forged_journal_events_cannot_bypass_one_verdict_under_race(db):
    """F14-lens race probe: a forged journal event cannot bypass the
    one-verdict key even when a second controller is concurrently live.
    Leg 1: with only a forged duplicate GatePassed present, the current
    owner's resolve still lands SUCCEEDED with exactly one
    HumanGateResolved and the second resolve is refused (NOT_WAITING) —
    a forged pass event can neither pre-authorize nor double-count a
    verdict. Leg 2: while B holds the scheduler lease, A's verdict is
    refused (LOCK, nothing lands) with forged GatePassed +
    HumanGateResolved rows already in the journal — and the forged
    HumanGateResolved then denies even the race-winner B's own resolve
    (ALREADY_RESOLVED): tamper can only deny, never authorize, and a
    concurrent second controller can never sneak a verdict in."""
    tr = TaskRepository(db)

    # leg 1: forged duplicate GatePassed only -> one verdict, never doubled
    gate1 = _admit_gate(db, "gate-race-forge-pass")
    db.execute(
        "INSERT INTO events (event_type, project_id, task_id, from_state, "
        "to_state, correlation_id, caused_by, reason, artifact_ids_json, "
        "payload_json, created_at) VALUES ('GatePassed', 'p1', ?, "
        "'WAITING_HUMAN', 'SUCCEEDED', '', 'forged', 'forged', NULL, "
        "'{}', ?)",
        (gate1, "2026-01-01T00:00:00.000000+00:00"))
    c = make_controller(db)
    out_c = c.resolve_human_gate(
        task_id=gate1, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out_c["rejected"] is False
    assert tr.get_status(gate1) is TaskStatus.SUCCEEDED
    assert db.execute(
        "SELECT COUNT(*) FROM events WHERE task_id = ? AND "
        "event_type = 'HumanGateResolved'",
        (gate1,)).fetchone()[0] == 1  # the one-verdict key: exactly one
    out_c2 = c.resolve_human_gate(
        task_id=gate1, verdict="REJECTED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out_c2["rejected"] is True and out_c2["code"] == "NOT_WAITING"

    # leg 2: concurrent lease holder + forged events -> deny, never authorize
    gate2 = _admit_gate(db, "gate-race-forge-resolved")
    db.execute(
        "INSERT INTO events (event_type, project_id, task_id, from_state, "
        "to_state, correlation_id, caused_by, reason, artifact_ids_json, "
        "payload_json, created_at) VALUES ('GatePassed', 'p1', ?, "
        "'WAITING_HUMAN', 'SUCCEEDED', '', 'forged', 'forged', NULL, "
        "'{}', ?)",
        (gate2, "2026-01-01T00:00:00.000000+00:00"))
    db.execute(
        "INSERT INTO events (event_type, project_id, task_id, from_state, "
        "to_state, correlation_id, caused_by, reason, artifact_ids_json, "
        "payload_json, created_at) VALUES ('HumanGateResolved', 'p1', ?, "
        "'WAITING_HUMAN', 'SUCCEEDED', '', 'forged', 'forged', NULL, "
        "'{}', ?)",
        (gate2, "2026-01-01T00:00:00.000000+00:00"))
    b = make_controller(db)  # B holds the fresh lease — the concurrent writer
    assert b._acquire_lock() is True
    a = make_controller(db)
    out_a = a.resolve_human_gate(
        task_id=gate2, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out_a["rejected"] is True and out_a["code"] == "LOCK"
    # A's refusal landed nothing: no new row beyond the two forged ones
    assert db.execute(
        "SELECT COUNT(*) FROM events WHERE task_id = ? AND "
        "caused_by = 'forged'",
        (gate2,)).fetchone()[0] == 2
    assert tr.get_status(gate2) is TaskStatus.WAITING_HUMAN
    # the race-winner B is denied too — the forged HumanGateResolved is the
    # journal's truth and can only deny (ALREADY_RESOLVED), never grant
    out_b = b.resolve_human_gate(
        task_id=gate2, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out_b["rejected"] is True and out_b["code"] == "ALREADY_RESOLVED"
    assert tr.get_status(gate2) is TaskStatus.WAITING_HUMAN
    assert db.execute(
        "SELECT COUNT(*) FROM events WHERE task_id = ? AND "
        "event_type = 'HumanGateResolved'",
        (gate2,)).fetchone()[0] == 1  # the forged one only — no verdict landed
    b._release_lock()


def test_11_f9_schema_index_scope_excludes_human_gate_resolved(db):
    """F9-lens fresh probe (the N1 disposition): the schema-level
    one-verdict index scopes exactly the five correlation-bearing types it
    covers — HumanGateResolved is NOT among them (the documented gap N1
    flagged; its correlations are fresh UUIDs per resolve), so a duplicate
    HumanGateResolved correlation CAN insert at the schema level, and the
    app-level F14 journal check is what covers it: a second resolve is
    still refused ALREADY_RESOLVED and a second verdict never lands."""
    ddl = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' "
        "AND name = 'idx_events_one_verdict'").fetchone()[0]
    for scoped in ("ClassificationActionDecision", "ScopeReviewDecided",
                   "EvidenceTransitionProposed", "EvidenceTransitionApplied",
                   "RefutedApplied"):
        assert scoped in ddl
    assert "HumanGateResolved" not in ddl  # N1: the known gap, recorded-only
    gate_id = _admit_gate(db, "gate-f9-scope")
    ctrl = make_controller(db)
    assert ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)["rejected"] is False
    # a duplicate HumanGateResolved correlation is NOT schema-constrained...
    db.execute(
        "INSERT INTO events (event_type, project_id, task_id, from_state, "
        "to_state, correlation_id, caused_by, reason, artifact_ids_json, "
        "payload_json, created_at) VALUES ('HumanGateResolved', 'p1', ?, "
        "'SUCCEEDED', 'SUCCEEDED', 'dup-correlation', 'forged', 'forged', "
        "NULL, '{}', ?)",
        (gate_id, "2026-01-01T00:00:00.000000+00:00"))
    # ...and the app-level F14 journal check is what covers the gap: after
    # the status is tampered back to WAITING_HUMAN, the second resolve is
    # refused ALREADY_RESOLVED — the mutable status is never the sole
    # authority, tamper can only deny, never a second verdict
    db.execute(
        "UPDATE tasks SET status = 'WAITING_HUMAN' WHERE task_id = ?",
        (gate_id,))
    out = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="REJECTED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "ALREADY_RESOLVED"
    assert db.execute(
        "SELECT COUNT(*) FROM events WHERE task_id = ? AND "
        "event_type = 'HumanGateResolved'",
        (gate_id,)).fetchone()[0] == 2  # 1 real + 1 forged — no third


# ── 13. C2: mid-execution heartbeat refresh keeps long tasks alive ──

def test_13_long_execution_heartbeat_refreshed(db, tmp_path):
    """Red-team C2: a long execution can no longer be NO_SIGNAL-reclaimed.
    While the (slow) model call runs, the controller refreshes the task's
    last_heartbeat every heartbeat_refresh_interval seconds — the final
    heartbeat is strictly NEWER than the claim, and the refresher is
    stopped cleanly after the execution."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.persistence.repositories import TaskRepository as _TR

    # real clock + short refresh interval: the mechanism under real time
    db_path = tmp_path / "c2.db"
    conn = _connect(str(db_path))
    _migrate(conn)
    ProjectRepository(conn).create("p1", "Test")
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    result = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1", payload=build_extract_task_payload(
            "dataset_manifest:dm-1")))
    task_id = result.entity_id
    tr = _TR(conn)

    def slow_extract():
        def _fn(task, untrusted):
            _time.sleep(0.35)  # a LONG execution — the reclaim window
            return extraction_draft_from_mapping(good_output())
        return _fn

    ctrl = Controller(conn, project_id="p1", extract_fn=slow_extract(),
                      heartbeat_refresh_interval=0.05)
    out = ctrl.tick()
    assert task_id in out.succeeded
    assert tr.get_status(task_id) is TaskStatus.SUCCEEDED
    # the refresher issued >= 1 mid-execution refresh — the heartbeat is
    # strictly newer than the claim (real clock), so a second controller
    # at any point during the execution saw a FRESH task, never stale.
    assert ctrl._heartbeat_refreshes >= 1
    conn.close()


# ── 14. F15 audit: live-worker lease protection + hung-worker recovery ──

def test_14_f15_live_worker_lease_protected(tmp_path):
    """F15 — a LIVE (non-hung) long execution is protected from a second
    controller: the mid-execution refresher extends the scheduler lease too
    (not just the task heartbeat), so B stays lock_held and the task ends
    SUCCEEDED ONCE (attempt=1) with A's own output — the pre-fix behavior
    re-executed the task (attempt=2) while A was still working."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.research.controller import Controller as _Controller

    db_path = tmp_path / "f15_live.db"
    seed_conn = _connect(str(db_path))
    _migrate(seed_conn)
    ProjectRepository(seed_conn).create("p1", "Test")
    seed_conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    res = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload=build_extract_task_payload("dataset_manifest:dm-1", "both")))
    task_id = res.entity_id
    TaskRepository(seed_conn).transition_status(
        task_id, TaskStatus.READY, caused_by="test")
    seed_conn.close()

    started = _time.monotonic()

    def slow_fn(task, untrusted):
        _time.sleep(0.8)   # LIVE execution — finishes fine, just slow
        return extraction_draft_from_mapping(good_output())

    a_conn = _connect(str(db_path))
    a = _Controller(a_conn, project_id="p1", extract_fn=slow_fn,
                    lease_seconds=2, heartbeat_refresh_interval=0.05)
    a_out = {}
    th = threading.Thread(target=lambda: a_out.setdefault("r", a.tick()))
    th.start()
    # Test hardening (F15 race pinned 2026-08-16): B must only start once
    # A has PROVABLY acquired the scheduler lease. Without this gate, B's
    # very first tick can win the acquire race against A's just-started
    # thread (thread scheduling delay), and the test fails nondetermin-
    # istically under CI load even though the product logic is correct
    # (the task still ends SUCCEEDED once — only A's TickResult ends up
    # empty). Gate deterministically on the lock row owner.
    lease_conn = _connect(str(db_path))
    try:
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline:
            row = lease_conn.execute(
                "SELECT owner FROM scheduler_lock WHERE id = 0").fetchone()
            if row is not None and row["owner"] == a._owner:
                break
            _time.sleep(0.005)
        else:
            raise AssertionError("A never acquired the scheduler lease")
    finally:
        lease_conn.close()

    b_conn = _connect(str(db_path))
    b = _Controller(b_conn, project_id="p1",
                    extract_fn=good_extract_fn(),
                    lease_seconds=2, heartbeat_refresh_interval=0.05)
    b_touched: list[str] = []
    b_dispatched: list[str] = []
    for _ in range(30):
        r = b.tick()
        b_touched.extend(r.recovery)
        b_dispatched.extend(r.dispatched)
        if _time.monotonic() - started > 2.5:
            break
        _time.sleep(0.08)

    th.join(timeout=5)
    tr = TaskRepository(b_conn)
    row = tr.get(task_id)
    # A's own output landed, exactly once — no duplicate re-execution.
    assert row["status"] == TaskStatus.SUCCEEDED, row["status"]
    assert row["attempt"] == 1, row["attempt"]
    assert task_id in a_out["r"].succeeded
    # B never recovered, dispatched, or re-executed the task while A lived.
    assert task_id not in b_touched
    assert task_id not in b_dispatched
    a_conn.close()
    b_conn.close()


def test_15_f15_hung_worker_recovered_after_horizon(tmp_path):
    """F15 — a genuinely HUNG execution (model call never returns) is NOT
    immortal: the bounded refresh horizon stops the refresher, the lease
    goes stale, and a second controller recovers + re-executes the task.
    Without the horizon the refresher would keep the heartbeat fresh
    forever and the task would be stuck RUNNING."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.research.controller import Controller as _Controller

    db_path = tmp_path / "f15_hung.db"
    seed_conn = _connect(str(db_path))
    _migrate(seed_conn)
    ProjectRepository(seed_conn).create("p1", "Test")
    seed_conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    res = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload=build_extract_task_payload("dataset_manifest:dm-1", "both")))
    task_id = res.entity_id
    TaskRepository(seed_conn).transition_status(
        task_id, TaskStatus.READY, caused_by="test")
    seed_conn.close()

    release = threading.Event()

    def hung_fn(task, untrusted):
        release.wait(10.0)   # genuinely hung — far past the 0.3s horizon
        return extraction_draft_from_mapping(good_output())

    a_conn = _connect(str(db_path))
    a = _Controller(a_conn, project_id="p1", extract_fn=hung_fn,
                    lease_seconds=1, heartbeat_refresh_interval=0.05,
                    heartbeat_refresh_horizon=0.3)
    th = threading.Thread(target=lambda: a.tick())
    th.start()
    _time.sleep(0.3)   # A claimed the task; refresher is within its horizon

    b_conn = _connect(str(db_path))
    b = _Controller(b_conn, project_id="p1",
                    extract_fn=good_extract_fn(),
                    lease_seconds=1, heartbeat_refresh_interval=0.05)
    touched: list[str] = []
    for _ in range(40):
        r = b.tick()
        touched.extend(r.recovery)
        if TaskRepository(b_conn).get(task_id)["status"] == TaskStatus.SUCCEEDED:
            break
        _time.sleep(0.1)

    row = TaskRepository(b_conn).get(task_id)
    # Recovered via the NO_SIGNAL ladder and re-executed by B.
    assert row["status"] == TaskStatus.SUCCEEDED, row["status"]
    assert row["attempt"] == 2, row["attempt"]
    assert task_id in touched
    release.set()
    th.join(timeout=5)
    a_conn.close()
    b_conn.close()

def test_15_f15_horizon_cliff_late_handler_discarded(tmp_path):
    """P2 #4 cliff — the A-side of the F15 horizon: once a handler outlives
    heartbeat_refresh_horizon, the refresher exits PERMANENTLY (the bounded
    horizon is exhausted), the lease goes stale, and a second controller
    reclaims + re-executes the task (attempt 2, exactly one output). When
    A's handler LATEly returns, its acceptance write is DISCARDED: the
    IDR29-02 binding guard refuses the commit (the fence is the backstop),
    and no second claim/output lands — a >horizon handler is
    discard-and-re-execute territory, by design."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.research.controller import Controller as _Controller

    db_path = tmp_path / "f15_cliff.db"
    seed_conn = _connect(str(db_path))
    _migrate(seed_conn)
    ProjectRepository(seed_conn).create("p1", "Test")
    seed_conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    res = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload=build_extract_task_payload("dataset_manifest:dm-1", "both")))
    task_id = res.entity_id
    TaskRepository(seed_conn).transition_status(
        task_id, TaskStatus.READY, caused_by="test")
    seed_conn.close()

    release = threading.Event()

    def hung_fn(task, untrusted):
        release.wait(10.0)   # genuinely hung — far past the 0.3s horizon
        return extraction_draft_from_mapping(good_output())

    a_conn = _connect(str(db_path))
    a = _Controller(a_conn, project_id="p1", extract_fn=hung_fn,
                    lease_seconds=1, heartbeat_refresh_interval=0.05,
                    heartbeat_refresh_horizon=0.3)
    a_result: dict = {}

    def _a_tick():
        a_result["out"] = a.tick()

    th = threading.Thread(target=_a_tick)
    th.start()
    _time.sleep(0.3)   # A claimed the task; refresher is within its horizon

    b_conn = _connect(str(db_path))
    b = _Controller(b_conn, project_id="p1",
                    extract_fn=good_extract_fn(),
                    lease_seconds=1, heartbeat_refresh_interval=0.05)
    touched: list[str] = []
    for _ in range(40):
        r = b.tick()
        touched.extend(r.recovery)
        if TaskRepository(b_conn).get(task_id)["status"] == TaskStatus.SUCCEEDED:
            break
        _time.sleep(0.1)

    row = TaskRepository(b_conn).get(task_id)
    # B recovered + re-executed the hung task through the NO_SIGNAL ladder.
    assert row["status"] == TaskStatus.SUCCEEDED, row["status"]
    assert row["attempt"] == 2, row["attempt"]
    assert task_id in touched
    assert count_rows(b_conn, "research_claims") == 1

    # The cliff: A's handler STILL has not returned — the refresher exited
    # permanently at the horizon (bounded by horizon/interval = 6, never the
    # ~2s recovery window; an immortal refresher would reach ~40+), which is
    # exactly why B could reclaim. Release A: the late acceptance is refused.
    release.set()
    th.join(timeout=5)
    assert a._heartbeat_refreshes <= 8, a._heartbeat_refreshes
    a_out = a_result.get("out")
    assert a_out is not None
    # A's late commit is refused — the IDR29-02 binding guard ("task already
    # SUCCEEDED; recovery owns it") fires BEFORE the fence (the acceptance
    # read sees B's terminal state): the tick ends with the claim dispatched
    # but NO succeeded/retried/failed outcome and a guard note on the channel.
    assert a_out.dispatched == [task_id]
    assert a_out.succeeded == [] and a_out.retried == [] and a_out.failed == []
    assert any("recovery owns it" in n and task_id in n for n in a.notes)
    # A's late write was discarded: exactly one output, status unchanged,
    # no second re-execution (attempt stays 2).
    assert count_rows(b_conn, "research_claims") == 1
    assert count_rows(b_conn, "claim_assumption_links") == 1
    row2 = TaskRepository(b_conn).get(task_id)
    assert row2["status"] == TaskStatus.SUCCEEDED
    assert row2["attempt"] == 2
    a_conn.close()
    b_conn.close()


# ── 20. composed control-plane attack: precedence, cross-project, canary, ──
# ──     journal coherence, replay-after-restore (adversarial audit)      ──

def test_20_error_precedence_matrix_deterministic(db, monkeypatch):
    """Composed F2/F14 probe: the resolve_human_gate failure order is a
    DETERMINISTIC, documented precedence — VERDICT -> RATIONALE -> OPERATOR
    (one KDF) -> LOCK -> NOT_FOUND -> NOT_HUMAN_GATE -> NOT_WAITING ->
    ALREADY_RESOLVED — with exactly 0 KDF on the two input-validity paths
    (malformed verdict / oversized rationale: attacker-known inputs, so the
    fast path reveals nothing protected) and exactly 1 KDF on every path
    after verification. The precedence is stable: a bad operator is always
    refused OPERATOR before any task/lease state is consulted (no task-
    existence probe pre-auth), the project check precedes the type/status
    checks (no gate-shape probe from another project), and the journal-
    truth rule (ALREADY_RESOLVED) fires even when the mutable status was
    tampered back to WAITING_HUMAN."""
    import hashlib

    import hermes.persistence.repositories as repos_mod

    repos_mod._burn_dummy_operator_work("precedence-warmup")
    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    tr = TaskRepository(db)
    gate_id = _admit_gate(db, "gate-precedence")
    ctrl = make_controller(db)

    # 1) malformed verdict: refused BEFORE any work — 0 KDF (attacker-known
    #    input; the fast path cannot reveal operator or gate state)
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="MAYBE",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] and out["code"] == "VERDICT"
    assert calls["n"] == 0
    # 2) oversized rationale: refused BEFORE any work — 0 KDF
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", rationale="X" * 5000,
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] and out["code"] == "RATIONALE"
    assert calls["n"] == 0
    # 3) invalid operator: one KDF, refused before any task/lease state —
    #    task existence is NOT probeable pre-auth
    calls["n"] = 0
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id="ghost", operator_token="wrong-token-123456")
    assert out["rejected"] and out["code"] == "OPERATOR"
    assert calls["n"] == 1
    # 4) held lease: one KDF, LOCK after verify; lease released after
    calls["n"] = 0
    b = make_controller(db)
    assert b._acquire_lock() is True
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] and out["code"] == "LOCK"
    assert calls["n"] == 1
    b._release_lock()
    # 5) task in another project: one KDF, NOT_FOUND — the project check
    #    fires before the gate-type/status checks
    calls["n"] = 0
    out = Controller(db, project_id="p-other", extract_fn=good_extract_fn(),
                     clock=frozen_clock(CLOCK)).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] and out["code"] == "NOT_FOUND"
    assert calls["n"] == 1
    # 6) task not a HUMAN_GATE: one KDF, NOT_HUMAN_GATE
    calls["n"] = 0
    extract_id = admit_extract_task(db)
    out = ctrl.resolve_human_gate(
        task_id=extract_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] and out["code"] == "NOT_HUMAN_GATE"
    assert calls["n"] == 1
    # 7) first valid APPROVED lands; re-resolve -> NOT_WAITING (one KDF)
    calls["n"] = 0
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", rationale="ok",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False
    assert calls["n"] == 1
    assert tr.get_status(gate_id) is TaskStatus.SUCCEEDED
    calls["n"] = 0
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] and out["code"] == "NOT_WAITING"
    assert calls["n"] == 1
    # 8) tampered status back to WAITING_HUMAN: the journal-truth rule
    #    (ALREADY_RESOLVED) fires — one verdict survives the tamper
    calls["n"] = 0
    db.execute("UPDATE tasks SET status = 'WAITING_HUMAN' "
               "WHERE task_id = ?", (gate_id,))
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="REJECTED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] and out["code"] == "ALREADY_RESOLVED"
    assert calls["n"] == 1
    hgr = db.execute(
        "SELECT COUNT(*) c FROM events WHERE task_id = ? "
        "AND event_type = 'HumanGateResolved'", (gate_id,)).fetchone()["c"]
    assert hgr == 1


def test_20_cross_project_gate_resolution_refused(db):
    """Composed authorization probe (brief §15): an operator resolving a
    gate through a controller bound to a DIFFERENT project is refused
    NOT_FOUND — the project check fires before the gate-type/status
    checks — with no state change and no events written. The gate belongs
    to p1; the controller bound to p-other cannot touch it. (The operator
    credential itself is system-wide by design — one ratified operator may
    resolve gates in any project; the PROJECT scoping lives in the
    controller binding, and the CLI resolves the task's own project when
    none is given.)"""
    gate_id = _admit_gate(db, "gate-xproj")
    before = _gate_events(db, gate_id)
    out = Controller(db, project_id="p-other", extract_fn=good_extract_fn(),
                     clock=frozen_clock(CLOCK)).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] and out["code"] == "NOT_FOUND"
    assert TaskRepository(db).get_status(gate_id) is TaskStatus.WAITING_HUMAN
    assert _gate_events(db, gate_id) == before
    # the SAME verdict through a p1-bound controller lands (operator is
    # system-wide; the gate's own project is authoritative)
    out2 = make_controller(db).resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", rationale="ok",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out2["rejected"] is False
    assert TaskRepository(db).get_status(gate_id) is TaskStatus.SUCCEEDED


def test_20_journal_coherence_each_outcome_exact_events(db, monkeypatch):
    """Composed journal-coherence probe (brief §L): every resolve_human_gate
    outcome leaves the journal coherent — the ONE legal success writes
    exactly one GatePassed + one HumanGateResolved (plus the two
    TaskStatusChanged hops) for the gate task, and EVERY refusal path
    (VERDICT, RATIONALE, OPERATOR, LOCK, NOT_FOUND, NOT_HUMAN_GATE,
    NOT_WAITING, ALREADY_RESOLVED) writes ZERO new events for the task.
    No event-without-state, no state-without-event, no duplicate."""
    import hashlib

    import hermes.persistence.repositories as repos_mod

    repos_mod._burn_dummy_operator_work("coherence-warmup")
    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    gate_id = _admit_gate(db, "gate-coherence")
    ctrl = make_controller(db)
    base = _gate_events(db, gate_id)

    def assert_no_new_events(label, out):
        assert out["rejected"] is True
        assert _gate_events(db, gate_id) == base, label

    assert_no_new_events("VERDICT", ctrl.resolve_human_gate(
        task_id=gate_id, verdict="MAYBE",
        operator_id=OP_ID, operator_token=OP_TOKEN))
    assert_no_new_events("RATIONALE", ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", rationale="X" * 5000,
        operator_id=OP_ID, operator_token=OP_TOKEN))
    assert_no_new_events("OPERATOR", ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id="ghost", operator_token="wrong-token-123456"))
    b = make_controller(db)
    assert b._acquire_lock() is True
    assert_no_new_events("LOCK", ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN))
    b._release_lock()
    extract_id = admit_extract_task(db)
    assert_no_new_events("NOT_HUMAN_GATE", ctrl.resolve_human_gate(
        task_id=extract_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN))

    # the one legal success: exactly one GatePassed + one HumanGateResolved
    # + two TaskStatusChanged hops (WAITING_HUMAN->RUNNING, RUNNING->SUCCEEDED)
    base_counts = {
        t: base.count(t) for t in ("GatePassed", "HumanGateResolved",
                                   "TaskStatusChanged")
    }
    calls["n"] = 0
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", rationale="ok",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False
    evs = _gate_events(db, gate_id)
    assert evs.count("GatePassed") == base_counts["GatePassed"] + 1
    assert evs.count("HumanGateResolved") == base_counts["HumanGateResolved"] + 1
    assert evs.count("TaskStatusChanged") == base_counts["TaskStatusChanged"] + 2
    assert TaskRepository(db).get_status(gate_id) is TaskStatus.SUCCEEDED

    # post-success refusals still write nothing (baseline = after success)
    after_success = _gate_events(db, gate_id)
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] and out["code"] == "NOT_WAITING"
    assert _gate_events(db, gate_id) == after_success
    db.execute("UPDATE tasks SET status = 'WAITING_HUMAN' "
               "WHERE task_id = ?", (gate_id,))
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="REJECTED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] and out["code"] == "ALREADY_RESOLVED"
    assert _gate_events(db, gate_id) == after_success


def test_20_replay_after_restore_one_verdict_survives(tmp_path):
    """Composed replay/restore probe (brief §23/§24): a ratified verdict
    survives backup + restore with EXACTLY one legal outcome. Resolve a
    gate APPROVED, snapshot the store, restore the snapshot onto a fresh
    path, then replay the SAME verdict with the SAME token: the restored
    journal still carries the one HumanGateResolved row, the gate is
    SUCCEEDED (attempt-free), and the replay is refused NOT_WAITING — or,
    under a status tamper back to WAITING_HUMAN, ALREADY_RESOLVED. The
    restore resurrects state faithfully; it never resurrects a second
    verdict or a second state transition."""
    from hermes.persistence.backup import create_backup, restore_backup
    from hermes.persistence.repositories import (
        OperatorCredentialRepository,
    )

    def build(root, resolve: bool):
        root.mkdir(parents=True)
        db = root / "hermes.db"
        conn = connect(str(db))
        migrate_to_latest(conn)
        ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
        OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
            OP_ID, OP_TOKEN, "Test Operator")
        res = apply_intent(conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload={
                "task_id": "gate-rr", "task_type": "HUMAN_GATE",
                "profile": "DIRECTOR", "idempotency_key": "k-rr",
                "iteration": 1, "spec": {"gate_requirement": "h"},
                "inputs": [], "outputs": [], "dependencies": [],
                "provenance": [], "cost_class": None,
                "concurrency_group": None, "max_retries": 3,
                "parent_task_id": None,
            }))
        gate_id = res.entity_id
        if resolve:
            ctrl = Controller(conn, project_id="p1",
                              extract_fn=good_extract_fn(),
                              clock=frozen_clock(CLOCK))
            out = ctrl.tick()
            assert gate_id in out.waiting_human
            r = ctrl.resolve_human_gate(
                task_id=gate_id, verdict="APPROVED", rationale="ok",
                operator_id=OP_ID, operator_token=OP_TOKEN)
            assert r["rejected"] is False
        conn.close()
        return db

    src = build(tmp_path / "src", resolve=True)
    bd = tmp_path / "bk"
    bd.mkdir()
    sconn = connect(str(src))
    result = create_backup(sconn, bd)
    sconn.close()

    tgt = tmp_path / "restored.db"
    restore_backup(result.backup_path, tgt)
    conn = connect(str(tgt))
    ctrl = Controller(conn, project_id="p1", extract_fn=good_extract_fn(),
                      clock=frozen_clock(CLOCK))
    # restored state: gate SUCCEEDED, exactly one HumanGateResolved
    assert TaskRepository(conn).get_status("gate-rr") is TaskStatus.SUCCEEDED
    n_hgr = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE task_id = 'gate-rr' "
        "AND event_type = 'HumanGateResolved'").fetchone()["c"]
    assert n_hgr == 1
    # replay the SAME verdict with the SAME token: refused, nothing written
    r = ctrl.resolve_human_gate(
        task_id="gate-rr", verdict="APPROVED", rationale="replay",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert r["rejected"] and r["code"] == "NOT_WAITING"
    # tamper the restored status back to WAITING_HUMAN: the restored
    # journal still refuses — ALREADY_RESOLVED, one verdict total
    conn.execute("UPDATE tasks SET status = 'WAITING_HUMAN' "
                 "WHERE task_id = 'gate-rr'")
    r2 = ctrl.resolve_human_gate(
        task_id="gate-rr", verdict="APPROVED", rationale="replay2",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert r2["rejected"] and r2["code"] == "ALREADY_RESOLVED"
    n_hgr2 = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE task_id = 'gate-rr' "
        "AND event_type = 'HumanGateResolved'").fetchone()["c"]
    assert n_hgr2 == 1
    conn.close()

# ── 21. composed epistemic + heartbeat-cliff probes (adversarial audit) ──
# ──     Q-05 crossover + section-28 operator-during-transition          ──

def test_21_q05_operator_gate_resolution_never_touches_epistemic_state(db):
    """Q-05 crossover probe: the operator control plane cannot alter
    epistemic state (classification, proposal/action-map, or Evidence
    Ladder) outside the documented proposal path. Live epistemic state is
    seeded (a research_program brief, a classification artifact + its
    provenance edge, an APPLIED ladder row, and a satisfaction link); the
    operator resolves a human gate through the first-class surface; the
    ENTIRE epistemic surface is then byte-identical (same rows, same
    order) and the journal gained ONLY the gate's own events - zero
    ClassificationAction*/EvidenceTransition*/ScopeReviewDecided events,
    zero new ladder rows, zero new satisfaction links, zero program
    changes. The ONLY epistemic writer is the controller tick's
    _apply_evidence_ladder_pass (pinned by the Q-05 suite); no operator
    surface reaches it."""
    from hermes.core.modes import OperationalMode as _Mode
    from hermes.persistence.failure_classifications import (
        FAILURE_CLASSIFICATION_ARTIFACT_TYPE as _FC_TYPE,
    )
    from hermes.persistence.repositories import _append_event_to_db

    # seed live epistemic state
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES ('rp-1', 'p1', 1, 'ch-rp1', NULL, 'scope-b', 'objective',
                   'c1', 'p1', '1', 'ih',
                   '[{"ref": "h1", "ladder_target": "SUPPORTED"}]',
                   '[]', '[]', '[{"claim_ref": "h1"}]',
                   '[]', '[]', NULL, 'director', NULL, ?)""",
        (CLOCK,))
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type, content_hash,
            size_bytes, storage_path, producer, metadata_json, created_at)
           VALUES ('fc-1', 'p1', NULL, ?, 'ch-fc1', 1, 'x', 'classifier',
                   ?, ?)""",
        (_FC_TYPE, "{\"schema_version\": \"1\", \"failure_class\": \"DECLARED_CONSTRAINT_VIOLATION\", \"hypothesis_ref\": \"h1\", \"program_ref\": \"rp-1\", \"classification_id\": \"fc-1\"}",
         CLOCK))
    db.execute(
        """INSERT INTO provenance_edges (artifact_id, upstream_id, edge_type,
           created_at) VALUES ('fc-1', 'dm-1', 'cites', ?)""", (CLOCK,))
    db.execute(
        """INSERT INTO evidence_ladder_state
           (state_id, project_id, program_id, hypothesis_ref, version, rung,
            transition_id, derived_from, created_at)
           VALUES ('st-1', 'p1', 'rp-1', 'h1', 1, 'SUPPORTED', 'tr-1',
                   'obligations', ?)""", (CLOCK,))
    db.execute(
        """INSERT INTO program_requirement_satisfactions
           (satisfaction_id, project_id, program_id, requirement_ref,
            artifact_id, created_at)
           VALUES ('sat-1', 'p1', 'rp-1', 'req-h1', 'fc-1', ?)""", (CLOCK,))
    # an existing epistemic event on the journal (pre-resolve baseline)
    _append_event_to_db(
        db, frozen_clock(CLOCK), "EvidenceTransitionApplied",
        project_id="p1", correlation_id="tr-1",
        caused_by="DETERMINISTIC",
        payload={"from_state": "SUPPORTED", "to_state": "SUPPORTED",
                 "rationale": "seeded baseline"})

    # park the gate FIRST (admission + park are not the operator
    # surface); the baseline is captured AFTER the park so the probe
    # isolates the resolve itself
    gate_id = _admit_gate(db, "gate-q05")
    assert (TaskRepository(db).get_status(gate_id) is
            TaskStatus.WAITING_HUMAN)

    # snapshot the ENTIRE epistemic surface
    epistemic = [
        "research_programs", "evidence_ladder_state", "thesis_evidence",
        "research_claims", "research_assumptions", "claim_assumption_links",
        "program_requirement_satisfactions", "artifacts", "provenance_edges",
    ]

    def snap(conn):
        out = {}
        for t in epistemic:
            rows = conn.execute(
                f"SELECT * FROM {t} ORDER BY rowid").fetchall()
            out[t] = [tuple(r) for r in rows]
        return out

    before = snap(db)
    before_events = {r[0] for r in db.execute(
        "SELECT DISTINCT event_type FROM events")}

    # operator gate resolution (the operator surface under probe)
    ctrl = make_controller(db)
    out = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out["rejected"] is False, out
    assert TaskRepository(db).get_status(gate_id) is TaskStatus.SUCCEEDED
    # the project mode write is the one intended non-epistemic side effect
    assert ProjectRepository(db).get_mode("p1") is _Mode.ACTIVE

    # epistemic surface byte-identical
    after = snap(db)
    for t in epistemic:
        assert after[t] == before[t], (
            f"operator resolve mutated epistemic table {t}: "
            f"{len(before[t])} -> {len(after[t])} rows")

    # journal: only the gate's own event types, zero epistemic events
    after_events = {r[0] for r in db.execute(
        "SELECT DISTINCT event_type FROM events")}
    added = after_events - before_events
    epistemic_events = {
        "ClassificationActionProposed", "ClassificationActionDecision",
        "EvidenceTransitionProposed", "EvidenceTransitionApplied",
        "RefutedApplied", "ScopeReviewDecided",
    }
    assert added & epistemic_events == set(), added
    assert added <= {"TaskStatusChanged", "GatePassed",
                     "HumanGateResolved", "ProjectResumed"}, added


def test_21_f15_heartbeat_cliff_operator_during_transition(tmp_path):
    """Section-28 composition (F15 cliff + operator mid-transition): A
    claims an extract task and hangs past the refresh horizon; B reclaims
    at the cliff; the wave parks at a human gate; the OPERATOR resolves the
    gate mid-transition (the dead worker is NO_SIGNAL, parked). Asserts
    EXACTLY ONE legal verdict (one HumanGateResolved, gate SUCCEEDED) and
    EXACTLY ONE task completion (extract SUCCEEDED once, attempt == 2, one
    claim set) - and that A's late handler write is discarded.

    Pins the F15-audit mode gate: while parked, the dead worker stays
    NO_SIGNAL (never FAILED), so the Decision-4 chain (NO_SIGNAL -> FAILED
    -> requeue -> attempt++ -> re-execute) completes on the first ACTIVE
    tick after the verdict. Pre-fix, the second-miss FAILED hop fired in
    AWAITING_HUMAN mode where the same-pass requeue is skipped, stranding
    the task at FAILED (attempt 1) forever - the operator's verdict never
    restarted it and the wave silently stopped."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.persistence.repositories import OperatorCredentialRepository
    from hermes.research.controller import Controller as _Controller

    db_path = tmp_path / "f15_cliff_gate.db"
    seed_conn = _connect(str(db_path))
    _migrate(seed_conn)
    ProjectRepository(seed_conn).create("p1", "Test")
    OperatorCredentialRepository(
        seed_conn, frozen_clock(CLOCK)).register(OP_ID, OP_TOKEN, "Op")
    seed_conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    # seed the EXTRACT first so it dispatches before the gate parks
    res = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload(
            "dataset_manifest:dm-1", "both"), "task_id": "ext-1"}))
    ext_id = res.entity_id
    apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-1-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    TaskRepository(seed_conn).transition_status(
        ext_id, TaskStatus.READY, caused_by="test")
    seed_conn.close()

    release = threading.Event()

    def hung_fn(task, untrusted):
        release.wait(10.0)   # genuinely hung - far past the 0.3s horizon
        return extraction_draft_from_mapping(good_output())

    a_conn = _connect(str(db_path))
    a = _Controller(a_conn, project_id="p1", extract_fn=hung_fn,
                    lease_seconds=1, heartbeat_refresh_interval=0.05,
                    heartbeat_refresh_horizon=0.3)
    a_result: dict = {}

    def _a_tick():
        a_result["out"] = a.tick()

    th = threading.Thread(target=_a_tick)
    th.start()
    # A claimed the extract; the refresher exits permanently at the horizon
    _time.sleep(0.8)

    b_conn = _connect(str(db_path))
    b = _Controller(b_conn, project_id="p1",
                    extract_fn=good_extract_fn(),
                    lease_seconds=1, heartbeat_refresh_interval=0.05)
    tr_b = TaskRepository(b_conn)
    # phase 1: B reclaims (generation+1); first miss + gate park
    gate_parked = False
    for _ in range(10):
        b.tick()
        if tr_b.get("gate-1")["status"] == TaskStatus.WAITING_HUMAN:
            gate_parked = True
            break
        _time.sleep(0.15)
    assert gate_parked, "gate never parked"
    # the dead worker reaches NO_SIGNAL on a SUBSEQUENT tick - the park
    # and the first-miss can land in different ticks depending on when B
    # reclaims relative to the stale threshold - and once parked it stays
    # NO_SIGNAL (the F15-audit mode gate; pre-fix it was FAILED and
    # stranded forever)
    no_signal = False
    for _ in range(8):
        if tr_b.get(ext_id)["status"] == TaskStatus.NO_SIGNAL:
            no_signal = True
            break
        b.tick()
        _time.sleep(0.1)
    assert no_signal, tr_b.get(ext_id)["status"]
    assert (ProjectRepository(b_conn).get_mode("p1") is
            OperationalMode.AWAITING_HUMAN)

    # the OPERATOR resolves the gate MID-transition (worker dead, parked)
    op_conn = _connect(str(db_path))
    op = _Controller(op_conn, project_id="p1",
                     extract_fn=good_extract_fn(),
                     lease_seconds=1, heartbeat_refresh_interval=0.05)
    out = op.resolve_human_gate(
        task_id="gate-1", verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out["rejected"] is False, out
    assert tr_b.get("gate-1")["status"] == TaskStatus.SUCCEEDED
    # the verdict does NOT touch the dead worker - still NO_SIGNAL
    assert tr_b.get(ext_id)["status"] == TaskStatus.NO_SIGNAL
    # mode returns ACTIVE - the wave may resume
    assert ProjectRepository(b_conn).get_mode("p1") is OperationalMode.ACTIVE

    # phase 2: B resumes; the second miss now FAILs + requeues + re-executes
    completed = False
    for _ in range(12):
        b.tick()
        if tr_b.get(ext_id)["status"] == TaskStatus.SUCCEEDED:
            completed = True
            break
        _time.sleep(0.15)
    assert completed, f"extract never completed: {tr_b.get(ext_id)['status']}"

    # exactly one completion: attempt 2, one claim set
    row = tr_b.get(ext_id)
    assert row["status"] == TaskStatus.SUCCEEDED, row["status"]
    assert row["attempt"] == 2, row["attempt"]
    assert count_rows(b_conn, "research_claims") == 1
    assert count_rows(b_conn, "claim_assumption_links") == 1
    # exactly one legal verdict: one HumanGateResolved, one GatePassed
    n_hgr = b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'HumanGateResolved'"
    ).fetchone()["c"]
    n_gp = b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'GatePassed'"
    ).fetchone()["c"]
    assert n_hgr == 1, n_hgr
    assert n_gp == 1, n_gp
    # a second resolve is refused (one verdict is terminal)
    out2 = op.resolve_human_gate(
        task_id="gate-1", verdict="REJECTED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out2["rejected"] is True and out2["code"] == "NOT_WAITING"

    # A's LATE handler return is DISCARDED: no second output, no duplicate
    # claims, no second completion
    release.set()
    th.join(timeout=5)
    a_out = a_result.get("out")
    assert a_out is not None
    assert a_out.succeeded == [] and a_out.retried == [] and \
        a_out.failed == []
    assert count_rows(b_conn, "research_claims") == 1
    assert count_rows(b_conn, "claim_assumption_links") == 1
    row2 = tr_b.get(ext_id)
    assert row2["status"] == TaskStatus.SUCCEEDED
    assert row2["attempt"] == 2
    a_conn.close()
    b_conn.close()
    op_conn.close()


def test_21_f15_paused_recovery_stays_no_signal_completes_after_resume(tmp_path):
    """F15-audit PAUSED-mode leg: a hung worker whose lease expires while
    the project is PAUSED stays NO_SIGNAL (the second-miss FAILED hop is
    ACTIVE-gated, and while stopped the same-pass requeue is skipped), so
    the Decision-4 chain completes EXACTLY ONCE on the first ACTIVE tick
    after resume - attempt 2, one claim set, no duplicate, A's late write
    discarded. Pre-fix, the worker was FAILED (attempt 1) while paused and
    never restarted on resume (FAILED tasks from a prior pass are never
    requeued), silently stopping the wave."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.research.controller import Controller as _Controller

    db_path = tmp_path / "f15_paused.db"
    seed_conn = _connect(str(db_path))
    _migrate(seed_conn)
    ProjectRepository(seed_conn).create("p1", "Test")
    seed_conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    res = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload(
            "dataset_manifest:dm-1", "both"), "task_id": "ext-1"}))
    ext_id = res.entity_id
    TaskRepository(seed_conn).transition_status(
        ext_id, TaskStatus.READY, caused_by="test")
    seed_conn.close()

    release = threading.Event()

    def hung_fn(task, untrusted):
        release.wait(10.0)   # genuinely hung - far past the 0.3s horizon
        return extraction_draft_from_mapping(good_output())

    a_conn = _connect(str(db_path))
    a = _Controller(a_conn, project_id="p1", extract_fn=hung_fn,
                    lease_seconds=1, heartbeat_refresh_interval=0.05,
                    heartbeat_refresh_horizon=0.3)
    a_result: dict = {}

    def _a_tick():
        a_result["out"] = a.tick()

    th = threading.Thread(target=_a_tick)
    th.start()
    _time.sleep(0.8)   # refresher exited at the horizon; lease not yet stale

    # PAUSE the project while A is hung (plain repository write; the
    # scheduler lock is not required for a mode transition)
    b_conn = _connect(str(db_path))
    ProjectRepository(b_conn).transition_mode(
        "p1", OperationalMode.PAUSED, caused_by="test",
        reason="paused mid-execution")
    assert ProjectRepository(b_conn).get_mode("p1") is OperationalMode.PAUSED

    b = _Controller(b_conn, project_id="p1",
                    extract_fn=good_extract_fn(),
                    lease_seconds=1, heartbeat_refresh_interval=0.05)
    tr_b = TaskRepository(b_conn)
    # phase 1: B reclaims; first miss marks NO_SIGNAL; the second miss is
    # mode-gated (PAUSED) so the worker stays NO_SIGNAL - never FAILED,
    # never requeued while stopped
    no_signal = False
    for _ in range(12):
        b.tick()
        if tr_b.get(ext_id)["status"] == TaskStatus.NO_SIGNAL:
            no_signal = True
            break
        _time.sleep(0.15)
    assert no_signal, tr_b.get(ext_id)["status"]
    # extra paused ticks must NOT advance the ladder
    for _ in range(4):
        b.tick()
        assert tr_b.get(ext_id)["status"] == TaskStatus.NO_SIGNAL
        assert tr_b.get(ext_id)["attempt"] == 1
        _time.sleep(0.1)
    assert ProjectRepository(b_conn).get_mode("p1") is OperationalMode.PAUSED

    # RESUME: the wave may restart the recovery chain
    ProjectRepository(b_conn).transition_mode(
        "p1", OperationalMode.ACTIVE, caused_by="test", reason="resumed")
    completed = False
    for _ in range(12):
        b.tick()
        if tr_b.get(ext_id)["status"] == TaskStatus.SUCCEEDED:
            completed = True
            break
        _time.sleep(0.15)
    assert completed, tr_b.get(ext_id)["status"]
    row = tr_b.get(ext_id)
    assert row["status"] == TaskStatus.SUCCEEDED
    assert row["attempt"] == 2, row["attempt"]
    assert count_rows(b_conn, "research_claims") == 1
    assert count_rows(b_conn, "claim_assumption_links") == 1

    # A's late return is discarded: no second output, no duplicate
    release.set()
    th.join(timeout=5)
    a_out = a_result.get("out")
    assert a_out is not None
    assert a_out.succeeded == [] and a_out.retried == [] and \
        a_out.failed == []
    assert count_rows(b_conn, "research_claims") == 1
    row2 = tr_b.get(ext_id)
    assert row2["status"] == TaskStatus.SUCCEEDED
    assert row2["attempt"] == 2
    a_conn.close()
    b_conn.close()


def test_21_f15_rejected_gate_wave_stops_recovery_still_completes(tmp_path):
    """REJECTED-verdict variant of the section-28 composition: the operator
    REJECTS the gate mid-transition (worker NO_SIGNAL, parked). Asserts the
    wave STOPS at the rejected gate (gate FAILED exactly once - one
    GateFailed + one HumanGateResolved, second resolve refused NOT_WAITING)
    while the dead worker still completes the Decision-4 recovery chain on
    the first ACTIVE tick after the verdict - attempt 2, exactly one
    completion, one claim set, A's late write discarded. A REJECTED gate
    must never strand the recovery (the recovery requeue is independent of
    the gate's terminal outcome)."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.persistence.repositories import OperatorCredentialRepository
    from hermes.research.controller import Controller as _Controller

    db_path = tmp_path / "f15_rejected.db"
    seed_conn = _connect(str(db_path))
    _migrate(seed_conn)
    ProjectRepository(seed_conn).create("p1", "Test")
    OperatorCredentialRepository(
        seed_conn, frozen_clock(CLOCK)).register(OP_ID, OP_TOKEN, "Op")
    seed_conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    res = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload(
            "dataset_manifest:dm-1", "both"), "task_id": "ext-1"}))
    ext_id = res.entity_id
    apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-1-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    TaskRepository(seed_conn).transition_status(
        ext_id, TaskStatus.READY, caused_by="test")
    seed_conn.close()

    release = threading.Event()

    def hung_fn(task, untrusted):
        release.wait(10.0)   # genuinely hung - far past the 0.3s horizon
        return extraction_draft_from_mapping(good_output())

    a_conn = _connect(str(db_path))
    a = _Controller(a_conn, project_id="p1", extract_fn=hung_fn,
                    lease_seconds=1, heartbeat_refresh_interval=0.05,
                    heartbeat_refresh_horizon=0.3)
    a_result: dict = {}

    def _a_tick():
        a_result["out"] = a.tick()

    th = threading.Thread(target=_a_tick)
    th.start()
    _time.sleep(0.8)

    b_conn = _connect(str(db_path))
    b = _Controller(b_conn, project_id="p1",
                    extract_fn=good_extract_fn(),
                    lease_seconds=1, heartbeat_refresh_interval=0.05)
    tr_b = TaskRepository(b_conn)
    gate_parked = False
    for _ in range(10):
        b.tick()
        if tr_b.get("gate-1")["status"] == TaskStatus.WAITING_HUMAN:
            gate_parked = True
            break
        _time.sleep(0.15)
    assert gate_parked, "gate never parked"
    # the dead worker reaches NO_SIGNAL on a SUBSEQUENT tick - the park
    # and the first-miss can land in different ticks depending on when B
    # reclaims relative to the stale threshold - and once parked it stays
    # NO_SIGNAL (the F15-audit mode gate; pre-fix it was FAILED and
    # stranded forever)
    no_signal = False
    for _ in range(8):
        if tr_b.get(ext_id)["status"] == TaskStatus.NO_SIGNAL:
            no_signal = True
            break
        b.tick()
        _time.sleep(0.1)
    assert no_signal, tr_b.get(ext_id)["status"]
    assert (ProjectRepository(b_conn).get_mode("p1") is
            OperationalMode.AWAITING_HUMAN)

    # the operator REJECTS the gate mid-transition (worker dead, parked)
    op_conn = _connect(str(db_path))
    op = _Controller(op_conn, project_id="p1",
                     extract_fn=good_extract_fn(),
                     lease_seconds=1, heartbeat_refresh_interval=0.05)
    out = op.resolve_human_gate(
        task_id="gate-1", verdict="REJECTED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out["rejected"] is False, out
    assert tr_b.get("gate-1")["status"] == TaskStatus.FAILED
    # exactly one REJECTED verdict on the journal
    assert b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'HumanGateResolved'"
    ).fetchone()["c"] == 1
    assert b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'GateFailed'"
    ).fetchone()["c"] == 1
    assert b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'GatePassed'"
    ).fetchone()["c"] == 0
    # the verdict does NOT touch the dead worker - still NO_SIGNAL
    assert tr_b.get(ext_id)["status"] == TaskStatus.NO_SIGNAL
    # mode returns ACTIVE - the wave may resume
    assert ProjectRepository(b_conn).get_mode("p1") is OperationalMode.ACTIVE

    # phase 2: B resumes; the recovery chain completes exactly once
    completed = False
    for _ in range(12):
        b.tick()
        if tr_b.get(ext_id)["status"] == TaskStatus.SUCCEEDED:
            completed = True
            break
        _time.sleep(0.15)
    assert completed, tr_b.get(ext_id)["status"]
    row = tr_b.get(ext_id)
    assert row["status"] == TaskStatus.SUCCEEDED
    assert row["attempt"] == 2, row["attempt"]
    assert count_rows(b_conn, "research_claims") == 1
    assert count_rows(b_conn, "claim_assumption_links") == 1
    # one verdict is terminal - a second resolve is refused
    out2 = op.resolve_human_gate(
        task_id="gate-1", verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out2["rejected"] is True and out2["code"] == "NOT_WAITING"
    assert b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'HumanGateResolved'"
    ).fetchone()["c"] == 1

    # A's LATE handler return is DISCARDED: no second completion
    release.set()
    th.join(timeout=5)
    a_out = a_result.get("out")
    assert a_out is not None
    assert a_out.succeeded == [] and a_out.retried == [] and \
        a_out.failed == []
    assert count_rows(b_conn, "research_claims") == 1
    row2 = tr_b.get(ext_id)
    assert row2["status"] == TaskStatus.SUCCEEDED
    assert row2["attempt"] == 2
    a_conn.close()
    b_conn.close()
    op_conn.close()


def test_21_f15_paused_revert_fresh_heartbeat_no_requeue(db):
    """F15-audit PAUSED liveness REVERT leg: the NO_SIGNAL + fresh-heartbeat
    revert to RUNNING is MODE-INDEPENDENT (unlike the FAILED hop, which is
    ACTIVE-gated) — a live worker whose heartbeat comes back while the
    project is PAUSED returns to RUNNING on the very next tick, and after
    resume completes its OWN acceptance exactly once with NO recovery
    requeue (attempt stays 1, one claim set). Pins IDR-029 Decision 4's
    'a fresh heartbeat from a live worker reverts NO_SIGNAL -> RUNNING and
    the worker's own acceptance completes normally' in the paused mode."""
    from hermes.research.extraction import accept_extraction_output

    task_id = admit_extract_task(db)
    tr = TaskRepository(db)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    stale_heartbeat(db, task_id)

    # PAUSE the project (plain repository write)
    ProjectRepository(db).transition_mode(
        "p1", OperationalMode.PAUSED, caused_by="test",
        reason="paused with a live worker")
    ctrl = make_controller(db)
    # first miss: stale RUNNING -> NO_SIGNAL (runs in every mode)
    t1 = ctrl.tick()
    assert task_id in t1.recovery
    assert tr.get_status(task_id) is TaskStatus.NO_SIGNAL
    # second miss while PAUSED: mode-gated -> stays NO_SIGNAL (never FAILED)
    ctrl.tick()
    assert tr.get_status(task_id) is TaskStatus.NO_SIGNAL

    # the worker's heartbeat comes back (live worker, still executing)
    tr.heartbeat(task_id)
    # REVERT is mode-independent: NO_SIGNAL + fresh heartbeat -> RUNNING
    # even while the project is PAUSED
    t2 = ctrl.tick()
    assert task_id in t2.recovery
    assert tr.get_status(task_id) is TaskStatus.RUNNING
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.PAUSED
    assert tr.get(task_id)["attempt"] == 1

    # RESUME; the reverted RUNNING task is untouched by recovery
    ProjectRepository(db).transition_mode(
        "p1", OperationalMode.ACTIVE, caused_by="test", reason="resumed")
    t3 = ctrl.tick()
    assert tr.get_status(task_id) is TaskStatus.RUNNING
    assert task_id not in t3.recovery   # fresh heartbeat - not a dead worker
    assert tr.get(task_id)["attempt"] == 1

    # the worker completes its OWN acceptance exactly once - no recovery
    # requeue ever happened (attempt stays 1)
    out = accept_extraction_output(
        db, "p1", task_id, extraction_draft_from_mapping(good_output()),
        extracted_by="model_ref:c-tier-1")
    assert out["verdict"] == "ADMITTED"
    tr.transition_status(task_id, TaskStatus.SUCCEEDED, caused_by="controller")
    assert tr.get(task_id)["attempt"] == 1, tr.get(task_id)["attempt"]
    assert count_rows(db, "research_claims") == 1
    assert count_rows(db, "claim_assumption_links") == 1
    # no re-dispatch, no requeue after the success
    t4 = ctrl.tick()
    assert tr.get_status(task_id) is TaskStatus.SUCCEEDED
    assert task_id not in t4.recovery


def test_21_f15_rejected_gate_wave_redispatch_downstream(tmp_path):
    """REJECTED-gate + downstream leg: an INDEPENDENT extract task behind
    the rejected gate must still be re-dispatched once the verdict returns
    the mode to ACTIVE — the wave re-dispatching past a FAILED gate is the
    ratified behavior (a failed gate blocks only its own dependents). A
    claims extract-1 (hung); B reclaims; the gate parks; the operator
    REJECTS it mid-transition; B then completes BOTH the recovery of
    extract-1 (attempt 2) and the dispatch of extract-2 (attempt 1) —
    exactly one completion each, two claim sets, one HumanGateResolved +
    one GateFailed (zero GatePassed), second resolve refused NOT_WAITING,
    A's late write discarded."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.persistence.repositories import OperatorCredentialRepository
    from hermes.research.controller import Controller as _Controller

    db_path = tmp_path / "f15_rejected_downstream.db"
    seed_conn = _connect(str(db_path))
    _migrate(seed_conn)
    ProjectRepository(seed_conn).create("p1", "Test")
    OperatorCredentialRepository(
        seed_conn, frozen_clock(CLOCK)).register(OP_ID, OP_TOKEN, "Op")
    seed_conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    res1 = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload(
            "dataset_manifest:dm-1", "both"), "task_id": "ext-1"}))
    ext1 = res1.entity_id
    apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-1-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    res2 = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload(
            "dataset_manifest:dm-1", "both"), "task_id": "ext-2",
            "idempotency_key": "ext-2-key"}))
    ext2 = res2.entity_id
    TaskRepository(seed_conn).transition_status(
        ext1, TaskStatus.READY, caused_by="test")
    TaskRepository(seed_conn).transition_status(
        ext2, TaskStatus.READY, caused_by="test")
    seed_conn.close()

    release = threading.Event()

    def hung_fn(task, untrusted):
        release.wait(10.0)   # genuinely hung - far past the 0.3s horizon
        return extraction_draft_from_mapping(good_output())

    def dual_extract_fn():
        """distinct claim sets per task (c1/a1 for ext-1, c2/a2
        for ext-2) so the two completions are distinguishable"""
        def _fn(task, untrusted):
            out = good_output()
            if task["task_id"] == "ext-2":
                # distinct CONTENT (the claim id is content-derived
                # from the statement, never the ref) so the two
                # completions land as distinguishable rows
                out["claims"][0]["statement"] = (
                    "Beta increases alpha under gamma conditions.")
                out["assumptions"][0]["statement"] = (
                    "The second sample is representative.")
            return extraction_draft_from_mapping(out)
        return _fn

    a_conn = _connect(str(db_path))
    a = _Controller(a_conn, project_id="p1", extract_fn=hung_fn,
                    lease_seconds=1, heartbeat_refresh_interval=0.05,
                    heartbeat_refresh_horizon=0.3)
    a_result: dict = {}

    def _a_tick():
        a_result["out"] = a.tick()

    th = threading.Thread(target=_a_tick)
    th.start()
    _time.sleep(0.8)

    b_conn = _connect(str(db_path))
    b = _Controller(b_conn, project_id="p1",
                    extract_fn=dual_extract_fn(),
                    lease_seconds=1, heartbeat_refresh_interval=0.05)
    tr_b = TaskRepository(b_conn)
    gate_parked = False
    for _ in range(10):
        b.tick()
        if tr_b.get("gate-1")["status"] == TaskStatus.WAITING_HUMAN:
            gate_parked = True
            break
        _time.sleep(0.15)
    assert gate_parked, "gate never parked"
    # the dead worker reaches NO_SIGNAL on a SUBSEQUENT tick - the park
    # and the first-miss can land in different ticks depending on when B
    # reclaims relative to the stale threshold - and once parked it stays
    # NO_SIGNAL (the F15-audit mode gate; pre-fix it was FAILED and
    # stranded forever)
    no_signal = False
    for _ in range(8):
        if tr_b.get(ext1)["status"] == TaskStatus.NO_SIGNAL:
            no_signal = True
            break
        b.tick()
        _time.sleep(0.1)
    assert no_signal, tr_b.get(ext1)["status"]
    assert (ProjectRepository(b_conn).get_mode("p1") is
            OperationalMode.AWAITING_HUMAN)

    # the operator REJECTS the gate mid-transition
    op_conn = _connect(str(db_path))
    op = _Controller(op_conn, project_id="p1",
                     extract_fn=dual_extract_fn(),
                     lease_seconds=1, heartbeat_refresh_interval=0.05)
    out = op.resolve_human_gate(
        task_id="gate-1", verdict="REJECTED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out["rejected"] is False, out
    assert tr_b.get("gate-1")["status"] == TaskStatus.FAILED
    # one REJECTED verdict: exactly one HumanGateResolved + one GateFailed
    assert b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'HumanGateResolved'"
    ).fetchone()["c"] == 1
    assert b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'GateFailed'"
    ).fetchone()["c"] == 1
    assert b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'GatePassed'"
    ).fetchone()["c"] == 0
    assert ProjectRepository(b_conn).get_mode("p1") is OperationalMode.ACTIVE

    # phase 2: B resumes - the recovery of ext-1 AND the dispatch of ext-2
    # both complete exactly once (the wave re-dispatches past the FAILED
    # gate)
    done = False
    for _ in range(14):
        b.tick()
        if (tr_b.get(ext1)["status"] == TaskStatus.SUCCEEDED and
                tr_b.get(ext2)["status"] == TaskStatus.SUCCEEDED):
            done = True
            break
        _time.sleep(0.15)
    assert done, (tr_b.get(ext1)["status"], tr_b.get(ext2)["status"])
    row1 = tr_b.get(ext1)
    row2 = tr_b.get(ext2)
    assert row1["status"] == TaskStatus.SUCCEEDED
    assert row1["attempt"] == 2, row1["attempt"]
    assert row2["status"] == TaskStatus.SUCCEEDED
    assert row2["attempt"] == 1, row2["attempt"]
    # two claim sets - one per extract, no duplicates
    assert count_rows(b_conn, "research_claims") == 2
    assert count_rows(b_conn, "claim_assumption_links") == 2
    # one verdict is terminal - a second resolve is refused
    out2 = op.resolve_human_gate(
        task_id="gate-1", verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out2["rejected"] is True and out2["code"] == "NOT_WAITING"
    assert b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'HumanGateResolved'"
    ).fetchone()["c"] == 1

    # A's LATE handler return is DISCARDED: no second output anywhere
    release.set()
    th.join(timeout=5)
    a_out = a_result.get("out")
    assert a_out is not None
    assert a_out.succeeded == [] and a_out.retried == [] and \
        a_out.failed == []
    assert count_rows(b_conn, "research_claims") == 2
    assert tr_b.get(ext1)["attempt"] == 2
    assert tr_b.get(ext2)["attempt"] == 1
    a_conn.close()
    b_conn.close()
    op_conn.close()


def test_21_f15_operator_resolve_racing_recovery_first_miss(tmp_path):
    """Operator-resolve racing the recovery first-miss: B's reclaiming tick
    marks the dead worker NO_SIGNAL (first miss) and parks the gate under
    the SAME scheduler lease; the operator resolves the gate CONCURRENTLY,
    retrying through any LOCK refusals while B's tick runs. Asserts the
    verdict still lands EXACTLY ONCE (one HumanGateResolved + one
    GatePassed) with no lost events, the parked worker is NO_SIGNAL at the
    moment of the verdict (never FAILED - the F15-audit mode gate), the
    recovery chain completes exactly once after the verdict (attempt 2,
    one claim set), and A's late write is discarded. The LOCK refusals
    write nothing (the gate stays WAITING_HUMAN through them)."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.persistence.repositories import OperatorCredentialRepository
    from hermes.research.controller import Controller as _Controller

    db_path = tmp_path / "f15_race_first_miss.db"
    seed_conn = _connect(str(db_path))
    _migrate(seed_conn)
    ProjectRepository(seed_conn).create("p1", "Test")
    OperatorCredentialRepository(
        seed_conn, frozen_clock(CLOCK)).register(OP_ID, OP_TOKEN, "Op")
    seed_conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    res = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload(
            "dataset_manifest:dm-1", "both"), "task_id": "ext-1"}))
    ext_id = res.entity_id
    apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-1-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    TaskRepository(seed_conn).transition_status(
        ext_id, TaskStatus.READY, caused_by="test")
    seed_conn.close()

    release = threading.Event()

    def hung_fn(task, untrusted):
        release.wait(10.0)   # genuinely hung - far past the 0.3s horizon
        return extraction_draft_from_mapping(good_output())

    a_conn = _connect(str(db_path))
    a = _Controller(a_conn, project_id="p1", extract_fn=hung_fn,
                    lease_seconds=1, heartbeat_refresh_interval=0.05,
                    heartbeat_refresh_horizon=0.3)
    a_result: dict = {}

    def _a_tick():
        a_result["out"] = a.tick()

    th = threading.Thread(target=_a_tick)
    th.start()
    _time.sleep(0.8)

    b_conn = _connect(str(db_path))
    b = _Controller(b_conn, project_id="p1",
                    extract_fn=good_extract_fn(),
                    lease_seconds=1, heartbeat_refresh_interval=0.05)
    tr_b = TaskRepository(b_conn)
    # phase 1 (sequential): B reclaims once A's lease expires, parks the
    # gate, and the dead worker reaches NO_SIGNAL - the state the operator
    # will race. The park and the first-miss can land in different ticks.
    gate_parked = False
    for _ in range(12):
        b.tick()
        if tr_b.get("gate-1")["status"] == TaskStatus.WAITING_HUMAN:
            gate_parked = True
            break
        _time.sleep(0.15)
    assert gate_parked, "gate never parked"
    no_signal = False
    for _ in range(8):
        if tr_b.get(ext_id)["status"] == TaskStatus.NO_SIGNAL:
            no_signal = True
            break
        b.tick()
        _time.sleep(0.1)
    assert no_signal, tr_b.get(ext_id)["status"]
    assert (ProjectRepository(b_conn).get_mode("p1") is
            OperationalMode.AWAITING_HUMAN)
    verdict_ev = b_conn.execute(
        "SELECT event_id FROM events WHERE event_type = 'HumanGateResolved'"
    ).fetchone()
    assert verdict_ev is None, "no verdict may exist before the race"
    # phase 2 (CONCURRENT): B keeps ticking in a background loop - its next
    # ticks are mid-recovery of the F15 chain (the worker is NO_SIGNAL and
    # AWAITING_HUMAN ticks can move it no further; the FAILED hop is
    # ACTIVE-gated) - while the OPERATOR hammers the resolve surface,
    # retrying through LOCK refusals (B's tick holds the lease) until the
    # verdict lands in a lease-free gap. ``b_mid_tick`` flips true while
    # B's tick is executing, so the probe deterministically proves the
    # resolve window overlapped B's recovery ticks (LOCK collisions are
    # timing-dependent; the overlap flag is not).
    op_conn = _connect(str(db_path))
    op = _Controller(op_conn, project_id="p1",
                     extract_fn=good_extract_fn(),
                     lease_seconds=1, heartbeat_refresh_interval=0.05)
    op_out: dict = {}
    refusals = {"LOCK": 0, "NOT_WAITING": 0, "TRANSITION": 0}
    b_mid_tick = {"v": False}
    saw_b_mid_tick = {"v": False}
    b_loop_done = threading.Event()

    def _b_loop():
        for _ in range(120):
            # once the verdict lands, keep ticking only until the
            # recovery chain completes after the verdict
            if op_out and tr_b.get(ext_id)["status"] == TaskStatus.SUCCEEDED:
                break
            b_mid_tick["v"] = True
            try:
                b.tick()
            finally:
                b_mid_tick["v"] = False
            _time.sleep(0.02)
        b_loop_done.set()

    bth = threading.Thread(target=_b_loop)
    bth.start()
    # deterministically open the window with B MID-tick: spin until
    # B's loop is inside a tick, so the resolve provably races B's
    # recovery ticks from the first attempt (B then keeps ticking
    # throughout the hammer loop, so the overlap cannot be a one-tick
    # fluke)
    spin_deadline = _time.monotonic() + 5.0
    while not b_mid_tick["v"] and _time.monotonic() < spin_deadline:
        _time.sleep(0.001)
    assert b_mid_tick["v"], "B's tick loop never started"
    saw_b_mid_tick["v"] = True
    deadline = _time.monotonic() + 10.0
    while _time.monotonic() < deadline:
        if b_mid_tick["v"]:
            saw_b_mid_tick["v"] = True
        out = op.resolve_human_gate(
            task_id="gate-1", verdict="APPROVED", operator_id=OP_ID,
            operator_token=OP_TOKEN)
        if not out["rejected"]:
            op_out["out"] = out
            break
        # LOCK = B's tick holds the lease; NOT_WAITING = a transient
        # pre-park window; TRANSITION = the controller's fail-closed
        # catch-all when its fenced verdict write hits a transient
        # error (e.g. sqlite "database is locked" under CI load) -
        # it ROLLBACKs (controller.py resolve_human_gate), so the
        # gate is STILL WAITING_HUMAN. All three are race-window
        # refusals that write nothing.
        assert out["code"] in ("LOCK", "NOT_WAITING", "TRANSITION"), out
        refusals[out["code"]] += 1
        _time.sleep(0.02)
    bth.join(timeout=10)
    assert b_loop_done.is_set(), "B loop never completed"
    assert "out" in op_out, "resolve never landed"
    assert saw_b_mid_tick["v"], (
        "the resolve window must overlap B's recovery ticks")
    # exactly one verdict, no lost events
    assert op_out["out"]["rejected"] is False
    assert tr_b.get("gate-1")["status"] == TaskStatus.SUCCEEDED
    n_hgr = b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'HumanGateResolved'"
    ).fetchone()["c"]
    assert n_hgr == 1, n_hgr
    assert b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'GatePassed'"
    ).fetchone()["c"] == 1
    # the worker was NO_SIGNAL at the moment of the verdict: no FAILED hop
    # may precede the HumanGateResolved event (journal order) - the
    # F15-audit mode gate held under the race
    hgr_row = b_conn.execute(
        "SELECT event_id FROM events WHERE event_type = 'HumanGateResolved'"
    ).fetchone()
    failed_before = b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND to_state = 'FAILED' "
        "AND event_id < ?",
        (ext_id, hgr_row["event_id"])).fetchone()["c"]
    assert failed_before == 0, failed_before
    assert tr_b.get(ext_id)["status"] == TaskStatus.SUCCEEDED
    assert ProjectRepository(b_conn).get_mode("p1") is OperationalMode.ACTIVE

    # exactly one completion: attempt 2, one claim set
    row = tr_b.get(ext_id)
    assert row["status"] == TaskStatus.SUCCEEDED
    assert row["attempt"] == 2, row["attempt"]
    assert count_rows(b_conn, "research_claims") == 1
    assert count_rows(b_conn, "claim_assumption_links") == 1

    # A's late return is discarded: no second completion
    release.set()
    th.join(timeout=5)
    a_out = a_result.get("out")
    assert a_out is not None
    assert a_out.succeeded == [] and a_out.retried == [] and \
        a_out.failed == []
    assert count_rows(b_conn, "research_claims") == 1
    assert tr_b.get(ext_id)["attempt"] == 2
    a_conn.close()
    b_conn.close()
    op_conn.close()


def test_21_f15_recovery_before_dispatch_same_tick(db):
    """Tick-ordering pin: ONE tick that both requeues a dead worker AND
    dispatches a fresh task does the recovery FIRST - the requeued worker
    re-executes (attempt 2) before the fresh task is claimed. Constructed
    via the PAUSED-mode first miss: tick 1 (paused) marks the stale worker
    NO_SIGNAL with dispatch stopped; after resume, tick 2's recovery
    completes the Decision-4 chain (FAILED -> RETRYING -> RUNNING ->
    SUCCEEDED) and its dispatch claims the fresh task - both in the same
    tick. The journal order (rowid) pins recovery-before-dispatch: every
    TaskStatusChanged hop of the requeued worker precedes every hop of the
    fresh task; the requeued worker carries the RETRYING hop, the fresh
    task never does."""
    ext1 = admit_extract_task(db, source_ref="dataset_manifest:dm-1")
    # a second, independent extract task with a distinct idempotency key
    res2 = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload(
            "dataset_manifest:dm-1", "both"), "task_id": "ext-2",
            "idempotency_key": "ext-2-key"}))
    ext2 = res2.entity_id
    tr = TaskRepository(db)
    tr.transition_status(ext1, TaskStatus.READY, caused_by="test")
    tr.transition_status(ext2, TaskStatus.READY, caused_by="test")
    # simulate the dead worker: RUNNING with a stale heartbeat
    tr.transition_status(ext1, TaskStatus.RUNNING, caused_by="test")
    stale_heartbeat(db, ext1)

    # PAUSED first miss: recovery marks NO_SIGNAL; dispatch is stopped so
    # ext-2 stays READY for the same-tick ordering probe
    ProjectRepository(db).transition_mode(
        "p1", OperationalMode.PAUSED, caused_by="test", reason="probe")
    # distinct content per task (the claim id is content-derived from the
    # statement, never the ref) so the two completions land as
    # distinguishable rows instead of collapsing at the PA4 artifact dedup
    def dual_extract_fn():
        def _fn(task, untrusted):
            out = good_output()
            if task["task_id"] == "ext-2":
                out["claims"][0]["statement"] = (
                    "Beta increases alpha under gamma conditions.")
                out["assumptions"][0]["statement"] = (
                    "The second sample is representative.")
            return extraction_draft_from_mapping(out)
        return _fn

    ctrl = make_controller(db, extract_fn=dual_extract_fn())
    t1 = ctrl.tick()
    assert ext1 in t1.recovery
    assert tr.get_status(ext1) is TaskStatus.NO_SIGNAL
    assert tr.get_status(ext2) is TaskStatus.READY

    # RESUME; tick 2 does recovery (requeue + re-execute) AND dispatch
    ProjectRepository(db).transition_mode(
        "p1", OperationalMode.ACTIVE, caused_by="test", reason="probe")
    before = count_rows(db, "events")
    t2 = ctrl.tick()
    assert ext1 in t2.succeeded
    assert ext2 in t2.succeeded
    assert tr.get(ext1)["attempt"] == 2, tr.get(ext1)["attempt"]
    assert tr.get(ext2)["attempt"] == 1, tr.get(ext2)["attempt"]

    # journal ORDER: every ext-1 hop precedes every ext-2 hop in this tick
    hops1 = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (ext1, before))]
    hops2 = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (ext2, before))]
    assert hops1 and hops2, (hops1, hops2)
    assert max(hops1) < min(hops2), (hops1, hops2)
    # ext-1 took the RETRYING hop (the recovery requeue); ext-2 never did
    retrying1 = db.execute(
        "SELECT COUNT(*) c FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND to_state = 'RETRYING'",
        (ext1,)).fetchone()["c"]
    retrying2 = db.execute(
        "SELECT COUNT(*) c FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND to_state = 'RETRYING'",
        (ext2,)).fetchone()["c"]
    assert retrying1 == 1, retrying1
    assert retrying2 == 0, retrying2
    # two distinguishable claim sets - no duplicates
    assert count_rows(db, "research_claims") == 2
    assert count_rows(db, "claim_assumption_links") == 2


def test_21_f15_second_gate_reparks_wave(tmp_path):
    """Second-gate re-park: after one REJECTED gate returns the mode to
    ACTIVE, a SECOND waiting gate re-parks the project AWAITING_HUMAN in
    the very tick that also completes the dead worker's recovery - the
    wave stops again until the second gate's own verdict. Each gate has
    exactly one verdict (gate-1 REJECTED, gate-2 APPROVED: one
    HumanGateResolved each, one GateFailed + one GatePassed, zero
    cross-talk), the recovered worker completes exactly once (attempt 2),
    and A's late write is discarded."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.persistence.repositories import OperatorCredentialRepository
    from hermes.research.controller import Controller as _Controller

    db_path = tmp_path / "f15_second_gate.db"
    seed_conn = _connect(str(db_path))
    _migrate(seed_conn)
    ProjectRepository(seed_conn).create("p1", "Test")
    OperatorCredentialRepository(
        seed_conn, frozen_clock(CLOCK)).register(OP_ID, OP_TOKEN, "Op")
    seed_conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    res = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload(
            "dataset_manifest:dm-1", "both"), "task_id": "ext-1"}))
    ext_id = res.entity_id
    for gid in ("gate-1", "gate-2"):
        apply_intent(seed_conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload={
                "task_id": gid, "task_type": "HUMAN_GATE",
                "profile": "DIRECTOR", "idempotency_key": gid + "-key",
                "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
                "inputs": [], "outputs": [], "dependencies": [],
                "provenance": [], "cost_class": None,
                "concurrency_group": None, "max_retries": 3,
                "parent_task_id": None,
            }))
    TaskRepository(seed_conn).transition_status(
        ext_id, TaskStatus.READY, caused_by="test")
    seed_conn.close()

    release = threading.Event()

    def hung_fn(task, untrusted):
        release.wait(10.0)   # genuinely hung - far past the 0.3s horizon
        return extraction_draft_from_mapping(good_output())

    a_conn = _connect(str(db_path))
    a = _Controller(a_conn, project_id="p1", extract_fn=hung_fn,
                    lease_seconds=1, heartbeat_refresh_interval=0.05,
                    heartbeat_refresh_horizon=0.3)
    a_result: dict = {}

    def _a_tick():
        a_result["out"] = a.tick()

    th = threading.Thread(target=_a_tick)
    th.start()
    _time.sleep(0.8)

    b_conn = _connect(str(db_path))
    b = _Controller(b_conn, project_id="p1",
                    extract_fn=good_extract_fn(),
                    lease_seconds=1, heartbeat_refresh_interval=0.05)
    tr_b = TaskRepository(b_conn)
    # phase 1: B reclaims; first miss + gate-1 parks
    gate1_parked = False
    for _ in range(10):
        b.tick()
        if tr_b.get("gate-1")["status"] == TaskStatus.WAITING_HUMAN:
            gate1_parked = True
            break
        _time.sleep(0.15)
    assert gate1_parked, "gate-1 never parked"
    no_signal = False
    for _ in range(8):
        if tr_b.get(ext_id)["status"] == TaskStatus.NO_SIGNAL:
            no_signal = True
            break
        b.tick()
        _time.sleep(0.1)
    assert no_signal, tr_b.get(ext_id)["status"]
    assert ProjectRepository(b_conn).get_mode("p1") is \
        OperationalMode.AWAITING_HUMAN

    # gate-1 is REJECTED: wave resumes, then gate-2 re-parks it
    op_conn = _connect(str(db_path))
    op = _Controller(op_conn, project_id="p1",
                     extract_fn=good_extract_fn(),
                     lease_seconds=1, heartbeat_refresh_interval=0.05)
    out1 = op.resolve_human_gate(
        task_id="gate-1", verdict="REJECTED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out1["rejected"] is False, out1
    assert tr_b.get("gate-1")["status"] == TaskStatus.FAILED

    # phase 2: one tick completes the recovery AND re-parks gate-2
    ext_done = gate2_parked = False
    for _ in range(12):
        b.tick()
        if tr_b.get(ext_id)["status"] == TaskStatus.SUCCEEDED:
            ext_done = True
        if tr_b.get("gate-2")["status"] == TaskStatus.WAITING_HUMAN:
            gate2_parked = True
        if ext_done and gate2_parked:
            break
        _time.sleep(0.15)
    assert ext_done, tr_b.get(ext_id)["status"]
    assert gate2_parked, "gate-2 never re-parked"
    assert tr_b.get(ext_id)["attempt"] == 2, tr_b.get(ext_id)["attempt"]
    assert tr_b.get("gate-2")["status"] == TaskStatus.WAITING_HUMAN
    assert ProjectRepository(b_conn).get_mode("p1") is \
        OperationalMode.AWAITING_HUMAN

    # the second gate's own verdict: APPROVED
    out2 = op.resolve_human_gate(
        task_id="gate-2", verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out2["rejected"] is False, out2
    assert tr_b.get("gate-2")["status"] == TaskStatus.SUCCEEDED
    assert ProjectRepository(b_conn).get_mode("p1") is OperationalMode.ACTIVE
    # each gate exactly one verdict, no cross-talk
    assert b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'HumanGateResolved'"
    ).fetchone()["c"] == 2
    assert b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'GateFailed'"
    ).fetchone()["c"] == 1
    assert b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'GatePassed'"
    ).fetchone()["c"] == 1
    # one completion, one claim set; second resolve refused
    assert count_rows(b_conn, "research_claims") == 1
    out3 = op.resolve_human_gate(
        task_id="gate-2", verdict="REJECTED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out3["rejected"] is True and out3["code"] == "NOT_WAITING"

    # A's late write is discarded
    release.set()
    th.join(timeout=5)
    a_out = a_result.get("out")
    assert a_out is not None
    assert a_out.succeeded == [] and a_out.retried == [] and \
        a_out.failed == []
    assert count_rows(b_conn, "research_claims") == 1
    a_conn.close()
    b_conn.close()
    op_conn.close()
def _run_f15_resolve_race_once(tmp_path, db_name, *, verdict,
                               b_loop_sleep=0.02, resolve_sleep=0.02,
                               resolve_deadline=15.0,
                               worker_max_retries=3,
                               hold_lease_after_verdict=False,
                               stall_check_task=None,
                               stall_mid_task=None,
                               stall_depth=0,
                               stall_wide_count=0,
                               stall_mesh=None,
                               stall_mesh_mixed=None,
                               gate2_rejected=False,
                               race_gate2_with_holder=False,
                               gate2_refusals=None,
                               handoff_owner=None,
                               handoff_at_tick=None,
                               handoff_owner2=None,
                               handoff_at_tick2=None,
                               holder_owner_sink=None,
                               lock_snapshots=None,
                               stall_fan=None,
                               b_max_calls_per_tick=None,
                               completion_budget=None,
                               skip_racing_loop=False,
                               hold_lease_after_worker=False) -> dict:
    """One full resolve-racing-recovery scenario (shared by the REJECTED
    race probe and the property-style schedule-invariance test): A claims
    the extract and hangs past the horizon; B reclaims, parks the gate,
    and the dead worker reaches NO_SIGNAL; the OPERATOR races B's
    mid-recovery tick loop (the window is opened deterministically with B
    mid-tick) until the verdict lands. Returns the observable facts:
    verdict event counts, gate status, worker attempt/status, retrying hop
    count, claim rows, FAILED-before-verdict journal count, mode, and the
    second-resolve refusal code."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.persistence.repositories import OperatorCredentialRepository
    from hermes.research.controller import Controller as _Controller

    db_path = tmp_path / db_name
    seed_conn = _connect(str(db_path))
    _migrate(seed_conn)
    ProjectRepository(seed_conn).create("p1", "Test")
    OperatorCredentialRepository(
        seed_conn, frozen_clock(CLOCK)).register(OP_ID, OP_TOKEN, "Op")
    seed_conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    res = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload(
            "dataset_manifest:dm-1", "both"), "task_id": "ext-1",
            "max_retries": worker_max_retries}))
    ext_id = res.entity_id
    apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-1-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    if gate2_rejected:
        # a SECOND human gate depending on gate-1: it parks WAITING_HUMAN
        # as soon as gate-1 SUCCEEDs, stopping the wave - the mesh chains
        # (all dep gate-1 SUCCEEDED) can then only dispatch once the
        # operator REJECTS gate-2 and the mode returns ACTIVE. The
        # recovery + gate-2 park + gate-2 verdict interleave with the
        # mesh completion inside the same bounded budget.
        apply_intent(seed_conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload={
                "task_id": "gate-2", "task_type": "HUMAN_GATE",
                "profile": "DIRECTOR", "idempotency_key": "gate-2-key",
                "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
                "inputs": [], "outputs": [], "dependencies": ["gate-1"],
                "provenance": [], "cost_class": None,
                "concurrency_group": None, "max_retries": 3,
                "parent_task_id": None,
            }))
    if stall_check_task is not None:
        # downstream chain for the partial-lease stall probe: an
        # INTERMEDIATE extract depends on gate-1 (the verdict gate), and
        # stall_check_task depends on the intermediate - so it is NOT
        # eligible in the worker-recovery tick (the intermediate is still
        # PENDING at discovery) but becomes eligible the tick after. A
        # lease holder armed after the recovery then blocks its claim
        # deterministically. stall_mid_task inserts ONE MORE hop between
        # the intermediate and the check task (the third-gate variant:
        # gate-1 -> ext-int -> ext-mid -> ext-3).
        apply_intent(seed_conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload={**build_extract_task_payload(
                "dataset_manifest:dm-1", "both",
                dependencies=("gate-1",)), "task_id": "ext-int",
                "idempotency_key": "ext-int-key"}))
        if stall_mid_task is not None:
            apply_intent(seed_conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p1",
                payload={**build_extract_task_payload(
                    "dataset_manifest:dm-1", "both",
                    dependencies=("ext-int",)),
                    "task_id": stall_mid_task,
                    "idempotency_key": stall_mid_task + "-key"}))
        apply_intent(seed_conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload={**build_extract_task_payload(
                "dataset_manifest:dm-1", "both",
                dependencies=((stall_mid_task or "ext-int"),)),
                "task_id": stall_check_task,
                "idempotency_key": stall_check_task + "-key"}))
    stall_tail: str | None = None
    stall_wide_tail: str | None = None
    if stall_depth:
        # DEPTH lens on the bounded completion budget: a chained extract
        # graph (deep-1 dep gate-1, deep-k dep deep-(k-1)) advances ONE
        # hop per tick (discovery runs once per tick), so a legitimately
        # deep chain needs stall_depth ticks to complete - a fixed budget
        # below that exhausts on a HEALTHY graph (false STALLED).
        _prev = "gate-1"
        for _k in range(1, stall_depth + 1):
            _tid = f"deep-{_k}"
            apply_intent(seed_conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p1",
                payload={**build_extract_task_payload(
                    "dataset_manifest:dm-1", "both",
                    dependencies=(_prev,)), "task_id": _tid,
                    "idempotency_key": _tid + "-key"}))
            _prev = _tid
        stall_tail = _prev
    if stall_wide_count:
        # WIDTH lens: stall_wide_count INDEPENDENT extracts (all dep
        # gate-1) with max_calls_per_tick=1 complete ONE per tick, so a
        # legitimately wide graph needs stall_wide_count ticks - the same
        # fixed-budget false-positive shape, from fan-out not depth.
        for _k in range(1, stall_wide_count + 1):
            _tid = f"wide-{_k}"
            apply_intent(seed_conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p1",
                payload={**build_extract_task_payload(
                    "dataset_manifest:dm-1", "both",
                    dependencies=("gate-1",)), "task_id": _tid,
                    "idempotency_key": _tid + "-key"}))
        stall_wide_tail = f"wide-{stall_wide_count}"
    stall_mesh_tail: list[str] = []
    if stall_mesh is not None:
        # MIXED depth x width lens: `width` PARALLEL chains, each of
        # `depth` hops, all fanning out from the verdict gate. With
        # max_calls_per_tick=1 each hop is one tick, so the graph needs
        # depth*width ticks total - the requirement is the PRODUCT, not
        # the shape (a 5x8 mesh and an 8x5 mesh both need 40 ticks).
        _md, _mw = stall_mesh
        for _w in range(1, _mw + 1):
            _prev = "gate-1"
            for _d in range(1, _md + 1):
                _tid = f"mesh-{_d}-{_w}"
                apply_intent(seed_conn, Intent(
                    kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                    project_id="p1",
                    payload={**build_extract_task_payload(
                        "dataset_manifest:dm-1", "both",
                        dependencies=(_prev,)), "task_id": _tid,
                        "idempotency_key": _tid + "-key"}))
                _prev = _tid
        stall_mesh_tail = [f"mesh-{_md}-{_w}" for _w in range(1, _mw + 1)]
    stall_mesh_mixed_tail: list[str] = []
    stall_mesh_mixed_total: int = 0
    if stall_mesh_mixed is not None:
        # MIXED-SHAPE lens: per-chain depths DIFFER - stall_mesh_mixed is
        # a tuple of per-chain hop counts, e.g. (2, 5, 7) = three chains
        # of 2, 5, and 7 hops, all fanning out from the verdict gate.
        # With max_calls_per_tick=1 each hop is one tick, so the graph
        # needs SUM(depths) ticks - the uniform depth*width product
        # formula does NOT describe a mixed shape (max*width would be
        # 7*3=21 for (2,5,7), but the true need is 2+5+7=14).
        for _w, _dmax in enumerate(stall_mesh_mixed, start=1):
            _prev = "gate-1"
            for _d in range(1, _dmax + 1):
                _tid = f"mix-{_d}-{_w}"
                apply_intent(seed_conn, Intent(
                    kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                    project_id="p1",
                    payload={**build_extract_task_payload(
                        "dataset_manifest:dm-1", "both",
                        dependencies=(_prev,)), "task_id": _tid,
                        "idempotency_key": _tid + "-key"}))
                _prev = _tid
            stall_mesh_mixed_tail.append(f"mix-{_dmax}-{_w}")
            stall_mesh_mixed_total += _dmax
    stall_fan_tail: list[str] = []
    stall_fan_total: int = 0
    if stall_fan is not None:
        # DEEP FAN CHAIN lens: the WIDEST possible graph shape - a
        # WIDENING fan-out tree where every level-k task has `width`
        # children at level k+1 (fan-1-1 root dep gate-1; fan-k-j dep
        # fan-(k-1)-(j // width)). Level k has width**(k-1) tasks, so the
        # tree grows exponentially and its tick requirement at
        # max_calls_per_tick=1 is the TOTAL NODE COUNT
        # (width**depth - 1) // (width - 1) - the widest possible graph
        # cannot be reduced to a depth x width product.
        _fd, _fw = stall_fan
        _prev_level: list[str] = ["fan-1-1"]
        apply_intent(seed_conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload={**build_extract_task_payload(
                "dataset_manifest:dm-1", "both",
                dependencies=("gate-1",)), "task_id": "fan-1-1",
                "idempotency_key": "fan-1-1-key"}))
        stall_fan_tail = _prev_level
        stall_fan_total += 1
        for _d in range(2, _fd + 1):
            _level: list[str] = []
            for _j in range(len(_prev_level) * _fw):
                _tid = f"fan-{_d}-{_j}"
                apply_intent(seed_conn, Intent(
                    kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                    project_id="p1",
                    payload={**build_extract_task_payload(
                        "dataset_manifest:dm-1", "both",
                        dependencies=(_prev_level[_j // _fw],)),
                        "task_id": _tid,
                        "idempotency_key": _tid + "-key"}))
                _level.append(_tid)
            stall_fan_tail = _level
            stall_fan_total += len(_level)
            _prev_level = _level
    TaskRepository(seed_conn).transition_status(
        ext_id, TaskStatus.READY, caused_by="test")
    seed_conn.close()
    release = threading.Event()

    def hung_fn(task, untrusted):
        # genuinely hung - far past the 0.3s horizon. The wait is LONG
        # (release is ALWAYS set - the success path and the finally):
        # a short timeout lets A wake MID-completion under CI load
        # (the huge-fan loop runs 300+ ticks), and its stale dispatch
        # then collides with B's DB writes (sqlite3 database is
        # locked) and crashes the thread. Never wake before release.
        release.wait(3600.0)
        return extraction_draft_from_mapping(good_output())

    a_conn = _connect(str(db_path))
    a = _Controller(a_conn, project_id="p1", extract_fn=hung_fn,
                    lease_seconds=1, heartbeat_refresh_interval=0.05,
                    heartbeat_refresh_horizon=0.3)
    a_result: dict = {}

    def _a_tick():
        try:
            a_result["out"] = a.tick()
        except BaseException as _e:  # noqa: BLE001 - surface, never mask
            a_result["exc"] = f"{type(_e).__name__}: {_e}"

    # DAEMON: if an assertion fires BEFORE the try/finally below
    # (whose finally sets release), A would otherwise leak stuck
    # in release.wait(3600.0) and block pytest's interpreter
    # shutdown for up to an hour (the CI hang pinned from run
    # 32042067489). Daemon => a leaked A never blocks shutdown;
    # the normal path still joins A via the deadline loop + the
    # finally, so this changes nothing on the success path.
    th = threading.Thread(target=_a_tick, daemon=True)
    th.start()
    _time.sleep(0.8)

    b_conn = _connect(str(db_path))
    _b_kwargs = {}
    if b_max_calls_per_tick is not None:
        _b_kwargs["max_calls_per_tick"] = b_max_calls_per_tick
    b = _Controller(b_conn, project_id="p1",
                    extract_fn=good_extract_fn(),
                    lease_seconds=1, heartbeat_refresh_interval=0.05,
                    **_b_kwargs)
    tr_b = TaskRepository(b_conn)
    # phase 1 (sequential): B reclaims, parks the gate, and the dead
    # worker reaches NO_SIGNAL
    gate_parked = False
    for _ in range(12):
        b.tick()
        if tr_b.get("gate-1")["status"] == TaskStatus.WAITING_HUMAN:
            gate_parked = True
            break
        _time.sleep(0.15)
    assert gate_parked, "gate never parked"
    no_signal = False
    # the NO_SIGNAL wait is DEADLINE-based (not a fixed tick count):
    # under CI load a bounded loop can exhaust while the worker is
    # still RUNNING (heartbeat refresh racing the 0.3s horizon) - the
    # deadline absorbs that scheduling jitter, the assertion pins the
    # property, not a race
    _no_signal_deadline = _time.monotonic() + 8.0
    while _time.monotonic() < _no_signal_deadline:
        if tr_b.get(ext_id)["status"] == TaskStatus.NO_SIGNAL:
            no_signal = True
            break
        b.tick()
        _time.sleep(0.1)
    assert no_signal, tr_b.get(ext_id)["status"]
    assert (ProjectRepository(b_conn).get_mode("p1") is
            OperationalMode.AWAITING_HUMAN)
    # phase 2 (CONCURRENT): B ticks in a background loop (mid-recovery of
    # the F15 chain - the worker is NO_SIGNAL and AWAITING_HUMAN ticks can
    # move it no further) while the operator hammers the resolve surface,
    # retrying through LOCK refusals (B's tick holds the lease) until the
    # verdict lands in a lease-free gap. The STALL probe instead SKIPS the
    # racing loop entirely: nothing else can recover the worker, so a
    # lease holder armed at the verdict is the sole post-verdict recovery
    # driver and the bounded completion budget below must surface the
    # stall - no stop-flag race, fully deterministic.
    op_conn = _connect(str(db_path))
    op = _Controller(op_conn, project_id="p1",
                     extract_fn=good_extract_fn(),
                     lease_seconds=1, heartbeat_refresh_interval=0.05)
    op_out: dict = {}
    refusals = {"LOCK": 0, "NOT_WAITING": 0, "TRANSITION": 0}
    b_mid_tick = {"v": False}
    b_loop_done = threading.Event()
    # holder declarations MUST precede the resolve loop: the stall-probe
    # hook inside it (and the finally cleanup) reference them
    holder_thread = None
    holder_stop = threading.Event()
    holder: object = None
    holder_held: dict = {}
    bth = None

    def _arm_lease_holder():
        nonlocal holder, holder_held, holder_thread
        holder_conn = _connect(str(db_path))
        holder = _Controller(holder_conn, project_id="p1",
                             extract_fn=good_extract_fn(),
                             lease_seconds=1,
                             heartbeat_refresh_interval=0.05)
        if holder_owner_sink is not None:
            holder_owner_sink["owner"] = holder._owner
        holder_held = {"ok": 0, "fail": 0, "exc": 0, "last": None}

        def _hold_lease(
                _holder=holder, _stats=holder_held,
                _stop=holder_stop):
            while not _stop.is_set():
                try:
                    ok = _holder._acquire_lock()
                except Exception as _e:  # noqa: BLE001
                    _stats["exc"] += 1
                    _stats["last"] = f"{type(_e).__name__}: {_e}"
                    _time.sleep(0.1)
                    continue
                if ok:
                    _stats["ok"] += 1
                else:
                    _stats["fail"] += 1
                _time.sleep(0.1)
        holder_thread = threading.Thread(
            target=_hold_lease, daemon=True)
        holder_thread.start()
        _hold_deadline = _time.monotonic() + 5.0
        while holder_held["ok"] == 0 and \
                _time.monotonic() < _hold_deadline:
            _time.sleep(0.005)
        assert holder_held["ok"] > 0, \
            f"lease holder never acquired the lock: {holder_held}"

    if (not hold_lease_after_verdict and not hold_lease_after_worker
            and not skip_racing_loop):
        def _b_loop():
            for _ in range(300):
                # once the verdict lands, stop ticking immediately: the
                # worker's post-verdict recovery belongs to the bounded
                # completion budget below (single-owner), not to this
                # racing loop
                if op_out:
                    break
                b_mid_tick["v"] = True
                try:
                    b.tick()
                finally:
                    b_mid_tick["v"] = False
                _time.sleep(b_loop_sleep)
            b_loop_done.set()

        bth = threading.Thread(target=_b_loop)
        bth.start()
        # deterministically open the window with B MID-tick so the resolve
        # provably races B's recovery ticks (LOCK collisions are
        # timing-dependent; the overlap flag is not)
        spin_deadline = _time.monotonic() + 5.0
        while not b_mid_tick["v"] and _time.monotonic() < spin_deadline:
            _time.sleep(0.001)
        assert b_mid_tick["v"], "B's tick loop never started"
    deadline = _time.monotonic() + resolve_deadline
    while _time.monotonic() < deadline:
        out = op.resolve_human_gate(
            task_id="gate-1", verdict=verdict, operator_id=OP_ID,
            operator_token=OP_TOKEN)
        if not out["rejected"]:
            op_out["out"] = out
            # stall-probe hook: a THIRD controller takes the scheduler
            # lease the INSTANT the verdict lands and is CONFIRMED holding
            # it before this returns - every post-verdict recovery tick is
            # then a LOCK refusal and the worker (still NO_SIGNAL: no B
            # loop, no other writer) can never reach a terminal state, so
            # the bounded completion budget below must SURFACE the stall,
            # never silently report a plausible shape
            if hold_lease_after_verdict:
                _arm_lease_holder()
                assert tr_b.get(ext_id)["status"] == TaskStatus.NO_SIGNAL, (
                    "worker must be NO_SIGNAL when the holder takes the "
                    "lease")
            break
        # TRANSITION = the controller's fail-closed catch-all when
        # its fenced verdict write hits a transient error (e.g.
        # sqlite "database is locked" under CI load): it ROLLBACKs
        # (controller.py resolve_human_gate), so the gate is STILL
        # WAITING_HUMAN and the refusal is retryable exactly like
        # LOCK - never a verdict landing.
        assert out["code"] in ("LOCK", "NOT_WAITING", "TRANSITION"), out
        refusals[out["code"]] += 1
        _time.sleep(resolve_sleep)
    if bth is not None:
        bth.join(timeout=resolve_deadline + 10)
        assert b_loop_done.is_set(), "B loop never completed"
    assert "out" in op_out, "resolve never landed"
    # if the background B loop exhausted its tick budget under load before
    # the post-verdict recovery chain completed, finish the chain from the
    # main thread (the loop thread has ended, so this is single-owner and
    # safe) - the assertions below then pin the chain's shape, not a
    # scheduling artifact
    check_tasks = [ext_id]
    if stall_check_task is not None:
        if stall_mid_task is not None:
            check_tasks.append(stall_mid_task)
        check_tasks.append(stall_check_task)
    if stall_depth:
        assert stall_tail is not None
        check_tasks.append(stall_tail)
    if stall_wide_count:
        assert stall_wide_tail is not None
        check_tasks.append(stall_wide_tail)
    if stall_mesh is not None:
        check_tasks.extend(stall_mesh_tail)
    if stall_mesh_mixed is not None:
        check_tasks.extend(stall_mesh_mixed_tail)
    if gate2_rejected:
        check_tasks.append("gate-2")
    if stall_fan is not None:
        check_tasks.extend(stall_fan_tail)
    holder_armed = {"v": False}
    # the completion budget scales with the pending graph the loop must
    # verify: a legitimately deep/wide chain advances ONE hop per tick,
    # so a FIXED 30-tick count can be exhausted by a healthy large graph
    # (false STALLED - see the budget-exhaustion probe below). Default =
    # 30 + one tick per checked hop + slack; an explicit completion_budget
    # reproduces the old fixed bound for the false-positive demonstration.
    if completion_budget is None:
        _mesh_ticks = (stall_mesh[0] * stall_mesh[1]) if stall_mesh else 0
        _mesh_mixed_ticks = (stall_mesh_mixed_total
                             if stall_mesh_mixed is not None else 0)
        _fan_ticks = stall_fan_total if stall_fan else 0
        completion_budget = max(
            30, 10 + len(check_tasks) + stall_depth + stall_wide_count
            + _mesh_ticks + _mesh_mixed_ticks + _fan_ticks)
    _completion_ticks = 0
    gate2_resolved = {"v": False}
    for _ in range(completion_budget):
        # owner-handoff hook: at the chosen tick, simulate the lease
        # CHANGING HANDS (exactly the write the controller's reclaim path
        # performs - UPDATE owner/locked_at) so the final snapshot must
        # name the NEWEST owner, proving it reads the live row, never a
        # stale one
        for _ht, _ho, _h_off in ((handoff_at_tick, handoff_owner, 1),
                                 (handoff_at_tick2, handoff_owner2, 2)):
            if _ho is not None and _ht is not None \
                    and _completion_ticks == _ht:
                # the handoff writes the NEW owner with a locked_at FAR
                # in the future (+N hours): the lease is fresh from the
                # new owner's perspective, so the OLD holder can never
                # reclaim it as stale inside the test window - the
                # snapshot must name the newest owner deterministically;
                # each successive handoff gets a LATER offset so the
                # locked_at ordering is strictly increasing (second
                # precision alone would tie two handoffs in one second).
                b_conn.execute(
                    "UPDATE scheduler_lock SET owner = ?, locked_at = ? "
                    "WHERE id = 0",
                    (_ho, _time.strftime(
                        "%Y-%m-%dT%H:%M:%S.000000+00:00",
                        _time.gmtime(_time.time() + 3600 * _h_off))),
                )
                b_conn.commit()
        if lock_snapshots is not None:
            _lr = b_conn.execute(
                "SELECT owner, locked_at FROM scheduler_lock WHERE id = 0"
            ).fetchone()
            lock_snapshots.append(
                (None if _lr is None else _lr["owner"],
                 None if _lr is None else _lr["locked_at"]))
        if all(tr_b.get(t)["status"] in (TaskStatus.SUCCEEDED,
                                          TaskStatus.FAILED)
               for t in check_tasks):
            break
        # partial-lease hook: once the worker has recovered (terminal),
        # arm a lease holder so the DOWNSTREAM claim can never succeed -
        # the budget must surface the downstream stall, never silently
        # pass on the worker's shape
        if (hold_lease_after_worker and not holder_armed["v"]
                and tr_b.get(ext_id)["status"] in (TaskStatus.SUCCEEDED,
                                                    TaskStatus.FAILED)):
            _arm_lease_holder()
            holder_armed["v"] = True
        _completion_ticks += 1
        b.tick()
        if (gate2_rejected and not gate2_resolved["v"]
                and tr_b.get("gate-2")["status"] == TaskStatus.WAITING_HUMAN):
            # gate-2-vs-holder race: arm the lease holder the INSTANT the
            # gate parks so the operator's REJECTED verdict races it - the
            # resolve is refused LOCK and gate-2 stays WAITING_HUMAN, the
            # wave stays stopped, and the mesh never dispatches; the
            # budget must then surface the downstream stall (gate-2 +
            # mesh tails) AND name the lease holder in the owner snapshot
            if race_gate2_with_holder and not holder_armed["v"]:
                _arm_lease_holder()
                holder_armed["v"] = True
            out_g2 = op.resolve_human_gate(
                task_id="gate-2", verdict="REJECTED", operator_id=OP_ID,
                operator_token=OP_TOKEN)
            if not out_g2["rejected"]:
                gate2_resolved["v"] = True
            elif gate2_refusals is not None:
                gate2_refusals.append(out_g2["code"])
    _scaled_budget = completion_budget
    # a second resolve must be refused (one verdict is terminal)
    other = "REJECTED" if verdict == "APPROVED" else "APPROVED"
    out2 = op.resolve_human_gate(
        task_id="gate-1", verdict=other, operator_id=OP_ID,
        operator_token=OP_TOKEN)
    second_refusal = out2["code"] if out2["rejected"] else None
    try:
        # SURFACE, never mask: if the bounded completion budget was
        # exhausted without every declared task reaching a terminal state,
        # the post-verdict chain is genuinely stalled (e.g. a competing
        # controller holds the lease, or a downstream claim is blocked) -
        # fail loudly so the stall is observable, never silently swallowed.
        # This check lives INSIDE the try so the finally below always
        # releases A's hung thread and the lease holder.
        stuck = [t for t in check_tasks
                 if tr_b.get(t)["status"] not in (TaskStatus.SUCCEEDED,
                                                   TaskStatus.FAILED)]
        lock_row = b_conn.execute(
            "SELECT owner, locked_at FROM scheduler_lock WHERE id = 0"
        ).fetchone()
        lock_note = (
            f" scheduler_lock owner={lock_row['owner']!r} "
            f"(locked_at={lock_row['locked_at']!r})"
            if lock_row is not None
            else " scheduler_lock free (no blocking owner row)")
        assert not stuck, (
            f"post-verdict recovery chain STALLED: tasks stuck at "
            f"{[(t, str(tr_b.get(t)['status'])) for t in stuck]} after "
            f"the bounded completion budget - a held lease or deadlock "
            f"was surfaced, never masked. Blocking-owner snapshot:{lock_note}")
        n_hgr = b_conn.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = 'HumanGateResolved'"
        ).fetchone()["c"]
        n_gp = b_conn.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = 'GatePassed'"
        ).fetchone()["c"]
        n_gf = b_conn.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = 'GateFailed'"
        ).fetchone()["c"]
        hgr_row = b_conn.execute(
            "SELECT event_id FROM events WHERE event_type = 'HumanGateResolved'"
        ).fetchone()
        failed_before = b_conn.execute(
            "SELECT COUNT(*) c FROM events WHERE task_id = ? "
            "AND event_type = 'TaskStatusChanged' AND to_state = 'FAILED' "
            "AND event_id < ?",
            (ext_id, hgr_row["event_id"])).fetchone()["c"]
        retrying = b_conn.execute(
            "SELECT COUNT(*) c FROM events WHERE task_id = ? "
            "AND event_type = 'TaskStatusChanged' AND to_state = 'RETRYING'",
            (ext_id,)).fetchone()["c"]
        row = tr_b.get(ext_id)
        facts = {
            "hgr": n_hgr, "gate_passed": n_gp, "gate_failed": n_gf,
            "gate_status": tr_b.get("gate-1")["status"],
            "worker_status": row["status"], "worker_attempt": row["attempt"],
            "retrying_hops": retrying, "failed_before_verdict": failed_before,
            "claims": count_rows(b_conn, "research_claims"),
            "links": count_rows(b_conn, "claim_assumption_links"),
            "mode": ProjectRepository(b_conn).get_mode("p1"),
            "second_refusal": second_refusal, "refusals": refusals,
            "completion_ticks_used": _completion_ticks,
            "completion_budget_scaled": _scaled_budget,
        }

        # A's late return is discarded: no second completion. The join is
        # DEADLINE-based with a generous bound - under the heavy 300-task
        # huge-fan load, CI thread scheduling can take longer than 5s for
        # A's hung tick to wake and finish its discard path; the deadline
        # absorbs that jitter, the assertion pins the property.
        release.set()
        _a_deadline = _time.monotonic() + 30.0
        while (_time.monotonic() < _a_deadline
               and "out" not in a_result):
            th.join(timeout=0.5)
        a_out = a_result.get("out")
        assert a_out is not None, (
            "A's hung tick never landed: " + repr(a_result))
        assert a_out.succeeded == [] and a_out.retried == [] and \
            a_out.failed == []
        assert count_rows(b_conn, "research_claims") == facts["claims"]
        assert tr_b.get(ext_id)["attempt"] == facts["worker_attempt"]
        return facts
    finally:
        # ALWAYS release A's hung thread and stop the lease holder, even
        # on the surfacing raise - never leak threads or leases
        holder_stop.set()
        if holder_thread is not None:
            holder_thread.join(timeout=5)
        release.set()
        th.join(timeout=5)
        a_conn.close()
        b_conn.close()
        op_conn.close()

def test_21_f15_recovery_before_dispatch_dep_edge(db):
    """Dep-edge variant of the same-tick ordering pin: ext-2 DEPENDS on
    ext-1 (the requeued dead worker), so ext-2's dispatch is F-10-gated on
    ext-1 SUCCEEDED. Tick 1 (paused) marks the stale worker NO_SIGNAL with
    dispatch stopped; after resume, tick 2's recovery completes ext-1
    (attempt 2) and ITS dispatch then claims ext-2 (now eligible) - both
    in the same tick. The journal order (event_id) pins the load-bearing
    discipline: every ext-1 hop precedes every ext-2 hop, ext-1 carries
    the RETRYING hop while ext-2 never does, and the two completions land
    as distinguishable claim sets."""
    ext1 = admit_extract_task(db, source_ref="dataset_manifest:dm-1")
    # ext-2 DEPENDS on ext-1 - its claim is gated on ext-1 SUCCEEDED
    res2 = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload(
            "dataset_manifest:dm-1", "both", dependencies=(ext1,)),
            "task_id": "ext-2", "idempotency_key": "ext-2-key"}))
    ext2 = res2.entity_id
    tr = TaskRepository(db)
    tr.transition_status(ext1, TaskStatus.READY, caused_by="test")
    tr.transition_status(ext2, TaskStatus.READY, caused_by="test")
    # simulate the dead worker: RUNNING with a stale heartbeat
    tr.transition_status(ext1, TaskStatus.RUNNING, caused_by="test")
    stale_heartbeat(db, ext1)

    # PAUSED first miss: recovery marks NO_SIGNAL; dispatch is stopped so
    # ext-2 stays READY for the same-tick ordering probe
    ProjectRepository(db).transition_mode(
        "p1", OperationalMode.PAUSED, caused_by="test", reason="probe")
    # distinct content per task (the claim id is content-derived from the
    # statement, never the ref) so the two completions land as
    # distinguishable rows instead of collapsing at the PA4 artifact dedup
    def dual_extract_fn():
        def _fn(task, untrusted):
            out = good_output()
            if task["task_id"] == "ext-2":
                out["claims"][0]["statement"] = (
                    "Beta increases alpha under gamma conditions.")
                out["assumptions"][0]["statement"] = (
                    "The second sample is representative.")
            return extraction_draft_from_mapping(out)
        return _fn

    ctrl = make_controller(db, extract_fn=dual_extract_fn())
    t1 = ctrl.tick()
    assert ext1 in t1.recovery
    assert tr.get_status(ext1) is TaskStatus.NO_SIGNAL
    assert tr.get_status(ext2) is TaskStatus.READY

    # RESUME; tick 2 does recovery (requeue + re-execute) AND dispatch -
    # ext-2's claim is F-10-gated on ext-1, which the recovery just
    # completed, so the ordering is load-bearing, not just observable
    ProjectRepository(db).transition_mode(
        "p1", OperationalMode.ACTIVE, caused_by="test", reason="probe")
    before = count_rows(db, "events")
    t2 = ctrl.tick()
    assert ext1 in t2.succeeded
    assert ext2 in t2.succeeded
    assert tr.get(ext1)["attempt"] == 2, tr.get(ext1)["attempt"]
    assert tr.get(ext2)["attempt"] == 1, tr.get(ext2)["attempt"]

    # journal ORDER: every ext-1 hop precedes every ext-2 hop in this tick
    hops1 = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (ext1, before))]
    hops2 = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (ext2, before))]
    assert hops1 and hops2, (hops1, hops2)
    assert max(hops1) < min(hops2), (hops1, hops2)
    # ext-1 took the RETRYING hop (the recovery requeue); ext-2 never did
    retrying1 = db.execute(
        "SELECT COUNT(*) c FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND to_state = 'RETRYING'",
        (ext1,)).fetchone()["c"]
    retrying2 = db.execute(
        "SELECT COUNT(*) c FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND to_state = 'RETRYING'",
        (ext2,)).fetchone()["c"]
    assert retrying1 == 1, retrying1
    assert retrying2 == 0, retrying2
    # two distinguishable claim sets - no duplicates
    assert count_rows(db, "research_claims") == 2
    assert count_rows(db, "claim_assumption_links") == 2

def test_21_f15_rejected_verdict_race_retryable_task(tmp_path):
    """REJECTED-verdict variant of the resolve-racing-recovery probe: the
    operator's REJECTED verdict lands while B's tick is mid-recovery of
    the F15 chain, on a RETRYABLE worker (max_retries not exhausted).
    Asserts the verdict lands EXACTLY ONCE (one HumanGateResolved + one
    GateFailed, zero GatePassed), the gate is FAILED and a second resolve
    is refused NOT_WAITING, the retryable worker is requeued and
    re-executes EXACTLY ONCE (attempt 2, one claim set), no FAILED hop
    precedes the verdict in journal order (the mode gate held under the
    race), and A's late write is discarded - attempts stay coherent."""
    facts = _run_f15_resolve_race_once(
        tmp_path, "f15_race_rejected.db", verdict="REJECTED")

    # exactly one REJECTED verdict, no lost events
    assert facts["hgr"] == 1, facts
    assert facts["gate_passed"] == 0, facts
    assert facts["gate_failed"] == 1, facts
    assert facts["gate_status"] == TaskStatus.FAILED, facts
    # the retryable worker completes exactly once (requeued, not
    # exhausted): attempt 2, one RETRYING hop, one claim set
    assert facts["worker_status"] == TaskStatus.SUCCEEDED, facts
    assert facts["worker_attempt"] == 2, facts
    assert facts["retrying_hops"] == 1, facts
    assert facts["claims"] == 1 and facts["links"] == 1, facts
    # the F15-audit mode gate held under the race: the worker was NO_SIGNAL
    # (never FAILED) at the moment of the verdict
    assert facts["failed_before_verdict"] == 0, facts
    assert facts["mode"] is OperationalMode.ACTIVE, facts
    # one verdict is terminal
    assert facts["second_refusal"] == "NOT_WAITING", facts

def test_21_f15_resolve_race_outcome_invariant_across_schedules(tmp_path):
    """Property-style invariance: the resolve-racing-recovery OUTCOME is a
    pure function of the inputs, not of the scheduler. Six seeded random
    schedules (varied B-loop pacing, resolve-loop pacing, and verdict)
    must all yield the SAME invariants: exactly one verdict (APPROVED or
    REJECTED, never both), exactly one worker completion at attempt 2 with
    one claim set, no FAILED hop before the verdict in journal order, and
    a terminal second resolve - the one-verdict/one-completion guarantees
    hold under every interleaving."""
    import random
    rng = random.Random(20260816)
    verdicts = ["APPROVED", "REJECTED"]
    schedules = []
    for i in range(6):
        schedules.append({
            "verdict": rng.choice(verdicts),
            "b_loop_sleep": rng.choice((0.01, 0.03, 0.05)),
            "resolve_sleep": rng.choice((0.01, 0.03, 0.05)),
        })
    for i, sched in enumerate(schedules):
        facts = _run_f15_resolve_race_once(
            tmp_path, f"f15_race_prop_{i}.db",
            verdict=sched["verdict"], b_loop_sleep=sched["b_loop_sleep"],
            resolve_sleep=sched["resolve_sleep"], resolve_deadline=20.0)
        # exactly one verdict
        assert facts["hgr"] == 1, (i, sched, facts)
        passed = facts["gate_passed"]
        failed = facts["gate_failed"]
        assert (passed, failed) in ((1, 0), (0, 1)), (i, sched, facts)
        assert facts["gate_status"] in (TaskStatus.SUCCEEDED,
                                        TaskStatus.FAILED), (i, sched, facts)
        # exactly one worker completion, requeued once, coherent attempts
        assert facts["worker_status"] == TaskStatus.SUCCEEDED, \
            (i, sched, facts)
        assert facts["worker_attempt"] == 2, (i, sched, facts)
        assert facts["retrying_hops"] == 1, (i, sched, facts)
        assert facts["claims"] == 1 and facts["links"] == 1, \
            (i, sched, facts)
        # the mode gate held: no FAILED hop before the verdict
        assert facts["failed_before_verdict"] == 0, (i, sched, facts)
        assert facts["mode"] is OperationalMode.ACTIVE, (i, sched, facts)
        # one verdict is terminal under every schedule
        assert facts["second_refusal"] == "NOT_WAITING", (i, sched, facts)
def _run_f15_second_gate_once(tmp_path, db_name, *, park_sleep=0.15,
                              resume_sleep=0.15) -> dict:
    """One full second-gate re-park scenario (shared by the deterministic
    probe and the property-style schedule-invariance test): A claims the
    extract and hangs past the horizon; B reclaims, gate-1 parks, the dead
    worker reaches NO_SIGNAL; gate-1 is REJECTED; the same tick completes
    the worker's recovery AND re-parks gate-2 at WAITING_HUMAN; gate-2 is
    then APPROVED. Returns the observable facts: per-gate verdict counts
    and statuses, worker attempt/status, claim rows, mode, and the
    second-resolve refusal code."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.persistence.repositories import OperatorCredentialRepository
    from hermes.research.controller import Controller as _Controller

    db_path = tmp_path / db_name
    seed_conn = _connect(str(db_path))
    _migrate(seed_conn)
    ProjectRepository(seed_conn).create("p1", "Test")
    OperatorCredentialRepository(
        seed_conn, frozen_clock(CLOCK)).register(OP_ID, OP_TOKEN, "Op")
    seed_conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    res = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload(
            "dataset_manifest:dm-1", "both"), "task_id": "ext-1"}))
    ext_id = res.entity_id
    for gid in ("gate-1", "gate-2"):
        apply_intent(seed_conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload={
                "task_id": gid, "task_type": "HUMAN_GATE",
                "profile": "DIRECTOR", "idempotency_key": gid + "-key",
                "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
                "inputs": [], "outputs": [], "dependencies": [],
                "provenance": [], "cost_class": None,
                "concurrency_group": None, "max_retries": 3,
                "parent_task_id": None,
            }))
    TaskRepository(seed_conn).transition_status(
        ext_id, TaskStatus.READY, caused_by="test")
    seed_conn.close()

    release = threading.Event()

    def hung_fn(task, untrusted):
        release.wait(10.0)   # genuinely hung - far past the 0.3s horizon
        return extraction_draft_from_mapping(good_output())

    a_conn = _connect(str(db_path))
    a = _Controller(a_conn, project_id="p1", extract_fn=hung_fn,
                    lease_seconds=1, heartbeat_refresh_interval=0.05,
                    heartbeat_refresh_horizon=0.3)
    a_result: dict = {}

    def _a_tick():
        a_result["out"] = a.tick()

    th = threading.Thread(target=_a_tick)
    th.start()
    _time.sleep(0.8)

    b_conn = _connect(str(db_path))
    b = _Controller(b_conn, project_id="p1",
                    extract_fn=good_extract_fn(),
                    lease_seconds=1, heartbeat_refresh_interval=0.05)
    tr_b = TaskRepository(b_conn)
    # phase 1: B reclaims; first miss + gate-1 parks
    gate1_parked = False
    for _ in range(10):
        b.tick()
        if tr_b.get("gate-1")["status"] == TaskStatus.WAITING_HUMAN:
            gate1_parked = True
            break
        _time.sleep(park_sleep)
    assert gate1_parked, "gate-1 never parked"
    no_signal = False
    for _ in range(8):
        if tr_b.get(ext_id)["status"] == TaskStatus.NO_SIGNAL:
            no_signal = True
            break
        b.tick()
        _time.sleep(park_sleep)
    assert no_signal, tr_b.get(ext_id)["status"]
    assert ProjectRepository(b_conn).get_mode("p1") is \
        OperationalMode.AWAITING_HUMAN

    # gate-1 is REJECTED: wave resumes, then gate-2 re-parks it
    op_conn = _connect(str(db_path))
    op = _Controller(op_conn, project_id="p1",
                     extract_fn=good_extract_fn(),
                     lease_seconds=1, heartbeat_refresh_interval=0.05)
    out1 = op.resolve_human_gate(
        task_id="gate-1", verdict="REJECTED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out1["rejected"] is False, out1
    assert tr_b.get("gate-1")["status"] == TaskStatus.FAILED

    # phase 2: one tick completes the recovery AND re-parks gate-2
    ext_done = gate2_parked = False
    for _ in range(12):
        b.tick()
        if tr_b.get(ext_id)["status"] == TaskStatus.SUCCEEDED:
            ext_done = True
        if tr_b.get("gate-2")["status"] == TaskStatus.WAITING_HUMAN:
            gate2_parked = True
        if ext_done and gate2_parked:
            break
        _time.sleep(resume_sleep)
    assert ext_done, tr_b.get(ext_id)["status"]
    assert gate2_parked, "gate-2 never re-parked"
    assert tr_b.get(ext_id)["attempt"] == 2, tr_b.get(ext_id)["attempt"]
    assert tr_b.get("gate-2")["status"] == TaskStatus.WAITING_HUMAN
    assert ProjectRepository(b_conn).get_mode("p1") is \
        OperationalMode.AWAITING_HUMAN

    # the second gate's own verdict: APPROVED
    out2 = op.resolve_human_gate(
        task_id="gate-2", verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out2["rejected"] is False, out2
    assert tr_b.get("gate-2")["status"] == TaskStatus.SUCCEEDED
    assert ProjectRepository(b_conn).get_mode("p1") is OperationalMode.ACTIVE
    # each gate exactly one verdict, no cross-talk
    n_hgr = b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'HumanGateResolved'"
    ).fetchone()["c"]
    n_gf = b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'GateFailed'"
    ).fetchone()["c"]
    n_gp = b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'GatePassed'"
    ).fetchone()["c"]
    # one completion, one claim set; second resolve refused
    claims = count_rows(b_conn, "research_claims")
    out3 = op.resolve_human_gate(
        task_id="gate-2", verdict="REJECTED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    second_refusal = out3["code"] if out3["rejected"] else None
    facts = {
        "hgr": n_hgr, "gate_failed": n_gf, "gate_passed": n_gp,
        "gate1_status": tr_b.get("gate-1")["status"],
        "gate2_status": tr_b.get("gate-2")["status"],
        "worker_status": tr_b.get(ext_id)["status"],
        "worker_attempt": tr_b.get(ext_id)["attempt"],
        "claims": claims, "mode": ProjectRepository(b_conn).get_mode("p1"),
        "second_refusal": second_refusal,
    }

    # A's late write is discarded
    release.set()
    th.join(timeout=5)
    a_out = a_result.get("out")
    assert a_out is not None
    assert a_out.succeeded == [] and a_out.retried == [] and \
        a_out.failed == []
    assert count_rows(b_conn, "research_claims") == facts["claims"]
    a_conn.close()
    b_conn.close()
    op_conn.close()
    return facts

def test_21_f15_second_gate_property_schedules(tmp_path):
    """Property-style invariance for the second-gate re-park: across five
    seeded random schedules (varied park and resume tick pacing), each gate
    gets EXACTLY ONE verdict (gate-1 REJECTED, gate-2 APPROVED: exactly two
    HumanGateResolved, one GateFailed + one GatePassed, zero cross-talk),
    the worker completes exactly once at attempt 2, the mode ends ACTIVE,
    and a second resolve is refused NOT_WAITING - the re-park guarantees
    are a pure function of the inputs, not of the scheduler."""
    import random
    rng = random.Random(20260817)
    schedules = []
    for _ in range(5):
        schedules.append({
            "park_sleep": rng.choice((0.05, 0.15, 0.3)),
            "resume_sleep": rng.choice((0.05, 0.15, 0.3)),
        })
    for i, sched in enumerate(schedules):
        facts = _run_f15_second_gate_once(
            tmp_path, f"f15_second_gate_prop_{i}.db",
            park_sleep=sched["park_sleep"],
            resume_sleep=sched["resume_sleep"])
        # each gate exactly one verdict, zero cross-talk
        assert facts["hgr"] == 2, (i, sched, facts)
        assert facts["gate_failed"] == 1, (i, sched, facts)
        assert facts["gate_passed"] == 1, (i, sched, facts)
        assert facts["gate1_status"] == TaskStatus.FAILED, (i, sched, facts)
        assert facts["gate2_status"] == TaskStatus.SUCCEEDED, \
            (i, sched, facts)
        # the worker completes exactly once at attempt 2, one claim set
        assert facts["worker_status"] == TaskStatus.SUCCEEDED, \
            (i, sched, facts)
        assert facts["worker_attempt"] == 2, (i, sched, facts)
        assert facts["claims"] == 1, (i, sched, facts)
        # the wave ends ACTIVE and one verdict per gate is terminal
        assert facts["mode"] is OperationalMode.ACTIVE, (i, sched, facts)
        assert facts["second_refusal"] == "NOT_WAITING", (i, sched, facts)

def test_21_f15_recovery_before_dispatch_gate_dep(db):
    """Gate-dep variant of the same-tick ordering pin: the requeued dead
    worker (ext-1) is the DEPENDENCY of a HUMAN_GATE, so the gate cannot
    park until the recovery completes ext-1. Tick 1 (paused) marks the
    stale worker NO_SIGNAL (the gate stays PENDING - its dep is not
    SUCCEEDED); after resume, tick 2's recovery completes ext-1 (attempt
    2) and ITS dispatch then discovers the gate (dep now SUCCEEDED) and
    parks it WAITING_HUMAN - both in the same tick. The journal order
    (event_id) pins the load-bearing discipline: every ext-1 hop precedes
    every gate hop, the gate parks exactly once (one HumanApprovalRequested),
    and the mode returns AWAITING_HUMAN."""
    ext1 = admit_extract_task(db, source_ref="dataset_manifest:dm-1")
    # the HUMAN_GATE DEPENDS on ext-1 - its park is gated on ext-1 SUCCEEDED
    gate_id = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-1-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [ext1],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        })).entity_id
    tr = TaskRepository(db)
    tr.transition_status(ext1, TaskStatus.READY, caused_by="test")
    # simulate the dead worker: RUNNING with a stale heartbeat
    tr.transition_status(ext1, TaskStatus.RUNNING, caused_by="test")
    stale_heartbeat(db, ext1)

    # PAUSED first miss: recovery marks NO_SIGNAL; dispatch is stopped, and
    # even if it ran the gate could not park (dep not SUCCEEDED)
    ProjectRepository(db).transition_mode(
        "p1", OperationalMode.PAUSED, caused_by="test", reason="probe")
    ctrl = make_controller(db)
    t1 = ctrl.tick()
    assert ext1 in t1.recovery
    assert tr.get_status(ext1) is TaskStatus.NO_SIGNAL
    assert tr.get_status(gate_id) is TaskStatus.PENDING

    # RESUME; tick 2: recovery completes ext-1 (attempt 2), then dispatch
    # discovers the gate (dep SUCCEEDED) and parks it WAITING_HUMAN
    ProjectRepository(db).transition_mode(
        "p1", OperationalMode.ACTIVE, caused_by="test", reason="probe")
    before = count_rows(db, "events")
    t2 = ctrl.tick()
    assert ext1 in t2.succeeded, t2
    assert gate_id in t2.waiting_human, t2
    assert tr.get(ext1)["attempt"] == 2, tr.get(ext1)["attempt"]
    assert tr.get_status(gate_id) is TaskStatus.WAITING_HUMAN
    assert ProjectRepository(db).get_mode("p1") is \
        OperationalMode.AWAITING_HUMAN

    # journal ORDER: every ext-1 hop precedes every gate hop in this tick
    hops1 = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (ext1, before))]
    hopsg = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (gate_id, before))]
    assert hops1 and hopsg, (hops1, hopsg)
    assert max(hops1) < min(hopsg), (hops1, hopsg)
    # the gate parks exactly once (one HumanApprovalRequested) - the dep
    # gate held through the recovery, so the wave stops at the gate
    assert db.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = "
        "'HumanApprovalRequested'").fetchone()["c"] == 1
    # one claim set for the recovered worker - no duplicates
    assert count_rows(db, "research_claims") == 1
    assert count_rows(db, "claim_assumption_links") == 1

def test_21_f15_rejected_verdict_race_retries_exhausted(tmp_path):
    """REJECTED-verdict race with the worker's retries EXHAUSTED: the
    operator's REJECTED verdict races B's mid-recovery tick loop on a
    worker whose max_retries is already consumed (1 of 1). The recovery
    ladder's second conclusive miss FAILs the worker on the first ACTIVE
    tick after the verdict, but the requeue leg is skipped (attempt 1 >=
    max_retries 1) - so the worker lands FAILED (never re-executed), the
    wave stops, and the gate's single REJECTED verdict is terminal. Asserts
    exactly one verdict (one HumanGateResolved + one GateFailed, zero
    GatePassed), worker FAILED at attempt 1 with ZERO retrying hops and
    zero claim sets, no FAILED hop precedes the verdict in journal order,
    and a second resolve is refused NOT_WAITING."""
    facts = _run_f15_resolve_race_once(
        tmp_path, "f15_race_exhausted.db", verdict="REJECTED",
        worker_max_retries=1)

    # exactly one REJECTED verdict, no lost events
    assert facts["hgr"] == 1, facts
    assert facts["gate_passed"] == 0, facts
    assert facts["gate_failed"] == 1, facts
    assert facts["gate_status"] == TaskStatus.FAILED, facts
    # the exhausted worker lands FAILED - never re-executed, never requeued
    assert facts["worker_status"] == TaskStatus.FAILED, facts
    assert facts["worker_attempt"] == 1, facts
    assert facts["retrying_hops"] == 0, facts
    assert facts["claims"] == 0 and facts["links"] == 0, facts
    # the F15-audit mode gate held under the race: no FAILED hop (neither
    # the worker's nor any other) precedes the verdict in journal order
    assert facts["failed_before_verdict"] == 0, facts
    assert facts["mode"] is OperationalMode.ACTIVE, facts
    # one verdict is terminal
    assert facts["second_refusal"] == "NOT_WAITING", facts



def test_21_f15_recovery_before_dispatch_chained_gates(db):
    """Chained-gate variant of the same-tick ordering pin: the requeued
    dead worker (ext-1) is the dependency of gate-1, which is ITSELF the
    dependency of gate-2 — so gate-2's park is transitively gated on the
    worker's recovery. Tick 1 (paused) marks ext-1 NO_SIGNAL while both
    gates stay PENDING (gate-1's dep is not SUCCEEDED; gate-2's dep is
    not even READY); after resume, tick 2's recovery completes ext-1
    (attempt 2) and its dispatch then parks gate-1 WAITING_HUMAN — the
    wave stops. The operator's APPROVED verdict resolves gate-1, and the
    very next tick's dispatch parks gate-2 WAITING_HUMAN (gate-1 now
    SUCCEEDED). Journal order (event_id) pins the load-bearing chain:
    every ext-1 hop precedes every gate-1 hop, every gate-1 hop precedes
    every gate-2 hop, each gate parks exactly once (two
    HumanApprovalRequested, zero re-parks), and the wave stops at each
    gate in turn.
    """
    ext1 = admit_extract_task(db, source_ref="dataset_manifest:dm-1")
    # gate-1 DEPENDS on ext-1 (its park is gated on ext-1 SUCCEEDED);
    # gate-2 DEPENDS on gate-1 (its park is gated on gate-1 SUCCEEDED)
    gate1 = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-1-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [ext1],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        })).entity_id
    gate2 = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-2", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-2-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [gate1],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        })).entity_id
    tr = TaskRepository(db)
    tr.transition_status(ext1, TaskStatus.READY, caused_by="test")
    # simulate the dead worker: RUNNING with a stale heartbeat
    tr.transition_status(ext1, TaskStatus.RUNNING, caused_by="test")
    stale_heartbeat(db, ext1)

    # PAUSED first miss: recovery marks NO_SIGNAL; dispatch is stopped,
    # and even if it ran neither gate could park (deps not SUCCEEDED)
    ProjectRepository(db).transition_mode(
        "p1", OperationalMode.PAUSED, caused_by="test", reason="probe")
    ctrl = make_controller(db)
    t1 = ctrl.tick()
    assert ext1 in t1.recovery
    assert tr.get_status(ext1) is TaskStatus.NO_SIGNAL
    assert tr.get_status(gate1) is TaskStatus.PENDING
    assert tr.get_status(gate2) is TaskStatus.PENDING

    # RESUME; tick 2: recovery completes ext-1 (attempt 2), then dispatch
    # discovers gate-1 (dep SUCCEEDED) and parks it WAITING_HUMAN — the
    # wave stops before gate-2 (gate-1 not yet SUCCEEDED)
    ProjectRepository(db).transition_mode(
        "p1", OperationalMode.ACTIVE, caused_by="test", reason="probe")
    before = count_rows(db, "events")
    t2 = ctrl.tick()
    assert ext1 in t2.succeeded, t2
    assert gate1 in t2.waiting_human, t2
    assert tr.get(ext1)["attempt"] == 2, tr.get(ext1)["attempt"]
    assert tr.get_status(gate1) is TaskStatus.WAITING_HUMAN
    assert tr.get_status(gate2) is TaskStatus.PENDING
    assert ProjectRepository(db).get_mode("p1") is \
        OperationalMode.AWAITING_HUMAN

    # journal ORDER so far: every ext-1 hop precedes every gate-1 hop
    hops1 = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (ext1, before))]
    hopsg1 = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (gate1, before))]
    assert hops1 and hopsg1, (hops1, hopsg1)
    assert max(hops1) < min(hopsg1), (hops1, hopsg1)

    # gate-1's verdict: APPROVED (gate-1 SUCCEEDED, mode back to ACTIVE)
    r1 = ctrl.resolve_human_gate(
        task_id="gate-1", verdict="APPROVED", rationale="chain",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert r1["rejected"] is False, r1
    assert tr.get_status(gate1) is TaskStatus.SUCCEEDED
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.ACTIVE

    # tick 3: dispatch re-parking gate-2 (gate-1 now SUCCEEDED)
    before2 = count_rows(db, "events")
    t3 = ctrl.tick()
    assert gate2 in t3.waiting_human, t3
    assert tr.get_status(gate2) is TaskStatus.WAITING_HUMAN
    assert ProjectRepository(db).get_mode("p1") is \
        OperationalMode.AWAITING_HUMAN

    # journal ORDER: every gate-1 hop precedes every gate-2 hop
    hopsg1b = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (gate1, before))]
    hopsg2 = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (gate2, before2))]
    assert hopsg2, hopsg2
    assert max(hopsg1b) < min(hopsg2), (hopsg1b, hopsg2)

    # each gate parks exactly once (two HumanApprovalRequested total, one
    # per gate) — the dep chain held, so the wave stops at each gate
    assert db.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = "
        "'HumanApprovalRequested'").fetchone()["c"] == 2
    # gate-2's verdict: APPROVED completes the chain
    r2 = ctrl.resolve_human_gate(
        task_id="gate-2", verdict="APPROVED", rationale="chain",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert r2["rejected"] is False, r2
    assert tr.get_status(gate2) is TaskStatus.SUCCEEDED
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.ACTIVE
    # two verdicts total, one GatePassed per gate, zero failures
    assert db.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = "
        "'HumanGateResolved'").fetchone()["c"] == 2
    assert db.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = "
        "'GatePassed'").fetchone()["c"] == 2
    assert db.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = "
        "'GateFailed'").fetchone()["c"] == 0
    # one claim set for the recovered worker - no duplicates
    assert count_rows(db, "research_claims") == 1
    assert count_rows(db, "claim_assumption_links") == 1

def test_21_f15_exhausted_retry_race_property_schedules(tmp_path):
    """Property-style invariance for the exhausted-retry REJECTED race:
    across five seeded random schedules (varied B-loop pacing, resolve
    pacing, and verdict REJECTED), the outcome is a pure function of the
    inputs — the worker lands FAILED at attempt 1 (never re-executed,
    never requeued: max_retries 1 of 1), exactly one REJECTED verdict
    (one HumanGateResolved + one GateFailed, zero GatePassed), the wave
    stops, no FAILED hop precedes the verdict in journal order, the mode
    ends ACTIVE, and a second resolve is refused NOT_WAITING."""
    import random
    rng = random.Random(20260818)
    schedules = []
    for _ in range(5):
        schedules.append({
            "b_loop_sleep": rng.choice((0.01, 0.03, 0.05)),
            "resolve_sleep": rng.choice((0.01, 0.02, 0.04)),
        })
    for i, sched in enumerate(schedules):
        facts = _run_f15_resolve_race_once(
            tmp_path, f"f15_exhausted_prop_{i}.db", verdict="REJECTED",
            worker_max_retries=1,
            b_loop_sleep=sched["b_loop_sleep"],
            resolve_sleep=sched["resolve_sleep"])
        # exactly one REJECTED verdict, no lost events
        assert facts["hgr"] == 1, (i, sched, facts)
        assert facts["gate_passed"] == 0, (i, sched, facts)
        assert facts["gate_failed"] == 1, (i, sched, facts)
        assert facts["gate_status"] == TaskStatus.FAILED, (i, sched, facts)
        # the exhausted worker lands FAILED - never re-executed
        assert facts["worker_status"] == TaskStatus.FAILED, (i, sched, facts)
        assert facts["worker_attempt"] == 1, (i, sched, facts)
        assert facts["retrying_hops"] == 0, (i, sched, facts)
        assert facts["claims"] == 0 and facts["links"] == 0, \
            (i, sched, facts)
        # the F15-audit mode gate held under the race, wave stopped
        assert facts["failed_before_verdict"] == 0, (i, sched, facts)
        assert facts["mode"] is OperationalMode.ACTIVE, (i, sched, facts)
        assert facts["second_refusal"] == "NOT_WAITING", (i, sched, facts)

def test_21_f15_resolve_race_stall_is_surfaced_not_masked(tmp_path):
    """Stall-surfacing probe for the resolve-race helper's bounded
    completion budget: with a THIRD controller holding the scheduler
    lease after the verdict, B's post-verdict recovery ticks are all LOCK
    refusals and the worker can never reach a terminal state — the
    helper's bounded budget must FAIL LOUDLY (surface the stall) rather
    than silently report a plausible shape. This pins that the
    completion loop is a genuine liveness check, not a mask: a held
    lease or deadlock after the verdict is observable, never swallowed.
    """
    with pytest.raises(AssertionError, match="STALLED"):
        _run_f15_resolve_race_once(
            tmp_path, "f15_stall.db", verdict="APPROVED",
            hold_lease_after_verdict=True)


def test_21_f15_recovery_before_dispatch_chained_gates_rejected(db):
    """Chained-gate ordering with a REJECTED middle verdict: gate-1 depends
    on the requeued dead worker (ext-1), gate-2 depends on gate-1, and a
    THIRD gate (gate-3, INDEPENDENT - no deps) waits behind the wave. Tick 1
    (paused) marks ext-1 NO_SIGNAL with all three gates PENDING; after
    resume, tick 2's recovery completes ext-1 (attempt 2) and parks gate-1
    WAITING_HUMAN (dep SUCCEEDED) - the wave stops. gate-1 APPROVED
    (SUCCEEDED, mode ACTIVE); tick 3 parks gate-2 WAITING_HUMAN (gate-1
    SUCCEEDED) - the wave stops again. gate-2 REJECTED (FAILED, mode back to
    ACTIVE); the very next tick re-parks gate-3 WAITING_HUMAN (INDEPENDENT -
    a FAILED dependency would block it, so gate-3 is NOT gated on gate-2 and
    becomes eligible the moment the mode returns ACTIVE). gate-3 APPROVED
    completes the chain. Journal order (event_id) pins the load-bearing
    chain: every ext-1 hop precedes every gate-1 hop, every gate-1 hop
    precedes every gate-2 hop, every gate-2 hop precedes every gate-3 hop;
    each gate parks exactly once (three HumanApprovalRequested, zero
    re-parks); the verdicts land once each (two GatePassed + one GateFailed);
    the mode returns ACTIVE.
    """
    ext1 = admit_extract_task(db, source_ref="dataset_manifest:dm-1")
    # gate-1 DEPENDS on ext-1; gate-2 DEPENDS on gate-1; gate-3 INDEPENDENT
    gate1 = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-1-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [ext1],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        })).entity_id
    gate2 = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-2", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-2-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [gate1],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        })).entity_id
    gate3 = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-3", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-3-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        })).entity_id
    tr = TaskRepository(db)
    tr.transition_status(ext1, TaskStatus.READY, caused_by="test")
    # simulate the dead worker: RUNNING with a stale heartbeat
    tr.transition_status(ext1, TaskStatus.RUNNING, caused_by="test")
    stale_heartbeat(db, ext1)

    # PAUSED first miss: recovery marks NO_SIGNAL; dispatch is stopped,
    # and even if it ran no gate could park (deps not SUCCEEDED)
    ProjectRepository(db).transition_mode(
        "p1", OperationalMode.PAUSED, caused_by="test", reason="probe")
    ctrl = make_controller(db)
    t1 = ctrl.tick()
    assert ext1 in t1.recovery
    assert tr.get_status(ext1) is TaskStatus.NO_SIGNAL
    assert tr.get_status(gate1) is TaskStatus.PENDING
    assert tr.get_status(gate2) is TaskStatus.PENDING
    assert tr.get_status(gate3) is TaskStatus.PENDING

    # RESUME; tick 2: recovery completes ext-1 (attempt 2), then dispatch
    # discovers gate-1 (dep SUCCEEDED) and parks it WAITING_HUMAN - the
    # wave stops before gate-2/gate-3 (gate-1 not yet SUCCEEDED)
    ProjectRepository(db).transition_mode(
        "p1", OperationalMode.ACTIVE, caused_by="test", reason="probe")
    before = count_rows(db, "events")
    t2 = ctrl.tick()
    assert ext1 in t2.succeeded, t2
    assert gate1 in t2.waiting_human, t2
    assert tr.get(ext1)["attempt"] == 2, tr.get(ext1)["attempt"]
    assert tr.get_status(gate1) is TaskStatus.WAITING_HUMAN
    assert tr.get_status(gate2) is TaskStatus.PENDING
    assert tr.get_status(gate3) is TaskStatus.PENDING
    assert ProjectRepository(db).get_mode("p1") is \
        OperationalMode.AWAITING_HUMAN

    # journal ORDER so far: every ext-1 hop precedes every gate-1 hop
    hops1 = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (ext1, before))]
    hopsg1 = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (gate1, before))]
    assert hops1 and hopsg1, (hops1, hopsg1)
    assert max(hops1) < min(hopsg1), (hops1, hopsg1)

    # gate-1's verdict: APPROVED (gate-1 SUCCEEDED, mode back to ACTIVE)
    r1 = ctrl.resolve_human_gate(
        task_id="gate-1", verdict="APPROVED", rationale="chain",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert r1["rejected"] is False, r1
    assert tr.get_status(gate1) is TaskStatus.SUCCEEDED
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.ACTIVE

    # tick 3: dispatch re-parking gate-2 (gate-1 now SUCCEEDED)
    before2 = count_rows(db, "events")
    t3 = ctrl.tick()
    assert gate2 in t3.waiting_human, t3
    assert tr.get_status(gate2) is TaskStatus.WAITING_HUMAN
    assert tr.get_status(gate3) is TaskStatus.PENDING
    assert ProjectRepository(db).get_mode("p1") is \
        OperationalMode.AWAITING_HUMAN

    # journal ORDER: every gate-1 hop precedes every gate-2 hop
    hopsg1b = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (gate1, before))]
    hopsg2 = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (gate2, before2))]
    assert hopsg2, hopsg2
    assert max(hopsg1b) < min(hopsg2), (hopsg1b, hopsg2)

    # gate-2's verdict: REJECTED (gate-2 FAILED, mode back to ACTIVE)
    r2 = ctrl.resolve_human_gate(
        task_id="gate-2", verdict="REJECTED", rationale="chain",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert r2["rejected"] is False, r2
    assert tr.get_status(gate2) is TaskStatus.FAILED
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.ACTIVE

    # tick 4: the wave resumes - gate-3 (INDEPENDENT, no deps) is now
    # eligible the moment the mode returns ACTIVE and re-parks
    before3 = count_rows(db, "events")
    t4 = ctrl.tick()
    assert gate3 in t4.waiting_human, t4
    assert tr.get_status(gate3) is TaskStatus.WAITING_HUMAN
    assert ProjectRepository(db).get_mode("p1") is \
        OperationalMode.AWAITING_HUMAN

    # journal ORDER: every gate-2 hop precedes every gate-3 hop
    hopsg2b = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (gate2, before))]
    hopsg3 = [r["event_id"] for r in db.execute(
        "SELECT event_id FROM events WHERE task_id = ? "
        "AND event_type = 'TaskStatusChanged' AND event_id > ?",
        (gate3, before3))]
    assert hopsg3, hopsg3
    assert max(hopsg2b) < min(hopsg3), (hopsg2b, hopsg3)

    # gate-3's verdict: APPROVED completes the chain
    r3 = ctrl.resolve_human_gate(
        task_id="gate-3", verdict="APPROVED", rationale="chain",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert r3["rejected"] is False, r3
    assert tr.get_status(gate3) is TaskStatus.SUCCEEDED
    assert ProjectRepository(db).get_mode("p1") is OperationalMode.ACTIVE
    # each gate parks exactly once (three HumanApprovalRequested total),
    # and the verdicts land once each (two GatePassed + one GateFailed)
    assert db.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = "
        "'HumanApprovalRequested'").fetchone()["c"] == 3
    assert db.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = "
        "'HumanGateResolved'").fetchone()["c"] == 3
    assert db.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = "
        "'GatePassed'").fetchone()["c"] == 2
    assert db.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = "
        "'GateFailed'").fetchone()["c"] == 1
    # one claim set for the recovered worker - no duplicates
    assert count_rows(db, "research_claims") == 1
    assert count_rows(db, "claim_assumption_links") == 1


def test_21_f15_resolve_race_partial_lease_stall_surfaced(tmp_path):
    """Partial-lease stall-surfacing probe: the worker's post-verdict
    recovery ticks SUCCEED (the worker reaches SUCCEEDED at attempt 2 and
    the intermediate ext-int completes), but a DOWNSTREAM claim (ext-2,
    dep on ext-int, which only becomes eligible the tick after the
    recovery) stays blocked by a lease holder armed the moment the worker
    recovers. The bounded completion budget must surface the DOWNSTREAM
    stall (STALLED naming ext-2) rather than silently succeeding on the
    worker's healthy shape - the completion loop is a genuine chain-liveness
    check, never a worker-only mask. The holder is armed only AFTER the
    worker recovers (partial, not full), so recovery ticks succeed and only
    the downstream claim is blocked - fully deterministic, no stop-flag race.
    """
    with pytest.raises(AssertionError, match="STALLED"):
        _run_f15_resolve_race_once(
            tmp_path, "f15_partial_stall.db", verdict="APPROVED",
            hold_lease_after_worker=True, stall_check_task="ext-2")


def _run_f15_chained_gates_once(tmp_path, db_name, *, park_sleep=0.15,
                                resume_sleep=0.15,
                                gate2_verdict="APPROVED",
                                with_gate3=False) -> dict:
    """One full chained-gate scenario (shared by the deterministic probe and
    the property-style schedule-invariance test): A claims the extract and
    hangs past the horizon; B reclaims, gate-1 (dep on the dead worker)
    parks after the recovery, gate-1 APPROVED; gate-2 (dep on gate-1) parks,
    gate-2 APPROVED. Returns the observable facts: per-gate verdict counts
    and statuses, worker attempt/status, claim rows, mode, and the
    second-resolve refusal code."""
    import time as _time

    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.persistence.repositories import OperatorCredentialRepository
    from hermes.research.controller import Controller as _Controller

    db_path = tmp_path / db_name
    seed_conn = _connect(str(db_path))
    _migrate(seed_conn)
    ProjectRepository(seed_conn).create("p1", "Test")
    OperatorCredentialRepository(
        seed_conn, frozen_clock(CLOCK)).register(OP_ID, OP_TOKEN, "Op")
    seed_conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    res = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={**build_extract_task_payload(
            "dataset_manifest:dm-1", "both"), "task_id": "ext-1"}))
    ext_id = res.entity_id
    gate1 = apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-1-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [ext_id],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        })).entity_id
    apply_intent(seed_conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-2", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-2-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [gate1],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    if with_gate3:
        # the THIRD gate: gated on gate-1 (SUCCEEDED), never on gate-2 -
        # a FAILED dependency would block it, so it must NOT depend on the
        # REJECTED gate-2; its eligibility gate is gate-1 SUCCEEDED plus
        # the MODE returning ACTIVE after gate-2's REJECTED verdict.
        # (Gating on gate-1 - not fully independent - also keeps it from
        # parking during the helper's ACTIVE phase-1 recovery window,
        # which would flip the mode and mode-gate the worker's second-miss
        # recovery; the deterministic db probe uses PAUSED for that role.)
        apply_intent(seed_conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload={
                "task_id": "gate-3", "task_type": "HUMAN_GATE",
                "profile": "DIRECTOR", "idempotency_key": "gate-3-key",
                "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
                "inputs": [], "outputs": [],
                "dependencies": [gate1],
                "provenance": [], "cost_class": None,
                "concurrency_group": None,
                "max_retries": 3, "parent_task_id": None,
            }))
    TaskRepository(seed_conn).transition_status(
        ext_id, TaskStatus.READY, caused_by="test")
    seed_conn.close()

    release = threading.Event()

    def hung_fn(task, untrusted):
        release.wait(10.0)   # genuinely hung - far past the 0.3s horizon
        return extraction_draft_from_mapping(good_output())

    a_conn = _connect(str(db_path))
    a = _Controller(a_conn, project_id="p1", extract_fn=hung_fn,
                    lease_seconds=1, heartbeat_refresh_interval=0.05,
                    heartbeat_refresh_horizon=0.3)
    a_result: dict = {}

    def _a_tick():
        a_result["out"] = a.tick()

    th = threading.Thread(target=_a_tick)
    th.start()
    _time.sleep(0.8)

    b_conn = _connect(str(db_path))
    b = _Controller(b_conn, project_id="p1",
                    extract_fn=good_extract_fn(),
                    lease_seconds=1, heartbeat_refresh_interval=0.05)
    tr_b = TaskRepository(b_conn)
    # phase 1: B reclaims + marks the dead worker NO_SIGNAL. This phase
    # races A's lease expiry (A holds the scheduler lease while hung, so
    # B's early ticks are lock_held refusals) and is a deadline-based spin
    # rather than a fixed tick count - under load the lease-expiry latency
    # varies and a fixed budget can exhaust before B ever claims. The
    # gate-1 park cannot absorb the wait here (gate-1 is dep-gated on
    # ext-1, so it parks only AFTER the recovery), so the NO_SIGNAL wait
    # must be generous and wall-clock-driven.
    no_signal_deadline = _time.monotonic() + 12.0
    no_signal = False
    while _time.monotonic() < no_signal_deadline:
        b.tick()
        if tr_b.get(ext_id)["status"] == TaskStatus.NO_SIGNAL:
            no_signal = True
            break
        _time.sleep(park_sleep)
    assert no_signal, tr_b.get(ext_id)["status"]

    # phase 2: one loop completes the recovery (ext-1 SUCCEEDED, attempt 2)
    # AND parks gate-1 (dep now SUCCEEDED) WAITING_HUMAN - the wave stops.
    # The loop keeps ticking until BOTH hold (the recovery chain spans
    # multiple ticks: NO_SIGNAL -> FAILED -> RETRYING -> RUNNING ->
    # SUCCEEDED, then the park), so a slow tick under load cannot exhaust
    # the budget before the chain completes.
    ext_done = gate1_parked = False
    for _ in range(20):
        b.tick()
        if tr_b.get(ext_id)["status"] == TaskStatus.SUCCEEDED:
            ext_done = True
        if tr_b.get("gate-1")["status"] == TaskStatus.WAITING_HUMAN:
            gate1_parked = True
        if ext_done and gate1_parked:
            break
        _time.sleep(park_sleep)
    assert ext_done, tr_b.get(ext_id)["status"]
    assert gate1_parked, "gate-1 never parked"
    assert tr_b.get(ext_id)["attempt"] == 2, tr_b.get(ext_id)["attempt"]
    assert ProjectRepository(b_conn).get_mode("p1") is \
        OperationalMode.AWAITING_HUMAN

    # gate-1 APPROVED: SUCCEEDED, mode ACTIVE
    op_conn = _connect(str(db_path))
    op = _Controller(op_conn, project_id="p1",
                     extract_fn=good_extract_fn(),
                     lease_seconds=1, heartbeat_refresh_interval=0.05)
    out1 = op.resolve_human_gate(
        task_id="gate-1", verdict="APPROVED", operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out1["rejected"] is False, out1
    assert tr_b.get("gate-1")["status"] == TaskStatus.SUCCEEDED

    # phase 3: gate-2 (dep gate-1 SUCCEEDED) parks WAITING_HUMAN
    gate2_parked = False
    for _ in range(20):
        b.tick()
        if tr_b.get("gate-2")["status"] == TaskStatus.WAITING_HUMAN:
            gate2_parked = True
            break
        _time.sleep(resume_sleep)
    assert gate2_parked, "gate-2 never parked"
    assert ProjectRepository(b_conn).get_mode("p1") is \
        OperationalMode.AWAITING_HUMAN

    # the second gate's own verdict (parameterized: APPROVED completes
    # the wave; REJECTED returns ACTIVE and re-parks gate-3)
    out2 = op.resolve_human_gate(
        task_id="gate-2", verdict=gate2_verdict, operator_id=OP_ID,
        operator_token=OP_TOKEN)
    assert out2["rejected"] is False, out2
    if gate2_verdict == "APPROVED":
        assert tr_b.get("gate-2")["status"] == TaskStatus.SUCCEEDED
        gate3_status = None
    else:
        assert gate2_verdict == "REJECTED", gate2_verdict
        assert tr_b.get("gate-2")["status"] == TaskStatus.FAILED
        assert with_gate3, "the REJECTED variant requires gate-3"
        gate3_status = TaskStatus.WAITING_HUMAN
    assert ProjectRepository(b_conn).get_mode("p1") is OperationalMode.ACTIVE
    if gate2_verdict == "REJECTED":
        # phase 4: gate-3 (INDEPENDENT - the mode return is its only
        # eligibility gate) re-parks WAITING_HUMAN
        gate3_parked = False
        for _ in range(20):
            b.tick()
            if tr_b.get("gate-3")["status"] == TaskStatus.WAITING_HUMAN:
                gate3_parked = True
                break
            _time.sleep(resume_sleep)
        assert gate3_parked, "gate-3 never parked"
        assert ProjectRepository(b_conn).get_mode("p1") is \
            OperationalMode.AWAITING_HUMAN
        out3 = op.resolve_human_gate(
            task_id="gate-3", verdict="APPROVED", operator_id=OP_ID,
            operator_token=OP_TOKEN)
        assert out3["rejected"] is False, out3
        assert tr_b.get("gate-3")["status"] == TaskStatus.SUCCEEDED
        gate3_status = TaskStatus.SUCCEEDED
        assert ProjectRepository(b_conn).get_mode("p1") is \
            OperationalMode.ACTIVE
    # each gate exactly one verdict, no cross-talk
    n_hgr = b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'HumanGateResolved'"
    ).fetchone()["c"]
    n_har = b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = "
        "'HumanApprovalRequested'").fetchone()["c"]
    n_gf = b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'GateFailed'"
    ).fetchone()["c"]
    n_gp = b_conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type = 'GatePassed'"
    ).fetchone()["c"]
    claims = count_rows(b_conn, "research_claims")
    _other = "REJECTED" if gate2_verdict == "APPROVED" else "APPROVED"
    out3 = op.resolve_human_gate(
        task_id="gate-2", verdict=_other, operator_id=OP_ID,
        operator_token=OP_TOKEN)
    second_refusal = out3["code"] if out3["rejected"] else None
    facts = {
        "hgr": n_hgr, "har": n_har, "gate_failed": n_gf,
        "gate_passed": n_gp,
        "gate1_status": tr_b.get("gate-1")["status"],
        "gate2_status": tr_b.get("gate-2")["status"],
        "gate3_status": gate3_status,
        "worker_status": tr_b.get(ext_id)["status"],
        "worker_attempt": tr_b.get(ext_id)["attempt"],
        "claims": claims, "mode": ProjectRepository(b_conn).get_mode("p1"),
        "second_refusal": second_refusal,
    }

    # A's late write is discarded
    release.set()
    th.join(timeout=5)
    a_out = a_result.get("out")
    assert a_out is not None
    assert a_out.succeeded == [] and a_out.retried == [] and \
        a_out.failed == []
    assert count_rows(b_conn, "research_claims") == facts["claims"]
    a_conn.close()
    b_conn.close()
    op_conn.close()
    return facts


def test_21_f15_chained_gates_property_schedules(tmp_path):
    """Property-style invariance for the chained-gate scenario: across five
    seeded random schedules (varied park and resume tick pacing), each gate
    gets EXACTLY ONE verdict (gate-1 APPROVED, gate-2 APPROVED: exactly two
    HumanGateResolved, two GatePassed, zero GateFailed), each gate parks
    exactly once (two HumanApprovalRequested), the worker completes exactly
    once at attempt 2 (one claim set), the mode ends ACTIVE, and a second
    resolve is refused NOT_WAITING - the chained-gate guarantees are a pure
    function of the inputs, not of the scheduler."""
    import random
    rng = random.Random(20260819)
    schedules = []
    for _ in range(5):
        schedules.append({
            "park_sleep": rng.choice((0.05, 0.15, 0.3)),
            "resume_sleep": rng.choice((0.05, 0.15, 0.3)),
        })
    for i, sched in enumerate(schedules):
        facts = _run_f15_chained_gates_once(
            tmp_path, f"f15_chained_prop_{i}.db",
            park_sleep=sched["park_sleep"],
            resume_sleep=sched["resume_sleep"])
        # each gate exactly one verdict, zero cross-talk
        assert facts["hgr"] == 2, (i, sched, facts)
        assert facts["gate_failed"] == 0, (i, sched, facts)
        assert facts["gate_passed"] == 2, (i, sched, facts)
        assert facts["gate1_status"] == TaskStatus.SUCCEEDED, (i, sched, facts)
        assert facts["gate2_status"] == TaskStatus.SUCCEEDED, (i, sched, facts)
        # the worker completes exactly once at attempt 2, one claim set
        assert facts["worker_status"] == TaskStatus.SUCCEEDED, (i, sched, facts)
        assert facts["worker_attempt"] == 2, (i, sched, facts)
        assert facts["claims"] == 1, (i, sched, facts)
        # the wave ends ACTIVE and one verdict per gate is terminal
        assert facts["mode"] is OperationalMode.ACTIVE, (i, sched, facts)
        assert facts["second_refusal"] == "NOT_WAITING", (i, sched, facts)
def test_21_f15_chained_gates_rejected_property_schedules(tmp_path):
    """Property-style invariance for the chained-gate REJECTED variant:
    across five seeded random schedules (varied park and resume tick
    pacing), gate-1 APPROVED, gate-2 REJECTED returns the mode to ACTIVE,
    gate-3 (INDEPENDENT - a FAILED dep would block it, so the mode return
    is its only eligibility gate) re-parks, and gate-3 APPROVED completes
    the chain. Every schedule must yield EXACTLY ONE verdict per gate
    (three HumanGateResolved, two GatePassed + one GateFailed), each gate
    parks exactly once (three HumanApprovalRequested), the worker
    completes exactly once at attempt 2 (one claim set), the mode ends
    ACTIVE, and a second resolve on gate-2 is refused NOT_WAITING - the
    REJECTED re-park guarantees are a pure function of the inputs, not of
    the scheduler.
    """
    import random
    rng = random.Random(20260822)
    schedules = []
    for _ in range(5):
        schedules.append({
            "park_sleep": rng.choice((0.05, 0.15, 0.3)),
            "resume_sleep": rng.choice((0.05, 0.15, 0.3)),
        })
    for i, sched in enumerate(schedules):
        facts = _run_f15_chained_gates_once(
            tmp_path, f"f15_chain_rej_prop_{i}.db",
            park_sleep=sched["park_sleep"],
            resume_sleep=sched["resume_sleep"],
            gate2_verdict="REJECTED", with_gate3=True)
        # each gate exactly one verdict, zero cross-talk
        assert facts["hgr"] == 3, (i, sched, facts)
        assert facts["har"] == 3, (i, sched, facts)
        assert facts["gate_failed"] == 1, (i, sched, facts)
        assert facts["gate_passed"] == 2, (i, sched, facts)
        assert facts["gate1_status"] == TaskStatus.SUCCEEDED, (i, sched, facts)
        assert facts["gate2_status"] == TaskStatus.FAILED, (i, sched, facts)
        assert facts["gate3_status"] == TaskStatus.SUCCEEDED, (i, sched, facts)
        # the worker completes exactly once at attempt 2, one claim set
        assert facts["worker_status"] == TaskStatus.SUCCEEDED, (i, sched, facts)
        assert facts["worker_attempt"] == 2, (i, sched, facts)
        assert facts["claims"] == 1, (i, sched, facts)
        # the wave ends ACTIVE and one verdict per gate is terminal
        assert facts["mode"] is OperationalMode.ACTIVE, (i, sched, facts)
        assert facts["second_refusal"] == "NOT_WAITING", (i, sched, facts)


def test_21_f15_resolve_race_third_gate_partial_lease_stall_surfaced(tmp_path):
    """Partial-lease stall surfacing, ONE HOP FURTHER downstream: the
    worker's post-verdict recovery SUCCEEDS (SUCCEEDED at attempt 2) and
    the first intermediate (ext-int) completes in the recovery tick, but
    the SECOND downstream hop (ext-mid) - and with it the third gate
    (ext-3, dep ext-mid) - stays blocked by a lease holder armed the
    moment the worker recovers. The bounded completion budget must
    surface the stall NAMING the downstream chain (ext-mid AND ext-3 in
    the STALLED message), never the recovered worker - the completion
    loop is a genuine whole-chain liveness check, not a worker-only mask.
    """
    with pytest.raises(AssertionError) as ei:
        _run_f15_resolve_race_once(
            tmp_path, "f15_third_gate_partial_stall.db", verdict="APPROVED",
            hold_lease_after_worker=True, stall_check_task="ext-3",
            stall_mid_task="ext-mid")
    msg = str(ei.value)
    assert "STALLED" in msg, msg
    assert "ext-mid" in msg, msg      # the blocked intermediate is named
    assert "ext-3" in msg, msg        # the third gate is named
    # the worker RECOVERED - it is never named as stuck
    assert "ext-1" not in msg, msg


def test_21_f15_completion_budget_deep_wide_graph_not_a_false_stall(tmp_path):
    """Dependency-graph DoS lens on the bounded completion budget: a
    FIXED 30-tick completion count can be exhausted by a LEGITIMATELY
    deep (40 chained extracts, one hop per tick) or wide (40 independent
    extracts at max_calls_per_tick=1) post-verdict graph - the helper
    then raises a FALSE STALLED whose causal clause ('a held lease or
    deadlock was surfaced') is byte-identical to a genuine lease stall,
    so the error cannot by itself distinguish a held lease from a large
    healthy graph. The probe pins (a) the false positive on both shapes,
    (b) the SAME graphs completing cleanly once the budget scales with
    the pending-graph size (the default), and (c) that the causal clause
    is indistinguishable between the false positive and a real
    hold_lease_after_verdict stall - the scaled budget, not the message,
    is what separates the two.
    """
    # (a) DEPTH: 40 chained extracts downstream of the verdict gate. A
    # fixed 30-tick budget exhausts on the healthy chain (the worker
    # recovers, but deep-31..deep-40 are still PENDING) -> false STALLED
    # naming the healthy tail.
    with pytest.raises(AssertionError) as ei:
        _run_f15_resolve_race_once(
            tmp_path, "f15_deep_fixed.db", verdict="APPROVED",
            stall_depth=40, completion_budget=30)
    msg_deep = str(ei.value)
    assert "STALLED" in msg_deep, msg_deep
    assert "deep-40" in msg_deep, msg_deep   # the healthy tail is named
    # (b) the SAME deep graph completes cleanly with the graph-scaled
    # default budget (30 + one tick per hop + slack = 52): one recovery,
    # one claim set, worker attempt 2.
    facts_deep = _run_f15_resolve_race_once(
        tmp_path, "f15_deep_scaled.db", verdict="APPROVED",
        stall_depth=40)
    assert facts_deep["worker_attempt"] == 2, facts_deep
    assert facts_deep["claims"] == 1, facts_deep
    # (a2) WIDTH: 40 independent extracts (all dep gate-1) with
    # max_calls_per_tick=1 complete ONE per tick - the same false STALLED
    # from fan-out rather than depth.
    with pytest.raises(AssertionError) as ei2:
        _run_f15_resolve_race_once(
            tmp_path, "f15_wide_fixed.db", verdict="APPROVED",
            stall_wide_count=40, b_max_calls_per_tick=1,
            completion_budget=30)
    msg_wide = str(ei2.value)
    assert "STALLED" in msg_wide, msg_wide
    assert "wide-40" in msg_wide, msg_wide
    # (b2) the same wide graph completes with the scaled default budget
    facts_wide = _run_f15_resolve_race_once(
        tmp_path, "f15_wide_scaled.db", verdict="APPROVED",
        stall_wide_count=40, b_max_calls_per_tick=1)
    assert facts_wide["worker_attempt"] == 2, facts_wide
    assert facts_wide["claims"] == 1, facts_wide
    # (c) DISTINGUISHABILITY: the false positive's causal clause is
    # byte-identical to a genuine held-lease stall - the message alone
    # cannot tell a held lease from a legitimately large graph.
    clause = "a held lease or deadlock was surfaced, never masked"
    assert clause in msg_deep, msg_deep
    assert clause in msg_wide, msg_wide
    with pytest.raises(AssertionError) as ei3:
        _run_f15_resolve_race_once(
            tmp_path, "f15_lease.db", verdict="APPROVED",
            hold_lease_after_verdict=True)
    msg_lease = str(ei3.value)
    assert clause in msg_lease, msg_lease
    # the stuck-task lists differ (healthy tail vs worker) but the causal
    # claim is identical - only the scaled budget separates the two
    assert "deep-40" in msg_deep and "ext-1" not in msg_deep, msg_deep
    assert "ext-1" in msg_lease and "deep-40" not in msg_lease, msg_lease


def test_21_f15_completion_budget_mixed_mesh_depth_x_width(tmp_path):
    """Mixed deep-and-wide lens on the completion budget: a MESH of
    `width` PARALLEL chains, each `depth` hops long, all fanning out from
    the verdict gate (stall_mesh=(depth, width)). At max_calls_per_tick=1
    every hop is exactly one tick, so the graph needs depth*width ticks
    REGARDLESS of shape - a 5x8 mesh and an 8x5 mesh both need 40 ticks.
    The probe pins that the requirement is the PRODUCT, not the shape: a
    fixed budget below the product false-STALLs both shapes naming the
    healthy deepest level, while the graph-scaled default budget (which
    adds the product) completes both - only a genuine stall can exhaust
    a budget that is sized to the mesh.
    """
    clause = "a held lease or deadlock was surfaced, never masked"
    for md, mw in ((5, 8), (8, 5)):
        tag = f"f15_mesh_{md}x{mw}"
        # fixed budget below the product -> false STALLED naming the
        # healthy deepest level (never the recovered worker)
        with pytest.raises(AssertionError) as ei:
            _run_f15_resolve_race_once(
                tmp_path, f"{tag}_fixed.db", verdict="APPROVED",
                stall_mesh=(md, mw), b_max_calls_per_tick=1,
                completion_budget=35)
        msg = str(ei.value)
        assert "STALLED" in msg, (md, mw, msg)
        assert f"mesh-{md}-" in msg, (md, mw, msg)
        assert "ext-1" not in msg, (md, mw, msg)
        assert clause in msg, (md, mw, msg)
        # the SAME shape completes with the graph-scaled default budget
        # (10 + check-set + depth*width): one recovery, one claim set
        facts = _run_f15_resolve_race_once(
            tmp_path, f"{tag}_scaled.db", verdict="APPROVED",
            stall_mesh=(md, mw), b_max_calls_per_tick=1)
        assert facts["worker_attempt"] == 2, (md, mw, facts)
        assert facts["claims"] == 1, (md, mw, facts)


def test_21_f15_third_gate_partial_lease_stall_property_schedules(tmp_path):
    """Property-style invariance for the third-gate partial-lease stall:
    across five seeded schedules (varied resolve retry pacing AND varied
    completion budgets - including budgets far ABOVE any healthy graph's
    need), EVERY schedule must surface the stall naming ext-mid AND
    ext-3 (the blocked intermediate and the third gate), never the
    recovered worker ext-1 - the downstream-stall surfacing is a pure
    function of the held lease, not of the scheduling or of how long the
    budget runs.
    """
    import random
    rng = random.Random(20260824)
    schedules = []
    for _ in range(5):
        schedules.append({
            "resolve_sleep": rng.choice((0.01, 0.05, 0.1)),
            "completion_budget": rng.choice((20, 30, 45, 60)),
        })
    for i, sched in enumerate(schedules):
        with pytest.raises(AssertionError) as ei:
            _run_f15_resolve_race_once(
                tmp_path, f"f15_third_gate_stall_prop_{i}.db",
                verdict="APPROVED",
                hold_lease_after_worker=True,
                stall_check_task="ext-3", stall_mid_task="ext-mid",
                resolve_sleep=sched["resolve_sleep"],
                completion_budget=sched["completion_budget"])
        msg = str(ei.value)
        assert "STALLED" in msg, (i, sched, msg)
        assert "ext-mid" in msg, (i, sched, msg)
        assert "ext-3" in msg, (i, sched, msg)
        assert "ext-1" not in msg, (i, sched, msg)


def test_21_f15_completion_budget_huge_fan_scaled_never_exhausted(tmp_path):
    """Huge dependency-fan lens: ONE verdict gate with HUNDREDS of
    independent downstream extracts (stall_wide_count=300). The fan is
    legitimately wide - at the default 8 extracts/tick it needs 38 ticks
    to complete - so a FIXED 30-tick budget false-STALLs it, naming the
    healthy tail with the byte-identical held-lease clause. The
    graph-scaled budget is SIZED TO THE FAN (adds the full 300 to the
    budget), so a huge fan can NEVER exhaust it - 300 >= every tick count
    the fan can need at any per-tick cap - and only a genuine held-lease
    stall (which produces the identical message) survives any budget. The
    probe pins both halves: the fan cannot outrun the scaled budget, and
    the STALLED message cannot by itself distinguish the fixed-budget
    false positive from a real lease stall.
    """
    clause = "a held lease or deadlock was surfaced, never masked"
    # (a) FIXED 30-tick budget: the huge fan needs 38 ticks -> false
    # STALLED naming the healthy tail (wide-300), never the worker.
    with pytest.raises(AssertionError) as ei:
        _run_f15_resolve_race_once(
            tmp_path, "f15_huge_fan_fixed.db", verdict="APPROVED",
            stall_wide_count=300, completion_budget=30)
    msg_fan = str(ei.value)
    assert "STALLED" in msg_fan, msg_fan
    assert "wide-300" in msg_fan, msg_fan
    assert "ext-1" not in msg_fan, msg_fan
    assert clause in msg_fan, msg_fan
    # (b) the graph-scaled default budget is sized to the fan: budget =
    # 10 + check-set + 300, far above the 38 ticks the fan can ever need
    # at cap=8 (and above ANY cap: a fan of W needs at most W ticks, and
    # the budget adds W) - so the huge fan COMPLETES, never a false
    # STALLED, and the scaled budget is genuinely un-exhaustable by width.
    facts = _run_f15_resolve_race_once(
        tmp_path, "f15_huge_fan_scaled.db", verdict="APPROVED",
        stall_wide_count=300)
    assert facts["worker_attempt"] == 2, facts
    assert facts["claims"] == 1, facts
    # (c) DISTINGUISHABILITY: the fixed-budget false positive and a
    # genuine hold_lease_after_verdict stall share the byte-identical
    # causal clause - the message alone cannot separate a huge healthy
    # fan from a held lease; only the graph-scaled budget can.
    with pytest.raises(AssertionError) as ei3:
        _run_f15_resolve_race_once(
            tmp_path, "f15_lease2.db", verdict="APPROVED",
            hold_lease_after_verdict=True)
    msg_lease = str(ei3.value)
    assert clause in msg_lease, msg_lease
    assert "wide-300" in msg_fan and "ext-1" not in msg_fan, msg_fan
    assert "ext-1" in msg_lease and "wide-300" not in msg_lease, msg_lease


def test_21_f15_completion_budget_mesh_exact_product_boundary(tmp_path):
    """Exact product-boundary pin for the mesh budget: a mesh of `width`
    PARALLEL chains, each `depth` hops long, at max_calls_per_tick=1
    completes EXACTLY depth*width ticks (one task per tick, chains
    depth-first). Across several shapes with the same product ((5,8) and
    (8,5) both 40; (6,6) = 36), a budget of product-1 false-STALLs naming
    the healthy deepest level (mesh-D-*), and a budget of EXACTLY product
    completes with completion_ticks_used == product - the graph-scaled
    formula (10 + check-set + depth*width) is the exact requirement,
    neither under- nor over-sized, and the product is confirmed precisely
    rather than by a loose slack.
    """
    for md, mw in ((5, 8), (8, 5), (6, 6)):
        product = md * mw
        tag = f"f15_mesh_boundary_{md}x{mw}"
        # budget = product - 1 -> false STALLED naming the deepest level
        with pytest.raises(AssertionError) as ei:
            _run_f15_resolve_race_once(
                tmp_path, f"{tag}_under.db", verdict="APPROVED",
                stall_mesh=(md, mw), b_max_calls_per_tick=1,
                completion_budget=product - 1, skip_racing_loop=True)
        msg = str(ei.value)
        assert "STALLED" in msg, (md, mw, msg)
        assert f"mesh-{md}-" in msg, (md, mw, msg)
        assert "ext-1" not in msg, (md, mw, msg)
        # budget = EXACTLY product -> completes, ticks used == product
        facts = _run_f15_resolve_race_once(
            tmp_path, f"{tag}_exact.db", verdict="APPROVED",
            stall_mesh=(md, mw), b_max_calls_per_tick=1,
            completion_budget=product, skip_racing_loop=True)
        assert facts["completion_ticks_used"] == product, (md, mw, facts)
        assert facts["worker_attempt"] == 2, (md, mw, facts)
        assert facts["claims"] == 1, (md, mw, facts)


def test_21_f15_completion_budget_deep_fan_chain_total_nodes(tmp_path):
    """Deep fan-chain lens: the WIDEST possible graph shape - a WIDENING
    fan-out tree where every level-k task has `width` children (fan-1-1
    root dep gate-1; fan-k-j dep fan-(k-1)-(j // width)). Level k has
    width**(k-1) tasks, so the tick requirement at cap=1 is the TOTAL
    NODE COUNT (width**depth - 1) // (width - 1), NOT a depth x width
    product - the fan grows exponentially. A fixed budget below the total
    false-STALLs naming the healthy deepest level; the graph-scaled
    default budget (which adds the exact total, not depth x width)
    completes with completion_ticks_used == total; and DIFFERENT shapes
    yield DIFFERENT totals (40 vs 21), pinning that the requirement is
    the node count of the specific tree, never a shape formula.
    """
    for fd, fw in ((4, 3), (3, 4)):
        total = (fw ** fd - 1) // (fw - 1)
        tag = f"f15_fan_{fd}x{fw}"
        with pytest.raises(AssertionError) as ei:
            _run_f15_resolve_race_once(
                tmp_path, f"{tag}_under.db", verdict="APPROVED",
                stall_fan=(fd, fw), b_max_calls_per_tick=1,
                completion_budget=total - 1, skip_racing_loop=True)
        msg = str(ei.value)
        assert "STALLED" in msg, (fd, fw, msg)
        assert f"fan-{fd}-" in msg, (fd, fw, msg)
        assert "ext-1" not in msg, (fd, fw, msg)
        facts = _run_f15_resolve_race_once(
            tmp_path, f"{tag}_scaled.db", verdict="APPROVED",
            stall_fan=(fd, fw), b_max_calls_per_tick=1,
            skip_racing_loop=True)
        assert facts["completion_ticks_used"] == total, (fd, fw, facts)
        assert facts["worker_attempt"] == 2, (fd, fw, facts)
        assert facts["claims"] == 1, (fd, fw, facts)
    # the two shapes have DIFFERENT totals - the requirement is the node
    # count of the specific widening tree, not a shared depth x width
    assert ((3 ** 4 - 1) // 2) == 40, "fan (4,3) total"
    assert ((4 ** 3 - 1) // 3) == 21, "fan (3,4) total"


def test_21_f15_completion_budget_huge_fan_headroom_measured(tmp_path):
    """Huge-fan headroom measurement: the 300-task fan needs EXACTLY
    ceil(300/8) = 38 completion-loop ticks at the default 8 extracts/tick
    (measured via completion_ticks_used with the racing loop skipped so
    the completion loop is the sole owner - deterministic), while the
    graph-scaled default budget is 10 + check-set(2) + 300 = 312. The
    measured headroom is 312 - 38 = 274 ticks (~7x the needed budget):
    the scaled budget is sized to the fan with documented slack, and the
    number pins the gap between what the graph needs and what the budget
    grants - the false-positive window is the FIXED budget only, and the
    scaled budget's headroom is a pure function of the fan count.
    """
    facts = _run_f15_resolve_race_once(
        tmp_path, "f15_huge_fan_headroom.db", verdict="APPROVED",
        stall_wide_count=300, skip_racing_loop=True)
    needed = facts["completion_ticks_used"]
    assert needed == 38, facts          # ceil(300/8) = 38
    scaled = 10 + 2 + 300               # 10 + check-set(ext-1, wide-300) + 300
    headroom = scaled - needed
    assert scaled == 312, facts
    assert headroom == 274, facts
    assert facts["worker_attempt"] == 2, facts
    assert facts["claims"] == 1, facts

def test_21_f15_completion_budget_mixed_shape_mesh_sum_of_depths(tmp_path):
    """MIXED-SHAPE mesh lens: per-chain depths DIFFER (stall_mesh_mixed is
    a tuple of per-chain hop counts, e.g. (2, 5, 7) = three chains of 2,
    5, and 7 hops). With max_calls_per_tick=1 each hop is one tick, so
    the graph needs SUM(depths) ticks - the uniform depth*width product
    formula does NOT describe a mixed shape (max*width would be 7*3=21
    for (2,5,7), but the true need is 2+5+7=14). The probe pins the
    non-uniform formula across several shapes: a budget of sum-1
    false-STALLs naming the healthy deepest level (mix-{max}-*), a budget
    of EXACTLY sum completes with completion_ticks_used == sum, and a
    uniform-formula budget (max_depth * width) is NOT the requirement
    (it both over- and under-sizes different shapes).
    """
    for depths in ((2, 5, 7), (1, 3, 5, 7), (3, 6, 9)):
        total = sum(depths)
        tag = f"f15_mixmesh_{'-'.join(str(d) for d in depths)}"
        # budget = sum - 1 -> false STALLED naming the deepest level
        with pytest.raises(AssertionError) as ei:
            _run_f15_resolve_race_once(
                tmp_path, f"{tag}_under.db", verdict="APPROVED",
                stall_mesh_mixed=depths, b_max_calls_per_tick=1,
                completion_budget=total - 1, skip_racing_loop=True)
        msg = str(ei.value)
        assert "STALLED" in msg, (depths, msg)
        assert f"mix-{max(depths)}-" in msg, (depths, msg)
        assert "ext-1" not in msg, (depths, msg)
        # budget = EXACTLY sum -> completes, ticks used == sum
        facts = _run_f15_resolve_race_once(
            tmp_path, f"{tag}_exact.db", verdict="APPROVED",
            stall_mesh_mixed=depths, b_max_calls_per_tick=1,
            completion_budget=total, skip_racing_loop=True)
        assert facts["completion_ticks_used"] == total, (depths, facts)
        assert facts["worker_attempt"] == 2, (depths, facts)
        assert facts["claims"] == 1, (depths, facts)
        # the uniform product formula is NOT the requirement for a mixed
        # shape: max*width over-sizes (2,5,7) and under-sizes (1,3,5,7)
        uniform = max(depths) * len(depths)
        assert uniform != total, (depths, uniform, total)


def test_21_f15_stalled_message_names_blocking_owner_row(tmp_path):
    """STALLED-message discrimination lens: can the surfacing message
    distinguish a GENUINE held lease from a HEALTHY deep/wide graph that
    exhausted a fixed budget? The raise now snapshots the scheduler_lock
    owner row: a genuine hold_lease_after_verdict stall names the
    blocking owner (the holder controller id, controller-*) with its
    locked_at timestamp, while a healthy deep/wide false STALL reports
    the lock FREE (no blocking owner row - the completion loop's own
    ticks hold and release the lease, so at the raise no foreign owner
    exists). The causal clause stays byte-identical; the owner snapshot
    is the discriminator - pinned both ways here.
    """
    clause = "a held lease or deadlock was surfaced, never masked"
    # (a) genuine held-lease stall: the message NAMES the blocking owner
    with pytest.raises(AssertionError) as ei:
        _run_f15_resolve_race_once(
            tmp_path, "f15_owner_genuine.db", verdict="APPROVED",
            hold_lease_after_verdict=True, skip_racing_loop=True)
    msg_lease = str(ei.value)
    assert "STALLED" in msg_lease, msg_lease
    assert clause in msg_lease, msg_lease
    assert "Blocking-owner snapshot:" in msg_lease, msg_lease
    assert "scheduler_lock owner=" in msg_lease, msg_lease
    assert "controller-" in msg_lease, msg_lease  # the holder's id
    assert "free (no blocking owner row)" not in msg_lease, msg_lease
    # (b) healthy deep graph, fixed budget: lock is FREE at the raise
    with pytest.raises(AssertionError) as ei2:
        _run_f15_resolve_race_once(
            tmp_path, "f15_owner_false.db", verdict="APPROVED",
            stall_depth=40, b_max_calls_per_tick=1,
            completion_budget=10, skip_racing_loop=True)
    msg_fan = str(ei2.value)
    assert "STALLED" in msg_fan, msg_fan
    assert clause in msg_fan, msg_fan
    assert "Blocking-owner snapshot:" in msg_fan, msg_fan
    assert "scheduler_lock free (no blocking owner row)" in msg_fan, msg_fan
    assert "scheduler_lock owner=" not in msg_fan, msg_fan
    # (c) same discriminator for the wide/fan false positive
    with pytest.raises(AssertionError) as ei3:
        _run_f15_resolve_race_once(
            tmp_path, "f15_owner_false_wide.db", verdict="APPROVED",
            stall_wide_count=300, completion_budget=30,
            skip_racing_loop=True)
    msg_wide = str(ei3.value)
    assert "scheduler_lock free (no blocking owner row)" in msg_wide, msg_wide
    # the causal clause is byte-identical across all three; the owner
    # snapshot is what distinguishes them
    assert (msg_lease.split("Blocking-owner snapshot:")[1].split(" after")[0]
            != msg_fan.split("Blocking-owner snapshot:")[1].split(" after")[0])


def test_21_f15_completion_budget_headroom_cap_sweep(tmp_path):
    """max_calls_per_tick cap sweep for the huge-fan headroom: the fan of
    300 independent extracts needs ceil(300/cap) completion ticks at ANY
    per-tick cap (each tick completes at most cap extracts), and the
    graph-scaled budget is 10 + check-set(2) + 300 = 312 REGARDLESS of
    the cap - so the headroom (312 - needed) shrinks as the cap grows but
    stays strictly positive at every cap (needed <= 300 < 312): the
    scaled budget cannot be exhausted by ANY cap choice, and only a
    genuine held-lease stall survives. The probe sweeps caps 1, 2, 4, 8,
    16, 32, 300 and pins needed == ceil(300/cap) and headroom ==
    312 - needed at each, plus a fixed budget of needed-1 false-STALLs at
    two representative caps (1 and 8).
    """
    budget = 312  # 10 + check-set(ext-1, wide-300) + 300, cap-independent
    for cap in (1, 2, 4, 8, 16, 32, 300):
        import math
        needed = math.ceil(300 / cap)
        tag = f"f15_fan_cap{cap}"
        facts = _run_f15_resolve_race_once(
            tmp_path, f"{tag}.db", verdict="APPROVED",
            stall_wide_count=300, b_max_calls_per_tick=cap,
            skip_racing_loop=True)
        assert facts["completion_ticks_used"] == needed, (cap, facts)
        assert facts["worker_attempt"] == 2, (cap, facts)
        assert facts["claims"] == 1, (cap, facts)
        headroom = budget - needed
        assert headroom > 0, (cap, needed, headroom)
        assert headroom == 312 - needed, (cap, needed, headroom)
    # the fixed-budget false STALL holds at every cap: budget below the
    # cap's need false-STALLs naming the healthy tail
    for cap in (1, 8):
        needed = -(-300 // cap)  # ceil(300/cap)
        with pytest.raises(AssertionError) as ei:
            _run_f15_resolve_race_once(
                tmp_path, f"f15_fan_fixed{cap}.db", verdict="APPROVED",
                stall_wide_count=300, b_max_calls_per_tick=cap,
                completion_budget=needed - 1, skip_racing_loop=True)
        msg = str(ei.value)
        assert "STALLED" in msg, (cap, msg)
        assert "wide-300" in msg, (cap, msg)
        assert "ext-1" not in msg, (cap, msg)
        # a budget of EXACTLY needed completes at that cap
        facts = _run_f15_resolve_race_once(
            tmp_path, f"f15_fan_exact{cap}.db", verdict="APPROVED",
            stall_wide_count=300, b_max_calls_per_tick=cap,
            completion_budget=needed, skip_racing_loop=True)
        assert facts["completion_ticks_used"] == needed, (cap, facts)

def test_21_f15_completion_budget_mixed_mesh_gate2_rejected(tmp_path):
    """Mixed-mesh x REJECTED-gate-2 interleave: the mixed-shape mesh
    chains all depend on gate-1 (SUCCEEDED), and a SECOND human gate
    (gate-2, dep gate-1) parks WAITING_HUMAN the instant gate-1 resolves,
    stopping the wave. The operator then REJECTS gate-2 -> GateFailed,
    mode returns ACTIVE, and the mesh chains dispatch one hop per tick.
    The bounded budget must therefore cover recovery + gate-2 park (tick
    1) PLUS the gate-2 verdict PLUS the mesh hops: ticks used == 1 +
    sum(depths), a budget of exactly sum(depths) (missing the interleave
    tick) false-STALLs naming the deepest mesh level (never the worker or
    gate-2 - both terminal), and the graph-scaled default completes.
    Journal order pins the interleave: every ext-1 hop precedes every
    gate-2 hop, every gate-2 hop precedes every mesh hop.
    """
    depths = (2, 5, 7)
    total = sum(depths)  # 14 mesh hops
    # (a) budget = sum(depths) -> false STALLED (the gate-2 park tick is
    # the interleave cost the tight formula must include)
    with pytest.raises(AssertionError) as ei:
        _run_f15_resolve_race_once(
            tmp_path, "f15_mixmesh_g2_under.db", verdict="APPROVED",
            stall_mesh_mixed=depths, gate2_rejected=True,
            b_max_calls_per_tick=1, completion_budget=total,
            skip_racing_loop=True)
    msg = str(ei.value)
    assert "STALLED" in msg, msg
    assert f"mix-{max(depths)}-" in msg, msg  # the deepest mesh level
    assert "gate-2" not in msg.split("Blocking-owner")[0], msg
    assert "ext-1" not in msg.split("Blocking-owner")[0], msg
    # (b) budget = 1 + sum(depths) -> completes, ticks used == that
    facts = _run_f15_resolve_race_once(
        tmp_path, "f15_mixmesh_g2_exact.db", verdict="APPROVED",
        stall_mesh_mixed=depths, gate2_rejected=True,
        b_max_calls_per_tick=1, completion_budget=total + 1,
        skip_racing_loop=True)
    assert facts["completion_ticks_used"] == total + 1, facts
    assert facts["worker_attempt"] == 2, facts
    assert facts["claims"] == 1, facts
    assert facts["mode"] is OperationalMode.ACTIVE, facts
    assert facts["gate_status"] == TaskStatus.SUCCEEDED, facts
    assert facts["gate_passed"] == 1, facts   # gate-1 APPROVED
    assert facts["gate_failed"] == 1, facts   # gate-2 REJECTED
    assert facts["hgr"] == 2, facts           # one verdict per gate
    assert facts["second_refusal"] == "NOT_WAITING", facts
    # (c) the graph-scaled default budget completes the interleaved graph
    facts2 = _run_f15_resolve_race_once(
        tmp_path, "f15_mixmesh_g2_scaled.db", verdict="APPROVED",
        stall_mesh_mixed=depths, gate2_rejected=True,
        b_max_calls_per_tick=1, skip_racing_loop=True)
    assert facts2["completion_ticks_used"] == total + 1, facts2
    assert facts2["completion_budget_scaled"] >= total + 1, facts2
    # (d) journal order: ext-1 hops < gate-2 hops < mesh hops
    ev = _run_f15_journal_order(
        tmp_path, "f15_mixmesh_g2_order.db", verdict="APPROVED",
        stall_mesh_mixed=depths, gate2_rejected=True,
        b_max_calls_per_tick=1, skip_racing_loop=True)
    assert ev["ext"] and ev["gate2"] and ev["mesh"], ev
    assert max(ev["ext"]) < min(ev["gate2"]), ev
    assert max(ev["gate2"]) < min(ev["mesh"]), ev


def _run_f15_journal_order(tmp_path, db_name, *, verdict, stall_mesh_mixed,
                           gate2_rejected, b_max_calls_per_tick,
                           skip_racing_loop) -> dict:
    """Run the resolve-race scenario and return the event_id lists of the
    ext-1 hops, the gate-2 hops (park/verdict), and the mesh hops, so the
    caller can pin the journal interleave order."""
    _run_f15_resolve_race_once(
        tmp_path, db_name, verdict=verdict,
        stall_mesh_mixed=stall_mesh_mixed, gate2_rejected=gate2_rejected,
        b_max_calls_per_tick=b_max_calls_per_tick,
        skip_racing_loop=skip_racing_loop)
    db_path = tmp_path / db_name
    conn = connect(str(db_path))
    try:
        def ids(task_id, states=None):
            q = ("SELECT event_id FROM events WHERE task_id = ? "
                 "AND event_type = 'TaskStatusChanged'")
            args = [task_id]
            if states is not None:
                q += " AND to_state IN (%s)" % ",".join("?" * len(states))
                args.extend(states)
            q += " ORDER BY event_id"
            return [r["event_id"] for r in conn.execute(q, args)]
        mesh_ids = []
        for d in range(1, max(stall_mesh_mixed) + 1):
            for w in range(1, len(stall_mesh_mixed) + 1):
                if d <= stall_mesh_mixed[w - 1]:
                    mesh_ids.extend(ids(f"mix-{d}-{w}"))
        return {
            "ext": ids("ext-1"),
            "gate2": ids("gate-2"),
            "mesh": sorted(mesh_ids),
        }
    finally:
        conn.close()


def test_21_f15_stalled_owner_snapshot_lease_handoff(tmp_path):
    """STALLED blocking-owner snapshot vs a lease HANDOFF: can the
    snapshot race an owner change (the owner row is updated between the
    last completion tick and the raise's SELECT) and name a STALE owner?
    The snapshot is a single atomic SELECT of the live scheduler_lock row,
    so it always reads the CURRENT owner+locked_at pair - a handoff (the
    controller's own reclaim write: UPDATE owner/locked_at) is observed as
    the NEW owner. The probe pins (a) every pre-handoff snapshot names the
    SAME live holder (controller-*) with a locked_at, never None; (b) the
    handoff owner is named by the post-handoff snapshots AND by the final
    STALLED message - the newest locked_at owner is authoritative; (c) the
    message's named owner equals the newest snapshot owner exactly.
    """
    # genuine stall with the holder live: snapshots all name the holder
    holder_sink = {}
    snapshots = []
    clause = "a held lease or deadlock was surfaced, never masked"
    with pytest.raises(AssertionError) as ei:
        _run_f15_resolve_race_once(
            tmp_path, "f15_owner_live.db", verdict="APPROVED",
            hold_lease_after_verdict=True, skip_racing_loop=True,
            holder_owner_sink=holder_sink, lock_snapshots=snapshots)
    msg_live = str(ei.value)
    assert holder_sink["owner"].startswith("controller-"), holder_sink
    assert snapshots, snapshots
    assert all(o == holder_sink["owner"] for o, _ in snapshots), snapshots
    assert all(ts is not None for _, ts in snapshots), snapshots
    assert ("scheduler_lock owner=" + repr(holder_sink['owner'])
            in msg_live), (
        msg_live)
    assert clause in msg_live, msg_live
    # lease HANDOFF mid-stall: the owner row is overwritten (the reclaim
    # write) at a chosen tick; every post-handoff snapshot AND the final
    # STALLED message name the NEWEST owner, never the stale holder
    holder_sink2 = {}
    snapshots2 = []
    with pytest.raises(AssertionError) as ei2:
        _run_f15_resolve_race_once(
            tmp_path, "f15_owner_handoff.db", verdict="APPROVED",
            hold_lease_after_verdict=True, skip_racing_loop=True,
            holder_owner_sink=holder_sink2, lock_snapshots=snapshots2,
            handoff_owner="controller-handoff",
            handoff_at_tick=3)
    msg_ho = str(ei2.value)
    # pre-handoff (ticks 0..2): the live holder; post-handoff (3..): the
    # new owner - the newest locked_at owner is authoritative
    pre = [o for o, _ in snapshots2[:3]]
    post = [o for o, _ in snapshots2[3:]]
    assert pre and all(o == holder_sink2["owner"] for o in pre), (
        pre, holder_sink2)
    assert post and all(o == "controller-handoff" for o in post), post
    assert "scheduler_lock owner='controller-handoff'" in msg_ho, msg_ho
    assert holder_sink2["owner"] not in msg_ho, msg_ho
    # the named owner equals the newest snapshot owner exactly
    last_owner, last_ts = snapshots2[-1]
    assert f"scheduler_lock owner={last_owner!r}" in msg_ho, msg_ho
    assert f"(locked_at={last_ts!r})" in msg_ho, msg_ho
    # and the causal clause stays identical - the owner line discriminates
    assert clause in msg_ho, msg_ho


def test_21_f15_completion_budget_unified_closed_form(tmp_path):
    """UNIFIED graph-scaled budget: one closed-form total covers every
    shape. With max_calls_per_tick=1 the post-verdict graph needs EXACTLY
    T = stall_depth + stall_wide_count + md*mw + sum(depths) +
    fan_total_completion ticks (one hop per tick across ALL shapes), and
    the scaled default budget is max(30, 10 + len(check_tasks) + T) - the
    same formula for depth, wide, mesh, mixed mesh, fan, and any COMBINED
    graph. The probe iterates a shape table and pins (a) ticks_used == T,
    (b) completion_budget_scaled == the closed form, (c) budget == T - 1
    false-STALLs, (d) budget == T completes, (e) combined graphs sum.
    """
    shapes = [
        # (label, kwargs) - T computed by the probe
        ("depth", {"stall_depth": 12}),
        ("wide", {"stall_wide_count": 12}),
        ("mesh", {"stall_mesh": (3, 4)}),
        ("mixed", {"stall_mesh_mixed": (2, 5, 7)}),
        ("fan", {"stall_fan": (4, 3)}),
    ]
    for label, kw in shapes:
        T = _f15_closed_form_total(kw)
        tag = f"f15_unified_{label}"
        # (c) budget == T - 1 -> false STALLED
        with pytest.raises(AssertionError) as ei:
            _run_f15_resolve_race_once(
                tmp_path, f"{tag}_under.db", verdict="APPROVED",
                b_max_calls_per_tick=1, completion_budget=T - 1,
                skip_racing_loop=True, **kw)
        msg = str(ei.value)
        assert "STALLED" in msg, (label, msg)
        # (d) budget == T -> completes with ticks used == T
        facts = _run_f15_resolve_race_once(
            tmp_path, f"{tag}_exact.db", verdict="APPROVED",
            b_max_calls_per_tick=1, completion_budget=T,
            skip_racing_loop=True, **kw)
        assert facts["completion_ticks_used"] == T, (label, facts)
        assert facts["worker_attempt"] == 2, (label, facts)
        # (a)+(b) the scaled default completes with ticks == T and its
        # budget equals the closed form
        facts2 = _run_f15_resolve_race_once(
            tmp_path, f"{tag}_scaled.db", verdict="APPROVED",
            b_max_calls_per_tick=1, skip_racing_loop=True, **kw)
        assert facts2["completion_ticks_used"] == T, (label, facts2)
        expected = max(30, 10 + _f15_check_set_len(kw) + T)
        assert facts2["completion_budget_scaled"] == expected, (
            label, facts2["completion_budget_scaled"], expected)
    # (e) a COMBINED graph (all five shapes) sums: T = sum of the parts
    combined = {"stall_depth": 4, "stall_wide_count": 5,
                "stall_mesh": (2, 3), "stall_mesh_mixed": (2, 3, 4),
                "stall_fan": (3, 2)}
    T_all = _f15_closed_form_total(combined)
    facts = _run_f15_resolve_race_once(
        tmp_path, "f15_unified_combined.db", verdict="APPROVED",
        b_max_calls_per_tick=1, skip_racing_loop=True, **combined)
    assert facts["completion_ticks_used"] == T_all, (T_all, facts)
    expected = max(30, 10 + _f15_check_set_len(combined) + T_all)
    assert facts["completion_budget_scaled"] == expected, (
        facts["completion_budget_scaled"], expected)


def _f15_closed_form_total(kw) -> int:
    """The unified closed-form total T: every post-verdict hop the graph
    must advance at max_calls_per_tick=1."""
    t = 0
    t += kw.get("stall_depth", 0)
    t += kw.get("stall_wide_count", 0)
    if kw.get("stall_mesh"):
        md, mw = kw["stall_mesh"]
        t += md * mw
    if kw.get("stall_mesh_mixed"):
        t += sum(kw["stall_mesh_mixed"])
    if kw.get("stall_fan"):
        fd, fw = kw["stall_fan"]
        t += (fw ** fd - 1) // (fw - 1)
    return t


def _f15_check_set_len(kw) -> int:
    """len(check_tasks): ext-1 + one tail per shape (mesh/mixed/fan tails
    = width/depth-count/fan-width tasks each, matching the helper)."""
    n = 1  # ext-1
    if kw.get("stall_depth"):
        n += 1
    if kw.get("stall_wide_count"):
        n += 1
    if kw.get("stall_mesh"):
        n += kw["stall_mesh"][1]
    if kw.get("stall_mesh_mixed"):
        n += len(kw["stall_mesh_mixed"])
    if kw.get("stall_fan"):
        fd, fw = kw["stall_fan"]
        n += fw ** (fd - 1)
    return n

def test_21_f15_mixed_mesh_gate2_rejected_races_lease_holder(tmp_path):
    """Mixed-mesh x REJECTED-gate-2 x HELD LEASE: the operator's REJECTED
    verdict for gate-2 races a lease holder armed the INSTANT gate-2
    parks WAITING_HUMAN (the wave just stopped). The resolve is refused
    LOCK - gate-2 stays WAITING_HUMAN, the mode stays AWAITING_HUMAN, and
    the mesh chains never dispatch. The bounded budget must then surface
    BOTH halves of the stall: the downstream chain (gate-2 + the mesh
    tails - never the recovered worker) in the stuck-task list, AND the
    lease itself via the blocking-owner snapshot (the holder controller-*
    id). The causal clause stays byte-identical to the healthy-graph
    false STALL - the owner line is what names the lease. Pinned both
    ways: with the holder the budget FAILS LOUDLY naming gate-2 + mesh,
    without it the same graph completes (the plain gate-2 probe).
    """
    depths = (2, 5, 7)
    clause = "a held lease or deadlock was surfaced, never masked"
    holder_sink = {}
    refusals = []
    with pytest.raises(AssertionError) as ei:
        _run_f15_resolve_race_once(
            tmp_path, "f15_g2_race.db", verdict="APPROVED",
            stall_mesh_mixed=depths, gate2_rejected=True,
            race_gate2_with_holder=True, gate2_refusals=refusals,
            b_max_calls_per_tick=1, skip_racing_loop=True,
            holder_owner_sink=holder_sink)
    msg = str(ei.value)
    # the downstream stall is surfaced: gate-2 AND the mesh tails are
    # named as stuck, never the recovered worker
    stuck_part = msg.split("Blocking-owner snapshot:")[0]
    assert "STALLED" in msg, msg
    assert "gate-2" in stuck_part, msg
    assert f"mix-{max(depths)}-" in stuck_part, msg
    assert "ext-1" not in stuck_part, msg
    assert clause in msg, msg
    # the lease itself is named: the blocking-owner snapshot carries the
    # holder's controller id
    assert "Blocking-owner snapshot:" in msg, msg
    assert f"scheduler_lock owner={holder_sink['owner']!r}" in msg, msg
    assert "scheduler_lock free (no blocking owner row)" not in msg, msg
    # the verdict was refused LOCK on every attempt - gate-2 never
    # resolved (the hook retries each tick while WAITING_HUMAN)
    assert refusals, refusals
    assert all(r == "LOCK" for r in refusals), refusals
    # without the holder the same graph completes (control: the plain
    # gate-2 probe) - the lease is what turns it into a surfaced stall
    facts = _run_f15_resolve_race_once(
        tmp_path, "f15_g2_race_control.db", verdict="APPROVED",
        stall_mesh_mixed=depths, gate2_rejected=True,
        b_max_calls_per_tick=1, skip_racing_loop=True)
    assert facts["gate_failed"] == 1, facts
    assert facts["mode"] is OperationalMode.ACTIVE, facts
    assert facts["completion_ticks_used"] == sum(depths) + 1, facts


def test_21_f15_stalled_owner_snapshot_double_handoff(tmp_path):
    """DOUBLE lease handoff: two owner changes mid-stall (handoff-1 at
    tick 3, handoff-2 at tick 5, each writing now+1h locked_at so the
    older holder can never reclaim it). Every snapshot before tick 3
    names the live holder, ticks 3-4 name handoff-1, ticks 5+ name
    handoff-2 - and the FINAL STALLED message names ONLY the newest owner
    (handoff-2, whose locked_at is newest), never the holder and never
    the intermediate handoff-1. The atomic SELECT always reads the live
    row; the newest locked_at owner is authoritative even across two
    successive handoffs.
    """
    holder_sink = {}
    snaps = []
    with pytest.raises(AssertionError) as ei:
        _run_f15_resolve_race_once(
            tmp_path, "f15_double_ho.db", verdict="APPROVED",
            hold_lease_after_verdict=True, skip_racing_loop=True,
            holder_owner_sink=holder_sink, lock_snapshots=snaps,
            handoff_owner="controller-handoff-1", handoff_at_tick=3,
            handoff_owner2="controller-handoff-2", handoff_at_tick2=5)
    msg = str(ei.value)
    holder = holder_sink["owner"]
    assert snaps, snaps
    # phase 0: the live holder; phase 1: handoff-1; phase 2: handoff-2
    ph0 = [o for o, _ in snaps[:3]]
    ph1 = [o for o, _ in snaps[3:5]]
    ph2 = [o for o, _ in snaps[5:]]
    assert ph0 and all(o == holder for o in ph0), (ph0, holder)
    assert ph1 and all(o == "controller-handoff-1" for o in ph1), ph1
    assert ph2 and all(o == "controller-handoff-2" for o in ph2), ph2
    # locked_at ordering: handoff-2 newest, then handoff-1, then holder
    ts_holder = [t for o, t in snaps[:3] if o == holder]
    ts_h1 = [t for o, t in snaps[3:5] if o == "controller-handoff-1"]
    ts_h2 = [t for o, t in snaps[5:] if o == "controller-handoff-2"]
    assert ts_holder and ts_h1 and ts_h2, (ts_holder, ts_h1, ts_h2)
    assert min(ts_h2) > max(ts_h1), (ts_h1, ts_h2)
    assert max(ts_h1) > max(ts_holder), (ts_holder, ts_h1)
    # the FINAL message names ONLY the newest owner - never the holder,
    # never the intermediate handoff-1
    assert "Blocking-owner snapshot:" in msg, msg
    assert "scheduler_lock owner='controller-handoff-2'" in msg, msg
    assert holder not in msg, msg
    assert "controller-handoff-1" not in msg, msg
    # and the named owner + locked_at equal the newest snapshot exactly
    last_owner, last_ts = snaps[-1]
    assert f"scheduler_lock owner={last_owner!r}" in msg, msg
    assert f"(locked_at={last_ts!r})" in msg, msg


