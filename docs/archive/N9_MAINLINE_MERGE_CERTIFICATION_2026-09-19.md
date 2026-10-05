# N9 Mainline Merge Certification — 2026-09-19

## 1. Repository identity

- Repository: `ace2013hieco-aa/khwarizmi-research`
- Branch: `main`; HEAD at merge time `fce59b8`; tree clean (untracked only:
  pre-existing `.freebuff/`, `IDEA.md`).

## 2. Pre-merge baseline

- `origin/main` = `fce59b8` (post-P6 work through IX docs, uncertified for P7).
- `origin/n9-closure` = `02cb976`; merge base `ff79bb6` (unambiguous).
- PR #1: base `main`, head `02cb976`, state OPEN, exactly 1 commit,
  `mergeable: MERGEABLE`, `mergeStateStatus: CLEAN`.

## 3. PR identity

PR #1 `fix(research): fence retracted evidence from new classifications`,
head `02cb976684b5a3a0eb49df1e16b38cb8c1298531`, parent verified
`ff79bb64a656d08209ba417080c978dc05937846`. No additional commits; no drift
(remote head == certified commit, empty diff).

## 4. Certified implementation commit

`02cb976` — diff vs `ff79bb6` limited to 5 files (+94/−10, 1 new test file):
`source_outcomes.py` (+25 predicate), `failure_classifications.py`
(substrate resolver + in-tx re-check), `controller.py` (candidate
derivation filter), `gateway.py` (validator resolution + in-tx
re-resolution), `tests/test_n9_retraction_admission.py` (new).
`_source_artifact_resolves` unchanged; no S5/N1/journal/migration/API/
provider changes (verified by sentinel grep over the diff).

## 5. Merge method

`gh pr merge 1 --merge` (merge commit; squash/rebase forbidden and not
used). Repo policy allows merge commits. No conflicts (GitHub CLEAN).

## 6. Resulting main SHA

`e37cd009152ad92e26e675780cd8713cb36a9827`
(`Merge pull request #1 from ace2013hieco-aa/n9-closure`, 2026-09-19T18:47:18Z).

## 7. Ancestry verification

- Parents: `fce59b8` + `02cb976` (both verified via `rev-parse ^1/^2`).
- `02cb976` is an ancestor of `main` (`merge-base --is-ancestor` true).
- `git diff fce59b8..e37cd00 --stat` == the 5 N9 files only.
- All N9 hunks present in the merged tree (`source_artifact_retracted`
  call sites in all 4 src files; `fresh_a` in-tx re-resolution in gateway).
- No unexpected commits (merge has exactly 2 parents; no other refs moved).

## 8. N9 test results (merged main)

`tests/test_n9_retraction_admission.py`: **21 cases, 0 failed, 0 errors**
(N9-A 2, N9-B 1, N9-CD 2, N9-EF 2, N9-G 1, N9-H 1, N9-I 1, N9-J 2,
adversarial 9).

## 9. Adversarial results (merged main)

9/9 in-file adversarial tests pass (duplicate retraction STALE, duplicate
classification idempotent, invalidated party excluded, journal-failure
rollback, no-partial-state refusal, lease LOCK, redetect-after-resolve,
supersession path, direct-intent refusal).

## 10. Full regression results (merged main)

**2035 collected, 0 failed, 0 errors, 0 skips** (JUnit XML). Delta vs the
2034 certified on the branch is +1 from main-side `test_chg1_contradictions.py`
additions (post-P6, pre-existing on main) — explained, not N9-related.

## 11. Static-analysis results (merged main)

- `ruff check src tests`: clean.
- `pyright src`: 0 errors, 0 warnings.
- `pyright --project pyrightconfig.tests.json`: 0 errors + 1 pre-existing
  warning (`test_research_program.py:141`, untouched).

## 12. Behavioral smoke evidence (merged main, 9/9 in 2.95s)

1. Fresh cite refused — `TestN9A::test_fresh_citation_after_retraction_refused`
   (`MALFORMED_PAYLOAD`/`EVIDENCE_DOES_NOT_RESOLVE`, 0 rows).
2. Pre-retraction row excluded post-retraction —
   `TestN9H::test_detection_after_retraction_excludes` (`recorded: []`).
3. Replay cannot bypass — `TestN9I::test_replay_does_not_resurrect_validity`
   (byte-identical, 0 live contacts, citation refused).
4. Detection excludes — `TestN9Adversarial::test_direct_contradiction_intent_over_retracted_refused`
   (`_cx_resolve_evidence_ref` → None; hand-built intent `EVIDENCE_REF`).
5. In-tx revalidation active —
   `TestN9Adversarial::test_refusal_leaves_no_partial_state` (0 artifacts/
   edges/contradictions; refusal audit rows only) + checks placed inside
   `BEGIN IMMEDIATE` (`failure_classifications.py`, `gateway.py`).
6. Isolation intact — `TestN9CD` both tests (cross-project refused;
   per-project governance).
7. S5 unchanged — `TestN9B` + `test_supersession_path_unaffected`
   (SUPERSEDED lifecycle, STALE/duplicate semantics intact).

## 13. Remote CI evidence

- Push run on merged SHA `e37cd00`: run `35462313369`, event `push`,
  **6/6 jobs success on real runners** (tests 14m44s, typecheck, lint,
  smoke, profiled gate, audit; no skips, no hidden failures).
- PR-head run `35461413080` (SHA `02cb976`): 6/6 success.
- Tested SHA == `origin/main` at verification time.

## 14. Scope-integrity verification

Merge delta vs pre-merge main is N9-only (controller.py delta is exactly
the N9 hunk; STALE guard, cone/blast-radius, tick-loop wiring, N1,
migrations, events/intents, providers untouched — verified by diff +
sentinel grep). Out-of-scope items unchanged: #1 STALE project filter
(present wart, not modified), #2 ancestor semantics (cited-artifact
scope preserved), #3 tick-loop wiring (pre-existing on main, merge
added nothing to it), #4/#5 no contradiction/provider changes.

## 15. Final verdict

### A — MAINLINE N9 CERTIFIED

## 16. P7 status

**P7 has NOT yet been rerun against the new mainline.** The post-P6
tick-loop work on main (`633cff1`, `2328399`) remains separately
uncertified and must be gated on its own before any P7 rerun claims.
