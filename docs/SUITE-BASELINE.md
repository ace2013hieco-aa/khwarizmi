# Suite baseline — known failures, so a new one is loud

The suite is not green on every machine. On this one, six tests fail **intermittently** during a full run
and pass when run alone — and the failing membership changes between runs (4 to 6 of them, different tests):

```text
tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
tests/test_...::test_matrix_runner_runs_clean_against_the_frozen_tree
```

They are **pre-existing**: the same set fails on the untouched main checkout, with no worktree and no
runner change. Each passes in isolation — they fail only under the full suite, which is the signature of
SQLite threading, Windows symlink privileges and shared state under contention rather than of a broken
assertion.

**They are recorded as `flaky`, not as known failures.** A known failure has to be deterministic; these are
not. The first recording put them in `known_failures`, and the very next full run — on a quiet machine —
had zero failures and reported all five as *fixed*. Then a run under load reported a different five as
*new*. Both reports were false, in opposite directions. That is what `flaky` exists for: a test that may
fail is reported, and never gates and never counts as fixed.

## Why a baseline and not "all green"

A gate that says *all green* cannot be met here. A gate that is always red teaches everyone that red is
normal — which is how a gate dies, and it is worse than no gate, because it looks like one.

So the gate is **no new failures**.

```bash
python scripts/suite_baseline.py --baseline docs/SUITE-BASELINE.json
python scripts/suite_baseline.py ... --update --note "why these are known"
python scripts/suite_baseline.py ... --allow "why this new one is intended"
python scripts/suite_baseline.py ... -- tests/test_x.py -k something
```

| exit | meaning |
|---|---|
| 0 | no failure outside the baseline |
| 1 | a failure the baseline does not know |
| 2 | the run is not evidence (missing baseline, no JUnit report, or pytest exited for a reason other than passing/failing) |

## Three outcomes, and the one that matters

- **new** — a failure the baseline does not know. **The only one that gates.**
- **flaky** — recorded as unreliable. Reported when it fails, never gating, and never reported as "fixed"
  when it passes. A flaky test in `known_failures` would make the gate cry wolf on the runs it failed and
  claim a fix on the runs it passed; both are lies, in opposite directions.
- **fixed** — a known failure that stopped failing. Reported so the baseline can shrink instead of going
  stale.

## How failures are read

From pytest's JUnit XML, not console text. A run killed mid-summary still yields a complete, structured
failure list, and a truncated log can never be mistaken for a clean one.

Two things that had to be got right, both found by running it:

- **`file` is not reliably present** in pytest's JUnit output. The first version trusted it and produced
  keys with an empty path (`::test_x`), which would have made every failure indistinguishable from every
  other test of the same name. The module is now resolved as the longest dotted prefix of `classname` that
  names a real file.
- **pytest exit codes 2–5 are not test outcomes.** `5` means "no tests collected" and comes with zero
  failures — a tool that read that as clean would pass every gate forever. Anything outside `0`/`1` is
  exit 2, "not evidence".

## What this does not do

It does not make the six failures acceptable. It records them so that a **seventh** is impossible to miss,
and so the suite can be used as a gate on a machine where it is not green.

**The queued fix is to make them deterministic** — SQLite busy-timeouts and a symlink test that tolerates
Windows privilege differences. When they are deterministic they move from `flaky` back to `known_failures`,
and when they pass they leave the file entirely. A list that never shrinks is a list that has become a
hiding place — and a `flaky` list that never shrinks is worse, because it silences a test rather than
tolerating one.

## Current state

```text
known_failures: 0
flaky:          6
```

The gate passes whether those six fail or pass. It fails only on a **seventh**.

## Self-checks

`tests/test_suite_baseline.py` — the comparison is tested directly, and the plumbing in-process with
`run_suite` monkeypatched. The first version spawned the tool from its own tests, which spawned the runner,
which ran the tests again: recursion, and under the full suite it failed for that reason rather than for a
defect. Monkeypatching also makes the failure path testable on a machine with no reliably-failing test.
