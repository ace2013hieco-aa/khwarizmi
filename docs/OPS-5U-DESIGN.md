# OPS-5U — design gate: an empty completion is a failed sample, not a bad request

| Item | Value |
| --- | --- |
| Slice | OPS-5U |
| Base | `main` at `1677e7e` |
| Branch | `slice/ops-5u-empty-completion` |
| Date | 2026-10-27 |
| Census at base | 124 / 28 (19/5/4) / 1 / 15 / 0 — `scripts/check_census.py` PASS on this tree |
| Gate | The charter of 2026-10-27 — one refusal classification, **no live run** |

The question is: **a well-formed 200 whose `content` is empty, because the model
spent the whole output budget on hidden reasoning — is that an unanswerable
request, or a failed sample?** The answer this slice enforces:

> A 200 whose only failure is that the draft is missing is a **sample**, and a
> sample is retried inside the plane's existing retry budget; when every sample
> in that budget is empty the stage fails with the budget named, never with
> "the provider is unavailable".

Both halves of that sentence were false at base. The classification was
`PERMANENT` (so the first such reply ended the stage run outright), and the
ending was an availability error that said nothing about what to raise.

---

## 1. The defect, measured at `1677e7e`

`src/hermes/tools/models/cloud.py:705-717` (at base):

```python
if not (content or "").strip() and finish == "length":
    raise _permanent(
        provider_id, "EMPTY_COMPLETION",
        "the reply had no content and finish_reason='length' — the "
        "output budget (max_output_tokens) was exhausted before any "
        f"text (completion_tokens={completion}); raise the model's "
        "output budget (reasoning tokens count against it)",
        hazard="MALFORMED_200")
```

The diagnosis and the remedy in that sentence are right. The channel is what is
wrong: `_permanent` maps to `PermanentProviderError`, which
`ModelRouter._run_chain` handles by breaking out of the candidate and moving on
— and with a one-candidate chain the walk ends in
`ProviderUnavailableError(..., hazard_class="UNAVAILABLE", recordable=False)`.

Measured on the live CLI at the base commit, one stage, one planner tick, every
reply the run-36 body (`tests/test_zz_probe_base.py`, a temporary probe — this
is the pre-change half of the measurement; the file is deleted before commit):

```text
PROBE rc = 0
PROBE status = FAILED
PROBE terminal = NO_STAGE_RUNS
PROBE stages = []
PROBE refusals = []
PROBE model_attempts = [{"tier": "m", "provider": "tokenharbor",
  "model": "deepseek-v4.1-flash", "attempt": 1, "outcome": "PERMANENT",
  "tokens_in": 0, "tokens_out": 0, "failure_class": "MALFORMED_200",
  "http_status": null, "failure_detail": "EMPTY_COMPLETION: the reply had no
  content and finish_reason='length' — the output budget (max_output_tokens)
  was exhausted before any text (completion_tokens=4096); raise the model's
  output budget (reasoning tokens count against it)"}]
PROBE provider calls = 1
```

One call, and the run died with it: the stage never produced a row
(`NO_STAGE_RUNS`), no refusal was recorded, and the task parked `FAILED`. The
stdout line the operator saw was
`  model call 1: ... PERMANENT class=MALFORMED_200 (in 0, out 0)` — a class
that says *malformed*, about a request the provider accepted and answered.

Two independent things are wrong in that transcript, and they are the slice:

1. **the channel** — a sample that can succeed on the next call was classified
   unanswerable, so there was no next call;
2. **the ending** — when there genuinely is no draft, the record must name the
   budget rather than leave an availability error and a task parked `FAILED`.

---

## 2. The change

### 2.1 The edge: a failed sample, in the retryable channel (`cloud.py`)

```python
def _no_draft(provider_id: str, completion: int) -> TransientProviderError:
    return TransientProviderError(
        f"{EMPTY_COMPLETION}: the reply had no content and finish_reason="
        f"'length' — the output budget (max_output_tokens) was exhausted "
        f"before any text (completion_tokens={completion}); retried as a "
        f"failed sample, not a bad request; if every attempt returns empty, "
        f"raise the model's output budget (reasoning tokens count against it)",
        provider_id=provider_id, hazard_class=EMPTY_COMPLETION,
        recordable=True, http_status=200)
```

The channel is the retry decision (the plane never reads a message), the
sentence is what an operator needs when the retries run out, and the status
stays `200` because *the answer being inside a 200 is the whole point*.

`EMPTY_COMPLETION` is a new module constant in `router.py` and a **hazard
class**, not a refusal code: `REFUSAL_CODES` is unchanged, and the constant is
exported beside it with the reason written down. The whole retry therefore runs
through the plane's ordinary transient path — same candidate, same call form,
the policy's declared `RetryPolicy`, the existing jittered backoff — and no new
retry machinery exists anywhere.

Only the exact shape `content` empty **and** `finish_reason == "length"` is this
failure. An empty `content` with `finish_reason == "stop"` stays a raw reply
that the contract parser refuses (pinned: an empty completion with `stop` is
not this class).

### 2.2 The end of the walk: refusal-as-data that names the budget (`router.py`)

`_run_chain` already knew how a walk ends for every other failure. The one new
branch reads the class of the *last* transport failure:

```python
if last_transport is not None and _ran_out_of_drafts(last_transport):
    raise _Refusal(
        MALFORMED_PAYLOAD,
        _out_of_drafts_detail(last_transport, attempts_per_candidate,
                              candidates=len(candidates)),
        retryable=False,
        provider_id=..., model_id=..., account=self._ledger[-1])
```

`_ran_out_of_drafts` is `isinstance(exc, TransientProviderError) and
hazard_class == EMPTY_COMPLETION` — the class is read, never the message text.
Everything else that can end a walk keeps its present shape, including
`ProviderUnavailableError` for a genuinely unavailable model.

The detail is the provider's own sentence (which names `output budget` and
`max_output_tokens`) plus what the plane did about it:

```text
EMPTY_COMPLETION: the reply had no content and finish_reason='length' — the
output budget (max_output_tokens) was exhausted before any text
(completion_tokens=4096); retried as a failed sample, not a bad request; if
every attempt returns empty, raise the model's output budget (reasoning tokens
count against it) — all 4 attempt(s) returned no draft; the plane stops here
rather than asking the same budget again (OPS-5U)
```

The refusal is accounted against the attempt that ended the walk, so no ledger
row is invented for a decision no provider call corresponds to.

### 2.3 What the record looks like now

The same live scenario, post-change (`tests/test_zz_probe_new.py`, also
temporary):

```text
PROBE rc = 0
  model call 1: tier=m provider=tokenharbor model=deepseek-v4.1-flash TRANSIENT status=200 class=EMPTY_COMPLETION (in 0, out 0)
  model call 2: ... TRANSIENT status=200 class=EMPTY_COMPLETION (in 0, out 0)
  model call 3: ... TRANSIENT status=200 class=EMPTY_COMPLETION (in 0, out 0)
  model call 4: ... TRANSIENT status=200 class=EMPTY_COMPLETION (in 0, out 0)
PROBE stages = [{"stage": "QUESTION", "profile": "planner", "task_id":
  "meth-1:QUESTION", "state": "FAILED", "termination": "MODEL_REFUSED",
  "proposals": 0, "admissions": 0, "refusals": 1}]
PROBE refusals = [{"code": "MALFORMED_PAYLOAD", "detail": "model refusal:
  EMPTY_COMPLETION: ... — all 4 attempt(s) returned no draft; ... (OPS-5U)",
  "profile": "planner", "tick": 1, "stage": "QUESTION", "excerpt": ""}]
PROBE attempts = [{"attempt": 1, "outcome": "TRANSIENT", "tokens_in": 0,
  "tokens_out": 0, "failure_class": "EMPTY_COMPLETION", "http_status": 200},
  ... attempt 2, 3, 4 — identical shape]
PROBE task status = RETRYING
```

Four attempts (the first plus the policy's three retries), a stage row that
failed *and says why*, one refusal in the record, and `RETRYING` — the
substrate's own ladder, untouched, deciding what happens next.

---

## 3. The four answers

### 3.1 Retryable, or retryable-with-a-bigger-budget?

**Retryable, at the same budget — and the reason is a measurement, not a
preference.**

The charter asks whether the retry should raise the budget, "and if the second,
say where the budget lives and why it may grow at runtime when nothing else
may". It may not, and this slice refuses to make it the first number on the
model path that is invented while the run is in flight:

- **Budgets here are declared data.** Every bound on a call is fixed before the
  run starts: the plane policy's ceiling (code, `build_model_binding`), the
  model profile's ceiling (code, `_PROVIDER_MAX_OUTPUT_TOKENS`), the stage's
  own ask (`profiles/*.yaml`). The one thing that *does* grow at runtime is
  backoff **time** — and that grows under declared bounds (`base_delay_seconds`,
  `max_delay_seconds`, `jitter`) and consumes no authority, no record and no
  request bytes. A call's token bound has no such precedent, and inventing one
  in the retry loop would put a spend decision outside the declarations the
  composition check reads.
- **A budget raise could not have helped runs 32–36, as measured.** The number
  on the wire is the *minimum* of three declarations
  (`router.py:_max_output_tokens`), and the live wire carried **3072** — the
  planner profile's own ask — in every one of those runs, not the 32768 that
  `1677e7e` declared. A cap-less call is clamped to the plane's default 4096
  before any model declaration is consulted. So `_PROVIDER_MAX_OUTPUT_TOKENS`
  cannot change a live call in either direction, and the charter's premise
  ("I raised the budget to 32 768 and runs still hit it") is not what happened:
  the budget variable was never actually varied at the surface those runs used.
  `TestTheDeclaredBudgetNeverReachedTheWire` pins all three numbers and the one
  that binds.
- **Variance is what the sample loop is for.** The charter's own measurement —
  the same prompt producing content on one call and none on another — is
  exactly what a second sample addresses. Three samples of a variable-length
  reasoning trace is a different ask from one sample of it.

If the Director wants a bigger live number, it is **two coordinated declared
edits plus a re-record**, and §7 records why this slice does not take them:
raise the planner's ask (3072) *and* the plane's policy ceiling (4096 — the
composition's own default, which seals any declaration above it), then
re-record, because the number is inside the recorded request body.

### 3.2 What the retry budget costs

- **The bound is declared and small.** `RetryPolicy` (default and live:
  `max_retries = 3`) gives four attempts per candidate; at the stage's actual
  ask of 3072, a stage whose every sample is empty costs at most
  **4 × 3072 = 12 288 completion tokens**, against 3072 at base. The charter's
  ~100 K figure assumes the 32768 budget; at the number the wire really carries,
  a fully exhausted stage is an order of magnitude below it.
- **Time**: three backoff sleeps, bounded by the same policy (1 s base, 30 s cap,
  jittered).
- **Above the plane, nothing changed**: the substrate's ladder decides a
  failed-typed stage's fate with its own bounded rules (`FAILED → RETRYING`
  while `attempt < max_retries`, P-AUTO-4 quarantine on repeats) — the same
  rules every other model refusal already goes through.
- **H3 does not have to land first — but it must land before any raise.** The
  retry multiplies *uncharged* spend: every failed attempt in the probe above
  reports `tokens_in 0 / tokens_out 0`, although the provider returned
  `usage.completion_tokens = 4096`, because the no-draft branch raises before
  the dialect builds the `ModelResponse` that carries usage. One uncharged
  sample became four; at 3072 that is a bounded, small invisibility. At a raised
  budget the same multiplier applies to a number ten times larger, and the
  ledger would still say nothing. So the honest order is **H3 first, then any
  budget raise** — not because the retry is unbounded, but because the retry is
  what makes the accounting gap multiplicative.

### 3.3 Is `hazard="MALFORMED_200"` still right?

**No.** The class must say what happened, and what happened is that the draft is
missing: the envelope parsed, the choice and message were present,
`finish_reason` was present, the HTTP status was 200. `MALFORMED_200` is the
class of a 200 the parser could not use; this one was used all the way to the
"there is no content" decision. The class is now `EMPTY_COMPLETION` — the
plane's own words for the fact, already the prefix of the message. Consequences:

- the ledger row's `failure_class` and the run report's per-attempt
  `failure_class` both read `EMPTY_COMPLETION`, and the *stdout* line reads
  `TRANSIENT status=200 class=EMPTY_COMPLETION` instead of
  `PERMANENT class=MALFORMED_200`;
- `http_status` is now `200` where the permanent form carried none — an
  operator can see the answer came inside a success;
- `MALFORMED_200` keeps its meaning at every other site (an unparseable body
  from a provider), and no other classification changed;
- `EMPTY_COMPLETION` is **not** a refusal code: `REFUSAL_CODES` (frozen subset
  of `gateway.py:93-109`) is untouched, and the terminal refusal of §2.2
  carries the frozen `MALFORMED_PAYLOAD`.

### 3.4 What the stage does

When every attempt returns empty, the plane raises a refusal (never an
availability error, never an exception escaping the stage):

- **code** `MALFORMED_PAYLOAD` — the frozen code whose meaning is "the reply is
  not the payload the contract requires". The *budget* is named in the detail,
  not encoded in a new code: the plane introduces no vocabulary, and
  `MODEL_REFUSED` is a runtime *termination* value (`types.py:122`), not a
  gateway refusal code — the stage's termination is `MODEL_REFUSED` either way.
- **`retryable=False`, `contract_feedback=False`** — the runtime's informed
  retry re-asks with the refusal rendered into the prompt as data; here that
  would ask a model that just returned four empty samples to fix a *contract*
  problem it does not have, and would spend the run's own re-prompt budget on
  it. The plane's samples are the retry; when they are spent, the stage ends.
- **the record**: a stage row `FAILED` / `MODEL_REFUSED` / `refusals: 1`, one
  run-report refusal whose detail names the budget, and one ledger row per
  provider call (four), all `TRANSIENT / EMPTY_COMPLETION / 200`.
- **the task**: the substrate's existing ladder, measured live as `RETRYING`
  after the tick (at base the same scenario parked the task `FAILED` with no
  stage row at all). That is a re-dispatch of the same stage at the same budget
  under the substrate's own bounds — and the reason `_out_of_drafts_detail`
  says how many attempts on how many candidates were spent: one empty sample
  and an exhausted budget are different incidents.

---

## 4. What does not change

| Constraint (charter §4) | Evidence |
| --- | --- |
| No new event kind, write path or transaction; census 124 / 28 (19/5/4) / 1 / 15 / 0 | `scripts/check_census.py` — PASS, figures reproduced exactly |
| A genuinely permanent failure is still permanent | `TestWhatMustNotChange`: 400 and 402 called **once**, `PERMANENT`, and a 500 still ends in `ProviderUnavailableError` after its retries |
| Substrate rules, gateway checks, capability grants | no file outside `tools/models/{cloud,router}.py` touched |
| Drain-only byte-identical; B4 24; LOOP baseline | `tests/test_loop_baseline.py`, `tests/test_b4_ref_graphs.py` green; the wire number is unchanged (no budget edit — §7) |
| Act-key, `proposable_kinds`, `max_ticks`, objectives | untouched |
| No key material, no reasoning text in any journal row | `test_the_reasoning_text_is_never_recorded` (hostile marker in `reasoning_content`, absent from refusal, ledger and detail) |

---

## 5. Falsifiers, and where each is pinned

| Falsifier (charter §5) | Test |
| --- | --- |
| An empty completion is retried and a subsequent good sample lets the stage proceed | `TestTheWalkIsRetried::test_a_no_draft_sample_is_retried_and_the_next_sample_answers`, `TestTheStage::test_a_live_stage_proceeds_after_one_empty_sample` |
| A persistent empty completion still fails the stage, with a code that names the budget | `test_a_walk_that_never_drafts_ends_as_a_refusal_naming_the_budget`, `TestTheStage::test_a_persistent_empty_completion_fails_the_stage_and_names_the_budget` |
| A 400/402 is still permanent — no retry | `TestWhatMustNotChange::test_a_400_or_402_is_still_permanent_and_called_once` |
| The retry budget bounds the attempts | `test_the_retry_budget_bounds_the_attempts` (0, 1, 3 retries) |
| Baseline and census unchanged | the existing gate tests, run in this slice's targeted set; `scripts/check_census.py` |

Also pinned, because each is a way this fix could quietly go wrong: the retried
attempt asks the *same* declared question
(`test_the_retried_attempt_asks_the_same_declared_question`), the terminal
refusal invents no ledger row
(`test_the_terminal_refusal_invents_no_ledger_row`), an empty completion with
`finish_reason == "stop"` is not this class
(`test_an_empty_completion_with_stop_is_still_a_raw_reply`), the class sits at
the provider edge (`test_the_provider_edge_raises_the_retryable_class`), and no
new refusal code was introduced (`test_empty_completion_is_not_a_refusal_code`).

---

## 6. Gates

1. Targeted, per the charter: `test_ops5u_empty_completion`,
   `test_cloud_provider`, `test_model_plane`, `test_ops5n_retry_identity`,
   `test_loop_baseline`, `test_b4_ref_graphs`, `test_census_check`.
2. `scripts/run_tests.py` (full).
3. `scripts/stamp_suite_count.py`, then `--check`.
4. `scripts/check_census.py` — unchanged.
5. `uvx ruff check src tests scripts`; `uvx pyright src`; pyright tests project.

Raw lines for every one of them are in the slice report, beside this file's
diff.

---

## 7. What this slice refuses

1. **No runtime budget growth** (§3.1): the retry re-asks the declared call, and
   the declared call is the only bound.
2. **No declared-budget raise** (§3.1, §3.2): the planner's ask (3072) and the
   plane's default ceiling (4096) both bind, and the wire number is inside the
   recorded request body — fixtures are keyed by the redacted request
   (IDR-046 D4), so moving it is a declared-data change plus a re-record, never
   a side effect of a classification fix. `H3` should land first.
3. **No reclassification of any other failure**: one code changed channel; 400,
   402, 429, 5xx and every refusal keep the meaning they had.
4. **No plane retry of a permanent failure** — the opposite, deliberately: the
   *walk* stops at a genuinely permanent answer, and the no-draft ending is
   `retryable=False` so the runtime does not re-ask it either.
5. **The composition change this slice drafted and dropped.** Making the plane
   policy's ceiling follow the largest declared provider budget is *inert where
   the runs died* (3072 binds first, measured), and it would put a second
   concern in a one-concern slice. It is recorded here as a finding for the next
   budget decision: today the plane's own default (4096) silently seals every
   bigger provider declaration, so a raise of the profile ask alone would land
   on 4096 — and that arithmetic is pinned in
   `TestTheDeclaredBudgetNeverReachedTheWire` either way.
