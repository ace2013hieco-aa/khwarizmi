# MERGE-LOG-NUM-1 — merge/num-1 (suite-count single source of truth + F1/F2 fix)

- Repo: `D:\New folder\research-agent` (GitHub `ace2013hieco-aa/khwarizmi-research`)
- Branch: `main` (fast-forwarded **locally**; merge worktree `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\num-1-merge-wt`) — **LOCAL-ONLY, NO PUSH**
- Task: NUM-1-MERGE — land `slice/num-1-counts@61c1ceb` + `fix/num-1-f1f2@bd9d1eb` (merge gate only)
- Verdict: **PASS** — `main` verified unmoved, clean fast-forward, every cited hash preserved; stamp
  `--check` OK (4440); collect 4440; B4 24/24; ruff clean; pyright src 0/0/0; pyright tests-config
  108 (documented env baseline, delta 0); full-suite red set == the documented environmental
  baseline **exactly** (delta 0, no new red). **Nothing pushed.**

## Lineage (verified, not assumed)

Linear topology; the whole advance was a single fast-forward, so every cited hash is preserved
byte-for-byte (no rebase, no `--no-ff` merge commit, no manual hunks, no conflict markers):

```
main  092b5455e6280a7dc16b3154785a6441c4c85669   (verified unmoved before the FF)
 ├ b71bbdfc5ec95e226b365dbb725f1abe24ac54df   feat(num-1): suite-generated single source of truth for suite size
 ├ 61c1ceb48096ae92354a0d8d364c7a6cf923835d   docs(num-1): point governed count lines at SUITE-COUNT.md, regenerate B4 fixtures
 └ bd9d1ebb7eddfb52bc97358602cccc40ed1751af   fix(num-1): close audit F1 + F2  == fix/num-1-f1f2 tip
```

- `git rev-parse main` (before) == `092b5455e6280a7dc16b3154785a6441c4c85669` → **unmoved** (no STOP).
- `git merge-base --is-ancestor 092b545 bd9d1eb` → true (**FF-able**; rebase prohibited D1, not used).
- Fast-forward executed as a **pure ref move** (`main` is checked out in the FRONT-1 merge worktree,
  so the advance was applied with the compare-and-swap form rather than a checkout):
  `git update-ref refs/heads/main bd9d1eb 092b545` → `FF OK`.
- `main`: `092b5455e6280a7dc16b3154785a6441c4c85669` → `bd9d1ebb7eddfb52bc97358602cccc40ed1751af`.
- `092b545` remains an ancestor of the new `main` → **pure fast-forward**.
- `origin/main` observed unchanged at `092b545…` — **no push performed**.

## Audit + fix record carried (referenced by hash, not re-committed)

- `AUDIT-NUM-1-REDTEAM.md` @ `audit/num-1-redteam@559abf0` (that branch adds this one file only).
  Verdict carried: **PASS-WITH-SHOULD-FIX** (0 MUST-FIX / 2 SHOULD-FIX / 4 informational).
- Fix record: `fix/num-1-f1f2@bd9d1eb` (F1 + F2 closed).

## Adjudication (audit findings → disposition)

| # | Finding (audit `559abf0`) | Disposition |
|---|---|---|
| F1 | `_check_tree` compared `str(Path)` against a raw `PYTHONPATH` split — the documented forward-slash form refused on Windows | **VALID → FIXED** `bd9d1eb` — both sides canonicalized (`os.path.normcase(os.path.normpath(...))`); native, forward-slash and mixed spellings accept, wrong-tree/missing still refuse (fail-closed unchanged) |
| F2 | Nothing enforced `docs/SUITE-COUNT.md` freshness — the stamp could drift silently | **VALID → FIXED** `bd9d1eb` — `--check` mode (re-derives the live count, non-zero on drift/missing/unparseable, writes nothing) + a CI step in the `test` job |
| F3 | Parser takes the *first* `N tests collected` match | **INVALID** — not a defect: pytest's capture swallows stray module-level prints and the `returncode != 0` guard rejects a broken collect; spoof probe verified non-exploitable |
| F4 | `docs/SUITE-COUNT.md` is not eol-pinned | **INVALID** — not a defect: nothing hashes the artifact (it is not a corpus member); the B4 `skipped` mention derives from `AGENTS.md`/`docs/STATE.md` bytes, which *are* pinned |
| F5 | `scripts/` sits outside the canonical lint gate | **INVALID** — pre-existing repo convention, not introduced by this slice; the new script is individually ruff-clean |
| F6 | `docs/STATE.md:11` wording nit | **CARRIED** — optional; `docs/STATE.md` is corpus-pinned (touch only via sanctioned regen) → deliberately not edited |

**Adjudication: INVALID ×3 (F3/F4/F5) · direction VALID (F1+F2, closed) · F6 carried.**

## Changed files (092b545..bd9d1eb)

```
9 files changed, 216 insertions(+), 8 deletions(-)
```

```
M .github/workflows/ci.yml            (+10: NUM-1 freshness step in the `test` job)
M AGENTS.md                           (count line → pointer; 1 line)
M docs/STATE.md                       (count line → pointer; 1 line)
A docs/SUITE-COUNT.md                 (GENERATED; Collected: 4440)
M docs/gr3-b4/b4-fixtures/README.md   (+18: NUM-1 re-derivation note)
R056 550fcc00… → 35f4aca6…  (b4-c1)   content-addressed fixture rotation
R054 06dea9db… → 75a1ac2b…  (b4-c2)   content-addressed fixture rotation
R066 d1312f01… → f54a8f40…  (b4-c4)   content-addressed fixture rotation
A scripts/stamp_suite_count.py        (+169: generator + `--check` freshness gate)
```

`b4-c3` (`eef41946…`) is unchanged (IDR-only stratum). `AGENTS.md`, `docs/STATE.md` and
`docs/SUITE-COUNT.md` are **byte-identical** to the slice tip (see STOP-condition checks below).

## Gates (raw, on landed tip `bd9d1eb`, offline)

- **Stamp `--check`** → `OK: docs\SUITE-COUNT.md collected=4440 matches the live collect` (exit 0).
- **collect** (`--collect-only`, no extra `-q`) → `4440 tests collected in 6.60s` (exit 0).
- **B4 surface** → `64 passed in 5.61s` (`tests/test_b4_ref_graphs.py` = **24/24**).
- **Ruff** `ruff check src tests` → `All checks passed!` (exit 0).
- **Pyright src** → `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests** (`--pythonpath <abs-venv-python> --project pyrightconfig.tests.json`) →
  `108 errors, 1 warning, 0 informations`. Every error is
  `Import "pytest" could not be resolved (reportMissingImports)` — the documented sandbox env
  baseline (pyright here resolves only its typeshed fallback and never loads the venv
  `site-packages`). This is **the documented 108-env baseline (delta 0, not zero)**.
- **Full suite** `PYTHONPATH=<worktree>/src .venv/Scripts/python.exe scripts/run_tests.py` →
  `5 failed, 4432 passed, 3 skipped, 1 warning in 613.98s` (`EXIT=1`).

## Red set == documented baseline (exact)

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

These are **exactly** the 5 pre-existing environmental reds documented in
`docs/archive/MERGE-LOG-CLOUD.md` (3 concurrency races + 1 Windows symlink-privilege refusal +
1 q05 race), reproduced verbatim in `docs/MERGE-LOG-FRONT-1.md`. The landed `4432 passed`
matches the documented figure. **Red set == documented set (exact); no new red; delta 0.**
`main` was verified unmoved before the FF, so this is a like-for-like comparison.

### Flake note (recorded, not a regression)

`tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree`
is the documented 30 s pinned-subprocess-timeout flake. It was observed once during the NUM-1-FIX
run (`pinned_test … timeout after 30.0s`) and **did not fail in this landed run**; it passes in
isolation on both the fix tree and the untouched slice tip. It is **not** in the red set, so no
isolation proof is required for this merge.

## STOP-condition checks

| Condition | Result |
|---|---|
| main moved before the FF | **PASS** — unmoved at `092b545…` |
| red set is a superset of baseline | **PASS** — exact equality (delta 0) |
| SUITE-COUNT drift (`--check` fails) | **PASS** — `--check` OK, collected 4440 |
| `docs/STATE.md` / `AGENTS.md` bytes differ from slice tip | **PASS** — identical (blob sha256: `AGENTS.md` `4b603e5b6e095606f64148f6ba246e8041f1b9b9a10a9c29bceff5c9859e5db4`, `docs/STATE.md` `fef61128e2d114b5d3a842195c436861cd7febc7bc6c9a72433c49e6a7a7b975`, `docs/SUITE-COUNT.md` `b0268bb348a529fc5d2a9b14631db136ff6e39028cecd55b608505f3e6c0fb3c`) |
| push without a human hash-pin | **none performed** |

## Push charters (DRAFTED, NOT EXECUTED)

D8/D9: every push requires explicit human approval and a hash pin. **No `git push` was run.**

**Charter A — `khwarizmi-research` (origin)**
- Remote: `origin https://github.com/ace2013hieco-aa/khwarizmi-research.git`
- Proposed (hash-pinned): `git push origin <reviewed-main-hash>:refs/heads/main`, where
  `<reviewed-main-hash>` is `main` at review time (the FF'd tip plus this log commit).
- Preconditions: human approves; `origin/main` still at/behind
  `092b5455e6280a7dc16b3154785a6441c4c85669`; local tree clean; the pushed hash equals the
  reviewed hash. No `--force`.

**Charter B — `khwarizmi` public mirror (orphan-sync convention)**
- Remote: **not configured in this checkout** — `git remote -v` lists only `origin`; the mirror
  URL/name must be supplied by the director (the in-repo docs carry no orphan-sync text).
- Convention: orphan-sync — the mirror branch is parented on the mirror's current HEAD (its
  parent is the mirror HEAD, not this repo's history), and it is **never force-pushed** (rule #5).
- Proposed (hash-pinned): `git push <mirror-remote> <reviewed-main-hash>:refs/heads/main`
  (no `--force`).
- Preconditions: mirror is public — director confirms the Apache-2.0 tree carries no non-public
  material; same reviewed hash as Charter A; human approves each push.

## Credential-path statement

- No live vendor calls and no real credentials were used. All gates ran offline; the test stack
  uses recorded transports (`RecordedTransport`). The `--check` freshness gate performs only a
  local `pytest --collect-only`.

## NOT-LIST scan

`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy` over `092b545..bd9d1eb` (commit subjects,
bodies, and the changed-file list): **no hits**.

## STOP BEFORE PUSH

`main` is fast-forwarded **locally only**. Nothing is pushed. Both charters above require a human
hash-pin before execution.
