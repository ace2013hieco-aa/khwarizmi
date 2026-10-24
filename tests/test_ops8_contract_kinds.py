"""OPS-8 — the contract names the legal proposal kinds.

The second live run had the question (OPS-7) but not the vocabulary: the model
answered `kind: "task-graph-planning"`, a plausible stage name outside the
profile's declared allowlist, and the runtime refused it `ROLE`. The refusal
was right; the prompt was incomplete. These tests pin both halves:

* every shipped profile's rendered contract lists exactly its
  ``authority.proposable_kinds`` (the same tuple the runtime enforces), and
* the listing is guidance only: an invented kind still refuses ``ROLE``, and a
  contract that *claims* an invented kind is legal does not widen the
  injected allowlist.
"""

from __future__ import annotations

import json
from typing import Any

from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import output_contract_for
from hermes.composition import (
    CloudModelSpec,
    EnvCredentialResolver,
    build_cloud_provider,
    build_model_binding,
)
from hermes.config import HermesConfig, ModelTierConfig
from hermes.core.intents import IntentKind
from hermes.security.boundaries import UntrustedContent
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import (
    FieldSpec,
    ModelProposal,
    ModelRefusal,
    ModelRequest,
    OutputContract,
    _contract_mapping,
)
from hermes.tools.providers.base import RequestSpec, TransportResponse

KEY = "sk-test-0123456789abcdefghijklmnop"
ENV = {"ANTHROPIC_API_KEY": KEY}
PUBLIC_IP = "93.184.216.34"


class _ScriptedTransport:
    """Records the request and returns one recorded Anthropic reply."""

    def __init__(self, response: TransportResponse) -> None:
        self.specs: list[RequestSpec] = []
        self._response = response

    def request(self, spec: RequestSpec) -> TransportResponse:
        self.specs.append(spec)
        return self._response


def _anthropic_reply(text: str) -> TransportResponse:
    body = {
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }
    return TransportResponse(status=200, body=json.dumps(body).encode("utf-8"),
                             content_type="application/json")


def _binding(transport: _ScriptedTransport) -> Any:
    credentials = EnvCredentialResolver(
        {"anthropic": "ANTHROPIC_API_KEY"}, environ=ENV)
    spec = CloudModelSpec(
        provider_id="anthropic", dialect="anthropic", model_id="test-model",
        api_key_env="ANTHROPIC_API_KEY")
    provider = build_cloud_provider(
        [spec], credentials=credentials, transport=transport,
        resolve=lambda host, port: (PUBLIC_IP,))
    return build_model_binding(
        HermesConfig(model_tiers=ModelTierConfig(m="anthropic:test-model")),
        [provider], credentials=credentials)


def _contract(
    *, proposable_kinds: tuple[str, ...] = ("INSERT_TASK", "BRANCH"),
) -> OutputContract:
    return OutputContract(
        name="proposal",
        fields=(FieldSpec("kind", "string"), FieldSpec("rationale", "string")),
        kind_field="kind", rationale_field="rationale",
        proposable_kinds=proposable_kinds)


def _request(contract: OutputContract) -> ModelRequest:
    return ModelRequest(
        tier="m", profile="planner", lease_generation="gen-ops8",
        prompt=(UntrustedContent(text="Does the effect hold?",
                                 origin="runtime.task", ref="task:ops8"),),
        output_contract=contract, rationale="propose the next step")


def _invoke(kind: str, *,
            proposable_kinds: tuple[str, ...] = ("INSERT_TASK", "BRANCH")
            ) -> tuple[Any, _ScriptedTransport]:
    transport = _ScriptedTransport(_anthropic_reply(
        json.dumps({"kind": kind, "rationale": "because"})))
    contract = _contract(proposable_kinds=proposable_kinds)
    outcome = _binding(transport).invoke(_request(contract))
    return outcome, transport


# ── 1. every shipped profile lists its own declared kinds ──


def test_every_shipped_profile_contract_lists_its_declared_kinds() -> None:
    profiles = load_profiles()
    assert len(profiles) == 6

    for spec in profiles.values():
        contract = output_contract_for(spec)
        mapping = _contract_mapping(contract)
        assert mapping is not None
        kinds = list(spec.authority.proposable_kinds)
        assert mapping["proposable_kinds"] == kinds

        # The values are *not* placed in the field's allowed_values: that
        # validation runs before the kind check and would turn a ROLE refusal
        # into a retryable MALFORMED_PAYLOAD.
        kind_field = next(
            field for field in mapping["fields"] if field["name"] == "kind")
        assert kind_field["allowed_values"] == []

        rendered = render_system(spec.name, mapping)
        expected = (
            'The "kind" field names the proposal kind. Use exactly one of: '
            + ", ".join(kinds) + ". Any other value is refused.")
        assert expected in rendered
        assert "The \"kind\" field names the proposal kind." in rendered


def test_every_shipped_profile_kind_is_accepted_by_the_router_allowlist() -> None:
    """The guidance cannot name a kind the injected allowlist always refuses."""
    allowed = {kind.value for kind in
               IntentKind.llm_proposable() | IntentKind.director_only()}
    for spec in load_profiles().values():
        assert set(spec.authority.proposable_kinds) <= allowed


# ── 2. the allowlist is still the authority ──


def test_an_invented_kind_still_refuses_role() -> None:
    outcome, _ = _invoke("task-graph-planning")
    assert isinstance(outcome, ModelRefusal)
    assert outcome.code == "ROLE"
    assert "outside the injected proposable allowlist" in outcome.detail


def test_a_legal_kind_still_drafts() -> None:
    outcome, transport = _invoke("INSERT_TASK")
    assert isinstance(outcome, ModelProposal)
    assert outcome.structured["kind"] == "INSERT_TASK"
    body = json.loads(transport.specs[0].body)
    assert ('Use exactly one of: INSERT_TASK, BRANCH. Any other value is '
            "refused.") in body["system"]


def test_the_listing_is_guidance_not_the_enforcement() -> None:
    """A contract that claims an invented kind is legal still refuses ROLE."""
    outcome, _ = _invoke(
        "task-graph-planning",
        proposable_kinds=("task-graph-planning",))
    assert isinstance(outcome, ModelRefusal)
    assert outcome.code == "ROLE"
