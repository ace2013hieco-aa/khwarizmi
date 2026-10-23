# MERGE-LOG-P2-2 — the DB-writer trust boundary, documented and accepted (GAP-1 P2-2 / ruling A)

## Provenance

| Item | Value |
| --- | --- |
| Task | P2-2 (GAP-1): unsigned decisions — any DB writer can forge a decision/intent |
| Ruling | **A — document-and-accept** (human, 2026-10-23) |
| Base (`main` before) | `67ba1e1`; restacked onto `24daf18` (P2-4 landing) by **cherry-pick** — the only overlap was `docs/gr3-b4/b4-fixtures/README.md`, in disjoint regions |
| Landed tip | `7325c3f` |
| Merge method | cherry-pick (no merge commit) |
| Push | included in the wave-3c push (this batch) |

## Scope

```
docs/STATE.md                              | 16 ++  (the accepted boundary)
docs/gr3-b4/b4-fixtures/README.md          | 16 ++  (re-derivation record)
docs/gr3-b4/b4-fixtures/*.json             |  3 renames (b4-c1, b4-c2, b4-c4)
```

One governed edit (`docs/STATE.md`) plus its **mandatory B4 regeneration**. No code, no
test, no migration.

## What was certified

The `docs/STATE.md` intentional-architecture list now carries the boundary beside the D5
credential entry, and it states all six things it must:

1. **The boundary is file write access** — SQLite write lets an actor insert or rewrite
   decision/intent rows, including a `HumanDecisionReceived` row cited as authority; the
   gateway admits it.
2. **`proposed_by` is a checked claim, not authorship** — gateway-validated against
   `AgentProfile`/role partition, runtime-filled from the trusted spec; it bounds what the
   runtime *says*, not who wrote the row.
3. **TAMPER-2's relation to it** — the unkeyed per-event chain makes journal *tampering*
   evident (only an out-of-band tip detects a re-chain), **not forgery**: a forger writes a
   valid chain. **Chain is not authorship.**
4. **What defends instead** — model output proposes; deterministic code and the
   human-authority gates decide; the audit trail records what the database says, not who
   typed it.
5. **What is accepted** — no command signing, MAC, key material or custody (D5 stands).
6. **The non-claim** — boundary acceptance only, not validity/reproducibility/admissibility,
   and not an audit-trail-is-forgery-proof claim.

`docs/ARCHITECTURE.md` and `AGENTS.md` were deliberately **not** touched: a §3.10
cross-reference would be a second governed edit and a second decision, and the agent was
instructed to stop rather than take it.

## B4 regeneration (deliberate, recorded)

`docs/STATE.md` is a `CORPUS_REFS` member, so the governed identities moved:

| Fixture | Old | New |
| --- | --- | --- |
| `b4-c1-p1a-baseline` | `20204aaf…` | `f8a80697…` |
| `b4-c2-expanded-cohort` | `3bbe04e6…` | `1b8aaec7…` |
| `b4-c3-idr-design-chain` | `eef41946…` | **unchanged** (IDR-only stratum) |
| `b4-c4-authority-spine` | `c3fca6dc…` | `ddc877b0…` |

Edge sets, `sources` counts and `skipped` lists are identical (5 / 19 / 10 / 5; 6 / 12 /
8 / 4; 21 / 28 / 15 / 18) — only the pinned byte identities moved. The three stale
content-addressed files were deleted, and the re-derivation record is in the fixtures
README in the established format. **24 B4 tests stay 24.**

## Gates (raw)

| Gate | Result |
| --- | --- |
| B4 ref graphs | **24 passed** (at the slice tip and again after the restack) |
| `stamp_suite_count.py --check` | `OK: docs\SUITE-COUNT.md collected=5058` |
| `check_census.py` | **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0, unchanged |
| Full suite (slice tip) | **5055 passed / 3 skipped / 0 failed** |
| `ruff check src tests scripts` | `All checks passed!` |
| `pyright src` / tests project | **0/0/0** / **0 errors, 1 known warning** |
| `docs/STATE.md` encoding | LF-only, 0 CR bytes; diff is the 16 added lines only |

## Residuals

1. `docs/ARCHITECTURE.md` §3.10 does not cross-reference this boundary. Deliberate; needs
   its own charter if wanted.
2. The boundary is a **statement about trust**, not a mechanism. Nothing in the tree
   changed to make forgery harder — that is the point of ruling A, and the entry says so.

## Prohibited-claims discipline

This gate records an accepted boundary. It claims no forgery resistance, no validity, no
reproducibility, and no admissibility; it explicitly denies that the audit trail is
forgery-proof.

License: Apache-2.0 (LICENSE).
