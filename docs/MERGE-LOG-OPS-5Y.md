# OPS-5Y — merge log: prior art is produced, or it is not asserted

**Base:** `35013e8` (design gate + amendment 1, both approved).
**Branch:** `slice/ops-5y-prior-art`.
**Phase 2:** implemented against `docs/OPS-5Y-DESIGN.md` as amended.

## Commits

| # | commit | subject | diffstat |
|---|---|---|---|
| 1 | `2501fa8` | feat(ops-5y): promote the seeding path, dry-run by default | 2 files, +513 |
| 2 | `4b73a84` | feat(ops-5y): a draft carries a statement, not only a rationale | 9 files, +204 −29 |
| 3 | `0864685` | feat(ops-5y): HYPOTHESIS, PREDICTION and CLAIM are minted, not cited | 16 files, +545 −214 |
| 4 | `8105cb2` | feat(ops-5y): a ref is admitted only with a row-backed witness | 21 files, +754 −74 |
| 5 | `3f449d0` | feat(ops-5y): a claim is anchored by direct support, not reachability | 3 files, +185 −6 |
| 6 | this commit | feat(ops-5y): the depth a run reached is written on its own event | 9 files, +474 −53, plus this log |

Every commit is one concern; each was gated on its own targeted suite. The
full suite ran green on the final code tree (5616 collected; `docs/SUITE-COUNT.md`
stamped and `--check` OK); the only later changes are the generated stamp and
this log.

## `D(C)`, stated so it can be checked against the substrate's edges

For a recorded `CLAIM` node `C` in project `P`:

1. **`D(C)`** — the direct support set — is:
   - every ref in `C.admitted_refs`; and
   - the `external_ref` of every recorded `EVIDENCE` node that `C` directly
     descends from (`REQUIRED_PREDECESSOR["CLAIM"] == "EVIDENCE"`).
2. `C` records only if at least one ref in `D(C)` satisfies all of:
   - `store.resolving_refs[ref] == P` (it resolves in this project);
   - `store.ref_backing[ref] == "FETCHED"` (the row is a `source_payload` whose
     producer begins `capability:source_fetch:`); and
   - `ref not in store.retracted_refs` (N9).
3. **`S(C)`** — the wider closure — is the least set containing `C` closed
   under predecessor edges, every node's `external_ref` and every node's
   `admitted_refs` (never `cited_refs`). It is computed **only** to explain a
   refusal: a fetched ref in `S(C) \ D(C)` is named in the detail and never
   anchors the claim. Reachability is not support.
4. The shape gate separately requires every `CLAIM.admitted_refs` member to
   carry the `evidence:` namespace (`MALFORMED_PAYLOAD` otherwise), and refuses
   `admitted_refs` on `HYPOTHESIS`/`PREDICTION`. Non-emptiness is **not** a
   shape rule: an empty admitted set keeps the historical
   `UNSUPPORTED_CLAIM` refusal, byte-for-byte (gate 7b).

`EVIDENCE` itself still records over a `ROW`-backed citation: a citation may
legitimately name a dataset manifest. The externality question belongs to the
claim, and `StageRecord.backing_class` + `HandlerResult.backing_class` make the
answer readable without inference.

## What moved in the digests, and why it is correct

- **The methodology document (version 3).** HYPOTHESIS, PREDICTION and CLAIM
  now ask for a `statement`; the HYPOTHESIS objective no longer instructs the
  model to cite a `hypothesis:` identity that has no producer; the description
  no longer says "draw a hypothesis from prior art". `literature-review`'s
  digest moved `ca7a95f4…` → `5a78e7ab…`; the old-form fixture's digest moved
  `36566121…` → `a5ba8919…` (it is derived from the shipped document). The
  swap fixture's control digest `91e7427f…` is **unchanged** — its document
  was not touched.
- **`Proposal.draft_digest`** includes `statement` only when non-empty. A
  proposal without one hashes exactly the pre-slice formula (pinned in
  `test_agent_runtime` and `test_ops5y_prior_art`). A synthesizer CLAIM
  proposal that supplies a statement therefore has a different digest — this
  is the intended change: the asserted content is now part of the draft's
  identity, and the rationale is not.
- **`Proposal.to_mapping`** includes `statement` only when non-empty, so a
  proposal without one serializes byte-identically.
- **Minted node content** adds `statement` and `origin`. Those nodes' derived
  ids and every run digest containing them move — by design. An `EVIDENCE`
  node with the same content keeps its id.
- **`SubstrateStore.to_mapping`** adds `ref_backing`. A store read from a mapping
  without it is all-`ROW`: citations still resolve, claims refuse. Fail closed.
- **`StageOutcome.content_origin` / `StageRecord.content_origin` and
  `StageRecord.backing_class`** are included only when non-empty, so a
  non-minted stage's mapping is unchanged.
- **`TaskStatusChanged` payloads are byte-identical** unless a handler reports
  depth. The methodology handler now does; every other handler writes no key.
  The `transition_status` transaction and its 4 KiB validator are unchanged.

## Fixtures that changed shape, and what they still prove

- `test_methodology_plane._build_chain` mints HYPOTHESIS/PREDICTION/CLAIM
  (statement + origin, no `external_ref`). The reconstruction, contradiction,
  project-scope and N9 tests still assert the same properties; the citation
  probes (hallucinated ref, cross-project ref, retracted ref) moved to
  `EVIDENCE`, the one citation kind, so they still prove **citation
  resolution** rather than a minted identity.
- `test_ops5d`: the claim's `external_ref.startswith("claim:")` assertion
  became `origin == "MINTED"` + a non-empty statement; the old prior-art label
  assertion became the minted-label assertion. The fetched-artifact →
  EVIDENCE → admitted-support property is unchanged.
- `test_ops5m`, `test_ops5l`, `test_ops5t`, `test_ops5f`, `test_wiring_w3`,
  `test_wiring_w4`, `test_loop0_e1_probe`, `test_ops7_input_projection`,
  `test_ops1_live_cli`: prior-art seeds dropped (a fresh project has no row to
  back them), statements supplied through `CHAIN_STATEMENTS`, and live runs
  given the read-only provenance port (`RefProvenanceReader` where a real
  artifact row exists, `fixture_provenance` for the DB-less plane fixtures).
  Each test still asserts its original property: truncation, S6-B2, stage
  budgets, wiring attribution, prompt reach, completion truth.
- `src/hermes/eval/hostile.py`: gap uses a minted HYPOTHESIS; hallucination and
  coupling use `EVIDENCE`; circular uses valid minted nodes; retraction and
  leak are unchanged. The eval matrix's pinned tests all still pass.
- No test was relaxed to pass. The one inventory check that changed is the
  point of the slice: `REFERENCED_NODE_KINDS == {EVIDENCE}` (was four kinds),
  with `MINTED_NODE_KINDS` named and pinned.

## Findings — where the tree contradicted the note, the review or the prompt

1. **§5.2 vs §4.4/gate 7(b): `CLAIM.admitted_refs` "must be non-empty".** The
   note states it as a shape rule, while the adversarial table and the required
   falsifier say an empty set refuses `UNSUPPORTED_CLAIM` exactly as today.
   Resolved in favour of the falsifier: the shape gate enforces only the
   `evidence:` namespace; non-emptiness remains `_support_refusal`'s
   `UNSUPPORTED_CLAIM`. `test_no_admitted_evidence_is_refused_exactly_as_before`
   pins the old sentence.
2. **§6.2 contradicts itself on objectives.** It says "the three stages ask for
   `statement` in the draft" and, a paragraph later, "PREDICTION and CLAIM
   objectives are not changed". With minting, a stage whose objective never
   asks for a statement cannot record unless a caller supplies one, so run 39
   would stop at PREDICTION. The prompt adds "plus the synthesizer objective".
   Resolved by changing HYPOTHESIS, PREDICTION and CLAIM objectives and bumping
   the document to version 3. This is the content revision the statement work
   implies, not a drive-by.
3. **The note's §9.2 blast radius omitted `src/hermes/eval/hostile.py`.** Its
   methodology probes used the old citation shape; they had to follow the
   minted shape. The eval matrix caught it (its `coupling` witness failed until
   the foreign ref was registered with a backing).
4. **"provider" has no selection path in the prompt's seed parameters.**
   `INSERT_TASK` carries no provider field; the run's model is selected by the
   composed tier configuration. `--provider` is recorded in the intent's
   justification (with that limitation stated in the script and its help). It
   changes journal text, not behaviour; calling it a selector would be a lie.
5. **A fresh project cannot carry a backed ref.** The store's backing predicate
   is project-scoped, and a fresh project has no rows. `--admission-ref` on a
   fresh seed is therefore refused with an explanation, and
   `--allow-existing-project` was added so a backed ref can be seeded into a
   project that already holds its claim/program/artifact rows. This is the
   usability gap (A) leaves open until (B) gives prior art a producer; it is
   recorded rather than papered over with a fake row.
6. **The review's Q1 remedy was inert, as the note says.** `ProfileSpec.schemas`
   is loaded and never read; the five surfaces (DRAFT_KEYS, the rendered
   contract, `_validate_drafts`, `_emit_drafts`/`_emit_intent`, `Proposal`) are
   what enforce the field. The projection at `run.py:1103` stays conditional;
   `draft_digest` stays conditional.
7. **`OLD_FORM_DIGEST` moved.** `_old_form_document()` is derived from the
   shipped document, so changing the objectives changes the old-form content.
   The parse-identity property still holds (no stage fields are added), and the
   pin was recomputed, not removed.
8. **The controller's terminal depth is written on FAILED, not RETRYING.** The
   controller's retry policy writes FAILED then RETRYING; only FAILED carries
   the dispatch's depth, and the eventual FAILED from a later attempt carries
   that attempt's. `depth_report` selects the deepest field row, so a later
   dispatch supersedes an earlier one. This is the honest record of "the last
   dispatch's depth", not a synthetic terminal.

## Gates run

1. Targeted per commit: the new file, `test_methodology_plane`,
   `test_ops5d_proposal_content`, `test_ops5m_truncated_chain`,
   `test_ops5l_evidence_ref_and_completion`, `test_ops5t_completion_truth`,
   `test_ops5f_stage_budget`, `test_wiring_w3`, `test_wiring_w4`,
   `test_loop0_e1_probe`, `test_ops7_input_projection`,
   `test_ops1_live_cli`, `test_loop_baseline`, `test_b4_ref_graphs`,
   `test_census_check`.
2. Full suite (`scripts/run_tests.py`): **green, 5616 collected** (3 skipped).
3. `scripts/stamp_suite_count.py` then `--check`: **OK**, 5616.
4. `scripts/check_census.py`: **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0.
5. `uvx ruff check src tests scripts`: pass. `uvx pyright src`: 0 errors.
   `uvx pyright --pythonpath .venv/Scripts/python.exe --project
   pyrightconfig.tests.json`: 0 errors (1 pre-existing warning in
   `test_research_program.py`).
6. The two falsifiers, by name:
   - `TestDirectSupport::test_a_fetched_artifact_elsewhere_does_not_launder_row_support`
     — `UNSUPPORTED_CLAIM`; the detail names the wider closure as explanation.
   - `TestDirectSupport::test_no_admitted_evidence_is_refused_exactly_as_before`
     — `UNSUPPORTED_CLAIM` with the historical sentence.
   - plus `test_an_all_row_support_graph_is_refused` (the third added falsifier
     from §4.4).
7. `scripts/depth_report.py` on a real journal whose run stopped at `EVIDENCE`
   prints `depth_source: "field" 1 | "prose" 0 | "unrecorded" 0` and the row
   `EVIDENCE / MALFORMED_PAYLOAD`; a `provider_response` evidence run reads
   `CLAIM / UNSUPPORTED_CLAIM / backing ROW`.
