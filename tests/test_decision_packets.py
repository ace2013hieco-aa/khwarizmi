"""DECISION-PACKETS — acceptance tests (read-only packets + queue ordering).

Pins four contracts:

1. **Deterministic assembly.** ``collect_pending_verdicts`` /
   ``assemble_packet`` / ``build_decision_queue`` are pure over the project's
   rows: identical rows yield identical canonical bytes, and a packet's
   ``content_hash`` is recomputed from its body (never trusted). One packet is
   byte-pinned to a golden SHA-256.

2. **Deterministic ordering.** ``order_pending_verdicts`` orders by a total key
   with completion-blocking contradictions first; the result is independent of
   input order.

3. **HARD RULE — no auto-ratification.** Running the module's entire public
   surface over a project with pending verdicts leaves the journal and every
   mutable row byte-identical, and the existing ratification surface still
   refuses without a ratified credential + verdict. A packet alone never
   ratifies.

4. **Purity guard.** The module's own source carries no gateway/write call.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hermes.core import frozen_clock
from hermes.persistence.database import connect
from hermes.persistence.failure_classifications import (
    FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research import decision_packets as dp
from hermes.research.contradictions import contradiction_id_of
from hermes.research.controller import Controller

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1"
PROGRAM_ID = "rp-1"

# The byte-pin: the SHA-256 of the canonical body of the blocking-contradiction
# packet for the fixed scenario below. Any change to packet assembly that
# alters its bytes fails here.
GOLDEN_PACKET_SHA256 = (
    "16e9f6f784eb5f7236b1fdf40515eb3216b36d2ddf3352914d64233853e8f725"
)


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, clock=frozen_clock(CLOCK)).create("p1", "Test")
    from hermes.persistence.repositories import OperatorCredentialRepository
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    yield conn
    conn.close()


# ── fixture builders ──


def _program(db, *, gates=("hypothesis",)):
    """A minimal head research_programs row (no evidence obligations)."""
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, 'p1', 1, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', ?,
                   '[]', '[]', '[]', ?, '[]', NULL, 'director', NULL, ?)""",
        (PROGRAM_ID, "ch-" + PROGRAM_ID,
         json.dumps([{"ref": "h1", "ladder_target": "SUPPORTED",
                      "falsification_condition": "fc", "rival_of": None,
                      "rival_status": None}]),
         json.dumps(list(gates)), CLOCK),
    )


def _artifact(db, aid, artifact_type, metadata=None):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, 'p1', NULL, ?, ?, 7, 'inline://t', 'test', ?, ?)""",
        (aid, artifact_type, "ch-" + aid,
         json.dumps(metadata) if metadata is not None else None, CLOCK),
    )
    return "ch-" + aid


def _classification(db, aid, failure_class, program_ref):
    return _artifact(
        db, aid, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
        {"failure_class": failure_class, "program_ref": program_ref,
         "hypothesis_ref": "h1", "classifier_version": "1.0",
         "classification_id": aid},
    )


def _contradiction(db, party_a, party_b, overlap):
    cid = contradiction_id_of(party_a, party_b)
    db.execute(
        """INSERT INTO contradictions
           (contradiction_id, project_id, type, party_a, party_b,
            evidence_overlap_json, status, detector_version, detected_at,
            detection_event_ref, created_at)
           VALUES (?, 'p1', 'CLASSIFICATION_CONFLICT', ?, ?, ?, 'OPEN',
                   'cx-detect-v1', ?, ?, ?)""",
        (cid, party_a, party_b, json.dumps(list(overlap)), CLOCK,
         "evt-" + cid, CLOCK),
    )
    return cid


def _human_gate(db, task_id, requirement):
    db.execute(
        """INSERT INTO tasks
           (task_id, project_id, task_type, idempotency_key, status,
            spec_json, created_at)
           VALUES (?, 'p1', 'HUMAN_GATE', ?, 'WAITING_HUMAN', ?, ?)""",
        (task_id, "idem-" + task_id,
         json.dumps({"gate_requirement": requirement}), CLOCK),
    )
    return task_id


def _proposal(db, proposal_id, content_hash, action, failure_class):
    db.execute(
        """INSERT INTO events
           (event_type, project_id, correlation_id, caused_by,
            payload_json, created_at)
           VALUES ('ClassificationActionProposed', 'p1', ?, 'DIRECTOR', ?, ?)""",
        (proposal_id,
         json.dumps({
             "classification_ref":
                 "failure_classification:" + content_hash,
             "action": action,
             "candidate_artifact_ref": "ev-shared",
             "rationale": "review downstream",
             "state": "PENDING_HUMAN_APPROVAL"}),
         CLOCK),
    )
    return proposal_id


def _scenario(db):
    """A project with one of every pending verdict, blocking + non-blocking."""
    _program(db, gates=("hypothesis",))
    # A completion-BLOCKING contradiction (parties name the head program).
    _artifact(db, "ev-shared", "evidence")
    a = _classification(db, "fc-a", "IMPLEMENTATION_FAILURE", PROGRAM_ID)
    b = _classification(db, "fc-b", "ENVIRONMENT_MISMATCH", PROGRAM_ID)
    blocking = _contradiction(db, "fc-a", "fc-b", ["ev-shared"])
    # A non-blocking contradiction (both parties live and foreign).
    _classification(db, "fc-c", "IMPLEMENTATION_FAILURE", "rp-other")
    _classification(db, "fc-d", "RESOURCE_CONSTRAINT", "rp-other")
    idle = _contradiction(db, "fc-c", "fc-d", [])
    # One mandatory gate (denies COMPLETED) and one non-mandatory gate.
    gate_mandatory = _human_gate(db, "gate-hypothesis", "hypothesis")
    gate_extra = _human_gate(db, "gate-prelive", "pre_live")
    # the mandatory gate's upstream work: a terminal dep + its artifact
    db.execute(
        """INSERT INTO tasks
           (task_id, project_id, task_type, idempotency_key, status,
            spec_json, created_at)
           VALUES ('task-upstream', 'p1', 'AGENT_TASK',
                   'idem-task-upstream', 'SUCCEEDED', '{}', ?)""",
        (CLOCK,))
    db.execute(
        """INSERT INTO task_dependencies (task_id, depends_on_task_id,
           created_at) VALUES ('gate-hypothesis', 'task-upstream', ?)""",
        (CLOCK,))
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES ('art-up', 'p1', 'task-upstream', 'evidence',
                   'ch-art-up', 3, 'inline://t', 'test', NULL, ?)""",
        (CLOCK,))
    # An advisory, human-confirmation-shaped proposal.
    prop_hash = _classification(db, "fc-prop", "FRAMING_ERROR", PROGRAM_ID)
    proposal = _proposal(db, "prop-1", prop_hash, "REVIEW_DOWNSTREAM_IMPACT",
                         "FRAMING_ERROR")
    return {"blocking": blocking, "idle": idle, "gate_mandatory": gate_mandatory,
            "gate_extra": gate_extra, "proposal": proposal, "a": a, "b": b}


def _by_subject(pendings):
    return {p.subject_ref: p for p in pendings}


# ── 1. deterministic assembly ──


def test_collects_every_pending_verdict(db):
    ids = _scenario(db)
    pendings = dp.collect_pending_verdicts(db, "p1")
    by = _by_subject(pendings)
    assert set(by) == {ids["blocking"], ids["idle"], ids["gate_mandatory"],
                       ids["gate_extra"], ids["proposal"]}
    assert by[ids["blocking"]].kind == dp.VERDICT_CONTRADICTION_RESOLUTION
    assert by[ids["gate_mandatory"]].kind == dp.VERDICT_HUMAN_GATE
    assert (by[ids["proposal"]].kind
            == dp.VERDICT_CLASSIFICATION_ACTION_PROPOSAL)
    # every packet requires the existing human-authority coordinate
    assert all(p.required_authority == dp.REQUIRED_AUTHORITY for p in pendings)
    # blocking is derived from the authoritative HR-08 denials
    assert by[ids["blocking"]].blocking_completion is True
    assert by[ids["gate_mandatory"]].blocking_completion is True
    assert by[ids["idle"]].blocking_completion is False
    assert by[ids["gate_extra"]].blocking_completion is False
    assert by[ids["proposal"]].blocking_completion is False
    # deterministic: same rows -> same tuple, ordered by (kind, subject_ref)
    assert pendings == dp.collect_pending_verdicts(db, "p1")
    assert pendings == tuple(sorted(
        pendings, key=lambda v: (v.kind, v.subject_ref)))


def test_proposal_gate_is_recomputed_not_trusted(db):
    """Parity with the controller replay: a non-gated class is never pending,
    and a decided proposal leaves the set."""
    _program(db)
    prop_hash = _classification(db, "fc-x", "IMPLEMENTATION_FAILURE",
                                PROGRAM_ID)
    _proposal(db, "prop-effective", prop_hash, "REVIEW_DOWNSTREAM_IMPACT",
              "IMPLEMENTATION_FAILURE")
    assert dp.collect_pending_verdicts(db, "p1") == ()

    _classification(db, "fc-y", "FRAMING_ERROR", PROGRAM_ID)
    _proposal(db, "prop-gated", "ch-fc-y", "REVIEW_DOWNSTREAM_IMPACT",
              "FRAMING_ERROR")
    subjects = {p.subject_ref for p in dp.collect_pending_verdicts(db, "p1")}
    assert subjects == {"prop-gated"}

    db.execute(
        """INSERT INTO events (event_type, project_id, correlation_id,
           caused_by, created_at)
           VALUES ('ClassificationActionDecision', 'p1', 'prop-gated',
                   'operator', ?)""", (CLOCK,))
    assert dp.collect_pending_verdicts(db, "p1") == ()


def test_resolved_gate_is_not_pending(db):
    _program(db)
    _human_gate(db, "gate-hypothesis", "hypothesis")
    assert [p.subject_ref for p in dp.collect_pending_verdicts(db, "p1")] == \
        ["gate-hypothesis"]
    db.execute(
        """INSERT INTO events (event_type, project_id, task_id, caused_by,
           created_at) VALUES ('HumanGateResolved', 'p1', 'gate-hypothesis',
           'operator', ?)""", (CLOCK,))
    assert dp.collect_pending_verdicts(db, "p1") == ()


def test_packet_is_byte_pinned_and_hash_recomputed(db):
    ids = _scenario(db)
    pending = _by_subject(dp.collect_pending_verdicts(db, "p1"))[ids["blocking"]]
    packet = dp.assemble_packet(db, "p1", pending)

    canonical = dp.canonical_packet_json(packet).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    assert digest == GOLDEN_PACKET_SHA256
    assert packet["content_hash"] == dp.PACKET_HASH_PREFIX + digest[:24]
    # recomputed, never trusted: re-assembly reproduces the same bytes
    again = dp.assemble_packet(db, "p1", pending)
    assert dp.canonical_packet_json(again) == dp.canonical_packet_json(packet)


def test_packet_cone_and_diffs_are_grounded(db):
    ids = _scenario(db)
    pending = _by_subject(dp.collect_pending_verdicts(db, "p1"))[ids["blocking"]]
    packet = dp.assemble_packet(db, "p1", pending)

    assert packet["verdict"]["state"] == dp.PENDING_VERDICT
    cone = {n["node_ref"]: n for n in packet["evidence_cone"]}
    assert "fc-a" in cone and "fc-b" in cone      # both classification parties
    assert "ev-shared" in cone                     # the evidence overlap
    assert cone["fc-a"]["detail"]["content_hash"] == "ch-fc-a"
    fields = {d["field"] for d in packet["diffs"]}
    assert {"failure_class", "evidence_overlap"} <= fields
    fc = next(d for d in packet["diffs"] if d["field"] == "failure_class")
    assert fc["left"] == "IMPLEMENTATION_FAILURE"
    assert fc["right"] == "ENVIRONMENT_MISMATCH"


def test_gate_packet_includes_task_and_dependency_diffs(db):
    ids = _scenario(db)
    pending = _by_subject(
        dp.collect_pending_verdicts(db, "p1"))[ids["gate_mandatory"]]
    packet = dp.assemble_packet(db, "p1", pending)
    assert {n["node_kind"] for n in packet["evidence_cone"]} >= {"task"}
    assert any(n["node_ref"] == ids["gate_mandatory"]
               for n in packet["evidence_cone"])
    fields = {d["field"] for d in packet["diffs"]}
    assert {"gate_requirement", "dependency_status"} <= fields


# ── 2. deterministic queue ordering ──


def test_queue_orders_completion_blocking_contradiction_first(db):
    ids = _scenario(db)
    queue = dp.build_decision_queue(db, "p1")
    items = queue["items"]
    assert items[0]["verdict"]["subject_ref"] == ids["blocking"]
    assert items[0]["verdict"]["kind"] == dp.VERDICT_CONTRADICTION_RESOLUTION
    assert items[0]["verdict"]["blocking_completion"] is True
    assert items[1]["verdict"]["subject_ref"] == ids["gate_mandatory"]
    assert items[2]["verdict"]["subject_ref"] == ids["idle"]
    # tiers are non-decreasing down the queue
    tiers = [i["verdict"]["tier"] for i in items]
    assert tiers == sorted(tiers)


def test_order_is_input_order_independent(db):
    ids = _scenario(db)
    pendings = dp.collect_pending_verdicts(db, "p1")
    forward = dp.order_pending_verdicts(pendings)
    backward = dp.order_pending_verdicts(tuple(reversed(pendings)))
    assert forward == backward
    assert [p.subject_ref for p in forward] == [
        ids["blocking"], ids["gate_mandatory"], ids["idle"], ids["proposal"],
        ids["gate_extra"]]


def test_queue_is_byte_deterministic(db):
    _scenario(db)
    q1 = dp.build_decision_queue(db, "p1")
    q2 = dp.build_decision_queue(db, "p1")
    assert dp.canonical_packet_json(q1) == dp.canonical_packet_json(q2)
    assert q1["content_hash"] == q2["content_hash"]
    assert q1["content_hash"].startswith(dp.QUEUE_HASH_PREFIX)


# ── 3. HARD RULE: no auto-ratification, ever ──


def _snapshot(db):
    return {
        "events": db.execute("SELECT COUNT(*) c FROM events").fetchone()["c"],
        "types": tuple(sorted(
            r["event_type"] for r in db.execute(
                "SELECT DISTINCT event_type FROM events"))),
        "tasks": tuple(sorted(
            (r["task_id"], r["status"]) for r in db.execute(
                "SELECT task_id, status FROM tasks"))),
        "contradictions": tuple(sorted(
            (r["contradiction_id"], r["status"]) for r in db.execute(
                "SELECT contradiction_id, status FROM contradictions"))),
    }


def test_packet_alone_never_ratifies(db):
    """Running the whole public surface leaves every row + the journal intact,
    and the ratification surface still refuses without credential + verdict."""
    _scenario(db)
    before = _snapshot(db)

    # Exercise the entire read-only surface.
    pendings = dp.collect_pending_verdicts(db, "p1")
    dp.order_pending_verdicts(pendings)
    for pending in pendings:
        packet = dp.assemble_packet(db, "p1", pending)
        # a packet is data for a human: no ratifying field, no operator id
        assert "decision" not in packet
        assert "operator_id" not in packet
        assert "token" not in dp.canonical_packet_json(packet)
        assert packet["verdict"]["state"] == dp.PENDING_VERDICT
    queue = dp.build_decision_queue(db, "p1")
    assert queue["items"]

    # Nothing was written: identical journal, task and contradiction state.
    assert _snapshot(db) == before
    # No ratification-shaped event appeared.
    ratified = {"HumanGateResolved", "HumanDecisionReceived",
                "ClassificationActionDecision", "ContradictionResolution"}
    assert ratified.isdisjoint(set(_snapshot(db)["types"]))

    # The packet exists, yet the existing surface still refuses to ratify
    # without a ratified credential...
    ctrl = Controller(db, project_id="p1", clock=frozen_clock(CLOCK))
    refused = ctrl.resolve_human_gate(
        task_id="gate-hypothesis", verdict="APPROVED",
        operator_id=OP_ID, operator_token="wrong-token")
    assert refused["rejected"] is True and refused["code"] == "OPERATOR"
    # ...and refuses an unrecognised verdict even WITH a valid credential.
    bad_verdict = ctrl.resolve_human_gate(
        task_id="gate-hypothesis", verdict="MAYBE",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert bad_verdict["rejected"] is True and bad_verdict["code"] == "VERDICT"
    # Still nothing written — a packet is not a verdict.
    assert _snapshot(db) == before


def test_module_exposes_no_ratification_api(db):
    _scenario(db)
    for name in ("apply_intent", "resolve_human_gate",
                 "record_operator_decision", "ratify"):
        assert not hasattr(dp, name)


# ── 4. purity guard: the module source carries no write / gateway call ──


def test_module_source_is_read_only():
    source = Path(dp.__file__).read_text(encoding="utf-8")
    for forbidden in ("apply_intent(", "resolve_human_gate(",
                      "record_operator_decision(", "INSERT INTO",
                      "UPDATE ", "DELETE FROM", ".commit(", ".executescript(",
                      "operator_credentials"):
        assert forbidden not in source, f"forbidden token in module: {forbidden}"
    assert all("ratif" not in name for name in dp.__all__)
