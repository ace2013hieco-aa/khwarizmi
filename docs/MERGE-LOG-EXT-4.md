# MERGE-LOG-EXT-4 — EXT-4 cold archive (L1/I4) restacked onto `main` and landed

Merge-gate record for the EXT-4 slice: an additive cold archive for
resolved/superseded rows (`slice/ext-4-archival@ba06f97`) plus its audit
wording fix (`fix/ext-4-s1s2@fceb94a`), re-stacked onto the current `main`
after a base-drift STOP and landed locally. Follows the
`MERGE-LOG-EXT-3` / `MERGE-LOG-LOOP-1` pattern.

**Outcome: EXT-4 landed on `main` — local fast-forward, no push.**
Redteam audit `audit/ext-4-redteam@9c6cbba` is **PASS-WITH-SHOULD-FIX**
(0 MUST-FIX, 2 SHOULD-FIX, 3 observations); both SHOULD-FIXes are closed by
`fceb94a` on the landed tip. **`origin` and the public mirror are NOT
advanced and NOT pushed — D8/D9 require a human hash-pin.**

## Provenance

| Item | Value |
| --- | --- |
| Task | EXT-4-REMERGE (merge gate, second restack — local-only) |
| Base (`main` before) | `9269dd9771c9c029ef0e7afc9b66f8989f3cd5db` |
| Landed tip (FF'd to) | `df4a5790ef7ab7ef3e97dd4f3c0bec90e4cab389` |
| Branch | `slice/ext-4-restacked` |
| Gate worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/ext-4-remerge-wt` |
| Main-bound holder | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` (FF'd **in place**) |
| Merge method | **fast-forward in place**, `git merge --ff-only` in the main-bound worktree |
| FF evidence | `merge-base(main, slice/ext-4-restacked)` == `main`; exit 0 |
| Rebase / merge commit / force | **none** — FF only, one parent per commit; the cited slice tips keep their hashes |
| Audit | `audit/ext-4-redteam@9c6cbba` — PASS-WITH-SHOULD-FIX; **no FAIL on the range** |

## Restack history (why this is the second charter)

1. **EXT-4-MERGE (charter 1)** verified the base was unmoved at `b687b8b`,
   then caught `main` advancing to `7202d08` at `2026-10-15 09:26:17 +0300`
   (the LOOP-1 landing) *during* its full-suite run. FF-ability of
   `fceb94a` failed (`7202d08` is not an ancestor of it) → **STOP**, no ref
   moved, no commit, no push. Every gate on that attempt was green on the
   pre-drift base and is recorded in the task reply.
2. **EXT-4-REMERGE (this charter)** re-based the slice from
   `9269dd9` (= `b687b8b` + LOOP-1 `d2e7ac4`/`b24a90b`/`34a3685`/`7202d08` +
   `MERGE-LOG-LOOP-1`) by **cherry-pick** — the sanctioned alternative to a
   barred ref move or merge commit (D1 forbids rebasing cited tips).

Base composition check (`git diff --name-status b687b8b 9269dd9`): exactly
`docs/MERGE-LOG-LOOP-1.md`, `docs/SUITE-COUNT.md` (the LOOP-1 re-stamp),
`src/hermes/agents/runtime/{__init__,assembly,run}.py`,
`tests/test_loop0_e1_probe.py`, `tests/test_loop1_context_assembly.py` — the
LOOP-1 landing only, no foreign content.

## Old → new hash map

| Original | Restacked | Commit |
| --- | --- | --- |
| `e33dc41a511ef7dbc22ba17a482413d6d4cc563f` | `cd642807b2c27ddf49d8029738e0fd3efa5aad2c` | `feat(persistence): additive cold archive for resolved/superseded rows (EXT-4 L1/I4)` |
| `ba06f9795e098e1ee985811ec5a6589834da289c` | `b9a4adfb3bdf9b62b04dd19ac4eabdf828c2c87a` | `docs(ext-4): record the archival design and the measured growth census` |
| `fceb94a6afd2e6da7a4af80ca74479a4de27030e` | `21daeb5652cc5bfde7d7f5976098876771625801` | `fix(ext-4): close audit S1 + S2 on the archival wording (slice ba06f97)` |
| — (new) | `df4a5790ef7ab7ef3e97dd4f3c0bec90e4cab389` | `chore(num-1): re-stamp the collected suite count for the restacked EXT-4 tip` |

Commit messages and author dates were preserved verbatim by the picks; only
the parents changed. The original tips `ba06f97` / `fceb94a` and the audit
`9c6cbba` are untouched and still resolvable.

## The one cherry-pick conflict, and its Director-authorized resolution

Cherry-picking `e33dc41` onto `9269dd9` produced **exactly one conflicted
path**: `docs/SUITE-COUNT.md` — the machine-generated stamp
(`GENERATED — do not hand-edit`), colliding because the old base carried
`Collected: 4452` while the new base carries `Collected: 4463`:

```
<<<<<<< HEAD
Collected: 4463        /  - Commit: 34a3685  - Stamped 2026-10-14T13:11:40Z
=======
Collected: 4468        /  - Commit: b687b8b  - Stamped 2026-10-14T12:21:10Z
>>>>>>> e33dc41
```

It is **not a substantive conflict**: `src/hermes/persistence/archive.py` and
`tests/test_archive.py` applied **byte-identically** (worktree blobs
`0d384889223953c81a93e3ec2cd7cfa8ffebec60` and
`8fcf76231dd2b7a99709f56e13ca1df024a1eef3` == their `e33dc41` blobs), and the
two later picks can only touch `docs/EXT-4-ARCHIVAL.md` and the `archive.py`
docstring. The charter's own step (3) already fixes this file's final value
at `4479` through the sanctioned generator, so the collision was surfaced to
the Director before acting and the **Director ruled: resolve via the
chartered re-stamp and land.**

Resolution applied: took the incoming side (blob == `e33dc41`'s
`930b9b175d0549072fe145c3a7d217320c139758`), then the step-(3) re-stamp
superseded it. Remaining conflicts: **0**. No conflict was adjudicated by the
gate itself; the ruling is recorded above and in the task reply.

## Content-identity proof (both directions)

`9269dd9 → 21daeb5` — exactly the 4 EXT-4 paths and nothing else:

```
A  docs/EXT-4-ARCHIVAL.md          | 134 ++++++++++++
M  docs/SUITE-COUNT.md             |   6 +-
A  src/hermes/persistence/archive.py | 426 ++++++++++++++++++++++++++++++++++++++
A  tests/test_archive.py           | 341 ++++++++++++++++++++++++++++++
4 files changed, 904 insertions(+), 3 deletions(-)
```

(identical +904/−3 to the original range `b687b8b..fceb94a`)

`fceb94a → 21daeb5` — exactly the 5 LOOP-1 files + 1 LOOP-1 log, no more:

```
A  docs/MERGE-LOG-LOOP-1.md              | 190 ++++++++++++++++++++
M  src/hermes/agents/runtime/__init__.py |   2 +
A  src/hermes/agents/runtime/assembly.py | 135 ++++++++++++++
M  src/hermes/agents/runtime/run.py      |  41 ++++-
A  tests/test_loop0_e1_probe.py          | 320 ++++++++++++++++++++++++++++++++++
A  tests/test_loop1_context_assembly.py  | 264 ++++++++++++++++++++++++++++
6 files changed, 944 insertions(+), 8 deletions(-)
```

Reverse direction (`21daeb5 → fceb94a`) is the mirror image (LOOP-1
deletions/modifications only). Substantive EXT-4 blobs are **identical**
between the old tip and the restacked tree:

```
IDENTICAL  src/hermes/persistence/archive.py  f62ac1cae5285bc4659b3d51f74a08dadcb4a758
IDENTICAL  tests/test_archive.py              8fcf76231dd2b7a99709f56e13ca1df024a1eef3
IDENTICAL  docs/EXT-4-ARCHIVAL.md             c9e8d7842cd85956882ee311230941379907e732
```

`docs/gr3-b4` is untouched by the restack (`git diff 9269dd9 df4a579 --
docs/gr3-b4` empty) — B4 fixtures remain byte-identical.

## Re-stamp (NUM-1)

New base collects **4463**; the slice adds **16** archive tests:

```
4463 + 16 = 4479
Stamped docs\SUITE-COUNT.md: collected=4479
```

The stamp is committed as its own commit (`df4a579`, 3/3 lines) because
step (3) requires `stamp --check` to pass on the restacked tip *before* the
FF in step (4); folding it into a picked commit would have broken the
content-identity proof above.

## Tamper / manifest spot probes (independent script, not the slice's tests)

Raw, on the landed tip:

```
P1 clean export   : appended=1 total=1 chunks=1 | verify rows=1 files_checked=1
P6 hot-DB digests : before={events:3f1816254b00fd8f, artifacts:2c2fcc13d65786e0,
                     contradictions:6b96540c45b9d78a, curated_knowledge_entries:4f53cda18c2baa0c,
                     curated_knowledge_supersession:4f53cda18c2baa0c}
                    after ={... identical ...}
P6 hot-DB digests : IDENTICAL — export is COPY-only
P2 journal hole   : gap scan clean=() after DELETE event_id=2=(2,)
P3 flipped byte   : REFUSED  ArchiveIntegrityError: archive chunk digest mismatch: chunks/chunk-000001.ndjson
P4 manifest tamper: REFUSED  ArchiveIntegrityError: archive row total mismatch: manifest 2, files 1

PROBE RESULT: PASS — hole detected, byte-flip refused, manifest tamper refused, export COPY-only
```

## Gates (raw, on the landed tip `df4a579`, `PYTHONPATH=<wt>/src`, no extra `-q`)

Interpreter for every gate below:
`D:/New folder/research-agent/.venv/Scripts/python.exe`
(**Test-Path: True**, Python 3.14.1, pyright 1.1.414, ruff 0.16.10).

```
######## COLLECT ########
4479 tests collected in 1.42s

######## STAMP --check ########
OK: docs\SUITE-COUNT.md collected=4479 matches the live collect

######## ARCHIVE 16 ########
collected 16 items
tests\test_archive.py ................                                   [100%]
============================= 16 passed in 0.82s ==============================

######## B4 24 ########
tests\test_b4_ref_graphs.py ........................                     [100%]
============================= 24 passed in 3.87s ==============================

######## CENSUS ########
control calls by statement: BEGIN 28, COMMIT 27, ROLLBACK 66
owners by layer: persistence 18, gateway 5, Controller 4

PASS - every certified figure is reproduced exactly.

######## RUFF ########
All checks passed!

######## PYRIGHT SRC ########
0 errors, 0 warnings, 0 informations

######## PYRIGHT TESTS (--pythonpath <Test-Path-proven venv python>, project pyrightconfig.tests.json) ########
tests\test_research_program.py:144:23 - warning: Instance methods should take a "self" parameter (reportSelfClsParameterName)
0 errors, 1 warning, 0 informations

######## FULL SUITE (scripts/run_tests.py tests --tb=short -rf) ########
4476 passed, 3 skipped in 469.48s (0:07:49)
FULLSUITE_EXIT=0
```

`4476 + 3 = 4479` == collect. The single warning is the pre-existing
`tests/test_research_program.py:144` (on `main` since before this slice).

## Red set: EMPTY (subset of baseline-5, delta 0)

No test failed. The documented environmental baseline-5 (3 concurrency
races, 1 Windows symlink-privilege refusal, 1 q05 race — `docs/archive/MERGE-LOG-CLOUD.md`,
reproduced through `MERGE-LOG-NUM-1` / `-FRONT-1` / `-EXT-2` / `-EXT-3`) did
not fire on this run either. **Empty ⊆ baseline-5; no new red.** The
documented `tests/test_eval_plane.py` timing flake did not fire, so no
isolation proof was required.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list functional coupling (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`) | **PASS** — 0 functional hits in the restack commits, their bodies, or the range diff. One case-*insensitive* substring false positive (`tse` inside "the manifest it**se**lf", `archive.py`/`EXT-4-ARCHIVAL.md` prose) is not a mention; reported for the record. |
| `main` moved before the FF | **PASS** — re-verified unmoved at `9269dd9` immediately pre-FF (holder `met-1-merge-wt` clean at the same hash) |
| cherry-pick conflict | **RESOLVED BY DIRECTOR RULING** — one conflicted path, the generated stamp only; no substantive conflict; remaining conflicts 0 (see above) |
| content-identity fails | **PASS** — both directions exact; substantive blobs identical |
| red set superset of baseline-5 | **PASS** — red set empty, delta 0 |
| `--check` drift | **PASS** — `collected=4479` == live collect 4479 |
| roadmap diff beyond the status cell | **PASS** — numstat `1 1`; word-diff shows only `QUEUED` → `LANDED (df4a579)` |
| stale main-bound worktree left behind | **PASS** — `met-1-merge-wt` clean and bound to `main` at the tip after the two docs commits |
| FAIL audit on the range | **PASS (did not fire)** — audit is PASS-WITH-SHOULD-FIX, both items closed |
| push without a human hash-pin | **none performed** |

Ignored by charter: a `git` housekeeping step emitted
`error: failed to delete 'D:/New folder/research-agent/.git/worktrees/step-4': Permission denied`
while pruning a stale worktree admin entry. It concerns an unrelated, already
dead entry and has no effect on the landing; recorded, not acted on.

## Worktree hygiene

`met-1-merge-wt` (house arrangement preserved): bound to `main@9269dd9` and
clean → FF'd **in place** to `df4a579` → the two docs commits land on top →
ends bound to `main` at the final tip, clean. `ext-4-remerge-wt` holds
`slice/ext-4-restacked` at `df4a579`; the slice author's `ext-4-wt`
(`ba06f97`), the fix worktree (`fceb94a`), the audit worktree (`9c6cbba`) and
the superseded `ext-4-merge-wt` (detached at `fceb94a`, the charter-1 holder)
are untouched. The shared checkout, `.hermes/`, JSON files and all other
worktrees were never touched.

## Dual push plans — drafted, NOT executed (D8/D9)

No push was performed by this gate. Both plans require a human hash-pin.

1. **`origin` plain-push** (`https://github.com/ace2013hieco-aa/khwarizmi-research.git`):
   push `<reviewed-main-hash>:refs/heads/main`, single refspec, no force, no
   tags, after re-verifying live `origin/main` is a strict ancestor of the
   reviewed tip (FF). Live `origin/main` at draft time:
   `b687b8bce5a0aaeb17cba1d9e17067de7414a7aa` — a strict ancestor of the
   local `main`, so the plain push would fast-forward.
2. **public mirror orphan-sync** (`https://github.com/ace2013hieco-aa/khwarizmi`):
   add a temp remote, `fetch --no-tags`, re-read the live mirror pin, build a
   sync commit whose tree is `<tip>^{tree}` and whose parent is the mirror
   HEAD (orphan convention — `merge-base` must be empty), push the exact hash
   with **no force** (rule #5), then remove the temp remote. Live mirror HEAD
   at draft time: `6b82419f0582b2d26ddffeea21d67863f2863d8c` — a moving
   target, always re-read with `ls-remote` immediately before the sync.

## Verdict

### A — EXT-4 MERGED (LOCAL-ONLY)

`main` FF'd `9269dd9771c9c029ef0e7afc9b66f8989f3cd5db` →
`df4a5790ef7ab7ef3e97dd4f3c0bec90e4cab389`. The cold archive lands as an
additive, unwired module with 16 tests, a fail-closed verifier and a
re-stamped suite count; audit items S1 and S2 are closed on the landed tip.
No push executed.

License: Apache-2.0 (LICENSE).
