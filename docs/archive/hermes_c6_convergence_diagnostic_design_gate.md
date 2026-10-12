# HERMES C6 — THE CONVERGENCE DIAGNOSTIC: DESIGN GATE

**Status:** DESIGN (2026-08-19) — no implementation, no digest change, no
code, no IDR. This is the design gate the five-fundamentals blueprint
requires for C6: §19 Q6 — "exact signal set (obligation coverage, rival
status, open contradictions, mutation depth); consumption surface
(DirectorDigest extension?); never-a-gate-input rule." §21 C6 pins the
shape: "Derived, hashed, advisory projection (obligation coverage + rival
status + open contradictions + mutation depth + the existing Q-02
diagnostics). Informs the human convergence decision; never a gate input."
§21 F-G adds the mandatory `FLOOR_EXHAUSTED` signal. **Nothing here is
ratified.** Implementation is gated on (a) ratification of the five-
fundamentals blueprint itself and (b) operator approval of this gate's
decisions.

> **Ratification update (2026-08-20, additive):** this contract was RATIFIED
> as a read-only, never-a-gate-input advisory surface with the
> NOT_DERIVABLE honesty discipline by operator ratification —
> `hermes_architecture_ratification.md` §5 (architecture frozen;
> implementation separately chartered, Step 8, P4-gated). The status
> paragraph above is the historical pre-ratification record.

**Cross-check remediation (2026-08-19):** the four-gate cross-check found
that S5's source (C4's floor-grant records) originally cited a substrate
that did not exist (the transient ranking). C4 was remediated to add the
append-only `FloorGrantRecorded` event as the durable substrate; S5's
derivation below is updated to read those events. C6's contract is
otherwise unchanged.

**Inputs:** `hermes_five_fundamentals_blueprint.md` §19 Q6, §21 C6 (F-G
`FLOOR_EXHAUSTED`), §22 condition 1 (projections are queries, not stores),
§22 closing condition (convergence is human-gated, HR-08), §27 (corrected
re-grade); `src/hermes/research/controller.py` (`reconcile_digest`
:981–1015 — the READ-ONLY, version-bound, content-hashed composite digest;
`RECONCILE_DIGEST_VERSION = "4"` :87; `propose_refutation_actions` :1083+
— the observe→act loop precedent; `_program_head_id` :1961 — head
derivation); `src/hermes/research/task_obligations.py` (obligation-fact
derivation :44+; `contradiction_reduction` always NONE :124 — "no stored
source in the current schema"); `src/hermes/core/intents.py`
(`CONTRADICTION_RESOLUTION` declared-but-deferred :42–49 — the
contradiction machinery is agent-runtime scope, NOT implemented);
`src/hermes/research/evaluation.py` (the Q-02 diagnostics C6 folds:
`STARVED_CANDIDATE`/`STALE_INPUT`/`NO_IMPROVEMENT` :89–92, task-side
`DEGENERATE_TO_BASELINE` :452); `hermes_c4_exploration_floor_design_gate.md`
§4.3 (the F-C derived facts C6 reads); `hermes_c5_director_priority_design_gate.md`
§4.3 (the priority history C6 reads).

---

## 1. Repository reconciliation (verified live, 2026-08-19)

| Blueprint C6 claim | Live repository fact | Verdict |
|---|---|---|
| "Derived, hashed, advisory projection … consumption surface (DirectorDigest extension?)" | The Director-facing digest IS a read-only, version-bound, content-hashed composite: `reconcile_digest()` (`controller.py:981–1015`) folds six deterministic sections and hashes the body; "Everything the Director needs to ACT is here, and nothing here can act" | CONFIRMED — the digest is the consumption surface; C6 is a new section + version bump |
| "obligation coverage" signal | `task_obligations.py` derives per-requirement obligation facts from compiled program rows + satisfaction links (:44+); satisfaction links are per-(program, requirement) stored rows (IDR-038 §3.1) | CONFIRMED DERIVABLE — obligation coverage is a pure function of existing stored facts |
| "rival status" signal | The head program's hypothesis structure carries `rival_of`/`rival_status` (`programs.py:188–200`); the `evidence_ladder_state` rows carry per-(program, hypothesis) rungs (IDR-041 §6); `refutation_review_candidates()` already surfaces dependent rival hypotheses with rungs | CONFIRMED DERIVABLE — rival status is a pure function of the head program + ladder state |
| "open contradictions" signal | **NOT derivable today.** The contradiction machinery is declared-but-deferred: `CONTRADICTION_RESOLUTION` is NOT proposable until the agent runtime lands (`intents.py:42–49`); there is no `CONTRADICTION_DETECTED` emitter; `contradiction_reduction` is always NONE ("no stored source in the current schema", `task_obligations.py:124`) | CONFIRMED ABSENT — the signal slot is designed but NOT implementable until the contradiction machinery lands; see §2.3 |
| "mutation depth" signal | Supersession is a stored, immutable chain: every program row carries `supersedes_ref` (`programs.py:260`); the head is derived (`controller.py:1961`); the chain is walkable from the head | CONFIRMED DERIVABLE — mutation depth is the supersession-chain length from the head, a pure function of immutable program rows |
| "the existing Q-02 diagnostics" | Action-side: `STARVED_CANDIDATE`/`STALE_INPUT`/`NO_IMPROVEMENT` (`evaluation.py:89–92`); task-side: `EMPTY_ELIGIBLE_SET`/`DEGENERATE_TO_BASELINE` (:450–452) | CONFIRMED — C6 folds the existing diagnostic vocabulary, adds nothing that duplicates it |
| "never a gate input" | The digest's own contract: "nothing here can act: never writes, never executes, never retracts — the classification/graph advisory posture" (`controller.py:991–993`) | CONFIRMED — C6 inherits the digest's advisory posture by construction |
| "F-G: `FLOOR_EXHAUSTED` … fired when the exploration floor (C4) has granted a trajectory its floor slot for N consecutive ticks with zero new obligation satisfaction" | C4's F-C counter is derived from floor-grant records + satisfaction links (C4 gate §2.3/§4.3) — the exact facts C6 needs | CONFIRMED DERIVABLE (once C4 lands) — C6 reads C4's derived facts, never its own counter |

**Verified gap:** the Director and the human have no single surface that
answers "is this research converging?" The digest surfaces failure facts
(classifications, falsifications, re-review candidates) but no
convergence picture: no obligation-coverage fraction, no rival-status
summary, no mutation depth, no floor-exhaustion signal. C6 is that
picture — advisory, hashed, and structurally unable to act.

---

## 2. DECISION — the three §19-Q6 questions, resolved

### 2.1 Question 1 — the exact signal set

**Resolved: C6 is a fixed, versioned set of FIVE advisory signals, each a
pure derivation from existing stored facts. Signals whose source facts do
not yet exist are designed as slots and emit NOT_DERIVABLE until their
source lands.**

| # | Signal | Derivation (source facts) | Status |
|---|---|---|---|
| S1 | **Obligation coverage** — per program: (satisfied requirements / total requirements), per ladder target; plus the project-level rollup | `task_obligations.py` obligation facts + IDR-038 satisfaction links | DERIVABLE today |
| S2 | **Rival status** — the head program's hypothesis set: each hypothesis's ladder rung + rival structure (ACTIVE/UNRESOLVED), and which rivals are REFUTED | head program (`_program_head_id`) + `evidence_ladder_state` rungs + `rival_of`/`rival_status` | DERIVABLE today |
| S3 | **Open contradictions** — the count + refs of detected-but-unresolved contradictions | the contradiction machinery (`CONTRADICTION_DETECTED` emitter + resolution routing) | **NOT DERIVABLE today** — declared-but-deferred (`intents.py:42–49`); emits `NOT_DERIVABLE` until it lands (§2.3) |
| S4 | **Mutation depth** — the supersession-chain length from the head program (how many program versions the current head sits atop) | the immutable `research_programs` rows' `supersedes_ref` chain, walked from the head | DERIVABLE today |
| S5 | **Floor exhaustion (F-G)** — per trajectory: whether C4's floor has granted it the slot for N consecutive rounds with zero new obligation satisfaction | C4's derived F-C facts (floor-grant records + satisfaction links) | DERIVABLE once C4 lands; emits `NOT_DERIVABLE` until then |

Plus the **fold of the existing Q-02 diagnostics** (§21 C6's "+ the
existing Q-02 diagnostics"): the digest's C6 section re-surfaces the
current round's `STARVED_CANDIDATE`/`STALE_INPUT`/`NO_IMPROVEMENT`
(action-side) and `DEGENERATE_TO_BASELINE`/`FLOOR_*` (task-side)
diagnostics, so the convergence picture and the ordering diagnostics live
in one place. C6 adds NO new ordering diagnostic — it folds, never
duplicates.

**The signal set is closed and versioned.** Adding a signal is a
`digest_version` change subject to review; there is no free-form
"convergence score," no composite, no scalar. Each signal is a fact or
`NOT_DERIVABLE` — never a guess, never a fill-in (the Q-02 §18.4
degenerate-to-baseline honesty discipline, extended).

### 2.2 Question 2 — the consumption surface: a digest section, version bump

**Resolved: C6 is a new `convergence` section of `reconcile_digest()`,
with `RECONCILE_DIGEST_VERSION` bumped 4 → 5. It is content-hashed as
part of the existing composite, deterministic, read-only, and re-derived
on every call — never persisted, never cached as mutable state.**

- The section shape:
  ```
  "convergence": {
    "obligation_coverage": { per-program + rollup },
    "rival_status": { per-hypothesis rung + rival structure },
    "open_contradictions": { count, refs } | "NOT_DERIVABLE",
    "mutation_depth": { head program_id, chain length },
    "floor_exhaustion": { per-trajectory F-C facts } | "NOT_DERIVABLE",
    "folded_diagnostics": [ the current Q-02/FLOOR diagnostics ],
    "signal_schema_version": "<versioned>"
  }
  ```
- The digest's existing contract carries C6 automatically: read-only
  ("nothing here can act"), version-bound, content-hashed composite,
  deterministic. C6 changes nothing about the digest's posture — it adds
  one section to the body that is already hashed.
- **The human surface:** the convergence section is what the operator
  reads to make the convergence decision (pivot / continue / abandon).
  The decision itself is the human's, through the existing operator
  channel — C6 informs it, never makes it (§4.4).

### 2.3 The NOT_DERIVABLE discipline (the honest-slots rule)

**Resolved: a signal whose source facts do not exist yet emits the literal
`NOT_DERIVABLE` marker with the reason — never zero, never empty, never a
silent omission.**

- S3 (open contradictions) emits `NOT_DERIVABLE` because the contradiction
  machinery is declared-but-deferred (`intents.py:42–49`). Emitting zero
  would be a lie — "no detected contradictions" is not the same as "no
  contradiction-detection capability." The marker names the missing
  source so the human knows the picture is partial.
- S5 (floor exhaustion) emits `NOT_DERIVABLE` until C4 lands.
- When a source lands (the contradiction machinery; C4), the signal
  flips from `NOT_DERIVABLE` to its real value under the SAME
  `signal_schema_version` — the flip is a `digest_version`-observable
  change, never a silent schema drift.
- This is the same honesty as `task_obligations.py:124` ("no stored
  source in the current schema … always NONE — the honest §18.4
  degeneracy, documented, never a guess"). C6 extends that discipline
  from dimensions to convergence signals.

### 2.4 Question 3 — the never-a-gate-input rule

**Resolved: C6 is structurally unable to act. It is a read-only digest
section; no gate, no ordering policy, no eligibility predicate, no ladder
derivation, no budget, and no dispatch path reads it. The rule is enforced
by construction (C6 exists only inside the digest body) AND by acceptance
criteria (AC-6/AC-7 structural fixtures).**

- The digest's own contract already says "nothing here can act"
  (`controller.py:991–993`). C6 inherits it.
- The one "act" adjacent to the digest — `propose_refutation_actions()`
  (`controller.py:1083+`) — consumes the digest to PROPOSE classification
  actions, and even those still require their existing authority. C6's
  convergence section is NOT an input to that loop: it proposes nothing,
  triggers nothing, and no future consumer may read it as a gate input
  without a new design gate (AC-7 pins this).
- **The convergence decision is the human's** (HR-08; blueprint §22
  closing condition: "Auto-convergence — any mechanism that declares a
  winner without the human gate" is in the "should explicitly NOT enter
  the architecture" list). C6 informs; the human decides.

---

## 3. Exact authority owner

- **Who computes C6?** The **controller's digest derivation** — the same
  read-only surface that computes the six existing sections
  (`controller.py:981–1015`). C6 adds one more deterministic derivation,
  no new authority.
- **Who consumes C6?** The **human operator** (the convergence decision)
  and the **Director** (as advisory context in the digest it already
  reads). No machine consumer may treat it as a gate input (§2.4).
- **Does C6 decide convergence?** **No.** It is a picture, never a
  verdict. The pivot/continue/abandon decision is the human's, through
  the existing operator channel.
- **Does C6 write anything?** **No.** It is derived on call, hashed into
  the digest composite, and never persisted as mutable state. The only
  durable trace is the append-only digest event payload that already
  carries the digest body.

---

## 4. The contract

### 4.1 The derivation (pure-function specification)

```
GIVEN: the project's immutable program rows, satisfaction links,
       evidence_ladder_state rows, the head program, C4's derived F-C
       facts (when C4 lands), the current Q-02/FLOOR diagnostics

S1 obligation_coverage:
  for each program: satisfied/total per ladder target (from
  task_obligations facts + satisfaction links); project rollup
S2 rival_status:
  head program's hypotheses: rung (from evidence_ladder_state) +
  rival_of/rival_status; flag REFUTED rivals
S3 open_contradictions:
  NOT_DERIVABLE (contradiction machinery deferred) — flips to
  {count, refs} when the machinery lands
S4 mutation_depth:
  walk supersedes_ref from the head; chain length + head program_id
S5 floor_exhaustion:
  NOT_DERIVABLE until C4 lands — then per-trajectory F-C facts
  (consecutive floor grants, new-satisfaction count, F-C mode state)
folded_diagnostics:
  the current round's Q-02 + FLOOR diagnostic list (fold, never duplicate)
```

The derivation is pure: no clock, no random, no write path, no LLM input
— the same purity contract as the digest's existing sections. It reads
only stored facts and other gates' derived facts; it invents nothing.

### 4.2 Determinism and identity

- Same stored facts + same `digest_version` + same `signal_schema_version`
  ⇒ byte-identical `convergence` section and identical composite
  `content_hash`. The digest is already content-hashed as a composite
  (`controller.py:1012–1015`); C6 rides that hash.
- The `convergence` section carries its own `signal_schema_version` so a
  signal-set change is version-observable, and a `NOT_DERIVABLE`→real
  flip is attributable.

### 4.3 The C4/C5 read contract (cross-gate)

- **From C4:** C6 reads C4's DERIVED F-C facts — the append-only
  `FloorGrantRecorded` events (C4 gate §4.3, the durable substrate added
  by the cross-check remediation) + the satisfaction links — never a
  stored counter. `FLOOR_EXHAUSTED` fires in C6 when C4's derivation
  shows N consecutive floor grants with zero new obligation satisfaction
  for a trajectory (the same N as C4's decay/kill-switch — C4 gate
  §2.3). C6 surfaces it; C4's F-C rule is the only auto-acting
  consequence. C6 never re-implements the counter.
- **From C5:** C6 may surface an advisory "the Director has held
  trajectory X for N rounds" from C5's priority history (C5 gate §4.3) —
  advisory context for the human, never a gate input. This is optional
  and versioned; the team may drop it (§7.2).

### 4.4 What C6 does NOT do (explicit exclusions)

- **NOT a convergence verdict.** No "converged"/"done"/"winner" state;
  the human decides (HR-08; blueprint §22 NOT-list).
- **NOT a gate input.** No gate, ordering policy, eligibility predicate,
  ladder derivation, budget, or dispatch path reads it (§2.4; AC-6/AC-7).
- **NOT a scalar or composite.** Five named signals + a fold; no score,
  no weight, no ranking (attack D discipline).
- **NOT a store.** Derived on call, hashed into the digest, never
  persisted as mutable state (blueprint §22 condition 1: projections are
  queries, not stores).
- **NOT a trigger.** It proposes nothing, emits no intent, and is not an
  input to `propose_refutation_actions()` or any observe→act loop.
- **NOT a fill-in.** A missing source is `NOT_DERIVABLE`, never zero or
  empty (§2.3).

---

## 5. Implementation surface (for the future implementation phase)

Exact and minimal:

1. `controller.py` — a `_convergence_section()` derivation helper called
   from `reconcile_digest()`; `RECONCILE_DIGEST_VERSION` bumped 4 → 5;
   the section added to the hashed body. No change to the digest's
   read-only posture.
2. `task_obligations.py` — no change; C6 reads its existing pure facts.
3. **No migration, no new table, no new intent, no new gate.** The only
   durable trace is the existing append-only digest event payload.
4. **Deferred source (S3):** the open-contradictions signal flips from
   `NOT_DERIVABLE` to real when the contradiction machinery
   (`CONTRADICTION_DETECTED` emitter + resolution routing) lands — that
   is agent-runtime scope (`intents.py:42–49`), a separate milestone.
5. **Deferred source (S5):** the floor-exhaustion signal flips from
   `NOT_DERIVABLE` to real when C4 lands.

---

## 6. Acceptance criteria (the implementation must prove all of these)

- **AC-1 — signal set completeness.** The `convergence` section carries
  exactly S1–S5 + `folded_diagnostics` + `signal_schema_version`; no
  extra signal, no free-form field.
- **AC-2 — obligation coverage correctness.** S1's per-program
  satisfied/total matches the `task_obligations` derivation + satisfaction
  links; the project rollup is the deterministic aggregate.
- **AC-3 — rival status correctness.** S2 reflects the head program's
  hypothesis rungs + rival structure; REFUTED rivals are flagged; a
  project with no head program emits a documented empty/`NOT_DERIVABLE`
  shape, never a crash.
- **AC-4 — NOT_DERIVABLE honesty.** S3 emits `NOT_DERIVABLE` (naming the
  deferred contradiction machinery) while the machinery is absent; S5
  emits `NOT_DERIVABLE` while C4 is absent; neither emits zero/empty.
- **AC-5 — mutation depth correctness.** S4's chain length equals the
  `supersedes_ref` walk from the head; a head with no supersession has
  depth 0; a project with NO program at all emits the documented
  empty/NOT_DERIVABLE shape (head = None); a corrupt/unresolvable row
  fails closed to a documented shape, never a crash.
- **AC-6 — never a gate input (structural).** No gate, ordering policy,
  eligibility predicate, ladder derivation, budget, or dispatch path
  references the `convergence` section; a grep-level structural fixture
  pins this. **Named-key-only pin (independent review 2026-08-20):** the
  fixture also pins that digest consumers access sections by named key
  only (no key-agnostic iteration, e.g. `digest.values()`), so a future
  consumer cannot silently ingest the section.
- **AC-7 — not a trigger.** `propose_refutation_actions()` and every
  observe→act loop consume the digest WITHOUT the `convergence` section
  as an input; C6 emits no intent and proposes nothing.
- **AC-8 — determinism.** Identical stored facts + version ⇒
  byte-identical `convergence` section and identical composite
  `content_hash`, independent of call order or schedule.
- **AC-9 — read-only.** Computing the `convergence` section writes
  nothing: no row inserted/updated/deleted, no event appended by the
  derivation itself (the digest event that carries it is the existing
  append-only surface).
- **AC-10 — no scalar.** The section contains no numeric score, weight,
  or composite ranking; the no-scalar discipline (attack D) holds over
  C6.

---

## 7. Open questions for the architecture team (decisions this gate
defers, none blocking the contract)

1. **S3 sequencing:** the open-contradictions signal is `NOT_DERIVABLE`
   until the contradiction machinery lands (agent-runtime scope). Should
   C6 ship with S3 as a permanent `NOT_DERIVABLE` slot, or should C6's
   implementation be sequenced AFTER the contradiction machinery so S3 is
   real on day one? This gate ships the slot (honest partial picture now
   over a complete picture later); confirm.
2. **The C5 priority-history advisory:** §4.3 makes the "Director has
   held trajectory X for N rounds" signal optional. Confirm whether it
   earns its place in the convergence picture or is dropped.
3. **Obligation-coverage granularity:** S1 reports per-program +
   rollup. Should it also break down per ladder target (SUPPORTED/ROBUST/
   REPLICATED) so the human sees WHICH rung's obligations are outstanding?
   The derivation supports it; the question is surface area.
4. **Mutation-depth threshold advisory:** S4 reports depth as a fact.
   Should C6 also emit an advisory marker when depth exceeds a versioned
   threshold (e.g. "mutation depth > N — consider convergence review")?
   Advisory only, never a gate input — but it edges toward a recommendation,
   so the team should decide whether a threshold marker is in scope or
   whether the raw fact is enough.
5. **Digest version bump policy:** C6 bumps `RECONCILE_DIGEST_VERSION`
   4 → 5. Confirm the digest's downstream consumers (the Director's
   digest readers, any pinned version fixtures) are updated in the same
   implementation phase, so the bump is atomic. **Enumerated by the
   independent review (2026-08-20):** 6 hardcoded `digest_version == "4"`
   pins in 4 test files (`test_provider_orchestration.py:1874`,
   `test_q04_gate_replay.py:338`, `test_q04_review_candidates.py:528`,
   `test_q05_evidence_ladder.py:1050/1100/1122`) + 1 symbolic pin
   (`test_q05_persistence.py:836` == `DIGEST_VERSION`, auto-follows).

---

## 8. Authority boundary (ratifiable text, pending approval)

- **CAN** derive the five convergence signals + the diagnostic fold as a
  read-only, versioned, content-hashed section of `reconcile_digest()` —
  a picture, never a verdict.
- **CAN** emit `NOT_DERIVABLE` for signals whose source facts are absent,
  naming the missing source — honest partial picture, never a fill-in.
- **CAN** read C4's derived F-C facts and (optionally) C5's priority
  history as advisory inputs — never re-implementing their counters.
- **CANNOT** act: no gate input, no ordering input, no eligibility/ladder/
  budget/dispatch consumption, no intent, no trigger, no observe→act
  consumption.
- **CANNOT** declare convergence, name a winner, or replace the human
  convergence decision — convergence is human-gated (HR-08).
- **CANNOT** persist mutable state or introduce a scalar/composite — the
  section is derived on call, hashed into the digest, and fact-shaped.

---

*End of C6 design gate. Status: DESIGN — awaiting blueprint ratification
and operator approval before any implementation phase. No file in `src/`,
`tests/`, or `docs/idr/` is touched by this document.*
