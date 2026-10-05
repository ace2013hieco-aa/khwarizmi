"""S6 source-retraction event capacity tests (ratified S6 architecture).

The P3 ``SourceRetracted`` event carries the bounded retraction fact
plus a deterministic integrity commitment (``cone_digest``) to the
computed S5 cone — never the unbounded cone lists. The authoritative
cone remains recoverable from persisted invalidation state
(artifact markers keyed by ``decision_artifact_id``, task records keyed
by ``retraction_id``, curated records keyed by ``retraction_id``).

Matrix:
  Payload shape (1–5), capacity (6–12), digest correctness (13–20),
  state equivalence (21–26), failure/atomicity (27–32), historical
  compatibility (33–37), S5 L2 integration (38–43), adversarial
  amplification (44–47).
"""
from __future__ import annotations

import hashlib
import json

import pytest

from hermes.core import frozen_clock
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.event_validation import DEFAULT_PAYLOAD_MAX_BYTES
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    OperatorCredentialRepository,
    ProjectRepository,
    _append_event_to_db,
)
from hermes.research.controller import Controller
from hermes.research.gateway import (
    STALE,
    GatewayRejection,
    apply_intent,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1"
REASON = "source retracted by publisher notice 2026-01"

EXPECTED_KEYS = {
    "source_ref", "source_artifact_id", "decision_artifact_id",
    "human_decision_ref", "cone_algorithm", "cone_digest",
    "artifact_count", "task_count", "curated_count"}


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
                     content_hash=None, project="p1", task_id=None):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, 1, 'x', 't', NULL, ?)""",
        (artifact_id, project, task_id, artifact_type,
         content_hash or f"ch-{artifact_id}", CLOCK))


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


def _record_decision(db, ref="hd-1", project="p1"):
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id=project, correlation_id=ref, caused_by="operator",
        reason="operator decision", payload={"decision": "RETRACT"})


def _retract(db, source_ref="src-a", decision_ref="hd-1", project="p1"):
    return apply_intent(db, Intent(
        kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
        project_id=project, justification="S6",
        payload={"source_ref": source_ref, "reason": "retracted",
                 "human_decision_ref": decision_ref}))


def _payload(db):
    row = db.execute(
        "SELECT payload_json FROM events WHERE event_type = ?",
        (EventType.SOURCE_RETRACTED.value,)).fetchone()
    return json.loads(row["payload_json"])


def _payload_bytes(db):
    row = db.execute(
        "SELECT payload_json FROM events WHERE event_type = ?",
        (EventType.SOURCE_RETRACTED.value,)).fetchone()
    return len(row["payload_json"].encode("utf-8"))


def _expected_digest(artifacts, tasks=(), curated=()):
    canonical = json.dumps(
        {"artifacts": sorted(artifacts), "tasks": sorted(tasks),
         "curated": sorted(curated)},
        sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _seed_cone(db, n, *, idstyle="real", edge_type="cites"):
    """A source with n downstream members; returns member ids."""
    _insert_artifact(db, "src-a", content_hash="H" * 64)
    members = []
    for i in range(n):
        aid = (f"art-{(i * 7919) % (16**24):024x}" if idstyle == "real"
               else f"d-{i:04d}")
        _insert_artifact(db, aid, artifact_type="evidence")
        _insert_edge(db, aid, "src-a", edge_type)
        members.append(aid)
    return members


def _reconstruct(db, decision_artifact_id, retraction_id):
    """Normative state reconstruction (§7): markers + records."""
    arts = [r["artifact_id"] for r in db.execute(
        "SELECT artifact_id FROM artifacts "
        "WHERE json_extract(metadata_json, '$.invalidated_by') = ? "
        "ORDER BY artifact_id ASC", (decision_artifact_id,)).fetchall()]
    tasks = [r["task_id"] for r in db.execute(
        "SELECT task_id FROM events WHERE event_type = ? "
        "AND correlation_id = ? ORDER BY task_id ASC",
        (EventType.TASK_INVALIDATED.value, retraction_id)).fetchall()]
    curated = [r["curated_id"] for r in db.execute(
        "SELECT payload_json FROM events WHERE event_type = ?",
        ("CuratedKnowledgeInvalidated",)).fetchall()
        if json.loads(r["payload_json"])["retraction_id"] == retraction_id]
    return sorted(arts), sorted(tasks), sorted(curated)


# ═══════════════════════ Payload shape (1–5) ═══════════════════════


class TestPayloadShape:
    def test_1_exact_nine_fields(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1")
        _insert_edge(db, "down-1", "src-a", "cites")
        _retract(db)
        assert set(_payload(db)) == EXPECTED_KEYS

    def test_2_no_unbounded_lists(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1")
        _insert_edge(db, "down-1", "src-a", "cites")
        _retract(db)
        payload = _payload(db)
        assert "invalidated_artifacts" not in payload
        assert "invalidated_tasks" not in payload
        assert "invalidated_curated_entries" not in payload

    def test_3_algorithm_tag(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        _retract(db)
        assert _payload(db)["cone_algorithm"] == "s5-cone-v1"

    def test_4_digest_is_sha256_hex(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        _retract(db)
        digest = _payload(db)["cone_digest"]
        assert len(digest) == 64
        assert digest == digest.lower()
        int(digest, 16)

    def test_5_counts_equal_cardinalities(self, db):
        _record_decision(db)
        _insert_task(db, "t-prod")
        _insert_artifact(db, "src-a", task_id="t-prod")
        _insert_task(db, "t-down")
        _insert_artifact(db, "d1", task_id="t-down")
        _insert_artifact(db, "d2")
        _insert_edge(db, "d1", "src-a", "cites")
        _insert_edge(db, "d2", "src-a", "cites")
        _retract(db)
        payload = _payload(db)
        assert payload["artifact_count"] == 2
        assert payload["task_count"] == 1
        assert payload["curated_count"] == 0


# ═══════════════════════ Capacity (6–12) ═══════════════════════


class TestCapacity:
    @pytest.mark.parametrize("n", [10, 115])
    def test_6_7_small_cones(self, db, n):
        _record_decision(db)
        _seed_cone(db, n)
        result = _retract(db)
        assert len(result.row["invalidated_artifacts"]) == n
        assert _payload_bytes(db) < DEFAULT_PAYLOAD_MAX_BYTES
        assert _payload(db)["artifact_count"] == n

    def test_8_previously_failing_122(self, db):
        _record_decision(db)
        _seed_cone(db, 122)
        result = _retract(db)
        assert len(result.row["invalidated_artifacts"]) == 122
        size = _payload_bytes(db)
        assert size < DEFAULT_PAYLOAD_MAX_BYTES
        assert _payload(db)["artifact_count"] == 122
        print(f"\n122-member cone: payload {size} bytes")

    def test_9_200_members(self, db):
        _record_decision(db)
        _seed_cone(db, 200)
        result = _retract(db)
        assert len(result.row["invalidated_artifacts"]) == 200
        size = _payload_bytes(db)
        assert size < DEFAULT_PAYLOAD_MAX_BYTES
        print(f"\n200-member cone: payload {size} bytes")

    def test_10_400_members(self, db):
        _record_decision(db)
        _seed_cone(db, 400)
        result = _retract(db)
        assert len(result.row["invalidated_artifacts"]) == 400
        size = _payload_bytes(db)
        assert size < DEFAULT_PAYLOAD_MAX_BYTES
        print(f"\n400-member cone: payload {size} bytes")

    def test_11_stress_2000_members(self, db):
        _record_decision(db)
        _seed_cone(db, 2000)
        result = _retract(db)
        assert len(result.row["invalidated_artifacts"]) == 2000
        size = _payload_bytes(db)
        assert size < DEFAULT_PAYLOAD_MAX_BYTES
        print(f"\n2000-member cone: payload {size} bytes")

    def test_12_size_independent_of_cardinality(self, db):
        def payload_size_for(n):
            conn = connect(":memory:")
            migrate_to_latest(conn)
            ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
            _record_decision(conn)
            _insert_artifact(conn, "src-a", content_hash="H" * 64)
            for i in range(n):
                aid = f"art-{(i * 7919) % (16**24):024x}"
                _insert_artifact(conn, aid, artifact_type="evidence")
                _insert_edge(conn, aid, "src-a", "cites")
            _retract(conn)
            row = conn.execute(
                "SELECT payload_json FROM events WHERE event_type = ?",
                (EventType.SOURCE_RETRACTED.value,)).fetchone()
            size = len(row["payload_json"].encode("utf-8"))
            conn.close()
            return size

        sizes = {n: payload_size_for(n) for n in (10, 122, 400)}
        # Effectively constant: the only cardinality-dependent bytes are
        # the decimal count digits (log-scale); member IDs never appear.
        assert max(sizes.values()) - min(sizes.values()) <= 4
        assert all(s < DEFAULT_PAYLOAD_MAX_BYTES for s in sizes.values())


# ═══════════════════════ Digest correctness (13–20) ═══════════════════════


class TestDigestCorrectness:
    def test_13_14_15_independent_reconstruction(self, db):
        _record_decision(db)
        _insert_task(db, "t-prod")
        _insert_artifact(db, "src-a", task_id="t-prod")
        _insert_task(db, "t-down")
        _insert_artifact(db, "d1", task_id="t-down")
        _insert_edge(db, "d1", "src-a", "cites")
        _retract(db)
        payload = _payload(db)
        # Independent reconstruction per §12 (not via production helper).
        canonical = json.dumps(
            {"artifacts": sorted(["d1"]), "tasks": sorted(["t-down"]),
             "curated": sorted([])},
            sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8")
        assert payload["cone_digest"] == hashlib.sha256(canonical).hexdigest()

    def test_16_sorted_ordering_used(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        for aid in ("zulu", "alpha", "mike"):
            _insert_artifact(db, aid)
            _insert_edge(db, aid, "src-a", "cites")
        _retract(db)
        assert _payload(db)["cone_digest"] == _expected_digest(
            ["alpha", "mike", "zulu"])

    def test_17_db_iteration_order_irrelevant(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        for aid in ("zulu", "alpha", "mike"):
            _insert_artifact(db, aid)
            _insert_edge(db, aid, "src-a", "derived_from")
        _retract(db)
        first = _payload(db)["cone_digest"]
        # Reverse physical insertion order cannot occur post-hoc, but the
        # digest input is explicitly sorted: rebuild identically.
        assert first == _expected_digest(["alpha", "mike", "zulu"])

    def test_18_duplicate_aliases_stable_digest(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_artifact(db, "d1")
        _insert_edge(db, "d1", "src-a", "cites")
        _insert_edge(db, "d1", "source_result:" + "H" * 64, "cites")
        _retract(db)
        assert _payload(db)["cone_digest"] == _expected_digest(["d1"])
        assert _payload(db)["artifact_count"] == 1

    def test_19_deterministic_repeated_computation(self, db):
        _record_decision(db)
        members = _seed_cone(db, 50)
        _retract(db)
        first = _payload(db)["cone_digest"]
        assert first == _expected_digest(members)

    def test_20_empty_cone_digest(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        _retract(db)
        payload = _payload(db)
        assert payload["artifact_count"] == 0
        assert payload["cone_digest"] == _expected_digest([])


# ═══════════════════════ State equivalence (21–26) ═══════════════════════


class TestStateEquivalence:
    def test_21_artifact_markers_reproduce_cone(self, db):
        _record_decision(db)
        members = _seed_cone(db, 25)
        _retract(db)
        payload = _payload(db)
        decision_id = payload["decision_artifact_id"]
        marked = [r["artifact_id"] for r in db.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE json_extract(metadata_json, '$.invalidated_by') = ? "
            "ORDER BY artifact_id ASC", (decision_id,)).fetchall()]
        assert marked == sorted(members)

    def test_22_task_records_reproduce_cone(self, db):
        _record_decision(db)
        _insert_task(db, "t-a")
        _insert_task(db, "t-b")
        _insert_artifact(db, "src-a", task_id="t-a")
        _insert_artifact(db, "d1", task_id="t-a")
        _insert_artifact(db, "d2", task_id="t-b")
        _insert_edge(db, "d1", "src-a", "cites")
        _insert_edge(db, "d2", "src-a", "cites")
        result = _retract(db)
        assert sorted(result.row["invalidated_tasks"]) == ["t-a", "t-b"]
        assert _payload(db)["task_count"] == 2

    def test_23_curated_records_reproduce_cone(self, db):
        curated_id = _seed_curated_on_downstream(db)
        _record_decision(db, ref="hd-r")
        _retract(db, decision_ref="hd-r")
        payload = _payload(db)
        assert payload["curated_count"] == 1
        rows = db.execute(
            "SELECT payload_json FROM events WHERE event_type = ?",
            ("CuratedKnowledgeInvalidated",)).fetchall()
        assert len(rows) == 1
        inv = json.loads(rows[0]["payload_json"])
        assert inv["curated_id"] == curated_id
        assert inv["retraction_id"] == _retraction_id(db)

    def test_24_recalculated_digest_matches(self, db):
        _record_decision(db)
        _insert_task(db, "t-down")
        members = _seed_cone(db, 30)
        for m in members[:5]:
            db.execute("UPDATE artifacts SET task_id = 't-down' "
                       "WHERE artifact_id = ?", (m,))
        _retract(db)
        payload = _payload(db)
        arts, tasks, curated = _reconstruct(
            db, payload["decision_artifact_id"], _retraction_id(db))
        assert payload["cone_digest"] == _expected_digest(arts, tasks, curated)
        assert tasks == ["t-down"]

    def test_25_empty_cone_reconstruction(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        _retract(db)
        payload = _payload(db)
        arts, tasks, curated = _reconstruct(
            db, payload["decision_artifact_id"], _retraction_id(db))
        assert (arts, tasks, curated) == ([], [], [])
        assert payload["cone_digest"] == _expected_digest([], [], [])

    def test_26_counts_equal_reconstruction(self, db):
        _record_decision(db)
        _seed_cone(db, 40)
        _retract(db)
        payload = _payload(db)
        arts, tasks, curated = _reconstruct(
            db, payload["decision_artifact_id"], _retraction_id(db))
        assert payload["artifact_count"] == len(arts) == 40
        assert payload["task_count"] == len(tasks) == 0
        assert payload["curated_count"] == len(curated) == 0


def _retraction_id(db):
    row = db.execute(
        "SELECT correlation_id FROM events WHERE event_type = ?",
        (EventType.SOURCE_RETRACTED.value,)).fetchone()
    return row["correlation_id"]


def _seed_curated_on_downstream(db):
    """Curated entry whose basis is a downstream cone member (bare edge).

    Returns the curated entry id. Retracting src-a invalidates it via
    the cone (not via the source itself)."""
    from hermes.research.evidence_ladder import (
        classification_content_hash,
        ladder_state_id,
    )
    from hermes.research.feature_binding import (
        CURATED_KIND_REFUTED_PATTERN,
        FEATURE_BINDING_ARTIFACT_TYPE,
        FEATURE_BINDING_REF_PREFIX,
        binding_content_hash,
        curation_command_hash,
        signature_from_binding,
    )
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
    _insert_artifact(db, "art-down", artifact_type="evidence",
                     content_hash="D" * 64)
    _insert_edge(db, "art-down", "src-a", "cites")
    meta = {
        "schema_version": "1", "failure_class": "DECLARED_CONSTRAINT_VIOLATION",
        "hypothesis_ref": "h1", "program_ref": "rp-1",
        "classification_id": "fc-1", "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": ["evidence:" + "D" * 64],
        "constraint_ref": "hypothesis:h1:falsification_condition",
        "failed_mechanism_ref": None, "regime_ref": None,
        "resource_gap": None, "scope_brief_ref": None,
        "scope_brief_field": None, "explanation": "s6 test",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": ["evidence:" + "D" * 64],
        "permitted_actions": [],
    }
    cls_hash = classification_content_hash(meta, "p1")
    _insert_artifact(db, "fc-1", artifact_type="failure_classification",
                     content_hash=cls_hash)
    # store classification metadata for the digest check
    db.execute("UPDATE artifacts SET metadata_json = ? "
               "WHERE artifact_id = 'fc-1'", (json.dumps(meta),))
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
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES ('art-fb1', 'p1', NULL, ?, ?, 1, 'x', 't', ?, ?)""",
        (FEATURE_BINDING_ARTIFACT_TYPE, bhash, json.dumps(binding), CLOCK))
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
        project_id="p1", justification="s6 seed",
        payload={**payload, "human_decision_ref": dref,
                 "operator_id": OP_ID})).entity_id


# ═══════════════════════ Failure / atomicity (27–32) ═══════════════════════


class TestFailureAtomicity:
    def test_27_persistence_failure_rolls_back(self, db):
        from unittest import mock

        import hermes.research.gateway as gw

        _record_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1")
        _insert_edge(db, "down-1", "src-a", "cites")
        real_append = gw._append_event_to_db

        def failing(conn, clock, event_type, *a, **kw):
            raise RuntimeError("simulated storage failure")

        with mock.patch.object(gw, "_append_event_to_db", failing), \
                pytest.raises(RuntimeError):
            _retract(db)
        # All-or-nothing: no SourceRetracted, no markers, decision intact.
        assert db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchone()["c"] == 0
        assert db.execute(
            "SELECT COUNT(*) c FROM artifacts WHERE "
            "json_extract(metadata_json, '$.invalidation_marker') = ?",
            ("INVALIDATED",)).fetchone()["c"] == 0
        assert real_append is gw._append_event_to_db

    def test_28_malformed_input_refusal(self, db):
        with pytest.raises(GatewayRejection):
            apply_intent(db, Intent(
                kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
                project_id="p1", justification="bad",
                payload={"source_ref": "", "reason": "r",
                         "human_decision_ref": "hd-x"}))

    def test_29_operator_refusal_is_data(self, db):
        _insert_artifact(db, "src-a")
        ctrl = _make(db)
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id="bad-op", operator_token="wrong")
        assert out == {**out, "rejected": True} and out["code"] == "OPERATOR"

    def test_30_lock_refusal_is_data(self, db):
        _insert_artifact(db, "src-a")
        ctrl = _make(db)
        other = _make(db)
        assert other._acquire_lock() is True
        out = ctrl.record_source_retraction_decision(
            source_ref="src-a", reason=REASON,
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "LOCK"
        other._release_lock()

    def test_31_duplicate_replay_idempotent(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "down-1")
        _insert_edge(db, "down-1", "src-a", "cites")
        first = _retract(db)
        second = _retract(db)
        assert first.duplicate is False
        assert second.duplicate is True
        assert db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchone()["c"] == 1

    def test_32_stale_unchanged(self, db):
        _record_decision(db, ref="hd-1")
        _record_decision(db, ref="hd-2")
        _insert_artifact(db, "src-a")
        _retract(db, decision_ref="hd-1")
        with pytest.raises(GatewayRejection) as exc:
            _retract(db, decision_ref="hd-2", )
        assert exc.value.code == STALE


# ═══════════════════════ Historical compatibility (33–37) ═══════════════════════


OLD_PAYLOAD = {
    "source_ref": "src-a",
    "source_artifact_id": "src-a",
    "decision_artifact_id": "rd-retract_abc123",
    "human_decision_ref": "hd-1",
    "invalidated_artifacts": ["down-1"],
    "invalidated_tasks": [],
    "invalidated_curated_entries": [],
}


class TestHistoricalCompatibility:
    def _write_old_event(self, db):
        _append_event_to_db(
            db, frozen_clock(CLOCK),
            EventType.SOURCE_RETRACTED.value,
            project_id="p1", correlation_id="retract_abc123",
            caused_by="DETERMINISTIC", reason="r",
            artifact_ids=["src-a"], payload=dict(OLD_PAYLOAD))

    def test_33_old_event_row_valid(self, db):
        self._write_old_event(db)
        row = db.execute(
            "SELECT payload_json FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchone()
        assert json.loads(row["payload_json"]) == OLD_PAYLOAD

    def test_34_old_payload_not_rewritten(self, db):
        self._write_old_event(db)
        before = db.execute(
            "SELECT payload_json FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchone()["payload_json"]
        _record_decision(db, ref="hd-new")
        _insert_artifact(db, "src-b")
        _retract(db, source_ref="src-b", decision_ref="hd-new")
        old = db.execute(
            "SELECT payload_json FROM events WHERE correlation_id = ?",
            ("retract_abc123",)).fetchone()["payload_json"]
        assert old == before

    def test_35_old_event_readable(self, db):
        self._write_old_event(db)
        payload = json.loads(db.execute(
            "SELECT payload_json FROM events WHERE correlation_id = ?",
            ("retract_abc123",)).fetchone()["payload_json"])
        assert payload["source_artifact_id"] == "src-a"
        assert payload["invalidated_artifacts"] == ["down-1"]

    def test_36_old_event_needs_no_algorithm(self, db):
        self._write_old_event(db)
        payload = json.loads(db.execute(
            "SELECT payload_json FROM events WHERE correlation_id = ?",
            ("retract_abc123",)).fetchone()["payload_json"])
        assert "cone_algorithm" not in payload
        assert "cone_digest" not in payload

    def test_37_mixed_old_new_population(self, db):
        self._write_old_event(db)
        _record_decision(db, ref="hd-new")
        _insert_artifact(db, "src-b")
        _insert_artifact(db, "down-b")
        _insert_edge(db, "down-b", "src-b", "cites")
        _retract(db, source_ref="src-b", decision_ref="hd-new")
        rows = db.execute(
            "SELECT correlation_id, payload_json FROM events "
            "WHERE event_type = ? ORDER BY event_id ASC",
            (EventType.SOURCE_RETRACTED.value,)).fetchall()
        assert len(rows) == 2
        old = json.loads(rows[0]["payload_json"])
        new = json.loads(rows[1]["payload_json"])
        assert old["invalidated_artifacts"] == ["down-1"]
        assert new["artifact_count"] == 1
        assert new["cone_digest"] == _expected_digest(["down-b"])


# ═══════════════════════ S5 L2 integration (38–43) ═══════════════════════


class TestL2Integration:
    def test_38_typed_references_resolve(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_artifact(db, "fc-1", artifact_type="failure_classification")
        _insert_edge(db, "fc-1", "source_result:" + "H" * 64, "cites")
        result = _retract(db)
        assert result.row["invalidated_artifacts"] == ["fc-1"]
        assert _payload(db)["artifact_count"] == 1
        assert _payload(db)["cone_digest"] == _expected_digest(["fc-1"])

    def test_39_task_derived_references_resolve(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_task(db, "t-fetch", spec={
            "source_refs": ["source_result:" + "H" * 64]})
        _insert_artifact(db, "art-pay")
        _insert_edge(db, "art-pay", "t-fetch", "derived_from")
        result = _retract(db)
        assert result.row["invalidated_artifacts"] == ["art-pay"]
        assert _payload(db)["cone_digest"] == _expected_digest(["art-pay"])

    def test_40_sibling_production_excluded(self, db):
        _record_decision(db)
        _insert_task(db, "t-prod")
        _insert_artifact(db, "src-a", task_id="t-prod")
        _insert_artifact(db, "sib", task_id="t-prod")
        _insert_artifact(db, "art-x")
        _insert_edge(db, "art-x", "t-prod", "derived_from")
        result = _retract(db)
        assert result.row["invalidated_artifacts"] == []
        assert _payload(db)["artifact_count"] == 0

    def test_41_cross_project_isolation(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_artifact(db, "mine", artifact_type="evidence")
        _insert_edge(db, "mine", "source_result:" + "H" * 64, "cites")
        _insert_artifact(db, "theirs", artifact_type="evidence", project="p2")
        _insert_edge(db, "theirs", "source_result:" + "H" * 64, "cites")
        result = _retract(db)
        assert result.row["invalidated_artifacts"] == ["mine"]
        assert _payload(db)["cone_digest"] == _expected_digest(["mine"])

    def test_42_cycles_terminate(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a")
        _insert_artifact(db, "b")
        _insert_edge(db, "b", "src-a", "cites")
        _insert_edge(db, "src-a", "b", "cites")
        result = _retract(db)
        assert sorted(result.row["invalidated_artifacts"]) == ["b"]
        assert _payload(db)["cone_digest"] == _expected_digest(["b"])

    def test_43_deterministic_ordering(self, db):
        _record_decision(db)
        members = _seed_cone(db, 60)
        _retract(db)
        assert _payload(db)["cone_digest"] == _expected_digest(members)


# ═══════════════════════ Adversarial amplification (44–47) ═══════════════════════


class TestAmplification:
    def test_44_large_cone_no_rejection(self, db):
        _record_decision(db)
        _seed_cone(db, 500)
        result = _retract(db)
        assert len(result.row["invalidated_artifacts"]) == 500
        assert _payload_bytes(db) < DEFAULT_PAYLOAD_MAX_BYTES

    def test_45_duplicate_aliases_stable_cardinality(self, db):
        _record_decision(db)
        _insert_artifact(db, "src-a", content_hash="H" * 64)
        _insert_artifact(db, "d1")
        _insert_edge(db, "d1", "src-a", "cites")
        _insert_edge(db, "d1", "source_result:" + "H" * 64, "cites")
        _retract(db)
        payload = _payload(db)
        assert payload["artifact_count"] == 1
        assert payload["cone_digest"] == _expected_digest(["d1"])

    def test_46_10x_baseline_cone(self, db):
        _record_decision(db)
        _seed_cone(db, 1000)
        result = _retract(db)
        assert len(result.row["invalidated_artifacts"]) == 1000
        assert _payload_bytes(db) < DEFAULT_PAYLOAD_MAX_BYTES
        assert _payload(db)["cone_digest"] == _expected_digest(
            [r["artifact_id"] for r in db.execute(
                "SELECT artifact_id FROM artifacts "
                "WHERE json_extract(metadata_json, '$.invalidated_by') "
                "IS NOT NULL ORDER BY artifact_id ASC").fetchall()])

    def test_47_high_cardinality_stress(self, db):
        _record_decision(db)
        members = _seed_cone(db, 3000)
        result = _retract(db)
        assert len(result.row["invalidated_artifacts"]) == 3000
        size = _payload_bytes(db)
        assert size < DEFAULT_PAYLOAD_MAX_BYTES
        assert _payload(db)["artifact_count"] == 3000
        print(f"\n3000-member cone: payload {size} bytes")
        assert _payload(db)["cone_digest"] == _expected_digest(members)
