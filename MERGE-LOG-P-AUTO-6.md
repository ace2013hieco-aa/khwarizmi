# MERGE-LOG-P-AUTO-6 — land P-AUTO-6 closed-loop integration test (LOCAL-ONLY, NO PUSH)

## Lineage (linear, fast-forward — no merge commit, tips preserved)

- `main@916fc23b1401991d3b84ea70a13ed7d8d1aaaa8f` (verified unmoved:
  local `rev-parse main` + `ls-remote origin refs/heads/main` identical
  pre-merge and re-checked post-merge)
- `slice/p-auto-6-loop@b3345f14ba6c22d2ac576f667c04d8b97d1a4233`
  (closed-loop integration test; 1 file, +629/−0 —
  `tests/test_p_auto_6_loop.py` +629, blob `b37ad424`; **zero `src/`
  changes**)
- `audit/p-auto-6-redteam@e7d89351345e04e0188aa6748d24e7a8ceaa999d`
  (`AUDIT-P-AUTO-6-REDTEAM.md`, 153 lines, blob `57d8e9b1`, verdict PASS —
  0 MUST-FIX / 3 SHOULD-FIX / 3 NOTE)
- `merge/p-auto-6` advanced `916fc23` → `b3345f1` by `git merge --ff-only`
  (`merge-base(main, slice) == 916fc23`; `--is-ancestor` TRUE; clean
  `Updating 916fc23..b3345f1 / Fast-forward`, exit 0; 1 file changed,
  +629). This log commit adds 2 files only (the carried audit doc,
  byte-identical by blob hash `57d8e9b1…`, + this log). **No `src/`
  changes on the merge branch. STOPPED BEFORE PUSH per D9-lapsed
  instructions.**

## Gate counts (merge worktree, `PYTHONPATH=<worktree>/src`, tip `b3345f1`)

- Full suite: **2670 passed, 12 warnings in 480.56s** (0 failed, 0 skipped;
  exit 0) — 2664 on `916fc23` + **6** new
  (`tests/test_p_auto_6_loop.py`; focused gate `6 passed in 1.18s`)
- `ruff check src tests`: **All checks passed!** (exit 0)
- `pyright src`: **0 errors, 0 warnings, 0 informations** (strict, exit 0)
- `pyright --project pyrightconfig.tests.json`: **0 errors, 1 warning**
  (pre-existing `tests/test_research_program.py:144`, exit 0)
- Red-to-green evidence (slice's temp legs, re-derived independently by the
  audit at different seams): envelope removal → `3 failed / 3 passed`
  (quarantine family) and `1 failed / 5 passed` (`assert 1 == 0` at
  `tests/test_p_auto_6_loop.py:549`, deadline); green at the tip under all
  gates above.

## Follow-ups carried (recorded, NOT implemented here)

None of these are introduced by this slice — C1/D1 live in the P-AUTO-4
autonomy machinery, F1 is test-harness ergonomics.

- **C1 (SHOULD-FIX)** — classifier substring collision:
  `classify_failure_signature` (`src/hermes/research/autonomy_caps.py:491-508`)
  matches the transient marker `"refused"` inside `"acceptance refused…"`,
  bucketing a deterministic validation rejection as `TRANSIENT`; the
  class label in the quarantine reason misleads and a deterministic refusal
  alternating with an `EMPTY` failure resets the other's streak
  (different-class reset, `:428-430`). The slice's poison test pins only
  `LOOP_PATTERN_QUARANTINE`-family containment, never the class. Fix:
  exclude/word-boundary the connection markers and pin the intended class.
- **D1 (SHOULD-FIX)** — `reimport_quarantine`
  (`src/hermes/research/autonomy_caps.py:526-551`, esp. `AND t.status =
  'FAILED'`) trusts the mutable row: forcing a journal-quarantined task to
  `RUNNING` + `attempt=0` loses the boot re-import and the task is
  re-executed once before re-deriving its streak. Not reachable in-band
  (quarantine implies the FAILED transition; refusals at
  `src/hermes/research/controller.py:2910-2916` / `:2944-2950`), but
  inconsistent with the anti-tamper precedent at `controller.py:1757-1768`.
  Harden by consulting the journal marker for non-FAILED rows or document
  the row-mutation assumption.
- **F1 (SHOULD-FIX)** — red legs are temp-only; nothing in the repo can
  re-run "envelope removed". Proposal: opt-in `HERMES_FAULT_KILL` registry
  (`tests/fault_injection/kills.py` + conftest) or a committed
  `scripts/red_legs.py`.
- **C2 (NOTE)** — the deadline envelope is proven only at the fetch batch
  check (`src/hermes/tools/providers/paginate.py:994-1002`,
  `_deadline_expired` at `:181`); mid-retry (`:592-595`) and search-walk
  (`:247`) sites are covered elsewhere (P-AUTO-3), not by this slice.
- **E1 (NOTE)** — the production-absence assertion is name-glob narrow
  (`*CERTIFICATION*` + `AUTONOMY`/`P-AUTO`, `PRODUCTION.md`); a
  differently-named certification record would escape. Broaden if the
  naming is not frozen.
- **G1 (NOTE)** — two explicit-file pyright `reportArgumentType` errors
  (slice `:123`, `:264`) are suppressed by the tests profile's
  `reportArgumentType: "none"`; test-only nits, runtime-safe as written.
- **Parked (unchanged)** — cross-process budget counters are in-memory;
  restart persistence remains out of scope for the P-AUTO line.

## Autonomy-loop completion statement

With this merge (local-only), the autonomy loop is **landed-or-landing**:
P-AUTO-1 (planner line, merged), P-AUTO-2 (prompts/assembler, merged),
P-AUTO-3 (live fetch path, merged), P-AUTO-4 (deterministic envelopes +
safety caps, merged), P-AUTO-5 (vault projection, merged), and P-AUTO-6
(closed-loop integration test — plan → dispatch → stub → validate → gate →
project, with seeded fault injection) lands here. P-AUTO-6 proves the loop
end-to-end and **does not declare production**: no certification artifact
exists, and the slice's boundary test
(`tests/test_p_auto_6_loop.py:604-629`) deliberately pins that absence.
Production declaration remains excluded from this line.