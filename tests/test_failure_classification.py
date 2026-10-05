"""Q-05 golden fixtures — FALSIFIED/REFUTED failure classification (design §15).

Covers the acceptance-test matrix (A–H) plus the adversarial-attack matrix
(design §14 / task §14): forged class, forged constraint, forged scope field,
no supporting evidence, IMPLEMENTATION_FAILURE auto-replacement,
FRAMING_ERROR scope rewrite, RESOURCE_CONSTRAINT budget bypass, class/evidence
mismatch, cross-project classification, stale evidence, duplicate/replay, and
classifier-version replay.

New coverage (v2 schema):
- ConditionType (INTRINSIC/ACCIDENTAL/UNDETERMINED) drives the
  ENVIRONMENT_MISMATCH action set; ignored for every other class.
- MECHANISM_DECAYED: mechanism-level temporal falsification within an
  unchanged regime; admission, citation discipline, idempotency, and
  the not-decisive invariant.

The substrate is pure: no DB, no clock, no writes. The structural tests read
the module source and assert the no-write/no-authority invariants so a future
"helpful" edit that adds a write path fails the suite loudly.
"""
from __future__ import annotations

import pathlib

import pytest

from hermes.research.failure_classification import (
    ACTION_MAP,
    ConditionType,
    FailureClass,
    FailureClassificationDraft,
    FalsificationRecord,
    PermittedAction,
    ResourceGap,
    certifies_decisive_falsification,
    classify_failure,
    permitted_actions_for,
    summarize_classification,
)

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "src" / "hermes" / "research" / "failure_classification.py"


# ── fixtures ──

@pytest.fixture
def record() -> FalsificationRecord:
    return FalsificationRecord(
        project_id="p1",
        hypothesis_ref="H1",
        program_ref="rp_abc",
        falsifying_evidence_refs=("validation:ev1", "validation:ev2"),
    )


@pytest.fixture
def resolvers():
    """Project-scoped stub resolvers — the write path supplies real ones.

    p1 resolves ev1/ev2, the declared constraint, the P1 mechanism
    (prediction/observable), the regime, and the scope field. p2 resolves
    NOTHING (cross-project attack). Superseded refs refuse to resolve
    (staleness attack).
    """

    def evidence(project_id: str, ref: str) -> bool:
        if project_id != "p1":
            return False
        if ref in ("validation:ev1", "validation:ev2"):
            return True
        if ref == "validation:ev_stale":
            return False  # superseded — the write-path resolver refuses
        return False

    def constraint(project_id: str, program_ref: str, ref: str) -> bool:
        return project_id == "p1" and program_ref == "rp_abc" \
            and ref in ("hypothesis:H1:falsification_condition",
                        "methodology_constraint:0")

    def mechanism(project_id: str, program_ref: str, ref: str) -> bool:
        return project_id == "p1" and program_ref == "rp_abc" \
            and ref == "prediction:P1"

    def regime(project_id: str, ref: str) -> bool:
        return project_id == "p1" and ref in ("regime:icss-v1:trend",)

    def scope_field(project_id: str, brief_ref: str, field: str) -> bool:
        return project_id == "p1" and brief_ref == "brief-1" \
            and field in ("core_question", "constraints")

    return {
        "evidence": evidence,
        "constraint": constraint,
        "mechanism": mechanism,
        "regime": regime,
        "scope_field": scope_field,
    }


def _draft(failure_class: str, *, evidence=("validation:ev1",), **kw) -> FailureClassificationDraft:
    base = {
        "failure_class": failure_class,
        "explanation": "the falsifying evidence contradicts the declared frame",
        "evidence_refs": evidence,
        "proposed_by": "ADVERSARY",
        "classifier_version": "q05-2026.1",
    }
    base.update(kw)
    return FailureClassificationDraft(**base)


def _codes(result) -> set[str]:
    return {e.code for e in result.errors}


# ── A. DECLARED_CONSTRAINT_VIOLATION ──

def test_a1_valid_constraint_citation_admitted(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
               constraint_ref="hypothesis:H1:falsification_condition"),
        evidence_resolver=resolvers["evidence"],
        constraint_resolver=resolvers["constraint"],
    )
    assert result.admitted
    cls = result.classification
    assert cls.failure_class is FailureClass.DECLARED_CONSTRAINT_VIOLATION
    assert {a.value for a in cls.permitted_actions} == {
        "REJECT_BRANCH", "REVIEW_DOWNSTREAM_IMPACT"}
    assert cls.constraint_ref == "hypothesis:H1:falsification_condition"


def test_a2_missing_constraint_citation_rejected(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value),
        evidence_resolver=resolvers["evidence"],
        constraint_resolver=resolvers["constraint"],
    )
    assert not result.admitted
    assert "MISSING_CITATION" in _codes(result)


def test_a3_wrong_constraint_object_rejected(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
               constraint_ref="hypothesis:H9:falsification_condition"),
        evidence_resolver=resolvers["evidence"],
        constraint_resolver=resolvers["constraint"],
    )
    assert not result.admitted
    assert "CITATION_DOES_NOT_RESOLVE" in _codes(result)


# ── B. IMPLEMENTATION_FAILURE ──

def test_b1_mechanism_level_evidence_admitted(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.IMPLEMENTATION_FAILURE.value,
               failed_mechanism_ref="prediction:P1"),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert result.admitted
    cls = result.classification
    assert {a.value for a in cls.permitted_actions} == {
        "PROPOSE_MECHANISM_SUBSTITUTION"}
    assert cls.failed_mechanism_ref == "prediction:P1"


def test_b2_evidence_contradicts_only_top_level_claim_rejected(record, resolvers):
    """No mechanism citation — the classification cannot distinguish a
    mechanism failure from a claim-level contradiction; fail closed."""
    result = classify_failure(
        record,
        _draft(FailureClass.IMPLEMENTATION_FAILURE.value),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert not result.admitted
    assert "NO_MECHANISM_REF" in _codes(result)


def test_b2b_mechanism_equals_claim_rejected(record, resolvers):
    """failed_mechanism_ref == hypothesis_ref: the 'mechanism' is the
    top-level goal itself — not an implementation failure."""
    result = classify_failure(
        record,
        _draft(FailureClass.IMPLEMENTATION_FAILURE.value,
               failed_mechanism_ref="H1"),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert not result.admitted
    assert "MECHANISM_EQUALS_CLAIM" in _codes(result)


def test_b3_unresolvable_mechanism_rejected(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.IMPLEMENTATION_FAILURE.value,
               failed_mechanism_ref="prediction:FORGED"),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert not result.admitted
    assert "CITATION_DOES_NOT_RESOLVE" in _codes(result)


# ── B2. MECHANISM_DECAYED ──
#
# MECHANISM_DECAYED: a mechanism that was previously NOT falsified in this
# exact regime, and is THEN falsified by a LATER FalsificationRecord in the
# SAME regime (temporal decay, not cross-sectional ENVIRONMENT_MISMATCH).
# It carries the same failed_mechanism_ref citation discipline as
# IMPLEMENTATION_FAILURE, but its action set differs: the mechanism's survival
# record decayed, so the proposal is to substitute the mechanism.


def test_b2_mechanism_decayed_admitted(record, resolvers):
    """MECHANISM_DECAYED with a resolved failed_mechanism_ref is admitted;
    the action set is exactly PROPOSE_MECHANISM_SUBSTITUTION (the mechanism
    that survived a prior regime now needs a replacement)."""
    result = classify_failure(
        record,
        _draft(FailureClass.MECHANISM_DECAYED.value,
               failed_mechanism_ref="prediction:P1"),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert result.admitted
    cls = result.classification
    assert cls.failure_class is FailureClass.MECHANISM_DECAYED
    assert [a.value for a in cls.permitted_actions] == [
        "PROPOSE_MECHANISM_SUBSTITUTION"]
    assert cls.failed_mechanism_ref == "prediction:P1"
    assert cls.classification_id.startswith("fc_")


def test_b2a_mechanism_decayed_missing_ref_rejected(record, resolvers):
    """No failed_mechanism_ref: cannot distinguish a mechanism decay from a
    claim-level contradiction — fail closed."""
    result = classify_failure(
        record,
        _draft(FailureClass.MECHANISM_DECAYED.value),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert not result.admitted
    assert "NO_MECHANISM_REF" in _codes(result)


def test_b2b_mechanism_decayed_mechanism_equals_claim_rejected(record, resolvers):
    """failed_mechanism_ref == hypothesis_ref: the 'mechanism' is the
    top-level goal, not a mechanism-level falsification."""
    result = classify_failure(
        record,
        _draft(FailureClass.MECHANISM_DECAYED.value,
               failed_mechanism_ref="H1"),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert not result.admitted
    assert "MECHANISM_EQUALS_CLAIM" in _codes(result)


def test_b2c_mechanism_decayed_unresolvable_mechanism_rejected(record,
                                                                resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.MECHANISM_DECAYED.value,
               failed_mechanism_ref="prediction:FORGED"),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert not result.admitted
    assert "CITATION_DOES_NOT_RESOLVE" in _codes(result)


def test_b2d_mechanism_decayed_no_evidence_rejected(record, resolvers):
    """MECHANISM_DECAYED requires evidence (it is in _EVIDENCE_REQUIRED_CLASSES)."""
    result = classify_failure(
        record,
        _draft(FailureClass.MECHANISM_DECAYED.value,
               failed_mechanism_ref="prediction:P1",
               evidence=()),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert not result.admitted
    assert "NO_SUPPORTING_EVIDENCE" in _codes(result)


def test_b2e_mechanism_decayed_not_decisive(record, resolvers):
    """MECHANISM_DECAYED is explicitly NOT a decisive falsification — only
    DECLARED_CONSTRAINT_VIOLATION certifies decisive falsification."""
    assert not certifies_decisive_falsification(
        FailureClass.MECHANISM_DECAYED, "H1", None)
    assert not certifies_decisive_falsification(
        FailureClass.MECHANISM_DECAYED,
        "H1", "hypothesis:H1:falsification_condition")


def test_b2f_mechanism_decayed_class_does_not_require_human_confirmation(
        record, resolvers):
    """The MECHANISM_DECAYED class itself does not require human confirmation
    (only FRAMING_ERROR does) — but its PROPOSE_MECHANISM_SUBSTITUTION action
    IS authority-shaped, so the proposal gate still fires on the action."""
    result = classify_failure(
        record,
        _draft(FailureClass.MECHANISM_DECAYED.value,
               failed_mechanism_ref="prediction:P1"),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert result.admitted
    cls = result.classification
    assert cls.requires_human_confirmation is False
    # the action is authority-shaped → proposal gate fires
    from hermes.research.failure_classification import (
        proposal_requires_human_confirmation,
    )
    assert proposal_requires_human_confirmation(
        cls.failure_class, PermittedAction.PROPOSE_MECHANISM_SUBSTITUTION,
        cls.contributing_factors) is True


# ── C. ENVIRONMENT_MISMATCH ──

def test_c1_explicit_regime_admitted(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.ENVIRONMENT_MISMATCH.value,
               regime_ref="regime:icss-v1:trend",
               condition_type=ConditionType.INTRINSIC),
        evidence_resolver=resolvers["evidence"],
        regime_resolver=resolvers["regime"],
    )
    assert result.admitted
    cls = result.classification
    # INTRINSIC: the mismatch is a property of the hypothesis/target regime —
    # only scope narrowing is warranted (no parallel-regime test).
    assert {a.value for a in cls.permitted_actions} == {
        "PROPOSE_SCOPE_NARROWING"}
    assert cls.regime_ref == "regime:icss-v1:trend"


def test_c2_no_regime_rejected(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.ENVIRONMENT_MISMATCH.value),
        evidence_resolver=resolvers["evidence"],
        regime_resolver=resolvers["regime"],
    )
    assert not result.admitted
    assert "MISSING_CITATION" in _codes(result)


# ── C2. ENVIRONMENT_MISMATCH condition-type action resolution ──
#
# ConditionType is meaningful ONLY for ENVIRONMENT_MISMATCH and drives the
# permitted-action set (pure function of class + condition):
#   INTRINSIC      → PROPOSE_SCOPE_NARROWING
#   ACCIDENTAL     → PROPOSE_SCOPE_NARROWING + PROPOSE_PARALLEL_REGIME_TEST
#   UNDETERMINED   → PROPOSE_SCOPE_NARROWING + PROPOSE_PARALLEL_REGIME_TEST

@pytest.mark.parametrize("condition,expected", [
    (ConditionType.INTRINSIC, {"PROPOSE_SCOPE_NARROWING"}),
    (ConditionType.ACCIDENTAL, {"PROPOSE_SCOPE_NARROWING",
                                 "PROPOSE_PARALLEL_REGIME_TEST"}),
    (ConditionType.UNDETERMINED, {"PROPOSE_SCOPE_NARROWING",
                                   "PROPOSE_PARALLEL_REGIME_TEST"}),
])
def test_c_condition_type_action_resolution(record, resolvers, condition,
                                           expected):
    """Every (ENVIRONMENT_MISMATCH, ConditionType) maps to the exact
    action set; the default (UNDETERMINED) is the conservative view."""
    result = classify_failure(
        record,
        _draft(FailureClass.ENVIRONMENT_MISMATCH.value,
               regime_ref="regime:icss-v1:trend",
               condition_type=condition),
        evidence_resolver=resolvers["evidence"],
        regime_resolver=resolvers["regime"],
    )
    assert result.admitted
    actions = {a.value for a in result.classification.permitted_actions}
    assert actions == expected


def test_c_condition_type_raw_string_coerced(record, resolvers):
    """A draft with condition_type set to the raw string 'INTRINSIC' (not
    ConditionType.INTRINSIC) is ADMITTED — _validate_draft guarantees
    coercibility, and _build_classification coerces via the same pattern as
    failure_class. The content_hash must match the ConditionType.INTRINSIC
    path exactly (identity is preserved through coercion)."""
    result = classify_failure(
        record,
        _draft(FailureClass.ENVIRONMENT_MISMATCH.value,
               regime_ref="regime:icss-v1:trend",
               condition_type="INTRINSIC"),
        evidence_resolver=resolvers["evidence"],
        regime_resolver=resolvers["regime"],
    )
    assert result.admitted
    cls = result.classification
    assert {a.value for a in cls.permitted_actions} == {
        "PROPOSE_SCOPE_NARROWING"}
    # Content hash must match the canonical ConditionType.INTRINSIC path
    result_enum = classify_failure(
        record,
        _draft(FailureClass.ENVIRONMENT_MISMATCH.value,
               regime_ref="regime:icss-v1:trend",
               condition_type=ConditionType.INTRINSIC),
        evidence_resolver=resolvers["evidence"],
        regime_resolver=resolvers["regime"],
    )
    assert result_enum.admitted
    assert cls.content_hash == result_enum.classification.content_hash


def test_c_default_condition_is_undetermined(record, resolvers):
    """An ENVIRONMENT_MISMATCH draft with no explicit condition_type
    defaults to UNDETERMINED (the conservative/investigate view)."""
    draft = _draft(FailureClass.ENVIRONMENT_MISMATCH.value,
                   regime_ref="regime:icss-v1:trend")
    assert draft.condition_type is ConditionType.UNDETERMINED


def test_c_malformed_condition_type_rejected_for_every_class(record, resolvers):
    """FIX 3 — a malformed (non-ConditionType) draft.condition_type must NOT
    raise inside _build_classification (classify_failure is "(pure, never
    raises)" per its docstring). It must fail closed with
    UNKNOWN_CONDITION_TYPE for EVERY failure class, validated unconditionally
    rather than special-cased to ENVIRONMENT_MISMATCH."""
    for fc in FailureClass:
        kwargs = {}
        if fc is FailureClass.ENVIRONMENT_MISMATCH:
            kwargs["regime_ref"] = "regime:icss-v1:trend"
        elif fc is FailureClass.DECLARED_CONSTRAINT_VIOLATION:
            kwargs["constraint_ref"] = "hypothesis:H1:falsification_condition"
        elif fc is FailureClass.IMPLEMENTATION_FAILURE or (
            fc is FailureClass.MECHANISM_DECAYED
        ):
            kwargs["failed_mechanism_ref"] = "prediction:P1"
        elif fc is FailureClass.RESOURCE_CONSTRAINT:
            kwargs["resource_gap"] = ResourceGap("compute_hours", 10.0, 40.0, "h")
        elif fc is FailureClass.FRAMING_ERROR:
            kwargs["scope_brief_ref"] = "brief-1"
            kwargs["scope_brief_field"] = "core_question"
        # UNKNOWN needs nothing extra
        draft = _draft(fc.value, condition_type="BOGUS", **kwargs)
        result = classify_failure(
            record, draft,
            evidence_resolver=resolvers["evidence"],
            constraint_resolver=resolvers["constraint"],
            mechanism_resolver=resolvers["mechanism"],
            regime_resolver=resolvers["regime"],
            scope_field_resolver=resolvers["scope_field"],
        )
        assert not result.admitted, f"{fc.value} should reject malformed condition_type"
        assert "UNKNOWN_CONDITION_TYPE" in _codes(result)


def test_c_condition_type_ignored_for_other_classes(record, resolvers):
    """ConditionType is meaningless for non-ENVIRONMENT_MISMATCH classes and
    must NOT alter their action set — the field is carried but inert."""
    base = _draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
                  constraint_ref="hypothesis:H1:falsification_condition",
                  condition_type=ConditionType.ACCIDENTAL)
    result = classify_failure(
        record, base,
        evidence_resolver=resolvers["evidence"],
        constraint_resolver=resolvers["constraint"],
    )
    assert result.admitted
    actions = {a.value for a in result.classification.permitted_actions}
    assert actions == {"REJECT_BRANCH", "REVIEW_DOWNSTREAM_IMPACT"}


def test_c_condition_type_enters_classification_id(record, resolvers):
    """Different ConditionType on the same ENVIRONMENT_MISMATCH record/draft
    produces DIFFERENT classification_ids — condition_type is part of the
    content identity (the module's own contract: identity binds schema_version,
    classifier_version, content). Two drafts identical except INTRINSIC vs
    ACCIDENTAL must not collapse to the same id with different action sets."""
    r_intrinsic = classify_failure(
        record,
        _draft(FailureClass.ENVIRONMENT_MISMATCH.value,
               regime_ref="regime:icss-v1:trend",
               condition_type=ConditionType.INTRINSIC),
        evidence_resolver=resolvers["evidence"],
        regime_resolver=resolvers["regime"],
    )
    r_accidental = classify_failure(
        record,
        _draft(FailureClass.ENVIRONMENT_MISMATCH.value,
               regime_ref="regime:icss-v1:trend",
               condition_type=ConditionType.ACCIDENTAL),
        evidence_resolver=resolvers["evidence"],
        regime_resolver=resolvers["regime"],
    )
    assert r_intrinsic.admitted and r_accidental.admitted
    assert r_intrinsic.classification.classification_id != \
        r_accidental.classification.classification_id


# ── D. RESOURCE_CONSTRAINT ──

def test_d1_measurable_deficit_admitted(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.RESOURCE_CONSTRAINT.value,
               resource_gap=ResourceGap("compute_hours", 10.0, 40.0, "h")),
        evidence_resolver=resolvers["evidence"],
    )
    assert result.admitted
    cls = result.classification
    assert cls.resource_gap is not None
    assert cls.resource_gap.observed < cls.resource_gap.required


def test_d2_no_automatic_retry_or_budget_action(record, resolvers):
    """The permitted set is EXACTLY {PARK_FOR_RESOURCE_REVIEW} — no retry, no
    budget expansion, no task creation (attack 7)."""
    result = classify_failure(
        record,
        _draft(FailureClass.RESOURCE_CONSTRAINT.value,
               resource_gap=ResourceGap("compute_hours", 10.0, 40.0, "h")),
        evidence_resolver=resolvers["evidence"],
    )
    assert result.admitted
    assert [a.value for a in result.classification.permitted_actions] == [
        "PARK_FOR_RESOURCE_REVIEW"]


def test_d3_not_a_deficit_rejected(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.RESOURCE_CONSTRAINT.value,
               resource_gap=ResourceGap("compute_hours", 40.0, 40.0, "h")),
        evidence_resolver=resolvers["evidence"],
    )
    assert not result.admitted
    assert "RESOURCE_GAP_NOT_A_DEFICIT" in _codes(result)


def test_d4_bare_claim_rejected(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.RESOURCE_CONSTRAINT.value),
        evidence_resolver=resolvers["evidence"],
    )
    assert not result.admitted
    assert "NO_RESOURCE_GAP" in _codes(result)


# ── E. FRAMING_ERROR ──

def test_e1_scope_citation_admitted_with_human_confirmation(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.FRAMING_ERROR.value,
               scope_brief_ref="brief-1", scope_brief_field="core_question"),
        evidence_resolver=resolvers["evidence"],
        scope_field_resolver=resolvers["scope_field"],
    )
    assert result.admitted
    cls = result.classification
    assert [a.value for a in cls.permitted_actions] == ["ROUTE_TO_SCOPE_REVIEW"]
    assert cls.requires_human_confirmation is True
    assert cls.scope_brief_ref == "brief-1"
    assert cls.scope_brief_field == "core_question"


def test_e2_missing_scope_reference_rejected(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.FRAMING_ERROR.value, scope_brief_ref="brief-1"),
        evidence_resolver=resolvers["evidence"],
        scope_field_resolver=resolvers["scope_field"],
    )
    assert not result.admitted
    assert "NO_SCOPE_FIELD" in _codes(result)

    result = classify_failure(
        record,
        _draft(FailureClass.FRAMING_ERROR.value,
               scope_brief_field="core_question"),
        evidence_resolver=resolvers["evidence"],
        scope_field_resolver=resolvers["scope_field"],
    )
    assert not result.admitted
    assert "NO_SCOPE_REF" in _codes(result)


def test_e2b_forged_scope_field_rejected(record, resolvers):
    """Attack 3 — a forged ScopeBrief field cannot resolve."""
    result = classify_failure(
        record,
        _draft(FailureClass.FRAMING_ERROR.value,
               scope_brief_ref="brief-1", scope_brief_field="budget_override"),
        evidence_resolver=resolvers["evidence"],
        scope_field_resolver=resolvers["scope_field"],
    )
    assert not result.admitted
    assert "CITATION_DOES_NOT_RESOLVE" in _codes(result)


# ── F. Authority attacks (fail closed, structural) ──

def test_f1_no_write_path_in_module():
    """The substrate has no SQL, no repository/gateway/event imports, no
    write verbs — it cannot create a hypothesis, task, program, or event."""
    src = MODULE_PATH.read_text(encoding="utf-8")
    for token in ("sqlite3", "INSERT INTO", "UPDATE ", "DELETE FROM",
                  "apply_intent", "hermes.persistence", "hermes.core",
                  "hermes.research.gateway", "hermes.research.evidence",
                  "EventType", "IntentKind"):
        assert token not in src, f"forbidden write-path token {token!r} found"


def test_f2_no_creation_actions_in_vocabulary():
    """The action vocabulary contains no creation/mutation actions — the
    mapping can never authorize creating a hypothesis/task, mutating scope,
    changing ladder state, or touching a budget."""
    values = {a.value for a in PermittedAction}
    for forbidden in ("CREATE_HYPOTHESIS", "CREATE_TASK", "CREATE_PROGRAM",
                      "MODIFY_SCOPE", "CHANGE_LADDER", "BYPASS_GATE",
                      "EXPAND_BUDGET", "RETRY"):
        assert forbidden not in values, f"forbidden action {forbidden!r} exists"


def test_f3_every_class_maps_and_nothing_else():
    """The action map is total over the closed vocabulary and the sets are
    proposal categories only (subset of PermittedAction)."""
    assert set(ACTION_MAP) == set(FailureClass)
    for cls in FailureClass:
        actions = permitted_actions_for(cls)
        assert actions <= set(PermittedAction)
        assert actions  # never empty — every honest classification routes


def test_f4_framing_error_never_mutates_scope(record, resolvers):
    """Attack 6 — FRAMING_ERROR routes to scope review; it can never rewrite
    the brief (the only action is ROUTE_TO_SCOPE_REVIEW and the result is
    human-confirmation-marked)."""
    result = classify_failure(
        record,
        _draft(FailureClass.FRAMING_ERROR.value,
               scope_brief_ref="brief-1", scope_brief_field="core_question"),
        evidence_resolver=resolvers["evidence"],
        scope_field_resolver=resolvers["scope_field"],
    )
    assert result.admitted
    actions = {a.value for a in result.classification.permitted_actions}
    assert actions == {"ROUTE_TO_SCOPE_REVIEW"}
    assert result.classification.requires_human_confirmation


def test_f5_implementation_failure_cannot_auto_create(record, resolvers):
    """Attack 5 — IMPLEMENTATION_FAILURE only *proposes* a substitution
    category; nothing in the result creates or schedules a candidate."""
    result = classify_failure(
        record,
        _draft(FailureClass.IMPLEMENTATION_FAILURE.value,
               failed_mechanism_ref="prediction:P1"),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert result.admitted
    assert [a.value for a in result.classification.permitted_actions] == [
        "PROPOSE_MECHANISM_SUBSTITUTION"]
    assert result.classification.classification_id.startswith("fc_")


# ── adversarial attack matrix (task §14) ──
#
# ── MECHANISM_DECAYED additions to the adversarial matrix ──
# (covered by B2 section above for admission/validation; these pin the
# cross-cutting attacks: idempotency and cross-project rejection)

def test_x1_forged_failure_class_rejected(record, resolvers):
    """Attack 1 — a forged class is rejected, never coerced."""
    result = classify_failure(
        record,
        _draft("MADE_UP_CLASS"),
        evidence_resolver=resolvers["evidence"],
    )
    assert not result.admitted
    assert "UNKNOWN_FAILURE_CLASS" in _codes(result)


def test_x2_forged_constraint_id_rejected(record, resolvers):
    """Attack 2 — a forged axiom/constraint id cannot dereference."""
    result = classify_failure(
        record,
        _draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
               constraint_ref="hypothesis:H1:forge"),
        evidence_resolver=resolvers["evidence"],
        constraint_resolver=resolvers["constraint"],
    )
    assert not result.admitted
    assert "CITATION_DOES_NOT_RESOLVE" in _codes(result)


def test_x3_forged_scope_field_rejected(record, resolvers):
    """Attack 3 — covered by test_e2b; kept for the matrix completeness."""
    test_e2b_forged_scope_field_rejected(record, resolvers)


def test_x4_no_supporting_evidence_rejected(record, resolvers):
    """Attack 4 — a failure class with no supporting evidence is rejected."""
    result = classify_failure(
        record,
        _draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
               constraint_ref="hypothesis:H1:falsification_condition",
               evidence=()),
        evidence_resolver=resolvers["evidence"],
        constraint_resolver=resolvers["constraint"],
    )
    assert not result.admitted
    assert "NO_SUPPORTING_EVIDENCE" in _codes(result)


def test_x5_no_auto_replacement(record, resolvers):
    """Attack 5 — covered by test_f5; kept for the matrix completeness."""
    test_f5_implementation_failure_cannot_auto_create(record, resolvers)


def test_x6_no_scope_rewrite(record, resolvers):
    """Attack 6 — covered by test_f4; kept for the matrix completeness."""
    test_f4_framing_error_never_mutates_scope(record, resolvers)


def test_x7_no_budget_bypass(record, resolvers):
    """Attack 7 — covered by test_d2; kept for the matrix completeness."""
    test_d2_no_automatic_retry_or_budget_action(record, resolvers)


def test_x8_class_mismatch_with_evidence_rejected(record, resolvers):
    """Attack 8 — a citation the class does not require is rejected, never
    silently dropped (class-mismatch evidence cannot hide)."""
    result = classify_failure(
        record,
        _draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
               constraint_ref="hypothesis:H1:falsification_condition",
               regime_ref="regime:icss-v1:trend"),
        evidence_resolver=resolvers["evidence"],
        constraint_resolver=resolvers["constraint"],
        regime_resolver=resolvers["regime"],
    )
    assert not result.admitted
    assert "CITATION_NOT_REQUIRED_FOR_CLASS" in _codes(result)


def test_x9_cross_project_classification_rejected(record, resolvers):
    """Attack 9 — a classification from a different project cannot resolve
    its citations (project-scoped resolvers)."""
    foreign = FalsificationRecord(
        project_id="p2",
        hypothesis_ref="H1",
        program_ref="rp_abc",
        falsifying_evidence_refs=("validation:ev1",),
    )
    result = classify_failure(
        foreign,
        _draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
               constraint_ref="hypothesis:H1:falsification_condition"),
        evidence_resolver=resolvers["evidence"],
        constraint_resolver=resolvers["constraint"],
    )
    assert not result.admitted
    assert "EVIDENCE_DOES_NOT_RESOLVE" in _codes(result)


def test_x9b_evidence_outside_record_rejected(record, resolvers):
    """Attack 9b — citing evidence that is not the record's own falsifying
    evidence is a forged provenance attempt."""
    result = classify_failure(
        record,
        _draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
               constraint_ref="hypothesis:H1:falsification_condition",
               evidence=("validation:ev1", "validation:ev9")),
        evidence_resolver=resolvers["evidence"],
        constraint_resolver=resolvers["constraint"],
    )
    assert not result.admitted
    assert "EVIDENCE_OUTSIDE_RECORD" in _codes(result)


def test_x10_stale_evidence_rejected(record, resolvers):
    """Attack 10 — superseded evidence refuses to resolve (the write-path
    resolver enforces head-status; the substrate fails closed)."""
    record_stale = FalsificationRecord(
        project_id="p1",
        hypothesis_ref="H1",
        program_ref="rp_abc",
        falsifying_evidence_refs=("validation:ev_stale",),
    )
    result = classify_failure(
        record_stale,
        _draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
               constraint_ref="hypothesis:H1:falsification_condition",
               evidence=("validation:ev_stale",)),
        evidence_resolver=resolvers["evidence"],
        constraint_resolver=resolvers["constraint"],
    )
    assert not result.admitted
    assert "EVIDENCE_DOES_NOT_RESOLVE" in _codes(result)


def test_x11_duplicate_classification_is_idempotent(record, resolvers):
    """Attack 11 — the same record + draft yields the SAME content-derived
    classification (duplicates collapse idempotently; nothing mutates)."""
    draft = _draft(FailureClass.IMPLEMENTATION_FAILURE.value,
                   failed_mechanism_ref="prediction:P1")
    r1 = classify_failure(record, draft,
                          evidence_resolver=resolvers["evidence"],
                          mechanism_resolver=resolvers["mechanism"])
    r2 = classify_failure(record, draft,
                          evidence_resolver=resolvers["evidence"],
                          mechanism_resolver=resolvers["mechanism"])
    assert r1.admitted and r2.admitted
    assert r1.classification.classification_id \
        == r2.classification.classification_id
    assert r1 == r2  # identical structured output


def test_x11b_mechanism_decayed_idempotent(record, resolvers):
    """Attack 11 (MECHANISM_DECAYED) — same replay yields identical identity."""
    draft = _draft(FailureClass.MECHANISM_DECAYED.value,
                   failed_mechanism_ref="prediction:P1")
    r1 = classify_failure(record, draft,
                          evidence_resolver=resolvers["evidence"],
                          mechanism_resolver=resolvers["mechanism"])
    r2 = classify_failure(record, draft,
                          evidence_resolver=resolvers["evidence"],
                          mechanism_resolver=resolvers["mechanism"])
    assert r1.admitted and r2.admitted
    assert r1.classification.classification_id \
        == r2.classification.classification_id
    assert r1 == r2


def test_x12_classifier_version_changes_identity(record, resolvers):
    """Attack 12 — replay after a changed classifier version produces a NEW
    derived classification; the historical one is untouched (both records
    coexist, no mutation)."""
    draft_v1 = _draft(FailureClass.IMPLEMENTATION_FAILURE.value,
                      failed_mechanism_ref="prediction:P1")
    draft_v2 = _draft(FailureClass.IMPLEMENTATION_FAILURE.value,
                      failed_mechanism_ref="prediction:P1",
                      classifier_version="q05-2026.2")
    r1 = classify_failure(record, draft_v1,
                          evidence_resolver=resolvers["evidence"],
                          mechanism_resolver=resolvers["mechanism"])
    r2 = classify_failure(record, draft_v2,
                          evidence_resolver=resolvers["evidence"],
                          mechanism_resolver=resolvers["mechanism"])
    assert r1.admitted and r2.admitted
    assert r1.classification.classification_id \
        != r2.classification.classification_id
    assert r1.classification.classifier_version == "q05-2026.1"
    assert r2.classification.classifier_version == "q05-2026.2"
    # the historical record's identity is bound to its own version — stable
    r1_replay = classify_failure(record, draft_v1,
                                 evidence_resolver=resolvers["evidence"],
                                 mechanism_resolver=resolvers["mechanism"])
    assert r1_replay.classification.classification_id \
        == r1.classification.classification_id


# ── G/H. replay determinism + provenance ──

def test_g_replay_identical_output(record, resolvers):
    draft = _draft(FailureClass.ENVIRONMENT_MISMATCH.value,
                   regime_ref="regime:icss-v1:trend",
                   contributing_factors=("RESOURCE_CONSTRAINT",))
    r1 = classify_failure(record, draft,
                          evidence_resolver=resolvers["evidence"],
                          regime_resolver=resolvers["regime"])
    r2 = classify_failure(record, draft,
                          evidence_resolver=resolvers["evidence"],
                          regime_resolver=resolvers["regime"])
    assert r1 == r2
    assert r1.classification.permitted_actions \
        == r2.classification.permitted_actions


def test_h_provenance_traceable(record, resolvers):
    """Every ADMITTED classification traces to the record's hypothesis,
    program, and falsifying evidence + the class-required citation."""
    draft = _draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
                   constraint_ref="hypothesis:H1:falsification_condition",
                   evidence=("validation:ev1", "validation:ev2"))
    result = classify_failure(record, draft,
                              evidence_resolver=resolvers["evidence"],
                              constraint_resolver=resolvers["constraint"])
    assert result.admitted
    cls = result.classification
    assert cls.project_id == record.project_id == "p1"
    assert cls.hypothesis_ref == record.hypothesis_ref == "H1"
    assert cls.program_ref == record.program_ref == "rp_abc"
    assert set(cls.evidence_refs) <= set(record.falsifying_evidence_refs)
    assert cls.evidence_refs == ("validation:ev1", "validation:ev2")
    assert cls.constraint_ref == "hypothesis:H1:falsification_condition"


def test_h2_contributing_factors_validated(record, resolvers):
    """Contributing factors are validated: vocabulary membership, disjoint
    from the primary, unique."""
    draft = _draft(FailureClass.ENVIRONMENT_MISMATCH.value,
                   regime_ref="regime:icss-v1:trend",
                   contributing_factors=("RESOURCE_CONSTRAINT",))
    result = classify_failure(record, draft,
                              evidence_resolver=resolvers["evidence"],
                              regime_resolver=resolvers["regime"])
    assert result.admitted
    assert result.classification.contributing_factors == (
        FailureClass.RESOURCE_CONSTRAINT,)

    bad = _draft(FailureClass.ENVIRONMENT_MISMATCH.value,
                 regime_ref="regime:icss-v1:trend",
                 contributing_factors=("ENVIRONMENT_MISMATCH",))
    result = classify_failure(record, bad,
                              evidence_resolver=resolvers["evidence"],
                              regime_resolver=resolvers["regime"])
    assert not result.admitted
    assert "FACTOR_EQUALS_PRIMARY" in _codes(result)


def test_unknown_class_honest_fallback(record, resolvers):
    """UNKNOWN is the honest fallback: no forced classification; the only
    permitted action is Director escalation."""
    result = classify_failure(
        record,
        _draft(FailureClass.UNKNOWN.value),
        evidence_resolver=resolvers["evidence"],
    )
    assert result.admitted
    assert [a.value for a in result.classification.permitted_actions] == [
        "ESCALATE_TO_DIRECTOR"]
    assert result.classification.requires_human_confirmation is False


def test_summarize_classification_deterministic(record, resolvers):
    result = classify_failure(
        record,
        _draft(FailureClass.FRAMING_ERROR.value,
               scope_brief_ref="brief-1", scope_brief_field="core_question"),
        evidence_resolver=resolvers["evidence"],
        scope_field_resolver=resolvers["scope_field"],
    )
    assert result.admitted
    summary = summarize_classification(result.classification)
    assert "FRAMING_ERROR" in summary
    assert "ROUTE_TO_SCOPE_REVIEW" in summary
    assert "REQUIRES HUMAN CONFIRMATION" in summary


def test_missing_classifier_version_rejected(record, resolvers):
    result = classify_failure(
        record,
        FailureClassificationDraft(
            failure_class=FailureClass.UNKNOWN.value,
            explanation="cannot determine",
            proposed_by="ADVERSARY",
            classifier_version="",
        ),
        evidence_resolver=resolvers["evidence"],
    )
    assert not result.admitted
    assert "MISSING_CLASSIFIER_VERSION" in _codes(result)


def test_missing_resolver_fails_closed(record):
    """A class-required citation without its resolver fails closed (thesis.py
    contract) — a resolverless classification can never be admitted."""
    result = classify_failure(
        record,
        _draft(FailureClass.DECLARED_CONSTRAINT_VIOLATION.value,
               constraint_ref="hypothesis:H1:falsification_condition"),
        evidence_resolver=None,
        constraint_resolver=None,
    )
    assert not result.admitted
    assert "EVIDENCE_UNDEREFERENCEABLE" in _codes(result)
    assert "CITATION_UNDEREFERENCEABLE" in _codes(result)


def test_contributing_framing_error_gates_human_confirmation(record,
                                                              resolvers):
    """Red-team §2 remediation (substrate + digest recompute): a
    FRAMING_ERROR CONTRIBUTING FACTOR on a non-authority primary class
    still requires human confirmation — the stored flag is derived True,
    the digest recomputes True, and the proposal gate fires on the framing
    assertion itself (never a stored fact)."""
    from hermes.research.failure_classification import (
        FailureClass,
        PermittedAction,
        proposal_requires_human_confirmation,
    )
    result = classify_failure(
        record,
        _draft(FailureClass.RESOURCE_CONSTRAINT.value,
               contributing_factors=(FailureClass.FRAMING_ERROR.value,),
               resource_gap=ResourceGap(
                   "compute_hours", 10.0, 40.0, "h")),
        evidence_resolver=resolvers["evidence"],
    )
    assert result.admitted
    cls = result.classification
    assert cls.requires_human_confirmation is True
    # the non-authority action is still gated by the contributor
    assert proposal_requires_human_confirmation(
        cls.failure_class,
        PermittedAction.PARK_FOR_RESOURCE_REVIEW,
        cls.contributing_factors)


def test_contributing_framing_error_gates_implementation_failure_primary(
        record, resolvers):
    """Review §8 exact attack: primary = IMPLEMENTATION_FAILURE with a
    FRAMING_ERROR CONTRIBUTING FACTOR must still require human
    confirmation (the red-team §2 rule is class-agnostic — the gate fires
    on the framing assertion itself). The RESOURCE_CONSTRAINT variant
    covers the rule by equivalence; this pins the exact primary named in
    the review instruction."""
    from hermes.research.failure_classification import (
        FailureClass,
        PermittedAction,
        proposal_requires_human_confirmation,
    )
    result = classify_failure(
        record,
        _draft(FailureClass.IMPLEMENTATION_FAILURE.value,
               failed_mechanism_ref="prediction:P1",
               contributing_factors=(FailureClass.FRAMING_ERROR.value,)),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert result.admitted
    cls = result.classification
    assert cls.requires_human_confirmation is True
    # the non-authority action is still gated by the contributor
    assert proposal_requires_human_confirmation(
        cls.failure_class,
        PermittedAction.REVIEW_DOWNSTREAM_IMPACT,
        cls.contributing_factors)
    # control: the same class without the contributor is NOT gated
    plain = classify_failure(
        record,
        _draft(FailureClass.IMPLEMENTATION_FAILURE.value,
               failed_mechanism_ref="prediction:P1"),
        evidence_resolver=resolvers["evidence"],
        mechanism_resolver=resolvers["mechanism"],
    )
    assert plain.admitted
    assert plain.classification.requires_human_confirmation is False



def test_requires_human_confirmation_for_derived_from_class():
    """F2 rule — the human-confirmation flag is a pure function of the
    class (True iff FRAMING_ERROR), exposed as the single ratified source
    the advisory digest recomputes from."""
    from hermes.research.failure_classification import (
        FailureClass,
        requires_human_confirmation_for,
    )
    for c in FailureClass:
        assert requires_human_confirmation_for(c) is (
            c is FailureClass.FRAMING_ERROR)
