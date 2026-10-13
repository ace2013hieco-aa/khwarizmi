# MERGE-LOG-MET-1 — merge/met-1 (pre-pilot benchmark baselines)

- Repo: `D:\New folder\research-agent` (GitHub `ace2013hieco-aa/khwarizmi-research`)
- Branch: `main` (fast-forwarded **locally**; merge worktree `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\met-1-merge-wt`) — **LOCAL-ONLY, NO PUSH**
- Task: MET-1-MERGE — land `slice/met-1-baseline@dfd99ef` (merge gate only)
- Verdict: **PASS** — `main` verified unmoved, clean fast-forward, hashes preserved; stamp `--check` OK (4440);
  collect 4440; B4 24/24; ruff clean; pyright src 0/0/0; pyright tests 0 errors + 1 pre-existing warning
  (absolute-`--pythonpath` run; see §5 for the 108-env note); full suite 4437 passed / 3 skipped / 0 failed
  (red set empty ⊆ baseline-5); `eval_plane` passes in isolation (205 passed). **Nothing pushed.**

## Lineage (verified, not assumed)

```
main  258fe2b421cc023fd47f1a242db459c84d751325   (verified unmoved before the FF)
 ├ 65b4d4a7b27514d4707939445286c2a9526d97bb  docs(met-1): Technical Validation baselines in CATALYST-APPLICATION.md (live re-derived)
 └ dfd99ef08e453f05bcfa7fb5b4d514f985aecc0c  docs(met-1): Pre-pilot benchmark baselines in CATALYST-QA-ANNEX.md (live re-derived)
            == slice/met-1-baseline tip
```

- `git rev-parse main` (before) == `258fe2b421cc023fd47f1a242db459c84d751325` → **unmoved** (no STOP).
- `git merge-base --is-ancestor 258fe2b dfd99ef` → true (**FF-able**; rebase prohibited D1, not used).
- `main` **was** checked out in the superseded CAT-2 merge worktree, so the advance was applied as the
  sanctioned **pure ref move** (`git update-ref refs/heads/main dfd99ef 258fe2b`, compare-and-swap guarded),
  and that worktree was **immediately retired** (`git worktree remove --force cat-2-merge-wt` — it showed
  the expected stale `M CATALYST-APPLICATION.md / M CATALYST-QA-ANNEX.md` after the ref move) so no stale
  main-bound worktree holding pre-merge content is left (the NUM-1-PUSH-A / CAT-1 lesson).
  `met-1-merge-wt` was then attached to `main` (`git worktree add met-1-merge-wt main`, clean at the tip).
  `git worktree prune` returned its known step-4 error
  (`failed to delete '.git/worktrees/step-4': Permission denied`) — **ignored per brief**.
- `main`: `258fe2b421cc023fd47f1a242db459c84d751325` → `dfd99ef08e453f05bcfa7fb5b4d514f985aecc0c`.
- `258fe2b` remains an ancestor of the new `main` → **pure fast-forward**.
- `origin/main` observed unchanged at `258fe2b…` (`git ls-remote origin refs/heads/main`) — **no push performed**.

## What landed

Docs-only slice, `+24/-0` over `main@258fe2b`, no `src/` / `tests/` / script / workflow / fixture /
`.gitattributes` / governed-corpus change:

```
CATALYST-APPLICATION.md | 12 ++++++++++++
CATALYST-QA-ANNEX.md    | 12 ++++++++++++
2 files changed, 24 insertions(+)
```

- `65b4d4a`: `## Technical Validation` section in `CATALYST-APPLICATION.md` (7 live re-derived figure
  groups + explicitly-absent disclosure + suite baseline at tree `258fe2b`).
- `dfd99ef`: `## 7. Pre-pilot benchmark (measured baselines — not targets)` in `CATALYST-QA-ANNEX.md`
  (same 7 groups, condensed; headline 50%/99% targets preserved as targets, byte-identical).
- Both files retain terminal `License: Apache-2.0 (LICENSE).` footers (verified in the merge worktree).
- Scope discipline preserved: synthetic control-plane handling only; replay = byte/evidence determinism,
  never scientific validity; no precision/recall measurement claimed (explicitly absent).

## Audit record carried (referenced by hash, not re-committed)

- `AUDIT-MET-1-REDTEAM.md` @ `ca0b40f25675ff8fa8efbfcf0cd9427c2505c63e`
  (audit input pinned by the merge brief; that commit adds this one file only).
  Verdict carried: **PASS-WITH-SHOULD-FIX** (7/7 figure groups reproduce live; 0 MUST-FIX, 1 SHOULD-FIX).
- Per-figure provenance (all live-verified by the carried audit; commands absolute, no extra `-q`):
  - F1 seeded-defect review — checker A 11/12, B 12/12, union 12/12, precision 1.0 on 4 cleans,
    1 disagreement (`fo-03`): `tests/cert_gate_rerun/test_reviewer_independence.py` (`3 passed`).
    Director re-derived at merge time in `met-1-merge-wt`: `3 passed in 0.11s` (exit 0).
  - F2 end-to-end harness ×2 + digest — `scripts/demo_judge.py` exit 0, `51/51 checks passed` on two
    consecutive runs, consecutive-same-tree digest equality True (hex `219cf7c4…` in the slice worktree).
  - F3 hostile-input refusals — `scripts/break_it.py` standalone `8/8 scenarios matched`, S1–S8 PASS,
    offline, no model.
  - F4 digest fold under 5 injected corruptions — all fail closed (`FORGED_IDENTITY` + `DEGRADED`,
    gate recomputed, duplicate decision refused at schema, no resurrection, stable hashes):
    `tests/test_q04_review_candidates.py::TestRecordSourceRetraction::test_digest_fold_fail_closed_deterministic`
    (`1 passed`).
  - F5 closed-loop seeded faults — 3/3 caught + recovery/golden/boundary legs:
    `tests/test_p_auto_6_loop.py` (`6 passed`).
  - F6 suite/collect/stamp/B4/ruff/pyrights/eval-plane node — collect 4440, stamp `--check` OK,
    B4 24/24, ruff clean, pyright src 0, pyright tests 0 errors/1 warning (absolute-path run),
    `test_eval_plane.py` flake not firing + passing in isolation.
  - F7 scope/absent/purity/gates attacks — no result/target confusion, no validity overclaim,
    diff purity (+24/-0 docs-only), gates delta-0.

## Adjudication

| # | Finding (carried audit `ca0b40f`) | Disposition |
|---|---|---|
| S1 | Digest hex is worktree-path-sensitive (`219cf7c4…` in slice worktree vs `625ff9…` in audit worktree; consecutive-same-tree equality holds, 51/51 + exit 0 unaffected) | **CARRIED-THEN-FIXED downstream** — fixed in `slice/ds-1-resume@227fc59eee9eba340ffaf727b8b7ffffbaf9d22c` (`docs(ds-1): qualify replay digest as same-tree consecutive-run claim (S1)`), which rewords the annex bullet to `same-tree consecutive-run digest — equality across consecutive runs is the claim`. Per merge brief, this landing is **not held** for S1; this log records S1 as carried-into-DS-1. |

No MUST-FIX in the carried audit; nothing required a fix commit on this landing.

### Later-audit disclosure (transparency; not the carried input)

After `ca0b40f`, the same branch advanced to `1246b628a7ac7471054bcc5833b4834244bcff0d`
(`FAIL+MUST-FIX, 2 MUST-FIX + 6 SHOULD-FIX`, re-ran the suite in the producer worktree+venv instead of
taking it as reported). It is **disclosed here, not carried** (the merge brief pins `ca0b40f`), with live
disposition on the landed tip:

- M1 (suite prose: producer env showed `5 failed / 4420 passed / 15 skipped`, the 5 being exactly the
  documented environmental baseline-5, vs shipped `0 failed / red set empty`). **Gate-irrelevant**:
  both values satisfy the merge criterion (red set ⊆ baseline-5 ∪ {documented flake}). Live on the landed
  tip in `met-1-merge-wt` (repo venv, docling/crawl4ai present): **0 failed** — the `red set empty` claim
  reproduces in this env. Env-dependence noted: producer venv lacks docling/crawl4ai (15 skips) while the
  repo venv has them (3 skips; 4437 = 4425 + 12, total still 4440).
- M2 (pyright tests prose `0 errors` vs `108 errors` with relative `--pythonpath ./.venv/...` from a
  venv-less worktree; all 108 are `reportMissingImports` for `pytest`). **Method artifact, gate-irrelevant**:
  with the brief-mandated **absolute** `--pythonpath` (`D:/New folder/research-agent/.venv/Scripts/python.exe`),
  the landed tip gives **0 errors, 1 warning** — matching the shipped claim and the CI value. The `108`
  remains the documented local baseline for the relative-path invocation
  (`docs/MERGE-LOG-NUM-1.md:8`, `MERGE-LOG-CAT-2.md`); delta-0 is against the shipped absolute-path claim.
- S1 retained (same digest path-sensitivity, SHOULD-FIX) — consistent with the carried audit; fixed in DS-1
  as above.

## Changed files (258fe2b..dfd99ef)

```
CATALYST-APPLICATION.md   (+12: Technical Validation section)
CATALYST-QA-ANNEX.md      (+12: §7 Pre-pilot benchmark section)
```

No `src/`, `tests/`, script, workflow, fixture, `.gitattributes` or governed-corpus change.

## Gates (raw, on landed tip `dfd99ef`, offline, `PYTHONPATH=<wt>/src`, no extra `-q`)

- **Stamp `--check`** → `OK: docs\SUITE-COUNT.md collected=4440 matches the live collect` (exit 0).
- **Collect** (`-m pytest --collect-only`) → `4440 tests collected in 1.28s` (exit 0).
- **Reviewer independence** (director re-derived) → `3 passed in 0.11s` (exit 0).
- **B4 surface** (`scripts/run_tests.py tests/test_b4_ref_graphs.py -v`) →
  `tests\test_b4_ref_graphs.py ........................` / `24 passed in 3.84s` (exit 0) = **24/24**.
- **Ruff** (`ruff check src tests`) → `All checks passed!` (exit 0).
- **Pyright src** (`pyright src`) → `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests** (`pyright --pythonpath "D:/New folder/research-agent/.venv/Scripts/python.exe" --project pyrightconfig.tests.json`) →
  `0 errors, 1 warning, 0 informations` (exit 0); the 1 warning is the pre-existing
  `tests/test_research_program.py:144:23 - warning: Instance methods should take a "self" parameter (reportSelfClsParameterName)`.
  Note: the `108-env` baseline documents the relative-`--pythonpath` invocation from a venv-less worktree;
  with the brief-mandated absolute path the landed tip is 0 errors (CI value), delta-0 vs the shipped claim.
- **Full suite** (`scripts/run_tests.py -v`) →
  `================= 4437 passed, 3 skipped in 519.82s (0:08:39) =================` (`EXIT=0`).
  Pass+skip = 4440 = collect. Skip delta vs the slice prose (3 vs 15) is env-only: the repo venv used here
  has docling/crawl4ai installed (12 pinned external-provider legs run and pass); the producer venv lacks
  them (15 skips). No drift: `--check` OK.

## Red set == empty (⊆ documented baseline-5) + documented flake isolation

```
Full-suite failures: none (0 failed).
```

The documented environmental baseline-5 (`docs/MERGE-LOG-NUM-1.md`, via `docs/archive/MERGE-LOG-CLOUD.md`:
3 concurrency races + 1 Windows symlink-privilege refusal + 1 q05 race) did not fire in this env.
Empty set ⊆ baseline-5 → **no new red; delta 0**. The documented `test_eval_plane.py` 30 s
pinned-subprocess-timeout flake did not fire in the full run; **isolation proof** (required by the brief):

```
tests/test_eval_plane.py in isolation, landed tip, met-1-merge-wt : 205 passed in 38.04s (EXIT=0)
```

## STOP-condition checks

| Condition | Result |
|---|---|
| NOT-list hit (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`) | **PASS** — `CLEAR` on all four over `main..slice/met-1-baseline` (commit subjects/bodies + diff) |
| main moved before the FF | **PASS** — unmoved at `258fe2b…` |
| red set superset of baseline | **PASS** — red set empty ⊆ baseline-5; flake isolation-proven |
| `--check` drift | **PASS** — `--check` OK, collected 4440 = 4437+3 |
| stale main-bound worktree left behind | **PASS** — superseded `cat-2-merge-wt` retired at the ref move; `main` bound only to `met-1-merge-wt` at the landed tip, clean |
| push without a human hash-pin | **none performed** |

## Push charters (DRAFTED, NOT EXECUTED)

D8/D9: every push requires explicit human approval and a hash pin. **No `git push` was run.**

**Charter A — `khwarizmi-research` (origin) — plain push**
- Remote: `origin https://github.com/ace2013hieco-aa/khwarizmi-research.git`
- Observed: `origin/main` = `258fe2b421cc023fd47f1a242db459c84d751325` (behind).
- Proposed (hash-pinned): `git push origin <reviewed-main-hash>:refs/heads/main` (no `--force`, no `--tags`),
  where `<reviewed-main-hash>` is the human-approved landed tip **plus** this log commit once reviewed
  (currently `main` = `dfd99ef08e453f05bcfa7fb5b4d514f985aecc0c` pre-log).
- Preconditions: human approves; `origin/main` still at/behind `258fe2b…`; local tree clean; pushed hash ==
  reviewed hash.

**Charter B — `khwarizmi` public mirror — orphan-sync**
- Remote: not configured in this checkout; observed at merge time
  `HEAD = refs/heads/main = 1192b5152edc81174cb905fa2bbc1cf532829f91`.
- Convention: orphan-sync — the sync commit's **parent is the mirror HEAD** (`1192b51…`), so the push is a
  fast-forward; **no `--force`** (rule #5).
- Proposed (hash-pinned): `git commit-tree <reviewed-main-tree> -p 1192b5152edc81174cb905fa2bbc1cf532829f91 -m "sync: pre-pilot benchmark baselines from dev main@<hash>"`, verify `sync^{tree} == <reviewed-main>^{tree}` and `merge-base --is-ancestor 1192b51… <sync>`, then `git push <mirror> <sync>:refs/heads/main`.
- Preconditions: same reviewed hash as Charter A; mirror public; human approves.

## Credential-path statement

- No live vendor calls and no real credentials were used. All gates ran offline; `--check` performs only a
  local `pytest --collect-only`.

## NOT-LIST scan

`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy` over `258fe2b..dfd99ef` (commit subject/body and the
diff bytes, case-sensitive): **no hits** (`CLEAR` × 4).

## STOP BEFORE PUSH

`main` is fast-forwarded **locally only**. Nothing is pushed. Both charters above require a human hash-pin
before execution.
