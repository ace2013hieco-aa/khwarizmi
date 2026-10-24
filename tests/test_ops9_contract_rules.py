"""OPS-9 — the contract states what the validator enforces.

Run 3 finally drafted, then refused for two reasons the prompt never stated: a
reply carrying both the single-proposal and the multi-proposal form, and a
delegation carrying invented keys (``task``, ``to``). The validator was right;
the contract was a lossy description of it. These tests pin the two statements
against the validator's own constants — not prose — plus the three behaviours:
both forms refuse, an unknown delegation key refuses, and one form with legal
keys drafts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import hermes.agents.runtime.run as run_module
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import (
    DELEGATION_KEYS,
    MULTI_PROPOSAL_FIELD,
    SINGLE_PROPOSAL_FIELD,
    AgentRuntime,
    output_contract_for,
)
from hermes.agents.runtime.types import (
    MALFORMED_PAYLOAD,
    DelegationState,
    RunLimits,
    TaskContext,
)
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import ModelProposal, _contract_mapping

PROJECT = "p-ops9"
LEASE = "gen-ops9"


class _ScriptedModel:
    """A model port serving one structured reply per profile, in order."""

    def __init__(self, scripts: dict[str, list[dict[str, Any]]]) -> None:
        self._scripts = {name: list(items) for name, items in scripts.items()}
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        script = self._scripts.get(request.profile)
        if not script:
            raise AssertionError(f"no scripted reply for {request.profile!r}")
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier=request.tier,
            profile=request.profile,
            lease_generation=request.lease_generation,
            structured=dict(script.pop(0)))


@dataclass(frozen=True, slots=True)
class _Applied:
    entity_id: str
    duplicate: bool


class _Applier:
    def __call__(self, intent: Any) -> _Applied:
        return _Applied(entity_id="ent_1", duplicate=False)


def _run(profile: str, structured: dict[str, Any], *,
         child_scripts: dict[str, list[dict[str, Any]]] | None = None
         ) -> tuple[Any, AgentRuntime]:
    scripts = {profile: [structured]}
    scripts.update(child_scripts or {})
    runtime = AgentRuntime(
        model=_ScriptedModel(scripts), orchestration=_Applier(),
        profiles=load_profiles())
    context = TaskContext(
        task_id="task-ops9", project_id=PROJECT, lease_generation=LEASE,
        limits=RunLimits(max_ticks=1))
    return runtime.run(profile, context), runtime


def _rendered(spec: Any) -> tuple[dict[str, Any], str]:
    mapping = _contract_mapping(output_contract_for(spec))
    assert mapping is not None
    return mapping, render_system(spec.name, mapping)


# ── 1. the statements, generated from the validator's constants ──


def test_every_profile_states_the_form_rule_and_the_delegation_keys() -> None:
    profiles = load_profiles()
    assert len(profiles) == 6

    for spec in profiles.values():
        mapping, rendered = _rendered(spec)
        assert mapping["single_form_field"] == SINGLE_PROPOSAL_FIELD
        assert mapping["multi_form_field"] == MULTI_PROPOSAL_FIELD
        assert mapping["delegation_keys"] == sorted(DELEGATION_KEYS)

        forms = (
            "Choose exactly one proposal form: the single-proposal form (a "
            f'top-level "{SINGLE_PROPOSAL_FIELD}" field) or the multi-proposal '
            f'form (a "{MULTI_PROPOSAL_FIELD}" array). A reply carrying both '
            "is refused; exactly one is allowed.")
        assert forms in rendered

        keys = ", ".join(sorted(DELEGATION_KEYS))
        delegation = (
            'If you output a "delegations" array, each item may carry only '
            f"these keys: {keys}. An unknown key is refused.")
        assert delegation in rendered


def test_the_prompt_reads_the_validator_key_set(monkeypatch: Any) -> None:
    """The drift guard: a new validator key appears without editing prose.

    If the prompt carried a hand-typed key list, the mutated key would be
    absent and this test would fail — which is exactly the failure the slice
    wants when the validator and the prompt diverge.
    """
    spec = load_profiles()["planner"]
    mutated = frozenset(set(run_module.DELEGATION_KEYS) | {"probe_key"})
    monkeypatch.setattr(run_module, "DELEGATION_KEYS", mutated)

    mapping, rendered = _rendered(spec)
    assert mapping["delegation_keys"] == sorted(mutated)
    assert "probe_key" in rendered
    for key in sorted(mutated):
        assert key in rendered


# ── 2. the validator is still the authority ──


def test_a_reply_with_both_forms_refuses_malformed_payload() -> None:
    result, _ = _run("critic", {
        "kind": "ABANDON", "rationale": "because", "payload": {},
        "proposals": [{"kind": "ABANDON", "rationale": "because",
                       "payload": {}}],
    })
    assert result.refusal_codes() == (MALFORMED_PAYLOAD,)
    assert "both the single-proposal and the multi-proposal form" in (
        result.refusals[0].detail)


def test_a_delegation_with_an_unknown_key_refuses() -> None:
    result, _ = _run("verifier", {
        "rationale": "delegate",
        "proposals": [],
        "delegations": [{"task": "x", "to": "y"}],
    })
    assert MALFORMED_PAYLOAD in result.refusal_codes()
    assert any("a delegation declares unknown keys: ['task', 'to']"
               in refusal.detail for refusal in result.refusals)


def test_a_single_form_with_a_legal_kind_drafts() -> None:
    result, _ = _run("critic", {
        "kind": "ABANDON", "rationale": "because", "payload": {},
    })
    assert result.refusal_codes() == ()
    assert [proposal.intent.kind.value for proposal in result.proposals] == [
        "ABANDON"]


def test_a_multi_form_with_a_legal_kind_drafts() -> None:
    result, _ = _run("critic", {
        "rationale": "because",
        "proposals": [{"kind": "ABANDON", "rationale": "because",
                       "payload": {}}],
    })
    assert result.refusal_codes() == ()
    assert [proposal.intent.kind.value for proposal in result.proposals] == [
        "ABANDON"]


def test_a_delegation_with_the_legal_keys_reaches_a_child() -> None:
    result, runtime = _run(
        "verifier",
        {
            "rationale": "delegate",
            "proposals": [],
            "delegations": [{"profile": "critic", "spec": {"topic": "x"}}],
        },
        child_scripts={"critic": [{
            "kind": "ABANDON", "rationale": "because", "payload": {}}]})
    records = runtime.delegation_records(run_id=result.run_id)
    assert records
    assert records[0].state == DelegationState.DONE.value
    assert not any("unknown keys" in refusal.detail
                   for refusal in result.refusals)
