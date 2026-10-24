"""Composition root — wire a hosted LLM (an API key) into a live controller.

Everything under `hermes.tools.models` and `hermes.agents.runtime` is a seam:
ports, protocols and plane logic that name no vendor and own no secrets. The
CLI's ``hermes run`` injects no model and no handler, so out of the box it
leaves extract, gate and methodology tasks unhandled. This module is the one
place that closes that gap: it reads an API key from the environment, builds a
`CloudChatProvider`, binds the model port from ``[model_tiers]``, loads the
agent profiles, registers the methodology handler and returns a `Controller`.

What it does *not* do — by design:

- It does not widen authority. The model still emits one structured proposal
  per run; every proposal still passes the gateway; verdicts still need an
  operator credential. Nothing here auto-approves.
- It does not read a key from argv, a config file or a database. The key is read
  from one named environment variable per provider, wrapped in an opaque
  `Credential`, and handed to the provider that injects it as a header.
- It does not add tools. Experiments that run code need the sandbox and an
  experiment registry, which do not exist yet.

Usage::

    spec = CloudModelSpec(provider_id="anthropic", dialect="anthropic",
                          model_id="<model id>", api_key_env="ANTHROPIC_API_KEY")
    controller = build_live_controller(cfg, conn, project_id="p1",
                                       specs=[spec])
    controller.run(max_ticks=10)

with ``[model_tiers] m = "anthropic:<model id>"`` in the Hermes config.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.supervisor import Supervisor
from hermes.config import HermesConfig, ModelTierConfig
from hermes.core.intents import IntentKind
from hermes.eval.live_vector import LiveVector
from hermes.eval.loop_observations import RecordingModelPort
from hermes.research.controller import Controller
from hermes.research.task_handlers import build_methodology_handler
from hermes.tools.models.binding import (
    ModelBinding,
    ModelPolicyTable,
    bind_model_port,
)
from hermes.tools.models.cloud import (
    AnthropicMessagesDialect,
    ChatDialect,
    CloudChatProvider,
    OpenAIChatDialect,
    Resolver,
)
from hermes.tools.models.router import (
    Credential,
    CredentialResolver,
    ModelPlanePolicy,
    ModelProfile,
    ModelProvider,
    parse_model_ref,
)
from hermes.tools.providers.base import Transport
from hermes.tools.providers.http import ProviderHTTPTransport

__all__ = [
    "CloudModelSpec",
    "CompositionError",
    "EnvCredentialResolver",
    "LiveComposition",
    "SystemClock",
    "build_cloud_provider",
    "build_controller",
    "build_live_composition",
    "build_live_controller",
    "build_model_binding",
    "check_composition",
    "specs_from_tiers",
    "tier_refs_from_config",
]

#: How long one model call may take at the HTTP edge.
DEFAULT_MODEL_HTTP_TIMEOUT_SECONDS = 120.0

_DIALECTS = ("anthropic", "openai")

#: The code-owned host allowlist — one canonical host per dialect. A
#: ``CloudModelSpec.host`` override may only name a host already declared
#: here, so a key-bearing transport is never redirected to an undeclared
#: host. The default is therefore exactly the two dialect hosts.
#: (HOST-ALLOWLIST: the override exists for a compatible gateway, but a
#: runtime-supplied host is precisely the hole — the credential rides the
#: header to whatever host the config names. Adding a gateway endpoint is a
#: code-owned change — one entry here plus its dialect — never a free-form
#: config value; "no new endpoints" keeps this list at the two canonical
#: hosts for now.)
_DIALECT_HOSTS: Final[Mapping[str, frozenset[str]]] = {
    "anthropic": frozenset({"api.anthropic.com"}),
    "openai": frozenset({"api.openai.com"}),
}

#: The code-owned hosted-model registry (OPS-1 Decision A2): the policy surface
#: that decides which providers may receive a credential from the environment.
#: A ``[model_tiers]`` ref resolves through this table, so an unknown provider
#: refuses by name instead of being defaulted. Adding an entry — a provider or a
#: compatible gateway host — is a reviewed code change, never a config value,
#: the same posture as ``_DIALECT_HOSTS`` above.
_MODEL_REGISTRY: Final[Mapping[str, tuple[str, str]]] = {
    "anthropic": ("anthropic", "ANTHROPIC_API_KEY"),
    "openai": ("openai", "OPENAI_API_KEY"),
}


class CompositionError(Exception):
    """The composition cannot run as configured. Names every problem at once."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


# ── small injected collaborators ──


class SystemClock:
    """The wall clock behind the `Clock` protocol (ISO-8601 UTC + monotonic)."""

    def now_utc(self) -> str:
        return datetime.now(UTC).isoformat()

    def monotonic(self) -> float:
        return time.monotonic()


class EnvCredentialResolver:
    """Resolves a provider's key from one named environment variable.

    The value exists only inside an opaque `Credential`; every string form of it
    is masked. `resolve` reads the environment at call time, so a rotated key is
    picked up without a restart.
    """

    def __init__(self, env_vars: Mapping[str, str],
                 *, environ: Mapping[str, str] | None = None) -> None:
        self._env_vars = dict(env_vars)
        self._environ = environ if environ is not None else os.environ

    def resolve(self, provider_id: str) -> Credential | None:
        var = self._env_vars.get(provider_id, "")
        if not var:
            return None
        value = self._environ.get(var, "").strip()
        return Credential(name=var, _value=value) if value else None

    def configured(self, provider_id: str) -> bool:
        return self.resolve(provider_id) is not None


# ── what to connect ──


@dataclass(frozen=True, slots=True)
class CloudModelSpec:
    """One hosted model: which API, which model, which env var holds the key.

    ``host`` may override the dialect's default host for a compatible gateway,
    but only to a host in the code-owned allowlist (`_DIALECT_HOSTS`) — an
    override can name the dialect's own canonical host, never an arbitrary one,
    because this transport carries the credential. The cost and window figures
    are declared metadata (advertisement, not proof): set them from the
    vendor's published numbers.
    """

    provider_id: str
    dialect: str
    model_id: str
    api_key_env: str
    host: str = ""
    context_window_tokens: int = 200_000
    max_output_tokens: int = 4_096
    input_cost_per_1k_tokens: float = 0.0
    output_cost_per_1k_tokens: float = 0.0

    def __post_init__(self) -> None:
        if self.dialect not in _DIALECTS:
            raise ValueError(
                f"unknown dialect {self.dialect!r} (expected one of {_DIALECTS})")
        if not (self.provider_id and self.model_id and self.api_key_env):
            raise ValueError(
                "CloudModelSpec needs provider_id, model_id and api_key_env")
        canonical = self.host.strip().lower()
        if canonical and canonical not in _DIALECT_HOSTS[self.dialect]:
            raise ValueError(
                f"CloudModelSpec.host {self.host!r} is outside the "
                f"{self.dialect!r} host allowlist "
                f"{sorted(_DIALECT_HOSTS[self.dialect])} — a key-bearing "
                f"transport is never redirected to an undeclared host")
        object.__setattr__(self, "host", canonical)

    def to_profile(self) -> ModelProfile:
        return ModelProfile(
            provider_id=self.provider_id,
            model_id=self.model_id,
            context_window_tokens=self.context_window_tokens,
            max_output_tokens=self.max_output_tokens,
            supports_streaming=False,
            supports_tool_calls=False,
            supports_structured_output=True,
            input_cost_per_1k_tokens=self.input_cost_per_1k_tokens,
            output_cost_per_1k_tokens=self.output_cost_per_1k_tokens)

    def make_dialect(self) -> ChatDialect:
        if self.dialect == "anthropic":
            return (AnthropicMessagesDialect(host=self.host) if self.host
                    else AnthropicMessagesDialect())
        return (OpenAIChatDialect(host=self.host) if self.host
                else OpenAIChatDialect())


def tier_refs_from_config(cfg: HermesConfig) -> dict[str, str]:
    """The configured ``[model_tiers]`` as ``{tier: "provider:model"}``."""
    tiers = cfg.model_tiers
    raw = {"s": tiers.s, "m": tiers.m, "c": tiers.c}
    return {tier: ref.strip() for tier, ref in raw.items() if ref.strip()}


def specs_from_tiers(
    cfg: HermesConfig, *, environ: Mapping[str, str] | None = None,
) -> tuple[CloudModelSpec, ...]:
    """Resolve the configured tier refs through the code-owned registry.

    Every problem is collected before anything raises: a malformed ref, an
    unknown provider, an unusable registry entry, and then the key check that
    ``check_composition`` owns. An empty ``[model_tiers]`` is *not* an error
    here — the caller chooses the drain-only path by the same signal — so this
    resolver is total and the builder's own ``check_composition`` remains the
    place that refuses a live composition with no tier.
    """
    refs = tier_refs_from_config(cfg)
    problems: list[str] = []
    specs: dict[tuple[str, str], CloudModelSpec] = {}
    resolved: set[str] = set()
    for tier, ref in sorted(refs.items()):
        try:
            provider_id, model_id = parse_model_ref(ref)
        except Exception as exc:  # noqa: BLE001 — re-reported as a problem
            problems.append(f"tier {tier!r}: {exc}")
            continue
        entry = _MODEL_REGISTRY.get(provider_id)
        if entry is None:
            problems.append(
                f"tier {tier!r}: provider {provider_id!r} is not in the model "
                f"registry (known: {', '.join(sorted(_MODEL_REGISTRY))})")
            continue
        dialect, api_key_env = entry
        key = (provider_id, model_id)
        if key not in specs:
            try:
                specs[key] = CloudModelSpec(
                    provider_id=provider_id, dialect=dialect,
                    model_id=model_id, api_key_env=api_key_env)
            except ValueError as exc:
                problems.append(
                    f"provider {provider_id!r} declares an unusable "
                    f"spec: {exc}")
                continue
        resolved.add(tier)
    if specs:
        # Check keys against the refs that resolved: passing the original cfg
        # would re-report a failed tier as "matches no CloudModelSpec", which
        # is the same condition under a worse name.
        kept = {tier: ref for tier, ref in refs.items() if tier in resolved}
        filtered = replace(cfg, model_tiers=ModelTierConfig(
            s=kept.get("s", ""), m=kept.get("m", ""), c=kept.get("c", "")))
        try:
            check_composition(filtered, list(specs.values()), environ=environ)
        except CompositionError as exc:
            problems.extend(exc.problems)
    if problems:
        raise CompositionError(problems)
    return tuple(specs.values())


# ── validation ──


def check_composition(
    cfg: HermesConfig,
    specs: Sequence[CloudModelSpec],
    *,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Fail fast, naming every problem: a missing key, a tier with no model."""
    env = environ if environ is not None else os.environ
    problems: list[str] = []
    declared = {(s.provider_id, s.model_id) for s in specs}
    refs = tier_refs_from_config(cfg)
    if not refs:
        problems.append("[model_tiers] declares no tier; set at least one "
                        "'provider:model' ref (an unconfigured tier refuses)")
    for tier, ref in sorted(refs.items()):
        try:
            pair = parse_model_ref(ref)
        except Exception as exc:  # noqa: BLE001 - re-reported as a problem
            problems.append(f"tier {tier!r}: {exc}")
            continue
        if pair not in declared:
            problems.append(f"tier {tier!r} -> {ref!r} matches no CloudModelSpec")
    seen: set[str] = set()
    for spec in specs:
        if spec.api_key_env in seen:
            continue
        seen.add(spec.api_key_env)
        if not env.get(spec.api_key_env, "").strip():
            problems.append(f"environment variable {spec.api_key_env} is not set")
    if problems:
        raise CompositionError(problems)


# ── builders ──


def build_cloud_provider(
    specs: Sequence[CloudModelSpec],
    *,
    credentials: CredentialResolver,
    transport: Transport | None = None,
    resolve: Resolver | None = None,
) -> CloudChatProvider:
    """One provider for the specs that share a ``provider_id`` and dialect."""
    if not specs:
        raise ValueError("build_cloud_provider needs at least one spec")
    provider_id = specs[0].provider_id
    first = specs[0]
    for spec in specs:
        if spec.provider_id != provider_id or spec.dialect != first.dialect \
                or spec.host != first.host:
            raise ValueError(
                "specs sharing a provider must share provider_id, dialect and "
                "host — build one provider per vendor endpoint")
    http: Transport = transport if transport is not None else \
        ProviderHTTPTransport(timeout=DEFAULT_MODEL_HTTP_TIMEOUT_SECONDS)
    return CloudChatProvider(
        provider_id=provider_id,
        dialect=first.make_dialect(),
        transport=http,
        credentials=credentials,
        profiles=[spec.to_profile() for spec in specs],
        resolve=resolve)


def build_model_binding(
    cfg: HermesConfig,
    providers: Sequence[ModelProvider],
    *,
    credentials: CredentialResolver,
    clock: Any = None,
    task_tiers: Mapping[str, str] | None = None,
    default_tier: str = "m",
    tool_allowlist: frozenset[str] = frozenset(),
) -> ModelBinding:
    """Bind the router to the configured tiers; the binding is the model port.

    ``task_tiers`` maps a profile name (planner, researcher, ...) to a tier;
    ``default_tier`` covers the rest. A task never chooses its own model.
    """
    policy = ModelPlanePolicy.from_config_tiers(
        {"s": cfg.model_tiers.s, "m": cfg.model_tiers.m, "c": cfg.model_tiers.c})
    proposable = frozenset(
        kind.value for kind in IntentKind.llm_proposable() | IntentKind.director_only())
    return bind_model_port(
        providers=providers,
        policy=policy,
        clock=clock if clock is not None else SystemClock(),
        task_policy=ModelPolicyTable(tiers=dict(task_tiers or {}),
                                     default_tier=default_tier),
        credentials=credentials,
        proposable_kinds=proposable,
        tool_allowlist=tool_allowlist)


def build_controller(
    conn: Any,
    *,
    project_id: str,
    binding: ModelBinding,
    profiles_dir: Path | str | None = None,
    profiles: Mapping[str, Any] | None = None,
    model: Any = None,
    supervisor: Supervisor | None = None,
    on_stage: Any = None,
    **controller_kwargs: Any,
) -> Controller:
    """A `Controller` with the methodology handler bound to ``binding``.

    The handler runs each workflow stage as an agent run under the controller's
    lease; every proposal it makes is applied through ``apply_intent``.

    ``profiles`` lets a caller that already loaded the profile map (the live
    composition does, for the vector sink) hand it over instead of loading it
    twice. ``model`` overrides the port the handler sees — the live composition
    passes a ``RecordingModelPort`` wrapping ``binding`` so M1 is measured at
    the call edge. ``supervisor`` and ``on_stage`` are the two surfaces the
    vector sink needs and are inert when omitted.
    """
    loaded = profiles if profiles is not None else load_profiles(
        directory=profiles_dir)
    handler = build_methodology_handler(
        model=model if model is not None else binding,
        profiles=loaded,
        supervisor=supervisor,
        on_stage=on_stage,
    )
    return Controller(
        conn,
        project_id=project_id,
        task_handlers={handler.template: handler},  # type: ignore[dict-item]
        **controller_kwargs)


@dataclass(frozen=True, slots=True)
class LiveComposition:
    """A composed live controller plus the surfaces its run reports.

    ``binding`` is the model port the run actually used (its ``model_ledger``
    is the per-attempt record the CLI prints); ``vector`` renders the in-process
    LOOP vector collected at run end (R3).
    """

    controller: Controller
    binding: ModelBinding
    vector: LiveVector


def _model_only_profiles(
    profiles: Mapping[str, Any],
) -> dict[str, Any]:
    """Narrow every profile to model-only drafting for this seam.

    The cloud provider refuses a reply that carries a tool call, and this
    composition wires no capability port, so asking the model for one could only
    fail later. Narrowing the copy — never the profile file — means the request
    declares no tools, the router serves it, and no tool can execute. A caller
    that wires capabilities must compose its own profiles.
    """
    return {
        name: spec if not spec.model_policy.allows_tool_calls else replace(
            spec,
            model_policy=replace(spec.model_policy, allows_tool_calls=False),
        )
        for name, spec in profiles.items()
    }


def build_live_composition(
    cfg: HermesConfig,
    conn: Any,
    *,
    project_id: str,
    specs: Sequence[CloudModelSpec],
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    resolve: Resolver | None = None,
    task_tiers: Mapping[str, str] | None = None,
    default_tier: str = "m",
    profiles_dir: Path | str | None = None,
    **controller_kwargs: Any,
) -> LiveComposition:
    """Key in the environment -> a controller, its binding, and its vector sink."""
    check_composition(cfg, specs, environ=environ)
    credentials = EnvCredentialResolver(
        {spec.provider_id: spec.api_key_env for spec in specs},
        environ=environ)
    by_provider: dict[str, list[CloudModelSpec]] = {}
    for spec in specs:
        by_provider.setdefault(spec.provider_id, []).append(spec)
    providers: list[ModelProvider] = [
        build_cloud_provider(group, credentials=credentials,
                             transport=transport, resolve=resolve)
        for group in by_provider.values()]
    profiles = _model_only_profiles(load_profiles(directory=profiles_dir))
    binding = build_model_binding(
        cfg, providers, credentials=credentials,
        task_tiers=task_tiers, default_tier=default_tier)
    supervisor = Supervisor()
    recorder = RecordingModelPort(binding)
    vector = LiveVector(supervisor=supervisor, profiles=profiles,
                        recorder=recorder)
    controller = build_controller(
        conn, project_id=project_id, binding=binding, profiles=profiles,
        model=recorder, supervisor=supervisor, on_stage=vector.record,
        **controller_kwargs)
    return LiveComposition(controller=controller, binding=binding, vector=vector)


def build_live_controller(
    cfg: HermesConfig,
    conn: Any,
    *,
    project_id: str,
    specs: Sequence[CloudModelSpec],
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    resolve: Resolver | None = None,
    task_tiers: Mapping[str, str] | None = None,
    default_tier: str = "m",
    profiles_dir: Path | str | None = None,
    **controller_kwargs: Any,
) -> Controller:
    """Key in the environment -> a controller that can call a hosted model."""
    return build_live_composition(
        cfg, conn, project_id=project_id, specs=specs, environ=environ,
        transport=transport, resolve=resolve, task_tiers=task_tiers,
        default_tier=default_tier, profiles_dir=profiles_dir,
        **controller_kwargs).controller
