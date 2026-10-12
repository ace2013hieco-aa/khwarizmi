# MERGE-LOG-USERINFO — land the userinfo stack onto main (LOCAL-ONLY, NO PUSH)

**Task ID:** MERGE-USERINFO
**Role:** Merge integrator — advance, verify, audit.
**Date (UTC):** 2026-10-10
**Repo:** D:\New folder\research-agent (GitHub ace2013hieco-aa/khwarizmi-research)
**Branch:** `merge/userinfo` (off `main`, local-only)
**Worktree (isolated):** D:\New folder\merge-userinfo-wt
**STOP:** stopped before push — no push performed, none attempted.

## 1. Inputs (verified, not assumed)

- `main` tip recorded before branching: `d10687499864db6fa85d282cbe19ebe4beb5eb37`
  (`docs(doc-drift2-micro): mark the AR-03 empty-result artifact dormant/unwired`).
  Local `main` carries unpushed platform commits — never touched (branch created
  via `git branch merge/userinfo main`; no checkout of, no commit on, `main`).
- 3-commit stack, topology verified linear (each commit single-parent, chained):
  - `5b7a4a5a81a29eaa70cf16f6e500e94fef54bcab` — `security(live-fetch): refuse
    userinfo/port URL forms in the egress gate (FIX-USERINFO)` (parent `d106874`)
  - `eecf6c1a6a96764867aa20153b80477d9c091623` — `fix(pin-port): fold an explicit
    default https port into the pin key (FIX-PIN-PORT)` (parent `5b7a4a5`)
  - `238d6e217cc529b6b3389740e55182c29af1a11c` — `security(live-fetch): refuse
    the full resolver exception family typed; correct the userinfo narrative
    (AUDIT-USERINFO SF-2/SF-3)` (parent `eecf6c1`)
  - `git merge-base --is-ancestor main 238d6e2` → YES (fast-forward valid).
- Audit input: `AUDIT-USERINFO-REDTEAM.md` at `cdffe25` (branch
  `audit/userinfo-bypass`, target `d106874...5b7a4a5`) — verdict **PASS**,
  0 MUST-FIX, 3 SHOULD-FIX (SF-1 pin misses `:443`; SF-2 resolver-error
  narrowing; SF-3 overstated userinfo narrative). Closures land as
  SF-1 → `eecf6c1`, SF-2/SF-3 → `238d6e2`.

## 2. Advance (clean fast-forward, hashes preserved)

```
git branch merge/userinfo main
git worktree add "D:\New folder\merge-userinfo-wt" merge/userinfo   # HEAD d106874, clean
git merge --ff-only 238d6e2
# Updating d106874..238d6e2 — Fast-forward, 5 files, +542/-44
```

Post-advance `git log --oneline`: `238d6e2 > eecf6c1 > 5b7a4a5 > d106874
(main)`. No `--no-ff` needed (topology did not force it); no hashes altered;
no `src/` changes made on the merge branch (advance only; docs added in §4).

Stack file footprint (`git diff --stat main..238d6e2`):

```
src/hermes/research/live_fetch.py  |  98 ++++++---
src/hermes/security/egress.py      |  13 +-
src/hermes/tools/providers/http.py |  45 ++++-
tests/test_fix_userinfo.py         | 394 +++++++++++++++++++++++++++++ (new)
tests/test_p_auto_3_live_fetch.py  |  36 +++-
```

## 3. Gates at merged tip `238d6e2` (isolated worktree, `PYTHONPATH=<worktree>/src`)

| Gate | Command | Result |
|---|---|---|
| Full suite | `python -m pytest tests -q` (project venv 3.14.1) | **exit 0 — 4365 passed, 0 failed, 0 errors, 0 skipped** (JUnit XML count; the 16 rows skipped in the author's offline env ran here — network available — and passed: 4349+16=4365) |
| Targeted battery | `pytest tests/test_fix_userinfo.py tests/test_p_auto_3_live_fetch.py tests/test_p_auto_4_caps.py tests/test_p_auto_4_fix.py` | **113 passed** (matches `238d6e2` record) |
| Lint | `ruff check src tests` | **All checks passed, exit 0** |
| Types (src) | `pyright --pythonpath <abs venv python> src` | **0 errors, 0 warnings, exit 0** |
| Types (tests) | `pyright --pythonpath <abs venv python> --project pyrightconfig.tests.json` | **0 errors, 1 warning, exit 0** — warning is pre-existing and off-stack (`tests/test_research_program.py:144` `reportSelfClsParameterName`) |

Note: `scripts/run_tests.py` was not used — it requires a worktree-local
`.venv` (absent here); `python -m pytest` with the project venv + worktree
`PYTHONPATH` is the equivalent hermetic invocation. All probes offline
(injected resolvers, no real egress); the suite's own `live_fetch`-marked
tests made real keyless egress by design (as in the stack's own records).

## 4. Count lineage (tests/test_fix_userinfo.py rows → suite totals)

- `5b7a4a5`: new file 33 rows → suite 4357 (4341 passed, 16 skipped).
- `eecf6c1`: +2 `:443`/`:0443` rows → suite 4359 (4343 passed, 16 skipped).
- `238d6e2`: battery 35 → 41 rows (+6) → suite 4365 (4349 passed, 16 skipped).
- Merged tip (this log): **4365 passed, 0 skipped** — same 4365 total; delta
  is environmental (network present, conditional skips executed), not a code delta.

## 5. SF-1/2/3 closure re-proofs (summaries; full pastes in MERGE-AUDIT-USERINFO.md)

- **SF-1 (pin covers `:443`)** — `src/hermes/tools/providers/http.py:242`
  (`_pin_key`), fold logic `:268-272`. Re-derived: `:443`/`:0443` vet OK and
  pin-table HIT under urllib's `Request.host` spelling; `:8443` refused
  `ORIGIN_NOT_ALLOWLISTED`. CLOSED.
- **SF-2 (resolver family typed)** — `src/hermes/security/egress.py:250-266`
  (`except Exception` → `EgressRefused DNS_FAILURE`). Re-derived: OSError,
  ValueError, RuntimeError, KeyError, TypeError + custom class → all typed
  `DNS_FAILURE`, zero bare escapes. CLOSED.
- **SF-3 (narrative corrected)** — `src/hermes/research/live_fetch.py:22-33`,
  `:98-117`; `src/hermes/tools/providers/http.py:246-255`. Re-derived: the
  `InvalidURL`/never-dialed + LIVE-row-is-non-default-port wording is present
  in both files. CLOSED.
- Bypass baseline re-confirmed: userinfo forms refused `CREDENTIALS_IN_URL`
  before any resolution.

## 6. Verdict

**PASS — merge `merge/userinfo` = `238d6e2` via clean fast-forward; all gates
green; all three SF closures re-derived at the merged tip. STOPPED BEFORE
PUSH as instructed (no push performed, none attempted).**
