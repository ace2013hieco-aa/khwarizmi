# MERGE-LOG-DS-1 — merge/ds-1 (Digital Science fit + compress + TV-condense + S1 + carried fixes, re-stacked)

- Repo: `D:\New folder\research-agent` (GitHub `ace2013hieco-aa/khwarizmi-research`)
- Branch: `main` (fast-forwarded **locally**; merge worktree `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\met-1-merge-wt`,
  restack worktree `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\ds-1-remerge-wt`) — **LOCAL-ONLY, NO PUSH**
- Task: DS-1-REMERGE — re-stack the DS-1 commits onto current main, verify, then land (merge gate only)
- Verdict: **PASS** — `main` verified unmoved at `7407745`, clean cherry-pick re-stack (zero conflicts),
  content-identity proven, clean fast-forward, hashes preserved; application word count 1255 ≤ 1450; §9 dual hashes
  reproduce (`7b16313c46c2` director span, `e7f13585107d` audit span); stamp `--check` OK (4440);
  collect 4440; B4 24/24; ruff clean; pyright src 0/0/0; pyright tests 0 errors + 1 pre-existing warning
  (Test-Path-proven absolute `--pythonpath`; see §6 for the 108-env note); full suite 4437 passed / 3 skipped /
  0 failed (red set empty ⊆ baseline-5); `eval_plane` 205 passed in isolation. **Nothing pushed.**

## Re-stack authorization (sanctioned alternative)

- The prior STOP was a Director planning error: `MERGE-LOG-MET-1` (`7407745`) broke the fast-forward for the
  original DS-1 line (`dfd99ef`-based siblings `e78e74b..eae2492`), making a direct FF impossible.
- Rebase-prohibition D1 covers `main`'s shared history. All lines here are **local-only** (main ahead of
  `origin/main`, never pushed), and the Director explicitly authorizes this **cherry-pick re-stack** as the
  sanctioned alternative to the barred ref-move/merge-commit.
- Method: detached worktree at `7407745` → branch `slice/ds-1-restacked` → cherry-pick `e78e74b..eae2492`
  **in order, no `-n` squashing, messages kept**; conflicts would have been STOP (zero encountered — no creative
  resolution performed).

## Lineage (verified, not assumed)

- `git rev-parse main` (before) == `7407745aba4011212e456a3efbe196f9e1baf75e` → **unmoved** (no STOP).
- Composition pre-check: `git diff dfd99ef..7407745 --stat` → exactly 1 file (`docs/MERGE-LOG-MET-1.md`,
  197 insertions) — main is `dfd99ef` + the MET-1 log only, as briefed.
- Old stack root check: `git rev-parse e78e74b^` == `dfd99ef` → siblings confirmed, FF-impossible confirmed.
- `git merge-base --is-ancestor 7407745 a19c238` → true (**FF-able**).

```
main  7407745aba4011212e456a3efbe196f9e1baf75e   (verified unmoved before the FF)
  ├ 36102e8fb44753a609c692d406401e262e7f4c33  docs(ds-1): replace section 9 Fit with Digital Science (human text)
  ├ 324741d663277ef316903b95e634fa077d20ce1d  docs(ds-1): compress application to safe redundancy floor (1697 words)
  ├ b5f93aca3b970506789af5c9dcd2f13fb9f111eb  docs(ds-1): condense application Technical Validation to pointer-summary (1249 words)
  ├ 671667235d66eb2131fd56887abf62582a9e3645  docs(ds-1): qualify replay digest as same-tree consecutive-run claim (S1)
  └ a19c2388738c94d1d78ff832196b6ab3f886fa63  docs(ds-1): close carried SHOULD-FIXes - targets guard, suite date/reds, pyright interpreter
             == slice/ds-1-restacked tip
```

- Old → new hash map (cherry-pick re-stack, messages kept):

| # | Old (dfd99ef-based) | New (7407745-based) | Subject |
|---|---|---|---|
| 1 | `e78e74b73aa15f8468b17677cfdcf4706b4dfe7a` | `36102e8fb44753a609c692d406401e262e7f4c33` | §9 human text |
| 2 | `756d1cade0d67466a5a7e703a7c37d6861abcf1e` | `324741d663277ef316903b95e634fa077d20ce1d` | compress (1697 words) |
| 3 | `6b6065b79cc555ea861f339c5e970c488f2834ce` | `b5f93aca3b970506789af5c9dcd2f13fb9f111eb` | TV-condense (1249 words) |
| 4 | `227fc59eee9eba340ffaf727b8b7ffffbaf9d22c` | `671667235d66eb2131fd56887abf62582a9e3645` | S1 qualifier |
| 5 | `eae2492759163dc3d239f1ae6cc90fc608fc2faa` | `a19c2388738c94d1d78ff832196b6ab3f886fa63` | carried fixes |

- `main`: `7407745aba4011212e456a3efbe196f9e1baf75e` → `a19c2388738c94d1d78ff832196b6ab3f886fa63`
  (this log commits on top).
- `7407745` remains an ancestor of the new `main` → **pure fast-forward** (`Updating 7407745..a19c238`).
- `origin/main` observed at `258fe2b421cc023fd47f1a242db459c84d751325` (local ref; behind) — **no push performed**.

## Content-identity proof (restacked tree == eae2492 tree + MERGE-LOG-MET-1.md)

- `git diff eae2492..HEAD --stat` → exactly 1 file (`docs/MERGE-LOG-MET-1.md`, 197 insertions);
  `--name-only` both directions → the same single file.
- `git diff eae2492 HEAD -- . ':!docs/MERGE-LOG-MET-1.md' --stat` → **empty** (no other byte differs).
- Stack-shape equality: `git diff dfd99ef..eae2492 --stat` == `git diff 7407745..HEAD --stat`
  (`CATALYST-APPLICATION.md 139 ++---`, `CATALYST-QA-ANNEX.md 4 +-`; 32 insertions, 111 deletions both).
- Per-commit word-count identity (same method, `len(git-show bytes split)`): restacked `6716672` 1249 ==
  original `227fc59` 1249; restacked tip 1255 == original `eae2492` 1255.

## (c) carried-human-decision

- The §9 block is **human-authored text** landed at `e78e74b` and carried byte-identical through
  compress/condense/S1/carried-fixes **and** through this re-stack: the audit-span sha12 is identical at
  every old commit (`e78e74b/756d1ca/6b6065b/227fc59`) and at the restacked tip (`e7f13585107d`).
- No model output decided any transition or altered the text (determinism invariant holds; docs-only range).

## What landed

Docs-only slice, `+32/-111` over `main@7407745`, no `src/` / `tests/` / script / workflow / fixture /
`.gitattributes` / governed-corpus change:

```
CATALYST-APPLICATION.md | 139 +++++++++++-------------------------------------
CATALYST-QA-ANNEX.md    |   4 +-
2 files changed, 32 insertions(+), 111 deletions(-)
```

- `36102e8` (§9): human-owned `## 9. Fit with Digital Science` (byte-exact; quirks preserved: 5× en-dash
  U+2013, 3× missing-space quirks; endpoints match the quoted human text).
- `324741d` (compress 2723→1697): every section rewritten as compression; all load-bearing content survives
  (per carried audit §2); dropped material is framing/color only.
- `b5f93ac` (TV-condense, TV 523→75 incl. heading / 72 body-only): 7 bullets → 1 pointer-summary
  (`CATALYST-APPLICATION.md:81`) + `Full methods + commands in annex §7.`; figure cross-check vs annex §7
  digit-by-digit PASS (per carried audit).
- `6716672` (S1): `same-tree consecutive-run replay digest` qualifier on both digest lines (app `:81`,
  annex `:85`); fixes the MET-1 S1 digest path-sensitivity as disclosed in `MERGE-LOG-MET-1.md:82`.
- `a19c238` (carried fixes): S-b targets-guard half-sentence (`all targets in §8/annex stay targets`,
  +6 words: 1249→1255); annex suite date/reds + pyright-interpreter prose.
- Both files retain terminal `License: Apache-2.0 (LICENSE).` footers.

## Audit record carried (referenced by hash, not re-committed)

- `AUDIT-DS-1-REDTEAM.md` @ `ff2e87f7daa1f8c28bede3acea3d802cff78cd9d`
  (`audit/ds-1-redteam`, input range `dfd99ef..227fc59`; that commit adds this one file only).
  Verdict carried: **PASS-WITH-SHOULD-FIX** (0 MUST-FIX, 3 SHOULD-FIX, 1 observation).

## Adjudication

| # | Finding (carried audit `ff2e87f` / later MET-1 audit `1246b62`) | Disposition on the restacked tip |
|---|---|---|
| S-a | Director's cited `§9 block hash 7b16313c46c2` called irreproducible (10 variants tried) | **CLOSED as report-hygiene** — reproduces live on the restacked tip under the Director's stated span method (`split('## 9. Fit with Digital Science')[1].split('## 10. Budget')[0]`, sha256, 12 hex): `7b16313c46c2` (1737 bytes). Audit span reproduces too: `e7f13585107d` (1766 bytes, `## 9.` heading through blank line before `## 10.`, UTF-8, no trailing newline). Both hashes + methods recorded in §6; no doc change needed. |
| S-b | Pointer drops the targets-remain-targets / explicitly-absent guard | **FIXED in-stack** by `a19c238` (`all targets in §8/annex stay targets`; 1249→1255 words, identity-proven). |
| S-c | Dimensions pilot months 2–4 precedes §7 Phase 3 DS scoping months 4–6 (sequencing tension, disclosed) | **CARRIED OPEN** — §9 is human-owned byte-exact (identity proven above); tensions are disclosed, not concealed (`:63` header, asks framed as asks, no commitment assumed); needs human approval, never a merge-blocker. |
| O-1 | GitHub issue #5 unresolvable (human-text provenance beyond `e78e74b` unverifiable) | Observation; landed text stable through whole stack (proven); no action. |
| M1 | Later MET-1 audit: producer env showed `5 failed` (exactly baseline-5) vs shipped `0 failed` | **Gate-irrelevant** — both satisfy red set ⊆ baseline-5. Live on the restacked tip (repo venv): **0 failed** (4437 passed / 3 skipped); shipped claim reproduces in this env. |
| M2 | Later MET-1 audit: pyright tests prose `0 errors` vs `108 errors` with relative `--pythonpath` from a venv-less worktree | **Method artifact, gate-irrelevant** — with the binding absolute `--pythonpath` (`D:/New folder/research-agent/.venv/Scripts/python.exe`, Test-Path True) the restacked tip gives **src 0/0/0, tests 0 errors + 1 pre-existing warning** (see §6). The `108` (`reportMissingImports` for `pytest`) stays the documented relative-path baseline; NEVER reported without the interpreter's Test-Path. |

No MUST-FIX in the carried audit; nothing held this landing. **HARD RULE check: no FAIL audit exists on the
landing range `7407745..a19c238`** (range diff is docs-only, 2 files; `ff2e87f` is PASS-WITH-SHOULD-FIX;
`1246b62` FAIL is scoped to MET-1 and disposed above with its S1 fixed-in-stack) → no STOP.

## Changed files (7407745..a19c238)

```
CATALYST-APPLICATION.md   (§9 human text + compress + TV pointer-summary + S1 qualifier + S-b guard)
CATALYST-QA-ANNEX.md      (S1 qualifier + suite date/reds + pyright-interpreter prose)
```

No `src/`, `tests/`, script, workflow, fixture, `.gitattributes` or governed-corpus change.

## Gates (raw, on restacked tip `a19c238`, offline, `PYTHONPATH=<wt>\src`, no extra `-q`)

- **Application word count** (in-process `len(git-show bytes split)`) → `1255` (bytes 9850) ≤ 1450, margin 195. **PASS.**
  Per-commit: `dfd99ef 2617` → `e78e74b 2723` → `756d1ca 1697` → `6b6065b 1249` → `227fc59 1249` →
  tip `1255` (+6 = carried S-b fix; prior 1249 gate re-verified at `6716672`/`227fc59`, delta explained, no drift).
- **§9 hashes** (in-process sha256, 12 hex) → director span `7b16313c46c2` (1737 bytes) **== cited**;
  audit span `e7f13585107d` (1766 bytes) **== carried audit**. Recorded, not relitigated.
- **Stamp `--check`** (`scripts/stamp_suite_count.py --check`) →
  `OK: docs\SUITE-COUNT.md collected=4440 matches the live collect` (exit 0).
- **Collect** (`scripts/run_tests.py tests --collect-only` equivalent) → `4440 tests collected in 1.33s`.
- **B4** (`scripts/run_tests.py tests/test_b4_ref_graphs.py`) → `24 passed in 4.47s` = **24/24**.
- **Ruff** (`python -m ruff check src tests`, ruff 0.16.10, repo venv) → `All checks passed!` (exit 0).
- **Pyright src** (`uvx pyright src --pythonpath "D:/New folder/research-agent/.venv/Scripts/python.exe"`,
  interpreter Test-Path: **True**) → `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests** (`uvx pyright --pythonpath "D:/New folder/research-agent/.venv/Scripts/python.exe" --project pyrightconfig.tests.json`,
  interpreter Test-Path: **True**) → `0 errors, 1 warning, 0 informations` (exit 0); the 1 warning is the
  pre-existing `tests/test_research_program.py:144:23 - warning: Instance methods should take a "self"
  parameter (reportSelfClsParameterName)`. The `108` import-resolution errors fire only with a nonexistent
  interpreter path (artifact, not code) — never reported without the Test-Path.
- **Full suite** (`scripts/run_tests.py tests --tb=short -rf`) →
  `4437 passed, 3 skipped in 523.63s (0:08:43)` (`EXIT=0`).
  Pass+skip = 4440 = collect. Skip delta vs the pre-carry prose (3 vs 15) is env-only: the repo venv has
  docling/crawl4ai installed (12 pinned external-provider legs run and pass); a venv lacking them skips 15.
  No drift: `--check` OK. Same 4437/3 shape as the MET-1 landing run in this env.

## Red set == empty (⊆ documented baseline-5) + documented flake isolation

```
Full-suite failures: none (0 failed).
```

The documented environmental baseline-5 (`docs/MERGE-LOG-NUM-1.md`, via `docs/archive/MERGE-LOG-CLOUD.md`:
3 concurrency races + 1 Windows symlink-privilege refusal + 1 q05 race) did not fire in this env.
Empty set ⊆ baseline-5 → **no new red; delta 0**. The documented `test_eval_plane.py` 30 s
pinned-subprocess-timeout flake did not fire in the full run; **isolation proof** (re-run on the restacked
tip in `ds-1-remerge-wt`, repo venv):

```
tests/test_eval_plane.py in isolation, restacked tip, ds-1-remerge-wt : 205 passed in 39.62s (EXIT=0)
```

## STOP-condition checks

| Condition | Result |
|---|---|
| NOT-list hit (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`) | **PASS** — `CLEAR` (0 hits) over `e78e74b^..eae2492` (commit subjects/bodies + diff) |
| main moved before the FF | **PASS** — unmoved at `7407745aba4011212e456a3efbe196f9e1baf75e` (re-verified immediately pre-FF) |
| cherry-pick conflict / creative resolution | **PASS** — 5/5 applied clean, messages kept, no squashing |
| content-identity fails | **PASS** — restacked == `eae2492` + `MERGE-LOG-MET-1.md` (both-directions diff = that 1 file; exclusion diff empty) |
| red set superset of baseline | **PASS** — red set empty ⊆ baseline-5; flake isolation-proven |
| `--check` drift | **PASS** — `--check` OK, collected 4440 = 4437+3 |
| application word count > 1450 | **PASS** — 1255 ≤ 1450 (margin 195) |
| stale main-bound worktree left behind | **PASS** — `main` bound only to `met-1-merge-wt` at the final tip, clean (see Hygiene) |
| FAIL audit on the landing range | **PASS** — none (HARD RULE checked, scopes + dispositions above) |
| push without a human hash-pin | **none performed** |

## Worktree hygiene

- `met-1-merge-wt` (Tay's arrangement preserved): was bound to `main@7407745` clean → FF'd in place to the
  restacked tip → this log commits on top; ends bound to `main` at the final tip, clean.
- `ds-1-remerge-wt`: holds `slice/ds-1-restacked@a19c238` (not main-bound; own restack work — left in place).
- `ds-1-merge-wt` (detached @ `eae2492`), `ds-1-audit-wt`, `ds-1-fix-wt`, all other sessions' worktrees: **untouched**
  (retire-superseded-holders only if stale — none here is a stale main-bound holder).
- `git worktree prune` / FF-time step-4 error (`failed to delete '.git/worktrees/step-4': Permission denied`) —
  **known, ignored per brief** (same as MET-1).

## Push charters (DRAFTED, NOT EXECUTED)

D8/D9: every push requires explicit human approval and a hash pin. **No `git push` was run.**

**Charter A — `khwarizmi-research` (origin) — plain push**
- Remote: `origin https://github.com/ace2013hieco-aa/khwarizmi-research.git`
- Observed: `origin/main` = `258fe2b421cc023fd47f1a242db459c84d751325` (behind; local ref, offline).
- Proposed (hash-pinned): `git push origin <reviewed-main-hash>:refs/heads/main` (no `--force`, no `--tags`),
  where `<reviewed-main-hash>` is the human-approved final tip **plus** this log commit once reviewed
  (currently `main` = `a19c2388738c94d1d78ff832196b6ab3f886fa63` pre-log).
- Preconditions: human approves; `origin/main` still at/behind `258fe2b…`; local tree clean; pushed hash ==
  reviewed hash.

**Charter B — `khwarizmi` public mirror — orphan-sync**
- Remote: not configured in this checkout; parent pinned by rule at mirror HEAD `1192b51…`.
- Convention: orphan-sync — the sync commit's **parent is the mirror HEAD** (`1192b51…`), so the push is a
  fast-forward; **no `--force`** (rule #5).
- Proposed (hash-pinned): `git commit-tree <reviewed-main-tree> -p 1192b5152edc81174cb905fa2bbc1cf532829f91 -m "sync: DS-1 restack from dev main@<hash>"`, verify `sync^{tree} == <reviewed-main>^{tree}` and `merge-base --is-ancestor 1192b51… <sync>`, then `git push <mirror> <sync>:refs/heads/main`.
- Preconditions: same reviewed hash as Charter A; mirror public; human approves.

## Credential-path statement

- No live vendor calls and no real credentials were used. All gates ran offline; `--check` performs only a
  local `pytest --collect-only`.

## NOT-LIST scan

`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy` over `e78e74b^..eae2492` (commit subject/body and the
diff bytes, case-sensitive): **no hits** (`CLEAR` × 4).

## STOP BEFORE PUSH

`main` is fast-forwarded **locally only** (plus this log commit). Nothing is pushed. Both charters above
require a human hash-pin before execution.
