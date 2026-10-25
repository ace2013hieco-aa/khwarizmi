# MERGE-LOG-OPS-13 — `task_type` enumerated, and the runtime stops refusing

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-13: render the legal `task_type` values from the `NodeType` enum |
| Base (`main` before) | `22e7ae1` |
| Landed tip | `528a72c` |

```
 docs/OPS-13-NOTES.md                 |  88 ++
 src/hermes/composition.py            |  37 +-
 src/hermes/research/gateway.py       |  15 ++  (INTENT_PAYLOAD_VALUE_SETS)
 src/hermes/tools/models/binding.py   |   2 +
 src/hermes/tools/models/cloud.py     |  24 ++  (render the value set)
 src/hermes/tools/models/router.py    |  17 +-
 tests/test_ops13_task_type_values.py | 246 ++
```

## The distinction that made this slice correct

My charter said the validator *requires* `task_type`, so the contract should say "required". The
agent checked and found the opposite at the surface the model writes to:

```
run.py:1053    payload.setdefault("task_type", "AGENT_TASK")
```

`_payload_to_node` does require the key — but `_derive_payload` defaults it before the gateway
ever sees the payload. So at the **draft** surface it is optional, and the contract now says so:

> For INSERT_TASK, the payload key "task_type" is optional (omitting it takes the runtime's
> default); when supplied it must be one of: AGENT_TASK, GATE, HUMAN_GATE, SUBGRAPH, TOOL_TASK.
> Any other value is refused.

Both halves are pinned. Had I not been contradicted, the contract would have demanded a key the
model is free to omit — a fresh mismatch of exactly the kind this whole series is closing.

## The value set has one source

```python
_TASK_TYPE_VALUES = frozenset(node_type.value for node_type in NodeType)
```

No typed list. `test_the_value_set_is_the_node_type_enum` asserts the constant equals the enum's
values, so an enum change with a stale constant fails even before the monkeypatch guard. Only
`INSERT_TASK` is mapped — it is the only task kind a model may propose (`ADMIT_TASK` is internal).

## What it changed — run 6

```
Ran 4 tick(s): 3 dispatched, 1 failed, 6 unhandled
vector: runs=6 admitted=2 … mix=SUCCEEDED:6/OTHER:0
```

**Every stage run succeeded. Zero runtime failures.** The refusals moved entirely to the gateway —
which is progress: the runtime is no longer the problem.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted | **61 passed**; Director re-ran **50** at the merged tip |
| Full suite | see note below — three documented intermittent tests, all host-level |
| `stamp_suite_count.py --check` | `collected=5153` |
| `check_census.py` | **PASS** — unchanged |
| B4 / baseline | **24** / unchanged |
| `ruff` / `pyright` | clean / **0/0/0** |

**Full-suite note.** The agent's run excluded an untracked audit probe that fails on pristine
`main` too (reproduced from `git archive main`). The Director ran the merged tree twice. The first
run hit three of the documented intermittents; the second hit **all five** — `test_concurrency` ×2,
`test_p_auto_5_vault`, `TestForcedConcurrencyRace`, `test_f6_one_verdict_race_closed` — which is
exactly the set recorded in `docs/AUDIT-PROGRAM-CLOSURE.md` §7 (observed producing 5, 4 and 0
failures on consecutive runs of this machine). Collected matches the stamp at **5153**; the pass
count is therefore 5145 passed / 3 skipped / 5 failed **by subtraction, not by an observed summary
line** — the `-q` output was truncated before the counts row. Nothing outside the documented set
failed in either run.

License: Apache-2.0 (LICENSE).
