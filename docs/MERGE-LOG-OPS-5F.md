# MERGE-LOG-OPS-5F — the stage declares its budget and its job

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-5F phase 2: a per-stage tick budget, and the stage's objective in the same revision |
| Base | `main` at `73bb8d2` (the approved design gate) |
| Branch | `slice/ops-5f-stage-budget` |
| Commits | `afdafe0` (implementation + tests), this commit (this log, the note and the stamp) |
| Status | **PASS** — the approved falsifiers are green |

## The ruling, and the corrected sentence

**B — a per-stage bound — with `OBSERVATION: 3`.** Ticks: QUESTION, HYPOTHESIS,
PREDICTION, EXPERIMENT, EVIDENCE, CLAIM, CRITIQUE, CONCLUSION stay at **1**;
OBSERVATION gets **3** (search, fetch, cite). The worst-case model-call ceiling
moves from **27 to 31** per run (+4); the nominal one-call-per-tick case from
**16 to 18** (+2). `MAX_STAGE_TICKS = 5` bounds the field; 3 would have forbidden
a future 4-tick stage for no present gain.

**The fold.** `StageSpec.objective` joins the **same** schema revision: one
version bump `1 → 2`, one digest move, recorded once. The budget alone would
likely have reproduced run 14 (zero tool calls) and cost a live run to learn
nothing.

**The corrected sentence, as recorded** — in the note (§1.3, §0.1) and here:

> **The bound explains the discard, not the absence.** The one-tick bound
> explains why a fetch would have been *discarded* at the stage boundary (runs
> 12 and 13's searches are that evidence); it does not explain run 14's
> `M2(calls=0)`, where the model never called a tool at all. B fixes the
> structural half and claims only that. The stage's objective is the other half
> — guidance, not control.

Q5 (review-child inheritance) is recorded as a known limit and not fixed here;
the critic is inert, and pinning a verifier reviewer's inherited budget is a
runtime change outside this field. Q6 holds: schema `"1"`, document version
`"2"`.

## What landed

1. **The stage field** (`methodology/workflows.py`). `StageSpec` gains
   `max_ticks: int | None = None` and `objective: str | None = None`;
   `STAGE_KEYS` gains both. `to_mapping` omits a key that is `None`, so an
   old-form document serializes exactly as before **and keeps its digest**. A
   missing `max_ticks` inherits `TerminationPolicy.max_ticks_per_stage`; a
   missing `objective` renders nothing at all.
2. **The bound on the bound.** `MAX_STAGE_TICKS = 5`. `_stage_ticks` refuses
   anything that is not a real integer in `1..5` — `0`, negatives, `True`,
   `2.0`, `"3"` and over-cap values raise `MethodologyConfigError` (the
   driver surfaces `MALFORMED_PAYLOAD`), never a silent clamp. `_stage_objective`
   refuses a declared but blank objective.
3. **The limits.** `TerminationPolicy.limits(max_ticks=None)` replaces only
   `RunLimits.max_ticks`; `max_proposals`, `max_tool_calls` and the deadline are
   untouched, so a stage budget can widen nothing else. Both drivers —
   `workflows.run_methodology` and the live driver's `project_stage` — pass
   `stage.max_ticks`.
4. **The objective's rendering.** It rides the stage-identity payload as one
   `runtime.payload` envelope (`{task}:{STAGE}:objective`) — the existing
   envelope port and the existing origin, no new origin and no second seam. It
   is untrusted, origin-labelled methodology **data**, never operator text
   (`runtime.task`) and never instruction authority.
5. **It is not chain content.** The objective is stage configuration, so it is
   not node content, not in `predecessor_content`, and never re-enters a later
   stage's prompt.
6. **The shipped document.** `LITERATURE_REVIEW_DOCUMENT` gains
   `"max_ticks": 3` on `OBSERVATION`, one objective on every stage, and moves
   `version` `1 → 2`. `OBSERVATION`'s objective states the causal chain and the
   order: search (the reply carries a handle) → fetch with that handle and a row
   index (the reply names the artifact) → **only then** propose the
   `EVIDENCE_TRANSITION` naming `evidence:<artifact_id>`, because a proposal
   ends the stage (`stop_when: proposals_raised`).

## The rendered `OBSERVATION` stage prompt (verbatim)

The first tick's prompt, exactly as the model receives it, from the phase-2
probe (`.hermes/ops5f_prompt.py`) over the shipped document. Each envelope is
labelled with its origin and ref; every one is untrusted content.

```
--- origin=runtime.task ref=task-ops5f:OBSERVATION:task_input bytes=312
{"admission_refs":["claim:claim-p-ops5f/c1","hypothesis:program-p-ops5f/h1","prediction:program-p-ops5f/h1/p1"],"external_refs":{"CLAIM":"claim:claim-p-ops5f/c1","HYPOTHESIS":"hypothesis:program-p-ops5f/h1","PREDICTION":"prediction:program-p-ops5f/h1/p1"},"question":"does the fetched source support the claim?"}
--- origin=runtime.payload ref=task-ops5f:OBSERVATION:methodology_id bytes=38
{"methodology_id":"literature-review"}
--- origin=runtime.payload ref=task-ops5f:OBSERVATION:objective bytes=487
{"objective":"Gather first, propose last. Call source_search to find a source; its reply carries a search handle. Then call source_fetch with that handle and a row index; its reply names the artifact it wrote. Only once you hold a fetched artifact should you propose an EVIDENCE_TRANSITION whose payload.evidence_artifact_ref is that artifact as evidence:<artifact_id>. A proposal ends this stage (stop_when: proposals_raised), so a proposal made before you have fetched cites nothing."}
--- origin=runtime.payload ref=task-ops5f:OBSERVATION:predecessor bytes=56
{"predecessor":"mnode_67ceecac3623e591728c88585425c23a"}
--- origin=runtime.payload ref=task-ops5f:OBSERVATION:predecessor_content bytes=83
{"predecessor_content":{"predecessors":["mnode_b83303fc54d57cdcd7a3d21e7df8fc9a"]}}
--- origin=runtime.payload ref=task-ops5f:OBSERVATION:predecessor_stage bytes=34
{"predecessor_stage":"EXPERIMENT"}
--- origin=runtime.payload ref=task-ops5f:OBSERVATION:stage bytes=23
{"stage":"OBSERVATION"}
--- origin=runtime.tick ref=task-ops5f:OBSERVATION bytes=11
tick 1 of 3
```

The budget is the existing `runtime.tick` marker — `tick 1 of 3`, then `tick 2
of 3`, then `tick 3 of 3`; the objective costs no budget bytes and the budget
costs no payload bytes. The next two blocks quote only the envelope each later
tick adds (long refs elided with `…`); every other envelope is identical to
tick 1's. Tick 2's prompt adds the search observation, whose `detail` carries
the handle the model must fetch:

```
--- origin=runtime.observation ref=fa99bca8…ff8a bytes=473
{"artifacts":[],"capability_id":"source_search","detail":"search openalex: 2 source row(s) (COMPLETE); search_handle=search_9428242d3f7f08b684b383554ecc674df70d055876ab5e996b1e0da2dc94237e; rows=2; omitted=0",…,"tick":1}
```

Tick 3's prompt adds the fetched row and the artifact it wrote:

```
--- origin=runtime.observation ref=ea304dae…7581 bytes=669
{"artifacts":["evidence/455b2fcddb97b5e13dd180e722b33ae815c3eea831d9e4964a2bf6e92ff500fd","source_payload/455b2fcddb97b5e13dd180e722b33ae815c3eea831d9e4964a2bf6e92ff500fd"],"capability_id":"source_fetch","detail":"fetched openalex: 54 bytes; cite evidence/455b2fcd… or source_payload:455b2fcd…",…,"tick":2}
```

The `EVIDENCE` stage's `predecessor_content` is the recorded node content, not
the objective:

```
{"cited_refs":["evidence:455b2fcddb97b5e13dd180e722b33ae815c3eea831d9e4964a2bf6e92ff500fd"],"predecessors":["mnode_67ceecac3623e591728c88585425c23a"]}
```

## The three digest pins

One governed-document event, one revision: the budget and the objective moved
the digest together.

| Value | Before | After | Pin |
| --- | --- | --- | --- |
| `literature_review().digest()` | `36566121eb5c4260aea121678c4c5e2f99f37c3002bc0e67f6a6553185641a0f` | `ca7a95f44a5c569addf32f1cb3d212ae0478119838dce9e27ef7e57d48a6693b` | old form unchanged; shipped moved |
| `methodology_identity()` | `mth_36566121eb5c4260aea12167` | `mth_ca7a95f44a5c569addf32f1c` | derived from the digest |
| `engineering_investigation().digest()` | `91e7427f74ecdd12db3d9a0a0dfa31f460b5f443086a4edd9b5b1d6aa61f9a2a` | **unchanged** | the control |

`test_an_old_form_document_parses_to_no_stage_fields_and_keeps_its_digest` pins
the old form (`3656…`), `test_the_shipped_document_digest_moves_and_the_control_does_not`
pins the new value (`ca7a95f4…`) and the control. The shipped-document version
pin in `test_methodology_plane` moves `"1" → "2"` as the recorded revision, not
to make a red test green.

## The falsifiers → evidence

### 1. `OBSERVATION` searches, fetches, then cites — the fetch→cite falsifier

`tests/test_ops5f_stage_budget.py::test_observation_searches_fetches_then_cites_the_fetched_artifact`
runs the real live driver over the real gateway and the OPS-5C capability supply
(no network). Tick 1 calls `source_search`; tick 2 fetches row 0 of the handle
it received; tick 3 proposes the transition naming the artifact it fetched.

- three model calls in the stage — `tick 1 of 3`, `tick 2 of 3`, `tick 3 of 3`;
- one dial (`/works`) then one fetch dial (`/W910000001`) on the scripted edge;
- exactly one `source_payload` artifact row, and the model cited it:
  `evidence:<artifact_id>`;
- one `EvidenceTransitionProposed` event, admitted by the gateway's
  `EVIDENCE_REF` / `in_project` check;
- the `EVIDENCE` node's `external_ref` **is** that artifact; `OBSERVATION`
  cites it; `CLAIM` admits it; the chain reconstructs `complete() is True`;
- the stage records `termination: STOP_WHEN`.

### 2. A 1-tick stage behaves exactly as today

`test_a_one_tick_stage_behaves_exactly_as_today` — the old-form document (no
stage fields, version 1): every projected context has `max_ticks == 1`, and a
silent run makes exactly one model call per stage that runs
(QUESTION, HYPOTHESIS, PREDICTION, EXPERIMENT, OBSERVATION, EVIDENCE) before the
substrate's `EVIDENCE` refusal. Nothing about a 1-tick stage changed.

### 3. A stage that proposes on tick 1 still stops

`test_a_proposal_on_the_first_tick_still_stops_the_stage` — a real artifact row
is written first, so the tick-1 `EVIDENCE_TRANSITION` is **admitted**; the stage
still makes exactly one model call and records `STOP_WHEN`. The objective is
guidance; the bound and `stop_when` are the controls.

### 4. An old-form document renders no objective and keeps its digest

`test_a_stage_without_an_objective_renders_none` — the old-form document's run
carries no `objective` payload envelope in any request and no `:objective` ref;
`test_an_old_form_document_parses_to_no_stage_fields_and_keeps_its_digest` pins
the digest to `3656…` and asserts neither new key is serialized.
`test_the_objective_never_reenters_the_prompt_as_chain_content` pins the other
half: the `EVIDENCE` prompt's `predecessor_content` has no `objective` key and
the `OBSERVATION` objective's text appears in **no** envelope of that prompt.

### 5. A silent stage spends its budget and terminates

`test_a_silent_stage_spends_its_budget_and_terminates` — three model calls, no
proposal, no artifact, no transition; the run stops at `EVIDENCE` with the
substrate's `MALFORMED_PAYLOAD` rather than inventing a ref.

### 6. The cost table is reproducible

`test_the_cost_table_is_reproducible_from_the_config` derives it from
`load_profiles()` and the parsed document: **27** worst / **16** nominal today;
**31** / **18** with the stage budget; global 2 **46** / **25**; global 3
**65** / **34**.

### 7. Accounting-only pins

`test_the_stage_vocabulary_gained_exactly_the_two_keys` (the closed stage
vocabulary), `test_a_budget_outside_one_to_five_is_refused_never_clamped` and
`test_a_declared_objective_must_be_non_empty_text` (fail-closed validation),
`test_the_objective_byte_delta_per_stage_is_pinned` (§3.4's numbers),
`test_the_objective_rides_the_existing_payload_origin` (no new origin).

## The cost table, with the objective's byte delta

Worst-case model-call ceiling, shipped document (unchanged from the design
gate; the objective adds bytes, not calls):

| Stage | Ticks today → B | Calls/tick | Stage calls | Review calls | Total |
| --- | --- | --- | --- | --- | --- |
| QUESTION | 1 → 1 | 1 | 1 → 1 | 1 → 1 | 2 → 2 |
| HYPOTHESIS | 1 → 1 | 2 | 2 → 2 | 2 → 2 | 4 → 4 |
| PREDICTION | 1 → 1 | 2 | 2 → 2 | 1 → 1 | 3 → 3 |
| EXPERIMENT | 1 → 1 | 2 | 2 → 2 | 1 → 1 | 3 → 3 |
| OBSERVATION | 1 → **3** | 2 | 2 → **6** | 2 → 2 | 4 → **8** |
| EVIDENCE | 1 → 1 | 1 | 1 → 1 | 0 → 0 | 1 → 1 |
| CLAIM | 1 → 1 | 2 | 2 → 2 | 2 → 2 | 4 → 4 |
| CRITIQUE | 1 → 1 | 2 | 2 → 2 | 0 → 0 | 2 → 2 |
| CONCLUSION | 1 → 1 | 2 | 2 → 2 | 2 → 2 | 4 → 4 |
| **Total** | **9 → 11** | | **16 → 20** | **11 → 11** | **27 → 31** |

Nominal **16 → 18**. Model calls are not charged to `per_run_tokens` (OPS-16
unlanded); no token or dollar bound is claimed.

The objective's prompt-byte delta (one `runtime.payload` envelope per stage;
`+16` bytes of JSON syntax):

| Stage | Objective bytes | Envelope bytes |
| --- | --- | --- |
| QUESTION | 85 | 101 |
| HYPOTHESIS | 107 | 123 |
| PREDICTION | 78 | 94 |
| EXPERIMENT | 106 | 122 |
| **OBSERVATION** | **471** | **487** |
| EVIDENCE | 110 | 126 |
| CLAIM | 66 | 82 |
| CRITIQUE | 87 | 103 |
| CONCLUSION | 73 | 89 |
| **Total** | **1183** | **1327** |

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted (the new file, methodology plane, W3, OPS-5D, OPS-5C, loop baseline, B4 ref graphs, census) | **250 passed in 8.37s** |
| Full suite under the heavy-gate lock | **first run: 5305 passed, 3 skipped, 1 failed** — the eval-plane pinned-HEAD proof, because the migrated pinned test was uncommitted. Committed at `afdafe0`; rerun **5306 passed, 3 skipped in 642.77s (0:10:42)**, exit 0 (5309 collected) |
| `stamp_suite_count.py` → `--check` | **Stamped collected=5309** → **OK: collected=5309 matches the live collect** |
| `check_census.py` | `PASS - every certified figure is reproduced exactly.` (124 / 28 (19/5/4) / 1 / 15 / 0; BEGIN 29, COMMIT 28, ROLLBACK 67) |
| `uvx ruff check src tests scripts` | `All checks passed!` |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| pyright tests project | `0 errors, 1 warning, 0 informations` (the known `test_research_program.py:144`) |
| B4 ref graphs | 24 (targeted run above) |
| LOOP baseline | unchanged (targeted run above) |
| Drain-only | untouched by this revision |

The first full run's failure is the same working-tree artifact OPS-5D recorded:
`test_neutralizing_a_pinned_refusal_turns_the_matrix_red` ends with
"neutralize: restored content does not match HEAD" because
`tests/test_methodology_plane.py` was modified but uncommitted. The
modify/red/restore assertions passed; only the HEAD-cleanliness check failed.
After `afdafe0` the same proof passes and the full suite is green. No assertion
was weakened and no rule changed to make either run pass.

## Limits and deliberate refusals

- **The objective is guidance, not control.** No stage gained a stop, a check or
  an authority; the tick bound and `stop_when` are unchanged. A live model that
  ignores its objective still spends only its own budget.
- **Review-child inheritance (Q5, known limit).** A review child inherits the
  stage's `RunLimits`; the critic is inert (one tick), and a verifier reviewer
  on a multi-tick stage would inherit its tick budget. Pinning it is a runtime
  change outside this stage field, recorded and not fixed here.
- **`HYPOTHESIS` and `EVIDENCE` stay at 1 tick.** A fetch in `HYPOTHESIS` is not
  that stage's cited evidence, and the verifier's `proposals_raised` stop makes
  a second tick inert.
- **No new event kind, write path or transaction.** The change is a stage
  `RunLimits` and a document field; the census is unchanged.
- **No new origin, no new envelope port.** The objective renders on
  `runtime.payload`; the budget renders as the existing `runtime.tick` marker.
- **No claim that a live model fetches.** The revision makes the instruction
  explicit and the citation possible; whether a live model acts on them is the
  next measurement's question.

License: Apache-2.0 (LICENSE).

---

## Director addendum — run 15, and a new kind of failure

Landed at `711c203`, then run 15 with the same prior-art-only seed as run 14.

```
runs 5, admitted 8, M2(calls=0), artifacts: 0, interactions: 0
QUESTION → HYPOTHESIS → PREDICTION → EXPERIMENT → OBSERVATION → FAILED/MODEL_REFUSED
```

Still no tool call. But the refusals changed character:

```
ROLE: model proposed kind None                                          ×2
MALFORMED_PAYLOAD: model output carried unknown key(s)
                   ['arguments', 'capability_id'] for contract 'runtime_proposal_v1'
```

**The model tried to call a tool.** It emitted `capability_id` and `arguments` — the correct item keys —
**at the top level of its reply** instead of inside a `tool_calls` array. It knew *what* a call consists
of and not *where it goes*.

That is the first time in fifteen runs the model has attempted a tool call at all. Runs 12 and 13 searched
(4 and 2 calls); run 14 made none; run 15 attempted one and mis-shaped it. The objective did its job — the
model now tries to gather. What it lacks is the envelope shape.

### The contract gap, and it was predicted

`composition.py:355-382` renders the note as *"Item keys: arguments, capability_id, rationale."* — **key
names, never the nesting.** OPS-17's inventory listed exactly this as unstated: *"`tool_calls` must be a
list of mappings, each carrying only `capability_id`, `arguments`, `rationale`."*

So the next gate is small and already evidenced: **state the shape, not just the keys.**

### What this means for the budget

The `OBSERVATION: 3` budget never got used — the stage failed on tick 1 with a malformed reply, so the
three ticks were never reached. The budget is not disproven; it is untested. It becomes testable once a
well-shaped call exists.

Director gates at the merged tip: 119 targeted passed, stamp `5309`, census **PASS**, B4 24.
