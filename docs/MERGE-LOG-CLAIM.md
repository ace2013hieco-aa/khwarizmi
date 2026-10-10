# MERGE-LOG-CLAIM — merge/claim (claim-ground + experiment-gate-doc-v2 integration)

**Branch:** `merge/claim`, from `main@ac1860a5b3500bcc970833e426120af4233b49af`; isolated worktree
`D:/New folder/merge-claim-wt`; **local-only, no pushes, `main` untouched** (verified unmoved at
`ac1860a` before and after all work).

**Inputs (verified):**

| Input | Tip | Verification |
|---|---|---|
| BASE local `main` | `ac1860a5b3500bcc970833e426120af4233b49af` | rev-parse before/after identical; carries unpushed platform commits `a8f0180..ac1860a` — never touched |
| Line 1 `fix/claim-ground` | `921f0c86c22a493700201e55ed54d4aa8fd3f1e5` | parent = `a8f0180` |
| Line 2 `fix/experiment-gate-doc-v2` | `05c3217fc6e7338777336cb25d5efd0e314501c5` | parent = `921f0c8` |

**Topology (verified linear pair):** `05c3217 → 921f0c8 → a8f0180`. `merge-base(main, 921f0c8) =
a8f018068e3c04b3160891ebd56cfd95d3590c95`; the claim-ground line diverged from `main` at `a8f0180`,
`main` then advanced `a8f0180..ac1860a` (platform commits; that range touches **no docs** —
`git log --oneline a8f0180..ac1860a -- docs/` is empty).

**Forbidden-topic scan:** `git log -p a8f0180..05c3217` searched for
`backtest_audit|SDA|TSE|Optimize-my-strategy` — **0 hits**. Nothing to stop/report.

## Merge hashes

| # | Merge commit | Parents | Line merged |
|---|---|---|---|
| 1 | `14bbf909a14a3c6361797184d2e8321a92097f1c` | `ac1860a` + `921f0c8` | `fix/claim-ground` — grounded admission G9–G13 |
| 2 (tip) | `3faabf274c1c6f12dd04046ab95b90f7bdcac2c6` | `14bbf90` + `05c3217` | `fix/experiment-gate-doc-v2` — finding C resolution (b) docs + pin |

Both merges `--no-ff` (ort strategy).

## Conflicts and resolutions

**None. Zero textual conflicts, zero semantic conflicts.** The only file contended between the
platform line and the claim-ground line is `src/hermes/research/controller.py`; git auto-merged it
and the result was proven an exact content union (see patch-exactness below). No STOP condition
triggered during integration. (git printed `error: failed to delete '.git/worktrees/step-4':
Permission denied` after the merges — stale worktree-admin cleanup noise from a prior session,
unrelated to merge content; both merge commits were created normally with both parents.)

## Changed files (`main` → tip): 23, all line-authored, zero merge-authored edits

- docs: `docs/ARCHITECTURE.md`, `docs/STATE.md`
- src (5): `persistence/migrations.py`, `persistence/repositories.py`, `research/claims.py`,
  `research/controller.py`, `research/extraction.py`
- tests (16): `test_claim_ground.py` (A), `test_experiment_gate_pin_v2.py` (A), and 14 modified
  (`test_c1_slot_ref`, `test_claims`, `test_claims_write_path`, `test_controller`,
  `test_controller_q02`, `test_database`, `test_extraction_pipeline`, `test_notes_dedup`,
  `test_p_auto_4_caps`, `test_p_auto_4_fix`, `test_q05_evidence_ladder`, `test_q05_persistence`,
  `test_research_program`, `test_thesis_ar03`)

## Patch-exactness (PASS)

All **23 files** of the line delta (`git diff --name-only a8f0180 05c3217`) are **blob-identical**
between line tip `05c3217` and merge tip `3faabf2` — verified per-file via `git rev-parse
<tip>:<path>` — with the single exception:

| File | Line-tip blob | Merge-tip blob | Why |
|---|---|---|---|
| `src/hermes/research/controller.py` | `63f5c15ce2322008b0d86629525846be20914330` | `14d55dae6936c924a31cbe85b70b85118e3036b9` | auto-merged union (see below) |

Controller union proof: content-normalized diff (stripping `index`/`@@` lines) of the merged blob
vs **each** parent is identical in both directions — merged = main W4 delta ∪ line delta exactly,
0 conflict markers. The merged blob is stable across both merge commits (`14bbf90` and `3faabf2`
both carry `14d55dae`). Key line blobs at tip == line tip: `claims.py 52579bac69bd`,
`migrations.py b30c1e898078`, `repositories.py ee0d12db9095`, `extraction.py c5153987e290`.

## Count lineage (exact)

Full-suite collection: **3783** (base `main@ac1860a`) → **3826** (tip) = **+43** =
26 (`tests/test_claim_ground.py`) + 16 (`tests/test_experiment_gate_pin_v2.py`) + 1
(`tests/test_claims.py`).

## Gate results (on the merged tree, tip `3faabf2`)

| Gate | Result |
|---|---|
| `uvx ruff check src tests` | **PASS — `All checks passed!`** |
| `uvx pyright --pythonpath <abs venv python> src` | **PASS — `0 errors, 0 warnings, 0 informations`** |
| `uvx pyright --pythonpath <abs venv python> --project pyrightconfig.tests.json` | **PASS (0 errors)** — 1 warning, pre-existing (below) |
| Full suite (`scripts/run_tests.py`) | **FAIL — 3826 tests, 0 errors, 9 failures, 16 skipped (junit `time=462.586s`)** |

Pyright-tests warning: `tests/test_research_program.py:144:23 reportSelfClsParameterName` — same
warning present at base `main@ac1860a`; the line's edits to that file touch only the 19→20
migration version assertions (~:861-896), not :144. Pre-existing, reported, untouched.

All 9 failures are `tests/test_b4_ref_graphs.py`, all `FileNotFoundError:
docs/gr3-b4/b4-fixtures/0ee743f9dcc3fcad0a409c11f881f3cb3cf34dca621a23832824bd415cc43f0b.json`:

```
FAILED tests/test_b4_ref_graphs.py::test_fixture_regeneration_reproduces_committed_bytes
FAILED tests/test_b4_ref_graphs.py::test_b4_strict_reader_round_trips_every_committed_fixture
FAILED tests/test_b4_ref_graphs.py::test_reader_refuses_digest_mismatch
FAILED tests/test_b4_ref_graphs.py::test_reader_refuses_unknown_keys
FAILED tests/test_b4_ref_graphs.py::test_reader_refuses_count_drift
FAILED tests/test_b4_ref_graphs.py::test_reader_refuses_non_governed_source
FAILED tests/test_b4_ref_graphs.py::test_reader_refuses_non_simulated_consumption
FAILED tests/test_b4_ref_graphs.py::test_reader_refuses_foreign_namespace
FAILED tests/test_b4_ref_graphs.py::test_reader_refuses_self_edge
```

## B4 failure attribution: inherited from line tip `05c3217`, not merge-induced

Ran `tests/test_b4_ref_graphs.py` alone at three commits (merge venv, each worktree's own `src` on
`PYTHONPATH`, cwd = each worktree):

| Commit | Result |
|---|---|
| `main@ac1860a` | **24 passed** (0 failures) |
| `921f0c8` (claim-ground tip; code-only) | **24 passed**, junit `failures="0"` |
| `05c3217` (gate-doc tip; worktree tracked-clean) | **9 failed / 15 passed**, junit `failures="9"` — **the identical 9 test IDs as the merge tip** |

Corroborating facts:

- `docs/gr3-b4/b4-fixtures/` tree is **byte-identical** (same blob ids: 4 content-addressed JSON +
  `README.md` + `.gitattributes`) at `05c3217` and at merge tip `3faabf2` — the merge introduced
  **zero** fixture change.
- `0ee743f9….json` is committed at **neither** tip.
- The B4 corpus regenerates content-addressed fixtures from live docs
  (`tests/test_b4_ref_graphs.py:61-65` sweeps `docs/ARCHITECTURE.md`, `docs/STATE.md`,
  `docs/API.md`, `docs/idr/IDR-024.md`, `docs/idr/IDR-028.md`).
- `05c3217` edited exactly those corpus sources: `docs/ARCHITECTURE.md` (+7) and `docs/STATE.md`
  (+13). Regeneration at `05c3217` therefore yields a new digest `0ee743f9…` that was never
  committed. The gate-doc line itself is red on the full suite.

**Root cause:** the gate-doc line was landed without re-running the B4 slice (or without
committing the regenerated fixture). The red pre-exists the merge; the merge reproduces it
verbatim, which is the correct integrator behavior.

**Remediation (line-owner scope, out of merge scope):** regenerate and commit
`docs/gr3-b4/b4-fixtures/` on the gate-doc line (or a follow-up commit), then re-merge or re-run
the suite at tip. A merge integrator must not introduce content absent from both parents, and the
task forbids changes beyond conflict repair.

## Verdict

Integration **PASS** (clean, topology-verified, patch-exact, zero authored edits); ruff + both
pyrights **PASS**; full suite **FAIL** with 9 failures **inherited verbatim from line tip
`05c3217`**. Per task STOP conditions: **STOP BEFORE PUSH.** See `docs/MERGE-AUDIT-CLAIM.md` for
the audit and final verdict.
