# MERGE-LOG-OPS-9 — the contract states what the validator enforces

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-9: the two proposal forms are exclusive; the delegation keys are named |
| Base (`main` before) | `cb00910` → landed on `89b76a8` by **cherry-pick** (OPS-9 branched before the OPS-8 merge log) |
| Landed tip | `7d3dca8` |

```
 docs/OPS-9-NOTES.md               |  54 ++  (F2 blocking, the flake, the uncovered rules)
 src/hermes/agents/runtime/run.py  |  21 +-  (the form-field constants)
 src/hermes/tools/models/cloud.py  |  14 ++  (render both statements)
 src/hermes/tools/models/router.py |  10 ++  (carry them)
 tests/test_ops9_contract_rules.py | 193 ++  (drift guard + three pins)
```

## What it fixes

Run 3's refusals were `MALFORMED_PAYLOAD: carries both the single-proposal and the
multi-proposal form` and `a delegation declares unknown keys: ['task','to']`. The model filled in
both forms because the prompt described both fields and never said *one or the other*.

The contract now ends with:

```
Choose exactly one proposal form: the single-proposal form (a top-level "kind" field)
or the multi-proposal form (a "proposals" array). A reply carrying both is refused;
exactly one is allowed.
If you output a "delegations" array, each item may carry only these keys:
profile, spec, task_type. An unknown key is refused.
```

## The method change — and the point of the slice

Both statements are rendered from the **validator's own constants**
(`SINGLE_PROPOSAL_FIELD`, `MULTI_PROPOSAL_FIELD`, `DELEGATION_KEYS`), not typed into prose.

`test_the_prompt_reads_the_validator_key_set` monkeypatches `DELEGATION_KEYS` to add `probe_key`,
rebuilds the contract, and asserts the key appears in the prompt. Demonstrated against a stale
prompt:

```
mutated validator keys: ['probe_key', 'profile', 'spec', 'task_type']
stale prompt missing: ['probe_key']
```

That is the guard the four-layer chain needed. Layers 1–3 were each a hand-written sentence that
had drifted from a check; layer 4 now cannot drift silently.

## Guidance, not enforcement

The three pins: a reply with both forms refuses `MALFORMED_PAYLOAD`; an unknown delegation key
refuses; a single-form and a multi-form reply with a legal kind both draft. The runtime checks are
unchanged and still use `DRAFT_KEYS` / `DELEGATION_KEYS` directly — the contract text is never
parsed.

## Cost

**+321 bytes** to every profile's system prompt (profile-invariant statements). M1 stays **304** —
it measures the user prompt, and the contract is the system message.

## Recorded, not covered

The note lists the validator rules still unstated: the top-level "no other keys" rule, the
`proposals` item schema, the `tool_calls` schema, and the delegation item constraints (declared
profile, mapping spec, task type, depth bounds). The recommended next slice takes the top-level
"no other keys" plus the `proposals` / `tool_calls` item schemas — not everything at once.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted | **150 passed**; Director re-ran the OPS-9/10 set at the merged tip |
| Full suite | **5122 passed / 3 skipped / 0 failed** |
| `stamp_suite_count.py --check` | `collected=5125` |
| `check_census.py` | **PASS** — unchanged |
| B4 / baseline | **24** / unchanged |
| `ruff` / `pyright` | clean / **0/0/0** |

License: Apache-2.0 (LICENSE).
