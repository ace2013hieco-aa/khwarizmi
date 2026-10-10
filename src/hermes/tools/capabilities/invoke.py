"""Capability plane — `invoke()`: the one gated execution path (§2.2 operation 2).

The pipeline is fixed and its order is load-bearing:

```text
closed schema → lease → resolve capability → resolve tool
  → AUTHORITY (default-deny)          <- before anything that could execute
  → declared-argument validation
  → credential refusal (names, then values)  <- before anything is recorded
  → record inputs (redacted)
  → idempotency (replay or conflict)  <- before any side effect
  → sandbox boundary gate             <- escape-shaped input refuses here
  → sandbox availability
  → hazard gate                       <- declared knowledge, reused vocabulary
  → rate gate                         <- atomic decision + cause
  → execute (cancel + deadline)       <- only now does anything run
  → handle + secret checks on the result
  → envelope + observation
```

Three properties are the point of that ordering:

1. **Permission precedes every execution.** `_authorize` runs before argument
   validation, before the sandbox gate, before the hazard and rate gates, and
   long before the tool is called. An unauthorized attempt therefore consumes no
   rate token, writes no idempotency record, runs no hazard evaluation, and — a
   deliberate minimization — records no arguments, so probing does not get an
   unauthorized payload echoed into a journal.
2. **Nothing runs before idempotency is consulted.** A replayed call returns the
   remembered observation without re-executing, without a rate token, and without
   a second artifact.
3. **No ambient authority.** There is no default grant, no wildcard, no trusted
   profile, and no `sandbox` escape hatch: a `SANDBOX` capability is granted and
   gated exactly like any other (§2.2: sandboxed execution is a capability, not
   an authority). `request.grant=None` is denial, not "unrestricted".

What this plane will not do
---------------------------
It will not author state. `Tool.mutating` is refused `ROLE` at the authority
step: a mutating effect is an *intent* and its admission belongs to the
Orchestration API (§2.2: "a capability attempting to author state"). The plane
also holds no connection, no transaction and no store — the idempotency ledger is
injected and documented as derived working state, so the plane has nothing to
write with.

Two refusal codes are deliberately **not** emitted here
-------------------------------------------------------
`EVIDENCE_REF` and `STALE` are in the §2.2 vocabulary but are the Orchestration
API's to raise: deciding that an artifact handle "does not dereference in-project"
requires the artifact store, and a supersession/chain-head judgement requires the
repository. This plane has neither, so it must not assert either. A malformed
handle *shape* is caught here as a `TOOL_ERROR` (the plane can see that much);
whether the handle resolves is the write boundary's verdict. `EMITTED_REFUSAL_CODES`
and `UNEMITTED_REFUSAL_CODES` state the split, and the test suite proves it.

Hazard gate
-----------
`§2.2` cites `tools/providers/hazards.py`, and the honest reuse is partial: the
provider evaluator is HTTP-shaped (status codes, throttle signatures, cursor
rules) and a capability call is not an HTTP response, so pretending otherwise
would be a fiction. What genuinely generalizes is reused directly —
`resolve_field_path` for dotted-path resolution and the frozen `HAZARD_CLASSES`
vocabulary — and the *recordable vs advisory* split is mirrored from
`HazardVerdict.recordable`, so the two evaluators classify alike without sharing
a shape they do not share.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from hermes.security.boundaries import UntrustedContent
from hermes.tools.capabilities.envelope import (
    EnvelopeAuthority,
    EnvelopeInputs,
    EnvelopeObservation,
    InvocationEnvelope,
    credential_class_names,
    digest_of,
    record_value,
    redact_arguments,
    redaction_gaps,
    undeclared_names,
)
from hermes.tools.capabilities.registry import CapabilityRegistry
from hermes.tools.capabilities.types import (
    CAPABILITY_REFUSAL_CODES,
    EVIDENCE_REF,
    IDEMPOTENCY_CONFLICT,
    LOCK,
    MALFORMED_PAYLOAD,
    MAX_ARGUMENT_BYTES,
    PROPOSAL,
    RATIONALE,
    ROLE,
    STALE,
    Capability,
    CapabilityKind,
    CapabilityRefusal,
    FailureKind,
    IdempotencyRecord,
    InputField,
    InvokeRequest,
    Observation,
    Tool,
    ToolCallContext,
    ToolResult,
    risk_at_most,
)
from hermes.tools.providers.hazards import HAZARD_CLASSES, resolve_field_path
from hermes.tools.research_sources import ProviderValidationError

__all__ = [
    "ADVISORY_HAZARD_CLASSES",
    "EMITTED_REFUSAL_CODES",
    "HANDLE_PATTERN",
    "UNEMITTED_REFUSAL_CODES",
    "CancelToken",
    "CapabilityHazardSpec",
    "CapabilityInvoker",
    "HazardMarkerSpec",
    "IdempotencyLedger",
    "InMemoryIdempotencyLedger",
    "NeverCancelled",
    "RateLimitGate",
    "ToolExecutor",
]

#: An artifact *handle* the plane may carry: `<kind>/<name>`, conservative
#: charset, never absolute. The plane carries handles; it mints no identity and
#: resolves nothing — dereference is the Orchestration API's write-boundary job.
HANDLE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z")

#: Hazard classes that inform rather than stop a call — the same split
#: `HazardVerdict.recordable=False` draws in the provider evaluator.
ADVISORY_HAZARD_CLASSES: frozenset[str] = frozenset({
    "NONE", "VALID_NEGATIVE", "NO_FULL_TEXT", "INJECTION_SUSPECT",
})

#: Codes this plane actually emits.
EMITTED_REFUSAL_CODES: frozenset[str] = frozenset({
    ROLE, LOCK, PROPOSAL, MALFORMED_PAYLOAD, RATIONALE, IDEMPOTENCY_CONFLICT,
})

#: Codes in the §2.2 vocabulary that belong to the Orchestration API's write
#: boundary, with the reason: the plane has no artifact store and no repository,
#: so it cannot honestly decide either verdict.
UNEMITTED_REFUSAL_CODES: frozenset[str] = frozenset({EVIDENCE_REF, STALE})

_PATH_TOKENS = re.compile(r"""[^\s,;:="']*[/\\][^\s,;:="']*""")
_PROCESS_CONSTRUCTS = re.compile(
    r"(;\s*|&&|\|\||\$\(|`|subprocess|\bos\.system\b|popen|\bexec\s*\()")
_NETWORK_CONSTRUCTS = re.compile(
    r"(https?://|\bsocket\b|\bcurl\b|\bwget\b|\bnc\b|\bftp://)")

_TYPE_CHECKS: dict[str, Any] = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: (isinstance(value, int)
                              and not isinstance(value, bool)),
    "number": lambda value: (isinstance(value, (int, float))
                             and not isinstance(value, bool)),
    "boolean": lambda value: isinstance(value, bool),
    "array": lambda value: (isinstance(value, (list, tuple))
                            and all(isinstance(item, (str, int, float, bool))
                                    for item in value)),
}


# ── ports ──


class ToolExecutor(Protocol):
    """A tool implementation.

    Given validated, permissioned arguments and a call context, it returns raw
    text and artifact handles. It receives no connection, no grant and no
    authority, so it cannot widen its own reach — there is no surface here with
    which to try.
    """

    def __call__(self, arguments: Mapping[str, Any],
                 context: ToolCallContext) -> ToolResult: ...


class CancelToken(Protocol):
    """Cooperative cancellation. Checked before and after execution."""

    def is_cancelled(self) -> bool: ...


class NeverCancelled:
    """The default token: nothing cancels unless a caller wires a real one."""

    def is_cancelled(self) -> bool:
        return False


class RateLimitGate(Protocol):
    """Admission control, structurally matching `providers.ratelimit`.

    Deliberately the same `(granted, reason)`-atomic shape as
    `ProviderRateLimiter` so that the real limiter can be injected unchanged
    (keyed by capability id); duplicating the token-bucket logic in this plane
    would be a second rate authority.
    """

    def acquire(self, capability_id: str) -> tuple[bool, str]: ...
    def release(self, capability_id: str) -> None: ...


class IdempotencyLedger(Protocol):
    """Remembers one settled invocation per key.

    Injected, and derived working state only: durable retention of the record is
    the Orchestration API's business (the envelope is what gets journaled), which
    is what keeps this plane free of a store.
    """

    def get(self, idempotency_key: str) -> IdempotencyRecord | None: ...
    def put(self, record: IdempotencyRecord) -> None: ...


class InMemoryIdempotencyLedger:
    """The default ledger: process-local, no durability, no connection.

    Only successful observations are remembered. A failed call is *not* settled,
    so retrying the same key re-attempts rather than replaying a failure — which
    is the behaviour a transient timeout needs.
    """

    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}

    def get(self, idempotency_key: str) -> IdempotencyRecord | None:
        return self._records.get(idempotency_key)

    def put(self, record: IdempotencyRecord) -> None:
        self._records[record.idempotency_key] = record

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._records))


# ── declared hazard knowledge (input-shaped) ──


@dataclass(frozen=True, slots=True)
class HazardMarkerSpec:
    """One declared input predicate: `equals` or `pattern` (at least one).

    `failure_class` is a `HAZARD_CLASSES` member; empty means the marker is
    advisory (`INJECTION_SUSPECT`).
    """

    field_path: str
    equals: str = ""
    pattern: str = ""
    failure_class: str = ""


@dataclass(frozen=True, slots=True)
class CapabilityHazardSpec:
    """Versioned hazard knowledge for one tool, declared as data.

    Deliberately not the provider `ProviderHazardSpec`: that shape carries
    status codes, throttle signatures and cursor rules that a capability call has
    no equivalent of. This carries what a capability call genuinely has —
    declared inputs to judge.
    """

    spec_id: str
    version: str
    markers: tuple[HazardMarkerSpec, ...] = ()


class _Refusal(Exception):
    """Internal control-flow signal, converted to `CapabilityRefusal` data at the
    public boundary. Private: never part of the port's contract, never escapes."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class _Trace:
    """Mutable recording context — internal only, never returned.

    Accumulates what is known so that every exit path can build a complete
    envelope, including the refusals that happen before the capability is
    resolved.
    """

    capability_id: str = ""
    tool_id: str = ""
    profile: str = ""
    lease_generation: str = ""
    why: str = ""
    idempotency_key: str = ""
    authority: EnvelopeAuthority = field(default_factory=EnvelopeAuthority)
    inputs: EnvelopeInputs = field(default_factory=EnvelopeInputs)
    hazard_class: str = ""
    hazard_reason: str = ""
    rate_decision: str = ""
    artifacts: tuple[str, ...] = ()
    observation_digest: str = ""
    observation_size: int = 0
    request_digest: str = ""


class CapabilityInvoker:
    """The one gated execution path for capabilities (§2.2 operation 2).

    Holds declarations (registry), implementations, and the injected ports. Holds
    no store, no connection, no transaction, and no authority of its own.
    """

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        implementations: Mapping[str, ToolExecutor] | None = None,
        clock: Any,
        limiter: RateLimitGate | None = None,
        ledger: IdempotencyLedger | None = None,
        cancel: CancelToken | None = None,
        hazard_specs: Mapping[str, CapabilityHazardSpec] | None = None,
        sandbox_enabled: bool = False,
        secrets: tuple[str, ...] = (),
    ) -> None:
        self._registry = registry
        self._implementations: dict[str, ToolExecutor] = dict(implementations or {})
        self._clock = clock
        self._limiter = limiter
        self._ledger: IdempotencyLedger = (ledger if ledger is not None
                                          else InMemoryIdempotencyLedger())
        self._cancel: CancelToken = cancel if cancel is not None else NeverCancelled()
        self._hazard_specs = dict(hazard_specs or {})
        self._sandbox_enabled = sandbox_enabled
        self._secrets = tuple(secret for secret in secrets if secret)
        # Fail-closed wiring: an implementation for something undeclared is a
        # composition bug, not something to ignore.
        for tool_id, spec in self._hazard_specs.items():
            if tool_id and not spec.spec_id:
                raise ProviderValidationError(
                    f"hazard spec registered for {tool_id!r} declares no spec_id",
                    hazard_class="MALFORMED_REQUEST", recordable=False)

    # ── public surface ──

    def invoke(self, request: InvokeRequest) -> Observation | CapabilityRefusal:
        """Run one bounded capability call: an observation, or a refusal."""
        trace = _Trace(
            capability_id=request.capability_id,
            profile=request.profile,
            lease_generation=request.lease_generation,
            why=request.rationale,
            idempotency_key=request.idempotency_key,
        )
        try:
            self._require_schema(request)
            self._require_lease(request)
            capability = self._resolve_capability(request.capability_id)
            trace.tool_id = capability.tool_id
            tool = self._resolve_tool(capability)
            # 1. AUTHORITY — before anything that could execute.
            self._authorize(request, capability, tool, trace)
            # 2. Declared arguments, then credential refusal (names, then
            #    values) — and only *then* recording. Nothing is recorded
            #    before the live-credential scan, so a secret smuggled as a
            #    value under a benign name cannot land in the envelope either.
            arguments = self._declared_arguments(tool, request)
            self._require_credential_free_inputs(tool, request)
            self._require_secret_free_inputs(arguments)
            self._record_inputs(trace, arguments)
            # 3. Idempotency — before any side effect.
            replayed = self._replayed_or_conflict(request, arguments, trace)
            if replayed is not None:
                return replayed
            # 4. Sandbox boundary, then availability.
            self._sandbox_gate(tool, arguments)
            if capability.kind is CapabilityKind.SANDBOX and not self._sandbox_enabled:
                return self._failed(
                    trace, FailureKind.SANDBOX_UNAVAILABLE,
                    "sandboxed execution is not configured (the sandbox is a "
                    "capability that is unavailable, never an authority that is "
                    "bypassed)")
            # 5. Hazard gate.
            hazard_class, hazard_reason, hazard_failure = self._hazard_gate(
                tool, arguments)
            trace.hazard_class = hazard_class
            trace.hazard_reason = hazard_reason
            if hazard_failure is not None:
                return self._failed(trace, hazard_failure, hazard_reason)
            # 6. Rate gate + execution + release.
            return self._gated_execution(trace, request, capability, tool,
                                         arguments)
        except _Refusal as refusal:
            return self._refuse(trace, refusal.code, refusal.detail)

    def invoke_from_mapping(
        self, data: Mapping[str, Any]
    ) -> Observation | CapabilityRefusal:
        """Closed-schema entry point: a mapping with unknown keys refuses."""
        built = InvokeRequest.from_mapping(data)
        if isinstance(built, CapabilityRefusal):
            trace = _Trace(
                capability_id=str(data.get("capability_id") or ""),
                profile=str(data.get("profile") or ""),
                lease_generation=str(data.get("lease_generation") or ""),
                why=str(data.get("rationale") or ""),
                idempotency_key=str(data.get("idempotency_key") or ""))
            return self._refuse(trace, built.code, built.detail)
        return self.invoke(built)

    # ── guards ──

    def _require_schema(self, request: InvokeRequest) -> None:
        if not request.capability_id:
            raise _Refusal(MALFORMED_PAYLOAD, "capability_id is required")
        if not request.profile:
            raise _Refusal(MALFORMED_PAYLOAD,
                           "profile is required — a call with no actor is not "
                           "attributable")
        if not request.idempotency_key:
            raise _Refusal(MALFORMED_PAYLOAD,
                           "an idempotency_key is required on every invoke")
        size = len(json.dumps(dict(request.arguments), default=str,
                              sort_keys=True).encode("utf-8"))
        if size > MAX_ARGUMENT_BYTES:
            raise _Refusal(RATIONALE,
                           f"arguments are {size} bytes, over the "
                           f"{MAX_ARGUMENT_BYTES}-byte cap")

    def _require_lease(self, request: InvokeRequest) -> None:
        """`LOCK` — invoked without a held lease (attribution tag absent)."""
        if not request.lease_generation.strip():
            raise _Refusal(LOCK,
                           "invoked without a lease-generation tag — the call "
                           "could not be attributed to a lease generation")

    def _resolve_capability(self, capability_id: str) -> Capability:
        capability = self._registry.capability(capability_id)
        if capability is None:
            raise _Refusal(MALFORMED_PAYLOAD,
                           f"unknown capability {capability_id!r}")
        return capability

    def _resolve_tool(self, capability: Capability) -> Tool:
        tool = self._registry.tool(capability.tool_id)
        if tool is None:
            raise _Refusal(MALFORMED_PAYLOAD,
                           f"capability {capability.capability_id!r} addresses "
                           f"unregistered tool {capability.tool_id!r}")
        return tool

    def _authority(self, request: InvokeRequest, *, decision: str,
                   refusal_code: str = "", approved: bool = False
                   ) -> EnvelopeAuthority:
        grant = request.grant
        return EnvelopeAuthority(
            grant_id=grant.grant_id if grant is not None else "",
            profile=grant.profile if grant is not None else "",
            tool_sets=(tuple(sorted(grant.tool_set_ids))
                       if grant is not None else ()),
            risk_ceiling=grant.max_risk if grant is not None else "",
            approved=approved,
            decision=decision,
            refusal_code=refusal_code)

    def _authorize(self, request: InvokeRequest, capability: Capability,
                   tool: Tool, trace: _Trace) -> None:
        """The permission check — default-deny, and first.

        Every denial records the authority section before raising, so a refusal
        is reconstructible rather than an unexplained `rejected: true`.
        """
        grant = request.grant
        if grant is None:
            trace.authority = self._authority(request, decision="REFUSED",
                                              refusal_code=ROLE)
            raise _Refusal(ROLE,
                           "no grant — this plane has no ambient authority and "
                           "denies by default")
        approved = capability.capability_id in grant.approvals
        if grant.profile != request.profile:
            trace.authority = self._authority(request, decision="REFUSED",
                                              refusal_code=ROLE, approved=approved)
            raise _Refusal(ROLE,
                           f"grant {grant.grant_id!r} binds profile "
                           f"{grant.profile!r}, not {request.profile!r}")
        open_sets: list[str] = []
        for set_id in self._registry.tool_set_ids():
            if set_id not in grant.tool_set_ids:
                continue
            tool_set = self._registry.tool_set(set_id)
            if tool_set is None:
                continue
            if capability.capability_id in tool_set.capability_ids:
                open_sets.append(set_id)
        if not open_sets:
            trace.authority = self._authority(request, decision="REFUSED",
                                              refusal_code=ROLE, approved=approved)
            raise _Refusal(ROLE,
                           f"capability {capability.capability_id!r} is not "
                           f"reachable through any tool set grant "
                           f"{grant.grant_id!r} opens")
        if not risk_at_most(capability.effective_risk(tool), grant.max_risk):
            trace.authority = self._authority(request, decision="REFUSED",
                                              refusal_code=ROLE, approved=approved)
            raise _Refusal(ROLE,
                           f"capability {capability.capability_id!r} is "
                           f"{capability.effective_risk(tool)} risk, above grant "
                           f"{grant.grant_id!r}'s ceiling {grant.max_risk!r}")
        if capability.needs_approval(tool) and not approved:
            trace.authority = self._authority(request, decision="REFUSED",
                                              refusal_code=PROPOSAL)
            raise _Refusal(PROPOSAL,
                           f"capability {capability.capability_id!r} requires a "
                           f"bound operator approval and grant "
                           f"{grant.grant_id!r} carries none for it")
        if tool.mutating:
            trace.authority = self._authority(request, decision="REFUSED",
                                              refusal_code=ROLE, approved=approved)
            raise _Refusal(ROLE,
                           f"tool {tool.tool_id!r} declares a mutating effect — a "
                           f"capability never authors state; the effect must be "
                           f"proposed as an intent and admitted by the "
                           f"Orchestration API")
        if not tool.accepts_no_side_effects() and not tool.sandboxed:
            trace.authority = self._authority(request, decision="REFUSED",
                                              refusal_code=ROLE, approved=approved)
            raise _Refusal(ROLE,
                           f"tool {tool.tool_id!r} declares network/filesystem/"
                           f"process reach without declaring sandboxed=True")
        trace.authority = self._authority(request, decision="GRANTED",
                                          approved=approved)
        trace.why = request.rationale

    def _declared_arguments(self, tool: Tool,
                            request: InvokeRequest) -> dict[str, Any]:
        """Validate arguments against the declared schema (closed, typed).

        Validation only: the recordable form is built by `_record_inputs` once
        the credential checks have passed, so a refusal cannot be the thing
        that records a secret.
        """
        declared = [spec.name for spec in tool.inputs]
        unknown = undeclared_names(request.arguments, declared)
        if unknown:
            raise _Refusal(MALFORMED_PAYLOAD,
                           f"undeclared argument(s) {list(unknown)} for tool "
                           f"{tool.tool_id!r} — the input schema is closed")
        values: dict[str, Any] = {}
        for spec in tool.inputs:
            if spec.name not in request.arguments:
                if spec.required:
                    raise _Refusal(MALFORMED_PAYLOAD,
                                   f"missing required argument {spec.name!r} for "
                                   f"tool {tool.tool_id!r}")
                continue
            value = request.arguments[spec.name]
            self._check_field(spec, value, tool)
            values[spec.name] = value
        return values

    def _record_inputs(self, trace: _Trace,
                       arguments: Mapping[str, Any]) -> None:
        """The redacted, recordable form of validated arguments.

        Deliberately a separate step from validation: recording is deferred
        until the credential checks have passed, so a refusal envelope is
        complete *without* carrying a secret value.
        """
        fields = redact_arguments(arguments)
        trace.inputs = EnvelopeInputs(
            fields=fields,
            digest=digest_of(fields),
            size_bytes=len(json.dumps(fields, sort_keys=True).encode("utf-8")),
            redaction_gaps=redaction_gaps(arguments))

    def _check_field(self, spec: InputField, value: Any, tool: Tool) -> None:
        if not _TYPE_CHECKS[spec.type](value):
            raise _Refusal(MALFORMED_PAYLOAD,
                           f"argument {spec.name!r} is not of declared type "
                           f"{spec.type!r} for tool {tool.tool_id!r}")
        text = record_value(value)
        if spec.allowed_values and text not in spec.allowed_values:
            raise _Refusal(MALFORMED_PAYLOAD,
                           f"argument {spec.name!r} is outside its declared "
                           f"values")
        if spec.pattern and re.search(spec.pattern, text) is None:
            raise _Refusal(MALFORMED_PAYLOAD,
                           f"argument {spec.name!r} does not match its declared "
                           f"pattern")
        if spec.max_bytes and len(text.encode("utf-8")) > spec.max_bytes:
            raise _Refusal(RATIONALE,
                           f"argument {spec.name!r} is "
                           f"{len(text.encode('utf-8'))} bytes, over its "
                           f"declared {spec.max_bytes}-byte bound")

    def _require_credential_free_inputs(self, tool: Tool, request: InvokeRequest
                                        ) -> None:
        """A credential-class argument *name* refuses.

        Matched exactly against the policy's aliases (see
        `envelope.credential_class_names`), and the parameter is named while its
        value never is — the `RedactionError` rule.
        """
        offending = credential_class_names(request.arguments.keys())
        if offending:
            raise _Refusal(
                MALFORMED_PAYLOAD,
                f"credential-class argument name(s) {list(offending)} may not be "
                f"supplied on a capability call for tool {tool.tool_id!r}")

    def _require_secret_free_inputs(self, arguments: Mapping[str, Any]) -> None:
        """A live credential *value* refuses, before anything is recorded.

        This is the half the name guard cannot cover: a secret smuggled as a
        value under a benign name. Without it the secret would reach the
        envelope and the journal.
        """
        for name, value in arguments.items():
            if self._secret_in(record_value(value)):
                raise _Refusal(
                    MALFORMED_PAYLOAD,
                    f"argument {name!r} carried a live credential — refused "
                    f"before it could be recorded (the value is never named)")

    # ── idempotency ──

    def _request_digest(self, request: InvokeRequest,
                        arguments: Mapping[str, Any]) -> str:
        return digest_of({
            "capability_id": request.capability_id,
            "profile": request.profile,
            "arguments": redact_arguments(arguments),
        })

    def _replayed_or_conflict(self, request: InvokeRequest,
                              arguments: Mapping[str, Any], trace: _Trace
                              ) -> Observation | None:
        """A remembered call replays; a key reused for a different act refuses."""
        trace.request_digest = self._request_digest(request, arguments)
        existing = self._ledger.get(request.idempotency_key)
        if existing is None:
            return None
        if existing.request_digest != trace.request_digest:
            raise _Refusal(
                IDEMPOTENCY_CONFLICT,
                f"idempotency key {request.idempotency_key!r} was already used "
                f"for a different request — a retry must be the same act")
        prior = existing.observation
        trace.artifacts = prior.artifacts
        trace.observation_digest = digest_of(
            prior.payload.text if prior.payload is not None else "")
        envelope = self._envelope_for(
            trace, status=prior.status,
            failure=prior.failure.value if prior.failure is not None else "",
            detail=prior.detail, replay=True)
        return Observation(
            capability_id=prior.capability_id,
            status=prior.status,
            payload=prior.payload,
            artifacts=prior.artifacts,
            failure=prior.failure,
            detail=prior.detail,
            idempotency_key=request.idempotency_key,
            replayed=True,
            envelope=envelope)

    # ── gates ──

    def _sandbox_gate(self, tool: Tool, arguments: Mapping[str, Any]) -> None:
        """Refuse an input that reaches outside the tool's declared boundary.

        This is a *remit* breach rather than a formatting slip — the caller is
        asking the tool to step outside what it declared it can do — so it
        refuses `ROLE`, not `MALFORMED_PAYLOAD`.
        """
        if tool.accepts_no_side_effects():
            return
        for name, value in arguments.items():
            text = record_value(value)
            if not tool.process and _PROCESS_CONSTRUCTS.search(text):
                raise _Refusal(
                    ROLE,
                    f"argument {name!r} contains a process-execution construct "
                    f"and tool {tool.tool_id!r} declares process=False")
            if not tool.network and _NETWORK_CONSTRUCTS.search(text.lower()):
                raise _Refusal(
                    ROLE,
                    f"argument {name!r} contains a network construct and tool "
                    f"{tool.tool_id!r} declares network=False")
            for token in _PATH_TOKENS.findall(text):
                if token.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", token):
                    raise _Refusal(
                        ROLE,
                        f"argument {name!r} contains the absolute path {token!r}; "
                        f"tool {tool.tool_id!r} only ever sees relative paths "
                        f"inside its declared scope")
                if ".." in token.split("/") or ".." in token.split("\\"):
                    raise _Refusal(
                        ROLE,
                        f"argument {name!r} contains a traversal in {token!r} — "
                        f"refused as a sandbox-escape-shaped input")
                if tool.filesystem_scope and not (
                        token == tool.filesystem_scope
                        or token.startswith(tool.filesystem_scope + "/")):
                    raise _Refusal(
                        ROLE,
                        f"argument {name!r} contains the path {token!r}, outside "
                        f"tool {tool.tool_id!r}'s declared scope "
                        f"{tool.filesystem_scope!r}")

    def _hazard_gate(self, tool: Tool, arguments: Mapping[str, Any]
                     ) -> tuple[str, str, FailureKind | None]:
        """Evaluate declared hazard knowledge against the declared inputs.

        Fails closed on a declared-but-unregistered spec: an ungated call is
        worse than a refused one.
        """
        if not tool.hazard_spec:
            return ("NONE", "", None)
        spec = self._hazard_specs.get(tool.hazard_spec)
        if spec is None:
            return (
                tool.hazard_spec,
                (f"hazard spec {tool.hazard_spec!r} is declared by tool "
                 f"{tool.tool_id!r} but not registered"),
                FailureKind.NOT_CONFIGURED)
        payload = dict(arguments)
        for marker in spec.markers:
            for value in resolve_field_path(payload, marker.field_path):
                text = record_value(value)
                matched = (
                    (marker.equals != "" and text.strip() == marker.equals)
                    or (marker.pattern != ""
                        and re.search(marker.pattern, text) is not None))
                if not matched:
                    continue
                hazard_class = (marker.failure_class
                                if marker.failure_class in HAZARD_CLASSES
                                else "INJECTION_SUSPECT")
                reason = (f"{spec.spec_id}@{spec.version} marker "
                          f"{marker.field_path!r} matched")
                if hazard_class in ADVISORY_HAZARD_CLASSES:
                    return (hazard_class, reason, None)
                return (hazard_class, reason, FailureKind.HAZARD)
        return ("NONE", "", None)

    def _rate_decision(self, capability_id: str) -> tuple[str, FailureKind | None]:
        if self._limiter is None:
            # Recorded, not silent: an ungated plane is a configuration fact an
            # auditor can see in the envelope.
            return ("ungated", None)
        granted, reason = self._limiter.acquire(capability_id)
        if granted:
            return ("granted", None)
        if reason == "daily_cap_exhausted":
            return (reason, FailureKind.RATE_LIMIT_EXHAUSTED)
        return (reason or "denied", FailureKind.RATE_LIMITED)

    # ── execution ──

    def _gated_execution(self, trace: _Trace, request: InvokeRequest,
                         capability: Capability, tool: Tool,
                         arguments: Mapping[str, Any]
                         ) -> Observation | CapabilityRefusal:
        decision, failure = self._rate_decision(request.capability_id)
        trace.rate_decision = decision
        if failure is not None:
            return self._failed(trace, failure, f"rate gate: {decision}")
        try:
            return self._execute(trace, request, capability, tool, arguments)
        finally:
            # The semaphore slot is always released once granted, which is what
            # keeps a failed call from leaking admission.
            if self._limiter is not None:
                self._limiter.release(request.capability_id)

    def _deadline_seconds(self, tool: Tool, request: InvokeRequest) -> float:
        """The effective deadline: a request may lower the declared bound, never
        raise it."""
        if request.deadline_seconds is None:
            return tool.timeout_seconds
        return max(0.0, min(request.deadline_seconds, tool.timeout_seconds))

    def _execute(self, trace: _Trace, request: InvokeRequest,
                 capability: Capability, tool: Tool,
                 arguments: Mapping[str, Any]
                 ) -> Observation | CapabilityRefusal:
        executor = self._implementations.get(tool.tool_id)
        if executor is None:
            return self._failed(
                trace, FailureKind.NOT_CONFIGURED,
                f"no implementation is wired for tool {tool.tool_id!r} — an "
                f"unimplemented capability fails rather than silently succeeding")
        started = self._clock.monotonic()
        deadline = started + self._deadline_seconds(tool, request)
        context = ToolCallContext(
            capability_id=capability.capability_id,
            tool_id=tool.tool_id,
            idempotency_key=request.idempotency_key,
            lease_generation=request.lease_generation,
            profile=request.profile,
            deadline_monotonic=deadline,
            scratch_dir=tool.filesystem_scope)
        if self._cancel.is_cancelled():
            return self._failed(trace, FailureKind.CANCELLED,
                                "cancelled before execution")
        try:
            result = executor(dict(arguments), context)
        except Exception as exc:  # noqa: BLE001 — a tool boundary: any failure
            # the implementation raises is a typed tool error. The exception
            # text is not recorded (it can embed arguments); only its class.
            return self._failed(trace, FailureKind.TOOL_ERROR,
                                f"tool raised {type(exc).__name__}")
        if self._cancel.is_cancelled():
            return self._failed(
                trace, FailureKind.CANCELLED,
                "cancelled during execution — the result is discarded")
        elapsed = self._clock.monotonic() - started
        if self._clock.monotonic() > deadline:
            # The plane enforces the deadline at the boundary and discards an
            # overrun result. Hard preemption of arbitrary Python needs the
            # sandbox, which is a capability this plane does not implement.
            return self._failed(
                trace, FailureKind.TIMEOUT,
                f"exceeded its {self._deadline_seconds(tool, request):.3f}s "
                f"deadline (took {elapsed:.3f}s) — the result is discarded")
        if not isinstance(result, ToolResult):
            return self._failed(
                trace, FailureKind.TOOL_ERROR,
                f"tool returned {type(result).__name__}, not a ToolResult")
        malformed = sorted(str(handle) for handle in result.artifacts
                           if HANDLE_PATTERN.match(str(handle)) is None)
        if malformed:
            return self._failed(
                trace, FailureKind.TOOL_ERROR,
                f"tool returned malformed artifact handle(s) {malformed[:3]} — "
                f"the plane carries handles and mints no identity")
        if self._secret_in(result.payload):
            return self._failed(
                trace, FailureKind.REDACTION_DENIED,
                "the observation contained a live credential — withheld rather "
                "than recorded (the value is never named)")
        return self._succeed(trace, request, result)

    def _succeed(self, trace: _Trace, request: InvokeRequest,
                 result: ToolResult) -> Observation:
        detail = "; ".join(str(note) for note in result.notes) or "ok"
        observation = self._observation(
            trace, status="OK", payload=result.payload,
            artifacts=tuple(str(handle) for handle in result.artifacts),
            failure=None, detail=detail, replayed=False)
        self._ledger.put(IdempotencyRecord(
            idempotency_key=request.idempotency_key,
            request_digest=trace.request_digest,
            observation=observation))
        return observation

    # ── observation + envelope construction ──

    def _observation(self, trace: _Trace, *, status: str, payload: str = "",
                     artifacts: tuple[str, ...] = (),
                     failure: FailureKind | None = None, detail: str = "",
                     replayed: bool = False) -> Observation:
        trace.artifacts = artifacts
        if status == "OK":
            trace.observation_digest = digest_of(payload)
            trace.observation_size = len(payload.encode("utf-8"))
        else:
            # A non-OK observation carries no payload, so the digest covers what
            # it *does* carry: the failure and its detail. Digesting the empty
            # string would make every failure look like every other failure in
            # the provenance record, which is the opposite of reconstructible.
            trace.observation_digest = digest_of(
                [failure.value if failure is not None else "", detail])
            trace.observation_size = 0
        envelope = self._envelope_for(
            trace, status=status,
            failure=failure.value if failure is not None else "",
            detail=detail, replay=replayed)
        return Observation(
            capability_id=trace.capability_id,
            status=status,
            payload=(UntrustedContent(
                text=payload,
                # The explicit unwrap seam: a caller that wants the bytes asks
                # for `.text`, and the envelope never shows them.
                origin=f"capability.{trace.capability_id}",
                ref=trace.inputs.digest) if status == "OK" else None),
            artifacts=artifacts,
            failure=failure,
            detail=detail,
            idempotency_key=trace.idempotency_key,
            replayed=replayed,
            envelope=envelope)

    def _failed(self, trace: _Trace, failure: FailureKind,
                detail: str) -> Observation:
        return self._observation(trace, status="FAILED", failure=failure,
                                 detail=detail)

    def _refuse(self, trace: _Trace, code: str, detail: str) -> CapabilityRefusal:
        trace.observation_digest = digest_of([code, detail])
        trace.observation_size = 0
        envelope = self._envelope_for(trace, status="REFUSED", failure=code,
                                      detail=detail)
        return CapabilityRefusal(code=code, detail=detail,
                                 capability_id=trace.capability_id,
                                 profile=trace.profile, envelope=envelope)

    def _envelope_for(self, trace: _Trace, *, status: str, failure: str = "",
                      detail: str = "", replay: bool = False
                      ) -> InvocationEnvelope:
        return InvocationEnvelope(
            capability_id=trace.capability_id,
            tool_id=trace.tool_id,
            invoked_at=self._clock.now_utc(),
            who_profile=trace.profile,
            lease_generation=trace.lease_generation,
            why=trace.why,
            idempotency_key=trace.idempotency_key,
            authority=trace.authority,
            inputs=trace.inputs,
            hazard_class=trace.hazard_class,
            hazard_reason=trace.hazard_reason,
            rate_decision=trace.rate_decision,
            observation=EnvelopeObservation(
                status=status,
                failure=failure,
                detail=detail,
                digest=trace.observation_digest,
                size_bytes=trace.observation_size,
                replayed=replay),
            artifacts=trace.artifacts)

    # ── secrets ──

    def _secret_in(self, text: str) -> bool:
        if not self._secrets:
            return False
        return any(secret in text for secret in self._secrets)


# The plane's emitted set must partition the §2.2 vocabulary — every code is
# either emitted here or explicitly the orchestrator's. Asserted, not assumed.
assert EMITTED_REFUSAL_CODES | UNEMITTED_REFUSAL_CODES == CAPABILITY_REFUSAL_CODES
assert not (EMITTED_REFUSAL_CODES & UNEMITTED_REFUSAL_CODES)
