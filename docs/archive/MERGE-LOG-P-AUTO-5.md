# MERGE-LOG-P-AUTO-5 — land P-AUTO-5 slice + holes fix (LOCAL-ONLY, NO PUSH)

## Lineage (linear, fast-forward — no merge commit, tips preserved)

- `main@9696d319384d019beea5facf931715c50aa753f6` (verified unmoved:
  local `rev-parse main` + `ls-remote origin refs/heads/main` identical
  pre-merge and re-checked post-merge)
- `slice/p-auto-5-vault@975655e66fd55590429bc0230c976919a34769a0`
  (deterministic journal-cursor projector; 3 files, +894/−4 —
  `src/hermes/vault/projection.py` +519, `src/hermes/vault/__init__.py` +2,
  `tests/test_p_auto_5_vault.py` +377)
- `fix/p-auto-5-holes@39de562a199c8d6a795423a3b6fb94e65861f2ce`
  (4 MUST-FIX closures; 2 files, +560/−72 — `projection.py` +235/−72,
  `tests/test_p_auto_5_fix.py` +325)
- `merge/p-auto-5` advanced `9696d31` → `39de562` by `git merge --ff-only`
  (`merge-base(main, fix) == 9696d31`; `--is-ancestor` TRUE for
  main→slice→fix; clean `Updating 9696d31..39de562 / Fast-forward`, exit 0;
  4 files changed, +1382/−4). This log commit adds 3 files only (2 carried
  audit docs, byte-identical by blob hash: redteam `c364048b…`, delta
  `017b8364…`, + this log). **No `src/` changes on the merge branch.
  STOPPED BEFORE PUSH per D9-lapsed instructions.**

## Gate counts (merge worktree, `PYTHONPATH=<worktree>/src`, tip `39de562`)

- Full suite: **2664 passed, 12 warnings in 557.64s** (0 failed, 0 skipped;
  exit 0)
- New on this lineage: **24** slice tests (`tests/test_p_auto_5_vault.py`) +
  **20** fix regression tests (`tests/test_p_auto_5_fix.py`) = **44**
  (two-file gate `44 passed in 0.75s`; each fix test red on `975655e`,
  green on `39de562`)
- `ruff check src tests`: **All checks passed!** (exit 0)
- `pyright src`: **0 errors, 0 warnings, 0 informations** (strict, exit 0)
- `pyright --project pyrightconfig.tests.json`: **0 errors, 1 warning**
  (pre-existing `tests/test_research_program.py:144`, exit 0)
- Audits carried: `AUDIT-P-AUTO-5-REDTEAM.md` (FAIL → 4 MUST-FIX B1/B2/C1/A2
  + 5 SHOULD-FIX) and `AUDIT-P-AUTO-5-DELTA.md` (PASS, 4/4 closures
  re-derived, hunts A–D clean, 0 MUST-FIX)

## Parked items (recorded, NOT implemented here)

- **B3 producer-side wiring** — align `SourceRetracted` payload/keys with
  admission subject keys (disjoint refs still leave `(True, True)`); declared
  producer-contract partial in the fix; wiring parked.
- **Manifest idea** — cursor-vs-`max(event_id)` sanity check / manifest so
  lost or backfilled ids are attributable (red-team NOTE G); parked.
- **X1** — gap warning is not project-scoped (false positives on interleaved
  multi-project journals); parked.
- **D2** — cursor restored ahead of the vault yields dangling stable-ID
  links; parked.
- **C3** — root path that exists as a file raises raw `FileExistsError`
  (not a `ProjectionRefused` code); parked.

## Residuals carried (from the delta audit, no new MUST-FIX)

- **N1** — verdict rule uses a closed refusing set: `DISMISSED` / non-string
  verdicts stay authoritative (synthetic; shipped gate verdicts are
  validated to APPROVED/REJECTED at `controller.py:1701`).
- **N2** — a cross-class `verdict` payload key would suppress authority on
  an authoritative row (no shipped producer does this).
- **N3** — `VICTIM_MISSING` is TOCTOU-only; `INVALIDATOR_MISSING` is only
  reachable via journal surgery; no refusal storm observed.
- **N4** — deleting the invalidator row restores stale authority; reproduced
  identically on unfixed `975655e` (pre-existing, journal surgery only).
- **N7** — real symlink repro blocked on this host (`WinError 1314`);
  hardlink equivalence + `ALIAS_ESCAPE` used; privileged-host methodology
  recorded, not executed.
