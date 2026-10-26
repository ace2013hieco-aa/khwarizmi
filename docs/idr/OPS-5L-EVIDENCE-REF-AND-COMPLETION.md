# OPS-5L — surface the ref, and stop calling a citationless run a success

| Item | Value |
| --- | --- |
| Task | OPS-5L: the admitted evidence ref reaches the `EVIDENCE` prompt; a run that admits no evidence transition stops reporting success |
| Base | `main` at `d0961d0` (the OPS-5K merge log plus the run-19 addendum) |
| Branch | `slice/ops-5l-evidence-ref-and-completion` |
| Phase | **1 (design gate) + 2 (implementation) — complete** |
| Status | **IMPLEMENTED (2026-10-26)** — A shipped, the reader gap closed, the report mirrors the task; the rulings are in §10 |
| Run 19 | 33 727-byte OpenAlex artifact fetched; `EVIDENCE` refused `got 'claim:prior-art-sars19/c1'`; six of nine stage runs; the diagnostic report's `terminal_state` is `SUCCEEDED` |
| Run 19 row | The task row said **FAILED** (events 626/632) — the report was the only liar. A latent second path exists and is named in §10.6 |

## 0. Verdict summary

1. **A — a `runtime.evidence` envelope — is chosen.** It is appended to a
   stage's context only when the run holds an admitted evidence ref:
   `{"evidence_ref": "evidence:<artifact_id>", "artifact_id": "<artifact_id>"}`,
   origin `runtime.evidence`, ref `{stage_task_id}:evidence`. It carries the
   ref, its artifact id and nothing else — no rationale, provider, URL, bytes
   or state. It is evidence **data**; the gateway and the substrate remain the
   only validators.
2. **B is not an alternative; it is the status quo on the successful path.**
   OPS-5D already writes the admitted ref into the `OBSERVATION` node's
   `cited_refs`, and the EVIDENCE stage receives it in
   `predecessor_content.cited_refs` (measured, §1.1). It is safe as a
   *rendering of recorded node content*, but it is the wrong designated
   channel: it makes a run-level fact depend on the predecessor's content
   shape, and it already feeds the next node's content channel. A is a
   separate origin, so a reader can tell "the run's admitted evidence" from
   "the previous node's content".
3. **C is rejected.** `external_refs` is the operator's task input (OPS-7);
   the evidence ref is the run's own observation. OPS-5D refuses an
   `evidence:` ref in `external_refs` for exactly this reason
   (`workflows.py:619-634`). Putting it back would let the operator pre-empt
   the agent.
4. **The run-19 quoted line is the diagnostic report, not the task row.**
   `run_report.build_run_report` (`run_report.py:132-142`) derives
   `terminal_state` from the six stage runs' states alone. Every stage run
   ended `SUCCEEDED` — the `EVIDENCE` run's only proposal was refused, but
   `stop_when: proposals_raised` counts *raised drafts*, not admissions
   (`run.py:846-847`; `run.py:807`). The report never sees the driver's
   refusal or the task's `FAILED` transition.
5. **The record path already fails closed.** The live methodology driver
   refuses to record the `EVIDENCE` node when its `external_ref` is empty
   (`methodology_driver.py:625-641`; `substrate.py:866-874`). The handler
   returns `HandlerResult(status="failed_typed", ...)`
   (`task_handlers/__init__.py:328-331`), and the controller does not
   transition the task `SUCCEEDED` on that branch (`controller.py:3237-3270`).
   **S6-B2 did not fire because it was never reached** — the handler returns
   at the `MethodologyRefusal` before the `applied == 0` check. Even if it
   were reached, it is a run-level admission count, not an evidence check,
   and review-task `INSERT_TASK` admissions count in it.
6. **Six of nine stages.** The first five stages ran. The sixth (`EVIDENCE`)
   ran and ended `SUCCEEDED`/`STOP_WHEN` with one proposal and zero
   admissions. The driver then refused the node (empty `external_ref`),
   returned the `MethodologyRefusal`, and `CLAIM`, `CRITIQUE` and
   `CONCLUSION` never ran. The six snapshots are six *stage runs*; the driver
   built five in-memory nodes, refused the sixth, and returned no execution
   (measured, §1.2).
7. **The honest terminal is `FAILED`, with a named reason.** `FAILED` is
   already the controller's terminal and the report's vocabulary
   (`run_report.py:142`; `controller.py:5332-5344`). No new terminal is
   invented. The report must mirror the root task's terminal and carry
   `terminal_reason`; a report built without a task outcome gets a fail-closed
   evidence check: an `EVIDENCE` stage with no admitted `EVIDENCE_TRANSITION`
   anywhere in the run is not `SUCCEEDED`.
8. **Two companion defects are recorded and in scope, because A cannot work
   without them.**
   - **The selector does not normalise the OPS-5K handle.** The gateway accepts
     `evidence/<id>` and stores the canonical ref (OPS-5K), but
     `_admitted_evidence_proposal` requires the raw payload to start with
     `evidence:` (`workflows.py:668-673`). A model citing the capability
     plane's own handle is admitted, then ignored, and the EVIDENCE node is
     refused. Measured in §1.5. The fix is read-side canonicalisation; the
     gateway and substrate are untouched.
   - **The report's terminal ignores the task.** See §3.
9. **No new event kind, write path, transaction, table or port.** Census stays
   **124 / 28 (19/5/4) / 1 / 15 / 0**. `proposable_kinds`, grants, `max_ticks`,
   objectives, the substrate's content rules, the gateway's checks and the
   `EVIDENCE` requirement are untouched. Drain-only byte-identical; B4 24;
   governed docs untouched; LOOP baseline unchanged (the envelope is a
   methodology-driver prompt part, and the baseline corpus does not use the
   driver).
10. **What this does not claim.** It does not claim a live model will cite.
    A surfaces the ref when one exists; it cannot create one. The run-19
    `"pending"` placeholder was refused and left no admitted ref, and A alone
    would still leave the EVIDENCE stage with an absent envelope. The
    acceptance is that the *system* never calls that run a success — not that
    the model magically succeeds.

### 0.1 The one sentence to carry forward

**The run holds one admitted evidence ref; the stage that must cite it should
see that ref by name, and a run that never admitted one has no terminal but
`FAILED`.**

## 1. The measurement

All probes are in-process, scripted, and offline: the real live methodology
driver, the real gateway, the real substrate, and (where a fetch is needed) the
real OPS-5C capability supply with a scripted HTTP transport — the same rig the
OPS-5D tests use. They are not committed; this note records their output.

### 1.1 The successful path's EVIDENCE prompt already carries the ref

With the OPS-5D `FetchThenCiteModel` (fetch in `HYPOTHESIS`, cite the fetched
artifact at `OBSERVATION` with the colon spelling), the run reaches
`termination=COMPLETE`, `stages=9`, and the EVIDENCE stage's prompt contains:

```text
origin: runtime.payload  ref: task-ops5d:EVIDENCE:predecessor_content
{"predecessor_content": {"cited_refs": ["evidence:0eb8332c...df73"],
                         "predecessors": ["mnode_e62a267b...6ec"]}}
```

So B is real: on the successful path the ref is already in the prompt, inside
the previous node's content. The run-19 failure is not that this field was
dropped; it is that **there was no admitted ref to put in it**.

### 1.2 The run-19 shape: six SUCCEEDED stage runs, no execution

A scripted run in the run-19 shape (no fetch citation; `OBSERVATION` proposes
the `"pending"` placeholder and is refused; `EVIDENCE` proposes
`claim:prior-art-sars19/c1` and is refused):

```text
QUESTION     SUCCEEDED  TICK_LIMIT  props=0 adm=0 ref=0
HYPOTHESIS   SUCCEEDED  TICK_LIMIT  props=0 adm=0 ref=0
PREDICTION   SUCCEEDED  TICK_LIMIT  props=0 adm=0 ref=0
EXPERIMENT   SUCCEEDED  TICK_LIMIT  props=0 adm=0 ref=0
OBSERVATION  SUCCEEDED  STOP_WHEN   props=2 adm=1 ref=1   # the admission is the review child's INSERT_TASK
EVIDENCE     SUCCEEDED  STOP_WHEN   props=1 adm=0 ref=1

driver: REFUSAL MALFORMED_PAYLOAD @ EVIDENCE (source=substrate)
detail: a EVIDENCE node cites an existing artifact: it needs a non-empty
        'external_ref' — an existing-kind node is never minted here, only cited
driver store: five in-memory nodes (QUESTION..OBSERVATION), then the EVIDENCE
        node is refused; the refusal returns no execution and the store is lost
handler shape: HandlerResult(status='failed_typed', outcome_recorded=False)

diagnostic report: terminal_state=SUCCEEDED, stages=6 of 9
```

This reproduces the Director's line exactly, including
`EVIDENCE SUCCEEDED STOP_WHEN props=1 adm=0 ref=1`. The six stage runs are all
`SUCCEEDED`; the chain returned a refusal, not an execution. The only
admission in the six is the `OBSERVATION` review child's task insertion — a
bookkeeping admission, not evidence. That is also why a run-level admission
count is not evidence.

### 1.3 The report is the surface that says SUCCEEDED

| Layer | What it says in the shape above | Why |
| --- | --- | --- |
| `EVIDENCE` stage run | `SUCCEEDED`, `STOP_WHEN`, `props=1`, `adm=0`, `ref=1` | `_tick_termination` stops on `raised` (a drafted proposal), not on an admission (`run.py:846-847`); the tick then terminates `SUCCEEDED` (`run.py:807`). A refused proposal is data, by design. |
| methodology driver | `MethodologyRefusal(MALFORMED_PAYLOAD, stage=EVIDENCE, source=substrate)` | The `EVIDENCE` node needs a non-empty `external_ref`; `_default_content` sets exactly the admitted `evidence_ref` (`workflows.py:724-727`), which is empty; `write_node` refuses (`methodology_driver.py:625-641`; `substrate.py:866-874`). |
| task handler | `HandlerResult(status="failed_typed", outcome_recorded=False)` | A `MethodologyRefusal` is returned before the `applied == 0` check (`task_handlers/__init__.py:328-331`). |
| controller task | not `SUCCEEDED`; `FAILED` or `RETRYING` with the handler's reason | The `completed` branch is the only SUCCEEDED branch (`controller.py:3237-3270`); `failed_typed` goes to `_retry_or_fail` (`controller.py:5302-5344`). |
| **diagnostic report** | **`terminal_state="SUCCEEDED"`** | `build_run_report` reads only `stage_runs`; all six stage states are `SUCCEEDED` (`run_report.py:132-142`). It never receives the driver's refusal or the task's state/reason. |

The quoted line's fields (`terminal_state`, `ticks`, the stage
`state`/`termination`/`props`/`adm`/`ref` tuple) are the report's fields. The
task row has no `stages` or `ticks`; it carries a status, and its latest
`TaskStatusChanged` event carries the reason.

**The S6-B2 question.** The run-level rule is
`applied = sum(stage.intents_applied); if applied == 0: failed_typed`
(`task_handlers/__init__.py:339-350`). It did not fire in run 19 because the
handler returned at the driver refusal first. If it had been reached, it would
not have distinguished evidence from bookkeeping: the `OBSERVATION` review
child's `INSERT_TASK` is an admission. S6-B2 is a liveness check ("the handler
recorded something through the one write path"), not an evidence check. The
evidence requirement is the `EVIDENCE` node's ref rule, and it already fails
closed.

### 1.4 Why only six of nine stages ran

The live driver iterates the nine declared stages in order. A stage whose run
does not reach `SUCCEEDED` is not recorded and stops the chain
(`methodology_driver.py:607-612`). Here every stage *run* reached `SUCCEEDED`,
so the loop reached `EVIDENCE`. It then built the `EVIDENCE` node and
`write_node` refused it (empty `external_ref`); the driver returned the
`MethodologyRefusal` (`methodology_driver.py:638-641`). `CLAIM`, `CRITIQUE`
and `CONCLUSION` never ran. The six snapshots are the six runs that happened.
The driver did **not** stop at `EVIDENCE` and return success; it stopped at
`EVIDENCE` and returned a refusal. The report turned the six clean runs into
`SUCCEEDED`.

### 1.5 The OPS-5K handle gap: an admitted ref the driver cannot see

This is the system-caused version of "the ref never reaches the stage". A
scripted run fetches in `HYPOTHESIS` and cites the capability plane's own
handle at `OBSERVATION`:

```text
model citation: evidence/0eb8332c...df73

OBSERVATION  SUCCEEDED  STOP_WHEN  props=2 adm=2 ref=0
    EVIDENCE_TRANSITION ADMITTED evidence/0eb8332c...df73
    INSERT_TASK ADMITTED
EVIDENCE     SUCCEEDED  TICK_LIMIT props=0 adm=0 ref=0

driver: REFUSAL MALFORMED_PAYLOAD @ EVIDENCE (source=substrate)
transition event payload:
{"evidence_artifact_ref": "evidence:0eb8332c...df73", ...}   # canonical, admitted
```

The gateway normalises `evidence/<id>` to the canonical `evidence:<id>` before
the event (OPS-5K, `gateway.py:1466-1482`, `:1549-1563`), but
`_admitted_evidence_proposal` reads the **raw intent payload** and requires
`ref.startswith("evidence:")` (`workflows.py:668-673`). The admitted handle is
skipped, `evidence_ref` stays empty, and the `EVIDENCE` node is refused. The
event proves the admission; the reader does not see it. This is a reader-side
gap, not a gateway or substrate rule: the fix is `canonical_evidence_ref` at
the selector and at `_evidence_ref_of`, exactly the normalisation OPS-5K
already applied at the writer.

### 1.6 The run-19 `"pending"` placeholder

The director's addendum records `OBSERVATION` proposing
`"evidence_artifact_ref": "pending"`. That value is refused
`MALFORMED_PAYLOAD` (the schema requires a ref), and because
`stop_when: proposals_raised` stops the stage on the first drafted proposal,
there is no later tick in which the same stage could cite the artifact it
fetched. The EVIDENCE stage is a `verifier` with `max_ticks: 1` and no tool
capability (`verifier.yaml`), so it cannot fetch or acquire a ref of its own.
Once `OBSERVATION` refuses the placeholder, the run has no admitted ref and is
already past the only stage that could have produced one. A cannot create a ref
here; it can only surface one when it exists. This is why §3's honest terminal
is not optional.

## 2. Finding 1 — how the ref reaches the EVIDENCE stage

### 2.1 A — the `runtime.evidence` envelope (chosen)

**Shape.** One `UntrustedContent` envelope, produced by a pure renderer in
`hermes.agents.runtime.assembly` (beside `project_index_envelope` and
`task_input_envelope`):

```json
{
  "evidence_ref": "evidence:<artifact_id>",
  "artifact_id": "<artifact_id>"
}
```

- origin: a new prompt-origin constant, `runtime.evidence`;
- ref: `{stage_task_id}:evidence` (the same attribution style as
  `{task_id}:task_input`);
- nothing else: no rationale, provider, URL, media type, byte count, state
  rung or content. The artifact id is the ref's suffix, derived — the driver
  does not re-dereference the artifact table;
- canonical input only: the selector canonicalises first (§2.5), so the
  document always carries `evidence:<id>`, even when the model wrote the
  handle;
- bounded by construction: two short strings, far below the 4 KiB prompt
  envelope bound; no truncation path is needed.

**Placement.** The live driver appends the envelope to the stage's
`TaskContext.context` after the project-index envelope and before
`wiring.run` (`methodology_driver.py:580-597`):

```text
context.context = (runtime.task, [runtime.project_index], runtime.evidence)
payload envelopes = runtime.payload (stage, objective, predecessor, ...)
```

The default assembler already renders `context.context` in order and the
payload envelopes after it (`assembly.py:283-292`), so the runtime needs no
new port: the driver hands it an already-rendered envelope. Deterministic
order, no clock, no I/O.

**When it is present.** Whenever the run holds an admitted ref at the moment
the stage's context is built: after an admission in `OBSERVATION`, the
`EVIDENCE` stage and every later stage see it; after an admission in
`EVIDENCE` itself, `CLAIM`, `CRITIQUE` and `CONCLUSION` see it. The stage that
makes the admission does not see it in its own prompt — the prompt predates
the admission, and there is no re-prompt. That one-stage lag is pinned, not
hidden.

**Authority.** None. The envelope is data. The gateway's `EVIDENCE_REF` check
remains the only artifact-row check; the substrate's node write remains the
only content rule; the envelope is never read by a validator and never
becomes an admission. A retracted ref in the envelope still fails closed at
the node write (N9).

### 2.2 B — through `predecessor_content` (rejected as the designated channel)

B is already the successful path's carrier: OPS-5D writes the admitted ref into
the `OBSERVATION` node's `cited_refs`, and the EVIDENCE stage sees it in
`predecessor_content` (§1.1). It is safe *as a rendering of recorded node
content*: it is the node's own field, read-only, deterministic, and the driver
does not copy it into the next node's content. The driver's `content_cache`
is keyed by node id and is only passed to the prompt
(`methodology_driver.py:580-587, 645`).

It is rejected as the designated channel for three reasons:

1. **It makes a run-level fact depend on the predecessor's content shape.** The
   ref is in `cited_refs` only because OPS-5D's `_default_content` put it
   there (`workflows.py:730-732`). A future content rule, a different
   predecessor, or a stage whose predecessor is not the admitting stage can
   remove it without touching the run's evidence fact. A is independent of
   the node-content schema.
2. **It conflates the evidence citation with chain content.** The field is
   the previous node's content; a reader cannot tell "this is the run's
   admitted evidence" from "this is a content key the node happens to carry".
   The separate origin is the whole point of a prompt envelope.
3. **It cannot cover the EVIDENCE stage's own admission.** If the ref is
   admitted at `EVIDENCE`, the predecessor content predates it; B can never
   carry it there. A (or none) is the only honest answer at that stage.

Adding the ref *into* `predecessor_content` when it is not in the node's
content would be worse: the prompt would assert a content field the node does
not have. That is rejected outright.

### 2.3 C — in `external_refs` of the task-input envelope (rejected)

`task_input_envelope` carries the operator's question and the refs the
operator supplied (`assembly.py:253-280`). The evidence ref is the run's own
observation, not operator input. OPS-5D already refuses an `evidence:` ref in
`external_refs`, `admission_refs` and the evidence position's
`stage_content` (`workflows.py:619-653`), so C would reverse a frozen
decision and let the operator pre-empt the agent. It is also the envelope
whose refs are *admission* facts, not the run's admitted evidence. Rejected.

### 2.4 The absent-ref pin

**The envelope is absent when the run holds no admitted evidence ref.** It is
not an envelope that says "none". The reasons:

- The envelope's contract is "the ref the run admitted". With no admission
  there is no value to render; a negative object would be a second shape, a
  second pin, and a prompt state that can drift from the run.
- A "none" object is not evidence and could be read as a directive; the
  model's job at EVIDENCE is already stated by the objective.
- The failure is already named by the driver and the substrate. Absence plus
  the fail-closed node write is the honest pair.

Pinned behaviour:

| Situation | Envelope | Consequence |
| --- | --- | --- |
| `OBSERVATION` (before any admission) | absent | The stage gathers and may admit a ref; its own prompt cannot carry it. |
| `EVIDENCE` with no prior admission | absent | The objective still asks for the ref; the gateway refuses any fabricated ref; the driver refuses the `EVIDENCE` node (`external_ref` empty); the run is not `SUCCEEDED` (the report mirrors the task, §3). |
| `EVIDENCE` with an admission from `OBSERVATION` | present | The prompt carries `evidence_ref` + `artifact_id`; a proposal citing it is admitted and the node records that ref. |
| `CLAIM`/`CRITIQUE`/`CONCLUSION` after an admission | present | The run still holds the ref; the later stages see the same value. |
| A ref admitted at `EVIDENCE` itself | absent in that stage, present in `CLAIM`+ | No retroactive re-prompt; the node's ref comes from the admitted proposal itself. |

The test pins absence by asserting that no prompt part has origin
`runtime.evidence` at the named stages; it does not assert an empty document.

### 2.5 The selector normalisation (companion, in scope)

`_admitted_evidence_proposal` must canonicalise the raw payload before its
`evidence:` check, and `_evidence_ref_of` must return the canonical form:

```text
selected = admitted EVIDENCE_TRANSITION whose
           canonical_evidence_ref(payload.evidence_artifact_ref) is not None
evidence_ref = canonical_evidence_ref(...)          # evidence:<artifact_id>
```

This is the read-side half of OPS-5K's "one reference, two spellings". It
does not touch the gateway, the substrate, the artifact-row check or the
`EVIDENCE` requirement. It makes the capability plane's own handle (the value
the model actually receives) selectable, and it makes the node's stored ref
canonical under either spelling. Without it, A cannot be built from an
admitted handle and the run-19 family recurs with a real admission in the
journal.

## 3. Finding 2 — the terminal that must not say SUCCEEDED

### 3.1 What the tree does, layer by layer

See §1.3. The short version: the report's `terminal_state` is the only layer
that says `SUCCEEDED`; the driver refuses, the handler fails, the controller
does not succeed. The report's rule is:

```python
states = [snapshot.result.state for snapshot in stage_runs]
if quarantine:   terminal = "QUARANTINED"
elif not states: terminal = "NO_STAGE_RUNS"
elif all(state == TaskStatus.SUCCEEDED.value for state in states):
    terminal = "SUCCEEDED"
else:            terminal = "FAILED"
```

(`run_report.py:132-142`). It has no task outcome, no driver outcome, no
admissions and no evidence kind in the decision. Every stage run in the
run-19 shape is `SUCCEEDED`, so the report says `SUCCEEDED`.

The vector's `runs=6 ... SUCCEEDED:6/OTHER:0` is the same stage-run fact in
another surface: `termination_mix` counts the six stage `ProposalSet`s
(`live_vector.py:117-146`), not the root task. It is a measurement, not a run
verdict, and it stays unchanged (LOOP baseline). The report's
`terminal_state` is the surface the operator reads as the run's terminal; it
must not be inferred from the same stage states.

### 3.2 The honest terminal

**`FAILED`, with a named reason.** It is the existing controller terminal and
the existing report value; no new terminal state is invented. The task record
already carries it (the handler's `failed_typed` reason is the reason on the
task's `TaskStatusChanged` event). The report must mirror the root task, not
infer a terminal from stage states.

The report gains a `terminal_reason` field (diagnostic, bounded, never an
authority). Its value:

- when the root task is not `SUCCEEDED`: the latest `FAILED`
  `TaskStatusChanged` reason for that task (the handler's
  `MALFORMED_PAYLOAD: ...` in the run-19 shape), or a sentence naming the
  non-success state when no reason is on file;
- when the report is built without a task outcome and the stage data shows an
  `EVIDENCE` stage with no admitted `EVIDENCE_TRANSITION` in any stage:
  "the run admitted no evidence transition" (the fail-closed backstop);
- `""` for `SUCCEEDED` / `NO_STAGE_RUNS`.

The precedence is: `QUARANTINED` > a non-`SUCCEEDED` task > the evidence
backstop > `NO_STAGE_RUNS` (only when neither task nor stage data exists) >
all-stage `SUCCEEDED`. The backstop makes the run-19 shape fail even for a
caller that builds a report from `stage_runs` alone (the OPS-5K report tests
do this with a single `OBSERVATION` stage, so they are unaffected). It inspects
the admitted proposals' kind — `EVIDENCE_TRANSITION` — not the admission
count, so a review child's `INSERT_TASK` cannot mask it. `terminal_reason` is
added to the report's minimal-key set in `_fit`, so a truncated report never
drops the one field that explains the terminal.

**Where the report gets the task outcome.** The CLI already has the controller
result and the open connection after `ctrl.run`
(`cli.py:621-676`). Before `conn.close()`, it reads the **root methodology
task** — the task-id prefix of the stage snapshots
(`{task}:{stage}`) — and records its final state plus the latest `FAILED`
`TaskStatusChanged` reason. It passes that one outcome to
`_write_live_report` → `build_run_report`. This is a read on the existing
connection; no write, no transaction, no new authority. A read failure falls
back to the stage-only path and never fails the run, exactly as the report's
own failure already does. The root task is used, not every child task, so a
failed review child cannot mislabel a successful root.

**Why not change the stage state?** A refused proposal is data, and a stage
run that stops cleanly is `SUCCEEDED` by the runtime's contract. Marking the
`EVIDENCE` *run* `FAILED` would rewrite refusal-as-data and would not
generalize to other required stages. The methodology layer already fails the
chain; the report must read that failure. The fix is in the report, plus the
selector (which turns the system-caused handle failure into a real success).

**Why not a new terminal `RAN_CITED_NOTHING`?** `FAILED` already covers "the
run did not complete"; the reason carries the distinction. A new terminal
would be a new vocabulary value in a diagnostic artifact, with no authority
behind it, and would violate the charter's "do not invent a new terminal if
one already covers it". Rejected.

**Why not make `EVIDENCE` optional / relax the node rule?** That would make
the run pass by deleting the requirement the programme exists to enforce. The
substrate's `external_ref` rule stays exactly as it is. Rejected.

### 3.3 The acceptance test

The new test file reproduces the run-19 shape with the real live driver and
the real gateway/substrate:

1. a scripted model with no admitted evidence (`"pending"` at `OBSERVATION`,
   the claim ref at `EVIDENCE`) produces six stage runs, all
   `SUCCEEDED`, and `EVIDENCE props=1 adm=0 ref=1`;
2. the driver returns `MethodologyRefusal` at `EVIDENCE` (`source=substrate`);
3. the handler returns `failed_typed`, not `completed`;
4. the root task is not `SUCCEEDED` — the controller-level pin reuses the
   `test_wiring_w4.py` dispatch shape
   (`test_a_zero_admission_methodology_run_is_not_a_recorded_outcome`): the
   failed entry is dispatched, `out.succeeded == []`, and the task does not
   reach SUCCEEDED;
5. the report's `terminal_state` is `FAILED`, never `SUCCEEDED`, and its
   `terminal_reason` names the evidence refusal / no-evidence condition;
6. the same test with a fetch and an admitted ref (both spellings) reaches
   `COMPLETE` (9 of 9), the EVIDENCE node's `external_ref` equals the fetched
   artifact, the EVIDENCE prompt carries the `runtime.evidence` envelope, and
   the report is `SUCCEEDED`.

## 4. Invariants

| Invariant | How the design upholds it |
| --- | --- |
| **No new event kind, write path or transaction; census 124 / 28 (19/5/4) / 1 / 15 / 0** | The envelope is a prompt part; the selector is a read-side normalisation; the report is a file. No event, table, port, transaction or acquisition owner moves. |
| **Substrate content rules and gateway checks unchanged; `EVIDENCE` stays required** | The `EVIDENCE` node still needs a non-empty `external_ref`; `EVIDENCE_REF` is still the only artifact-row check; the selector uses the gateway's admission, never a second dereference. No rule is relaxed. |
| **`proposable_kinds`, grants, `max_ticks`, objectives untouched** | The envelope is prompt data; the driver does not change the profiles or the document. |
| **Drain-only byte-identical; B4 24; governed docs untouched; LOOP baseline unchanged** | The live branch is the only place the envelope/report change is reachable. The LOOP baseline corpus is a plain runtime context, not the methodology driver; its M1 bytes do not move. The new envelope is a live-run M1 change, stated, not a baseline re-pin. |
| **No key material** | The envelope carries two ids; the report reason is the handler's bounded refusal text. No key, body, URL or credential enters either. |
| **Report is not a record** | `terminal_reason`/task outcome are diagnostic fields; the task row and the journal remain the record. The report is never read back as authority. |

## 5. Falsifiers → tests (phase 2)

| Falsifier | Test shape | Assertion |
| --- | --- | --- |
| The EVIDENCE prompt carries the admitted ref, and a scripted run citing it admits with `EVIDENCE.external_ref ==` the fetched artifact | Fetch in `HYPOTHESIS`; admit at `OBSERVATION` with the colon spelling; EVIDENCE cites the envelope's ref | Exactly one `runtime.evidence` part at EVIDENCE with `{evidence_ref, artifact_id}`; the node's `external_ref` equals the artifact; the run is `COMPLETE` (9/9); the transition event carries the canonical ref |
| The same with the capability plane's handle | Cite `evidence/<id>` at `OBSERVATION`; the same EVIDENCE flow | The gateway admits and stores canonical; the selector canonicalises; the node's ref is `evidence:<id>`; the run is `COMPLETE` (the §1.5 gap is closed) |
| A stage with no admitted ref yet behaves as designed | Run the no-evidence model through `OBSERVATION`/`EVIDENCE` | No `runtime.evidence` part at either stage; the driver refuses at EVIDENCE; no `EVIDENCE` node; the handler is `failed_typed` |
| A run admitting no evidence transition cannot terminate `SUCCEEDED` | The run-19 shape; build the report with and without a task outcome | The driver refuses; the handler fails; the report's `terminal_state == "FAILED"` and `terminal_reason` names the evidence condition; `terminal_state != "SUCCEEDED"` |
| The report mirrors a genuine success | The successful scripted run; report with the root task `SUCCEEDED` | `terminal_state == "SUCCEEDED"`, `terminal_reason == ""`; the stage list is 9/9 |
| A quarantined task still outranks | The OPS-10 quarantine shape | `QUARANTINED` unchanged; the new task outcome does not override it |
| Census / baseline / B4 unchanged | The chartered gates | 124 / 28 (19/5/4) / 1 / 15 / 0; LOOP baseline 4/4; B4 24 |

## 6. Gates (implementation phase)

1. Targeted: the new test file, `test_ops5k_ref_spelling`,
   `test_ops5d_proposal_content`, `test_methodology_plane`, `test_wiring_w3`,
   `test_wiring_w4` (the controller-dispatch pin), `test_loop_baseline`,
   `test_b4_ref_graphs`, `test_census_check`.
2. `scripts/run_tests.py` (full) under the heavy-gate lock.
3. `scripts/stamp_suite_count.py` then `--check`.
4. `scripts/check_census.py` — unchanged.
5. `uvx ruff check src tests scripts`; `uvx pyright src`; pyright with
   `pyrightconfig.tests.json`.

For **this phase-1 commit** the change is docs-only. The gates on this tree:

| Gate | Result |
| --- | --- |
| Targeted (the eight existing files above, chartered set) | **256 passed**, exit 0 (256 collected) |
| Full suite (`scripts/run_tests.py`) | **5 376 passed, 3 skipped, 0 failed in 639.06s**, exit 0 (5 379 collected) |
| `scripts/stamp_suite_count.py --check` | `OK: docs\SUITE-COUNT.md collected=5379 matches the live collect` |
| `scripts/check_census.py` | **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0 |
| `uvx ruff check src tests scripts` | `All checks passed!` |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| pyright tests project | `0 errors, 1 warning` (pre-existing `test_research_program.py:144`) |

The documented baseline-5 environmental reds did not reproduce on this run;
the suite was fully green. No code changed in this phase.

## 7. What I could not decide from the tree

*Every item below is answered in §10; they are kept as the open questions the
phase-1 gate actually had.*

1. **Run 19's actual report JSON and task row are not in the tree.** The
   quoted line is the report's vocabulary (`terminal_state`, `ticks`,
   stage `state`/`termination`/`props`/`adm`/`ref`), and the reproduced shape
   produces exactly it. The tree's task path returns `failed_typed`; if the
   Director's task row was also `SUCCEEDED`, that is a different path and the
   run-19 report/task row is needed to name it. The fix covers the report
   either way; the task-row question is the one I cannot settle without the
   artifact.
   → **Resolved (§10.4): the row said `FAILED`.** A second path does exist in
   the tree, but run 19 did not travel it (§10.6).
2. **Whether A should ride every later stage or only `EVIDENCE`.** I recommend
   every stage after the admission (the run holds the ref), with the
   one-stage lag for the admitting stage pinned. The narrower option changes
   fewer prompt bytes; the broader one is the honest statement of the run's
   state.
   → **Resolved (§10.3): every later stage, as recommended.**
3. **Whether the OBSERVATION `"pending"` placeholder needs a prompt sentence.**
   The charter freezes objectives, and the objective already says to cite the
   fetched artifact; the placeholder is a model behavior, not a schema gap.
   I did not add a sentence. If the Director wants one, it is a separate
   contract-note change with its own drift pin.
   → **Unchanged: no objective was added.**
4. **The exact report field name and reason wording.** `terminal_reason` is
   proposed; the reason string is the task's latest `FAILED` transition
   reason, or the evidence backstop's sentence. Both are diagnostic text,
   not a terminal vocabulary.
   → **Resolved: `terminal_reason`, shipped as §3.2 describes.**
5. **Whether the report should carry the root task's outcome or a richer
   methodology outcome.** The root task is the record's terminal and is
   already available; a new `on_execution` sink would be more direct but adds
   a handler/composition surface. I chose the existing task row and the
   read-only CLI query.
   → **Resolved: the existing task row, read read-only in `cli.py`.**

## 8. Rejected alternatives (summary)

| Option | Why rejected |
| --- | --- |
| B as the designated ref channel | It is the status quo on the successful path; it depends on the predecessor's content shape, conflates a run fact with node content, and cannot cover the EVIDENCE stage's own admission. |
| C in `external_refs` | It is the operator's input; OPS-5D refuses evidence refs there for a reason. |
| A "no evidence" sentinel envelope | A second shape and a negative state with no authority; absence is the truthful default. |
| Mark the EVIDENCE stage run `FAILED` | Refusal-as-data is a certified runtime posture; the stage run did stop cleanly, and the methodology layer already fails the chain. The report should read the failure, not rewrite the runtime. |
| Make `EVIDENCE` optional / relax the node rule | Deletes the requirement the slice exists to enforce. |
| A new `RAN_CITED_NOTHING` terminal | `FAILED` already covers it; the reason carries the distinction. |
| Change the EVIDENCE objective to "cite the ref in the envelope" | Objectives are frozen by the charter; the envelope is self-describing. The objective already names the admitted ref. |
| Treat S6-B2 as the fix | It was not reached, and it counts bookkeeping admissions; it is not evidence-specific. |
| Change the gateway to store the raw handle in the event | The canonical event is the OPS-5K contract; the reader is what needs the normalisation. |

## 9. Claim boundary

This note claims what the tree does at `d0961d0`: the measured run-19 shape
(§1.2), the successful path's predecessor content (§1.1), the OPS-5K selector
gap (§1.5), the report's terminal rule (§3.1), and the driver/handler/task
failure path (§1.3). It claims the A design and its pins, the `FAILED` +
`terminal_reason` terminal, and the rejected alternatives. It does **not**
claim that a live model will cite the ref, that A can create a ref where none
was admitted, or that the report is an authority. The record remains the
journal and the task row.

What phase 2 actually shipped, the two things the design did not name, and the
second path it found and deliberately left open are in **§10**.

## 10. Phase 2 — what shipped

| Item | Value |
| --- | --- |
| Base | `main` at `5d976d1` (the rebase onto it was a no-op) |
| Branch | `slice/ops-5l-evidence-ref-and-completion` |
| Code + tests | one commit: the envelope, the selector canonicalisation, the report terminal, `_root_task_outcomes`, `tests/test_ops5l_evidence_ref_and_completion.py` (37 tests), the widened `test_wiring_w3.py` driver-import pin |
| Docs | this section, then the suite-count stamp, then `docs/MERGE-LOG-OPS-5L.md` |

### 10.1 The rulings, as shipped

1. **A — the `runtime.evidence` envelope.** `hermes.agents.runtime.assembly
   .evidence_envelope` renders exactly `{"evidence_ref": "evidence:<id>",
   "artifact_id": "<id>"}` with origin `runtime.evidence` and ref
   `{stage_task_id}:evidence`. The live driver appends it after the project-index
   envelope and before `wiring.run`, so the assembled order is
   `runtime.task`, `runtime.project_index`, `runtime.evidence`, then the
   `runtime.payload` parts. It is **absent** while the run holds no admitted ref
   — no "none" object — and it rides every stage from the first one after the
   admission. The artifact id is derived from the ref's suffix; the driver never
   re-dereferences the artifact table.
2. **The reader gap is closed on the read side.** `_admitted_evidence_proposal`
   and `_evidence_ref_of` take an optional `canonicalise` callable; the **live
   driver** injects the research plane's `canonical_evidence_ref` (the same
   grammar OPS-5K applied at the writer). An admitted `evidence/<id>` now
   selects, and the `EVIDENCE` node stores canonical `evidence:<id>`. The
   gateway, the substrate, the `EVIDENCE` requirement and the stored event are
   untouched — the event was already canonical.
3. **The report mirrors the root methodology task.** `build_run_report` gains
   `task_outcomes` and a `terminal_reason` field. Precedence:
   `QUARANTINED` > a non-`SUCCEEDED` root task (reason = that task's latest
   `FAILED` `TaskStatusChanged` reason, or a sentence naming its state) > the
   fail-closed evidence backstop (`NO_EVIDENCE_REASON`) > `NO_STAGE_RUNS` >
   a non-`SUCCEEDED` stage run (reason names the stage and its termination) >
   `SUCCEEDED` with `""`. The CLI reads the outcome read-only on its own
   connection before closing it; a failed read returns `()` and the report falls
   back to the stage-only path. `terminal_reason` is in `_fit`'s minimal key set,
   so a truncated report never drops the field that explains the terminal. No
   new terminal value exists.
4. **The acceptance is met.** The run-19 shape — six `SUCCEEDED` stage runs, no
   admitted `EVIDENCE_TRANSITION` — cannot be reported as a success at any layer:
   at the driver (refusal), at the handler (`failed_typed`), at the task
   (`RETRYING`/`FAILED`, never `SUCCEEDED`), in the report built from stage runs
   alone (the backstop), and in the report the live CLI writes (the task's own
   reason). Four layers, one falsifier, pinned in §6 of the test file and again
   end-to-end through `hermes.cli.main`.

### 10.2 The caveat, verbatim

> A cannot create a ref. The acceptance is that **the system never calls the
> citationless run a success**, not that the model automatically succeeds.

This is exactly what shipped. Run 19's `"pending"` placeholder left no admitted
ref, so with A in place the `EVIDENCE` stage's envelope is still *absent* in that
shape — the test pins the absence — and the honest answer is the terminal, not a
new prompt object.

### 10.3 Why the envelope rides every later stage, not `EVIDENCE` only

The narrower option (append it only at `EVIDENCE`) was rejected for two reasons
that the phase-1 note had left open:

1. **The later stages are the ones that must answer to the same evidence.**
   `CLAIM` states it, `CRITIQUE` attacks it, `CONCLUSION` answers the question
   against it. A fact about the run does not stop being true at the stage that
   first reads it, so an `EVIDENCE`-only envelope would describe the run
   incorrectly from `CLAIM` onward.
2. **The `predecessor_content` channel would then silently lose the ref.** That
   field is the *previous node's* content. `CONCLUSION`'s predecessor is
   `CRITIQUE`, whose content carries no evidence position at all
   (`_default_content` gives `CRITIQUE` a `subject_ref`), so under B — or under an
   `EVIDENCE`-only A — the run's evidence ref would vanish from the last two
   prompts even though the run still holds it. A separate origin is what lets a
   reader tell "the run's admitted evidence" apart from "the previous node's
   content", and it is why the envelope is not folded into the payload.

The one-stage lag is kept and pinned rather than hidden: the stage that admits
the ref cannot see it in its own prompt, because the prompt predates the
admission and there is no re-prompt.

### 10.4 Run 19's task row: the report was the only liar

Read from the Director's artifacts (`hermes-live.db`, project
`sars-covid-19`): the root methodology task's row was **`FAILED`**, from the
`TaskStatusChanged` transitions at events **626** and **632**. The task never
said success, so for run 19 there was exactly one liar — the diagnostic report.
The diagnosis in §1.3/§3.1 stands.

One nuance the implementation surfaces rather than hides. The rule is *the
latest* `FAILED` reason, and run 19 was attempted twice: event 626 carries the
`EVIDENCE` node's substrate refusal, event 632 carries the second attempt's
model-plane failure. So a report built over run 19's own journal would name the
model-chain failure, not the empty-`external_ref` sentence. That is the approved
wording, and it is honest about which attempt the record ends on; the fresh
single-tick shape (what the tests reproduce) has one `FAILED` reason and reports
the substrate's sentence verbatim.

### 10.5 Two things the implementation added that the design did not name

1. **An empty-id guard (`_canonical_citation`).** `canonical_evidence_ref`
   maps `evidence/` to `evidence:` — it deliberately leaves the id to the
   gateway. The real gateway refuses an empty id (`MALFORMED_PAYLOAD`, OPS-5K),
   but an *injected* applier can admit `evidence:` / `evidence/`, and the ref
   would then reach `evidence_envelope`, which raises on a ref naming no
   artifact. A `ValueError` inside the stage loop is a crash, not a refusal, so
   the guard treats a canonical ref with no artifact id as **no admitted ref**:
   the run stops on the substrate's own refusal. Pinned through the real runtime
   with a granting applier, and by the guard's unit cases. The gateway's
   `EVIDENCE_REF` remains the only artifact-row check.
2. **The live driver gained one import, and the pin that makes it safe.**
   `test_wiring_w3.py`'s `DRIVER_IMPORTS` set now admits
   `hermes.research.evidence_transitions`. That widening is justified by a new
   AST pin in this slice's test file: the module imports `__future__` and `enum`
   and nothing else — no repository, no connection, no gateway — so it is
   vocabulary, not a second validation path. The existing
   "no second artifact-row check" source scan (`test_ops5d_proposal_content.py`)
   still passes and is duplicated here for the driver's new text.

Recorded, deliberately **not** changed: the methodology *plane's* own
`_admitted_evidence_proposal` default still reads colon-only. The plane's
reference/swap driver has no capability plane and never sees a handle, so
widening its default would be an unrequested behaviour change. It is pinned as
`test_the_plane_default_keeps_its_colon_only_reading` so the asymmetry is a
decision rather than an accident.

### 10.6 The latent second path — found, demonstrated, **not fixed**

Run 19 did not travel it, but it exists, and A cannot work around it:

**Shape.** Any stage run ends non-`SUCCEEDED` — a terminal model refusal, a tool
failure, a timeout — **after** an earlier stage admitted something. The driver
breaks out of the stage loop and returns a `MethodologyExecution` with
`termination` set to that stage's reason; it does not return a
`MethodologyRefusal`. The handler's only gate is the run-level admission count
(`applied == 0` → `failed_typed`, S6-B2), so a non-zero count makes it return
`completed`, and the controller transitions the root task to **`SUCCEEDED`**. The
CLI then prints `1 succeeded` over a chain that stopped early — with or without
an admitted evidence ref.

**Evidence.** Reproduced three ways: through the real `Controller` with an
`EVIDENCE` `ModelRefusal` (citationless and cited), and through the live CLI with
a `HYPOTHESIS` contract refusal. All three are in-process, scripted and offline
against the real tree — the same kind of probe §1 records, not committed; one of
them (the cited `Controller` shape) is now pinned by this slice's test file, and
the other two are the follow-up slice's starting point. In every case the stage
list is short, the admission count is non-zero, and the task row reaches
`SUCCEEDED`. Under the
OPS-5L report the same run reports `FAILED` with a reason, because the report now
reads the record and the stage states — so the diagnostic surface is honest even
where the task state is not.

**Why it is not fixed here.** Making a non-`COMPLETE` execution a `failed_typed`
is a **task-state semantics change** — it moves methodology tasks that today
succeed into `RETRYING`/`FAILED`, which is exactly the kind of change the charter
routes through its own design gate, and it is outside the approved scope of
OPS-5L (surface the ref, fix the reader, stop the false *report*). It is recorded
here, and the test that demonstrates it asserts only the report's verdict:
pinning the row as `SUCCEEDED` would freeze the defect as the contract.

**Recommended follow-up slice.** In `build_methodology_handler`, treat an
execution whose `termination != "COMPLETE"` as `failed_typed`, with the
termination and the stopping stage in the reason — the same fail-closed shape
S6-B2 already uses for a zero-admission run. It needs its own design gate because
it changes task states, the W4/W3 dispatch pins, and every test that asserts a
partial chain's completion.

### 10.7 Phase-2 gates

| Gate | Result |
| --- | --- |
| Targeted (this file + the nine chartered files, plus `test_cli.py`) | `345 passed in 30.42s`, exit 0 |
| Full suite (under the heavy-gate lock) | `5413 passed, 3 skipped in 603.47s (0:10:03)`, exit 0 (5416 collected) — fully green; the documented baseline-5 did not reproduce |
| `scripts/stamp_suite_count.py` / `--check` | `Stamped docs\SUITE-COUNT.md: collected=5416` / `OK: … collected=5416 matches the live collect` |
| `scripts/check_census.py` | `PASS - every certified figure is reproduced exactly.` (124 / 28 (19/5/4) / 1 / 15 / 0) |
| `uvx ruff check src tests scripts` | `All checks passed!` |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| pyright tests project | `0 errors, 1 warning` (pre-existing `test_research_program.py:144`) |

Two annotation-only test edits were made after the full run (the fixture's
illegal `-> Rig` return and the mixed proposal/refusal model port); the new file
and the targeted set were re-run green after them, with both pyright projects and
ruff.

License: Apache-2.0 (LICENSE).
