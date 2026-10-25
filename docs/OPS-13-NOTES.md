# OPS-13 — operational notes

OPS-13 closes run 5's one remaining contract gap: `task_type` was rendered as a
legal `INSERT_TASK` payload key, but the values it accepts were never stated.
The model supplied a plausible non-`NodeType` string and the validator refused
it (`MALFORMED_PAYLOAD: payload.task_type must be a NodeType value`). The
contract now states the enumeration, and only the enumeration.

## The rendered line

For each profile whose declared kinds include `INSERT_TASK`:

> For INSERT_TASK, the payload key "task_type" is optional (omitting it takes
> the runtime's default); when supplied it must be one of: AGENT_TASK, GATE,
> HUMAN_GATE, SUBGRAPH, TOOL_TASK. Any other value is refused.

Profiles without `INSERT_TASK` in `authority.proposable_kinds` (critic,
verifier) carry no such line. The values are sorted for determinism.

## Where each fact comes from

| Fact | Source |
| --- | --- |
| The legal values | `_TASK_TYPE_VALUES = frozenset(node.value for node in NodeType)` — derived from the enum, never a typed list |
| Which kinds carry the key | `INTENT_PAYLOAD_VALUE_SETS` (beside `INTENT_PAYLOAD_KEYS`); only `INSERT_TASK`, the one task kind a model may propose (`ADMIT_TASK` is `internal_only`) |
| The refusal | `_payload_to_node` parses `_require_str("task_type")` through `NodeType`; a non-member raises `MALFORMED_PAYLOAD` |
| Optionality | `AgentRuntime._derive_payload` calls `payload.setdefault("task_type", "AGENT_TASK")` before the intent is built |

**Why "optional" and not "required".** The validator *does* require the key:
a payload that reaches `_payload_to_node` without it refuses
`payload.task_type must be a non-empty string`. But the model never hands a
payload straight to the gateway — the runtime defaults `task_type` first, for
both proposal forms, so an omitted key is accepted at the draft surface. The
rendered sentence describes that surface. Calling the key "required" would be
guidance that is stricter than the behaviour; the pair of pins in
`tests/test_ops13_task_type_values.py` holds both halves
(`test_the_validator_requires_the_key_a_draft_may_omit_it`,
`test_omitting_the_key_drafts_with_the_runtime_default`).

The composition root reads `INTENT_PAYLOAD_VALUE_SETS` through
`live_contract_rules()` (now a three-tuple: availability, payload keys, payload
values) and injects it into the model call. The runtime and the model plane
still never import the research gateway.

## The drift guard

`test_value_set_drift_flows_into_the_contract` monkeypatches
`hermes.research.gateway.INTENT_PAYLOAD_VALUE_SETS` to
`{"task_type": frozenset({"PROBE_TASK"})}` and asserts the rendered contract
follows: `PROBE_TASK` appears, `AGENT_TASK` disappears, and the sentence's
value clause is exactly `must be one of: PROBE_TASK. Any other value is
refused.` `test_without_the_injected_set_the_line_is_absent` is the other half:
a contract that stopped carrying the injected set renders no line at all.

## The line that did not move

Guidance, not enforcement. An unknown `task_type` still refuses
`MALFORMED_PAYLOAD` (`test_an_unknown_task_type_still_refuses_malformed_payload`,
using the plausible string `RESEARCHER`), and a legal `NodeType` still drafts
and still admits (`test_a_legal_node_type_still_drafts`,
`test_a_legal_node_type_still_admits`).

## `kind None` — recorded, not changed

Run 5 also showed `ROLE: model proposed kind None` on HYPOTHESIS. The contract
already says `kind` is required in the single-proposal form, and the model
omitted it anyway; that is instruction-following variance, not a missing rule,
and a sixth sentence would be prose inflation. **Retry-with-feedback on a
contract-shape refusal is the candidate fix, and it is a loop behaviour change
needing its own gate.**

## Invariants

- No new event, field, write or transaction. Census unchanged: 124 / 28
  (19/5/4) / 1 / 15 / 0.
- The LOOP baseline does not move: M1 stays 304 (the contract is the system
  message, not `request.prompt`).
- Drain-only unchanged; B4 stays 24. Governed docs untouched.
  `proposable_kinds` untouched.
- No key material anywhere.

## Cost

System prompt: **+212 bytes** for each of the four task profiles
(experimenter, planner, researcher, synthesizer); **+0** for critic and
verifier.

License: Apache-2.0 (LICENSE).
