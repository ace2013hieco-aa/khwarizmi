# Contract matrix — 2026-10-28

The first static check of the **seams** rather than the slices. Every blocker this week was two layers
disagreeing about one value; each slice tested its own claim and passed, so the disagreement surfaced only
when a live run walked into it.

`scripts/contract_matrix.py` walks four seams, read-only and deterministic, and exits 1 on a mismatch.

```bash
python scripts/contract_matrix.py          # table, exit 1 on mismatch
python scripts/contract_matrix.py --json
```

## What it found on the current tree (`slice/ops-5y-prior-art` @ `e24cea0`)

### 1. The OPS-5Z defect, in all three stages

```
stage        profile      gate   declared  verdict
HYPOTHESIS   researcher   needs  optional  MISMATCH
PREDICTION   experimenter needs  optional  MISMATCH
CLAIM        synthesizer  needs  optional  MISMATCH
```

The method is key ablation: build the node the default producer makes, delete one content key at a time,
and ask the shape gate. `statement` is load-bearing for all three minted kinds — and every contract offers
it as optional. Run 39 found this for `HYPOTHESIS`; the matrix finds it for `PREDICTION` and `CLAIM` too,
before either has ever been reached.

### 2. Two stages can be recorded with no content at all — **new**

```
EXPERIMENT   produced=[]                      NO SHAPE RULE — an empty EXPERIMENT node is accepted
OBSERVATION  produced=['cited_refs']  decorative=['cited_refs']
                                              NO SHAPE RULE — an empty OBSERVATION node is accepted
```

`_kind_refusal` (`substrate.py:905-1010`) has **no branch for either kind**. `_default_content` returns
`{}` for `EXPERIMENT` (`workflows.py:793-820` matches it against nothing), and produces `cited_refs` for
`OBSERVATION` only when an `evidence_ref` was passed — which the gate never requires.

**A correction, made after the invariant suite caught my wording.** I first wrote "an empty node of either
kind is accepted". That is true of `_kind_refusal` and false of `write_node`: a node with **no predecessor**
is refused `PROVENANCE` ("every transition carries a provenance edge"), so the hole is easy to miss. The
verified statement is narrower and worse — *content is unconstrained once provenance is satisfied*:

```text
empty EXPERIMENT  + PREDICTION predecessor -> recorded (mnode_b13759…)
empty OBSERVATION + EXPERIMENT predecessor -> recorded (mnode_762a400…)
```

So the two stages that constitute the middle of the chain can each record with no content at all:

- **`EXPERIMENT`** — the stage whose objective is "describe the test that would discriminate between the
  hypothesis and the observation that would refute it" records nothing. The run's discriminating step
  leaves no trace.
- **`OBSERVATION`** — an observation node may cite nothing and still record.

### 3. And the conclusion check cannot see it *(inferred, not yet demonstrated end-to-end)*

`_support_refusal`'s `CONCLUSION` branch (`substrate.py:1252-1254`):

```python
present = {store.nodes[item].kind for item in ancestry if item in store.nodes}
missing = [kind for kind in CHAIN_KINDS[:-1] if kind not in present]
```

It checks **kinds**, never content. Combined with §2, a `CONCLUSION` is recordable from a chain in which
the experiment and the observation both recorded nothing. The two halves are verified separately — the
kinds-only check by reading, the empty-content recording by execution — but the end-to-end conclusion has
not been driven through a real chain, so it is stated as an inference rather than a measurement.

This is the compatibility question in its sharpest form: OPS-5Y closed the *front* of the chain (minting)
and OPS-5Y's `D(C)` closed the *end* (support), and the *middle* is hollow in a way neither touches.

### 4. Clean

- **Refusal vocabulary:** nothing emitted that is undeclared, nothing declared that is unemitted.
- **Objectives:** all three minting stages ask for a statement in prose. The prose is right; the contract
  was the disagreement.

## What this says about the process

Three disagreements, one pass, no run, no provider, ~2 seconds. One was already known (5Z, found by run 39
at the cost of a run); two were not.

That is the answer to "how do we avoid disturbing the whole while fixing one part": **the seams are
statically checkable, and they were never being checked.** The per-slice falsifiers ask "did my change do
what it claims"; nothing asked "do these two layers still agree".

## How to use it

- Run before and after any slice that touches a boundary: draft fields, node content, intent payloads,
  refusal codes, stage objectives.
- Exit 1 is a gate, not a warning.
- The `--json` form is for diffing two trees: a mismatch that appears is a regression, and one that
  disappears is a fix.

## Known limits

- Only `_kind_refusal` is exercised. `_support_refusal` is separate (which is why `CLAIM.admitted_refs`
  reads as decorative here — it is enforced there, and the report says so).
- The `required` flag is read from `output_contract_for`, so it sees the contract the model is given, not
  what the model does with it.
- Objectives are checked for the word "statement", which is a weak test that would have caught the OPS-5Y
  wording but cannot judge whether the prose is followable.

---

# Extension — the gate now covers six seams

Added after the Director asked for "the same structural gate for all parts". Two more seams, both
mechanical:

## E. Contract rendering — is every declared field actually in the prompt?

Every profile renders `statement` as:

```
- statement (string, optional; optional: what the proposal asserts, never why it is raised ...)
```

Two things here:

1. **`optional` is correct today and is the OPS-5Z defect**, visible in the prompt text itself. After 5Z
   the three minting profiles must render `required when the reply proposes` — so **this line is 5Z's
   acceptance check**, and it is a diff, not a judgement.
2. **The word is duplicated** — `optional; optional:` — because `_contract_lines` writes the requirement
   and the field note then repeats it. Cosmetic, but it is the line the model is asked to obey, and a line
   that stammers is a line a weak model discounts. Worth one character of cleanup in 5Z's phase 2.

No field is absent from the prompt: every declared `FieldSpec` appears in the rendered text for its
profile.

## F. Payload schemas — 12 of 19 proposable kinds have no declared schema

```
critic       ABANDON, REQUEST_ADDITIONAL_EXPERIMENT, REQUEST_HUMAN, REQUEST_REPLICATION
experimenter REQUEST_ADDITIONAL_EXPERIMENT, REQUEST_REPLICATION
planner      ABANDON, BRANCH
```

`INTENT_PAYLOAD_KEYS` documents this as intentional — "kinds absent here have no closed top-level schema
exposed" — so this is **known, not new**. But the proportion is worth seeing: a profile may propose
`REQUEST_HUMAN` or `ABANDON` with no payload guidance at all, and the contract renders nothing for it. If a
run ever reaches those kinds, the model is guessing and the gateway's validator is the only opinion.

Not a finding to fix in 5Z. Recorded so that the first time a run proposes `REQUEST_HUMAN`, the absence of
guidance is a known condition rather than a surprise.

## The gate, in one line

```bash
python scripts/contract_matrix.py || exit 1
```

Six seams: minted-kind content (ablation), declaration vs enforcement, contract rendering, payload
schemas, refusal vocabulary, objectives. Exit 1 means a layer disagrees with another layer about a value —
which is the only failure class this project has actually suffered from.

---

# Two instruments that complete the gate

## `scripts/depth_regression.py` — the ratchet

The matrix checks that layers agree. It cannot check whether the pipeline still *reaches* as far as it did,
because reach is a property of a run, not of a declaration. This pins it.

```bash
python scripts/depth_regression.py --db <journal> --baseline docs/DEPTH-RATCHET.json
```

- Reads only **field-derived** depths (`depth_source == "field"`). Prose-derived depths come from before the
  field existed, and they include run 38's `PREDICTION` — which was bought with prior art that did not
  exist. Pinning that as a floor would fail every honest run.
- Exits 1 when reach falls and no allowance was given; `--allow-decrease "<reason>"` passes and **records
  the reason in the file's history**; `--update` moves the ratchet.
- A decrease is not automatically a regression — an honest floor can be lower than a seeded one, which is
  exactly what happened between run 38 and run 39. The rule is that it may never be *silent*.

Current ratchet: **depth 1 (`QUESTION`), `sars-covid-39`**, recorded with that reasoning.

## `tests/test_pipeline_invariants.py` — the properties that outlive a slice

Ten tests that hold whatever changed, rather than one slice's claim:

1. a claim is never supported by a non-fetched artifact (`D(C)`);
2. a claim with no admitted evidence refuses exactly as it always has;
3. every refusal code the substrate emits is declared;
4. every field the contract declares reaches the prompt;
5. **no chain kind records a node with empty content** — `xfail(strict)`, EXPERIMENT and OBSERVATION;
6. the minting and non-minting stages share profiles, so a per-profile flag cannot express the rule.

Tests 5, 6 and 7 are `xfail(strict=True)`, one marker per hole: an empty EXPERIMENT, an empty OBSERVATION,
and a CONCLUSION over an empty middle. The first version used **one** marker for the first two, and tested
OBSERVATION only inside `if EXPERIMENT was recorded` — so fixing EXPERIMENT would have left the second hole
untested while the suite went green. The audit found that; the markers are now independent.

A hole with a marker still cannot be forgotten, but it *can* be half-fixed, which is why the markers are
separate and why the fix note says to delete each one individually.

## The gate, complete

```bash
python scripts/contract_matrix.py || exit 1
python scripts/depth_regression.py --db ... --baseline docs/DEPTH-RATCHET.json || exit 1
python -m pytest tests/test_pipeline_invariants.py -q
```

Three questions, three instruments: **do the layers agree**, **does the pipeline still reach**, **do the
properties that outlive a slice still hold**.

---

# Blast-radius weighting

Mismatches are now sorted by the import fan-in of the modules that own the seam (`run.py` declares,
`substrate.py` enforces), and the table carries a `blast` column. The point is triage: a disagreement in a
module with six importers is not the same finding as one in a leaf, and the matrix previously listed them
as equals.

The proxy is import fan-in, which understates. Ix measures `run.py` at 36 *call* callers against 6 import
edges — calls cross modules that imports do not. The proxy keeps the gate runnable without Docker; when Ix
is up, prefer its number.

---

# The baseline — so the gate can go green

The audit's F4 was the sharpest finding about the matrix: it exited 1 for three known findings, so a
*fourth* produced the same signal. A gate that is permanently red is a report with an exit code.

```bash
python scripts/contract_matrix.py --baseline docs/CONTRACT-BASELINE.json
```

- **Exit 0** when every finding is already accepted.
- **Exit 1** when a finding is **not** in the baseline — a disagreement that did not exist before.
- **Exit 1** when the baseline file is missing: a missing baseline is not a pass, same rule as the depth
  ratchet.
- `--allow "<reason>"` accepts the new finding and records the reason; `--update` re-accepts everything.
- A baselined finding that has **gone away** is reported (`no longer present — record with --update`) so the
  baseline shrinks honestly instead of accumulating stale entries.

Findings are keyed per `(stage, unoffered key)`, not per row, so fixing one field of a stage removes one
entry rather than the whole stage.

Accepted today (3): `HYPOTHESIS:statement`, `PREDICTION:statement`, `CLAIM:statement` — the OPS-5Z defect,
which is the thing 5Z exists to fix. **When 5Z lands, these three disappear and the baseline should be
updated to empty**; until then the gate is green and any *new* disagreement is loud.

Verified all five paths: no baseline (1), known only (0), new finding (1, named), `--allow` (0, history
entry), stale entry (reported, 0).

Also hardened: `sys.stdout.reconfigure(encoding="utf-8")`. The audit saw a cp1252 `UnicodeEncodeError` on
the arrow in the table — I could not reproduce it here, but a crash-while-printing exits 1, which is
indistinguishable from "a mismatch was found". Pinning the encoding makes the exit status mean what it says.

---

# Self-checks — the gates must be able to fail

`tests/test_gate_selfchecks.py` (11 tests) asserts that each instrument **fails when it should**, using
temp trees and temp journals. The real `src/` is only ever read.

It exists because the audit's injections were all manual and then thrown away, so the repairs could have
regressed silently. These are those injections, kept:

| injected defect | the gate must |
|---|---|
| a new module on an already-pinned pair | exit 1 (`NEW MODULE EDGE`) |
| two modules importing each other | exit 1 (`NEW CYCLE`) |
| a ratchet file that does not exist | exit 2 — not 0 |
| a `if TYPE_CHECKING:` cross-layer import | exit 0 — a false positive is also a failure |
| an unparseable module | exit 1 (`UNPARSEABLE`) |
| depth 3 then 1 in one project | exit 1 (`REACH FELL`) |
| a journal with no field rows | exit 1 (`UNMEASURABLE`) |
| a baseline trimmed by one accepted key | exit 1 (`NEW FINDING`, named) |
| the recorded baseline | exit 0 |

**Verified that the self-checks can fail.** Re-introducing the F6 hole — ignoring module edges when
deciding failure — makes `test_a_new_module_on_a_pinned_pair_fails` fail with `assert 0 == 1`. A self-check
that cannot fail is the same defect it is written to catch.

**A real bug it found immediately:** two tests shared the name `test_a_missing_baseline_is_not_a_pass`
(one for the depth ratchet, one for the matrix). Python silently redefines the first, so the depth test had
never run — "10 passed" was 9 unique tests. Ruff's `F811` caught it; the names are now specific.

Exit codes, across all three scripts: **0** clean, **1** a finding, **2** the gate could not run. A test that
accepted 1 where 2 is right would pass a gate that had crashed.

---

# Second audit — N7 and N10

## N7 — the exit code read one seam of six

`finding_keys` keyed only the declaration/enforcement mismatches, so the vocabulary, rendering,
payload-schema and objective seams could report a defect and never move the exit status. The tree already
printed `without a schema: 12/19` with no effect.

Every seam now contributes keys (`vocab:`, `render:`, `payload:`, `objective:`, plus the stage keys). The
baseline grew from 3 to **21 accepted findings** — the 3 statement mismatches, 12 proposable kinds with no
payload schema, and 6 objectives that never ask for a statement. Those are known gaps; a **new** one fails.

## N10 — a self-check accepted a crashed gate

`test_a_missing_contract_baseline_is_not_a_pass` asserted `returncode == 1`, so a gate that crashed with
`SystemExit` satisfied it — the exact confusion the file's own docstring warns about. A missing baseline is
unusable input: **exit 2**, matching the other two gates.

## Self-checks now 17

Added for this audit: a shadowed file is read (N1), a bogus `--allow-edge` is rejected (N2), a non-dict
ratchet is unusable (N3), an absent project is not "held" (N4), a bare `--update` cannot launder a regression
(N5).

---

# The split — one self-check file per instrument

The rehearsal found this. I merged `test_gate_selfchecks.py` into a worktree at the OPS-5Z tip, whose closure
excludes the depth ratchet, and **five tests failed** — they test `depth_regression.py`, which was not there.

Worse, one **passed**: `test_a_missing_depth_baseline_is_not_a_pass` asserts exit 2, and a missing script
makes Python exit 2. A test that passes when its subject is absent is the defect these files exist to catch,
reproduced inside the file written to catch it.

So the file is split by instrument:

| file | tests | travels with |
|---|---|---|
| `tests/test_gate_selfchecks.py` | 12 | `contract_matrix.py` + `structure_map.py` |
| `tests/test_depth_selfchecks.py` | 7 | `depth_regression.py` |

Each opens with `test_the_script(s)_under_test_exist`, so a missing subject fails loudly instead of
satisfying an exit-code assertion by coincidence. Verified by hiding `structure_map.py` — the guard fails.

**Rehearsal result on the OPS-5Z tree (`d9601b4`) with only the merge closure:**

```text
python scripts/contract_matrix.py --baseline docs/CONTRACT-BASELINE.json   -> 0
pytest tests/test_gate_selfchecks.py                                      -> 12 passed
pytest --collect-only                                                     -> 5628 tests
```

5616 + 12 = 5628, which is the number the suite-count stamp needs after the merge.
