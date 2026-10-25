# LIVE-PROJECT-INDEX — a bounded read port for ids the model must cite (OPS-18)

| Item | Value |
| --- | --- |
| Slice | OPS-18 |
| Phase | 1 — design gate (approved); **phase 2 implements it on the same branch.** |
| Base | `main` at `ba61179` (OPS-17 merged; run 10 reached CONCLUSION) |
| Branch | `slice/ops-18-read-port` |
| Date | 2026-10-25 |
| Status | **APPROVED (2026-10-25) with corrections C1/C2 and rulings R1–R6.** The phase-1 note commit is `96d4a43`; this revision records the approval conditions and the live measurement. |

## 0. Decision summary

| Decision | Ruling |
| --- | --- |
| **D1 — shape** | **A: a bounded project index in the stage prompt.** A `runtime.project_index` envelope, appended to each stage's `TaskContext.context` before the stage runs. No capability plane. |
| **D2 — scope** | Project-scoped only. Every durable query binds `project_id = ?`; chain nodes come from the run's in-memory `SubstrateStore` and are filtered on `node.project_id`. The reader has no "all projects" surface. |
| **D3 — freshness** | Read **once per stage**, at stage start, after the previous stage's committed admissions. The envelope is part of the stage's context and therefore checkpointed; a resume replays the same snapshot, the next stage reads fresh. Not per tick. |
| **D4 — bounds** | 40 entries maximum, deterministic order, plus the existing 4 KiB envelope bound. Truncation is explicit: `omitted: N` counts every entry not shown. The envelope is always present, including `{"entries": [], "omitted": 0}` on an empty project. |
| **D5 — authority** | The index is untrusted data with origin `runtime.project_index`. It lists what exists; it is not an authority and does not make an id valid. The gateway remains the only validator. |
| **D6 — cost** | **Live `sars-covid-10` measurement (12 tasks, 0 artifacts, 0 scope briefs, 0 chain nodes in a fresh process): 1,108 bytes / 12 entries.** Growth case (reconstructed): 2,471 bytes for 24 entries; 4,023 bytes at the 40-entry cap for 46 entries (`omitted: 6`); 26 bytes empty. M1 moves by the envelope bytes per model call; the LOOP baseline does not move. |

The short version: expose the project's ids as one bounded, project-scoped,
content-free list; do not build the capability plane yet; do not let the index
become an authority.

## 0.1 Phase-2 corrections and rulings

### C1 — chain nodes are not durable

`SubstrateStore.nodes` is an **in-memory dict** (`methodology/substrate.py:522-536`),
not a table. The durable part of the index is exactly the three SQL reads
(`tasks`, `artifacts`, `scope_briefs`); the `chain_node` entries come from the
store object the run already holds. Consequences:

- A fresh process sees **no chain nodes**. This is consistent with B-5: the
  substrate chain is derived working state, never durable.
- An `mnode_` is an in-memory, per-run identifier; a task id is durable. The
  index therefore labels chain nodes `… chain node (not a task id)` and lists
  the durable task ids as the dependency targets.
- The driver obtains the store from its own `run_methodology` call
  (`store = SubstrateStore()`, `methodology_driver.py:507`), populated by
  `write_node` after each successful stage. It passes the provider
  `(project_id, node_id, kind)` for every node; the adapter filters on
  `project_id` and sorts by id. The reader is **not handed the store object**:
  it never sees node content, only the three identity fields. If the provider
  is absent (non-live callers), no envelope is appended. A fresh process has an
  empty store, so the `chain_node` section is empty — never a database read.

### C2 — the live database exists; the measurement is real

The phase-1 note said the live DB was absent. It is at
`D:/New folder/hermes-live.db`, and run reports are in
`D:/New folder/run-reports/`. For `sars-covid-10` the durable rows are
**12 tasks, 0 artifacts, 0 scope briefs**; a fresh process also has 0 chain
nodes. The **measured live index is 1,108 bytes / 12 entries**. The 40-entry
cap is retained: 1,108 bytes is far below the 3,000-byte re-measurement
threshold in R6.

### Rulings

| Ruling | Record |
| --- | --- |
| **R1** | **A approved**, not B, not C, for the reasons in §2. B remains the post-OPS-5B answer and is not precluded. |
| **R2** | The `not a task id` label is approved; **do not add a contract sentence now**. If run 11 still produces `dependency mnode_…`, the next gate is a contract sentence that `dependencies` accepts only task ids. Recorded as the fallback. |
| **R3** | Existence, not admissibility. A retracted artifact appearing in the index is correct; the validator still refuses it. **The envelope's own wording must not use "available", "valid", or "approved" vocabulary.** |
| **R4** | Do not mirror `runtime.task.external_refs` and do not add a second ref section. If run 11 still refuses a ref the index could not have shown, that is the next lever. |
| **R5** | Fail-loud approved. A stage never runs with a silently missing index. A soft-failure marker is not designed; it would need its own decision. |
| **R6** | 40 entries approved, subject to the live re-measurement. The live typical is 1,108 bytes (<3,000), so 40 stands. |

## 1. What run 10 actually refused

Run 10's four read-shaped refusals, from `docs/MERGE-LOG-OPS-17.md`:

```
PROPOSAL: task admission rejected: dependency mnode_9f52… does not exist
PROPOSAL: evidence artifact 'synthetic-sars10/e1' not in project 'sars-covid-10'
PROPOSAL: scope brief 'claim:synthetic-sars10/c1' not governed: ScopeBrief not found
PROPOSAL: task admission rejected: dependency mnode_a692… does not exist
```

Three of the four are the model using an id that is not a row in the
project's durable tables. The fourth — `dependency mnode_…` — needs a closer
reading, because the tree shows the model can already see an `mnode_` id.

### 1.1 The `mnode_` case is a type confusion, not only invention

`mnode_` ids are **derived substrate chain nodes**, not task rows:

- `node_id_of` derives them from kind/project/producing-task/content
  (`src/hermes/methodology/substrate.py:295-304`); `NODE_ID_PREFIX` is
  `"mnode_"` (`:142`).
- The methodology driver holds them in the in-process `SubstrateStore` only;
  the slice's own docstring says no `mnode_` reference is durable and no
  `mnode_`/`medge_` reference outlives the process
  (`src/hermes/research/task_handlers/methodology_driver.py:31-33, 49-51`).
- The stage's payload carries the immediate predecessor's id:
  `"predecessor": predecessor_id` (`methodology_driver.py:547-553`).
- The gateway's dependency check is against `tasks` and
  `task_dependencies` (`src/hermes/research/gateway.py:4690-4706`). An
  `mnode_` id is never a task id and cannot satisfy it.

So the model may be copying a visible `mnode_` into `dependencies` rather than
inventing it. An index that lists `mnode_` ids would not fix that refusal; it
could make it more likely. The design therefore must list the **legal
dependency targets** — durable `task_id`s — and label chain nodes as
**not task ids**. If the live run still copies an `mnode_` after seeing both,
the next lever is a contract sentence (`dependencies` accepts only `task`
entries), not a larger index.

### 1.2 The evidence and scope refusals

`runtime.task` already carries the operator's `external_refs` — the
`hypothesis:…`, `prediction:…`, `evidence:…`, `claim:…` ids the task supplied
(`src/hermes/agents/runtime/assembly.py:141-168`). The model is not missing
those strings. It is missing the **durable rows**:

- `EVIDENCE_TRANSITION` requires `evidence:<artifact_id>` and checks
  `ArtifactRepository.in_project` (`gateway.py:1437-1454`).
- `PROPOSE_RESEARCH_PROGRAM` requires a frozen `scope_briefs.brief_id`
  (`gateway.py:400-413`; `repositories.py:1487-1505`).

The observed `claim:…` scope ref is a family confusion: a claim ref is not a
scope brief. The index lists the actual brief ids, if any; if none exist, it
says so explicitly by carrying no `SCOPE_BRIEF` entries.

## 2. A / B / C, costed honestly

| Shape | What it buys | Cost today | Ruling |
| --- | --- | --- | --- |
| **A — bounded index in the prompt** | The model sees the project's existing ids, kinds and types. Addresses evidence and scope refs directly; addresses the dependency refusal by showing legal `TASK` ids and labelling chain nodes as non-tasks. | One read-only projection (3 `SELECT`s + 3 `COUNT`s per stage), plus prompt bytes (measured below). No new plane, no write, no transaction. | **Chosen.** |
| **B — read tools** | The model can query for depth: graph traversal, provenance chains, filtered searches. Closer to the declared `graph_read` / `provenance_read` design. | Blocked on the capability plane (OPS-5B). The live composition narrows every profile to model-only and passes no capability port (`composition.py:512-529, 485-495`). Each lookup is an extra model/tool cycle, and the tool-call item schema is still unstated (OPS-17 inventory). | **Not this gate; not precluded.** The right long-term answer. |
| **C — both** | Orientation plus depth. | Sum of A and B; B is unavailable, so C degenerates to A with an unused seam. | **Rejected now.** Revisit after OPS-5B. |

A is the smallest thing that removes an entire refusal class without a new
authority or mutation surface. It is also reversible: remove the provider and
the stage prompt returns to today's shape.

## 3. The index: exact shape

### 3.1 Envelope

- Origin: `runtime.project_index` (new constant in
  `src/hermes/agents/runtime/assembly.py`).
- Ref: `f"{project_id}:project_index"`.
- Text: the canonical JSON of one object:

```json
{
  "entries": [
    {"id": "task_…", "kind": "task", "label": "PENDING AGENT_TASK"},
    {"id": "sb-…", "kind": "scope_brief", "label": "v1"},
    {"id": "evidence:evidence-…", "kind": "artifact", "label": "evidence"},
    {"id": "mnode_…", "kind": "chain_node", "label": "HYPOTHESIS chain node (not a task id)"}
  ],
  "omitted": 0
}
```

The document carries no `project_id`; the envelope ref carries the scope, and
the entries are already project-scoped. The empty document is exactly
`{"entries": [], "omitted": 0}` (26 bytes canonical).

### 3.2 Entry fields — nothing else

| Field | Source | Constraint |
| --- | --- | --- |
| `id` | task id; `artifact_type:artifact_id` for a durable artifact row; `brief_id`; `mnode_…` | one line, from a stored column, never content |
| `kind` | closed set: `task`, `scope_brief`, `artifact`, `chain_node` | distinguishes legal dependency targets from orientation |
| `label` | `f"{status} {task_type}"`; `f"v{version}"`; `artifact_type`; `f"{chain_kind} chain node (not a task id)"` | derived from closed vocabularies or stored type/version fields; never free text |

No entry carries `spec`, `metadata`, rationale, scope text, node content,
question text, another project's row, or any credential.

The artifact form is the one `EVIDENCE_TRANSITION` consumes:
`evidence:<artifact_id>` (`gateway.py:1437-1454`). The index lists **durable
artifact rows**, not a general claim/hypothesis/prediction dereference table:
refs that exist only as program annotations or substrate `external_ref`s stay
in `runtime.task.external_refs` or program content and are not invented into
index entries. The observed evidence refusal is covered; the claim-as-scope-ref
confusion is addressed by the `scope_brief` section showing actual brief ids,
not by listing claim refs again.

### 3.3 Ordering and truncation

- Order: `task`, `scope_brief`, `artifact`, `chain_node`; within each kind,
  ascending `id`. The order is deterministic and is also the truncation
  priority: the tail is dropped first.
- Entry cap: **40** (`INDEX_MAX_ENTRIES`).
- Byte cap: the canonical envelope is held to `MAX_PAYLOAD_BYTES`
  (`4096`, `agents/runtime/types.py:73`), the same bound every other
  prompt envelope uses. If the 40 entries exceed the byte cap, entries are
  dropped from the tail until the document fits.
- `omitted` is `total - len(shown)` after both caps, so a truncated index
  never looks complete.
- The empty project still gets the envelope; `entries: []` is the explicit
  "nothing exists yet" marker. Absence of the envelope is only legal when no
  provider is configured (tests and non-live callers), not in the live
  composition.

### 3.4 Deterministic by construction

No clock, random, or ambient order enters the document. The SQL orders by
`id`; chain nodes are sorted by id; labels are closed-vocabulary derivations.
The same project state produces the same envelope bytes. That matters because
the envelope is inside `TaskContext.context` and therefore inside
`TaskContext.digest()`: a resume must replay the same index, not a new one.

## 4. The five answers

### 4.1 Scope — project-scoped only

The reader is constructed with one connection and called with one
`project_id`. The durable half is **3 `SELECT`s + 3 `COUNT`s** — tasks,
artifacts, scope briefs — and every one is bound. The chain-node half is not a
query: it is the run's `SubstrateStore`, passed as `(project_id, node_id,
kind)` and filtered again on `node.project_id`.

```sql
SELECT task_id, task_type, status FROM tasks
 WHERE project_id = ? ORDER BY task_id LIMIT 41;
SELECT artifact_id, artifact_type FROM artifacts
 WHERE project_id = ? ORDER BY artifact_id LIMIT 41;
SELECT brief_id, version FROM scope_briefs
 WHERE project_id = ? ORDER BY brief_id LIMIT 41;
-- plus one COUNT(*) for each, same WHERE clause
```

Chain nodes are passed from the driver's `SubstrateStore` as
`(project_id, node_id, kind)` and filtered again on `node.project_id` by the
reader. There is no query without `WHERE project_id = ?` and no method that
lists projects or all rows.

**Testable claim:** for any two projects P1 and P2 with disjoint rows, every
entry in P1's index either (a) resolves to a row in P1's `tasks`, `artifacts`
or `scope_briefs`, or (b) is a chain node whose `project_id` is P1; and no id
that exists only in P2 appears. The test seeds P1 and P2 with the same kinds
and overlapping id prefixes, plus a P2 chain node, and asserts both halves.

### 4.2 Freshness — once per stage, not per tick

The provider is called in `run_methodology` immediately before
`wiring.run(projection.profile, context)` (`methodology_driver.py:546-554`),
after the previous stage's admissions have committed. The envelope is added to
the stage's `TaskContext.context`; the runtime's existing assembler renders it
(`assembly.py:171-180`).

Why not per tick:

- the stage's context is the unit the runtime checkpoints and resumes; a
  mid-run refresh would make the context digest change between ticks and turn
  a resume into a different prompt;
- the live methodology sets one tick per stage, so per-stage and per-tick
  coincide today; per-stage is the simpler rule that survives a future
  multi-tick stage without a dynamic assembler;
- a stage's own admissions happen after its model replies, so a same-stage
  refresh would only show work the stage has not yet proposed. The next stage
  needs the fresh view, and gets it.

A resume replays the checkpointed envelope, not a new read. The snapshot is
therefore honest about the state the model saw; it is not a claim about the
project's current state at resume time.

### 4.3 Cost — measured on the live project, plus the growth case

The live project is `sars-covid-10` in `D:/New folder/hermes-live.db`:
**12 tasks, 0 artifacts, 0 scope briefs**, and 0 chain nodes in a fresh process
(the store is in-memory, C1). The measured live index is **1,108 bytes / 12
entries**. The growth cases are reconstructed from the approved phase-1 note:

| Project shape | Entries shown | `omitted` | Envelope bytes |
| --- | ---: | ---: | ---: |
| empty | 0 | 0 | 26 |
| **live `sars-covid-10` (12 tasks, no artifacts/briefs/nodes)** | **12** | **0** | **1,108** |
| reconstructed run-10 shape | 24 | 0 | 2,471 |
| same + 22 more artifacts (46 total) | 40 | 6 | 4,023 |
| worst-case 40 long artifact ids | ≤40 | byte-capped | ≤4,096 |

The per-stage prompt delta is the envelope text: **+1,108 bytes** on the live
project today, at most +4,096 after truncation. The system prompt is unchanged.
The 40-entry cap is retained: the live typical is below the 3,000-byte R6
threshold. If the project grows past it, the first knob is the entry cap: the
46-entry reconstruction at **32** entries is **3,248 bytes**. The next knob is
ordering: chain nodes are already last and are dropped first (the immediate
predecessor is in the payload anyway), then artifacts. Tasks and scope briefs
are few and are retained.

### 4.4 Empty project

The provider returns a view with zero entries and the driver still appends the
envelope. The model sees `{"entries": [], "omitted": 0}`, not silence. This is
the difference between "nothing exists yet" and "I was not told". A test calls
the reader on a project with no tasks, artifacts, briefs or chain nodes and
asserts the envelope is present and empty.

The live methodology task itself is normally a `task` row, so a live project
is rarely completely empty; the marker still matters for the corpus and for a
new project before its first admission.

### 4.5 M1 and the LOOP baseline

The index is prompt payload, not system text, so **M1 moves**: each model call
in a methodology stage carries the envelope text, adding the measured bytes
above. The run report's per-call M1 will show it.

The **LOOP baseline does not move**: `tests/test_loop_baseline.py` builds its
own `TaskContext`s and its own model port; it never calls the methodology
driver or the index provider. If any pinned row or digest moves, that is a
failure to report, never a re-pin. `test_loop_observations` likewise measures a
test-owned port. `test_ops7_input_projection` pins the `runtime.task`
envelope, which is unchanged; the index is a separate origin and a separate
envelope.

## 5. Read boundary and injection

The read is a **read-only projection**, not a repository and not a
transaction owner.

- New `src/hermes/persistence/project_index.py`: `read_project_index_rows(
  conn, project_id)` returns three tuples of bare selected columns plus the
  three totals. Only `SELECT` and `COUNT(*)`; no `INSERT`/`UPDATE`/`DELETE`,
  no `BEGIN`/`COMMIT`/`ROLLBACK`. It does not import `research/`.
- New `src/hermes/research/project_index.py`: the adapter that turns the rows
  and the chain-node refs into the entry list, applies labels, order and the
  40-entry cap, and returns `ProjectIndexView(entries, total)`.
- `agents/runtime/assembly.py`: `PROJECT_INDEX_ORIGIN`,
  `ProjectIndexEntry`, `ProjectIndexChainNode`, `ProjectIndexView`, and
  `project_index_envelope(...)`. The renderer is pure and owns the 4 KiB byte
  cap/truncation; it imports only runtime types and the untrusted-content
  boundary, like every other renderer there.
- `research/task_handlers/methodology_driver.py`: an optional
  `project_index` callable, called once per stage; the returned view is
  rendered and appended to `context.context` before `wiring.run`.
- `research/task_handlers/__init__.py` and `composition.py`: thread the
  provider; phase 2's `build_live_composition` constructs it from the
  controller's connection and always injects it. `build_controller` without a
  provider keeps today's behavior, which is what the existing tests see.
- No controller change, no new intent, no new event, no new table, no new
  durable field. The connection is read, not fenced: the reader cannot write.

A read failure **raises**; the driver never silently omits the envelope. An
index-less stage would be indistinguishable from "nothing exists", which is
exactly the failure this gate is closing. This is **R5 (approved)**. A
soft-failure marker is not designed; it would need its own decision.

## 6. Invariants and how they are kept

| Invariant | Mechanism |
| --- | --- |
| No new event, field, write or transaction; census 124 / 28 (19/5/4) / 1 / 15 / 0 | The reader is 3 `SELECT`s + 3 `COUNT`s; no transaction-control statement. `check_census.py` is unchanged and re-run. A dynamic test compares the `BEGIN`/`COMMIT`/`ROLLBACK` trace of a stage with and without the index. |
| Read-only | No writer import in the reader; an AST/import test plus the dynamic trace. The provider returns data; it cannot admit. |
| Drain-only unchanged; B4 24 | The index is only on the methodology handler path; no drain/B4 surface changes. |
| No key material, no cross-project rows | Selected columns contain no credentials; the cross-project test seeds P1/P2 and a P2 chain node. |
| Untrusted data, own origin | `UntrustedContent(origin="runtime.project_index", ref="<project>:project_index")`; labels are closed-vocabulary, and a content-exclusion test seeds instructions/secrets into spec/metadata/scope text/node content and asserts they are absent. |
| LOOP baseline unchanged | The baseline corpus never calls the provider; if a pinned row moves, stop and report. |

## 7. Falsifiers → phase-2 tests

| Charter falsifier | Test |
| --- | --- |
| A stage prompt carries the index, with an explicit empty marker | live-composition stage asserts the `runtime.project_index` envelope; empty-provider test asserts `entries: []`, `omitted: 0` |
| Over-cap project shows `omitted: N` and stays bounded | seed >40 entries; assert 40 shown, `omitted` exact, envelope ≤4096 bytes |
| Another project's ids never appear | P1/P2 durable rows + P2 chain node; assert disjoint |
| Same transaction count with/without the index | `sqlite3` trace callback around a scripted stage; compare control statements |
| A live-shaped run citing an index id no longer refuses | scripted model reads the envelope, drafts a dependency on a `task` entry and an `EVIDENCE_TRANSITION` on an `artifact` entry; assert those codes are absent and the proposals admit |
| LOOP baseline passes unchanged | existing `test_loop_baseline` + `test_loop_observations` |

Additional phase-2 tests: per-stage freshness (a task admitted in stage 1
appears in stage 2's index); chain nodes labeled not-task-ids; read failure
raises; no content/credential appears; origin is distinct; no import from the
reader to a writer.

## 8. Unresolved, or undecidable from this tree

1. **The live project is now measured (C2).** The phase-1 note was written
   without the live DB; it is at `D:/New folder/hermes-live.db` and the
   `sars-covid-10` index is 12 tasks / 1,108 bytes. The reconstruction remains
   only as the growth case.
2. **The `mnode_` label may not be enough.** The tree proves an `mnode_` is not
   a task, but only a live run can show whether the model stops copying it.
   If run 11 still produces `dependency mnode_…`, the next lever is a contract
   sentence that `dependencies` accepts only `task` ids — a separate
   prompt/contract gate. **Recorded as the approved fallback (R2).**
3. **Admissibility vs existence.** The index lists artifact rows that exist;
   it does not filter retracted or web-derived artifacts, because no cheap
   project-scoped retraction projection is on this read path. A retracted
   artifact may still be refused; the index must not be read as an
   admissibility claim.
4. **Claim/hypothesis/prediction refs that are not artifact rows.** The tree
   stores some refs inside program content, not the `artifacts` table. The
   index lists only durable artifact rows; the four fixture refs already reach
   the model in `runtime.task.external_refs` but are not verified existence
   there. Whether to add a second ref section is a future decision.
5. **Read failure policy.** R5 approved fail-loud: a read failure raises; a
   soft-failure marker is not designed.
6. **The cap is a judgment, ruled.** R6 approved 40 entries after the live
   measurement (1,108 bytes, below the 3,000-byte threshold); 32 entries is the
   first alternative if the project grows.

## 9. Phase 2 implementation

1. `persistence/project_index.py` — the read-only row projection.
2. `agents/runtime/assembly.py` — origin, entry/view types, pure envelope
   renderer with the 40/4096 bounds.
3. `research/project_index.py` — the adapter (labels, order, caps, chain
   nodes).
4. `methodology_driver.py` — optional provider, one read per stage, append the
   envelope before `wiring.run`; thread it through `build_methodology_handler`.
5. `composition.py` — construct and inject the reader in
   `build_live_composition`; leave non-live callers without it.
6. `tests/test_ops18_project_index.py` — the falsifiers plus cross-project,
   content-exclusion, transaction, freshness and read-failure tests.
7. Gates: the charter's targeted set, full suite under the heavy-gate lock,
   suite stamp, census, ruff, pyright src/tests.

License: Apache-2.0 (LICENSE).
