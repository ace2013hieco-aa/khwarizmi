# AUDIT-P-AUTO-6-REDTEAM - closed-loop integration test (slice/p-auto-6-loop@b3345f1)

- **Target**: `b3345f1` - 1 file: `tests/test_p_auto_6_loop.py` +629 (blob `b37ad424`, sha256 `41d25f4acbec641794ff16d11abce038b2410abcf49229649f1d570ca65e1310`)
- **Base**: `main@916fc23`; **branch**: `audit/p-auto-6-redteam` (local-only, no push)
- **Isolated worktree**: `.worktrees/p-auto-6-redteam`; probes run with `PYTHONPATH=<audit-wt>/src`; the slice test file is run **read-only from its own worktree** (no checkout changes; no writes to human-owned dirs)
- **Host**: Windows, Python 3.14.1, pytest 9.1.1; probe/red-leg plugins in OS temp (`C:/Users/Ali Zoghi/AppData/Local/Temp/p6audit/`)
- **Verdict: PASS** - 0 MUST-FIX, 3 SHOULD-FIX, 3 NOTE. A/B/C/D/E/F adjudicated; the golden is non-vacuous and the envelope claims reproduce under independently rebuilt red legs.

| Section | Adjudication |
|---|---|
| A - golden vacuity | **PASS** - falsified by two single-event mutations at the golden itself; material mutations caught earlier |
| B - red-leg independence | **PASS** - self-built plugins (different seams) reproduce identical failure sets |
| C - fault realism | **PASS + SHOULD-FIX** - deadline coverage partial; classifier collision buckets deterministic refusal as TRANSIENT |
| D - quarantine-then-proceed | **PASS for in-band shapes; SHOULD-FIX** for a row-tamper shape that loses the boot re-import |
| E - production boundary | **NOTE** - explicit and pinned at the roadmap's stated location; assertions are name-glob narrow |
| F - temp-plugin problem | **SHOULD-FIX** - commit a parameterized fault-injection harness; nothing is committed today |

## Raw gates (6-test file, read-only; audit-worktree src)

```
$ PYTHONPATH=<audit-wt>/src python -m pytest ../p-auto-6-loop/tests/test_p_auto_6_loop.py -p no:cacheprovider -v
..\p-auto-6-loop\tests\test_p_auto_6_loop.py ......                      [100%]
6 passed in 1.45s                                                        (exit 0)

$ ruff check ../p-auto-6-loop/tests/test_p_auto_6_loop.py
All checks passed!                                                       (exit 0)

$ pyright --pythonpath <venv>/python.exe ../p-auto-6-loop/tests/test_p_auto_6_loop.py   # explicit file, no project
  test_p_auto_6_loop.py:123:9  - error: dict|None -> program_from_dict(d)   (reportArgumentType)
  test_p_auto_6_loop.py:264:9  - error: Unknown|None -> RecordedTransport(inner) (reportArgumentType)
2 errors, 0 warnings, 0 informations

$ cd <slice-wt> && pyright --pythonpath <venv>/python.exe --project pyrightconfig.tests.json   # certified profile
tests/test_research_program.py:144:23 - warning: Instance methods should take a "self" parameter
0 errors, 1 warning, 0 informations                                      (exit 0)  # pre-existing warning
```

The 2 explicit-file errors are suppressed by the project tests profile (`reportArgumentType: "none"`, `pyrightconfig.tests.json`) - test-only typing nits at `_plan()` (`current_primary` can return None) and `_replay_wiring(inner=None)` (replay mode never touches `inner`). NOTE, not a defect: consistent with the profile's deliberate probe-script suppressions; both would surface as runtime errors anyway (`program_from_dict(None)` would raise; `inner` unused in replay).

## A - golden vacuity: PASS (non-vacuous, layered)

Mutation plugins ran the full 6-test file each (temp dir). Results:

| Mutation | Outcome | First failing assertion |
|---|---|---|
| A1 `accept_extraction_output` -> accept with **no rows** (skip validate) | 3 failed / 3 passed | `:367 assert len(claims) == 1` (`0 == 1`) - material, before the golden |
| A2 `_park_human_gate` -> auto-SUCCEED (drop gate) | 1 failed / 5 passed | `:340` `HumanApprovalRequested` row absent (IndexError) - journal footprint, `out.waiting_human` still matched because the mutation kept the return shape |
| A3 drop only the `GatePassed` event (verdict, status, resume all intact) | 1 failed / 5 passed | **`:383 the golden`**: `At index 1 diff: ('HumanGateResolved', 'rp-...-gate-hypothesis') != ('GatePassed', 'rp-...-gate-hypothesis')` |
| A4 drop only the `ProjectResumed` event (mode still goes ACTIVE) | 1 failed / 5 passed | **`:383 the golden`**: `At index 3 diff: ('HumanApprovalRequested', 'rp-...-gate-pre_compute') != ('ProjectResumed', None)` |

The landmark golden is order+type sensitive and is falsified by single-event omissions (A3/A4) that leave the status chain and the resolve return value intact - it asserts real journal structure, not mere presence. Broken-validate/dropped-gate mutations are additionally caught by independent material/journal assertions before the golden (A1/A2), so the test is layered rather than golden-only. **Not vacuous.**

## B - red-leg independence: PASS (self-built, different seams)

Plugins rebuilt from scratch (not the slice's):
- `rq.py`: `controller.build_loop_threshold -> 10**9` - threshold inflation; `LoopDetector.observe_failure` and `classify_failure_signature` untouched.
- `rd.py`: `paginate._deadline_expired -> False` - kills the **check site**; the deadline value is still computed and threaded.

```
$ ... -p rq -v
FAILED test_poison_task_quarantined_never_retried_silently             (:450)
FAILED test_loop_pattern_trips_detector_at_threshold_and_quarantines   (:512)
FAILED test_recovery_after_quarantine_legit_work_proceeds_and_idle_is_named (:584)
3 failed, 3 passed in 1.22s                                              (exit 1)

$ ... -p rd -v
FAILED test_hung_fetch_deadline_fires_typed_transient_no_hang
  assert would_hang.contacted == 0  ->  assert 1 == 0                    (:549)
1 failed, 5 passed in 1.57s                                              (exit 1)
```

Identical failure sets to the slice's temp plugins (which no-op `observe_failure` and null `_dispatch_deadline`). The envelope claims do not depend on one particular monkeypatch or one particular seam. The deadline red leg also confirms the record-mode `would-hang` transport is **causally** contacted when the envelope is disabled (the premise of the green `contacted == 0`).

## C - fault realism: PASS + SHOULD-FIX

Probe output (poisoned extract admitted on `dm-1`):

```
POISON quarantine reason (full): loop quarantined: task 'extract_b22aecc...' failed 3x with failure
  class 'TRANSIENT' (last: "acceptance refused: extraction output refused: draft.source_ref
  'dataset_manifest:WRONG' does not match the producing ta...") (LOOP_PATTERN_QUARANTINED/POISON_TASK_QUARANTINED)
POISON last FAILED reason: ... draft.source_ref 'dataset_manifest:WRONG' does not match the producing
  task's spec.source_ref 'dataset_manifest:dm-1' ... (V6-P7-E03)
FLAP class: TRANSIENT ; REAL shipped shapes: "search UNAVAILABLE (could not search)" -> TRANSIENT,
  "search EMPTY (searched, found nothing)" -> EMPTY
MARKER COLLISION: 'refused' in 'acceptance refused...': True
```

- **Poison** is a reachable shape: the draft cites a different source than the producing task's spec; the binding check that rejects it is the shipped V6-P7-E03 validation (`controller.py:5259-5269` acceptance path). Not a straw man.
- **Flap** mirrors shipped `failed_typed` reasons (`source_handlers.py:529,547`): a 429/transient burst classifies identically. Not a straw man.
- **Hung fetch** exercises the pre-source deadline check (`tools/providers/paginate.py:994-1002`, `_deadline_expired` at `:181`); a real blackholed provider is exactly what D1 was built for.

**SHOULD-FIX C1 (classifier collision).** `classify_failure_signature` (`autonomy_caps.py:491-508`) substring-matches the transient marker `"refused"` (intended for connection-refused) inside `"acceptance refused..."`, so a *deterministic* validation rejection counts as `TRANSIENT`. Consequences: the class label in the quarantine reason is misleading, and a deterministic refusal alternating with an EMPTY failure resets the other's streak (different-class reset, `:428-430`). Not introduced by P-AUTO-6 (P-AUTO-4 machinery), but the slice's poison test pins only `LOOP_PATTERN_QUARANTINED`, never the class - the collision goes unobserved. Fix: exclude `"acceptance refused"` (or word-boundary the connection markers) and/or assert the intended class in the slice test.

**NOTE C2 (deadline coverage is partial).** The D1 envelope has three check sites - search walk (`paginate.py:247`), retry loop (`:592-595`), fetch per-source/per-attempt (`:994-1002`, `:1105`) - and the slice proves only the fetch batch site. Mid-retry expiry and search-walk expiry are untested by this slice (covered elsewhere by P-AUTO-3 tests; not required for P-AUTO-6, but the slice's "deadline fires" claim is site-scoped).

## D - quarantine-then-proceed soundness: PASS for in-band shapes; SHOULD-FIX for the row-tamper shape

Probe D (v3) against the slice's helpers:

```
V1 PASS: quarantine refused the requeue (attempt=0, bound not reached), loudly
V3 PASS: direct _re_execute_requeued refused
V2 boot re-import after row tamper: []
V2 result: retried=[] model_calls=1 journal_RUNNING_events=4 status=FAILED
V2 DOWNGRADE CONFIRMED: recovery re-executed a journal-quarantined task after the mutable row was forced live
V4 PASS: interleaved failure quarantined independently (handler calls=3); legit work SUCCEEDED; V1 task untouched
```

- **V1 (intended recovery shape): PASS.** A seeded-quarantine task left stale-RUNNING with `attempt=0` is refused by `_requeue_recovered` *because of the quarantine* (loud note in `ctrl.notes`, `controller.py:2910-2916`); `attempt` was reset to 0 to prove the refusal is not merely the retry bound. No new RUNNING event.
- **V3 (belt-and-braces): PASS.** A direct `_re_execute_requeued([task])` call is refused with the named note (`controller.py:2944-2950`).
- **V4 (interleave a second failure mid-recovery): PASS.** A flapping task admitted after the first quarantine trips its own detector at threshold (3 handler calls) and quarantines independently; legitimate extract work proceeds and SUCCEEDS; the first task is never touched.
- **V2 (SHOULD-FIX D1): the boot re-import is defeatable by row mutation.** `reimport_quarantine` only reports tasks whose row is *currently* `FAILED` (`AND t.status = 'FAILED'`, `autonomy_caps.py:542-551`). Forcing a journal-quarantined task's mutable row back to `RUNNING` (with `attempt=0` to isolate the guard) makes a fresh controller drop it from the quarantine set; recovery then re-executes it **once** (`model_calls +1`, a 4th RUNNING journal row) before the re-derived streak re-quarantines it. No in-band path puts a quarantined task back to RUNNING (quarantine implies the FAILED transition; operator re-open is a new intent), so this is not reachable by normal operation - but it is inconsistent with the repo's own anti-tamper precedent for gates ("the mutable status column is never the sole authority", `controller.py:1757-1768`). Harden by having the boot import also consult the journal marker for live rows (allowing an explicit operator un-quarantine intent to clear it), or document the row-mutation assumption in the envelope. A regression test for the tamper shape would fit a follow-up slice.

## E - production-boundary strength: NOTE

`test_no_production_declaration_in_this_slice` (slice `:604-629`) asserts: no `docs/archive/*CERTIFICATION*` filename containing `AUTONOMY`/`P-AUTO`, and no `PRODUCTION.md` at the root or in `docs/`. The module docstring and the test name state explicitly that P-AUTO-6 proves the loop and does not declare production.

- **Strength**: the pinned location/name is exactly what the roadmap names as the production artifact (Phase-D-style certification record in `docs/archive/`), and the test resolves `parents[1]` from the test file (worktree-correct). It also forces any future certification to *update this test deliberately* - a welcome tripwire.
- **Reader risk: low.** Nothing in the slice's names, docstrings, or assertions claims production.
- **Weakness (NOTE E1)**: absence is name-glob narrow - a claim under another name (`docs/archive/AUTONOMY-PRODUCTION-APPROVAL.md`, `docs/PRODUCTION-READINESS.md`, a README/commit-message claim) escapes. If the certification naming is not yet frozen, broaden the globs (`*PRODUCTION*`, `*SIGN-OFF*`, `*APPROVAL*`) or assert the template filename once it exists. No MUST-FIX: the boundary is a documented convention and the slice cannot positively assert a future artifact.

## F - temp-plugin problem: SHOULD-FIX

The slice's red legs live only in `%TEMP%/p6` (`red_quarantine.py`, `red_deadline.py`); a repo search finds no committed `red_leg`/`fault_injection` harness. The audit rebuilt them (B), so the *method* is portable, but a future slice owner cannot re-run "envelope removed" from the repository, and the audit's red-to-green evidence is not self-service.

**SHOULD-FIX F1 (proposal).** Commit a parameterized fault-injection harness, opt-in only:
- `tests/fault_injection/kills.py`: a closed registry `ENVELOPE_KILLS = {"quarantine": <kill>, "deadline": <kill>, ...}` (small, documented, one function per envelope).
- `tests/conftest.py`: when `HERMES_FAULT_KILL` is set, apply the named kill at session start and **refuse unknown names**; never applied when unset.
- Documented command, e.g. `HERMES_FAULT_KILL=quarantine python -m pytest tests/test_p_auto_6_loop.py` -> expect 3 failed.
- Alternative if touching `conftest.py` is undesirable: `scripts/red_legs.py` generating a temp plugin dir and shelling out to pytest (same shape as today, just committed and named).

Temp-only sufficed for P-AUTO-6's one-shot proof under this audit gate, but committing the harness is what makes red-to-green part of the suite's operating contract rather than an oral tradition.

## Findings

**MUST-FIX: none.** No finding blocks the slice: the golden is falsifiable, the envelopes reproduce under independent red legs, and no in-band operation reaches the D1 tamper shape.

**SHOULD-FIX (3)**
1. **C1** - classifier substring collision: `"refused"` (connection family) matches `"acceptance refused"`, bucketing deterministic rejections as `TRANSIENT`; exclude or word-boundary the markers, and pin the intended class in the slice's poison test.
2. **D1** - `reimport_quarantine` depends on the mutable `t.status='FAILED'`; a row forced live loses the journal quarantine and can be re-executed once. Consult the journal marker for non-FAILED rows, or document the assumption; consider an explicit operator un-quarantine intent to clear it.
3. **F1** - commit a parameterized, opt-in fault-injection harness so the red legs are reproducible from the repo.

**NOTE (3)**
1. **E1** - production-absence assertion is name-glob narrow; broaden if certification naming is not frozen.
2. **C2** - the deadline envelope is proven only at the fetch batch check; mid-retry/search-walk sites are covered elsewhere.
3. **G1** - two explicit-file pyright `reportArgumentType` errors (slice `:123`, `:264`) are suppressed by the tests profile's `reportArgumentType: "none"`; test-only nits, runtime-safe as written (`inner` unused in replay; `current_primary` non-None in-fixture).

## Limits

- Hermetic only: no live egress, no schema changes, no writes to tracked files; slice and base trees were never checked out by probes (read-only file access + audit worktree src).
- The cross-process budget-counter limitation (in-memory counters) is untouched/parked per the P-AUTO-6 scope; no restart-persistence fault was built or required.
- Mutation probes monkeypatch internals (as the slice's own red legs do); they demonstrate journal/test sensitivity, not runtime exploits. V2 requires out-of-band DB row mutation (single-writer fenced DB is the system's stated defense).
