# Step 6 — Task-Side Orchestration — Second-Gate Hostile Review
**Scope:** the SD-FOLDED design record (`hermes_researchsourceprovider_step6_orchestration_design.md`,
post-fold-in). Attacked ONLY the five fixed surfaces — the dispatch-threaded
handler contract (SD-01), the template-generic re-execution (SD-02), the
two-transaction write (SD-03), the get-by-hash idempotent branch (SD-04), the
resolver extension (SD-05) — for the same bypass and silent-failure classes.
All claims checked against the shipped code (`record_extraction`'s exact
one-shot mechanics, `_refresh_fence`, the artifacts schema). No code written.
**Verdict: MERGE WITH REMEDIATION (second round)** — five precision pins
(SD2-01…SD2-05, all P2/P3); the five folded surfaces hold under the attack;
one SD-01 rationale corrected (the stale-fence danger was overstated).

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| SD2-01 | **P2** | SD-04 idempotent branch | The `content_hash` UNIQUE is GLOBAL — a second project fetching identical bytes hits the existing row; the reuse must be (project, task, bytes)-keyed; a cross-project duplicate raises a typed conflict, never a misbound reuse |
| SD2-02 | **P2** | SD-02 one-shot | The fold-in pins the has-prior probe but not the identical-vs-different COMPARISON — the shipped EXTRACT model is a content-hash-SET comparison; without it a crash-retry with identical content is refused (or ambiguously succeeds) |
| SD2-03 | **P2** | SD-01 dispatch-threaded | The fence-threading is a WIRING discipline, not structure — the handler factory must take no raw connection, and the per-tick repos bundle's build site (`_refresh_fence`) must be pinned; the SD-01 stale-capture rationale is corrected (a stale fence fails closed by the LIVE generation check) |
| SD2-04 | **P3** | SD-05 resolver | The dereference must key on the FULL content hash (the artifacts UNIQUE), never the truncated `"art_" + hash[:24]` alias; the `source_result` id form + the fetched artifact_type name are unpinned |
| SD2-05 | **P3** | SD-02 re-execution | The template-generic re-execution must be execute-ONLY (no claim — the requeued task is already RUNNING; reusing the `_dispatch_pass` loop would re-claim RUNNING→RUNNING, an invalid from-status), preserving per-template error semantics (the IDR29-02 split) |

## Detail

### SD2-01 (P2) — the get-by-hash reuse is project-blind as written

The fold-in pins: *"get_by_hash(content_hash) → if present, verify
`sha256(raw_bytes) == content_hash` and REUSE the existing row."* The shipped
`artifacts.content_hash` is **`NOT NULL UNIQUE`** — GLOBAL, not per-project
(migration 1). Two projects legitimately retrieving the same paper (a standard
literature-review case) produce identical bytes → identical hash → the second
project's get-by-hash hits the FIRST project's row. Reusing it would persist
the second task's output as the first project's artifact row — the `task_id`/
`project_id` binding (the A2 discipline: "the task id is persisted on every
row") would be wrong, and a second INSERT is impossible (UNIQUE).

**Pin:** the reuse is **(project_id, task_id, bytes)-keyed** — reuse ONLY the
crash-retry case (the same task, same project, identical bytes). A get-by-hash
hit from a different project or task raises a typed `SourceOutcomeConflictError`
(never silent, never a misbound reuse). Cross-project identical content is a
real scenario the GLOBAL UNIQUE cannot represent with per-row task bindings —
a later-slice decision (per-project uniqueness or an artifact-sharing row),
explicitly DEFERRED here, not silently resolved.

### SD2-02 (P2) — the one-shot needs the identical-vs-different comparison

The fold-in pins the has-prior probe ("queries the source outcome rows … never
the hard-coded `research_claims` probe"). But the shipped EXTRACT one-shot
(`record_extraction` 3c, `repositories.py:1523`) is NOT a bare probe — it is a
**content-hash-SET comparison**: `existing = {content_hash of prior rows}` vs
`proposed = {content_hash of the new output}`; **equal → idempotent reuse**
(the per-row UNIQUE collapse absorbs it), **different → refusal** ("one
execution, one output").

The source slice needs the same comparison in `record_source_outcome`: prior
artifact content hashes by task vs. the new outcome's hashes. As written, the
has-prior probe alone would refuse a legitimate crash-retry re-execution
(identical content) — or the write method would have no defined behavior for
the identical case. **Pin:** the has-prior probe is the REFUSAL side; the
identical case is detected by the hash-set comparison and routed to the
SD-04 reuse (idempotent SUCCEEDED), exactly the EXTRACT precedent.

### SD2-03 (P2) — the fence-threading is a wiring discipline; pin the wiring

The dispatch-threaded `handler(task, fenced, repos)` hands the handler a fence
— but nothing in the shipped controller STRUCTURALLY prevents a handler from
writing through a raw/captured connection. Two pins:

1. **The handler factory takes NO connection.** The wiring contract: the
   factory receives only the tick-independent provider machinery (adapters,
   transport, limiter, recorder, clock, redaction) — a raw `conn` is refused
   at wiring time, and fixture 11's negative case asserts it (a handler wired
   with a raw conn fails the wiring test, never runs).
2. **The per-tick repos bundle's build site is `_refresh_fence`** — the ONLY
   shipped place the repos are rebuilt per acquisition (`controller.py:309`).
   The source slice's `ArtifactRepository` + the outcome-recording repo join
   that rebuild; the design's "per-tick repository bundle" must name the site.

**Corrected analysis (SD-01 rationale):** `_FencedConnection._assert_lock_valid`
reads the controller's **LIVE** `_lock_generation` (set on every acquisition),
so a fence/repos bundle from a PREVIOUS tick fails closed in every
generation-change case (reclaim → generation bump → `LockLostError`); a
same-owner re-acquisition keeps the generation, so a stale bundle would pass —
but legitimately (the controller owns the lock). The stale-capture danger in
SD-01 was therefore overstated: the REAL hazard was the constructor `None`
(crash, not silent write). The dispatch-threaded fix remains correct and clean;
this review confirms no write bypass exists in the shipped fence mechanism
itself.

### SD2-04 (P3) — the dereference must key the FULL hash, and the ref forms are unpinned

The fold-in pins the resolver extension against the `artifacts` table
(project-scoped). Two forms are still unpinned:

1. The fetch artifact_id is the **truncated** `"art_" + content_hash[:24]`
   (the FD-05 in-phase alias). The resolver must key the `content_hash` column
   (the table's UNIQUE, full-length), never the truncated alias — a 24-hex
   prefix has a (tiny but nonzero) collision space, and the resolver should be
   deterministic on the unique key.
2. The ref forms themselves: `source_result:<id>` — the id is the FULL content
   hash of the canonical SearchResult JSON (per OQ-1's lossless round-trip);
   the fetched artifact `artifact_type` name must be named (the design writes
   "the fetched artifact type" — unpinned). The extraction pipeline cites
   these as `source_ref`s, so the type names are contract.

### SD2-05 (P3) — the re-execution is execute-ONLY

The fold-in: *"re-dispatches each requeued task through the SAME per-task
execute path the normal dispatch uses."* Careful: `_requeue_recovered` already
transitioned the task to RUNNING — the requeued task must NOT be re-claimed.
Reusing the whole `_dispatch_pass` loop would claim it again (RUNNING→RUNNING,
an invalid from-status — `validate_task_transition` rejects it). The EXTRACT
precedent is execute-ONLY: `_execute_extract` reads the task and executes
without claiming. **Pin:** the template-generic re-execution dispatches the
execute-ONLY per-template function (classify → `_execute_extract` /
`_execute_source_*` / gate path) with each template's error semantics preserved
(the EXTRACT IDR29-02 binding-error split; the source binding errors for the
source tasks). The "SAME per-task execute path" language is amended to
"the SAME execute-ONLY path".

## What survives — verified against the shipped code, not assumed

- **The one-shot model is fully implementable:** `record_extraction`'s
  BEGIN-IMMEDIATE-first → binding reads → hash-set comparison → per-row
  UNIQUE-collapse reuse is the exact template for `record_source_outcome`
  (A2-02 TOCTOU closure confirmed: reads inside the transaction).
- **The two-transaction shape is consistent:** the handler's rows commit, then
  the controller transitions SUCCEEDED; a transition failure (fence lost)
  leaves RUNNING-with-rows → the NO_SIGNAL ladder recovers it; the committed
  rows are content-addressed and idempotent, never a half-state.
- **The fence mechanism has no write bypass:** the LIVE-generation check makes
  every stale-fence scenario fail closed (corrected analysis, SD2-03).
- **The get-by-hash branch matches the shipped collapse precedent** — the
  identical-content reuse is the source slice's analogue of the per-row UNIQUE
  collapse `record_extraction` already performs.
- **The discovery + ladder + mode + registry surfaces** were verified in the
  first gate and remain unaffected by the fold-in (no changes to them).

## Overall verdict

**MERGE WITH REMEDIATION (second round).** The five folded surfaces hold
under the attack; the findings are precision pins that make the fold-in
implementable without ambiguity — not a redesign:

- SD2-01 and SD2-02 are the sharpest (P2): the idempotent branch must be
  (project, task, bytes)-keyed and the one-shot must use the hash-set
  comparison, both against the shipped EXTRACT model.
- SD2-03 (P2) pins the wiring discipline + the build site, with the SD-01
  rationale corrected (no bypass existed in the fence; the fix was for the
  None case + cleanliness).
- SD2-04/05 (P3) pin the ref forms and the execute-only re-execution.

The fold-in of SD2-01…SD2-05 (a few sentences in §3/§5/§10/§13 + the D10
fixtures) is the standing condition before any step-6 code — the three-gate
pattern that carried steps 1–5a.

---

**Probe evidence:** `repositories.py` (`record_extraction` 3c one-shot,
`:1523–1547`; BEGIN-IMMEDIATE-first binding, `:1478–1522`),
`migrations.py` (artifacts `content_hash NOT NULL UNIQUE`, migration 1),
`controller.py` (`_refresh_fence` :309, `_assert_lock_valid` live-generation
read, `_requeue_recovered` RUNNING transition, `_dispatch_pass` claim).
Suite unchanged: **837 passed, `uvx pyright src` 0 errors** (design-only
review; no production code touched).
