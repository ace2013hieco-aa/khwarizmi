# MERGE-LOG-WAVE-3A — D8-HYGIENE, UNWRAP-AUDIT, WIRE-6, PROVIDER-1 landed serially (GAP-1 wave 3a)

## Provenance

| Item | Value |
| --- | --- |
| Wave | GAP-1 wave 3a — four slices, landed serially on local `main` |
| Base (`main` before) | `332614ca2b8093369e8e590a0facd63a380dc536` (pushed tip `5e470fa` + the docs-only rulings record) |
| Method | restack (cherry-pick, slice re-stamps dropped) → fresh restamp per landing → `git merge --ff-only` → merge log on top. No rebase, no merge commit, no force. |
| Final tip (this log) | this commit (the wave-3a tip; the D9 pin request carries the full hash and tree) |
| Push | **drafted, NOT executed** — awaiting the human's explicit "Pin both exact hashes" |

## Landings

| # | Slice | Slice tip | Restacked tip | Merge-log commit |
| --- | --- | --- | --- | --- |
| 1 | D8-HYGIENE (D8-A) | `2c209f7` | `41d1117` | `3193e23` |
| 2 | UNWRAP-AUDIT (P2-5) | `cd79bfb` | `5def094` | `afad218` |
| 3 | WIRE-6 (D6-A) | `af130be` | `3df7dc8` | `ec5af26` |
| 4 | PROVIDER-1 (P2-3 + P2-10) | `4b239da` | `29c8b8c` | `8bfaf6f` |

Each landing re-ran the slice's targeted battery, `stamp --check`, census, B4,
and ruff before the fast-forward. Suite count chain: 4929 → 4940 → 4945 → 4972.

## Verdicts and evidence

- **D8-HYGIENE — LAND.** Live-surface path scrub (4 absolute paths), 11-PDF
  provenance table (8 exports Apache-2.0, 3 arXiv CC BY 4.0), minimal NOTICE
  trademark line (no registration claim), Apache-2.0 + DCO / no-CLA posture.
  Residual absolute paths: 85 files, all dated prose records; **zero** in
  `src/`, `tests/`, `scripts/`, `.github/`, or configs. No asset deleted.
- **UNWRAP-AUDIT — LAND.** 13 sites classified with file:line evidence, **0
  UNWRAPPED**, 4 documented accessors, 5 residual gaps reported. The single-seam
  claim is withdrawn rather than repaired. One accepted deviation from
  "docs + tests only": a **docstring-only** edit in `prompt_assembly.py`
  correcting the module's own false single-seam sentence; zero prompt bytes,
  zero fixtures, zero behaviour (pinned by `_text_reads(...) == []`).
- **WIRE-6 — LAND.** Zero `src` changes. AST-derived dispatch coverage; the
  uncovered remainder is exactly the six D6-A kinds; `NOT_WIRED` fallback
  pinned; coupling map pinned to the ruling; all director-only and
  internal-only kinds covered. Director probes: wiring `BRANCH` → 3 pins fail;
  weakening the fallback to `UNKNOWN_KIND` → 4 pins fail.
- **PROVIDER-1 — LAND.** `_load_shipped_spec` raises the hazard boundary's
  typed `SpecValidationError` (`SPEC_INVALID`) before any request; registry
  census pins 8 shipped / 7 refused of 15. Gateway-wide payload bound
  (depth 16 / 4096 containers / cycle refusal) applied before budget hooks and
  every validator, refusing `MALFORMED_PAYLOAD` with no write. The triage's
  eighth provider, `base`, is the adapter base module, not a provider id.

## Gates (raw, at the pre-log tip `8bfaf6f`, heavy-gate mutex held)

| Gate | Result |
| --- | --- |
| Full suite | **4964 passed / 3 skipped / 5 failed** in 673.98s (collected 4972) |
| `stamp_suite_count.py --check` | `OK: docs\SUITE-COUNT.md collected=4972 matches the live collect` |
| `check_census.py` | **PASS** — 124 calls / 28 owners (19/5/4) / 1 rollback-only / 15 imports / 0 outside |
| B4 ref graphs | **24 passed** |
| `ruff check src tests scripts` | `All checks passed!` |
| `pyright src` | **0 errors, 0 warnings, 0 informations** |
| `pyright --project pyrightconfig.tests.json` | **0 errors, 1 warning** (known: `tests/test_research_program.py:144`) |
| NOT-list (`5e470fa..HEAD`) | **0 hits** |
| Migration chain | **v22** — no migration touched |

## The five failures are environmental, not wave-3a

All five reproduce at the **pushed baseline `5e470fa`** in a clean detached
worktree, and outside the sandbox:

| Test | Failure |
| --- | --- |
| `test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed` | `BEGIN IMMEDIATE` → `attempt to write a readonly database` |
| `test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds` | same |
| `test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed` | same |
| `test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed` | same (second writer errors instead of being refused) |
| `test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory` | `symlink_to()` returns success but the link is absent (`lexists` false, `iterdir` empty), so the real-link branch never plants an alias and `_join_note` correctly does not refuse |

Both classes reproduce with **plain stdlib** on this host — five threads doing
`BEGIN IMMEDIATE` against one WAL database return `SQLITE_READONLY` for all but
one, and `Path.symlink_to` silently produces no directory entry. Neither
depends on repository code, the wave, or the WorkBuddy sandbox (the five also
fail with the sandbox disabled). The wave-2 certification of `0 failed` was
taken before this host behaviour appeared.

**Consequence:** the wave is green on its own 43 new tests and on every touched
surface; the host cannot currently produce a 0-failure full suite at any
commit, including the pushed one. The push decision is the human's.

## Intended deltas (W4)

1. **New refusals, pathological payloads only** — depth > 16 or > 4096
   containers now refuse `MALFORMED_PAYLOAD` pre-write. No admitted suite
   traffic is affected; the free-form `spec` values that were previously
   admitted are explicitly pinned as still admitted.
2. **Refusal-census count** — `MALFORMED_PAYLOAD 122 → 123`, total
   `267 → 268`, inline reason recorded; structure unchanged.
3. **Typed spec error** — a spec-less provider now raises `SpecValidationError`
   (a `PermanentProviderError`) instead of a bare `ValueError`; in-tree callers
   propagate it and the walk/fetch pins assert no I/O occurred.
4. **Module docstring** — `prompt_assembly`'s self-description corrected; no
   prompt byte changes.

## Residuals (reported, not fixed)

1. Host-level concurrent-WAL and symlink behaviour (above) — blocks a
   zero-failure gate on this machine; needs an environment fix or a ruling to
   quarantine the five tests, not a code change.
2. `docs/archive/**` and dated audit/merge records keep absolute developer
   paths by policy (evidence, not instructions).
3. D6 (`WIRE-6`) and D8 (`D8-HYGIENE`) status rows in `docs/GAP1-RULINGS.md`
   are updated **after** the push, in the next docs commit.
4. TAMPER-2 (D1) and AUDIT-TXN (D12) remain queued for wave 3b; P2-2 and P2-16
   remain unruled and are not touched.

## Prohibited-claims discipline

This wave certifies hygiene, a data-flow classification, a structural dispatch
pin, a fail-closed provider refusal, and a payload shape bound. It makes no
validity, reproducibility, or admissibility claim; the envelope remains an
accident barrier, the seven spec-less providers remain unsupported, and a
bounded payload is not a safe payload.

License: Apache-2.0 (LICENSE).
