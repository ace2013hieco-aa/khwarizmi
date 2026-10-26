# MERGE-LOG-OPS-5M — a truncated chain cannot succeed, and a billing failure says so

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-5M: close the truncated-chain path; make a billing failure legible in the ledger |
| Base | `main` at `d9a59b8` (the OPS-5L Director addendum) |
| Branch | `slice/ops-5m-truncated-chain` |
| Gate | The charter of 2026-10-26 — both items code-side, **no live run** (the provider account is out of credit) |
| Status | **PASS** — every falsifier green; census, B4, LOOP baseline and the drain-only bytes unchanged |
| Commits | `6f0ed43` implementation + tests; `0ffea06` the suite stamp; then this log (two commits — the log, and the commit/diff section added to it) |

No design gate: the Director approved the fix OPS-5L recommended, in writing, and
fixed its shape (`execution.termination != "COMPLETE"` → `failed_typed`, beside
S6-B2). The charter is the gate.

## Diff

`git diff --stat d9a59b8..6f0ed43` — the code and tests only (the docs commits
after it add `docs/SUITE-COUNT.md` and this log):

```text
 src/hermes/cli.py                                  |   8 +
 src/hermes/research/task_handlers/__init__.py      |  32 +
 .../research/task_handlers/methodology_driver.py   |  46 +-
 src/hermes/run_report.py                           |  38 +-
 src/hermes/tools/models/cloud.py                   |  98 ++-
 src/hermes/tools/models/router.py                  |  81 ++-
 src/hermes/tools/research_sources.py               |  17 +-
 tests/test_cloud_provider.py                       |   4 +-
 tests/test_model_plane.py                          |  17 +-
 tests/test_ops5l_evidence_ref_and_completion.py    |  51 +-
 tests/test_ops5m_truncated_chain.py                | 791 +++++++++++++++++++++
 tests/test_wiring_w3.py                            |   9 +-
 12 files changed, 1141 insertions(+), 51 deletions(-)
```

## What landed

### 1. The completion gate (`task_handlers/__init__.py`)

`build_methodology_handler` now asks a second question before it can answer
`completed`:

```python
if execution.termination != METHODOLOGY_COMPLETE:
    return HandlerResult(
        status="failed_typed",
        reason=(f"PROPOSAL: methodology {execution.methodology_id!r} stopped "
                f"early — termination {execution.termination!r} with "
                f"{len(execution.stages)} of {len(parsed.stages)} declared "
                f"stage(s) recorded; a truncated chain is not a recorded "
                f"outcome (OPS-5M)"),
        outcome_recorded=False)
```

It sits **after** S6-B2, in its own branch, and changes nothing about S6-B2's
coverage: every input that reached S6-B2's reason before still reaches it,
byte-identically. The order is deliberate — "did anything happen" is answered
first, and a run that admitted nothing is `failed_typed` for that reason
whatever its termination. The new gate owns exactly the inputs S6-B2 is blind
to: an execution with at least one admission and a termination that is not
`COMPLETE`.

The predicate is an **equality against completion**, not a list of known
failures. A termination value added to the runtime later fails closed here
rather than passing as complete.

### 2. `METHODOLOGY_COMPLETE` (`methodology_driver.py`)

`run_methodology` used the bare literal `"COMPLETE"`. It now uses a named
constant, and the handler compares against the same name — so the two spellings
of "finished" cannot drift. The constant carries the closed definition (below).
It adds no value: the string was already produced here.

### 3. The legible failure (`tools/models/*`, `run_report.py`, `cli.py`)

The ledger row (`ModelCallAccount`) already had `failure_class`, and nothing
rendered it — it was filled with `type(exc).__name__`, which told an operator
`PermanentProviderError` and nothing more. The fix wires that field through and
gives it something worth reading:

| Surface | Before | After |
| --- | --- | --- |
| `ProviderError` | message + hazard class | + `http_status`, + `error_class` (bounded token) |
| `CloudChatProvider._raise_for_status` | took the status, dropped the body entirely | takes the response, reads **one** field (`error.type` / `error.code` / `type` / `code`) as the class |
| `ModelCallAccount.failure_class` | `type(exc).__name__` | the provider's error class, else the hazard class, else the type name |
| `ModelCallAccount` | — | + `http_status: int \| None`, + `failure_detail: str` (240 chars, one line) |
| CLI `model call N:` line | `PERMANENT (in 0, out 0)` | `PERMANENT status=402 class=billing_error (in 0, out 0)` |
| report `model_attempts[]` | no failure fields | `failure_class`, `http_status`, `failure_detail` — **only on a failed attempt** |
| controller note | `attempt 1: PermanentProviderError` | `attempt 1: PermanentProviderError HTTP 402 billing_error` |

Nothing is reclassified: the outcome stays `PERMANENT`, the retry decision is
untouched, and `402` is now in the provider test's "does not retry" set rather
than absent from it. A 402's message carries **no** refusal-code prefix — the
frozen vocabulary has no honest code for "the account cannot pay"
(`MALFORMED_PAYLOAD` names the wrong fault, `ROLE` names authority) — so the
class travels as data (`error_class`, `failure_class`) and the sentence says
what happened.

A successful attempt's row is byte-identical to before: the three fields appear
only when `outcome != "OK"`, so a green run's report does not move.

## What `COMPLETE` means, and everything that is not it

`MethodologyExecution.termination` is `COMPLETE` when, **and only when**, the
driver's stage loop ran to its end without breaking: every required stage of the
document was projected, consulted, run and recorded, and every recorded stage's
run reached `SUCCEEDED`. A stage the document marks not-required is skipped by
design and does not affect it; a stage already recorded (an idempotent resume)
counts as run. Neither stops the loop.

The field is assigned in exactly two places, each immediately followed by the
loop's `break`:

| Value | Where it comes from | Why it is not complete |
| --- | --- | --- |
| `STAGE_LIMIT` | this driver: `termination.max_stages` reached with stages still to run | the document's own bound stopped the chain; it is reached only when stages remain |
| `PROPOSAL_LIMIT` | the stopping stage run's `Termination` | that stage's run did not succeed |
| `TICK_LIMIT` | " | " |
| `NO_PROPOSALS` | " | " |
| `STOP_WHEN` | " | " |
| `CANCELLED` | " | " |
| `TIMEOUT` | " | " |
| `MODEL_REFUSED` | " | " |
| `TOOL_FAILED` | " | " |
| `PORT_FAILURE` | " | " |
| `FAILED` / `CANCELLED` / `SKIPPED` / `INVALIDATED` / `NO_SIGNAL` | the stopping stage run's `state`, when its `termination` was empty | same — a stage that did not succeed stopped the chain |
| anything else, including `""` | — | the gate is `!= COMPLETE`, so an unknown value fails closed |

**Which early stop legitimately counts as complete:** a *stage* that stops early
on `STOP_WHEN`, `NO_PROPOSALS`, `PROPOSAL_LIMIT` or `TICK_LIMIT` and still
reaches `SUCCEEDED`. That stage did its job: it is recorded, the chain extends,
and the execution's `termination` stays `COMPLETE` — because the driver only
assigns the field when a stage did **not** succeed, a succeeded stage's own
termination never reaches it. `TICK_LIMIT` is the clearest case: the runtime's
own `_assemble` ends a run `SUCCEEDED` + `TICK_LIMIT` when its tick budget runs
out without a stop condition, and such a stage is a normal recorded link. So no
termination that *can* appear in `execution.termination` is legitimate; the
legitimate early stops are the ones that never appear there.

## The truncated chain, before and after

Reproduced through the real `Controller`, with the real gateway, the real
runtime and the real handler; no network.

| | Cited | Citationless |
| --- | --- | --- |
| shape | OBSERVATION admits `evidence:<seeded>`, EVIDENCE returns a terminal `ModelRefusal` | QUESTION admits an ordinary `INSERT_TASK`, HYPOTHESIS returns a terminal `ModelRefusal` |
| stages recorded | 5 of 9 | 1 of 9 |
| admissions before the stop | 1 (an `EVIDENCE_TRANSITION`) | 1 (an `INSERT_TASK`) |
| **before OPS-5M** | task `SUCCEEDED`, `out.succeeded == [task_id]` | task `SUCCEEDED`, `out.succeeded == [task_id]` |
| **after** | `RETRYING`, `out.retried == [task_id]`, reason `… termination 'MODEL_REFUSED' with 5 of 9 declared stage(s) recorded … (OPS-5M)` | `RETRYING`, `out.retried == [task_id]`, reason `… termination 'MODEL_REFUSED' with 1 of 9 … (OPS-5M)` |

Both were verified red-then-green: with the gate disabled the two tests fail on
`assert out.succeeded == []` (`['t-ops5m-cited'] == []`); restored, they pass.
The third shape — a nine-stage document bounded to `max_stages: 3` — reaches
`STAGE_LIMIT` with three stages recorded and is now `RETRYING` too.

Verbatim, from the real Controller (the test file's own harness):

```text
[cited]         succeeded=[] retried=['t-cited'] failed=[] status=RETRYING
   reason: PROPOSAL: methodology 'literature-review' stopped early — termination
           'MODEL_REFUSED' with 5 of 9 declared stage(s) recorded; a truncated
           chain is not a recorded outcome (OPS-5M)
   stages: QUESTION HYPOTHESIS PREDICTION EXPERIMENT OBSERVATION EVIDENCE

[citationless]  succeeded=[] retried=['t-bare'] failed=[] status=RETRYING
   reason: PROPOSAL: methodology 'literature-review' stopped early — termination
           'MODEL_REFUSED' with 1 of 9 declared stage(s) recorded; a truncated
           chain is not a recorded outcome (OPS-5M)
   stages: QUESTION HYPOTHESIS

[stage-limit]   succeeded=[] retried=['t-limit'] failed=[] status=RETRYING
   reason: PROPOSAL: methodology 'literature-review' stopped early — termination
           'STAGE_LIMIT' with 3 of 9 declared stage(s) recorded; a truncated
           chain is not a recorded outcome (OPS-5M)
   stages: QUESTION HYPOTHESIS PREDICTION

[complete]      succeeded=['t-full'] retried=[] failed=[] status=SUCCEEDED
   stages: QUESTION HYPOTHESIS PREDICTION EXPERIMENT OBSERVATION EVIDENCE CLAIM
           CRITIQUE CONCLUSION
```

Note `failed=[]` on all three: the handler's verdict is `failed_typed`, so the
controller retries rather than failing outright — the same shape S6-B2 has
always had, and the same shape OPS-5L measured on the run-19 path.

The honest run is untouched: a nine-of-nine chain with every stage `SUCCEEDED`
still reaches `SUCCEEDED`, and a driver-level run of the same document still
terminates exactly `METHODOLOGY_COMPLETE` over nine recorded stages.

## The ledger, printed

Same endpoint, same scripted transport, two statuses — the CLI line and the
report row, verbatim:

```text
  model call 1: tier=m provider=anthropic model=test-model PERMANENT status=402 class=billing_error (in 0, out 0)
  {"tier": "m", "provider": "anthropic", "model": "test-model", "attempt": 1,
   "outcome": "PERMANENT", "tokens_in": 0, "tokens_out": 0, "duration_ms": …,
   "failure_class": "billing_error", "http_status": 402,
   "failure_detail": "HTTP 402: the provider will not serve this account — a billing failure, not a malformed request"}

  model call 1: tier=m provider=anthropic model=test-model PERMANENT status=400 class=invalid_request_error (in 0, out 0)
  {"tier": "m", "provider": "anthropic", "model": "test-model", "attempt": 1,
   "outcome": "PERMANENT", "tokens_in": 0, "tokens_out": 0, "duration_ms": …,
   "failure_class": "invalid_request_error", "http_status": 400,
   "failure_detail": "MALFORMED_PAYLOAD: HTTP 400 from the model provider"}
```

Runs 20 and 21 printed `model call 1: … PERMANENT (in 0, out 0)` for the first
of those. The body — `Insufficient balance. This request requires up to 266
tokens reserved.` — appears nowhere: not in the row, not in the report, not on
the CLI. The row carries a class, a status and one bounded sentence.

## Falsifiers

| Falsifier | Result |
| --- | --- |
| A chain that stops early after an admission reaches `FAILED`, not `SUCCEEDED` — cited | **PASS** — `test_a_cited_truncated_chain_fails`: `RETRYING`, reason names `MODEL_REFUSED` and `5 of 9`; red with the gate disabled |
| — citationless | **PASS** — `test_a_citationless_truncated_chain_fails`: `RETRYING`, `1 of 9`, and the only admission is an `INSERT_TASK` (no evidence ref anywhere) |
| — on the document's own bound | **PASS** — `test_a_stage_limit_truncation_fails`: `STAGE_LIMIT`, `3 of 9` |
| A complete 9/9 chain still reaches `SUCCEEDED` | **PASS** — `test_a_complete_chain_still_succeeds` (`succeeded`, nine stage runs, every one admitted) and `test_the_driver_still_reports_complete_for_that_run` (`COMPLETE` over nine records) |
| S6-B2 is not weakened and not merged | **PASS** — `test_s6b2_still_answers_its_own_question` (an effectless *complete* run still says `(S6-B2)` and not `OPS-5M`) and `test_the_two_gates_are_separate_branches` (both predicates present, in that order) |
| A 402 is legible as a billing failure in the ledger and the report | **PASS** — `test_a_402_says_billing_in_the_ledger_and_the_report` |
| A 400 is legible as a request failure | **PASS** — `test_a_400_says_request_failure_in_the_ledger_and_the_report` |
| Both stay `PERMANENT` | **PASS** — `test_both_failures_stay_permanent` (one row, `attempt == 1`, no retry) — and it passes **with the fix reverted**, because it pins what must not change |
| No body, no header, no key | **PASS** — `test_the_ledger_carries_no_body_and_no_header`, `test_a_hostile_error_class_is_reduced_to_a_token` (a 200-fold injection payload is cut to 64 characters, exactly) |
| Baseline and census unchanged | **PASS** — LOOP baseline green, B4 24, census 124 / 28 (19/5/4) / 1 / 15 / 0, drain-only byte-identical |

## Invariants

1. No new event kind, write path, transaction, table, port or refusal code. The
   census is **124 / 28 (19/5/4) / 1 / 15 / 0** — unchanged.
2. The substrate's content rules and the gateway's checks are untouched;
   `EVIDENCE` stays required.
3. Drain-only byte-identical (`test_no_tiers_is_byte_identical`, in the
   targeted set); B4 24; governed docs untouched; LOOP baseline unchanged.
4. `proposable_kinds`, grants, `max_ticks`, objectives and the methodology
   document are untouched.
5. No key material, no response bodies, no headers: the ledger gains a token, a
   number and one sentence; the class is sanitised at the provider edge and
   capped again in the ledger.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted (new file + OPS-5L + plane + W3 + W4 + OPS-1 CLI + LOOP + B4 + census) | `283 passed in 13.51s`, exit 0 |
| Full suite (`scripts/run_tests.py`, alone on the machine) | `5 failed, 5426 passed, 3 skipped, 1 warning in 741.63s (0:12:21)` — **exactly** the documented baseline-5 (delta 0) |
| `scripts/stamp_suite_count.py` then `--check` | `Stamped docs\SUITE-COUNT.md: collected=5434`; `OK: docs\SUITE-COUNT.md collected=5434 matches the live collect` |
| `scripts/check_census.py` | `PASS - every certified figure is reproduced exactly.` (124 / 28 (19/5/4) / 1 / 15 / 0) |
| `uvx ruff check src tests scripts` | `All checks passed!` |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| `uvx pyright --pythonpath .venv/Scripts/python.exe --project pyrightconfig.tests.json` | `0 errors, 1 warning, 0 informations` (pre-existing `test_research_program.py:144`) |

The red set is the one `docs/AUDIT-PROGRAM-CLOSURE.md` §7 documents: four
readonly-DB concurrency races and one Windows symlink privilege. Run in
isolation all five pass, which is what makes them environmental rather than
deterministic. An earlier full run on this tree reported **six** — the extra one
was `test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree`,
the documented `eval_plane` timing flake: it passes alone, `run_matrix` reports
`clean: True` when invoked directly on this tree, and the runner's only
load-sensitive part is its 30-second subprocess timeout per pinned test
(`hermes/eval/matrix.py:200`). The re-run above did not fire it.

## Pins I moved in existing tests

Five, all deliberate, all named here rather than buried:

1. `test_model_plane.py::test_account_row_surface_is_frozen` — the frozen row
   surface gains `http_status` and `failure_detail`. That surface is a contract,
   and this slice is the one that widens it.
2. `test_model_plane.py::test_one_row_per_provider_call` — asserted
   `failure_class == "TransientProviderError"`; now `"TIMEOUT"` (the hazard class
   the provider actually named). The old value was the Python type that carried
   the failure, which is the defect this slice fixes.
3. `test_model_plane.py::test_permanent_failure_lands_one_permanent_row` — same,
   `"PermanentProviderError"` → `"MALFORMED_200"`.
4. `test_wiring_w3.py::test_the_driver_defines_no_new_vocabulary` — the driver's
   closed constant set gains `METHODOLOGY_COMPLETE`, which names a value the
   driver already produced. No value, code or kind is added.
5. `test_ops5l_evidence_ref_and_completion.py::test_a_stage_refusal_after_an_admission_is_reported_failed`
   — the charter allows it ("that test may now assert the task state too"), and
   it now does: `out.succeeded == []`, `RETRYING`, and the reason names `OPS-5M`
   and not `S6-B2`. The docstring's "the row's state is deliberately not
   asserted here" is replaced by why it can be asserted now.

## What I refused to do

- **Did not run anything live.** The account is out of credit; the slice is
  proved from tests alone, as the charter requires. Every 402 and 400 in this
  document came from a scripted transport, not from a provider.
- **Did not merge the two gates.** S6-B2 keeps its own branch, its own message
  and its own precedence. A single `if` that answered both would have passed
  every behavioural test in this slice and still been the thing the charter
  forbids — which is why the separation is pinned at the source, not only at
  the behaviour.
- **Did not reclassify anything.** `PERMANENT` stays `PERMANENT`; a 402 still
  will not succeed on retry. The provider test's "does not retry" set gained
  `402` rather than losing a member.
- **Did not put the body, the headers or the vendor's message in the ledger.**
  The class is one sanitised token; the message is this plane's own sentence.
  The tests assert the vendor's words appear nowhere.
- **Did not invent a refusal code for a billing failure.** The message carries
  no code prefix, because the frozen vocabulary has no honest one. The class
  travels as data instead.
- **Did not add a second field for the class.** `failure_class` already existed
  and the report dropped it; it is wired through and given the value an operator
  needs. The two new fields are the status and the bounded message, which the
  ledger genuinely lacked.
- **Did not touch the report's byte shape for a successful run.** The failure
  fields appear only on a failed attempt, so a green report is unchanged.
- **Did not chase the baseline-5.** Five tests fail intermittently on this host
  (four readonly-DB concurrency races, one Windows symlink privilege); they pass
  in isolation, they are documented in `docs/AUDIT-PROGRAM-CLOSURE.md` §7, and
  this run reproduced exactly those five — no more, no fewer.
