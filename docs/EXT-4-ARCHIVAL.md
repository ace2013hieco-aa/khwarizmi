# EXT-4 — additive cold archive for resolved/superseded rows (L1 / I4)

- **Slice:** `slice/ext-4-archival` (local-only, no push)
- **Base:** `main@b687b8bce5a0aaeb17cba1d9e17067de7414a7aa`
- **Triage input:** `audit/ext-1-triage@bc1a5da`, item **L1 — unbounded journal
  growth** (verdict VALID), with **I4 tiered archival** folded in as the same
  work.
- **Scope:** hardening only. This slice implements the archive valve; it does
  not size it (the capacity gate's job) and it does not change any certified
  surface.

## 1. Growth census (measured)

Measured with a synthetic harness that populates a migrated DB through direct
SQL — a measurement fixture, **not** a certified lifecycle run — and then
measures the surfaces the triage names.

| events | DB file (bytes) | gap-scan | full event scan |
| ---: | ---: | ---: | ---: |
| 5,000 | 5,079,040 | 4.6 ms | 14.4 ms |
| 20,000 | 13,107,200 | 18.1 ms | 74.4 ms |
| 60,000 | 34,492,416 | 53.2 ms | 189.4 ms |

Everything is linear. Per event, as the marginal rate between adjacent rows
of the table above — every division shown:

| per event | 5,000 → 20,000 | 20,000 → 60,000 |
| --- | ---: | ---: |
| DB growth | (13,107,200 − 5,079,040) / 15,000 = 535.2 B ≈ 0.52 KiB | (34,492,416 − 13,107,200) / 40,000 = 534.6 B ≈ 0.52 KiB |
| gap-scan | (18.1 − 4.6) ms / 15,000 = 0.90 µs | (53.2 − 18.1) ms / 40,000 = 0.88 µs |
| full scan | (74.4 − 14.4) ms / 15,000 = 4.00 µs | (189.4 − 74.4) ms / 40,000 = 2.88 µs |

Dividing each row's own totals by its event count instead reads 1,015.8 /
655.4 / 574.9 B, 0.920 / 0.905 / 0.887 µs (gap-scan) and 2.880 / 3.720 /
3.157 µs (full scan) per event for 5,000 / 20,000 / 60,000; the 5,000-event
row carries fixed page-cache and warm-up overhead, so the marginal rates above
are the sizing figures. At 20,000 events the populated DB holds:

| table | rows |
| --- | ---: |
| `events` | 20,000 |
| `artifacts` | 4,000 |
| `contradictions` | 2,000 |
| `curated_knowledge_entries` | 1,000 |
| `curated_knowledge_supersession` | 199 |

and the hot/cold split inside those tables:

- `contradictions`: 667 `OPEN` (hot) / 1,333 `RESOLVED|SUPERSEDED` (cold)
- `curated_knowledge_entries`: 250 `ADMITTED` (hot) /
  750 `SUPERSEDED|INVALIDATED` (cold)

So **66.65 % of the contradiction table (1,333 / 2,000) and 75 % of the
curated-knowledge table (750 / 1,000) is terminal state** that every
full-surface scan still walks. That is the unbounded growth L1 describes,
and it is the part this slice makes exportable.

**What grows unbounded, ranked by cost of the O(history) scans over it:**

1. `events` — the journal. Append-only by certification; never exported.
   The scans over it are `journal_gap_event_ids` (all ids in the occupied
   span) and any full `SELECT * FROM events`.
2. `contradictions` — resolved/superseded rows accumulate; `all_entries` and
   `open_contradictions` walk the table.
3. `curated_knowledge_entries` + `curated_knowledge_supersession` — the
   supersession ledger is cold by construction.
4. `artifacts` — content-addressed rows; immutable, so they grow but their
   terminality is not a row-state question. Left alone in this slice.

## 2. Design — additive only

`src/hermes/persistence/archive.py` (`ColdArchive`) copies the terminal rows
into a content-addressed cold archive and proves the copy.

**Exported cold classes** (keyed by primary key):

- `contradictions` — `status != 'OPEN'`
- `curated_knowledge_entries` — `status != 'ADMITTED'`
- `curated_knowledge_supersession` — every row

**Operations**

- `export(conn, chunk_size)` — SELECT-only reads on the caller's connection;
  writes `chunks/chunk-NNNNNN.ndjson` and `manifest.json`. Idempotent by key:
  the archived key set is derived from the manifest, so a re-run appends only
  keys that are not already cold, and a newly-terminal row is picked up by
  the next pass.
- `verify()` — re-reads every chunk, re-hashes every row and every file, and
  compares against the manifest. Fail-closed: a flipped byte, a missing
  chunk, a wrong row count, a duplicate key, a row absent from the manifest,
  or a manifest row absent from disk all raise `ArchiveIntegrityError`.
- `status()` — the manifest-only standing (rows, tables, chunks, digest).

**Invariants preserved — and how**

| Invariant | How it is preserved |
| --- | --- |
| Append-only journal, no DELETE/UPDATE/INSERT | `archive.py` issues only `SELECT`. It never opens a transaction, so it cannot commit anything. Proven in-tree by a whole-DB tripwire test. |
| Journal-hole tamper detection | `events` is not a cold table, so `journal_gap_event_ids` still scans the whole occupied span. A test plants a hole after an export and asserts it is still reported. |
| Certified transaction census | No transaction control in `archive.py` at all — `check_census.py` reproduces 121 / 27 / 15 / 0 exactly. |
| Single mutation path | The archive writes files, never durable state through the gateway. |
| Archive-not-delete | A row can be in the archive AND still hot. Nothing is removed. |

## 3. Deliberately NOT done in this slice

- **No `archived` marker in the database.** Marking is optional by the task's
  own wording. Doing it would need a schema migration and a DB write (hence a
  transaction), which would move the certified census and touch the
  migration surface. The archived key set is derivable from the manifest
  instead, so marking buys nothing here.
- **No sizing, no retention policy, no hot-path pruning.** L1's recommended
  action is *hardening slice + capacity design gate*; the census above is the
  "measure before sizing" input that gate needs. A bound on the O(history)
  scans would change `journal_gap_event_ids`, which is certified tamper
  evidence — that is a design gate, not a fixer improvisation.
- **Nothing else deleted or mutated anywhere.** No STOP condition fired.

## 4. Tests

`tests/test_archive.py` (16 tests) pins: cold classes only (OPEN/ADMITTED stay
hot); a whole-DB snapshot tripwire proving an export never mutates the hot
database; `events` never a cold table; verification proving a clean export;
verification refusing a flipped byte, a missing chunk, a row-set mismatch, an
unknown schema, and an absent archive; idempotence by key; incremental pickup
of a newly-terminal row; journal-hole detection surviving an export; and the
binding refusals (bad `chunk_size`, root that is a file).

## 5. Prohibited-claims discipline

This slice claims byte fidelity of an export against the database it came
from. It claims **no** scientific validity, no reproducibility, and no
reduction in journal size — the journal does not shrink, by design.

License: Apache-2.0 (LICENSE).
