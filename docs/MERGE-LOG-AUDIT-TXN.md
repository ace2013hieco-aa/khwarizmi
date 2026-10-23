# MERGE-LOG-AUDIT-TXN — same-transaction audit append (GAP-1 D12 / P2-7)

## Provenance

| Item | Value |
| --- | --- |
| Task | AUDIT-TXN (GAP-1 D12-A; chartered after TAMPER-2 landed, as the ruling requires) |
| Base (`main` before) | `76962af` (TAMPER-2 landing + D1 rulings row) |
| Slice | `slice/audit-txn@5ef14f8` — created at the base, so **no restack was needed**; landed by fast-forward |
| Landed tip (FF'd to) | `5ef14f8417a499411a633412a44ac0dfc204b945` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — awaiting the human's D9 pin |

Design-note commit (reviewed before implementation): `80ad983`
(IDR-013 addendum A1.1–A1.6).

## The defect and what changed

`apply_intent` dispatched to a validator whose write path owned its own
`BEGIN … COMMIT`; only after that commit returned did the gateway append
`IntentApplied` through `append_transactional` — **a second transaction**. A
crash between the two left a durable mutation with no audit row.

Now the audit row is written **inside the mutation's transaction**:

- `_append_audit_event` is a pure builder returning an immutable `AuditRecord`
  (defined in persistence, so the import direction is unchanged and no new
  persistence→research statement appears).
- `apply_intent` builds the applied record once, before dispatch, and validates
  it with the writer's own gate (`validate_event`), so an over-cap or
  secret-bearing record refuses **pre-write** instead of stranding a committed
  mutation.
- The record travels as an explicit `audit=` parameter — never connection
  state, a thread-local or a module global — through all 13 validators to the
  **10 transaction owners** (5 persistence, 5 gateway), each of which appends it
  immediately before its existing `COMMIT`.
- Duplicates and rejections keep their own transaction: a rejection produces no
  mutation, so there is nothing to strand, and that is also what keeps the
  `retry_without_project` FK fallback available. The fused path never calls
  `append_transactional`, so its `ROLLBACK`-then-retry can never undo a
  mutation.

## What was certified

- **Forward crash window closed** — a fault injected into the `IntentApplied`
  append (only that event; the mutation's own event still writes) leaves
  **neither** the mutation row nor the audit row, and still journals exactly one
  `IntentRejected`. Proven for a persistence owner (ADMIT_TASK), a gateway owner
  (CURATE_KNOWLEDGE) and the artifact-only mutation (RECORD_CLASSIFICATION).
- **Backward window closed** — a fault after `COMMIT` leaves both the mutation
  and its `IntentApplied` row; the mutation is durable, so the applied row is
  not a false claim.
- **No `IntentApplied` without the mutation** — the fused row is only written on
  a branch that already wrote the mutation in that transaction; a rollback takes
  both.
- **Adjacency** — for one intent of each of the 13 branches, exactly one
  `IntentApplied`, with `prev_hash == <mutation event>.chain_hash` and
  `event_id == <mutation event>.event_id + 1`.
- **Refusal-as-data unchanged** — role, project and payload refusals each land
  exactly one `IntentRejected` with the exact `GatewayRejection.code`; the
  stale-project fallback still writes `project_id IS NULL` with the id retained
  in the payload and touches no mutation table.
- **Chain intact** — `verify_journal` is `CHAIN_OK` after a fused apply; nothing
  bypasses `_append_event_to_db`, so the audit row is chained directly onto the
  mutation's event with no interleaving possible.
- **Census unchanged, and re-derived rather than assumed** — no
  `BEGIN`/`COMMIT`/`ROLLBACK` statement was added, removed or moved: 124 calls,
  28 owners (19/5/4), 1 rollback-only, 15 imports, 0 outside layers, statement
  mix `BEGIN 29, COMMIT 28, ROLLBACK 67`. `AGENTS.md:23` and
  `docs/ARCHITECTURE.md:151/:180` stay true verbatim; no governed-doc edit and
  no B4 regeneration.

## Gates (raw, at landed tip `5ef14f8`)

| Gate | Result |
| --- | --- |
| `tests/test_audit_txn_atomicity.py` | **40 passed** |
| Full suite | **5050 passed / 3 skipped / 5 failed** in 747.80s (collected 5058) |
| `stamp_suite_count.py --check` | `OK: docs\SUITE-COUNT.md collected=5058 matches the live collect` |
| `check_census.py` | **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0 outside; `BEGIN 29, COMMIT 28, ROLLBACK 67` |
| B4 ref graphs | **24 passed** |
| `ruff check src tests scripts` | `All checks passed!` |
| `pyright src` | **0 errors, 0 warnings, 0 informations** |
| `pyright --project pyrightconfig.tests.json` | **0 errors, 1 warning** (known `test_research_program.py:144`) |
| NOT-list | **0 hits** |
| Governed corpus touched | **none** |

The five failures are the host-level set documented in `MERGE-LOG-WAVE-3A.md`;
nothing outside that set failed.

## Intended deltas (W4)

1. **An over-cap or secret-bearing justification now refuses pre-write** with
   `MALFORMED_PAYLOAD`. Previously the mutation committed and the audit append
   then failed — the F2 signature (durable mutation, no audit row, raw error).
   This is the defect being fixed, seen from the refusal side.
2. **A rejection whose echoed justification is itself unwritable** (over-cap or
   secret-format) is now bounded — truncated to 1024, or omitted with the value
   never sanitised into something that looks authored — and the row carries
   `audit_bounded`. Refusal journaling stays total; only rows that today cannot
   be written at all are affected.
3. **Refusal-site census**: `MALFORMED_PAYLOAD 123 → 124`, total `268 → 269`,
   inline reason recorded; structure unchanged. This is the pre-dispatch
   audit-payload gate, not a transaction-census figure.
4. **Audit rows now precede no mutation but share its commit** — the journal
   order within a transaction is mutation event, then `IntentApplied`.

## Residuals (reported, not fixed)

1. **Rejections and duplicates still own their transaction.** A rejection has no
   mutation to fuse; a duplicate writes nothing. Both are deliberate (A1.3) and
   neither can strand a mutation.
2. The `retry_without_project` FK fallback remains available **only** on the
   non-fused path — by construction, never inside a mutation transaction.
3. The five host-level suite failures persist (environment, not code).

## Prohibited-claims discipline

This gate certifies transaction atomicity of the audit append: no durable
mutation without its audit row, and no `IntentApplied` row without the mutation
it reports. It is not a claim that the audit trail is complete against an actor
who can rewrite the database file, nor that a verified journal is authority.

License: Apache-2.0 (LICENSE).
