# OPS-5W — every budget class is smaller than a thought

| Item | Value |
| --- | --- |
| Task | OPS-5W: what a stage's output budget should be when the model reasons before it answers |
| Base | `main` at `a4b3c95` |
| Branch | `slice/ops-5w-output-budget` |
| Phase | **1 (design gate) — awaiting approval** |
| Status | No product code changed. The probes are read-only |
| Findings | The live wire's 3072 (the planner ask, sealed by a 4096 policy and a 32768 provider ceiling); the deepseek trace leaves every live ask too small for reasoning plus the largest reply; empty attempts spend tokens the ledger reports as 0 (H3) |

## 0. Verdict summary

1. **The cited class is a prompt budget, not the output budget.** The charter
   quotes `prompt_assembly.py` `BudgetClass` (2048/3072/4096), but those are
   `max_prompt_chars` and `max_evidence_refs`; the class has no token field
   (measured, §1.1). The live output budget is the stage profile's
   `model_policy.max_output_tokens` — planner 3072, researcher 2048,
   synthesizer 4096 — and the wire is the minimum of that ask, the plane policy
   ceiling (4096) and the model's provider ceiling (32768). The effect the
   charter names is real: every live ask is at or below 4096; the planner's
   3072 and the researcher's 2048 are below the observed deepseek reasoning
   alone (3 906), and the synthesizer's 4096 leaves only 190 tokens for content
   after that reasoning, below the 2 048 largest legal reply. The mechanism is
   the profile ask, not the prompt class. A `REASONING` entry in `BudgetClass`
   would not move the wire by one token.

2. **A fourth output tier, not a per-ask allowance, and not a prompt class.**
   The output budget gains a code-owned, per-model `reasoning_floor_tokens`
   declaration: a **reasoning floor of 16 384** tokens, applied when the
   selected model declares it. The effective ask is
   `max(stage_ask, reasoning_floor)`, clamped by the plane ceiling and the
   model/provider ceiling. The three stage asks keep their values and their
   meaning for non-reasoning models; a reasoning model gets the floor. The
   stage ask remains visible in the report. A task carrying
   `cost_class: "large"` keeps its prompt `LARGE` tier (4096 prompt chars,
   32 refs), keeps the controller's `UNKNOWN` reading (LARGE is not a ratified
   `CostTier`), and gets the same output treatment as any task on its stage
   profile: the floor only if the selected model reasons. No operator-facing
   `cost_class` meaning changes.

3. **The number is 16 384 tokens.** The arithmetic is in §2.3:
   15 623 reasoning chars ÷ 4 = **3 906 tokens**; the largest legal reply is
   8 192 bytes ÷ 4 = **2 048 tokens**; the observed subtotal is **5 954**;
   16 384 leaves **10 430 tokens of headroom**. The total is 2.75× the observed
   subtotal; the headroom is 2.67× the observed reasoning. 16 KiB is the
   smallest measured working budget
   (16 KiB and 32 KiB both finished; 8 KiB did not). The provider's 32 768
   stays an outer ceiling; the *ask* is 16 384. The plane policy ceiling rises
   from 4 096 to 16 384, so it stops sealing the floor; a stage ask above
   16 384 clamps at the plane ceiling, not the provider's 32 768.

4. **The budget bounds the whole completion, not the reply.** The number on the
   wire is `max_tokens`, which the provider counts over reasoning **and**
   content. That is the intended meaning of `max_output_tokens`; the report
   will make the split visible as `tokens_reasoning` and `content_chars`
   (`tokens_out` stays the whole completion). The largest legal reply
   (8 192 bytes) is a proposal cap, not the token budget; 2 048 of the 16 384
   tokens cover it at the same 4-chars/token estimate the router's pre-flight
   uses.

5. **H3 must land first.** An empty attempt is currently free in the ledger and
   expensive on the invoice: `_attempt` starts `usage = TokenUsage()`, the
   `EMPTY_COMPLETION` error carries no usage, and the `TRANSIENT` row records
   0 / 0 (measured, §1.3). Raising the budget before that fix would multiply
   an invisible cost: at the new floor, one model-call walk whose every sample
   is empty can spend up to **4 × 16 384 = 65 536** completion tokens (the
   live retry budget is three retries), versus 4 × 3 072 = 12 288 today; a
   multi-tick stage multiplies that by its ticks. H3 is the first commit of
   phase 2, not a parallel option.

6. **What the operator sees: `tokens_reasoning` (and `content_chars`).** A
   model attempt row carries `tokens_in`, `tokens_out`, `tokens_reasoning`,
   `content_chars`, plus a `budget` block with `ask`, `reasoning_floor`,
   `ceiling`, `model_max` and `effective`. A stage that burns 12 K reasoning
   tokens and produces 200 characters shows 12 116 `tokens_reasoning` and 200
   `content_chars`; the empty-completion row shows the same counts beside
   `failure_class: EMPTY_COMPLETION` instead of 0 / 0. `tokens_reasoning` is
   `null` when the provider does not report a separate count — never a false
   zero. No reasoning text is recorded anywhere.

7. **No new event kind, write path or transaction. Census unchanged:
   124 / 28 (19/5/4) / 1 / 15 / 0.** The changes are a model-profile
   declaration, a policy ceiling, the router's min/floor formula, a usage
   count, and diagnostic report fields. Drain-only byte-identical; B4 24; LOOP
   baseline unchanged; governed docs untouched. `proposable_kinds`,
   `max_ticks`, objectives and the act-key are untouched.

## 1. The measurement

All probes ran read-only on `a4b3c95`. The OPS-5U budget group
(`TestTheDeclaredBudgetNeverReachedTheWire`) passes on this base; the probe
commands are in Appendix A.

### 1.1 The cited class is prompt, not output

```
BudgetClass fields: ('name', 'max_prompt_chars', 'max_evidence_refs',
                     'SMALL', 'STANDARD', 'LARGE')
STANDARD: BudgetClass(name='STANDARD', max_prompt_chars=3072,
                      max_evidence_refs=16)
planner output ask: 3072
researcher: 2048   synthesizer: 4096
```

`BudgetClass` (`prompt_assembly.py:79-120`) is the prompt-assembly tier used
by `StubModelClient._budget_for` (`:268-271`) and `assemble_prompt`
(`:162-246`). It has no `max_output_tokens` field. The only live output ask is
the runtime profile's `model_policy.max_output_tokens`
(`agents/runtime/config.py:451-464`), passed into the request at
`agents/runtime/run.py:1803`. The two scales coincide numerically
(2048/3072/4096) because both were chosen as small/medium/large, which is
probably why the charter read one as the other. The finding's *effect* is
still correct: the deepest live ask is 4096, the planner's 3072 is below the
observed reasoning (3 906), and the synthesizer's 4096 leaves only 190 tokens
for content after it.

The live chain, in order:

| Declaration | Where | Live value |
| --- | --- | --- |
| Stage ask | `profiles/planner.yaml:19` (`model_policy.max_output_tokens`) | **3072** |
| Plane policy ceiling | `router.py:1356` (`ModelPlanePolicy.max_output_tokens` = `DEFAULT_MAX_OUTPUT_TOKENS`) | **4096** |
| Model/provider ceiling | `composition.py:202-210` (`_PROVIDER_MAX_OUTPUT_TOKENS` → `CloudModelSpec.max_output_tokens`) | **32768** (tokenharbor/anyrouter); 4096 elsewhere |
| Model-declared setting | `ModelProfile.settings.max_output_tokens` | `None` live |
| **Effective wire** | `router.py:1819-1830` (`min`) | **3072** |

The OPS-5U pin measured the same number at the live CLI:
`test_the_live_wire_carries_the_profiles_own_ask` asserts the body's
`max_tokens` is the planner's 3072, under both ceilings. The 32768 from
`1677e7e` is a ceiling that no live ask reaches; it is not the budget.

### 1.2 The deepseek trace leaves no live ask enough room

| Model | Reasoning chars | ≈ tokens (chars ÷ 4) | Content chars |
| --- | --- | --- | --- |
| deepseek-v4.1-flash | 15 623 | **3 906** | 220 |
| minimax-m3.1-flash | 1 587 | 397 | 1 070 |

At 3072 the planner can spend its entire completion budget on the deepseek
trace and emit `content: ""`; that is `EMPTY_COMPLETION` (OPS-5U). At 2048 the
researcher/critic/verifier cannot fit the deepseek trace at all, and even the
minimax trace plus the 2 048 largest reply (2 445) does not fit. At 4096 the
synthesizer fits the deepseek trace but leaves only 190 tokens for content,
below the 2 048 largest legal reply. The retry re-asks the same number, so
every sample fails the same way; OPS-5U correctly made the sample retryable,
but the retry cannot help until the ask is larger.

### 1.3 H3 — the empty attempt is free in the ledger

Using the OPS-5U fixture (`usage.prompt_tokens=40`,
`usage.completion_tokens=4096`, empty content, `finish_reason=length`):

```
row: 1 TRANSIENT EMPTY_COMPLETION tokens_in 0 tokens_out 0 max_tokens 4096
row: 2 TRANSIENT EMPTY_COMPLETION tokens_in 0 tokens_out 0 max_tokens 4096
row: 3 TRANSIENT EMPTY_COMPLETION tokens_in 0 tokens_out 0 max_tokens 4096
```

The provider reported 40 prompt and 4096 completion tokens; the ledger kept
neither. The path is exact: `_attempt` starts `usage = TokenUsage()`
(`router.py:2005`); `_no_draft` raises a `TransientProviderError` carrying the
message and the completion count in text, but no usage (`cloud.py:146-165`);
the `except TransientProviderError` branch records `usage` unchanged
(`router.py:2030-2040`). The run report prints `tokens_in` / `tokens_out` from
that row (`run_report.py:142-195`). A stage whose every sample is empty is
therefore reported as 0 / 0, while the invoice counts the reasoning tokens.
OPS-5U's own report moved the *reason* (it names the budget); it did not move
the *cost*.

## 2. The output-budget design

### 2.1 The layers are different, and the fix belongs at the output layer

There are two budgets in the tree and they must not be conflated:

- **Prompt budget** — `BudgetClass` (prompt chars, evidence refs). It bounds
  what is sent, not what is generated. It is used by the extraction stub, not
  by a live stage.
- **Output budget** — `max_output_tokens` / `max_tokens` on the completion.
  It bounds reasoning + content. It is the stage profile's ask, min'd with the
  plane and provider ceilings.

OPS-5W changes only the output layer. The prompt classes stay exactly where
they are; `test_p_auto_2_prompts` remains the pin.

### 2.2 The chosen shape: a fourth output tier (a reasoning floor)

Add a code-owned, per-model declaration:

- `ModelProfile.reasoning_floor_tokens: int = 0` (and the same field on
  `CloudModelSpec`, copied by `to_profile`);
- a code-owned map keyed by `(provider_id, model_id)` — the measured
  `deepseek-v4.1-flash` and `minimax-m3.1-flash` on the tokenharbor/anyrouter
  gateways; the exact keys are the live tier refs — sets **16 384**; a model
  not listed is 0 and its budget is unchanged. Keying by
  model, not provider, is what keeps a non-reasoning model on the same gateway
  at its old budget. The declaration is a non-negative integer; a bool,
  float or negative value refuses at construction, the same fail-closed shape
  as `model_policy.max_output_tokens` (`agents/runtime/config.py:451-455`).

The router's formula becomes:

```python
ceiling = min(self._policy.max_output_tokens, profile.max_output_tokens)
declared = profile.settings.max_output_tokens
if declared is not None:
    ceiling = min(ceiling, declared)
ask = DEFAULT_MAX_OUTPUT_TOKENS if request.max_output_tokens is None \
      else request.max_output_tokens
if profile.reasoning_floor_tokens:
    ask = max(ask, profile.reasoning_floor_tokens)
return max(1, min(ask, ceiling))
```

with:

- `DEFAULT_MAX_OUTPUT_TOKENS` = **4096** (the cap-less base, unchanged);
- `ModelPlanePolicy.max_output_tokens` = **16 384** (was 4096) — the plane's
  ceiling, so the floor is not sealed;
- `_PROVIDER_MAX_OUTPUT_TOKENS` = **32 768** for the reasoning gateways
  (unchanged) — the provider's outer ceiling.

The resulting live numbers:

| Profile | Stage ask | Reasoning floor | Effective (reasoning model) | Effective (non-reasoning model) |
| --- | --- | --- | --- | --- |
| researcher / critic / verifier | 2048 | 16 384 | **16 384** | 2048 |
| planner / experimenter | 3072 | 16 384 | **16 384** | 3072 |
| synthesizer | 4096 | 16 384 | **16 384** | 4096 |
| cap-less caller | 4096 (default) | 16 384 | **16 384** | 4096 |

For a non-reasoning model the formula returns its ask (or the 4 096 cap-less
base). The only visible change would be a caller that explicitly asks above
4 096 on a model whose provider ceiling is above 4 096; no live profile asks
above 4 096, and all live non-reasoning providers declare the 4 096 default.
The raised plane ceiling is a cap, not an ask: it changes what a caller *may*
ask, not what it does ask.

The floor is a **floor on the ask**, not a ceiling in principle; in this
design the plane ceiling is also 16 384, so a stage that explicitly asks for
more than 16 384 is clamped at 16 384 until the plane ceiling is raised. No
live profile asks more, so the live reasoning wire is 16 384. The stage ask is
still in the report (`budget.ask`), and the effective is `budget.effective`.
The provider's 32 768 remains the outer ceiling; raising the plane ceiling to
32 768 is a one-line declaration change, not a new mechanism.

**Why a fourth tier rather than a per-ask allowance?** The charter's two
options are about the output layer. An allowance added to every ask (say
+12 288) would change the meaning of every stage ask and would double-count the
reply: the base ask already covers the reply, so an allowance should cover
only reasoning, and then every profile carries two numbers. A floor is one
number, applied only when the selected model reasons, and the stage ask keeps
its non-reasoning meaning. It is the "REASONING class" option: the fourth tier
is 16 384; the three existing asks are unchanged.

**What happens to `cost_class: "large"`?**

| Layer | Today | After OPS-5W |
| --- | --- | --- |
| `BudgetClass.from_cost_class("large")` | `LARGE` (4096 prompt chars, 32 refs) | unchanged |
| controller `CostTier` | raw `"large"` uppercases to `LARGE`, which is not LOW/MEDIUM/HIGH → `UNKNOWN` (`controller.py:3628-3633`) | unchanged |
| output budget | not selected by `cost_class` | still not; the floor is selected by the model |
| a task carrying `cost_class: "large"` | no production task carries it (the constants are `"small"` for EXTRACT/SOURCE/GRAPH) | same as today; on a reasoning model it gets the floor, on a non-reasoning model its stage ask |

No operator-facing `cost_class` meaning changes. If the Director wants
`cost_class: "large"` to select a larger output budget, that is a new
operator-facing mapping with a wider blast radius (it would reinterpret
existing task data); it is not part of this design.

### 2.3 The number: 16 384, with the arithmetic

The estimate uses the router's own 4-chars-per-token rule
(`router.py:1807-1817`), so the number is in the same unit the pre-flight
uses.

| Term | Value | Source / derivation |
| --- | --- | --- |
| Observed reasoning | 15 623 chars ÷ 4 = **3 906 tokens** | deepseek-v4.1-flash, the charter's measurement |
| Largest legal reply | 8 192 bytes ÷ 4 = **2 048 tokens** | `MAX_PROPOSAL_BYTES` (`router.py:237`), ASCII JSON at 4 chars/token |
| Observed subtotal | **5 954 tokens** | 3 906 + 2 048 |
| Headroom | **10 430 tokens** | 16 384 − 5 954 |
| **Reasoning floor** | **16 384 tokens** | 3 906 + 2 048 + 10 430 |

Why 16 384, and why the sum:

- It is the smallest budget measured to finish on the provider (16 KiB and
  32 KiB both finished; 8 KiB did not). The measured working budget was
  16 KiB, declared as 16 384 tokens; the number is not a wish.
- The headroom is 2.67× the observed reasoning; the total is 2.75× the
  observed subtotal. It covers one more full sample at the observed reasoning
  length (3 906) plus 6 524 tokens — enough for sampling variance in the
  reasoning trace without paying for the 32 KiB ceiling on every call.
- The largest legal reply fits with 14 336 tokens left for reasoning
  (16 384 − 2 048); the observed 3 906 is 27% of that.
- 16 384 is 4 × the old 4 096 default, a round binary number an operator can
  hold in their head. It is not 32 768 because the 32 KiB provider declaration
  is an outer ceiling, not a measured need; paying 32 KiB on every reasoning
  call doubles the worst case for no measured benefit. A future stage that
  needs more than 16 384 raises the plane ceiling with the floor; the
  provider's 32 768 is already there to receive it.
- Worst case for one retry walk, if every sample is empty: the live retry
  budget is three retries (four attempts), so **4 × 16 384 = 65 536 completion
  tokens**, versus 4 × 3 072 = 12 288 today; a multi-tick stage multiplies
  that by its ticks. That is the number H3 must make visible.

The context pre-flight uses the same effective budget
(`router.py:1798-1804`): a 4 096-char prompt (the extraction assembler's cap)
is ≈ 1 024 tokens by the router's own estimate; even a prompt an order of
magnitude larger plus 16 384 is far below the 200 000-token window of the
reasoning gateways. The pre-flight reads the actual prompt envelopes, so the
larger budget can only make a genuinely oversized request refuse earlier; it
does not widen the window (the test is in §6).

### 2.4 The budget bounds the whole completion

`max_tokens` is the provider's completion bound: reasoning + content. That is
the intended meaning; the name `max_output_tokens` is accurate if "output"
includes the hidden reasoning. The design does not rename the field. It makes
the split visible:

- `tokens_out` = the provider's completion tokens, including reasoning;
- `tokens_reasoning` = the provider's separately reported reasoning count, or
  `null` when not reported;
- `content_chars` = the characters of the content the provider returned
  (0 for a no-draft sample; never the reasoning text);

The content token count, when wanted, is `tokens_out - tokens_reasoning`
(known-reasoning case); the report shows the total and the reasoning count,
which is enough to read the split without a third derived field.

- `budget.ask` = the stage's declared ask;
- `budget.reasoning_floor` = the model's declared floor (0 if none);
- `budget.ceiling` = the plane ceiling (16 384);
- `budget.model_max` = the provider/model ceiling (32 768 for the reasoning
  gateways);
- `budget.effective` = what the wire carries.

The field names are final: `tokens_reasoning` and `content_chars` in the
report; `reasoning_floor_tokens` on the model profile/spec and in the budget
block as `reasoning_floor`. The report's `tokens_out` is unchanged, so an old
reader sees the whole completion; the new fields explain it.

### 2.5 What this does not do

- It does not change the prompt `BudgetClass` values or `cost_class`.
- It does not make a reasoning model spend 16 384; the budget is a cap.
- It does not raise the retry budget or escalate the ask between samples.
- It does not charge model tokens to the controller's per-run token caps;
  those count provider requests (OPS-16), a different bound. The model spend
  is made visible by H3, not enforced by `per_run_tokens`.
- It does not change the provider ceiling: 32 768 stays a ceiling; the ask is
  16 384.

## 3. H3 — the cost must be visible before the budget rises

### 3.1 The defect

The empty-completion path throws before `ModelResponse.usage` exists:

- `OpenAIChatDialect.parse` reads `usage` and `completion_tokens`, sees empty
  content with `finish_reason: length`, and calls `_no_draft(provider_id,
  completion)` (`cloud.py:730-745`);
- `_no_draft` raises `TransientProviderError` with the completion count only
  in the message (`cloud.py:146-165`);
- `_attempt` initializes `usage = TokenUsage()` and, on the transient branch,
  records that zero (`router.py:2005-2040`);
- the row is the one the run report prints (`run_report.py:142-195`).

The OPS-5U design already says "the output bound a call carries is the
minimum of three declarations" and that a budget raise must be paired with a
re-record; it did not claim the usage was visible. H3 is the missing half.

### 3.2 The fix

1. `TokenUsage` gains `reasoning_tokens: int | None = None` (None = the
   provider did not report a separate count; never a false 0). `__add__`
   propagates None; `total_tokens` stays input + output. `ModelFixture` gains
   the optional count, recorded from the response usage; the fixture identity
   still keys on the normalized request, not usage.
2. The OpenAI dialect parses `usage.completion_tokens_details.reasoning_tokens`
   (or `usage.reasoning_tokens` when present) and passes the sample's
   `prompt_tokens`, `completion_tokens` and reasoning count to `_no_draft`.
   The error carries those counts as data; `_attempt` records them on the
   `TRANSIENT` row instead of `TokenUsage()`. The counts are integers; no
   reasoning text is carried, stored or reported.
3. `ModelCallAccount` and `DispatchAccount` carry `reasoning_tokens` and
   `content_chars` (and the budget block values); the run report's
   `_attempt_row` prints `tokens_reasoning`, `content_chars` and `budget`. The
   CLI's model-call line adds `reasoning=<n>` when known, so a live operator
   sees it without opening the report. `content_chars` is the length of the
   content string, never the reasoning text.
4. The empty-completion retry (OPS-5U) is unchanged: same candidate, same
   budget, ordinary retry budget. H3 changes what is recorded, never what is
   asked.

### 3.3 Why first

A budget rise without H3 raises an unmeasured spend. At the new floor the
worst case is 65 536 completion tokens for one retry walk (four empty
attempts); at the old planner ask it is 12 288. A multi-tick stage multiplies
that by its ticks. The ledger currently says 0 / 0 for every one of those
attempts. The budget change is therefore phase 2's **second** commit, after
H3's usage fix; the design note does not approve a budget raise that leaves
the invoice invisible. The two concerns stay separate commits so the
accounting change can be reviewed on its own.

## 4. What the operator sees

A model attempt row after the change (illustrative; `tokens_reasoning` is
`null` if the provider did not report it):

```json
{
  "tier": "m",
  "provider": "tokenharbor",
  "model": "deepseek-v4.1-flash",
  "attempt": 1,
  "outcome": "OK",
  "tokens_in": 1024,
  "tokens_out": 12184,
  "tokens_reasoning": 12116,
  "content_chars": 200,
  "duration_ms": 4210,
  "budget": {
    "ask": 3072,
    "reasoning_floor": 16384,
    "ceiling": 16384,
    "model_max": 32768,
    "effective": 16384
  }
}
```

The 200-character content is exactly `content_chars: 200` beside
`tokens_reasoning: 12116`; the operator can see that the stage paid for
thinking, not for prose. On an empty sample the same row has
`failure_class: EMPTY_COMPLETION`, `tokens_out`/`tokens_reasoning` from the
provider, `content_chars: 0`, and the failure detail that names the budget. On
a non-reasoning model, `tokens_reasoning` is `null`/0 and the budget block's
`reasoning_floor` is 0; the row's `effective` is the old ask.

The budget block makes the three declarations visible together: the stage
asked 3 072, the model's floor is 16 384, the plane's ceiling is 16 384, the
provider's ceiling is 32 768, and the wire carries 16 384. No reader has to
reconstruct the min from three files.

## 5. Invariants

The charter's "what must not change", mapped:

1. **No new event kind, write path or transaction.** The changes are model
   metadata, a policy ceiling, the router formula, a usage count and report
   fields. Census stays **124 / 28 (19/5/4) / 1 / 15 / 0**
   (`scripts/check_census.py` on the base: PASS).
2. **`cost_class` meaning unchanged.** LARGE stays a prompt tier; the
   controller still reads `"large"` as `UNKNOWN`; the output floor is
   model-triggered, not `cost_class`-triggered. No task carrying it is
   reinterpreted.
3. **The provider ceiling stays a ceiling; the ask and the ceiling stay
   visible.** `_PROVIDER_MAX_OUTPUT_TOKENS` 32 768 remains; the plane ceiling
   is 16 384; the effective wire is 16 384; the report's `budget` block shows
   all three. The provider's 32 768 is not rewritten or removed.
4. **Drain-only byte-identical; B4 24; LOOP baseline unchanged; governed docs
   untouched.** The budget changes only live model calls; the LOOP baseline
   uses scripted model ports and does not carry the report block. The run
   report's model-attempt rows gain fields; a drain-only run has no model
   attempts, so its report is unchanged. B4's reference graphs are unrelated.
5. **`proposable_kinds`, `max_ticks`, objectives, the act-key untouched.**
   The max-token change does not touch any intent, tick or authority bound.
6. **No key material; no reasoning text in any journal row.** The model
   ledger and report carry counts only; the fixture's `text_hex` remains the
   content, never `reasoning_content`. The OPS-5U hostile-marker pin stays
   green.

## 6. Falsifiers → tests

The new test file is `tests/test_ops5w_output_budget.py`; it uses the
test-owned scripted transports and the OPS-5U fixtures. The named pins:

| # | Falsifier | Test | Red on base? |
| --- | --- | --- | --- |
| 1 | A reasoning model that spends its budget thinking still emits a draft at the new budget | `test_a_reasoning_stage_emits_a_draft_at_the_floor` (empty sample, then a good one, live CLI path with a scripted transport) | yes (the wire/budget pin; a scripted model cannot prove the real-model fit, which is the measured claim) |
| 2 | The wire carries the reasoning floor, under both ceilings | `test_the_wire_carries_the_reasoning_floor` (planner ask 3072 → body `max_tokens` 16 384) | yes (base: 3072) |
| 3 | A non-reasoning model's budget is unchanged | `test_a_non_reasoning_model_keeps_its_ask` (researcher 2048, planner 3072, synthesizer 4096; cap-less 4096) | no (regression) |
| 4 | The context pre-flight still refuses a call that genuinely does not fit | `test_the_context_preflight_still_refuses_an_oversized_call` (tiny window, effective 16 384) | no (regression) |
| 5 | An empty completion is still retried (OPS-5U unbroken) | the existing `TestTheWalkIsRetried` / `TestTheStage` pins | no (regression) |
| 6 | An empty attempt records its usage | `test_an_empty_completion_records_its_usage` (tokens_in 40, tokens_out 4096, row not 0/0) | yes (base: 0/0) |
| 7 | The report names reasoning tokens and the content length | `test_the_report_names_tokens_reasoning` (12 184 out, 12 116 reasoning, 200 content_chars) | yes (fields absent) |
| 8 | The report shows the ask, floor, ceiling, model max and effective | `test_the_budget_block_shows_ask_floor_ceiling` | yes (fields absent) |
| 9 | No reasoning text is recorded | the existing OPS-5U `test_the_reasoning_text_is_never_recorded` (hostile marker; counts only) | no (regression) |
| 10 | Baseline and census unchanged | `test_loop_baseline`, `test_b4_ref_graphs`, `test_census_check` | no |

The OPS-5U test class `TestTheDeclaredBudgetNeverReachedTheWire` is
**updated, not deleted**: it becomes the pin that the reasoning floor now
reaches the wire (policy 16 384, model 32 768, ask 3 072, floor 16 384,
effective 16 384). Its old 4 096/32 768/3 072 values were the finding; the new
values are the closure. The OPS-5U retry pins stay byte-for-byte.

The run report's old attempt-row pin uses a `set(row) >= {...}` check
(`test_ops10_run_report.py:108-111`), so the extra fields are additive there;
the new keys are pinned in test 7/8 above. The CLI model-call line gains
`reasoning=`; its pin is updated with the report.

## 7. Gates (implementation phase)

1. Targeted: `tests/test_ops5w_output_budget.py`,
   `tests/test_ops5u_empty_completion.py`,
   `tests/test_ops5f_stage_budget.py`, `tests/test_p_auto_2_prompts.py`
   (the file that owns the prompt classes; the charter's
   `test_prompt_assembly` name does not exist in this tree),
   `tests/test_ops10_run_report.py`, `tests/test_loop_baseline.py`,
   `tests/test_b4_ref_graphs.py`, `tests/test_census_check.py`.
2. `scripts/run_tests.py` (full).
3. `scripts/stamp_suite_count.py` then `--check`.
4. `scripts/check_census.py` — unchanged.
5. `uvx ruff check src tests scripts`; `uvx pyright src`; pyright tests
   project.

For this design-note commit: the change is documentation-only, so the
AGENTS.md docs-only rule applies — the full suite must be green before the
commit. It ran on the base tree: **5576 passed, 3 skipped** (5579 collected);
the note changes no test.

## 8. What I could not decide from the tree

1. **The policy ceiling: 16 384 or 32 768?** I chose 16 384, equal to the
   reasoning floor, so the plane cap and the ask are the same and no live call
   can ask above the measured working budget. The provider's 32 768 remains an
   outer ceiling; a future stage that needs more raises the plane ceiling and
   the floor together. If the Director wants the 32 KiB declaration to be
   reachable, set the policy ceiling to 32 768; the floor can stay 16 384 and
   the report already names both.
2. **A per-model or per-provider reasoning declaration?** I chose per-model
   (`(provider_id, model_id)`), so a non-reasoning model on the same gateway
   keeps its old budget. The two measured models are listed; a new reasoning
   model needs an explicit code entry, the same review discipline as the
   provider ceiling. A provider-level declaration would be simpler but would
   raise every model on that gateway.
3. **H3 first, or the same commit?** I chose a separate first commit: H3 can
   be reviewed as an accounting fix with no budget change, and the budget
   change then has a measured cost. The two can land in one slice, but not in
   one commit.
4. **Does the floor apply to a cap-less call?** I chose yes: the cap-less base
   is 4096, the floor lifts it to 16 384 on a reasoning model. A cap-less call
   to a non-reasoning model stays 4096. If the Director wants a cap-less call
   to remain 4096 even on a reasoning model, the floor would apply only to an
   explicit ask, and a caller that forgets the ask would still empty-complete;
   I do not recommend it.
5. **Should the empty attempt be charged to the controller's token caps?**
   No: those caps count provider requests (OPS-16), not model tokens; changing
   their meaning is a separate slice. H3 makes the model spend visible in the
   ledger/report; it does not make `per_run_tokens` a model-token cap.
6. **Should `max_output_tokens` be renamed `max_completion_tokens`?** I chose
   no rename: the field already means the whole completion at the provider
   edge; the report's `tokens_reasoning`/`content_chars` removes the
   ambiguity. A rename would touch the profile schema, the request, the call,
   the ledger and every fixture for no semantic gain.
7. **The charter's `BudgetClass` citation.** I could not make it the output
   budget: the class has prompt fields only and the live path never reads it.
   The finding is still real through the profile ask. If the Director intended
   a different class object (not this one), it is not in this tree at
   `a4b3c95`.
8. **Recorded fixtures.** The effective `max_tokens` is inside the normalized
   request, and fixtures are keyed by it; a live recording made before this
   change cannot replay a call at 16 384. The repo's tests use scripted
   transports, so no in-tree fixture changes; the live composition's recording
   sink must re-record the reasoning calls. The note cannot do that from the
   tree; it is a deployment step.

## 9. Claim boundary

This note claims the budget chain and the H3 zero-usage path as measured on
`a4b3c95`; it does not claim a live model will emit a draft at 16 384 (the
provider measured 16 KiB and 32 KiB finishing, but that is a sample, not a
guarantee), and it does not claim the budget is the only variable in run 37.
It does not claim the prompt `BudgetClass` is the output budget; it claims the
opposite. It does not implement; phase 2 waits for approval. No reasoning text
is stored or reported; only counts.

## 10. Phase 2 order (if approved)

1. **H3 first**: `TokenUsage.reasoning_tokens`, the empty-completion error's
   usage, the ledger/dispatch fields, the run report and CLI fields; tests 6,
   7, 9; no budget change.
2. **The reasoning floor**: `ModelProfile.reasoning_floor_tokens`,
   `CloudModelSpec`, the code-owned per-model map, the policy ceiling (16 384),
   the router formula; tests 1–4.
3. **The pins and the stamp**: update the OPS-5U budget class and the CLI/report
   pins; the new test file's remaining pins; the targeted and full gates; the
   suite-count stamp. Re-record the reasoning fixtures at the new effective
   budget in the live composition (deployment step, not a repo test).

## Appendix A — probe reproduction

Read-only, from the repository root, with the venv interpreter and
`PYTHONPATH='src;tests'` (Windows separator; Git Bash).

- **Prompt class vs output ask**: import `BudgetClass` from
  `hermes.research.prompt_assembly`, print
  `tuple(BudgetClass.STANDARD.__dataclass_fields__)` and the instance; import
  `load_profiles` and print `["planner"].model_policy.max_output_tokens`.
  Observed: prompt fields only; STANDARD `max_prompt_chars=3072`; planner ask
  3072.
- **Three declarations**: `ModelPlanePolicy().max_output_tokens` → 4096;
  `DEFAULT_MAX_OUTPUT_TOKENS` → 4096; `_PROVIDER_MAX_OUTPUT_TOKENS` →
  `{'tokenharbor': 32768, 'anyrouter': 32768}`; a `CloudModelSpec` for
  tokenharbor → `to_profile().max_output_tokens=32768`,
  `settings.max_output_tokens=None`.
- **Live wire**: run
  `pytest tests/test_ops5u_empty_completion.py::TestTheDeclaredBudgetNeverReachedTheWire -q`
  on the base; 5 passed. The live-CLI pin asserts the body's `max_tokens` is
  the planner's 3072.
- **H3**: the OPS-5U `_rig` + `_no_draft()` fixture, invoke the router, print
  `router.accounting()` rows. Observed: three `TRANSIENT EMPTY_COMPLETION`
  rows, `tokens_in 0 tokens_out 0`, `max_tokens 4096`, while the fixture's
  provider body carries `prompt_tokens=40`, `completion_tokens=4096`.
