"""Capability plane — closed schemas for Tool / Capability / ToolSet / Observation.

`ARCHITECTURE_DELTA.md` §2.2 is the contract. This module holds only *declared
shapes*: a `Tool` is what may execute, a `Capability` is what a caller may name, a
`ToolSet` is a named composition (the B-3 slot), and an `Observation` is the only
successful output.

The plane is a port, not an authority
-------------------------------------
Three rules are structural here rather than policed later:

1. **No ambient authority.** Nothing in this plane may be reached without an
   explicit `ToolGrant`. There is no default grant, no wildcard, and no
   "trusted caller": `CapabilityRegistry.enumerate(grant=None)` returns an empty
   set, and the invoker refuses before it evaluates anything else (§6 below).
2. **Nothing here writes durable state.** `Observation.artifacts` holds *handles*
   the Orchestration API may dereference — this module authors no identity and
   holds no connection. A `Tool` that declares `mutating=True` is refused at the
   authority step, because admission of a mutation belongs to the Orchestration
   API and never to a plane (§2.2 `ROLE`: "a capability attempting to author
   state").
3. **Sandboxed execution is a capability, not an authority.** A sandboxed tool
   is granted, gated and observed exactly like any other; it never gets to skip
   the pipeline because it happens to run code.

Refusal codes — and where each one actually lives
------------------------------------------------
§2.2 *Errors* names the codes this plane may emit. They are the existing gateway
vocabulary; this plane introduces none. One correction to the delta's citation is
recorded here because it is load-bearing for anyone auditing the set:

- **Declared as module constants in `research/gateway.py:93-108`**: `ROLE`,
  `PROPOSAL`, `MALFORMED_PAYLOAD`, `EVIDENCE_REF`, `STALE`,
  `IDEMPOTENCY_CONFLICT`.
- **Emitted as string literals by `research/controller.py`** (the credentialed
  verdict surfaces): `LOCK` (≥7 sites) and `RATIONALE` (≥5 sites).

`docs/API.md:54` cites `gateway.py:93-108` as the home of all of them, but
`gateway.py` contains neither the string `"LOCK"` nor a `RATIONALE` code
constant. The set is unchanged and the meanings are the ones the surviving code
uses; only the citation is imprecise. `GATEWAY_DEFINED_CODES` and
`CONTROLLER_EMITTED_CODES` below state the measured provenance, and the R3 test
suite re-derives it from source so the claim cannot rot silently.

Import direction (§3.1)
-----------------------
`hermes.tools.*` + stdlib, plus `hermes.security.boundaries` for the
untrusted-observation envelope §2.2 *Outputs* requires (stdlib-only; imports
nothing from Hermes). Never `research`, never `core`, never `persistence`.

Naming note: `Tool` here is the *executable declaration*. `hermes.tools.models`
has a `ToolCallRequest`, which is a model's translated request for a tool — a
proposal, not a declaration, and deliberately a different type in a different
plane.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping

from hermes.security.boundaries import UntrustedContent

if TYPE_CHECKING:
    from hermes.tools.capabilities.envelope import InvocationEnvelope

__all__ = [
    "CAPABILITY_REFUSAL_CODES",
    "CONTROLLER_EMITTED_CODES",
    "EVIDENCE_REF",
    "GATEWAY_DEFINED_CODES",
    "IDEMPOTENCY_CONFLICT",
    "INPUT_TYPES",
    "LOCK",
    "MALFORMED_PAYLOAD",
    "MAX_ARGUMENT_BYTES",
    "PROPOSAL",
    "RATIONALE",
    "RISK_ORDER",
    "ROLE",
    "STALE",
    "Capability",
    "CapabilityKind",
    "CapabilityRefusal",
    "CapabilitySet",
    "FailureKind",
    "IdempotencyRecord",
    "InputField",
    "InvokeRequest",
    "Observation",
    "RiskLevel",
    "Tool",
    "ToolCallContext",
    "ToolGrant",
    "ToolResult",
    "ToolSet",
    "max_risk_for",
    "risk_at_most",
]

# ── refusal codes: the existing gateway vocabulary (§2.2 Errors) ──

ROLE = "ROLE"
LOCK = "LOCK"
PROPOSAL = "PROPOSAL"
MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"
EVIDENCE_REF = "EVIDENCE_REF"
RATIONALE = "RATIONALE"
STALE = "STALE"
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"

#: Codes `research/gateway.py:93-108` declares as named constants.
GATEWAY_DEFINED_CODES: frozenset[str] = frozenset({
    ROLE, PROPOSAL, MALFORMED_PAYLOAD, EVIDENCE_REF, STALE,
    IDEMPOTENCY_CONFLICT,
})

#: Codes `research/controller.py` emits as inline string literals (no constant
#: exists anywhere for them today).
CONTROLLER_EMITTED_CODES: frozenset[str] = frozenset({LOCK, RATIONALE})

#: The complete set this plane may emit. No member is invented here.
CAPABILITY_REFUSAL_CODES: frozenset[str] = (
    GATEWAY_DEFINED_CODES | CONTROLLER_EMITTED_CODES)

#: The event-payload cap (§3.3). Capability arguments are an event-payload-shaped
#: crossing, so they inherit the same bound.
MAX_ARGUMENT_BYTES = 4096

RISK_ORDER: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

#: Declared input types. Deliberately scalar-only (arrays of scalars allowed):
#: a capability argument set is a closed, flat, recordable structure, not a
#: nested document. Richer shapes belong to artifacts.
INPUT_TYPES: tuple[str, ...] = ("string", "integer", "number", "boolean", "array")


# ── enums ──


class RiskLevel(str, Enum):
    """Declared risk of a capability — what a grant must be willing to cover."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CapabilityKind(str, Enum):
    """What a capability *is* — a tool, or sandboxed execution.

    There is deliberately no COMPOSITE kind. Composition is the `ToolSet` (the
    B-3 slot), and a tool set is a *granting* structure with no executor: it
    decides which capabilities a grant opens and nothing else. That makes
    "composition cannot widen authority" true by construction, because there is
    no composed execution path that could reach a member the grant did not open.
    """

    TOOL = "TOOL"
    SANDBOX = "SANDBOX"


class FailureKind(str, Enum):
    """The execution-failure taxonomy (the Observation side).

    Distinct from the refusal codes above: a refusal means *the plane declined
    to act* (an authority or schema decision), while a failure means *the call
    was allowed and did not succeed*. Collapsing the two would make an
    unauthorized attempt indistinguishable from an outage.
    """

    TOOL_ERROR = "TOOL_ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    HAZARD = "HAZARD"
    RATE_LIMITED = "RATE_LIMITED"
    RATE_LIMIT_EXHAUSTED = "RATE_LIMIT_EXHAUSTED"
    SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    REDACTION_DENIED = "REDACTION_DENIED"


def risk_at_most(risk: str, ceiling: str) -> bool:
    """True when `risk` is no higher than `ceiling` (closed vocabulary)."""
    if risk not in RISK_ORDER or ceiling not in RISK_ORDER:
        return False  # fail closed on an unknown level
    return RISK_ORDER.index(risk) <= RISK_ORDER.index(ceiling)


def max_risk_for(levels: tuple[str, ...]) -> str:
    """The highest level in `levels` (empty → the lowest, fail-closed)."""
    known = [level for level in levels if level in RISK_ORDER]
    if not known:
        return RISK_ORDER[0]
    return max(known, key=RISK_ORDER.index)


# ── declared schemas ──


@dataclass(frozen=True, slots=True)
class InputField:
    """One declared input field of a tool.

    `max_bytes` bounds one field's recorded size (0 = unbounded);
    `allowed_values`, when set, is a closed value set; `pattern`, when set, is an
    anchored regular expression the value must match.
    """

    name: str
    type: str
    required: bool = True
    max_bytes: int = 0
    pattern: str = ""
    allowed_values: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Tool:
    """One executable unit — what may actually run.

    Every field here is a *declaration the plane enforces*, not documentation:
    `requires_approval` becomes a `PROPOSAL` refusal without a bound approval,
    `mutating` becomes a `ROLE` refusal (a plane never authors state),
    `network`/`filesystem_scope`/`process` are the sandbox boundary a
    sandbox-escape-shaped input is judged against, and `hazard_spec` names the
    declared hazard knowledge the hazard gate evaluates.
    """

    tool_id: str
    summary: str
    inputs: tuple[InputField, ...] = ()
    risk: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    mutating: bool = False
    network: bool = False
    filesystem_scope: str = ""
    process: bool = False
    timeout_seconds: float = 30.0
    hazard_spec: str = ""
    sandboxed: bool = False
    environment: str = ""  # e.g. a sandbox runner name; "" = in-process

    def input_field(self, name: str) -> InputField | None:
        for spec in self.inputs:
            if spec.name == name:
                return spec
        return None

    def accepts_no_side_effects(self) -> bool:
        """True when the declaration claims no external reach at all."""
        return not (self.network or self.filesystem_scope or self.process)


@dataclass(frozen=True, slots=True)
class Capability:
    """A named, addressable capability — what a caller may `invoke`.

    A `TOOL` capability addresses exactly one tool. A `SANDBOX` capability
    addresses sandboxed execution, which is a capability and never an authority.
    Either way a capability is a single address: it cannot stand in for several
    tools, so it cannot be used to route around the authority check for one of
    them.
    """

    capability_id: str
    tool_id: str
    summary: str = ""
    kind: CapabilityKind = CapabilityKind.TOOL
    requires_approval: bool = False
    risk: RiskLevel = RiskLevel.LOW

    def effective_risk(self, tool: "Tool | None") -> str:
        """The risk that applies: the tool's, floored by the capability's own.

        A capability may *raise* the risk of what it addresses; it can never
        lower it.
        """
        if tool is None:
            return str(self.risk.value)
        return max_risk_for((str(self.risk.value), str(tool.risk.value)))

    def needs_approval(self, tool: "Tool | None") -> bool:
        if self.requires_approval:
            return True
        return bool(tool is not None and tool.requires_approval)


@dataclass(frozen=True, slots=True)
class ToolSet:
    """A named composition of capabilities — the B-3 slot.

    Composition is declared data: a set names capabilities by id, and the
    registry resolves them. Nothing is imported, nothing is discovered at
    runtime, and a member that does not resolve fails the composition closed.
    """

    set_id: str
    capability_ids: tuple[str, ...]
    summary: str = ""
    version: str = "1"


@dataclass(frozen=True, slots=True)
class ToolGrant:
    """An explicit, non-ambient authority.

    Supplied by the Orchestration API, never invented by a caller and never
    defaulted. A grant names the profile it binds, the tool sets it opens, the
    risk ceiling it covers, and the capabilities that carry a bound operator
    approval. Anything not in here is denied.
    """

    grant_id: str
    profile: str
    tool_set_ids: frozenset[str] = frozenset()
    max_risk: str = RiskLevel.LOW.value
    approvals: frozenset[str] = frozenset()

    def opens(self, tool_set_id: str) -> bool:
        return tool_set_id in self.tool_set_ids


@dataclass(frozen=True, slots=True)
class CapabilitySet:
    """The discovery surface (§2.2 operation 1) — what a grant can reach.

    Empty when there is no grant: discovery is itself authority-scoped, so
    enumerating cannot advertise what a caller may not invoke.
    """

    capabilities: tuple[Capability, ...] = ()
    tool_sets: tuple[ToolSet, ...] = ()
    grant_id: str = ""

    def ids(self) -> tuple[str, ...]:
        return tuple(capability.capability_id for capability in self.capabilities)

    def contains(self, capability_id: str) -> bool:
        return capability_id in self.ids()


# ── call-side value types ──


@dataclass(frozen=True, slots=True)
class InvokeRequest:
    """A closed invocation request (§2.2 *Inputs*).

    There are no free-form kwargs. `idempotency_key` is required: every invoke
    carries one, so a retry is always distinguishable from a second act.
    `grant` is required for the call to be authorized at all — passing `None` is
    not "unrestricted", it is denial.
    """

    capability_id: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    lease_generation: str = ""
    profile: str = ""
    rationale: str = ""
    grant: ToolGrant | None = None
    deadline_seconds: float | None = None

    @classmethod
    def field_names(cls) -> frozenset[str]:
        return frozenset({
            "capability_id", "arguments", "idempotency_key", "lease_generation",
            "profile", "rationale", "grant", "deadline_seconds",
        })

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "InvokeRequest | CapabilityRefusal":
        """Build from a mapping, refusing unknown keys (closed schema).

        Returns a refusal rather than raising, so a malformed request is data at
        the boundary exactly like an authority decision is.
        """
        unknown = sorted(set(data) - cls.field_names())
        if unknown:
            return CapabilityRefusal(
                code=MALFORMED_PAYLOAD,
                detail=f"unknown request keys: {unknown}")
        return cls(
            capability_id=str(data.get("capability_id") or ""),
            arguments=dict(data.get("arguments") or {}),
            idempotency_key=str(data.get("idempotency_key") or ""),
            lease_generation=str(data.get("lease_generation") or ""),
            profile=str(data.get("profile") or ""),
            rationale=str(data.get("rationale") or ""),
            grant=data.get("grant"),
            deadline_seconds=data.get("deadline_seconds"))


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool implementation hands back — raw and untrusted.

    A tool returns text and artifact *handles*. It has no way to return a
    transcript, a grant, or an admission: the shape does not exist.
    """

    payload: str = ""
    artifacts: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolCallContext:
    """What a tool implementation is given — and the whole of what it is given.

    Carries the deadline and cancel token it must honour, the idempotency key it
    belongs to, and the scratch scope it may touch. It carries no connection, no
    repository, no grant and no authority: a tool cannot widen its own reach
    because there is no surface here to widen.
    """

    capability_id: str
    tool_id: str
    idempotency_key: str
    lease_generation: str
    profile: str
    deadline_monotonic: float
    scratch_dir: str = ""


@dataclass(frozen=True, slots=True)
class Observation:
    """The only successful output of the plane — untrusted, and not an authority.

    `payload` is envelope-wrapped (`UntrustedContent`), so an observation cannot
    reach a judgment surface as a bare string, and `artifacts` holds handles the
    Orchestration API may dereference at its own write boundary. Admission is
    explicitly not this plane's job: an observation is evidence-shaped input to a
    decision, never the decision.
    """

    capability_id: str
    status: str = "OK"  # "OK" | "FAILED"
    payload: UntrustedContent | None = None
    artifacts: tuple[str, ...] = ()
    failure: FailureKind | None = None
    detail: str = ""
    idempotency_key: str = ""
    replayed: bool = False
    envelope: InvocationEnvelope | None = None

    def ok(self) -> bool:
        return self.status == "OK"


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """One remembered invocation: the key, its request digest, its observation.

    Derived working state, held only by the injected ledger. Durable retention
    is the Orchestration API's business (the envelope is what gets journaled),
    which is what keeps this plane free of a store.
    """

    idempotency_key: str
    request_digest: str
    observation: Observation


@dataclass(frozen=True, slots=True)
class CapabilityRefusal:
    """Refusal-as-data: `{"rejected": True, "code", "detail"}` plus provenance.

    `code` is always a member of `CAPABILITY_REFUSAL_CODES`, and the envelope is
    attached, so a *refused* attempt is as reconstructible as a successful one.
    """

    code: str
    detail: str
    capability_id: str = ""
    profile: str = ""
    envelope: InvocationEnvelope | None = None

    def as_dict(self) -> dict[str, Any]:
        """The shape §2.4 gives gateway refusals, so a plane refusal and a spine
        refusal are recognisably the same discipline."""
        return {"rejected": True, "code": self.code, "detail": self.detail}
