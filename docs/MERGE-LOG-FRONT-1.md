# MERGE-LOG-FRONT-1 — merge/front-1 (one-screen front door + B-01 archive move)

- Repo: `D:\New folder\research-agent` (GitHub `ace2013hieco-aa/khwarizmi-research`)
- Branch: `main` (worktree `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\front-1-merge-wt`) — **LOCAL-ONLY, NO PUSH**
- Task: FRONT-1-MERGE — land `slice/front-1-readme@a46896f` + `fix/front-1-s1s4@3d47459` (merge gate only)
- Verdict: **PASS** — `main` verified unmoved, clean fast-forward, hashes preserved; ruff +
  pyright src green; full-suite red set == the documented pre-existing environmental baseline
  (exact, delta 0, no new red); `docs/STATE.md` byte-identical (B4 pin). **Nothing pushed.**

## Lineage (verified, not assumed)

Linear topology; the whole advance was a single fast-forward, so every cited hash is preserved
byte-for-byte (no rebase, no `--no-ff` merge commit, no manual hunks, no conflict markers):

```
main   ef4129624677a1519954af000e6cc7da5ba05519   (verified unmoved before the FF)
 ├ f7e628fe65758ebbf8c574776e1004ed3fd7076b   slice: move 106 closed root records → docs/archive (B-01)
 ├ a46896f6590e03898b55622669845e0a628d9e95   slice: rewrite README as one-screen front door
 ├ 4409aa83298d2dfd75601dc2d3e0b76f6ec3fed8   fix S2: path-qualify bare-name refs to moved docs
 ├ 7cd4980232f57517e9adba14231bee3dca549865   fix S1: repair anchors invalidated by the README rewrite
 ├ aae07ab0a739e4b0c9276ee1a9787b9d9afe4e23   fix S3: guarantees row 4 → ARCHITECTURE.md 3.8
 └ 3d47459e1fdc58391fa6d7e44d630fe0f4a68368   fix S4: doctor parenthetical  == fix/front-1-s1s4 tip
```

- `git rev-parse main` (before) == `ef4129624677a1519954af000e6cc7da5ba05519` → **unmoved** (no STOP).
- `git merge-base --is-ancestor main fix/front-1-s1s4` → true (**FF-able**; rebase prohibited, not used).
- `git merge --ff-only fix/front-1-s1s4` → `Updating ef41296..3d47459  Fast-forward`
- `main`: `ef4129624677a1519954af000e6cc7da5ba05519` → `3d47459e1fdc58391fa6d7e44d630fe0f4a68368`
- `git status` clean post-FF; `origin/main` observed unchanged — **no push performed**.

## Audit + fix record carried (referenced by hash, not re-committed)

- `AUDIT-FRONT-1-REDTEAM.md` @ `audit/front-1-redteam@b7e610ce18f46ae378831868a4dd5b0af1c61b73`
  (that branch adds this one file only, +224 lines vs `main`). Verdict carried:
  **PASS-WITH-SHOULD-FIX** (0 MUST-FIX / 4 SHOULD-FIX / 2 observations).
- Fix record: the four `fix/front-1-s1s4` commits in the lineage above. Verdict: **PASS**.

## Changed files (ef41296..3d47459)

```
154 files changed, 93 insertions(+), 294 deletions(-)
```

- 106 `git mv` root records → `docs/archive/` (100% similarity, 0 create / 0 delete).
- `README.md` 249 → 47 lines (one-screen front door); `docs/README.md` descriptor updated.
- 46 `src/`+`tests/` files: bare-name refs path-qualified to `docs/archive/` (+ the one
  `DURABILITY_GATE` string constant).
- Root md **110 → 4**; total md **259**; `docs/archive/` md **29 → 135**.
- This merge-log commit adds `docs/MERGE-LOG-FRONT-1.md` (root md stays 4; total md 260).

## Gates (raw, on merged tip `3d47459`, offline)

- **Ruff** `uvx ruff check src tests` → `All checks passed!` (exit 0).
- **Pyright src** `uvx pyright src` → `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests** `uvx pyright --pythonpath <abs-venv-python> --project pyrightconfig.tests.json`
  → `108 errors, 1 warning, 0 informations` — **every** error is
  `Import "pytest" could not be resolved (reportMissingImports)`. This is **identical at
  `main@ef41296` (delta 0)**: pyright in this sandbox resolves only its typeshed fallback and never
  loads the venv `site-packages` (search paths = typeshed only), so *any* third-party import is
  unresolved. The documented baseline (`docs/archive/MERGE-LOG-CLOUD.md`) recorded
  `0 errors, 1 warning` on the authoring machine, whose pyright does load site-packages.
- **Full suite** `PYTHONPATH=<worktree>/src .venv/Scripts/python.exe scripts/run_tests.py -v`:
  `5 failed, 4432 passed, 3 skipped, 1 warning in 601.39s` (`EXIT=1`).

## Red set == documented baseline (exact)

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

These are **exactly** the 5 pre-existing environmental reds documented in
`docs/archive/MERGE-LOG-CLOUD.md` (3 concurrency races + 1 Windows symlink-privilege refusal +
1 q05 race). The landed `4432 passed` matches the documented figure. **Red set == documented
set (exact); no new red; delta 0.** `main` was not moved before the FF, so this is a like-for-like
comparison.

### Flake note (recorded, not a regression)

`tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree`
did **not** fail in this landed run. It is the documented 30 s pinned-subprocess-timeout flake
(`MERGE-LOG-CLOUD.md` "Flake note"); it was observed once in an earlier FRONT-1 run, passes in
isolation on both trees, and is **not** part of the red set.

## SHOULD-FIX disposition

| # | Finding (audit `b7e610c`) | Disposition |
|---|---|---|
| S1 | README rewrite invalidated in-repo anchors | **FIXED** `7cd4980` — `config.py:17` → `pyproject.toml [project].dependencies = []`; `README.md:15` → `## Operate (quickstart) <a id="operate"></a>`; `docs/README.md:5` descriptor. `AGENTS.md:87` deliberately **not edited**: it is a governed corpus member (`src/hermes/persistence/corpus.py:65`) content-addressed in 3 B4 fixtures (`tests/test_b4_ref_graphs.py:282` re-verifies live bytes) and regeneration writes `*.json`; the README anchor closes the pointer (also fixes `.github/workflows/ci.yml:27`). |
| S2 | bare-name residual census under-enumerated | **FIXED** `4409aa8` — 56 refs path-qualified across 46 files (38 `.md` basenames + 16 `ARCHITECTURE_DELTA` stems + 2 `WIRING_DESIGN` stems); 0 unqualified remain; 18/18 `docs/archive/` targets exist. 17 refs in `tests/fixtures/s2_crawl4ai/**` **justified leave-as-historical** (frozen recorded provider bytes; 5 are `*.json`). |
| S3 | guarantees row 4 cited `ARCHITECTURE.md 3.2` | **FIXED** `aae07ab` — now `3.8` (normative "Replay / determinism"). |
| S4 | Limits claimed `hermes doctor` probes execution engines | **FIXED** `3d47459` — now names the real probes (runtime, config, database, sandbox runner, lockfile). |
| O1 | demo "~5 s" vs measured warm ~7 s | **CARRIED** (soft rounding; no code change). |
| O2 | REPLAY DIGEST environment-sensitive | **CARRIED** (claim is consecutive-run stability, which holds). |

## Push charters (DRAFTED, NOT EXECUTED)

D8/D9: every push requires explicit human approval and a hash pin. **No `git push` was run.**

**Charter A — `khwarizmi-research` (origin)**
- Remote: `origin https://github.com/ace2013hieco-aa/khwarizmi-research.git`
- Proposed (hash-pinned): `git push origin <reviewed-main-hash>:refs/heads/main`, where
  `<reviewed-main-hash>` is `main` at review time (the FF'd tip plus this log commit).
- Preconditions: human approves; `origin/main` still at/behind `ef4129624677a1519954af000e6cc7da5ba05519`;
  local tree clean; the pushed hash equals the reviewed hash.

**Charter B — `khwarizmi` public mirror**
- Remote: **not configured in this checkout** — the mirror's URL/name must be supplied by the
  director (`git remote -v` lists only `origin`; no mirror remote or in-repo reference exists).
- Proposed (hash-pinned): `git push <mirror-remote> <reviewed-main-hash>:refs/heads/main`.
- Preconditions: mirror is public — director confirms the Apache-2.0 tree carries no non-public
  material; same reviewed hash as Charter A; human approves each push.

## Credential-path statement

- No live vendor calls and no real credentials were used. All gates ran offline; the test/demo
  stack uses recorded transports (`RecordedTransport`). `hermes doctor` reported
  `Sandbox [OPTIONAL / NOT CONFIGURED]`.
- NOT-LIST scan over `main..tip` (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`):
  **no additions**; one `backtest_audit` token appears only on a **removed** line (the old
  `README.md:185` external-engines paragraph deleted by the README rewrite).

## STOP BEFORE PUSH

`main` is fast-forwarded **locally only**. Nothing is pushed. Both charters above require a human
hash-pin before execution.
