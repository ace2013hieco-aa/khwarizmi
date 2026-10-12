# AUDIT-P-AUTO-4 redteam — caps are safety machinery (attacked as such)

Target: `slice/p-auto-4-caps@da0d26c` over base `main@9e4a5d3` (read-only;
no target files touched). Values table treated as FIXED — enforcement
attacked, not values. All probes offline/fixture-only (stub DNS/proxy,
in-memory SQLite, `PYTHONPATH=<p-auto-4-caps-wt>/src`).

Verdict: **FAIL** (6 MUST-FIX, 3 SHOULD-FIX, 5 NOTE — details A–G below).
The machinery is real and mostly enforced, but it is not yet safe to
stand behind for live loops: real provider-request volume can exceed the
token envelope 4x unrefused, recovery re-execution is uncounted,
quarantine evaporates on restart, the DNS vet does not pin the dial, and
the operator deadline knob is unwired in the live path.

## A. Cap-bypass — FAIL

- **A1 MUST-FIX — token envelope tracks estimates, never actuals.**
  `controller.py:765` `_estimate_tokens` returns `max_pages` (50 max) as
  the whole per-dispatch token charge, but one search dispatch can issue
  up to `max_pages * (max_retries+1)` = 200 transport requests. 8 max-size
  searches in one tick count 400 against `per_tick_tokens=1000` (granted,
  probe returns `''`) while the wire can carry 1600. No feedback path
  exists from transport → tracker (sole token source is the estimate).
  Probe: `P-A1 ... tick_counted=400 tick_actual_worst=1600 per_tick_cap=1000
  consume_code='' -> BYPASS`. Minimal fix: charge actuals (count transport
  requests per dispatch into the tracker) or scale the estimate by the
  retry multiplier `(max_retries+1)` with the multiplier documented.
- **A2 MUST-FIX — recovery re-execution is uncounted and unvetted.**
  `controller.py:2882` `_re_execute_requeued` contains zero `_budget` /
  `_loops` / quarantine references (probe `budget_refs: 0, loop_refs: 0`);
  `_requeue_recovered` (`controller.py:2849`) transitions
  FAILED→RETRYING→RUNNING without `consume_step` or a per-task-budget
  check. A task at its step cap that goes NO_SIGNAL is requeued and
  re-executed past its budget with no refusal. Minimal fix: `check_step`
  in requeue + `consume_step` on re-execution (same pre-claim pattern as
  `controller.py:4865-4925`).
- **A3 SHOULD-FIX — wall-clock gaps.** (i) Tick wall is checked only
  between dispatches in `_dispatch_pass`: a handler sleeping 0.3s with
  `per_tick_wall_s=0.05` completes with `idle=''` and zero WALLCLOCK
  notes (probe `P-A3 ... -> BYPASS`). A hung handler holds the tick past
  every wall cap; only the heartbeat horizon (a different mechanism)
  bounds it. (ii) A tick with no eligible work never evaluates the wall
  (`_tick_start` reset at `controller.py:836-838`, loop body never runs):
  probe `P-A3 empty_tick ... idle='' -> NO-FIRE`. Minimal fix: stamp/check
  the tick wall after the dispatch loop and on the no-eligible path.
- **A4 NOTE — run scope restarts every `run()` call** (`controller.py:975-977`
  resets `run_steps/run_tokens`; probe `pre=500 post=0`) and every tracker
  is process-lifetime in-memory. `cli.py:493-494` calls `run()` once per
  invocation so this is coherent per-process, but a supervisor
  cron-looping `hermes run` accumulates unbounded across processes.
  Cross-process budgets need durable counters (design gate).

## B. Quarantine escape — FAIL

- **B1 MUST-FIX — restart wipes the streak and the quarantine set.**
  Both live in `LoopDetector` memory (`autonomy_caps.py:371-373`). Probe:
  threshold 3, two `TRANSIENT` failures (`retried,retried`), fresh
  `Controller` on the same DB → `quarantined_tasks()==()`, third
  consecutive failure → `retried`, `quarantined_after==()`
  (`P-B1 ... -> ESCAPE`). A poison task gets 5 attempts across one
  restart without quarantining. Minimal fix without new schema: on
  construction, re-import quarantine from FAILED-task rows whose `reason`
  carries the quarantine marker (the marker is already persisted in the
  terminal FAILED reason by `controller.py:4997-5004`).
- **B2 MUST-FIX — free-text signatures are evadable by nature.**
  `LoopDetector.observe_failure` (`autonomy_caps.py:375-396`): alternating
  `TRANSIENT/TIMEOUT ×3` yields codes `['','','','','','']`, never
  quarantines; blank signatures never count. Reason strings embed
  per-incident text (`controller.py:5154-5155`
  `f"extraction output rejected: {exc}"`, `:5192-5193`
  `f"acceptance refused: {exc}"`, `:3005-3006` handler reason), so one root
  cause produces many signatures and the streak self-resets. Probe
  `P-B2 ... -> ESCAPE`. Minimal fix: key streaks on a normalized
  failure class (not the rendered reason) and count blank signatures.
- Recovery path: **PASS** — `_requeue_recovered` refuses quarantined tasks
  (`controller.py:2862-2866`); FAILED rows are ineligible for normal
  dispatch, so no in-process re-dispatch after quarantine was found.

## C. Config-widening — PARTIAL (1 MUST-FIX, 1 SHOULD-FIX, 2 NOTE)

- `narrow_int/narrow_float` refuse widening loudly — **PASS** on every
  direct path (probe: deadline 600 → `ValueError ... never widen`).
- **C1 MUST-FIX — operator deadline knob is unwired in the live path.**
  `live_fetch.py:137-148` builds the narrowed `SourcePolicy`, but
  `build_live_fetch_wiring` (`live_fetch.py:264-351`) constructs handlers
  with defaults (`:349-350`
  `make_source_search_handler(machinery)` — no policy arg), so the 300s
  default always applies regardless of operator config. Deliverable (b)
  claims the deadline is "wired to operator config" — the object is built
  and then dropped. Minimal fix: pass
  `policy=source_policy_from_autonomy(autonomy_caps)` at `:349-350`
  (or delete the tunability claim).
- **C2 SHOULD-FIX — explicit tightening silently overridden by the floor.**
  `controller.py:671-676`: `per_tick_steps < max_calls_per_tick` is
  replaced via `dataclasses.replace` with no error. Probe: explicit
  `per_tick_steps=1` (default `max_calls_per_tick=8`) → effective `8`
  (`P-C ... -> SILENT-OVERRIDE`). An operator tightening is widened
  silently — the exact pattern the narrow-only doctrine forbids. Minimal
  fix: refuse construction on the inconsistent combination (loud), or
  document floor precedence in the values table.
- **NOTE — injection seam bypasses narrow checks.** `Controller(...,
  budget_tracker=BudgetTracker(...1e9...))` is accepted with no refusal
  (probe `P-C injection ... -> INJECTION-BYPASS`). Acceptable only if
  direct injection is declared test-only and production always builds via
  `build_*`; state that in the constructor docs.
- **NOTE — TOML load has no ceiling.** Widened `[autonomy_caps]`
  (`per_run_steps=1000000`, `deadline=600.0`) loads fine; refusal is
  deferred to `build_*` call sites. Sound only while every wiring path
  funnels through `build_*` — C1 shows one that does not.

## D. DNS-vet bypass — FAIL (MUST-FIX)

Vetting without pinning: `_AllowlistedTransport.request` resolves and
vets, then hands the **original spec** to the inner transport (probe:
`inner_received_url=['https://api.openalex.org/works']`, unpinned).
`ProviderHTTPTransport` dials by hostname (stdlib re-resolution), so the
checked address is not the dialed address — the exact TOCTOU the S2
reference exists to close (`egress.py:11-22`: "the address that was
checked is the address that is dialed"). Private-stub refusal works
(probe: `DNS_REBINDING_REFUSED ... 10.0.0.5 (private ...)`), so the vet
itself is correct; the dial is unbound. Minimal fix: dial the pinned
address (S2 `GuardedFetcher` mechanics for the two D5 hosts) or route
live fetch through the guarded fetcher; record the PS-03
single-entry-point reconciliation the `egress.py:24-28` docstring already
flags as a design-gate decision. (A bypass needing live egress to prove
end-to-end is NOT claimed — methodology recorded per STOP CONDITIONS.)

## E. Proxy escape — PASS + NOTE

With `HTTPS_PROXY` set, the guarded opener carries **no** `ProxyHandler`
at all while `getproxies()` reports the env proxy and the default opener
carries it (`P-E ... guarded_ProxyHandlers=[] default_...=[{...https...}]
-> CLOSED`). Env proxy is honored nowhere on the guarded path. NOTE: the
`http.py` comment claims the opener "carries an EMPTY ProxyHandler({})",
but CPython 3.14 drops the empty mapping in `add_handler` — the outcome
is correct (no proxy authority survives) while the comment describes a
mechanism that does not survive. Reword the comment to the outcome.
`urlopen` usages honoring env proxies are test-only (live probe).

## F. Starvation/deadlock review — PASS + 1 SHOULD-FIX

No hang or deadlock found: every breach is STOP-shaped (park/end/skip),
quarantine parks terminally, and `run()` always terminates. One silent
state: a tick in which **every** task is individually capped
(`BUDGET_PER_TASK_*` → `continue`) ends with `idle=''` and empty
dispatch — indistinguishable from clean completion at the `TickResult`
level (codes live only in notes). Probe: `tick2 dispatched=[] idle=''`
with note `dispatch refused for ... BUDGET_PER_TASK_STEPS_EXCEEDED`
(`P-F ... -> SILENT-TICK`). SHOULD-FIX: set a tick `idle` code when caps
skip all dispatches (e.g. reuse the per-task code that fired).

## G. F15 cap-sweep preservation — PASS + NOTE

`tests/test_controller.py::test_21_f15_completion_budget_headroom_cap_sweep`
re-run green against the target (27 passed with the 26 P-AUTO-4 tests).
Floor behavior re-derived: no operator →
`max_calls_per_tick=16 ⇒ per_tick_steps=16`; explicit `per_tick_steps=4`
+ floor 16 ⇒ `16` (probe `P-G`). The floor preserves the sweep
(`needed == ceil(300/cap)` at every cap). NOTE: the second case is C2 —
an explicit tightening silently widened; the sweep passes *because* of
the silent override, so G's green depends on C2's SHOULD-FIX going the
loud-refusal route rather than the silent-floor route.

## Gates (raw, target `da0d26c`, `PYTHONPATH=<caps-wt>/src`)

- 26-test file: `26 passed in 0.44s` (plus F15 sweep: 27 passed combined)
- `ruff check src tests`: `All checks passed!`
- `pyright src`: `0 errors, 0 warnings, 0 informations`
- `pyright --project pyrightconfig.tests.json`: `0 errors, 1 warning`
  (pre-existing `tests/test_research_program.py:144` self-parameter; not target)

## MUST-FIX (minimal) / SHOULD-FIX / NOTE index (6 / 3 / 5)

MUST-FIX: A1 (charge actual transport counts or retry-scaled estimate);
A2 (budget consume/check in requeue + re-execute); B1 (re-import
quarantine from FAILED marker reasons at construction); B2 (normalized
failure-class streak keys, count blanks); C1 (install narrowed
SourcePolicy into live handlers); D (pin the dialed address for D5
hosts). SHOULD-FIX: A3 (post-dispatch + empty-tick wall checks); C2
(loud refusal on per_tick < max_calls instead of silent floor); F
(idle code when caps skip a whole tick). NOTE: A4 (process-lifetime
counters); C-injection seam; C-TOML ceiling; E comment wording; G/C2
interaction.
