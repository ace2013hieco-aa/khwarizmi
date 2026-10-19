"""ROLE-EXH-1 (GAP-1 P1-5) — role-gate exhaustiveness pins (fail closed).

``gateway._require_role`` partitions every ``IntentKind`` into three
authority classes:

- ``director_only`` — admitted only for ``AgentProfile.DIRECTOR``;
- ``internal_only`` — admitted only for ``AgentProfile.DETERMINISTIC``;
- ``llm_proposable`` — the LLM-proposable surface; a kind that is also
  ``director_only`` stays Director-only (that branch runs first).

Before ROLE-EXH-1 the final branch was negative admission: anything not
``director_only``/``internal_only`` was admitted for every
non-DETERMINISTIC profile. A kind in NONE of the three partitions — the
latent forward-compatibility hole as new kinds land — was therefore
silently admitted to all four LLM agent profiles. The fix is positive
admission: an LLM profile is admitted only when the kind is in
``llm_proposable``; an unpartitioned kind is refused for every profile.

These tests (a) pin the admission matrix for every CURRENT kind and
profile, so no existing path's decision changes; (b) guard the three
partitions structurally — exhaustive union, effectively disjoint
admission classes, no hardcoded counts, so a future kind (CRED-1) must
be classified for the guard to pass; and (c) prove a kind in no
partition is refused for every profile, via an in-test removal of a
member from all three partitions (the fail-on-base scenario: base code
admits it for the four LLM profiles).
"""
from __future__ import annotations

import pytest

from hermes.core.intents import Intent, IntentKind
from hermes.core.node import AgentProfile
from hermes.research.gateway import ROLE, GatewayRejection, _require_role

LLM_AGENT_PROFILES = frozenset({
    AgentProfile.DIRECTOR,
    AgentProfile.RESEARCHER,
    AgentProfile.IMPLEMENTER,
    AgentProfile.ADVERSARY,
})

PARTITION_METHODS = ("llm_proposable", "director_only", "internal_only")


def _intent(kind: IntentKind, profile: AgentProfile) -> Intent:
    return Intent(kind=kind, proposed_by=profile.value, project_id="p1")


def _admitted(kind: IntentKind, profile: AgentProfile) -> bool:
    """The role gate's decision for ``(kind, profile)`` — admitted or refused."""
    try:
        _require_role(_intent(kind, profile))
    except GatewayRejection:
        return False
    return True


def _current_admission(kind: IntentKind, profile: AgentProfile) -> bool:
    """The declared authority semantics, read from the partitions.

    ``director_only`` precedes ``llm_proposable`` in ``_require_role``, so
    a kind in both is Director-only. ``internal_only`` admits only
    DETERMINISTIC. A kind in none of the partitions is refused for every
    profile (the ROLE-EXH-1 fail-closed rule; no current kind is
    unpartitioned).
    """
    if kind in IntentKind.director_only():
        return profile is AgentProfile.DIRECTOR
    if kind in IntentKind.internal_only():
        return profile is AgentProfile.DETERMINISTIC
    if kind in IntentKind.llm_proposable():
        return profile in LLM_AGENT_PROFILES
    return False


def test_admission_matrix_pins_every_current_kind_and_profile() -> None:
    """Every (kind, profile) pair keeps its current decision — no change."""
    for kind in IntentKind:
        for profile in AgentProfile:
            assert _admitted(kind, profile) is _current_admission(kind, profile), (
                kind.value, profile.value)


@pytest.mark.parametrize(
    ("name", "admitted_profiles"),
    [
        ("INSERT_TASK", LLM_AGENT_PROFILES),
        ("PROPOSE_GATE_OVERRIDE", LLM_AGENT_PROFILES),
        # In both llm_proposable and director_only: Director wins.
        ("PROPOSE_RESEARCH_PROGRAM", frozenset({AgentProfile.DIRECTOR})),
        # director_only only.
        ("PROPOSE_CLASSIFICATION_ACTION", frozenset({AgentProfile.DIRECTOR})),
        ("ADMIT_TASK", frozenset({AgentProfile.DETERMINISTIC})),
        ("RECORD_CLASSIFICATION", frozenset({AgentProfile.DETERMINISTIC})),
        ("RETRACT_SOURCE", frozenset({AgentProfile.DETERMINISTIC})),
        ("CONTRADICTION_RESOLUTION", frozenset({AgentProfile.DETERMINISTIC})),
    ],
)
def test_named_kind_admission_pins(
    name: str, admitted_profiles: frozenset[AgentProfile],
) -> None:
    """Exact per-profile decisions for representative current kinds."""
    kind = IntentKind[name]
    for profile in AgentProfile:
        assert _admitted(kind, profile) is (profile in admitted_profiles), (
            name, profile.value)


def test_unknown_profile_is_refused_with_role() -> None:
    """The unknown-profile path is unchanged: ROLE, kind preserved."""
    for kind in (IntentKind.INSERT_TASK,
                 IntentKind.PROPOSE_RESEARCH_PROGRAM,
                 IntentKind.ADMIT_TASK):
        with pytest.raises(GatewayRejection) as exc:
            _require_role(Intent(kind=kind, proposed_by="NOT_A_PROFILE",
                                 project_id="p1"))
        assert exc.value.code == ROLE
        assert exc.value.kind is kind


def test_partitions_are_exhaustive_and_effectively_disjoint() -> None:
    """Structural guard: every member classified; classes disjoint.

    No counts are hardcoded: the guard is over the live enum and the live
    partition methods, so it stays valid when new kinds are added (CRED-1)
    as long as each is classified. The effective admission classes are
    ``director_only``, ``internal_only`` and ``llm_proposable`` minus
    ``director_only`` (Director takes precedence), which must be pairwise
    disjoint; the declaration-level overlap permitted today is only
    ``director_only ⊆ llm_proposable`` (PROPOSE_RESEARCH_PROGRAM), never
    an ``internal_only`` overlap.
    """
    members = frozenset(IntentKind)
    llm = IntentKind.llm_proposable()
    director = IntentKind.director_only()
    internal = IntentKind.internal_only()

    union = llm | director | internal
    unclassified = sorted(m.value for m in members - union)
    assert union == members, f"unclassified IntentKind members: {unclassified}"

    effective = (director, internal, llm - director)
    for index, left in enumerate(effective):
        for right in effective[index + 1:]:
            overlap = sorted(m.value for m in left & right)
            assert left.isdisjoint(right), f"admission classes overlap: {overlap}"

    assert internal.isdisjoint(director)
    assert internal.isdisjoint(llm)


@pytest.mark.parametrize("profile", list(AgentProfile))
def test_a_kind_in_no_partition_is_refused_for_every_profile(
    monkeypatch: pytest.MonkeyPatch, profile: AgentProfile,
) -> None:
    """The fail-on-base scenario: a member removed from all three
    partitions (simulating a kind added without classification) is
    refused for every profile. On base code the four LLM profiles are
    admitted instead (pytest.raises sees no exception)."""
    for name in PARTITION_METHODS:
        patched = frozenset(getattr(IntentKind, name)()) - {IntentKind.INSERT_TASK}
        monkeypatch.setattr(
            IntentKind, name, classmethod(lambda cls, _set=patched: _set))

    assert IntentKind.INSERT_TASK not in IntentKind.llm_proposable()
    assert IntentKind.INSERT_TASK not in IntentKind.director_only()
    assert IntentKind.INSERT_TASK not in IntentKind.internal_only()

    with pytest.raises(GatewayRejection) as exc:
        _require_role(_intent(IntentKind.INSERT_TASK, profile))
    assert exc.value.code == ROLE
