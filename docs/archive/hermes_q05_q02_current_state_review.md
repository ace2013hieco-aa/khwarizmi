# Hermes — Q-05 / Q-02 Current-State Review

**Date:** 2026-08-15
**Method:** direct inspection of the CURRENT repository (not prior reports alone); live execution of the test suite and pyright against the current working tree; claims labeled COMMITTED / WORKING-TREE ONLY / DOCUMENTED / INFERRED / UNVERIFIED where it matters.

---

## A. Current HEAD

- **HEAD:** `dc84673` — `hermes status/doctor --json: stable machine-readable probes` (branch `main`, up to date with `origin/main`).
- **The task's stated baseline `d7931ece` IS in history** and is an ancestor of HEAD — HEAD is **57 commits ahead** of it (`git rev-list --count d7931ece..dc84673` = 57).
- Everything the task assumed was "remediation not yet guaranteed present in the remote HEAD" is **COMMITTED**, and substantially more: Q-05 is closed, Q-02 is implemented and ratified, and Q-04 plus the Evidence-Ladder proposal lifecycle have also landed.

Commit chain relevant to this review (oldest → newest, all COMMITTED):

| Hash | What it is |
|---|---|
| `55c35c2` | ResearchSourceProvider step-6 final review (closure pin target) |
| `d7931ec` | Q-05 surviving-ideas stage: IDR-036/037 ratified; Q-02 design gate |
| `92423e1` | Q-05 adversarial remediation: digest corruption observability, resolver immutability proof, governance correction, Q-02 Model-B revision, closure scope pin |
| `3438231` | Q-05 review findings: digest flags for non-list evidence refs + missing content hash |
| `a3c15a4` | Q-05 review record + Q-02 hostile design-gate re-run (six areas) |
| `612ea5d` | **Q-05 CLOSED** — operator accepted the §10 adversarial audit as the closure gate |
| `3f16265` | Q-02 implementation: ActionEvaluation EligibleTask mode + version-bound controller dispatch |
| `27f0504` | Q-02 audit F5: corrupt program rows fail closed |
| `3494124` | Q-02 evaluator v1.1: obligation-fact derivation |
| `b0ebcb0` | Ratify Q-02 EligibleTask ordering policy as IDR-038 |
| `3fb91c6` / `d081c74` / `e838a9c` / `e90e8e4` / `53bc729` | Q-02 evaluator v1.2.0 satisfaction links + audits + recovery determinism proof |
| `642e95c` → `c8d8b03` → `31273d5` (Q-04), `57fb3e9` → `74f320c` (Evidence Ladder / IDR-040/041), `5aef874` (red-team §2/§3), red-team A/B/C series, `73388c4` (F14), `62a9a9d`/`5a063c8`/`86bba35`/`dc84673` (operator-loop audit + CLI JSON probes) | Post-Q-05/Q-02 hardening and expansion |

## B. Working tree status

- `git status`: **clean except one untracked file** — `hermes_q05_independent_review.md` at the repo root. No uncommitted modifications to any tracked file (`git diff` is empty).
- The untracked file is the **independent Q-05 closure review** (external party, Claude, 2026-08-15, against `612ea5d` and live HEAD `dedeec5`). It is **WORKING-TREE ONLY — never committed**.
- The Freebuff/desktop artifacts (`desktop-v2.db*`, `.freebuff/`) are untracked runtime state, not repository content.

## C. Q-05 committed vs uncommitted state

| Item | State |
|---|---|
| Q-05 substrate + taxonomy + action map (IDR-036) | COMMITTED (`d7931ec`+), CLOSED (`612ea5d`) |
| Q-05 persistence slice + digest (IDR-037) | COMMITTED, CLOSED (`612ea5d`) |
| Q-05 adversarial remediation (digest observability, immutability proof, governance correction, Model-B revision, closure pin) | COMMITTED (`92423e1`) |
| Digest stored-fact flags (non-list evidence refs, missing content hash) | COMMITTED (`3438231`) |
| Red-team §2/§3 (contributing-FRAMING_ERROR gate + honest scope-resolver label) — remediates the independent review's two findings | COMMITTED (`5aef874`) |
| Independent review record (`hermes_q05_independent_review.md`) | **WORKING-TREE ONLY (untracked)** |
| IDR-036/037 status text | COMMITTED; still says "INDEPENDENTLY VERIFIED by an external party is not claimed" — **stale now that the review exists and its findings are remediated** (see §F) |

**Conclusion:** the task's opening premise — "remediation changes not yet guaranteed present in the remote HEAD" — is **falsified**. The only uncommitted Q-05 artifact is the independent-review record itself, plus the governance-text upgrades that record warrants. The 993-test figure cited by the remediation report was real at that time; the suite has since grown (see §E).

## D. Q-05 findings (verified directly against the current tree)

### D.1 Digest shape and corruption observability — VERIFIED (COMMITTED)

`src/hermes/persistence/failure_classifications.py` → `classifications_digest(rows)` (pure, read-only) returns exactly:

```
digest_version, integrity_status ("OK" | "FLAGGED" | "DEGRADED"),
count, items, errors
```

- **Deterministic:** rows are sorted by `artifact_id` before processing — no SQL row order, no unordered iteration. `test_deterministic_result_same_state` and `test_pure_deterministic_and_empty` lock byte-identical output for identical input.
- **Valid row → surfaced item** with `permitted_actions` and `requires_human_confirmation` **recomputed from the ratified substrate** (F2 rule — a tampered stored value is flagged, never trusted).
- **Corrupt row → explicit diagnostic, never silently omitted.** Two regimes, both tested:
  - *Dropped with a diagnostic* (row never becomes a recommendation): `WRONG_ARTIFACT_TYPE`, `MALFORMED_METADATA`, `FORGED_IDENTITY`, `MISSING_CLASSIFICATION_ID`, `MISSING_REQUIRED_METADATA`, `INVALID_FAILURE_CLASS`.
  - *Surfaced with recomputed values + integrity flag*: `MALFORMED_PERMITTED_ACTIONS`, `STORED_ACTIONS_MISMATCH`, `STORED_CONFIRMATION_MISMATCH`, plus the post-independent-review additions `MALFORMED_EVIDENCE_REFS` (F3) and `MISSING_CONTENT_HASH` (F4).
- **All nine diagnostic codes required by the task exist and are fixture-tested** (`TestDigestCorruptionObservable`, `TestF2DerivedFieldsRecomputed`, `TestDigestStoredFactIntegrity`, `TestAuditRemediations`).
- **Mixed state:** `test_mixed_valid_and_corrupt_rows` — 1 valid + 1 corrupt ⇒ `count == 1`, the valid item surfaced, the corrupt row in `errors`, `integrity_status == "DEGRADED"`. The same holds for the N-valid + 1-corrupt case by construction of the pure loop.
- **Controller is not failed by a bad advisory row:** `Controller.classification_proposals()` is read-only consumption (tested: zero artifacts/edges/events written, task status untouched); the digest surfaces the corruption instead of failing the tick.
- `digest_version = "2"` (COMMITTED).

### D.2 Resolver snapshot / immutability proof — VERIFIED (COMMITTED)

The pre-transaction-resolution claim (Option A) holds as a **structural fact**:

- **`research_programs`:** no `UPDATE`/`DELETE` statement exists anywhere in `src/` (grep-verified). `ResearchProgramRepository.record` is insert/read-only; supersession creates a NEW row (`supersedes_ref`); historical rows are byte-immutable. `test_program_target_frozen_across_supersession` proves v1 row bytes and the recorded classification are identical before/after v2 supersession, and that a fresh classification can still cite the superseded v1.
- **`scope_briefs`:** not only no `UPDATE`/`DELETE` — **no production write path of any kind** (`INSERT INTO scope_briefs` exists only in test fixtures). `frozen_at NOT NULL` in the schema. A frozen brief cannot change because nothing in `src` can write the table (this is stronger than the documented claim; it is also why the FRAMING_ERROR scope resolver is labeled DEFERRED — fail closed, IDR-037 D5).
- **Required fail-closed tests all exist:** stale/foreign program ref → `FailureClassificationError`, nothing persisted (`test_stale_program_ref_fails_closed`); foreign brief + same-project brief lacking the cited field → refused (`test_stale_brief_ref_fails_closed`).
- **Conclusion: IMMUTABILITY VERIFIED.** The TOCTOU window is closed because the class-specific citation targets (`research_program:`, `scope_brief:`) are append-only content-addressed rows; the mutable parts (task binding, evidence ownership, one-shot identity) are re-verified INSIDE the `BEGIN IMMEDIATE` write transaction (D4, V6-P7-A2-02 precedent).
- The independent review independently re-verified the same fact by direct grep (its §7).

### D.3 Governance-status honesty — VERIFIED, one correction pending

- IDR-036 and IDR-037 both carry: **IMPLEMENTED + TESTED — RATIFIED / CLOSED (2026-08-15)** with the explicit line *"closure is by operator authority; INDEPENDENTLY VERIFIED by an external party is not claimed."* That is the correct, honest vocabulary — it does **not** collapse OPERATOR-ADOPTED into INDEPENDENTLY VERIFIED. COMMITTED and accurate for the committed record.
- **Pending correction:** an independent review HAS since been performed (`hermes_q05_independent_review.md`, WORKING-TREE ONLY) and PASSED with one MEDIUM + one LOW finding, both subsequently remediated and regression-locked in committed history (`5aef874`). Once that review record is committed, the honest status becomes **IMPLEMENTED + TESTED / INDEPENDENTLY REVIEWED (2026-08-15, external party) / findings remediated / CLOSED** — the IDR status lines and README index entries should be upgraded at that point. This review does NOT claim the upgrade before the record is committed; it flags the stale text (see §N).
- The README's **top Status line and the Build-plan "Phase 0 — YOU ARE HERE" marker are stale** — they describe the v6 P3 era and do not reflect Q-05/Q-02/Q-04, the Evidence-Ladder proposal lifecycle, the operator loop, or the CLI. COMMITTED but DOCUMENTED-STALE (see §N).

### D.4 Action-map semantics — VERIFIED (COMMITTED)

- `PermittedAction` docstring: *"Hermes-native **proposal categories** — never executed by this module. The vocabulary deliberately contains no creation/mutation actions."* Authority is enforced by absence of capability (the module imports no SQL/repository/gateway) — a structural guarantee, not a convention.
- `REVIEW_DOWNSTREAM_IMPACT` is documented as a *review obligation* — it does not imply a dependency/impact engine exists (the Q-04 traversal is read-only reachability over existing edges); `PROPOSE_MECHANISM_SUBSTITUTION` requires the existing Director `PROPOSE_RESEARCH_PROGRAM` gateway path — AC-5 reachable only through the per-action human gate, never an auto-creator. Consistent with code.
- LLM boundary (task §9): LLM may propose; deterministic code decides validity/citations/identity/action-map/permissions/versioning/serialization — the substrate's `classify_failure` returns `ADMITTED`/`REJECTED` from pure validation; the write path re-runs the substrate with real resolvers (D1, EC-V6) and never trusts a caller-supplied `claimed` classification.

### D.5 Taxonomy preservation — VERIFIED (COMMITTED)

- Six classes: `DECLARED_CONSTRAINT_VIOLATION`, `IMPLEMENTATION_FAILURE`, `ENVIRONMENT_MISMATCH`, `RESOURCE_CONSTRAINT`, `FRAMING_ERROR`, `UNKNOWN`. **No `HARD_AXIOM_VIOLATION`** (renamed — Hermes has no axiom carrier), **no `MULTI_FACTOR`** (exactly-one primary + optional contributing factors; `UNKNOWN` remains legitimate). Matches the architecture §9 requirements exactly.

### D.6 Derived-artifact taxonomy gap — DOCUMENTED ONLY (per design)

Existing `artifact_type` values in `src` (grep-verified): `dataset_manifest`, `source_result`, `source_payload`, `failure_classification` (advisory; D8-refused as evidence), plus the form-checked deferred carriers `task_evidence`/`task_output` and the closed fail-closed rule for unknown types (`repositories.py._dereference_artifact_ref`). The raw-source / source-result-metadata / advisory-analysis / decision / execution distinction is **not** formalized — a future generic derived-artifact policy (OBSERVATION / DERIVED_ANALYSIS / PROPOSAL / DECISION / EXECUTION) is a design note only, per the task §11/§28. No new taxonomy implemented.

### D.7 Authority vocabulary — DOCUMENTED ONLY (per design)

Q-05 is documented as advisory metadata (D8); Q-02 Model B is documented as **deterministic controller control policy** (IDR-038, design §3: "Q-02 is NOT merely advisory"). The richer vocabulary (DESCRIPTIVE / ADVISORY / PROPOSAL-GENERATING / CONTROL-POLICY / AUTHORITATIVE / EXECUTING) is not introduced as a subsystem — it is terminology clarity already partially present in the docs (§12 satisfied without new machinery).

## E. Q-05 remediation results (live, current working tree)

- **`pytest` (full suite): 1306 passed, 0 failed** — run fresh on 2026-08-15 against HEAD `dc84673`. The remediation report's 993 was accurate at the `d7931ec`/`92423e1` era; the independent review measured 1154 at `dedeec5`; IDR-041 records 1258 at `1d1d493`; the suite has grown with each post-closure commit.
- **`uvx pyright src`: 0 errors, 0 warnings.**
- Q-05-specific: `tests/test_failure_classification.py` + `tests/test_q05_persistence.py` (95 collected at the independent review; more since) — all pass.

## F. Q-05 independent-review status

| Aspect | State |
|---|---|
| Review performed | YES — external party (Claude), 2026-08-15, against `612ea5d` and live HEAD `dedeec5`, with a fresh adversarial probe outside the existing matrix |
| Verdict | PASS, with one MEDIUM (§4: contributing `FRAMING_ERROR` did not trigger the human-confirmation gate or citation discipline) + one LOW (§7: IDR-037 D5 scope-resolver labeling) |
| §4 MEDIUM remediation | COMMITTED — `5aef874` (red-team §2: `requires_human_confirmation_for` now fires on FRAMING_ERROR ∈ {primary} ∪ contributing_factors; regression-locked in the digest + substrate tests) |
| §5-LOW remediation | COMMITTED — `5aef874` (red-team §3: IDR-037 D5 now labels the scope resolver DEFERRED — fail closed, mirroring the regime resolver) |
| Review record | **WORKING-TREE ONLY — not yet committed** |
| Committed IDR status text | Still "INDEPENDENTLY VERIFIED … is not claimed" — accurate for the committed record, **stale as a description of reality** |

**Honest status today:** IMPLEMENTED + TESTED → ARCHITECTURE ADOPTED BY OPERATOR (CLOSED 2026-08-15) → INDEPENDENTLY REVIEWED (2026-08-15) with both findings remediated and regression-locked. The IDR/README status lines should be upgraded to "INDEPENDENTLY REVIEWED — findings remediated, CLOSED" **in the same commit that records the review** (see §O).

## G. Q-02 design status

- **NOT design-only.** Q-02 is **IMPLEMENTED + TESTED + RATIFIED** as IDR-038 (2026-08-15): ActionEvaluation **EligibleTask mode** as a versioned deterministic controller policy (Model B). The design doc `hermes_q02_epistemic_roi_design.md` carries the "DESIGN READY FOR IMPLEMENTATION" gate at §17 and the implementation record §16.1–16.4 (v1.1 obligation-fact derivation; v1.2 per-requirement satisfaction links; audit II F6/F8).
- The task's §22 implementation gate is fully satisfied and **exceeded** (Model B documented; ActionEvaluation reuse explicit; precedence explicit; deterministic proxies explicit; LLM quarantine explicit; versioning explicit; recovery semantics explicit; acceptance tests written AND passing; no second scheduler).
- Architecture-preservation check (§13/§14): no scalar ROI, no ROI scheduler, no weighted utility scoring, no LLM scheduler. `evaluate_eligible_tasks` is a pure function in `evaluation.py` (the existing ActionEvaluation module — same `DimensionLevel`/`CostTier`/lexicographic-policy/basis_refs/version-triple vocabulary), and the controller consumes it at dispatch. `test_evaluation_never_imports_the_controller` pins the import direction.
- Version triple: `evaluator_version = 1.2.0`, `policy_version = task-eval-2026.1`, `schema_version = 1`. Every dispatch records `ordering_policy_version` on the `TickResult`.

## H. Q-02 precedence model (exact, as ratified)

The design's §11 defines the precedence; the code implements it:

```
HARD ELIGIBILITY (status ∈ PENDING/READY/RETRYING AND all deps SUCCEEDED —
                   _discover_eligible, SQL pre-filter; re-validated atomically
                   at claim, F-10)
  >
GATE / HUMAN_GATE / per-tick cap (GATE verdict gates the wave; HUMAN_GATE parks
   at WAITING_HUMAN and stops the wave; project mode AWAITING_HUMAN blocks all
   dispatch; max_calls_per_tick is checked before claim — a capped task is
   never stranded RUNNING)
  >
RATIFIED DIRECTOR PRIORITY — MECHANISM DEFERRED (no priority column exists;
   test_no_priority_mechanism_exists asserts its absence; the precedence slot
   is pinned at design level only)
  >
Q-02 EPISTEMIC ORDERING (lexicographic: evidence_gap_closure,
   contradiction_reduction, rival_discrimination, replication_value,
   frontier_value, coverage → cost LOW-first/UNKNOWN-last → created_at
   earliest-first → task_ref) — applied ONLY to the already-eligible set
  >
created_at → task_id  (final deterministic tie-break; also the SQL ORDER BY
   baseline when ordering is disabled)
```

Notes that differ from the task's *example* chain:
- **"Budget" is not a subsystem.** There is no budget authority in the code; the resource floor is the per-tick call cap (`max_calls_per_tick`), tested as the budget-boundary invariant (`test_ordering_cannot_squeeze_past_the_call_cap`).
- **Director priority does not exist as a mechanism** — the precedence slot is reserved and documented, the mechanism deferred. This is explicit and tested, not implicit.
- HUMAN_GATE is enforced at the mode/wave level, which Q-02 cannot bypass regardless of ordering.

## I. Q-02 acceptance tests (map to the required A–J)

All in `tests/test_q02_eligible_ordering.py` (pure) and `tests/test_controller_q02.py` (controller), all passing at HEAD:

| Required | Test(s) |
|---|---|
| A — eligible vs eligible | `test_low_cost_eligible_task_dispatches_first`, `test_linked_task_with_unmet_obligations_orders_first`, `test_high_evidence_gap_dimension_orders_first` |
| B — dependency invariant | `test_dependency_blocked_task_is_never_ordered_or_dispatched` |
| C — gate invariant | `test_task_awaiting_a_failed_gate_is_never_ordered` + HUMAN_GATE wave-stop `test_8_human_gate_parks_wave_stops_and_resumes` |
| D — budget invariant | `test_ordering_cannot_squeeze_past_the_call_cap` (per-tick cap; no budget subsystem — documented) |
| E — Director precedence | `test_no_priority_mechanism_exists` (mechanism deferred, precedence pinned at design level) |
| F — determinism | `test_same_inputs_same_ranking_identity`, `test_ordering_is_total`, `test_ordering_deterministic_as_satisfactions_grow_across_ticks` |
| G — provenance | `test_basis_refs_round_trip_into_the_ranking`, `test_program_refs_carried_as_basis_and_sorted`, `test_forged_or_malformed_provenance_is_never_an_ordering_input` |
| H — policy versioning | `test_version_triple_changes_identity`; dispatch records `ordering_policy_version` |
| I — disabled mode | `test_disabled_ordering_dispenses_baseline_created_at_order` |
| J — tie handling | `test_equal_policy_falls_back_to_created_at_then_task_id`, `test_tie_break_is_not_clock_or_process_order` |
| Recovery (task §20) | `test_ordering_survives_crash_recovery_unperturbed` — ordering is **recomputed on recovery** (computed at discovery, never persisted, re-derived deterministically from stored facts + policy version); recovery/requeue paths themselves are untouched by Q-02 |
| LLM quarantine (task §16/§17) | `test_llm_supplied_spec_fields_cannot_enter_the_ordering` (a hostile `roi_score`/`information_gain` spec field is invisible to the policy); the forbidden chain `LLM → "high ROI" → hidden scheduler → execution priority` is structurally impossible (design §8) |
| Information value ≠ truth (task §18) | Design §17 note: "Information gain is not truth… every dimension is an expected-value proxy about running the action, never a belief about correctness" — documented; no credence is produced by the policy |

## J. ResearchSourceProvider closure scope

- `hermes_researchsourceprovider_closure_gate_package.md` is **pinned to `55c35c2`** with explicit §A1 scope-pinning language: *"A verification recorded at `55c35c2` is NOT a verification of `d7931ec` (or later)"* and *"If the gate is rerun at a new HEAD, a NEW closure-gate package must be created pinned to that HEAD."* VERIFIED — the historical closure record is not falsely upgraded, and no status page equates the `55c35c2` verification with current-HEAD verification.
- Current slice status (per the package and README IDR entries): steps 1–6 of 7 IMPLEMENTED + TESTED; step 7 (record/replay acceptance run) pending; NOT RATIFIED-as-implemented; EXTERNALLY VERIFIED unclaimed.

## K. Ix status

- `docs/ix/` holds structural-observatory reports (smells, importer/dependent ranks, step-6 structural comparisons), last generated **2026-08-14** — before Q-05/Q-02/Q-04/red-team work. They are COMMITTED but **stale relative to current HEAD**.
- Ix remains a **structural observatory, not a correctness authority** — no module was deleted on Ix's say-so; deferred modules are preserved intentionally. A fresh Ix run at `dc84673` is a recommended hygiene step (§O).

## L. Diagram-design status

- `cathrynlavery/diagram-design` remains an external engineering/documentation skill / methodology-harvest candidate. Grep-verified: **no `DiagramService` / `DiagramAuthority` / `DiagramDB` / `DiagramScheduler` and no diagram dependency in `src/`.** Diagrams remain projections; no runtime integration exists — candidate status preserved.

## M. Surviving-ideas roadmap (actual, verified)

| Capability | Prompt's intended status | ACTUAL repo status (COMMITTED) |
|---|---|---|
| Q-05 failure classification | IMPLEMENTED + TESTED; review pending | IMPLEMENTED + TESTED, **CLOSED** (IDR-036/037, `612ea5d`); independently reviewed with findings remediated (`5aef874`); review record uncommitted |
| Q-02 epistemic ordering | DESIGN ONLY | **IMPLEMENTED + TESTED + RATIFIED** (IDR-038, evaluator 1.2.0) — ahead of the prompt's assumption |
| Q-09 MECE | NOT STARTED | NOT STARTED — no code, no design |
| Q-04 dependency/failure graph | NOT STARTED | **IMPLEMENTED + TESTED + RATIFIED** (IDR-039/040) — ahead of the prompt's assumption |
| Q-07 Zwicky | NOT STARTED | NOT STARTED (framework disposition EXPERIMENTAL) |
| CV-01 convergence | NOT STARTED | NOT STARTED (framework disposition EXPERIMENTAL, 3 of 5 levels) |
| TRIZ | DEFERRED | DEFERRED — abstract contradiction pattern folded into Q-05 IMPLEMENTATION_FAILURE as a prompt technique only; no TRIZ code |
| Obsidian | DEFERRED | DEFERRED — no code |
| 4S architecture layer | REJECTED | REJECTED as a persisted layer; design lens only — no code |

**No forbidden architecture was introduced** (grep-verified): no second scheduler, no second evidence authority, no second provenance system, no second state machine, no second graph database, no automatic hypothesis generation, no automatic pivoting, no diagram/Obsidian/TRIZ/4S subsystem.

## N. Remaining gaps

1. **Independent-review record uncommitted** — `hermes_q05_independent_review.md` is the only uncommitted Q-05 artifact; the IDR-036/037 status lines and README index entries still read "INDEPENDENTLY VERIFIED … is not claimed," which is now stale as a description of reality.
2. **README top Status line + Build-plan "Phase 0 — YOU ARE HERE" marker are stale** — they predate Q-05/Q-02/Q-04, the Evidence-Ladder proposal lifecycle, the operator loop, and the CLI (`hermes audit/status/doctor --json`).
3. **Ix reports stale** (last run 2026-08-14, pre-Q-05/Q-02/Q-04/red-team).
4. **Research Operating System loop (§27) is not yet documented as a conceptual roadmap anywhere.** The links already exist in code — ResearchProgram → task graph → execution → evidence/REFUTED → Q-05 ("why?") → Q-04 blast-radius candidates ("what is affected?") → ActionEvaluation → Q-02 ("what next?") → Controller → task graph again — but no document ties the loop together. Documentation-only gap; do not fill missing links with speculative architecture.
5. **Derived-artifact taxonomy and authority vocabulary** are documented as future design questions only (§D.6/D.7) — intentionally unimplemented.
6. **Budget authority does not exist** — the per-tick call cap is the resource floor; a real budget subsystem is not part of the architecture and should not be invented here.
7. Evidence Ladder's full ladder-table REFUTED write path (D3 ref) remains future; the currently shipped path is the bare-classification driver (AC-2) plus the APPLY executor — the "Evidence Ladder remains deferred; Q-05 persistence landed early as preparatory infrastructure" sequencing record (`hermes_q05_post_adversarial_remediation.md` finding 4, IDR-037) is honest and unchanged.

## O. Recommended next step

1. **Commit the narrow Q-05 governance set** (the task §29 commit, minus Q-02 — Q-02 is already committed and ratified separately): `hermes_q05_independent_review.md` + the IDR-036/037 status upgrades ("IMPLEMENTED + TESTED / INDEPENDENTLY REVIEWED (2026-08-15, external party) / findings remediated / CLOSED") + the README status-line and IDR-index corrections + this review document. This is the single uncommitted, well-scoped follow-up.
2. Then a hygiene pass: refresh `docs/ix/` at `dc84673` and (optionally) write the §27 Research-Operating-System conceptual-loop note as documentation.
3. Then, per the roadmap, the sequence is Q-09 → Q-04 extension → Q-07 → CV-01 — none of which are started, and none of which should be started by this task's stop condition.

**Stop condition honored:** no Q-09/Q-04/Q-07/CV-01/TRIZ/Obsidian/4S work was performed; Q-02 was not re-implemented (it is already ratified); no surviving-ideas program-wide ratification claim is made; nothing was committed.
