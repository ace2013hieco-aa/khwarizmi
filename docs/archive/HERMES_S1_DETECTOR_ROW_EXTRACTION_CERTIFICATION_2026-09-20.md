# S-1 Detector Row Extraction Certification

## §0 Verdict

```text
S-1 — CERTIFIED / CONTROLLER EXTRACTION SUCCESSFUL
```

## §1 Baseline

`HEAD == origin/main == 558a8d5` at start (branch `main`, DG-2
report present). Tree: no tracked modifications (untracked only:
`IDEA.md`, operator `Prompts/`, external `or*.json`).

## §2 Implementation Commit

`231cd75` `refactor(controller): extract S-1 detector row
derivation`, parent `558a8d5`. Exactly 3 files, +439/−90:
`src/hermes/research/contradiction_candidates.py` (new, 124
lines), `src/hermes/research/controller.py` (+19/−90),
`tests/test_s1_detector_rows.py` (new, 10 characterization
tests). No other file touched.

## §3 Exact Seam

Moved verbatim (self→params only):
`_detector_candidate_rows:1967` →
`detector_candidate_rows(conn, project_id, digest_items)`;
`_detector_resolve_ref:2025` →
`detector_resolve_ref(conn, project_id, ref)`;
`_open_contradiction_parties:825` →
`open_contradiction_parties(conn, project_id)`.
Controller keeps same-named thin wrappers delegating with
`(self._conn, self._project_id[, digest items])`; all existing
callers (`_detect_contradictions_pass:1922`,
`re_review_candidates:801`) and tests run unchanged.
One deliberate annotation fix: `digest_items: list` (was implicit)
— runtime-identical, required to keep `pyright src` at 0 errors
(the only post-move defect found, fixed before commit).
No helper object, no DTO, no `__all__`, no package exports.

## §4 Files Changed

Per §2. Production: 1 moved-from (controller) + 1 new module.
Tests: 1 new file. Docs/config/deps: none.

## §5 Characterization Tests

`tests/test_s1_detector_rows.py`, 10 tests, green pre- AND
post-extraction without assertion changes (facade preservation
proven — only an import-sort + docstring touch, no logic touch):
C1 row-shape exact dicts + invalidated flag + detection outcome;
C2 sorted evidence + cid-deterministic output; C3 p1/p2 disjoint;
C4 retracted refs contribute nothing + `recorded: []`; C5 corrupt
rows skipped, pair still detected; C6 empty `[]`; C7 repeated
identical incl. duplicate-on-redetect semantics; C8
rebuild-identical rows across fresh DBs.

## §6 Before/After Behavioral Equivalence

| Property | Before (558a8d5) | After (231cd75) | Result |
|---|---|---|---|
| Row shape | 7-field dicts | identical (C1 asserts) | PASS |
| Ordering | digest order in, sorted evidence, cid-sorted N1 out | identical (C2) | PASS |
| Project isolation | per-query predicates | identical (C3) | PASS |
| Retraction behavior | N9 skip at derivation | identical (C4 + N9 suite 21/21) | PASS |
| Exceptions | fail-safe skips, raisers untouched | identical (C5) | PASS |
| Empty results | `[]` | identical (C6) | PASS |
| Determinism | rebuild-identical | identical (C7/C8 + cross-run IDs) | PASS |
| Identity behavior | consumed only | unchanged (no authoring in moved code; N9 identity tests green) | PASS |
| Transaction context | caller-owned, none opened | unchanged (0 BEGIN/COMMIT in new module, grep-verified) | PASS |
| Lease/fence context | untouched reads | unchanged (no lease/fence symbols in new module) | PASS |
| N9 boundary | predicate consumed | unchanged (same call, same position; N9 suite green) | PASS |
| Public API | 30 Controller methods | unchanged (wrappers preserve names/signatures; no `__all__`) | PASS |

Mechanical proof: normalized old-vs-new body comparison shows
identical SQL sets (1/2/0 statements) and zero keyword
divergences across all three functions.

## §7 Transaction Preservation

New module: 0 `BEGIN/COMMIT/ROLLBACK` (grep-verified), 0
`apply_intent`, 0 `INSERT/UPDATE`. Reads execute in the caller's
context exactly as before (same conn object passed through).
Gateway + repository transactions untouched. No new tx, no moved
boundary, no independent commit, no retained connection.

## §8 Lease/Fence Preservation

No lease acquire/release/refresh/validate in moved code or
wrappers; fence object never referenced; reads pass through
unfenced identically (`_FencedConnection` only gates writes).
`source_artifact_retracted` import removed from controller (sole
use moved with the code — no dead import; ruff confirms).

## §9 Authority Preservation

No HumanDecision/gate/credential/verdict paths in S-1; refusal
generation untouched (skips preserved verbatim); authority-then-
mutation order lives in `_detect_contradictions_pass` and verdict
surfaces, none of which moved.

## §10 Identity/Idempotency Preservation

Hashes/ids read only; `sorted()` is ordering, not authoring;
duplicate handling stays in the gateway tx. No UUID/hash
generation added (grep-verified: no `uuid/hashlib/random/clock`
in the new module).

## §11 Project Isolation

`project_id` explicit at all three signatures; every query
predicates `project_id = ?`; decision-row project join preserved
inside the unchanged predicate call. C3 proves disjointness.

## §12 N9 Preservation

Same predicate, same call position, same skip semantics; N9
admission/validator/in-tx paths untouched (`source_outcomes.py`,
gateway, `failure_classifications.py` byte-identical —
`git diff` shows controller-only production change). N9 suite
21/21 green post-extraction; P7 residual stays closed
(fresh-pair refusal + empty detection re-verified via N9 tests).

## §13 Replay/Determinism

No timestamps/UUIDs/providers/env in moved code; inputs
(committed rows + oldest-first digest) fully determine outputs;
N1 output cid-sorted regardless. Rebuild-identical rows (C8) +
cross-run identical contradiction IDs (P7 probes) confirm.

## §14 API Surface

No new supported API: new module has no `__all__`, is
undocumented as a surface, and is INTERNAL per A-05. Wrappers
preserve the 30-method Controller surface byte-for-byte in
signature. No package exports modified. DG-2 §16 guards honored.

## §15 Dependency Direction

`Controller → contradiction_candidates → persistence`
(`source_outcomes` predicate, `repositories.ContradictionRepository`
function-level as before). No `contradiction_candidates →
controller/gateway` edge (grep-verified; only docstring mentions).
No cycle (persistence never imports the new module).

## §16 Diff Review

Controller diff: +19/−90 — import-line swap, three wrapper
replacements, zero other hunks (full-diff reviewed). New module:
moved bodies + seam docstring. Tests: additive file only (plus
import-sort/docstring touch). No formatting churn, no renames,
no comment rewrites beyond wrapper pointer docstrings.

## §17 Validation

- New tests: 10/10 (pre- and post-move, assertions identical).
- Slices: chg1 + N9 + p6 + hr08 + controller suites green.
- Full suite: **2045 collected (2035 + 10 new), 0 failed,
  0 errors, 0 skips** (JUnit XML).
- `ruff check src tests`: clean (one self-introduced I001 found
  and fixed pre-commit).
- `pyright src`: 0 errors (one self-introduced iterable-typing
  error found and fixed pre-commit with annotation-only change).
- Tests profile: 0 errors + 1 pre-existing warning
  (`test_research_program.py:141`, untouched).
- `git diff --check`: clean.

## §18 Adversarial Review

1. Logic changed in move? PASS (normalized equivalence proof).
2. SQL changed? PASS (identical sets). 3. Ordering? PASS (C2).
4. Exceptions? PASS (C5 + verbatim skips). 5. Tx moved? PASS
(none exist). 6. Connection lifecycle? PASS (pass-through).
7. Lease/fence? PASS (untouched). 8. Authorization? PASS (none
present). 9. Identity authoring? PASS (none). 10. Predicates?
PASS (all preserved). 11. N9 duplicated/bypassed? PASS (same
call, N9 suite green). 12. Provider access? PASS (none).
13. Nondeterminism? PASS (C7/C8). 14. New public API? PASS
(no `__all__`, INTERNAL per A-05/DG-2). 15. Unrelated cluster?
PASS (diff touches S-1 methods + 1 import only). 16. Module
imports Controller? PASS (verified absent). 17. Direction
clean? PASS (§15). 18. C1–C8 covered? PASS (10 tests).
19. Revertible? PASS (single commit, no migration/state).
20. Exactly one seam? PASS (3 functions, one concern).
Result: 20 PASS, 0 FAIL.

## §19 Residual Risks

None blocking. Notes: (a) S-1 function names are public-
spelled but INTERNAL by status — future readers must check
A-05, not the prefix (recorded in code docstring). (b) Dual
retraction surfaces unchanged (out of scope; reconciliation
stands). (c) Next seams (S-2+) remain YELLOW/RED per DG-2.

## §20 Final Certification

```text
S-1 — CERTIFIED / CONTROLLER EXTRACTION SUCCESSFUL
```
