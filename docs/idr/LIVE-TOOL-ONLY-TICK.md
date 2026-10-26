# OPS-5H — a tick may carry a tool call and no proposal

| Item | Value |
| --- | --- |
| Task | OPS-5H: let a tick gather — a reply that calls a tool and proposes nothing is valid |
| Base | `main` at `5f44a27` (the gate is landed there) |
| Branch | `slice/ops-5h-tool-only-tick` |
| Phase | **1 — design gate** (2026-10-26) and **2 — implementation** (2026-10-26) |
| Status | **IMPLEMENTED** — A landed (one predicate, one injected `action_field`, one rendered sentence), the multi-form instruction corrected to match enforcement, OPS-5I recorded |
| Run 16 | `OBSERVATION` tick 1: correct nesting, correct capability, correct arguments, **no `kind`** → `ROLE: model proposed kind None, outside the injected proposable allowlist`; the call was discarded with the proposal it did not have |

## 0. Verdict summary

1. **A — a reply carrying a non-empty tool-call array is valid with no proposal
   fields.** One predicate in the model plane, one injected contract field, one
   rendered sentence. A reply with neither a proposal nor a call is refused
   exactly as today (`ROLE`, same detail). **Recommended.**
2. **Where the gate is.** The runtime already tolerates a proposal-free reply:
   `_validate_drafts` (`run.py:1045`) reads "no proposal form present" as *no
   drafts* and records nothing (`run.py:1082-1083`), and `_tick` (`run.py:738`)
   runs the tool phase regardless of what was drafted. The **only** gate is the
   model plane's kind check (`router.py:2095-2104`), which refuses the reply
   before the tool phase can run. This slice relaxes that check and nothing else.
3. **B — a separate `NO_PROPOSAL` kind — rejected.** It adds a value to a
   governed list (`proposable_kinds`, invariant 5) to express a concept the
   absence of a field already expresses, and it would need a *second* place
   (the runtime's draft validator) taught to ignore the kind it just made legal.
4. **C — propose and call in the same tick — rejected.** It is the wall run 16
   hit: a proposal on tick 1 stops the stage (`stop_when: proposals_raised`,
   `run.py:832-834`) before the tool result exists, so the artifact fetched in
   that tick can never be cited in that stage. The objective says "gather first,
   propose last"; C cannot satisfy it.
5. **The predicate** (§3): the contract names an action array; that array is a
   **non-empty list**; and the reply raises **no proposal** — no non-empty
   string under the single-form field, no non-empty list under the multi-form
   field. Nothing else changes: `rationale` stays required, the closed key set,
   the declared types, the allowed values and the 4 KiB cap all still apply, and
   each call's item shape is still the runtime's check.
6. **What a call-only tick records** (§5): `TICK_STARTED`, `MODEL_REQUESTED`,
   `TOOL_REQUESTED`, `TOOL_OBSERVED`, `CHECKPOINT_WRITTEN`. **No
   `MODEL_REFUSED`**, no `PROPOSAL_DRAFTED`, no `PROPOSAL_REFUSED`. The run's
   `proposals` and `admissions` counts do not move; `tool_calls` rises by one per
   invoked call; `termination` is untouched (the run continues). It does not look
   like a failed tick because nothing that marks a failure is emitted.
7. **The stage continues, and the tick bound is the only thing stopping it**
   (§6): `proposals_raised` reads `raised == 0` as "not raised",
   `PROPOSAL_LIMIT` is a statement about admitted proposals and is not reached by
   0, and `max_ticks` still ends the stage. `max_ticks` is also the *cost* bound:
   this slice adds no call, so OPS-5F's ceiling (27 → 31 model calls per run)
   is unchanged — it makes the ticks already granted usable.
8. **Termination when a stage never proposes** (§7): exactly as today. The stage
   runs out of ticks, the runtime sets `TICK_LIMIT` with `SUCCEEDED`
   (`run.py:630-632`, `run.py:1816-1818`), the methodology driver records the
   stage and extends the chain (`methodology_driver.py:605-615`), and the chain
   stops at `EVIDENCE` on the missing ref. No new termination and no hang. A
   stage that never proposes is reviewed by nobody: `_maybe_review` returns
   `None` while `state.proposals` is empty (`run.py:1622-1623`).
9. **One sentence of contract** (§8), drift-guarded like the rest: rendered from
   the plane's own form names and the injected action-field name.
10. **One adjacent contradiction found, not silently fixed** (§11): the rendered
    note already says *"omit it in the multi-proposal form"* about `kind`, and
    the plane refuses exactly that reply (`ROLE`, measured below). It is the same
    class of defect as run 16. It is **not** part of A; it is offered as a
    one-clause optional fold, and it is the Director's call.
11. **Census unchanged** (124 / 28 (19/5/4) / 1 / 15 / 0): no new event kind, no
    write path, no transaction, no store. `proposable_kinds` untouched. LOOP
    baseline untouched by construction (a contract that names no action field
    keeps today's behaviour exactly). Drain-only byte-identical; B4 24;
    governed docs untouched.

### 0.1 The one sentence to carry forward

**A tick may gather without proposing: a reply that raises no proposal and calls
a tool is valid, the tool runs, no draft is produced, and the stage continues
until its declared tick bound — which is the only thing that stops it.** The
model plane is where the refusal lives; the runtime already reads a proposal-free
reply as no drafts, so this slice moves one predicate, not the tick order.

## 1. The evidence, and what the tree does today

### 1.1 Run 16, verbatim

```json
{
  "rationale": "Begin evidence acquisition by searching PubMed for peer-reviewed literature …",
  "tool_calls": [
    {"capability_id": "source_search",
     "arguments": {"provider": "pubmed", "topic": "SARS 2003 containment vers…"}}
  ]
}
```

```
ROLE: model proposed kind None, outside the injected proposable allowlist
```

Right nesting (OPS-5G), right capability, right arguments, no `kind`. The call
was discarded along with the proposal the reply did not have. The refusal is
retryable (`contract_feedback=True`, OPS-15), so the model was re-prompted with
the contract-shape feedback and reverted to the flat form — which OPS-5G's
unknown-key check refused in turn.

### 1.2 The two halves of the contradiction, located in the tree

| Half | Where | What it says |
| --- | --- | --- |
| The plane refuses a reply with no kind | `router.py:2095-2104` | `if contract.kind_field:` … `not in self._proposable_kinds` → `ROLE`, `model proposed kind None, outside the injected proposable allowlist`, `contract_feedback=True` |
| The runtime already tolerates one | `run.py:1082-1083` | the draft validator's *no proposal form present* branch returns `[], refusals` — no drafts, no refusal |
| The tool phase does not need a draft | `run.py:767-776` | `_tick` runs `_tool_phase` unconditionally; `raised = len(drafted)` is computed after it |
| A stage stops on a proposal, not on a call | `run.py:832-834` | `stop_when: proposals_raised` returns `STOP_WHEN` when `raised > 0` |

So the runtime's *outcome* — gather on this tick, continue, propose later — is
already fully supported. What is not supported is the *reply*: the plane refuses
it before the runtime sees it. That is the whole of the gap.

### 1.3 The measurement (this tree, today)

A probe over the **live** `researcher` contract (`output_contract_for(load_profiles()["researcher"])`,
`kind_field='kind'`, fields `kind, rationale, payload, proposals, tool_calls`,
`proposable_kinds = INSERT_TASK, EVIDENCE_TRANSITION, REQUEST_ADDITIONAL_EXPERIMENT`)
through the real `ModelRouter` with a scripted provider:

| Reply | Plane's answer today |
| --- | --- |
| `rationale` + `tool_calls:[{…}]`, no `kind` (**run 16**) | `ROLE` — `model proposed kind None, outside the injected proposable allowlist` |
| the same with `"kind": "GATHER"` | `ROLE` — `model proposed kind 'GATHER', …` |
| the same with `"kind": ""` | `ROLE` — `model proposed kind '', …` |
| the same with `"kind": null` | `MALFORMED_PAYLOAD` — `field 'kind' is not of declared type 'string'` |
| `rationale` + `"tool_calls": []` | `ROLE` — `model proposed kind None, …` |
| `rationale` + `payload`, no `kind` | `ROLE` — `model proposed kind None, …` |
| `rationale` only | `ROLE` — `model proposed kind None, …` |
| multi-proposal form, top-level `kind` omitted | `ROLE` — `model proposed kind None, …` |
| `rationale` + a legal `kind` + a call | **accepted** (structured carries the kind and the calls) |

Every path that reaches the kind check is a `ROLE` the model cannot escape by
any correct gathering reply. The last row is why the exemption must be narrow
(§3): a reply that *does* propose must still be checked.

### 1.4 Why OPS-5F's harness could not have caught this

`tests/test_ops5f_stage_budget.py`'s `SearchFetchCiteModel` returns
`ModelProposal(...)` **directly** (`_proposal`, line 158) — it is the runtime's
injected model port, so tick 1's call-only reply never met the plane. Its
`test_observation_searches_fetches_then_cites_the_fetched_artifact` is green
today *and* would be green with run 16's exact reply: the falsifier is scripted
below the gate that refuses. The phase-2 falsifiers for this slice must
therefore put the **plane** in the path (a real `ModelRouter` under the live
contract, as §10 specifies), or they prove nothing about this defect.

## 2. A / B / C

### 2.1 A — a proposal-free reply is valid when it calls a tool (recommended)

The plane's kind check is skipped when the reply is *proposal-free and calling*:

- **one contract field**: `OutputContract.action_field: str = ""`
  (`router.py:344-378`) — the array field in which a reply may ask for action
  without proposing. Injected by the
  runtime (`output_contract_for`, `run.py:323`) as `TOOL_CALLS_FIELD` when the
  profile declares the section, and `""` otherwise. The plane never learns the
  runtime's vocabulary; it learns the *name*, exactly as it already learns
  `single_form_field`, `multi_form_field` and `delegation_keys`.
- **one predicate** (§3), read once per reply;
- **one rendered sentence** (§8).

It is the smallest shape that matches what `stop_when: proposals_raised` already
means, and it needs no new kind, no new event and no new write path.

**What it costs:** one system-message sentence for the profiles whose contracts
declare `tool_calls` (`researcher`, `experimenter`, `critic` — 187 UTF-8 bytes
including its newline, computed from the sentence in §8). No model call, no
token bound and no tick bound moves. M1 counts the user prompt only, so M1 is
unchanged.

### 2.2 B — a separate "action-only" reply kind (e.g. `kind: "NO_PROPOSAL"`) — rejected

- `proposable_kinds` is a governed, per-profile allowlist checked in three
  places (the plane's injection, `spec.refuses_by_authority`, the contract's
  rendered list). Adding a pseudo-kind means a vocabulary change for a value
  that is never an intent, never admitted and never written — it exists only to
  be ignored by the runtime's draft validator. That is a second statement of
  "no proposal", in the one place where a wrong value is *refused*.
- It is strictly harder for the model: it must remember to emit a kind that
  means "no kind", after fifteen runs of being taught that every reply carries
  one. Run 16 shows the model already does the natural thing — it simply
  gathers.
- It would not even be free downstream: `_validate_drafts` would have to learn
  to skip the marked kind before `IntentKind(kind_name)` refuses it as not an
  `IntentKind` (`run.py:1104-1110`).

**Verdict: rejected.** The absence of a field expresses absence; a keyword
expresses it badly.

### 2.3 C — keep validation as is; propose and call in the same tick — rejected

`_tick_termination` (`run.py:832-834`) stops the stage on `raised > 0` under
`proposals_raised`, and the profile's own order is fixed: the reply's proposals
are admitted before its sibling tool batch (`run.py:738-760`), so a proposal
authored in the same tick cannot cite that tick's artifact. C therefore forces
*either* a proposal that cites nothing (run 14's `MALFORMED_PAYLOAD:
payload.evidence_artifact_ref must be 'evidence:<artifact_id>'`) *or* a stop
before gathering. It contradicts the `OBSERVATION` objective in the same
document ("Gather first, propose last"). **Verdict: rejected** — it is the wall
this gate exists to remove.

### 2.4 Rejected alternatives

| Alternative | Why rejected |
| --- | --- |
| A separate action-only **reply section** (`{"actions": [...]}`) instead of reusing `tool_calls` | A second name for the same array: OPS-5B/5G spent two slices teaching one shape. It would also make the runtime's tool phase read two fields. |
| Relax the check at the **runtime** instead | The refusal is raised in the plane before the runtime is reached (`_shape_result` → `_proposal` → `_validate_output`); relaxing downstream would leave the live path unchanged. |
| Make `kind` optional at the **field-spec** level | It already is (`FieldSpec(kind_field, "string", required=False)`, `run.py:336`). The refusal comes from the *kind check*, not the required-field check; making the field optional changes nothing. |
| Accept **any** reply that carries a call (`kind` optional whenever a call is present) | It would mask a malformed proposal: `{"kind": "GATHER", "tool_calls": […]}` would be accepted and its kind silently dropped. §3 requires the reply to raise *no* proposal. |
| Let a stage declare "gathering stages" in the methodology document | A new stage-level concept for a per-*tick* fact; the profile already declares what its stages may call. |
| Skip the contract's `rationale` requirement on an action-only reply | The `RATIONALE` discipline (§2.1: every reply carries a rationale) is per-reply and costless here; keeping it also keeps one shape rule for all replies of a profile. |

## 3. The exact validity predicate

### 3.1 The predicate

A reply is **proposal-free and calling** — and therefore valid with no `kind` —
iff all of the following hold, evaluated in this order:

1. the reply is a JSON object, carries no decision-shaped key, and its keys are
   all declared (unchanged checks, unchanged codes);
2. `contract.action_field` is non-empty — the contract names an action array
   (`""` on every contract that does not, which is today's behaviour exactly);
3. `parsed[action_field]` is a **list with at least one element** — an empty
   array is a reply with neither a proposal nor a call, and is refused as today;
4. the reply **raises no proposal**:
   - the single-form field is absent, or its value is not a non-empty string
     (`None`, `""` and whitespace-only all count as no proposal);
   - the multi-form field is absent, `None`, or an empty list.

When the predicate holds, the kind check is skipped. When it does not, the kind
check runs **exactly as today**, with today's code and detail.

The predicate has one stated consumer and one writer: the model plane decides it,
and the runtime's `_validate_drafts` (`run.py:1068`, `1079`, `1082`) is where the
same reading already lives. §3.3 makes the two agree by construction.

### 3.2 How it is read downstream (why nothing else has to change)

A reply that satisfies the predicate reaches the runtime as `structured` with:

- `tool_calls`: the array the tool phase reads (`run.py:1260`). The per-item
  checks, the batch bound and the admission rules are **unchanged** —
  `capability_id` present, arguments a mapping, keys exactly `TOOL_CALL_KEYS`,
  `capability_id in spec.tools`, the plane's grant.
- no `kind`, no `payload`, no `proposals`: `_validate_drafts` takes the
  *no proposal form present* branch and returns no drafts and no refusals
  (`run.py:1082-1083`). Nothing is admitted, so nothing enters the spine.

The `payload` key stays legal-but-draft-only: a reply carrying a payload and no
proposal is **not** exempted (it declares nothing to call), and it is refused
`ROLE` as today — measured, §1.3 row 6.

### 3.3 The one normalisation, so the two layers cannot disagree

The predicate's condition 4 is the runtime's own reading of "no proposal"
(`run.py:1068`, `1079`, `1082`), so the plane and the validator say the same
thing. To keep the reply the plane returns identical to the reply the validator
reads, the plane drops a single-form value that condition 4 counts as no
proposal (`None` / `""` / whitespace) *when the predicate holds*:

```text
action_only = _action_only_reply(contract, parsed)     # the plane's predicate
if action_only and contract.single_form_field:
    parsed.pop(contract.single_form_field, None)       # null/"" is no proposal
```

Only the falsy values can be dropped — a truthy single-form string makes the
predicate false — so nothing a proposal could be built from is ever removed. A
`MALFORMED_PAYLOAD` for `kind: null` becomes an accepted gathering reply; a
reply with no call and no proposal is still `ROLE`, byte-identical to today.

**Placement, exactly:** the predicate is computed after the JSON-object and
decision-shaped-key checks and **before** the unknown-key check and the
declared-field loop, so the drop precedes the `kind` field's declared-type check
(which is what refuses `null` today) while the unknown-key, required-field, type
and allowed-value checks all still run on the dropped reply. Nothing else in
`_validate_output` moves.

### 3.4 What is still refused, with today's code

| Reply | Code | Why |
| --- | --- | --- |
| neither a proposal nor a call (`{"rationale": "…"}`, `tool_calls: []`, `tool_calls` absent) | `ROLE` | The predicate is false; the kind check runs unchanged. This is the charter's falsifier 2. |
| a kind present but not in the allowlist, with a call | `ROLE` | A malformed proposal attempt is not a gathering reply (§2.4). |
| `payload` with no kind and no call | `ROLE` | Unchanged. |
| the flat form (`capability_id`/`arguments` at the top level) | `MALFORMED_PAYLOAD` | The unknown-key check runs before the kind check; OPS-5G's pin holds. |
| an unknown key anywhere, a wrong type, a wrong allowed value | `MALFORMED_PAYLOAD` | Unchanged, still `contract_feedback=True` (one informed retry, OPS-15). |
| a non-empty `proposals` list with a top-level `kind` present | unchanged | The single-form/multi-form rule is untouched. |
| a **delegation-only** reply (no proposal, no call) | `ROLE` | The action field names exactly one array; the exemption is not extended to `delegations`. |
| any reply over 4 KiB | `RATIONALE` | The `max_proposal_bytes` cap is unchanged. |

### 3.5 Required keys on a proposal-free reply

`rationale` — required, non-empty, unchanged. It is the contract's required
field (`run.py:337`, checked at `router.py:2074-2089`) and the §2.1 discipline
that every model reply explains itself; the model's gathering rationale is
exactly the honest account of why a tick with no proposal was worth making.
Nothing else is required: no `kind`, no `payload`, no `proposals`, no
`delegations`.

**One property to state plainly:** on a proposal-free tick the top-level
rationale is *validated but not consumed*. It is used to build a draft's
justification only in the single-form path (`run.py:1079-1081`); what reaches
the capability plane is each call's own `rationale` (`TOOL_CALL_KEYS`). It is
not written to the trace either: `raw_excerpt` accompanies refusals, not
successful ticks (`run.py:975-984`). Recording the gathering tick's rationale as
an event detail would be a new trace field and is **out of scope**; §12 records
it as an open question, not as part of A.

## 4. What the plane needs, exactly (the phase-2 diff, listed so it is not discovered late)

| Site | Change |
| --- | --- |
| `router.py:344-378` (`OutputContract`) | `+ action_field: str = ""` — the injected action-array name; `""` means "no such concept for this contract" |
| `router.py:2027` (`_validate_output`) | compute the predicate after the decision-key check; `+ if contract.kind_field and not action_only:` at `:2095`; the drop at §3.3 |
| `router.py:2241` (`_contract_mapping`) | `+ "action_field": contract.action_field` so the rendered prompt reads the same name the predicate does |
| `cloud.py:_contract_lines`/`render_system` | one part, appended in the proposal-form block (§8), rendered from `single_form_field`, `multi_form_field`, `action_field` |
| `run.py:323` (`output_contract_for`) | `action_field=(TOOL_CALLS_FIELD if TOOL_CALLS_FIELD in field_names else "")` |
| `tests/test_ops5h_tool_only_tick.py` (new) | the falsifiers of §10 |

No new module, no new import direction (the plane keeps stdlib +
`hermes.security.boundaries`; the runtime keeps naming the field), no event, no
store, no SQL.

## 5. What a call-only tick records

### 5.1 The trace, in order

```text
TICK_STARTED      {"profile": "OBSERVATION-profile"}
MODEL_REQUESTED   {"tier": …, "call_budget": 2}          # one attempt; no retry
TOOL_REQUESTED    {"capability_id": "source_search"}
TOOL_OBSERVED     {"capability_id": "source_search", "artifacts": ["evidence/…"]}
CHECKPOINT_WRITTEN{"state": "RUNNING", "proposals": 0, "terminal": false}
```

Absent by construction: `MODEL_REFUSED` (the plane accepted the reply),
`PROPOSAL_DRAFTED` and `PROPOSAL_REFUSED` (there was no draft to validate), and
`INTENT_*` (nothing was emitted to the spine). There is no per-tick "completed"
event: the tick's end is the checkpoint (`run.py:625-626`, inside the loop at
`run.py:613-628`).

**Measured on this tree.** The outcome is already reachable at the runtime port
(the plane refuses the reply before it, §1.3, so the probe drives the runtime the
way OPS-5F's harness does — a scripted model *port*). A two-tick profile
(`stop_when: proposals_raised`, `max_ticks: 2`) whose tick 1 is run 16's reply
verbatim and whose tick 2 proposes:

```text
state=SUCCEEDED termination=STOP_WHEN ticks=2 proposals=1 tool_calls=1 refusals=0

  tick 1  TICK_STARTED / MODEL_REQUESTED / TOOL_REQUESTED(source_search)
          TOOL_OBSERVED(evidence/art_0001) / CHECKPOINT_WRITTEN(proposals: 0)
  tick 2  TICK_STARTED / MODEL_REQUESTED / PROPOSAL_DRAFTED(INSERT_TASK)
          INTENT_EMITTED / INTENT_ADMITTED / RUN_TERMINATED(STOP_WHEN)
```

Zero refusals, no `MODEL_REFUSED`, tick 1's duties done and the run continuing:
the only thing that stops this today is the plane's kind check. The phase-2 test
is the same sequence with the **real router** in place of the scripted port.

### 5.2 What the counts say

| Surface | Value for a call-only tick |
| --- | --- |
| `ProposalSet.proposals` / the run's admissions | **unchanged** (0 for this tick) — nothing was proposed, so nothing was admitted |
| `ProposalSet.tool_calls` (`run.py:1381` the counter, `run.py:1832` the run's own count) | **+1 per invoked call** — a skipped or refused call is not an invocation |
| `ProposalSet.refusals` | unchanged, *provided the call was not refused*: a skipped call (`ROLE`) or a failed call appends a refusal, and a **failed** call still stops the run `FAILED/TOOL_FAILED` (`run.py:767-773`) — that severity rule is LOOP-4 E7 and is untouched |
| `state.feedback` / `evidence` | one `ToolFeedback` per call; the artifact refs join the evidence set (`_absorb_evidence`, `run.py:797`) |
| `termination` (stage / run) | **unchanged** — the run has not terminated; it continues |
| the live vector | `M2(calls=n)` rises (`live_vector.py:150-160`), `artifacts` rises; the run's `admitted` does not |
| the checkpoint | `proposals: 0`, `tool_calls: n`, `feedback: (…)` — a resumable, non-terminal tick (`run.py:1795-1799`) |

So the observable signature of a gathering tick is **calls up, proposals flat,
no failure code** — the opposite of run 16's signature (`MODEL_REFUSED` with
`proposals` flat and `M2(calls=0)`).

### 5.3 Why it is not a failure tick

The only markers this plane has for "the tick did not work" are
`MODEL_REFUSED` (the plane refused), `PROPOSAL_REFUSED` (a draft failed its
contract), `INTENT_REFUSED` (the spine refused) and `TOOL_FAILED`. None of them
is emitted for a valid gathering reply, and the run's state stays `RUNNING`
until a stop policy or the tick bound ends the stage. The OPS-10 excerpt rule is
equally untouched: an excerpt accompanies a refusal.

## 6. Does the stage continue — and what stops it

### 6.1 `stop_when: proposals_raised` (the shipped `OBSERVATION`, `EVIDENCE`, `CLAIM`, `CONCLUSION`)

`_tick_termination` (`run.py:832-834`) returns `STOP_WHEN` only when `raised > 0`.
A call-only tick has `raised == 0`, so it returns `None` and the run takes
another tick. This is unchanged code; the slice only makes such a tick reach it.
The stage therefore continues **within its declared tick bound**, and its first
proposal still ends it immediately (`proposals_raised`) — the objective's
"propose last" and the profile's stop agree, which is exactly why A fits.

### 6.2 `PROPOSAL_LIMIT`

`len(state.proposals) >= max_proposals` (`run.py:847-848`). A gathering tick
adds nothing to `state.proposals`, so it can neither reach the limit nor be
stopped by it. The limit remains a statement about *admitted proposals*, not
about ticks.

### 6.3 `max_ticks` — the only thing stopping a spin

The tick bound is `context.limits.max_ticks or spec.termination.max_ticks`
(`run.py:1688-1689`), and it is **the sole bound on a stage that only ever calls
tools**. `OBSERVATION` has 3 (OPS-5F); the profile declares 4 and the tool batch
has its own `max_tool_calls` (4) and the run its deadline. A proposal-free tick
must not become a way to spin, and it is not one: it is a tick, it counts
against the bound, and the bound is hard.

### 6.4 The `no_proposals` stage (the `critic` profile)

`stop_when: no_proposals` returns `NO_PROPOSALS` when `raised == 0`
(`run.py:835-836`). **Consequence to state, not to hide:** a critic stage whose
model emits a call-only reply now stops at that tick with `NO_PROPOSALS` instead
of failing the run. That is its own declared policy read correctly ("this stage's
job is to have nothing to raise"), and it is only reachable because a call the
critic's grant cannot reach is refused `ROLE` and skipped (`run.py:1331-1340`),
so no invocation happens. The shipped critic declares no reachable capability,
so in the shipped document this is inert; it is pinned as a behaviour so it is
not discovered as a surprise. Whether `no_proposals` *should* read a gathering
tick as a completed job is a stop-policy question, not this gate's (§12).

## 7. Termination when a stage never proposes

Unchanged, and stated so the bound is not mistaken for a hang:

1. the model calls tools on every tick and proposes on none;
2. the tick loop exhausts `max_ticks`; the run sets `SUCCEEDED` / `TICK_LIMIT`
   (`run.py:630-632`, and again in `_assemble` at `run.py:1816-1818`);
3. `_maybe_review` returns `None` while `state.proposals` is empty
   (`run.py:1622-1623`), so no review child runs and no reviewer cost is
   incurred;
4. `_close` writes the terminal checkpoint and `RUN_TERMINATED`
   (`run.py:681-687`);
5. the methodology driver records the stage with `termination=TICK_LIMIT` and
   extends the chain (`methodology_driver.py:605-655`); the stage's node carries
   the default content with no evidence ref;
6. the chain then stops at `EVIDENCE`, which cannot cite an artifact that was
   never admitted — the same refusal OPS-5F's falsifier recorded.

**No stage is exempt from proposing.** The exemption is per *tick*, not per
stage: a stage whose every tick gathers simply runs out of its declared budget
and ends as above. Nothing here changes the substrate's content rules, and a
stage that ends this way is neither a hang nor a failure of the stage itself.

## 8. The contract must say it — one sentence, drift-guarded

**Where.** `render_system` renders the proposal-form rules from the plane's own
names (`cloud.py:282-296`). The new part is appended in that block, and it is
rendered from the *injected* names — `single_form_field`, `multi_form_field` and
`action_field` — so a rename of either form field or of the action array moves
the sentence with it. The drift guard mutates `TOOL_CALLS_FIELD` on the runtime
module and asserts the rendered sentence follows, exactly as
`test_ops9_contract_rules.py::test_the_prompt_reads_the_validator_key_set`
mutates `DELEGATION_KEYS` today, and OPS-5G's shape guard does for the call
item.

**The sentence, verbatim (recommended):**

```text
A reply that proposes nothing is valid when it calls a tool: omit the "kind"
and "proposals" fields and output a non-empty "tool_calls" array; the stage
continues within its tick budget.
```

**Bytes:** 186 UTF-8 bytes, 187 including the line's newline — one `parts`
entry, system text, never a `ModelRequest.prompt` envelope, so M1 (payload bytes
at the port) is unchanged by construction. It is rendered only for a contract
whose `action_field` is non-empty, i.e. the three profiles that declare
`tool_calls` (`researcher`, `experimenter`, `critic`); every other profile's
system text is byte-identical to today.

**Why the model must be told.** Run 16's model gathered correctly and then
reverted to a shape it believed was legal, because the only shape it had been
taught was "a reply carries a proposal kind" (OPS-8 renders the allowlist into
every prompt). A legal reply nobody describes is a reply the model will stop
sending after one refusal — which is exactly the reversion the addendum records.

**Boundary:** the sentence states the *positive* case. The negative case (a
reply with neither) is unchanged behavior and is already carried by the field
note ("required in the single-proposal form") and by the refusal itself; a
reviewer who wants it stated outright can append one clause
(+54 bytes: `A reply with neither a proposal nor a call is refused.`). It is not
in the recommended sentence, to keep the statement consistent with the charter's
"one sentence".

## 9. What must not change

| Invariant | How the design upholds it |
| --- | --- |
| No new event kind, write path or transaction; census 124 / 28 (19/5/4) / 1 / 15 / 0 | the change is one predicate in the model plane plus one injected contract name; no store, no SQL, no event, no new module |
| `proposable_kinds` untouched; substrate content rules untouched | B is rejected precisely so no pseudo-kind enters the governed list; no gateway or intent vocabulary moves |
| Drain-only byte-identical; B4 24; governed docs untouched | the sentence is rendered by the **live** cloud provider's system text; the drain-only path builds no live contract (OPS-5G's precedent), and the phase-2 gate re-measures B4 |
| LOOP baseline unchanged; M1 unchanged | the baseline builds its own `OutputContract` without `action_field` → `""` → the predicate is false → today's behaviour; the sentence is system text, so M1 (user-prompt bytes) does not move |
| A proposal-free tick is not a way to spin | §6.3: it consumes a tick, and `max_ticks` is the bound; no new loop, no new retry |
| Lease fence, single mutation path, append-only journal | untouched: nothing in this slice writes durable state or reads the lease |
| The runtime's severity rule (LOOP-4 E7) | untouched: a *failed* call still stops the run `FAILED/TOOL_FAILED`; only a *valid* gathering reply stops being a `MODEL_REFUSED` |

## 10. Falsifiers → phase-2 tests

`tests/test_ops5h_tool_only_tick.py` (new). Every falsifier that concerns the
plane runs the **real `ModelRouter` under the live `output_contract_for(...)`
contract** (§1.4), and the ones that concern the loop run the real gateway.

| Falsifier | Test shape | Assertion |
| --- | --- | --- |
| Run 16's exact reply is accepted, the tool executes, no draft is produced, the stage continues | scripted provider + real router under the live `researcher` contract, wired into the runtime with a fake capability port and `max_ticks: 2`; tick 1 = run 16's reply verbatim, tick 2 = a proposal | tick 1: `ModelProposal`, `structured` has no `kind`, one draft-free tool call reaches the port; the trace has `TOOL_REQUESTED`/`TOOL_OBSERVED` and **no** `MODEL_REFUSED`; tick 2 runs and the run's `proposals` has one entry |
| A reply with neither a proposal nor a call still refuses, same code | the five shapes of §1.3 rows 5-7 through the plane | `ROLE`, detail `model proposed kind None, outside the injected proposable allowlist`, `contract_feedback=True`; the detail is byte-identical to today's |
| A malformed proposal is not masked by a call | `{"kind": "GATHER", "tool_calls": […]}` | `ROLE` with `model proposed kind 'GATHER'` |
| A stage that only ever calls tools terminates at its tick bound | `max_ticks: 3`, a model that calls on every tick and never proposes | `ticks == 3`; `termination == TICK_LIMIT`; `state == SUCCEEDED`; no `MODEL_REFUSED`; no review child |
| The full three-tick sequence works (search, fetch, cite) | the shipped document + `OBSERVATION: 3` with the **plane in the path**: tick 1 `source_search` (no proposal), tick 2 `source_fetch` (no proposal), tick 3 `EVIDENCE_TRANSITION` citing the fetched artifact; real gateway | the `EVIDENCE` node's ref is that artifact; `EVIDENCE_REF` admits; three model calls; `M2(calls=2)` |
| The predicate is exactly as stated | table over `{absent, null, "", "  ", "GATHER", legal kind}` × `{absent, [], [call]}` for the action field | accepted only for `{single form raises no proposal} × {non-empty list}`; each refusal's code equals §3.4's row |
| A contract with no `action_field` behaves exactly as today | `OutputContract(kind_field="kind", …)` with `action_field=""`, run 16's reply | `ROLE`, unchanged — this is the LOOP baseline's guarantee, pinned |
| The prompt states it and moves with the constants | `render_system` over the live mapping for the three profiles; then with `TOOL_CALLS_FIELD` monkeypatched | the sentence is present for `researcher`/`experimenter`/`critic` and absent elsewhere; the mutated name appears; `_contract_mapping` carries `action_field` |
| The sentence is bounded | the rendered system text before/after | the delta is 187 bytes for the three profiles and 0 for the others |
| Baseline / census / B4 / LOOP | chartered gates | unchanged (24 / 124 / 28 (19/5/4) / 1 / 15 / 0) |

Beyond the falsifiers, the file pins the OPS-15 interaction (a proposal-free
reply is **not** a `contract_feedback` refusal and therefore earns no retry) and
the critic's `NO_PROPOSALS` reading (§6.4).

## 11. Found while measuring: the multi-form note contradicts the plane

The rendered guidance says, in the `kind` field's own note:

```text
- kind (string, optional; required in the single-proposal form; omit it in the
  multi-proposal form)
```

and the plane refuses exactly that reply:

```text
{"rationale": "cite it",
 "proposals": [{"kind": "INSERT_TASK", "rationale": "a task", "payload": {}}]}
→ ROLE | model proposed kind None, outside the injected proposable allowlist
```

because the kind check is not conditioned on the form. It is the same class of
defect as run 16 — a rendered instruction the validator refuses — found in the
same site, while measuring §1.3. It is **not part of A**, and it is not silently
fixed: the multi-proposal form is a proposal, so it is outside this slice's
scope, and no shipped run has exercised it (the multi-form path is pinned only
*with* a legal top-level kind,
`test_ops9_contract_rules.py::test_a_multi_form_with_a_legal_kind_drafts`).

**Optional fold, for the Director:** one clause — skip the kind check when the
multi-form field carries a non-empty list (the runtime validates each item's
kind by itself at `run.py:1104-1110`, including the profile's authority at
`run.py:1111-1118`, so no item check is lost), with its own falsifier. It closes
the other half of the same contradiction for ~6 lines. Recorded as a decision
point in §12, not as a recommendation to smuggle in.

### 11.1 The phase-2 ruling — correct the instruction, record the form

The Director's ruling was narrower than the optional fold, and it is the
correct one: **the contradiction is worse than an adjacent wording slip,
because the multi-proposal form is unreachable.** The plane's kind check runs
first (`router.py:2095` at the base) and the runtime's both-forms check runs
after (`run.py:1071` at the base), so every multi-form reply fails one of the
two. The note was offering a form that cannot be used.

**In this slice the instruction was corrected to match the enforcement.** The
note no longer offers the multi form: the `kind` note reads `required in the
single-proposal form`, the `proposals` note reads `not usable in this build; a
non-empty array is refused`, and the rendered rule states one form. **Validator
behaviour is unchanged** — making the form work, or removing it, is **OPS-5I**
(`docs/idr/OPS-5I-THE-UNREACHABLE-FORM.md`), which touches OPS-9's semantics
and is not this slice's.

## 12. What I could not decide from the tree

1. **The multi-form fold (§11).** The tree cannot tell me whether the Director
   wants that clause in this revision or a later one. It is genuinely the same
   contradiction; it is genuinely not this charter's shape A.
2. **`null` and `""` as "no proposal".** §3.3 takes the runtime's reading
   (`None`, `""`, whitespace → no proposal) so the two layers agree, which means
   a live model that writes `"kind": null` on a gathering tick is accepted. The
   stricter alternative — exempting only *absence* — is a one-clause change in
   the same predicate, but it would refuse a reply the runtime reads as
   proposal-free and cost one informed retry before failing the stage. I chose
   agreement between the layers; if the Director prefers the stricter reading,
   it is a one-line difference, and it should be chosen before phase 2 fixes the
   predicate in a test table.
3. **Whether the gathering tick's rationale should be recorded.** §3.5: it is
   validated and then unused. Recording it would mean a new trace detail (not a
   new event kind) — a diagnostic change this charter's census item does not
   authorize. Named here rather than added. **Recorded in phase 2 as candidate
   OPS-5J** (§14.5): a new trace detail belongs with the run-report work, not
   with this predicate.
4. **`stop_when: no_proposals` reading a gathering tick as a completed job**
   (§6.4). The shipped critic cannot reach a capability, so nothing in the
   shipped document exercises it; whether the *policy* should distinguish "no
   proposals this tick" from "no proposals, ever" is a LOOP-2/LOOP-4 stop-policy
   question, not a validation one.
5. **The two profiles that declare `allows_tool_calls: true` but no `tool_calls`
   section** (`planner`, `synthesizer`). Their contracts therefore gain no
   `action_field` sentence, and the runtime refuses any call they emit as outside
   their declared contract (`run.py:1262-1271`). That is pre-existing and
   self-consistent (the field the contract asks for is the field the runtime
   reads), but it means the sentence's reach is exactly the three profiles that
   declare the section. If the Director wants a developer stage to gather, that
   is a profile-data change, not this predicate.
6. **The `ROLE` code for "neither" being the *right* code.** It is today's code
   and the charter requires it unchanged, so the design keeps it — but a reply
   that raises nothing at all is arguably a `MALFORMED_PAYLOAD` shape failure
   rather than a partition breach. Changing it would move a code the LOOP
   baseline and the OPS-15 retryability table both pin, for no behavioural gain.
   Recorded, not changed.

## 13. Claim boundary

This note claims the run-16 measurement as given, the two contradiction halves
as located in the tree at the cited lines, the §1.3 probe (taken on this tree
through the real router under the live contract), the predicate and its
implementation sites, the trace and count signature of a call-only tick, the
termination story, the sentence and its byte cost, and the invariants in §9. It
does **not** claim that a live model will gather under the new predicate, that
the stage's eventual evidence is scientifically valid, that replay or a scripted
falsifier proves anything about a live provider, or that the exemption is
cost-free: it is bounded by the tick bound and the profile's stop policy, which
are the only stops it has.

## 14. Phase 2 — what landed, and what it proves

### 14.1 The diff, site by site

| Site | Change |
| --- | --- |
| `router.py` (`OutputContract`) | `action_field: str = ""` — the injected action-array name |
| `router.py` (`_validate_output`) | the predicate is read once, after the decision-key check; a single-form value the runtime reads as "no proposal" is dropped before its type check; the kind check is `if contract.kind_field and not action_only:` |
| `router.py` (`_action_only_reply`) | the predicate itself, one function, no second copy |
| `router.py` (`_contract_mapping`) | carries `action_field`, so the rendered prompt reads the same name |
| `run.py` (`output_contract_for`) | `action_field=TOOL_CALLS_FIELD if the profile declares the section else ""`; the two form notes corrected (OPS-5I) |
| `cloud.py` (`render_system`) | one form is stated (OPS-5I) and one sentence states the gathering exemption, rendered from `single_form_field`, `multi_form_field`, `action_field` |
| `tests/test_ops5h_tool_only_tick.py` | the falsifiers below |

### 14.2 The predicate, in code terms

```python
def _action_only_reply(contract, parsed) -> bool:
    if not contract.action_field:            # "" -> today's behaviour exactly
        return False
    calls = parsed.get(contract.action_field)
    if not isinstance(calls, list) or not calls:   # non-empty list only
        return False
    single = contract.single_form_field
    if single:
        value = parsed.get(single)
        if value is not None and not (isinstance(value, str) and not value.strip()):
            return False                      # a proposal, or a type slip: not exempt
    multi = contract.multi_form_field
    if multi:
        value = parsed.get(multi)
        if value is not None and not (isinstance(value, list) and not value):
            return False                      # a non-empty (or non-list) proposals: not exempt
    return True
```

`rationale` is untouched: it is required by the field spec, and a reply without
it still refuses `MALFORMED_PAYLOAD` / `RATIONALE` exactly as today. The
exemption changes *one* branch — the kind check — and the drop is the runtime's
own reading of "no proposal", so the two layers cannot disagree.

### 14.3 The trace of a call-only tick (measured on this tree)

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

No `MODEL_REFUSED`, no `PROPOSAL_DRAFTED` on tick 1, `proposals` flat, the call
executed, and the run continuing to its next tick.

### 14.4 Falsifiers, each with its result

| Falsifier | Result |
| --- | --- |
| Run 16's exact reply is accepted; the tool executes; `proposals`/admissions stay flat; the stage continues | **PASS** — `ModelProposal`, no `kind` in `structured`, one `TOOL_REQUESTED`/`TOOL_OBSERVED`, tick-1 checkpoint `proposals: 0`, tick 2 drafts and admits |
| The full three-tick sequence (search, fetch, cite) with the plane in the path and the real gateway | **PASS** — three accepted wire replies, one artifact row (`FETCH_HASH`), `EVIDENCE` node `external_ref == evidence:<FETCH_HASH>`, `EvidenceTransitionProposed` admitted, stage ends `STOP_WHEN` |
| A stage that only calls tools ends at its tick bound with a stated termination | **PASS** — `SUCCEEDED` / `TICK_LIMIT`, `ticks == 3`, `proposals == 0`, `tool_calls == 3`, no `MODEL_REFUSED`, no review child |
| A reply with neither refuses, same code as today | **PASS** — `ROLE`, detail `model proposed kind None, outside the injected proposable allowlist`, `contract_feedback=True` |
| A malformed kind beside a call still refuses `ROLE` | **PASS** — `ROLE`, `model proposed kind 'GATHER', …` |
| A multi-form reply refuses, and the note no longer offers the form | **PASS** — without a top-level kind `ROLE` at the plane; with one `MALFORMED_PAYLOAD` at the runtime; the rendered note states one form and calls `proposals` not usable |
| A contract with no `action_field` behaves exactly as today | **PASS** — run 16's reply still refuses `ROLE` with the same detail (the LOOP baseline's guarantee) |
| The predicate is exactly as stated | **PASS** — the 14-row table in the test: accepted only for a non-empty action array and no proposal; `kind: 5` is a type refusal, not an exemption |
| The sentence reaches exactly the three profiles and moves with the injected names | **PASS** — present for `researcher`/`experimenter`/`critic`, absent for the other three; a renamed contract moves every name in the sentence |
| The sentence is bounded | **PASS** — 186 UTF-8 bytes, +187 with its newline, 0 for the other three profiles |
| Baseline / census / B4 / LOOP | **PASS** — see the gate table in the merge log |

### 14.5 Two records this slice does not implement

- **OPS-5I — the unreachable form.** Recorded in
  `docs/idr/OPS-5I-THE-UNREACHABLE-FORM.md`: *the multi-proposal form cannot be
  used in this build; decide whether to make it work or remove it.* The two
  line references are `router.py:2095` and `run.py:1071` at this slice's base
  (`5f44a27`). The instruction was corrected; validator behaviour was not
  touched.
- **OPS-5J — the gathering tick's rationale (candidate).** On a proposal-free
  tick the top-level `rationale` is validated and then unused: it builds a
  draft's justification only in the single-form path, and `raw_excerpt`
  accompanies refusals, not successful ticks. Recording it would be a new trace
  detail — not a new event kind — and it belongs with the run-report work, not
  with this predicate. Named, not added.

### 14.6 What did not move

No new event kind, write path, transaction or module; census unchanged
(124 / 28 (19/5/4) / 1 / 15 / 0); `proposable_kinds` untouched; drain-only
byte-identical and B4 still 24; the LOOP baseline unchanged because a contract
that names no action field keeps `action_field == ""`; and **`max_ticks`
remains the only thing stopping a stage that only ever gathers** — the
exemption makes the ticks already granted usable, it does not add one.

License: Apache-2.0 (LICENSE).
