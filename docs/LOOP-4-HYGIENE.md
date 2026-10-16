# LOOP-4-HYGIENE — the LOOP-0 hygiene remainder, closed in one bounded batch

## Provenance

| Item | Value |
| --- | --- |
| Task | LOOP-4 (fixer — close the LOOP-0 hygiene remainder; no new scope) |
| Base | `main@25b9e69af769480d31b4708b14ed8680abb23b03` |
| Branch | `slice/loop-4-hygiene` (local-only, **no push**) |
| Worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/loop-4-wt` |
| Triage of record | `audit/loop-0-triage@a481f3f` — `AUDIT-LOOP-0-TRIAGE.md` |
| Commits | `7f3f78d` (E2/E3/G8-mid) · `b4145e3` (E5) · `40ba139` (E6) · `46b573d` (E7) · `b383cde` (E8) · `33a52e7` (13 pins) · `72ee54a` (restamp 4642 → 4655) |

Changed files (6): `src/hermes/agents/runtime/{assembly,run,supervisor,types}.py`,
`tests/test_loop4_hygiene.py` (new, 13 tests), `docs/SUITE-COUNT.md` (restamp).

## Per-item verdict

| Item | Triage verdict | This batch | Evidence |
| --- | --- | --- | --- |
| **E2** — the terminal act is not deadline-checked | VALID | **FIXED** | `_close` takes the run's `deadline` and passes it to both supervisor checks (it used to pass `None`). Pin: `test_a_deadline_that_expires_during_the_terminal_act_times_the_run_out`. |
| **E3** — resume resets the deadline | VALID | **FIXED** | `Checkpoint.deadline_mono` carries the run's deadline as an *absolute* monotonic instant, set once at run start and re-recorded unchanged on every entry; `resume` re-enters with that same instant instead of re-deriving a fresh one or re-basing a remaining duration; `_run_deadline` resolves once per run and keeps it on `_RunState`. Pins: `test_the_opening_checkpoint_does_not_extend_the_runs_deadline_anchor`, `test_a_resume_continues_the_runs_deadline_and_never_re_grants_it`. |
| **E5** — retry is information-free; inline sleep under the lease | VALID | **FIXED** | The refusal that ended attempt N-1 is rendered into attempt N's prompt as a `runtime.retry` envelope (`assembly.retry_envelope`), and `Supervisor.attempt` never sleeps *past* the run's deadline. Pins: `test_a_retry_is_asked_with_the_refusal_that_ended_the_previous_attempt`, `test_the_retry_sleep_never_crosses_the_runs_deadline`. |
| **E6** — `Termination.DELEGATION_LIMIT` is dead vocabulary | VALID | **FIXED** | The constant is **removed** (its only reference was its own declaration) and the module docstring's "delegation depth and child-run budget all stop the loop" is corrected to state the actual contract: those are *refusal* bounds. Pin: `test_the_termination_vocabulary_holds_no_dead_member` (also asserts every remaining member is written by a site in `run.py`). |
| **E7** — inconsistent failure severity | VALID | **FIXED** | One rule, stated in `_one_tool_call`: a capability the plane **actually invoked** and that refused or failed stops the run; a **malformed** call (no `capability_id`, arguments not a mapping, an unknown key) is refused and skipped while the batch carries on. The two malformed sites that were fatal now match every other malformed-output site. Pins: `test_a_malformed_tool_call_is_refused_and_the_tick_carries_on`, `test_a_capability_the_plane_invoked_and_that_failed_still_stops_the_run`, `test_a_capability_refusal_from_the_plane_still_stops_the_run`. |
| **E8** — `Proposal.capability_refs` is never populated | VALID | **FIXED** | Populated by rule from the run's retained feedback — the **derived** invocation keys of the calls whose evidence the draft was drafted on (a draft is authored before its own tick's calls run). Excluded from `draft_digest()`, so provenance is not draft identity. Pin: `test_a_draft_carries_the_evidence_it_was_drafted_on`. |
| **G8** — `_tool_phase` observes `token.cancelled` only | VALID (minor) | **FIXED** | The mid-batch check is the full supervisor check, so the run's deadline is observed there like everywhere else. Pin: `test_the_deadline_is_observed_mid_batch_not_only_at_the_tick`. |
| **G8** — `max_* = 0` conflated with unset via `or` | STALE | **RECORDED** (no change) | See below. Pin: `test_a_zero_limit_defers_to_the_profile_rather_than_disabling`. |
| **G8** — `converged` novelty / `draft_digest` excludes tick | NOT-A-BUG | **RECORDED** (no change) | See below. Pin: `test_converged_novelty_is_read_before_the_seen_set_absorbs_it`. |

## The two RECORDED items (rationale)

**G8 `or`-zero — STALE, not a defect.** `RunLimits` documents the rule in its own
docstring: "`0`/`None` defers to the profile's config" (`types.py`). `_max_ticks`
and `_max_proposals` read `context.limits.X or spec.termination.X`, which is that
rule expressed literally, not a conflation of "unset" with "disabled". A profile
with `max_ticks: 0` in its *limits* is therefore not a run that may take no
ticks; it is a run that defers. The pin drives a context with `max_ticks=0`
against a profile declaring `max_ticks: 2` and asserts two ticks ran. No code
change is warranted: the behaviour is the documented contract.

**G8 `converged` novelty / `draft_digest` excludes the tick — NOT-A-BUG.**
`_tick` counts `novel` against `state.seen_drafts` **before** updating it, so the
tick that first raises a draft counts it as novel and only a genuine repeat reads
as `novel == 0`; that ordering is what makes "the model repeated itself" a
statement about a repeat rather than about a first appearance. `draft_digest()`
excluding the tick is the *precondition* for recognising the same draft on a
different tick at all — and it is also what lets a checkpoint's prefix re-digest
identically after a resume. Both were confirmed deliberate on current main by the
triage; the pin locks the composite behaviour (tick 1 novel, tick 2 a recognised
repeat → `STOP_WHEN` at tick 2, one distinct digest). No code change.

## Non-vacuity — every pin is load-bearing

Each fix was reverted on its own (in-process, never committed) and the
corresponding pins re-run; all failed. Restored, all pass.

| Reverted | Pins run | Result |
| --- | --- | --- |
| E2/E3/G8-mid (deadline) | the 4 deadline pins | **4 failed**, 9 deselected |
| E5 — sleep bound only | the retry-sleep pin | **1 failed** (`TypeError`: no `deadline` parameter) |
| E5 — informed retry only | the retry-note pin | **1 failed** (`AssertionError`: 0 envelopes, expected 1) |
| E6 | the vocabulary pin | **1 failed** |
| E7 | the malformed-call pin | **1 failed** |
| E8 | the provenance pin | **1 failed** |

E5 was reverted in halves because reverting the whole group also removes
`RETRY_ORIGIN`, which the pin imports — the module then fails to *collect* rather
than failing an assertion, which is weaker evidence than a behavioural failure.

## Gates (raw, on the landed tip `72ee54a`, `PYTHONPATH=<wt>/src`, no extra `-q`)

Interpreter: `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/loop-4-wt/.venv/Scripts/python.exe`
(a directory junction to the repo venv; **Test-Path: True** for both the repo venv
`D:/New folder/research-agent/.venv/Scripts/python.exe` and the junction, identical
SHA-256 `22D89D728C105376D48ECD425EBA826C05F713A9962805B9B39924664A203076`; Python 3.14.1).

```
collect            : 4655 tests collected in 6.48s
stamp --check      : OK: docs\SUITE-COUNT.md collected=4655 matches the live collect   (exit 0)
check_census       : PASS - every certified figure is reproduced exactly.              (exit 0)
ruff (src tests)   : All checks passed!                                                (exit 0)
pyright src        : 0 errors, 0 warnings, 0 informations                              (exit 0)
pyright tests-cfg  : 0 errors, 1 warning, 0 informations                               (exit 0)
B4                 : 24 passed in 3.85s
LOOP-4 battery     : 13 passed in 0.82s
probe + assembly   : 11 passed in 0.42s
feedback battery   : 20 passed in 0.47s
review battery     : 12 passed in 0.37s
FULL suite         : 5 failed, 4647 passed, 3 skipped, 1 warning in 588.36s (0:09:48)
                     4647 + 3 + 5 = 4655 == collect
```

The only pyright warning is the pre-existing
`tests/test_research_program.py:144:23 reportSelfClsParameterName`, a file outside
this slice's diff.

### Red set: EXACTLY baseline-5 (not a superset)

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

Environmental races (readonly-DB concurrency ×4) / Windows symlink privilege ×1 —
unchanged from the documented baseline. **Delta = 0.** The documented `eval_plane`
timing flake did not fire (0 occurrences), so no isolation proof was required. The
suite was run **alone on an idle machine**.

## Stamp self-consistency

Base `Collected: 4642` → landed `Collected: 4655` = **+13**, exactly the new
battery's pin count. Per-commit: the five fix commits and the test commit hold
4642 (code and tests, no stamp edit); the restamp moves 4642 → 4655.

## Spine diff — empty (proven two ways)

```
$ git diff 25b9e69 HEAD -- src/ ':!src/hermes/agents/runtime/' | wc -l
0
$ git diff --name-only 25b9e69 HEAD -- src/hermes/research/gateway.py \
    src/hermes/research/gates.py src/hermes/research/integrity_gates.py \
    src/hermes/research/contradictions.py src/hermes/research/controller.py \
    src/hermes/persistence/ src/hermes/events.py src/hermes/core/intents.py | wc -l
0
```

Nothing outside `src/hermes/agents/runtime/` was touched. `apply_intent` and every
certified transaction boundary are untouched.

## NOT-list scan: PASS (no functional coupling)

Binding rule: the four terms bar DOING WORK in those domains; clearance prose
asserting absence is NOT a hit; only functional coupling stops. Canonical four:
`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`.

| Surface | Hits |
| --- | --- |
| Range diff (`git diff 25b9e69 HEAD`) | **0** |
| Landed tree `src tests config` (`git grep`) | **0** |
| Commit subjects + bodies over the range | **0** |

## Prohibited-claims discipline

This batch fixes a deadline, a retry envelope, a severity rule, a vocabulary
member and a provenance field on the drafting side of the plane. It makes no
claim about the validity of any content a model, a reviewer or a capability
carries, no reproducibility claim, and no admissibility claim for any source.
Every observation in the run remains untrusted data; the single mutation path
(`apply_intent`) and the human-authority fence are untouched.

License: Apache-2.0 (LICENSE).
