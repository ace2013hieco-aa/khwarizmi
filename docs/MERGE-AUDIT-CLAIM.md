# MERGE-AUDIT-CLAIM — audit of merge/claim (claim-ground + experiment-gate-doc-v2)

**Audited tip:** `3faabf274c1c6f12dd04046ab95b90f7bdcac2c6` (branch `merge/claim`, worktree
`D:/New folder/merge-claim-wt`; parents `14bbf909` ← `ac1860a` + `921f0c8`, tip merges `05c3217`).
**Method:** precedent — patch-exactness by blob identity + independent re-proofs. All evidence
reproducible from the commands quoted inline.

## Verdict

**FAIL — conditionally.** Every merge-fidelity proof **PASSES** (integration, patch-exactness,
fabrication re-proofs, migration safety re-proof, count lineage, ruff, both pyrights). The single
failing gate is the **full suite: 9 failures, all `tests/test_b4_ref_graphs.py`** — proven
**inherited verbatim from line tip `05c3217`** (identical 9 test IDs fail at that tip; `921f0c8`
and `main@ac1860a` pass 24/24; the fixture tree is byte-identical between `05c3217` and the merge
tip, so the merge introduced no fixture change). Full attribution and raw counts:
`docs/MERGE-LOG-CLAIM.md` §"B4 failure attribution".

Per the task's STOP conditions, **STOP BEFORE PUSH.** Remediation belongs to the gate-doc line
owner (regenerate + commit `docs/gr3-b4/b4-fixtures/` at the line), not to the merge: a merge
integrator may not introduce content absent from both parents, and the task forbids changes beyond
conflict repair.

## 1. Patch-exactness — PASS

All 23 files of the line delta (`git diff --name-only a8f0180 05c3217`) are blob-identical between
`05c3217` and `3faabf2` except `controller.py` (`63f5c15c` → `14d55dae`), which is proven an exact
content union: content-normalized diff (stripping `index`/`@@`) vs each parent identical in both
directions; 0 conflict markers; blob stable across both merge commits. Key line-file blobs at tip
== line tip: `claims.py 52579bac69bd`, `migrations.py b30c1e898078`, `repositories.py
ee0d12db9095`, `extraction.py c5153987e290`. Zero merge-authored source edits.

## 2. Fabrication re-proofs — PASS (23/23 legs)

Independent probe (`probe_claim_ground.py` harness, 23 legs, run at merge tip with worktree `src` on
`PYTHONPATH`) — raw tail: `PROBE MERGE-CLAIM RESULT: PASS (0 failing legs)`.

**Refusals (fabricated input, fail-closed):**

- **Non-readable carriers refuse with `unverifiable_span_ref`** — 9 carrier shapes probed; the 4
  audit carriers refuse: `dataset_manifest`, `task_evidence`, `task_output`, `validation`
  (plus `pre_registered_experiment`, `model_ref`, `failure_classification` variants). Gate basis:
  `READABLE_TEXT_CARRIERS = frozenset({"source_payload"})` (`claims.py:117`),
  `FAIL_CLOSED_EXEMPT_CARRIERS = frozenset()` (`claims.py:124`), G10 at `claims.py:529-542`.
- **G9 fabricated quote refuses `statement_not_in_source`** — byte check of the claim statement
  against the source payload (`claims.py:560-583`); a quote not present in the carrier refuses.
- **G12 fabricated experiment refs refuse `unverified_experiment_ref`** — 4 ref shapes probed
  (`pre_registered_experiment:exp-1`, `:fabricated-999`, `:`, `:exp-1:replicate-2`); DIRECT
  grounding is admitted only when the referenced experiment exists and is admitted by the
  controller's fail-closed resolver (`controller.py:5402-5407` refusal, wired
  `experiment_resolver=_experiment_admitted` at `controller.py:5428`; gate at `claims.py:636-659`).

**Legitimate flows admit:** span on `source_payload` carrier; genuine byte-present quote;
paraphrase (no quote); DIRECT grounding with admitted experiment; INFERRED/SPECULATIVE grounding
(no experiment requirement); descriptive/baseline claim; `model_ref` propagation into the claim
result (draft-extracted, `None` when absent).

**26-test battery (audit-authored suite) re-run at tip:** `tests/test_claim_ground.py` (26) +
`tests/test_experiment_gate_pin_v2.py` (16) + `tests/test_database.py` + `tests/test_claims.py` +
`tests/test_claims_write_path.py` = junit **tests=168, failures=0, errors=0, skipped=0**.

## 3. Migration safety re-proof (19→20) — PASS

`_migrate_19_to_20` is ADD COLUMN only, over `("model_ref", "prompt_template_version", "run_id")`
on `research_claims`, each guarded by `pragma_table_info` (`migrations.py:1193-1222`; registry
`_MIGRATIONS`, entry `migrate_to_latest` at `migrations.py:1250`). Probe legs (raw probe run at
merge tip):

- **B0–B3 reconstruction:** build a v19-shaped database (drop the 3 columns, reset
  `schema_version` to 19) → `migrate_to_latest()` → all 3 columns exist, `schema_version` = 20.
- **Legacy NULLs survive (no-backfill policy):** rows written under v19 keep NULL in all 3 columns
  after migration; NULL is the documented UNKNOWN representation, no value is invented.
- **Idempotent re-run:** a second `migrate_to_latest()` over the migrated database is a no-op
  (no error, no duplicate columns, version unchanged).

## 4. Count lineage — PASS (exact)

3783 collected at base `main@ac1860a` → **3826** at tip = **+43** = 26 (`test_claim_ground`) +
16 (`test_experiment_gate_pin_v2`) + 1 (`test_claims`). No unexplained delta.

## 5. Full-suite gate — FAIL (inherited, not merge-induced)

junit at tip: `tests=3826 errors=0 failures=9 skipped=16 time=462.586`. All 9 failures are
`tests/test_b4_ref_graphs.py` with `FileNotFoundError:
docs/gr3-b4/b4-fixtures/0ee743f9dcc3fcad0a409c11f881f3cb3cf34dca621a23832824bd415cc43f0b.json`.

Attribution (single-test runs, same interpreter, each commit's own worktree and `src`):

| Commit | B4 result |
|---|---|
| `main@ac1860a` | 24 passed |
| `921f0c8` (claim-ground) | 24 passed |
| `05c3217` (gate-doc) | **9 failed / 15 passed — identical test IDs as merge tip** |

The gate-doc commit edited the B4 corpus sweep sources (`docs/ARCHITECTURE.md` +7,
`docs/STATE.md` +13) without regenerating/committing the content-addressed fixture that the
regenerated corpus now yields (`0ee743f9…`, committed at neither tip). The red exists at the line
tip itself. Fast gates at merge tip: ruff `All checks passed!`; pyright src `0 errors, 0 warnings,
0 informations`; pyright tests `0 errors, 1 warning, 0 informations` — the warning
(`tests/test_research_program.py:144:23 reportSelfClsParameterName`) is pre-existing at
`main@ac1860a`; the line touches that file only at ~:861-896.

## 6. Constraint compliance

| Constraint | Status |
|---|---|
| No `src/` changes beyond conflict repair | **Held** — zero conflicts; zero merge-authored edits (blob table §1) |
| Platform line never touched | **Held** — `main` at `ac1860a` before/after; `a8f0180..ac1860a` intact |
| Isolated worktree | **Held** — all work in `D:/New folder/merge-claim-wt` |
| `PYTHONPATH=<worktree>/src`, absolute `--pythonpath` | **Held** — used for every gate/probe |
| Local-only, no push | **Held** — no push command issued; remote inspected read-only (`git ls-remote`) |
| Forbidden topics (backtest_audit / SDA / TSE / Optimize-my-strategy) | **Clear** — 0 hits in `a8f0180..05c3217` |

## 7. Final verdict

**FAIL as a green-gate certification; PASS as a faithful integration.** The merge is exactly the
union of its inputs; the only red is the gate-doc line's own uncommitted B4 fixture regeneration,
which the merge inherits without alteration. STOP BEFORE PUSH. Next action for the line owner:
commit regenerated `docs/gr3-b4/b4-fixtures/` on `fix/experiment-gate-doc-v2` (or a successor),
then re-merge and re-run the full suite.
