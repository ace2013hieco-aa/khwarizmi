"""CX-OVERLAP-1 (P2-17, design-gate ruling R7) — fresh overlap store.

Pins the recorded-row provenance fix in ``_validate_record_contradiction``:
the ``contradictions.evidence_overlap_json`` row carries the FRESH overlap
re-derived inside the write transaction, never the pre-lock pair-rule
snapshot (a resolution/retraction committing between the pre-lock read
and ``BEGIN IMMEDIATE`` must not be recorded as admitted provenance).

The DIFFER scenario is constructed deterministically at the facts seam
(the first two ``_cx_classification_facts`` calls — the pre-lock pair
rule — see committed truth; later calls — the in-transaction recompute —
see the controlled post-race facts), so the pre-lock and in-lock values
differ without weakening the production path. Also pinned: the
empty-overlap refusal gate is byte-unchanged, a real retraction landing
in the pre-lock window still refuses in-transaction, N9 pre-lock refusal
paths are unchanged, the duplicate fast-path re-verifies nothing, and the
journal remains append-only.
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

import hermes.research.gateway as gateway_mod
from hermes.core import frozen_clock
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.core.node import NodeContract
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ContradictionRepository,
    OperatorCredentialRepository,
    ProjectRepository,
    TaskRepository,
    _append_event_to_db,
)
from hermes.persistence.source_outcomes import source_artifact_retracted
from hermes.research.contradictions import CONTRADICTION_DETECTOR_VERSION
from hermes.research.controller import Controller
from hermes.research.gateway import (
    EVIDENCE_REF,
    GatewayRejection,
    _cx_classification_facts,
    apply_intent,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1-long"
EV1 = "art-ev1"
EV2 = "art-ev2"
REFS = ["source_result:evhash1", "source_result:evhash2"]


# ═══════════════════════ fixture ═══════════════════════


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    yield conn
    conn.close()


def _make(db):
    return Controller(db, project_id="p1", clock=frozen_clock(CLOCK))


def _program(db):
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES ('rp-1', 'p1', 1, 'ch-rp-1', NULL, 'b', 'o', 'c1', 'p1',
                   '1', 'ih', ?, ?, '[]', '[]', '[]', '[]', NULL, 'director',
                   NULL, ?)""",
        (json.dumps([{"ref": "h1", "ladder_target": "SUPPORTED",
                      "falsification_condition": "fc", "rival_of": None,
                      "rival_status": None}]),
         json.dumps([{"ref": "p1"}]), CLOCK))
    db.commit()


def _task(db, task_id):
    TaskRepository(db, frozen_clock(CLOCK)).create(NodeContract(
        task_id=task_id, project_id="p1", task_type="TOOL_TASK",
        idempotency_key=f"idem-{task_id}", dependencies=[]))
    db.execute("UPDATE tasks SET status = 'RUNNING' WHERE task_id = ?",
               (task_id,))
    db.commit()


def _chain(db, *, ev_id, ev_hash, outcome_id, task_id):
    for aid, ch in ((outcome_id, f"outhash-{outcome_id}"), (ev_id, ev_hash)):
        db.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type,
                content_hash, size_bytes, storage_path, producer,
                metadata_json, created_at)
               VALUES (?, 'p1', NULL, 'source_result', ?, 1, 'x', 't',
                       NULL, ?)""",
            (aid, ch, CLOCK))
    for child, parent in ((outcome_id, task_id), (ev_id, outcome_id)):
        db.execute(
            "INSERT INTO provenance_edges "
            "(artifact_id, upstream_id, edge_type, created_at) "
            "VALUES (?, ?, 'derived_from', ?)",
            (child, parent, CLOCK))
    db.commit()


def _dcv(db, evidence_refs):
    return _make(db).record_failure_classification(
        program_ref="rp-1", hypothesis_ref="h1",
        failure_class="DECLARED_CONSTRAINT_VIOLATION",
        evidence_refs=list(evidence_refs),
        falsifying_evidence_refs=list(evidence_refs),
        explanation="operator analysis dcv", classifier_version="1.0",
        constraint_ref="hypothesis:h1:falsification_condition",
        proposed_by="operator:op-1", producing_task_id="t1",
        rationale="", operator_id=OP_ID, operator_token=OP_TOKEN)


def _impl(db, evidence_refs):
    return _make(db).record_failure_classification(
        program_ref="rp-1", hypothesis_ref="h1",
        failure_class="IMPLEMENTATION_FAILURE",
        evidence_refs=list(evidence_refs),
        falsifying_evidence_refs=list(evidence_refs),
        explanation="operator analysis impl", classifier_version="1.0",
        failed_mechanism_ref="prediction:p1",
        proposed_by="operator:op-1", producing_task_id="t1",
        rationale="", operator_id=OP_ID, operator_token=OP_TOKEN)


def _pair(db):
    """Two digest-valid RUNNING-task classifications sharing TWO evidence
    artifacts (the overlap is two items wide so a controlled drop leaves
    a non-empty fresh overlap). Returns (party_a_id, party_b_id)."""
    _program(db)
    _task(db, "t1")
    _chain(db, ev_id=EV1, ev_hash="evhash1", outcome_id="art-out1",
           task_id="t1")
    _chain(db, ev_id=EV2, ev_hash="evhash2", outcome_id="art-out2",
           task_id="t1")
    return _dcv(db, REFS)["entity_id"], _impl(db, REFS)["entity_id"]


def _record(db, party_a, party_b):
    return apply_intent(db, Intent(
        kind=IntentKind.RECORD_CONTRADICTION, proposed_by="DETERMINISTIC",
        project_id="p1", justification="cx-overlap test",
        payload={"party_a": party_a, "party_b": party_b,
                 "detector_version": CONTRADICTION_DETECTOR_VERSION,
                 "supersedes_ref": ""}))


def _retract(db, source_ref="source_result:evhash1"):
    import hashlib
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id="p1", correlation_id="hd-1", caused_by="operator",
        reason="operator decision",
        payload={"decision": "RETRACT_SOURCE", "source_ref": source_ref,
                 "reason_digest": hashlib.sha256(b"retracted").hexdigest()})
    return apply_intent(db, Intent(
        kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
        project_id="p1", justification="cx-overlap test",
        payload={"source_ref": source_ref, "reason": "retracted",
                 "human_decision_ref": "hd-1"}))


def _stored(db, contradiction_id):
    row = db.execute(
        "SELECT evidence_overlap_json AS j FROM contradictions "
        "WHERE contradiction_id = ?", (contradiction_id,)).fetchone()
    return json.loads(row["j"])


def _cx_event_payloads(db):
    rows = db.execute(
        "SELECT payload_json FROM events WHERE event_type = ?",
        (EventType.CONTRADICTION_DETECTED.value,)).fetchall()
    return [json.loads(r["payload_json"]) for r in rows]


def _facts_seam(*, mutate_after=2, mutate=None):
    """Deterministic seam over ``_cx_classification_facts``: the first
    ``mutate_after`` calls (the pre-lock pair rule) observe committed
    truth; later calls (the in-transaction fresh recompute) observe
    ``mutate(evidence, artifact_id)`` — modelling a state transition that
    commits inside the pre-lock window. The production path is not
    touched: only the facts input is scripted."""
    real = gateway_mod._cx_classification_facts
    state = {"calls": 0, "pre": {}}

    def scripted(conn, project_id, artifact_id):
        facts = real(conn, project_id, artifact_id)
        state["calls"] += 1
        if facts is not None and state["calls"] <= mutate_after:
            state["pre"][artifact_id] = sorted(facts["evidence"])
        if (facts is not None and mutate is not None
                and state["calls"] > mutate_after):
            facts = dict(facts)
            facts["evidence"] = mutate(
                set(facts["evidence"]), artifact_id)
        return facts

    return scripted, state


class _RetractAtBegin:
    """Connection proxy: fires a REAL ``_retract`` at the first
    ``BEGIN IMMEDIATE`` the RECORD_CONTRADICTION validator issues, then
    delegates — the production-semantics pre-lock-window race (the
    retraction commits after the pre-transaction pair rule and before
    the write transaction opens)."""

    def __init__(self, conn, retract):
        self._conn = conn
        self._retract = retract
        self.fired = False

    def execute(self, sql, *args, **kwargs):
        if (not self.fired and isinstance(sql, str)
                and sql.strip() == "BEGIN IMMEDIATE"):
            self.fired = True
            self._retract()
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


# ═══════════════════════ fresh-store pins ═══════════════════════


class TestFreshStore:
    def test_recorded_row_carries_fresh_overlap_not_prelock_snapshot(
            self, db):
        party_a, party_b = _pair(db)
        seam, state = _facts_seam(mutate=lambda ev, _aid: ev - {EV1})
        with mock.patch.object(gateway_mod, "_cx_classification_facts",
                               seam):
            result = _record(db, party_a, party_b)
        assert result.duplicate is False
        # 2 pre-lock pair-rule reads + 2 in-transaction fresh reads.
        assert state["calls"] == 4
        pre_lock = sorted(
            set(state["pre"][party_a]) & set(state["pre"][party_b]))
        assert pre_lock == [EV1, EV2]
        # The recorded row carries the FRESH in-transaction recompute —
        # the pre-lock snapshot never reaches the row.
        assert _stored(db, result.entity_id) == [EV2]
        assert _stored(db, result.entity_id) != pre_lock
        # Audit readback (entry / all_entries) shows the fresh value.
        repo = ContradictionRepository(db)
        entry = repo.entry("p1", result.entity_id)
        assert entry is not None
        assert entry["evidence_overlap"] == [EV2]
        assert repo.all_entries("p1")[0]["evidence_overlap"] == [EV2]
        # R7 change shape is scoped to the recorded row: the journal event
        # payload is a byte-stable consumer and stays on the pre-lock
        # snapshot. If a future gate rules the event must carry the fresh
        # value, this assertion is the deliberate change point.
        payloads = _cx_event_payloads(db)
        assert len(payloads) == 1
        assert payloads[0]["evidence_overlap"] == pre_lock

    def test_normal_record_stores_the_recomputed_overlap(self, db):
        party_a, party_b = _pair(db)
        result = _record(db, party_a, party_b)
        facts_a = _cx_classification_facts(db, "p1", party_a)
        facts_b = _cx_classification_facts(db, "p1", party_b)
        assert facts_a is not None and facts_b is not None
        recomputed = sorted(
            set(facts_a["evidence"]) & set(facts_b["evidence"]))
        assert recomputed == [EV1, EV2]
        assert _stored(db, result.entity_id) == recomputed
        repo = ContradictionRepository(db)
        entry = repo.entry("p1", result.entity_id)
        assert entry is not None
        assert entry["evidence_overlap"] == recomputed
        assert repo.all_entries("p1")[0]["evidence_overlap"] == recomputed


# ═══════════════════════ refusal gate pins ═══════════════════════


class TestRefusalGateUnchanged:
    def test_fresh_empty_overlap_refuses_with_unchanged_gate(self, db):
        party_a, party_b = _pair(db)
        # In-transaction recompute: party_b's evidence stops resolving —
        # the fresh intersection is empty while the pre-lock overlap was
        # [EV1, EV2]. The gate must refuse exactly as before.
        seam, _state = _facts_seam(
            mutate=lambda ev, aid: (set() if aid == party_b else ev))
        with mock.patch.object(gateway_mod, "_cx_classification_facts",
                               seam), pytest.raises(
                                   GatewayRejection) as exc:
            _record(db, party_a, party_b)
        assert exc.value.code == EVIDENCE_REF
        assert "share no currently-valid resolved evidence" in \
            exc.value.reason
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 0
        assert _cx_event_payloads(db) == []

    def test_real_retraction_in_prelock_window_refuses_in_transaction(
            self, db):
        party_a, party_b = _pair(db)
        proxy = _RetractAtBegin(db, lambda: _retract(db))
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(proxy, Intent(
                kind=IntentKind.RECORD_CONTRADICTION,
                proposed_by="DETERMINISTIC", project_id="p1",
                justification="cx-overlap test",
                payload={"party_a": party_a, "party_b": party_b,
                         "detector_version": CONTRADICTION_DETECTOR_VERSION,
                         "supersedes_ref": ""}))
        assert proxy.fired is True
        # The refusal came from the in-transaction N9 gate (the pre-lock
        # pair rule had already passed on the pre-retraction state).
        assert exc.value.code == EVIDENCE_REF
        assert "currently-valid" in exc.value.reason
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 0
        assert _cx_event_payloads(db) == []
        # The race actually raced: the retraction committed and the S5
        # cone invalidated both parties.
        assert source_artifact_retracted(db, "p1", EV1) is True
        assert _cx_classification_facts(db, "p1", party_a) is None
        assert _cx_classification_facts(db, "p1", party_b) is None

    def test_retraction_before_submission_refuses_prelock(self, db):
        party_a, party_b = _pair(db)
        _retract(db)
        with pytest.raises(GatewayRejection) as exc:
            _record(db, party_a, party_b)
        assert exc.value.code == EVIDENCE_REF
        assert "digest-valid" in exc.value.reason
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 0
        # N9 fence unchanged: re-detection records nothing new.
        assert _make(db).detect_contradictions()["recorded"] == []


# ═══════════════════════ duplicate fast-path pin ═══════════════════════


class TestDuplicateFastPath:
    def test_duplicate_does_not_recompute_and_does_not_rewrite(self, db):
        party_a, party_b = _pair(db)
        first = _record(db, party_a, party_b)
        stored_before = _stored(db, first.entity_id)
        events_before = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_DETECTED.value,)).fetchone()["c"]
        # Seam would make any fresh recompute fail/replace the facts —
        # proving the duplicate path never reaches it (P2-18 semantics:
        # duplicates do not re-verify; the recorded row is not rewritten).
        seam, state = _facts_seam(mutate=lambda ev, _aid: set())
        with mock.patch.object(gateway_mod, "_cx_classification_facts",
                               seam):
            second = _record(db, party_a, party_b)
        assert second.duplicate is True
        assert second.entity_id == first.entity_id
        assert state["calls"] == 2  # pre-lock pair rule only
        assert _stored(db, first.entity_id) == stored_before
        assert db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_DETECTED.value,)).fetchone()["c"] == \
            events_before


# ═══════════════════════ append-only pin ═══════════════════════


class TestAppendOnlyJournal:
    def test_record_appends_exactly_two_events(self, db):
        party_a, party_b = _pair(db)
        max_before = db.execute(
            "SELECT COALESCE(MAX(event_id), 0) m FROM events").fetchone()["m"]
        result = _record(db, party_a, party_b)
        new_types = sorted(
            r["event_type"] for r in db.execute(
                "SELECT event_type FROM events WHERE event_id > ?",
                (max_before,)).fetchall())
        assert new_types == sorted([
            EventType.CONTRADICTION_DETECTED.value,
            EventType.INTENT_APPLIED.value])
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions "
            "WHERE contradiction_id = ?",
            (result.entity_id,)).fetchone()["c"] == 1
        row = db.execute(
            "SELECT detection_event_ref FROM contradictions "
            "WHERE contradiction_id = ?",
            (result.entity_id,)).fetchone()
        assert row["detection_event_ref"] == result.entity_id
        # Duplicate re-record appends only the audit event — never a
        # second mutation row (append-only; history is never rewritten).
        max_mid = db.execute(
            "SELECT COALESCE(MAX(event_id), 0) m FROM events").fetchone()["m"]
        _record(db, party_a, party_b)
        new_types = sorted(
            r["event_type"] for r in db.execute(
                "SELECT event_type FROM events WHERE event_id > ?",
                (max_mid,)).fetchall())
        assert new_types == [EventType.INTENT_APPLIED.value]
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions").fetchone()["c"] == 1
