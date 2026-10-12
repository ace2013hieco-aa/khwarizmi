# MERGE-LOG-P-AUTO-4 — land P-AUTO-4 slice + bypass fix (LOCAL-ONLY, NO PUSH)

## Lineage (linear, fast-forward — no merge commit, tips preserved)

- `main@9e4a5d3f8f7895e639f40216cf4345cbf7538a89` (verified unmoved:
  local `rev-parse` + `ls-remote origin main` identical, pre and post)
- `slice/p-auto-4-caps@da0d26ce08c1a4d416d4fdee97154e15d61239f8`
  (envelopes + safety caps; 7 files, +1513/−15)
- `fix/p-auto-4-bypass@0f578dfa44858f164805eb8207db716dba4725ab`
  (6 bypass closures; 6 files, +946/−45)
- `merge/p-auto-4` advanced `9e4a5d3` → `0f578df` by CAS-guarded
  `update-ref` (`merge-base == 9e4a5d3`, `--is-ancestor` TRUE).
  This log commit adds 3 files only (2 carried audit docs, byte-identical
  by blob hash, + this log). **No `src/` changes on the merge branch.
  STOPPED BEFORE PUSH per D9-lapsed instructions.**

## Gate counts (merge worktree, `PYTHONPATH=<worktree>/src`)

- Full suite: **2620 collected → 2616 passed, 4 skipped** (live, 0 failed)
- New on this lineage: **26** P-AUTO-4 caps tests + **12** bypass-fix tests
  (38 total; each fix test fails on `da0d26c`, passes on `0f578df`)
- F15 cap-sweep (`needed == ceil(300/cap)`): green
- `ruff check src tests`: **All checks passed!**
- `pyright src`: **0 errors**; tests config: **0 errors, 1 warning**
  (pre-existing `test_research_program.py:144`)
- Audits carried: `AUDIT-P-AUTO-4-REDTEAM.md` (FAIL → 6 MUST-FIX) and
  `AUDIT-P-AUTO-4-DELTA.md` (PASS, closures re-derived, hunts clean)

## D6 ratified values table (proposed in slice, fixed for audit/fix)

per_task_steps=5, per_tick_steps=8, per_run_steps=1000, per_task_tokens=250,
per_tick_tokens=1000, per_run_tokens=10000, overall_dispatch_deadline_s=300.0,
per_tick_wall_s=600.0, per_run_wall_s=3600.0, retry_max_retries=3,
retry_base_delay_s=1.0, retry_max_delay_s=30.0, jitter=True,
daily_cap_hard_stop=daily_cap_exhausted (no retry), loop_repeat_threshold=3,
openalex 5.0/5/1000, pubmed 3.0/3/1000, admission_wait_bound_s=60.0.

## Residuals carried (NOT fixed here — design follow-ups, fail-closed)

- **N1** (delta NOTE): lease-race orphan execution charges no tokens —
  bounded to one dispatch volume, rare; re-execution counted separately.
- **N2** (delta NOTE): quarantine is terminal-permanent — no operator
  un-quarantine intent/CLI exists; content-addressed re-admission returns
  the same FAILED row. Needs a design-gated appeal path, never a silent one.
- **Cross-process counters**: all trackers are process-lifetime in-memory;
  durable cross-process budgets need a schema/design gate (explicitly
  deferred — memory-only is what failed B1 within a process; across
  processes nothing accumulates at all).
