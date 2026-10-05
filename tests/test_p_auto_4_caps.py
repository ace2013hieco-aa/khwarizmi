"""P-AUTO-4 caps — every cap proven to fire (deterministic, offline).

Covers: budget per-task/tick/run steps + tokens, wall-clock tick/run,
retry attempts exhausted + backoff bounds + daily-cap hard stop, loop
pattern quarantine + poison-task park (human-visible, never silent retry),
DNS-rebinding refusal (private/loopback/link-local/mixed), proxy-path
(opener ignores HTTPS_PROXY), narrow-only refuses widen, values table +
starvation/deadlock review present.
"""
from __future__ import annotations

import urllib.request

import pytest

import hermes.tools.providers.http as http_module
from hermes.config import AutonomyCapsConfig, default_config
from hermes.research.autonomy_caps import (
    BUDGET_PER_RUN_STEPS_EXCEEDED,
    BUDGET_PER_RUN_TOKENS_EXCEEDED,
    BUDGET_PER_TASK_STEPS_EXCEEDED,
    BUDGET_PER_TASK_TOKENS_EXCEEDED,
    BUDGET_PER_TICK_STEPS_EXCEEDED,
    BUDGET_PER_TICK_TOKENS_EXCEEDED,
    DAILY_CAP_HARD_STOP,
    DNS_REBINDING_REFUSED,
    LOOP_PATTERN_QUARANTINED,
    P_AUTO_4_PROPOSED_VALUES,
    STARVATION_DEADLOCK_REVIEW,
    BudgetEnvelope,
    BudgetTracker,
    LoopDetector,
    build_envelope,
    build_loop_threshold,
    build_rate_profiles,
    build_retry_caps,
    build_wallclock,
    deterministic_backoff_delay,
    narrow_float,
    narrow_int,
    refuse_non_public_addresses,
)
from hermes.research.live_fetch import (
    ALLOWLIST_HOSTS,
    _AllowlistedTransport,
    rate_profiles_from_autonomy,
    source_policy_from_autonomy,
)
from hermes.tools.providers.base import RateProfile, RequestSpec
from hermes.tools.providers.ratelimit import ProviderRateLimiter

PUBLIC = ("93.184.216.34",)  # public, globally routable (example.com)


def _public_resolve(host: str) -> tuple[str, ...]:
    return PUBLIC


class _FakeInner:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def request(self, spec: RequestSpec):
        from hermes.tools.providers.base import TransportResponse

        self.seen.append(spec.url)
        return TransportResponse(
            status=200, body=b"{}", headers={},
            content_type="application/json")


# ── values table + review note ──


def test_values_table_present_for_gate_ratification():
    assert P_AUTO_4_PROPOSED_VALUES["per_task_steps"] == 5
    assert P_AUTO_4_PROPOSED_VALUES["per_tick_steps"] == 8
    assert P_AUTO_4_PROPOSED_VALUES["per_run_steps"] == 1000
    assert P_AUTO_4_PROPOSED_VALUES["per_task_tokens"] == 250
    assert P_AUTO_4_PROPOSED_VALUES["per_tick_tokens"] == 1000
    assert P_AUTO_4_PROPOSED_VALUES["per_run_tokens"] == 10000
    assert P_AUTO_4_PROPOSED_VALUES["overall_dispatch_deadline_s"] == 300.0
    assert P_AUTO_4_PROPOSED_VALUES["retry_max_retries"] == 3
    assert P_AUTO_4_PROPOSED_VALUES["daily_cap_hard_stop"] == DAILY_CAP_HARD_STOP
    assert P_AUTO_4_PROPOSED_VALUES["loop_repeat_threshold"] == 3
    assert default_config().autonomy_caps.overall_deadline_seconds == 300.0


def test_starvation_deadlock_review_present():
    assert "STOP, never a wait" in STARVATION_DEADLOCK_REVIEW
    assert "quarantine" in STARVATION_DEADLOCK_REVIEW.lower()


# ── budget steps ──


def test_per_task_steps_fires():
    tracker = BudgetTracker(
        envelope=BudgetEnvelope(
            per_task_steps=2, per_tick_steps=1000, per_run_steps=1000,
            per_task_tokens=1000, per_tick_tokens=1000,
            per_run_tokens=1000))
    assert tracker.consume_step("t1") == ""
    assert tracker.consume_step("t1") == ""
    assert tracker.consume_step("t1") == BUDGET_PER_TASK_STEPS_EXCEEDED


def test_per_tick_steps_fires():
    tracker = BudgetTracker(
        envelope=BudgetEnvelope(
            per_task_steps=1000, per_tick_steps=2, per_run_steps=1000,
            per_task_tokens=1000, per_tick_tokens=1000,
            per_run_tokens=1000))
    assert tracker.consume_step("a") == ""
    assert tracker.consume_step("b") == ""
    assert tracker.consume_step("c") == BUDGET_PER_TICK_STEPS_EXCEEDED


def test_per_run_steps_fires():
    tracker = BudgetTracker(
        envelope=BudgetEnvelope(
            per_task_steps=1000, per_tick_steps=1000, per_run_steps=2,
            per_task_tokens=1000, per_tick_tokens=1000,
            per_run_tokens=1000))
    assert tracker.consume_step("a") == ""
    assert tracker.consume_step("b") == ""
    assert tracker.consume_step("c") == BUDGET_PER_RUN_STEPS_EXCEEDED


# ── budget tokens ──


def test_per_task_tokens_fires():
    tracker = BudgetTracker(
        envelope=BudgetEnvelope(
            per_task_steps=1000, per_tick_steps=1000, per_run_steps=1000,
            per_task_tokens=5, per_tick_tokens=1000, per_run_tokens=1000))
    assert tracker.consume_tokens("t1", 5) == ""
    assert tracker.consume_tokens("t1", 1) == BUDGET_PER_TASK_TOKENS_EXCEEDED


def test_per_tick_tokens_fires():
    tracker = BudgetTracker(
        envelope=BudgetEnvelope(
            per_task_steps=1000, per_tick_steps=1000, per_run_steps=1000,
            per_task_tokens=1000, per_tick_tokens=5, per_run_tokens=1000))
    assert tracker.consume_tokens("a", 5) == ""
    assert tracker.consume_tokens("b", 1) == BUDGET_PER_TICK_TOKENS_EXCEEDED


def test_per_run_tokens_fires():
    tracker = BudgetTracker(
        envelope=BudgetEnvelope(
            per_task_steps=1000, per_tick_steps=1000, per_run_steps=1000,
            per_task_tokens=1000, per_tick_tokens=1000, per_run_tokens=5))
    assert tracker.consume_tokens("a", 5) == ""
    assert tracker.consume_tokens("b", 1) == BUDGET_PER_RUN_TOKENS_EXCEEDED


# ── wall-clock ──


def test_tick_wall_clock_fires_via_controller():
    from hermes.artifacts.store import ArtifactStore
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import (
        ArtifactRepository,
        ProjectRepository,
    )
    from hermes.research.controller import Controller

    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: "2026-01-01T00:00:00+00:00").create(
        "p1", "Test")
    store = ArtifactStore(
        "/tmp/p4-tick-wall", ArtifactRepository(conn, lambda: "2026-01-01T00:00:00+00:00"),
        clock=lambda: "2026-01-01T00:00:00+00:00")
    # Tick budget already spent: monotonic never advances past the bound.
    ctrl = Controller(
        conn, project_id="p1", artifact_store=store,
        clock=lambda: "2026-01-01T00:00:00+00:00",
        autonomy_operator={"per_tick_wall_seconds": 0.001},
        monotonic=lambda: 1000.0)
    # Force the tick start long before "now" so the bound fires.
    ctrl._tick_start = 0.0  # type: ignore[attr-defined]
    assert ctrl._tick_wall_exceeded() is True
    conn.close()


def test_run_wall_clock_fires_via_controller():
    from hermes.artifacts.store import ArtifactStore
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
    from hermes.research.controller import Controller

    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: "2026-01-01T00:00:00+00:00").create(
        "p1", "Test")
    store = ArtifactStore(
        "/tmp/p4-run-wall", ArtifactRepository(conn, lambda: "2026-01-01T00:00:00+00:00"),
        clock=lambda: "2026-01-01T00:00:00+00:00")
    ctrl = Controller(
        conn, project_id="p1", artifact_store=store,
        clock=lambda: "2026-01-01T00:00:00+00:00",
        autonomy_operator={"per_run_wall_seconds": 10.0},
        monotonic=lambda: 1000.0)
    ctrl._run_start = 0.0  # type: ignore[attr-defined]
    assert ctrl._run_wall_exceeded() is True
    conn.close()


def test_controller_run_stops_on_run_step_budget():
    from hermes.artifacts.store import ArtifactStore
    from hermes.core.intents import Intent, IntentKind
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
    from hermes.research.controller import Controller
    from hermes.research.extraction import (
        build_extract_task_payload,
        extraction_draft_from_mapping,
    )
    from hermes.research.gateway import apply_intent

    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: "2026-01-01T00:00:00+00:00").create(
        "p1", "Test")
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"))
    store = ArtifactStore(
        "/tmp/p4-run-steps", ArtifactRepository(conn, lambda: "2026-01-01T00:00:00+00:00"),
        clock=lambda: "2026-01-01T00:00:00+00:00")
    apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
        payload=build_extract_task_payload("dataset_manifest:dm-1", "both")))

    def _good(task, untrusted):
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

    ctrl = Controller(
        conn, project_id="p1", artifact_store=store, extract_fn=_good,
        clock=lambda: "2026-01-01T00:00:00+00:00",
        autonomy_operator={"per_run_steps": 1, "per_tick_steps": 8})
    outs = ctrl.run(max_ticks=4)
    assert any(o.idle == BUDGET_PER_RUN_STEPS_EXCEEDED for o in outs)
    conn.close()


def test_controller_tick_stops_on_tick_step_budget():
    from hermes.artifacts.store import ArtifactStore
    from hermes.core.intents import Intent, IntentKind
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
    from hermes.research.controller import Controller
    from hermes.research.extraction import build_extract_task_payload
    from hermes.research.gateway import apply_intent

    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: "2026-01-01T00:00:00+00:00").create(
        "p1", "Test")
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"))
    store = ArtifactStore(
        "/tmp/p4-tick-steps", ArtifactRepository(conn, lambda: "2026-01-01T00:00:00+00:00"),
        clock=lambda: "2026-01-01T00:00:00+00:00")
    apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
        payload=build_extract_task_payload("dataset_manifest:dm-1", "both")))
    apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
        payload=build_extract_task_payload("dataset_manifest:dm-1", "claims")))

    def _good2(task, untrusted):
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

    ctrl = Controller(
        conn, project_id="p1", artifact_store=store, extract_fn=_good2,
        clock=lambda: "2026-01-01T00:00:00+00:00",
        max_calls_per_tick=1,
        autonomy_operator={"per_tick_steps": 1, "per_run_steps": 1000})
    out = ctrl.tick()
    assert out.idle == BUDGET_PER_TICK_STEPS_EXCEEDED
    assert len(out.dispatched) == 1
    conn.close()


# ── retry ──


def test_retry_backoff_bounded_and_capped():
    caps = build_retry_caps(None)
    assert caps.max_retries == 3
    assert deterministic_backoff_delay(0, 1.0, 30.0) == 1.0
    assert deterministic_backoff_delay(1, 1.0, 30.0) == 2.0
    assert deterministic_backoff_delay(10, 1.0, 30.0) == 30.0
    narrowed = build_retry_caps({"retry_max_retries": 1})
    assert narrowed.max_retries == 1


def test_daily_cap_hard_stop_no_retry():
    class _Clock:
        def now_utc(self) -> str:
            return "2026-01-01T00:00:00+00:00"

        def monotonic(self) -> float:
            return 0.0

        def sleep(self, delay: float) -> None:
            return None

    limiter = ProviderRateLimiter(
        {"openalex": RateProfile(
            rps=1000.0, burst=1, concurrency=1, daily_cap=1)},
        _Clock())  # type: ignore[arg-type]
    granted, reason = limiter.acquire("openalex")
    assert granted and reason == ""
    limiter.release("openalex")
    granted, reason = limiter.acquire("openalex")
    assert not granted and reason == DAILY_CAP_HARD_STOP


# ── loop / poison quarantine ──


def test_loop_pattern_quarantine_fires():
    detector = LoopDetector(repeat_threshold=3)
    assert detector.observe_failure("t1", "TRANSIENT") == ""
    assert detector.observe_failure("t1", "TRANSIENT") == ""
    assert detector.observe_failure("t1", "TRANSIENT") == LOOP_PATTERN_QUARANTINED
    assert detector.is_quarantined("t1") is True
    assert "t1" in detector.reason_for("t1")


def test_poison_task_parked_human_visible_never_silent():
    from hermes.artifacts.store import ArtifactStore
    from hermes.core.intents import Intent, IntentKind
    from hermes.core.task_status import TaskStatus
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import (
        ArtifactRepository,
        ProjectRepository,
        TaskRepository,
    )
    from hermes.research.controller import Controller
    from hermes.research.extraction import build_extract_task_payload
    from hermes.research.gateway import apply_intent

    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: "2026-01-01T00:00:00+00:00").create(
        "p1", "Test")
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"))
    store = ArtifactStore(
        "/tmp/p4-poison", ArtifactRepository(conn, lambda: "2026-01-01T00:00:00+00:00"),
        clock=lambda: "2026-01-01T00:00:00+00:00")
    res = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
        payload=build_extract_task_payload("dataset_manifest:dm-1", "both")))
    task_id = res.entity_id
    ctrl = Controller(
        conn, project_id="p1", artifact_store=store,
        clock=lambda: "2026-01-01T00:00:00+00:00",
        autonomy_operator={"loop_repeat_threshold": 2})
    # Move to RUNNING so _retry_or_fail can park it.
    TaskRepository(conn).transition_status(
        task_id, TaskStatus.READY, caused_by="test")
    TaskRepository(conn).transition_status(
        task_id, TaskStatus.RUNNING, caused_by="test")
    assert ctrl._retry_or_fail(task_id, "TRANSIENT") == "retried"
    TaskRepository(conn).transition_status(
        task_id, TaskStatus.RUNNING, caused_by="test")
    assert ctrl._retry_or_fail(task_id, "TRANSIENT") == "failed"
    assert task_id in ctrl.quarantined_tasks()
    assert TaskRepository(conn).get_status(task_id) is TaskStatus.FAILED
    assert any(task_id in note for note in ctrl.notes)
    conn.close()


# ── DNS rebinding ──


@pytest.mark.parametrize("addresses", [
    ("127.0.0.1",),
    ("10.0.0.5",),
    ("192.168.1.10",),
    ("169.254.169.254",),
    ("::1",),
    ("93.184.216.34", "10.0.0.5"),  # mixed public/private refused as a whole
    (),
])
def test_dns_rebinding_refused(addresses):
    with pytest.raises(ValueError, match=DNS_REBINDING_REFUSED):
        refuse_non_public_addresses("api.openalex.org", addresses)


def test_dns_guard_on_live_fetch_gate():
    inner = _FakeInner()
    gate = _AllowlistedTransport(
        inner, allowlist=ALLOWLIST_HOSTS, resolve=_public_resolve)
    resp = gate.request(RequestSpec(
        url="https://api.openalex.org/works", params={}, headers_meta={}))
    assert resp.status == 200
    assert inner.seen == ["https://api.openalex.org/works"]

    def _loopback(host: str) -> tuple[str, ...]:
        return ("127.0.0.1",)

    evil_gate = _AllowlistedTransport(
        _FakeInner(), allowlist=ALLOWLIST_HOSTS, resolve=_loopback)
    from hermes.tools.research_sources import ProviderValidationError

    with pytest.raises(ProviderValidationError):
        evil_gate.request(RequestSpec(
            url="https://api.openalex.org/works", params={},
            headers_meta={}))


# ── proxy path ──


def test_guarded_opener_ignores_https_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.com:8080")
    monkeypatch.setenv("https_proxy", "http://proxy.example.com:8080")
    opener = http_module._build_opener()
    proxy_maps = [h.proxies for h in opener.handlers
                  if isinstance(h, urllib.request.ProxyHandler)]
    # P-AUTO-4 proxy-path: the guarded opener must never route via the env
    # proxy — either no ProxyHandler survives (empty mapping is dropped,
    # leaving no proxy authority) or any surviving mapping carries no
    # https/http entry.
    for mapping in proxy_maps:
        assert mapping.get("https") is None
        assert mapping.get("http") is None
    assert any(
        isinstance(h, http_module._SameOriginRedirectHandler)
        for h in opener.handlers)


# ── narrow-only ──


def test_narrow_only_refuses_widening():
    with pytest.raises(ValueError, match="never widen"):
        narrow_int(1000, 300, "overall_deadline_seconds")
    with pytest.raises(ValueError, match="never widen"):
        narrow_float(600.0, 300.0, "overall_deadline_seconds")
    assert narrow_int(100, 300, "overall_deadline_seconds") == 100
    assert narrow_float(100.0, 300.0, "overall_deadline_seconds") == 100.0
    # Operator plumbing: tighter deadline honoured, wider refused.
    policy = source_policy_from_autonomy(
        AutonomyCapsConfig(overall_deadline_seconds=60.0))
    assert policy.overall_deadline_seconds == 60.0
    with pytest.raises(ValueError, match="never widen"):
        source_policy_from_autonomy(
            AutonomyCapsConfig(overall_deadline_seconds=600.0))
    profiles = rate_profiles_from_autonomy(
        AutonomyCapsConfig(openalex_daily_cap=10))
    assert profiles["openalex"].daily_cap == 10
    with pytest.raises(ValueError, match="never widen"):
        rate_profiles_from_autonomy(
            AutonomyCapsConfig(openalex_daily_cap=100000))
    assert build_envelope(None).per_task_steps == 5
    assert build_wallclock(None).dispatch_deadline_s == 300.0
    assert build_loop_threshold(None) == 3
    assert build_rate_profiles(None)["openalex"]["daily_cap"] == 1000
