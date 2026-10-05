# HERMES v6 — STEP 3 LIVE VERIFICATION REPORT

Independent verifier, continuing the closure review (Step 1 CLAIM / Step 2 EXTRACT complete).
Verification performed live against repository HEAD on 2026-08-13. Companion artifact:
`docs/idr/hermes_v6_authority_evidence_map.md` (Step 2).

**No release/ratification verdict is issued in this step** (§18). This step produces fresh
evidence and findings for the next closure stage.

---

## A. Fresh Baseline

| Item | Value |
|---|---|
| Git HEAD | `7de1135f14d080d6863457bc949e6afef2be53e8` |
| Branch | `main` |
| Working-tree state | 1 modified file (`hermes_research_architecture_v6.md` — candidate-status edit, 13+/13-), 1 untracked (`docs/idr/hermes_v6_authority_evidence_map.md`) |
| Python version | 3.14.1 |
| Architecture version | v6 candidate — `IMPLEMENTED + TESTED`, not RATIFIED (§27 item 43 not yet run; working tree converts the doc to "candidate pending external verification") |
| Test command | `.venv/Scripts/python.exe scripts/run_tests.py -v` |
| Collected | 374 |
| Passed | 374 |
| Failed | 0 |
| Errors | 0 |
| Exit code | 0 |
| Runtime | 6.69 s (test run), ~7.1 s wall |

Fresh run, not historical numbers. Test accounting verified independently in §J.

---

## B. ResearchProgram Live Tests

### B1. Priority Attack A — validator-bypass persistence (A1–A6)

All probes construct a `ResearchProgram` by hand (never calling `compile_research_program` /
`compile_from_payload`), wrap it in `CompilationResult(status=COMPILED, program=...)`, and call
`ResearchProgramRepository.record()` on a fresh migrated DB with a frozen brief present.

| # | Input | Result |
|---|---|---|
| A1 | Hand-built program, structurally typed, **empty semantic content** (no hypotheses/predictions) | **PERSISTED** — rows=1, `ResearchProgramCompiled` event emitted, returned dict, `current()` = version 1, `produced_by='attacker'`, hashes stored as forged strings |
| A2 | Semantically invalid: `ROBUST` ladder target with **no prediction** (E1 violation) | **PERSISTED** — rows=1, event emitted |
| A3 | Malformed-but-typed: `hypotheses=()`, `predictions=()` | **PERSISTED** — rows=1, event emitted |
| A4 | Forged `compiler_version="999.999.999"` | **PERSISTED** — stored `compiler_version='999.999.999'`, schema_version stored as supplied |
| A5 | Forged derived obligations: `evidence_requirements` with `ladder_target=REPLICATED`, artifact `garbage_artifact`, empty `gate_requirements` (compiler would derive different obligations) | **PERSISTED** — forged obligations stored verbatim |
| A6 | Confirmatory target (`SUPPORTED`) with **all obligations omitted** (`evidence_requirements=()`, `gate_requirements=()`) | **PERSISTED** — stored with empty obligations |
| Control | Same epistemic content (A2/A6 variants) through the real validator | `INCOMPLETE` — `E1_PREDICTIONS_MISSING ×2`, `E5_RIVAL_COVERAGE` (would have been rejected by `record()`) |

**Conclusion:** `record()` gates on the `compiled` **flag** (`repositories.py:866-872`); it does
not re-validate epistemic content, origin, compiler version, or derived obligations. Every
hand-built COMPILED result persisted atomically with its event. Same content through the
validator → INCOMPLETE → rejected. The flag is the entire epistemic gate.

### B2. Verdict attacks (V1–V6) — non-COMPILED verdicts vs `record()`

| Verdict | Result |
|---|---|
| `INCOMPLETE` (missing E1 prediction) | rejected, rows=0, no program event |
| `CONTRADICTORY` (conflicting predictions) | rejected, rows=0, no program event |
| `UNSUPPORTED` (task_graph_template_ref non-None) | rejected, rows=0, no program event |
| `INVALID` (unknown top-level key) | rejected, rows=0, no program event |
| Hand-built `CompilationResult(INCOMPLETE, program=...)` | rejected on flag alone, rows=0 |
| Hand-built `CompilationResult(INVALID, program=...)` | rejected on flag alone, rows=0 |

All four non-COMPILED verdicts verified live against `record()`: no row, no event, no partial
state (the single residual event in each probe is the fixture's `ResearchCreated`, not a
program event). R-04/PA4 semantics confirmed.

### B3. Closed-schema attacks (C1–C10)

| # | Input | Verdict | Errors |
|---|---|---|---|
| C1 | Top-level unknown key | INVALID | `UNKNOWN_PAYLOAD_KEY` |
| C2 | Unknown hypothesis key | INVALID | `UNKNOWN_PAYLOAD_KEY` |
| C3 | Unknown prediction key | INVALID | `UNKNOWN_PAYLOAD_KEY` |
| C4 | Unknown discrimination key | INVALID | `UNKNOWN_PAYLOAD_KEY` |
| C5 | Nested unknown dictionary | INVALID | `UNKNOWN_PAYLOAD_KEY` |
| C6 | Non-dict hypothesis entry | INVALID | `MALFORMED_PAYLOAD` |
| C7 | Non-list hypotheses | INVALID | `MALFORMED_PAYLOAD` |
| C8 | Non-string ref | INVALID | `MALFORMED_PAYLOAD` |
| C9 | Non-string objective | INVALID | `MALFORMED_PAYLOAD` |
| C10 | Invalid enum | INVALID | `MALFORMED_PAYLOAD` |
| Control | Clean payload | COMPILED | — |

Key property verified: malformed/untrusted semantic input **fails closed** — every case yields a
deterministic `INVALID` verdict, never an exception, never coercion, never a valid program
(EC-F01 recursive check confirmed live).

### B4. Scope-governance attacks (D1–D9)

| # | Test | Result | Enforced at |
|---|---|---|---|
| D1 | Valid ScopeBrief + matching hash | accepted, rows=1, event | — |
| D2 | Valid brief + **forged** hash | validator returns **COMPILED**; write path rejects (`R-02` message), rows=0, no program event | **write path only** (validator does not validate the hash) |
| D3 | Missing ScopeBrief | rejected (`ScopeBrief not found`), rows=0 | repository (governance) |
| D4 | Wrong `project_id` | rejected (`program project 'p1' does not match 'p9'`), rows=0 | repository |
| D5 | Supersede non-head | rejected (`Supersede target ... is not the current head (E9)`), no new row | repository |
| D6 | Supersede with identical content | rejected (`supersession must change program content`), rows=1 | repository |
| D7 | Supersede current head | accepted, version=2, `supersedes_id` set, head=2 | — |
| D8 | Mutate old version | repository: **no update/delete methods exist** (structural); raw SQL `UPDATE`/`DELETE` **succeed** (no DB triggers) | repository API level only — not DB level |
| D9 | Two current heads | rejected (`already has a ResearchProgram ... E9`); additionally `UNIQUE (project_id, version)` at DB level | repository + database |

Enforcement-layer note (§6 requirement): governance checks are enforced at the **repository
write path**, never in the validator; two-head prevention is additionally DB-enforced
(`UNIQUE (project_id, version)`). Immutability is structural at the repository API
("no update/delete path"), **not** enforced at the DB layer.

---

## C. ActionEvaluation Live Tests (F1–F10)

| # | Test | Result |
|---|---|---|
| F1 | Order/history/stale invariance | invariant — identical `ranking_id`, `comparison`, `diagnostics` under all shuffles |
| F2 | Duplicate refs `[c1, c1, c2]` | kept as 3 distinct entries; `input_state_hash`/`content_hash` include the duplicate; no dedup. IDR-019 requires no dedup ⇒ **consistent with contract** |
| F3 | Unknown dimension key | silently ignored (not read); missing known keys default to `NONE` (`evaluation.py:283`) — no rejection, no diagnostic. IDR-019 silent ⇒ not a contract defect; see EC-V6-05 |
| F4 | `cost="CRAZY"` (typed violation) | **raises `KeyError: 'CRAZY'`** at `_ordering_key` (`evaluation.py:320`) — fail-loud exception, no coercion, no partial state. See EC-V6-06 |
| F5 | Gate dominance (all-HIGH candidate `blocked_by` gate) | **excluded** (`EXCLUDED_GATE`), never ranked — verified |
| F6 | Unsatisfied dependencies | excluded with `BLOCKED_DEPENDENCY` + reason (`unsatisfied dependency (route via engineering plane): exp-9`) |
| F7 | No improvement | `NO_IMPROVEMENT` diagnostic (`stop/pause/human — never pass`) |
| F8 | Stale input | `STALE_INPUT` diagnostic, flagged per-candidate + diagnostic |
| F9 | Empty candidate set | `EMPTY_CANDIDATE_SET` diagnostic; 0 comparison rows; deterministic `ranking_id` (nothing invented) |
| F10 | Cross-process determinism | 2 fresh interpreter processes ⇒ **identical** `ranking_id`/`content_hash`/`input_state_hash` |

---

## D. Authority Boundary Results (Attack B)

- **B1/B2/B3:** `Intent(PROPOSE_RESEARCH_PROGRAM, proposed_by=...)` constructs successfully for
  `RESEARCHER`, `ADVERSARY`, `IMPLEMENTER`, arbitrary strings, **empty string**, and `DIRECTOR`.
  `is_llm_proposable()` is `True` for all. No construction-time role decision exists.
- **B4:** walk of every module in `hermes.*`: **no admission/dispatch/gateway function exists
  anywhere** (no `apply_intent`).
- **B5:** `research/gateway.py` is a 4-line placeholder ("Phase 0: placeholder").
- **B6:** `IntentKind.director_only()` is referenced **only** in `intents.py` (metadata);
  nothing at runtime consumes it.
- **Classification:** no gateway exists ⇒ **DEFERRED / P3 CONTRACT**, not a runtime failure.
  v6 represents this honestly: `intents.py` docstring ("the gateway ... lands in P3"),
  §28.2 ("bypass the gateway (the intent kind is Director-only ... admitted through the
  normal path)"), IDR-018 ("the P3 `apply_intent` per-kind validator"). See EC-V6-02 for the
  one type-level wrinkle (kind is both `llm_proposable()` and `director_only()`).

---

## E. Persistence Boundary Results

- COMPILED-flag gate: works exactly as contracted (V1–V6); non-COMPILED never persists.
- **Epistemic trust boundary (EC-V6-01):** the flag is caller-set; origin is not verified
  (A1–A6). Full analysis in §K.
- **Atomicity (R-04) — failure injection at 5 points, all clean:**

| Injection point | Failure | Program rows | Events | Half-state |
|---|---|---|---|---|
| P1 before program INSERT | BEFORE INSERT trigger | +0 | +0 | **no** |
| P2 after program INSERT, before event | AFTER INSERT trigger | +0 | +0 | **no** |
| P3 during event validation | monkeypatched S6 validator raises | +0 | +0 | **no** |
| P4 during event INSERT | BEFORE INSERT trigger on `events` | +0 | +0 | **no** |
| P5 immediately before COMMIT | commit raises | +0 | +0 | **no** |

Program row + `ResearchProgramCompiled` event are **both present or both absent** under every
failure mode (`BEGIN IMMEDIATE` + `try/except ROLLBACK`, `repositories.py:897-1011`).

---

## F. Governance / Scope Results

See D1–D9 (§B4). Governance enforcement boundary is the repository write path (R-02 hash
re-resolution from DB, frozen-brief existence, head-only supersession, identical-content
rejection, single-head). Supersession chain: verified live (D5/D6/D7).

---

## G. Evidence Boundary Results (Attack 12)

- **Current structural closure:** `research/programs.py` and `research/evaluation.py` contain
  **no callable evidence-promotion path** — no `EVIDENCE_TRANSITION` use, no status fields,
  no evidence-interface methods (verified by source audit + live import scan). `ladder_target`
  is a declared target; `HypothesisSpec` has no evidence status (E8).
- **Future compatibility:** §28.2 "CANNOT mark any claim supported/promoted (E8 — no status
  field exists; payload-level unknown-key rejection closes the door)" and §27 item 45
  (permanent rule: no future phase may let compilation, the program, the graph, or any LLM
  proposal mark a hypothesis without the §10.2 preconditions) are documented. Not a defect
  that Evidence is absent — it is explicitly deferred (P2 §27 item 43-era roadmap); the
  separation is regression-pinned (E8 tests present).
- **Verifier note:** no Evidence code exists, so "no promotion path" is structural by
  absence; the permanent rule (EC-V6-09b) must be re-pinned when Evidence lands.

---

## H. Provenance Results (Attack 13)

- Existing links, live schema inspection: `research_programs` carries `produced_by`, `reason`,
  `created_at` (E9) and `supersedes_id` (chain). No `tasks`/evidence FK or link columns on
  `research_programs`; no provenance table row exists for ResearchProgram→Task.
- Classification: ResearchProgram→Task links **DEFERRED** (P3 gateway + GR7 template
  instantiation, P6); Evidence/provenance spine **DEFERRED** (P2 roadmap). Supersession and
  ScopeBrief governance are **LIVE** (verified D1–D9).
- `produced_by` is **recorded, never verified** (caller-supplied string; verified in A1:
  `produced_by='attacker'` persisted). Consistent with E9-as-provenance; relevant to
  EC-V6-01.

---

## I. Adversarial Results

- Validator-bypass persistence: **confirmed** (A1–A6) — see EC-V6-01.
- Closed-schema: **all 10 fail closed** (C1–C10).
- Verdicts: **all 4 non-COMPILED rejected with zero residue** (V1–V4; hand-built V5/V6 too).
- Governance: **8/9 correct**; D8's raw-SQL mutation is possible (no DB triggers) — see
  EC-V6-07.
- Determinism: invariant + cross-process (F1, F10).
- No-write: evaluation.py and programs.py have no authority surface (zero direct/transitive
  hits; programs.py's only match is a docstring mention of `apply_intent`); no module outside
  the new files references the new surfaces at runtime (`hermes.artifacts.store`'s `.record(`
  is its own artifact repo — false positive).
- Evaluator typed-violation: raises `KeyError` (F4) — fail-loud, cryptic; see EC-V6-06.

---

## J. Test Count Verification

| Line | Source | Count |
|---|---|---|
| v4 baseline | `d9797ee` (commit states 280 passed) | 280 |
| IDR-017 additions (+8) | `215dc4d` (`test_phase1_acceptance.py` +216 lines) | 288 |
| ResearchProgram (+45) | `37f523b` (commit message: "45 new tests; full suite 333 passed") | 333 |
| R-01..R-04 (+6) | `ecf762a` (`test_research_program.py` +99 lines; regression tests incl. R-04 failure-injection) | 339 |
| ActionEvaluation (+31) | `7de1135` (`tests/test_evaluation.py`, new, 365 lines) | 370 |
| EC closures (+4) | `7de1135` (`tests/test_research_program.py` +56 lines) | 374 |

- Fresh `pytest --collect-only`: **374** collected; `test_research_program.py`=55,
  `test_evaluation.py`=31 (matches doc numbers 55/31).
- Fresh full run: 374 passed, 0 failed, exit 0. **Accounting VERIFIED.**

---

## K. Findings

### EC-V6-01 — `record()` trusts the COMPILED flag; "no direct mutation bypass (E6/E7)" is not structurally enforced (P2)

**Evidence (live):** A1–A6 — every hand-built COMPILED result persisted (row + event) even
when the identical epistemic content yields `INCOMPLETE` from the real validator; forged
`compiler_version`, forged derived obligations, and omitted obligations all stored verbatim;
`produced_by` accepted from any caller.

**Normative wording:**
- IDR-018 §5: repository contract = "only a `COMPILED` result may be persisted (E6/E7 — no
  direct mutation bypass)". The gate is on the result's status; the architecture does **not**
  require the repository to re-run the validator — the repository is intentionally a
  lower-level trust boundary ("persist a previously validated COMPILED result").
- v6 §28.2: epistemic validation is the validator's job; the write path re-verifies
  **governance** (R-02 hash), not epistemic content — consistent with D2b live result.
- E6/E7 are defined as "no write path in the validator; closed payload schema; versioning-only
  change path" — those are enforced. The additional phrase "no direct mutation bypass" is
  claimed as structural ("E6/E7 enforced structurally", IDR-018 §5) but the only structural
  mechanism is a **boolean flag on a caller-constructed object**.
- `produced_by`: recorded as provenance (E9), never verified (B1–B3: any string accepted).

**Answers to §15 questions:**
1. Is `record()` intentionally lower-level? **Yes** — the approved text gates on the COMPILED
   result, not on origin.
2. Does IDR-018 require re-validation at the repository boundary? **No** — it requires only
   COMPILED status; governance (R-02) is separately required and IS enforced at the write path.
3. Does v6 define `CompilationResult(COMPILED)` as trusted input? **Implicitly yes** — the
   authority model (T1: "Controller / validators / gateway — trusted") assumes only the
   validator produces results; no text addresses a hand-built result.
4. Is `produced_by` trusted or verified? **Trusted/recorded**, never verified (E9 provenance).
5. Can an unauthorized caller construct a valid-looking compiled result? **Yes, trivially**
   (A1–A6); a 15-line script with a DB handle does it.
6. Can such a caller bypass the Director-only intent metadata entirely? **Yes** — there is no
   gateway, no admission function, no runtime consumer of `director_only()` (B4–B6). The
   metadata is the *entire* defense and it is inert at HEAD.

**Classification:** Not a P0/P1 defect against the normative text as written (the repository
contract is flag-gated; the gateway is an explicitly deferred P3 phase boundary; the
single-operator trust model, v6 §21, assumes one trusted human on one machine). It **is**:
(a) a real, localized, **callable authority surface at HEAD** — the only guard between any
Python caller with a DB handle and a persisted, evented program is a self-set boolean; and
(b) an **architectural ambiguity + doc overstatement** — "no direct mutation bypass (E6/E7)"
is materially weaker than "enforced structurally" claims. Under the stated trust model this is
bounded (local, single-operator, immutable chain, governance + atomicity verified), so:
**P2 — must be explicitly classified and resolved before ratification**, at minimum by a
normative statement in §28.2/IDR-018 that the persistence boundary trusts a COMPILED result's
flag and that origin enforcement is the P3 gateway's responsibility (with a regression test
pin), or by adding a validator-origin marker. **Owner: architecture amendment (Step 4), not
P2 code.**

### EC-V6-02 — `PROPOSE_RESEARCH_PROGRAM` is both `llm_proposable()` and `director_only()` (P3)

`intents.py:47-53` includes it in `llm_proposable()`; `intents.py:56-63` declares it
Director-only. The doc resolves this by design ("LLM-proposable, admitted through the normal
path"; Director is the semantic proposer). At HEAD this overlap is metadata-only (no gateway).
Not a defect; must be enforced by the P3 per-kind validator (`proposed_by` check) — record as
a Step-4 admission-chain requirement.

### EC-V6-03 — No admission function exists at HEAD (P3, DEFERRED)

`gateway.py` = Phase 0 placeholder; no `apply_intent` in the codebase (B4/B5). Classified
**DEFERRED / P3 CONTRACT**, honestly represented in v6 and intents.py. Not a runtime failure.

### EC-V6-04 — Duplicate `candidate_ref`s kept as distinct entries (observation, P3)

F2: `[c1, c1, c2]` ranks 3 entries; hashes include the duplicate. IDR-019 is silent on
deduplication ⇒ current behavior is consistent with the approved contract. Decision on dedup
(or explicit rejection) belongs to a future schema-hardening pass.

### EC-V6-05 — `CandidateAction.dimensions` has no closed-schema check (observation, P3)

F3: unknown keys silently ignored; missing keys default `NONE` (`evaluation.py:283`). Unlike
ResearchProgram (EC-F01), the evaluator has no unknown-key rejection for dimensions. IDR-019
does not require one; impact is nil today (transient, advisory, no write surface, typed
caller). If `CandidateAction` ever becomes a schema'd LLM input, add the closed-schema check.

### EC-V6-06 — Typed violation in evaluator raises raw `KeyError` (minor, P3)

F4: `cost="CRAZY"` → `KeyError: 'CRAZY'` at `_ordering_key`. Fail-loud, deterministic, no
coercion, no partial state — acceptable. Optional improvement: structured error instead of
`KeyError` when the evaluator gains a schema'd-input surface.

### EC-V6-07 — Immutability is API-level, not DB-level (observation, P3)

D8: no repository UPDATE/DELETE methods (structural ✓); raw SQL UPDATE/DELETE succeed (no
triggers). The claim "immutability is structural" is accurate **at the repository level**.
Under the single-operator trust model this matches the rest of the store; the enforcement
boundary should be stated precisely in the doc if DB-level enforcement (triggers) is ever
desired.

### EC-V6-08 — §28.2 failure-semantics line overstates the validator (doc fix, P3)

"governance mismatch → rejected at validator *and* at the write path": live D2 shows the
validator returns **COMPILED** for a forged scope hash (the hash is identity input, not
checked); rejection occurs **only** at the write path (D2b). The same section's R-02 wording
is correct. Internal inconsistency — wording fix required (no behavior change).

### EC-V6-09 — Verified positives (baseline for ratification)

- (a) Deterministic identity (AC-01/08/09) — VERIFIED live (control COMPILED; D1; F1; F10).
- (b) Closed schema fails closed (AC-02/03/04, EC-F01) — VERIFIED (C1–C10).
- (c) Write-path governance + immutability + head-only supersession (AC-06, R-02, E9) —
  VERIFIED (D1–D9).
- (d) Atomicity (R-04) — VERIFIED at 5 failure-injection points (P1–P5).
- (e) Non-COMPILED never persists (E6/E7 flag gate) — VERIFIED (V1–V6).
- (f) No evidence promotion (E8) — VERIFIED structurally + documented permanent rule (§27
  item 45); re-pin when Evidence lands.
- (g) Evaluator: no write surface, no candidate generation, gates dominate, failures surfaced
  (AC-03/04/05/06, §28.3 rules) — VERIFIED (g1–g3, F5–F9).
- (h) Provenance recorded (E9), governance chain live — VERIFIED (g6, D-series).

---

## L. Contract Status Matrix

| Contract | Result | Evidence |
|---|---|---|
| RP-01 deterministic identity (AC-01/08/09) | **VERIFIED** | control COMPILED; D1; suite 55 tests |
| RP-02 verdicts deterministic & structured | **VERIFIED** | V1–V4; control INCOMPLETE with E1/E5 codes |
| RP-03 closed schema, no coercion | **VERIFIED** | C1–C10 all INVALID; control COMPILED |
| RP-04 write path enforces governance + immutability, atomic (R-02/E9/R-04) | **VERIFIED** | D1–D9; P1–P5 no half-state |
| RP-05 no evidence promotion (E8) | **VERIFIED** | g5; §28.2; §27 item 45 |
| RP-06 no second write path / "no direct mutation bypass" | **PARTIALLY VERIFIED** | flag gate works (V1–V6) but hand-built COMPILED bypasses epistemic validation (A1–A6) → EC-V6-01 |
| AE-01 deterministic versioned identity (AC-01/12) | **VERIFIED** | F1, F10 cross-process identical |
| AE-02 no scalar score, lexicographic policy | **VERIFIED** | structure + suite (31 tests) |
| AE-03 gates dominate, never ranked (AC-03) | **VERIFIED** | F5 |
| AE-04 failures surfaced, not hidden | **VERIFIED** | F7/F8/F9 |
| AE-05/06 no write path, no candidate generation | **VERIFIED** | g1/g3; F9 `EMPTY_CANDIDATE_SET` |

---

## M. Central Authority Claim

**CONFIRMED WITH DEFERRED CONDITIONS.**

The central claim — *the current architecture structurally prevents the new components
(ResearchProgram, ActionEvaluation) from becoming alternate authorities* — holds for the
**current P2 surfaces**, verified live:
- The validator and evaluator are pure computations with **no write surface** and no runtime
  callers outside their own modules.
- The only write path (`ResearchProgramRepository.record()`) enforces governance, immutability,
  supersession semantics, and atomicity — all verified by direct execution.
- No evidence-promotion path exists, structurally and by documented permanent rule.
- Closed schema, deterministic identity, gate-dominance, and fail-loud diagnostics all
  verified by live attack.

But three explicit conditions qualify it:
1. **EC-V6-01 (P2):** the `record()` COMPILED-flag trust boundary is a real, localized,
   callable authority surface; "no direct mutation bypass" is overclaimed in the docs and the
   currently sole defense (gateway Director-only enforcement) is a P3-deferred contract with
   zero runtime presence at HEAD.
2. **P3 admission chain must materialize:** `apply_intent` + per-kind validator enforcing
   `director_only()`/`proposed_by` + the human gate (§9.1) — this is the enforcement chain
   whose absence EC-V6-01 exposes.
3. **P3+/P6+ integrations (gateway task instantiation, Evidence, GR7 templates) must preserve
   the §28.1 authority invariant and §27 item 45 rule** — these are the future conditions the
   claim's truth depends on, and each is tracked.

Not REFUTED (no unmitigated authority leak exists within the current implemented surface under
the documented single-operator trust model); not UNVERIFIED (all claims exercised by fresh
execution); not bare CONFIRMED (EC-V6-01 is a genuine current gap in the *documented*
enforcement claim, not merely a roadmap item).

---

## N. What Step 4 Must Attack

1. **EC-V6-01 decision:** ratify the normative reading — either (a) state explicitly that the
   persistence boundary trusts a COMPILED result's flag and origin enforcement belongs to the
   P3 gateway (with a regression test pinning the contract), or (b) require repository-side
   origin/re-validation. Fix IDR-018 §5 "enforced structurally" overstatement and §28.2
   "rejected at validator *and* write path" (EC-V6-08).
2. **P3 admission chain:** design the `apply_intent` per-kind validator for
   `PROPOSE_RESEARCH_PROGRAM` — `proposed_by` enforcement, LLM-proposability + Director-only
   overlap (EC-V6-02), human-gate wiring — and verify it closes the EC-V6-01 exposure at the
   gateway level.
3. **P3+ task instantiation:** verify that program → `INSERT_TASK`/GR7 wiring gives the
   program no direct task-write path (authority invariant §28.1(a)).
4. **P2+ Evidence landing:** re-run the E8/§27 item 45 check when Evidence lands — ResearchProgram,
   ActionEvaluation, Graph Fabric, and LLM proposals must never acquire evidence-promotion
   authority; add the permanent-rule regression.
5. **CandidateAction schema hardening (P3):** closed-schema check for dimension keys
   (EC-V6-05), dedup decision (EC-V6-04), structured typed-violation error (EC-V6-06).
6. **Immutability boundary statement (EC-V6-07):** decide whether DB-level triggers are
   required or API-level structural immutability is the documented boundary.
7. **Governance-at-validator question:** whether the validator should ever receive the frozen
   brief's hash as a checked input (removing the §28.2 "rejected at validator" inconsistency),
   or §28.2 should be reworded (EC-V6-08).
8. **Re-baseline at Step 4's HEAD:** fresh 374-test run (or corrected count) must be recorded
   before the next adversarial round; re-run A1–A6 against any repository changes first.

---

## O. Compliance Notes

- No release/ratification verdict issued (per §18): the report stops at findings for the next
  closure stage (§27 item 43 external gate remains the ratification condition).
- Attack B was not called a runtime failure: it is classified DEFERRED/P3 per v6's honest
  representation (EC-V6-03).
- The current absence of Evidence code was not called a defect: it is an explicitly deferred
  phase boundary with the permanent rule recorded (§12, EC-V6-09f).
- Probe artifacts (reproducible): `%TEMP%/opencode/step3/probe_{a,b,c,d,v,atomic,atomic_p5,f,g}.py`;
  all DB fixtures in-memory; no repository files touched; working tree unchanged by verification.
