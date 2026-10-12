# ResearchSourceProvider — Step 6 — Third-Gate Hostile Design Review
## P0-REMEDIATED SURFACES: THE `observation_hash` CONTRACT + THE DISPATCH-THREADED HANDLER

**Date:** 2026-08-14 · **HEAD:** `4dd455b` (the step-6 pre-implementation gate package)
**Status: FOLDED IN (2026-08-14).** All nine findings reproduced against the
design records + shipped code; dispositions recorded below; the fold-in is
complete in the design record §3/§5/§6/§7/§10/§12/§13 and the remediation
record §E/§F/§H/§I. Design-only — no code, per the gate (§25 still stands).
**Scope (per the gate):** attack ONLY the new `observation_hash` three-check
contract and the dispatch-threaded handler surfaces (`handler(task, fenced,
repos)` / `SourceTaskExecutionContext`, the per-tick fence wiring) for the same
bypass and silent-failure classes. No step-6 orchestration code exists yet; the
design records are the attack surface.

**Authorities inspected:**
`hermes_researchsourceprovider_step6_design_remediation.md` (§C/§E/§F/§H),
`hermes_researchsourceprovider_step6_orchestration_design.md` (§3 SD-01/SD2-03,
§5 D3, §6/§7, §10, §12 D10, §13), `src/hermes/tools/research_sources.py`
(`content_hash_of_search_result`, `observation_hash_of_search_result`,
`make_search_result_id`), `src/hermes/research/controller.py`
(`_FencedConnection` 58–170, `_refresh_fence` 306, `_assert_lock_valid` 313,
`_acquire_lock`), `src/hermes/persistence/repositories.py`
(`record_extraction` 1354 — the 3c one-shot precedent), `src/hermes/research/
programs.py` (`canonical_json` 325), `tests/test_research_sources.py`
(the P0 + observation-hash fixtures, `_independent_observation_hash_of`).
No shipped path uses `conn.cursor()` (grep) — the fence-leak finding below is
LATENT, not currently exploited.

---

## Verdict summary

| ID | Severity | Surface | Finding |
|---|---|---|---|
| OB-01 | **P1** | observation_hash · one-shot | The hash-SET membership is unpinned: outcome-level divergence (aggregate/notes/fetch-log) is invisible to a per-result-only comparison — and a naive "all hashes" reading re-endangers the P0 crash-retry at the FETCH layer |
| OB-02 | **P2** | observation_hash · reuse | The idempotent-reuse branch never re-verifies the PERSISTED row's observation_hash before reusing — a tampered observation field is silently re-adopted, caught only later at dereference |
| OB-03 | **P2** | observation_hash · scope | The contract's tamper claim is record-metadata-scoped; row-level columns (task_id/project_id/artifact_type) and the outcome-level metadata are covered by NO hash — the three-check text must state the scope or it over-claims |
| OB-04 | **P3** | observation_hash · admission | "Forged hash → rejection" is inconsistent-forge-only; a self-consistent forge (record + both hashes recomputed) is undetectable by re-derivation — say so, or the claim implies a MAC that doesn't exist |
| OB-05 | **P3** | observation_hash · round-trip | The OQ-1 lossless round-trip needs the tuple/list coercion contract in the resolver; a naive `SearchResult(**parsed)` silently stores `authors` as a list — observation_hash survives (same bytes), dataclass equality does not |
| HD-01 | **P1** | dispatch · fence surface | `_FencedConnection.__getattr__` delegates `cursor()`/`commit()`/`rollback()` to the RAW connection — a handler (or future repo helper) can write or commit without ever running `_assert_lock_valid` |
| HD-02 | **P1** | dispatch · signature | The two authoritative records contradict on the dispatch signature: §3 pins bare `handler(task, fenced, repos)`; remediation §H pins the typed bundle "not the bare (task, fenced, repos)" — and §H is NOT in the remediation's supersession list |
| HD-03 | **P2** | dispatch · per-tick bundle | The SD2-03 negative must assert the REPOS' connection IS the fenced one (identity check), not only that the factory took no conn — the fenced conn's `__getattr__` is the raw conn (HD-01) |
| HD-04 | **P3** | dispatch · task snapshot | The `task: dict` read-only snapshot's capture point is unpinned; pin that it is taken at dispatch and the handler never re-reads status (the write path's in-txn binding re-check is the authoritative one) |

**Verdict: MERGE WITH REMEDIATION (third round).** The observation-hash
three-check contract is sound in its three distinct checks; the fence mechanism
itself is sound (the LIVE-generation check closes the SD-01 stale-capture
class). What remains are precision pins: OB-01 is the sharpest — it re-opens
the P0 crash-retry invariant at the FETCH layer if the one-shot set is defined
carelessly; HD-01/HD-02 are the handler-surface pins that decide whether the
SD2-03 "no raw conn" guarantee is structural or rhetorical. Zero architectural
violations: no second authority, no new write path, no evidence promotion
surface introduced by any finding. Implementation per the twice-folded record
stays blocked until these fold in.

---

## 1. The observation_hash contract — findings

The contract (remediation §E) has three distinct checks: **(1) Admission** —
`_validate_identities` recomputes `content_hash` (semantic) and stores
`observation_hash` (full-record, minus `content_hash`) in the artifact
metadata; **(2) Idempotent reuse** — the one-shot is the SEMANTIC hash-SET
comparison only; **(3) Dereference/load** — the resolver re-derives BOTH from
the persisted row and fails loudly on mismatch. The three-check split itself is
correct — this gate attacks the seams between them.

### OB-01 (P1) — The hash-SET membership is unpinned; outcome-level divergence is invisible, and a naive reading re-breaks P0 at the FETCH layer

The one-shot (design §5 D3-6, SD2-02) says: "prior artifact content hashes by
task vs the new outcome's hashes — EQUAL → idempotent reuse, DIFFERENT →
refusal." It never pins WHICH artifacts are in the set. Three readings, three
defects:

**(a) Per-result-only → outcome-level divergence is silently reused.** The
`source_result` hashes are the SEMANTIC hashes (§C), and `reconciliation` is
explicitly EXCLUDED from the semantic preimage — observation. So a crash-retry
whose per-result bibliographic fields are identical but whose walk genuinely
produced a different OUTCOME (aggregate `COMPLETE` → `SHORTFALL`/`UNAVAILABLE`,
or a materially different notes tuple — a source dropped by dedup, a
MALFORMED_ROW note) compares EQUAL at the per-result level and silently REUSES
the first run's `source_search` record — including its aggregate, notes, and
request-log facts. The recovery matrix §F's "identical complete outcome" cell
is then defined over an unpinned set. The gate's own §5 requirement — "the
crash-retry one-shot must see identical semantic sources as identical" — was
about SEMANTIC SOURCES, not about silently blessing a different AGGREGATE
verdict. This is exactly the silent-failure class the gate exists for: a retry
that would have shortfalled re-adopts a COMPLETE outcome.

**(b) "All hashes" → the P0 invariant re-breaks at the FETCH layer.** If the
set is naively "every persisted hash by task," the fetch outcome's
`FetchLogEntry` stream (F6 `attempts` / `attempt_verdicts` /
`access_timestamp_utc`) is observation metadata that changes on EVERY retry —
a crash-retry with identical payload bytes would compare DIVERGENT → false
one-shot refusal → FAILED terminal. That is the P0 defect resurrected in a
second place.

**(c) The outcome-level hash is undefined.** §G gives `source_search` a
"semantic outcome hash" — no helper exists, no preimage is named. The D10
fixtures 17/21 ("identical content → idempotent reuse") can pass under reading
(a) or (b) without ever being pinned to the outcome record.

**Pin (binding on implementation):** the one-shot SET is exactly:
1. the per-result SEMANTIC content hashes (`content_hash_of_search_result`),
   PLUS
2. the outcome-level record's hash — a NEW deterministic helper, preimage
   = canonical(outcome_kind, aggregate, notes, request-log-facts hash)
   (observation timestamps/cursor chain excluded — the request-log *facts* are
   the stable content, the timestamps are observation).
For FETCH: the SET = the per-source payload content hashes (`sha256(raw_bytes)`)
+ the NoFullText evidence records' hashes; the `FetchLogEntry` stream and all
`attempts`/`attempt_verdicts`/timestamps are EXCLUDED (observation). A changed
aggregate (COMPLETE→SHORTFALL, or a fetch that now succeeds where it failed)
must be DIVERGENT → refusal; identical payloads + changed log metadata must be
IDENTICAL → reuse. Fixtures: outcome-level-divergence refusal probe +
fetch retry with changed attempt_verdicts stays idempotent.

### OB-02 (P2) — The reuse branch never re-verifies the persisted row's observation_hash before reusing

SD-04 pins the reuse verify as `sha256(raw_bytes) == content_hash` (fetch
payloads). For `source_result` rows the analog is the semantic hash equality —
which, by construction, is INSENSITIVE to observation tampering (that is the
whole point of the P0 split). A row whose timestamp/counts were edited
recomputes the same semantic hash → the reuse path re-adopts the tampered row;
check 3 only catches it LATER, at dereference. The tamper is real but deferred
to a different authority, and the reuse path — the path that runs on every
crash-recovery — blesses it silently.

**Pin:** the reuse branch runs check 3 against the PERSISTED row before
reusing: reconstruct the record from the row's metadata, recompute BOTH hashes,
compare against the row's `content_hash` column AND the metadata's stored
`observation_hash`. The RETRY's own observation_hash is never compared (that
stays IDENTICAL by design — OB-01(b)); the PERSISTED row must pass its own
re-verification. Fixture: a semantically-identical-but-observation-tampered
row fails the reuse (typed integrity error), not just the later dereference.

### OB-03 (P2) — The tamper claim is record-scoped; the contract text must say so

§E(3) says the observation_hash "catches an observation-field tamper … that
content_hash alone CANNOT detect." True — for the RECORD's metadata JSON. But
the artifact row's OTHER columns — `task_id`, `project_id`, `artifact_type`,
`producer` — and the outcome-level record's aggregate/notes are covered by NO
hash at all. A forge that rewrites a row's task binding (the §9/§17
"reused artifact with incorrect task provenance" class) passes observation_hash
by construction. That is the documented model (binding integrity = the in-txn
task-binding re-check + edges UNIQUE + the resolver's project-scoped lookup,
never a hash) — but the three-check contract must state the scope explicitly,
or fixture 21's "metadata/data mismatch" claim reads as covering row-level
forgery it cannot.

**Pin (text):** "observation_hash is RECORD-metadata integrity only; row-level
binding columns are protected by the in-transaction task-binding re-check and
the §14 edge UNIQUEs, never by any hash." No behavior change; scope honesty.

### OB-04 (P3) — "Forged hash → rejection" is inconsistent-forge-only; say so

`observation_hash` is a public deterministic function — no keyed MAC exists
anywhere in this slice. Re-derivation rejects a hash that does not match the
record; it cannot detect an adversarial writer who recomputes BOTH hashes for a
tampered record (a self-consistent forge passes `_validate_identities` by
definition). §E(1)'s "a forged/mismatched hash → typed rejection" conflates
"forged" with "mismatched." The authenticity defense is the authority boundary
(only the deterministic walk produces records; the gateway admits; the write
path validates), not the hash.

**Pin (text):** identity re-derivation detects corruption and INCONSISTENT
forgeries; a self-consistent re-hash is out of the deterministic-code threat
model and is prevented by the single-producer boundary, not by the hash.

### OB-05 (P3) — The lossless round-trip needs the tuple/list coercion contract

OQ-1(b) pins "the persisted metadata reconstructs the SearchResult exactly
(SearchResult' == SearchResult)." `authors: tuple[str, ...]` — JSON round-trip
yields a LIST, and dataclasses do not coerce: a naive `SearchResult(**parsed)`
silently stores a list. The observation_hash SURVIVES (canonical_json
serializes list and tuple to identical bytes — verified against
`canonical_json`, `programs.py:325`), but the dataclass EQUALITY (the §10/§I
round-trip contract) and any downstream consumer reading `result.authors` as a
tuple break. The shipped round-trip test coerces manually
(`test_content_hash_recomputable_after_roundtrip`); the ORCHESTRATION
resolver's reconstruction contract is unpinned.

**Pin:** the resolver's reconstruction is specified: `authors` coerced to
tuple; `identifiers`/`provenance`/`request_params_redacted` as dicts;
`None`-preservation for `cursor_key`/`year`/`abstract_sha256`/
`valid_negative_for`. Fixture: persist → resolve → `SearchResult' == SearchResult`
(on BOTH identity and observation fields) AND `observation_hash` re-verifies.

---

## 2. The dispatch-threaded handler surfaces — findings

### HD-01 (P1) — `_FencedConnection.__getattr__` leaks the raw connection: `cursor()`/`commit()`/`rollback()` bypass the generation check

`_FencedConnection` (controller.py:58) intercepts exactly three entry points:
`execute`, `executemany`, `executescript` (rejected). Everything else falls
through `__getattr__` to the RAW sqlite3 connection. Consequences:

- **`fenced.cursor()`** → the raw connection's cursor → `cursor.execute("INSERT
  ...")` performs a write that NEVER runs `_assert_lock_valid`. A stale
  controller (or a handler that holds a stale bundle) can mutate the DB
  through a cursor without ever tripping the fence — the exact double-write
  class ADV-02 exists to exclude, reachable through the very capability the
  step-6 bundle hands the handler.
- **`fenced.commit()` / `fenced.rollback()`** → the raw conn's transaction
  controls. A handler calling `fenced.commit()` mid-`_commit_source_outcome`
  commits the repository's open transaction early → half-state (rows committed,
  edges not — the two-transaction model's atomicity destroyed); a mid-tick
  `rollback()` silently discards a repository's uncommitted work.

No shipped path uses `.cursor()` (grep) and the shipped repositories call
`self._conn.execute` directly, so this is LATENT today — but the step-6 design
hands this exact object to handler code, and the SD2-03 "no raw conn in scope"
guarantee is only structural if the fence's delegation surface is closed.

**Pin:** `_FencedConnection` rejects `cursor` (raise, like `executescript`),
and `commit`/`rollback` are either disallowed on the fenced surface (the
repositories own transactions) or wrapped to raise loudly; a D10 fixture
asserts `fenced.cursor()` cannot write (a cursor attempt raises, never lands a
row) and that the repos bundle exposes no conn attribute.

### HD-02 (P1) — The two authoritative records contradict on the dispatch signature

- Design record §3 (SD-01 fold-in): "the pinned contract: … handler(task,
  self._fenced, self._repos)" — a BARE tuple carrying the fenced conn.
- Remediation §H: "Typed capability bundle (not the bare (task, fenced,
  repos))" — `SourceTaskExecutionContext`, "no raw connection."
- Remediation §A supersession list names §C/§D/§F only — §H is NOT in it, and
  the design record §3 was never amended. Both documents claim authority over
  the exact surface this gate attacks.

This is not cosmetic. With the bare tuple, the handler receives the fenced
conn DIRECTLY — and per HD-01, the fenced conn's `__getattr__` IS the raw
connection, so the SD2-03 "a raw conn is refused at wiring, never runs"
guarantee is void in the bare-tuple form. The typed bundle is what makes
"no raw conn in scope" structural: the bundle has exactly the two write
methods and the provider machinery, nothing else.

**Pin:** supersede §3's dispatch line with the typed bundle (add §H to the
remediation's supersession list), and the D10 SD2-03 fixture asserts the BUNDLE
surface: no `conn` attribute on the bundle, and the repos inside expose no
connection either.

### HD-03 (P2) — The SD2-03 negative must pin the repos' connection identity

SD2-03's wiring negative tests the FACTORY (a handler factory handed a raw
conn fails). It does not test the DISPATCHED repos: a repos bundle built over
the WRONG connection (a stale `_FencedConnection` from a previous generation,
or a raw conn smuggled past the factory) would still pass the current fixture
as long as the factory took no conn. The corrected SD-01 rationale says the
stale-fence danger was overstated because the check reads the LIVE generation
— true for the shipped `_project_repo`/`_task_repo` — but the source repos are
new, and the bundle must be pinned to the CURRENT fenced connection.

**Pin:** `_refresh_fence` builds the source repos over `self._fenced` and the
D10 fixture asserts `repos._conn IS fenced` (identity), plus the
stale-generation negative: a bundle held across a generation change fails
closed on the source write (SD-01 fixture 11 applied to the OUTCOME write, not
just the extract write).

### HD-04 (P3) — Pin when the `task` snapshot is taken

§H's `task: dict` ("the current task row, read-only view") is unpinned as to
capture point. If it is a snapshot from dispatch and the recovery ladder moves
the task mid-handler (NO_SIGNAL → FAILED → RETRYING → RUNNING under lease
expiry), the handler's view is stale — harmless for WRITES (the fence covers
generation changes; the write path re-reads binding INSIDE the transaction),
but the handler's own reads (e.g., spec refs) would use stale data. The
authoritative re-check is the in-txn binding read; the snapshot is for
parameter passing only.

**Pin (text):** the snapshot is taken at dispatch; the handler never re-reads
task STATUS (only the write path does, inside the transaction); a handler
needing fresh data re-reads through the repos' read surface, never the
snapshot.

---

## 3. What survives (verified against shipped code)

- **The three-check split itself.** Admission recompute, semantic-only one-shot,
  dereference re-derivation are the right three seams; OB-01–05 refine the
  seams, none of them collapse a check into another.
- **The fence mechanism.** `_assert_lock_valid` reads the LIVE lock row
  (owner + generation) against the controller's captured generation
  (controller.py:313); the check runs inside the writer's transaction on the
  first write statement; `_acquire_lock` increments the generation on reclaim
  (controller.py:324–335). A stale bundle fails closed in every generation-
  change case — HD-01 is a hole in the DELEGATION surface, not in the check.
- **The semantic/observation split in code.** `content_hash_of_search_result`
  (semantic preimage, `_IDENTITY_FIELDS`) and `observation_hash_of_search_result`
  (full-record minus `content_hash`) are correctly separated; `canonical_json`
  (sort_keys, compact separators, ensure_ascii=False) matches the tests'
  independent recomputation; `make_search_result_id` stays request-state.
- **The one-shot precedent.** The shipped `record_extraction` 3c
  (repositories.py:1523) is a hash-SET comparison (not a bare probe), which is
  the model OB-01 pins — the source method must copy the SET semantics, not
  the EXTRACT probe shape.
- **Zero new authority.** Every finding stays inside the existing controller /
  one write method / one mutation path. No finding introduces a loop, a
  scheduler, a table, an event, or an evidence surface.

---

## 4. Fold-in (COMPLETE — 2026-08-14)

1. OB-01 — pin the one-shot SET membership (per-result semantic hashes + the
   outcome-level record hash; FETCH: payload hashes + NoFullText records only,
   `FetchLogEntry` stream excluded); new outcome-hash helper + the
   divergence-vs-observation split fixtures.
2. OB-02 — reuse branch re-verifies the PERSISTED row's observation_hash
   before reuse; tampered-row reuse fails (fixture).
3. HD-01 — `_FencedConnection` closes `cursor`/`commit`/`rollback` on the
   fenced surface; the no-cursor-write fixture.
4. HD-02 — supersede §3's dispatch line with the typed
   `SourceTaskExecutionContext`; the bundle-surface fixture (no conn).
5. OB-03/OB-04 — scope-honesty text in §E (record-only tamper scope;
   inconsistent-forge-only rejection).
6. HD-03 — `_refresh_fence` builds the source repos over `self._fenced`;
   repos-connection-identity fixture + stale-generation source-write negative.
7. OB-05 / HD-04 — resolver reconstruction coercion contract (tuple/dict/None)
   + the `SearchResult' == SearchResult` fixture; task-snapshot capture pin.

Then the record may move to **STEP 6 DESIGN — ACCEPTED FOR IMPLEMENTATION
(third gate)** — **FOLDED: the design record + remediation record now carry
every pin above (D10 fixtures 22–27; §E/§F/§H/§I text); the §25 condition is
met and the standing condition for step-6 code is the once-folded record.**
