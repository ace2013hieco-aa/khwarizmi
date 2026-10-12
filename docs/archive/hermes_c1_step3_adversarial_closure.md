# Hermes C1 Step-3 Adversarial Closure

**Gate:** C1 STEP-3 adversarial closure (final implementation attack before Step 4)
**Repository:** https://github.com/ace2013hieco-aa/khwarizmi-research
**Branch:** `main`
**HEAD before gate:** `2b0f52b` (Step 3 C1 Option A implementation)
**HEAD after correction:** `cb1f8e1` (write-path E6 fix) — this report at `HEAD` includes both
**Date:** 2026-08-21
**Auditor:** adversarial closure agent (live source inspection, not document trust)
**Governing contracts:** `hermes_research_architecture_v6.md` + `hermes_architecture_ratification.md:6.2` (FULL-HISTORY ratified, LIVE-CHAIN rejected) + `hermes_c1_slot_ref_design_gate.md` + `hermes_c1_step3_schema_version_spec_conflict.md` (Option A ratified) + `hermes_final_ratification_gate.md`

---

## 1. Executive Verdict

**STEP 3 — C1 CLOSED** (after one P1 correction). **STEP 4 — AUTHORIZED TO BEGIN** (do not implement automatically).

The implemented C1 surface at `2b0f52b` was **substantially correct** and already satisfied AC-1 Delta=0, schema-version Option A, FULL-HISTORY determinism, project isolation, provenance, serialization and authority invariants. One **P1 Step-3 blocker** was discovered via direct write-path bypass: `ResearchProgramRepository.record()` re-validated AR-01 but not E6, allowing a forged `COMPILED` object to poison the append-only vocabulary. The minimal write-path correction was applied (`cb1f8e1`), proven, and regression-tested. With that fix, every hard-stop invariant holds, validator and persistence boundaries agree, and no P0/P1 remains.

---

## 2. Repository State

- `git status` before gate: `2b0f52b` clean (`origin/main` synced), untracked `.freebuff/` only
- `git log --oneline -n 5`: `2b0f52b` Step 3 C1 Option A, `ce7aa26` spec-conflict note, `a1721c1` C4, `1b01f59`/`44ad61c` HR-04
- HEAD after work: `cb1f8e1` fix commit + this report (to be committed)
- Verification baseline (live):
  - Tests: 1660 at `2b0f52b` (1618 baseline + 42 C1) → 1667 after fix (+7 write-path regression)
  - `pyright 0 errors, 0 warnings`
  - `ruff clean` (1 auto-fixable import ordering fixed)
  - Targets: `src/hermes/research/programs.py`, `src/hermes/persistence/repositories.py`, `src/hermes/research/gateway.py`, plus helpers

No unrelated modifications.

---

## 3. Implementation Surfaces Audited

**Authoritative production:**
- `src/hermes/research/programs.py:116` `PROGRAM_SCHEMA_VERSION="2"`, `117` `SUPPORTED_PROGRAM_SCHEMA_VERSIONS=frozenset({"1","2"})`
- `programs.py:169` `_SLOT_REF_RE`, `170` `_SLOT_REF_MAX_LENGTH=128`, `173` `MAX_SLOT_RATIONALE=2000`
- `programs.py:222` `HypothesisSpec.slot_ref: str | None = None` (frozen, optional, gate §7.2 permanent)
- `programs.py:279` `SlotDeclaration(slot_ref, rationale)`, `298` `ResearchProgramDraft.new_slot_declarations`
- `programs.py:1346` `_h_to_dict` non-None-only emission (load-bearing AC-1)
- `programs.py:1408` `canonical_content_dict` (includes `slot_ref` when present, `schema_version` always), `1437` `content_hash_of`, `1442` `input_hash_of`
- `programs.py:622,1186` validator schema-version set-membership, `894` E6 (format + vocabulary + both-direction checks)
- `programs.py:1086` `_KNOWN_PAYLOAD_KEYS` includes `new_slot_declarations`, `1104` `_HYPOTHESIS_KEYS` includes `slot_ref`
- `programs.py:1242` `_draft_from_payload` parses `slot_ref`/`new_slot_declarations` via `_require_str`
- `src/hermes/persistence/repositories.py:1325,1535` — persistence (see below)
- `src/hermes/research/gateway.py:254` `slot_vocabulary = program_repo.slot_vocabulary(project_id)` (fail-closed `MALFORMED_PAYLOAD`), `285` `compile_from_payload(..., slot_vocabulary=slot_vocabulary)`, `315` `new_slot_declarations` into `record()`

**Tests inspected:** `tests/test_c1_slot_ref.py` (42 → 49), `tests/test_research_program.py` (72), `tests/test_gateway.py`, plus controller/evaluation/migrations.

**Hidden-surface search (global grep):**
- `slot_ref` → `programs.py` 48, `repositories.py` 23, tests/docs only elsewhere — no hidden coupling
- `slot_vocabulary` → `programs.py` 11, `repositories.py` 4, `gateway.py` 4 — only authoritative path
- `new_slot_declarations` → `programs.py` 17, `repositories.py` 11, `gateway.py` 2 — payload-only, never in `canonical_content_dict`
- `PROGRAM_SCHEMA_VERSION` / `SUPPORTED_PROGRAM_SCHEMA_VERSIONS` → `programs.py` 6/3, `repositories.py` 3/3 — single derivation, gateway+validator+write agree
- `schema_version` elsewhere (`claims.py`, `evaluation.py`, `migrations.py`, etc.) correctly isolated — no cross-schema coupling

---

## 4. Attack Matrix

| Attack | Target | Method | Verdict |
|--------|--------|--------|---------|
| A slot vocabulary poisoning | `programs.py:900` E6, `repositories.py:1535` vocabulary | A1 malformed/type/length/unicode/duplicate, A2 duplicate, A3 superseded, A4 abandoned, A5 orphan, A6 undeclared | **PASS** (all rejected or correctly admitted) |
| B project isolation | `repositories.py:1558 WHERE project_id=?` | Proj A slot:Y without intro, Proj A/B same label, query/cache/serialization | **PASS** |
| C determinism | `programs.py:339 _canonicalize`, `repositories.py:1535 ORDER BY version ASC` | insertion/row/supersession order, duplicates, reload, set→sorted before hash | **PASS** |
| D AC-1 identity | `programs.py:1346,1408`, `tests/test_c1_slot_ref.py:54` goldens | D1-D7 v1/v2/None/serialization/gateway vs direct | **PASS** (v1 hash stable, v1→v2 hash change expected) |
| E schema bypass | `programs.py:622`, `repositories.py:1325` | "1","2","3","0","999","",None,int, forged 999, default, validator/write agreement | **PASS** (only {"1","2"} accepted, both boundaries agree) |
| F race/TOCTOU | gateway vocab read → validate → `record()` | concurrent writers observing stale vocab | **ACCEPTED** (see §12) |
| G provenance | `gateway.py:315`, `repositories.py:1480` | delete/duplicate/reorder/forge declaration without use, declaration as vocab authority | **PASS** |
| H event/audit | `repositories.py:1463 EventRepository` | tamper event payload/ordering/presence, actor metadata | **PASS** |
| I serialization | `programs.py:1346 _h_to_dict`, `programs.py:339 _canonicalize` | missing/None/empty/unicode/long/key-order/optional/old-new payloads | **PASS** |
| J cross-path | compiler/gateway/repository/reload | same logical program via different paths, vocab/None/schema/project coupling | **PASS** (except pre-fix P1, now fixed) |
| K authority escape | `SlotRef` surface reachability | scheduling/priority/eligibility/budget/evidence/lifecycle/mutation | **PASS** (NONE, see §13) |
| L corrupted history | `repositories.py:1564 _json_loads`, `1591 string check` | malformed JSON/slot_ref/missing fields/duplicate/inconsistent | **PASS** (fail-closed) |
| M S7 compatibility | FULL-HISTORY without implementing S7 | historical slot remains discoverable for future screen | **PASS** |
| N backward compat | `SUPPORTED={"1","2"}` | v1 load/validate/persist/reload/hash/program_id/gateway/replay | **PASS** |

---

## 5. AC-1 Identity Attack

**Highest priority.** Goldens captured pre-C1 at `scripts/_capture_prec1_golden.py` (ratified provenance):
- `GOLDEN_BASE_CONTENT 5d4a7f3f72e96d4dc6779541367755df4a209fbfd8d189b66d30ad8aea660b96` / `GOLDEN_BASE_ID rp_5d4a7f3f72e96d4dc6779541` (confirmatory `H1 SUPPORTED` vs `H0 ACTIVE`)
- `GOLDEN_MIN_CONTENT 3d6de28cadd37c0e37e086c01ce061a9c5323e3c891076e7d516d42bf8283255`

Live probe reproductions (independent canonicalizer + hashlib, not production helper re-run):

| Case | Payload | Expected | Observed |
|------|---------|----------|----------|
| D1 old v1 | `schema_version="1"` explicit confirmatory | `COMPILED`, hash = golden | **PASS** `5d4a7f3f...` exact |
| D2 absent slot | no `slot_ref` key | identical to pre-C1 identity, `slot_ref` absent in canonical | **PASS** `canonical_content_dict` hypotheses have no `slot_ref` key (`programs.py:1360`) |
| D3 explicit `None` | `slot_ref=None` | **same** as D2 (non-None-only rule) | **PASS** `compiles COMPILED`, `content_hash` equals D2, `_h_to_dict` omits (`programs.py:1360 if h.slot_ref is not None`) |
| D4 v2 noslot | `schema_version="2"` same content | valid v2 program, different identity (schema_version is hash input `programs.py:1433`) | **PASS** `COMPILED`, hash differs from D1 (expected) |
| D5 v1→v2 recompilation | same semantic content, v1 hash vs v2 hash | MUST differ (no silent preservation) | **PASS** documented: version is identity input |
| D6 persisted v1 reload | persist v1 via `repo.record`, reload `repo.get` | no mutation, `content_hash`/`program_id` stable despite current being v2 | **PASS** `record` preserves claimed hash (`repositories.py:1325` set-membership accepts "1") |
| D7 gateway vs direct | same payload via `compile_from_payload` vs `apply_intent` | identical identity | **PASS** `direct.program_id == gateway.entity_id` |

**AC-1 Delta=0 THE gate:** slot-less program recompiles to identical hash under post-C1 compiler because `slot_ref` is omitted when `None` and `schema_version="1"` remains in `SUPPORTED`. Slot participation: same slot → same `program_id`, different slot → different `program_id`, rationale change → same `program_id` (AC-5).

---

## 6. Schema-Version Attack

| Vector | Validation (`programs.py:622`) | Persistence (`repositories.py:1325`) | Agreement |
|--------|-------------------------------|--------------------------------------|-----------|
| `"1"` | `COMPILED` | `record` persists `schema_version="1"` | ✓ |
| `"2"` (current default) | `COMPILED` | `record` persists | ✓ |
| `"3","0","999",""` | `INVALID SCHEMA_VERSION_MISMATCH` | `ResearchProgramIntegrityError` (same set) | ✓ |
| `None` missing key | defaults to `"2"` (`_draft_from_payload:1337`) → `COMPILED` | — | ✓ |
| wrong type `int` | `MALFORMED_PAYLOAD` via `_require_str` | — | ✓ |
| forged `"999"` self-consistent hashes | `INVALID` | `IntegrityError` (re-derived identity + set check) | ✓ |
| `ResearchProgramDraft()` default | `schema_version=="2"` (`programs.py:296`) | — | ✓ |

No validator/write disagreement exploitable. Defaulting to `"2"` does not migrate existing v1 rows; v1 remains valid and retains original `content_hash`.

---

## 7. Full-History Vocabulary Attack

Definition `hermes_c1_slot_ref_design_gate.md:4.3` — union over ALL `research_programs` rows per project, append-only.

- **Insertion order:** orders `[1,2,3]`, `[3,2,1]`, `[2,1,3]` → `frozenset({"slot:slot_1","slot:slot_2","slot:slot_3"})` identical (`repositories.py:1559 ORDER BY version ASC`).
- **Duplicate historical slots:** two hypotheses same `slot:explain_momentum` → `vocab == {"slot:explain_momentum"}` single entry.
- **Superseded slots remain:** `slot:x` v1 → `slot:y` v2 → slotless v3 → `vocab == {"slot:x","slot:y"}` (grandparent/parent included).
- **Abandoned/REFUTED:** same as superseded — never retired.
- **Replay stable:** pure function of immutable rows, sorted `used_slots`/`declared_slots` before checks, `canonical_json` sorted.

**Orphan/declaration confusion:** declaration metadata is audit-only; vocabulary is `hypothesis_json` only.

---

## 8. Project Isolation Attack

Mandatory per ratification: `hermes_architecture_ratification.md:6.2` project-scoped.

- **Isolation 1:** `proj-a slot:isolated_a` admitted via `apply_intent`; `repo.slot_vocabulary("proj-b") == frozenset()` — not leaked.
- **Isolation 2:** `proj-b` using `slot:isolated_a` without declaration → `E6_SLOT_UNDECLARED` (`INVALID`), not `COMPILED` (leak would have admitted).
- **Isolation 3:** identical label `slot:X` declared independently in both projects → both `COMPILED` with independent vocabularies — correctly isolated, not globally deduplicated.
- **Isolation 4:** `proj-a slot:second_a` via supersession → `vocab_a {"slot:isolated_a","slot:second_a"}`, `vocab_b {"slot:isolated_a"}` — no leakage; all queries `WHERE project_id=?` (`repositories.py:1558,1203,1212,1508,1527`); no global cache.
- **Serialization/reload:** `slot_vocabulary` re-reads `hypothesis_json` from DB each call (`1535`), no in-process stale cache.

SQL filter audit: every C1-related read (`slot_vocabulary`, `superseded_program_ids`, `list_for_project`, `current`) predicates on `project_id`.

---

## 9. Determinism Attack

- **Canonical serialization:** `_canonicalize` sorts dict keys, sorts list-of-dicts by canonical JSON, sorts scalar lists by `str` (`programs.py:339`) — ordering nondeterminism defeated (adversarial D).
- **Vocabulary construction:** `set` then `frozenset` plus sorted iteration over `used_slots`/`declared_slots` (`programs.py:969,982`) — deterministic.
- **Identity:** `content_hash = sha256(canonical_json(canonical_content_dict))` (`1437`) — same slot → same hash, different slot → different hash, same content different order → same hash (hypotheses/predictions sorted via canonicalization).
- **Cross-insertion determinism:** `slot_vocabulary` deterministic regardless of DB insert order due to `ORDER BY version ASC` and set equality.

---

## 10. Provenance/Event Attack

Contract: `program rows → canonical vocabulary` is source of truth; `new_slot_declarations` → audit/provenance, never alternative vocabulary.

- **Delete declaration event:** `DELETE FROM events WHERE event_type='ResearchProgramCompiled'` → `slot_vocabulary` still `{"slot:real_slot"}` (from `hypothesis_json`). PASS.
- **Duplicate/forged declaration event:** inserted fake `ResearchProgramCompiled` with `slot:fake_via_event` → `vocab` unchanged (not in `hypothesis_json`). PASS.
- **Reorder declaration events:** vocab unaffected (not event-derived).
- **Add declaration without use:** `E6_SLOT_DECLARATION_UNUSED` at compile and now at write path.
- **Remove declaration from valid program:** `E6_SLOT_UNDECLARED` if not in vocab.
- **Event payload tamper:** mutating `events.payload_json` post-admission does not change `content_hash`, `program_id`, or vocab (vocab reads `research_programs.hypothesis_json` only).
- **Rationale:** appears in `ResearchProgramCompiled` payload only when `new_slot_declarations` present (`gateway.py:315`, `repositories.py:1480`), never in `canonical_content_dict` (`programs.py:1408`). Different rationale → same `content_hash` (AC-5).

---

## 11. Serialization Attack

| Vector | Input | Result |
|--------|-------|--------|
| missing `slot_ref` | no key | `COMPILED`, no `slot_ref` in canonical |
| `slot_ref=None` explicit | `None` | `COMPILED`, same hash as missing (non-None-only) |
| `slot_ref=""` | empty string | `E6_SLOT_MALFORMED` |
| whitespace `"   "` | | `E6_SLOT_MALFORMED` |
| wrong type `int`/`dict` | | `MALFORMED_PAYLOAD` at `_draft_from_payload` |
| extremely long `slot: a*130` | 135 chars | `E6_SLOT_MALFORMED` (>128) |
| boundary `128`/`129` | `slot: a*123` / `slot: a*124` | `COMPILED` / `INVALID` |
| unicode `slot:α` | | `E6_SLOT_MALFORMED` (ASCII only `_SLOT_REF_RE`) |
| key ordering reversed hypotheses | | same `content_hash` (canonical sort) |
| unrelated optional fields | unknown keys | `UNKNOWN_PAYLOAD_KEY` (closed schema) |
| nested structures, omitted vs null | | stable per `_canonicalize` |

No historical payload hash drift except intentional `slot_ref` addition or version change.

---

## 12. Race/TOCTOU Assessment

Gateway flow: `slot_vocabulary()` read (`gateway.py:254`) → `compile_from_payload` (`285`) with that vocab → `record()` (`315`) which re-derives identity and now re-validates E6 against `slot_vocabulary()` again (`repositories.py:1366+`).

Window between vocab read and `record` `BEGIN IMMEDIATE` is not transactional: two concurrent writers using same project could both observe empty vocab, both declare `slot:contested` with rationale, both compile `COMPILED`, and both enter `record` with `BEGIN IMMEDIATE` serialized. First `INSERT` succeeds; second `INSERT` will see `vocab` now contains `slot:contested` due to the fresh `slot_vocabulary()` read inside `record`'s E6 re-validation (pre-transaction but after first commit's `COMMIT`). Second writer's `new_slot_declarations=[slot:contested]` will be rejected `E6_SLOT_ALREADY_DECLARED` at write path — fail-closed, no vocabulary corruption, but the second writer observes a validation-time success that becomes a persistence-time rejection.

**Severity:** **ACCEPTED** (not P1). Architecture intentionally tolerates this: `hermes_research_architecture_v6.md` §28.2 Model D + gateway comment that budget/ordering are deferred; no requirement for serializable `slot` reservation. The invariant protected is **vocabulary append-only correctness**, not concurrent declaration availability. No new locking introduced (per hard-stop: do not introduce locking merely for theoretical race). If stronger reservation needed, a future amendment would add a unique constraint or reservation intent, not a silent lock here.

No other TOCTOU violates ratified invariants.

---

## 13. Authority-Escape Assessment

Searched every occurrence of `slot_ref`, `slot_vocabulary`, `new_slot_declarations`, `PROGRAM_SCHEMA_VERSION`/`SUPPORTED_PROGRAM_SCHEMA_VERSIONS`.

- `slot_ref` appears only in `programs.py` (definition, `_h_to_dict`, E6, draft parsing), `repositories.py` (vocab projection `1535`, write-path E6 `1366+`), `gateway.py` (vocab pass-through `254,285` + declaration threading `315`).
- No occurrence in `controller.py`, `evaluation.py` (except unrelated `floor_slots`/`slots` scheduling slots), `task_status.py`, `lifecycle.py`, `modes.py`, or budget/evidence ladder.
- `DIMENSION_ORDER` unchanged (`evaluation.py:489` six dimensions), `IntentKind` unchanged (14 kinds), `SUPPORTED_VERSION` migration `14` unchanged.
- Coverage: `slot_ref` never read for scheduling, priority, eligibility, evidence promotion, budget, task creation, lifecycle transitions, or mutation authority.

**Verdict: PASS — no authority escape. C1 remains identity/provenance only, as ratified `design_gate.md:3`/`8`.**

---

## 14. Corrupted-History Assessment

| Corruption | Injection | Expected `AC-7` behavior | Observed |
|------------|-----------|---------------------------|----------|
| malformed JSON `hypothesis_json='NOT_JSON'` | raw `INSERT INTO research_programs` | raise `ResearchProgramError` (fail-closed, not shrink vocab) | **PASS** `repositories.py:1566 raise ResearchProgramError` |
| `slot_ref` not `str` (`123`) | | raise | **PASS** (`1591`) |
| `hypothesis_json` not list | | raise | **PASS** (`1575`) |
| hypothesis entry not dict | | raise | **PASS** (`1582`) |
| invalid schema version persisted via bypass | forged `"999"` self-consistent | `ResearchProgramIntegrityError` at write path | **PASS** (`1325`) |
| gateway with corrupt vocab row present | `apply_intent` | `GatewayRejection MALFORMED_PAYLOAD` (reject, never crash) | **PASS** (`gateway.py:254 except → _reject MALFORMED_PAYLOAD`) |

No silent ignoring, no shrinking, no invalid acceptance.

---

## 15. S7 Compatibility Assessment

S7 deferred (`hermes_architecture_ratification.md:6.3`). C1 must provide information S7 will need without implementing S7.

- Historical slot `slot:ancient_mech` admitted, superseded by `slot:other_slot` → `vocab == {"slot:ancient_mech","slot:other_slot"}` — both discoverable.
- `slot:ancient_mech` remains in `slot_vocabulary()` even after lineage abandoned — resurrected hypothesis can be screened via `slot equality + distinct content_hash lineage` (IDR-041 model).
- C1 adds `slot_ref` axis to program rows, not to resurrection authority; S7 will be advisory human-gated (`design_gate.md:5.4`).

**Boundary clean: PASS.** No S7 implementation, no premature resurrected-state transition.

---

## 16. Backward Compatibility

- `SUPPORTED_PROGRAM_SCHEMA_VERSIONS == frozenset({"1","2"})` (`programs.py:117`) — both accepted at validation and persistence (identical set via `repositories.py:1298` import).
- New drafts default to `"2"` (`programs.py:296`, `1337` payload omission) — does not migrate existing rows; v1 rows retain `schema_version="1"` and original `content_hash`.
- V1 programs remain valid: `compile_from_payload(schema_version="1")` → `COMPILED`, `repo.record` persists, `repo.get`/`current`/`list_for_project` preserve hash, gateway admits v1.
- V2 programs compile and persist distinctly; v1 identity never rehashed silently.
- Unsupported `"3","0","999","", int` consistently rejected both boundaries.

---

## 17. Test-Quality Assessment

| Invariant | Test exists? | Tests actual boundary? | Adversarial? | Verdict |
|-----------|--------------|-------------------------|--------------|---------|
| AC-1 Delta=0 | `test_c1_slot_ref.py:54 TestAC1DeltaZero` 3 tests + golden pins | Yes — live pre-C1 goldens `5d4a7f...`/`3d6de28...`, independent hashlib, `slot_ref` absent in canonical, slotless event shape unchanged | Yes (Naive None-emission would fail) | **STRONG** |
| v1 compatibility | `TestSchemaVersionContract.test_v1_program_persists_at_write_path` | Yes — persists v1, checks `content_hash==GOLDEN_BASE_CONTENT` | Yes | **STRONG** |
| v2 default | `test_supported_set_is_exactly_1_and_2`, `test_current_default_version_is_2`, `test_payload_omitting_schema_version_defaults_to_2` | Yes — `ResearchProgramDraft()` and payload omission both default `"2"` | Yes | **STRONG** |
| unsupported rejection + validator/write agreement | `test_unsupported_versions_rejected_at_validation`, `test_unsupported_version_rejected_at_write_path` | Yes — both boundaries, forged `"999"` self-consistent | Yes | **STRONG** |
| FULL-HISTORY vocab | `TestAC4AppendOnlyReplayStable` 3 tests + `TestAC7Reachability` | Yes — order-independent `frozenset`, superseded retained, pre-C1 tolerated, grandparent reachability | Yes (reverse insert) | **STRONG** |
| project isolation | Adversarial probe `proj-a/b` vocab isolation (not in committed tests before gate) + now implicit via `slot_vocabulary WHERE project_id` | Boundary actually exercised via live DB two-project test | Yes | **STRONG** (would benefit from committed isolation fixture — not required for closure) |
| declaration vs vocabulary | `TestAC3ClosedVocabulary` 6 tests + G provenance probe | Yes — `E6_SLOT_UNDECLARED`/`ALREADY_DECLARED`/`DECLARATION_UNUSED`/`MALFORMED`, rationale in event not in content | Yes | **STRONG** |
| deterministic reconstruction | `TestAC4…pure_function`, `TestAC2SlotParticipation` | Yes — same slot same ID, different slot different ID, rationale not hashed | Yes | **STRONG** |
| malformed history fail-closed | `TestAC7Reachability.test_corrupt_row_fails_closed`, `test_gateway_refuses_on_corrupt_vocabulary` | Yes — `NOT_JSON` → `ResearchProgramError` + `GatewayRejection MALFORMED_PAYLOAD` | Yes | **STRONG** |
| None serialization | `TestAC1DeltaZero.test_ac1_no_slot_ref_key_in_canonical_dict` + `_h_to_dict` check | Yes — asserts absent key, would catch `"slot_ref":None` drift | Yes | **STRONG** |
| direct/gateway consistency | D7 probe + `test_v1_program_persists` + gateway admission `test_rationale_in_event_not_in_content` | Yes — coherent across `compile_from_payload`/`apply_intent`/`repo.record`/`repo.get` | Yes | **STRONG** |
| write-path E6 (new) | `TestWritePathSlotDiscipline` 7 tests | Yes — forged COMPILED bypass for undeclared/malformed/overlong/orphan/redecl, plus valid new/reuse | Yes | **STRONG** |

No test merely checks implementation detail without invariant; all pin observable behavior. One gap (project isolation) was probed live at gate and proven, though a committed isolation fixture would be P3 hygiene, not a blocker.

---

## 18. Findings by Severity

| ID | Severity | Title | Status |
|----|----------|-------|--------|
| F-01 | **P1 Step-3 blocker** | Write-path E6 bypass allows vocabulary poisoning via forged `COMPILED` (undeclared/ malformed/ over-long/ orphan/ re-declared `slot_ref` persists via direct `ResearchProgramRepository.record()` bypass, polluting FULL-HISTORY vocab) | **FIXED** `cb1f8e1` |
| — | P2 | Gateway second admission of same slotted payload with `new_slot_declarations` already in vocab → `E6_SLOT_ALREADY_DECLARED` (non-idempotent exact-payload retry) | **ACCEPTED** — by design; `design_gate.md:4.3` requires re-declaration rejected, idempotency is `content_hash`-based via `slot:reused` without declaration (`TestWritePathSlotDiscipline.test_write_path_accepts_reuse…`) |
| — | P3 | Committed tests lacked explicit two-project isolation fixture | **ACCEPTED** — proven live at gate, hygiene only |
| — | P4 | Ruff import order in `repositories.py` | **FIXED** (auto) |
| — | ACCEPTED | `slot:BadCase` in persisted row after manual `INSERT` still counted in vocab (format not re-validated in `slot_vocabulary`) | **ACCEPTED** — harmless: format is re-checked at every `compile`/`record` E6, so polluted malformed vocab cannot be used; write-path now prevents fresh pollution |

No P0 architectural blocker found.

---

## 19. Corrections Applied

**One production correction (P1, minimal, hard-stop compliant):**

File `src/hermes/persistence/repositories.py:1366` (`ResearchProgramRepository.record()`), section `2d`:

- Re-validates every `hypothesis.slot_ref` format (`_SLOT_REF_RE`, `_SLOT_REF_MAX_LENGTH`) — `ResearchProgramIntegrityError` `E6_SLOT_MALFORMED`
- Validates `new_slot_declarations` shape: dict with only `slot_ref`/`rationale`, `slot_ref` format, `rationale` non-empty ≤ `MAX_SLOT_RATIONALE`, no duplicate declaration, not already in `vocab` (`slot_vocabulary(project_id)` fail-closed `AC-7`)
- Both-direction membership: `used ∉ vocab ∧ ∉ declared` → `E6_SLOT_UNDECLARED`; `declared ∉ used` → `E6_SLOT_DECLARATION_UNUSED`
- Uses repository's own `slot_vocabulary()` as source of truth before `BEGIN IMMEDIATE` (same pattern as `resolve_scope_content_hash` governance)

Why necessary: without it, the `gateway` was the only E6 enforcement; the repository's ` EC-V6-11..16 + AR-01` did not cover C1, so a `COMPILED` forgery could poison the vocabulary permanently (vocabulary is union over rows).

Diff: `+133` lines in `repositories.py` (including comments), `+174` lines in `tests/test_c1_slot_ref.py` (7 regression tests).

**No redesign, no C5/C6/S5/S7/P4 change, no mutation path, no slot vocabulary semantics change.**

---

## 20. Final Closure Criteria

| Criterion | Status |
|-----------|--------|
| AC-1 remains Delta=0 | ✓ golden `5d4a7f...` verified |
| v1 identity stable | ✓ persisted v1 reload unchanged |
| v1 and v2 both accepted | ✓ |
| unsupported rejected at all required boundaries | ✓ validator + write agree |
| default schema is v2 | ✓ `PROGRAM_SCHEMA_VERSION="2"` |
| FULL-HISTORY verified | ✓ superseded/abandoned retained |
| vocabulary project-scoped | ✓ `WHERE project_id` |
| deterministic reconstruction | ✓ sorted + `ORDER BY version` |
| declaration not alternative source of truth | ✓ `hypothesis_json` only |
| malformed history does not silently corrupt | ✓ fail-closed `ResearchProgramError` / `MALFORMED_PAYLOAD` |
| validator/write-path semantics agree | ✓ after fix (E6 added to write path) |
| no C1 authority escape | ✓ none in controller/evaluation/task/budget |
| compatible with deferred S7 | ✓ FULL-HISTORY discoverable |
| no P0/P1 remains | ✓ F-01 fixed |
| tests/static checks pass | ✓ 49 C1 + relevant suites, `pyright 0`, `ruff clean` |

---

## 21. Step-3 Closure Decision

**STEP 3 — C1 CLOSED.**

The C1 slot-vocabulary surface faithfully enforces the ratified FULL-HISTORY contract without introducing a new correctness, identity, provenance, isolation, determinism, or authority defect, after the one P1 write-path correction.

---

## 22. Step-4 Authorization

**STEP 4 — AUTHORIZED TO BEGIN.**

S5/S7 architectural/implementation decision gate (per `hermes_architecture_ratification.md:8 Step 4`). Do not implement Step 4 automatically; a separate charter is required. Until S7 lands, the C1 `§5.4` resurrection-screening consumer MUST NOT be claimed operationally complete (prohibited-claims discipline).

---

*End of adversarial closure. Gate executed live against `2b0f52b` + fix `cb1f8e1`, 2026-08-21. Hostile to implementation, conservative on identity/provenance, no manufactured problems. If the implementation survives the attack: CLOSE STEP 3. Then AUTHORIZE STEP 4. And STOP.*
