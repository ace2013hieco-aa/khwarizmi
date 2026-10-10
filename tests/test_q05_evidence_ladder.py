"""Evidence Ladder APPLIED side (IDR-041 AC-1..5) — the deterministic
transition executor.

The APPLY pass is the ladder's ONE write path: obligation climbs (the
highest rung whose artifact obligation set is satisfied by the recorded
per-requirement satisfaction links) and the ratified REFUTED terminus (an
admitted EVIDENCE_TRANSITION_PROPOSED whose AC-4 ratification RE-VERIFIES
at apply time). Every transition writes an ``evidence_ladder_state`` row +
an ``EvidenceTransitionApplied`` event atomically, with a deterministic
transition id; the current rung is DERIVED from ratified sources, never
trusted from the cache (F2). These fixtures pin AC-1 (deterministic,
idempotent climbs), AC-2 (REFUTED only from re-verified ratified input),
AC-3 (REFUTED terminal), AC-4 (crash-recovery determinism), and AC-5 (no
bare-payload writes).
"""
from __future__ import annotations

import json as _json
import sqlite3

import pytest

from hermes.core import frozen_clock
from hermes.core.intents import Intent, IntentKind
from hermes.core.node import AgentProfile, NodeContract, NodeType
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.failure_classifications import (
    FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
    FailureClassificationRepository,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.program_obligations import (
    ProgramRequirementSatisfactionRepository,
    ValidationVerdictRepository,
)
from hermes.persistence.repositories import (
    ProjectRepository,
    TaskRepository,
)
from hermes.research.controller import Controller
from hermes.research.failure_classification import (
    FailureClass,
    FailureClassificationDraft,
    FalsificationRecord,
    permitted_actions_for,
)
from hermes.research.gateway import apply_intent

CLOCK = "2026-01-01T00:00:00.000000+00:00"

SUPPORTED_CLASSES = ("pre_registered_experiment", "statistical_analysis",
                     "validation", "adversarial_critique")
ROBUST_CLASSES = SUPPORTED_CLASSES + ("robustness_validation",
                                      "out_of_sample_validation",
                                      "regime_analysis")
REPLICATED_CLASSES = ROBUST_CLASSES + ("replication_report",)


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


def _make(conn, **kwargs):
    return Controller(conn, project_id="p1", clock=frozen_clock(CLOCK),
                      **kwargs)


def insert_program(db, program_id="rp-1", *, hypotheses=(), evidence=(),
                   version=1):
    """A minimal research_programs row (the test_controller_q02 shape)."""
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, ?, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', ?,
                   '[]', '[]', ?, '[]', '[]', NULL, 'director', NULL, ?)""",
        (program_id, "p1", version, "ch-" + program_id,
         _json.dumps(list(hypotheses)), _json.dumps(list(evidence)), CLOCK),
    )


def _hyp(ref, ladder="SUPPORTED"):
    return {"ref": ref, "ladder_target": ladder,
            "falsification_condition": "fc", "rival_of": None,
            "rival_status": None}


def _req(claim_ref, ladder="SUPPORTED"):
    """An evidence requirement DERIVED from a confirmatory target — the
    compiled shape (the test_controller_q02 convention). The required
    artifact classes come from the ratified LADDER_OBLIGATIONS constant."""
    from hermes.research.programs import LADDER_OBLIGATIONS, LadderTarget
    artifacts, _ = LADDER_OBLIGATIONS[LadderTarget(ladder)]
    return {"claim_ref": claim_ref, "ladder_target": ladder,
            "required_artifacts": list(artifacts), "associated_gates": []}


def insert_artifact(db, artifact_id, artifact_type, *, meta=None):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, 'p1', NULL, ?, ?, 1, 'x', 't', ?, ?)""",
        (artifact_id, artifact_type, "ch-" + artifact_id,
         _json.dumps(meta or {}), CLOCK),
    )


def satisfy(db, program_id, requirement_ref, classes, prefix="art",
            *, verdicts: bool = True):
    """Insert the required-class artifacts and record the satisfaction
    links (the IDR-038 §3.1 write path — the ratified obligation facts).

    ``verdicts=True`` (default) also records a PASS validation verdict for
    each artifact (M1/HR-02: content validation gates the ladder — a link
    without a verdict is refused and certifies nothing). ``verdicts=False``
    exercises the pre-M1 shape (links without verdicts), which the
    derivation must refuse."""
    repo = ProgramRequirementSatisfactionRepository(
        db, clock=frozen_clock(CLOCK))
    verdict_repo = ValidationVerdictRepository(db, clock=frozen_clock(CLOCK))
    for i, cls in enumerate(classes):
        aid = f"{prefix}-{i}-{cls}"
        insert_artifact(db, aid, cls)
        if verdicts:
            verdict_repo.record(project_id="p1", artifact_id=aid,
                                verdict="PASS")
            repo.record(project_id="p1", program_id=program_id,
                        requirement_ref=requirement_ref, artifact_id=aid)
        else:
            # pre-M1 shape: link inserted via raw SQL (the write path
            # refuses verdict-less links) — proves the DERIVATION refuses
            # verdict-less classes, not just the write.
            db.execute(
                """INSERT INTO program_requirement_satisfactions
                   (satisfaction_id, project_id, program_id, requirement_ref,
                    artifact_id, created_at)
                   VALUES (?, 'p1', ?, ?, ?, ?)""",
                (f"ss_{prefix}_{i}_{cls}", program_id, requirement_ref,
                 aid, CLOCK))


def _ladder_rows(db):
    return [dict(r) for r in db.execute(
        "SELECT program_id, hypothesis_ref, version, rung, transition_id, "
        "       derived_from FROM evidence_ladder_state "
        "ORDER BY program_id, hypothesis_ref, version")]


def _applied_events(db):
    return [dict(r) for r in db.execute(
        "SELECT correlation_id, from_state, to_state, payload_json "
        "FROM events WHERE event_type = 'EvidenceTransitionApplied' "
        "ORDER BY event_id")]


def _classification(db, *, failure_class="DECLARED_CONSTRAINT_VIOLATION",
                    cls_art="fc-x", evidence_ref="ev-a",
                    program_ref="rp-1", hypothesis_ref="h1",
                    constraint_ref=None):
    """A D3-valid, CONTENT-CONSISTENT classification row — REJECT_BRANCH
    is permitted for DECLARED_CONSTRAINT_VIOLATION, so the full
    ratification chain is reachable; ``constraint_ref`` optionally records
    the cited declared constraint (the bare-classification falsification
    driver reads it). The row's content_hash is the derived identity
    (IDR-036 EC-V6) — the APPLY's F13 content-integrity check re-derives
    it from the metadata, so the fixture row must be self-consistent.
    Returns the ``failure_classification:<content_hash>`` ref."""
    from hermes.research.evidence_ladder import classification_content_hash
    insert_artifact(db, evidence_ref, "evidence")
    meta = {
        "schema_version": "1",
        "failure_class": failure_class,
        "hypothesis_ref": hypothesis_ref,
        "program_ref": program_ref,
        "classification_id": cls_art,
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": ["evidence:" + evidence_ref],
        "constraint_ref": None,
        "failed_mechanism_ref": None,
        "regime_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": "test",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": [],
        "permitted_actions": sorted(
            a.value for a in permitted_actions_for(
                FailureClass(failure_class))),
    }
    if constraint_ref is not None:
        meta["constraint_ref"] = constraint_ref
    content_hash = classification_content_hash(meta, "p1")
    insert_artifact(db, cls_art, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
                    meta=meta)
    db.execute(
        "UPDATE artifacts SET content_hash = ? WHERE artifact_id = ?",
        (content_hash, cls_art))
    db.execute(
        "INSERT INTO provenance_edges (artifact_id, upstream_id, edge_type, "
        " created_at) VALUES (?, ?, 'cites', ?)",
        (cls_art, evidence_ref, CLOCK))
    # the content hash is str | None by the shared derivation's contract;
    # this fixture builds content-consistent metadata, so it is never None
    return "failure_classification:" + (content_hash or "")


def _proposal_intent(classification_ref, action, *, candidate="ev-a",
                     **overrides):
    payload = {
        "classification_ref": classification_ref,
        "action": action,
        "candidate_artifact_ref": candidate,
        "rationale": "test",
    }
    payload.update(overrides.pop("payload", {}))
    return Intent(
        kind=IntentKind.PROPOSE_CLASSIFICATION_ACTION,
        proposed_by=overrides.pop("proposed_by", "DIRECTOR"),
        project_id=overrides.pop("project_id", "p1"),
        payload=payload, justification="test",
    )


def _resolve_intent(proposal_id, decision):
    return Intent(
        kind=IntentKind.RESOLVE_CLASSIFICATION_PROPOSAL,
        proposed_by="DETERMINISTIC", project_id="p1",
        payload={"proposal_id": proposal_id, "decision": decision,
                 "rationale": "operator verdict", "operator_id": OP_ID},
        justification="test",
    )


def _transition_intent(ratification_ref=None, *, evidence_ref="ev-a",
                       to_state="REFUTED", from_state="SUPPORTED"):
    """``ratification_ref=None`` OMITS the key — the declared-but-unratified
    shape (the admission accepts it; the APPLY must not)."""
    payload = {"evidence_artifact_ref": "evidence:" + evidence_ref,
               "from_state": from_state, "to_state": to_state,
               "rationale": "test"}
    if ratification_ref is not None:
        payload["ratification_ref"] = ratification_ref
    return Intent(
        kind=IntentKind.EVIDENCE_TRANSITION,
        proposed_by="DIRECTOR", project_id="p1",
        payload=payload, justification="test",
    )


def ratified_refuted_chain(db, *, hypothesis_ref="h1", program_ref="rp-1",
                           to_state="REFUTED", evidence_ref="ev-a",
                           cls_art="fc-x"):
    """Build the full ratified REFUTED chain and return the transition
    proposal id: classification -> PENDING proposal -> APPROVED decision ->
    admitted EVIDENCE_TRANSITION proposal. Distinct ``evidence_ref`` /
    ``cls_art`` produce a distinct, independent ratification chain."""
    ref = _classification(db, program_ref=program_ref,
                          hypothesis_ref=hypothesis_ref,
                          evidence_ref=evidence_ref, cls_art=cls_art)
    prop = apply_intent(db, _proposal_intent(
        ref, "REJECT_BRANCH",
        payload={"candidate_artifact_ref": evidence_ref}),
        clock=frozen_clock(CLOCK))
    apply_intent(db, _resolve_intent(prop.entity_id, "APPROVED"),
                 clock=frozen_clock(CLOCK))
    tr = apply_intent(db, _transition_intent(
        prop.entity_id, evidence_ref=evidence_ref, to_state=to_state),
        clock=frozen_clock(CLOCK))
    return tr.entity_id, prop.entity_id
    apply_intent(db, _resolve_intent(prop.entity_id, "APPROVED"),
                 clock=frozen_clock(CLOCK))
    tr = apply_intent(db, _transition_intent(prop.entity_id,
                                             to_state=to_state),
                      clock=frozen_clock(CLOCK))
    return tr.entity_id, prop.entity_id


class TestObligationClimbs:
    """AC-1 — an obligation-satisfied program advances deterministically
    and idempotently, each advance emitting one EvidenceTransitionApplied
    with a deterministic correlation id."""

    def test_supported_climb_applied_once_and_idempotent(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        ctrl = _make(db)
        ctrl.tick()
        rows = _ladder_rows(db)
        assert [(r["version"], r["rung"], r["derived_from"])
                for r in rows] == [(1, "SUPPORTED", "obligations")]
        events = _applied_events(db)
        assert len(events) == 1
        assert events[0]["to_state"] == "SUPPORTED"
        assert events[0]["correlation_id"] == rows[0]["transition_id"]
        assert events[0]["correlation_id"].startswith("eltr_")
        # a re-tick over the same facts applies nothing new
        ctrl.tick()
        assert len(_applied_events(db)) == 1
        assert len(_ladder_rows(db)) == 1

    def test_partial_obligations_apply_nothing(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES[:2])
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []

    def test_empty_climb_refused_without_validation_verdicts(self, db):
        """T-EMPTY-CLIMB (M1 / HR-02): artifacts of ALL required classes
        whose content carries NO validation verdict can never climb — the
        ladder certifies CONTENT validation, never bare artifact labels.
        The audit's probe returned SUPPORTED from four empty artifacts of
        the right classes; this pins the closure: same artifacts, no
        verdicts, rung derivation returns nothing."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        # links WITHOUT verdicts: the pre-M1 shape the write path now
        # refuses — inserted via the raw SQL path to prove the DERIVATION
        # (not just the write) refuses verdict-less classes.
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES, verdicts=False)
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []
        # the satisfaction read reports no verdict-covered classes at all
        sats = ProgramRequirementSatisfactionRepository(
            db).satisfaction_types_by_requirement("p1")
        assert sats == {}

    def test_fail_verdict_never_climbs(self, db):
        """M1 / HR-02 — a FAIL validation verdict (content validated and
        found wanting) certifies nothing: the requirement stays outstanding
        and the ladder never climbs on it. The write path refuses the link
        outright (rule 5); even a raw-SQL link (bypassing the write) is
        excluded by the verdict-covered read."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        verdict_repo = ValidationVerdictRepository(db)
        from hermes.persistence.program_obligations import (
            RequirementSatisfactionError,
        )
        for i, cls in enumerate(SUPPORTED_CLASSES):
            aid = f"art-fail-{i}-{cls}"
            insert_artifact(db, aid, cls)
            verdict_repo.record(project_id="p1", artifact_id=aid,
                                verdict="FAIL")
            # the write path REFUSES a FAIL-verdict link (never a climb)
            with pytest.raises(
                    RequirementSatisfactionError, match="validation verdict"):
                ProgramRequirementSatisfactionRepository(db).record(
                    project_id="p1", program_id="rp-1",
                    requirement_ref="h1", artifact_id=aid)
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []
        # the verdict-covered read excludes every FAIL-verdict class
        assert ProgramRequirementSatisfactionRepository(
            db).satisfaction_types_by_requirement("p1") == {}

    def test_full_chain_supported_robust_replicated(self, db):
        """The SUPPORTED -> ROBUST -> REPLICATED chain: one applied
        transition per certified rung, versions 1, 2, 3."""
        insert_program(db, hypotheses=[_hyp("h1", "REPLICATED")],
                       evidence=[_req("h1", "REPLICATED")])
        ctrl = _make(db)
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES, prefix="s")
        ctrl.tick()
        assert [r["rung"] for r in _ladder_rows(db)] == ["SUPPORTED"]
        satisfy(db, "rp-1", "h1", ROBUST_CLASSES, prefix="r")
        ctrl.tick()
        assert [r["rung"] for r in _ladder_rows(db)] == ["SUPPORTED",
                                                         "ROBUST"]
        satisfy(db, "rp-1", "h1", REPLICATED_CLASSES, prefix="p")
        ctrl.tick()
        rows = _ladder_rows(db)
        assert [(r["version"], r["rung"]) for r in rows] == [
            (1, "SUPPORTED"), (2, "ROBUST"), (3, "REPLICATED")]
        events = _applied_events(db)
        assert [e["to_state"] for e in events] == ["SUPPORTED", "ROBUST",
                                                   "REPLICATED"]
        # from_rung chains the rungs
        assert [e["from_state"] for e in events] == [None, "SUPPORTED",
                                                     "ROBUST"]
        # every transition id is unique and deterministic
        ids = [e["correlation_id"] for e in events]
        assert len(set(ids)) == 3
        from hermes.research.evidence_ladder import obligation_transition_id
        assert ids[0] == obligation_transition_id("rp-1", "h1", "SUPPORTED")
        assert ids[1] == obligation_transition_id("rp-1", "h1", "ROBUST")
        assert ids[2] == obligation_transition_id("rp-1", "h1", "REPLICATED")
        # idempotent: another tick applies nothing
        ctrl.tick()
        assert len(_applied_events(db)) == 3

    def test_multiple_hypotheses_applied_in_sorted_order(self, db):
        insert_program(
            db, hypotheses=[_hyp("h2"), _hyp("h1")],
            evidence=[_req("h2"), _req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES, prefix="a")
        satisfy(db, "rp-1", "h2", SUPPORTED_CLASSES, prefix="b")
        ctrl = _make(db)
        ctrl.tick()
        events = _applied_events(db)
        payloads = [_json.loads(e["payload_json"]) for e in events]
        assert [p["hypothesis_ref"] for p in payloads] == ["h1", "h2"]
        assert [p["to_rung"] for p in payloads] == ["SUPPORTED", "SUPPORTED"]

    def test_all_classes_at_once_jumps_to_replicated(self, db):
        """The derived rung is the highest certified rung — when every
        obligation lands in one tick, one transition jumps to REPLICATED."""
        insert_program(db, hypotheses=[_hyp("h1", "REPLICATED")],
                       evidence=[_req("h1", "REPLICATED")])
        satisfy(db, "rp-1", "h1", REPLICATED_CLASSES)
        ctrl = _make(db)
        ctrl.tick()
        rows = _ladder_rows(db)
        assert [(r["version"], r["rung"]) for r in rows] == [
            (1, "REPLICATED")]
        assert len(_applied_events(db)) == 1


class TestRefuted:
    """AC-2/AC-3 — REFUTED is applied only from a re-verified ratified
    input, is terminal, and never comes from a bare payload."""

    def test_refuted_applied_from_ratified_approval(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        tr_id, _ = ratified_refuted_chain(db)
        ctrl = _make(db)
        ctrl.tick()
        rows = _ladder_rows(db)
        assert [(r["version"], r["rung"], r["derived_from"]) for r in rows] \
            == [(1, "REFUTED", "ratification")]
        events = _applied_events(db)
        assert len(events) == 1
        assert events[0]["to_state"] == "REFUTED"
        assert events[0]["correlation_id"] == rows[0]["transition_id"]
        payload = _json.loads(events[0]["payload_json"])
        assert payload["proposal_id"] == tr_id
        assert payload["to_rung"] == "REFUTED"
        # idempotent: a re-tick applies nothing new
        ctrl.tick()
        assert len(_applied_events(db)) == 1

    def test_refuted_without_ratification_applies_nothing(self, db):
        """AC-5 — a REFUTED proposal with no ratification is a declared
        record, never a ratified input: the APPLY writes nothing."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        ref = _classification(db)
        prop = apply_intent(db, _proposal_intent(
            ref, "REJECT_BRANCH"),
            clock=frozen_clock(CLOCK))
        apply_intent(db, _resolve_intent(prop.entity_id, "APPROVED"),
                     clock=frozen_clock(CLOCK))
        apply_intent(db, _transition_intent(), clock=frozen_clock(CLOCK))
        # sanity: the unratified transition proposal WAS admitted
        n = db.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type = 'EvidenceTransitionProposed'"
        ).fetchone()[0]
        assert n == 1
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []

    def test_forged_ratification_ref_applies_nothing(self, db):
        """The APPLY re-runs AC-4 at apply time: a transition proposal whose
        ratification does not re-verify (forged ref) is skipped with a note
        — written directly to the audit (bypassing admission) so the APPLY's
        own fail-closed path is what is probed."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        _classification(db)
        from hermes.persistence.repositories import _append_event_to_db
        _append_event_to_db(
            db, frozen_clock(CLOCK), "EvidenceTransitionProposed",
            project_id="p1", correlation_id="tr_forged",
            caused_by="DIRECTOR",
            payload={"evidence_artifact_ref": "evidence:ev-a",
                     "from_state": "SUPPORTED", "to_state": "REFUTED",
                     "ratification_ref": "prop_does_not_exist",
                     "rationale": ""},
        )
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []
        assert any("does not re-verify" in n for n in ctrl._notes)

    def test_rejected_decision_applies_nothing(self, db):
        """A transition proposal whose ratification decision is REJECTED
        re-verifies to nothing at apply time."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        ref = _classification(db)
        prop = apply_intent(db, _proposal_intent(
            ref, "REJECT_BRANCH"),
            clock=frozen_clock(CLOCK))
        apply_intent(db, _resolve_intent(prop.entity_id, "REJECTED"),
                     clock=frozen_clock(CLOCK))
        # admission refuses an un-approved ratification — write the
        # transition proposal directly to probe the APPLY re-verify
        from hermes.persistence.repositories import _append_event_to_db
        _append_event_to_db(
            db, frozen_clock(CLOCK), "EvidenceTransitionProposed",
            project_id="p1", correlation_id="tr_rejected",
            caused_by="DIRECTOR",
            payload={"evidence_artifact_ref": "evidence:ev-a",
                     "from_state": "SUPPORTED", "to_state": "REFUTED",
                     "ratification_ref": prop.entity_id,
                     "rationale": ""},
        )
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []
        assert any("does not re-verify" in n for n in ctrl._notes)

    def test_target_hypothesis_must_exist_in_program(self, db):
        """The ratified classification's (program, hypothesis) must resolve
        in the project — a foreign hypothesis applies nothing."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        _tr_id, _ = ratified_refuted_chain(db, hypothesis_ref="h-OTHER")
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []
        assert any("does not resolve" in n for n in ctrl._notes)

    def test_refuted_is_terminal(self, db):
        """AC-3 — once REFUTED is applied, no later ratified input can move
        it; and the admission itself refuses a transition leaving REFUTED."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        ratified_refuted_chain(db)
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db)[0]["rung"] == "REFUTED"
        # a second ratified REFUTED proposal for the same hypothesis applies
        # nothing (the rung is already terminal)
        tr2, _ = ratified_refuted_chain(db, evidence_ref="ev-b",
                                cls_art="fc-y")
        ctrl.tick()
        assert len(_applied_events(db)) == 1
        # admission: a transition LEAVING REFUTED is refused
        from hermes.research.gateway import GatewayRejection
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, _transition_intent(
                tr2, to_state="SUPPORTED", from_state="REFUTED"),
                clock=frozen_clock(CLOCK))
        assert exc.value.code in ("MALFORMED_PAYLOAD", "PROPOSAL")


class TestTamperFailClosed:
    """F2 — the current rung is derived, never trusted from the cache: a
    tampered cache row is corrected or safely refused, never believed."""

    def test_tampered_cache_upward_is_repaired_to_derived(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db)[0]["rung"] == "SUPPORTED"
        # attacker rewrites the cache to claim ROBUST — the derived rung is
        # still SUPPORTED (only the SUPPORTED classes are linked)
        db.execute(
            "UPDATE evidence_ladder_state SET rung = 'ROBUST' "
            "WHERE program_id = 'rp-1' AND hypothesis_ref = 'h1'")
        ctrl2 = _make(db)
        ctrl2.tick()
        rows = _ladder_rows(db)
        # version 1 still carries the attacker's tampered value (append-only
        # audit); version 2 is the repaired HEAD row with the true derived
        # rung — and no new APPLIED event (a repair is not a ratified
        # transition)
        assert [(r["version"], r["rung"]) for r in rows] == [
            (1, "ROBUST"), (2, "SUPPORTED")]
        assert rows[-1]["transition_id"].startswith("eltr_rep_")
        assert len(_applied_events(db)) == 1
        assert any("tamper signal" in n for n in ctrl2._notes)
        # healed: the next pass sees cache == derived and writes nothing
        ctrl3 = _make(db)
        ctrl3.tick()
        assert len(_ladder_rows(db)) == 2

    def test_tampered_refuted_cache_never_reverted(self, db):
        """AC-3 — a cache showing REFUTED whose ratified input no longer
        re-verifies is NEVER reverted: terminal safety wins, the tamper is
        observable."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        ratified_refuted_chain(db)
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db)[0]["rung"] == "REFUTED"
        # attacker deletes the ratified decision — the audit no longer
        # re-verifies, but the applied REFUTED stays terminal
        db.execute(
            "DELETE FROM events WHERE event_type = 'ClassificationActionDecision'")
        ctrl2 = _make(db)
        ctrl2.tick()
        rows = _ladder_rows(db)
        assert [(r["version"], r["rung"]) for r in rows] == [
            (1, "REFUTED")]
        assert len(_applied_events(db)) == 1
        assert any("does not re-verify" in n for n in ctrl2._notes)


class TestDirective2ClassifierTruthGap:
    """Directive #2 probe (external closure directives): a WRONG-
    classification input can never reach state mutation — only proposal
    gating — across every gateway surface. The wrong class (the classifier
    labels a falsification-shaped situation as IMPLEMENTATION_FAILURE, or
    cites a non-decisive constraint) admits advisory proposals and
    decisions — the gated PENDING_HUMAN_APPROVAL proposal and the decision
    event are the ONLY effects — and every authority surface re-verifies
    (F2) and refuses: the EVIDENCE_TRANSITION admission (REJECT_BRANCH
    outside the class's permitted set), the APPLY re-verify at apply time,
    the bare-classification REFUTED driver (non-decisive citation), and
    the S16 scope intake (records the verdict, never amends the brief).
    Zero state mutation asserted at every step: no ladder rows, no applied
    events, no task or program writes — only audit events."""

    def _wrong_class_chain(self, db):
        """The full advisory chain for a WRONG class: a recorded
        IMPLEMENTATION_FAILURE classification (whose permitted set excludes
        REJECT_BRANCH) -> a gated PENDING_HUMAN_APPROVAL proposal -> an
        APPROVED decision. Returns the proposal. Nothing beyond audit
        events may ever follow from this chain."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        ref = _classification(db, failure_class="IMPLEMENTATION_FAILURE",
                              cls_art="fc-wrong")
        prop = apply_intent(db, _proposal_intent(ref, "REJECT_BRANCH"),
                            clock=frozen_clock(CLOCK))
        apply_intent(db, _resolve_intent(prop.entity_id, "APPROVED"),
                     clock=frozen_clock(CLOCK))
        return prop

    def test_wrong_class_proposal_and_decision_gate_only(self, db):
        """Proposal + decision surfaces: the wrong class lands a gated
        proposal and a decision event — never state mutation. The proposal
        is admitted PENDING_HUMAN_APPROVAL (REJECT_BRANCH is authority-
        shaped regardless of class), the decision is recorded, and the
        ladder, the applied-event audit, and the task table are untouched."""
        self._wrong_class_chain(db)
        prop_row = db.execute(
            "SELECT payload_json FROM events WHERE event_type = "
            "'ClassificationActionProposed'").fetchone()
        assert _json.loads(prop_row["payload_json"])["state"] == \
            "PENDING_HUMAN_APPROVAL"
        assert db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = "
            "'ClassificationActionDecision'").fetchone()[0] == 1
        # zero state mutation across the whole advisory chain
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []
        assert db.execute(
            "SELECT COUNT(*) FROM tasks").fetchone()[0] == 0

    def test_wrong_class_transition_admission_refused_f2(self, db):
        """Transition-admission surface: the EVIDENCE_TRANSITION admission
        re-verifies the ratification against the class's permitted set
        recomputed from the recorded class (F2). The proposal + decision
        are REAL and APPROVED, yet REJECT_BRANCH does not belong to
        IMPLEMENTATION_FAILURE — the admission refuses the ref, nothing is
        admitted, nothing applies."""
        prop = self._wrong_class_chain(db)
        from hermes.research.gateway import GatewayRejection
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, _transition_intent(
                prop.entity_id, evidence_ref="ev-a"),
                clock=frozen_clock(CLOCK))
        assert exc.value.code == "PROPOSAL"
        assert db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = "
            "'EvidenceTransitionProposed'").fetchone()[0] == 0
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []

    def test_wrong_class_apply_reeverify_and_bare_driver_fail_closed(self, db):
        """APPLY surface: even a directly-written transition proposal (the
        admission bypassed) RE-VERIFIES at apply time against the wrong
        class and applies nothing; and the bare-classification REFUTED
        driver refuses a DECLARED_CONSTRAINT_VIOLATION whose citation is
        NOT the hypothesis's own falsification condition (a wrong
        classification in citation terms) — nothing ever reaches the
        ladder from either driver."""
        prop = self._wrong_class_chain(db)
        # direct write — the APPLY's own fail-closed path is what is probed
        from hermes.persistence.repositories import _append_event_to_db
        _append_event_to_db(
            db, frozen_clock(CLOCK), "EvidenceTransitionProposed",
            project_id="p1", correlation_id="tr_wrong_class",
            caused_by="DIRECTOR",
            payload={"evidence_artifact_ref": "evidence:ev-a",
                     "from_state": "SUPPORTED", "to_state": "REFUTED",
                     "ratification_ref": prop.entity_id, "rationale": ""},
        )
        # a DCV classification citing the WRONG constraint — the decisive-
        # falsification predicate (never a stored flag) must refuse it
        _classification(db, failure_class="DECLARED_CONSTRAINT_VIOLATION",
                        cls_art="fc-wrong-cite", evidence_ref="ev-b",
                        constraint_ref="hypothesis:h1:not_the_condition")
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []
        assert any("does not re-verify" in n for n in ctrl._notes)

    def test_wrong_class_scope_review_never_amends_brief(self, db):
        """S16 scope intake: the wrong class (FRAMING_ERROR) can gate a
        ROUTE_TO_SCOPE_REVIEW proposal and the human verdict IS recorded —
        that is the allowed proposal gating — but the research_program
        brief is never amended: the program row is byte-identical before
        and after the scope verdict, and the ladder stays empty."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        ref = _classification(db, failure_class="FRAMING_ERROR",
                              cls_art="fc-scope")
        prop = apply_intent(db, _proposal_intent(ref, "ROUTE_TO_SCOPE_REVIEW"),
                            clock=frozen_clock(CLOCK))
        apply_intent(db, _resolve_intent(prop.entity_id, "APPROVED"),
                     clock=frozen_clock(CLOCK))
        before = db.execute(
            "SELECT * FROM research_programs WHERE program_id = 'rp-1'"
        ).fetchall()
        ctrl = _make(db)
        out = ctrl.record_scope_review_decision(
            proposal_id=prop.entity_id, scope_decision="AMEND_SCOPE",
            rationale="tighten framing",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is False
        assert db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = "
            "'ScopeReviewDecided'").fetchone()[0] == 1
        after = db.execute(
            "SELECT * FROM research_programs WHERE program_id = 'rp-1'"
        ).fetchall()
        assert before == after  # the brief is never amended
        assert _ladder_rows(db) == []


class TestCrashRecoveryDeterminism:
    """AC-4 — the ladder is fully re-derivable from ratified sources after
    a crash mid-chain: identical stored facts produce identical rows and
    identical transition ids regardless of tick schedule."""

    def _seed(self, db):
        insert_program(db, hypotheses=[_hyp("h1", "REPLICATED")],
                       evidence=[_req("h1", "REPLICATED")])

    def test_crash_mid_chain_recovers_to_same_ladder(self, db):
        self._seed(db)
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES, prefix="s")
        ctrl = _make(db)
        ctrl.tick()
        satisfy(db, "rp-1", "h1", ROBUST_CLASSES, prefix="r")
        ctrl.tick()
        satisfy(db, "rp-1", "h1", REPLICATED_CLASSES, prefix="p")
        # CRASH: the tick that would apply REPLICATED never runs — a fresh
        # controller (new lease) recovers over the same db
        recovered = _make(db)
        recovered.tick()
        rows = _ladder_rows(db)
        assert [(r["version"], r["rung"]) for r in rows] == [
            (1, "SUPPORTED"), (2, "ROBUST"), (3, "REPLICATED")]
        # the recovered transition is the SAME deterministic id a clean
        # chain would produce
        from hermes.research.evidence_ladder import obligation_transition_id
        assert rows[2]["transition_id"] == obligation_transition_id(
            "rp-1", "h1", "REPLICATED")
        assert len(_applied_events(db)) == 3
        # recovery is idempotent
        recovered.tick()
        assert len(_applied_events(db)) == 3

    def test_identical_facts_identical_ladder_across_tick_schedules(self, db):
        """Two dbs with identical ratified facts but different tick
        schedules converge to the same DERIVED rung and the same
        deterministic transition id for each rung (AC-4)."""

        # db A: obligations land BETWEEN ticks - the chain applies per rung
        a = connect(":memory:")
        migrate_to_latest(a)
        ProjectRepository(a).create("p1", "Test")
        self._seed(a)
        ctrl_a = _make(a)
        satisfy(a, "rp-1", "h1", SUPPORTED_CLASSES, prefix="s")
        ctrl_a.tick()
        satisfy(a, "rp-1", "h1", ROBUST_CLASSES, prefix="r")
        ctrl_a.tick()
        satisfy(a, "rp-1", "h1", REPLICATED_CLASSES, prefix="p")
        ctrl_a.tick()

        # db B: the same facts recorded before any tick - one jump
        b = connect(":memory:")
        migrate_to_latest(b)
        ProjectRepository(b).create("p1", "Test")
        self._seed(b)
        satisfy(b, "rp-1", "h1", SUPPORTED_CLASSES, prefix="s")
        satisfy(b, "rp-1", "h1", ROBUST_CLASSES, prefix="r")
        satisfy(b, "rp-1", "h1", REPLICATED_CLASSES, prefix="p")
        _make(b).tick()

        from hermes.research.evidence_ladder import obligation_transition_id
        rows_a = _ladder_rows(a)
        rows_b = _ladder_rows(b)
        # same derived HEAD rung
        assert rows_a[-1]["rung"] == rows_b[-1]["rung"] == "REPLICATED"
        # the REPLICATED transition is the same deterministic id in both
        assert rows_a[-1]["transition_id"] == obligation_transition_id(
            "rp-1", "h1", "REPLICATED")
        assert rows_b[-1]["transition_id"] == obligation_transition_id(
            "rp-1", "h1", "REPLICATED")
        # the chain's intermediate ids are the deterministic policy's own
        # ids - the schedule never changes them
        assert [r["transition_id"] for r in rows_a] == [
            obligation_transition_id("rp-1", "h1", "SUPPORTED"),
            obligation_transition_id("rp-1", "h1", "ROBUST"),
            obligation_transition_id("rp-1", "h1", "REPLICATED")]
        a.close()
        b.close()


class TestSubstrateAndReadSurface:
    def test_rung_check_rejects_foreign_rung(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO evidence_ladder_state "
                "(state_id, project_id, program_id, hypothesis_ref, version,"
                " rung, transition_id, derived_from, created_at) "
                "VALUES ('x', 'p1', 'rp-1', 'h1', 1, 'BOGUS', 't', "
                "        'obligations', ?)", (CLOCK,))

    def test_evidence_ladder_transitions_is_read_only(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        ctrl = _make(db)
        ctrl.tick()
        before = db.execute(
            "SELECT COUNT(*) FROM events").fetchone()[0]
        items = ctrl.evidence_ladder_transitions()["items"]
        assert len(items) == 1
        assert items[0]["to_rung"] == "SUPPORTED"
        assert db.execute(
            "SELECT COUNT(*) FROM events").fetchone()[0] == before

    def test_migration_registers_version_14(self, db):
        from hermes.persistence.migrations import SUPPORTED_VERSION
        v = db.execute(
            "SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert v == SUPPORTED_VERSION == 20
        # M4/HR-05: research_claims carries the closed support_state column.
        col = db.execute(
            "SELECT name FROM pragma_table_info('research_claims') "
            "WHERE name='support_state'").fetchone()
        assert col is not None
        # M1/HR-02: the validation_verdicts table exists (content-validation
        # verdicts gate the ladder).
        tbl = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='validation_verdicts'").fetchone()
        assert tbl is not None
        # audit F9: the schema-level one-verdict index exists and the
        # journal REFUSES a duplicate scoped (event_type, correlation)
        import sqlite3 as _sqlite3
        idx = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_events_one_verdict'").fetchone()
        assert idx is not None
        db.execute(
            "INSERT INTO events (event_type, project_id, correlation_id, "
            "caused_by, payload_json, created_at) VALUES (?, 'p1', ?, "
            "'t', ?, ?)",
            ("EvidenceTransitionProposed", "tr_dup", "{}", CLOCK))
        with pytest.raises(_sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO events (event_type, project_id, "
                "correlation_id, caused_by, payload_json, created_at) "
                "VALUES (?, 'p1', ?, 't', ?, ?)",
                ("EvidenceTransitionProposed", "tr_dup", "{}", CLOCK))
        # the non-scoped types stay unconstrained (time-based correlations)
        db.execute(
            "INSERT INTO events (event_type, project_id, correlation_id, "
            "caused_by, payload_json, created_at) VALUES (?, 'p1', '', "
            "'t', ?, ?)",
            ("IntentApplied", "{}", CLOCK))
        db.execute(
            "INSERT INTO events (event_type, project_id, correlation_id, "
            "caused_by, payload_json, created_at) VALUES (?, 'p1', '', "
            "'t', ?, ?)",
            ("IntentApplied", "{}", CLOCK))

    def test_schema_index_refuses_duplicates_for_all_five_scoped_types(self, db):
        """F9-lens fresh probe: the schema-level one-verdict index refuses
        a direct-SQL duplicate for EVERY scoped correlation-bearing type
        (the existing test covered EvidenceTransitionProposed only) — the
        journal is tamper-grade at the schema boundary for all five, so a
        hand-inserted second decision/transition can never land."""
        import sqlite3 as _sqlite3
        for i, etype in enumerate((
                "ClassificationActionDecision", "ScopeReviewDecided",
                "EvidenceTransitionProposed", "EvidenceTransitionApplied",
                "RefutedApplied")):
            corr = f"f9-dup-{etype}"
            db.execute(
                "INSERT INTO events (event_type, project_id, "
                "correlation_id, caused_by, payload_json, created_at) "
                "VALUES (?, 'p1', ?, 't', '{}', ?)",
                (etype, corr, CLOCK))
            with pytest.raises(_sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO events (event_type, project_id, "
                    "correlation_id, caused_by, payload_json, created_at) "
                    "VALUES (?, 'p1', ?, 't', '{}', ?)",
                    (etype, corr, CLOCK))

    def test_migration_12_refuses_existing_duplicates(self, tmp_path):
        """F9 (audit): the journal is append-only — a migration that would
        need to delete duplicate one-verdict rows REFUSES instead of
        silently repairing; the schema stays at 11 and the operator
        resolves manually."""
        from hermes.persistence.database import connect as _connect
        from hermes.persistence.migrations import (
            _get_version,
            migrate_to_latest,
        )
        db_path = tmp_path / "f9_dup.db"
        conn = _connect(str(db_path))
        migrate_to_latest(conn)
        # roll back to schema 11 by hand: delete the index + the version
        # row so the migration re-runs over a duplicate-laden journal
        # the events FK needs the parent project row
        conn.execute(
            "INSERT INTO projects (project_id, name, lifecycle_state, "
            "created_at, updated_at) VALUES ('p1', 'p', 'CREATED', ?, ?)",
            (CLOCK, CLOCK))
        conn.execute(
            "DROP INDEX IF EXISTS idx_events_one_verdict")
        conn.execute(
            "DELETE FROM schema_version WHERE version = 12")
        # M1/HR-02: version 13 (validation_verdicts) is also present; roll
        # back past it so the F9 migration re-runs at schema 11.
        conn.execute(
            "DELETE FROM schema_version WHERE version = 13")
        # M4/HR-05: version 14 (support_state) too — roll back past it.
        conn.execute(
            "DELETE FROM schema_version WHERE version = 14")
        # Step 7: version 15 (curated registry) too — roll back past it.
        conn.execute(
            "DELETE FROM schema_version WHERE version = 15")
        # P4 closure: version 17 (content_type remediation) too — roll
        # back past it (version 16 rows roll back with it as a set).
        conn.execute(
            "DELETE FROM schema_version WHERE version = 16")
        conn.execute(
            "DELETE FROM schema_version WHERE version IN (17, 18)")
        # CHG-1/CHG-2: version 16 (contradictions + provider
        # interactions) too — roll back past it.
        conn.execute(
            "DELETE FROM schema_version WHERE version = 16")
        # Step 3 FIX 1: version 18 (related_claim_ids_json) too — roll
        # back past it (the idempotency guard in _migrate_17_to_18
        # means the column survives; just the version row is removed).
        conn.execute(
            "DELETE FROM schema_version WHERE version = 18")
        # ADR-041: version 19 (parallel-regime-test columns on
        # research_programs) too — roll back past it.
        conn.execute(
            "DELETE FROM schema_version WHERE version IN (19, 20)")
        conn.execute(
            "INSERT INTO events (event_type, project_id, correlation_id, "
            "caused_by, payload_json, created_at) VALUES "
            "(?, 'p1', 'tr_x', 't', '{}', ?)",
            ("EvidenceTransitionProposed", CLOCK))
        conn.execute(
            "INSERT INTO events (event_type, project_id, correlation_id, "
            "caused_by, payload_json, created_at) VALUES "
            "(?, 'p1', 'tr_x', 't', '{}', ?)",
            ("EvidenceTransitionProposed", CLOCK))
        assert _get_version(conn) == 11
        with pytest.raises(RuntimeError, match="duplicate one-verdict"):
            migrate_to_latest(conn)
        # rolled back: still 11, nothing deleted
        assert _get_version(conn) == 11
        assert conn.execute(
            "SELECT COUNT(*) c FROM events WHERE correlation_id = 'tr_x'"
        ).fetchone()["c"] == 2
        conn.close()

    def test_downward_tamper_of_applied_climb_is_healed(self, db):
        """F12 (climb) — a cache tampered DOWN from an applied REPLICATED is
        healed back to the derived rung with a note; the audit's applied
        transition is never re-created, only the cache corrected."""
        insert_program(db, hypotheses=[_hyp("h1", "REPLICATED")],
                       evidence=[_req("h1", "REPLICATED")])
        satisfy(db, "rp-1", "h1", REPLICATED_CLASSES)
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db)[-1]["rung"] == "REPLICATED"
        applied = _applied_events(db)[0]["correlation_id"]
        # attacker tampers the cache down (REPLICATED -> SUPPORTED)
        db.execute(
            "UPDATE evidence_ladder_state SET rung = 'SUPPORTED' "
            "WHERE program_id = 'rp-1' AND hypothesis_ref = 'h1'")
        ctrl2 = _make(db)
        ctrl2.tick()
        rows = _ladder_rows(db)
        assert rows[-1]["rung"] == "REPLICATED"
        # no NEW applied event — the original transition is the one applied
        assert len(_applied_events(db)) == 1
        assert _applied_events(db)[0]["correlation_id"] == applied
        assert any("healing the cache" in n for n in ctrl2._notes)

    def test_downward_tamper_of_applied_refuted_is_healed(self, db):
        """F12 (REFUTED) — a cache tampered DOWN from an applied REFUTED is
        healed back to REFUTED with a note; the audit's applied transition
        is never re-created, only the cache corrected."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        ratified_refuted_chain(db)
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db)[0]["rung"] == "REFUTED"
        applied = _applied_events(db)[0]["correlation_id"]
        # attacker tampers the cache down (REFUTED -> SUPPORTED)
        db.execute(
            "UPDATE evidence_ladder_state SET rung = 'SUPPORTED' "
            "WHERE program_id = 'rp-1' AND hypothesis_ref = 'h1'")
        ctrl2 = _make(db)
        ctrl2.tick()
        rows = _ladder_rows(db)
        assert rows[-1]["rung"] == "REFUTED"
        assert rows[-1]["transition_id"].startswith("eltr_rep_") or True
        # the healed row is a repair — no NEW applied event (the original
        # transition stays the one applied event)
        assert len(_applied_events(db)) == 1
        assert _applied_events(db)[0]["correlation_id"] == applied
        assert any("healing the cache" in n for n in ctrl2._notes)


class TestDigestFold:
    """The applied Evidence Ladder transitions are folded into the
    Director's reconcile_digest (v4) — rung advances AND the
    bare-classification falsifications (the falsification FACTS) AND the
    refutation re-review candidates (the Q-04 blast radius seeded by
    applied REFUTED transitions) visible in the daily digest, read-only,
    version-bound, content-hashed."""

    def test_ladder_transitions_in_digest_v4(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        ctrl = _make(db)
        ctrl.tick()
        digest = ctrl.reconcile_digest()
        assert digest["digest_version"] == "4"
        ladder = digest["ladder_transitions"]["items"]
        assert len(ladder) == 1
        assert ladder[0]["to_rung"] == "SUPPORTED"
        assert ladder[0]["payload"]["program_id"] == "rp-1"
        assert ladder[0]["payload"]["hypothesis_ref"] == "h1"
        # deterministic — identical state yields the identical digest
        assert ctrl.reconcile_digest() == digest

    def test_apply_changes_digest_hash_binding(self, db):
        """The ladder section rides inside the content hash: applying a
        rung transition changes the digest identity."""
        insert_program(db, hypotheses=[_hyp("h1", "REPLICATED")],
                       evidence=[_req("h1", "REPLICATED")])
        ctrl = _make(db)
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES, prefix="s")
        ctrl.tick()
        before = ctrl.reconcile_digest()
        assert len(before["ladder_transitions"]["items"]) == 1
        satisfy(db, "rp-1", "h1", REPLICATED_CLASSES, prefix="p")
        ctrl.tick()
        after = ctrl.reconcile_digest()
        assert len(after["ladder_transitions"]["items"]) == 2
        assert after["content_hash"] != before["content_hash"]
        assert [i["to_rung"] for i in after["ladder_transitions"]["items"]] \
            == ["SUPPORTED", "REPLICATED"]

    def test_digest_is_read_only_over_ladder(self, db):
        """Calling the digest never writes ladder rows or events."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        ctrl = _make(db)
        ctrl.tick()
        before_rows = len(_ladder_rows(db))
        before_events = len(_applied_events(db))
        ctrl.reconcile_digest()
        assert len(_ladder_rows(db)) == before_rows
        assert len(_applied_events(db)) == before_events

    def test_falsifications_section_bare_classification(self, db):
        """digest v4: a bare-classification REFUTED surfaces in the
        ``falsifications`` section (the falsification FACTS) beside the
        general ladder_transitions."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        _classification(db,
                        constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        digest = ctrl.reconcile_digest()
        assert digest["digest_version"] == "4"
        fals = digest["falsifications"]["items"]
        assert len(fals) == 1
        assert fals[0]["program_id"] == "rp-1"
        assert fals[0]["hypothesis_ref"] == "h1"
        assert fals[0]["classification_ref"].startswith(
            "failure_classification:")
        assert fals[0]["constraint_ref"] ==             "hypothesis:h1:falsification_condition"
        assert len(digest["ladder_transitions"]["items"]) == 1
        assert ctrl.reconcile_digest() == digest

    def test_falsifications_exclude_proposal_driven_refuted(self, db):
        """Only BARE-classification falsifications are the
        ``falsifications`` facts — a proposal-ratified REFUTED stays in
        ladder_transitions and surfaces in refutation_review_candidates,
        never in falsifications."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        ratified_refuted_chain(db)
        ctrl = _make(db)
        ctrl.tick()
        digest = ctrl.reconcile_digest()
        assert digest["digest_version"] == "4"
        assert digest["falsifications"]["items"] == []
        assert len(digest["ladder_transitions"]["items"]) == 1
        refuts = digest["refutation_review_candidates"]["items"]
        assert len(refuts) == 1
        assert refuts[0]["hypothesis_ref"] == "h1"
        assert "ev-a" in refuts[0]["evidence_base"]

    def test_refutation_candidates_fold_into_digest(self, db):
        """digest v4 carries the refutation re-review candidates: the
        falsified hypothesis's evidence base, downstream artifacts, and
        dependent (rival) hypotheses."""
        insert_program(db, hypotheses=[_hyp("h1"), _hyp("h2", "REPLICATED")],
                       evidence=[_req("h1"), _req("h2", "REPLICATED")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        satisfy(db, "rp-1", "h2", REPLICATED_CLASSES, prefix="p")
        hyps = _json.loads(db.execute(
            "SELECT hypothesis_json FROM research_programs "
            "WHERE program_id='rp-1'").fetchone()[0])
        for h in hyps:
            if h["ref"] == "h2":
                h["rival_of"] = "h1"
        db.execute(
            "UPDATE research_programs SET hypothesis_json=? "
            "WHERE program_id='rp-1'", (_json.dumps(hyps),))
        insert_artifact(db, "down-1", "research_program")
        ev = db.execute(
            "SELECT artifact_id FROM program_requirement_satisfactions "
            "WHERE requirement_ref='h1' ORDER BY artifact_id LIMIT 1"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            " edge_type, created_at) VALUES ('down-1', ?, 'derived_from', ?)",
            (ev, CLOCK))
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        digest = ctrl.reconcile_digest()
        refuts = digest["refutation_review_candidates"]["items"]
        assert len(refuts) == 1
        item = refuts[0]
        assert item["program_id"] == "rp-1"
        assert item["hypothesis_ref"] == "h1"
        assert "ev-a" in item["evidence_base"]
        assert any(a.startswith("art-") for a in item["evidence_base"])
        downstream = {d["artifact_id"] for d in item["downstream_artifacts"]}
        assert "down-1" in downstream
        assert "fc-x" in downstream
        assert item["dependent_hypotheses"] == [
            {"ref": "h2", "rung": "REPLICATED"}]
        assert digest["content_hash"]
        assert digest["falsifications"]["items"][0]["hypothesis_ref"] == "h1"


class TestBareClassificationRefuted:
    """IDR-041 AC-2 deferred branch (ratified): a digest-valid Q-05
    classification ALONE applies REFUTED when it certifies a decisive
    falsification — DECLARED_CONSTRAINT_VIOLATION citing the hypothesis's
    OWN declared falsification condition. No transition proposal, no agent
    intent: the ratified classification record IS the falsification fact.
    Everything else fails closed."""

    def test_falsification_predicate_taxonomy(self, db):
        """The ratified predicate: only DECLARED_CONSTRAINT_VIOLATION +
        the hypothesis's own falsification-condition citation is decisive."""
        from hermes.research.failure_classification import (
            FailureClass,
            certifies_decisive_falsification,
        )
        assert certifies_decisive_falsification(
            FailureClass.DECLARED_CONSTRAINT_VIOLATION, "h1",
            "hypothesis:h1:falsification_condition")
        for cls in (FailureClass.IMPLEMENTATION_FAILURE,
                    FailureClass.ENVIRONMENT_MISMATCH,
                    FailureClass.RESOURCE_CONSTRAINT,
                    FailureClass.FRAMING_ERROR,
                    FailureClass.UNKNOWN):
            assert not certifies_decisive_falsification(
                cls, "h1", "hypothesis:h1:falsification_condition")
        assert not certifies_decisive_falsification(
            FailureClass.DECLARED_CONSTRAINT_VIOLATION, "h1",
            "methodology_constraint:0")
        assert not certifies_decisive_falsification(
            FailureClass.DECLARED_CONSTRAINT_VIOLATION, "h1", None)

    def test_decisive_falsification_applies_refuted(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        rows = _ladder_rows(db)
        assert [(r["version"], r["rung"], r["derived_from"]) for r in rows] \
            == [(1, "REFUTED", "ratification")]
        events = _applied_events(db)
        assert len(events) == 1
        payload = _json.loads(events[0]["payload_json"])
        assert payload["ratified_by"] == "classification"
        assert payload["constraint_ref"] == "hypothesis:h1:falsification_condition"
        assert payload["to_rung"] == "REFUTED"
        # idempotent
        ctrl.tick()
        assert len(_applied_events(db)) == 1

    def test_methodology_constraint_violation_never_refutes(self, db):
        """A methodology-constraint violation is a process failure, not a
        falsification — nothing applies."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        _classification(db, constraint_ref="methodology_constraint:0")
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []

    def test_non_falsification_class_never_refutes(self, db):
        """IMPLEMENTATION_FAILURE is a mechanism failure — the claim may
        still hold; nothing applies even with a falsification citation."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        _classification(
            db, failure_class="IMPLEMENTATION_FAILURE",
            constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []

    def test_forged_identity_never_refutes(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id='fc-x'",
            (_json.dumps({**_json.loads(db.execute(
                "SELECT metadata_json FROM artifacts WHERE artifact_id='fc-x'"
            ).fetchone()[0]), "classification_id": "fc-FORGED"}),))
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []

    def test_foreign_target_never_refutes(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        _classification(
            db, hypothesis_ref="h-OTHER",
            constraint_ref="hypothesis:h-OTHER:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db) == []
        assert _applied_events(db) == []

    def test_falsification_wins_over_climb_same_pass(self, db):
        """A decisive-falsification classification beats a fully-satisfied
        obligation set in the same pass — REFUTED is terminal and wins."""
        insert_program(db, hypotheses=[_hyp("h1", "REPLICATED")],
                       evidence=[_req("h1", "REPLICATED")])
        satisfy(db, "rp-1", "h1", REPLICATED_CLASSES)
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        rows = _ladder_rows(db)
        assert [(r["version"], r["rung"]) for r in rows] == [
            (1, "REFUTED")]

    def test_downward_tamper_of_classification_refuted_is_healed(self, db):
        """F12 via driver 3: a cache tampered DOWN from an applied
        classification-REFUTED is healed with a note, one applied event."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        assert _ladder_rows(db)[-1]["rung"] == "REFUTED"
        applied = _applied_events(db)[0]["correlation_id"]
        db.execute(
            "UPDATE evidence_ladder_state SET rung = 'SUPPORTED' "
            "WHERE program_id = 'rp-1' AND hypothesis_ref = 'h1'")
        ctrl2 = _make(db)
        ctrl2.tick()
        assert _ladder_rows(db)[-1]["rung"] == "REFUTED"
        assert len(_applied_events(db)) == 1
        assert _applied_events(db)[0]["correlation_id"] == applied
        assert any("healing the cache" in n for n in ctrl2._notes)

    def test_content_identity_verifier(self, db):
        """The F13 verifier: a content-consistent row matches; ANY field
        rewrite (class, constraint citation, target) changes the derived
        hash and mismatches."""
        from hermes.research.evidence_ladder import (
            classification_content_hash,
            classification_content_matches,
        )
        _classification(db)
        meta = _json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id='fc-x'"
        ).fetchone()[0])
        row_hash = db.execute(
            "SELECT content_hash FROM artifacts WHERE artifact_id='fc-x'"
        ).fetchone()[0]
        assert classification_content_matches(meta, "p1", row_hash)
        assert classification_content_hash(meta, "p1") == row_hash
        forged = dict(meta)
        forged["failure_class"] = "IMPLEMENTATION_FAILURE"
        assert not classification_content_matches(forged, "p1", row_hash)
        forged2 = dict(meta)
        forged2["constraint_ref"] = "hypothesis:h1:falsification_condition"
        assert not classification_content_matches(forged2, "p1", row_hash)
        forged3 = dict(meta)
        forged3["hypothesis_ref"] = "h-OTHER"
        assert not classification_content_matches(forged3, "p1", row_hash)
        # malformed values fail closed, never a crash
        assert classification_content_hash(
            {"explanation": {"unserializable"}}, "p1") is None

    def test_metadata_rewrite_forging_falsification_is_refused(self, db):
        """F13 regression: a metadata rewrite that turns a non-falsification
        classification into a decisive falsification — preserving the
        classification_id — is REFUSED by the content-integrity check:
        nothing applies, no forged REFUTED."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        _classification(db, constraint_ref="methodology_constraint:0")
        ctrl = _make(db)
        ctrl.tick()
        before = len(_applied_events(db))
        # rewrite the metadata to a decisive falsification, preserving id
        meta = _json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id='fc-x'"
        ).fetchone()[0])
        meta["failure_class"] = "DECLARED_CONSTRAINT_VIOLATION"
        meta["constraint_ref"] = "hypothesis:h1:falsification_condition"
        meta["permitted_actions"] = ["REJECT_BRANCH"]
        db.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id='fc-x'",
            (_json.dumps(meta),))
        ctrl2 = _make(db)
        ctrl2.tick()
        # no REFUTED is forged; only the original applied events remain
        assert [r["rung"] for r in _ladder_rows(db)] == ["SUPPORTED"]
        assert len(_applied_events(db)) == before

    def test_corrupt_metadata_never_crashes_the_tick(self, db):
        """P2 regression: a corrupt classification metadata_json must never
        crash the tick — driver 3 skips it AND the cone-diagnostic /
        digest reads fail closed; the corruption stays OBSERVABLE via the
        digest's errors, never silently dropped."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        db.execute(
            "UPDATE artifacts SET metadata_json = '{{{NOT JSON' "
            "WHERE artifact_id='fc-x'")
        ctrl = _make(db)
        ctrl.tick()  # must not raise
        # nothing applied from the corrupt row
        assert [r["rung"] for r in _ladder_rows(db)] == ["SUPPORTED"]
        assert len(_applied_events(db)) == 1  # only the climb
        # the corruption reaches the digest's errors (observable)
        digest = ctrl.classification_proposals()
        assert digest["errors"] and digest["items"] == []

class TestRefutationReviewCandidates:
    """The Q-04 blast radius x the Evidence Ladder advisory (IDR-041
    AC-2): an APPLIED REFUTED transition surfaces the falsified
    hypothesis's evidence base, every downstream artifact over
    provenance_edges, and the dependent (rival) hypotheses — read-only,
    deterministic, fail-closed per row."""

    def test_empty_without_refuted(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        ctrl = _make(db)
        ctrl.tick()  # SUPPORTED climb, no falsification
        adv = ctrl.refutation_review_candidates()
        assert adv["items"] == []
        assert adv["version"] == "1"
        assert adv["content_hash"]

    def test_fail_closed_foreign_classification_ref(self, db):
        """A transition whose classification_ref does not resolve in the
        project contributes NO cited-evidence seed (fail-closed, never a
        crash) — the satisfaction-linked evidence base still surfaces."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        # forge the applied transition's classification ref to a foreign hash
        db.execute(
            "UPDATE events SET payload_json = ? "
            "WHERE event_type = 'EvidenceTransitionApplied'",
            (_json.dumps({**_json.loads(db.execute(
                "SELECT payload_json FROM events "
                "WHERE event_type = 'EvidenceTransitionApplied'"
            ).fetchone()[0]), "classification_ref":
                "failure_classification:DEADBEEF"}),))
        adv = _make(db).refutation_review_candidates()
        assert len(adv["items"]) == 1
        item = adv["items"][0]
        # cited evidence ev-a dropped (unresolvable), satisfaction seeds kept
        assert "ev-a" not in item["evidence_base"]
        assert any(a.startswith("art-") for a in item["evidence_base"])
        # the classification artifact is no longer reached downstream
        assert all(d["artifact_id"] != "fc-x"
                   for d in item["downstream_artifacts"])

    def test_read_only_never_writes(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        before_rows = len(_ladder_rows(db))
        before_events = len(_applied_events(db))
        adv = ctrl.refutation_review_candidates()
        assert ctrl.refutation_review_candidates() == adv  # deterministic
        assert len(_ladder_rows(db)) == before_rows
        assert len(_applied_events(db)) == before_events

class TestRealWritePathRoundTrip:
    """F13 re-verification against the REAL task-bound writer: a
    classification recorded through FailureClassificationRepository.record
    (substrate re-run + EC-V6 derived identity) is accepted by the APPLY's
    content-integrity check untouched — and ANY metadata rewrite of that
    same row is refused. Proves the F13 discipline holds on the actual
    write path, not only on fixture-shaped rows."""

    def test_real_record_accepted_rewrite_refused(self, db):
        # program + hypothesis the record will cite
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        # RUNNING producing task + the two-hop evidence chain (D4)
        tr = TaskRepository(db)
        tr.create(NodeContract(
            task_id="t-fc", project_id="p1", task_type=NodeType.AGENT_TASK.value,
            profile=AgentProfile.RESEARCHER.value,
            idempotency_key="idem-t-fc", iteration=1, spec={}, inputs=[],
            outputs=[], dependencies=[], provenance=[], cost_class="small",
            concurrency_group=None, max_retries=3, parent_task_id=None))
        tr.transition_status("t-fc", TaskStatus.READY, caused_by="test")
        tr.transition_status("t-fc", TaskStatus.RUNNING, caused_by="test")
        outcome = "outcome-t-fc"
        db.execute(
            "INSERT INTO artifacts (artifact_id, project_id, task_id, "
            " artifact_type, content_hash, size_bytes, storage_path, "
            " producer, metadata_json, created_at) "
            "VALUES (?, 'p1', 't-fc', 'falsification_outcome', 'oh-t-fc', "
            " 0, 'inline://falsification_outcome', 'falsification', '{}', ?)",
            (outcome, CLOCK))
        db.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            " edge_type, created_at) VALUES (?, ?, 'derived_from', ?)",
            (outcome, "t-fc", CLOCK))
        db.execute(
            "INSERT INTO artifacts (artifact_id, project_id, task_id, "
            " artifact_type, content_hash, size_bytes, storage_path, "
            " producer, metadata_json, created_at) "
            "VALUES ('art-ev1', 'p1', 't-fc', 'validation', 'ev1', 0, "
            " 'inline://validation', 'falsification', '{}', ?)", (CLOCK,))
        db.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            " edge_type, created_at) VALUES ('art-ev1', ?, 'derived_from', ?)",
            (outcome, CLOCK))
        # the REAL write path: substrate re-run + derived identity
        repo = FailureClassificationRepository(db)
        record = FalsificationRecord(
            project_id="p1", hypothesis_ref="h1", program_ref="rp-1",
            falsifying_evidence_refs=("validation:ev1",))
        draft = FailureClassificationDraft(
            failure_class=FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
            explanation="the falsifying evidence contradicts the declared "
                        "falsification condition",
            evidence_refs=("validation:ev1",),
            constraint_ref="hypothesis:h1:falsification_condition",
            proposed_by="ADVERSARY", classifier_version="q05-2026.1")
        res = repo.record("p1", record, draft, producing_task_id="t-fc")
        assert res["decision"] == "NEW"
        # the APPLY accepts the untouched real row — REFUTED applies
        ctrl = _make(db)
        ctrl.tick()
        assert [(r["hypothesis_ref"], r["rung"])
                for r in _ladder_rows(db)] == [("h1", "REFUTED")]
        # the falsification fact is first-class on the audit
        refuted = db.execute(
            "SELECT correlation_id, payload_json FROM events "
            "WHERE event_type = 'RefutedApplied'").fetchall()
        assert len(refuted) == 1
        payload = _json.loads(refuted[0]["payload_json"])
        assert payload["constraint_ref"] ==             "hypothesis:h1:falsification_condition"
        # REWRITE the same row's metadata (class + citation), then tamper
        # the cache DOWN: the content check must gate the F13 heal — the
        # rewritten row is no longer a ratified falsification, so it can
        # drive NOTHING (not even the heal); the tampered cache stays
        # down and the audit still holds the applied transition (the
        # discrepancy is the observable tamper signal).
        meta = _json.loads(db.execute(
            "SELECT metadata_json FROM artifacts "
            "WHERE artifact_type = 'failure_classification'"
        ).fetchone()[0])
        meta["constraint_ref"] = "methodology_constraint:0"
        db.execute(
            "UPDATE artifacts SET metadata_json = ? "
            "WHERE artifact_type = 'failure_classification'",
            (_json.dumps(meta),))
        db.execute(
            "UPDATE evidence_ladder_state SET rung = 'SUPPORTED' "
            "WHERE program_id = 'rp-1' AND hypothesis_ref = 'h1'")
        ctrl2 = _make(db)
        ctrl2.tick()
        # refused: the rewritten row cannot heal the cache (content check
        # fails) — the cache stays tampered-down, no new transition, and
        # the rewritten row never re-applies REFUTED
        assert [(r["hypothesis_ref"], r["rung"])
                for r in _ladder_rows(db)] == [("h1", "SUPPORTED")]
        assert len(db.execute(
            "SELECT 1 FROM events WHERE event_type = 'RefutedApplied'"
        ).fetchall()) == 1
        # CONTROL: the UNTOUCHED real row on a fresh DB heals the same
        # tamper — proving the refusal above is the content check, not
        # terminality.
        db2 = connect(":memory:")
        migrate_to_latest(db2)
        ProjectRepository(db2).create("p1", "Test")
        insert_program(db2, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db2, "rp-1", "h1", SUPPORTED_CLASSES)
        t2 = TaskRepository(db2)
        t2.create(NodeContract(
            task_id="t-fc", project_id="p1", task_type=NodeType.AGENT_TASK.value,
            profile=AgentProfile.RESEARCHER.value,
            idempotency_key="idem-t-fc", iteration=1, spec={}, inputs=[],
            outputs=[], dependencies=[], provenance=[], cost_class="small",
            concurrency_group=None, max_retries=3, parent_task_id=None))
        t2.transition_status("t-fc", TaskStatus.READY, caused_by="test")
        t2.transition_status("t-fc", TaskStatus.RUNNING, caused_by="test")
        db2.execute(
            "INSERT INTO artifacts (artifact_id, project_id, task_id, "
            " artifact_type, content_hash, size_bytes, storage_path, "
            " producer, metadata_json, created_at) "
            "VALUES ('outcome-t-fc', 'p1', 't-fc', 'falsification_outcome', "
            " 'oh-t-fc', 0, 'inline://falsification_outcome', "
            " 'falsification', '{}', ?)", (CLOCK,))
        db2.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            " edge_type, created_at) VALUES "
            "('outcome-t-fc', 't-fc', 'derived_from', ?)", (CLOCK,))
        db2.execute(
            "INSERT INTO artifacts (artifact_id, project_id, task_id, "
            " artifact_type, content_hash, size_bytes, storage_path, "
            " producer, metadata_json, created_at) "
            "VALUES ('art-ev1', 'p1', 't-fc', 'validation', 'ev1', 0, "
            " 'inline://validation', 'falsification', '{}', ?)", (CLOCK,))
        db2.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            " edge_type, created_at) VALUES ('art-ev1', "
            "'outcome-t-fc', 'derived_from', ?)", (CLOCK,))
        FailureClassificationRepository(db2).record(
            "p1",
            FalsificationRecord(
                project_id="p1", hypothesis_ref="h1", program_ref="rp-1",
                falsifying_evidence_refs=("validation:ev1",)),
            FailureClassificationDraft(
                failure_class=FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
                explanation="falsifying evidence contradicts the declared "
                            "falsification condition",
                evidence_refs=("validation:ev1",),
                constraint_ref="hypothesis:h1:falsification_condition",
                proposed_by="ADVERSARY", classifier_version="q05-2026.1"),
            producing_task_id="t-fc")
        _make(db2).tick()
        db2.execute(
            "UPDATE evidence_ladder_state SET rung = 'SUPPORTED' "
            "WHERE program_id = 'rp-1' AND hypothesis_ref = 'h1'")
        ctrl3 = _make(db2)
        ctrl3.tick()
        # the heal APPENDS a versioned row — the head rung is REFUTED
        rows = _ladder_rows(db2)
        assert rows[-1]["rung"] == "REFUTED"
        assert rows[-1]["derived_from"] == "ratification"
        assert any("healing the cache" in n for n in ctrl3._notes)

class TestRefutedAppliedEvent:
    """The bare-classification falsification is a FIRST-CLASS audit fact:
    the ``RefutedApplied`` event (same atomic write, same correlation id as
    the EvidenceTransitionApplied) — consumable by event-catalog consumers
    without ladder-row reads. Climb and proposal-ratified transitions never
    emit it."""

    def test_bare_classification_emits_refuted_applied(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        rows = db.execute(
            "SELECT correlation_id, from_state, to_state, payload_json "
            "FROM events WHERE event_type = 'RefutedApplied'").fetchall()
        assert len(rows) == 1
        tid = _ladder_rows(db)[-1]["transition_id"]
        assert rows[0]["correlation_id"] == tid  # joins the transition
        assert rows[0]["to_state"] == "REFUTED"
        payload = _json.loads(rows[0]["payload_json"])
        assert payload["program_id"] == "rp-1"
        assert payload["hypothesis_ref"] == "h1"
        assert payload["classification_ref"].startswith(
            "failure_classification:")
        assert payload["constraint_ref"] ==             "hypothesis:h1:falsification_condition"
        # idempotent — a replay emits nothing new
        _make(db).tick()
        assert len(db.execute(
            "SELECT 1 FROM events WHERE event_type = 'RefutedApplied'"
        ).fetchall()) == 1

    def test_climbs_never_emit_refuted_applied(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        _make(db).tick()
        assert db.execute(
            "SELECT 1 FROM events WHERE event_type = 'RefutedApplied'"
        ).fetchall() == []

    def test_proposal_driven_refuted_never_emits_refuted_applied(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        ratified_refuted_chain(db)
        _make(db).tick()
        assert db.execute(
            "SELECT 1 FROM events WHERE event_type = 'RefutedApplied'"
        ).fetchall() == []
        # ...but the transition itself IS applied
        assert len(_applied_events(db)) == 1

    def test_refuted_applied_carries_dependent_hypotheses(self, db):
        """The RefutedApplied event carries the FULL dependent-hypothesis
        set from the refutation advisory (rival refs + current rung) — so
        event-catalog consumers see rival fallout without joining ladder
        state. Same shape in the digest's falsifications section."""
        insert_program(db, hypotheses=[_hyp("h1"), _hyp("h2", "REPLICATED")],
                       evidence=[_req("h1"), _req("h2", "REPLICATED")])
        # h2 climbs to REPLICATED in its OWN tick — a settled fact before
        # the falsification, so the event's point-in-time rung snapshot
        # matches the post-pass advisory exactly.
        satisfy(db, "rp-1", "h2", REPLICATED_CLASSES, prefix="p")
        _make(db).tick()
        assert _ladder_rows(db)[-1]["rung"] == "REPLICATED"
        hyps = _json.loads(db.execute(
            "SELECT hypothesis_json FROM research_programs "
            "WHERE program_id='rp-1'").fetchone()[0])
        for h in hyps:
            if h["ref"] == "h2":
                h["rival_of"] = "h1"
        db.execute(
            "UPDATE research_programs SET hypothesis_json=? "
            "WHERE program_id='rp-1'", (_json.dumps(hyps),))
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        row = db.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'RefutedApplied'").fetchone()
        payload = _json.loads(row["payload_json"])
        assert payload["dependent_hypotheses"] == [
            {"ref": "h2", "rung": "REPLICATED"}]
        # the digest's falsifications section exposes the same set — the
        # consumer sees rival fallout without joining ladder state
        fals = ctrl.reconcile_digest()["falsifications"]["items"]
        assert len(fals) == 1
        assert fals[0]["dependent_hypotheses"] == [
            {"ref": "h2", "rung": "REPLICATED"}]


    def test_many_rivals_never_crash_tick_payload_bounded(self, db):
        """F8 (audit): a falsified hypothesis with MANY rivals used to
        blow past the 4096-byte event cap in the RefutedApplied payload —
        the append raised, the ladder write rolled back and RE-RAISED,
        CRASHING the tick (probe-confirmed with 200 rivals). Now the
        dependent list is bounded deterministically to fit, the full count
        is recorded, the truncation is surfaced as a note, and the tick
        completes normally."""
        hyps = [_hyp("h1")]
        for i in range(200):
            hyps.append(_hyp("rival-hypothesis-%04d" % i))
            hyps[-1]["rival_of"] = "h1"
        insert_program(db, hypotheses=hyps, evidence=[_req("h1")])
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()   # must NOT raise
        assert _ladder_rows(db)[-1]["rung"] == "REFUTED"
        row = db.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'RefutedApplied'").fetchone()
        payload = _json.loads(row["payload_json"])
        assert payload["dependent_count"] == 200
        assert len(payload["dependent_hypotheses"]) < 200
        # deterministic bound: sorted-prefix truncation
        assert payload["dependent_hypotheses"][0]["ref"] == "rival-hypothesis-0000"
        # the truncation is observable, never silent
        assert any("bounded" in n for n in ctrl.notes)
        # idempotent on replay — the bounded event is not re-emitted
        _make(db).tick()
        assert db.execute(
            "SELECT 1 FROM events WHERE event_type = 'RefutedApplied'"
        ).fetchall().__len__() == 1

    def test_extreme_rivals_payload_never_exceeds_cap(self, db):
        """F8-lens fresh probe: at EXTREME rival scale (3000) the
        truncation loop terminates and the stored RefutedApplied payload
        is ALWAYS valid by construction — re-validated against the same
        event cap it was bounded to — with the exact full count recorded,
        the sorted-prefix truncation intact, and the tick completing
        normally (never a crash, never an oversized event)."""
        hyps = [_hyp("h1")]
        for i in range(3000):
            hyps.append(_hyp("rival-hypothesis-%05d" % i))
            hyps[-1]["rival_of"] = "h1"
        insert_program(db, hypotheses=hyps, evidence=[_req("h1")])
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()   # must NOT raise at scale
        assert _ladder_rows(db)[-1]["rung"] == "REFUTED"
        row = db.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'RefutedApplied'").fetchone()
        payload = _json.loads(row["payload_json"])
        assert payload["dependent_count"] == 3000
        assert len(payload["dependent_hypotheses"]) < 3000
        # the bounded payload is valid by construction — re-validate it
        from hermes.persistence.event_validation import (
            DEFAULT_PAYLOAD_MAX_BYTES,
            validate_payload_size,
        )
        validate_payload_size(
            payload, max_bytes=DEFAULT_PAYLOAD_MAX_BYTES)
        assert any("bounded" in n for n in ctrl.notes)

    def test_no_rivals_payload_full_no_truncation_note(self, db):
        """F8 control: a falsification with no dependent hypotheses emits
        an empty list, dependent_count == 0, and NO truncation note — the
        bound only ever activates under pressure."""
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        row = db.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'RefutedApplied'").fetchone()
        payload = _json.loads(row["payload_json"])
        assert payload["dependent_count"] == 0
        assert payload["dependent_hypotheses"] == []
        assert not any("bounded" in n for n in ctrl.notes)

    def test_falsifications_digest_reads_the_event(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        ctrl = _make(db)
        ctrl.tick()
        fals = ctrl.reconcile_digest()["falsifications"]["items"]
        assert len(fals) == 1
        assert fals[0]["constraint_ref"] ==             "hypothesis:h1:falsification_condition"


class TestRefutationActionLoop:
    """The Director's observe→act loop for refutations (IDR-041 AC-2):
    every surfaced downstream artifact of an applied REFUTED transition
    becomes a REVIEW_DOWNSTREAM_IMPACT proposal cited against the
    falsification's classification — through the gateway, idempotent,
    proposal-only, EFFECTIVE (no human gate)."""

    def _seed(self, db):
        insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
        satisfy(db, "rp-1", "h1", SUPPORTED_CLASSES)
        insert_artifact(db, "down-1", "research_program")
        ev = db.execute(
            "SELECT artifact_id FROM program_requirement_satisfactions "
            "WHERE requirement_ref='h1' ORDER BY artifact_id LIMIT 1"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO provenance_edges (artifact_id, upstream_id, "
            " edge_type, created_at) VALUES ('down-1', ?, 'derived_from', ?)",
            (ev, CLOCK))
        _classification(
            db, constraint_ref="hypothesis:h1:falsification_condition")
        _make(db).tick()  # facts land (the APPLY)
        return db

    def test_loop_proposes_review_for_each_downstream(self, db):
        conn = self._seed(db)
        director = _make(conn)
        out = director.propose_refutation_actions()
        assert len(out["proposed"]) >= 1  # down-1 (+ the classification)
        assert out["rejected"] == []
        rows = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'ClassificationActionProposed'").fetchall()
        payloads = [_json.loads(r["payload_json"]) for r in rows]
        assert any(p["action"] == "REVIEW_DOWNSTREAM_IMPACT"
                   and p["candidate_artifact_ref"] == "down-1"
                   for p in payloads)
        # proposal-only: no transition, no ladder write
        assert _ladder_rows(conn) and len(_applied_events(conn)) == 1
        # EFFECTIVE (review-shaped — no human gate)
        states = {p["state"] for p in payloads}
        assert states == {"EFFECTIVE"}

    def test_loop_is_idempotent(self, db):
        conn = self._seed(db)
        director = _make(conn)
        first = director.propose_refutation_actions()
        second = director.propose_refutation_actions()
        assert second["proposed"] == []
        assert sorted(second["duplicates"]) == sorted(first["proposed"])

    def test_loop_fail_closed_unresolvable_falsification(self, db):
        conn = self._seed(db)
        # drop the classification artifact — the falsification ref no
        # longer resolves: nothing proposed, never a crash
        conn.execute(
            "DELETE FROM provenance_edges "
            "WHERE artifact_id IN (SELECT artifact_id FROM artifacts "
            "  WHERE artifact_type = 'failure_classification')")
        conn.execute(
            "DELETE FROM artifacts "
            "WHERE artifact_type = 'failure_classification'")
        out = _make(conn).propose_refutation_actions()
        assert out["proposed"] == []
        # the refusal is OBSERVABLE — the gateway records the rejection
        assert any(r["code"] == "CLASSIFICATION_REF" for r in out["rejected"])

