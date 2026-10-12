# HERMES C4 — THE EXPLORATION FLOOR: DESIGN GATE

**Status:** DESIGN (2026-08-19) — no implementation, no policy change, no
code, no IDR. This is the design gate the five-fundamentals blueprint
explicitly requires: §19 Q3 — "Exploration floor (G3/C4): exact predicate
(one slot per tick to a non-leading trajectory?), interaction with the
per-tick call cap, decay semantics, and the degenerate-to-baseline
fallback. **Needs its own design gate in the Q-02 design-gate style.**"
§21 C4 adds the mandatory F-C decay-or-kill-switch rule. This document
resolves all four sub-questions into a decidable contract and pins the
acceptance criteria the implementation must meet. **Nothing here is
ratified.** Implementation is gated on (a) ratification of the five-
fundamentals blueprint itself and (b) operator approval of this gate's
decisions.

> **Ratification update (2026-08-20, additive):** this contract was RATIFIED
> as designed by operator ratification — `hermes_architecture_ratification.md`
> §5 (architecture frozen; implementation separately chartered, Step 2 —
> first implementation, controller-only). The status paragraph above is the
> historical pre-ratification record.

**Cross-check remediation (2026-08-19):** the four-gate cross-check found
that this gate's original §2.3/§4.3 cited a substrate that does NOT exist
— the ranking diagnostics are transient and never persisted
(`evaluation.py:494–511` "never persisted"; `_dispatch_pass` records only
`ordering_policy_version` in the in-memory `TickResult`,
`controller.py:2993–2997`; no ranking/diagnostic event type exists in the
catalog, `events.py:15–90`). The floor-grant history therefore has no
durable record. **Fixed:** the floor-grant history now rides a NEW
append-only event (`FloorGrantRecorded`, §4.3), the same pattern as
`RefutedApplied`. This adds one event type to the catalog — consistent
with the existing catalog's forward-compatibility additions — and is the
one deliberate, flagged exception to the "no new event" framing.

**Independent adversarial review remediation (2026-08-20):** the
independent review (deleg_a790ff80, verdict HOLDS WITH CAVEATS) found
the C4↔C5 composition rules lived in the C5 gate only — C4 was silent
on C5. **Fixed:** §4.5 now mirrors C5 §5 verbatim, and the Inputs cite
the C5 gate. Verdict recorded in `C:/Users/Ali Zoghi/gate_review/
c4_findings.md`.

**Inputs:** `hermes_five_fundamentals_blueprint.md` §18 attacks A/B/K/L
(the failure modes C4 defends), §15 "the one pressure point" (trajectory
label resolution, lines 1405–1411), §19 Q3, §21 C4 (F-C rule) + C6 (F-G
`FLOOR_EXHAUSTED`), §22 condition 1, §26.2 condition-4 consistency note
(trajectory labels from `task_obligations.py`), §27 (corrected re-grade:
A and the K/L residual are the attacks solved ONLY if C4 lands);
`src/hermes/research/evaluation.py` (`TASK_ORDERING_POLICY` :439–444,
`EligibleTask` :455–472, `EligibleTaskRanking` :494–511 — transient,
hashed, never persisted, never a gate input, `evaluate_eligible_tasks`
:514–556, `_task_ordering_key` :573–581, `TaskDiagnosticKind`
:450–452 — incl. the existing `DEGENERATE_TO_BASELINE` pattern, action-side
diagnostics `STARVED_CANDIDATE`/`STALE_INPUT`/`NO_IMPROVEMENT` :89–92);
`src/hermes/research/controller.py` (`DEFAULT_MAX_CALLS_PER_TICK = 8`
:248, cap enforcement :3018–3019, `_order_eligible` :1914–1932 — the
consumption point, `_load_obligation_context` :1934+ — read-only facts);
`src/hermes/research/task_obligations.py` (pure obligation-fact
derivation, header :1–25, `_obligation_level` :33–41);
`hermes_c5_director_priority_design_gate.md` (§5 composition — the
two gates state identical composition rules; §4.5 below mirrors it);
`hermes_q02_epistemic_roi_design.md` (Model B authority decision, §18.4
degenerate-to-baseline precedent, §18.5 ordering key) as the format and
authority precedent.

---

## 1. Repository reconciliation (verified live, 2026-08-19)

| Blueprint C4 claim | Live repository fact | Verdict |
|---|---|---|
| "A versioned constraint inside the Q-02 ordering policy" | The Q-02 task-ordering surface IS a versioned deterministic policy: `TASK_ORDERING_POLICY` string + `evaluator_version`/`policy_version`/`schema_version` triple, content-derived `ranking_id` (`evaluation.py:433–447`, :494–511). The controller consumes the order at discovery (`controller.py:1914–1932`) | CONFIRMED FEASIBLE — a floor is a versioned amendment to this policy, no new surface |
| "trajectory-level allocation is expressed as task-level ordering via the trajectory label (the task's program/hypothesis provenance ref)" | Every eligible task carries `basis_refs` and is derived from stored task state + `research_program:` provenance (`controller.py:1917–1930`); obligation facts derive per-program (`task_obligations.py:44+`) | CONFIRMED FEASIBLE — the trajectory label is already derivable; see §2.1 for the keying decision |
| "the trajectory labels the floor would key on are computed by `task_obligations.py` — a pure derivation module … Label computation is a deterministic read, not an authority" (blueprint §26.2) | `task_obligations.py` header: "pure: no SQL, no persistence imports, no write path, no LLM input"; imports the shared `DimensionLevel` vocabulary | CONFIRMED — the floor's inputs are the same pure facts Q-02 already reads |
| "interaction with the per-tick call cap" | `max_calls_per_tick` is a hard liveness cap (default 8, `controller.py:248`), enforced at dispatch (`controller.py:3018–3019`: `calls >= cap → idle`) | CONFIRMED — the cap is the binding capacity constraint the floor must respect |
| "the degenerate-to-baseline fallback" | The pattern already exists: `DEGENERATE_TO_BASELINE` diagnostic when no obligation facts resolve (`evaluation.py:452`, :543–549; Q-02 §18.4) | CONFIRMED — C4 reuses the established fallback shape |
| "Current defense: STARVED_CANDIDATE + STALE_INPUT diagnostics" (attacks K/L) | Both exist on the ACTION-evaluation side (`evaluation.py:89–92`, :238–257); the TASK-ordering side has only `EMPTY_ELIGIBLE_SET` and `DEGENERATE_TO_BASELINE` | CONFIRMED — the diagnostics make starvation VISIBLE but nothing BOUNDS it; the floor is the missing bound |
| "the floor must be a floor, not a quota" (attack B) | No floor/quota/reservation mechanism exists anywhere in `src/` | CONFIRMED ABSENT — C4 is new control policy |

**Verified gap:** the Q-02 ordering is pure epistemic merit. A leading
trajectory whose tasks always rank highest monopolizes every dispatch
slot within the call cap (attack A), and the satisfaction links its
dispatch produces raise its obligation-facts, which raise its future
rankings (attacks K/L's self-reinforcing loop). The diagnostics expose
this; nothing bounds it. C4 is the bound.

---

## 2. DECISION — the four §19-Q3 sub-questions, resolved

### 2.1 The predicate: one reserved slot, keyed to trajectory labels

**Resolved: the floor is a RESERVATION, not a quota. At each ordering
round, IF pure policy ordering would allocate every available dispatch
slot to a single trajectory AND at least one eligible task of a
non-leading trajectory exists, THEN the highest-policy-ranked non-leading
task is promoted into exactly ONE reserved slot (the last of the round's
available slots). Otherwise the floor is inert and pure policy ordering
stands.**

- **Trajectory label:** the task's program provenance ref
  (`research_program:<program_id>` — the same ref the obligation
  derivation already keys on, `task_obligations.py`). Whether the label
  should be refined to (program, hypothesis) granularity is deferred to
  the architecture team (§7.1) — the contract is parametric in the label
  function, and the program-level label is the day-one default because it
  is exactly what the provenance ref carries today.
- **"Leading" is derived, never stored:** the leading trajectory is the
  one that pure policy ordering would give all slots to, computed from
  this round's eligible set. No standing "leader" flag, no stored posture
  (blueprint §21: posture labels are derived at ordering time, never
  stored — Q-02 §14's stored-priority rejection extends).
- **One slot, not a share:** the floor grants at most ONE slot per round
  (versioned parameter `floor_slots`, default 1). It never grants a
  fraction of capacity, never guarantees a trajectory any cumulative
  share, and never promotes more than the highest-ranked non-leading
  task. A floor is a minimum, not an allocation plan.
- **The floor never forces dispatch:** it reorders; the claim path still
  applies eligibility, gates, dependencies, and the call cap. A promoted
  task that fails any of them is not dispatched, and the floor does not
  substitute another.

### 2.2 Call-cap interaction: the floor operates WITHIN the cap, never expands it

**Resolved: the floor consumes capacity; it never creates it.**

- The round's available slot count is `min(floor_slots_eligible_count,
  remaining_call_capacity)` where remaining call capacity is
  `max_calls_per_tick − calls_already_made_this_tick`
  (`controller.py:3018–3019` semantics). If remaining capacity is zero,
  the floor grants nothing and the tick idles on the cap exactly as it
  does today.
- The reserved slot is the LAST available slot of the round, never the
  first: the leader keeps the top `capacity − floor_slots` slots under
  pure policy order. The floor is a floor on the non-leader, not a tax on
  the leader beyond one slot.
- `floor_slots` is always < `max_calls_per_tick` (validated at policy
  construction; a configuration violating this is rejected, not clamped —
  fail-closed, observable).

### 2.3 Decay semantics: the F-C decay-or-kill-switch rule (mandatory, both modes designed)

**Resolved: the floor carries an explicit decay-or-kill-switch, per
blueprint §21 F-C. A trajectory that receives the floor slot for N
consecutive eligible rounds with ZERO new obligation satisfaction either
loses its floor entitlement (decay mode) or is suspended from the floor
until a new eligible obligation appears (kill-switch mode). N is a
versioned policy parameter (`floor_stagnation_rounds`). The floor
protects exploration, not stagnation; a permanent entitlement is failure
mode B by construction.**

- **"New obligation satisfaction" is a stored fact, never a judgment:**
  a round counts as productive for the floored trajectory iff at least
  one new satisfaction link (IDR-038 §3.1) is recorded for one of its
  programs between that round and the next. Satisfaction links are
  append-only stored rows — the counter is a pure derivation from them
  and the floor-grant history, never a mutable stored counter.
- **Floor-grant history is derived, not stored as mutable state:** each
  floor grant is recorded as an append-only `FloorGrantRecorded` event
  (§4.3) — a durable, content-derived audit record, NOT the transient
  ranking (which is never persisted, `evaluation.py:494–511`). The
  consecutive-grant counter is re-derived each round from those events +
  the satisfaction links. Same F2 discipline as everywhere else: the
  derivation is the authority, any cache of it is compared, never
  trusted.
- **Decay mode:** after N stagnant rounds, the trajectory's floor
  entitlement is withdrawn for a versioned cooldown
  (`floor_decay_cooldown_rounds`); after the cooldown it may re-qualify.
- **Kill-switch mode:** after N stagnant rounds, the trajectory is
  suspended from the floor until a NEW eligible obligation appears for
  one of its programs (a new outstanding obligation fact in the
  `task_obligations.py` derivation — the same pure facts the ordering
  reads). Re-admission is automatic and deterministic when the fact
  appears; no human action, no agent intent.
- **Mode selection is a versioned policy parameter** (`floor_stagnation_
  mode` ∈ {`decay`, `kill_switch`}). This gate designs BOTH; the default
  is deferred to the architecture team (§7.3). Both modes are
  deterministic and version-bound; neither reads wall-clock time.

### 2.4 The degenerate-to-baseline fallback

**Resolved: the floor reuses the Q-02 §18.4 degenerate-to-baseline
pattern. Whenever the floor's inputs cannot be derived — no non-leading
eligible task exists, the trajectory label is unresolvable, a program row
is corrupt (the existing fail-closed skip, `controller.py:1948–1955`), or
the floor policy is malformed — the ordering falls back to PURE POLICY
ORDERING, and the fallback is recorded as an observable diagnostic, never
a silent skip and never a crash.**

- New `TaskDiagnosticKind` values (additive): `FLOOR_GRANTED` (the floor
  fired — which trajectory, which task, which slot), `FLOOR_INERT`
  (eligible set is single-trajectory or no non-leader exists — the floor
  had nothing to do), `FLOOR_DEGENERATE_TO_BASELINE` (inputs
  underivable/corrupt — pure policy stands), `FLOOR_STAGNANT` (the
  decay/kill-switch counter advanced), `FLOOR_ENTITLEMENT_WITHDRAWN` /
  `FLOOR_SUSPENDED` / `FLOOR_READMITTED` (the F-C state transitions).
- Diagnostics are advisory observables — they ride the existing transient
  hashed ranking (`evaluation.py:494–511`) and the event payload that
  surfaces it. They are never gate inputs, never persisted as mutable
  state (blueprint §22 condition 1: projections are queries, not stores).

---

## 3. Exact authority owner

- **Who decides the floor's behavior?** The **versioned ordering policy**
  — the same authority that owns `TASK_ORDERING_POLICY` today
  (`evaluation.py:439–447`). C4 amends that policy string and its version
  triple; it creates no new decision-maker. A floor-policy change IS a
  `policy_version` change, subject to the same review discipline Q-02
  established (blueprint attack D's vigilance note applies: every
  policy_version change is reviewed for scalar creep).
- **Who consumes the floor?** The **Controller** (`_order_eligible`,
  `controller.py:1914–1932`) — exactly where it consumes the pure policy
  order today. No new consumption surface.
- **Does the floor admit, gate, budget, or decide?** **No.** It reorders
  the already-eligible set. Eligibility, gates, dependencies, the call
  cap, and the budget are untouched (§4.4 exclusions). The floor is
  ordering policy and nothing else — Q-02 Model B's authority shape
  exactly (the Q-02 gate §3: "changes its ORDERING RULE, nothing else").
- **Does the floor read spent budget or sunk cost?** **No.** The
  stagnation counter reads NEW satisfaction links (forward-looking
  obligation facts), never spent budget — attack O's invariant is
  preserved (§4.4).

---

## 4. The contract

### 4.1 The floor amendment (policy surface)

The versioned ordering policy gains a floor clause, parametric in:

| Parameter | Meaning | Default (proposed) |
|---|---|---|
| `floor_slots` | slots reserved per round when the floor fires | 1 |
| `floor_stagnation_rounds` (N) | consecutive unproductive floor grants before F-C fires | team decision (§7.3) |
| `floor_stagnation_mode` | `decay` or `kill_switch` | team decision (§7.3) |
| `floor_decay_cooldown_rounds` | decay-mode cooldown after withdrawal | team decision (§7.3) |
| trajectory label function | day-one: program provenance ref | program-level (§7.1) |

All parameters are version-bound; any change bumps `policy_version`. The
floor clause is part of the `TASK_ORDERING_POLICY` string, so the
ordering identity (`ranking_id`, content-derived) reflects it — same
inputs + same version triple ⇒ same ordering, floor included.

### 4.2 The floor function (deterministic specification)

```
GIVEN: eligible set E (already eligible — dependencies, gates, budget OK),
       round capacity C = remaining call-cap slots (> 0),
       trajectory label λ(task), pure obligation facts,
       floor-grant history + satisfaction links (derived, §2.3)

1. order E by pure policy (_task_ordering_key) → O
2. if C == 0: floor grants nothing (cap binding); emit FLOOR_INERT
3. let T_lead = λ(O[0]); let top_C = O[:C]
4. if {λ(t) for t in top_C} has > 1 trajectory: floor inert
   (pure policy already diversifies); emit FLOOR_INERT
5. let candidates = [t in O if λ(t) != T_lead and not F-C-suspended]
6. if candidates empty: floor inert; emit FLOOR_INERT
7. promote candidates[0] into slot position C-1 (the last available
   slot); emit FLOOR_GRANTED(trajectory, task, slot)
8. update the derived F-C counter for λ(candidates[0]):
   productive round (≥1 new satisfaction link since last grant) → reset;
   unproductive → increment; at N → emit FLOOR_ENTITLEMENT_WITHDRAWN
   (decay) or FLOOR_SUSPENDED (kill-switch)
9. any underivable input → pure policy stands; emit
   FLOOR_DEGENERATE_TO_BASELINE (never a crash, never silent)
```

The function is pure: no clock, no random, no SQL, no write path, no LLM
input — the same purity contract as `evaluate_eligible_tasks`
(`evaluation.py:521–527`). It extends that function (or wraps it); it
does not replace the ratified ordering key.

### 4.3 Observability (the audit surface)

- Every floor state transition is a ranking diagnostic (§2.4 vocabulary)
  surfaced in the transient ranking, AND every floor grant / F-C
  transition is ALSO recorded as an append-only `FloorGrantRecorded`
  event (content-derived id, trajectory/task/slot facts, F-C counter
  state) — because the ranking itself is never persisted
  (`evaluation.py:494–511`), the event is the durable substrate. This is
  the same pattern as `RefutedApplied` (a first-class event for a fact
  consumers must read without re-deriving the whole pass).
- The F-C counter is re-derivable from those events + the satisfaction
  links: an auditor (or the C6 convergence diagnostic) can recompute the
  entire floor history without trusting any stored counter.
- **C6 handoff (blueprint F-G):** the `FLOOR_EXHAUSTED` advisory signal
  belongs to the C6 convergence diagnostic, NOT to this gate. C6 reads
  the same derived facts (N consecutive floor grants, zero new
  satisfaction) and surfaces "the floor is feeding a stagnant trajectory"
  to the human convergence decision. Advisory only, never a gate input —
  the F-C decay/kill-switch is the ONLY auto-acting consequence, and it
  acts on floor entitlement, never on research state.

### 4.4 What C4 does NOT do (explicit exclusions)

- **NOT a quota or share plan.** No trajectory is guaranteed cumulative
  allocation; the floor is a per-round minimum reservation (§2.1).
- **NOT an eligibility mechanism.** The floor never admits an ineligible
  task, never overrides a gate, dependency, or the call cap (§2.1, §2.2).
- **NOT a second scheduler.** It is a clause in the ratified ordering
  policy, consumed where the policy is consumed today. No new authority,
  no new dispatch path (blueprint §22 condition 2; failure mode R stays
  solved).
- **NOT a scalar.** The floor is a structural reservation rule over the
  lexicographic order — no weight, no score, no composite. The no-scalar
  invariant (IDR-019, attack D) is untouched: the ordering key
  (`_task_ordering_key`) is unchanged; the floor permutes its OUTPUT
  under a documented, versioned constraint.
- **NOT a sunk-cost reader.** The stagnation counter reads new
  satisfaction links only, never spent budget (attack O invariant).
- **NOT an effort-normalizer.** The floor bounds allocation asymmetry; it
  does not correct for it in the dimensions. Effort-normalization as a
  dimension stays rejected (blueprint §21, K/L analysis).
- **NOT a convergence mechanism.** Convergence remains human-gated
  (HR-08); the floor's F-C rule withdraws entitlement from stagnant
  trajectories — it never declares a winner, never pauses a program,
  never transitions research state.

### 4.5 Composition with C5 (the Director-priority gate)

C4 and C5 both modify the ordering; they must compose without conflict.
The rule (mirrored verbatim in the C5 gate's §5 — the two gates are
mutually aware; this section was added by the 2026-08-20 independent
adversarial review, which found the composition lived in C5 only):

1. **Priority reorders FIRST** (C5's §4.2 clause, below the dimensions).
2. **The floor applies SECOND** to the priority-reordered set: C4's
   "highest-policy-ranked non-leading task" (§4.2 step 5) is selected
   from the priority-aware order. So an ELEVATE'd non-leading trajectory
   is more likely to receive the floor slot — priority influences WHICH
   non-leader the floor promotes, never WHETHER the floor fires.
3. **Priority never exempts from the floor's F-C rule.** A SUSTAIN'd or
   ELEVATE'd stagnant trajectory still loses its floor entitlement under
   §2.3. Priority affects ordering; the floor's decay/kill-switch
   governs floor entitlement. The two are orthogonal by construction.
4. **No priority can suppress the floor.** The floor's reservation is a
   structural clause of the same policy; a DEPRIORITIZE on the floor's
   beneficiary reorders the non-leading candidates but does not cancel
   the reserved slot.

**Joint C4×C5 test matrix (pre-P4 readiness brief §11, 2026-08-20).** The
composition contract must be proven across this matrix at implementation
(each cell = the floor decision + the priority consumption, asserted
together):

| # | Priority state | Trajectory state | Round shape | Expected |
|---|---|---|---|---|
| 1 | none | — | diverse top-C | floor inert (AC-1) |
| 2 | none | monopoly | — | floor fires, pure-policy pick (AC-2) |
| 3 | ELEVATE | non-leading elevated | monopoly | floor fires; elevated non-leader preferred for the slot |
| 4 | SUSTAIN | non-leading sustained | monopoly | floor fires; sustain holds position, no extra promotion |
| 5 | DEPRIORITIZE | floor beneficiary | monopoly | floor still fires; beneficiary reorders among non-leaders, slot NOT cancelled |
| 6 | ELEVATE | stagnant (F-C decayed) | monopoly | floor entitlement lost under F-C despite priority (rule 3) |
| 7 | any | zero-claim round | cap binding / empty set | no floor grant, no priority consumption, TTL not advanced (C5 §2.5) |
| 8 | inert (admitted under non-consuming version) | monopoly | — | floor fires on PURE-policy order; priority not consumed (C5 AC-12) |

Cells 6–8 are the adversarial core: they prove priority never exempts from
F-C, never suppresses the floor, and never silently activates.

---

## 5. Implementation surface (for the future implementation phase)

Exact and minimal:

1. `evaluation.py` — the floor clause in/around `evaluate_eligible_tasks`
   (a floor-aware wrapper that calls the ratified pure ordering first,
   then applies §4.2 steps 2–9); the §2.4 diagnostic vocabulary added to
   `TaskDiagnosticKind`; floor parameters in the policy version triple.
   The ratified `_task_ordering_key` is NOT modified.
2. `controller.py` — `_order_eligible` passes the round's remaining
   call-cap slot count into the floor-aware evaluation; each floor grant
   / F-C transition appends a `FloorGrantRecorded` event (the durable
   substrate — the ranking itself is transient).
3. `task_obligations.py` — no change to the derivation; the floor reads
   its existing pure facts (the blueprint §26.2 consistency note holds:
   label computation is a deterministic read, not an authority).
4. **No migration, no new table, no new intent, no new gate.** One new
   event type (`FloorGrantRecorded`) is added to the catalog — the one
   flagged exception (§ header). The floor-grant history lives in those
   append-only events; the F-C counter is derived.
5. **Deferred consumer (C6):** the `FLOOR_EXHAUSTED` advisory signal is
   C6's design surface (§4.3) — not implementable until C6 is designed.

---

## 6. Acceptance criteria (the implementation must prove all of these)

- **AC-1 — floor inert under diversity.** When pure policy ordering's top
  C slots already span ≥ 2 trajectories, the floor changes NOTHING: the
  floor-aware ordering equals the pure policy ordering, and the ranking
  emits `FLOOR_INERT`.
- **AC-2 — floor fires under monopoly.** When all top-C slots belong to
  one trajectory and a non-leading eligible task exists, exactly ONE
  non-leading task (the highest-policy-ranked) is promoted into the last
  available slot; the leader keeps the remaining C−1 slots in pure policy
  order; `FLOOR_GRANTED` emitted with trajectory/task/slot facts.
- **AC-3 — cap binding.** When remaining call-cap capacity is zero, the
  floor grants nothing and the tick idles on the cap exactly as today;
  `floor_slots` ≥ capacity configurations are rejected at policy
  construction (fail-closed, observable).
- **AC-4 — determinism.** Identical eligible set + identical version
  triple + identical derived facts ⇒ identical `ranking_id` and identical
  floor decision, independent of replay order or schedule.
- **AC-5 — degenerate-to-baseline.** No non-leading eligible task, an
  unresolvable trajectory label, or a corrupt program row ⇒ pure policy
  ordering stands with `FLOOR_DEGENERATE_TO_BASELINE` (or `FLOOR_INERT`)
  emitted — never a crash, never a silent skip.
- **AC-6 — F-C counter derivation.** The consecutive-unproductive count
  is a pure function of the floor-grant records + satisfaction links: a
  round with ≥ 1 new satisfaction link for the floored trajectory resets
  the count; N consecutive unproductive rounds fire the configured mode.
- **AC-7 — decay mode.** After N stagnant rounds the trajectory loses its
  floor entitlement for the cooldown; during cooldown it is skipped by
  step 5; after the cooldown it may re-qualify; every transition emitted
  (`FLOOR_STAGNANT` → `FLOOR_ENTITLEMENT_WITHDRAWN` → re-grant).
- **AC-8 — kill-switch mode.** After N stagnant rounds the trajectory is
  suspended (`FLOOR_SUSPENDED`); it is automatically re-admitted the
  round a new eligible obligation fact appears for one of its programs
  (`FLOOR_READMITTED`); no human or agent action is involved in either
  transition.
- **AC-9 — no authority leak.** Structural fixtures: no new `IntentKind`,
  no new table, no migration, `_task_ordering_key` unchanged, no
  eligibility/gate/dependency/budget predicate touched, no spent-budget
  read anywhere in the floor path.
- **AC-10 — no scalar.** The floor introduces no numeric score, weight, or
  composite: the extension of the existing no-scalar structural tests
  (`test_evaluation.py:338+` pattern) passes over the floor-aware
  ranking.

---

## 7. Open questions for the architecture team (decisions this gate
defers, none blocking the contract)

1. **Trajectory granularity:** day-one keying is the program provenance
   ref (§2.1). Rival hypotheses within one program are the blueprint's
   portfolio shape (§22 condition 1) — should the floor key on
   (program, hypothesis) so rivals inside one program also get floor
   protection, or is program-level sufficient until practice says
   otherwise? The contract is parametric in the label function; either
   answer is a policy-version choice, not a contract change.
2. **Floor slot count:** `floor_slots` default 1 is proposed. With
   `max_calls_per_tick = 8` the leader keeps ≥ 7 slots — is that the
   right bound, or should the default scale (e.g. 1 per 8 capacity)?
   Scaling rules risk becoming allocation plans (§4.4); the team should
   confirm the flat default.
3. **F-C parameters and mode:** `floor_stagnation_rounds` (N),
   `floor_decay_cooldown_rounds`, and the default mode (`decay` vs
   `kill_switch`) are open. Both modes are fully designed (§2.3); the
   choice is a values judgment about how patiently the system should fund
   a stagnant trajectory. Kill-switch is the stricter reading of "the
   floor protects exploration, not stagnation"; decay is the more
   forgiving one.
4. **Interaction with the active-trajectory bound (§19 Q5):** if a future
   admission bound caps concurrently-ACTIVE trajectories, the floor and
   the bound must agree on which trajectories exist. The floor is
   ordering-side (within the eligible set); the bound is admission-side.
   This gate assumes they compose independently; the team should confirm
   when Q5 is designed.
5. **Floor-grant event surface (RESOLVED by cross-check):** the original
   text assumed the floor history could ride an existing ranking-summary
   event payload — but no such persisted payload exists (the ranking is
   transient). §4.3 now adds the `FloorGrantRecorded` event as the
   durable substrate. The team should confirm the event-type addition is
   acceptable, or propose an alternative durable record.

---

## 8. Authority boundary (ratifiable text, pending approval)

- **CAN** reserve at most `floor_slots` dispatch slots per round for the
  highest-ranked non-leading eligible task — a versioned clause in the
  ratified Q-02 ordering policy, consumed at the existing consumption
  point.
- **CAN** withdraw or suspend a stagnant trajectory's floor entitlement
  (the F-C rule) — acting on floor entitlement only, derived from
  append-only facts, deterministic, version-bound.
- **CAN** emit the §2.4 diagnostic vocabulary as advisory observables on
  the existing ranking surface.
- **CANNOT** expand the call cap, admit an ineligible task, override a
  gate/dependency/budget, or substitute a task that fails any of them.
- **CANNOT** guarantee any trajectory a cumulative allocation share — the
  floor is a per-round minimum, never a quota.
- **CANNOT** read spent budget, name tasks, or introduce any scalar —
  ordering key unchanged, no-scalar invariant intact.
- **CANNOT** declare convergence, pause a program, or transition any
  research state — convergence remains human-gated (HR-08).

---

*End of C4 design gate. Status: DESIGN — awaiting blueprint ratification
and operator approval before any implementation phase. No file in `src/`,
`tests/`, or `docs/idr/` is touched by this document.*
