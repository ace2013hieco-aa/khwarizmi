# HERMES Q-02 — EPISTEMIC ORDERING AT TASK ELIGIBILITY: REVISED DESIGN (MODEL B)

**Status:** DESIGN (post-adversarial remediation, 2026-08-15) — no
implementation, no scheduler modification, no code. Replaces the previous
gate document, which mixed two authority models (§2). This revision chooses
**Model B** explicitly and resolves every ownership question the adversarial
review raised.
**Inputs:** the surviving-ideas framework §D.2 (Q-02 — ADOPT NARROWLY), the
repo reconciliation, `hermes_research_architecture_v6.md`,
`src/hermes/research/evaluation.py` (ActionEvaluation),
`src/hermes/research/controller.py` (IDR-029), `docs/idr/IDR-029.md`,
IDR-036/IDR-037 (Q-05), and the adversarial finding this document answers.

---

## 1. Repository reconciliation (verified live, 2026-08-15)

| Framework claim | Live repository fact | Verdict |
|---|---|---|
| A/C: no epistemic-value signal feeds task prioritization | `ActionEvaluation` IS a deterministic epistemic comparison (dimensions: evidence_gap_closure, contradiction_reduction, rival_discrimination, replication_value, frontier_value, coverage; lexicographic policy; cost tiers; basis_refs) — but it ranks CANDIDATE ACTIONS for the Director. `Controller._discover_eligible` (the scheduler's discovery) is dependency-gated and `ORDER BY t.created_at, t.task_id`. No `roi`/`information_gain`/`expected_value` term exists anywhere in `src`. | PARTIALLY VERIFIED — signal exists for actions, absent for task eligibility |
| B/D: a Scheduler exists and owns prioritization | No standalone scheduler. v6 defines the scheduler as the controller's internal admission/dispatch function; `ADMIT_TASK` is scheduler-internal, never LLM-proposable. Implemented as the IDR-029 `Controller`. | MISCHARACTERIZED + ABSENT |
| E: scalar `roi_score = f(...)` | **Rejected by ratified architecture**: "No scalar score, no weighted utility… there is nothing to maximize, so there is nothing to Goodhart" (evaluation.py header, Part 1 verdict). | REJECTED |
| G: may influence ranking only | Consistent with the controller posture (IDR-029: "without creating a scheduler, a second authority…"). | VERIFIED (constraint) |
| H: ephemeral, no new artifact class | `CandidateRanking` is a hashed, versioned, in-memory advisory result — the pattern. | VERIFIED (constraint) |
| I/N: information-gain provenance; removal leaves dispatch functional | `basis_refs` + version triple precedent exists; the re-based removal test is §13.8. | PARTIALLY VERIFIED |

**Verified gap:** the controller's discovery pass orders eligible tasks by
`created_at` only — no deterministic epistemic ordering at task-eligibility
time, and no information-gain provenance discipline for one.

---

## 2. The previous design's defect (adversarial finding)

The prior gate described Q-02 as "an advisory, versioned, deterministic
ordering … consumed by the Director/reconcile loop as input, never as an
override" (Model A) while simultaneously naming **the controller's discovery
pass as the consumer** and making the ordering an input to dispatch (Model B).
It also left the information-gain dimension's source open (LLM proposal vs
deterministic proxy). A design that is "advisory" and also "an input to the
scheduler" is not one coherent model. This revision resolves it.

---

## 3. DECISION — Model B: versioned deterministic controller policy

**Q-02 is NOT merely advisory. It supplies the controller's deterministic
epistemic ordering policy for the already-eligible READY set.**

Why B over A: under Model A the Director would receive advice it has **no
mechanism to act on** — there is no ratified Director-priority field and the
controller dispatch is created_at-ordered, so "advisory ordering" would order
nothing and change nothing. Model B delivers the actual epistemic ordering the
framework asks for while remaining fully deterministic, gate-enforcing, and
versioned — the exact shape v6 already requires of scheduler decisions
("scheduler decisions in deterministic control flow").

What B is NOT:
- NOT a new scheduler / second authority. The scheduler remains the
  controller's internal admission/dispatch; Q-02 changes its ORDERING RULE,
  nothing else.
- NOT advisory metadata. The ordering policy is **versioned deterministic
  control logic** (`evaluation.py` pure function + the controller's
  application of it at dispatch), reproducible and audit-bound.
- NOT an override of anything. The policy orders WITHIN the already-eligible
  set (dependencies SUCCEEDED, gates passed, budget respected). The
  controller still MUST NOT: admit ineligible tasks, override budgets, gates,
  or dependencies, accept LLM instructions as execution authority.

The controller's existing determinism is preserved and enriched: dispatch
order becomes eligibility → epistemic ordering policy → `created_at`/`task_id`
tie-break (§11).

---

## 4. Exact authority owner

- **Who decides task dispatch order?** The **Controller** (IDR-029), executing
  its ratified control policy.
- **Does Q-02 influence that decision?** **Yes** — it supplies the ordering
  policy the controller applies within the eligible set.
- **Is that influence deterministic?** **Yes** — a pure, versioned function
  over the eligible set + deterministic obligation facts + cost.
- **Where is that deterministic policy defined?** In `evaluation.py` (the
  ActionEvaluation core) as a new **EligibleTask mode** (§5), consumed by
  `Controller._dispatch_pass` via `_discover_eligible`'s output ordering
  (§6). The policy version is bound to every dispatch (§10).
- **Can an LLM-supplied estimate directly affect dispatch?** **No.** v1 uses
  deterministic derived proxies only (§7, option C). Any future heuristic is
  quarantined at the Director-visible advisory surface (§8) and can never
  reach controller policy.

---

## 5. ActionEvaluation extension — EligibleTask mode (preferred architecture)

No new ROI component. The smallest architecture is an extension of the
existing ActionEvaluation core:

    ActionEvaluation
        ├── CandidateAction mode   (existing — Director-visible advice)
        └── EligibleTask mode      (new — controller dispatch policy)

The EligibleTask mode reuses, unmodified: `DimensionLevel`, `CostTier`, the
lexicographic ordering policy shape, the version triple
(evaluator/policy/schema), `basis_refs` provenance, and the hashed/versioned
result pattern. It adds one pure function (e.g. `evaluate_eligible_tasks`)
over a new frozen input (`EligibleTask`: task_ref, template, cost_class,
obligation facts, dimensions, basis_refs) and a frozen result
(`EligibleTaskRanking`) with the same non-scalar guarantees: multidimensional
comparison table, documented lexicographic policy, no score, no weights.

Deliberately NOT created: `ROIScheduler`, `EpistemicROIModule`,
`TaskROIArtifact`, `ROIState`, `ROIEvent` — the repository proves the
comparison core already exists and the controller already exists.

## 6. Task-ordering input model

Input (all deterministic): the already-eligible READY/PENDING/RETRYING set
from `_discover_eligible` (dependency gate unchanged) + each task's
`cost_class` + the project's current program obligation facts (derived at
compile: evidence requirements, rival status, replication requirements,
frontier/coverage obligations) + the policy version triple.

Output: an ordered task list bound to the policy version, applied by the
controller at dispatch. The ordering is computed at discovery time, never
persisted, and re-derivable on demand (the `CandidateRanking` pattern).

## 7. Deterministic information-value model (option C — preferred for v1)

Every dimension is computed from existing obligations by deterministic code.
An explicit, versioned mapping (the policy's input contract):

| Dimension | Deterministic source of fact | Basis ref |
|---|---|---|
| evidence_gap_closure | unresolved program evidence requirements reachable from the task's graph position | `research_program:<id>:evidence_requirement:<i>` |
| contradiction_reduction | declared contradictions in the program state | program contradiction refs |
| rival_discrimination | `RivalStatus.UNRESOLVED` rivals (compiled program) | `research_program:<id>:rival:<R>` |
| replication_value | replication requirements outstanding | program replication refs |
| frontier_value / coverage | frontier/coverage gap obligations | program obligation refs |
| cost tiers | task `cost_class` (LOW/MEDIUM/HIGH/UNKNOWN) | `task:<id>:cost_class` |

**A dimension that cannot be deterministically derived is `NONE` (AC-08:
unknown never treated as a value) — never an LLM guess, never a heuristic
scalar.** The policy therefore cannot Goodhart: there is no number to game.

**Information gain is not truth (§17 of the review):** every dimension is an
expected-utility-about-learning label ("value of running this experiment"),
never a belief about correctness ("its hypothesis is true"). The two are
separate surfaces; no truth claim exists anywhere in the ordering.

---

## 8. Model boundary / LLM quarantine

- **v1 policy inputs: deterministic only (option C).** No LLM-supplied estimate
  enters the ordering computation. The policy's dimension facts come from the
  compiled program, task state, and cost fields — all code-derived.
- **LLM channel (option B):** an LLM may PROPOSE informational metadata
  (labels, candidate basis refs, qualitative notes) for the **Director-visible
  advisory view only**. That channel is quarantined: it never reaches the
  controller policy, never affects dispatch order, and is versioned + labeled
  if surfaced.
- The forbidden chain is structurally impossible in v1:

      LLM → "high ROI" → hidden scheduler → silent execution priority

  because the only path from input to dispatch order is the deterministic
  policy function (§5–§7), which takes no LLM input.

---

## 9. Provenance

- Every dimension fact cites its basis (`basis_refs`), per AC-07.
- The ordering result carries the version triple
  (`evaluator_version`, `policy_version`, `schema_version`) and a
  content-derived `ranking_id` — replay with identical inputs yields an
  identical result (AC-01/AC-12).
- Every dispatch records the applied `ordering_policy_version` (on the
  `TickResult`/dispatch log), so any execution can be audited against the
  exact policy that ordered it.
- v1 has no heuristic estimator (option C); when a labeled heuristic is ever
  admitted to the advisory surface, it carries estimator identity + version +
  basis refs — never a naked information-gain number.

---

## 10. Versioning

- The ordering is reproducibility-sensitive (it affects actual execution
  order), so the policy is a **versioned artifact**: changing any part of the
  dimension→fact mapping, the dimension order, or the tie-break is a NEW
  `policy_version` (and a new derived ordering).
- Contract: same eligible set + same version triple + same input facts ⇒
  **byte-identical dispatch order**.
- Historical task executions are NEVER silently reinterpreted: the dispatch
  log binds each execution to its `ordering_policy_version`; a policy change
  affects only future dispatches.

---

## 11. Director vs Controller responsibility

| Role | May | May not |
|---|---|---|
| **Director** | inspect advisory rankings; review epistemic tradeoffs; propose research actions; set human priorities (once a ratified priority mechanism exists) | dictate dispatch order outside the ratified policy |
| **Controller** | deterministically dispatch per the ratified policy; enforce dependencies/gates/budget; execute; recover | admit ineligible tasks; override gates/budgets; accept LLM instructions |
| **Q-02** | supply the deterministic ordering policy (pure, versioned) | become a Director replacement or hidden scheduler intelligence |

**Exact precedence (defined now, mechanism for priority deferred):**
eligibility (dependencies SUCCEEDED, gates passed, budget respected) →
**ratified Director-set priority** (if/when a ratified override mechanism
exists, it ranks above the epistemic policy) → epistemic ordering policy →
`created_at`, `task_id` deterministic tie-break.

---

## 12. Recovery implications

- The ordering is computed at discovery time and never persisted, so
  crash-recovery re-derives it deterministically from the same eligible set +
  the same policy version — recovery/requeue paths (`_recovery_pass`,
  `_requeue_recovered`) are unchanged.
- Dispatch remains idempotent: reordering the eligible set does not change
  what a task does when claimed, only when it is claimed.
- A policy-version mismatch at recovery is impossible by construction (the
  version is read from the same code the dispatch used).

---

## 13. Acceptance tests (replace the weak "low ROI must not beat a
dependency-blocked task" test — that task is not eligible, so the assertion
was vacuous)

1. **Eligible-vs-eligible.** Task A and Task B are BOTH eligible
   (dependencies SUCCEEDED, no gate/budget block). The deterministic
   epistemic policy produces the declared order (A before B or vice versa,
   per the policy's dimension facts).
2. **Dependency boundary.** Task A is high-value but dependency-blocked; Task
   B is eligible. A cannot be executed because of Q-02 — the dependency gate
   runs first, unchanged, and the ordering never admits.
3. **Budget boundary.** Task A is high-value but budget-blocked; Task B is
   eligible. Q-02 cannot override the budget — the ordering applies only
   within the admitted set.
4. **Gate boundary.** Task A is high-value but awaiting a gate; Task B is
   eligible. Q-02 cannot override the gate — gated tasks are excluded before
   ordering (the ActionEvaluation EXCLUDED_GATE precedent).
5. **Director priority boundary.** A Director-set priority conflicts with the
   advisory epistemic ordering. Precedence: ratified Director priority >
   epistemic policy > created_at/task_id tie-break (§11). (The override
   mechanism is deferred; the precedence is asserted at design level.)
6. **Determinism.** Same eligible set + same policy/version/input facts ⇒
   byte-identical ordering.
7. **Information provenance.** Every non-deterministic/heuristic input carries
   estimator identity + estimator version + basis_refs. v1 has none (option
   C) — the contract is asserted by construction, and the advisory surface's
   labeling contract is tested when a heuristic is present.
8. **Removal.** Disable the Q-02 ordering input entirely. The controller
   remains functional under the baseline deterministic behavior
   (created_at/task_id order, dependency-gated) — no dead code, no behavior
   change (the framework's N, re-based).
9. **Tie behavior.** Equal epistemic ordering uses an explicit deterministic
   tie-breaker (created_at, then task_id) — never hash(random), process
   order, dictionary iteration, or wall-clock time.

---

## 14. Rejected alternatives

- **The framework's scalar `roi_score = f(...)`** — rejected by the ratified
  ActionEvaluation verdict (no scalar, no weighted utility); a scalar would
  make "ROI alone" the sole-justification attack.
- **A new Scheduler / `ROIScheduler` / `EpistemicROIModule`** — the scheduler
  is the controller's internal function; a new component would be a second
  authority.
- **`TaskROIArtifact` / `ROIState` / `ROIEvent`** — the ordering is ephemeral
  and re-derivable; persistence would be a new artifact class, forbidden.
- **Model A (purely advisory)** — coherent but orders nothing: the Director
  has no ratified priority mechanism to act on the advice, so dispatch stays
  created_at and Q-02 has no effect on execution order.
- **LLM-computed dispatch / LLM-proposed `ADMIT_TASK`** — forbidden by v6
  (scheduler decisions deterministic; `ADMIT_TASK` never LLM-proposable).
- **Stored priority field on tasks** — a new mutation surface and
  budget-adjacent authority; the ordering is computed at eligibility time.
- **Heuristic scalar information-gain in v1** — Goodhart-able; option C
  (deterministic derived proxies) is preferred by the review and sufficient.

---

## 15. Explicit non-goals

- NOT optimizing execution priority via heuristics or LLM estimates.
- NOT a new artifact class, event, intent, or table.
- NOT touching budgets, gates, dependencies, or task status.
- NOT reinterpreting historical executions (version-bound dispatch).
- NOT a Director replacement or hidden scheduler intelligence.
- NOT Q-09 (MECE), Q-04 (dependency/failure graph), Q-07 (Zwicky), or CV-01
  — those remain unstarted.
- NOT implemented in this task. This document is the design.

---

## 16. Implementation phase (sequenced)

Implementation begins only after Q-05's independent review has run and
closed. Then, in order:

1. `evaluation.py` EligibleTask mode (pure function + frozen dataclasses +
   version triple) + fixtures (the §13 suite, tests 1/6/7/9 at the pure
   level).
2. Controller consumption: `_discover_eligible`'s output ordered by the
   policy; `TickResult`/dispatch log records `ordering_policy_version`;
   dependency gate untouched (tests 2/3/4/8 at the controller level).
3. Integration fixtures (test 5 precedence assertion) + full-suite +
   pyright + structural comparison (no new write path, no new authority).
4. Independent review before ratification.

### 16.1 Implementation record (2026-08-15)

Q-05 closed (`612ea5d`) → the sequencing condition was met. Implemented:

1. `evaluation.py` EligibleTask mode — `EligibleTask` / `EligibleTaskEvaluation`
   / `TaskRankingDiagnostic` / `EligibleTaskRanking` frozen dataclasses, the
   version triple (`TASK_ORDERING_SCHEMA_VERSION="1"`,
   `DEFAULT_TASK_EVALUATOR_VERSION="1.0.0"`,
   `DEFAULT_TASK_POLICY_VERSION="task-eval-2026.1"`), `evaluate_eligible_tasks`
   (pure, hashed, content-derived `task_ord_*` identity), the documented
   `TASK_ORDERING_POLICY` (dimensions → cost LOW-first/UNKNOWN-last →
   created_at → task_ref), and `summarize_task_ranking`. Reuses the shared
   `DimensionLevel`/`CostTier`/`DIMENSION_ORDER`/`_DIM_LEVEL_ORDER`/
   `_COST_ORDER` constants — one policy source (§18.6); the module stays
   pure (`test_j_evaluator_has_no_dispatch_surface` still green).
2. Controller consumption — `_dispatch_pass` now orders `_discover_eligible`'s
   output via `_order_eligible`/`_eligible_task_input`; `TickResult` records
   `ordering_policy_version` (§9); `enable_epistemic_ordering=False` is the
   §13.8 removal switch. The derivation reads ONLY stored `cost_class`
   (untiered → UNKNOWN, AC-08) and the gateway-validated `research_program:`
   provenance refs as basis (V6-FINAL-02); v1 epistemic dimensions are NONE
   by design (§18.4 degenerate-to-baseline). Dependency gate, gates, and the
   per-tick call cap are untouched.
3. Fixtures — 19 pure (§13.1/6/7/9 + degeneracy/versioning) +
   17 controller (§13.2/3/4/5/8 + derivation + structural). Full suite
   **1033 passed**, pyright **0 errors**.
4. Independent review before ratification: still standing.

### 16.2 Enrichment record — evaluator v1.1 (obligation-fact derivation)

The v1 degeneracy (all dimensions NONE without a task→program link) is now
lifted where the schema can support it. `evaluation.py` stays pure and
ladder-vocabulary-free (AC-05); the derivation lives in the new pure module
`src/hermes/research/task_obligations.py` (imports only the shared
`DimensionLevel` from evaluation — one policy source, §18.6), and the
controller consumes it per tick:

- **Source of fact** (Q-02 §7 option C): for each task, the compiled programs
  named in its gateway-validated `research_program:` provenance refs. Counts
  are summed across linked programs.
- **evidence_gap_closure** — evidence requirements whose `required_artifacts`
  are not all present in the project's artifact inventory (unresolved).
- **rival_discrimination** — `UNRESOLVED` rival hypotheses + discrimination
  requirements (their satisfaction is not recorded in the current schema, so
  they count as outstanding).
- **replication_value** — evidence requirements targeting the REPLICATED
  rung whose artifacts are not all present.
- **contradiction_reduction / frontier_value / coverage** — no stored source
  in the current schema → always NONE (documented §18.4 degeneracy).
- **Ratified count→level policy** (versioned with the evaluator): total 0 →
  NONE; all satisfied → LOW; exactly 1 outstanding → MEDIUM; ≥2 → HIGH.
  Every non-NONE fact cites its `research_program:<id>:...` basis_ref.
- **Fail-closed**: malformed program rows/entries are skipped (never a fact);
  a missing or foreign program ref resolves to nothing → degenerate baseline.
  The derivation is read-only (project-scoped SELECTs only; no new table,
  event, authority, or write path).
- `DEFAULT_TASK_EVALUATOR_VERSION` → **1.1.0** (identity changes with the
  derivation; policy version `task-eval-2026.1` unchanged — the lexicographic
  ordering key did not change).
- Fixtures: 11 pure derivation + 5 controller enrichment + 2 module-purity.
  Full suite **1052 passed**, pyright **0 errors**.
- The derivation happens only when a task's provenance actually links a
  program; unlinked tasks (all real v1 EXTRACT tasks) still degenerate to the
  created_at/cost baseline — the §13.8 removal switch is unchanged.

### 16.3 Enrichment record II — evaluator v1.2 (per-requirement satisfaction links)

The v1.1 class-level approximation (satisfied = every required artifact class
exists somewhere in the project) is replaced by a stored per-requirement
link, so fulfillment is per hypothesis:

- **Migration 8→9** adds `program_requirement_satisfactions` (append-only,
  `UNIQUE(program_id, requirement_ref, artifact_id)`, content-derived
  identity, no UPDATE/DELETE path, no event type, no free-form metadata).
- **Write path** (`src/hermes/persistence/program_obligations.py`): the
  link is validated at admission (program governed by the project;
  requirement dereferences to a real evidence requirement of that program;
  artifact exists in the project; artifact class is one the requirement
  requires). Idempotent; the row IS the audit.
- **Derivation**: `program_obligation_dimensions` now takes the per-
  requirement satisfaction facts (`{program_id: {requirement_ref:
  frozenset(artifact_types)}}`); a requirement is fulfilled iff every class
  in its `required_artifacts` has been linked to it. Nothing stored is
  derived — the derivation recomputes from the rows + artifact types.
- `DEFAULT_TASK_EVALUATOR_VERSION` → **1.2.0** (identity changes with the
  fulfillment model; policy version `task-eval-2026.1` unchanged).
- **Recovery-safety proof**: a controller crashes mid-dispatch with the
  enriched ordering active; the re-derived eligible order and recorded
  policy version are deterministic across the crash, and recovery requeue
  (IDR-029 Decision 4) never re-enters the eligible set.
- Fixtures: 14 satisfaction-link write-path/derivation/tamper + recovery
  proof. Full suite **1066 passed** at `3fb91c6`, pyright **0 errors**.

### 16.4 Adversarial audit II — F6/F7/F8 (fresh-eyes, post-satisfaction-link)

A fresh-eyes review of the v1.2 package at `3fb91c6` re-verified the version
triple (evaluator 1.2.0 in the content identity), the count→level policy via
the real write path, the provenance fail-closed paths, the version-bound
dispatch record, and the new satisfaction surface (live probes, not just
fixtures):

- **F8 (MEDIUM)** — the satisfaction write path dereferenced program rows
  through the shared parser's bare `json.loads`: a corrupt program row
  crashed `record()` with a raw `JSONDecodeError`. Fixed at `e838a9c`: the
  link is refused with a clean `RequirementSatisfactionError`, nothing is
  written. Same corruption class as F5, on the write side.
- **F6 (LOW)** — `record()` accepted and returned a free-form `reason` that
  was never persisted. Removed: the row itself is the audit.
- **F7 (LOW)** — stale "v1.1" references in the module docstrings and
  IDR-038 corrected to 1.2.0.
- All prior probes re-run and closed (version binding, D8 discrimination-ref
  refusal, cross-project and wrong-class tamper refusals, idempotency,
  corrupt-program-plus-satisfaction dispatch survives with a note).

**Verdict: PASSED after remediation.** Full suite **1068 passed**, pyright
**0 errors** at the current HEAD.

---

## 17. Hostile self-review of THIS revision

> **Does Q-02 decide which task runs next?** The CONTROLLER decides, per the
> ratified policy; Q-02 supplies the policy. Dispatch remains deterministic
> control flow (v6 line 32), not advisory metadata and not a second
> authority.
>
> **Could an LLM silently influence execution order?** No — v1 takes no LLM
> input into the policy (option C); the only dispatch path is the pure
> policy function. The LLM channel is Director-visible advisory only.
>
> **Could it reintroduce a scalar / Goodhart target?** No — comparison table +
> lexicographic policy; undeterminable dimensions are NONE, never a number.
>
> **Could it skip a gated/budget-blocked task "by ROI alone"?** No — the
> ordering applies only to the already-eligible set; gates/budgets/
> dependencies run first, untouched (tests 2–4).
>
> **Could it change budgets, Director priorities, or history?** No budget
> surface, no priority field, version-bound dispatch, no reinterpretation.
>
> **Could it create an artifact/event/intent?** No — ephemeral, re-derivable,
> the `CandidateRanking` pattern, zero new persistence.

---

**DESIGN READY FOR IMPLEMENTATION** — Model B chosen explicitly (versioned
deterministic controller policy via the ActionEvaluation EligibleTask mode,
option-C deterministic proxies, LLM quarantined to the advisory surface),
every ownership question answered in §4, precedence and versioning defined,
the nine acceptance tests specified, and no implementation started. The
standing sequencing constraint stands: Q-02 implementation begins only after
the Q-05 independent review has run and closed.

---

## 18. Hostile design-gate re-run (post-closure, 2026-08-15) — the six areas

Re-run against the verified controller/`evaluation.py` facts. Each area:
the hostile question, the verified fact, and the resolution.

### 18.1 Precedence

> Hostile: is "eligibility → epistemic policy → created_at/task_id" actually
> implementable, or does the ordering slip before a gate?

Verified: `_dispatch_pass` iterates `_discover_eligible()` (dependency-gated
`WHERE NOT EXISTS` on non-SUCCEEDED deps) in order and CLAIMS each task
(READY→RUNNING); the per-tick call cap (`calls >= max_calls_per_tick`) breaks
the loop, so **ordering decides which eligible task consumes the call
budget** — the epistemic ordering has real dispatch effect exactly there, and
only there. The dependency gate runs first, unchanged. Gated/human-gate
kinds are classified and PARKED after the loop (`_park_human_gate`) — a
gated task's fate is decided by classification, never by position, so Q-02
cannot override a gate. **Resolution:** precedence holds in the current
controller; the ordering plugs into `_discover_eligible`'s output order with
the existing dependency gate untouched.

### 18.2 Director priority

> Hostile: the design's "ratified Director priority > epistemic policy" cites
> a mechanism that does not exist — is that a design gap or a fiction?

Verified: no Director-priority field or mechanism exists in the controller;
the Director's only levers are advisory (ActionEvaluation) and intent
proposals (`apply_intent`). **Resolution:** the precedence line is a
**documented contract, not an implementation**: v1 has no priority override,
so the effective precedence is eligibility → epistemic policy →
created_at/task_id. The contract states that IF a ratified override mechanism
is ever built, it ranks above the policy — and Q-02 itself must never
introduce a priority field (no new mutation surface, no budget-adjacent
authority). The LLM advisory channel (§8) is not a priority mechanism and
cannot reach the policy.

### 18.3 Recovery

> Hostile: ordering is computed at discovery and never persisted — after a
> crash, recovery requeues tasks and changes statuses, so the re-derived
> order is over a DIFFERENT set. Is the determinism claim broken?

Verified: recovery (`_recovery_pass`/`_requeue_recovered`) mutates task
statuses; the next tick's eligible set can legitimately differ. **Resolution:**
the determinism contract is per-set: *same eligible set + same version triple
+ same facts ⇒ same order*. A different set yields a different (correct)
order. Audit integrity is preserved because every dispatch records the
applied `ordering_policy_version`; the fence (`scheduler_lock` owner +
generation, checked inside write transactions) makes the controller
single-writer, so there is no TOCTOU between the ordering read (fenced
SELECT) and the claim (fenced write) within a tick. Ordering is advisory to
dispatch, never persisted state, so recovery cannot corrupt it.

### 18.4 Deterministic proxy inputs

> Hostile: the dimension→fact mapping names data that may not exist at
> dispatch time (task→program-obligation links). Does the policy collapse?

Verified: programs carry derived obligations (`evidence_requirements`,
`gate_requirements`, rival status) at compile; tasks in the current schema are
template-driven (extract/search/gate) with no program binding column. So for
many real tasks the mapping is not computable today. **Resolution:** the
designed failure mode is explicit — a task whose obligation facts cannot be
deterministically resolved gets ALL dimensions `NONE`, which degenerates the
ordering to the `created_at`/`task_id` tie-break: **exactly the removal
test's baseline**. Degenerate-to-baseline is the honest, designed behavior —
never an error, never a heuristic fill, never an LLM guess. The policy is
only as rich as the obligation data resolvable at dispatch time, and that is
stated as a feature (no Goodhart surface), not a gap.

### 18.5 Tie-breaking

> Hostile: is the final order TOTAL and deterministic? Same-created_at
> collisions; dict/set iteration; wall clock.

Verified: the ordering key is lexicographic over `DIMENSION_ORDER` levels
(each NONE<LOW<MEDIUM<HIGH), then cost (UNKNOWN last, AC-08), then
`created_at` (stored TEXT, deterministic), then `task_id` (PK, unique) — a
**total order**. `DIMENSION_ORDER` is a fixed tuple, not a set; no dict
iteration, no `hash(random)`, no wall clock enters the key. Two tasks created
in the same tick with identical dimensions/cost are broken by `task_id`.
**Resolution:** tie-break is total and deterministic; asserted by acceptance
test 9.

### 18.6 ActionEvaluation reuse

> Hostile: does "EligibleTask mode" actually reuse the core, or duplicate it?
> Can the advisory and dispatch surfaces drift apart?

Verified: `evaluation.py` imports only `programs.py`; nothing imports the
controller, and nothing imports `evaluation.py` from the controller today —
adding the EligibleTask mode creates a clean controller→evaluation edge, no
cycle. `DimensionLevel`, `CostTier`, `DIMENSION_ORDER`, the version triple,
and `basis_refs` are all shared constants. **Resolution — the reuse
contract:** the EligibleTask mode MUST import those shared definitions and
the lexicographic-policy construction from `evaluation.py`, never redefine
them; and **one policy definition serves both surfaces** — the dispatch
EligibleTask mode is the ratified control policy, and the Director-visible
CandidateAction mode consumes the SAME dimension vocabulary and versioning.
The two modes may differ in which facts they consume (actions vs tasks) but
cannot diverge on the policy itself, so the advisory and control surfaces
cannot drift. A structural test will assert the single-source policy and the
import direction (evaluation never imports the controller).

---

**DESIGN READY FOR IMPLEMENTATION** — reaffirmed after the hostile gate: all
six areas resolve against verified controller/evaluation facts (precedence
implementable under the call cap; Director-priority precedence is a
documented contract with no v1 mechanism; recovery determinism is per-set
with version-bound audit and a single-writer fence; degenerate-to-baseline is
the designed proxy fallback; the tie-break is total; the EligibleTask mode
reuses shared definitions with a single policy source and a cycle-free import
direction). No implementation in this task.

---

## 19. Post-implementation adversarial audit (2026-08-15, at `3494124`)

Fresh-eyes review of the COMMITTED implementation (not the docs' claims): the
EligibleTask mode, the `task_obligations.py` derivation, and the controller
consumption were re-read from source, then probed at real boundaries with the
full suite (1052 at that HEAD) and pyright clean.

### 19.1 Findings

**F5 — HIGH (fixed, `27f0504`): corrupt program rows crash dispatch.** The
derivation reads `research_programs` rows on every tick via the repository's
row parser, whose `_json_loads` is bare `json.loads`. A row with corrupt JSON
in any column raised `JSONDecodeError` through `_load_obligation_context` and
killed the WHOLE tick — the controller never read program rows before Q-02,
so this was a new crash surface. Proven with a live corrupt-row attack.
**Fix:** rows are parsed defensively; a corrupt row is skipped, recorded on
the controller's existing `_notes` channel, and the task degenerates to the
baseline ordering. Re-probe confirms the tick completes and the note fires.
Regression-locked in `TestEnrichedDerivation::test_corrupt_program_row_...`.

### 19.2 Probed and accepted (documented policy, not defects)

- **All-satisfied obligations → LOW floor (not NONE).** A program-linked task
  whose obligations are all satisfied outranks an unlinked task. This is the
  deliberate floor ("the task still belongs to a live program") — and it is
  bounded: it applies only to gateway-validated program links, and unlinked
  tasks still degenerate. Kept, documented in §16.2.
- **Class-level satisfaction approximation.** "Satisfied" = every required
  artifact CLASS exists somewhere in the project's artifact inventory; the
  schema records no per-requirement binding, so per-hypothesis fulfillment
  cannot be checked. Deterministic and code-derived; the approximation is
  part of the ratified v1.1 policy, and today's schema cannot even produce
  ladder-class artifacts, so all confirmatory requirements are honestly
  outstanding.
- **Type-violating dimension inputs fail loudly.** Passing a bare string
  where `DimensionLevel` is typed crashes with `AttributeError` at
  serialization — consistent with the CandidateAction surface's contract.
  Not silent, no new behavior.
- **String `required_artifacts` / malformed obligation entries** are skipped
  (never a fact, never a crash) — verified live.

### 19.3 Authority re-check (answered against the diff)

The derivation adds **zero** authority: project-scoped SELECTs only, inside
the existing single-writer tick; no new table/event/intent/scheduler/write
path; the ordering still never admits, never overrides gates/budget/deps, and
the §13.8 removal switch is unchanged. The version-bound dispatch record
(`TickResult.ordering_policy_version`) was verified through the enriched
path.

### 19.4 Audit verdict

**PASSED after remediation.** One finding (F5) was found, fixed, and
regression-locked; the examined policy choices are documented, bounded, and
deterministic. Full suite **1053 passed**, pyright **0 errors** at the audit
HEAD + fix. This audit was executed by the implementation agent at operator
instruction — it does not substitute for an external independent review, and
Q-02 remains unratified pending the formal IDR and operator closure.
