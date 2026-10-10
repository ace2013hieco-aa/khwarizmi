"""Governance — the action→authority matrix, as versioned DATA (§2.5).

What this module is
-------------------
The Governance control plane owns the *authority vocabulary*, the *refusal
vocabulary and its FROZEN meanings* (§2.5 *Owns*). This module carries that
ownership as data: a versioned, immutable `Policy` whose rows answer exactly one
question — for this **action**, which **authority** does the action require,
which **checks** must a recorded decision satisfy, and which refusal code follows
when any of that is absent?

Nothing here enforces anything. There is no checker, no interceptor and no
second validator: the spine's enforcement chain (§2.5 *Enforcement points*) is
untouched, and this module cannot bypass or reimplement any of it because it
cannot write, read or reach outside the process.

The default-authority table (provenance of every row)
-----------------------------------------------------
The nine governed actions and their default authority levels are the brief's
default-authority table handed to this round (ARCHITECTURE_DELTA §2.5):

    web-search / read / sandbox-run   → AGENT
    hypothesis-modify                 → AGENT+RECORD
    contradiction-declare / evidence-delete → REVIEWER/RESTRICTED
    direction-change / publish / external   → HUMAN

No level, action or code is invented here. The three authority levels are the
ones the brief names; `RESTRICTED` is a flag on the row (the approval must bind
the *specific target*, not merely the action class), not a fourth level. Every
refusal code is mirrored from the certified vocabulary — the gateway's named
constants (`research/gateway.py:94-109`) plus the controller's inline literals;
the test suite re-derives the provenance from those source files so drift fails
the build. **No new refusal code and no meaning change** (§2.5 *Errors*;
`docs/API.md`).

v2 — check inputs are POLICY-OWNED (R5 red team P1-a, P2 expiry/head)
--------------------------------------------------------------------
Version 1 let the *request* name the payload keys its own approval checks should
read (`binding_key`, `target_key`) and the approval window
(`window_seconds`). A caller could therefore choose which field satisfied a
control — binding a decision row's own verdict verb as a "command hash"
(`command_hash='APPROVED'`, `binding_key='decision'`) or a free-text note as an
"evidence target" (`target_ref=<note>`, `target_key='rationale'`) — and either
`HUMAN` or `REVIEWER/RESTRICTED` authority followed with nothing bound.

Version 2 moves every check input into the row, where the policy — not the party
being checked — decides what must be bound:

  `binding_key`     the payload key a `HUMAN` row requires the recorded decision
                    to bind the command hash at (`""` = the row binds no command)
  `target_key`      the payload key a `RESTRICTED` row requires the recorded
                    decision to bind the requested target at (`""` = no target
                    check; `RESTRICTED` requires it, non-`RESTRICTED` forbids it)
  `head_key`        the payload key the recorded decision binds the chain head at
                    (`""` = the row has no head requirement)
  `window_seconds`  the approval freshness window in seconds; **`0` is the
                    explicit opt-in meaning "no expiry is evaluated"** and is the
                    constructor default. A row that declares a non-zero window
                    makes the clock declaration (`now`) mandatory, so a caller
                    cannot switch the only staleness control off by omission.

`MAX_APPROVAL_WINDOW_SECONDS` bounds the window (a row outside `[0, MAX]` is
refused at construction). A request that still supplies `binding_key`,
`target_key` or `window_seconds` is refused `MALFORMED_PAYLOAD`
("check inputs are policy-owned") — see `hermes.governance.authority`.

The values the checks compare against (`command_hash`, `target_ref`, `head_ref`)
stay in the request: they describe *the act*, not the control.

Refusal-code meanings used here (frozen; quoted from the sources)
-----------------------------------------------------------------
  ROLE               gateway.py:94  — "proposed_by not permitted for this kind".
                     Used for a partition violation: an actor without the
                     authority the row requires, an agent claiming a human
                     surface, an action no policy row governs (deny by default),
                     and a self-approved act (the requester acting as its own
                     authority — §2.1 "any profile acting as an authority").
  OPERATOR           gateway.py:109 — "operator credential is not ratified (A4)".
                     Used when an operator identity is presented but the
                     recorded credential for it does not exist.
  PROPOSAL           gateway.py:107 — "proposal not found / not pending / already
                     decided differently"; §2.1/:115 — a verdict-shaped act with
                     no *bound* recorded HumanDecision. Used for a missing,
                     pending, denied or non-binding recorded decision.
  STALE              gateway.py:101 — "supersession/chain-head violation". Used
                     when a recorded approval binds a superseded head.
  RATIONALE          controller.py (inline) — missing/oversized rationale. Used
                     when a row requires a record and the act carries none.
  MALFORMED_PAYLOAD  gateway.py:98 — schema violation or unknown key. Used when
                     the request cannot supply what the row declares (a missing
                     scope, clock, bound value or actor; a policy-owned check
                     input; an unreadable row shape).

Deny-wins
---------
A `Policy` may hold several rows for one action (a versioned document can carry a
permit and a denial). `resolve()` applies **deny-wins**: any DENY row governs,
whatever PERMIT rows exist beside it, and the resolution names every conflicting
row so the refusal is never silent.

The canonical document is bound at the public surface (R5-REATTACK E2, FIX-2)
-----------------------------------------------------------------------------
`resolve(action)` answers for the **shipped** document only. A caller cannot
hand it another matrix: the party who authors the matrix is the same party whose
act is being resolved, and a check whose subject selects the document it is
checked against is not a check — the same standard v2 applied to the request's
check inputs, applied one level up. The substitutable seam survives as
`_resolve(action, policy)`, reachable only from the evaluation layer and the
test harness. A `policy` argument handed to the public `resolve` (positional or
keyword, the shipped document included) is refused **as data** — a resolution
that denies by default and carries a `MALFORMED_PAYLOAD` refusal — so a
wiring-time misconfiguration is visible instead of silently honoured.

Import direction (§3.1): standard library only. This module imports no `hermes.*`
module — not `core`, not `research`, not `persistence` — so it cannot hold a
connection, open a transaction, append a journal row or read a clock.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

# ═══════════════════ the refusal vocabulary (mirrored, never extended) ═══════

ROLE = "ROLE"
OPERATOR = "OPERATOR"
PROPOSAL = "PROPOSAL"
STALE = "STALE"
MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"
RATIONALE = "RATIONALE"

#: Codes `research/gateway.py` declares as named constants.
GATEWAY_DEFINED_CODES: frozenset[str] = frozenset(
    {ROLE, OPERATOR, PROPOSAL, STALE, MALFORMED_PAYLOAD})
#: Codes `research/controller.py` emits as inline string literals.
CONTROLLER_EMITTED_CODES: frozenset[str] = frozenset({RATIONALE})
#: The complete set this plane may emit. No member is invented here; the suite
#: re-derives both halves from the two source files.
GOVERNANCE_REFUSAL_CODES: frozenset[str] = (
    GATEWAY_DEFINED_CODES | CONTROLLER_EMITTED_CODES)

# ═══════════════════ the closed requirement vocabulary ═══════════════════
#
# A refusal always names *which* requirement was unsatisfied. These are the
# plane's own diagnostic names (derived working vocabulary, like the runtime
# plane's TRACE_KINDS) — not refusal codes, not events, not intent kinds.

REQUIREMENT_POLICY = "NO_POLICY"
REQUIREMENT_REQUEST = "REQUEST"
REQUIREMENT_AUTHORITY = "AUTHORITY"
REQUIREMENT_CREDENTIAL = "CREDENTIAL"
REQUIREMENT_DECISION = "RECORDED_DECISION"
REQUIREMENT_INDEPENDENCE = "INDEPENDENCE"
REQUIREMENT_BINDING = "COMMAND_BINDING"
REQUIREMENT_HEAD = "HEAD_SUPERSESSION"
REQUIREMENT_RECORD = "RECORD"
REQUIREMENT_TARGET = "TARGET_BINDING"

REQUIREMENTS: tuple[str, ...] = (
    REQUIREMENT_POLICY,
    REQUIREMENT_REQUEST,
    REQUIREMENT_AUTHORITY,
    REQUIREMENT_CREDENTIAL,
    REQUIREMENT_DECISION,
    REQUIREMENT_INDEPENDENCE,
    REQUIREMENT_BINDING,
    REQUIREMENT_HEAD,
    REQUIREMENT_RECORD,
    REQUIREMENT_TARGET,
)

# ═══════════════════ actions, levels, effects ═══════════════════

WEB_SEARCH = "WEB_SEARCH"
WEB_READ = "WEB_READ"
SANDBOX_RUN = "SANDBOX_RUN"
HYPOTHESIS_MODIFY = "HYPOTHESIS_MODIFY"
CONTRADICTION_DECLARE = "CONTRADICTION_DECLARE"
EVIDENCE_DELETE = "EVIDENCE_DELETE"
DIRECTION_CHANGE = "DIRECTION_CHANGE"
PUBLISH = "PUBLISH"
EXTERNAL = "EXTERNAL"

#: The governed action vocabulary. These names are this plane's own — the suite
#: asserts none of them is an `IntentKind` or an `EventType` value, i.e. the
#: matrix adds no intent kind and no event.
ACTIONS: tuple[str, ...] = (
    WEB_SEARCH,
    WEB_READ,
    SANDBOX_RUN,
    HYPOTHESIS_MODIFY,
    CONTRADICTION_DECLARE,
    EVIDENCE_DELETE,
    DIRECTION_CHANGE,
    PUBLISH,
    EXTERNAL,
)

PERMIT = "PERMIT"
DENY = "DENY"
EFFECTS: tuple[str, ...] = (PERMIT, DENY)

# ═══════════════════ policy-owned check inputs (v2) ═══════════════════

#: The payload keys the shipped policy binds for `HUMAN` actions. Policy data,
#: never a request field (v2).
PUBLISH_BINDING_KEY = "publish_hash"
DIRECTION_BINDING_KEY = "direction_hash"
EXTERNAL_BINDING_KEY = "external_hash"
#: The payload key a `RESTRICTED` row binds its target at.
EVIDENCE_TARGET_KEY = "target_ref"
#: The payload key a row with a head requirement binds the chain head at.
HEAD_KEY = "head_ref"

#: The shipped default window for a row whose authority is a recorded decision
#: (one day). `0` would mean "no expiry is evaluated" (the constructor default).
DEFAULT_APPROVAL_WINDOW_SECONDS = 24 * 60 * 60
#: The declared upper bound on a row's window (one week). A row outside
#: `[0, MAX_APPROVAL_WINDOW_SECONDS]` is refused at construction.
MAX_APPROVAL_WINDOW_SECONDS = 7 * 24 * 60 * 60

# ═══════════════════ the canonical-policy rule (R5-REATTACK E2, FIX-2) ═══════

#: Sentinel for "no `policy` argument was supplied" at a public entry. A public
#: evaluation entry binds `GOVERNANCE_POLICY` internally; any `policy` it
#: receives — the shipped document included — is a wiring error, not a call.
_NO_POLICY_SUPPLIED: Any = object()

#: The one detail a substituted-policy refusal carries, wherever a public entry
#: refuses a caller-supplied `policy`. Frozen text, so the code and the reason it
#: is emitted are asserted together and cannot drift apart.
POLICY_SUBSTITUTION_DETAIL = (
    "policy is canonical; the evaluation admits no substituted policy")


class AuthorityLevel(str, Enum):
    """The authority an action requires — the brief's levels, verbatim.

    `AGENT+RECORD` is `AGENT_RECORD`; `REVIEWER/RESTRICTED` is `REVIEWER` plus
    the row's `restricted` flag (so there are exactly three levels plus one
    modifier, not a fourth level).
    """

    AGENT = "AGENT"
    AGENT_RECORD = "AGENT+RECORD"
    REVIEWER = "REVIEWER"
    HUMAN = "HUMAN"

    @property
    def requires_operator_identity(self) -> bool:
        """True for the levels a *human* must supply (reviewer and above)."""
        return self in (AuthorityLevel.REVIEWER, AuthorityLevel.HUMAN)

    @property
    def requires_recorded_decision(self) -> bool:
        """True for the levels whose authority is a recorded human decision.

        Such a row's decisive decision must also be *independent* of the
        requester (the requester may not act as its own authority) — see
        `hermes.governance.authority`.
        """
        return self in (AuthorityLevel.REVIEWER, AuthorityLevel.HUMAN)

    @property
    def requires_bound_command(self) -> bool:
        """True for the levels that must bind the exact command, not the class.

        `HUMAN` binds the deterministic command hash (the human ratified *this*
        act) at the row's `binding_key`; `REVIEWER` needs a recorded decision for
        the act's scope but not a command-hash binding — the gateway's own
        reviewer surfaces dereference a recorded decision, while the
        curation/classification/contradiction validators additionally compare a
        command hash (`gateway.py:2048-2055`, `:3268-3272`, `:2998-3002`). This
        is where the plane draws the line between the two levels.
        """
        return self is AuthorityLevel.HUMAN


# ═══════════════════ values ═══════════════════


def canonical_json(value: Any) -> str:
    """Deterministic JSON for digests and equivalence checks.

    Local on purpose (§3.3 discipline): importing `research.programs` for its
    canonicaliser would drag the research layer into the control plane; the two
    must agree only on *determinism*, not on an implementation.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def digest_of(value: Any) -> str:
    """SHA-256 over the canonical encoding."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _field_names(cls: Any) -> tuple[str, ...]:
    return tuple(item.name for item in dataclasses.fields(cls))


def _unknown_keys(data: Mapping[str, Any], cls: Any, what: str) -> None:
    unknown = sorted(set(data) - set(_field_names(cls)))
    if unknown:
        raise GovernanceFormatError(f"unknown {what} keys: {unknown}")


class GovernanceFormatError(ValueError):
    """A policy/row/refusal mapping could not be read (closed schema).

    Raised, never swallowed: a mapping the plane cannot read is not a verdict it
    may guess at. Note the split `hermes.governance.authority` keeps: *evidence*
    the plane cannot read is an integrity incident (this error, for direct
    callers of this module and of `approvals`), while a *request* the plane
    cannot interpret is answered with refusal-as-data — `evaluate_authority`
    never raises to its caller (R5 red team P1-b).
    """


@dataclass(frozen=True, slots=True)
class GovernanceRefusal:
    """Refusal-as-data: `{"rejected": True, "code", "detail"}` (§2.4 shape).

    `code` is always a member of `GOVERNANCE_REFUSAL_CODES`; `detail` is always
    non-empty (a refusal is never silent); `requirement` names which check
    failed; `evidence` lists the rows the evaluation read (decision event ids,
    operator ids) so a refusal can be audited back to what it saw.
    """

    code: str
    detail: str
    requirement: str = ""
    action: str = ""
    actor: str = ""
    policy_id: str = ""
    policy_version: int = 0
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """The shape §2.4 gives gateway refusals."""
        return {"rejected": True, "code": self.code, "detail": self.detail}

    def to_mapping(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": self.detail,
            "requirement": self.requirement,
            "action": self.action,
            "actor": self.actor,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "evidence": list(self.evidence),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "GovernanceRefusal":
        _unknown_keys(data, cls, "GovernanceRefusal")
        code = str(data.get("code", ""))
        if code not in GOVERNANCE_REFUSAL_CODES:
            raise GovernanceFormatError(
                f"refusal code {code!r} is not in the frozen vocabulary "
                f"{sorted(GOVERNANCE_REFUSAL_CODES)}")
        detail = str(data.get("detail", ""))
        if not detail.strip():
            raise GovernanceFormatError("a refusal must carry a non-empty detail")
        return cls(
            code=code,
            detail=detail,
            requirement=str(data.get("requirement", "")),
            action=str(data.get("action", "")),
            actor=str(data.get("actor", "")),
            policy_id=str(data.get("policy_id", "")),
            policy_version=int(data.get("policy_version", 0)),
            evidence=tuple(str(item) for item in (data.get("evidence") or ())),
        )


@dataclass(frozen=True, slots=True)
class PolicyRow:
    """One row of the action→authority matrix.

    A row is data: `authority` (the level), `restricted` (the REVIEWER/RESTRICTED
    modifier), `record_required` (the act must carry a record), `effect`
    (PERMIT/DENY), the **check inputs** the row declares (`binding_key`,
    `target_key`, `head_key`, `window_seconds` — v2: policy-owned, never
    request-supplied) and the refusal codes the evaluation emits when one of the
    authorities is missing. `refusal_code` is the row's primary code — what an
    actor receives when it simply does not hold the authority the row requires.
    """

    action: str
    authority: str
    refusal_code: str
    effect: str = PERMIT
    restricted: bool = False
    record_required: bool = False
    credential_refusal_code: str = ""
    record_refusal_code: str = ""
    binding_refusal_code: str = ""
    head_refusal_code: str = ""
    binding_key: str = ""
    target_key: str = ""
    head_key: str = ""
    window_seconds: int = 0
    note: str = ""

    def __post_init__(self) -> None:
        if self.effect not in EFFECTS:
            raise GovernanceFormatError(f"unknown effect {self.effect!r}")
        if self.authority not in {level.value for level in AuthorityLevel}:
            raise GovernanceFormatError(f"unknown authority {self.authority!r}")
        for name in ("refusal_code", "credential_refusal_code",
                     "record_refusal_code", "binding_refusal_code",
                     "head_refusal_code"):
            code = getattr(self, name)
            if code and code not in GOVERNANCE_REFUSAL_CODES:
                raise GovernanceFormatError(
                    f"{self.action}: {name} {code!r} is not in the frozen "
                    f"vocabulary")
        if not self.refusal_code:
            raise GovernanceFormatError(f"{self.action}: a refusal code is required")
        if self.restricted and self.authority not in {
                AuthorityLevel.REVIEWER.value, AuthorityLevel.HUMAN.value}:
            raise GovernanceFormatError(
                f"{self.action}: RESTRICTED requires a recorded decision "
                f"(REVIEWER or HUMAN authority)")
        if self.authority in {AuthorityLevel.REVIEWER.value,
                              AuthorityLevel.HUMAN.value}:
            if not self.credential_refusal_code:
                raise GovernanceFormatError(
                    f"{self.action}: operator authority needs a credential "
                    f"refusal code")
            if not self.record_refusal_code:
                raise GovernanceFormatError(
                    f"{self.action}: operator authority needs a record refusal "
                    f"code")
        # ── the v2 check inputs, validated as data ──
        if not 0 <= self.window_seconds <= MAX_APPROVAL_WINDOW_SECONDS:
            raise GovernanceFormatError(
                f"{self.action}: window_seconds {self.window_seconds} is outside "
                f"[0, {MAX_APPROVAL_WINDOW_SECONDS}]")
        if self.restricted and not self.target_key:
            raise GovernanceFormatError(
                f"{self.action}: RESTRICTED must declare the target_key its "
                f"approval binds")
        if self.target_key and not self.restricted:
            raise GovernanceFormatError(
                f"{self.action}: target_key is only meaningful on a RESTRICTED "
                f"row")
        if self.binding_key and self.authority != AuthorityLevel.HUMAN.value:
            raise GovernanceFormatError(
                f"{self.action}: only a HUMAN row binds the command hash "
                f"(binding_key requires HUMAN authority)")
        if self.authority == AuthorityLevel.HUMAN.value and not self.binding_key:
            raise GovernanceFormatError(
                f"{self.action}: a HUMAN row must declare the binding_key its "
                f"authority rests on (the act ratifies a specific command)")
        if self.window_seconds and self.authority not in {
                AuthorityLevel.REVIEWER.value, AuthorityLevel.HUMAN.value}:
            raise GovernanceFormatError(
                f"{self.action}: an approval window is only meaningful on a row "
                f"whose authority is a recorded decision")

    @property
    def level(self) -> AuthorityLevel:
        return AuthorityLevel(self.authority)

    @property
    def display(self) -> str:
        """The authority as the brief writes it (`REVIEWER/RESTRICTED`, …)."""
        suffix = "/RESTRICTED" if self.restricted else ""
        return f"{self.authority}{suffix}"

    @property
    def check_inputs(self) -> tuple[str, ...]:
        """The checks this row declares, as `"<check>:<key>"` (or `window:N`).

        Derived data, for a reader or an auditor — never a request field.
        """
        checks: list[str] = []
        if self.binding_key:
            checks.append(f"binding:{self.binding_key}")
        if self.target_key:
            checks.append(f"target:{self.target_key}")
        if self.head_key:
            checks.append(f"head:{self.head_key}")
        if self.window_seconds:
            checks.append(f"window:{self.window_seconds}")
        if self.record_required:
            checks.append("record:rationale")
        return tuple(checks)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "authority": self.authority,
            "refusal_code": self.refusal_code,
            "effect": self.effect,
            "restricted": self.restricted,
            "record_required": self.record_required,
            "credential_refusal_code": self.credential_refusal_code,
            "record_refusal_code": self.record_refusal_code,
            "binding_refusal_code": self.binding_refusal_code,
            "head_refusal_code": self.head_refusal_code,
            "binding_key": self.binding_key,
            "target_key": self.target_key,
            "head_key": self.head_key,
            "window_seconds": self.window_seconds,
            "note": self.note,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PolicyRow":
        _unknown_keys(data, cls, "PolicyRow")
        return cls(
            action=str(data["action"]),
            authority=str(data["authority"]),
            refusal_code=str(data["refusal_code"]),
            effect=str(data.get("effect", PERMIT)),
            restricted=bool(data.get("restricted", False)),
            record_required=bool(data.get("record_required", False)),
            credential_refusal_code=str(data.get("credential_refusal_code", "")),
            record_refusal_code=str(data.get("record_refusal_code", "")),
            binding_refusal_code=str(data.get("binding_refusal_code", "")),
            head_refusal_code=str(data.get("head_refusal_code", "")),
            binding_key=str(data.get("binding_key", "")),
            target_key=str(data.get("target_key", "")),
            head_key=str(data.get("head_key", "")),
            window_seconds=int(data.get("window_seconds", 0)),
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True, slots=True)
class Policy:
    """A versioned policy document: an immutable, ordered set of rows.

    Versioned on purpose (§2.5 *Change rule*): a change to the matrix is a
    Governance change, so the document carries its own identity and digest, and
    every verdict names the version that produced it. Version 2 documents the
    schema move that made every check input policy-owned (see the module
    docstring).
    """

    policy_id: str
    version: int
    rows: tuple[PolicyRow, ...]

    def rows_for(self, action: str) -> tuple[PolicyRow, ...]:
        """Every row governing `action`, in declaration order."""
        return tuple(row for row in self.rows if row.action == action)

    def actions(self) -> tuple[str, ...]:
        """The governed actions, in first-declaration order."""
        seen: list[str] = []
        for row in self.rows:
            if row.action not in seen:
                seen.append(row.action)
        return tuple(seen)

    def digest(self) -> str:
        return digest_of({"policy_id": self.policy_id, "version": self.version,
                          "rows": [row.to_mapping() for row in self.rows]})

    def to_mapping(self) -> dict[str, Any]:
        return {"policy_id": self.policy_id, "version": self.version,
                "rows": [row.to_mapping() for row in self.rows]}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Policy":
        _unknown_keys(data, cls, "Policy")
        return cls(
            policy_id=str(data["policy_id"]),
            version=int(data["version"]),
            rows=tuple(PolicyRow.from_mapping(row) for row in data["rows"]),
        )


@dataclass(frozen=True, slots=True)
class ResolvedPolicy:
    """The resolved policy for one action — deny-wins, conflicts named.

    `row` is the governing row (`None` when no row governs the action:
    *deny by default*). `denies`/`permits` are the conflicting rows the resolution
    saw, in declaration order, so a caller can show *why* a permit did not apply.

    `refusal` is set only by the public `resolve` when it refuses a substituted
    document: the resolution then denies by default (`row is None`,
    `allowed_by_policy` False) and names the frozen `MALFORMED_PAYLOAD` reason,
    so the refusal is carried as data rather than raised or ignored.
    """

    action: str
    row: PolicyRow | None
    denies: tuple[PolicyRow, ...] = ()
    permits: tuple[PolicyRow, ...] = ()
    refusal: GovernanceRefusal | None = None

    @property
    def governed(self) -> bool:
        return self.row is not None or bool(self.denies) or bool(self.permits)

    @property
    def allowed_by_policy(self) -> bool:
        """False when no row governs, or when any DENY row governs (deny-wins)."""
        return not (self.row is None or self.row.effect == DENY)

    @property
    def conflicts(self) -> tuple[str, ...]:
        """The actions/effects that conflicted, so a refusal is never silent."""
        if self.denies and self.permits:
            return tuple(
                [f"DENY:{row.action}" for row in self.denies]
                + [f"PERMIT:{row.action}" for row in self.permits])
        return ()


def _resolve(action: str, policy: "Policy") -> ResolvedPolicy:
    """Resolve an action against a *supplied* policy, applying **deny-wins**.

    Deterministic: the governing row is the *first* DENY row when any exist
    (declaration order), otherwise the first PERMIT row. No filtering, no
    scoring, no precedence by authority level — a denial is never overridden by
    a permit, whatever level the permit names.

    The substitutable seam: the evaluation layer (`hermes.governance.authority`)
    and the test harness resolve variant documents here. The **public**
    `resolve` is bound to the shipped document (R5-REATTACK E2, FIX-2).
    """
    rows = policy.rows_for(action)
    denies = tuple(row for row in rows if row.effect == DENY)
    permits = tuple(row for row in rows if row.effect == PERMIT)
    if denies:
        return ResolvedPolicy(action=action, row=denies[0], denies=denies,
                              permits=permits)
    if permits:
        return ResolvedPolicy(action=action, row=permits[0], denies=(), permits=permits)
    return ResolvedPolicy(action=action, row=None)


def resolve(action: str, policy: Any = _NO_POLICY_SUPPLIED,
            **unexpected: Any) -> ResolvedPolicy:
    """Resolve an action against the **shipped** policy — canonical, deny-wins.

    The public surface admits no substituted document (R5-REATTACK E2, FIX-2):
    a check whose subject selects the matrix it is checked against is not a
    check. A `policy` argument — positional or keyword, the shipped document
    included — is refused **as data**: the returned resolution denies by default
    (`row is None`, `allowed_by_policy` False) and carries a `MALFORMED_PAYLOAD`
    refusal naming `POLICY_SUBSTITUTION_DETAIL`. It is never silently ignored,
    and never a `TypeError` (a wiring misconfiguration must be readable as data).
    Variant documents resolve through the private seam `_resolve`.
    """
    if policy is not _NO_POLICY_SUPPLIED or unexpected:
        return _substituted_policy_resolution(action)
    return _resolve(action, GOVERNANCE_POLICY)


def _substituted_policy_resolution(action: str) -> ResolvedPolicy:
    """The coded denial for a `policy` handed to the public `resolve`."""
    return ResolvedPolicy(
        action=action,
        row=None,
        refusal=GovernanceRefusal(
            code=MALFORMED_PAYLOAD,
            detail=POLICY_SUBSTITUTION_DETAIL,
            requirement=REQUIREMENT_POLICY))


# ═══════════════════ the shipped policy document (v2) ═══════════════════


def _agent_row(action: str, note: str) -> PolicyRow:
    return PolicyRow(action=action, authority=AuthorityLevel.AGENT.value,
                     refusal_code=ROLE, note=note)


def _reviewer_row(action: str, *, restricted: bool, note: str,
                  target_key: str = "") -> PolicyRow:
    return PolicyRow(
        action=action,
        authority=AuthorityLevel.REVIEWER.value,
        restricted=restricted,
        refusal_code=ROLE,
        credential_refusal_code=OPERATOR,
        record_refusal_code=PROPOSAL,
        binding_refusal_code=PROPOSAL,
        target_key=target_key,
        window_seconds=DEFAULT_APPROVAL_WINDOW_SECONDS,
        note=note,
    )


def _human_row(action: str, *, binding_key: str, note: str) -> PolicyRow:
    return PolicyRow(
        action=action,
        authority=AuthorityLevel.HUMAN.value,
        refusal_code=ROLE,
        credential_refusal_code=OPERATOR,
        record_refusal_code=PROPOSAL,
        binding_refusal_code=PROPOSAL,
        head_refusal_code=STALE,
        binding_key=binding_key,
        head_key=HEAD_KEY,
        window_seconds=DEFAULT_APPROVAL_WINDOW_SECONDS,
        note=note,
    )


#: Rows in the brief's default-authority table order. Each row's authority is
#: pinned by `test_the_matrix_matches_the_briefs_default_authority_table`, and
#: each row's check inputs by `test_the_check_inputs_are_policy_owned`.
DEFAULT_AUTHORITY_ROWS: tuple[PolicyRow, ...] = (
    _agent_row(WEB_SEARCH, "brief: web-search = AGENT"),
    _agent_row(WEB_READ, "brief: read = AGENT"),
    _agent_row(SANDBOX_RUN, "brief: sandbox-run = AGENT"),
    PolicyRow(action=HYPOTHESIS_MODIFY,
              authority=AuthorityLevel.AGENT_RECORD.value,
              record_required=True,
              refusal_code=ROLE,
              record_refusal_code=RATIONALE,
              note="brief: hypothesis-modify = AGENT+RECORD"),
    _reviewer_row(CONTRADICTION_DECLARE, restricted=False,
                  note="brief: contradiction-declare = REVIEWER"),
    _reviewer_row(EVIDENCE_DELETE, restricted=True,
                  target_key=EVIDENCE_TARGET_KEY,
                  note="brief: evidence-delete = REVIEWER/RESTRICTED"),
    _human_row(DIRECTION_CHANGE, binding_key=DIRECTION_BINDING_KEY,
               note="brief: direction-change = HUMAN"),
    _human_row(PUBLISH, binding_key=PUBLISH_BINDING_KEY,
               note="brief: publish = HUMAN"),
    _human_row(EXTERNAL, binding_key=EXTERNAL_BINDING_KEY,
               note="brief: external = HUMAN"),
)

#: The shipped document. Version 2 (the policy-owned check-input schema); no DENY
#: rows (a shipped denial would change behaviour, so conflicts are pinned with a
#: variant in the suite instead).
POLICY_VERSION = 2
GOVERNANCE_POLICY = Policy(policy_id="hermes-governance",
                           version=POLICY_VERSION,
                           rows=DEFAULT_AUTHORITY_ROWS)
