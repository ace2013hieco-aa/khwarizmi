# OPS-14 — operational notes

OPS-14 closes the last two contract gaps of the same family OPS-13 opened:
`profile` and `inputs` were legal `INSERT_TASK` payload keys whose value set and
shape the validator enforced and the contract never stated. Run 6 refused 6 of
10 drafts on `MALFORMED_PAYLOAD: payload.profile must be an AgentProfile value`;
run 7 added `MALFORMED_PAYLOAD: payload.inputs must be a list of strings`. The
contract now states both, from the validator's own sources.

## The rendered lines

For each profile whose declared kinds include `INSERT_TASK`:

> For INSERT_TASK, the payload key "profile" is optional (omitting it takes the
> runtime's default); when supplied it must be one of: ADVERSARY,
> DETERMINISTIC, DIRECTOR, IMPLEMENTER, RESEARCHER. Any other value is refused.

> For INSERT_TASK, the payload key "inputs" is optional (omitting it admits an
> empty list); when supplied it must be a list of strings. Any other value is
> refused.

The `profile` line sits with the OPS-13 value-set lines (same renderer, same
provenance); the `inputs` clause is the next block in the same place. Profiles
without `INSERT_TASK` in `authority.proposable_kinds` (critic, verifier) carry
neither line. Values are sorted for determinism.

## Where each fact comes from

| Fact | Source |
| --- | --- |
| The legal `profile` values | `_PROFILE_VALUES = frozenset(member.value for member in AgentProfile)` (`gateway.py:1366`) — derived from the enum, never a typed list |
| Which kinds carry the key | `INTENT_PAYLOAD_VALUE_SETS[IntentKind.INSERT_TASK]["profile"]` (`gateway.py:1378`), beside `INTENT_PAYLOAD_KEYS` |
| The `profile` refusal | `_payload_to_node` parses a supplied value through `AgentProfile` (`gateway.py:4147-4153`); a non-member raises `MALFORMED_PAYLOAD` |
| The `inputs` shape | `_PAYLOAD_LIST_SHAPE = "a list of strings"` (`gateway.py:1385`); the validator's refusal interpolates the same constant (`gateway.py:4135`), so the prompt and the check cannot disagree |
| Which kinds carry the shape | `INTENT_PAYLOAD_SHAPES[IntentKind.INSERT_TASK]["inputs"]` (`gateway.py:1392`), beside the value-set map |
| The `inputs` refusal | `_require_str_list` reads `payload.get(key, [])` and checks `list` of `str`; anything else raises `MALFORMED_PAYLOAD` |
| `profile` optionality | `AgentRuntime._derive_payload` calls `payload.setdefault("profile", spec.agent_profile)` (`run.py:1054`) before the intent is built |
| `inputs` optionality | the validator itself: `_require_str_list` reads an absent key as `[]` (`gateway.py:4131`) — there is no runtime default for it |

## Optionality: two different defaults, stated differently

`profile` **is** defaulted at the draft surface. `_derive_payload` supplies
`spec.agent_profile` for every `INSERT_TASK` draft, so an omitted key never
reaches the gateway empty:

| profile | default `agent_profile` |
| --- | --- |
| planner | DIRECTOR |
| researcher | RESEARCHER |
| experimenter | IMPLEMENTER |
| synthesizer | DIRECTOR |

(These are the four profiles that can draft `INSERT_TASK`; critic and verifier
declare no task kind and carry neither line.) The sentence therefore says
"omitting it takes the runtime's default", exactly as OPS-13 does for
`task_type`. The validator has **no** default of its own: a payload that reaches
`_payload_to_node` without `profile` admits with `profile = None`
(`test_an_omitted_profile_admits_as_null`). Calling the key "required" would be
stricter than the draft surface; calling it "optional" without naming the
default would hide where the value comes from.

`inputs` is **not** defaulted by the runtime. `_derive_payload` leaves it
absent, and `_require_str_list` reads an absent key as an empty list. The
sentence says so — "omitting it admits an empty list" — rather than borrowing
the runtime-default wording, which would be false for this key.

## The drift guard

`test_profile_drift_flows_into_the_contract` monkeypatches
`hermes.research.gateway.INTENT_PAYLOAD_VALUE_SETS` to
`{"profile": frozenset({"PROBE_PROFILE"})}` and asserts the rendered contract
follows: `PROBE_PROFILE` appears, `DIRECTOR` disappears, and the sentence's
value clause is exactly `must be one of: PROBE_PROFILE. Any other value is
refused.` `test_shape_drift_flows_into_the_contract` does the same for
`INTENT_PAYLOAD_SHAPES` (`"a probe shape"`), proving the `inputs` clause is
generated from the constant too, not written once in `cloud.py`.
`test_without_the_injected_sets_the_clauses_are_absent` is the other half: a
contract that stopped carrying the injected rules renders neither line.

`test_the_value_set_is_the_agent_profile_enum` is the enum-equality half, as
OPS-13's `test_the_value_set_is_the_node_type_enum` is for `NodeType`:
`INTENT_PAYLOAD_VALUE_SETS` must equal, exactly,

```python
{IntentKind.INSERT_TASK: {
    "task_type": frozenset(member.value for member in NodeType),
    "profile": frozenset(member.value for member in AgentProfile),
}}
```

and `set(PROFILE_VALUES) == {member.value for member in AgentProfile}`. A
hand-typed set that drifts from the enum fails here.

## The line that did not move

Guidance, not enforcement. An unknown `profile` still refuses
`MALFORMED_PAYLOAD` (`test_an_unknown_profile_still_refuses_malformed_payload`,
using the plausible string `ARCHITECT`); a non-list `inputs` and a list with a
non-string element still refuse with the validator's own message
(`test_a_non_list_inputs_still_refuses_malformed_payload`,
`test_a_non_string_input_still_refuses_malformed_payload`). A legal profile
still drafts and still admits (`test_a_legal_profile_still_drafts`,
`test_a_legal_profile_still_admits`); supplied inputs are admitted in order
(`test_supplied_inputs_are_admitted_in_order`).

The composition root reads the shape map through `live_contract_rules()`, now a
four-tuple (availability, payload keys, payload values, payload shapes), and
injects it into the model call. The runtime and the model plane still never
import the research gateway.

## Invariants

- No new event, field, write or transaction. Census unchanged: 124 / 28
  (19/5/4) / 1 / 15 / 0.
- The LOOP baseline does not move: M1 stays 304 (the contract is the system
  message, not `request.prompt`).
- Drain-only unchanged; B4 stays 24. Governed docs untouched.
  `proposable_kinds` untouched.
- No key material anywhere.

## Cost

System prompt: **+382 bytes** for each of the four task profiles (experimenter,
planner, researcher, synthesizer); **+0** for critic and verifier. Of the 382,
219 bytes are the `profile` line and 161 the `inputs` line, plus one newline
each.

License: Apache-2.0 (LICENSE).
