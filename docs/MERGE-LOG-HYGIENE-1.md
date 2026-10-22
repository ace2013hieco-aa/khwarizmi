# MERGE-LOG-HYGIENE-1 — hygiene pass: claims, lint scope, lease generation, migration 2→3, decision determinism, LOCK retry (GAP-1 P3-1/2/3/5/7/11)

## Provenance

| Item | Value |
| --- | --- |
| Task | HYGIENE-1-MERGE (merge gate; local FF — the push is bundled with the wave-2 fleet under one human D9 pin) |
| Base (`main` before) | `efeb1f4` (COND-TYPE landing + its merge log) |
| Slice | `slice/hygiene-1@df1f57d`; **restacked** as `slice/hygiene-1-restacked@e01b636` (8 cherry-picks; the slice's own re-stamp dropped and re-created for the combined count — no rebase, no merge commit) |
| Landed tip (FF'd to) | `e01b636e4817b33a879e827e60bfbb68ca30a762` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — bundled with the wave-2 fleet under one human D9 pin |

## Scope

```
AGENTS.md                                |  18 +-    (P3-1 claim + P3-2 command; governed)
docs/API.md                              |  15 +     (P3-11 retry rule; governed)
README.md                                |   2 +-    (P3-2 command)
.github/workflows/ci.yml                 |   4 +-    (P3-2 ruff lines only)
scripts/adversarial_probe_s5.py          |  84 +-    (P3-2 lint)
scripts/demo_retraction_cone.py          |   2 +-
scripts/p1b_audit2_probes.py             |  12 +-
src/hermes/persistence/{backup,database}.py | 17 +   (P3-3 released-row semantics)
src/hermes/persistence/migrations.py     |  22 +-    (P3-5 explicit rebuild)
src/hermes/research/controller.py        |  40 +-    (P3-3 lease, P3-7 conflict mapping)
src/hermes/research/gateway.py           |   6 +-    (P3-7 ORDER BY)
src/hermes/research/verdict_decisions.py |  31 +-    (P3-7 conflict detection)
tests/*                                  | 10 files  (3 new test modules + aligned pins)
docs/gr3-b4/b4-fixtures/*                | 3 renames + README record
docs/SUITE-COUNT.md                      |  +3 -3    (4886)
```

## What was certified

- **P3-1** — AGENTS.md no longer claims "No DELETE exists in `src/`". The
  honest invariant: durable research state is append-only (no DELETE of
  tasks/evidence/events); the only remaining `DELETE FROM` sites are the
  legacy writer-lock release in `database.py`. `tests/test_delete_census.py`
  pins exactly 2 occurrences in exactly that file, both
  `DELETE FROM scheduler_lock`, with no line-number pins.
- **P3-2** — the ruff gate now covers `src tests scripts`
  (ci.yml ruff lines, AGENTS.md, README); three scripts cleaned minimally.
- **P3-3** — scheduler lease release now MARKS the row free in place
  (`RELEASED_LOCK_OWNER = ""`) instead of deleting it; the next acquisition
  reuses the row and increments `generation`, so the ADV-02 generation never
  resets to 0 and a released holder's token cannot validate after the next
  owner takes over. Owner-guarded release; `get_lock_owner`/backup restore
  treat the marker as free. No schema change. Pins: generation monotonicity,
  reclaim fencing, stale-reclaim continuity, restore-under-live-lease.
- **P3-5** — migration 2→3 no longer uses `CREATE TABLE ... AS SELECT`
  (which lost PK/constraints/indexes/affinity). It now creates the explicit
  table DDL, copies with a column list, drops, renames, and recreates the
  indexes. A v2→latest migration test pins PK/AUTOINCREMENT, NOT NULLs, FKs,
  indexes, and row preservation.
- **P3-7** — the two decision lookups lacking ORDER BY now use
  `ORDER BY rowid`; `record_human_decision_once` detects a repeat under the
  same correlation with different content and raises
  `HumanDecisionConflict`, translated by the Controller to the existing
  refusal-as-data `IDEMPOTENCY_CONFLICT` (no new authority, no new code
  string). **Intended behavior change**: a conflicting repeat is now
  refused instead of silently returning the first decision; the
  CRES-DIGEST replay pin was aligned while preserving its core property
  (the digest never moves). Recorded as a W4-delta candidate.
- **P3-11** — docs/API.md defines LOCK as the only retryable refusal:
  client-owned bounded backoff with a fresh scheduler/lease re-read; never
  bypass the lease; every refusal is data.

## B4 regeneration (deliberate, two governed docs in one edit)

`AGENTS.md` + `docs/API.md` edits moved three governed fixture identities:
`b4-c1 357b9ee3… → 20204aaf…`, `b4-c2 03127be4… → 3bbe04e6…`,
`b4-c4 b5b21189… → c3fca6dc…`; `b4-c3 eef41946…` unchanged. Edge sets and
source counts identical; README table + one re-derivation record appended.

## Gates (raw)

Agent run at slice tip: **FULL suite 4866 passed, 3 skipped, 0 failed**;
stamp 4869; census PASS; B4 24; ruff pass; pyright 0/0/0 + 0/1; NOT-list 0.

Director re-derivation at restacked tip `e01b636`: battery (11 files: new
pins + all touched surfaces) **328 passed**; stamp `--check` OK **4886**
(4878 + 8); census PASS; B4 **24 passed**; ruff (src+tests+scripts)
`All checks passed!`; NOT-list **0 hits** (word-boundary).

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| behavior change beyond the ruled P3-7 determinism/conflict fix | **none** — lease, migration and lint changes preserve behavior; P3-7b recorded above |
| census shift | **none** — 124 / 28 / 19 / 15 unchanged |
| B4 digests moved unintentionally | **no** — deliberate regen for the two governed docs, recorded in the fixture README |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `efeb1f4` |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies documentation truth, gate scope, lease-generation
hygiene, a schema-preserving migration, deterministic decision reads, and a
documented retry rule. It makes no validity, reproducibility, or
admissibility claim.

License: Apache-2.0 (LICENSE).
