"""Governance — authority evaluation over recorded rows (§2.5, B-1).

What this module is
-------------------
Given (a) an *action* a caller wants to take, (b) the recorded evidence — the
`operator_credentials` row for the acting operator and the recorded
`HumanDecisionReceived` rows — and (c) the versioned policy matrix, this module
answers one question:

    ALLOWED — the row's authority is satisfied, and here are the rows that
              satisfied it;
    REFUSED — refusal-as-data (`{"rejected": True, "code", "detail"}`) naming
              the requirement that failed, the evidence it read, and the policy
              version that decided.

It answers; it does not act. Nothing here enforces, mutates, writes, or decides a
transition: the spine's enforcement chain (§2.5 *Enforcement points*) is
untouched, no caller in the repo invokes this module, and denying or allowing has
no effect on any state anywhere. "Wired" is therefore **false** — an honest
statement repeated in the package docstring and the round report.

The evaluation is TOTAL (R5 red team P1-b)
------------------------------------------
`evaluate_authority` never raises to its caller. Every gap the contract leaves —
a missing scope, no declared clock, a row shape that cannot be read, a request
object of the wrong type — is answered with a coded refusal:

* every request-shape gap is pre-validated and refused `MALFORMED_PAYLOAD` with
  the requirement it blocks (so the code is never a guess);
* a narrow backstop around the evaluation converts any read failure
  (`GovernanceFormatError`/`ValueError`/`TypeError`/`KeyError`/`AttributeError`/
  `IndexError`) into the same coded refusal, naming the exception type in the
  detail.

That is the difference the plane keeps between **evidence** and a **request**:
evidence the plane cannot read is an integrity incident (`GovernanceFormatError`,
for a direct caller of `policy`/`approvals`), while a request the plane cannot
interpret is the caller's schema problem and is *refused*, so a caller never has
to catch to learn it was denied. §2.4's discipline — "never raises through the
loop" — holds at this surface too.

Check inputs are policy-owned (R5 red team P1-a)
------------------------------------------------
The request carries the *values* an act is judged on (`command_hash`,
`target_ref`, `head_ref`, `now`). It does **not** carry the *keys* the recorded
decision is read at, nor the approval window: those are policy data on the row
(`PolicyRow.binding_key`/`target_key`/`head_key`/`window_seconds`, v2). A request
that still supplies `binding_key`, `target_key` or `window_seconds` is refused
`MALFORMED_PAYLOAD` — "check inputs are policy-owned" — because a check whose
subject selects the field it is checked against is not a check. Concretely, this
removes the two live P1 bypasses:

    PUBLISH        command_hash='APPROVED'  binding_key='decision'
    EVIDENCE_DELETE target_ref=<operator note>  target_key='rationale'

Both are now refused: the row, not the requester, names `publish_hash` and
`target_ref`.

Authority is read, never claimed
--------------------------------
The request carries **no authority field**: a caller cannot declare its own
level, so self-elevation is impossible by construction (a mapping that tries is
refused `MALFORMED_PAYLOAD`). Authority is derived only from recorded rows:

* `AGENT` / `AGENT+RECORD` — no credential and no recorded decision; the act is
  inside the agent's own remit. `AGENT+RECORD` additionally requires the act to
  carry a record (a rationale); without one the act is refused `RATIONALE`.
* `REVIEWER` (+ the row's `RESTRICTED` modifier) — a ratified operator credential
  must exist for the named operator (`OPERATOR` otherwise), and a recorded
  decision for the act's scope must be `APPROVED` (otherwise the approval
  lifecycle's own refusal). A `RESTRICTED` row additionally requires the recorded
  decision to bind the *specific target* at the row's `target_key`, not merely
  the action class.
* `HUMAN` — the `REVIEWER` bar plus a binding of the exact deterministic command
  hash (`command_hash` at the row's `binding_key`), plus the head check: a
  recorded approval that binds a superseded head is refused `STALE`.

The distinguishing rule between `REVIEWER` and `HUMAN` is therefore *what the
recorded decision must bind*, and it mirrors the repo: the curation /
classification / contradiction validators compare a recorded decision against a
recomputed command hash and refuse `PROPOSAL` when they differ
(`gateway.py:2048-2055`, `:3268-3272`, `:2998-3002`), while the reviewer surfaces
dereference a recorded decision (`gateway.py:1479-1494`, `:2021-2036`).

Independence — an operator does not ratify their own act (R5 red team P2)
------------------------------------------------------------------------
For every row whose authority is a recorded decision, the decisive decision must
be *independent* of the requester: the recorded `operator_id` of the decisive row
may not equal the requesting `actor`. An operator acting on their own approval is
refused `ROLE` ("any profile acting as an authority", §2.1) with requirement
`INDEPENDENCE`. The failure modes fail closed: a decision row carrying no
`operator_id`, and a request declaring no `actor`, are both refused (independence
cannot be established), so omitting the actor is not a way to skip the rule.

The shape precedent is the runtime plane's own structural suppression — a child
run never spawns a review by its own reviewer (`agents/runtime/run.py`,
`test_agent_runtime.py:1623` "a child run never reviews its own reviewer"). Here
the rule is *reported* rather than suppressed, because a Governance evaluation
must answer with a code.

**The rule's limit — no identity registry (R5-REATTACK item 3, FIX-2).** The rule
compares two *strings*: the requesting `actor` and the recorded decision's
`operator_id`. The plane holds no registry of the profiles that may act and
cannot resolve identity, so two operator ids a deployment binds to one human are,
to this plane, two distinct parties — `op-2` may decide an act that
`actor='op-1'` requested. Resolving identity, or closing `actor` to a vocabulary,
needs a profile registry this plane does not have (a design gate); it is recorded
here as a documented limit, pinned by a test asserting the distinction, **not**
as a fix claim.

The trust boundary (documented, not enforced here) — R5 red team P2 caveat
-------------------------------------------------------------------------
The rows handed to this module are evaluated **as given**. The plane cannot tell
a genuinely recorded `HumanDecisionReceived` row from a well-formed forgery: it
holds no connection and performs the read nowhere. Resolving rows from the
journal, and proving they were recorded, is the **enforcement path's** act (§2.5
*Enforcement points*) — today the human-gate spine, which appends and reads those
rows inside the gateway's transaction. This plane is therefore an evaluation over
supplied evidence, and its verdict is only as good as the evidence resolution
that feeds it. That is stated in the docstring and pinned by a test rather than
papered over with a check this plane cannot perform.

Known, recorded design limits (accepted residuals; deltas recorded in
`R5_FIX_REPORT.md`)
--------------------------------------------------------------------
* **Scope selection (red team X1).** The approval *scope* (`correlation_id` /
  `approval_scope`, and the project id) is still declared by the requester. The
  plane cannot compute the repo's command-hash correlation key for an act without
  repo knowledge, which would be a design gate. What it does instead is prove
  containment: a decision row from another project or another scope is counted
  and never used, and only an `APPROVED` decision for the *exact* scope satisfies
  the row.
* **No lease generation (red team P3).** The word `lease` does not appear in this
  package. A lease-generation concept needs a new table/column or event — a
  schema and authority change, i.e. a design gate, and explicitly out of scope
  for this round. The window is the freshness control this plane can evaluate
  from rows it is handed.
* **`REQUIREMENTS` / `emitted_refusal_codes` (red team P3 extras).** Diagnostic
  and audit vocabulary — the plane's own names, like the runtime's `TRACE_KINDS`
  — not codes, events, intent kinds or tables.

Codes emitted (frozen meanings; no new code, no meaning change)
---------------------------------------------------------------
`ROLE` (no authority / partition violation / self-approval / ungoverned action —
deny by default), `OPERATOR` (operator identity presented, credential not
ratified), `PROPOSAL` (no bound / mismatched recorded decision), `STALE` (the
approval binds a superseded head), `RATIONALE` (a required record is absent),
`MALFORMED_PAYLOAD` (the request or row schema is malformed, including a
policy-owned check input).

Where a row can express the choice, the code comes from the row (so the matrix
stays auditable data); the plane's own two literals are `ROLE` and
`MALFORMED_PAYLOAD`.

Deny-wins
---------
Delegated to `policy._resolve`: any DENY row governs whatever PERMIT rows sit
beside it, and the verdict names every conflicting row (`conflicting_rows`) so the
denial is never silent.

The policy is canonical at the public surface (R5-REATTACK E2, FIX-2)
---------------------------------------------------------------------
`evaluate_authority(request, context)` evaluates against `GOVERNANCE_POLICY` and
nothing else. A caller who could pass `policy=` would select, one level up, every
check input v2 made policy-owned — the defect the request schema closed,
re-opened by choosing the matrix. So the public entry admits no substituted
policy: a `policy` argument, positional or keyword (the shipped document
included), is refused **as data** with `MALFORMED_PAYLOAD` naming
`POLICY_SUBSTITUTION_DETAIL` — a coded refusal, never a `TypeError` and never a
silent ignore, because a wiring-time misconfiguration must be legible as data.
`evaluate_approval` and `resolve` are canonical-bound the same way. The
substitutable seam survives as the private `_evaluate_authority` (with
`approvals._evaluate_approval` and `policy._resolve`), reachable only from the
evaluation layer and the test harness.

Import direction: `hermes.governance.{policy,approvals}` + standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from hermes.governance.approvals import (
    ApprovalEvaluation,
    ApprovalRequest,
    DecisionRow,
    _evaluate_approval,
    is_readable_timestamp,
)
from hermes.governance.policy import (
    GOVERNANCE_POLICY,
    GOVERNANCE_REFUSAL_CODES,
    MALFORMED_PAYLOAD,
    OPERATOR,
    POLICY_SUBSTITUTION_DETAIL,
    REQUIREMENT_AUTHORITY,
    REQUIREMENT_BINDING,
    REQUIREMENT_CREDENTIAL,
    REQUIREMENT_DECISION,
    REQUIREMENT_HEAD,
    REQUIREMENT_INDEPENDENCE,
    REQUIREMENT_POLICY,
    REQUIREMENT_RECORD,
    REQUIREMENT_REQUEST,
    REQUIREMENT_TARGET,
    ROLE,
    STALE,
    GovernanceFormatError,
    GovernanceRefusal,
    Policy,
    _resolve,
    digest_of,
)

ALLOWED = "ALLOWED"
REFUSED = "REFUSED"
VERDICTS: tuple[str, ...] = (ALLOWED, REFUSED)

#: The closed request schema. `authority` is deliberately absent — a caller
#: cannot claim a level, and an unknown key (including `authority`) refuses.
#: The check *inputs* are absent too (v2, P1-a): `binding_key`, `target_key` and
#: `window_seconds` live on `PolicyRow`, never on the request.
REQUEST_KEYS: frozenset[str] = frozenset({
    "action",
    "project_id",
    "actor",
    "actor_is_human",
    "operator_id",
    "correlation_id",
    "approval_scope",
    "command_hash",
    "head_ref",
    "rationale",
    "target_ref",
    "now",
})

#: Check inputs a v1-shaped caller may still try to supply. Refused explicitly
#: (not merely "unknown key") so the refusal says which rule was invoked.
POLICY_OWNED_REQUEST_KEYS: tuple[str, ...] = (
    "binding_key", "target_key", "window_seconds")

#: The request fields that must be strings (validated before any check runs, so
#: no read of a wrongly-typed field can raise).
REQUEST_STRING_FIELDS: tuple[str, ...] = (
    "action", "project_id", "actor", "operator_id", "correlation_id",
    "approval_scope", "command_hash", "head_ref", "rationale", "target_ref",
    "now")

#: Keys that would make a credential snapshot carry a secret. The plane never
#: sees, stores or checks a token: verification is the spine's act at the
#: controller surface (`OperatorCredentialRepository.verify`), and a row that
#: tries to hand this plane one is refused.
SECRET_KEYS: tuple[str, ...] = ("token", "token_hash", "plaintext_token",
                                "password", "secret")

#: Sentinel for "no `policy` argument was supplied" at the public
#: `evaluate_authority`. Any `policy` it receives — the shipped document included
#: — is refused as data (R5-REATTACK E2, FIX-2): the canonical document is bound
#: internally, and the substitutable seam is the private `_evaluate_authority`.
_NO_POLICY_SUPPLIED: Any = object()


@dataclass(frozen=True, slots=True)
class CredentialRow:
    """One `operator_credentials` row as READ from the store.

    The recorded columns are `operator_id`, `name`, `created_at`
    (`persistence/migrations.py` 10→11 creates exactly these plus `token_hash`).
    The hash is deliberately **not** part of this snapshot, and `from_mapping`
    refuses it: this plane audits *that a credential exists*, never whether a
    token is right.
    """

    operator_id: str
    name: str = ""
    created_at: str = ""

    def to_mapping(self) -> dict[str, Any]:
        return {"operator_id": self.operator_id, "name": self.name,
                "created_at": self.created_at}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CredentialRow":
        for key in SECRET_KEYS:
            if key in data:
                raise GovernanceFormatError(
                    f"a CredentialRow never carries {key!r}: the plane audits "
                    f"existence, the spine verifies the token")
        unknown = sorted(set(data) - {"operator_id", "name", "created_at"})
        if unknown:
            raise GovernanceFormatError(f"unknown CredentialRow keys: {unknown}")
        if not data.get("operator_id"):
            raise GovernanceFormatError("CredentialRow.operator_id is required")
        return cls(operator_id=str(data["operator_id"]),
                   name=str(data.get("name", "")),
                   created_at=str(data.get("created_at", "")))


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """What a caller wants to do, and the values it declares about the act.

    A *declaration*, never an authorization: every field is either an input the
    policy row needs (the action, the project) or a value the evaluation compares
    against recorded rows (`operator_id`, `actor`, `command_hash`, `head_ref`,
    `target_ref`, `now`). Which payload keys those values are compared *at* is
    policy data (v2) — see the module docstring.
    """

    action: str
    project_id: str
    actor: str = ""
    actor_is_human: bool = False
    operator_id: str = ""
    correlation_id: str = ""
    approval_scope: str = ""
    command_hash: str = ""
    head_ref: str = ""
    rationale: str = ""
    target_ref: str = ""
    now: str = ""

    @property
    def scope(self) -> str:
        """The approval scope: the explicit scope, else the correlation id.

        A correlation id *is* the repo's command/correlation key for a recorded
        decision (`retract:sha256(...)`, `curate-decision-<hash>`, …), so it is
        the natural default and an explicit override stays available.
        """
        return self.approval_scope or self.correlation_id

    def to_mapping(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "project_id": self.project_id,
            "actor": self.actor,
            "actor_is_human": self.actor_is_human,
            "operator_id": self.operator_id,
            "correlation_id": self.correlation_id,
            "approval_scope": self.approval_scope,
            "command_hash": self.command_hash,
            "head_ref": self.head_ref,
            "rationale": self.rationale,
            "target_ref": self.target_ref,
            "now": self.now,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ActionRequest":
        owned = sorted(set(data) & set(POLICY_OWNED_REQUEST_KEYS))
        if owned:
            raise GovernanceFormatError(
                f"check inputs are policy-owned: {owned} — which payload key a "
                f"check reads and the approval window are declared by the "
                f"policy row, never by the request")
        unknown = sorted(set(data) - REQUEST_KEYS)
        if unknown:
            raise GovernanceFormatError(
                f"unknown ActionRequest keys: {unknown} — authority is read from "
                f"recorded rows, never claimed in the request")
        return cls(
            action=str(data.get("action", "")),
            project_id=str(data.get("project_id", "")),
            actor=str(data.get("actor", "")),
            actor_is_human=bool(data.get("actor_is_human", False)),
            operator_id=str(data.get("operator_id", "")),
            correlation_id=str(data.get("correlation_id", "")),
            approval_scope=str(data.get("approval_scope", "")),
            command_hash=str(data.get("command_hash", "")),
            head_ref=str(data.get("head_ref", "")),
            rationale=str(data.get("rationale", "")),
            target_ref=str(data.get("target_ref", "")),
            now=str(data.get("now", "")),
        )


@dataclass(frozen=True, slots=True)
class EvidenceContext:
    """The recorded rows handed to the evaluation — nothing is read here.

    `credential` is the `operator_credentials` row for the acting operator (or
    `None` when there is none); `decisions` are `HumanDecisionReceived` rows
    (this project's, and any others — the evaluation filters by project itself,
    so an unfiltered read cannot leak another project's authority in).

    The rows are evaluated **as given**: see the module docstring's trust
    boundary. The shape is validated (`_context_errors`) so a wrongly-shaped
    context is a coded refusal, not a raise.
    """

    credential: CredentialRow | None = None
    decisions: tuple[DecisionRow, ...] = field(default_factory=tuple)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "credential": (self.credential.to_mapping()
                           if self.credential is not None else None),
            "decisions": [row.to_mapping() for row in self.decisions],
        }


@dataclass(frozen=True, slots=True)
class AuthorityVerdict:
    """The plane's answer: ALLOWED, or REFUSED with refusal-as-data.

    `required_authority`/`satisfied_authority` use the brief's names
    (`AGENT`, `AGENT+RECORD`, `REVIEWER`, `REVIEWER/RESTRICTED`, `HUMAN`).
    `evidence` lists the rows that satisfied (or were consulted for) the verdict
    — recorded decision event ids and the operator id — so any verdict can be
    audited back to the rows behind it.
    """

    action: str
    project_id: str
    verdict: str
    actor: str = ""
    required_authority: str = ""
    satisfied_authority: str = ""
    requirement: str = ""
    policy_id: str = ""
    policy_version: int = 0
    evidence: tuple[str, ...] = ()
    conflicting_rows: tuple[str, ...] = ()
    approval: ApprovalEvaluation | None = None
    refusal: GovernanceRefusal | None = None

    def is_allowed(self) -> bool:
        return self.verdict == ALLOWED

    def digest(self) -> str:
        """Deterministic digest of the verdict — the determinism fixture's unit."""
        return digest_of(self.to_mapping())

    def as_dict(self) -> dict[str, Any]:
        """A flat, human-legible form; refusals keep the §2.4 shape."""
        base: dict[str, Any] = {
            "action": self.action,
            "project_id": self.project_id,
            "verdict": self.verdict,
            "actor": self.actor,
            "allowed": self.is_allowed(),
            "required_authority": self.required_authority,
            "satisfied_authority": self.satisfied_authority,
            "requirement": self.requirement,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "evidence": list(self.evidence),
        }
        if self.refusal is not None:
            base.update({"rejected": True, "code": self.refusal.code,
                         "detail": self.refusal.detail})
        return base

    def to_mapping(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "project_id": self.project_id,
            "verdict": self.verdict,
            "actor": self.actor,
            "required_authority": self.required_authority,
            "satisfied_authority": self.satisfied_authority,
            "requirement": self.requirement,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "evidence": list(self.evidence),
            "conflicting_rows": list(self.conflicting_rows),
            "approval": (self.approval.to_mapping()
                         if self.approval is not None else None),
            "refusal": (self.refusal.to_mapping()
                        if self.refusal is not None else None),
        }


def _refuse(
    *,
    request: ActionRequest,
    policy: Policy,
    code: str,
    detail: str,
    requirement: str,
    required_authority: str = "",
    evidence: tuple[str, ...] = (),
    conflicting_rows: tuple[str, ...] = (),
    approval: ApprovalEvaluation | None = None,
) -> AuthorityVerdict:
    """Build a REFUSED verdict — always with a code and a non-empty detail."""
    if code not in GOVERNANCE_REFUSAL_CODES:
        raise GovernanceFormatError(
            f"refusal code {code!r} is not in the frozen vocabulary")
    refusal = GovernanceRefusal(
        code=code,
        detail=detail,
        requirement=requirement,
        action=request.action,
        actor=request.actor or request.operator_id,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        evidence=evidence,
    )
    return AuthorityVerdict(
        action=request.action,
        project_id=request.project_id,
        verdict=REFUSED,
        actor=request.actor or request.operator_id,
        required_authority=required_authority,
        requirement=requirement,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        evidence=evidence,
        conflicting_rows=conflicting_rows,
        approval=approval,
        refusal=refusal,
    )


def _malformed(request: ActionRequest, policy: Policy, detail: str,
               requirement: str = REQUIREMENT_REQUEST) -> AuthorityVerdict:
    return _refuse(request=request, policy=policy, code=MALFORMED_PAYLOAD,
                   detail=detail, requirement=requirement)


def _context_errors(context: Any) -> list[str]:
    """Every shape problem in a context, as readable strings (never a raise)."""
    problems: list[str] = []
    if context is None:
        return problems
    if not isinstance(context, EvidenceContext):
        return [
            (f"context must be an EvidenceContext, not "
             f"{type(context).__name__}")]
    credential = context.credential
    if credential is not None and not isinstance(credential, CredentialRow):
        problems.append(f"context.credential must be a CredentialRow or None, "
                        f"not {type(credential).__name__}")
    try:
        rows = tuple(context.decisions)
    except TypeError:
        return problems + [
            (f"context.decisions must be iterable, not "
             f"{type(context.decisions).__name__}")]
    bad = sorted({type(row).__name__ for row in rows
                  if not isinstance(row, DecisionRow)})
    if bad:
        problems.append(f"context.decisions must hold DecisionRow values; found "
                        f"{bad}")
    return problems


def evaluate_authority(
    request: ActionRequest | Mapping[str, Any],
    context: EvidenceContext | None = None,
    policy: Any = _NO_POLICY_SUPPLIED,
    **unexpected: Any,
) -> AuthorityVerdict:
    """Evaluate one action against the canonical policy and the recorded rows.

    Pure and deterministic: no clock, no store, no I/O, no model. The same
    request and the same rows — in any order — give the same verdict and the same
    `digest()`.

    **Total**: this function does not raise for any request shape. A `Mapping`
    request is parsed against the closed schema; a schema violation, a
    policy-owned check input, an unreadable row shape and a gap the row requires
    (scope, clock, actor, bound value) are each answered with refusal-as-data
    (`MALFORMED_PAYLOAD` plus the requirement it blocks), so a caller never has
    to catch to learn it was refused.

    The **canonical** document is bound here (R5-REATTACK E2, FIX-2): the public
    entry admits no substituted policy — the party who authors the matrix is the
    party whose act is evaluated, and choosing the matrix chooses every check
    input at once. A `policy` argument, positional or keyword (the shipped
    document included), is refused **as data** with `MALFORMED_PAYLOAD` naming
    `POLICY_SUBSTITUTION_DETAIL` — never a `TypeError`, never a silent ignore.
    Variant documents evaluate through the private seam `_evaluate_authority`.
    """
    if policy is not _NO_POLICY_SUPPLIED or unexpected:
        return _substituted_policy_verdict(request)
    return _evaluate_authority(request, context, GOVERNANCE_POLICY)


def _substituted_policy_verdict(request: Any) -> AuthorityVerdict:
    """The coded refusal for a `policy` handed to the public `evaluate_authority`."""
    action = project_id = ""
    if isinstance(request, ActionRequest):
        action, project_id = request.action, request.project_id
    elif isinstance(request, Mapping):
        action = str(request.get("action", ""))
        project_id = str(request.get("project_id", ""))
    return _malformed(
        ActionRequest(action=action, project_id=project_id),
        GOVERNANCE_POLICY,
        POLICY_SUBSTITUTION_DETAIL,
        requirement=REQUIREMENT_POLICY)


def _evaluate_authority(
    request: ActionRequest | Mapping[str, Any],
    context: EvidenceContext | None,
    policy: Policy,
) -> AuthorityVerdict:
    """The substitutable seam: the full evaluation against a *supplied* policy.

    Total as before — the parsing, the pre-validation and the backstop all live
    here, so a variant document behaves exactly like the canonical one. The
    public `evaluate_authority` binds the shipped document and refuses a
    substituted one as data. Reachable from the evaluation layer and the test
    harness only.
    """
    if isinstance(request, Mapping):
        mapping = dict(request)
        placeholder = ActionRequest(action=str(mapping.get("action", "")),
                                    project_id=str(mapping.get("project_id", "")))
        owned = sorted(set(mapping) & set(POLICY_OWNED_REQUEST_KEYS))
        if owned:
            return _malformed(
                placeholder, policy,
                f"check inputs are policy-owned: {owned} — which payload key a "
                f"check reads and the approval window are declared by policy "
                f"{policy.policy_id}/v{policy.version}, never by the request")
        try:
            typed = ActionRequest.from_mapping(mapping)
        except (GovernanceFormatError, ValueError, TypeError) as exc:
            return _malformed(placeholder, policy,
                              f"request schema violation: {exc}")
    else:
        typed = request
        if not isinstance(typed, ActionRequest):
            return _malformed(
                ActionRequest(action="", project_id=""), policy,
                f"a request must be an ActionRequest or a mapping, not "
                f"{type(typed).__name__}")

    try:
        return _evaluate(typed, context, policy)
    except (GovernanceFormatError, ValueError, TypeError, KeyError,
            AttributeError, IndexError) as exc:
        # The backstop, not the control: every gap above is pre-validated into a
        # precise refusal, and this keeps an unforeseen one from raising through
        # the loop (§2.4 "never raises through the loop"; red team P1-b).
        return _malformed(
            typed, policy,
            f"the evaluation could not read a declared input "
            f"({type(exc).__name__}): {exc}")


def _evaluate(typed: ActionRequest, context: Any,
              policy: Policy) -> AuthorityVerdict:
    """The evaluation proper — every gap coded, nothing raised."""
    # ── request shape (so no later read can fail) ──
    for name in REQUEST_STRING_FIELDS:
        value = getattr(typed, name, None)
        if not isinstance(value, str):
            return _malformed(typed, policy,
                              f"request.{name} must be a string, not "
                              f"{type(value).__name__}")
    if not typed.action:
        return _malformed(typed, policy,
                          "request.action must be a non-empty action name")
    if not typed.project_id:
        return _malformed(typed, policy,
                          "request.project_id must be a non-empty project id")
    if typed.now and not is_readable_timestamp(typed.now):
        return _malformed(
            typed, policy,
            f"request.now {typed.now!r} is not an ISO-8601 timestamp — an "
            f"approval window cannot be evaluated against an unreadable clock")
    problems = _context_errors(context)
    if problems:
        return _malformed(typed, policy,
                          "unreadable evidence context: " + "; ".join(problems))
    evidence_context = context if context is not None else EvidenceContext()

    resolved = _resolve(typed.action, policy)
    if not resolved.governed or resolved.row is None:
        return _refuse(
            request=typed, policy=policy, code=ROLE, requirement=REQUIREMENT_POLICY,
            detail=(f"action {typed.action!r} is governed by no row of policy "
                    f"{policy.policy_id}/v{policy.version} — no authority grants "
                    f"it (deny by default)"))
    row = resolved.row
    required = row.display

    if not resolved.allowed_by_policy:
        detail = (f"action {typed.action!r} is DENIED by policy "
                  f"{policy.policy_id}/v{policy.version} (row effect DENY)")
        if resolved.conflicts:
            detail += (" — conflicting rows: "
                       + ", ".join(resolved.conflicts))
        return _refuse(
            request=typed, policy=policy, code=row.refusal_code,
            requirement=REQUIREMENT_AUTHORITY, detail=detail,
            required_authority=required, conflicting_rows=resolved.conflicts)

    level = row.level
    decision_bearing = level.requires_recorded_decision

    # ── the recorded-decision levels (REVIEWER / HUMAN) ──
    if level.requires_operator_identity and not typed.operator_id:
        return _refuse(
            request=typed, policy=policy, code=row.refusal_code,
            requirement=REQUIREMENT_AUTHORITY,
            detail=(f"action {typed.action!r} requires {required} authority: "
                    f"operator authority is a recorded credential, and no "
                    f"operator id was presented (an agent holds no credential)"),
            required_authority=required)

    credential = evidence_context.credential
    unratified = (credential is None
                  or credential.operator_id != typed.operator_id)
    if level.requires_operator_identity and unratified:
        return _refuse(
            request=typed, policy=policy,
            code=row.credential_refusal_code or OPERATOR,
            requirement=REQUIREMENT_CREDENTIAL,
            detail=(f"no recorded operator credential for "
                    f"{typed.operator_id!r} — action {typed.action!r} "
                    f"requires {required} authority, and an unratified "
                    f"operator decides nothing"),
            required_authority=required,
            evidence=((credential.operator_id,) if credential else ()))

    # ── gaps the row requires, refused before any decision is read ──
    if decision_bearing and not typed.actor:
        return _malformed(
            typed, policy,
            f"action {typed.action!r} requires {required} authority: the request "
            f"names no actor, so independence between the requester and the "
            f"recorded decision cannot be established",
            requirement=REQUIREMENT_INDEPENDENCE)
    if row.restricted and not typed.target_ref:
        return _malformed(
            typed, policy,
            f"action {typed.action!r} is RESTRICTED: the act must declare the "
            f"target ref its approval binds at {row.target_key!r} (the key is "
            f"policy-owned), and no target ref was supplied",
            requirement=REQUIREMENT_TARGET)
    if decision_bearing and not typed.scope:
        return _malformed(
            typed, policy,
            f"action {typed.action!r} requires {required} authority: no approval "
            f"scope was declared (correlation_id or approval_scope), so the "
            f"recorded decision for this act cannot be located",
            requirement=REQUIREMENT_DECISION)
    if decision_bearing and row.window_seconds and not typed.now:
        return _malformed(
            typed, policy,
            f"action {typed.action!r} requires {required} authority with a "
            f"{row.window_seconds}s approval window declared by the policy row: "
            f"the request must declare `now`, otherwise the window cannot be "
            f"evaluated and the only staleness control would be off",
            requirement=REQUIREMENT_DECISION)
    if level.requires_bound_command and not typed.command_hash:
        return _malformed(
            typed, policy,
            f"action {typed.action!r} requires {required} authority: the act must "
            f"declare the command hash its approval binds at {row.binding_key!r} "
            f"(the key is policy-owned), and none was supplied",
            requirement=REQUIREMENT_BINDING)
    if row.head_key and not typed.head_ref:
        return _malformed(
            typed, policy,
            f"action {typed.action!r} requires {required} authority: the act must "
            f"declare the chain head it assumes at {row.head_key!r} (the key is "
            f"policy-owned), otherwise suppression of a superseded approval "
            f"cannot be detected",
            requirement=REQUIREMENT_HEAD)

    approval: ApprovalEvaluation | None = None
    evidence: tuple[str, ...] = (
        (credential.operator_id,) if credential is not None else ())
    if decision_bearing:
        approval = _evaluate_approval(
            ApprovalRequest(scope=typed.scope, project_id=typed.project_id,
                            now=typed.now, window_seconds=row.window_seconds,
                            policy_id=policy.policy_id,
                            policy_version=policy.version),
            evidence_context.decisions, policy)
        evidence += tuple(row.event_id for row in approval.rows)
        if not approval.approved or approval.decisive_row is None:
            refusal = approval.refusal
            if refusal is None:  # defensive: an unapproved state must refuse
                return _malformed(typed, policy,
                                  "the approval lifecycle returned an "
                                  "unapproved state without a refusal")
            return _refuse(
                request=typed, policy=policy, code=refusal.code,
                requirement=REQUIREMENT_DECISION, detail=refusal.detail,
                required_authority=required, evidence=evidence,
                approval=approval)
        decisive: DecisionRow = approval.decisive_row

        # ── independence: the recorded decider is not the requester ──
        decider = decisive.operator_id()
        if not decider:
            return _malformed(
                typed, policy,
                f"the decisive decision {decisive.event_id!r} carries no "
                f"operator_id, so it cannot be shown to be independent of the "
                f"requester — an unattributable approval authorizes nothing",
                requirement=REQUIREMENT_INDEPENDENCE)
        if decider == typed.actor:
            return _refuse(
                request=typed, policy=policy, code=ROLE,
                requirement=REQUIREMENT_INDEPENDENCE,
                detail=(f"actor {typed.actor!r} is the operator who decided "
                        f"{decisive.event_id!r}: an operator does not ratify "
                        f"their own act (independence is required)"),
                required_authority=required, evidence=evidence,
                approval=approval)

        if (level.requires_bound_command
                and not decisive.binds(row.binding_key, typed.command_hash)):
            return _refuse(
                request=typed, policy=policy,
                code=row.binding_refusal_code or STALE,
                requirement=REQUIREMENT_BINDING,
                detail=(f"the recorded decision {decisive.event_id!r} does "
                        f"not bind {row.binding_key}={typed.command_hash!r}"
                        f" — it does not ratify this command"),
                required_authority=required, evidence=evidence,
                approval=approval)

        bound_head = (decisive.payload.get(row.head_key) if row.head_key
                      else None)
        if (isinstance(bound_head, str) and bound_head
                and bound_head != typed.head_ref):
            return _refuse(
                request=typed, policy=policy,
                code=row.head_refusal_code or STALE,
                requirement=REQUIREMENT_HEAD,
                detail=(f"the recorded decision {decisive.event_id!r} binds "
                        f"head {bound_head!r}, not the requested head "
                        f"{typed.head_ref!r} — the approval is superseded"),
                required_authority=required, evidence=evidence,
                approval=approval)

        if row.restricted and not decisive.binds(row.target_key,
                                                 typed.target_ref):
            return _refuse(
                request=typed, policy=policy,
                code=row.binding_refusal_code or STALE,
                requirement=REQUIREMENT_TARGET,
                detail=(f"action {typed.action!r} is RESTRICTED: the recorded "
                        f"decision {decisive.event_id!r} must bind "
                        f"{row.target_key}={typed.target_ref!r}, and does not"),
                required_authority=required, evidence=evidence,
                approval=approval)

    if row.record_required and not typed.rationale.strip():
        return _refuse(
            request=typed, policy=policy,
            code=row.record_refusal_code or ROLE,
            requirement=REQUIREMENT_RECORD,
            detail=(f"action {typed.action!r} requires {required} authority and a "
                    f"record: no rationale was supplied, so the act carries no "
                    f"record to audit"),
            required_authority=required, evidence=evidence, approval=approval)

    return AuthorityVerdict(
        action=typed.action,
        project_id=typed.project_id,
        verdict=ALLOWED,
        actor=typed.actor or typed.operator_id,
        required_authority=required,
        satisfied_authority=required,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        evidence=evidence,
        approval=approval)


def emitted_refusal_codes(policy: Policy = GOVERNANCE_POLICY) -> frozenset[str]:
    """Every code this module can emit for `policy` — asserted ⊆ the frozen set.

    The plane's own two literals (`ROLE` for a partition violation and
    `MALFORMED_PAYLOAD` for a malformed request) plus every row's declared codes.
    A future row that names a code outside the frozen vocabulary fails the suite
    (and `PolicyRow.__post_init__` refuses it outright).
    """
    codes = {ROLE, MALFORMED_PAYLOAD}
    for row in policy.rows:
        for name in ("refusal_code", "credential_refusal_code",
                     "record_refusal_code", "binding_refusal_code",
                     "head_refusal_code"):
            code = getattr(row, name)
            if code:
                codes.add(code)
    return frozenset(codes)
