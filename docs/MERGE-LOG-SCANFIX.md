# MERGE-LOG-SCANFIX — integration of the notes-dedup + fence-classifier lines onto `main`

Merge integrator record for the two scan-hardening lines: FIX-NOTES-DEDUP
(`fix/notes-dedup@9630856`) and FIX-FENCE-CLASSIFIER
(`fix/fence-classifier@6d6a194`). Follows the `MERGE-LOG-P-AUTO-1` /
`MERGE-LOG-FETCH` pattern.

**Outcome: both lines were integrated and verified on `merge/scanfix` and the
delta audit returned PASS (`docs/MERGE-AUDIT-SCANFIX.md`). `main` was NOT
advanced and NOT pushed — D9 is lapsed and this task is merge + audit only.**

## Inputs

| Input | Value |
| --- | --- |
| Repository | `D:\New folder\research-agent` (`ace2013hieco-aa/khwarizmi-research`) |
| `main` at task start (local) | `6a5b69f3f0662411abcae9b5ec74aed9aa0cd3a1` |
| `main` at task start (remote) | `6a5b69f3f0662411abcae9b5ec74aed9aa0cd3a1` (`git ls-remote origin refs/heads/main` — pasted) |
| `fix/notes-dedup` tip | `96308567714f52407a7ecb3c65612e9d495c2109` (2 files, note-emission only) |
| `fix/fence-classifier` tip | `6d6a194589468e07cba8194b1017cd8b263c20e5` (3 files, fence semantics widened only; owning gate DG-4 §14 re-run green) |
| Human approval banked | none — **D9 lapsed; no push under any circumstance** |

Both tips branch directly off `main` (`git merge-base main <tip>` =
`6a5b69f…` for both). `main` was verified unmoved before and after.

## Merge hashes

| Ref | Hash |
| --- | --- |
| `merge-base main HEAD` | `6a5b69f3f0662411abcae9b5ec74aed9aa0cd3a1` (== `main`) |
| `merge/scanfix` entry tip | `6a5b69f…` (created via `git worktree add -b merge/scanfix scanfix-merge-wt main`) |
| merge 1 — notes-dedup | `1255e32481d324fd7179b2eef052c2ba89173106` |
| merge 2 — fence-classifier (integration tip) | `6f186d97bafa9669b118a8cdc1861dea96d7ae95` |
| `main` old → new | `6a5b69f…` → **unchanged** |

## Lines integrated (4 commits, `6a5b69f..6f186d9`)

| Commit | Subject |
| --- | --- |
| `9630856` | fix(notes-dedup): route per-tick note appends through `_note_once` with stable condition keys |
| `6d6a194` | fix(fence-classifier): literal/comment-aware fail-closed scan + DDL/PRAGMA fencing |
| `1255e32` | merge(notes-dedup): integrate `fix/notes-dedup` tip `9630856` into `merge/scanfix` (local-only) |
| `6f186d9` | merge(fence-classifier): integrate `fix/fence-classifier` tip `6d6a194` into `merge/scanfix` (local-only) |

Diffstat `main..6f186d9` — 4 files, 821 insertions, 77 deletions
(`git diff --numstat main..HEAD`):

```
18/6    src/hermes/persistence/database.py
297/71  src/hermes/research/controller.py   (both lines)
286/0   tests/test_fence_classifier.py
220/0   tests/test_notes_dedup.py
```

No file outside the two lines' declared sets; 821/77 equals notes (261/22) +
fence (560/55) exactly.

## Conflicts and resolutions — zero conflicts, hunk-disjoint

Both lines edit `src/hermes/research/controller.py`, in different regions as
predicted — verified, not assumed: the fence line's single contiguous hunk
occupies new lines **134–409** (`_FencedConnection`); the notes line's eight
hunks land at **757, 1605, 2220, 4244, 4272, 4288, 4304, 4685** — disjoint by
more than 340 lines. Git: `Auto-merging src/hermes/research/controller.py` →
`Merge made by the 'ort' strategy` for both merges, **zero conflicts**. No
conflict markers anywhere (`grep -rn "^<<<<<<<\|^>>>>>>>\|^=======$" src tests`
→ none), and **no src change was authored by the integrator**.

### Integrity invariants

| # | Claim | Command | Result |
| --- | --- | --- | --- |
| INV1 | merged tip vs fence tip is exactly the notes patch | `git diff --stat fix/fence-classifier HEAD` | 2 files, 261 insertions, 22 deletions — the notes commit's stat, exactly |
| INV2 | merged tip vs notes tip is exactly the fence patch | `git diff --stat fix/notes-dedup HEAD` | 3 files, 560 insertions, 55 deletions — the fence commit's stat, exactly |
| INV3 | fence merge's own delta vs first parent == fence patch | `git diff --stat HEAD^1 HEAD` | 3 files, 560/55 |
| INV4 | fence merge's own delta vs second parent == notes patch | `git diff --stat HEAD^2 HEAD` | 2 files, 261/22 |
| INV5 | no conflict markers | `grep -rn …` | NONE |
| INV6 | merge 2 parents | `git rev-list --parents -n 1 HEAD` | `6f186d9 1255e32 6d6a194` |
| INV7 | docs commits leave src+tests byte-identical | `git diff --exit-code 6f186d9 HEAD -- src tests` | exit 0 (docs-only commits listed above the audited tip) |

Disclosure: git reported `failed to delete
'D:/New folder/research-agent/.git/worktrees/step-4': Permission denied`
while pruning a stale, pre-existing worktree admin directory unrelated to
this integration. HEAD was verified correct after each operation; the
directory was left in place. Same pre-existing condition disclosed by the
`MERGE-LOG-P-AUTO-1` record.

## Gate results (measured on integration tip `6f186d9`)

Run in the isolated worktree `scanfix-merge-wt` (cwd = worktree,
`PYTHONPATH=<worktree>/src`), the shared venv reached through a gitignored
`.venv` junction; import proven per run (`hermes ->
D:\New folder\research-agent\scanfix-merge-wt\src\hermes\__init__.py`).

| Gate | Command | Result |
| --- | --- | --- |
| Full suite (DG-4 §16 named command) | `.venv/Scripts/python.exe scripts/run_tests.py -q` | **exit 0**, `[100%]`, **2566** test dots, zero `F`/`E` markers |
| Refusal re-scan | `pytest tests/test_fence_classifier.py tests/test_notes_dedup.py` | **57 passed in 1.25s** |
| Lint | `.venv/Scripts/ruff.exe check src tests` | `All checks passed!` — exit 0 |
| Types (src, strict) | `.venv/Scripts/pyright.exe --pythonpath <abs worktree venv python> src` | `0 errors, 0 warnings, 0 informations` |
| Types (tests) | same `--pythonpath`, `--project pyrightconfig.tests.json` | `0 errors, 1 warning` — pre-existing `tests/test_research_program.py:144` `reportSelfClsParameterName` |
| Census | `.venv/Scripts/python.exe scripts/check_census.py` | `PASS` — 121/18/5/4/27/1/15/0 reproduced exactly |

## Count lineage `2509 → 2512 / 2563 → 2566`

| Figure | Derivation |
| --- | --- |
| 2509 | `main` baseline = fence tip 2563 − 54 new fence tests (derived; not re-run here) |
| 2512 | notes tip = 2509 + 3 (reported by the FIX-NOTES-DEDUP owning task) |
| 2563 | fence tip = 2509 + 54 (reported by the FIX-FENCE-CLASSIFIER owning task) |
| **2566** | merged tip = 2509 + 54 + 3 — **measured here**, exit 0, `[100%]` |
| **57** | targeted at merged tip = 54 + 3 — measured here |

Census lineage: the certified figures (121 calls / 18 persistence / 5 gateway
/ 4 Controller / 27 owners / 1 rollback-only / 15 persistence→research) are
reproduced exactly at the merged tip — the fence line's `database.py` edit is
census-neutral by construction (same single BEGIN + ROLLBACK call sites) and
the notes line touches no transaction control.

## Owning gate

DG-4 §14 lease / single writer (line 660), PROTECTED under DG-6 (line 109),
`docs/archive/HERMES_DG4_REPOSITORY_STRUCTURAL_DESIGN_GATE_2026-09-21.md`.
The DG-4 §16 named gate command (line 959) is the full suite above; re-run
green at the merged tip.

## Disposition

Integration verified; delta audit verdict **PASS**
(`docs/MERGE-AUDIT-SCANFIX.md`). `main` was **not** advanced and **not**
pushed; `merge/scanfix` is **absent from the remote** (`git ls-remote origin
'refs/heads/merge/scanfix'` → empty). The push decision is the director's, on
a fresh D9.
