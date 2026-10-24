# MERGE-LOG-OPS-4A — the live-run instrument (wave 4, parallel track)

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-4A: score a real run — the collector the LOOP baseline never had |
| Base (`main` before) | `9f74279` |
| Slice | `slice/ops-4a-live-metrics@82ac4e3` — created at the base, **fast-forwarded** |
| Landed tip | `82ac4e3e80eac93b504de1ca9cf80721cd7cbd55` |

## Scope

```
docs/SUITE-COUNT.md                  |   6 +-  (5062 → 5071)
src/hermes/eval/loop_observations.py | 397 ++  (new: the collector)
tests/test_loop_observations.py      | 368 ++  (9 pins)
```

**`loop_metrics.py` untouched** (0 files) and **`src/hermes/agents/runtime/` untouched**
(0 files). The metric definitions and the pinned baseline were read, not changed.

## What it closes

`loop_metrics` computes the vector from observations; nothing collected them from a real
run. After this slice, `collect_scenario(...)` turns a run's surfaces — the `ProposalSet`,
the terminal checkpoint, the supervisor, the model port and the capability port — into the
same `ScenarioObservation` the baseline uses.

Collection is by **wrapping the ports the caller injects**: `RuntimeWiring(capabilities=...)`
and `AgentRuntime(capabilities=...)` both accept a port, so `RecordingCapabilityPort` and
`RecordingModelPort` measure without touching the runtime, adding an event, or moving a
trace digest.

## The acceptance criterion — met

`test_collector_reproduces_the_pinned_baseline_row_for_row` runs the **existing scripted
corpus** through the collector and asserts the vector is **identical to the pinned
baseline**, row for row, trace digest for trace digest, aggregate included
(`runs 13, admitted 19, duplicate 1, intent_refused 0, other 2`; mix
`SUCCEEDED 11 / TOOL_FAILED 1 / TIMEOUT 1 / CANCELLED 0 / OTHER 0`).

The baseline was **not** re-pinned. The charter's failure rule held: a disagreement would
have meant the collector was wrong.

## Honesty properties, pinned

- **`n/a` is never `0.0`.** `test_unwrapped_capability_port_reports_na_never_zero` and
  `test_unwrapped_model_port_reports_na_for_m1` pin it. A zero would read as "no repeated
  tool calls" — a claim nobody measured.
- **`CollectedScenario` rather than `ScenarioObservation`.** The latter cannot express "not
  measured": empty `tool_calls` and a measured zero are the same value. The wrapper carries
  `unmeasured` beside the observation and `vector()` is the reporting surface. A caller who
  bypasses `vector()` gets the old zero, which the module docstring states.
- **A refused request is still a model call** (`test_a_refused_request_is_still_a_model_call`).
- **Determinism** — two collections of the same run are equal.

## What was refused

`scripts/loop_report.py` — a run-id reader has nothing to read. The supervisor's trace is
in-memory by design (B-5 refuses durability) and checkpoints are in-memory too. It would
have printed nothing or invented a dump format. Declining it is correct; it moves the
"readable" question into OPS-1's ruling, where the durable surfaces are decided.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Collector + baseline | **13 passed** |
| Full suite | **5051 passed / 15 skipped / 5 failed** (5071 collected) — the five are the documented intermittent set, and the agent **re-ran the same five at `9f74279`: 5 failed there too**, so they are host-level |
| `stamp_suite_count.py --check` | `collected=5071` |
| `check_census.py` | **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0 |
| B4 ref graphs | **24 passed** |
| `ruff` / `pyright src` / tests | clean / **0 errors** / **0 errors, 1 known warning** |

## Residuals

1. **The vector must be computed in-process.** A finished run leaves the journal and the
   database; its trace and checkpoints do not survive the process. OPS-4 therefore has to
   collect at run end — that is a hook in OPS-1 phase 2, not a property of this slice.
2. **M2 is only as good as the wrapper.** Paths that construct their own capability port
   cannot be measured; none exist in-tree today, but the collector reports `n/a` rather
   than guessing.
3. `RuntimeWiring` does not expose its supervisor, so a wiring caller must construct and
   pass one or M0 has no trace to digest.

License: Apache-2.0 (LICENSE).
