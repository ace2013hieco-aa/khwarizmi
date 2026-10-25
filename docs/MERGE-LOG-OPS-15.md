# MERGE-LOG-OPS-15 — one informed retry, and it earned its cost

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-15: retry a contract-shape refusal once, with the refusal as feedback |
| Base (`main` before) | `fd66a65` |
| Slice | `slice/ops-15-retry-feedback` — rebased onto `fd66a65`, four commits, **fast-forwarded** |
| Landed tip | `b2f26270b92fe34477fa76256311f5aab3c2befc` |

```
 docs/idr/LIVE-CONTRACT-RETRY.md         | 679 +++  (the gate, rebased)
 docs/OPS-15-NOTES.md                    | 115 ++  (rulings + OPS-16)
 src/hermes/agents/runtime/assembly.py   |  37 ++  (`runtime.contract_feedback`)
 src/hermes/agents/runtime/run.py        | 114 +-  (the predicate, the retry)
 src/hermes/agents/runtime/supervisor.py |   8 +
 src/hermes/tools/models/cloud.py        |   8 +-  (escaping both tag directions)
 src/hermes/tools/models/router.py       |  47 +-  (the marker at 9 sites)
 tests/test_ops15_contract_retry.py      | 508 ++
```

## What landed

A refusal is marked `contract_feedback=True` at **exactly** the whole-reply output-validation
sites — 8 true, 1 false. `_retryable_model_refusal` reads that boolean, with
`RETRYABLE_MODEL_REFUSALS` kept as the LOOP-4 fallback. The bound is
`min(1, supervisor_retry, call_budget - 1)`, so a second refusal is terminal and a third call is
impossible.

**The guard against future drift is static, not behavioural:** a test parses `router.py` and
requires **all nine** `raise _Refusal(...)` calls inside `_validate_output` to state
`contract_feedback=` explicitly. A new site cannot inherit the default by omission — it has to
decide. That is the right shape for a rule that will otherwise be forgotten.

## The live proof — run 9

Two retries fired and **both converted**:

| Stage | Run 8 | Run 9 |
| --- | --- | --- |
| QUESTION | `FAILED/MODEL_REFUSED` (attempt 1) | `SUCCEEDED`, `ref=0` |
| HYPOTHESIS | `SUCCEEDED` with a refusal | `SUCCEEDED`, `ref=0` |

```
runs 9 → 7,  admitted 7 → 8,  OTHER 2 → 1,  calls 16 → 15
```

More admissions in fewer runs, and the two stages most prone to `kind None` now come through clean.
That is the retry paying for itself in a single run.

## The escaping extension

`render_user` now escapes `</?\s*untrusted` — both tag directions — where it previously escaped only
closing tags. Under the old regex a forged opening tag rendered **2** openers; now it renders **1**
and escapes the forgery. Two tests prove the widening changed nothing else: one compares the new
renderer byte-for-byte against a legacy copy over payload JSON, observation bodies, the tick marker
and prose; the other does the same for **every prompt a clean runtime run actually recorded**. The
baseline and LOOP batteries pass unchanged.

## The claim, stated precisely

> **OPS-16 — model-call accounting.** The Controller's `per_run_tokens` envelope counts provider
> transport requests, and the methodology handler reports zero of them; model calls are therefore
> not charged to it. Until OPS-16 lands, **no run may be described as spend-capped**: OPS-15 bounds
> model calls per phase per tick, not tokens or dollars.

That sentence is in the note verbatim. The retry spends real money; the declared cap does not see
it; saying so is the only honest option.

## What run 9 exposed next

The chain reached **CLAIM** and stopped, and the refusals are now almost entirely semantic:

| Code | Count | Detail |
| --- | --- | --- |
| `PROPOSAL` | 2 | `dependency mnode_… does not exist` |
| `PROPOSAL` | 1 | `evidence artifact 'synthetic-sars9/e1' not in project` |
| `RATIONALE` | 1 | `proposal exceeded the 4096-byte cap (5811 bytes)` |

The first three are the **read port** gap — the model cites ids it cannot verify exist. The fourth is
a contract gap and a cheap one: the 4 KiB cap is enforced and never stated.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted | **129 passed**; Director re-ran **81** at the merged tip |
| Full suite | **5198 passed / 4 skipped / 0 failed** (5202 collected) |
| `stamp_suite_count.py --check` | `collected=5202` |
| `check_census.py` | **PASS** — unchanged |
| B4 / baseline | **24** / unchanged, pinned digests unmoved |
| `ruff` / `pyright` | clean / **0/0/0** |

The skip count moved 3 → 4 between the pre-stamp and final runs with the same 5202 collected and no
failure; the agent flagged it rather than smoothing it over.

License: Apache-2.0 (LICENSE).
