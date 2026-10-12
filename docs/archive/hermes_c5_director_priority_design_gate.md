# HERMES C5 — DIRECTOR PRIORITY INPUT: DESIGN GATE

**Status:** DESIGN (2026-08-19) — no implementation, no intent added, no
code, no IDR. This is the design gate the five-fundamentals blueprint
requires for C5: §19 Q4 — "closed strength enum values; the intent kind
name; whether it requires human ratification per-instance or per-policy-
version; revocation semantics." §21 C5 pins the shape: "Gateway-admitted,
bounded, version-bound, eligibility-neutral. Fills the Q-02 §11 reserved
slot under the five conditions of §17." **Nothing here is ratified.**
Implementation is gated on (a) ratification of the five-fundamentals
blueprint itself and (b) operator approval of this gate's decisions.

> **Ratification update (2026-08-20, additive):** this contract was RATIFIED
> with **OPTION B (bounded Director priority)** by operator ratification —
> `hermes_architecture_ratification.md` §6.1, including the explicit
> attack-C risk acceptance (architecture frozen; implementation separately
> chartered, Step 7, P4-gated). The status paragraph above is the historical
> pre-ratification record; §2.2's Option A and §2.6's Option B remain
> visible as the decision history.

**Cross-check remediation (2026-08-19):** the four-gate cross-check found
that §2.5's TTL originally cited "the ranking history" as its derivation
source — but the ranking is transient and never persisted
(`evaluation.py:494–511`), so no such history exists. **Fixed:** the TTL
counter is now derived from the append-only dispatch-round record (the
`TaskStatusChanged` READY→RUNNING claim events, which ARE persisted) —
"eligible rounds since admission" counts dispatch rounds observable in
the event log, never a transient ranking. **Second remediation
(independent review 2026-08-20):** the review found "eligible rounds"
was not well-defined from claim events — zero-claim rounds emit nothing,
so the counter would silently stall. §2.5 now pins DISPATCH-round
semantics explicitly (priority is inert in zero-claim rounds, so no
decay is lost there) and flags the calendar-round alternative in §7.6.

**Why this gate is the most adversarial of the set:** C5 re-admits the
exact thing Q-02 rejected. Q-02 §14: "**Stored priority field on tasks** —
a new mutation surface and budget-adjacent authority; the ordering is
computed at eligibility time." Q-02 §18.2 verified live that no priority
mechanism exists and deliberately deferred one. Yet Q-02 §11.5 ALSO
asserted the precedence "ratified Director priority > epistemic policy >
created_at/task_id tie-break" *at design level, mechanism deferred*. C5 is
the deferred mechanism. The resolution (§2.1): **C5's priority is NOT a
stored field on tasks — it is an admitted proposal record consumed at
ordering time.** That distinction is the entire gate.

**Inputs:** `hermes_five_fundamentals_blueprint.md` §17 (the five
conditions, lines 1523–1539), §18 attack C (lines 1566–1573), §19 Q4, §21
C5, §22 condition 2; `hermes_q02_epistemic_roi_design.md` §11.5 (the
deferred precedence), §14 (the stored-priority rejection), §18.2 (the
deferred-mechanism verification), §13 row "Director … set human priorities
(once a ratified priority mechanism exists)"; `src/hermes/core/intents.py`
(`IntentKind` :24–99 — `llm_proposable` :76–82, `director_only` :84–93,
`internal_only` :95–99; the `PROPOSE_CLASSIFICATION_ACTION` proposal-shaped
precedent :55–60); `src/hermes/research/gateway.py`
(`_handle_propose_classification_action` :322+ — admission-is-the-audit
pattern, `EFFECTIVE` vs `PENDING_HUMAN_APPROVAL` split :423–426);
`src/hermes/research/evaluation.py` (`TASK_ORDERING_POLICY` :439–444,
`_task_ordering_key` :573–581 — the lexicographic key C5 would extend);
`hermes_c4_exploration_floor_design_gate.md` §2.1/§4.2 (the floor C5 must
compose with).

---

## 1. Repository reconciliation (verified live, 2026-08-19)

| Blueprint/Q-02 claim | Live repository fact | Verdict |
|---|---|---|
| "Fills the Q-02 §11 reserved slot" | Q-02 §11.5 asserts the precedence "ratified Director priority > epistemic policy" and §18.2 verifies "no Director-priority field or mechanism exists in the controller" — the slot is real and empty | CONFIRMED — the reserved slot exists, unfilled |
| "Q-02 rejected a priority field" | Q-02 §14 rejects "**Stored priority field on tasks** — a new mutation surface and budget-adjacent authority" | CONFIRMED — the rejection is specifically about a STORED FIELD ON TASKS; see §2.1 for why C5 is not that |
| "Proposal-shaped: an intent through the gateway (the `PROPOSE_CLASSIFICATION_ACTION` precedent — admission is the audit)" | `PROPOSE_CLASSIFICATION_ACTION` is `director_only` (`intents.py:92–93`), admitted proposal-only with `EFFECTIVE` / `PENDING_HUMAN_APPROVAL` split (`gateway.py:423–426`), "the admission is the audit record" (`intents.py:55–60`) | CONFIRMED FEASIBLE — the proposal-shaped admission pattern exists and is the exact precedent condition 1 names |
| "Bounded vocabulary: trajectory ref + closed strength enum; no task names, no budgets, no deadlines" | The ordering surface keys on task provenance (program ref) and lexicographic dimension levels (`evaluation.py:439–444`, :573–581); no priority vocabulary exists | CONFIRMED FEASIBLE — a trajectory-keyed enum rides the existing ordering input shape |
| "Version-bound: … recorded in the dispatch log via `ordering_policy_version`" | The ranking carries the version triple (`evaluator_version`/`policy_version`/`schema_version`, `evaluation.py:433–447`) and a content-derived `ranking_id` | CONFIRMED FEASIBLE — priority consumption bumps `policy_version`; every dispatch already records it |
| "Eligibility-neutral: never makes an ineligible task eligible" | Ordering applies only within the already-eligible set (`controller.py:1914–1932`; Q-02 §6 "never admits") | CONFIRMED — eligibility is decided before ordering; C5 cannot touch it |
| "Revocable by supersession … the human may override via the operator channel" | The operator channel exists (`RESOLVE_CLASSIFICATION_PROPOSAL` / `RECORD_SCOPE_REVIEW_DECISION` internal-only intents, `intents.py:61–70`; operator credentials IDR-041 B4) | CONFIRMED FEASIBLE — a revocation intake can reuse the operator-ingestion pattern |

**Verified gap:** the Director has no channel to express "this trajectory
matters more right now" except by proposing new programs or classification
actions. Q-02's design acknowledged this need (§13: "set human priorities
(once a ratified priority mechanism exists)") and deferred the mechanism.
C5 is that mechanism — if and only if it passes the five conditions.

---

## 2. DECISION — the four §19-Q4 questions, resolved

### 2.1 The core distinction: an admitted proposal, NOT a stored field

**Resolved: C5's priority is a proposal-shaped admission through the
gateway — an append-only `DirectorPriorityProposed` record, consumed at
ordering time as a versioned clause of the ordering policy. It is NOT a
column on `tasks`, NOT a mutable priority store, NOT a field on any
research-state row.**

Why this does not contradict Q-02 §14's rejection:

- Q-02 rejected a **stored priority field on tasks** because it would be
  "a new mutation surface and budget-adjacent authority" — a per-task
  mutable fact that the scheduler reads and that agents could rewrite.
- C5's priority is **none of those things**: it is an immutable admission
  record (append-only, like every other proposal), keyed to a TRAJECTORY
  (never a task), carrying a closed strength enum (never a budget, a
  deadline, or a task name), and consumed by the deterministic ordering
  policy under the policy version that admits it. The ordering is still
  "computed at eligibility time" — Q-02 §14's own words — now from one
  more versioned input.
- The pattern is exactly `PROPOSE_CLASSIFICATION_ACTION`: "Proposal-only —
  the action is never executed here … The admission is the audit record"
  (`intents.py:55–60`). C5's admission is likewise never an execution
  authority; it is an input the ordering policy may consult.

**The chain stays intact (blueprint §17 closing line):** Director →
proposal → gateway validation → Q-02 ordering policy → controller dispatch.
*The signal proposes; the deterministic machinery decides.*

### 2.2 Question 1 — the closed strength enum

**Resolved: a THREE-value closed enum, consumed as a lexicographic key
component — never a number, never a weight.**

```
PriorityStrength (closed, versioned):
  ELEVATE    — this trajectory's eligible tasks order ahead of
               epistemically-equal tasks of non-prioritized trajectories
  SUSTAIN    — this trajectory's eligible tasks are protected from
               deprioritization below their epistemic rank (a floor-like
               hold within the ordering; composes with C4, §5)
  DEPRIORITIZE — this trajectory's eligible tasks order behind
               epistemically-equal tasks of non-prioritized trajectories
```

- **Three values, not a scale.** More levels would invite strength creep
  (attack C's exact mechanism: "priority strength creep; 'advisory'
  becomes 'obeyed'"). Three is enough to express "more / hold / less";
  any finer gradation is a scalar in disguise and is rejected by
  construction (AC-9).
- **Position in the lexicographic key — the load-bearing decision:**
  priority enters the ordering key BELOW the six epistemic dimensions and
  ABOVE cost/created_at/task_ref. That is: **priority breaks ties among
  epistemically-equal tasks; it never overrides an epistemic difference.**
  A HIGH-gap task of a non-prioritized trajectory still orders above a
  LOW-gap task of an ELEVATE'd one.
  - **This deliberately refines Q-02 §11.5's literal reading** ("ratified
    Director priority > epistemic policy"). That reading, implemented
    literally, IS attack C: a priority that outranks the epistemic
    dimensions is a hidden scheduler. Q-02 §11.5 was asserted "at design
    level, mechanism deferred" — the deferral exists precisely so the
    mechanism's design gate could settle the position. This gate settles
    it BELOW the dimensions, and flags the literal reading to the
    architecture team (§7.1) as the one decision that may be overruled —
    but only with an explicit attack-C risk acceptance on record.
- **No task names, no budgets, no deadlines** (condition 2, verbatim):
  the payload carries trajectory ref + strength + rationale. Any other key
  is rejected at admission (`MALFORMED_PAYLOAD`).

### 2.3 Question 2 — the intent kind name

**Resolved: `PROPOSE_DIRECTOR_PRIORITY` — a new `director_only` intent
kind, proposal-shaped, admission-is-the-audit.**

- Added to `IntentKind` and to `director_only()` (`intents.py:84–93`) —
  only the Director may propose it, enforced by the gateway's per-kind
  `proposed_by` validation (the IDR-018 pattern).
- NOT in `llm_proposable()` beyond the Director surface, NOT in
  `internal_only()` — it is a Director proposal, not an operator ingestion.
- The gateway validates: trajectory ref dereferences in-project (a
  `research_program:` ref — the same provenance discipline the ordering
  already reads); strength in the closed enum; rationale non-empty and
  capped; no forbidden keys (task names, budgets, deadlines). Rejections
  are observable data, never crashes.
- The admission appends a `DirectorPriorityProposed` event (append-only,
  content-derived id, correlation to the proposal) — the audit IS the
  record, exactly as `ClassificationActionProposed`.

### 2.4 Question 3 — ratification: per-policy-version, NOT per-instance

**Resolved: priority proposals are EFFECTIVE on admission (no per-instance
human gate). The human control is per-policy-version: the ordering policy
version that admits priority consumption is itself the ratification
surface, and the operator may revoke any priority at any time (§2.5).**

This is the gate's riskiest decision, stated honestly:

- **Why not per-instance ratification:** a priority that requires a human
  gate per instance is not a scheduling signal — it is a queue of pending
  approvals the human must process to keep dispatch moving. That converts
  the Director's bounded nudge into human micromanagement and defeats C5's
  purpose (giving the Director a channel to express trajectory urgency
  between human decisions). The `PROPOSE_CLASSIFICATION_ACTION` precedent
  splits EFFECTIVE (advisory-shaped) from PENDING_HUMAN_APPROVAL
  (authority-shaped) precisely so advisory signals need no gate
  (`gateway.py:423–426`). C5's priority is advisory-shaped: it reorders
  within the eligible set and can do nothing else.
- **Why this is still safe (the mitigations that make per-version
  ratification acceptable):** (1) bounded vocabulary — three enum values,
  trajectory-keyed, no task/budget/deadline; (2) eligibility-neutral —
  structurally cannot admit, gate, or budget; (3) version-bound — priority
  consumption exists only under the policy version that admits it, so the
  architecture team's ratification of THAT policy version is the
  ratification of the mechanism; (4) revocable — operator revocation at
  any time (§2.5); (5) TTL — priorities expire automatically (§2.5);
  (6) below-the-dimensions position — priority never overrides an
  epistemic difference (§2.2). If the team judges these insufficient, the
  fallback is per-instance PENDING_HUMAN_APPROVAL — designed, not
  implemented (§7.2).
- **The operator ratifies the mechanism by ratifying the policy version.**
  Until a `policy_version` that consumes `DirectorPriorityProposed` records
  is ratified and deployed, admitted priorities are inert audit records —
  the mechanism is off by default.

### 2.5 Question 4 — revocation semantics: supersession + operator revocation + TTL

**Resolved: three revocation paths, all deterministic, none mutating
history.**

1. **Supersession by the Director:** a new `PROPOSE_DIRECTOR_PRIORITY`
   for the SAME trajectory ref supersedes the prior one (condition 5,
   verbatim). The prior record stays in the append-only history (never
   deleted); the ordering policy consumes only the LATEST unexpired record
   per trajectory. Supersession is derived from the event order, never a
   stored "active" flag (F2 discipline).
2. **Operator revocation:** a new internal-only intent
   `REVOKE_DIRECTOR_PRIORITY` (operator-ingestion pattern,
   `intents.py:61–70` precedent) records the human's revocation of a
   trajectory's priority. The ordering policy treats a revoked priority as
   expired from the revocation round forward. The human override is
   condition 5's second clause, verbatim.
3. **TTL (time-to-live in dispatch rounds):** every priority carries a
   versioned `priority_ttl_rounds`; the ordering policy counts DISPATCH
   rounds since admission — a dispatch round is a round observable in the
   event log as at least one `TaskStatusChanged` READY→RUNNING claim
   event (emitted at `controller.py:3029–3030`, persisted at
   `repositories.py:603–611`), never a mutable counter and never the
   transient ranking (which is never persisted, `evaluation.py:494–511`).
   **Semantics pinned (independent review 2026-08-20):** the event log
   carries NO per-tick round marker (grep `events.py`: none), so rounds
   with zero claims (empty eligible set, cap binding, all-blocked) do NOT
   advance the TTL counter. This is deliberate, not a stall bug: priority
   affects ordering ONLY at claim time, so a round with no claims is a
   round where the priority is inert — there is no ordering for it to
   distort. TTL's purpose is to stop a stale priority silently biasing
   future dispatch; measuring it in dispatch rounds is exactly that.
   Residual (flagged §7.6): during long idle/cap-bound periods a priority
   lives longer in calendar time than `priority_ttl_rounds` suggests —
   harmless while inert, but the team must confirm dispatch-round
   semantics rather than calendar-round semantics is the intended decay.
   A priority that is never re-proposed decays — "strength creep" cannot
   accumulate because nothing persists indefinitely. Default TTL is a
   team decision (§7.3).

### 2.6 Pre-P4 readiness brief — recommended resolution of the §2.2 conflict (2026-08-20)

The pre-P4 architecture-readiness brief (2026-08-20) resolves the §2.2
normative conflict by recommending **OPTION B** — the literal Q-02 §11.5
precedence — **bounded to the already-eligible set**:

```
Director priority > Q-02 epistemic ordering > cost > created_at > task_ref
```

This is recorded as the architecture team's RECOMMENDED choice, subject to
ratification; it supersedes §2.2's below-dimensions recommendation as the
pending decision (both remain visible for the ratification record). The
bounded override MUST NOT:

- change eligibility (priority never admits an ineligible task);
- bypass gates (gated tasks stay parked regardless of priority);
- bypass dependencies (dependency order is untouched);
- bypass budgets (the call cap and budget classes are untouched);
- change the Evidence Ladder (no ladder transition from priority);
- create tasks (priority is ordering-side only);
- modify program state (no program mutation from priority).

**Temporal safeguard 1 — policy activation boundary.** A priority admitted
while priority consumption is DISABLED (a policy version without the
priority clause) must NOT silently become active when a later policy
version enables the mechanism. Rule: **only priorities admitted under a
consuming policy version are consumable.** Priorities admitted under a
non-consuming version remain inert audit records; if the Director wants
them active, it must re-propose them under a consuming version. The
alternative (auto-activation on policy upgrade) is rejected unless the
architecture team explicitly ratifies it: silent activation would let a
stale priority queue seize ordering authority the moment the mechanism
turns on — attack C by another path.

**Temporal safeguard 2 — TTL activation semantics.** TTL begins when the
priority becomes CONSUMABLE (first admission under a consuming policy
version), NOT at proposal admission. A priority admitted under a
non-consuming version accrues no TTL; its clock starts only if/when it is
re-proposed under a consuming version. This pairs with safeguard 1: inert
priorities never decay, because they were never live. TTL counting itself
remains the dispatch-round semantics of §2.5 (zero-claim rounds do not
advance it).

**Acceptance criteria added for Option B:**

- **AC-12 — activation boundary.** A priority admitted under a
  non-consuming policy version is NOT consumed after a policy upgrade
  enables priority; only priorities admitted under the consuming version
  are consumed. Re-proposal under the consuming version activates it.
- **AC-13 — TTL activation.** A priority's TTL counter starts at first
  admission under a consuming policy version, not at initial (inert)
  admission; an inert priority never expires while inert.
- **AC-14 — bounded override.** Under Option B, priority reorders within
  the already-eligible set only; eligibility, gates, dependencies,
  budgets, the Evidence Ladder, task creation, and program state are all
  unchanged (structural fixtures pin each).

---

## 3. Exact authority owner

- **Who proposes priority?** The **Director** (the semantic proposer,
  IDR-018) — and ONLY the Director (`director_only()`).
- **Who decides whether priority is consumed?** The **versioned ordering
  policy** — the same authority that owns `TASK_ORDERING_POLICY`. Priority
  is an input to the policy, never a bypass of it. A policy version that
  consumes priority is a `policy_version` change subject to the same
  review discipline as any other (attack D's vigilance note).
- **Who revokes?** The Director (supersession) or the operator
  (`REVOKE_DIRECTOR_PRIORITY`). No agent, no task, no other surface.
- **Does priority admit, gate, budget, or decide?** **No.** It reorders
  the already-eligible set (condition 4). Eligibility, gates,
  dependencies, the call cap, and the budget are untouched.
- **Does priority create a second scheduler?** **No.** Dispatch remains
  the controller's internal function consuming the policy order
  (`controller.py:1914–1932`). Priority adds one input to the ordering;
  it adds no dispatch path, no admission path, no authority (blueprint
  §22 condition 2; failure mode R stays solved).

---

## 4. The contract

### 4.1 The admission payload (gateway surface)

```json
{
  "trajectory_ref": "research_program:rp_...",
  "strength": "ELEVATE",
  "rationale": "why this trajectory matters now (capped, non-empty)"
}
```

- `trajectory_ref` MUST be a `research_program:` ref that dereferences
  in-project (the same provenance discipline the ordering reads). A
  task-level ref, a hypothesis-level ref, or any other shape is rejected
  — condition 2's "no task names" is enforced at admission, not by
  convention.
- `strength` MUST be in the closed enum; unknown values rejected.
- `rationale` non-empty, capped (same cap discipline as other rationale
  fields).
- Any additional key (budget, deadline, task name, numeric weight) →
  `MALFORMED_PAYLOAD` rejection. The vocabulary is closed by construction.

### 4.2 The ordering consumption (policy surface)

The versioned ordering policy gains a priority clause, applied AFTER the
six epistemic dimensions and BEFORE cost/created_at/task_ref:

```
ordering key = (epistemic dimensions,   # unchanged — _task_ordering_key
                priority component,      # NEW: ELEVATE > none > DEPRIORITIZE;
                                         #      SUSTAIN = hold at epistemic rank
                cost, created_at, task_ref)   # unchanged
```

- The priority component is derived per task from its trajectory's latest
  unexpired, unrevoked `DirectorPriorityProposed` record. No record ⇒ the
  "none" level. The derivation is a pure function of the append-only
  event history + the versioned TTL/revocation facts (F2 — never a stored
  "current priority" table).
- **SUSTAIN semantics:** a SUSTAIN'd trajectory's tasks keep their
  epistemic rank and are exempt from any BELOW-dimension deprioritization
  (e.g. they are not pushed down by a competing ELEVATE). SUSTAIN is a
  hold, not a boost.
- **Determinism:** same eligible set + same version triple + same event
  history ⇒ identical `ranking_id` and identical priority consumption.

### 4.3 Observability (the audit surface)

- Every priority admission is a `DirectorPriorityProposed` event
  (append-only, content-derived id). Every revocation is a
  `DirectorPriorityRevoked` event. The ordering's ranking diagnostics
  surface which tasks were priority-affected each round (a new
  `TaskDiagnosticKind.PRIORITY_APPLIED` advisory), so the dispatch log
  shows not just the order but WHY (condition 3: "recorded in the dispatch
  log via `ordering_policy_version`" — extended to name the priority).
- The C6 convergence diagnostic (future) may read the priority history as
  an advisory signal ("the Director has been holding trajectory X for N
  rounds"); advisory only, never a gate input.

### 4.4 What C5 does NOT do (explicit exclusions)

- **NOT a stored priority field on tasks.** No column on `tasks`, no
  mutable priority store, no per-task priority fact (Q-02 §14's rejection
  stands; §2.1 is the distinction).
- **NOT an override of the epistemic dimensions.** Priority sits BELOW the
  dimensions in the lexicographic key (§2.2). It breaks ties, never
  epistemic differences.
- **NOT an eligibility mechanism.** Priority never admits, gates, budgets,
  or names tasks (conditions 2 + 4).
- **NOT a scalar.** Three enum values, lexicographic consumption — no
  number, no weight, no composite (attack D stays solved; AC-9).
- **NOT a second scheduler.** Dispatch path unchanged; priority is one
  more versioned input to the one ordering policy (attack C's defense is
  the five conditions, all enforced here).
- **NOT permanent.** TTL + supersession + operator revocation guarantee no
  priority persists indefinitely (§2.5).

---

## 5. Composition with C4 (the exploration floor)

C4 and C5 both modify the ordering; they must compose without conflict.
The rule (mirrored verbatim in the C4 gate's §4.5 — the two gates are
mutually aware; C4 §4.5 was added by the 2026-08-20 independent
adversarial review, which found this composition lived here only):

1. **Priority reorders FIRST** (the §4.2 clause, below the dimensions).
2. **The floor applies SECOND** to the priority-reordered set: C4's
   "highest-policy-ranked non-leading task" (C4 §4.2 step 5) is selected
   from the priority-aware order. So an ELEVATE'd non-leading trajectory
   is more likely to receive the floor slot — priority influences WHICH
   non-leader the floor promotes, never WHETHER the floor fires.
3. **Priority never exempts from the floor's F-C rule.** A SUSTAIN'd or
   ELEVATE'd stagnant trajectory still loses its floor entitlement under
   C4 §2.3. Priority affects ordering; the floor's decay/kill-switch
   governs floor entitlement. The two are orthogonal by construction.
4. **No priority can suppress the floor.** The floor's reservation is a
   structural clause of the same policy; a DEPRIORITIZE on the floor's
   beneficiary reorders the non-leading candidates but does not cancel
   the reserved slot.

---

## 6. Acceptance criteria (the implementation must prove all of these)

- **AC-1 — admission contract.** A valid payload (in-project trajectory
  ref, closed strength, non-empty capped rationale) is admitted with a
  `DirectorPriorityProposed` event; a task-level ref, unknown strength,
  empty rationale, or any forbidden key (budget/deadline/task name/number)
  is rejected with an observable code; only the Director may propose
  (`director_only` enforced).
- **AC-2 — eligibility-neutral.** A priority on a trajectory with NO
  eligible tasks changes nothing; a priority never causes an ineligible
  task to be dispatched (structural fixture: eligibility set unchanged).
- **AC-3 — below-the-dimensions position.** A HIGH-epistemic task of a
  non-prioritized trajectory orders ABOVE a LOW-epistemic task of an
  ELEVATE'd trajectory; priority only permutes tasks that are
  epistemically equal (the §2.2 load-bearing clause).
- **AC-4 — closed enum, no scalar.** Exactly three strength values; the
  ordering key contains no numeric priority term; the no-scalar structural
  tests (`test_evaluation.py:338+` pattern) pass over the priority-aware
  ranking.
- **AC-5 — supersession.** A second priority for the same trajectory
  supersedes the first; the ordering consumes only the latest unexpired
  record; the prior record remains in the append-only history.
- **AC-6 — operator revocation.** `REVOKE_DIRECTOR_PRIORITY` (operator
  credentials required) expires the trajectory's priority from the
  revocation round; an unauthenticated revocation is refused fail-closed.
- **AC-7 — TTL.** A priority expires after `priority_ttl_rounds` DISPATCH
  rounds (each = a round with ≥ 1 persisted READY→RUNNING claim event;
  derived, not stored); zero-claim rounds do not advance the counter
  (priority is inert there — no ordering to distort); an expired priority
  affects no ordering; re-proposal resets the TTL.
- **AC-8 — version-bound.** Under a policy version that does NOT consume
  priority, admitted priorities are inert audit records (ordering
  identical to the no-priority baseline); consumption exists only under
  the ratifying `policy_version`, and every priority-affected dispatch
  records it.
- **AC-9 — determinism.** Identical eligible set + version triple + event
  history ⇒ identical `ranking_id` and identical priority consumption,
  independent of replay order.
- **AC-10 — C4 composition.** With both C4 and C5 active: the floor still
  fires under monopoly (C4 AC-2), priority influences which non-leader
  receives the floor slot, and a stagnant prioritized trajectory still
  loses its floor entitlement under F-C (no priority exempts from decay).
- **AC-11 — no authority leak.** Structural fixtures: no new table, no
  migration, no change to eligibility/gate/dependency/budget predicates,
  `_task_ordering_key`'s dimension prefix unchanged, dispatch path
  unchanged.

---

## 7. Open questions for the architecture team (decisions this gate
defers, none blocking the contract)

1. **The §2.2 position decision (the one that may be overruled):** this
   gate places priority BELOW the epistemic dimensions, deliberately
   refining Q-02 §11.5's literal "priority > epistemic policy" reading.
   The literal reading is attack C if implemented unbounded. If the team
   wants the literal reading, it must record an explicit attack-C risk
   acceptance and add a stronger bound (e.g. priority may override only
   NONE/LOW epistemic differences). This gate recommends the below-
   dimensions position as the only reading consistent with "the signal
   proposes; the deterministic machinery decides."
   **UPDATE (2026-08-20, pre-P4 readiness brief §10):** the brief
   recommends OPTION B (literal precedence, bounded to the eligible set)
   with the seven MUST-NOT bounds + two temporal safeguards of §2.6.
   The decision is now: ratify Option B-with-bounds (§2.6) OR keep
   Option A (below-dimensions). Both are fully designed; neither is
   silent. Ratification must pick one explicitly.
2. **Per-instance ratification fallback:** §2.4 chooses per-policy-version
   ratification (EFFECTIVE on admission). If the team judges the six
   mitigations insufficient, the fallback is per-instance
   PENDING_HUMAN_APPROVAL (the `PROPOSE_CLASSIFICATION_ACTION` gated
   pattern) — fully designable, at the cost of making priority a queue of
   pending approvals. Confirm the EFFECTIVE choice.
3. **TTL default:** `priority_ttl_rounds` is open. Too short and priority
   is useless between human decisions; too long and it approaches a
   standing instruction (creep risk). Propose a default in the tens of
   eligible rounds, versioned.
6. **TTL round semantics (independent review 2026-08-20):** §2.5 pins
   dispatch-round counting (zero-claim rounds don't advance TTL). If the
   team wants calendar-round decay instead, that requires a per-round
   marker event (a new event type — currently none exists in the catalog).
   Confirm dispatch-round semantics is acceptable before implementation.
4. **SUSTAIN necessity:** the three-value enum includes SUSTAIN (a hold).
   If the team judges two values (ELEVATE/DEPRIORITIZE) sufficient, SUSTAIN
   can be dropped without touching the rest of the contract — it is an
   enum member, not a mechanism. Confirm whether the hold semantics earn
   their place.
5. **Interaction with the active-trajectory bound (§19 Q5):** if a future
   admission bound caps concurrently-ACTIVE trajectories, a priority on a
   trajectory at the bound must not imply admission. This gate assumes
   priority is ordering-side only; confirm when Q5 is designed.

---

## 8. Authority boundary (ratifiable text, pending approval)

- **CAN** admit a Director-proposed, trajectory-keyed, closed-enum
  priority as an append-only audit record through the existing gateway —
  admission is the audit, never an execution.
- **CAN** consume admitted, unexpired, unrevoked priorities as a
  versioned clause of the ordering policy, BELOW the epistemic dimensions,
  under the ratifying `policy_version`.
- **CAN** record supersession (Director) and revocation (operator) as
  append-only events; the ordering derives current priority from the event
  history, never a stored flag.
- **CANNOT** store priority on tasks, name tasks, set budgets or
  deadlines, or introduce any numeric strength — the vocabulary is closed
  by construction.
- **CANNOT** override an epistemic difference, admit an ineligible task,
  or bypass any gate/dependency/budget — priority is eligibility-neutral
  ordering input.
- **CANNOT** persist indefinitely — TTL + supersession + operator
  revocation guarantee every priority is revocable and expires.
- **CANNOT** create a second scheduler or dispatch path — dispatch remains
  the controller's internal function consuming the one policy order.

---

*End of C5 design gate. Status: DESIGN — awaiting blueprint ratification
and operator approval before any implementation phase. No file in `src/`,
`tests/`, or `docs/idr/` is touched by this document.*
