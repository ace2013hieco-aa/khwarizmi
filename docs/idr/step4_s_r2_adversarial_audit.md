# STEP4 / S-R2 adversarial audit — regime-axis wiring

**Status:** COMPLETE — verdict **PASS**
**Date:** 2026-09-27
**Audited:** `step-4/s-r2@c28df44` (files: `src/hermes/research/regimes.py` +231,
`src/hermes/research/programs.py`, `src/hermes/persistence/failure_classifications.py`,
`src/hermes/persistence/repositories.py`, 6 test files, IDR-044 addendum)
**Auditor:** fresh independent session (adversary role); falsify-don't-confirm
**Method:** independent re-derivation + 15 executable attack checks in two batteries
(all reproduced against the audited commit; scripts run from outside the repo at
`Temp/opencode/s_r2_attack.py` 11 checks + `s_r2_deep.py` 4 checks; read-only except this record)

## Inputs confirmed (receipt)

1. `c28df44` file list re-derived via `git show --stat` — matches charter
   (regimes.py +231 transition layer, programs.py, failure_classifications.py,
   repositories.py, test_regimes/test_research_program/test_gateway/test_q05/
   test_claims_write_path/test_program_obligations, IDR-044 addendum).
2. S-R1 audit C1 **re-derived, never consumed**: forged `RegimeEvaluation`
   (unregistered ref + resolved verdict) passes `authoritative_verdict`
   (returns `IN_REGIME`, no refusal) — the F-3 hole is real at S-R1 and still
   present in the unit at S-R2 by design; INDETERMINATE still refuses with the
   exact code `INDETERMINATE_NOT_AUTHORITY`. Four binding rulings re-stated from
   the audit record: (1) versioned pairs + freeze-at-classification,
   (2) INDETERMINATE closed-enum + decision-inertness,
   (3) mainline-scoped IDR numbering, (4) Literal-AND-guard lands in S-R2.
3. Pre-change integration points re-derived from `main@c0b5777` bytes (not the
   report): `programs.py` has no `resolve_regime`/`parse_regime_ref` and keeps
   the free-string guard; `failure_classifications.py` keeps
   `regime_resolver=None` + the `ENVIRONMENT_MISMATCH is not ...` refusal;
   `repositories.py` keeps the `form-checked ... DEFERRED phases` stance with no
   `resolve_regime`. Post-change wiring present at `c28df44`.
   Prohibited-reference scan (`git grep` at `c28df44`): no hits — clean.

## Attack results (15 checks, 0 BROKEN)

- **(1) C1 substrate — HELD.** `derive_transition` signature has no
  `evaluation`/`response`/`verdict` parameter; forged kwargs die `TypeError` at
  the boundary (both directions attempted). Response re-derived from
  registry + snapshot on every call (low-vol-declared yields `IN_REGIME`;
  undeclared yields `INDETERMINATE` regardless of offered evidence).
- **(1) C1 programs — HELD.** Forged `target_regime` refuses with exact codes:
  `ICSS-v1:high-vol`/`ICSS-v2:low-vol` → `UNREGISTERED_REGIME`;
  `low-vol`/`regime-A` → `UNVERSIONED_REGIME`; registered `ICSS-v1:low-vol`
  compiles; deserialized JSON payload (`ICSS-v1:evil`) refuses identically.
- **(1) C1 failure-classifications — HELD (unit + end-to-end).** `_regime_resolver`
  admits only the registered tag; full write-path forge (caller-authored
  `claimed` for unregistered `ICSS-v1:trend`) dies `FailureClassificationError`
  at the re-run BEFORE any claimed comparison, 0 rows; registered-tag positive
  control admits with decision `NEW`.
- **(1) C1 claims — HELD.** Live resolver admits only the registered tag
  (`methodology` still form-checked — no overreach); hand-marked `ADMITTED`
  extraction with `ICSS-v1:evil` dies `dangling context ref` at the write path,
  0 rows, 0 edges (substrate form-check admits, boundary re-check kills).
- **(2) SIMULATED both directions — HELD.** Omission refuses `TypeError`;
  every mistag (`LIVE`, padded, empty, lowercase, truncated, `None`, `0`,
  bytes) refuses `INVALID_TRANSITION_PROVENANCE`; deserialized dict omission
  still `TypeError`, deserialized mistag still coded refusal, exact `SIMULATED`
  from JSON admits; no `from_dict`/bypass helper exists on the module.
- **(3) INDETERMINATE inertness end-to-end — HELD.** No-tag snapshot evaluates
  `INDETERMINATE`; `authoritative_verdict` and `authoritative_transition` both
  refuse `INDETERMINATE_NOT_AUTHORITY`; `INDETERMINATE` + evidence refuses
  `EXTRANEOUS_TRANSITION_EVIDENCE`; resolved-but-uncited refuses
  `TRANSITION_EVIDENCE_REQUIRED` — all through `derive_transition`, not the unit.
- **(4) Delta-0 — HELD (recomputed, not trusted).** Ordinary program compiles
  with zero regime codes; canonical preimage contains no `target_regime` /
  `parent_program_id` keys; content hash independently recomputed with plain
  `hashlib.sha256` over `canonical_json` matches `program.content_hash`, and
  `program_id == "rp_" + hash[:24]`. Pre-change bytes at `c0b5777` already
  guard both preimage emitters with `if program.parent_program_id is not None`,
  so the all-None case is byte-identical pre/post.
- **(5) Ladder/SUPPORT_STATES — HELD via real paths.** `SIMULATED ∉ SUPPORT_STATES`;
  `LadderTarget("SIMULATED")` raises `ValueError`; claim with
  `support_state="SIMULATED"` validates `INVALID` on the real extractor path;
  `derive_program_obligations` output for a `SUPPORTED` hypothesis contains no
  `SIMULATED`; satisfaction record with artifact type `SIMULATED` refuses.
- **(6) No-migration — HELD.** `git diff c0b5777..c28df44` over
  `migrations.py` and `migrations/` is empty; runtime schema is v19
  (`SUPPORTED_VERSION`); `research_claims` has no regime column;
  `research_programs.target_regime` is the pre-existing ADR-041 column.
- **C2 — HELD.** Bare-string evidence refs → `MALFORMED_EVIDENCE_REFS`;
  bare-string/non-pair context tags → `MALFORMED_REGIME_CONTEXT`.
- **Rulings — HELD.** (1) version games + post-outcome `TypeError` covered by
  the green suite, `evaluate_regime`/predicate/`REGISTRY` bodies untouched by
  the S-R2 delta (transition layer appended); (2) inertness re-proved above;
  (3) skeleton text at `c28df44` states the mainline-scoped ruling verbatim;
  (4) `evaluate_regime` fixes no single-condition semantics — composed
  AND-predicates remain expressible, nothing preempts the guard.

## Gates re-run

Full suite green (`scripts/run_tests.py`, all dots, 0 failures);
`ruff check src tests` clean; `pyright src` 0 errors;
`pyright tests` 0 errors + 1 pre-existing warning in the untouched file —
matches the slice commit's claim.

## Observation (no action, pinned for S-R4)

O-1 (P3, not a defect): direct `RegimeTransition(...)` construction accepts a
caller-chosen `response` contradicting the snapshot (reproduced: registered ref
+ `NOT_IN_REGIME` constructs while the snapshot declares low-vol). By design
only `derive_transition` output is authoritative and every S-R2 wiring point
re-derives — but S-R4 consumers owe the same stance (re-derive, never consume a
constructed transition), the A3 precedent carried forward.

## Verdict

**PASS** — C1 discharged at every wiring point with forged-caller evidence,
both SIMULATED directions (incl. deserialized) refuse, INDETERMINATE is inert
end-to-end, Delta-0 recomputed independently, ladder/SUPPORT_STATES refuse on
the real obligation path, no migration. No stop condition triggered: no src/
edit (`git status` clean except pre-existing untracked files), no push, every
finding evidenced.
