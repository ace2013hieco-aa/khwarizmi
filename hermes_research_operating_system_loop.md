# Hermes — Research Operating System: the Emergent Loop (Conceptual Roadmap)

**Date:** 2026-08-15 · **Status:** conceptual roadmap ONLY — nothing here is
implemented by this document. Every link below is labeled from direct
inspection of the code at HEAD `dc84673`: **EXISTS** (implemented and tested),
**PLANNED** (documented contract/IDR, not materialized), or **MISSING**
(no design). This note ties together links that already exist; it does not
invent missing ones with speculative architecture.

## 1. The loop

```
ResearchProgram
  ↓  (1) program → task projection
Task graph
  ↓  (2) eligibility + dispatch
Execution
  ↓  (3) acceptance writes artifacts
Evidence
  ↓  (4) ladder climb / falsification
SUPPORTED…REPLICATED / REFUTED
  ↓  (5) "why did it fail?"   Q-05
Failure classification
  ↓  (6) "what else does that affect?"   Q-04
Blast radius / re-review candidates
  ↓  (7) proposal lifecycle → ratified decisions
ActionEvaluation
  ↓  (8) "what should we investigate next?"   Q-02
Epistemic ordering
  ↓  (9) dispatch order
Controller
  ↓ (10) task transitions / recovery / satisfaction links
Task graph again
```

## 2. Link-by-link status (verified at HEAD `dc84673`)

| # | Link | Status | Where |
|---|---|---|---|
| 1 | ResearchProgram → task graph | **EXISTS** | `research/task_plan.py` (ResearchTaskPlan program → task projection); `INSERT_TASK`/`ADMIT_TASK` through the gateway with `research_program:<id>` provenance refs admission-checked (V6-FINAL-02) |
| 2 | Task graph → execution | **EXISTS** | `Controller._discover_eligible` (deps SUCCEEDED + status filter) → claim → dispatch by kind (EXTRACT / HUMAN_GATE / GATE / AGENT_TASK) |
| 3 | Execution → evidence | **EXISTS** | EXTRACT acceptance writes artifacts (`accept_extraction_output`); step-6 `record_source_outcome` writes `source_result`/`source_payload` artifacts with the two-hop `_source_artifact_resolves` resolver |
| 4 | Evidence → SUPPORTED…/REFUTED | **EXISTS (partial)** | Evidence Ladder APPLY executor (`_apply_evidence_ladder_pass`, AC-1..5): obligation climbs SUPPORTED→ROBUST→REPLICATED from recorded satisfaction links; REFUTED applied from ratified classifications via the bare-classification driver (AC-2); `RefutedApplied` event. The full ladder-table record carrying the D3 `failure_classification:` ref is the documented contract, not yet materialized (PLANNED) |
| 5 | REFUTED → Q-05 "why?" | **EXISTS** | `failure_classification` artifacts recorded task-bound with real resolvers; `classifications_digest` + `Controller.classification_proposals` surface them to the Director; the REFUTED path consumes digest-valid classifications |
| 6 | Q-05 → Q-04 "what is affected?" | **EXISTS** | `failure_cone`/`blocked_roots`/`change_blast_radius` (read-only traversals over existing edges); `re_review_candidates` = artifact blast radius ∩ outstanding classifications; `SourceRetracted` seeds candidates |
| 7 | Q-04/Q-05 → ActionEvaluation | **EXISTS** | Director action loop (`propose_review_actions`) emits each candidate's permitted actions as `PROPOSE_CLASSIFICATION_ACTION` intents; APPROVED proposals are ratification facts consumed by existing authority paths (AC-4); ActionEvaluation is the shared evaluation vocabulary |
| 8 | ActionEvaluation → Q-02 "what next?" | **EXISTS** | `evaluation.py` EligibleTask mode; obligation facts from compiled programs + satisfaction links (`task_obligations.py`); versioned lexicographic policy (evaluator 1.2.0) |
| 9 | Q-02 → Controller | **EXISTS** | `_order_eligible` applies the policy to the already-eligible set at dispatch; every tick records `ordering_policy_version` |
| 10 | Controller → task graph again | **EXISTS** | dispatch transitions (PENDING→READY→RUNNING→SUCCEEDED/FAILED/RETRYING); NO_SIGNAL recovery requeues; satisfaction links recorded on completion; HUMAN_GATE parks and stops the wave until the operator decides |

## 3. Human-in-the-loop surfaces (EXISTS)

The loop is not fully automatic and is not meant to be: the Director sees the
Q-05 digest (advisory), the Q-04 re-review candidates, and the Q-02 ranking;
classification-action proposals require the existing approval gate
(PENDING_HUMAN_APPROVAL → ratified decision via `record_operator_decision`);
HUMAN_GATE tasks stop the wave. The epistemic stages propose and inform; the
operator and the Controller's deterministic policy decide and execute. No
stage silently acquires authority over truth, evidence, gates, budgets, task
creation, scope, or execution.

## 4. Planned (documented, not implemented — do NOT build now)

- Full REFUTED ladder record with the D3 `failure_classification:` dereference
  contract (the current path is the bare-classification driver + APPLY).
- Q-09 ScopeBrief field-diff + MECE diagnostic (NOT STARTED — next roadmap
  item after Q-05/Q-02 closure).
- Q-04 artifact-level `conflicts_with` / `introduces_risk` edges (DEFERRED to
  the provenance-lineage phase).
- Director-set priority override mechanism (DEFERRED — the precedence slot is
  pinned in IDR-038 §11; no mechanism exists).
- Budget authority (does not exist; the per-tick call cap is the resource
  floor — do not invent one here).

## 5. Missing (no design — intentionally out of scope)

- Q-07 Zwicky ideation (EXPERIMENTAL disposition, not started).
- CV-01 adversary convergence diagnostics (EXPERIMENTAL, not started).
- TRIZ subsystem (DEFERRED — abstract contradiction pattern only, as a prompt
  technique folded into Q-05's IMPLEMENTATION_FAILURE path).
- Obsidian integration (DEFERRED) and any diagram-authority/runtime
  dependency (REJECTED — diagrams remain projections).
- 4S architecture layer (REJECTED as a persisted layer; design lens only).

## 6. What the loop is NOT

- No second scheduler: the Controller is the ONE execution authority; Q-02
  only orders the already-eligible set.
- No automatic hypothesis generation, no automatic pivoting: every
  next-action proposal flows through the proposal lifecycle and the existing
  gateway authorities.
- No automatic loop driver: the loop is emergent from the existing
  components; no orchestrator is proposed or planned.

## 7. Source-of-truth pointers

- Q-05: `src/hermes/research/failure_classification.py`,
  `src/hermes/persistence/failure_classifications.py`, IDR-036/037.
- Q-04: `src/hermes/core/graph.py` (failure_cone / blast radius),
  `src/hermes/research/controller.py`, IDR-039/040.
- Q-02: `src/hermes/research/evaluation.py` (EligibleTask mode),
  `src/hermes/research/task_obligations.py`, IDR-038.
- Evidence Ladder: `src/hermes/research/evidence_ladder.py`,
  `src/hermes/research/evidence_transitions.py`, IDR-040/041.
- Controller: `src/hermes/research/controller.py`, IDR-029.
- Full current-state verification: `hermes_q05_q02_current_state_review.md`.
