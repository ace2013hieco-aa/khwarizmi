# MERGE-LOG-LOOP-M — the measured loop baseline

## Provenance

| Item | Value |
| --- | --- |
| Task | LOOP-M: a measured baseline for the usefulness claim (runs **before** LOOP-5) |
| Base (`main` before) | `3111f76` |
| Slice | `slice/loop-metrics@48b8ee2` — created at the base, landed by **fast-forward** |
| Landed tip | `48b8ee260b083de8186f47f01fd9638808d06702` |

## Scope

```
docs/LOOP-BASELINE.md            | 157 ++  (the table, the corpus, the limits)
docs/SUITE-COUNT.md              |   6 +-  (5058 → 5062)
src/hermes/eval/loop_metrics.py  | 227 ++  (pure vector computation)
tests/test_loop_baseline.py      | 1017 ++ (the corpus + 4 pins)
```

**Zero files changed under `src/hermes/agents/runtime/`.** That was the hard constraint, and
it holds: `git diff --name-only 3111f76..48b8ee2 -- src/hermes/agents/runtime` is empty.
The reason is mechanical, not stylistic — `Supervisor.trace_digest` hashes
`{**event.detail, "kind", "seq"}`, so adding one detail field would move every pinned trace
digest, and the emit and transaction censuses are frozen.

`loop_metrics.py` imports `statistics`, `dataclasses` and `typing` — nothing else. No I/O,
no clock, no database, no randomness.

## What was measured

Eight scenarios (S1–S8), each a declared profile plus a scripted model, scripted capability
results and a frozen clock; 13 runs in total (8 root + 5 child). The vector, as pinned:

| Scenario | Termination | Ticks | M1 bytes (min/med/max) | Tools | M2 repeat | M3 new/tick | M4 rounds | M6 admitted/dup/refused/other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S1 | STOP_WHEN | 1 | 148/148/148 | 1 | 0.00 | [1] | n/a | 1/0/0/0 |
| S2 | STOP_WHEN | 2 | 140/312.5/485 | 2 | 0.00 | [1,0] | n/a | 2/0/0/0 |
| S3 | STOP_WHEN | 2 | 124/296.5/469 | 2 | **0.50** | [1,0] | n/a | 1/1/0/0 |
| S4 | STOP_WHEN | 2 | 150/415/1421 | 0 | 0.00 | [0,0] | 2/2 FAIL→PASS | 4/0/0/0 |
| S5 | STOP_WHEN | 2 | 140/410/1421 | 0 | 0.00 | [0,0] | 2/2 FAIL→FAIL | 4/0/0/0 |
| **S6** | **TOOL_FAILED** | 1 | 138/138/138 | 1 | 0.00 | [1] | n/a | **1**/0/0/1 |
| S7 | TIMEOUT | 1 | 144/144/144 | 0 | 0.00 | [0] | n/a | 1/0/0/1 |
| S8 | TICK_LIMIT | 1 | 64/96/128 | 0 | 0.00 | [0] | n/a | 1/0/0/0 |

Aggregate: **19 admitted, 1 duplicate, 0 intent-refused, 2 other refusals**; termination mix
**SUCCEEDED 11 / TOOL_FAILED 1 / TIMEOUT 1 / CANCELLED 0 / OTHER 0**.

**S6 is the number LOOP-5 must move.** A draft is admitted, the tool then fails, and the run
terminates `TOOL_FAILED` with **one durable proposal** — exactly the E4 defect, now measured
rather than argued. LOOP-5's expected movement is on that row and nowhere else.

Two honest observations the table surfaces on its own:

1. **S3's repeat rate is 0.50** — the model asked the same tool with the same args twice and
   the loop did not intercept it at the capability layer; it converged only after the
   repeated observation. That is LOOP-2 working as designed (feedback retained) but not
   LOOP-2 suppressing the call.
2. **`trace_digest` is not a run identity.** It hashes kind, sequence and detail, not the run
   id, so S4's and S5's first review children share a digest. The test pins the exact
   values; the document says why they can coincide.

## What was deliberately not done

- **No composite quality score.** `test_baseline_has_no_composite_score` fails if one is
  introduced. A weighted number would hide the trade-offs the table exists to expose.
- **No instrumentation.** Every metric reads the runtime's public surface (the
  `ProposalSet`, the checkpoint, `trace_digest`) or the test-owned ports. Nothing was added
  to the thing being measured.
- **No retroactive claim.** The baseline is **post-LOOP-1..4**; the pre-LOOP output numbers
  do not exist. The document states plainly that this table cannot prove the earlier loop
  work improved output — it can only judge what comes next, against a fixed corpus.

## Gates (raw)

| Gate | Result |
| --- | --- |
| `tests/test_loop_baseline.py` ×2 | **4 passed** each; identical vectors and digests (asserted, not just counted) |
| Full suite | **5059 passed / 3 skipped / 0 failed** (5062 collected) |
| `stamp_suite_count.py --check` | `collected=5062` |
| `check_census.py` | **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0 |
| B4 ref graphs | **24 passed** |
| `ruff check src tests scripts` | `All checks passed!` |
| `pyright src` / tests project | **0/0/0** / **0 errors, 1 known warning** |
| Runtime diff | **0 files** under `src/hermes/agents/runtime/` |

## Residuals

1. **The instrument measures the loop, not an LLM.** A scripted model cannot exhibit
   research judgment; a usefulness claim about research quality needs a recorded-live layer
   (the model plane can record/replay) and is out of scope here.
2. **Eight scenarios are a fixed instrument, not a sample.** No population prevalence, no
   statistical significance, and none should be inferred.
3. **Pure draft counts are not split out for S4/S5/S8** — M6 counts all admitted intents,
   and the review-task and child-task command admissions are called out in the document. A
   draft-only split would need another observation field, which this slice did not add.

## Prohibited-claims discipline

This gate certifies a measurement of loop mechanics on a deterministic corpus. It claims no
research validity, no reproducibility, no quality score, and no retrospective improvement.
The only claim it licenses is movement against this table, with the corpus and model layer
held fixed.

License: Apache-2.0 (LICENSE).
