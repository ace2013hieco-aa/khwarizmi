# MERGE-LOG-STATE-ENTRY — STATE.md platform entry + B4 regen onto current main

**Task:** MERGE-STATE-ENTRY. **Role:** merge integrator (advance, verify). **D9 LAPSED — merge + verify only.**
**Verdict:** **PASS.** Linear FF advance verified; B4 green; edge sets invariant; ruff clean; the full
suite's red set is **exactly** the documented pre-existing set (no new red). Local-only, **nothing pushed**.

## 1. Lineage

| Item | Value |
| --- | --- |
| Repo | `D:\New folder\research-agent` |
| BASE — remote main (verified unmoved) | `5665b7d1fd10ea79662adc96dc2a7a4f2ee0b347` |
| Source branch | `fix/state-platform-entry` @ `99268956a597ccbf4a8ba6e6cbe1535ca820468f` |
| Integration branch | `merge/state-entry` @ `9926895` (**FF of the source tip**) |
| Worktree | `D:\New folder\merge-state-entry-wt` (clean) |
| Pushed? | **NO** — `git ls-remote origin refs/heads/merge/state-entry` → 0 lines |

**Topology verified, not assumed.** `git merge-base --is-ancestor 5665b7d 9926895` → **TRUE**;
`git merge-base 5665b7d 9926895` = `5665b7d`; `git rev-list --count 5665b7d..9926895` = **1**. The
advance was performed with `git merge --ff-only 9926895`, not a branch reset, so the worktree and
index followed the move (post-advance `git status --short` → clean).

## 2. Changed files (8, +23 / −3 — as specified by the input)

```
M docs/STATE.md                                              +11
A docs/gr3-b4/b4-fixtures/06dea9dbe4370c0ba733f02035049be7fb36ec40e0d3d98d76195772bc7fcfb7.json   +1
D docs/gr3-b4/b4-fixtures/232fd00e97ba2a0c0d358d80905567d75b3dab728c35be6988d0aa7e8eee04f3.json   -1
A docs/gr3-b4/b4-fixtures/550fcc009fa9f1541eb5c39db3f4c1b255995e5e61136ec7ec597984d5aa5fd8.json   +1
D docs/gr3-b4/b4-fixtures/7ed0612ea0c615d12071b3b23c6805ecb89d51a622ce8e507a5e047f205a338d.json   -1
D docs/gr3-b4/b4-fixtures/948a0d8876b9d70e2064f178f81a024be3a86e5ff36dcd90d8c3a3bde4a522ca.json   -1
M docs/gr3-b4/b4-fixtures/README.md                           +9
A docs/gr3-b4/b4-fixtures/d1312f0163df58370ee3fdf29b1744fe63e8af25fa71e3ca1a1caefa2264fdbf.json   +1
```

`grep -vE '\.(md|json)$'` over the changed set → **NONE**: md + json only, no `src/` change.
Git reports the fixture moves as `A`/`D` pairs rather than `R` because the one-line content-addressed
JSONs differ too much for rename detection — semantically they are renames (old name removed, new
name added, body re-pinned).

## 3. Gates at the merged tip

### 3.1 B4 — PASS

```
tests/test_b4_ref_graphs.py -> 24 passed in 114.81s   (exit 0)
```

(Before the regen ceremony the same suite was `9 failed, 15 passed`; the ceremony is what makes it
green — recorded in the source branch's README note.)

### 3.2 Edge-set invariance — PASS (set equality, not just counts)

Re-derived at the merged tip against remote main `5665b7d`, comparing the **edge sets** themselves
(normalised `{src,dst}` tuples), not only their cardinality:

```
232fd00e -> 06dea9db | edges 19 -> 19 | edge-set IDENTICAL: True | sources 12 -> 12 | skipped 24 -> 26
7ed0612e -> d1312f01 | edges  5 ->  5 | edge-set IDENTICAL: True | sources  4 ->  4 | skipped 14 -> 16
948a0d88 -> 550fcc00 | edges  5 ->  5 | edge-set IDENTICAL: True | sources  6 ->  6 | skipped 17 -> 19

ALL EDGE SETS INVARIANT: True
```

Edge sets remain **5 / 19 / 10 / 5**; `sources` counts are unchanged (4 / 12 / 6 / 8). Only
`counts.skipped` grows **+2** per affected fixture — the newly cited `IDR-046` / `ARCHITECTURE_DELTA`
tokens from the added STATE.md paragraph. **No edge-set mismatch** → no stop condition.

`b4-c3` (`eef419463e5201c4…`, the IDR-only stratum) is **untouched** — identical blob in the tip and
in main: `2e6becde4b36c7273d602075162cdcea03fff51d`.

### 3.3 ruff — PASS

```
$ ruff check src tests
All checks passed!   (exit 0)
```

### 3.4 Full suite — red set ⊆ documented set (exact equality)

```
5 failed, 4349 passed, 3 skipped, 1 warning in 690.95s (0:11:30)
EXIT=1
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

Set comparison against the documented pre-existing reds:

```
expected: 5 | actual: 5
NEW reds (actual - expected)          -> (empty)
reds not reproduced (expected - actual) -> (empty)
RED SET == DOCUMENTED SET (exact)
```

Counts are identical to every prior run at `main` (5 failed / 4349 passed / 3 skipped). The five are
the known environmental failures (concurrency races plus a Windows symlink-privilege refusal), none
touching `docs/STATE.md`, the fixtures, or the corpus; they were previously shown to fail identically
on a clean baseline. **No new red → no stop condition.** The suite does not exit 0 in this
environment; that is a pre-existing condition, not attributable to this change (zero delta).

## 4. State left behind

- `merge/state-entry` = `9926895` + this log commit; no `src/` changes; worktree clean; **nothing pushed**.
- Remote main verified unmoved: `5665b7d1fd10ea79662adc96dc2a7a4f2ee0b347`.
- Dev checkout HEAD unchanged at `1918dad` (`audit/r1-manifest`). No branch, tag, or ref moved.

## 5. Remote verification

```
$ git ls-remote origin refs/heads/main
5665b7d1fd10ea79662adc96dc2a7a4f2ee0b347	refs/heads/main
$ git ls-remote origin refs/heads/merge/state-entry | wc -l
0
```

**Verdict: PASS — FF advance verified, B4 24/24, edge sets invariant, ruff clean, suite reds exactly
the documented five. STOP BEFORE PUSH reached; no push performed.**
