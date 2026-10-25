# OPS-17 — operational notes

OPS-17 closes the last two contract gaps in the "state what the validator
enforces" family. Run 9's CLAIM stage refused a 5811-byte proposal:

> `RATIONALE`: the model proposal exceeded the 4096-byte cap (5811 bytes); no
> artifact overflow port is wired, so the proposal is refused

and run 8's HYPOTHESIS stage refused a string `provenance`:

> `MALFORMED_PAYLOAD`: payload.provenance must be a list of strings

Both rules were enforced and never stated. The contract now renders the cap
from `MAX_PAYLOAD_BYTES`, the same constant the overflow refusal interpolates,
and the full `_require_str_list` family from `INTENT_PAYLOAD_SHAPES`.

## The rendered statements

Every profile (all six) now carries the cap line:

> The whole reply must be at most 4096 bytes. A proposal over the cap is
> refused, and no artifact overflow port is wired today, so an over-cap body is
> neither preserved nor parsed.

Each of the four task-drafting profiles (experimenter, planner, researcher,
synthesizer) carries four shape lines; critic and verifier carry none, because
they do not declare `INSERT_TASK`:

> For INSERT_TASK, the payload key "dependencies" is optional (omitting it
> admits an empty list); when supplied it must be a list of strings. Any other
> value is refused.

> For INSERT_TASK, the payload key "inputs" is optional (omitting it admits an
> empty list); when supplied it must be a list of strings. Any other value is
> refused.

> For INSERT_TASK, the payload key "outputs" is optional (omitting it admits an
> empty list); when supplied it must be a list of strings. Any other value is
> refused.

> For INSERT_TASK, the payload key "provenance" is optional (omitting it admits
> an empty list); when supplied it must be a list of strings. Any other value
> is refused.

The `inputs` line is the OPS-14 line, unchanged. The three new lines are the
rest of the same validator family; `_payload_to_node` passes exactly these four
keys through `_require_str_list` (`gateway.py:4198-4201`).

## Where each fact comes from

| Fact | Source |
| --- | --- |
| The cap number | `MAX_PAYLOAD_BYTES = 4096` (`agents/runtime/types.py:73`), interpolated by the overflow refusal (`run.py:920`) |
| The cap carried into the contract | `output_contract_for(... max_proposal_bytes=MAX_PAYLOAD_BYTES)` (`run.py:361`) |
| The cap rendered | `render_system` (`tools/models/cloud.py:245-255`) |
| The list shape | `_PAYLOAD_LIST_SHAPE = "a list of strings"` (`gateway.py:1385`), the same phrase `_require_str_list` puts in its refusal (`gateway.py:4141-4142`) |
| Which keys carry the shape | `INTENT_PAYLOAD_SHAPES[IntentKind.INSERT_TASK]` (`gateway.py:1394-1400`) |
| The keys in that family | the four `_require_str_list(...)` calls in `_payload_to_node` (`gateway.py:4198-4201`) |
| Omission semantics | `_require_str_list` reads `payload.get(key, [])` (`gateway.py:4138`), so an absent key admits an empty list; there is no runtime default for these keys |

The model plane's whole-proposal check creates the overflow at
`ModelPlanePolicy.max_proposal_bytes`, whose default is `MAX_PROPOSAL_BYTES`
(`router.py:1252`, check at `:1961`). The two constants and the journal's
`DEFAULT_PAYLOAD_MAX_BYTES` are pinned equal in
`test_the_two_cap_constants_agree`; if one moves alone the statement would
describe a check the model does not actually face, so the drift fails a test.

## The three shape lines that were not in the charter's headline

The charter named `provenance` and said to include any other key in the same
family the validator checks. `outputs` and `dependencies` are the other two
`_require_str_list` keys. `inputs` was already mapped by OPS-14. No other task
payload key is in this family: the scalar checks (`spec` object, `iteration`
int, `max_retries` int, the nullable strings) have bespoke messages and no
shared shape constant, so they are **not** mapped here. They remain unstated
and are listed below.

## The code's refusal text differs from the charter's quote

The charter's §1 quote ends "no artifact overflow port is wired, so the
proposal is refused". The base code's message at `run.py:920-923` ends:

```
... no artifact overflow port is wired, so the body is not preserved
— an overflowed body is not parsed
```

OPS-17 does not change the message. The new pin
`test_an_over_cap_proposal_still_refuses_with_the_same_message` asserts the
code's actual text, with code `RATIONALE` and the observed 5811-byte size. The
charter quote is a paraphrase, not a second message the code emits.

The same cap governs two other runtime sites with different messages: the
derived `INSERT_TASK` payload (`run.py:968`), and the delegated child command
(`run.py:1456`); `delegated payload` has its own refusal in
`delegate.py:272-280`. All remain `RATIONALE`, all use `MAX_PAYLOAD_BYTES`, and
none changed.

## Drift guards

- `test_cap_drift_flows_into_the_contract` monkeypatches
  `hermes.agents.runtime.run.MAX_PAYLOAD_BYTES` to 2048, rebuilds the contract
  and asserts `max_proposal_bytes == 2048`, the 2048-byte sentence appears and
  the 4096-byte sentence disappears.
- `test_shape_drift_flows_into_the_contract` monkeypatches
  `hermes.research.gateway.INTENT_PAYLOAD_SHAPES` to
  `{"provenance": "a probe provenance shape"}`, asserts the provenance clause
  follows, the other family lines disappear and the old phrase is absent.
- The other halves: `test_without_the_injected_cap_the_statement_is_absent`
  and `test_without_the_injected_shapes_the_family_is_absent` render a contract
  that stopped carrying the rules and prove neither sentence is hard-coded.
- `test_the_shape_map_is_exactly_the_str_list_family` and the updated OPS-14
  map pin keep the map exact: no invented key, no missing family member.

## Refusal pins and happy paths

- Over-cap whole proposal: refused `RATIONALE`, state `FAILED`, termination
  `MODEL_REFUSED`, exact message above.
- `provenance` as a string: refused `MALFORMED_PAYLOAD`,
  `payload.provenance must be a list of strings`.
- Each of `dependencies`, `inputs`, `outputs`, `provenance` as a string:
  refused `MALFORMED_PAYLOAD` with its own key in the message.
- `provenance` as `["note:one", "note:two"]`: admitted in order.
- All four keys as lists on one draft: drafts with no refusals.
- The live CLI composition renders the cap and all four shape lines in the
  actual system message.

## System-byte deltas

Measured with `render_system` over the live contract mapping, before (base
`98eb28a`) and after:

| Profile | Before | After | Delta |
| --- | ---: | ---: | ---: |
| critic | 1755 | 1934 | +179 |
| experimenter | 2525 | 3201 | +676 |
| planner | 2449 | 3125 | +676 |
| researcher | 2565 | 3241 | +676 |
| synthesizer | 2801 | 3477 | +676 |
| verifier | 1784 | 1963 | +179 |

The cap line is 178 bytes plus its newline for every profile. The three new
shape lines are 167 (`dependencies`), 162 (`outputs`) and 165 (`provenance`)
bytes plus one newline each for the four task profiles: 497 bytes. M1 is
unchanged because the contract is the system message, not `request.prompt`.

## Every remaining refusal the contract does not state

Scope: refusals reachable from a model reply in the shipped profiles. The
declared-but-unwired kinds (`ABANDON`, `BRANCH`, `REQUEST_HUMAN`,
`REQUEST_REPLICATION`, `REQUEST_ADDITIONAL_EXPERIMENT`) are already covered by
the availability sentence and the gateway's `NOT_WIRED` refusal. Semantic
refusals are marked **[read port]**: they cannot be fixed by a sentence because
the model must be able to verify the referenced id exists.

### Whole-reply and item shape (runtime / model plane)

| Refusal | Code | Source |
| --- | --- | --- |
| empty reply | `MALFORMED_PAYLOAD` | `router.py:2047-2049` |
| reply is not valid JSON | `MALFORMED_PAYLOAD` | `router.py:2051-2055` |
| reply is not a JSON object | `MALFORMED_PAYLOAD` | `router.py:2056-2059` |
| decision-shaped top-level key (`decision`, `verdict`, `adjudication`, `approved`, `rejected`) | `PROPOSAL` | `router.py:2060-2065` |
| unknown top-level key; the field list never says "no other keys" | `MALFORMED_PAYLOAD` | `router.py:2066-2073` |
| required field omitted (type/required wording is printed per field, the refusal is not) | `MALFORMED_PAYLOAD` | `router.py:2074-2081` |
| field of the wrong declared type | `MALFORMED_PAYLOAD` | `router.py:2082-2089` |
| field outside declared values (no live contract field uses it today) | `MALFORMED_PAYLOAD` | `router.py:2090-2093` |
| `proposals` is not a list / an item is not a mapping | `MALFORMED_PAYLOAD` | `run.py:1028-1038` |
| proposal item unknown keys; only `kind`/`rationale`/`payload` | `MALFORMED_PAYLOAD` | `run.py:1044-1050` |
| item `kind` missing, not a string, or not an `IntentKind` | `MALFORMED_PAYLOAD` | `run.py:1051-1061` |
| item rationale missing/empty | `RATIONALE` | `run.py:1073-1076` |
| item payload not a mapping | `MALFORMED_PAYLOAD` | `run.py:1080-1084` |

The charter deliberately excludes the `proposals` and `tool_calls` item
schemas from OPS-17; they stay listed here so the next gate can choose them.

### Tool calls (runtime; excluded from OPS-17 by the charter)

| Refusal | Code | Source |
| --- | --- | --- |
| `tool_calls` not a list of mappings | `MALFORMED_PAYLOAD` | `run.py:1211-1215` |
| batch exceeds `max_tool_calls`, refused whole | `MALFORMED_PAYLOAD` | `run.py:1218-1222` |
| unknown tool-call key | `MALFORMED_PAYLOAD` | `run.py:1225-1229` |
| missing `capability_id` | `MALFORMED_PAYLOAD` | `run.py:1263-1266` |
| capability outside the profile's declared tools; the contract never lists a profile's tools | `ROLE` | `run.py:1270-1274` |
| `arguments` not a mapping | `MALFORMED_PAYLOAD` | `run.py:1301-1304` |
| capability plane refusal / capability failure (environmental) | forwarded / `MALFORMED_PAYLOAD` | `run.py:1317-1347` |

### Delegations (runtime; keys are stated, values and bounds are not)

| Refusal | Code | Source |
| --- | --- | --- |
| `delegations` not a list of mappings | `MALFORMED_PAYLOAD` | `run.py:1368-1372` |
| child runs disabled by the run's limits | `MALFORMED_PAYLOAD` | `run.py:1402-1405` |
| delegation depth exceeded | `MALFORMED_PAYLOAD` | `run.py:1406-1410` |
| child-run budget exhausted | `MALFORMED_PAYLOAD` | `run.py:1411-1415` |
| delegation `spec` not a mapping | `MALFORMED_PAYLOAD` | `run.py:1416-1418`; `delegate.py:260-265` |
| child `profile` not declared | `ROLE` | `delegate.py:247-254` |
| child `task_type` not a `NodeType` value (reaches the gateway as the child command) | `MALFORMED_PAYLOAD` | `gateway.py:4140-4143` |
| delegated payload / child command over the cap | `RATIONALE` | `delegate.py:272-280`; `run.py:1450-1460` |

### `INSERT_TASK` scalar shapes and semantics

The contract lists the legal top-level keys but states only the `task_type`,
`profile` and four list shapes.

| Refusal | Code | Source |
| --- | --- | --- |
| `spec` not a dict | `MALFORMED_PAYLOAD` | `gateway.py:4154-4157` |
| `iteration` not an int >= 1 | `MALFORMED_PAYLOAD` | `gateway.py:4159-4162` |
| `max_retries` not an int >= 0 | `MALFORMED_PAYLOAD` | `gateway.py:4164-4167` |
| `parent_task_id` / `cost_class` / `concurrency_group` not a string or null | `MALFORMED_PAYLOAD` | `gateway.py:4169-4180` |
| dependency does not exist or the graph is not a DAG | `DEPENDENCY` (mapped to `PROPOSAL`) **[read port]** | `gateway.py:4690-4706` |
| `provenance` `research_program:` ref does not dereference in-project | `PROVENANCE` **[read port]** | `gateway.py:4226-4245` |
| `provenance` `evidence_requirement:` pairing does not dereference | `PROVENANCE` **[read port]** | `gateway.py:4251-4268` |
| EXTRACT `spec.source_ref` malformed or its manifest absent; pinned profile/scope/cost | `MALFORMED_PAYLOAD` / `PROVENANCE` **[read port for the manifest]** | `gateway.py:4292-4352` |
| SOURCE_SEARCH / SOURCE_FETCH spec provider, bounds, search-task lineage, `source_result:` refs | `MALFORMED_PAYLOAD` / `DEPENDENCY` / `PROVENANCE` **[read port]** | `gateway.py:4373-4529` |
| task id already admitted with different content; cross-project id | `IDEMPOTENCY_CONFLICT` | `gateway.py:4644-4679` |

### `EVIDENCE_TRANSITION`

The contract lists its closed payload keys; it does not state required keys,
legal states or the ratification contract. Run 9's "evidence artifact ... not
in project" is this validator.

| Refusal | Code | Source |
| --- | --- | --- |
| `evidence_artifact_ref` missing / not `evidence:<id>` / empty id | `MALFORMED_PAYLOAD` | `gateway.py:1437-1448` |
| evidence artifact not in the project **[read port]** | `EVIDENCE_REF` (mapped to `PROPOSAL`) | `gateway.py:1449-1454` |
| `from_state` / `to_state` not a ratified evidence state | `MALFORMED_PAYLOAD` | `gateway.py:1455-1464` |
| `from_state == to_state` | `MALFORMED_PAYLOAD` | `gateway.py:1465-1468` |
| `from_state == "REFUTED"` | `MALFORMED_PAYLOAD` | `gateway.py:1469-1472` |
| `ratification_ref` not a non-empty string, or not an APPROVED `REJECT_BRANCH` proposal with a permitted action | `MALFORMED_PAYLOAD` / `PROPOSAL` | `gateway.py:1474-1478`, `:1490-1503` |
| `rationale` over `MAX_EVIDENCE_TRANSITION_RATIONALE` | `MALFORMED_PAYLOAD` | `gateway.py:1479-1485` |

### `PROPOSE_RESEARCH_PROGRAM`

The contract lists its top-level keys; the required top-level fields, the
nested draft schema and every compiler/gateway semantic check are unstated.

| Refusal | Code | Source |
| --- | --- | --- |
| `scope_ref` missing or empty | `MALFORMED_PAYLOAD` | `gateway.py:400-403` |
| scope brief not governed **[read port]** | `SCOPE_NOT_GOVERNED` | `gateway.py:407-413` |
| stale/foreign `supersedes_ref` | `STALE` | `gateway.py:415-421` |
| slot vocabulary unresolvable | `MALFORMED_PAYLOAD` | `gateway.py:428-434` |
| `ratification_ref` not an APPROVED `PROPOSE_MECHANISM_SUBSTITUTION` proposal | `MALFORMED_PAYLOAD` / `PROPOSAL` | `gateway.py:442-458` |
| `triggering_classification_id` absent/corrupt/not ADMITTED/not permitting the action, or binding mismatch | `MALFORMED_PAYLOAD` / `CLASSIFICATION_REF` **[read port]** | `gateway.py:466-560` |
| nested draft schema (hypotheses, predictions, discrimination requirements, methodology constraints, versions, ...) | `MALFORMED_PAYLOAD` (compiler `INVALID`) | `programs.py:1182-1202`, `:1283-1332` |
| compile gate not satisfied (evidence/obligation integrity) | `MALFORMED_PAYLOAD` / gate code | `programs.py` compiler verdict |

### The observed semantic family — the next gate

Run 9 ended with three semantic refusals the contract cannot fix by prose:

| Observed detail | Code | Gateway code |
| --- | --- | --- |
| `dependency mnode_… does not exist` | `PROPOSAL` | `DEPENDENCY` |
| `evidence artifact 'synthetic-sars9/e1' not in project` | `PROPOSAL` | `EVIDENCE_REF` |
| `provenance … does not dereference …` (not observed yet, same class) | `PROPOSAL` | `PROVENANCE` |

These need a read port: the model must be able to ask which task ids, evidence
artifacts, programs and requirements exist in the project before citing them.
No sentence can make a forged or stale id true.

## Invariants

- No new event, durable field, write or transaction. Census unchanged:
  124 / 28 (19/5/4) / 1 / 15 / 0. The contract field
  `OutputContract.max_proposal_bytes` is transient prompt configuration, not
  durable state; the census check confirms the durable figures.
- The LOOP baseline does not move: M1 stays 304 (the contract is the system
  message, not `request.prompt`).
- Drain-only unchanged; B4 stays 24. Governed docs untouched.
- No authority change: `proposable_kinds`, caps and budgets untouched.
- No key material anywhere.

## Gates

- Targeted: `tests/test_ops17_shape_gaps.py`,
  `test_ops14_profile_and_inputs`, `test_ops13_task_type_values`,
  `test_ops12_contract_gaps`, `test_loop_baseline`, `test_b4_ref_graphs`,
  `test_census_check` — `94 passed in 87.89s`.
- Full suite: `5216 passed, 3 skipped in 733.59s (0:12:13)` under the
  heavy-gate lock, with the untracked prompt probe quarantined.
- `scripts/stamp_suite_count.py` — collected 5219; `--check` clean.
- `scripts/check_census.py` — PASS, every certified figure reproduced.
- `uvx ruff check src tests scripts` — All checks passed.
- `uvx pyright src` — 0 errors, 0 warnings.
- `uvx pyright --pythonpath .venv/Scripts/python.exe --project
  pyrightconfig.tests.json` — 0 errors, 1 pre-existing warning
  (`test_research_program.py:144`, unrelated to this slice).

License: Apache-2.0 (LICENSE).
