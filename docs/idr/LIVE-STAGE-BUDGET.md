# OPS-5F — a stage that gathers evidence needs more than one tick

| Item | Value |
| --- | --- |
| Task | OPS-5F: give a stage enough ticks to gather evidence and cite it, and tell it what the ticks are for |
| Base | `main` at `d908318` (OPS-5D merged + run-14 addendum) |
| Branch | `slice/ops-5f-stage-budget` |
| Phase | **1 — design gate** (2026-10-25) and **2 — implementation** (2026-10-26) |
| Status | **IMPLEMENTED** — B (per-stage bound), OBSERVATION 3, every other stage 1, with `StageSpec.objective` folded into the same revision |
| Run 14 | `M2(calls=0)`, 0 artifacts; QUESTION → … → OBSERVATION → EVIDENCE → stop; `MALFORMED_PAYLOAD: payload.evidence_artifact_ref must be 'evidence:<artifact_id>'` |

## 0. Verdict summary

1. **B — a per-stage bound — chosen, and the stage also declares its job.**
   `StageSpec` gains an optional `max_ticks` and an optional `objective`, in
   **one** schema revision: a missing `max_ticks` inherits the methodology's
   `max_ticks_per_stage` (today 1); a missing `objective` renders nothing. The
   shipped `OBSERVATION` stage gets **3** ticks (search, fetch, cite) and every
   stage gets an objective. Every other stage stays at **1** tick.
2. **Why 3 for OBSERVATION.** Tick 1 can only search (the actionable handle
   arrives in that tick's feedback); tick 2 can fetch the handle's row (the
   artifact exists after the tool phase); tick 3 can propose the
   `EVIDENCE_TRANSITION` naming the artifact. A known URL shortens this to 2;
   the search path needs 3. The `EVIDENCE` stage (verifier) has **no tool
   calls** and cites the run-level ref admitted in `OBSERVATION`; 1 is enough.
3. **Cost.** The shipped document's worst-case **model-call ceiling** moves
   from **27 to 31 per run** (+4); the nominal one-call-per-tick case moves
   from 16 to 18 (+2). A global budget of 2 costs **46** (worst) / 25
   (nominal); a global 3 costs **65** / 34. Model calls are not charged to
   `per_run_tokens` (OPS-16 unlanded); this is a call count, not a token or
   dollar bound.
4. **The within-tick order is not the thing to reverse.** The model authors
   its proposal before the tick's tools run; even tools-first, the proposal
   cannot name the artifact. The second model call is the only way. Reversing
   the order would break the E4 admission ordering and would not create the
   citation.
5. **The budget is necessary, not sufficient — and the corrected sentence is
   the one to carry.** Run 14 made **zero** tool calls. *The bound explains the
   discard, not the absence*: it explains why runs 12/13's searches could not
   be cited in the stage that needed them, not why run 14's model never
   called a tool. So the same revision also gives each stage its **objective**
   (`StageSpec.objective`): “a schema is not a job description” is fixed by a
   job description, not by a larger bound. The objective is guidance, never a
   control — the tick bound and `stop_when` remain the only stops.
6. **Compatibility.** An old document without the field parses to `None`, uses
   the methodology-wide default, and **keeps its digest**. The shipped
   `LITERATURE_REVIEW_DOCUMENT` gains `max_ticks: 3` on `OBSERVATION`, an
   objective on every stage, and moves its document version `1 → 2`; its
   digest moves from
   `36566121eb5c4260aea121678c4c5e2f99f37c3002bc0e67f6a6553185641a0f`
   to
   `ca7a95f44a5c569addf32f1cb3d212ae0478119838dce9e27ef7e57d48a6693b`.
   That is **one** governed-document event — one revision, one digest move —
   recorded here and in the merge log. The schema version stays `1` (both keys
   are optional and additive).
7. **Bounds.** The stage field is `1..5` (`MAX_STAGE_TICKS`); a stage with 3
   ticks and no useful proposal ends at the runtime's `TICK_LIMIT`, not an
   unbounded loop. The existing `max_stages`, the run deadline, the per-tick
   tool/model caps, `max_proposals`, and the review-round cap all remain.
8. **No new event kind, write path or transaction.** The only change is the
   stage's `RunLimits` and the document field. Census unchanged.

### 0.1 The one sentence to carry forward

**Give the evidence-gathering stage enough ticks to finish its own work —
OBSERVATION gets three (search, fetch, cite), every other stage stays at one —
and do not pretend the budget chooses the fetch; it only makes a fetch
citable.** The bound explains the *discard*, not the *absence*: the stage's
objective is what tells the model to gather, and it is guidance, not control.

## 1. The measurement, and the two causes

### 1.1 Run 14

With prior-art refs only, the agent had to earn its evidence. It made **zero**
tool calls, fetched nothing, and the chain stopped at `EVIDENCE` when its
malformed `EVIDENCE_TRANSITION` was refused. The addendum at `d908318` records
this as the first honest measurement: the previous CONCLUSION was partly bought
with a synthetic ref.

### 1.2 The structural cause — a fetch cannot be cited in its own stage

`workflows.py:196-197` sets the methodology-wide
`max_ticks_per_stage` to 1. The runtime's tick order (`run.py:729-765`) is
fixed: the model response carries the proposals and the tool calls; **the
proposals are admitted before the tool batch runs**. A fetch's artifact is
written during that tick's tool phase, *after* the proposals. The model cannot
name it until the next tick's feedback. With `max_ticks=1` there is no next
tick, so:

- the stage's proposals cannot cite an artifact fetched in that stage;
- the stage ends, and the fetched artifact is only reachable later through the
  project index (if it is written at all);
- the searches in runs 12 and 13 were journaled and then thrown away at the
  stage boundary — the artifact/handle had no tick in which to be used.

That is a real structural defect in the stage that needs evidence. It is not,
however, the whole of run 14.

### 1.3 The behavioural cause — nothing told the model to fetch

Run 14's `M2(calls=0)` says the model never *called* a tool. The one-tick bound
cannot explain an absent call; it explains why a call would have been useless.
The run-14 addendum already names the remaining wall: the model knows
`source_fetch` exists and knows the shape of an `EVIDENCE_TRANSITION`, but
nothing tells it that **this stage's job requires one**. A schema is not a job
description.

The budget is therefore **necessary for the citation, not sufficient for the
fetch**. **The bound explains the discard, not the absence.** So the phase-2
revision does both halves: it gives the stage its three ticks *and* its
objective (see §12). The objective is methodology **data** — the stage's job in
plain words, rendered as untrusted prompt content — never authority and never a
control: a stage that proposes on its first tick still stops there.

## 2. A / B / C, costed

### 2.1 A — raise `max_ticks_per_stage` globally

One document value; every stage gets the same budget. Cost (the ceiling in §3):
global 2 = **46** model calls per run (25 nominal); global 3 = **65** (34
nominal). The structural stages (QUESTION, PREDICTION, CLAIM, CRITIQUE,
CONCLUSION) pay for ticks they do not need, and a single global number cannot
express “this stage's work is three calls long”. **Verdict: rejected**, with the
cost stated for the Director if B is judged disproportionate.

### 2.2 B — a per-stage bound (chosen)

`StageSpec` gains `max_ticks`; a stage declares only what its work needs. The
shipped document sets `OBSERVATION: 3`; every other stage remains at 1. Cost:
**31** model calls per run worst case (27 today), 18 nominal (16 today); +4
worst, +2 nominal. This is the cheapest shape that makes the evidence stage
work, and the bound is a property of the stage's work, not of the methodology.
**Verdict: recommended.**

### 2.3 C — restructure the document so an earlier stage fetches

The OPS-5D path already demonstrates the workaround: fetch in HYPOTHESIS, cite
in OBSERVATION through the OPS-18 project index. It works for a **known URL**
and it keeps the stage budget at 1, but:

- the actionable **search handle** from a prior stage's feedback is not carried
  into the next stage's prompt (the handle is transient per composed run; the
  project index lists artifacts, not handles), so the general search → fetch →
  cite path is still unavailable in one stage;
- it makes HYPOTHESIS carry an observation artifact before the experiment and
  leaves the OBSERVATION stage unable to gather its own source;
- the model still has no stage instruction telling it to fetch in HYPOTHESIS.

**Verdict: rejected as the general fix.** It is a known-URL workaround, not the
stage's own budget.

### 2.4 Rejected alternatives

| Alternative | Why rejected |
| --- | --- |
| Reverse propose-then-tools inside the tick | The model authored the proposal before the tools ran; the artifact is still unknown. It would also break the E4 rule that a proposal is admitted before its sibling tool, and a tool failure would no longer leave the admitted draft untouched. |
| Add a second model call inside the tick | That is a second tick under another name; hiding it in the tick would make the budget unmeasurable. |
| A durable search-handle store | A new durable surface/write path; out of scope, and a stage budget is the smaller fix. |
| A stage-specific `stop_when` instead of ticks | The stop policy is a separate behavioural control; this gate changes the tick bound only. A stage that proposes early still stops early (see §5). |
| Global A | See §2.1; every stage pays for the OBSERVATION stage's three calls. |

## 3. The budget per stage, and the cost table

### 3.1 The budget

| Stage | Profile | Ticks | What the extra ticks do |
| --- | --- | --- | --- |
| `QUESTION` | planner | 1 | structural; the question is the operator's |
| `HYPOTHESIS` | researcher | 1 | prior-art citation; a fetch here is not the stage's cited evidence |
| `PREDICTION` | experimenter | 1 | structural |
| `EXPERIMENT` | experimenter | 1 | structural; the experiment capability is not supplied |
| `OBSERVATION` | researcher | **3** | tick 1 search (the handle arrives after the tools); tick 2 fetch the handle's row (the artifact exists after the tools); tick 3 propose `EVIDENCE_TRANSITION` citing it |
| `EVIDENCE` | verifier | 1 | the verifier has no tool calls; it cites the run-level ref admitted in OBSERVATION |
| `CLAIM` | synthesizer | 1 | synthesis; no source tools |
| `CRITIQUE` | critic | 1 | adversarial read; no tools |
| `CONCLUSION` | synthesizer | 1 | synthesis; no source tools |

A known-URL fetch needs 2 ticks (fetch, cite); the search path needs 3. The
budget is the search path, not the minimum. `HYPOTHESIS: 2` (prior-art
acquisition) is a possible extension; it adds 2 to the worst-case ceiling
(the researcher's 2 calls/tick) and 1 nominal, and it still does not tell the
model to fetch. It is not recommended in this slice.

The `OBSERVATION` stage's profile already declares `max_ticks: 4` and
`max_tool_calls: 4`; the document's 3 is below the profile default. The
`EVIDENCE` verifier declares `max_ticks: 3`; the document's 1 is the effective
context limit.

### 3.2 The cost model

```
stage_calls   = Σ over stages (stage_ticks × profile.max_model_calls_per_tick)
review_calls  = Σ over reviewed stages (review_ticks × reviewer.max_model_calls_per_tick)
total         = stage_calls + review_calls
```

`max_model_calls_per_tick` is the profile's ceiling (one normal call plus one
informed retry). The nominal column uses one call per tick. The review child
runs only when the stage raised proposals; it inherits the parent stage's
`RunLimits` (the runtime's existing `_delegate_one` behaviour). The critic
reviewer (`stop_when: no_proposals`, `max_proposals` inherited as 1) stops at
one tick whether it passes or objects; the verifier reviewer
(`stop_when: proposals_raised`) runs its inherited ticks when it has no
proposals and stops at one when it has one. All verifier-reviewed stages in the
shipped document are 1-tick stages, so the OBSERVATION budget does not increase
the verifier review cost. The reviewer's free text is not a token bound.

### 3.3 The table (shipped document, worst-case ceiling)

| Stage | Profile | Ticks today → B | Calls/tick | Stage calls today → B | Review | Review calls today → B | Total today → B |
| --- | --- | --- | --- | --- | --- | --- | --- |
| QUESTION | planner | 1 → 1 | 1 | 1 → 1 | verifier | 1 → 1 | 2 → 2 |
| HYPOTHESIS | researcher | 1 → 1 | 2 | 2 → 2 | critic | 2 → 2 | 4 → 4 |
| PREDICTION | experimenter | 1 → 1 | 2 | 2 → 2 | verifier | 1 → 1 | 3 → 3 |
| EXPERIMENT | experimenter | 1 → 1 | 2 | 2 → 2 | verifier | 1 → 1 | 3 → 3 |
| OBSERVATION | researcher | 1 → **3** | 2 | 2 → **6** | critic | 2 → 2 | 4 → **8** |
| EVIDENCE | verifier | 1 → 1 | 1 | 1 → 1 | — | 0 → 0 | 1 → 1 |
| CLAIM | synthesizer | 1 → 1 | 2 | 2 → 2 | critic | 2 → 2 | 4 → 4 |
| CRITIQUE | critic | 1 → 1 | 2 | 2 → 2 | — | 0 → 0 | 2 → 2 |
| CONCLUSION | synthesizer | 1 → 1 | 2 | 2 → 2 | critic | 2 → 2 | 4 → 4 |
| **Total** | | **9 → 11** | | **16 → 20** | | **11 → 11** | **27 → 31** |

Nominal (one model call per tick, one per review): **16 → 18**. Worst case:
**27 → 31** (+4). Global 2: **46** (25 nominal); global 3: **65** (34
nominal). The table is the ceiling; the live runs' actual calls are lower
because many stages raise nothing and are not reviewed.

Model calls are **not** charged to `per_run_tokens` (OPS-16, unlanded). No
token or dollar boundedness is claimed; the model ledger records usage as a
diagnostic.

### 3.4 The objective's byte delta

The objective adds **prompt bytes, not calls**. Each stage renders one
`runtime.payload` envelope, `{"objective": "…"}`; the envelope is the
declaration plus 16 bytes of JSON syntax (no escaping is needed in the shipped
text). Every value is far below the 4 KiB per-envelope cap, so an objective can
never tear an envelope, and the tick budget itself costs no payload bytes at
all — it arrives in the existing `runtime.tick` marker (`tick 1 of 3`).

| Stage | Objective bytes | Rendered envelope bytes |
| --- | --- | --- |
| `QUESTION` | 85 | 101 |
| `HYPOTHESIS` | 107 | 123 |
| `PREDICTION` | 78 | 94 |
| `EXPERIMENT` | 106 | 122 |
| `OBSERVATION` | **471** | **487** |
| `EVIDENCE` | 110 | 126 |
| `CLAIM` | 66 | 82 |
| `CRITIQUE` | 87 | 103 |
| `CONCLUSION` | 73 | 89 |
| **Total** | **1183** | **1327** |

The per-stage numbers are pinned in `tests/test_ops5f_stage_budget.py`, so the
table is a measurement rather than a recollection. The ceiling in §3.3 stays the
ceiling: the objective changes what the model is told, never how many calls it
may make.

## 4. The within-tick order, and why it is not reversed

`run.py:729-765` states the ordering contract: the model response carries both
the draft set and the tool calls; the proposals are admitted before the tool
batch; the tool phase reads no proposal/admission state. The model authored the
proposal **before** the tool result existed, so a proposal cannot name a
same-tick artifact. The next tick is the first moment the model can see the
fetch result.

Reversing the order would not help: the proposal is already authored, and the
runtime would have to call the model again after the tools to use the result —
a second tick. It would also change the E4 property (a failed sibling tool
keeps the proposals admitted before it) and the “a tool cannot consume a
same-tick admission” rule. The design keeps the order. The budget is the
second, third, … model call the stage is allowed; it is not a reordering.

## 5. What stops a stage from spinning

- **The stage tick bound** is hard: a stage with 3 ticks and no useful
  proposal runs its three model phases and then the runtime sets
  `TICK_LIMIT`; a tick always counts, even when it produced nothing. The
  methodology driver records the stage's `termination` (`TICK_LIMIT`) in its
  `StageOutcome`/`StageRecord`; the full chain then has no evidence ref and
  stops at EVIDENCE with the substrate's refusal. A stage that raises a
  useless proposal earlier is stopped by its profile's `stop_when`
  (`proposals_raised` for most), not by the budget.
- **Every other bound remains**: `max_stages` (9), the methodology deadline
  (180 s), the per-tick `max_model_calls_per_tick` (1–2) and
  `max_tool_calls`, `max_proposals` (1), the review round cap
  (`max_review_rounds` 1), and the supervisor's cancel/deadline.
- **The bound on the bound** is a new schema cap, `MAX_STAGE_TICKS = 5`
  (inclusive), and the methodology's own `max_ticks_per_stage` default. The
  field is validated as an integer in `1..5`; 0, negatives, booleans and
  values over 5 are refused at load with `MALFORMED_PAYLOAD` (the plane's
  existing shape code), never clamped silently.
- A stage with 3 ticks whose early ticks are tool-only is the intended path;
  the profile's `stop_when` does **not** give it a second chance after a
  proposal. The shipped `OBSERVATION` objective says “gather first, propose
  last” and names the order (search → fetch → propose), so the model is told
  the job in the same revision that gives it the ticks (§12).

## 6. Compatibility

### 6.1 The field

- `StageSpec` gains `max_ticks: int | None = None`.
- `STAGE_KEYS` gains `"max_ticks"` (and `"objective"`, §6.3); no other stage
  key changes.
- `from_mapping` validates `1..5`; `to_mapping` includes `"max_ticks"` **only
  when it is not `None`**, so a document that does not declare it serializes
  exactly as before and keeps its digest.
- A missing stage value means **inherit** `TerminationPolicy.max_ticks_per_stage`
  (today 1). The methodology-wide value remains valid and is still the default.
- The stage's `RunLimits` is the methodology's limits with `max_ticks`
  replaced by the stage value (or the default). The review child inherits the
  stage's limits (existing runtime behaviour).
- `METHODOLOGY_SCHEMA_VERSION` remains `"1"`: the field is optional and absence
  is defined; no existing document's meaning changes. A schema bump is not
  required for an additive optional key; if the format owner considers the
  change breaking for external readers, that is a separate decision (see §10).

### 6.2 The shipped document's digest moves — and says so

The shipped `LITERATURE_REVIEW_DOCUMENT` gains `max_ticks: 3` on
`OBSERVATION`, one `objective` per stage, and moves its **document version**
`1 → 2`. Both keys are in the same revision, so there is **one** digest move,
not two:

| Value | Before | After |
| --- | --- | --- |
| `literature_review().digest()` | `36566121eb5c4260aea121678c4c5e2f99f37c3002bc0e67f6a6553185641a0f` | `ca7a95f44a5c569addf32f1cb3d212ae0478119838dce9e27ef7e57d48a6693b` |
| `methodology_identity()` | `mth_36566121eb5c4260aea12167` | `mth_ca7a95f44a5c569addf32f1c` |
| `engineering_investigation().digest()` | `91e7427f74ecdd12db3d9a0a0dfa31f460b5f443086a4edd9b5b1d6aa61f9a2a` | unchanged (declares neither key, version 1) |

This is **one governed-document event**: the methodology's identity changes,
the swap probe's first digest changes, and the live run reports the new
document version. It is recorded here and in the merge log; no new event kind is
added (census unchanged). The phase-2 tests pin all three values: the old-form
document (neither key, version 1) still derives the old value; the shipped
document derives the new value; the swap fixture is the control that must not
move. The existing shipped-document version pin (`test_methodology_plane`
asserts `config.version == "1"`) is the governed-document pin and moves to
`"2"` as the recorded revision, not to make a red test green silently.

### 6.3 The `objective` field

- `StageSpec` gains `objective: str | None = None`; `STAGE_KEYS` gains
  `"objective"`; `to_mapping` includes it **only when it is not `None`**, so an
  old-form document serializes exactly as before and keeps its digest.
- A stage without an objective projects **no `objective` payload key** and its
  prompt carries no objective envelope: the stage is identity, predecessor and
  budget only — which is exactly what today's prompt looks like.
- The objective enters the prompt through the **existing** `runtime.payload`
  envelope port and origin — the same origin as `stage`, `methodology_id` and
  `predecessor_stage`. It is methodology data: untrusted, origin-labelled,
  never operator text (`runtime.task`) and never instruction authority.
- An objective is **not** chain content. It is stage configuration, so it is
  absent from the node content, absent from `predecessor_content`, and
  therefore never re-enters a later stage's prompt. The phase-2 test pins that
  the `EVIDENCE` prompt's `predecessor_content` has no `objective` key and does
  not contain the `OBSERVATION` objective's text at all.

## 7. What must not change

| Invariant | How the design upholds it |
| --- | --- |
| No new event kind/write path/transaction; census 124 / 28 (19/5/4) / 1 / 15 / 0 | the change is a stage `RunLimits` and a document field; no store, SQL or event |
| Substrate content rules / gateway checks | untouched; the OPS-5D evidence path is unchanged |
| Drain-only / B4 / governed docs | no CLI or corpus change; B4 24; the methodology module is not a governed corpus doc but its digest change is recorded |
| `proposable_kinds` and tool grants | unchanged; the stage budget changes no authority |
| LOOP baseline | unchanged; the baseline uses its own runtime ports and no methodology |
| Shipped digest not silently changed | §6.2 records the old/new digest and the version bump |

## 8. Falsifiers → phase-2 tests

| Falsifier | Test shape | Assertion |
| --- | --- | --- |
| A 2-tick stage fetches in tick 1 and cites in tick 2 | scripted stage (OBSERVATION profile) with `max_ticks: 2`; tick 1 calls `source_fetch`; tick 2 proposes `EVIDENCE_TRANSITION` citing the artifact; real gateway | the `EVIDENCE` node's ref is that artifact; `EVIDENCE_REF` admits; the fake transport is dialed once |
| A 1-tick stage behaves as today | the old document (no field) and the same scripted stage | one model call; the stage's context `max_ticks` is the methodology default 1; no second tick |
| A stage with no useful proposal for its whole budget terminates | a document ending at OBSERVATION with `max_ticks: 3`; a silent model | the stage's record `termination == TICK_LIMIT`; the run reports it; with the full chain, the EVIDENCE stop names the missing ref |
| The cost table is reproducible from the config | a pure test over `load_profiles()` and the parsed document | stage/review totals equal 27/31 and the nominal 16/18; the global 2/3 totals 46/65 |
| The shipped digest moves and old docs don't | the old-form document digest and the shipped document digest | the old value `3656…` and the new value `3112…`; the stage field `1..5` validation |
| Baseline / census | chartered gates | unchanged |

The phase-2 test file is `tests/test_ops5f_stage_budget.py` (new). Beyond the
falsifiers above it pins the fold: the objectives' bytes and rendering, the
old-form document rendering none, the objective's absence from
`predecessor_content` (and from the next stage's prompt entirely), and all
three digest values — old form, shipped document, unchanged control. The
existing
`test_methodology_plane`/`test_wiring_w3` fixtures that build full chains get
the new OBSERVATION budget from the shipped document; their scripted models
propose the evidence transition in the OBSERVATION run (tick 1), so the extra
budget is unused but harmless. The OPS-5D real-fetch test exercises the
fetch→cite path; the OPS-5F test exercises the same-stage two-tick version.

## 9. Phase-1 gates

Docs-only: the targeted methodology/wiring/OPS-5C/OPS-5D/loop-baseline/B4/
census files, the full suite under the heavy-gate lock, the suite-count stamp
(unchanged **5277**, no test added in phase 1), the census, ruff and pyright.
The raw results are in the phase-1 report; the design-note commit is the
deliverable.

## 10. What I could not decide from the tree

1. **Whether the budget alone will make a live model fetch.** It cannot, on the
   run-14 measurement: the model made zero tool calls. **Resolved by the
   Director's phase-2 ruling:** the stage's job is added in the same revision
   (§12), because running after the budget alone would likely reproduce run 14
   and cost a live run to learn nothing. This design still does not claim the
   objective closes the behavioural wall — it makes the instruction explicit
   and measurable, which is what a live run can then test.
2. **Whether HYPOTHESIS should also get 2 ticks.** It would let the stage
   search/fetch prior art, but its node is a prior-art citation, not the
   agent's evidence, and the OBSERVATION stage can gather the source itself.
   Cost: +2 worst / +1 nominal. The design leaves it at 1.
3. **Whether EVIDENCE should get 2 ticks.** The verifier has no tools and its
   `stop_when: proposals_raised` stops the stage after its first proposal; a
   second tick would not correct a malformed proposal without a `stop_when`
   change. The run-level ref from OBSERVATION writes the node even when the
   verifier's proposal is refused. The design leaves it at 1.
4. **The cap value.** `MAX_STAGE_TICKS = 5` is a judgement: enough for
   search–fetch–cite plus two corrections, below the largest profile default
   (6). A 3-cap would forbid future 4-tick stages; a 5-cap is the smallest
   round bound above the recommended 3.
5. **Review-child inheritance.** The stage budget also raises the review
   child's `max_ticks` (the runtime passes the parent's limits). For the critic
   reviewer this is inert (it stops at one); for a verifier reviewer it would
   inherit a larger tick budget on a stage that has one. If the Director wants
   the review child pinned to the methodology default, that is a runtime
   change outside this stage field.
6. **The schema version.** Keeping `"1"` relies on the optional/additive
   reading; bumping to `"2"` would require the parser to accept both and would
   be a larger compatibility statement. The design recommends `"1"` for the
   schema and `"2"` for the shipped **document** version. If the format owner
   treats an added stage key as a schema break, the parser and the version
   policy need a separate gate.

## 11. Claim boundary

This note claims the run-14 measurement as given, the one-tick/citation
mechanism in the runtime, the cost arithmetic above, the compatibility
semantics and the shipped digest move. It does **not** claim that a live model
will fetch under the new budget, that the budget is a token or dollar bound,
that the objective *makes* a model gather (it is guidance; the bound and
`stop_when` remain the controls), that the stage's evidence is scientifically
valid, or that the prior-art positions become agent-gathered. The structural
half and the instruction are this revision; whether a live model acts on them
is the next measurement's question.

## 12. The fold — the stage declares its job in the same revision

The Director's phase-2 ruling folded the next gate into this one. One schema
revision, one document version, one digest move:

- `StageSpec.objective` is optional stage data; the shipped document declares
  one for each of its nine stages.
- `OBSERVATION`'s objective is the one that matters. It states the causal
  chain and the order in plain words: call `source_search` (its reply carries
  a search handle), then `source_fetch` with that handle and a row index (its
  reply names the artifact it wrote), **only then** propose an
  `EVIDENCE_TRANSITION` whose `payload.evidence_artifact_ref` is
  `evidence:<artifact_id>` — and it says that a proposal ends the stage
  (`stop_when: proposals_raised`), so a proposal made first cites nothing.
- The objective is rendered as **untrusted, origin-labelled** data on the
  existing `runtime.payload` origin. No new origin, no second envelope port.
- An old document parses to `None`, renders no objective and keeps its digest.
- The objective is not chain content: it never enters `predecessor_content`
  and never re-enters a later prompt (§6.3).
- **The objective is guidance, not control.** The tick bound and the profile's
  `stop_when` are unchanged; a stage that proposes on tick 1 keeps stopping on
  tick 1. The falsifier is in the phase-2 suite.

**Known limit (recorded, not fixed):** the review child inherits the stage's
`RunLimits`, so a verifier reviewer on a stage with a larger budget would
inherit it. The critic is inert (it stops after one tick); pinning the review
child to the methodology default is a runtime change outside this field. It is
recorded here as a known limit for the next gate that touches review
inheritance.

License: Apache-2.0 (LICENSE).
