# MERGE-LOG-TAMPER-2 — per-event journal hash chain, migration v23, re-chain tool (GAP-1 D1)

## Provenance

| Item | Value |
| --- | --- |
| Task | TAMPER-2 (GAP-1 D1; chartered-deferred after TAMPER-1, **not dropped**) |
| Base (`main` before) | `4eab1b5` (pushed `8929fc4` + the wave-3a rulings docs commit) |
| Slice | `slice/tamper-2@c110f94` — created at the base, so **no restack was needed**; landed by fast-forward with its own re-stamps intact |
| Landed tip (FF'd to) | `c110f94fe8c43b53fcc00728cf549f61fbe68448` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — awaiting the human's D9 pin for the new tip |

Design-note commits (reviewed before implementation): `e8890fd` (decisions
A1–A8) and `5d033b1` (the re-chain transaction hook + idempotency fix).

## Scope

```
src/hermes/persistence/journal_chain.py      | 333 ++  (new: chain, verify, re-chain)
src/hermes/persistence/migrations.py         |  80 +-  (22 -> 23, start_version hook)
src/hermes/persistence/repositories.py       |  65 +-  (writer chains every append)
src/hermes/cli.py                            | 167 +-  (journal verify / rechain)
scripts/replay_diff.py                       |  22 +-  (derived-digest strip)
tests/test_tamper_2_journal_chain.py         | 639 ++  (46 pins)
tests/journal_tamper.py                      |   9 +   (docstring only)
tests/* (9 files)                            |  57 +-  (version bumps, v3/v4 seeding, pins)
docs/idr/TAMPER-EVIDENT-JOURNAL.md           | 382 ++  (TAMPER-2 addendum A1-A8)
docs/SUITE-COUNT.md                          |  +6 -6  (5018)
```

19 files, +1725 / −45. No governed document touched; B4 stays 24.

## What was certified

- **The chain (§1.4 / A1).** `chain_row` hashes the 11 stored fields verbatim
  (`NULL` → JSON `null`) as `h(n) = sha256(h(n-1) + "\n" + canonical_json)`
  with `GENESIS = sha256("hermes.journal.chain.v1/genesis")`. It reproduces the
  frozen fixture digests (M1/M2/M11) **and** agrees with the reference prover on
  every `tamper_cases.json` mutant (M3–M8), so the `src/` implementation and the
  prover artifact cannot drift apart.
- **Verification (§1.5 / A7.3).** The closed code set, first-defect-wins,
  `CHAIN_UNENCODABLE_ROW` failing closed rather than skipping. `verify_journal`
  checks the refusal layer first: `CHAIN_TRIGGERS_MISSING` outranks any row
  defect, because a missing trigger is a precondition, not a row finding.
- **Migration 22 → 23 (A7.1).** The mandatory order — drop both triggers →
  add both nullable columns → backfill in `event_id` order → recreate both
  triggers **last**. The drop is load-bearing: the backfill is an
  `UPDATE events`, which the shipped triggers abort. `created_at` is
  byte-identical; no table rebuild; no `SELECT *`. The body is **idempotent**
  and is re-executed by the re-chain tool.
- **Writer (A7.2).** `event_id` is reserved from the `sqlite_sequence`
  high-water mark, the tip is read, and both digests are computed and inserted
  **inside the caller's transaction**. The tip is the highest `event_id`
  carrying a non-NULL `chain_hash` (or `GENESIS`), so a raw fixture insert that
  left NULLs is skipped over rather than chained onto, and still reports
  `CHAIN_UNCHAINED_ROW`.
- **Re-chain (A7.4/A7.5).** `rechain_journal` asserts an open transaction and
  issues no control statement of its own; the owner is the migration runner via
  `migrate_to_latest(conn, start_version=22)`. The CLI refuses without
  `--confirm-rechain`, refuses a database below `SUPPORTED_VERSION`, and with
  `--anchor` refuses when the current tip already diverged — leaving the file
  untouched. Both the docstring and the CLI say it plainly: **a re-chain
  blesses the current bytes.**
- **All 24 tamper sites preserved.** `tests/journal_tamper.py` is docstring-only
  (+9/−0); every site still proves refusal-then-forcing, and now also leaves a
  `CHAIN_HASH_MISMATCH` behind. No production read path verifies the chain, so
  no consumer test started failing for a new reason.

## Director review findings (both fixed before landing)

| Finding | Where caught | Fix |
| --- | --- | --- |
| The design's re-chain rode `migrate_to_latest(conn, start_version=22)` — **that parameter did not exist**, and on a v23 database the runner opens no transaction at all, so the census-neutral posture was unimplementable | design-note review, against the live signature at `migrations.py:1343` | `5d033b1`: the parameter is specified explicitly, its census neutrality argued (no new `BEGIN`/`COMMIT`/`ROLLBACK`), plus migration idempotency pinned |
| `hermes journal verify` on a pre-v23 database raised a raw `sqlite3.OperationalError` (`no such column: prev_hash`) instead of refusing | implementation review | `3234b4a`: version guard with a clean refusal, exit 1, file untouched, plus a pin |

## Census

**Unchanged: 124 transaction-control calls / 28 owners (19 persistence, 5
gateway, 4 Controller) / 1 rollback-only / 15 imports.** The re-chain adds no
owner and no control statement.

One honest note the count alone does not show: `journal_chain.py` is a **new
persistence module consuming `hermes.research.programs`**. The 15-statement
figure is preserved because the slice folded a redundant *function-local*
import of that same module (`program_to_dict` in
`ResearchProgramRepository.record`) into the module-level import — the
dependency **edge set** gains a file, the statement count does not change.
Re-certifying to 16 was rejected as the alternative: it needs governed-doc
edits and a B4 regeneration to record a number that no longer tracks edges.

## Gates (raw, at landed tip `c110f94`)

| Gate | Result |
| --- | --- |
| Full suite | **5010 passed / 3 skipped / 5 failed** in 747.53s (collected 5018) |
| `stamp_suite_count.py --check` | `OK: docs\SUITE-COUNT.md collected=5018 matches the live collect` |
| `check_census.py` | **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0 outside |
| B4 ref graphs | **24 passed** |
| `ruff check src tests scripts` | `All checks passed!` |
| `pyright src` | **0 errors, 0 warnings, 0 informations** |
| `pyright --project pyrightconfig.tests.json` | **0 errors, 1 warning** (known `test_research_program.py:144`) |
| NOT-list (`4eab1b5..HEAD`) | **0 hits** |
| Migration chain | **v23** |

The five failures are the host-level set documented in `MERGE-LOG-WAVE-3A.md`
(concurrent `BEGIN IMMEDIATE` → `SQLITE_READONLY`; silently-dropped symlinks),
reproduced at the pushed baseline `5e470fa`. **Nothing outside that set failed.**

## Intended deltas (W4)

1. **Schema v23** — two nullable columns on `events`, backfilled.
2. **`hermes audit --json`** now emits `prev_hash`/`chain_hash`: its contract is
   "exactly the events-table columns", so the keys moved with the table.
3. **The writer** inserts `event_id` explicitly and both digests.
4. **A pre-v23 database cannot be appended to by the v23 writer** — it would
   need columns that do not exist. Production migrates first; a stale database
   now fails closed with a SQL error instead of writing an unchained row.
5. **`scripts/replay_diff.py`** strips the two digests as *derived* values: they
   are functions of `correlation_id`, which is already stripped, so comparing
   them verbatim would report a false diff. `PROVENANCE_STRIP` itself is
   untouched and its load-bearing test still passes.
6. **CLI emit census** 95 → 116 (the new surface, itemised in place).

## Residuals (reported, not fixed)

1. **DB-file swap and tail truncation** remain undetectable without an
   out-of-band `--anchor`. This slice ships no sidecar anchor file, no
   signature, no MAC and no key material; an anchor store is **P2-4**.
2. **`DROP TRIGGER`** is detected as *absence* only — a trigger dropped, used
   and recreated identically is invisible.
3. **`created_at`** is outside the preimage by design (§1.1).
4. **A full re-chain by an actor with DDL rights** produces a valid chain; only
   an anchor detects it.
5. The five host-level suite failures persist (environment, not code).

## Prohibited-claims discipline

A green chain is a mechanically true statement about the bytes in one file.
It is **not** authority, **not** scientific validity, **not** reproducibility,
and **not** authorship. Replay/verification proves byte and derivation
determinism only. The re-chain is a deliberate act on a known-good journal and
never a repair.

License: Apache-2.0 (LICENSE).
