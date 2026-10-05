# MERGE-LOG-FETCH — integration of the P-AUTO-3-FIX + H2 acquisition lines onto `main`

Merge integrator record for the P-AUTO-3 live-fetch fix line
(`slice/p-auto-3-fetch` → `fix/p-auto-3-redirect`) and the H2 acquisition
promotion (`h2-acquisition`). Follows the `MERGE-LOG-P-AUTO-1` /
`MERGE-LOG-045-FIXLINE` pattern.

**Outcome: both lines were integrated and verified on `merge/fetch`
(tip `8acb887`, two merge commits), but the delta merge-audit returned
FAIL on one MUST-FIX (M1 — the H2 controller docling wiring cannot admit).
`main` was NOT advanced and NOT pushed; D9 lapsed with the last landing and
this charter covers merge + audit only.** See `docs/MERGE-AUDIT-FETCH.md`.

## Inputs

| Input | Value |
| --- | --- |
| Repository | `D:\New folder\research-agent` (`ace2013hieco-aa/khwarizmi-research`) |
| `main` at task start (local) | `e5f06a72370ed4af02903b6504bad6c848c1fc4a` |
| `main` at task start (remote, `git ls-remote origin refs/heads/main`) | `e5f06a72370ed4af02903b6504bad6c848c1fc4a` |
| P-AUTO-3 line (3 commits) | `0298b4e` (slice) → `c066a72` (audit records) → `bf7c34f` (fix), tip `fix/p-auto-3-redirect@bf7c34f2aaebc6f7fc7e5965c97923e82db7d84e` |
| H2 tip | `h2-acquisition@8de7f22298674300c58dbe0744a9f1652b541534` |
| Prior audits (input only) | `audits/AUDIT-P-AUTO-3-REDTEAM.md`, `audits/AUDIT-H2-REDTEAM.md` (recorded on the line at `c066a72`) |
| Human approval banked | **NONE ACTIVE — D9 LAPSED** with the last landing; merge + audit only, no push |

`main` was verified unmoved (local == remote) before the merge and again at
the close of the task, so the "main moved under you" STOP condition did not
fire.

## Merge hashes

| Ref | Hash |
| --- | --- |
| `merge-base main bf7c34f` | `e5f06a72370ed4af02903b6504bad6c848c1fc4a` (== `main`) |
| `merge-base main 8de7f22` | `e5f06a72370ed4af02903b6504bad6c848c1fc4a` (== `main`) |
| `merge/fetch` base | `e5f06a72370ed4af02903b6504bad6c848c1fc4a` |
| M1 — P-AUTO-3 leg | `670e6433cf54ce130540ab01a2d654e52c2d9549`, parents `e5f06a7` + `bf7c34f` |
| M2 — H2 leg, branch tip | `8acb8876beb8608a1783927d908bf58e12577569`, parents `670e643` + `8de7f22` |
| `main` old → new | `e5f06a7` → **unchanged** `e5f06a7` |

Both merges were `--no-ff` so every input hash survives as a merge parent
("merge commit preserving hashes", per the P-AUTO-1-RETRY precedent).

## Lines integrated

P-AUTO-3 line (`e5f06a7..bf7c34f`, diffstat **17 files, +2070/−22**):

| Commit | Subject |
| --- | --- |
| `0298b4e` | feat(p-auto-3): wire live keyless fetch path for OpenAlex + PubMed (D5) |
| `c066a72` | docs(audit): record P-AUTO-3 + H2 redteam reports verbatim with director notes |
| `bf7c34f` | fix(p-auto-3): A redirect re-vet + C parser v2 + D overall deadline + E limiter test |

The fix commit is the widened footprint the audit scans:
`0298b4e..bf7c34f` — **13 files, +1033/−42** (8 src/test files, 1 fixture
edit, 1 new fixture, the audit records).

H2 (`e5f06a7..8de7f22`, diffstat **45 files, +51073/−43**): promotion of the
S1 docling / S2 crawl4ai spikes with pinned extras, fixtures, and the
controller EXTRACT wiring (`8de7f22`).

## Conflicts and resolutions

**Zero conflicts.** A `git merge-tree --write-tree bf7c34f 8de7f22`
pre-check predicted a clean union, and both merges landed cleanly:

- M1 was a descendant merge (`bf7c34f` is a child of `main`), `--no-ff`;
  git's own diffstat equals `main..bf7c34f` exactly.
- M2 reported `Auto-merging pyproject.toml` only. The two pyproject hunks
  are non-overlapping (`[project.optional-dependencies]` extras vs the
  `[tool.pytest.ini_options]` marker list), so `ort` mechanically kept
  **both**: `docling = ["docling==2.131.0"]`,
  `crawl4ai = ["crawl4ai==0.9.4"]` and the `live_fetch` marker.

No manual conflict repair was needed and **no src changes were made by the
integrator** — proven by the invariants in `MERGE-AUDIT-FETCH.md`
(`git diff --exit-code bf7c34f M1 -- src tests` empty; M2's src+tests delta
vs each parent is exactly the other line's file list).

Disclosure: during both merges git reported
`error: failed to delete 'D:/New folder/research-agent/.git/worktrees/step-4': Permission denied`
while pruning a **stale, pre-existing** worktree admin directory unrelated
to this line (same disclosure as the P-AUTO-1 and P-AUTO-1-RETRY records).
Both merges landed correctly with the expected parents; the directory was
left in place, not force-removed.

## Gate results (on the merged tree, tip M2 `8acb887`; all re-run by this task)

Run in the isolated worktree `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\mergefetch`
with the shared venv interpreter, cwd = worktree, `PYTHONPATH=<worktree>/src`,
and the import proven per run (`hermes.__file__` resolves inside the
worktree).

| Gate | Command | Result |
| --- | --- | --- |
| Full suite | `PYTHONDONTWRITEBYTECODE=1 HERMES_SKIP_LIVE_FETCH=1 PYTHONPATH=<wt>/src .venv/Scripts/python.exe scripts/run_tests.py -v -p no:cacheprovider` | `2499 passed, 4 skipped, 13 warnings in 555.48s (0:09:15)` — exit 0 |
| Lint (C3) | `uvx ruff check src tests` | `All checks passed!` — exit 0 |
| Types (src, strict) | `PYTHONPATH=<wt>/src uvx pyright src` | `0 errors, 0 warnings, 0 informations` — exit 0 |
| Types (tests) | `PYTHONPATH=<wt>/src uvx pyright --pythonpath "D:/New folder/research-agent/.venv/Scripts/python.exe" --project pyrightconfig.tests.json` | `0 errors, 1 warning, 0 informations` — exit 0 (pre-existing `tests/test_research_program.py:144:23`, `reportSelfClsParameterName`) |

The 4 skips are the live-egress tests under `HERMES_SKIP_LIVE_FETCH=1`
(2 at `tests/test_p_auto_3_live_fetch.py:776`, 2 at `:815`, reason "live
network unavailable (or skipped by env)"). The suite was run **alone**, per
the P-AUTO-1-RETRY lesson; no static gate ran concurrently.

Suite header, verbatim: `platform win32 -- Python 3.14.1, pytest-9.1.1,
pluggy-1.6.0`.

### Count lineage `2325 → 2358 → 2470 → 2503` (independently re-derived)

| Figure | Derivation |
| --- | --- |
| 2325 | `main@e5f06a7` collected total (reproduced: `72 files, total 2325`) |
| **2358** | `bf7c34f` = 2325 + 33; the live-fetch test file collects 23 at `0298b4e` and **33** at `bf7c34f` (measured) |
| 2470 | `8de7f22` = 2325 + 145 (S1 docling 50 + crawl4ai 47 + egress 48); the H2 audit's `2399` was against its then-baseline 2304 — re-derived here against current `main` |
| **2503** | `merge/fetch@M2` = 2325 + 33 + 145 = **2503** collected (`76 files`) |

Raw collection lines: `tree-main total_collected=2325`,
`tip-pauto total_collected=2358`, `tip-h2 total_collected=2470`,
`mergefetch total_collected=2503`. The suite's `2499 passed + 4 skipped`
sums to 2503 exactly; no test was deleted or skipped to reach green
(`git diff --diff-filter=D` vs both parents is empty and the full parent
file union is present at M2).

## S4-condition survival (NOTICE + pins post-merge)

| Condition | Post-merge state |
| --- | --- |
| `NOTICE` | present, byte-identical to `8de7f22` — `This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai).` |
| Extras pins | `pyproject.toml` parses (`tomllib`); `optional-dependencies = {docling = ["docling==2.131.0"], crawl4ai = ["crawl4ai==0.9.4"]}` |
| `live_fetch` marker | present in `[tool.pytest.ini_options] markers` |
| `uv.lock` | carried from `8de7f22` (byte-identical at M2; the P-AUTO-3 line never touched it) |

## Audit disposition

The delta merge-audit (`docs/MERGE-AUDIT-FETCH.md`) found:

- widened P-AUTO-3-FIX footprint: **no certified-path behavior change**
  (hunk inventory + seam-only test diff + 147-test and 38-test A/B legs
  green on both src trees) — no MUST-FIX;
- H2 controller-wiring A/B: **MUST-FIX M1** — the docling branch of
  `controller._span_resolve` can never return True (proof and raw outcomes
  in the audit doc), so the promoted S1 wiring is inert as shipped;
- S4 survival and count lineage: **PASS**, as above.

## Post-merge integrity checks

- `main` local == `main` remote == `e5f06a72370ed4af02903b6504bad6c848c1fc4a`
  at the close of the task — **not advanced**.
- **No `git push` of any ref was performed**; D9 is lapsed and the audit
  verdict is FAIL, so there was no push decision to exercise.
- All work confined to the isolated worktree; the shared checkout
  `D:/New folder/research-agent` stayed on `audit/p-auto-3-redteam` with its
  own staged state, unmodified. Other branches/worktrees were read via
  `git show`/`git diff`/`git archive` only.
- Worktree `git status --porcelain --untracked-files=all` empty apart from
  the two docs committed here; gate/probe logs stayed under
  `/tmp/fetch-audit/` and were never staged.
- Only the two deliverable docs are added by this record's commits — one
  concern per commit, no src changes, no unrelated files.

## Verdict

**Integrated and verified; NOT merged and not pushable.** `merge/fetch`
carries both lines unchanged (M1/M2 as above) plus these two docs.
`main` remains at `e5f06a7`. The merge-audit FAIL on MUST-FIX M1 (H2
controller wiring inert) blocks a push decision; because the fix requires a
src change the charter forbids on this branch, M1 is handed back for a
follow-up line. The STOP condition "audit FAIL — report, do not fix" was
honored, as was STOP BEFORE PUSH.
