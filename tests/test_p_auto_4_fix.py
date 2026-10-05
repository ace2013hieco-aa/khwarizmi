"""P-AUTO-4-FIX — every auditor bypass becomes a refusal or journaled fact.

Each test FAILS on slice/p-auto-4-caps@da0d26c and PASSES on the fix
(red legs pasted in the task reply; many fail on old code with
ImportError/TypeError on the new names — the capability itself missing).
Offline/fixture-only throughout.
"""
from __future__ import annotations

import pytest

from hermes.research.autonomy_caps import (
    BUDGET_PER_TASK_STEPS_EXCEEDED,
    BUDGET_PER_TICK_TOKENS_EXCEEDED,
    LOOP_PATTERN_QUARANTINED,
    WALLCLOCK_TICK_DEADLINE_EXCEEDED,
    LoopDetector,
    classify_failure_signature,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"


def _db():
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ProjectRepository

    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create("p1", "Test")
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, CLOCK))
    return conn


def _store(conn, tag):
    from hermes.artifacts.store import ArtifactStore
    from hermes.persistence.repositories import ArtifactRepository

    return ArtifactStore(
        f"/tmp/p4fix-{tag}",
        ArtifactRepository(conn, lambda: CLOCK), clock=lambda: CLOCK)


def _good_draft():
    from hermes.research.extraction import extraction_draft_from_mapping

    return extraction_draft_from_mapping({
        "source_ref": "dataset_manifest:dm-1",
        "claims": [{
            "ref": "c1",
            "statement": "Alpha reduces beta under gamma conditions.",
            "source_ref": "dataset_manifest:dm-1",
            "support_state": "INFERRED",
            "span_ref": "sec.3",
            "claim_type": "causal",
            "context_tags": {"regime": "ICSS-v1:low-vol",
                             "dataset_ref": "dm-1"},
            "assumption_refs": ["a1"]}],
        "assumptions": [{
            "ref": "a1",
            "statement": "The sample is representative.",
            "context_tags": {"population": "adults-18-65"},
            "supporting_artifact_refs": ["dataset_manifest:dm-1"]}],
        "extracted_by": "model_ref:c-tier-1",
        "schema_version": "2"})


def _admit_extract(conn, scope="both"):
    from hermes.core.intents import Intent, IntentKind
    from hermes.research.extraction import build_extract_task_payload
    from hermes.research.gateway import apply_intent

    res = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
        payload=build_extract_task_payload("dataset_manifest:dm-1", scope)))
    return res.entity_id


# ── A1: measured actuals charged ──


class _ProbeHandler:
    """Fake AGENT_TASK handler reporting a fixed measured request count."""

    def __init__(self, actual: int) -> None:
        self._actual = actual

    def build_context(self, task, project_id, repos):
        return object()

    def __call__(self, ctx):
        from hermes.research.source_handlers import HandlerResult

        return HandlerResult(status="failed_typed", reason="TRANSIENT probe",
                             outcome_recorded=False,
                             provider_requests=self._actual)


def _admit_agent(conn, tid):
    from hermes.core.intents import Intent, IntentKind
    from hermes.research.gateway import apply_intent

    res = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
        payload={
            "task_id": tid, "task_type": "AGENT_TASK",
            "profile": "DIRECTOR", "idempotency_key": tid + "-key",
            "iteration": 1, "spec": {"template": "probe-tokens"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None}))
    return res.entity_id


def test_a1_measured_actuals_charged_not_estimates():
    from hermes.research.controller import Controller

    conn = _db()
    tid = _admit_agent(conn, "tok-1")
    ctrl = Controller(
        conn, project_id="p1", artifact_store=_store(conn, "a1"),
        task_handlers={"probe-tokens": _ProbeHandler(actual=200)},
        clock=lambda: CLOCK)
    out = ctrl.tick()
    assert tid in out.retried
    # Estimate for this task is 1; the ledger must carry the measured 200.
    assert ctrl._budget.task_tokens[tid] == 200
    conn.close()


def test_a1_tick_overrun_refuses_forward():
    from hermes.research.controller import Controller

    conn = _db()
    tids = [_admit_agent(conn, f"tok-{i}") for i in range(3)]
    ctrl = Controller(
        conn, project_id="p1", artifact_store=_store(conn, "a1b"),
        task_handlers={"probe-tokens": _ProbeHandler(actual=200)},
        clock=lambda: CLOCK,
        autonomy_operator={"per_tick_tokens": 250})
    out = ctrl.tick()
    # 200 + 200 counted (400 > 250 recorded); the third dispatch refuses.
    assert ctrl._budget.run_tokens == 400
    assert tids[2] not in out.dispatched
    assert out.idle == BUDGET_PER_TICK_TOKENS_EXCEEDED
    conn.close()


# ── A2: recovery through budget accounting ──


def test_a2_requeue_refuses_over_step_budget():
    from hermes.core.task_status import TaskStatus
    from hermes.persistence.repositories import TaskRepository
    from hermes.research.autonomy_caps import BudgetEnvelope, BudgetTracker
    from hermes.research.controller import Controller

    conn = _db()
    tid = _admit_extract(conn)
    store = _store(conn, "a2")
    tracker = BudgetTracker(envelope=BudgetEnvelope(
        per_task_steps=1, per_tick_steps=1000, per_run_steps=1000,
        per_task_tokens=100000, per_tick_tokens=100000,
        per_run_tokens=100000))
    tracker.task_steps[tid] = 1  # budget already spent by prior execution
    ctrl = Controller(
        conn, project_id="p1", artifact_store=store,
        extract_fn=lambda task, untrusted: _good_draft(),
        clock=lambda: CLOCK, budget_tracker=tracker)
    tr = TaskRepository(conn)
    tr.transition_status(tid, TaskStatus.READY, caused_by="t")
    tr.transition_status(tid, TaskStatus.RUNNING, caused_by="t")
    conn.execute(
        "UPDATE tasks SET last_heartbeat = ? WHERE task_id = ?",
        ("2020-01-01T00:00:00.000000+00:00", tid))
    ctrl.tick()  # NO_SIGNAL first miss
    ctrl.tick()  # FAILED -> requeue must refuse on the step budget
    assert tr.get_status(tid) is TaskStatus.FAILED
    assert any(BUDGET_PER_TASK_STEPS_EXCEEDED in n for n in ctrl.notes)
    conn.close()


# ── B1: quarantine + streak survive restart ──


def test_b1_quarantine_and_streak_reimported_on_boot():
    from hermes.core.task_status import TaskStatus
    from hermes.persistence.repositories import TaskRepository
    from hermes.research.controller import Controller

    conn = _db()
    tid = _admit_extract(conn)
    conn.execute("UPDATE tasks SET max_retries = 10 WHERE task_id = ?",
                 (tid,))
    kw = {"project_id": "p1", "artifact_store": _store(conn, "b1"),
            "clock": lambda: CLOCK,
            "autonomy_operator": {"loop_repeat_threshold": 3}}
    c1 = Controller(conn, **kw)
    tr = TaskRepository(conn)
    tr.transition_status(tid, TaskStatus.READY, caused_by="t")
    tr.transition_status(tid, TaskStatus.RUNNING, caused_by="t")
    assert c1._retry_or_fail(tid, "TRANSIENT") == "retried"
    tr.transition_status(tid, TaskStatus.RUNNING, caused_by="t")
    assert c1._retry_or_fail(tid, "TRANSIENT") == "retried"
    c2 = Controller(conn, **kw)  # restart: journaled state reloaded
    assert tid not in c2.quarantined_tasks()
    tr.transition_status(tid, TaskStatus.RUNNING, caused_by="t")
    assert c2._retry_or_fail(tid, "TRANSIENT") == "failed"
    assert tid in c2.quarantined_tasks()
    c3 = Controller(conn, **kw)  # terminal quarantine re-imported too
    assert tid in c3.quarantined_tasks()
    assert c3._loops.reason_for(tid)
    conn.close()


# ── B2: signature normalization ──


def test_b2_normalized_classes_and_blank_count():
    assert classify_failure_signature("request timed out") == "TRANSIENT"
    assert classify_failure_signature("TRANSIENT probe") == "TRANSIENT"
    assert classify_failure_signature("throttled 429") == "TRANSIENT"
    assert classify_failure_signature("") == "UNKNOWN"
    assert classify_failure_signature("search EMPTY") == "EMPTY"
    detector = LoopDetector(repeat_threshold=3)
    assert detector.observe_failure("t1", "TRANSIENT probe") == ""
    assert detector.observe_failure("t1", "request timed out") == ""
    assert detector.observe_failure("t1", "throttled: 429") == \
        LOOP_PATTERN_QUARANTINED
    blank = LoopDetector(repeat_threshold=2)
    assert blank.observe_failure("t2", "") == ""
    assert blank.observe_failure("t2", "") == LOOP_PATTERN_QUARANTINED


# ── C1: narrowed deadline installed ──


def test_c1_operator_deadline_reaches_live_handlers():
    from hermes.research.live_fetch import build_live_fetch_wiring

    conn = _db()
    store = _store(conn, "c1")
    tight = build_live_fetch_wiring(
        conn, store, lambda: CLOCK,
        autonomy_caps={"overall_deadline_seconds": 60.0})
    for name in ("source_search", "source_fetch"):
        assert tight.handlers[name].policy.overall_deadline_seconds == 60.0
    default = build_live_fetch_wiring(conn, store, lambda: CLOCK)
    for name in ("source_search", "source_fetch"):
        assert default.handlers[name].policy.overall_deadline_seconds == 300.0
    conn.close()


# ── C2: explicit tightening never silently overridden ──


def test_c2_explicit_tightening_refuses_loudly():
    from hermes.research.controller import Controller

    conn = _db()
    with pytest.raises(ValueError, match="undercuts max_calls_per_tick"):
        Controller(
            conn, project_id="p1", artifact_store=_store(conn, "c2"),
            clock=lambda: CLOCK,
            autonomy_operator={"per_tick_steps": 1})
    # Consistent tightening of both knobs constructs fine.
    ctrl = Controller(
        conn, project_id="p1", artifact_store=_store(conn, "c2b"),
        clock=lambda: CLOCK, max_calls_per_tick=1,
        autonomy_operator={"per_tick_steps": 1})
    assert ctrl._budget.envelope.per_tick_steps == 1
    conn.close()


# ── D: pinned dial ──


def test_d_pinned_connection_dials_vetted_address():
    import hermes.tools.providers.http as http_module

    dialed = {}

    def fake_create_connection(address, timeout=None, *args, **kwargs):
        dialed["address"] = address
        return object()

    class FakeContext:
        def wrap_socket(self, sock, server_hostname=None):
            dialed["sni"] = server_hostname
            return sock

    conn = http_module._PinnedHTTPSConnection(
        "api.openalex.org", context=FakeContext(),
        pinned_ip="93.184.216.34")
    original = http_module.socket.create_connection
    http_module.socket.create_connection = fake_create_connection
    try:
        conn.connect()
    finally:
        http_module.socket.create_connection = original
    assert dialed["address"] == ("93.184.216.34", 443)
    assert dialed["sni"] == "api.openalex.org"


def test_d_gate_publishes_pin_for_exactly_one_request():
    import hermes.tools.providers.http as http_module
    from hermes.research.live_fetch import (
        ALLOWLIST_HOSTS,
        _AllowlistedTransport,
    )
    from hermes.tools.providers.base import RequestSpec, TransportResponse

    observed = []

    class Inner:
        def request(self, spec):
            observed.append(http_module._lookup_pin("api.openalex.org"))
            return TransportResponse(status=200, body=b"{}", headers={},
                                     content_type="application/json")

    gate = _AllowlistedTransport(
        Inner(), allowlist=ALLOWLIST_HOSTS,
        resolve=lambda host: ("93.184.216.34",))
    gate.request(RequestSpec(url="https://api.openalex.org/works",
                             params={}, headers_meta={}))
    assert observed == ["93.184.216.34"]
    assert http_module._lookup_pin("api.openalex.org") is None


def test_d_opener_routes_pinned_hosts_through_pin_handler():

    import hermes.tools.providers.http as http_module

    opener = http_module._build_opener(pin_resolver=lambda host: None)
    kinds = [type(h).__name__ for h in opener.handlers]
    assert "PinnedHTTPSHandler" in kinds
    assert "HTTPSHandler" not in kinds


# ── A3: post-execution wall check ──


def test_a3_slow_single_dispatch_trips_tick_wall():
    import time

    from hermes.research.controller import Controller

    conn = _db()
    _admit_extract(conn)

    def _slow(task, untrusted):
        time.sleep(0.3)
        return _good_draft()

    ctrl = Controller(
        conn, project_id="p1", artifact_store=_store(conn, "a3"),
        extract_fn=_slow, clock=lambda: CLOCK,
        autonomy_operator={"per_tick_wall_seconds": 0.05,
                           "per_run_wall_seconds": 1000.0})
    out = ctrl.tick()
    assert out.dispatched != []
    assert out.idle == WALLCLOCK_TICK_DEADLINE_EXCEEDED
    conn.close()


# ── F: capped tick emits a named idle ──


def test_f_fully_capped_tick_emits_named_idle():
    from hermes.research.controller import Controller
    from hermes.research.extraction import extraction_draft_from_mapping

    conn = _db()
    tid = _admit_extract(conn)

    def _bad(task, untrusted):
        return extraction_draft_from_mapping({
            "source_ref": "dataset_manifest:dm-1",
            "claims": [{
                "ref": "c1",
                "statement": "Alpha reduces beta under gamma conditions.",
                "source_ref": "dataset_manifest:dm-1",
                "support_state": "INFERRED",
                "span_ref": "sec.3",
                "claim_type": "causal",
                "context_tags": {"regime": "ICSS-v1:low-vol",
                                 "dataset_ref": "dm-1"},
                "assumption_refs": ["missing"]}],
            "assumptions": [{
                "ref": "a1",
                "statement": "The sample is representative.",
                "context_tags": {"population": "adults-18-65"},
                "supporting_artifact_refs": ["dataset_manifest:dm-1"]}],
            "extracted_by": "model_ref:c-tier-1",
            "schema_version": "2"})

    ctrl = Controller(
        conn, project_id="p1", artifact_store=_store(conn, "f1"),
        extract_fn=_bad, clock=lambda: CLOCK,
        autonomy_operator={"per_task_steps": 1})
    first = ctrl.tick()
    assert tid in first.retried
    second = ctrl.tick()
    assert second.dispatched == []
    assert second.idle == BUDGET_PER_TASK_STEPS_EXCEEDED
    conn.close()
