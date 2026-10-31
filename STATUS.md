# STATUS — 2026-10-31

**3 of 9 methodology stages run live.** A live run recorded QUESTION, HYPOTHESIS and PREDICTION and stopped at
EXPERIMENT with **zero fetches and zero artifacts**. Every number below was measured on this tree today, or by
the run named at the foot of the page. Nothing here is a plan.

## 1. What runs

```
live methodology chain     3 of 9 stages  QUESTION → HYPOTHESIS → PREDICTION → stops at EXPERIMENT
                           zero fetches, zero artifacts in a live run
                           2 ticks · 26 model calls · 82,322 tokens in / 6,475 out · 113.2 s wall
                           1 capability invocation attempted, 0 egress rows, artifact root 0 files
                           terminal FAILED — MODEL_REFUSED, refusal_code MALFORMED_PAYLOAD
                           live model apinex:free/deepseek-v4.1-flash, fresh journal, schema 23

claim gate                 grounds a verbatim quotation; grounded=True and a non-empty detail naming
                           figure, subject and date:
                           "the artifact states Brazil 100 on 2020-09-01, bound to the subjects the
                           claim names"
                           refuses a false figure: refusal=ASSERTION_NOT_FOUND, detail carries the
                           subject and the figure ("Brazil 500: …")
                           refuses a figure with no subject: refusal=UNATTRIBUTED_NUMERAL
                           (re-measured today against grounding.check_claim, :424)

content states             content / fallback / unreadable (capabilities/content.py:84)
                           seven declared provider formats (:102-108)
                           eight captured responses pinned under tests/fixtures/source_payloads/, with
                           capture_manifest.json (hermes-capture-manifest/v1, captured 2026-10-30):
                           six manifest records over crossref, arxiv, inspirehep, semantic-scholar and
                           europepmc — the five new sources — beside the real 1,260-character OpenAlex
                           record and the 5,590-byte PubMed cookie wall, which are pinned without a
                           manifest record of their own

verification round         wired, bounded to one round per claim; opens on a scan conflict
                           the spine executes it under the RESEARCHER grant
                           (task_handlers/__init__.py:360 → verification.run_round, :572); the round
                           id is a hash of the claim refs and the disputed question, and the gateway
                           refuses a second round for the same claim
```

The chain's recovery is measured too. HYPOTHESIS and PREDICTION each needed a second attempt — the first was
refused for a missing `rationale`, and for unknown top-level keys `max_retries`/`task_type`. The envelope
sentence in the stage objective is what makes the stage pass; it does not make the model's first draft valid.

## 2. Built, tested, and never reached by a live run

Everything here is unit-tested and pinned, and none of it has been exercised by a run that fetched:

- the claim gate **inside the chain** — `check_claim` is called on the CLAIM stage
  (`task_handlers/methodology_driver.py:831`). CLAIM is stage 7 of 9; the chain stops at 4.
- **content states on a fetched artifact** — the five new readers are proven against captured bytes. A live
  run writes no artifact, so `content` / `fallback` / `unreadable` has never classified a live response.
- **the verification round** — wired and bounded, but the stage that would open it is EXPERIMENT, where the
  run dies. No round has ever opened live.
- **the conclusion** — CRITIQUE and CONCLUSION (stages 8-9) have never been entered by a live run.
- **the five new content sources** — read and pinned, and not selectable live (§3).
- **replay-level refusals** — the PubMed cookie wall is refused with `NON_CONTENT_PAYLOAD` before an artifact
  exists, proven in recorded replay. Replay proves byte determinism, never validity.

## 3. What is known broken

```
the chain stops at EXPERIMENT      MALFORMED_PAYLOAD — "model output proposed without a non-empty
                                    'statement' for contract 'runtime_proposal_v1'". The stage objective
                                    does not state the proposal envelope (methodology/workflows.py:444)
                                    while HYPOTHESIS (:426) and PREDICTION (:437) both do. The repo's own
                                    contract matrix says the same thing: HYPOTHESIS, PREDICTION and CLAIM
                                    `ask` for a statement; EXPERIMENT is `silent`.

CLAIM subjects are caller-declared  methodology_driver.py:752 takes them from stage_content, and
                                    scripts/seed_methodology_run.py has no flag that supplies it. A figure
                                    claim therefore reaches the gate with subjects=() and is refused
                                    UNATTRIBUTED_NUMERAL — measured. The gate would refuse every figure claim.

the five new sources are not        live_fetch.py:557 builds hazard specs for openalex and pubmed only; the
selectable                          adapter map (:524) and the live suite's PROVIDERS
                                    (tests/test_p_auto_3_live_fetch.py:102) are the same two. crossref,
                                    arxiv, inspirehep, semantic-scholar and europepmc cannot be fetched by
                                    a live run at all.

REFUTED is never produced           grounding.py:494 finds the rival figure and discards it: an artifact
                                    figure for the same subject and date is accepted only within 0.5 of the
                                    claim's, so a contradicting source returns ASSERTION_NOT_FOUND — "no
                                    figure bound to 'Brazil' in the artifact matches it" — measured. The
                                    module carries no support-state vocabulary at all, so no figure can be
                                    graded as opposed. A refutation never reaches the round or the conclusion.

the admitted reply is not retained  the run report keeps refused replies only. The evidence that an admitted
                                    proposal carried a statement is the journal's intent kind plus a refused
                                    sibling — not the admitted bytes.
```

## 4. The measure

```
3 / 9 stages reach the journal in a live run        5,931 tests collected (docs/SUITE-COUNT.md)
0 / 9 stages have read a fetched artifact live      0 new failures against docs/SUITE-BASELINE.json
```

The two numbers belong on the same line, because one of them is not evidence for the other. The suite proves the
parts — the gate's readings, the five extractors, the round's bound, the journal's invariants. It does not prove
the chain: four stages have been entered live and three recorded, and the five stages that gather, cite, judge
and conclude have never been entered at all.

---

*Measurement. Live run `2026-10-30T19:00:36Z` → `19:02:29Z` on tree `c844cdf`, fresh project
`verify-f3cf2e7-a`, `--max-retries 0`, 30-tick bound ending after 2 ticks. Its full stage trace, proposal
ledger, refusal details and raw replies are tracked at
[docs/OPS-5Z-LIVE-RUN-2026-10-30.md](./docs/OPS-5Z-LIVE-RUN-2026-10-30.md); the four runs it followed, which
recorded 1 of 9, are at
[docs/OPS-5Z-LIVE-RUN-E2E-2026-10-30.md](./docs/OPS-5Z-LIVE-RUN-E2E-2026-10-30.md). The journal itself
(`hermes.db`) and the run report JSON stay outside the repository. The gate readings and every line citation
above were re-measured on 2026-10-31 against this tree.*
