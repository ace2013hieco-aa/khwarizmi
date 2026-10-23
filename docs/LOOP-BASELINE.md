# LOOP-BASELINE — a measured baseline for the loop's output behaviour

| Item | Value |
| --- | --- |
| Slice | LOOP-M (measurement; runs before LOOP-5 implementation) |
| Base | `3111f76` (`main`) |
| Branch | `slice/loop-metrics` |
| Date | 2026-10-23 |
| Status | Baseline measured and pinned; no runtime change |

## 1. What this is, and what it is not

LOOP-1..4 removed four mechanical defects (content-free prompts, no evidence
retention/convergence, unbounded review, and a dropped run bound). None of
those changes had a baseline of the loop's *output behaviour*, so a claim that
they improved usefulness would be an assertion. This slice builds the
instrument, takes the baseline once, and pins it.

It is a **post-LOOP-1..4 baseline**. The pre-LOOP output numbers do not exist
and cannot be reconstructed; this table cannot retroactively prove that
LOOP-1..4 improved output. A usefulness claim is admissible only as
**movement against this table** with the corpus and the model layer held fixed.

It measures the **loop's mechanics on a scripted model**, not an LLM's research
quality. The model is a deterministic script; the tool results are scripted.
The scenario corpus is fixed, committed in `tests/test_loop_baseline.py`, and
hashed below; changing it is visible because the test pins the digests.

No composite "quality score" is defined. The vector is the result; a weighted
number would hide the trade-offs this baseline exists to expose.

## 2. Corpus

| # | Scenario | Exercises | Input SHA-256 |
| --- | --- | --- | --- |
| S1 | one tick, one proposal, one tool, evidence returns | happy path | `4a72a7e33fcb7a5293a74c6c2a06ec1947372d4e3c788ac21cd6fcc677e61192` |
| S2 | multi-tick evidence gathering until stability | convergence (LOOP-2) | `cf32bd51ccbff97c21b28107dbb14fa91cf768176957c42dc56f1a348b7162c7` |
| S3 | same tool and args twice, no new evidence | repeated-call measurement | `e778d77321fedf7ebe41e7c0b6f2080966a54d0f5453513bbf547d3db8f869b3` |
| S4 | review rejects, re-draft passes inside the cap | review rounds (LOOP-3) | `3fcca54627cd865474454f33e1ad13638d3e8d5a928fa14e22a499ac7dda200d` |
| S5 | review rejects until the cap | bounded rounds, terminal state | `9f763e00792317f30c63af5e28eaa962683dac892d908ad8ce320aa5e38d7074` |
| S6 | tool failure after drafts exist | **E4 — the LOOP-5 falsifier baseline** | `9649e90d6fe350baa402bb04e40bcbefe4938c203e64a800f5e64f9f5b2aeb63` |
| S7 | deadline expires mid-tick | run-level bound (LOOP-4) | `1c7d38df4b8899f0fe4b27f6c605c6e4b5595cd8f88bc2a9522f789b0eb600aa` |
| S8 | delegation to a child run | child accounting | `f86478c2951294a3df4f8d3d841314723e44cb1b2a31c86380145002219b67eb` |

Corpus SHA-256:
`44beb12e56ee87abed53bea14bab2dd48c4000809ba07af0ff3b8900df8f8f29`

Each input includes the declared profile, the scripted model outputs, the
scripted capability responses, the frozen context, the run limits, and the
clock advance (only S7 advances it). There is no network, no wall clock, no
sleep, and no randomness.

## 3. Baseline vector

M1 is prompt payload bytes (non-marker text) per model call, min / median /
max across the scenario's calls. `n/a` for M3 means no tick introduced zero
new evidence after the run had evidence; `n/a` for M4 means no review was
declared. M6 is the root run's admissions (including review/child-task
command admissions; see the notes).

| Scenario | Termination | Ticks | M1 prompt bytes (min/median/max) | Tools | M2 repeat rate | M3 new evidence per tick | M3 ticks→stable | M4 review used/cap; verdicts | M6 root admitted/dup/refused/other | Child runs/admitted |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S1 | STOP_WHEN | 1 | 148 / 148 / 148 | 1 | 0.00 | [1] | n/a | n/a | 1 / 0 / 0 / 0 | 0 / 0 |
| S2 | STOP_WHEN | 2 | 140 / 312.5 / 485 | 2 | 0.00 | [1,0] | 2 | n/a | 2 / 0 / 0 / 0 | 0 / 0 |
| S3 | STOP_WHEN | 2 | 124 / 296.5 / 469 | 2 | 0.50 | [1,0] | 2 | n/a | 1 / 1 / 0 / 0 | 0 / 0 |
| S4 | STOP_WHEN | 2 | 150 / 415 / 1421 | 0 | 0.00 | [0,0] | n/a | 2/2 FAIL -> PASS | 4 / 0 / 0 / 0 | 2 / 1 |
| S5 | STOP_WHEN | 2 | 140 / 410 / 1421 | 0 | 0.00 | [0,0] | n/a | 2/2 FAIL -> FAIL | 4 / 0 / 0 / 0 | 2 / 2 |
| S6 | TOOL_FAILED | 1 | 138 / 138 / 138 | 1 | 0.00 | [1] | n/a | n/a | 1 / 0 / 0 / 1 | 0 / 0 |
| S7 | TIMEOUT | 1 | 144 / 144 / 144 | 0 | 0.00 | [0] | n/a | n/a | 1 / 0 / 0 / 1 | 0 / 0 |
| S8 | TICK_LIMIT | 1 | 64 / 96 / 128 | 0 | 0.00 | [0] | n/a | n/a | 1 / 0 / 0 / 0 | 1 / 1 |

Notes:

- **S3** is the repeated-call case: one of two invocations repeats
  `(capability_id, args digest)`, so M2 is `0.50`; the second draft is a
  duplicate (`1 / 1`), not a second durable intent.
- **S4/S5** root admissions include the two review-task `INSERT_TASK`
  commands (one per round) plus the two drafts; the reviewer children's
  admissions are the objection proposals (`1` in S4, `2` in S5). S8 root
  admission is the child-task command; the child's admission is its own draft.
- **S6** is the baseline LOOP-5 must move: the draft is admitted before the
  tool fails, and the run terminates `TOOL_FAILED` with one other refusal.
  LOOP-5's expected movement is on this row, not on the rest of the table.
  Under ruling A (2026-10-23), this row is the documented, intended
  behaviour — a pin, not a defect marker; the earlier "must move" framing is
  historical.
- **S7**'s clock advances by 11 seconds on the first model call against a
  10-second declared bound; the draft is admitted before the terminal act, and
  the run reports `TIMEOUT`.

Aggregate across all 13 runs: admitted **19**, duplicate **1**,
intent-refused **0**, other refusals **2**; termination mix
**SUCCEEDED 11 / TOOL_FAILED 1 / TIMEOUT 1 / CANCELLED 0 / OTHER 0**.
The scenario-level `admitted` column is root-only; the aggregate includes child
admissions.

## 4. Trace digests (M0)

`Supervisor.trace_digest` hashes event kind, sequence, and detail; it does not
include the run id. Two structurally identical child runs can therefore share
a digest (S4/S5's first review child do). The test pins the exact values.

| Scenario | Root trace digest | Child trace digests |
| --- | --- | --- |
| S1 | `d0d8913e98dc21df86be6f626275f684139ff46ab704041a43584c33def2117f` | — |
| S2 | `75d1a73d29e4823ef2c45f0016de4caf53e37b71d25dd5f4bb1c0c6c02cae226` | — |
| S3 | `46489456219cfdd9a0e56f0b6cc589602530252886baa8579ca96bc2d72b308c` | — |
| S4 | `1b764dff6d1aea9476904e7c6a5178d734e15c3097531d7535497f40a48a579d` | `443a6989039bf11c2d1c4822795349a9f4e766c3f9fc66bbb5f4ec03cf291e65`, `eea161b7f7bc202011dcb33ad13a1c4a83432ce6f53b06dd3a50472e02f92052` |
| S5 | `3ebbbe731b67e5eb539c075fd133f64f4c94970e28550653e1f892fdcabc4ba6` | `443a6989039bf11c2d1c4822795349a9f4e766c3f9fc66bbb5f4ec03cf291e65`, `9f94fb98751292b59fc8bbc6c82d31ec1c2c4a40d477fc5cdf0ad57dcc819004` |
| S6 | `a2fab43e12af0c49089e7746714de9b0dd78c54a4af1acbd02c62395cf277acb` | — |
| S7 | `52bf20958f9fa7f3383c694f5c4c2d79fc9923e0651330b6271bf42f05e24652` | — |
| S8 | `f726a801d66069e3bffaff68959e7509d514694b38b6212de6ca943a39d8ae1e` | `bae2c4959cc730137e1dca695bb2cfde83ea1d99793ae2c0d9303d4be2c5c92c` |

## 5. Data sources (measured from outside)

| Metric | Source |
| --- | --- |
| M0 `trace_digest` | `AgentRuntime.supervisor.trace_digest(run_id)` after the run |
| M1 `prompt_payload_bytes` | test-owned model port's recorded `ModelRequest.prompt`; UTF-8 bytes of each envelope's `.text`, excluding the `runtime.tick` marker and the origin/ref labels |
| M2 `repeat_tool_rate` | test-owned capability port's actual invocations; `(capability_id, sha256(canonical arguments))` |
| M3 `evidence_novelty` / `ticks_to_stability` | the terminal checkpoint's `feedback` (`ToolFeedback.evidence_digest()`), read via `runtime.checkpoint(run_id)` |
| M4 `review_rounds` | `ProposalSet.review_verdicts` and the profile's declared `review.max_review_rounds` |
| M5 `termination_mix` | `ProposalSet` / checkpoint `state` and `termination` |
| M6 `admitted_proposals` | `ProposalSet.proposals` admission verdicts plus `ProposalSet.refusals` |

No runtime module was instrumented, no event kind or detail field was added,
and no durable write was introduced. The test-owned model and capability ports
record the calls the runtime makes; the runtime's own public run surface
(`ProposalSet`, checkpoint, trace) supplies the rest.

## 6. Reproduce

```
.venv/Scripts/python.exe scripts/run_tests.py tests/test_loop_baseline.py -v
```

The test builds the corpus, runs every scenario, computes the vector, and pins
the table, the per-scenario input digests, and the corpus digest. It also runs
the corpus twice and asserts identical vectors and identical trace digests.
Run it twice in succession to reproduce the determinism proof.

`python tests/test_loop_baseline.py` prints the pinned vector and digests for
inspection; it is not the gate.

## 7. What this does and does not measure

- It measures the **loop's mechanics** on a scripted model: prompt payload
  presence/growth, tool repetition, evidence novelty and convergence, review
  rounds, termination, admissions/refusals, and trace reproducibility.
- It does **not** measure an LLM's research quality, scientific validity,
  reproducibility, or the usefulness of any research claim. A scripted model
  cannot exhibit those.
- It is **post-LOOP-1..4**. Pre-LOOP output numbers do not exist and cannot be
  reconstructed; no statement here proves LOOP-1..4 improved output.
- A usefulness claim is admissible only as **movement against this table** with
  the corpus and model layer held fixed. A changed corpus or a different model
  is a different measurement, not a movement.
- The table is a vector, not a score. No composite quality number is defined.

License: Apache-2.0 (LICENSE).
