"""Governance plane tests (ARCHITECTURE_DELTA §2.5, B-1).

What is covered — and what the coverage *proves*
------------------------------------------------
* **The matrix as data** — the nine governed actions and their default authority
  levels are pinned against the brief's default-authority table verbatim, every
  row's refusal codes are pinned, every row's *check inputs* are pinned as policy
  data (v2), the document round-trips its closed mapping, and the action
  vocabulary is asserted to be neither an `IntentKind` nor an `EventType` (the
  matrix adds no intent kind and no event).
* **No new refusal code** — the plane's own code set is re-derived from
  `research/gateway.py` (named constants) and `research/controller.py` (inline
  literals) at test time, so a new code anywhere fails the build; the plane's
  emitted set must be exactly the six mirrored codes, and the coverage table must
  exercise every one of them.
* **Authority is read, never claimed** — the request schema carries no authority
  field; a mapping that declares one, an agent claiming to be the human, a
  credential row for another operator, a decision row from another project, a
  decision binding a different command and a decision with an unrecognised
  verdict are each refused, with the frozen code the matrix names.
* **Check inputs are policy-owned (R5 red team P1-a)** — the two reproduced
  bypasses (`PUBLISH command_hash='APPROVED' binding_key='decision'`,
  `EVIDENCE_DELETE target_ref=<note> target_key='rationale'`) and every
  request-supplied `binding_key`/`target_key`/`window_seconds` are refused; the
  binding/target/head keys and the approval window are pinned on the rows, and
  the controls still bite for the policy's own keys.
* **The evaluation is total (P1-b)** — the director's reproduction (a
  credentialed human act with no scope) and a hostile request-shape sweep both
  return refusal-as-data with a coded, non-empty denial; nothing raises.
* **Independence (P2)** — a requester who is also the recorded decider is
  refused, a distinct requester is allowed, and an unattributable decision or an
  unnamed requester fails closed. The R4 analogue is the runtime's "a child run
  never reviews its own reviewer".
* **No re-stamping (P2)** — a verdict's policy provenance cannot be rewritten by
  a caller: the re-stamp helper is gone and the source is scanned for one.
* **The policy is canonical (R5-REATTACK E2)** — the public `evaluate_authority`,
  `evaluate_approval` and `resolve` accept no substituted `policy`: a document
  authored by the requesting party is refused `MALFORMED_PAYLOAD` (a coded
  refusal, never a `TypeError` and never a silent ignore). The same construction
  through the private seam still grants, proving the attack is real rather than a
  strawman.
* **Deny-wins** — a variant policy carrying PERMIT + DENY rows for one action
  refuses, names both conflicting rows, and resolves deterministically.
* **Denials are data, never silent** — every non-APPROVED approval state returns
  refusal-as-data with a code from the frozen vocabulary and a non-empty detail;
  the suite sweeps the whole scenario table asserting exactly that, so no path
  can refuse by returning nothing.
* **Determinism** — the same rows in any order give byte-identical verdicts
  (digest equality), and the approval lifecycle's fixture table is pinned.
* **Purity (B-5 bar)** — every module is checked mechanically: stdlib + own
  modules only, no `hermes.core`/`hermes.research`/`hermes.persistence`, no
  connection, no SQL, no journal writer, no clock read, no filesystem, no
  module-level mutable state, and no caller anywhere (the plane is wired to
  nothing — nothing in `src/` outside this package mentions it).

The plane is not an authority: nothing asserted here decides a transition.
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import hermes.governance as governance_module
from hermes.core.events import EventType
from hermes.core.intents import IntentKind
from hermes.governance import approvals as approvals_module
from hermes.governance import authority as authority_module
from hermes.governance import policy as policy_module
from hermes.governance.approvals import (
    APPROVE_VERDICTS,
    APPROVED,
    DEFAULT_VERDICT_KEY,
    DENIED,
    DENY_VERDICTS,
    EXPIRED,
    MISSING,
    PENDING,
    STATE_REFUSAL_CODES,
    STATES,
    ApprovalRequest,
    DecisionRow,
    _evaluate_approval,
    evaluate_approval,
)
from hermes.governance.approvals import (
    emitted_refusal_codes as approval_refusal_codes,
)
from hermes.governance.approvals import (
    is_readable_timestamp as _is_readable_timestamp,
)
from hermes.governance.authority import (
    ALLOWED,
    POLICY_OWNED_REQUEST_KEYS,
    REFUSED,
    REQUEST_KEYS,
    SECRET_KEYS,
    VERDICTS,
    ActionRequest,
    AuthorityVerdict,
    CredentialRow,
    EvidenceContext,
    _evaluate_authority,
    emitted_refusal_codes,
    evaluate_authority,
)
from hermes.governance.policy import (
    ACTIONS,
    CONTRADICTION_DECLARE,
    CONTROLLER_EMITTED_CODES,
    DEFAULT_APPROVAL_WINDOW_SECONDS,
    DEFAULT_AUTHORITY_ROWS,
    DENY,
    DIRECTION_BINDING_KEY,
    DIRECTION_CHANGE,
    EFFECTS,
    EVIDENCE_DELETE,
    EVIDENCE_TARGET_KEY,
    EXTERNAL,
    EXTERNAL_BINDING_KEY,
    GATEWAY_DEFINED_CODES,
    GOVERNANCE_POLICY,
    GOVERNANCE_REFUSAL_CODES,
    HEAD_KEY,
    HYPOTHESIS_MODIFY,
    MALFORMED_PAYLOAD,
    MAX_APPROVAL_WINDOW_SECONDS,
    OPERATOR,
    PERMIT,
    POLICY_SUBSTITUTION_DETAIL,
    POLICY_VERSION,
    PROPOSAL,
    PUBLISH,
    PUBLISH_BINDING_KEY,
    RATIONALE,
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
    REQUIREMENTS,
    ROLE,
    SANDBOX_RUN,
    STALE,
    WEB_READ,
    WEB_SEARCH,
    AuthorityLevel,
    GovernanceFormatError,
    GovernanceRefusal,
    Policy,
    PolicyRow,
    _resolve,
    canonical_json,
    digest_of,
    resolve,
)

# ═══════════════════════ paths + fixtures ═══════════════════════

PACKAGE = Path(policy_module.__file__).parent
SRC_ROOT = PACKAGE.parents[1]
HERMES_ROOT = PACKAGE.parent

PROJECT = "p1"
OTHER_PROJECT = "p2"
SCOPE = "curate-decision-h1"
OTHER_SCOPE = "curate-decision-h2"
OP = "op-1"
OP2 = "op-2"

#: The requesting party for a decision-bearing act. It is deliberately *not* the
#: operator: an operator does not ratify their own act (independence).
REQUESTER = "synthesizer"

T1 = "2026-09-24T09:00:00+00:00"
T2 = "2026-09-24T09:30:00+00:00"
T3 = "2026-09-24T10:00:00+00:00"
#: Exactly the row's default window after T1 — the inclusive boundary.
T5 = "2026-09-25T09:00:00+00:00"
#: Two windows after T1 — past every shipped row's window.
T6 = "2026-09-26T09:00:00+00:00"

CREDENTIAL = CredentialRow(operator_id=OP, name="Operator One", created_at=T1)
OTHER_CREDENTIAL = CredentialRow(operator_id=OP2, name="Operator Two", created_at=T1)

#: The brief's default-authority table, verbatim: (action, authority, restricted,
#: record_required). This is the fixture every matrix row is pinned against.
BRIEF_AUTHORITY_TABLE: tuple[tuple[str, str, bool, bool], ...] = (
    (WEB_SEARCH, "AGENT", False, False),
    (WEB_READ, "AGENT", False, False),
    (SANDBOX_RUN, "AGENT", False, False),
    (HYPOTHESIS_MODIFY, "AGENT+RECORD", False, True),
    (CONTRADICTION_DECLARE, "REVIEWER", False, False),
    (EVIDENCE_DELETE, "REVIEWER/RESTRICTED", True, False),
    (DIRECTION_CHANGE, "HUMAN", False, False),
    (PUBLISH, "HUMAN", False, False),
    (EXTERNAL, "HUMAN", False, False),
)

#: The check inputs, pinned per action (v2: policy data, never request fields).
#: (action, binding_key, target_key, head_key, window_seconds)
BRIEF_CHECK_INPUTS: tuple[tuple[str, str, str, str, int], ...] = (
    (WEB_SEARCH, "", "", "", 0),
    (WEB_READ, "", "", "", 0),
    (SANDBOX_RUN, "", "", "", 0),
    (HYPOTHESIS_MODIFY, "", "", "", 0),
    (CONTRADICTION_DECLARE, "", "", "", DEFAULT_APPROVAL_WINDOW_SECONDS),
    (EVIDENCE_DELETE, "", EVIDENCE_TARGET_KEY, "", DEFAULT_APPROVAL_WINDOW_SECONDS),
    (DIRECTION_CHANGE, DIRECTION_BINDING_KEY, "", HEAD_KEY,
     DEFAULT_APPROVAL_WINDOW_SECONDS),
    (PUBLISH, PUBLISH_BINDING_KEY, "", HEAD_KEY, DEFAULT_APPROVAL_WINDOW_SECONDS),
    (EXTERNAL, EXTERNAL_BINDING_KEY, "", HEAD_KEY, DEFAULT_APPROVAL_WINDOW_SECONDS),
)


def _decision(event_id: str, *, verdict: str = APPROVED, scope: str = SCOPE,
              project: str = PROJECT, operator: str = OP, created_at: str = T1,
              reason: str = "operator verdict", **payload: Any) -> DecisionRow:
    """One recorded `HumanDecisionReceived` row (the repo's payload shape)."""
    body: dict[str, Any] = {"decision": verdict, "operator_id": operator}
    body.update(payload)
    return DecisionRow(event_id=event_id, project_id=project,
                       correlation_id=scope, caused_by="operator", reason=reason,
                       payload=body, created_at=created_at)


def _approval_row(event_id: str = "ev-1", **overrides: Any) -> DecisionRow:
    return _decision(event_id, **overrides)


def _module_source(module: Any) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


def _package_sources() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8")
            for path in sorted(PACKAGE.glob("*.py"))}


def _direct_hermes_imports(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == "hermes":
                found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "hermes":
                    found.add(alias.name)
    return found


def _imported_modules(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
    return found


def _referenced_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


def _calls(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


def _variant(*rows: PolicyRow, version: int = 99) -> Policy:
    """A policy document variant — never the shipped one."""
    return replace(GOVERNANCE_POLICY, version=version, rows=rows)


# ═══════════════════════ the matrix coverage table ═══════════════════════
#
# One row per scenario. Every ALLOWED shape and every refusal code the plane can
# emit appears here, so this table is simultaneously the coverage proof and the
# matrix documentation the round report quotes.

MATRIX_COVERAGE: tuple[dict[str, Any], ...] = (
    # ── AGENT rows: no credential, no recorded decision ──
    {"label": "web_search is agent authority", "action": WEB_SEARCH,
     "verdict": ALLOWED},
    {"label": "web_read is agent authority", "action": WEB_READ,
     "verdict": ALLOWED},
    {"label": "sandbox_run is agent authority", "action": SANDBOX_RUN,
     "verdict": ALLOWED},
    {"label": "an agent action ignores unrelated decisions",
     "action": WEB_SEARCH,
     "context": (None, (_decision("ev-other", scope=OTHER_SCOPE),)),
     "verdict": ALLOWED},
    # ── AGENT+RECORD ──
    {"label": "hypothesis_modify without a record refuses RATIONALE",
     "action": HYPOTHESIS_MODIFY, "verdict": REFUSED, "code": RATIONALE,
     "requirement": REQUIREMENT_RECORD},
    {"label": "hypothesis_modify with a blank record refuses RATIONALE",
     "action": HYPOTHESIS_MODIFY, "request": {"rationale": "   "},
     "verdict": REFUSED, "code": RATIONALE, "requirement": REQUIREMENT_RECORD},
    {"label": "hypothesis_modify with a record is allowed",
     "action": HYPOTHESIS_MODIFY, "request": {"rationale": "narrowing H2"},
     "verdict": ALLOWED, "satisfied": "AGENT+RECORD"},
    {"label": "hypothesis_modify needs no credential",
     "action": HYPOTHESIS_MODIFY, "request": {"rationale": "why not"},
     "context": (None, (_decision("ev-other", scope=OTHER_SCOPE),)),
     "verdict": ALLOWED, "satisfied": "AGENT+RECORD"},
    # ── REVIEWER: contradiction-declare ──
    {"label": "an agent cannot declare a contradiction",
     "action": CONTRADICTION_DECLARE, "verdict": REFUSED, "code": ROLE,
     "requirement": REQUIREMENT_AUTHORITY},
    {"label": "a self-declared human is not an operator",
     "action": CONTRADICTION_DECLARE,
     "request": {"actor_is_human": True}, "verdict": REFUSED, "code": ROLE,
     "requirement": REQUIREMENT_AUTHORITY},
    {"label": "an unratified operator is refused OPERATOR",
     "action": CONTRADICTION_DECLARE, "request": {"operator_id": OP},
     "verdict": REFUSED, "code": OPERATOR,
     "requirement": REQUIREMENT_CREDENTIAL},
    {"label": "another operator's credential is not this operator's",
     "action": CONTRADICTION_DECLARE, "request": {"operator_id": OP},
     "context": (OTHER_CREDENTIAL, ()), "verdict": REFUSED, "code": OPERATOR,
     "requirement": REQUIREMENT_CREDENTIAL},
    {"label": "an unidentified requester cannot be checked for independence",
     "action": CONTRADICTION_DECLARE, "request": {"operator_id": OP},
     "context": (CREDENTIAL, (_approval_row(),)), "verdict": REFUSED,
     "code": MALFORMED_PAYLOAD, "requirement": REQUIREMENT_INDEPENDENCE},
    {"label": "a ratified operator with no decision refuses PROPOSAL",
     "action": CONTRADICTION_DECLARE,
     "request": {"operator_id": OP, "actor": REQUESTER, "now": T2},
     "context": (CREDENTIAL, ()), "verdict": REFUSED, "code": PROPOSAL,
     "requirement": REQUIREMENT_DECISION, "approval_state": MISSING},
    {"label": "a pending decision refuses PROPOSAL",
     "action": CONTRADICTION_DECLARE,
     "request": {"operator_id": OP, "actor": REQUESTER, "now": T2},
     "context": (CREDENTIAL, (_decision("ev-1", verdict="CURATE_KNOWLEDGE"),)),
     "verdict": REFUSED, "code": PROPOSAL, "requirement": REQUIREMENT_DECISION,
     "approval_state": PENDING},
    {"label": "a denied decision refuses PROPOSAL",
     "action": CONTRADICTION_DECLARE,
     "request": {"operator_id": OP, "actor": REQUESTER, "now": T2},
     "context": (CREDENTIAL, (_decision("ev-1", verdict="DENIED"),)),
     "verdict": REFUSED, "code": PROPOSAL, "requirement": REQUIREMENT_DECISION,
     "approval_state": DENIED},
    {"label": "a gate REJECTED verdict is a denial",
     "action": CONTRADICTION_DECLARE,
     "request": {"operator_id": OP, "actor": REQUESTER, "now": T2},
     "context": (CREDENTIAL, (_decision("ev-1", verdict="REJECTED"),)),
     "verdict": REFUSED, "code": PROPOSAL, "requirement": REQUIREMENT_DECISION,
     "approval_state": DENIED},
    {"label": "a decision from another project is not authority",
     "action": CONTRADICTION_DECLARE,
     "request": {"operator_id": OP, "actor": REQUESTER, "now": T2},
     "context": (CREDENTIAL, (_approval_row(project=OTHER_PROJECT),)),
     "verdict": REFUSED, "code": PROPOSAL, "requirement": REQUIREMENT_DECISION,
     "approval_state": MISSING},
    {"label": "a decision for another scope is not authority",
     "action": CONTRADICTION_DECLARE,
     "request": {"operator_id": OP, "actor": REQUESTER, "now": T2},
     "context": (CREDENTIAL, (_approval_row(scope=OTHER_SCOPE),)),
     "verdict": REFUSED, "code": PROPOSAL, "requirement": REQUIREMENT_DECISION,
     "approval_state": MISSING},
    {"label": "an approved decision authorizes contradiction-declare",
     "action": CONTRADICTION_DECLARE,
     "request": {"operator_id": OP, "actor": REQUESTER, "now": T2},
     "context": (CREDENTIAL, (_approval_row(),)), "verdict": ALLOWED,
     "satisfied": "REVIEWER"},
    {"label": "a requester who is the recorded decider refuses ROLE",
     "action": CONTRADICTION_DECLARE,
     "request": {"operator_id": OP, "actor": OP, "now": T2},
     "context": (CREDENTIAL, (_approval_row(),)), "verdict": REFUSED,
     "code": ROLE, "requirement": REQUIREMENT_INDEPENDENCE},
    {"label": "an unattributable decision refuses the independence check",
     "action": CONTRADICTION_DECLARE,
     "request": {"operator_id": OP, "actor": REQUESTER, "now": T2},
     "context": (CREDENTIAL, (_approval_row(operator=""),)), "verdict": REFUSED,
     "code": MALFORMED_PAYLOAD, "requirement": REQUIREMENT_INDEPENDENCE},
    {"label": "an expired decision refuses PROPOSAL",
     "action": CONTRADICTION_DECLARE,
     "request": {"operator_id": OP, "actor": REQUESTER, "now": T6},
     "context": (CREDENTIAL, (_approval_row(),)),
     "verdict": REFUSED, "code": PROPOSAL, "requirement": REQUIREMENT_DECISION,
     "approval_state": EXPIRED},
    # ── REVIEWER/RESTRICTED: evidence-delete ──
    {"label": "an agent cannot delete evidence",
     "action": EVIDENCE_DELETE, "verdict": REFUSED, "code": ROLE,
     "requirement": REQUIREMENT_AUTHORITY},
    {"label": "a restricted act without a target is malformed",
     "action": EVIDENCE_DELETE,
     "request": {"operator_id": OP, "actor": REQUESTER, "now": T2},
     "context": (CREDENTIAL, (_approval_row(),)),
     "verdict": REFUSED, "code": MALFORMED_PAYLOAD,
     "requirement": REQUIREMENT_TARGET},
    {"label": "a restricted act needs the approval to bind the target",
     "action": EVIDENCE_DELETE, "request": {"operator_id": OP,
                                            "actor": REQUESTER,
                                            "target_ref": "art:1", "now": T2},
     "context": (CREDENTIAL, (_approval_row(),)),
     "verdict": REFUSED, "code": PROPOSAL, "requirement": REQUIREMENT_TARGET},
    {"label": "a restricted act binding another target refuses PROPOSAL",
     "action": EVIDENCE_DELETE, "request": {"operator_id": OP,
                                            "actor": REQUESTER,
                                            "target_ref": "art:1", "now": T2},
     "context": (CREDENTIAL, (_approval_row(target_ref="art:2"),)),
     "verdict": REFUSED, "code": PROPOSAL, "requirement": REQUIREMENT_TARGET},
    {"label": "a restricted act binding the exact target is allowed",
     "action": EVIDENCE_DELETE, "request": {"operator_id": OP,
                                            "actor": REQUESTER,
                                            "target_ref": "art:1", "now": T2},
     "context": (CREDENTIAL, (_approval_row(target_ref="art:1"),)),
     "verdict": ALLOWED, "satisfied": "REVIEWER/RESTRICTED"},
    {"label": "contradiction-declare is not restricted",
     "action": CONTRADICTION_DECLARE,
     "request": {"operator_id": OP, "actor": REQUESTER, "now": T2},
     "context": (CREDENTIAL, (_approval_row(),)), "verdict": ALLOWED,
     "satisfied": "REVIEWER"},
    # ── HUMAN: direction-change / publish / external ──
    {"label": "an agent cannot change direction",
     "action": DIRECTION_CHANGE, "verdict": REFUSED, "code": ROLE,
     "requirement": REQUIREMENT_AUTHORITY},
    {"label": "an unratified operator cannot change direction",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP},
     "verdict": REFUSED, "code": OPERATOR,
     "requirement": REQUIREMENT_CREDENTIAL},
    {"label": "a human act needs the exact command bound",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP,
                                             "actor": REQUESTER,
                                             "command_hash": "h-7",
                                             "head_ref": "gen-1", "now": T2},
     "context": (CREDENTIAL, (_approval_row(),)),
     "verdict": REFUSED, "code": PROPOSAL, "requirement": REQUIREMENT_BINDING},
    {"label": "a bound human act is allowed",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP,
                                             "actor": REQUESTER,
                                             "command_hash": "h-7",
                                             "head_ref": "gen-1", "now": T2},
     "context": (CREDENTIAL, (_approval_row(direction_hash="h-7"),)),
     "verdict": ALLOWED, "satisfied": "HUMAN"},
    {"label": "a human act without a command hash is malformed",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP,
                                             "actor": REQUESTER,
                                             "head_ref": "gen-1", "now": T2},
     "context": (CREDENTIAL, (_approval_row(direction_hash="h-7"),)),
     "verdict": REFUSED, "code": MALFORMED_PAYLOAD,
     "requirement": REQUIREMENT_BINDING},
    {"label": "a human act without a declared head is malformed",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP,
                                             "actor": REQUESTER,
                                             "command_hash": "h-7", "now": T2},
     "context": (CREDENTIAL, (_approval_row(direction_hash="h-7"),)),
     "verdict": REFUSED, "code": MALFORMED_PAYLOAD,
     "requirement": REQUIREMENT_HEAD},
    {"label": "a human act without a declared clock is malformed",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP,
                                             "actor": REQUESTER,
                                             "command_hash": "h-7",
                                             "head_ref": "gen-1"},
     "context": (CREDENTIAL, (_approval_row(direction_hash="h-7"),)),
     "verdict": REFUSED, "code": MALFORMED_PAYLOAD,
     "requirement": REQUIREMENT_DECISION},
    {"label": "a malformed clock is malformed data, not a raise",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP,
                                             "actor": REQUESTER,
                                             "command_hash": "h-7",
                                             "head_ref": "gen-1",
                                             "now": "yesterday"},
     "context": (CREDENTIAL, (_approval_row(direction_hash="h-7"),)),
     "verdict": REFUSED, "code": MALFORMED_PAYLOAD,
     "requirement": REQUIREMENT_REQUEST},
    {"label": "a superseded head refuses STALE",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP,
                                             "actor": REQUESTER,
                                             "command_hash": "h-7",
                                             "head_ref": "gen-2", "now": T2},
     "context": (CREDENTIAL, (_approval_row(direction_hash="h-7",
                                            **{HEAD_KEY: "gen-1"}),)),
     "verdict": REFUSED, "code": STALE, "requirement": REQUIREMENT_HEAD},
    {"label": "a matching head is allowed",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP,
                                             "actor": REQUESTER,
                                             "command_hash": "h-7",
                                             "head_ref": "gen-1", "now": T2},
     "context": (CREDENTIAL, (_approval_row(direction_hash="h-7",
                                            **{HEAD_KEY: "gen-1"}),)),
     "verdict": ALLOWED, "satisfied": "HUMAN"},
    {"label": "an approval that binds no head skips the head check",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP,
                                             "actor": REQUESTER,
                                             "command_hash": "h-7",
                                             "head_ref": "gen-2", "now": T2},
     "context": (CREDENTIAL, (_approval_row(direction_hash="h-7"),)),
     "verdict": ALLOWED, "satisfied": "HUMAN"},
    {"label": "a bound command within its window is allowed",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP,
                                             "actor": REQUESTER,
                                             "command_hash": "h-7",
                                             "head_ref": "gen-1", "now": T2},
     "context": (CREDENTIAL, (_approval_row(direction_hash="h-7"),)),
     "verdict": ALLOWED, "satisfied": "HUMAN", "approval_state": APPROVED,
     "age_seconds": 1800},
    {"label": "the window boundary is inclusive",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP,
                                             "actor": REQUESTER,
                                             "command_hash": "h-7",
                                             "head_ref": "gen-1", "now": T5},
     "context": (CREDENTIAL, (_approval_row(direction_hash="h-7"),)),
     "verdict": ALLOWED, "satisfied": "HUMAN", "age_seconds": 86400},
    {"label": "an expired bound command refuses PROPOSAL",
     "action": DIRECTION_CHANGE, "request": {"operator_id": OP,
                                             "actor": REQUESTER,
                                             "command_hash": "h-7",
                                             "head_ref": "gen-1", "now": T6},
     "context": (CREDENTIAL, (_approval_row(direction_hash="h-7"),)),
     "verdict": REFUSED, "code": PROPOSAL, "requirement": REQUIREMENT_DECISION,
     "approval_state": EXPIRED},
    {"label": "publish is allowed when bound", "action": PUBLISH,
     "request": {"operator_id": OP, "actor": REQUESTER, "command_hash": "h-8",
                 "head_ref": "gen-1", "now": T2},
     "context": (CREDENTIAL, (_approval_row(publish_hash="h-8"),)),
     "verdict": ALLOWED, "satisfied": "HUMAN"},
    {"label": "an external act is allowed when bound", "action": EXTERNAL,
     "request": {"operator_id": OP, "actor": REQUESTER, "command_hash": "h-9",
                 "head_ref": "gen-1", "now": T2},
     "context": (CREDENTIAL, (_approval_row(external_hash="h-9"),)),
     "verdict": ALLOWED, "satisfied": "HUMAN"},
    {"label": "publish by an agent refuses ROLE", "action": PUBLISH,
     "verdict": REFUSED, "code": ROLE, "requirement": REQUIREMENT_AUTHORITY},
    {"label": "an external act by an agent refuses ROLE", "action": EXTERNAL,
     "verdict": REFUSED, "code": ROLE, "requirement": REQUIREMENT_AUTHORITY},
    # ── deny-by-default + schema bypass shapes ──
    {"label": "an ungoverned action denies by default",
     "action": "NOT_AN_ACTION", "verdict": REFUSED, "code": ROLE,
     "requirement": REQUIREMENT_POLICY},
    {"label": "a request declaring an authority is malformed",
     "raw": {"action": PUBLISH, "project_id": PROJECT, "authority": "HUMAN",
             "operator_id": OP, "actor": REQUESTER, "command_hash": "h-8"},
     "verdict": REFUSED, "code": MALFORMED_PAYLOAD,
     "requirement": REQUIREMENT_REQUEST},
    {"label": "a request with an unknown key is malformed",
     "raw": {"action": WEB_SEARCH, "project_id": PROJECT, "levels": ["AGENT"]},
     "verdict": REFUSED, "code": MALFORMED_PAYLOAD,
     "requirement": REQUIREMENT_REQUEST},
    {"label": "a request declaring a binding key is malformed",
     "raw": {"action": PUBLISH, "project_id": PROJECT, "operator_id": OP,
             "actor": REQUESTER, "command_hash": "APPROVED",
             "binding_key": "decision"},
     "verdict": REFUSED, "code": MALFORMED_PAYLOAD,
     "requirement": REQUIREMENT_REQUEST},
    {"label": "a request declaring a target key is malformed",
     "raw": {"action": EVIDENCE_DELETE, "project_id": PROJECT,
             "operator_id": OP, "actor": REQUESTER,
             "target_ref": "operator note", "target_key": "rationale"},
     "verdict": REFUSED, "code": MALFORMED_PAYLOAD,
     "requirement": REQUIREMENT_REQUEST},
    {"label": "a request declaring an approval window is malformed",
     "raw": {"action": WEB_SEARCH, "project_id": PROJECT, "now": T2,
             "window_seconds": 3600},
     "verdict": REFUSED, "code": MALFORMED_PAYLOAD,
     "requirement": REQUIREMENT_REQUEST},
    {"label": "a request declaring a head key is malformed",
     "raw": {"action": DIRECTION_CHANGE, "project_id": PROJECT,
             "operator_id": OP, "actor": REQUESTER, "command_hash": "h-7",
             "head_key": "other_ref"},
     "verdict": REFUSED, "code": MALFORMED_PAYLOAD,
     "requirement": REQUIREMENT_REQUEST},
    {"label": "an empty action is malformed",
     "raw": {"action": "", "project_id": PROJECT}, "verdict": REFUSED,
     "code": MALFORMED_PAYLOAD, "requirement": REQUIREMENT_REQUEST},
    {"label": "a missing project is malformed",
     "raw": {"action": WEB_SEARCH}, "verdict": REFUSED,
     "code": MALFORMED_PAYLOAD, "requirement": REQUIREMENT_REQUEST},
)


def _build(item: dict[str, Any]) -> tuple[Any, EvidenceContext]:
    if "raw" in item:
        return dict(item["raw"]), EvidenceContext()
    request: dict[str, Any] = {
        "action": item["action"],
        "project_id": item.get("project_id", PROJECT),
        "correlation_id": SCOPE,
    }
    request.update(item.get("request", {}))
    credential, decisions = item.get("context", (None, ()))
    return (ActionRequest(**request),
            EvidenceContext(credential=credential, decisions=tuple(decisions)))


def _evaluate(item: dict[str, Any]) -> AuthorityVerdict:
    request, context = _build(item)
    return evaluate_authority(request, context)


COVERAGE_IDS = [item["label"] for item in MATRIX_COVERAGE]


# ═══════════════════════ the policy as data ═══════════════════════


class TestPolicyAsData:
    def test_the_matrix_matches_the_briefs_default_authority_table(self) -> None:
        rows = GOVERNANCE_POLICY.rows
        assert len(rows) == len(BRIEF_AUTHORITY_TABLE)
        for row, (action, authority, restricted, record) in zip(
                rows, BRIEF_AUTHORITY_TABLE, strict=True):
            assert row.action == action
            assert row.display == authority
            assert row.restricted is restricted
            assert row.record_required is record
            assert row.effect == PERMIT

    def test_the_shipped_matrix_governs_exactly_the_briefs_nine_actions(self) -> None:
        assert GOVERNANCE_POLICY.actions() == ACTIONS
        assert tuple(action for action, *_ in BRIEF_AUTHORITY_TABLE) == ACTIONS

    def test_every_shipped_action_has_exactly_one_row(self) -> None:
        for action in ACTIONS:
            assert len(GOVERNANCE_POLICY.rows_for(action)) == 1, action

    def test_every_row_carries_a_refusal_code_from_the_frozen_vocabulary(self) -> None:
        for row in GOVERNANCE_POLICY.rows:
            for name in ("refusal_code", "credential_refusal_code",
                         "record_refusal_code", "binding_refusal_code",
                         "head_refusal_code"):
                code = getattr(row, name)
                assert not code or code in GOVERNANCE_REFUSAL_CODES, (row.action, name)

    def test_operator_rows_name_a_credential_and_a_record_refusal_code(self) -> None:
        for row in GOVERNANCE_POLICY.rows:
            if row.authority in (AuthorityLevel.REVIEWER.value,
                                 AuthorityLevel.HUMAN.value):
                assert row.credential_refusal_code == OPERATOR
                assert row.record_refusal_code == PROPOSAL
            else:
                assert row.credential_refusal_code == ""
                expected = RATIONALE if row.record_required else ""
                assert row.record_refusal_code == expected

    def test_only_the_human_rows_declare_a_head_refusal_code(self) -> None:
        for row in GOVERNANCE_POLICY.rows:
            if row.authority == AuthorityLevel.HUMAN.value:
                assert row.head_refusal_code == STALE
                assert row.binding_refusal_code == PROPOSAL
            elif row.authority == AuthorityLevel.REVIEWER.value:
                assert row.head_refusal_code == ""
                assert row.binding_refusal_code == PROPOSAL
            else:
                assert row.head_refusal_code == ""
                assert row.binding_refusal_code == ""

    def test_the_check_inputs_are_policy_owned(self) -> None:
        # v2 (red team P1-a): the keys a check reads, and the approval window,
        # are row data — pinned here so no request field can ever select them.
        assert len(GOVERNANCE_POLICY.rows) == len(BRIEF_CHECK_INPUTS)
        for row, (action, binding, target, head, window) in zip(
                GOVERNANCE_POLICY.rows, BRIEF_CHECK_INPUTS, strict=True):
            assert row.action == action
            assert row.binding_key == binding, action
            assert row.target_key == target, action
            assert row.head_key == head, action
            assert row.window_seconds == window, action
        human = [row.action for row in GOVERNANCE_POLICY.rows
                 if row.binding_key]
        assert human == [DIRECTION_CHANGE, PUBLISH, EXTERNAL]
        assert [row.action for row in GOVERNANCE_POLICY.rows
                if row.head_key] == human
        assert [row.action for row in GOVERNANCE_POLICY.rows
                if row.window_seconds] == [
            CONTRADICTION_DECLARE, EVIDENCE_DELETE, DIRECTION_CHANGE, PUBLISH,
            EXTERNAL]
        assert [row.action for row in GOVERNANCE_POLICY.rows
                if row.target_key] == [EVIDENCE_DELETE]
        assert DEFAULT_APPROVAL_WINDOW_SECONDS == 24 * 60 * 60
        assert MAX_APPROVAL_WINDOW_SECONDS == 7 * 24 * 60 * 60
        assert all(row.window_seconds <= MAX_APPROVAL_WINDOW_SECONDS
                   for row in GOVERNANCE_POLICY.rows)

    def test_the_check_inputs_are_reported_as_derived_data(self) -> None:
        publish = GOVERNANCE_POLICY.rows_for(PUBLISH)[0]
        assert publish.check_inputs == (
            f"binding:{PUBLISH_BINDING_KEY}", f"head:{HEAD_KEY}",
            f"window:{DEFAULT_APPROVAL_WINDOW_SECONDS}")
        assert GOVERNANCE_POLICY.rows_for(WEB_SEARCH)[0].check_inputs == ()
        assert GOVERNANCE_POLICY.rows_for(EVIDENCE_DELETE)[0].check_inputs == (
            f"target:{EVIDENCE_TARGET_KEY}",
            f"window:{DEFAULT_APPROVAL_WINDOW_SECONDS}")

    def test_only_hypothesis_modify_is_record_required(self) -> None:
        required = [row.action for row in GOVERNANCE_POLICY.rows
                    if row.record_required]
        assert required == [HYPOTHESIS_MODIFY]
        for row in GOVERNANCE_POLICY.rows:
            if row.record_required:
                assert row.record_refusal_code == RATIONALE

    def test_only_evidence_delete_is_restricted(self) -> None:
        restricted = [row.action for row in GOVERNANCE_POLICY.rows
                      if row.restricted]
        assert restricted == [EVIDENCE_DELETE]

    def test_the_shipped_policy_carries_no_denial(self) -> None:
        assert all(row.effect == PERMIT for row in GOVERNANCE_POLICY.rows)
        assert EFFECTS == (PERMIT, DENY)

    def test_the_policy_is_versioned_and_immutable(self) -> None:
        assert POLICY_VERSION == 2, "v2 is the policy-owned check-input schema"
        assert (GOVERNANCE_POLICY.policy_id, GOVERNANCE_POLICY.version) == (
            "hermes-governance", POLICY_VERSION)
        with pytest.raises(AttributeError):
            GOVERNANCE_POLICY.version = 3  # type: ignore[misc]

    def test_the_policy_version_bump_is_documented(self) -> None:
        source = _module_source(policy_module)
        assert "v2" in source
        assert "policy-owned" in source
        assert "check inputs are policy-owned" in source

    def test_the_digest_tracks_the_rows(self) -> None:
        first = DEFAULT_AUTHORITY_ROWS[0]
        changed = replace(first, refusal_code=OPERATOR)
        variant = _variant(changed, *DEFAULT_AUTHORITY_ROWS[1:])
        assert variant.digest() != GOVERNANCE_POLICY.digest()
        assert _variant(*DEFAULT_AUTHORITY_ROWS).digest() != \
            GOVERNANCE_POLICY.digest()  # version differs too
        same = _variant(*DEFAULT_AUTHORITY_ROWS, version=POLICY_VERSION)
        assert same.digest() == GOVERNANCE_POLICY.digest()

    def test_the_policy_round_trips_its_closed_mapping(self) -> None:
        mapping = GOVERNANCE_POLICY.to_mapping()
        assert Policy.from_mapping(mapping) == GOVERNANCE_POLICY
        assert json.loads(canonical_json(mapping)) == mapping
        with pytest.raises(GovernanceFormatError):
            Policy.from_mapping({**mapping, "authority": "HUMAN"})
        row_mapping = DEFAULT_AUTHORITY_ROWS[0].to_mapping()
        assert PolicyRow.from_mapping(row_mapping) == DEFAULT_AUTHORITY_ROWS[0]
        with pytest.raises(GovernanceFormatError):
            PolicyRow.from_mapping({**row_mapping, "extra": 1})

    def test_a_row_naming_an_unknown_code_is_refused_at_construction(self) -> None:
        with pytest.raises(GovernanceFormatError):
            PolicyRow(action=WEB_SEARCH, authority="AGENT",
                      refusal_code="NOT_A_CODE")
        with pytest.raises(GovernanceFormatError):
            PolicyRow(action=WEB_SEARCH, authority="SUPERVISOR",
                      refusal_code=ROLE)
        with pytest.raises(GovernanceFormatError):
            PolicyRow(action=WEB_SEARCH, authority="AGENT", refusal_code=ROLE,
                      effect="MAYBE")

    def test_a_restricted_row_requires_a_recorded_decision_level(self) -> None:
        with pytest.raises(GovernanceFormatError):
            PolicyRow(action=WEB_SEARCH, authority="AGENT", refusal_code=ROLE,
                      restricted=True)

    def test_the_check_input_invariants_are_refused_at_construction(self) -> None:
        # A restricted row must name the target key its approval binds ...
        with pytest.raises(GovernanceFormatError):
            PolicyRow(action=EVIDENCE_DELETE, authority="REVIEWER",
                      refusal_code=ROLE, credential_refusal_code=OPERATOR,
                      record_refusal_code=PROPOSAL, restricted=True)
        # ... and a non-restricted row must not declare one.
        with pytest.raises(GovernanceFormatError):
            PolicyRow(action=CONTRADICTION_DECLARE, authority="REVIEWER",
                      refusal_code=ROLE, credential_refusal_code=OPERATOR,
                      record_refusal_code=PROPOSAL, target_key="target_ref")
        # Only a HUMAN row binds the command hash.
        with pytest.raises(GovernanceFormatError):
            PolicyRow(action=CONTRADICTION_DECLARE, authority="REVIEWER",
                      refusal_code=ROLE, credential_refusal_code=OPERATOR,
                      record_refusal_code=PROPOSAL, binding_key="direction_hash")
        # A HUMAN row must declare the binding key its authority rests on.
        with pytest.raises(GovernanceFormatError):
            PolicyRow(action=PUBLISH, authority="HUMAN", refusal_code=ROLE,
                      credential_refusal_code=OPERATOR,
                      record_refusal_code=PROPOSAL, head_key=HEAD_KEY)
        # A window outside the declared bounds is refused.
        with pytest.raises(GovernanceFormatError):
            PolicyRow(action=PUBLISH, authority="HUMAN", refusal_code=ROLE,
                      credential_refusal_code=OPERATOR,
                      record_refusal_code=PROPOSAL,
                      binding_key=PUBLISH_BINDING_KEY,
                      window_seconds=MAX_APPROVAL_WINDOW_SECONDS + 1)
        with pytest.raises(GovernanceFormatError):
            PolicyRow(action=PUBLISH, authority="HUMAN", refusal_code=ROLE,
                      credential_refusal_code=OPERATOR,
                      record_refusal_code=PROPOSAL,
                      binding_key=PUBLISH_BINDING_KEY, window_seconds=-1)
        # A window on a row whose authority is not a recorded decision is refused.
        with pytest.raises(GovernanceFormatError):
            PolicyRow(action=WEB_SEARCH, authority="AGENT", refusal_code=ROLE,
                      window_seconds=60)

    def test_the_refusal_vocabulary_is_the_mirrored_vocabulary(self) -> None:
        assert GOVERNANCE_REFUSAL_CODES == (
            GATEWAY_DEFINED_CODES | CONTROLLER_EMITTED_CODES)
        assert frozenset(
            {ROLE, OPERATOR, PROPOSAL, STALE, MALFORMED_PAYLOAD, RATIONALE}) == GOVERNANCE_REFUSAL_CODES

    def test_the_refusal_code_provenance_is_rederived_from_source(self) -> None:
        gateway = (HERMES_ROOT / "research" / "gateway.py").read_text(
            encoding="utf-8")
        controller = (HERMES_ROOT / "research" / "controller.py").read_text(
            encoding="utf-8")
        for code in sorted(GATEWAY_DEFINED_CODES):
            assert f'{code} = "{code}"' in gateway, code
        for code in sorted(CONTROLLER_EMITTED_CODES):
            assert f'"{code}"' in controller, code
            assert f'{code} = "{code}"' not in gateway, code
        assert frozenset({ROLE, OPERATOR, PROPOSAL, STALE, MALFORMED_PAYLOAD}) == (
            GATEWAY_DEFINED_CODES)
        assert frozenset({RATIONALE}) == CONTROLLER_EMITTED_CODES

    def test_the_plane_emits_no_code_outside_the_frozen_vocabulary(self) -> None:
        assert emitted_refusal_codes() <= GOVERNANCE_REFUSAL_CODES
        assert approval_refusal_codes() <= GOVERNANCE_REFUSAL_CODES
        assert emitted_refusal_codes() | approval_refusal_codes() == (
            GOVERNANCE_REFUSAL_CODES)

    def test_the_requirement_vocabulary_is_closed(self) -> None:
        assert len(REQUIREMENTS) == len(set(REQUIREMENTS))
        assert set(REQUIREMENTS) >= {
            REQUIREMENT_POLICY, REQUIREMENT_REQUEST, REQUIREMENT_AUTHORITY,
            REQUIREMENT_CREDENTIAL, REQUIREMENT_DECISION,
            REQUIREMENT_INDEPENDENCE, REQUIREMENT_BINDING,
            REQUIREMENT_HEAD, REQUIREMENT_RECORD, REQUIREMENT_TARGET}

    def test_action_names_are_not_intent_kinds_or_event_types(self) -> None:
        assert not (set(ACTIONS) & {kind.value for kind in IntentKind})
        assert not (set(ACTIONS) & {event.value for event in EventType})

    def test_the_plane_defines_no_event_or_intent_kind(self) -> None:
        for name, source in _package_sources().items():
            referenced = _referenced_names(source)
            assert "EventType" not in referenced, name
            assert "IntentKind" not in referenced, name
            assert "Intent" not in referenced, name

    def test_resolving_every_action_yields_no_conflict(self) -> None:
        for action in ACTIONS:
            resolved = resolve(action)
            assert resolved.governed
            assert resolved.allowed_by_policy
            assert resolved.conflicts == ()
            assert resolved.denies == ()


# ═══════════════════════ the matrix coverage table ═══════════════════════


@pytest.mark.parametrize("item", MATRIX_COVERAGE, ids=COVERAGE_IDS)
def test_matrix_coverage(item: dict[str, Any]) -> None:
    verdict = _evaluate(item)
    assert verdict.verdict == item["verdict"], verdict.as_dict()
    expected_action = item["raw"]["action"] if "raw" in item else item["action"]
    assert verdict.action == expected_action
    if item["verdict"] == ALLOWED:
        assert verdict.refusal is None
        assert verdict.requirement == ""
        assert verdict.satisfied_authority == item.get(
            "satisfied", verdict.required_authority)
        assert verdict.required_authority == verdict.satisfied_authority
    else:
        assert verdict.refusal is not None
        assert verdict.refusal.code == item["code"], verdict.as_dict()
        assert verdict.refusal.detail.strip()
        assert verdict.requirement == item["requirement"]
    if "approval_state" in item:
        assert verdict.approval is not None
        assert verdict.approval.state == item["approval_state"]
    if "age_seconds" in item:
        assert verdict.approval is not None
        assert verdict.approval.age_seconds == item["age_seconds"]


def test_every_governed_action_appears_in_the_coverage_table() -> None:
    covered = {item["action"] for item in MATRIX_COVERAGE
               if item.get("action") in ACTIONS}
    assert covered == set(ACTIONS)


def test_every_governed_action_has_an_allowed_shape_in_the_table() -> None:
    allowed = {item["action"] for item in MATRIX_COVERAGE
               if item["verdict"] == ALLOWED and "action" in item}
    assert allowed == set(ACTIONS)


def test_the_coverage_table_exercises_every_code_the_plane_can_emit() -> None:
    codes = {item["code"] for item in MATRIX_COVERAGE if "code" in item}
    assert codes == GOVERNANCE_REFUSAL_CODES
    assert codes == emitted_refusal_codes()


def test_no_refusal_path_in_the_table_is_silent() -> None:
    for item in MATRIX_COVERAGE:
        verdict = _evaluate(item)
        if verdict.verdict == REFUSED:
            assert verdict.refusal is not None, item["label"]
            assert verdict.refusal.code in GOVERNANCE_REFUSAL_CODES
            assert verdict.refusal.detail.strip(), item["label"]
            assert verdict.refusal.requirement in REQUIREMENTS, item["label"]
        else:
            assert verdict.refusal is None, item["label"]


def test_every_refusal_is_a_bounded_coded_record() -> None:
    # P1-b's other half: a denial is never empty, never uncoded and never
    # unbounded — every refusal in the table serialises to a small, coded record.
    for item in MATRIX_COVERAGE:
        verdict = _evaluate(item)
        payload = verdict.as_dict()
        if verdict.refusal is not None:
            assert set(payload) >= {"rejected", "code", "detail"}
            assert payload["rejected"] is True
            assert payload["code"] == verdict.refusal.code
            assert len(json.dumps(payload)) < 4096, item["label"]
        else:
            assert "rejected" not in payload


def test_verdicts_are_plain_serialisable_data() -> None:
    for item in MATRIX_COVERAGE:
        verdict = _evaluate(item)
        payload = verdict.to_mapping()
        assert json.loads(canonical_json(payload)) == json.loads(
            json.dumps(payload, sort_keys=True))
        assert json.loads(json.dumps(verdict.as_dict()))["verdict"] == (
            verdict.verdict)


# ═══════════════════════ the red-team fixes (R5-FIX) ═══════════════════════


class TestPolicyOwnedCheckInputs:
    """P1-a: the check inputs are policy data; the two live bypasses are dead."""

    def test_the_request_schema_has_no_check_input_field(self) -> None:
        for key in POLICY_OWNED_REQUEST_KEYS:
            assert key not in REQUEST_KEYS, key
        assert "authority" not in REQUEST_KEYS
        assert not hasattr(ActionRequest, "binding_key")
        assert not hasattr(ActionRequest, "target_key")
        assert not hasattr(ActionRequest, "window_seconds")

    @pytest.mark.parametrize("key", POLICY_OWNED_REQUEST_KEYS)
    def test_a_policy_owned_check_input_is_refused(self, key: str) -> None:
        with pytest.raises(GovernanceFormatError) as refused:
            ActionRequest.from_mapping({"action": PUBLISH,
                                        "project_id": PROJECT, key: "anything"})
        assert "policy-owned" in str(refused.value)

    def test_the_publish_binding_bypass_is_refused(self) -> None:
        # The reproduced attack: bind the decision row's own verdict verb and
        # call it a command hash.
        verdict = evaluate_authority(
            {"action": PUBLISH, "project_id": PROJECT, "operator_id": OP,
             "actor": REQUESTER, "command_hash": "APPROVED",
             "binding_key": "decision", "correlation_id": SCOPE},
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(decision="APPROVED"),)))
        assert verdict.verdict == REFUSED
        assert verdict.refusal is not None
        assert verdict.refusal.code == MALFORMED_PAYLOAD
        assert "policy-owned" in verdict.refusal.detail
        assert "binding_key" in verdict.refusal.detail

    def test_the_evidence_delete_target_bypass_is_refused(self) -> None:
        # The reproduced attack: bind a free-text note and call it the target.
        verdict = evaluate_authority(
            {"action": EVIDENCE_DELETE, "project_id": PROJECT,
             "operator_id": OP, "actor": REQUESTER,
             "target_ref": "operator note", "target_key": "rationale",
             "correlation_id": SCOPE},
            EvidenceContext(credential=CREDENTIAL, decisions=(_approval_row(
                rationale="operator note"),)))
        assert verdict.verdict == REFUSED
        assert verdict.refusal is not None
        assert verdict.refusal.code == MALFORMED_PAYLOAD
        assert "policy-owned" in verdict.refusal.detail
        assert "target_key" in verdict.refusal.detail

    def test_the_bypass_fails_closed_even_without_the_key_field(self) -> None:
        # Defence in depth: with the key field gone, the forged *value* still
        # binds nothing at the policy's own key.
        verdict = evaluate_authority(
            ActionRequest(action=PUBLISH, project_id=PROJECT, operator_id=OP,
                          actor=REQUESTER, command_hash="APPROVED",
                          head_ref="gen-1", now=T2, correlation_id=SCOPE),
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(decision="APPROVED"),)))
        assert verdict.refusal is not None
        assert verdict.refusal.code == PROPOSAL
        assert verdict.requirement == REQUIREMENT_BINDING
        assert len(verdict.refusal.detail.split()) < 40

    def test_the_target_bypass_fails_closed_even_without_the_key_field(self) -> None:
        verdict = evaluate_authority(
            ActionRequest(action=EVIDENCE_DELETE, project_id=PROJECT,
                          operator_id=OP, actor=REQUESTER,
                          target_ref="operator note", now=T2,
                          correlation_id=SCOPE),
            EvidenceContext(credential=CREDENTIAL, decisions=(_approval_row(
                rationale="operator note"),)))
        assert verdict.refusal is not None
        assert verdict.refusal.code == PROPOSAL
        assert verdict.requirement == REQUIREMENT_TARGET

    def test_the_controls_still_bite_at_the_policys_own_keys(self) -> None:
        allowed = evaluate_authority(
            ActionRequest(action=PUBLISH, project_id=PROJECT, operator_id=OP,
                          actor=REQUESTER, command_hash="h-8",
                          head_ref="gen-1", now=T2, correlation_id=SCOPE),
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(publish_hash="h-8"),)))
        assert allowed.is_allowed()
        assert allowed.satisfied_authority == "HUMAN"
        other_key = evaluate_authority(
            ActionRequest(action=PUBLISH, project_id=PROJECT, operator_id=OP,
                          actor=REQUESTER, command_hash="h-8",
                          head_ref="gen-1", now=T2, correlation_id=SCOPE),
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(other_hash="h-8"),)))
        assert other_key.refusal is not None
        assert other_key.refusal.code == PROPOSAL
        assert other_key.requirement == REQUIREMENT_BINDING

    def test_the_window_cannot_be_switched_off_by_the_request(self) -> None:
        # A request-supplied window is refused outright ...
        refused = evaluate_authority(
            {"action": DIRECTION_CHANGE, "project_id": PROJECT, "operator_id": OP,
             "actor": REQUESTER, "command_hash": "h-7", "head_ref": "gen-1",
             "window_seconds": 0, "correlation_id": SCOPE},
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(direction_hash="h-7"),)))
        assert refused.refusal is not None
        assert refused.refusal.code == MALFORMED_PAYLOAD
        # ... and omitting the clock cannot skip the row's window.
        skipped = evaluate_authority(
            ActionRequest(action=DIRECTION_CHANGE, project_id=PROJECT,
                          operator_id=OP, actor=REQUESTER, command_hash="h-7",
                          head_ref="gen-1", correlation_id=SCOPE),
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(direction_hash="h-7"),)))
        assert skipped.refusal is not None
        assert skipped.refusal.code == MALFORMED_PAYLOAD
        assert skipped.requirement == REQUIREMENT_DECISION
        assert str(DEFAULT_APPROVAL_WINDOW_SECONDS) in skipped.refusal.detail

    def test_a_zero_window_row_needs_no_clock(self) -> None:
        # `window_seconds == 0` keeps its explicit opt-in semantics: a row that
        # declares no window needs no clock declaration (pinned as a variant).
        rows = tuple(replace(row, window_seconds=0)
                     for row in DEFAULT_AUTHORITY_ROWS)
        policy = _variant(*rows)
        assert all(row.window_seconds == 0 for row in policy.rows)
        verdict = _evaluate_authority(
            ActionRequest(action=DIRECTION_CHANGE, project_id=PROJECT,
                          operator_id=OP, actor=REQUESTER, command_hash="h-7",
                          head_ref="gen-1", correlation_id=SCOPE),
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(direction_hash="h-7"),)),
            policy)
        assert verdict.is_allowed()
        assert verdict.approval is not None
        assert verdict.approval.window_seconds == 0
        assert verdict.approval.age_seconds is None

    def test_the_approval_layer_is_given_the_rows_window(self) -> None:
        # Past T1 by two default windows: the row's own window decides, and the
        # request had no say in it.
        verdict = evaluate_authority(
            ActionRequest(action=PUBLISH, project_id=PROJECT, operator_id=OP,
                          actor=REQUESTER, command_hash="h-8", head_ref="gen-1",
                          now=T6, correlation_id=SCOPE),
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(publish_hash="h-8"),)))
        assert verdict.approval is not None
        assert verdict.approval.window_seconds == DEFAULT_APPROVAL_WINDOW_SECONDS
        assert verdict.approval.state == EXPIRED
        assert verdict.approval.age_seconds == 2 * DEFAULT_APPROVAL_WINDOW_SECONDS
        assert verdict.refusal is not None
        assert verdict.refusal.code == PROPOSAL


class TestTotality:
    """P1-b: no evaluation path raises to the caller; every denial is coded."""

    def test_the_director_reproduction_refuses_instead_of_raising(self) -> None:
        # Credentialed HUMAN action, approved decision, no scope declared.
        verdict = evaluate_authority(
            ActionRequest(action=PUBLISH, project_id=PROJECT, operator_id=OP,
                          actor=REQUESTER, command_hash="h-8",
                          head_ref="gen-1", now=T2),
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(publish_hash="h-8"),)))
        assert verdict.verdict == REFUSED
        assert verdict.refusal is not None
        assert verdict.refusal.code in GOVERNANCE_REFUSAL_CODES
        assert verdict.refusal.code == MALFORMED_PAYLOAD
        assert verdict.refusal.detail.strip()

    def test_the_same_reproduction_through_the_mapping_path_is_coded(self) -> None:
        verdict = evaluate_authority(
            {"action": PUBLISH, "project_id": PROJECT, "operator_id": OP,
             "actor": REQUESTER, "command_hash": "h-8", "head_ref": "gen-1",
             "now": T2},
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(publish_hash="h-8"),)))
        assert verdict.refusal is not None
        assert verdict.refusal.code == MALFORMED_PAYLOAD
        assert verdict.requirement == REQUIREMENT_DECISION

    def test_the_mapping_and_typed_paths_agree_on_the_refusal(self) -> None:
        request = ActionRequest(action=CONTRADICTION_DECLARE,
                                project_id=PROJECT, operator_id=OP,
                                actor=REQUESTER, now=T2, correlation_id=SCOPE)
        context = EvidenceContext(credential=CREDENTIAL,
                                  decisions=(_approval_row(),))
        typed = evaluate_authority(request, context)
        mapped = evaluate_authority(request.to_mapping(), context)
        assert typed.verdict == mapped.verdict == ALLOWED
        assert typed.digest() == mapped.digest()

    def test_a_request_of_the_wrong_type_is_refused(self) -> None:
        for hostile in (None, 42, "PUBLISH", object()):
            verdict = evaluate_authority(hostile)  # type: ignore[arg-type]
            assert verdict.verdict == REFUSED
            assert verdict.refusal is not None
            assert verdict.refusal.code == MALFORMED_PAYLOAD

    def test_an_unreadable_context_or_row_is_refused(self) -> None:
        cases: tuple[Any, ...] = (
            {"not": "a context"},
            EvidenceContext(credential={"operator_id": OP}),
            EvidenceContext(credential=CREDENTIAL, decisions=({"event_id": "x"},)),
            EvidenceContext(credential=CREDENTIAL, decisions=(None,)),
            EvidenceContext(credential=CREDENTIAL, decisions="not-a-row-tuple"),
        )
        for context in cases:
            verdict = evaluate_authority(
                ActionRequest(action=CONTRADICTION_DECLARE, project_id=PROJECT,
                              operator_id=OP, actor=REQUESTER,
                              correlation_id=SCOPE),
                context)  # type: ignore[arg-type]
            assert verdict.verdict == REFUSED, context
            assert verdict.refusal is not None
            assert verdict.refusal.code == MALFORMED_PAYLOAD
            # The *pre-check* names the unreadable shape; the backstop message
            # would mean the shape check failed to run at all.
            assert "unreadable evidence context" in verdict.refusal.detail, context
            assert verdict.refusal.detail.strip()

    def test_a_wrongly_typed_request_field_is_refused(self) -> None:
        request = ActionRequest(action=WEB_SEARCH, project_id=PROJECT,
                                rationale=5)  # type: ignore[arg-type]
        verdict = evaluate_authority(request)
        assert verdict.refusal is not None
        assert verdict.refusal.code == MALFORMED_PAYLOAD
        assert "rationale" in verdict.refusal.detail

    def test_no_hostile_request_shape_raises(self) -> None:
        shapes: tuple[Any, ...] = (
            {},
            {"action": None, "project_id": None},
            {"action": WEB_SEARCH},
            {"project_id": PROJECT},
            {"action": WEB_SEARCH, "project_id": PROJECT, "actor": [1]},
            {"action": PUBLISH, "project_id": PROJECT, "operator_id": OP,
             "command_hash": "APPROVED", "binding_key": "decision"},
            {"action": PUBLISH, "project_id": PROJECT, "operator_id": OP,
             "actor": REQUESTER, "target_key": "rationale"},
            {"action": WEB_SEARCH, "project_id": PROJECT, "window_seconds": -1},
            {"action": WEB_READ, "project_id": PROJECT, "now": "not-a-clock"},
            {"action": CONTRADICTION_DECLARE, "project_id": PROJECT,
             "operator_id": OP, "actor": REQUESTER},
            {"action": EVIDENCE_DELETE, "project_id": PROJECT, "operator_id": OP,
             "actor": REQUESTER},
            {"action": DIRECTION_CHANGE, "project_id": PROJECT, "operator_id": OP,
             "actor": REQUESTER, "command_hash": "h-7", "head_ref": "gen-1"},
            {"action": EXTERNAL, "project_id": PROJECT, "operator_id": OP,
             "actor": REQUESTER, "command_hash": "h-9", "head_ref": "gen-1"},
            {"action": "NOT_AN_ACTION", "project_id": PROJECT},
            {"action": HYPOTHESIS_MODIFY, "project_id": PROJECT,
             "rationale": 7},
            {"action": HYPOTHESIS_MODIFY, "project_id": PROJECT},
            {"action": SANDBOX_RUN, "project_id": PROJECT, "authority": "HUMAN"},
            ActionRequest(action=CONTRADICTION_DECLARE, project_id=PROJECT,
                          operator_id=OP, actor=REQUESTER, now=T2, correlation_id=SCOPE),
        )
        contexts: tuple[Any, ...] = (
            None,
            EvidenceContext(),
            EvidenceContext(credential=CREDENTIAL),
            EvidenceContext(credential=CREDENTIAL, decisions=(_approval_row(),)),
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(operator=""),)),
            EvidenceContext(credential=CREDENTIAL, decisions=(None,)),
        )
        for shape in shapes:
            for context in contexts:
                verdict = evaluate_authority(shape, context)  # type: ignore[arg-type]
                assert verdict.verdict in VERDICTS, (shape, context)
                if verdict.is_allowed():
                    assert verdict.refusal is None
                else:
                    assert verdict.refusal is not None, (shape, context)
                    assert verdict.refusal.code in GOVERNANCE_REFUSAL_CODES
                    assert verdict.refusal.detail.strip()
                    assert verdict.requirement in REQUIREMENTS

    def test_the_clock_predicate_is_closed(self) -> None:
        assert _is_readable_timestamp(T1)
        assert _is_readable_timestamp("2026-09-24T09:00:00Z")
        for bad in ("", "yesterday", "2026-13-01T00:00:00+00:00", 5, None):
            assert not _is_readable_timestamp(bad)  # type: ignore[arg-type]


class TestIndependence:
    """P2 (item 3): an operator does not ratify their own act."""

    def _request(self, actor: str) -> ActionRequest:
        return ActionRequest(action=CONTRADICTION_DECLARE, project_id=PROJECT,
                             operator_id=OP, actor=actor, now=T2, correlation_id=SCOPE)

    def test_a_self_approved_act_is_refused(self) -> None:
        verdict = evaluate_authority(
            self._request(OP),
            EvidenceContext(credential=CREDENTIAL, decisions=(_approval_row(),)))
        assert verdict.verdict == REFUSED
        assert verdict.refusal is not None
        assert verdict.refusal.code == ROLE
        assert verdict.requirement == REQUIREMENT_INDEPENDENCE
        assert OP in verdict.refusal.detail

    def test_a_self_approving_human_act_is_refused_too(self) -> None:
        verdict = evaluate_authority(
            ActionRequest(action=PUBLISH, project_id=PROJECT, operator_id=OP,
                          actor=OP, command_hash="h-8", head_ref="gen-1",
                          now=T2, correlation_id=SCOPE),
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(publish_hash="h-8"),)))
        assert verdict.refusal is not None
        assert verdict.refusal.code == ROLE
        assert verdict.requirement == REQUIREMENT_INDEPENDENCE

    def test_an_independent_requester_is_allowed(self) -> None:
        # The R4 analogue: the review belongs to a party other than the reviewed
        # (test_agent_runtime.py:1623 "a child run never reviews its own reviewer").
        verdict = evaluate_authority(
            self._request(REQUESTER),
            EvidenceContext(credential=CREDENTIAL, decisions=(_approval_row(),)))
        assert verdict.is_allowed()
        assert verdict.satisfied_authority == "REVIEWER"
        assert verdict.actor == REQUESTER
        assert verdict.approval is not None
        assert verdict.approval.approver_operator_id == OP

    def test_an_actor_name_that_is_not_the_decider_is_allowed(self) -> None:
        for actor in ("researcher", "DIRECTOR", "critic"):
            assert evaluate_authority(
                self._request(actor),
                EvidenceContext(credential=CREDENTIAL,
                                decisions=(_approval_row(),))).is_allowed(), actor

    def test_two_operator_ids_are_treated_as_distinct(self) -> None:
        # Documented limit (R5-REATTACK item 3 — no identity registry): the rule
        # compares the requesting `actor` to the recorded decider's `operator_id`
        # as *strings*. `op-2` (credentialed) may decide an act `actor='op-1'`
        # requested — the plane cannot tell the two ids are one human. Recorded
        # as a limit, pinned as behaviour, not claimed as a fix.
        allowed = evaluate_authority(
            ActionRequest(action=CONTRADICTION_DECLARE, project_id=PROJECT,
                          operator_id=OP2, actor=OP, now=T2,
                          correlation_id=SCOPE),
            EvidenceContext(credential=OTHER_CREDENTIAL,
                            decisions=(_decision("ev-1", operator=OP2),)))
        assert allowed.is_allowed()
        assert allowed.satisfied_authority == "REVIEWER"
        assert allowed.evidence == (OP2, "ev-1")
        # The rule still bites for the *same* id: op-2 deciding its own act.
        refused = evaluate_authority(
            ActionRequest(action=CONTRADICTION_DECLARE, project_id=PROJECT,
                          operator_id=OP2, actor=OP2, now=T2,
                          correlation_id=SCOPE),
            EvidenceContext(credential=OTHER_CREDENTIAL,
                            decisions=(_decision("ev-1", operator=OP2),)))
        assert refused.refusal is not None
        assert refused.refusal.code == ROLE
        assert refused.requirement == REQUIREMENT_INDEPENDENCE

    def test_an_unattributable_decision_fails_closed(self) -> None:
        verdict = evaluate_authority(
            self._request(REQUESTER),
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(operator=""),)))
        assert verdict.refusal is not None
        assert verdict.refusal.code == MALFORMED_PAYLOAD
        assert verdict.requirement == REQUIREMENT_INDEPENDENCE

    def test_an_unnamed_requester_fails_closed(self) -> None:
        verdict = evaluate_authority(
            self._request(""),
            EvidenceContext(credential=CREDENTIAL, decisions=(_approval_row(),)))
        assert verdict.refusal is not None
        assert verdict.refusal.code == MALFORMED_PAYLOAD
        assert verdict.requirement == REQUIREMENT_INDEPENDENCE

    def test_an_agent_action_needs_no_independence(self) -> None:
        verdict = evaluate_authority(
            ActionRequest(action=WEB_SEARCH, project_id=PROJECT, actor=OP))
        assert verdict.is_allowed()


class TestProvenanceAndTrustBoundary:
    """P2 (item 4) re-stamping, and P2 (item 6) the documented trust boundary."""

    def test_a_verdict_cannot_be_restamped_with_another_policys_provenance(self) -> None:
        assert not hasattr(authority_module, "with_policy")
        for name, source in _package_sources().items():
            assert "with_policy" not in source, name
            assert "replace(verdict" not in source, name
        verdict = _evaluate(MATRIX_COVERAGE[0])
        assert verdict.policy_id == "hermes-governance"
        assert verdict.policy_version == POLICY_VERSION

    def test_the_verdict_names_the_policy_that_decided_it(self) -> None:
        variant = _variant(*DEFAULT_AUTHORITY_ROWS, version=7)
        verdict = _evaluate_authority(
            ActionRequest(action=WEB_SEARCH, project_id=PROJECT),
            None,
            variant)
        assert (verdict.policy_id, verdict.policy_version) == (
            "hermes-governance", 7)
        assert verdict.digest() == digest_of(verdict.to_mapping())
        assert _evaluate(MATRIX_COVERAGE[0]).policy_version == POLICY_VERSION

    def test_the_trust_boundary_is_documented_in_both_modules(self) -> None:
        # Normalised prose, so the claim can be re-flowed without hiding: the rows
        # are evaluated as given, the read belongs to the enforcement path, and
        # the plane states what it cannot do.
        for module in (authority_module, approvals_module):
            flat = " ".join(_module_source(module).replace("**", "").split())
            assert "as given" in flat, module.__name__
            assert "journal" in flat, module.__name__
            assert "enforcement path" in flat, module.__name__
            assert "cannot" in flat, module.__name__

    def test_rows_are_evaluated_as_given(self) -> None:
        # A wholly forged but well-formed row cannot be detected here: the plane
        # holds no read. Recorded as a documented limit, pinned as behaviour so
        # the claim cannot drift.
        forged = _approval_row(publish_hash="h-8", operator=OP)
        verdict = evaluate_authority(
            ActionRequest(action=PUBLISH, project_id=PROJECT, operator_id=OP,
                          actor=REQUESTER, command_hash="h-8",
                          head_ref="gen-1", now=T2, correlation_id=SCOPE),
            EvidenceContext(credential=CREDENTIAL, decisions=(forged,)))
        assert verdict.is_allowed()
        assert verdict.evidence == (OP, "ev-1")

    # ── R5-REATTACK E2 (FIX-2): the policy is canonical at the public surface ──

    @staticmethod
    def _attacker_publish_policy() -> Policy:
        """R5_REREPORT item 1, evasion 2 — the HUMAN twin of the attack.

        A legal v2 row (every `PolicyRow.__post_init__` invariant holds) whose
        `binding_key='decision'` lets the recorded decision's own verdict verb
        satisfy the 'command hash' check that v1 was meant to close.
        """
        permissive = PolicyRow(action=PUBLISH, authority="HUMAN",
                               refusal_code=ROLE,
                               credential_refusal_code=OPERATOR,
                               record_refusal_code=PROPOSAL,
                               binding_refusal_code=PROPOSAL,
                               head_refusal_code=STALE,
                               binding_key="decision", head_key="",
                               window_seconds=0)
        return Policy(policy_id="attacker-policy", version=1, rows=(permissive,))

    @staticmethod
    def _attacker_restricted_policy() -> Policy:
        """The REVIEWER/RESTRICTED twin: `target_key='rationale'` on EVIDENCE_DELETE."""
        permissive = PolicyRow(action=EVIDENCE_DELETE, authority="REVIEWER",
                               restricted=True, refusal_code=ROLE,
                               credential_refusal_code=OPERATOR,
                               record_refusal_code=PROPOSAL,
                               binding_refusal_code=PROPOSAL,
                               target_key="rationale", window_seconds=0)
        return Policy(policy_id="attacker-policy", version=1, rows=(permissive,))

    def _attacker_cases(self) -> tuple[tuple[str, ActionRequest,
                                            EvidenceContext, Policy], ...]:
        """The two E2 constructions: (label, request, context, attacker policy)."""
        publish = (
            "publish/human",
            ActionRequest(action=PUBLISH, project_id=PROJECT, operator_id=OP,
                          actor=REQUESTER, command_hash="APPROVED",
                          head_ref="gen-1", now=T2, correlation_id=SCOPE),
            EvidenceContext(credential=CREDENTIAL, decisions=(_approval_row(),)),
            self._attacker_publish_policy())
        delete = (
            "evidence-delete/restricted",
            ActionRequest(action=EVIDENCE_DELETE, project_id=PROJECT,
                          operator_id=OP, actor=REQUESTER,
                          target_ref="operator note", now=T2,
                          correlation_id=SCOPE),
            EvidenceContext(credential=CREDENTIAL,
                            decisions=(_approval_row(rationale="operator note"),)),
            self._attacker_restricted_policy())
        return (publish, delete)

    def test_a_substituted_policy_is_refused_at_the_public_entry(self) -> None:
        # The killing test (R5_REREPORT item 1): a caller hands the public entry
        # a matrix it authored. Neither keyword nor positional substitution is
        # honoured — each is a coded MALFORMED_PAYLOAD refusal (never a TypeError,
        # never a silent ignore), naming the canonical policy's provenance.
        for label, request, context, attacker in self._attacker_cases():
            for verdict in (
                evaluate_authority(request, context, policy=attacker),
                evaluate_authority(request, context, attacker),
            ):
                assert verdict.verdict == REFUSED, label
                assert verdict.refusal is not None, label
                assert verdict.refusal.code == MALFORMED_PAYLOAD, label
                assert verdict.refusal.detail == POLICY_SUBSTITUTION_DETAIL, label
                assert verdict.requirement == REQUIREMENT_POLICY, label
                assert verdict.policy_id == GOVERNANCE_POLICY.policy_id, label

    def test_the_same_substitution_grants_through_the_private_seam(self) -> None:
        # The other half of the pin: the attack is *real*. The identical
        # construction, reached through the private seam, still grants — so the
        # public refusal above exercises the true evaluation path, not a strawman.
        for label, request, context, attacker in self._attacker_cases():
            verdict = _evaluate_authority(request, context, attacker)
            assert verdict.is_allowed(), label
            assert verdict.policy_id == "attacker-policy", label
        granted = _evaluate_authority(*self._attacker_cases()[0][1:])
        assert granted.satisfied_authority == "HUMAN"
        restricted = _evaluate_authority(*self._attacker_cases()[1][1:])
        assert restricted.satisfied_authority == "REVIEWER/RESTRICTED"

    def test_the_canonical_binding_is_total_on_the_public_surface(self) -> None:
        # `evaluate_approval` and `resolve` bind the canonical document too: a
        # `policy=` handed to either is refused as data, and the same document
        # still substitutes through their private seams.
        attacker = self._attacker_publish_policy()
        evaluation = evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT), (),
            policy=attacker)
        assert evaluation.state == MISSING
        assert not evaluation.approved
        assert evaluation.refusal is not None
        assert evaluation.refusal.code == MALFORMED_PAYLOAD
        assert evaluation.refusal.detail == POLICY_SUBSTITUTION_DETAIL

        resolution = resolve(PUBLISH, policy=attacker)
        assert resolution.row is None
        assert not resolution.allowed_by_policy
        assert resolution.refusal is not None
        assert resolution.refusal.code == MALFORMED_PAYLOAD
        assert resolution.refusal.detail == POLICY_SUBSTITUTION_DETAIL

        assert _resolve(PUBLISH, attacker).row is not None
        assert _evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT), (), attacker
        ).policy_id == "attacker-policy"

    def test_the_recorded_limits_are_recorded(self) -> None:
        source = _module_source(authority_module)
        assert "design limits" in source
        assert "accepted residuals" in source
        # The residuals are *named* in the docstring and implemented nowhere: no
        # lease concept, no scope resolver, no code or table smuggled in.
        assert "no lease generation" in source.lower()
        for name, body in _package_sources().items():
            assert "lease_generation" not in body, name
            assert "lease" not in _referenced_names(body), name


# ═══════════════════════ authority shapes ═══════════════════════


class TestAuthorityShapes:
    def test_the_request_schema_carries_no_authority_field(self) -> None:
        assert "authority" not in REQUEST_KEYS
        assert "level" not in REQUEST_KEYS
        assert "satisfied_authority" not in REQUEST_KEYS

    def test_the_request_schema_is_closed(self) -> None:
        with pytest.raises(GovernanceFormatError):
            ActionRequest.from_mapping({"action": WEB_SEARCH, "project_id": "p1",
                                        "authority": "HUMAN"})
        request = ActionRequest.from_mapping(
            {"action": WEB_SEARCH, "project_id": "p1"})
        assert request.to_mapping()["action"] == WEB_SEARCH
        assert ActionRequest.from_mapping(request.to_mapping()) == request
        assert set(request.to_mapping()) == set(REQUEST_KEYS)

    def test_the_scope_defaults_to_the_correlation_id(self) -> None:
        request = ActionRequest(action=PUBLISH, project_id=PROJECT,
                                correlation_id=SCOPE)
        assert request.scope == SCOPE
        assert ActionRequest(action=PUBLISH, project_id=PROJECT,
                             approval_scope="explicit").scope == "explicit"

    def test_an_agent_action_needs_no_recorded_evidence(self) -> None:
        verdict = evaluate_authority(ActionRequest(action=SANDBOX_RUN,
                                                   project_id=PROJECT))
        assert verdict.is_allowed()
        assert verdict.satisfied_authority == "AGENT"
        assert verdict.evidence == ()
        assert verdict.approval is None

    def test_authority_is_read_from_rows_not_from_the_actor_name(self) -> None:
        # The request may call itself anything; only the recorded credential and
        # the recorded decision count.
        request = ActionRequest(action=PUBLISH, project_id=PROJECT,
                                actor="DIRECTOR", actor_is_human=True,
                                operator_id=OP, command_hash="h-8",
                                head_ref="gen-1", now=T2,
                                correlation_id=SCOPE)
        assert evaluate_authority(request, EvidenceContext()).refusal is not None
        verdict = evaluate_authority(
            request, EvidenceContext(
                credential=CREDENTIAL,
                decisions=(_approval_row(publish_hash="h-8"),)))
        assert verdict.is_allowed()

    def test_a_decision_row_for_another_project_cannot_authorize(self) -> None:
        request = ActionRequest(action=CONTRADICTION_DECLARE,
                                project_id=PROJECT, operator_id=OP,
                                actor=REQUESTER, now=T2, correlation_id=SCOPE)
        verdict = evaluate_authority(
            request, EvidenceContext(
                credential=CREDENTIAL,
                decisions=(_approval_row(project=OTHER_PROJECT),)))
        assert verdict.refusal is not None
        assert verdict.refusal.code == PROPOSAL
        assert verdict.approval is not None
        assert verdict.approval.foreign_project_rows == 1

    def test_the_verdict_names_the_rows_it_read(self) -> None:
        request = ActionRequest(action=CONTRADICTION_DECLARE,
                                project_id=PROJECT, operator_id=OP,
                                actor=REQUESTER, now=T2, correlation_id=SCOPE)
        verdict = evaluate_authority(
            request, EvidenceContext(credential=CREDENTIAL,
                                     decisions=(_approval_row(),)))
        assert verdict.is_allowed()
        assert verdict.evidence == (OP, "ev-1")
        assert verdict.approval is not None
        assert verdict.approval.approver_operator_id == OP

    def test_a_denied_decision_names_the_denier_and_the_reason(self) -> None:
        request = ActionRequest(action=CONTRADICTION_DECLARE,
                                project_id=PROJECT, operator_id=OP,
                                actor=REQUESTER, now=T2, correlation_id=SCOPE)
        verdict = evaluate_authority(
            request, EvidenceContext(
                credential=CREDENTIAL,
                decisions=(_approval_row(verdict=DENIED,
                                         reason="out of scope"),)))
        assert verdict.refusal is not None
        assert "out of scope" in verdict.refusal.detail
        assert OP in verdict.refusal.detail
        assert "DENIED" in verdict.refusal.detail

    def test_a_non_decisive_verdict_never_approves(self) -> None:
        request = ActionRequest(action=CONTRADICTION_DECLARE,
                                project_id=PROJECT, operator_id=OP,
                                actor=REQUESTER, now=T2, correlation_id=SCOPE)
        row = DecisionRow(event_id="ev-1", project_id=PROJECT,
                          correlation_id=SCOPE, payload={"verdict": "APPROVED"},
                          created_at=T1)
        verdict = evaluate_authority(request,
                                     EvidenceContext(credential=CREDENTIAL,
                                                     decisions=(row,)))
        assert verdict.refusal is not None
        assert verdict.refusal.code == PROPOSAL
        assert verdict.approval is not None
        assert verdict.approval.state == PENDING

    def test_a_decision_row_without_a_scope_is_not_in_scope(self) -> None:
        request = ActionRequest(action=CONTRADICTION_DECLARE,
                                project_id=PROJECT, operator_id=OP,
                                actor=REQUESTER, now=T2, correlation_id=SCOPE)
        verdict = evaluate_authority(
            request, EvidenceContext(credential=CREDENTIAL,
                                     decisions=(_approval_row(
                                         scope=""),)))
        assert verdict.refusal is not None
        assert verdict.approval is not None
        assert verdict.approval.foreign_scope_rows == 1

    def test_an_ungoverned_action_denies_by_default(self) -> None:
        verdict = evaluate_authority(ActionRequest(
            action="INSTALL_SUBSTRATE", project_id=PROJECT))
        assert verdict.refusal is not None
        assert verdict.refusal.code == ROLE
        assert verdict.requirement == REQUIREMENT_POLICY
        assert "deny by default" in verdict.refusal.detail

    def test_a_malformed_request_is_refused_as_data_never_raised(self) -> None:
        verdict = evaluate_authority({"action": PUBLISH, "project_id": PROJECT,
                                      "authority": "HUMAN"})
        assert verdict.verdict == REFUSED
        assert verdict.refusal is not None
        assert verdict.refusal.code == MALFORMED_PAYLOAD
        assert verdict.refusal.requirement == REQUIREMENT_REQUEST
        assert "schema violation" in verdict.refusal.detail

    def test_the_actor_name_is_recorded_but_grants_nothing(self) -> None:
        # Two callers asking for the same act with different names get the same
        # verdict — the actor string is evidence, not authority.
        first = evaluate_authority(ActionRequest(action=WEB_READ,
                                                 project_id=PROJECT,
                                                 actor="researcher"))
        second = evaluate_authority(ActionRequest(action=WEB_READ,
                                                  project_id=PROJECT,
                                                  actor="synthesizer"))
        assert first.verdict == second.verdict == ALLOWED
        assert first.satisfied_authority == second.satisfied_authority == "AGENT"
        assert first.actor == "researcher"
        assert first.digest() != second.digest()

    def test_the_credential_snapshot_refuses_a_secret(self) -> None:
        for key in SECRET_KEYS:
            with pytest.raises(GovernanceFormatError):
                CredentialRow.from_mapping({"operator_id": OP, key: "hunter2"})
        with pytest.raises(GovernanceFormatError):
            CredentialRow.from_mapping({"operator_id": OP, "issuer": "x"})
        with pytest.raises(GovernanceFormatError):
            CredentialRow.from_mapping({"name": "no id"})
        row = CredentialRow.from_mapping({"operator_id": OP, "name": "Operator One",
                                          "created_at": T1})
        assert row == CREDENTIAL
        assert "token" not in row.to_mapping()

    def test_the_verdict_mapping_round_trips_its_shape(self) -> None:
        verdict = _evaluate(MATRIX_COVERAGE[0])
        mapping = verdict.to_mapping()
        assert mapping["verdict"] == ALLOWED
        assert mapping["refusal"] is None
        assert set(mapping) == {
            "action", "project_id", "verdict", "actor", "required_authority",
            "satisfied_authority", "requirement", "policy_id", "policy_version",
            "evidence", "conflicting_rows", "approval", "refusal"}

    def test_a_governance_refusal_round_trips_and_refuses_a_new_code(self) -> None:
        refusal = GovernanceRefusal(code=ROLE, detail="no authority", action="X")
        assert GovernanceRefusal.from_mapping(refusal.to_mapping()) == refusal
        with pytest.raises(GovernanceFormatError):
            GovernanceRefusal.from_mapping({"code": "BRAND_NEW", "detail": "x"})
        with pytest.raises(GovernanceFormatError):
            GovernanceRefusal.from_mapping({"code": ROLE, "detail": "  "})
        assert refusal.as_dict() == {"rejected": True, "code": ROLE,
                                     "detail": "no authority"}

    def test_the_verdicts_vocabulary_is_closed(self) -> None:
        assert VERDICTS == (ALLOWED, REFUSED)
        verdict = _evaluate(MATRIX_COVERAGE[0])
        assert verdict.verdict in VERDICTS
        assert set(verdict.as_dict()) >= {"action", "verdict", "allowed"}


# ═══════════════════════ the approval lifecycle ═══════════════════════


DETERMINISM_FIXTURES: tuple[tuple[str, tuple[DecisionRow, ...], dict[str, Any],
                                   str, str], ...] = (
    ("missing", (), {}, MISSING, PROPOSAL),
    ("pending", (_decision("ev-1", verdict="CURATE_KNOWLEDGE"),), {},
     PENDING, PROPOSAL),
    ("approved", (_approval_row(),), {}, APPROVED, ""),
    ("approved-within-window", (_approval_row(),),
     {"now": T2, "window_seconds": 3600}, APPROVED, ""),
    ("approved-at-window-edge", (_approval_row(),),
     {"now": T3, "window_seconds": 3600}, APPROVED, ""),
    ("expired", (_approval_row(),), {"now": T5, "window_seconds": 3600},
     EXPIRED, PROPOSAL),
    ("denied", (_approval_row(verdict=DENIED),), {}, DENIED, PROPOSAL),
    ("rejected", (_approval_row(verdict="REJECTED"),), {}, DENIED, PROPOSAL),
    ("denied-then-approved",
     (_approval_row(verdict=DENIED), _approval_row(event_id="ev-2",
                                                   created_at=T2)),
     {}, APPROVED, ""),
    ("approved-then-denied",
     (_approval_row(), _approval_row(event_id="ev-2", created_at=T2,
                                     verdict=DENIED)),
     {}, DENIED, PROPOSAL),
    ("non-decisive-then-approved",
     (_decision("ev-0", verdict="SOMETHING", created_at=T1), _approval_row()),
     {}, APPROVED, ""),
)


@pytest.mark.parametrize("label,rows,extra,state,code",
                         DETERMINISM_FIXTURES,
                         ids=[item[0] for item in DETERMINISM_FIXTURES])
def test_approval_fixture(label: str, rows: tuple[DecisionRow, ...],
                          extra: dict[str, Any], state: str, code: str) -> None:
    request = ApprovalRequest(scope=SCOPE, project_id=PROJECT, **extra)
    evaluation = evaluate_approval(request, rows)
    assert evaluation.state == state, (label, evaluation.to_mapping())
    if code:
        assert evaluation.refusal is not None
        assert evaluation.refusal.code == code
    else:
        assert evaluation.refusal is None
        assert evaluation.approved


class TestApprovalLifecycle:
    def test_the_state_vocabulary_is_closed(self) -> None:
        assert STATES == (MISSING, PENDING, APPROVED, DENIED, EXPIRED)
        assert set(STATE_REFUSAL_CODES) == {MISSING, PENDING, DENIED, EXPIRED}
        assert set(STATE_REFUSAL_CODES.values()) == {PROPOSAL}

    def test_the_lifecycle_defaults_to_the_shipped_policy(self) -> None:
        assert evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT)).policy_id == (
            GOVERNANCE_POLICY.policy_id)

    def test_a_missing_scope_refuses_with_a_detail(self) -> None:
        evaluation = evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT))
        assert evaluation.state == MISSING
        assert evaluation.refusal is not None
        assert evaluation.refusal.code == PROPOSAL
        assert evaluation.refusal.detail.strip()
        assert evaluation.refusal.evidence == ()

    def test_a_denial_is_data_and_names_the_row(self) -> None:
        evaluation = evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT),
            (_approval_row(verdict=DENIED, reason="cost"),))
        assert evaluation.state == DENIED
        assert evaluation.denial_count == 1
        assert evaluation.refusal is not None
        assert evaluation.refusal.evidence == ("ev-1",)
        assert "cost" in evaluation.refusal.detail
        assert evaluation.approver_operator_id == OP

    def test_repeated_decisive_rows_are_visible(self) -> None:
        evaluation = evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT),
            (_approval_row(), _approval_row(event_id="ev-2", created_at=T2)))
        assert evaluation.decisive_count == 2
        assert evaluation.repeated_decisions
        assert evaluation.approved

    def test_a_single_decisive_row_is_not_repeated(self) -> None:
        evaluation = evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT),
            (_approval_row(),))
        assert evaluation.decisive_count == 1
        assert not evaluation.repeated_decisions

    def test_no_window_means_no_expiry_and_says_so(self) -> None:
        evaluation = evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT, now=T5),
            (_approval_row(),))
        assert evaluation.state == APPROVED
        assert evaluation.age_seconds is None
        assert evaluation.window_seconds == 0

    def test_age_is_derived_from_the_declared_now(self) -> None:
        evaluation = evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT, now=T2,
                            window_seconds=3600),
            (_approval_row(),))
        assert evaluation.age_seconds == 1800

    def test_a_malformed_now_is_an_integrity_incident(self) -> None:
        with pytest.raises(GovernanceFormatError):
            evaluate_approval(
                ApprovalRequest(scope=SCOPE, project_id=PROJECT,
                                now="yesterday", window_seconds=60),
                (_approval_row(),))

    def test_a_malformed_created_at_is_an_integrity_incident(self) -> None:
        with pytest.raises(GovernanceFormatError):
            evaluate_approval(
                ApprovalRequest(scope=SCOPE, project_id=PROJECT, now=T2,
                                window_seconds=60),
                (_approval_row(created_at="not-a-timestamp"),))

    def test_a_request_needs_a_scope_and_a_project(self) -> None:
        with pytest.raises(GovernanceFormatError):
            evaluate_approval(ApprovalRequest(scope="", project_id=PROJECT))
        with pytest.raises(GovernanceFormatError):
            evaluate_approval(ApprovalRequest(scope=SCOPE, project_id=""))
        with pytest.raises(GovernanceFormatError):
            evaluate_approval(ApprovalRequest(scope=SCOPE, project_id=PROJECT,
                                              window_seconds=-5))

    def test_rows_outside_the_scope_are_counted_not_used(self) -> None:
        evaluation = evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT),
            (_approval_row(scope=OTHER_SCOPE),
             _approval_row(project=OTHER_PROJECT),
             _approval_row()))
        assert evaluation.approved
        assert evaluation.foreign_scope_rows == 1
        assert evaluation.foreign_project_rows == 1
        assert [row.event_id for row in evaluation.rows] == ["ev-1"]

    def test_the_lifecycle_is_order_independent(self) -> None:
        rows = (_approval_row(created_at=T2, verdict=DENIED),
                _approval_row(event_id="ev-2", created_at=T1))
        forward = evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT), rows)
        backward = evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT),
            tuple(reversed(rows)))
        assert forward.digest() == backward.digest()
        assert forward.state == backward.state == DENIED

    def test_the_lifecycle_is_deterministic(self) -> None:
        rows = (_approval_row(), _decision("ev-2", verdict="SOMETHING",
                                           created_at=T2))
        request = ApprovalRequest(scope=SCOPE, project_id=PROJECT, now=T3,
                                  window_seconds=7200)
        first = evaluate_approval(request, rows)
        second = evaluate_approval(request, rows)
        assert first.digest() == second.digest()
        assert first == second

    def test_the_evaluation_round_trips_its_mapping(self) -> None:
        evaluation = evaluate_approval(
            ApprovalRequest(scope=SCOPE, project_id=PROJECT),
            (_approval_row(),))
        payload = evaluation.to_mapping()
        assert payload["state"] == APPROVED
        assert json.loads(canonical_json(payload)) == payload
        assert set(payload) == {
            "scope", "project_id", "state", "rows", "decisive_row",
            "decisive_count", "denial_count", "non_decisive_rows",
            "foreign_scope_rows", "foreign_project_rows", "age_seconds",
            "window_seconds", "policy_id", "policy_version", "refusal"}

    def test_a_decision_row_is_a_closed_snapshot(self) -> None:
        row = _approval_row()
        assert DecisionRow.from_mapping(row.to_mapping()) == row
        with pytest.raises(GovernanceFormatError):
            DecisionRow.from_mapping({**row.to_mapping(), "sql": "SELECT 1"})
        with pytest.raises(GovernanceFormatError):
            DecisionRow.from_mapping({"event_id": "ev-1"})
        with pytest.raises(GovernanceFormatError):
            DecisionRow.from_mapping({"event_id": "ev-1", "project_id": PROJECT,
                                      "payload": "not-a-mapping"})

    def test_the_verdict_is_read_from_the_payload_key(self) -> None:
        row = _approval_row()
        assert row.verdict() == APPROVED
        assert row.verdict(DEFAULT_VERDICT_KEY) == APPROVED
        assert row.verdict("missing_key") == ""
        assert row.binds("direction_hash", "h-7") is False
        assert row.binds("", "x") is False
        assert row.binds("direction_hash", "") is False
        assert _approval_row(direction_hash="h-7").binds("direction_hash",
                                                         "h-7") is True

    def test_approve_and_deny_vocabularies_are_mirrored(self) -> None:
        assert frozenset({"APPROVED"}) == APPROVE_VERDICTS
        assert frozenset({"DENIED", "REJECTED"}) == DENY_VERDICTS
        assert not (APPROVE_VERDICTS & DENY_VERDICTS)


# ═══════════════════════ deny-wins ═══════════════════════


class TestPolicyConflicts:
    PERMIT_ROW = PolicyRow(action=PUBLISH, authority="HUMAN",
                           refusal_code=ROLE, credential_refusal_code=OPERATOR,
                           record_refusal_code=PROPOSAL,
                           binding_refusal_code=PROPOSAL,
                           head_refusal_code=STALE,
                           binding_key=PUBLISH_BINDING_KEY, head_key=HEAD_KEY,
                           window_seconds=DEFAULT_APPROVAL_WINDOW_SECONDS,
                           effect=PERMIT)
    DENY_ROW = PolicyRow(action=PUBLISH, authority="HUMAN", effect=DENY,
                         refusal_code=OPERATOR, credential_refusal_code=OPERATOR,
                         record_refusal_code=PROPOSAL,
                         binding_refusal_code=PROPOSAL,
                         head_refusal_code=STALE,
                         binding_key=PUBLISH_BINDING_KEY, head_key=HEAD_KEY,
                         window_seconds=DEFAULT_APPROVAL_WINDOW_SECONDS)

    def _bound_request(self) -> ActionRequest:
        return ActionRequest(action=PUBLISH, project_id=PROJECT,
                             operator_id=OP, actor=REQUESTER,
                             command_hash="h-8", head_ref="gen-1", now=T2,
                             correlation_id=SCOPE)

    def _context(self) -> EvidenceContext:
        return EvidenceContext(credential=CREDENTIAL,
                               decisions=(_approval_row(publish_hash="h-8"),))

    def test_permit_alone_allows(self) -> None:
        policy = _variant(self.PERMIT_ROW)
        verdict = _evaluate_authority(self._bound_request(), self._context(),
                                      policy)
        assert verdict.is_allowed()

    def test_deny_wins_over_permit(self) -> None:
        policy = _variant(self.PERMIT_ROW, self.DENY_ROW)
        verdict = _evaluate_authority(self._bound_request(), self._context(),
                                      policy)
        assert verdict.verdict == REFUSED
        assert verdict.refusal is not None
        assert verdict.refusal.code == OPERATOR
        assert verdict.requirement == REQUIREMENT_AUTHORITY

    def test_deny_wins_regardless_of_declaration_order(self) -> None:
        policy = _variant(self.DENY_ROW, self.PERMIT_ROW)
        verdict = _evaluate_authority(self._bound_request(), EvidenceContext(),
                                      policy)
        assert verdict.verdict == REFUSED
        assert policy.rows_for(PUBLISH)[0].effect == DENY

    def test_deny_wins_over_a_higher_permit_level(self) -> None:
        permit = replace(self.PERMIT_ROW, action=WEB_SEARCH,
                         authority="AGENT", credential_refusal_code="",
                         record_refusal_code="", binding_refusal_code="",
                         head_refusal_code="", binding_key="", head_key="",
                         window_seconds=0)
        deny = replace(self.DENY_ROW, action=WEB_SEARCH)
        policy = _variant(permit, deny)
        verdict = _evaluate_authority(
            ActionRequest(action=WEB_SEARCH, project_id=PROJECT), None, policy)
        assert verdict.verdict == REFUSED
        assert verdict.refusal is not None
        assert verdict.refusal.code == OPERATOR
        assert verdict.required_authority == "HUMAN"

    def test_the_conflict_is_named_in_the_verdict_and_the_detail(self) -> None:
        policy = _variant(self.PERMIT_ROW, self.DENY_ROW)
        verdict = _evaluate_authority(self._bound_request(), EvidenceContext(),
                                      policy)
        assert verdict.conflicting_rows == ("DENY:PUBLISH", "PERMIT:PUBLISH")
        assert verdict.refusal is not None
        assert "conflicting rows" in verdict.refusal.detail
        assert "DENY:PUBLISH" in verdict.refusal.detail

    def test_the_resolution_is_deterministic_with_two_denials(self) -> None:
        second = replace(self.DENY_ROW, refusal_code=ROLE)
        policy = _variant(self.DENY_ROW, second, self.PERMIT_ROW)
        resolved = _resolve(PUBLISH, policy)
        assert resolved.denies == (self.DENY_ROW, second)
        assert resolved.row == self.DENY_ROW
        verdict = _evaluate_authority(self._bound_request(), EvidenceContext(),
                                      policy)
        assert verdict.refusal is not None
        assert verdict.refusal.code == OPERATOR

    def test_an_ungoverned_action_fails_closed_under_a_variant(self) -> None:
        policy = _variant(self.DENY_ROW)  # nothing governs WEB_SEARCH
        verdict = _evaluate_authority(
            ActionRequest(action=WEB_SEARCH, project_id=PROJECT), None, policy)
        assert verdict.refusal is not None
        assert verdict.refusal.code == ROLE
        assert verdict.requirement == REQUIREMENT_POLICY

    def test_the_shipped_policy_resolves_to_its_single_row(self) -> None:
        for row in GOVERNANCE_POLICY.rows:
            resolved = resolve(row.action)
            assert resolved.row == row
            assert resolved.permits == (row,)
            assert resolved.denies == ()


# ═══════════════════════ determinism + purity ═══════════════════════

ALLOWED_IMPORTS: dict[str, set[str]] = {
    "__init__.py": {"__future__"},
    "policy.py": {"__future__", "dataclasses", "enum", "hashlib", "json",
                  "typing"},
    "approvals.py": {"__future__", "dataclasses", "datetime", "types",
                     "typing", "hermes.governance.policy"},
    "authority.py": {"__future__", "dataclasses", "typing",
                     "hermes.governance.policy", "hermes.governance.approvals"},
}

BANNED_CALLS = {"open", "execute", "executemany", "executescript", "commit",
                "rollback", "connect", "write_text", "write_bytes", "unlink",
                "remove", "rmtree", "mkdir", "popen", "system", "write",
                "_append_event_to_db", "now", "utcnow", "fromtimestamp",
                "monotonic", "sleep"}

BANNED_NAMES = {"conn", "cursor", "sqlite3", "repositories", "execute",
                "_append_event_to_db", "Lock", "RLock", "fcntl", "msvcrt",
                "logging", "requests", "socket"}


class TestDeterminismAndPurity:
    def test_the_package_holds_only_the_four_modules(self) -> None:
        assert sorted(_package_sources()) == sorted(ALLOWED_IMPORTS)

    def test_every_module_imports_only_stdlib_and_the_planes_own_modules(self) -> None:
        for name, source in _package_sources().items():
            imports = _imported_modules(source)
            assert imports <= ALLOWED_IMPORTS[name], (name, imports)

    def test_no_module_imports_any_other_hermes_plane(self) -> None:
        banned = ("hermes.core", "hermes.research", "hermes.persistence",
                  "hermes.tools", "hermes.security", "hermes.artifacts",
                  "hermes.recovery", "hermes.vault", "hermes.agents",
                  "hermes.engineering", "hermes.vault")
        for name, source in _package_sources().items():
            for module in _direct_hermes_imports(source):
                assert module.startswith("hermes.governance"), (name, module)
                for prefix in banned:
                    assert not module.startswith(prefix), (name, module)

    def test_no_module_opens_a_connection_or_writes(self) -> None:
        for name, source in _package_sources().items():
            offenders = sorted(_calls(source) & BANNED_CALLS)
            assert not offenders, (name, offenders)
            referenced = _referenced_names(source) & BANNED_NAMES
            assert not referenced, (name, sorted(referenced))
            for fragment in ("BEGIN IMMEDIATE", "INSERT INTO", "UPDATE ",
                             "DELETE FROM", "SELECT ", "PRAGMA"):
                assert fragment not in source, (name, fragment)

    def test_no_module_holds_a_connection_cursor_or_journal_writer(self) -> None:
        for name, source in _package_sources().items():
            assert "_append_event_to_db" not in source, name
            assert "conn" not in _referenced_names(source), name
            assert "cursor" not in _referenced_names(source), name

    def test_no_module_reads_a_clock(self) -> None:
        for name, source in _package_sources().items():
            for banned in ("datetime.now", "datetime.utcnow",
                           "datetime.today", "time.time", "monotonic("):
                assert banned not in source, (name, banned)

    def test_no_module_touches_the_filesystem_or_the_network(self) -> None:
        for name, source in _package_sources().items():
            imports = _imported_modules(source)
            for banned in ("os", "io", "pathlib", "shutil", "socket",
                           "subprocess", "tempfile", "urllib", "http",
                           "requests", "glob", "pickle"):
                assert banned not in imports, (name, banned)

    def test_no_module_holds_mutable_module_state(self) -> None:
        for name, module in (("policy", policy_module),
                             ("approvals", approvals_module),
                             ("authority", authority_module)):
            mutable = {key: value for key, value in vars(module).items()
                       if isinstance(value, (dict, list, set))
                       and not key.startswith("__")}
            assert mutable == {}, (name, sorted(mutable))

    def test_the_policy_tables_are_immutable(self) -> None:
        with pytest.raises(TypeError):
            DEFAULT_AUTHORITY_ROWS[0] = DEFAULT_AUTHORITY_ROWS[1]  # type: ignore[index]
        with pytest.raises(AttributeError):
            GOVERNANCE_POLICY.rows = ()  # type: ignore[misc]

    def test_the_same_rows_in_give_the_same_verdict_out(self) -> None:
        request = ActionRequest(action=DIRECTION_CHANGE, project_id=PROJECT,
                                operator_id=OP, actor=REQUESTER,
                                command_hash="h-7", head_ref="gen-1", now=T2,
                                correlation_id=SCOPE)
        context = EvidenceContext(
            credential=CREDENTIAL,
            decisions=(_approval_row(direction_hash="h-7"),
                       _decision("ev-0", verdict="OTHER", created_at=T1)))
        first = evaluate_authority(request, context)
        second = evaluate_authority(
            request, EvidenceContext(credential=context.credential,
                                     decisions=tuple(reversed(context.decisions))))
        assert first.digest() == second.digest()
        assert first.to_mapping() == second.to_mapping()

    def test_evaluating_a_verdict_changes_nothing(self) -> None:
        before = GOVERNANCE_POLICY.digest()
        for item in MATRIX_COVERAGE:
            _evaluate(item)
        assert GOVERNANCE_POLICY.digest() == before

    def test_every_verdict_digest_is_a_sha256_hex(self) -> None:
        verdict = _evaluate(MATRIX_COVERAGE[0])
        assert verdict.digest() == digest_of(verdict.to_mapping())
        assert len(verdict.digest()) == 64
        assert GOVERNANCE_POLICY.digest() == digest_of(
            GOVERNANCE_POLICY.to_mapping())

    def test_the_plane_is_wired_to_nothing(self) -> None:
        # R6 decision (platform/r1-delta): the methodology plane's driver is the
        # single declared consumer of `evaluate_authority`'s public entry — its
        # per-stage governance preflight. src/hermes/methodology/workflows.py is
        # therefore the one named, intended exception to "no file outside this
        # package names hermes.governance". The exception is exactly that one
        # file (no spine file — cli/controller/gateway — reaches the plane);
        # nothing else is exempt.
        #
        # R7-FIX2 (P2): the eval plane is the SECOND declared consumer, and it
        # is named here rather than hidden from this check. Before this change
        # `src/hermes/eval/hostile.py` imported the governance plane through
        # `importlib.import_module("hermes." + "governance.approvals")` — a
        # string concatenation whose only function was to keep the contiguous
        # text this gate greps for out of the file. The dependency was real;
        # only its spelling evaded the check. The eval plane now reaches the
        # plane through one declared route (`hermes.eval.import_gate`, whose
        # AST-level gate reports the crossing whatever the spelling), so the
        # two files below are listed as what they are — declared consumers —
        # instead of being made invisible.
        #
        # What this gate still protects is unchanged: no *spine* file reaches
        # the governance plane, and the consumer set is now an explicit,
        # reviewable list rather than something discovered by a grep.
        allowed_consumers = {
            Path("methodology") / "workflows.py",
            # The eval plane's declared consumers: the driver module, and
            # the import gate that owns the single crossing it uses.
            Path("eval") / "hostile.py",
            Path("eval") / "import_gate.py",
        }
        hits: list[str] = []
        for path in sorted(HERMES_ROOT.rglob("*.py")):
            if PACKAGE in path.parents:
                continue
            if "hermes.governance" in path.read_text(encoding="utf-8"):
                relative = path.relative_to(HERMES_ROOT)
                if relative in allowed_consumers:
                    continue
                hits.append(str(relative))
        assert hits == []

    def test_every_declared_consumer_is_actually_a_consumer(self) -> None:
        """The exemption list must not become a hiding place.

        Every allowed consumer is exempted only while it really does name
        the plane; if one stops using it (the crossing is deleted, or the
        route is folded away), the entry is stale and this fails — so an
        exemption cannot outlive the dependency it excuses.
        """
        allowed_consumers = {
            Path("methodology") / "workflows.py",
            Path("eval") / "hostile.py",
            Path("eval") / "import_gate.py",
        }
        for relative in sorted(allowed_consumers):
            path = HERMES_ROOT / relative
            assert path.exists(), f"exempted consumer does not exist: {relative}"
            assert PACKAGE.name in path.read_text(encoding="utf-8"), (
                f"{relative} is exempted as a consumer but no longer names "
                f"the plane — drop the exemption")

    def test_the_package_exports_nothing_eagerly(self) -> None:
        assert governance_module.__all__ == []
        for module in (policy_module, approvals_module, authority_module):
            assert getattr(module, "__all__", []) == []

    def test_the_refusal_plane_never_returns_an_empty_detail(self) -> None:
        for item in MATRIX_COVERAGE:
            verdict = _evaluate(item)
            if verdict.refusal is not None:
                assert verdict.refusal.detail.strip(), item["label"]
                assert verdict.refusal.code in GOVERNANCE_REFUSAL_CODES
            else:
                assert verdict.verdict == ALLOWED
