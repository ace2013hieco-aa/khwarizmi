# OPS-5Z — a requirement is either declared or it is not

**Status:** design gate, phase 1. **No product code in this commit.**
**Charter:** OPS-5Z, issued 2026-10-28 from run 39.
**Base:** `slice/ops-5y-prior-art` at `e24cea0`.
**Branch:** `slice/ops-5z-required-statement`.
**Amended:** 2026-10-28, §9.8 — the gate branch moved from `db8c708` to
`3b6bc85` after this note's first commit. The note is written against the tree
at `e24cea0` and the gate branch at `3b6bc85`.

This note is written against the tree, not against the charter's summary. Every
claim carries an anchor. Where the charter and the tree disagree, the tree wins
and the disagreement is named (§9). The fourth remedy the charter asks me to
check is wrong in its premise and would not have worked; §9.3 says why, from the
tree.

---

## 0. What this note decides

| charter question | answer |
|---|---|
| **Q1** where does the requirement live? | **(a), refined**: a *stage-conditional, reply-conditional, override-conditional* contract marker. `requires_statement` is carried in the stage context payload; it is true only when the stage is minting **and** the caller supplied no non-empty `stage_content[kind]["statement"]`. The model contract gains `FieldSpec.required_when_proposing`; the router refuses the proposing reply with `contract_feedback=True` (so the model gets one informed retry) and `_validate_drafts` refuses the draft as defence in depth. The contract matrix's B seam is made stage-aware; its E seam already renders with the flag at the branch tip. The substrate's shape gate stays the last line. |
| **Q2** is one tick enough? | **Yes — and the tick budget is the wrong budget.** The minting profiles already declare `max_model_calls_per_tick: 2`, and `_model_phase` spends one of those on an informed contract re-prompt (OPS-15). No `max_ticks` moves. The cost is one extra model call *only when a contract refusal happens*, inside an already-declared bound. |
| **Q3** what does the model see? | The contract line changes from `(string, optional; optional: …)` to `(string, required when the reply proposes; … e.g. "Under condition Z, X is associated with Y.")`. One concrete example, in the contract, **not** in the objective: the objective's wording does not move and the governed document's version/digest does not change. The non-minting rendered line also loses the duplicated requirement word (gate 8); the structured contract mapping for a non-minting profile is unchanged. |
| **Q4** does the task-level retry carry the refusal? | **No.** A retry is a fresh dispatch from the same persisted spec: `_inputs_from_spec` rebuilds `MethodologyInputs` from the spec's `inputs` alone, and a fresh `TaskContext` carries no refusal. The controller stores the failure reason on the `TaskStatusChanged` event, never on the task row. The only feedback loop that carries a refusal is inside a tick. |
| fourth remedy (raise `max_ticks`) | **Rejected by measurement of the tree.** A second *tick* is not a second attempt at the same question: the prior tick's draft refusals are never rendered into a prompt (`_model_request` renders feedback, verdicts and a retry note — not `state.refusals`). Raising `max_ticks` would re-ask the identical question, which is precisely the LOOP-4 E5 defect OPS-15 already fixed at the call layer. |

The whole defect is a disagreement between two files: `run.py:361` offers
`statement` as optional, `workflows.py:763-786` consumes it as mandatory, and
the refusal is produced one layer below the layer that could tell the model.

---

## 1. The measurement, restated from the tree

Run 39 (`sars-covid-39`, `scripts/seed_methodology_run.py`, no prior art,
`apinex:free/deepseek-v4.1-flash`) made **11 model calls, 11 OK**, then:

```text
poison task quarantined: task 'meth-sars-covid-39' failed 3x
  (last: "MALFORMED_PAYLOAD: a HYPOTHESIS node is minted by the run:
   it needs a non-empty 'statement'")
```

The run report shows `QUESTION` and `HYPOTHESIS` both `SUCCEEDED` with two
admissions; the HYPOTHESIS stage run succeeded and admitted an `INSERT_TASK`,
but the node write refused. Depth **1 of 9**.

Three facts about that failure matter here, and each is a tree fact, not an
inference:

1. **The stage never learned it was incomplete.** The substrate's shape gate is
   at the write boundary (`write_node`, called at `methodology_driver.py:815`;
   the plane's own copy at `workflows.py:1048`), which is *below* the runtime's
   draft validation and *above* nothing the model can see.
2. **Requiring the field at the contract would have refused the draft, not the
   node.** That is the layer where a code can still reach the model (§3).
3. **The run's reported code does not distinguish the two layers.** Both the
   node-shape refusal and the model-output refusal are `MALFORMED_PAYLOAD`
   (the output-validation vocabulary is fixed: `MALFORMED_PAYLOAD`, `RATIONALE`,
   `ROLE`, `PROPOSAL`). The discriminating fact is the *detail* text and the
   event kind, which is why falsifier 5 in §6 is written against the reason, not
   the code.

What run 39 also established, and this note relies on:

- minting works: `MINTED_NODE_KINDS == {HYPOTHESIS, PREDICTION, CLAIM}`
  (`substrate.py:166`) and a fresh project reaches `QUESTION` with no prior art;
- the HYPOTHESIS objective already asks for the statement
  (`workflows.py:428-433`), so the model was told in prose and believed the
  validator instead;
- the provider is not the problem: 11/11 calls succeeded.

---

## 2. Q1 — where the requirement lives

### 2.1 What is wrong with (b), required everywhere

One flag flip would make every profile refuse drafts it accepts today. The
profiles that never run a minting stage are `planner` (`QUESTION`), `verifier`
(`EVIDENCE`) and `critic` (`CRITIQUE`) — `workflows.py:415-480` — and each would
refuse its only draft. The other three
(`researcher`, `experimenter`, `synthesizer`) each run **both** a minting and a
non-minting stage:

| profile | minting stage | non-minting stage |
|---|---|---|
| `researcher` | `HYPOTHESIS` | `OBSERVATION` |
| `experimenter` | `PREDICTION` | `EXPERIMENT` |
| `synthesizer` | `CLAIM` | `CONCLUSION` |

So the requirement cannot be a property of the profile. A profile-level flag
would either miss the minting stage (if false) or refuse the gather/prose stage
(if true). This is a correction to the charter's framing of "four profiles that
never mint": the tree has six runtime profiles, and only three never mint; the
flag must be **stage-conditional**, not profile-conditional.

### 2.2 What is wrong with (c), driver-only

The charter already suspects this: "the model still never learns". The tree is
worse than that, and the detail decides the design:

- At `max_ticks: 1` (the shipped document sets `max_ticks_per_stage: 1`,
  `workflows.py:474-479`), a draft whose statement is missing does **not** fail
  the run at the draft. `_validate_drafts` records a `RuntimeRefusal`, raises
  nothing, and returns an empty draft list. `_tick_termination` then finds
  `raised == 0` and `stop_when: proposals_raised` does not fire; the tick
  returns False; the inner loop ends; `_run_spec` sets
  `SUCCEEDED` / `TICK_LIMIT` (`run.py:677-679`). The stage reports success with
  zero proposals, and the node write is still the thing that refuses.
- A driver-side check that only re-runs the substrate's shape rule would
  therefore convert "stage succeeded, node refused" into "stage failed", i.e. an
  earlier failure with the same unusable feedback. It would not carry the
  runtime's draft refusal, and it would not reach the model.

A `_validate_drafts`-only check has the same shape: it is *defence in depth*,
never the primary seam. The primary seam must be the **model contract**, because
that is the only path that (i) refuses before a stage can report success and
(ii) has an informed retry behind it.

A driver check is not taken as a third layer. On the live path the router
refusal truncates the run before `write_node`, so the failure names the draft.
For a port that bypasses the router, `_validate_drafts` refuses the draft and
the substrate refuses the node write — the last line the charter keeps. A driver
check would add another shape rule and a new refusal layer for a path the live
composition does not take; it would not make the model learn anything the
router already tells it.

### 2.3 The decision: a conditional contract field

Three conditions, all required, all cheap to state:

```
requires_statement(stage, inputs) :=
      stage in MINTED_NODE_KINDS
  and not (inputs is not None
           and isinstance(inputs.stage_content.get(stage), Mapping)
           and non-empty string at inputs.stage_content[stage]["statement"])
```

- **Stage-conditional** — only `HYPOTHESIS`, `PREDICTION`, `CLAIM`.
- **Override-conditional** — when the caller supplied the statement (fixtures,
  the plane's own tests), the model is not its source, so it is not required
  from the model. This preserves `_minted_statement`'s first precedence
  (`workflows.py:781-786`) and keeps every fixture-driven run green without
  touching its prompt.
- **Reply-conditional** — the field is required only when the reply *proposes*.
  `required=True` would be wrong: `required` is per reply, and a minting stage's
  gather tick (a reply that calls a tool and raises no proposal, OPS-5H) must
  still validate. That is why the marker is `required_when_proposing`, not
  `required`.

The requirement is per **proposing draft**, not per first draft: a minting stage
may raise more than one proposal in principle, `_minted_statement` takes the
first admitted one, and the model cannot know which will be admitted. Requiring
each proposing draft is the only fail-closed reading.

With `inputs is None`, there is no override to honour, so the flag is true. A
projection that does not know its inputs must not promise the model that the
statement is optional.

The requirement is enforced at two runtime layers, with the substrate below
them:

1. **The router** (`_validate_output`): the proposing reply is refused with
   `contract_feedback=True`. This is the only layer that gives the model the
   refusal and a second call inside the same tick.
2. **`_validate_drafts`**: the draft is refused and recorded. This catches a
   `ModelPort` that bypasses the router's validator (a scripted port, a future
   provider, a test binding); it cannot retry.

The substrate's shape gate stays below both. For a port that bypasses the
router, `_validate_drafts` refuses the draft and the substrate refuses the node
write; the live path never reaches the substrate for this defect because the
router refusal truncates the run first. The substrate is unchanged and remains
the last line, as the charter requires.

### 2.4 Exact surfaces

**`src/hermes/agents/runtime/run.py`**

| line | change |
|---|---|
| `:343` | `output_contract_for(spec, *, capability_tool_note="", requires_statement=False)` — new keyword, default False, so every existing caller keeps today's contract by construction. |
| `:361` | `FieldSpec("statement", "string", required=False, required_when_proposing=requires_statement)` |
| `:376-379` | the field note is unchanged when false; when true it drops the leading `optional:` and gains one example: `"what the proposal asserts, never why it is raised (that is the rationale); at most {N} characters; e.g. \"Under condition Z, X is associated with Y.\""` |
| `:125`, `:135-136` | **the module docstring, not model-visible.** Its wire example says `"statement": "<optional: …>"` and its prose says "The key is optional everywhere". After this slice both are false for a minting stage; update the example and the prose to name the conditional requirement. No prompt, digest or test pin reads it. |
| `:1093` | `_validate_drafts` already receives `context`; read `context.payload.get("requires_statement") is True` once, and refuse a proposing draft whose statement is absent or blank — a new refusal site with code `MALFORMED_PAYLOAD` and a detail naming the minting stage. |
| `:1187-1206` | the existing present-but-blank and over-bound checks stay; the new check fills the absence hole and reuses the same blank rule. |
| `:1812` | `_model_request` passes `requires_statement=context.payload.get("requires_statement") is True` to `output_contract_for` at `:1853`. |

**`src/hermes/tools/models/router.py`**

| line | change |
|---|---|
| `:364-377` | `FieldSpec.required_when_proposing: bool = False`, appended after `allowed_values` so every positional construction is unchanged. |
| before `:2266` (`return parsed`) | after the declared-field loop (`:2235`) and after the kind allowlist block (`:2255-2265`), a conditional presence/non-empty check for each declared field with the marker, skipped when `action_only` (`:2221`). Placing it after the kind check preserves today's `ROLE` precedence for a reply that has neither a legal kind nor a statement. |
| new site | one `_Refusal(MALFORMED_PAYLOAD, …, retryable=True, contract_feedback=True)` — the informed re-prompt OPS-15 exists to carry. |
| `:2445` | `_contract_mapping` emits `"required_when_proposing": True` on a field **only when true**, so a non-minting mapping is byte-identical. |

**`src/hermes/tools/models/cloud.py`**

| line | change |
|---|---|
| `:294-316` | `_contract_lines` renders the requirement slot from the marker first: `required when the reply proposes` → `required` → `optional`. It also drops a leading `optional: ` from the field note when the slot already states the requirement, so the line says it once (gate 8). The structured mapping is unchanged; only the rendered line changes for a non-minting profile. |
| `:319` | `render_system` needs no structural change; the field line carries the new wording. |

**`src/hermes/methodology/workflows.py`**

| line | change |
|---|---|
| new helper | `_stage_requires_statement(stage, inputs) -> bool`, one definition, used by both drivers so the plane and the spine cannot drift. |
| `:987-999` | the plane driver adds `payload["requires_statement"] = True` only when the helper says so. |
| `:763-786` | `_minted_statement` is untouched. Precedence stays supplied → first admitted proposal's → `""`. |

**`src/hermes/research/task_handlers/methodology_driver.py`**

| line | change |
|---|---|
| `:243-298` | `project_stage` adds the flag to `payload` from the same helper (with `inputs=None` ⇒ true for a minting stage). |
| `:509-566` | `MethodologyExecution` gains `refusal_code: str = ""` and `refusal_detail: str = ""`; `to_mapping()` adds them **only when non-empty**; `digest()` is untouched. |
| `:774-780` | on the non-`SUCCEEDED` branch, fill both from `wired.result.refusals[-1]` when there is one. |

**`src/hermes/research/task_handlers/__init__.py`**

| line | change |
|---|---|
| `:390-414` | the truncated-chain `HandlerResult` carries `refusal_code=execution.refusal_code or "PROPOSAL"` and appends `execution.refusal_detail` (when non-empty) to the existing `PROPOSAL:` reason. The fallback preserves today's code for a `STAGE_LIMIT` truncation with no refusal; the reason's head and the substring assertions in `test_ops5m` are untouched. |
| `:370-389` | the zero-admission `HandlerResult` carries the same `execution.refusal_code or "PROPOSAL"` and appends the same detail to `_zero_admission_reason(execution)`. This branch fires *before* the truncated-chain branch when the failing stage had no prior admission; the order is pinned mechanically by `test_ops5m_truncated_chain.py:498-512`, so the termination check cannot be moved above the count gate — the detail must ride the zero branch. Without it, falsifier 5 would hold only for a chain that admitted something before the refused stage. The S6-B2 head and its substrings are untouched. |

**`scripts/contract_matrix.py`** (the gate; merge the branch `diag/contract-matrix`
at **`3b6bc85`**, not the charter's `db8c708` — §9.8)

The runnable closure is three files, taken at the branch tip:
`scripts/contract_matrix.py`, `scripts/structure_map.py` (the matrix imports it
for the fan-in weight) and `docs/CONTRACT-BASELINE.json`; the companion
`docs/CONTRACT-MATRIX-2026-10-28.md` is documentation and merges with them. The
branch tip also carries a depth ratchet, two ratchet JSONs, a structure note and
two test files; those are a separate instrument and stay on the branch (§8). The
matrix is a command gate, not a suite test, under this closure.

| line | change |
|---|---|
| `contracts()` | **output unchanged**: the profile-level report the JSON output carries. It may take the profile map `build()` already loaded; the report shape does not move. |
| `build()` / `declaration_vs_enforcement()` | load the profiles once in `build()` and pass them through; `declaration_vs_enforcement()` builds each **stage's** contract with `output_contract_for(spec, requires_statement="statement" in required)` and passes its flags to `_offered()`. The `required` truth still comes from the shape-gate ablation, never from the contract under test. This is what clears the three `stage:statement` keys; the branch tip's `_offered()` already accepts `required_when_proposing`. |
| `rendered_coverage()` | **no change.** The tip already renders each *profile* with `requires_statement=True` for the three minting profiles (probing the signature), keys `render-required:<profile>`, and checks the line for `required when the reply proposes`. The product's wording is what clears the three keys. The table is per profile by design: the system text names the agent, not the stage, and the six-profile table is what the charter's E section asks for. |
| `main()` | with `--baseline`, exit 1 only on a **new** key; without it, exit 1 on any B mismatch. A profile-level marker does **not** exit 1: both B and E are per profile, so the matrix cannot tell a profile-level flag from a stage-level one. The gather-tick test (§6 row 8) is the discriminator, exactly as the charter says. |

The matrix is a gate, not a report: it must exit 0 after the change, and a
missing marker must make it exit 1 again. A profile-level flag is not this
seam's to catch (it would clear both B and E); the gather-tick test in §6 row 8
is. The baseline arithmetic — six keys removed, 18 kept — is §6 row 11 and
§9.8.

**Why the context payload and not a new parameter.** `assemble_payload_envelopes`
(`assembly.py:244`) already renders every top-level payload key as one
`runtime.payload` envelope, so the flag is model-visible as untrusted data with
no new envelope, no new origin, no new event. It changes `TaskContext.digest()`
(`types.py:308-324`) for minting stages only, which is correct: the run's inputs
genuinely changed. No checkpoint, journal or trace byte moves for a non-minting
stage (or for a minting stage whose statement was supplied). One consequence is
honest to state: a checkpoint written by the old code for a minting stage would
refuse on resume after this change, because the digest it recorded did not
include the flag. That is the `STALE` rule doing its job — fail-closed, never a
silent reinterpretation — and it is the same class as any context change. This
slice does not claim a migration path for an old checkpoint; it claims the
refusal is explicit.

### 2.5 What each layer catches

- **Router** (`_validate_output`): the ordinary path. Refuses before a
  `ModelProposal` exists, with `contract_feedback=True`, so `_model_phase` may
  re-ask inside the same tick. This is the layer that produces the retry.
- **`_validate_drafts`**: a second, independent check for any `ModelPort` that
  bypasses the router's validator (scripted ports, a future provider, a test
  binding). It refuses the draft and records a `RuntimeRefusal` with the same
  code. It cannot retry; it exists so no port can mint an empty node through
  this runtime.
- **Substrate** (`_kind_refusal` / empty `statement`): unchanged, and still the
  last line of defence. A port that bypasses both runtime layers still cannot
  write an empty node; its failure names the substrate, which is the existing
  behavior and is not the live path. This design does not weaken it, does not
  move it and does not rely on it as the first check.

---

## 3. Q2 — is one tick enough?

**Claim: yes, and no tick budget moves.** The claim rests on a distinction the
charter's framing misses: `max_ticks` is not where a retry lives.

### 3.1 The two budgets

- `max_ticks` / `max_ticks_per_stage`: how many *ticks* a run takes. The shipped
  document sets 1 for every stage except `OBSERVATION` (3) —
  `workflows.py:474-479`.
- `max_model_calls_per_tick`: how many model **calls** one phase of one tick may
  spend. Declared per profile, and the minting profiles already declare 2:

```
researcher.yaml:48     max_model_calls_per_tick: 2
experimenter.yaml:40   max_model_calls_per_tick: 2
synthesizer.yaml:41    max_model_calls_per_tick: 2
```

### 3.2 The path, traced

1. `_model_phase` reads `call_budget = max(1, spec.termination.max_model_calls_per_tick)`
   (`run.py:916`) → 2 for a minting stage.
2. It builds `RetryBudget(max_retries=min(1, supervisor.retry.max_retries,
   call_budget - 1))` (`:922-926`). The live composition constructs
   `Supervisor()` with the default `RetryBudget(max_retries=2)`
   (`composition.py:1011`, `supervisor.py:121`), so the min is 1.
3. The router refuses the incomplete reply with `contract_feedback=True`;
   `_retryable_model_refusal` (`run.py:241-258`) returns True for that marker.
4. `Supervisor.attempt` calls `on_retry` and re-invokes; `_model_request` adds
   `contract_feedback_envelope(code, detail, attempt=1)`
   (`run.py:1836-1844`, `assembly.py:449-475`) — origin
   `runtime.contract_feedback`, carrying the refusal's code and detail.
5. The model sees the refusal and can supply the statement. The draft then
   validates and the stage records its node.

Note step 3 is code-based, not profile-guessed: the marker is the refusing
site's decision, so a request-side `MALFORMED_PAYLOAD` still never retries.

### 3.3 Why the tick budget is the wrong budget (the fourth remedy)

If we raised `max_ticks` instead, tick 2 would be built by the same
`_model_request`, whose prompt is: the assembler's envelopes, the retained tool
feedback, consumed review verdicts, and — only on an in-tick retry — the retry
note. **`state.refusals` is not part of the prompt.** The run's refusals reach
the report (`ProposalSet.refusals`) and the journal (`PROPOSAL_REFUSED`), never
the next tick. So tick 2 would ask the identical question with the identical
contract, and a deterministic model failure would repeat.

Worse, the ordinary model refusal never reaches tick 2 at all: `_model_phase`
terminates the run `FAILED` / `MODEL_REFUSED` on a terminal refusal
(`run.py:982-996`). The tick budget cannot buy a retry the refusal path does not
grant. That is the fourth remedy's error, stated from the tree.

### 3.4 Cost

- **One extra model call, only when the first reply is refused**, inside a bound
  the profile already declares. No new knob, no new limit, no provider-policy
  change.
- `provider_requests` already counts actuals (FIX-A1), so the cost is measured
  by the existing instrument rather than assumed.
- The depth instrument is unaffected: `stage_reached` still names the stage whose
  run stopped the chain (`methodology_driver.py:774-779`), and the new
  `refusal_detail` says why.

### 3.5 The boundary this does not cross

A minting stage whose model spends its only tick on a tool call and never
proposes still fails at the node write. The fix makes a **minting** reply
complete; it does not make a gathering model propose. That is honest and
unchanged: `OBSERVATION` is the stage with the gather budget (3 ticks), and
`_stage_requires_statement` is false there, so the gather path is untouched.

---

## 4. Q3 — what the model sees

### 4.1 The contract line, before and after

The statement field is declared identically for every profile today
(`run.py:361`, `:376-379`) and renders as:

```text
- statement (string, optional; optional: what the proposal asserts, never why
  it is raised (that is the rationale); at most 2000 characters)
```

For a minting stage it becomes:

```text
- statement (string, required when the reply proposes; what the proposal
  asserts, never why it is raised (that is the rationale); at most 2000
  characters; e.g. "Under condition Z, X is associated with Y.")
```

The non-minting line is the same field, so it renders as:

```text
- statement (string, optional; what the proposal asserts, never why it is
  raised (that is the rationale); at most 2000 characters)
```

The requirement word is stated once. Gate 8 is explicit that the duplicated
word is the defect in the prompt, and it names `_contract_lines` as the place to
fix it. This is a rendering fix, not a contract change: `output_contract_for`
still returns the same `FieldSpec` and the same `field_notes` for a non-minting
profile, and `_contract_mapping` is byte-identical. The digest this slice must
not move is the methodology document's (`SHIPPED_DIGEST` in
`test_ops5f_stage_budget.py`), which is independent of this line; no test pins
the rendered statement line. The new mapping pin in §6 is what proves the
non-minting contract did not move.

### 4.2 The example

A required field with no example is a field a weak model skips. The example is
one clause in the *contract*, because the contract is what the model treats as
the validator — run 39 proved the model ignores the objective's prose when the
schema says "optional". It is guidance only: the validator checks presence and
non-emptiness, never the example's shape, and no new prose repeats the
rationale rule.

### 4.3 Why the objective does not move

The HYPOTHESIS/PREDICTION/CLAIM objectives already ask for the statement
(`workflows.py:428-433`, `:434-438`, `:461-466`). Changing their *wording* would
be a governed-document content change: `LITERATURE_REVIEW_DOCUMENT` is version
`"3"` (`workflows.py:409`) with digest
`5a78e7ab5d479cf1446d5c3762afeaa4e0c0438ea6712b95e837c4febbbc6ad3`, and every
methodology digest, test pin and journal reference to the document moves with
it. Q3's question is answered where it can be answered without that cost: the
contract carries the requirement and the example; the objective's meaning is
unchanged, as §4.6 of the charter requires.

---

## 5. Q4 — does the task-level retry carry the refusal?

**No.** Traced end to end:

1. A stage fails; the handler returns `failed_typed` with a reason.
2. `Controller._retry_or_fail` (`controller.py:5350-5400`) writes the reason on
   the `TaskStatusChanged` event (`transition_status(..., reason=reason,
   details=details)`), transitions `FAILED` then `RETRYING`. The reason is not
   written onto the task row as an input.
3. The next dispatch re-reads the persisted spec and builds `MethodologyInputs`
   from its `inputs` mapping alone — `_inputs_from_spec` (`__init__.py:533-547`)
   reads `question`, `external_refs`, `admission_refs`, `retracted_refs`,
   `stage_content`, `governance_context`. There is no refusal field to read.
4. Each stage's `TaskContext` is constructed fresh by `project_stage`
   (`methodology_driver.py:243-298`) from the document, the inputs and the run's
   attribution. Nothing from the previous dispatch is in scope.
5. `MethodologyExecution` is reconstructed from the new run's derived store and
   stage records; `refusal_code`/`refusal_detail` (§2.4) describe *this*
   dispatch's refusal and are never fed back as input.

Consequence: **the only feedback loop that carries a refusal is inside one
tick.** Review verdicts are the other cross-tick feedback path, and they carry a
reviewer's judgment, not the draft refusal. That is why Q2's answer is the
load-bearing one and why a task-level retry is not a substitute for it. It also
means a retried dispatch with the same spec and the same model behaviour can
fail identically until the retry budget is spent — which is what run 39's
"failed 3x" line records.

---

## 6. Falsifiers, mapped to tests

| # | falsifier (charter §5) | test |
|---|---|---|
| 1 | A minting stage's draft with no statement is refused **at the draft**, with a code, before any node is written. | `test_ops5z_required_statement.py::test_the_router_refuses_a_proposing_reply_without_a_statement` (assert `MALFORMED_PAYLOAD`, `contract_feedback=True`, zero drafts; on the router path no `write_node` is reached) and `::test_the_draft_layer_refuses_a_proposing_draft_without_a_statement` (a scripted port that bypasses the router: zero drafts and the draft refusal is recorded; the substrate refuses the node write, which is the last line). |
| 2 | A minting draft with a non-empty statement validates and records its node. | `::test_a_minting_stage_with_a_statement_records_its_node` — one run, one node, `statement` on the node, `content_origin == "MINTED"`. |
| 3 | A non-minting profile's draft with no statement validates exactly as today — byte-identical contract, and a pinned digest. | `::test_a_non_minting_contract_is_byte_identical` — pin the exact `_contract_mapping` JSON and its digest for all six profiles with `requires_statement=False`, the cleaned non-minting rendered line (one requirement word), plus `test_ops5y_prior_art.py:237` (unchanged: every default contract still reports `required is False`). |
| 4 | The rendered contract marks `statement` required for a minting stage and optional for a non-minting one. | `::test_the_rendered_line_states_the_condition` — `render_system` output contains `required when the reply proposes` / the example for minting, and `optional; what the proposal asserts…` (one requirement word, no `optional; optional:`) for `QUESTION`/`EVIDENCE`/`CRITIQUE`. |
| 5 | The run's failure names the draft refusal, not the node write. | `::test_the_dispatch_reports_the_draft_refusal` — on the router-terminal path the `HandlerResult.reason` contains the runtime's detail and `refusal_code == MALFORMED_PAYLOAD`, and does **not** contain `a HYPOTHESIS node is minted by the run`. Exercised on both handler branches: a chain with a prior admission (the truncated-chain result) and a chain whose first stage fails (the zero-admission result), so the detail is not silently dropped when `applied == 0`. A port that bypasses the router still ends at the substrate by design; that is not the live path and not this falsifier's subject. |
| 6 | The override condition: a supplied statement keeps the model contract optional and the fixture runs green. | `::test_a_supplied_statement_makes_the_field_optional` plus the existing `test_ops7`/`test_wiring_w3`/`test_wiring_w4`/`test_loop0`/`test_ops5y` runs, which pass `CHAIN_STATEMENTS`. |
| 7 | The informed retry is real: a refused minting reply is re-asked with the contract feedback and succeeds on the second call. | `::test_a_refused_minting_reply_is_informed_and_retried` — two-call scripted model, assert `runtime.contract_feedback` in the second prompt, `contract_feedback:` ref, one node written. |
| 8 | A gather tick in a minting stage is not refused. | `::test_a_tool_only_reply_needs_no_statement` — `requires_statement=True` with `tool_calls` and no proposal validates. |
| 9 | The structural marker decision is explicit. | `test_ops15_contract_retry.py`: `SITE_CASES` gains the conditional-field row; the AST count moves 9→10 raises, 8→9 `True`, 1→1 `False`. |
| 10 | The contract matrix sees the stage-conditioned requirement. | `python scripts/contract_matrix.py --baseline docs/CONTRACT-BASELINE.json` exits 0: B is nine stage rows, all `ok` — the three minting stages offer `statement` through the marker, the six non-minting stages are unchanged; E is six profile rows, the three minting profiles carrying `required when the reply proposes` and the other three `optional`; every `statement` line states the requirement once. The matrix **cannot** distinguish a profile-level marker (B and E are per profile); the gather-tick test in row 8 does. |
| 11 | The baseline is cleared of exactly this slice's findings, and of nothing else. | After `--update`: the six keys `HYPOTHESIS:statement`, `PREDICTION:statement`, `CLAIM:statement`, `render-required:researcher`, `render-required:experimenter`, `render-required:synthesizer` are absent; 18 keys remain (the six `objective:` gaps and twelve `payload:` gaps), and `--baseline` exits 0 with no `fixed` list. Emptying the file would make the other 18 new findings and turn the gate red. |

Test updates forced by the flag's presence in the payload:

- `tests/test_ops7_input_projection.py:152` — `_inputs()` carries no
  `stage_content`, so the three minting projections gain the key; the assertion
  becomes per-stage (minting ⇒ present and true; non-minting ⇒ absent).
- `tests/test_wiring_w3.py:312` — projects `HYPOTHESIS` with `inputs=None`, so
  the key is present and true.
- `tests/test_ops7_input_projection.py:242` and `tests/test_ops5f_stage_budget.py:617`
  project `QUESTION`; unaffected.
- Fixture runs (`test_ops5h`, `test_wiring_w3/w4`, `test_ops7::_run`, `test_loop0`,
  `test_ops5y`) pass `CHAIN_STATEMENTS`, so no flag is set: their runtime prompts
  (the `ModelRequest.prompt` envelopes) and context digests do not move. The
  rendered system line is the separate gate-8 cleanup, which no fixture digest
  pins.
- `tests/test_ops5m_truncated_chain.py` — the existing `OPS-5M`,
  `MODEL_REFUSED` and `n of 9` substrings stay; the appended detail follows
  them. The gate-source test still sees only reads of `execution`.
- `tests/test_ops15_contract_retry.py` — the new router site is the tenth
  `raise _Refusal`: 10 raises, 9 `contract_feedback=True`, 1 `False`.
- `scripts/contract_matrix.py` — only B is made stage-aware (§2.4); E already
  renders with the flag at the branch tip. The gate closure is
  `contract_matrix.py` + `structure_map.py` + `docs/CONTRACT-BASELINE.json` +
  the companion note, taken at `3b6bc85`; none is imported by `src`, so the
  census is unaffected. The baseline is updated to the 18 remaining keys by
  `--update` after the product change, never emptied.

---

## 7. What must not change

1. **No global `required=True`.** `required` stays False on the statement field
   for every profile; only the new marker moves, and only for a minting stage
   with no supplied override.
2. **Non-minting structured contracts byte-identical.** `output_contract_for`
   defaults the flag False; `_contract_mapping` emits the marker only when true;
   `FieldSpec` and `field_notes` are unchanged when false. The rendered line
   loses the duplicated requirement word (gate 8), which is a prompt-presentation
   change, not a contract change; no digest pins it. Pinned by falsifier 3.
3. **No new event kind, write path or transaction.** The census stays
   `124 / 28 (19/5/4) / 1 / 15 / 0`; `scripts/check_census.py` is a gate, not a
   formality. `MethodologyExecution` gains fields on a read surface only, and
   `digest()` is untouched.
4. **Substrate `MALFORMED_PAYLOAD` stays.** The node-level refusal remains the
   last line of defence; no fallback to the rationale (OPS-5Y §6.2, not
   reopened).
5. **`_minted_statement` precedence untouched.** Supplied → first admitted
   proposal's → `""`.
6. **Drain-only byte-identical. B4 24. LOOP baseline unchanged.** The
   conditional marker only appears on a minting-stage path with no override.
   The gate-8 cleanup changes only the rendered system line: drain-only composes
   no model plane, the LOOP baseline measures the runtime's `ModelRequest.prompt`
   envelopes, and B4 reads reference graphs — none of them renders that line.
7. **The objectives' meaning is unchanged**, and their bytes are unchanged too
   (§4.3).

---

## 8. Blast radius and gate cost

**Product files:** five (`run.py`, `router.py`, `cloud.py`, `workflows.py`,
`methodology_driver.py`) plus one handler file (`task_handlers/__init__.py`) for
the failure naming, plus the module docstring in `run.py` that says the key is
optional everywhere. **Gate files:** three runnable — `scripts/contract_matrix.py`,
`scripts/structure_map.py`, `docs/CONTRACT-BASELINE.json` — plus the companion
`docs/CONTRACT-MATRIX-2026-10-28.md`, all merged at the branch tip `3b6bc85`.
The branch tip's other six files (the depth ratchet, two ratchet JSONs, the
structure note and two test files, ~1,450 lines and 27 tests) are a separate
instrument and stay on the branch; the matrix is a command gate, not a suite
test, under this closure (§9.8). No persistence, gateway, controller, event or
schema file is touched: the census is expected to reproduce exactly.

**Tests:** one new file; one exhaustive-site table extended (`test_ops15`);
two payload-set assertions updated; `test_ops5m`'s reason assertions stay; the
matrix gate is run directly (it is not collected by the suite in this closure);
one default-contract assertion deliberately left
alone (`test_ops5y_prior_art.py:237`) as proof that the default is unchanged.

**Records:** `docs/SUITE-COUNT.md` is restamped by
`scripts/stamp_suite_count.py`, never hand-edited. The count will move by the
new file's tests; the exact number is measured in phase 2 and reported, not
predicted here.

---

## 9. What the tree contradicts, including the fourth remedy

### 9.1 The charter's retry anchor is the wrong function

The charter cites `assembly.py:422` — "Render a retryable refusal as data for
the next attempt (LOOP-4 E5)". In the tree, `:421` is `retry_envelope`, and it is
the **rationale** retry (`RETRY_ORIGIN`, selected for a non-`contract_feedback`
refusal at `run.py:1841-1844`). The path that carries a *contract-shape* refusal
is `contract_feedback_envelope` (`assembly.py:449-475`, OPS-15), origin
`runtime.contract_feedback`, selected at `run.py:1837-1841`. The charter's point
— "the feedback path exists" — stands; the function it names is the other one,
and the difference matters because only the OPS-15 path is retried for a
shape refusal.

### 9.2 The tree has six profiles, and three of them run both kinds of stage

§2.1. A profile-level flag would fail in both directions. The flag is
stage-conditional.

### 9.3 The fourth remedy is wrong

The charter's fourth remedy (implicit in Q2: raise the tick budget so a second
tick can retry) is rejected on tree evidence in §3.3: prior refusals are not
rendered into the next tick's prompt, and a terminal model refusal never reaches
a next tick at all. The budget that governs a retry is
`max_model_calls_per_tick`, already 2 on every minting profile. Raising
`max_ticks` would add a second *identical* request — the precise defect LOOP-4
E5 recorded and OPS-15 fixed inside the tick.

### 9.4 A `_validate_drafts`-only refusal does not fail the run

At `max_ticks=1`, a refused draft can end `SUCCEEDED` / `TICK_LIMIT` with zero
proposals (`run.py:677-679`), and the node write still refuses. This is why the
router check is the primary seam and the draft check is defence in depth; a port
that bypasses the router still ends at the substrate, which is the last line the
charter keeps. The charter's option (a) as originally worded
("`_validate_drafts` refuses a draft without it") is necessary but not
sufficient.

### 9.5 The failure code alone does not distinguish the layers

Both the draft refusal and the node refusal are `MALFORMED_PAYLOAD`. The
charter's falsifier "the run's failure names the draft refusal, not the node
write" is therefore met by the **detail text** (and the `MODEL_REFUSED`
termination), not by a new code. Inventing a code would add refusal vocabulary
the gateway does not validate, so this note does not.

### 9.6 Run 39's spec is current, and the journal confirms the defect

I read the live journal at `D:/New folder/hermes-live.db` read-only. The run-39
task `meth-sars-covid-39` (project `sars-covid-39`) has `spec.methodology`
version `"3"`, `max_ticks_per_stage: 1`, no `stage_content`, and the current
HYPOTHESIS/PREDICTION/CLAIM objectives — the PREDICTION objective says "as this
proposal's statement". Its three `TaskStatusChanged` failures carry
`MALFORMED_PAYLOAD: a HYPOTHESIS node is minted by the run: it needs a
non-empty 'statement'…` with `stage_reached: HYPOTHESIS`,
`stages_recorded: 1`, `stages_declared: 9`, and `refusal_code:
MALFORMED_PAYLOAD`. The model saw the current objective and the optional
contract, and the node write refused. There is no stale-objective caveat to a
reproduction.

### 9.7 What is *not* contradicted

The charter's central finding stands unmodified: the contract declares the field
optional and the consumer requires it; the refusal is one layer below the layer
that could reach the model; and fixing the flag without a feedback path would
only move the failure earlier. §2–§5 are built on that finding, not against it.

### 9.8 The gate branch moved after this note's first commit

The charter names `diag/contract-matrix` at `db8c708` and describes gate 7 as
if that commit had a baseline, a marker-aware B and a flag-rendering E. It does
not: `db8c708` predates `c085557` (the baseline), `b83b959` (the second audit's
fixes) and `3b6bc85` (the commit whose message is "gate 7 was unsatisfiable — B
read 'required', E rendered without the flag"). The branch tip is `3b6bc85`,
and the gate's baseline, marker acceptance and E probe exist only there. B still
needs the slice's stage-aware build to use the marker (§2.4); what the tip
supplies is the seam that can see it. Merging `db8c708` would land a gate that
stays red however correct the slice is — the exact failure the branch tip was
written to prevent.

At `3b6bc85` the tree also differs from the charter in three measured ways:

- **The baseline is 24 keys, not 3.** It contains the three statement keys, the
  three `render-required:<profile>` keys, six `objective:<stage>` keys and
  twelve `payload:<profile>:<kind>` keys. This slice removes the first six;
  `--update` records the remaining 18. The charter's "the baseline must empty
  itself" is true of the three statement findings it knew about, not of the 18
  other known gaps; emptying the file would make all 18 new findings and turn
  the gate red. §6 row 11 records the exact arithmetic.
- **A profile-level marker does not exit 1.** Both B and E are per profile; a
  profile-level flag would clear both seams. The charter says the matrix cannot
  tell the stages apart; it is right, and the earlier claim in this note that
  the matrix catches a profile-level flag is withdrawn. The gather-tick
  falsifier (§6 row 8) is the discriminator.
- **The merge is three runnable files plus a note, not one script.**
  `contract_matrix.py` imports `structure_map.py` for the fan-in weight and
  reads `docs/CONTRACT-BASELINE.json`; the companion note is documentation. The
  branch tip's depth ratchet and self-check tests are a separate instrument
  (~1,450 lines, 27 tests); merging them is optional and would put the matrix
  into the suite, but it would also enlarge this slice by a diagnostic branch
  it does not need. This note recommends the three-file closure and running the
  matrix as a command, which is what the charter's gate 7 specifies.

Two truth-to-fix details this slice must not leave behind: the module docstring's
example at `run.py:125` and its prose at `:135-136` say the key is optional
everywhere, which stops being true for a minting stage (§2.4); and a run whose
failing stage had no prior admission hits the S6-B2 zero-admission branch before
the truncated-chain branch, so the handler change must cover both (§2.4, §6
row 5).

---

## 10. Phase-2 gates (in the charter's order)

1. **Targeted:** `tests/test_ops5z_required_statement.py`,
   `test_methodology_plane`, `test_ops5y_prior_art`, `test_wiring_w3`,
   `test_wiring_w4`, `test_ops1_live_cli`, `test_loop_baseline`,
   `test_census_check`, plus the changed tables: `test_ops15_contract_retry`,
   `test_ops7_input_projection`, `test_ops5f_stage_budget`,
   `test_ops5m_truncated_chain`.
2. `scripts/run_tests.py` (full).
3. `scripts/stamp_suite_count.py`, then `--check` (5616 before this slice).
4. `scripts/check_census.py` — expected `124 / 28 (19/5/4) / 1 / 15 / 0`.
5. `uvx ruff check src tests scripts`; `uvx pyright src`; the tests project.
6. A live run after the change: `sars-covid-40`, fresh project, no prior art.
   Report depth and refusal. No scripted-model claim of success; run 39 is the
   baseline.
7. **`python scripts/contract_matrix.py --baseline docs/CONTRACT-BASELINE.json
   || exit 1`** — merge the gate closure at `diag/contract-matrix` **`3b6bc85`**
   (not `db8c708`: that commit has no baseline, no marker probe and no
   `render-required` keys — §9.8), then make B stage-aware (§2.4). Acceptance:
   B's nine stage rows all `ok`; E's three minting profile rows carry
   `required when the reply proposes`; every `statement` line states the
   requirement once. The baseline loses exactly the six keys in §6 row 11 and
   `--update` records 18. A profile-level flag is **not** caught by the matrix
   (both seams are per profile); it is caught by §6 row 8.
8. **The `_contract_lines` cleanup** — the rendered `statement` line states the
   requirement once; the structured `_contract_mapping` for a non-minting
   profile is byte-identical (pinned by falsifier 3).

A red gate stops the slice. The census delta (if any) is reported and the gate
stops rather than being waived.

---

## 11. The boundary, stated plainly

This fix makes the system **ask unambiguously for the field it will consume**
and **tell the model when it did not get it**. It does not make a weak model
answer well; it makes the failure legible at the layer that can still act on it,
and it gives the model one informed attempt inside the tick it already has. If
the model ignores both the contract line and the refusal envelope, the run still
fails — at the draft, with the refusal named, one layer earlier than run 39 and
with a report an operator can read. A port that bypasses the router still ends
at the substrate, which stays the last line. That is the claim; nothing here
promises completion on `apinex:free/deepseek-v4.1-flash`.

---

## Appendix — anchors read for this note

| anchor | what it establishes |
|---|---|
| `run.py:343-439` | `output_contract_for`; the statement field, note and `OutputContract` construction |
| `run.py:894-1000` | `_model_phase`; `call_budget`, retry budget, refusal recording, terminal state |
| `run.py:1093-1229` | `_validate_drafts`; the blank/over-bound statement rules and the draft tuple |
| `run.py:1812-1859` | `_model_request`; retry-prompt selection and the contract construction |
| `run.py:636-680` | the tick loop; `TICK_LIMIT` SUCCEEDED when a tick raises nothing |
| `run.py:241-258` | `_retryable_model_refusal`; the marker is the retrying site's decision |
| `supervisor.py:104-122`, `:175-219` | default `RetryBudget(max_retries=2)`; attempt loop and `on_retry` |
| `composition.py:1011` | the live supervisor is the default, so the in-tick retry is available |
| `router.py:364-416` | `FieldSpec` / `OutputContract` |
| `router.py:2173-2266` | `_validate_output`; `action_only` at `:2221`, field loop `:2235`, kind check `:2255` |
| `router.py:2445-2466` | `_contract_mapping` |
| `cloud.py:293-360` | `_contract_lines`, `render_system` |
| `assembly.py:244-258` | payload envelopes, one per top-level key |
| `assembly.py:449-475` | `contract_feedback_envelope` (OPS-15) |
| `assembly.py:421-447` | `retry_envelope` (LOOP-4 E5, the rationale path) |
| `workflows.py:401-480` | the shipped document, version `"3"`, stages, termination |
| `workflows.py:763-791` | `_minted_statement` precedence |
| `workflows.py:987-1005` | the plane driver payload and `runtime_run` call |
| `methodology_driver.py:243-302` | `project_stage` |
| `methodology_driver.py:509-566` | `MethodologyExecution`, `digest()`, `to_mapping()` |
| `methodology_driver.py:774-779`, `:809-820`, `:854-864` | the non-SUCCEEDED break; `write_node`; the single constructor |
| `task_handlers/__init__.py:390-414` | the truncated-chain `HandlerResult` |
| `task_handlers/__init__.py:370-389` | the zero-admission `HandlerResult`; S6-B2 fires before the truncated-chain branch |
| `task_handlers/__init__.py:533-547` | `_inputs_from_spec`; a retry starts from the spec alone |
| `controller.py:5350-5400` | `_retry_or_fail`; the reason goes on the event |
| `controller.py:157-158` | `refusal_code` is written into the event detail |
| `substrate.py:166` | `MINTED_NODE_KINDS` |
| `substrate.py:924-940` | the minted-kind shape gate: non-empty `statement`, `origin == "MINTED"` |
| `researcher.yaml:48`, `experimenter.yaml:40`, `synthesizer.yaml:41` | `max_model_calls_per_tick: 2` on every minting profile |
| `test_ops15_contract_retry.py:121-199` | `SITE_CASES`; 9 raises / 8 `True` / 1 `False` today |
| `test_ops5y_prior_art.py:237-245` | every default contract reports `statement.required is False` |
| `test_ops7_input_projection.py:58-62`, `:126`, `:152`, `:242` | `_inputs()` has no `stage_content`; `_run()` passes `CHAIN_STATEMENTS`; the two payload assertions |
| `test_wiring_w3.py:299-315` | the `HYPOTHESIS` projection with `inputs=None` |
| `tests/test_ops5f_stage_budget.py:617` | the `QUESTION` projection |
| `tests/test_ops5f_stage_budget.py:127` | `SHIPPED_DIGEST`; the methodology document's digest, not the rendered statement line |
| `tests/test_ops5m_truncated_chain.py:309-410`, `:779-798` | the `OPS-5M` / `MODEL_REFUSED` / `n of 9` reason substrings; the gate reads the execution it holds |
| `tests/test_ops5m_truncated_chain.py:475-512` | S6-B2 still fails a complete effectless run; the count gate precedes the termination gate mechanically |
| `swap_test.py:92-99` | `CHAIN_STATEMENTS` (the override path) |
| `scripts/contract_matrix.py` at `3b6bc85` | B's three mismatches today, read per profile; E's `optional; optional:` line rendered with the flag for the three minting profiles; `--baseline` exits 1 only on a new key |
| `docs/CONTRACT-BASELINE.json` at `3b6bc85` | the 24 accepted keys; the six this slice must remove; the 18 that must remain |
| `tests/test_pipeline_invariants.py:222-241` (branch `diag/contract-matrix`) | the premise test: the minting and non-minting stages share profiles |
| `run.py:125`, `:135-136` | the wire-shape docstring: `"statement": "<optional: …>"` and "The key is optional everywhere" |
| `D:/New folder/hermes-live.db` (read-only) | run-39 spec: version `"3"`, `max_ticks_per_stage: 1`, no `stage_content`, current objectives; events: `stage_reached: HYPOTHESIS`, `stages_recorded: 1`, `stages_declared: 9`, `refusal_code: MALFORMED_PAYLOAD` |

---

# 10. Run 40 — the first live measurement

Recorded against `RUN-40-PROTOCOL.md`, before anyone reads the result favourably.

## Outcome: C — stopped before `EVIDENCE`, at the deepest point any run has reached

```text
stages_recorded: 5   stages_declared: 9   stage_reached: EVIDENCE
refusal_code: MALFORMED_PAYLOAD
```

Run 39, before this slice: **1** stage, `stage_reached: HYPOTHESIS`. Run 40: **5** — `QUESTION`,
`HYPOTHESIS`, `PREDICTION`, `EXPERIMENT`, `OBSERVATION`. Only two projects in the journal carry any recorded
depth at all, and 5 is the highest.

**The slice did what it was for.** `HYPOTHESIS` and `PREDICTION` were minted, and the substrate refuses a
minted node whose statement is empty (`MALFORMED_PAYLOAD`). Their presence is proof the model supplied
statements and the gate accepted them — which is the first time that has happened in a live run.

## Why it stopped

```text
MALFORMED_PAYLOAD: a EVIDENCE node cites an existing artifact: it needs a
non-empty 'external_ref' — an existing-kind node is never minted here, only cited
```

The model cited `evidence:obs-sars-covid-40-brazil-india-cases-sep1-2020` — an **observation handle** — where
the stage's objective asked for the admitted `evidence:<artifact_id>`. The refusal is correct and fail-closed;
the model did not follow the objective. That is outcome C: model compliance, not substrate.

The retry then died on infrastructure: five consecutive `429 rate_limit_error`, then
`every candidate model in the fallback chain failed`. That is a run about the provider, not the pipeline.

## The other refusals, in order

| stage | code | what |
|---|---|---|
| `HYPOTHESIS` | `ROLE` | model tried `openalex`, outside `['source_search', 'source_fetch']` — recovered on retry |
| `EXPERIMENT` | `PROPOSAL` | `REQUEST_ADDITIONAL_EXPERIMENT` is declared but its gateway validator is not wired in this phase |
| `OBSERVATION` | `MALFORMED_PAYLOAD` | `payload.evidence_artifact_ref` must be `evidence:<artifact_id>` |
| `EVIDENCE` | `PROPOSAL` | cited the observation handle rather than the admitted artifact |
| `QUESTION` | `MALFORMED_PAYLOAD` | unknown payload key `provenance_level` — the `INSERT_TASK` schema is closed |
| `QUESTION` | `PROPOSAL` | duplicate task admission |

## What this does not establish

**It does not establish that the chain can reach a claim.** It reached five of nine stages. The remaining
four — `EVIDENCE`, `CLAIM`, `CRITIQUE`, `CONCLUSION` — have still never run to completion in a live run.

**It does not establish that the middle is sound.** `EXPERIMENT` recorded a node while one of its proposals
was refused for a validator that is not wired. Whether that node carries real content or is the hollow middle
the invariants already mark is **not measured here** and is the next thing to look at.

**The depth is 5, not 9, and the difference is model behaviour.** No code change would have carried this run
further; a model that cited the admitted artifact would have.

## Next

The gap between 5 and 6 is one citation. Either the objective is not clear enough about the difference
between an observation handle and an admitted artifact — a prompt fix — or the model cannot hold it across
the stage boundary. Run 41 should answer that; the same question is fine, the project id must be fresh.

## 10.1 Run 41 — the gate bites

Same question, fresh project, same code. Result: **depth 2**, and the refusals are the slice's own message:

```text
HYPOTHESIS | MALFORMED_PAYLOAD | model refusal: model output proposed without a
             non-empty 'statement' for contract 'runtime_proposal_v1'
PREDICTION | MALFORMED_PAYLOAD | same
```

The router refused each proposing reply with `contract_feedback`, the model was re-asked inside the tick, it
still proposed without a statement, and the stage died. The substrate then refused the node — downstream, and
correctly, because no admitted proposal carried a statement to mint from.

**That is the falsifier pair, live.** Run 40's model complied and the chain reached depth 5; run 41's did not
and was refused at the prompt rather than allowed to mint an empty node. Before this slice both runs would
have looked identical: a node with no statement, refused by the substrate with a message that named the node
write instead of the missing field.

The cost of non-compliance is now a failed stage, not a silent empty node — which is what fail-closed means.

## 10.2 The next blocker is upstream of the citation

Run 40's `EVIDENCE` refusal was downstream of something I found afterwards and did not put in §10:

```text
artifacts for sars-covid-40: 0
```

`source_search` ran (one provider interaction, `openalex`, HTTP 200). `source_fetch` did not — so no artifact
was ever written, `_default_content` had no `evidence_ref` to put on the `EVIDENCE` node, and the model,
asked to cite something that did not exist, invented `evidence:obs-sars-covid-40-…`.

So the chain's real blocker is **`OBSERVATION` proposing before it fetches**. The stage declares
`max_ticks: 3` and `stop_when: proposals_raised`; a proposal on the first tick ends the stage, and the
objective's "Gather first, propose last" is advice, not a rule.

That is the hollow-middle defect with live evidence: a stage records a node while the artifact behind it does
not exist. The fix is not a prompt change — a stage whose proposal cites no fetched artifact should be
refused, which is the queued middle-holes slice. Until then, run 41's model would have failed at `EVIDENCE`
for the same reason even had it supplied its statements.

---

# 11. The middle-holes rule — written, measured, not landed

Attempted as the next slice; reverted. What follows is what it cost, because the cost is the finding.

## The rule

`_kind_refusal` gains one branch: an `OBSERVATION` node needs a non-empty `cited_refs`. An observation that
cites nothing is not a recorded stage — it is the hole run 40 fell into (zero artifacts, an observation
recorded, and the failure surfacing one stage later at `EVIDENCE` with a citation the run could not make).

It works. `tests/test_pipeline_invariants.py::test_an_empty_observation_is_refused` — one of the three
`xfail(strict=True)` markers — **passes** with the rule in place, and its marker comes off, exactly as the
marker's own reason instructs.

## What it costs, measured

With the rule in place the full suite reports **20 new failures** across six files:

```text
7  tests/test_eval_plane.py
5  tests/test_ops5l_evidence_ref_and_completion.py
4  tests/test_ops5f_stage_budget.py
2  tests/test_ops5d_proposal_content.py
1  tests/test_ops5y_prior_art.py
1  tests/test_wiring_w3.py
```

They are not hand-built nodes with a missing key. They are **plane runs whose scripted model never produces
an `EVIDENCE_TRANSITION`**: no admitted evidence proposal, so no `evidence_ref`, so the observation is
hollow — and under the old rule the chain completed over it. `test_ops5l` alone carries five model classes;
the migration is roughly twenty stubs, not one shared helper.

## Why it is not landed here

Twenty fixtures changed in one pass at the end of a long session is how a real regression gets papered over.
Each stub has to be reviewed for whether the *test's* subject survives the added proposal — a model that
suddenly grounds an observation may change what the test was measuring. That is a slice of its own.

The rule is correct, evidenced, and one `git revert` away from the analysis above. The migration list is the
six files above; `test_pipeline_invariants.py::test_an_empty_observation_is_refused` becomes a plain test and
`test_an_empty_experiment_is_refused` stays marked until `EXPERIMENT` gets a content rule too.

## A real defect found on the way

While migrating the swap fixture:

```text
experimenter tools = ('experiment_execute', 'artifact_store')
researcher   tools = ('source_search', 'source_fetch')
```

`engineering_investigation()` — the swap fixture's second methodology — declared its `OBSERVATION` stage on
the `experimenter` profile, which has **no source tools**. A stage that cannot read a source cannot observe
one; it recorded an empty node and the swap probe reported `both_complete() is True` over it. That is the
hollow middle in a fixture that existed to prove the runtime was sound.

The fixture is corrected in the un-landed diff (OBSERVATION on `researcher`), and it belongs in the
middle-holes slice rather than here — it is a product-shaped defect in a fixture, not a test tidy-up.

## 11.1 It landed

§11 recorded the rule as written, measured and reverted. It is now landed (`b493505`), and the migration went
the way §11 predicted: twenty tests, and every one of them needed a decision rather than a key.

The two halves:

- **Fixtures that hand-built a chain** now cite the artifact they admitted —
  `test_methodology_plane._build_chain`, one inline chain in the same file, and the eval harness's
  `_method_chain_to_observation`. The last one is product code: every hostile case in the eval matrix was
  built on an observation that cited nothing.
- **Runs that used to stop at `EVIDENCE` now stop at `OBSERVATION`** — nine assertions moved stage, four
  moved depth 5 → 4. Several tests were renamed, because a name that says `stops_at_evidence` when the run
  stops at `OBSERVATION` is a comment that lies.

## The two second-order effects §11 did not foresee

**`engineering_investigation()` could not observe.** Its `OBSERVATION` ran on `experimenter`, whose tools are
`experiment_execute` and `artifact_store` — no `source_search`, no `source_fetch`. A stage that cannot read a
source cannot observe one; it recorded an empty node and the swap probe reported `both_complete() is True`
over it. Its `OBSERVATION` now runs on `researcher`, and the control digest moved with it and is re-pinned.

**A truncated run reported `SUCCEEDED`.** `run_report._terminal` fired its no-evidence backstop only when an
`EVIDENCE` stage had run. A chain that stopped at `OBSERVATION` had every stage it ran succeed, so the report
said `SUCCEEDED` while the handler said `failed_typed` — the same run, two verdicts, and the report was the
one an operator would read. The rule now reads "stage runs and no admitted `EVIDENCE_TRANSITION`", which is
the same invariant one stage earlier.

That second one is the completion-gate defect again, found by a fixture migration rather than by an audit.
It is worth saying plainly: the rule was a twelve-line change, and the two defects worth having came from
following its consequences into code nobody had looked at.

## Verified

```text
5682 collected · 5 known-flaky · 0 new · ruff clean · pyright 0 (src and tests)
```

`test_an_empty_observation_is_refused` is a plain test now. `test_an_empty_experiment_is_refused` stayed
marked at the time: `EXPERIMENT` had no content rule yet, and the same migration had to happen for it. §13
records that migration; the marker is gone.

---

# 12. `EXPERIMENT` content — the decision

Taken 2026-10-29, before the rule is written, because the shape decides the rule.

## Decision

An `EXPERIMENT` node carries a **`test` string**: prose naming the discriminating test, written by the run.

## Why this and not the alternatives

**Not a minted kind.** Making `EXPERIMENT` carry `statement` + `origin: MINTED` would reuse every existing
rule and cost almost nothing mechanically. It is wrong on vocabulary: an experiment is a *design*, not an
assertion, and a chain that says "this experiment asserts X" has confused the thing you do with the thing you
conclude. `HYPOTHESIS`, `PREDICTION` and `CLAIM` are minted because each is a claim about the world;
`EXPERIMENT` is the step that would test one.

**Not "any content beyond `predecessors`".** Weakest of the three and it fails the OPS-5Z test: a rule the
model is never told is not a requirement, it is a trap. It also cannot be rendered into the prompt, so the
model would still not know what to write.

**`test` matches the stage's own objective**, which already reads: *"Describe the test that would
discriminate between the hypothesis and the observation that would refute it."* The contract should say what
the objective already asks for, in the same place the `statement` requirement is stated.

## What it implies

- a content key `test` on `EXPERIMENT`, required non-empty in `_kind_refusal`;
- a `_default_content` branch for `EXPERIMENT` reading it from the admitted proposal — today there is no
  branch at all, which is why the node is empty by construction;
- the contract note, so the model is told the field is required when it proposes (the OPS-5Z marker, not a
  new mechanism);
- the same fixture migration the `OBSERVATION` slice needed — `EXPERIMENT` appears in every chain fixture in
  the suite, and §11.1 records what that cost and what it found.

## What it does not decide

Whether the gateway's `REQUEST_ADDITIONAL_EXPERIMENT` validator, still unwired in this phase, is the same
`test` by another name. That validator should be read before the key is named, because two names for one
field is how a contract drifts.

**Superseded (OPS-5Z Group E).** The intent is wired as a *conflict verification round*, not as an
experiment declaration: its payload carries the two claims and the `contradiction_scan` conflict, and the
`test` key question above is answered by "a different thing". See `docs/OPS-5Z-TRIAGE.md` §E1.

---

# 12. OPS-5Z2 — the refusal the model never saw

## 12.1 The measurement this answers

Run 40 reached five of nine stages and stopped at `EVIDENCE` because the model cited
`evidence:obs-sars-covid-40-…` — a ref it invented — where the admitted artifact was required. Its
`OBSERVATION` stage had `max_ticks: 3` and the model used more than one tick. The earlier tick's refusal
reached `state.refusals`, the run report and the `PROPOSAL_REFUSED` journal event, and never the model:
`_model_request` renders the assembler's envelopes, retained tool feedback, review verdicts and — only on an
in-tick retry — the refusal that ended the previous attempt. `state.refusals` was not part of a prompt.

## 12.2 Where the feedback is attached

`_model_request` — the tick's prompt composer — fed by `_RunState.draft_feedback`, a queue the draft sites
fill and the next `_model_phase` consumes once. Not the router: `_validate_output` decides a whole reply's
shape *before* a draft exists, so it cannot see a refused draft at all; its `contract_feedback` retry is the
same-tick repair, and by the time `_validate_drafts` has refused a draft that slot is spent. A refused draft
is a fact about a *tick*, so the tick boundary is the only place it can be carried.

The queue is part of the checkpoint (`Checkpoint.draft_feedback`), so a crash between the refused tick and
its consumer re-renders the refusal once on the resumed tick instead of forgetting it. `_model_phase`
snapshots and clears it before the call: a refusal recorded by this tick's own drafts belongs to the next
one, and the in-tick retry is the same tick's question, so it keeps the note rather than being re-asked
amnesiacally (the LOOP-4 E5 rule).

Each refusal is rendered by `draft_feedback_envelope` with OPS-15's origin (`runtime.contract_feedback`) and
OPS-15's bounding rule (canonical JSON, 4 KiB, `detail_omitted_bytes` instead of a torn body — now one
shared helper, so the two renderers cannot drift). The document names the refused `tick` and `kind` rather
than overloading OPS-15's `attempt`, which a draft refusal does not have.

## 12.3 Which refusals are re-prompted

The refusing site decides, exactly as OPS-15's `contract_feedback` marker does:

- **`_validate_drafts`** — every site is the model's to repair except the authority branch, which passes
  `model_actionable=False`: a profile partition is not changed by proposing again.
- **`_emit_drafts`** — the payload-over-the-cap `RATIONALE`.
- **`_emit_intent`** — a spine refusal whose *own* code is in `ACTIONABLE_SPINE_CODES`: the gateway's closed
  payload schema (`MALFORMED_PAYLOAD`), a citation that does not dereference (`EVIDENCE_REF`,
  `EVIDENCE_DOES_NOT_RESOLVE`), an unresolved provenance ref (`PROVENANCE`). The code is carried out of
  `_apply` as a value (a fourth return element), never parsed from `detail`'s prose.

Everything else the spine refuses — `ROLE`, `OPERATOR`, `PROPOSAL`, `STALE`, `LOCK`, `BUDGET`, `DEPENDENCY`,
`IDEMPOTENCY_CONFLICT`, `UNKNOWN_KIND`, `NOT_WIRED`, `PROJECT_NOT_FOUND`, `SCOPE_NOT_GOVERNED`,
`NOT_COMPILED`, `CLASSIFICATION_REF` — is decided above the model. Re-prompting one would spend a tick on a
question whose answer cannot change.

## 12.4 Falsifiers

| # | falsifier | test |
|---|---|---|
| 1 | a malformed payload's refusal reaches the next tick's prompt, origin-labelled and canonically escaped | `test_ops5z2_draft_feedback.py::test_a_refused_draft_reaches_the_next_ticks_prompt`, `::test_the_envelope_escapes_a_detail_that_quotes_the_model` |
| 2 | a citation that names nothing admitted carries the refused ref | `::test_a_citation_that_names_nothing_admitted_carries_its_ref` (`evidence:obs-sars-covid-40-…` in the next prompt); `::test_a_governance_refusal_from_the_spine_is_not_re_prompted` for the split |
| 3 | a clean tick's prompt is unchanged | `::test_a_clean_tick_carries_only_the_tick_marker`, plus `test_loop_baseline` (prompt bytes and trace digests) unchanged |
| 4 | once per refused draft, budget still enforced | `::test_the_note_appears_once_per_refusal_and_the_tick_budget_still_stops` (3 prompts, 1 note each, 3 calls, `TICK_LIMIT`); `::test_the_in_tick_retry_keeps_the_note_it_did_not_produce` (the note is scoped to the tick, not the call) |
| 5 | a gather tick is untouched | `::test_a_gather_tick_queues_nothing` |

Also pinned: the queue's checkpoint carriage (`::test_a_pending_refusal_is_checkpointed_until_it_is_consumed`),
the legacy-mapping default (`::test_the_marker_round_trips_and_a_legacy_mapping_defaults_to_false`), the
authority opt-out (`::test_a_draft_refusal_the_model_cannot_repair_is_not_queued`), the cap refusal
(`::test_a_payload_over_the_cap_is_queued_too`), the 4 KiB bound
(`::test_the_envelope_keeps_identity_and_drops_an_oversized_detail`) and that `refuse()` never auto-queues
(`::test_the_queue_holds_only_what_a_draft_site_queued`).

## 12.5 Gates

```text
5697 collected · 0 failing · baseline: no new failure (0 known) · contract matrix exit 0 (18 known)
ruff clean · pyright src 0 · pyright tests 0 errors (1 pre-existing warning)
```

`test_hygiene_structural.py::test_no_spine_code_token_in_src` caught the first name of the fourth `_apply`
return value (`spine_code`); it is `rejection_code`, and the rule is right — the plane names the spine's code
without adopting its vocabulary.

## 12.6 The live run — blocked before the first model call

```text
hermes.composition.CompositionError: environment variable APINEX_API_KEY is not set
```

`specs_from_tiers` refuses at composition, so no project was seeded, no journal row was written and no stage
ran. **The behavioural half is unproven on the tree**: whether `apinex:free/deepseek-v4.1-flash` reads the
envelope and repairs its citation is not something a scripted port can answer, and this environment has no
provider credential. The plumbing half — the queue, the envelope, the once-only consumption, the checkpoint
carriage and the unchanged clean prompt — is pinned above.

To measure it when a key is present: seed a fresh project with `scripts/seed_methodology_run.py --apply`,
run `python -m hermes.cli run <project> --ticks N` with a config declaring
`m = "apinex:free/deepseek-v4.1-flash"`, and read `stage_reached` / `refusal_code` against run 40's five of
nine.

## 12.7 What the fix does not reach

**Superseded.** This section used to record that a refused draft counted as raised, so `proposals_raised`
ended the stage on the refusal itself and the note was never read. That was the defect, not a limitation, and
`raised` now counts admitted and duplicate drafts only. The table below describes what the code does today;
`test_a_spine_refusal_does_not_end_a_proposals_raised_stage` pins it.

| refusal | continues the stage? | note read? |
|---|---|---|
| `_validate_drafts` — schema, statement, bounds; no draft emitted | yes | **yes**, next tick |
| spine — `EVIDENCE_REF`, gateway `MALFORMED_PAYLOAD`, … | **yes** — a refused draft raises nothing | **yes**, next tick |
| nothing proposed and no capability called, under `no_proposals` | no | — |

`no_proposals` needs the other half of the distinction: a draft the spine *refused* is not "nothing proposed".
Counting admissions alone made a refused objection indistinguishable from a clean adversarial pass — the
critic's own policy — so the review ended `SUCCEEDED` with zero admitted proposals. It now ends only when the
model proposed nothing *and* called nothing.

The limit that remains is the tick budget, not the accounting: `max_ticks_per_stage: 1` for every stage except
`OBSERVATION`, so a refusal at a one-tick stage still leaves no next tick for the note to reach. Run 40's
`EVIDENCE` refusal is that case — the note is queued and correct, and the stage has already spent its tick.

---

# 13. OPS-5ZM — the experiment rule lands

§12 decided the shape; this slice writes it. An `EXPERIMENT` node without a non-empty `test` is refused
`MALFORMED_PAYLOAD`, and the detail names `'test'`; a node that names its test records, and the text survives
on it. `NODE_CONTENT_KEYS` admits the key, so the shape gate sees it rather than treating it as an authored-id
attempt.

Three supporting pieces:

- **`_default_content`** gained the branch §12 said was missing by construction. A caller-supplied non-empty
  `test` wins; otherwise the admitted proposal's `statement` lands as `test`. The wire keeps one prose field;
  the node keeps its own name for it.
- **`_stage_requires_statement`** now reads `_STAGE_PROSE_KEY` (`statement` for HYPOTHESIS/PREDICTION/CLAIM,
  `test` for EXPERIMENT), so the runtime is told the prose is required in the experiment's stage too. The
  helper that places it, `_minted_statement`, is `_stage_prose`: it never minted for an experiment and the old
  name claimed otherwise.
- **the contract note** is stage-agnostic: "the substance this stage's objective asks for — a claim, or an
  experiment's discriminating test — never why it is raised (that is the rationale)". The objective already
  asks for the test in those words; the note says where that substance belongs without naming a payload key
  the proposal schema does not have.

Fixtures migrated: `eval/hostile.py`, `swap_test.CHAIN_STATEMENTS`, `test_methodology_plane`'s built and
inline chains (and the no-external-ref pin, which is about `external_ref`, not content),
`test_pipeline_invariants`. `test_an_empty_experiment_is_refused` is a plain test now, and its complement, a
well-formed experiment records its test, was added so the rule cannot pass by refusing everything.

`REQUEST_ADDITIONAL_EXPERIMENT` is still unwired: absent from `WIRED_INTENT_KINDS`, dispatch returns
`NOT_WIRED`, and it has no payload schema. There is nothing yet to reconcile the key with; §12's open question
is still open, and it belongs to the slice that wires the intent.

**Superseded (OPS-5Z Group E).** It is now in `WIRED_INTENT_KINDS` with a closed payload schema, wired as
the conflict verification round (`docs/OPS-5Z-TRIAGE.md` §E1); the section above records the state before
that slice.

## 13.1 Gates

```text
5702 collected · 0 failing · baseline: no new failure (0 known) · contract matrix exit 0 (18 known)
ruff clean · pyright src 0 · pyright tests 0 errors (1 pre-existing warning) · census PASS
```

---

# 13. The grounding gate

`src/hermes/research/grounding.py` decides whether a claim's figures are supported by the artifact it
cites. It is a **figure/subject binder**, and this section is precise about what that does and does not buy.

## What it decides

```
grounded   every figure in the claim was found, bound to the right subject
caveated   nothing checkable was asserted, or no bytes were available
refused    a figure was asserted and not found, or a numeral bound to no subject
```

`CaveatCode` is deliberately a different enum from `RefusalCode`: a caller branching on a truthy `code` would
read a caveat as a failure and invert the verdict.

## Binding, not containment

An artifact naming both countries contains both figures, so a swapped claim passes a containment test:

```
artifact     3,959,158 in Brazil and 3,769,523 in India
claim        3,769,523 in Brazil and 3,959,158 in India
containment  both present                              -> PASSES  (the bug)
binding      Brazil 3,769,523: none bound to Brazil    -> REFUSED
```

## The date check — what the incident actually needed

The model's figures were **real**: an 18 September 2020 snapshot asserted "as of 1 September". India overtook
Brazil on 7 September, so the ordering was correct for the date the model used and wrong only for the date
asked. Binding cannot see that — every figure is present and bound to the right country — so the gate was a
binder and the incident walked through it.

`dates_in` extracts `1 September 2020`, `September 1, 2020`, `1 Sept 2020`, `2020-09-01` and the year-less
`as of 1 September`. The date is bound **on both sides**: the date nearest the claim's figure must match the
date nearest that figure in the artifact. It runs inside the figure loop, after the figure has been matched.

```
artifact   Week ending 1 September 2020: Brazil 3,862,311 … Week ending 18 September: India 5,275,035
claim      "India 5,275,035 … as of 1 September 2020"
           → REFUSED  India 5,275,035 is dated 2020-09-18; the claim is dated 2020-09-01
claim      "… as of 1 September 2020 (published 18 September 2020)"
           → REFUSED  a second true date does not rescue the first
claim      "… as of 18 September 2020"
           → GROUNDED
```

Two earlier versions of this rule were wrong in the same way, and both were caught by audit rather than by
their own tests:

- it asked whether the claim's date appeared **anywhere** in the artifact — containment again, so a two-week
  table passed the incident;
- it accepted **any** of the claim's dates — so a parenthetical publication date rescued a claim that was
  wrong about the data date.

A claim with no date is unaffected. An artifact naming no date is `caveated` (`undated_source`), not refused.

## What it still does not catch

A correct figure with a wrong conclusion; a wrong source; a table read correctly and summarised badly. And the
date binding is by character distance: in a multi-row table the nearest date to a row's last cell can be the
*next* row's date, and a "May 5" in prose is read as 5 May. Both produce false refusals, not false passes.

## The escape hatch this class of gate always has

A discarded numeral is indistinguishable from an absent one, so **every tokeniser bug becomes a caveat instead
of a refusal**. Three were found by audit and fixed:

- `"Brazil 9,999,999 may be an undercount."` — the lowercase modal `may` matched the month and dropped the
  figure, so a wrong number was caveated as qualitative. Months are now matched capitalised only.
- `subjects=("Brazil", "")` — an empty name matched at every offset and the scan never advanced: **the call
  never returned**. A hang is the absence of a verdict, not a wrong one.
- `"COVID-19 cases rose."` — the `19` was read as an assertion, refusing correct prose. Numerals inside a name
  are now skipped, as are ordinals (`2nd`).

Still open: European grouping (`3.959.158`) yields no numeral, and a percentage (`5.2%`) will not match a
source that states the raw count.

## Wiring: possible in the claim-ground plane, not done

An earlier revision of this section claimed the gate could not be wired because no artifact bytes reach the
claim site. **That was wrong.** `controller.py:5543` `_stored_text` already reads the cited `source_payload`
bytes and hands them to `validate_extraction` through `text_resolver` — the exact input `check_claim` takes.
`SupportState.PARTIAL` ("the source supports part of the claim") is likewise an existing, content-addressed
caveat channel, so the three-state verdict has a home.

So the gate is wireable in the extraction plane today. It is not wired because the incident happened in the
**methodology** chain, whose `CLAIM` node has no `source_ref` and never calls that validator — two claim models
that do not meet. Wiring it into the extraction plane would improve a path the incident did not take.

## `subjects` is a parameter, and that is a hole

`check_claim(statement, bytes, subjects=...)` trusts the caller for the entity names. A caller can pass `()`
and get `UNATTRIBUTED_NUMERAL`, or pass the wrong names and get a confident `grounded`. Deriving them from the
claim means entity recognition, which means a model — the one thing this module forbids. The honest options are
to constrain the caller (candidates = supplied names ∪ capitalised tokens in the claim, refusing a figure bound
to an unlisted candidate) or to accept the parameter and document the trust boundary. Neither is implemented.
