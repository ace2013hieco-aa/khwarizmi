# MERGE-LOG-DETECT — detector + census lines + delta audits

**Task ID:** MERGE-DETECT. **Role:** merge integrator (integrate, verify, audit).
**Precedent:** `docs/MERGE-LOG-SCANFIX.md` / `docs/MERGE-AUDIT-SCANFIX.md`
(patch-exactness + re-proofs). **Authority window:** D9 **LAPSED** — merge + audit
ONLY. **Nothing was pushed.** Local `main` was **not advanced, not checked out, not
rebased, not amended**. The 14 unpushed platform commits on `main` were never
touched. This document is the integration record; the independent verification and
the PASS/FAIL verdict are in `docs/MERGE-AUDIT-DETECT.md`.

## 1. Outcome

Three input lines were integrated onto a **local-only** branch `merge/detect` cut
from local `main`, in an **isolated worktree** (`D:/tmp/merge-detect-wt`). All three
merges completed with **zero conflicts** under the `ort` strategy; no STOP condition
fired. No `src/` change was authored by the integrator — every byte in the merged
tree is either base `main` or an authored line delta (proved by INV-A…INV-F, §5).
Every gate is green: full suite **3800 passed / 0 failed / 0 skipped**, ruff clean,
`pyright src` 0 errors 0 warnings, `pyright --project pyrightconfig.tests.json`
0 errors (1 pre-existing warning), certified-census checker 8/8 figures OK, census
anchor 3 passed, differential-replay harness 3/3 PASS. Integration tip is
**`50c3fdc0d54e7051ff968f5f50bcdc518cbf99cb`**.

## 2. Inputs (receipts)

| Item | Value |
|---|---|
| Repo | `D:\New folder\research-agent` |
| GitHub | `ace2013hieco-aa/khwarizmi-research` (`origin`) |
| BASE local `main` (verified) | `ac1860a5b3500bcc970833e426120af4233b49af` — `feat(wiring): W4 spine registration (tick call-site, consult kwarg, OPERATOR hunk, HandlerResult adaptation)` |
| `origin/main` | `e4b276db7880cb8c0e17e1239e03c589138541ae` |
| `main` vs `origin/main` | **14 ahead, 0 behind** (`git rev-list --left-right --count origin/main...main` → `0  14`) |
| Line 1 | `fix/det-express` @ `4d1513b30fcca4b09f564f528226114146cd7823` (parent `a8f0180`) |
| Line 2 | `fix/high04-fairness` @ `33e00838f73e25def6a511ce29b92aa5fa827dd7` (parent `4d1513b` — **linear pair**) |
| Line 3 | `fix/census-sweep` @ `843c28122828021d0edafa163c4b83dd43c7735d` (parent `ac1860a` — **separate**) |
| Integration branch | `merge/detect` — **LOCAL-ONLY, NO PUSH** |
| Worktree | `D:/tmp/merge-detect-wt` (isolated; `.venv` symlinked to the host venv) |
| Interpreter | Python **3.14.1** |
| Import provenance | `hermes -> D:\tmp\merge-detect-wt\src\hermes\__init__.py` (worktree `src/`, not the host tree) |

The 14 unpushed platform commits carried by BASE `main` (`efff4fd`, `25aeb7a`,
`8cc3539`, `2dab02a`, `c4ca8cb`, `66c73f0`, `d66e841`, `c24df0c`, `a8f0180`,
`f2142a1`, `54f7cb5`, `ca387d8`, `6d6c83d`, `ac1860a`) are the platform/wiring line.
`merge/detect` only **descends** from them; none was rewritten, and none was pushed.

Remote read-only probe (`git ls-remote origin refs/heads/main refs/heads/merge/detect`):

```
e4b276db7880cb8c0e17e1239e03c589138541ae	refs/heads/main
```

`refs/heads/merge/detect` is **absent from the remote** — the branch exists only
locally. No write of any kind was made to `origin`.

## 3. Merge hashes

| # | Merge commit | First parent | Second parent | Strategy | Conflicts |
|---|---|---|---|---|---|
| 1 | `b35373d12f5f7cd77950f6b15c93ff72d5505bd2` | `ac1860a` (main) | `4d1513b` (det-express) | `--no-ff`, `ort` | **0** |
| 2 | `54b0a6ef93cf88e7e17bbde828423442d4a733e8` | `b35373d` | `33e0083` (high04-fairness) | `--no-ff`, `ort` | **0** |
| 3 | `50c3fdc0d54e7051ff968f5f50bcdc518cbf99cb` | `54b0a6e` | `843c281` (census-sweep) | `--no-ff`, `ort` | **0** |

`--no-ff` preserves each line's tip as a real second parent, so lineage stays
readable and each line's own delta stays independently diffable (INV-A…INV-C).

## 4. Changed files (`git diff --numstat main HEAD`)

```
266	0	scripts/replay_diff.py
4	4	src/hermes/eval/ops.py
184	24	src/hermes/research/contradictions.py
16	2	src/hermes/research/controller.py
2	2	src/hermes/research/programs.py
1	1	src/hermes/tools/capabilities/invoke.py
1	1	src/hermes/tools/providers/hazards.py
4	4	src/hermes/tools/providers/normalize.py
165	0	tests/test_census_anchor.py
185	0	tests/test_replay_diff.py
10 files changed, 828 insertions(+), 38 deletions(-)
```

Ownership: lines 1+2 own `scripts/replay_diff.py`,
`src/hermes/research/contradictions.py`, `src/hermes/research/controller.py`,
`tests/test_replay_diff.py`; line 3 owns the five census-swept `src/` modules and
`tests/test_census_anchor.py`. No file is claimed by two lines except
`controller.py`, which carries base `main`'s W4 hunks **plus** the detector hunks
(§6). No documentation file was touched by any line.

## 5. Integrity invariants (patch-exactness)

| ID | Invariant | Measurement | Result |
|---|---|---|---|
| INV-A | det-express own delta == authored delta | `git diff --stat main b35373d` → 4 files, 442+/27−; `git diff --stat a8f0180 4d1513b` → 4 files, 442+/27− (same per-file rows) | **PASS** |
| INV-B | fairness own delta == authored delta | `git diff --stat b35373d 54b0a6e` → 3 files, 238+/28−; `git diff --stat 4d1513b 33e0083` → 3 files, 238+/28− (same per-file rows) | **PASS** |
| INV-C | census own delta == authored delta | `git diff --stat 54b0a6e 50c3fdc` → 6 files, 177+/12−; `git diff --stat ac1860a 843c281` → 6 files, 177+/12− (same per-file rows) | **PASS** |
| INV-D | fairness-owned files byte-identical to the fairness tip | `git diff --exit-code 33e0083 HEAD -- scripts/replay_diff.py src/hermes/research/contradictions.py tests/test_replay_diff.py` → empty, **exit 0** | **PASS** |
| INV-E | census-owned files byte-identical to the census tip | `git diff --exit-code 843c281 HEAD -- src/hermes/eval/ops.py src/hermes/research/programs.py src/hermes/tools/capabilities/invoke.py src/hermes/tools/providers/hazards.py src/hermes/tools/providers/normalize.py tests/test_census_anchor.py` → empty, **exit 0** | **PASS** |
| INV-F | zero true conflict markers | `git grep -n -E "^(<<<<<<<\|>>>>>>>) \|^=======$" HEAD -- src tests scripts docs README.md agents.md` → **exit 1 (zero hits)** | **PASS** |
| INV-G | `controller.py` merged delta == authored delta, W4 preserved | `+`/`−` lines of `git diff main HEAD -- …controller.py` (18) vs `git diff a8f0180 33e0083 -- …controller.py` (18) → `diff` **IDENTICAL** | **PASS** |

INV-F note: a naive `^=======` scan produces false positives from decorative table
rules (`src/hermes/research/autonomy_caps.py:13,15,60`) and `docs/ix/*` report
headers. The precise scan above anchors to a **bare** seven-character rule and to
angle-bracket markers with a trailing space; both are absent.

INV-G is the load-bearing one: `main` already contains the W4 hunks, so they cancel
out of `main..HEAD`, and what remains is byte-for-byte the detector delta the two
lines authored. The integrator wrote no `src/` change.

## 6. Conflicts — verified, not assumed

Zero conflicts were reported by `ort` on all three merges. The one file with
overlapping *interest* between base `main` and an input line is
`src/hermes/research/controller.py`; disjointness was checked at the hunk level
rather than inferred:

| Provenance | Hunks at the merged tip | Region |
|---|---|---|
| base `main` (W4 spine registration) | `:3115` `binder = getattr(entry, "bind_controller", None)`; `:3163` `if getattr(entry, "wiring_template", False):`; `:3173`/`:3181`/`:3186` `recorded_no` variants | ~3115–3186 |
| lines 1+2 (detector diagnostics pass) | `:2425` `DETECTOR_TRUNCATED,` import; `:2430` `diagnostics: dict = {}`; `:2434` `rows, diagnostics=diagnostics`; `:2442` `truncated = diagnostics.get(DETECTOR_TRUNCATED)`; `:2448` note text + `key="contradiction:detector-truncated"` | ~2425–2495 |

The two regions are **~630 lines apart** with no intervening shared context, which is
why `ort` merged them independently and why both survive verbatim (INV-G).

No `src/` change beyond conflict repair was needed, because there were no conflicts
to repair: `git diff --exit-code 50c3fdc HEAD -- src tests scripts` → **exit 0**
(re-verified after both documentation commits — the docs commits are `src`/`tests`
neutral).

## 7. Disclosure — stale worktree admin directory

Each of the three `git worktree` operations printed:

```
error: failed to delete 'D:/New folder/research-agent/.git/worktrees/step-4': Permission denied
```

This is a **pre-existing stale worktree admin entry** from earlier work on this host,
not a product of this integration; git prunes stale admin directories opportunistically
and the deletion is blocked by a Windows file lock. It does not affect HEAD, the index,
or the merge result. `git rev-parse HEAD` was re-checked after every merge and matched
the intended commit each time. `docs/MERGE-LOG-SCANFIX.md` discloses the identical
condition. No `step-4` worktree was created, modified, or deleted by this task.

## 8. Gate results

All gates run from `D:/tmp/merge-detect-wt` with
`PYTHONPATH=D:/tmp/merge-detect-wt/src` (absolute), and both pyright invocations
additionally pass an absolute `--pythonpath`.

| Gate | Command | Result |
|---|---|---|
| Full suite | `PYTHONPATH=… .venv/Scripts/python.exe scripts/run_tests.py` | `3800 passed, 12 warnings in 619.11s (0:10:19)` — **exit 0** |
| Lint (C3) | `uvx ruff check src tests` | `All checks passed!` — **exit 0** |
| Types, src (strict) | `uvx pyright --pythonpath D:/tmp/merge-detect-wt/.venv/Scripts/python.exe src` | **0 errors, 0 warnings, 0 informations** — exit 0 |
| Types, tests | `uvx pyright --pythonpath … --project pyrightconfig.tests.json` | **0 errors, 1 warning, 0 informations** — exit 0 |
| Certified census | `… scripts/check_census.py` | **PASS — every certified figure reproduced exactly** (8/8 OK) — exit 0 |
| Census anchor | `… scripts/run_tests.py tests/test_census_anchor.py -v` | **3 passed** — exit 0 |
| Detector tests | `… scripts/run_tests.py tests/test_replay_diff.py -v` | **14 passed** — exit 0 |
| Differential replay harness | `… scripts/replay_diff.py` | **PASS ×3** (`run_twice_equal[n=5]`, `journal_reproduces_derived[n=5]`, `fan_out_bounded[n=100]`) — exit 0 |

The single pyright-tests warning is `tests/test_research_program.py:144:23 -
warning: Instance methods should take a "self" parameter
(reportSelfClsParameterName)`. That file is **not** touched by any integrated line
(absent from §4) and the warning is inherited from base `main`; it is a warning, not
an error, and the gate exits 0.

Certified-census checker output:

```
figure                                       certified  measured  status
------------------------------------------------------------------------------
executed transaction-control calls               121       121  OK
acquisition owners (persistence)                  18        18  OK
acquisition owners (gateway)                       5         5  OK
acquisition owners (Controller)                    4         4  OK
acquisition owners (total)                        27        27  OK
rollback-only participants                         1         1  OK
persistence->research import statements           15        15  OK
control calls outside certified layers             0         0  OK

control calls by statement: BEGIN 28, COMMIT 27, ROLLBACK 66
owners by layer: persistence 18, gateway 5, Controller 4
```

These are the figures `agents.md` certifies (27 acquisition owners = persistence 18 +
gateway 5 + Controller 4, plus 1 rollback-only participant; 15 persistence→research
import statements). The census-sweep line changes identifier *grammar* (`$` → `\Z`)
and adds an anchor test; it does not move any census figure. Both the checker and the
new anchor agree at the merged tip.

## 9. Count lineage

| Ref | Files | Collected | Own delta | Evidence |
|---|---|---|---|---|
| `a8f0180` (det-express base, on `main`) | — | — | — | neither new test file present |
| `ac1860a` — **BASE local `main`** | 98 | **3783** | — | neither new test file present |
| `4d1513b` — `fix/det-express` | 95 | 3695 | **+9** | `tests/test_replay_diff.py: 9` (new file) |
| `33e0083` — `fix/high04-fairness` | 95 | 3700 | **+5** | `tests/test_replay_diff.py: 14` (round-robin coverage) |
| `843c281` — `fix/census-sweep` | 99 | 3786 | **+3** | `tests/test_census_anchor.py: 3` (new file) |
| `50c3fdc` — **merged tip** | **100** | **3800** | — | both files present: `test_census_anchor.py: 3`, `test_replay_diff.py: 14` |

Arithmetic reconciles **exactly**:

```
3783 (base main)
  + 9 (det-express: test_replay_diff.py, new)
  + 5 (high04-fairness: round-robin tests added to the same file)
  + 3 (census-sweep: test_census_anchor.py, new)
= 3800  == merged tip collected  == merged tip passed
98 base files + 2 new files = 100 files
```

`4d1513b`/`33e0083` show 95 files rather than 99 because that pair branched off
`a8f0180`, an **earlier** `main` that predates the W1–W4 wiring test files; only their
*own deltas* are additive to this integration. Collection counts were taken per ref in
throwaway detached worktrees (`D:/tmp/md-{base,detex,fair,census}`) so that no ref was
checked out inside the integration worktree.

Collected == passed with **zero** skip/xfail/error characters in the run: the
outcome-character census over the suite's progress lines is `{'.': 3800}`, i.e. 3800
passes and nothing else.

Disclosure — the first full-suite run printed progress characters but **no** final
summary line. Cause: `pyproject.toml:38` sets `addopts = "-q -p no:hypothesis
-p no:anyio"`, and the invocation added a second `-q`; double-quiet suppresses
pytest's summary. This is an **invocation artifact, not a suite defect**. The suite
was re-run canonically (no extra `-q`) from the same worktree and HEAD, producing the
authoritative line quoted in §8:

```
3800 passed, 12 warnings in 619.11s (0:10:19)
FULLSUITE_EXIT=0
```

## 10. Owning gates for the touched surfaces

| Surface | Owning certification slice | Re-run here |
|---|---|---|
| `src/hermes/research/contradictions.py` | N1 contradiction semantics / N9 retraction fencing | full suite (incl. N1/N9 fixtures) + `scripts/replay_diff.py` + `tests/test_replay_diff.py` — green |
| `src/hermes/research/controller.py` | tick-loop / lease fence | full suite (incl. `tests/test_wiring_w4.py: 21`) — green |
| five census-swept `src/` modules | P6 / DG-5 census discipline | `scripts/check_census.py` 8/8 + `tests/test_census_anchor.py` 3 — green |

No architectural invariant was weakened: the detector change is confined to **pair
selection order** and **diagnostics reporting** under an existing cap; the census change
is confined to **anchor grammar** in identifier regexes. Neither touches `apply_intent`,
the journal's append-only property, lease fencing, content-hash identity, or the
internal-only/LLM-proposable intent split.

## 11. Disposition

**PASS** (verdict and independent re-proofs: `docs/MERGE-AUDIT-DETECT.md`).

- Integration tip `50c3fdc0d54e7051ff968f5f50bcdc518cbf99cb` on `merge/detect`,
  **local-only**.
- **STOPPED BEFORE PUSH.** D9 has lapsed; no push, no force-push, no remote write, no
  tag, no PR. `refs/heads/merge/detect` does not exist on `origin`.
- Local `main` verified unmoved at `ac1860a5b3500bcc970833e426120af4233b49af`;
  `origin/main` verified unmoved at `e4b276db7880cb8c0e17e1239e03c589138541ae`
  (read-only probe). The platform line was never touched.
- Audit dispositions: **det-express (A) → PROVEN-CLOSED**; **claim-ground (C) →
  out of scope for this integration** (subject code absent at the merged tip;
  remediation lives on `fix/experiment-gate-doc-v2` @ `05c3217`, not on `main`, not
  integrated here); **doc-drift2 (B) → CARRIED OPEN**, unchanged by this integration.
  Evidence for each is in `docs/MERGE-AUDIT-DETECT.md` §5.
