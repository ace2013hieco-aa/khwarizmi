# HERMES RESEARCH — Q-05 APPROVED-PROPOSAL HANDOFF
## DESIGN GATE (design only; NOT implemented)

**Status:** DESIGN GATE COMPLETE — the handoff from an APPROVED
classification-action proposal to the EXISTING authority paths is **DESIGN
READY FOR IMPLEMENTATION**. No code in this task. The design is
architecture input for a future phase; it is gated behind the ratified
IDR-040 §3.5 proposal lifecycle (the human-approval gate, the
RESOLVE_CLASSIFICATION_PROPOSAL decision, the pending-proposals replay, the
operator-verdict ingestion surface).

**HEAD reconciled against:** `57fb3e9` (IDR-040 §3.5 ratification), full
suite **1184 passed**, pyright `src` **0 errors**.

---

## 1. Role and gate question

The gate question: *does an APPROVED classification-action proposal create a
new authority, or does it feed the existing ones?*

The proposal lifecycle (IDR-040 §3.5) records two facts per re-review
candidate action: the **proposal** (`ClassificationActionProposed`,
admitted by the Director through the gateway) and the **ratified human
verdict** (`ClassificationActionDecision`, ingested by the DETERMINISTIC
layer). An APPROVED decision is a *ratification fact* — it says "the human
confirmed this action". The handoff question is where that fact goes next.

The answer this design defends: **the handoff adds NO authority.** Every
`PermittedAction` already maps to an existing Hermes authority path
(`failure_classification.py`: "proposing a mechanism substitution still
requires the existing Director PROPOSE_RESEARCH_PROGRAM gateway path;
rejecting a branch still requires the existing ABANDON/EVIDENCE_TRANSITION
authority; narrowing scope still requires the S16 human amendment path").
The approved proposal is **evidence-of-ratification** for those paths — a
consumable fact, never a new executor.

---

## 2. Reconciliation against the live repository (verified facts)

| Fact | Verified at HEAD `57fb3e9` |
|---|---|
| The proposal lifecycle exists | `PROPOSE_CLASSIFICATION_ACTION` (Director-only) + `RESOLVE_CLASSIFICATION_PROPOSAL` (DETERMINISTIC, internal-only) wired in the gateway; `ClassificationActionProposed` / `ClassificationActionDecision` events; one-proposal-one-verdict; `record_operator_decision` lease-held ingestion |
| The gate is recomputed, not trusted | `requires_human_confirmation_for` derives from the class (F2); the replay and the decision validator recompute (F11 closed at `d960ba3`) |
| The permitted-action vocabulary maps to existing authorities | `PermittedAction` (7 members) ↔ `ACTION_MAP` (6 classes) ↔ the authority comment at `failure_classification.py` L92–100 |
| The gateway wires only five kinds | `PROPOSE_RESEARCH_PROGRAM`, `PROPOSE_CLASSIFICATION_ACTION`, `RESOLVE_CLASSIFICATION_PROPOSAL`, `INSERT_TASK`, `ADMIT_TASK`; everything else (incl. `ABANDON`, `EVIDENCE_TRANSITION`) is declared-but-NOT_WIRED |
| The decision event is the ratification record | appended by the gateway, `correlation_id = proposal_id`, one verdict per proposal |
| The digest is the Director's daily read | `reconcile_digest` v2 folds proposals, candidates, and pending proposals — version-bound and content-hashed |

---

## 3. The handoff contract

**An APPROVED proposal is a ratification fact, consumed by the existing
authority paths — never a new authority and never an auto-executor.**

### 3.1 The one new surface (read-only)

`Controller.approved_proposal_actions()` — a READ-ONLY advisory: every
undecided-proposal-excluded, APPROVED decision joined with its proposal
(the action, the classification ref, the candidate artifact, the decision
rationale), version-bound and content-hashed (the `reconcile_digest`
pattern). This is the ONLY new handoff surface. It feeds the existing
authority paths the question "what did the human ratify"; each path still
validates its own inputs and executes nothing through the advisory.

F2 discipline applied to the surface: it RECOMPUTES the ratification — the
decision event must exist AND correlate to a real proposal AND the action
must belong to the proposal's classification class's `permitted_actions`
set (recomputed via the dereference contract, D3). A tampered decision
payload alone cannot present a ratification; the proposal and the class are
re-verified on every read.

### 3.2 The action → authority map (the handoff table)

| PermittedAction | Existing authority path | Wiring state at HEAD | Handoff design |
|---|---|---|---|
| `REJECT_BRANCH` | ABANDON / EVIDENCE_TRANSITION | declared, NOT_WIRED | the approved proposal is a `ratification_ref` evidence input to the transition validator when it is wired; the validator still validates the branch and the transition itself |
| `REVIEW_DOWNSTREAM_IMPACT` | the Q-04 re-review advisory (IDR-040) IS the consumption; acting requires retraction/supersede authority | ratified read | no execution path exists or is proposed — the approval simply confirms the re-review obligation; the retraction/supersede authority stays where it lives |
| `PROPOSE_MECHANISM_SUBSTITUTION` | `PROPOSE_RESEARCH_PROGRAM` gateway path | WIRED | the approved proposal feeds the program-proposal builder as a ratified rationale ref; the existing validator unchanged |
| `PROPOSE_SCOPE_NARROWING` | S16 human amendment path | declared | the approval routes to the same operator channel that ingested the verdict: a new S16 amendment record with the approval id as its ratification ref |
| `PARK_FOR_RESOURCE_REVIEW` | resource review (advisory status) | declared | the approval surfaces the parked item in the resource-review read; parking itself stays a Director decision |
| `ROUTE_TO_SCOPE_REVIEW` | S16 scope authority (the FRAMING_ERROR path — the ONLY class that requires human confirmation) | declared | the approval is the scope-review intake: the operator-verdict channel records the scope decision with the approval as ratification ref |
| `ESCALATE_TO_DIRECTOR` | Director attention | declared | the digest surfaces the escalation; attention is a read, not an action |

### 3.3 Fail-closed rules

1. **An APPROVED proposal never auto-executes.** There is no
   "approved → act" ladder; every action still requires its existing path.
2. **A REJECTED proposal is terminal.** The one-verdict rule means no
   second decision can flip it; the handoff surfaces only APPROVED.
3. **The handoff recomputes, never trusts.** The surface re-verifies the
   decision ↔ proposal ↔ class ↔ action binding on every read (F2). A
   forged or orphaned decision event cannot present a ratification.
4. **The existing paths keep their own validation.** The ratification ref
   is an input, not a bypass: the future EVIDENCE_TRANSITION validator,
   the PROPOSE_RESEARCH_PROGRAM validator, and the S16 amendment record
   each still validate their own domain inputs. A ratification ref to a
   REJECTED proposal, a non-existent proposal, or an action outside the
   class's permitted set is refused.

---
## 4. Authority boundary

- **CAN** surface the ratification: `approved_proposal_actions()` is a
  read-only, version-bound, content-hashed advisory (the `reconcile_digest`
  pattern) — it tells the existing paths what the human ratified.
- **CAN** carry a `ratification_ref` (the proposal id) into an existing
  path's input where the path already validates it: the future
  EVIDENCE_TRANSITION validator, the PROPOSE_RESEARCH_PROGRAM builder, and
  the S16 amendment record.
- **CANNOT** execute anything. No approved-proposal auto-execution ladder
  is architecture — the same reason the auto-retraction ladder was rejected
  in IDR-040 §4: a ratified fact is not a trigger.
- **CANNOT** bypass existing validation: the ratification ref is an input,
  never a skip-switch.
- **CANNOT** create a second decision: the one-proposal-one-verdict rule is
  the lifecycle's terminality guarantee (a REJECTED proposal can never be
  flipped).

## 5. Deferred (explicitly NOT in this design)

- Wiring the `ABANDON` / `EVIDENCE_TRANSITION` gateway validators. The
  design specifies their input contract (the `ratification_ref`); the
  validators themselves are a future phase's implementation, and they will
  NOT be admitted until they validate their own domain inputs.
- The S16 amendment record (the scope-review intake for
  `PROPOSE_SCOPE_NARROWING` / `ROUTE_TO_SCOPE_REVIEW`). Its ratification-ref
  contract is specified here; the record itself is future work.
- Any new intent kind. The handoff needs none: the existing paths ingest
  the ratification ref as an input field of their OWN intents.

## 6. Acceptance criteria for the future implementation phase

AC-1 — `approved_proposal_actions()` returns exactly the APPROVED,
undecided-excluded proposals whose decision ↔ proposal ↔ class ↔ action
binding re-verifies; a tampered decision payload, an orphaned decision, or
an action outside the class's permitted set never appears (fail-closed with
an observable note).
AC-2 — a REJECTED proposal never appears in the advisory, and a second
decision on any proposal is refused (one-verdict terminality holds).
AC-3 — the advisory is deterministic, version-bound, content-hashed, and
never writes (fixture-pinned no-write; the AC-7 authority scan pattern).
AC-4 — a future EVIDENCE_TRANSITION admission carrying a `ratification_ref`
is refused unless the ref dereferences to an APPROVED proposal whose action
matches the class's permitted set AND the transition itself validates; a
ref to a REJECTED/unknown proposal is refused.
AC-5 — the PROPOSE_RESEARCH_PROGRAM builder accepts the ratification ref as
rationale evidence only; the validator's existing checks are unchanged and
still refuse a program proposal whose evidence does not dereference.

## 7. Hostile self-review of THIS design

- **Could an approved proposal double-execute?** No — the advisory is
  read-only; every execution still goes through an existing path, and the
  ratification ref is an input, not a trigger. No handoff code can act.
- **Could a forged `ClassificationActionDecision` (tampered APPROVED) reach
  an authority path?** The advisory recomputes the binding (decision event
  exists + correlates to a real proposal + action ∈ class's permitted set)
  before presenting anything; the future validators check the ref
  themselves (AC-4). The residual boundary is the honest one: an attacker
  with direct DB-write access can rewrite the events table — the same
  documented boundary as the one-verdict rule (IDR-040 audit). The handoff
  does not widen it.
- **Could the class metadata tamper re-order the handoff?** The advisory
  recomputes the permitted set from the classification's class on every
  read (F2) — a tampered class changes what the advisory presents, and the
  digest flags corrupt rows (the classification_proposals digest already
  drops malformed items, so an inconsistent class is visible, not silent).
- **Is `approved_proposal_actions` redundant with the digest?** No — the
  digest answers "what needs action / what is pending"; the handoff answers
  "what did the human ratify". Different questions, same advisory posture.
- **Why not auto-route APPROVED proposals to their paths?** Because routing
  IS execution-adjacent: an automatic EVIDENCE_TRANSITION on approval would
  be exactly the auto-retraction ladder the framework rejected. The human
  or the Director initiates the existing path; the ratification ref makes
  the approval legible to it.

## 8. Verdict

**DESIGN READY FOR IMPLEMENTATION — subject to the operator's ratification
gate.** The handoff is architecture input for a future phase: one read-only
advisory surface, zero new authority, zero new intents, and a precise
ratification-ref input contract for the already-declared authority paths.
No implementation in this task.
