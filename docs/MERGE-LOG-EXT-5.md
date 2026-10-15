# MERGE-LOG-EXT-5 — EXT-5 operator-output boundary (R3) landed on `main`

Merge-gate record for the EXT-5 slice: an additive operator-output
control-byte boundary (`slice/ext-5-cliscrub@7d25fee`, 7 files,
+687/−125) plus its redteam-audit SHOULD-FIX closure
(`fix/ext-5-bidi@c22441e`, 4 files, +56/−7), landed on `main` by
**local fast-forward only**. Follows the `MERGE-LOG-EXT-4` /
`MERGE-LOG-EXT-3` pattern.

**Outcome: EXT-5 landed on `main` — local fast-forward, no push.**
Redteam audit `audit/ext-5-redteam@a0a9808` is **PASS-WITH-SHOULD-FIX**
(0 MUST-FIX, 1 SHOULD-FIX, 3 observations); the single SHOULD-FIX
(U+061C ARABIC LETTER MARK passing `scrub()` raw — display-direction
spoof only, no control byte, no line-forging) is **closed** by
`c22441e` on the landed tip, whose Bidi_Control coverage is now
exactly the 12-code-point Unicode inventory (proven live below).
**`origin` and the public mirror are NOT advanced and NOT pushed —
D8/D9 require a human hash-pin.**

## Provenance

| Item | Value |
| --- | --- |
| Task | EXT-5-MERGE (merge gate, local-only) |
| Base (`main` before) | `45e479c8554f572c5780782678c79cef4c6257b4` |
| Landed tip (FF'd to) | `c22441e82fdc54911be6a84d5dbd6e49452d64a2` |
| Branch | `slice/ext-5-cliscrub` @ `7d25fee` → `fix/ext-5-bidi` @ `c22441e` |
| Gate worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/ext-5-merge-wt` |
| Main-bound holder | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` (FF'd **in place**) |
| Merge method | **fast-forward in place**, `git merge --ff-only` |
| FF evidence | `merge-base(main, c22441e)` == `main` == `45e479c`; exit 0 |
| Rebase / merge commit / force | **none** — 0 merges in range, one parent per commit; the cited slice/fix tips keep their hashes |
| Audit | `audit/ext-5-redteam@a0a9808` — PASS-WITH-SHOULD-FIX; **no FAIL on the range** |

## What landed

The R3 remedy: every operator-facing CLI line is now emitted through
one boundary instead of raw `print`:

- `src/hermes/output.py` (new, +149) — `scrub()` escapes, per code
  point and reversibly (`\xNN` / `\uNNNN`), the forbidden classes:
  32 C0 + 32 C1 + DEL + the Bidi_Control set; `emit` / `emit_lines`
  fail **closed**: a guard violation refuses with rc=1 and a fixed
  refusal line on stderr — never a silent success, never a traceback.
- `src/hermes/cli.py` — 94 emit sites, **0 bare `print`** after the
  slice (94 before, all raw).
- `src/hermes/eval/platform_cli.py` — 15 sites; `src/hermes/eval/matrix.py` — 1 site. Total 110 boundary sites (certified census 94/15/1).
- `tests/test_output_boundary.py` + `tests/test_cli_output_scrub.py` — +142 / +244 (slice) and +24 / +24 (fix) = **108 pins** total.
- `docs/SUITE-COUNT.md` — re-stamped **4479 → 4583 → 4587** (the fix re-stamp is its own commit, `7d25fee`).

The fix (`c22441e`) is **set membership only** — no scrub/guard/emit
logic changed: `0x061C` joins `_BIDI_OVERRIDES`. ZWSP/ZWNBSP/ZWJ stay
deliberately out (Cf, invisible but not direction-spoofing).

## Content identity (pure FF — nothing rewritten)

No restack, no cherry-pick, no conflict: the landed range is the two
branches verbatim. Raw:

```
$ git log --oneline 45e479c..c22441e
c22441e fix(output): escape U+061C (ALM) in the bidi boundary (EXT-5 S1)
7d25fee chore(num-1): re-stamp the collected suite count (4583)
a7fc507 fix(cli): emit every operator line through the output boundary (EXT-5 R3)
c9ef9a9 feat(output): add the operator-output control-byte boundary (EXT-5 R3)

$ git rev-list --count --merges 45e479c..c22441e
0
$ c22441e parents = 1

$ merge-base(45e479c, 7d25fee) = 45e479c8554f572c5780782678c79cef4c6257b4
$ merge-base(7d25fee, c22441e) = 7d25fee2c49b98ffae47794079e9be7ad6b006e8

$ git diff --name-status 45e479c c22441e
M       docs/SUITE-COUNT.md
M       src/hermes/cli.py
M       src/hermes/eval/matrix.py
M       src/hermes/eval/platform_cli.py
A       src/hermes/output.py
A       tests/test_cli_output_scrub.py
A       tests/test_output_boundary.py

$ git diff --stat 45e479c c22441e   (tail)
 7 files changed, 736 insertions(+), 125 deletions(-)
```

Stamp chain: **4479 + 104 = 4583** (slice) **+ 4 = 4587** (fix);
`stamp --check` reproduces 4587 live (below).

## U+061C closure (audit S1) — Bidi_Control inventory now exactly 12/12

The audit reproduced the hole live (`061C_raw passes_raw True` while
sibling LRM U+200E was escaped) and registered it SHOULD-FIX. The fix
closes it by membership. Raw, live on the landed tip
(`PYTHONPATH=<wt>/src`):

```
repr scrub(chr(0x061C)) = '\u061c'          # escaped, visible, reversible
repr scrub(chr(0x200E)) = '\u200e'          # sibling LRM — same treatment
0x061C in _BIDI_OVERRIDES: True             # set n = 12
_BIDI_OVERRIDES == {0x061C, 0x200E, 0x200F} | 0x202A-0x202E | 0x2066-0x2069: True
```

The 12 members are exactly the Unicode Bidi_Control property:
`061C, 200E, 200F, 202A-202E, 2066-2069`. New pins (all inside the
108‑slate, all green below): a primitive pin
(`tests/test_output_boundary.py:75-81`), a full-inventory pin (`:92`),
and an end-to-end CLI pin proving the raw ALM UTF-8 bytes
(`0xD8 0x9C`) never reach the console and the visible `\u061c`
spelling does, with the stored row byte-identical
(`tests/test_cli_output_scrub.py:135+`).

## Gates (raw, on the landed tip `c22441e`, `PYTHONPATH=<wt>/src`, no extra `-q`)

Interpreter for every gate below:
`D:/New folder/research-agent/.venv/Scripts/python.exe`
(**Test-Path: True**, Python 3.14.1, pyright 1.1.414, ruff 0.17.0).

```
######## COLLECT ########
4587 tests collected in 9.63s
COLLECT_EXIT=0

######## STAMP --check ########
OK: docs\SUITE-COUNT.md collected=4587 matches the live collect
STAMP_EXIT=0

######## PINS 108 ########
108 passed in 0.69s
PINS_EXIT=0

######## B4 24 ########
24 passed in 3.78s
B4_EXIT=0

######## CENSUS (emit recount, in-process) ########
src/hermes/cli.py: bare_prints=[] sites=94 expected=94 match=True
src/hermes/eval/platform_cli.py: bare_prints=[] sites=15 expected=15 match=True
src/hermes/eval/matrix.py: bare_prints=[] sites=1 expected=1 match=True
CENSUS EMIT: PASS 94/15/1
CENSUS_EXIT=0

######## CHECK_CENSUS ########
certified census check - src/hermes (read-only)

figure                                       certified  measured  status
------------------------------------------------------------------------------
executed transaction-control calls                 121       121  OK
acquisition owners (persistence)                    18        18  OK
acquisition owners (gateway)                         5         5  OK
acquisition owners (Controller)                      4         4  OK
acquisition owners (total)                          27        27  OK
rollback-only participants                           1         1  OK
persistence->research import statements             15        15  OK
control calls outside certified layers               0         0  OK

PASS - every certified figure is reproduced exactly.
CHECKCENSUS_EXIT=0

######## RUFF ########
All checks passed!
RUFF_EXIT=0

######## PYRIGHT SRC ########
0 errors, 0 warnings, 0 informations
PYRIGHT_SRC_EXIT=0

######## PYRIGHT TESTS (absolute --pythonpath <venv>, pyrightconfig.tests.json) ########
tests\test_research_program.py:144:23 - warning: Instance methods should take a "self" parameter (reportSelfClsParameterName)
0 errors, 1 warning, 0 informations
PYRIGHT_TESTS_EXIT=0

######## FULL SUITE (scripts/run_tests.py tests --tb=short -rf) ########
4584 passed, 3 skipped in 540.99s (0:09:00)
FULLSUITE_EXIT=0
```

`4584 + 3 = 4587` == collect. The single warning is the pre-existing
`tests/test_research_program.py:144` (on `main` since before this
slice, identical in `MERGE-LOG-EXT-4`).

## Red set: EMPTY (subset of baseline-5, delta 0)

No test failed — `FAILED`/`ERROR` lines in the full-suite log: 0. The
documented environmental baseline-5 (3 concurrency races, 1 Windows
symlink-privilege refusal, 1 q05 race — `docs/archive/MERGE-LOG-CLOUD.md`,
reproduced through `MERGE-LOG-NUM-1` / `-FRONT-1` / `-EXT-2` / `-EXT-3` /
`-EXT-4`) did not fire on this run either. **Empty ⊆ baseline-5; no new
red.** The documented `tests/test_eval_plane.py` timing flake did not
fire (`test_eval_plane` mentions: 0), so no isolation proof was
required.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list functional coupling (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`) | **PASS** — 0 case-sensitive hits in the range commit subjects/bodies and in the full range diff; the loose case-insensitive sweep surfaces only the substring `tse` inside ordinary English ("it**se**lf", ×3 in diff prose) — not a mention; reported for the record |
| `main` moved before the FF | **PASS** — re-verified unmoved at `45e479c` immediately pre-FF (holder `met-1-merge-wt` clean at the same hash) |
| FF-ability fails | **PASS** — `merge-base(main, c22441e)` == `main`; `git merge --ff-only` exit 0 |
| red set superset of baseline-5 | **PASS** — red set empty, delta 0 |
| `--check` drift | **PASS** — `collected=4587` == live collect 4587 |
| roadmap diff beyond the status cell | **PASS** — numstat `1 1`; word-diff shows only `QUEUED` → `LANDED (c22441e)` |
| stale main-bound worktree left behind | **PASS** — `met-1-merge-wt` clean and bound to `main` at the final tip after the two docs commits |
| FAIL audit on the range | **PASS (did not fire)** — audit is PASS-WITH-SHOULD-FIX, the single item closed by `c22441e` |
| push without a human hash-pin | **none performed** |

Ignored by charter: a `git` housekeeping step emitted
`error: failed to delete 'D:/New folder/research-agent/.git/worktrees/step-4': Permission denied`
while the FF operations pruned a stale worktree admin entry. It
concerns an unrelated, already dead entry and has no effect on the
landing; recorded, not acted on.

## Carried residual — vault note bodies (its own slice, NOT landed here)

Audit observation O2: the boundary covers the **operator's terminal
lines only**. Vault note bodies remain raw files on disk by design —
only the operator's CLI status lines (e.g. `cli.py:703` "Projected …",
`:914` usage) go through `emit`. Scrubbing terminal lines cannot move
vault note digests, and `NOTE_DIGEST_DIVERGES` (recomputed journal
digest != manifest digest) stays the journal↔vault drift detector. Any
vault-body scrub must be chartered as **its own slice**; it is not
covered by EXT-5 and does not land with this merge. (Same status for
audit O1: `--report-path` file reports are byte-raw by design — a file
report is data, not terminal bytes; do not "fix" it by escaping.)

## Worktree hygiene

`met-1-merge-wt` (house arrangement preserved): bound to `main@45e479c`
and clean → FF'd **in place** to `c22441e` → the two docs commits land
on top → ends bound to `main` at the final tip, clean.
`ext-5-merge-wt`: gate worktree created detached at `45e479c`, FF'd to
`c22441e`; all gates above ran there; the two docs commits are made
there and `main` is FF'd again over them. The slice author's `ext-5-wt`
(`7d25fee`), the fix worktree `ext-5-fix-wt` (`c22441e`), the audit
worktree `ext-5-audit-wt` (`a0a9808`) are untouched. The shared
checkout, `.hermes/`, JSON files and all other worktrees were never
touched.

## Dual push plans — drafted, NOT executed (D8/D9)

No push was performed by this gate. Both plans require a human hash-pin.

1. **`origin` plain-push** (`https://github.com/ace2013hieco-aa/khwarizmi-research.git`):
   push `<reviewed-main-hash>:refs/heads/main`, single refspec, no force,
   no tags, after re-verifying live `origin/main` is a strict ancestor of
   the reviewed tip (FF). Live `origin/main` at draft time:
   `45e479c8554f572c5780782678c79cef4c6257b4` — a strict ancestor of the
   local `main`, so the plain push would fast-forward.
2. **public mirror orphan-sync** (`https://github.com/ace2013hieco-aa/khwarizmi`):
   add a temp remote, `fetch --no-tags`, re-read the live mirror pin,
   build a sync commit whose tree is `<tip>^{tree}` and whose parent is
   the mirror HEAD (orphan convention — `merge-base` must be empty),
   push the exact hash with **no force** (rule #5), then remove the temp
   remote. Live mirror HEAD at draft time:
   `471540d50c2950b275781fe8e1e9a1cc22697d82` — a moving target, always
   re-read with `ls-remote` immediately before the sync.

## Verdict

### A — EXT-5 MERGED (LOCAL-ONLY)

`main` FF'd `45e479c8554f572c5780782678c79cef4c6257b4` →
`c22441e82fdc54911be6a84d5dbd6e49452d64a2`; the two docs commits (this
MERGE-LOG and the roadmap row-4 flip) land on top. The operator-output
control-byte boundary lands additive-only at the display edge: all 110
operator emit sites (94 + 15 + 1, zero bare prints) route through one
scrub/emit boundary; the Bidi_Control inventory is exactly the Unicode
12; refusal is fail-closed and loud (rc=1 + fixed line, never silent);
the suite count is re-stamped 4587; audit S1 (U+061C) is closed on the
landed tip. No push executed.

License: Apache-2.0 (LICENSE).
