# DELTA-AUDIT-P-AUTO-4 — do the 6 closures hold? anything new opened?

Target: `fix/p-auto-4-bypass@0f578df` over `slice/p-auto-4-caps@da0d26c`
(read-only; no target files touched). All probes below are independently
written from the audit descriptions (`delta_probes.py`, Temp scratch —
NOT from the fix report's legs) and executed offline/fixture-only with
`PYTHONPATH=<fix-wt>/src` (green) and `<caps-wt>/src` (red).

Verdict: **PASS** — all 6 closures re-derived red→green, hunts A–D clean
(2 NOTEs, 0 MUST-FIX).

## Closures re-derived (own probes)

- **A1 CLOSED** — ledger carries measured 200 for a 200-request dispatch
  (estimate was 1): `D-A1 ledger=200`. Tick overrun recorded at 400 against
  a 250 cap with the 3rd dispatch refused
  (`BUDGET_PER_TICK_TOKENS_EXCEEDED`). Red on da0d26c (estimates only).
- **A2 CLOSED** — over-budget recovery requeue stays FAILED with the named
  note (`D-A2 status=FAILED note=True`). Red: requeued RUNNING→SUCCEEDED.
  Recovery counts per-task steps only by F15 design (tick/run capacity
  exempt — cadence preserved, attempt bound + quarantine guards intact).
- **B1 CLOSED** — 2 pre-restart failures reseeded from the journal; 3rd
  post-restart failure quarantines; terminal quarantine re-imported with
  reason on the next boot (`D-B1 ... quarantined=True reimported=True`).
  Red: streak lost, third failure `retried`. No schema: read-only SELECTs
  over existing `events`/`tasks` (`autonomy_caps.py` `reimport_quarantine`).
- **B2 CLOSED** — TRANSIENT/TIMEOUT alternation quarantines on the 3rd
  (`codes=['', '', 'LOOP_PATTERN_QUARANTINED']`); blank reasons count as
  UNKNOWN and quarantine (`D-B2`). Red: 6 alternating failures, never
  quarantined.
- **C1 CLOSED** — tightened 45s deadline present in both live handlers,
  default 300s otherwise (`D-C1 tight=[45.0, 45.0] default=[300.0, 300.0]`).
  Red: always 300s (builder output dropped at wiring).
- **C2 CLOSED** — explicit `per_tick_steps:1` + default floor raises
  `ValueError`; consistent pairs build (`D-C2`). Red: silent floor to 8.
- **D CLOSED** — pinned connection dials `(pin, 443)` with hostname SNI;
  gate publishes the pin for exactly one request (table cleared after);
  opener routes pinned hosts through `PinnedHTTPSHandler` with no default
  `HTTPSHandler` left (`D-D ... -> CLOSED`). Red: pin API absent
  (ImportError), inner receives the unpinned spec.
- **A3/F CLOSED** — slow single dispatch ends
  `WALLCLOCK_TICK_DEADLINE_EXCEEDED`; fully-capped tick ends
  `BUDGET_PER_TASK_STEPS_EXCEEDED` (was `idle=''`). Red: both `''`.

## Regression hunt

- **A — token paths: PASS + NOTE N1.** `_run_handler` charges exactly once
  on all 5 terminal paths (HandlerResult actuals + 4 estimate fallbacks;
  entry-None/no-builder paths execute nothing → correctly uncharged;
  dispatch post-claim charges non-handler estimates only). Recovery
  re-executions charge (extract estimate / handler actuals). N1: the
  lease-race note path (`controller.py` BindingError, task already left
  RUNNING) charges nothing — the orphan's requests (bounded: one
  dispatch) go uncounted while its re-execution counts separately. Rare +
  bounded; accepted residual, do not "fix" by double-charging blindly.
- **B — pin table: PASS.** Two threads pinning distinct hosts each observe
  only their own pin; table empty after both requests; mismatched clear
  cannot drop another request's pin (`H-B ... ISOLATED+CLEARED ... keeps`).
  Unpinned hosts fall through to the normal path (existing redirect tests
  green as evidence).
- **C — re-import vs N9/retraction: PASS + NOTE N2.** `FAILED→INVALIDATED`
  is not a legal transition, so a quarantined FAILED row is stably
  re-imported — retraction (artifact/evidence scope, disjoint event types:
  `IntentApplied/ResearchCreated/TaskCreated/TaskStatusChanged`) cannot
  resurrect or disturb it. N2: no operator un-quarantine path exists (no
  intent/CLI) — quarantine is currently terminal-permanent, and
  content-addressed re-admission returns the same FAILED row. Fail-closed
  and human-visible; needs a design-gated appeal path, not a silent one.
- **D — C2 false positives: PASS.** Matrix: default/8, absent-knob/16,
  defaults-obj/16, explicit4/4, explicit100/8 all behave (build or loud
  refusal only on genuinely inconsistent explicit pairs); an explicitly
  authored `8` with floor 16 refuses loudly — correct (loud > silent).

## Gates (raw, target `0f578df`)

- 12-test file: `12 passed` (behavioral red on da0d26c: 8 failed; b2+d×3
  ImportError-red — capability absent pre-fix)
- Full suite: green, 0 failed (4 live skipped); F15 cap-sweep green
- `ruff check src tests`: `All checks passed!`
- `pyright src`: `0 errors`; tests config: `0 errors, 1 warning`
  (pre-existing `test_research_program.py:144`)

## MUST-FIX: none. NOTEs: N1 (lease-race orphan undercount, bounded),
## N2 (no un-quarantine path — design follow-up).
