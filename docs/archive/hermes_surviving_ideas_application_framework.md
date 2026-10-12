# HERMES — SURVIVING IDEAS APPLICATION FRAMEWORK

**Prepared by:** the adversarial-review agent, per the meta-design task
**Date:** 2026-08-15
**Status:** proposed framework — not an implementation plan, not implementation prompts

## Provenance tag legend (used throughout)

- **[MEMORY]** — from prior conversations with Ace, retained in my memory, not re-verified against the current repo in this session.
- **[SOURCE-DERIVED]** — introduced by the meta-design task prompt itself (component names like `ResearchProgram`, `Task Graph`, `Controller`, etc.), not independently confirmed.
- **[REPOSITORY-VERIFIED]** — confirmed by direct inspection of the live repository in this session. *No claim in this document carries this tag — see §B.*
- **[INFERENCE]** — my own reasoning, not sourced from any of the above.
- **[PROPOSED DESIGN]** — a recommendation, not a fact about the current state of anything.

---

## A. Executive verdict

Nothing in this framework survives as a **new state machine**, a **new datastore**, or a **new authority**. Everything that survives becomes one of three things: a field/metadata extension on an existing artifact, an advisory scoring or diagnostic function with zero decision authority, or an optional tool/skill that sits outside the core loop and produces ordinary candidates the existing pipeline already knows how to validate.

Summary verdicts (full reasoning in §D and the matrix in §N):

| Candidate | Verdict |
|---|---|
| Q-05 — FALSIFIED failure classification | **ADOPT NARROWLY** |
| Q-02 — Epistemic ROI | **ADOPT NARROWLY** |
| Q-09 — MECE completeness | **MERGE**, conditional on a field diff I could not perform (§R) |
| Q-04 — Dependency/failure graph | **ADOPT NARROWLY** |
| Q-07 — Zwicky / morphological analysis | **EXPERIMENTAL** |
| Q-06 — TRIZ (full 40-principle corpus) | **DEFER** |
| Q-06 — TRIZ (abstract contradiction pattern only) | **ADOPT NARROWLY**, folded into Q-05 |
| Q-13 — Obsidian | **DEFER** |
| Q-01 — Parallel epistemic state machine | **REJECT** |
| 4S (as a persisted architecture layer) | **REJECT** |
| 4S (as a documentation/design lens) | **MERGE** |
| CV-01 — Adversary convergence flag | **EXPERIMENTAL**, and only for 3 of its 5 proposed metric levels |

The strongest single finding: Q-05 (what to do with a falsified hypothesis) is a genuine, well-scoped gap and should be the first thing built. The weakest: Q-01 and the 4S state-machine framing, both of which duplicate machinery that either already exists or is better represented as one field extension.

---

## B. Trust / provenance notes

I attempted to verify claims against the live repository before writing this, per the task's instruction. Results:

- Direct fetch of `https://github.com/ace2013hieco-aa/khwarizmi-research` returned a **404**. This is consistent with a private repository blocking unauthenticated access (GitHub returns 404 rather than 403 for private repos to avoid confirming their existence to unauthorized requests), but I cannot distinguish that from the repo simply not existing at that URL. Either way, I have no content from it.
- I searched the available MCP connector directory for a GitHub connector. **None exists in the directory available to me.** I have no path to authenticated repo access in this session.
- Consequently, **every "existing Hermes owner" assignment in this document is SOURCE-DERIVED or MEMORY-based, not REPOSITORY-VERIFIED.** Component names introduced fresh by this task's own prompt — `ResearchProgram`, `ResearchClaim`, `ResearchAssumption`, `Task Graph`, `Controller`, `Scheduler`, `Adversary` (as a named component), `Statistical Engine`, `ReportRenderer`, `Graph/Provenance layer`, `SkillRecord`, `Engineering Plane` — have no confirmed schema available to me. `ResearchSourceProvider` has two independent unverified mentions (this task, and the earlier Qwen "audit"), which raises my confidence slightly but does not make it verified.
- The CV-01 source document, `hermes_v6_convergence_flag_amendment.md`, was **not provided** in this conversation. My CV-01 analysis (§D.10, §L) uses only the summary embedded in this task's own text. If the actual document specifies different fields, constraints, or metric levels, that section needs to be re-checked against it.
- No credential or token content is reproduced anywhere in this document.

Practical implication: treat every "Exact owner" field in §D as a hypothesis to be confirmed, not a fact.

---

## C. Hermes baseline

**[MEMORY] — from prior conversations with Ace, unverified in this session:**
Evidence Ladder (SPECULATIVE → PLAUSIBLE → SUPPORTED → ROBUST → REPLICATED); reconciliation loop; typed Intent gateway; pre-registration with spec hashes; ThesisEvidenceTable; DatasetManifest; ScopeBrief; RETRACT_SOURCE cascade; DirectorDigest / HumanResumeDigest; corroboration count; skip-rate metric; AuditView; golden-scenario fixtures; a formal architecture-governance process (versioned docs + IDRs + adversarial review before adopting external ideas — the very process this document is part of).

**[SOURCE-DERIVED] — from this task's prompt, unverified:**
ResearchProgram, ResearchClaim, ResearchAssumption, Task Graph, Controller, Scheduler, Adversary (as a component), ResearchSourceProvider, Statistical Engine, ReportRenderer, Graph/Provenance layer, SkillRecord, Engineering Plane.

**Fixed design constraints, carried forward from the prior adversarial review and this task:**
1. Stdlib-first, minimal dependencies. Any candidate requiring a new external dependency needs an explicit IDR exception with justification.
2. Hermes remains sole authority for state, mutation, provenance, evidence, gating, scheduling, and reproducibility. Nothing here may become a second authority.
3. No silent transitions from FALSIFIED to a new hypothesis, and no silent bypass of existing gates, budgets, or dependency constraints, regardless of how a candidate is scored or classified.

---

## D. Candidate-by-candidate application models

### D.1 Q-05 — FALSIFIED failure classification

**A. Problem.** When a hypothesis is falsified, there is currently no confirmed structured mechanism for determining *why*, which blocks any principled reject/patch/pivot decision.

**B. Existing capability.** The Evidence Ladder [MEMORY] presumably has a falsification terminus. ThesisEvidenceTable [MEMORY] already links evidence to theses.

**C. Gap.** No taxonomy of failure causes, and no deterministic mapping from failure-type to permitted downstream action.

**D. Exact owner.** Evidence Ladder [MEMORY] — extend the FALSIFIED state; store classification on the existing falsification/ThesisEvidenceTable record, not a new artifact.

**E. Proposed application.** A required enum field `failure_class` with five values (HARD_AXIOM_VIOLATION, IMPLEMENTATION_FAILURE, ENVIRONMENT_MISMATCH, RESOURCE_CONSTRAINT, FRAMING_ERROR), each deterministically mapped to a permitted-action set.

**F. Data flow.** Contradicting evidence → ladder transition to FALSIFIED (existing) → LLM-proposed `failure_class` + citation → deterministic verification of the citation → classification recorded → permitted-action set exposed to Controller [SOURCE-DERIVED] → any resulting action still requires existing authorization.

**G. Authority boundary.** CAN propose a classification and compute the associated permitted-action set. CANNOT auto-create a hypothesis, auto-retract a branch, or auto-reopen a rejected line — this is the "must not silently pivot" rule from Chain A, and it is load-bearing.

**H. Persistence.** Field extension on the existing falsification record.

**I. Determinism.** The failure_class → permitted-action-set mapping is a deterministic lookup table. The classification itself may have LLM input but must be checked against a required citation (e.g., HARD_AXIOM_VIOLATION requires a citation to a specific axiom/constraint object in the pre-registration spec hash; no citation, no classification).

**J. Model boundary.** LLM proposes class + citation. Deterministic code validates the citation and owns the action-set mapping and authorization gating.

**K. Provenance.** Every classification must cite the specific evidence artifact(s), and (for HARD_AXIOM_VIOLATION) the specific violated axiom/constraint object.

**L. Security.** None — internal reasoning over internal artifacts.

**M. Phase.** 1 — highest priority.

**N. Acceptance tests.** A HARD_AXIOM_VIOLATION classification without a valid citation is rejected by the checker. A FRAMING_ERROR classification routes to the originating ScopeBrief, not a mechanism patch. Only IMPLEMENTATION_FAILURE may suggest (never auto-create) a substitution candidate. No classification, alone, creates a new hypothesis without passing existing authorization — verified in a regression test.

---

### D.2 Q-02 — Epistemic ROI

**A. Problem.** No confirmed cost-adjusted, expected-information-gain signal feeding task prioritization.

**B. Existing capability.** A Scheduler / Task Graph [SOURCE-DERIVED] is assumed to exist.

**C. Gap.** No such signal currently informs it.

**D. Exact owner.** Scheduler [SOURCE-DERIVED], as one input among existing priority factors — not a replacement.

**E. Proposed application.** `roi_score(task) = f(expected_information_gain, compute_cost, api_cost, time_cost, risk_cost)`, computed at eligibility time.

**F. Data flow.** Task metadata + deterministic cost terms + a heuristic/LLM information-gain estimate → roi_score → one ranking input to the existing scheduler, whose constraint logic (budgets, dependencies) runs independently and first.

**G. Authority boundary.** CAN influence ranking. CANNOT override gates, dependencies, budgets, safety checks, or Director-set priorities.

**H. Persistence.** Ephemeral computation; log as scheduling metadata for audit if useful, not a new artifact class.

**I. Determinism.** Cost terms deterministic/table-driven. Information-gain term is the one unavoidable heuristic input — log its provenance explicitly.

**J. Model boundary.** LLM/heuristic estimates information gain only. Deterministic code owns the arithmetic and the scheduler's use of it.

**K. Provenance.** Log which estimator produced the information-gain term for every scored task.

**L. Security.** None.

**M. Phase.** 1.

**N. Acceptance tests.** Removing ROI entirely leaves the scheduler functional. A negative/zero-ROI task is never scheduled ahead of a budget- or dependency-blocked task by virtue of ROI alone. ROI never appears as the sole justification for skipping a higher-priority gated task in an audit log.

---

### D.3 Q-09 — MECE completeness

**A. Problem.** No confirmed check that a decomposition is mutually exclusive and collectively exhaustive; gaps or overlaps could mean options are silently never considered or effort is duplicated.

**B. Existing capability.** ScopeBrief [MEMORY] presumably captures scope and constraints; unknown whether it captures decomposition structure. **This is the exact question the prior adversarial review flagged as blocking (Q-03) and it remains unresolved — I cannot perform the required field diff without repo access.**

**C. Gap.** Unknown pending that diff. Two branches: (1) ScopeBrief has no decomposition structure at all — a real, small gap; (2) it already tracks sub-questions/branches — the gap narrows to a completeness *checker* only.

**D. Exact owner.** Provisionally ScopeBrief or ResearchProgram [SOURCE-DERIVED, unverified]; the new piece, if any, is a diagnostic function, not an artifact family.

**E. Proposed application.** A deterministic-as-possible completeness check: missing-branch detection (does every stated constraint/actor/environment dimension have a corresponding branch?), overlap detection (do two branches share the same operative mechanism?), and a required alternative/do-nothing-branch check. Output: pass/fail + specific gap list, attached as metadata — not a new `MECEReport` artifact type unless the diff shows there's genuinely nowhere else to put it.

**F. Data flow.** ScopeBrief/ResearchProgram decomposition → rule-based checks (+ optional LLM-proposed candidate gaps) → diagnostic result stored on the same object → gate consumes pass/fail before allowing progression to hypothesis generation.

**G. Authority boundary.** CAN block progression on failure. CANNOT invent or auto-approve the content of a missing branch — only flag its absence.

**H. Persistence.** Field/metadata extension preferred; new artifact only if the diff shows no existing home.

**I. Determinism.** Coverage rules deterministic; LLM may suggest candidate gaps for human acceptance, never insert silently.

**J. Model boundary.** LLM proposes candidate gaps/overlaps; deterministic code owns the gate logic.

**K. Provenance.** Every flagged gap/overlap cites the specific branches compared.

**L. Security.** None.

**M. Phase.** 2 — blocked on the ScopeBrief field diff (effectively a Phase 0 research task, see §R).

**N. Acceptance tests.** A decomposition missing a stated constraint dimension fails with a specific citation. Two branches covering the same mechanism are flagged as overlapping. A decomposition with no do-nothing/reframe branch fails. Passing validates structural coverage only, never branch content.

---

### D.4 Q-04 — Dependency / failure graph

**A. Problem.** No confirmed way to answer "if A is rejected/patched/changed, what else is affected" — distinct from provenance (where something came from).

**B. Existing capability.** A Graph/Provenance layer [SOURCE-DERIVED] presumably tracks backward-looking derivation lineage (`derived_from`-style edges).

**C. Gap.** Provenance doesn't obviously answer the forward-looking "what currently depends on this" question needed to prevent a fix in one place silently invalidating conclusions elsewhere.

**D. Exact owner.** Graph/Provenance layer [SOURCE-DERIVED], extended with new *edge types* only — no new node types, no new datastore. Existing artifacts (Evidence, ResearchClaim, ResearchAssumption, hypotheses, tasks) keep their identity; the graph adds edges between existing IDs.

**E. Proposed application.** Three new edge types: `depends_on`, `conflicts_with`, `introduces_risk` (the last referencing an existing risk/assumption record, not a free-text field). **Explicitly reject** the original source's full 16-node/16-edge taxonomy — most of those node types either duplicate existing artifact classes under different names or don't need first-class node status at all.

**F. Data flow.** Authoring time: author declares `depends_on` edges to existing objects. Review time (Adversary/hostile-gate style): `conflicts_with` and `introduces_risk` edges added, since detecting a conflict requires comparison against the rest of the graph. On any FALSIFIED or RETRACT_SOURCE-cascade event [MEMORY], a deterministic reachability query over `depends_on` identifies every downstream object needing re-review — the single most concrete use case here.

**G. Authority boundary.** CAN surface affected downstream objects for re-review. CANNOT auto-retract, auto-invalidate, or auto-modify them — that stays wherever RETRACT_SOURCE cascade authority already lives [MEMORY].

**H. Persistence.** Extension of the existing graph layer's edge set.

**I. Determinism.** Edge existence and reachability queries must be deterministic. Whether a pair *should* have a `conflicts_with` edge may involve LLM judgment; the traversal that uses a declared edge must not.

**J. Model boundary.** LLM proposes edges with justification; deterministic code owns storage, cycle handling, traversal.

**K. Provenance.** Every edge records who/what proposed it and what evidence was cited.

**L. Security.** None beyond what the existing graph layer already handles.

**M. Phase.** 2, explicitly gated on confirming this is a real gap rather than something the existing provenance graph already computes (see §R) — if reverse traversal over existing `derived_from` edges already answers "what depends on this," this collapses to "write a new query," not "add edge types."

**N. Acceptance tests.** Retracting a source correctly identifies every object with a `depends_on` path to it (test on a graph with ≥3 hops, no false negatives). A cycle in `depends_on` is rejected at creation time. Reachability query runtime is bounded on a realistically-sized graph.

---

### D.5 Q-07 — Zwicky / morphological analysis

**A. Problem.** Candidate generation may rely on ad hoc or opaque LLM brainstorming with no systematic, inspectable coverage guarantee.

**B. Existing capability.** None confirmed — this is the strongest candidate for "genuinely new but small," since it doesn't obviously duplicate ScopeBrief, the Evidence Ladder, or provenance.

**C. Gap.** A deterministic, inspectable way to enumerate a solution space along explicit dimensions.

**D. Exact owner.** None existing — implement as a stateless tool/skill, not a subsystem.

**E. Proposed application.** Given human-approved dimensions and per-dimension values, deterministically enumerate the Cartesian product, apply declared exclusion constraints, and emit survivors as ordinary hypothesis proposals into the existing pipeline. Zwicky output carries no special status once emitted.

**F. Data flow.** Dimensions + values (human-approved) → deterministic constraint filter → combination list → each becomes a normal candidate-hypothesis → unchanged existing validation pipeline.

**G. Authority boundary.** CAN generate candidates. CANNOT receive different validation treatment than any other hypothesis.

**H. Persistence.** Persist the dimension/value declaration as run metadata attached to the resulting candidate batch, for reproducibility — the tool itself needn't be a first-class subsystem.

**I. Determinism.** Dimension/value declaration may be LLM-assisted; combination generation and filtering must be fully deterministic given the declared inputs.

**J. Model boundary.** LLM proposes dimensions/values for human approval; deterministic code owns enumeration and filtering.

**K. Provenance.** Every generated candidate records its source dimension-value tuple.

**L. Security.** None.

**M. Phase.** 2/3, experimental. Anti-explosion controls (§I below) must be specified before this goes live — 6 dimensions × 5 values is already 15,625 combinations.

**N. Acceptance tests.** Identical inputs reproducibly generate the identical candidate set. A declared exclusion constraint removes exactly the excluded combinations. Every candidate traces back to a specific tuple. A combinatorial-explosion guard actually halts generation past a configured limit rather than silently truncating.

---

### D.6 Q-06 — TRIZ

Full protest and verdict in §J. Summary: **DEFER** the 40-principle corpus; **ADOPT NARROWLY** the abstract contradiction-statement pattern only, folded into Q-05's IMPLEMENTATION_FAILURE path as a prompt technique, not a new component.

---

### D.7 Q-13 — Obsidian

**A. Problem.** Humans may want a browsable/curatable graph view rather than reading linear digests.

**B. Existing capability.** DirectorDigest / HumanResumeDigest [MEMORY] already provide human-facing summaries. AuditView [MEMORY] — the name alone suggests a human-facing inspection surface may already exist, which is a strong reason to check before building a second one.

**C. Gap.** Unconfirmed. Digests are presumably linear; graph browsing is a different modality. Whether that modality gap justifies a new dependency is a value judgment for Ace, not an architectural necessity.

**D. Exact owner.** Graph/Provenance layer [SOURCE-DERIVED] remains sole authority; Obsidian, if built, is a read-only exporter/projection only.

**E. Proposed application.** A one-way export job (Hermes canonical state → Obsidian-compatible markdown + frontmatter), run on demand or schedule. No import path, ever, absent a separate future IDR explicitly permitting one.

**F. Data flow.** Hermes graph/provenance state → deterministic exporter → static markdown files → Obsidian (read/browse only).

**G. Authority boundary.** CAN project for browsing. CANNOT write back under any circumstance in this design.

**H. Persistence.** Exported files are disposable/regenerable projections — never a backup, never a source of truth.

**I. Determinism.** Same graph state must produce the same exported files.

**J. Model boundary.** None — mechanical export, no reasoning task.

**K. Provenance.** Each exported note carries its source object's ID and last-updated timestamp.

**L. Security.** Obsidian is an external application outside Hermes's process boundary. The exporter writes to a Hermes-controlled directory; it should assume nothing about the human's Obsidian plugins or sync services, and use no credentials or network calls. Note: the exporter itself, being pure file writes, may not actually trigger the stdlib-first dependency concern the prior review raised — that concern applies more to *using* Obsidian (the human's local application) than to writing markdown files, which needs no new Hermes dependency at all.

**M. Phase.** 3 or later — lowest priority.

**N. Acceptance tests.** Re-running the export with unchanged state produces byte-identical output. Deleting and regenerating the export directory reproduces the same content. No code path reads from the export directory back into Hermes state.

---

### D.8 Q-01 — Parallel epistemic state machine

**Verdict: REJECT.**

**A–C.** The proposed states (PROPOSED, EXPERIMENTING, FALSIFIED, CORROBORATED, INCONCLUSIVE) map onto the existing Evidence Ladder [MEMORY] without residue: PROPOSED ≈ pre-registered/SPECULATIVE; EXPERIMENTING ≈ an in-progress ladder climb; CORROBORATED ≈ a matter of degree already captured by SUPPORTED/ROBUST/REPLICATED; FALSIFIED already exists as a terminus (and gets the Q-05 extension); INCONCLUSIVE ≈ "still SPECULATIVE/PLAUSIBLE, no further evidence pending" rather than a distinct state. No gap identified.

**D–N.** Not applicable. If a genuine gap surfaces later (e.g., the ladder can't represent "actively being tested" distinctly from "not started"), raise it as a single targeted field addition, not a parallel machine.

---

### D.9 4S (State / Structure / Solve / Sell)

**A. Problem.** Risk of solving the wrong problem, wrong decomposition, wrong framework, or a technically correct but non-actionable output.

**B. Existing capability.** ScopeBrief [MEMORY] (State), the Q-09 diagnostic if built (Structure), the existing hypothesis/experiment/Evidence Ladder pipeline (Solve), DirectorDigest/HumanResumeDigest [MEMORY] (Sell).

**C. Gap.** Primarily an organizing/naming question, not a capability question, once Q-09 is resolved. The open question is whether ScopeBrief already has TOSCA-style completeness properties — blocked on the same repo-access gap as Q-09.

**D. Exact owner.** No single owner — 4S is a cross-cutting checklist over existing/proposed components, not a new component.

**E. Proposed application.** Use "State/Structure/Solve/Sell" as internal design language only. Do not persist "4S" as a field, state, or gate anywhere. If a lightweight check is wanted, make it a documentation checklist for engineers authoring ScopeBriefs, not a runtime mechanism.

**F–N.** Not applicable in the runtime sense — see §K for the full protest.

---

### D.10 CV-01 — Adversary convergence flag

**A. Problem.** An Adversary critique and the original Researcher chain could converge on the same conclusion through correlated failure (shared sources, shared biases) rather than genuine independent verification — undetected, this makes correlated errors look like agreement, which is worse than no adversarial check.

**B. Existing capability.** An Adversary/critique mechanism exists [SOURCE-DERIVED, consistent with the prior review's description of "hostile gates"/"adversarial audits"]. No confirmed convergence-detection mechanism.

**C. Gap.** No way to distinguish "agreed because well-supported" from "agreed because drawing on the same sources and never had a real chance to disagree."

**D. Exact owner.** Adversary component [SOURCE-DERIVED], extended with a post-hoc, read-only diagnostic — not a second Adversary, not a new verdict authority.

**E. Proposed application.** After an ADVERSARIAL_REVIEW task, run a deterministic ConvergenceCheck across whichever overlap levels are well-defined (see §L — currently 3 of 5). Output: an advisory flag on the review record, visible only at Director review, with zero effect on the Critique verdict, Evidence Ladder, or gate outcome.

**F. Data flow.** Researcher chain + Critique chain → per-level overlap computation → diagnostic vector (not a scalar) → advisory flag → Director review only.

**G. Authority boundary.** CAN surface a diagnostic. CANNOT alter, veto, or annotate the verdict; cannot function as evidence; cannot block a gate.

**H. Persistence.** Derived/computed diagnostic attached to the review record — explicitly not an evidence type.

**I. Determinism.** Overlap computations must be fully deterministic given the two artifact chains.

**J. Model boundary.** None in the check itself. Using an LLM to judge "argument-structure overlap" would introduce a second model call whose own correlation with the originals becomes a confound — avoid it; use structural/lexical proxies instead.

**K. Provenance.** Every flagged overlap cites exactly which artifacts/citations/claims overlapped.

**L. Security.** None.

**M. Phase.** EXPERIMENTAL — not ready for Phase 1; the metrics need their own design pass first.

**N. Acceptance tests.** A Researcher/Critique pair built from deliberately independent sources scores low on citation and lineage overlap; a pair sharing source material scores high. The flag never appears in any code path that reads the verdict field. Removing the ConvergenceCheck entirely changes no gate outcome in regression.

---

## E. Cross-capability workflows

**Chain A — Failed hypothesis → adaptive pivot.**
Evidence (existing) → FALSIFIED (existing ladder terminus) → failure classification (Q-05, new field) → deterministic permitted-action lookup → {reject: existing RETRACT_SOURCE cascade / patch: IMPLEMENTATION_FAILURE only, optionally using the narrow TRIZ pattern / pivot: FRAMING_ERROR only, returns to ScopeBrief / escalate: Director}. Every branch requires existing authorization before a new hypothesis or task is created — this directly satisfies the no-silent-pivot rule.

**Chain B — Problem → structured solution space.**
ScopeBrief → Q-09 MECE gate → Zwicky (Q-07, optional, never mandatory) → candidates → existing validation. If Phase 0 shows ScopeBrief already enforces completeness, this collapses to "ScopeBrief → candidates," with Zwicky remaining a tool a researcher may invoke.

**Chain C — Dependency-aware candidate analysis.**
Candidate → Q-04 dependency edges (declared/proposed) → reachability check → surfaced conflicts/risks → existing Adversary review → existing decision. The graph's marginal contribution over ordinary provenance is specifically the forward "what would this affect" query.

**Chain D — Epistemic ROI.**
Task pool → Q-02 roi_score (advisory) → existing Scheduler (unchanged authority) → execution. Must never bypass budgets/gates/dependencies.

**Chain E — Adversary independence.**
Research chain + existing Critique → CV-01 overlap check → advisory flag → Director review only if flagged. Never changes the Critique's own verdict.

---

## F. FALSIFIED failure-classification framework (detailed)

| Class | Supporting evidence | Generator | LLM may propose? | Deterministic check | Downstream action enabled | Prohibited without Director/human | Persisted as |
|---|---|---|---|---|---|---|---|
| HARD_AXIOM_VIOLATION | Citation to a specific axiom/constraint in the pre-registration spec hash that the evidence contradicts | Adversary or Researcher | Yes, mandatory citation | Cited axiom object exists and is the right type | Mark branch REJECTED; trigger Q-04 downstream re-review check | Deleting history; reopening the same mechanism without new axioms | Metadata field + citation |
| IMPLEMENTATION_FAILURE | Evidence shows the specific mechanism failed, not the underlying goal | Adversary or Researcher | Yes | Cited evidence references the mechanism-level component, not the top-level goal | Propose (not create) a mechanism-substitution candidate, optionally via the narrow contradiction pattern or Zwicky | Auto-creating/auto-scheduling the substitute | Metadata field + link to draft substitution candidate |
| ENVIRONMENT_MISMATCH | Evidence shows the mechanism works in one regime but not the tested one | Adversary or Researcher | Yes | Cited evidence includes a differing environment/regime tag | Narrow the hypothesis's applicable regime (scope edit, not a new hypothesis) | Broadening scope without new evidence | Metadata field + regime tag |
| RESOURCE_CONSTRAINT | Evidence shows the mechanism would work with more budget/compute/data | Scheduler-adjacent check or Adversary | Yes | Cited evidence quantifies a specific resource gap | Flag for re-evaluation if resources change (parked, not final) | Silent retry without confirming resources actually changed | Metadata field + resource-gap quantity |
| FRAMING_ERROR | Evidence/argument shows the question, not the mechanism, was wrong | Adversary, confirmed by Director | Requires human confirmation, not LLM-only, since it implicates the ScopeBrief itself | A specific ScopeBrief field is cited as the source of the framing error | Route back to ScopeBrief revision, not hypothesis revision | Any agent unilaterally rewriting the ScopeBrief without its owner | Metadata field + ScopeBrief field citation |

FRAMING_ERROR is deliberately the most restricted class: it implicates the problem definition itself, and should require the same authority that can revise a ScopeBrief — not whoever ran the experiment.

---

## G. MECE framework (detailed)

I cannot perform the required field-by-field diff of `ProblemCharter`/`CoreQuestion` against `ScopeBrief`/`ResearchProgram` without repository access. What follows is the diff *procedure* and the conditional recommendation for each branch.

**Branch 1 — ScopeBrief already has TOSCA-equivalent fields** (trouble/owner/success-criteria/constraints/actors) and/or decomposition structure: then `CoreQuestion`/`ProblemCharter` contribute nothing new. MECE capability = a completeness diagnostic over ScopeBrief's existing structure (or a new minimal "branches" list field if decomposition isn't tracked yet).

**Branch 2 — ScopeBrief captures only top-level scope/intent**, with no explicit owner/success-criteria/constraint separation: then a small, targeted set of new *required fields* on ScopeBrief (mirroring TOSCA's five elements) is a genuinely useful minimal addition, plus the same completeness diagnostic.

**Recommendation:** run this diff as an explicit Phase 0 research task before designing Q-09 further (see §R).

**Minimum output form:** prefer a deterministic diagnostic returning pass/fail + gap list, attached as metadata to the ScopeBrief/ResearchProgram — not a new persisted `MECEReport` artifact type, unless the diff shows MECE checks need their own approval workflow distinct from ScopeBrief revision.

---

## H. Dependency / failure graph framework (detailed)

- **Node reuse.** No new node types; edges reference existing artifact IDs (hypotheses, claims, assumptions, evidence, tasks).
- **Edge reuse.** Three new edge types only (`depends_on`, `conflicts_with`, `introduces_risk`), reusing whatever storage the existing provenance layer already has.
- **Reachability.** Backward traversal (provenance) presumably already exists; forward traversal ("what depends on this") is the new need.
- **Cycle constraints.** `depends_on` must be acyclic — reject at edge-creation time if a cycle would result. `conflicts_with`/`introduces_risk` aren't directional in the same sense and should be deduplicated (A↔B is one fact).
- **Versioning.** If underlying objects can be revised (not just retracted), edges should reference a specific version/hash where the existing (reportedly content-addressed) provenance layer supports it — otherwise an edge can silently point at a stale version.
- **Provenance.** Every edge carries who/what proposed it and its supporting citation.
- **Deterministic traversal.** Reachability queries must be reproducible given fixed graph state — worth an explicit test given Hermes's overall determinism emphasis.

---

## I. Zwicky framework (detailed)

Anti-explosion controls, in order of preference:
1. Hard caps on dimension count (e.g., ≤6) and values per dimension (e.g., ≤5) — configuration-level, not runtime-negotiable by an agent.
2. Exclusion-constraint pass applied before enumeration counts against the cap.
3. Mandatory human approval of the dimension/value set before enumeration runs.
4. Q-02 ROI scoring to rank and truncate the generated list before entering the validation pipeline — only top-N proceed automatically; the rest are retained but not scheduled.

**Minimum useful version:** fixed small caps + human approval gate before enumeration + no automatic scheduling beyond top-N by ROI.

---

## J. TRIZ decision — structured protest and verdict

1. **What does TRIZ solve that Zwicky/Adversary doesn't?** Zwicky enumerates combinations of a *known* dimension set; it doesn't help when no one has identified the right dimension at all — i.e., reframing rather than recombining. TRIZ's contradiction framing targets exactly that reframing step. A theoretically distinct niche exists; the open question is whether the specific principle library is the right tool.

2. **Does the 40-principle corpus transfer to Hermes's actual domain?** Unverifiable without confirmed knowledge of that domain. Working assumption [MEMORY-derived]: quantitative/financial research, where several principles (mechanical substitution, phase transition, field substitution) have no obvious literal meaning, while others (segmentation, prior action, inversion, "use of copies" ≈ simulation) have plausible abstract analogs. This is a genuine 50/50 case, not one to resolve by assumption.

3. **Can the abstract pattern be kept without the corpus?** Yes — "state what improves, state what worsens, ask what would let both improve" needs no TRIZ branding or principle library, and carries none of the domain-transfer risk.

4. **Optional domain skill?** Only after evidence of transfer.

5. **What evidence would justify adoption?** At least one retrospective case where framing a real Hermes failure as a TRIZ contradiction, mapped to a specific principle, produced a candidate a domain expert (Ace) judges non-obvious and useful — one the abstract pattern alone would not have produced.

**Verdict: DEFER** the full corpus. **ADOPT NARROWLY** the abstract contradiction pattern, folded into Q-05's IMPLEMENTATION_FAILURE path. Hold the full corpus at EXPERIMENTAL SKILL status pending the retrospective test in (5). Do not build TRIZ-specific tooling in Phase 1/2.

---

## K. 4S framework — detailed mapping

Direct answer to the task's question — **is 4S worth persisting as a named Hermes concept, or is it a design lens?**

**Design lens only.** Every stage maps onto an existing or proposed component with no residual capability once those are accounted for: State → ScopeBrief; Structure → Q-09 diagnostic; Solve → existing hypothesis/experiment/Evidence Ladder pipeline; Sell → DirectorDigest/HumanResumeDigest. Persisting it as a 9-state mandatory pipeline (as IDR-025 proposed) would layer a second gate sequence on top of gates that mostly already exist or are covered by the narrower Q-09/Q-05 proposals — the "turned a methodology into architecture unnecessarily" failure mode the anti-overengineering checklist warns against.

---

## L. CV-01 convergence framework — detailed protest and candidate design

| Level | Deterministic? | Meaningful? | Cheap? | Interpretable? | False-positive risk | False-negative risk | Verdict |
|---|---|---|---|---|---|---|---|
| 1. Citation-set overlap | Yes | Weak alone — two good-faith reviewers citing the same primary sources is often expected, not suspicious | Yes | Yes | High — conflates "same good sources" with "correlated failure" | Low | Compute, but never use alone; genuinely ambiguous as an independence proxy |
| 2. Argument-structure overlap | Not well-defined without a formal argument representation | Potentially, if defined | No — likely needs a second model call, reintroducing the confound noted in D.10.J | Only if the representation is inspectable | Unknown | Unknown | Not ready — needs its own design pass before it's a metric at all |
| 3. Assumption overlap | Yes, if ResearchAssumption exists as structured data | Yes — shared unexamined assumptions is a much better correlated-failure signal than shared citations | Yes, if structured | Yes | Lower than Level 1 | Moderate | Best candidate — implement first |
| 4. Prediction overlap | Yes, if predictions are structured data on hypotheses/claims | Yes | Yes | Yes | Moderate | Moderate | Good second candidate |
| 5. Artifact-lineage overlap | Yes, via existing provenance (`derived_from`) | Strong — shared upstream artifact is directly interpretable | Yes, if lineage queries already exist | Yes | Low | Low | Strong candidate, reuses Q-04/existing provenance |

**Recommendation:** implement Levels 3, 4, and 5 first. Keep Level 1 computed but flagged as weak/ambiguous, not primary. Do not implement Level 2 until it has its own design spec — right now it's an aspiration, not a metric. Output form: a diagnostic vector across implemented levels, never a single scalar — a scalar would hide exactly the distinction (high citation overlap, low lineage overlap, or the reverse) that makes this useful.

---

## M. Research Operating System map

| Loop stage | Status |
|---|---|
| DEFINE | Exists — ScopeBrief [MEMORY] |
| STRUCTURE | Proposed, pending diff — Q-09 |
| HYPOTHESIZE | Exists — pre-registration with spec hashes [MEMORY] |
| DESIGN | Not addressed by any candidate here (Zwicky is a tangential accelerant at most) |
| EXECUTE | Outside scope of this review's candidates |
| OBSERVE | Exists — ThesisEvidenceTable [MEMORY] |
| FALSIFY/SUPPORT | Exists — Evidence Ladder [MEMORY] |
| EXPLAIN FAILURE | **The clearest actual gap** — Q-05 |
| PIVOT/REFINE | Partially covered by Q-05's action set; Zwicky and the narrow TRIZ pattern are optional accelerants, not required |
| PRIORITIZE NEXT INFORMATION | Proposed, advisory — Q-02 |
| REPORT/DECIDE | Exists — DirectorDigest/HumanResumeDigest [MEMORY]; Q-13 is an optional additional projection |

Of 11 stages, 5 already have confirmed owners, 1 (EXPLAIN FAILURE) has a clear, well-scoped gap, 2 (STRUCTURE, PRIORITIZE) have plausible-but-unverified small gaps, 1 (PIVOT/REFINE) has an optional accelerant with real domain-transfer risk, and 2 (DESIGN, EXECUTE) are untouched by any candidate here. **No "Research OS kernel" abstraction is warranted** — the loop is mostly already covered by named components; what's missing is one clear gap and two small, unverified ones.

---

## N. Proposed application matrix

| Candidate | Real gap | Existing owner | Application | Data form | Authority | Phase | Priority | Verdict |
|---|---|---|---|---|---|---|---|---|
| Q-05 | Yes | Evidence Ladder | Enum field + deterministic action-mapping | Field extension | Advisory classification, deterministic action-gating | 1 | High | ADOPT NARROWLY |
| Q-02 | Plausible | Scheduler | Advisory scoring function | Ephemeral computation | Advisory only | 1 | Medium | ADOPT NARROWLY |
| Q-09 | Unknown, pending diff | ScopeBrief/ResearchProgram | Completeness gate | Field/metadata | Blocks progression, not content | 2 | Medium | MERGE (conditional) |
| Q-04 | Plausible | Graph/Provenance layer | 3 new edge types | Edge extension | Surfaces, doesn't decide | 2 | Medium | ADOPT NARROWLY |
| Q-07 | Plausible, most independent | None (new tool) | Deterministic combination generator | Skill/tool + run metadata | Generates only | 2/3 | Low-Med | EXPERIMENTAL |
| Q-06 (full) | Unverified | None | N/A pending evidence | N/A | N/A | Deferred | Low | DEFER |
| Q-06 (narrow) | Weak, harmless | Folds into Q-05 | Contradiction-statement prompt | No new artifact | Advisory | 1 | Low | ADOPT NARROWLY |
| Q-13 | Weak, AuditView may cover it | Graph/Provenance layer | One-way exporter | Disposable projection | Read-only | 3 | Low | DEFER |
| Q-01 | None found | Evidence Ladder | N/A | N/A | N/A | — | — | REJECT |
| 4S (architecture) | None | Cross-cutting | N/A | N/A | N/A | — | — | REJECT |
| 4S (methodology) | N/A | Cross-cutting | Documentation lens | N/A | N/A | — | — | MERGE |
| CV-01 | Plausible, needs metric redesign | Adversary | Diagnostic vector (Levels 3,4,5) | Derived, non-evidentiary | Advisory only | 2 | Medium | EXPERIMENTAL |

---

## O. Phase plan

**Phase 0 (research, not design).** Field diff: ScopeBrief/ResearchProgram vs. ProblemCharter/CoreQuestion (resolves Q-09 and 4S). Confirm whether AuditView already provides graph/human-facing browsing (resolves part of Q-13). Confirm whether the provenance graph already supports forward reachability (resolves whether Q-04 is edge-addition or query-addition). This requires repository/architecture-doc access I don't currently have (§R) — cannot be completed in this session.

**Phase 1.** Q-05, Q-02, Q-06-narrow (folded into Q-05).

**Phase 2.** Q-09 (contingent on Phase 0), Q-04 (contingent on Phase 0), CV-01 (Levels 3/4/5 only).

**Phase 3.** Q-07, Q-13 (if still wanted after Phase 0).

**Not scheduled.** Q-01 (rejected), Q-06 full corpus (deferred), 4S as persisted architecture (rejected).

---

## P. Acceptance-test concepts

Per-candidate tests are in §D (item N each). Cross-cutting requirements:
- No candidate may pass acceptance testing if it can create a hypothesis, retract a branch, or modify a ScopeBrief without existing authorization.
- Every advisory score/flag (ROI, convergence) needs a regression test proving its removal changes no gate outcome.
- Every new edge or field needs a determinism test: same input state, same output.

---

## Q. Deferred / rejected ideas

- **REJECT** — Q-01: no gap beyond what Q-05 covers.
- **REJECT (as architecture)** — 4S as a 9-state mandatory pipeline: fully covered by existing/proposed components.
- **REJECT** — the full 16-node/16-edge KG taxonomy: collapsed to 3 edge types (Q-04).
- **REJECT, pending Phase 0** — ProblemCharter/CoreQuestion as new artifacts: presumptively redundant with ScopeBrief per the prior review.
- **DEFER** — Q-06 full TRIZ corpus: pending retrospective evidence of domain transfer.
- **DEFER** — Q-13 Obsidian: pending confirmation that AuditView doesn't already serve this need.
- **DEFER** — CV-01 Level 2 (argument-structure overlap): not yet a well-defined metric.

---

## R. Remaining architecture questions

These block converting this framework into implementation prompts.

1. **Repository access.** I could not reach `https://github.com/ace2013hieco-aa/khwarizmi-research` (404, consistent with a private repo) and found no GitHub connector in the available MCP directory. Every "Exact owner" assignment above is unverified. Before generating implementation prompts, someone with actual repo access — Ace, or a future session using a properly scoped OAuth connector, not a pasted token — needs to confirm or correct each assignment in §D.
2. **ScopeBrief field diff.** The single highest-leverage open question: does ScopeBrief already have TOSCA-equivalent fields and/or decomposition structure? Determines the verdict on Q-09 and most of 4S.
3. **Forward reachability.** Does the existing provenance graph already support "what depends on this" queries in reverse? Determines whether Q-04 needs new edge types or just a new query.
4. **What AuditView actually is.** Its name suggests a human-facing inspection surface may already exist, which would reduce or eliminate the case for Q-13.
5. **CV-01's actual source document** (`hermes_v6_convergence_flag_amendment.md`) was not provided in this conversation. My analysis relies entirely on the summary embedded in this task's prompt; if the real document differs, §D.10 and §L need re-checking.
6. **Hermes's actual research domain** — assumed quantitative/financial [MEMORY-derived] for the TRIZ domain-transfer question. Should be confirmed, not assumed.
7. **What `Statistical Engine`, `ReportRenderer`, `Task Graph`, `Controller`, and `Engineering Plane` actually do.** These names appear only in this task's own vocabulary. I've deliberately avoided assigning any candidate to them specifically because I can't confirm what they are; a repo-verified pass may reassign some owner fields once they're understood.
