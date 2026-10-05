# IDR-045 Implementation Audit — Adversarial (fresh independent session)

**Branch:** `idr-045/impl-audit` from `idr-045/implement@96c52e7` (merge-base `c2c8fa9`)
**Inputs confirmed:** (1) `idr-045/implement@96c52e7` file list — 9 files (`ROADMAP.md`, `docs/idr/IDR-045.md`, `src/hermes/core/intents.py`, `src/hermes/persistence/repositories.py`, `src/hermes/research/controller.py`, `src/hermes/research/gateway.py`, `src/hermes/research/programs.py`, `src/hermes/research/task_plan.py`, `tests/test_idr045_plan_admission_and_provenance.py`); (2) fifth audit C1–C6 `idr-045/audit5@92ba005:docs/IDR45-audit5.md` (170 lines, PASS WITH CONDITIONS C1–C6); (3) ratification `D1-A, D2-A, Q1=plan-once, Q7=keyed-otherwise`; (4) live baselines `main@c2c8fa9` for every touched file (`git show 96c52e7` vs `c2c8fa9` diffed). All readable — no STOP.

**Scope / constraints honored:** read-only except this file; no `src/`/`tests/`/`docs/` edits; no push.

**Verdict: PASS**

> **Superseded in part by `docs/MERGE-AUDIT-045.md` (verdict FAIL).** This
> implementation audit did not falsify the two merge blockers, and its own
> evidence contains the gap: §4 verified that the C5 length guard *fires* on a
> `__post_init__` bypass but did not check **where** it fires — it runs in
> `_append_audit_event`, after `_validate_insert_task` has already committed its
> row, so the refusal left a durable task with no `IntentApplied` and no
> `IntentRejected` row (F2). §1/§2/§3 also did not exercise the pass's failure
> paths, all of which swallowed silently (F-swallow, now D1.7). The PASS below is
> scoped to the seven attack surfaces listed, which did hold.

All seven attack surfaces were executed against live code at `96c52e7`. Every falsification attempt failed — the C1–C6 closures hold as coded. No new intent kind / event type / table was introduced; follow-ons remain untouched. One non-blocking observation is carried forward (envelope, already deferred in IDR-045).

---

## 1 — C1 end-to-end (B3C child admitted, tick plans the primary only — executed)

**Attack:** `fresh_db → _admit_compiled(base_payload) → tick()` admits 9-task primary plan (`src/hermes/research/task_plan.py:build_task_plan`); then admit B3C child via `PROPOSE_RESEARCH_PROGRAM` with `parent_program_id=pid1, parent_hypothesis_ref=H1, target_regime=ICSS-v1:low-vol`; then `tick()` again.

**Evidence:**

- `src/hermes/persistence/repositories.py:1711` `current_primary(project_id)` → `SELECT … WHERE project_id=? AND parent_program_id IS NULL ORDER BY version DESC LIMIT 1`; `src/hermes/research/controller.py:_plan_admission_pass` inline query `AND parent_program_id IS NULL` (same literal, not `current()` / `_program_head_id`).
- Live run: `unfiltered=current("p1").parent_program_id == pid1` (child is head), `filtered=current_primary("p1").program_id == pid1` (primary still head); child plan `task_ids` disjoint from primary; `tasks_after tick == primary_plan.task_ids` (9 rows), child `task_ids ∩ DB == ∅`.
- `26 passed` in `tests/test_idr045_plan_admission_and_provenance.py:TestC1B3CChildHead`.

**Result: C1 HOLDS — not falsified.** The controller never calls `current()` for eligibility; the filtered head is the sole admission key (Q7).

## 2 — Per-payload atomicity (mid-plan crash leaves k rows, re-tick completes — executed)

**Attack:** `k=4` payloads admitted individually via `apply_intent(ADMIT_TASK, DETERMINISTIC)` outside `tick()` → `tasks==4, TaskCreated==4`; then `Controller.tick()` completes to `n=9` (`plan.task_ids` match clean-admission reference DB).

**Evidence:**

- `src/hermes/research/controller.py:_plan_admission_pass` — loop `for payload in payloads: apply_intent(conn, intent, …)` with no `BEGIN/COMMIT`; `TaskRepository.create` (`src/hermes/persistence/repositories.py:408`) owns `BEGIN`/`COMMIT` per row; `src/hermes/research/gateway.py:apply_intent` delegates without outer transaction (verified: no `BEGIN` in pass body, no `BEGIN` in `apply_intent` wrapper).
- `tick()` ordering: `mode self-heal → if ACTIVE: _plan_admission_pass() → _apply_evidence_ladder_pass() → _dispatch_pass()` (`controller.py`: the self-heal at :516-559, the `mode is not ACTIVE` early return at :560, `_plan_admission_pass()` at :574, ladder :579, contradictions :592, dispatch :599; `tick()` itself is defined at :486).
  *(Citation corrected 2026-09-29 by MERGE-AUDIT-045 F14: this line previously cited `controller.py:tick:75,89,91,114`, which does not correspond to `tick()` in this file.)*
- `tests/test_idr045_plan_admission_and_provenance.py:TestD1CrashResume` green.

**Result: C6 HOLDS — not falsified.** Crash leaves `k` observable rows; re-tick is idempotent via `ADMIT_TASK duplicate=True` (`gateway.py:3906`).

## 3 — V1 (origin_* reads in any authorization path — grep + attempt)

**Attack:** grep `_require_role` / `_require_project` for `origin_`; then `apply_intent(ADMIT_TASK, RESEARCHER, origin_kind=deterministic, origin_ref=plan_admission_pass)` bypass attempt.

**Evidence:**

- `src/hermes/research/gateway.py:151` `_require_role` reads only `AgentProfile(intent.proposed_by)` + `IntentKind.{director_only,internal_only,llm_proposable}` (`intents.py:124,144`); `origin_` count in that function: 0; `_require_project`: 0.
- All `origin_` hits in `gateway.py` lie inside `def _append_audit_event` (14 occurrences, each within `gateway.py:4068`); structural test `TestV1GrepGuard` enforces this.
- Bypass attempt: `GatewayRejection code=ROLE "ADMIT_TASK is internal-only … only the DETERMINISTIC controller may propose it, not RESEARCHER"` — provenance ignored.

**Result: V1 HOLDS — not falsified.**

## 4 — V4 bounds (oversized origin_ref through the real audit builder)

**Attack:** construct `Intent(origin_ref="x"*65)` (limit 64) normally; then bypass `__post_init__` via `object.__new__` + `object.__setattr__` and call `apply_intent`.

**Evidence:**

- `src/hermes/core/intents.py:202` `__post_init__` → `ValueError "origin_ref exceeds max length 64: 65"`; limits: `origin_kind 13 / origin_ref 64 / model_ref 128 / run_id 64 / prompt_template_version 32 / charter_version 32` (`intents.py:ORIGIN_*_MAX_LENGTH`).
- `src/hermes/research/gateway.py:4103` `_append_audit_event` pre-`validate_payload_size` loop → `GatewayRejection MALFORMED_PAYLOAD "origin_ref exceeds max length 64: 65"` even on bypass object.
- Default payload byte-identical: `set(payload)=={intent_kind, proposed_by, project_id, justification}` (no `origin_*`); non-default payload size 237 < 4096.

**Result: V4 HOLDS — not falsified.** Per-field limits are dual-enforced (construction + audit boundary), before the 4 KiB cap.

## 5 — DIRECTOR origin sites (exactly two relabeled, behavior identical — diff + test)

**Evidence:**

- `git diff c2c8fa9..96c52e7 -- src/hermes/research/controller.py` — only additions: `origin_kind="deterministic"` + `origin_ref="propose_review_actions"` at `propose_review_actions` (line 1136) and `origin_kind="deterministic"` + `origin_ref="propose_refutation_actions"` at `propose_refutation_actions` (line 1203); `proposed_by="DIRECTOR"` unchanged at both sites.
- Counts at `96c52e7`: `proposed_by="DIRECTOR"` == 2, `origin_kind` == 4 (2 DIRECTOR sites + 1 plan-admission site + 1 docstring); `DIRECTOR+origin_kind` co-occurrences == 2.
- `tests/test_idr045_plan_admission_and_provenance.py:TestD2DirectorSitesCarryProvenance` asserts both strings; `TestV1GrepGuard` confirms `proposed_by` not switched to `DETERMINISTIC`.

**Result: HOLDS — not falsified.** Two-site relabeling is additive, behavior-identical.

## 6 — program_from_dict as new attack surface (untrusted dict → program row? trace its callers)

**Evidence:**

- Callers (`git grep program_from_dict`): `src/hermes/research/controller.py:4065,4084` + `tests/test_idr045…:138,215,400,452` only; `src/hermes/research/programs.py:1613` defines it.
- Single production caller: `_plan_admission_pass` → `d = _research_program_row_to_dict(row)` (`repositories.py:1826`, parses `hypothesis_json` etc. from the DB row) → `program = program_from_dict(d)` → `build_task_plan(program)` → `plan_to_payloads`. No `Intent` payload, no user input, no `INSERT`.
- `program_from_dict` body (`programs.py:1613`): pure `ResearchProgram(…)` reconstruction from already-parsed dict; no `Repository`, no `INSERT`, no `execute`, no `conn` — `writes DB? false`.
- Write path for `research_programs` is `ResearchProgramRepository.create` via `compile_from_payload` (validated), not `program_from_dict`. The new helper is a row-dict → dataclass reconstruction at the same trust boundary.
  *(Corrected 2026-09-29 by MERGE-AUDIT-045 F5/F10: this line previously claimed the helper "is the inverse of `program_to_dict`". It is not — `program_to_dict` omits `program_id`/`project_id`, so a round-trip dropped both to `''` while `task_plan._identity` hashes `program_id` into every plan `task_id`. `program_from_dict` now requires both keys and raises. The conclusion of this section — that it is not an attack surface — is unaffected.)*

**Result: NOT an attack surface — not falsified.** It cannot create a program row; it reads the DB-trusted projection then projects to `TaskCreated` only via `apply_intent`.

## 7 — Follow-ons genuinely untouched (envelope/lease/stall/lifecycle/trace grep)

**Evidence:**

- `git diff c2c8fa9..96c52e7 --stat` touches only the 9 IDR-045 files; `migrations.py` and `events.py` diffs empty (no new table / event type); `IntentKind` values unchanged.
- Keyword deltas in `controller.py`: `envelope 6→6, lease_horizon 0→0, stall 1→1, lifecycle 0→0, trace_artifact 0→0, reasoning_trace 0→0`; `_plan_admission_pass` contains no `cap/limit/envelope/stall/timeout` logic (the `MAX(version)` SQL literal is not a cap).
- `docs/idr/IDR-045.md` lists follow-ons explicitly as untouched, each needing its own gate; the 26-test suite does not assume them.

**Result: HOLDS — not falsified.** No silent absorption.

---

## Method

All attacks executed via `uv run python` against the `96c52e7` working tree (branch `idr-045/impl-audit`), re-reading `src/` at each step; pytest `tests/test_idr045_plan_admission_and_provenance.py` (26/26 pass) used only as corroboration, not as sole evidence.

## Residual observation (non-blocking, already deferred)

The admission pass has no per-tick payload cap — a 100-requirement program would emit 100 `ADMIT_TASK` intents in one tick. This is the envelope bounded-liveness follow-on documented in `docs/idr/IDR-045.md` and `docs/IDR45-audit5.md:§3`; its absence does not violate C1–C6 and is correctly not shipped here. The `derive_program_obligations` consistency check blocks empty-hypothesis synthetic fixtures as specified; a fully-consistent synthetic program is out of scope for this IDR (DB trust boundary).

## Provenance (no push)

Branch `idr-045/impl-audit` is local-only; this file has not been pushed.
