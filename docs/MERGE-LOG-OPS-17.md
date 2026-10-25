# MERGE-LOG-OPS-17 — the cap and the list shapes stated; the chain completes

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-17: the 4 KiB proposal cap and the `_require_str_list` family |
| Base (`main` before) | `98eb28a` |
| Landed tip | `0ed3f7fb34f77acb3f0ffc71bd11dbb25e46fc0f` |

```
 docs/OPS-17-NOTES.md                   | 294 ++  (the inventory)
 src/hermes/agents/runtime/run.py       |   3 +
 src/hermes/research/gateway.py         |  17 +-
 src/hermes/tools/models/cloud.py       |  10 ++
 src/hermes/tools/models/router.py      |   6 +-
 tests/test_ops17_shape_gaps.py         | 319 ++
```

## Three conflicts the agent raised, and how they resolve

### 1. My charter misquoted the refusal

I wrote that an over-cap proposal is "refused". The code says:

> `the body is not preserved — an overflowed body is not parsed`

The agent did **not** change the message to match my charter — it pinned the code's actual text. That
is the right direction: the charter is a brief, the code is the record.

### 2. "Every remaining refusal is semantic" — wrong, and corrected

I wrote that in the roadmap. The agent's inventory shows otherwise: proposal/tool-call item schemas,
delegation values and bounds, `INSERT_TASK` scalar types, `EVIDENCE_TRANSITION` state rules and the
`PROPOSE_RESEARCH_PROGRAM` nested schema are all still unstated. The **observed** refusals are mostly
read-port; the **inventory** is not. That distinction matters, and I've corrected the roadmap rather
than leaving my sentence standing.

### 3. A transient field was added — accepted

`OutputContract.max_proposal_bytes: int = 0`, populated from `MAX_PAYLOAD_BYTES` at build time and
rendered into the contract mapping. **Ruling: accepted.** My invariant was about durable state —
events, writes, transactions, the census. A prompt-configuration field *derived from the constant* is
precisely how the prompt reads that constant, which is what the drift guard requires. It is not
config-settable and not persisted; if it ever became either, that would be a different slice.

## What landed

> The whole reply must be at most 4096 bytes. A proposal over the cap is refused, and no artifact
> overflow port is wired today, so an over-cap body is neither preserved nor parsed.

plus the `_require_str_list` family — `inputs`, `outputs`, `dependencies`, `provenance` — for the four
task-drafting profiles. Exactly the keys the validator checks; no scalar keys were invented into the
family, which was the charter's explicit instruction.

Drift guards demonstrated by patching `MAX_PAYLOAD_BYTES` to 2048 and `INTENT_PAYLOAD_SHAPES` to a
probe: the sentences follow, and the absent-injection tests prove neither is hard-coded.

## What it changed — run 10

```
runs 9, admitted 9, SUCCEEDED:8/OTHER:1, 17 calls
```

**The chain completed:** QUESTION → HYPOTHESIS → PREDICTION → EXPERIMENT → OBSERVATION → EVIDENCE →
CLAIM → CRITIQUE → **CONCLUSION**. All nine stages. CONCLUSION failed on `MODEL_REFUSED` after the
cap was exceeded again (5824 bytes), so the methodology did not close — but every stage ran.

## The remaining six refusals

| Code | Detail | Class |
| --- | --- | --- |
| `PROPOSAL` ×2 | `dependency mnode_… does not exist` | **read port** |
| `PROPOSAL` ×1 | `evidence artifact '…' not in project` | **read port** |
| `PROPOSAL` ×1 | `scope brief '…' not governed: ScopeBrief not found` | **read port** |
| `PROPOSAL` ×1 | `REQUEST_ADDITIONAL_EXPERIMENT is declared but its gateway validator is not wired` | availability |
| `RATIONALE` ×1 | `exceeded the 4096-byte cap (5824 bytes)` | instruction-following |

**Four of six are the read port.** The model cannot see which nodes, artifacts and scope briefs exist,
so it invents them. The availability one is notable: the contract *does* say which kinds are
unavailable, and the model chose one anyway — the same instruction-following variance as `kind None`,
now on a different field.

And the cap statement did not stop the overrun: the model still wrote 5,824 bytes with a 4,096-byte
limit printed in its system message. A sentence is not a constraint.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted | **94 passed**; Director re-ran **61** at the merged tip |
| Full suite | **5216 passed / 3 skipped / 0 failed** (5219 collected) |
| `stamp_suite_count.py --check` | `collected=5219` |
| `check_census.py` | **PASS** — unchanged |
| B4 / baseline | **24** / unchanged |
| `ruff` / `pyright` | clean / **0/0/0** |

License: Apache-2.0 (LICENSE).
