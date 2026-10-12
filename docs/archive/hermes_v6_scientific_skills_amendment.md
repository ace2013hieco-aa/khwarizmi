# HERMES × SCIENTIFIC AGENT SKILLS — V6 ARCHITECTURE INTEGRATION AMENDMENT

**Date:** 2026-08-13
**Nature of this document:** DESIGN-ONLY. It changes no ratified text, adds no code, no dependencies, no skills, no runtime surface, and no Git commits. It is the protest + amendment design phase that precedes any adoption.
**Inputs:** `hermes_scientific_agent_skills_audit.md` (the independent source audit, HEAD `5ad4aae7`, v2.63.0, MIT, 161 skills) + the live Hermes repository + `hermes_research_architecture_v6.md` (RATIFIED §1–§28; CONTRA candidate §29).

---

## A. Baseline

| Fact | Value |
|---|---|
| Hermes HEAD | `4b2a7ce` (CI: archive a pytest-cov coverage report; `main` in sync with `origin/main`) |
| v6 status | RATIFIED for §1–§28 (IDR-023; §27 item 43 closure gate closed); §29 CONTRA candidate — P7 substrate + write path + extraction pipeline + controller IMPLEMENTED + TESTED; everything else in §29 DESIGNED |
| Test baseline | **571 passed, 0 failed, exit 0** (re-run fresh this session, isolated runner, 7.93 s) |
| Source repository | `https://github.com/ace2013hieco-aa/scientific-agent-skills` |
| Source HEAD | `5ad4aae76bc40257b914367afacc6fd686a282d5` — **verified unchanged via `git ls-remote` this session** (2026-08-13); matches the audit |
| Source version | v2.63.0 |
| Source license | MIT (K-Dense Inc.) |
| Source collection | 161 skills; per-skill front-matter (version, author, license, allowed-tools), per-skill pytest suites, spec-validation + security-scan CI |
| Key live-repo facts | `src/hermes/tools/research_sources.py` = 4-line stub; `src/hermes/tools/reporting.py` = 5-line stub; no `src/hermes/skills/` and no `SkillRecord` code (PA3 is ratified as design, not yet implemented); `ExperimentSpec`/`StatsAdapter`/`Statistical Gate`/Adversary modes are architectural (§28/§12/§13), not yet operational beyond the ratified slices |
| Source facts re-verified this session | hypothesis-generation `SKILL.md:34` — "automatically score, rank, select, accept, or reject scientific hypotheses" is explicitly excluded; the high-value CLIs import only the standard library (`argparse`, `re`, `collections`, `xml.etree`, `pathlib`, `typing`, cross-script `from validate_hypothesis_schema import …`); paper-lookup carries 11 per-provider reference files (arxiv, biorxiv, core, crossref, europepmc, medrxiv, openalex, pmc, pubmed, semantic-scholar, unpaywall) |

---

## B. Architecture Protest (candidate-by-candidate)

The mandated protest, answered for all eight candidates before any adoption decision. The five-part structure is applied uniformly.

### B.1 Paper Lookup

- **A. What concrete Hermes problem does this solve?** P7 literature retrieval is a ratified port with an empty implementation. `ResearchSourceProvider` is a 4-line stub; the v6 §15 contract (`search`/`fetch`/`extract` + thin adapters) has no content behind it. The source supplies a decade of per-provider API failure semantics that Hermes would otherwise rediscover provider by provider.
- **B. Does Hermes already solve it?** The *abstraction* is ratified (§15); the *capability* is not operational. So this is an implementation-gap fill, not a new capability class.
- **C. What is the source adding?** Reference content (the per-provider failure catalog — HTTP-200 failures, cursor traps, silent rewrites), deterministic computation patterns (pagination + retrieved-vs-total reconciliation, identifier normalization, URL redaction, JATS/Atom parsing), and an explicit instruction-injection boundary. Not new architecture.
- **D. Fit inside an existing component?** Yes — the §15 provider port + Tool Runtime + a `paper-lookup` SkillRecord. The adapter logic is Hermes-owned by ratified text (§15, §22: nothing vendored).
- **E. Does it create a new authority / scheduler / pipeline / memory / evidence path / dependency ecosystem / uncontrolled network surface?** No new authority: retrieval is read-only, and results are admitted as `Source` records + artifacts + provenance only through the existing write path. Network is a bounded provider allowlist with Tool Runtime rate-limit policy. No new dependency: the upstream scripts are stdlib-only and reimplemented anyway.
- **F. Now, later, or not at all?** DESIGN now; implementation belongs to P5 (provider port) / P7 (literature execution). The failure catalog is usable content immediately, but no adapter runs before the Tool Runtime rate-limit policy and provider allowlist are ratified (§27 item 55).

### B.2 Literature Review

- **A. Problem?** Hermes' P7 literature stack is incomplete: no encoded systematic-search protocol (declared databases + queries, inclusion/exclusion criteria with reasons, screening stages, deduplication rules, search accounting, citation verification).
- **B. Already solved?** Partially — `ResearchTaskPlan`, `ResearchProgram` obligations, LitKG, provenance, and GraphRetrievalService exist as the *surfaces*; the *methodology* (how a search is declared, screened, and accounted) is not encoded anywhere.
- **C. Source adds?** Methodology only. The source's *pipeline* (parallel-cli orchestration, requests-based citation verification, subprocess PDF generation, mandatory AI figures, OpenRouter) is rejected wholesale — it carries 11 CRITICAL findings in the upstream's own security scan.
- **D. Fit?** Inside `ResearchTaskPlan` / the P7 literature workflow / a `literature-review` SkillRecord (methodology). One Hermes literature workflow — never a second engine.
- **E. New authority etc.?** No — provided the pipeline rejection is total. The methodology is deterministic structure (protocol, screening, accounting) + model judgment (synthesis), both bounded by existing artifacts.
- **F. Now/later?** P7, alongside Paper Lookup (the protocol presumes the retrieval layer).

### B.3 Hypothesis Generation

- **A. Problem?** The `ResearchProgram` epistemic contract (§28.2) is implemented, and the Director's `PROPOSE_RESEARCH_PROGRAM` proposal path exists — but the *generation procedure* upstream of the Director is thin. Nothing structurally produces candidate hypotheses with rival explanations, discriminating predictions, declared assumptions, falsification conditions, and preregistration-ready analysis plans.
- **B. Already solved?** Partially — `ResearchProgramValidator` validates drafts (E1–E5, governance, identity). The *generation* side has no procedure.
- **C. Source adds?** Capability + deterministic CLI patterns. Its explicit boundary — never score/rank/select/accept/reject hypotheses — is Hermes' own epistemic discipline. The 8 CLIs (schema validation, prediction-matrix coherence, causal-claim lint, falsification controls, operationalization, preregistration scaffold, evidence-ledger audit) are stdlib-only, deterministic, local-only.
- **D. Fit?** A Researcher skill feeding the Director's proposal path; the deterministic CLIs as Tool Runtime utilities. The ResearchClaim/ResearchAssumption substrate (§29, implemented) can carry the extracted-claim context the generation reads.
- **E. New authority?** No — with one structural guard the amendment makes explicit: the skill's checks are **pre-flight advisories** on a `ResearchProgramDraft`; `ResearchProgramValidator` remains the sole authority that can produce `COMPILED`. The skill can neither admit nor reject a program (§30.2 rule 3). No change to the ratified E1–E5 checks.
- **F. Now/later?** First harvest priority. DESIGN now; implementation at P4/P7 (the surrounding authority — the validator, the gateway wiring, the proposal variant — is already operational from the ratified v6 slices).

### B.4 Experimental Design

- **A. Problem?** `ExperimentSpec` is architectural (v6 §28/§8: `pre_registration_hash`, `analysis_plan`, baseline binding); the *design-generation* procedure — deterministic DOE layouts, seeded randomization schedules, blocking/stratification plans, pseudoreplication checks — has no implementation.
- **B. Already solved?** No — nothing generates or validates designs.
- **C. Source adds?** Real procedure: full/fractional factorial, Plackett–Burman, CCD, Box–Behnken, Latin hypercube, crossover/repeated measures, split-plot, cluster designs; seeded reproducible randomization; pseudoreplication detection; run-order randomization against drift. Seeded schedules mesh with Hermes' reproducibility model.
- **D. Fit?** A Researcher skill producing `ExperimentSpec` proposals; DOE/randomization generators behind a Hermes adapter (pyDOE3/numpy as controlled tool dependencies).
- **E. New authority?** No — the boundary is "design, never approve": the skill produces a proposal; the deterministic ExperimentSpec validator, pre-registration, and human/Gateway-controlled execution own everything after.
- **F. Now/later?** P8, when the ExperimentSpec + validator + pre-registration slice lands.

### B.5 Statistical Analysis

- **A. Problem?** The Statistical Engine / Statistical Gate are architectural (v6 §28, §12, P9), not implemented. The *methodology* layer (test selection, assumption checking, effect sizes, power, reporting standards) has no content.
- **B. Already solved?** The *contracts* exist (`StatisticalAnalysisTool`, `StatsAdapter`, Statistical Gate, pre-registered `analysis_plan`). The *procedure* does not.
- **C. Source adds?** Methodology + a procedural structure (question → data inspection → test selection → assumptions → effect size → uncertainty → reporting) and assumption-check scripting.
- **D. Fit?** With the mandatory **three-way split**: skill (methodology/interpretation guidance) ≠ `StatsAdapter` (computation) ≠ Statistical Gate (deterministic compliance decision). The skill must never emit "p < .05 → supported."
- **E. New authority?** No — the split *prevents* the skill from becoming one. Gate decisions stay deterministic and owned by the gate.
- **F. Now/later?** P8/P9 — deferred until the StatsAdapter + Statistical Gate slice lands. The methodology content is designed now; the skill cannot be meaningfully implemented before the engine it advises exists.

### B.6 Peer Review

- **A. Problem?** PARTIAL — the Adversary already owns this class of work (`HYPOTHESIS_CRITIQUE` / `METHODOLOGY_REVIEW` / `ROBUSTNESS_REVIEW` / `RESULT_REVIEW` / `REPORT_REVIEW`, §13). Missing: the structured review content (claim↔evidence matrix, reporting checklists, statistical-reproducibility template) and the deterministic audit CLIs, plus a confidentiality policy for unpublished manuscripts.
- **B. Already solved?** The *agent class* is solved; the *review tooling/content* is not.
- **C. Source adds?** Deterministic CLI checks (`validate_claim_evidence`, `audit_citations`, `audit_statistics_reproducibility` — stdlib-only), template content, and a confidentiality boundary.
- **D. Fit?** Inside the Adversary as a **mode + skill package**; the CLIs behind the Tool Runtime; the confidentiality policy into Tool/Agent Runtime policy. Never a `PeerReviewAgent`.
- **E. New authority?** No — findings remain `Critique` artifacts (PASS/FAIL/PASS_WITH_CONCERNS, gate-blocking only via existing Critique verdict semantics), artifact-cited.
- **F. Now/later?** P11.

### B.7 Scientific Critical Thinking

- **A. Problem?** Almost everything maps onto existing Hermes machinery (Adversary, contradiction contextualization, `ResearchAssumption`, `ResearchChallenge`, Evidence Ladder, the nine integrity gates). The genuine gap is the **structured review checklist/rubric content** — GRADE / Cochrane Risk-of-Bias structures, a bias/confounding taxonomy, causal-vs-association checks, an evidence hierarchy, logical-fallacy and statistical-pitfall catalogs.
- **B. Already solved?** The *capabilities* yes; the *content* no.
- **C. Source adds?** Methodology/checklist content only — it has **no scripts at all** (references only). The taxonomies are deterministic *structures*; their *application* is model judgment.
- **D. Fit?** As content feeding the Adversary's standing checklist and CONTRA's steelman/context modes (§29).
- **E. New authority?** No — with the guard that a checklist is never an evidence gate by itself; only the v6-authorized mechanisms may gate.
- **F. Now/later?** P11 (fold into Adversary + CONTRA).

### B.8 Scientific Writing

- **A. Problem?** `ReportRenderer` is a 5-line stub; the structured-report discipline (§15 staged verification) is ratified but not operational. The source's evidence-binding model (source manifests, claim↔evidence manifests, numeric consistency, methods/results reconciliation, citation verification, authorship/accountability, `submission_ready` human authorization, uncertainty preservation) is genuinely reusable procedure — not generic prose guidance.
- **B. Already solved?** The *contract* (staged `ResearchReport` → deterministic renderer → reporting gate) is ratified; the *implementation and the manifest discipline* are not.
- **C. Source adds?** Capability + deterministic CLI patterns (manifest validation, consistency checks, claims audit, reference checks, authorship validation, reporting-guideline selection).
- **D. Fit?** ResearchReport schema enrichment (manifest fields), deterministic reporting validators, ReportRenderer procedures, a `scientific-writing` skill for the drafting task, and the human `submission_ready` authorization on the existing Reporting gate.
- **E. New authority?** No — drafting is LLM-bounded; every consistency/reference/authorship check is deterministic; human authorization is required for submission. No fabrication path exists structurally.
- **F. Now/later?** P12 (the deterministic CLI discipline can land as tool content when P5's `ReportRenderer` lands).

---

## C. Candidate Decisions

| # | Candidate | Disposition | Rationale (one line) |
|---|---|---|---|
| 1 | Paper Lookup | **REIMPLEMENT AS HERMES SKILL** (P7) | Ratified provider port is an empty stub; harvest the failure catalog as content, reimplement the abstraction Hermes already owns |
| 2 | Literature Review | **HARVEST METHODOLOGY ONLY** (P7) | Search protocol/screening/accounting are missing methodology; the source's own pipeline is CRITICAL-flagged and rejected |
| 3 | Hypothesis Generation | **REIMPLEMENT AS HERMES SKILL** — first priority (P4/P7) | The missing upstream of the Director's proposal path; its never-auto-select boundary is Hermes' own discipline |
| 4 | Experimental Design | **REIMPLEMENT AS HERMES P8 SKILL** | Seeded DOE/randomization procedures fill the empty design-generation slot; proposal-only |
| 5 | Statistical Analysis | **REIMPLEMENT AS HERMES SKILL** (P8/P9), split skill / StatsAdapter / Statistical Gate | Methodology content is useful; the gate stays deterministic and never LLM-judged |
| 6 | Peer Review | **MERGE INTO EXISTING ADVERSARY** (P11) | The agent class exists; harvest the mode, the deterministic CLIs, and the confidentiality policy |
| 7 | Scientific Critical Thinking | **ADOPT IN REDUCED FORM** — methodology into Adversary + CONTRA (P11) | Capability overlaps entirely; only the checklist content is new |
| 8 | Scientific Writing | **REIMPLEMENT AS HERMES P12 SKILL + VALIDATION METHODOLOGY** | Manifest/consistency/authorship discipline fills the stubbed report pipeline |

**None imported wholesale. The audit's "zero new architectural components" claim is VERIFIED** — the formal verification is at §E; the one caveat (PA3 `SkillRecord` is ratified design, not yet implemented) is an implementation precondition, not a new component.

---

## D. Current Hermes Gap (what each candidate fills)

| Candidate | The concrete gap it fills |
|---|---|
| Paper Lookup | `ResearchSourceProvider` (4-line stub) has no retrieval capability, no provider adapters, no failure catalog |
| Literature Review | No encoded search protocol / screening stages / exclusion reasons / search accounting anywhere in the P7 literature workflow |
| Hypothesis Generation | No procedure upstream of the Director producing candidates + rivals + discriminating predictions + falsification conditions |
| Experimental Design | No design-generation procedure; `ExperimentSpec` exists as contract only |
| Statistical Analysis | No methodology layer between the research question and the (future) Statistical Gate |
| Peer Review | No structured review templates or deterministic audit CLIs behind the Adversary's existing review task variants |
| Critical Thinking | No deterministic review checklist content (bias taxonomy, evidence grading, causal-vs-association) |
| Scientific Writing | `ReportRenderer` (5-line stub); no manifest/consistency/authorship discipline in the reporting pipeline |

---

## E. Existing-Component Mapping (verification of "zero new components")

| Responsibility | Existing owner (ratified) | What the harvest adds there |
|---|---|---|
| Retrieval port | §15 `ResearchSourceProvider` + thin adapters (P5) | Failure catalog, reconciliation/redaction discipline, adapter content |
| Search methodology | P7 `ResearchTaskPlan` / literature workflow + `LiteratureReview` artifact (§16.1) | `SearchProtocol` + `ScreeningRecord` + search accounting |
| Hypothesis proposal | §13 Researcher → §28.2 Director `PROPOSE_RESEARCH_PROGRAM` → `ResearchProgramValidator` | Generation procedure + pre-flight checks (advisory only) |
| Design proposal | §28/§8 `ExperimentSpec` + validator + pre-registration (P8) | DOE/randomization generators (proposal-only) |
| Statistical computation + gate | §28/§12 `StatsAdapter` + Statistical Gate (P9) | Methodology content (skill), never gate logic |
| Review | §13 Adversary task variants (P11) | Peer-review mode + templates + deterministic CLIs |
| Review content | §13 Adversary checklist + §29 CONTRA steelman/context | Checklist/rubric taxonomies |
| Reporting | §15 `ReportRenderer` + §16.1 `ResearchReport` + Reporting gate (§12) | Manifest/consistency/authorship validators + `submission_ready` |
| Skill lifecycle | PA3 `SkillRecord` + Engineering Control Plane (§13/§20/§27 items 19/29) | The *content* of the first real skill admissions |

Every capability maps onto an existing ratified surface. The only "new" things are artifact **fields** on existing artifacts (§J data models) and Tool Runtime **utilities** — both inside existing components. No new box, no new authority, no new event, no new intent, no new scheduler.

---

## F. Cross-Candidate Composition

The audit's strongest finding is that three chains are worth more than eight independent skills. Hermes' v6 spine already exists for all three; the amendment only fills the skill layer on top.

### Chain A — Epistemic → Experimental

```text
Hypothesis Generation (skill)         ← ResearchClaim/ResearchAssumption substrate (§29) as context
        ↓  candidate hypotheses + rivals + discriminating predictions + falsification conditions
ResearchProgram (§28.2, implemented)  ← Director proposal → ResearchProgramValidator → Gateway
        ↓
Experimental Design (skill)
        ↓  ExperimentSpec proposal (design type, seeded randomization, blocking, replication, run order)
deterministic ExperimentSpec validator → pre-registration (analysis_plan bound) → human/Gateway execution
        ↓
Statistical Analysis (skill)          ← proposes analysis plan (test selection, assumptions, effect sizes, power)
StatsAdapter (computation) → Statistical Gate (deterministic verdict)
```

**Shared data contracts (no redundant schemas):** the chain reuses the §28.2 `HypothesisSpec`/`Prediction`/`discrimination_requirements` shapes (hypothesis generation produces proposals *in those shapes*), the §11 `analysis_plan` + `pre_registration_hash` + `primary_metric`/`pre_specified_threshold` (experimental design and statistical analysis both produce proposals *in those shapes*), and the §12 Statistical Gate verdict. The amendment adds **no new contract types** — it adds procedures that populate existing contracts. The one shared primitive across the chain is **falsification discipline** (falsification_condition at generation → declared in the program → checked in the design → tested by the analysis) — encoded once, referenced three times.

### Chain B — Research Discovery → Adversarial

```text
Paper Lookup (skill/provider)         → Source records (provider, query, reconciliation, access time, redacted params)
        ↓
Literature Review (methodology)       → SearchProtocol + ScreeningRecord + search accounting on LiteratureReview
        ↓
LitKG / EXTRACT pipeline (§29.3, implemented) → ResearchClaim (span refs) / ResearchAssumption
        ↓
Peer Review (Adversary mode) + Critical Thinking (checklists) / CONTRA steelman
        ↓
Critique (artifact-cited) → ResearchChallenge (steelman, counter-evidence) — advisory, never evidence
```

**Provenance continuity:** a single §14 provenance graph carries provider → Source → artifact → claim (span refs) → critique → challenge. No second evidence graph. The `EXTRACT` pipeline already enforces producing-task binding and span-level provenance (§29.5); the search protocol feeds the literature task that produces the sources those extractions dereference.

### Chain C — Evidence → Report

```text
validated evidence (Evidence Ladder §10)
        ↓
ResearchReport (§16.1)  ← gains claim/evidence manifest + citation manifest + authorship record
        ↓
Scientific Writing (skill)  ← drafts prose bound to the manifest; every factual statement cites an artifact
        ↓
ReportRenderer (staged verification: generator → schema check → render → content verification) + manifest/consistency/reference/authorship checks
        ↓
Reporting gate (§12) + human `submission_ready` authorization
```

**No new report authority.** The GR9 graph gate (where enabled) applies unchanged — the manifest is the machine-checkable form of "every claim has closed provenance."

---

## G. SkillRecord Integration (how external material becomes Hermes-owned)

Every surviving candidate enters through the **PA3 engineering-plane admission** — the ratified and only skill mechanism. The amendment does not create a second path.

```text
scientific-agent-skills (HEAD 5ad4aae7, v2.63.0, MIT)
        ↓  source/version/license record (this amendment, §H)
        ↓  source security review against Hermes' own threat model (upstream CI is never sufficient)
        ↓  Hermes-native reimplementation / methodology extraction (per-candidate harvest type, §C)
        ↓  deterministic golden-fixture tests (manual-proof-first, §29 rule 7 extended)
        ↓  Engineering Change → worktree → CI (isolated runner) → PR → human merge (§20)
        ↓
SkillRecord { id, name, description, tool_refs, instructions_ref, package_ref|null,
              dependency_spec, tests_ref, license, version, content_hash, provenance, supersedes }
        ↓
Tool Runtime allowlist (progressive disclosure: only name + description enter prompts, §17/PA3-b)
        ↓
Agent Runtime (Researcher / Adversary task variants bind the skill)
```

**Rules that bind every admission:**
1. **No runtime installation** from the external repository, ever (PA3-a; the rejected PX5/PX12 pattern stays rejected).
2. **LLM prose is never a skill** — a `SkillRecord` is admitted only after a merged, tested engineering change (§20, curation invariant §16.6).
3. **Harvest type recorded in provenance:** each SkillRecord's `provenance` records source repo, source path, source HEAD, skill version, license, author, harvest type (IDEAS / REIMPLEMENT / METHODOLOGY / DETERMINISTIC-CLI), and the Hermes destination component.
4. **Re-audit on source bump:** a new upstream version triggers a re-run of the security/provenance record before the pinned SkillRecord version advances.
5. **PA3 open ratification items are preconditions, not preempted:** §27 items 19/29 (human-only merge vs. CI gate + human review; project-scoped vs. operator-global storage) must be decided before the first harvested SkillRecord is admitted — this amendment records them as §27 items 56 and does not decide them.

---

## H. Security / Supply Chain

| Dimension | Decision |
|---|---|
| Source pinning | Record the audited HEAD `5ad4aae7` in every harvested SkillRecord's provenance; verified unchanged via `git ls-remote` on 2026-08-13; re-audit on bump |
| License | MIT — permits reimplementation and derivative content; record license + attribution per SkillRecord (PA3 requires `license` + `content_hash` + `provenance`) |
| Dependencies | **Core:** none added. **Controlled tool dependencies** (behind Tool Runtime adapters, version-pinned): numpy/pandas/pyDOE3 (experimental design), scipy/statsmodels/pingouin/PyMC (statistical analysis). **Rejected:** parallel-cli, requests-based citation verification, subprocess PDF generation, OpenRouter, firecrawl, any orchestration |
| Network | Provider adapters use an allowlisted endpoint set with a Tool Runtime rate-limit policy (§27 item 55); credentials never in logs (redaction contract); external content retrieved by Paper Lookup / Literature Review is **untrusted data** — the instruction-injection boundary is explicit and the §18 rule ("web content is data, not instructions; never raw-concatenated into reasoning contexts") applies verbatim |
| External LLM | Any model-assisted step (hypothesis generation, synthesis, drafting, review) goes through `ModelClient` with record/replay; `model_ref` on every judgment-bearing artifact (§14.4) |
| Upstream CI | Not evidence of Hermes safety — the literature-review pipeline's **11 CRITICAL findings in the upstream's own scan** are the standing proof; every harvest is re-screened against Hermes' threat model |
| Confidentiality | Adopt the peer-review confidentiality boundary (unpublished manuscripts never leave the authorized processing context) as Tool/Agent Runtime policy (§27 item 57) |
| Reproducibility | All deterministic CLIs and fixtures replayable offline; seeded RNG where design generation is involved; ModelClient replay fixtures keyed to exact model version |

---

## I. Phase Placement

| Candidate | Phase | Gate / implementation precondition |
|---|---|---|
| Paper Lookup | **P7** (design now; adapter content usable at P5) | §15 provider port implementation; Tool Runtime + rate-limit policy + provider allowlist (§27 item 55) |
| Literature Review (methodology) | **P7** | Paper Lookup first (the protocol presumes retrieval); ResearchTaskPlan / literature workflow |
| Hypothesis Generation | **P4/P7** (deterministic CLIs as Tool Runtime utilities at P5; skill at P4/P7) | ResearchProgram proposal path (already operational); skill admission via PA3 (§27 item 56) |
| Experimental Design | **P8** | ExperimentSpec + validator + pre-registration slice |
| Statistical Analysis | **P8/P9** | StatsAdapter + Statistical Gate slice |
| Peer Review | **P11** | Adversary modes slice |
| Critical Thinking | **P11** | Adversary + CONTRA |
| Scientific Writing | **P12** (deterministic CLI discipline at P5 as tool content) | ReportRenderer implementation; ResearchReport manifest fields; Reporting gate `submission_ready` semantics (§27 item 58) |

**Sequencing rule (from the audit, confirmed):** a skill's *architecture* can be designed now; its *implementation* belongs to the phase where its surrounding Hermes authority exists. Paper Lookup and Scientific Writing address implemented-but-empty ports (actionable content now, runtime at their phases); the P8/P11/P12 candidates address architectural-only surfaces (encoded when their slices land).

**Determinism classification (per capability):**

| Capability | Deterministic (code) | Model-assisted (bounded) | Authority (Hermes-owned) |
|---|---|---|---|
| Paper Lookup | retrieval, parsing, reconciliation, redaction, dedup, identifier normalization | query intent interpretation | admission of Source records; evidence ladder |
| Literature Review | search protocol, screening decisions, exclusion reasons, search accounting, dedup, citation structure checks | synthesis | task admission; gate decisions |
| Hypothesis Generation | schema validation, prediction-matrix coherence, falsification controls, causal-claim lint, operationalization, preregistration scaffold | candidate generation | `COMPILED` verdict (validator); gateway admission |
| Experimental Design | seeded layouts, randomization schedules, pseudoreplication checks, design validity | design selection | pre-registration; human/Gateway execution |
| Statistical Analysis | computation (adapter), gate verdict | test selection / interpretation guidance | Statistical Gate |
| Peer Review / Critical Thinking | claim↔evidence matrix validation, citation audit, statistics-reproducibility audit, taxonomy structure | review judgment, checklist application | Critique gate-blocking (existing semantics) |
| Scientific Writing | manifest validation, numeric consistency, methods/results reconciliation, reference checks, authorship validation | drafting | Reporting gate; human `submission_ready` |

**Authority must remain deterministic/governed everywhere.** Skills propose; Hermes decides.

---

## J. Architecture Amendments (per surviving candidate)

Format per candidate: SECTION / CURRENT RULE / NEW RULE / OWNER / DATA MODEL / TOOL BOUNDARY / MODEL BOUNDARY / AUTHORITY LIMIT / PROVENANCE / SECURITY / DEPENDENCIES / TRIGGER / PHASE / ACCEPTANCE TESTS / DEFERRED PARTS.

### J.1 Paper Lookup

- **SECTION:** §15 (Tool Model / `ResearchSourceProvider`), §12 tool list (`LiteratureSearchTool`/`PaperFetchTool`), P5/P7 roadmap.
- **CURRENT RULE:** `ResearchSourceProvider` is a ratified Protocol (`search`/`fetch`/`extract`) with a 4-line stub implementation and no adapters.
- **NEW RULE:** the provider port is implemented with Hermes-owned thin adapters (PubMed, PMC, EuropePMC, arXiv, OpenAlex, Crossref, Semantic Scholar, CORE, Unpaywall, bioRxiv, medRxiv — initial allowlist, §27 item 55). `SearchResult` gains reconciliation and provenance fields (data model below). A `paper-lookup` SkillRecord wraps the methodology (database selection guidance, query strategy, provider-specific hazards) — skill content, not provider code. The per-provider failure catalog (HTTP-200 "Error" entries, empty bodies, `errCode` fields, cursor traps, silent rewrites) is reference content shipped with the SkillRecord.
- **OWNER:** Tool Runtime (adapter execution, rate limits, redaction) + Researcher/Implementer (query intent) + the existing write path (Source admission).
- **DATA MODEL:** `SearchResult` += `provider`, `endpoint`, `request_params_redacted`, `retrieved_count`, `total_count`, `reconciliation: COMPLETE | SHORTFALL` (typed failure on shortfall — never a silent empty result), `access_timestamp`, `content_hash`. `Source` (existing §16.1) unchanged in role; provenance now carries the retrieval record.
- **TOOL BOUNDARY:** the provider adapters + deterministic utilities (`reconcile_retrieval`, `redact_url`, `normalize_identifier`, `deduplicate_sources`, `detect_http200_failure`); network to the allowlisted endpoints only; rate limits enforced by the Tool Runtime; side_effect class `READ_ONLY` (retrieval is read-only).
- **MODEL BOUNDARY:** retrieval/parsing/reconciliation/dedup/redaction = deterministic code. Database selection and query refinement = LLM judgment bounded by the skill.
- **AUTHORITY LIMIT:** read-only retrieval; the result becomes structured evidence/provenance/artifacts only through the existing write path — never a free-form LLM answer as evidence. No task creation, no evidence promotion, no gate input by the retrieval layer itself.
- **PROVENANCE:** provider, endpoint, parameters (redacted), identifiers, access timestamp, reconciliation counts, content hashes — the retrieval is re-runnable.
- **SECURITY:** external content = untrusted data (instruction-injection boundary); §18 "web content is data" rule verbatim; credentials never logged; bounded downloads (S11 defaults).
- **DEPENDENCIES:** stdlib only in Hermes-owned adapters (JATS/Atom parsing via stdlib `xml.etree`); no external packages.
- **TRIGGER:** P7 `LITERATURE` task with retrieval need → skill binds → adapters run under the allowlist → Source records admitted.
- **PHASE:** P7 (adapter content at P5).
- **ACCEPTANCE TESTS:** malformed HTTP-200 responses (arXiv "Error" entry, PMC empty body, EuropePMC `errCode`) → typed failure, never silent empty; provider cursor trap → bounded pagination with reconciliation; retrieval shortfall → `SHORTFALL` typed failure; identifier normalization (DOI/PMID/arXiv/PMC); dedup; credential redaction; injection-boundary handling (hostile payload never interpreted as instructions); reproducible provenance (same request → same record).
- **DEFERRED PARTS:** providers beyond the initial allowlist; full-text extraction beyond JATS/Atom; the LitKG/GraphRetrieval integration (its own GR1/GR2 phases).
- **Implementation contract (DESIGNED):** `hermes_researchsourceprovider_contract.md` — the concrete adapter set (11 providers + the web-search row), the `SearchResult` reconciliation fields and semantics (`COMPLETE`/`SHORTFALL`/`UNKNOWN`, `PARTIAL`-vs-`EMPTY` aggregates, `VALID_NEGATIVE`), the versioned hazard-spec failure catalog with one deterministic evaluator, per-provider rate-limit starting-point defaults, the redaction contract, and the §27 item 55 ratification points. No code — the design the Part 3 implementation consumes.
- **Implementation blueprint (DESIGNED):** `hermes_researchsourceprovider_implementation_design.md` — the *how*: `src/hermes/tools/providers/` module layout, the `ProviderAdapter` skeleton (three thin hooks — `build_request` / `parse_page` / `extract_ids` — under one provider-agnostic `walk()` driver), the `ProviderHazardSpec` schema + generic `evaluate_hazards`, the reconciliation driver with the cursor guard and `COMPLETE`/`SHORTFALL`/`UNKNOWN` + `PARTIAL`/`EMPTY` aggregates, the clock-injected `ProviderRateLimiter`, the recorder-boundary redaction, the offline `RecordedTransport` record/replay harness with the failure catalog as the fixture corpus, five test files, and the seven-step implementation order. Gated on §27 item 55 ratification — now **RESOLVED (IDR-030, 2026-08-13)**.

### J.2 Literature Review (methodology)

- **SECTION:** §16.1 (`LiteratureReview` artifact), §7 (`ResearchTaskPlan`), P7 roadmap.
- **CURRENT RULE:** `LiteratureReview` carries `contradictions[]` (tag-structured); the literature task produces `Source[]` + `LiteratureReview`; no search protocol or screening structure exists.
- **NEW RULE:** a literature review is governed by a declared `SearchProtocol` (databases, Boolean/field queries, inclusion/exclusion criteria, dedup rule, screening stages, search boundary) recorded before screening; screening decisions carry reasons; search accounting (per-provider retrieved / deduplicated / included counts) is recorded on the artifact; citation verification is a deterministic check. The systematic-review *methodology* (PRISMA-style where applicable) is skill content, not a new engine.
- **OWNER:** Researcher (executes the protocol) → the existing write path (artifact admission) + Tool Runtime (verification checks).
- **DATA MODEL:** `SearchProtocol` record (declared, content-hashed); `ScreeningRecord { stage, decision: INCLUDE | EXCLUDE | DEFER, reason, source_ref }`; `LiteratureReview` += `search_protocol_ref`, `screening_records[]`, `search_accounting` (per-provider counts).
- **TOOL BOUNDARY:** the Paper Lookup retrieval layer + deterministic utilities (`check_search_accounting`, `verify_citations`, `apply_inclusion_exclusion`); no subprocess PDF generation, no parallel-cli, no figure generation.
- **MODEL BOUNDARY:** protocol execution, screening classification, dedup, accounting = deterministic; synthesis (thematic synthesis) = LLM judgment bounded by the skill and artifact-cited.
- **AUTHORITY LIMIT:** the review is an artifact, never evidence; its `contradictions[]` remain tag-structured and feed the existing §19/GR3 machinery only.
- **PROVENANCE:** protocol hash, screening record per source, accounting counts, citation verification results — re-runnable.
- **SECURITY:** the upstream pipeline (requests/subprocess/OpenRouter/parallel-cli — 11 CRITICAL in the upstream scan) is **rejected wholesale**; Hermes' provider network surface only.
- **DEPENDENCIES:** none beyond the Paper Lookup layer; stdlib checks.
- **TRIGGER:** a P7 literature task with a declared search question (optionally from a ResearchProgram obligation).
- **PHASE:** P7.
- **ACCEPTANCE TESTS:** a golden review round-trips protocol → screening → accounting → artifact; an undeclared source outside the protocol boundary is flagged; inclusion/exclusion applied with reasons; dedup collapses duplicates; citation verification flags a fabricated/undereferenced citation; search accounting sums correctly.
- **DEFERRED PARTS:** PRISMA-style *figure* reporting (presentation policy — rejected); thematic synthesis as a scheduled capability (P12 reporting); cross-database protocol federation beyond the allowlist.

### J.3 Hypothesis Generation

- **SECTION:** §28.2 (upstream of the `PROPOSE_RESEARCH_PROGRAM` proposal path), §13 (Researcher task variant + skill), P4/P7.
- **CURRENT RULE:** the Director produces a schema'd `ResearchProgramDraft`; `ResearchProgramValidator` compiles (E1–E5, governance, identity); the Gateway admits. Generation procedure is unstructured.
- **NEW RULE:** a `hypothesis-generation` SkillRecord (Researcher-bound) produces candidate hypotheses with the source's full discipline — observation → question → hypothesis → mechanism → causal estimand → prediction → alternative explanation → null → negative control → analysis plan — plus rival explanations, discriminating predictions, declared assumptions, falsification conditions, and operationalization. Its output is a `ResearchProgramDraft`-shaped **proposal** carrying an advisory `PreflightReport`. The deterministic checks (prediction-matrix coherence, causal-claim lint, falsification controls, operationalization, preregistration scaffold, evidence-ledger audit) are reimplemented as Tool Runtime utilities and run on the proposal pre-flight.
- **OWNER:** Researcher (generation, bounded) → Director (selection, `PROPOSE_RESEARCH_PROGRAM`) → `ResearchProgramValidator` (admission authority) → Gateway.
- **DATA MODEL:** no new contract types — the proposal reuses the §28.2 `ResearchProgramDraft`/`HypothesisSpec`/`Prediction`/`discrimination_requirements` shapes. New advisory artifact: `PreflightReport { checks[], result: PASS | WARN | FAIL, notes[] }` — attached to the proposal, **never a verdict**, never persisted as evidence (transient, like `CandidateRanking`).
- **TOOL BOUNDARY:** the reimplemented deterministic CLIs (`validate_prediction_matrix`, `lint_causal_claims`, `check_falsification_controls`, `check_operationalization`, `generate_preregistration_scaffold`, `audit_evidence_ledger`) as Tool Runtime utilities; read access to the `ResearchClaim`/`ResearchAssumption` substrate (§29.3) for evidence-bound context.
- **MODEL BOUNDARY:** generation, rival construction, mechanism, prediction derivation = LLM judgment bounded by the skill; every structural check = deterministic code.
- **AUTHORITY LIMIT:** the skill MUST NOT select the research direction, rank hypotheses authoritatively, promote evidence, create a `ResearchProgram`, create tasks, or mutate lifecycle/gates. Its `PreflightReport` can neither admit nor reject a program: `COMPILED` remains exclusively `ResearchProgramValidator`'s verdict, and the write path already fails closed on anything but the validator's own compiled program (Model D). **The ratified E1–E5 checks are unchanged** — the skill front-loads the same discipline so drafts arrive COMPILED-eligible; it never replaces or extends the validator.
- **PROVENANCE:** `proposed_by: hypothesis-generation-skill`, `model_ref`, source/claim refs behind every candidate; candidates are proposals, never evidence.
- **SECURITY:** stdlib-only, local-only utilities; no network; no credentials; the safety/ethics screening language of the source is usable policy content only.
- **DEPENDENCIES:** none (stdlib reimplementation).
- **TRIGGER:** a research question / evidence-bound observation context (optionally from a frozen `ScopeBrief`) → Researcher runs the skill → proposal to the Director.
- **PHASE:** P4/P7.
- **ACCEPTANCE TESTS:** incoherent prediction matrix → deterministic `FAIL` (not an LLM judgment); causal language linted ("association ≠ causation"); falsification-condition completeness; rival explanations preserved (no silent collapse); operationalization check; preregistration scaffold deterministic; the **structural never-auto-select test** (no path from skill output to program admission except Director → Validator → Gateway); the **pre-flight-vs-verdict test** (a `PreflightReport.FAIL` cannot block a validator-`COMPILED` program, and a `PASS` cannot admit a validator-`INVALID` one — the validator is the sole authority).
- **DEFERRED PARTS:** the scaffold's deployment as a real pre-registration pipeline (its own §11 slice); integration of the evidence-ledger audit with the refuted-registry screen (S7) — recorded as a future intersection, not implemented here.

### J.4 Experimental Design

- **SECTION:** §8/§28 (`ExperimentSpec` + pre-registration), §13 (Researcher variant), P8.
- **CURRENT RULE:** `ExperimentSpecification` gains `pre_registration_hash`, `executed_spec_hash`, `primary_metric`/`pre_specified_threshold`, `exploratory_confirmatory`, `analysis_plan`; no design-generation procedure exists.
- **NEW RULE:** an `experimental-design` SkillRecord (Researcher-bound) produces an `ExperimentSpec` **proposal**: design type selection (full/fractional factorial, Plackett–Burman, CCD, Box–Behnken, Latin hypercube, crossover/repeated measures, split-plot, cluster), seeded randomization schedule, blocking/stratification plan, replication structure, run-order randomization, pseudoreplication check, sample-size/power pointer. Deterministic validator + pre-registration + human/Gateway-controlled execution own everything downstream.
- **OWNER:** Researcher (proposal) → deterministic ExperimentSpec validator → pre-registration → human/Gateway execution.
- **DATA MODEL:** transient `DesignProposal { design_type, factors[], levels, randomization_seed, blocking, replication_structure, run_order, pseudoreplication_check, power_pointer }` → maps into the existing `ExperimentSpecification` shape (no new contract fields beyond the existing §8/§28.2 set).
- **TOOL BOUNDARY:** DOE generators and seeded RNG behind a Hermes adapter (controlled tool deps); `check_pseudoreplication`, `randomize_run_order` utilities.
- **MODEL BOUNDARY:** design selection = LLM judgment bounded by the skill; seeded layout generation, validity, pseudoreplication detection = deterministic.
- **AUTHORITY LIMIT:** never approves, never executes, never registers by itself; pre-registration and execution are human/Gateway-controlled.
- **PROVENANCE:** `randomization_seed`, generator version, adapter version, design content hash — same seed ⇒ same layout, replayable.
- **SECURITY:** computation only; no network; controlled tool deps version-pinned behind the adapter.
- **DEPENDENCIES:** numpy/pandas/pyDOE3 — **controlled tool dependencies**, never core.
- **TRIGGER:** a `ResearchProgram`/frozen `ScopeBrief` research question requiring a designed experiment (P8).
- **PHASE:** P8.
- **ACCEPTANCE TESTS:** seed reproducibility (same seed → identical layout); pseudoreplication detected in a planted fixture; run-order randomization against drift; invalid design fixtures rejected; the **proposal-without-approval structural test** (no path from skill output to execution without validator + pre-registration + human gate).
- **DEFERRED PARTS:** sample-size/power computation (Statistical Analysis skill); sequential/adaptive design machinery (P10 robustness); the GR4 graph candidate seeding intersection (its own phase).

### J.5 Statistical Analysis

- **SECTION:** §28/§12 (`StatsAdapter` + Statistical Gate), §13 (Researcher variant + analysis task), P8/P9.
- **CURRENT RULE:** `StatisticalAnalysisTool`/`StatsAdapter` and the Statistical Gate are ratified but not implemented; `analysis_plan` is pre-registered (M4).
- **NEW RULE:** a `statistical-analysis` SkillRecord (Researcher-bound) provides the **methodology layer** — test selection guidance, assumption checking, effect sizes, power, uncertainty, reporting standards — and produces an `analysis_plan` **proposal**. Computation runs through `StatsAdapter`; the gate verdict is deterministic and owned by the Statistical Gate. The skill never emits a verdict.
- **OWNER:** Researcher (proposal) → `StatsAdapter` (computation) → Statistical Gate (decision) → existing evidence path.
- **DATA MODEL:** no new artifact — the skill drafts the existing `analysis_plan` (declared tests + primary test + fallback order) plus an assumption-check report feeding the gate.
- **TOOL BOUNDARY:** `StatsAdapter` behind the Tool Runtime (controlled tool deps); `assumption_checks` utility; no direct package invocation by the agent.
- **MODEL BOUNDARY:** test selection and interpretation guidance = LLM judgment, labeled and model_ref-tagged; computation and gate verdict = deterministic. **"p < .05 → SUPPORTED" is structurally impossible** — the gate is the only path to a verdict.
- **AUTHORITY LIMIT:** the skill cannot decide significant/not-significant, robust/not-robust, supported/not-supported; cannot promote evidence; cannot bypass the gate.
- **PROVENANCE:** analysis-plan hash (pre-registered), adapter version, dataset refs, assumption-check records, gate verdict record.
- **SECURITY:** computation only; controlled tool deps version-pinned; no network.
- **DEPENDENCIES:** scipy/statsmodels/pingouin/PyMC — **controlled tool dependencies** behind `StatsAdapter`, never core.
- **TRIGGER:** a pre-registered experiment producing results (P9).
- **PHASE:** P8/P9 (deferred to the Statistical Engine slice — the skill cannot be meaningfully implemented before the engine it advises exists).
- **ACCEPTANCE TESTS:** test-selection workflow on golden datasets; assumption-check ordering; effect-size/power correctness; the **structural no-gate-verdict test** (the skill's output schema has no verdict field); pre-registered-plan adherence.
- **DEFERRED PARTS:** the Bayesian workflow (PyMC) — controlled tool scope, later; multiple-comparison machinery (its own P9 gate work); reporting-standards rendering (Scientific Writing).

### J.6 Peer Review

- **SECTION:** §13 (Adversary task variants), P11.
- **CURRENT RULE:** the Adversary holds `HYPOTHESIS_CRITIQUE` / `METHODOLOGY_REVIEW` / `ROBUSTNESS_REVIEW` / `RESULT_REVIEW` / `REPORT_REVIEW`; findings are artifact-cited `Critique` records with gate-blocking semantics.
- **NEW RULE:** a **peer-review mode + skill package** inside the Adversary: claim↔evidence matrix template, reporting checklist, statistical-reproducibility template, citation audit — plus deterministic Tool Runtime checks (`validate_claim_evidence`, `audit_citations`, `audit_statistics_reproducibility`). The upstream confidentiality boundary (unpublished manuscripts never leave the authorized processing context) is adopted as Tool/Agent Runtime policy.
- **OWNER:** Adversary profile (review judgment) + Tool Runtime (deterministic checks).
- **DATA MODEL:** no new artifact — the mode produces the existing `Critique` (severity-ranked, artifact-cited, PASS/FAIL/PASS_WITH_CONCERNS); templates are skill assets.
- **TOOL BOUNDARY:** the three stdlib deterministic checks behind the Tool Runtime.
- **MODEL BOUNDARY:** review judgment = Adversary LLM work, artifact-cited; matrix completeness, citation integrity, and statistics-reproducibility audits = deterministic.
- **AUTHORITY LIMIT:** findings are critiques; gate-blocking only via existing Critique verdict semantics; no evidence promotion, no automatic resolution, no `PeerReviewAgent`.
- **PROVENANCE:** every finding cites artifacts (span refs where available); `model_ref` on the Adversary's judgment; deterministic check outputs recorded.
- **SECURITY:** confidentiality boundary as policy; no external network for the checks (stdlib, local).
- **DEPENDENCIES:** stdlib only.
- **TRIGGER:** a `REPORT_REVIEW`/`RESULT_REVIEW` variant with the peer-review mode bound (P11).
- **PHASE:** P11.
- **ACCEPTANCE TESTS:** claim↔evidence matrix completeness; citation audit flags a fabricated/undereferenced citation; statistics-reproducibility audit catches a planted mismatch; confidentiality boundary (unpublished manuscript never leaves the authorized context); findings are critiques, never gates (structural test).
- **DEFERRED PARTS:** editorial-decision semantics (the source's separation of review findings from editorial decisions maps to the existing Director/human path — nothing new); the ethics/integrity review dimension (policy content, P13 calibration).

### J.7 Scientific Critical Thinking

- **SECTION:** §13 (Adversary standing checklist), §29 (CONTRA steelman/context modes), P11.
- **CURRENT RULE:** the Adversary has a standing checklist (test-selection stability, reward-hack patterns, §13/§710); CONTRA adds steelman/contextualization (candidate).
- **NEW RULE:** the structured critique taxonomies — evidence grading (GRADE / Cochrane Risk-of-Bias), bias/confounding classes, causal-vs-association checks, evidence hierarchy, logical fallacies, statistical pitfalls — become deterministic **checklist/rubric content** in the Adversary's standing checklist and the CONTRA steelman/context templates. The taxonomy is code-able structure; its application is model judgment.
- **OWNER:** Adversary + CONTRA (content), Tool Runtime (taxonomy vocabulary, deterministic).
- **DATA MODEL:** a versioned review-checklist schema (evidence-grade vocabulary, bias classes, causal-check items) — content, not a gate.
- **TOOL BOUNDARY:** the taxonomy vocabulary as a Tool Runtime read-only structure.
- **MODEL BOUNDARY:** taxonomy = deterministic structure; application (grading a claim, spotting a bias) = LLM judgment bounded by the checklist.
- **AUTHORITY LIMIT:** a checklist is never an evidence gate by itself; only the §10/§12 mechanisms may gate. External schematic/visual-aid generation (OpenRouter-dependent) is rejected.
- **PROVENANCE:** checklist version recorded on the Critique that applies it.
- **SECURITY:** no network; no scripts to audit (references only).
- **DEPENDENCIES:** none.
- **TRIGGER:** bound into the Adversary's review variants and CONTRA modes (P11).
- **PHASE:** P11.
- **ACCEPTANCE TESTS:** a planted confounding/selection-bias fixture is surfaced by the checklist application; evidence-grade vocabulary applies deterministically (grading of *labels* is code; grading of *content* is judgment, and the two are separated in the schema); the **checklist-is-not-a-gate structural test**.
- **DEFERRED PARTS:** the GRADE/Cochrane full instrument mechanics (P13 calibration); any automated "critical thinking" loop (rejected — no scheduler).

### J.8 Scientific Writing

- **SECTION:** §15 (`ReportRenderer`), §16.1 (`ResearchReport`), §12 (Reporting gate), P12.
- **CURRENT RULE:** `ReportRenderer` is a ratified staged-verification pipeline with a 5-line stub; `ResearchReport` is a first-class structured artifact; the Reporting gate verifies statement→artifact citations; GR9 adds closed provenance where enabled.
- **NEW RULE:** `ResearchReport` gains the manifest discipline: `claim_evidence_manifest` (every claim → its evidence refs), `citation_manifest`, `consistency_report` (numeric consistency + methods/results reconciliation), `authorship_record`, `reporting_guideline_ref`. Deterministic validators (`validate_manifest`, `check_consistency`, `audit_claims`, `check_references`, `validate_authorship`, `select_reporting_guidelines`) run in the renderer's staged verification. A `scientific-writing` SkillRecord bounds the drafting task. The Reporting gate's human authorization gains `submission_ready` semantics (§27 item 58).
- **OWNER:** Researcher (drafting, bounded) → deterministic validators (Tool Runtime) → `ReportRenderer` (staged verification) → Reporting gate + human.
- **DATA MODEL:** `ResearchReport` += `claim_evidence_manifest`, `citation_manifest`, `consistency_report`, `authorship_record`, `reporting_guideline_ref`, `submission_ready` (settable only by human authorization). All versioned/immutable per §16.1.
- **TOOL BOUNDARY:** the stdlib deterministic check CLIs behind the Tool Runtime; the renderer (md/tex/html) unchanged.
- **MODEL BOUNDARY:** drafting = LLM judgment bounded by the skill and by the manifest (every factual statement cites an artifact — the existing staged-verification rule); manifests, consistency, references, authorship = deterministic.
- **AUTHORITY LIMIT:** the writing layer cannot fabricate citations/data/results/methods/approvals/authorship/statistical claims (structural: manifest validation + citation checks reject any statement without a dereferenceable artifact ref); cannot approve its own output (`submission_ready` is human-set); cannot promote evidence.
- **PROVENANCE:** claim→evidence manifest refs into the §14 graph; GR9 closed-provenance check (where enabled) applies unchanged.
- **SECURITY:** stdlib-only checks; confidentiality policy applies (unpublished manuscripts); no external services.
- **DEPENDENCIES:** none.
- **TRIGGER:** a `REPORT_DRAFT` task at P12 (the deterministic CLI discipline can land at P5 as tool content behind `ReportRenderer`).
- **PHASE:** P12.
- **ACCEPTANCE TESTS:** claim↔evidence manifest completeness (a claim without evidence refs fails); numeric consistency (planted inconsistent numbers fail); methods/results reconciliation; citation verification (fabricated citation fails); authorship validation; `submission_ready` only set by human authorization; the **no-fabrication structural test** (no path from drafting output to a submitted report without manifest validation + renderer verification + human authorization).
- **DEFERRED PARTS:** LaTeX/HTML rendering polish (P12); reporting-guideline selection breadth; the vault projection of the final report (§21, unchanged).

---

## K. Acceptance Tests (cross-cutting summary)

Beyond the per-candidate tests in §J, every harvested capability ships under the manual-proof-first rule (§29 rule 7, extended): **golden fixtures (assertion-correctness, S8 pattern) pass before any scheduled execution**, and adversarial review precedes adoption. The standing per-candidate adversarial fixtures are enumerated in §J; the cross-cutting invariants are:

1. **Never-auto-select** (hypothesis generation) — no path from skill output to program admission except Director → Validator → Gateway.
2. **Never-evidence** (all) — retrieval, reviews, rankings, checklists, and pre-flight reports are never `Validation`-citable; the ladder's §10.2 preconditions are untouched.
3. **No-gate-verdict** (statistical analysis, reviews) — skill output schemas carry no verdict fields.
4. **Proposal-without-approval** (experimental design) — no path from design to execution without validator + pre-registration + human gate.
5. **No-fabrication** (scientific writing) — no path from draft to submitted report without manifest validation + renderer verification + human authorization.
6. **Replayability** (all) — deterministic checks replay offline; seeded RNG where design is involved; ModelClient record/replay for judgment steps.
7. **Provenance-closed** (all) — every consumed artifact carries dereferenceable refs; dangling refs reject.

---

## L. Explicitly Rejected Ideas

| Idea | Rejected because |
|---|---|
| Importing any skill wholesale | Skills are agent-facing capability documents; Hermes owns behavior (audit verdict, confirmed) |
| The literature-review *pipeline* (parallel-cli, search_databases, generate_pdf, generate_schematic_ai) | Second orchestration surface; subprocess/requests/OpenRouter; 11 CRITICAL in the upstream's own scan |
| Mandatory AI-generated figures | Presentation policy, not a research-control primitive; external-LLM dependency |
| The source's skill-invocation/orchestration model (cross-skill composition) | Reconcile/Task Graph/Gateway/Controller already own execution (PX12-class rejection preserved) |
| Direct Write/Edit skill model | Hermes bounds writes via Tool Runtime + artifact/write-path rules |
| External LLM usage for peer-review/writing steps | ModelClient with record/replay is the only model surface |
| `PeerReviewAgent` / `CriticalThinkingAgent` | Duplicate agent classes; the Adversary owns this work |
| pyDOE3/scipy/statsmodels/pingouin/PyMC as core dependencies | Controlled tool dependencies behind adapters only |
| A second literature engine, a second report authority, a second evidence graph | Zero-new-component rule; existing surfaces own all of it |
| Pre-flight checks becoming validator checks | The ratified E1–E5 contract is unchanged; pre-flight is advisory |
| A runtime skill marketplace or runtime skill installation | PA3-a / PX5 / PX12 rejection preserved |

---

## M. Implementation Preconditions

| Candidate | Must exist first |
|---|---|
| Paper Lookup | §15 provider port implementation (P5); Tool Runtime with rate-limit policy + provider allowlist (§27 item 55); redaction contract |
| Literature Review | Paper Lookup; `ResearchTaskPlan` literature workflow; `LiteratureReview` artifact fields |
| Hypothesis Generation | ResearchProgram proposal path (already operational); PA3 skill admission decision (§27 item 56); Tool Runtime utilities (P5) |
| Experimental Design | ExperimentSpec + validator + pre-registration slice (P8) |
| Statistical Analysis | StatsAdapter + Statistical Gate slice (P9) |
| Peer Review | Adversary modes slice (P11) |
| Critical Thinking | Adversary + CONTRA modes (P11) |
| Scientific Writing | `ReportRenderer` implementation (P5); `ResearchReport` manifest fields; Reporting gate `submission_ready` semantics (§27 item 58) |
| All | PA3 `SkillRecord` implementation (ratified design, not yet coded); §27 items 19/29 decided; golden fixtures + adversarial review (manual-proof-first) |

**The sequencing rule in one sentence:** the surrounding Hermes authority must exist before the skill can meaningfully run — nothing in this amendment accelerates a phase or backdoors a capability.

---

## N. Documentation Changes

| File | Change |
|---|---|
| `hermes_research_architecture_v6.md` | New §3f candidate amendment record; new §30 candidate amendment package (normative candidate rules + phase table + status, DESIGNED); new §27 items 55–58 (open items). No ratified text modified |
| `hermes_scientific_agent_skills_audit.md` | Unchanged (the primary input; this document is its design-phase follow-on) |
| `README.md` | Index entry for this amendment document |
| Future IDRs | Each adopted capability gets its own Part 3 implementation IDR through the normal engineering-plane process (no IDR in this design-only phase) |

---

## O. Final Decision

**ACCEPT WITH CONDITIONS.**

The audit's dispositions are confirmed for all eight candidates; the zero-new-components claim is verified (§E). The conditions, recorded as §27 items 55–58, are the preconditions that must be decided/ratified before implementation of the corresponding slices:

1. **§27 item 55** — provider allowlist + rate-limit policy + reconciliation/redaction contract (before any Paper Lookup adapter runs). **RESOLVED — IDR-030 (2026-08-13):** the five decision points (initial 11-provider allowlist, reconciliation semantics, redaction contract, rate-limit starting-point defaults, `total_is_estimate` + dedup-before-reconcile) are ratified against the remediated contract/blueprint design (three review gates folded in); the web-search row (Serper/Searxng) is a separate deferred row of the same decision; Part 3 implementation of the provider slice is authorized per the blueprint's seven-step order.
2. **§27 item 56** — PA3 skill-admission ratification (items 19/29) decided before the first harvested `SkillRecord` is admitted.
3. **§27 item 57** — confidentiality policy ratification (P11).
4. **§27 item 58** — `submission_ready` Reporting-gate semantics (P12).

**Status ladder:** everything in this amendment is **DESIGNED**. Nothing is IMPLEMENTED, TESTED, VERIFIED, or RATIFIED. The v6 ratified baseline (§1–§28) is untouched; the CONTRA candidate (§29) is untouched. Implementation — when authorized — proceeds per capability through the five-stage loop: Part 3 implementation, adversarial review, closure verification, and only then ratification. **Slice-level exception (2026-08-13):** the Paper Lookup design decision is ratified at §27 item 55 (IDR-030) — the *design* is authorized for Part 3; the *slice* remains DESIGNED until implemented, tested, and independently gated.

---

## Second Internal Challenge (the drift attack, per design-phase §30)

Assume the proposed integration is wrong. The failure modes, and the defenses the amendment already encodes:

| Attack | Finding | Defense / revision |
|---|---|---|
| Duplicate responsibility (skill validators vs. `ResearchProgramValidator`) | Real risk if the skill's checks were treated as authoritative | Rule 3 (§30.2): pre-flight is advisory; `COMPILED` is exclusively the validator's; the E1–E5 contract is unchanged (J.3) |
| Duplicate validation (skill claim-linting vs. `ClaimAssumptionValidator`) | Different artifacts (generated candidates vs. extracted claims); no shared authority path | Skill CLIs are generation-time Tool Runtime utilities; the substrate's validator is the only admission validator for extracted claims (J.3) |
| Hidden authority (skill output treated as `COMPILED`) | Model D already forbids trusting caller-claimed verdicts; the gateway persists only the validator's own compiled program | Preflight is labeled `PREFLIGHT`, transient, never evidence (J.3; §28.2 trust model unchanged) |
| Skill→mutation bypass | Skills have no write surface except proposal drafts via the intent path | PA3 admission + Tool Runtime allowlist + the one-mutation-path rule (J.1–J.8 authority limits) |
| Skill→evidence bypass (retrieval/review as evidence) | Ladder §10.2 preconditions untouched; "never evidence" extended to all new surfaces | Cross-cutting invariant 2 (§K); Source/`Critique`/checklist are never `Validation`-citable |
| Model→gate bypass ("p < .05 → supported") | Structurally impossible: gate-only verdict path | Three-way split (J.5); no-verdict-field schema test |
| Second scheduler / second pipeline (literature-review pipeline) | Rejected wholesale on CRITICAL-scan evidence + orchestration duplication | §L; Reconcile/Task Graph own execution |
| Second literature engine / second report authority / second evidence graph | All new surfaces map onto existing artifacts and the single §14 provenance graph | §E, §F |
| Dependency sprawl | Controlled tool deps only, version-pinned, behind adapters; stdlib reimplementation where possible | §H, J.4/J.5 |
| External-content injection | Untrusted-data rule verbatim; instruction-injection boundary explicit | §H, J.1 |
| Licensing/provenance loss | Every SkillRecord records source HEAD/path/license; re-audit on bump | §G, §H |
| Nondeterministic reproducibility | Seeded RNG; ModelClient record/replay; deterministic validators | §I determinism table |
| Phase leakage / premature implementation | The amendment is DESIGNED; nothing runs before its phase gate + surrounding authority exists | §M, §O |

**No attack survived; the revisions needed were already structural in the amendment (the pre-flight-vs-verdict boundary, the three-way statistical split, the pipeline rejection, the PA3 precondition).** This confirms — rather than forces — the ACCEPT WITH CONDITIONS verdict.
