# Verification run for `f3cf2e7` — 2026-10-30

**Answer: yes.** A `HYPOTHESIS` node was minted with a statement. The chain
passed `HYPOTHESIS` and the next prose stage, `PREDICTION`, and stopped at
`EXPERIMENT` (stage 4 of 9). The journal's decisive row is:

```
stage_reached = "EXPERIMENT"
stages_recorded = 3
stages_declared = 9
refusal_code = "MALFORMED_PAYLOAD"
```

The refusal is not `ROLE` on a stage name. The `HYPOTHESIS` stage's runtime
state is `SUCCEEDED`; its node was written (`stages_recorded` counts QUESTION,
HYPOTHESIS and PREDICTION). The fix works.

The next failure is new, and it is not the subjects gap: `EXPERIMENT` is the
first stage after the fix that still lacks the envelope sentence, and the model
again put its content in `payload` instead of `statement`. `OBSERVATION` never
ran, so `CLAIM` was never reached.

---

## 1. Conditions

| Item | Value |
| --- | --- |
| Tree | `c844cdf` — includes `f3cf2e7` (the objective change) and `af30672` (grounded detail); clean tracked tree |
| Model | `apinex:free/deepseek-v4.1-flash`, all tiers, live |
| Journal | `D:/New folder/e2e-20261030/verify-f3cf2e7/hermes.db` — fresh, schema 23 |
| Artifact root | `D:/New folder/e2e-20261030/verify-f3cf2e7/artifacts` — fresh, empty |
| Run | `2026-10-30T19:00:36Z` → `19:02:29Z` |
| Question | The exact Run A attempt 2 question from the four failing runs |
| Seed | Fresh project `verify-f3cf2e7-a`, `--max-retries 0` (the four failing runs used 0; the objective, profiles and seeder code are unchanged) |
| Ticks | 2 (bounded at 30) |

The seeded `HYPOTHESIS` objective was checked in the task row before the run and
contains the new sentence:

> Emit one proposal whose `kind` is an intent kind — `INSERT_TASK`,
> `PROPOSE_RESEARCH_PROGRAM` or `REQUEST_HUMAN` — and never the stage name; put
> your sentence in `statement` and leave `payload` empty.

The seeder did not change: `spec.inputs` still has only `question`,
`admission_refs` and `external_refs`; there is no `stage_content`, so this run
does not touch the subjects gap. Nothing was changed between this run and the
four failing runs except `f3cf2e7` (and the already-committed `af30672`, which
only affects a grounded verdict's detail; the chain never reaches `CLAIM`).

---

## 2. The decision, from the journal

`events.event_id = 24`:

```
PROPOSAL: methodology 'literature-review' stopped early — termination
'MODEL_REFUSED' with 3 of 9 declared stage(s) recorded; a truncated chain is
not a recorded outcome (OPS-5M) — runtime refusal MALFORMED_PAYLOAD: model
refusal: model output proposed without a non-empty 'statement' for contract
'runtime_proposal_v1'; a proposal must assert what it claims (attempts exhausted)

payload: {"refusal_code": "MALFORMED_PAYLOAD",
          "stage_reached": "EXPERIMENT",
          "stages_declared": 9,
          "stages_recorded": 3}
```

The first row of the pre-stated decision table applies: `stage_reached` is past
`HYPOTHESIS`, and a `HYPOTHESIS` node was minted. The new failure is at
`EXPERIMENT`, not a repeat at `HYPOTHESIS`.

---

## 3. Stage trace

| Stage | Runtime state | Termination | Proposals | Admissions | Refusals | Node recorded? |
| --- | --- | --- | --- | --- | --- | --- |
| QUESTION | SUCCEEDED | STOP_WHEN | 2 | 2 | 0 | yes |
| HYPOTHESIS | SUCCEEDED | STOP_WHEN | 2 | 2 | 1 | **yes** |
| PREDICTION | SUCCEEDED | PROPOSAL_LIMIT | 2 | 2 | 1 | yes |
| EXPERIMENT | FAILED | MODEL_REFUSED | 0 | 0 | 2 | **no** |
| OBSERVATION … CONCLUSION | — | — | — | — | — | not run |

`stages_recorded = 3` is the durable count: QUESTION, HYPOTHESIS, PREDICTION.
The HYPOTHESIS stage's `SUCCEEDED` state and the count are both independent of
the refused first attempt; a node exists only if `_stage_prose` found an
admitted statement. The stage's admissions (2) are the model's admitted
`INSERT_TASK` (journal event #15, `proposed_by = RESEARCHER`, justification
"The stage requires formulating a testable hypothesis …") and the runtime's
review delegation (event #17, `delegate to critic`, no statement). The review
delegation is not the prose source: the node minted, so the model's admitted
proposal carried the statement.

`PREDICTION` passed the same way: one model `INSERT_TASK` admission (event #20)
plus the review delegation (event #22), and its node was recorded.

`EXPERIMENT` did not produce an admitted proposal; its two replies are in §5.

---

## 4. The raw HYPOTHESIS reply

**The runtime does not retain the raw reply for an admitted proposal.** The
diagnostic report retains a reply excerpt only when a proposal is refused. The
exact JSON below is the **first** HYPOTHESIS attempt, which the runtime refused
for a missing `rationale`; it is the only HYPOTHESIS raw reply the record
contains. It answers the whole question — the model wrote
`"kind":"INSERT_TASK"` — and it shows the sentence where the objective asked
for it:

```json
{"kind":"INSERT_TASK","statement":"The abstract of PhysRevLett.116.061102 reports initial black hole masses of 36 and 29 solar masses and a luminosity distance of approximately 410 Mpc, supporting the binary black hole merger interpretation with a radiated energy of ~3 solar masses.","payload":{"spec":{"objective":"Fetch the arXiv 1602.03837 / PRL 116, 061102 abstract and verify the stated masses and distance.","methods":["source_fetch from arXiv abstract page and/or publisher landing"],"inputs":["arxiv:1602.03837","doi:10.1103/PhysRevLett.116.061102"],"outputs":["verified abstract","mass/distance extraction"]},"task_type":"TOOL_TASK","provenance":["arXiv:1602.03837","DOI:10.1103/PhysRevLett.116.061102"],"inputs":["arXiv:1602.03837"],"outputs":["abstract","masses","distance"]}}
```

Refusal detail:

```
model refusal: model output omitted required field 'rationale' for contract
'runtime_proposal_v1'
```

The second HYPOTHESIS attempt was admitted (journal event #15, `INSERT_TASK`,
`proposed_by = RESEARCHER`) and the node was minted; its raw JSON is not
retained. The journal's intent kind and the node's existence are the evidence
that the admitted proposal was statement-bearing. This is a recordkeeping gap,
not a contradiction: the refused first reply proves the model follows the
envelope sentence; the admitted second reply proves the stage accepts it.

Two details of the raw reply are worth naming:

- The model did **not** leave `payload` empty. It put a task spec there. The
  objective said "leave `payload` empty"; the refusal was for the missing
  `rationale`, not for the payload. The essential part of the sentence — an
  intent kind and a `statement` — was followed.
- The first attempt still needed a second pass for `rationale`. The fix makes
  the envelope legible; it does not make the model's first draft valid on every
  field.

---

## 5. Where it stops now: EXPERIMENT

`EXPERIMENT` is the first stage after the fix that fails. Its objective was not
changed by `f3cf2e7`; it still says only:

> Describe the test that would discriminate between the hypothesis and the
> observation that would refute it.

The runtime requires the test in the top-level `statement` (mapped to the node's
`test`), and refuses a reply without one. The model put the test inside
`payload.claims` / `payload.conflict` / `payload.targets`, not in `statement`.
Both EXPERIMENT replies are retained because both were refused.

**First EXPERIMENT reply (exact JSON):**

```json
{"kind":"REQUEST_ADDITIONAL_EXPERIMENT","rationale":"The task requires fetching the paper's abstract to verify reported masses and distance against the prediction; the only available capability is source_fetch.","payload":{"claims":[{"ref":"prediction","statement":"The paper's abstract reports initial black hole masses of 36 and 29 solar masses and a luminosity distance of 410 Mpc.","source_ref":"predecessor_content"},{"ref":"observation","statement":"The paper's abstract reports different masses or distance, or uncertainty intervals indicating systematics dominate.","source_ref":"predecessor_content"}],"conflict":{"kind":"verification","left":"prediction","right":"observation","subject":"GW150914 abstract reported values","date":"2024-01-01","detail":"Prediction states abstract values; observation states they differ or uncertainties dominate"},"mode":"verify-one","targets":[{"claim_ref":"prediction","provider":"arXiv","url":"https://arxiv.org/abs/1602.03837"}]}}
```

**Second EXPERIMENT reply (exact JSON):**

```json
{"kind":"REQUEST_ADDITIONAL_EXPERIMENT","rationale":"The hypothesis asserts specific values in the GW150914 abstract (36 and 29 solar masses, 410 Mpc luminosity distance); the objective asks for the discriminating test, which is an independent fetch of the paper's abstract to confirm or refute those figures.","payload":{"claims":[{"ref":"claim_support","statement":"The GW150914 abstract reports initial black hole masses of 36 and 29 solar masses and a luminosity distance of 410 Mpc.","source_ref":"arXiv 1602.03837"},{"ref":"claim_refute","statement":"The GW150914 abstract does not report initial black hole masses of 36 and 29 solar masses or a luminosity distance of 410 Mpc.","source_ref":"arXiv 1602.03837"}],"conflict":{"kind":"numeric_discrepancy","left":"claim_support","right":"claim_refute","subject":"GW150914 abstract reported masses and distance","date":"2016-02-11","detail":"Abstract values 36/29 solar masses and 410 Mpc either match or materially differ from the paper's actual text."},"mode":"verify-one","targets":[{"claim_ref":"claim_support","provider":"arXiv","url":"https://arxiv.org/abs/1602.03837"}]}}
```

Both are refused with:

```
MALFORMED_PAYLOAD: model refusal: model output proposed without a non-empty
'statement' for contract 'runtime_proposal_v1'; a proposal must assert what it
claims
```

The second reply also carries `conflict.kind = "numeric_discrepancy"`, not in
the round validator's allowed set (`ATTRIBUTION`, `ORDER`, `QUANTITY`); the
statement refusal is reached first. The model is not failing for lack of a
rationale or because it used the stage name as the kind. It used a legal
intent kind (`REQUEST_ADDITIONAL_EXPERIMENT`) and put its prose one level too
deep.

This is **not** the subjects gap. `OBSERVATION` never ran; no fetch, no
artifact, no `CLAIM`. The subjects gap remains downstream and untested.

---

## 6. Proposal ledger

| Stage | Proposals | Admitted | Refused | What the admitted proposals were |
| --- | --- | --- | --- | --- |
| QUESTION | 2 | 2 | 0 | model `INSERT_TASK` + review delegation |
| HYPOTHESIS | 2 | 2 | 1 | model `INSERT_TASK` (#15) + review delegation (#17); first model reply refused for missing `rationale` |
| PREDICTION | 2 | 2 | 1 | model `INSERT_TASK` (#20) + review delegation (#22); first model reply refused for unknown top-level keys `['max_retries', 'task_type']` |
| EXPERIMENT | 0 | 0 | 2 | both replies refused before they became proposals: no top-level `statement` |

The HYPOTHESIS refusal's exact code/detail:

```
MALFORMED_PAYLOAD: model refusal: model output omitted required field
'rationale' for contract 'runtime_proposal_v1'
```

The PREDICTION refusal's exact code/detail:

```
MALFORMED_PAYLOAD: model refusal: model output carried unknown key(s)
['max_retries', 'task_type'] for contract 'runtime_proposal_v1'
```

Both stages recovered on the next attempt, which is what the runtime's bounded
re-prompt is for. EXPERIMENT had two attempts and neither carried a top-level
statement.

`proposals` counts drafts that reached the proposal set; a model-plane contract
refusal is counted in `refusals` but not in `proposals`. That is why HYPOTHESIS
reads 2/2/1 and EXPERIMENT reads 0/0/2: the missing-rationale and missing-
statement replies were refused before a draft existed, while the admitted
second replies became proposals.

---

## 7. Cost

| Metric | Value |
| --- | --- |
| Ticks | 2 |
| Model calls | 26 |
| Tokens in / out | 82,322 / 6,475 |
| Capability invocations | 1 attempted, 0 egress rows |
| Successful fetches | 0 |
| Artifacts | 0 |
| Wall clock | 113.2 s |
| Terminal | `FAILED` — `MODEL_REFUSED` at `EXPERIMENT`, 3/9 recorded |

The console shows 20 model-call rows plus "6 more"; the diagnostic report lists
all 26. The single capability invocation is counted by `M2(calls=1)` and left
no `provider_interactions` row; no bytes were fetched.

---

## 8. What this run establishes

1. **The fix works.** A live model, given the envelope sentence in the
   HYPOTHESIS objective, emitted `"kind":"INSERT_TASK"` with a `statement`; the
   proposal was admitted and a HYPOTHESIS node was minted. `PREDICTION`, which
   got the same sentence, also minted. The chain reached `EXPERIMENT`
   (`stages_recorded = 3`), two stages further than the four failing runs.
2. **The next failure is a coverage gap, not a reason to rewrite the
   HYPOTHESIS objective.** `EXPERIMENT` is a prose stage (`test` is its content
   key) that `f3cf2e7` did not touch. It asks for "the test" without saying
   where it goes; the model put it in `payload` and was refused. The same
   sentence, applied to `EXPERIMENT`, is the smallest next experiment.
3. **The structural argument still stands.** Every prose stage currently
   depends on the model constructing an intent envelope around a sentence.
   HYPOTHESIS and PREDICTION now succeed because the objective repeats the
   envelope at the point of use; EXPERIMENT shows what happens one stage later
   without it. The durable fix is a statement-only path for a stage whose job is
   "say one sentence", so the envelope does not have to be re-stated in every
   objective. That is a design gate, not another prose round on HYPOTHESIS.
4. **The admitted raw reply is not retained.** The journal proves the kind and
   the node's existence; the diagnostic report retains the refused first
   reply only. If the exact admitted JSON is required as evidence, the runtime
   needs a bounded admitted-reply excerpt (or the proposal ledger) at the run
   boundary. Right now the evidence for "the model wrote the right envelope"
   is a refused sibling plus the journal's intent kind, not the admitted bytes.
5. **The subjects gap is untouched.** `OBSERVATION` never ran; `CLAIM` never
   ran; no subjects were supplied or needed. The next slice's work remains the
   same, but it is now two stages further away.

---

## Appendix A — commands

```bash
.venv/Scripts/python.exe -m hermes.cli \
  --config "D:/New folder/e2e-20261030/verify-f3cf2e7/hermes.toml" init

.venv/Scripts/python.exe scripts/seed_methodology_run.py \
  --db "D:/New folder/e2e-20261030/verify-f3cf2e7/hermes.db" \
  --project verify-f3cf2e7-a \
  --name "Verify f3cf2e7 A" \
  --question "Test this hypothesis about the LIGO detection GW150914 (arXiv 1602.03837, DOI 10.1103/PhysRevLett.116.061102): its abstract reports initial black hole masses of 36 and 29 solar masses and a luminosity distance of 410 Mpc. Fetch the paper's abstract and state what it supports." \
  --max-retries 0 --apply

KEY=$(cat "D:/New folder/.secrets/run40.txt")
APINEX_API_KEY="$KEY" .venv/Scripts/python.exe -m hermes.cli \
  --config "D:/New folder/e2e-20261030/verify-f3cf2e7/hermes.toml" \
  run verify-f3cf2e7-a --ticks 30
```

## Appendix B — raw evidence

- Journal: `D:/New folder/e2e-20261030/verify-f3cf2e7/hermes.db`
- Diagnostic report:
  `D:/New folder/e2e-20261030/verify-f3cf2e7/run-reports/run_20261030T1900366279170000_verify-f3cf2e7-a.json`
- Console: `D:/New folder/e2e-20261030/verify-f3cf2e7/run.console.log`
- Artifact root: `D:/New folder/e2e-20261030/verify-f3cf2e7/artifacts` (0 files)
