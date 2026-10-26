# MERGE-LOG-OPS-5H — a tick may gather

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-5H phase 2: the proposal-free tick, and one instruction that lies |
| Base | `main` at `5f44a27` (the OPS-5H design gate) |
| Branch | `slice/ops-5h-tool-only-tick` |
| Commits | `10aee00` (implementation + tests), `1cced45` (the phase-2 record and OPS-5I), `c596c02` (the stamp), this commit (this log) |
| Status | **PASS** — the falsifiers are green; the full suite is green except the documented baseline-5, reproduced at the base |

## What landed

1. **One predicate** (`tools/models/router.py::_action_only_reply`). A reply is
   proposal-free and calling iff the contract names an action array, that array
   is a list with at least one element, the single-form field is absent / `None`
   / whitespace, and the multi-form field is absent / `None` / `[]`. The kind
   check is skipped only then; every other check runs unchanged.
2. **One injected contract field** (`OutputContract.action_field`), set by the
   runtime to `TOOL_CALLS_FIELD` when the profile declares the section and `""`
   otherwise. The plane learns the *name*, as it already learns the form fields.
3. **One rendered sentence**, from the injected names: *A reply that proposes
   nothing is valid when it calls a tool: omit the "kind" and "proposals" fields
   and output a non-empty "tool_calls" array; the stage continues within its
   tick budget.* 186 UTF-8 bytes, +187 with its newline, for `researcher`,
   `experimenter` and `critic`; 0 for the other three.
4. **The instruction corrected, not the validator** (OPS-5I). The note no longer
   says *"omit it in the multi-proposal form"* or offers a choice of forms; the
   `kind` note reads `required in the single-proposal form`, the `proposals`
   note reads `not usable in this build; a non-empty array is refused`, and the
   rendered rule states one form.

## The validity predicate, in code terms

```python
def _action_only_reply(contract, parsed) -> bool:
    if not contract.action_field:                  # "" -> today's behaviour
        return False
    calls = parsed.get(contract.action_field)
    if not isinstance(calls, list) or not calls:   # non-empty list only
        return False
    single = contract.single_form_field
    if single:
        value = parsed.get(single)
        if value is not None and not (isinstance(value, str) and not value.strip()):
            return False
    multi = contract.multi_form_field
    if multi:
        value = parsed.get(multi)
        if value is not None and not (isinstance(value, list) and not value):
            return False
    return True
```

A truthy value of any type in either form field makes the predicate false, so a
malformed `kind` beside a call is still a `ROLE` (or, for a wrong type, a
`MALFORMED_PAYLOAD`), and a reply with neither is still `ROLE` with today's
detail.

## Falsifiers

| Falsifier | Result |
| --- | --- |
| Run 16's exact reply is accepted; the tool executes; `proposals`/admissions stay flat; the stage continues | **PASS** — tick 1 is `TICK_STARTED / MODEL_REQUESTED / TOOL_REQUESTED / TOOL_OBSERVED / CHECKPOINT_WRITTEN(proposals: 0)`; tick 2 drafts and admits; `tool_calls == 1` |
| The full three-tick sequence: tick 1 search, tick 2 fetch, tick 3 propose — the `EVIDENCE` ref is the fetched artifact | **PASS** — real router under the live contract, real capability supply, real gateway; one artifact row (`FETCH_HASH`); `EVIDENCE.external_ref == evidence:<FETCH_HASH>`; `EvidenceTransitionProposed` admitted; `STOP_WHEN` |
| A stage that only calls tools ends at its tick bound with a stated termination | **PASS** — `SUCCEEDED` / `TICK_LIMIT`, 3 ticks, 3 calls, 0 proposals, 0 refusals, no `MODEL_REFUSED`, no review child |
| A reply with neither refuses, same code as today | **PASS** — `ROLE`, `model proposed kind None, outside the injected proposable allowlist`, `contract_feedback=True` |
| A malformed kind beside a call still refuses `ROLE` | **PASS** — `ROLE`, `model proposed kind 'GATHER', …` |
| A multi-form reply refuses, and the note no longer offers the form | **PASS** — `ROLE` at the plane without a top-level kind; `MALFORMED_PAYLOAD` at the runtime with one; the note states one form and calls `proposals` not usable |
| A contract with no `action_field` behaves exactly as today | **PASS** — run 16's reply still refuses `ROLE` with the same detail |
| The predicate is exactly as stated | **PASS** — the 14-row table; `kind: 5` is a type refusal, not an exemption |
| Baseline / census / B4 / LOOP unchanged | **PASS** — `test_loop_baseline` 4/4, `test_b4_ref_graphs` 24/24, census 124 / 28 (19/5/4) / 1 / 15 / 0 |

## The trace of a call-only tick

`researcher`, `max_ticks: 2`, tick 1 = run 16's reply, tick 2 = a proposal:

```text
state=SUCCEEDED termination=STOP_WHEN ticks=2 proposals=1 tool_calls=1 refusals=0

  tick 0  RUN_STARTED / CHECKPOINT_WRITTEN(RUNNING, proposals: 0)
  tick 1  TICK_STARTED / MODEL_REQUESTED(tier: research, call_budget: 2)
          TOOL_REQUESTED(source_search)
          TOOL_OBSERVED(source_search, artifacts: [evidence/art_ops5h])
          CHECKPOINT_WRITTEN(RUNNING, proposals: 0)
  tick 2  TICK_STARTED / MODEL_REQUESTED / PROPOSAL_DRAFTED(INSERT_TASK)
          INTENT_EMITTED / INTENT_ADMITTED / CHECKPOINT_WRITTEN
          RUN_TERMINATED(SUCCEEDED, STOP_WHEN) / CHECKPOINT_WRITTEN(terminal)
```

Calls up, proposals flat, no failure code. `max_ticks` is the only thing
stopping a stage that only ever gathers.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted (the new file, OPS-5G, OPS-5F, OPS-5B, LOOP baseline, B4, census) | `116 passed in 9.73s`, exit 0 |
| The pins the correction moved (OPS-9, OPS-12, OPS-1 live CLI) | `35 passed in 1.49s`, exit 0 |
| Full suite (`scripts/run_tests.py`) | `5 failed, 5334 passed, 3 skipped, 1 warning in 681.10s (0:11:21)` — the 5 are the documented baseline-5, reproduced at the base (below) |
| `scripts/stamp_suite_count.py` then `--check` | `Stamped docs\SUITE-COUNT.md: collected=5342`; `OK: docs\SUITE-COUNT.md collected=5342 matches the live collect` |
| `scripts/check_census.py` | `PASS - every certified figure is reproduced exactly` (124 / 28 (19/5/4) / 1 / 15 / 0) |
| `uvx ruff check src tests scripts` | `All checks passed!` |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| `uvx pyright --pythonpath .venv/Scripts/python.exe --project pyrightconfig.tests.json` | `0 errors, 1 warning, 0 informations` (the warning is the pre-existing `test_research_program.py:144`) |

### The red set is the documented baseline-5

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

These are the five environmental reds documented in `docs/MERGE-LOG-CAT-1.md`
(3 SQLite `attempt to write a readonly database` races + 1 Windows
symlink-privilege refusal + 1 q05 race). **Isolation proof:** the same five
tests were run at the base commit in a clean worktree at `5f44a27` and failed
with the same signatures —

```
5 failed (the same five node ids, the same signatures) at 5f44a27,
in a clean worktree, before this slice's commits were applied
```

— so the slice introduces no new failure. No `eval_plane` flake fired this run.

## What I refused to do

- **Did not make the multi-proposal form work, and did not remove it.** That is
  OPS-5I: it touches OPS-9's semantics, and this slice's ruling was to correct
  the instruction only. Validator behaviour is byte-for-byte unchanged.
- **Did not record the gathering tick's rationale.** Validated and unused; a new
  trace detail belongs with the run-report work. Recorded as candidate OPS-5J.
- **Did not add an event kind, write path, transaction or module.** Census
  unchanged; `proposable_kinds` untouched; the methodology document untouched.
- **Did not touch the tick order, the stop policies or `max_ticks`.** A
  call-only tick consumes a tick; the bound is unchanged and remains the only
  stop for a stage that never proposes.
- **Did not change the runtime's severity rule.** A failed call still stops the
  run `FAILED/TOOL_FAILED`; only a *valid* gathering reply stops being a
  `MODEL_REFUSED`.

License: Apache-2.0 (LICENSE).

---

## Director addendum — run 17, and the model is now the limit

Landed at `dab4917`, then run 17 with the same prior-art-only seed.

```
runs 5, admitted 7, M2(calls=0), artifacts: 0
QUESTION → HYPOTHESIS → PREDICTION → EXPERIMENT → OBSERVATION → FAILED/MODEL_REFUSED
```

**Three refusals, all the same shape:**

```
MALFORMED_PAYLOAD: model output carried unknown key(s) ['arguments', 'capability_id']
```

The model put the item keys at the reply's top level — the flat form — at `HYPOTHESIS` tick 1 and twice
at `OBSERVATION` tick 1. Two of the replies are near-identical to each other, and two model calls
returned byte-identical output (`in 2463, out 184` twice), so the retry fed back the refusal and the model
repeated itself.

### The contract is not the problem

`composition.py:368` still renders, verbatim:

> `"tool_calls" is an array; each item is an object with exactly these keys: {"arguments": {...},
> "capability_id": "...", "rationale": "..."}; the flat form — those keys at the reply's top level — is
> refused (MALFORMED_PAYLOAD).`

**The contract names the exact error the model then made.** `test_ops5g_tool_call_shape` passes 4/4 on this
tree. The mechanism is proven by the falsifier table: run 16's exact reply is accepted, the tool runs, the
stage continues, and the three-tick sequence produces an artifact `EVIDENCE_REF` accepts.

So the plumbing is done. What remains is that the model does not reliably produce a reply the contract
spells out — including one it produced correctly **once**, in run 16.

### The honest reading

Seventeen runs have moved the failure from *structural* to *behavioural*. The remaining variance is model
compliance: the same contract, the same falsifiers, and a model that alternates between the correct shape
and the refused one.

The next experiment should hold the code fixed and change the model — one variable, no new clause.

Director gates at the merged tip: 69 targeted passed, stamp `5342`, census **PASS**.
