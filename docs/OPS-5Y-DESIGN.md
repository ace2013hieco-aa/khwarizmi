# OPS-5Y — prior art is produced, or it is not asserted

**Status:** design gate, phase 1. **No product code in this commit.**
**Charter:** OPS-5Y, issued 2026-10-27.
**Base:** `main` at `5bf131b`, plus the measurement commits `6b349a8`
(depth report) and `50777ae` (run 38) on `diag/depth-report`.
**Branch:** `slice/ops-5y-prior-art`.
**Amendment 1:** 2026-10-28, folded from the review of `1d54f52`. The review
accepts the central decision and tightens §4.1's sufficiency rule to **direct
support**; it also rules §11's five open questions. §13 records the amendment.

This note is written against the tree, not against the charter's summary. Every
claim below carries a code anchor. Where the charter and the tree disagree, the
tree wins and the disagreement is named.

---

## 0. What this note decides

1. **Option (A) + (C)**, in that order. (B) is the long-term source of real
   prior art and is deferred, because it depends on the fetch → derive → admit
   chain that (C) unblocks.
2. **The minimum is three kinds, not two.** `HYPOTHESIS`, `PREDICTION` **and
   `CLAIM`'s own identity** have no producer. The charter's §4.3 names only the
   first two; `CLAIM` is refused for the same reason at the same boundary
   (`substrate.py:866-874`, reached from `workflows.py:750-753`).
3. **`EVIDENCE` remains the one citation kind.** It already has a producer (the
   admitted `EVIDENCE_TRANSITION`), and keeping it a citation preserves the
   artifact-checked identity that the other three should never have had.
4. **A node kind is not both mintable and citable.** Citation becomes a
   `cited_refs` field on a minted node. The old conflation — a chain node whose
   identity *is* a cited artifact — is the defect; restoring it under a flag
   would restore the defect.
5. **The support invariant is enforced at `CLAIM`**, in the substrate's
   `_support_refusal`, over the **direct support set** — the claim's own
   admitted refs and its direct `EVIDENCE` predecessor's citation — using one
   externality bit per ref supplied by a read-only artifact-provenance port.
   The wider closure is the refusal explanation, not the sufficiency
   condition. The substrate's own edges give reachability; they do not give
   externality, and this note says so rather than pretending otherwise.
6. **Stage depth becomes a field** on the existing `TaskStatusChanged` event
   payload — no new event kind, no new transaction — and `depth_report.py`
   reads it before falling back to prose.
7. **The census is unchanged.** `124 / 28 (19/5/4) / 1 / 15 / 0` reproduces
   exactly on this tree (measured, `scripts/check_census.py`, 2026-10-28).

The gap itself is **not a discovery**. `_PRIOR_ART_LABEL`
(`workflows.py:594`), the `_default_content` docstring (`workflows.py:735-742`)
and the run-38 commit already record it. The depth baseline is the price, not
the finding.

---

## 1. The measurement, restated from the tree

Run 38 seeded one fresh project through `apply_intent` with the same nine-stage
methodology, the same question, and **empty** `admission_refs`/`external_refs`.
The provider answered: 12 calls, 12 OK. The run died at `HYPOTHESIS` after
three identical attempts:

```text
MALFORMED_PAYLOAD: a HYPOTHESIS node cites an existing artifact:
it needs a non-empty 'external_ref'
```

The model-level stage reports `SUCCEEDED`; the **chain write** refused. That is
the correct locus. The refusal is deterministic and provider-independent:

- `REFERENCED_NODE_KINDS = {HYPOTHESIS, PREDICTION, EVIDENCE, CLAIM}`
  (`substrate.py:153`);
- a node of one of those kinds must carry a non-empty `external_ref` under its
  own namespace (`substrate.py:866-884`);
- `_default_content` supplies `external_ref` only from
  `inputs.external_refs` for those kinds (`workflows.py:750`, `:756`);
- a fresh run has no such input, so the value is `""` and the shape gate
  refuses.

The same is true of the historical best. `sars-covid-30`/`-31` reached
`PREDICTION` because their task inputs carried:

```json
"admission_refs": ["hypothesis:prior-art-sars30/h1",
                   "prediction:prior-art-sars30/h1/p1",
                   "claim:prior-art-sars30/c1"]
```

`SubstrateStore.admit_ref` (`substrate.py:551-562`) registers **any** string as
resolving in a project; `resolve_ref` (`substrate.py:613-662`) checks membership
in that registry, not the existence of a row. The registry is last-writer-wins,
keyed by ref string alone, and records no content hash. The historical depth is
therefore **an assertion about prior art**, not a measurement of it. The one
run that failed `EVIDENCE_DOES_NOT_RESOLVE` failed because its ref was not in
the assertion list, not because no artifact carried it.

This note does not relitigate that finding. It prices it.

---

## 2. What is actually unproduced

| stage | current node rule | producer today | verdict |
|---|---|---|---|
| `QUESTION` | local, inline `question` | the run | fine |
| `HYPOTHESIS` | **citation** of `hypothesis:` | none | must mint |
| `PREDICTION` | **citation** of `prediction:` | none | must mint |
| `EXPERIMENT` | local | the run | fine |
| `OBSERVATION` | local, cites the admitted evidence | the run | fine |
| `EVIDENCE` | **citation** of `evidence:<artifact_id>` | admitted `EVIDENCE_TRANSITION` | keep |
| `CLAIM` | **citation** of `claim:` **plus** admitted evidence | none for the `claim:` half | must mint |
| `CRITIQUE` | local | the run | fine |
| `CONCLUSION` | local | the run | fine |

Three positions have no producer, not two. The `CLAIM` half is easy to miss
because the same node also carries `admitted_refs = (evidence_ref,)`
(`workflows.py:750-753`); that half is real support, but the node is still
refused by the *shape* gate before support is ever considered if
`inputs.external_refs["CLAIM"]` is empty.

`EVIDENCE` is different in kind: its producer exists, the gateway dereferences
the artifact row (`gateway.py:1541-1560`), and the driver projects the admitted
ref into the registry (`methodology_driver.py:295-305`). It should keep its
citation identity.

---

## 3. §4.1 — who may assert a ref, and what must back it

### 3.1 The authority rule

| actor | may supply | what backs it |
|---|---|---|
| operator (task `spec.inputs`) | `admission_refs`, `external_refs` | a **project-scoped row the ref names**, resolved by the namespace owner |
| live driver | an `evidence:` ref | the gateway's `ADMITTED` `EVIDENCE_TRANSITION` verdict; the artifact row was dereferenced at admission |
| model | a proposal (including `EVIDENCE_TRANSITION`) | nothing: a proposal is not an assertion of prior art |
| substrate | a registration | a `RefBacking` value; **no backing, no registration** |

The sentence that replaces "any string an operator writes resolves" is:

> A ref is admitted only if the project can dereference it to a row that
> carries its content; a ref the run minted is not admitted as prior art, and a
> proposal is not a backing.

### 3.2 The backing predicate, per namespace

The port is one read-only call:

```python
provenance_of(project_id, ref) -> "FETCHED" | "ROW" | None
```

`None` means unbacked. `ROW` means a real project row carries it. `FETCHED`
means the row is a `source_payload` artifact written by the fetch capability
and therefore content external to the run. The four namespaces resolve as
follows:

| ref family | backing row | content carried |
|---|---|---|
| `evidence:<artifact_id>` | `artifacts.artifact_id`, same project | the artifact row + bytes; `FETCHED` iff `artifact_type = 'source_payload'` **and** `producer` starts `capability:source_fetch:` |
| `claim:<claim_id>` | `research_claims.claim_id`, same project | `statement`, `source_ref`, `span_ref` |
| `hypothesis:<program_id>/<h_ref>` | `research_programs.program_id` + a `hypothesis_json` entry whose `ref` is `<h_ref>` | the hypothesis spec + falsification condition |
| `prediction:<program_id>/<h_ref>/<p_ref>` | the same program + a `prediction_json` entry whose `ref` is `<p_ref>` and `claim_ref` is `<h_ref>` | the prediction spec |

The program/claim grammar is new **as a dereference rule**, not as a table:
both rows already exist (`migrations.py:419-443`, `:486-507`), and both are
immutable/append-only. `program_id` is `rp_<hash>`, `claim_id` is `cl_<hash>`,
and the embedded hypothesis/prediction `ref` is the row-local name. The slash
is safe: `HypothesisSpec.ref` is validated by `_REF_RE`
(`programs.py:167-170`), which excludes `/`.

`evidence:` remains forbidden in `admission_refs` by OPS-5D
(`workflows.py:620-636`). It is listed here because it is the one namespace the
run itself admits, and because the support invariant needs its `FETCHED`
classification.

### 3.3 The mechanism

```python
@dataclass(frozen=True, slots=True)
class RefBacking:
    origin: str       # "FETCHED" | "ROW"
    witness: str      # "RESOLVER" | "GATEWAY"

def SubstrateStore.admit_ref(
    self, ref: str, project_id: str, *, backing: RefBacking | None = None
) -> SubstrateRefusal | None:
    if backing is None:
        return _refuse(
            PRIOR_ART_UNBACKED,
            f"ref {ref!r} is asserted as prior art but no project row "
            f"carries it — an assertion is not an artifact",
            project_id=project_id, ref=ref)
    self.resolving_refs[str(ref)] = str(project_id)
    self.ref_backing[str(ref)] = backing.origin
    return None
```

- `PRIOR_ART_UNBACKED` is added to `SUBSTRATE_REFUSAL_CODES`
  (`substrate.py:213-217`). It is this plane's code, not a gateway code.
- `run_methodology` (both the plane's `workflows.py:821` and the live
  `methodology_driver.py:656`) calls `admit_ref` for every `admission_refs`
  entry **before any stage, governance consult or model call**. A refusal is
  returned as `MethodologyRefusal(code="PRIOR_ART_UNBACKED", source="inputs")`.
- The live driver obtains the backing from the injected `provenance_of` port.
  The plane's `run_methodology` takes an optional resolver for its own
  fixtures; **omitted, every non-empty `admission_refs` refuses**. That is the
  fail-closed default, and it is what makes the historical seeds refuse in the
  plane's own tests.
- The run's own `evidence:` ref is admitted with
  `RefBacking(origin="FETCHED"|"ROW", witness="GATEWAY")` after the gateway
  admits the `EVIDENCE_TRANSITION`. The witness is the gateway's verdict; the
  driver does not re-check the artifact row. It does ask the port for the
  `FETCHED`/`ROW` classification, because support needs that bit.

### 3.4 What happens to the historical seeds

Every `hypothesis:prior-art-sarsNN/...`, `prediction:...`, `claim:claim-...`
seed names a `program_id`/`claim_id` that does not exist. The port returns
`None`; `admit_ref` refuses; the run stops at intake with a named code instead
of failing at stage 2 or fabricating a citation. **This is the proof the channel
is closed, not narrowed.** A seeded run that wants to cite real prior art must
name a real `rp_...`/`cl_...` row.

### 3.5 Cost of (A)

- Every historical seed refuses. The depth record built on those seeds is
  explicitly untrustworthy until re-run; that is the correct outcome, not a
  regression.
- Every fixture that seeds refs must either drop them (and mint) or supply a
  resolver. The blast radius is enumerated in §9.
- A live operator can no longer make prior art exist by typing it. Until (B)
  gives derived prior art a producer, a *fresh* project has no prior art at
  all — which is true, and which (C) is designed to survive.
- (A) on its own produces no research. It closes a fabrication channel and
  makes the failure honest. (C) is what lets a fresh run think.

---

## 4. §4.2 — the support invariant

### 4.1 The rule, in checkable form

For a `CLAIM` node `C` in project `P`, let `S(C)` be the least set containing
`C` and closed under:

1. every `predecessors` edge of a node in `S(C)` (the node must be recorded in
   `P`);
2. every node's `external_ref`;
3. every node's `admitted_refs`.

`cited_refs` are **excluded**. A citation is a mention; it is not support.

Read this against the charter's wording: the "citation" that may point at a
node minted in this run is the `predecessors` edge — the chain — not the
`cited_refs` field. A minted `mnode_` id is never an artifact ref and can never
appear in `cited_refs` or `admitted_refs`; `resolve_ref` refuses it for having
no artifact namespace. So a minted node can be *in* the chain that reaches a
claim, but it can never be *the external anchor* of that claim.

`C` is recordable only if at least one ref in **`D(C)`**, the *direct support
set*, is **fetched-external**:

- every ref in `C.admitted_refs`; and
- the `external_ref` of every `EVIDENCE` node that `C` directly descends from
  (`REQUIRED_PREDECESSOR["CLAIM"] == "EVIDENCE"`).

A fetched-external ref is one that resolves in `P` to an `artifacts` row with
`artifact_type = 'source_payload'` and `producer` beginning
`capability:source_fetch:`.

`S(C)` is still computed, but only to **explain** a refusal: the detail names
the wider closure and says that no fetched artifact in it is the claim's own
direct support. A fetched artifact elsewhere in the closure — an ancestor's
`admitted_refs`, a sibling's citation, a prior-art claim the run cites — never
launders a `ROW`-backed evidence ref. This is the review's amendment: the
charter's `S(C)` wording was one step too weak because reachability is not
support.

Two shape rules make the closure honest:

- `CLAIM.admitted_refs` must be non-empty and every member must carry the
  `evidence:` namespace. A prior-art `claim:` ref may be **cited**, never
  admitted as support.
- `HYPOTHESIS` and `PREDICTION` may not carry `admitted_refs` at all. A
  conjecture does not support anything, and a minted node must not become an
  anchor by being listed as support.

### 4.2 What is computable from the substrate's own edges

| question | answer | why |
|---|---|---|
| Is a ref reachable from `C`? | **yes** | `predecessors`, `external_ref`, `admitted_refs` are fields on the recorded nodes; `provenance_edges` (`substrate.py:683-702`) is the derived view of the predecessor declarations |
| Is a reachable ref externally anchored? | **no** | `resolving_refs` records only `(ref → project_id)` (`substrate.py:551-562`); the artifact row, its type and its producer live in `artifacts` (`migrations.py:194-208`), which the substrate never reads |
| Is the closure free of cycles? | **yes** | `check_provenance_graph` already refuses a cyclic store at every write (`substrate.py:705-750`) |

So the invariant is **not** computable from the substrate's edges alone. It is
computable from the direct set plus **one bit per resolving ref**:
`ref_backing[ref] ∈ {"FETCHED", "ROW"}`. That bit is stored in the in-memory
`SubstrateStore` (no table, no event, no transaction) and is supplied by the
driver from the read-only `provenance_of` port. The wider `S(C)` walk is still
computed for the refusal detail; it is deliberately not the sufficiency test.

This is the honest boundary: the substrate can prove *shape* and *reachability*;
it cannot prove that bytes came from outside the model. The port is the witness,
and the store records which witness said `FETCHED`. A caller that lies to
`admit_ref` can forge the bit in a unit test; no production caller has a reason
or a path to, and the design does not pretend Python enforces it.

### 4.3 Where it is enforced

`_support_refusal` in `substrate.py:1052-1091`, called from `write_node`
(`:1121`) on the staged store. The staged store includes the candidate node, so
the closure walk sees the claim's own `admitted_refs` and the EVIDENCE
predecessor's `external_ref`. The check runs after shape, refs, provenance and
subject; it is the last refusal before the store is mutated.

`write_node` remains the only chain-write boundary. No new write path, no
transaction, no event.

### 4.4 Adversarial cases

| chain | result |
|---|---|
| `QUESTION → HYPOTHESIS → PREDICTION → EXPERIMENT → OBSERVATION → EVIDENCE → CLAIM`, every node minted, `CLAIM.admitted_refs = ()` | `UNSUPPORTED_CLAIM` — no admitted evidence (existing check) |
| same, `CLAIM.admitted_refs = ("evidence:<id>",)`, artifact is `provider_response` | `UNSUPPORTED_CLAIM` — the ref resolves and is admitted, but `ref_backing["evidence:<id>"] = ROW`, so the closure has no fetched anchor |
| same, artifact is `source_payload` with `producer = capability:source_fetch:...` | records; the closure is anchored |
| `CLAIM.admitted_refs = ("claim:cl_x", "evidence:<id>")` | `MALFORMED_PAYLOAD` — a claim may admit only `evidence:` refs |
| `HYPOTHESIS.admitted_refs = ("claim:cl_x",)` | `MALFORMED_PAYLOAD` — a conjecture carries no support |
| `CLAIM.cited_refs = ("claim:cl_x",)`, no admitted evidence | `UNSUPPORTED_CLAIM` — a citation is not support |
| `CLAIM` admits `evidence:X` (`ROW`); its `EVIDENCE` predecessor cites `evidence:Y` (`ROW`); a fetched `evidence:Z` sits in an ancestor's `admitted_refs` or a cited prior-art claim | `UNSUPPORTED_CLAIM` — `Z` is in the wider closure, not in the direct set; the review's laundering case |
| `CLAIM` admits no evidence ref at all | `UNSUPPORTED_CLAIM` — the old behaviour, unchanged |
| a hand-built store with every direct ref registered `ROW` | `UNSUPPORTED_CLAIM` — the falsifier's "entire support graph minted by the run" case |

The `provider_response` row is the case that matters: the gateway's
`EVIDENCE_TRANSITION` check is `ArtifactRepository.in_project(artifact_id,
project_id)` (`gateway.py:1551-1560`), and
`persistence/provider_interactions.py:184` writes model response bodies as
`artifact_type="provider_response"` with the project id. A model can therefore
propose its own response artifact as "evidence" and the **gateway will admit
it**. The substrate's externality check is the only thing that stops the claim.
That is by design: §5.3 leaves the gateway's checks untouched.

---

## 5. §4.3 — exact constant changes

### 5.1 Substrate constants (`src/hermes/methodology/substrate.py`)

| constant | before | after |
|---|---|---|
| `REFERENCED_NODE_KINDS` (`:153`) | `{HYPOTHESIS, PREDICTION, EVIDENCE, CLAIM}` | `{EVIDENCE}` |
| `NEW_NODE_KINDS` (`:147`) | `{QUESTION, EXPERIMENT, OBSERVATION, CRITIQUE, CONCLUSION}` | `{QUESTION, HYPOTHESIS, PREDICTION, EXPERIMENT, OBSERVATION, CLAIM, CRITIQUE, CONCLUSION}` |
| `REF_NAMESPACES` (`:159`) | `{HYPOTHESIS: "hypothesis:", PREDICTION: "prediction:", EVIDENCE: "evidence:", CLAIM: "claim:"}` | **unchanged** — it is the artifact-ref grammar, no longer 1:1 with node kinds |
| `CHAIN_KINDS` (`:165`) | the nine-stage tuple | **unchanged** |
| `ALLOWED_TRANSITIONS` (`:174`) | the nine predecessors | **unchanged** |
| `NODE_CONTENT_KEYS` (`:224`) | `{question, external_ref, question_ref, subject_ref, assertion, admitted_refs, cited_refs, predecessors, summary, label}` | add `statement`, `origin` |
| `SUBSTRATE_REFUSAL_CODES` (`:213`) | 8 codes | add `PRIOR_ART_UNBACKED` |
| `AUTHORED_ID_KEYS` (`:220`) | unchanged | **unchanged** |
| `SUBSTRATE_SCHEMA_VERSION` | `"1"` | **unchanged** — no durable record changes; a node that carries no new key keeps its identity, and a minted node's identity changes because its content does |

`REF_NAMESPACES` staying four means the test invariant
`set(REF_NAMESPACES) == REFERENCED_NODE_KINDS`
(`tests/test_methodology_plane.py:354`) must become
`REFERENCED_NODE_KINDS <= set(REF_NAMESPACES)`, with `EVIDENCE` named as the
only citation kind. The union/disjointness invariant
(`CHAIN_KINDS == NEW_NODE_KINDS | REFERENCED_NODE_KINDS`,
`:341-342`) still holds.

### 5.2 Shape rules (`_kind_refusal`, `:838`)

- The `NEW_NODE_KINDS` branch already refuses a non-empty `external_ref` for
  local kinds (`:841-864`). `HYPOTHESIS`, `PREDICTION` and `CLAIM` now enter
  that branch.
- Add, for those three kinds:
  - `statement` must be a non-empty string;
  - `origin` must be exactly `"MINTED"`;
  - `admitted_refs` is refused for `HYPOTHESIS`/`PREDICTION`; for `CLAIM` it
    must be non-empty and every member must start `evidence:`.
- The referenced-kind branch (`:866-884`) now applies only to `EVIDENCE`:
  non-empty `external_ref`, `evidence:` namespace. No semantic change.
- `QUESTION`, `EXPERIMENT`, `OBSERVATION`, `CRITIQUE`, `CONCLUSION` are
  unchanged. `CRITIQUE.subject_ref` still dereferences a recorded node
  (`:1000-1018`); `CONCLUSION.question_ref` still requires a complete lineage
  (`:1078-1091`).

### 5.3 Ref resolution (`_refs_refusal`, `:905`)

- Referenced-kind side (`:933-950`): only `EVIDENCE` now; its own
  `external_ref` resolves under admission semantics exactly as today.
- Local-kind side (`:952-962`): the existing defense-in-depth refusal of a
  non-empty `external_ref` now covers `HYPOTHESIS`/`PREDICTION`/`CLAIM`.
- `admitted_refs` (`:963-967`): for `CLAIM` only; every member resolves under
  admission semantics. The all-`evidence:` shape rule is the kind check above.
- `cited_refs` (`:968-982`): unchanged; a mention must resolve in-project, a
  retracted one is allowed here and only here.

### 5.4 Store (`SubstrateStore`)

- Add `ref_backing: dict[str, str]` (`ref → "FETCHED"|"ROW"`), default empty.
- `to_mapping()` adds `"ref_backing": dict(sorted(self.ref_backing.items()))`.
- `from_mapping()` accepts the key, defaults it empty, and still refuses
  unknown keys. An old mapping with no `ref_backing` reads as an all-`ROW`
  store: claims refuse. Fail-closed.
- `admit_ref` returns `SubstrateRefusal | None` as in §3.3. The docstring's
  last-writer-wins note stays; the backing bit makes a production re-home
  impossible because the port is project-scoped, but the in-memory fixture API
  is not a security boundary and this note does not pretend it is.

### 5.5 Is a kind ever both mintable and citable?

**No, as a node kind.** The kind selects the content rule and the identity
rule; a node cannot be both "the run's own conjecture with inline content" and
"a citation whose identity is someone else's artifact". Citation is a field:
any minted node may carry `cited_refs`, which resolve as mentions and never
count as support. `EVIDENCE` is the one citation kind because it has a
producer, an artifact-checked ref, and a gateway admission behind it.

If a future slice wants a prior-art `EVIDENCE` node that is also a local
observation, that is a new kind and a new design gate. It is not this slice.

---

## 6. §4.4 — labels, origin, and the depth field

### 6.1 Labels

| old | new |
|---|---|
| `_PRIOR_ART_LABEL = "prior-art citation (no producer in this build)"` (`workflows.py:594`) | `_MINTED_LABEL = "run-minted conjecture, not prior art"` |
| `_CLAIM_IDENTITY_LABEL = "claim identity is prior art; support is the recorded evidence ref"` (`:595-596`) | `_MINTED_CLAIM_LABEL = "run-minted claim; support is the admitted evidence ref"` |

The node itself carries `origin: "MINTED"` and `statement: <the run's text>`.
The label is appended to the rationale (a node field that does not re-enter a
later prompt), exactly where the old prior-art label was. The distinction is
therefore visible in four places:

- **content**: `origin` and `statement` on the node;
- **rationale**: `_MINTED_LABEL` / `_MINTED_CLAIM_LABEL`;
- **run report**: `StageOutcome.content_origin` is `"MINTED"` for the three,
  and empty for every other kind, carried by the methodology run's own report
  mapping (`MethodologyExecution.to_mapping()` / `MethodologyRun.to_mapping()`).
  The CLI's OPS-10 diagnostic report is a different surface and reports no
  prior-art claim at all, so it cannot misreport one;
- **depth record**: `backing_class` on the terminal `TaskStatusChanged`
  payload (§6.3) — an `EVIDENCE` over model-authored bytes reads `ROW`
  before the claim refuses, so the run record needs no prose inference.

`StageOutcome.to_mapping()` adds `content_origin` only when non-empty, so a
non-minted stage's mapping is unchanged; a minted stage's mapping and the run
digest change because its content changed. No LOOP or B4 baseline builds a
minted chain (neither test imports the methodology plane), so §5.4 is not at
risk from this field.

### 6.2 Where the statement comes from

The review's Q1 ruling is accepted: **the rationale is not the statement.** A
rationale answers *why I propose this*, not *what is claimed*; a field named
`statement` holding a justification is the defect class this project has spent
nine slices removing.

**A tree correction to the review's remedy.** The review says "add `statement`
to `schemas.draft` (a one-line contract change)". In this tree that line is
inert: `ProfileSpec.schemas` is loaded (`config.py:354`) and **never read**; the
runtime builds the contract in `output_contract_for` (`run.py:329-410`) from
`model_policy`, and the closed draft vocabulary is
`DRAFT_KEYS = {kind, rationale, payload}` (`run.py:263`), enforced per draft at
`:1115`. Adding `statement` to the YAML alone would be refused as an unknown
draft key. The real change has five surfaces:

1. `run.py`: `DRAFT_KEYS` gains `statement`; `output_contract_for` renders it
   (string, optional); `_validate_drafts` reads it (non-empty, ≤ 2000 chars)
   and returns it; `_emit_drafts` / `_emit_intent` thread it onto `Proposal`;
   the wire-shape docstring at `:120-130` gains it.
2. `types.py`: `Proposal.statement: str = ""`; `to_mapping` and `draft_digest`
   include it **only when non-empty**, so a proposal without one keeps its
   existing digest.
3. `profiles/{researcher,experimenter,synthesizer}.yaml`: `schemas.draft`
   names `statement` as documentation; the runtime contract, not the YAML, is
   the enforcement.
4. the contract-rule tests (`test_ops9_contract_rules`, `test_agent_runtime`);
5. the stage objectives: the three stages ask for `statement` in the draft;
   only the `HYPOTHESIS` objective's prior-art instruction is corrected per
   §5.5.

The stage's `statement` is then:

1. `inputs.stage_content[kind]["statement"]` when a caller supplies it
   (fixtures and the plane's own tests); otherwise
2. the first **admitted** proposal's `proposal.statement`, stripped; otherwise
3. the stage is refused at the chain write with `MALFORMED_PAYLOAD` — a minted
   conjecture with no statement is not a node.

The selection is one helper, `_minted_statement(kind, inputs, proposals)`, in
`workflows.py`; both drivers call it before `_default_content` and pass the
result as `statement`. The helper never invents text and never reads the
question as a fallback.

If the Director judges the runtime-contract change outside this slice, the
review's fallback is **not available as written**: the run's evidence artifact
is a `source_payload`, not a `research_claims` row, so it has no recorded
`statement` to copy. The fallback would need a separate evidence-to-statement
producer. The contract change is the only honest source in this build; the
fallback is recorded here as rejected for that reason, not silently dropped.

For the same three kinds, `_default_content` writes `external_refs[kind]` (when
non-empty) to `cited_refs`, **never** to `external_ref`. That is the whole
change of meaning for the field: it names a prior-art mention on a minted node,
not the identity of the node.

A stage whose run proposed nothing does not get a node. That is the same
refusal-as-data discipline the rest of the plane uses.

One stage objective is corrected (`workflows.py:424-432`): the `HYPOTHESIS`
objective currently says "cite the prior art you were given: the `hypothesis:`
ref in the task input" — that instruction is part of the defect and is
replaced with "state a testable hypothesis of your own in your proposal's
rationale; if prior art was admitted, cite it as a citation, never as your
hypothesis." `PREDICTION` and `CLAIM` objectives are **not** changed: neither
instructs the model to cite a ref that cannot exist, and §5.5 forbids touching
them for any other reason. Their statement is read from whatever rationale
their admitted proposal carries; if there is none, the node refuses.

### 6.3 Depth as a field

`HandlerResult` (`source_handlers.py:369-393`) gains:

```python
stage_depth: int = 0        # stages actually recorded
stage_reached: str = ""     # the stage whose run was attempted / stopped it
stages_declared: int = 0    # the document's declared stages
refusal_code: str = ""      # the code that stopped the run, at that stage
backing_class: str = ""     # the evidence ref's backing: FETCHED / ROW / ""
```

`MethodologyRefusal` gains `backing_class: str = ""`; `StageRecord` carries the
same for the stage that admitted the evidence. The driver knows both values
from the refusal and from the port, so the handler does not parse prose.

`TaskRepository.transition_status` (`repositories.py:615-712`) gains an optional
`details: Mapping[str, Any] | None = None`, passed as the event `payload` to
`_append_event` (`:441-453`). The existing 4 KiB validator
(`persistence/event_validation.py:21`) still runs. The controller attaches the
handler's five values to the terminal transition it writes for the dispatch
(`controller.py:3272-3300`), and threads them through `_retry_or_fail` so the
eventual `FAILED` carries the last dispatch's depth. A handler that reports no
depth writes no key, so every existing event payload is byte-identical.

`scripts/depth_report.py` reads, in order:

1. `payload_json.stages_recorded` / `stage_reached` / `refusal_code` /
   `backing_class` on `TaskStatusChanged` — `depth_source: "field"`;
2. the existing `STAGES_RECORDED` prose regex (`depth_report.py:44`) —
   `depth_source: "prose"`;
3. nothing — `unrecorded`, as today.

The report prints the source and the two stop discriminators: a run that stops
at `EVIDENCE` for want of a fetched artifact reads `stage_reached=EVIDENCE`,
`refusal_code=MALFORMED_PAYLOAD`, `backing_class=""`; a run that records an
`EVIDENCE` over model-authored bytes and stops at `CLAIM` reads
`stage_reached=CLAIM`, `refusal_code=UNSUPPORTED_CLAIM`, `backing_class=ROW`.
Without both fields the next depth report reads `unrecorded` again and the
measurement is wasted (review Q5). This is the change §7.6 requires; it is
**not** the completion gate and **not** the rejection record (§5.7).

---

## 7. §4.5 — does the fix reach `EVIDENCE`?

### 7.1 The mechanism is present

- The live composition builds the research egress supply
  (`composition.py:964-970`), wires `source_search`/`source_fetch` grants and
  the capability recorder into the controller (`:1015-1028`).
- The `researcher` profile carries both tools and `EVIDENCE_TRANSITION` in its
  proposable kinds (`profiles/researcher.yaml:24,32`).
- The `OBSERVATION` stage is `researcher`, `max_ticks: 3`, and its objective
  spells out search → fetch → propose (`workflows.py:443-455`).
- `source_fetch` writes a `source_payload` artifact with
  `producer="capability:source_fetch:..."` (`capability_supply.py:749-756`).
- The gateway's `EVIDENCE_TRANSITION` validator dereferences the artifact row
  in-project (`gateway.py:1551-1560`); the driver projects the admitted ref
  into the store (`methodology_driver.py:295-305`).
- The `EVIDENCE` stage writes `external_ref = evidence_ref`
  (`workflows.py:752-755`); the store resolves it because the driver admitted
  it.

So `EVIDENCE` is reachable **structurally**. No constant change is needed for
it, and the same is true of `CRITIQUE`/`CONCLUSION`: their checks already work
once the chain reaches them.

### 7.2 The remaining risks, named now

1. **Model compliance, not structure.** The model must fetch before it
   proposes; a proposal ends the `OBSERVATION` stage. If it proposes an
   `EVIDENCE_TRANSITION` before any fetch, no artifact exists, the gateway
   refuses `EVIDENCE_REF`, no `evidence_ref` is selected, and `EVIDENCE` refuses
   `MALFORMED_PAYLOAD` (empty `external_ref`). The objective already says this;
   run 39 measures whether the model obeys.
2. **A non-fetched citation can reach `EVIDENCE`.** The gateway admits *any*
   project artifact, including `provider_response` (`provider_interactions.py:184`).
   The substrate's `EVIDENCE` shape gate only checks that the ref is a
   non-empty `evidence:` string that resolves; it does not require a fetched
   artifact. Therefore an `EVIDENCE` node can be recorded over model-authored
   bytes, and the chain stops at `CLAIM` with `UNSUPPORTED_CLAIM`. This is the
   designed boundary: §5.3 leaves the gateway untouched, and support is the
   claim's question, not the citation's. The `EVIDENCE` rationale carries the
   port's classification (`"cited artifact is a fetched source"` /
   `"cited artifact is not a fetched source — a claim over it will refuse"`) so
   the record is not misleading.
3. **If the Director wants `EVIDENCE` itself to refuse a non-fetched
   artifact**, that is a separate decision and needs its own code (the
   substrate would have to refuse a ref that resolves). This note does not
   take it, because it would make `EVIDENCE` uncitable in fixtures that do not
   wire the port and because the support invariant already stops the claim.
   It is listed in §11 as an open decision.

### 7.3 What run 39 should show

If the model fetches and proposes, the chain reaches `EVIDENCE` and then
`CLAIM`; the claim records only if the fetched artifact is
`source_payload`/`capability:source_fetch:`. If it does not, the chain reaches
`EVIDENCE` and the claim refuses with `UNSUPPORTED_CLAIM`. Both outcomes are
measurements; neither is a fabricated prior art.

---

## 8. §4.6 — falsifiers, mapped to tests

| falsifier | how it is proved |
|---|---|
| a fresh project with no `external_refs`/`admission_refs` reaches `PREDICTION` | plane test: `run_methodology` with empty inputs and a scripted model; assert `HYPOTHESIS` and `PREDICTION` nodes carry `statement`/`origin=MINTED`, no `external_ref`, and `reconstruct_chain` stops at the first absent stage rather than refusing at HYPOTHESIS |
| a fresh project reaches `EVIDENCE` with a fetched artifact, external provenance | live/plane test with a fake `source_fetch` artifact row (`source_payload`, `capability:source_fetch:`) and an admitted `EVIDENCE_TRANSITION`; assert the `EVIDENCE` node records and the `CLAIM` records only when the port says `FETCHED` |
| an all-minted support graph is refused | unit: hand-build the chain with `admit_ref(..., backing=ROW)`; `write_node(CLAIM)` returns `UNSUPPORTED_CLAIM` |
| a fetched artifact elsewhere in the closure does not launder a `ROW`-backed admission | unit: the claim admits `evidence:X` (`ROW`); a fetched `evidence:Z` is an ancestor's admission or a cited prior-art claim; `write_node(CLAIM)` returns `UNSUPPORTED_CLAIM` and the detail names the wider closure as explanation only |
| a claim with no admitted `evidence:` ref still refuses exactly as today | the existing `UNSUPPORTED_CLAIM` test is kept unchanged; the new rule narrows, it does not replace |
| an unbacked `admission_refs` entry refuses at intake | unit: `admit_ref(ref, project)` with no backing returns `PRIOR_ART_UNBACKED`; driver: non-empty `admission_refs` with no resolver returns a `MethodologyRefusal` before any model call; the historical `prior-art-sarsNN` seeds are the regression fixture |
| a minted hypothesis is never reported as prior art | node content `origin`/`statement`; rationale contains `_MINTED_LABEL` and not the old string; `StageOutcome.content_origin == "MINTED"`; `_PRIOR_ART_LABEL` is deleted |
| a claim citing an unbacked ref still refuses | `resolve_ref` is unchanged: a ref not in `resolving_refs` returns `EVIDENCE_DOES_NOT_RESOLVE` |
| drain-only byte-identical; census unchanged | `.venv/Scripts/python.exe scripts/check_census.py` and the existing drain-only snapshot test; expected `124 / 28 (19/5/4) / 1 / 15 / 0` |

The existing `test_ops5d_proposal_content.py:328-331` assertion on the old
labels is replaced by the minted-label assertion; it is not deleted, because
the falsifier is exactly about the label.

---

## 9. Blast radius

### 9.1 Product files

| file | change |
|---|---|
| `src/hermes/methodology/substrate.py` | constants, `RefBacking`, `admit_ref`, shape/refs/support checks, store mapping |
| `src/hermes/methodology/workflows.py` | inputs docs, seeding, `_default_content`, `_node_rationale`, labels, objectives, `StageOutcome.content_origin`, optional resolver |
| `src/hermes/research/task_handlers/methodology_driver.py` | seeding, port plumbing, statement selection, EVIDENCE provenance rationale, `StageRecord`/depth |
| `src/hermes/research/task_handlers/__init__.py` | handler wiring for the port; `HandlerResult` depth values on every return |
| `src/hermes/research/source_handlers.py` | `HandlerResult` optional fields |
| `src/hermes/research/controller.py` | pass the depth details to the terminal transition (and through `_retry_or_fail`, so the eventual `FAILED` carries the last dispatch's depth) |
| `src/hermes/persistence/repositories.py` | `transition_status(details=...)` |
| `src/hermes/composition.py` | build the `provenance_of` port from `ArtifactRepository` + program/claim rows; pass it to the handler |
| `src/hermes/persistence/chain_refs.py` (new, read-only) | the four namespace dereferences (`evidence:`, `claim:`, `hypothesis:`, `prediction:`) as project-scoped `SELECT`s; no write, no transaction, no new owner |
| `src/hermes/research/chain_refs.py` (new, read-only) | the ref parser + `provenance_of` adapter, mirroring the OPS-18 projection/adapter split; the driver receives it as a callable, so the handler package still never imports persistence |
| `scripts/depth_report.py` | read the depth, refusal and backing fields, fall back to prose, print the source |
| `scripts/seed_methodology_run.py` (new, phase-2 tooling) | the run-38 seed script promoted from `D:/New folder/.tmp-seed-run38.py`: parameterised (project, question, admission refs, provider), dry-run by default, seeds only through `apply_intent` |

The two new files are read-only projections; they add no transaction-control
call and no acquisition owner, so the census is unaffected. The driver must
not import `hermes.persistence`; the composition owns the concrete reader and
injects it, exactly as it injects `ProjectIndexReader` today.

### 9.2 Fixtures and tests

The semantic change is expected to touch:

- `tests/test_methodology_plane.py` — `_fresh`/`_build_chain` (mint instead of
  cite), the constant inventory (`:336-354`), the citation assertions
  (`:859-875`), the cross-project/retraction fixtures;
- `tests/test_ops5d_proposal_content.py` — labels and the claim's
  `external_ref` assertion;
- `tests/test_ops5m_truncated_chain.py`, `tests/test_ops5l_evidence_ref_and_completion.py`,
  `tests/test_ops5t_completion_truth.py` — `chain_inputs` seeds become minted
  or backed;
- `tests/test_wiring_w3.py`, `tests/test_wiring_w4.py`,
  `tests/test_ops7_input_projection.py`, `tests/test_ops1_live_cli.py`,
  `tests/test_loop0_e1_probe.py` — spec/inputs fixtures;
- `src/hermes/methodology/swap_test.py` — `chain_inputs` drops the prior-art
  seeds; the swap probe is about documents, not citations, and should exercise
  the minted path;
- `tests/test_loop_baseline.py`, `tests/test_b4_ref_graphs.py` — **not
  expected to change** (neither imports the methodology plane); verify, do not
  assume.

The fixture rewrite is mechanical but not small. The note states it here so
the implementation gate does not discover it at the first red test.

---

## 10. What must not change

- **No new event kind, write path or transaction.** The only durable change is
  an optional payload key on the existing `TaskStatusChanged` event, written by
  the existing `transition_status` transaction.
- **The gateway's checks, grants and governance plane are untouched.** The
  `provider_response` hole is closed at the claim, not at the gateway; §5.3 is
  honoured literally.
- **No new table, migration or acquisition owner.** `check_census.py` must
  reproduce `124 / 28 (19/5/4) / 1 / 15 / 0`; a delta is a finding and stops
  the slice.
- **Drain-only byte-identical.** The CLI's drain-only path composes no
  handlers; the depth payload is never written there.
- **`proposable_kinds`, `max_ticks`, the act-key and the stage objectives**
  change only where the objective instructed the model to cite a ref that
  cannot exist. The `HYPOTHESIS` objective is the one such instruction; the
  other eight objectives are untouched, and any change to them is a finding.
- **No key material.**
- **The completion gate (`_zero_admission_reason`) and the `IntentRejected`
  record are not touched.** They are real and downstream; a gate that counts
  the right admissions is worthless while nothing is produced to admit.

---

## 11. What I could not decide — and how it was ruled

The review of `1d54f52` (2026-10-28) ruled all five. Each entry keeps the
question and records the ruling that now binds phase 2.

1. **The `statement` source — ruled: not the rationale.** Accepted. §6.2
   carries the corrected design: `statement` becomes a runtime draft field
   (`DRAFT_KEYS`, `output_contract_for`, `_validate_drafts`, `Proposal`,
   conditional `draft_digest`), with `inputs.stage_content[kind]["statement"]`
   as the fixture path. One correction to the review's remedy: adding the key
   to `schemas.draft` alone is inert in this tree, because
   `ProfileSpec.schemas` is loaded and never read; §6.2 lists the five surfaces
   that actually enforce it. The fallback (copy the cited evidence's recorded
   statement) is rejected for the reason given there: the run's evidence
   artifact is a `source_payload`, not a `research_claims` row, so there is no
   statement to copy.
2. **`claim:<claim_id>` — ruled: accepted as written.** A ref names a row; a
   content hash is an idempotency key whose meaning shifts under supersession.
   (B) may prefer content hashes; that is a later decision.
3. **`EVIDENCE` refuses a non-fetched artifact — ruled: no, plus an
   addition.** Accepted for the two reasons in §7.2 and the review's third: a
   `ROW`-backed citation is legitimate (a dataset manifest), and "is this
   claim anchored to bytes from outside the model?" is the claim's question,
   not the citation's. Addition, now §6.3: the backing class reaches the
   run/depth record as `backing_class`, so a run that stops at `CLAIM` can be
   read without inference.
4. **No operator command for backed refs — ruled: a usability gap, with one
   action.** Accepted. Phase 2 promotes the run-38 seed script into
   `scripts/seed_methodology_run.py`, parameterised (project, question,
   admission refs, provider) and dry-run by default; §12.8 depends on it. This
   note does not copy the file: the phase-1 commit is docs-only, and the
   promoted script is code that seeded through `apply_intent` and must be
   reviewed as such.
5. **Fetch-then-propose is unproven — ruled: run 39 is the measurement, and
   the record must distinguish the stops.** Accepted. §6.3 now carries
   `stage_reached`, `refusal_code` and `backing_class`, so "stopped at
   `EVIDENCE` for want of a fetched artifact" and "stopped at `CLAIM` with
   `UNSUPPORTED_CLAIM`" are different readings of the same record.

---

## 12. Phase-2 gates

The charter's gates, with the additions this note implies:

1. **Targeted:** the new test file `tests/test_ops5y_prior_art.py`,
   `test_methodology_plane` (the substrate and the `swap_test` helper),
   `test_ops5d_proposal_content`, `test_ops5m_truncated_chain`,
   `test_loop_baseline`, `test_b4_ref_graphs`, `test_census_check`, plus the
   fixtures in §9.2 that the semantic change touches.
2. `scripts/run_tests.py` (full).
3. `scripts/stamp_suite_count.py` then `--check` (the new tests change the
   collected count; the stamp is generated, never hand-edited).
4. `scripts/check_census.py` — unchanged, or the delta is reported and the
   gate stops.
5. `uvx ruff check src tests scripts`; `uvx pyright src`; pyright tests
   project.
6. `scripts/depth_report.py --db ... --project <fresh>` after a live run: the
   project must read `depth_source: "field"` at the stage the run actually
   reached, not `unrecorded`, and must print `stage_reached`,
   `refusal_code` and `backing_class`.
7. **The review's two falsifiers are required tests, not options:**
   (a) a `CLAIM` that admits a `ROW`-backed `evidence:` ref refuses with
   `UNSUPPORTED_CLAIM` even when a fetched artifact sits elsewhere in its
   closure (§4.4, the `Z` row); (b) a `CLAIM` with no admitted `evidence:` ref
   is `UNSUPPORTED_CLAIM` exactly as today — the change narrows the invariant,
   it does not replace it.
8. `scripts/seed_methodology_run.py` exists, is dry-run by default, and can
   seed a fresh project with empty or backed refs through `apply_intent`; gate
   6 uses it.

A red gate stops the change. The phase-1 commit is this note only; no product
code, no test change.

---

## 13. Amendment 1 — disposition of the review

Reviewed 2026-10-28 against `1d54f52`. The review approved the central decision
((A) + (C), (B) deferred) and required one amendment; it ruled all five §11
questions. The note is amended in place rather than annotated, so no section
below still argues a position the review rejected.

| review item | disposition | where |
|---|---|---|
| §2 direct support | accepted; `D(C)` — the claim's own admitted refs plus its direct `EVIDENCE` predecessor's `external_ref` — is the sufficiency set. `S(C)` is retained only as the refusal explanation. | §0.5, §4.1, §4.2, §4.4 |
| Q1 `statement` | accepted; the rationale is rejected as a statement. The change is the five-surface draft-contract edit, with the inert-`schemas` correction to the review's remedy. | §6.2, §11.1 |
| Q2 `claim:<claim_id>` | accepted as written. | §3.2, §11.2 |
| Q3 `EVIDENCE` does not refuse | accepted; the backing class is added to the run/depth record. | §6.1, §6.3, §7.2, §11.3 |
| Q4 no operator command | accepted; the seed script is promoted to `scripts/` in phase 2, not in this docs commit. | §9.1, §11.4, §12.8 |
| Q5 unproven fetch-then-propose | accepted; the depth record distinguishes the two stopping cases. | §6.3, §11.5 |
| review gates 1-3 | accepted as §12 item 7 (gates 1-2) and the extended gate 6 (gate 3); item 8 is the Q4 action. | §12 |

The amendment widens nothing: no new write path, no new event kind, no new
transaction, no new acquisition owner. The census target stays
`124 / 28 (19/5/4) / 1 / 15 / 0`, and a delta still stops the slice.

What the amendment changes in the *reasoning*, not just the wording:

1. Reachability was doing work it cannot do. A fetched artifact anywhere in a
   claim's closure used to satisfy the rule; it no longer does. The claim must
   be anchored by something it admits, or by the evidence it directly
   descends from. This is strictly narrower and is the charter's intent read
   correctly.
2. The refusal detail still names the wider closure, because that is how an
   operator learns *why* a fetched ancestor did not help. The detail is
   explanation; `D(C)` is the test.
3. The depth record now carries the refusal, not only the stage. A depth
   number without the code that stopped the run is a number that invites the
   next audit to re-derive the same finding.

---

## Appendix — code anchors read for this note

```text
src/hermes/methodology/substrate.py        147, 153, 159, 165, 174, 213, 224,
                                            391, 551-562, 613-662, 683-702,
                                            705-750, 838-884, 905-982,
                                            1052-1091, 1093-1135
src/hermes/methodology/workflows.py        424-432, 485-506, 594-596, 620-636,
                                            710-728, 732-770, 789-941
src/hermes/research/task_handlers/methodology_driver.py
                                            295-305, 568-590, 611-805
src/hermes/research/task_handlers/__init__.py
                                            249-400, 404-437, 491-505
src/hermes/research/source_handlers.py     369-393
src/hermes/research/controller.py          3258-3300
src/hermes/persistence/repositories.py     441-453, 615-712, 953-1035
src/hermes/persistence/migrations.py       194-208, 419-443, 486-507
src/hermes/persistence/provider_interactions.py 184
src/hermes/research/gateway.py             1541-1560
src/hermes/research/capability_supply.py   725-770
src/hermes/composition.py                  964-1028
src/hermes/agents/runtime/profiles/researcher.yaml 24, 32
scripts/depth_report.py                    44, 145-185
tests/test_methodology_plane.py            336-354, 859-875
tests/test_ops5d_proposal_content.py       328-331
```

Measured on this tree, 2026-10-28:

```text
scripts/check_census.py  PASS
  executed transaction-control calls 124
  acquisition owners 28 (persistence 19, gateway 5, Controller 4)
  rollback-only participants 1
  persistence->research import statements 15
  control calls outside certified layers 0
```
