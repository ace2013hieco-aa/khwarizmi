# MERGE-LOG-EXT-2 -- local FF of slice/ext-2-restacked2@863f4b1

**Task:** EXT-2-MERGE2 (merge gate only -- re-stack the EXT-2 integrity
commits onto current `main`, verify, then land; no new scope).
**Repo:** `D:\New folder\research-agent` (GitHub `ace2013hieco-aa/khwarizmi-research`).
**Branch:** `main` (fast-forwarded **locally**; main-bound holder
`C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\met-1-merge-wt`, restack worktree
`C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\ext-2-remerge2-wt`) -- **LOCAL-ONLY, NO PUSH**.
**Verdict:** **PASS** -- `main` verified unmoved at `ff9fa7b`, clean cherry-pick re-stack
(zero conflicts), content-identity proven both directions, clean fast-forward,
stamp `--check` OK (4447), collect 4447, tamper pins 3/3, B4 24/24, census PASS,
ruff clean, pyright src 0/0/0, pyright tests-config 0 errors (1 pre-existing warning),
full suite 4444 passed / 0 failed / 3 skipped (red set EMPTY, subset of baseline-5),
`eval_plane` 205 passed in isolation. **Nothing pushed.**

## Re-stack authorization (sanctioned alternative)

- Sibling SUB-1-REMERGE moved `main` `b240de2 -> ff9fa7b` (legitimate sibling landing:
  `79dbfef` Demo.srt + `0609086` companion fill + MERGE-LOG-SUB-1 only). The EXT-2 stack
  root `84006a3` has parent `3eed0a6`, while `main` is at `ff9fa7b`
  (= `3eed0a6` + 2 EXT-0 files + 3 SUB-1 files). A direct FF is therefore
  **impossible**: `git merge-base --is-ancestor ff9fa7b 9332f52` is **false**.
- Rebase-prohibition D1 covers `main`'s shared history. All lines here are **local-only**
  (`main` is ahead of `origin/main`, never pushed), and the Director explicitly authorizes this
  **cherry-pick re-stack** as the sanctioned alternative (EXT-2-MERGE2 re-issue; prior attempt
  STOPPED correctly on the moved main and its pre-flight legs are adopted here).
- Method: fresh worktree at `ff9fa7b` on new branch `slice/ext-2-restacked2` -> cherry-pick
  `84006a3`, `4419a96`, `9332f52` **in order, messages kept, no squashing**.
  Conflicts would have been STOP (zero encountered -- no creative resolution performed).

## Lineage (verified, not assumed)

- `git rev-parse main` (before) == `ff9fa7b526e2d2888cd18a1f1574787425578dac` -> **unmoved**
  (re-verified immediately pre-FF in the main-bound holder, clean tree; no STOP).
- Composition pre-check: `git diff --name-only b240de2..ff9fa7b` -> **exactly 3 files**:
  `CATALYST-DEMO-SCRIPT.md`, `docs/MERGE-LOG-SUB-1.md`, `docs/judge-demo/Demo.srt`
  (`b240de2ad0b5ad11b71ad92524efb8da9f555b5d..ff9fa7b526e2d2888cd18a1f1574787425578dac`).
- Old stack root check: `git rev-parse 84006a3^` == `3eed0a6ac76e82447b595f131aacef9a167dbbde`
  -> siblings confirmed, FF-impossible confirmed.
- `git merge-base --is-ancestor ff9fa7b 863f4b1` -> **true** (**FF-able**).

```
main  ff9fa7b526e2d2888cd18a1f1574787425578dac   (verified unmoved before the FF)
  ├ e7b446e6222e1fd55efb104fbd90b316323dbd64  feat(artifacts): fail-closed verified content-addressed read (EXT-1 R2)
  ├ bafb1382a44b73baed675eb380d9f2d1f9d9b38b  fix(persistence): re-verify artifact bytes on the decision read path (EXT-1 R2)
  └ 863f4b1dc4273323e8bd263f63bc782133d5fbf1  fix(controller): refuse a tampered artifact at the EXTRACT seam (EXT-2 audit S1)
             == slice/ext-2-restacked2 tip
```

- Old -> new hash map (cherry-pick re-stack, messages kept; author + author-date preserved):

| # | Old (`3eed0a6`-based) | New (`ff9fa7b`-based) | Subject |
|---|---|---|---|
| 1 | `84006a3f3d9034523b7642340adf85e8289bf759` | `e7b446e6222e1fd55efb104fbd90b316323dbd64` | feat(artifacts): fail-closed verified content-addressed read (EXT-1 R2) |
| 2 | `4419a969139c06c1c864c91ee0e75b686b37f509` | `bafb1382a44b73baed675eb380d9f2d1f9d9b38b` | fix(persistence): re-verify artifact bytes on the decision read path (EXT-1 R2) |
| 3 | `9332f52d0bf91ee25bf5c3876cb26fa96c96b920` | `863f4b1dc4273323e8bd263f63bc782133d5fbf1` | fix(controller): refuse a tampered artifact at the EXTRACT seam (EXT-2 audit S1) |

- Message byte-identity (file-compare of `git log -1 --format=%B` old vs new):
  all three pairs compare **identical** (no diff lines).
- Author/date preserved (spot-checked #1):
  `ace2013hieco-aa 2026-10-13 22:15:36 +0300` at both `84006a3` and `e7b446e`.
- `main`: `ff9fa7b526e2d2888cd18a1f1574787425578dac` -> `863f4b1dc4273323e8bd263f63bc782133d5fbf1`
  via `merge --ff-only` **in place** in the main-bound holder (house procedure).

## Content-identity proof (restacked tree == `9332f52` tree + 2 EXT-0 files + 3 SUB-1 files)

- `git diff --name-status 9332f52 HEAD` -> **exactly 5 files**:
  `M CATALYST-DEMO-SCRIPT.md`, `A docs/EXT-1-ROADMAP.md`, `A docs/MERGE-LOG-EXT-0.md`,
  `A docs/MERGE-LOG-SUB-1.md`, `A docs/judge-demo/Demo.srt`
  (2 EXT-0 files + 3 SUB-1 files; `--name-only | Measure-Object -Line` -> `5`).
- **Reverse** direction `git diff --name-status HEAD 9332f52` -> the same 5 files:
  `M CATALYST-DEMO-SCRIPT.md`, `D` x4 (i.e. the only difference in either direction
  is those 5 files).
- Exclusion diff **both ways**
  (`. ':!docs/EXT-1-ROADMAP.md' ':!docs/MERGE-LOG-EXT-0.md' ':!docs/MERGE-LOG-SUB-1.md' ':!docs/judge-demo/Demo.srt' ':!CATALYST-DEMO-SCRIPT.md'`)
  -> **empty** in both directions (no `--name-only` lines) => **no other byte differs**.
- Blob-level identity (`git rev-parse <rev>:<path>`, all 6 EXT-2 files match old vs new):
  `docs/SUITE-COUNT.md`, `src/hermes/artifacts/store.py`,
  `src/hermes/persistence/source_outcomes.py`, `src/hermes/research/controller.py`,
  `tests/test_artifacts.py`, `tests/test_extract_artifact_integrity.py` -> **6/6 YES**.
- Stack-shape equality: `git diff --stat 3eed0a6..9332f52` == `git diff --stat ff9fa7b..863f4b1`
  (`6 files changed, 293 insertions(+), 9 deletions(-)` both).

## What landed

`+293/-9` over `main@ff9fa7b` (6 files). No provider leakage, no persistence->research
imports added, no `.hermes/` / JSON / worktree files touched:

```
docs/SUITE-COUNT.md                       |   6 +-  (restamp 4444 -> 4447)
src/hermes/artifacts/store.py             |  33 +++++++  (ArtifactIntegrityError + read_verified)
src/hermes/persistence/source_outcomes.py |  10 +-  (read_payload_bytes via read_verified)
src/hermes/research/controller.py         |  32 +++++-  (EXTRACT-seam named refusal)
tests/test_artifacts.py                   |  64 +++++++++++-  (read-path re-verification pins)
tests/test_extract_artifact_integrity.py  | 157 ++++++  (new: 3 EXTRACT-seam refusal pins)
```

## S1 closure (AUDIT-EXT-2-REDTEAM SHOULD-FIX)

- Audit `f065cc3` (PASS-WITH-SHOULD-FIX) found the EXTRACT seam let
  `ArtifactIntegrityError` escape `tick()`/`run()` uncaught (task left RUNNING, no refusal
  code), while the handler seam already produced refusal-as-data (FAILED).
- Fix (old `9332f52`, restacked `863f4b1`): `_execute_extract`
  (`src/hermes/research/controller.py`) catches `ArtifactIntegrityError` at the seam
  (model call moved inside the same try) and routes it to the NAMED terminal refusal
  `ARTIFACT_INTEGRITY_REFUSED` (mirrors `_run_handler`). Terminal, not retryable
  (a re-read re-derives the same mismatch). No wider certified-surface change, no new writes.
- Pins: 3 tests in `tests/test_extract_artifact_integrity.py` (both refusal pins fail when
  the handler is removed); 4 re-verification tests in `tests/test_artifacts.py`.
  Commit message records: stamp 4444 -> 4447, B4 fixtures byte-identical, check_census PASS,
  ruff clean, full suite red set == baseline-5.

## Gates (raw, on restacked tip `863f4b1`, offline, `PYTHONPATH=<wt>\src`, no extra `-q`)

Interpreter for every gate below: `D:/New folder/research-agent/.venv/Scripts/python.exe`
(**Test-Path: True**, Python 3.14.1, pyright **1.1.414**, ruff **0.16.10**)
-- recorded with each result per the binding pyright rule. Machine idle
(no competing jobs; B4 3.76s nominal vs 4.45s SUB-1 reference).

- **Tamper pins** (`scripts/run_tests.py tests/test_extract_artifact_integrity.py -v`) ->
  `3 passed in 1.00s` (exit 0). The EXTRACT-seam named refusal holds on the restacked tree.
- **Wiring pins** (`scripts/run_tests.py tests/test_artifacts.py -v`) ->
  `26 passed in 0.58s` (exit 0).
- **Stamp `--check`** (`scripts/stamp_suite_count.py --check`) ->
  `OK: docs\SUITE-COUNT.md collected=4447 matches the live collect` (exit 0).
- **Collect** (`scripts/run_tests.py --collect-only`) -> `4447 tests collected in 1.39s` (== 4447).
- **B4** (`scripts/run_tests.py tests/test_b4_ref_graphs.py`) -> `24 passed in 3.76s` = **24/24**.
- **Census** (`scripts/check_census.py`) -> `PASS - every certified figure is reproduced exactly`
  (121 calls; owners 18/5/4 = 27; rollback-only 1; persistence->research imports 15; outside 0).
- **Ruff** (`python -m ruff check src tests`) -> `All checks passed!` (exit 0).
- **Pyright src** (`python -m pyright src --pythonpath "<venv python>"`,
  interpreter **Test-Path: True**) -> `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests-config** (`python -m pyright --pythonpath "<venv python>" --project
  pyrightconfig.tests.json`, interpreter **Test-Path: True**) ->
  `0 errors, 1 warning, 0 informations` (exit 0). The single warning
  (`test_research_program.py:144 reportSelfClsParameterName`) is in a file outside the
  6-file landing range (pre-existing, not a regression). Note: the SUB-1-era 108-env
  baseline (unresolvable `import pytest`) does **not** reproduce here -- the venv
  `site-packages` resolves and the stricter 0-error standard holds.
- **Full suite** (`scripts/run_tests.py tests --tb=short -rf`) ->
  `4444 passed, 3 skipped in 455.33s (0:07:35)`. Pass+skip = **4447** = collect.
  **0 failed** -- red set EMPTY (subset of baseline-5; see below).

## Red set: EMPTY, subset of baseline-5 (not a superset)

Documented baseline-5 (`docs/MERGE-LOG-SUB-1.md`, via MERGE-LOG-CLOUD/FRONT-1/NUM-1):

```
tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

This run: **none** of the 5 fired (environmental races / Windows symlink privilege --
flaky by nature). Red set = EMPTY SET, and EMPTY is a subset of baseline-5 (delta < 0,
an improvement, not a regression). The landing range touches 2 test files whose 33 tests
(26 + 3 + 4 overlapping pins) all pass above, so no red could be induced.

### Documented flake -- did not fire; isolation proof recorded

`tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree`
is the documented 30 s pinned-subprocess-timeout flake (`docs/MERGE-LOG-NUM-1.md`). It is **not**
in the red set (empty), so no isolation proof was required; one was run anyway on the restacked
tip in `ext-2-remerge2-wt` (repo venv, Test-Path True):

```
tests/test_eval_plane.py in isolation, restacked tip, ext-2-remerge2-wt : 205 passed in 38.26s (EXIT=0)
```

## STOP-condition checks

| Condition | Result |
|---|---|
| NOT-list hit (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`) | **PASS** -- `CLEAR` (0 hits) over the range subjects/bodies and the full range diff |
| main moved before the FF | **PASS** -- unmoved at `ff9fa7b526e2d2888cd18a1f1574787425578dac` (re-verified immediately pre-FF in holder) |
| cherry-pick conflict / creative resolution | **PASS** -- 3/3 applied clean, messages kept, no squashing |
| content-identity fails | **PASS** -- restacked == `9332f52` + 2 EXT-0 + 3 SUB-1 files (both-directions diff = those 5; exclusion diff empty both ways; blobs 6/6) |
| red set superset of baseline | **PASS** -- red set EMPTY, subset of baseline-5 |
| `--check` drift | **PASS** -- `--check` OK, collected 4447 = 4444+0+3 |
| roadmap diff beyond the status cell | **PASS** -- deferred to the roadmap commit below (proven there by diff) |
| stale main-bound worktree left behind | **PASS** -- `main` bound only to `met-1-merge-wt` at the final tip (see Hygiene) |
| FAIL audit on the landing range | **PASS** -- none (HARD RULE checked below) |
| push without a human hash-pin | **none performed** |

### HARD RULE -- no FAIL audit on the landing range

The landing range `ff9fa7b..863f4b1` is the 6-file EXT-2 stack. The only audit artifact
targeting it is `f065cc3` (AUDIT-EXT-2-REDTEAM) with verdict **PASS-WITH-SHOULD-FIX**
(0 MUST-FIX), whose single SHOULD-FIX (S1) is closed by `9332f52`/`863f4b1` above.
A `--grep=EXT-2` sweep over all refs finds no other EXT-2 audit (the one lowercase
`ext-2` hit, `d9ed6f7`, is a recovery-probe commit touching diagrams + `test_controller.py`,
not an audit of this range). No FAIL audit exists on this range => **HARD RULE not
triggered**; nothing to surface and halt on.

## Worktree hygiene

- `met-1-merge-wt` (house arrangement preserved): was bound to `main@ff9fa7b` clean -> FF'd **in
  place** to the restacked tip `863f4b1` -> this log commits on top; ends bound to `main`
  at the final tip, **clean**. No stale main-bound worktree.
- `ext-2-remerge2-wt`: holds `slice/ext-2-restacked2@863f4b1` (not main-bound; own restack work).
  After the in-place FF both refs point at `863f4b1` (expected -- same commit, no divergence).
- `ext-2-wt` (`slice/ext-2-integrity@4419a96`), `ext-2-fix-wt` (`fix/ext-2-s1@9332f52`),
  `ext-0-wt`, `ext-0-merge-wt`, `sub-1-remerge-wt`, all other sessions' worktrees: **untouched**.
- `git worktree prune` / the FF-time step-4 error
  (`failed to delete 'D:/New folder/research-agent/.git/worktrees/step-4': Permission denied`) --
  **known, ignored per brief** (same as MET-1 / DS-1 / EXT-0 / SUB-1).

## Push charters (DRAFTED, NOT EXECUTED -- D8/D9)

Every push requires explicit human approval and a hash pin. **No `git push` was run; no remote
ref was touched.**

**Charter A -- `khwarizmi-research` (origin) -- plain push**
- Remote: `origin https://github.com/ace2013hieco-aa/khwarizmi-research.git` (only remote configured).
- Observed: `origin/main` = `ff9fa7b526e2d2888cd18a1f1574787425578dac` (behind; local ref, offline).
- Proposed (hash-pinned): `git push origin <reviewed-main-hash>:refs/heads/main`
  (**no `--force`**, no `--tags`), where `<reviewed-main-hash>` is the human-approved final tip
  **plus** this log commit and the roadmap commit below once reviewed (currently `main` =
  `863f4b1dc4273323e8bd263f63bc782133d5fbf1` pre-log). Advances `origin/main`
  `ff9fa7b -> 863f4b1 -> log -> roadmap`, fast-forward only.
- Preconditions: human approves; `origin/main` still at/behind `ff9fa7b...`; local tree clean;
  pushed hash == reviewed hash.

**Charter B -- `khwarizmi` public mirror -- orphan-sync**
- Remote: **not configured in this checkout**. Parent pinned by rule at mirror HEAD
  `1192b5152edc81174cb905fa2bbc1cf532829f91` (`sync: Catalyst application from dev main@256d155`,
  present locally as a commit; convention carried from `MERGE-LOG-CAT-2.md` / `-DEM-1` / `-DS-1` / `-SUB-1`).
- Convention: orphan-sync -- the sync commit's **parent is the mirror HEAD** (`1192b51...`), so the
  push is a fast-forward; **no `--force`** (rule #5).
- Proposed (hash-pinned): `git commit-tree <reviewed-main-tree> -p 1192b5152edc81174cb905fa2bbc1cf532829f91 -m "sync: EXT-2 restack from dev main@<hash>"`,
  then verify `sync^{tree} == <reviewed-main>^{tree}` and
  `git merge-base --is-ancestor 1192b51... <sync>`, then `git push <mirror> <sync>:refs/heads/main`.
- Preconditions: same reviewed hash as Charter A; mirror public; human approves.

## Credential-path statement

- No live vendor calls and no real credentials were used. All gates ran offline; `--check`
  performs only a local `pytest --collect-only`.

## NOT-LIST scan

`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy` -- **0 substantive hits** across the range's
commit subjects/bodies and the full range diff (`Select-String` -> no match).

License: Apache-2.0 (LICENSE).
