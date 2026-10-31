# AUDIT — the chain never cites an observation

**Status:** audit complete; one change proposed and falsified at runtime, not landed in `src/`.
**Base:** `slice/ops-5z-required-statement` at `5070857`.
**Evidence:** `D:/New folder/hermes-live.db` (read-only), the run reports in
`D:/New folder/run-reports/`, and two probes in `.hermes/` that render the live
prompt and replay run 40's exact reply without a network call.

---

## 0. Verdict

The premise that motivated this audit is half right, and the half that is wrong
changes the fix.

**Wrong half:** tools *have* executed through the live path — repeatedly.
`M2(calls=n)` is 4 (run 12), 5 (runs 18, 19), 8 (run 31), 1 (run 40); the
`provider_interactions` table holds the provider round-trips; the `artifacts`
table holds four `source_payload` rows written by real `source_fetch` calls in
runs 18, 19 and 31. A tool call is not the missing event.

**Right half:** **no run has ever admitted an `EVIDENCE_TRANSITION`.** The
journal records 80 `EVIDENCE_TRANSITION` intents *rejected* and **zero applied**
(226 `INSERT_TASK` and 98 `ADMIT_TASK` are the only admitted kinds). Every
EVIDENCE node either cites a ref that does not resolve or is never minted. That
is the real absence, and it is the one that stops the chain.

Ranked diagnosis:

| Rank | Hypothesis | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | **The stage ends on a refused draft.** `stop_when: proposals_raised` counts a draft the spine refused as "raised"; `PROPOSAL_LIMIT` counts it too. The gathering tick's observation is then unreachable. | **Holds** | Run 40's `OBSERVATION` reply; `run.py:885`, `run.py:953`, `run.py:1155`; the replay below |
| 2 | **The model proposes on the same tick it gathers**, and the prompt's "top-level `kind` is required" makes that the compliant reading. | **Holds as the trigger** | Run 40's `OBSERVATION` rationale says "I defer the verdict to a later tick" while carrying `kind: EVIDENCE_TRANSITION`; rendered prompt has both rules (`cloud.py:403`, `cloud.py:412`) |
| A | The tools are never offered. | **Ruled out** | The live `tool_calls` note names `source_search`/`source_fetch`, their arguments, provider allowlist, handle grammar, and the same-tick citation rule |
| B | The tools are offered and the model ignores them. | **Ruled out for run 40** | The model emitted a correct `source_search`; it executed at 07:38:59.898 and is the run's one `M2` call |
| C | The model calls a tool and the call is dropped. | **Ruled out literally**; the *result* is orphaned | The call ran; the stage stopped one tick later by its own stop policy, not by the translator, validator or gateway |
| D | The budget forbids it. | **Ruled out for OBSERVATION** | `OBSERVATION` declares 3 ticks; run 40 used 1. Every other stage has 1 tick, which is enough to propose |
| — | **The single next change:** a refused draft is not a raised proposal. Count only `ADMITTED`/`DUPLICATE` drafts for `proposals_raised` and `PROPOSAL_LIMIT`. | **Proposed** | §7; falsifier replay in §7.3 |

The correction matters: a fix aimed at the tool schema (A), the model's
willingness (B), the translator (C) or the tick budget (D) would each be a fix
to something the record shows is already working. The stage's **accounting of a
refusal** is what turns a recoverable tick into a dead stage.

---

## 1. Question 1 — has a tool call ever executed?

Yes, through `build_live_composition` and a real provider, and the evidence is
durable even though the runtime's trace is not.

| Run | `M2(calls=)` | Provider interactions | Fetched `source_payload` rows | Admitted `EVIDENCE_TRANSITION` |
| --- | --- | --- | --- | --- |
| 12 | 4 | 3 PubMed searches + 1 OpenAlex search | 0 | 0 |
| 13 | 2 | 1 PubMed search + 1 OpenAlex search | 0 | 0 |
| 18 | 5 | 4 PubMed/OpenAlex | 1 (`e142ee…`) | 0 |
| 19 | 5 | 5 PubMed/OpenAlex | 1 (`05475c…`) | 0 |
| 31 | 8 | 8 PubMed/OpenAlex | 2 (`ebcd5b…`, `705db4…`) | 0 |
| 40 | 1 | 1 OpenAlex search | 0 | 0 |

The `artifacts` rows are the proof that `source_fetch` executed: the producer is
`capability:source_fetch:<provider>:RESEARCHER:<hash>`, and the row's
`artifact_id` equals the interaction's `response_body_hash` (the content hash of
the fetched body). These are not fixture rows; the same bytes are in the
provider interaction log.

**Why the journal says "0 tool events":** the journal has exactly six event
types — `IntentApplied`, `TaskCreated`, `TaskStatusChanged`, `IntentRejected`,
`ResearchCreated`, `CapabilityPlaneComposed`. The runtime's `TICK_STARTED`,
`MODEL_REQUESTED`, `TOOL_REQUESTED`, `TOOL_OBSERVED` and `PROPOSAL_*` events go
to the in-process trace and the run report, not to the append-only journal. The
absence of `TOOL_*` rows is a **record-coverage fact**, not an execution fact.
The only durable per-call record is `provider_interactions`, which is
provider-level and does not name the capability.

**The absence that is real:** at the audit snapshot (50 projects; the journal
was still being written during the audit — it moved from 1,204 to 1,240 events
between the first and last read), 80 `EVIDENCE_TRANSITION` intents were rejected
and none was applied. The exact totals are a timestamp; the 80/0 ratio is the
finding. Of the 80,
by justification text (a heuristic, not a code), 13 mention a pending/no-artifact
state, 3 explicitly defer, 40 claim an artifact, and 24 are other. The model
frequently knows it has nothing to cite and proposes anyway. That is the behaviour the chain
cannot survive, because `EVIDENCE` (verifier) has no tools and can only cite
what `OBSERVATION` already admitted.

---

## 2. Question 2 — is the tool schema actually offered?

**Yes.** `.hermes/audit_prompt.py` builds the real capability supply (no
network), the real plane, the real generated note and the real rendered system
text. The researcher's `tool_calls` field note is 1,470 UTF-8 bytes and reads,
in part:

```text
legal capabilities: source_fetch(provider: string, one of ['openalex', 'pubmed'],
url?: string, search_handle?: string, row_index?: integer) — Fetch one source by
allowlisted URL, or one row of a prior search by its transient handle and 0-based
index. …; source_search(provider: string, one of ['openalex', 'pubmed'],
topic?: string, doi?: string, pmid?: string, max_results?: integer) — Search one
allowlisted provider (OpenAlex or PubMed) for source rows. …
"tool_calls" is an array; each item is an object with exactly these keys:
{"arguments": {...}, "capability_id": "...", "rationale": "..."} …
An observation returns artifact handles evidence/<artifact_id> and
source_payload/<content_hash>; cite EVIDENCE_TRANSITION as evidence:<artifact_id>
… Proposals are admitted before tool calls in the same tick, so an artifact
observed this tick can be cited only in a later tick.
```

The rendered system message for the same profile (3,671 bytes) carries the
gather sentence; the *user* prompt carries the objective and the tick marker:
"Gather first, propose last … A proposal ends this stage (stop_when:
proposals_raised)" and "tick 1 of 3".

So hypothesis A is false. The tools are named, their argument shapes are
stated, the provider values are closed, the observation handle is spelled out,
and the same-tick citation rule is explicit.

**But the same message contradicts itself.** At `cloud.py:403`:

```text
The top-level "kind" field is required: the single-proposal form is the only
proposal form in this build, and a reply carrying a non-empty "proposals" array
is refused.
```

and at `cloud.py:412`:

```text
A reply that proposes nothing is valid when it calls a tool: omit the "kind" and
"proposals" fields and output a non-empty "tool_calls" array; the stage continues
within its tick budget.
```

The field line says `kind` is "optional; required in the single-proposal form",
then the unqualified sentence says it "is required". The validator's actual rule
is the conditional one (OPS-5H's predicate). Run 40's model resolved the
contradiction the wrong way: it wrote a rationale that says *"I defer the verdict
to a later tick"* and still set `kind: EVIDENCE_TRANSITION`. That is a model
trying to gather while obeying "kind is required" — the inverted twin of the
run-16 defect. Run 16 was an instruction the validator refused; this is a
requirement the validator does not have.

This is a contributing cause, not the single next change (§7.4).

---

## 3. Question 3 — does the reply format carry a tool call?

**Yes, and it reaches the journal's durable consequences.** Run 40's
`OBSERVATION` tick 1, verbatim from the run report:

```json
{
  "kind": "EVIDENCE_TRANSITION",
  "rationale": "No evidence artifact has been fetched yet; per the observation
    methodology I must call source_search to locate a source and then
    source_fetch it before proposing an EVIDENCE_TRANSITION, so I defer the
    verdict to a later tick.",
  "tool_calls": [{
    "capability_id": "source_search",
    "rationale": "Find authoritative COVID-19 case count sources for Brazil and
      India as of 1 September 2020 …",
    "arguments": {"provider": "openalex",
                  "topic": "COVID-19 confirmed cases Brazil India 1 September
                            2020 WHO cumulative",
                  "max_results": 10}
  }]
}
```

The plane accepted the reply; the runtime's `_tool_phase` invoked
`source_search`; the provider interaction `ix_84864a…` was recorded at
07:38:59.898; the run report's vector is `M2(calls=1)`. The same reply's
`EVIDENCE_TRANSITION` was refused by the gateway with

```text
MALFORMED_PAYLOAD: payload.evidence_artifact_ref must be
'evidence:<artifact_id>' … got None
```

The call was **not** dropped at the translator, the draft validator or the
intent gateway. The only place a call can be dropped in this path is a
whole-reply refusal *before* the runtime (an unknown key, a bad type, an
over-cap body), and that is recorded as `MODEL_REFUSED` with an excerpt — not
silent. Run 42 shows that path: `unknown key(s) ['profile', 'spec',
'task_type']`.

So hypothesis C is false in its literal form. What *is* dropped is the
observation's future: the search result, its transient handle, and the refusal
note are all in the run's state when the stage ends, and no later tick reads
them.

---

## 4. Question 4 — why did run 40's OBSERVATION not fetch?

It ran one search and then stopped, with two of its three ticks unspent. The
order inside `_tick` (`run.py:860-900`) is:

1. `_model_phase` — the model reply is validated into drafts, and each draft is
   emitted to the spine. The `EVIDENCE_TRANSITION` is emitted, refused by
   `apply_intent`, and **appended to `state.proposals` anyway**
   (`run.py:1155`), and its digest is returned in `drafted`.
2. `_tool_phase` — `source_search` runs. It succeeds. The observation carries
   `search_handle=…` in its bounded detail, and the feedback envelope for the
   next tick is built.
3. `raised = len(drafted)` (`run.py:885`) — 1, because the refused draft still
   produced a digest.
4. `_tick_termination` (`run.py:944`) — `proposals_raised` returns `STOP_WHEN`.
   The stage ends `SUCCEEDED`, one tick in.

Even if step 3 were changed, step 4's next branch would stop the stage:
`PROPOSAL_LIMIT` compares `len(state.proposals)` (`run.py:953`) against the
stage's `max_proposals: 1`. The refused draft is one proposal. So the same
misconception is written twice.

Then the driver records the `OBSERVATION` node with no `cited_refs` (the
middle-holes rule landed after run 40; it was not live), the `EVIDENCE` stage
runs on the `verifier` profile — **which has no tools** — and there is no
`evidence:` envelope in its prompt at all, because the driver appends one only
when an admitted transition supplied the ref. The model invents
`evidence:obs-sars-covid-40-brazil-india-cases-sep1-2020`; the gateway refuses
with `EVIDENCE_REF`; the stage stops at depth 5.

The search's artifact handle was never in a prompt the EVIDENCE stage could use,
and the verifier could not have fetched it even if it had been. The chain has no
recovery path across that boundary.

**The one thing that did work:** the search handle *does* reach the next tick.
`.hermes/audit_replay.py`'s gather-only mode prints tick 2's prompt; the
`runtime.observation` envelope contains

```json
{"capability_id": "source_search",
 "detail": "search openalex: 2 source row(s) (OK); search_handle=h-audit-0001;
            rows=2; omitted=0",
 "outcome": "TOOL_OBSERVED", …}
```

So the mechanism for tick 2's `source_fetch` exists. It is the stage's stop
policy that prevents tick 2 from happening.

---

## 5. Question 5 — is one tick enough?

For `OBSERVATION`, the budget is not the constraint: the shipped document
declares `max_ticks: 3` (OPS-5F), and run 40 used one. For every other stage,
`max_ticks_per_stage: 1` is enough to raise one proposal; those stages do not
need to gather. Hypothesis D is false for the stage under audit.

The budget *is* a real limit for the repair path on the other stages: a
HYPOTHESIS/PREDICTION/CLAIM/EXPERIMENT reply that the plane refuses for a
missing `statement` gets one informed retry inside the tick (OPS-15) but no
second tick. Runs 41 and 42 show that this is sometimes not enough. That is a
different failure, upstream of OBSERVATION, and it is why their depth is 2 and 1
rather than 5.

---

## 6. The evidence, measured without a live model

`.hermes/audit_replay.py` drives the real `researcher` profile, the real
`project_stage` OBSERVATION context (3 ticks), the real `apply_intent` gateway
and a real artifact row, with a scripted model port. The plane's acceptance is
not being re-proved here — run 40 proves it; what is being measured is the
runtime's tick order.

```
mode=run40
ticks_used=1 (budget 3)
state=SUCCEEDED termination=STOP_WHEN
proposals=2 admissions=1 tool_calls=1
refusal_codes=('MALFORMED_PAYLOAD',)
  - MALFORMED_PAYLOAD tick=1 kind='EVIDENCE_TRANSITION': payload.evidence_artifact_ref must be 'evidence:<artifact_id>' … got None
  proposal EVIDENCE_TRANSITION: admission=REFUSED …
capability calls:
  - source_search {'provider': 'openalex', 'topic': '…', 'max_results': 10}

mode=gather-only
ticks_used=3 (budget 3)
state=SUCCEEDED termination=STOP_WHEN
proposals=2 admissions=2 tool_calls=2
refusal_codes=()
  proposal EVIDENCE_TRANSITION: admission=ADMITTED
capability calls:
  - source_search {'provider': 'openalex', 'topic': '…', 'max_results': 10}
  - source_fetch {'provider': 'openalex', 'search_handle': 'h-audit-0001', 'row_index': 0}
```

The **only** difference between the two runs is the premature
`EVIDENCE_TRANSITION` in the first reply. With it, the stage dies on tick 1 with
a search. Without it, the same stage searches on tick 1, fetches on tick 2 and
admits the citation on tick 3. That is the whole failure, isolated.

`test_ops5z2_draft_feedback.py::test_a_spine_refusal_ends_a_proposals_raised_stage_before_the_note_is_read`
already pins this behaviour and says so in its docstring: "a **spine** refusal …
ends the stage on the same tick, however many ticks it was granted." OPS-5Z2
built the note that would repair the reply and then measured that the stage ends
before the note is read. The slice's own boundary statement is the diagnosis.

---

## 7. The single next change

### 7.1 The change

**A draft the spine refused is not a raised proposal.**

- `_tick` (`run.py:885`): `raised` becomes the number of *this tick's* drafts
  whose admission is `ADMITTED` or `DUPLICATE`, not `len(drafted)`.
- `_tick_termination` (`run.py:953`): `PROPOSAL_LIMIT` compares the same count,
  not `len(state.proposals)`. OPS-5H §6.2 already states the intended meaning:
  "The limit remains a statement about admitted proposals, not about ticks."
  The code does not implement its own design note.

`state.proposals` keeps every draft for the report and the review; the change is
to the *stop-policy accounting*, not to the history.

### 7.2 Why this one, and why it is not a fifth contract rule

- It asks the model to do **nothing new**. Run 40 already gathered correctly;
  the stage threw the gather away. The fix makes the tick that already happened
  usable, and lets OPS-5Z2's note reach the tick it was built for.
- It touches no contract field, no proposable kind, no intent vocabulary, no
  event, no write path. `proposable_kinds` is untouched.
- It is not the "make gather-first a rule" move the record warns against. That
  would be a fifth rule, and it would need a model that complies. This change
  needs no compliance: the model may keep proposing early, and the stage
  survives long enough to be told why the proposal failed.
- It is bounded: the tick budget is still hard. A model that only ever emits
  refused drafts now ends at `TICK_LIMIT` instead of `STOP_WHEN`; it records
  nothing either way, and the bound still ends it.

### 7.3 Falsifier

Add one test (the shape of `.hermes/audit_replay.py`, in `tests/`):

1. **Run 40's exact OBSERVATION reply** on a `researcher` stage with
   `max_ticks: 3`, a real gateway, and a scripted capability port.
   *Before:* 1 tick, `STOP_WHEN`, one `source_search`, `EVIDENCE_TRANSITION`
   refused, no fetch.   *After:* tick 2 runs; its prompt carries the
   `runtime.observation` envelope with the search handle and the
   `runtime.contract_feedback` draft-feedback envelope; a gather-only
   `source_fetch` on tick 2 executes; a valid `EVIDENCE_TRANSITION` on tick 3 is
   admitted.
2. **Control:** a tick-1 draft the spine *admits* still stops the stage at tick 1
   (`proposals_raised` still means what it says for a real proposal). This is
   `EarlyProposalModel` in `test_ops5f_stage_budget.py`, re-run unchanged.
3. **The old pin changes:** `test_a_spine_refusal_ends_a_proposals_raised_stage_before_the_note_is_read`
   must be rewritten to assert the note *is* read on tick 2. That is the point:
   the test currently pins the defect.

**Measured (runtime patch, no `src/` edit).** `.hermes/audit_replay.py
run40-fixed` applies the two accounting rules to the *exact* run-40 reply:

```text
mode=run40-fixed
ticks_used=3 (budget 3); model_calls=4 (incl. review)
state=SUCCEEDED termination=STOP_WHEN
proposals=3 admissions=2 tool_calls=2
refusal_codes=('MALFORMED_PAYLOAD',)
  proposal EVIDENCE_TRANSITION: admission=REFUSED   (tick 1)
  proposal EVIDENCE_TRANSITION: admission=ADMITTED  (tick 3)
capability calls:
  - source_search {'provider': 'openalex', …}
  - source_fetch {'provider': 'openalex', 'search_handle': 'h-audit-0001', 'row_index': 0}
```

Tick 2's prompt, in order: the four payload envelopes, the
`runtime.observation` envelope carrying
`search_handle=h-audit-0001`, a `runtime.contract_feedback` envelope carrying
the tick-1 refusal (`payload.evidence_artifact_ref … got None`), and
`tick 2 of 3`. Tick 3's prompt carries both observations. The note OPS-5Z2
built is read for the first time.

The control, `early-admitted`, is unchanged: a tick-1 `EVIDENCE_TRANSITION`
that the spine accepts stops the stage at tick 1, `STOP_WHEN`, with no tool
calls. So the change does not weaken `proposals_raised` for a real proposal; it
only stops counting a refusal as one.

If (1) does not produce a tick-2 fetch, the change is still correct but not
sufficient, and the next lever is §7.4.

### 7.4 The named second lever (not this change)

Correct `cloud.py:403` to say "required when the reply proposes" and make the
gather sentence adjacent to it. That is a prompt correction, not a new rule: it
makes the rendered text match the validator. It should follow the accounting
fix, because a model that still proposes early is now survivable, and the prompt
change can then be measured on a stage that does not die.

### 7.5 The live probe that would settle it

After the change, run one fresh project with the same question and the same
model, and read only the `OBSERVATION` stage: three ticks, a search on tick 1, a
fetch on tick 2, an admitted `EVIDENCE_TRANSITION` on tick 3. Success is the
`EVIDENCE` node carrying a real artifact id; failure is a second premature
proposal, which would make §7.4 the next change. The journal's
`IntentApplied`/`IntentRejected` rows are enough to read the result; the run
report's `M2` is not needed.

---

## 8. What the four slices actually bought

| Slice | What it changed | Measured effect | Honest verdict |
| --- | --- | --- | --- |
| **OPS-5Z** — a proposing reply must carry a `statement` | The plane refuses a proposal without one; the substrate refuses a minted node without one | Run 40 minted HYPOTHESIS and PREDICTION with statements (the substrate refuses an empty one) and reached depth 5, the deepest `stages_recorded` in the journal. Runs 41 and 42 show the refusal instead of an empty node | **Bought fidelity and the deepest run.** The slice's own record calls it the first live run to mint them; the durable record can support "depth 5", not "first" |
| **middle-holes** — an OBSERVATION with no `cited_refs` is not a recorded stage | The substrate refuses an empty observation | Landed after run 40; 41 and 42 never reached OBSERVATION. Would have removed run 40's empty OBSERVATION from the recorded chain | **Bought honesty, zero live depth yet.** It is the correct rule; it cannot make an observation exist |
| **OPS-5ZM** — an EXPERIMENT records its `test` | The node's content carries the model's `statement` as `test` | Run 40's EXPERIMENT admitted 1 of 2. Run 43 (landed during this audit) reached depth 3 and was refused at EXPERIMENT: the model's reply carried both proposal forms, the stage ran out its tick, and the mint had no `test` | **Bought an honest refusal at the gate; no measured depth.** Run 43 is the first recorded example of the gate doing its job |
| **OPS-5Z2** — a refused draft's note reaches the next tick | The note is queued and rendered into the next `_model_phase` | Run 40's OBSERVATION refusal was a *spine* refusal in a `proposals_raised` stage; the stage ended on the same tick. The note was queued and never read. The slice's own test pins that | **Bought plumbing, no live reach.** It is the missing half of this audit's change, not a depth gain on its own |

**The 5 → 3 → 2 → 1 sequence is not a controlled comparison.** Run 40 is the
only one of the four that reached OBSERVATION. Run 43 (depth 3, during this
audit) failed at EXPERIMENT's `test`; runs 41 and 42 failed earlier, at the
statement gate. Same code, same model — the model's compliance is unstable, not
the contract getting worse. The slices did not cause the drop; they made the
drop legible. Run 40's terminal failure is also not the chain: 15 model attempts
succeeded, then five 429s exhausted the fallback chain. The chain had already
stopped at EVIDENCE.

So: the four slices bought honest refusals and the deepest run's minted nodes.
They did not buy an observation. This audit's change is the first one aimed at the
stage's *ordering*, not at the model's prose.

---

## 9. Found while measuring (nobody was looking for these)

1. **`PROPOSAL_LIMIT` counts refused drafts.** `run.py:953` uses
   `len(state.proposals)`; OPS-5H §6.2 says "[t]he limit remains a statement
   about admitted proposals, not about ticks." Even with `raised` fixed, the
   refused draft would hit
   `max_proposals: 1` and end the stage. The same misconception is written
   twice; fixing one site would have produced a "fix" that changed nothing.
2. **The prompt requires `kind` and then says to omit it.** `cloud.py:403`
   states an unqualified requirement; `cloud.py:412` states the gather
   exemption. Run 40's reply — a deferring rationale with a proposal kind — is
   the signature of a model obeying the first sentence. This is the inverse of
   the run-16 defect: an instruction the validator *does not* enforce, rather
   than one it refuses.
3. **`provider_interactions.evidence_artifact_id` is NULL on every row.** The
   column exists, is indexed and has a `list_for_evidence` reader, but the sink
   (`make_persisting_sink`) never passes it. The fetch→artifact link is
   recoverable only because the interaction's `response_body_hash` equals the
   artifact's content hash. A schema that promises a link and never writes it is
   a record that will mislead the next audit.
4. **The journal has no runtime trace.** Six event types; no `TICK_*`,
   `MODEL_*`, `TOOL_*`, `PROPOSAL_*`. "0 tool events" in the premise is a
   coverage artifact. Any future claim about tool execution has to be read from
   `provider_interactions`, `artifacts` and the run report together; the journal
   alone cannot answer it.
5. **`EVIDENCE` is unrecoverable by design.** The verifier profile has no tools
   (`plan.profiles["verifier"].tools == ()`; the capability line withholds
   `evidence_inspect`). If `OBSERVATION` does not admit a ref in its own stage,
   no later stage can fetch one. The chain has no repair path across the
   boundary — which is why a one-tick stop at OBSERVATION is fatal rather than
   merely slow.
6. **A refused draft consumes the stage's proposal budget.** The stage
   projection sets `max_proposals: 1`; `state.proposals` includes the refused
   draft, so the stage has spent its budget on a command the spine rejected.
7. **The run report calls a refused draft a "proposal".** Run 40's OBSERVATION
   line is `proposals: 2, admissions: 1, refusals: 1`; the two are the refused
   `EVIDENCE_TRANSITION` plus the review/delegation child. A reader cannot tell
   from that line that the stage's own proposal was refused; only the refusal
   list says so.
8. **`test_ops5f_stage_budget.py`'s rig passes no `capability_tool_notes`.**
   The scripted model calls `source_search`/`source_fetch` in a prompt that
   never advertises them. The test proves the runtime's tool phase, not the
   live prompt's offer — the same class of gap the OPS-5H note records for the
   run-16 predicate. The live prompt probe (§2) is what covers it.
9. **The run reports live outside the repo.** `D:/New folder/run-reports/` is
   the only place `model_attempts`, `M2` and the refusal excerpts exist. The
   journal cannot be used alone to answer "did the chain observe?" — which is
   how the premise's "0 tool events" reading became possible.

---

## 10. What this audit does not claim

- It does not claim the four slices were wrong. OPS-5Z's gate is what made run
  40's depth-5 chain possible; the middle-holes rule is correct; OPS-5ZM makes
  the EXPERIMENT node honest; OPS-5Z2 is the note this change finally delivers.
- It does not claim the termination change will make the live model comply. It
  claims the stage will no longer die on a refusal it can repair, and that the
  next tick's prompt will carry both the observation handle and the refusal
  reason.
- It does not claim a scripted replay proves a live provider. The replay proves
  the tick order and the stop-policy accounting; the live reach is §7.5.
- It does not claim scientific validity, reproducibility, or that a fetch is
  evidence. It claims only that the provenance chain can now record the fetch
  the model already makes.
- It does not claim the 5 → 3 → 2 → 1 sequence is a regression caused by the
  slices. It is four samples of unstable model compliance; the controlled
  comparison is the replay in §6, not the runs.

---

## 11. Reproduce

```bash
# What the live prompt offers (no network, no model call)
.venv/Scripts/python.exe .hermes/audit_prompt.py

# Run 40's exact reply vs. the same reply without its premature proposal
.venv/Scripts/python.exe .hermes/audit_replay.py run40
.venv/Scripts/python.exe .hermes/audit_replay.py gather-only

# The journal counts in §0/§1
.venv/Scripts/python.exe - <<'EOF'
import sqlite3
c = sqlite3.connect("D:/New folder/hermes-live.db")
print(c.execute("select event_type, count(*) from events group by 1").fetchall())
print(c.execute("select count(*) from events where event_type='IntentRejected' and payload_json like '%EVIDENCE_TRANSITION%'").fetchall())
print(c.execute("select count(*) from events where event_type='IntentApplied' and payload_json like '%EVIDENCE_TRANSITION%'").fetchall())
EOF
```

The probes insert the repo's `src` on `sys.path` themselves; the shell's own
`hermes` points at a WorkBuddy shim, so the explicit path is not optional for
anything run outside them.

---

## Appendix — the run-40 reply, and what each layer did with it

| Layer | What it did | Where |
| --- | --- | --- |
| Model plane (`ModelRouter`) | Accepted the JSON object: known keys, legal kind, no decision-shaped key, under the cap; `tool_calls` is a non-empty array and the kind check is satisfied | `router.py` `_validate_output` |
| Runtime draft validator | Built one draft (`EVIDENCE_TRANSITION`, payload `{}`); no draft-schema refusal | `run.py` `_validate_drafts` |
| Intent gateway | Refused the draft: `MALFORMED_PAYLOAD`, `payload.evidence_artifact_ref … got None` | `apply_intent` |
| Runtime proposal history | Appended the refused proposal to `state.proposals`; returned its digest as "drafted" | `run.py:1155` |
| Runtime tool phase | Invoked `source_search`; OpenAlex HTTP 200; one `M2` call; feedback envelope retained the handle | `run.py` `_tool_phase` |
| Runtime termination | `raised = 1` → `STOP_WHEN`; the stage ended one tick into three | `run.py:885`, `run.py:944` |
| Methodology driver | Recorded the OBSERVATION node with no cited ref (middle-holes rule not yet live); moved to EVIDENCE | `methodology_driver.py` |
| EVIDENCE stage | Verifier profile, no tools, no `evidence:` envelope; model invented `evidence:obs-sars-covid-40-…`; gateway refused `EVIDENCE_REF` | run report |
| Handler | Failed at depth 5; the retry hit five 429s and exhausted the fallback chain | run report |

The row that matters is the sixth: the layer that turned a recoverable refusal
into a dead stage.
