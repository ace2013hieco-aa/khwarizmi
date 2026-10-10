"""Governance — the approval lifecycle, derived from recorded journal rows (§2.5).

What this module is
-------------------
An approval in Hermes is not a table: it is a *recorded human decision* — a
`HumanDecisionReceived` journal row (`core/events.py:32`), idempotent per command
hash (`research/verdict_decisions.py:33`), appended by the spine inside the
gateway's transaction. This module derives the approval **lifecycle** from those
rows and nothing else:

    MISSING → PENDING → APPROVED
                     ↘ DENIED
    APPROVED → EXPIRED   (only when the row's window is non-zero and `now` is declared)

Derivation rules (all deterministic; the same rows in give the same verdict out)
--------------------------------------------------------------------------------
* **Scope** is the row's `correlation_id` — the repo's own command-hash /
  correlation key (`retract:sha256(...)`, `curate-decision-<hash>`, …). A row
  whose `project_id` differs is a *foreign project* row and is counted, never
  used. A row for the same project but another correlation is a *foreign scope*
  row and is counted, never used. Project isolation is therefore structural, not
  a filter the caller can forget. (The scope value itself is declared by the
  requester — a recorded design limit, see `authority`'s docstring, red team X1:
  this plane can only prove *containment*, since computing an act's correlation
  key needs repo knowledge.)
* **Order** is `(created_at, event_id)` ascending — the journal's own order. The
  input sequence of rows never matters, so a shuffled read returns the same
  verdict (pinned by a determinism fixture).
* **Decisive rows** are those whose verdict (`payload[verdict_key]`, default
  `"decision"`) is a member of the mirrored verdict vocabulary: `APPROVED` →
  approve; `DENIED` and the gate surface's `REJECTED`
  (`controller.resolve_human_gate`: "the verdict is APPROVED or REJECTED") →
  deny. Any other or missing verdict is *non-decisive*: it leaves the scope
  `PENDING`. There is no path from an unrecognised verdict to an approval.
* **Newest decisive row wins.** The journal enforces one verdict per correlation
  for its correlation-bearing event types (`persistence/migrations.py` 11→12), so
  a well-formed journal has at most one; when more exist the plane reports
  `decisive_count` and `repeated_decisions` as data rather than hiding them.
* **Expiry is declared, never read.** The plane reads no clock: the caller
  supplies `now` and the *window* the policy row declares (v2 — the window is
  policy data, `PolicyRow.window_seconds`, never a request field; the authority
  layer passes it down). `window_seconds == 0` or `now == ""` means no expiry is
  evaluated — and that is reported (`age_seconds`, `window_seconds`), so the
  absence of a window is visible in the verdict. A non-zero window with no `now`
  is refused by `authority` (the declaration is mandatory there), so expiry can
  no longer be switched off by omission.

The rows are evaluated **as given** (trust boundary)
-----------------------------------------------------
This module cannot tell a genuinely appended `HumanDecisionReceived` row from a
well-formed forgery: it holds no connection and performs no read. Resolving rows
from the journal, and proving they were recorded there, is the **enforcement
path's** act — today the human-gate spine, which writes and reads those rows
inside the gateway's transaction (§2.5 *Enforcement points*). The lifecycle below
is therefore an evaluation over *supplied* evidence, and it is exactly as
trustworthy as the row resolution that feeds it. Recorded as a documented limit
(red team P2 caveat), not papered over with a check this plane cannot perform.

Denials are data, never silent
------------------------------
Every state other than `APPROVED` carries a `GovernanceRefusal` whose code is a
member of the frozen vocabulary and whose meaning is unchanged:

  MISSING / PENDING → `PROPOSAL` (no bound recorded HumanDecision authorizes the
                      act; §2.1/:115)
  DENIED            → `PROPOSAL` (gateway.py:107: "already decided differently")
  EXPIRED           → `PROPOSAL` (the recorded decision is no longer the binding
                      decision for this act)

The frozen set has no expiry-specific code and this round may not introduce one
(§2.5 *Errors*), so a closed window refuses under the same "no currently bound
decision" code as a missing one, and the *state* plus the refusal `detail` carry
the distinction. `STALE` is deliberately **not** used here: it means a
chain-head/supersession violation, and this module has no chain-head concept —
the authority evaluation owns that check.

Evidence the plane cannot read is an integrity incident
-------------------------------------------------------
A row mapping with unknown/missing keys, or a `created_at` that is not an ISO-8601
timestamp, raises `GovernanceFormatError` rather than being guessed at — the same
discipline the runtime plane applies to a corrupt checkpoint. A *request* the
plane cannot interpret is the caller's schema problem and is answered with a
refusal-as-data by `authority.evaluate_authority`, never here; that layer also
pre-validates `now` and the context shape, so its evaluation stays total.

Import direction: `hermes.governance.policy` + standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from hermes.governance.policy import (
    GOVERNANCE_POLICY,
    GOVERNANCE_REFUSAL_CODES,
    MALFORMED_PAYLOAD,
    POLICY_SUBSTITUTION_DETAIL,
    PROPOSAL,
    REQUIREMENT_DECISION,
    REQUIREMENT_POLICY,
    GovernanceFormatError,
    GovernanceRefusal,
    Policy,
    digest_of,
)

# ── lifecycle states (this plane's own derived vocabulary, not journal states) ──

MISSING = "MISSING"
PENDING = "PENDING"
APPROVED = "APPROVED"
DENIED = "DENIED"
EXPIRED = "EXPIRED"

STATES: tuple[str, ...] = (MISSING, PENDING, APPROVED, DENIED, EXPIRED)

# ── mirrored verdict vocabulary (no synonym is invented) ──

APPROVE_VERDICTS: frozenset[str] = frozenset({"APPROVED"})
#: `DENIED` is an approval payload's verdict; `REJECTED` is the gate surface's
#: word for the same judgment (`controller.resolve_human_gate`).
DENY_VERDICTS: frozenset[str] = frozenset({"DENIED", "REJECTED"})

#: The state→refusal-code mapping. Every member is an existing code with its
#: frozen meaning; the mapping is data so a reader can audit it in one place.
#: `APPROVED` is absent by construction — an approved state refuses nothing.
STATE_REFUSAL_CODES: Mapping[str, str] = MappingProxyType({
    MISSING: PROPOSAL,
    PENDING: PROPOSAL,
    DENIED: PROPOSAL,
    EXPIRED: PROPOSAL,
})

#: The payload key a decision row's verdict is read from when the caller does not
#: declare one. (`HumanDecisionReceived` payloads in the repo carry
#: `"decision"` — e.g. `controller.record_curation_decision`.)
DEFAULT_VERDICT_KEY = "decision"

#: The key the approving operator is read from, when present.
OPERATOR_KEY = "operator_id"

#: Sentinel for "no `policy` argument was supplied" at the public
#: `evaluate_approval`. Any `policy` it receives — the shipped document included
#: — is refused as data (R5-REATTACK E2, FIX-2): the canonical document is bound
#: internally, and the substitutable seam is the private `_evaluate_approval`.
_NO_POLICY_SUPPLIED: Any = object()


@dataclass(frozen=True, slots=True)
class DecisionRow:
    """One `HumanDecisionReceived` event row, as READ from the journal.

    The snapshot mirrors the recorded columns this plane consumes
    (`events.event_id/project_id/correlation_id/caused_by/reason/payload_json/
    created_at`). It carries no connection and no cursor: the caller owns the
    read, and `from_mapping` is a closed schema, so a row with unknown keys is
    refused rather than partially believed.
    """

    event_id: str
    project_id: str
    correlation_id: str = ""
    caused_by: str = ""
    reason: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def verdict(self, key: str = DEFAULT_VERDICT_KEY) -> str:
        """The row's recorded verdict, `""` when it carries none."""
        value = self.payload.get(key)
        return value if isinstance(value, str) else ""

    def operator_id(self) -> str:
        value = self.payload.get(OPERATOR_KEY)
        return value if isinstance(value, str) else ""

    def binds(self, key: str, value: str) -> bool:
        """True when this row's payload binds `key` to exactly `value`.

        The repo's binding discipline, read-only: the gateway compares a recorded
        decision's `curation_id` / `classification_hash` / `resolution_id`
        against a recomputed command hash and refuses when they differ
        (`gateway.py:2048-2055`). A declared `key` the row simply does not carry
        is *not* a binding.
        """
        if not key or not value:
            return False
        return self.payload.get(key) == value

    def to_mapping(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "project_id": self.project_id,
            "correlation_id": self.correlation_id,
            "caused_by": self.caused_by,
            "reason": self.reason,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DecisionRow":
        unknown = sorted(set(data) - {
            "event_id", "project_id", "correlation_id", "caused_by", "reason",
            "payload", "created_at"})
        if unknown:
            raise GovernanceFormatError(f"unknown DecisionRow keys: {unknown}")
        missing = [key for key in ("event_id", "project_id") if not data.get(key)]
        if missing:
            raise GovernanceFormatError(f"missing DecisionRow keys: {missing}")
        payload = data.get("payload") or {}
        if not isinstance(payload, Mapping):
            raise GovernanceFormatError("DecisionRow.payload must be a mapping")
        return cls(
            event_id=str(data["event_id"]),
            project_id=str(data["project_id"]),
            correlation_id=str(data.get("correlation_id", "")),
            caused_by=str(data.get("caused_by", "")),
            reason=str(data.get("reason", "")),
            payload=dict(payload),
            created_at=str(data.get("created_at", "")),
        )


def is_readable_timestamp(value: str) -> bool:
    """True when `value` is an ISO-8601 timestamp this plane can read.

    The predicate `authority` uses to pre-validate a *request's* `now` before the
    lifecycle below is invoked, so a malformed clock becomes refusal-as-data
    there. Integrity incidents *inside recorded rows* still raise here (see the
    module docstring): a row the journal could not have produced is not a
    request-shape problem.
    """
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _parse_timestamp(value: str, what: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GovernanceFormatError(
            f"{what} {value!r} is not an ISO-8601 timestamp: {exc}") from exc


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """What the caller asks the lifecycle about — one scope in one project.

    `now` is the caller's clock declaration (a string, so the caller's clock
    stays the only clock). `window_seconds` is the freshness window — in
    production it is passed down from the governing policy row (v2: policy data,
    never a request field); the default `0` is the explicit opt-in meaning "no
    expiry is evaluated".
    """

    scope: str
    project_id: str
    now: str = ""
    window_seconds: int = 0
    verdict_key: str = DEFAULT_VERDICT_KEY
    policy_id: str = ""
    policy_version: int = 0

    def to_mapping(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "project_id": self.project_id,
            "now": self.now,
            "window_seconds": self.window_seconds,
            "verdict_key": self.verdict_key,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, slots=True)
class ApprovalEvaluation:
    """The derived lifecycle of one approval scope.

    Every count is evidence, not decoration: `foreign_project_rows`,
    `foreign_scope_rows`, `non_decisive_rows`, `decisive_count` and
    `window_seconds` make what the plane did *not* count as an approval visible,
    and `refusal` is present for every state except `APPROVED` (denials are data,
    never silent).
    """

    scope: str
    project_id: str
    state: str
    rows: tuple[DecisionRow, ...] = ()
    decisive_row: DecisionRow | None = None
    decisive_count: int = 0
    denial_count: int = 0
    non_decisive_rows: int = 0
    foreign_scope_rows: int = 0
    foreign_project_rows: int = 0
    age_seconds: int | None = None
    window_seconds: int = 0
    policy_id: str = ""
    policy_version: int = 0
    refusal: GovernanceRefusal | None = None

    @property
    def approved(self) -> bool:
        return self.state == APPROVED

    @property
    def repeated_decisions(self) -> bool:
        """True when the journal holds more than one decisive row for the scope.

        The journal's one-verdict-per-correlation index (`migrations.py` 11→12)
        means a well-formed journal never does; surfacing it keeps a tampered or
        hand-written journal from passing unnoticed.
        """
        return self.decisive_count > 1

    @property
    def approver_operator_id(self) -> str:
        if self.decisive_row is None:
            return ""
        return self.decisive_row.operator_id()

    def digest(self) -> str:
        """Deterministic digest of the verdict — the determinism fixture's unit."""
        return digest_of(self.to_mapping())

    def to_mapping(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "project_id": self.project_id,
            "state": self.state,
            "rows": [row.to_mapping() for row in self.rows],
            "decisive_row": (self.decisive_row.to_mapping()
                             if self.decisive_row is not None else None),
            "decisive_count": self.decisive_count,
            "denial_count": self.denial_count,
            "non_decisive_rows": self.non_decisive_rows,
            "foreign_scope_rows": self.foreign_scope_rows,
            "foreign_project_rows": self.foreign_project_rows,
            "age_seconds": self.age_seconds,
            "window_seconds": self.window_seconds,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "refusal": (self.refusal.to_mapping()
                        if self.refusal is not None else None),
        }


def _state_refusal(state: str, *, scope: str, evaluation: "ApprovalEvaluation",
                   policy_id: str, policy_version: int) -> GovernanceRefusal:
    """The refusal for a non-approved state — code from the frozen mapping."""
    code = STATE_REFUSAL_CODES[state]
    decisive = evaluation.decisive_row
    evidence = tuple(row.event_id for row in evaluation.rows)
    if state == MISSING:
        detail = (f"no recorded HumanDecision for approval scope {scope!r} in "
                  f"project {evaluation.project_id!r}: the act is not authorized "
                  f"(PROPOSAL: no bound recorded HumanDecision)")
    elif state == PENDING:
        detail = (f"approval scope {scope!r} has {evaluation.non_decisive_rows} "
                  f"recorded decision row(s) and no decisive verdict yet: the act "
                  f"is not authorized while the decision is pending (PROPOSAL: no "
                  f"bound recorded HumanDecision)")
    elif state == DENIED:
        who = (decisive.operator_id() if decisive is not None else "") or "an operator"
        why = (decisive.reason if decisive is not None else "") or "no reason recorded"
        detail = (f"approval scope {scope!r} was DENIED by {who} "
                  f"(reason: {why}) — the recorded decision does not authorize this "
                  f"act (PROPOSAL: already decided differently)")
    else:  # EXPIRED
        detail = (f"approval scope {scope!r} expired: age {evaluation.age_seconds}s "
                  f"exceeds the declared window {evaluation.window_seconds}s, so the "
                  f"recorded decision is no longer the binding decision for this act "
                  f"(PROPOSAL: no bound recorded HumanDecision)")
    return GovernanceRefusal(
        code=code,
        detail=detail,
        requirement=REQUIREMENT_DECISION,
        actor=(decisive.operator_id() if decisive is not None else ""),
        policy_id=policy_id,
        policy_version=policy_version,
        evidence=evidence,
    )


def evaluate_approval(
    request: ApprovalRequest,
    decisions: tuple[DecisionRow, ...] = (),
    policy: Any = _NO_POLICY_SUPPLIED,
    **unexpected: Any,
) -> ApprovalEvaluation:
    """Derive one approval scope's lifecycle from recorded rows (canonical policy).

    Pure and deterministic: no clock, no store, no I/O. The same rows in — in any
    order — give the same evaluation and the same `digest()`.

    Integrity incidents raise here (a malformed `now`/`created_at`, an empty
    scope, a negative window): a *direct* caller of this module is handing the
    plane evidence, and unreadable evidence is never guessed at. The request
    surface is `authority.evaluate_authority`, which pre-validates these inputs
    and answers with refusal-as-data instead.

    The **canonical** document is bound here (R5-REATTACK E2, FIX-2): the public
    entry admits no substituted policy. A `policy` argument — positional or
    keyword, the shipped document included — is refused as data, never raised and
    never ignored: an evaluation that denies by default (`state` MISSING,
    `approved` False) and carries a `MALFORMED_PAYLOAD` refusal naming
    `POLICY_SUBSTITUTION_DETAIL`. Variant documents evaluate through the private
    seam `_evaluate_approval`.
    """
    if policy is not _NO_POLICY_SUPPLIED or unexpected:
        return _substituted_policy_evaluation(request)
    return _evaluate_approval(request, decisions, GOVERNANCE_POLICY)


def _substituted_policy_evaluation(request: Any) -> ApprovalEvaluation:
    """The coded denial for a `policy` handed to the public `evaluate_approval`."""
    scope = project_id = ""
    if isinstance(request, ApprovalRequest):
        scope, project_id = request.scope, request.project_id
    return ApprovalEvaluation(
        scope=scope,
        project_id=project_id,
        state=MISSING,
        policy_id=GOVERNANCE_POLICY.policy_id,
        policy_version=GOVERNANCE_POLICY.version,
        refusal=GovernanceRefusal(
            code=MALFORMED_PAYLOAD,
            detail=POLICY_SUBSTITUTION_DETAIL,
            requirement=REQUIREMENT_POLICY,
            policy_id=GOVERNANCE_POLICY.policy_id,
            policy_version=GOVERNANCE_POLICY.version))


def _evaluate_approval(
    request: ApprovalRequest,
    decisions: tuple[DecisionRow, ...],
    policy: Policy,
) -> ApprovalEvaluation:
    """The substitutable seam: one scope's lifecycle against a *supplied* policy.

    Integrity incidents raise here as before (see the public entry); the public
    `evaluate_approval` binds the shipped document and refuses a substituted one
    as data. The evaluation layer calls this seam with the governing row's
    document.
    """
    if not request.scope or not request.project_id:
        raise GovernanceFormatError(
            "an ApprovalRequest needs a non-empty scope and project_id")
    if request.window_seconds < 0:
        raise GovernanceFormatError("window_seconds must not be negative")
    policy_id = request.policy_id or policy.policy_id
    policy_version = request.policy_version or policy.version

    in_project = [row for row in decisions
                  if row.project_id == request.project_id]
    foreign_project_rows = len(decisions) - len(in_project)
    matching = [row for row in in_project if row.correlation_id == request.scope]
    foreign_scope_rows = len(in_project) - len(matching)
    ordered = tuple(sorted(matching, key=lambda row: (row.created_at, row.event_id)))

    decisive_rows = [
        row for row in ordered
        if row.verdict(request.verdict_key) in (APPROVE_VERDICTS | DENY_VERDICTS)
    ]
    decisive = decisive_rows[-1] if decisive_rows else None
    denial_count = sum(1 for row in decisive_rows
                       if row.verdict(request.verdict_key) in DENY_VERDICTS)

    evaluation = ApprovalEvaluation(
        scope=request.scope,
        project_id=request.project_id,
        state=MISSING,
        rows=ordered,
        decisive_row=decisive,
        decisive_count=len(decisive_rows),
        denial_count=denial_count,
        non_decisive_rows=len(ordered) - len(decisive_rows),
        foreign_scope_rows=foreign_scope_rows,
        foreign_project_rows=foreign_project_rows,
        window_seconds=request.window_seconds,
        policy_id=policy_id,
        policy_version=policy_version,
    )

    if not ordered:
        state = MISSING
    elif decisive is None:
        state = PENDING
    elif decisive.verdict(request.verdict_key) in DENY_VERDICTS:
        state = DENIED
    elif request.now and request.window_seconds > 0:
        now = _parse_timestamp(request.now, "ApprovalRequest.now")
        decided = _parse_timestamp(
            decisive.created_at,
            f"decision row {decisive.event_id!r} created_at")
        age = int((now - decided).total_seconds())
        evaluation = replace(evaluation, age_seconds=age)
        state = EXPIRED if age > request.window_seconds else APPROVED
    else:
        state = APPROVED

    if state == APPROVED:
        return replace(evaluation, state=state)
    return replace(
        evaluation,
        state=state,
        refusal=_state_refusal(state, scope=request.scope, evaluation=evaluation,
                               policy_id=policy_id,
                               policy_version=policy_version))


def emitted_refusal_codes() -> frozenset[str]:
    """The codes this module can emit — asserted ⊆ the frozen vocabulary.

    A convenience for the suite and for a future audit: the module's own code set
    must never grow beyond `GOVERNANCE_REFUSAL_CODES`.
    """
    return frozenset(
        code for code in STATE_REFUSAL_CODES.values()
        if code in GOVERNANCE_REFUSAL_CODES)
