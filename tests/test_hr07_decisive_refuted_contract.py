"""HR-07 — the decisive REFUTED input contract (semantic safety tests).

Pins the exact epistemic inputs allowed to produce a decisive REFUTED
transition, and proves that the prohibited inputs never do.

The invariant: the system MUST NOT treat a declaration, a citation string,
an explanation, an artifact type, an implementation failure, a resource
failure, an environment mismatch, or UNKNOWN as decisive scientific
falsification by themselves. Only the complete current contract produces
REFUTED:

    a digest-valid, content-consistent Q-05 classification
        whose class is DECLARED_CONSTRAINT_VIOLATION
        citing the hypothesis's OWN declared falsification condition
        bound to the project's CURRENT (head) program
        whose hypothesis dereferences in that program
    → REFUTED

Semantic safety cases (brief §8):
  A  execution/implementation failure      → NOT REFUTED
  B  resource exhaustion                    → NOT REFUTED
  C  environment mismatch                   → NOT REFUTED
  D  valid decisive falsification           → MAY REFUTED (positive path)
  E  result satisfies the condition         → NOT REFUTED
  F  untestable / unknown                   → NOT REFUTED
  G  forged result (content/hash mismatch)  → NOT REFUTED

Plus the HR-07 head-binding hardening: a classification citing a SUPERSEDED
program never applies REFUTED (bare path and proposal path), while the
current head still does.

Honest gap (brief §9): the current system has no executed
falsification-RESULT type. The decisive input today is a ratified
classification record — architecturally constrained (class + citation +
content integrity + head binding + dereference) but still dependent on a
future validated falsification-result substrate. These tests pin the
contract that substrate must satisfy; they do not pretend the
classification is an executed experiment.
"""
from __future__ import annotations

import json as _json

import pytest

from hermes.core import frozen_clock
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    OperatorCredentialRepository,
    ProjectRepository,
)
from hermes.research.controller import Controller
from hermes.research.evidence_ladder import classification_content_hash
from hermes.research.failure_classification import (
    FailureClass,
    certifies_decisive_falsification,
    permitted_actions_for,
)
from hermes.research.gateway import GatewayRejection, apply_intent
from hermes.research.programs import LADDER_OBLIGATIONS, LadderTarget

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1"

FAILURE_CLASSIFICATION_ARTIFACT_TYPE = "failure_classification"

# The five classes that MUST NOT directly produce REFUTED (brief §4).
FORBIDDEN_CLASSES = (
    FailureClass.IMPLEMENTATION_FAILURE,
    FailureClass.ENVIRONMENT_MISMATCH,
    FailureClass.RESOURCE_CONSTRAINT,
    FailureClass.FRAMING_ERROR,
    FailureClass.UNKNOWN,
)


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    yield conn
    conn.close()


def _make(conn, **kwargs):
    return Controller(conn, project_id="p1", clock=frozen_clock(CLOCK),
                      **kwargs)


def _hyp(ref, ladder="SUPPORTED"):
    return {"ref": ref, "ladder_target": ladder,
            "falsification_condition": "fc", "rival_of": None,
            "rival_status": None}


def _req(claim_ref, ladder="SUPPORTED"):
    artifacts, _ = LADDER_OBLIGATIONS[LadderTarget(ladder)]
    return {"claim_ref": claim_ref, "ladder_target": ladder,
            "required_artifacts": list(artifacts), "associated_gates": []}


def insert_program(db, program_id="rp-1", *, hypotheses=(), evidence=(),
                   version=1, supersedes_id=None):
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, ?, ?, ?, 'b', 'o', 'c1', 'p1', '1', 'ih', ?,
                   '[]', '[]', ?, '[]', '[]', NULL, 'director', NULL, ?)""",
        (program_id, "p1", version, "ch-" + program_id, supersedes_id,
         _json.dumps(list(hypotheses)), _json.dumps(list(evidence)), CLOCK),
    )


def insert_artifact(db, artifact_id, artifact_type, *, meta=None,
                    project="p1"):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, NULL, ?, ?, 1, 'x', 't', ?, ?)""",
        (artifact_id, project, artifact_type, "ch-" + artifact_id,
         _json.dumps(meta or {}), CLOCK),
    )


def classification_row(db, *, cls_art="fc-x", failure_class="DECLARED_"
                       "CONSTRAINT_VIOLATION", program_ref="rp-1",
                       hypothesis_ref="h1", constraint_ref=None,
                       evidence_ref="ev-a", project="p1",
                       hash_project=None):
    """A digest-valid, CONTENT-CONSISTENT classification row (the
    bare-classification REFUTED driver's input shape). The content_hash is
    the derived identity, so the APPLY's F13 content-integrity check
    re-derives it. Returns the ``failure_classification:<hash>`` ref.

    ``project`` places the artifact rows (evidence + classification) in a
    specific project; ``hash_project`` (default: ``project``) is the
    identity the content hash is derived under — the foreign-project
    fixtures use the split to prove the cross-project boundary."""
    insert_artifact(db, evidence_ref, "evidence", project=project)
    meta = {
        "schema_version": "1",
        "failure_class": failure_class,
        "hypothesis_ref": hypothesis_ref,
        "program_ref": program_ref,
        "classification_id": cls_art,
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": ["evidence:" + evidence_ref],
        "constraint_ref": constraint_ref,
        "failed_mechanism_ref": None,
        "regime_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": "hr07 test",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": [],
        "permitted_actions": sorted(
            a.value for a in permitted_actions_for(
                FailureClass(failure_class))),
    }
    content_hash = classification_content_hash(
        meta, hash_project if hash_project is not None else project)
    insert_artifact(db, cls_art, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
                    meta=meta, project=project)
    db.execute("UPDATE artifacts SET content_hash = ? WHERE artifact_id = ?",
               (content_hash, cls_art))
    return "failure_classification:" + (content_hash or "")


def _ladder_rows(db):
    return [dict(r) for r in db.execute(
        "SELECT program_id, hypothesis_ref, version, rung, derived_from "
        "FROM evidence_ladder_state ORDER BY program_id, hypothesis_ref, "
        "version")]


def _applied_events(db):
    return [dict(r) for r in db.execute(
        "SELECT correlation_id, from_state, to_state, payload_json "
        "FROM events WHERE event_type = 'EvidenceTransitionApplied' "
        "ORDER BY event_id")]


def _tick_and_assert_no_refuted(db):
    ctrl = _make(db)
    ctrl.tick()
    assert _ladder_rows(db) == []
    assert _applied_events(db) == []


# ── the ratified predicate is exact (brief §6) ──

def test_predicate_exactness():
    """Only DECLARED_CONSTRAINT_VIOLATION + the hypothesis's OWN
    falsification-condition citation is decisive. Every forbidden class,
    a methodology constraint, a wrong-hypothesis citation, and a missing
    citation are all non-decisive."""
    assert certifies_decisive_falsification(
        FailureClass.DECLARED_CONSTRAINT_VIOLATION, "h1",
        "hypothesis:h1:falsification_condition")
    for cls in FORBIDDEN_CLASSES:
        assert not certifies_decisive_falsification(
            cls, "h1", "hypothesis:h1:falsification_condition")
    # methodology constraint — a process failure, never a falsification
    assert not certifies_decisive_falsification(
        FailureClass.DECLARED_CONSTRAINT_VIOLATION, "h1",
        "methodology_constraint:0")
    # wrong hypothesis — the citation must name the SAME hypothesis
    assert not certifies_decisive_falsification(
        FailureClass.DECLARED_CONSTRAINT_VIOLATION, "h1",
        "hypothesis:h2:falsification_condition")
    # arbitrary / missing citation
    assert not certifies_decisive_falsification(
        FailureClass.DECLARED_CONSTRAINT_VIOLATION, "h1", "some:other:ref")
    assert not certifies_decisive_falsification(
        FailureClass.DECLARED_CONSTRAINT_VIOLATION, "h1", None)


# ── golden fixtures: every forbidden class never refutes (brief §4) ──

@pytest.mark.parametrize("cls", FORBIDDEN_CLASSES,
                         ids=lambda c: c.value)
def test_forbidden_class_never_refutes(db, cls):
    """Golden fixture per prohibited input: a digest-valid classification
    of a forbidden class — even carrying a falsification-condition citation
    — never produces REFUTED."""
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    classification_row(db, failure_class=cls.value,
                       constraint_ref="hypothesis:h1:falsification_condition")
    _tick_and_assert_no_refuted(db)


# ── semantic case A: execution/implementation failure → NOT REFUTED ──

def test_a_implementation_failure_not_refuted(db):
    """An experiment that CRASHED is an implementation/mechanism failure —
    the hypothesis may still hold. Not a falsification."""
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    classification_row(
        db, failure_class="IMPLEMENTATION_FAILURE",
        constraint_ref="hypothesis:h1:falsification_condition")
    _tick_and_assert_no_refuted(db)


# ── semantic case B: resource exhaustion → NOT REFUTED ──

def test_b_resource_exhaustion_not_refuted(db):
    """An experiment stopped early for resources is a resource constraint —
    absence of a completed run is not evidence against the hypothesis."""
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    classification_row(
        db, failure_class="RESOURCE_CONSTRAINT",
        constraint_ref="hypothesis:h1:falsification_condition")
    _tick_and_assert_no_refuted(db)


# ── semantic case C: environment mismatch → NOT REFUTED ──

def test_c_environment_mismatch_not_refuted(db):
    """A regime that does not apply is an environment mismatch — the test
    was not a valid test of the hypothesis, so it cannot refute it."""
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    classification_row(
        db, failure_class="ENVIRONMENT_MISMATCH",
        constraint_ref="hypothesis:h1:falsification_condition")
    _tick_and_assert_no_refuted(db)


# ── semantic case D: valid decisive falsification → MAY REFUTED ──

def test_d_valid_decisive_falsification_refutes(db):
    """The positive path: a digest-valid DECLARED_CONSTRAINT_VIOLATION
    citing the hypothesis's own falsification condition, bound to the
    current head program, applies the terminal REFUTED rung."""
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    classification_row(
        db, constraint_ref="hypothesis:h1:falsification_condition")
    ctrl = _make(db)
    ctrl.tick()
    rows = _ladder_rows(db)
    assert [(r["rung"], r["derived_from"]) for r in rows] == \
        [("REFUTED", "ratification")]
    events = _applied_events(db)
    assert len(events) == 1
    payload = _json.loads(events[0]["payload_json"])
    assert payload["ratified_by"] == "classification"
    assert payload["to_rung"] == "REFUTED"


# ── semantic case E: result satisfies the condition → NOT REFUTED ──

def test_e_condition_satisfied_not_refuted(db):
    """A result that SATISFIES the declared falsification condition is not a
    violation. The current substrate has no result-state type, so the
    honest encoding is: no decisive constraint-violation citation exists —
    a DECLARED_CONSTRAINT_VIOLATION without the hypothesis's own
    falsification-condition reference certifies nothing."""
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    # no falsification-condition citation — the condition was not violated
    classification_row(db, constraint_ref=None)
    _tick_and_assert_no_refuted(db)


# ── semantic case F: untestable / unknown → NOT REFUTED ──

def test_f_untestable_unknown_not_refuted(db):
    """An UNTESTABLE test (missing data / invalid methodology) is UNKNOWN —
    the honest fallback. It can escalate, never refute."""
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    classification_row(
        db, failure_class="UNKNOWN",
        constraint_ref="hypothesis:h1:falsification_condition")
    _tick_and_assert_no_refuted(db)


def test_f_framing_error_not_refuted(db):
    """A methodology/framing problem routes to scope review, never to a
    decisive falsification."""
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    classification_row(
        db, failure_class="FRAMING_ERROR",
        constraint_ref="hypothesis:h1:falsification_condition")
    _tick_and_assert_no_refuted(db)


# ── semantic case G: forged result → NOT REFUTED ──

def test_g_forged_content_hash_not_refuted(db):
    """A classification whose stored metadata no longer re-derives the row's
    authoritative content hash (a forged/tampered result) is refused by the
    F13 content-integrity check — never a falsification fact."""
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    classification_row(
        db, constraint_ref="hypothesis:h1:falsification_condition")
    # tamper: rewrite the explanation without updating the content hash
    row = db.execute(
        "SELECT metadata_json FROM artifacts WHERE artifact_id='fc-x'"
    ).fetchone()
    meta = _json.loads(row[0])
    meta["explanation"] = "FORGED after the fact"
    db.execute(
        "UPDATE artifacts SET metadata_json = ? WHERE artifact_id='fc-x'",
        (_json.dumps(meta),))
    _tick_and_assert_no_refuted(db)


def test_g_forged_identity_not_refuted(db):
    """A classification whose classification_id does not equal its artifact
    identity (forged identity) is refused by the digest-valid check."""
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    classification_row(
        db, constraint_ref="hypothesis:h1:falsification_condition")
    row = db.execute(
        "SELECT metadata_json FROM artifacts WHERE artifact_id='fc-x'"
    ).fetchone()
    meta = _json.loads(row[0])
    meta["classification_id"] = "fc-FORGED"
    # re-derive a consistent hash so ONLY the identity check is exercised
    content_hash = classification_content_hash(meta, "p1")
    db.execute(
        "UPDATE artifacts SET metadata_json = ?, content_hash = ? "
        "WHERE artifact_id='fc-x'", (_json.dumps(meta), content_hash))
    _tick_and_assert_no_refuted(db)


# ── HR-07 head binding: superseded program never refutes ──

def test_superseded_program_bare_path_not_refuted(db):
    """A decisive classification citing a SUPERSEDED program is a historical
    record, never a live REFUTED — the bare-classification driver binds to
    the current program head."""
    insert_program(db, "rp-old", hypotheses=[_hyp("h_old")],
                   evidence=[_req("h_old")], version=1)
    insert_program(db, "rp-new", hypotheses=[_hyp("h_new")],
                   evidence=[_req("h_new")], version=2,
                   supersedes_id="rp-old")
    classification_row(
        db, program_ref="rp-old", hypothesis_ref="h_old",
        constraint_ref="hypothesis:h_old:falsification_condition")
    _tick_and_assert_no_refuted(db)


def test_head_program_still_refutes(db):
    """The head-binding check does not over-restrict: a decisive
    classification against the CURRENT head still applies REFUTED."""
    insert_program(db, "rp-old", hypotheses=[_hyp("h_old")],
                   evidence=[_req("h_old")], version=1)
    insert_program(db, "rp-new", hypotheses=[_hyp("h_new")],
                   evidence=[_req("h_new")], version=2,
                   supersedes_id="rp-old")
    classification_row(
        db, program_ref="rp-new", hypothesis_ref="h_new",
        constraint_ref="hypothesis:h_new:falsification_condition")
    ctrl = _make(db)
    ctrl.tick()
    rows = _ladder_rows(db)
    assert [(r["program_id"], r["rung"]) for r in rows] == \
        [("rp-new", "REFUTED")]


def _proposal_intent(classification_ref, action, *, candidate="ev-a"):
    return Intent(
        kind=IntentKind.PROPOSE_CLASSIFICATION_ACTION,
        proposed_by="DIRECTOR", project_id="p1",
        payload={"classification_ref": classification_ref, "action": action,
                 "candidate_artifact_ref": candidate, "rationale": "test"},
        justification="test")


def _resolve_intent(proposal_id, decision):
    return Intent(
        kind=IntentKind.RESOLVE_CLASSIFICATION_PROPOSAL,
        proposed_by="DETERMINISTIC", project_id="p1",
        payload={"proposal_id": proposal_id, "decision": decision,
                 "rationale": "operator verdict", "operator_id": OP_ID},
        justification="test")


def _transition_intent(ratification_ref, *, evidence_ref="ev-a"):
    return Intent(
        kind=IntentKind.EVIDENCE_TRANSITION,
        proposed_by="DIRECTOR", project_id="p1",
        payload={"evidence_artifact_ref": "evidence:" + evidence_ref,
                 "from_state": "SUPPORTED", "to_state": "REFUTED",
                 "ratification_ref": ratification_ref, "rationale": "test"},
        justification="test")


def test_superseded_program_proposal_path_not_refuted(db):
    """The proposal-shaped REFUTED path is head-bound too: a fully ratified
    REJECT_BRANCH chain whose classification cites a SUPERSEDED program
    applies nothing (the target never resolves)."""
    insert_program(db, "rp-old", hypotheses=[_hyp("h_old")],
                   evidence=[_req("h_old")], version=1)
    insert_program(db, "rp-new", hypotheses=[_hyp("h_new")],
                   evidence=[_req("h_new")], version=2,
                   supersedes_id="rp-old")
    ref = classification_row(
        db, program_ref="rp-old", hypothesis_ref="h_old",
        constraint_ref="hypothesis:h_old:falsification_condition")
    prop = apply_intent(db, _proposal_intent(ref, "REJECT_BRANCH"),
                        clock=frozen_clock(CLOCK))
    apply_intent(db, _resolve_intent(prop.entity_id, "APPROVED"),
                 clock=frozen_clock(CLOCK))
    apply_intent(db, _transition_intent(prop.entity_id),
                 clock=frozen_clock(CLOCK))
    _tick_and_assert_no_refuted(db)


# ── HR-07 cross-project epistemic boundary (Step-0 fixture) ──
#
# Project A hypothesis + Project B classification / execution result
#   → REFUTED rejected
#
# The boundary is enforced at three independent layers, each pinned here:
#   1. DISCOVERY — the bare-classification driver's query is project-scoped
#      (controller.py:2294–2298, ``WHERE project_id = ?``), so a foreign
#      project's classification artifact is never loaded.
#   2. CONTENT INTEGRITY — the classification content hash is derived WITH
#      the project_id (evidence_ladder.py:151–186), so a row whose identity
#      was derived under a foreign project never re-derives here (F13).
#   3. ADMISSION — the proposal path's D3 dereference is project-scoped
#      (failure_classifications.py:582–600), so a proposal citing a foreign
#      classification is rejected at the gateway.

def _add_project_p2(db):
    ProjectRepository(db).create("p2", "Foreign Project")


def test_foreign_project_classification_bare_path_not_refuted(db):
    """Layer 1 — discovery scoping: a digest-valid, decisive classification
    that lives in Project B (p2) — citing Project A's (p1) hypothesis and
    head program by name — is invisible to Project A's controller. The
    bare-classification driver never loads it, so it can never apply
    REFUTED to Project A's hypothesis."""
    _add_project_p2(db)
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    # The classification is decisive in every respect EXCEPT project: it
    # names p1's hypothesis + head program and cites h1's own
    # falsification condition — but the artifact rows live in p2.
    classification_row(
        db, program_ref="rp-1", hypothesis_ref="h1",
        constraint_ref="hypothesis:h1:falsification_condition",
        project="p2")
    _tick_and_assert_no_refuted(db)


def test_foreign_derived_identity_never_rederives_here(db):
    """Layer 2 — content-integrity scoping (defense in depth): even if a
    classification row were physically present in Project A, an identity
    DERIVED under a foreign project (p2) never re-derives under p1 — the
    F13 content-integrity check refuses it as forged. The project_id is a
    first-class input to the classification content hash."""
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    # Row lives in p1, but its content hash was derived under p2's identity.
    classification_row(
        db, program_ref="rp-1", hypothesis_ref="h1",
        constraint_ref="hypothesis:h1:falsification_condition",
        project="p1", hash_project="p2")
    _tick_and_assert_no_refuted(db)


def test_foreign_project_classification_proposal_path_rejected(db):
    """Layer 3 — admission scoping: a PROPOSE_CLASSIFICATION_ACTION citing
    a classification that dereferences only in a foreign project is
    rejected at the gateway (D3 dereference is project-scoped). The
    proposal never enters the audit, so no ratification chain can form."""
    _add_project_p2(db)
    insert_program(db, hypotheses=[_hyp("h1")], evidence=[_req("h1")])
    ref = classification_row(
        db, program_ref="rp-1", hypothesis_ref="h1",
        constraint_ref="hypothesis:h1:falsification_condition",
        project="p2")
    with pytest.raises(GatewayRejection):
        apply_intent(db, _proposal_intent(ref, "REJECT_BRANCH"),
                     clock=frozen_clock(CLOCK))
    _tick_and_assert_no_refuted(db)
