# MERGE-LOG-CLOUD — merge/cloud (provider seam + hardening)

- Repo: `D:\New folder\research-agent` (GitHub `ace2013hieco-aa/khwarizmi-research`)
- Branch: `merge/cloud` — **LOCAL-ONLY, NO PUSH**
- Worktree: `D:\New folder\merge-cloud-wt` (isolated; `PYTHONPATH=<worktree>/src`)
- Task: MERGE-CLOUD — land the provider seam + hardening (D9, merge + verification only)
- Verdict: **PASS** — clean FF through both tips, hashes preserved; all 81 new tests
  green; ruff + both pyrights green; full-suite red set == the documented pre-existing
  environmental baseline (delta 0, no new red). **Nothing pushed.**

## Lineage (verified, not assumed)

Linear topology; both advances were fast-forward, so every cited hash is preserved
byte-for-byte (no rebase, no `--no-ff` merge commit, no manual hunks, no markers):

```
main               5d602ee3370aa614aecbc194515cb30ff6ed895f   (verified unmoved first)
  └─ FF #1         876318c3570cfc1d6668f299d677bbc80ba64db7   slice/cloud-provider
       └─ FF #2    9332e27267f5abba05f80905f9485480b4b9a6b7   fix/cloud-harden  == merge/cloud tip
```

- `git merge --ff-only slice/cloud-provider` → `Updating 5d602ee..876318c  Fast-forward`
- `git merge --ff-only fix/cloud-harden`    → `Updating 876318c..9332e27  Fast-forward`
- `git merge-base --is-ancestor 876318c HEAD` → true; same for `9332e27`.
- `git diff --stat HEAD fix/cloud-harden` → **empty** (merged tip tree is identical to the
  cited fix tip). `git status` clean post-FF.
- `main` untouched; `origin/main` observed at `5d602ee` (unchanged, no push performed).

## Audit carried (byte-identical)

- `audits/AUDIT-CLOUD.md` is in fact at the repo **root** as `AUDIT-CLOUD.md` on
  `audit/cloud-provider@4b1f44ee60008e7ce5283a4b2f74eb74cc6afc58`
  (that branch adds this one file only, +209 lines vs `main`).
- Blob `52325efb46c1b7be69b393aae88643187d66e242` — carried **unmodified**
  (referenced by hash; not re-committed here — this merge commit is one file).
- Verdict carried: **PASS, 0 MUST-FIX** (~150 offline probes across A–F: A16/B36/C35/D54/E9/F14).

## Changed files (main..HEAD) — no `src/` authored on the merge branch

```
 src/hermes/composition.py        | 369 +++++++++++++++++++++   (new)
 src/hermes/tools/models/cloud.py | 581 ++++++++++++++++++++++++   (new)
 tests/test_cloud_provider.py     | 695 ++++++++++++++++++++++++   (new)
 3 files changed, 1645 insertions(+), 0 deletions(-)
```

All three are additions carried by the cited slice/fix commits; the merge branch itself
authors **no** `src/` change (only this log).

## Gates (raw, on merged tip `9332e27`, offline)

- **81-test file** (`tests/test_cloud_provider.py`):
  `81 passed in 1.43s`; `--collect-only -q` → `tests/test_cloud_provider.py: 81`.
- **Full suite** (`scripts/run_tests.py -q`, `PYTHONPATH=<worktree>/src`):
  `EXIT=1`; JUnit `errors=0 failures=5 skipped=3 tests=4440` (**4432 passed**, 605.03s).
  The 5 are **exactly** the pre-existing environmental reds documented on the merge base
  (`MERGE-LOG-DEMOS.md` on `main@5d602ee`), verified against a `main` baseline run
  (`errors=0 failures=5 skipped=3 tests=4359` → 4351 passed; **identical red set**):
  ```
  FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
  FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
  FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
  FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
  FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
  ```
  Concurrency races + a Windows symlink-privilege refusal — environmental, not code.
  `4440 = 4359 + 81`; `4432 = 4351 + 81` — the +81 is exactly the new cloud file.
  **Red set == documented set (exact). No new red.**
- **Ruff**: `ruff check src/hermes/tools/models/cloud.py src/hermes/composition.py tests/test_cloud_provider.py`
  → `All checks passed!`; `ruff check src tests` → `All checks passed!`.
- **Pyright src**: `0 errors, 0 warnings, 0 informations`.
- **Pyright tests** (`--project pyrightconfig.tests.json`): `0 errors, 1 warning, 0 informations`
  — the single warning is pre-existing and unrelated
  (`tests/test_research_program.py:144:23` missing-`self`).

### Flake note (recorded, not a regression)

One earlier merged-tip suite run showed a 6th failure,
`tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree`,
whose message is a **pinned-subprocess timeout** (`...test_a_crash_after_progress...: timeout
after 30.0s`). It **passes in isolation** (file: 201 passed; class: 7 passed), the pinned
test passes standalone on both trees, and it did **not** recur in the confirming clean run.
Classified as a load/timing flake (matrix canary budget = 30 s), not a merge regression.

## Credential-path statement

- **Source of truth**: the operator env store only. `CloudModelSpec` names the env var
  (`api_key_env`); the key is read at request time and, if unset, the request **fails
  closed pre-dial** with `CREDENTIAL_MISSING` (`cloud.py:513`), 0 transport specs.
- **Placement**: the secret is injected **only** into `RequestSpec.headers_meta` —
  `x-api-key` for Anthropic (`cloud.py:364-365`), `authorization: Bearer` for OpenAI
  (`cloud.py:427-428`). It never enters the body, URL, or params (`params=={}`).
- **Body tripwire**: a prompt carrying the live key raises `ModelPlaneInvariantError`
  **before** any transport call (`cloud.py:527`); the message names no secret.
- **Never recorded**: `RequestSpec.headers_meta` is never persisted by
  `RecordedTransport`; `ModelCall` carries no credential field; records are redacted and
  secret-scanned on every path.
- **Host pinning**: a host override may only name a code-owned dialect host
  (`_DIALECT_HOSTS`, `composition.py:99`; gate `composition.py:183-187`); the gate is
  re-derived on `dataclasses.replace`.
- **No live vendor calls / no real credentials** were used by any gate above.
- Credential grep over the three payload files (`sk-ant-|sk-proj-|sk-live|xoxb-|xoxp-|
  ghp_|AKIA…|AIza…|BEGIN … PRIVATE KEY|api_key=…`): **0 hits**. Tree-wide `git grep` hits
  are pre-existing synthetic decoys in the secret-scrubber's own fixtures
  (`tests/test_corpus_pack.py`, `tests/cert_gate_rerun/seeded_errors.json`), byte-identical
  between `main` and the merged tip (empty diff) — not introduced here, not live keys.

## SHOULD-FIX follow-ups carried (recorded only — NOT implemented)

From `AUDIT-CLOUD.md` §SHOULD-FIX (0 MUST-FIX):

1. `cloud.py:319-341` — validate `_forwarded` values (finite per-dialect range; reject
   NaN/±Inf and `bool`, today `nan` emits invalid JSON and `True→1.0`).
2. `composition.py:191-201` + `cloud.py:92` — close the dead-knob gap: either declare
   `temperature` in `to_profile().settings.options` (wire the tested path) or remove
   `_forwarded`; add one binding-level test proving the wired stack forwards/refuses it.
3. `cloud.py:381-392,434-459` — refuse unknown Anthropic block types / OpenAI message keys
   loudly (`MALFORMED_PAYLOAD`) instead of silently dropping to empty text.
4. `cloud.py:288-290` (+`router.py:2017-2021`) — plausibility-bound usage magnitude
   (vs `context_window_tokens` + output cap) or flag-and-record.

## STOP BEFORE PUSH

`merge/cloud` is local-only. `main` verified unmoved at
`5d602ee3370aa614aecbc194515cb30ff6ed895f`; **no push performed** and none attempted.
Per task, push is prohibited regardless of outcome.

### Flag for the director

The literal DONE bar "full suite **exit 0**" is unattainable without `src/` edits
(forbidden), because the merge base `main@5d602ee` is itself exit 1 with these same 5
documented environmental reds. This log therefore applies the project's own convention
(`MERGE-LOG-DEMOS.md`: "Red set == documented set (exact). No new red → no stop
condition."): merged red set == baseline red set, **delta 0**, all 81 new tests green.
