# OPS-5D — from proposal to substrate content

| Item | Value |
| --- | --- |
| Task | OPS-5D: make the agent's admitted work the content of the node that records it |
| Base | `main` at `1bf49ef` (OPS-5C merged) |
| Branch | `slice/ops-5d-proposal-content` |
| Phase | **1 — design gate. No code in this phase.** |
| Status | **APPROVED for phase 2 (2026-10-25)** — A at the evidence position, with the prior-art remainder labelled; full A is the OPS-5E follow-on, not this slice |
| Run 13 | `M2(calls=2, repeat=0.000)`; 2 searches (pubmed, openalex), both `RECORDED_SUCCESS`; **0 artifacts, 0 fetches**; `PROPOSAL: evidence artifact 'synthetic-sars13/e1' not in project` ×3 |

## 0. Verdict summary

1. **A, for the evidence position, is chosen.** The `EVIDENCE` node's
   `external_ref` comes from the model's **admitted** `EVIDENCE_TRANSITION`
   proposal — the artifact the agent fetched — not from the operator's seed.
   The `OBSERVATION` node carries the same ref as a *cited* (mention) ref when
   it was admitted by that stage, and the `CLAIM` node's `admitted_refs` is the
   **recorded** `EVIDENCE` ref. The node's `rationale` is the admitted
   proposal's rationale. The artifact-row check is the gateway's existing
   `EVIDENCE_REF` check; the driver never reads the artifact table.
2. **Full A is blocked for `HYPOTHESIS`, `PREDICTION` and `CLAIM` by two
   frozen rules, not by preference.** `substrate._kind_refusal` requires a
   non-empty, namespace-correct `external_ref` for **every** referenced kind,
   and no model-proposable intent mints an artifact in the
   `hypothesis:`/`prediction:`/`claim:` namespaces. `IntentKind.llm_proposable`
   has no claim/hypothesis/prediction kind, and every profile's
   `proposable_kinds` is fixed by invariant 5. Full A would need either a new
   artifact-producer/proposable-kind gate (violates "proposable_kinds and the
   tool grants unchanged" and "no new write path") or an inline citation for a
   referenced kind (violates "the substrate's content rules stay as they are").
   Those three positions therefore keep **operator-supplied prior-art
   citations**, explicitly labelled; the evidence position does not.
3. **The operator's synthetic evidence ref is removed by the design, not
   preserved.** The live task handler and the plane driver refuse an
   `evidence:` ref in `external_refs`, `admission_refs` or in the evidence
   position's `stage_content`; the agent's admitted ref replaces it.
   `retracted_refs` is the N9 projection, not a citation or a resolver entry:
   an evidence ref there is allowed because it can only remove support, never
   make a ref resolve or be cited. The prior-art refs (`hypothesis:`,
   `prediction:`, `claim:`) may remain in the seed because their producers do
   not exist in this build.
4. **B is rejected.** The methodology cannot resolve a "newest admitted
   artifact of the right type" for the three prior-art kinds (there are no such
   artifacts), so B fixes at most the evidence position — where it also decides
   *for* the agent which artifact is the evidence. It would either read the
   OPS-18 project-index view (bounded to 40 entries, a prompt view rather than
   a resolver, and truncation can omit the artifact) or need a dedicated
   artifact read port (the driver's import discipline forbids a repository
   import). B is the wrong authority and still incomplete.
5. **C is rejected.** It is the status quo: the agent's fetch never becomes the
   chain's evidence, and the seed's fake ref keeps pre-empting it. That is the
   wall run 13 measured.
6. **No new event kind, write path or transaction.** The only new act is an
   in-memory `SubstrateStore.admit_ref` projection of a ref the gateway already
   admitted; the store already uses that act for the seed. The artifact check
   is the gateway's, not a second one. Census unchanged.
7. **The falsifier is achievable with the authority that exists.** A scripted
   run can fetch (OPS-5C), propose `EVIDENCE_TRANSITION` citing the fetched
   `evidence:<artifact_id>`, and record an `EVIDENCE` node whose
   `external_ref` is that artifact. The phase-2 tests pin it.
8. **What this does not claim.** It does not claim a complete, truthful chain
   for the three prior-art positions; it does not claim relevance, validity or
   scientific reproducibility; and it does not treat a replay as evidence of
   validity. It claims the evidence position, the validation path, the no-ref
   behaviour and the seed rule.

### 0.1 The one sentence to carry forward

**The evidence position records the agent's admitted evidence ref — the
artifact it fetched and cited through `EVIDENCE_REF` — while the three
prior-art positions remain operator-supplied citations until their artifact
producers exist, and the record says which is which.**

### 0.2 Director ruling (phase 2)

**Approved: A at the evidence position, with the prior-art remainder
labelled.** Not full A, and not a rule relaxation. The evidence position gets
the fix; the other three positions stay prior art and are labelled in the note
and in the node rationale.

**OPS-5E — the artifact-producer gate.** *Until a producer exists for
`hypothesis:`, `prediction:` and `claim:`, those positions cite prior art and
the chain's only agent-gathered evidence is the `EVIDENCE` ref.*

Answers recorded at approval:

- **Q3 (rationale carries model text): approved.** The node `rationale` is a
  node field, not content, and it does not re-enter the next prompt.
- **Q5 (the claim's own `external_ref` stays prior art): approved, labelled.**
  The claim's identity is prior art; its support is the recorded evidence ref.
- **Q6 (delegated child proposals not traversed): recorded as a known limit,
  not fixed here.**
- **Q1, Q2, Q4:** as recommended.

Phase-2 scope clarification, recorded because it preserves N9: the seed
refusal covers the citation/resolution positions (`external_refs`,
`admission_refs`, and the evidence position's `stage_content`). A
`retracted_refs` entry is the N9 projection and may name an evidence ref; it
cannot make a fake resolve or be cited, and refusing it would make N9
unreachable for agent evidence.

## 1. The measurement, and the code path that explains it

### 1.1 Run 13

With the capability plane and the actionable search handle both landed, run 13
executed two searches (PubMed and OpenAlex, both `RECORDED_SUCCESS`), fetched
nothing, and cited `synthetic-sars13/e1` three times. Every citation was refused
`PROPOSAL: evidence artifact 'synthetic-sars13/e1' not in project`. The model
did what the prompt allowed; the chain still could not record the agent's work.

### 1.2 The production path, in order

1. The task handler reads the task's `spec["inputs"]` into `MethodologyInputs`
   (`research/task_handlers/__init__.py:319`, `_inputs_from_spec` at `:415`).
   The operator's `external_refs` and `admission_refs` enter here.
2. The live driver (`research/task_handlers/methodology_driver.py:492`) builds
   an in-memory `SubstrateStore` and admits every `inputs.admission_refs` as a
   resolving ref (`:521-525`). That registry is a *fixture act*: it records a
   string as resolving in a project and checks no artifact row.
3. Per stage it runs the profile (`:571-585`). The run may fetch and may propose
   `EVIDENCE_TRANSITION`; the gateway validates the proposal (see §4).
4. The driver then ignores `wired.result.proposals` and builds the node from
   `methodology_plane._default_content(...)` (`:593`).
5. `_default_content` (`methodology/workflows.py:462-480`) reads
   `inputs.external_refs[kind]` for every referenced kind:
   `EVIDENCE` gets the seed's `evidence:synthetic-sars13/e1`, never the model's
   admission.
6. `write_node` resolves the node's refs against the store's registry
   (`substrate.py:1093-1141`); the seed's fake ref is in that registry, so the
   node is recorded. The agent's real ref is not in the registry, and the node
   never names it.
7. The next stage receives `content` as `predecessor_content` in
   `context.payload` (`methodology_driver.py:564`), which the runtime's default
   assembler renders into the next prompt (`assembly.py:236-252`). The chain
   therefore propagates the seed, not the work.

The model's proposal **is** durable: an admitted `EVIDENCE_TRANSITION` writes
`EVIDENCE_TRANSITION_PROPOSED` with `evidence_artifact_ref` in its payload
(`gateway.py:1515-1530`), and the admission audit carries the intent's
`justification` (the proposal rationale) in `IntentApplied`
(`gateway.py:4943-4994`). The durable facts exist; the driver simply does not
read them.

### 1.3 What the substrate permits today

`NODE_CONTENT_KEYS` (`substrate.py:224-228`) already allows `external_ref`,
`admitted_refs`, `cited_refs`, `summary`, `label`, `assertion`, `question`,
`question_ref`, `subject_ref` and `predecessors`. The rules that constrain A:

- a referenced kind (`HYPOTHESIS`, `PREDICTION`, `EVIDENCE`, `CLAIM`) **must**
  carry a non-empty `external_ref` with its own namespace
  (`_kind_refusal`, `:838-889`; `REF_NAMESPACES`, `:159-164`);
- a locally-defined kind (`QUESTION`, `EXPERIMENT`, `OBSERVATION`, `CRITIQUE`,
  `CONCLUSION`) must **not** carry a non-empty `external_ref`; it carries its
  content inline (`:844-864`);
- a node may not admit its own `external_ref` as support (`_refs_refusal`,
  `:905-983`);
- a `CLAIM` needs an admitted `evidence:` ref (`_support_refusal`,
  `:1052-1092`);
- a `CRITIQUE`'s `subject_ref` and a `CONCLUSION`'s `question_ref` must
  dereference to recorded nodes / the lineage.

These rules are the contract. The design does not relax any of them.

## 2. A / B / C, costed

### 2.1 A — the proposal supplies the content

For the **evidence position** this is exactly right: the model already has to
produce an `EVIDENCE_TRANSITION` with `payload.evidence_artifact_ref`; the
gateway already checks that ref with `ArtifactRepository.in_project`
(`gateway.py:1447-1452`); the driver can use the admitted proposal. The
proposal is the agent's actual choice, not a reconstruction.

The limits are structural, not stylistic:

| Position | Can the model name a valid ref? | Why |
| --- | --- | --- |
| `HYPOTHESIS` | no | no LLM-proposable kind; no `hypothesis:` artifact producer in the tree |
| `PREDICTION` | no | same, `prediction:` |
| `EVIDENCE` | **yes** | `EVIDENCE_TRANSITION` is proposable by researcher/verifier and the gateway checks the artifact row |
| `CLAIM` | no | no claim intent; no claim artifact producer (claims.py is a designed, unwired substrate) |

The code evidence: `IntentKind.llm_proposable()` (`core/intents.py:124-133`)
contains no hypothesis/prediction/claim kind; the profiles
(`agents/runtime/profiles/*.yaml`) grant only the declared kinds; and no
`artifact_type` `hypothesis`/`prediction`/`claim` exists. The substrate's
`REF_NAMESPACES` is a citation convention over refs the caller admits, not a
producer.

**Cost of the scoped A:** one pure content builder shared by the two drivers,
one seed-refusal rule, one test-migration of the methodology/wiring fixtures,
and the phase-2 falsifier tests. No new table, event, transaction, port or
authority.

**Cost of full A:** a new artifact producer + proposable intent for each of
hypothesis/prediction/claim (or a new internal-only writer), which is a
different gate. Relaxing `_kind_refusal` to allow inline cited-kind content
would make a "citation" no longer cite anything and would break the chain's
purpose. Neither is in this slice.

### 2.2 B — the methodology resolves refs from the project

`_default_content` would prefer the newest artifact of the right type over
`inputs.external_refs`. Cost:

- a **resolver** the driver does not have: the OPS-18 project-index view is
  bounded to 40 entries, is a prompt view rather than a resolver, and its
  truncation can omit the very artifact; otherwise a dedicated artifact read
  port (or a repository import, which the import discipline forbids);
- "right type" exists only for `source_payload`/evidence; there is no
  hypothesis/prediction/claim artifact to pick, so B fixes at most the evidence
  position — the same position A fixes;
- it **decides for the agent** which artifact is the evidence; the charter's
  point is that this is the agent's judgment and the validator's check;
- "newest admitted" is undefined: artifact rows have no admission state, and
  several fetches can be equally citable;
- it would silently change the chain when another artifact is written, which
  is not a function of the model's work.

**Verdict: rejected.** It is a weaker authority than A and no more complete.

### 2.3 C — keep the operator's refs authoritative

The status quo. It preserves every current test and the synthetic full-chain
fixtures, and it guarantees the agent's fetched artifact never reaches the
chain. Run 13 is the measurement of that guarantee. **Verdict: rejected.**

### 2.4 Rejected alternatives

| Alternative | Cost | Verdict |
| --- | --- | --- |
| Add `PROPOSE_HYPOTHESIS`/`PROPOSE_CLAIM` intents + artifact producers | new intent kinds, validators, tables/artifacts, proposable_kinds and census change | out of scope; a later gate, and the honest way to complete full A |
| Relax `_kind_refusal` so a referenced kind may carry inline content | breaks "a cited kind cites"; breaks the chain's citation semantics | rejected; violates invariant 2 |
| Let the driver pick the newest artifact (B) | decides for the agent; new read port; still no H/P/C | rejected |
| Have the model's rationale be the node `summary` | model text would re-enter the next prompt through `predecessor_content` | rejected as content; recorded as `rationale` instead (see §3.3) |
| Keep the seed evidence ref as a fallback | the fake ref pre-empts the real one exactly as in run 13 | rejected |

## 3. The chosen shape — fields, selection, rationale

### 3.1 Per-position content

The driver builds the structural content first (the existing
`_default_content`) and then merges the **agent facts** below. No reference
field is taken from `stage_content` or from the model's free text.

| Stage | Content after OPS-5D | Source |
| --- | --- | --- |
| `QUESTION` | `question` | operator question (unchanged) |
| `HYPOTHESIS` | `external_ref` | `inputs.external_refs["HYPOTHESIS"]` — prior-art seed, labelled |
| `PREDICTION` | `external_ref` | `inputs.external_refs["PREDICTION"]` — prior-art seed, labelled |
| `EXPERIMENT` | `predecessors` only | structural |
| `OBSERVATION` | `cited_refs = (evidence_ref,)` when the ref was admitted by that stage | the admitted `EVIDENCE_TRANSITION` (mention, not support) |
| `EVIDENCE` | `external_ref = evidence_ref` | the admitted `EVIDENCE_TRANSITION` — **the fix** |
| `CLAIM` | `external_ref = inputs.external_refs["CLAIM"]`; `admitted_refs = (evidence_ref,)` | prior-art claim identity + the recorded `EVIDENCE` ref |
| `CRITIQUE` | `subject_ref = predecessor_id` | structural |
| `CONCLUSION` | `question_ref = question_id` | structural |
| every non-root | `predecessors = (predecessor_id,)` | structural, never model-supplied |

`summary`, `label` and `assertion` are **not** populated from the model in this
slice: they are free text or a closed assertion vocabulary with no source in
the admitted proposal, and `summary`/`label` would be rendered into the next
stage's prompt through `predecessor_content`. The substrate keeps the keys; the
driver does not use them.

### 3.2 Which proposal supplies the evidence ref

A pure selector over the run's `ProposalSet`:

- scan the proposals of the `OBSERVATION` and `EVIDENCE` stage runs, in run
  order;
- keep only proposals of kind `EVIDENCE_TRANSITION` with
  `proposal.was_admitted()` (`ADMITTED` or `DUPLICATE`) and a payload
  `evidence_artifact_ref` starting `evidence:`; the gateway already enforced
  the prefix and the artifact row, so this is a shape guard, not a second
  validation;
- the **latest** such ref (by tick, then batch position) is the run's
  `evidence_ref`;
- no proposal, no admitted ref → no `evidence_ref`; the no-ref rule applies
  (§5).

The selector is limited to `OBSERVATION`/`EVIDENCE` because those are the
stages that record observation/evidence. A fetch or transition proposed in an
earlier stage is durable but is not used as the chain's evidence ref; the model
can re-propose after the experiment. This is a semantic rule of the driver, not
a new validator.

The selector reads the stage run's **own** proposal tuple. A delegated child's
proposal lives in the child run's tuple and is not traversed in this slice
(`DelegationRecord` carries the child's intent id/digest, not its payload); a
stage that sources evidence through a delegation has no ref at the evidence
position and stops unless its own run re-proposes the transition. A
delegation-aware selector is a later option, not part of this gate.

The `CLAIM` node uses the **recorded** `EVIDENCE` node's `external_ref`, not
the selector directly and never `inputs.external_refs["EVIDENCE"]`; if there
is no recorded evidence node, the chain has not reached the claim (provenance)
or the claim refuses `UNSUPPORTED_CLAIM`.

### 3.3 The node rationale

The node's `rationale` is the first admitted proposal's `rationale` in the
stage's run, in run order. If the stage has no admitted proposal but its node
uses a ref admitted in an earlier stage (the `EVIDENCE` node when the
transition was admitted during `OBSERVATION`), the rationale of that supplying
proposal is used; otherwise the existing template
(`stage <kind> via profile <profile>`).

Why `rationale` and not `summary`:

- the rationale is a node field, not content, and it does not re-enter the
  next prompt: it is not part of `content`, so it does not enter
  `content_cache` and therefore does not enter the next stage's
  `predecessor_content`;
- it is already durable for an admitted proposal: the runtime sets
  `Intent.justification = proposal.rationale`, and `IntentApplied` carries it
  (`gateway.py:4943-4994`);
- it records the agent's rationale without turning the next prompt into a
  model-to-model relay.

The rationale is model text and is recorded as such (the node is derived
working state, and the Vault/project index does not read node rationale). It is
not a claim of validity.

### 3.4 What stays advisory

The `EVIDENCE_TRANSITION` payload's `from_state`, `to_state`,
`ratification_ref`, the proposal `capability_refs`, `artifact_ref`,
`admission_detail` and every rejected proposal remain advisory/durable
provenance; they are not copied into node content. The proposal's
`admitted_entity_id` (the transition id) is durable and may be reported, but it
is not a node field. The model's tools' arguments, fetched bytes, titles and
URLs never enter the node content.

## 4. Validation — the same `EVIDENCE_REF` check, not a second one

The only artifact-row validation is the gateway's:

```
_validate_evidence_transition -> evidence_artifact_ref prefix
    -> ArtifactRepository(conn).in_project(artifact_id, project_id)
    -> EVIDENCE_REF rejection (gateway.py:1447-1452)
```

The driver:

1. reads only `Proposal.was_admitted()` and the admitted payload;
2. checks only the `evidence:` prefix shape (the gateway already required it);
3. calls `store.admit_ref(ref, project_id)` for the admitted ref — an
   **in-memory registration** of a fact the gateway established, exactly the
   act the driver already uses for the seed; it is not an artifact read and not
   a second check;
4. lets `write_node` run its existing `resolve_ref` against the store's
   registry (the substrate's own content rule).

Consequences:

- a proposal citing a nonexistent artifact is **refused `EVIDENCE_REF` by the
  gateway**; it is not admitted, so the driver never registers or uses it;
- a foreign-project artifact is refused by `in_project`; the ref never enters
  the store for this project;
- a retracted ref is admitted by the gateway (the artifact row exists) but
  refused by `write_node` as `RETRACTED_CITATION` (N9); the chain stops, which
  is the existing rule, not a second validation path;
- the driver imports no repository and reads no table. The `in_project` check
  happens exactly once, at admission.

## 5. When the proposal names no ref (§4.3)

**Pick: the stage is not recorded, and the run stops at that stage.** No
fallback to the operator's evidence ref; no empty content for a cited kind.

- `EVIDENCE`: build the node with `external_ref = ""` (or omit it); the
  substrate's own `_kind_refusal` returns
  `MALFORMED_PAYLOAD: a EVIDENCE node cites an existing artifact: it needs a
  non-empty 'external_ref'`. The driver returns that refusal with the stage,
  and no node is written. The message is the existing one; no new code is
  invented.
- `CLAIM`: no recorded evidence ref → the content's `admitted_refs` is empty;
  the substrate's `_support_refusal` returns `UNSUPPORTED_CLAIM`. If the claim
  has no prior-art `external_ref`, `MALFORMED_PAYLOAD` fires first. Either way
  the claim is not recorded.
- `HYPOTHESIS`/`PREDICTION`: the seed's prior-art ref is still required; if it
  is absent, `MALFORMED_PAYLOAD` fires. This is the seed's contract, not the
  model's.
- Local kinds (`QUESTION`, `EXPERIMENT`, `OBSERVATION`, `CRITIQUE`,
  `CONCLUSION`): the structural content is complete without a proposal; they
  record as today.

Why not fall back to the operator's ref: that is exactly the pre-emption run 13
measured. Why not record empty content: the substrate forbids it for a cited
kind, and the content rule is not relaxed. Why fail rather than skip the node
and continue: skipping a cited kind would let the chain reach a later stage
without the position it claims, and the transition map would refuse the next
node anyway; stopping names the first stage that cannot be truthfully recorded.

The stage run's `SUCCEEDED` state is necessary, not sufficient: a run can
succeed with refused proposals (run 13 did), so the content gate is separate
and decisive.

## 6. `_default_content` and the seed (§4.4, §4.6)

### 6.1 `_default_content` survives as the structural base

It remains the one content builder for every stage: question, prior-art refs,
predecessor, critique subject and conclusion question. OPS-5D changes only the
agent-derived positions:

- `EVIDENCE.external_ref` is never read from `inputs.external_refs["EVIDENCE"]`;
- `OBSERVATION.cited_refs` and `CLAIM.admitted_refs` come from the recorded
  evidence ref;
- the node rationale comes from the admitted proposal (or the template).

A `stage_content` override may shape non-ref content for tests (and, for the
prior-art positions, the same refs the seed may supply). The driver guards the
**evidence position**: an `evidence:` ref in `stage_content["EVIDENCE"]
["external_ref"]`, or in the `cited_refs`/`admitted_refs` keys of
`OBSERVATION`/`CLAIM`, is refused `MALFORMED_PAYLOAD` before the node is built,
so the override cannot pre-empt the agent. A ref smuggled into a **local**
kind's `external_ref` is left to the substrate's existing shape rule (the
`test_a_local_kind_with_a_stage_content_external_ref_is_refused` behaviour is
unchanged: the refusal still comes from the substrate).

### 6.2 The seed

| Seed entry | After OPS-5D |
| --- | --- |
| `question` | stays; the operator's question is the root |
| `external_refs["EVIDENCE"]` | **refused** (`MALFORMED_PAYLOAD`, detail names the evidence position) |
| any `admission_refs` entry starting `evidence:` | **refused** for the same reason |
| a `retracted_refs` entry starting `evidence:` | **allowed**: it is the N9 projection, not a citation or resolver entry; it can only remove support |
| `external_refs["HYPOTHESIS"/"PREDICTION"/"CLAIM"]` | stays, as **prior-art citations**; the three positions have no model-producible artifact producer in this build |
| `stage_content` evidence refs | the evidence position's `external_ref`/`cited_refs`/`admitted_refs` may not be supplied by `stage_content` at all (the agent supplies them); prior-art refs and non-ref overrides follow the existing rules |

The live handler (`_inputs_from_spec`) and both drivers will enforce the
refusal before any stage. The OPS-7 task-input envelope then no longer shows a
fake evidence id to the model; it shows the prior-art refs and the question.
The model gets the real evidence id from its own fetch feedback
(`evidence/<artifact_id>`, OPS-5C) and from the `OBSERVATION` node's cited ref
when the transition was admitted there. The OPS-18 project index also lists
`source_payload:<artifact_id>` entries, so a later stage can name the artifact
it saw; the driver's selection still comes from the admitted transition, not
from the index.

**What replaces the operator's evidence ref:** the admitted
`EVIDENCE_TRANSITION` ref. The operator's job at the evidence position ends at
"fetch and cite"; the validator checks the artifact row.

**The one-tick path.** The shipped methodology allows one tick per stage, and
proposals are admitted before the sibling tool batch, so a fetch and its
citation cannot share a tick. The fetch can happen in an earlier stage (for
example HYPOTHESIS); the artifact then appears in the OPS-18 project index read
by the citing stage (OBSERVATION/EVIDENCE), which names `evidence:<artifact_id>`.
The design adds no multi-tick stage and no driver-picked artifact. A delegated
child's proposal lives in the child's tuple and is not traversed (Q6).

**What replaces the prior-art refs:** nothing in this slice. They are not
evidence and they do not compete with the agent's evidence; they are the
citations the hypothesis/prediction/claim positions have always carried. If the
Director wants them gone, the honest consequence is that the methodology
cannot record `HYPOTHESIS` (no producer), and the chain stops there. That is a
separate artifact-producer gate, not a seed workaround. The design labels the
prior-art refs and refuses an `EVIDENCE` ref, which is the pre-emption the
charter names.

## 7. Replay (§4.5)

The node content is a pure function of:

- the parsed methodology document;
- the task inputs (question, prior-art refs) — durable in the task spec;
- the admitted proposals selected by the rule in §3.2 and their rationales;
- the run's stage identity (`producing_task_id = {task}:{stage}`).

Durable facts that reproduce it:

| Fact | Where |
| --- | --- |
| the admitted evidence ref | `EVIDENCE_TRANSITION_PROPOSED` payload `evidence_artifact_ref` (`gateway.py:1515-1530`) |
| the admitted proposal's rationale | `IntentApplied` audit payload `justification` (`gateway.py:4943-4994`); the intent's justification is the proposal rationale (`run.py:994-996`) |
| the task inputs | the task row's `spec["inputs"]` (the handler's source, `task_handlers/__init__.py:415-428`) |
| the stage identity | `{task_id}:{stage}` (projection, `methodology_driver.py:157-165`) |

Two replay shapes are therefore available, and both must reproduce the same
`node_id`/content:

1. **Re-drive the transcript.** The same scripted/recorded model replies and
   the same inputs produce the same proposals; the same admissions select the
   same ref and rationale; the node id re-derives by content.
2. **Re-derive from the journal.** Read the admitted transition's ref and the
   admission's justification, rebuild the content with the same pure builder,
   and compare. The refused synthetic-ref proposal is not content, so replaying
   it changes nothing.

The live store is in-memory and is not the replay source; the durable events
are. The claim is **content determinism**, not scientific validity: a replay
proves the same bytes/content, never that the evidence supports the claim. The
model transcript itself is not a durable transcript; the admitted intent and
its audit are the durable facts the node content depends on.

## 8. What must not change

| Invariant | How the design upholds it |
| --- | --- |
| Census 124 / 28 (19/5/4) / 1 / 15 / 0 | no new table, transaction, acquisition owner or SQL; the store is in-memory; `admit_ref` already exists |
| Substrate content rules | unchanged: no new kinds, keys, refusal codes; a cited kind still requires a namespace-correct resolving ref; a claim still needs an admitted `evidence:` ref; no rule relaxed |
| One mutation path | the model's evidence ref is admitted by the existing gateway; the driver only writes an in-memory node; no second durable writer |
| Drain-only / B4 / governed docs | composition is not entered by drain-only; B4 stays 24; no governed doc edited |
| `proposable_kinds` and tool grants | unchanged; the verifier already may propose `EVIDENCE_TRANSITION`; no new capability |
| LOOP baseline | no tool calls in the baseline; the runtime is untouched |
| Bounded payloads | the evidence ref and rationale are within the existing intent/event bounds; no new unbounded payload |

## 9. Falsifiers → phase-2 tests

| Falsifier | Test shape | Assertion |
| --- | --- | --- |
| A fetch becomes the `EVIDENCE` node's `external_ref` | scripted run over the real chain: fetch (OPS-5C), then propose `EVIDENCE_TRANSITION` citing `evidence:<fetched id>`; the real gateway admits it; the driver records the node | `content["external_ref"] == "evidence:<id>"`; the node is not the seed's; `EVIDENCE_REF` accepts the same artifact; the record is the fetched artifact |
| A nonexistent ref still refuses; no second path | propose `evidence:ghost`; the real gateway refuses `EVIDENCE_REF`; no admitted ref | the run's refusal carries `EVIDENCE_REF`; the driver registers nothing; no `EVIDENCE` node; the stage stop is the substrate's `MALFORMED_PAYLOAD` |
| No ref behaves as §5 | a stage run that proposes no evidence transition and a seed with no evidence ref | no node; `MALFORMED_PAYLOAD` (or `UNSUPPORTED_CLAIM` for a claim), pinned; no fallback |
| Replay reproduces content | two runs with the same scripted replies; and a journal-derived rebuild from `EVIDENCE_TRANSITION_PROPOSED` + `IntentApplied` | equal `node_id` and content in all three |
| Seed evidence ref is refused | task inputs carrying `evidence:...` in `external_refs`/`admission_refs`/`stage_content` | `MALFORMED_PAYLOAD` before any stage; no node |
| Baseline / census / B4 | chartered gates | unchanged |

The phase-2 test file is `tests/test_ops5d_proposal_content.py` (new). It does
not exist in phase 1.

**Fixture migration is part of phase 2, not a rule weakening.** The current
`test_wiring_w3` / `swap_test` fixtures seed a synthetic `evidence:` ref and
expect a complete chain. They will use a scripted model that proposes an
`EVIDENCE_TRANSITION` whose ref the fake applier admits (or the real gateway
with a real artifact row). The direct substrate tests in
`test_methodology_plane.py` keep their synthetic refs: they exercise the
substrate store, not the methodology driver's seed rule.

## 10. Phase-1 gates

This is a docs-only design gate. The phase-1 gates are: the targeted OPS-5D
surface (the real methodology/wiring tests, OPS-5C/5B, loop baseline, B4,
census), the full suite under the heavy-gate lock, the suite-count stamp, the
census, ruff and pyright. The raw results are in the phase-1 report; the suite
count is expected to stay **5270** because this phase adds no test.

Charter note: `test_methodology_workflows` does not exist in the tree; the real
coverage is `tests/test_methodology_plane.py` (the plane/driver) and
`tests/test_wiring_w3.py` (the live driver). Both are run in its place.

## 11. What I could not decide from the tree

1. **Whether hypothesis/prediction/claim artifact producers are planned.** The
   tree has no producer and no artifact type for them; the seed's refs are
   fixture strings. If no producer is planned, full A cannot ever be truthful
   and the three positions remain prior-art citations by design. If producers
   are planned, their gate is the honest follow-on to full A.
2. **Whether `stage_content` is a public contract or a test seam.** The design
   treats it as a test seam and guards only the evidence position's refs. If a
   caller relies on it to supply an evidence ref, that use is refused; if a
   caller relies on it for prior-art or non-ref content, it still works.
3. **Whether the node `rationale` should carry model text at all.** The design
   says yes, because it is recorded and does not re-enter the next prompt. A
   stricter posture would record only the template and keep the model rationale
   in the proposal/event alone.
4. **Whether the `OBSERVATION` node should carry the evidence ref as a
   `cited_refs` mention before the `EVIDENCE` node.** The design recommends it
   (the verifier can then see the artifact it is asked to cite); the run-level
   selector does not depend on it. The Director may prefer no ref in an earlier
   node.
5. **Whether the `CLAIM`'s own `external_ref` may remain the operator's
   prior-art claim citation.** The tree has no claim producer; the design keeps
   it, with the agent's evidence as `admitted_refs`. A stricter reading would
   make the claim stage unrecordable until a claim producer exists, stopping
   the chain at `CLAIM`.
6. **The exact stage scope of the evidence selector.** The design limits it to
   `OBSERVATION`/`EVIDENCE` so an evidence ref proposed before the experiment
   does not silently become the chain's evidence. If the Director wants any
   stage's admitted transition, the selector is a one-line widening; the
   semantics of "observation" would change with it.

## 12. Claim boundary

This note claims the run-13 measurement as given by the Director, the code
paths above, the substrate/gateway rules, and the field/validation/no-ref/
seed/replay decisions. It does **not** claim that the full chain becomes
truthful (the three prior-art positions remain citations), that a model
rationale is meaningful, that a replay is validity, or that the fetched source
supports any claim. It does not claim a UI, a new artifact producer, or a
change to `proposable_kinds`/grants. The evidence position is the one the
capability plane can make real today.

License: Apache-2.0 (LICENSE).
