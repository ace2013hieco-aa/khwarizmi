# MERGE-LOG-DEM-1 — merge/dem-1 (demo-script companion + application §8 pointers + carried S1–S3 closures)

**Task:** DEM-1-MERGE (merge gate only — no new scope)
**Slice:** `slice/dem-1-script@11e0cf7` + `fix/dem-1-carried@15db542` (S1–S3 closures)
**Base:** `main@de1fd9890769ceccf2a78e833477f4f39618401e`
**Worktree:** `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\dem-1-merge-wt` (detached) — **LOCAL-ONLY, NO PUSH**
**Verdict:** **PASS** — `main` fast-forwarded **locally** `de1fd98 → 15db542`, plus this log commit. All gates green; no STOP condition fired.

## Lineage (verified, not assumed)

- `main` observed at `de1fd9890769ceccf2a78e833477f4f39618401e` **before** the ref move — equals the brief's expected hash (checked, not assumed).
- `git merge-base --is-ancestor de1fd98 15db542` → **true** ⇒ a **direct fast-forward** (D1 rebase not needed; the DS-1 restack case did not recur).
- `git log --oneline 15db542..main` → **empty** ⇒ no divergence.
- Landing range `de1fd98..15db542` = 3 commits:

```
15db542 fix(dem-1): close audit S1-S3 (cite tip-stability, digest provenance, word-count subject)
11e0cf7 docs(dem-1): application §8 beat-navigation + deep-dive pointers
3596a96 docs(dem-1): land CATALYST-DEMO-SCRIPT.md at root (third FRONT-1 exception)
```

- Ancestry re-proved: `de1fd98 ⊂ 15db542` and `11e0cf7 ⊂ 15db542`.

## Ref-move procedure (and one documented deviation)

The brief asked for worktree `dem-1-merge-wt` and "never touch other worktrees", while also requiring
"no stale main-bound worktree left". `main` was **already held** by the clean worktree `met-1-merge-wt`
at `de1fd98`, so `git worktree add … main` was refused by git:

```
Preparing worktree (checking out 'main')
fatal: 'main' is already used by worktree at 'C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt'
```

Moving `refs/heads/main` from outside that worktree would have left it stale (HEAD moved, files not) —
the explicit STOP condition. The **DS-1 precedent** (this brief's cited lesson) records the house
procedure as FF'ing the main-bound holder **in place**: "`met-1-merge-wt` … was bound to `main@7407745`
clean → FF'd in place to the restacked tip → this log commits on top; ends bound to `main` at the final
tip, clean" (`docs/MERGE-LOG-DS-1.md:187-188`).

So: `dem-1-merge-wt` was created **detached** at `15db542` (verification + gate battery + log authoring),
and the ref move was executed **in place** in the main-bound holder, exactly as DS-1 did:

```
$ git -C <met-1-merge-wt> merge --ff-only 15db542
Updating de1fd98..15db542
Fast-forward
 CATALYST-APPLICATION.md |   5 +-
 CATALYST-DEMO-SCRIPT.md | 159 +++++++++++++++++++++++++++++++++++++++++++++++++
 docs/MERGE-LOG-DS-1.md  |   6 +-
 3 files changed, 166 insertions(+), 4 deletions(-)
 create mode 100644 CATALYST-DEMO-SCRIPT.md
```

`met-1-merge-wt` ends bound to `main` at the new tip, **clean** — no stale main-bound worktree.

## What landed

- **`CATALYST-DEMO-SCRIPT.md`** (new, +159) — the demo companion: 8-beat navigation table, the
  under-the-hood path per beat, adjacent evidence, deliberate non-claims, governance note. The
  third human-owned root `CATALYST-*` document (FRONT-1 exception family).
- **`CATALYST-APPLICATION.md`** (§8 pointers + S2 clause) — two pointer lines to the companion, plus
  one reconciling digest-provenance clause.
- **`docs/MERGE-LOG-DS-1.md`** (S3) — the `1450` word-count subject qualified as *the application*.

## Audit record carried (referenced by hash, not re-committed)

Audit `3e2c073` (`AUDIT-DEM-1-REDTEAM.md`, branch `audit/dem-1-redteam`) = **PASS-WITH-SHOULD-FIX**,
0 MUST-FIX / 3 SHOULD-FIX / 4 observations. All three SHOULD-FIXes are closed in-stack by `15db542`:

| Item | Disposition | Proof at the landed tip |
|---|---|---|
| S1 base-relative app cites blank at the tip | **FIXED in-stack** | both `CATALYST-APPLICATION.md:81` cites re-anchored to the `"Technical Validation"` **section heading**; `grep 'APPLICATION.md:81'` → 0 hits; heading resolves at base (`:79`) and tip (`:82`) |
| S2 two unreconciled "replay digest" values | **FIXED in-stack** | reconciling clause on the application's Technical Validation line (`CATALYST-APPLICATION.md:84`): `f360c174…` = shipped-recording digest (`docs/judge-demo/TWO-RUN-PROOF.txt`), `219cf7c4…` = this-tree re-derivation; both hexes kept |
| S3 `≤1450` subject ambiguous | **FIXED in-stack** | subject qualified as "the application" at all 3 occurrences (`docs/MERGE-LOG-DS-1.md:8`, `:131`, `:180`) |

**HARD RULE check:** no FAIL audit exists on the landing range `de1fd98..15db542` (`3e2c073` is
PASS-WITH-SHOULD-FIX; the range is docs-only, 3 files, no `src/`/`tests/` bytes) → **no STOP**.

## Changed files (de1fd98..15db542)

```
M  CATALYST-APPLICATION.md   (+3 pointers, +S2 clause)
A  CATALYST-DEMO-SCRIPT.md   (+159, new)
M  docs/MERGE-LOG-DS-1.md    (S3: 3 one-line subject qualifications)
3 files changed, 166 insertions(+), 4 deletions(-)
```

## Gates (raw, on the landed tip `15db542`, offline, `PYTHONPATH=<wt>\src`, no extra `-q`)

- **Application word count** (in-process `len(bytes.split())`) → `1312` (bytes 10361, 86 lines) **≤ 1450**. **PASS.**
- **Stamp `--check`** (`scripts/stamp_suite_count.py --check`) →
  `OK: docs\SUITE-COUNT.md collected=4440 matches the live collect` (exit 0).
- **Collect** (`scripts/run_tests.py --collect-only`) → `4440 tests collected in 6.56s` (== 4440).
- **B4** (`pytest tests/test_b4_ref_graphs.py`) → `24 passed in 12.51s` = **24/24**.
- **Ruff** (`python -m ruff check src tests`, ruff 0.16.10, repo venv) → `All checks passed!` (exit 0).
- **Pyright src** (`pyright src --pythonpath "D:/New folder/research-agent/.venv/Scripts/python.exe"`,
  pyright 1.1.414, interpreter Test-Path **True**) → `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests** (pyright 1.1.414, interpreter Test-Path **True**) → `0 errors, 1 warning, 0 informations`
  (exit 0). The single warning is the pre-existing
  `tests/test_research_program.py:144:23 - warning: Instance methods should take a "self" parameter`.
  **Method note (recorded, not hidden):** the repo's `pyrightconfig.tests.json` carries no
  `venvPath`/`venv`, and in this harness pyright's environment auto-detection does not bind the repo venv,
  so the *unbound* run reports the artifact baseline `108 errors` — all `reportMissingImports` for
  `pytest`, i.e. no interpreter search path. That `108` is the repo's own recorded env baseline
  ("the documented 108-env baseline (delta 0, not zero)", `docs/MERGE-LOG-NUM-1.md:82-83`). With the venv
  bound (`venvPath`+`venv`), the same tree reports `0 errors, 1 warning`. `--pythonpath` alone was proven
  inert here (identical `108` with the repo venv, with a pytest-less interpreter, and with none).
  Either way this is an environment property, identical at base and tip (the range is docs-only) → delta 0.
- **Full suite** (`scripts/run_tests.py`) →
  `5 failed, 4432 passed, 3 skipped, 1 warning in 637.63s (0:10:37)` (`EXIT=1`).
  Pass+fail+skip = 4432 + 5 + 3 = **4440** = collect. All 5 failures are the documented environmental
  baseline — exact equality, **delta 0** (see the red-set block below). The range touches no `src/`/`tests/`
  bytes, so the suite delta vs base is 0 by construction.

## Red set (⊆ documented baseline-5) + documented flake isolation

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

This is **exact set equality** with the documented environmental baseline-5
(`docs/MERGE-LOG-NUM-1.md:90-94`, reproduced from `docs/archive/MERGE-LOG-CLOUD.md`: 3 concurrency races +
1 Windows symlink-privilege refusal + 1 q05 race). Equality ⇒ subset-of-baseline holds and **delta 0** — no
new red. The failures are environmental (e.g. `sqlite3.OperationalError: attempt to write a readonly
database` on the concurrency races), not code: the landing range changes no `src/`/`tests/` bytes.

**Documented `test_eval_plane.py` flake — isolation proof (fired once under load, clean when uncontended):**

```
run 1 (contended, concurrent pyright load): 1 failed, 204 passed in 116.49s
  FAILED tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree
  cause : pinned_test 'tests/test_agent_runtime.py::TestCrashRecovery::test_a_crash_after_progress_is_resumable_but_never_re_dispatched': timeout after 30.0s
run 2 (uncontended, repo venv)            : 205 passed in 88.58s (EXIT=0)
```

The flake did **not** fire in the full-suite run (absent from the red set). The contended isolation run
reproduced the documented 30 s pinned-subprocess-timeout verbatim; the uncontended re-run is clean.

## Honest timestamp blanks (note carried from the companion)

The companion's beat table deliberately leaves **8 blank timestamp cells** (one per beat). Counted
precisely: 8 blank cells, **9** occurrences of the literal marker `[mm:ss — owner to fill while watching]`
(8 cells + the §1 description), **10** `mm:ss` tokens (adds the §1 prose mention of the format).
No `mm:ss` **value** appears anywhere else in the document, and the rehearsal table's real marks
(`docs/judge-demo/RECORDING-CHECKLIST.md:45-53`: `0:00`, `0:10`, `0:30`, `0:50`, `1:10`, `1:40`, `2:20`,
`3:00`, `3:20`) were **not** copied. An honest blank beats a fabricated number; the recording owner
fills them while watching.

## STOP-condition checks

| Condition | Result |
|---|---|
| NOT-list hit | **CLEAR** — 0 hits (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`) |
| `main` moved before the FF | **CLEAR** — observed exactly `de1fd98` |
| FF-ability fails (divergent) | **CLEAR** — `merge-base --is-ancestor de1fd98 15db542` true; reverse range empty |
| red-set superset of baseline-5 | **CLEAR** — see red-set block above |
| `--check` drift | **CLEAR** — `collected=4440` matches the live collect |
| word count > 1450 | **CLEAR** — `1312` ≤ 1450 |
| stale main-bound worktree left | **CLEAR** — `main` bound only to `met-1-merge-wt`, at the final tip, clean |
| FAIL audit on the landing range | **CLEAR** — none (HARD RULE checked above) |
| push without a human hash-pin | **none performed** |

## Worktree hygiene

- `met-1-merge-wt` (main-bound holder): was clean at `main@de1fd98` → **FF'd in place** to `15db542`;
  ends bound to `main` at the final tip, clean.
- `dem-1-merge-wt` (this task): detached at `15db542`; holds this log commit; **not** main-bound.
- `dem-1-fix-wt` (`fix/dem-1-carried@15db542`), `dem-1-wt` (`slice/dem-1-script@11e0cf7`),
  `dem-1-audit-wt` (`audit/dem-1-redteam`), all other sessions' worktrees: **untouched**.
- A worktree-local, gitignored `.venv` **junction** was created in `dem-1-merge-wt` to let pyright bind
  the repo venv; it is ignored by `.gitignore` (`.venv/`) and does not enter any commit.
- `git worktree prune` / FF-time step-4 error (`failed to delete '.git/worktrees/step-4': Permission
  denied`) — **known, ignored per brief** (same as DS-1/MET-1).

## Push charters (DRAFTED, NOT EXECUTED)

D8/D9: every push requires explicit human approval **and a hash pin**. **No `git push` was run.**

**Charter A — `khwarizmi-research` (origin) — plain push**
- Remote: `origin https://github.com/ace2013hieco-aa/khwarizmi-research.git`
- Observed (offline local ref): `origin/main` = `de1fd9890769ceccf2a78e833477f4f39618401e`; it is an
  **ancestor** of local `main`, so the push is a fast-forward (3 commits ahead).
- Proposed (hash-pinned): `git push origin <reviewed-main-hash>:refs/heads/main` (no `--force`, no `--tags`),
  where `<reviewed-main-hash>` is the human-approved final tip **including** this log commit.
- Preconditions: human approves; `origin/main` still at/behind `de1fd98…`; local tree clean; pushed
  hash == reviewed hash.

**Charter B — `khwarizmi` public mirror — orphan-sync**
- Remote: not configured in this checkout; parent pinned by rule at mirror HEAD
  `1192b5152edc81174cb905fa2bbc1cf532829f91` (present locally as a commit).
- Convention: orphan-sync — the sync commit's **parent is the mirror HEAD**, so the push is a
  fast-forward; **no `--force`** (rule #5).
- Proposed (hash-pinned): `git commit-tree <reviewed-main-tree> -p 1192b5152edc81174cb905fa2bbc1cf532829f91 -m "sync: DEM-1 from dev main@<hash>"`,
  verify `sync^{tree} == <reviewed-main>^{tree}` and `merge-base --is-ancestor 1192b51… <sync>`, then
  `git push <mirror> <sync>:refs/heads/main`.
- Preconditions: same reviewed hash as Charter A; mirror public; human approves.

## Credential-path statement

No live vendor calls and no real credentials were used. All gates ran offline; `--check` performs only a
local `pytest --collect-only`.

## NOT-LIST scan

`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy` over `de1fd98..15db542` (commit subjects/bodies and
the diff bytes): **no hits** (`CLEAR` × 4).

## STOP BEFORE PUSH

`main` is fast-forwarded **locally only** (plus this log commit). Nothing is pushed. Both charters above
require a human hash-pin before execution.

License: Apache-2.0 (LICENSE).
