"""Model binding — the `ModelPort` → `ModelRouter` wiring (WIRING_DESIGN BIND-2).

`WIRING_DESIGN.md` BIND-2 asks one question: *how does a model call produce only
proposals that re-enter through intents?* The router answers the plane half
(`src/hermes/tools/models/router.py`: closed request schema, output-contract
validation, enveloped `ModelProposal`, refusal-as-data). This module is the
**binding** half, and it is a new-files-only slice: it edits nothing that already
exists, adds no dependency, and emits no code the frozen vocabulary does not
already name.

What the binding adds — and nothing else
----------------------------------------
Three jobs sit between the runtime's `ModelPort` and the router, and each is a
wiring concern rather than a plane behaviour:

1. **Per-task model policy resolution.** A task does not choose its model tier.
   The binding resolves the tier for the task's profile from *declared policy
   data* (`ModelPolicyTable`) and rewrites the request's tier field to the
   resolved value. A caller-supplied tier is therefore a hint that the binding
   overrides — never an ambient authority — and a task with no declared tier and
   no default refuses `MALFORMED_PAYLOAD` instead of falling through to some
   model. This is the `ModelPlanePolicy` discipline (config-declared refs, no
   baked-in vendor) applied one level up.
2. **Credential discipline that never touches a payload or a log.** The router
   already has no credential field on `ModelCall` and refuses credential-class
   option *names*. The binding adds two independent controls on the same rule:
   it refuses a credential-class option name before the router is reached
   (defence in depth, naming the parameter and never the value), and it scans
   every row it records for a live credential value, failing loudly with
   `ModelPlaneInvariantError` rather than recording it. Credentials themselves
   reach the transport edge only: `bind_model_port` hands the resolver to the
   router's constructor, and no code path here can put a credential into a
   `ModelRequest`.
3. **Accounting per dispatch.** The router accounts per *provider attempt*
   (retry and fallback hops included: `router.py` `_attempt`); the binding
   accounts per *dispatch*, so "what did this task ask the model plane for?"
   has exactly one row even when the router retried, fell back, or never
   reached a provider at all. A refusal is accounted too — deciding not to call
   a model is a decision about the model plane and belongs in its ledger.

What the binding is not
-----------------------
It is **not** an authority and holds no state beyond a bounded in-process log:
no SQLite, no transaction, no repository, no journal, no lease custody, no
artifact store. It never decides a transition (the router's output is a
`ModelProposal` or a `ModelRefusal`, both data), it authors no identity, and it
imports `hermes.tools.models.router` plus stdlib only — never `hermes.core`,
never `hermes.agents`, never `hermes.research`, never `hermes.persistence`.

Refusal vocabulary (frozen)
---------------------------
The one code this module's own checks emit is `MALFORMED_PAYLOAD` (a task with
no resolvable tier; a credential-class option name). Everything else is the
router's own frozen subset (`LOCK`, `MALFORMED_PAYLOAD`, `PROPOSAL`, `RATIONALE`,
`ROLE`) forwarded unchanged. No new code, kind, event or table is introduced.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, runtime_checkable

from hermes.tools.models.router import (
    CREDENTIAL_ONLY_POLICY,
    MALFORMED_PAYLOAD,
    CredentialResolver,
    ModelCallAccount,
    ModelPlaneInvariantError,
    ModelPlanePolicy,
    ModelProposal,
    ModelProvider,
    ModelRefusal,
    ModelRequest,
    ModelRouter,
    TokenUsage,
)

__all__ = [
    "DispatchAccount",
    "ModelBinding",
    "ModelPolicyTable",
    "ModelPort",
    "bind_model_port",
]


@runtime_checkable
class ModelPort(Protocol):
    """The runtime's model port — one bounded call, a proposal or a refusal.

    Structurally identical to `hermes.agents.runtime.run.ModelPort`
    (`run.py:180`), and satisfied by `ModelBinding` below exactly as it is by
    `ModelRouter`. Declared here rather than imported so this module depends on
    the port's *shape* and adds no `hermes.tools → hermes.agents` import edge —
    the same structural-conformance choice W1's capability bridge makes for
    `CapabilityPort`. Import direction stays one-way (§3.1).
    """

    def invoke(self, request: ModelRequest) -> ModelProposal | ModelRefusal: ...


@dataclass(frozen=True, slots=True)
class ModelPolicyTable:
    """Declared per-task model policy: *task key → tier*.

    Declared data, never authority. The key is the task's runtime identity (the
    profile name the runtime puts on `ModelRequest.profile`), so resolving a
    tier is a lookup rather than a guess. `default_tier` is the fallback for a
    key the table does not name; an empty default means "no default", and a task
    that resolves to nothing refuses rather than silently reaching a model.
    """

    tiers: Mapping[str, str] = field(default_factory=dict)
    default_tier: str = ""

    def tier_for(self, key: str) -> str:
        """The tier declared for `key`, else the default, else `""` (no model)."""
        declared = self.tiers.get(key, "")
        if declared and declared.strip():
            return declared
        return self.default_tier if self.default_tier.strip() else ""


@dataclass(frozen=True, slots=True)
class DispatchAccount:
    """One ledger row per dispatch — the *wiring's* accounting, not the plane's.

    The router's `ModelCallAccount` records provider attempts; this records what
    a task asked for. `attempt == 0` marks a dispatch the binding itself refused
    (no provider was contacted), mirroring the router's own attempt-0 rule.

    `to_mapping()` is the only record shape this module produces, and it carries
    no credential value, no request body and no identity — digests and counts
    only. Rendering an account can therefore not leak a secret or a prompt.
    """

    sequence: int
    profile: str
    requested_tier: str
    resolved_tier: str
    lease_generation: str
    outcome: str  # "OK" | "REFUSED"
    provider_id: str = ""
    model_id: str = ""
    attempt: int = 0
    request_digest: str = ""
    refusal_code: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    context_tokens: int = 0
    price_usd: float | None = None
    dispatched_at: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_mapping(self) -> dict[str, Any]:
        """The row as bounded, JSON-serialisable, credential-free data."""
        return {
            "sequence": self.sequence,
            "profile": self.profile,
            "requested_tier": self.requested_tier,
            "resolved_tier": self.resolved_tier,
            "lease_generation": self.lease_generation,
            "outcome": self.outcome,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "attempt": self.attempt,
            "request_digest": self.request_digest,
            "refusal_code": self.refusal_code,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "context_tokens": self.context_tokens,
            "price_usd": self.price_usd,
            "dispatched_at": self.dispatched_at,
        }


class ModelBinding:
    """`ModelRouter` behind the runtime's `ModelPort`, with policy + accounting.

    Construct one per composition root and inject it wherever the plane expects a
    `ModelPort`. `invoke` is the whole surface: resolve the task's declared tier,
    refuse early on a credential-class option name, dispatch, account.
    """

    def __init__(
        self,
        *,
        router: ModelRouter,
        policy: ModelPolicyTable,
        clock: Any,
        credentials: CredentialResolver | None = None,
    ) -> None:
        self._router = router
        self._policy = policy
        self._clock = clock
        self._dispatch_log: list[DispatchAccount] = []
        #: Resolved once, for one purpose only: to fail loudly if a live
        #: credential value ever appears in a row this module records. The
        #: binding never builds a request from these bytes.
        self._secrets = _secrets_of(credentials, router.provider_ids())

    # ── the port ──

    def invoke(self, request: ModelRequest) -> ModelProposal | ModelRefusal:
        """One dispatch: policy-resolved, credential-guarded, accounted."""
        resolved_tier = self._policy.tier_for(request.profile)
        if not resolved_tier:
            return self._refuse(
                request, resolved_tier,
                f"no model tier is declared for task/profile {request.profile!r} "
                f"and the policy declares no default (declared keys: "
                f"{sorted(self._policy.tiers)}) — a task does not choose its own "
                f"model, and one with no declared tier refuses rather than "
                f"silently reaching a model")
        offending = _credential_option_names(request.options)
        if offending:
            return self._refuse(
                request, resolved_tier,
                f"credential-class option name(s) {offending} may not be supplied "
                f"on a model call — credentials are injected at the transport "
                f"edge and never enter a payload, a request or a log")
        bound = (request if request.tier == resolved_tier
                 else replace(request, tier=resolved_tier))
        outcome = self._router.invoke(bound)
        # Recorded against the *caller's* request, so `requested_tier` keeps the
        # hint the caller sent; `resolved_tier` is what the router was asked for.
        self._record(request, resolved_tier, outcome)
        return outcome

    # ── read surfaces ──

    def dispatch_log(self) -> tuple[DispatchAccount, ...]:
        """Every dispatch this binding has made, in order."""
        return tuple(self._dispatch_log)

    @property
    def dispatches(self) -> int:
        return len(self._dispatch_log)

    def model_ledger(self) -> tuple[ModelCallAccount, ...]:
        """The router's own per-attempt ledger (read-only passthrough)."""
        return self._router.accounting()

    def policy(self) -> ModelPolicyTable:
        return self._policy

    def verify_accounting(self) -> None:
        """Fail closed unless every dispatch has exactly one ordered row.

        Pairs with the router's own `verify_accounting()` (which proves every
        provider attempt was accounted): this side proves the *dispatch* ledger
        is whole and ordered, so an unaccounted dispatch is an invariant breach
        rather than a warning — the same fail-closed posture the plane takes.
        """
        self._router.verify_accounting()
        for index, row in enumerate(self._dispatch_log):
            if row.sequence != index:
                raise ModelPlaneInvariantError(
                    f"dispatch accounting sequence broken at index {index}: row "
                    f"claims {row.sequence}", hazard_class="ACCOUNTING_GAP",
                    recordable=False)

    # ── recording ──

    def _refuse(self, request: ModelRequest, resolved_tier: str,
                detail: str) -> ModelRefusal:
        """A refusal this binding decided. Accounted even though no call was made."""
        refusal = ModelRefusal(code=MALFORMED_PAYLOAD, detail=detail,
                               tier=resolved_tier or request.tier)
        self._record(request, resolved_tier, refusal)
        return refusal

    def _record(self, request: ModelRequest, resolved_tier: str,
                outcome: ModelProposal | ModelRefusal) -> DispatchAccount:
        account = outcome.account
        usage = account.usage if account is not None else TokenUsage()
        row = DispatchAccount(
            sequence=len(self._dispatch_log),
            profile=request.profile,
            requested_tier=request.tier,
            resolved_tier=resolved_tier,
            lease_generation=request.lease_generation,
            outcome="REFUSED" if isinstance(outcome, ModelRefusal) else "OK",
            provider_id=outcome.provider_id or _account_field(account, "provider_id"),
            model_id=outcome.model_id or _account_field(account, "model_id"),
            attempt=account.attempt if account is not None else 0,
            request_digest=(account.request_digest if account is not None else ""),
            refusal_code=(outcome.code if isinstance(outcome, ModelRefusal)
                          else None),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            context_tokens=(account.context_tokens if account is not None else 0),
            price_usd=(account.price_usd if account is not None else None),
            dispatched_at=self._clock.now_utc(),
        )
        # The row is the only thing this module records; scan it before it is
        # kept, so a leaked credential is an incident rather than a log line.
        self._assert_secret_free(row.to_mapping(), where="dispatch account")
        self._dispatch_log.append(row)
        return row

    def _assert_secret_free(self, value: object, *, where: str) -> None:
        """Fail closed if a live credential appears in what is about to be kept.

        The structural guarantee (no credential field exists on a request) plus
        the option-name guard should make this unreachable; it is here so that
        "should" is not what stands between a secret and this module's records.
        """
        if not self._secrets:
            return
        rendered = json.dumps(value, default=str)
        for secret in self._secrets:
            if secret and secret in rendered:
                raise ModelPlaneInvariantError(
                    f"a live credential appeared in {where} — refusing to record "
                    f"it (the value is never named)",
                    hazard_class="SECRET_LEAK", recordable=False)


def bind_model_port(
    *,
    providers: Iterable[ModelProvider],
    policy: ModelPlanePolicy,
    clock: Any,
    task_policy: ModelPolicyTable,
    credentials: CredentialResolver | None = None,
    proposable_kinds: frozenset[str] = frozenset(),
    tool_allowlist: frozenset[str] = frozenset(),
) -> ModelBinding:
    """Build the router *and* its binding, so credentials have one entry point.

    The resolver is handed to `ModelRouter`'s constructor — the transport edge —
    and nowhere else. That is the whole credential flow: it enters here, and no
    value derived from it can be placed on a `ModelRequest` because the binding
    has no parameter, field or code path that accepts one.
    """
    router = ModelRouter(
        providers=providers,
        policy=policy,
        clock=clock,
        proposable_kinds=proposable_kinds,
        tool_allowlist=tool_allowlist,
        credentials=credentials,
    )
    return ModelBinding(router=router, policy=task_policy, clock=clock,
                        credentials=credentials)


# ── pure helpers ──


def _credential_option_names(options: Mapping[str, str]) -> list[str]:
    """Option names of credential class — matched exactly, never by substring.

    The same rule (and the same alias set) the router enforces in
    `_require_non_secret_options`; substring matching would refuse an ordinary
    name such as `max_tokens`, so the match is exact.
    """
    aliases = CREDENTIAL_ONLY_POLICY.credential_aliases
    return sorted(key for key in options if key.strip().lower() in aliases)


def _secrets_of(credentials: CredentialResolver | None,
                provider_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Resolve the live credential values once, for the leak scan only."""
    if credentials is None:
        return ()
    found: list[str] = []
    for provider_id in provider_ids:
        credential = credentials.resolve(provider_id)
        if credential is None:
            continue
        value = credential.reveal()
        if value:
            found.append(value)
    return tuple(found)


def _account_field(account: ModelCallAccount | None, name: str) -> str:
    """The account's provider/model id, or `""` when there is no account."""
    if account is None:
        return ""
    return str(getattr(account, name, "") or "")
