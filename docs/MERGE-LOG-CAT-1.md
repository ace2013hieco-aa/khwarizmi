# MERGE-LOG-CAT-1 — merge/cat-1 (root Catalyst application + S1 count-idiom fix)

- Repo: `D:\New folder\research-agent` (GitHub `ace2013hieco-aa/khwarizmi-research`)
- Branch: `main` (fast-forwarded **locally**; merge worktree `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\cat-1-merge-wt`) — **LOCAL-ONLY, NO PUSH**
- Task: CAT-1-MERGE — land `slice/cat-application@607ca82` (`90243dd` + `607ca82`) + `fix/cat-1-s1@5710f2a` (merge gate only)
- Verdict: **PASS** — `main` verified unmoved, clean fast-forward, hashes preserved; stamp `--check` OK (4440);
  collect 4440; B4 24/24; ruff clean; pyright src 0/0/0; pyright tests-config 108 (documented env baseline,
  delta 0); full-suite red set == the documented 5 environmental reds **plus** the documented `eval_plane`
  30 s timeout flake (isolation-proven). **Nothing pushed.**

## Lineage (verified, not assumed)

Linear topology; the whole advance was a single fast-forward, so every cited hash is preserved byte-for-byte
(no rebase, no `--no-ff` merge commit, no manual hunks, no conflict markers):

```
main  3f8a1d696d8cd46664d72ec62d53b46cfe0b3218   (verified unmoved before the FF)
 ├ 90243dd  docs(cat-1): land human-owned CATALYST-APPLICATION.md at root (byte-identical)
 ├ 607ca82  docs(cat-1): refresh stale suite counts to 4440 per SUITE-COUNT.md, append license footer
 └ 5710f2a  fix(cat-1): close audit S1 — two suite lines to collected-count semantics  == fix/cat-1-s1 tip
```

- `git rev-parse main` (before) == `3f8a1d696d8cd46664d72ec62d53b46cfe0b3218` → **unmoved** (no STOP).
- `git merge-base --is-ancestor 3f8a1d6 5710f2a` → true (**FF-able**; rebase prohibited D1, not used).
- `main` was **not** bound to any worktree at merge time (the stale FRONT-1 worktree was retired in
  NUM-1-PUSH-A-RETRY), so the FF was a normal checkout fast-forward — no compare-and-swap ref move was
  needed and **no stale main-bound worktree exists afterwards**:
  `git worktree add <wt> main` then `git merge --ff-only 5710f2a` → `main`: `3f8a1d6…` → `5710f2a…`.
- `3f8a1d6` remains an ancestor of the new `main` → **pure fast-forward**.
- `origin/main` observed unchanged at `3f8a1d6…` — **no push performed**.

## Audit + fix record carried (referenced by hash, not re-committed)

- `AUDIT-CAT-1-REDTEAM.md` @ `audit/cat-1-redteam@83a360d` (that branch adds this one file only).
  Verdict carried: **PASS-WITH-SHOULD-FIX** (0 MUST-FIX / 1 SHOULD-FIX / 2 observations).
- Fix record: `fix/cat-1-s1@5710f2a` (S1 closed).

## Adjudication

| # | Finding (audit `83a360d`) | Disposition |
|---|---|---|
| S1 | The two refreshed lines asserted the **collected** count (4440) with **pass** semantics ("4,440 green" / "passes 4,440 tests") | **VALID → FIXED** `5710f2a` — `:6`/`:66` now read "collects 4,440 … per docs/SUITE-COUNT.md; 5 documented environmental reds at the certified tip (docs/MERGE-LOG-NUM-1.md), Ruff and Pyright clean"; exactly 2 lines, 2 ins / 2 del |
| O1 | Root `.md` set 4 → 5; exception recorded only in the `90243dd` body | **CARRIED** — this log records it in `docs/` |
| O2 | The doc's self-URL resolves on the mirror only after the mirror sync | **CARRIED** — resolved by Charter B below |
| NOTE | `AUDIT-CAT-1-REDTEAM.md` cites the annex link as `CATALYST-APPLICATION.md:8`; it is actually **`:7`** (the `90243dd` body says "line 7") | **CORRECTION FLAGGED** at CAT-1-FIX; audit record left unedited (out of scope) |

## Byte-fidelity (re-derived with hashes at merge time)

```
SOURCE(D:\New folder\CATALYST-APPLICATION.md) len=15498 lf=148 sha256=9b92077b38c4473fe74a2149f7ba86e4a7ec58c9f554dc31aee2fafc598b1744
90243dd blob                                  len=15498 lf=148 sha256=9b92077b…   == SOURCE (byte-identical: True)
5710f2a blob                                  len=15885 lf=150 sha256=288fcdc31bc74fb4…  (counts + footer + S1 rewrite)
```

`607ca82` vs `90243dd` = exactly the two count lines + the footer; `5710f2a` vs `607ca82` = exactly two lines
(`git diff -U0` changed-line count = 4 → 2 removed + 2 added). Every hedge (`:34,:48,:60,:68,:99`), the annex
line (`:7`) and the footer (`:150`) are byte-untouched; the `D:` original was never modified (COPY, never move).

## Changed files (3f8a1d6..5710f2a)

```
1 file changed, 150 insertions(+)
A  CATALYST-APPLICATION.md      (root; human-owned grant application, byte-identical landing + counts + footer + S1 rewrite)
```
No `src/`, `tests/`, script, workflow, fixture, `.gitattributes` or governed-corpus change.

## Gates (raw, on landed tip `5710f2a`, offline)

- **Stamp `--check`** → `OK: docs\SUITE-COUNT.md collected=4440 matches the live collect` (exit 0).
- **collect** (`--collect-only`, no extra `-q`) → `4440 tests collected in 8.81s` (exit 0).
- **B4 surface** → `64 passed` (`tests/test_b4_ref_graphs.py` = **24/24**).
- **Ruff** `ruff check src tests` → `All checks passed!` (exit 0).
- **Pyright src** → `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests** (`--pythonpath <abs-venv-python> --project pyrightconfig.tests.json`) →
  `108 errors, 1 warning` — every error is `Import "pytest" could not be resolved (reportMissingImports)`;
  the documented 108-env baseline (**delta 0, not zero**).
- **Full suite** → `6 failed, 4431 passed, 3 skipped, 1 warning in 676.36s` (`EXIT=1`).

## Red set == documented baseline-5 + the documented flake

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
FAILED tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree   <- documented 30 s flake
```

The first five are **exactly** the pre-existing environmental reds documented in `docs/archive/MERGE-LOG-CLOUD.md`
and reproduced in `docs/MERGE-LOG-FRONT-1.md` / `docs/MERGE-LOG-NUM-1.md` (3 concurrency races + 1 Windows
symlink-privilege refusal + 1 q05 race). The sixth is the documented `eval_plane` flake; **isolation proof**
(required by the merge brief):

```
pinned subprocess test run directly, landed tip : 1 passed in 2.00s
eval_plane in isolation, BASE 3f8a1d6           : 1 passed in 40.44s
eval_plane in isolation, landed tip 5710f2a     : 1 passed in 40.00s
eval_plane in isolation, landed tip 5710f2a     : 1 passed in 40.67s
failure signature when it does fire             : pinned_test 'tests/test_agent_runtime.py::TestCrashRecovery::
                                                  test_a_crash_after_progress_is_resumable_but_never_re_dispatched'
                                                  : timeout after 30.0s
```

The flake is a load-sensitive 30 s subprocess timeout in the matrix runner (the pinned test itself passes in
2.0 s); it also fired twice in isolation immediately after the 11-minute full-suite run, then passed twice
consecutively once the machine was idle, and it passes on the untouched base. This slice adds a single root
markdown file and cannot influence a subprocess timeout. **Red set ⊆ documented baseline-5 ∪ {documented
`eval_plane` flake} — no new red; delta 0.**

## STOP-condition checks

| Condition | Result |
|---|---|
| main moved before the FF | **PASS** — unmoved at `3f8a1d6…` |
| red set superset of baseline | **PASS** — baseline-5 + the isolation-proven documented flake only |
| `--check` drift | **PASS** — `--check` OK, collected 4440 |
| third-line change in the doc | **PASS** — the fix diff is exactly 2 lines (`:6`, `:66`) |
| stale main-bound worktree left behind | **PASS** — `main` is bound to `cat-1-merge-wt` and sits at the landed tip, clean |
| push without a human hash-pin | **none performed** |

## Push charters (DRAFTED, NOT EXECUTED)

D8/D9: every push requires explicit human approval and a hash pin. **No `git push` was run.**

**Charter A — `khwarizmi-research` (origin) — plain push**
- Remote: `origin https://github.com/ace2013hieco-aa/khwarizmi-research.git`
- Observed: `origin/main` = `3f8a1d696d8cd46664d72ec62d53b46cfe0b3218` (behind).
- Proposed (hash-pinned): `git push origin <reviewed-main-hash>:refs/heads/main` (no `--force`, no `--tags`).
- Preconditions: human approves; `origin/main` still at/behind `3f8a1d6…`; local tree clean; pushed hash ==
  reviewed hash.

**Charter B — `khwarizmi` public mirror — orphan-sync**
- Remote: not configured in this checkout; observed `HEAD = refs/heads/main = 1c5a3fd46823317c7b2104ed20f2ebfb2bf75636`.
- Convention: orphan-sync — the sync commit's **parent is the mirror HEAD** (`1c5a3fd`), so the push is a
  fast-forward; **no `--force`** (rule #5).
- Proposed (hash-pinned): create `commit-tree <reviewed-main-tree> -p 1c5a3fd -m "sync: root Catalyst application + S1 fix from dev main@<hash>"`, verify `sync^{tree} == <reviewed-main>^{tree}` and
  `merge-base --is-ancestor 1c5a3fd <sync>`, then `git push <mirror> <sync>:refs/heads/main`.
- Preconditions: same reviewed hash as Charter A; mirror public; human approves.

## Credential-path statement

- No live vendor calls and no real credentials were used. All gates ran offline; the stack uses recorded
  transports. `--check` performs only a local `pytest --collect-only`.

## NOT-LIST scan

`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy` over `3f8a1d6..5710f2a` (commit subjects, bodies and
the changed-file list): **no hits**.

## STOP BEFORE PUSH

`main` is fast-forwarded **locally only**. Nothing is pushed. Both charters above require a human hash-pin
before execution.
