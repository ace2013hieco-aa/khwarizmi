# MERGE-LOG-CFIX3 — vault `_rejects` key fix onto `main` (FF, LOCAL-ONLY)

Merge integrator record for C-FIX-3 (`fix/vault-rejects-key@328c003`).
**Outcome: clean fast-forward, full gates green. `main` NOT advanced,
NOT pushed — D9 lapsed; merge + verification only. STOPPED BEFORE PUSH.**

## Inputs

| Input | Value |
| --- | --- |
| Repository | `D:\New folder\research-agent` (`ace2013hieco-aa/khwarizmi-research`) |
| Worktree | `D:\New folder\merge-cfix3-wt` (isolated, branch `merge/cfix3`) |
| `main` local | `f7bed1ba0115e003c302be7c83eaec46114c4617` |
| `main` remote (`git ls-remote origin refs/heads/main`) | `f7bed1ba0115e003c302be7c83eaec46114c4617 refs/heads/main` — unmoved |
| Fix tip | `328c003bcb64bc87ca84de21f66a6b14297fcbec` (`fix/vault-rejects-key`) |
| Fix scope | 2 files: `src/hermes/vault/projection.py` +15/−4, `tests/test_vault_rejects_key.py` +141/−0 |
| Human approval | none — **D9 lapsed; no push under any circumstance** |

Topology (verified, not assumed):
`git merge-base main fix/vault-rejects-key` = `f7bed1b` (== `main` tip),
so the fix descends directly from `main`; clean FF expected and taken.

## Merge hashes

| Ref | Hash |
| --- | --- |
| `merge/cfix3` created off | `f7bed1b` via `git worktree add -b merge/cfix3 <wt> main` |
| FF advance | `f7bed1b..328c003` (`git merge --ff-only 328c003`) — zero conflicts |
| `merge/cfix3` post-FF | `328c003` (identical hash — no `--no-ff`, no rewrite) |
| This log commit | (single commit, one file — hash recorded at commit time) |
| `main` old → new | `f7bed1b` → **unchanged** |

Diffstat `main..328c003` (`git diff main HEAD --numstat`):
`15/4 src/hermes/vault/projection.py`, `141/0 tests/test_vault_rejects_key.py`
= 156 insertions, 4 deletions, 2 files. No `src/` changes on the merge
branch beyond the fast-forwarded fix commit itself.

## Key-semantics statement (C-F-02 resolution)

`_rejects` (`src/hermes/vault/projection.py:392-404`) now honors both
production keys against the shared refusing set
(`_NON_ACCEPTING_VERDICTS`, `:106-108`, 7 values: REJECTED/REJECT/
DENIED/REFUSED/FAILED/VETOED/REVOKED):

- `decision` — live on `HumanDecisionReceived` (4 writers,
  `src/hermes/research/controller.py:2186` CURATE_KNOWLEDGE, `:2335`
  RETRACT_SOURCE, `:2550` CONTRADICTION_RESOLUTION, `:2692`
  RECORD_CLASSIFICATION); never `verdict`.
- `verdict` — live on `HumanGateResolved` (1 writer,
  `src/hermes/research/controller.py:1923`, APPROVED/REJECTED).

Both keys are live with the **same** refusing semantics (same set, same
strip+upper normalization; `gateway.py:1129` confirms `decision` also
carries APPROVED/REJECTED elsewhere) — no conflicting semantics, no
STOP trigger. `verdict` kept because a shipped writer emits it.
No authority change: `AUTHORITATIVE_EVENT_TYPES` (5 types) untouched;
`_is_authoritative` (`:399-402`) logic unchanged apart from the key fix.
NOT-topics (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`)
untouched — none encountered.

## Fix audit-equivalent (red→green, director-verified on fix branch)

On `fix/vault-rejects-key` (same `328c003` content now on `merge/cfix3`):
BEFORE (fix stashed): `tests/test_vault_rejects_key.py` → **1 failed,
2 passed** (`_rejects({"decision": "REJECTED"})` returned `False`,
refusing decision slipped the filter).
AFTER (fix restored): same file → **3 passed** (refusing decision
excluded as `authoritative: false`; accepting `RETRACT_SOURCE` stays
`authoritative: true`; gate `verdict: REJECTED` still excluded).

## Gates on `merge/cfix3` (absolute paths, `PYTHONPATH=<worktree>/src`)

- Full suite: `2696` tests, `0` failures, `0` errors, `0` skipped
  (`EXIT:0`; JUnit `tests=2696 failures=0 errors=0 skipped=0`; collect
  `TOTAL:2696`; `PYTHONPATH=D:\New folder\merge-cfix3-wt\src`,
  `D:\New folder\research-agent\.venv\Scripts\python.exe -m pytest`).
- Ruff: `All checks passed!`
  (`python -m ruff check src tests`).
- Pyright src: `0 errors, 0 warnings, 0 informations`
  (`python -m pyright --pythonpath <abs-venv-python> src`).
- Pyright tests: `0 errors, 1 warning, 0 informations` — the single
  warning is pre-existing and unrelated
  (`tests/test_research_program.py:144:23` missing-`self`; file
  untouched by this fix).

## Conflicts — none

Fast-forward only; no merge commit, no manual hunks, no markers.
`git status` clean post-FF; this log is the sole additional commit
(docs-only, one file, no behavior change).
