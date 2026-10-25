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

import hashlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from hermes.agents.runtime.config import ProfileSpec, load_profiles
from hermes.agents.runtime.run import TOOL_CALL_KEYS
from hermes.agents.runtime.supervisor import Supervisor
from hermes.artifacts.store import ArtifactStore
from hermes.config import HermesConfig, ModelTierConfig
from hermes.core import utc_now
from hermes.core.events import EventType
from hermes.core.intents import IntentKind
from hermes.eval.live_vector import LiveVector
from hermes.eval.loop_observations import (
    RecordingCapabilityPort,
    RecordingModelPort,
)
from hermes.persistence.repositories import ArtifactRepository, EventRepository
from hermes.research.capability_supply import (
    EVIDENCE_HANDLE_PREFIX,
    HANDLE_SEPARATOR,
    RESEARCH_EGRESS_TOOL_SET_ID,
    SOURCE_PAYLOAD_HANDLE_PREFIX,
    SOURCE_REF_SEPARATOR,
    SUPPLIED_CAPABILITY_IDS,
    build_research_egress_supply,
)
from hermes.research.controller import Controller
from hermes.research.task_handlers import build_methodology_handler
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.types import (
    IN_PROCESS_ENVIRONMENT,
    ToolGrant,
    max_risk_for,
)
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
    "CapabilityPlanePlan",
    "CloudModelSpec",
    "CompositionError",
    "EnvCredentialResolver",
    "LiveComposition",
    "SystemClock",
    "WithheldDeclaration",
    "build_capability_tool_notes",
    "build_cloud_provider",
    "build_controller",
    "build_live_composition",
    "build_live_controller",
    "build_model_binding",
    "check_composition",
    "plan_capability_plane",
    "specs_from_tiers",
    "tier_refs_from_config",
]

#: How long one model call may take at the HTTP edge.
DEFAULT_MODEL_HTTP_TIMEOUT_SECONDS = 120.0

_DIALECTS = ("anthropic", "openai")

#: The code-owned host allowlist — one canonical host per dialect, plus the
#: one reviewed gateway endpoint. A ``CloudModelSpec.host`` override may only
#: name a host already declared here, so a key-bearing transport is never
#: redirected to an undeclared host. The default is therefore exactly the
#: dialect hosts plus the reviewed gateway entry.
#: (HOST-ALLOWLIST: the override exists for a compatible gateway, but a
#: runtime-supplied host is precisely the hole — the credential rides the
#: header to whatever host the config names. Adding a gateway endpoint is a
#: code-owned change — one entry here, its dialect, and its `_PROVIDER_HOSTS`
#: binding — never a free-form config value. ``www.oxionai.com`` is
#: deliberately absent: it answers HTTP 403 (Cloudflare 1010); only the apex
#: is admitted.)
_DIALECT_HOSTS: Final[Mapping[str, frozenset[str]]] = {
    "anthropic": frozenset({"api.anthropic.com"}),
    "openai": frozenset({"api.openai.com", "oxionai.com",
                         "integrate.api.nvidia.com"}),
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
    "oxionai": ("openai", "OXIONAI_API_KEY"),
    "nvidia": ("openai", "NVIDIA_API_KEY"),
}

#: The endpoint binding for a provider whose id is not its dialect (OPS-6:
#: a compatible gateway). A canonical provider falls back to its dialect's
#: default host; anything else must be bound here, so a gateway can never
#: silently inherit the vendor host. The value must also be in
#: ``_DIALECT_HOSTS`` for the provider's dialect — `CloudModelSpec` enforces
#: that at construction.
_PROVIDER_HOSTS: Final[Mapping[str, str]] = {
    "oxionai": "oxionai.com",
    "nvidia": "integrate.api.nvidia.com",
}


class CompositionError(Exception):
    """The composition cannot run as configured. Names every problem at once."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True, slots=True)
class WithheldDeclaration:
    """One declared capability the registry cannot supply.

    Recorded per ``(profile, agent_profile, capability_id)`` — a declaration
    is a profile's statement, and the same capability declared by two profiles
    is two declarations (OPS-5 R3). It carries ids only: no arguments, no
    fetched content, no authority.
    """

    profile: str
    agent_profile: str
    capability_id: str

    def as_record(self) -> dict[str, str]:
        return {
            "profile": self.profile,
            "agent_profile": self.agent_profile,
            "capability_id": self.capability_id,
        }


@dataclass(frozen=True, slots=True)
class CapabilityPlanePlan:
    """The per-run capability facts the composition derives and records.

    ``profiles`` is a narrowed copy (never the profile files); ``grants`` is
    keyed by ``agent_profile`` because that is the key the runtime and the
    invoker both use. ``capability_line`` is the one operator line; the event
    payload is ids/counts/environment only.
    """

    profiles: Mapping[str, ProfileSpec]
    grants: Mapping[str, ToolGrant]
    withheld: tuple[WithheldDeclaration, ...]
    supplied: tuple[str, ...]
    granted: tuple[str, ...]
    capability_line: str

    def event_payload(self) -> dict[str, Any]:
        """The ``CapabilityPlaneComposed`` payload — counts, ids, environment.

        No arguments, no URLs, no fetched content, no key material. The
        withheld set is the record R6/OPS-5 R3 requires; the supplied and
        granted sets make the plane's shape reconstructible without reading
        the process state.
        """
        return {
            "supplied": list(self.supplied),
            "granted": list(self.granted),
            "withheld": [item.as_record() for item in self.withheld],
            "environment": IN_PROCESS_ENVIRONMENT,
        }


def _capability_plane_line(supplied: tuple[str, ...],
                           granted: tuple[str, ...],
                           withheld: tuple[WithheldDeclaration, ...]) -> str:
    """The one capability line: ids, environment, granted and withheld only.

    Deliberately silent on cost, tokens, dollars and bounds: the line states
    what the plane is, not what it may spend (D4/R6).
    """
    granted_text = ", ".join(granted) if granted else "none"
    withheld_text = (
        ", ".join(f"{item.profile}/{item.capability_id}" for item in withheld)
        if withheld else "none")
    return (
        f"Capability plane: {len(supplied)} supplied "
        f"({', '.join(supplied)}), {IN_PROCESS_ENVIRONMENT}; "
        f"granted {len(granted)} profile(s) ({granted_text}); "
        f"withheld {len(withheld)} declaration(s): {withheld_text}")


def plan_capability_plane(
    profiles: Mapping[str, ProfileSpec],
    *,
    supplied: Sequence[str],
    risks: Mapping[str, str],
) -> CapabilityPlanePlan:
    """Narrow profiles, derive per-``agent_profile`` grants, name the withheld set.

    Pure: it copies the profile map with ``dataclasses.replace`` and mints no
    authority beyond what the declared tools and the supplied set support.

    * a declared tool the registry supplies is kept;
    * a declared tool the registry does not supply is withheld and named;
    * a profile with no supplied tool is composed with ``tools=()``;
    * a profile with some supplied tools keeps the supplied subset — it is not
      emptied (the design note's correction to OPS-5's literal wording);
    * ``allows_tool_calls`` and ``structured_fields`` are profile data and are
      left exactly as declared (OPS-5 R2).
    """
    supplied_tuple = tuple(sorted(set(supplied)))
    supplied_set = frozenset(supplied_tuple)
    narrowed: dict[str, ProfileSpec] = {}
    withheld: list[WithheldDeclaration] = []
    for name in sorted(profiles):
        spec = profiles[name]
        declared = tuple(spec.tools)
        kept = tuple(capability_id for capability_id in declared
                    if capability_id in supplied_set)
        missing = tuple(capability_id for capability_id in declared
                        if capability_id not in supplied_set)
        for capability_id in missing:
            withheld.append(WithheldDeclaration(
                profile=name, agent_profile=spec.agent_profile,
                capability_id=capability_id))
        if kept != declared:
            spec = replace(spec, tools=kept)
        narrowed[name] = spec
    withheld.sort(key=lambda item: (
        item.agent_profile, item.profile, item.capability_id))

    by_agent: dict[str, list[str]] = {}
    for spec in narrowed.values():
        for capability_id in spec.tools:
            bucket = by_agent.setdefault(spec.agent_profile, [])
            if capability_id not in bucket:
                bucket.append(capability_id)
    grants: dict[str, ToolGrant] = {}
    problems: list[str] = []
    for agent_profile in sorted(by_agent):
        capability_ids = tuple(sorted(by_agent[agent_profile]))
        missing_risks = [capability_id for capability_id in capability_ids
                         if capability_id not in risks]
        if missing_risks:
            problems.append(
                f"supplied capability(s) {missing_risks} have no declared risk "
                f"— a grant cannot be derived without a ceiling")
            continue
        grants[agent_profile] = ToolGrant(
            grant_id=f"grant.live.{agent_profile.lower()}",
            profile=agent_profile,
            tool_set_ids=frozenset({RESEARCH_EGRESS_TOOL_SET_ID}),
            max_risk=max_risk_for(
                tuple(risks[capability_id] for capability_id in capability_ids)),
            approvals=frozenset())
    if problems:
        raise CompositionError(problems)
    granted = tuple(sorted(grants))
    withheld_tuple = tuple(withheld)
    return CapabilityPlanePlan(
        profiles=narrowed,
        grants=grants,
        withheld=withheld_tuple,
        supplied=supplied_tuple,
        granted=granted,
        capability_line=_capability_plane_line(
            supplied_tuple, granted, withheld_tuple))


def _capability_tool_note(schemas: tuple[str, ...],
                          item_keys: frozenset[str]) -> str:
    """One generated ``tool_calls`` field note.

    The legal ids and schemas come from the registry declarations; the item
    keys come from the runtime's closed TOOL_CALL_KEYS; the handle/ref and
    index forms come from the supply's own constants. No list here is typed a
    second time, so a declaration change or a handle change flows into the
    prompt and fails its drift test.
    """
    keys = ", ".join(sorted(item_keys))
    if not schemas:
        return (f"no capability is reachable for this profile — a tool_calls "
                f"item is refused (ROLE). Item keys: {keys}.")
    handles = (
        f"An observation returns artifact handles "
        f"{EVIDENCE_HANDLE_PREFIX}{HANDLE_SEPARATOR}<artifact_id> and "
        f"{SOURCE_PAYLOAD_HANDLE_PREFIX}{HANDLE_SEPARATOR}<content_hash>; cite "
        f"EVIDENCE_TRANSITION as "
        f"{EVIDENCE_HANDLE_PREFIX}{SOURCE_REF_SEPARATOR}<artifact_id> and a "
        f"source/claim ref as "
        f"{SOURCE_PAYLOAD_HANDLE_PREFIX}{SOURCE_REF_SEPARATOR}<content_hash>. "
        f"A project-index artifact entry id is "
        f"<artifact_type>{SOURCE_REF_SEPARATOR}<artifact_id>; replace the type "
        f"prefix with {EVIDENCE_HANDLE_PREFIX}{SOURCE_REF_SEPARATOR} for "
        f"EVIDENCE_TRANSITION. Proposals are admitted before tool calls in the "
        f"same tick, so an artifact observed this tick can be cited only in a "
        f"later tick.")
    return ("legal capabilities: " + "; ".join(schemas)
            + f". Item keys: {keys}. " + handles)


def build_capability_tool_notes(
    plan: CapabilityPlanePlan,
    supply: Any,
    *,
    item_keys: frozenset[str],
) -> dict[str, str]:
    """Per-profile prompt notes, generated from the registry declarations.

    The note is authority-scoped: ``registry.enumerate(grant=...)`` already
    excludes anything the grant cannot reach, and the profile's narrowed
    ``spec.tools`` filters the rest. A profile with no grant gets the
    empty-reach statement. This is prompt data, never a validator.
    """
    notes: dict[str, str] = {}
    for name in sorted(plan.profiles):
        spec = plan.profiles[name]
        grant = plan.grants.get(spec.agent_profile)
        schemas: list[str] = []
        if grant is not None:
            for capability in supply.registry.enumerate(grant=grant).capabilities:
                if capability.capability_id not in spec.tools:
                    continue
                tool = supply.registry.tool_for(capability.capability_id)
                if tool is None:
                    continue
                fields: list[str] = []
                for field in tool.inputs:
                    allowed = (
                        f", one of {sorted(field.allowed_values)}"
                        if field.allowed_values else "")
                    marker = "" if field.required else "?"
                    fields.append(f"{field.name}{marker}: {field.type}{allowed}")
                schemas.append(
                    f"{capability.capability_id}({', '.join(fields)})"
                    f" — {tool.summary}")
        notes[name] = _capability_tool_note(tuple(schemas), item_keys)
    return notes


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
                spec = CloudModelSpec(
                    provider_id=provider_id, dialect=dialect,
                    model_id=model_id, api_key_env=api_key_env,
                    host=_PROVIDER_HOSTS.get(provider_id, ""))
                if not spec.host and provider_id != spec.dialect:
                    raise ValueError(
                        f"provider {provider_id!r} has no code-owned endpoint "
                        f"binding in _PROVIDER_HOSTS — a gateway must name its "
                        f"host in code, never in config")
                specs[key] = spec
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


def live_contract_rules() -> tuple[
        frozenset[str],
        dict[str, tuple[str, ...]],
        dict[str, dict[str, tuple[str, ...]]],
        dict[str, dict[str, str]]]:
    """The gateway's applicability, payload-key, value and shape rules.

    Read at call time. The composition root is the one layer allowed to bridge
    the research gateway and the runtime/model plane. Reading these constants
    here (rather than in the prompt) is the OPS-12/OPS-13/OPS-14 single-source
    rule: a validator-set change flows into the contract without a second
    hand-typed list.
    """
    from .research.gateway import (
        INTENT_PAYLOAD_KEYS,
        INTENT_PAYLOAD_SHAPES,
        INTENT_PAYLOAD_VALUE_SETS,
        WIRED_INTENT_KINDS,
    )

    available = frozenset(kind.value for kind in WIRED_INTENT_KINDS)
    payload_keys = {
        kind.value: tuple(sorted(keys))
        for kind, keys in INTENT_PAYLOAD_KEYS.items()}
    payload_values = {
        kind.value: {
            key: tuple(sorted(values))
            for key, values in sorted(sets.items())}
        for kind, sets in INTENT_PAYLOAD_VALUE_SETS.items()}
    payload_shapes = {
        kind.value: dict(sorted(shapes.items()))
        for kind, shapes in INTENT_PAYLOAD_SHAPES.items()}
    return available, payload_keys, payload_values, payload_shapes


def build_model_binding(
    cfg: HermesConfig,
    providers: Sequence[ModelProvider],
    *,
    credentials: CredentialResolver,
    clock: Any = None,
    task_tiers: Mapping[str, str] | None = None,
    default_tier: str = "m",
    tool_allowlist: frozenset[str] = frozenset(),
    available_kinds: frozenset[str] | None = None,
    payload_keys: Mapping[str, Sequence[str]] | None = None,
    payload_values: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    payload_shapes: Mapping[str, Mapping[str, str]] | None = None,
) -> ModelBinding:
    """Bind the router to the configured tiers; the binding is the model port.

    ``task_tiers`` maps a profile name (planner, researcher, ...) to a tier;
    ``default_tier`` covers the rest. A task never chooses its own model.
    ``available_kinds``/``payload_keys``/``payload_values``/``payload_shapes``
    are the OPS-12/OPS-13/OPS-14 contract guidance from the gateway's own
    constants; they are absent unless the caller supplies them.
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
        tool_allowlist=tool_allowlist,
        available_kinds=available_kinds,
        payload_keys=payload_keys,
        payload_values=payload_values,
        payload_shapes=payload_shapes)


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
    project_index: Any = None,
    grants: Mapping[str, Any] | None = None,
    capabilities: Any = None,
    capability_tool_notes: Mapping[str, str] | None = None,
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
    vector sink needs and are inert when omitted. ``project_index`` (OPS-18) is
    the read-only project-index provider; omitted, the stage prompt keeps its
    previous shape. ``grants`` and ``capabilities`` are the OPS-5B capability
    plane; omitted, the runtime keeps its pre-5B no-port refusal path, so a
    caller that does not wire them cannot accidentally run tools.
    """
    loaded = profiles if profiles is not None else load_profiles(
        directory=profiles_dir)
    handler = build_methodology_handler(
        model=model if model is not None else binding,
        profiles=loaded,
        supervisor=supervisor,
        on_stage=on_stage,
        project_index=project_index,
        grants=grants,
        capabilities=capabilities,
        capability_tool_notes=capability_tool_notes,
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
    LOOP vector collected at run end (R3). The capability fields are the
    composition's own statement — ids and counts only, never arguments or
    fetched content — so the CLI can print the one ledger line before the first
    tick.
    """

    controller: Controller
    binding: ModelBinding
    vector: LiveVector
    capability_line: str = ""
    supplied: tuple[str, ...] = ()
    granted: tuple[str, ...] = ()
    withheld: tuple[WithheldDeclaration, ...] = ()


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
    capability_machinery: Any = None,
    **controller_kwargs: Any,
) -> LiveComposition:
    """Key in the environment -> a controller, its binding, and its vector sink.

    The capability plane is built once per composed run: one supply, one
    invoker, one grant map and one withheld set. ``capability_machinery`` is a
    test seam over the already-shipped supply builder (the real chain is
    ``RecordedTransport -> allowlist -> host pin -> HTTP``); production leaves
    it ``None``.
    """
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

    clock = utc_now
    artifact_store = ArtifactStore(
        cfg.artifacts.artifact_root, ArtifactRepository(conn, clock), clock)
    try:
        supply = build_research_egress_supply(
            conn=conn, store=artifact_store, clock=clock,
            project_id=project_id, machinery=capability_machinery,
            sandbox_policy=cfg.sandbox, autonomy_caps=cfg.autonomy_caps)
    except Exception as exc:  # named composition refusal
        raise CompositionError([
            f"capability plane: {type(exc).__name__}: {exc}"]) from exc
    capability_risks = {
        capability.capability_id: capability.effective_risk(
            supply.registry.tool_for(capability.capability_id))
        for capability in supply.capabilities}
    plan = plan_capability_plane(
        load_profiles(directory=profiles_dir),
        supplied=SUPPLIED_CAPABILITY_IDS, risks=capability_risks)
    event_payload = plan.event_payload()
    correlation = "capability_plane:" + hashlib.sha256(
        json.dumps(event_payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    try:
        EventRepository(conn).append_transactional(
            clock, EventType.CAPABILITY_PLANE_COMPOSED.value,
            project_id=project_id, correlation_id=correlation,
            caused_by="composition",
            reason=("the capability plane was composed; declared-but-unsupplied "
                    "capabilities are withheld and named (OPS-5B R3)"),
            payload=event_payload)
    except Exception as exc:  # fail closed, named
        raise CompositionError([
            ("capability plane composition could not be journaled: "
             f"{type(exc).__name__}: {exc}")]) from exc

    available_kinds, payload_keys, payload_values, payload_shapes = (
        live_contract_rules())
    binding = build_model_binding(
        cfg, providers, credentials=credentials,
        task_tiers=task_tiers, default_tier=default_tier,
        available_kinds=available_kinds, payload_keys=payload_keys,
        payload_values=payload_values, payload_shapes=payload_shapes)
    supervisor = Supervisor()
    recorder = RecordingModelPort(binding)
    capability_port = CapabilityInvoker(
        registry=supply.registry,
        implementations=supply.implementations,
        clock=supply.machinery.clock,
        ledger=InMemoryIdempotencyLedger(),
        sandbox_enabled=False)
    # One recorder per composed run: every stage runtime sees this same port,
    # so M2's denominator is the run's actual invocations, never a per-stage
    # slice (R3/D3).
    capability_recorder = RecordingCapabilityPort(capability_port)
    capability_tool_notes = build_capability_tool_notes(
        plan, supply, item_keys=TOOL_CALL_KEYS)
    vector = LiveVector(supervisor=supervisor, profiles=plan.profiles,
                        recorder=recorder,
                        capabilities=capability_recorder)
    from .research.project_index import ProjectIndexReader

    controller = build_controller(
        conn, project_id=project_id, binding=binding, profiles=plan.profiles,
        model=recorder, supervisor=supervisor, on_stage=vector.record,
        project_index=ProjectIndexReader(conn),
        grants=plan.grants, capabilities=capability_recorder,
        capability_tool_notes=capability_tool_notes,
        **controller_kwargs)
    return LiveComposition(
        controller=controller, binding=binding, vector=vector,
        capability_line=plan.capability_line, supplied=plan.supplied,
        granted=plan.granted, withheld=plan.withheld)


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
    capability_machinery: Any = None,
    **controller_kwargs: Any,
) -> Controller:
    """Key in the environment -> a controller that can call a hosted model."""
    return build_live_composition(
        cfg, conn, project_id=project_id, specs=specs, environ=environ,
        transport=transport, resolve=resolve, task_tiers=task_tiers,
        default_tier=default_tier, profiles_dir=profiles_dir,
        capability_machinery=capability_machinery,
        **controller_kwargs).controller
