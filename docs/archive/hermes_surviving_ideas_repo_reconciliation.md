# HERMES — SURVIVING IDEAS REPO RECONCILIATION

**Agent:** Hermes Research architecture-design + implementation agent
**Date:** 2026-08-15
**Repo:** `D:/New folder/research-agent` @ `2d6d851` (branch `main`)
**Source:** the live repository, the ratified architecture (`hermes_research_architecture_v6.md`), and the ratified IDR archive (`docs/idr/`). Every claim below was verified against actual files — the framework's own provenance tags (`[MEMORY]`/`[SOURCE-DERIVED]`) confirm the adversarial-review agent had **no repository access** and asked for exactly this reconciliation (§B, §R of the framework).

---

## 0. Baseline facts (verified at HEAD)

| Fact | Verification |
|---|---|
| Test suite | `892 passed` (pytest, full run, 9.0s) |
| Typecheck | `uvx pyright src` → `0 errors, 0 warnings` (the CI-verified baseline; `tests/` is NOT pyright-clean by design) |
| Schema version | `SUPPORTED_VERSION = 8` (`persistence/migrations.py:19`) |
| Ratified baseline | v6 ratified for the approved slices (IDR-023); ResearchSourceProvider step 6 IMPLEMENTED, NOT RATIFIED-as-implemented (IDR-032/033/034) |
| Placeholder modules | `research/{evidence,gates,integrity_gates,provenance,reconcile,registration}.py`, all four `agents/*.py` |

---

## 1. Reconciliation method

For each framework claim: locate the actual file/schema/API/authority/phase, then classify.

```
VERIFIED            — the framework's claim matches the repository
PARTIALLY VERIFIED  — the component exists but the framework's claim about it is wrong or incomplete
STALE               — described a prior architecture version; superseded by current ratifications
REDUNDANT           — already solved by existing machinery; the framework's addition duplicates it
ABSENT              — the claimed component/state/record does not exist in code, schema, or ratified docs
MISCHARACTERIZED    — the claim names something real but describes it incorrectly
```

---

## 2. Q-05 reconciliation (the task at hand)

### 2.1 "The Evidence Ladder presumably has a falsification terminus" — **MISCHARACTERIZED + ABSENT**

- The ratified ladder (v6 §10.1) is:

  ```
  SPECULATIVE → PLAUSIBLE → SUPPORTED → ROBUST → REPLICATED
                      (terminal-ish: UNCERTAIN, REFUTED)
  ```

  The falsification terminus is **REFUTED**, not FALSIFIED. The word **FALSIFIED appears nowhere in the repository** — not in `src/`, not in the v3/v4/v6 architecture docs, not in the tests (grep over the whole tree: 0 source matches).
- The `any → REFUTED` transition (v6 §10.2) is **ratified design, not executable behavior**: `src/hermes/research/evidence.py` is a Phase 0 placeholder ("Evidence ladder and promotion rules (v3 §10) — deterministic validator. Phase 0: placeholder."). There is **no evidence table, no EvidenceRepository, no Evidence Validator** (confirmed independently by the Step-3 authority/evidence map, `docs/idr/hermes_v6_authority_evidence_map.md:149`: "Evidence Ladder has no code"). The README roadmap pins it to P2.
- **Consequence for Q-05:** there is no FALSIFIED/REFUTED *record* to extend. The framework's target ("existing falsification record + failure_class") has no existing carrier. The smallest honest implementation is a **pure, deterministic classification substrate** (the exact manual-proof-first pattern this repository used for CONTRA P7 — `claims.py` substrate first, persistence later in IDR-026/027/028) that consumes a falsification record shaped like the future REFUTED write path and emits a versioned, provenance-bearing classification + deterministic permitted-action set. It must NOT build the ladder (P2 roadmap), and must NOT invent a new state machine.

### 2.2 "ThesisEvidenceTable already links evidence to theses" — **PARTIALLY VERIFIED**

- The `thesis_evidence` table **exists** (migration 1→2) with verdicts `THESIS_SUPPORTED | THESIS_PARTIALLY_SUPPORTED | THESIS_CONTRADICTED | THESIS_INSUFFICIENT | THESIS_MIXED`, and the deterministic verdict mapping is ratified (v6 §9.1).
- But `src/hermes/research/thesis.py` states plainly: "the `thesis_evidence` table exists since migration 1 but **nothing reads it**". The only implemented piece is the pure `validate_thesis_evidence` AR-03 validator (round-2+ counter-search compliance) with an injected resolver. Thesis-mode is DESIGNED (P1/P2/P4 phases), not runtime.
- **The thesis table is a literature-evidence table, not a hypothesis-falsification record.** `THESIS_CONTRADICTED`/`THESIS_INSUFFICIENT` are *hypothesis-gate precondition inputs* (v6 §9.1) — never ladder rungs and never a falsification record. The framework's "store the classification on the falsification/ThesisEvidenceTable record" conflates the two.

### 2.3 Failure classes vs. Hermes concepts

| Framework class | Hermes-native concept | Verdict |
|---|---|---|
| HARD_AXIOM_VIOLATION | **No axiom concept exists anywhere** (grep: 0 hits in src, 0 in v6). Closest carriers: a hypothesis's declared `falsification_condition`, `methodology_constraints`, and the frozen ScopeBrief. | **RENAME → `DECLARED_CONSTRAINT_VIOLATION`**; citation target = a declared constraint, not an "axiom" |
| IMPLEMENTATION_FAILURE | §10.2 REFUTED causes: "failed BacktestResult / Replication / leakage Validation … a validity/leakage bug in the supporting pipeline"; `EXPLORATORY_DRIFT` (spec drift) is a concrete Hermes sub-case (§11.1) | VERIFIED; deterministic discriminator = cite the failed mechanism-level prediction, not the claim |
| ENVIRONMENT_MISMATCH | Regime is a first-class Hermes concept: the versioned `ICSS-v1` regime axis, `regime` in `CONTEXT_DIMENSIONS`/`DEREFERENCE_DIMENSIONS` (claims.py), regime-slice re-application for `SUPPORTED → ROBUST` (§10.2) | VERIFIED; citation = a declared regime ref |
| RESOURCE_CONSTRAINT | **No budget ledger exists** (deferred — `budget_check` is a documented no-op hook; `AR-02 stays DEFERRED` in IDR-030). `cost_class` on tasks is the only resource surface. No "park" state exists (FAILED/ABANDONED are terminal). | KEEP, scoped: the *class* is honest, but the consequence must be "no automatic action; Director re-evaluation proposal", never a park-state invention |
| FRAMING_ERROR | ScopeBrief is real and frozen/versioned (S16): `scope_briefs` table with `content_hash`, `supersedes_id`, frozen_at; amendments = new versions with supersession edges (§11.1). | VERIFIED; citation = `scope_brief_ref` + a specific field; consequence = route to scope revision authority only |
| (not proposed) | — | **ADD `UNKNOWN`**: the framework's own §12 admits a wrong forced classification is worse than an explicit unresolved result |

**Taxonomy decision:** exactly-one `failure_class` (primary) + optional validated `contributing_factors`; `UNKNOWN` is a first-class value; `MULTI_FACTOR` is *not* a class (it would hide the primary and break the deterministic action map — a multi-factor failure is a primary + contributors). See design §5.

### 2.4 Components the framework named as owners — actual status

| Component | Actual status | Verdict |
|---|---|---|
| Evidence Ladder | Placeholder; no table, no repo (P2 roadmap) | ABSENT (as code) |
| FALSIFIED state | Does not exist; ladder terminus is REFUTED | MISCHARACTERIZED / ABSENT |
| ThesisEvidenceTable | Table exists; nothing reads it; validator pure substrate | PARTIALLY VERIFIED |
| ResearchClaim / ResearchAssumption | IMPLEMENTED: `claims.py` substrate (IDR-025) + write path (`ClaimAssumptionRepository`, IDR-026/027) + EXTRACT pipeline (IDR-028). **Advisory substrate only — never evidence, never ladder-citable, never a gate input** (v6 §29.2) | VERIFIED (with the boundary intact) |
| ScopeBrief | Table exists (frozen/versioned/content-hashed); `scope_text_json` is **unstructured JSON with no closed schema, no validator, no gateway write path** (rows inserted directly in tests) | PARTIALLY VERIFIED |
| ResearchProgram | IMPLEMENTED: `programs.py` (validator + identity + obligations), `ResearchProgramRepository` (integrity), gateway `PROPOSE_RESEARCH_PROGRAM` (Director-only) | VERIFIED |
| Director | `agents/director.py` — Phase 0 placeh
| Director | `agents/director.py` — Phase 0 placeholder (P4) | ABSENT (as code) |
| Intent Gateway | IMPLEMENTED: `apply_intent` wired for `PROPOSE_RESEARCH_PROGRAM` / `INSERT_TASK` / `ADMIT_TASK`. **`EVIDENCE_TRANSITION`, `BRANCH`, `ABANDON`, etc. are declared but NOT_WIRED** | PARTIALLY VERIFIED |
| Task Graph | IMPLEMENTED: `tasks`/`task_dependencies` DAG, `graph.py` (readiness, cycle detection), admission only via INSERT_TASK; `task_plan.py` (program → tasks) | VERIFIED |
| Controller / Reconcile | Controller IMPLEMENTED (IDR-029): deterministic C-tier execution surface, fenced, single-writer. `reconcile.py` = Phase 0 placeholder | PARTIALLY VERIFIED |
| Provenance | `provenance_edges` table + 5 edge types (cites/derived_from/supersedes/used_as_input/justifies); **two-hop reachability already implemented** in the source slice (`_source_artifact_resolves`, `load_search_results`); `provenance.py` model = placeholder | PARTIALLY VERIFIED |
| Gates | `gates.py`/`integrity_gates.py` = placeholders; the three mandatory human gates exist as plan tasks in `task_plan.py` | PARTIALLY VERIFIED |
| Contradiction handling | `CONTRADICTION_DETECTED` event declared; `any → UNCERTAIN` ratified (§10.2); CONTRA claim/assumption substrate implemented; **no contradiction-resolution validator, no open_contradictions persistence** | PARTIALLY VERIFIED |
| Refuted registry | Ratified (§10.2: refuted hypotheses "remain first-class registry assets, structurally screened") — **no code** | ABSENT (as code) |

---

## 3. Q-02 Scheduler — verify only (do NOT implement)

- **There is no Scheduler module.** `ADMIT_TASK` is internal-only and "the scheduler that proposes it is P3-general-runtime, **deferred**" (`gateway.py` docstring). The reconcile loop (`reconcile.py`) is a placeholder.
- The closest existing component is `evaluation.py` (ActionEvaluation, IDR-019) — a **deterministic candidate-comparison library** producing an advisory `CandidateRanking` for the Director. It is explicitly NOT a scheduler and NOT a priority engine; it has no write path.
- The controller (`controller.py`) is an execution surface, not a scheduler: it claims READY work from the existing task graph under a `scheduler_lock`.
- **For future Q-02:** "the Scheduler" has no owner to extend. Any Q-02 must either (a) feed the Director's decision input (the ActionEvaluation precedent), or (b) wait for the reconcile loop's dispatch slice. Q-02 as "one ranking input to the existing scheduler" presumes a component that does not exist.

## 4. Q-09 ScopeBrief — verify only (do NOT implement)

- `scope_briefs` schema (migration 1→2): `brief_id, project_id, version, content_hash, supersedes_id, scope_text_json, rationale, created_at, frozen_at`; `UNIQUE (project_id, version)`; briefs are frozen/immutable/versioned — the S16 amendment pattern is real.
- `scope_text_json` is **free-form JSON with no closed schema and no validator** — the framework's Branch 2 (unstructured) is the current reality. There is no decomposition structure, no TOSCA-equivalent field set, no MECE check, and no gateway path that creates or revises briefs (SCOPING is not wired).
- **For future Q-09:** a completeness diagnostic has no owner today and the brief's content schema is unvalidated — Q-09's Phase 0 diff is now answerable: Branch 2 holds, but the *first* gap is a closed ScopeBrief schema, which is a bigger task than the framework assumed.

## 5. Q-04 graph/provenance — verify only (do NOT implement)

- `provenance_edges` (5 edge types, `UNIQUE(artifact_id, upstream_id, edge_type)`, `CHECK artifact_id != upstream_id`) + **reachability traversal is already implemented** in `source_outcomes.py`: `_source_artifact_resolves` walks 1-hop and 2-hop `derived_from` edges with project scoping, and `load_search_results` selects by edge reachability, not by stored task_id.
- **For future Q-04:** the "forward reachability" primitive already exists inside the source slice. Q-04 collapses toward "a general-purpose downstream-impact query service over `provenance_edges`" (probably a new `depends_on` edge type + a query), not "provenance doesn't exist". The framework's §R item 3 is answered: reverse traversal over existing edges is partially implemented, not absent.

## 6. Cross-cutting framework assumptions — corrected

1. **"FALSIFIED already exists as a terminus"** — wrong; the terminus is REFUTED and unimplemented. Q-01's verdict (states map onto the ladder "without residue") was built on a ladder that does not exist in code.
2. **"extend the Evidence Ladder; store classification on the existing falsification record"** — impossible today; the ladder and the record are absent. Q-05 must land as a pure classification substrate with a defined record shape for the future write path.
3. **"RETRACT_SOURCE cascade [MEMORY]"** — `SOURCE_RETRACTED` event is declared in the event catalog, but no retraction cascade exists in code (the source slice has no retraction path; §9.2 says retraction is human-initiated by construction).
4. **"DirectorDigest / HumanResumeDigest / AuditView [MEMORY]"** — none of these exist in code; the vault (`vault/projection.py`) anchors a v3 boundary. The framework's own §R item 4 remains open.
5. **"Axiom/constraint objects in the pre-registration spec hash"** — no axiom registry exists; the only declared-constraint carriers are program `methodology_constraints`, hypothesis `falsification_condition`, and the ScopeBrief. HARD_AXIOM_VIOLATION must be re-based on these.
6. **Scheduler/Controller/Task Graph naming** — Controller = the deterministic execution surface (exists); Scheduler = does not exist; Task Graph = exists (DAG); "Reconcile" = placeholder. The framework's Chain A "expose to Controller" is viable only in the sense that the future reconcile/controller consumption is deferred.

## 7. Reconciliation verdict summary

| Framework claim | Verdict |
|---|---|
| Q-05 is a real gap | **VERIFIED — but larger than framed**: the entire REFUTED/falsification terminus is unimplemented, and no falsification record exists to extend |
| Q-05 owner = Evidence Ladder FALSIFIED record | **MISCHARACTERIZED** (REFUTED, and no code) |
| ThesisEvidenceTable = falsification carrier | **MISCHARACTERIZED** (literature table; gate input; nothing reads it) |
| HARD_AXIOM_VIOLATION maps cleanly | **NO** — no axiom concept; rename/re-base required |
| ResearchClaim/ResearchAssumption exist | **VERIFIED** (advisory substrate + write path) |
| ScopeBrief exists (frozen/versioned) | **VERIFIED**; unstructured content — **no validator** |
| ResearchProgram exists | **VERIFIED** (full implementation) |
| Director exists as authority | **ABSENT as code** (placeholder); the *authorization path* exists via the gateway |
| Intent Gateway = single mutation path | **VERIFIED** (3 kinds wired; evidence intents NOT_WIRED) |
| Scheduler exists (Q-02 owner) | **ABSENT** |
| ScopeBrief decomposition (Q-09) | **ABSENT** (unstructured JSON) — Branch 2 of the framework holds |
| Provenance graph (Q-04 owner) | **PARTIALLY VERIFIED** — edges + two-hop reachability exist in the source slice |

## 8. What this means for Q-05

1. The design gate answer (framework §19) is **YES — Q-05 is a real, verified gap**, with a corrected premise: there is no FALSIFIED record; the classification substrate must define the record shape it consumes, exactly as `thesis.py`/`claims.py` define the shapes their future write paths will persist.
2. Q-05 must NOT touch `evidence.py` (ladder is a P2 roadmap deliverable), MUST NOT add tables/events/intents/gateway wiring (manual-proof-first rule, v6 §29.2 rule 7), and MUST NOT create any authority, state machine, or write path.
3. All five proposed classes survive in revised form (one renamed, one added, all re-based on Hermes-native citation targets).
