# Depth baseline — 2026-10-27

The first measured answer to a question that had only been assumed: **how far
does a Hermes run actually get, and what stops it?**

Read-only, taken against `D:/New folder/hermes-live.db` after 43 projects. It is
a baseline, not a verdict on the design — the next live run gets compared
against these numbers.

Regenerate with:

```bash
python scripts/depth_report.py --db "D:/New folder/hermes-live.db"
python scripts/depth_report.py --db ... --project sars-covid-30
python scripts/depth_report.py --db ... --json
```

The tool opens the journal with `mode=ro`, so it can be run against a database
while a run is in flight. Two runs over the same file produce identical bytes.

## The three findings

**1. The chain has never passed stage 3 of 9.** The deepest recorded stage
anywhere is `PREDICTION`, reached in `sars-covid-30` and `sars-covid-31`.
`EXPERIMENT`, `OBSERVATION`, `EVIDENCE`, `CLAIM`, `CRITIQUE` and `CONCLUSION`
have never executed once. `research_claims`, `evidence_ladder_state` and
`validation_verdicts` are all empty — not "zero failures", empty.

**2. Thirteen runs report `completed` with zero substantive admissions.**
`IntentApplied` splits into 190 `INSERT_TASK` and 80 `ADMIT_TASK` — and nothing
else, ever. The completion gate (`_zero_admission_reason`, S6-B2) sums
`intents_applied`, and `_admission_tally` counts every `ADMITTED` proposal
regardless of kind. An admitted task insertion therefore satisfies a gate whose
name says a run must not be "effectless". This is audit finding F3 generalised:
it was reported as *the reviewer's* `INSERT_TASK` counting as the stage's work;
the record shows it is *any* task insert, and it is the dominant path — 270 of
270 applied intents are bookkeeping.

**3. A rejection is recorded without a reason.** All 156 `IntentRejected`
events carry the same `reason` string, `"intent rejected"`, and a payload of
`{intent_kind, justification, project_id, proposed_by}` — no refusal code, no
validator message, no hazard class. 68 of those rejections are
`EVIDENCE_TRANSITION`, which is the substantive research act. The project's
governing principle is refusal-as-data; at the journal boundary a refusal is
currently a sentence.

## What the instrument cannot know

Stage progression is **not a field**. It appears only as prose inside a failure
reason (`... with 3 of 9 declared stage(s) recorded`), so only 3 of 43 projects
carry a parseable depth; the other 40 failed before emitting a stage count at
all. The `DEPTH` table marks every row accordingly and the `FAILURES` section is
labelled `prose`. No depth in this document is inferred — an unparseable run is
reported as `unrecorded`, never guessed.

## What this changes about the plan

OPS-5X (F2 / F3 / F11) bites on a run that *reaches a review*. No run has ever
reached a review, so it is not the next blocker. The evidence points at two
gates upstream of it:

- **The completion gate accepts bookkeeping as work.** Narrowing it to
  substantive admissions is a small, testable change, and it would have failed
  13 of the 13 runs that reported success.
- **The journal cannot say why an intent was refused.** Without a refusal code
  on `IntentRejected`, the question "why did the researcher's evidence proposal
  not land" is unanswerable from the record — which is why the failure census
  below had to be parsed out of prose.

## The report, verbatim

```text
DEPTH REPORT — all projects
==============================================================================

VERDICT
  deepest stage ever recorded   PREDICTION (3 of 9) in sars-covid-30
  depth known for               3/43 projects
  runs reporting 'completed'    13
  claims recorded               0
  admissions: substantive       0   bookkeeping 270

CENSUS
  projects            43
  lifecycle           {'CREATED': 43}
  events              1006
  event types         {'CapabilityPlaneComposed': 30, 'IntentApplied': 270, 'IntentRejected': 156, 'ResearchCreated': 43, 'TaskCreated': 269, 'TaskStatusChanged': 238}
  tasks               {'CANCELLED': 37, 'FAILED': 30, 'PENDING': 189, 'SUCCEEDED': 13}
  task profiles       {'<null>': 80, 'ADVERSARY': 92, 'DIRECTOR': 1, 'RESEARCHER': 96}
  applied intents     {'ADMIT_TASK': 80, 'INSERT_TASK': 190}
  rejected intents    {'BRANCH': 1, 'EVIDENCE_TRANSITION': 68, 'INSERT_TASK': 54, 'PROPOSE_RESEARCH_PROGRAM': 4, 'REQUEST_ADDITIONAL_EXPERIMENT': 16, 'REQUEST_HUMAN': 12, 'REQUEST_REPLICATION': 1}
  rejected by         {'ADVERSARY': 91, 'DIRECTOR': 26, 'IMPLEMENTER': 23, 'RESEARCHER': 16}
  artifacts           {'source_payload': 4}

SUBSTANCE — the tables a research result would land in
  research_claims          0
  evidence_ladder_state    0
  validation_verdicts      0
  research_programs        0

DEPTH — deepest recorded stage per project (prose-derived)
  3/43 projects carry a parseable stage count

  project            stage         n  claims tasks
  diag-1             unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  diag-2             unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  diag-3             unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  probe-apinex       unrecorded    -  no     {'FAILED': 1, 'PENDING': 3}
  sars-covid         unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  sars-covid-10      unrecorded    -  no     {'CANCELLED': 1, 'PENDING': 10, 'SUCCEEDED': 1}
  sars-covid-11      unrecorded    -  no     {'CANCELLED': 1, 'PENDING': 10, 'SUCCEEDED': 1}
  sars-covid-12      unrecorded    -  no     {'CANCELLED': 1, 'PENDING': 9, 'SUCCEEDED': 1}
  sars-covid-13      unrecorded    -  no     {'CANCELLED': 1, 'PENDING': 9, 'SUCCEEDED': 1}
  sars-covid-14      unrecorded    -  no     {'CANCELLED': 1, 'FAILED': 1, 'PENDING': 11}
  sars-covid-15      unrecorded    -  no     {'CANCELLED': 1, 'PENDING': 9, 'SUCCEEDED': 1}
  sars-covid-16      unrecorded    -  no     {'CANCELLED': 1, 'PENDING': 9, 'SUCCEEDED': 1}
  sars-covid-17      unrecorded    -  no     {'CANCELLED': 1, 'PENDING': 8, 'SUCCEEDED': 1}
  sars-covid-18      unrecorded    -  no     {'CANCELLED': 2, 'PENDING': 6, 'SUCCEEDED': 1}
  sars-covid-19      unrecorded    -  no     {'CANCELLED': 2, 'FAILED': 1, 'PENDING': 7}
  sars-covid-2       unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  sars-covid-20      unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  sars-covid-21      unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  sars-covid-22      unrecorded    -  no     {'CANCELLED': 1, 'PENDING': 5, 'SUCCEEDED': 1}
  sars-covid-23      unrecorded    -  no     {'CANCELLED': 1, 'FAILED': 1, 'PENDING': 3}
  sars-covid-24      unrecorded    -  no     {'CANCELLED': 1, 'FAILED': 1, 'PENDING': 5}
  sars-covid-25      unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  sars-covid-26      unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  sars-covid-27      unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  sars-covid-28      unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  sars-covid-29      unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  sars-covid-3       unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}
  sars-covid-30      PREDICTION    3  no     {'CANCELLED': 2, 'FAILED': 1, 'PENDING': 7}
  sars-covid-31      PREDICTION    3  no     {'CANCELLED': 3, 'FAILED': 1, 'PENDING': 7}
  sars-covid-32      unrecorded    -  no     {'CANCELLED': 1, 'FAILED': 1, 'PENDING': 5}
  sars-covid-33      HYPOTHESIS    2  no     {'CANCELLED': 2, 'FAILED': 1, 'PENDING': 3}
  sars-covid-34      unrecorded    -  no     {'CANCELLED': 1, 'FAILED': 1, 'PENDING': 5}
  sars-covid-35      unrecorded    -  no     {'CANCELLED': 1, 'FAILED': 1, 'PENDING': 3}
  sars-covid-36      unrecorded    -  no     {'CANCELLED': 1, 'FAILED': 1, 'PENDING': 5}
  sars-covid-37      unrecorded    -  no     {'CANCELLED': 1, 'FAILED': 1, 'PENDING': 3}
  sars-covid-4       unrecorded    -  no     {'CANCELLED': 3, 'FAILED': 1, 'PENDING': 3}
  sars-covid-5       unrecorded    -  no     {'CANCELLED': 1, 'PENDING': 2, 'SUCCEEDED': 1}
  sars-covid-6       unrecorded    -  no     {'CANCELLED': 2, 'FAILED': 1, 'PENDING': 3}
  sars-covid-7       unrecorded    -  no     {'CANCELLED': 1, 'PENDING': 5, 'SUCCEEDED': 1}
  sars-covid-8       unrecorded    -  no     {'CANCELLED': 1, 'PENDING': 8, 'SUCCEEDED': 1}
  sars-covid-9       unrecorded    -  no     {'CANCELLED': 1, 'PENDING': 9, 'SUCCEEDED': 1}
  sars-covid-trace35 unrecorded    -  no     {'CANCELLED': 1, 'FAILED': 1, 'PENDING': 3}
  sars-covid-trace36 unrecorded    -  no     {'FAILED': 1, 'PENDING': 1}

  deepest anywhere: PREDICTION (3 of 9) in sars-covid-30

FAILURES — prose — parsed from TaskStatusChanged.reason, not a typed field
   37 #######................. OTHER:superseded by new sequencer pass
      first 2026-10-24T18:56:28.875184+00:00  last 2026-10-27T15:59:46.932204+00:00
      e.g. superseded by new sequencer pass
   24 ####.................... OTHER:retry scheduled
      first 2026-10-24T13:11:46.397738+00:00  last 2026-10-27T09:48:42.647157+00:00
      e.g. retry scheduled
   18 ###..................... EFFECTLESS_RUN:admissions=0
      first 2026-10-24T13:11:46.396091+00:00  last 2026-10-27T12:42:18.577275+00:00
      e.g. PROPOSAL: methodology completed with 0 admissions via apply_intent — an effectless run is not a recorded outcome (S6-B2)
   16 ###..................... MODEL_CHAIN_EXHAUSTED
      first 2026-10-24T15:24:47.000616+00:00  last 2026-10-27T15:59:46.928733+00:00
      e.g. handler 'methodology_run' failed: every candidate model in the fallback chain failed
   13 ##...................... OTHER:handler 'methodology_run' completed
      first 2026-10-24T19:57:13.565421+00:00  last 2026-10-26T17:31:44.313994+00:00
      e.g. handler 'methodology_run' completed
    8 ##...................... MALFORMED_PAYLOAD:HYPOTHESIS cites existing artifact
      first 2026-10-24T15:21:37.523566+00:00  last 2026-10-25T04:42:56.634811+00:00
      e.g. MALFORMED_PAYLOAD: a HYPOTHESIS node cites an existing artifact: it needs a non-empty 'external_ref' — an existing-kind node is never minted here, only cited
    4 #....................... MALFORMED_PAYLOAD:EVIDENCE cites existing artifact
      first 2026-10-25T20:01:40.570958+00:00  last 2026-10-27T07:01:58.547813+00:00
      e.g. MALFORMED_PAYLOAD: a EVIDENCE node cites an existing artifact: it needs a non-empty 'external_ref' — an existing-kind node is never minted here, only cited (att
    4 #....................... TRUNCATED_CHAIN:MODEL_REFUSED
      first 2026-10-26T20:26:41.203244+00:00  last 2026-10-27T09:48:42.645142+00:00
      e.g. PROPOSAL: methodology 'literature-review' stopped early — termination 'MODEL_REFUSED' with 3 of 9 declared stage(s) recorded; a truncated chain is not a recorde
    3 #....................... TRUNCATED_CHAIN:TOOL_FAILED
      first 2026-10-26T20:26:57.798690+00:00  last 2026-10-26T20:27:44.385470+00:00
      e.g. PROPOSAL: methodology 'literature-review' stopped early — termination 'TOOL_FAILED' with 1 of 9 declared stage(s) recorded; a truncated chain is not a recorded 
    1 ........................ EVIDENCE_UNRESOLVED
      first 2026-10-26T12:41:47.302906+00:00  last 2026-10-26T12:41:47.302906+00:00
      e.g. EVIDENCE_DOES_NOT_RESOLVE: ref 'hypothesis:probe/h1' does not resolve in project 'probe-apinex' — no admitted artifact carries it (attempts exhausted)

FRONTIER — work declared and never done
  pending             189
  blocked by deps     12
       43 <null>
       92 ADVERSARY / AGENT_TASK
        1 DIRECTOR / SUBGRAPH
       45 RESEARCHER / AGENT_TASK
        1 RESEARCHER / SUBGRAPH
        7 RESEARCHER / TOOL_TASK
  cancelled reasons   {'superseded by new sequencer pass': 37}

GAPS — what this record cannot answer
  rejections with a diagnostic reason: 0/156
  stage progression recorded as data: NO
  A rejection records that an intent was refused, not why: no refusal code and no validator message reach the journal. Stage progression is not a field at all — it appears only as prose inside a failure reason, so depth below is prose-derived and every row says so.
```

---

# Run 38 — a controlled attempt, and what it proved

One fresh project (`sars-covid-38`), seeded through `apply_intent` with the same
nine-stage methodology and the same question as the last run, on the one
provider that answers reliably (`apinex:free/deepseek-v4.1-flash`). The only
deliberate difference from the historical runs: `admission_refs` and
`external_refs` were left **empty** instead of pre-seeded with prior art.

## What the provider did

It worked. **12 model calls, 12 OK**, no refusals, no empty completions, no
retry walk: `in 1535–2954, out 82–823`. The provider that has been blamed for
most of this session's failures carried the run without a single transport
error.

## What actually happened

```
Ran 4 tick(s) for project sars-covid-38: 3 dispatched, 0 succeeded,
    0 waiting on human, 1 failed, 9 unhandled.
poison task quarantined: task 'meth-sars-covid-38' failed 3x
    (last: "MALFORMED_PAYLOAD: a HYPOTHESIS node cites an existing
     artifact: it needs a non-empty 'external_ref'")
```

Three attempts, identical failure, then quarantine. The run report shows
`QUESTION` and `HYPOTHESIS` both `SUCCEEDED` at the model level — the failure is
in the **chain write**, not in the model's reply. Depth reached **HYPOTHESIS
(2 of 9)**, one stage *shallower* than the historical best.

## Why — and this is the finding

`REFERENCED_NODE_KINDS = {HYPOTHESIS, PREDICTION, EVIDENCE, CLAIM}`
(`methodology/substrate.py:153`). Those four are **citations**: "an existing-kind
node is never minted here, only cited" (`:871`). A fresh project has nothing to
cite, so the node is written with `external_ref: ""` and the substrate refuses.

`_default_content` says so in its own docstring
(`methodology/workflows.py:735-742`):

> The prior-art positions (`HYPOTHESIS`, `PREDICTION`, `CLAIM`'s own identity)
> still read `inputs.external_refs`; **they have no producer in this build** and
> are labelled in the node rationale.

Nothing in `src/` ever creates a `hypothesis:` ref. The previous best run
reached `PREDICTION` only because its task inputs were hand-seeded with
`hypothesis:prior-art-sars35/h1` — prior art that does not exist. The one run
that got as far as `EVIDENCE_DOES_NOT_RESOLVE` died for exactly that reason:
"no admitted artifact carries it".

## What this means

**The depth did not change, and the cause is structural.** The chain cannot pass
stage 2 on a fresh project by construction, independent of provider, model,
output budget, or the review machinery:

- not the provider — 12/12 calls succeeded;
- not the budget — OPS-5W's floor is inert on this gateway anyway;
- not OPS-5X — the run never reached a review.

The methodology as built is **not bootstrappable**. Four of its nine stages
consume prior art that no component produces, so every run so far has either
failed at `HYPOTHESIS` (unseeded) or failed at the fabricated citation (seeded).

## The instrument's own gap, demonstrated

The report cannot say "stage 2" for this run: the refusal is `MALFORMED_PAYLOAD`,
which carries no stage count, so the project reads `unrecorded` even though the
run report knows the stage names. This is the second reason to put a stage field
on the record rather than a sentence.
