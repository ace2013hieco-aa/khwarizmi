# HERMES v6 — AUTHORITY CLAIM EVIDENCE MAP

**Step 2 deliverable (extraction only — no verdict).** Prepared by the independent verifier for the Hermes v6 closure gate. Evidence base: repo HEAD `7de1135` + uncommitted working-tree status edit (`hermes_research_architecture_v6.md` converted to candidate status), full source, git history, worktree re-collection at `d9797ee`/`37f523b`/`ecf762a`, live behavioral probes.

**Status anchor (from repo, not reports):** the working tree (uncommitted diff on HEAD) states v6 is a *candidate*, `IMPLEMENTED + TESTED`, awaiting the §27 item 43 external gate; the doc's state ladder is DESIGNED → IMPLEMENTED + TESTED → EXTERNALLY VERIFIED (not yet run) → RATIFIED. Note the committed v6 message says "ratify v6 architecture"; the working-tree doc corrects this to candidate. The working tree is the authoritative status. The suite run on HEAD today: **374 passed, 0 failed** (matches §28.6's claim).

---

## 1. RESEARCHPROGRAM CONTRACTS

### RP-01 Identity — deterministic, ordering-invariant, versioned

| | |
|---|---|
| Requirement | `rp_<sha256(content)[:24]>`; identical inputs+versions ⇒ identical identity; input ordering cannot alter identity; version triple participates |
| Source | v6 §28.2 data model; IDR-018 decision 1, rationale 2; Part 2 §7/§17 |
| Implementation | `programs.py:296-332` (`_canonicalize`/`canonical_json` — recursive dict sort, dict-list sort by canonical JSON, scalar-list sort), `:798` (content_hash), `:800-811` (input_hash incl. scope_content_hash, refs, versions, supersedes_ref), `:814` (`rp_`+24), `:110-111` (schema version const). No clock/random: module imports are `hashlib/json/re/dataclasses/enum/typing` only (`:47-54`) |
| Tests | `test_research_program.py::TestDeterminism::test_ac01_same_inputs_same_identity`, `::test_adversarial_d_same_semantics_different_ordering`, `::test_ac08_changed_compiler_version_changes_identity`, `::test_ac09_changed_scope_content_hash_changes_input_hash`, `::test_ac09_changed_scope_brief_requires_new_program`, `::test_adversarial_g_changed_hypothesis_changes_program`; `::TestRemediation::test_r01_determinism_two_confirmatory_order_invariant` |
| Verification status | Implemented + tested. Content hash excludes provenance fields (`created_at/version/produced_by` live on the row — `:268-272`, `program_to_dict` `:1086-1109`). **Not proven:** order-invariance for the *prediction/discrimination* lists in input_hash (input_hash uses sorted refs — safe by construction); cross-process identity (same interpreter assumed; no subprocess test). |

### RP-02 Schema — closed at top level and at every entry level

| | |
|---|---|
| Requirement | Unknown keys rejected top-level AND nested; strict typing; no coercion; malformed fails closed |
| Source | v6 §28.2 ("closed-schema conformance (unknown keys rejected — including nested, EC-F01); strict typing, no coercion, R-03"); EC-F01; R-03 |
| Implementation | `_KNOWN_PAYLOAD_KEYS`/`_HYPOTHESIS_KEYS`/`_PREDICTION_KEYS`/`_DISCRIMINATION_KEYS` (`:837-854`); `_validate_payload_keys` recurses one structural level into each entry (`:857-906`); `_require_str` raises on non-str (`:951-962`); `_draft_from_payload` strict enum via `_to_enum` (`:968-972`); `compile_from_payload` catches `KeyError/TypeError/ValueError` → `MALFORMED_PAYLOAD` INVALID (`:934-942`); `compile_research_program` catches `TypeError/ValueError/AttributeError` → `MALFORMED_DRAFT` INVALID (EC-F02, `:401-413`) |
| Tests | `TestValidationVerdicts::test_ac02_malformed_proposal_fails_closed_invalid`, `::test_ac02_unknown_keys_fail_closed`, `::test_ac02_bad_enum_fails_closed`; `TestRemediation::test_ecf01_nested_unknown_keys_rejected`, `::test_ecf01_nested_unknown_keys_predictions_and_discrimination`, `::test_r03_non_string_ref_fails_closed`, `::test_r03_non_string_objective_fails_closed`, `::test_ecf02_typed_draft_fails_closed`, `::test_ecf02_valid_typed_draft_still_compiles` |
| Verification status | Implemented + tested. Probe: top-level unknown, entry-level unknown, dict-typed value, non-list `hypotheses`, dict objective — all `INVALID`, zero exceptions. Depth: the schema has no legitimate nesting beyond one entry level; deeper dictionary *values* are rejected by typing (`MALFORMED_PAYLOAD`) — probe `hypotheses[0]["meta"]={"deep":{"x":1}}` → `UNKNOWN_PAYLOAD_KEY`. **Not proven:** rejection of unknown keys inside a payload that is itself a list element of `predictions` when the entry is a non-dict (e.g. `"predictions": ["x"]`) — skipped by key check, then `TypeError` → `MALFORMED_PAYLOAD` (fails closed, but with the generic code). |

### RP-03 Epistemic validation (E1–E5, contradiction, rivals)

| | |
|---|---|
| Requirement | Confirmatory targets need predictions (E1); obligations derived (E2/E3); gates derived; discrimination meaningful (E4); contradictory predictions detected; checkbox rivals rejected; UNRESOLVED rivals preserved; declared target ≠ actual status (E8) |
| Implementation | `programs.py:617-742`; obligation map `LADDER_OBLIGATIONS` `:119-140`; gates `_derive_gate_requirements` `:355-369`; verdict precedence `worst()` `:99-107` (`INVALID > CONTRADICTORY > UNSUPPORTED > INCOMPLETE > COMPILED`); E8: no status field anywhere in the model — see §6 |
| Tests | `TestValidationVerdicts::test_ac03_incomplete_missing_predictions`, `::test_ac03_incomplete_missing_rival_coverage`, `::test_ac04_contradictory_predictions`, `::test_ac04_contradictory_discrimination`, `::test_unsupported_template_ref`, `::test_errors_are_structured`; `TestCompiledProgram::test_compiled_derives_obligations`, `::test_compiled_gates_include_mandatory_human_gates`, `::test_ac11_rival_preserved_first_class`, `::test_ac11_unresolved_rival_preserved`, `::test_ac11_identical_rival_rejected` |
| Verification status | Implemented + tested. **Not proven:** contradictory-prediction detection across *identical observable but different condition spelling* (exact-string match only); E4 CONTRADICTORY vs E5 INCOMPLETE interaction matrix (only one combined path tested); ladder targets above SUPPORTED (ROBUST/REPLICATED) never exercised in any committed test — the obligation map for those rungs is untested (map-only evidence). |

### RP-04 Governance — frozen ScopeBrief

| | |
|---|---|
| Requirement | ScopeBrief resolved from authoritative DB state; caller-supplied scope hash not trusted; frozen brief governs; supersession head-only; old versions immutable; identical-content supersession rejected; no history rewrite |
| Implementation | Validator requires non-None string (`SCOPE_NOT_GOVERNED`/`SCOPE_HASH_NOT_STRING`, `:595-608`); repository resolves hash from `scope_briefs` by `brief_id+project_id` (`repositories.py:804-820`) and compares against `program.scope_content_hash` before the write (`:884-892`); supersession head-only + content-change enforced in `superseded_program_ids` (`:822-847`) and inside the tx (`:921-964`); no UPDATE/DELETE methods (`:1019-1063`); `UNIQUE (project_id, version)`, `UNIQUE (project_id, content_hash)`, `CHECK (supersedes_id != program_id)` (`migrations.py:383-385`) |
| Tests | `TestValidationVerdicts::test_scope_not_governed_invalid`, `::test_unresolvable_supersedes_invalid`; `TestResearchProgramRepository::test_record_requires_scope_brief`, `::test_record_without_supersession_rejected_when_chain_exists`, `::test_supersession_creates_new_version_history_preserved`, `::test_supersede_with_identical_content_rejected`, `::test_supersede_non_head_rejected`, `::test_adversarial_h_superseded_program_still_readable`; `TestRemediation::test_r02_write_path_rejects_bogus_scope_hash`, `::test_r02_write_path_accepts_matching_scope_hash` |
| Verification status | Implemented + tested. Probe: `scope_content_hash="FORGED"` → validator verdict `COMPILED`, write path rejects with `ResearchProgramError`, zero rows. **Doc discrepancy found:** v6 §28.2 failure semantics states "governance mismatch → rejected at validator *and* at the write path"; the validator only rejects `None`/non-string — a *mismatched string* passes the validator (pure function, no DB access) and is rejected only at the write path. IDR-018's R-02 wording ("rejected at the write path") is accurate; the v6 §28.2 line overstates validator enforcement. |

### RP-05 Persistence — only COMPILED persists; atomic; idempotent

| | |
|---|---|
| Requirement | Non-COMPILED → no row, no event, no partial state; persist+event atomic; duplicates idempotent; event type allowlisted; DB constraints as defense-in-depth |
| Implementation | `record()` gates on `result.compiled and result.program is not None` (`repositories.py:866-872`); `BEGIN IMMEDIATE` tx, row + `ResearchProgramCompiled` event inside (`:897-1007`); idempotent duplicate return (`:904-919`); `validate_event` at the persistence boundary (`event_validation.py:139-151`, allowlist `:43`); DB-level `CHECK (length(CAST(payload_json AS BLOB)) <= 4096)` (`migrations.py:136`); FK on via `connect()` (`database.py:44`); PK/FK/UNIQUEs (`migrations.py:360-386`) |
| Tests | `TestResearchProgramRepository::test_ac06_record_rejects_non_compiled`, `::test_record_compiled_persists_and_emits_event`, `::test_duplicate_record_is_idempotent`; `TestMigration::test_foreign_keys_enforced`; `TestRemediation::test_r04_failure_injection_no_partial_state` |
| Verification status | Implemented + tested for INCOMPLETE only in committed tests. Live probe (Step-2 inspection): `INCOMPLETE`, `CONTRADICTORY`, `UNSUPPORTED`, `INVALID` verdicts all → `ResearchProgramError`, 0 rows, `current() is None`. **Test gap:** CONTRADICTORY/UNSUPPORTED/INVALID against `record()` are not committed tests. |

### RP-06 Authority — no second authority path (see §4 Negative Capability Map)

| | |
|---|---|
| Implementation evidence | `programs.py` imports: stdlib only (`:47-54`); zero references to tasks/lifecycle/status/evidence/gates/budget/provenance/graph as *code* (grep: all matches are docstrings/strings). The only write surface is `ResearchProgramRepository.record()` which touches exactly two tables: `research_programs` + `events` (`repositories.py:966-1006`). **Confirmed capability surface:** `record()` accepts a hand-constructed `ResearchProgram` carrying a `COMPILED` flag without re-running the validator — probe persisted `rp_handbuilt…` + emitted `ResearchProgramCompiled`. See §7. |
| Verification status | Partially structural. See §13/§14. |

---

## 2. ACTIONEVALUATION CONTRACTS

### AE-01 Input restrictions — existing admissible candidates only

| | |
|---|---|
| Implementation | `CandidateAction` is a data holder with refs (`evaluation.py:97-122`); no generator, no task creation; empty set → `EMPTY_CANDIDATE_SET` diagnostic, zero output (`:206-215`); no task-node construction anywhere (no `node`/`TaskRepository` imports — AST-probed) |
| Tests | `TestNoAuthority::test_ac04_no_candidate_generation`; `TestBoundedExpansion::test_ac11_evaluation_cannot_generate_work` |
| Verification status | Implemented + tested. **Not proven:** that the future P3 candidate-source adapter (S3/GR6/S14) can't feed synthetic actions — deferred by definition (§28.5 row 7). |

### AE-02 Determinism

| | |
|---|---|
| Implementation | Pure function `evaluate_candidates` (`:191-272`); input canonicalization in `_build_ranking` (`:335-345`: sorted refs, sorted history, sorted stale ids); deterministic sort key `(_ordering_key, candidate_ref)` reversed (`:261-265`); no clock/random/LLM/IO (module imports: `dataclasses, enum, typing` + `canonical_json, sha256_hex` from `programs.py`, whose transitive imports are `hashlib/json/re/dataclasses/enum/typing`) |
| Tests | `TestDeterminism` (8 tests: same-inputs, candidate-order, history-order, stale-id-order, cross-process re-import, independent re-derivation, version change, policy change) |
| Verification status | Implemented + tested. Probe: identical candidates `(c1,c2)` and `(c2,c1)` → identical `['c2','c1']` order (tie-break is `candidate_ref` descending — deterministic, order-invariant). **Observed behavior:** duplicate `candidate_ref` entries are *not* deduplicated — `(c1,c1b,c1b)` yields three identical table rows; `input_state_hash` is computed from the ref *set* (multiplicity-insensitive) while `content_hash` includes the full comparison (multiplicity-sensitive). Deterministic in both cases; semantic nuance recorded for Step 3. |

### AE-03 Ranking semantics

| | |
|---|---|
| Implementation | No scalar score: comparison is a full table + documented lexicographic policy (`DEFAULT_ORDERING_POLICY` `:48-53`, `DIMENSION_ORDER` `:40-43`); `_ordering_key` = dimension levels then cost/time/compute tiers with `UNKNOWN=0` (last) then `candidate_ref` (`:312-320`); gates dominate: `blocked_by` → `EXCLUDED_GATE` hard exclusion (`:225-229`), never ranked; `dependency_unsatisfied` → `BLOCKED_DEPENDENCY` (`:230-235`); ordering policy embedded in output (`:353`) |
| Tests | `TestGateDominance` (3), `TestStateSensitivity::test_ac02_ordering_policy_is_lexicographic_not_weighted`, `::test_unknown_cost_sorts_last_but_never_blocks`, `TestNoScalarScore` (3) |
| Verification status | Implemented + tested. **Not proven:** every pairwise policy combination; `UNKNOWN` time/compute (only `cost` tested); `NO_IMPROVEMENT` + gate-blocked mixed set (diagnostic counted only over admissible). |

### AE-04 Diagnostics

| | |
|---|---|
| Implementation | `STARVED_CANDIDATE` (`:239-246`), `STALE_INPUT` (`:247-252`, per-candidate staleness `:300-309`), `EMPTY_CANDIDATE_SET` (`:206-215`), `NO_IMPROVEMENT` (`:253-259`); all deterministic, advisory-only — no branch mutates state |
| Tests | `TestAuditability` (8 tests covering stale flagged/not-flagged, starvation detected/not, no-improvement, structured reasons, full table, summarize determinism) |
| Verification status | Implemented + tested. **Not proven:** `selection_history` with malformed entries (e.g. length≠2 tuples → `ValueError` raised, no verdict — evaluator has no typed-fail-closed contract, unlike RP's EC-F02); behavior is *raise*, recorded for §13. |

### AE-05 Authority (see §4) / AE-06 Output

| | |
|---|---|
| Implementation | `ranking_id = "eval_" + content_hash[:24]` (`:361`); content-addressed; re-derivable (pure function); transient — nothing persists `CandidateRanking` (no repository, no event, no serializer that touches storage); never evidence: no evidence vocabulary (AST test), no gate input: nothing consumes the ranking (no caller in `src/` — grep: `evaluate_candidates`/`CandidateRanking` referenced only in `evaluation.py` and `tests/test_evaluation.py`) |
| Tests | `TestNoAuthority::test_ac04_module_has_no_write_surface` (AST-stripped source scan for sqlite/INSERT/UPDATE/DELETE/repository/persistence/conn.execute), `::test_ac05_no_evidence_promotion_vocabulary`, `::test_ac06_no_budget_spend`; `TestNoScalarScore::test_ranking_id_content_addressed` |
| Verification status | Implemented + tested structurally. Note: the AST scan covers `evaluation.py` only; the transitive import `programs.py` is clean by the same criteria (verified by grep). **Observed:** unknown dimension keys silently default to `NONE` (normalization, not rejection — probe); typed violations (e.g. `cost="CRAZY"`) raise `AttributeError` at serialization (no fail-closed verdict — recorded, not judged). |

---

## 3. AUTHORITY SURFACE MAP

```
ResearchProgram:
  compile_from_payload(payload, project_id, scope_content_hash, superseded_program_ids)
    └─ programs.py (pure; stdlib only)
        └─ CompilationResult{status, errors, program}        [no I/O]
  compile_research_program(draft, …)                         [same, typed entry]
  ResearchProgramRepository.record(project_id, result, produced_by, reason)
    └─ repositories.py
        ├─ resolve_scope_content_hash()      → SELECT scope_briefs      [read]
        ├─ superseded_program_ids()          → SELECT research_programs [read]
        ├─ INSERT research_programs          [write — the ONLY RP write]
        └─ INSERT events (ResearchProgramCompiled) via _append_event_to_db → validate_event → INSERT events [write]
  read side: get/get_by_hash/current/list_for_project/exists → SELECT only
  No other callers in src/: grep for compile_from_payload/compile_research_program/ResearchProgramRepository
    matches only programs.py, repositories.py, events/intents/migrations/event_validation (definitions),
    and tests. No agent/CLI/tool/reconcile/gateway call path exists at HEAD.

ActionEvaluation:
  evaluate_candidates(candidates, selection_history, stale_input_ids, evaluator_version,
                      policy_version, ordering_policy) → CandidateRanking
    └─ evaluation.py (pure; dataclasses/enum/typing + canonical_json/sha256_hex)
        └─ output: dataclass tree; NO persistence access, NO events, NO side effects
  No callers in src/ other than tests.
```

Every node above: zero `TaskRepository`/`ProjectRepository`/`apply_intent`/evidence/budget/provenance/graph/dispatch access. The **only** storage-touching class is `ResearchProgramRepository`, confined to its two tables.

---

## 4. NEGATIVE CAPABILITY MAP

| Forbidden authority | RP path? | AE path? | Interface exists? | Direct repo path? | Gateway path? | Existing test? |
|---|---|---|---|---|---|---|
| Create tasks | No | No | Yes — `TaskRepository.create` | No (no import/reference from RP/AE code) | N/A (placeholder) | No (only AE AST absence scan) |
| Mutate lifecycle | No | No | Yes — `ProjectRepository.transition_lifecycle` | No | N/A | No |
| Mutate task status | No | No | Yes — `TaskRepository.transition_status`/`invalidate` | No | N/A | No |
| Promote evidence | No | No | **No — Evidence Ladder has no code** (`evidence.py` placeholder; no evidence table, no EvidenceRepository) | No | N/A | RP: `test_ac07_compiled_program_carries_no_evidence_status` (schema-level); AE: `test_ac05_no_evidence_promotion_vocabulary` |
| Approve gates | No | No | **No — `gates.py`/`integrity_gates.py` placeholders** | No | N/A | No |
| Mutate budget | No | No | **No budget code anywhere** | No | N/A | AE: `test_ac06_no_budget_spend` (vocabulary only) |
| Mutate provenance | No | No | No repository class (table `provenance_edges` exists, unused) | No | N/A | No |
| Mutate graph authority | No | No | `core/graph.py` is read-only queries; graph mutation = `TaskRepository` | No | N/A | No |
| Bypass Intent Gateway | Partially | No | Gateway = 4-line placeholder; no `apply_intent` exists | **Yes for RP**: `ResearchProgramRepository.record()` is public and unreferenced by src — a caller with a conn can write without any admission check | No gateway to bypass | No |
| Dispatch execution | No | No | `tools/execution.py` placeholder | No | N/A | No |
| Select research direction | No | No | `agents/director.py` placeholder | No | N/A | No |
| Generate arbitrary research actions | No | No | Template ref → `UNSUPPORTED` (`programs.py:748-756`); AE never invents | No | N/A | `test_unsupported_template_ref`, `test_ac04_no_candidate_generation` |

**Overriding caveat (§7 rule):** "no path exists" for the top rows is *structural* (no imports/references), not merely untested — verified by repo-wide grep. The one row with an **actual callable surface** is "Bypass Intent Gateway / direct RP write": `record()` plus the validator-bypass finding (§7).

---

## 5. DIRECTOR / INTENT GATEWAY ENFORCEMENT (PROPOSE_RESEARCH_PROGRAM)

- **What makes it Director-only:** `IntentKind.director_only()` returns `{PROPOSE_RESEARCH_PROGRAM}` (`intents.py:56-63`); the kind is also in `llm_proposable()` (`:46-53`).
- **Where enforced:** **metadata only.** `director_only()` is referenced nowhere in `src/` outside `intents.py` (grep: only `tests/test_research_program.py` assertions). `research/gateway.py` is a 4-line placeholder; **`apply_intent` does not exist in the repository.** The doc's own admission: gateway wiring is P3 DEFERRED (§28.5 row 3; `intents.py:6-10`).
- **Consequences for the claim:** at HEAD, *any* caller (Researcher/Adversary/Implementer/arbitrary LLM output) can construct `Intent(PROPOSE_RESEARCH_PROGRAM, proposed_by="anyone", …)` — nothing reads `proposed_by`; and, more directly, any code with a DB connection can call `compile_from_payload` → `record()` without any intent at all. The Director-only restriction is a **declared contract awaiting P3 enforcement**, not a runtime check. `produced_by` on `record()` is caller-supplied, never verified.
- **"What happens when an unauthorized role attempts it":** unanswerable at HEAD — there is no admission path to attempt. Step 3 can only verify the absence (and the write-path freedom of any caller).

---

## 6. EVIDENCE-LADDER BOUNDARY

- **Status field:** none. `ResearchProgram`/`HypothesisSpec` carry `ladder_target` (declared target enum, `programs.py:59-69`) — no status-like key exists in model, payload schema, DB columns (`migrations.py:360-386`), or event payload (`repositories.py:999-1005`). `test_ac07…` asserts serialization contains no `evidence_status|claim_status|verdict|promotion|ladder_status`.
- **Validator sets evidence status?** No — no such code exists anywhere.
- **Repository advances evidence?** No — no evidence table/repository exists; `evidence.py` is a Phase 0 placeholder.
- **RP/AE can call evidence promotion?** No callable exists; the Ladder's promotion authority is *not implemented in the codebase at all* (unlike the Director-only rule, this one is structurally closed: the interface doesn't exist).
- **`ResearchProgramCompiled` recognized as evidence?** No code path reads the program as evidence; `research_programs` is a standalone table FK'd to `projects` only; artifacts table is separate (`migrations.py:148-166`); no validation logic links them.
- **Could a compiled program satisfy a Validation-artifact requirement accidentally?** No validation-artifact logic exists on this baseline (integrity gates placeholder). The invariant to prove — "no RP/AE code path can invoke or impersonate the Evidence Ladder's promotion authority" — is satisfied at HEAD by *absence of the authority*; Step 3 should re-verify via AST/vocabulary scan on both modules plus event-payload inspection.

---

## 7. PERSISTENCE BOUNDARY (ResearchProgram write path)

- **Inputs accepted by `record()`:** `project_id: str`, `result: CompilationResult`, `produced_by`, `reason` (`repositories.py:851-858`).
- **Validated independently:** COMPILED flag + non-None program (`:866-872`); `project_id` match (`:874-878`); governance hash vs DB-resolved brief hash (`:884-892`); supersession head-only + content-change (`:921-964`); idempotent duplicate (same project+content_hash) (`:904-919`).
- **Not validated at the boundary:** the program's *epistemic content* — E1–E5, schema conformance, strict typing. **Probe (performed, Step-2 inspection):** a hand-constructed `ResearchProgram` (never passed through the compiler; `hypotheses=()` empty, `compiler_version='9.9.9'`) wrapped in `CompilationResult(COMPILED, …)` **persisted** and emitted `ResearchProgramCompiled`. The COMPILED gate checks the *flag*, not the *origin*.
- **Malformed-object persistence:** `INCOMPLETE/CONTRADICTORY/UNSUPPORTED/INVALID` → always `ResearchProgramError` before any write (probe + `test_ac06_record_rejects_non_compiled`); no partial state (R-04 trigger test).
- **Raw SQL bypass:** possible by definition (direct `INSERT` with a fabricated row) — DB constraints then enforce PK, FK, `UNIQUE(project_id,version)`, `UNIQUE(project_id,content_hash)`, `CHECK(supersedes_id != program_id)` (`migrations.py:383-385`); `PRAGMA foreign_keys=ON` is set by `connect()` (`database.py:44`). No CHECK validates JSON content; a raw-SQL row with empty hypothesis JSON is legal. Defense-in-depth is constraint-level, not content-level.

---

## 8. PROVENANCE MAP

**ResearchProgram chain:**

| Link | Status at HEAD | Evidence |
|---|---|---|
| Research Question → ScopeBrief | Conceptual (v4 S16; DB table exists) | `scope_briefs` table |
| ScopeBrief → ResearchProgram | **Persisted** (governance edge) | `scope_ref` + hash comparison in `record()`; FK-less ref |
| ResearchProgram → Hypothesis | Persisted as JSON columns (inline entries, not first-class tables — P8 deferred) | `hypothesis_json` |
| Hypothesis → Prediction | Persisted inline (`claim_ref`) | `prediction_json` |
| Prediction → EvidenceRequirement | Persisted inline (derived, `claim_ref` keyed) | `evidence_json` |
| EvidenceRequirement → Potential Task | **Deferred** (P3/P6 admission; no task binding code) | §28.5 rows 2, 4 |
| Supersession chain | **Persisted** | `supersedes_id`, versioning, `ResearchProgramCompiled` event per version |

No `provenance_edges` rows are written for programs (the table exists for artifacts; no code writes it at HEAD).

**ActionEvaluation chain:** CandidateAction refs → objective/obligation refs → dimensions → `CandidateRanking` (hash) → **Director consumption deferred (P3+/§27 item 47)**. Nothing is persisted; the chain is conceptual until the Director/round integration lands.

---

## 9. TEST COVERAGE MAP (exact tests, both files = 86 tests)

**tests/test_research_program.py — 55 tests**

| Class | Tests | Proves |
|---|---|---|
| `TestDeterminism` (6) | `test_ac01_same_inputs_same_identity`, `test_adversarial_d_same_semantics_different_ordering`, `test_ac08_changed_compiler_version_changes_identity`, `test_ac09_changed_scope_content_hash_changes_input_hash`, `test_ac09_changed_scope_brief_requires_new_program`, `test_adversarial_g_changed_hypothesis_changes_program` | RP-01 identity, ordering invariance, version/scope participation |
| `TestValidationVerdicts` (13) | `test_ac02_malformed_proposal_fails_closed_invalid`, `test_ac02_unknown_keys_fail_closed`, `test_ac02_bad_enum_fails_closed`, `test_ac02_unresolvable_refs_invalid`, `test_ac02_self_rival_invalid`, `test_ac03_incomplete_missing_predictions`, `test_ac03_incomplete_missing_rival_coverage`, `test_ac04_contradictory_predictions`, `test_ac04_contradictory_discrimination`, `test_unsupported_template_ref`, `test_scope_not_governed_invalid`, `test_unresolvable_supersedes_invalid`, `test_errors_are_structured` | RP-02/RP-03 verdicts, closed schema (top level), governance inputs |
| `TestCompiledProgram` (7) | `test_compiled_derives_obligations`, `test_compiled_gates_include_mandatory_human_gates`, `test_ac07_compiled_program_carries_no_evidence_status`, `test_ac11_rival_preserved_first_class`, `test_ac11_unresolved_rival_preserved`, `test_ac11_identical_rival_rejected`, `test_summarize_is_deterministic` | RP-03 derivation, E8 schema absence, rival semantics |
| `TestResearchProgramRepository` (10) | `test_ac06_record_rejects_non_compiled`, `test_ac06_no_direct_mutation_bypass`, `test_record_compiled_persists_and_emits_event`, `test_duplicate_record_is_idempotent`, `test_record_requires_scope_brief`, `test_record_without_supersession_rejected_when_chain_exists`, `test_supersession_creates_new_version_history_preserved`, `test_supersede_with_identical_content_rejected`, `test_supersede_non_head_rejected`, `test_adversarial_h_superseded_program_still_readable` | RP-04/RP-05 write path (INCOMPLETE only), immutability, supersession |
| `TestIntentContract` (4) | `test_propose_research_program_is_llm_proposable`, `..._is_director_only`, `..._not_internal_only`, `test_intent_instantiates` | §5 metadata membership (not runtime enforcement) |
| `TestMigration` (5) | `test_fresh_db_migrates_to_4`, `test_migration_replay_idempotent`, `test_v3_to_v4_upgrade_path`, `test_future_version_rejected`, `test_foreign_keys_enforced` | migration + DB constraints |
| `TestRemediation` (10) | `test_r01_determinism_two_confirmatory_order_invariant`, `test_r02_write_path_rejects_bogus_scope_hash`, `test_r02_write_path_accepts_matching_scope_hash`, `test_r03_non_string_ref_fails_closed`, `test_r03_non_string_objective_fails_closed`, `test_ecf01_nested_unknown_keys_rejected`, `test_ecf01_nested_unknown_keys_predictions_and_discrimination`, `test_ecf02_typed_draft_fails_closed`, `test_ecf02_valid_typed_draft_still_compiles`, `test_r04_failure_injection_no_partial_state` | R-01…R-04, EC-F01/F02 regressions |

**tests/test_evaluation.py — 31 tests**

| Class | Tests | Proves |
|---|---|---|
| `TestDeterminism` (8) | same-identity, candidate-order, history-order, stale-id-order, repeated-process, independent re-derivation, version/policy change | AE-02 determinism |
| `TestStateSensitivity` (4) | dimension rerank, lexicographic-not-weighted, UNKNOWN-cost-last, canonical dimension order | AE-03 |
| `TestGateDominance` (3) | gate-blocked never ranked, high-value still excluded, dependency-blocked surfaced | AE-03 |
| `TestNoAuthority` (4) | no write surface (AST scan), no evidence vocabulary, no budget, no candidate generation | AE-01/AE-05 |
| `TestAuditability` (8) | structured reasons, full table, stale flagged/not-referenced, starvation detected/not, no-improvement, summarize deterministic | AE-04 |
| `TestBoundedExpansion` (1) | output size = input size, no continuation | AE-01 |
| `TestNoScalarScore` (3) | no score/value/priority fields, lexicographic policy text, content-addressed id | AE-03/AE-06 |

**Coverage gaps (explicit):** CONTRADICTORY/UNSUPPORTED/INVALID vs `record()`; validator-bypass (hand-built COMPILED result); unknown-key at deeper-than-entry nesting (probe-only); ROBUST/REPLICATED obligation maps; duplicate `candidate_ref` multiplicity; typed-violation behavior of the evaluator; `UNKNOWN` time/compute tiebreak; absence-of-task-path for `programs.py` (only `evaluation.py` has a structural absence scan); produced_by attribution.

---

## 10. TEST COUNT RECONCILIATION (git-verified, collected at each commit)

| Commit | Event | delta | Collected total | Per-file evidence |
|---|---|---|---|---|
| `d9797ee` (v4 Phase 1) | baseline | — | **280** | `test_phase1_acceptance` 20, no research_program/evaluation files |
| `215dc4d` (IDR-017) | +8 invalidate tests | +8 | 288 | `test_phase1_acceptance` 20→28 |
| `37f523b` (RP impl) | +45 RP tests | +45 | **333** | `test_research_program` 45; `test_database` renamed (3→4), no count change |
| `ecf762a` (R-01…R-04) | +6 regressions | +6 | **339** | `test_research_program` 45→51 |
| `7de1135` (v6) | +31 evaluation +4 EC closures | +35 | **374** | `test_evaluation` 31; `test_research_program` 51→55 |

**Current HEAD collection: 374** (per-file: artifacts 16, cli 6, concurrency 4, config 3, database 16, evaluation 31, event_validation 27, events 17, failure_injection 5, lifecycle 82, modes 13, package 2, phase1_acceptance 28, repositories 31, research_program 55, task_status 38). Full run: **374 passed**. Overlap explanation: "55 research-program tests" includes the 45 original + 6 R-regressions + 4 EC-closures; "35 new v6 tests" = 31 evaluation + 4 EC-closures only (R-tests predate the v6 commit); "339 pre-v6 baseline" = 333 + 6 R-tests. All three doc numbers are mutually consistent; IDR-018's historical "45 tests"/"333 passed"/"339 passed" are snapshots at `37f523b`/`ecf762a` respectively. No test was deleted or modified to inflate counts (git diff evidence: only additions + one rename).

---

## 11. SOURCE-LEVEL CAPABILITY AUDIT

| Pattern | Matches | Reachable from RP? | Reachable from AE? | Classification |
|---|---|---|---|---|
| `INSERT INTO tasks` / `UPDATE tasks` / `DELETE FROM tasks` | `repositories.py:350,524,530,537,600,623` | No | No | Unrelated infrastructure (`TaskRepository`); no import path |
| `INSERT INTO projects` / `UPDATE projects` | `repositories.py:123,193,248,285` | No | No | Unrelated (`ProjectRepository`) |
| `INSERT INTO evidence` / `UPDATE evidence` | none | — | — | Interface does not exist |
| `INSERT INTO provenance` / `UPDATE provenance` | none | No | No | Table exists; unused |
| `INSERT INTO research_programs` | `repositories.py:968` only | Yes (own write) | No | RP's sole write |
| `apply_intent` | zero definitions; docstring mentions only (`intents.py:4,8`, `programs.py:918`) | No | No | Placeholder — not implemented |
| `transition_lifecycle/mode/status`, `advance_iteration`, `invalidate` | `repositories.py` (definitions only) | No | No | Unreachable from RP/AE |
| `Evidence`, `SUPPORTED/ROBUST/REPLICATED` | `programs.py` (enum/map/docstrings) | Declared targets only | No | RP: target vocabulary; no promotion call |
| Gate approval / budget / provenance / graph mutation / dispatch / scheduler | no code exists (`gates.py`, `integrity_gates.py`, `budget` n/a, `provenance.py`, `reconcile.py`, `execution.py`, `director.py` all placeholders) | — | — | Authority surfaces not yet implemented in the codebase |
| Direct calls to RP/AE entry points from non-test src | none | — | — | Both capabilities are only reachable by direct import; no wiring |

**Bottom line:** every authority-adjacent match is either inside `repositories.py`'s sanctioned classes or is a docstring/enum string. No hidden second path exists in code; the *open* surfaces are `record()`'s COMPILED-flag trust and the absence of any gateway (both documented in §5/§7).

---

## 12. ADVERSARIAL TEST REQUIREMENTS (for Step 3 — probes to execute)

**ResearchProgram:** (1) unauthorized-role `PROPOSE_RESEARCH_PROGRAM` — expected: no enforcement exists (records as DEFERRED contract, tests absence); (2) malformed drafts incl. non-dict payload, missing objective/scope/versions, bad enums; (3) nested unknown keys incl. deep-dict values and non-dict entries; (4) forged ScopeBrief hash (validator + write path + DB-resolved); (5) contradictory predictions + identical-signature discrimination; (6) checkbox rival and UNRESOLVED rival preservation; (7) INCOMPLETE/CONTRADICTORY/UNSUPPORTED/INVALID → `record()` rejection (0 rows, 0 events); (8) duplicate/supersession misuse (identical-content supersede, non-head supersede, second non-superseding program, reversion-vs-duplicate); (9) **direct repository mutation attempt with a hand-built COMPILED result** (already shown to persist — must be pinned as an explicit test); (10–15) evidence-promotion / task-creation / lifecycle / gate-approval / budget / provenance / graph-state attempts — expected: no interface reachable; verify by import-graph + AST scan.

**ActionEvaluation:** (1–8) direct task/lifecycle/status/budget/gate/evidence/provenance/graph mutation attempts — no interface; (9) synthetic-candidate injection into `evaluate_candidates` (verify inputs are data, output is a table); (10) candidate ordering instability (reverse, shuffle, duplicates incl. multiplicity-sensitivity of `input_state_hash` vs `content_hash`); (11) stale input; (12) empty set; (13) starvation; (14) repeated identical evaluation (cross-process determinism incl. fresh interpreter); (15) deterministic tie-break (identical refs, near-identical candidates); (16) gate-blocked exclusion incl. all-HIGH candidate; (17) typed-violation behavior (record current *raise* semantics); (18) unknown-dimension-key normalization behavior.

---

## 13. UNVERIFIED CLAIMS

1. **"Director-only is enforced"** — NOT verified; no runtime enforcement exists at HEAD (metadata only; gateway placeholder). The claim is contract-deferred to P3, per §28.5.
2. **"Governance mismatch rejected at validator AND write path"** (v6 §28.2 failure semantics) — validator part **contradicted** by probe (mismatched string compiles); write path verified.
3. **Part 6 probe battery A–L** — superseded in the working-tree doc: acknowledged as an ad-hoc instrument; only committed subsets remain. Cannot be re-verified from repo.
4. **"v6 folds v5.1 in full"** — unverifiable from repo: `hermes_research_architecture_v5_1.md` is absent (only v3/v4/v6 present).
5. **ROBUST/REPLICATED obligation maps** — map content unverified by any test.
6. **"55 tests cover ResearchProgram"** as a summary claim — disaggregated in §9; several invariants (§9 gaps) are uncovered.
7. **`CandidateRanking` "never a gate input / never persisted"** — true at HEAD only because no consumer exists; the *absence of wiring* is verified, the *future* guarantee is architectural.
8. **Validator-bypass persistence** (hand-built COMPILED result) — behavior verified by probe; whether it violates the approved architecture depends on the P3 gateway contract (which requires the validator), unresolved here.

## 14. POTENTIAL EVIDENCE GAPS

- **No committed test for the validator-bypass surface** (`record()` + hand-built COMPILED result) — the single most important gap for the authority claim.
- **No structural absence scan for `programs.py`** (only `evaluation.py` has the AST-based no-write-surface test).
- **No test for non-INCOMPLETE verdicts against `record()`** (CONTRADICTORY/UNSUPPORTED/INVALID probe-only).
- **No runtime role check exists to test** — Step 3 cannot positively verify Director-only admission; it can only document the declared-vs-enforced distinction.
- **Deep-nesting key rejection** beyond entry level is probe-verified, not committed.
- **`produced_by` attribution** is caller-supplied and untested (provenance of authorship unverified).
- **No integration tests at all** for either capability with the reconcile loop/graph (they don't exist yet — DEFERRED, not MISSING; §21 distinction maintained).
- **Evaluator typed-input behavior** (raise on `cost="CRAZY"`; silent NONE-default for unknown dimension keys) has no committed pin and no documented contract in IDR-019.
- **Duplicate `candidate_ref` multiplicity** semantics (table rows duplicated; `input_state_hash` multiplicity-insensitive) untested and undocumented.

---

*End of extraction. No claim verified; no verdict issued. Step 3 — LIVE VERIFICATION — should execute §12's probes against these extracted contracts, with §7 (validator-bypass) and §5 (absence of runtime Director-only enforcement) as the two highest-priority attack surfaces.*
