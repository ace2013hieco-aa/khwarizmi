# IDR-045 Audit 5 — Adversarial (read-only)

Branch: `idr-045/audit5` from `main@c2c8fa9`. Inputs: (1) `IDR-045-plan-admission-and-intent-provenance.md` (draft v1.1, untracked, `Status: Proposed. Not ratified`), (2) Q-evidence `idr-045/qpass-narrow@e077898:docs/IDR45-Q37-evidence.md`, (3) ratification `D1-A, D2-A, Q1=plan-once, Q7=keyed-otherwise`, (4) live tree `main@c2c8fa9`. One write: this file. No `src/`/`tests/`/`config` edit, no push.

## Verdict: PASS WITH CONDITIONS

D1 plan-once and D2 additive-fields are jointly adoptable as specified, but the draft as written does not implement the ratified Q7 semantics. Six conditions (C1–C6) must be fixed in the implementation prompt before code is written. No finding is confirmation-only; every claim cites `file:line` and was re-read on `main`.

---

## 1 — D1: plan-once + keyed-otherwise

### 1.1 B3C-child-head — constructed case

Live head selection is unfiltered max-version:

- `src/hermes/persistence/repositories.py:1700-1706` `current(project_id)` → `SELECT … WHERE project_id=? ORDER BY version DESC LIMIT 1`
- `src/hermes/research/completion.py:104-114` `_current_program` — identical query
- `src/hermes/research/controller.py:2851-2858` `_program_head_id` — maximises `version` then `program_id`, same selection
- `src/hermes/research/controller.py:3524-3528,3661-3666` — same `ORDER BY version DESC LIMIT 1` for ladder

Parallel-regime-test child insertion:

- `src/hermes/persistence/repositories.py:1600-1616` — when `program.parent_program_id is not None`, `version = (head["v"] or 0) + 1` (`:1616`); comment `:1612-1614` "parallel-regime-test programs get the next version number (v=max+1) — they run alongside, not as replacements, but the UNIQUE(project_id, version) constraint requires a fresh slot." Migration `src/hermes/persistence/migrations.py:1158-1185` (18→19) adds advisory `parent_program_id/target_regime` with no filter on `current()`.

Therefore a B3C child **becomes head** on the live tree. Q-evidence `e077898:docs/IDR45-Q37-evidence.md:Q7` proves this with the same lines.

**Falsification attempt:** Draft D1 §3.1 defines eligibility as "the project's head program exists, is compiled and parseable; the plan for that program is not already fully admitted." The draft never qualifies head with `WHERE parent_program_id IS NULL`. Ratification `Q7=keyed-otherwise` requires eligibility keyed by `MAX(version) WHERE parent_program_id IS NULL` (filtered head), leaving B3C sideways. The draft text and the ratified semantics diverge. An implementer following §3.1 literally reproduces **replace-head** (B3C steals head, `build_task_plan(current)` at `src/hermes/research/task_plan.py:110-120` re-targets to the child, losing `task_plan.py:100-107` `_identity(program_id,…)` idempotence for the primary chain).

**Condition C1 (blocking):** Implementation prompt must define eligibility as filtered head (`SELECT MAX(version) FROM research_programs WHERE project_id=? AND parent_program_id IS NULL`), not `current()`. Either add `ResearchProgramRepository.current_primary(project_id)` or inline the filtered query. Add a test that constructs the B3C case (ADMIT parent program, emit one `EMIT_PARALLEL_REGIME_PROGRAM` child, assert second `tick()` does **not** admit a new primary plan and `task_ids` still equal `plan.task_ids` of the primary program).

### 1.2 Revised-program — constructed case

Plan identity is content-addressed on `program_id`:

- `src/hermes/research/task_plan.py:100-107` `_identity(program_id, role, ref)` + `:137` `task_id="rp-{pid_short}-gate-{slug}"` + `:178` `rp-{pid_short}-ev-{i:02d}-{slug}`
- Supersession forces new content: `src/hermes/persistence/repositories.py:1581-1598` head-only check + `:1592-1596` "supersession must change program content"
- A new head therefore yields disjoint `task_ids`.

Live behaviour for old tasks: nothing retires them. Pattern `supersession|supersede` over `src/hermes/research/task_plan.py` and admission path returns only claim/assumption and contradiction logic, never tasks — confirmed in `reports/repo-state-audit-5-2026-09-29.md:541-542` Q1. There is no plan-admission pass at all on `main` (`rg plan_to_payloads|build_task_plan` in `src/hermes/research/controller.py` → 0 hits), so the situation cannot yet arise, but the design must decide.

Draft §2 lists "Program supersession behavior for already-admitted plans (Section 6, Q1)" as out of scope; §6 Q1 is `UNVERIFIED`; ratification asserts `Q1=plan-once` (admit new plan alongside old, leave old rows, observable no-op for already-admitted primary plan, not silent skip). The §3.6 test plan has no case for "superseding program admits second DAG while first remains."

**Condition C2 (blocking):** Implementation prompt must state: supersession leaves old tasks in place (no DELETE — there is none in `src/` beyond `scheduler_lock` at `src/hermes/persistence/database.py:159` + `src/hermes/research/controller.py:2381`); second admission emits new `task_ids` via same `plan_to_payloads` path; a tick where primary plan already fully admitted is an **observable no-op** (no new `TaskCreated`/`IntentApplied` rows, idempotent `ADMIT_TASK` returns `duplicate=True` at `src/hermes/research/gateway.py:3906-3917`, not a silent exception). Add test: compile v1, admit plan, compile v2 superseding v1, tick admits v2 plan, assert old `task_ids` still present and new `task_ids` disjoint, and a third tick is a no-op (zero new `TaskCreated`).

### 1.3 Plan-once idempotence / crash-resume / ordering

- `src/hermes/research/gateway.py:3906-3917` — `ADMIT_TASK` idempotent on `task_id` (`TaskRepository.get` then `create`); `src/hermes/research/task_plan.py:84-93` `ordered` (leading gates, evidence, trailing `pre_live`) + `gateway.py:3890-3899` missing-dep rejection ensures prefix-closed admission. P2/P3 hold **iff** the pass iterates `plan.ordered` and calls `apply_intent` per payload. No other `INSERT INTO tasks` site exists (`src/hermes/persistence/repositories.py:408` is the sole writer per `IDR-045 §3.2 P1`).

No falsification found beyond C1/C2, but §3.6 test 3 "admit k of n payloads, then re-tick" requires the pass to be non-atomic by design (each `apply_intent` is its own transaction at `gateway.py:4057-4064`). A mid-plan crash leaves k rows; re-tick must complete to n. This is testable, but the pass must not wrap the loop in a single transaction.

---

## 2 — D2: additive fields

### 2.1 Single builder — re-verified

Direct reading (not grep shortcut):

- Sole builder `src/hermes/research/gateway.py:4085-4090` in `_append_audit_event:4068-4100` (`"intent_kind": kind_label, "proposed_by": …, "project_id": …, "justification": …`), invoked at `:4058, :4061, :4064`.
- `rg '"intent_kind"' src/ tests/` → 1 builder + 5 readers/filters (`tests/test_gateway.py:462,799,815,823`, `tests/test_walking_skeleton.py:205`) — the draft's §4.3 "5 payload builders" counts readers, not builders. Q-evidence `e077898` corrects this; audit 5 reproduces it on `main`.
- No test asserts exact 4-key mapping: `rg 'set\(payload\)|payload==\{' tests/` over IntentApplied payloads → 0 hits. Only unrelated payloads assert exact keys (`tests/test_c1_slot_ref.py:286`, `tests/test_extraction_pipeline.py:154`, etc.), as reported at `reports/repo-state-audit-5-2026-09-29.md:547-548` Q3. Confirmed: **no breaking exact-mapping assertion exists**.

The risk table's row "Existing tests asserting an exact 4-key payload (Q3)" is therefore vacuous — the risk does not exist. This does not invalidate D2; it means the "only when non-default" rule is sufficient but not load-bearing for test breakage on `main`.

### 2.2 V1–V5 enforceability

| V | Claim | Live code | Enforceable? |
|---|-------|-----------|--------------|
| V1 | Provenance never authority; role gate reads `proposed_by` only | `src/hermes/research/gateway.py:151-189` `_require_role` reads only `AgentProfile(intent.proposed_by)` + `IntentKind.{director_only,internal_only,llm_proposable}` at `src/hermes/core/intents.py:124-154`; new fields are on `Intent` at `:166-174` (`kind, proposed_by, project_id, payload, justification` only today). No gateway read of any `origin_*` field can occur until D2 adds it — but draft provides no grep-guard or structural test forbidding it. | **Policy, not code.** Condition C3: add structural test that `rg origin_kind\|origin_ref\|model_ref\|run_id\|prompt_template` over `src/hermes/research/gateway.py` returns 0 reads in role/authorization path (allow only audit payload builder). |
| V2 | Additive defaults; 10 `Intent(` in `src/` + 175 in `tests` stay valid | `src/hermes/core/intents.py:167-174` frozen dataclass with defaults; `rg 'Intent\(' src/ --count` → 10 sites (all `controller.py`), `tests/` → 175 (audit-4 §6.3). | Holds if new fields have defaults (`None`/`""`). |
| V3 | Pre-existing rows never backfilled; missing keys = "origin unrecorded" | Readers must use `.get()` with default. Draft states this but provides no reader contract. | Holds only if projector treats absence as unrecorded, not as error. Condition C4: specify reader default. |
| V4 | 4 KiB cap + secret scan | `src/hermes/persistence/event_validation.py:74-84` `validate_payload_size` (4096) + `:87-137` `validate_no_secrets` (recursive, ADV-03). Gateway audit path delegates to `EventRepository.append_transactional` at `gateway.py:4092-4100`, which validates via `repositories.py:_append_event_to_db`. However **no per-field length limit is stated** in §4.1 (it lists fields but not bounds). Without bounds, one `origin_ref` or `model_ref` string could push `payload_json` over 4096. Test §4.6.3 "Oversized field values are refused" is **untestable as specified**. | Condition C5: define max lengths (e.g. `origin_kind ∈ {deterministic,llm}` 13 chars, `origin_ref` ≤64, `model_ref` ≤128, `run_id` ≤64, `prompt_template_version`/`charter_version` ≤32) and enforce in `Intent` constructor or `_append_audit_event` before `validate_payload_size`, with `RATIONALE` or `MALFORMED_PAYLOAD` rejection. |
| V5 | Not duplicative of `produced_by`/`caused_by` | `reports/repo-state-audit-5-2026-09-29.md:544-545` Q2: 73 hits of `produced_by|caused_by` over `src/hermes/research/*.py` are labels on rows/events (e.g. `gateway.py:438,678` `produced_by=intent.proposed_by`, `source_handlers.py:477,504`, `controller.py:529,1379-1405`), not on `Intent`. `intents.py:167-174` has neither. | Verified: not duplicative. Draft's §6 Q2 `UNVERIFIED` is now verified; implementation should close it. |

### 2.3 Machine-readable / hash impact

`src/hermes/persistence/repositories.py:1704` etc. have no intent hash and no event schema version on `IntentApplied` today (`reports/repo-state-audit-5…§6.2`). Adding optional fields with defaults and omitting defaults from payload keeps prior rows' `payload_json` byte-identical and requires no migration — confirmed by the single builder being a plain dict literal at `gateway.py:4085-4090`.

---

## 3 — Five follow-ons: genuinely out of scope?

Draft §2 lists 5 deferred records plus Q1 supersession; §7 re-lists 5 plus trace. Check each for hidden D1/D2 dependency:

| Deferred record | Hidden dep on D1/D2? | Evidence |
|---|---|---|
| Run envelope (task/depth/time/cost caps, gate vs separate record, gateway fan-out) | **Partial hidden dep exists.** Plan size = `|gate_tasks|+|evidence_tasks|` unbounded by program content (`task_plan.py:136-204`; `evidence_tasks` one per `evidence_requirement`). D1 admitting 100-requirement plan emits 100+ `ADMIT_TASK` intents in one tick, each its own `apply_intent` transaction. No tick-level bound or fan-out check exists on `main` (`controller.py:486-603` `tick()` has `max_calls_per_tick` only for dispatch, not admission). §3.4 "To revisit: once envelope exists, pass is natural enforcement point" acknowledges the seam but defers the bound. Without an interim bound, D1 is correct but not robust under load. | `task_plan.py:177`, `gateway.py:4044-4048` dispatch, `controller.py:393-400` constructor |
| Lease horizon per task (`NodeContract.timeout` never read; refresher 300 s) | No hidden dep for admission — lease is `scheduler_lock` at `controller.py:494,2336-2381`, not per-task (`controller.py:267,425`). | `reports/repo-state-audit-5:281-284` |
| FAILED-dependent stall (dependents of FAILED blocked; no FAILED→CANCELLED driver) | **No hidden dep for admission**, but observable consequence: if hypothesis gate resolves REJECTED (`controller.py:1246-1410`), downstream evidence tasks remain `PENDING` with unsatisfied deps forever. Draft §3.4 claim "hypothesis gate remains first human stop; evidence tasks cannot dispatch before it passes (F-10 at `repositories.py:556-579`)" is true, but REJECTED case is permanent block — correctly marked as open, no silent absorption. | `repositories.py:556-579`, `graph.py:40-75`, `tests/test_controller.py:419` |
| REPORTING→COMPLETED driver (`can_complete_research` guard, no production driver) | No hidden dep for D1/D2 — plan admission and provenance do not require lifecycle driver. Draft §5 correctly notes `pre_live` gating via dependencies (`task_plan.py:206-208,174-176`) suffices for ordering; completion driver is separate. | `src/hermes/research/completion.py:96-101`, `repositories.py:241-242` |
| Reasoning-trace artifacts (4 KiB cap, content-addressed) | No hidden dep — events capped at `event_validation.py:23` 4096, trace must be artifact-ref per draft. D2's `justification` stays authority record, not trace dump. | `event_validation.py:23,74-110` |
| Q1 supersession (already covered in §1.2) | Boundary confusion, not hidden dep. Draft lists it both as deferred (§2 last bullet) and as UNVERIFIED (§6 Q1) while ratifying `Q1=plan-once`. Implementation must treat Q1 as **decided** (C2), not deferred. | Draft §2 vs §6 Q1 vs ratification |

**Finding:** 4 of 5 follow-ons plus trace are cleanly severable. The envelope is the only partially-hidden coupling: D1's correctness does not require it, but D1's liveness under adversarial program size does. Mark as open condition, not silent absorption — draft does mark it, but implementation prompt should add an interim per-tick admission cap or program-size check.

---

## 4 — Test plan sufficiency (§3.6 / §4.6)

### §3.6 (D1, 8 tests)

| # | Spec | Testable? |
|---|------|-----------|
| 1 | Controller-driven full DAG via `tick()`; readiness = first gate | Yes. |
| 2 | Idempotence (second/third tick no rows/events) | Yes — assert `TaskCreated`/`IntentApplied` counts stable (ADMIT_TASK `duplicate=True` at `gateway.py:3906-3917`). |
| 3 | Crash-resume k-of-n then re-tick equals clean | **Testable but underspecified.** Requires injecting k by calling `apply_intent` k times outside `tick()`, then invoking pass. Draft does not state that the pass must be non-atomic (it must not wrap loop in one transaction). Condition C6: specify per-payload `apply_intent` loop, not bulk transaction. |
| 4 | Role: `ADMIT_TASK` with `DETERMINISTIC` only; RESEARCHER still refused | Yes — existing `tests/test_gateway.py:173-178` covers `_require_role`. |
| 5 | Structural: no repository-write import | Yes — pattern `TaskRepository.*create|INSERT INTO tasks` over pass module; analogue `tests/test_v6_attacks.py:164-167` purity probe exists. |
| 6 | Uncompiled program → no-op, no exception | Yes — `task_plan.py:116-119` raises `ValueError` for missing `program_id`; pass must catch and no-op (observable: zero new rows, `tick()` not failed). |
| 7 | Non-ACTIVE mode admits nothing | Yes — `controller.py:516-559` idle when non-ACTIVE. |
| 8 | Regression walking skeleton still passes | Yes — `INSERT_TASK` path unchanged (`gateway.py:4044-4048`). |

### §4.6 (D2, 5 tests)

| # | Spec | Testable? |
|---|------|-----------|
| 1 | Default leaves `IntentApplied` payload byte-identical | Yes — with C5 bounds and "only when non-default" omission. |
| 2 | Non-default fields appear with expected keys, pass validation + secret scan | Yes — assert payload contains `origin_kind` etc. and `validate_event` at `event_validation.py:139-151` passes. |
| 3 | Oversized field values refused | **Not testable as specified** — no max lengths in §4.1. Requires C5. |
| 4 | Role gate ignores new fields | Yes — `gateway.py:151-189` unchanged. |
| 5 | DIRECTOR sites keep `proposed_by=DIRECTOR`, add `origin_kind=deterministic`, IDR-041 tests still pass | Yes — `controller.py:1123,1188` sites; must not alter `GatewayRejection` behaviour. Existing `tests/test_gateway.py:170-181` etc. |

---

## 5 — Gaps honestly marked?

| Gap | Draft marking | Honest? |
|-----|---------------|---------|
| Supersession / stale tasks | §2 out-of-scope + §6 Q1 `UNVERIFIED` + §7 follow-on, but ratified `Q1=plan-once` contradicts deferral | **Miscount.** Must be promoted from deferred to decided (C2). |
| Stall (FAILED dependents) | §2 out-of-scope #3, §7 follow-on, §5 lifecycle note | Honest — not absorbed. |
| Lease horizon | §2 out-of-scope #2, §7 follow-on | Honest — not absorbed; no hidden dep (see §3). |
| 10 `Intent(` sites / 5 builders | §4.3 counts 10 in `src/` (all `controller.py`) and "5 payload builders" — actual is 1 builder + 5 readers; 10 `Intent(` in `src/` not re-counted on `main` (this audit found `controller.py:1123,1188` as the two `DIRECTOR` sites, remainder `DETERMINISTIC`) | **Stale count** — correct count is 1 builder; test risk based on it is overstated. Not a silent absorption, just an inaccurate change-surface estimate. |
| IDR numbering (`IDR-SKELETON.md`, Status line) | §6 Q6 `UNVERIFIED` claims IDR-031..041 lack `Status:` — `reports/repo-state-audit-5:556-557` Q6 proves every IDR-030..041 + IDR-044 has `**Status:**` line; IDR-042/043 do not exist, IDR-044 is highest | **Premise false.** Must correct before filing; audit 5 carries this forward as erratum. |

---

## 6 — Errata in draft requiring correction before filing

- **Baseline HEAD:** Draft §5 cites `70f3f71` (a `w6-audit` commit not on `main`); `main` at audit time was `84b9a24` (`reports/repo-state-audit-5:9,40-49`), at this audit still `c2c8fa9`. Update baseline or rebase.
- **Q-evidence path:** Draft references Q-evidence on `idr-045/qpass-narrow` but `reports/repo-state-audit-5` still lists 10 untracked paths without that evidence file — evidence lives on a non-main branch (`e077898:docs/IDR45-Q37-evidence.md`); this audit is on `idr-045/audit5` without that file by design (read-only inputs). File the evidence on `main` or attach as IDR appendix before ratification is consumed.
- **Status line claim:** see §5 last row.

---

## 7 — Required conditions for PASS

- **C1 — Filtered head:** Define filtered head (`parent_program_id IS NULL`) and forbid use of unfiltered `current()` for plan eligibility; add B3C-child-head test.
- **C2 — Supersession decided:** Document leave-in-place + admit-new-DAG + observable no-op; add revised-program test; remove Q1 from deferred list.
- **C3 — V1 structural guard:** Add no-authority-read test for `origin_*` over `gateway.py`.
- **C4 — V3 reader contract:** Specify missing-key = unrecorded, not error; cover in §4.6.1/2.
- **C5 — V4 bounds:** Specify per-field max lengths and secret-scan scope before code; makes §4.6.3 testable and keeps 4 KiB invariant.
- **C6 — Crash-resume atomicity:** Specify per-payload `apply_intent` loop (no outer transaction) for §3.6.3.

With C1–C6 applied, D1 plan-once and D2 additive fields are jointly sound: B3C child is ignored, revised program is an observable extension not a silent mutation, the single builder at `gateway.py:4085-4090` is the only mutation surface, and the five follow-ons remain severable (envelope as bounded liveness follow-on).

---

## 8 — Inputs receipt

- `IDR-045-plan-admission-and-intent-provenance.md` — read from repo root (untracked, 179 lines, `Status: Proposed`).
- `idr-045/qpass-narrow@e077898:docs/IDR45-Q37-evidence.md` — read via `git show` (72 lines, Q3 single-builder + Q7 head-vs-sideways).
- Ratification `D1-A, D2-A, Q1=plan-once, Q7=keyed-otherwise` — taken from prompt header.
- Live tree `main@c2c8fa9` — checked out as `idr-045/audit5` base.

All four present; no STOP condition triggered. No `backtest_audit|SDA|TSE|Optimize-my-strategy` coupling in `src/`/`tests/`/`config` beyond `reports/repo-state-audit-5:162-165` prose boundary statement — reported, not stopped.

## 9 — Provenance (no push)

Branch `idr-045/audit5` is local-only; this file has not been committed yet at time of writing — commit follows in next step.
