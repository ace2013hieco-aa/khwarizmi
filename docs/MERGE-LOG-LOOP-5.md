# MERGE-LOG-LOOP-5 — E4 reclassified: the ordering is correct (GAP-1 loop track, final row)

## Provenance

| Item | Value |
| --- | --- |
| Task | LOOP-5 (E4): proposals cross the write path before the tick's tool batch |
| Ruling | **A — the ordering is correct, documented** (human, 2026-10-23) |
| Base (`main` before) | `87f2cd2` (LOOP-M baseline) |
| Slice | design gate `bb26500` + ruling record `d8b96fa` — both fast-forwarded |
| Landed tip | `d8b96facc1f731fd8046f48b31d91100b22a164d` |

## Scope

```
docs/idr/LOOP-TICK-ORDERING.md      | 217 ++  (new: inventory + ruling)
src/hermes/agents/runtime/run.py    |  10 +-  (`_tick` docstring only)
tests/test_loop0_e1_probe.py        |  24 +-  (the probe's claim, not its observations)
docs/LOOP-BASELINE.md               |   3 +   (S6 is a pin, not a defect marker)
```

**`tests/test_loop_baseline.py` is untouched** — the mechanical proof that no behaviour
moved. It passes with the S6 row still pinned at **1 admitted / `TOOL_FAILED`** and trace
digest `a2fab43e…`.

## What the gate found

The charter was written to close E4 as a defect. The inventory found the opposite:

- **No tool consumes a same-tick admission.** `_tool_phase` (`run.py:1077-1238`) contains
  no reference to `state.proposals`, `entity_id`, or an admission result — verified by
  reading the range, not by inference.
- **Drafts and tool calls are siblings from one model response.** `_model_phase` takes
  `result.structured` (drafts + `tool_calls`), calls `_emit_drafts`, and returns
  `(structured, drafted)`; `_tool_phase` then runs `structured["tool_calls"]`. The model
  wrote its tool arguments before the admission existed.

So the ordering **fact** E4 recorded is real, and its **inference** — *"the tools that
justify them"* — is false. A tick-N proposal is justified by ticks 1..N-1 evidence, and a
sibling tool failing does not retroactively unjustify it.

## Why A, on audit grounds

`IntentApplied` records **admission**, not execution. Under B, a `TOOL_FAILED` run would
discard the staged intent and leave **no record that the model decided anything**, while the
tools it requested failed. That is an audit regression against the posture AUDIT-TXN
established: the record should say what happened, and what happened is "a decision was
admitted, then a sibling tool failed."

The design note initially recommended A because B would move the S1–S3 baseline digests.
The Director rejected that as the reason: the baseline is an **instrument**, and a deliberate
amendment is exactly how it records a change. The ruling record carries the audit argument
instead, and says so.

## What landed

- The **design note** (`bb26500`): the §2.1 dependency inventory, the three options, and the
  recommendation.
- The **ruling** (`d8b96fa`): the six-point record, a rewritten §3 that leads with the audit
  reason, and an explicit reclassification — *the ordering is confirmed; the justification
  inference is rejected*.
- The **probe** now asserts the documented ordering under a name that says so
  (`test_proposals_are_admitted_before_the_sibling_tool_batch`). **Every observation is
  unchanged** (`FAILED`, `TOOL_FAILED`, exactly one applier call, `INSERT_TASK`); only its
  claim and its failure message moved. If the ordering ever changes, the probe still fails.
- **`_tick`'s docstring** states the contract, so a reader of the tick does not need the IDR.
- **The baseline** records that S6 is intended — a pin, not a defect marker.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Probe + baseline | **7 passed** |
| LOOP-1..4 suites | **53 passed** |
| Full suite | **5059 passed / 3 skipped / 0 failed** |
| `stamp_suite_count.py --check` | `collected=5062` |
| `check_census.py` | **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0 |
| B4 ref graphs | **24 passed** |
| `ruff` / `pyright src` / tests | **All checks passed** / **0/0/0** / **0 errors, 1 known warning** |
| `run.py` diff | docstring only (one hunk; AST identical after stripping docstrings) |

## Residuals

1. **E4 remains a live ordering**, now intended and pinned. A future change to the tick order
   will fail the probe — deliberately.
2. **B is not forbidden forever.** It would require an audit-contract decision, not just a
   baseline amendment: the record of a decision would have to be judged less important than
   suppressing an admission whose sibling action failed.
3. The LOOP track now has **no open row**. What remains is the parked set (G5 adaptivity,
   G6 hang preemption, G7 durable working memory, G3b CLI entry) and the PROVIDER residuals.

## Prohibited-claims discipline

This gate reclassifies a finding and documents an ordering. It claims no improvement, no
behaviour change, and no new guarantee. The loop behaves exactly as it did before the slice;
what changed is the record of what that behaviour means.

License: Apache-2.0 (LICENSE).
