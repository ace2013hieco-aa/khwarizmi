# MERGE-LOG-SUB-1 — local FF of slice/sub-1-restacked@0609086

**Task:** SUB-1-REMERGE (merge gate only — re-stack the SUB-1 commits onto current `main`,
verify, then land; no new scope).
**Repo:** `D:\New folder\research-agent` (GitHub `ace2013hieco-aa/khwarizmi-research`).
**Branch:** `main` (fast-forwarded **locally**; main-bound holder
`C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\met-1-merge-wt`, restack worktree
`C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\sub-1-remerge-wt`) — **LOCAL-ONLY, NO PUSH**.
**Verdict:** **PASS** — `main` verified unmoved at `b240de2`, clean cherry-pick re-stack
(zero conflicts), content-identity proven both directions, clean fast-forward,
stamp `--check` OK (4440), collect 4440, B4 24/24, ruff clean, pyright src 0/0/0,
pyright tests-config 108 (documented env baseline, delta 0), full suite
4432 passed / 5 failed / 3 skipped (red set == documented baseline-5 **exactly**),
`eval_plane` 205 passed in isolation. **Nothing pushed.**

## Re-stack authorization (sanctioned alternative)

- `MERGE-LOG-EXT-0` (`b240de2`) broke the fast-forward for the SUB-1 line: the stack root
  `acee3f7` has parent `3eed0a6`, while `main` advanced to `b240de2` (= `3eed0a6` + the two
  EXT-0 files). A direct FF is therefore **impossible**:
  `git merge-base --is-ancestor b240de2 96399e4` → **false**.
- Rebase-prohibition D1 covers `main`'s shared history. All lines here are **local-only**
  (`main` is ahead of `origin/main`, never pushed), and the Director explicitly authorizes this
  **cherry-pick re-stack** as the sanctioned alternative to the barred ref-move/merge-commit
  (DS-1 precedent).
- Method: worktree at `b240de2` → branch `slice/sub-1-restacked` → cherry-pick
  `3eed0a6..96399e4` **in order, no `-n` squashing, messages kept**. Conflicts would have been
  STOP (zero encountered — no creative resolution performed).

## Lineage (verified, not assumed)

- `git rev-parse main` (before) == `b240de2ad0b5ad11b71ad92524efb8da9f555b5d` → **unmoved**
  (re-verified immediately pre-FF; no STOP).
- Composition pre-check: `git diff --stat 3eed0a6..b240de2` → **exactly 2 files**,
  both additions: `docs/EXT-1-ROADMAP.md` (+27), `docs/MERGE-LOG-EXT-0.md` (+109)
  (`2 files changed, 136 insertions(+)`) — `main` is `3eed0a6` + the EXT-0 landing **only**,
  as briefed.
- Old stack root check: `git rev-parse acee3f7^` == `3eed0a6` → siblings confirmed,
  FF-impossible confirmed.
- `git merge-base --is-ancestor b240de2 0609086` → **true** (**FF-able**).

```
main  b240de2ad0b5ad11b71ad92524efb8da9f555b5d   (verified unmoved before the FF)
  ├ 79dbfef691e0d43b2873eada026415d3b51a5893  docs(sub-1): add docs/judge-demo/Demo.srt from owner-measured beat timings
  └ 0609086d09f8379c61c1cfa92bbaff66f75f9ffb  docs(sub-1): fill CATALYST-DEMO-SCRIPT.md timestamps + YouTube chapters
             == slice/sub-1-restacked tip
```

- Old → new hash map (cherry-pick re-stack, messages kept; author + author-date preserved):

| # | Old (`3eed0a6`-based) | New (`b240de2`-based) | Subject |
|---|---|---|---|
| 1 | `acee3f7ee23f340fe7ea67eb7056adc11c6f8327` | `79dbfef691e0d43b2873eada026415d3b51a5893` | add `docs/judge-demo/Demo.srt` from owner-measured beat timings |
| 2 | `96399e4b95f3ec5e22ba851f3e61b65bf3e19b04` | `0609086d09f8379c61c1cfa92bbaff66f75f9ffb` | fill `CATALYST-DEMO-SCRIPT.md` timestamps + YouTube chapters |

- Message byte-identity (in-process `sha256` of `git log -1 --format=%B`):
  `acee3f7` `8a9f318121241b4a57e0eccdd1ecf605bd177acd2a602874e0f83292c15d1e79`
  == `79dbfef` **same**; `96399e4` `baf9109956c3c9d29d5839ca1149c37e24b6c5326a32d74c00534da97b3a33f2`
  == `0609086` **same**.
- `main`: `b240de2ad0b5ad11b71ad92524efb8da9f555b5d` → `0609086d09f8379c61c1cfa92bbaff66f75f9ffb`
  (this log commits on top).
- `b240de2` remains an ancestor of the new `main` → **pure fast-forward**
  (`Updating b240de2..0609086` / `Fast-forward`).
- `origin/main` observed at `3eed0a6ac76e82447b595f131aacef9a167dbbde` (local ref; behind) —
  **no push performed**.

## Content-identity proof (restacked tree == `96399e4` tree + the 2 EXT-0 files)

- `git diff --name-status 96399e4 0609086` → **exactly 2 files**, both `A`:
  `docs/EXT-1-ROADMAP.md`, `docs/MERGE-LOG-EXT-0.md` (`--name-only | wc -l` → `2`).
- **Reverse** direction `git diff --name-status 0609086 96399e4` → the same 2 files, both `D`
  (i.e. the only difference in either direction is the two EXT-0 files).
- Exclusion diff **both ways** (`. ':!docs/EXT-1-ROADMAP.md' ':!docs/MERGE-LOG-EXT-0.md'`)
  → **empty** in both directions ⇒ **no other byte differs**.
- Blob-level identity (in-process `git rev-parse`):
  `docs/judge-demo/Demo.srt` → `42d44acbf0ccb8e3e1a62cad5007afe0617134cf` at **both**
  `96399e4` and `0609086`; `CATALYST-DEMO-SCRIPT.md` → `90fbd9154f2ea0447c658344802650164149774a`
  at **both**.
- Stack-shape equality: `git diff --stat 3eed0a6..96399e4` == `git diff --stat b240de2..0609086`
  (`CATALYST-DEMO-SCRIPT.md 34 ++---`, `docs/judge-demo/Demo.srt 44 ++`;
  `2 files changed, 70 insertions(+), 8 deletions(-)` both).

## What landed

Docs-only slice, `+70/-8` over `main@b240de2`, no `src/` / `tests/` / script / workflow /
fixture / `.gitattributes` / governed-corpus change:

```
CATALYST-DEMO-SCRIPT.md  (8 beat-table timestamp cells filled with verbatim owner starts;
                          B8 cell notes ends 1:05 + the 1:05-1:44 unassigned tail, owner to
                          confirm; new §7 YouTube chapters: 8 mm:ss title lines + video URL)
docs/judge-demo/Demo.srt (new, 44 lines: 8 beat captions from verbatim human timings plus a
                          closing anomaly caption)
```

- **Timings verbatim** (honesty intact): starts `0:00, 0:29, 0:33, 0:35, 0:38, 0:41, 0:43, 0:59`
  as owner-measured; `§1` prose untouched; STUB/SKIP labels preserved; no new claims or figures.
- **Anomaly disclosed, not concealed**: the `1:05`-`1:44` tail is explicitly marked unassigned /
  owner-to-confirm in both the beat table and the SRT caption 9; B8 is **not** stretched to cover it.

## SRT validator re-run (9 captions, monotonic, ≤2 lines)

Validator: `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\sub-1-validate.py`
(asserts UTF-8, LF-only, 9 captions, monotonic non-overlapping spans, expected spans, ≤2 text
lines each). Interpreter `D:/New folder/research-agent/.venv/Scripts/python.exe`
(**Test-Path: True**, Python 3.14.1).

**Canonical (committed blob) bytes — PASS:**

```
captions: 9
caption 1: OK start=0ms end=29000ms lines=2
caption 2: OK start=29000ms end=33000ms lines=2
caption 3: OK start=33000ms end=35000ms lines=2
caption 4: OK start=35000ms end=38000ms lines=2
caption 5: OK start=38000ms end=41000ms lines=2
caption 6: OK start=41000ms end=43000ms lines=2
caption 7: OK start=43000ms end=59000ms lines=2
caption 8: OK start=59000ms end=65000ms lines=2
caption 9: OK start=65000ms end=104000ms lines=2
SRT VALID: 9 captions, monotonic non-overlapping spans, UTF-8, LF, <=2 lines each
```

### Checkout-artifact disclosure (`CR found`, gate-irrelevant)

A **fresh** `git worktree add`/cherry-pick checkout of the same blob reports:

```
assert b"\r" not in raw, "CR found: file must be LF-only"
AssertionError: CR found: file must be LF-only
```

Root cause, proven — **not** a content defect:

- The committed **blob is LF-only**: `git cat-file blob 42d44acb…` → **0** CR bytes, **1555** bytes.
- `core.autocrlf=true` in this repo (checked, local + inherited), and `.gitattributes` pins
  `eol=lf` only for the **12 governed-corpus** documents — `docs/judge-demo/Demo.srt` is **not**
  among them. A fresh checkout therefore smudges LF→CRLF on disk (**1599** bytes, 44 extra CRs).
- The original gate environment (`sub-1-wt`) had the file **LF on disk** because it was authored
  in place and never checked out — hence the original PASS. Restoring the canonical LF bytes
  (`git cat-file blob … > <path>`) reproduces the PASS in-place.
- `git diff` in that state is **empty** (no content difference); `git status` shows ` M` purely
  from the autocrlf stat cache (`git update-index --refresh` → `needs update`;
  warning: `LF will be replaced by CRLF the next time Git touches it`).
- **Disposition: disclosed, not fixed.** Pinning `docs/judge-demo/Demo.srt eol=lf` in
  `.gitattributes` would be a third changed file and new scope, breaking content-identity; the
  merge gate forbids it. The landed bytes are the LF blob, which is what SRT consumers read and
  which is what the validator checks. Recorded here so the next gate knows why an in-place run
  can trip the CR assertion on a fresh checkout.

## Stamp note (4440 vs 4444)

`docs/SUITE-COUNT.md` is **untouched** by this slice and remains `Collected: 4440` (the
`b240de2` base count — the base `main@3eed0a6` count is also 4440). SUB-1 **adds no tests**, so
the stamp **stays 4440** and was deliberately **not** re-stamped. The `4444` figure belongs to
the **unmerged EXT-2** tree (`slice/ext-2-integrity@4419a96`, +4 tests) and is **not** this
line's count.

## Gates (raw, on restacked tip `0609086`, offline, `PYTHONPATH=<wt>\src`, no extra `-q`)

Interpreter for every gate below: `D:/New folder/research-agent/.venv/Scripts/python.exe`
(**Test-Path: True**, Python 3.14.1) — recorded with each result per the binding pyright rule.

- **Stamp `--check`** (`scripts/stamp_suite_count.py --check`) →
  `OK: docs\SUITE-COUNT.md collected=4440 matches the live collect` (exit 0).
- **Collect** (`scripts/run_tests.py --collect-only`) → `4440 tests collected in 6.05s` (== 4440).
- **B4** (`tests/test_b4_ref_graphs.py`) → `24 passed in 4.45s` = **24/24**.
- **Ruff** (`python -m ruff check src tests`, ruff **0.16.10**) → `All checks passed!` (exit 0).
- **Pyright src** (`python -m pyright src --pythonpath "<venv python>"`, pyright **1.1.414**,
  interpreter **Test-Path: True**) → `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests-config** (`python -m pyright --pythonpath "<venv python>" --project
  pyrightconfig.tests.json`) → `108 errors, 1 warning, 0 informations` (exit 1) —
  **the documented 108-env baseline (delta 0, not zero)**, see below.
- **Full suite** (`scripts/run_tests.py tests --tb=short -rf`) →
  `5 failed, 4432 passed, 3 skipped, 1 warning in 607.88s (0:10:07)` (`EXIT=1`).
  Pass+fail+skip = **4440** = collect. The delta versus the clean env (`4437 passed / 0 failed`)
  is **exactly the 5 environmental reds** below.

### Pyright 108: documented env baseline, not a regression

`docs/MERGE-LOG-NUM-1.md` (later than DS-1, already on `main`) records this identical figure and
diagnosis: *"`108 errors, 1 warning, 0 informations`. Every error is `Import "pytest" could not be
resolved (reportMissingImports)` — the documented sandbox env baseline (pyright here resolves only
its typeshed fallback and never loads the venv `site-packages`). This is **the documented 108-env
baseline (delta 0, not zero)**."*

Independently re-confirmed here (verbose run on `0609086`):

```
Setting pythonPath for service "<default>": "D:\New folder\research-agent\.venv\Scripts\python.exe"
Execution environment: file:///d%3A/New%20folder/research-agent/.venv/Scripts/python.exe
  Search paths:
    <pyright dist>\typeshed-fallback\stdlib
    c:\...\sub-1-remerge-wt
    c:\...\sub-1-remerge-wt\src
    c:\...\sub-1-remerge-wt\typings
    <pyright dist>\typeshed-fallback\stubs\...
```

The venv `site-packages` is **absent** from the search paths, so every `import pytest` in
`tests/` is unresolvable. Isolation of the artifact (all four give the **identical**
`108 errors, 1 warning`):

| # | `--pythonpath` argument | Test-Path | Result |
|---|---|---|---|
| 1 | `D:/New folder/research-agent/.venv/Scripts/python.exe` | **True** | 108 errors |
| 2 | `D:/New folder/research-agent/.venv` (venv root) | **True** | 108 errors |
| 3 | space-free junction `…/opencode/ra-venv/Scripts/python.exe` → same venv | **True** | 108 errors |
| 4 | `…/.venv/Scripts/does-not-exist.exe` | **False** | 108 errors |
| 5 | **control**: identical command in `ds-1-remerge-wt` (the DS-1 tree) | **True** | 108 errors |

⇒ In this environment the interpreter-path channel is inert: an **existing** repo-venv path and a
**nonexistent** path produce the same result. The DS-1-era prose (`0 errors` with an absolute
`--pythonpath`) is **not reproducible today** — the control run (#5) reproduces the DS-1 log's own
command on the DS-1 log's own worktree and now yields 108. The later, on-`main` NUM-1 record
(`108`, delta 0) is therefore the **governing** baseline, and the brief's stated dichotomy
("nonexistent path → 108 artifact; repo venv → 0-error standard") no longer separates in this
environment. The **src** gate still holds the 0-error standard (`0/0/0`). Reported, not
adjudicated; no config was edited to force a number.

## Red set == documented baseline-5 (exact, not a superset)

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

These are **exactly** the 5 pre-existing environmental reds documented in
`docs/archive/MERGE-LOG-CLOUD.md` (3 concurrency races + 1 Windows symlink-privilege refusal +
1 q05 race), reproduced verbatim in `docs/MERGE-LOG-FRONT-1.md` and again in
`docs/MERGE-LOG-NUM-1.md` — whose landed figure `5 failed, 4432 passed, 3 skipped` matches this
run **digit for digit**. **Red set == documented set (exact); no new red; delta 0.** The landing
range is docs-only (`CATALYST-DEMO-SCRIPT.md`, `docs/judge-demo/Demo.srt`) and touches no test,
so no red could be induced. `main` was verified unmoved before the FF, so this is a like-for-like
comparison.

### Documented flake — did not fire; isolation proof recorded

`tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree`
is the documented 30 s pinned-subprocess-timeout flake (`docs/MERGE-LOG-NUM-1.md`). It is **not**
in the red set above, so no isolation proof was required; one was run anyway on the restacked tip
in `sub-1-remerge-wt` (repo venv):

```
tests/test_eval_plane.py in isolation, restacked tip, sub-1-remerge-wt : 205 passed in 86.25s (EXIT=0)
```

## STOP-condition checks

| Condition | Result |
|---|---|
| NOT-list hit (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`) | **PASS** — `CLEAR` (0 hits) over the range's commit subjects/bodies, the full range diff, and the new SRT body |
| main moved before the FF | **PASS** — unmoved at `b240de2ad0b5ad11b71ad92524efb8da9f555b5d` (re-verified immediately pre-FF) |
| cherry-pick conflict / creative resolution | **PASS** — 2/2 applied clean, messages kept, no squashing |
| content-identity fails | **PASS** — restacked == `96399e4` + the 2 EXT-0 files (both-directions diff = those 2 files; exclusion diff empty both ways; blobs identical) |
| red set superset of baseline | **PASS** — exact equality with baseline-5 (delta 0) |
| `--check` drift | **PASS** — `--check` OK, collected 4440 = 4432+5+3 |
| stale main-bound worktree left behind | **PASS** — `main` bound only to `met-1-merge-wt` at the final tip, clean (see Hygiene) |
| FAIL audit on the landing range | **PASS** — none (HARD RULE checked below) |
| push without a human hash-pin | **none performed** |

### HARD RULE — no FAIL audit on the landing range

The landing range `b240de2..0609086` is docs-only (2 files, both additions to a docs path).
An exhaustive sweep of every ref (`git log --all --name-only`, 164 audit-named artifacts) plus
`git grep` over `main`'s `audits/` and `docs/` finds **no `AUDIT-SUB-1*` artifact** and no audit
file mentioning `SUB-1` at all. No FAIL audit exists on this range ⇒ **HARD RULE not triggered**;
nothing to surface and halt on.

## Worktree hygiene

- `met-1-merge-wt` (Tay's arrangement preserved): was bound to `main@b240de2` clean → FF'd **in
  place** to the restacked tip → this log commits on top; ends bound to `main` at the final tip,
  **clean**. No stale main-bound worktree.
- `sub-1-remerge-wt`: holds `slice/sub-1-restacked@0609086` (not main-bound; own restack work —
  left in place).
- `sub-1-wt` (`slice/sub-1-captions@96399e4`), `ext-0-merge-wt`, `ext-0-wt`, all other sessions'
  worktrees: **untouched**.
- `git worktree prune` / the FF-time step-4 error
  (`failed to delete 'D:/New folder/research-agent/.git/worktrees/step-4': Permission denied`) —
  **known, ignored per brief** (same as MET-1 / DS-1 / EXT-0).

## Push charters (DRAFTED, NOT EXECUTED — D8/D9)

Every push requires explicit human approval and a hash pin. **No `git push` was run; no remote
ref was touched.**

**Charter A — `khwarizmi-research` (origin) — plain push**
- Remote: `origin https://github.com/ace2013hieco-aa/khwarizmi-research.git` (only remote configured).
- Observed: `origin/main` = `3eed0a6ac76e82447b595f131aacef9a167dbbde` (behind; local ref, offline).
- Proposed (hash-pinned): `git push origin <reviewed-main-hash>:refs/heads/main`
  (**no `--force`**, no `--tags`), where `<reviewed-main-hash>` is the human-approved final tip
  **plus** this log commit once reviewed (currently `main` = `0609086d09f8379c61c1cfa92bbaff66f75f9ffb`
  pre-log). Advances `origin/main` `3eed0a6 → 0609086 → log`, fast-forward only.
- Preconditions: human approves; `origin/main` still at/behind `3eed0a6…`; local tree clean;
  pushed hash == reviewed hash.

**Charter B — `khwarizmi` public mirror — orphan-sync**
- Remote: **not configured in this checkout**. Parent pinned by rule at mirror HEAD
  `1192b5152edc81174cb905fa2bbc1cf532829f91` (`sync: Catalyst application from dev main@256d155`,
  present locally as a commit; convention carried from `MERGE-LOG-CAT-2.md` / `-DEM-1` / `-DS-1`).
- Convention: orphan-sync — the sync commit's **parent is the mirror HEAD** (`1192b51…`), so the
  push is a fast-forward; **no `--force`** (rule #5).
- Proposed (hash-pinned): `git commit-tree <reviewed-main-tree> -p 1192b5152edc81174cb905fa2bbc1cf532829f91 -m "sync: SUB-1 restack from dev main@<hash>"`,
  then verify `sync^{tree} == <reviewed-main>^{tree}` and
  `git merge-base --is-ancestor 1192b51… <sync>`, then `git push <mirror> <sync>:refs/heads/main`.
- Preconditions: same reviewed hash as Charter A; mirror public; human approves.

## Credential-path statement

- No live vendor calls and no real credentials were used. All gates ran offline; `--check`
  performs only a local `pytest --collect-only`.

## NOT-LIST scan

`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy` — **0 substantive hits** across the range's
commit subjects/bodies, the full range diff, and the new `docs/judge-demo/Demo.srt` body
(all three scans `grep -i` → no match, exit 1).

License: Apache-2.0 (LICENSE).
