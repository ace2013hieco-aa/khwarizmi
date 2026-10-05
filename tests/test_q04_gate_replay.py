"""IDR-040 §3 — the human-approval gate + ratified decision + replay loop.

A PROPOSE_CLASSIFICATION_ACTION whose classification requires human
confirmation (FRAMING_ERROR) is admitted PENDING_HUMAN_APPROVAL — it can
never become executable until a ratified RESOLVE_CLASSIFICATION_PROPOSAL
decision (APPROVED / REJECTED), recorded as the ClassificationActionDecision
event (one proposal, one verdict; idempotent repeats; contradictory refused).
The reconcile-loop consumer replays undecided pending proposals into the
Director's next digest run (reconcile_digest v2, pending_proposals section),
closing the propose-observe loop. These fixtures pin the gate admission
contract, the decision admission contract, and the replay/digest fold.
"""
from __future__ import annotations

import json as _json

import pytest

from hermes.core import frozen_clock, utc_now
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.failure_classifications import (
    FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.controller import Controller
from hermes.research.failure_classification import (
    FailureClass,
    permitted_actions_for,
)
from hermes.research.gateway import GatewayRejection, apply_intent

CLOCK = "2026-01-01T00:00:00.000000+00:00"

# A4 — the ratified operator credential every verdict in this file presents
# (proof-of-humanity: an unratified verdict is refused fail-closed).
OP_ID = "op-1"
OP_TOKEN = "op-token-1"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    from hermes.persistence.repositories import OperatorCredentialRepository
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    yield conn
    conn.close()


def _artifact(conn, aid, atype="evidence"):
    conn.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, 'p1', NULL, ?, ?, 0, 'inline://t', 'test', NULL, ?)""",
        (aid, atype, "ch-" + aid, CLOCK),
    )


def _edge(conn, down, up, etype="cites"):
    conn.execute(
        "INSERT INTO provenance_edges (artifact_id, upstream_id,"
        " edge_type, created_at) VALUES (?, ?, ?, ?)",
        (down, up, etype, CLOCK),
    )


def _classification_with_class(conn, failure_class, cls_art="fc-ev-a",
                               evidence_ref="ev-a"):
    """A D3-valid classification row with an explicit failure class — for
    the gate fixtures (FRAMING_ERROR is the one human-confirmation class)."""
    _artifact(conn, evidence_ref, "evidence")
    _artifact(conn, cls_art, FAILURE_CLASSIFICATION_ARTIFACT_TYPE)
    meta = _json.dumps({
        "failure_class": failure_class,
        "hypothesis_ref": "h1", "classifier_version": "1.0",
        "classification_id": cls_art,
        "evidence_refs": ["evidence:" + evidence_ref],
        "program_ref": "rp-1", "falsifying_evidence_refs": [],
        "permitted_actions": sorted(
            a.value for a in permitted_actions_for(
                FailureClass(failure_class)))},
        sort_keys=True)
    conn.execute(
        "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
        (meta, cls_art))
    _edge(conn, cls_art, evidence_ref, "cites")


def _classification(conn, cls_art="fc-ev-a", evidence_ref="ev-a"):
    """IMPLEMENTATION_FAILURE — the EFFECTIVE (no-gate) baseline."""
    _classification_with_class(conn, "IMPLEMENTATION_FAILURE",
                               cls_art=cls_art, evidence_ref=evidence_ref)


def _proposal_intent(**overrides):
    payload = {
        "classification_ref": "failure_classification:ch-fc-ev-a",
        "action": "REVIEW_DOWNSTREAM_IMPACT",
        "candidate_artifact_ref": "ev-a",
        "rationale": "retracted source downstream",
    }
    payload.update(overrides.pop("payload", {}))
    return Intent(
        kind=IntentKind.PROPOSE_CLASSIFICATION_ACTION,
        proposed_by=overrides.pop("proposed_by", "DIRECTOR"),
        project_id=overrides.pop("project_id", "p1"),
        payload=payload,
        justification="test",
    )


def _resolve_intent(proposal_id, decision, **overrides):
    return Intent(
        kind=IntentKind.RESOLVE_CLASSIFICATION_PROPOSAL,
        proposed_by=overrides.pop("proposed_by", "DETERMINISTIC"),
        project_id=overrides.pop("project_id", "p1"),
        payload={
            "proposal_id": proposal_id,
            "decision": decision,
            "rationale": "operator verdict",
            "operator_id": OP_ID,
        },
        justification="test",
    )


def _make(conn, **kwargs):
    return Controller(conn, project_id="p1", clock=utc_now, **kwargs)


class TestHumanApprovalGate:
    """A proposal whose classification requires human confirmation is
    admitted PENDING_HUMAN_APPROVAL — it can never become executable until
    a ratified decision; an EFFECTIVE proposal needs no decision."""

    def test_framing_error_proposal_is_pending(self, db):
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        result = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        assert result.duplicate is False
        row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'ClassificationActionProposed'"
        ).fetchone()
        assert _json.loads(row["payload_json"])[
            "state"] == "PENDING_HUMAN_APPROVAL"

    def test_other_class_proposal_is_effective(self, db):
        conn = db
        _classification(conn)
        result = apply_intent(conn, _proposal_intent(), clock=lambda: CLOCK)
        assert result.duplicate is False
        row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'ClassificationActionProposed'"
        ).fetchone()
        assert _json.loads(row["payload_json"])["state"] == "EFFECTIVE"

    def test_gate_recomputed_never_trusted_from_storage(self, db):
        """The gate derives from the class via requires_human_confirmation_for:
        a tampered failure_class that is not a ratified member is refused —
        nothing admitted, nothing pending."""
        conn = db
        _artifact(conn, "ev-a")
        _artifact(conn, "fc-evil", FAILURE_CLASSIFICATION_ARTIFACT_TYPE)
        conn.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (_json.dumps({"failure_class": "NOT_A_CLASS",
                          "hypothesis_ref": "h1",
                          "classification_id": "fc-evil",
                          "evidence_refs": [], "program_ref": "rp-1",
                          "falsifying_evidence_refs": [],
                          "permitted_actions": [],
                          "classifier_version": "1.0"}), "fc-evil"))
        _edge(conn, "fc-evil", "ev-a", "cites")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _proposal_intent(payload={
                "classification_ref": "failure_classification:ch-fc-evil",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "CLASSIFICATION_REF"
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionProposed'"
        ).fetchone()[0] == 0


class TestResolveClassificationProposal:
    def test_approve_records_ratified_decision(self, db):
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        result = apply_intent(
            conn, _resolve_intent(prop.entity_id, "APPROVED"),
            clock=lambda: CLOCK)
        assert result.duplicate is False
        assert result.event_type == "ClassificationActionDecision"
        row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()
        payload = _json.loads(row["payload_json"])
        assert payload["proposal_id"] == prop.entity_id
        assert payload["decision"] == "APPROVED"

    def test_reject_records_ratified_decision(self, db):
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        result = apply_intent(
            conn, _resolve_intent(prop.entity_id, "REJECTED"),
            clock=lambda: CLOCK)
        assert result.duplicate is False
        assert result.event_type == "ClassificationActionDecision"

    def test_identical_decision_is_idempotent(self, db):
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        apply_intent(conn, _resolve_intent(prop.entity_id, "APPROVED"),
                     clock=lambda: CLOCK)
        second = apply_intent(
            conn, _resolve_intent(prop.entity_id, "APPROVED"),
            clock=lambda: CLOCK)
        assert second.duplicate is True
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()[0] == 1
    def test_contradictory_decision_refused(self, db):
        """One proposal, one ratified verdict — a contradictory second
        decision is refused, nothing appended."""
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        apply_intent(conn, _resolve_intent(prop.entity_id, "APPROVED"),
                     clock=lambda: CLOCK)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _resolve_intent(prop.entity_id, "REJECTED"),
                         clock=lambda: CLOCK)
        assert exc.value.code == "PROPOSAL"
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()[0] == 1

    def test_effective_proposal_has_nothing_to_decide(self, db):
        conn = db
        _classification(conn)  # IMPLEMENTATION_FAILURE -> EFFECTIVE
        prop = apply_intent(conn, _proposal_intent(), clock=lambda: CLOCK)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _resolve_intent(prop.entity_id, "APPROVED"),
                         clock=lambda: CLOCK)
        assert exc.value.code == "PROPOSAL"

    def test_unknown_proposal_refused(self, db):
        conn = db
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _resolve_intent("prop_ghost", "APPROVED"),
                         clock=lambda: CLOCK)
        assert exc.value.code == "PROPOSAL"

    def test_unknown_payload_key_rejected(self, db):
        conn = db
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, Intent(
                kind=IntentKind.RESOLVE_CLASSIFICATION_PROPOSAL,
                proposed_by="DETERMINISTIC", project_id="p1",
                payload={"proposal_id": "prop_x", "decision": "APPROVED",
                         "extra": 1},
                justification="test"), clock=lambda: CLOCK)
        assert exc.value.code == "MALFORMED_PAYLOAD"

    def test_unratified_decision_rejected(self, db):
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _resolve_intent(prop.entity_id, "MAYBE"),
                         clock=lambda: CLOCK)
        assert exc.value.code == "MALFORMED_PAYLOAD"


class TestPendingProposalReplay:
    def test_undecided_pending_replayed(self, db):
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        pending = _make(conn).pending_classification_proposals()
        assert len(pending) == 1
        assert pending[0]["proposal_id"] == prop.entity_id
        assert pending[0]["action"] == "ROUTE_TO_SCOPE_REVIEW"
        assert pending[0]["candidate_artifact_ref"] == "ev-a"

    def test_decided_proposal_leaves_the_replay(self, db):
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        apply_intent(conn, _resolve_intent(prop.entity_id, "APPROVED"),
                     clock=lambda: CLOCK)
        assert _make(conn).pending_classification_proposals() == []

    def test_effective_proposals_never_replayed(self, db):
        conn = db
        _classification(conn)
        apply_intent(conn, _proposal_intent(), clock=lambda: CLOCK)
        assert _make(conn).pending_classification_proposals() == []

    def test_digest_folds_pending_proposals_versioned(self, db):
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        ctrl = _make(conn)
        digest = ctrl.reconcile_digest()
        assert digest["digest_version"] == "4"
        assert [p["proposal_id"] for p in digest["pending_proposals"]] == [
            prop.entity_id]
        assert ctrl.reconcile_digest() == digest  # deterministic

    def test_digest_replay_reflects_decision(self, db):
        """The propose-observe loop closes: decide -> the next digest run
        no longer replays the proposal (and its content hash changes)."""
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        ctrl = _make(conn)
        before = ctrl.reconcile_digest()
        assert len(before["pending_proposals"]) == 1
        apply_intent(conn, _resolve_intent(prop.entity_id, "REJECTED"),
                     clock=lambda: CLOCK)
        after = ctrl.reconcile_digest()
        assert after["pending_proposals"] == []
        assert after["content_hash"] != before["content_hash"]

    def test_corrupt_proposal_payload_skipped_with_note(self, db):
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        conn.execute(
            "UPDATE events SET payload_json = '{corrupt' "
            "WHERE event_type = 'ClassificationActionProposed'")
        ctrl = _make(conn)
        assert ctrl.pending_classification_proposals() == []
        assert any("corrupt" in n for n in ctrl._notes)

    def test_tampered_pending_on_no_gate_proposal_not_replayed(self, db):
        """F11 regression — the replay recomputes the gate from the
        classification (F2): a forged PENDING state on a proposal whose
        class needs no confirmation is never surfaced as a pending advisory,
        is noted as a tamper signal, and cannot be decided."""
        conn = db
        _classification(conn)  # IMPLEMENTATION_FAILURE -> EFFECTIVE
        prop = apply_intent(conn, _proposal_intent(), clock=lambda: CLOCK)
        conn.execute(
            "UPDATE events SET payload_json = json_set(payload_json, "
            "'$.state', 'PENDING_HUMAN_APPROVAL') WHERE correlation_id = ?",
            (prop.entity_id,))
        ctrl = _make(conn)
        assert ctrl.pending_classification_proposals() == []
        assert any("tamper" in n for n in ctrl._notes)
        out = ctrl.record_operator_decision(
            proposal_id=prop.entity_id, decision="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "PROPOSAL"
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()[0] == 0

    def test_tampered_effective_on_gated_proposal_still_replayed(self, db):
        """F11 regression (downward tamper) — a forged EFFECTIVE state on a
        FRAMING_ERROR proposal cannot suppress the replay or block the
        decision: the class is the source of truth, never the stored state."""
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        conn.execute(
            "UPDATE events SET payload_json = json_set(payload_json, "
            "'$.state', 'EFFECTIVE') WHERE correlation_id = ?",
            (prop.entity_id,))
        ctrl = _make(conn)
        pending = ctrl.pending_classification_proposals()
        assert len(pending) == 1
        assert pending[0]["proposal_id"] == prop.entity_id
        out = ctrl.record_operator_decision(
            proposal_id=prop.entity_id, decision="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False

    def test_replay_skips_undereferenceable_classification_with_note(self, db):
        """F11 regression (fail-closed) — a proposal whose classification
        ref no longer dereferences (artifact deleted) is never replayed as
        pending, with an observable note, and cannot be decided."""
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        conn.execute("DELETE FROM artifacts WHERE artifact_id = 'fc-ev-a'")
        ctrl = _make(conn)
        assert ctrl.pending_classification_proposals() == []
        assert any("does not dereference" in n for n in ctrl._notes)
        out = ctrl.record_operator_decision(
            proposal_id=prop.entity_id, decision="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "PROPOSAL"


class TestOperatorIngestion:
    """The FIRST-CLASS operator-verdict ingestion surface: record_operator_decision
    builds the RESOLVE_CLASSIFICATION_PROPOSAL intent (DETERMINISTIC) and admits
    it through the gateway — the sanctioned path for the human verdict. This is
    the loop's contract; the hand-built-intent fixtures above pin the same
    gateway semantics, and these pin the surface itself."""

    def _seed_pending(self, db):
        conn = db
        _classification_with_class(conn, "FRAMING_ERROR")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "ROUTE_TO_SCOPE_REVIEW",
        }), clock=lambda: CLOCK)
        return conn, _make(conn), prop.entity_id

    def test_approve_via_ingestion(self, db):
        conn, ctrl, pid = self._seed_pending(db)
        out = ctrl.record_operator_decision(
            proposal_id=pid, decision="APPROVED", rationale="ok", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False and out["duplicate"] is False
        assert ctrl.pending_classification_proposals() == []
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()[0] == 1

    def test_reject_via_ingestion(self, db):
        conn, ctrl, pid = self._seed_pending(db)
        out = ctrl.record_operator_decision(
            proposal_id=pid, decision="REJECTED", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False
        row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()
        assert _json.loads(row["payload_json"])["decision"] == "REJECTED"

    def test_duplicate_verdict_idempotent(self, db):
        conn, ctrl, pid = self._seed_pending(db)
        ctrl.record_operator_decision(proposal_id=pid, decision="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
        out = ctrl.record_operator_decision(proposal_id=pid, decision="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["duplicate"] is True and out["rejected"] is False
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()[0] == 1

    def test_contradictory_verdict_surfaced_as_data(self, db):
        conn, ctrl, pid = self._seed_pending(db)
        ctrl.record_operator_decision(proposal_id=pid, decision="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
        out = ctrl.record_operator_decision(proposal_id=pid, decision="REJECTED", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "PROPOSAL"
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()[0] == 1  # nothing written on the refusal

    def test_unknown_proposal_surfaced_as_data(self, db):
        conn, ctrl, _ = self._seed_pending(db)
        out = ctrl.record_operator_decision(
            proposal_id="prop_ghost", decision="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "PROPOSAL"
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()[0] == 0

    def test_unratified_decision_surfaced_as_data(self, db):
        _conn, ctrl, pid = self._seed_pending(db)
        out = ctrl.record_operator_decision(proposal_id=pid, decision="MAYBE", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "MALFORMED_PAYLOAD"

    def test_effective_proposal_surfaced_as_data(self, db):
        conn = db
        _classification(conn)  # IMPLEMENTATION_FAILURE -> EFFECTIVE
        prop = apply_intent(conn, _proposal_intent(), clock=lambda: CLOCK)
        out = _make(conn).record_operator_decision(
            proposal_id=prop.entity_id, decision="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "PROPOSAL"

    def test_ingestion_runs_through_fenced_connection_after_tick(self, db):
        """After a real tick (lock acquired + released, fence set), the
        operator verdict runs through the fenced connection — no
        LockLostError, the generation fence holds, and the decision lands."""
        conn, ctrl, pid = self._seed_pending(db)
        out = ctrl.tick()  # acquires the lock, refreshes the fence, releases
        assert out.idle is not None
        assert ctrl._fenced is not None
        result = ctrl.record_operator_decision(
            proposal_id=pid, decision="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert result["rejected"] is False
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()[0] == 1


    def test_lease_held_by_another_controller_refused(self, db):
        """The verdict write is lease-held: while another controller owns
        the scheduler lock, the verdict is refused fail-closed (code LOCK)
        and nothing is written; once the lease is free the same verdict
        lands."""
        conn, ctrl, pid = self._seed_pending(db)
        other = _make(conn)
        assert other._acquire_lock() is True
        out = ctrl.record_operator_decision(proposal_id=pid, decision="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "LOCK"
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()[0] == 0
        other._release_lock()
        out = ctrl.record_operator_decision(proposal_id=pid, decision="APPROVED", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()[0] == 1

    def test_lease_released_after_verdict(self, db):
        """The acquisition is scoped: after the verdict, the scheduler
        lock row is gone — the surface never leaves a held lease behind."""
        conn, ctrl, pid = self._seed_pending(db)
        ctrl.record_operator_decision(proposal_id=pid, decision="REJECTED", operator_id=OP_ID, operator_token=OP_TOKEN)
        assert conn.execute(
            "SELECT COUNT(*) FROM scheduler_lock").fetchone()[0] == 0


class TestPerActionGate:
    """IDR-041 authority decision (ratified): the proposal gate is
    ACTION-shaped, not class-only — authority-shaped actions (REJECT_BRANCH,
    the two S16 scope routes, and mechanism substitution — the AC-5 leg)
    require human confirmation regardless of class, so their approvals
    become REACHABLE through the gate. Advisory / proposal-shaped actions
    stay EFFECTIVE."""

    def test_reject_branch_is_pending_for_any_class(self, db):
        conn = db
        # DECLARED_CONSTRAINT_VIOLATION does NOT require human confirmation
        # by class — but REJECT_BRANCH is authority-shaped, so the proposal
        # is PENDING and decidable.
        _classification_with_class(conn, "DECLARED_CONSTRAINT_VIOLATION")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "REJECT_BRANCH",
        }), clock=lambda: CLOCK)
        assert prop.duplicate is False
        row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'ClassificationActionProposed'"
        ).fetchone()
        assert _json.loads(row["payload_json"])[
            "state"] == "PENDING_HUMAN_APPROVAL"
        # and it IS decidable — the full chain is reachable
        res = apply_intent(
            conn, _resolve_intent(prop.entity_id, "APPROVED"),
            clock=lambda: CLOCK)
        assert res.duplicate is False
        assert res.event_type == "ClassificationActionDecision"

    def test_scope_routes_are_pending(self, db):
        conn = db
        _classification(conn)  # IMPLEMENTATION_FAILURE — EFFECTIVE by class
        for action in ("ROUTE_TO_SCOPE_REVIEW", "PROPOSE_SCOPE_NARROWING",
                       "PROPOSE_MECHANISM_SUBSTITUTION"):
            prop = apply_intent(conn, _proposal_intent(payload={
                "action": action,
            }), clock=lambda: CLOCK)
            row = conn.execute(
                "SELECT payload_json FROM events "
                "WHERE event_type = 'ClassificationActionProposed' "
                "  AND correlation_id = ?",
                (prop.entity_id,),
            ).fetchone()
            assert _json.loads(row["payload_json"])[
                "state"] == "PENDING_HUMAN_APPROVAL"

    def test_non_authority_actions_stay_effective(self, db):
        conn = db
        _classification(conn)
        for action in ("REVIEW_DOWNSTREAM_IMPACT",
                       "PARK_FOR_RESOURCE_REVIEW", "ESCALATE_TO_DIRECTOR"):
            prop = apply_intent(conn, _proposal_intent(payload={
                "action": action,
            }), clock=lambda: CLOCK)
            row = conn.execute(
                "SELECT payload_json FROM events "
                "WHERE event_type = 'ClassificationActionProposed' "
                "  AND correlation_id = ?",
                (prop.entity_id,),
            ).fetchone()
            assert _json.loads(row["payload_json"])["state"] == "EFFECTIVE"

    def test_mechanism_substitution_is_decidable(self, db):
        """The AC-5 leg is now REACHABLE: PROPOSE_MECHANISM_SUBSTITUTION is
        gated (PENDING) and decidable end-to-end through the gate."""
        conn = db
        _classification(conn)  # IMPLEMENTATION_FAILURE owns the action
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "PROPOSE_MECHANISM_SUBSTITUTION",
        }), clock=lambda: CLOCK)
        res = apply_intent(
            conn, _resolve_intent(prop.entity_id, "APPROVED"),
            clock=lambda: CLOCK)
        assert res.duplicate is False
        assert res.event_type == "ClassificationActionDecision"

    def test_contributing_framing_error_gates_non_authority_action(self, db):
        """Red-team §2 remediation: a FRAMING_ERROR CONTRIBUTING FACTOR on a
        non-authority primary class (RESOURCE_CONSTRAINT -> PARK_FOR_RESOURCE_REVIEW)
        still requires human confirmation — the gate fires on the framing
        assertion itself, at admission (recomputed F2), and the proposal is
        decidable."""
        from hermes.research.failure_classification import (
            FailureClass,
            permitted_actions_for,
        )
        conn = db
        _artifact(conn, "ev-a", "evidence")
        _artifact(conn, "fc-rc", FAILURE_CLASSIFICATION_ARTIFACT_TYPE)
        conn.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = 'fc-rc'",
            (_json.dumps({
                "failure_class": "RESOURCE_CONSTRAINT",
                "hypothesis_ref": "h1", "classifier_version": "1.0",
                "classification_id": "fc-rc",
                "evidence_refs": ["evidence:ev-a"],
                "program_ref": "rp-1", "falsifying_evidence_refs": [],
                "contributing_factors": ["FRAMING_ERROR"],
                "permitted_actions": sorted(
                    a.value for a in permitted_actions_for(
                        FailureClass.RESOURCE_CONSTRAINT))}, sort_keys=True),)
        )
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "PARK_FOR_RESOURCE_REVIEW",
            "classification_ref": "failure_classification:ch-fc-rc",
        }), clock=lambda: CLOCK)
        assert prop.duplicate is False
        row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'ClassificationActionProposed' "
            "AND correlation_id = ?", (prop.entity_id,)
        ).fetchone()
        assert _json.loads(row["payload_json"])["state"] ==             "PENDING_HUMAN_APPROVAL"
        # decidable through the gate — the verdict is ratified
        res = apply_intent(conn, _resolve_intent(
            prop.entity_id, "APPROVED"), clock=lambda: CLOCK)
        assert res.duplicate is False
        assert res.event_type == "ClassificationActionDecision"

    def test_gate_recomputed_from_action_never_stored(self, db):
        """The gate recompute takes the ACTION (F2): a proposal whose stored
        state claims EFFECTIVE but whose ACTION is authority-shaped is
        replayed as pending by the controller's digest (the class wins for
        the class-branch; the action branch is derived from the payload)."""
        conn = db
        _classification_with_class(conn, "DECLARED_CONSTRAINT_VIOLATION")
        prop = apply_intent(conn, _proposal_intent(payload={
            "action": "REJECT_BRANCH",
        }), clock=lambda: CLOCK)
        # tamper the stored state down to EFFECTIVE
        conn.execute(
            "UPDATE events SET payload_json = ? "
            "WHERE event_type = 'ClassificationActionProposed' "
            "  AND correlation_id = ?",
            (_json.dumps({**_json.loads(conn.execute(
                "SELECT payload_json FROM events "
                "WHERE event_type = 'ClassificationActionProposed' "
                "  AND correlation_id = ?", (prop.entity_id,)
            ).fetchone()["payload_json"]), "state": "EFFECTIVE"}),
             prop.entity_id),
        )
        ctrl = _make(conn)
        pending = ctrl.pending_classification_proposals()
        assert any(i["proposal_id"] == prop.entity_id for i in pending)

    def test_decidable_proposal_with_unknown_action_refused(self, db):
        """The decision validator recomputes the action too: a proposal
        whose action is not a ratified member is undecidable — nothing to
        decide, nothing pending."""
        conn = db
        _classification_with_class(conn, "DECLARED_CONSTRAINT_VIOLATION")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _proposal_intent(payload={
                "action": "REJECT_BRANCH",
                "bogus": 1,
            }), clock=lambda: CLOCK)
        assert exc.value.code == "MALFORMED_PAYLOAD"


def test_12_f2_operator_decision_refusals_pay_one_kdf_each(db, monkeypatch):
    """F2-lens timing probe on record_operator_decision: EVERY outcome —
    unratified operator (OPERATOR), unknown proposal (PROPOSAL), the
    ratified APPROVED success, the idempotent duplicate, the
    contradictory-verdict refusal (PROPOSAL), and the lease-held LOCK —
    pays EXACTLY ONE PBKDF2 run, because the operator verify precedes the
    lock and the gateway on this surface. A stopwatch on the ingestion
    surface cannot distinguish operator validity, proposal state, or
    lease state."""
    import hashlib

    import hermes.persistence.repositories as repos_mod
    # Order-independence: pre-warm the lazily-built module dummy hash (the
    # sibling F2 probes do the same).
    repos_mod._burn_dummy_operator_work("order-independent-warmup")

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    _classification_with_class(db, "FRAMING_ERROR")
    prop = apply_intent(db, _proposal_intent(payload={
        "action": "ROUTE_TO_SCOPE_REVIEW",
    }), clock=lambda: CLOCK)
    ctrl = _make(db)
    pid = prop.entity_id

    # unratified operator: OPERATOR — one KDF, nothing written
    out = ctrl.record_operator_decision(
        proposal_id=pid, decision="APPROVED",
        operator_id="ghost", operator_token="wrong-token-123456")
    assert out["rejected"] is True and out["code"] == "OPERATOR"
    assert calls["n"] == 1
    # unknown proposal: PROPOSAL — one KDF (the verify precedes the gateway)
    calls["n"] = 0
    out = ctrl.record_operator_decision(
        proposal_id="prop_ghost", decision="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "PROPOSAL"
    assert calls["n"] == 1
    # ratified APPROVED: lands — one KDF
    calls["n"] = 0
    out = ctrl.record_operator_decision(
        proposal_id=pid, decision="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False and out["duplicate"] is False
    assert calls["n"] == 1
    # duplicate: idempotent success — still one KDF
    calls["n"] = 0
    out = ctrl.record_operator_decision(
        proposal_id=pid, decision="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False and out["duplicate"] is True
    assert calls["n"] == 1
    # contradictory verdict: PROPOSAL refusal — one KDF, nothing written
    calls["n"] = 0
    out = ctrl.record_operator_decision(
        proposal_id=pid, decision="REJECTED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "PROPOSAL"
    assert calls["n"] == 1
    # LOCK: lease held by another controller — one KDF (the verify
    # precedes the lock; the gateway is never reached, so even a resolved
    # proposal refuses LOCK with the same budget)
    other = _make(db)
    assert other._acquire_lock() is True
    calls["n"] = 0
    out = ctrl.record_operator_decision(
        proposal_id=pid, decision="APPROVED",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "LOCK"
    assert calls["n"] == 1
    other._release_lock()
