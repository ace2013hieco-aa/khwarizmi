# MERGE-AUDIT-CLAIM-ADDENDUM — regen closure re-verification of `merge/claim`

**Addendum to** `docs/MERGE-AUDIT-CLAIM.md` (the `3faabf27` audit, verdict **FAIL — conditionally**,
single failing gate: full suite, 9 `tests/test_b4_ref_graphs.py` reds inherited from line tip
`05c3217`). This document supersedes nothing; it records the remediation merge
(`fix/gate-doc-regen@0a8b7ae`) and re-runs every gate at the advanced tip. Counts and
`file:line` throughout. All commands run in the isolated worktree `D:/New folder/merge-claim-wt`;
**local-only, no pushes, `main` untouched**.

## Verdict

**PASS — all gates green.** The advance to `0a8b7ae` landed as merge commit `386d2eb`
(`--no-ff`, forced — topology below), B4 is **24/24 green** (was the identical 9 reds),
and the full suite — the one gate the prior audit failed and the one proof it could not
produce — is **exit 0: 3810 passed, 16 skipped** (junit `tests="3826" errors="0"
failures="0" skipped="16"`, `time=489.447s`). Count lineage is exact end-to-end
(§4). Per the task's STOP conditions: **STOP BEFORE PUSH** (D9 lapsed; §7).

## 1. Inputs receipt (verified, no STOP)

| Input | Value | Verification |
|---|---|---|
| BASE local `main` | `ac1860a5b3500bcc970833e426120af4233b49af` | rev-parse before == after (§6); platform line `a8f0180..ac1860a` (5 commits) never touched |
| `main` on remote | `e4b276db7880cb8c0e17e1239e03c589138541ae` | read-only `git ls-remote`; ancestor of local (local is ahead — unpushed platform commits, untouched) |
| `merge/claim` on entry | `88e37bbd5cde0def2abf62a23824cf75a228dc21` | == `3faabf27` + 2 docs commits (`6407db2` log, `88e37bb` audit); docs-only — `git diff --exit-code 3faabf2 88e37bb -- src tests` → identical |
| Fix line `fix/gate-doc-regen` | `0a8b7ae81d59e5de11fbf14905fea3eecc2143fe` | 3 fixture renames + `docs/gr3-b4/b4-fixtures/README.md` (+16/−6), **no `src/`**; parent `05c3217` |
| merge-base(`88e37bb`, `0a8b7ae`) | `05c3217fc6e7338777336cb25d5efd0e314501c5` | the fix line is a sibling off the gate-doc tip already inside `merge/claim` via merge `3faabf2` |
| `merge/claim` on remote | **absent** | `git ls-remote origin refs/heads/main "refs/heads/merge/claim*"` → only `main`; never pushed |

Forbidden-topic scan (`backtest_audit|SDA|TSE|Optimize-my-strategy`) over the fix delta
`05c3217..0a8b7ae`: **0 hits**. Nothing to stop/report.

## 2. Topology — linear advance impossible, `--no-ff` forced (charter fallback clause)

The task expected a linear advance to `0a8b7ae`. That is not reachable: `merge/claim`
carries 9 commits beyond `05c3217` (merges `14bbf90`, `3faabf2` + docs `6407db2`, `88e37bb`
+ their first-parent line), while the fix line is a single commit on `05c3217`:

```
git merge-base --is-ancestor 0a8b7ae 88e37bb  → exit 1 (NOT an ancestor)
git merge-base --is-ancestor 88e37bb 0a8b7ae  → exit 1 (NOT an ancestor)
git rev-list --count 88e37bb..0a8b7ae         → 1
git rev-list --count 0a8b7ae..88e37bb         → 9
```

Both `git reset --hard` (would delete the prior round's log + audit) and rebase (would
rewrite the hashes the prior docs cite by name) were rejected. Chosen, per the charter's
explicit fallback — *"--no-ff merge preserving hashes only if forced"*:

`git merge --no-ff 0a8b7ae` → **`386d2eb0c1226e606dee8051132bb7b3168a8dd4`** ("Merge made
by the 'ort' strategy", zero conflicts; `git rev-list --parents -n 1 386d2eb` →
`386d2eb0… 88e37bbd… 0a8b7ae8…`). Both input tips and every referenced hash survive
verbatim. Documented deviation, not a STOP condition.

## 3. Patch-exactness — PASS (blob identity vs `0a8b7ae`)

Advance delta `88e37bb..386d2eb`: exactly **4 paths**, all under `docs/gr3-b4/b4-fixtures/`
(3 content-addressed JSON renames + `README.md`, +16/−6), **0 `src/` files**. All 6 files of
the fixture tree at `386d2eb` are blob-identical to the fix tip `0a8b7ae`
(`git rev-parse <tip>:<path>`): `.gitattributes 4b3dd118`, `0ee743f9…json c9a8c794`,
`3efc5422…json 043a1b02`, `4feda75b…json 541f9d61`, `eef41946…json 2e6becde`
(unchanged, IDR-only stratum), `README.md 9bacfdc6`.

Zero merge-authored edits: `git diff --exit-code 88e37bb 386d2eb -- src tests` → identical;
with `git diff --exit-code 3faabf2 88e37bb -- src tests` (prior docs commits, identical),
the `src`+`tests` tree at `386d2eb` is byte-identical to `3faabf2` — the tree the prior
audit already certified patch-exact against line tip `05c3217` (`docs/MERGE-AUDIT-CLAIM.md`
§1). The integrator introduced nothing absent from a parent.

## 4. B4 regen closure + count lineage — PASS (exact)

**B4 red → green (single-module runs, same venv, `PYTHONPATH=<worktree>/src`):**

| Tip | `tests/test_b4_ref_graphs.py` junit | Raw |
|---|---|---|
| `88e37bb` (before) | `tests="24" failures="9" errors="0"` | exit 1 — `9 failed, 15 passed in 3.78s` |
| `386d2eb` (after) | `tests="24" failures="0" errors="0" skipped="0"` | exit 0 — **`24 passed in 3.62s`** |

The 9 before-reds are the identical test IDs the prior audit recorded
(`docs/MERGE-LOG-CLAIM.md` §"B4 failure attribution", lines 90-100). Mechanism: `0a8b7ae`
renames the three stale content-addressed fixtures to the digests the current corpus
yields (`ffbdf93c… → 0ee743f9…`, `8d2c74fa… → 3efc5422…`, `4bc5dc28… → 4feda75b…`),
naming them in the README table (`docs/gr3-b4/b4-fixtures/README.md:33-36`) with the
regen record at `:47-53`. Root cause confirmed: the B4 sweep reads the two governed docs
the gate-doc commit `05c3217` edited (`docs/ARCHITECTURE.md` +7, `docs/STATE.md` +13;
sweep sources at `tests/test_b4_ref_graphs.py:61-65`), which moved their bytes and the
fixtures' content-address — the exact remediation the prior audit assigned to the line
owner (`docs/MERGE-AUDIT-CLAIM.md:118-119`), now delivered and closed.

**Count lineage (collected): 3783 (base `main@ac1860a`) → 3826 (`3faabf2`) → 3826
(`386d2eb`) → 3826 (final tip).** The +43 at the first hop is the prior audit's exact
lineage (26 `test_claim_ground` + 16 `test_experiment_gate_pin_v2` + 1 `test_claims`;
`docs/MERGE-AUDIT-CLAIM.md` §4). The advance adds/removes no tests (fixture renames
only), so 3826 holds. Reconciled outcomes:

| Tip | passed | failed | skipped |
|---|---|---|---|
| `3faabf2` (prior round) | 3801 | **9** (B4) | 16 |
| `386d2eb` (this round) | **3810** | **0** | 16 |

+9 = exactly the 9 B4 reds turning green; no other test moved.

## 5. Raw gates (at `386d2eb`, worktree venv Python 3.14.1)

| Gate | Raw output | Exit |
|---|---|---|
| `uvx ruff check src tests` | `All checks passed!` | 0 |
| `uvx pyright --pythonpath "D:/New folder/merge-claim-wt/.venv/Scripts/python.exe" src` | `0 errors, 0 warnings, 0 informations` | 0 |
| `uvx pyright --pythonpath "D:/New folder/merge-claim-wt/.venv/Scripts/python.exe" --project pyrightconfig.tests.json` | `0 errors, 1 warning, 0 informations` | 0 |
| `PYTHONPATH="D:/New folder/merge-claim-wt/src" .venv/Scripts/python.exe scripts/run_tests.py -v` | **`3810 passed, 16 skipped in 489.52s (0:08:09)`** — junit `tests="3826" errors="0" failures="0" skipped="16"` | **0** |

The pyright-tests warning (`tests/test_research_program.py:144:23
reportSelfClsParameterName`) is pre-existing at base `main@ac1860a` and outside this
line's edits (prior audit §5, `docs/MERGE-AUDIT-CLAIM.md:97-100`). Reported, untouched —
not a red gate (exit 0, warnings ≠ errors).

**Full-suite exit 0 with count — the proof missing from the prior round — is delivered.**

## 6. Constraint compliance

| Constraint | Status |
|---|---|
| No `src/` changes | **Held** — advance delta 4 paths, 0 `src/`; `git diff --exit-code 88e37bb 386d2eb -- src tests` identical (§3) |
| Platform line never touched | **Held** — `main` at `ac1860a5b3500bcc970833e426120af4233b49af` before and after (rev-parse pasted in the charter report); remote `main e4b276d` read-only, an ancestor of local |
| Isolated worktree | **Held** — all work in `D:/New folder/merge-claim-wt`; `git status --porcelain` clean apart from this file's commit |
| Absolute `--pythonpath` + `PYTHONPATH=<worktree>/src` | **Held** — used for every gate and both B4 runs |
| Local-only, no push | **Held** — no push command issued; `merge/claim` absent on remote; this addendum commit is the **final tip** and exists only in the local object store |
| Forbidden topics | **Clear** — 0 hits in `05c3217..0a8b7ae` (§1) |
| Commit discipline | **Held** — advance = 1 merge commit; addendum = 1 commit, 1 file (this document); no mixing |

**Disclosure (pre-existing, deliberately untouched):** during the merge, git printed
`error: failed to delete 'D:/New folder/research-agent/.git/worktrees/step-4': Permission
denied` — the same stale worktree-admin noise the prior round recorded
(`docs/MERGE-LOG-CLAIM.md:37-39`). The merge landed correctly (`386d2eb`, both parents,
clean status); the stale directory was left in place for its owner.

## 7. Final verdict

**PASS.** Faithful `--no-ff` advance to `0a8b7ae` (hashes preserved), patch-exact, B4
closure delivered and re-proven red→green, count lineage exact at 3826, all four gates
green with the full suite **exit 0: 3810 passed, 16 skipped**. The blocking condition of
`docs/MERGE-AUDIT-CLAIM.md` is closed; nothing is carried forward. Per the task's STOP
conditions and lapsed D9: **STOP BEFORE PUSH.** The final tip (`386d2eb` + this addendum
commit) is local-only; pushing is a fresh decision for the operator, not this charter.
