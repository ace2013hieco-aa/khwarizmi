# MERGE-LOG-P2-16 — the detector's blind spots, triaged and documented (GAP-2, last open item)

## Provenance

| Item | Value |
| --- | --- |
| Task | P2-16 (GAP-2): the contradiction detector's recognition surface — a **scope call**, not a defect |
| Ruling | **A — document the boundary** (human, 2026-10-23) |
| Base (`main` before) | `54f6173` |
| Slice | `triage/p2-16` (triage doc, `f5f862e`) + `slice/p2-16-boundary` (ruling record, `a275af2`) — both fast-forwarded |
| Landed tip | `a275af2c838beb4510d9dbd12ed9289df810172f` |
| Merge method | fast-forward, twice (no merge commits) |

## Scope

```
docs/triage/P2-16-DETECTOR-BLIND-SPOTS.md            | 444 ++  (new: the triage)
docs/GAP2-RULINGS.md                                 |   2 +-  (the disposition row)
src/hermes/research/contradiction_candidates.py      |  18 ++  (module docstring)
src/hermes/persistence/failure_classifications.py    |   9 +-  (one method docstring)
```

## What the triage established

- **The surface.** The detector recognizes exactly six typed prefixes (`evidence`,
  `source_result`, `source_payload`, `source_search`, `failure_classification`,
  `feature_binding`) plus a bare-ID row check, in two places
  (`contradiction_candidates.py:106`, `gateway.py:2995`). Anything else returns `None` and
  is **silently dropped** — no log, no counter, no diagnostic key, no journal event.
- **Why it is not live.** Admission (`_verify_evidence_owned`,
  `failure_classifications.py:365-394`) requires a typed ref, refuses
  `failure_classification` outright (D8), and demands two-hop `derived_from` reachability
  from the producing task. Among production-written kinds only `source_result` and the
  fetch-path `source_payload` are reachable, and both are recognized. The one plausible
  unrecognized kind (`source_fetch_outcome`) is one hop, fails the check, and its
  exclusion at the contradiction resolver is deliberately pinned
  (`test_web_provenance_fence.py:322-332`).
- **The dimensional gap.** Contributing factors, numeric claims and source identity have
  **no agreed contradiction semantics**: same-class pairs are excluded by N1, and no
  cross-artifact numeric or source-equivalence rule exists. Recognizing any of them would
  be a new contract, not a detector setting.

## What landed

- **The triage document** (`f5f862e`), including a corrected framing: the recommendation
  rests on the **structural closure**, and the corpus measurement is explicitly demoted to
  corroboration — *"six refs across two test fixtures is a lower bound on nothing."*
- **Two docstrings at the coupling points** (`a275af2`). The blind spot exists because two
  modules independently encode the same closed set, so each now names the other: the
  detector says its prefix set **must stay a subset of what admission can produce** and
  that widening admission without widening it makes the drop live and silent; the
  admission check says widening it without widening the detector creates a silent drop.
  Both say the obligation is a reviewer's, not something the module can enforce.
- **The records**: the triage status is `RULED A`, and the `GAP2-RULINGS.md` row moves from
  *NEEDS-INVESTIGATION — no action* to a disposition naming the ruling, the declined
  options and the reason. The historical triage verdict stays in its column; the ruling
  lives in the disposition.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted (`s1_detector_rows`, `chg1_contradictions`, `failure_classification`, `web_provenance_fence`) | **138 passed** |
| B4 ref graphs | **24 passed** |
| `stamp_suite_count.py --check` | `collected=5058` |
| `check_census.py` | **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0 |
| Full suite | **5055 passed / 3 skipped / 0 failed** |
| `ruff check src tests scripts` | `All checks passed!` |
| `pyright src` | **0 errors, 0 warnings, 0 informations** |
| Source changes | **docstring-only** — `git diff -U0` hunks fall inside triple-quoted blocks; AST identical after stripping docstrings |

## Residuals

1. **The boundary is documented, not enforced.** A future admission widening that forgets
   the detector will produce a silent drop; the docstrings are the only warning, and they
   address a reviewer, not the code.
2. **The dimensional question is open by design.** Contributing factors, numeric claims and
   source identity have no contradiction semantics; deciding them would be a new contract
   with its own gate.
3. Production prevalence of the measured dimensions remains unmeasured — the shipped corpus
   has none. A purpose-built fixture set (two classifications, same project/program/
   hypothesis, different failure class, non-empty overlap, differing dimension) would be
   needed to revisit.

## Prohibited-claims discipline

This gate documents a boundary and a coupling obligation. It claims no completeness for
the detector, no enforcement, and no detection guarantee. The blind spot is accepted, and
its acceptance is written where the next change will be read.

License: Apache-2.0 (LICENSE).
