"""Model plane — the provider-independent LLM port (ARCHITECTURE_DELTA §2.1).

What this module is
-------------------
One port for every model call in Hermes. It owns *provider abstraction* (a
model backend is a `ModelProvider`; nothing above it names a vendor), *policy
selection* (a tier name resolves through config-declared refs, never through a
hardcoded vendor), *structured-output validation*, the *streaming envelope*,
*tool-call translation*, *retries with backoff*, the *fallback chain*, *per-call
token/context accounting*, *capability advertisement*, *credential handling* and
*model-specific configuration*.

What this module is NOT
-----------------------
**It is never an authority.** Model bytes are untrusted input. Every output
crosses back into Hermes as an envelope-wrapped `UntrustedContent`
(`hermes.security.boundaries`, §2.1 *Outputs*) inside a `ModelProposal`, which
carries rationale and is bounded to 4 KiB — never a mutation, never a decision,
never an identity. A request that asks for a decision, or a model that answers
with decision-shaped output, is refused `PROPOSAL` rather than served. This is
the `evaluation.py` discipline ("no LLM in evaluation", "no write path") applied
at the port boundary: there is nothing here to Goodhart, because nothing here
can decide.

It owns no state either: no SQLite, no transaction, no repository, no journal,
no artifact store, no lease custody. An oversized proposal is handed back as
`ModelArtifactOverflow` bytes so that the *write boundary* stores it and
recomputes content-hash identity by rule (§3.3) — this module authors no ID
anywhere, and `ModelArtifactOverflow` deliberately has no identity field.

Refusal semantics (exactly §2.1 *Errors* — no new code exists here)
------------------------------------------------------------------
Two disjoint channels, so the loop is never surprised:

1. **Policy refusals are data.** A request this port declines to serve returns a
   `ModelRefusal` whose `code` is drawn from the frozen gateway-vocabulary
   subset §2.1 names — `LOCK`, `MALFORMED_PAYLOAD`, `PROPOSAL`, `RATIONALE`,
   `ROLE` (`REFUSAL_CODES`). Nothing is raised through the loop; nothing
   succeeds silently.

   - `LOCK` — invoked without a held lease: the request carries no
     lease-generation tag. Custody stays spine-owned; this port requires only
     that the attribution tag be present (§4 B-4 — attribution comes from the
     lease generation, never from a settable ambient variable).
   - `PROPOSAL` — output presented as a decision: a contract that *asks* for a
     decision, or decision-shaped model output.
   - `ROLE` — the model proposing outside its remit: a kind outside the injected
     proposable allowlist, an undeclared tool, or a capability asked of a model
     that does not advertise it.
   - `RATIONALE` — an absent rationale where the contract requires one, or an
     oversized proposal with artifact overflow unavailable.
   - `MALFORMED_PAYLOAD` — schema violation: unknown keys, wrong types, a policy
     tier with no configured ref, a ref naming an unregistered provider or an
     unadvertised model, a context window exceeded.

2. **Transport failures are raised** unchanged through the existing
   `hermes.tools.research_sources` provider hierarchy — exactly as §2.1 mandates
   for replay ("Replay mismatch surfaces as the existing replay/provider error
   hierarchy (`ReplayUnavailableError`), unchanged") and as the provider plane
   already behaves. A missing, incompatible or corrupt fixture raises
   `ReplayUnavailableError`; a fallback chain whose every candidate failed
   raises `ProviderUnavailableError` carrying one note per candidate.

Accounting is not optional
--------------------------
`_provider_attempts` is incremented immediately *before* each provider call, and
the ledger row is written inside the `finally` that closes the attempt — so a
retry, a fallback hop, or an attempt that raised still lands exactly one row, and
a refusal that never reached a provider lands one row too (attempt 0).
`verify_accounting()` fails closed when the two disagree: an unaccounted model
call is an invariant breach, not a warning, so an untracked call cannot pass a
test.

Credential discipline
---------------------
A credential is never a payload field: `ModelCall` has no credential field at
all, so there is no path by which one could enter a request body, a log line or
an event. Two controls sit on top of that structural absence:

- credential-class *keys* supplied by a caller are **refused**
  (`MALFORMED_PAYLOAD`, naming the parameter and never its value, following the
  `RedactionError` rule); and
- a live credential *value* appearing anywhere in a call form or in a recorded
  response is a **loud invariant breach** (`ModelPlaneInvariantError`) — it means
  a secret reached a payload, a log or a fixture, which is an incident, not a
  tidy refusal.

Redaction itself follows the `tools/providers/redact.py` precedent via
`CREDENTIAL_ONLY_POLICY`; see that constant for why the plane's own call form
uses a credential-only policy rather than the provider wire policy's
default-deny.

Import direction (§3.1)
-----------------------
`hermes.tools.*` + stdlib, plus `hermes.security.boundaries` — the envelope
§2.1 *Outputs* explicitly requires — which is stdlib-only and imports nothing
from Hermes, so no dependency direction is weakened. Never `research`, never
`core`, never `persistence`, never `artifacts`, never a vendor SDK. Consequently
the proposable-kind allowlist, the tool allowlist and the credential resolver are
all *injected*: the plane never reaches up to read `IntentKind.llm_proposable()`
for itself, and it never names a vendor — tier → `"provider:model"` refs come
from `config/hermes.toml` `[model_tiers]`.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, TypeAlias, cast

from hermes.security.boundaries import UntrustedContent
from hermes.tools.providers.redact import (
    DEFAULT_POLICY,
    RedactionPolicy,
    redact_params,
)
from hermes.tools.providers.replay import ReplayUnavailableError
from hermes.tools.research_sources import (
    PermanentProviderError,
    ProviderError,
    ProviderUnavailableError,
    ProviderValidationError,
    RetryPolicy,
    TransientProviderError,
)

__all__ = [
    "CREDENTIAL_ONLY_POLICY",
    "DECISION_SHAPED_KEYS",
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "DEFAULT_TIMEOUT_SECONDS",
    "LOCK",
    "MALFORMED_PAYLOAD",
    "MAX_PROPOSAL_BYTES",
    "PROPOSAL",
    "RATIONALE",
    "REFUSAL_CODES",
    "ROLE",
    "TERMINAL_REFUSALS",
    "ChunkKind",
    "Credential",
    "CredentialResolver",
    "FieldSpec",
    "ModelArtifactOverflow",
    "ModelCall",
    "ModelCallAccount",
    "ModelChunk",
    "ModelFixture",
    "ModelPlaneError",
    "ModelPlaneInvariantError",
    "ModelPlanePolicy",
    "ModelProfile",
    "ModelProposal",
    "ModelProvider",
    "ModelRefusal",
    "ModelRequest",
    "ModelResponse",
    "ModelResult",
    "ModelRouter",
    "ModelSettings",
    "ModelSink",
    "ModelStreamResult",
    "NeutralToolCallTranslator",
    "OutputContract",
    "ProviderChunk",
    "RecordedModelProvider",
    "TokenUsage",
    "ToolCallRequest",
    "ToolCallTranslation",
    "ToolCallTranslator",
    "dump_model_fixtures",
    "fixture_from_response",
    "load_model_fixtures",
    "model_fixture_id_of",
    "normalized_model_call",
    "parse_model_ref",
]

# ── the frozen refusal subset (§2.1 Errors) — no new code may be added here ──

LOCK = "LOCK"
MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"
PROPOSAL = "PROPOSAL"
RATIONALE = "RATIONALE"
ROLE = "ROLE"

#: The complete set of refusal codes this plane may emit. Every member already
#: exists in the gateway vocabulary (`gateway.py` rejection-code block); this
#: plane introduces none (§2.1: "This delta introduces none").
REFUSAL_CODES: frozenset[str] = frozenset({
    LOCK, MALFORMED_PAYLOAD, PROPOSAL, RATIONALE, ROLE,
})

#: A refusal that is a partition or authority breach rather than a transient
#: model misbehaviour is terminal: never retried, never fallen back. Another
#: model answering the same illegal question is not a fix — it is a second
#: breach.
TERMINAL_REFUSALS: frozenset[str] = frozenset({LOCK, PROPOSAL, ROLE})

#: The event-payload cap (§3.3, `event_validation.py`). A model proposal is an
#: event-payload-shaped crossing, so it inherits the same bound.
MAX_PROPOSAL_BYTES = 4096

DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_TIMEOUT_SECONDS = 120.0

#: Default cap for a recorded response body (a recording whose bytes exceed it
#: is refused loudly rather than silently truncated).
DEFAULT_MAX_RESPONSE_BYTES = 1 << 20

#: Redaction for the plane's *own* call form. `redact.DEFAULT_POLICY` is
#: fail-closed by default-deny because its inputs are open wire param dicts. A
#: model call is not a wire form: it is built here from a closed key set, so
#: default-deny would mask every legitimate key and destroy the determinism the
#: replay path depends on. Only credential-class names are classified, and any
#: that appear are *refused* (not merely masked) by the payload guard —
#: redaction here is defence in depth behind a fail-closed guard, matching the
#: redact.py precedent rather than replacing it.
CREDENTIAL_ONLY_POLICY = RedactionPolicy(
    credential_aliases=DEFAULT_POLICY.credential_aliases,
    polite_identifiers=frozenset(),
    default_deny=False,
)

#: Output keys refused on sight at the top level of structured model output: a
#: model answering a decision-shaped question has crossed from proposal into
#: verdict, whatever the contract said.
DECISION_SHAPED_KEYS: frozenset[str] = frozenset({
    "decision", "verdict", "adjudication", "approved", "rejected",
})

#: Declared output field types, and the only ones a contract may name.
_FIELD_TYPE_CHECKS: dict[str, Callable[[object], bool]] = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: (isinstance(value, (int, float))
                             and not isinstance(value, bool)),
    "boolean": lambda value: isinstance(value, bool),
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
}


# ── errors ──


class ModelPlaneError(ProviderError):
    """Base for model-plane errors — joins the existing provider hierarchy so
    callers classify by class and `hazard_class`, never by message text."""


class ModelPlaneInvariantError(ModelPlaneError):
    """A model-plane invariant was breached: an unaccounted call, or a recorded
    form that still contained a live credential.

    Fail-closed and loud — a silent accounting gap or a silent credential leak
    is worse than a failed task (the `RecordTooLargeError` precedent: "refused
    loudly, never silently dropped").
    """


# ── value types ──


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token accounting for one call, as reported by the provider."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(self.input_tokens + other.input_tokens,
                          self.output_tokens + other.output_tokens)


@dataclass(frozen=True, slots=True)
class ModelSettings:
    """Model-specific configuration, declared per model (never per vendor).

    `options` names *this model's* declared knobs. A caller-supplied option
    outside the selected model's declared set refuses rather than being
    forwarded blindly: a closed schema at the model edge, mirroring the closed
    request schema.
    """

    max_output_tokens: int | None = None
    timeout_seconds: float | None = None
    options: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Static, declared capability/profile metadata (§2.1 operation 2).

    Advertisement, not proof: the plane uses it to select and to refuse early,
    and never treats it as a guarantee about what a model will return. `tiers`
    records which policy tiers the model may serve; an empty tuple means "any".
    Config remains the only selector — `tier_refs` decides what is reachable at
    all, so a model cannot be reached just by naming it.
    """

    provider_id: str
    model_id: str
    context_window_tokens: int
    max_output_tokens: int
    supports_streaming: bool = False
    supports_tool_calls: bool = False
    supports_structured_output: bool = False
    modalities: tuple[str, ...] = ("text",)
    tiers: tuple[str, ...] = ()
    input_cost_per_1k_tokens: float = 0.0
    output_cost_per_1k_tokens: float = 0.0
    settings: ModelSettings = field(default_factory=ModelSettings)

    def serves_tier(self, tier: str) -> bool:
        return not self.tiers or tier in self.tiers


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One field of a declared output contract."""

    name: str
    type: str  # "string"|"integer"|"number"|"boolean"|"array"|"object"
    required: bool = True
    allowed_values: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class OutputContract:
    """The explicit output contract.

    `allows_decision` exists in order to be refused: a caller that asks for a
    decision gets `PROPOSAL`, because model output is never an authority.
    `kind_field`, when set, is checked against the injected proposable
    allowlist — a value outside it is `ROLE` (a partition breach), not a schema
    slip. `rationale_field`, when set, is required non-empty (`RATIONALE` when
    absent).
    """

    name: str
    fields: tuple[FieldSpec, ...] = ()
    kind_field: str = ""
    rationale_field: str = ""
    allows_decision: bool = False


@dataclass(frozen=True, slots=True)
class Credential:
    """An opaque credential.

    The value is reachable only through `reveal()`, and every string form is
    masked, so a credential cannot leak through an f-string, a log line, a
    traceback, a digest or a recorded fixture by accident. Only the transport
    edge that injects it (inside a `ModelProvider`) should call `reveal()`.
    """

    name: str
    _value: str = field(repr=False, default="")

    def reveal(self) -> str:
        return self._value

    def __str__(self) -> str:
        return f"<Credential name={self.name!r} value=<redacted>>"


class CredentialResolver(Protocol):
    """Supplies credentials by provider id.

    The plane calls this only to learn *which* secrets exist, so that it can
    refuse to emit or record any form containing one. It never builds a request
    from the result.
    """

    def resolve(self, provider_id: str) -> "Credential | None": ...


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    """A translated, provider-neutral tool-call *request*.

    The model plane never executes it. This is a proposal handed to the
    CAPABILITY plane, which owns hazard gating, rate limiting, redaction and
    whatever observation it may return. `provider_call_ref` is the provider's own
    correlation token — provenance only, never an identity, and never trusted as
    one.
    """

    provider_call_ref: str
    tool_name: str
    arguments: Mapping[str, Any]
    raw: UntrustedContent


class ChunkKind(str, Enum):
    """The neutral streaming vocabulary."""

    DELTA = "DELTA"
    TOOL_CALL = "TOOL_CALL"
    USAGE = "USAGE"
    END = "END"


@dataclass(frozen=True, slots=True)
class ProviderChunk:
    """A RAW chunk as a provider emits it (before enveloping)."""

    kind: ChunkKind
    text: str = ""
    usage: TokenUsage | None = None
    tool_calls_raw: str = ""


@dataclass(frozen=True, slots=True)
class ModelChunk:
    """An ENVELOPED chunk — the streaming envelope.

    `text` is an `UntrustedContent`, never a bare `str`: a partial model answer
    cannot be interpolated into a prompt, a log line or a refusal detail without
    the explicit, grep-auditable `.text` unwrap.
    """

    kind: ChunkKind
    text: UntrustedContent | None = None
    usage: TokenUsage | None = None
    tool_calls: tuple[ToolCallRequest, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """A RAW provider response (untrusted and unenveloped — the plane envelops)."""

    text: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str = "stop"
    tool_calls_raw: str = ""


@dataclass(frozen=True, slots=True)
class ModelCall:
    """The closed, provider-facing call form.

    Built by the router from a `ModelRequest`. Contains no credential field and
    no free-form kwargs. `payload` is the request body; `options` the
    model-specific knobs, already validated against the model's declared set.
    """

    provider_id: str
    model_id: str
    payload: Mapping[str, Any]
    options: Mapping[str, str] = field(default_factory=dict)
    output_contract: Mapping[str, Any] | None = None
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    stream: bool = False


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """A closed request (§2.1 Inputs): tier/profile id, envelope-wrapped context,
    an explicit output contract, and the lease-generation tag.

    There are no free-form kwargs. A request supplied as a mapping goes through
    `from_mapping`, which refuses unknown keys. Streaming is not a request flag:
    it is the separate `ModelRouter.invoke_stream` entry point, so a caller
    cannot half-ask for a stream.
    """

    tier: str
    profile: str
    lease_generation: str
    prompt: tuple[UntrustedContent, ...] = ()
    output_contract: OutputContract | None = None
    rationale: str = ""
    max_output_tokens: int | None = None
    tools: tuple[str, ...] = ()
    options: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def field_names(cls) -> frozenset[str]:
        return frozenset({
            "tier", "profile", "lease_generation", "prompt",
            "output_contract", "rationale", "max_output_tokens",
            "tools", "options",
        })

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ModelRequest | ModelRefusal":
        """Build from a mapping, refusing unknown keys (closed schema).

        Returns `ModelRefusal(MALFORMED_PAYLOAD)` — it never raises for a caller
        error — so a malformed request is data at the boundary like every other
        policy refusal.
        """
        unknown = sorted(set(data) - cls.field_names())
        if unknown:
            return ModelRefusal(
                code=MALFORMED_PAYLOAD,
                detail=f"unknown request keys: {unknown}",
                tier=str(data.get("tier", "")))
        missing = [key for key in ("tier", "profile", "lease_generation")
                   if not data.get(key)]
        if missing:
            return ModelRefusal(
                code=MALFORMED_PAYLOAD,
                detail=f"missing required request keys: {missing}",
                tier=str(data.get("tier", "")))
        return cls(
            tier=str(data["tier"]),
            profile=str(data["profile"]),
            lease_generation=str(data["lease_generation"]),
            prompt=tuple(data.get("prompt") or ()),
            output_contract=data.get("output_contract"),
            rationale=str(data.get("rationale") or ""),
            max_output_tokens=data.get("max_output_tokens"),
            tools=tuple(data.get("tools") or ()),
            options=dict(data.get("options") or {}))


@dataclass(frozen=True, slots=True)
class ModelArtifactOverflow:
    """An oversized proposal handed back as bytes for the write boundary.

    Deliberately carries **no identity field**: §3.3 forbids any plane from
    supplying, caching or trusting an ID, so the artifact write boundary
    recomputes content-hash identity by rule. This object is a transfer
    envelope, not a record.
    """

    body: bytes
    size_bytes: int
    media_type: str = "application/json"


@dataclass(frozen=True, slots=True)
class ModelProposal:
    """The port's only successful output: an untrusted proposal.

    Not a mutation, not an authority, not an identity. `content` and `rationale`
    are envelope-wrapped and the whole thing is bounded by
    `ModelPolicy.max_proposal_bytes`, with artifact-ref overflow for anything
    larger. On overflow the bounded fields are emptied and `overflow` carries
    the bytes — the proposal stays bounded while nothing is silently dropped.
    """

    provider_id: str
    model_id: str
    tier: str
    profile: str
    lease_generation: str
    content: UntrustedContent | None = None
    structured: Mapping[str, Any] = field(default_factory=dict)
    rationale: UntrustedContent | None = None
    tool_calls: tuple[ToolCallRequest, ...] = ()
    overflow: ModelArtifactOverflow | None = None
    account: "ModelCallAccount | None" = None


@dataclass(frozen=True, slots=True)
class ModelRefusal:
    """Refusal-as-data: `{"rejected": True, "code", "detail"}` plus provenance.

    `code` is always a member of `REFUSAL_CODES`.
    """

    code: str
    detail: str
    tier: str = ""
    provider_id: str = ""
    model_id: str = ""
    account: "ModelCallAccount | None" = None

    def as_dict(self) -> dict[str, Any]:
        """The shape §2.4 gives gateway refusals, so a plane refusal and a spine
        refusal are recognisably the same discipline."""
        return {"rejected": True, "code": self.code, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ModelCallAccount:
    """One ledger row — exactly one per attempt.

    `normalized_request` is the redacted call form: the *only* description of a
    call that is ever recorded, so nothing log-shaped can carry a credential
    (the call form has no credential field to begin with).
    """

    sequence: int
    tier: str
    profile: str
    provider_id: str
    model_id: str
    attempt: int  # 1-based; 0 = refused before any provider call
    outcome: str  # "OK" | "REFUSED" | "TRANSIENT" | "PERMANENT"
    lease_generation: str
    request_digest: str
    normalized_request: Mapping[str, Any]
    retrieved_at: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    context_tokens: int = 0
    refusal_code: str | None = None
    failure_class: str | None = None
    price_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ModelStreamResult:
    """A materialised stream plus its account.

    Materialised rather than lazily yielded, so the plane keeps the two
    properties it exists to provide: byte-identical replay and accounting
    exactness. A half-consumed generator would make "one row per attempt" depend
    on the caller's iteration. `iter_chunks()` is the consumption API for
    callers that want the streaming shape.
    """

    chunks: tuple[ModelChunk, ...] = ()
    account: ModelCallAccount | None = None
    refusal: ModelRefusal | None = None

    def iter_chunks(self) -> Iterator[ModelChunk]:
        yield from self.chunks

    @property
    def text(self) -> str:
        """The concatenated deltas — the deliberate unwrap seam for a caller
        that has decided to use model text."""
        return "".join(
            chunk.text.text for chunk in self.chunks
            if chunk.kind is ChunkKind.DELTA and chunk.text is not None)


ModelResult: TypeAlias = "ModelProposal | ModelRefusal"
ModelSink: TypeAlias = Callable[["ModelFixture"], None]
ToolCallTranslation: TypeAlias = "tuple[ToolCallRequest, ...] | ModelRefusal"


# ── canonicalisation + fixture identity ──


def _canonical_bytes(value: Any) -> bytes:
    """Deterministic canonical serialisation (the corpus/identity preimage)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str).encode("utf-8")


def parse_model_ref(ref: str) -> tuple[str, str]:
    """Parse a config model ref `"provider:model"` into its two parts.

    Raises `ProviderValidationError` on a malformed ref: a config ref is a
    startup surface, and `load_config`'s discipline is to fail loudly rather
    than run with a value it cannot interpret.
    """
    if not isinstance(ref, str) or ref.count(":") != 1:
        raise ProviderValidationError(
            f"model ref must be 'provider:model', got {ref!r}",
            hazard_class="MALFORMED_REQUEST", recordable=False)
    provider_id, model_id = (part.strip() for part in ref.split(":"))
    if not provider_id or not model_id:
        raise ProviderValidationError(
            f"model ref must name both a provider and a model, got {ref!r}",
            hazard_class="MALFORMED_REQUEST", recordable=False)
    return provider_id, model_id


def normalized_model_call(
    call: ModelCall,
    policy: RedactionPolicy = CREDENTIAL_ONLY_POLICY,
) -> dict[str, Any]:
    """The canonical redacted call form.

    The only description of a call that is recorded or digested. There is no
    credential field to strip, and credential-class names are already refused
    before a call is built; the policy is still applied as defence in depth, so a
    future field added to `ModelCall` cannot silently become recordable.
    """
    payload = call.payload if isinstance(call.payload, Mapping) else {}
    options = call.options if isinstance(call.options, Mapping) else {}
    return {
        "provider_id": call.provider_id,
        "model_id": call.model_id,
        "payload": _redact_mapping(payload, policy),
        "options": _redact_mapping(options, policy),
        "contract": call.output_contract,
        "max_output_tokens": call.max_output_tokens,
        "stream": call.stream,
    }


def _redact_mapping(mapping: Mapping[Any, Any],
                    policy: RedactionPolicy) -> dict[str, Any]:
    """Redact a mapping by KEY, preserving each value's original structure.

    `redact_params` takes `dict[str, str]` because its inputs are open wire param
    dicts whose values are already strings. A model call's payload is nested
    (`prompt` is a list of envelopes), and stringifying it would make the recorded
    form — both the audit artifact and the replay-identity preimage — unreadable
    and escape-sensitive for no security gain, because the thing being classified
    is the *name*. So the name is classified through the same policy and the value
    is replaced only when that name is classified.
    """
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        name = str(key)
        classified = redact_params({name: ""}, policy)[name] != ""
        out[name] = "<redacted>" if classified else value
    return out


def model_fixture_id_of(
    provider_id: str,
    model_id: str,
    normalized: Mapping[str, Any],
) -> str:
    """Deterministic fixture identity over (provider, model, normalized call).

    Recomputed by rule, never authored: `load_model_fixtures` recomputes it for
    every record and refuses a corpus whose stored id disagrees, so a fixture id
    cannot be supplied from outside. `fx_`-class, mirroring
    `tools/providers/replay.py`'s rule and prefix.
    """
    if not provider_id or not model_id:
        raise ProviderValidationError(
            "fixture identity requires provider_id and model_id",
            hazard_class="MALFORMED_REQUEST", recordable=False)
    raw = _canonical_bytes({
        "provider_id": provider_id,
        "model_id": model_id,
        "request": dict(normalized),
    })
    return "fx_" + hashlib.sha256(raw).hexdigest()[:24]


# ── record / replay ──


@dataclass(frozen=True, slots=True)
class ModelFixture:
    """One serialisable replay fixture (a corpus unit).

    Stores the recorded response as bytes (`text_hex`) so replay is
    byte-identical, plus the recorded stream chunk sequence so a replayed
    stream is byte-identical too. The identity is *recomputed* on load.
    """

    fixture_id: str
    provider_id: str
    model_id: str
    transport_version: str
    normalized_request: Mapping[str, Any]
    text_hex: str = ""
    text_hash: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"
    tool_calls_raw: str = ""
    chunk_kinds: tuple[str, ...] = ()
    chunk_texts_hex: tuple[str, ...] = ()

    def to_mapping(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "transport_version": self.transport_version,
            "normalized_request": dict(self.normalized_request),
            "text_hex": self.text_hex,
            "text_hash": self.text_hash,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "finish_reason": self.finish_reason,
            "tool_calls_raw": self.tool_calls_raw,
            "chunk_kinds": list(self.chunk_kinds),
            "chunk_texts_hex": list(self.chunk_texts_hex),
        }

    def response_text(self) -> str:
        return bytes.fromhex(self.text_hex).decode("utf-8") if self.text_hex else ""

    def usage(self) -> TokenUsage:
        return TokenUsage(self.input_tokens, self.output_tokens)

    @staticmethod
    def from_mapping(data: Mapping[str, Any]) -> "ModelFixture":
        """Parse one fixture, recomputing and checking its identity.

        Corrupt or authored fixtures fail loudly (never a partial load), and the
        stored `fixture_id` is treated as a claim to be checked rather than a
        key to be trusted.
        """
        if not isinstance(data, dict):
            raise ReplayUnavailableError(
                "corrupt model fixture: not a mapping",
                hazard_class="FIXTURE_CORRUPT", recordable=False)
        for key in ("provider_id", "model_id", "transport_version",
                    "normalized_request"):
            if not data.get(key):
                raise ReplayUnavailableError(
                    f"corrupt model fixture: missing {key!r}",
                    hazard_class="FIXTURE_CORRUPT", recordable=False)
        normalized = data["normalized_request"]
        if not isinstance(normalized, dict):
            raise ReplayUnavailableError(
                "corrupt model fixture: normalized_request is not a mapping",
                hazard_class="FIXTURE_CORRUPT", recordable=False)
        recomputed = model_fixture_id_of(str(data["provider_id"]),
                                        str(data["model_id"]), normalized)
        stored = str(data.get("fixture_id") or "")
        if stored != recomputed:
            raise ReplayUnavailableError(
                f"corrupt model fixture: fixture_id {stored!r} is not the "
                f"recomputed identity {recomputed!r} (ids are recomputed by "
                f"rule, never authored)",
                hazard_class="FIXTURE_CORRUPT", recordable=False)
        text_hex = str(data.get("text_hex") or "")
        text_hash = str(data.get("text_hash") or "")
        if text_hex:
            try:
                body = bytes.fromhex(text_hex)
            except ValueError:
                raise ReplayUnavailableError(
                    "corrupt model fixture: text_hex is not hex",
                    hazard_class="FIXTURE_CORRUPT", recordable=False) from None
            if text_hash and hashlib.sha256(body).hexdigest() != text_hash:
                raise ReplayUnavailableError(
                    "corrupt model fixture: text hash mismatch",
                    hazard_class="FIXTURE_CORRUPT", recordable=False)
        chunk_kinds = tuple(str(kind) for kind in
                           (data.get("chunk_kinds") or ()))
        chunk_texts_hex = tuple(str(text) for text in
                                (data.get("chunk_texts_hex") or ()))
        if len(chunk_kinds) != len(chunk_texts_hex):
            raise ReplayUnavailableError(
                "corrupt model fixture: chunk kinds and chunk texts disagree "
                f"({len(chunk_kinds)} vs {len(chunk_texts_hex)})",
                hazard_class="FIXTURE_CORRUPT", recordable=False)
        return ModelFixture(
            fixture_id=recomputed,
            provider_id=str(data["provider_id"]),
            model_id=str(data["model_id"]),
            transport_version=str(data["transport_version"]),
            normalized_request=dict(normalized),
            text_hex=text_hex,
            text_hash=text_hash,
            input_tokens=int(data.get("input_tokens") or 0),
            output_tokens=int(data.get("output_tokens") or 0),
            finish_reason=str(data.get("finish_reason") or "stop"),
            tool_calls_raw=str(data.get("tool_calls_raw") or ""),
            chunk_kinds=chunk_kinds,
            chunk_texts_hex=chunk_texts_hex)


def fixture_from_response(
    provider_id: str,
    model_id: str,
    transport_version: str,
    normalized: Mapping[str, Any],
    response: ModelResponse,
    chunks: tuple[ProviderChunk, ...] = (),
) -> ModelFixture:
    """Build a fixture from a recorded response (deterministic; id recomputed)."""
    body = response.text.encode("utf-8")
    return ModelFixture(
        fixture_id=model_fixture_id_of(provider_id, model_id, normalized),
        provider_id=provider_id,
        model_id=model_id,
        transport_version=transport_version,
        normalized_request=dict(normalized),
        text_hex=body.hex(),
        text_hash=hashlib.sha256(body).hexdigest(),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        finish_reason=response.finish_reason,
        tool_calls_raw=response.tool_calls_raw,
        chunk_kinds=tuple(chunk.kind.value for chunk in chunks),
        chunk_texts_hex=tuple(chunk.text.encode("utf-8").hex()
                              for chunk in chunks))


def load_model_fixtures(path: str) -> dict[str, ModelFixture]:
    """Load a fixture corpus file `{"fixtures": [...]}` keyed by fixture id.

    Corrupt files fail loudly (never a partial load); each record's identity is
    recomputed and checked by `ModelFixture.from_mapping`.
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("fixtures"), list):
        raise ReplayUnavailableError(
            f"corrupt model fixture file {path!r}: expected "
            f'{{"fixtures": [...]}}',
            hazard_class="FIXTURE_CORRUPT", recordable=False)
    out: dict[str, ModelFixture] = {}
    for raw in data["fixtures"]:
        record = ModelFixture.from_mapping(raw)
        out[record.fixture_id] = record
    return out


def dump_model_fixtures(records: Iterable[ModelFixture], path: str) -> None:
    """Write a fixture corpus file (deterministic order)."""
    ordered = sorted(records, key=lambda record: record.fixture_id)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"fixtures": [record.to_mapping() for record in ordered]},
                  handle, sort_keys=True, indent=2, ensure_ascii=False)
        handle.write("\n")


class ModelProvider(Protocol):
    """A model backend — the provider abstraction.

    A vendor SDK, a local runner or a scripted fake all satisfy this shape, and
    nothing above it names a vendor. `describe()` is *declared metadata* and must
    be local: it never contacts the model, which is what lets replay answer it
    without network. Implementations return RAW text; the plane owns the
    untrusted-content envelope, so a provider cannot forget to apply it.
    """

    provider_id: str

    def describe(self) -> tuple[ModelProfile, ...]: ...

    def invoke(self, call: ModelCall) -> ModelResponse: ...

    def stream(self, call: ModelCall) -> tuple[ProviderChunk, ...]: ...


class ToolCallTranslator(Protocol):
    """Translates a provider's native tool-call blob into the neutral shape.

    Returns either the translated calls or a `ModelRefusal` — it never raises a
    caller error through the loop, so a provider with an exotic tool-call format
    cannot smuggle a refusal into an exception.
    """

    def translate(self, raw: UntrustedContent, *,
                  allowed_tools: frozenset[str]) -> "ToolCallTranslation": ...


class NeutralToolCallTranslator:
    """The neutral tool-call shape: `{"calls": [{...}]}`.

    A provider adapter translates its own format into this one; the plane then
    owns validation. Undeclared top-level keys, an undeclared entry key, a
    non-object arguments value or a non-JSON blob refuse `MALFORMED_PAYLOAD`; a
    tool the caller never declared refuses `ROLE` — asking for a capability
    outside the declared set is a remit breach, not a formatting slip.
    """

    _ENTRY_KEYS = frozenset({"provider_call_ref", "tool_name", "arguments"})

    def translate(self, raw: UntrustedContent, *,
                  allowed_tools: frozenset[str]) -> "ToolCallTranslation":
        try:
            payload = json.loads(raw.text)
        except (TypeError, ValueError):
            return ModelRefusal(code=MALFORMED_PAYLOAD,
                                detail="tool-call payload is not JSON")
        if not isinstance(payload, dict):
            return ModelRefusal(code=MALFORMED_PAYLOAD,
                                detail="tool-call payload must be an object")
        unknown = sorted(set(payload) - {"calls"})
        if unknown:
            return ModelRefusal(
                code=MALFORMED_PAYLOAD,
                detail=f"unknown tool-call keys: {unknown}")
        entries = payload.get("calls")
        if not isinstance(entries, list):
            return ModelRefusal(code=MALFORMED_PAYLOAD,
                                detail="tool-call payload requires a 'calls' list")
        translated: list[ToolCallRequest] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                return ModelRefusal(
                    code=MALFORMED_PAYLOAD,
                    detail=f"tool call {index} is not an object")
            unknown_entry = sorted(set(entry) - self._ENTRY_KEYS)
            if unknown_entry:
                return ModelRefusal(
                    code=MALFORMED_PAYLOAD,
                    detail=f"unknown keys in tool call {index}: {unknown_entry}")
            tool_name = str(entry.get("tool_name") or "")
            if not tool_name:
                return ModelRefusal(
                    code=MALFORMED_PAYLOAD,
                    detail=f"tool call {index} names no tool")
            if tool_name not in allowed_tools:
                return ModelRefusal(
                    code=ROLE,
                    detail=f"model requested undeclared tool {tool_name!r}")
            arguments = entry.get("arguments", {})
            if not isinstance(arguments, dict):
                return ModelRefusal(
                    code=MALFORMED_PAYLOAD,
                    detail=f"tool call {index} arguments must be an object")
            translated.append(ToolCallRequest(
                provider_call_ref=str(entry.get("provider_call_ref")
                                      or f"call-{index}"),
                tool_name=tool_name,
                arguments=dict(arguments),
                raw=raw))
        return tuple(translated)


class RecordedModelProvider:
    """A `ModelProvider` wrapper adding record/replay (the deterministic path).

    Replay serves fixtures by recomputed fixture id and **never touches the
    wrapped provider** — the zero-network guarantee is structural, not
    conditional, so a replay-mode bug cannot reach a live model. Record mode
    delegates, checks the response against the size cap and the secret scan, then
    reports the built fixture to the sink (persistence lives with the sink; this
    class holds no connection, preserving the SD2-03 shape).

    `transport_version` plays the role adapter/parser version plays for data
    providers: a fixture recorded under a different transport version refuses
    rather than being silently reinterpreted.
    """

    def __init__(
        self,
        inner: ModelProvider,
        *,
        provider_id: str,
        model_id: str,
        transport_version: str,
        mode: str = "record",
        sink: ModelSink | None = None,
        fixtures: Mapping[str, ModelFixture] | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        redaction_policy: RedactionPolicy = CREDENTIAL_ONLY_POLICY,
        secrets: tuple[str, ...] = (),
    ) -> None:
        if mode not in ("record", "replay"):
            raise ProviderValidationError(
                f"unknown RecordedModelProvider mode {mode!r}",
                provider_id=provider_id,
                hazard_class="MALFORMED_REQUEST", recordable=False)
        if not provider_id or not model_id:
            raise ProviderValidationError(
                "RecordedModelProvider requires provider_id and model_id",
                hazard_class="MALFORMED_REQUEST", recordable=False)
        self._inner = inner
        self.provider_id = provider_id
        self.model_id = model_id
        self.transport_version = transport_version
        self._mode = mode
        self._sink = sink
        self._fixtures = dict(fixtures) if fixtures else {}
        self._max_response_bytes = max_response_bytes
        self._policy = redaction_policy
        self._secrets = tuple(secret for secret in secrets if secret)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def fixtures(self) -> Mapping[str, ModelFixture]:
        return dict(self._fixtures)

    def describe(self) -> tuple[ModelProfile, ...]:
        """Declared metadata — delegated, and never a network call."""
        return self._inner.describe()

    def replay_bytes(self, call: ModelCall) -> bytes:
        """The recorded-bytes path (§2.1 operation 3): fixtures only, no contact.

        Works only in replay mode; a record-mode provider refuses, because
        "replay" that could reach a live model is not replay.
        """
        if self._mode != "replay":
            raise ReplayUnavailableError(
                f"replay requested but {self.provider_id!r} is in record mode",
                provider_id=self.provider_id,
                hazard_class="REPLAY_UNAVAILABLE", recordable=False)
        normalized = normalized_model_call(call, self._policy)
        record = self._fixture_for(normalized)
        return bytes.fromhex(record.text_hex) if record.text_hex else b""

    def invoke(self, call: ModelCall) -> ModelResponse:
        normalized = normalized_model_call(call, self._policy)
        if self._mode == "replay":
            record = self._fixture_for(normalized)
            return ModelResponse(text=record.response_text(),
                                 usage=record.usage(),
                                 finish_reason=record.finish_reason,
                                 tool_calls_raw=record.tool_calls_raw)
        response = self._inner.invoke(call)
        self._verify_response(response)
        record = fixture_from_response(self.provider_id, self.model_id,
                                       self.transport_version, normalized,
                                       response)
        self._publish(record)
        return response

    def stream(self, call: ModelCall) -> tuple[ProviderChunk, ...]:
        normalized = normalized_model_call(call, self._policy)
        if self._mode == "replay":
            record = self._fixture_for(normalized)
            return tuple(
                ProviderChunk(kind=ChunkKind(kind),
                              text=bytes.fromhex(text_hex).decode("utf-8"))
                for kind, text_hex in zip(record.chunk_kinds,
                                          record.chunk_texts_hex,
                                          strict=True))
        chunks = self._inner.stream(call)
        self._verify_response(_response_from_chunks(chunks))
        record = fixture_from_response(self.provider_id, self.model_id,
                                       self.transport_version, normalized,
                                       _response_from_chunks(chunks), chunks)
        self._publish(record)
        return chunks

    # ── internals ──

    def _fixture_for(self, normalized: Mapping[str, Any]) -> ModelFixture:
        fixture_id = model_fixture_id_of(self.provider_id, self.model_id,
                                        normalized)
        record = self._fixtures.get(fixture_id)
        if record is None:
            raise ReplayUnavailableError(
                f"no model fixture for {fixture_id!r} "
                f"(provider {self.provider_id!r}, model {self.model_id!r})",
                provider_id=self.provider_id,
                hazard_class="FIXTURE_MISSING", recordable=False)
        if record.transport_version != self.transport_version:
            raise ReplayUnavailableError(
                f"model fixture {fixture_id!r} pins transport "
                f"{record.transport_version!r}, replay requires "
                f"{self.transport_version!r}",
                provider_id=self.provider_id,
                hazard_class="FIXTURE_INCOMPATIBLE", recordable=False)
        return record

    def _verify_response(self, response: ModelResponse) -> None:
        body = response.text.encode("utf-8")
        if len(body) > self._max_response_bytes:
            raise ModelPlaneInvariantError(
                f"model response {len(body)} bytes exceeds the recording cap "
                f"{self._max_response_bytes} — refused loudly, never silently "
                f"dropped",
                provider_id=self.provider_id,
                hazard_class="RECORD_TOO_LARGE", recordable=False)
        self.assert_secret_free(response.text, where="model response")

    def assert_secret_free(self, value: object, *, where: str) -> None:
        """Fail closed if a live credential appears in `value`.

        A secret reaching a payload, a log line, an event or a fixture is an
        incident: it means the structural guarantee (no credential field exists)
        plus the key guard were both bypassed somewhere upstream.
        """
        if not self._secrets:
            return
        rendered = value if isinstance(value, str) else repr(value)
        for secret in self._secrets:
            if secret and secret in rendered:
                raise ModelPlaneInvariantError(
                    f"a live credential appeared in {where} — refusing to "
                    f"record it (the value is never named)",
                    provider_id=self.provider_id,
                    hazard_class="SECRET_LEAK", recordable=False)

    def _publish(self, record: ModelFixture) -> None:
        if self._sink is not None:
            self._sink(record)


def _response_from_chunks(chunks: tuple[ProviderChunk, ...]) -> ModelResponse:
    """Synthesise the whole-response view of a stream.

    Streams and one-shot responses are the same recorded interaction, so a
    stream's deltas concatenate to the response text and its USAGE chunk is the
    usage. Anything else would make the two paths non-interchangeable.
    """
    text = "".join(chunk.text for chunk in chunks
                   if chunk.kind is ChunkKind.DELTA)
    tool_calls_raw = "".join(chunk.tool_calls_raw for chunk in chunks
                             if chunk.kind is ChunkKind.TOOL_CALL)
    usage = TokenUsage()
    for chunk in chunks:
        if chunk.kind is ChunkKind.USAGE and chunk.usage is not None:
            usage = chunk.usage
    return ModelResponse(text=text, usage=usage, tool_calls_raw=tool_calls_raw)


# ── policy ──


@dataclass(frozen=True, slots=True)
class ModelPlanePolicy:
    """Model-policy selection: config-declared refs plus the fallback chain.

    `tier_refs` is `config/hermes.toml`'s `[model_tiers]` mapping (tier →
    `"provider:model"`). That indirection is the whole "core Hermes never names a
    vendor" rule made mechanical: no tier has a default model here, so an
    unconfigured tier refuses instead of silently falling back to a baked-in
    vendor.
    """

    tier_refs: Mapping[str, str] = field(default_factory=dict)
    fallback_chain: tuple[str, ...] = ()
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_proposal_bytes: int = MAX_PROPOSAL_BYTES
    allow_artifact_overflow: bool = True
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    @staticmethod
    def from_config_tiers(
        model_tiers: Mapping[str, Any],
        *,
        fallback_chain: tuple[str, ...] = (),
        **overrides: Any,
    ) -> "ModelPlanePolicy":
        """Build from a parsed `[model_tiers]` section.

        Empty values mean "not configured" and are dropped (matching
        `ModelTierConfig`'s documented convention). A malformed non-empty ref
        fails fast at construction rather than at first call.
        """
        refs = {str(tier): str(ref).strip() for tier, ref in model_tiers.items()
                if str(ref).strip()}
        for ref in refs.values():
            parse_model_ref(ref)
        return ModelPlanePolicy(tier_refs=refs,
                                fallback_chain=fallback_chain, **overrides)

    def tier_order(self, tier: str) -> tuple[str, ...]:
        """The requested tier first, then each fallback tier (deduplicated)."""
        chain = [tier]
        chain.extend(other for other in self.fallback_chain if other != tier)
        return tuple(chain)


@dataclass(frozen=True, slots=True)
class _Candidate:
    """One selectable (tier, provider, model) triple."""

    tier: str
    provider_id: str
    model_id: str
    provider: ModelProvider
    profile: ModelProfile


class _Refusal(Exception):
    """Internal control-flow signal, converted to `ModelRefusal` data at the
    public boundary. Private on purpose: it is never part of the port's contract
    and must not escape `ModelRouter`.
    """

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        retryable: bool = False,
        provider_id: str = "",
        model_id: str = "",
        account: ModelCallAccount | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable
        self.provider_id = provider_id
        self.model_id = model_id
        self.account = account


# ── the router ──


class ModelRouter:
    """The Model Provider API (§2.1): `invoke` / `invoke_stream` / `describe` /
    `replay_bytes`, with policy selection, retries, fallback and accounting.

    Everything the plane must not decide for itself is injected: the tier→model
    refs (config), the proposable-kind allowlist (the runtime passes
    `IntentKind.llm_proposable()`), the tool allowlist (the capability plane),
    the credential resolver and the clock. That is what keeps this module free of
    vendor names, free of `core` imports and free of ambient state.
    """

    def __init__(
        self,
        *,
        providers: Iterable[ModelProvider],
        policy: ModelPlanePolicy,
        clock: Any,
        proposable_kinds: frozenset[str] = frozenset(),
        tool_allowlist: frozenset[str] = frozenset(),
        credentials: CredentialResolver | None = None,
        translator: ToolCallTranslator | None = None,
        sleep: Callable[[float], None] | None = None,
        jitter_source: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._providers: dict[str, ModelProvider] = {}
        for provider in providers:
            provider_id = getattr(provider, "provider_id", "")
            if not provider_id:
                raise ProviderValidationError(
                    "every model provider must declare a provider_id",
                    hazard_class="MALFORMED_REQUEST", recordable=False)
            self._providers[str(provider_id)] = provider
        self._policy = policy
        self._clock = clock
        self._proposable_kinds = frozenset(proposable_kinds)
        self._tool_allowlist = frozenset(tool_allowlist)
        self._credentials = credentials
        self._translator: ToolCallTranslator = translator or NeutralToolCallTranslator()
        self._sleep = sleep if sleep is not None else _default_sleep(clock)
        self._jitter_source = jitter_source
        self._secrets = self._resolve_secrets()
        self._ledger: list[ModelCallAccount] = []
        self._provider_attempts = 0
        self._backoff_delays: list[float] = []

    # ── read surfaces ──

    def describe(self) -> tuple[ModelProfile, ...]:
        """Capability advertisement for every registered provider, deterministically
        ordered (provider id, then model id). Declared metadata only — no call."""
        profiles: list[ModelProfile] = []
        for provider_id in sorted(self._providers):
            profiles.extend(self._providers[provider_id].describe())
        return tuple(sorted(profiles, key=lambda p: (p.provider_id, p.model_id)))

    def profile_of(self, provider_id: str, model_id: str) -> ModelProfile | None:
        for profile in self.describe():
            if profile.provider_id == provider_id and profile.model_id == model_id:
                return profile
        return None

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def accounting(self) -> tuple[ModelCallAccount, ...]:
        return tuple(self._ledger)

    @property
    def provider_attempts(self) -> int:
        """Provider calls executed — the number the ledger must account for."""
        return self._provider_attempts

    @property
    def backoff_delays(self) -> tuple[float, ...]:
        """Delays the router actually slept, in order (observability for tests)."""
        return tuple(self._backoff_delays)

    def total_usage(self) -> TokenUsage:
        total = TokenUsage()
        for row in self._ledger:
            total = total + row.usage
        return total

    def total_price_usd(self) -> float:
        return round(sum(row.price_usd or 0.0 for row in self._ledger), 9)

    def verify_accounting(self) -> None:
        """Fail closed unless every provider attempt has a ledger row.

        The negative condition is the important one: a call that reached a
        provider with no row to show for it is an invariant breach, so this
        raises rather than warning.
        """
        accounted = sum(1 for row in self._ledger if row.attempt > 0)
        unaccounted = self._provider_attempts - accounted
        if unaccounted:
            raise ModelPlaneInvariantError(
                f"{unaccounted} model call(s) executed without an accounting "
                f"record (provider attempts={self._provider_attempts}, "
                f"accounted rows={accounted}) — an untracked call is an "
                f"invariant breach",
                hazard_class="ACCOUNTING_GAP", recordable=False)
        for index, row in enumerate(self._ledger):
            if row.sequence != index:
                raise ModelPlaneInvariantError(
                    f"accounting sequence broken at index {index}: row claims "
                    f"{row.sequence}",
                    hazard_class="ACCOUNTING_GAP", recordable=False)

    # ── the port ──

    def invoke(self, request: ModelRequest) -> "ModelResult":
        """One bounded inference call → an untrusted proposal, or a refusal."""
        try:
            self._require_lease(request)
            self._require_contract(request)
            self._require_non_secret_options(request)
            candidates = self._candidates(request, require_stream=False)
            self._require_known_options(request, candidates)
        except _Refusal as refusal:
            return self._refuse(request, refusal)
        try:
            # `require_stream=False` cannot produce a stream result; the cast
            # states that the two public entry points never cross over.
            return cast("ModelProposal",
                        self._run_chain(candidates, request, require_stream=False))
        except _Refusal as refusal:
            return self._refuse(request, refusal)

    def invoke_stream(self, request: ModelRequest) -> ModelStreamResult:
        """The streaming entry point — same policy, same accounting, enveloped
        chunks. Requires a candidate that advertises streaming."""
        try:
            self._require_lease(request)
            self._require_contract(request)
            self._require_non_secret_options(request)
            candidates = self._candidates(request, require_stream=True)
            self._require_known_options(request, candidates)
        except _Refusal as refusal:
            return ModelStreamResult(refusal=self._refuse(request, refusal))
        try:
            result = self._run_chain(candidates, request, require_stream=True)
        except _Refusal as refusal:
            return ModelStreamResult(refusal=self._refuse(request, refusal))
        assert isinstance(result, ModelStreamResult)
        return result

    def replay_bytes(self, request: ModelRequest) -> bytes:
        """§2.1 operation 3 — the recorded-bytes path, with zero live contact.

        Contacts nothing at all, which is exactly why it writes no ledger row:
        the ledger accounts *provider invocations*, and a replay read is the
        deliberate absence of one. A missing, incompatible or corrupt fixture
        raises `ReplayUnavailableError` (§2.1: unchanged).
        """
        candidates = self._candidates(request, require_stream=False)
        candidate = candidates[0]
        provider = candidate.provider
        if not isinstance(provider, RecordedModelProvider):
            raise ReplayUnavailableError(
                f"provider {candidate.provider_id!r} is not a "
                f"RecordedModelProvider — replay has no recorded bytes to serve",
                provider_id=candidate.provider_id,
                hazard_class="REPLAY_UNAVAILABLE", recordable=False)
        call = self._build_call(candidate, request, stream=False)
        return provider.replay_bytes(call)

    # ── request guards ──

    def _require_lease(self, request: ModelRequest) -> None:
        """`LOCK` — invoked without a held lease (§4 B-4).

        The plane checks *presence of the attribution tag*, never custody: the
        lease is spine-owned, and a plane that verified ownership would be a
        second lease authority. An empty tag means the call cannot be attributed
        to a generation, which is the condition `LOCK` names.
        """
        if not request.lease_generation.strip():
            raise _Refusal(
                LOCK,
                "invoked without a lease-generation tag — the call could not be "
                "attributed to a lease generation (§4 B-4)")

    def _require_contract(self, request: ModelRequest) -> None:
        contract = request.output_contract
        if request.tools and not self._tool_allowlist:
            raise _Refusal(
                MALFORMED_PAYLOAD,
                "tools were requested but no tool allowlist is declared — the "
                "capability plane owns that allowlist and none was injected")
        if contract is None:
            return
        if contract.allows_decision:
            raise _Refusal(
                PROPOSAL,
                f"output contract {contract.name!r} asks for a decision — model "
                f"output is never an authority (proposals only)")
        for spec in contract.fields:
            if spec.type not in _FIELD_TYPE_CHECKS:
                raise _Refusal(
                    MALFORMED_PAYLOAD,
                    f"output contract {contract.name!r} declares unknown type "
                    f"{spec.type!r} for field {spec.name!r}")

    def _require_non_secret_options(self, request: ModelRequest) -> None:
        """Refuse a caller-supplied option name belonging to credential class.

        Matched *exactly* against the policy's alias set rather than through
        `redact_params`' substring rule. The substring rule exists for open wire
        param dicts, where `X-Api-Key` and `access_token_2` must not slip past.
        A model option name, by contrast, comes from a closed set declared on the
        model, and substring matching would refuse legitimate names such as
        `max_tokens` (it contains "token"). Refusing exactly the credential names
        keeps the guard fail-closed without inventing false positives that would
        make an ordinary option unusable.

        Names the parameter and never its value, following the `RedactionError`
        rule: this check runs while the raw value is still in scope.
        """
        aliases = CREDENTIAL_ONLY_POLICY.credential_aliases
        offending = sorted(
            key for key in request.options if key.strip().lower() in aliases)
        if not offending:
            return
        raise _Refusal(
            MALFORMED_PAYLOAD,
            f"credential-class option name(s) {offending} may not be supplied on "
            f"a model call — credentials are injected at the transport edge and "
            f"never enter a payload")

    def _require_known_options(
        self, request: ModelRequest, candidates: list[_Candidate]
    ) -> None:
        declared: set[str] = set()
        for candidate in candidates:
            declared.update(str(key) for key in
                            candidate.profile.settings.options)
        unknown = sorted(set(request.options) - declared)
        if unknown:
            raise _Refusal(
                MALFORMED_PAYLOAD,
                f"unknown model option(s) {unknown} for tier "
                f"{request.tier!r}; declared options: {sorted(declared)}")

    # ── selection ──

    def _candidates(
        self, request: ModelRequest, *, require_stream: bool
    ) -> list[_Candidate]:
        """Resolve the tier chain to capable candidates.

        An incapable candidate is skipped with a recorded reason rather than
        refusing outright, because that is what a fallback chain is for; the
        refusal comes only when nothing in the chain can serve the request.
        """
        unmet: list[str] = []
        candidates: list[_Candidate] = []
        for tier in self._policy.tier_order(request.tier):
            ref = self._policy.tier_refs.get(tier)
            if not ref:
                unmet.append(f"{tier}: no model configured for tier")
                continue
            try:
                provider_id, model_id = parse_model_ref(ref)
            except ProviderValidationError as exc:
                unmet.append(f"{tier}: malformed ref {ref!r} ({exc})")
                continue
            provider = self._providers.get(provider_id)
            if provider is None:
                unmet.append(f"{tier}: no provider registered as {provider_id!r}")
                continue
            profile = self._profile_of_candidate(provider_id, model_id)
            if profile is None:
                unmet.append(
                    f"{tier}: provider {provider_id!r} does not advertise "
                    f"model {model_id!r}")
                continue
            if not profile.serves_tier(tier):
                unmet.append(
                    f"{tier}: model {model_id!r} does not advertise tier {tier!r}")
                continue
            missing = self._unmet_needs(request, profile,
                                        require_stream=require_stream)
            if missing:
                unmet.append(
                    f"{tier}: model {model_id!r} does not support "
                    f"{', '.join(missing)}")
                continue
            candidates.append(_Candidate(tier, provider_id, model_id,
                                         provider, profile))
        if not candidates:
            detail = "; ".join(unmet) if unmet else "the model policy is empty"
            raise _Refusal(
                MALFORMED_PAYLOAD,
                f"no candidate model can serve this request: {detail}")
        return candidates

    def _profile_of_candidate(self, provider_id: str,
                              model_id: str) -> ModelProfile | None:
        provider = self._providers.get(provider_id)
        if provider is None:
            return None
        for profile in provider.describe():
            if profile.model_id == model_id:
                return profile
        return None

    def _unmet_needs(
        self, request: ModelRequest, profile: ModelProfile, *, require_stream: bool
    ) -> list[str]:
        """Advertised capabilities this request needs and the model lacks.

        Also where the *context budget* is enforced: a prompt whose estimated
        footprint plus the requested output cannot fit the window is a schema
        violation for that model, not something to discover mid-call.
        """
        missing: list[str] = []
        if require_stream and not profile.supports_streaming:
            missing.append("streaming")
        if request.tools and not profile.supports_tool_calls:
            missing.append("tool calls")
        if request.output_contract is not None and not profile.supports_structured_output:
            missing.append("structured output")
        estimated = self._estimate_context_tokens(request)
        budget = self._max_output_tokens(profile, request)
        if estimated + budget > profile.context_window_tokens:
            missing.append(
                f"a context window of at least {estimated + budget} tokens "
                f"(estimated {estimated} + output {budget} > "
                f"{profile.context_window_tokens})")
        return missing

    def _estimate_context_tokens(self, request: ModelRequest) -> int:
        """Deterministic pre-flight context estimate (4 characters per token).

        An estimate, not a measurement: it exists to refuse *before* spending a
        call, and the authoritative count is whatever the provider reports back
        into the ledger as `context_tokens`.
        """
        characters = sum(len(part.text) for part in request.prompt)
        characters += len(request.rationale)
        characters += sum(len(tool) for tool in request.tools)
        return (characters + 3) // 4

    def _max_output_tokens(self, profile: ModelProfile,
                           request: ModelRequest) -> int:
        """The effective output bound: the request may lower a cap, never raise
        one. Policy, model ceiling and model-declared setting are all floors-
        relative-to-request ceilings."""
        ceiling = min(self._policy.max_output_tokens, profile.max_output_tokens)
        declared = profile.settings.max_output_tokens
        if declared is not None:
            ceiling = min(ceiling, declared)
        if request.max_output_tokens is None:
            return ceiling
        return max(1, min(request.max_output_tokens, ceiling))

    def _timeout_seconds(self, profile: ModelProfile) -> float:
        declared = profile.settings.timeout_seconds
        if declared is None:
            return self._policy.timeout_seconds
        return min(declared, self._policy.timeout_seconds)

    def _build_call(self, candidate: _Candidate, request: ModelRequest,
                    *, stream: bool) -> ModelCall:
        profile = candidate.profile
        options = {str(key): str(value)
                   for key, value in profile.settings.options.items()}
        options.update({str(key): str(value)
                        for key, value in request.options.items()})
        payload = {
            # The prompt carries the caller's own text, so this is the explicit
            # unwrap seam (`security/boundaries.py` rule 2): model input must be
            # real text, and `.text` is the grep-auditable place where a caller
            # decided that the text is fit to send. Enveloped parts are *labelled*
            # with their origin/ref so a reader can tell what arrived untrusted.
            "prompt": [
                {"origin": part.origin, "ref": part.ref, "text": part.text}
                for part in request.prompt
            ],
            "rationale": request.rationale,
            "tools": sorted(request.tools),
            "profile": request.profile,
        }
        call = ModelCall(
            provider_id=candidate.provider_id,
            model_id=candidate.model_id,
            payload=payload,
            options=options,
            output_contract=(_contract_mapping(request.output_contract)
                             if request.output_contract is not None else None),
            max_output_tokens=self._max_output_tokens(profile, request),
            timeout_seconds=self._timeout_seconds(profile),
            stream=stream)
        self._assert_secret_free(normalized_model_call(call),
                                 where="a model call form")
        return call

    # ── execution ──

    def _run_chain(
        self, candidates: list[_Candidate], request: ModelRequest,
        *, require_stream: bool,
    ) -> "ModelProposal | ModelStreamResult":
        """Walk the chain: retry a transient failure on the same candidate, move
        to the next candidate on permanent failure or exhausted retries.

        A terminal refusal (`LOCK`/`PROPOSAL`/`ROLE`) stops the walk outright —
        falling back would ask a second model the same illegal question.
        """
        attempts_per_candidate = getattr(
            self._policy.retry_policy, "max_retries", 3) + 1
        notes: list[str] = []
        last_transport: ProviderError | None = None
        last_refusal: _Refusal | None = None
        for candidate in candidates:
            for attempt in range(1, attempts_per_candidate + 1):
                call = self._build_call(candidate, request,
                                        stream=require_stream)
                # Bound before the call so the refusal path below can attach the
                # row when the attempt itself raised instead of returning one.
                account: ModelCallAccount | None = None
                try:
                    response, chunks, account = self._attempt(
                        candidate, request, call, attempt,
                        stream=require_stream)
                except TransientProviderError as exc:
                    notes.append(_note(candidate, attempt, exc))
                    last_transport = exc
                    if attempt < attempts_per_candidate:
                        self._backoff(attempt)
                        continue
                    break
                except PermanentProviderError as exc:
                    notes.append(_note(candidate, attempt, exc))
                    last_transport = exc
                    break
                except _Refusal as refusal:
                    if not refusal.retryable or refusal.code in TERMINAL_REFUSALS:
                        raise
                    if refusal.account is None and account is not None:
                        refusal.account = account
                    last_refusal = refusal
                    if attempt < attempts_per_candidate:
                        self._backoff(attempt)
                        continue
                    break
                try:
                    return self._shape_result(candidate, request, response,
                                              chunks, account,
                                              require_stream=require_stream)
                except _Refusal as refusal:
                    if not refusal.retryable or refusal.code in TERMINAL_REFUSALS:
                        if refusal.account is None:
                            refusal.account = account
                        raise
                    if refusal.account is None and account is not None:
                        refusal.account = account
                    last_refusal = refusal
                    if attempt < attempts_per_candidate:
                        self._backoff(attempt)
                        continue
                    break
        if last_refusal is not None:
            raise last_refusal
        raise ProviderUnavailableError(
            "every candidate model in the fallback chain failed",
            hazard_class="UNAVAILABLE", recordable=False,
            notes=tuple(notes)) from last_transport

    def _attempt(
        self, candidate: _Candidate, request: ModelRequest, call: ModelCall,
        attempt: int, *, stream: bool,
    ) -> tuple[ModelResponse, tuple[ProviderChunk, ...], ModelCallAccount]:
        """One provider attempt, accounted exactly once whichever way it exits."""
        normalized = normalized_model_call(call)
        digest = hashlib.sha256(_canonical_bytes(normalized)).hexdigest()
        # Counted *before* the call so that a call which reaches a provider and
        # then loses its ledger row is detectable (verify_accounting).
        self._provider_attempts += 1
        outcome = "OK"
        failure_class: str | None = None
        usage = TokenUsage()
        chunks: tuple[ProviderChunk, ...] = ()
        try:
            if stream:
                chunks = candidate.provider.stream(call)
                response = _response_from_chunks(chunks)
            else:
                response = candidate.provider.invoke(call)
                chunks = ()
            usage = response.usage
            return response, chunks, self._record(
                candidate=candidate, request=request, attempt=attempt,
                outcome=outcome, normalized=normalized, digest=digest,
                usage=usage, failure_class=None)
        except TransientProviderError as exc:
            failure_class = type(exc).__name__
            self._record(candidate=candidate, request=request, attempt=attempt,
                         outcome="TRANSIENT", normalized=normalized,
                         digest=digest, usage=usage,
                         failure_class=failure_class)
            raise
        except PermanentProviderError as exc:
            failure_class = type(exc).__name__
            self._record(candidate=candidate, request=request, attempt=attempt,
                         outcome="PERMANENT", normalized=normalized,
                         digest=digest, usage=usage,
                         failure_class=failure_class)
            raise

    def _shape_result(
        self, candidate: _Candidate, request: ModelRequest,
        response: ModelResponse, chunks: tuple[ProviderChunk, ...],
        account: ModelCallAccount, *, require_stream: bool,
    ) -> "ModelProposal | ModelStreamResult":
        proposal = self._proposal(candidate, request, response, account)
        if not require_stream:
            return proposal
        return ModelStreamResult(
            chunks=self._envelope_chunks(candidate, request, chunks, proposal),
            account=account)

    def _proposal(
        self, candidate: _Candidate, request: ModelRequest,
        response: ModelResponse, account: ModelCallAccount,
    ) -> ModelProposal:
        """Validate the raw response into a bounded, enveloped proposal."""
        contract = request.output_contract
        structured: Mapping[str, Any] = {}
        rationale_text = request.rationale
        if contract is not None:
            structured = self._validate_output(contract, response.text)
            if contract.rationale_field:
                raw_rationale = structured.get(contract.rationale_field)
                rationale_text = (raw_rationale
                                  if isinstance(raw_rationale, str) else "")
                if not rationale_text.strip():
                    raise _Refusal(
                        RATIONALE,
                        f"model output omitted the required rationale field "
                        f"{contract.rationale_field!r}",
                        retryable=True,
                        provider_id=candidate.provider_id,
                        model_id=candidate.model_id, account=account)
        tool_calls = self._translate_tool_calls(candidate, response)
        body = _canonical_bytes({
            "structured": structured,
            "rationale": rationale_text,
            "tool_calls": [
                {"tool_name": call.tool_name,
                 "arguments": dict(call.arguments)}
                for call in tool_calls
            ],
        })
        if len(body) > self._policy.max_proposal_bytes:
            if not self._policy.allow_artifact_overflow:
                raise _Refusal(
                    RATIONALE,
                    f"proposal is {len(body)} bytes, over the "
                    f"{self._policy.max_proposal_bytes}-byte cap, and artifact "
                    f"overflow is unavailable",
                    retryable=True,
                    provider_id=candidate.provider_id,
                    model_id=candidate.model_id, account=account)
            return ModelProposal(
                provider_id=candidate.provider_id,
                model_id=candidate.model_id,
                tier=candidate.tier,
                profile=request.profile,
                lease_generation=request.lease_generation,
                content=None,
                structured={},
                rationale=None,
                tool_calls=(),
                overflow=ModelArtifactOverflow(
                    body=body, size_bytes=len(body)),
                account=account)
        return ModelProposal(
            provider_id=candidate.provider_id,
            model_id=candidate.model_id,
            tier=candidate.tier,
            profile=request.profile,
            lease_generation=request.lease_generation,
            content=_envelope(response.text, origin="model.output",
                              ref=account.request_digest),
            structured=structured,
            rationale=_envelope(rationale_text, origin="model.rationale",
                                ref=account.request_digest),
            tool_calls=tool_calls,
            overflow=None,
            account=account)

    def _envelope_chunks(
        self, candidate: _Candidate, request: ModelRequest,
        chunks: tuple[ProviderChunk, ...], proposal: ModelProposal,
    ) -> tuple[ModelChunk, ...]:
        """Envelope a recorded stream. Text never leaves this function bare."""
        enveloped: list[ModelChunk] = []
        for index, chunk in enumerate(chunks):
            tool_calls: tuple[ToolCallRequest, ...] = ()
            if chunk.kind is ChunkKind.TOOL_CALL and chunk.tool_calls_raw:
                translated = self._translator.translate(
                    _envelope(chunk.tool_calls_raw, origin="model.stream.tool_calls",
                              ref=f"{proposal.account.request_digest if proposal.account else ''}#{index}"),
                    allowed_tools=self._tool_allowlist)
                if isinstance(translated, ModelRefusal):
                    raise _Refusal(translated.code, translated.detail,
                                   retryable=translated.code not in TERMINAL_REFUSALS,
                                   provider_id=candidate.provider_id,
                                   model_id=candidate.model_id)
                tool_calls = translated
            enveloped.append(ModelChunk(
                kind=chunk.kind,
                text=(_envelope(chunk.text, origin="model.stream.delta",
                                ref=f"{proposal.account.request_digest if proposal.account else ''}#{index}")
                      if chunk.text else None),
                usage=chunk.usage,
                tool_calls=tool_calls))
        return tuple(enveloped)

    def _validate_output(
        self, contract: OutputContract, text: str
    ) -> Mapping[str, Any]:
        """Validate model output against the contract (fail-closed).

        Unknown keys and type violations are `MALFORMED_PAYLOAD` and retryable —
        a model that emits junk may yet answer correctly on a second attempt.
        A decision-shaped key is `PROPOSAL` and terminal: that is a category
        error, not a formatting one. A kind outside the injected allowlist is
        `ROLE` and terminal.
        """
        if not text.strip():
            raise _Refusal(MALFORMED_PAYLOAD,
                           "model returned no output for a structured contract",
                           retryable=True)
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            raise _Refusal(MALFORMED_PAYLOAD,
                           "model output is not valid JSON",
                           retryable=True) from None
        if not isinstance(parsed, dict):
            raise _Refusal(MALFORMED_PAYLOAD,
                           "model output must be a JSON object",
                           retryable=True)
        decision_keys = sorted(set(parsed) & DECISION_SHAPED_KEYS)
        if decision_keys:
            raise _Refusal(
                PROPOSAL,
                f"model output carried decision-shaped key(s) {decision_keys} — "
                f"model output is never an authority, whatever was asked")
        declared = {spec.name: spec for spec in contract.fields}
        unknown = sorted(set(parsed) - set(declared))
        if unknown:
            raise _Refusal(
                MALFORMED_PAYLOAD,
                f"model output carried unknown key(s) {unknown} for contract "
                f"{contract.name!r}", retryable=True)
        for name, spec in declared.items():
            if name not in parsed:
                if spec.required:
                    raise _Refusal(
                        MALFORMED_PAYLOAD,
                        f"model output omitted required field {name!r} for "
                        f"contract {contract.name!r}", retryable=True)
                continue
            value = parsed[name]
            if not _FIELD_TYPE_CHECKS[spec.type](value):
                raise _Refusal(
                    MALFORMED_PAYLOAD,
                    f"model output field {name!r} is not of declared type "
                    f"{spec.type!r}", retryable=True)
            if spec.allowed_values and value not in spec.allowed_values:
                raise _Refusal(
                    MALFORMED_PAYLOAD,
                    f"model output field {name!r} is outside its declared "
                    f"values", retryable=True)
        if contract.kind_field:
            proposed = parsed.get(contract.kind_field)
            if not isinstance(proposed, str) or proposed not in self._proposable_kinds:
                # A partition breach, not a formatting slip: the model is not
                # allowed to propose this whatever the contract said.
                raise _Refusal(
                    ROLE,
                    f"model proposed kind {proposed!r}, outside the injected "
                    f"proposable allowlist")
        return parsed

    def _translate_tool_calls(
        self, candidate: _Candidate, response: ModelResponse
    ) -> tuple[ToolCallRequest, ...]:
        """Translate the provider's tool-call blob into neutral proposals.

        The plane translates and stops: it has no transport, no capability
        registry and no way to execute anything a model asked for.
        """
        if not response.tool_calls_raw:
            return ()
        translated = self._translator.translate(
            _envelope(response.tool_calls_raw, origin="model.tool_calls",
                      ref=response.finish_reason),
            allowed_tools=self._tool_allowlist)
        if isinstance(translated, ModelRefusal):
            raise _Refusal(
                translated.code, translated.detail,
                retryable=(translated.code not in TERMINAL_REFUSALS),
                provider_id=candidate.provider_id, model_id=candidate.model_id)
        return translated

    # ── accounting + backoff ──

    def _record(
        self, *, candidate: _Candidate, request: ModelRequest, attempt: int,
        outcome: str, normalized: Mapping[str, Any], digest: str,
        usage: TokenUsage, failure_class: str | None,
        refusal_code: str | None = None,
    ) -> ModelCallAccount:
        row = ModelCallAccount(
            sequence=len(self._ledger),
            tier=candidate.tier,
            profile=request.profile,
            provider_id=candidate.provider_id,
            model_id=candidate.model_id,
            attempt=attempt,
            outcome=outcome,
            lease_generation=request.lease_generation,
            request_digest=digest,
            normalized_request=dict(normalized),
            retrieved_at=self._clock.now_utc(),
            usage=usage,
            context_tokens=usage.input_tokens or self._estimate_context_tokens(request),
            refusal_code=refusal_code,
            failure_class=failure_class,
            price_usd=_price_of(candidate.profile, usage))
        self._ledger.append(row)
        return row

    def _refuse(self, request: ModelRequest, refusal: _Refusal) -> ModelRefusal:
        """Convert a `_Refusal` signal into refusal-as-data, accounted.

        A refusal that never reached a provider still lands a row (attempt 0):
        "we declined to call a model" is a decision about the model plane and
        belongs in its ledger.
        """
        account = refusal.account
        if account is None:
            account = ModelCallAccount(
                sequence=len(self._ledger),
                tier=request.tier,
                profile=request.profile,
                provider_id=refusal.provider_id,
                model_id=refusal.model_id,
                attempt=0,
                outcome="REFUSED",
                lease_generation=request.lease_generation,
                request_digest="",
                normalized_request={},
                retrieved_at=self._clock.now_utc(),
                usage=TokenUsage(),
                context_tokens=0,
                refusal_code=refusal.code,
                failure_class=None,
                price_usd=None)
            self._ledger.append(account)
        return ModelRefusal(
            code=refusal.code,
            detail=refusal.detail,
            tier=request.tier,
            provider_id=refusal.provider_id or account.provider_id,
            model_id=refusal.model_id or account.model_id,
            account=account)

    def _backoff(self, attempt: int) -> None:
        """Jittered exponential backoff, mirroring `providers/paginate.py`.

        The jitter source is injectable so tests stay deterministic; `attempt` is
        1-based, making the first delay `base × 2`.
        """
        policy = self._policy.retry_policy
        base = getattr(policy, "base_delay_seconds", 1.0)
        max_delay = getattr(policy, "max_delay_seconds", 30.0)
        delay = min(max_delay, base * (2 ** attempt))
        if getattr(policy, "jitter", True):
            delay *= self._jitter_source(0.5, 1.0)
        self._backoff_delays.append(delay)
        self._sleep(delay)

    def _assert_secret_free(self, value: object, *, where: str) -> None:
        """Fail closed if a live credential appears in `value`.

        The structural guarantee (no credential field exists on a call) plus the
        option-name guard should make this unreachable; it is here so that
        "should" is not what stands between a secret and a log.
        """
        if not self._secrets:
            return
        rendered = value if isinstance(value, str) else repr(value)
        for secret in self._secrets:
            if secret in rendered:
                raise ModelPlaneInvariantError(
                    f"a live credential appeared in {where} — refusing to emit "
                    f"or record it (the value is never named)",
                    hazard_class="SECRET_LEAK", recordable=False)

    def _resolve_secrets(self) -> tuple[str, ...]:
        if self._credentials is None:
            return ()
        found: list[str] = []
        for provider_id in sorted(self._providers):
            credential = self._credentials.resolve(provider_id)
            if credential is None:
                continue
            value = credential.reveal()
            if value:
                found.append(value)
        return tuple(found)


def _contract_mapping(contract: OutputContract | None) -> dict[str, Any] | None:
    if contract is None:
        return None
    return {
        "name": contract.name,
        "fields": [
            {"name": spec.name, "type": spec.type, "required": spec.required,
             "allowed_values": sorted(spec.allowed_values)}
            for spec in contract.fields
        ],
        "kind_field": contract.kind_field,
        "rationale_field": contract.rationale_field,
        "allows_decision": contract.allows_decision,
    }


def _envelope(text: str, *, origin: str, ref: str) -> UntrustedContent:
    """Wrap model bytes in the untrusted-content envelope (§2.1 Outputs).

    The single place model text becomes a Hermes-visible value, so the envelope
    cannot be forgotten at one call site and remembered at another.
    """
    return UntrustedContent(text=text, origin=origin, ref=ref)


def _price_of(profile: ModelProfile, usage: TokenUsage) -> float | None:
    """Model cost for one call, or None when the model declares no pricing.

    None is deliberate rather than 0.0: an unpriced call is *unknown* cost, and
    the `evaluation.py` discipline is that UNKNOWN is never silently treated as a
    value.
    """
    if profile.input_cost_per_1k_tokens <= 0 and profile.output_cost_per_1k_tokens <= 0:
        return None
    return round(
        usage.input_tokens / 1000.0 * profile.input_cost_per_1k_tokens
        + usage.output_tokens / 1000.0 * profile.output_cost_per_1k_tokens, 9)


def _note(candidate: _Candidate, attempt: int, exc: ProviderError) -> str:
    return (f"{candidate.provider_id}/{candidate.model_id} "
            f"(tier {candidate.tier}) attempt {attempt}: "
            f"{type(exc).__name__}")


def _default_sleep(clock: Any) -> Callable[[float], None]:
    """Prefer the clock's own sleep (the provider-plane convention), else fall
    back to `time.sleep` so backoff is real outside tests."""
    sleep = getattr(clock, "sleep", None)
    if sleep is not None:
        return cast(Callable[[float], None], sleep)
    return time.sleep
