# HERMES RESEARCH — Q-04 DEPENDENCY / FAILURE GRAPH
## DESIGN GATE (reconciliation + first-slice design; NOT implemented)

**Status:** DESIGN GATE COMPLETE — first slice **DESIGN READY FOR
IMPLEMENTATION**; artifact-level edges **DEFERRED**. No implementation in
this task (Q-04 remains unimplemented; the design is architecture input for
a future phase, gated behind Q-05/Q-02 like every other surviving idea).

**HEAD reconciled against:** the working tree at the Q-02 completion-write
commit chain (`e90e8e4`, `53bc729`), full suite **1076 passed**, pyright 0.

---

## 1. Role and gate question

Q-04's surviving idea (framework §D.4, §H): *"if A is rejected/patched/
changed, what else is affected"* — forward reachability, distinct from
provenance (where something came from). The framework's OWN phase-0 gate
(§M): *if the existing provenance graph already computes reverse traversal
over derived_from edges, Q-04 collapses to a new query; otherwise it needs
edge types.* This document runs that gate against the LIVE repository and
designs the first slice that survives it.

---

## 2. Reconciliation against the live repository (verified facts)

1. **Task dependency graph exists and is authoritative for scheduling.**
   `task_dependencies` (task_id → depends_on_task_id) is **insert-only**
   (the only write is at task creation, `repositories.py` `TaskRepository.
   create`), `UNIQUE(task_id, depends_on_task_id)`, `CHECK (task_id !=
   depends_on_task_id)`. `src/hermes/core/graph.py` provides pure query
   helpers: `is_ready` (LOCAL readiness — all deps SUCCEEDED, INVALIDATED
   is a permanent block), `detect_cycle` (F-11 DFS), and iteration
   subgraph filtering. Domain code never touches SQL (IDR-007).
2. **The controller's eligibility check is LOCAL, not transitive.**
   `_discover_eligible` gates a task on its DIRECT deps being SUCCEEDED
   (NOT EXISTS a non-SUCCEEDED dep). Nothing in the repo computes the
   FORWARD closure — "which downstream tasks are transitively blocked if
   this task fails/retires/gets patched" is not answered anywhere.
3. **Artifact lineage exists but is a different layer.** `provenance_edges`
   (migration) carries typed artifact edges `cites`, `derived_from`,
   `supersedes`, `used_as_input`, `justifies` — inserted by the source
   slice and the Q-05 classification write. It is read for dereference
   checks; the gateway docstring still calls provenance lineage "the
   future authoritative mechanism."
4. **Failure state is recorded, task-bound, advisory.** Q-05 stores
   failure classifications as task-bound metadata with a read-only,
   corruption-observable digest (`classifications_digest`, v2). The
   controller never writes classifications; the digest is Director-visible.
5. **Recovery is owned by IDR-029 Decision 4.** The ladder (NO_SIGNAL →
   FAILED → RETRYING → re-execute) is the ONLY authority that resurrects a
   failed task; requeue never re-enters the eligible set.

**Phase-0 gate result:** the existing graph does NOT answer forward
reachability, so Q-04 is a real gap — but the FIRST slice needs **no new
edge types and no new table**: `task_dependencies` already IS the ratified
`depends_on` edge set for the scheduling layer, and failure propagation
over it is a deterministic traversal over ratified state.

---

## 3. First-slice design — derived task-level failure propagation

### 3.1 Sources of truth (all ratified; nothing stored is derived — F2)

| Fact | Ratified source | Read authority |
|---|---|---|
| edge set (depends_on) | `task_dependencies` (insert-only) | read-only SELECT |
| node state | `tasks.status` (state machine, `transition_status`) | read-only |
| failure label (why) | Q-05 `failure_classifications` via `classifications_digest` | read-only digest |

### 3.2 The derivation (pure, deterministic, recomputed per query)

A forward traversal over `task_dependencies` from a seed task set,
following OUTGOING edges (task → its dependents) transitively. The
predicate is the TRANSITIVE version of the controller's own eligibility
predicate — the graph never invents a new blocking rule:

- a dependent is in the cone iff it has a path from a seed through edges
  where the edge's source node is NOT SUCCEEDED (a failed/retrying/pending
  ancestor blocks the path);
- each cone entry is labeled with the first blocking ancestor and THAT
  ancestor's status (+ Q-05 classification label when the digest has one);
- traversal is cycle-defensive (visited set — a hand-inserted 2-cycle must
  terminate) and deterministic (sorted task_ids, stable ordering).

Outputs (all advisory):

1. `failure_cone(seed_task_ids)` → `{task_id: (blocking_ancestor,
   blocking_status, classification_label|None)}` — the framework's
   concrete use case: on any FALSIFIED / retracted / failed source,
   identify every downstream task needing re-review.
2. `blocked_roots(project_id)` → tasks whose dependency closure contains a
   TERMINAL FAILED ancestor (permanently blocked until the failure is
   resolved by IDR-029 or a new iteration) — distinct from transiently
   blocked (RETRYING ancestor still on the ladder).
3. `change_blast_radius(proposed_change)` → the advisory "what would this
   affect" surface for the Director, over the same edges.

### 3.3 Determinism and versioning

- `GRAPH_QUERY_VERSION = "1"` bound into every result hash
  (`sha256` of the sorted result payload), mirroring the Q-05 digest and
  Q-02 ranking identity patterns: same state + same query version ⇒ same
  result identity. Results are NEVER persisted — recomputed per query, so
  there is no stored-version drift to invalidate.
- No clock, no random, no LLM input in the traversal (model boundary
  §J: deterministic code owns traversal; only edge EXISTENCE for the
  deferred artifact edges may involve judgment).

### 3.4 Consumption (read-only; no new authority)

- The Director consumes `failure_cone` / `blocked_roots` /
  `change_blast_radius` as advisory surfaces — exactly the
  `classifications_digest` precedent (derived, hashed, read-only).
- The controller MAY attach a note when a dispatch attempt is blocked by a
  cone whose blocking ancestor carries a Q-05 classification ("blocked by
  research_program:...: task FAILED — IMPLEMENTATION_FAILURE") — diagnostic
  only; the eligibility logic is untouched.
- The graph CANNOT block, admit, retract, supersede, or modify anything.

---

## 4. Authority boundary

- **CAN** surface affected downstream objects for re-review, with the
  blocking edge and its failure label.
- **CANNOT** auto-retract, auto-invalidate, auto-fail, or auto-modify
  (framework §G — retraction authority stays where it already lives).
- **CANNOT** change scheduling: `_discover_eligible`, the dependency gate,
  and IDR-029's ladder are untouched. The graph is the TRANSITIVE VIEW of
  the same predicate, not a second gate.
- **CANNOT** write: the slice is a pure derivation + read-only consumption.
  Structural check: no INSERT/UPDATE/DELETE in the module.

---

## 5. Deferred — artifact-level edges (explicitly NOT in this slice)

`conflicts_with` and `introduces_risk` at the artifact/claim level require
(1) new edge types in `provenance_edges` (a schema change) and (2) LLM-
proposed edge existence with justification (model boundary §J) — the
framework's own phase-0 contingency, and the gateway still labels lineage
"the future authoritative mechanism." Deferring them keeps this slice free
of new tables, new authorities, and the LLM-judgment edge-existence path.
When the lineage layer lands, this design's traversal + determinism
contracts extend to it unchanged.

---

## 6. Acceptance tests (specified — to be implemented with the slice)

1. **No false negatives, ≥3 hops:** A→B→C→D chain, A FAILED-terminal →
   cone = {B, C, D} (B's edge labeled by A, C by A/B-first, D by A/B/C-
   first — every dependent present, none missing).
2. **Partial failure isolation:** A SUCCEEDED, B FAILED, C (dep B) + D
   (dep C) in cone; B's sibling task E (dep A only) NOT in cone.
3. **Terminal vs transient:** RETRYING ancestor → dependent transiently
   blocked (label shows RETRYING, recovery ladder active); FAILED-terminal
   → permanently blocked (shows in `blocked_roots`).
4. **Classification label:** a cone entry's blocking ancestor with a Q-05
   classification carries the label from the digest; corrupt/missing
   classification degrades to label None (never a crash).
5. **Cycle defensiveness:** a hand-inserted 2-cycle (A→B, B→A) terminates
   the traversal with deterministic output (visited set).
6. **Determinism:** same state ⇒ byte-identical cone + content hash; two
   queries in any order agree.
7. **No authority:** module contains no write SQL; controller eligibility
   fixtures unchanged (the graph never altered dispatch).
8. **Bounds:** traversal runtime linear in edges (visited set) on a
   realistically-sized graph.

---

## 7. Rejected alternatives

- **Persisted graph table** — rejected (F2: never trust stored derived
  fields; recompute from ratified sources; the graph is a VIEW).
- **New edge types now** — rejected (needs schema change + LLM edge
  existence; deferred per the framework's own contingency).
- **Graph as a scheduler input** — rejected (would be a second authority
  layered on `_discover_eligible`; violates the one-authority rule that
  Q-02 and Q-05 already observe).
- **Auto-retraction / auto-invalidate via the graph** — rejected
  (framework §G is explicit: the graph surfaces, it does not decide).
- **Global reachability scan per tick** — rejected for the consumption
  surfaces (per-query, seeded; a full scan is a Director action, not a
  tick cost).

---

## 8. Non-goals

- No new node types, no new tables, no new edge types, no new events.
- No change to eligibility, gates, the call cap, or the recovery ladder.
- No LLM input into the traversal; no stored derived state.
- Q-04 is NOT implemented in this task; this document is the design gate.

---

## 9. Hostile self-review of THIS gate

> **Does the graph decide which task runs next?** No. The controller's
> `_discover_eligible` is unchanged; the graph is the transitive view of
> the SAME predicate, consumed by the Director as advice. No second
> authority.
>
> **Does it duplicate `core/graph.py`?** No — `is_ready` is LOCAL
> readiness; `detect_cycle` guards creation. Forward closure is computed
> nowhere today (verified by search); the slice adds the missing query to
> the same pure-graph module family.
>
> **Does it trust stored derived state?** No — every output is recomputed
> per query from `task_dependencies` (insert-only) + `tasks.status` +
> the Q-05 digest (itself recomputed). Nothing stored is derived (F2).
>
> **Can a hand-inserted cycle hang the traversal?** No — visited set,
> bounded, deterministic (acceptance 5).
>
> **Does it compete with Q-02's ordering or Q-05's digest?** No — Q-02
> orders ELIGIBLE tasks; Q-04 describes BLOCKED ones. Q-05 labels
> failures; Q-04 labels the blocking edges WITH those labels. All three
> are read-only derivations; the controller remains the only writer of
> task state.
>
> **Does it leak authority by exposing classifications?** No — it consumes
> the same read-only digest the Director already sees.
>
> **Is the deferred edge work secretly required for the first slice to be
> useful?** No — the framework's concrete use case (a failed/retracted
> source ⇒ every downstream needing re-review) is fully answered by the
> task-level cone. The artifact edges are a separate, later capability.

---

## 10. Verdict

**DESIGN READY FOR IMPLEMENTATION (first slice)** — derived, deterministic,
read-only, no new table/edge/event/authority, reconciled against the live
task graph, IDR-029 recovery, and the Q-05 classification digest. The
artifact-level `conflicts_with` / `introduces_risk` edges remain **DEFERRED**
to the provenance-lineage phase. Consistent with the staged discipline:
Q-04 joins Q-09/Q-07/CV-01 as NOT STARTED at the code level; this document
is the design gate an implementation phase will consume.
