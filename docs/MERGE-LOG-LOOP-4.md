# MERGE-LOG-LOOP-4 — the deadline bound, the informed retry, E6/E7/E8, and the absolute anchor

## Provenance

| Item | Value |
| --- | --- |
| Task | LOOP-4-MERGE (merge gate only — no push) |
| Base (`main` before) | `25b9e69af769480d31b4708b14ed8680abb23b03` |
| Slice | `slice/loop-4-hygiene@62b40af0ec154cf6a3955384564773e680a78d97` |
| Fix | `fix/loop-4-anchor@46c048a67ae31fdc4816885661718ed3948a1938` |
| Landed tip (FF'd to) | `46c048a` — tree `14c52a666bae21d49c8f73833427058a7deae41b` |
| Slice commits | `7f3f78d` (deadline bound, E2/E3/G8 mid-batch) + `b4145e3` (informed retry, E5) + `40ba139` (drop the dead `DELEGATION_LIMIT`, E6) + `46b573d` (one severity rule, E7) + `b383cde` (`capability_refs`, E8) + `33a52e7` (13 pins) + `72ee54a` (restamp 4642 → 4655) + `62b40af` (record) |
| Fix commits | `aa12dd2` (absolute `deadline_mono` anchor, audit M1) + `d2ce3f6` (rewritten E3 pins, audit M2) + `46c048a` (record) |
| Merge worktree (gate runs + this log) | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/loop-4-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` in the main-bound house worktree |
| FF evidence | `merge-base(main, 46c048a)` == `main` (`25b9e69`); `main..46c048a` = 11, `46c048a..main` = 0; the chain is **single-parent** end-to-end (`7f3f78d` parent `25b9e69` … `46c048a` parent `d2ce3f6`) — **no merge commit** |
| Rebase / merge commit / force | **none** — FF only, linear single-parent chain (D1 respected: no rebase) |

## Scope

8 files, **+1308/−38**, **spine diff 0** (`git diff 25b9e69..46c048a -- src/ ':!src/hermes/agents/runtime/'`
is empty — 0 lines):

```
docs/LOOP-4-ANCHOR-FIX.md              | 259 ++   (the M1/M2 fix record)
docs/LOOP-4-HYGIENE.md                 | 155 ++   (the batch record)
docs/SUITE-COUNT.md                    |   6 +-   (restamp 4642 -> 4655)
src/hermes/agents/runtime/assembly.py  |  37 ++
src/hermes/agents/runtime/run.py       | 204 ++-  (deadline bound, retry, severity, anchor)
src/hermes/agents/runtime/supervisor.py|  29 +-
src/hermes/agents/runtime/types.py     |  33 +-  (Checkpoint.deadline_mono, capability_refs)
tests/test_loop4_hygiene.py            | 623 ++   (new, 13 tests)
```

The batch closes the LOOP-0 hygiene remainder in one bounded pass: the run's deadline becomes a
**run-level** bound checked at the terminal act and mid-batch (E2/E3/G8); a retry is asked with the
refusal that ended the previous attempt and its wait never crosses the bound (E5); the dead
`DELEGATION_LIMIT` member is removed (E6); malformed model output lands on one stated severity rule —
refused-and-skipped vs invoked-and-fatal (E7); a draft carries the evidence it was drafted on (E8).
The fix then makes the deadline carry an **absolute monotonic instant** (`Checkpoint.deadline_mono`)
so a repeatedly-resumed run is bounded (M1) and rewrites the two E3 pins to assert the work *not* done
(M2). No file outside `src/hermes/agents/runtime/` is touched: the single mutation path
(`apply_intent`), the journal writers, persistence, and the research layers are untouched.

Stamp delta is self-consistent: base `Collected: 4642` → landed `Collected: 4655` = **+13** = the new
battery (`tests/test_loop4_hygiene.py` collects exactly 13). Per-commit: the five fix commits, the
pin commit, the slice record, and the three anchor-fix commits all hold **4655** after `72ee54a`
moved `4642 → 4655`; the six commits before it hold 4642 (code and tests, no stamp edit). The
anchor fix adds no test, so it does not move the stamp.

## HARD RULE — audit duty (carried, not adjudicated)

Two audits exist on this exact range; both are carried, neither is re-litigated.

| Audit | Hash | Branch | Verdict |
| --- | --- | --- | --- |
| `AUDIT-LOOP-4-REDTEAM.md` | `11a78b5184c0ba3c9b07f3c74d4cba86b13117a7` | `audit/loop-4-redteam` | **FAIL — 2 MUST-FIX** (M1 deadline-reset loophole, M2 vacuous pin) on `slice/loop-4-hygiene@62b40af` |
| `AUDIT-LOOP-4-READDENDUM.md` | `7202144c1ecb351e637f618dc76b2d12b40712fb` | `audit/loop-4-reaudit` | **PASS — M1/M2 FAIL-CLOSED → PASS** on `fix/loop-4-anchor@46c048a` |

**The FAIL → PASS chain (recorded, not re-litigated).** `11a78b5` FAILed the *pre-fix* tree: M1 — the
E3 carry stored a *remaining duration*, re-recorded on every entry, so a crash before progress handed
the run the full declared bound on every resume (driven: `remaining` stayed 100.0 across five resumes
against a declared 100.0 s); M2 — both E3 pins passed with the carry neutralised, so they pinned E2's
terminal check, not the carry. `aa12dd2` answered M1 by carrying the deadline as an absolute instant
set once; `d2ce3f6` answered M2 by making both pins assert the work *not* done. `7202144` re-audited
the fixed tree and found M1/M2 closed — remaining strictly decreasing to expiry, both pins failing
with the carry neutralised and passing with E2's check alone neutralised, the battery 13/13, and the
full suite exactly the baseline-5.

Per the HARD RULE this gate does not adjudicate either audit. It re-derives the load-bearing claims
live on the landed tip:

| Audit claim | This gate's re-derivation |
| --- | --- |
| M1 closed — bounded resume, fail-closed expiry | carried; the landed `13/13` hygiene battery re-run below exercises it |
| M2 closed — both E3 pins load-bearing | carried; the landed battery includes the two rewritten pins |
| Battery 13/13 | re-derived live: `13 passed` |
| Full suite = exact baseline-5 | re-derived live: `5 failed, 4647 passed, 3 skipped` — exactly the 5 |
| Spine diff 0 | re-derived live: empty (0 lines) |
| Stamp 4642 → 4655 (+13) | re-derived live: `--check` OK 4655, pin count 13 |

**No OTHER FAIL audit exists on the range.** `audit/loop-0-triage` (`AUDIT-LOOP-0-TRIAGE.md`) is the
*input* triage that adjudicated the items as VALID/STALE on the pre-slice tree — it is not a FAIL
verdict on `25b9e69..46c048a`. The only other audit docs in the tree (`audits/AUDIT-H2-REDTEAM.md`,
`audits/AUDIT-P-AUTO-3-REDTEAM.md`, `docs/archive/AUDIT-*`, `docs/gr3-b4/*-audit*.md`,
`docs/MERGE-AUDIT-*`) predate and do not cover this range. **HARD RULE satisfied — no unadjudicated
FAIL audit; not a STOP.**

## Gates (raw, on the landed tip `46c048a`, `PYTHONPATH=<wt>/src`, no extra `-q`)

Interpreter for every gate below:
`C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/loop-4-merge-wt/.venv/Scripts/python.exe`
(a directory junction to the repo venv; **Test-Path: True** for both the repo venv
`D:/New folder/research-agent/.venv/Scripts/python.exe` and the junction, identical SHA-256
`22D89D728C105376D48ECD425EBA826C05F713A9962805B9B39924664A203076`; Python 3.14.1). The worktree was
clean at `46c048a` when the gates ran.

- **Collect** (`scripts/run_tests.py --collect-only`) → `4655 tests collected in 7.13s` (== 4655).
- **Stamp `--check`** (`scripts/stamp_suite_count.py --check`) →
  `OK: docs\SUITE-COUNT.md collected=4655 matches the live collect` (exit 0).
- **Census** (`scripts/check_census.py`) → `PASS - every certified figure is reproduced exactly.` (exit 0).
- **Ruff** (`python -m ruff check src tests`) → `All checks passed!` (exit 0).
- **Pyright src** (`python -m pyright src --pythonpath "<wt>/.venv/Scripts/python.exe"`) →
  `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests-config** (`python -m pyright --pythonpath "<wt>/.venv/Scripts/python.exe"
  --project pyrightconfig.tests.json`) → `0 errors, 1 warning, 0 informations` (exit 0), the only
  warning being the pre-existing `tests/test_research_program.py:144:23 reportSelfClsParameterName`
  (that file is not in the range diff). The repo-venv junction makes the venv discoverable to
  pyright, so the recording alone reaches the **0-error** standard.
- **B4** (`pytest tests/test_b4_ref_graphs.py`) → `24 passed in 3.89s` = **24/24**.
- **Hygiene battery** (`pytest tests/test_loop4_hygiene.py`) → `13 passed in 0.84s` = **13/13**.
- **Probe + assembly** (`pytest tests/test_loop0_e1_probe.py tests/test_loop1_context_assembly.py`)
  → `11 passed in 0.45s` = **11/11**.
- **Feedback battery** (`pytest tests/test_loop2_feedback.py`) → `20 passed in 0.48s` = **20/20**.
- **Review battery** (`pytest tests/test_loop3_review_rounds.py`) → `12 passed in 0.37s` = **12/12**.
- **Full suite** (`scripts/run_tests.py tests --tb=short -rf`, **idle machine**) →
  `5 failed, 4647 passed, 3 skipped, 1 warning in 594.41s (0:09:54)`.
  Pass + skip + failed = 4647 + 3 + 5 = **4655** == collect.

## Red set: EXACTLY baseline-5 (not a superset)

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

Environmental races (readonly-DB concurrency ×4 — the log's traceback is
`sqlite3.OperationalError: attempt to write a readonly database`) / Windows symlink privilege ×1 —
flaky by nature, unchanged from the documented baseline. **Delta = 0; the red set is the baseline-5
exactly, not a superset.** The documented `eval_plane` timing flake
(`tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree`)
**did not fire** (0 occurrences in the log), so no isolation proof was required. The suite was run
**alone on an idle machine** — no static gate ran concurrently (lesson carried from
`MERGE-AUDIT-P-AUTO-1-RETRY`).

## NOT-list scan: PASS (no functional coupling)

Binding rule: the four terms bar DOING WORK in those domains; clearance prose asserting absence is
NOT a hit; only functional coupling stops the gate. The canonical four:
`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy` (external engines, per `docs/ARCHITECTURE.md`).

- Range diff (`git diff 25b9e69..46c048a`), word-boundary, case-insensitive → **1 hit** — the slice
  record's own declaration of the four terms (`docs/LOOP-4-HYGIENE.md`), which is clearance prose
  asserting absence and **not** a hit.
- Whole landed tree (`git grep -inE "backtest_audit|optimize-my-strategy|\bSDA\b|\bTSE\b" 46c048a -- src tests config`)
  → **0 hits**.
- Commit subjects + bodies over the range → **0 hits**.

**No hit = no functional coupling. Scan PASSES; no STOP.**

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 in tree + commit bodies; the 1 range hit is clearance prose |
| `main` moved before the FF | **PASS** — re-verified unmoved at `25b9e69` (local == `origin/main`) immediately pre-FF |
| FF-ability | **PASS** — `merge-base(main, 46c048a)` == `main`; `--ff-only` used, exit 0; `46c048a..main` = 0; no merge commit; rebase prohibited (D1) and not used |
| dirty main-bound worktree / concurrent merge gate | **PASS** — exactly one main-bound worktree (`met-1-merge-wt`), clean at `25b9e69` pre-FF; the gate worktree `loop-4-merge-wt` did not exist before this gate (no collision) |
| red set superset of baseline-5 | **PASS** — exactly the 5, delta 0; `eval_plane` did not fire |
| `--check` drift | **PASS** — collected 4655 == stamp |
| FAIL audit on the landing range | **PASS** — `11a78b5` FAIL (M1+M2) is closed per `7202144` PASS; no other FAIL audit |
| stale main-bound worktree left behind | **PASS** — house worktree clean at the final tip |
| push without a human hash-pin | **none performed** |

## Worktree hygiene

- **House main-bound worktree** (`C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt`,
  the arrangement carried from prior gates): bound to `main@25b9e69` and clean → FF'd **in place** to
  `46c048a` (the landing) → then FF'd in place again to this log commit → ends bound to `main` at the
  final tip, clean.
- **`loop-4-merge-wt`** (this gate's worktree): detached at the landed tip `46c048a`; every gate ran
  here; this log was authored and committed here, then FF'd onto `main`.
- `slice/loop-4-hygiene`, `fix/loop-4-anchor`, `audit/loop-4-redteam` and `audit/loop-4-reaudit`
  worktrees left as found. The shared checkout, `.hermes/`, `or*.json`, and other worktrees were not
  touched. (The FF logs a harmless `failed to delete .../worktrees/step-4: Permission denied` — the
  known stale-prune step; ignored, FF exit 0.)

## Dual push plans — drafted, NOT executed (D8/D9)

No push was performed by this gate. Both plans require a human hash-pin.

1. **`origin` plain-push** (`https://github.com/ace2013hieco-aa/khwarizmi-research`):
   push `<merge-gate-tip>:refs/heads/main`, single refspec, no force, no tags, after
   re-verifying live `origin/main` is a strict ancestor of the tip (FF).
2. **public mirror orphan-sync** (`https://github.com/ace2013hieco-aa/khwarizmi`):
   add a temp remote, `fetch --no-tags`, re-read the live mirror pin, build a sync commit
   whose tree is `<tip>^{tree}` and whose parent is the mirror HEAD (orphan convention —
   `merge-base` must be empty), push exact-hash with **no force** (rule #5), then remove
   the temp remote.

Neither plan is executed here. **No push without a human hash-pin.**

## Prohibited-claims discipline

This gate certifies a merge (a deadline bound, an informed retry, a severity rule, a vocabulary
member, a provenance field and an absolute deadline anchor, plus the pins that claim to cover them).
It makes no claim about the validity of any content a model, a reviewer or a capability carries, no
reproducibility claim, and no admissibility claim for any source. The "fails closed" legs are
statements about this plane's own terminal reporting, never about the truth of what a run observed.

License: Apache-2.0 (LICENSE).
