"""S5 implementation tests (v6 §7/S5, Step 5 charter) — RETRACT_SOURCE.

Covers the Step-5 charter §11 test matrix:

A. Gateway enforcement   (internal-only role gate; no direct-write path)
B. Basic retraction      (event + decision artifact + persisted state)
C. Cone invalidation     (direct / chain / branch / empty cone / untouched)
D. Idempotence           (identical repeat = duplicate, zero effects)
E. Boundary conditions   (nonexistent source, non-source type, missing
                         human decision, already-retracted STALE,
                         non-SUCCEEDED tasks untouched)
F. Event integrity       (type, payload, ordering, causality)
G. Failure atomicity     (a mid-cascade failure leaves NOTHING written)
H. Repeated application  (repeat after success is consistent)

The cascade boundary (charter §7/§8/§9) is also pinned: NO §16.6 screen,
NO §21 projection, NO S7 semantics are implemented or invoked.
"""
from __future__ import annotations

import json

import pytest

from hermes.core import frozen_clock
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.gateway import (
    EVIDENCE_REF,
    MALFORMED_PAYLOAD,
    PROPOSAL,
    ROLE,
    STALE,
    GatewayRejection,
    apply_intent,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    yield conn
    conn.close()


def _insert_artifact(db, artifact_id, *, artifact_type="source_result",
                     content_hash=None, project_id="p1", task_id=None,
                     metadata=None):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type, content_hash,
            size_bytes, storage_path, producer, metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, 1, 'x', 'test', ?, ?)""",
        (artifact_id, project_id, task_id, artifact_type,
         content_hash or f"ch-{artifact_id}",
         json.dumps(metadata) if metadata else None, CLOCK))


def _insert_edge(db, artifact_id, upstream_id, edge_type):
    db.execute(
        """INSERT INTO provenance_edges
           (artifact_id, upstream_id, edge_type, created_at)
           VALUES (?, ?, ?, ?)""",
        (artifact_id, upstream_id, edge_type, CLOCK))


def _meta_of(db, artifact_id):
    """Artifact metadata as a dict — NULL/absent metadata is {}."""
    row = db.execute(
        "SELECT metadata_json FROM artifacts WHERE artifact_id = ?",
        (artifact_id,)).fetchone()
    raw = row["metadata_json"] if row else None
    return json.loads(raw) if raw else {}


_SUCCEEDED_TASKS: list[str] = []


def _insert_task(db, task_id, status="SUCCEEDED", deps=()):
    from hermes.core.node import NodeContract
    from hermes.persistence.repositories import TaskRepository
    repo = TaskRepository(db, frozen_clock(CLOCK))
    node = NodeContract(
        task_id=task_id, project_id="p1", task_type="TOOL_TASK",
        idempotency_key=f"idem-{task_id}", dependencies=list(deps))
    row = repo.create(node)
    if status != "PENDING":
        db.execute("UPDATE tasks SET status = ? WHERE task_id = ?",
                   (status, task_id))
    return row


def _record_human_decision(db, ref="hd-1"):
    """Record a ratified HumanDecision event (the v6 §7/S5 authority)."""
    from hermes.persistence.repositories import _append_event_to_db
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id="p1", correlation_id=ref, caused_by="operator",
        reason="operator decision", payload={"decision": "RETRACT"})


def _retract(db, source_ref="src-a", decision_ref="hd-1",
             reason="source retracted by publisher", proposed_by="DETERMINISTIC"):
    return apply_intent(db, Intent(
        kind=IntentKind.RETRACT_SOURCE, proposed_by=proposed_by,
        project_id="p1",
        justification="S5 cascade",
        payload={"source_ref": source_ref, "reason": reason,
                 "human_decision_ref": decision_ref}))


# ════════════════════════ A. Gateway enforcement ════════════════════════

class TestGatewayEnforcement:
    def test_retract_source_is_internal_only(self):
        assert IntentKind.RETRACT_SOURCE in IntentKind.internal_only()
        assert IntentKind.RETRACT_SOURCE not in IntentKind.llm_proposable()
        intent = Intent(kind=IntentKind.RETRACT_SOURCE,
                        proposed_by="DETERMINISTIC", project_id="p1")
        assert not intent.is_llm_proposable()
        assert intent.is_internal_only()

    def test_agent_roles_rejected(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        for role in ("DIRECTOR", "RESEARCHER", "IMPLEMENTER", "ADVERSARY"):
            with pytest.raises(GatewayRejection) as exc:
                apply_intent(db, Intent(
                    kind=IntentKind.RETRACT_SOURCE, proposed_by=role,
                    project_id="p1",
                    payload={"source_ref": "src-a", "reason": "r",
                             "human_decision_ref": "hd-1"}))
            assert exc.value.code == ROLE

    def test_deterministic_accepted(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        result = _retract(db)
        assert result.duplicate is False
        assert result.entity_id == "src-a"

    def test_unknown_payload_key_rejected(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
                project_id="p1",
                payload={"source_ref": "src-a", "reason": "r",
                         "human_decision_ref": "hd-1", "extra": 1}))
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_empty_reason_rejected(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
                project_id="p1",
                payload={"source_ref": "src-a", "reason": "  ",
                         "human_decision_ref": "hd-1"}))
        assert exc.value.code == MALFORMED_PAYLOAD


# ════════════════════════ B. Basic retraction ════════════════════════

class TestBasicRetraction:
    def test_source_retracted_event_emitted(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _retract(db)
        rows = db.execute(
            "SELECT * FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchall()
        assert len(rows) == 1
        assert rows[0]["project_id"] == "p1"
        assert rows[0]["caused_by"] == "DETERMINISTIC"
        payload = json.loads(rows[0]["payload_json"])
        assert payload["source_artifact_id"] == "src-a"

    def test_decision_artifact_with_supersedes_edge(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        result = _retract(db)
        rd = result.row["decision_artifact_id"]
        row = db.execute(
            "SELECT artifact_type FROM artifacts WHERE artifact_id = ?",
            (rd,)).fetchone()
        assert row["artifact_type"] == "ResearchDecision"
        edge = db.execute(
            "SELECT edge_type FROM provenance_edges "
            "WHERE artifact_id = ? AND upstream_id = 'src-a'",
            (rd,)).fetchone()
        assert edge["edge_type"] == "supersedes"

    def test_persisted_state_matches_result(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1")
        _insert_edge(db, "down-1", "src-a", "derived_from")
        result = _retract(db)
        meta = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = 'down-1'"
        ).fetchone()["metadata_json"])
        assert meta["invalidation_marker"] == "INVALIDATED"
        assert meta["invalidated_by"] == result.row["decision_artifact_id"]
        # nothing deleted (§16.1): every artifact still present
        count = db.execute("SELECT COUNT(*) c FROM artifacts").fetchone()["c"]
        assert count == 3  # src-a + down-1 + the new ResearchDecision

    def test_hash_ref_form_resolves(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-h", content_hash="abc123")
        result = _retract(db, source_ref="source_result:abc123")
        assert result.entity_id == "src-h"


# ════════════════════════ C. Cone invalidation ════════════════════════

class TestConeInvalidation:
    def test_direct_dependent_invalidated(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1")
        _insert_edge(db, "down-1", "src-a", "cites")
        _retract(db)
        meta = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts "
            "WHERE artifact_id = 'down-1'").fetchone()["metadata_json"])
        assert meta["invalidation_marker"] == "INVALIDATED"

    def test_multi_level_chain(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        chain = [("b", "src-a"), ("c", "b"), ("d", "c")]
        for aid, upstream in chain:
            _insert_artifact(db, aid)
            _insert_edge(db, aid, upstream, "derived_from")
        _retract(db)
        invalidated = []
        for aid in ("b", "c", "d"):
            if _meta_of(db, aid).get("invalidation_marker") == "INVALIDATED":
                invalidated.append(aid)
        assert invalidated == ["b", "c", "d"]

    def test_branching_graph_multiple_branches(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "left")
        _insert_artifact(db, "right")
        _insert_artifact(db, "join")
        _insert_edge(db, "left", "src-a", "cites")
        _insert_edge(db, "right", "src-a", "used_as_input")
        _insert_edge(db, "join", "left", "derived_from")
        _insert_edge(db, "join", "right", "cites")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == \
            ["join", "left", "right"]

    def test_shared_dependency_no_duplicate_invalidation(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "shared")
        _insert_edge(db, "shared", "src-a", "cites")
        # repeated descendant exposure: two paths reach 'shared'
        _insert_artifact(db, "mid")
        _insert_edge(db, "mid", "src-a", "derived_from")
        _insert_edge(db, "shared", "mid", "cites")
        result = _retract(db)
        assert result.row["invalidated_artifacts"].count("shared") == 1

    def test_empty_cone(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        result = _retract(db)
        assert result.row["invalidated_artifacts"] == []
        assert result.row["invalidated_tasks"] == []

    def test_unrelated_nodes_untouched(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "unrelated")
        _retract(db)
        row = db.execute(
            "SELECT metadata_json FROM artifacts "
            "WHERE artifact_id = 'unrelated'").fetchone()
        meta = json.loads(row["metadata_json"]) if (
            row and row["metadata_json"]) else {}
        assert meta.get("invalidation_marker") != "INVALIDATED"

    def test_non_dependency_edge_never_propagates(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "contra")
        # `justifies` and `supersedes` are NOT dependency-class edges
        _insert_edge(db, "contra", "src-a", "justifies")
        result = _retract(db)
        assert result.row["invalidated_artifacts"] == []

    def test_succeeded_task_of_invalidated_artifact_transitions(self, db):
        _record_human_decision(db)
        _insert_task(db, "t-producer")           # PENDING -> SUCCEEDED below
        db.execute("UPDATE tasks SET status = 'SUCCEEDED' "
                   "WHERE task_id = 't-producer'")
        _insert_artifact(db, "src-a", task_id="t-producer")
        _insert_artifact(db, "down-1", task_id="t-producer")
        _insert_edge(db, "down-1", "src-a", "cites")
        result = _retract(db)
        assert result.row["invalidated_tasks"] == ["t-producer"]
        status = db.execute(
            "SELECT status FROM tasks WHERE task_id = 't-producer'"
        ).fetchone()["status"]
        assert status == "INVALIDATED"
        ev = db.execute(
            "SELECT * FROM events WHERE event_type = ? AND task_id = ?",
            (EventType.TASK_INVALIDATED.value, "t-producer")).fetchone()
        assert ev is not None
        assert ev["from_state"] == "SUCCEEDED"
        assert ev["to_state"] == "INVALIDATED"


# ════════════════════════ D. Idempotence ════════════════════════

class TestIdempotence:
    @staticmethod
    def _cascade_counts(db):
        src = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchone()["c"]
        task_inv = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.TASK_INVALIDATED.value,)).fetchone()["c"]
        artifacts = db.execute(
            "SELECT COUNT(*) c FROM artifacts").fetchone()["c"]
        return src, task_inv, artifacts

    def test_identical_repeat_is_duplicate_with_zero_effects(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1")
        _insert_edge(db, "down-1", "src-a", "cites")
        first = _retract(db)
        cascade_before = self._cascade_counts(db)
        second = _retract(db)
        assert second.duplicate is True
        assert second.entity_id == first.entity_id
        # Zero CASCADE effects: no duplicate SourceRetracted, no duplicate
        # TaskInvalidated, no duplicate decision artifact. (The gateway's
        # uniform IntentApplied audit record is emitted for every admission
        # by design — the EVIDENCE_TRANSITION precedent — and is not an S5
        # semantic effect.)
        assert self._cascade_counts(db) == cascade_before
        meta = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts "
            "WHERE artifact_id = 'down-1'").fetchone()["metadata_json"])
        assert meta["invalidation_marker"] == "INVALIDATED"  # stable state

    def test_repeat_preserves_single_source_retracted_event(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _retract(db)
        _retract(db)
        rows = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchall()
        assert rows[0]["c"] == 1


# ════════════════════════ E. Boundary conditions ════════════════════════

class TestBoundaries:
    def test_missing_human_decision_fail_closed(self, db):
        _insert_artifact(db, "src-a")
        with pytest.raises(GatewayRejection) as exc:
            _retract(db, decision_ref="hd-nonexistent")
        assert exc.value.code == PROPOSAL
        # nothing written
        n = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchone()["c"]
        assert n == 0

    def test_nonexistent_source_rejected(self, db):
        _record_human_decision(db)
        with pytest.raises(GatewayRejection) as exc:
            _retract(db, source_ref="nope")
        assert exc.value.code == EVIDENCE_REF

    def test_cross_project_source_rejected(self, db):
        ProjectRepository(db, frozen_clock(CLOCK)).create("p2", "Other")
        _record_human_decision(db)
        _insert_artifact(db, "foreign-src", project_id="p2")
        with pytest.raises(GatewayRejection) as exc:
            _retract(db, source_ref="foreign-src")
        assert exc.value.code == EVIDENCE_REF

    def test_non_source_artifact_type_rejected(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "claim-1", artifact_type="research_claim")
        with pytest.raises(GatewayRejection) as exc:
            _retract(db, source_ref="claim-1")
        assert exc.value.code == EVIDENCE_REF

    def test_bad_hash_prefix_rejected(self, db):
        # The human-decision dereference runs FIRST (fail-closed ordering):
        # with a recorded decision in place the malformed source ref is
        # what trips the rejection.
        _record_human_decision(db)
        with pytest.raises(GatewayRejection) as exc:
            _retract(db, source_ref="not_a_type:abc")
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_missing_decision_beats_source_resolution(self, db):
        # No recorded decision: the PROPOSAL rejection fires before any
        # source resolution — nothing about the source is leaked.
        with pytest.raises(GatewayRejection) as exc:
            _retract(db, source_ref="not_a_type:abc",
                     decision_ref="hd-missing")
        assert exc.value.code == PROPOSAL

    def test_second_different_retraction_is_stale(self, db):
        _record_human_decision(db, "hd-1")
        _record_human_decision(db, "hd-2")
        _insert_artifact(db, "src-a")
        _retract(db, decision_ref="hd-1")
        with pytest.raises(GatewayRejection) as exc:
            _retract(db, decision_ref="hd-2", reason="different reason")
        assert exc.value.code == STALE

    def test_non_succeeded_task_not_transitioned(self, db):
        _record_human_decision(db)
        _insert_task(db, "t-run", status="RUNNING")
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1", task_id="t-run")
        _insert_edge(db, "down-1", "src-a", "cites")
        result = _retract(db)
        assert result.row["invalidated_tasks"] == []  # artifact IS marked...
        meta = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts "
            "WHERE artifact_id = 'down-1'").fetchone()["metadata_json"])
        assert meta["invalidation_marker"] == "INVALIDATED"
        # ...but the RUNNING task keeps its lifecycle state
        status = db.execute(
            "SELECT status FROM tasks WHERE task_id = 't-run'"
        ).fetchone()["status"]
        assert status == "RUNNING"


# ════════════════════════ F. Event integrity ════════════════════════

class TestEventIntegrity:
    def test_event_ordering_and_causality(self, db):
        _record_human_decision(db)
        _insert_task(db, "t1")
        db.execute("UPDATE tasks SET status = 'SUCCEEDED' "
                   "WHERE task_id = 't1'")
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1", task_id="t1")
        _insert_edge(db, "down-1", "src-a", "cites")
        _retract(db)
        rows = db.execute(
            "SELECT rowid, event_type, correlation_id, caused_by "
            "FROM events WHERE event_type IN (?, ?) ORDER BY rowid",
            (EventType.TASK_INVALIDATED.value,
             EventType.SOURCE_RETRACTED.value)).fetchall()
        # TaskInvalidated lands BEFORE the terminal SourceRetracted record;
        # all carry the same deterministic correlation key.
        types = [r["event_type"] for r in rows]
        assert types[-1] == EventType.SOURCE_RETRACTED.value
        corr = {r["correlation_id"] for r in rows}
        assert len(corr) == 1  # one deterministic retraction id
        assert rows[0]["caused_by"] == "DETERMINISTIC"

    def test_deterministic_correlation_key(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _retract(db)
        row = db.execute(
            "SELECT correlation_id FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchone()
        assert row["correlation_id"].startswith("retract_")

    def test_payload_carries_cascade_record(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1")
        _insert_edge(db, "down-1", "src-a", "derived_from")
        _retract(db)
        payload = json.loads(db.execute(
            "SELECT payload_json FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchone()["payload_json"])
        assert payload["source_artifact_id"] == "src-a"
        assert payload["human_decision_ref"] == "hd-1"
        assert payload["decision_artifact_id"].startswith("rd-retract_")
        # S6 bounded fact + integrity commitment (no unbounded lists).
        assert set(payload) == {
            "source_ref", "source_artifact_id", "decision_artifact_id",
            "human_decision_ref", "cone_algorithm", "cone_digest",
            "artifact_count", "task_count", "curated_count"}
        assert payload["cone_algorithm"] == "s5-cone-v1"
        assert payload["artifact_count"] == 1
        assert payload["task_count"] == 0
        assert payload["curated_count"] == 0
        import hashlib
        expected = hashlib.sha256(json.dumps(
            {"artifacts": ["down-1"], "tasks": [], "curated": []},
            sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8")).hexdigest()
        assert payload["cone_digest"] == expected


# ════════════════════════ G. Failure atomicity ════════════════════════

class TestFailureAtomicity:
    def test_mid_cascade_failure_writes_nothing(self, db):
        _record_human_decision(db)
        _insert_task(db, "t1")
        db.execute("UPDATE tasks SET status = 'SUCCEEDED' "
                   "WHERE task_id = 't1'")
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1", task_id="t1")
        _insert_edge(db, "down-1", "src-a", "cites")

        # Sabotage the LAST write of the transaction (the SourceRetracted
        # event) so COMMIT never runs. Patch at the GATEWAY module (the
        # validator's import binding), not the repositories module.
        from unittest import mock

        import hermes.research.gateway as gw
        from hermes.persistence.event_validation import EventValidationError
        real_append = gw._append_event_to_db

        def sabotaged(conn, clock, event_type, *a, **kw):
            if event_type == EventType.SOURCE_RETRACTED.value:
                raise EventValidationError("sabotaged", "payload")
            return real_append(conn, clock, event_type, *a, **kw)

        with mock.patch.object(gw, "_append_event_to_db", sabotaged), \
                pytest.raises(EventValidationError):
            _retract(db)

        # NOTHING persisted: no event, no decision artifact, no edge,
        # no metadata marker, no task transition.
        n_ev = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type IN (?, ?)",
            (EventType.SOURCE_RETRACTED.value,
             EventType.TASK_INVALIDATED.value)).fetchone()["c"]
        assert n_ev == 0
        n_rd = db.execute(
            "SELECT COUNT(*) c FROM artifacts "
            "WHERE artifact_type = 'ResearchDecision'").fetchone()["c"]
        assert n_rd == 0
        meta = db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id='down-1'"
        ).fetchone()["metadata_json"]
        assert not meta or json.loads(meta).get(
            "invalidation_marker") != "INVALIDATED"
        status = db.execute(
            "SELECT status FROM tasks WHERE task_id = 't1'"
        ).fetchone()["status"]
        assert status == "SUCCEEDED"


# ════════════════════════ H. Repeated application ════════════════════════

class TestRepeatedApplication:
    def test_apply_apply_same_state(self, db):
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1")
        _insert_edge(db, "down-1", "src-a", "cites")
        _retract(db)
        snapshot1 = db.execute(
            "SELECT artifact_id, metadata_json FROM artifacts "
            "ORDER BY artifact_id").fetchall()
        with pytest.raises(GatewayRejection) as exc:
            _retract(db, reason="second try")   # different command -> STALE
        assert exc.value.code == STALE
        snapshot2 = db.execute(
            "SELECT artifact_id, metadata_json FROM artifacts "
            "ORDER BY artifact_id").fetchall()
        assert [tuple(r) for r in snapshot1] == \
            [tuple(r) for r in snapshot2]


# ═════════════════ Cascade boundary pins (§7/§8/§9) ═════════════════

class TestCascadeBoundary:
    def test_no_s16_or_v21_surfaces_touched(self, db):
        """Steps 4-5 (§16.6 screen, §21 projection) remain deferred: the
        cascade writes ONLY its own rows — no vault/rendering/registry
        tables exist or are touched."""
        _record_human_decision(db)
        _insert_artifact(db, "src-a")
        _retract(db)
        tables = {r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for forbidden in ("vault_projection", "refuted_registry",
                          "inadmissible_sources", "knowledge_amendments"):
            assert forbidden not in tables

    def test_s5_cone_untouched_by_feature_binding(self, db):
        """Step 7 has landed (the curated follow-on is a CHARTERED addition
        inside the S5 transaction), but the S5 cone CORE stays untouched:
        the dependency-edge vocabulary carries no feature_binding type, and
        the cone walk still seeds only from the retracted source artifact.
        The curated predicate CONSUMES the cone exactly as produced — it
        never extends it, and the known L2 identifier-form defect is not
        repaired here."""
        from hermes.research.gateway import _S5_DEPENDENCY_EDGE_TYPES
        assert _S5_DEPENDENCY_EDGE_TYPES == (
            "cites", "derived_from", "used_as_input")
        assert "feature_binding" not in _S5_DEPENDENCY_EDGE_TYPES


# ═══════ S-4 pins (DG-3C C-1): the extracted cone closure is pure ═══════

class TestS4ConeClosurePins:
    def test_c_dg3c_1_pure_closure_semantics(self):
        """The extracted closure keeps the certified S5 membership semantics:
        empty adjacency, direct child, multi-level chain, diamond de-dup,
        cycle termination with the seed excluded, dangling references,
        unreachable components, sorted output, repeat determinism."""
        from hermes.research.gateway import _s5_cone_closure

        assert _s5_cone_closure("seed", {}) == []
        assert _s5_cone_closure("seed", {"seed": ["c1"]}) == ["c1"]
        assert _s5_cone_closure(
            "seed", {"seed": ["b"], "b": ["c"], "c": ["d"]}
        ) == ["b", "c", "d"]
        # Diamond: the shared leaf is emitted once (sorted, l < leaf).
        assert _s5_cone_closure(
            "seed", {"seed": ["l", "r"], "l": ["leaf"], "r": ["leaf"]}
        ) == ["l", "leaf", "r"]
        # A cycle back to the seed terminates and never emits the seed.
        assert _s5_cone_closure(
            "seed", {"seed": ["a"], "a": ["seed"]}
        ) == ["a"]
        # A reference to a node with no adjacency entry is emitted as a
        # leaf — never a KeyError (fail-safe, pre-existing posture).
        assert _s5_cone_closure(
            "seed", {"seed": ["ghost", "real"]}
        ) == ["ghost", "real"]
        # A component unreachable from the seed never appears.
        assert _s5_cone_closure(
            "seed", {"seed": ["a"], "orphan": ["b"]}
        ) == ["a"]
        # Output order is canonical (sorted) regardless of adjacency order.
        assert _s5_cone_closure("seed", {"seed": ["z", "a", "m"]}) == [
            "a", "m", "z"]
        chain = {"seed": ["a"], "a": ["b"], "b": ["seed"]}
        first = _s5_cone_closure("seed", chain)
        assert first == ["a", "b"]
        for _ in range(5):
            assert _s5_cone_closure("seed", chain) == first

    def test_c_dg3c_2_structural_purity(self):
        """The helper is structurally incapable of I/O, refusal, time, hash,
        event, or transaction work: no connection parameter, no mutation of
        the caller's adjacency map, and no such identifier anywhere in its
        AST (node-level, so the contract docstring is never mistaken for
        code)."""
        import ast
        import inspect

        from hermes.research import gateway as gw

        helper = gw._s5_cone_closure
        params = list(inspect.signature(helper).parameters)
        assert params == ["source_artifact_id", "downstream"]
        assert not any("conn" in p.lower() for p in params)

        adj = {"seed": ["a"], "a": ["b"]}
        snapshot = {k: list(v) for k, v in adj.items()}
        assert helper("seed", adj) == ["a", "b"]
        assert adj == snapshot  # the input mapping is never mutated
        assert helper("seed", adj) == helper("seed", adj)

        fn = ast.parse(inspect.getsource(helper)).body[0]
        assert isinstance(fn, ast.FunctionDef)
        assert not any(
            isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(fn))
        banned = {
            "conn", "execute", "_reject", "clock", "hashlib", "EventType",
            "_append_event_to_db", "GatewayRejection", "sha256", "uuid",
            "source_artifact_retracted", "_cx_classification_facts",
            "_l2_resolve_upstream",
        }
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        assert not (names & banned)
        assert not (attrs & banned)
        literals = {n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert literals == {ast.get_docstring(fn, clean=False)}

    def test_c_dg3c_3_call_site_equivalence(self, db):
        """End-to-end: the retraction's ``invalidated_artifacts`` equals the
        closure of the adjacency map the cascade itself builds — over all
        three dependency edge types, through a typed reference, a task hop,
        a branch and a diamond (duplicate) path."""
        from hermes.research.gateway import (
            _S5_DEPENDENCY_EDGE_TYPES,
            _l2_resolve_upstream,
            _s5_cone_closure,
        )

        _record_human_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_task(db, "t-fetch")
        db.execute("UPDATE tasks SET spec_json = ? WHERE task_id = ?",
                   (json.dumps({
                       "source_refs": ["source_result:" + "H" * 64]}),
                    "t-fetch"))
        for artifact_id in ("d1", "d2", "d3", "d-typed", "d-task"):
            _insert_artifact(db, artifact_id, artifact_type="evidence")
        _insert_edge(db, "d1", "src-a", "cites")
        _insert_edge(db, "d2", "src-a", "cites")
        _insert_edge(db, "d3", "d1", "cites")
        _insert_edge(db, "d3", "d2", "cites")
        _insert_edge(db, "d-typed", "source_result:" + "H" * 64, "cites")
        _insert_edge(db, "d-task", "t-fetch", "derived_from")

        rows = db.execute(
            "SELECT e.upstream_id, e.artifact_id, e.edge_type "
            "FROM provenance_edges e "
            "JOIN artifacts a ON a.artifact_id = e.artifact_id "
            "WHERE a.project_id = ? AND e.edge_type IN (?,?,?)",
            ("p1", *_S5_DEPENDENCY_EDGE_TYPES)).fetchall()
        downstream: dict[str, list[str]] = {}
        memo: dict = {}
        for r in rows:
            for canonical in sorted(_l2_resolve_upstream(
                    db, r["upstream_id"], r["edge_type"], memo)):
                downstream.setdefault(canonical, []).append(
                    r["artifact_id"])
        expected = _s5_cone_closure("src-a", downstream)

        result = _retract(db)
        assert result.duplicate is False
        assert expected == ["d-task", "d-typed", "d1", "d2", "d3"]
        assert result.row["invalidated_artifacts"] == expected
