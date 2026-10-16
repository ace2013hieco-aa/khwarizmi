# LOOP-4-ANCHOR-FIX — the deadline anchor (audit M1) and the E3 pins (audit M2)

## Provenance

| Item | Value |
| --- | --- |
| Task | LOOP-4-FIX (fixer — close the LOOP-4 redteam audit's two MUST-FIXes) |
| Slice under fix | `slice/loop-4-hygiene@62b40af` |
| Audit of record | `audit/loop-4-redteam@11a78b5` — `AUDIT-LOOP-4-REDTEAM.md` (FAIL: M1 + M2) |
| Branch | `fix/loop-4-anchor` (local-only, **no push**) |
| Worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/loop-4-fix-wt` |
| Commits | `aa12dd2` (anchor, M1) · `d2ce3f6` (pins, M2) · this record |

Changed files (5): `src/hermes/agents/runtime/{run,supervisor,types}.py`,
`tests/test_loop4_hygiene.py`, `docs/LOOP-4-HYGIENE.md` (the slice record's E3
row, corrected) — plus this record. **Spine diff 0**, no certified
writer/validator/gate touched, no `archive/`/`AGENTS.md`/`ARCHITECTURE.md`/
`STATE.md`/`API.md`/`docs/gr3-b4/` edit.

Everything the audit left standing (E2, E5, E6, E7, E8, G8 — 45/45 legs) stands
untouched; the anchor change is confined to how a run's bound is *carried*.

## M1 — the deadline anchor (absolute, set once)

**The defect.** The checkpoint carried a *remaining duration*
(`deadline_remaining_seconds`), re-recorded on every entry to `_run_spec` —
including a resume. The opening checkpoint is written before the first tick, so
it re-derived that duration against its own start; a run that crashed before
completing a tick therefore re-recorded the same duration and was handed the full
declared bound on every resume. Driven live, the bound never shrank and the run
was unbounded.

**The fix.** The checkpoint carries the run's deadline as an *absolute* monotonic
instant, `Checkpoint.deadline_mono`, set once when the run first resolves its
bound and re-recorded unchanged on every later entry. `resume` re-enters with
that same instant; `remaining = deadline_mono - now` shrinks on each resume, and
an anchor at or before `now` resumes already-expired (the first supervisor check
reports `TIMEOUT`, so the run fails closed without spending a model call). The
opening checkpoint can no longer extend the anchor.

**Monotonic only.** No wall-clock reading enters the deadline math (a wall-clock
term here would be a MUST-STOP finding, and there is none). The instant is
process-local — which is this plane's own scope, since its recovery is
process-local and derived (`supervisor.py`); the docstrings now state that limit
rather than claiming the relative carry crossed processes.

### Probe — the auditor's crash-before-progress resume loop, re-driven

Each attempt crashes *inside* tick 1, so the last checkpoint is always the
opening one. Same probe against both trees (`HERMES_SRC` selects the tree),
declared bound **100.0 s**, 10 s burnt per attempt.

**Before — `slice/loop-4-hygiene@62b40af`** (the auditor's M1, reproduced):

```
attempt    mono           carried  remaining calls  outcome
      0    10.0        left=100.0      100.0     1  crashed in tick 1
      1    20.0        left=100.0      100.0     1  crashed in tick 1
      2    30.0        left=100.0      100.0     1  crashed in tick 1
      3    40.0        left=100.0      100.0     1  crashed in tick 1
      4    50.0        left=100.0      100.0     1  crashed in tick 1
      5    60.0        left=100.0      100.0     1  crashed in tick 1
      6    70.0        left=100.0      100.0     1  crashed in tick 1
      7    80.0        left=100.0      100.0     1  crashed in tick 1
      8    90.0        left=100.0      100.0     1  crashed in tick 1
      9   100.0        left=100.0      100.0     1  crashed in tick 1
     10   110.0        left=100.0      100.0     1  crashed in tick 1
     11   120.0        left=100.0      100.0     1  crashed in tick 1
expired observed: False
```

**After — `fix/loop-4-anchor`** (anchor fixed at 100.0, remaining strictly
decreasing, expiry fail-closed):

```
attempt    mono           carried  remaining calls  outcome
      0    10.0      anchor=100.0       90.0     1  crashed in tick 1
      1    20.0      anchor=100.0       80.0     1  crashed in tick 1
      2    30.0      anchor=100.0       70.0     1  crashed in tick 1
      3    40.0      anchor=100.0       60.0     1  crashed in tick 1
      4    50.0      anchor=100.0       50.0     1  crashed in tick 1
      5    60.0      anchor=100.0       40.0     1  crashed in tick 1
      6    70.0      anchor=100.0       30.0     1  crashed in tick 1
      7    80.0      anchor=100.0       20.0     1  crashed in tick 1
      8    90.0      anchor=100.0       10.0     1  crashed in tick 1
      9   100.0      anchor=100.0        0.0     1  crashed in tick 1
     10   100.0      anchor=100.0        0.0     0  resume -> state=FAILED termination=TIMEOUT
     11   100.0      anchor=100.0        0.0     0  resume -> state=FAILED termination=TIMEOUT
expired observed: True
```

100.0 → strictly decreasing → expired, with the anchor never moving. The resumed
run at expiry makes **0** model calls and reports `TIMEOUT`/`FAILED`: bounded,
and failing closed.

## M2 — the E3 pins now pin the carry

**The defect.** Both E3 pins passed with the carry neutralised, so they pinned
E2's terminal check rather than the carry: `_run_deadline` silently fell back to
the declared bound, and `_close`'s new check turned the terminal state into
`TIMEOUT` either way. One pin's docstring also asserted a counterfactual the code
falsified ("would have ended on its tick limit").

**The fix.** Both pins assert the work *not* done — the only thing that
distinguishes a carried bound from a freshly minted one:

* `test_the_opening_checkpoint_does_not_extend_the_runs_deadline_anchor` (was
  `..._records_what_was_left_of_the_runs_deadline`) — the resume's *opening*
  checkpoint carries the same absolute instant as the run's first checkpoint
  after downtime elapsed: **100.0**, where a re-based bound would read **125.0**.
* `test_a_resume_continues_the_runs_deadline_and_never_re_grants_it` — the
  resumed run makes exactly **one** model call and stops at mono **115**; a fresh
  bound would allow a second call and reach mono **210**. Its docstring now
  states the real counterfactual.

### Probe — neutralisation, both directions (source-level reverts, then restored)

```
--- unmodified — pins must PASS ---
..                                                                       [100%]
2 passed, 11 deselected in 0.31s

--- carry neutralised (resume mints a fresh bound) — must FAIL ---
tests\test_loop4_hygiene.py:370: AssertionError
FAILED tests/test_loop4_hygiene.py::test_the_opening_checkpoint_does_not_extend_the_runs_deadline_anchor
FAILED tests/test_loop4_hygiene.py::test_a_resume_continues_the_runs_deadline_and_never_re_grants_it
2 failed, 11 deselected in 0.37s

--- E2 neutralised (_close ignores the deadline) — must PASS ---
..                                                                       [100%]
2 passed, 11 deselected in 0.32s

tree restored clean: True
```

*Carry neutralised* = `resume` re-enters with `deadline=None` (the anchor is
discarded; `_run_deadline` falls back to the declared bound). *E2 neutralised* =
`_close`'s two supervisor checks stop observing the deadline (the pre-E2
behaviour), nothing else changed. **Both directions hold**: the pins fail without
the carry and pass without E2's check — they test E3, not E2.

## The rest of the LOOP-4 battery is untouched

Only the two E3 pins moved. Every other pin is byte-identical to the slice and
green:

```
IDENTICAL  test_a_deadline_that_expires_during_the_terminal_act_times_the_run_out   (E2)
IDENTICAL  test_a_retry_is_asked_with_the_refusal_that_ended_the_previous_attempt   (E5)
IDENTICAL  test_the_retry_sleep_never_crosses_the_runs_deadline                     (E5)
IDENTICAL  test_the_termination_vocabulary_holds_no_dead_member                     (E6)
IDENTICAL  test_a_malformed_tool_call_is_refused_and_the_tick_carries_on            (E7)
IDENTICAL  test_a_capability_the_plane_invoked_and_that_failed_still_stops_the_run  (E7)
IDENTICAL  test_a_capability_refusal_from_the_plane_still_stops_the_run             (E7)
IDENTICAL  test_a_draft_carries_the_evidence_it_was_drafted_on                      (E8)
IDENTICAL  test_the_deadline_is_observed_mid_batch_not_only_at_the_tick             (G8)
IDENTICAL  test_a_zero_limit_defers_to_the_profile_rather_than_disabling            (G8)
IDENTICAL  test_converged_novelty_is_read_before_the_seen_set_absorbs_it            (G8)
```

The test file's diff against `62b40af` is four hunks: the module table, the E3
block, and one `def` rename — nothing else. The battery is **13/13** and the
runtime-adjacent batteries (`test_agent_runtime`, `test_loop2_feedback`,
`test_loop3_review_rounds`, `test_wiring_w2`) are **256 passed**.

## Count — unchanged (no test added or removed)

The two E3 pins were rewritten in place; the battery is still 13 tests, so the
stamp is **not** moved.

```
collect            : 4655 tests collected in 6.61s
stamp --check      : OK: docs\SUITE-COUNT.md collected=4655 matches the live collect   (exit 0)
check_census       : PASS - every certified figure is reproduced exactly.              (exit 0)
B4                 : git diff 62b40af HEAD -- docs/gr3-b4/ -> 0 lines (byte-identical); 24 passed
```

## Gates (raw, `PYTHONPATH=<wt>/src`, no extra `-q`)

Interpreter: `D:/New folder/research-agent/.venv/Scripts/python.exe` (Python 3.14.1,
pytest 9.1.1). Note: `--pythonpath` is an *ini* option in this pytest, not a CLI
flag, so the tree is put on the path with `PYTHONPATH=<wt>/src`, exactly as the
slice record does.

```
ruff (src tests)   : All checks passed!                                                (exit 0)
pyright src        : 0 errors, 0 warnings, 0 informations                              (exit 0)
pyright tests-cfg  : 0 *type* errors; 116 reportMissingImports (pytest resolution) + 1
                     pre-existing warning — the worktree has no configured interpreter
                     for pyright to resolve `pytest` from, so every `import pytest`
                     reports missing; no error is in this diff
LOOP-4 battery     : 13 passed in 0.82s
B4                 : 24 passed in 3.80s
loop2 + loop3      : 32 passed in 0.51s
runtime batteries  : 256 passed in 7.33s
spine diff         : git diff 62b40af HEAD -- src/ ':!src/hermes/agents/runtime/' -> 0 lines
```

FULL suite (`scripts/run_tests.py`, alone on an idle machine):

```
5 failed, 4647 passed, 3 skipped, 1 warning in 608.78s (0:10:08)
4647 + 3 + 5 = 4655 == collect
```

### Red set: EXACTLY baseline-5 (not a superset)

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

Environmental races (readonly-DB concurrency ×4) / Windows symlink privilege ×1 —
identical to the documented baseline. **Delta = 0.** The documented `eval_plane`
timing flake did not fire (0 occurrences), so no isolation proof was required.

## Observations (reported, not demanded)

* **O-A — the anchor is process-local.** `deadline_mono` is a monotonic reading,
  so it is meaningful within one process. This plane's recovery is itself
  process-local and derived (`supervisor.py`), so the fix is consistent with the
  plane's scope; a checkpoint resumed in a *different* process cannot interpret
  the instant. No wall-clock term is used, per the brief (that would be a
  MUST-STOP finding).
* **O-B — a foreign or corrupt anchor larger than the declared bound.** The fix
  fails closed for `remaining <= 0`. An anchor further in the future than the
  declared bound (only reachable from a foreign monotonic origin or a tampered
  record) would still grant a bound longer than declared. Out of the brief's
  scope and not reachable within one process; reported so the reader can decide.
* **O-C — the audit's O1/O2/O3 stand.** The `DELEGATION_LIMIT` prose, the
  malformed-path trace silence and the child-run re-derivation were Observations
  in the audit and are not touched here.

## NOT-list compliance

Binding NOT-list bars DOING WORK in the four domains; clearance prose is not a
hit; a hit is functional coupling only. Case-insensitive word-boundary scan:

| Surface | Hits |
| --- | --- |
| Range diff (`git diff 62b40af HEAD`) | **0** |
| Landed tree `src tests config` (`git grep`) | **0** |
| Commit subjects + bodies over the range | **0** |

**No functional coupling. Not a STOP.** No shared checkout was used, nothing was
pushed, and `.hermes/`, `or*.json` and worktree-bound branches were not touched.

## Prohibited-claims discipline

This fixes how a run's time bound is *carried* and the pins that claim to cover
it. It makes no claim about the validity of any content a model, a reviewer or a
capability carries, no reproducibility claim, and no admissibility claim for any
source. The single mutation path (`apply_intent`) and the human-authority fence
are untouched.

License: Apache-2.0 (LICENSE).
