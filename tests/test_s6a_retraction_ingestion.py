"""Step 8 Slice 1 (Step 6 gate §18) — operator-decision ingestion for
source retraction (closes GAP-1).

Covers the Step 8 charter test matrix through the PRODUCTION controller
path (``Controller.record_source_retraction_decision``), not direct
gateway fixtures:

A. Happy path          (decision → HumanDecisionReceived → RETRACT_SOURCE
                        → S5 cascade)
B. Invalid operator    (OPERATOR refusal, zero writes — Attack 1)
C. Lease contention    (LOCK refusal, zero writes — Attack 2)
D. Lease cleanup       (lock released after success + every refusal path)
E. Invalid source_ref  (missing / empty / malformed)
F. Invalid reason      (missing / empty)
G. Oversized reason    (bounded RATIONALE refusal pre-write — Attack 5)
H. Idempotent replay   (1× / 2× / 3× — Attack 3)
I. Cross-project       (decision reuse across projects fail-closed —
                        Attack 4)
J. Fabricated gateway  (unknown human_decision_ref stays fail-closed)

Plus the end-to-end production-path proof: decision → SourceRetracted →
superseding ResearchDecision → SUCCEEDED→INVALIDATED → cone invalidation
→ curated-knowledge invalidation where the basis intersects.

The S5 cascade semantics themselves are pinned by
tests/test_s5_retraction.py and tests/test_step7_curated_registry.py;
this file pins the ingestion surface only and references that coverage
rather than duplicating it.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from hermes.core import frozen_clock
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    OperatorCredentialRepository,
    ProjectRepository,
    _append_event_to_db,
)
from hermes.research.controller import Controller
from hermes.research.evidence_ladder import classification_content_hash
from hermes.research.feature_binding import (
    CURATED_KIND_REFUTED_PATTERN,
    FEATURE_BINDING_ARTIFACT_TYPE,
    FEATURE_BINDING_REF_PREFIX,
    binding_content_hash,
    signature_from_binding,
)
from hermes.research.gateway import (
    EVIDENCE_REF,
    PROPOSAL,
    STALE,
    GatewayRejection,
    apply_intent,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1"
REASON = "source retracted by publisher notice 2026-01"


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


def _insert_artifact(db, artifact_id, *, artifact_type="source_result",
                     content_hash=None, project="p1", task_id=None,
                     meta=None):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, 1, 'x', 't', ?, ?)""",
        (artifact_id, project, task_id, artifact_type,
         content_hash or f"ch-{artifact_id}",
         json.dumps(meta) if meta else None, CLOCK))


def _insert_edge(db, artifact_id, upstream_id, edge_type="cites"):
    db.execute(
        """INSERT INTO provenance_edges
           (artifact_id, upstream_id, edge_type, created_at)
           VALUES (?, ?, ?, ?)""",
        (artifact_id, upstream_id, edge_type, CLOCK))


def _insert_task(db, task_id, status="SUCCEEDED"):
    from hermes.core.node import NodeContract
    from hermes.persistence.repositories import TaskRepository
    repo = TaskRepository(db, frozen_clock(CLOCK))
    node = NodeContract(
        task_id=task_id, project_id="p1", task_type="TOOL_TASK",
        idempotency_key=f"idem-{task_id}", dependencies=[])
    repo.create(node)
    if status != "PENDING":
        db.execute("UPDATE tasks SET status = ? WHERE task_id = ?",
                   (status, task_id))


def _counts(db):
    events = db.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
    artifacts = db.execute(
        "SELECT COUNT(*) c FROM artifacts").fetchone()["c"]
    lock = db.execute(
        "SELECT COUNT(*) c FROM scheduler_lock").fetchone()["c"]
    return events, artifacts, lock


def _decision_rows(db, project="p1"):
    return db.execute(
        "SELECT * FROM events WHERE project_id = ? AND event_type = ?",
        (project,
         EventType.HUMAN_DECISION_RECEIVED.value)).fetchall()


def _source_retracted_rows(db, project="p1"):
    return db.execute(
        "SELECT * FROM events WHERE project_id = ? AND event_type = ?",
        (project, EventType.SOURCE_RETRACTED.value)).fetchall()


# --- curated-seeding helpers (trimmed Step 7 fixture model: the curated
# --- entry's retraction basis IS a source artifact, so the S5 cascade can
# --- reach it through the production ingestion path).

def _hyp(ref, ladder="SUPPORTED"):
    return {"ref": ref, "ladder_target": ladder,
            "falsification_condition": "fc", "rival_of": None,
            "rival_status": None}


def _insert_program(db, program_id="rp-1", *, hypotheses=(), project="p1"):
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, 1, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', ?,
                   '[]', '[]', '[]', '[]', '[]', NULL, 'director', NULL, ?)""",
        (program_id, project, "ch-" + program_id,
         json.dumps(list(hypotheses)), CLOCK))


def _insert_classification(db, *, cls_art="fc-1", project="p1",
                           falsifying_refs=None):
    if falsifying_refs is None:
        falsifying_refs = ["evidence:evhash1"]
    meta = {
        "schema_version": "1",
        "failure_class": "DECLARED_CONSTRAINT_VIOLATION",
        "hypothesis_ref": "h1",
        "program_ref": "rp-1",
        "classification_id": cls_art,
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": list(falsifying_refs),
        "constraint_ref": "hypothesis:h1:falsification_condition",
        "failed_mechanism_ref": None,
        "regime_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": "s6a test",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": list(falsifying_refs),
        "permitted_actions": [],
    }
    content_hash = classification_content_hash(meta, project)
    _insert_artifact(db, cls_art, artifact_type="failure_classification",
                     content_hash=content_hash, project=project, meta=meta)
    return "failure_classification:" + (content_hash or "")


def _seed_curated_on_source(db, *, source_id="art-src1",
                            source_hash="srchash1"):
    """A curatable state whose falsifying evidence IS a source artifact.
    Returns the curated entry id after gateway admission."""
    from hermes.research.evidence_ladder import ladder_state_id
    from hermes.research.feature_binding import curation_command_hash
    _insert_program(db, "rp-1", hypotheses=[_hyp("h1")])
    _insert_artifact(db, source_id, artifact_type="source_result",
                     content_hash=source_hash)
    cls_ref = _insert_classification(
        db, falsifying_refs=[f"source_result:{source_hash}"])
    db.execute(
        """INSERT INTO evidence_ladder_state
           (state_id, project_id, program_id, hypothesis_ref,
            version, rung, transition_id, derived_from, created_at)
           VALUES (?, 'p1', 'rp-1', 'h1', 1, 'REFUTED', 'tr-1',
                   'ratification', ?)""",
        (ladder_state_id("rp-1", "h1", 1), CLOCK))
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.EVIDENCE_TRANSITION_APPLIED.value,
        project_id="p1", correlation_id="tr-1",
        from_state="SUPPORTED", to_state="REFUTED",
        caused_by="controller",
        reason="evidence ladder ratification transition: SUPPORTED -> REFUTED",
        payload={"program_id": "rp-1", "hypothesis_ref": "h1",
                 "from_rung": "SUPPORTED", "to_rung": "REFUTED",
                 "driver": "ratification",
                 "ratified_by": "classification",
                 "classification_ref": cls_ref})
    binding = {"schema_version": 1, "project_ref": "p1",
               "program_ref": "rp-1", "hypothesis_ref": "h1",
               "instrument": "xauusd", "feature_family": "momentum",
               "claim_type": "directional"}
    content_hash = binding_content_hash(binding)
    _insert_artifact(db, "art-fb1", artifact_type=FEATURE_BINDING_ARTIFACT_TYPE,
                     content_hash=content_hash, meta=binding)
    binding_ref = FEATURE_BINDING_REF_PREFIX + content_hash
    sig = signature_from_binding(binding)
    payload = {"operation": "ADMIT", "kind": CURATED_KIND_REFUTED_PATTERN,
               "program_ref": "rp-1", "hypothesis_ref": "h1",
               "source_binding_ref": binding_ref,
               "source_decision_event_ref": "tr-1",
               "signature_json": sig, "supersedes_ref": ""}
    cmd_hash = curation_command_hash(payload)
    dref = f"curate-decision-{cmd_hash}"
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id="p1", correlation_id=dref, caused_by="operator",
        reason="operator curation verdict (ADMIT)",
        payload={"decision": "CURATE_KNOWLEDGE", "curation_id": cmd_hash,
                 "operator_id": OP_ID, "rationale": ""})
    return apply_intent(db, Intent(
        kind=IntentKind.CURATE_KNOWLEDGE, proposed_by="DETERMINISTIC",
        project_id="p1", justification="s6a seed",
        payload={**payload, "human_decision_ref": dref,
                 "operator_id": OP_ID})).entity_id


# ═══════════════════════ A. Happy path ═══════════════════════


class TestHappyPath:
    def test_decision_accepted_and_cascade_executes(self, db):
        _insert_task(db, "t-producer")
        _insert_artifact(db, "src-a", task_id="t-producer")
        _insert_artifact(db, "down-1", task_id="t-producer")
        _insert_edge(db, "down-1", "src-a", "cites")
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False
        assert out["duplicate"] is False
        assert out["source_ref"] == "src-a"
        assert out["retraction_id"]
        assert out["decision_ref"].startswith("retract-decision-")
        assert out["entity_id"] == "src-a"

    def test_decision_event_row_binds_digest_not_reason(self, db):
        _insert_artifact(db, "src-a")
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        rows = _decision_rows(db)
        assert len(rows) == 1
        assert rows[0]["correlation_id"] == out["decision_ref"]
        assert rows[0]["caused_by"] == "operator"
        payload = json.loads(rows[0]["payload_json"])
        # Step 8 payload lock: exactly these keys, digest not text.
        assert set(payload) == {"decision", "retraction_id", "source_ref",
                               "reason_digest", "operator_id"}
        assert payload["decision"] == "RETRACT_SOURCE"
        assert payload["retraction_id"] == out["retraction_id"]
        assert payload["source_ref"] == "src-a"
        assert payload["operator_id"] == OP_ID
        assert payload["reason_digest"] == hashlib.sha256(
            REASON.encode("utf-8")).hexdigest()
        assert REASON not in rows[0]["payload_json"]

    def test_s5_effects_present_after_ingestion(self, db):
        _insert_task(db, "t-producer")
        _insert_artifact(db, "src-a", task_id="t-producer")
        _insert_artifact(db, "down-1", task_id="t-producer")
        _insert_edge(db, "down-1", "src-a", "cites")
        ctrl = _make(db)
        ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        # SourceRetracted emitted
        assert len(_source_retracted_rows(db)) == 1
        # superseding ResearchDecision artifact recorded
        dec = db.execute(
            "SELECT * FROM artifacts WHERE artifact_type = ?",
            ("ResearchDecision",)).fetchall()
        assert len(dec) == 1
        # downstream cone member invalidated
        meta = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = ?",
            ("down-1",)).fetchone()["metadata_json"])
        assert meta.get("invalidation_marker") == "INVALIDATED"
        assert meta.get("invalidated_by")
        # SUCCEEDED producer transitioned with event
        assert db.execute(
            "SELECT status FROM tasks WHERE task_id = ?",
            ("t-producer",)).fetchone()["status"] == "INVALIDATED"
        assert db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.TASK_INVALIDATED.value,)).fetchone()["c"] == 1


# ═══════════════════════ B. Invalid operator (Attack 1) ═══════════════════════


class TestInvalidOperator:
    def test_bad_operator_refused_with_zero_writes(self, db):
        _insert_artifact(db, "src-a")
        before = _counts(db)
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id="bad-op", operator_token="wrong-token")
        assert out["rejected"] is True
        assert out["code"] == "OPERATOR"
        assert _counts(db) == before
        assert _decision_rows(db) == []
        assert _source_retracted_rows(db) == []


# ═══════════════════════ C. Lease contention (Attack 2) ═══════════════════════


class TestLeaseContention:
    def test_held_lease_refused_with_zero_writes_then_lands(self, db):
        _insert_artifact(db, "src-a")
        ctrl = _make(db)
        other = _make(db)
        assert other._acquire_lock() is True
        before = _counts(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        assert out["code"] == "LOCK"
        assert _counts(db) == before
        assert _decision_rows(db) == []
        other._release_lock()
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False
        assert len(_source_retracted_rows(db)) == 1


# ═══════════════════════ D. Lease cleanup ═══════════════════════


class TestLeaseCleanup:
    def _lock_count(self, db):
        return db.execute(
            "SELECT COUNT(*) c FROM scheduler_lock").fetchone()["c"]

    def test_lease_released_after_success(self, db):
        _insert_artifact(db, "src-a")
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False
        assert self._lock_count(db) == 0

    def test_lease_released_after_operator_refusal(self, db):
        _insert_artifact(db, "src-a")
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id="bad-op", operator_token="wrong-token")
        assert out["rejected"] is True
        assert self._lock_count(db) == 0

    def test_lease_released_after_gateway_refusal(self, db):
        # Valid shape, unknown source: the decision records, the gateway
        # refuses EVIDENCE_REF, and the lease is still released.
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="ghost-src", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        assert out["code"] == EVIDENCE_REF
        assert self._lock_count(db) == 0
        assert _source_retracted_rows(db) == []

    def test_lease_released_after_malformed_refusal(self, db):
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        assert self._lock_count(db) == 0


# ═══════════════════════ E. Invalid source_ref ═══════════════════════


class TestInvalidSourceRef:
    def test_missing_source_ref_rejected(self, db):
        ctrl = _make(db)
        before = _counts(db)
        out = ctrl.record_source_retraction_decision(
            source_ref=None, reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        assert out["code"] == "MALFORMED_PAYLOAD"
        assert _counts(db) == before

    def test_empty_source_ref_rejected(self, db):
        ctrl = _make(db)
        before = _counts(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        assert out["code"] == "MALFORMED_PAYLOAD"
        assert _counts(db) == before

    def test_nonexistent_source_gateway_refusal(self, db):
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="nope", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        assert out["code"] == EVIDENCE_REF
        assert _source_retracted_rows(db) == []


# ═══════════════════════ F. Invalid reason ═══════════════════════


class TestInvalidReason:
    def test_missing_reason_rejected(self, db):
        _insert_artifact(db, "src-a")
        ctrl = _make(db)
        before = _counts(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=None,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        assert out["code"] == "MALFORMED_PAYLOAD"
        assert _counts(db) == before

    def test_blank_reason_rejected(self, db):
        _insert_artifact(db, "src-a")
        ctrl = _make(db)
        before = _counts(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason="   ",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        assert out["code"] == "MALFORMED_PAYLOAD"
        assert _counts(db) == before


# ═══════════════════════ G. Oversized reason (Attack 5) ═══════════════════════


class TestOversizedReason:
    def test_reason_bomb_bounded_refusal_pre_write(self, db):
        _insert_artifact(db, "src-a")
        ctrl = _make(db)
        before = _counts(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason="x" * 9000,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        assert out["code"] == "RATIONALE"
        assert _counts(db) == before
        assert _decision_rows(db) == []
        assert _source_retracted_rows(db) == []


# ═══════════════════════ H. Idempotent replay (Attack 3) ═══════════════════════


class TestIdempotentReplay:
    def test_triple_invocation_single_decision_single_cascade(self, db):
        _insert_task(db, "t-producer")
        _insert_artifact(db, "src-a", task_id="t-producer")
        _insert_artifact(db, "down-1", task_id="t-producer")
        _insert_edge(db, "down-1", "src-a", "cites")
        ctrl = _make(db)
        kw = {"source_ref": "src-a", "reason": REASON,
              "operator_id": OP_ID, "operator_token": OP_TOKEN}
        first = ctrl.record_source_retraction_decision(**kw)
        assert first["rejected"] is False
        assert first["duplicate"] is False
        second = ctrl.record_source_retraction_decision(**kw)
        third = ctrl.record_source_retraction_decision(**kw)
        assert second["duplicate"] is True
        assert second["rejected"] is False
        assert third["duplicate"] is True
        assert third["rejected"] is False
        assert second["retraction_id"] == first["retraction_id"]
        # Exactly one decision record and one cascade.
        assert len(_decision_rows(db)) == 1
        assert len(_source_retracted_rows(db)) == 1
        assert db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.TASK_INVALIDATED.value,)).fetchone()["c"] == 1

    def test_different_reason_after_retraction_is_stale(self, db):
        _insert_artifact(db, "src-a")
        ctrl = _make(db)
        first = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert first["rejected"] is False
        second = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason="a different cited reason",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        # A second, differing command on an already-superseded source must
        # not double-supersede: the gateway refuses STALE (existing S5
        # coverage referenced, not duplicated).
        assert second["rejected"] is True
        assert second["code"] == STALE
        assert len(_source_retracted_rows(db)) == 1


# ═══════════════════════ I. Cross-project isolation (Attack 4) ═══════════════════════


class TestCrossProjectIsolation:
    def test_decision_from_project_a_unusable_in_project_b(self, db):
        _insert_artifact(db, "src-a")
        ctrl_a = _make(db, project="p1")
        out = ctrl_a.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False
        # Reusing p1's decision ref for a p2 admission fails closed.
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
                project_id="p2", justification="cross-project reuse",
                payload={"source_ref": "src-a", "reason": REASON,
                         "human_decision_ref": out["decision_ref"]}))
        assert exc.value.code == PROPOSAL
        assert _source_retracted_rows(db, project="p2") == []


# ═══════════════════════ J. Fabricated gateway decision ═══════════════════════


class TestFabricatedGatewayDecision:
    def test_unknown_human_decision_ref_stays_fail_closed(self, db):
        _insert_artifact(db, "src-a")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
                project_id="p1", justification="fabricated",
                payload={"source_ref": "src-a", "reason": REASON,
                         "human_decision_ref": "hd-ghost"}))
        assert exc.value.code == PROPOSAL
        assert _source_retracted_rows(db) == []


# ═══════════════════════ End-to-end production-path proof ═══════════════════════


class TestEndToEndProductionPath:
    def test_full_chain_through_ingestion(self, db):
        curated_id = _seed_curated_on_source(db)
        # The curated entry's basis is the source artifact; give the
        # source a SUCCEEDED producer and a downstream cone member.
        _insert_task(db, "t-producer")
        db.execute("UPDATE artifacts SET task_id = ? WHERE artifact_id = ?",
                   ("t-producer", "art-src1"))
        _insert_artifact(db, "down-1", task_id="t-producer")
        _insert_edge(db, "down-1", "art-src1", "cites")
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="source_result:srchash1", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False
        assert out["duplicate"] is False
        # HumanDecisionReceived → SourceRetracted (the seed records one
        # CURATE_KNOWLEDGE decision too — count the RETRACT_SOURCE one).
        retract_decisions = [
            r for r in _decision_rows(db)
            if json.loads(r["payload_json"])["decision"] == "RETRACT_SOURCE"]
        assert len(retract_decisions) == 1
        assert retract_decisions[0]["correlation_id"] == out["decision_ref"]
        retracted = _source_retracted_rows(db)
        assert len(retracted) == 1
        # superseding ResearchDecision artifact
        dec = db.execute(
            "SELECT * FROM artifacts WHERE artifact_type = ?",
            ("ResearchDecision",)).fetchall()
        assert len(dec) == 1
        # SUCCEEDED → INVALIDATED transition with event
        assert db.execute(
            "SELECT status FROM tasks WHERE task_id = ?",
            ("t-producer",)).fetchone()["status"] == "INVALIDATED"
        assert db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.TASK_INVALIDATED.value,)).fetchone()["c"] == 1
        # dependency-cone invalidation
        meta = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = ?",
            ("down-1",)).fetchone()["metadata_json"])
        assert meta.get("invalidation_marker") == "INVALIDATED"
        assert meta.get("invalidated_by")
        # curated-knowledge invalidation where the basis intersects
        row = db.execute(
            "SELECT status, invalidation_event_ref FROM "
            "curated_knowledge_entries WHERE curated_id = ?",
            (curated_id,)).fetchone()
        assert row["status"] == "INVALIDATED"
        assert row["invalidation_event_ref"] is not None
        inv = db.execute(
            "SELECT payload_json FROM events WHERE event_type = ?",
            ("CuratedKnowledgeInvalidated",)).fetchone()
        assert inv is not None
        payload = json.loads(inv["payload_json"])
        assert payload["curated_id"] == curated_id
        assert "art-src1" in payload["matched_evidence"]
