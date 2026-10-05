# Hermes Steal Amendments — Objection-Filtered Harvest from llm-wiki

**Status:** proposal, uncommitted
**Amends:** `hermes_research_architecture_v3.md` (v3)
**Supersedes:** nothing. **Complements:** the v3 merge decision record (§3).
**Citation convention (per v3 C8):** `v3 §N` = `hermes_research_architecture_v3.md`; `steal §N` = this document. Bare `§N` refers to v3. **Finding ids:** `S1–S16` = adopted steals; `X1–X14` = considered and excluded. Finding ids refer to findings, not sections.
**Source:** `llm-wiki` (MIT; fork `ace2013hieco-aa/llm-wiki` of `nvk/llm-wiki`). Ideas only — no code is vendored; disposition per v3 §22 (**REIMPLEMENT**).

One sentence: *Hermes adopts, from llm-wiki, only what survives two adversarial review rounds: thesis-driven investigation as a structured gate precondition, a deterministic corroboration count, round-based gap drilling, Director/human digests, supersede-and-invalidate cascades, bounded event payloads, near-miss registry advisories, ModelClient-owned golden fixtures, write-path enforcement tests, angle variants with a quarantined exploratory burst, hardened tool-runtime defaults, dataset manifests, skip-rate metrics, a provenance audit service, acquisition triage, and frozen-brief promotion — each landing inside an existing v3 component, never as a parallel system.*

---

## 1. Method

Two adversarial rounds preceded this document. Round 1 (user): objections on verdict placement, determinism, agent memory, and immutability. Round 2 (self-adversarial): objections to the first harvest's compensating-control imports. Governing rules, all preserved from v3:

1. **v3 §2 principle 2** — one authoritative mutation path; "no second write path" extends to *no second audit path, no second registry, no second eval framework*.
2. **v3 §2 principle 6** — the burden of proof is on making a responsibility agentic; deterministic code owns what it can.
3. **v3 §2 principle 7** — never over-engineer; SQLite is the day-one system of record; DuckDB is a deferred enhancement.
4. **v3 §2 principle 8** — external frameworks are never architectural authorities; adapters behind Hermes-owned ports only.
5. **Compensating vs. preventing controls** — llm-wiki lints, peeks, and redacts because it is a markdown-file knowledge base without typed state, a gateway, or a single write path. Hermes has all three. A compensating control is adopted only when it fills a *real* gap; where v3 already specifies the control, the residue (if any) amends the existing component.

---

## 2. Merge Decision Record — Adopted

| Steal | Source mechanism | v3 target | Phase | IDR |
|---|---|---|---|---|
| S1 Thesis-driven investigation | `/wiki:thesis` | §6.1, §9.1, §10.2, §13 | P1/P2/P4 | — |
| S2 Deterministic corroboration count | article confidence scoring | §5, §10.1, §14 | P2/P7 | — |
| S3 Round-based gap drilling | `--min-time` rounds | §7, §8, §13 | P3/P4 | — |
| S4 Director digest + human resume + feedback curator | session memory / rehydrate / feedback | §13, §14.6, §21 | P3/P4/P10+ | **yes** |
| S5 Supersede-and-invalidate cascade | `/wiki:retract` | §7, §8, §10.2, §14, §16.1, §21 | P2/P3 | **yes** |
| S6 Bounded event payloads | redacted session capture | §8.1 | P1 | **yes** |
| S7 Near-miss refuted-registry advisory | multi-wiki peek | §10.2, §13, §16.6 | P2/P3/P4 | — |
| S8 Golden-scenario Director fixtures | promptfoo evals | §5, §13 | P4 | — |
| S9 Write-path enforcement tests | read-only query profile | §8.1, §18, §21 | P3/P5 | — |
| S10 Angle variants + quarantined exploratory burst | parallel research agents / retardmax | §2.4, §13 | P4 | **yes** |
| S11 Tool-runtime operational defaults | collector scale/media bounds | §15, §18 T3/T4 | P5 | — |
| S12 Dataset manifests | `/wiki:dataset` | §5, §12, §16 | P1/P7 | — |
| S13 Skip-rate metric | thesis-as-bloat-filter | §7, §14.6 | P2/P10+ | — |
| S14 Provenance audit + freshness service | `/wiki:audit`, librarian | §12, §14, §16.2 | P2/P10+ | — |
| S15 DATA_ACQUISITION triage | opinionated inventory | §5, §13 | P7 | — |
| S16 Frozen-brief promotion | Concept → Idea → Project | §6.1, §9.2, §11 | P1/P2 | — |

---

## 3. Excluded (with reasons)

| X | Idea | Source | Excluded because | Survivor |
|---|---|---|---|---|
| X1 | ReportLinter service | `test-structure.sh` | v3 §12/§15 already specify staged verification ("every factual statement cites an artifact; unresolved citations fail"); lint-after-the-fact is a compensating control for unvalidated markdown writes — Hermes validates on write | none (already in v3) |
| X2 | DuckDB read-only replica | `profiles/query-lite` | principle 7 names DuckDB a deferred enhancement; the injection vector (renderer emitting Intents) is foreclosed by construction — no intent path from the renderer, §18 T1, content hashes detect tampering | S9 |
| X3 | Redacted audit-digest layer | session capture hooks | duplicates §8.1 event log + §14 provenance; §18 defines no AgentAction trail; parallel audit = second write path; LLM redaction = non-deterministic leak risk | S6 |
| X4 | OverlapPeek (hash-based, blocking) | multi-wiki peek | §16.6 already makes the refuted screen cross-project; hash equality misses near-duplicates; archive peeking violates the curation invariant | S7 |
| X5 | promptfoo | `promptfooconfig.yaml` | principle 8; direct-mutation and gate-skip failure modes are foreclosed (gateway, §9.1); llm-wiki's NL-router ambiguity does not transfer to typed intents | S8 |
| X6 | Retraction / deletion | `/wiki:retract` | §16.1 immutability | S5 |
| X7 | Agent session rehydration | `/wiki:session rehydrate` | §13 fresh context per task; anchoring bias; Adversary sees artifacts only (ds §36) | S4 |
| X8 | Corroboration confidence scoring (quality-weighted) | article confidence | non-deterministic; §10.1 demoted `LITERATURE_SUPPORTED` for exactly this reason | S2 |
| X9 | Thesis verdict as ladder rung | thesis verdict | §10.2: literature promotes only to `PLAUSIBLE`; `SUPPORTED` requires pre-registration + gates | S1 (gate precondition) |
| X10 | Obsidian dual-linking / hub-topic organization | wiki layout | wrong domain (knowledge-management UX) | none |
| X11 | Retardmax verbatim | `--retardmax` | conflicts with §2 principle 4 confirmatory discipline | S10 (quarantined burst) |
| X12 | Fuzzy NL intent router | `/wiki <natural language>` | §8 typed intents by design | none |
| X13 | Multi-runtime plugin packaging | claude-plugin / codex / opencode | Hermes is a library, not an agent plugin | none |
| X14 | Structural lint of command tables / manifest drift (84 assertions) | `test-docs-consistency.sh` | repo hygiene for a docs-heavy plugin; Hermes integrity is enforced on write | none |

---

## 4. Adopted Steals

### S1 — Thesis-driven investigation

**Amends v3:** §6.1 (lifecycle states `LITERATURE_REVIEW`, `HYPOTHESIS_FORMULATION`), §9.1 (hypothesis-gate evidence pack), §10.2 (the `→ PLAUSIBLE` precondition "prose-level contradiction judgment belongs to the PLAUSIBLE synthesis and critique" — R1/F1), §13 (Researcher/Adversary task variants).

**New artifact — `ThesisEvidenceTable`:**

```text
ThesisEvidenceTable {
  thesis: ref(Hypothesis draft | Question)
  rows: [{
    claim_component: str,          # key variable / sub-claim decomposed from the thesis
    direction: FOR | AGAINST | NEUTRAL | MECHANISTIC | META,
    source_ref: ref(Source),       # required; validator rejects empty
    venue_tier: A | B | C,         # S2 allowlist, populated by DataValidationService
    subject_tags: {instrument, feature_family, claim_type},   # §10.2 R1/F1 schema
    falsification_relevance: str   # optional, schema'd
  }]
  falsification_criteria: [str],   # feeds NullHypothesis + falsification condition (§9.1)
  verdict: ThesisVerdict,
  round: int,
  counter_search: {performed: bool, terms: [str], result: NONE_FOUND | FOUND} | null
}
```

**Verdict enum (namespaced; never a ladder rung — no collision with §10):** `THESIS_SUPPORTED | THESIS_PARTIALLY_SUPPORTED | THESIS_CONTRADICTED | THESIS_INSUFFICIENT | THESIS_MIXED`.

**Deterministic verdict mapping (validator-computed, no LLM):**

| Row composition | Verdict |
|---|---|
| no rows, or all rows NEUTRAL/META | `THESIS_INSUFFICIENT` |
| ≥1 AGAINST row and 0 FOR rows | `THESIS_CONTRADICTED` |
| ≥1 FOR row and 0 AGAINST rows, ≥2 distinct sources | `THESIS_SUPPORTED` |
| FOR rows and AGAINST rows, FOR-count > AGAINST-count | `THESIS_PARTIALLY_SUPPORTED` |
| otherwise | `THESIS_MIXED` |

**Protocol (exact):**

1. **Decompose** the thesis into key variables → testable predictions → falsification criteria (schema'd fields). The falsification criteria are the direct feed for the §9.1 `NullHypothesis` + falsification condition.
2. **Dispatch round 1 balanced:** supporting, opposing, mechanistic, meta/review, adjacent. CONTRARIAN routing per S10 (Adversary profile, context-isolated).
3. **Bloat filter:** a source is skipped unless it relates to a claim variable; skip reasons recorded (S13). Higher skip rate = tighter focus; the skip rate is measured, never LLM-judged.
4. **Compile** the table; the verdict is computed by the mapping above.
5. **Round 2+ (anti-confirmation-bias):** the weaker side is targeted — compliance is a hard validator rule (below), mirroring the §10.2 null-result rule.

**Validator rules (all deterministic):** every row cites a non-superseded, non-refuted `Source`; `direction` non-empty; `subject_tags` match the R1/F1 schema; verdict matches the mapping; **round ≥ 2 ⇒ either ≥1 row on the round-1 minority direction, or a schema'd `counter_search` with `result: NONE_FOUND`** — a legitimately empty counter-evidence search must be recorded, exactly as §10.2 records "the question is open."

**Effects:** the §9.1 hypothesis-gate evidence pack gains `ThesisEvidenceTable` (thesis-mode projects); §10.2's prose-level contradiction judgment becomes a checkable structure; `THESIS_CONTRADICTED` / `THESIS_PARTIALLY_SUPPORTED` route to `HYPOTHESIS_FORMULATION` revision per existing gate semantics.

**Phase:** P1 (schema), P2 (validator + gate pack), P4 (protocol prompts).

**Tests:** fixture tables that must pass/reject; verdict-mapping table tests; round-2 counter-search compliance tests; gate-pack integration.

---

### S2 — Deterministic corroboration count

**Amends v3:** §10.1 (`EvidenceAttributes`), §5 (`DataValidationService`), §14 (typed `cites` edges).

**Amendment (exact):** add `corroboration_count: int` and `venue_tiers: {a: int, b: int, c: int}` to `EvidenceAttributes` — **reporting attributes only; never ladder preconditions** (§10.1 rules unchanged: the Evidence Validator answers "is this eligible?" without an LLM).

**Computation (deterministic, in `DataValidationService`):** count distinct `Source` artifacts with a `cites` edge to the claim (§14), deduped by venue+title fingerprint; tier per the operator-managed venue allowlist — A: peer-reviewed DOI (Crossref); B: arXiv/Semantic Scholar; C: web/other. No LLM anywhere in the computation; no "source quality" component (X8).

**Dispatch signal (controller-deterministic):** if `corroboration_count < C_MIN` (default 3, configurable) and the literature result is not null, `DIRECTOR_REVIEW` receives a proposal input to spawn a `LITERATURE` gap task ("find independent sources"). Advisory to the Director; never a gate precondition — the §10.2 null-result rule ("the question is open is itself a supported claim") is preserved verbatim.

**Phase:** P2 (attribute + count), P7 (allowlist population).

**Tests:** count correctness on fixture provenance graphs; allowlist tiering; null-result exemption; no-ladder-input assertion.

---

### S3 — Round-based gap drilling

**Amends v3:** §8 (reconcile loop), §7 (task graph), §13 (Director).

**Amendment:** synthesis artifacts gain schema'd `gaps: [{statement, type: UNANSWERED_QUESTION | SOURCE_DIVERSITY | OPEN_CONTRADICTION | COUNTER_EVIDENCE, subject_tags}]`. The round policy: the next round's `LITERATURE`/`EXPERIMENT_DESIGN` tasks are proposed **from the current gap list** — `DIRECTOR_REVIEW` proposes `INSERT_TASK` intents per gap; the gateway validates; each round is a new subgraph instantiation (§7 preserved). The loop never invents workflow: a gap with no matching task proposal is a gap in the plan, not a license to auto-dispatch (the §8 "never" list preserved). Round budget comes from the §19 budget ledger.

**Phase:** P3 (policy), P4 (Director proposal).

**Tests:** fixture loop runs where round-2 task set must equal round-1 gap list; gaps with no proposal assert no auto-dispatch.

---

### S4 — Director digest, human resume, feedback curation

**Amends v3:** §13 (`context_policy`), §14.6 (honesty instrument), §21 (vault).

**`DirectorDigest` (new, controller-produced):** compact structured summary — lifecycle state, task statuses, gate verdicts, open contradictions, budget ledger, model-tier usage, pointers to artifact ids. This is the implementation pattern for v3 §13's "Director sees structured summary, never raw pages," with a static size class per the M1 context-budget classes. Never raw pages; never artifact bodies.

**`HumanResumeDigest`:** on `AWAITING_HUMAN` resume / `GateExpired` / operator request — "where did I leave off" (state, pending decisions, deadlines). UI/UX concern; delivered via the vault-inbox; never agent context.

**`FeedbackCurator`:** high-signal human corrections / preferences / approvals / plan acceptances captured as redacted candidates (deterministic field-drop redaction: labels + event refs, never payload bodies); generic acknowledgements ignored; explicit promotion into calibration data for the honesty instrument (§14.6).

**Hard rule (X7, preserved):** no digest is ever rehydrated into Researcher/Adversary context. §13 fresh-context-per-task and ds §36 "Adversary sees artifacts only" are preserved verbatim. The controller remembers; the agent stays amnesiac.

**Phase:** P3 (resume), P4 (digest), P10+ (curator calibration).

**Tests:** digest size caps; redaction determinism; promotion requires an explicit intent; no-rehydration assertion.

---

### S5 — Supersede-and-invalidate cascade

**Amends v3:** §8 event catalog, §7 (`INVALIDATED`), §10.2 (screen), §14 (`supersedes`), §16.1 (immutability), §21 (vault).

**New intent type:** `RETRACT_SOURCE {source_ref, reason, human_decision_ref}` — human-initiated (per §9.2 override discipline: human decisions are recorded states), gateway-validated; requires a cited reason and a recorded `HumanDecision`.

**Cascade (controller-computed, deterministic, via the §14 recursive CTE):**

1. Emit `SourceRetracted` (event added to the §8.1 catalog).
2. Write a new `Validation`(FAIL) / `Critique` / `ResearchDecision` artifact with a `supersedes` edge to the source.
3. Mark every downstream artifact reachable via `used_as_input` / `derived_from` / `cites` as `INVALIDATED` (§7 semantics: archived-not-deleted).
4. Add the source to the inadmissible-source screen (refuted registry, §16.6) so §10.2's structural screen rejects future citations.
5. Regenerate the derived vault projection (§21 single writer) without the source.

**No deletion anywhere** (§16.1 preserved verbatim); history remains append-only and auditable.

**Phase:** P2 (provenance), P3 (gateway + cascade).

**Tests:** cascade fixture graph; `INVALIDATED` propagation; vault regeneration; no-deletion assertion (content-addressed store unchanged).

---

### S6 — Bounded event payloads

**Amends v3:** §8.1 (event catalog, `payload_json`).

**Policy (exact):** every event type declares a payload schema; `payload_json` is size-capped (default 4 KiB; larger payloads become content-hash refs into the artifact store); secrets never enter payloads (tokens/passwords excluded by schema, enforced by a deterministic validator on the write path); honesty-instrument fields (`model_ref`, `regime_tag`, decision outcomes, §14.6) are **required** on the events that feed calibration. No new audit layer — this amends the existing event schema (X3).

**Phase:** P1.

**Tests:** payload-size cap; secrets-out validator; calibration fields present.

---

### S7 — Near-miss refuted-registry advisory

**Amends v3:** §16.6 (registry), §10.2 (screen), §13 (Director).

**Amendment:** on hypothesis proposal, the controller computes signature similarity against the **curated refuted registry** using the §10.2 screen axes (instrument × feature-binding signature × strategy family). Output: `NearMissRefutation {hypothesis_ref, matched_refuted_ids, similarity_axes}` — **advisory only**; surfaced to the `DIRECTOR_REVIEW` proposal and the §9.1 gate pack as an advisory field. Never blocking; queries the curated registry only, never archived project data (curation invariant, §16.6, preserved). X4's hash-based archive peeking is excluded; the screen itself (blocking) already exists and is explicitly cross-project.

**Phase:** P2 (registry), P3 (controller), P4 (Director).

**Tests:** similarity computation on fixture signatures; advisory-not-blocking assertion; registry-only query assertion.

---

### S8 — Golden-scenario Director fixtures

**Amends v3:** §13 (ModelClient record/replay, swap protocol), §5 (ModelClient service).

**Amendment:** a ModelClient-owned golden scenario suite (no external framework — principle 8, X5) asserting **intent-choice correctness**, not merely behavioral drift:

- (a) pre-registered hypothesis failed → the proposal includes the human-approved abandonment path (`ABANDON` intent + `ResearchDecision` payload referencing the failure artifact);
- (b) replication disagreement → `CONTRADICTION_RESOLUTION` / `UNCERTAIN` routing proposal, never silent `SUPPORTED`;
- (c) gate timeout → extend / auto-pause / escalate proposal;
- (d) off-plan test at `ANALYSIS` → statistical-gate failure routing (never acceptance, R3).

**Assertions:** intent type, payload schema validity, required artifact refs present; malformed output must fail as a retryable task failure (never a partial write, §13). CI runs **deterministic replay** keyed to exact model version; live runs are scheduled, budget-ledger aware; a cross-tier model swap re-records fixtures (§13 swap protocol).

**Phase:** P4.

**Tests:** the suite itself; replay determinism; swap re-recording.

---

### S9 — Write-path enforcement tests

**Amends v3:** §8.1 (observers), §18 (T1), §21 (renderer).

**Amendment:** deterministic tests assert observers and the vault renderer never open a write transaction on research state; the renderer opens SQLite in **read-only mode** by config; observers produce events only through the event-append API. No DuckDB replica (principle 7, X2) — cheap defense-in-depth, not new architecture.

**Phase:** P3 (tests), P5 (renderer).

**Tests:** write-transaction assertions; read-only-open assertion.

---

### S10 — Researcher angle variants + quarantined exploratory burst

**Amends v3:** §13 (task-type variants), §2 principle 4 (confirmatory ≠ exploratory).

**Angle slots (new field on `LITERATURE` tasks):** `ACADEMIC, TECHNICAL, APPLIED, NEWS, CONTRARIAN` (default 5); deep mode adds `HISTORICAL, ADJACENT, DATA_STATS` (8). CONTRARIAN routing goes to the Adversary profile (context isolation preserved, ds §36).

**`ExploratoryBurst` mode:** operator-opt-in, budget-capped, max-speed ingest with reduced synthesis rigor; outputs classified `EXPLORATORY_DRIFT` (§11 preserved: archived, visible, useful for hypothesis generation, **incapable of driving any transition toward SUPPORTED or above**). The burst never drives transitions; the §11 hash-mismatch classification is the quarantine mechanism (X11).

**Phase:** P4 (variants), P4 (burst dispatch, budget ledger).

**Tests:** angle routing; burst outputs never satisfy §10.2 promotion preconditions.

---

### S11 — Tool-runtime operational defaults

**Amends v3:** §15 (tool model), §18 T3/T4.

**Defaults (exact):** bounded downloads — timeouts, file-size caps, content-type checks, IPv4 retry; scale classes `tiny → huge` bound rows/media/rounds per task; dry-run-first for destructive tool operations; **structural guardian** — a deterministic post-write integrity check (schema, orphan refs, registry drift) that auto-fixes trivial issues with a recorded event and alerts otherwise, running on the artifact write path (not a separate lint layer, X1).

**Phase:** P5.

**Tests:** caps enforced; dry-run produces no writes; guardian auto-fix events.

---

### S12 — Dataset manifests

**Amends v3:** §16 (artifact model), §12 Data gate, §5 `DataValidationService`.

**New artifact — `DatasetManifest`:**

```text
DatasetManifest {
  id, location: path | url,
  profile: {format, size, headers, schema_observations},
  query_recipes: [str],
  content_hash, provenance
}
```

Indexes data that stays external; never copies data into the store (§16 preserved). Feeds the Data gate's deterministic schema/gap/duplicate checks; content-hash verification unchanged.

**Phase:** P1 (schema), P7 (service).

**Tests:** manifest validation; no-copy assertion.

---

### S13 — Skip-rate metric

**Amends v3:** §7 (task record), §14.6 (honesty instrument).

**Amendment:** research tasks record `sources_considered`, `sources_skipped` with deterministic skip reasons (`IRRELEVANT_TO_THESIS | DUPLICATE | UNTRUSTED_VENUE | PAYWALL | OTHER`) and `skip_rate`. The honesty instrument gains a drift signal: a rising `IRRELEVANT_TO_THESIS` rate may indicate thesis-filter bloat or source narrowing (S1's bloat filter; S10's burst).

**Phase:** P2 (schema), P10+ (instrument).

**Tests:** skip-reason classification; drift-signal computation.

---

### S14 — Provenance audit and freshness service

**Amends v3:** §14 (recursive CTE), §12 Reporting gate, §16.2 (replication freshness).

**Amendment:** a deterministic `AuditView` over the §14 recursive CTE answers "why does Hermes believe this?" for any artifact — the chain, not the prose. Freshness rules (last-updated, regime-taxonomy version) drive a scheduled staleness scan. Where trust is in question, the audit **proposes** `REPLICATION` re-runs executed fresh (§16.2, cache-bypassed) — proposal only, never auto-execution (the §8 "never" list preserved).

**Phase:** P2 (CTE), P10+ (audit).

**Tests:** chain correctness on fixture provenance; freshness rules; no-auto-execution assertion.

---

### S15 — DATA_ACQUISITION triage

**Amends v3:** §5 (`DataValidationService`), §13 (`DATA_ACQUISITION` thin task).

**Deterministic heuristics:** small durable set → inventory records; large / unstable / media-heavy → corpus manifest (S12) or collection ingest; one-off → ingest/query only; big pivots start with a sample table before records are written. No LLM in the triage; the service decides, the thin task executes.

**Phase:** P7.

**Tests:** triage classification fixtures.

---

### S16 — Frozen-brief promotion (project-level pre-registration)

**Amends v3:** §6.1 (`SCOPING`), §11 (pre-registration discipline), §9.2 (optional question gate).

**Amendment:** `SCOPING` produces a frozen `ScopeBrief` (schema'd artifact behind the `ScopeDefined` event); any change is a new version with a supersession edge and recorded rationale (the §11 amendment pattern at project level); promotion into `EXPERIMENT_DESIGN` cites the frozen brief. The optional question gate (§9.2) evaluates against the brief.

**Phase:** P1/P2.

**Tests:** frozen-brief immutability; amendment supersession; promotion-citation requirement.

---

## 5. Adoption into v3 (exact locations)

| Amendment | Lands in v3 at | New/changed code | IDR |
|---|---|---|---|
| S1 | §9.1 gate pack; §10.2 precondition text; §13 task variants; event catalog (`ThesisInvestigationCompleted`) | `hermes/research/thesis.py` (P2); `hermes/agents/researcher.py`, `adversary.py` (P4) | — |
| S2 | §10.1 `EvidenceAttributes`; §5 `DataValidationService` | `hermes/research/evidence.py` (P2); `hermes/tools/research_sources.py` allowlist (P7) | — |
| S3 | §8 round policy; §7 task graph | `hermes/research/reconcile.py` (P3) | — |
| S4 | §13 context_policy; §14.6; §21 | `hermes/tools/context.py` digests (P4); vault inbox digest (P3) | **yes** (privacy) |
| S5 | §8 event catalog (`SourceRetracted`); §7 `INVALIDATED`; §16.6 screen | `hermes/core/intents.py` (P3); `hermes/research/provenance.py` cascade (P2) | **yes** (new intent) |
| S6 | §8.1 payload policy | `hermes/research/events.py` validator (P1) | **yes** (payload policy) |
| S7 | §16.6; §10.2; §13 | `hermes/research/evidence.py` (P2); `reconcile.py` (P3) | — |
| S8 | §13 ModelClient; §5 | `hermes/agents/director.py` fixtures + `tests/` (P4) | — |
| S9 | §8.1; §18 T1; §21 | tests (P3); renderer config (P5) | — |
| S10 | §13 variants; §2.4 | `hermes/agents/researcher.py`; burst dispatch in `reconcile.py` (P4) | **yes** (burst opt-in) |
| S11 | §15; §18 T3/T4 | `hermes/tools/` runtime (P5) | — |
| S12 | §16 artifact model; §12 Data gate | `hermes/research/evidence.py` manifest (P1/P7) | — |
| S13 | §7 task record; §14.6 | `hermes/research/registration.py` (P2) | — |
| S14 | §14 CTE; §12; §16.2 | `hermes/research/provenance.py` `AuditView` (P2/P10+) | — |
| S15 | §5; §13 | `hermes/tools/research_sources.py` (P7) | — |
| S16 | §6.1; §11; §9.2 | `hermes/research/registration.py` `ScopeBrief` (P1/P2) | — |

IDR count: **4** (S4, S5, S6, S10). All other amendments extend existing contracts and need no new decision record.

---

## 6. Open questions

1. **Registry locality (S7/S5):** single-operator default means one global refuted registry; confirm the isolation story if Hermes ever serves multiple operators (refutation data privacy across operators).
2. **`C_MIN` default (S2):** 3 is a starting point; measure against real literature tasks at P7.
3. **Payload cap (S6):** 4 KiB default vs. artifact-store refs for larger payloads — confirm against real event sizes at P1.
4. **`RETRACT_SOURCE` proposers (S5):** human-only (recommended, §9.2 discipline) vs. a `DIRECTOR_REVIEW` proposal subject to human approval.
5. **Skip metrics in reporting (S13):** whether skip rate surfaces in the Reporting gate's uncertainty/limitations section (§12).
6. **Burst workspace (S10):** separate workspace for isolation vs. same workspace with `EXPLORATORY_DRIFT` classification (recommended: same workspace; classification is the quarantine).
