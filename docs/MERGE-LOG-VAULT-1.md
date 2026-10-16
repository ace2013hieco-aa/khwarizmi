# MERGE-LOG-VAULT-1 — merge/vault-1 (R3 vault note-body residual closed)

- Repo: `D:\New folder\research-agent` (GitHub `ace2013hieco-aa/khwarizmi-research`)
- Branch: `main` (fast-forwarded **locally**; gate worktree
  `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\vault-1-merge-wt`, detached at the landed tip)
  — **LOCAL-ONLY, NO PUSH**
- Task: VAULT-1-MERGE — land `slice/vault-1-body@d6001a2` (merge gate only)
- Verdict: **PASS** — `main` verified unmoved, clean fast-forward with **no cherry-pick conflict**,
  content-identity proven incl. the sanctioned stamp re-derivation, hostile spot green, all gates green.
  **Nothing pushed.**

## Lineage (verified, not assumed)

```
slice/vault-1-body@d6001a2   (audit/vault-1-redteam@e3c7c4c = PASS)
 ├ da19aba  fix(vault): escape note-body control bytes through the output boundary
 ├ 348c200  test(vault): pin escaped note bodies and the manifest digest agreement
 └ d6001a2  chore(vault-1): re-stamp the collected suite count (4610)
```

```
main  5e582b2101e43d154f968e2483488908fa76ccfb   (verified unmoved before the FF)
 └ slice/vault-1-restacked@cba379f  (re-stacked locally; cherry-pick, messages kept)
```

- `git rev-parse main` (before) == `5e582b2101e43d154f968e2483488908fa76ccfb` → **unmoved** (no STOP).
  `git ls-remote origin refs/heads/main` observed at the same instant == `5e582b2…` (no external move).
- Base composition re-proved: `git diff --stat 6f34a33 5e582b2` = exactly
  `docs/EXT-1-ROADMAP.md` (`2 +-`) and `docs/MERGE-LOG-ROADMAP-I6.md` (`113 +`) → `2 files changed,
  114 insertions(+), 1 deletion(-)`; no `src/`/`tests/`/script/workflow delta.
- `git merge-base --is-ancestor 5e582b2 cba379f` → true (**FF-able**); rebase prohibited (D1), not used.
- Main-bound holder `met-1-merge-wt` confirmed **fully clean** (0 porcelain entries) immediately before the
  ref move; the FF was applied **in place** in the holder (`git merge --ff-only cba379f`, exit 0) so no stale
  main-bound worktree holding pre-merge content is left (NUM-1-PUSH-A / CAT-1 lesson).
- `main`: `5e582b2101e43d154f968e2483488908fa76ccfb` → `cba379f19b3c1568251033628339b561e9cb6eaa`.
- `5e582b2` remains an ancestor of the new `main` → **pure fast-forward**; merge-base == `5e582b2…`.
- This log commit advances `main` `cba379f` → the final tip (docs-only; behaviour-neutral).

## Re-stack: old → new hash map (cherry-pick, in order, no conflict)

| slice commit | message | restacked hash |
|---|---|---|
| `da19aba` | fix(vault): escape note-body control bytes through the output boundary | `6c977b8` |
| `348c200` | test(vault): pin escaped note bodies and the manifest digest agreement | `c06fde0` |
| `d6001a2` | chore(vault-1): re-stamp the collected suite count (4610) | `f85e68c` (verbatim) → **`cba379f`** (re-stamped) |

- All three cherry-picks applied **cleanly**; no non-stamp conflict arose, so no STOP was triggered.
- Messages preserved for the two code/test commits. `git patch-id --stable` for the three slices is
  **byte-identical** to the originals (`fd14d432…`, `6b9681c2…`, `797c7889…` on both sides) — the picked
  payload is the same patch, not a re-write.

### The stamp re-derivation (pre-authorized, generator-only, count unchanged)

The verbatim pick `f85e68c` (cherry-pick of `d6001a2`'s stamp) applied without a textual conflict, but its
generated `## Provenance` block named `348c200` — the slice-side tests commit, which is **not reachable from
`main`** (`git merge-base --is-ancestor 348c200 main` → false). Every stamp currently landed on `main` names a
reachable commit (`e0afafd`, `b687b8b`, `21daeb5` are all ancestors of `main`), and the EXT-4 restack precedent
was re-stamped for exactly this reason (`chore(num-1): re-stamp the collected suite count for the restacked EXT-4
tip` → provenance `21daeb5`). The director's note covers this: *take the restacked value via the sanctioned
generator (re-run stamp on the restacked tip — must read 4610 — then continue)*.

- Action: re-ran **`scripts/stamp_suite_count.py` alone** on the restacked tests commit
  (`c06fde0`), then committed its output. **No hand-written byte**: the artifact is generator-authored, and the
  generator derives the count from a live `pytest --collect-only` on this tree.
- Result: `Collected: 4610` (**unchanged**), provenance `Commit: c06fde0` (reachable), fresh UTC stamp.
- `git diff f85e68c cba379f -- docs/SUITE-COUNT.md` = the two provenance lines and nothing else
  (`Collected:` line identical on both sides).
- Commit message adjusted to stay true (`…for the restacked tip (4610)`, body naming `c06fde0`); the alternative
  read — landing `f85e68c` verbatim — would have landed a provenance hash absent from `main`'s history. Both
  readings, the count (4610) and the mechanism (generator-only) are recorded here for the audit trail.

## Content-identity proof (restacked tree vs slice tip)

Universe: 740 tracked entries at `d6001a2`, 741 at `cba379f` (one new file from `main`).

```
$ git diff --name-only d6001a2 cba379f          # and the reverse, identical set
docs/EXT-1-ROADMAP.md          # main's ROADMAP-I6 status flip (blob c77c864 == 5e582b2's)
docs/MERGE-LOG-ROADMAP-I6.md   # new on main (blob bde1a8b == 5e582b2's)
docs/SUITE-COUNT.md            # sanctioned re-stamp: 2 provenance lines only, 4610 both sides

$ git ls-tree -r d6001a2 | sort  vs  git ls-tree -r cba379f | sort
740 vs 741 entries; 5 diff lines = the 3 paths above (1 added, 1 roadmap flip, 1 provenance)
⇒ every other tracked path is byte-identical (same blob hash)

$ git diff --name-only d6001a2 cba379f -- src tests
(empty)              ⇒ the entire slice payload is byte-identical
```

Trees: `d6001a2^{tree}` = `63b7b9635871f4a4b50f6766b25852296c18f23c`;
`5e582b2^{tree}` = `1d378e308a091cac2db6832130231f58f3e41595`;
`cba379f^{tree}` = `efe6c5bcf4a538f78494f363ab8fbdc312a7b5ab`.

## What landed

```
docs/SUITE-COUNT.md            |   6 +-
src/hermes/vault/projection.py |  59 +++++++-
tests/test_vault_body_scrub.py | 329 ++++++++++++++++++++++++++++++++++++++++++++
3 files changed, 385 insertions(+), 9 deletions(-)
```

- `src/hermes/vault/projection.py` — the two note-body renderers (`_single_line`, `_task_alias`) now transcribe
  journal bytes through `hermes.output.scrub`; the renderer census comment and docstrings record that the
  boundary's fail-closed `_guard` is deliberately **off** the note path (a note always renders — escaped
  visibly, never refused). No repository write, no journal rewrite, no validator touched.
- `tests/test_vault_body_scrub.py` (new, 329 lines, **10** tests) — hostile body → escaped `.md`, manifest
  digest over the escaped bytes (pre-slice raw digest refused with `NOTE_DIGEST_DIVERGES`), benign bodies
  byte-identical with the boundary on/off, journal immutability, no-refusal, and the AST renderer census.
- `docs/SUITE-COUNT.md` — re-stamped 4600 → **4610** (4600 + the 10 new pins) as described above.

## Digest-honesty record

- Derived-view bytes **moved by design on hostile content only**. The measured move set over the full-suite
  render-reachable scope is **2921 note-body boundary calls / 0 non-identity** (audit re-derivation, §2) —
  i.e. `scrub` is the identity map on all pre-existing content, so **no digest moved and no golden needed
  regeneration**. No committed `.projection-manifest.json` and no committed `evt-*.md` exist in the tree; the
  vault batteries compute digests at runtime, so there is nothing hand-editable to drift.
- **Journal bytes never move.** The boundary is a rendering transform: the hostile spot below reads the row
  back byte-for-byte, and `test_the_boundary_never_rewrites_the_journal` pins the whole `events` row set
  before/after a projection.
- This log makes **no** claim about the validity of any displayed content (prohibited-claims discipline); a
  display transform is not evidence.

## Audit record

- `audit/vault-1-redteam@e3c7c4c` — `AUDIT-VAULT-1-REDTEAM.md` (405 lines), **VERDICT: PASS**, "No MUST-FIX, no
  SHOULD-FIX introduced by this slice." Its counts line reproduces the director's figures: hostile full-column
  sweep 22/22; digest re-derivation 2921/0; PRE-slice digest refused; no-refusal 8/8; journal immutability 5/5;
  non-vacuity 6/10 pins fail with `scrub` neutralized; B4 24/24; `check_census` PASS; 0 cert-record edits.
- No FAIL audit exists on the landing range `5e582b2..cba379f` (`git branch -a --list "*vault*"` and the audit
  log return only this PASS audit) → **no STOP**.
- Director re-derivation: content-identity, hostile spot and every gate below were re-run here on the landed tip.

## Gates (raw, on landed tip `cba379f`, offline, `PYTHONPATH=<wt>/src`, no extra `-q`)

- **Interpreter (Test-Path-proven)**: `D:\New folder\research-agent\.venv\Scripts\python.exe` exists,
  `Python 3.14.1`. Machine effectively idle at gate time (1 `python.exe` = the agent host; 3 `node.exe` = IDE;
  no pytest/ruff/pyright peers).
- **Stamp `--check`** → `OK: docs\SUITE-COUNT.md collected=4610 matches the live collect` (exit 0).
- **Collect** (`scripts/run_tests.py --collect-only`) → `4610 tests collected in 1.46s` (exit 0).
- **New battery** (`tests/test_vault_body_scrub.py -v`) → `10 passed in 0.36s` (exit 0) = **10/10**.
- **B4 surface** (`tests/test_b4_ref_graphs.py -v`) → `24 passed in 3.86s` (exit 0) = **24/24**.
- **Ruff** (`uvx ruff check src tests`) → `All checks passed!` (exit 0).
- **Pyright src** (`uvx pyright --pythonpath <repo-venv> src`) → `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests** (`… --project pyrightconfig.tests.json`) → `0 errors, 1 warning, 0 informations` (exit 0;
  the warning is the pre-existing `reportSelfClsParameterName` in `tests/test_research_program.py:144`).
- **`check_census`** → `PASS - every certified figure is reproduced exactly.` (exit 0); owners 18/5/4/27,
  rollback-only 1, persistence→research imports 15, control calls outside certified layers 0.
- **FULL suite** (`scripts/run_tests.py -v`) →
  `4607 passed, 3 skipped in 528.37s (0:08:48)` with `FULLSUITE_EXIT=0`; the verbose log carries **zero**
  `FAILED`/`ERROR` lines.

### Hostile spot (in-process, on `cba379f`; planted ESC/BEL/OSC/C1/DEL/Bidi body)

```
cursor: 3 notes written: 3
raw forbidden code points in any line: []
payload line: ['- payload: {"note":"\\[\\[forged|tap\\]\\]","v":"\\u001b[2J"}']
visible escape '\\x1b[31mRED' in body: True
visible escape '\\x07' in body: True
visible escape '\\x1b]0;pwn' in body: True
reason line: '- reason: \\x1b[31mRED\\x07\\n  Project: forged\\x1b]0;pwn\\x07'
forged line as own line: False
journal row keeps its own bytes: True len 35
manifest digest == file bytes: True
verify ok: True counts: {}
spot_exit=0
```

An ANSI/OSC-bearing reason reaches the `.md` as **visible escapes**, a data newline cannot forge a body line,
the journal row keeps its own bytes, and the manifest verifies the escaped bytes with **no** `NOTE_DIGEST_DIVERGES`.

## Red-set proof (vs the documented baseline-5)

The audit run recorded `5 failed, 4602 passed, 3 skipped` — five **pre-existing, environment-dependent**
failures (`test_concurrency` ×2, `test_p_auto_5_vault::test_join_refuses_symlink_and_directory`,
`test_phase1_acceptance` forced-race, `test_q05_ratification_consumers::test_f6…`), reproduced identically on
the pre-slice base `5e582b2` (`sqlite3.OperationalError: attempt to write a readonly database`; a Win32 symlink
privilege simulation).

- This landing run: `4607 passed, 3 skipped`, exit 0 → **red set empty**, i.e. a **strict subset of baseline-5**
  (0 ⊂ 5). No `eval_plane` flake occurred at all, so no isolation proof for one was required.
- Isolation check for the five named tests on `cba379f`: `5 passed in 0.91s` (exit 0) — consistent with the
  recorded environment/load dependence rather than a code regression.

## Roadmap disposition (no flip — recorded)

`docs/EXT-1-ROADMAP.md` row 4 is **R3 CLI control-byte scrub → EXT-5 → LANDED (c22441e)**, and that row scopes
the **CLI emitter** surface only. No EXT-1 row covers the **vault note body** (`grep -i vault
docs/EXT-1-ROADMAP.md` → 0 hits), so this slice **flips no roadmap cell**; the residual is recorded here and in
the audit rather than by editing the roadmap. Nothing in `docs/EXT-1-ROADMAP.md` changes in this merge.

## STOP-condition checks

| Condition | Result |
|---|---|
| NOT-list functional coupling | **PASS** — 0 hits, strict and loose, over commit text and diff bytes (see below) |
| main moved before the FF | **PASS** — unmoved at `5e582b2…`; `origin/main` observed at the same hash |
| non-stamp cherry-pick conflict | **PASS** — none: all three picks applied cleanly |
| content-identity fails | **PASS** — 3 differing paths, all accounted for (2 from `main` + 1 sanctioned re-stamp); `src`/`tests` 0 |
| red-set superset | **PASS** — red set empty ⊆ baseline-5 |
| `--check` drift | **PASS** — `OK … collected=4610` |
| stale main-bound worktree left | **PASS** — FF applied in place in the holder; holder clean at the landed tip |
| FAIL audit on the range | **PASS** — none exists (only the PASS `e3c7c4c`) |
| push without a human hash-pin | **none performed** |

## Push charters (DRAFTED, NOT EXECUTED)

D8/D9: every push requires explicit human approval and a hash pin. **No `git push` was run.**

**Charter A — `khwarizmi-research` (origin) — plain push**
- Remote: `origin https://github.com/ace2013hieco-aa/khwarizmi-research.git`
- Observed at merge time: `origin/main` = `5e582b2101e43d154f968e2483488908fa76ccfb` (**behind** local `main`).
- Proposed (hash-pinned): `git push origin <reviewed-main-hash>:refs/heads/main` (no `--force`, no `--tags`),
  where `<reviewed-main-hash>` is the human-approved landed tip **plus** this log commit once reviewed.
- Preconditions: human approves; `origin/main` still at/behind `5e582b2…`; local tree clean; pushed hash ==
  reviewed hash.

**Charter B — `khwarizmi` public mirror — orphan-sync**
- Remote: `https://github.com/ace2013hieco-aa/khwarizmi.git` (not configured in this checkout).
- Observed at merge time (read-only `git ls-remote`, exit 0): `refs/heads/main` =
  `7f09601f4c4b5e53e6f065904fcd287127ae12d1` — the mirror has advanced past the `e5cdff5…` recorded at the
  ROADMAP-I6 merge, so the sync parent must be re-read at push time.
- Convention: orphan-sync — the sync commit's **parent is the mirror HEAD**, so the push is a fast-forward;
  **no `--force`** (rule #5).
- Proposed (hash-pinned): `git commit-tree <reviewed-main-tree> -p <mirror-head> -m "sync: VAULT-1 vault
  note-body boundary from dev main@<hash>"`; verify `sync^{tree} == <reviewed-main>^{tree}` and
  `merge-base --is-ancestor <mirror-head> <sync>`; then `git push <mirror> <sync>:refs/heads/main`.
- Preconditions: same reviewed hash as Charter A; mirror public; human approves.

## Credential-path statement

- No live vendor calls and no real credentials were used. All gates ran offline; `--check` performs only a local
  `pytest --collect-only`. The mirror figure above is a read-only `ls-remote`, not a push.

## NOT-LIST scan

The four canonical barred identifiers (described here **by count, not quoted**, per the 2026-10-14 lesson) over
`5e582b2..cba379f` — commit subject/body **and** the full diff bytes, case-sensitive word-boundary and again
case-insensitively (loose): **0 hits on all four** in both passes, both streams. No code, test, or configuration
in the landing range references any of the four domains. Not a STOP condition.

## STOP BEFORE PUSH

`main` is fast-forwarded **locally only**. Nothing is pushed. Both charters above require a human hash-pin
before execution.

License: Apache-2.0.
