"""S5 L2 read-path normalization/resolution tests (ratified S5 L2 design
gate — Option B).

The ``provenance_edges`` table stores dependency references in the
producers' durable forms (bare artifact IDs, typed ``<type>:<hash>``
references, bare task IDs). The S5 cone resolves every stored upstream
value to canonical ``artifacts.artifact_id`` identities before BFS
matching (``l2_resolution._l2_resolve_upstream``); stored representations are
never rewritten.

Matrix:
  Unit (resolver): bare hit, typed forms, misses, malformed, prefixes,
    task-hop per edge type, missing/malformed tasks, deferred carriers,
    claim refs, precedence, determinism.
  Integration: mixed graphs, typed/task cones, sibling exclusion,
    cross-project isolation, duplicate aliases, cycles, untouched branch.
  End-to-end: retraction through the production controller path with
    typed/task-linked dependents, task transitions, curated invalidation,
    replay determinism, idempotency.
  Compatibility: historical bare/typed/task/mixed graphs.
  Adversarial: A1–A12 from the design gate.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

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
    STALE,
    apply_intent,
)
from hermes.research.l2_resolution import _l2_resolve_upstream

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


def _insert_task(db, task_id, status="SUCCEEDED", *, project="p1",
                 spec=None):
    from hermes.core.node import NodeContract
    from hermes.persistence.repositories import TaskRepository
    repo = TaskRepository(db, frozen_clock(CLOCK))
    node = NodeContract(
        task_id=task_id, project_id=project, task_type="TOOL_TASK",
        idempotency_key=f"idem-{task_id}", dependencies=[])
    repo.create(node)
    if status != "PENDING":
        db.execute("UPDATE tasks SET status = ? WHERE task_id = ?",
                   (status, task_id))
    if spec is not None:
        db.execute("UPDATE tasks SET spec_json = ? WHERE task_id = ?",
                   (json.dumps(spec), task_id))


def _resolve(db, value, edge_type="cites"):
    return _l2_resolve_upstream(db, value, edge_type, {})


def _record_decision(db, ref="hd-1", project="p1"):
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id=project, correlation_id=ref, caused_by="operator",
        reason="operator decision", payload={"decision": "RETRACT"})


def _retract(db, source_ref="src-a", decision_ref="hd-1", project="p1",
             reason="source retracted by publisher"):
    return apply_intent(db, Intent(
        kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
        project_id=project, justification="S5 L2",
        payload={"source_ref": source_ref, "reason": reason,
                 "human_decision_ref": decision_ref}))


def _invalidated(db):
    # Downstream-invalidated artifacts (the superseding ResearchDecision
    # artifact itself carries the marker by construction — excluded).
    rows = db.execute(
        "SELECT artifact_id, artifact_type, metadata_json FROM artifacts "
        "WHERE artifact_type != 'ResearchDecision'").fetchall()
    out = set()
    for r in rows:
        try:
            meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
        except ValueError:
            meta = {}
        if meta.get("invalidation_marker") == "INVALIDATED":
            out.add(r["artifact_id"])
    return out


# ═══════════════════════ Unit: rules 1+2 ═══════════════════════


class TestResolverBareAndTyped:
    def test_1_bare_artifact_hit(self, db):
        _insert_artifact(db, "art-a")
        assert _resolve(db, "art-a") == {"art-a"}

    def test_2_typed_source_result(self, db):
        _insert_artifact(db, "art-s", content_hash="H" * 64)
        assert _resolve(db, "source_result:" + "H" * 64) == {"art-s"}

    def test_2b_typed_source_payload(self, db):
        _insert_artifact(db, "art-p", artifact_type="source_payload",
                         content_hash="P" * 64)
        assert _resolve(db, "source_payload:" + "P" * 64) == {"art-p"}

    def test_2b2_typed_source_search_and_fetch_outcome(self, db):
        _insert_artifact(db, "art-ss", artifact_type="source_search",
                         content_hash="S" * 64)
        assert _resolve(db, "source_search:" + "S" * 64) == {"art-ss"}
        _insert_artifact(db, "art-fo", artifact_type="source_fetch_outcome",
                         content_hash="O" * 64)
        assert _resolve(db, "source_fetch_outcome:" + "O" * 64) == {"art-fo"}

    def test_2c_typed_failure_classification(self, db):
        _insert_artifact(db, "fc-1", artifact_type="failure_classification",
                         content_hash="F" * 64)
        assert _resolve(db, "failure_classification:" + "F" * 64) == {"fc-1"}

    def test_2d_typed_feature_binding(self, db):
        _insert_artifact(db, "art-fb", artifact_type="feature_binding",
                         content_hash="B" * 64)
        assert _resolve(db, "feature_binding:" + "B" * 64) == {"art-fb"}

    def test_2e_evidence_form_carries_bare_id(self, db):
        _insert_artifact(db, "art-ev", artifact_type="evidence")
        assert _resolve(db, "evidence:art-ev") == {"art-ev"}

    def test_2f_type_prefix_is_part_of_identity(self, db):
        # A source_result: ref must never resolve a source_payload row
        # (SD-05/S6-A1 type-confusion discipline).
        _insert_artifact(db, "art-p", artifact_type="source_payload",
                         content_hash="P" * 64)
        assert _resolve(db, "source_result:" + "P" * 64) == set()

    def test_3_typed_miss(self, db):
        assert _resolve(db, "source_result:" + "Z" * 64) == set()

    def test_4_malformed_typed(self, db):
        assert _resolve(db, "source_result:") == set()
        assert _resolve(db, ":abc") == set()
        assert _resolve(db, "source_result") == set()
        assert _resolve(db, "") == set()
        assert _resolve(db, None) == set()
        assert _resolve(db, 123) == set()

    def test_4b_truncated_hash_never_matches(self, db):
        # SD2-04: exact full-hash equality only — a truncated alias
        # resolves to nothing.
        _insert_artifact(db, "art-s", content_hash="H" * 64)
        assert _resolve(db, "source_result:" + "H" * 24) == set()

    def test_5_unknown_prefix(self, db):
        assert _resolve(db, "frobnicate:abc123") == set()
        assert _resolve(db, "dataset_manifest:dm-1") == set()
        assert _resolve(db, "research_program:rp-1") == set()
        assert _resolve(db, "hypothesis:h1") == set()


# ═══════════════════════ Unit: rule 3 task-hop ═══════════════════════


def _fetch_task(db, task_id="t-fetch", *, source_hashes=(), project="p1"):
    _insert_task(db, task_id, project=project, spec={
        "source_refs": [f"source_result:{h}" for h in source_hashes]})


class TestResolverTaskHop:
    def test_6_derived_from_resolves_task_inputs(self, db):
        _insert_artifact(db, "art-s", content_hash="H" * 64)
        _fetch_task(db, source_hashes=["H" * 64])
        assert _resolve(db, "t-fetch", "derived_from") == {"art-s"}

    def test_6b_derived_from_ignores_task_outputs(self, db):
        # Sibling-production exclusion at resolver level: a task that
        # merely PRODUCED the seed does not resolve to it via
        # derived_from (only consumed inputs count).
        _insert_task(db, "t-prod")
        _insert_artifact(db, "art-s", task_id="t-prod")
        assert _resolve(db, "t-prod", "derived_from") == set()

    def test_7_used_as_input_resolves_task_outputs(self, db):
        _insert_task(db, "t-prod")
        _insert_artifact(db, "art-o1", task_id="t-prod")
        _insert_artifact(db, "art-o2", task_id="t-prod")
        assert _resolve(db, "t-prod", "used_as_input") == {"art-o1", "art-o2"}

    def test_7b_used_as_input_ignores_task_inputs(self, db):
        _insert_artifact(db, "art-s", content_hash="H" * 64)
        _fetch_task(db, "t-fetch", source_hashes=["H" * 64])
        # t-fetch produced nothing: outputs are empty even though it
        # consumed art-s.
        assert _resolve(db, "t-fetch", "used_as_input") == set()

    def test_8_cites_resolves_inputs_union_outputs(self, db):
        _insert_artifact(db, "art-s", content_hash="H" * 64)
        _fetch_task(db, "t-fetch", source_hashes=["H" * 64])
        _insert_artifact(db, "art-p", task_id="t-fetch")
        assert _resolve(db, "t-fetch", "cites") == {"art-s", "art-p"}

    def test_9_missing_task(self, db):
        assert _resolve(db, "t-ghost", "derived_from") == set()
        assert _resolve(db, "t-ghost", "used_as_input") == set()
        assert _resolve(db, "t-ghost", "cites") == set()

    def test_10_malformed_task_spec(self, db):
        _insert_task(db, "t-bad")
        db.execute("UPDATE tasks SET spec_json = 'not json' "
                   "WHERE task_id = 't-bad'")
        assert _resolve(db, "t-bad", "derived_from") == set()
        _insert_task(db, "t-nospec")
        db.execute("UPDATE tasks SET spec_json = '[1, 2, 3]' "
                   "WHERE task_id = 't-nospec'")
        assert _resolve(db, "t-nospec", "derived_from") == set()
        _insert_task(db, "t-norefs")
        assert _resolve(db, "t-norefs", "derived_from") == set()

    def test_10b_singular_source_ref_input(self, db):
        _insert_artifact(db, "art-s", content_hash="H" * 64)
        _insert_task(db, "t-ext", spec={"source_ref": "source_result:" +
                                                    "H" * 64})
        assert _resolve(db, "t-ext", "derived_from") == {"art-s"}


# ═══════════════════════ Unit: rules 4+, precedence, determinism ═══════════════════════


class TestResolverPrecedenceDeterminism:
    def test_11_deferred_carriers_unresolved(self, db):
        assert _resolve(db, "task_evidence:somehash") == set()
        assert _resolve(db, "task_output:somehash") == set()

    def test_12_claim_assumption_refs_unresolved(self, db):
        assert _resolve(db, "cl_abc123") == set()
        assert _resolve(db, "as_abc123") == set()

    def test_13_artifact_before_task_precedence(self, db):
        # A6: the same string present as BOTH an artifact row and a
        # task id resolves as the artifact (status-quo behavior) and
        # is NOT expanded through the task's inputs.
        _insert_artifact(db, "shared-id")
        _insert_artifact(db, "art-other", content_hash="H" * 64)
        _insert_task(db, "shared-id", spec={
            "source_refs": ["source_result:" + "H" * 64]})
        assert _resolve(db, "shared-id", "derived_from") == {"shared-id"}

    def test_14_repeated_resolution_deterministic(self, db):
        _insert_artifact(db, "art-s", content_hash="H" * 64)
        _fetch_task(db, source_hashes=["H" * 64])
        first = _resolve(db, "t-fetch", "cites")
        for _ in range(5):
            assert _resolve(db, "t-fetch", "cites") == first
        assert _resolve(db, "source_result:" + "H" * 64) == {"art-s"}


# ═══════════════════════ Integration: cone over mixed graphs ═══════════════════════


class TestMixedGraphCone:
    def test_15_mixed_bare_and_typed(self, db):
        # A3: bare and typed edges side by side.
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_artifact(db, "down-bare")
        _insert_artifact(db, "fc-1", artifact_type="failure_classification")
        _insert_edge(db, "down-bare", "src-a", "cites")
        _insert_edge(db, "fc-1", "source_result:" + "H" * 64, "cites")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == [
            "down-bare", "fc-1"]
        assert _invalidated(db) == {"down-bare", "fc-1"}

    def test_16_typed_downstream_chain(self, db):
        # Typed edge into the cone, then a bare edge onward: the walk
        # continues through resolved members.
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_artifact(db, "mid")
        _insert_artifact(db, "down")
        _insert_edge(db, "mid", "source_result:" + "H" * 64, "derived_from")
        _insert_edge(db, "down", "mid", "cites")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == [
            "down", "mid"]

    def test_17_task_input_cone(self, db):
        # A fetch payload derived from a task that consumed the source.
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _fetch_task(db, source_hashes=["H" * 64])
        _insert_artifact(db, "art-pay", artifact_type="source_payload",
                         content_hash="Q" * 64)
        _insert_edge(db, "art-pay", "t-fetch", "derived_from")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == [
            "art-pay"]

    def test_18_task_output_cone(self, db):
        # An artifact using a task's outputs as input, where the task
        # produced the retracted source.
        _record_decision(db)
        _insert_task(db, "t-prod")
        _insert_artifact(db, "src-a", task_id="t-prod")
        _insert_artifact(db, "art-use")
        _insert_edge(db, "art-use", "t-prod", "used_as_input")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == [
            "art-use"]

    def test_19_citation_task_cone_inputs_and_outputs(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _fetch_task(db, "t-fetch", source_hashes=["H" * 64])
        _insert_artifact(db, "art-pay", task_id="t-fetch")
        _insert_artifact(db, "cite-in")
        _insert_artifact(db, "cite-out")
        _insert_edge(db, "cite-in", "t-fetch", "cites")
        _insert_task(db, "t-other")
        _insert_artifact(db, "src-b")
        _insert_edge(db, "cite-out", "t-other", "cites")
        result = _retract(db)
        inv = set(result.row["invalidated_artifacts"])
        # cite-in cites t-fetch, which consumed src-a → downstream.
        # cite-out cites an unrelated task → untouched.
        assert "cite-in" in inv
        assert "cite-out" not in inv

    def test_20_sibling_production_excluded(self, db):
        # HIGH PRIORITY: task T produces BOTH the seed and a sibling;
        # an artifact derived from T must NOT be invalidated through a
        # task→outputs expansion for derived_from (only consumed inputs
        # count) — and the sibling itself stays valid.
        _record_decision(db)
        _insert_task(db, "t-prod")
        _insert_artifact(db, "src-a", task_id="t-prod")
        _insert_artifact(db, "sib", task_id="t-prod")
        _insert_artifact(db, "art-x")
        _insert_edge(db, "art-x", "t-prod", "derived_from")
        result = _retract(db)
        assert result.row["invalidated_artifacts"] == []
        assert _invalidated(db) == set()

    def test_21_cross_project_isolation(self, db):
        # P1 dependent (typed edge) invalidated; P2 artifacts untouched
        # even with task/reference metadata nearby.
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_artifact(db, "down-p1", artifact_type="evidence")
        _insert_edge(db, "down-p1", "source_result:" + "H" * 64, "cites")
        _insert_artifact(db, "src-b", project="p2")
        _insert_artifact(db, "down-p2", project="p2")
        _insert_edge(db, "down-p2", "src-b", "cites")
        _fetch_task(db, "t-p2", source_hashes=["H" * 64], project="p2")
        _insert_artifact(db, "pay-p2", project="p2")
        _insert_edge(db, "pay-p2", "t-p2", "derived_from")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == [
            "down-p1"]
        assert _invalidated(db) == {"down-p1"}

    def test_22_duplicate_aliases_single_invalidation(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_artifact(db, "down")
        _insert_edge(db, "down", "src-a", "cites")
        _insert_edge(db, "down", "source_result:" + "H" * 64, "cites")
        result = _retract(db)
        assert result.row["invalidated_artifacts"].count("down") == 1

    def test_23_cycle_terminates(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "node-b")
        _insert_edge(db, "node-b", "src-a", "cites")
        _insert_edge(db, "src-a", "node-b", "cites")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == [
            "node-b"]

    def test_24_unrelated_branch_untouched(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_artifact(db, "src-other", content_hash="O" * 64)
        _insert_artifact(db, "down-other")
        _insert_edge(db, "down-other", "source_result:" + "O" * 64, "cites")
        _fetch_task(db, "t-other", source_hashes=["O" * 64])
        _insert_artifact(db, "pay-other")
        _insert_edge(db, "pay-other", "t-other", "derived_from")
        result = _retract(db)
        assert result.row["invalidated_artifacts"] == []
        assert _invalidated(db) == set()


# ═══════════════════════ End-to-end via production ingestion ═══════════════════════


def _seed_curated_on_typed_dependent(db):
    """Curated entry whose basis is reachable ONLY through a typed edge.

    src-a (source) ←typed cites── fc-dep (evidence) is the falsifying
    basis; retracting src-a must invalidate the entry via the L2 cone.
    """
    from hermes.research.evidence_ladder import ladder_state_id
    from hermes.research.feature_binding import curation_command_hash
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES ('rp-1', 'p1', 1, 'ch-rp-1', NULL, 'b', 'o', 'c1', 'p1',
                   '1', 'ih', ?, '[]', '[]', '[]', '[]', '[]', NULL,
                   'director', NULL, ?)""",
        (json.dumps([{"ref": "h1", "ladder_target": "SUPPORTED",
                      "falsification_condition": "fc", "rival_of": None,
                      "rival_status": None}]), CLOCK))
    _insert_artifact(db, "src-a", content_hash="H" * 64)
    _insert_artifact(db, "fc-dep", artifact_type="evidence",
                     content_hash="D" * 64)
    _insert_edge(db, "fc-dep", "source_result:" + "H" * 64, "cites")
    meta = {
        "schema_version": "1", "failure_class": "DECLARED_CONSTRAINT_VIOLATION",
        "hypothesis_ref": "h1", "program_ref": "rp-1",
        "classification_id": "fc-1", "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": ["evidence:" + "D" * 64],
        "constraint_ref": "hypothesis:h1:falsification_condition",
        "failed_mechanism_ref": None, "regime_ref": None,
        "resource_gap": None, "scope_brief_ref": None,
        "scope_brief_field": None, "explanation": "l2 test",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": ["evidence:" + "D" * 64],
        "permitted_actions": [],
    }
    cls_hash = classification_content_hash(meta, "p1")
    _insert_artifact(db, "fc-1", artifact_type="failure_classification",
                     content_hash=cls_hash, meta=meta)
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
        from_state="SUPPORTED", to_state="REFUTED", caused_by="controller",
        reason="evidence ladder ratification transition: SUPPORTED -> REFUTED",
        payload={"program_id": "rp-1", "hypothesis_ref": "h1",
                 "from_rung": "SUPPORTED", "to_rung": "REFUTED",
                 "driver": "ratification", "ratified_by": "classification",
                 "classification_ref": "failure_classification:" + (
                     cls_hash or "")})
    binding = {"schema_version": 1, "project_ref": "p1",
               "program_ref": "rp-1", "hypothesis_ref": "h1",
               "instrument": "xauusd", "feature_family": "momentum",
               "claim_type": "directional"}
    bhash = binding_content_hash(binding)
    _insert_artifact(db, "art-fb1", artifact_type=FEATURE_BINDING_ARTIFACT_TYPE,
                     content_hash=bhash, meta=binding)
    payload = {"operation": "ADMIT", "kind": CURATED_KIND_REFUTED_PATTERN,
               "program_ref": "rp-1", "hypothesis_ref": "h1",
               "source_binding_ref": FEATURE_BINDING_REF_PREFIX + bhash,
               "source_decision_event_ref": "tr-1",
               "signature_json": signature_from_binding(binding),
               "supersedes_ref": ""}
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
        project_id="p1", justification="l2 seed",
        payload={**payload, "human_decision_ref": dref,
                 "operator_id": OP_ID})).entity_id


class TestEndToEnd:
    def test_25_typed_dependent_invalidated_via_ingestion(self, db):
        _insert_task(db, "t-prod")
        _insert_artifact(db, "src-a", task_id="t-prod",
                         content_hash="H" * 64)
        _insert_artifact(db, "fc-1", artifact_type="failure_classification")
        _insert_edge(db, "fc-1", "source_result:" + "H" * 64, "cites")
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False
        assert _invalidated(db) == {"fc-1"}

    def test_26_task_linked_dependent_invalidated_via_ingestion(self, db):
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _fetch_task(db, source_hashes=["H" * 64])
        _insert_artifact(db, "art-pay", artifact_type="source_payload",
                         content_hash="Q" * 64)
        _insert_edge(db, "art-pay", "t-fetch", "derived_from")
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="source_result:" + "H" * 64, reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False
        assert out["entity_id"] == "src-a"
        assert _invalidated(db) == {"art-pay"}

    def test_27_task_transitions_correct_with_typed_edges(self, db):
        _insert_task(db, "t-prod")
        _insert_artifact(db, "src-a", task_id="t-prod",
                         content_hash="H" * 64)
        _insert_task(db, "t-down")
        _insert_artifact(db, "fc-1", artifact_type="failure_classification",
                         task_id="t-down")
        _insert_edge(db, "fc-1", "source_result:" + "H" * 64, "cites")
        ctrl = _make(db)
        ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        # t-down produced the invalidated dependent → transitions;
        # t-prod produced only the (superseded, not cone-invalidated)
        # source → stays SUCCEEDED (pre-existing S5 transition rule:
        # transitions are driven by invalidated downstream artifacts).
        assert db.execute(
            "SELECT status FROM tasks WHERE task_id = 't-prod'"
        ).fetchone()["status"] == "SUCCEEDED"
        assert db.execute(
            "SELECT status FROM tasks WHERE task_id = 't-down'"
        ).fetchone()["status"] == "INVALIDATED"
        assert db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.TASK_INVALIDATED.value,)).fetchone()["c"] == 1

    def test_28_curated_invalidated_via_typed_cone(self, db):
        curated_id = _seed_curated_on_typed_dependent(db)
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False
        # fc-dep reached the cone ONLY through the typed cites edge.
        assert "fc-dep" in _invalidated(db)
        row = db.execute(
            "SELECT status FROM curated_knowledge_entries "
            "WHERE curated_id = ?", (curated_id,)).fetchone()
        assert row["status"] == "INVALIDATED"
        inv = db.execute(
            "SELECT payload_json FROM events WHERE event_type = ?",
            ("CuratedKnowledgeInvalidated",)).fetchone()
        assert inv is not None
        assert json.loads(inv["payload_json"])["curated_id"] == curated_id

    def test_29_replay_deterministic(self, db):
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_artifact(db, "fc-1", artifact_type="failure_classification")
        _insert_edge(db, "fc-1", "source_result:" + "H" * 64, "cites")
        ctrl = _make(db)
        kw = {"source_ref": "src-a", "reason": REASON,
              "operator_id": OP_ID, "operator_token": OP_TOKEN}
        first = ctrl.record_source_retraction_decision(**kw)
        assert first["duplicate"] is False
        second = ctrl.record_source_retraction_decision(**kw)
        third = ctrl.record_source_retraction_decision(**kw)
        assert second["duplicate"] is True
        assert third["duplicate"] is True
        assert len(db.execute(
            "SELECT * FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchall()) == 1
        assert _invalidated(db) == {"fc-1"}

    def test_30_idempotency_stale_unchanged(self, db):
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        ctrl = _make(db)
        first = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert first["rejected"] is False
        second = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason="a different cited reason",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert second["rejected"] is True
        assert second["code"] == STALE


# ═══════════════════════ Compatibility: historical graphs ═══════════════════════


class TestCompatibility:
    def test_31_historical_bare(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down")
        _insert_edge(db, "down", "src-a", "derived_from")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == ["down"]

    def test_32_historical_typed(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_artifact(db, "fc-1", artifact_type="failure_classification")
        _insert_edge(db, "fc-1", "source_result:" + "H" * 64, "cites")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == ["fc-1"]

    def test_33_historical_task_reference(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _fetch_task(db, source_hashes=["H" * 64])
        _insert_artifact(db, "art-pay")
        _insert_edge(db, "art-pay", "t-fetch", "derived_from")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == [
            "art-pay"]

    def test_34_mixed_historical_current(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_artifact(db, "down-bare")
        _insert_artifact(db, "fc-typed", artifact_type="evidence")
        _fetch_task(db, source_hashes=["H" * 64])
        _insert_artifact(db, "pay-task")
        _insert_edge(db, "down-bare", "src-a", "cites")
        _insert_edge(db, "fc-typed", "source_result:" + "H" * 64, "cites")
        _insert_edge(db, "pay-task", "t-fetch", "derived_from")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == [
            "down-bare", "fc-typed", "pay-task"]


# ═══════════════════════ Adversarial A1–A12 ═══════════════════════


class TestAdversarialA1A12:
    def _seed(self, db):
        _insert_artifact(db, "src-a", content_hash="H" * 64)

    def test_a1_bare_edge(self, db):
        self._seed(db)
        _insert_artifact(db, "d1")
        _insert_edge(db, "d1", "src-a", "cites")
        assert _resolve(db, "src-a") == {"src-a"}

    def test_a2_prefixed_task_edge_forms(self, db):
        self._seed(db)
        _fetch_task(db, source_hashes=["H" * 64])
        assert _resolve(db, "source_result:" + "H" * 64) == {"src-a"}
        assert _resolve(db, "t-fetch", "derived_from") == {"src-a"}

    def test_a3_mixed_graph(self, db):
        self._seed(db)
        _record_decision(db)
        _insert_artifact(db, "d-bare")
        _insert_artifact(db, "d-typed", artifact_type="evidence")
        _fetch_task(db, source_hashes=["H" * 64])
        _insert_artifact(db, "d-task")
        _insert_edge(db, "d-bare", "src-a", "cites")
        _insert_edge(db, "d-typed", "source_result:" + "H" * 64, "cites")
        _insert_edge(db, "d-task", "t-fetch", "derived_from")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == [
            "d-bare", "d-task", "d-typed"]

    def test_a4_historical_graph(self, db):
        # Rows written directly in stored forms (as historical writers
        # left them) resolve without any rewrite.
        self._seed(db)
        _insert_artifact(db, "fc-old", artifact_type="failure_classification")
        _insert_edge(db, "fc-old", "source_result:" + "H" * 64, "cites")
        assert _resolve(db, "source_result:" + "H" * 64) == {"src-a"}

    def test_a5_replay_identical(self, db):
        self._seed(db)
        _record_decision(db)
        _insert_artifact(db, "d1", artifact_type="evidence")
        _insert_edge(db, "d1", "source_result:" + "H" * 64, "cites")
        first = _retract(db)
        second = _retract(db)
        assert second.duplicate is True
        assert _invalidated(db) == {"d1"}
        assert first.row["invalidated_artifacts"] == ["d1"]

    def test_a6_ambiguous_alias_precedence(self, db):
        # Same string as artifact row AND task id: artifact wins, no
        # task expansion (Rule 1 precedence).
        _insert_artifact(db, "dup")
        _insert_artifact(db, "art-s", content_hash="H" * 64)
        _insert_task(db, "dup", spec={
            "source_refs": ["source_result:" + "H" * 64]})
        assert _resolve(db, "dup", "derived_from") == {"dup"}

    def test_a7_cross_project_collision(self, db):
        # Global PKs make true collisions impossible; a P2 row never
        # enters a P1 cone even when P2 edges reference P1 content.
        self._seed(db)
        _record_decision(db)
        _insert_artifact(db, "mine", artifact_type="evidence")
        _insert_edge(db, "mine", "source_result:" + "H" * 64, "cites")
        _insert_artifact(db, "theirs", artifact_type="evidence", project="p2")
        _insert_edge(db, "theirs", "source_result:" + "H" * 64, "cites")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == ["mine"]
        assert _invalidated(db) == {"mine"}

    def test_a8_missing_target(self, db):
        assert _resolve(db, "source_result:" + "0" * 64) == set()
        assert _resolve(db, "t-missing", "cites") == set()

    def test_a9_malformed_storm(self, db):
        # A storm of malformed upstreams cannot fail the retraction or
        # pollute the cone; the valid dependent still invalidates.
        self._seed(db)
        _record_decision(db)
        _insert_artifact(db, "d1", artifact_type="evidence")
        _insert_edge(db, "d1", "source_result:" + "H" * 64, "cites")
        for idx, bad in enumerate(["", ":", "source_result:", ":::",
                                 "unknownprefix:" + "H" * 64,
                                 "task_evidence:zzz",
                                 "cl_notanartifact", "t-ghost-task"]):
            _insert_artifact(db, f"junk-{idx}")
            _insert_edge(db, f"junk-{idx}", bad, "cites")
            assert _resolve(db, bad) == set()
        result = _retract(db)
        # The valid dependent invalidates through the storm; the seed
        # itself is superseded (never a cone member).
        assert result.row["invalidated_artifacts"] == ["d1"]

    def test_a10_duplicate_aliases(self, db):
        self._seed(db)
        _record_decision(db)
        _insert_artifact(db, "d1")
        _insert_edge(db, "d1", "src-a", "cites")
        _insert_edge(db, "d1", "source_result:" + "H" * 64, "cites")
        _fetch_task(db, source_hashes=["H" * 64])
        _insert_edge(db, "d1", "t-fetch", "derived_from")
        result = _retract(db)
        assert result.row["invalidated_artifacts"].count("d1") == 1

    def test_a11_cycle_terminates(self, db):
        self._seed(db)
        _record_decision(db)
        _insert_artifact(db, "b")
        _insert_artifact(db, "c")
        _insert_edge(db, "b", "src-a", "cites")
        _insert_edge(db, "c", "b", "cites")
        _insert_edge(db, "b", "c", "cites")
        _insert_edge(db, "src-a", "c", "cites")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == ["b", "c"]

    def test_a12_large_cone(self, db):
        # 200 downstream members across both forms: all invalidate,
        # deterministically ordered. (Sized to respect the pre-existing
        # 4 KiB S6 event-payload cap on the SourceRetracted event —
        # cones large enough to exceed it are a separate, form-
        # independent scalability question, reported out of scope.)
        self._seed(db)
        _record_decision(db)
        for i in range(100):
            _insert_artifact(db, f"bare-{i}")
            _insert_edge(db, f"bare-{i}", "src-a", "cites")
            _insert_artifact(db, f"typed-{i}", artifact_type="evidence")
            _insert_edge(db, f"typed-{i}", "source_result:" + "H" * 64,
                         "cites")
        result = _retract(db)
        assert len(result.row["invalidated_artifacts"]) == 200
        assert result.row["invalidated_artifacts"] == sorted(
            result.row["invalidated_artifacts"])


# ═══════════ S-3 extraction pins (DG-3B §19) ═══════════


_L2_SYMBOLS = (
    "_l2_lookup_artifact_by_hash",
    "_l2_resolve_ref_to_artifacts",
    "_l2_task_spec_refs",
    "_l2_task_outputs",
    "_l2_resolve_upstream",
)


class _RecordingCursor:
    """Cursor proxy delegated to by :class:`_RecordingConn`."""

    def __init__(self, cursor, statements):
        self._cursor = cursor
        self._statements = statements

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class _RecordingConn:
    """Connection proxy that records every executed statement.

    ``_l2_resolve_upstream`` receives a connection-like object; the proxy
    delegates to the real connection but captures the SQL text, so the
    resolver's statement class (read vs write vs transaction control)
    becomes directly observable rather than merely asserted by inspection.
    """

    def __init__(self, conn):
        self._conn = conn
        self.statements: list[str] = []

    def execute(self, sql, params=()):
        self.statements.append(sql)
        return _RecordingCursor(self._conn.execute(sql, params),
                                self.statements)


def test_pin1_module_boundary_single_implementation():
    """DG-3B §19 pin 1 — ownership and no duplicate implementation.

    Pre-move: the family is gateway-owned and defined exactly once there.
    Post-move: all five functions are defined by ``l2_resolution``; the
    gateway's single call site uses that imported implementation (object
    identity, not a re-export), and no second ``_l2_`` definition remains
    in the gateway source.
    """
    from hermes.research import gateway as gw

    if importlib.util.find_spec("hermes.research.l2_resolution") is None:
        src = Path(gw.__file__).read_text(encoding="utf-8")
        for name in _L2_SYMBOLS:
            assert src.count(f"def {name}") == 1
        return

    from hermes.research import l2_resolution as l2

    for name in _L2_SYMBOLS:
        assert callable(getattr(l2, name))
    assert gw._l2_resolve_upstream is l2._l2_resolve_upstream
    src = Path(gw.__file__).read_text(encoding="utf-8")
    for name in _L2_SYMBOLS:
        assert f"def {name}" not in src


def test_pin2_resolver_reads_only_opens_no_transaction(db):
    """DG-3B §19 pin 2 — the resolver is read-only, transaction-free.

    Every statement the resolver issues — across all four rule carriers
    (bare identity hit, typed ``<type>:<hash>``, ``evidence:`` form, and
    the task hop) — is a ``SELECT``. No ``INSERT``/``UPDATE``/``DELETE``
    and no ``BEGIN``/``COMMIT``/``ROLLBACK`` is ever issued.
    """
    _insert_artifact(db, "hit", content_hash="ch-hit")
    _insert_artifact(db, "typed", artifact_type="source_result",
                     content_hash="H" * 64)
    _fetch_task(db, "t-spec", source_hashes=["H" * 64])
    _insert_task(db, "t-prod")
    _insert_artifact(db, "produced", artifact_type="evidence",
                     task_id="t-prod")

    spy = _RecordingConn(db)
    _l2_resolve_upstream(spy, "hit", "cites", {})
    _l2_resolve_upstream(spy, "source_result:" + "H" * 64, "cites", {})
    _l2_resolve_upstream(spy, "evidence:hit", "cites", {})
    _l2_resolve_upstream(spy, "t-spec", "derived_from", {})
    _l2_resolve_upstream(spy, "t-prod", "used_as_input", {})
    _l2_resolve_upstream(spy, "t-prod", "cites", {})

    assert spy.statements, "resolver issued no statement at all"
    write_verbs = ("INSERT", "UPDATE", "DELETE", "BEGIN", "COMMIT",
                   "ROLLBACK")
    for sql in spy.statements:
        normalized = " ".join(sql.upper().split())
        assert normalized.startswith("SELECT"), sql
        for verb in write_verbs:
            assert verb not in normalized, (verb, sql)


def test_pin3_global_by_key_caller_side_isolation(db):
    """DG-3B §19 pin 3 — scope-by-design; do not "fix" this.

    L2 resolution is global-by-key: the resolver takes only a connection
    and a stored reference, so a foreign-project artifact is resolvable by
    key. Project isolation is supplied by the caller's project-scoped
    emission JOIN (``_validate_retract_source``), which therefore never
    emits a foreign-project dependent row.
    """
    _insert_artifact(db, "p2-art", artifact_type="evidence", project="p2")
    assert _resolve(db, "p2-art") == {"p2-art"}
    assert _resolve(db, "p2-art", "used_as_input") == {"p2-art"}

    _insert_artifact(db, "src-a", content_hash="H" * 64)
    _record_decision(db)
    _insert_artifact(db, "mine", artifact_type="evidence")
    _insert_edge(db, "mine", "src-a", "cites")
    _insert_artifact(db, "theirs", artifact_type="evidence", project="p2")
    _insert_edge(db, "theirs", "src-a", "cites")

    result = _retract(db)
    assert sorted(result.row["invalidated_artifacts"]) == ["mine"]
