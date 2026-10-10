"""Capability execution shim — the W1 dispatch bridge for BIND-1.

`WIRING_DESIGN.md` BIND-1 asks one question: *how does a capability call execute
from a tick without becoming a writer?* This module is the bridge half of the
answer. It is a **new-files-only** slice (W1) and edits nothing that already
exists; no existing template or handler changes, and every key it knows is a key
somebody registered here.

What the bridge is
------------------
A declared, closed mapping from a **task template key** to a **capability-plane
invocation**, plus the one function that performs a dispatch:

```text
template key ──resolve──▶ CapabilityInvocation        (registered data only)
                │
                ├─ unknown key ──────────────────────▶ "unhandled" (fail closed)
                │
                ├─ permission check (dispatch level) ▶ ROLE refusal-as-data
                │      default-deny: no grant / profile mismatch / unreachable
                │
                ├─ closed argument schema ───────────▶ MALFORMED_PAYLOAD refusal
                │
                └─ CapabilityPort.invoke(request) ───▶ Observation | CapabilityRefusal
                                                       │
                                                       ▼
                                              ObservationHandoff
                                              (untrusted payload + provenance)
```

Four properties are the point, and each is proved by `tests/test_wiring_capability.py`:

1. **Unhandled until registered.** An unknown template key resolves to the
   ``"unhandled"`` sentinel — the same literal `Controller._classify` returns for
   a template with no executor (`research/controller.py:5173`) — never to a guess,
   a default, or a near-miss. Nothing is dispatched for an unregistered key, so a
   key becomes live only when a slice registers it.
2. **Permission precedes every execution.** The dispatch-level permission check
   runs before a request is built, before any argument is recorded, and long
   before the port is touched. A denial therefore consumes no rate token, opens
   no idempotency record in the plane, and runs no tool. (`invoke.py` checks
   authority first for the same reason; this pre-check is the *dispatch* half of
   that discipline, not a replacement for it — the plane stays authoritative.)
3. **Observations return through the port.** The bridge holds no connection, no
   cursor, no repository, no journal and no SQL; it cannot author state because
   the surface to do so does not exist here. The observation comes back as the
   port's return value and leaves as a *proposal*.
4. **The handoff is provenance, not authority.** `ObservationHandoff` carries the
   envelope-wrapped untrusted payload, the bounded redacted provenance note, and
   the task/project/lease attribution. It mints no identity, decides nothing, and
   admits nothing: it is input to an ordinary admission intent routed by the tick
   through `apply_intent`, never the admission itself.

Import discipline (``ARCHITECTURE_DELTA.md`` §3.1 — ports + core types only)
---------------------------------------------------------------------------
`hermes.tools.capabilities.*` (the port's declared shapes), the untrusted-content
envelope (`hermes.security.boundaries`), and stdlib. Never `hermes.persistence`,
never a repository, never raw SQL, never `hermes.research.gateway`.

`CapabilityPort` is declared here **structurally** — the same one-method protocol
the runtime injects (`src/hermes/agents/runtime/run.py:187`) — instead of being
imported from the runtime plane. `CapabilityInvoker.invoke`
(`src/hermes/tools/capabilities/invoke.py:356`) satisfies it by shape, as does
any plane a composition root injects, so the handler speaks the port without
adding a `research → agents` import edge it does not need. Structural conformance
is the contract; the import would only add coupling.

Refusal vocabulary (frozen)
---------------------------
Exactly two codes are emitted by this module's own checks — `ROLE` (a permission
denial at dispatch) and `MALFORMED_PAYLOAD` (a closed-schema violation) — plus
whatever the plane itself returns, which is its own frozen set. No new code,
kind, event or table is introduced anywhere in this slice, and no member of the
refusal vocabulary is redefined.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from hermes.security.boundaries import UntrustedContent
from hermes.tools.capabilities.envelope import (
    InvocationEnvelope,
    undeclared_names,
)
from hermes.tools.capabilities.registry import CapabilityRegistry
from hermes.tools.capabilities.types import (
    MALFORMED_PAYLOAD,
    ROLE,
    CapabilityRefusal,
    InvokeRequest,
    Observation,
    ToolGrant,
)
from hermes.tools.research_sources import ProviderValidationError

__all__ = [
    "REFUSED",
    "UNHANDLED",
    "CapabilityDispatchRegistry",
    "CapabilityInvocation",
    "CapabilityPort",
    "DispatchContext",
    "ObservationHandoff",
]

#: The fail-closed sentinel for a template key no slice has registered. Pinned to
#: the exact literal `Controller._classify` returns for an unknown template
#: (`research/controller.py:5173`) so the bridge and the tick agree on the same
#: word for "no executor", and asserted against that source in the W1 suite.
UNHANDLED = "unhandled"

#: The refusal status this module stamps on a handoff it refused itself, and the
#: status the plane stamps on a refusal envelope (`invoke.py:_refuse`). One
#: spelling, so a refusal reads the same wherever it was decided.
REFUSED = "REFUSED"


def _reject(message: str) -> ProviderValidationError:
    """A registration error — before anything is dispatched, fail closed.

    Deliberately the same error discipline the capability registry uses for its
    own registration (`registry.py:_reject`): a mis-wired composition is refused
    at wiring, not tolerated at call time.
    """
    return ProviderValidationError(message, hazard_class="MALFORMED_REQUEST",
                                   recordable=False)


def _dispatch_key(template_key: str) -> str:
    """The registry's key form — the same normalisation the tick applies.

    `Controller` casefolds and strips a task's template before dispatch
    (`research/controller.py:3048`), so the registry normalises identically:
    `"Cap.Echo"` and `"  cap.echo "` are one key, and a key cannot register in
    one form and be missed in another.
    """
    return template_key.strip().casefold()


@runtime_checkable
class CapabilityPort(Protocol):
    """The Capability plane's ``invoke`` — one bounded call, an observation or a
    refusal.

    Structurally identical to `hermes.agents.runtime.run.CapabilityPort` (the
    protocol the runtime injects at `run.py:187`) and satisfied by
    `CapabilityInvoker` (`invoke.py:356`). Declared here rather than imported so
    this handler depends on the port's *shape* and adds no cross-plane import
    edge; see the module docstring.
    """

    def invoke(self, request: InvokeRequest) -> Observation | CapabilityRefusal: ...


@dataclass(frozen=True, slots=True)
class CapabilityInvocation:
    """One declared template-key → capability binding.

    Declared data, never authority: it names *which* capability a template key
    reaches and which argument names are accepted, and it can do nothing else.
    A key is not dispatchable until an instance of this is registered, which is
    what makes `UNHANDLED` the default state of every key.

    ``argument_fields`` is the dispatch-side closed schema; an argument outside
    it refuses `MALFORMED_PAYLOAD` before the port is called. It is deliberately
    a separate check from the plane's declared tool inputs: this one bounds what
    a *template* may forward, the plane's bounds what a *tool* may receive, and
    both are closed. An empty tuple means "this template forwards nothing".
    """

    template_key: str
    capability_id: str
    argument_fields: tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class DispatchContext:
    """Everything one dispatch is given — and the whole of what it is given.

    There is no connection, no repository, no gateway and no controller
    reference here, because a handler must not be able to reach one. The grant is
    the caller's authority (``None`` is denial, never "unrestricted"), the lease
    generation is propagated attribution rather than a re-issued fence, and the
    idempotency key makes a retry distinguishable from a second act.
    """

    task_id: str
    project_id: str
    lease_generation: str
    profile: str
    idempotency_key: str
    grant: ToolGrant | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ObservationHandoff:
    """The observation → provenance handoff handed back to the tick.

    One shape for every dispatch outcome, so a caller never has to guess which
    of three types it received:

    - ``rejected`` is ``True`` for a refusal (dispatch-level or plane-level) and
      ``code`` then names the frozen refusal code;
    - ``status == UNHANDLED`` marks a template key nobody registered — data, not
      an exception, so the tick can leave the task for diagnostics;
    - otherwise ``status`` is the plane's own observation status and the payload
      and provenance sections are populated.

    The payload travels as an `UntrustedContent` envelope, never as a bare
    string: the only way to read the bytes is the explicit `payload_text()` seam,
    exactly as `Observation.payload.text` is the plane's. `provenance` is the
    plane's **bounded, redacted** journal note (`InvocationEnvelope.to_journal_note`),
    not the full envelope — the 4 KiB payload rule governs this crossing. A
    handoff that never reached the plane (unhandled, denied, malformed) carries
    ``provenance == {}`` and ``envelope_complete is False``: it says it has no
    plane envelope rather than synthesising one.

    Nothing here is an admission, an identity, or an authority. It is a proposal
    the ordinary admission intent routes to the one write path.
    """

    template_key: str
    capability_id: str
    task_id: str
    project_id: str
    lease_generation: str
    profile: str
    idempotency_key: str
    status: str
    payload: UntrustedContent | None = None
    artifacts: tuple[str, ...] = ()
    failure: str = ""
    detail: str = ""
    replayed: bool = False
    observation_digest: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)
    envelope_complete: bool = False
    rejected: bool = False
    code: str = ""

    def payload_text(self) -> str:
        """The explicit unwrap seam — the only way to read the observed bytes.

        Rendering `ObservationHandoff` (or its record form) never shows the text,
        so a log line, an error message or a judgment surface cannot leak it by
        accident. A caller that genuinely needs the bytes — an admission
        validator inside the write path — asks here, by name.
        """
        return "" if self.payload is None else self.payload.text

    def as_record(self) -> dict[str, Any]:
        """The handoff as bounded, JSON-serialisable data for a journal-intent.

        Carries the envelope *marker* (origin and ref), never the payload text —
        see `payload_text()`. This is the shape an ordinary admission intent
        proposes; it is **not** a decision, a digest presented as authority, or a
        durable record. Nothing in this module journals it.
        """
        return {
            "template_key": self.template_key,
            "capability_id": self.capability_id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "lease_generation": self.lease_generation,
            "profile": self.profile,
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "rejected": self.rejected,
            "code": self.code,
            "detail": self.detail,
            "failure": self.failure,
            "replayed": self.replayed,
            "observation_digest": self.observation_digest,
            "envelope_complete": self.envelope_complete,
            "payload_origin": (self.payload.origin
                               if self.payload is not None else ""),
            "payload_ref": (self.payload.ref
                            if self.payload is not None else ""),
            "artifacts": list(self.artifacts),
            "provenance": dict(self.provenance),
        }


class CapabilityDispatchRegistry:
    """The declared template-key → capability-invocation map, plus dispatch.

    Holds registered data and a read-only view of the plane's declarations
    (`CapabilityRegistry`), which is what lets the permission pre-check answer
    "can this grant reach this capability?" without inventing an authority of its
    own. It holds no implementation, no grant, no connection and no writer.
    """

    def __init__(self, *, plane: CapabilityRegistry) -> None:
        self._plane = plane
        self._entries: dict[str, CapabilityInvocation] = {}

    # ── registration ──

    def register(self, invocation: CapabilityInvocation) -> CapabilityInvocation:
        """Register one binding, fail-closed.

        A duplicate key and a capability the plane has not declared are both
        composition bugs: refusing them at registration means a dispatch cannot
        reach an undeclared capability or silently shadow another binding.
        """
        key = _dispatch_key(invocation.template_key)
        if not key:
            raise _reject("a capability invocation must declare a template_key")
        if key in self._entries:
            raise _reject(f"template key {key!r} is already registered — a "
                          f"binding is not silently replaced")
        if self._plane.capability(invocation.capability_id) is None:
            raise _reject(
                f"template key {key!r} names capability "
                f"{invocation.capability_id!r}, which the capability plane has "
                f"not declared — registration fails closed")
        self._entries[key] = invocation
        return invocation

    def keys(self) -> tuple[str, ...]:
        """The registered keys, in a stable order."""
        return tuple(sorted(self._entries))

    def resolve(self, template_key: str) -> CapabilityInvocation | None:
        """The binding for a key, or ``None`` — never a default."""
        return self._entries.get(_dispatch_key(template_key))

    def classify(self, template_key: str) -> str:
        """The key when registered, else the `UNHANDLED` sentinel.

        Same answer the tick's own classifier gives for a template it cannot
        dispatch, so an unregistered key is unhandled here *and* there.
        """
        key = _dispatch_key(template_key)
        return key if key in self._entries else UNHANDLED

    # ── the permission check ──

    def denial_for(self, invocation: CapabilityInvocation,
                   context: DispatchContext) -> str:
        """The dispatch-level permission check: ``""`` permits, a reason denies.

        Default-deny, and intentionally the *same* authority the plane enforces
        (a grant is required; it binds the caller's profile; the capability must
        be reachable through a tool set the grant opens, at or below its risk
        ceiling) consulted through the plane's own `enumerate` so the two
        surfaces cannot disagree. It is a pre-check, not a substitute: the plane
        re-runs its full authority step (approval, mutating, sandbox) inside
        `invoke`, and this method neither weakens nor duplicates that.
        """
        grant = context.grant
        if grant is None:
            return ("no grant — the dispatch surface has no ambient authority "
                    "and denies by default")
        if grant.profile != context.profile:
            return (f"grant {grant.grant_id!r} binds profile "
                    f"{grant.profile!r}, not {context.profile!r}")
        if not self._plane.enumerate(grant=grant).contains(
                invocation.capability_id):
            return (f"capability {invocation.capability_id!r} is not reachable "
                    f"through grant {grant.grant_id!r} (tool sets "
                    f"{sorted(grant.tool_set_ids)}, ceiling {grant.max_risk!r})")
        return ""

    # ── dispatch ──

    def dispatch(self, template_key: str, *, port: CapabilityPort,
                 context: DispatchContext) -> ObservationHandoff:
        """Dispatch one capability call for a template key.

        The order below is the guarantee: resolve, then permission, then the
        closed schema, and only then the port. Any earlier answer returns without
        the port being touched, so a refusal is decided before there is anything
        to execute.
        """
        invocation = self.resolve(template_key)
        if invocation is None:
            return _unhandled(template_key, context)
        # PERMISSION — before a request exists and before the port is touched.
        denial = self.denial_for(invocation, context)
        if denial:
            return _refused(invocation, context, ROLE, denial)
        # CLOSED SCHEMA — still before execution.
        undeclared = undeclared_names(context.arguments,
                                      invocation.argument_fields)
        if undeclared:
            return _refused(
                invocation, context, MALFORMED_PAYLOAD,
                f"undeclared argument(s) {list(undeclared)} for template key "
                f"{invocation.template_key!r} — the dispatch schema is closed")
        request = InvokeRequest(
            capability_id=invocation.capability_id,
            arguments=dict(context.arguments),
            idempotency_key=context.idempotency_key,
            lease_generation=context.lease_generation,
            profile=context.profile,
            rationale=invocation.rationale,
            grant=context.grant)
        # EXECUTION — reachable only past every check above.
        outcome = port.invoke(request)
        if isinstance(outcome, CapabilityRefusal):
            return _refused_by_plane(invocation, context, outcome)
        return _handoff(invocation, context, outcome)


# ── handoff construction (pure; no I/O, no writes) ──


def _unhandled(template_key: str, context: DispatchContext) -> ObservationHandoff:
    """An unregistered key — data, so the tick can leave the task for diagnostics."""
    key = _dispatch_key(template_key)
    return ObservationHandoff(
        template_key=key,
        capability_id="",
        task_id=context.task_id,
        project_id=context.project_id,
        lease_generation=context.lease_generation,
        profile=context.profile,
        idempotency_key=context.idempotency_key,
        status=UNHANDLED,
        detail=(f"template key {key!r} is not registered — unhandled (fail "
                f"closed: nothing is dispatched for an unregistered key)"))


def _refused(invocation: CapabilityInvocation, context: DispatchContext,
             code: str, detail: str) -> ObservationHandoff:
    """A dispatch-level refusal. No plane call happened, so there is no envelope."""
    return ObservationHandoff(
        template_key=invocation.template_key,
        capability_id=invocation.capability_id,
        task_id=context.task_id,
        project_id=context.project_id,
        lease_generation=context.lease_generation,
        profile=context.profile,
        idempotency_key=context.idempotency_key,
        status=REFUSED,
        detail=detail,
        rejected=True,
        code=code)


def _refused_by_plane(invocation: CapabilityInvocation, context: DispatchContext,
                      refusal: CapabilityRefusal) -> ObservationHandoff:
    """A refusal the plane decided, carrying the plane's own envelope provenance."""
    envelope = refusal.envelope
    return ObservationHandoff(
        template_key=invocation.template_key,
        capability_id=refusal.capability_id or invocation.capability_id,
        task_id=context.task_id,
        project_id=context.project_id,
        lease_generation=context.lease_generation,
        profile=refusal.profile or context.profile,
        idempotency_key=context.idempotency_key,
        status=REFUSED,
        detail=refusal.detail,
        observation_digest=_observation_digest(envelope),
        provenance=_provenance_of(envelope),
        envelope_complete=_complete(envelope),
        rejected=True,
        code=refusal.code)


def _handoff(invocation: CapabilityInvocation, context: DispatchContext,
             observation: Observation) -> ObservationHandoff:
    """A plane observation, wrapped with its provenance for the tick."""
    envelope = observation.envelope
    return ObservationHandoff(
        template_key=invocation.template_key,
        capability_id=observation.capability_id or invocation.capability_id,
        task_id=context.task_id,
        project_id=context.project_id,
        lease_generation=context.lease_generation,
        profile=context.profile,
        idempotency_key=(observation.idempotency_key
                         or context.idempotency_key),
        status=observation.status,
        payload=observation.payload,
        artifacts=observation.artifacts,
        failure=(observation.failure.value
                 if observation.failure is not None else ""),
        detail=observation.detail,
        replayed=observation.replayed,
        observation_digest=_observation_digest(envelope),
        provenance=_provenance_of(envelope),
        envelope_complete=_complete(envelope),
        rejected=False,
        code="")


def _provenance_of(envelope: InvocationEnvelope | None) -> Mapping[str, Any]:
    """The bounded, redacted provenance note, or ``{}`` when there is no envelope."""
    if envelope is None:
        return {}
    return envelope.to_journal_note()


def _observation_digest(envelope: InvocationEnvelope | None) -> str:
    """The envelope's observation digest, or ``""`` when there is no envelope."""
    if envelope is None or envelope.observation is None:
        return ""
    return str(envelope.observation.digest)


def _complete(envelope: InvocationEnvelope | None) -> bool:
    """Whether the envelope carries every required provenance section."""
    return envelope is not None and envelope.is_complete()
