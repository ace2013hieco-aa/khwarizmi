"""IDR-041 — the first ratification-ref consumers.

An APPROVED classification-action proposal is a ratification FACT consumed by
the existing authority paths. Two consumers land here:

- EVIDENCE_TRANSITION (AC-4): an admission carrying a ``ratification_ref``
  is admitted only if the ref dereferences to an APPROVED REJECT_BRANCH
  proposal whose action is in the classification's permitted set (recomputed,
  F2); REJECTED/unknown/action-mismatch refs are refused. Proposal-shaped:
  the admission appends EVIDENCE_TRANSITION_PROPOSED and never APPLIES.
  Note: through the ratified gate, REJECT_BRANCH belongs only to
  DECLARED_CONSTRAINT_VIOLATION, which does NOT require human confirmation —
  so no legitimately-APPROVED REJECT_BRANCH proposal exists yet; the happy
  path is exercised with directly-built audit rows and the validator is the
  enforcement contract.
- The S16 scope-review intake (RECORD_SCOPE_REVIEW_DECISION): records the
  human's scope verdict on an APPROVED ROUTE_TO_SCOPE_REVIEW /
  PROPOSE_SCOPE_NARROWING proposal (the controller's lease-held
  record_scope_review_decision surface) — one scope decision per approval,
  never amending a brief, never executing.
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


def _classification(conn, failure_class, cls_art="fc-x", ev="ev-x"):
    _artifact(conn, ev, "evidence")
    _artifact(conn, cls_art, FAILURE_CLASSIFICATION_ARTIFACT_TYPE)
    meta = _json.dumps({
        "failure_class": failure_class, "hypothesis_ref": "h1",
        "classifier_version": "1.0", "classification_id": cls_art,
        "evidence_refs": ["evidence:" + ev], "program_ref": "rp-1",
        "falsifying_evidence_refs": [],
        "permitted_actions": sorted(
            a.value for a in permitted_actions_for(
                FailureClass(failure_class)))},
        sort_keys=True)
    conn.execute(
        "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
        (meta, cls_art))
    conn.execute(
        "INSERT INTO provenance_edges (artifact_id, upstream_id, edge_type,"
        " created_at) VALUES (?, ?, 'cites', ?)",
        (cls_art, ev, CLOCK))


def _propose(conn, action, ref="failure_classification:ch-fc-x",
             candidate="ev-x"):
    return apply_intent(conn, Intent(
        kind=IntentKind.PROPOSE_CLASSIFICATION_ACTION,
        proposed_by="DIRECTOR", project_id="p1",
        payload={"classification_ref": ref, "action": action,
                 "candidate_artifact_ref": candidate, "rationale": "r"},
        justification="t"), clock=lambda: CLOCK)


def _decide(conn, pid, verdict="APPROVED"):
    return apply_intent(conn, Intent(
        kind=IntentKind.RESOLVE_CLASSIFICATION_PROPOSAL,
        proposed_by="DETERMINISTIC", project_id="p1",
        payload={"proposal_id": pid, "decision": verdict,
                 "operator_id": OP_ID},
        justification="t"), clock=lambda: CLOCK)


def _direct_ratification(conn, pid, action, ref, candidate="ev-y",
                         decision="APPROVED"):
    """Builds an APPROVED proposal directly as audit rows (for classes
    whose gate never produces decisions — the enforcement contract)."""
    _event(conn, "ClassificationActionProposed", pid, {
        "classification_ref": ref, "action": action,
        "candidate_artifact_ref": candidate, "rationale": "r",
        "state": "EFFECTIVE"})
    _event(conn, "ClassificationActionDecision", pid, {
        "proposal_id": pid, "decision": decision, "rationale": "op"})


def _event(conn, event_type, corr, payload):
    conn.execute(
        "INSERT INTO events (event_type, project_id, correlation_id,"
        " caused_by, payload_json, created_at) "
        "VALUES (?, 'p1', ?, 'DETERMINISTIC', ?, ?)",
        (event_type, corr, _json.dumps(payload, sort_keys=True), CLOCK))


def _transition_intent(**overrides):
    payload = {
        "evidence_artifact_ref": "evidence:ev-y",
        "from_state": "SUPPORTED", "to_state": "REFUTED",
        "ratification_ref": "prop_reject_branch",
        "rationale": "decisive",
    }
    payload.update(overrides.pop("payload", {}))
    return Intent(
        kind=IntentKind.EVIDENCE_TRANSITION,
        proposed_by=overrides.pop("proposed_by", "RESEARCHER"),
        project_id=overrides.pop("project_id", "p1"),
        payload=payload, justification="t",
    )


def _make(conn, **kwargs):
    return Controller(conn, project_id="p1", clock=utc_now, **kwargs)


def test_f6_one_verdict_race_closed(tmp_path, monkeypatch):
    """F6 (audit): two CONCURRENT contradictory verdicts on the same
    proposal — the one-verdict check and the append now run in ONE
    BEGIN IMMEDIATE transaction, so a racing second verdict cannot slip
    past the prior-read: exactly ONE decision event lands and the second
    apply is refused (pre-fix, the probe landed APPROVED + REJECTED)."""
    import threading
    import time as _time

    import hermes.research.gateway as gateway_mod
    from hermes.persistence.database import connect as _connect
    from hermes.persistence.migrations import migrate_to_latest as _migrate
    from hermes.persistence.repositories import (
        OperatorCredentialRepository as _OCR,
    )
    from hermes.persistence.repositories import (
        ProjectRepository as _PR,
    )

    db_path = tmp_path / "f6_race.db"
    conn = _connect(str(db_path))
    _migrate(conn)
    _PR(conn).create("p1", "Test")
    _OCR(conn, frozen_clock(CLOCK)).register(OP_ID, OP_TOKEN, "T")
    _classification(conn, "FRAMING_ERROR")
    pid = _propose(conn, "ROUTE_TO_SCOPE_REVIEW").entity_id
    conn.close()

    real_append = gateway_mod._append_event_to_db

    def slow_append(*a, **k):
        _time.sleep(0.3)   # widen the write window for both racers
        return real_append(*a, **k)

    monkeypatch.setattr(gateway_mod, "_append_event_to_db", slow_append)

    results: dict[str, tuple] = {}

    def run(decision: str, tag: str):
        c = _connect(str(db_path))
        try:
            r = apply_intent(c, Intent(
                kind=IntentKind.RESOLVE_CLASSIFICATION_PROPOSAL,
                proposed_by="DETERMINISTIC", project_id="p1",
                payload={"proposal_id": pid, "decision": decision,
                         "operator_id": OP_ID}),
                clock=lambda: CLOCK)
            results[tag] = ("ok", r.duplicate)
        except GatewayRejection as exc:
            results[tag] = ("rejected", exc.code)
        finally:
            c.close()

    t1 = threading.Thread(target=run, args=("APPROVED", "A"))
    t2 = threading.Thread(target=run, args=("REJECTED", "B"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    verdicts = sorted(results)
    # exactly one verdict lands; the racing contradictory one is refused
    ok = [t for t in verdicts if results[t][0] == "ok"]
    rej = [t for t in verdicts if results[t][0] == "rejected"]
    assert len(ok) == 1 and len(rej) == 1
    assert results[rej[0]][1] == "PROPOSAL"
    conn2 = _connect(str(db_path))
    try:
        n = conn2.execute(
            "SELECT COUNT(*) c FROM events "
            "WHERE event_type = 'ClassificationActionDecision'"
        ).fetchone()["c"]
        assert n == 1
    finally:
        conn2.close()


class TestEvidenceTransitionRatification:
    """EVIDENCE_TRANSITION with the AC-4 ratification-ref contract: the ref
    must be an APPROVED REJECT_BRANCH proposal whose action is in the
    classification's permitted set (recomputed, F2). Proposal-shaped — the
    admission appends EVIDENCE_TRANSITION_PROPOSED and never APPLIES."""

    def _seed_ratified(self, db):
        conn = db
        _classification(conn, "DECLARED_CONSTRAINT_VIOLATION",
                        cls_art="fc-y", ev="ev-y")
        _direct_ratification(conn, "prop_reject_branch", "REJECT_BRANCH",
                             "failure_classification:ch-fc-y", "ev-y")
        return conn

    def test_ratified_transition_admitted(self, db):
        conn = self._seed_ratified(db)
        result = apply_intent(conn, _transition_intent(), clock=lambda: CLOCK)
        assert result.duplicate is False
        assert result.entity_type == "evidence_transition_proposal"
        assert result.entity_id.startswith("tr_")
        row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'EvidenceTransitionProposed'"
        ).fetchone()
        payload = _json.loads(row["payload_json"])
        assert payload["from_state"] == "SUPPORTED"
        assert payload["to_state"] == "REFUTED"
        assert payload["ratification_ref"] == "prop_reject_branch"

    def test_repeat_is_idempotent(self, db):
        conn = self._seed_ratified(db)
        first = apply_intent(conn, _transition_intent(), clock=lambda: CLOCK)
        second = apply_intent(conn, _transition_intent(), clock=lambda: CLOCK)
        assert first.entity_id == second.entity_id
        assert second.duplicate is True
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'EvidenceTransitionProposed'"
        ).fetchone()[0] == 1

    def test_rejected_ratification_refused(self, db):
        conn = self._seed_ratified(db)
        _direct_ratification(conn, "prop_rejected", "REJECT_BRANCH",
                             "failure_classification:ch-fc-y", "ev-y",
                             decision="REJECTED")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _transition_intent(payload={
                "ratification_ref": "prop_rejected",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "PROPOSAL"

    def test_unknown_ratification_refused(self, db):
        conn = self._seed_ratified(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _transition_intent(payload={
                "ratification_ref": "prop_ghost",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "PROPOSAL"

    def test_non_reject_branch_ratification_refused(self, db):
        """AC-4 action binding: an APPROVED proposal whose action is NOT
        REJECT_BRANCH can never ratify an evidence transition."""
        conn = self._seed_ratified(db)
        _direct_ratification(conn, "prop_route", "ROUTE_TO_SCOPE_REVIEW",
                             "failure_classification:ch-fc-y", "ev-y")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _transition_intent(payload={
                "ratification_ref": "prop_route",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "PROPOSAL"

    def test_action_outside_class_permitted_set_refused(self, db):
        """F2: the ratification re-verifies the action against the
        classification's permitted set recomputed from the class — a
        REJECT_BRANCH ref whose class does not permit REJECT_BRANCH
        (FRAMING_ERROR) is refused."""
        conn = self._seed_ratified(db)
        _classification(conn, "FRAMING_ERROR", cls_art="fc-z", ev="ev-z")
        _direct_ratification(conn, "prop_framing", "REJECT_BRANCH",
                             "failure_classification:ch-fc-z", "ev-z")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _transition_intent(payload={
                "ratification_ref": "prop_framing",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "PROPOSAL"

    def test_evidence_ref_does_not_dereference(self, db):
        conn = self._seed_ratified(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _transition_intent(payload={
                "evidence_artifact_ref": "evidence:ghost",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "EVIDENCE_REF"

    def test_unratified_states_refused(self, db):
        conn = self._seed_ratified(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _transition_intent(payload={
                "from_state": "SPECULATED",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "MALFORMED_PAYLOAD"
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _transition_intent(payload={
                "to_state": "SPECULATED",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "MALFORMED_PAYLOAD"

    def test_terminal_state_cannot_be_left(self, db):
        conn = self._seed_ratified(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _transition_intent(payload={
                "from_state": "REFUTED", "to_state": "SUPPORTED",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "MALFORMED_PAYLOAD"

    def test_noop_transition_refused(self, db):
        conn = self._seed_ratified(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _transition_intent(payload={
                "from_state": "SUPPORTED", "to_state": "SUPPORTED",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "MALFORMED_PAYLOAD"

    def test_unknown_payload_key_rejected(self, db):
        conn = self._seed_ratified(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _transition_intent(payload={
                "extra": "nope",
            }), clock=lambda: CLOCK)
        assert exc.value.code == "MALFORMED_PAYLOAD"

    def test_never_applies(self, db):
        """Proposal-shaped: the admission records the proposal and changes
        NO state — no EVIDENCE_TRANSITION_APPLIED event can ever exist from
        this path (the APPLIED side is the future Evidence Ladder's)."""
        conn = self._seed_ratified(db)
        apply_intent(conn, _transition_intent(), clock=lambda: CLOCK)
        applied = conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'EvidenceTransitionApplied'"
        ).fetchone()[0]
        assert applied == 0


class TestScopeReviewIntake:
    """The S16 scope-review intake (RECORD_SCOPE_REVIEW_DECISION): the
    human's scope verdict on an APPROVED S16-routed proposal, recorded
    through the controller's lease-held surface. One scope decision per
    approval; never amends a brief; never executes."""

    def _seed_approved_route(self, db, decision_verdict="APPROVED"):
        conn = db
        _classification(conn, "FRAMING_ERROR")
        prop = _propose(conn, "ROUTE_TO_SCOPE_REVIEW")
        _decide(conn, prop.entity_id, verdict=decision_verdict)
        return conn, _make(conn), prop.entity_id

    def test_scope_decision_recorded(self, db):
        conn, ctrl, pid = self._seed_approved_route(db)
        out = ctrl.record_scope_review_decision(
            proposal_id=pid, scope_decision="AMEND_SCOPE",
            rationale="tighten framing",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False and out["duplicate"] is False
        row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'ScopeReviewDecided'"
        ).fetchone()
        payload = _json.loads(row["payload_json"])
        assert payload["proposal_id"] == pid
        assert payload["scope_decision"] == "AMEND_SCOPE"
        assert payload["rationale"] == "tighten framing"

    def test_unratified_scope_decision_refused(self, db):
        """F7 (audit): A4 parity — a scope verdict without a RATIFIED
        operator credential is refused with code OPERATOR and nothing is
        written (the surface previously recorded human verdicts with no
        proof-of-humanity at all)."""
        conn, ctrl, pid = self._seed_approved_route(db)
        out = ctrl.record_scope_review_decision(
            proposal_id=pid, scope_decision="AMEND_SCOPE",
            operator_id="ghost", operator_token="wrong-token")
        assert out["rejected"] is True and out["code"] == "OPERATOR"
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ScopeReviewDecided'"
        ).fetchone()[0] == 0
        # a ratified operator still records afterwards
        out2 = ctrl.record_scope_review_decision(
            proposal_id=pid, scope_decision="AMEND_SCOPE",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out2["rejected"] is False

    def test_all_three_verdicts_recordable(self, db):
        conn = db
        for verdict in ("CONFIRM_SCOPE", "AMEND_SCOPE", "DEFER_SCOPE"):
            _classification(conn, "FRAMING_ERROR", cls_art="fc-" + verdict[:2],
                            ev="ev-" + verdict[:2])
            prop = _propose(conn, "ROUTE_TO_SCOPE_REVIEW",
                            ref="failure_classification:ch-fc-" + verdict[:2],
                            candidate="ev-" + verdict[:2])
            _decide(conn, prop.entity_id)
            out = _make(conn).record_scope_review_decision(
                proposal_id=prop.entity_id, scope_decision=verdict,
                operator_id=OP_ID, operator_token=OP_TOKEN)
            assert out["rejected"] is False
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ScopeReviewDecided'"
        ).fetchone()[0] == 3

    def test_duplicate_is_idempotent(self, db):
        conn, ctrl, pid = self._seed_approved_route(db)
        ctrl.record_scope_review_decision(proposal_id=pid,
                                          scope_decision="CONFIRM_SCOPE",
                                          operator_id=OP_ID,
                                          operator_token=OP_TOKEN)
        out = ctrl.record_scope_review_decision(
            proposal_id=pid, scope_decision="CONFIRM_SCOPE",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["duplicate"] is True and out["rejected"] is False
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ScopeReviewDecided'"
        ).fetchone()[0] == 1

    def test_contradictory_scope_decision_refused(self, db):
        """One scope decision per approval — a second DIFFERENT verdict is
        refused, nothing written."""
        conn, ctrl, pid = self._seed_approved_route(db)
        ctrl.record_scope_review_decision(proposal_id=pid,
                                          scope_decision="AMEND_SCOPE",
                                          operator_id=OP_ID,
                                          operator_token=OP_TOKEN)
        out = ctrl.record_scope_review_decision(
            proposal_id=pid, scope_decision="CONFIRM_SCOPE",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "PROPOSAL"
        assert conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'ScopeReviewDecided'"
        ).fetchone()[0] == 1

    def test_rejected_approval_refused(self, db):
        _conn, ctrl, pid = self._seed_approved_route(
            db, decision_verdict="REJECTED")
        out = ctrl.record_scope_review_decision(
            proposal_id=pid, scope_decision="CONFIRM_SCOPE",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "PROPOSAL"

    def test_unknown_approval_refused(self, db):
        conn = db
        out = _make(conn).record_scope_review_decision(
            proposal_id="prop_ghost", scope_decision="CONFIRM_SCOPE",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "PROPOSAL"

    def test_non_s16_routed_approval_refused(self, db):
        """The intake accepts only S16-routed approvals: an APPROVED
        proposal whose action is not ROUTE_TO_SCOPE_REVIEW /
        PROPOSE_SCOPE_NARROWING (e.g. REVIEW_DOWNSTREAM_IMPACT) is refused."""
        conn = db
        _classification(conn, "DECLARED_CONSTRAINT_VIOLATION",
                        cls_art="fc-y", ev="ev-y")
        _direct_ratification(conn, "prop_review", "REVIEW_DOWNSTREAM_IMPACT",
                             "failure_classification:ch-fc-y", "ev-y")
        out = _make(conn).record_scope_review_decision(
            proposal_id="prop_review", scope_decision="CONFIRM_SCOPE",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "PROPOSAL"

    def test_unratified_decision_refused(self, db):
        _conn, ctrl, pid = self._seed_approved_route(db)
        out = ctrl.record_scope_review_decision(
            proposal_id=pid, scope_decision="MAYBE_SCOPE",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "MALFORMED_PAYLOAD"

    def test_role_gate_internal_only(self, db):
        conn = db
        _classification(conn, "FRAMING_ERROR")
        prop = _propose(conn, "ROUTE_TO_SCOPE_REVIEW")
        _decide(conn, prop.entity_id)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, Intent(
                kind=IntentKind.RECORD_SCOPE_REVIEW_DECISION,
                proposed_by="DIRECTOR", project_id="p1",
                payload={"proposal_id": prop.entity_id,
                         "scope_decision": "CONFIRM_SCOPE"},
                justification="t"), clock=lambda: CLOCK)
        assert exc.value.code == "ROLE"

    def test_lease_held_by_another_controller_refused(self, db):
        conn, ctrl, pid = self._seed_approved_route(db)
        other = _make(conn)
        assert other._acquire_lock() is True
        out = ctrl.record_scope_review_decision(
            proposal_id=pid, scope_decision="CONFIRM_SCOPE",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True and out["code"] == "LOCK"
        other._release_lock()

    def test_never_amends_brief(self, db):
        """The intake records the decision; the S16 authority's versioned
        brief amendment is a separate act — no scope_briefs row is touched."""
        conn, ctrl, pid = self._seed_approved_route(db)
        ctrl.record_scope_review_decision(proposal_id=pid,
                                          scope_decision="AMEND_SCOPE",
                                          operator_id=OP_ID,
                                          operator_token=OP_TOKEN)
        assert conn.execute(
            "SELECT COUNT(*) FROM scope_briefs").fetchone()[0] == 0

    def test_unknown_payload_key_rejected(self, db):
        conn, _ctrl, pid = self._seed_approved_route(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, Intent(
                kind=IntentKind.RECORD_SCOPE_REVIEW_DECISION,
                proposed_by="DETERMINISTIC", project_id="p1",
                payload={"proposal_id": pid,
                         "scope_decision": "CONFIRM_SCOPE",
                         "extra": "nope"},
                justification="t"), clock=lambda: CLOCK)
        assert exc.value.code == "MALFORMED_PAYLOAD"


def _seed_brief(conn):
    conn.execute(
        """INSERT INTO scope_briefs
           (brief_id, project_id, version, content_hash, supersedes_id,
            scope_text_json, rationale, created_at, frozen_at)
           VALUES ('brief-1', 'p1', 1, 'briefhash1', NULL, '{"scope":"x"}',
                   NULL, ?, ?)""",
        (CLOCK, CLOCK))


def _program_payload(**overrides):
    payload = {
        "scope_ref": "brief-1",
        "epistemic_objective": "Establish whether momentum predicts XAUUSD",
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
        "discrimination_requirements": [
            {"ref": "D1", "hypothesis_a": "H1", "hypothesis_b": "H0",
             "observable": "20d_returns",
             "expected_difference": "H1 positive, H0 zero",
             "required_condition": "trend_up",
             "measurement_method_ref": "method-1"},
        ],
        "methodology_constraints": ["icss-v1"],
        "task_graph_template_ref": None,
        "compiler_version": "1.0.0",
        "policy_version": "rp-2026.1",
        "schema_version": "1",
        "supersedes_ref": None,
    }
    payload.update(overrides)
    return payload


def _program_intent(payload, proposed_by="DIRECTOR"):
    return Intent(
        kind=IntentKind.PROPOSE_RESEARCH_PROGRAM,
        proposed_by=proposed_by, project_id="p1",
        payload=payload, justification="ratified mechanism substitution",
    )


class TestProgramRatifiedRationale:
    """AC-5 (IDR-041): PROPOSE_RESEARCH_PROGRAM accepts a ratification_ref
    as ratified rationale evidence — an APPROVED PROPOSE_MECHANISM_
    SUBSTITUTION proposal whose action is in the classification's permitted
    set (recomputed, F2). The compile checks are unchanged; the ref is
    recorded on the program row's reason. Through the ratified gate the
    mechanism-substitution approval is unreachable (IMPLEMENTATION_FAILURE
    needs no human confirmation) — the happy path uses directly-built audit
    rows, the refusal paths are live."""

    def _seed_mech(self, db):
        conn = db
        _seed_brief(conn)
        _classification(conn, "IMPLEMENTATION_FAILURE", cls_art="fc-m",
                        ev="ev-m")
        _direct_ratification(conn, "prop_mech", "PROPOSE_MECHANISM_SUBSTITUTION",
                             "failure_classification:ch-fc-m", "ev-m")
        return conn

    def test_ratified_ref_compiles_and_records_evidence(self, db):
        conn = self._seed_mech(db)
        result = apply_intent(conn, _program_intent(
            _program_payload(ratification_ref="prop_mech")),
            clock=lambda: CLOCK)
        assert result.duplicate is False
        assert result.entity_type == "research_program"
        row = conn.execute(
            "SELECT reason FROM research_programs WHERE program_id = ?",
            (result.entity_id,),
        ).fetchone()
        assert row["reason"].endswith("(ratification_ref=prop_mech)")

    def test_program_without_ref_still_compiles(self, db):
        """The existing checks are unchanged: a program without the ref is
        admitted exactly as before (AC-5 is evidence-only)."""
        conn = self._seed_mech(db)
        result = apply_intent(conn, _program_intent(_program_payload()),
                              clock=lambda: CLOCK)
        assert result.duplicate is False
        assert result.entity_type == "research_program"

    def test_rejected_ratification_refused(self, db):
        conn = self._seed_mech(db)
        _direct_ratification(conn, "prop_rej", "PROPOSE_MECHANISM_SUBSTITUTION",
                             "failure_classification:ch-fc-m", "ev-m",
                             decision="REJECTED")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _program_intent(_program_payload(
                ratification_ref="prop_rej")), clock=lambda: CLOCK)
        assert exc.value.code == "PROPOSAL"
        assert conn.execute(
            "SELECT COUNT(*) FROM research_programs").fetchone()[0] == 0

    def test_unknown_ratification_refused(self, db):
        conn = self._seed_mech(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _program_intent(_program_payload(
                ratification_ref="prop_ghost")), clock=lambda: CLOCK)
        assert exc.value.code == "PROPOSAL"

    def test_non_mechanism_ratification_refused(self, db):
        conn = self._seed_mech(db)
        _direct_ratification(conn, "prop_review", "REVIEW_DOWNSTREAM_IMPACT",
                             "failure_classification:ch-fc-m", "ev-m")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _program_intent(_program_payload(
                ratification_ref="prop_review")), clock=lambda: CLOCK)
        assert exc.value.code == "PROPOSAL"

    def test_action_outside_class_permitted_set_refused(self, db):
        conn = self._seed_mech(db)
        _classification(conn, "FRAMING_ERROR", cls_art="fc-z", ev="ev-z")
        _direct_ratification(conn, "prop_framing",
                             "PROPOSE_MECHANISM_SUBSTITUTION",
                             "failure_classification:ch-fc-z", "ev-z")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _program_intent(_program_payload(
                ratification_ref="prop_framing")), clock=lambda: CLOCK)
        assert exc.value.code == "PROPOSAL"

    def test_malformed_ref_type_refused(self, db):
        conn = self._seed_mech(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, _program_intent(_program_payload(
                ratification_ref=123)), clock=lambda: CLOCK)
        assert exc.value.code == "MALFORMED_PAYLOAD"


def test_12_f2_scope_decision_refusals_pay_one_kdf_each(db, monkeypatch):
    """F2-lens timing probe on record_scope_review_decision: EVERY
    outcome — unratified operator (OPERATOR), unknown approval
    (PROPOSAL), the ratified record (success), the idempotent duplicate,
    the contradictory second scope decision (PROPOSAL), and the
    lease-held LOCK — pays EXACTLY ONE PBKDF2 run, because the operator
    verify precedes the lock and the gateway on this surface. A stopwatch
    cannot distinguish operator validity, approval state, or lease
    state."""
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

    conn = db
    _classification(conn, "FRAMING_ERROR")
    prop = _propose(conn, "ROUTE_TO_SCOPE_REVIEW")
    _decide(conn, prop.entity_id)
    ctrl = _make(conn)
    pid = prop.entity_id

    # unratified operator: OPERATOR — one KDF, nothing written
    out = ctrl.record_scope_review_decision(
        proposal_id=pid, scope_decision="AMEND_SCOPE",
        operator_id="ghost", operator_token="wrong-token-123456")
    assert out["rejected"] is True and out["code"] == "OPERATOR"
    assert calls["n"] == 1
    # unknown approval: PROPOSAL — one KDF (the verify precedes the gateway)
    calls["n"] = 0
    out = ctrl.record_scope_review_decision(
        proposal_id="prop_ghost", scope_decision="CONFIRM_SCOPE",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "PROPOSAL"
    assert calls["n"] == 1
    # ratified record lands — one KDF
    calls["n"] = 0
    out = ctrl.record_scope_review_decision(
        proposal_id=pid, scope_decision="AMEND_SCOPE",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False and out["duplicate"] is False
    assert calls["n"] == 1
    # duplicate: idempotent — still one KDF
    calls["n"] = 0
    out = ctrl.record_scope_review_decision(
        proposal_id=pid, scope_decision="AMEND_SCOPE",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is False and out["duplicate"] is True
    assert calls["n"] == 1
    # contradictory second scope decision: PROPOSAL — one KDF, nothing new
    calls["n"] = 0
    out = ctrl.record_scope_review_decision(
        proposal_id=pid, scope_decision="CONFIRM_SCOPE",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "PROPOSAL"
    assert calls["n"] == 1
    # LOCK: lease held by another controller — one KDF (the verify
    # precedes the lock; the gateway is never reached)
    other = _make(conn)
    assert other._acquire_lock() is True
    calls["n"] = 0
    out = ctrl.record_scope_review_decision(
        proposal_id=pid, scope_decision="CONFIRM_SCOPE",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    assert out["rejected"] is True and out["code"] == "LOCK"
    assert calls["n"] == 1
    other._release_lock()
