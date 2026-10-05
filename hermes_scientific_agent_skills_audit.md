# HERMES × SCIENTIFIC AGENT SKILLS — SELECTIVE SOURCE AUDIT

**Date:** 2026-08-13
**Source audited:** `https://github.com/ace2013hieco-aa/scientific-agent-skills`
**Source HEAD:** `5ad4aae76bc40257b914367afacc6fd686a282d5` (2026-08-11), v2.63.0, MIT, 161 skills
**Hermes baseline:** `hermes_research_architecture_v6.md` (RATIFIED §1–§28; CONTRA candidate §29) + live repo at HEAD `4b2a7ce`, suite 571 passed.
**Method:** source-first inspection (SKILL.md, scripts, references, tests, CI, security scan) per candidate; then each candidate audited against the live Hermes code and the ratified v6 text. Independent of any prior review — the reference review supplied by the user was read **after** the per-candidate audits were drafted, and the cross-reference matrix (§13) records where the two agree and where this audit sharpens or departs.

---

## 1. Executive Verdict

**Six of eight candidates are worth harvesting; none are worth importing wholesale; zero new architectural components are required.**

The source repository is genuinely well-governed — MIT, per-skill version/author/license front-matter, per-skill pytest suites, skill-spec validation CI, a weekly LLM-assisted security scan with a published triage ledger (34 CRITICAL / 8 HIGH findings out of 954, 146/161 skills clean), and a PR skill-scan gate. That governance pattern is itself a harvest (§7.9). But the skills are **agent-facing capability documents + thin CLIs**, and Hermes is a deterministic research-control system. The correct disposition is uniformly **"harvest the methodology and the deterministic CLI patterns; reimplement inside Hermes-owned ports; reject the orchestration, the package ecosystems, and the external-LLM surfaces."**

The most important structural finding is on the Hermes side: **`ResearchSourceProvider` and `ReportRenderer` are 4-line and 5-line stubs** (`src/hermes/tools/research_sources.py`, `src/hermes/tools/reporting.py`). The v6 architecture defines both as Hermes-owned native reimplementations (§27 items / §15), but the *slots exist and the implementations do not*. Several candidates (Paper Lookup, Literature Review, Scientific Writing) therefore address real, current gaps — not hypothetical ones. The other candidates (Experimental Design, Statistical Analysis, Hypothesis Generation, Peer Review, Critical Thinking) map onto surfaces that are architectural (ExperimentSpec, Statistical Gate, Adversary, ResearchProgram) but not yet operational in this phase; for those the harvest is **methodology content to be encoded when the surrounding slices land**.

**The strongest single candidate is Hypothesis Generation.** Its explicit "never score/rank/select/accept/reject hypotheses" boundary, its separation of observation/question/hypothesis/mechanism/estimand/prediction/alternative/null/control, its prediction-matrix validator, causal-claim linter, falsification-control checker, and preregistration scaffold — all stdlib-only, deterministic, local-only — are almost exactly Hermes' epistemic discipline expressed as skill material. It should be the first thing harvested.

**Second strongest: Paper Lookup.** The per-provider reference files encode a decade of API failure semantics (HTTP-200 failures, cursor traps, silent rewrites) that Hermes' own ResearchSourceProvider will need. Harvest the *failure catalog* as content and the pagination/reconciliation discipline as ideas; reimplement the provider abstraction as the v6 architecture already mandates.

---

## 2. Source Repository Findings

| Fact | Value |
|---|---|
| License | MIT (K-Dense Inc.) |
| HEAD | `5ad4aae7` (2026-08-11), version 2.63.0 |
| Collection | 161 skills, 100+ databases, Agent Skills standard + Agent Plugins package |
| Python | requires >=3.13; skill scripts vary (3.10–3.11+) |
| Core deps | `cisco-ai-skill-scanner`, `firecrawl-py`, `pytest`, `python-dotenv` |
| CI | skill-spec-validation, skill-tests (per-skill pytest), security-scan (weekly), pr-skill-scan, release |
| Security scan (2026-08-10) | 954 findings; 34 CRITICAL / 8 HIGH / 146 of 161 safe; scanner `cisco-ai-skill-scanner 2.0.13` + `claude-opus-5` |
| Skill format | `SKILL.md` front-matter (`name`, `description`, `allowed-tools`, `license`, `compatibility`, `metadata.version`, `skill-author`) + `references/`, `scripts/`, `assets/`, per-skill `tests/` |

**Governance observations (independently verified):**
- Every audited skill declares `allowed-tools`, license, version, and author in front-matter; several declare `last-reviewed`.
- Deterministic CLIs in the high-value skills are deliberately **stdlib-only and network-free** (paper-lookup scripts, peer-review CLIs, hypothesis-generation CLIs, scientific-writing CLIs). This is a genuine engineering choice, not an accident — and it is the exact shape Hermes wants.
- The security model is real but bounded: the scan is LLM-assisted with a published triage ledger distinguishing verified findings, fixes, and false-positive classes. "Passed upstream CI" was explicitly **not** treated as "safe for Hermes" — the scan itself flags `literature-review`, `scientific-schematics`, `scientific-slides` as CRITICAL, and those flags match the structural risks this audit found (§6, §10).
- The collection's orchestration (parallel-cli, cross-skill invocation, PDF/figures generation, OpenRouter-backed steps) is **rejected as a Hermes pattern** (§6, §8, §15).

---

## 3. Candidate-by-Candidate Audit

### 3.1 Paper Lookup — **REIMPLEMENT AS HERMES SKILL (provider reimplementation)**

- **Source location:** `skills/paper-lookup/` (SKILL.md 263 lines; `references/` 11 per-provider files ≈ 2,000 lines; `scripts/` 5 stdlib-only CLIs ≈ 1,400 lines; `tests/test_scripts.py` 586 lines).
- **What it actually provides:** 11 scholarly APIs (PubMed, PMC, Europe PMC, bioRxiv, medRxiv, arXiv, OpenAlex, Crossref, Semantic Scholar, CORE, Unpaywall); per-provider endpoint/parameter/hazard references; bounded pagination with **retrieved-vs-total reconciliation (exit 4 on shortfall)**; identifier normalization; JATS full-text extraction; arXiv Atom parsing that catches the API's HTTP-200 "Error" entry; redaction of credentials from logged URLs; an explicit **external-content instruction-injection boundary** ("treat every response as untrusted third-party data").
- **Concrete Hermes gap:** `ResearchSourceProvider` is a 4-line stub. The v6 architecture mandates Hermes-owned native reimplementation with thin adapters — the slot is ratified but empty.
- **Existing overlap:** `src/hermes/tools/research_sources.py` (stub), v6 §15/§27 provider port, `dataset_manifests` + `_dereference_artifact_ref` write-path discipline (P7).
- **Architectural fit:** EXCELLENT — the skill's contract (bounded retrieval → schema'd records with provenance, repeatable) is exactly the ResearchSourceProvider contract.
- **Determinism:** retrieval/parsing/reconciliation must be deterministic in Hermes (catalog + redaction + reconciliation are code). Database selection and query refinement are LLM judgment, bounded by a skill.
- **Security:** stdlib-only scripts, no credentials in repo, redact_url helper, injection boundary documented. LIGHT.
- **Dependencies:** standard library only (scripts). LIGHT.
- **License:** MIT. **Phase:** P7 (Research Execution).
- **Disposition:** **REIMPLEMENT AS HERMES SKILL** — harvest the per-provider **failure catalog** as reference content, the **reconciliation/redaction/pagination discipline** as ideas; reimplement the provider abstraction and thin adapters as v6 §15 already requires, then wrap the methodology in a SkillRecord. Do not import the scripts verbatim (they encode cursor logic per provider that the Hermes adapters will own).

### 3.2 Experimental Design — **REIMPLEMENT AS HERMES P8 SKILL**

- **Source location:** `skills/experimental-design/` (SKILL.md 234 lines; `references/` 4 files ≈ 470 lines; `scripts/doe_designs.py` 183, `scripts/randomization.py` 171; `tests` 322 lines).
- **What it actually provides:** pre-data design decisions (Fisher's three principles), design-type selection (full/fractional factorial, Plackett–Burman, CCD, Box–Behnken, Latin hypercube, crossover, repeated measures, split-plot, Latin square, cluster-randomized), **seeded reproducible randomization**, blocking/stratification, replication-vs-pseudoreplication, run-order randomization against drift, sequential/adaptive designs.
- **Concrete Hermes gap:** ExperimentSpec is architectural (v6 §28/§8: `pre_registration_hash`, `analysis_plan`, baseline binding) but the *design-generation procedure* — the deterministic layouts, randomization schedules, pseudoreplication checks — has no implementation. The source provides real procedures, not prose.
- **Existing overlap:** `ExperimentSpecification` (v6 §28), pre-registration, methodology/statistical gates, replication.
- **Architectural fit:** EXCELLENT with the mandatory boundary — **the skill designs; it does not approve.**
- **Determinism:** seeded layouts, factorial matrices, randomization schedules are deterministic computation. Design *selection* is LLM judgment bounded by the skill; design *validity* is deterministic validation.
- **Security:** numpy/pandas/pyDOE3 — MODERATE dependency burden, controlled tool deps only. LIGHT-MODERATE risk.
- **License:** MIT. **Phase:** P8.
- **Disposition:** **REIMPLEMENT AS HERMES P8 SKILL** — the DOE/randomization CLIs are genuine reusable procedure (seeded schedules mesh with Hermes reproducibility). The skill produces an **ExperimentSpec proposal**; deterministic validator + pre-registration + human/gateway control execution. Never approves, never executes.

### 3.3 Statistical Analysis — **REIMPLEMENT AS HERMES SKILL SPLIT FROM THE STATISTICAL ENGINE**

- **Source location:** `skills/statistical-analysis/` (SKILL.md 446 lines; `references/` 5 files: assumptions_and_diagnostics, bayesian_statistics, effect_sizes_and_power, reporting_standards, test_selection_guide; `scripts/assumption_checks.py`).
- **What it actually provides:** test-selection guidance, assumption checking, effect sizes, power, Bayesian alternatives, APA reporting, diagnostics.
- **Concrete Hermes gap:** Statistical Engine / Statistical Gate are architectural (v6 §28), not implemented. The source's *procedural structure* (question → data inspection → test selection → assumptions → effect size → uncertainty → reporting) is genuinely useful methodology content.
- **Existing overlap:** v6 `StatisticalAnalysisTool`/`StatsAdapter`/Statistical Gate (architectural), pre-registered `analysis_plan` (M4).
- **Critical boundary:** **three-way split — skill (methodology/interpretation guidance) ≠ StatsAdapter (computation) ≠ Statistical Gate (deterministic compliance decision).** The skill must never emit "p < .05 → supported." Gate decisions are deterministic; significance is never an LLM judgment.
- **Determinism:** computation + gate = deterministic; interpretation = LLM judgment, labeled.
- **Security:** scipy/pingouin/statsmodels/pandas/seaborn/matplotlib (+PyMC for Bayesian) — HEAVY dependency burden. Controlled tool dependencies only; never Hermes core.
- **License:** MIT. **Phase:** P8/P9.
- **Disposition:** **REIMPLEMENT AS HERMES SKILL** — harvest the methodology (test selection, assumption workflow, effect sizes, power, reporting standards) as a skill that **proposes** an analysis plan; computation via the StatsAdapter; gate decision deterministic. Defer until the Statistical Engine slice lands.

### 3.4 Peer Review — **MERGE INTO ADVERSARY (peer-review mode + deterministic CLIs)**

- **Source location:** `skills/peer-review/` (SKILL.md 288 lines; 8 stdlib-only CLIs; 9 asset templates incl. claim_evidence_matrix, reporting_checklist, statistical_reproducibility; 396-line tests).
- **What it actually provides:** authorization/confidentiality gating, claim→evidence matrix, methods/statistics/reproducibility review, citation audit, reporting-guideline selection, actionable review format, separation of review findings from editorial decisions.
- **Concrete Hermes gap:** PARTIAL — the Adversary already owns this class of work (`HYPOTHESIS_CRITIQUE`/`METHODOLOGY_REVIEW`/`ROBUSTNESS_REVIEW`/`RESULT_REVIEW`/`REPORT_REVIEW` task variants, v6 §13/§712). What's missing is the **structured review checklist/template content** and the **deterministic CLI checks** (claim↔evidence validation, citation audit, statistics-reproducibility audit).
- **Existing overlap:** Adversary profile + task variants; CONTRA; ResearchChallenge; Evidence Ladder.
- **Architectural fit:** EXCELLENT as an Adversary **mode/skill**, not a new agent.
- **Determinism:** the CLIs (validate_claim_evidence, audit_citations, audit_statistics_reproducibility) are deterministic checks; the review *judgment* is the Adversary's LLM work, artifact-cited.
- **Security:** stdlib-only, local-only CLIs — LIGHT. The **confidentiality boundary** for unpublished manuscripts is worth adopting as a Tool/Agent Runtime policy verbatim.
- **License:** MIT. **Phase:** P11.
- **Disposition:** **MERGE INTO EXISTING ADVERSARY** as a peer-review skill mode; adopt the deterministic CLIs behind the Tool Runtime; adopt the confidentiality policy. No new component.

### 3.5 Scientific Critical Thinking — **ADOPT IN REDUCED FORM, MERGE INTO ADVERSARY + CONTRA**

- **Source location:** `skills/scientific-critical-thinking/` (SKILL.md 180 lines; **references only — no scripts**; `references/` 7 files: common_biases, core_capabilities, evidence_hierarchy, experimental_design, logical_fallacies, scientific_method, statistical_pitfalls).
- **What it actually provides:** structured evidence-grading frameworks (GRADE, Cochrane Risk of Bias), bias/confounding taxonomy, causal-vs-association checks, alternative explanations, evidence hierarchy, logical fallacies, statistical pitfalls.
- **Concrete Hermes gap:** PARTIAL — almost everything maps onto existing Hermes machinery (Adversary, contradiction contextualization, ResearchAssumption, ResearchChallenge, Evidence Ladder, nine integrity gates). **The genuine gap is the structured review checklist/rubric content** — a reusable, deterministic taxonomy for the Adversary's standing checklist.
- **Existing overlap:** Adversary + CONTRA (§29) + ResearchAssumption + ResearchChallenge + Evidence Ladder — heavy overlap.
- **Architectural fit:** GOOD as content feeding the Adversary's review checklists and CONTRA's steelman/context modes.
- **Determinism:** the taxonomies (bias classes, evidence hierarchy) are deterministic structures; the *application* is LLM judgment bounded by the skill. The optional visual aids require an external OpenRouter key — **rejected**.
- **Security:** no network for the core; optional schematics path requires external LLM — excluded. LIGHT.
- **License:** MIT. **Phase:** P11.
- **Disposition:** **ADOPT IN REDUCED FORM — HARVEST METHODOLOGY ONLY** (checklist/rubric content into Adversary + CONTRA). No scripts to reuse; the value is the structured critique dimensions, not a new capability.

### 3.6 Literature Review — **HARVEST METHODOLOGY ONLY (reimplement inside P7)**

- **Source location:** `skills/literature-review/` (SKILL.md 263 lines; `scripts/` search_databases, verify_citations, generate_pdf, generate_schematic[_ai]; `references/` 5 files).
- **What it actually provides:** systematic-search workflow, multi-database strategy, screening, inclusion/exclusion, exclusion reasons, deduplication, citation verification, PRISMA reporting, thematic synthesis, document generation.
- **Concrete Hermes gap:** YES for methodology (search protocol, screening stages, search accounting) — Hermes' P7 literature stack is incomplete. But the source's *pipeline* (parallel-cli orchestration, requests-based citation verification, subprocess PDF generation, mandatory AI figures) is exactly what Hermes must not copy.
- **Existing overlap:** ResearchSourceProvider, LitKG (GR1/GR2), ResearchTaskPlan, provenance, GraphRetrievalService, ReportRenderer.
- **Architectural fit:** GOOD for methodology; REJECT for pipeline. One Hermes literature workflow, not a second engine.
- **Determinism:** search protocol + inclusion/exclusion + dedup + citation verification = deterministic methodology; synthesis = LLM judgment.
- **Security:** **CRITICAL in the repo's own scan (11 findings).** Depends on parallel-web/parallel-cli, requests, subprocess, OpenRouter for figures. Reject the pipeline wholesale.
- **License:** MIT. **Phase:** P7.
- **Disposition:** **HARVEST METHODOLOGY ONLY** — search protocol, screening stages, exclusion reasons, search accounting, citation verification discipline → ResearchTaskPlan / ResearchProgram literature workflow. Reject parallel-cli, AI figures, PDF generation, OpenRouter.

### 3.7 Hypothesis Generation — **REIMPLEMENT AS HERMES SKILL (STRONGEST CANDIDATE)**

- **Source location:** `skills/hypothesis-generation/` (SKILL.md 264 lines; 8 stdlib-only deterministic CLIs: validate_hypothesis_schema, validate_prediction_matrix, lint_causal_claims, check_falsification_controls, check_operationalization, generate_preregistration_scaffold, audit_evidence_ledger; `references/` 10 files incl. causal_inference_and_claims, preregistration_and_open_science, source_ledger, security_validation; 400-line tests).
- **What it actually provides:** **explicit non-negotiable boundary — "never automatically score, rank, select, accept, or reject scientific hypotheses"**; strict separation of observation / research question / hypothesis / mechanism / causal estimand / prediction / alternative explanation / null / negative control / analysis plan; rival explanations + discriminating predictions; declared assumptions; falsification conditions; operationalization; preregistration readiness; causal-claim linting.
- **Concrete Hermes gap:** YES — the ResearchProgram architecture (§28) exists and is implemented, but the *generation procedure* (candidate + rivals + discriminating predictions + falsification conditions, with deterministic schema/prediction-matrix validation) is exactly the missing upstream of the Director's `PROPOSE_RESEARCH_PROGRAM` proposal path.
- **Existing overlap:** Director/ResearchProgram/ResearchProgramValidator (implemented); ResearchClaim/ResearchAssumption substrate (§29, P7).
- **Architectural fit:** EXCELLENT with the mandated chain: `skill → candidate hypotheses/rivals/predictions → Director → ResearchProgramDraft → ResearchProgramValidator → Gateway`. The skill must never create a ResearchProgram, promote evidence, or select research direction.
- **Determinism:** schema validation, prediction-matrix coherence, falsification-control checks, causal-claim linting = deterministic; generation = LLM judgment bounded by the skill.
- **Security:** stdlib-only, local-only, no network, no credentials. LIGHT. The safety/ethics gate language is a useful policy template.
- **License:** MIT. **Phase:** P4/P7 (methodology → P7; the deterministic validators mirror ResearchProgramValidator's discipline).
- **Disposition:** **REIMPLEMENT AS HERMES SKILL — first harvest priority.** Its epistemic discipline is Hermes' own, expressed as reusable procedure + deterministic CLIs.

### 3.8 Scientific Writing — **REIMPLEMENT AS HERMES P12 SKILL + RENDERING/VALIDATION METHODOLOGY**

- **Source location:** `skills/scientific-writing/` (SKILL.md 356 lines; 8 stdlib-only CLIs: validate_manifest, check_consistency (numeric + methods/results reconciliation), audit_claims, check_references, lint_manuscript, scaffold_manuscript, select_reporting_guidelines, validate_authorship; `references/` 12 files; 225-line tests).
- **What it actually provides:** outline-first drafting, **evidence-bound claims with source manifests**, consistency manifests (numeric consistency; methods/results reconciliation), citation verification, reporting-guideline selection, authorship/accountability validation, "submission_ready" human authorization, confidentiality controls.
- **Concrete Hermes gap:** **YES — `ReportRenderer` is a 5-line stub.** The v6 architecture defines the structured-report discipline natively but it is not operational. The evidence-binding and consistency-audit model here is genuinely reusable, not generic writing prose.
- **Existing overlap:** ReportRenderer (stub), ResearchReport, provenance, vault projection, reporting gate.
- **Architectural fit:** EXCELLENT — `research artifacts → ResearchReport → claim/evidence manifest → deterministic consistency checks → ReportRenderer → human/reporting gate`. Never "LLM → polished paper."
- **Determinism:** manifests, consistency checks, reference checks, authorship validation = deterministic; drafting = LLM judgment bounded by the skill.
- **Security:** stdlib-only, local-only CLIs; confidentiality policy for unpublished manuscripts. LIGHT.
- **License:** MIT. **Phase:** P12.
- **Disposition:** **REIMPLEMENT AS HERMES P12 SKILL + VALIDATION METHODOLOGY.** The manifest/consistency/claims-audit discipline materially improves the (currently stubbed) reporting pipeline.

---

## 4. Comparison Matrix

| Candidate | Value | Hermes overlap | Dependency burden | Risk | Phase | Disposition |
|---|---|---|---|---|---|---|
| Paper Lookup | High | Provider port is a stub | LIGHT (stdlib) | LIGHT | P7 | REIMPLEMENT AS HERMES SKILL |
| Experimental Design | High | ExperimentSpec architectural | MODERATE (numpy/pandas/pyDOE3) | LIGHT | P8 | REIMPLEMENT AS HERMES P8 SKILL |
| Statistical Analysis | High | Stats Engine/Gate architectural | HEAVY (scipy/statsmodels/pingouin/PyMC…) | LIGHT (controlled) | P8/P9 | REIMPLEMENT AS HERMES SKILL (split) |
| Peer Review | Medium-High | Adversary owns the class | LIGHT (stdlib CLIs) | LIGHT | P11 | MERGE INTO ADVERSARY |
| Critical Thinking | Medium | Adversary + CONTRA overlap heavily | LIGHT (no scripts) | LIGHT | P11 | ADOPT IN REDUCED FORM (methodology only) |
| Literature Review | Medium | P7 literature stack incomplete | HEAVY (parallel-cli, requests, subprocess) | **HIGH (11 CRITICAL in upstream scan)** | P7 | HARVEST METHODOLOGY ONLY |
| Hypothesis Generation | **Very High** | ResearchProgram implemented; generation thin | LIGHT (stdlib) | LIGHT | P4/P7 | REIMPLEMENT AS HERMES SKILL |
| Scientific Writing | High | ReportRenderer is a 5-line stub | LIGHT (stdlib) | LIGHT | P12 | REIMPLEMENT AS HERMES SKILL + METHODOLOGY |

---

## 5. Recommended Hermes Skill Designs (surviving candidates)

### 5.1 `hypothesis-generation` (first priority — P7)

- **Owner:** Researcher (proposal) → Director (selection) → ResearchProgramValidator (validation).
- **Input contract:** observation/evidence-bound context (schema'd `Source`/claim refs, optional preliminary findings).
- **Output contract:** candidate `Hypothesis` set, each with mechanism, rival explanations, discriminating predictions (prediction matrix), null + negative controls, declared assumptions, falsification conditions, operationalization, preregistration-ready analysis-plan draft.
- **Authority limits:** MUST NOT select the research direction, promote evidence, create a ResearchProgram, create tasks, or mutate state. Its output feeds the Director's `PROPOSE_RESEARCH_PROGRAM` draft path only.
- **Required tools:** the 8 stdlib-only CLIs reimplemented as Hermes-native validators (schema, prediction matrix, causal lint, falsification controls, operationalization, preregistration scaffold, evidence-ledger audit).
- **Required artifacts:** schema'd hypothesis candidates (reuse ResearchClaim/ResearchAssumption substrate refs).
- **Provenance:** `proposed_by: hypothesis-generation-skill`, model ref, source refs behind every claim; candidates are proposals, never evidence.
- **Model boundary:** generation is LLM judgment; every structural check (matrix coherence, falsification, causal-claim lint) is deterministic code.
- **Permissions:** read artifact refs; write to proposal drafts via the ordinary intent path; no direct repository/task writes.
- **Tests:** golden fixtures — candidate set → prediction-matrix validator; malformed matrix rejected; falsification-condition completeness; causal-claim lint (correlation≠causation); "never auto-select" structural test.
- **Phase:** P7.

### 5.2 `paper-lookup` (P7)

- **Owner:** Researcher/Implementer via ResearchSourceProvider (Hermes-owned port).
- **Input contract:** bounded retrieval request (identifiers, topic, constraints).
- **Output contract:** schema'd `Source` records with provider, query, parameters, identifiers, access timestamp, retrieval reconciliation, provenance to repeat.
- **Authority limits:** read-only retrieval; the result becomes structured evidence/provenance/artifacts only through the existing write path (never free-form LLM answer as evidence).
- **Required tools:** Hermes provider abstraction + thin adapters (PubMed/PMC/EuropePMC/arXiv/OpenAlex/Crossref/Semantic Scholar/CORE/Unpaywall/bioRxiv/medRxiv), pagination + reconciliation, JATS/Atom parsing, redaction.
- **Required artifacts:** `Source` records; optional raw payload artifacts (content-hashed).
- **Provenance:** provider, endpoint, parameters, identifiers, access date, reconciliation counts.
- **Model boundary:** retrieval/parsing/reconciliation deterministic; query intent interpretation is LLM judgment bounded by the skill; every response treated as untrusted third-party data (instruction-injection boundary).
- **Permissions:** network to the provider allowlist only; rate-limit policy enforced by the Tool Runtime; no credentials in logs.
- **Tests:** golden fixtures — HTTP-200 malformed responses (arXiv "Error" entry, PMC empty body, EuropePMC errCode) rejected; reconciliation shortfall exits with a typed failure; identifier normalization; redaction; dedup.
- **Phase:** P7.

### 5.3 `experimental-design` (P8)

- **Owner:** Researcher (proposal) → deterministic ExperimentSpec validator → pre-registration → human/gateway-controlled execution.
- **Input contract:** research question, factors, units, constraints, existing data context.
- **Output contract:** ExperimentSpec proposal — design type, seeded randomization schedule, blocking/stratification plan, replication structure, run order, sample-size/power pointer, pseudoreplication check.
- **Authority limits:** never approves, never executes; proposal only.
- **Required tools:** DOE generators (factorial/fractional/CCD/Box–Behnken/Latin hypercube) and seeded RNG behind a Hermes adapter (pyDOE3 is a controlled tool dep).
- **Tests:** seeded reproducibility (same seed → same layout), pseudoreplication detection, run-order randomization, design validity checks.
- **Phase:** P8.

### 5.4 `statistical-analysis` (P8/P9)

- **Owner:** Researcher proposes; StatsAdapter computes; Statistical Gate decides.
- **Input contract:** pre-registered `analysis_plan`, dataset refs, candidate results.
- **Output contract:** proposed analysis (test selection, assumptions, effect sizes, uncertainty) → adapter output → gate verdict. Never "p < .05 → supported."
- **Tests:** test-selection workflow against golden datasets; assumption-check ordering; effect-size/power correctness; the structural "skill cannot emit a gate verdict" test.
- **Phase:** P8/P9 (deferred to the Statistical Engine slice).

### 5.5 `peer-review` (P11) and 5.6 `critical-thinking` (P11)

- **Owner:** Adversary profile (modes/templates, not new agents).
- **Content:** claim↔evidence matrix, reporting checklists, statistical-reproducibility template, citation audit, bias/evidence taxonomy (GRADE/Cochrane ROB), causal-vs-association checks.
- **Authority limits:** review findings are critiques (PASS/FAIL/PASS_WITH_CONCERNS), artifact-cited; never a gate verdict or evidence promotion by themselves.
- **Security:** adopt the upstream confidentiality boundary (unpublished manuscripts never leave the authorized processing context) as Tool/Agent Runtime policy.
- **Phase:** P11.

### 5.7 `scientific-writing` (P12)

- **Owner:** Researcher drafts; ReportRenderer renders; reporting gate + human approve.
- **Input contract:** research artifacts + claim/evidence source manifest.
- **Output contract:** structured report with claim↔evidence manifest, numeric-consistency + methods/results reconciliation checks, citation verification, reporting-guideline coverage, authorship record, "submission_ready" human gate.
- **Authority limits:** drafting is LLM-bounded; every consistency/reference/authorship check is deterministic; human authorization required for submission.
- **Phase:** P12 (deferred to the ReportRenderer slice; the deterministic CLI discipline can land early as tool content).

---

## 6. Rejected / Deferred Candidates (and rejected parts)

| Item | Verdict | Why |
|---|---|---|
| Literature Review *pipeline* (parallel-cli, search_databases, generate_pdf, generate_schematic_ai) | REJECT | Second orchestration surface; subprocess/requests/OpenRouter; **11 CRITICAL findings in upstream's own scan**; Hermes owns its P7 literature workflow. |
| Mandatory AI-generated figures (literature-review, critical-thinking optional path) | REJECT | Presentation policy, not a research-control primitive; external-LLM dependency. |
| Statistical-analysis package ecosystem as Hermes deps | REJECT (as core) | scipy/statsmodels/pingouin/PyMC are controlled tool dependencies behind StatsAdapter, never architecture deps. |
| experimental-design numpy/pandas/pyDOE3 as core deps | REJECT (as core) | Controlled tool deps only. |
| Direct Write/Edit model of several upstream skills | REJECT | Hermes bounds writes via Tool Runtime + artifact/write-path rules. |
| External LLM usage for peer-review/writing steps | REJECT | Hermes' context/security policy is the authority; model calls go through ModelClient with record/replay. |
| The source's orchestration/skill-invocation model (parallel-cli, cross-skill composition) | REJECT | Reconcile/Task Graph/Gateway/Controller already own execution. |
| Full adoption of any skill wholesale (all 8) | REJECT | Every surviving candidate is reimplemented or merged, never imported. |
| **Critical Thinking as a standalone skill** | DEFER/ADOPT-REDUCED | Value is checklist content; fold into Adversary + CONTRA when those slices land. |

---

## 7. Architecture Changes Required

**ZERO new architectural components.** This is the required outcome and it holds. Every harvest lands inside existing ratified surfaces:

- `ResearchSourceProvider` (§15/§27) — must move from stub to implementation (the paper-lookup/literature-review harvest is the content for it).
- `ReportRenderer` (§15/§27) — must move from stub to implementation (scientific-writing manifest/consistency discipline is the content).
- `ExperimentSpec` / Statistical Engine / Statistical Gate (§28) — already ratified; the experimental-design and statistical-analysis skills fill the *proposal/methodology* side.
- Adversary (P11) — peer-review/critical-thinking become modes/templates inside the existing profile; no new agent.
- ResearchProgram + Validator (implemented) — hypothesis-generation feeds the Director proposal path; the deterministic CLIs mirror validator discipline.
- SkillRecord (PA3) — the harvesting mechanism already exists in the architecture (§13/§16.6/§20/§27 item PA3): external skill → source/license/version → Hermes-native definition → tests → Engineering Plane admission → SkillRecord → Tool/Agent Runtime. Nothing new is required to adopt these skills; the engineering-plane admission is the *only* way in.

---

## 8. Harvest Strategy

| Candidate | Harvest | Not harvested |
|---|---|---|
| Paper Lookup | **IDEAS + REFERENCE CONTENT** (failure catalog per provider, reconciliation/redaction discipline) | scripts verbatim (providers owned by Hermes adapters) |
| Experimental Design | **IDEAS + PROCEDURE** (seeded DOE/randomization; pseudoreplication checks) | pyDOE3 as core (tool dep only) |
| Statistical Analysis | **METHODOLOGY** (test selection, assumptions, effect sizes, power, reporting) | package ecosystem; any gate decision |
| Peer Review | **IDEAS + DETERMINISTIC CLI CHECKS** (claim↔evidence, citation, reproducibility audit) + confidentiality policy | new agent |
| Critical Thinking | **METHODOLOGY ONLY** (taxonomies, evidence grading) | scripts (none exist), external schematics |
| Literature Review | **METHODOLOGY ONLY** (search protocol, screening, search accounting, citation verification) | pipeline, parallel-cli, AI figures, PDF gen |
| Hypothesis Generation | **IDEAS + DETERMINISTIC CLI PATTERNS** (validators, linter, scaffold) — reimplemented | direct ResearchProgram creation |
| Scientific Writing | **IDEAS + DETERMINISTIC CLI PATTERNS** (manifests, consistency, authorship) | generic prose prompts; external services |

**Rule applied throughout:** HARVEST CODE only where it is stdlib-only, deterministic, and Hermes-shaped (the peer-review/hypothesis-generation/writing CLIs); REIMPLEMENT where Hermes must own the behavior (providers, engine, gate, renderer); IDEAS-ONLY where the value is methodology content (critical thinking, literature-review protocol, statistical methodology).

---

## 9. Supply-Chain Requirements

- **Version pin:** record the audited source HEAD (`5ad4aae7`) in every harvested SkillRecord's provenance; re-audit on version bump.
- **License:** MIT — permits reimplementation and derivative content; record license + attribution in the SkillRecord (PA3 requires `license` + `content_hash` + `provenance`).
- **Dependencies:** stdlib-only for harvested CLIs (reimplemented); any external package (pyDOE3, scipy family) is a **controlled tool dependency behind a Hermes adapter**, version-pinned, never a project/architecture dependency.
- **Network:** provider adapters use an allowlisted endpoint set with rate-limit policy enforced by the Tool Runtime; no credentials in logs (redaction); external-LLM steps only via ModelClient (record/replay).
- **Security:** every harvest re-runs the upstream triage against Hermes' own threat model; **"upstream CI passed" is never sufficient** — the literature-review CRITICALs are the proof.
- **Reproducibility:** all deterministic CLIs and fixtures must be replayable offline; seeded RNG where design generation is involved.

---

## 10. Phase Placement

| Candidate | Phase | Gate |
|---|---|---|
| Paper Lookup | **P7** | ResearchSourceProvider implementation |
| Literature Review (methodology) | **P7** | ResearchTaskPlan / literature workflow |
| Hypothesis Generation | **P4/P7** | ResearchProgram proposal path (ResearchProgramValidator exists now) |
| Experimental Design | **P8** | ExperimentSpec slice |
| Statistical Analysis | **P8/P9** | Statistical Engine/Gate slice |
| Peer Review | **P11** | Adversary modes |
| Critical Thinking | **P11** | Adversary + CONTRA |
| Scientific Writing | **P12** | ReportRenderer slice (deterministic CLI discipline can land earlier as tool content) |

---

## 11. Acceptance-Test Plan (per adopted skill, Hermes golden-fixture style)

For every harvested skill: golden scenario; deterministic expected output where applicable; malformed input; adversarial input; provenance expectation; permission expectation; network/dependency assumptions; replay behavior. Highlights:

- **hypothesis-generation:** a candidate set whose prediction matrix is incoherent → deterministic `INVALID` (not an LLM judgment); a causal claim linted as "association ≠ causation"; falsification-condition completeness; the **structural never-auto-select test** (no path from skill output to ResearchProgram admission except via Director + Validator + Gateway).
- **paper-lookup:** HTTP-200 malformed provider payloads (arXiv "Error" entry, PMC empty body, EuropePMC errCode, crossref cursor trap) → typed failures, never silent empty results; reconciliation shortfall → exit code; identifier normalization; credential redaction; dedup; rate-limit behavior.
- **experimental-design:** same-seed → identical layout (reproducibility); pseudoreplication detected; run-order randomization against drift; proposal-without-approval structural test.
- **statistical-analysis:** test-selection workflow on golden datasets; assumption-check ordering; effect-size/power correctness; **skill cannot emit a gate verdict** structural test.
- **peer-review / critical-thinking:** claim↔evidence matrix completeness; citation-audit correctness; confidentiality boundary (unpublished manuscript never leaves authorized context); findings are critiques, never gates.
- **scientific-writing:** claim↔evidence manifest completeness; numeric consistency; methods/results reconciliation; citation verification; authorship validation; "submission_ready" human gate; no evidence fabrication path.

---

## 12. Final Decision

| Candidate | Decision |
|---|---|
| Paper Lookup | **REIMPLEMENT AS HERMES SKILL** (P7) |
| Experimental Design | **REIMPLEMENT AS HERMES P8 SKILL** |
| Statistical Analysis | **REIMPLEMENT AS HERMES SKILL** (split: skill / StatsAdapter / Statistical Gate) |
| Peer Review | **MERGE INTO EXISTING ADVERSARY** (mode + deterministic CLIs + confidentiality policy) |
| Scientific Critical Thinking | **ADOPT IN REDUCED FORM** — methodology only, into Adversary + CONTRA |
| Literature Review | **HARVEST METHODOLOGY ONLY** — reimplement inside P7 |
| Hypothesis Generation | **REIMPLEMENT AS HERMES SKILL** — first priority |
| Scientific Writing | **REIMPLEMENT AS HERMES P12 SKILL + VALIDATION METHODOLOGY** |

**None imported wholesale. Zero new authorities, schedulers, memories, evidence paths, or uncontrolled dependencies.** The end state is a small, high-quality Hermes-owned skill library admitted through the PA3 engineering plane — never the 161-skill collection as a runtime surface.

---

## 13. Cross-reference against the user's reference review

The reference review supplied by the user was read after this audit's per-candidate work was drafted. The two are **substantively aligned on all eight dispositions**; the disagreements below are sharpenings, not reversals.

### 13.1 Consensus (8/8)

| Candidate | This audit | Reference review | Agreement |
|---|---|---|---|
| Paper Lookup | REIMPLEMENT as Hermes skill | ADOPT / REIMPLEMENT | ✅ |
| Experimental Design | REIMPLEMENT as P8 skill | REIMPLEMENT as P8 skill | ✅ |
| Statistical Analysis | REIMPLEMENT, split skill/engine/gate | ADOPT, split skill/engine/gate | ✅ |
| Peer Review | MERGE into Adversary | MERGE into Adversary | ✅ |
| Critical Thinking | ADOPT REDUCED — methodology into Adversary/CONTRA | ADOPT REDUCED — merge into Adversary/CONTRA | ✅ |
| Literature Review | HARVEST METHODOLOGY ONLY | HARVEST METHODOLOGY + reimplement in P7 | ✅ |
| Hypothesis Generation | REIMPLEMENT as Hermes skill (first priority) | ADOPT methodology, native skill | ✅ |
| Scientific Writing | REIMPLEMENT as P12 skill + methodology | ADOPT, high value | ✅ |

### 13.2 Where this audit sharpens the reference review (no reversals)

1. **Paper Lookup — "steal" is content, not code.** The reference lists harvestable items (database selection, quiet-failure detection, etc.) without distinguishing *what* to take. This audit is more specific: the **per-provider failure catalog is reference content** (the crown jewels), the pagination/reconciliation code is *ideas* to reimplement because Hermes' adapters must own per-provider cursor logic. Importing the scripts would import the provider-specific logic that the Hermes port must own anyway.
2. **Literature Review — the rejection is stronger than the reference implies.** The reference rejects the orchestration and AI figures; this audit adds the decisive fact: **11 CRITICAL findings in the upstream's own security scan** on this skill, plus subprocess PDF generation and OpenRouter dependencies. This upgrades "don't copy the pipeline" to "the pipeline is the thing that must never touch Hermes," while keeping the methodology harvest.
3. **Peer Review — the deterministic CLIs are reusable near-verbatim.** The reference correctly says "merge, not new agent," but under-notes that `validate_claim_evidence`, `audit_citations`, and `audit_statistics_reproducibility` are **stdlib-only deterministic checks** — the rare case where HARVEST CODE (behind the Tool Runtime) rather than reimplement is justified. Critical Thinking, by contrast, has **no scripts at all** — pure taxonomy harvest. The reference treats them similarly; this audit separates them on the code-vs-content axis.
4. **Critical Thinking — evidence-grading is deterministic structure.** Both agree it's methodology-only. This audit adds that GRADE / Cochrane ROB taxonomies are **deterministic structures** (the taxonomy is code-able even if application is LLM judgment) — worth encoding as a checklist schema, not just prose.
5. **The unifying claim both reach:** the three chains (Hypothesis→Design→Statistics; Literature→Adversary→Peer Review; Evidence→Writing→Report) are the real value, and Hermes' v6 spine already exists for all three. This audit confirms that from the live code: the spine is real (ResearchProgram, Task Graph, Gateway, Controller, claim/assumption substrate all implemented; suite 571 green) — and the *stubs* (ResearchSourceProvider, ReportRenderer) are exactly where the first harvest should land.

### 13.3 Independent findings the reference review does not emphasize

- **The stub-vs-architecture distinction determines sequencing.** Paper Lookup and Scientific Writing address *implemented-but-empty* ports, so their harvests are actionable now (methodology content can land immediately); Experimental Design / Statistical Analysis / Peer Review / Critical Thinking address *architectural-only* surfaces and should be encoded when their slices land. The reference lists phases but does not surface this sequencing rule.
- **The hypothesis-generation CLIs are the template for Hermes' own validator discipline.** Their pattern — deterministic schema/matrix/lint checks that make *structural* epistemic violations fail in code — should be mirrored in ResearchProgramValidator and the claim/assumption validators, not just wrapped as a skill. This is a code-level harvest recommendation the reference implies but does not state.
- **Dependency-weight as a decision rule worked.** The single candidate with a HEAVY ecosystem and HIGH risk (Literature Review) is also the one the upstream scan flags CRITICAL — the qualitative cost/benefit rule in this audit's §4 predicted the security outcome. The rule should be applied to every future harvest.

---

*This document is an architecture-design audit; it changes no ratified text. Any adoption proceeds through the normal PA3 engineering-plane admission (IDR + implementation + tests + review), never as a runtime import.*
