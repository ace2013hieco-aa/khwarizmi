# TAMPER-EVIDENT JOURNAL — Per-Event Hash Chain + Append-Only Triggers

**Status:** PARTIALLY IMPLEMENTED — stage S only (TAMPER-1, 2026-10-18):
§2.1's append-only triggers landed by migration 20 → 21
(`SUPPORTED_VERSION = 21`), with the §3.1 rule-2 re-creation inside the
`_migrate_2_to_3` rebuild; see the addendum at the end. The chain (§1), the
§3.3 chain migration, and §4 signatures remain DESIGN ONLY — no chain column
and no re-chain tool exists at this revision.

**Date:** 2026-10-11
**Base:** `origin/main` @ `f6939129eb8429934c57db206a11480dab691ddb`
**Decides for:** how the append-only journal (`events`, v4 §8.1) becomes
*tamper-evident* — a per-row hash chain plus SQL-level refusal of
`UPDATE`/`DELETE` — and under what precondition digital signatures land.

**Not decided here:** cryptographic authorship, key custody, external
anchoring, and any migration content. See §4.

---

## 0. Scope, non-goals, and what is already true

The journal is already append-only *by discipline*: `src/` contains no
`UPDATE events` and no `DELETE FROM events` statement (the only two
`events` DDL statements in `src/` are `migrations.py:309` and `:328`,
both inside the `2 → 3` rebuild), and the single writer is
`_append_event_to_db` (`src/hermes/persistence/repositories.py:97`),
called from 27 sites across 5 modules. Append-only is therefore a
**convention enforced by code review**, not a property the database can
enforce. This design adds two independent enforcement layers:

1. **Detection** — a per-event hash chain (§1) makes any post-hoc
   mutation of a row, or deletion/reordering of rows, *recomputably
   visible*.
2. **Refusal** — `BEFORE UPDATE` / `BEFORE DELETE` triggers (§2) make the
   two mutation verbs *fail closed at the SQL layer* for every caller,
   including raw `sqlite3` and any future driver.

**Non-goals.** This is tamper-**evident**, not tamper-**proof**. An actor
holding DDL rights can `DROP TRIGGER` and re-chain; that act is explicit,
greppable, and not hidden by this design. Prevention against such an
actor requires the external anchor and signatures deferred in §4.

**Already-certified properties this must not disturb:** single mutation
path through `apply_intent` (`gateway.py`), no `DELETE` anywhere in
`src/`, supersession-as-new-row, refusal-as-data, the 4 KiB bounded
payload cap (`event_validation.py:23`, DB-level byte-exact at
`migrations.py:137`), and lease-fenced single-writer control. The chain is
a *derived view* of the journal; per the prohibited-claims discipline it
is never presented as authority, and a green chain-verify is never
presented as scientific validity.

---

## 1. Per-event chain

### 1.1 Which fields are hashed — the identity/provenance split

The chain covers **derived identity only**. `created_at` is *excluded*.

This is the established G1 split, recorded for `ResearchProgram` at
`docs/idr/hermes_v6_authority_evidence_map.md:19` — "content hash excludes
provenance fields (`created_at/version/produced_by` live on the row)" —
and implemented at `src/hermes/research/programs.py:1509` where
`canonical_content_dict` omits exactly those fields. The same split is
adopted here for one concrete reason beyond consistency: `created_at` is
the field a rebuild, replay, or re-import may legitimately restamp, so
hashing it would make §3's mandatory re-chain non-deterministic.

Consequence, stated plainly: **`created_at` mutation is not detected by
the chain.** That is a deliberate, documented gap instead of an accident.
Closing it requires an independent provenance anchor and is deferred with
§4.

### 1.2 Genesis

```
GENESIS = sha256_hex("hermes.journal.chain.v1/genesis")
```

A fixed domain-separated constant, never the empty string: a chain that
begins at `H("")` is indistinguishable from a chain that begins at a
truncated/forged digest, and the domain string makes the genesis value
non-confusable with any event digest.

Rule: the row with the smallest `event_id` that carries a chain hash must
have `prev_hash == GENESIS`. In a fully chained journal that is the
journal's first row.

`sha256_hex` is reused as-is (`src/hermes/research/programs.py:387`); the
half-a-dozen competing local canonicalizers in the tree
(`hermes/governance/policy.py:287`, `hermes/agents/runtime/types.py:163`,
`hermes/methodology/substrate.py:267`) are **not** used — one authority,
same argument as ADV-05 for `KNOWN_EVENT_TYPES`.

### 1.3 Field list (11 of 14 columns)

Hashed, in this order (order is documentary; the serializer sorts keys):

| # | Field | Source column |
|---|---|---|
| 1 | `event_id` | `event_id` |
| 2 | `event_type` | `event_type` |
| 3 | `project_id` | `project_id` |
| 4 | `task_id` | `task_id` |
| 5 | `from_state` | `from_state` |
| 6 | `to_state` | `to_state` |
| 7 | `correlation_id` | `correlation_id` |
| 8 | `caused_by` | `caused_by` |
| 9 | `reason` | `reason` |
| 10 | `artifact_ids_json` | `artifact_ids_json` |
| 11 | `payload_json` | `payload_json` |

Excluded: `created_at` (§1.1) and the two chain columns themselves
(`prev_hash`, `chain_hash`).

The 11 fields are taken **verbatim as stored**, not parsed and
re-serialized. Two reasons, both load-bearing:

- **Byte coverage.** Re-parsing `payload_json` and re-serializing would
  make a reformatted-but-semantically-equal payload hash-identical, i.e.
  silently undetectable. Hashing the stored TEXT covers the bytes.
- **No new canonicalizer.** The only serialization added by this design is
  `canonical_json` (`src/hermes/research/programs.py:381`) applied to a
  **flat mapping of scalars**, so `_canonicalize`'s
  list-sorting branch (`programs.py:354`, which sorts lists of dicts and
  scalars) is never reached and intra-payload element order is preserved
  rather than erased. That property is asserted by a fixture (§6, M8).

`NULL` in any of fields 3–6, 8, 9, 10, 11 serializes as JSON `null`
(the columns are nullable; the writer currently always supplies `{}` for
`payload_json` and `[]` for `artifact_ids_json` via `_json_dumps`,
`repositories.py:85`).

### 1.4 Recurrence

Let `h(n)` be the chain digest of the row at position `n`, `n ≥ 1`, rows
ordered by `event_id` ascending.

```
body(n)     = canonical_json({f: value_of(f) for f in the 11 fields})
preimage(n) = h(n-1) + "\n" + body(n)          # UTF-8 encoded
h(n)        = sha256_hex(preimage(n))           # 64 lowercase hex chars
h(0)        = GENESIS
```

The `"\n"` separator and fixed-width 64-hex predecessor make the
concatenation prefix-free: the split point of `preimage(n)` is unique, so
no two distinct `(h(n-1), body(n))` pairs can collide by construction.
`h(n-1)` is written lowercase hex and lowercased before comparison, so
case never becomes a false defect.

Storage: two new columns on `events`, appended after `created_at`:

```
prev_hash   TEXT    -- h(n-1) for this row; NULL = unchained
chain_hash  TEXT    -- h(n)   for this row; NULL = unchained
```

Both are **nullable with no `DEFAULT`**. Deliberate: 45 direct
`INSERT INTO events` sites across 17 test modules build journal fixtures
in raw SQL (§5), and a `NOT NULL` column breaks every one of them. The
chain is therefore enforced by the *writer*, and absence of a chain is a
*reported defect* rather than an unrepresentable state:

- The writer (`_append_event_to_db`, `repositories.py:97`) reads the
  current tip and inserts both digests, inside the caller's already-open
  transaction. The tip read and the `INSERT` must be in the same
  transaction — the read is not hoisted above acquisition (the G1-3
  statement-ordering precedent). Under lease-fenced single-writer control
  there is exactly one tip at a time.
- A row inserted by anything other than the writer has
  `chain_hash IS NULL` and verifies as `CHAIN_UNCHAINED_ROW` — visible,
  not silently accepted.

Column addition uses `ALTER TABLE ... ADD COLUMN`, the same append-only
pattern as `_migrate_19_to_20` (`migrations.py:1193`, `:1215-1217`): no
table rebuild, no history rewrite. Re-chaining is not a rewrite — the new
columns carry no information that is not recomputable from the row's own
existing values.

### 1.5 Verification

```
verify_journal_chain(rows, *, anchor=None, allow_unchained=False)
    -> {ok, code, event_id, expected, actual, genesis, tip}
```

Walk rows in `event_id` ascending order, maintaining a running digest
initialized to `GENESIS`. At the **first** defect, stop and return it
(subsequent rows are consequential, not independent findings).

| Code | Meaning |
|---|---|
| `CHAIN_EVENT_ID_OUT_OF_ORDER` | `event_id` not strictly increasing |
| `CHAIN_UNCHAINED_ROW` | `chain_hash`/`prev_hash` NULL and `allow_unchained=False` |
| `CHAIN_PREV_MISMATCH` | stored `prev_hash` ≠ running digest |
| `CHAIN_HASH_MISMATCH` | stored `chain_hash` ≠ recomputed `h(n)` |
| `CHAIN_UNENCODABLE_ROW` | a hashed value cannot be UTF-8 encoded (e.g. a lone surrogate reaching the DB by file-level edit) — fail closed, never skip |
| `CHAIN_TIP_MISMATCH` | `anchor` supplied and final digest ≠ anchor |
| `CHAIN_OK` | no defect |

`anchor` is the optional out-of-band tip digest; supplying it converts the
one undetectable case (§1.6) into a detectable one.

### 1.6 What the chain does not catch

- **Tail truncation.** Deleting the last *k* rows leaves a shorter but
  self-consistent chain. Only `anchor`/§4 detects this.
- **Full re-chain.** An actor who can drop the triggers and recompute every
  row produces a valid chain. Detecting this needs the external anchor,
  not more hashing.
- **`created_at` rewrite.** By design (§1.1).

### 1.7 Cost

- Per row: 128 bytes of stored hex + 129 bytes of preimage prefix
  (64-hex predecessor + `"\n"`). No effect on the 4 KiB payload cap, which
  continues to bound `payload_json` alone, byte-exactly
  (`migrations.py:137`, `event_validation.py:23`/`:74`).
- Per append: one indexed `SELECT` for the tip plus one SHA-256 over a
  bounded (≤ 4 KiB payload) preimage. The 4 KiB cap is what makes inline
  hashing of payloads correct rather than a deferred artifact digest.

---

## 2. `BEFORE UPDATE` / `BEFORE DELETE` triggers

There is **no existing trigger anywhere in `src/`** — this would be the
first. SQLite has no `ALTER TABLE ... DROP CONSTRAINT`, hence triggers.

### 2.1 DDL (exact, to be reproduced verbatim)

```sql
CREATE TRIGGER IF NOT EXISTS trg_events_append_only_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'HERMES_JOURNAL_IMMUTABLE_UPDATE');
END;

CREATE TRIGGER IF NOT EXISTS trg_events_append_only_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'HERMES_JOURNAL_IMMUTABLE_DELETE');
END;
```

### 2.2 Named errors

The two message strings are part of the contract and are pinned literally
by test:

- `HERMES_JOURNAL_IMMUTABLE_UPDATE`
- `HERMES_JOURNAL_IMMUTABLE_DELETE`

`RAISE()` is legal only inside a trigger body, and only as a statement —
hence `SELECT RAISE(ABORT, ...)` rather than a bare `RAISE`.

### 2.3 Semantics

- `RAISE(ABORT)` undoes the offending statement and leaves the transaction
  open; the error propagates to the caller. Through the Python `sqlite3`
  driver this surfaces as `sqlite3.IntegrityError` carrying the message —
  pinned by test (§6, M9).
- Applies to `UPDATE` and `DELETE` **only**. `INSERT` is untouched, so the
  single writer and the 45 raw-insert fixture sites keep working.
- DDL does not fire DML triggers: `ALTER TABLE events ADD COLUMN` and
  `CREATE TABLE events_new` are unaffected. `DROP TABLE events` **does**
  destroy the triggers (it destroys every trigger on the table) — this is
  the entire reason for §3.
- No configuration disables a trigger. The only escape is
  `DROP TRIGGER ...`, which is itself explicit DDL; §5 routes the test
  sites that legitimately need it through one helper.

### 2.4 What the triggers do not do

They do not stop `DROP TRIGGER` + `UPDATE`, they do not cover `ALTER TABLE
... DROP COLUMN` (a rebuild path), and they do not detect a row that was
never chained. They raise the cost of tampering and guarantee that the
ordinary path fails closed; the chain provides detection on top.

---

## 3. Rebuild rule — any migration touching `events` must re-chain

### 3.1 The rule (binding on all future migrations)

Any migration whose statements touch the `events` table must, **inside that
migration's single transaction** (`migrate_to_latest` wraps each migration
in `BEGIN`/`COMMIT`, `migrations.py:1265`):

1. Recompute `prev_hash`/`chain_hash` for **every** row in `event_id`
   ascending order, starting from `GENESIS` — i.e. re-chain, do not copy
   the old digests.
2. Re-create both triggers from §2.1 **last**, after the re-chain, because
   the rebuild path drops them.
3. Enumerate the `events` columns explicitly in any copy. The precedent's
   `INSERT INTO events SELECT * FROM events_new`
   (`migrations.py:308`, `:327`) is positionally coupled to the column
   order; after the chain columns land, `SELECT *` silently mis-assigns.
4. Leave `created_at` untouched (§1.1 makes it possible to do so without
   breaking the chain).
5. Ship a test that runs the migration and then asserts
   `verify_journal_chain(...).ok` — the migration is not done until the
   chain verifies.

Rule 1 is what makes re-chaining *mandatory* rather than optional: a
rebuild that preserves old digests while reordering or re-keying rows
produces a journal that fails its own verification.

### 3.2 Why this rule exists — the precedent

**Four of the twenty registered migrations touch `events`**, and exactly
one of them rebuilds it:

| Migration | `events` involvement |
|---|---|
| `_migrate_0_to_1` (`migrations.py:23-175`) | `CREATE TABLE events` (`:124`) + 2 indexes (`:143`, `:146`) |
| `_migrate_2_to_3` (`migrations.py:293-340`) | **rebuild**: `DROP TABLE events` (`:309`), re-`CREATE` (`:311`), `INSERT INTO events SELECT * FROM events_new` (`:327`) |
| `_migrate_11_to_12` (`migrations.py:729-777`) | `CREATE UNIQUE INDEX idx_events_one_verdict ON events(...)` (`:763-764`) + read (`:744`) |
| `_migrate_14_to_15` (`migrations.py:873-1001`) | `events` index + read (`:967`) |

(`_migrate_4_to_5` mentions `events` in its docstring only — no statement.)

`_migrate_2_to_3` is the rebuild precedent, and it does the two things
§3.1 forbids done alone: `DROP TABLE events` (`:309`) and the positional
`INSERT INTO events SELECT * FROM events_new` (`:327`). It is
**grandfathered, not endorsed**: it predates both the chain and the
triggers, so it has nothing to re-chain and nothing to re-create. Its
pinned regression test (`tests/test_database.py:147-289`,
char-counted CHECK → byte-accurate CHECK) is the template for §3.1 rule 5.

The other three bound the rule's reach rather than weaken it. Index
creation (`:763-764`) does not destroy triggers, so an index-only
migration satisfies §3.1 rules 1-2 trivially — but it must still not
re-create the table, and the two read-only touches (`:744`, `:967`) show
that migrations already depend on the journal's *contents*, which is
precisely what a silently broken chain would corrupt.

The concrete trap it demonstrates: if the chain existed and a future
migration copied it, re-created the table, and forgot §3.1 rule 2, the
journal would silently become mutable again while still verifying — the
worst failure mode available, because both enforcement layers degrade
without any error.

### 3.3 The chain migration itself (future slice — 20 → 21)

Ordered, all in one transaction:

1. `ALTER TABLE events ADD COLUMN prev_hash TEXT`
2. `ALTER TABLE events ADD COLUMN chain_hash TEXT`
3. Re-chain all existing rows in `event_id` order from `GENESIS`
   (no triggers exist yet — nothing to drop).
4. Create both triggers (§2.1) — **last**.
5. `SUPPORTED_VERSION = 21`; register in `_MIGRATIONS`
   (`migrations.py:1226-1247`).
6. Test: migrate a v20 database with rows, then assert chain-verify is
   `CHAIN_OK`; assert `UPDATE`/`DELETE` now raise; assert `INSERT` still
   succeeds. Assert `created_at` values are byte-identical to
   pre-migration.

Not implemented in this change.

---

## 4. Signatures — deferred, with the external-verifier precondition

**Decision: no signature, no MAC, no key material in this design.**

The chain is unkeyed, so it proves *internal consistency and
post-hoc-mutation detection* and nothing about *who wrote the row*.
Unkeyed hashing cannot answer authorship: the same actor who can rewrite a
row can recompute the chain. Signatures are the only mechanism that
answers it, and they are deferred for four reasons:

1. **A key is a new authority surface.** The certified invariant is that
   determinism owns control and no external output decides a transition;
   an operator-held signing key is a new custody/rotation/compromise
   boundary that needs its own design gate and its own §28.3-style
   rule set.
2. **No key store exists.** There is no keystore, no key file, no secret
   convention in the repo to extend; inventing one inside a journal-integrity
   slice would smuggle a security decision into an integrity change.
3. **Signing without anchoring buys little.** An attacker with DDL rights
   who can drop a trigger can also drop a table or restore a backup; a
   signature over a chain the attacker can wholly replace is only as good
   as the *verifier's* independent knowledge of the tip.
4. **The verifier does not exist yet.**

### Precondition to un-deferring (all four, in order)

Signatures may be designed only once all of the following are true:

1. **An out-of-band tip anchor exists** — an append-only channel, or a
   human-escrowed digest, that the database owner cannot rewrite. This is
   the same artifact that closes `CHAIN_TIP_MISMATCH` (§1.5) and is
   *required* regardless of signatures.
2. **An external verifier exists** — a party that is neither the database
   owner nor the verifier process, holding the public key and the anchor,
   and able to recompute §1.4 independently. Until an independent party
   actually runs the check, a signature is a claim about a check nobody
   performed.
3. **A custody policy exists** for key generation, storage, rotation, and
   compromise response, with a named owner.
4. **A canonical-bytes contract is frozen and shared** with that verifier.
   §1.4 of this document *is* that contract; it must be versioned
   (`hermes.journal.chain.v1`) and changes to it are a new chain version,
   never an in-place edit.

When the precondition is met, the natural shape is: signature over
`h(tip)` (not per row), stored outside `events`, verified by the external
party against the anchor. That is a **future IDR**, not this one.

**Claims discipline:** replay/verification proves byte and derivation
determinism only — never scientific validity, never admissibility of a
retracted source (N9), and never authority. A verified chain is a
mechanically true statement about the file.

---

## 5. Blast radius and required test-surface migration

Counts are at base `f693912` and are the evidence for the decisions above.

**Production (`src/`).** Exactly one `INSERT INTO events` statement
(`repositories.py:122`), inside the one shared writer
`_append_event_to_db` (`repositories.py:97`), reached by:

- 27 direct call sites across 5 modules — `repositories.py` 5,
  `controller.py` 10, `gateway.py` 10, `source_outcomes.py` 1,
  `verdict_decisions.py` 1;
- 3 delegating `_append_event` methods (`repositories.py:370`, `:708`,
  `:1811`) with 8 call sites.

So the chain is computed in **one function**; no orchestration, controller,
or gateway change is required. No `src/` statement performs
`UPDATE events` or `DELETE FROM events` — the triggers are non-breaking
for production code.

**Tests — the compatibility cost, named:**

| Raw statement | Sites | Files |
|---|---|---|
| `INSERT INTO events` | 45 | 17 |
| `UPDATE events` | 14 | 6 |
| `DELETE FROM events` | 10 | 6 |
| `DROP TABLE events` | 1 | 1 |

`INSERT` sites need nothing (chain columns are nullable). The 24
`UPDATE`/`DELETE` sites are *deliberate* tamper simulations that prove
consumers fail closed on a corrupt journal — e.g.
`tests/test_q04_gate_replay.py:367` corrupts `payload_json` to prove replay
refuses, `tests/test_step7_curated_registry.py:594-692` corrupts
curated-registry payloads, `tests/test_vault_manifest.py:220-561` punches
holes and rewrites `reason`. Under §2 they raise before reaching the
consumer, so the implementing slice must route them through **one**
tamper-simulation helper that drops both triggers, performs the mutation,
and re-creates them — and that asserts the mutation is refused *before*
the drop. The single `DROP TABLE events` site
(`tests/test_fence_classifier.py:186`) is a stale-lease probe that never
succeeds and is unaffected.

This table is why the trigger DDL is specified as its own §2 and the
re-creation requirement as its own §3: the failure mode of this change is
not "the chain has a bug", it is "a test's tamper simulation silently stops
tampering and the suite goes green without proving anything".

---

## 6. Fixture proof (this design's falsifier)

`tests/test_tamper_evident_journal.py` + `tests/fixtures/tamper_evident/`
carry a **reference implementation** of §1.4/§1.5 and §2.1 and pin it
against frozen digests. It is a prover artifact, deliberately not `src/`:
the spec is proved implementable and falsifiable before anything ships.

| ID | Fixture | Pins |
|---|---|---|
| M1 | `journal_clean.json` | reference `h(n)` reproduces the frozen `chain_hash` for every row — the recurrence and the 11-field list, byte for byte |
| M1b | `journal_clean.json` | the same digest is reproduced by a **second, independent** construction path (`hashlib` + literal `json.dumps`, bypassing both the reference module and `programs.canonical_json`) — the spec is implementable from this document's prose alone |
| M2 | `journal_clean.json` | `verify_journal_chain` → `CHAIN_OK`; `tip` equals the frozen tip |
| M3 | `tamper_cases.json` | one mutant per hashed field (11 of them) → `CHAIN_HASH_MISMATCH` at the expected `event_id`, `expected`/`actual` both reported |
| M4 | `tamper_cases.json` | deleting a middle row → `CHAIN_PREV_MISMATCH` at its successor |
| M5 | `tamper_cases.json` | `created_at` mutation → **no** defect (pins §1.1 as deliberate, so nobody "fixes" it silently) |
| M6 | `tamper_cases.json` | tail truncation → no defect without `anchor`, `CHAIN_TIP_MISMATCH` with it (pins §1.6 as known, not overlooked) |
| M7 | `tamper_cases.json` | unchained row (NULL digests) → `CHAIN_UNCHAINED_ROW`; passes only with `allow_unchained=True` |
| M8 | `tamper_cases.json` | reordering keys inside `payload_json`'s stored TEXT → `CHAIN_HASH_MISMATCH` (proves stored bytes, not parsed semantics, are covered) |
| M9 | §2.1 DDL, executed | the trigger DDL is valid SQLite; `UPDATE` and `DELETE` each raise `sqlite3.IntegrityError` whose message contains the named error; the aborted statement left the row unchanged |
| M10 | §2.1 DDL, executed | `INSERT` still succeeds under both triggers (no over-blocking) |
| M11 | `journal_rebuilt.json` | §3.1: the same journal after a simulated `DROP TABLE`/copy/re-chain verifies to the **same tip** as the original — the rebuild rule is deterministic, and `SELECT *` without explicit columns is detectable by the M1 digests |

M9/M10 execute §2.1's DDL against an in-memory table with the same shape as
`migrations.py:124-139`; they do not modify `src/` and do not add a
migration.

**Honest limit of the fixture proof.** The frozen digests were generated by
the same reference implementation the tests use, so M1 pins *drift*, not
the correctness of Python's SHA-256 or of the spec's design choices; M1b is
the independent cross-check that catches a spec the document cannot actually
express. Neither proves the design is *right*, only that it is unambiguous
and mechanically checkable — which is the whole claim being made.

---

## 7. Not claimed / open questions

**Not claimed.** A verified chain is not authority. It is not scientific
reproducibility, not validity, not source admissibility, and not proof of
authorship. §1.6's three gaps are real and stated. §2 raises the cost of
tampering; it does not prevent it.

**Open questions (deliberate, for the implementing slice):**

- **Q1 — Backfill vs. forward-only chain origin.** §3.3 backfills so the
  whole journal is covered. The alternative (chain starts at the first
  post-migration row, pre-existing rows stay `NULL`) is strictly
  append-only and needs no backfill `UPDATE`, at the cost of leaving all
  prior history outside the chain. A cheaper forward-only variant gets a
  smaller coverage claim, and that trade must be made explicitly rather
  than by default.
- **Q2 — Verification trigger point.** Nothing in this design calls
  verify. Candidates: CLI (`cli.py` has `integrity_check`,
  `database.py`), a backup/snapshot path (`persistence/backup.py`), or
  explicit-only. Wiring it into a startup path changes the failure mode
  of an old journal from "tamper-evident" to "refuses to boot".
- **Q3 — Re-chain cost bound** for large journals (this design assumes a
  single transaction; the largest observed test journals are small, and no
  production journal size is recorded).
- **Q4 — `_json_dumps` canonicality.** The stored TEXT is currently
  `json.dumps(..., sort_keys=True, ensure_ascii=False)` with default
  separators (`repositories.py:85-88`), which is *not* the compact form
  `canonical_json` produces. §1.3 hashes stored bytes, so this is harmless
  today — but it means the same semantic payload has more than one valid
  byte encoding, each with a different digest. If that is ever tightened,
  it is a chain-version change, not an edit.

---

## 8. References

- `src/hermes/persistence/migrations.py:20` — `SUPPORTED_VERSION = 20`
- `src/hermes/persistence/migrations.py:124-139` — `events` DDL, byte-exact
  4 KiB CHECK at `:137`
- `src/hermes/persistence/migrations.py:293-340` — `_migrate_2_to_3`
  rebuild precedent (`:308`, `:309`, `:327`)
- `src/hermes/persistence/migrations.py:1193-1223` — `_migrate_19_to_20`
  append-only `ADD COLUMN` precedent (`:1215-1217`)
- `src/hermes/persistence/migrations.py:729-777` (`:763-764`) — the unique
  index on `events`; `:873-1001` (`:967`) — reads `events`
- `src/hermes/persistence/migrations.py:1226-1247` — migration registry;
  `:1250-1273` — `migrate_to_latest` (`BEGIN` per migration at `:1265`)
- `src/hermes/persistence/repositories.py:85-88` — `_json_dumps`
- `src/hermes/persistence/repositories.py:97-127` — `_append_event_to_db`,
  the single writer (`:122` INSERT)
- `src/hermes/persistence/event_validation.py:23`, `:74` — 4 KiB cap
- `src/hermes/research/programs.py:354-379`, `:381-384`, `:387-393` —
  `_canonicalize`, `canonical_json`, `sha256_hex`
- `src/hermes/core/events.py:15`, `:120-139` — `EventType`, `EventRecord`
- `docs/idr/hermes_v6_authority_evidence_map.md:19` — G1 identity /
  provenance split
- `docs/idr/IDR-010.md` — forward-only migration mechanism
- `docs/idr/IDR-013.md` — transition/event atomicity

## Revisions

None (design draft).

## Addendum — stage-S implementation status (TAMPER-1, 2026-10-18)

**Landed:** the §2.1 triggers, by migration 20 → 21 (`_migrate_20_to_21`),
plus the §3.1 rule-2 re-creation inside the `_migrate_2_to_3` rebuild (the
rebuild's `DROP TABLE` destroys triggers, so it re-forms them last). The
triggers refuse in-DB `UPDATE`/`DELETE` with `sqlite3.IntegrityError`
carrying `HERMES_JOURNAL_IMMUTABLE_UPDATE` / `HERMES_JOURNAL_IMMUTABLE_DELETE`;
`INSERT` is untouched. The chain (§1), the §3.3 chain migration, and §4
signatures are not implemented.

**Residual honesty.** The triggers deter in-DB `UPDATE`/`DELETE` only.
Replacing the database file wholesale, or `DROP TRIGGER` followed by a
rewrite, is **not covered** — neither raises the named errors. Detecting
those is TAMPER-2 (hash chain + re-chain tool), which remains
chartered-deferred — deferred, not dropped.

## Addendum — TAMPER-2 design decisions (2026-10-23)

Phase-1 design note for TAMPER-2. Decisions only: no column, trigger,
migration or `src/` change exists at this revision, so the Status paragraph
above remains accurate. What follows is binding on the implementing slice.

### A1. Chain version

```
CHAIN_VERSION = "hermes.journal.chain.v1"
GENESIS       = sha256_hex("hermes.journal.chain.v1/genesis")
              = 1cc5f8a885ca75f3edb337cef85b5f7835283725e46f72e629e225dbbcd46ba2
```

frozen, and matching `tests/fixtures/tamper_evident/journal_clean.json`.

v1 **is** the §1.4 preimage: the 11-field list of §1.3, the
`h(n-1) + "\n" + body(n)` concatenation, SHA-256, lowercase hex. Any change
to it — a field added or removed, a different separator, a different digest,
a different genesis domain string — is a **new chain version**
(`hermes.journal.chain.v2`), never an in-place edit. v1 rows must stay
verifiable under v1 rules forever. The version is a property of the journal
as a whole, not of a row: there is no per-row version column, a bump is a
schema-version step, and a journal is only ever verified under the version
its schema declares. A bump therefore ships as one migration that re-chains
every row in that same transaction.

### A2. Q1 — chain origin: BACKFILL (ruled)

Every pre-existing row is chained, in `event_id` ascending order, from
`GENESIS`. Coverage claim: the whole journal as stored at migration time.

The load-bearing consequence: **the backfill is an `UPDATE events`**, and
the triggers shipped by 20 → 21 abort every `UPDATE events` with
`HERMES_JOURNAL_IMMUTABLE_UPDATE`. A backfill written as the obvious
`UPDATE ... WHERE chain_hash IS NULL` cannot work — the migration that adds
the chain is blocked by the triggers that are already there. The migration
must therefore open a `DROP TRIGGER` window **inside its own transaction**:
drop both, add the columns, backfill, recreate both last (exact order in
A7.1).

That window cannot leak. SQLite DDL is transactional, so a failure anywhere
in the backfill rolls the drop back and both triggers return with the rest
of the transaction; there is no committed state in which the journal is
mutable.

Rejected — **forward-only** (pre-existing rows stay `NULL`): no `UPDATE`
needed, but it permanently marks every legacy row `CHAIN_UNCHAINED_ROW`, so
verify is useless on exactly the journals that most need it, and the
coverage claim degrades to "everything after an unrecorded date". Rejected —
**hybrid** (chain from the first post-migration row, declare the past out of
scope) for the same reason.

### A3. Q2 — verification point: EXPLICIT + CLI only (ruled)

Nothing in `src/` verifies the chain automatically. No startup path, no
migration, no repository read, no gateway step, no backup/snapshot hook. The
one entry point is the CLI (A7.5).

Why never a startup path:

- Startup already runs migrations. A chain check there converts a chain
  defect into a failure to boot: an old journal, a half-migrated database,
  or any fixture DB whose 45 raw `INSERT INTO events` sites left
  `chain_hash` NULL would take the process down. "Tamper-evident" would
  degrade to "unbootable", and the operator could not distinguish a chain
  finding from a broken install.
- A chain defect is evidence for a human, not a control-flow input. The
  certified invariant is that determinism owns control; a hash comparison
  must not decide a transition, and must not decide whether the process
  starts.
- Verification must stay off every read path, or the 24 tamper sites and
  their consumer tests would begin failing for a new reason and hide the
  fail-closed behaviour they exist to prove.

Verify is read-only and exits non-zero on any defect.

### A4. Q3 — re-chain cost bound

The largest frozen fixture is 3 rows; a 3-row re-chain is below timer
resolution (< 1 ms). The bound below is **measured** on the implementation
host with the reference implementation
(`tests/tamper_evident_reference.py`) over a synthetic journal of
~200-byte payloads, `event_id` 1..n:

| n | hashing only | full SQLite re-chain |
|---|---|---|
| 1,000 | 0.011 s | — |
| 10,000 | 0.108 s | 0.146 s |
| 50,000 | 0.563 s | — |

The full figure is the whole operation: `BEGIN`, drop both triggers, n
single-row `UPDATE`s, recreate both triggers, `COMMIT`. Throughput is ~69k
rows/s and linear (~92k rows/s hashing alone), so the bound is **~15 s per
1,000,000 rows**. No production journal size is recorded anywhere in the
repo, so the 1M figure is an extrapolation from a measured 10k, not a
measurement of a real journal.

Posture: **one transaction for the whole re-chain.** Consequences the tool
must respect:

- The write lock is held for the entire run. At ~350k rows the run exceeds
  the 5 s `busy_timeout`, so re-chaining is a quiesced-database operation,
  never something run beside a live controller.
- Rows are read on one cursor in `event_id` order and updated on another;
  only `prev_hash`/`chain_hash` change, so the scan order is stable and
  memory is O(1) in journal size.
- A crash mid-run rolls back to the previous chain and both triggers; the
  tool is never half-applied.

### A5. Q4 — `_json_dumps` canonicality

`_json_dumps` (`repositories.py:85-88`) is
`json.dumps(..., sort_keys=True, ensure_ascii=False)` with default
separators, so a stored payload reads `{"a": 1, "b": 2}` where
`canonical_json` would produce `{"a":1,"b":2}`. §1.3 hashes the **stored
bytes**, so this is harmless today: the digest covers whichever encoding is
actually on disk, and no row is ambiguous about its own bytes. For v1 there
is no "correct" payload encoding beyond "what is stored".

Tightening it is a **chain-version** change, not an edit. The precise
reason: v1 verification would still pass, because each row hashes its own
bytes — but §4 precondition 4 requires the canonical-bytes contract to be
frozen *and shared with an external verifier*. Changing the encoder changes
which byte string counts as *the* encoding of a payload, so "same payload,
same digest" becomes version-dependent, and a verifier that canonicalizes
payloads itself instead of hashing stored bytes would disagree. Any
tightening therefore ships as v2, with its own migration and a full
re-chain.

One consequence of `ensure_ascii=False` is recorded because it is a real
failure mode: non-ASCII is stored as UTF-8 text and the preimage is UTF-8
encoded, so a lone surrogate reaching the DB by a file-level edit makes
encoding raise — reported as `CHAIN_UNENCODABLE_ROW`, never skipped.

### A6. The stage-S residual, honestly

TAMPER-1 named `DROP TRIGGER` and DB-file swap as not covered. TAMPER-2
covers what can honestly be covered and refuses to over-claim the rest.

**`DROP TRIGGER`** is invisible to row-by-row hashing: dropping a trigger
changes no row byte, so no chain walk can see it. It becomes a **named
structural finding**, `CHAIN_TRIGGERS_MISSING`, produced by
`missing_append_only_triggers(conn)` reading `sqlite_master` for both
trigger names, and checked *before* the row walk (a missing refusal layer is
a precondition, not a row defect). Honest limit: this detects **absence**
only. A trigger dropped, used, and recreated identically is
indistinguishable from one that was never dropped; the chain detects the
*row* mutation the window allowed, and only an anchor makes the window
itself suspicious.

**DB-file swap.** Replacing the database wholesale with a self-consistent,
fully re-chained file is **undetectable without an out-of-band anchor**.
That is the entire content of `anchor=`, and nothing more: the caller
supplies a 64-hex tip digest obtained through a channel the database owner
cannot rewrite, and a mismatch is `CHAIN_TIP_MISMATCH`. This design ships
**no sidecar anchor file, no signature, no MAC, no key material**; an anchor
store is P2-4 and explicitly out of scope. Until one exists, the honest
statement is: a swapped file verifies.

**Still not caught**, unchanged from §1.6:

- **Tail truncation** — deleting the last *k* rows leaves a shorter,
  self-consistent chain. Only `anchor` detects it.
- **Full re-chain** — an actor with DDL rights recomputes every row and
  produces a valid chain. More hashing cannot fix this; only an anchor can.
- **`created_at` rewrite** — excluded from the preimage by §1.1, by design.

Claims discipline, restated because it is the thing most likely to be lost
in implementation: a green chain is **never** authority, **never**
scientific validity, **never** reproducibility, **never** authorship. It is
a mechanically true statement about the bytes in one file.

### A7. Implementation surface

#### A7.1 Migration `22 → 23`

`_migrate_22_to_23`, registered last, `SUPPORTED_VERSION = 23`. Statement
order inside the transaction opened by `migrate_to_latest`
(`migrations.py:1358`) — this order is mandatory:

1. `DROP TRIGGER IF EXISTS trg_events_append_only_update`
2. `DROP TRIGGER IF EXISTS trg_events_append_only_delete`
3. `ALTER TABLE events ADD COLUMN prev_hash TEXT`
4. `ALTER TABLE events ADD COLUMN chain_hash TEXT`
5. Backfill: every row in `event_id` ascending from `GENESIS`, recomputed
   from the row's own 11 stored fields — never copied.
6. Re-create **both** triggers from the §2.1 DDL, **last**.

Steps 3-4 are guarded by `pragma_table_info`, the `schema_version` row is
written only when version 23 is absent, and both triggers are dropped and
recreated unconditionally, so the step is **idempotent** — and it must be,
because the re-chain (A7.5) re-executes this body on an already-v23
database. The implementing slice must pin that idempotency with a test that
runs `_migrate_22_to_23` twice and still verifies `CHAIN_OK`. No table
rebuild, no `SELECT *` copy, no touch of `created_at` (`ADD COLUMN` does
not rewrite rows, so it is byte-identical before and after), and no
transaction-control call of its own — the runner owns it.

#### A7.2 Writer

`_append_event_to_db` (`repositories.py:97`) computes and inserts both
digests inside the caller's already-open transaction. Tip read, id
reservation and `INSERT` share that one transaction; the read is never
hoisted above acquisition.

- **Tip** = the `chain_hash` of the **highest `event_id` row carrying a
  non-NULL `chain_hash`**, or `GENESIS` when there is none. Not "the last
  row": 45 raw `INSERT INTO events` fixture sites bypass the writer and
  leave `chain_hash` NULL, and a last-row read would chain onto NULL and
  make every later append unverifiable. Unchained rows stay visible as
  `CHAIN_UNCHAINED_ROW` — never absorbed, never silently bridged. The tip
  rule exists so appends keep working; verification still stops at the first
  hole.
- **`event_id` reservation.** `event_id` is field 1 of the preimage but is
  assigned at `INSERT`. The writer reserves it first, from the AUTOINCREMENT
  high-water mark (`sqlite_sequence.seq` for `events`, falling back to
  `MAX(event_id)+1`), and inserts it explicitly. Reservation, tip read and
  `INSERT` share the caller's transaction, and every caller already holds a
  write transaction before invoking the writer (`BEGIN IMMEDIATE` in the
  repository owners, `BEGIN` in `append_transactional`), so SQLite's
  single-writer rule leaves exactly one tip and one next id at a time.

The deferred-`BEGIN` caller is the weak one and is stated plainly: with
`BEGIN` in `append_transactional` the write lock is taken at the `INSERT`,
not at the tip read, so if another writer commits between the tip read and
the write, SQLite fails the lock upgrade with `SQLITE_BUSY` and the append
rolls back. The writer must never fork the chain to survive that: a forked
chain — two rows sharing a `prev_hash` — is `CHAIN_PREV_MISMATCH` for the
verifier, not a silent branch.

#### A7.3 Verification API

New module `src/hermes/persistence/journal_chain.py`, importing
`canonical_json` and `sha256_hex` from `hermes.research.programs` — one
canonicalizer authority, never a local copy.

```
verify_journal_chain(rows, *, anchor=None, allow_unchained=False) -> dict
    # pure; rows are mappings or sqlite3.Row, supplied in event_id order
verify_journal(conn, *, anchor=None) -> dict
    # DB-facing: structural check first, then the walk over
    # SELECT ... FROM events ORDER BY event_id
missing_append_only_triggers(conn) -> tuple[str, ...]
```

Result keys: `ok, code, event_id, expected, actual, genesis, tip` (§1.5),
plus `chain_version` and `findings: tuple[str, ...]` on the DB-facing
wrapper. Codes, exact and closed: `CHAIN_OK`,
`CHAIN_EVENT_ID_OUT_OF_ORDER`, `CHAIN_UNCHAINED_ROW`, `CHAIN_PREV_MISMATCH`,
`CHAIN_HASH_MISMATCH`, `CHAIN_UNENCODABLE_ROW`, `CHAIN_TIP_MISMATCH`, and
`CHAIN_TRIGGERS_MISSING` (structural; the DB wrapper only — the pure walker
never returns it, so the M1-M11 fixture contract is untouched).

Stop at the first defect. Structural findings precede the walk:
`CHAIN_TRIGGERS_MISSING` outranks any row defect, because with the refusal
layer gone the row-level finding is not the most important one. `ok` is true
only for `CHAIN_OK` with an empty `findings`.

#### A7.4 Re-chain

```
rechain_journal(conn) -> {rows, old_tip, new_tip, changed}
```

Drop both triggers, recompute every row in `event_id` order from `GENESIS`,
recreate both triggers, one transaction. It issues no control call of its
own: it asserts an open transaction and refuses otherwise. That transaction
is the migration runner's, never its own: `journal rechain` reaches this
body through `migrate_to_latest(conn, start_version=22)`, which opens
`BEGIN` at `migrations.py:1358` and commits at `:1361`, so
`rechain_journal` is the body and the runner is the owner. `changed` counts
rows whose recomputed pair differs from what was stored; `old_tip` is the
pre-existing tip or `None`.

Its docstring and the CLI output must say the sharpest thing in this design:
**a re-chain blesses the current bytes.** After tampering, re-chaining
produces a journal that verifies and no longer records that anything
happened. It is a deliberate act for a known-good journal (a rebuild, an
import, an encoding migration), never a repair, and never a response to a
red verify.

#### A7.5 CLI

On the existing `argparse` structure (`cli.py:783`), a `journal` group with
two subcommands, both taking `--db` (default: the configured
`cfg.sqlite.database_path`) and an optional `--anchor <64-hex>`:

- `hermes journal verify [--db PATH] [--anchor HEX] [--json]` — read-only;
  prints the code, `event_id`, expected/actual, tip and any structural
  finding; exits 1 on any defect (including `CHAIN_TRIGGERS_MISSING`), 0
  only on `CHAIN_OK` with no findings. `allow_unchained` is deliberately not
  exposed: the CLI verifier is strict.
- `hermes journal rechain [--db PATH] [--anchor HEX] --confirm-rechain` —
  refuses without the flag; prints `old_tip`, `new_tip` and the row count.
  With `--anchor` it verifies *before* re-chaining and **refuses** when the
  current tip does not match, because re-chaining a journal that has already
  diverged from the out-of-band digest would launder exactly the case the
  anchor exists to catch.

Transaction posture, stated because the census is frozen (A8): the re-chain
rides the migration runner's existing `BEGIN`/`COMMIT`/`ROLLBACK`
(`migrations.py:1358-1363`) by re-applying step 22 rather than adding an
owner. That requires one runner change, stated exactly:
`migrate_to_latest` gains an optional `start_version: int | None = None`.
`None` preserves today's behaviour exactly — `current = _get_version(conn)`
at `:1350` — and a supplied value is used as the loop start in place of it,
so `migrate_to_latest(conn, start_version=22)` on a v23 database runs
`_MIGRATIONS[22]` and nothing else, opening the transaction the current
signature never opens on that database. It is an internal maintenance hook
for this one caller, not a public migration API: no other `src/` path
passes it, and startup keeps calling the no-argument form.

Why this cannot move the census: the parameter adds **no** `BEGIN`,
`COMMIT` or `ROLLBACK` statement of its own — it only changes the first
argument of the `range()` at `:1356`, and the runner's existing three calls
at `:1358-1363` are reused verbatim — so the frozen figures (124 / 28 / 19
/ 1 / 15) cannot move. The alternative, a dedicated owner opening its own
transaction around `rechain_journal`, was rejected precisely because it
would add +2 or +3 transaction-control calls and +1 owner, and A8 forbids
both.

`journal rechain` must refuse unless
`_get_version(conn) == SUPPORTED_VERSION`, because on a v22 database
`start_version=22` would run a **migration**, not a re-chain — a different
operation with a different meaning. Both refusals are unconditional and
neither has an override: a database not at `SUPPORTED_VERSION` is refused
("run migrations first"), and a missing `--confirm-rechain` is refused.

#### A7.6 What the implementing slice must prove

- Migrate a populated v22 database: `verify_journal` is `CHAIN_OK`,
  `created_at` is byte-identical, and `UPDATE`/`DELETE` raise the named
  errors again.
- A fresh append after the migration chains onto the backfilled tip.
- An append after a NULL-chained row chains onto the last non-NULL tip,
  and that row still reports `CHAIN_UNCHAINED_ROW`.
- Drop one trigger: `CHAIN_TRIGGERS_MISSING`; restore: `CHAIN_OK`.
- Re-chain a tampered journal: `changed > 0`, new tip, then `CHAIN_OK`.
- Re-chain with a stale `--anchor`: refuses, file untouched.
- The runner accepts `start_version`, and a re-chain on a v23 database runs
  exactly one migration body — `_migrate_22_to_23`, once — inside one
  transaction.
- `migrate_to_latest()` with no arguments behaves byte-identically to
  before: the existing runner tests pass unchanged as the regression test.
- The 24 tamper sites still refuse-then-force, and no production read path
  verifies the chain.

### A8. Census and B4

- **Transaction census stays 124 / 28 / 19 / 1 / 15.** No new
  transaction-control call: the migration rides the runner's existing one
  and the re-chain rides the migration. The `start_version` parameter
  (A7.5) is a loop bound, not a transaction — it adds no call site, so the
  five figures are untouched by it. A dedicated maintenance owner was
  considered and rejected — +2 or +3 calls and +1 owner (126 / 29 or
  127 / 29), which the charter forbids. `database.acquire_writer_lock` was
  considered and rejected: `tests/test_hygiene_structural.py:106` pins it
  as having zero `src/` callers.
- **B4.** `docs/idr/TAMPER-EVIDENT-JOURNAL.md` is not in the governed
  corpus. The 12 are `AGENTS.md`, `docs/API.md`, `docs/ARCHITECTURE.md`,
  `docs/STATE.md` and `docs/idr/IDR-018/023/024/025/026/027/028/036.md`
  (`GOVERNED_CORPUS_REFS`, `src/hermes/research/corpus.py:118`). Editing
  this file is therefore not expected to move any B4 digest, and the
  implementing phase must still run `tests/test_b4_ref_graphs.py` and prove
  it stays 24.
