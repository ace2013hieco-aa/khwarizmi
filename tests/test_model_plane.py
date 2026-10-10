"""Model plane tests (ARCHITECTURE_DELTA §2.1 — the Model Provider API).

Covers the port's whole contract:

- **provider abstraction + policy selection** — tier → config ref → provider/model,
  with no vendor named anywhere in the module;
- **capability advertisement** — an incapable model is skipped, and the request's
  capability needs are actually met by whatever serves it;
- **structured-output validation** — closed schema, typed fields, declared value
  sets, required rationale, and the two authority refusals (`PROPOSAL`, `ROLE`);
- **streaming envelope** — every chunk's text is an `UntrustedContent`;
- **tool-call translation** — neutral shape, undeclared tool refused, never
  executed here;
- **retries with backoff** — transient retried, permanent not, delays recorded;
- **fallback chain** — attempt, then hop, then `ProviderUnavailableError`;
- **accounting exactness** — one row per provider call, refusals accounted too,
  and `verify_accounting` failing closed on an untracked call;
- **credential discipline** — credential-class option names refused without
  naming the value, live secrets refused loudly, no credential field anywhere;
- **replay** — byte-identical fixtures, recomputed `fx_` identity, and a refusing
  inner transport proving zero live contact;
- **boundedness** — the 4 KiB proposal cap overflowing to artifact bytes that
  carry no identity.

The plane is a port: nothing asserted here may decide a transition.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from hermes.security.boundaries import UntrustedContent
from hermes.tools.models.router import (
    CREDENTIAL_ONLY_POLICY,
    DECISION_SHAPED_KEYS,
    LOCK,
    MALFORMED_PAYLOAD,
    MAX_PROPOSAL_BYTES,
    PROPOSAL,
    RATIONALE,
    REFUSAL_CODES,
    ROLE,
    TERMINAL_REFUSALS,
    ChunkKind,
    Credential,
    FieldSpec,
    ModelArtifactOverflow,
    ModelCall,
    ModelCallAccount,
    ModelFixture,
    ModelPlaneInvariantError,
    ModelPlanePolicy,
    ModelProfile,
    ModelProposal,
    ModelRefusal,
    ModelRequest,
    ModelSettings,
    ModelStreamResult,
    NeutralToolCallTranslator,
    OutputContract,
    ProviderChunk,
    RecordedModelProvider,
    TokenUsage,
    dump_model_fixtures,
    load_model_fixtures,
    model_fixture_id_of,
    normalized_model_call,
    parse_model_ref,
)
from hermes.tools.research_sources import (
    PermanentProviderError,
    ProviderUnavailableError,
    ProviderValidationError,
    RetryPolicy,
    TransientProviderError,
)

CLOCK_STAMP = "2026-01-01T00:00:00.000000+00:00"
SECRET = "sk-live-DO-NOT-RECORD-0123456789"

TIERS = ("s", "m", "c")


# ═══════════════════════ fakes ═══════════════════════


class FakeClock:
    """Frozen clock that also records every backoff sleep."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    def now_utc(self) -> str:
        return CLOCK_STAMP

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


class ScriptedProvider:
    """A scripted `ModelProvider` that records every call it receives.

    The recorded call list is the plane's evidence: what a caller asked for, and
    what the model was actually handed.
    """

    def __init__(
        self,
        provider_id: str = "alpha",
        profiles: tuple[ModelProfile, ...] = (),
        script: list[Any] | None = None,
        stream_script: list[Any] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self._profiles = profiles
        self._script = list(script or [])
        self._stream_script = list(stream_script or [])
        self.calls: list[ModelCall] = []
        self.stream_calls: list[ModelCall] = []

    def describe(self) -> tuple[ModelProfile, ...]:
        return self._profiles

    def invoke(self, call: ModelCall) -> Any:
        self.calls.append(call)
        if not self._script:
            return _response("{}")
        action = self._script.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action

    def stream(self, call: ModelCall) -> tuple[ProviderChunk, ...]:
        self.stream_calls.append(call)
        if not self._stream_script:
            return ()
        action = self._stream_script.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action

    @property
    def calls_made(self) -> int:
        return len(self.calls) + len(self.stream_calls)


class RefusingProvider:
    """Inner provider that must never be contacted (the replay proof)."""

    def __init__(self, provider_id: str = "alpha",
                 profiles: tuple[ModelProfile, ...] = ()) -> None:
        self.provider_id = provider_id
        self._profiles = profiles
        self.contacted = 0

    def describe(self) -> tuple[ModelProfile, ...]:
        return self._profiles

    def invoke(self, call: ModelCall) -> Any:
        self.contacted += 1
        raise AssertionError("live model contacted during replay")

    def stream(self, call: ModelCall) -> tuple[ProviderChunk, ...]:
        self.contacted += 1
        raise AssertionError("live model contacted during replay")


class FixedCredentials:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def resolve(self, provider_id: str) -> Credential | None:
        if provider_id not in self._values:
            return None
        return Credential(name="model_api_key", _value=self._values[provider_id])


# ═══════════════════════ helpers ═══════════════════════


def _untrusted(text: str, origin: str = "test.prompt",
               ref: str = "ref-1") -> UntrustedContent:
    return UntrustedContent(text=text, origin=origin, ref=ref)


def _response(text: str, *, input_tokens: int = 10, output_tokens: int = 5,
              finish: str = "stop", tool_calls_raw: str = "") -> Any:
    from hermes.tools.models.router import ModelResponse

    return ModelResponse(text=text, usage=TokenUsage(input_tokens, output_tokens),
                         finish_reason=finish, tool_calls_raw=tool_calls_raw)


def _profile(model_id: str = "m1", provider_id: str = "alpha",
             **overrides: Any) -> ModelProfile:
    fields: dict[str, Any] = {
        "context_window_tokens": 8000,
        "max_output_tokens": 1024,
        "supports_streaming": True,
        "supports_tool_calls": True,
        "supports_structured_output": True,
        "input_cost_per_1k_tokens": 0.5,
        "output_cost_per_1k_tokens": 1.5,
    }
    fields.update(overrides)
    return ModelProfile(provider_id=provider_id, model_id=model_id, **fields)


def _policy(**overrides: Any) -> ModelPlanePolicy:
    fields: dict[str, Any] = {
        "tier_refs": {"s": "alpha:m1", "m": "beta:m2", "c": "gamma:m3"},
        "fallback_chain": ("m", "c"),
        "retry_policy": RetryPolicy(max_retries=2, base_delay_seconds=1.0,
                                    max_delay_seconds=30.0, jitter=True),
    }
    fields.update(overrides)
    return ModelPlanePolicy(**fields)


def _router(providers: list[Any], *, policy: ModelPlanePolicy | None = None,
            clock: FakeClock | None = None,
            proposable: frozenset[str] = frozenset({"INSERT_TASK", "BRANCH"}),
            tools: frozenset[str] = frozenset({"search"}),
            credentials: Any = None) -> Any:
    from hermes.tools.models.router import ModelRouter

    resolved = clock if clock is not None else FakeClock()
    return ModelRouter(
        providers=providers,
        policy=policy if policy is not None else _policy(),
        clock=resolved,
        proposable_kinds=proposable,
        tool_allowlist=tools,
        credentials=credentials,
        sleep=resolved.sleep,
        jitter_source=lambda low, high: 1.0,
    )


def _request(**overrides: Any) -> ModelRequest:
    fields: dict[str, Any] = {
        "tier": "s",
        "profile": "director",
        "lease_generation": "lease-gen-7",
        "prompt": (_untrusted("Summarise the admitted evidence."),),
    }
    fields.update(overrides)
    return ModelRequest(**fields)


JSON_CONTRACT = OutputContract(
    name="json_proposal",
    fields=(FieldSpec("text", "string"),),
)

DIRECTOR_CONTRACT = OutputContract(
    name="director_proposal",
    fields=(
        FieldSpec("kind", "string"),
        FieldSpec("rationale", "string", required=False),
    ),
    kind_field="kind",
    rationale_field="rationale",
)


def _ok_json(text: str = "hello") -> Any:
    return _response(json.dumps({"text": text}))


def _director(kind: str = "INSERT_TASK", rationale: str = "because") -> Any:
    return _response(json.dumps({"kind": kind, "rationale": rationale}))


# ═══════════════════════ module-level invariants ═══════════════════════


class TestModuleInvariants:
    def test_refusal_codes_are_exactly_the_frozen_subset(self) -> None:
        # §2.1 introduces no new refusal code; every code already exists in the
        # gateway vocabulary.
        assert frozenset(
            {LOCK, MALFORMED_PAYLOAD, PROPOSAL, RATIONALE, ROLE}) == REFUSAL_CODES

    def test_terminal_refusals_are_a_subset_of_refusal_codes(self) -> None:
        assert TERMINAL_REFUSALS <= REFUSAL_CODES

    def test_proposal_cap_is_the_event_payload_cap(self) -> None:
        assert MAX_PROPOSAL_BYTES == 4096

    def test_module_names_no_vendor(self) -> None:
        source = _module_source()
        for vendor in ("openai", "anthropic", "claude", "gemini", "google",
                       "mistral", "cohere", "bedrock", "azure", "ollama",
                       "vllm", "llama", "gpt-"):
            assert vendor not in source.lower(), f"vendor literal {vendor!r} in the model plane"

    def test_module_never_names_a_vendor_sdk_import(self) -> None:
        source = _module_source()
        for banned in ("import openai", "import anthropic", "import google",
                       "from openai", "from anthropic", "from google"):
            assert banned not in source.lower()

    def test_direct_hermes_imports_are_within_the_allowed_direction(self) -> None:
        """§3.1: model-plane code imports `hermes.tools.*` + stdlib only, plus the
        envelope module §2.1 Outputs requires."""
        allowed = {
            "hermes.tools.models.router",
            "hermes.tools.providers.redact",
            "hermes.tools.providers.replay",
            "hermes.tools.research_sources",
            "hermes.security.boundaries",
        }
        for module in _module_imports():
            if not module.startswith("hermes"):
                continue
            assert module in allowed, f"model plane imported {module!r}"
        for forbidden in ("hermes.research", "hermes.core", "hermes.persistence",
                          "hermes.artifacts", "hermes.recovery"):
            assert not any(module.startswith(forbidden)
                           for module in _module_imports()), forbidden

    def test_module_never_reads_the_intent_vocabulary(self) -> None:
        # The proposable allowlist is injected; the plane must not reach up into
        # `core` for it (that is what keeps core out of the plane). Checked over
        # parsed code, because the module docstring legitimately *names* the
        # thing it refuses to import.
        tree = ast.parse(_module_source())
        referenced: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                referenced.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced.add(node.attr)
        assert "IntentKind" not in referenced
        assert "llm_proposable" not in referenced

    def test_package_init_reexports_nothing(self) -> None:
        # An eager re-export would grow an import edge from `hermes.tools` into
        # the model plane (and, transitively, into research through
        # tools.research_sources).
        import hermes.tools.models as package

        assert package.__all__ == []


class TestFrozenSurfaces:
    def test_request_surface_is_frozen(self) -> None:
        assert ModelRequest.field_names() == frozenset(
            {"tier", "profile", "lease_generation", "prompt", "output_contract",
             "rationale", "max_output_tokens", "tools", "options"})

    def test_proposal_surface_is_frozen(self) -> None:
        assert set(_field_names(ModelProposal)) == {
            "provider_id", "model_id", "tier", "profile", "lease_generation",
            "content", "structured", "rationale", "tool_calls", "overflow",
            "account"}

    def test_proposal_carries_no_identity(self) -> None:
        proposal = ModelProposal(provider_id="alpha", model_id="m1", tier="s",
                                 profile="director", lease_generation="g")
        assert not hasattr(proposal, "proposal_id")
        assert not hasattr(proposal, "artifact_ref")
        assert not hasattr(proposal, "content_hash")
        assert isinstance(proposal.structured, dict)

    def test_overflow_carries_no_identity(self) -> None:
        # §3.3: the write boundary recomputes identity by rule, so the transfer
        # envelope must not offer one to trust.
        overflow = ModelArtifactOverflow(body=b"{}", size_bytes=2)
        assert set(_field_names(ModelArtifactOverflow)) == {
            "body", "size_bytes", "media_type"}
        assert not hasattr(overflow, "content_hash")
        assert not hasattr(overflow, "artifact_id")

    def test_call_form_has_no_credential_field(self) -> None:
        assert not any("credential" in name or "secret" in name or "api_key" in name
                       for name in _field_names(ModelCall))

    def test_account_row_surface_is_frozen(self) -> None:
        assert set(_field_names(ModelCallAccount)) == {
            "sequence", "tier", "profile", "provider_id", "model_id", "attempt",
            "outcome", "lease_generation", "request_digest", "normalized_request",
            "retrieved_at", "usage", "context_tokens", "refusal_code",
            "failure_class", "price_usd"}

    def test_decision_shaped_keys_are_the_verdict_vocabulary(self) -> None:
        assert "verdict" in DECISION_SHAPED_KEYS
        assert "decision" in DECISION_SHAPED_KEYS


# ═══════════════════════ request guards ═══════════════════════


class TestRequestGuards:
    def test_missing_lease_refuses_lock(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider])
        result = router.invoke(_request(lease_generation="  "))
        assert isinstance(result, ModelRefusal)
        assert result.code == LOCK
        assert provider.calls_made == 0

    def test_refusal_before_any_call_is_accounted(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider])
        result = router.invoke(_request(lease_generation=""))
        assert isinstance(result, ModelRefusal)
        rows = router.accounting()
        assert len(rows) == 1
        assert rows[0].attempt == 0
        assert rows[0].outcome == "REFUSED"
        assert rows[0].refusal_code == LOCK
        assert rows[0].lease_generation == ""
        router.verify_accounting()

    def test_decision_contract_refuses_proposal(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider])
        contract = OutputContract(name="verdict", fields=(FieldSpec("text", "string"),),
                                  allows_decision=True)
        result = router.invoke(_request(output_contract=contract))
        assert isinstance(result, ModelRefusal)
        assert result.code == PROPOSAL
        assert provider.calls_made == 0

    def test_unknown_request_keys_refuse(self) -> None:
        result = ModelRequest.from_mapping({
            "tier": "s", "profile": "director", "lease_generation": "g",
            "system_prompt": "smuggled"})
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD
        assert "system_prompt" in result.detail

    def test_missing_required_request_keys_refuse(self) -> None:
        result = ModelRequest.from_mapping({"tier": "s"})
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD

    def test_request_mapping_roundtrip_matches_the_frozen_surface(self) -> None:
        built = ModelRequest.from_mapping({
            "tier": "m", "profile": "adversary", "lease_generation": "gen-3",
            "rationale": "why", "tools": ("search",), "options": {"temperature": "0"}})
        assert isinstance(built, ModelRequest)
        assert built.tier == "m"
        assert built.tools == ("search",)
        assert built.options == {"temperature": "0"}

    def test_unknown_contract_field_type_refuses(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider])
        contract = OutputContract(name="bad",
                                  fields=(FieldSpec("text", "quantum"),))
        result = router.invoke(_request(output_contract=contract))
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD
        assert "quantum" in result.detail

    def test_tools_without_an_allowlist_refuse(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider], tools=frozenset())
        result = router.invoke(_request(tools=("search",)))
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD
        assert provider.calls_made == 0

    def test_unknown_model_option_refuses(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider])
        result = router.invoke(_request(options={"temperature": "0.2"}))
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD
        assert "temperature" in result.detail
        assert provider.calls_made == 0

    def test_declared_model_option_is_forwarded(self) -> None:
        profile = _profile(settings=ModelSettings(options={"temperature": "0"}))
        provider = ScriptedProvider("alpha", (profile,), [_ok_json()])
        router = _router([provider])
        result = router.invoke(_request(options={"temperature": "0.2"}))
        assert isinstance(result, ModelProposal)
        assert provider.calls[0].options["temperature"] == "0.2"


# ═══════════════════════ policy selection ═══════════════════════


class TestPolicySelection:
    def test_config_tiers_drop_empty_values_and_parse_refs(self) -> None:
        policy = ModelPlanePolicy.from_config_tiers(
            {"s": "alpha:m1", "m": "", "c": "  "}, fallback_chain=("m", "c"))
        assert policy.tier_refs == {"s": "alpha:m1"}

    def test_malformed_config_ref_fails_fast(self) -> None:
        with pytest.raises(ProviderValidationError):
            ModelPlanePolicy.from_config_tiers({"s": "not-a-ref"})
        with pytest.raises(ProviderValidationError):
            parse_model_ref("alpha:")
        with pytest.raises(ProviderValidationError):
            parse_model_ref("alpha:m1:extra")

    def test_tier_order_prefers_the_requested_tier(self) -> None:
        policy = _policy(fallback_chain=("m", "c", "s"))
        assert policy.tier_order("s") == ("s", "m", "c")

    def test_unconfigured_tier_refuses(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider], policy=_policy(tier_refs={"m": "beta:m2"}))
        result = router.invoke(_request(tier="s"))
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD
        assert "no model configured" in result.detail

    def test_unregistered_provider_refuses(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider], policy=_policy(tier_refs={"s": "delta:m9"}))
        result = router.invoke(_request())
        assert isinstance(result, ModelRefusal)
        assert "no provider registered" in result.detail

    def test_unadvertised_model_refuses(self) -> None:
        provider = ScriptedProvider("alpha", (_profile("other"),), [_ok_json()])
        router = _router([provider])
        result = router.invoke(_request())
        assert isinstance(result, ModelRefusal)
        assert "does not advertise" in result.detail

    def test_model_not_serving_the_tier_refuses(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(tiers=("c",)),), [_ok_json()])
        router = _router([provider])
        result = router.invoke(_request(tier="s"))
        assert isinstance(result, ModelRefusal)
        assert "does not advertise tier" in result.detail

    def test_provider_without_an_id_is_rejected(self) -> None:
        with pytest.raises(ProviderValidationError):
            _router([RefusingProvider(provider_id="")])

    def test_describe_is_ordered_and_complete(self) -> None:
        alpha = ScriptedProvider("alpha", (_profile("m2"), _profile("m1")), [])
        beta = ScriptedProvider("beta", (_profile("m2", provider_id="beta"),), [])
        router = _router([beta, alpha])
        described = router.describe()
        assert [(p.provider_id, p.model_id) for p in described] == [
            ("alpha", "m1"), ("alpha", "m2"), ("beta", "m2")]
        assert router.provider_ids() == ("alpha", "beta")
        assert router.profile_of("alpha", "m1") is not None
        assert router.profile_of("alpha", "zz") is None


# ═══════════════════════ capability advertisement ═══════════════════════


class TestCapabilities:
    def test_incapable_model_refusal_names_the_gap(self) -> None:
        profile = _profile(supports_structured_output=False)
        provider = ScriptedProvider("alpha", (profile,), [_ok_json()])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD
        assert "structured output" in result.detail
        assert provider.calls_made == 0

    def test_incapable_candidate_is_skipped_for_a_capable_one(self) -> None:
        weak = _profile("m1", supports_structured_output=False)
        strong = _profile("m2", provider_id="beta")
        alpha = ScriptedProvider("alpha", (weak,), [_ok_json()])
        beta = ScriptedProvider("beta", (strong,), [_ok_json("done")])
        router = _router([alpha, beta])
        result = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(result, ModelProposal)
        assert result.provider_id == "beta"
        assert result.tier == "m"
        assert alpha.calls_made == 0

    def test_tools_never_reach_a_model_that_cannot_use_them(self) -> None:
        profile = _profile(supports_tool_calls=False)
        provider = ScriptedProvider("alpha", (profile,), [_ok_json()])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke(_request(tools=("search",)))
        assert isinstance(result, ModelRefusal)
        assert "tool calls" in result.detail
        assert provider.calls_made == 0

    def test_streaming_requires_the_advertised_capability(self) -> None:
        profile = _profile(supports_streaming=False)
        provider = ScriptedProvider("alpha", (profile,), [_ok_json()])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke_stream(_request())
        assert result.refusal is not None
        assert "streaming" in result.refusal.detail

    def test_context_window_overflow_refuses(self) -> None:
        profile = _profile(context_window_tokens=100)
        provider = ScriptedProvider("alpha", (profile,), [_ok_json()])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke(_request(prompt=(_untrusted("x" * 4000),)))
        assert isinstance(result, ModelRefusal)
        assert "context window" in result.detail

    def test_request_cannot_raise_the_output_cap(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(max_output_tokens=256),),
                                    [_ok_json()])
        router = _router([provider])
        result = router.invoke(_request(max_output_tokens=10 ** 9))
        assert isinstance(result, ModelProposal)
        assert provider.calls[0].max_output_tokens == 256

    def test_model_declared_setting_lowers_the_cap(self) -> None:
        profile = _profile(max_output_tokens=1024,
                           settings=ModelSettings(max_output_tokens=64))
        provider = ScriptedProvider("alpha", (profile,), [_ok_json()])
        router = _router([provider])
        assert isinstance(router.invoke(_request()), ModelProposal)
        assert provider.calls[0].max_output_tokens == 64

    def test_request_may_lower_the_cap(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(max_output_tokens=1024),),
                                    [_ok_json()])
        router = _router([provider])
        assert isinstance(router.invoke(_request(max_output_tokens=32)),
                          ModelProposal)
        assert provider.calls[0].max_output_tokens == 32

    def test_declared_timeout_is_honoured_below_the_policy_ceiling(self) -> None:
        profile = _profile(settings=ModelSettings(timeout_seconds=5.0))
        provider = ScriptedProvider("alpha", (profile,), [_ok_json()])
        router = _router([provider], policy=_policy(timeout_seconds=120.0))
        assert isinstance(router.invoke(_request()), ModelProposal)
        assert provider.calls[0].timeout_seconds == 5.0


# ═══════════════════════ retries and backoff ═══════════════════════


class TestRetryAndBackoff:
    def test_transient_failure_is_retried_then_succeeds(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            TransientProviderError("throttled", hazard_class="THROTTLED"),
            _ok_json(),
        ])
        clock = FakeClock()
        router = _router([provider], clock=clock)
        result = router.invoke(_request())
        assert isinstance(result, ModelProposal)
        assert provider.calls_made == 2
        assert clock.slept == [2.0]

    def test_backoff_delays_are_exponential(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            TransientProviderError("a", hazard_class="TIMEOUT"),
            TransientProviderError("b", hazard_class="TIMEOUT"),
            TransientProviderError("c", hazard_class="TIMEOUT"),
        ])
        clock = FakeClock()
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()),
                         clock=clock)
        # Every candidate exhausted its transient retries: that is a
        # transport-level failure, so the existing provider hierarchy raises.
        with pytest.raises(ProviderUnavailableError):
            router.invoke(_request())
        assert clock.slept == [2.0, 4.0]
        assert router.backoff_delays == (2.0, 4.0)

    def test_backoff_is_capped_at_the_policy_ceiling(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            TransientProviderError("a", hazard_class="TIMEOUT"),
            TransientProviderError("b", hazard_class="TIMEOUT"),
            TransientProviderError("c", hazard_class="TIMEOUT"),
            TransientProviderError("d", hazard_class="TIMEOUT"),
            TransientProviderError("e", hazard_class="TIMEOUT"),
        ])
        clock = FakeClock()
        router = _router(
            [provider],
            policy=_policy(tier_refs={"s": "alpha:m1"}, fallback_chain=(),
                           retry_policy=RetryPolicy(
                               max_retries=4, base_delay_seconds=1.0,
                               max_delay_seconds=5.0, jitter=False)),
            clock=clock)
        with pytest.raises(ProviderUnavailableError):
            router.invoke(_request())
        assert clock.slept == [2.0, 4.0, 5.0, 5.0]

    def test_permanent_failure_is_not_retried(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            PermanentProviderError("malformed", hazard_class="MALFORMED_200"),
            _ok_json(),
        ])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        with pytest.raises(ProviderUnavailableError):
            router.invoke(_request())
        assert provider.calls_made == 1

    def test_exhausted_retries_move_to_the_fallback_candidate(self) -> None:
        alpha = ScriptedProvider("alpha", (_profile(),), [
            TransientProviderError("a", hazard_class="TIMEOUT"),
            TransientProviderError("b", hazard_class="TIMEOUT"),
            TransientProviderError("c", hazard_class="TIMEOUT"),
        ])
        beta = ScriptedProvider("beta",
                                (_profile("m2", provider_id="beta"),),
                                [_ok_json("from beta")])
        router = _router([alpha, beta])
        result = router.invoke(_request())
        assert isinstance(result, ModelProposal)
        assert result.provider_id == "beta"
        assert alpha.calls_made == 3
        assert beta.calls_made == 1


# ═══════════════════════ fallback chain ═══════════════════════


class TestFallbackChain:
    def test_primary_failure_falls_back_on_permanent_error(self) -> None:
        alpha = ScriptedProvider("alpha", (_profile(),), [
            PermanentProviderError("boom", hazard_class="MALFORMED_200")])
        beta = ScriptedProvider("beta", (_profile("m2", provider_id="beta"),),
                                [_ok_json("beta answered")])
        router = _router([alpha, beta])
        result = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(result, ModelProposal)
        assert result.provider_id == "beta"
        assert result.tier == "m"
        assert result.content is not None
        assert result.content.text == '{"text": "beta answered"}'

    def test_every_candidate_failing_raises_provider_unavailable(self) -> None:
        alpha = ScriptedProvider("alpha", (_profile(),), [
            PermanentProviderError("a", hazard_class="MALFORMED_200")])
        beta = ScriptedProvider("beta", (_profile("m2", provider_id="beta"),), [
            PermanentProviderError("b", hazard_class="MALFORMED_200")])
        gamma = ScriptedProvider("gamma", (_profile("m3", provider_id="gamma"),), [
            PermanentProviderError("c", hazard_class="MALFORMED_200")])
        router = _router([alpha, beta, gamma])
        with pytest.raises(ProviderUnavailableError) as excinfo:
            router.invoke(_request())
        notes = excinfo.value.notes
        assert len(notes) == 3
        assert notes[0].startswith("alpha/m1 (tier s)")
        assert notes[1].startswith("beta/m2 (tier m)")
        assert notes[2].startswith("gamma/m3 (tier c)")
        router.verify_accounting()
        assert router.provider_attempts == 3

    def test_terminal_refusal_does_not_fall_back(self) -> None:
        # A ROLE breach must stop the walk: asking a second model the same
        # illegal question is not a fix.
        alpha = ScriptedProvider("alpha", (_profile(),),
                                 [_director(kind="ADMIT_TASK")])
        beta = ScriptedProvider("beta", (_profile("m2", provider_id="beta"),),
                                [_director(kind="INSERT_TASK")])
        router = _router([alpha, beta])
        result = router.invoke(_request(output_contract=DIRECTOR_CONTRACT))
        assert isinstance(result, ModelRefusal)
        assert result.code == ROLE
        assert beta.calls_made == 0

    def test_terminal_refusal_is_not_retried_on_the_same_candidate(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _ok_json(), _ok_json(), _ok_json()])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        contract = OutputContract(name="verdict", fields=(FieldSpec("text", "string"),),
                                  allows_decision=True)
        result = router.invoke(_request(output_contract=contract))
        assert isinstance(result, ModelRefusal)
        assert result.code == PROPOSAL
        assert provider.calls_made == 0


# ═══════════════════════ structured-output validation ═══════════════════════


class TestStructuredOutput:
    def test_unknown_output_key_refuses_then_retries(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response(json.dumps({"text": "ok", "injected": "x"})),
            _ok_json("clean"),
        ])
        router = _router([provider])
        result = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(result, ModelProposal)
        assert provider.calls_made == 2
        assert result.structured == {"text": "clean"}

    def test_missing_required_field_refuses(self) -> None:
        # An empty object carries no unknown keys, so the required-field check
        # is the one that fires.
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response("{}") for _ in range(3)])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD
        assert "required field" in result.detail

    def test_type_mismatch_refuses(self) -> None:
        contract = OutputContract(name="typed",
                                  fields=(FieldSpec("count", "integer"),))
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response(json.dumps({"count": "seven"})) for _ in range(3)])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke(_request(output_contract=contract))
        assert isinstance(result, ModelRefusal)
        assert "declared type" in result.detail

    def test_declared_value_set_is_enforced(self) -> None:
        contract = OutputContract(
            name="enumerated",
            fields=(FieldSpec("mode", "string",
                              allowed_values=frozenset({"FAST", "SLOW"})),))
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response(json.dumps({"mode": "TURBO"})) for _ in range(3)])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke(_request(output_contract=contract))
        assert isinstance(result, ModelRefusal)
        assert "outside its declared values" in result.detail

    def test_integer_field_rejects_a_boolean(self) -> None:
        contract = OutputContract(name="typed",
                                  fields=(FieldSpec("count", "integer"),))
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response(json.dumps({"count": True})) for _ in range(3)])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke(_request(output_contract=contract))
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD

    def test_non_json_output_refuses(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response("not json at all") for _ in range(3)])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(result, ModelRefusal)
        assert "not valid JSON" in result.detail

    def test_json_array_output_refuses(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response("[1, 2, 3]") for _ in range(3)])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(result, ModelRefusal)
        assert "must be a JSON object" in result.detail

    def test_decision_shaped_output_refuses_without_a_retry(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response(json.dumps({"decision": "APPROVE"})) for _ in range(3)])
        router = _router([provider])
        result = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(result, ModelRefusal)
        assert result.code == PROPOSAL
        assert provider.calls_made == 1

    def test_kind_outside_the_injected_allowlist_refuses_role(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),),
                                    [_director(kind="ADMIT_TASK")])
        router = _router([provider])
        result = router.invoke(_request(output_contract=DIRECTOR_CONTRACT))
        assert isinstance(result, ModelRefusal)
        assert result.code == ROLE
        assert "ADMIT_TASK" in result.detail
        assert provider.calls_made == 1

    def test_kind_inside_the_allowlist_is_accepted(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),),
                                    [_director(kind="BRANCH")])
        router = _router([provider])
        result = router.invoke(_request(output_contract=DIRECTOR_CONTRACT))
        assert isinstance(result, ModelProposal)
        assert result.structured == {"kind": "BRANCH", "rationale": "because"}

    def test_absent_rationale_refuses(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response(json.dumps({"kind": "INSERT_TASK"})) for _ in range(3)])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke(_request(output_contract=DIRECTOR_CONTRACT))
        assert isinstance(result, ModelRefusal)
        assert result.code == RATIONALE

    def test_empty_rationale_refuses(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _director(rationale="   ") for _ in range(3)])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke(_request(output_contract=DIRECTOR_CONTRACT))
        assert isinstance(result, ModelRefusal)
        assert result.code == RATIONALE

    def test_no_contract_accepts_free_text(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),),
                                    [_response("free-form answer")])
        router = _router([provider])
        result = router.invoke(_request())
        assert isinstance(result, ModelProposal)
        assert result.structured == {}
        assert result.content is not None
        assert result.content.text == "free-form answer"


# ═══════════════════════ output envelope + boundedness ═══════════════════════


class TestEnvelopeAndBounds:
    def test_model_output_is_enveloped_and_str_safe(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),),
                                    [_response("SECRET-ANSWER-BODY")])
        router = _router([provider])
        result = router.invoke(_request())
        assert isinstance(result, ModelProposal)
        assert result.content is not None
        assert isinstance(result.content, UntrustedContent)
        assert not isinstance(result.content, str)
        assert "SECRET-ANSWER-BODY" not in str(result.content)
        assert "SECRET-ANSWER-BODY" not in repr(result.content)
        assert "SECRET-ANSWER-BODY" in result.content.text

    def test_rationale_is_enveloped(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_director()])
        router = _router([provider])
        result = router.invoke(_request(output_contract=DIRECTOR_CONTRACT))
        assert isinstance(result, ModelProposal)
        assert result.rationale is not None
        assert "because" in result.rationale.text
        assert "because" not in str(result.rationale)

    def test_oversized_proposal_overflows_to_artifact_bytes(self) -> None:
        huge = "y" * (MAX_PROPOSAL_BYTES + 200)
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json(huge)])
        router = _router([provider])
        result = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(result, ModelProposal)
        assert result.overflow is not None
        assert result.overflow.size_bytes > MAX_PROPOSAL_BYTES
        # The bounded fields are emptied: the payload lives in the overflow.
        assert result.structured == {}
        assert result.content is None
        assert result.tool_calls == ()
        payload = json.loads(result.overflow.body.decode("utf-8"))
        assert payload["structured"]["text"] == huge

    def test_overflow_disabled_refuses_rationale(self) -> None:
        huge = "y" * (MAX_PROPOSAL_BYTES + 200)
        provider = ScriptedProvider("alpha", (_profile(),), [
            _ok_json(huge) for _ in range(3)])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=(),
                                        allow_artifact_overflow=False))
        result = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(result, ModelRefusal)
        assert result.code == RATIONALE

    def test_proposal_within_the_cap_does_not_overflow(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json("small")])
        router = _router([provider])
        result = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(result, ModelProposal)
        assert result.overflow is None


# ═══════════════════════ streaming envelope ═══════════════════════


class TestStreaming:
    def _chunks(self) -> tuple[ProviderChunk, ...]:
        return (
            ProviderChunk(kind=ChunkKind.DELTA, text="he"),
            ProviderChunk(kind=ChunkKind.DELTA, text="llo"),
            ProviderChunk(kind=ChunkKind.USAGE, usage=TokenUsage(7, 3)),
            ProviderChunk(kind=ChunkKind.END),
        )

    def test_stream_chunks_are_enveloped(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [],
                                    stream_script=[self._chunks()])
        router = _router([provider])
        result = router.invoke_stream(_request())
        assert isinstance(result, ModelStreamResult)
        assert result.refusal is None
        deltas = [chunk for chunk in result.chunks
                  if chunk.kind is ChunkKind.DELTA]
        assert len(deltas) == 2
        for chunk in deltas:
            assert isinstance(chunk.text, UntrustedContent)
            assert chunk.text.text not in str(chunk.text)

    def test_stream_text_concatenates_deltas(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [],
                                    stream_script=[self._chunks()])
        router = _router([provider])
        result = router.invoke_stream(_request())
        assert result.text == "hello"
        assert len(list(result.iter_chunks())) == 4

    def test_stream_carries_usage_and_is_accounted(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [],
                                    stream_script=[self._chunks()])
        router = _router([provider])
        result = router.invoke_stream(_request())
        assert result.account is not None
        assert result.account.usage == TokenUsage(7, 3)
        assert result.account.context_tokens == 7
        router.verify_accounting()
        assert router.provider_attempts == 1

    def test_stream_marks_the_call_as_streaming(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [],
                                    stream_script=[self._chunks()])
        router = _router([provider])
        router.invoke_stream(_request())
        assert provider.stream_calls[0].stream is True

    def test_stream_retries_on_a_transient_failure(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [], stream_script=[
            TransientProviderError("throttled", hazard_class="THROTTLED"),
            self._chunks(),
        ])
        clock = FakeClock()
        router = _router([provider], clock=clock)
        result = router.invoke_stream(_request())
        assert result.refusal is None
        assert result.text == "hello"
        assert clock.slept == [2.0]

    def test_stream_refusal_is_data_not_an_exception(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(supports_streaming=False),),
                                    [], stream_script=[])
        router = _router([provider])
        result = router.invoke_stream(_request())
        assert result.chunks == ()
        assert result.refusal is not None
        assert result.refusal.code in REFUSAL_CODES


# ═══════════════════════ tool-call translation ═══════════════════════


def _tool_blob(*calls: dict[str, Any]) -> str:
    return json.dumps({"calls": list(calls)})


class TestToolCalls:
    def test_translation_is_neutral_and_never_executed(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response(json.dumps({"text": "ok"}),
                      tool_calls_raw=_tool_blob(
                          {"provider_call_ref": "p-1", "tool_name": "search",
                           "arguments": {"query": "iron"}}))])
        router = _router([provider])
        result = router.invoke(_request(output_contract=JSON_CONTRACT,
                                        tools=("search",)))
        assert isinstance(result, ModelProposal)
        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.tool_name == "search"
        assert call.arguments == {"query": "iron"}
        assert call.provider_call_ref == "p-1"
        # The plane translated and stopped: no execution surface exists.
        assert not hasattr(router, "execute_tool")
        assert not hasattr(result, "observations")

    def test_tool_call_raw_is_enveloped(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response(json.dumps({"text": "ok"}),
                      tool_calls_raw=_tool_blob(
                          {"tool_name": "search", "arguments": {}}))])
        router = _router([provider])
        result = router.invoke(_request(output_contract=JSON_CONTRACT,
                                        tools=("search",)))
        assert isinstance(result, ModelProposal)
        assert isinstance(result.tool_calls[0].raw, UntrustedContent)

    def test_undeclared_tool_refuses_role(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response(json.dumps({"text": "ok"}),
                      tool_calls_raw=_tool_blob(
                          {"tool_name": "rm_rf", "arguments": {}}))])
        router = _router([provider])
        result = router.invoke(_request(output_contract=JSON_CONTRACT,
                                        tools=("search",)))
        assert isinstance(result, ModelRefusal)
        assert result.code == ROLE
        assert "rm_rf" in result.detail

    def test_unknown_tool_call_key_refuses(self) -> None:
        # Scripted three times: the tool-call refusal is retryable, so the last
        # attempt's refusal is the one that surfaces.
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response(json.dumps({"text": "ok"}),
                      tool_calls_raw=_tool_blob(
                          {"tool_name": "search", "arguments": {},
                           "smuggled": 1})) for _ in range(3)])
        router = _router([provider])
        result = router.invoke(_request(output_contract=JSON_CONTRACT,
                                        tools=("search",)))
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD
        assert "smuggled" in result.detail

    def test_non_json_tool_calls_refuse(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response(json.dumps({"text": "ok"}), tool_calls_raw="not json")])
        router = _router([provider])
        result = router.invoke(_request(output_contract=JSON_CONTRACT,
                                        tools=("search",)))
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD

    def test_translator_refuses_an_unknown_top_level_key(self) -> None:
        translator = NeutralToolCallTranslator()
        result = translator.translate(_untrusted('{"calls": [], "extra": 1}'),
                                      allowed_tools=frozenset({"search"}))
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD

    def test_translator_refuses_a_non_object_arguments_value(self) -> None:
        translator = NeutralToolCallTranslator()
        result = translator.translate(
            _untrusted(_tool_blob({"tool_name": "search", "arguments": "x"})),
            allowed_tools=frozenset({"search"}))
        assert isinstance(result, ModelRefusal)
        assert "arguments must be an object" in result.detail

    def test_stream_tool_call_chunks_are_translated(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [], stream_script=[(
            ProviderChunk(kind=ChunkKind.TOOL_CALL,
                          tool_calls_raw=_tool_blob(
                              {"tool_name": "search", "arguments": {"q": "x"}})),
            ProviderChunk(kind=ChunkKind.END),
        )])
        router = _router([provider])
        result = router.invoke_stream(_request(tools=("search",)))
        assert result.refusal is None
        tool_chunks = [chunk for chunk in result.chunks
                       if chunk.kind is ChunkKind.TOOL_CALL]
        assert len(tool_chunks) == 1
        assert tool_chunks[0].tool_calls[0].tool_name == "search"


# ═══════════════════════ credentials ═══════════════════════


class TestCredentials:
    def test_credential_str_is_masked(self) -> None:
        credential = Credential(name="model_api_key", _value=SECRET)
        assert SECRET not in str(credential)
        assert SECRET not in repr(credential)
        assert credential.reveal() == SECRET

    def test_credential_class_option_name_is_refused_without_its_value(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider], credentials=FixedCredentials({"alpha": SECRET}))
        result = router.invoke(_request(
            options={"api_key": SECRET}))
        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD
        assert "api_key" in result.detail
        assert SECRET not in result.detail
        assert provider.calls_made == 0

    def test_secret_never_reaches_the_ledger(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider], credentials=FixedCredentials({"alpha": SECRET}))
        router.invoke(_request(options={"token": SECRET}))
        for row in router.accounting():
            assert SECRET not in repr(row)

    def test_live_secret_in_a_call_form_is_an_invariant_breach(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider], credentials=FixedCredentials({"alpha": SECRET}))
        with pytest.raises(ModelPlaneInvariantError) as excinfo:
            router.invoke(_request(prompt=(_untrusted(f"use {SECRET}"),)))
        assert SECRET not in str(excinfo.value)
        assert provider.calls_made == 0

    def test_live_secret_in_a_response_is_refused_at_record_time(self) -> None:
        inner = ScriptedProvider("alpha", (_profile(),), [_response(f"leak {SECRET}")])
        recorded = RecordedModelProvider(
            inner, provider_id="alpha", model_id="m1",
            transport_version="1", mode="record", secrets=(SECRET,))
        call = ModelCall(provider_id="alpha", model_id="m1",
                         payload={"prompt": []})
        with pytest.raises(ModelPlaneInvariantError) as excinfo:
            recorded.invoke(call)
        assert SECRET not in str(excinfo.value)

    def test_recorded_call_form_carries_no_credential(self) -> None:
        call = ModelCall(provider_id="alpha", model_id="m1",
                         payload={"prompt": [{"text": "hi"}], "tools": []},
                         options={"temperature": "0.2"})
        normalized = normalized_model_call(call)
        assert "credential" not in json.dumps(normalized).lower()
        assert normalized["options"] == {"temperature": "0.2"}

    def test_benign_option_names_are_not_masked(self) -> None:
        # The plane's own call form is not a wire form, so redaction uses the
        # credential-only policy: `temperature` must survive verbatim.
        call = ModelCall(provider_id="alpha", model_id="m1", payload={},
                         options={"temperature": "0.2"})
        assert normalized_model_call(call)["options"]["temperature"] == "0.2"
        assert CREDENTIAL_ONLY_POLICY.default_deny is False

    def test_option_name_containing_an_alias_is_allowed_but_recorded_masked(self) -> None:
        """The two halves of the credential story, side by side.

        The refusal guard matches aliases *exactly* (so the legitimate option
        name `max_tokens` is usable), while the recorded form still runs the
        inherited substring redaction (so it stays fail-closed). Identity is
        unaffected: the masking is deterministic.
        """
        profile = _profile(settings=ModelSettings(options={"max_tokens": "64"}))
        provider = ScriptedProvider("alpha", (profile,), [_ok_json()])
        router = _router([provider])
        result = router.invoke(_request(options={"max_tokens": "512"}))
        assert isinstance(result, ModelProposal)
        assert provider.calls[0].options["max_tokens"] == "512"
        recorded = router.accounting()[-1].normalized_request
        assert recorded["options"]["max_tokens"] == "<redacted>"

    def test_credential_only_policy_leaves_credential_names_classified(self) -> None:
        assert "api_key" in CREDENTIAL_ONLY_POLICY.credential_aliases
        assert CREDENTIAL_ONLY_POLICY.polite_identifiers == frozenset()


# ═══════════════════════ accounting ═══════════════════════


class TestAccounting:
    def test_one_row_per_provider_call(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            TransientProviderError("a", hazard_class="TIMEOUT"),
            _ok_json(),
        ])
        router = _router([provider])
        assert isinstance(router.invoke(_request()), ModelProposal)
        rows = [row for row in router.accounting() if row.attempt > 0]
        assert len(rows) == 2
        assert provider.calls_made == 2
        assert router.provider_attempts == provider.calls_made
        assert [row.attempt for row in rows] == [1, 2]
        assert [row.outcome for row in rows] == ["TRANSIENT", "OK"]
        assert rows[0].failure_class == "TransientProviderError"
        assert rows[0].refusal_code is None

    def test_sequence_is_contiguous(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            TransientProviderError("a", hazard_class="TIMEOUT"),
            _ok_json(),
        ])
        router = _router([provider])
        router.invoke(_request())
        router.invoke(_request())
        assert [row.sequence for row in router.accounting()] == [0, 1, 2]
        router.verify_accounting()

    def test_verify_accounting_raises_on_an_untracked_call(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider])
        original = router._record

        def _losing_record(**kwargs: Any) -> Any:
            row = original(**kwargs)
            router._ledger.pop()  # the call happened; its row is lost
            return row

        router._record = _losing_record  # type: ignore[method-assign]
        try:
            assert isinstance(router.invoke(_request()), ModelProposal)
            with pytest.raises(ModelPlaneInvariantError) as excinfo:
                router.verify_accounting()
            assert "without an accounting record" in str(excinfo.value)
        finally:
            router._record = original  # type: ignore[method-assign]

    def test_verify_accounting_is_clean_after_a_normal_run(self) -> None:
        alpha = ScriptedProvider("alpha", (_profile(),), [
            PermanentProviderError("a", hazard_class="MALFORMED_200")])
        beta = ScriptedProvider("beta", (_profile("m2", provider_id="beta"),),
                                [_ok_json()])
        router = _router([alpha, beta])
        router.invoke(_request(output_contract=JSON_CONTRACT))
        router.verify_accounting()
        assert router.provider_attempts == 2

    def test_rows_carry_lease_generation_and_profile(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider])
        router.invoke(_request(lease_generation="gen-42"))
        row = router.accounting()[0]
        assert row.lease_generation == "gen-42"
        assert row.profile == "director"
        assert row.tier == "s"
        assert row.retrieved_at == CLOCK_STAMP

    def test_rows_carry_a_deterministic_request_digest(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json(),
                                                             _ok_json()])
        router = _router([provider])
        router.invoke(_request())
        router.invoke(_request())
        digests = {row.request_digest for row in router.accounting()}
        assert len(digests) == 1
        assert len(next(iter(digests))) == 64

    def test_usage_and_price_accumulate(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response("{}", input_tokens=1000, output_tokens=1000),
            _response("{}", input_tokens=1000, output_tokens=0),
        ])
        router = _router([provider])
        router.invoke(_request())
        router.invoke(_request())
        assert router.total_usage() == TokenUsage(2000, 1000)
        # 2000/1000 * 0.5 + 1000/1000 * 1.5 = 2.5
        assert router.total_price_usd() == pytest.approx(2.5)

    def test_unpriced_model_reports_none_not_zero(self) -> None:
        profile = _profile(input_cost_per_1k_tokens=0.0,
                           output_cost_per_1k_tokens=0.0)
        provider = ScriptedProvider("alpha", (profile,), [_ok_json()])
        router = _router([provider])
        router.invoke(_request())
        assert router.accounting()[0].price_usd is None
        assert router.total_price_usd() == 0.0

    def test_context_tokens_recorded_from_provider_usage(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response("{}", input_tokens=123, output_tokens=4)])
        router = _router([provider])
        router.invoke(_request())
        assert router.accounting()[0].context_tokens == 123

    def test_fallback_attempts_are_all_accounted(self) -> None:
        alpha = ScriptedProvider("alpha", (_profile(),), [
            TransientProviderError("a", hazard_class="TIMEOUT"),
            TransientProviderError("b", hazard_class="TIMEOUT"),
            TransientProviderError("c", hazard_class="TIMEOUT"),
        ])
        beta = ScriptedProvider("beta", (_profile("m2", provider_id="beta"),),
                                [_ok_json()])
        router = _router([alpha, beta])
        assert isinstance(router.invoke(_request()), ModelProposal)
        assert router.provider_attempts == 4
        accounted = [row for row in router.accounting() if row.attempt > 0]
        assert len(accounted) == 4
        assert [row.provider_id for row in accounted] == [
            "alpha", "alpha", "alpha", "beta"]
        assert [row.attempt for row in accounted] == [1, 2, 3, 1]
        router.verify_accounting()

    def test_refusal_after_attempts_is_accounted(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            _response("junk") for _ in range(3)])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        result = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(result, ModelRefusal)
        assert result.account is not None
        assert result.account.attempt == 3
        assert result.account.refusal_code is None
        router.verify_accounting()

    def test_permanent_failure_lands_one_permanent_row(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            PermanentProviderError("x", hazard_class="MALFORMED_200")])
        router = _router([provider],
                         policy=_policy(tier_refs={"s": "alpha:m1"},
                                        fallback_chain=()))
        with pytest.raises(ProviderUnavailableError):
            router.invoke(_request())
        rows = router.accounting()
        assert len(rows) == 1
        assert rows[0].attempt == 1
        assert rows[0].outcome == "PERMANENT"
        assert rows[0].failure_class == "PermanentProviderError"
        router.verify_accounting()

    def test_refusal_as_data_shape(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider])
        result = router.invoke(_request(lease_generation=""))
        assert isinstance(result, ModelRefusal)
        assert result.as_dict() == {"rejected": True, "code": LOCK,
                                    "detail": result.detail}

    def test_normalized_request_is_recorded_and_deterministic(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json(),
                                                             _ok_json()])
        router = _router([provider])
        router.invoke(_request())
        router.invoke(_request())
        first, second = (row.normalized_request for row in router.accounting())
        assert first == second
        assert first["model_id"] == "m1"
        assert first["payload"]["prompt"][0]["text"] == (
            "Summarise the admitted evidence.")
        assert first["stream"] is False


# ═══════════════════════ replay ═══════════════════════


def _recording() -> tuple[ModelFixture, ModelCall]:
    inner = ScriptedProvider("alpha", (_profile(),), [_response("recorded body")])
    sink: list[ModelFixture] = []
    recorded = RecordedModelProvider(
        inner, provider_id="alpha", model_id="m1", transport_version="1",
        mode="record", sink=sink.append)
    call = ModelCall(provider_id="alpha", model_id="m1",
                     payload={"prompt": [{"text": "hi"}]})
    response = recorded.invoke(call)
    assert response.text == "recorded body"
    assert len(sink) == 1
    return sink[0], call


class TestReplay:
    def test_record_mode_publishes_a_fixture_to_the_sink(self) -> None:
        fixture, call = _recording()
        assert fixture.provider_id == "alpha"
        assert fixture.model_id == "m1"
        assert fixture.response_text() == "recorded body"
        assert fixture.fixture_id == model_fixture_id_of(
            "alpha", "m1", normalized_model_call(call))

    def test_replay_serves_recorded_bytes_without_contact(self) -> None:
        fixture, call = _recording()
        inner = RefusingProvider("alpha", (_profile(),))
        replay = RecordedModelProvider(
            inner, provider_id="alpha", model_id="m1", transport_version="1",
            mode="replay", fixtures={fixture.fixture_id: fixture})
        response = replay.invoke(call)
        assert response.text == "recorded body"
        assert inner.contacted == 0

    def test_replay_is_byte_identical(self) -> None:
        fixture, call = _recording()
        replay = RecordedModelProvider(
            RefusingProvider("alpha"), provider_id="alpha", model_id="m1",
            transport_version="1", mode="replay",
            fixtures={fixture.fixture_id: fixture})
        assert replay.invoke(call).text.encode("utf-8") == b"recorded body"

    def test_replay_stream_chunks_are_byte_identical(self) -> None:
        chunks = (ProviderChunk(kind=ChunkKind.DELTA, text="a"),
                  ProviderChunk(kind=ChunkKind.DELTA, text="b"),
                  ProviderChunk(kind=ChunkKind.END))
        inner = ScriptedProvider("alpha", (_profile(),), [], stream_script=[chunks])
        sink: list[ModelFixture] = []
        recorded = RecordedModelProvider(
            inner, provider_id="alpha", model_id="m1", transport_version="1",
            mode="record", sink=sink.append)
        call = ModelCall(provider_id="alpha", model_id="m1", payload={},
                         stream=True)
        assert recorded.stream(call) == chunks
        fixture = sink[0]
        replay = RecordedModelProvider(
            RefusingProvider("alpha"), provider_id="alpha", model_id="m1",
            transport_version="1", mode="replay",
            fixtures={fixture.fixture_id: fixture})
        assert replay.stream(call) == chunks

    def test_replay_mode_never_touches_the_inner_provider(self) -> None:
        fixture, call = _recording()
        inner = RefusingProvider("alpha")
        replay = RecordedModelProvider(
            inner, provider_id="alpha", model_id="m1", transport_version="1",
            mode="replay", fixtures={fixture.fixture_id: fixture})
        replay.invoke(call)
        replay.stream(call)
        replay.replay_bytes(call)
        assert inner.contacted == 0

    def test_replay_missing_fixture_raises_replay_unavailable(self) -> None:
        from hermes.tools.providers.replay import ReplayUnavailableError

        replay = RecordedModelProvider(
            RefusingProvider("alpha"), provider_id="alpha", model_id="m1",
            transport_version="1", mode="replay", fixtures={})
        with pytest.raises(ReplayUnavailableError):
            replay.invoke(ModelCall(provider_id="alpha", model_id="m1",
                                    payload={}))

    def test_replay_transport_version_mismatch_raises(self) -> None:
        from hermes.tools.providers.replay import ReplayUnavailableError

        fixture, call = _recording()
        replay = RecordedModelProvider(
            RefusingProvider("alpha"), provider_id="alpha", model_id="m1",
            transport_version="2", mode="replay",
            fixtures={fixture.fixture_id: fixture})
        with pytest.raises(ReplayUnavailableError) as excinfo:
            replay.invoke(call)
        assert "transport" in str(excinfo.value)

    def test_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(ProviderValidationError):
            RecordedModelProvider(RefusingProvider("alpha"),
                                  provider_id="alpha", model_id="m1",
                                  transport_version="1", mode="live")

    def test_fixture_id_is_recomputed_and_authored_ids_are_refused(self) -> None:
        from hermes.tools.providers.replay import ReplayUnavailableError

        fixture, _ = _recording()
        tampered = fixture.to_mapping()
        tampered["fixture_id"] = "fx_" + "0" * 24
        with pytest.raises(ReplayUnavailableError) as excinfo:
            ModelFixture.from_mapping(tampered)
        assert "recomputed identity" in str(excinfo.value)

    def test_fixture_body_hash_mismatch_is_refused(self) -> None:
        from hermes.tools.providers.replay import ReplayUnavailableError

        fixture, _ = _recording()
        tampered = fixture.to_mapping()
        tampered["text_hex"] = b"different".hex()
        with pytest.raises(ReplayUnavailableError):
            ModelFixture.from_mapping(tampered)

    def test_fixture_chunk_disagreement_is_refused(self) -> None:
        from hermes.tools.providers.replay import ReplayUnavailableError

        fixture, _ = _recording()
        tampered = fixture.to_mapping()
        tampered["chunk_kinds"] = ["DELTA"]
        tampered["chunk_texts_hex"] = []
        with pytest.raises(ReplayUnavailableError):
            ModelFixture.from_mapping(tampered)

    def test_corrupt_fixture_file_is_refused(self, tmp_path: Path) -> None:
        from hermes.tools.providers.replay import ReplayUnavailableError

        path = tmp_path / "corpus.json"
        path.write_text(json.dumps({"nope": []}), encoding="utf-8")
        with pytest.raises(ReplayUnavailableError):
            load_model_fixtures(str(path))

    def test_fixture_corpus_roundtrip(self, tmp_path: Path) -> None:
        fixture, _ = _recording()
        path = str(tmp_path / "corpus.json")
        dump_model_fixtures([fixture], path)
        loaded = load_model_fixtures(path)
        assert set(loaded) == {fixture.fixture_id}
        assert loaded[fixture.fixture_id].response_text() == "recorded body"

    def test_fixture_identity_changes_with_the_request(self) -> None:
        first = model_fixture_id_of("alpha", "m1", {"a": 1})
        second = model_fixture_id_of("alpha", "m1", {"a": 2})
        assert first != second
        assert first.startswith("fx_")
        assert len(first) == 3 + 24

    def test_fixture_identity_requires_provider_and_model(self) -> None:
        with pytest.raises(ProviderValidationError):
            model_fixture_id_of("", "m1", {})


class TestRouterReplay:
    def _replay_router(self, fixtures: dict[str, ModelFixture]) -> Any:
        inner = RefusingProvider("alpha", (_profile(),))
        recording = RecordedModelProvider(
            inner, provider_id="alpha", model_id="m1", transport_version="1",
            mode="replay", fixtures=fixtures)
        return _router([recording])

    def test_router_records_then_replays_identically(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json("answer")])
        sink: list[ModelFixture] = []
        recording = RecordedModelProvider(
            provider, provider_id="alpha", model_id="m1",
            transport_version="1", mode="record", sink=sink.append)
        router = _router([recording])
        first = router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(first, ModelProposal)
        fixtures = {fixture.fixture_id: fixture for fixture in sink}
        units_before = router.provider_attempts

        replay_router = self._replay_router(fixtures)
        second = replay_router.invoke(_request(output_contract=JSON_CONTRACT))
        assert isinstance(second, ModelProposal)
        assert second.structured == first.structured
        assert provider.calls_made == 1
        assert units_before == 1

    def test_replay_bytes_returns_recorded_bytes_without_a_ledger_row(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),),
                                    [_response("recorded body")])
        sink: list[ModelFixture] = []
        recording = RecordedModelProvider(
            provider, provider_id="alpha", model_id="m1",
            transport_version="1", mode="record", sink=sink.append)
        router = _router([recording])
        assert isinstance(router.invoke(_request()), ModelProposal)
        fixtures = {fixture.fixture_id: fixture for fixture in sink}

        replay_router = self._replay_router(fixtures)
        assert replay_router.replay_bytes(_request()) == b"recorded body"
        # A replay read contacts nothing, so there is no call to account — the
        # ledger stays empty and the refusal-free run proves no live contact.
        assert replay_router.provider_attempts == 0
        assert replay_router.accounting() == ()
        replay_router.verify_accounting()

    def test_replay_bytes_refuses_a_record_mode_provider(self) -> None:
        from hermes.tools.providers.replay import ReplayUnavailableError

        inner = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        recording = RecordedModelProvider(
            inner, provider_id="alpha", model_id="m1", transport_version="1",
            mode="record")
        router = _router([recording])
        with pytest.raises(ReplayUnavailableError):
            router.replay_bytes(_request())

    def test_replay_bytes_refuses_a_non_recording_provider(self) -> None:
        from hermes.tools.providers.replay import ReplayUnavailableError

        router = _router([ScriptedProvider("alpha", (_profile(),), [_ok_json()])])
        with pytest.raises(ReplayUnavailableError):
            router.replay_bytes(_request())


# ═══════════════════════ authority discipline ═══════════════════════


class TestAuthorityDiscipline:
    def test_plane_exposes_no_write_or_control_surface(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider])
        for banned in ("apply_intent", "commit", "begin", "write", "execute",
                       "transition", "record_intent", "save"):
            assert not hasattr(router, banned), banned

    def test_refusal_codes_emitted_are_always_in_the_frozen_set(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [
            TransientProviderError("a", hazard_class="TIMEOUT"),
            _ok_json(),
        ])
        router = _router([provider])
        router.invoke(_request(lease_generation=""))
        router.invoke(_request(options={"secret": "x"}))
        router.invoke(_request())
        for row in router.accounting():
            if row.refusal_code is not None:
                assert row.refusal_code in REFUSAL_CODES

    def test_proposal_requires_a_lease_generation(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_ok_json()])
        router = _router([provider])
        result = router.invoke(_request(lease_generation="gen-9"))
        assert isinstance(result, ModelProposal)
        assert result.lease_generation == "gen-9"

    def test_empty_proposal_kinds_allowlist_refuses_every_kind(self) -> None:
        provider = ScriptedProvider("alpha", (_profile(),), [_director()])
        router = _router([provider], proposable=frozenset())
        result = router.invoke(_request(output_contract=DIRECTOR_CONTRACT))
        assert isinstance(result, ModelRefusal)
        assert result.code == ROLE


# ═══════════════════════ module introspection helpers ═══════════════════════


def _module_path() -> Path:
    import hermes.tools.models.router as module

    assert module.__file__ is not None
    return Path(module.__file__)


def _module_source() -> str:
    return _module_path().read_text(encoding="utf-8")


def _module_imports() -> set[str]:
    tree = ast.parse(_module_source())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def _field_names(cls: type) -> set[str]:
    from dataclasses import fields

    return {spec.name for spec in fields(cls)}
