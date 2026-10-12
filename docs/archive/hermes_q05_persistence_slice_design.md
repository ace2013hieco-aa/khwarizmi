# HERMES Q-05 — PERSISTENCE SLICE: STORING THE RATIFIED FAILURE CLASSIFICATION

**Status:** DESIGNED — no code (design decision record; the repo's
design → hostile gate → implementation sequence).
**Date:** 2026-08-15
**Ratified upstream:** IDR-036 (Q-05 taxonomy + action map) + the substrate
`src/hermes/research/failure_classification.py` (41 golden fixtures, 933
passed, pyright 0 errors).
**Consumes:** `FailureClassification` (ADMITTED substrate output),
`FalsificationRecord`, the injected resolver protocol.
**Constraint set (from the operator task):** store the ratified
classification as **a metadata field** on the future REFUTED evidence-ladder
record **with provenance edges**, **no new tables**, **no new authorities**.

---

## 1. Context

The Evidence Ladder (v6 §10) is a Phase 0 placeholder on this baseline: no
evidence table, no EvidenceRepository, no falsification record. The Q-05
substrate (ratified as IDR-036) therefore defines the classification as a pure
validator result and explicitly deferred persistence to "when the Evidence
Ladder lands (P2)".

This slice is that persistence design — with a correction: **it does not wait
for the ladder.** The repository already has the exact carrier for advisory,
content-addressed metadata: the generic `artifacts` table (`artifact_type`
has **no CHECK constraint** — a new type value requires no migration) and the
`provenance_edges` table (`cites`/`derived_from`/`supersedes`/`used_as_input`/
`justifies`). The source slice (step 6) and the CONTRA claim/assumption slice
both established the pattern: content-derived identity, project scoping,
get-by-hash-first idempotency, task-bound writes, zero new events. This slice
lands the classification through the SAME seam, and defines the metadata-field
contract the future REFUTED record will carry.

**What this slice is NOT:** the Evidence Ladder; a REFUTED transition engine;
a hypothesis table; a new intent/gateway kind; a new event; a new authority;
a new scheduler; automatic hypothesis/task/scope creation. The classification
remains advisory metadata — never evidence, never a `Validation`, never
ladder-citable (v6 §29.2 boundary preserved).

## 2. Decisions

### D1 — Persist as an `artifacts` row, not a new table

An ADMITTED `FailureClassification` is recorded through the existing
`ArtifactRepository.record` (the source-outcome pattern — inline JSON
metadata, `inline://` storage path; no filesystem bytes needed):

| Field | Value |
|---|---|
| `artifact_id` | `classification.classification_id` (`"fc_" + content_hash[:24]`) |
| `artifact_type` | `"failure_classification"` (open column — no migration) |
| `content_hash` | `classification.content_hash` (the substrate's canonical SHA-256) |
| `project_id` | `classification.project_id` (project-scoped, like every artifact) |
| `task_id` | the producing falsification task (D4 binding) |
| `producer` | `"falsification:" + producing_task_id` |
| `metadata` | the structured classification (class, contributing factors, evidence refs, class-specific citations, `classifier_version`, `classification_id`, `permitted_actions`, `requires_human_confirmation`, explanation, proposed_by) |
| `size_bytes` / `storage_path` | `0` / `"inline://failure_classification"` |

**Identity discipline (EC-V6):** the write path re-derives `content_hash`
from the classification's canonical JSON and re-runs the substrate validator
with the REAL resolvers — it never trusts a caller's ADMITTED claim or an
authored hash (same Model D the ResearchProgram/claims write paths use).

### D2 — Provenance edges (existing `provenance_edges`, no new types)

Written atomically with the artifact row (IDR-013), dependent-first
(`(artifact_id, upstream_id, edge_type)` — house convention):

1. `(classification_id, evidence_ref, "cites")` for **each** falsifying
   evidence artifact the classification cites — the citation edges the task
   demands.
2. `(classification_id, producing_task_id, "derived_from")` — the
   falsification-producing task that authorized the write (D4).
3. Future (when the ladder lands): the REFUTED record row carries a
   metadata field `failure_classification_ref` (D3) and a `cites` edge from
   the REFUTED record to the classification — the classification stays
   advisory (it never claims to derive the record; the RECORD cites it).

Reclassification under a new `classifier_version` is a **new content hash →
new artifact row** (content_hash UNIQUE); both rows coexist — historical truth
is never mutated. A `supersedes` edge from the new to the old classification
is OPTIONAL/deferred to consumption (the versioning works without it).

### D3 — The metadata-field contract on the future REFUTED record

When the Evidence Ladder lands (P2), its falsification/REFUTED record carries
the classification as a **metadata field** (the framework's "existing record +
field" target, now real):

```json
{
  "failure_class": "DECLARED_CONSTRAINT_VIOLATION",
  "classifier_version": "q05-2026.1",
  "classification_id": "fc_<24 hex>",
  "failure_classification_ref": "failure_classification:<content_hash>"
}
```

The ref is a **dereference contract** (the `research_program:` provenance
pattern, V6-FINAL-02): at the ladder's write path the ref MUST resolve to an
`artifacts` row of type `failure_classification` in the same project, or the
record fails closed. `failure_class`/`classifier_version`/`classification_id`
are denormalized for readability; the ref is the authority.

### D4 — Authorization: task-bound, zero new intents

The classification is advisory metadata, not a state mutation — recording it
needs **no new intent** and no gateway change. The write is authorized by
binding, exactly like the source/EXTRACT slices (V6-P7-A2-01/02, checked
INSIDE the write transaction):

- the producing task exists, is same-project, and is RUNNING (or the
  falsification transition's producing task) at commit time;
- the classification's evidence refs all belong to the producing task's
  outputs (two-hop `derived_from` reachability — the `_source_artifact_resolves`
  precedent) and are the record's falsifying evidence;
- the classification is ADMITTED by the substrate re-run with real resolvers.

A second, future authorization surface is the ladder's own REFUTED
transition: when that write path exists, the classification is recorded as
part of processing an already-authorized falsification, not independently.

### D5 — Resolver wiring (the write path supplies the real resolvers)

| Resolver | Real source | Status |
|---|---|---|
| `evidence_resolver(project_id, ref)` | `artifacts` + project-edge reachability (reuse the two-hop pattern from `source_outcomes._source_artifact_resolves`) | AVAILABLE NOW |
| `constraint_resolver(project_id, program_ref, ref)` | `ResearchProgramRepository` row: hypothesis `falsification_condition` / `methodology_constraints` | AVAILABLE NOW |
| `mechanism_resolver(project_id, program_ref, ref)` | program `predictions[].ref` | AVAILABLE NOW |
| `scope_field_resolver(project_id, brief_ref, field)` | `scope_briefs.scope_text_json` key presence (the brief has no closed schema — the resolver checks the JSON structure; documented limitation, see OQ-1) | AVAILABLE NOW (best-effort) |
| `regime_resolver(project_id, ref)` | the regime axis store (ICSS-v1) — **does not exist yet** (IDR-026/027 deferred it) | **DEFERRED — fail closed** |

An `ENVIRONMENT_MISMATCH` classification is therefore **not admissible at the
write path until the regime axis lands** — the substrate admits it, the write
path refuses it (resolver absence ⇒ fail-closed, the thesis.py contract). This
is recorded, not papered over.

### D6 — Idempotency / one-shot (the artifacts-table engine)

- **Identical content** (same record + draft + classifier version): same
  `content_hash` → get-by-hash-first (SD-04) → reuse the existing row, no new
  row, no duplicate edges (INSERT OR IGNORE) — crash/retry idempotent.
- **Same hash, different `artifact_type`** (a hash collision across slices):
  REJECTED loudly (the R02 artifact-type reuse guard, never silently reused).
- **New classifier version** (legitimately new content): new row, both
  records coexist — this is the versioning semantics, NOT the divergent
  one-shot refusal of source outcomes (that refusal guards one execution/one
  output; a reclassification is a new derivation, not a divergent output).

### D7 — Zero new events

The artifact row + provenance edges ARE the audit record (the IDR-028 D3
precedent: "journaling via the task's own events + §14 edges, zero new
events"). The producing task's own `TaskStatusChanged`/lifecycle events already
journal the execution; `EVIDENCE_TRANSITION_*` events remain reserved for the
ladder's own transitions (P2), untouched by this slice.

### D8 — Read/consumption surface (advisory only)

A read query over `artifacts` (`artifact_type = 'failure_classification'`,
project-scoped) + `provenance_edges` answers "what classifications exist for
hypothesis H / evidence E" for the future reconcile loop / controller. The
classification artifact is **never dereferenceable as evidence** — no resolver
outside this slice may cite it as a `source_result`/`Validation`/ladder
precondition (the advisory boundary is structural: its `artifact_type` is
outside every citable type set).

## 3. Fail-closed matrix (write-path rules)

| Attempt | Result |
|---|---|
| Persist a REJECTED/unvalidated classification | refused — the write path re-runs the substrate |
| Forged `content_hash` / `classification_id` | refused — identity re-derived (EC-V6) |
| Classification for a foreign project | refused — project-scoped bindings + resolvers |
| Evidence refs outside the producing task / record | refused — subset + reachability checks |
| ENVIRONMENT_MISMATCH without the regime axis | refused — resolver absent fails closed |
| Cross-type hash reuse | refused — R02 guard |
| A write path attempting to create tasks/hypotheses/scope edits | impossible — the slice's only write is the artifact + edges (structural) |
| FRAMING_ERROR mutating the brief | impossible — the slice never writes `scope_briefs` |

## 4. Acceptance-test plan (future fixtures, when implemented)

1. ADMITTED classification persists: row + `cites`(evidence) + `derived_from`(task) edges, atomic.
2. Identity re-derivation: forged hash → `IntegrityError`, nothing written.
3. Crash-retry: identical content → reuse, no duplicate rows/edges.
4. Reclassification under a new classifier version → new row, old row intact, both queryable.
5. Task binding: foreign/stale/not-RUNNING producing task → refused.
6. Cross-project: classification of p2 evidence under p1 → refused.
7. ENVIRONMENT_MISMATCH write → refused (regime resolver deferred), substrate still admits (documented asymmetry).
8. R02 cross-type reuse → refused.
9. Future REFUTED-record integration: record row carries `failure_classification_ref`; undereferenceable ref → record fails closed.
10. Advisory boundary: the classification is unreachable by any evidence/ladder resolver (structural scan).

## 5. Open questions (recorded, non-blocking)

- **OQ-1** — the scope-field resolver reads `scope_text_json` before a closed
  ScopeBrief schema exists (Q-09's Phase 0). A missing schema means
  "field present" is a JSON-key check, not a schema-validated check. If Q-09
  lands a closed schema first, the resolver upgrades to it. FRAMING_ERROR
  classifications are admissible now only when the brief's JSON is actually
  structured (the resolver refuses on non-dict brief text — fail closed).
- **OQ-2** — whether the future ladder records the classification inside the
  REFUTED record's own row (denormalized metadata) or only as an edge + ref.
  This design prefers the ref + denormalized read fields (D3); the ladder's
  row schema is its own P2 decision.
- **OQ-3** — the `supersedes` edge between classification versions is
  deferred to consumption; the content-hash engine already provides
  coexistence, so the edge is a query convenience, not a correctness need.

---

## 6. Hostile gate — self-review of this design (run before implementation)

> **Does this slice create a new table?** No — `artifacts` + `provenance_edges`
> already exist; `artifact_type` is open (no CHECK), so `"failure_classification"`
> needs no migration.

> **Does it create a new authority?** No — it reuses the existing
> `ArtifactRepository` write path; the only new code is a repository method
> (the "record classification" seam), bound to a producing task like every
> other artifact writer. No intent, no gateway, no event, no scheduler.

> **Could the write path become a second epistemic authority?** No — the
> write is gated on the substrate's ADMITTED verdict re-run with real
> resolvers; the artifact is advisory metadata and is structurally
> unreachable by evidence/ladder resolvers (D8). It cannot promote, demote,
> or transition anything.

> **Could it silently pivot / create a hypothesis or task?** No — the slice's
> only write surface is the artifact row + edges (structural); creation
> actions remain exclusively on the existing gateway paths.

> **Could FRAMING_ERROR rewrite scope?** No — the slice never writes
> `scope_briefs`; it only records the classification and (later) a ref on the
> REFUTED record. Scope revision stays on the S16 human amendment path.

> **Could the regime gap be papered over?** No — an ENVIRONMENT_MISMATCH
> classification is refused at the write path until the regime axis exists
> (fail-closed), and the asymmetry is documented (substrate admits, write
> path refuses) rather than hidden.

> **Could historical classifications be rewritten?** No — content-addressed
> immutable rows; a reclassification is a new artifact, and the future
> REFUTED record's ref dereferences to a specific immutable row.

**GATE RESULT: PASSED — no remediation required before implementation.**

## 7. Implementation notes (appended after implementation, when authorized)

### IMPLEMENTED — 2026-08-15 (per operator authorization)

**Code surface (exactly the §7 seam, no migration, no event, no intent, no
gateway change):**

- `src/hermes/persistence/failure_classifications.py` (566 lines) —
  `FailureClassificationRepository` in the `SourceOutcomeRepository` shape:
  `record_failure_classification(project_id, record, draft, *,
  producing_task_id, claimed=None, reason="")`, the real resolver bundle
  (evidence / constraint / mechanism / scope-field; regime deliberately
  absent), the D8 read surface (`classifications_for_project`,
  `classifications_for_evidence`, `dereference_failure_classification_ref`),
  and the three fail-closed error classes (`FailureClassificationError`,
  `FailureClassificationBindingError`, `FailureClassificationIntegrityError`).
- `tests/test_q05_persistence.py` (810 lines) — the §4 acceptance fixtures
  1–10 plus the fail-closed matrix and adversarial attacks (forged claimed
  identity, R02 cross-type reuse, foreign/stale/not-RUNNING tasks,
  cross-project evidence, non-ADMITTED drafts, wrong-object citations,
  FRAMING_ERROR without scope mutation, RESOURCE_CONSTRAINT without
  budget/task mutation, IMPLEMENTATION_FAILURE without auto-replacement,
  classification-as-evidence refusal, stale evidence, and the D7 zero-new-
  events / D8 structural scans).

**Post-implementation hostile probes (beyond the suite):** matching `claimed`
is accepted (no false refusal); identical content under a second task without
evidence ownership → `FailureClassificationBindingError`; evidence reachable
from both tasks → REUSED with a second `derived_from` edge; reuse keeps the
immutable row (reason is audit-only on NEW writes); ENVIRONMENT_MISMATCH
refused with the documented DEFERRED reason before admission; reclassification
coexists with the old row byte-identical.

**Numbers:** 962 passed (933 baseline + 29 persistence fixtures), 0 failed /
0 errors, 9.16s, exit 0. pyright (`uvx pyright src`): 0 errors / 0 warnings.
Commit: uncommitted (per workflow — no commit without operator request).

**Review status:** READY FOR INDEPENDENT REVIEW — the slice holds to every
hostile-gate answer in §6: no new table, no new authority (the artifact write
delegates to the existing `ArtifactRepository.record`), no second epistemic
surface (structural scan + the evidence resolver refuses
`failure_classification` refs), no silent pivot (only writes are the row +
edges), no ScopeBrief write, regime gap fails closed, and historical rows are
immutable.


- Expected code surface (all existing seams): a
  `record_failure_classification` repository method (task-bound, identity
  re-derived, one transaction, edges atomic — the `SourceOutcomeRepository.record`
  shape), the real resolver bundle, and `tests/test_q05_persistence.py` with
  the §4 fixtures. No migration, no event, no intent, no gateway change.
