# MERGE-LOG-OPS-8 — the contract names the legal kinds

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-8: render the profile's declared `proposable_kinds` into the contract |
| Base (`main` before) | `599b5a5` |
| Slice | `slice/ops-8-contract-kinds` — three commits, **fast-forwarded** |
| Landed tip | `cb0091012798c3b3a6ad3254d399a9b11b51cc65` |

```
 docs/OPS-8-NOTES.md               |  45 ++  (F3 + the M1 distinction)
 src/hermes/agents/runtime/run.py  |   4 +   (carry the tuple)
 src/hermes/tools/models/cloud.py  |   9 +-  (render it)
 src/hermes/tools/models/router.py |   6 +-  (contract object)
 tests/test_ops8_contract_kinds.py | 173 ++  (six profiles + three pins)
```

## What was broken

The model proposed `kind: "task-graph-planning"`. The runtime refused `ROLE` — correctly, because
`proposable_kinds` is a declared per-profile allowlist. But the contract said only *"The `kind`
field names the proposal kind"*: the closed set existed, was enforced, and was **never shown to
the model**.

## What landed

`ProfileSpec.authority.proposable_kinds` — the same tuple `refuses_by_authority` enforces — is
carried into the contract and rendered beside the field:

```
The "kind" field names the proposal kind. Use exactly one of:
INSERT_TASK, BRANCH, ABANDON, REQUEST_HUMAN. Any other value is refused.
```

One line per profile, asserted exactly for all six (not sampled). The test also asserts every
profile's declared kinds fall inside the router's injected allowlist, so the guidance can never
name a value the router always refuses.

## Guidance, not enforcement

`test_the_listing_is_guidance_not_the_enforcement` builds a contract that *claims*
`task-graph-planning` is legal and sends it — the router still refuses `ROLE`, because its
allowlist is separate from the contract text. A profile edit cannot widen authority through the
prompt.

## The metric correction

My charter said "M1 moves again; report the new number". **That was wrong**, and the agent said so:
M1 measures `request.prompt`, while the contract is the **system** message. M1 stays **304** for
the same question; the system message grows (+90 to +124 bytes depending on the profile, ~23 input
tokens for the planner).

The agent declined to force M1 upward by folding the system text in or duplicating the contract as
an envelope — either would change what the metric means, and the first would move the baseline.
That is the right call: a metric bent to show progress stops being a metric.

## What it changed in practice — run 3

| | Run 2 | Run 3 |
| --- | --- | --- |
| Termination mix | `OTHER:3` | **`SUCCEEDED:5`** |
| Admissions | 0 | 0 |
| M1 | 304 | 304–577 |

The model now drafts legal kinds and the stages complete. Admissions are still zero, for a
**different** reason: it emits both proposal forms at once (OPS-9). That is progress measured
honestly — the layer moved, the outcome did not.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted | **157 passed**; Director re-ran **121** at the merged tip |
| Full suite | **5115 passed / 3 skipped / 0 failed** |
| `stamp_suite_count.py --check` | `collected=5118` — verified in a clean tree |
| `check_census.py` | **PASS** — unchanged |
| B4 / baseline | **24** / unchanged and passing |
| `ruff` / `pyright src` / tests | clean / **0/0/0** / **0 errors, 1 known warning** |

License: Apache-2.0 (LICENSE).
