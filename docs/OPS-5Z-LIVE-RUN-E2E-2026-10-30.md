# End-to-end composition run — 2026-10-30

**Verdict: no.** Four live invocations of the shipped chain all stop at
`HYPOTHESIS` — stage 2 of 9 — with **one** stage recorded, **zero** fetches and
**zero** artifacts. `OBSERVATION`, `EVIDENCE`, `CLAIM`, `CRITIQUE` and
`CONCLUSION` never run. The claim gate is never called, so the run cannot
distinguish a supported claim from an unsupported one.

The pre-identified `CLAIM` subjects blocker is real and is confirmed below by
code and by a read-only call to the gate. It is not the first blocker: the
composition cannot reach it.

No code, test, configuration value or existing database row was changed to make
any run pass. The journal contains only the seeded projects and tasks plus the
controller's own attempts; the diagnostic reports are files written beside the
database.

---

## 1. Conditions of the run

| Item | Value |
| --- | --- |
| Tree | `7a35416` (`slice/ops-5z-required-statement`) plus uncommitted work present before the first run (see below) |
| Python | 3.14.1, editable install from this checkout |
| Model | `apinex:free/deepseek-v4.1-flash` for all three tiers (`s`/`m`/`c`) |
| Credential | `APINEX_API_KEY` read from the operator secrets file; never written to the report or the journal |
| Journal | `D:/New folder/e2e-20261030/hermes.db` (fresh, schema 23) |
| Artifact root | `D:/New folder/e2e-20261030/artifacts` (fresh, empty) |
| Operator workspace | `D:/New folder/e2e-20261030/`; nothing in the repository's tracked tree was edited |
| First run | `2026-10-30T18:03:21Z`; last report generated `18:06:36Z` |

**Uncommitted tree at run time.** `src/hermes/research/grounding.py`,
`src/hermes/research/inspection.py`, `tests/test_grounding_gate.py`,
`tests/test_ops5z4_falsification.py` and `docs/SUITE-COUNT.md` were already
modified when the runs started (file mtimes 21:00 local, before the first seed
at 21:03). The change is a clock-numeral exclusion (`09:50:45` must not parse
as three figures). I did not make it; the runs used the worktree as it stood.
This is an uncontrolled variable, but it does not touch the stage that failed:
the failure is in the model-proposal contract, before any figure is parsed.

The prompt's example seed line cannot run as written. `--cite evidence:<ref>`
is not `KIND=REF` (the accepted kinds are `HYPOTHESIS`, `PREDICTION`, `CLAIM`),
and the run refuses `evidence:` in `admission_refs` by design
(`_seeded_evidence_refusal`, `workflows.py:654-703`). The runs below therefore
seeded a project with no prior-art refs and let the agent attempt the fetch, as
the OPS-5D design requires.

---

## 2. The two transcripts

The pair in the same project is **Run A attempt 2** and **Run B**, both seeded
into `e2e-chain-a2-20261030`. Run A's first attempt is in its own project
because it failed before producing any evidence; it is included in §2.3 so that
nothing is hidden. The identical B rerun is there too; all four reproduce the
same first failing stage.

### 2.1 Run A — intended supported claim

Question:

> Test this hypothesis about the LIGO detection GW150914 (arXiv 1602.03837,
> DOI 10.1103/PhysRevLett.116.061102): its abstract reports initial black hole
> masses of 36 and 29 solar masses and a luminosity distance of 410 Mpc. Fetch
> the paper's abstract and state what it supports.

Seed: `meth-e2e-chain-a2-20261030`, `--max-retries 0`.
Report: `run-reports/run_20261030T1804313880610000_e2e-chain-a2-20261030.json`.

| Stage | Runtime state | Termination | Proposals | Admissions | Refusals | Node recorded? |
| --- | --- | --- | --- | --- | --- | --- |
| QUESTION | SUCCEEDED | TICK_LIMIT | 2 | 1 | 1 | yes |
| HYPOTHESIS | FAILED | MODEL_REFUSED | 0 | 0 | 2 | **no** |
| PREDICTION … CONCLUSION | — | — | — | — | — | not run |

The one QUESTION refusal is the planner proposing `REQUEST_HUMAN`, which the
gateway refuses as not wired:

```
PROPOSAL: REQUEST_HUMAN is declared but its gateway validator is not wired in
this phase (… INSERT_TASK, ADMIT_TASK) (spine code NOT_WIRED)
```

The HYPOTHESIS stage's two refusals, in order:

1. `ROLE` — the model proposed the stage name as the intent kind:

   ```
   model proposed kind 'HYPOTHESIS', outside the injected proposable allowlist
   ```

   The model's statement was a correct restatement of the figures:

   > The abstract of the GW150914 paper supports a binary black hole merger
   > consistent with the masses 36 and 29 solar masses and a luminosity
   > distance of 410 Mpc; a refuting observation would find the abstract
   > reporting different mass values, a different distance, or no black hole
   > merger at all.

2. `MALFORMED_PAYLOAD` — its fallback `INSERT_TASK` carried no statement:

   ```
   model refusal: model output proposed without a non-empty 'statement' for
   contract 'runtime_proposal_v1'; a proposal must assert what it claims
   ```

Journal row (`events.event_id = 34`):

```
PROPOSAL: methodology 'literature-review' stopped early — termination
'MODEL_REFUSED' with 1 of 9 declared stage(s) recorded; a truncated chain is
not a recorded outcome (OPS-5M) — runtime refusal MALFORMED_PAYLOAD: model
refusal: model output proposed without a non-empty 'statement' for contract
'runtime_proposal_v1'; a proposal must assert what it claims (attempts exhausted)
payload: {"refusal_code": "MALFORMED_PAYLOAD", "stage_reached": "HYPOTHESIS",
          "stages_declared": 9, "stages_recorded": 1}
```

Consequence: no `OBSERVATION` tick, no `source_search`, no `source_fetch`, no
artifact, no `CLAIM`, no gate verdict.

### 2.2 Run B — intended unsupported claim

Question, same project, same model, same config:

> Test this hypothesis about the LIGO detection GW150914 (arXiv 1602.03837,
> DOI 10.1103/PhysRevLett.116.061102): its abstract reports a total binary
> black hole mass of 100 solar masses and a luminosity distance of 410 Mpc.
> Fetch the paper's abstract and state what it supports.

Seed: `meth-e2e-chain-a2-b`, `--max-retries 0`.
Report: `run-reports/run_20261030T1805194412070000_e2e-chain-a2-20261030.json`.

| Stage | Runtime state | Termination | Proposals | Admissions | Refusals | Node recorded? |
| --- | --- | --- | --- | --- | --- | --- |
| QUESTION | SUCCEEDED | TICK_LIMIT | 2 | 1 | 1 | yes |
| HYPOTHESIS | FAILED | TOOL_FAILED | 1 | 0 | 2 | **no** |
| PREDICTION … CONCLUSION | — | — | — | — | — | not run |

The HYPOTHESIS refusals:

1. The verification-round validator refused the model's conflict kind:

   ```
   MALFORMED_PAYLOAD: round request refused: conflict.kind 'parameter_value'
   is not one of ['ATTRIBUTION', 'ORDER', 'QUANTITY']
   ```

2. The capability plane refused the model's `source_fetch` arguments:

   ```
   MALFORMED_PAYLOAD: capability plane refused 'source_fetch' with
   MALFORMED_PAYLOAD: undeclared argument(s) ['max_results'] for tool
   'source_fetch' — the input schema is closed
   ```

Journal row (`events.event_id = 51`):

```
PROPOSAL: methodology 'literature-review' stopped early — termination
'TOOL_FAILED' with 1 of 9 declared stage(s) recorded; a truncated chain is not
a recorded outcome (OPS-5M) — runtime refusal MALFORMED_PAYLOAD: capability
plane refused 'source_fetch' with MALFORMED_PAYLOAD: undeclared argument(s)
['max_results'] for tool 'source_fetch' — the input schema is closed (attempts
exhausted)
payload: {"refusal_code": "MALFORMED_PAYLOAD", "stage_reached": "HYPOTHESIS",
          "stages_declared": 9, "stages_recorded": 1}
```

The intended false figure never became a claim. The model's HYPOTHESIS
statement corrected 100 to the abstract's other mass:

> The abstract of PhysRevLett.116.061102 (GW150914) states a total binary
> black hole mass of approximately 62 solar masses and a luminosity distance
> of approximately 410 Mpc; if the abstract instead states 100 M_sun total
> mass, the 100 M_sun claim is supported.

That statement was inside a proposal the gateway refused. Even if the stage had
recorded, the run would not have produced the unsupported claim the test needs.
There is no seed field for a caller-supplied claim text; the only claim text in
the live path is the model's.

### 2.3 Reproduction attempts

| Attempt | Project / task | Stage reached | Runtime termination | Journal code | Report path |
| --- | --- | --- | --- | --- | --- |
| A1 (first) | `e2e-chain-20261030` / `meth-e2e-chain-20261030` | HYPOTHESIS | TICK_LIMIT, then substrate refusal | `MALFORMED_PAYLOAD` | `run_20261030T1803212076440000…` |
| A2 (pair) | `e2e-chain-a2-20261030` / `meth-e2e-chain-a2-20261030` | HYPOTHESIS | MODEL_REFUSED | `MALFORMED_PAYLOAD` | `run_20261030T1804313880610000…` |
| B1 (pair) | `e2e-chain-a2-20261030` / `meth-e2e-chain-a2-b` | HYPOTHESIS | TOOL_FAILED | `MALFORMED_PAYLOAD` | `run_20261030T1805194412070000…` |
| B2 (rerun) | `e2e-chain-a2-20261030` / `meth-e2e-chain-a2-b2` | HYPOTHESIS | TICK_LIMIT, then substrate refusal | `MALFORMED_PAYLOAD` | `run_20261030T1806077233970000…` |

A1 and B2 reproduce the same terminal code and detail:

```
MALFORMED_PAYLOAD: a HYPOTHESIS node is minted by the run: it needs a
non-empty 'statement' — a conjecture or claim with no asserted content is not
a chain node (attempts exhausted)
payload: {"refusal_code": "MALFORMED_PAYLOAD", "stage_reached": "HYPOTHESIS",
          "stages_declared": 9, "stages_recorded": 1}
```

They are the clearest evidence of the driver seam. In A1 the model **did** write
a correct statement, but its statement-bearing `INSERT_TASK` was refused for
invented payload keys:

```
MALFORMED_PAYLOAD: unknown payload keys: ['expected_outputs', 'provider',
'type'] — the INSERT_TASK schema is closed
```

The stage's only admitted proposal was the runtime's own review delegation
(`INSERT_TASK`, justification `delegate to critic`, no statement; the task row
is the `ADVERSARY` review child). The driver's `_stage_prose` reads admitted
proposals, found no statement, and blamed the minted node. The model's actual
sentence was never put to the gate:

> The two initial black hole masses in GW150914 are 36 and 29 solar masses, and
> the luminosity distance is 410 Mpc (36(+5/-4) M☉ and 29(+4/-4) M☉;
> D_L = 410(+160/-180) Mpc).

B2's model statement corrected 100 to 65:

> The abstract of Abbott et al. (Phys. Rev. Lett. 116, 061102) reports a total
> binary black hole mass of approximately 65 solar masses, not 100 solar
> masses as the predecessor task claims …

B2's refusals were a round payload missing its required keys
(`claims`, `conflict`, `mode`, `targets`) and two tool calls with no
`capability_id`. The model's statement-bearing proposal was refused; the review
delegation was admitted; `_stage_prose` was empty; the substrate refused the
node.

---

## 3. The artifact

There is none.

| Asked for | Result |
| --- | --- |
| ref | none — `artifacts` has 0 rows |
| size | none |
| provider | none — `provider_interactions` has 0 rows |
| `content_format` | none |
| read state | `OBSERVATION` never ran; no read was attempted |
| first 200 characters the model saw | none — the model saw the question/prompt, never source bytes |
| `retrieved_at` | none |

The artifact root contains 0 files. This is not a backfilled row and not a
replayed fixture: the chain never reached the stage that fetches. Falsifier 1
therefore fails for the plain reason that there was no fetch to be live.

---

## 4. The claim and the gate

### 4.1 In the run

No `CLAIM` stage ran. There is no claim statement, no declared subject, and no
gate verdict in any journal row. The journal can say only
`stage_reached = HYPOTHESIS`, `stages_recorded = 1`, `stages_declared = 9`.

The model-authored HYPOTHESIS statements above are not claims; they were never
passed to `check_claim`. The closest thing to a claim in the transcript is a
hypothesis that was refused before a node existed.

### 4.2 The blocker, confirmed by code

The gate needs caller-declared subjects because deriving them would require
entity recognition, i.e. a model, and the gate forbids one.

- `scripts/seed_methodology_run.py` has no subject flag and no `stage_content`
  key. `build_intent` writes only `question`, `admission_refs` and
  `external_refs` into `spec.inputs` (`:181-189`).
- The shipped `LITERATURE_REVIEW_DOCUMENT`'s `CLAIM` stage carries an
  `objective` only (`workflows.py:461-464`). The document has no
  `stage_content` at all.
- The handler maps `spec.inputs.stage_content` into `MethodologyInputs`
  (`task_handlers/__init__.py:605-620`).
- `_claim_subjects` reads `inputs.stage_content["CLAIM"]["subjects"]`
  (`methodology_driver.py:749-754`); absent, it returns `()`.
- The model's proposal has `kind`, `rationale`, `payload`, `statement`.
  `_stage_prose` reads only `statement` (`workflows.py:813-843`). There is no
  path from a proposal to `subjects`.

So the shipped path reaches `CLAIM` with `subjects=()`. The model **cannot**
author the subjects. If it could, the gate's subjects would be supplied by the
thing the gate is checking — worse than the current gap, not a fix.

### 4.3 What the gate would do

A read-only call to the same `check_claim` over the live OpenAlex abstract
(`ligo-abstract-openalex.txt`, fetched directly at 18:07Z, **not** an artifact of
the chain), using a claim shape the model could have written:

| Statement | Subjects | Verdict | Detail |
| --- | --- | --- | --- |
| The initial black hole mass is 36 solar masses. | none | `unattributed_numeral` | the claim names no subject to bind its figures to |
| The initial black hole mass is 36 solar masses. | `["black hole"]` | `grounded: true` | `""` (empty) |
| The luminosity distance is 410 Mpc. | `["luminosity distance"]` | `grounded: true` | `""` (empty) |
| The initial black hole mass is 50 solar masses. | `["black hole"]` | `assertion_not_found` | `black hole 50: no figure bound to 'black hole' in the artifact matches it` |
| The initial black hole mass is 50 solar masses. | none | `unattributed_numeral` | the claim names no subject to bind its figures to |

This is the decisive confirmation of the pre-identified blocker: **with no
subjects, a supported and an unsupported figure claim receive the same refusal
code**. The gate can discriminate only when the caller supplies subjects. The
shipped seed supplies none.

It also exposes a second condition the prompt asked for: even a `grounded`
verdict carries `detail=""`. The chain's `_grounding_token` synthesizes the word
`grounded`, but the gate's own `GroundingVerdict.detail` is empty
(`grounding.py:513`). Falsifier 4's "non-empty detail" is not met by the gate as
shipped.

### 4.4 The smallest change that clears the subjects blocker

Add a repeatable `--subject` (or `--stage-content` JSON) flag to the seeder and
write:

```python
spec["inputs"]["stage_content"] = {"CLAIM": {"subjects": list(args.subjects)}}
```

This is the one input the gate needs. It keeps the subjects caller-declared and
deterministic, and does not let the model author the thing it is being checked
against. A static subject list in the shipped workflow would be wrong for an
arbitrary question; a model-derived list would defeat the gate.

This change alone would **not** make the composition reach `CLAIM`: the chain
still stops at `HYPOTHESIS`. It is the second fix, not the first.

---

## 5. If a round opened

No round opened. `CRITIQUE` never ran, no `VERIFICATION_ROUND_OPENED` event
exists, and there is no conflict, mode, fetch, or terminal outcome to report.
The only verification-shaped text in the run is the model's attempt to propose
a round at `HYPOTHESIS` (Run B), which the round validator refused because its
`conflict.kind` was `parameter_value`.

---

## 6. Cost

| Run | Ticks | Model calls | Tokens in / out | Successful fetches | Artifacts | Wall clock |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | 2 | 6 | 17,486 / 1,628 | 0 | 0 | 18.9 s |
| A2 | 2 | 7 | 22,683 / 2,042 | 0 | 0 | 32.2 s |
| B1 | 2 | 6 | 19,198 / 1,769 | 0 | 0 | 29.2 s |
| B2 | 2 | 7 | 17,810 / 2,020 | 0 | 0 | 28.9 s |
| **Total** | **8** | **26** | **77,177 / 7,459** | **0** | **0** | **109.2 s** |

All 26 model calls are `OK` attempts at the provider. The capability ledger
records 3 attempted tool calls (A1 2, B1 1, A2/B2 0); all were refused before
egress. There are no `provider_interactions` rows.

---

## 7. Falsifiers of the run itself

| # | Falsifier | Result |
| --- | --- | --- |
| 1 | The fetch was live: `retrieved_at` is this run, not a backfilled row | **FAIL** — no fetch, no artifact, no `retrieved_at`. There is nothing to be live. |
| 2 | The model is the shipped one and its output is recorded | **PARTIAL** — the model is live `apinex:free/deepseek-v4.1-flash`, not scripted. But only *refused* proposals carry a reply excerpt in the diagnostic report. A successful proposal's statement is in-process only; the claim text is not durable. The HYPOTHESIS sentences above are visible only because the proposals were refused. |
| 3 | Run B's refusal is the gate's: `assertion_not_found` or `date_mismatch`, `source="grounding"` | **FAIL** — Run B's refusal is `MALFORMED_PAYLOAD` at `HYPOTHESIS` (capability plane: `undeclared argument(s) ['max_results']`; plus the round validator's `conflict.kind`). It is not from `grounding`; the gate was never called. |
| 4 | Run A's grounding is the gate's, `grounded: true` with a non-empty `detail` | **FAIL** — no `CLAIM` stage and no grounding. The direct gate probe grounds with `detail=""`, so even a reached gate would fail the "non-empty detail" clause. |
| 5 | Re-running Run B reproduces the same code | **PARTIAL / FAIL** — B1 ends `TOOL_FAILED` with runtime `MALFORMED_PAYLOAD` (`max_results`); B2 ends `MALFORMED_PAYLOAD` with the substrate's missing-statement detail. The code string recurs, the phase and detail do not, and the gate's code never recurs because the gate never runs. A refusal that changes phase is not a rule. |

The run is falsifiable in the ordinary sense — the model is live, the journal is
fresh, and the same commands can be repeated — but the falsifiers that were
supposed to validate the *claim gate* cannot be evaluated because the chain
never reaches it.

---

## 8. Every place the composition failed

The first failure is `HYPOTHESIS`; everything after it did not really run.

1. **HYPOTHESIS model-proposal contract (the first and blocking failure).**
   The stage needs an admitted proposal carrying a non-empty `statement`. The
   live model produced, across four runs:
   - the stage name as the intent kind (`kind: "HYPOTHESIS"`), refused `ROLE`;
   - an `INSERT_TASK` with invented payload keys
     (`expected_outputs`, `provider`, `type`), refused `MALFORMED_PAYLOAD`;
   - a `REQUEST_ADDITIONAL_EXPERIMENT` with an invalid `conflict.kind`, refused
     by the round validator;
   - a `REQUEST_ADDITIONAL_EXPERIMENT` missing required payload keys, refused;
   - `source_fetch` arguments outside the closed schema (`max_results`,
     duplicated keys, no `capability_id`), refused by the capability plane;
   - a fallback `INSERT_TASK` with no statement, refused by the contract.

   The runtime and the mesh of validators are doing their jobs. The model is not
   producing the one shape the stage requires.

2. **The review delegation is admitted as stage prose.** When the model's
   statement-bearing proposal is refused, the runtime's own review child
   (`INSERT_TASK`, `delegate to critic`, no statement) is the only admitted
   proposal. `_stage_prose` scans admitted proposals, finds no statement, and
   the substrate refuses the node with "a HYPOTHESIS node … needs a non-empty
   'statement'". The message blames the model for a statement it did write. A1
   and B2 show this exactly. The review delegation should not be a candidate for
   the stage's prose; but ignoring it would still leave the stage without a
   statement when the model's proposal is refused, so this is a truthfulness
   fix, not a cure.

3. **The QUESTION planner asked for a human.** In A2, B1 and B2 the planner
   proposed `REQUEST_HUMAN`; the gateway refused it as `NOT_WIRED`. The stage
   recovered, but it shows the model does not know which stages may fetch and
   which merely frame the question. The planner has no source tools; it read
   the question as a request for evidence it could not gather.

4. **OBSERVATION never ran.** No `source_search`, no `source_fetch`, no egress,
   no artifact, no content read. The chain's only evidence-producing stage is
   behind HYPOTHESIS, which is not passable. The five content sources and the
   five-source read layer were never exercised.

5. **CLAIM never ran, so the subjects blocker was never exercised.** The code
   gap is confirmed (§4.2) and the direct gate probe shows the exact code it
   would produce. The run cannot test it.

6. **The durable record does not contain the claim.** The journal carries the
   stage reached, the count recorded, and a refusal code — not the model's
   statement. The run report carries refused-reply excerpts, but it is
   explicitly a diagnostic artifact, not a record. A claim that passed the gate
   would leave no path to audit what was grounded. This matters for the
   deliverable's "claim — statement, subjects, verdict": two of the three are
   absent from the journal by construction.

7. **Run B's premise is not reproducible through the seed.** The model corrected
   the false 100 M☉ to 62/65 M☉ in both B attempts. There is no `--claim` or
   `--stage-content` flag to supply the claim the gate is meant to refuse, and
   supplying one would make the run a fixture/harness run, not a live-model
   claim. The negative path cannot be produced reliably by asking a question;
   the model may simply be right.

8. **Depth regressed against the one prior exercise.** The prompt records a
   previous chain that reached 6 of 9 stages. This tree records 1 of 9. The
   difference is the minted-stage contract (`requires_statement`) and the
   model's inability to satisfy it through the profile's proposable kinds.

---

## 9. The smallest changes, in order

These are proposals, not applied changes.

1. **Make the HYPOTHESIS stage's proposal shape explicit.** The contract already
   lists the proposable kinds and the statement requirement; it does not say
   that `kind` is an *intent* kind and never the stage name, nor does it show
   the minimal `INSERT_TASK` payload. One field note in `output_contract_for`
   (`run.py:422-429`) — "`kind` is one of the listed proposable kinds, not the
   stage name; a statement-bearing draft uses the declared payload fields only"
   — addresses the exact `ROLE` and payload-key refusals. It is prompt guidance;
   the validators remain the authority. If the model still cannot comply, the
   structural fix is a statement-only mint path that does not couple a stage's
   prose to an unrelated `INSERT_TASK` schema; that is a design gate, not a
   one-line change.

2. **Add caller-declared subjects to the seed.** A repeatable `--subject` flag
   writing `spec.inputs.stage_content["CLAIM"]["subjects"]` is the smallest
   change that clears the pre-identified gate blocker. It is necessary but not
   sufficient until (1) is fixed. Do not derive subjects from the claim or the
   artifact.

3. **Give a grounded verdict a detail.** `check_claim` returns
   `GroundingVerdict(grounded=True)` with `detail=""` (`grounding.py:513`).
   Naming the bound figures and subjects would satisfy the prompt's "non-empty
   detail" condition and make the grounded path auditable. This changes no
   verdict, only the record.

4. **If the negative path must be live-tested, expose the claim text as a
   caller field and label the run.** A `--claim`/`--stage-content` flag would
   make Run B reproducible, but it makes the claim caller-authored, not
   model-authored. That is a harness test of the gate, and should be labelled as
   one; it is not evidence that the live model can be made to assert a false
   figure.

---

## 10. What the tests could not have caught

Only a composition crosses these seams.

- **Scripted proposals always satisfy the contract.** The stage tests hand the
  runtime a proposal with `kind: INSERT_TASK`, a valid payload, and a statement.
  The live model proposed `kind: "HYPOTHESIS"`, invented payload keys, invented
  tool arguments, and omitted `capability_id`. No unit test exercises a model
  that has not read the closed schema.
- **Every stage test supplies `stage_content`.** The methodology-plane fixtures
  write the HYPOTHESIS/PREDICTION/CLAIM statements (and the gate tests write
  subjects) through a path the live seeder does not expose. The tests are green
  because the caller supplies exactly what the live caller cannot.
- **The gate tests pass `subjects=...`.** They prove the gate binds correctly;
  they never assert that the shipped path reaches it with a non-empty list. The
  composition is the first place the default `()` is observable.
- **The review delegation is never the only admitted proposal in a test.** The
  driver's `_stage_prose` behavior on a refused model proposal plus an admitted
  review child is not covered. A1/B2 reproduce it live.
- **The journal tests check `stage_reached` and `stages_recorded`, not the
  statement.** No test asserts that the text the gate examined is durable. The
  claim can pass or fail and leave no auditable sentence.
- **The fetch tests use fixtures or backfilled rows.** They prove the reader
  parses a captured payload; they do not prove a live model can search, fetch,
  admit, and then claim through one process. This run never got the chance.
- **The gate's success detail is not asserted.** A test can assert
  `grounded is True` and never notice that `detail` is empty. The prompt's
  falsifier 4 would fail a green gate.

---

## Appendix A — commands

```bash
# Fresh journal and artifact store
.venv/Scripts/python.exe -m hermes.cli \
  --config "D:/New folder/e2e-20261030/hermes.toml" init

# Seed Run A (attempt 2; same project as Run B)
.venv/Scripts/python.exe scripts/seed_methodology_run.py \
  --db "D:/New folder/e2e-20261030/hermes.db" \
  --project e2e-chain-a2-20261030 \
  --name "E2E Run A attempt 2" \
  --question "Test this hypothesis about the LIGO detection GW150914 ..." \
  --max-retries 0 --apply

# Seed Run B (same project)
.venv/Scripts/python.exe scripts/seed_methodology_run.py \
  --db "D:/New folder/e2e-20261030/hermes.db" \
  --project e2e-chain-a2-20261030 \
  --task-id meth-e2e-chain-a2-b \
  --question "Test this hypothesis ... total binary black hole mass of 100 solar masses ..." \
  --max-retries 0 --allow-existing-project --apply

# Run (the key is read from the environment; never written to the report)
KEY=$(cat "D:/New folder/.secrets/run40.txt")
APINEX_API_KEY="$KEY" .venv/Scripts/python.exe -m hermes.cli \
  --config "D:/New folder/e2e-20261030/hermes.toml" \
  run e2e-chain-a2-20261030 --ticks 30
```

## Appendix B — exact journal rows

```
#18 e2e-chain-20261030 meth-e2e-chain-20261030 FAILED
  MALFORMED_PAYLOAD: a HYPOTHESIS node is minted by the run: it needs a
  non-empty 'statement' — a conjecture or claim with no asserted content is not
  a chain node (attempts exhausted)
  {"refusal_code": "MALFORMED_PAYLOAD", "stage_reached": "HYPOTHESIS",
   "stages_declared": 9, "stages_recorded": 1}

#34 e2e-chain-a2-20261030 meth-e2e-chain-a2-20261030 FAILED
  PROPOSAL: ... termination 'MODEL_REFUSED' with 1 of 9 ... — runtime refusal
  MALFORMED_PAYLOAD: model refusal: model output proposed without a non-empty
  'statement' for contract 'runtime_proposal_v1'; a proposal must assert what
  it claims (attempts exhausted)
  {"refusal_code": "MALFORMED_PAYLOAD", "stage_reached": "HYPOTHESIS",
   "stages_declared": 9, "stages_recorded": 1}

#51 e2e-chain-a2-20261030 meth-e2e-chain-a2-b FAILED
  PROPOSAL: ... termination 'TOOL_FAILED' with 1 of 9 ... — runtime refusal
  MALFORMED_PAYLOAD: capability plane refused 'source_fetch' with
  MALFORMED_PAYLOAD: undeclared argument(s) ['max_results'] for tool
  'source_fetch' — the input schema is closed (attempts exhausted)
  {"refusal_code": "MALFORMED_PAYLOAD", "stage_reached": "HYPOTHESIS",
   "stages_declared": 9, "stages_recorded": 1}

#72 e2e-chain-a2-20261030 meth-e2e-chain-a2-b2 FAILED
  MALFORMED_PAYLOAD: a HYPOTHESIS node is minted by the run: it needs a
  non-empty 'statement' — a conjecture or claim with no asserted content is not
  a chain node (attempts exhausted)
  {"refusal_code": "MALFORMED_PAYLOAD", "stage_reached": "HYPOTHESIS",
   "stages_declared": 9, "stages_recorded": 1}
```

## Appendix C — raw evidence

- Journal: `D:/New folder/e2e-20261030/hermes.db`
- Artifact root: `D:/New folder/e2e-20261030/artifacts` (0 files)
- Reports: `D:/New folder/e2e-20261030/run-reports/`
- Console logs: `runA.console.log`, `runA2.console.log`, `runB.console.log`,
  `runB2.console.log`
- Direct gate probe source: `ligo-abstract-openalex.txt`
