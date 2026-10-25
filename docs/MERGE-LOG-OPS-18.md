# MERGE-LOG-OPS-18 — the read port, and what it did not fix

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-18: a bounded project index the model can read before citing |
| Base (`main` before) | `ba61179` |
| Landed tip | `1d3a508` + the stamp |

```
 docs/idr/LIVE-PROJECT-INDEX.md                     | 118 ++
 src/hermes/agents/runtime/assembly.py              | 111 ++
 src/hermes/composition.py                          |   9 +-
 src/hermes/persistence/project_index.py            |  ~  (new: 3 SELECTs + 3 COUNTs)
 src/hermes/research/project_index.py               |  ~  (new: labels, ordering, cap)
 src/hermes/research/task_handlers/__init__.py      |   8 +-
 .../task_handlers/methodology_driver.py            |  24 +-
 tests/test_ops18_project_index.py                  |  ~  (13 tests)
```

## Disclosure: the Director implemented this one

The slice agent spent **4 h 40 m** and was still polling when stopped. Its full suite had finished at
**11:56** — `1 failed, 5228 passed` — and the log had not changed for four and a half hours; the agent
was running `sleep 60 / 90 / 120` against a file that had stopped growing.

The failure was real and architectural:

```
FAILED test_loop1_context_assembly.py::test_the_assembly_module_is_pure_no_clock_no_model_no_io
```

`assembly.py` is purity-tested on an **exact import set**. The agent added `from dataclasses import
dataclass` and three `@dataclass` types inside it — the one module contractually forbidden from
holding a dependency.

**The fix, made by me:** `NamedTuple` instead of `dataclass`. `typing` is already imported, so the
import set is unchanged; immutability, ordering and attribute access are identical. The purity test
passes with no widening of the contract — which was the point. Loosening `ALLOWED_IMPORTS` would have
been the easy move and the wrong one.

I also found **two untracked modules** the agent never committed (`persistence/project_index.py`,
`research/project_index.py`) — the suite could not even collect without them. Both are now committed.

Every previous slice in this programme was agent-implemented and Director-verified. This one was not,
and the record should say so.

## What the tests prove

13 tests, including the two the charter demanded because they make claims checkable:

- **transaction count identical with and without the index** — "read-only" as a measurement, not an
  assertion;
- **cross-project isolation with overlapping id prefixes** — the only version of that test that can
  fail;
- content-free envelope (asserted on keys), no admissibility wording, truthful `omitted`, ordering,
  empty-project marker, read-once-per-stage, fail-loud on a read error, and both "cited from the index
  no longer refuses" cases.

## What run 11 shows — the honest part

```
runs 8, admitted 9, SUCCEEDED:6/OTHER:2, intent_refused 5 → 2
```

Seven stages reached (QUESTION, HYPOTHESIS, PREDICTION, EXPERIMENT, OBSERVATION, EVIDENCE, CLAIM).
Refusals down from six to four — but **the two the read port was built for both survived**:

| Refusal | Why it survived |
| --- | --- |
| `dependency mnode_… does not exist` | the model kept copying the predecessor `mnode_` from its payload. The index labels chain nodes "not a task id"; **the label was not enough** |
| `evidence artifact 'synthetic-sars11/e1' not in project` | there is **no artifact row to cite** — the project has zero artifacts, because nothing produces them (no capability plane) |

So the read port is correct and test-proven, and the live model did not avail itself of it. That is
the third instance of the same phenomenon: `kind None`, the cap overrun (4,289 bytes against a stated
4,096), and now this. **The contract has grown past what the model reliably follows.**

## The next lever, pre-authorised

R2 said: if run 11 still produces `dependency mnode_…`, the fallback is a contract sentence that
`dependencies` accepts only task ids. **That is now triggered.**

And a second option is worth costing: a `PROPOSAL` refusal whose cause is *correctable* (a
non-existent dependency or evidence ref) could carry the index back to the model in the retry
envelope — "that id does not exist; here is what does". That is a stronger fix than another sentence,
because it uses the mechanism OPS-15 built instead of adding prose to a contract the model already
ignores in places.

The evidence-ref refusal is not fixable by either: it needs an artifact to exist, which needs the
capability plane.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted (OPS-18 + LOOP-1 + baseline + OPS-7 + live CLI + B4) | **79 passed** |
| Full suite | **5 failures, all the documented intermittent set** (5232 collected) |
| `stamp_suite_count.py --check` | `collected=5232` |
| `check_census.py` | **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0 |
| B4 / LOOP baseline | **24** / unchanged, purity restored |

The five failures are `test_concurrency` ×2, `test_p_auto_5_vault`, `TestForcedConcurrencyRace`,
`test_f6_one_verdict_race_closed` — the same host-level set as the last three runs. Nothing outside it
failed.

License: Apache-2.0 (LICENSE).
