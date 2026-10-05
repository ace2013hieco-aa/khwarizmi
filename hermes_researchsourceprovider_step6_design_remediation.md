# Step 6 — Task-Side Orchestration — Adversarial Design Remediation
## Pre-Implementation Resolution Record (2026-08-14)

**Status: STEP 6 DESIGN — ACCEPTED FOR IMPLEMENTATION** (after this
remediation). The P0 finding was a REAL defect in shipped code and is FIXED
with regression fixtures; the P1/P2 findings are resolved as design decisions
below. No step-6 orchestration code has been written; the design record
(`hermes_researchsourceprovider_step6_orchestration_design.md`) + both audit
records (SD/SD2) remain authoritative where this record does not supersede
them (it does for: the SearchResult identity model §C, the artifact
identity/provenance model §D — which REVISES the SD2-01 cross-project conflict
ruling — the recovery matrix §F, the observation-hash pins §E (OB-01…OB-05), and
the dispatch-signature supersession §H (HD-02 — §H REPLACES the design record
§3's bare-tuple `handler(task, fenced, repos)` dispatch line)).

---

## A. Baseline

- HEAD at gate: `05b303b` (before this remediation; the P0 fix is now
  uncommitted on top).
- Suite before: **837 passed, pyright 0 errors**; after the P0 fix:
  **842 passed (837 + 5 P0 fixtures), pyright 0 errors**.
- Source files inspected: `src/hermes/tools/research_sources.py` (the
  `SearchResult` record + identity helpers), `src/hermes/tools/providers/
  paginate.py` (the walk sets `content_hash`), `src/hermes/tools/providers/
  normalize.py` (`dedup_key`), `src/hermes/persistence/migrations.py`
  (`artifacts`, `provenance_edges`), `src/hermes/persistence/repositories.py`
  (`ArtifactRepository`, `record_extraction` — the one-shot precedent),
  `src/hermes/research/controller.py` (handler registry, `_refresh_fence`,
  recovery ladder), `src/hermes/artifacts/store.py`, `tests/test_research_
  sources.py` (the identity fixtures), the step-6 design + SD/SD2 audits.

## B. Finding-by-finding disposition

| Finding | Verdict | Disposition |
|---|---|---|
| **P0 — SearchResult identity unstable** | **VERIFIED — REAL DEFECT, FIXED** | `content_hash_of_search_result` hashed the FULL record (minus `content_hash`), including `access_timestamp_utc`, `request_params_redacted`, counts, `reconciliation`, `provenance` (whose `request_log_ref` changes every run). Same semantic source across runs → H1 ≠ H2 → the step-6 hash-set one-shot would classify a crash-retry as divergent. FIXED: `content_hash` is now the SEMANTIC identity (§C) + a new `observation_hash_of_search_result` for full-record integrity. 5 regression fixtures. |
| **P1 — global content hash vs project/task provenance** | **Resolved: GLOBAL CONTENT ARTIFACT + PROJECT-SCOPED PROVENANCE** | §D. REVISES SD2-01: cross-project identical content is legitimate sharing via `provenance_edges`, NOT a typed conflict. The `content_hash` UNIQUE constraint stays (artifact = content). |
| **P1 — `record_source_outcome()` monolithic** | **Resolved: internally factored** | §E — one public write boundary, private pure/validation helpers + one transactional commit function. No helper may write. |
| **P1 — two-transaction recovery matrix** | **Resolved: explicit matrix** | §F — every {status × outcome} pair has exactly one deterministic interpretation. |
| **P2 — artifact type taxonomy** | **Resolved: taxonomy + legality matrix** | §G. |
| **P2 — handler capability boundary** | **Resolved: typed capability bundle** | §H — `SourceTaskExecutionContext`; no raw conn, no gateway, no unrelated repos. |

---

## C. Final SearchResult identity contract

**Two hashes, two contracts:**

1. **`content_hash` — SEMANTIC/source identity** (stable across runs). Preimage
   (the ONLY fields):
   - `provider`
   - `identifiers` (sorted)
   - `title`
   - `authors`
   - `year`
   - `venue`
   - `abstract_sha256`
   - `source_url`
   - `valid_negative`, `valid_negative_for` (a lookup's "answered no for X" IS
     that negative result's identity)

2. **`observation_hash` — full-record integrity** (tamper evidence over the
   persisted form). Preimage: the ENTIRE record EXCEPT `content_hash` (ADV-01).
   Computed at persist time via `observation_hash_of_search_result`; stored in
   the artifact metadata; NOT a dataclass field (the port type stays stable).

**EXCLUDED from `content_hash` (observation/retrieval metadata):**
`result_id`, `endpoint`, `query`, `request_params_redacted`,
`access_timestamp_utc`, `page_index`, `cursor_key`, `raw_retrieved_count`,
`delivered_count`, `total_count`, `total_is_estimate`, `reconciliation`,
`provenance`, `content_hash` itself.

**Why `result_id` stays request-state:** `make_search_result_id` keeps its
(provider, endpoint, query, position, identifiers) preimage — it is the
request-log discipline id ("this record as retrieved by this request at this
position"). Source refs (`source_result:<id>`) key on the SEMANTIC
`content_hash`, so position changes across runs never destabilize a ref.

**Migration impact:** NONE on the DB (no persisted source rows exist — the
slice's write path is not yet built). The walk's `content_hash` assignment
(`paginate.py`) now fills the semantic hash; the ADV-01/06 identity tests were
updated to the new preimage. Cross-cutting invariant: repeated retrieval of
the same canonical source NEVER creates a new identity from observation
metadata changes.

**Tests:** the 5 P0 fixtures in `tests/test_research_sources.py` (timestamps,
request metadata, observation metadata, material change, crash-retry hash-set
idempotency) + the updated ADV-01/06 recomputation tests.

---

## D. Final artifact identity/provenance model

**GLOBAL CONTENT ARTIFACT + PROJECT-SCOPED PROVENANCE.**

- **Artifact identity = content** — one `artifacts` row per content hash
  (the existing `content_hash UNIQUE`); `artifact_id` = `"art_" + full
  content hash` (the truncated `[:24]` alias is presentation-only — §18 of the
  gate; every integrity check uses the FULL hash).
- **Ownership/provenance = relations** — every (project, task) → artifact
  relation is a `provenance_edges` row (`derived_from` / `used_as_input`),
  the existing §14 table; the artifact row's nullable `project_id`/`task_id`
  columns are FIRST-WRITER informational metadata, never rewritten on reuse.
- **Cross-project identical content is legitimate sharing:** the second
  project's write finds the row (get-by-hash), verifies the bytes, and adds
  its own provenance edges — no misbinding (the row's first-writer columns
  stay), no typed conflict. **This REVISES SD2-01's `SourceOutcomeConflictError`**
  ruling: the conflict class is dropped in favor of edges-based reuse, because
  the `provenance_edges` table exists precisely for this and the row's binding
  is edges-carried. The typed conflict survives ONLY for the genuinely
  divergent case (same task, different bytes → the one-shot refusal, §F).
- **One-shot (A2-03) keys on edges:** "prior output of task T" =
  `SELECT artifacts JOIN provenance_edges WHERE upstream_id = task:T AND
  edge_type = 'derived_from'`; the hash-SET comparison (§F) decides idempotent
  vs divergent.

**Why not PROJECT-BOUND artifacts:** the UNIQUE constraint is on
`content_hash`, not `(project_id, content_hash)`; the schema was built for
global content addressing, and the extraction pipeline's claims already
dereference project-scoped `dataset_manifest:` refs against global-ish
content identity. Bounding artifacts to projects would either weaken the
UNIQUE (a migration) or duplicate content (against content-addressing).

---

## E. Final `record_source_outcome()` internal structure

One public write boundary; internally factored private helpers (each pure or
read-only — NO helper may write, BEGIN IMMEDIATE, or touch the gateway):

```
record_source_outcome(exec_ctx, outcome, *, outcome_kind) -> SourceAcceptance
  ├─ _validate_task_binding(exec_ctx, outcome)      # task exists, project match,
  │                                                 # template marker, RUNNING,
  │                                                 # spec refs match outcome refs
  │                                                 # (A2-01/02 — read INSIDE the txn)
  ├─ _validate_project(exec_ctx)                    # V6-P7-F03
  ├─ _validate_identities(outcome)                  # re-derive EVERY identity with the
  │                                                 # shipped helpers; mismatch → fail
  ├─ _resolve_idempotency(exec_ctx, outcome)        # prior-by-task via edges (D);
  │                                                 # hash-SET compare → IDENTICAL |
  │                                                 # DIVERGENT | NEW
  ├─ _prepare_records(outcome)                      # semantic-hash artifact rows +
  │                                                 # observation_hash metadata + the
  │                                                 # artifact-type taxonomy (G); pure
  ├─ _prepare_provenance_edges(exec_ctx, outcome)   # task→outcome→per-source edges; pure
  └─ _commit_source_outcome(...)                    # THE ONLY writer: BEGIN IMMEDIATE →
      # re-read binding inside txn → idempotent reuse or insert + edges → COMMIT
      # (the two-transaction split: rows+edges here; SUCCEEDED is the controller's)
```

Invariant pins: `_commit_source_outcome` is the ONLY function that executes
`BEGIN`/`INSERT`/`COMMIT`; every helper returns typed data; every identity is
re-derived at `_validate_identities` AND re-checked inside `_commit`'s
transaction (belt over the TOCTOU); no helper returns a connection.

**The observation_hash verification contract (P0 write-path pin — three
distinct checks, never conflated):**

1. **Admission (new write):** `_validate_identities` recomputes BOTH hashes
   with the shipped helpers — `content_hash` (semantic preimage, §C) must
   equal `result.content_hash` (a forged/mismatched hash → typed rejection,
   ADV-01/06); `observation_hash` (full-record preimage minus `content_hash`)
   is computed over the record being persisted and STORED in the artifact
   metadata (`observation_hash_of_search_result` — the port type stays
   unchanged; the hash rides the metadata, per §C).
2. **Idempotent reuse (crash-retry):** the one-shot decision is the SEMANTIC
   hash-SET comparison ONLY (§F) — a retry whose observation metadata changed
   (new timestamp/log ref/counts) is IDENTICAL and reuses, never a refusal;
   observation_hash differences between runs are EXPECTED and never gate
   idempotency (that would re-break the P0 crash-retry invariant).
3. **Dereference/load:** the resolver re-derives BOTH hashes from the
   PERSISTED row and compares against the stored values — the observation_hash
   re-verification catches an observation-field tamper (edited timestamp /
   counts / log ref, semantic fields untouched) that `content_hash` alone
   CANNOT detect (the gate §17 metadata/data-mismatch class); a mismatch
   FAILS the dereference loudly (SD-05), never a form-checked pass.

Probes: `tests/test_research_sources.py` — `test_observation_hash_catches_observation_field_tamper`
(content_hash survives the tamper, observation_hash does not — proving the
write path needs BOTH), `test_observation_hash_deterministic_roundtrip`
(serialize → persist-form → deserialize → recompute → equal), and
`test_observation_hash_differs_across_legit_retries` (same semantic hash,
different observation_hash — the idempotency gate stays content-based). D10
fixture 21 pins the same class at the orchestration level.

**Third-gate pins (OB-01…OB-05 — folded in 2026-08-14 from
`hermes_researchsourceprovider_step6_design_audit3.md`):**

1. **OB-01 — hash-SET membership PINNED.** The one-shot set = the per-result
   SEMANTIC content hashes + the OUTCOME-LEVEL record's hash (a new
   deterministic helper: canonical(outcome_kind, aggregate, notes,
   request-log-facts hash); access timestamps + cursor chain excluded). For
   FETCH: the per-source payload content hashes + the NoFullText
   evidence-record hashes ONLY — the `FetchLogEntry` stream
   (attempts/attempt_verdicts/timestamps) is observation and NEVER enters the
   set. A changed aggregate (COMPLETE→SHORTFALL) or a fetch that now succeeds
   where it failed = DIVERGENT → refusal; identical semantic content with
   changed observation metadata = IDENTICAL → reuse (the P0 invariant enforced
   at BOTH layers).
2. **OB-02 — reuse re-verifies the PERSISTED row.** Before reusing, the
   get-by-hash branch reconstructs the record from the row's metadata and
   re-derives BOTH hashes against the row's `content_hash` column AND the
   stored `observation_hash`; the retry's own observation_hash is never
   compared; a tampered persisted row fails the REUSE with a typed integrity
   error, not merely the later dereference.
3. **OB-03 — scope honesty.** observation_hash is RECORD-metadata integrity
   ONLY; row-level binding columns (`task_id`/`project_id`/`artifact_type`/
   `producer`) and the outcome-level metadata are protected by the
   in-transaction task-binding re-check + the §14 edge UNIQUEs, never by any
   hash.
4. **OB-04 — inconsistent-forge-only.** Re-derivation rejects corruption and
   INCONSISTENT forgeries; a self-consistent re-hash is out of the
   deterministic-code threat model (the single-producer boundary is the
   authenticity defense — no keyed MAC exists in the slice).
5. **OB-05 — resolver reconstruction coercion.** The resolver's reconstruction
   is pinned: `authors` coerced to tuple, dicts preserved, `None`-preservation
   for the nullable fields; `SearchResult' == SearchResult` on identity AND
   observation fields; the observation_hash re-verifies.

---

## F. Recovery state matrix (two-transaction acceptance)

| Task status | Persisted outcome | Required behavior |
|---|---|---|
| RUNNING | none | execute/recover (the normal path or the NO_SIGNAL → RETRYING → RUNNING ladder re-executes the task's OWN handler, execute-only — SD2-05) |
| RUNNING | identical complete outcome | idempotent reuse → controller SUCCEEDED (the hash-SET equal case; the SET = per-result semantic hashes + the outcome-record hash — OB-01; observation metadata never enters) |
| RUNNING | divergent outcome | one-shot refusal → FAILED terminal (a retry would diverge again; A2-03) |
| SUCCEEDED | identical outcome | idempotent no-op (the controller never re-executes SUCCEEDED tasks; discovery excludes them — defensive only) |
| SUCCEEDED | divergent outcome | reject (unreachable via the controller — defensive; logs a diagnostic, never silent) |
| FAILED | valid persisted outcome | **explicit:** FAILED-with-rows is the one-shot terminal OR the recovery requeue (attempts remaining). The re-execution re-runs the task's own handler; identical → idempotent SUCCEEDED (the crash-recovery path); divergent → FAILED stays (the refusal path). Never auto-requeued past `max_retries`. |
| READY | persisted outcome | **impossible** (rows require execution; no ratified transition writes rows at READY) → treat as corrupt: loud diagnostic, leave READY undispatched, never silent |
| RETRYING | persisted outcome | the retry's re-execution hits the one-shot: identical → idempotent SUCCEEDED; divergent → FAILED terminal |
| INVALIDATED | persisted outcome | policy: rows remain as immutable history; no re-execution, no promotion, no new edges |

The required failure scenario (§12 of the gate) resolves as: source task
RUNNING → outcome txn commits → crash before SUCCEEDED → ladder
(NO_SIGNAL → FAILED → RETRYING → RUNNING, attempts permitted) → the task's own
handler re-executes → the write path's hash-SET compare sees IDENTICAL →
idempotent reuse → SUCCEEDED. No duplicate artifacts (get-by-hash), no
duplicate edges (edge UNIQUE), no false divergence (semantic hashes, §C), no
impossible status (every transition through the ratified state machine).

---

## G. Artifact type taxonomy

| Type | Owner | Immutable | Content-addressed | `source_ref`-able | Provenance edges | Evidence | Task-consumable | Writer | Resolver |
|---|---|---|---|---|---|---|---|---|---|
| `source_search` (outcome: aggregate + notes + request-log facts) | the SOURCE_SEARCH task | yes | yes (semantic outcome hash) | no | yes (task → outcome) | NEVER | yes (fetch task reads its refs) | `record_source_outcome` only | outcome ref |
| `source_result` (per-result semantic record) | the SOURCE_SEARCH task | yes | yes (`content_hash`, §C) | **yes** (`source_result:<full-hash>`) | yes (outcome → result) | NEVER | yes (SOURCE_FETCH input) | `record_source_outcome` only | the extended `_dereference_artifact_ref` (SD-05) |
| `source_fetch_outcome` (fetch aggregate + `FetchLogEntry` stream) | the SOURCE_FETCH task | yes | yes | no | yes (task → outcome) | NEVER | yes (audit) | `record_source_outcome` only | outcome ref |
| `source_payload` (fetched raw bytes) | the SOURCE_FETCH task | yes | yes (`sha256(raw_bytes)`) | **yes** (the extraction pipeline's citation target) | yes (task → payload) | NEVER (it is INPUT to extraction, never evidence) | yes (EXTRACT cites it) | `record_source_outcome` only | the extended resolver |

Rules: `artifact_type` is validated at admission (closed taxonomy, unknown type
→ typed error); ONLY `source_result`/`source_payload` may be cited as
`source_ref`; NO type may ever become Evidence (the Evidence Ladder is a
separate authority); the write path sets the type from the outcome kind, never
from payload content.

---

## H. Handler capability contract

**Typed capability bundle** (not the bare `(task, fenced, repos)`):

```python
@dataclass(frozen=True)
class SourceTaskExecutionContext:
    task: dict                 # the current task row (read-only view)
    project_id: str
    repos: SourceRepos         # ArtifactRepository + record_source_outcome +
                               # _dereference_artifact_ref, ALL over the fence
    providers: ProviderMachinery  # adapters/transport/limiter/recorder/clock/
                               # redaction (tick-independent)
    policy: SourcePolicy       # bounds, retry, cap policy
    # NO raw connection. NO gateway. NO Controller internals. NO unrelated repos.
```

Rationale: the gate's P2 §8 — a bare `(task, fenced, repos)` hands the handler
an unfenced-typed `Any` connection + unbounded repos; a typed bundle makes the
capability surface explicit, prevents accidental raw-conn capture (the factory
takes NO connection, SD2-03), and gives the dispatch signature a name to test.
The bundle is a capability carrier, NOT an authority — it exposes exactly the
two write methods (the source recording + artifact reuse) and the read-only
provider machinery. The controller's dispatch builds the bundle per tick from
`self._fenced` (SD2-03's `_refresh_fence` site); a stale bundle fails closed
(the fence's LIVE-generation check).

**Third-gate pins (HD-01…HD-04 — folded in 2026-08-14):** HD-02 — this §H
SUPERSEDES the design record §3's bare-tuple dispatch line
(`handler(task, self._fenced, self._repos)`); the implementation dispatches
ONLY the typed bundle. HD-01 — the fenced connection's delegation surface is
closed: `cursor` REJECTED loudly (the `executescript` F3 pattern — a
cursor-based write never lands), `commit`/`rollback` disallowed on the fenced
surface (the repositories own transactions) — a shipped-code pin the step-6
implementation carries. HD-03 — the source repos join `_refresh_fence` over
`self._fenced`; the SD2-03 negative asserts `repos._conn IS fenced` (identity),
not only that the factory took no conn. HD-04 — the `task` snapshot is taken
at dispatch; the handler never re-reads task STATUS (the write path's
in-transaction binding re-check is the authoritative read).

---

## I. Final acceptance-test matrix (the gate's attacks → expected)

| Gate section | Attack | Expected |
|---|---|---|
| 9 provenance | dangling `source_result` / fetched ref; wrong type; wrong project; wrong task; another search's result; forged hash/id; reused artifact with wrong provenance | all fail closed (resolver + edges + identity re-derivation); no silent success |
| 10 round-trip | serialize → persist → resolve → reconstruct | `SearchResult' == SearchResult` on all identity + observation fields (lossless; the persisted metadata carries the full record; observation_hash verifies it) |
| 11 idempotency | A: same task/result/observation → reuse; B: same task/semantic + changed observation → reuse (§C); C: same task + different semantic → typed conflict; D: same content + different task, same project → documented edges policy; E: same content + different project → edges sharing (D); F: same task + bytes + provenance differences → identity unchanged (provenance is observation), observation_hash differs. The SET = per-result semantic + outcome-record hashes (OB-01): a changed aggregate is DIVERGENT, never reused; the reuse re-verifies the persisted observation_hash (OB-02) |
| 12 crash/restart | the 8 crash windows (§F matrix) | no duplicates, no dangling edges, no stuck task, no false divergence, deterministic replay |
| 13 fencing | stale-fence artifact/source-result/edge/transition writes; handler retaining stale fence/repos; recovery callback; nested helper | `LockLostError`, rollback, no stale mutation (every authoritative write through the fence) |
| 14 template/handler | unknown/case/whitespace/malformed template; wrong profile; fetch without dependency; fetch → non-source-search; forged refs; missing handler; wrong return; unexpected raise | fail closed; never silent SUCCEEDED; never alternate task creation; never gateway bypass |
| 15 no-evidence | payloads with SUPPORT/ROBUST/REPLICATED/gate/task-creation/lifecycle directives | zero evidence/gate/task/lifecycle mutation (closed schema; unknown keys rejected) |
| 16 injection | hostile titles/abstracts/fetched HTML/metadata with instructions | treated purely as data; no controller behavior change; no tool/state/prompt mutation |
| 17 integrity | forged artifact_id/content_hash; truncated-alias mismatch; same-alias-different-content; corrupted bytes; metadata/data mismatch | fail closed (FULL-hash checks everywhere); the reuse path re-verifies the persisted observation_hash (OB-02); scope: record-metadata integrity only (OB-03) |
| 18 truncated-id | two hashes sharing a prefix; forged truncated id; wrong full hash; alias/full-hash mismatch | fail closed; the `[:24]` alias is presentation-only |
| 19 recovery generic | EXTRACT / SOURCE_SEARCH / SOURCE_FETCH / unknown recovery | each re-executes ITS OWN handler (execute-only, SD2-05); no reinterpretation |
| 20 daily cap | cap exhausted → task retry → tick → repeated tick → recovery | no unbounded loop; the cap-stop task FAILED with the cap cause, no auto-requeue (OQ-3); no duplicate calls |
| 21 bounds | task bounds → FetchRequest bounds; persisted size bounded; per-result can't bypass the batch cap; oversized rejected pre-durable; one malicious source can't create unbounded metadata | all bounded (S11/GC-03) |
| 22 no-new-authority | source inspection | existing Controller / Task Graph / Gateway / transitions / repository mutation only; zero new loops |

---

## J. Deferred items (explicitly not dropped)

1. **Cross-project artifact dedup/sharing UX** — the edges-based sharing model
   (§D) is the mechanism; a later slice may add per-project aggregate views or
   a sharing policy. The mechanism is IN now, the policy surface is deferred.
2. **The `repositories.py` bounded split** — post-step-6 (the IX god-module
   ruling): land `record_source_outcome` in its natural seam, then split the
   P7/source cluster into a `persistence/repositories/` package with `__init__`
   re-exports.
3. **The recorder's budget-ledger persistence (AR-02)** — unchanged, deferred.
4. **Parallel fetch (F13)** — needs a new design gate.
5. **S12 large-corpus routing** — `raw_bytes_ref`/storage for very large
   payloads; the artifact store handles the normal case now.
6. **Per-project `(project_id, content_hash)` uniqueness** — NOT adopted (the
   global-content model wins, §D); a future slice may add a VIEW, never a
   weakened constraint.
