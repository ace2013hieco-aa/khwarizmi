# MERGE-LOG-DEMOS — land judge + retraction + platform demos

Verdict: **PASS** — clean FF advance through the demo stack; all three demos green on
the merged tip; scripts + docs only (no `src/` delta); full suite at its documented
pre-existing baseline (no new red). **LOCAL-ONLY — nothing pushed.**

## Topology (verified, not assumed)

| Ref | Tip | Note |
|---|---|---|
| remote `origin/main` | `218c5a5` | verified via `ls-remote`; **unmoved** after the merge |
| `merge/demo` | `218c5a5` | already contained in `origin/main` (judge + retraction) |
| `slice/platform-demo` | `673ecb1` | linear descendant of `origin/main` → FF-valid |
| **`merge/demos`** | **this commit** | FF to `673ecb1`, then this single log commit |

> The brief described `main@cdf0f69`; the *actual* remote main is `218c5a5` (the judge +
> retraction merge was already pushed). Recorded as found — the stack is linear either way.

## Advance (1)

```bash
git worktree add -b merge/demos .worktrees/merge-demos origin/main   # @ 218c5a5
git merge --ff-only merge/demo            # Already up to date (already an ancestor)
git merge --ff-only slice/platform-demo   # FF: 218c5a5 -> 673ecb1
```

FF proof: `673ecb1^ == 218c5a5` (old main). No `--no-ff`, no hash rewrite.

## Changed files (2)

`git diff --stat 218c5a5 673ecb1` — scripts + docs only; **`src/` delta empty**:

```
 docs/platform-demo/DEMO-TRANSCRIPT.txt    | 100 ++++
 docs/platform-demo/RECORDING-CHECKLIST.md | 101 ++++
 docs/platform-demo/TWO-RUN-PROOF.txt      |  30 ++
 scripts/demo_platform.py                  | 797 ++++++++++++++++++++++++++++++
 4 files changed, 1028 insertions(+)
```

(The judge + retraction demo files were already on `origin/main` via `merge/demo`.)

## Demos on the merged tip (3) — `PYTHONUTF8=1`, `PYTHONPATH=<worktree>/src`

| Demo | Command | Result | Digest |
|---|---|---|---|
| judge | `scripts/demo_judge.py` | **51/51**, exit 0 | `7149f708ff1aae3b3927fa55ce05341128115d9009bb37be8d407550c4a2d446` |
| retraction | `scripts/demo_retraction_cone.py` | **40/40**, exit 0 | (check ledger only) |
| platform | `scripts/demo_platform.py` | **35/35**, exit 0 | `e79059828c823ae55bee7c5131eff9b0d16fbae6c40aa20c9ff6c4feea415914` |

The judge and platform digests are **path-scoped** (each prints its own resolved
`hermes.__file__`, `…\.worktrees\merge-demos\src\hermes\__init__.py`), so on this worktree
they differ from the single-line values (`f360c174…` / `c5c13934…`) only by the checkout
directory name — 51/51 and 35/35 hold in both.

### Digest caveat (reported, not fixed)

`scripts/demo_judge.py`'s replay digest is **duration-sensitive across the 60-second
boundary**. When the closed-loop pytest leg runs ≥ 60 s, pytest appends a `(0:MM:SS)`
suffix (`… 6 passed in 111.58s (0:01:51) …`); the demo's mask set at
`scripts/demo_judge.py:647-648` covers `\d+\.\d+s` but **not** that suffix, so the suffix
(and its varying value) leaks into the digest. Observed: fast runs reproduce
`7149f708…`; a slow run produced `34bcc306…` then `7a48f733…` (each 51/51, exit 0).
This is **not** a merge effect: `scripts/demo_judge.py` is byte-identical
(`bd7aebbe…`) at `677b470`, `218c5a5`, `673ecb1` and this commit, and `673ecb1 → this
commit` changes only this log file. The demo is green either way; the digest simply is
not duration-independent for slow legs. Not fixed (merge + verify only).

## Gates

- `ruff check src tests` → **All checks passed**.
- `ruff check scripts/demo_judge.py scripts/demo_retraction_cone.py scripts/demo_platform.py tests/test_retraction_demo.py`
  → **1 pre-existing BLE001** at `scripts/demo_retraction_cone.py:587`
  (`except BaseException:` without `# noqa`) — the retraction line's own committed byte;
  `scripts/` is outside the CI lint scope (`uvx ruff check src tests`).
- Full suite (`scripts/run_tests.py`, `PYTHONPATH=<worktree>/src`) → **exit 1**;
  `5 failed, 4351 passed, 3 skipped, 1 warning in 613.44s`.

The 5 are **exactly** the documented pre-existing environmental reds (no new red):

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

`MERGE-LOG-STATE-ENTRY.md` records the identical set and counts (5 failed / 4349 passed /
3 skipped) and classifies them as environmental (concurrency races plus a Windows
symlink-privilege refusal). The +2 passed is exactly the 2 tests the demo merge added.
**Red set == documented set (exact). No new red → no stop condition.**

## STOP BEFORE PUSH

`merge/demos` is local-only; `origin/main` verified unmoved at
`218c5a5a9717063c4c87780048c2642bed1a1b2d`; no push performed.
