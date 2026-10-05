"""N9 retraction-aware evidence admission tests (ratified N9 design).

Proves the N9 invariant through the production surfaces only:

* a retracted source is inadmissible as evidence for a newly recorded
  production classification (substrate admission + in-transaction
  re-check, existing EVIDENCE_DOES_NOT_RESOLVE / EVIDENCE_REF
  vocabulary — no new error codes);
* contradiction detection independently excludes retracted evidence
  (candidate derivation + admission validator + in-transaction
  re-resolution).

S5 remains the sole writer of retraction/invalidation state; the new
predicate only reads it. N1, identity, lifecycle, journal, replay, and
project isolation are otherwise unchanged.
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

from hermes.artifacts.store import ArtifactStore
from hermes.core import frozen_clock
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.core.node import NodeContract
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.provider_interactions import (
    ProviderInteractionRepository,
    make_persisting_sink,
)
from hermes.persistence.repositories import (
    ArtifactRepository,
    OperatorCredentialRepository,
    ProjectRepository,
    TaskRepository,
    _append_event_to_db,
)
from hermes.persistence.source_outcomes import source_artifact_retracted
from hermes.research.contradictions import contradiction_id_of
from hermes.research.controller import Controller
from hermes.research.gateway import (
    EVIDENCE_REF,
    GatewayRejection,
    _cx_resolve_evidence_ref,
    apply_intent,
)
from hermes.research.source_handlers import (
    ProviderMachinery,
    make_source_search_handler,
)
from hermes.research.source_templates import (
    build_source_search_task_payload,
)
from hermes.tools.providers.adapters.openalex import OpenalexAdapter
from hermes.tools.providers.base import TransportResponse
from hermes.tools.providers.replay import (
    RecordedTransport,
    interaction_to_fixture,
    provider_resolver_for,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1-long"
PROVIDER = "openalex"
OPENALEX_PAGE = {
    "meta": {"count": 1},
    "results": [{
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1234/abcdef",
        "title": "A study of things",
        "authorships": [{"author": {"display_name": "Ada L."}}],
        "publication_year": 2024,
        "primary_location": {"source": {"display_name": "J. Tests"}},
    }],
}


# ═══════════════════════ fixtures ═══════════════════════


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p2", "Other")
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    yield conn
    conn.close()


def _make(db, project="p1"):
    return Controller(db, project_id=project, clock=frozen_clock(CLOCK))


def _program(db, program_id="rp-1", *, project="p1"):
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, 1, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', ?,
                   ?, '[]', '[]', '[]', '[]', NULL, 'director', NULL, ?)""",
        (program_id, project, "ch-" + program_id,
         json.dumps([{"ref": "h1", "ladder_target": "SUPPORTED",
                      "falsification_condition": "fc", "rival_of": None,
                      "rival_status": None}]),
         json.dumps([{"ref": "p1"}]), CLOCK))
    db.commit()


def _task(db, task_id, *, project="p1"):
    repo = TaskRepository(db, frozen_clock(CLOCK))
    repo.create(NodeContract(
        task_id=task_id, project_id=project, task_type="TOOL_TASK",
        idempotency_key=f"idem-{task_id}", dependencies=[]))
    db.execute("UPDATE tasks SET status = 'RUNNING' WHERE task_id = ?",
               (task_id,))
    db.commit()


def _chain(db, *, ev_id, ev_hash, outcome_id, task_id, project="p1"):
    for aid, ch in ((outcome_id, f"outhash-{outcome_id}"),
                    (ev_id, ev_hash)):
        db.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type,
                content_hash, size_bytes, storage_path, producer,
                metadata_json, created_at)
               VALUES (?, ?, NULL, 'source_result', ?, 1, 'x', 't',
                       NULL, ?)""",
            (aid, project, ch, CLOCK))
    for child, parent in ((outcome_id, task_id), (ev_id, outcome_id)):
        db.execute(
            """INSERT INTO provenance_edges
               (artifact_id, upstream_id, edge_type, created_at)
               VALUES (?, ?, 'derived_from', ?)""",
            (child, parent, CLOCK))
    db.commit()


def _bind(db, ev_artifact_id, task_id, outcome_id, *, project="p1"):
    """Bind an existing evidence node to another task (outcome node +
    two-hop derived_from edges). One content hash lives in exactly one
    artifact row (global UNIQUE) — sharing the node is the legitimate
    multi-analyst pattern."""
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, NULL, 'source_result', ?, 1, 'x', 't',
                   NULL, ?)""",
        (outcome_id, project, f"outhash-{outcome_id}", CLOCK))
    for child, parent in ((outcome_id, task_id),
                          (ev_artifact_id, outcome_id)):
        db.execute(
            """INSERT INTO provenance_edges
               (artifact_id, upstream_id, edge_type, created_at)
               VALUES (?, ?, 'derived_from', ?)""",
            (child, parent, CLOCK))
    db.commit()


def _classify(db, *, failure_class, evidence_ref, task_id,
              classifier_version="1.0", **kw):
    return _make(db).record_failure_classification(
        program_ref="rp-1", hypothesis_ref="h1",
        failure_class=failure_class, evidence_refs=[evidence_ref],
        falsifying_evidence_refs=[evidence_ref],
        explanation=f"operator analysis {failure_class}",
        classifier_version=classifier_version,
        proposed_by=f"operator:{OP_ID}",
        producing_task_id=task_id, rationale="",
        operator_id=OP_ID, operator_token=OP_TOKEN, **kw)


def _dcv(db, evidence_ref, task_id, **kw):
    return _classify(
        db, failure_class="DECLARED_CONSTRAINT_VIOLATION",
        evidence_ref=evidence_ref, task_id=task_id,
        constraint_ref="hypothesis:h1:falsification_condition", **kw)


def _impl(db, evidence_ref, task_id, **kw):
    return _classify(
        db, failure_class="IMPLEMENTATION_FAILURE",
        evidence_ref=evidence_ref, task_id=task_id,
        failed_mechanism_ref="prediction:p1", **kw)


def _retract(db, source_ref, *, decision_ref="hd-1"):
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id="p1", correlation_id=decision_ref, caused_by="operator",
        reason="operator decision", payload={"decision": "RETRACT"})
    return apply_intent(db, Intent(
        kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
        project_id="p1", justification="n9 test",
        payload={"source_ref": source_ref, "reason": "retracted",
                 "human_decision_ref": decision_ref}))


def _status(db, cid):
    row = db.execute(
        "SELECT status FROM contradictions WHERE contradiction_id = ?",
        (cid,)).fetchone()
    return row["status"] if row else None


def _fc_count(db):
    return db.execute(
        "SELECT COUNT(*) c FROM artifacts "
        "WHERE artifact_type = 'failure_classification'").fetchone()["c"]


# ═══════════════════════ N9-A — fresh citation after retraction ═══════════════════════


class TestN9A:
    def test_fresh_citation_after_retraction_refused(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        assert _dcv(db, "source_result:evhash1", "t1")["rejected"] is False
        out = _make(db).record_source_retraction_decision(
            source_ref="source_result:evhash1", reason="retracted",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False, out
        assert source_artifact_retracted(db, "p1", "art-ev1") is True
        # Fresh analyst task bound to the retracted evidence, new
        # classifier version (new content identity — not a duplicate).
        _task(db, "t9")
        _bind(db, "art-ev1", "t9", "art-out9")
        before = _fc_count(db)
        fresh = _dcv(db, "source_result:evhash1", "t9",
                     classifier_version="2.0")
        assert fresh["rejected"] is True
        assert fresh["code"] == "MALFORMED_PAYLOAD"
        assert "EVIDENCE_DOES_NOT_RESOLVE" in fresh["detail"]
        assert _fc_count(db) == before
        det = _make(db).detect_contradictions()
        assert det["recorded"] == []

    def test_predicate_false_before_retraction(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        assert source_artifact_retracted(db, "p1", "art-ev1") is False
        assert source_artifact_retracted(db, "p1", "no-such-row") is False
        assert _dcv(db, "source_result:evhash1", "t1")["rejected"] is False


# ═══════════════════════ N9-B — existing contradiction after retraction ═══════════════════════


class TestN9B:
    def test_existing_lifecycle_unchanged_by_fence(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a = _dcv(db, "source_result:evhash1", "t1")["entity_id"]
        b = _impl(db, "source_result:evhash1", "t1")["entity_id"]
        cid = contradiction_id_of(a, b)
        assert _make(db).detect_contradictions()["recorded"] == [cid]
        _retract(db, "source_result:evhash1")
        assert _status(db, cid) == "SUPERSEDED"
        # History preserved: rows, parties, journal.
        row = db.execute(
            "SELECT party_a, party_b, status FROM contradictions "
            "WHERE contradiction_id = ?", (cid,)).fetchone()
        assert (row["party_a"], row["party_b"]) == (min(a, b), max(a, b))
        assert db.execute(
            "SELECT 1 FROM events WHERE event_type = ? "
            "AND correlation_id LIKE ?",
            (EventType.CONTRADICTION_SUPERSEDED.value,
             f"{cid}:superseded:%")).fetchone() is not None
        assert db.execute(
            "SELECT 1 FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchone() is not None
        # Re-detection records nothing new.
        assert _make(db).detect_contradictions()["recorded"] == []


# ═══════════════════════ N9-C / N9-D — project isolation ═══════════════════════


class TestN9CD:
    def test_cross_project_citation_of_retracted_refused(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        _retract(db, "source_result:evhash1")
        _program(db, program_id="rp-x", project="p2")
        _task(db, "t2", project="p2")
        out = Controller(db, project_id="p2",
                         clock=frozen_clock(CLOCK)
                         ).record_failure_classification(
            program_ref="rp-x", hypothesis_ref="h1",
            failure_class="DECLARED_CONSTRAINT_VIOLATION",
            evidence_refs=["source_result:evhash1"],
            falsifying_evidence_refs=["source_result:evhash1"],
            explanation="x", classifier_version="1.0",
            constraint_ref="hypothesis:h1:falsification_condition",
            proposed_by="operator:op-1", producing_task_id="t2",
            rationale="", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        # p2's own detector sees nothing cross-project.
        assert Controller(
            db, project_id="p2",
            clock=frozen_clock(CLOCK)).detect_contradictions()[
                "recorded"] == []

    def test_identical_bytes_governed_per_project(self, db):
        _program(db)
        _program(db, program_id="rp-x", project="p2")
        _task(db, "t1")
        _task(db, "t2", project="p2")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        _chain(db, ev_id="art-ev2", ev_hash="evhash2",
               outcome_id="art-out2", task_id="t2", project="p2")
        _retract(db, "source_result:evhash1")
        # p1's retraction does not govern p2's independently valid
        # evidence, and p1's own citation stays fenced.
        assert source_artifact_retracted(db, "p1", "art-ev1") is True
        assert source_artifact_retracted(db, "p2", "art-ev2") is False
        ok = Controller(db, project_id="p2",
                        clock=frozen_clock(CLOCK)
                        ).record_failure_classification(
            program_ref="rp-x", hypothesis_ref="h1",
            failure_class="IMPLEMENTATION_FAILURE",
            evidence_refs=["source_result:evhash2"],
            falsifying_evidence_refs=["source_result:evhash2"],
            explanation="operator analysis", classifier_version="1.0",
            failed_mechanism_ref="prediction:p1",
            proposed_by="operator:op-1", producing_task_id="t2",
            rationale="", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert ok["rejected"] is False, ok
        _task(db, "t9")
        _bind(db, "art-ev1", "t9", "art-out9")
        stale = _dcv(db, "source_result:evhash1", "t9",
                     classifier_version="2.0")
        assert stale["rejected"] is True


# ═══════════════════════ N9-E / N9-F — missing / malformed unchanged ═══════════════════════


class TestN9EF:
    def test_missing_evidence_unchanged(self, db):
        _program(db)
        _task(db, "t-prod")
        out = _dcv(db, "source_result:00", "t-prod")
        assert out["rejected"] is True

    def test_malformed_evidence_unchanged(self, db):
        _program(db)
        _task(db, "t-prod")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t-prod")
        bad_class = _make(db).record_failure_classification(
            program_ref="rp-1", hypothesis_ref="h1",
            failure_class="NOT_A_CLASS",
            evidence_refs=["source_result:evhash1"],
            falsifying_evidence_refs=["source_result:evhash1"],
            explanation="x", classifier_version="1.0",
            proposed_by="operator:op-1", producing_task_id="t-prod",
            rationale="", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert bad_class["rejected"] is True
        assert bad_class["code"] == "MALFORMED_PAYLOAD"
        bad_shape = _make(db).record_failure_classification(
            program_ref="rp-1", hypothesis_ref="h1",
            failure_class="UNKNOWN", evidence_refs=["not-a-ref"],
            falsifying_evidence_refs=["not-a-ref"], explanation="x",
            classifier_version="1.0", proposed_by="operator:op-1",
            producing_task_id="t-prod", rationale="", operator_id=OP_ID,
            operator_token=OP_TOKEN)
        assert bad_shape["rejected"] is True


# ═══════════════════════ N9-G — repeated stale citation ═══════════════════════


class TestN9G:
    def test_repeated_stale_citation_deterministic(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        _retract(db, "source_result:evhash1")
        _task(db, "t9")
        _bind(db, "art-ev1", "t9", "art-out9")
        first = _dcv(db, "source_result:evhash1", "t9",
                     classifier_version="2.0")
        second = _dcv(db, "source_result:evhash1", "t9",
                      classifier_version="2.0")
        assert first["rejected"] is True and second["rejected"] is True
        assert (first["code"], second["code"]) == (
            "MALFORMED_PAYLOAD", "MALFORMED_PAYLOAD")
        assert first["detail"] == second["detail"]
        assert _fc_count(db) == 0
        assert _make(db).detect_contradictions()["recorded"] == []


# ═══════════════════════ N9-H — created before, detected after ═══════════════════════


class TestN9H:
    def test_detection_after_retraction_excludes(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a = _dcv(db, "source_result:evhash1", "t1")["entity_id"]
        b = _impl(db, "source_result:evhash1", "t1")["entity_id"]
        # No detection before retraction; retract; detect only after.
        _retract(db, "source_result:evhash1")
        det = _make(db).detect_contradictions()
        assert det["recorded"] == []
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 0
        # The S5 lifecycle for the invalidated parties is unchanged:
        # re-detection never resurrects them.
        assert _make(db).detect_contradictions()["recorded"] == []
        assert a != b


# ═══════════════════════ N9-I — replayed bytes after retraction ═══════════════════════


class _ScriptedTransport:
    def __init__(self, script):
        self._script = list(script)
        self.contacted = 0

    def request(self, spec):
        self.contacted += 1
        action = self._script.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action


class _RefusingTransport:
    def __init__(self):
        self.contacted = 0

    def request(self, spec):
        self.contacted += 1
        raise AssertionError("live provider contacted")


class _FakeLimiter:
    def acquire(self, provider):
        return True, ""

    def release(self, provider):
        pass

    def note_throttled(self, provider, retry_after=None):
        pass

    def last_denial_reason(self, provider):
        return ""


class _FakeRecorder:
    def __init__(self):
        self.logs = []

    def record(self, log):
        self.logs.append(log)


class _FakeClock:
    def __init__(self, t=CLOCK):
        self.t = t

    def now_utc(self):
        return self.t

    def monotonic(self):
        return 0.0

    def sleep(self, delay):
        return None


def _ok_response():
    return TransportResponse(
        status=200, body=json.dumps(OPENALEX_PAGE).encode("utf-8"),
        headers={}, content_type="application/json")


class TestN9I:
    def test_replay_does_not_resurrect_validity(self, db, tmp_path):
        from hermes.tools.providers.replay import RecordedInteraction
        store = ArtifactStore(
            str(tmp_path / "store"),
            ArtifactRepository(db, frozen_clock(CLOCK)),
            clock=frozen_clock(CLOCK))
        adapters = {PROVIDER: OpenalexAdapter()}
        inner = _ScriptedTransport([_ok_response()])
        machinery = ProviderMachinery(
            adapters=adapters,
            transport=RecordedTransport(
                inner, resolve_provider=provider_resolver_for(adapters),
                clock=_FakeClock(), mode="record",
                sink=make_persisting_sink(db, store, _FakeClock())),
            limiter=_FakeLimiter(), recorder=_FakeRecorder(),
            clock=_FakeClock())
        ctrl = Controller(
            db, project_id="p1", owner="n9i", clock=lambda: CLOCK,
            lease_seconds=60,
            task_handlers={"source_search": make_source_search_handler(
                machinery)},
            artifact_store=store)
        task_id = apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload=build_source_search_task_payload(
                PROVIDER, {"identifiers": {}, "topic": "dark matter",
                           "mode": "TOPIC", "unrecognized_hints": []},
                scope_ref="p1"))).entity_id
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(task_id) is TaskStatus.SUCCEEDED
        recorded = sorted(
            r["content_hash"] for r in db.execute(
                "SELECT content_hash FROM artifacts "
                "WHERE artifact_type = 'source_result'").fetchall())
        assert recorded
        rows = ProviderInteractionRepository(db).list_for_task(task_id)
        fixtures = {}
        for row in rows:
            body = store.read(row["response_body_hash"])
            fx = interaction_to_fixture(
                RecordedInteraction(
                    interaction_id=row["interaction_id"],
                    provider_id=row["provider_id"],
                    adapter_version=row["adapter_version"],
                    parser_version=row["parser_version"],
                    normalized_request=json.loads(row["request_json"]),
                    request_hash=row["normalized_request_hash"],
                    status_class=row["response_status_class"],
                    response_body_hash=row["response_body_hash"],
                    outcome_kind=row["outcome_kind"],
                    failure_class=row["failure_class"],
                    retrieved_at=row["retrieved_at"],
                    source_url_redacted=row["source_url_redacted"]),
                body, headers={}, status=200)
            fixtures[fx.fixture_id] = fx
        # Retract the recorded source through the production surface.
        _program(db)
        out = _make(db).record_source_retraction_decision(
            source_ref=f"source_result:{recorded[0]}", reason="retracted",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False, out
        # Replay identical bytes: deterministic, zero live contact.
        refusing = _RefusingTransport()
        machinery2 = ProviderMachinery(
            adapters=adapters,
            transport=RecordedTransport(
                refusing, resolve_provider=provider_resolver_for(adapters),
                clock=_FakeClock(), mode="replay", fixtures=fixtures),
            limiter=_FakeLimiter(), recorder=_FakeRecorder(),
            clock=_FakeClock())
        ctrl2 = Controller(
            db, project_id="p1", owner="n9i-replay", clock=lambda: CLOCK,
            lease_seconds=60,
            task_handlers={"source_search": make_source_search_handler(
                machinery2)},
            artifact_store=store)
        task2 = apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload=build_source_search_task_payload(
                PROVIDER, {"identifiers": {}, "topic": "dark matter",
                           "mode": "TOPIC", "unrecognized_hints": []},
                scope_ref="p1"))).entity_id
        ctrl2.run(max_ticks=8)
        assert TaskRepository(db).get_status(task2) is TaskStatus.SUCCEEDED
        assert refusing.contacted == 0
        replayed = sorted(
            r["content_hash"] for r in db.execute(
                "SELECT content_hash FROM artifacts "
                "WHERE artifact_type = 'source_result'").fetchall())
        assert set(replayed) == set(recorded)
        # Fresh citation of the retracted evidence is refused: replay
        # determinism does not resurrect admissibility.
        _task(db, "t-n9i")
        ev_row = db.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE content_hash = ? AND artifact_type = 'source_result'",
            (recorded[0],)).fetchone()
        db.execute(
            """INSERT INTO artifacts (artifact_id, project_id, task_id,
               artifact_type, content_hash, size_bytes, storage_path,
               producer, metadata_json, created_at)
               VALUES ('n9i-out', 'p1', NULL, 'source_result',
                       'outhash-n9i-out', 1, 'x', 't', NULL, ?)""",
            (CLOCK,))
        for child, parent in (("n9i-out", "t-n9i"),
                              (ev_row["artifact_id"], "n9i-out")):
            db.execute(
                "INSERT INTO provenance_edges (artifact_id, upstream_id, "
                "edge_type, created_at) VALUES (?, ?, 'derived_from', ?)",
                (child, parent, CLOCK))
        db.commit()
        fresh = _dcv(db, f"source_result:{recorded[0]}", "t-n9i",
                     classifier_version="2.0")
        assert fresh["rejected"] is True
        assert _make(db).detect_contradictions()["recorded"] == []


# ═══════════════════════ N9-J — valid pre-retraction behavior ═══════════════════════


class TestN9J:
    def test_valid_evidence_admits_and_detects(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a = _dcv(db, "source_result:evhash1", "t1")
        b = _impl(db, "source_result:evhash1", "t1")
        assert a["rejected"] is False and b["rejected"] is False
        det = _make(db).detect_contradictions()
        assert det["recorded"] == [
            contradiction_id_of(a["entity_id"], b["entity_id"])]
        assert _status(db, det["recorded"][0]) == "OPEN"

    def test_deterministic_rebuild(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        first = (_dcv(db, "source_result:evhash1", "t1"),
                 _impl(db, "source_result:evhash1", "t1"))
        conn2 = connect(":memory:")
        migrate_to_latest(conn2)
        ProjectRepository(conn2, frozen_clock(CLOCK)).create("p1", "Test")
        OperatorCredentialRepository(conn2, frozen_clock(CLOCK)).register(
            OP_ID, OP_TOKEN, "Test Operator")
        try:
            _program(conn2)
            _task(conn2, "t1")
            _chain(conn2, ev_id="art-ev1", ev_hash="evhash1",
                   outcome_id="art-out1", task_id="t1")
            second = (_dcv(conn2, "source_result:evhash1", "t1"),
                      _impl(conn2, "source_result:evhash1", "t1"))
            assert (first[0]["entity_id"], first[1]["entity_id"]) == (
                second[0]["entity_id"], second[1]["entity_id"])
            assert contradiction_id_of(
                first[0]["entity_id"], first[1]["entity_id"]
            ) == contradiction_id_of(
                second[0]["entity_id"], second[1]["entity_id"])
        finally:
            conn2.close()


# ═══════════════════════ adversarial ═══════════════════════


class TestN9Adversarial:
    def test_duplicate_retraction_stale(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        first = _retract(db, "source_result:evhash1")
        assert first.duplicate is False
        with pytest.raises(GatewayRejection) as exc:
            _retract(db, "source_result:evhash1", decision_ref="hd-2")
        assert exc.value.code == "STALE"

    def test_duplicate_classification_idempotent(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        first = _dcv(db, "source_result:evhash1", "t1")
        second = _dcv(db, "source_result:evhash1", "t1")
        assert second["duplicate"] is True
        assert second["entity_id"] == first["entity_id"]

    def test_invalidated_classification_excluded(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a = _dcv(db, "source_result:evhash1", "t1")["entity_id"]
        b = _impl(db, "source_result:evhash1", "t1")["entity_id"]
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (json.dumps({"invalidation_marker": "INVALIDATED"}), a))
        db.commit()
        assert _make(db).detect_contradictions()["recorded"] == []
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.RECORD_CONTRADICTION,
                proposed_by="DETERMINISTIC", project_id="p1",
                justification="n9",
                payload={"party_a": a, "party_b": b,
                         "detector_version": "cx-detect-v1",
                         "supersedes_ref": ""}))
        assert exc.value.code == EVIDENCE_REF
        assert b != a

    def test_journal_failure_rolls_back(self, db):
        import hermes.research.controller as ctrl_mod
        import hermes.research.verdict_decisions as vd_mod
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")

        def _failing(conn, clock, event_type, *a, **kw):
            raise RuntimeError("simulated storage failure")

        # Both append seams are patched: the failure must hold whether the
        # controller (pre-extraction) or the helper (post-extraction) owns
        # the verdict's first journal write.
        with mock.patch.object(ctrl_mod, "_append_event_to_db", _failing), \
                mock.patch.object(vd_mod, "_append_event_to_db", _failing), \
                pytest.raises(RuntimeError):
            _dcv(db, "source_result:evhash1", "t1")
        assert _fc_count(db) == 0
        assert ctrl_mod._append_event_to_db is not None

    def test_refusal_leaves_no_partial_state(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        _retract(db, "source_result:evhash1")
        _task(db, "t9")
        _bind(db, "art-ev1", "t9", "art-out9")
        arts_before = db.execute(
            "SELECT COUNT(*) c FROM artifacts").fetchone()["c"]
        edges_before = db.execute(
            "SELECT COUNT(*) c FROM provenance_edges").fetchone()["c"]
        max_event_before = db.execute(
            "SELECT COALESCE(MAX(event_id), 0) m FROM events").fetchone()["m"]
        out = _dcv(db, "source_result:evhash1", "t9",
                   classifier_version="2.0")
        assert out["rejected"] is True
        # The operator-verdict journal row plus the refusal audit row are
        # the expected refusal-as-data trail; no classification state
        # lands (no artifact row, no new edges, no contradiction).
        assert _fc_count(db) == 0
        assert db.execute(
            "SELECT COUNT(*) c FROM artifacts").fetchone()["c"] \
            == arts_before
        assert db.execute(
            "SELECT COUNT(*) c FROM provenance_edges").fetchone()["c"] \
            == edges_before
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 0
        new_types = sorted(
            r["event_type"] for r in db.execute(
                "SELECT event_type FROM events WHERE event_id > ?",
                (max_event_before,)).fetchall())
        assert new_types, "refusal must leave an audit trail"
        assert "ContradictionDetected" not in new_types

    def test_lease_contention_refuses(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        holder = _make(db)
        assert holder._acquire_lock() is True
        try:
            out = _dcv(db, "source_result:evhash1", "t1")
            assert out["rejected"] is True
            assert out["code"] == "LOCK"
        finally:
            holder._release_lock()
        assert _dcv(db, "source_result:evhash1", "t1")["rejected"] is False

    def test_redetection_after_resolution(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a = _dcv(db, "source_result:evhash1", "t1")["entity_id"]
        b = _impl(db, "source_result:evhash1", "t1")["entity_id"]
        cid = _make(db).detect_contradictions()["recorded"][0]
        assert cid == contradiction_id_of(a, b)
        res = _make(db).record_contradiction_resolution(
            contradiction_id=cid, operator_id=OP_ID,
            operator_token=OP_TOKEN)
        assert res["rejected"] is False
        det = _make(db).detect_contradictions()
        assert det["recorded"] == []
        assert _status(db, cid) == "RESOLVED"

    def test_supersession_path_unaffected(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        a = _dcv(db, "source_result:evhash1", "t1")["entity_id"]
        b = _impl(db, "source_result:evhash1", "t1")["entity_id"]
        cx1 = _make(db).detect_contradictions()["recorded"][0]
        _task(db, "t3")
        _chain(db, ev_id="art-ev2", ev_hash="evhash2",
               outcome_id="art-out2", task_id="t3")
        c = _dcv(db, "source_result:evhash2", "t3")["entity_id"]
        d = _impl(db, "source_result:evhash2", "t3")["entity_id"]
        r2 = apply_intent(db, Intent(
            kind=IntentKind.RECORD_CONTRADICTION,
            proposed_by="DETERMINISTIC", project_id="p1",
            justification="n9",
            payload={"party_a": c, "party_b": d,
                     "detector_version": "cx-detect-v1",
                     "supersedes_ref": cx1}))
        assert r2.duplicate is False
        assert _status(db, cx1) == "SUPERSEDED"
        assert _status(db, r2.entity_id) == "OPEN"
        assert (a, b) != (c, d)

    def test_direct_contradiction_intent_over_retracted_refused(self, db):
        _program(db)
        _task(db, "t1")
        _chain(db, ev_id="art-ev1", ev_hash="evhash1",
               outcome_id="art-out1", task_id="t1")
        assert _cx_resolve_evidence_ref(
            db, "p1", "source_result:evhash1") == "art-ev1"
        a = _dcv(db, "source_result:evhash1", "t1")["entity_id"]
        _task(db, "t2")
        _bind(db, "art-ev1", "t2", "art-out2")
        b = _impl(db, "source_result:evhash1", "t2")["entity_id"]
        _retract(db, "source_result:evhash1")
        # The validator's resolution layer now excludes the retracted
        # evidence — independently of candidate derivation.
        assert _cx_resolve_evidence_ref(
            db, "p1", "source_result:evhash1") is None
        # Bypass candidate derivation entirely: the hand-built intent
        # must still fail at the admission validator.
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.RECORD_CONTRADICTION,
                proposed_by="DETERMINISTIC", project_id="p1",
                justification="n9",
                payload={"party_a": a, "party_b": b,
                         "detector_version": "cx-detect-v1",
                         "supersedes_ref": ""}))
        assert exc.value.code == EVIDENCE_REF
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 0
