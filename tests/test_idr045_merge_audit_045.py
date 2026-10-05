"""MERGE-AUDIT-045 blocker closures — executed proof.

Two blockers from `docs/MERGE-AUDIT-045.md` (verdict FAIL), each closed here
with an executed test rather than a claim:

  F2  C5 provenance bounds enforced PRE-WRITE. The guard used to live in
      `gateway._append_audit_event`, which `apply_intent` calls *after*
      `_validate_insert_task` has already committed its row: an oversized
      `origin_ref` raised `GatewayRejection(MALFORMED_PAYLOAD)` with the task
      row already durable and NO `IntentApplied` / `IntentRejected` row. The
      guard is now `gateway._require_provenance_bounds`, called from
      `apply_intent` before validator dispatch.

  F-swallow  `_plan_admission_pass` swallowed every outcome: four bare
      `except Exception` blocks and an `except GatewayRejection: continue`,
      none of which recorded anything. A corrupt head, a fault inside the
      gateway, and a deterministic mid-pass refusal were all invisible — the
      last producing a permanent partial DAG whose outward `TickResult` was
      indistinguishable from a healthy wave parked at a human gate. Every
      outcome now records a note on `Controller.notes`.

Record defects corrected alongside (no test needed; doc-only):
placeholders, the `gateway.py` header, the `program_from_dict` identity hazard,
the three missing evidence artifacts, Q3, the `10`/`175` counts, the drifted
line citations, and the three mojibake em-dashes in `task_plan.py`.
"""

from __future__ import annotations

import json

import pytest

import hermes.research.gateway as gmod
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import EventRepository, ProjectRepository
from hermes.research.controller import Controller
from hermes.research.gateway import GatewayRejection, apply_intent
from hermes.research.programs import program_from_dict, program_to_dict

CLOCK = "2026-01-01T00:00:00.000000+00:00"


def frozen_clock(ts=CLOCK):
    return lambda: ts


BASE_PAYLOAD = {
    "scope_ref": "brief-1",
    "epistemic_objective": "Establish whether momentum predicts XAUUSD returns",
    "hypotheses": [
        {"ref": "H1", "ladder_target": "SUPPORTED",
         "falsification_condition": "returns do not follow momentum",
         "rival_of": None, "rival_status": None},
        {"ref": "H0", "ladder_target": "SPECULATIVE",
         "falsification_condition": "null hypothesis",
         "rival_of": "H1", "rival_status": "ACTIVE"},
    ],
    "predictions": [
        {"ref": "P1", "claim_ref": "H1", "observable": "20d_returns",
         "direction": "FOR", "condition": "trend_up"},
        {"ref": "P0", "claim_ref": "H0", "observable": "20d_returns",
         "direction": "NEUTRAL", "condition": "trend_up"},
    ],
    "discrimination_requirements": [],
    "methodology_constraints": ["icss-v1"],
    "task_graph_template_ref": None,
    "compiler_version": "1.0.0",
    "policy_version": "rp-2026.1",
    "schema_version": "1",
    "supersedes_ref": None,
}


def fresh_db(clock=frozen_clock()):
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, clock).create("p1", "Test")
    conn.execute(
        "INSERT INTO scope_briefs (brief_id, project_id, version, content_hash, "
        "supersedes_id, scope_text_json, rationale, created_at, frozen_at) "
        "VALUES (?, ?, 1, ?, NULL, ?, NULL, ?, ?)",
        ("brief-1", "p1", "briefhash1", json.dumps({"scope": "x"}),
         clock(), clock()),
    )
    return conn


def admit_compiled(conn, payload=None, clock=frozen_clock()):
    apply_intent(conn, Intent(
        kind=IntentKind.PROPOSE_RESEARCH_PROGRAM, proposed_by="DIRECTOR",
        project_id="p1", payload=dict(payload or BASE_PAYLOAD)), clock=clock)


def event_counts(conn, project_id="p1"):
    ev = EventRepository(conn).list_for_project(project_id)
    return {
        name: sum(1 for e in ev if e["event_type"] == name)
        for name in ("TaskCreated", "IntentApplied", "IntentRejected")
    }


def bypass_intent(task_id, idempotency_key, **over):
    """An ``Intent`` whose ``__post_init__`` bounds are defeated.

    ``Intent`` is a frozen slots dataclass, so the only way to reach
    ``apply_intent`` with an out-of-bounds provenance field is
    ``object.__setattr__`` — the same bypass the IDR-045 implementation audit
    used. This is the case F2 was about.
    """
    intent = object.__new__(Intent)
    fields = {
        "kind": IntentKind.ADMIT_TASK, "proposed_by": "DETERMINISTIC",
        "project_id": "p1", "justification": "MERGE-AUDIT-045 F2 probe",
        "payload": {
            "task_id": task_id, "task_type": "HUMAN_GATE",
            "idempotency_key": idempotency_key, "iteration": 1,
            "spec": {}, "inputs": [], "outputs": [], "dependencies": [],
            "provenance": ["spec:payload-v1"],
        },
        "origin_kind": None, "origin_ref": None, "model_ref": None,
        "run_id": None, "prompt_template_version": None,
        "charter_version": None,
    }
    fields.update(over)
    for name, value in fields.items():
        object.__setattr__(intent, name, value)
    return intent


# ── F2: C5 bounds enforced PRE-WRITE ────────────────────────────────────────


class TestF2BoundsArePreWrite:
    """F2 — an oversized provenance field refuses with zero rows written."""

    def test_oversized_origin_ref_writes_nothing_and_is_journalled(self):
        conn = fresh_db()
        task_id, idem = "t-f2-oversize", "idem-f2-oversize"
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, bypass_intent(task_id, idem, origin_ref="x" * 65),
                         clock=frozen_clock())
        assert exc.value.code == "MALFORMED_PAYLOAD"
        assert "origin_ref exceeds max length 64" in str(exc.value)
        # The defect: the row used to be committed anyway.
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()["n"] == 0
        # The defect: no journal row at all used to be written.
        counts = event_counts(conn)
        assert counts["TaskCreated"] == 0
        assert counts["IntentApplied"] == 0
        # The fix: the refusal itself is now journalled as data.
        assert counts["IntentRejected"] == 1

    @pytest.mark.parametrize("field,value,limit", [
        ("origin_ref", "x" * 65, 64),
        ("model_ref", "y" * 129, 128),
        ("run_id", "r" * 65, 64),
        ("prompt_template_version", "p" * 33, 32),
        ("charter_version", "c" * 33, 32),
    ])
    def test_every_field_refuses_pre_write(self, field, value, limit):
        conn = fresh_db()
        task_id = f"t-f2-{field}"
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, bypass_intent(task_id, f"idem-f2-{field}",
                                             **{field: value}),
                         clock=frozen_clock())
        assert exc.value.code == "MALFORMED_PAYLOAD"
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()["n"] == 0
        assert event_counts(conn) == {
            "TaskCreated": 0, "IntentApplied": 0, "IntentRejected": 1}

    def test_in_bounds_provenance_still_applies(self):
        """The pre-write guard must not reject a legal intent."""
        conn = fresh_db()
        result = apply_intent(
            conn,
            Intent(kind=IntentKind.ADMIT_TASK, proposed_by="DETERMINISTIC",
                   project_id="p1", origin_kind="deterministic",
                   origin_ref="plan_admission_pass",
                   payload={
                       "task_id": "t-f2-ok", "task_type": "HUMAN_GATE",
                       "idempotency_key": "idem-f2-ok", "iteration": 1,
                       "spec": {}, "inputs": [], "outputs": [],
                       "dependencies": [], "provenance": ["spec:payload-v1"]}),
            clock=frozen_clock())
        assert result.entity_id == "t-f2-ok"
        assert event_counts(conn)["IntentApplied"] == 1

    def test_constructor_still_fails_closed(self):
        """``__post_init__`` remains the first line of defence."""
        with pytest.raises(ValueError):
            Intent(kind=IntentKind.ADMIT_TASK, proposed_by="DETERMINISTIC",
                   project_id="p1", payload={}, origin_ref="x" * 65)

    def test_no_post_write_bounds_guard_remains(self):
        """The F2 defect site must not reappear: the audit-event builder no
        longer enforces the bounds, because it runs after the commit."""
        import inspect

        from hermes.research import gateway
        src = inspect.getsource(gateway._append_audit_event)
        assert "ORIGIN_REF_MAX_LENGTH" not in src
        assert "MALFORMED_PAYLOAD" not in src
        # and the enforcement does live in apply_intent's pre-dispatch path
        assert "_require_provenance_bounds(intent)" in inspect.getsource(
            gateway.apply_intent)


# ── F-swallow: plan-admission failure discipline ────────────────────────────


def _corrupt_head(conn):
    """Make the filtered primary head unparseable, as a corrupt row would be."""
    bad_hypotheses = (
        '[{"ref": "H1", "ladder_target": "NOT_A_LADDER_TARGET",'
        ' "falsification_condition": "x", "rival_of": null,'
        ' "rival_status": null}]'
    )
    conn.execute(
        "UPDATE research_programs SET hypothesis_json = ?", (bad_hypotheses,))
    conn.commit()


class TestPlanPassRecordsEveryOutcome:
    """Every swallowed outcome is now a recorded note."""

    def test_corrupt_head_records_a_note(self):
        conn = fresh_db()
        admit_compiled(conn)
        _corrupt_head(conn)
        ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
        admitted = ctrl._plan_admission_pass()
        assert admitted == []
        assert ctrl.notes, "a corrupt primary head must record a note"
        assert any("plan admission skipped" in n for n in ctrl.notes)
        # The tick must surface it too, not just a bare idle result.
        ctrl2 = Controller(conn, project_id="p1", clock=frozen_clock())
        ctrl2.tick()
        assert any("plan admission skipped" in n for n in ctrl2.notes)

    def test_fault_inside_gateway_records_a_note(self):
        """A non-GatewayRejection exception is recorded as a FAULT, distinctly."""
        conn = fresh_db()
        admit_compiled(conn)
        real = gmod.apply_intent
        calls = {"n": 0}

        def flaky(c, intent, **kw):
            calls["n"] += 1
            if calls["n"] == 3:
                raise KeyError("synthetic internal fault in the gateway")
            return real(c, intent, **kw)

        gmod.apply_intent = flaky
        try:
            ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
            admitted = ctrl._plan_admission_pass()
        finally:
            gmod.apply_intent = real
        assert calls["n"] > 0
        assert ctrl.notes, "an unexpected gateway exception must record a note"
        joined = "\n".join(ctrl.notes)
        assert "FAULT KeyError" in joined
        assert "synthetic internal fault" in joined
        assert "INCOMPLETE" in joined
        assert admitted  # the payloads before the fault were admitted

    def test_deterministic_refusal_surfaces_partial_dag(self):
        """A permanent 2/9 DAG must be visible, not silently 'healthy'."""
        conn = fresh_db()
        admit_compiled(conn)
        real = gmod.apply_intent
        state = {"n": 0}

        def refuse_third(c, intent, **kw):
            state["n"] += 1
            if state["n"] == 3:
                raise GatewayRejection(intent.kind, "DEPENDENCY",
                                       "synthetic mid-pass refusal")
            return real(c, intent, **kw)

        gmod.apply_intent = refuse_third
        try:
            ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
            admitted = ctrl._plan_admission_pass()
        finally:
            gmod.apply_intent = real
        assert len(admitted) == 2
        tasks = conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
        assert tasks == 2, "partial DAG expected"
        joined = "\n".join(ctrl.notes)
        assert "INCOMPLETE" in joined
        # 2 admitted; the 3rd refused at the root and each of its 6 dependents
        # then refused on the missing dependency -> 7 refusals total.
        assert "2 of 9" in joined
        assert "7 refused" in joined
        assert "DEPENDENCY" in joined
        # The refusal is journalled by apply_intent as data too.
        assert event_counts(conn)["IntentRejected"] >= 1

    def test_healthy_admission_records_no_note(self):
        """A clean admission must stay quiet — notes mean failure."""
        conn = fresh_db()
        admit_compiled(conn)
        ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
        admitted = ctrl._plan_admission_pass()
        assert len(admitted) == 9
        assert ctrl.notes == []

    def test_idempotent_second_pass_records_no_note(self):
        """C2 no-op: a fully-admitted plan is not a failure."""
        conn = fresh_db()
        admit_compiled(conn)
        Controller(conn, project_id="p1", clock=frozen_clock())._plan_admission_pass()
        ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
        assert ctrl._plan_admission_pass() == []
        assert ctrl.notes == []

    def test_cold_start_records_no_note(self):
        """No program yet is the normal case, not a failure."""
        conn = fresh_db()
        ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
        assert ctrl._plan_admission_pass() == []
        assert ctrl.notes == []

    def test_notes_are_not_duplicated_across_ticks(self):
        """`_notes` is never cleared, so a repeated condition must not grow it."""
        conn = fresh_db()
        admit_compiled(conn)
        _corrupt_head(conn)
        ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
        for _ in range(5):
            ctrl._plan_admission_pass()
        assert len(ctrl.notes) == len(set(ctrl.notes)), "duplicate notes"
        assert len(ctrl.notes) >= 1

    def test_no_broad_except_in_pass_without_a_record(self):
        """Structural: every ``except`` in the pass must be followed by a
        ``_note_once``/``refusals.append`` record on the same handler path."""
        import inspect

        from hermes.research.controller import Controller as Ctrl
        src = inspect.getsource(Ctrl._plan_admission_pass)
        assert "except Exception" in src
        # No silent `continue`/`pass` on a swallow path.
        for handler_tail in src.split("except ")[1:]:
            body = handler_tail.split("\n\n")[0]
            assert "continue" not in body, f"silent continue: {handler_tail[:60]}"
            assert ("_note_once" in body or "refusals.append" in body), (
                f"unrecorded except: {handler_tail[:60]}")


# ── F5: program_from_dict identity hazard ───────────────────────────────────


class TestProgramFromDictIdentityHazard:
    """F5 — the silent `''` identity default is closed."""

    def test_missing_program_id_raises(self):
        d = program_to_dict(program_from_dict(
            _row_dict(fresh_db_and_admit())))
        d.pop("program_id", None)
        with pytest.raises(ValueError, match="program_id"):
            program_from_dict(d)

    def test_round_trip_via_program_to_dict_raises_not_silently_empty(self):
        """The F5 finding: program_to_dict omits both identity keys."""
        conn = fresh_db()
        admit_compiled(conn)
        original = program_from_dict(_row_dict(conn))
        exported = program_to_dict(original)
        assert "program_id" not in exported
        with pytest.raises(ValueError, match="program_id"):
            program_from_dict(exported)

    def test_row_dict_round_trip_still_works(self):
        conn = fresh_db()
        admit_compiled(conn)
        rebuilt = program_from_dict(_row_dict(conn))
        assert rebuilt.program_id
        assert rebuilt.project_id == "p1"


def _row_dict(conn):
    from hermes.persistence.repositories import (
        _research_program_row_to_dict,
    )
    row = conn.execute(
        "SELECT * FROM research_programs WHERE project_id = ? "
        "AND parent_program_id IS NULL ORDER BY version DESC LIMIT 1",
        ("p1",)).fetchone()
    return _research_program_row_to_dict(row)


def fresh_db_and_admit():
    conn = fresh_db()
    admit_compiled(conn)
    return conn
