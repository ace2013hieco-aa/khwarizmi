# MERGE-LOG-OPS-5D — the evidence position, and the labelled remainder

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-5D phase 2: the evidence position becomes the agent's admitted artifact |
| Base | `main` at `f9ea5f0` (the approved design gate) |
| Branch | `slice/ops-5d-proposal-content` |
| Commits | `25f3722` (implementation + tests), this commit (merge log + approval addendum + stamp) |
| Status | **PASS** — the approved falsifiers are green |

## The ruling

**A at the evidence position, with the prior-art remainder labelled.** Not full
A, and not a rule relaxation. The evidence position gets the fix; the other
three cited positions stay prior art and are labelled in the design note and
in the node rationale.

**OPS-5E — the artifact-producer gate.** *Until a producer exists for
`hypothesis:`, `prediction:` and `claim:`, those positions cite prior art and
the chain's only agent-gathered evidence is the `EVIDENCE` ref.*

The claim distinction, as approved: **the claim's identity is prior art; its
support is the recorded evidence ref.** The node rationale is **a node field,
not content, and it does not re-enter the next prompt.**

Phase-2 scope clarification: the seed refusal covers the citation/resolution
positions (`external_refs`, `admission_refs`, and the evidence position's
`stage_content`). A `retracted_refs` entry is the N9 projection and may name an
evidence ref; it cannot make a fake resolve or be cited, and refusing it would
make N9 unreachable for agent evidence.

## What landed

1. **One shared content builder** (`methodology/workflows.py`) used by both
   drivers. `_default_content` now takes the run's admitted `evidence_ref`:
   - `EVIDENCE.external_ref = evidence_ref` (never the seed);
   - `OBSERVATION.cited_refs = (evidence_ref,)` when admitted by that stage;
   - `CLAIM.admitted_refs = (evidence_ref,)`; the claim's own `external_ref`
     stays the prior-art citation.
   The prior-art positions (`HYPOTHESIS`, `PREDICTION`, the claim identity)
   still read `inputs.external_refs`; their node rationale carries
   `prior-art citation (no producer in this build)` / the claim distinction.
2. **The evidence selector.** The latest `ADMITTED`/`DUPLICATE`
   `EVIDENCE_TRANSITION` with an `evidence:` payload in the `OBSERVATION` or
   `EVIDENCE` stage run supplies the ref. The driver projects it into the
   in-memory `SubstrateStore` (`admit_ref`) before writing the node; the
   artifact-row check remains the gateway's `EVIDENCE_REF` / `in_project`.
   No table read, no repository import, no second check.
3. **The seed refusal.** Before any stage, both drivers refuse a non-empty
   `EVIDENCE` entry or any `evidence:` value in `external_refs`, any
   `evidence:` value in `admission_refs`, and any evidence-position
   `stage_content` ref (`OBSERVATION.cited_refs`, `EVIDENCE.external_ref`,
   `CLAIM.admitted_refs`). Code `MALFORMED_PAYLOAD`, source `inputs`. A
   `retracted_refs` evidence entry is allowed (N9 projection).
4. **The node rationale.** The first admitted proposal's rationale in the
   stage run, or the supplying evidence proposal's rationale for the
   `EVIDENCE` node, or the existing template. It is a node field, not content;
   it does not enter `predecessor_content` and never re-enters a prompt. It is
   durable for an admitted proposal via `IntentApplied.justification`.
5. **The stop.** No admitted evidence transition → the `EVIDENCE` node is not
   recorded; `write_node` returns the substrate's own
   `MALFORMED_PAYLOAD` ("needs a non-empty 'external_ref'") and the run stops
   at `EVIDENCE`. No fallback to the seed, no driver-picked artifact.

## The falsifiers → evidence

### 1. The fetched artifact is the EVIDENCE node's ref

`tests/test_ops5d_proposal_content.py::test_the_fetched_artifact_is_the_evidence_node_ref`
runs the real live driver over the real gateway, with the fetch executed
through the OPS-5C capability supply (HYPOTHESIS fetches; the shipped
one-tick-per-stage bound means the citation happens in OBSERVATION, which reads
the artifact id from the OPS-18 project index). Printed:

```
EVIDENCE NODE ID: mnode_8b7ff98ab7d75fcda5aadc1f124e1884
EVIDENCE CONTENT: {"external_ref": "evidence:0eb8332c7cbbb89c5cb0f626816a31ec02864879fe044c5df5b87b916c18df73",
                   "predecessors": ["mnode_e62a267bd736cbd8cd8141c215a0c6ec"]}
EVIDENCE RATIONALE: cite the artifact the agent fetched
TRANSITION EVENT REF: evidence:0eb8332c7cbbb89c5cb0f626816a31ec02864879fe044c5df5b87b916c18df73
```

The gateway admitted the transition with `EVIDENCE_REF`; the event carries the
ref; the artifact row is real (`in_project` true). The `OBSERVATION` node
cites it; the `CLAIM` node admits it; the claim's own ref is prior art.

`test_the_evaluation_of_the_evidence_ref_is_the_gateway_check` shows the same
row accepted and a ghost refused `EVIDENCE_REF`.

### 2. The seed evidence ref is refused

`test_a_seed_evidence_ref_is_refused` — three cases (`external_refs["EVIDENCE"]`,
an `evidence:` value in `admission_refs`, an evidence-position `stage_content`
ref) each return `MALFORMED_PAYLOAD`, source `inputs`, before any model call.

### 3. No admitted transition stops at EVIDENCE

`test_a_run_without_an_admitted_transition_stops_at_evidence` — a silent model
and a prior-art-only seed: the driver stops at `EVIDENCE`, source `substrate`,
`MALFORMED_PAYLOAD`, the substrate's non-empty-ref message; no transition event
and no artifact row.

### 4. A ghost ref still refuses; no second path

`test_a_ghost_ref_is_refused_by_the_gateway_and_stops_at_evidence` — the real
gateway records the `EVIDENCE_REF` refusal (the runtime's frozen vocabulary
surfaces it as `PROPOSAL` with the spine code in the detail, C4), the driver
stops at `EVIDENCE`, and no transition/artifact exists.
`test_the_drivers_have_no_second_artifact_row_check` asserts neither driver's
source names `ArtifactRepository`, `in_project` or an artifact SQL check.

### 5. Replay

`test_a_replay_reproduces_the_evidence_node_content_and_id` — two runs with the
same scripted fetch/cite replies produce the same `EVIDENCE` content, rationale
and `mnode_` id; the second transition is a duplicate, so the durable
`EvidenceTransitionProposed` count stays 1.

The replay argument remains the design note's: the node content is a pure
function of the task inputs, the admitted transition's ref
(`EvidenceTransitionProposed`), its rationale (`IntentApplied.justification`)
and the stable stage task id. This is content determinism, not validity.

## The first full-suite run — an honest correction

The first full run on the migrated tree was **red: 5273 passed, 3 skipped,
1 failed**. The failure was
`test_eval_plane.py::TestMatrixRedProof::test_neutralizing_a_pinned_refusal_turns_the_matrix_red`
at its final assertion: the neutralization proof checks that the restored
pinned test file matches `HEAD`, and `tests/test_methodology_plane.py` was
migrated but **uncommitted** at that moment. The proof's modify/red/restore
assertions passed; only the HEAD-cleanliness check failed. It was a working-tree
artifact, not a behavior failure.

The code and tests were committed at `25f3722`; the pinned test passes on the
committed file; the full suite was rerun green (row below). No assertion was
weakened and no rule was changed to make the first run pass.

## Fixture migration (not a rule weakening)

The prior fixtures seeded an `evidence:` ref and expected a complete chain.
OPS-5D moves them to the agent path:

- `tests/test_methodology_plane.py`: `GroundedModel` proposes the evidence
  transition (with a review-child guard); `AdmittingApplier` admits;
  `chain_inputs` carries prior art only; the N9 driver test uses a retracted
  agent ref; new seed-refusal and stop tests.
- `tests/test_wiring_w3.py`: `GroundedModel`/`ProposingModel` propose the
  evidence transition where the profile may; the custom profile authority
  declares it; the silent run now stops at EVIDENCE (a new pin).
- `tests/test_wiring_w4.py`: a real artifact row backs the agent evidence ref
  through the real gateway; the full chain still lands through the bound
  applier; the zero-admission S6-B2 pin uses a one-stage document because the
  evidence gate would otherwise stop before the zero-admission check.
- `tests/test_ops7_input_projection.py`, `tests/test_ops1_live_cli.py`,
  `tests/test_loop0_e1_probe.py`, `swap_test.chain_inputs`: prior-art refs only;
  the model supplies the evidence transition (OPS-1's CLI fixture is one stage;
  it exercises the live CLI, not the chain).

No assertion was weakened to make the model's output fit; the fixtures now
exercise the rule instead of the seed.

## Limits and deliberate refusals

- **Prior art is prior art.** `HYPOTHESIS`, `PREDICTION` and the claim's own
  `external_ref` remain operator citations; their producers are OPS-5E. The
  claim's support is now the agent's evidence ref.
- **No fallback.** A run with no admitted evidence transition stops at
  `EVIDENCE`; the seed cannot supply the ref; the driver cannot pick an
  artifact (B was rejected).
- **No rule relaxation / no second check.** `_kind_refusal` and the gateway's
  `in_project` are untouched; the substrate's N9 rule is untouched. The
  driver's `admit_ref` is an in-memory projection of the admission.
- **Delegated child proposals are not traversed** (Q6, known limit). A stage
  that sources evidence through a delegation has no ref and stops.
- **One tick per stage.** A fetch and its citation cannot share a tick; the
  fetch happens earlier and the OPS-18 project index lets the citing stage name
  the artifact. No multi-tick stage was added.
- **Retracted evidence and N9.** The seed may carry an evidence ref in
  `retracted_refs` (the N9 projection); it cannot make a ref resolve or be
  cited. The citation/resolution seed positions refuse it.
- **No new event/write/transaction.** Census unchanged; the store is
  in-memory; the only durable acts are the model's ordinary intents.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted (the new file, methodology plane, W3, W4, loop0, OPS-7, OPS-18, OPS-1, OPS-5C/5B, loop baseline, B4, census) | **283 passed in 9.43s** |
| Full suite under the heavy-gate lock | **first run: 5273 passed, 3 skipped, 1 failed** — the eval-plane pinned-HEAD proof; the migrated pinned test was uncommitted. Committed at `25f3722`; rerun **5274 passed, 3 skipped in 721.05s (0:12:01)**, exit 0 (5277 collected) |
| `stamp_suite_count.py` → `--check` | **Stamped collected=5277** → **OK: collected=5277 matches the live collect** |
| `check_census.py` | `PASS - every certified figure is reproduced exactly.` (124 / 28 (19/5/4) / 1 / 15 / 0) |
| `uvx ruff check src tests scripts` | `All checks passed!` |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| pyright tests project | `0 errors, 1 warning, 0 informations` (the known `test_research_program.py:144`) |
| B4 ref graphs | 24 |
| LOOP baseline | unchanged |
| Drain-only | byte-identical |

License: Apache-2.0 (LICENSE).

---

## Director addendum — run 14, and the prediction that held

Landed at `c173c4c`, then run 14 with **prior-art refs only** — no `evidence:` ref in the seed, because
it is now refused. The agent had to earn its evidence.

```
runs 7, admitted 10, SUCCEEDED:6/OTHER:1
M2(calls=0)          → no search, no fetch
artifacts: 0
```

**The chain stopped at EVIDENCE.** Six stages — QUESTION → HYPOTHESIS → PREDICTION → EXPERIMENT →
OBSERVATION → EVIDENCE — and then:

```
MALFORMED_PAYLOAD: payload.evidence_artifact_ref must be 'evidence:<artifact_id>'
```

The model proposed an `EVIDENCE_TRANSITION` with a malformed ref, because it had **no artifact to
name**: it never fetched.

**This is the outcome the ruling predicted, and it is the correct one.** Run 13 reached CONCLUSION
partly by citing a ref I invented. With that ref gone, the chain stops at the first stage that needs
evidence the agent did not gather. The previous progress was partly bought with a fake reference, and
run 14 is the first honest measurement.

### What it establishes

- **The plumbing is right.** The evidence position now records an agent-fetched artifact when one
  exists — proven by `test_the_fetched_artifact_is_the_evidence_node_ref` against the real driver and
  the real gateway.
- **The seed can no longer fake it** — `test_a_seed_evidence_ref_is_refused` refuses three positions
  before any model call.
- **The agent has never fetched.** Not in run 12 (4 searches), not in run 13 (2 searches), not in run
  14 (0 calls). Fourteen runs, zero fetches, zero artifacts outside scripted tests.

### The wall has moved from structural to behavioural

The last four gates were about making a fetch *possible and citable*. All of that now works. What does
not happen is the fetch itself: the model knows `source_fetch` exists and how to call it, and it knows
the shape an `EVIDENCE_TRANSITION` must take — but **nothing tells it that this stage's job requires
one**.

A schema is not a job description. That is the next gate.

Director gates at the merged tip: 116 targeted passed, stamp `5277`, census **PASS**, B4 24.
