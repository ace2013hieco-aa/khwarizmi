# HERMES DG-5 — Persistence → Research Inversion Design Gate

**Date:** 2026-09-21
**Authorizing baseline:** `9cf1837a096f2e8ffa818614e6a77d87d46c9a48` (certified G-1 revision, `main`)
**Scope:** the `src/hermes/persistence/` → `src/hermes/research/` dependency direction — read-only design gate
**Report:** this file (the only repository change DG-5 makes)

---

## §0 Executive verdict

```text
DG-5 — DESIGN GATE PASSED / NO ARCHITECTURAL INVERSION CORRECTION AUTHORIZED
```

Measured physically at `9cf1837` with `ast` (never grep prose, never inherited conclusions):

* **13** true persistence→research runtime import statements (§3). DG-4's "16 sites" overcounts by three:
  one is `TYPE_CHECKING`-only (`source_outcomes.py:39-40`, `FetchedPayload`), one is
  persistence→**tools** not research (`source_outcomes.py:45`), one is intra-persistence
  (`repositories.py:51`). A further DG-4 omission is corrected here:
  `program_obligations.py:41` (intra-persistence private import) was never listed.
* Of the 13: **2 true inversions (A)**, **6 intentional exceptions (B)**, **2 misplaced pure
  utilities (C)**, **2 domain-type references (D)**, **1 false positive (I)** (§6).
* **GREEN candidates: none. YELLOW: one** (`_json_loads` centralization — identified, **not
  authorized**, needs its own implementation gate; §18). **RED: twelve** inversion sites plus
  every protected surface in §22. **REJECTED: three** attractive-but-aesthetic proposals (§19),
  including `_is_extract_spec` consolidation.
* The three documented cycle pairs are real and each is held together by an intentional,
  IDR-recorded design (§5). Removing any leg weakens a certified invariant.
* `_is_extract_spec`: **KEEP THREE COPIES** (§8). `_json_loads`: YELLOW, deferred (§9).
  `_research_program_row_to_dict`: **KEEP** — a persistence row mapper consumed in the allowed
  direction (§10).
* Identity authorship, transaction timing, N9 fencing, project isolation, and journal ordering
  are unchanged by every disposition in this report, because this report authorizes no
  implementation (§11–§15).

**DG-5 finds no safe architectural inversion correction.** That is the preferred result, not a
failure to find one: the upward dependencies that look like layering violations are, on
physical inspection, the certified Model-D integrity boundaries (IDR-018 EC-V6-11..16, IDR-026
Decision 2, IDR-036 D3/D5), the HR-08 completion choke point, and the admission/write-path
agreement checks — each explicitly designed, each tested, each load-bearing.

---

## §1 Baseline identity

```text
repository          github.com/ace2013hieco-aa/khwarizmi-research
branch              main
HEAD                9cf1837a096f2e8ffa818614e6a77d87d46c9a48
origin/main         9cf1837a096f2e8ffa818614e6a77d87d46c9a48    (HEAD == origin/main)
tracked changes     none (working tree clean apart from pre-existing untracked material)
untracked (pre-existing, untouched)
                    IDEA.md, Prompts/, desktop.ini, logos/, obsidian-vault/,
                    orci.json, orhead.json, ortree.json
```

`git log --oneline -5`:

```text
9cf1837 docs(archive): certify G-1 proposed-set extraction
b9a30a9 refactor(persistence): extract proposed-set helper
4b501e9 docs(archive): complete DG-4 repository structural design gate
0f86189 docs(archive): certify S4 S5 cone closure extraction
f54af56 refactor(gateway): extract S5 cone closure
```

The G-1 extraction moved `SourceOutcomeRepository._proposed_set` to module level
(`source_outcomes.py:184-200`); all DG-4 line references into `source_outcomes.py` below line
184 therefore shift by +19. Nothing in this gate modifies, stages, reads-for-authority, or
deletes the untracked items.

---

## §2 Source/document authority

The physical source wins wherever a document disagrees. Required reading was completed
(`AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/STATE.md`,
`hermes_research_architecture_v6.md`, DG-4, G-1) plus the owning IDRs (IDR-018, IDR-026,
IDR-028, IDR-036, IDR-038). DG-4 conclusions were re-verified from source, not inherited;
three DG-4 census entries are corrected in §3 (one `TYPE_CHECKING` overcount, one
tools/research layer miscategorization, one intra-persistence miscount plus one omission).
V6 §28.2 Model D (layered trust) and the IDR integrity-boundary addenda are normative for
§6–§7: several upward imports exist **because** the IDRs require the repository to re-derive
with the research layer's own pure helpers ("one deterministic derivation, never two").

---

## §3 Complete dependency census

Method: `ast.parse` over `src/hermes/persistence/`, `src/hermes/research/`, `src/hermes/core/`,
`src/hermes/tools/` at HEAD. Docstrings/comments/string literals excluded by construction
(AST import nodes only). Test-only imports excluded.

### §3a Persistence → research runtime imports (13 statements — the complete list)

| # | Persistence site | Research dependency | Import type | Runtime? | Used for | Current semantic owner | Risk |
| - | ---------------- | ------------------- | ----------- | -------- | -------- | ---------------------- | ---- |
| 1 | `failure_classifications.py:52` | `hermes.research.failure_classification`: `FAILURE_CLASS_SCHEMA_VERSION, FailureClass, FailureClassification, FailureClassificationDraft, FalsificationRecord, PermittedAction, classify_failure, parse_contributing_factors, permitted_actions_for, requires_human_confirmation_for` | top-level | **yes** — `classify_failure` re-run pre-BEGIN at `:168`; `FailureClass` at `:157,:713`; schema check at `:191`; digest re-verify at `:734,:741,:745,:779`; annotations at `:130-131,:134,:508-509` | research (domain substrate, IDR-036) | medium — write-path semantics depend on it |
| 2 | `program_obligations.py:55` | `hermes.research.programs`: `canonical_json, sha256_hex` | function-local (inside `validation_verdict_id_of:53`) | **yes** — pure derivation at `:56-60`, no conn, no tx | shared pure primitive, currently housed in research | low — pure, no snapshot |
| 3 | `program_obligations.py:169` | `hermes.research.programs`: `canonical_json, sha256_hex` | function-local (inside `satisfaction_id_of:166`) | **yes** — pure derivation at `:170-175`, no conn, no tx | shared pure primitive, currently housed in research | low — pure, no snapshot |
| 4 | `repositories.py:52` | `hermes.research.claims`: `CLAIM_SCHEMA_VERSION, DEREFERENCE_DIMENSIONS, REF_SEP, ContextResolver, ExtractionResult, ExtractionVerdict, assumption_id_of, claim_id_of` | top-level | **yes** — `claim_id_of` verify at `:1997`, `assumption_id_of` at `:2022` (both in-tx); `REF_SEP` at `:1900-1902`; `DEREFERENCE_DIMENSIONS` at `:2044`; `ExtractionVerdict.ADMITTED` at `:2288`; `ContextResolver` annotation at `:1870`; `ExtractionResult` annotation at `:1942`; schema checks at `:2006-2033` | research (validator + identity, IDR-026) | high — in-tx identity verification |
| 5 | `repositories.py:62` | `hermes.research.extraction`: `EXTRACT_TEMPLATE` | top-level | **yes** — `_is_extract_spec` body at `:1831`; write-path refusal message at `:2093` | research (admission vocabulary, IDR-028) | low — single constant, must agree with admission |
| 6 | `repositories.py:63` | `hermes.research.programs`: `CompilationResult, CompilationStatus` | top-level | **mixed** — `CompilationResult` annotation-only at `:1235` (never evaluated: `from __future__ import annotations` at `:27`); `CompilationStatus.COMPILED.value` executed in-tx at `:1599` | research (compiler contract, IDR-018 E6/E7) | low — gate token |
| 7 | `repositories.py:64` | `hermes.research.thesis`: `EmptyResultResolver` | top-level | **no** — annotation-only at `:2503`, never evaluated (`__future__.annotations`) | research (validator protocol) | none — import executes, name never evaluated |
| 8 | `repositories.py:236` | `hermes.research.completion`: `can_complete_research` | function-local (inside `ProjectRepository.transition_lifecycle:201`) | **yes** — called **inside** `BEGIN IMMEDIATE` (`:219` → `:236-237`) with `(self._conn, project_id)` | research (HR-08 governance rule) | high — in-tx domain rule; cycle pair (c) leg |
| 9 | `repositories.py:1259` | `hermes.research.programs`: `program_to_dict` | function-local (inside `ResearchProgramRepository.record:1232`) | **yes** — pre-BEGIN serialization at `:1571` (BEGIN at `:1502`) | research (canonical serialization) | low — pre-tx, pure of snapshot |
| 10 | `repositories.py:1298` | `hermes.research.programs`: `SUPPORTED_PROGRAM_SCHEMA_VERSIONS, content_hash_of, derive_program_obligations, input_hash_of, program_id_of, validate_program_epistemic` | function-local (inside `record:1232`) | **yes** — pre-BEGIN integrity re-derivation at `:1306-1355` (BEGIN at `:1502`; EC-V6-16 "before the transaction") | research (compiler identity + epistemics, IDR-018) | medium — certified boundary, pre-tx |
| 11 | `repositories.py:1379` | `hermes.research.programs`: `_SLOT_REF_MAX_LENGTH, _SLOT_REF_RE, MAX_SLOT_RATIONALE` | function-local (inside `record:1232`) | **yes** — pre-BEGIN slot validation at `:1391-1443` | research (**private** namespace) | medium — private reach; E6 defense-in-depth |
| 12 | `repositories.py:2440` | `hermes.research.thesis`: `empty_result_content_hash_of, empty_result_id_of` | function-local (inside `EmptyResultArtifactRepository.record:2432`) | **yes** — pre-BEGIN identity derivation at `:2455-2457` (BEGIN at `:2468`; AR-03) | research (content identity) | medium — identity authorship consults upward |
| 13 | `source_outcomes.py:41` | `hermes.research.source_templates`: `SOURCE_FETCH_TEMPLATE, SOURCE_SEARCH_TEMPLATE` | top-level | **yes** — in-tx task-template binding at `:496-497` and `:586` (V6-P7-A2-01) | research (task vocabulary) | low — constants, tx only as comparisons |

### §3b Explicitly NOT counted (with reason)

| Site | What | Why not an inversion |
| ---- | ---- | -------------------- |
| `source_outcomes.py:39-40` | `ArtifactRepository`, `FetchedPayload` | inside `if TYPE_CHECKING: (:38)` — never executed; `FetchedPayload` is tools-layer in any case. DG-4 §10 item 13 overstated this as runtime. |
| `source_outcomes.py:45` | `content_hash_of_search_result, observation_hash_of_search_result, outcome_record_hash, search_result_from_mapping, search_result_to_mapping` | `hermes.tools.research_sources` — the **tools** layer, not research. Consumed for in-tx identity authoring/verification; tools→research direction is separately recorded debt (`research_sources.py:33`, `hazards.py:137`). |
| `repositories.py:51` | `_source_artifact_resolves` | intra-persistence (`source_outcomes` → same layer). DG-4 §10 item 16's only entry; not an inversion. |
| `failure_classifications.py:448,476,497,555,584` | `_json_loads` (5 function-local sites) | intra-persistence (same layer, private). |
| `failure_classifications.py:118` | `ArtifactRepository` | intra-persistence, function-local. |
| `source_outcomes.py:275-283` | `ArtifactRepository, _json_loads` | intra-persistence, function-local (stored as `self._json_loads`). |
| `program_obligations.py:41` | `_research_program_row_to_dict` | intra-persistence, top-level. Omitted from DG-4 §10; recorded here. |
| `src/hermes/core/**/*.py` | — | **zero** imports of `hermes.research`/`hermes.persistence` anywhere in core (verified). Core is clean. |

No dynamically resolved references (`importlib`, `__import__`, `import_module`) exist in
`src/hermes/persistence/`. No `TYPE_CHECKING` runtime imports of research exist.

---

## §4 Reverse dependency census

### §4a Research → persistence private imports (re-verified, both genuine)

| Site | Symbol | Enclosing scope | Why research needs it | Disposition |
| ---- | ------ | --------------- | --------------------- | ----------- |
| `research/gateway.py:1487` | `_json_loads` from `hermes.persistence.repositories` | function-local in `_resolve_program_in_project:1480` (program-ref resolver); used once at `:1503` (`d["hypotheses"] = _json_loads(...) or []`) | parse the `research_programs` row the gateway itself just SELECTed (`:1491-1499`, project-scoped) | allowed direction, private name — YELLOW, see §9 |
| `research/completion.py:63` | `_research_program_row_to_dict` from `hermes.persistence.repositories` | top-level; used at `:117` in `_current_program:104` (head-of-chain read, `ORDER BY version DESC LIMIT 1`, project-scoped) | parse the program row for the HR-08 eligibility predicate | allowed direction, private name — KEEP, see §10 |

Both are genuinely persistence concepts (row→dict mappers over `sqlite3.Row` + `_json_loads`
calls at `repositories.py:1756-1765`): the `hypothesis_json`/`prediction_json`/
`discrimination_json`/`evidence_json`/`gate_json`/`methodology_json` columns are a
persistence storage shape, and the parse lives next to the writer that produces it.

### §4b Per-symbol reverse census (all production + test callers)

| Symbol | Producer layer | Production callers | Test callers | Private? | Identity-bearing? | Tx-bearing? | Journal-bearing? | N9-bearing? |
| ------ | -------------- | ------------------ | ------------ | -------- | ----------------- | ----------- | ---------------- | ----------- |
| `_research_program_row_to_dict` (`repositories.py:1756`) | persistence | `repositories.py:1524,1627,1638,1647,1658,1666`; `program_obligations.py:214`; `controller.py:2829,3471,3759`; `completion.py:117` | `test_controller_q02.py:966,972` | yes (`_`) | no (parses stored identity, authors none) | no (pure of conn; callers own snapshots) | no | no |
| `_json_loads` (`repositories.py:86`) | persistence | `repositories.py` ×13 sites (`:488-491,878,889,1698,1759-1764,1771,1778-1779,2088,2498`); `failure_classifications.py` ×5 (`:450-451,478,499,573,604`); `source_outcomes.py` via `self._json_loads` (`:360,494,584,987`); `gateway.py:1503` | none (no test imports it) | yes | no (parse only) | no | no | no |
| `_source_artifact_resolves` (`source_outcomes.py:96`) | persistence | `failure_classifications.py` (evidence resolver); `repositories.py:51` consumers; `gateway.py` (incl. in-tx `:2262`) | `test_provider_orchestration.py:849,868,870` | yes | no (resolution, not authorship) | **yes — takes `conn`, executes SQL in caller's snapshot** | no | **yes — resolution substrate of N9** |
| `source_artifact_retracted` (`source_outcomes.py:159`) | persistence | `failure_classifications.py:50,378,411`; `contradiction_candidates.py:16,62`; `gateway.py:65,2262` | `test_n9_retraction_admission.py:43,241,261-262,340-341` | no (public) | no | **yes — conn-bound read** | no | **yes — the canonical N9 predicate** |
| `validation_verdict_id_of` (`program_obligations.py:53`) | persistence (via research primitives) | `program_obligations.py:126` (write path); tests | `test_program_obligations.py:215` | no | **yes — authors `vv_` ids** | participant (called on write path, no own BEGIN) | no | no |
| `satisfaction_id_of` (`program_obligations.py:166`) | persistence (via research primitives) | `program_obligations.py:286` (write path); tests | `test_program_obligations.py:116` | no | **yes — authors `ss_` ids** | participant | no | no |
| `_is_extract_spec` (×3) | one per layer (§8) | `repositories.py:2089`; `extraction.py:368`; `gateway.py:3266` | none directly (constant `EXTRACT_TEMPLATE` used in `test_controller_q02.py:28,65`, `test_extraction_pipeline.py:36,143`, `test_program_obligations.py:33,376,381`) | yes (×3) | no | consults in-tx task reads at each site | no (admission predicates) | no |

Ownership is never inferred from filename: `_research_program_row_to_dict` is persistence-owned
because it parses a persistence storage shape beside its writer; `validation_verdict_id_of`
is persistence-owned authorship even though its primitives live in research; N9 predicates are
persistence-owned because they read the persistence substrate (`artifacts` + `provenance_edges`).

---

## §5 Cycle analysis

All three documented pairs re-verified at HEAD (post-G1 line numbers). Each pair has exactly
one lazy leg — the "lazy-guarded" description is substantively correct; four ARCHITECTURE.md
line references are stale (§23).

### Pair (a) — `persistence.repositories` ⇄ `persistence.source_outcomes` (intra-layer)

```text
cycle       repositories.py:51 eager → source_outcomes (_source_artifact_resolves)
            source_outcomes.py:783 lazy → repositories (_append_event_to_db, inside _commit)
root cause  the single journal writer lives in repositories.py; the source-outcome
            _commit must emit SourceRetracted atomically with its rows (same tx)
semantic    persistence → persistence (NOT a research inversion; DG-4 §10 item 16 correctly
            separated). Import cycle only, no layer violation.
candidate   none — relocating the writer breaks mutation→event→commit atomicity (§15)
safe?       NO — RED. evidence: source_outcomes.py:781-790 (lazy import + call inside
            record's BEGIN IMMEDIATE..COMMIT at :313..:321)
```

### Pair (b) — `persistence.repositories` ⇄ `research.extraction`

```text
cycle       repositories.py:62 eager → research.extraction (EXTRACT_TEMPLATE)
            research/extraction.py:349 lazy → persistence.repositories
            (ClaimAssumptionRepository, NotFoundError, TaskRepository, inside function)
root cause  admission vocabulary (the EXTRACT marker) is research-owned; the write path
            must refuse non-EXTRACT tasks with the identical comparison (V6-P7-A2-01)
semantic    intentional AGREEMENT coupling: repositories.py:1820 docstring — "the same
            comparison the gateway applies at admission (V6-P7-E01), so admission and
            the write path never disagree"
candidate   moving EXTRACT_TEMPLATE downward (core) or duplicating it per layer
safe?       NO — RED. A move does not break the import cycle usefully (extraction.py:349
            still needs repositories for task reads); duplication recreates exactly the
            divergence hazard the single constant prevents. evidence: repositories.py:2089,
            extraction.py:368, gateway.py:3266 (three coordinated checks, one constant)
```

### Pair (c) — `persistence.repositories` ⇄ `research.completion`

```text
cycle       repositories.py:236 lazy → research.completion (can_complete_research)
            research/completion.py:63 eager → persistence.repositories
            (_research_program_row_to_dict)
root cause  HR-08 choke point: transition_lifecycle refuses COMPLETED unless the
            completion invariant holds (repositories.py:226-243: "the single choke point
            so no current or future driver can reach COMPLETED without the invariant
            holding"); the completion predicate itself parses program rows via the
            persistence mapper (completion.py:104-117)
semantic    TRUE INVERSION with a stated fail-closed rationale (category A, §6 item 8):
            a domain rule evaluated inside a persistence transaction, taking conn
candidate   lift the HR-08 check out of transition_lifecycle into gateway/controller
safe?       NO — RED. Removal weakens "no driver reaches COMPLETED" to "no gateway path
            reaches COMPLETED"; the lazy leg hides the reversal but the reversal is the
            design. evidence: BEGIN at :219 precedes the call at :237; can_complete_research
            takes conn at completion.py:258-259 and re-reads via _current_program
```

Import cycle ≠ architectural inversion: pair (a) is a cycle with no inversion; pairs (b)/(c)
are inversions with cycles. In all three, removing one leg either breaks atomicity,
recreates divergence, or weakens a fail-closed choke point.

---

## §6 Classification of every inversion

Each of the 13 runtime dependencies receives exactly one classification:

| # | Site | Class | Evidence |
| - | ---- | ----- | -------- |
| 1 | `failure_classifications.py:52` | **B — INTENTIONAL ARCHITECTURAL EXCEPTION** | IDR-036 D3 designs the substrate as pure (no SQL/imports) precisely so the write path re-runs it; `record:127` docstring "the write path re-runs the substrate with the real resolver bundle and never trusts an authored hash (D1, EC-V6)"; `classify_failure` at `:168` runs pre-BEGIN (`:233`) |
| 2 | `program_obligations.py:55` | **C — PURE UTILITY MISPLACED** | `canonical_json` (`programs.py:366-369`: `json.dumps` + sort + compact) and `sha256_hex` (`:372-378`: hashlib wrapper) are stdlib-thin; `programs.py` imports nothing from hermes (verified §7); consumers span persistence, tools (`research_sources.py:33`), claims, thesis |
| 3 | `program_obligations.py:169` | **C — PURE UTILITY MISPLACED** | same primitives, second identity author (`ss_` at `:170-175`) |
| 4 | `repositories.py:52` | **B — INTENTIONAL ARCHITECTURAL EXCEPTION** | IDR-026 Decision 2: "every claim's `claim_id`/`content_hash` is re-derived with the *same* `claim_id_of`/`assumption_id_of` helpers"; in-tx verification at `:1997-2026` is the certified pattern, not an accident |
| 5 | `repositories.py:62` | **B — INTENTIONAL ARCHITECTURAL EXCEPTION** | single canonical constant prevents admission/write divergence (§5b); V6-P7-A2-01/E01 agreement |
| 6 | `repositories.py:63` | **D — DOMAIN TYPE OWNERSHIP ERROR (directional only)** | `CompilationResult`/`CompilationStatus` correctly owned by research (IDR-018); persistence references the COMPILED gate token (E6/E7) at `:1599` in-tx; annotation use at `:1235` never evaluates |
| 7 | `repositories.py:64` | **I — FALSE POSITIVE / NOT AN INVERSION** | `EmptyResultResolver` (`thesis.py:49`: a `Callable` alias) used solely in an unevaluated annotation (`:2503`, `__future__.annotations`); the import statement executes but the name costs nothing at runtime |
| 8 | `repositories.py:236` | **A — TRUE ARCHITECTURAL INVERSION** | domain rule evaluated inside a persistence tx with `conn` (§5c); genuine inversion, RED because the choke point is the design |
| 9 | `repositories.py:1259` | **D — DOMAIN TYPE OWNERSHIP ERROR (directional only)** | `program_to_dict` is canonical research serialization (`programs.py:1463`); persistence uses it pre-BEGIN (`:1571` < `:1502`) to build the row it owns |
| 10 | `repositories.py:1298` | **B — INTENTIONAL ARCHITECTURAL EXCEPTION** | IDR-018 EC-V6-11..16 integrity boundary: "the repository now re-derives `content_hash`, `program_id`, `input_hash` with the compiler's own pure helpers"; pre-BEGIN (`:1306-1355` < `:1502`) per EC-V6-16 |
| 11 | `repositories.py:1379` | **A — TRUE ARCHITECTURAL INVERSION** | persistence reaches into research's **private** namespace (`_SLOT_REF_RE`, `_SLOT_REF_MAX_LENGTH`); genuine smell, RED because the E6 slot re-check at write path (`:1391-1443`, pre-BEGIN) is certified defense-in-depth ("the same defense-in-depth pattern as AR-01", `:1374-1378`) |
| 12 | `repositories
...[truncated 20887 chars]