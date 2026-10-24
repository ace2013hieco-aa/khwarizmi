# MERGE-LOG-OPS-12 — five rules rendered from the validator

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-12: close the five contract gaps run 4 exposed |
| Base (`main` before) | `d7f0af1` |
| Landed tip | `b163ef8` (+ one Director commit adding the run-4 task rows to the note) |

```
 docs/OPS-12-NOTES.md               |  58 ++  (the dispatch finding + the rows)
 src/hermes/agents/runtime/run.py   |  21 +-  (AUTHORED_KEYS)
 src/hermes/composition.py          |  30 +-
 src/hermes/research/gateway.py     |  47 +-  (INTENT_PAYLOAD_KEYS, WIRED_INTENT_KINDS)
 src/hermes/research/programs.py    |   4 +-
 src/hermes/tools/models/binding.py |   6 +-
 src/hermes/tools/models/cloud.py   |  52 ++  (the five statements)
 src/hermes/tools/models/router.py  |  42 +-
 tests/test_ops12_contract_gaps.py  | 350 ++
```

## What landed

Five statements, each derived from a validator constant:

1. **Availability** — *"Declared but unavailable in this phase (the gateway has no validator for them): BRANCH, ABANDON, REQUEST_HUMAN. Choosing one is refused."* Read from `WIRED_INTENT_KINDS`.
2. **Single form requires `kind`** — the field line now says so, and a separate line repeats the requirement.
3. **Closed payload** — the legal top-level keys per kind, from `INTENT_PAYLOAD_KEYS`.
4. **Derived identity** — `idempotency_key`, `project_id`, `proposed_by`, `task_id` are refused if supplied, from `AUTHORED_KEYS`.
5. **Both forms** — the OPS-9 sentence kept, and the relationship moved onto the two field lines themselves.

The agent's judgement on (5) was right and worth recording: it did **not** add a third sentence. The field list presented `kind` and `proposals` as unrelated optional siblings; putting the relationship on those two lines is the fix, not more prose elsewhere.

## The drift guard now covers three sets

Payload keys, derived keys, and availability — each monkeypatched and asserted through to the
rendered prompt. A stale prompt fails with `stale prompt missing validator payload key(s):
['probe_key']`.

## What it cost

System prompt grows **+753 to +1,221 bytes** per profile (synthesizer largest — `PROPOSE_RESEARCH_PROGRAM`
has the widest payload schema). M1 unchanged: the contract is the system message.

## Run 5 — the result

```
Ran 2 tick(s): 1 dispatched, 1 succeeded, 0 failed, 1 unhandled
vector: runs=2 admitted=1 … mix=SUCCEEDED:1/OTHER:1
```

**No failure, no quarantine, one clean stage.** The QUESTION stage now drafts two proposals and
admits one — where run 4 refused four times at the same stage. Two gaps remain, both named by the
report:

| Code | Stage | Detail |
| --- | --- | --- |
| `MALFORMED_PAYLOAD` | QUESTION | `payload.task_type must be a NodeType value` |
| `ROLE` | HYPOTHESIS | `model proposed kind None` |

The first is a missing enumeration (`task_type` is listed as a legal key but its value set is not
stated). The second is not a missing rule — the contract says `kind` is required in the single
form, and the model still omitted it. That is instruction-following variance, and it should be
treated as such rather than patched with more prose.

## The dispatch finding, completed

The note now carries the six rows run 4 created, read from the live database. Four remain
`PENDING` — durable, eligible, unreachable. **A queue that never drains and never fails is worse
than one that errors**, and that is the next structural question: what executes an admitted child
task?

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted | **147 passed**; Director re-ran **40** at the merged tip |
| Full suite | **5140 passed / 3 skipped / 0 failed** |
| `stamp_suite_count.py --check` | `collected=5143` |
| `check_census.py` | **PASS** — unchanged |
| B4 / baseline / profiles | **24** / unchanged / `proposable_kinds` untouched |
| `ruff` / `pyright` | clean / **0/0/0** |

License: Apache-2.0 (LICENSE).
