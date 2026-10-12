# MERGE-LOG-CAT-2 — merge/cat-2 (root Catalyst Q&A annex)

- Repo: `D:\New folder\research-agent` (GitHub `ace2013hieco-aa/khwarizmi-research`)
- Branch: `main` (fast-forwarded **locally**; merge worktree `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\cat-2-merge-wt`) — **LOCAL-ONLY, NO PUSH**
- Task: CAT-2-MERGE — land `slice/cat-annex@112cae1` (merge gate only)
- Verdict: **PASS** — `main` verified unmoved, clean fast-forward, hash preserved; stamp `--check` OK (4440);
  collect 4440; B4 24/24; ruff clean; pyright src 0/0/0; pyright tests-config 108 (documented env baseline,
  delta 0); full-suite red set == the documented 5 environmental reds **plus** the documented `eval_plane`
  30 s timeout flake (isolation-proven). **Nothing pushed.**

## Lineage (verified, not assumed)

```
main  256d155bd77b18ddec88001ebbbc4ae393fb0f6f   (verified unmoved before the FF)
 └ 112cae1  docs(cat-2): land human-owned CATALYST-QA-ANNEX.md at root (second FRONT-1 exception)
            == slice/cat-annex tip  (full hash 112cae1d87a4f6e6110e7b29758a3876cbb80379)
```

- `git rev-parse main` (before) == `256d155bd77b18ddec88001ebbbc4ae393fb0f6f` → **unmoved** (no STOP).
- `git merge-base --is-ancestor 256d155 112cae1` → true (**FF-able**; rebase prohibited D1, not used).
- `main` **was** checked out in the superseded CAT-1 merge worktree, so the advance was applied as the
  sanctioned **pure ref move** (`git update-ref refs/heads/main 112cae1 256d155`, compare-and-swap guarded),
  and that worktree was **immediately retired** (`git worktree remove --force cat-1-merge-wt`) so no stale
  main-bound worktree holding pre-merge content is left (the NUM-1-PUSH-A / CAT-1 lesson). `cat-2-merge-wt`
  was then attached to `main`.
- `main`: `256d155bd77b18ddec88001ebbbc4ae393fb0f6f` → `112cae1d87a4f6e6110e7b29758a3876cbb80379`.
- `256d155` remains an ancestor of the new `main` → **pure fast-forward**.
- `origin/main` observed unchanged at `256d155…` — **no push performed**.

## Audit record carried (referenced by hash, not re-committed)

- `AUDIT-CAT-2-REDTEAM.md` @ `audit/cat-2-redteam@31e9ee5` (that branch adds this one file only).
  Verdict carried: **PASS** (0 MUST-FIX / 0 SHOULD-FIX / 4 observations).

## Adjudication

| # | Finding (audit `31e9ee5`) | Disposition |
|---|---|---|
| O1 | "Labels:" sentence duplicated at `CATALYST-QA-ANNEX.md:3` and `:4` | **CARRIED** — pre-existing human prose; the slice correctly left it byte-untouched (disclosed in the `112cae1` body) |
| O2 | Root `.md` now 6 (4 + two human-directed exceptions) | **CARRIED** — this log records the second exception in `docs/` |
| O3 | Blob sha differs from the source by CRLF→LF only | **CARRIED** — see the byte-fidelity note below |
| O4 | The annex is not eol-pinned in `.gitattributes` | **CARRIED** — harmless (nothing hashes these root docs) |

No MUST-FIX and no SHOULD-FIX were found; nothing required a fix commit.

## Byte-fidelity (re-derived with hashes at merge time)

```
SOURCE(D:\New folder\khwarizmi\CATALYST-QA-ANNEX.md)  len=5865 crlf=78  sha256=c0eb359ada54c557073f4003b88ae2cd5c162c30bbd2fc9aee9aa281fbb84a03
  4 on-disk copies, all identical (khwarizmi, khwarizmi-app, khwarizmi-mirror, khwarizmi-pub)
112cae1 blob (LF)        len=5819 crlf=0   sha256=913d2ca03a4775b7320e9c4dc8bbba5a07a8e08ed58b2d09ce5d2d2a4172be68
112cae1 working tree     len=5899 crlf=80  sha256=5dd35016321bfb83…

working-tree == source + b"\r\nLicense: Apache-2.0 (LICENSE).\r\n"  ->  True
content delta (source-LF vs landed)                                ->  exactly 2 lines (blank + footer)
```

**EOL note (O3/O4).** The landed file is byte-faithful to the human-owned source: the *working tree* is
exactly the source plus the appended licence footer. The stored *blob* sha differs **only** because
`core.autocrlf=true` normalises the human file's CRLF to LF on commit — the annex is not eol-pinned in
`.gitattributes` (which pins only the 12 governed-corpus docs), and a checkout restores CRLF. No content
was altered. Recorded so a future blob-vs-source byte diff is not misread as tampering.

## Annex-link closure

`CATALYST-APPLICATION.md:7` links `[Q&A detail](CATALYST-QA-ANNEX.md)`. That link **dangled** when CAT-1
landed (recorded in `AUDIT-CAT-1-REDTEAM.md` and `docs/MERGE-LOG-CAT-1.md`). `112cae1` lands the target, so
the link now resolves; the annex links back at `CATALYST-QA-ANNEX.md:3` (`[CATALYST-APPLICATION.md](…)`).
Both files sit at the root, so both relative targets resolve.

## Changed files (256d155..112cae1)

```
1 file changed, 80 insertions(+)
A  CATALYST-QA-ANNEX.md      (root; human-owned Q&A annex, byte-identical landing + licence footer)
```
No `src/`, `tests/`, script, workflow, fixture, `.gitattributes` or governed-corpus change.

## Gates (raw, on landed tip `112cae1`, offline)

- **Stamp `--check`** → `OK: docs\SUITE-COUNT.md collected=4440 matches the live collect` (exit 0).
- **collect** (`--collect-only`, no extra `-q`) → `4440 tests collected in 8.09s` (exit 0).
- **B4 surface** → `64 passed` (`tests/test_b4_ref_graphs.py` = **24/24**).
- **Ruff** `ruff check src tests` → `All checks passed!` (exit 0).
- **Pyright src** → `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests** (`--pythonpath <abs-venv-python> --project pyrightconfig.tests.json`) →
  `108 errors, 1 warning` — the documented 108-env baseline (**delta 0, not zero**).
- **Full suite** → `6 failed, 4431 passed, 3 skipped, 1 warning in 655.13s` (`EXIT=1`).

## Red set == documented baseline-5 + the documented flake

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
FAILED tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree   <- documented 30 s flake
```

The first five are the pre-existing environmental reds documented in `docs/archive/MERGE-LOG-CLOUD.md` and
reproduced in `MERGE-LOG-FRONT-1.md` / `MERGE-LOG-NUM-1.md` / `MERGE-LOG-CAT-1.md`. The sixth is the
documented `eval_plane` flake; **isolation proof** (required by the merge brief):

```
pinned subprocess test run directly, landed tip, machine idle : 1 passed in 1.88s
pinned subprocess test run directly, right after the suite    : 1 passed in 33.70s   (> the 30 s matrix budget)
eval_plane in isolation, landed tip, right after the suite    : 1 failed in 66.74s   (the load-induced timeout)
eval_plane in isolation, landed tip, machine idle             : 1 passed in 39.62s
eval_plane in isolation, landed tip, machine idle             : 1 passed in 38.88s
failure signature when it fires                                : "timeout after 30.0s"
```

The flake is a load-sensitive 30 s subprocess timeout inside the matrix runner — the pinned test itself
completes in 1.88 s idle but 33.70 s under full-suite load. This slice adds a single root markdown file and
cannot influence a subprocess timeout. **Red set ⊆ documented baseline-5 ∪ {documented `eval_plane` flake} —
no new red; delta 0.**

## STOP-condition checks

| Condition | Result |
|---|---|
| main moved before the FF | **PASS** — unmoved at `256d155…` |
| red set superset of baseline | **PASS** — baseline-5 + the isolation-proven documented flake only |
| `--check` drift | **PASS** — `--check` OK, collected 4440 |
| stale main-bound worktree left behind | **PASS** — the superseded `cat-1-merge-wt` was retired before/at the ref move; `main` is bound only to `cat-2-merge-wt` at the landed tip, clean |
| push without a human hash-pin | **none performed** |

## Push charters (DRAFTED, NOT EXECUTED)

D8/D9: every push requires explicit human approval and a hash pin. **No `git push` was run.**

**Charter A — `khwarizmi-research` (origin) — plain push**
- Remote: `origin https://github.com/ace2013hieco-aa/khwarizmi-research.git`
- Observed: `origin/main` = `256d155bd77b18ddec88001ebbbc4ae393fb0f6f` (behind).
- Proposed (hash-pinned): `git push origin <reviewed-main-hash>:refs/heads/main` (no `--force`, no `--tags`).
- Preconditions: human approves; `origin/main` still at/behind `256d155…`; local tree clean; pushed hash ==
  reviewed hash.

**Charter B — `khwarizmi` public mirror — orphan-sync**
- Remote: not configured in this checkout; observed at merge time
  `HEAD = refs/heads/main = 1192b5152edc81174cb905fa2bbc1cf532829f91`.
- Convention: orphan-sync — the sync commit's **parent is the mirror HEAD** (`1192b51…`), so the push is a
  fast-forward; **no `--force`** (rule #5).
- Proposed (hash-pinned): `git commit-tree <reviewed-main-tree> -p 1192b5152edc81174cb905fa2bbc1cf532829f91 -m "sync: root Catalyst Q&A annex from dev main@<hash>"`, verify `sync^{tree} == <reviewed-main>^{tree}` and `merge-base --is-ancestor 1192b51… <sync>`, then `git push <mirror> <sync>:refs/heads/main`.
- Preconditions: same reviewed hash as Charter A; mirror public; human approves.

## Credential-path statement

- No live vendor calls and no real credentials were used. All gates ran offline; `--check` performs only a
  local `pytest --collect-only`.

## NOT-LIST scan

`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy` over `256d155..112cae1` (commit subject/body and the
changed-file list): **no hits**.

## STOP BEFORE PUSH

`main` is fast-forwarded **locally only**. Nothing is pushed. Both charters above require a human hash-pin
before execution.
