# OPS-12 — operational notes

OPS-12 renders five validator rules that run 4 exposed into the contract. Each
statement is generated from the validator's own constants — the single-form
kind requirement, the closed payload keys, the derived identity keys, the
declared-but-unwired kinds, and the mutual exclusion of the two forms. The
validator remains the authority; the contract is guidance. This note records
the structural finding run 4's admissions exposed and the one evidence gap in
the supplied charter.

## The dispatch finding (recorded, not solved)

Run 4 admitted two `INSERT_TASK` proposals. Those admissions created five tasks
that nothing can dispatch:

- two `PENDING` `AGENT_TASK` tasks,
- two `PENDING` `TOOL_TASK` tasks, and
- cancellations.

The only registered handler is `methodology_run`. Admitted child work
therefore has no executor: the task rows are durable and eligible, but the
controller has no handler for their types. **This is not a contract gap.** The
next structural question is: *what executes an admitted child task?* — a
dispatch/routing design and its own slice. OPS-12 does not attempt to solve it.

The rows, read from the live database after run 4 (project `sars-covid-4`):

| task_id | status | type |
| --- | --- | --- |
| `task_00ff135406d579ba0b871618c4616ea7` | `PENDING` | `AGENT_TASK` |
| `task_4f307317127a51471cf9478734a3277b` | `PENDING` | `AGENT_TASK` |
| `seq-sars-covid-4-9d6499cee2d670b4b0d13da970c` | `PENDING` | `TOOL_TASK` |
| `seq-sars-covid-4-2a7deb21be1155d80c75e83a748` | `PENDING` | `TOOL_TASK` |
| `seq-sars-covid-4-c03e4b9268c722f19b4a5748053` | `CANCELLED` | `TOOL_TASK` |
| `seq-sars-covid-4-82576537eaaa76bd77d24a5d216` | `CANCELLED` | `TOOL_TASK` |

Four rows stay `PENDING` indefinitely — they are durable, eligible, and
unreachable, which is the worst of the three states: a queue that never drains
and never fails.

The exact task ids were not included in the supplied charter, and no run-4
report file is present in this checkout; the ids should be copied from the
run-4 report when this note is merged. The types above are the finding.

The availability note also makes visible a second instance of the same class:
every kind the `critic` profile declares (`ABANDON`, `REQUEST_HUMAN`,
`REQUEST_REPLICATION`, `REQUEST_ADDITIONAL_EXPERIMENT`) is unwired. The
contract now says so; the authority is unchanged. Whether the review/critic
path gets validators is part of the same dispatch question, not this slice.

## The five statements and their constants

| Statement | Validator constant |
| --- | --- |
| The single-proposal form requires a top-level `kind`. | `SINGLE_PROPOSAL_FIELD` |
| The payload is closed; these are its top-level keys per kind. | `INTENT_PAYLOAD_KEYS` (`_TASK_PAYLOAD_KEYS`, `_EVIDENCE_TRANSITION_PAYLOAD_KEYS`, `RESEARCH_PROGRAM_PAYLOAD_KEYS`) |
| Identity keys are derived, never supplied. | `AUTHORED_KEYS` |
| Declared-but-unwired kinds are unavailable in this phase. | `WIRED_INTENT_KINDS` |
| Exactly one proposal form; both is refused. | `SINGLE_PROPOSAL_FIELD` / `MULTI_PROPOSAL_FIELD`, plus per-field notes |

The composition root reads these sets through `live_contract_rules()` and
injects them into the model call; the runtime and the model plane never import
the research gateway. The drift guard in `tests/test_ops12_contract_gaps.py`
mutates each set and proves the rendered contract follows it.

## The five-form wording

OPS-9's sentence after the field list already said both forms were mutually
exclusive; run 4 still filled both. The field list itself presented `kind`
and `proposals` as two optional siblings with no relationship, so OPS-12 puts
the rule on the two field lines as well (`kind` is required in the single form;
`proposals` is used alone) rather than adding a third sentence after the list.
The original sentence stays; the field-level notes are the new lever.
