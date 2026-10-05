"""P-AUTO-6 — closed-loop integration test (the last autonomy slice).

Full loop on fixtures: **plan → dispatch → model-stub → validate → gate →
project** — each stage's journal footprint asserted as an ordered golden
(event types + order, never wall-clock). Seeded fault injection proves the
P-AUTO-4 envelopes fire in-loop: poison task (quarantined, never retried
silently), hung fetch (D1 deadline fires, typed TRANSIENT, no hang), loop
pattern (detector trips at threshold, quarantine + named note). Recovery
after quarantine is exercised end-to-end, and the controller's quarantine
skip is asserted to be loud (named idle code, never a silent tick).

Hermetic throughout: replay/refusing transports + ``StubModelClient`` +
frozen clocks; no live egress; fixture-only. P-AUTO-6 does NOT declare
production — that needs the separate Phase-D-style certification gate
(roadmap §'What "production" means'); the final test pins that boundary.

Red legs (envelope removed) are external runs, not code in this file:
- quarantine removed (``LoopDetector.observe_failure`` neutralized) ->
  the poison + loop-pattern tests fail;
- deadline removed (``source_handlers._dispatch_deadline`` -> None) ->
  the hung-fetch test fails.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

CLOCK = "2026-01-01T00:00:00.000000+00:00"
TOPIC = "CRISPR"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "p_auto_3_live"
OP_ID = "op-1"
OP_TOKEN = "op-token-1"


# ═══════════════════ fixtures / helpers ═══════════════════


def _db(*, manifests=("dm-1", "dm-2", "dm-3")):
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import (
        OperatorCredentialRepository,
        ProjectRepository,
    )

    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create("p1", "Test")
    OperatorCredentialRepository(conn, lambda: CLOCK).register(
        OP_ID, OP_TOKEN, "Test Operator")
    conn.execute(
        "INSERT INTO scope_briefs (brief_id, project_id, version, content_hash, "
        "supersedes_id, scope_text_json, rationale, created_at, frozen_at) "
        "VALUES (?, ?, 1, ?, NULL, ?, NULL, ?, ?)",
        ("brief-1", "p1", "briefhash1", json.dumps({"scope": "x"}),
         CLOCK, CLOCK))
    for manifest_id in manifests:
        conn.execute(
            "INSERT INTO dataset_manifests (manifest_id, project_id, location, "
            "format, size_bytes, headers_json, schema_observations_json, "
            "query_recipes_json, content_hash, provenance_json, created_at, "
            "immutable) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (manifest_id, "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
             "h-" + manifest_id, None, CLOCK))
    return conn


def _store(conn, tmp_path, tag):
    from hermes.artifacts.store import ArtifactStore
    from hermes.persistence.repositories import ArtifactRepository

    return ArtifactStore(
        str(tmp_path / f"store-{tag}"),
        ArtifactRepository(conn, lambda: CLOCK), clock=lambda: CLOCK)


def _base_payload():
    """A compiled-program payload (rival coverage satisfies E5)."""
    return {
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


def _admit_program(conn):
    from hermes.core.intents import Intent, IntentKind
    from hermes.research.gateway import apply_intent

    return apply_intent(conn, Intent(
        kind=IntentKind.PROPOSE_RESEARCH_PROGRAM, proposed_by="DIRECTOR",
        project_id="p1", payload=_base_payload()), clock=lambda: CLOCK)


def _plan(conn):
    from hermes.persistence.repositories import ResearchProgramRepository
    from hermes.research.programs import program_from_dict
    from hermes.research.task_plan import build_task_plan

    program = program_from_dict(
        ResearchProgramRepository(conn, lambda: CLOCK).current_primary("p1"))
    return build_task_plan(program)


def _admit_extract(conn, manifest="dataset_manifest:dm-1"):
    from hermes.core.intents import Intent, IntentKind
    from hermes.research.extraction import build_extract_task_payload
    from hermes.research.gateway import apply_intent

    result = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
        payload=build_extract_task_payload(manifest, "both")))
    return result.entity_id


def _admit_search(conn, provider):
    from hermes.core.intents import Intent, IntentKind
    from hermes.research.gateway import apply_intent
    from hermes.research.source_templates import build_source_search_task_payload

    result = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
        payload=build_source_search_task_payload(
            provider,
            {"identifiers": {}, "topic": TOPIC, "mode": "TOPIC",
             "unrecognized_hints": []},
            scope_ref="p1", page_size=5, max_pages=1)))
    return result.entity_id


def _refs_for(conn, search_task_id):
    from hermes.persistence.source_outcomes import SourceOutcomeRepository

    results = SourceOutcomeRepository(conn).load_search_results(search_task_id)
    return ["source_result:" + r.content_hash for r in results[:2]]


def _admit_fetch(conn, search_task_id, provider, refs):
    from hermes.core.intents import Intent, IntentKind
    from hermes.research.gateway import apply_intent
    from hermes.research.source_templates import build_source_fetch_task_payload

    result = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
        payload=build_source_fetch_task_payload(
            search_task_id, refs, provider=provider,
            max_sources=2, size_cap_bytes=1024 * 1024)))
    return result.entity_id


def _events(conn, *, kind=None, task_id=None):
    query = ("SELECT event_id, event_type, task_id, from_state, to_state, "
             "reason, payload_json FROM events")
    clauses, params = [], []
    if kind is not None:
        clauses.append("event_type = ?")
        params.append(kind)
    if task_id is not None:
        clauses.append("task_id = ?")
        params.append(task_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY event_id"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def _status(conn, task_id):
    return conn.execute(
        "SELECT status FROM tasks WHERE task_id = ?", (task_id,)).fetchone()[0]


def _controller(conn, tmp_path, *, extract_fn=None, handlers=None,
                loop_detector=None, tag="ctrl"):
    """Production-shaped controller; the model seam defaults to the stub."""
    from hermes.research.controller import Controller
    from hermes.research.prompt_assembly import StubModelClient

    if extract_fn is None:
        extract_fn = StubModelClient().as_extract_fn()
    return Controller(
        conn, project_id="p1", extract_fn=extract_fn,
        task_handlers=handlers, artifact_store=_store(conn, tmp_path, tag),
        clock=lambda: CLOCK, loop_detector=loop_detector)


def _resolve(ctrl, task_id):
    return ctrl.resolve_human_gate(
        task_id=task_id, verdict="APPROVED", rationale="integration fixture",
        operator_id=OP_ID, operator_token=OP_TOKEN)


def _would_hang():
    """A transport that would block/raise if a request ever reached it."""

    class _WouldHang:
        def __init__(self):
            self.contacted = 0

        def request(self, spec):
            self.contacted += 1
            raise AssertionError(f"request reached the would-hang transport: {spec.url!r}")

    return _WouldHang()


def _replay_wiring(conn, store, *, deadline=None, inner=None, fixtures=None,
                   mode="replay"):
    """P-AUTO-3 wiring (swapped inner transport, zero live contact).

    ``mode="replay"`` serves recorded fixtures and never touches the
    inner transport; ``mode="record"`` forwards to it — used by the
    deadline fault so "the transport was never contacted" is causal
    (if execution reached the request, the would-hang transport WOULD
    fire), not a replay-mode artifact.
    """
    import dataclasses

    from hermes.research.live_fetch import build_live_fetch_wiring
    from hermes.research.source_handlers import (
        make_source_fetch_handler,
        make_source_search_handler,
    )
    from hermes.tools.providers.replay import RecordedTransport, provider_resolver_for

    def _public(host):
        return ("93.184.216.34",)

    class _Clock:
        def now_utc(self):
            return CLOCK

        def monotonic(self):
            return 0.0

        def sleep(self, delay):
            return None

    caps = {"overall_dispatch_deadline_s": deadline} if deadline else None
    live = build_live_fetch_wiring(conn, store, lambda: CLOCK,
                                   dns_resolve=_public, autonomy_caps=caps)
    replay = RecordedTransport(
        inner,
        resolve_provider=provider_resolver_for(live.adapters),
        clock=_Clock(),
        mode=mode,
        fixtures=fixtures or {},
    )
    machinery = dataclasses.replace(live.machinery, transport=replay)
    # Rebuild the handlers over the replay machinery, INSTALLING the narrowed
    # policy (the P-AUTO-4 FIX-C1 contract: building the policy is not enough).
    handlers = dict(live.handlers)
    handlers["source_search"] = make_source_search_handler(
        machinery, policy=live.handlers["source_search"].policy)
    handlers["source_fetch"] = make_source_fetch_handler(
        machinery, policy=live.handlers["source_fetch"].policy)
    return dataclasses.replace(live, transport=replay, machinery=machinery,
                               handlers=handlers)


def _fixtures(provider):
    from hermes.tools.providers.replay import load_fixtures

    if not FIXTURES.exists():
        pytest.skip("recorded live fixtures not present")
    corpus = load_fixtures(str(FIXTURES / f"{provider}.json"))
    assert corpus, "empty fixture corpus"
    return corpus


def _frontmatter(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "---"
    fm = {}
    for line in lines[1:]:
        if line == "---":
            break
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip().strip('"')
    return fm


# ═══════════════════ (a) the closed loop ═══════════════════


def test_closed_loop_plan_dispatch_stub_validate_gate_project(tmp_path):
    """plan → dispatch → model-stub → validate → gate → project, with the
    journal footprint of every stage pinned as an ordered golden."""
    from hermes.core.task_status import TaskStatus
    from hermes.vault import projection as vault

    conn = _db()
    _admit_program(conn)
    plan = _plan(conn)
    extract_id = _admit_extract(conn)
    ctrl = _controller(conn, tmp_path)

    # ── plan: tick 1 admits the DAG (ADMIT_TASK/DETERMINISTIC) ──
    out1 = ctrl.tick()
    hypothesis = plan.gate_tasks[0].task_id
    pre_compute = plan.gate_tasks[1].task_id
    assert out1.dispatched == [hypothesis]
    assert out1.waiting_human == [hypothesis]
    assert out1.idle == "waiting_human"

    created = [e["task_id"] for e in _events(conn, kind="TaskCreated")]
    assert [t for t in created if t in plan.task_ids] == \
        [task.task_id for task in plan.ordered]
    intents = [json.loads(e["payload_json"] or "{}")
               for e in _events(conn, kind="IntentApplied")]
    plan_admits = [p for p in intents
                   if p.get("intent_kind") == "ADMIT_TASK"
                   and p.get("origin_ref") == "plan_admission_pass"]
    assert len(plan_admits) == len(plan.ordered)
    assert {p.get("proposed_by") for p in plan_admits} == {"DETERMINISTIC"}
    assert {p.get("origin_kind") for p in plan_admits} == {"deterministic"}

    # ── gate: park → human verdict → ratified resolution ──
    assert _events(conn, kind="HumanApprovalRequested")[0]["task_id"] == hypothesis
    assert _resolve(ctrl, hypothesis)["rejected"] is False
    assert _status(conn, hypothesis) == TaskStatus.SUCCEEDED.value

    # ── gate 2: same cycle, proving the wave resumes between gates ──
    out2 = ctrl.tick()
    assert out2.dispatched == [pre_compute]
    assert out2.waiting_human == [pre_compute]
    assert _resolve(ctrl, pre_compute)["rejected"] is False

    # ── model-stub + validate: the extract task runs through the stub ──
    out3 = ctrl.tick()
    assert out3.dispatched == [extract_id]
    assert out3.succeeded == [extract_id]
    chain = [(e["event_type"], e["from_state"], e["to_state"], e["reason"])
             for e in _events(conn, task_id=extract_id)]
    assert [(t, f, s) for t, f, s, _ in chain] == [
        ("TaskCreated", None, "PENDING"),
        ("TaskStatusChanged", "PENDING", "READY"),
        ("TaskStatusChanged", "READY", "RUNNING"),
        ("TaskStatusChanged", "RUNNING", "SUCCEEDED"),
    ]
    assert chain[-1][3] == "extraction output accepted"
    claims = conn.execute(
        "SELECT claim_id, statement, source_ref, support_state, extracted_by "
        "FROM research_claims WHERE producing_task_id = ?", (extract_id,)
    ).fetchall()
    assert len(claims) == 1
    assert claims[0]["source_ref"] == "dataset_manifest:dm-1"
    # the stub's deterministic draft reached the claim row; acceptance
    # binds the controller as the executing identity (extracted_by).
    assert "stub extraction" in claims[0]["statement"]
    assert claims[0]["extracted_by"].startswith("controller:")

    # ── the golden: stage landmarks in journal order (types + order only) ──
    landmarks = []
    for e in _events(conn):
        if e["event_type"] in ("HumanApprovalRequested", "GatePassed",
                               "HumanGateResolved", "ProjectResumed"):
            landmarks.append((e["event_type"], e["task_id"]))
        elif e["task_id"] == extract_id and e["event_type"] == "TaskStatusChanged":
            landmarks.append((e["from_state"] + "->" + str(e["to_state"]),
                              e["task_id"]))
    assert landmarks == [
        ("HumanApprovalRequested", hypothesis),
        ("GatePassed", hypothesis),
        ("HumanGateResolved", hypothesis),
        ("ProjectResumed", None),
        ("HumanApprovalRequested", pre_compute),
        ("GatePassed", pre_compute),
        ("HumanGateResolved", pre_compute),
        ("ProjectResumed", None),
        ("PENDING->READY", extract_id),
        ("READY->RUNNING", extract_id),
        ("RUNNING->SUCCEEDED", extract_id),
    ]

    # ── project: the derived view reflects the journal with correct labels ──
    root = str(tmp_path / "vault")
    cursor, written = vault.project(conn, "p1", root, cursor=0)
    max_event = conn.execute("SELECT MAX(event_id) AS m FROM events").fetchone()["m"]
    assert cursor == max_event
    assert len(written) == max_event
    gate_event = _events(conn, kind="HumanGateResolved")[0]["event_id"]
    gate_note = _frontmatter(
        Path(root) / vault.note_filename(gate_event, "HumanGateResolved"))
    assert gate_note["authoritative"] == "true"
    assert gate_note["currently_valid"] == "true"
    extract_event = _events(conn, task_id=extract_id)[-1]["event_id"]
    extract_note = _frontmatter(
        Path(root) / vault.note_filename(extract_event, "TaskStatusChanged"))
    assert extract_note["authoritative"] == "false"
    assert "currently_valid" not in extract_note


# ═══════════════════ (b) seeded fault injection ═══════════════════


def _poison_draft():
    """A draft that can never bind to the producing task (validation poison)."""
    from hermes.research.extraction import extraction_draft_from_mapping

    return extraction_draft_from_mapping({
        "source_ref": "dataset_manifest:WRONG",
        "claims": [{
            "ref": "c1", "statement": "poison",
            "source_ref": "dataset_manifest:WRONG",
            "support_state": "INFERRED", "span_ref": "sec.1",
            "claim_type": "causal",
            "context_tags": {"regime": "ICSS-v1:low-vol",
                             "dataset_ref": "dm-1"}}],
        "assumptions": [],
        "extracted_by": "model_ref:poison", "schema_version": "2"})


def test_poison_task_quarantined_never_retried_silently(tmp_path):
    """A task whose output keeps failing validation is quarantined at the
    threshold — FAILED with a human-visible note, never retried silently."""
    from hermes.core.task_status import TaskStatus
    from hermes.research.autonomy_caps import LOOP_PATTERN_QUARANTINED

    conn = _db()
    poison_id = _admit_extract(conn, "dataset_manifest:dm-1")
    ctrl = _controller(conn, tmp_path, tag="poison",
                       extract_fn=lambda task, untrusted: _poison_draft())

    outcomes = [ctrl.tick() for _ in range(3)]
    assert outcomes[0].retried == [poison_id]
    assert outcomes[1].retried == [poison_id]
    assert outcomes[2].failed == [poison_id]
    assert poison_id in ctrl.quarantined_tasks()
    assert _status(conn, poison_id) == TaskStatus.FAILED.value
    reason = ctrl._loops.reason_for(poison_id)
    assert LOOP_PATTERN_QUARANTINED in reason
    assert any("quarantined" in note and poison_id in note
               for note in ctrl.notes)

    # never retried silently: no further dispatch, no RUNNING after FAILED
    runs_before = sum(
        1 for e in _events(conn, task_id=poison_id)
        if e["to_state"] == "RUNNING")
    after = [ctrl.tick() for _ in range(3)]
    assert all(not out.dispatched for out in after)
    assert sum(1 for e in _events(conn, task_id=poison_id)
               if e["to_state"] == "RUNNING") == runs_before
    assert _status(conn, poison_id) == TaskStatus.FAILED.value


def test_loop_pattern_trips_detector_at_threshold_and_quarantines(tmp_path):
    """The loop detector trips at the ratified threshold (3) on consecutive
    same-class failures and journals the named quarantine code."""
    from hermes.research.autonomy_caps import (
        LOOP_PATTERN_QUARANTINED,
        classify_failure_signature,
    )
    from hermes.research.source_handlers import HandlerResult

    class _FlappingHandler:
        def __init__(self):
            self.calls = 0

        def build_context(self, task, project_id, repos):
            return object()

        def __call__(self, ctx):
            self.calls += 1
            return HandlerResult(
                status="failed_typed", reason="TRANSIENT provider flapping (429)",
                outcome_recorded=True, provider_requests=1)

    from hermes.core.intents import Intent, IntentKind
    from hermes.research.gateway import apply_intent

    conn = _db()
    result = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
        payload={
            "task_id": "flap-1", "task_type": "AGENT_TASK",
            "profile": "RESEARCHER", "idempotency_key": "flap-1-key",
            "iteration": 1, "spec": {"template": "flap"},
            "inputs": [], "outputs": [], "dependencies": [], "provenance": [],
            "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None}))
    flap_id = result.entity_id
    handler = _FlappingHandler()
    ctrl = _controller(conn, tmp_path, tag="flap",
                       handlers={"flap": handler})

    outcomes = [ctrl.tick() for _ in range(3)]
    assert [o.retried for o in outcomes[:2]] == [[flap_id], [flap_id]]
    assert outcomes[2].failed == [flap_id]
    assert handler.calls == 3
    assert flap_id in ctrl.quarantined_tasks()
    assert classify_failure_signature("TRANSIENT provider flapping (429)") \
        == "TRANSIENT"
    last = _events(conn, task_id=flap_id)[-1]
    assert last["to_state"] == "FAILED"
    assert LOOP_PATTERN_QUARANTINED in last["reason"]
    assert any(LOOP_PATTERN_QUARANTINED in note for note in ctrl.notes)


def test_hung_fetch_deadline_fires_typed_transient_no_hang(tmp_path):
    """A fetch dispatch whose deadline is exhausted aborts BEFORE any request:
    the would-hang transport is never contacted, and the recorded outcome is
    typed TRANSIENT (deadline_exhausted) — no hang, no silent retry."""
    from hermes.research.autonomy_caps import WALLCLOCK_DISPATCH_DEADLINE_EXCEEDED

    conn = _db()
    store = _store(conn, tmp_path, "fetch")
    # 1. search (hermetic replay) produces the source refs the fetch cites.
    search_wiring = _replay_wiring(conn, store, fixtures=_fixtures("openalex"))
    ctrl = _controller(conn, tmp_path, tag="search",
                       handlers=search_wiring.handlers)
    search_id = _admit_search(conn, "openalex")
    ctrl.run(max_ticks=4)
    assert _status(conn, search_id) == "SUCCEEDED"
    refs = _refs_for(conn, search_id)
    assert len(refs) == 2
    # 2. the fetch runs under an exhausted dispatch deadline (1e-9 s); the
    #    transport below would be contacted if the deadline did not fire.
    would_hang = _would_hang()
    # record mode: the inner transport is a live forward, so contacting it
    # is the observable failure mode the deadline must prevent.
    fetch_wiring = _replay_wiring(conn, store, deadline=1e-9, inner=would_hang,
                                  mode="record")
    ctrl2 = _controller(conn, tmp_path, tag="fetch",
                        handlers=fetch_wiring.handlers)
    fetch_id = _admit_fetch(conn, search_id, "openalex", refs)
    ctrl2.tick()
    assert would_hang.contacted == 0
    assert _status(conn, fetch_id) == "SUCCEEDED"  # dispatch completed: verdict recorded

    row = conn.execute(
        "SELECT metadata_json FROM artifacts WHERE task_id = ? "
        "AND artifact_type = 'source_fetch_outcome'", (fetch_id,)).fetchone()
    assert row is not None
    meta = json.loads(row["metadata_json"] or "{}")
    assert meta["aggregate"] == "FAILED"
    assert meta["fetched_count"] == 0
    assert any("deadline exhausted" in note for note in meta["notes"])
    assert meta["per_source"], "no per-source verdicts recorded"
    for verdict in meta["per_source"]:
        assert verdict["resolution"] == "failed"
        assert verdict["failure_class"] == "TRANSIENT"
        assert verdict["reason"] == "deadline_exhausted"
    assert WALLCLOCK_DISPATCH_DEADLINE_EXCEEDED  # the D1 envelope this proves


# ═══════════════════ (c) recovery after quarantine ═══════════════════


def test_recovery_after_quarantine_legit_work_proceeds_and_idle_is_named(tmp_path):
    """After a quarantine: legitimate work still proceeds, the quarantine is
    journal-backed (re-imported on boot), never re-executed, and the skip is
    loud — a named idle code, not a silent tick."""
    from hermes.core.task_status import TaskStatus
    from hermes.research.autonomy_caps import LOOP_PATTERN_QUARANTINED

    conn = _db()
    poison_id = _admit_extract(conn, "dataset_manifest:dm-1")
    ctrl = _controller(conn, tmp_path, tag="poison2",
                       extract_fn=lambda task, untrusted: _poison_draft())
    for _ in range(3):
        ctrl.tick()
    assert poison_id in ctrl.quarantined_tasks()

    # legitimate work admitted AFTER the quarantine proceeds on boot.
    good_id = _admit_extract(conn, "dataset_manifest:dm-2")
    ctrl2 = _controller(conn, tmp_path, tag="recovery")
    assert poison_id in ctrl2.quarantined_tasks()  # journal-backed re-import
    assert ctrl2._loops.reason_for(poison_id)
    ctrl2.run(max_ticks=6)
    assert _status(conn, good_id) == TaskStatus.SUCCEEDED.value
    assert _status(conn, poison_id) == TaskStatus.FAILED.value
    run_events = [e for e in _events(conn, task_id=poison_id)
                  if e["to_state"] == "RUNNING"]
    assert len(run_events) == 3, "quarantine must stop re-execution"

    # the quarantine skip is loud: a live task carrying quarantine state (the
    # re-import/live-seed shape the controller consults before any dispatch)
    # yields the NAMED idle code — never a silent empty tick.
    live_id = _admit_extract(conn, "dataset_manifest:dm-3")
    ctrl3 = _controller(conn, tmp_path, tag="named")
    ctrl3._loops.seed_quarantined(
        {live_id: f"loop quarantined: seeded ({LOOP_PATTERN_QUARANTINED})"})
    out = ctrl3.tick()
    assert out.dispatched == []
    assert out.idle == LOOP_PATTERN_QUARANTINED
    assert any("quarantined" in note and live_id in note
               for note in ctrl3.notes)
    assert _status(conn, live_id) == "PENDING"


# ═══════════════════ (d) production boundary ═══════════════════


def test_no_production_declaration_in_this_slice():
    """P-AUTO-6 proves the loop; production is declared ONLY by the separate
    Phase-D-style certification record — never by completing this slice."""
    root = Path(__file__).resolve().parents[1]
    archive = root / "docs" / "archive"
    assert archive.exists()
    autonomy_records = [
        p.name for p in archive.glob("*CERTIFICATION*")
        if "AUTONOMY" in p.name.upper() or "P-AUTO" in p.name.upper()]
    assert autonomy_records == [], (
        "this slice declares no production certification; a Phase-D-style "
        "record is a separate deliverable")
    assert not (root / "PRODUCTION.md").exists()
    assert not (root / "docs" / "PRODUCTION.md").exists()
