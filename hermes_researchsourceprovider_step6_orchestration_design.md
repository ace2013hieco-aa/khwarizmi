# ResearchSourceProvider — Step 6 of 7 — Task-Side Orchestration
## Design Decision Record (IMPLEMENTED — TESTED; NOT RATIFIED-AS-IMPLEMENTED)

**Status:** **IMPLEMENTED + TESTED (2026-08-14)** — the thrice-gated design
survived FOUR post-implementation hostile code audits
(`hermes_researchsourceprovider_step6_code_audit.md` S6-A1…A5,
`hermes_researchsourceprovider_step6_code_audit2.md` S6-B1…B3,
`hermes_researchsourceprovider_step6_code_audit3.md` S6-C1…C4, and
`hermes_researchsourceprovider_step6_code_audit4.md` S6-D1…D4) and all
confirmed findings were folded in (typed resolver, provider-agreement rule,
HandlerResult return contract, edge-based fetch input, provider-less-result
refusal, structural completion check, required resolver type, the
cross-task citation closed by the dispatch-seam task-scoped write view, and
the S6-D4 no-escape reach-in — the scoped view retains NO raw bundle).
**881 passed suite-wide (869 + 12 audit-regression fixtures), pyright 0
errors.** The §26 Ix structural comparison is CLEAN
(`docs/ix/step6_structural_comparison_20260814.md` — zero new write paths,
zero cycles, single handler→repository boundary; re-verified at `06dc7b6`).
The closure-candidate evidence map is in
`docs/idr/step6_closure_candidate_evidence_map.md`. **Pre-step-7
remediation (`hermes_researchsourceprovider_step6_remediation2.md`,
IDR-033 — 2026-08-14): the second-round review's P1 (cross-project
SOURCE_FETCH lineage) closed at BOTH surfaces — gateway admission requires
``search_task.project_id == fetch.project_id`` (PROVENANCE, ``P1 lineage``)
and the write path re-checks the producing task's search lineage inside the
write transaction (V6-P7-A2 discipline); C1 (provider contract) closed from
both ends (admission + builder require the allowlisted provider). 884
passed suite-wide (881 + 3 fixtures), pyright 0 errors.** **S6-R01…R04
closure (second round — `hermes_researchsourceprovider_step6_remediation_report.md`,
IDR-034, 2026-08-14): R01 completes the lineage — gateway refs must resolve
FROM the cited search task (two-hop edges) and the write path re-checks the
task-graph dependency edge + refs-ownership in-transaction (outcome ⊆ spec
⊆ search-output); R02 — artifact TYPE now participates in content-hash
reuse (same hash + different type → SourceOutcomeIntegrityError); R03 —
SOURCE_FETCH carries its OWN bounds (max_sources/size_cap_bytes/retry_policy)
through builder → gateway → handler (persisted spec is authoritative; no
silent default substitution); R04 — fetch provider must agree with its
cited search's provider at the write path. 6 regression fixtures; 890
passed suite-wide (884 + 6), pyright 0 errors; Ix clean (153 → 161, all
documented orphan-class deltas; zero new write paths/cycles).** **Final
review (`hermes_researchsourceprovider_step6_final_review.md` + the R01
resolver audit, IDR-035, 2026-08-14): the two-hop refs-ownership path and
the in-transaction dependency-edge re-check hold under hostile probing; two
fold-ins — the partial-refs execution scope (the spec refs ARE the fetch
scope; no silent over-fetch) and the payload-write-boundary type guard (an
existing source_result row can never stand in for a source_payload through
the type-blind ArtifactStore dedup). 20/20 fresh hostile probes; 892 passed
suite-wide (890 + 2), pyright 0 errors. **FINAL REVIEW VERDICT: READY FOR
STEP 7.** NOT RATIFIED-AS-IMPLEMENTED — the external closure gate remains
a standing condition; step 7 is the next scheduled action.

**Pre-implementation gate (2026-08-14):** the adversarial gate ran and resolved
in `hermes_researchsourceprovider_step6_design_remediation.md`:
**STEP 6 DESIGN — ACCEPTED FOR IMPLEMENTATION.** The P0 finding
(Semantic identity unstable) was a REAL defect in the shipped
`content_hash_of_search_result` — FIXED (semantic preimage + the new
`observation_hash_of_search_result`, 5 regression fixtures, 842 passed); the
P1/P2 findings resolved as design decisions (GLOBAL CONTENT ARTIFACT +
PROJECT-SCOPED PROVENANCE via `provenance_edges` — REVISING the SD2-01
cross-project conflict ruling; internally factored `record_source_outcome`;
 the explicit recovery state matrix; the artifact-type taxonomy; the typed
`SourceTaskExecutionContext` capability bundle). **The hostile gate has run AND the
SD-01…SD-05 findings + OQ-1…OQ-6 rulings are FOLDED IN (2026-08-14)** — see
`hermes_researchsourceprovider_step6_design_audit.md` for the full record. The
fold-in dispositions: SD-01 → the handler contract becomes dispatch-threaded
`handler(task, fenced, repos)` (the fence is per-tick; §3); SD-02 → the
recovery re-execution becomes template-generic (re-dispatch through the same
per-task execute path, §10); SD-03 → the write path is TWO transactions (rows+
edges atomic; the controller owns SUCCEEDED), §5; SD-04 → the idempotency
branch is get-by-hash-first inside the write transaction, §5/§7; SD-05 → the
dereference resolver is extended for the source artifact type, §5. OQ-1…OQ-6
ruled in §13. **The second-gate hostile review has run AND the SD2-01…SD2-05
precision pins are FOLDED IN (2026-08-14)** — see
`hermes_researchsourceprovider_step6_design_audit2.md`: the idempotent reuse
is (project, task, bytes)-keyed (a cross-project duplicate raises a typed
conflict — SD2-01, §5); the one-shot uses the EXTRACT content-hash-SET
comparison (identical → idempotent reuse; different → refusal — SD2-02, §5);
the handler factory takes NO connection and the per-tick repos bundle builds in
`_refresh_fence` (SD2-03, §3); the resolver keys the FULL content hash and the
ref/type forms are named (SD2-04, §5); the template-generic re-execution is
execute-ONLY (no re-claim — SD2-05, §10). One SD-01 rationale corrected: a
stale fence fails closed by the LIVE generation check, so no write bypass
existed in the fence itself — the dispatch-threaded fix stands for the None
case + current repos. The standing condition is now the implementation gate —
no further design review required; step-6 code may be written per this folded
record per the three-gate pattern that carried steps 1–5a. **The THIRD-gate
hostile review has run AND the OB-01…OB-05 + HD-01…HD-04 pins are FOLDED IN
(2026-08-14)** — see `hermes_researchsourceprovider_step6_design_audit3.md`
(verdict MERGE WITH REMEDIATION, third round): the one-shot hash-SET
membership is PINNED (§5 — per-result semantic hashes + the outcome-record
hash; the fetch log stream excluded), the reuse path re-verifies the persisted
`observation_hash` (§5), the §3 dispatch line is SUPERSEDED by the typed
`SourceTaskExecutionContext` (§3, HD-02), the fence delegation surface is
closed (HD-01), and the resolver reconstruction contract is pinned (§6/§10,
OB-05). Design-only — no code; the §25 implementation gate stays.

**Scope:** the task-side orchestration that calls `walk()` + `combine()` and
`fetch_batch()`, and routes `SearchOutcome` / `FetchOutcome` through the
ordinary Hermes write path. The provider drivers (`paginate.py`,
`hazards.py`, `ratelimit.py`, `http.py`, the adapters) are **shipped, read-only,
and unchanged by this step** — this record specifies the task layer that calls
them, nothing inside them.

**Deferred (NOT this step):** the blueprint's step-6 `replay.py` acceptance
harness (a test-only artifact, orthogonal to this record), the recorder's
budget-ledger persistence (the AR-02 hook), per-task budget charging, and
parallel fetch (F13 — needs a new design gate).

---

## 1. Baseline — the shipped surfaces this record builds on

| Surface | Shipment | Authority |
|---|---|---|
| `paginate.py` `walk()` / `combine()` | step 3 (WS/WK/WK3 audits folded in) | read-only; `combine()` is the raising point (`RetrievalShortfallError(EMPTY)` / `ProviderUnavailableError(UNAVAILABLE)`) |
| `paginate.py` `fetch_batch()` | step 5a (FD/A1+F1–F13/GC/FC audits folded in) | read-only; entry checks fail closed; the `FetchedPayload` carrier is transient |
| `base.py` `ProviderAdapter` (5 hooks) + runtime protocols | steps 3/4 | the thin adapter boundary |
| `ratelimit.py` / `http.py` | step 4 (RT/TR/RL/RT4 audits folded in) | the gate; atomic `(bool, str)` acquire; transport raises only transport-level failures |
| `controller.py` (IDR-029 C-tier controller) | P7 slice, IMPLEMENTED + TESTED | one execution surface; claims READY work, executes, recovers; generation-fenced (ADV-02); `task_handlers: dict[str, Callable]` for template-named AGENT_TASKs |
| `extraction.py` (EXTRACT template + `accept_extraction_output`) | P7 write path (IDR-028/026/027, A2 bindings) | the validated-before-acceptance precedent: task-bound atomic repository write, journaling without new events |
| `ArtifactRepository` (`repositories.py`) + `artifacts/store.py` | v4 | the artifact store — content → filesystem, metadata → `artifacts` row, IDR-013 atomicity |
| `research_sources.py` port types | step 1 | `SearchOutcome` / `FetchOutcome` / `SearchResult` / `FetchedPayload` (transient carrier) |
| IDR-030 (§27 item 55 ratification) | ratified | the provider allowlist + per-provider rate defaults are RATIFIED; the slice is read-only by construction and "hands outcomes to the task which routes through the ordinary write path — the only-entry-point invariant (PS-03)" |

The blueprint §5.3 already pins the handoff contract: *"the slice is read-only,
so the walk's `RequestLogRecord` and the fetch `FetchLogEntry` stream are
carried on the outcomes (transient). The task's ordinary write path persists
the redacted log facts into the Source records' provenance (content-hashed,
§14) atomically with admission — no new table. Dereference contract
(V6-FINAL-02 discipline): a `request_log_ref` in `SearchResult.provenance`
must resolve to the persisted record the task wrote with the Source admission;
a ref that cannot resolve fails, never dangles."*

---

## 2. Invariants preserved (no new authority, no second path)

1. **One execution surface** — the IDR-029 controller dispatches the provider
   tasks through its template-handler registry. No new scheduler, no new loop,
   no new authority. Two minimal controller changes are ADMITTED by the SD
   fold-in and are the ONLY controller changes this step makes: the
   dispatch-threaded handler signature `handler(task, fenced, repos)` (SD-01,
   §3) and the template-generic recovery re-execution (SD-02, §10). Both are
   signature/plumbing changes — neither adds an authority or a loop.
2. **The drivers stay read-only** — `walk`/`combine`/`fetch_batch` never touch
   the DB, the gateway, or the repository. The only DB access is inside the
   task layer's write path, exactly as IDR-028's `accept_extraction_output` →
   `record_extraction`.
3. **The only mutation path** — task admission via the gateway's `INSERT_TASK`;
   task status via the controller's `transition_status` (the ratified state
   machine); outcome persistence via ONE repository write method. No direct
   inserts from the provider machinery.
4. **No new events** — journaling is the producing task's existing
   `TaskCreated` / `TaskStatusChanged` events + the immutable rows + §14
   provenance edges (IDR-028 Decision 3 precedent). Zero new event types.
5. **No evidence promotion, no gate passage** — a search outcome or a fetched
   artifact is an INPUT to later epistemic stages (an extraction task cites it
   via `source_ref`), never evidence, never a gate verdict, never a status
   beyond ACTIVE/SUCCEEDED task status.
6. **No new tables** — the `artifacts` table (migration 1) is the durable home;
   `provenance_edges` (migration 2) carries the links; the task `spec` JSON
   carries the deterministic template parameters. Per the blueprint §5.3.
7. **Fail closed everywhere** — an unhandleable outcome class, an unbound
   write, a stale lease, an unknown template, or a dangling ref is a loud
   typed error, never a silent success.

---

## 3. D1 — Execution surface: the controller's template-handler registry

The orchestration is a **template-named `task_handler`** on the shipped
`Controller`, wired at construction (like `extract_fn` / `gate_verdict_fn`):

```
Controller(conn, project_id,
           task_handlers={
               SOURCE_SEARCH_TEMPLATE: make_source_search_handler(providers, ...),
               SOURCE_FETCH_TEMPLATE:  make_source_fetch_handler(providers, ...),
           },
           ...)
```

**SD-01 — the handler contract is dispatch-threaded `(task, fenced, repos)`.**
The shipped `Controller` rebuilds its fenced connection + repositories on
EVERY successful lock acquisition (`_refresh_fence`, `controller.py:309` — the
fence is per-tick, and the constructor value is `None`). A handler closure
cannot therefore capture the fence/repos at construction (it would capture
`None` or a stale generation). The pinned contract: the handler captures ONLY
the tick-independent provider machinery — the adapters (allowlist-validated,
IDR-030), the transport, the limiter, the recorder, the clock, the redaction
policy — and the controller passes the CURRENT fence + a per-tick repository
bundle at dispatch:

```
# in the controller's per-task execute path (the ONE change):
# HD-02 — the typed bundle SUPERSEDES the bare (task, fenced, repos) form;
# repos is the per-tick bundle rebuilt over self._fenced in _refresh_fence.
ctx = SourceTaskExecutionContext(task=task, project_id=project_id,
                                 repos=self._repos, providers=providers,
                                 policy=policy)
handler(ctx)
```

so the handler's writes are attributed to the CURRENT lease generation
(ADV-02). This is a minimal, explicit handler-contract change — the
"no controller code changes" claim of the pre-audit record is withdrawn; the
typed-bundle dispatch signature + a per-tick repos bundle are the admitted
change (HD-02).
The alternative (handlers become controller methods, the `_execute_extract`
pattern) is equivalent; the dispatch-threaded form is pinned because it keeps
the registry generic and the P3 handler surface the controller docstring
promises. `_classify` continues to route a template-named AGENT_TASK to
`self._task_handlers[template]` and fail-close on an unhandled template
(`"unhandled"` — never a silent SUCCEEDED).

**SD2-03 — the wiring discipline is pinned, and the SD-01 rationale is
corrected.** (a) The handler FACTORY takes NO connection: it receives only the
tick-independent provider machinery (adapters, transport, limiter, recorder,
clock, redaction) — a raw `conn` is refused at wiring time, and the D10
fixture asserts the negative (a handler wired with a raw conn fails the wiring
test, never runs). The dispatched `fenced`/`repos` are the ONLY DB handles in
scope. (b) The per-tick repos bundle builds in `_refresh_fence` — the ONLY
shipped place the repos are rebuilt per acquisition (`controller.py:309`);
the source slice's `ArtifactRepository` + the outcome-recording repo join that
rebuild. (c) CORRECTED: `_FencedConnection._assert_lock_valid` reads the
controller's LIVE `_lock_generation` (set per acquisition), so a stale
fence/repos bundle FAILS CLOSED in every generation-change case — the SD-01
stale-capture danger was overstated; the REAL hazard was the constructor `None`
(crash, never a silent write). The dispatch-threaded fix stands: it eliminates
the None case and keeps the repos current.

**HD-01 — the fence's DELEGATION surface is closed (a shipped-code pin the
step-6 implementation carries):** `_FencedConnection.__getattr__` currently
delegates `cursor()`/`commit()`/`rollback()` to the RAW connection — a handler
(or a future repo helper) could write through a cursor without ever running
`_assert_lock_valid`, or commit/rollback a repository's open transaction
mid-write (half-state). The implementation: `cursor` is REJECTED loudly (the
`executescript` F3 pattern — a cursor-based write never lands); `commit`/
`rollback` are disallowed on the fenced surface (the repositories own
transactions). **HD-03 — the source repos join `_refresh_fence` over
`self._fenced`** and the SD2-03 negative asserts `repos._conn IS fenced`
(identity), not only that the factory took no conn. **HD-04 — the `task`
snapshot is taken at dispatch; the handler never re-reads task STATUS** (the
write path's in-transaction binding re-check is the authoritative read).

Why the controller and not a standalone executor: it is the single execution
surface that already owns claim → RUNNING → SUCCEEDED/FAILED transitions, the
NO_SIGNAL recovery ladder, the generation fence (ADV-02 — a stale controller
cannot write), and the mode check (a non-ACTIVE project dispatches nothing).
A second executor would be a second authority — rejected.

**What the handler must NOT do:** the handler does not admit tasks, does not
build payloads (the planner does), does not touch the DB except through the
`fenced` connection it is handed — it calls the drivers, then calls the ONE
repository write method over that fence. The handler is the injection point
for the provider machinery, nothing more.

---

## 4. D2 — Task templates: `SOURCE_SEARCH` and `SOURCE_FETCH`

Two canonical template markers (casefolded-stripped, matching the `EXTRACT`
gateway-matching discipline — a hand-built payload cannot case-spoof), with a
deterministic payload builder per template (the `build_extract_task_payload`
pattern):

**`SOURCE_SEARCH`** (AGENT_TASK, RESEARCHER profile)
- spec: `provider` (from the IDR-030 allowlist — unknown provider fails at
  admission, never at execution), query hints (`normalize.parse_query_hints`
  output), `page_size`, `max_pages`, `size_cap_bytes`, `template` +
  `template_version`.
- Executor: `walk(adapter, hints, ...)` per provider → `combine(...)`; the two
  aggregate raises are caught as **typed outcomes** (`EMPTY` / `UNAVAILABLE`),
  never as crashes and never as silent success — the outcome is recorded with
  its aggregate + notes (the walk already produces the verdict-note
  convention `COMPLETE(...)` / `SHORTFALL(cause=...)` / `UNKNOWN(...)`).

**`SOURCE_FETCH`** (AGENT_TASK, RESEARCHER profile)
- depends on its SOURCE_SEARCH task via the existing `task_dependencies` edge
  (task-graph dependency rules; no alternate insertion path).
- spec: the search task's task_id + the source refs it produced (the durable
  refs, not a payload copy of the results — the fetch input is resolved from
  the persisted outcome, never from a hand-authored list).
- Executor: resolve the `SearchResult` stream from the search task's persisted
  outcome → `fetch_batch(adapter, sources, request, transport, limiter,
  recorder, clock, ...)`.

Why two templates and not one: the fetch input is the search's output, so the
task graph expresses the dependency (search → fetch) structurally; a single
template would either embed the search inside fetch (two responsibilities in
one node, no provenance edge) or need an internal phase machine (a second
scheduler shape). The dependency edge keeps the operational authority in the
task graph.

**Payload identity:** `task_id` + `idempotency_key` are content-derived from
(provider, query hints, scope/requirement refs, template version) — re-running
the planner cannot duplicate work (AC-05 discipline).

---

## 5. D3 — The write path: one repository method, task-bound and atomic

Follow the IDR-026/027/028 pattern exactly. A new repository method —
`record_source_outcome` (on the repositories module; mirrored on
`ClaimAssumptionRepository.record_extraction`'s discipline):

```
def record_source_outcome(
    conn, project_id, task_id,
    outcome,               # SearchOutcome | FetchOutcome
    *,
    outcome_kind,          # "search" | "fetch"
    produced_by=...,
) -> dict
```

Contract (each row is the V6-P7-A2 discipline applied to the source slice):

1. **Task binding, checked INSIDE the write transaction (A2-01/02/03):** the
   task must exist, belong to `project_id`, carry the matching template marker
   (`SOURCE_SEARCH` ↔ outcome_kind="search", `SOURCE_FETCH` ↔ "fetch"), be
   RUNNING, and its spec's expected refs must match the outcome's actual refs.
   One-shot acceptance: a task that already produced a *different* outcome is
   refused; an identical re-acceptance stays idempotent. Raises a typed
   binding error, never a raw FK IntegrityError (V6-FINAL-01/02, V6-P7-F03).
   **SD-02 pin — the has-prior probe is source-carrier, not EXTRACT-carrier:**
   the one-shot "already produced" check queries the source outcome rows
   (the persisted artifact records by `task_id`), never the hard-coded
   `research_claims` probe the EXTRACT path uses. **SD2-02 — the one-shot is
a hash-SET COMPARISON, not a bare probe:** the shipped EXTRACT model
(`record_extraction` 3c, `repositories.py:1523`) compares the prior rows'
content-hash SET to the new output's; EQUAL → idempotent reuse (SUCCEEDED),
DIFFERENT → refusal ("one execution, one output"). The source write method
implements the same: prior artifact content hashes by task vs. the new
outcome's hashes — the identical crash-retry case is routed to the SD-04
reuse, never refused by the probe alone.

**OB-01 — the hash-SET MEMBERSHIP is PINNED (third-gate):** the set is (1)
the per-result SEMANTIC content hashes (`content_hash_of_search_result`) PLUS
(2) the OUTCOME-LEVEL record's hash — a NEW deterministic helper, preimage =
canonical(outcome_kind, aggregate, notes, request-log-facts hash); access
TIMESTAMPS and the cursor chain are observation and excluded. For FETCH the
set is the per-source payload content hashes (`sha256(raw_bytes)`) + the
NoFullText evidence-record hashes; the `FetchLogEntry` stream
(`attempts`/`attempt_verdicts`/timestamps) is OBSERVATION and NEVER enters the
set. A changed aggregate (COMPLETE→SHORTFALL/UNAVAILABLE) or a fetch that now
succeeds where it failed is DIVERGENT → one-shot refusal; identical semantic
content with changed observation metadata is IDENTICAL → reuse (the P0
crash-retry invariant, enforced at BOTH the search and fetch layers).
**OB-02 — the REUSE branch re-verifies the PERSISTED row before reusing:**
reconstruct the record from the row's metadata, recompute BOTH hashes, compare
against the row's `content_hash` column AND the metadata's stored
`observation_hash`; the retry's OWN observation_hash is never compared
(identical-by-design), but a semantically-identical-but-observation-tampered
row FAILS the reuse with a typed integrity error — not merely the later
dereference (check 3).
2. **Project-existence check** (V6-P7-F03) — resolved inside the method, never
   trusted from the caller.
3. **Integrity boundary (EC-V6 / ADV-01/06 discipline):** every persisted
   identity is re-derived with the same helpers inside the method — the
   `SearchResult` content hash via `content_hash_of_search_result` (preimage
   EXCLUDES `content_hash`, ADV-01), the `FetchedPayload` artifact id via
   `sha256(raw_bytes)` — and any mismatch fails closed before the write.
4. **Atomic persistence + provenance — TWO transactions, not one (SD-03):**
   the outcome rows (D4/D5) + the §14 provenance edges (task → outcome
   artifact; search task → fetch task → per-source artifacts) commit in ONE
   transaction. The task's `SUCCEEDED` transition is NOT in that transaction:
   the controller owns it, transitioning after the handler returns — the
   EXTRACT precedent (`accept_extraction_output` writes rows; the controller
   transitions). Rationale: `transition_status` validates the from-status and
   SUCCEEDED is terminal — a write method that also transitioned would
   double-transition and crash the tick. The two-step is exactly what makes
   the crash-mid-acceptance chain (D8) the natural recovery case: rows
   committed, task still RUNNING → the NO_SIGNAL ladder finds it. No half-
   state within each transaction (event failure → rollback; crash-mid-write →
   nothing committed).
5. **Dereference contract (V6-FINAL-02, FD-05):** every `request_log_ref` /
   `source_ref` / artifact id written must resolve to a row written in the
   same transaction — a ref that cannot resolve fails, never dangles. The task
   write path is the **sole dereference point** for `FetchedPayload` bytes.
   **SD-05 pin — the resolver extension:** the shipped
   `_dereference_artifact_ref` (`repositories.py:1331`) dereferences
   `dataset_manifest:<id>` concretely and form-checks every other type; this
   step lands the source artifact type against the `artifacts` table
   (project-scoped) so a missing ref FAILS — the resolver's own docstring
   names it "the single extension point as those stores land". **SD2-04 —
   the resolver keys the FULL content hash and the forms are named:** the
   lookup is `content_hash` (the table's UNIQUE, full-length), NEVER the
   truncated `"art_" + content_hash[:24]` alias (the FD-05 in-phase alias is
   not a unique key); the ref forms are pinned — `source_result:<id>` where
   `<id>` is the FULL content hash of the canonical SearchResult JSON (the
   OQ-1 lossless round-trip), and the fetched artifact rows carry a NAMED
   `artifact_type` (the extraction pipeline cites these as `source_ref`s, so
   the type names are contract).
6. **SD-04 pin — the idempotent record branch:** the artifact write is
   get-by-hash-first, inside the write transaction: `get_by_hash(content_hash)`
   → if present, verify `sha256(raw_bytes) == content_hash` and REUSE the
   existing row (atomic re-admission, FD-03); else insert. The shipped
   `ArtifactRepository.record` is a plain INSERT (no ON CONFLICT) and
   `content_hash` is UNIQUE — a duplicate insert raises IntegrityError, the
   opposite of idempotent. The branch is pinned here and implemented in the
   write method, never left to the caller. **SD2-01 — the reuse is
   (project, task, bytes)-keyed:** `content_hash` UNIQUE is GLOBAL (migration
   1), so a SECOND project retrieving identical bytes hits the first project's
   row — reusing it would misbind the row's `task_id`/`project_id`. Reuse
   ONLY the crash-retry case (same task, same project, identical bytes); a
   get-by-hash hit from a different project/task raises a typed
   `SourceOutcomeConflictError` (never silent, never misbound). Cross-project
   identical content (a real scenario the GLOBAL UNIQUE cannot represent with
   per-row task bindings) is explicitly DEFERRED to a later slice.

---

## 6. D4 — SearchOutcome routing (decision with an open carrier question)

The SearchOutcome (per-provider `SearchResult` stream + aggregate + notes +
`RequestLogRecord`) becomes durable through the **existing `artifacts` table**
— no new table (blueprint §5.3).

**DECIDED:** each `SearchResult` is persisted as its own durable record with
its content hash + the redacted request-log facts in its provenance (§14 edge
from the outcome), so a later extraction task can cite it with the Hermes
`source_ref` form (`artifact_type:ref`) and the dereference contract can
resolve per-source. The aggregate + notes + the walk's `RequestLogRecord`
facts ride the outcome-level record's metadata (the verdict-note convention is
preserved verbatim — `COMPLETE(...)` / `SHORTFALL(cause=...)` / `UNKNOWN(...)`
— so a downstream reader never infers full-text success from the aggregate,
PS3-04).

**RULED (OQ-1, hostile gate): PER-RESULT rows** — `artifact_type="source_result"`
per SearchResult (content-hashed canonical JSON metadata), conditioned on TWO
pins: (a) **the SD-05 resolver extension** (a `source_result:<id>` ref must
actually resolve against the `artifacts` table, or fail) and (b) a **lossless
round-trip** — the persisted metadata reconstructs the `SearchResult` exactly
(the fetch task resolves its fetch input from the persisted outcome; a lossy
carrier breaks the fetch task's input and the write path's re-hash check). The
outcome-level record (`artifact_type="source_search"`) carries the aggregate +
notes + the walk's `RequestLogRecord` facts (OQ-4 — single copy, F1 memory
discipline; per-source provenance edges reference the outcome record, so
`request_log_ref` resolves). The outcome record's content hash is the
**outcome-record hash** (OB-01 — the one-shot SET's second member; the new
deterministic helper over canonical(outcome_kind, aggregate, notes,
request-log-facts hash); observation timestamps excluded). The verdict-note convention is preserved verbatim
(`COMPLETE(...)` / `SHORTFALL(cause=...)` / `UNKNOWN(...)`) — a downstream
reader never infers full-text success from the aggregate (PS3-04).

---

## 7. D5 — FetchOutcome routing: `FetchedPayload` → `ArtifactRepository`

The fetch path persists exactly the transient carrier's contents (A1 — "the
artifact-store entry the task write path will persist"):

- Each `FetchedPayload` → `artifacts/store.py` (raw bytes → filesystem) +
  the idempotent record branch (D3-6 / SD-04: get-by-hash-first, inside the
  write transaction — reuse the existing row when the bytes match, else
  insert), **dereference-by-`artifact_id`** (GC-02 — never positional), with
  `producer` = the fetch task, `task_id` set, `content_hash` =
  `sha256(raw_bytes)` (FD-06 cross-check pinned by the fixtures).
- The idempotency engine is the **get-by-hash-first branch (SD-04)**, NOT the
  `content_hash` UNIQUE constraint alone: the shipped `ArtifactRepository.record`
  is a plain INSERT (no ON CONFLICT), so a duplicate would raise
  IntegrityError. A crash-retry re-fetch producing identical bytes →
  `get_by_hash` hit → verified reuse → one artifact row, no duplicate
  (FD-03).
- `NoFullText` sources are recorded as resolved-without-text (a result, never
  a failure — PS2-01); `FetchFailure` sources are recorded as failed with
  their class + reason (never silent, F12 — the failure object carries no
  body/header/URL).
- The fetch log (`FetchLogEntry` stream, F6 attempts/verdicts) rides the
  outcome record's metadata with the redaction facts — the recorder
  persistence itself stays deferred (AR-02). **OB-01 (fetch) — the FETCH
one-shot SET is pinned:** per-source payload content hashes
(`sha256(raw_bytes)`) + the NoFullText evidence-record hashes ONLY; the
`FetchLogEntry` stream is observation and never gates idempotency — identical
payloads with changed attempts/verdicts/timestamps stay IDENTICAL.

---

## 8. D6 — Journaling without new events

The producing task's existing `TaskCreated` / `TaskStatusChanged` events +
the immutable artifact rows + the §14 provenance edges are the audit trail —
exactly the IDR-028 Decision 3 precedent. The `model_ref` / producer fields on
the rows carry the provenance facts. **No new event type is ever emitted.**

---

## 9. D7 — What the write path must NOT do

- Promote evidence (`SUPPORTED`/`ROBUST`/`REPLICATED` are the Evidence
  Ladder's — out of scope, no surface here).
- Pass or fail a human gate (gates run through the controller's GATE/HUMAN_GATE
  classification; a search/fetch task is an ordinary AGENT_TASK).
- Create tasks (the planner does; a handler never emits `INSERT_TASK`).
- Set any task status beyond the controller's `transition_status` transitions.
- Bypass the gateway (admission is `INSERT_TASK`; the payloads are built by
  the deterministic builders and admitted through the ordinary path).
- Call the drivers with unvalidated input (the fetch entry checks + the
  valid_negative/duplicate rejections are the driver's own boundary; the task
  layer passes the persisted refs, never hand-authored lists).

---

## 10. D8 — Recovery semantics

- **Crash-mid-acceptance (IDR29-01 remediation):** a RUNNING task with
  persisted rows is recovered through the ratified ladder — lease expiry →
  NO_SIGNAL → FAILED → RETRYING → RUNNING (v4 §19); the discovery path is
  the existing `_recovery_pass`, NOT the READY-with-SUCCEEDED-deps path (the
  crashed task is RUNNING, not READY). The record pins this chain explicitly.
- **SD-02 — the re-execution is TEMPLATE-GENERIC, not EXTRACT-hardwired:** the
  shipped `_requeue_recovered` → `_re_execute_requeued` calls
  `_execute_extract` unconditionally (`controller.py:455–477`) — a requeued
  source task would be re-executed as an EXTRACT task. The pinned change: the
  re-execution pass re-dispatches each requeued task through the SAME execute-
  ONLY per-template path (classify → EXTRACT → `_execute_extract` /
  handler-backed → `handler(ctx)` (the typed `SourceTaskExecutionContext`,
HD-02) / gate → gate path), so a
  requeued SOURCE_SEARCH/SOURCE_FETCH task is re-executed by ITS OWN handler.
  **SD2-05 — execute-ONLY, never a re-claim:** `_requeue_recovered` already
  transitioned the task to RUNNING, so the re-execution must NOT re-enter the
  `_dispatch_pass` claim (RUNNING→RUNNING is an invalid from-status); it calls
  the execute-only per-template function (`_execute_extract` is exactly that
  shape — it reads the task and executes without claiming), preserving each
  template's error semantics (the EXTRACT IDR29-02 binding-error split; the
  source binding errors for the source tasks).
- **Idempotent re-acceptance:** a retried task re-fetches; identical bytes →
  identical artifact id → the get-by-hash-first branch reuses the existing row
  (FD-03, SD-04). One-shot acceptance keys on the OUTPUT identity, not the
  attempt count — the A2-03 idempotency survives the retry attempt increment
  (keyed on `producing_task_id`, the shipped `_requeue_recovered` comment).
- **Stale lease / fencing (ADV-02):** all writes go through the fenced
  connection; a reclaimed generation raises `LockLostError` and rolls back.
- **Mode:** a non-ACTIVE project dispatches nothing (the controller's mode
  check — a `WAITING_HUMAN`/paused project stops the wave before any handler
  runs).
- **Unhandled classes:** an unknown template or an unclassifiable outcome is
  left with a diagnostic (`unhandled`), never silently SUCCEEDED.

---

## 11. D9 — Failure semantics per class

| Failure | Surface | Disposition |
|---|---|---|
| `RetrievalShortfallError(EMPTY)` / `ProviderUnavailableError(UNAVAILABLE)` from `combine()` | search | typed outcome recorded with its aggregate + notes (the walk's verdict-note convention); task FAILED via the controller's retry policy |
| transient provider failure (timeout/throttle) | drivers | driver-level retry (backoff/limiter) — unchanged |
| daily-cap `False` | fetch | FD-02 batch stop + cap note; **RULED (OQ-3) — NO auto-requeue**: the task FAILED with the cap cause and is not requeued by the retry policy (a RETRYING re-execution would re-fetch against the exhausted UTC window within the tick — the AR-02 class; the cap resets on the limiter's UTC window, not on the task retry cadence). Re-arm is the planner's/human's after the window |
| permanent failure | drivers | typed `FetchFailure`/permanent verdict — recorded, never silent |
| adapter-hook `ProviderError` | handlers | loud (FC-01 discipline) — the handler's `except Exception` fail-closed path marks FAILED with the reason |
| binding violation / integrity mismatch | write path | typed binding/integrity errors, zero rows written |
| event failure / crash mid-write | write path | transaction rollback — no half-state |

---

## 12. D10 — Golden-fixture plan (`tests/test_provider_orchestration.py`)

The step-6 acceptance gate (green before any step-7 review):

1. `SOURCE_SEARCH` handler runs `walk`+`combine` and records a COMPLETE outcome
   (per-result refs resolve; request-log facts persisted).
2. `SHORTFALL` / `EMPTY` / `UNAVAILABLE` aggregates are recorded typed, never
   silent (the `combine()` raises caught as outcomes).
3. `SOURCE_FETCH` depends on its search task; the fetch input resolves from the
   persisted outcome, never from a hand-authored list.
4. `FetchedPayload` → artifact store; `sha256(raw_bytes) == content_hash` ==
   the artifact row (FD-06); dereference-by-`artifact_id` (GC-02).
5. Crash-retry re-fetch is content-idempotent — identical bytes → one artifact
   row (FD-03); a DIFFERENT output from the same task is refused (one-shot).
6. Task-binding violations (wrong template, wrong project, not RUNNING, mismatched
   refs) fail with typed errors, zero rows written (A2).
7. No new events: only `TaskCreated`/`TaskStatusChanged` for the producing
   task; the artifact rows + §14 edges are the audit trail.
8. No evidence promotion, no gate passage, no status beyond the ratified
   transitions — the search/fetch path cannot touch the Evidence Ladder.
9. A stale-lease write fails closed (fenced connection) — the ADV-02 probe
   applied to the outcome write.
10. Unhandled template / unknown provider fails at admission or dispatch,
    never silently.

SD-01…SD-05 fold-in fixtures (each probe from the audit, now a green test):

11. **SD-01** — the dispatch-threaded handler receives the CURRENT fence: a
    handler writing through a stale/fabricated fence fails closed
    (`LockLostError`, rollback); the same write through the dispatched fence
    commits (ADV-02 applied to the source write).
12. **SD-02** — a requeued SOURCE_SEARCH task (via the NO_SIGNAL → FAILED →
    RETRYING → RUNNING ladder) is re-executed by ITS OWN handler (never
    `_execute_extract`); the re-execution is content-idempotent.
13. **SD-03** — the two-transaction shape: rows + §14 edges commit, then the
    controller transitions SUCCEEDED; a crash between the two leaves
    RUNNING-with-rows, which the ladder recovers (no double-transition, no
    wedged task).
14. **SD-04** — the get-by-hash-first branch: an identical re-fetch → ONE
    artifact row (no IntegrityError); a divergent re-execution → one-shot
    refusal, zero new rows.
15. **SD-05** — `source_result:<id>` dereferences against the `artifacts` table:
    a missing ref FAILS the write (never a form-checked pass).

SD2-01…SD2-05 second-gate pins (2026-08-14):

16. **SD2-01** — a cross-project identical content (same bytes, different
    project/task) raises `SourceOutcomeConflictError` — the reuse is never
    misbound; the same-project/same-task crash-retry still reuses.
17. **SD2-02** — the hash-SET comparison: a crash-retry with identical content
    → idempotent reuse + SUCCEEDED; a divergent re-execution → one-shot
    refusal (the EXTRACT `record_extraction` 3c model).
18. **SD2-03** — the wiring negative: a handler factory handed a raw `conn`
    fails the wiring test (never runs); the dispatched `fenced`/`repos` are
    the only DB handles.
19. **SD2-04** — the resolver keys the FULL content hash (a truncated-alias
    ref FAILS); `source_result:<full-hash>` and the named fetched
    `artifact_type` resolve project-scoped.
20. **SD2-05** — a requeued task's re-execution never re-claims (no
    RUNNING→RUNNING); the execute-only per-template dispatch preserves the
    EXTRACT binding-error split.

Observation-hash verification probe (2026-08-14 — the P0 write-path pin):

21. **Tamper vs retry** — a persisted `source_result` row whose OBSERVATION
    field is mutated (timestamp/counts edited, semantic fields untouched)
    recomputes the SAME `content_hash` (content_hash ALONE cannot detect it —
    the gate §17 metadata/data-mismatch class) but FAILS the
    `observation_hash` re-verification at the write path/dereference; and a
    crash-retry with legitimately different observation metadata is IDEMPOTENT
    (same semantic hash-SET — observation differences are expected and never
    gate the one-shot).

Third-gate pins (2026-08-14 — the OB/HD fold-in, `…design_audit3.md`):

22. **OB-01a (outcome divergence)** — a crash-retry with identical per-result
    semantic hashes but a CHANGED aggregate (COMPLETE → SHORTFALL) is
    DIVERGENT → one-shot refusal, zero new rows; identical semantic +
    identical aggregate is IDENTICAL → reuse.
23. **OB-01b (fetch log is observation)** — a re-fetch with identical payload
    bytes but changed `FetchLogEntry` attempts/verdicts/timestamps is
    IDENTICAL → reuse (the P0 invariant re-broken if the log stream entered
    the SET).
24. **OB-02 (tampered-row reuse refusal)** — a persisted `source_result` row
    with an observation field edited (semantic fields untouched) fails the
    REUSE path's re-verification (both hashes recomputed vs the stored
    values) with a typed integrity error — not merely the later dereference.
25. **HD-01 (fence delegation surface)** — `fenced.cursor()` is REJECTED
    loudly and never lands a row; `fenced.commit()`/`rollback()` cannot
    commit/rollback a repository's open transaction; the no-cursor-write
    negative probe.
26. **HD-02/HD-03 (bundle surface)** — the dispatched
    `SourceTaskExecutionContext` exposes NO connection attribute; the repos
    inside are built over `self._fenced` in `_refresh_fence` (`repos._conn IS
    fenced` identity assert); a stale-generation bundle fails closed on the
    source write.
27. **OB-05 (lossless round-trip with coercion)** — persist → resolve →
    reconstruct → `SearchResult' == SearchResult` on identity AND observation
    fields (authors coerced to tuple; dicts/None preserved) AND the
    observation_hash re-verifies.

---

## 13. D11 — OQ rulings (hostile gate, folded in 2026-08-14)

The six open questions are RULED; the rulings are binding on implementation:

- **OQ-1 (carrier) — PER-RESULT rows** (`artifact_type="source_result"`),
  conditioned on the SD-05 resolver extension + a lossless SearchResult
  round-trip (§6); the outcome-level `source_search` record carries the pinned
  outcome-record hash (OB-01).
- **OQ-2 (templates) — TWO templates** (`SOURCE_SEARCH` → `SOURCE_FETCH` via a
  task-dependency edge). The shipped `_discover_eligible` gates on
  deps-SUCCEEDED, so the edge works with zero discovery changes; a single
  template would need an internal phase machine (a second scheduler shape) —
  rejected (§4).
- **OQ-3 (cap interplay) — NO auto-requeue**: a `daily_cap_exhausted` fetch
  task FAILED with the cap cause, never requeued by the retry policy (RETRYING
  would re-fetch against the exhausted UTC window — the AR-02 class); re-arm
  is the planner's/human's after the window (§11).
- **OQ-4 (log carrier) — outcome-level metadata**: the redacted
  `RequestLogRecord` / `FetchLogEntry` facts ride the outcome record's
  metadata (single copy, F1); per-source provenance edges reference the
  outcome record, so `request_log_ref` resolves (§6).
- **OQ-5 (admission validation) — YES, at INSERT_TASK time**: the gateway
  enforces the canonical normalized marker + pinned profile (RESEARCHER/C-
  tier) + scope + cost_class + provider-allowlist membership + positive
  bounds — the exact V6-P7-E01/E02 precedent (`_is_extract_spec` +
  `_validate_extract_source`). A hand-built payload cannot case-spoof past
  admission (§2/§4).
- **OQ-6 (sizing) — builder-carried bounds**: the deterministic payload
  builders carry explicit `max_pages`/`max_sources`/`size_cap_bytes` derived
  from the scope/requirement (S11 scale classes); the fetch envelope's real
  control is the task's own `FetchRequest` sizing (GC-03); over-bound requests
  are rejected at admission (OQ-5), never at execution (§4).

---

## 14. Non-negotiables (survive any fold-in)

- One execution surface (the controller), one write method, one mutation path.
- The drivers remain read-only and unchanged by this step.
- No new tables, no new events, no new intents, no new scheduler, no graph
  database.
- Every persisted identity is re-derived at the write path (ADV-01/06).
- Every ref dereferences (V6-FINAL-02); a dangling ref fails.
- Search/fetch outcomes are inputs, never evidence; the aggregate is a
  resolution signal, never a full-text-success signal (PS3-04).
- The slice remains NOT ratified-as-implemented until step 7's adversarial
  review + the §27 item 55 record.
