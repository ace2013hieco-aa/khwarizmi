# OPS-5B — from proposals to citable evidence

| Item | Value |
| --- | --- |
| Task | OPS-5B: wire the capability plane and make a tool observation a citable artifact |
| Base | `main` at `1e9266c` (OPS-18 merged) |
| Branch | `slice/ops-5b-capabilities` |
| Phase | **1 — design gate. No code in this phase.** |
| Status | **PROPOSED (2026-10-25)** — D1–D6 decided; one supply ruling raised for the Director (§9.4) |

## 0. Verdict summary

1. **The artifact chain is broken at the result → artifact hop.** No live path writes an
   `artifacts` row when a tool returns bytes. The `source_fetch` executor returns
   `"artifact": payload.artifact.artifact_id` (`research/capability_supply.py:385-399`), and
   that value is `"art_" + sha256(raw_bytes)[:24]` — a transient carrier identity minted by the
   fetch driver (`tools/research_sources.py:465`, `tools/providers/paginate.py:1248-1249`).
   It is **not** a row in `artifacts.artifact_id`. `EVIDENCE_REF` reads that column through
   `ArtifactRepository.in_project` (`research/gateway.py:1448-1452`,
   `persistence/repositories.py:1029-1035`), so the returned value cannot satisfy it. The
   project's zero artifact count is the symptom; the model's invented `synthetic-sars11/e1`
   is what a model does when asked to cite a row nobody creates.
2. **Wiring the port is necessary and not sufficient.** `build_live_composition` passes
   `capabilities=None`, `grants=None`, `artifacts=None` and a model-only profile copy
   (`composition.py:516-533, 562, 576-580`; `task_handlers/__init__.py:320-328`). A port would
   execute `source_search` / `source_fetch`; their observations would still produce no row.
3. **The supply decision is the gate.** `source_fetch` will record the fetched bytes as a
   `source_payload` artifact through the existing `ArtifactStore.write` →
   `ArtifactRepository.record` path (IDR-008/013), with the composition's `project_id`, the
   content hash as the artifact id, and `task_id = NULL`. `source_search` writes no artifact;
   search is discovery, not evidence. `artifact_store` stays unsupplied: a model-callable
   writer would author bytes, and the plane refuses `mutating=True`
   (`tools/capabilities/invoke.py:558-565`).
4. **A row is not a citation until the model is told how to cite it.** Tool feedback carries
   `artifacts` handles but never the payload text (`agents/runtime/types.py:597-665`;
   `agents/runtime/assembly.py:295-339`). The tool will return two handles —
   `evidence/<artifact_id>` and `source_payload/<content_hash>` — and the contract must state
   the mapping. The project index lists the row as `<artifact_type>:<artifact_id>`
   (`research/project_index.py:44-47`), so a `source_payload` row appears as
   `source_payload:<id>` while `EVIDENCE_TRANSITION` requires `evidence:<id>`
   (`gateway.py:1437-1452`). The OPS-18 test masks this because its artifact type is literally
   `evidence` (`tests/test_ops18_project_index.py:511-516`); a `source_payload` row exposes it.
5. **One of six profiles gains real tool reach.** `researcher` declares exactly the two
   supplied capabilities. The other five account for **ten withheld declarations** (seven
   distinct ids) the registry cannot supply. They are withheld, named and journaled, not
   silently narrowed (§4.1). No shipped profile is mixed; the mixed rule is stated for future
   profiles.
6. **The three router gates are avoided, not weakened.** `_model_request` will stop using
   `ModelRequest.tools` as a native-tool advertisement (`tools=()`), and the capability ids,
   input schemas and item shape move into the output contract's `tool_calls` field note,
   generated from the registry (OPS-5 §2.1/F3; OPS-17 left the item schema unstated,
   `docs/OPS-17-NOTES.md:174-187`). The router guards still fire for any caller that sets
   `tools`; the provider still refuses native `tool_use` blocks.
7. **M2 becomes a number.** One `RecordingCapabilityPort` per composed run, between the
   invoker and every stage runtime; the vector renders
   `M2(calls=N,repeat=X.XXX)`. A zero-call run reports a measured `0.000`, not `n/a`; `n/a`
   survives only where no port exists.
8. **The artifact write is the ruling.** It is a new call site of an existing writer — the
   same `ArtifactStore` the task-side source path already uses — and it adds no table, no
   transaction-control call, no acquisition owner and no event beyond the one
   `CapabilityPlaneComposed` row. If the Director reads this as a new write path under §4.1,
   the chain cannot be built in this slice without a plane change; §9.4 states that conflict
   rather than hiding it.

The one sentence to read twice: **a working capability port without an artifact write still
admits zero evidence.** The port supplies observation; the artifact write supplies citation.
They are separate hops, and only the second one exists nowhere today.

## 1. The tree at this base

### 1.1 The live path after OPS-18

```
hermes run (cli.py:598-608)
  build_live_composition (composition.py:536-581)
    load_profiles() → _model_only_profiles()        # every allows_tool_calls := False
    build_model_binding(...)                        # no tool_allowlist
    RecordingModelPort(binding)                     # M1
    LiveVector(supervisor, profiles, recorder)      # M2 hard-coded n/a
    build_controller(..., project_index=Reader)     # OPS-18 read port
      → build_methodology_handler(model, profiles, supervisor, on_stage,
                                  project_index)    # grants/capabilities/artifacts all None
        → RuntimeWiring(capabilities=None, grants=None, artifacts=None)
          → AgentRuntime(capabilities=None, grants={}, artifacts=None)
```

`build_methodology_handler` already accepts `grants`, `capabilities` and `artifacts`
(`research/task_handlers/__init__.py:249-262`) and threads them into `RuntimeWiring`
(`:320-328`). `RuntimeWiring` and `AgentRuntime` already accept them
(`agents/runtime/wiring.py:291-320`; `agents/runtime/run.py:445-478`). The seam is shaped;
nothing is plugged in. `build_controller` does not forward any of the three
(`composition.py:459-499`), and the live composition does not build them.

`_model_only_profiles`'s stated reason — "The cloud provider refuses a reply that carries a
tool call" (`composition.py:516-526`) — is false for the JSON path. The provider refuses
**native** tool-use blocks; the runtime's tool path is a JSON field, which it does not refuse
(OPS-5 §1.2/F2). The narrowing is the only reason `ModelRequest.tools` is empty today, and
therefore the only reason the two router gates (`router.py:1544-1548`, `:1678-1679`) and the
provider constructor guard (`tools/models/cloud.py:636-639`) do not fire.

### 1.2 The measured profile table

Loaded from `agents/runtime/profiles/*.yaml` at this base:

| Profile | `agent_profile` | `allows_tool_calls` | `structured_fields` | declared `tools` | supplied? | after 5B |
| --- | --- | --- | --- | --- | --- | --- |
| `critic` | `ADVERSARY` | true | `proposals, tool_calls` | `evidence_inspect, contradiction_scan` | 0/2 | tools `()`, no grant; withheld 2 |
| `experimenter` | `IMPLEMENTER` | true | `proposals, tool_calls, delegations` | `experiment_execute, artifact_store` | 0/2 | tools `()`, no grant; withheld 2 |
| `planner` | `DIRECTOR` | true | `proposals, delegations` | `graph_read, artifact_store` | 0/2 | tools `()`, no grant; withheld 2 |
| `researcher` | `RESEARCHER` | true | `proposals, tool_calls` | `source_search, source_fetch` | **2/2** | unchanged; granted; observes |
| `synthesizer` | `DIRECTOR` | true | `proposals, delegations` | `artifact_store, provenance_read` | 0/2 | tools `()`, no grant; withheld 2 |
| `verifier` | `ADVERSARY` | false | `proposals, delegations` | `evidence_inspect, statistic_check` | 0/2 | tools `()`, no grant; withheld 2 |

Ten withheld declarations across five profiles. `researcher` is the only profile whose
contract asks for `tool_calls` **and** whose entire declared tool set is supplied. `critic`
asks for `tool_calls` but declares no supplied tool; its calls will be the existing benign
`ROLE` skip (§4.3), not a fatal plane refusal.

### 1.3 Who writes `artifacts` today

| Writer | Artifact types | Bindings | Reachable from a live run? |
| --- | --- | --- | --- |
| `SourceOutcomeRepository.record` → `_commit` → `ArtifactStore.write` (`persistence/source_outcomes.py:370-411, 1040-1057`) | `source_payload` (bytes), `source_result`, `source_search`, `source_fetch_outcome` | `BEGIN IMMEDIATE`; requires a **RUNNING** `SOURCE_SEARCH` / `SOURCE_FETCH` task (`:376-411`, `_validate_task_binding`) | **No.** The live composition registers only the methodology handler; `build_live_fetch_wiring` builds the source handlers (`research/live_fetch.py:436-460`) but nothing registers them. |
| Retraction decision (`gateway.py:1772-1816`) | `ResearchDecision` | `apply_intent` transaction | Only after a ratified retraction; not a producer. |
| Failure classification / corpus / claims / program obligations | their own types | their own certified paths | Task-side, not capability-side. |
| Provider interaction sink (`persistence/provider_interactions.py:140-200`) | `provider_response` only when a body is retained | plain INSERT on the caller's autocommit connection | Yes, but OPS-5A's capability path passes `retain_body=False` (`capability_supply.py:287-294`), so a fetch writes **no** `provider_response` row. |

The capability path's only durable writes today are `provider_interactions` rows: identity,
redacted request metadata and a response digest, never the body (OPS-5A R1). A fetch result
becomes a `TOOL_OBSERVED` trace event, a `ToolFeedback` record and nothing citable.

### 1.4 `EVIDENCE_REF`: what it reads and what would satisfy it

`_validate_evidence_transition` (`gateway.py:1421-1452`):

1. `payload.evidence_artifact_ref` must be a string starting `evidence:` (`:1437-1443`);
2. the suffix is treated as an **artifact id** (`:1444-1447`);
3. `ArtifactRepository(conn).in_project(artifact_id, intent.project_id)` must be true
   (`:1448-1452`), which is exactly:

```sql
SELECT 1 FROM artifacts WHERE artifact_id = ? AND project_id = ?
```

(`repositories.py:1029-1035`). The check is **typeless**: any artifact row in the project
satisfies it, including a `source_payload`. It does not accept a content hash in place of the
artifact id, and it does not accept the `source_payload:<hash>` typed form. The only way to
satisfy it is a row whose `artifact_id` and `project_id` are real.

The table is `artifacts` (`persistence/migrations.py:190-204`): `artifact_id` primary key,
`project_id` FK, `task_id` FK **nullable**, `artifact_type` NOT NULL, `content_hash` UNIQUE,
`size_bytes`, `storage_path`, `producer`, `metadata_json`, `created_at`. The content hash is
globally unique; ownership is either `project_id` or edge-carried (§9.5).

### 1.5 What the model sees after a successful tool call

`_one_tool_call` emits `TOOL_OBSERVED` with `list(result.artifacts)` (`run.py:1348-1351`) and
retains a `ToolFeedback` carrying the artifact handles, the payload's byte size and digest,
and the invocation ref (`run.py:1354-1357`; `types.py:597-665`). The payload text is
deliberately **not** in the prompt: `_tool_feedback` stores only size/digest
(`run.py:365-386`), and `feedback_envelopes` renders the record's fields, never
`payload.text` (`assembly.py:295-339`). On success, `detail` is not passed at all
(`run.py:1354-1356`); only failures carry it.

Consequences the charter did not ask about but the chain depends on:

- **`source_fetch`**: the model chose the URL and gets artifact handles; handles are enough
  to cite. It does not see the fetched text, which is the LOOP-2 posture.
- **`source_search`**: the model gets `artifacts: []`, a byte count and a digest. It cannot
  see the rows, the titles or the URLs, and it chose its whole tool batch before any result
  existed. **Search can be wired and still not actionable in a live run.** A model can still
  fetch a URL it already knows; that is the path the falsifier proves. Making search useful
  needs either a bounded structural summary in the feedback detail or a read capability
  (OPS-5C); this note does not smuggle one in (§13 R4).
- **`NO_FULL_TEXT`**: a successful observation with no artifact. The model sees "OK, no
  handles" and cannot tell it from an empty search without the detail. The note recommends
  carrying the bounded success detail (§13 R3); that is a small runtime change, not a new
  authority.

## 2. The supply chain traced hop by hop

The charter's question: **when a tool returns content, what makes it a citable artifact
row?** Trace:

| # | Hop | Site | What exists after the hop |
| --- | --- | --- | --- |
| 1 | Model reply carries a JSON `tool_calls` array | contract from `structured_fields` (`run.py:314-362`); `_tick` (`:693-758`) | a structured mapping; the item schema and legal ids are **not** in the contract today (OPS-17 inventory; §3.5) |
| 2 | Runtime filters and authorizes the batch | `_tool_phase` (`:1197-1239`); `_one_tool_call` (`:1241-1358`) | `spec.tools` check; port-presence check; a missing port is a benign `ROLE` skip (`:1287-1299`) |
| 3 | Runtime builds `InvokeRequest` | `:1305-1315` | a derived idempotency key (`types.py:229-237`); the grant for `spec.agent_profile` |
| 4 | Plane authority, schema, idempotency, sandbox, hazard | `invoke.py:407-577`, `:762-808` | an authorized call, or a typed refusal; no tool has run yet |
| 5 | Executor runs | `capability_supply.py:297-440` | a provider walk/fetch; egress journal rows; **no artifact row** |
| 6 | Executor returns `ToolResult` | `types.py:410-420`; fetch branch `capability_supply.py:385-399` | `payload` (full text), `artifacts=()`, notes; the `art_<hash24>` transient id is embedded in the payload text |
| 7 | Plane wraps the observation | `invoke.py:835-940` | an `Observation` with `UntrustedContent`, the artifacts **handles** it was given (none), the envelope, size and digest; **no persistence** of payload or handles |
| 8 | Runtime records the observation | `run.py:1348-1357`; `_tool_feedback`; `feedback_envelopes` | `TOOL_OBSERVED` event + `ToolFeedback` (handles, size, digest); no `artifacts` row; no payload text in the prompt |
| 9 | Anything that writes an `artifacts` row | §1.3 | the task-side source path and gateway paths; **the capability path reaches none** |
| 10 | `EVIDENCE_REF` reads | `gateway.py:1448-1452`; `repositories.py:1029-1035` | `SELECT 1 FROM artifacts WHERE artifact_id = ? AND project_id = ?` — fails, because hop 6 never inserted |

**Answer: nothing makes a tool result a citable artifact row today. The chain breaks at hops
6–7, between the executor's return value and durable state.** A tool returns bytes; the plane
mints an observation digest; the runtime retains a size and a digest; the journal records the
egress metadata. None of those is a row the gateway can dereference. The `art_<hash24>` value
is the most dangerous artifact of the gap: it *looks* citable and is content-derived, and
nothing in the path rejects it because it is only payload text — but it is a carrier id, not
an `artifacts.artifact_id`, and citing it produces the same `EVIDENCE_REF` refusal as citing
an invented id.

Second break, specific to discovery: hop 8 withholds the observation payload and, on success,
drops even the tool notes. `source_search` therefore produces an observation the model cannot
read. This note keeps the LOOP-2 text-withholding posture and does not inline the payload;
it records the consequence and the two possible follow-ons (§13 R4).

## 3. D1 — what the composition wires

### 3.1 The supply, the registry and the invoker

`capability_supply.build_research_egress_supply` already returns the coherent bundle:
declarations, capabilities, one tool set, a `CapabilityRegistry` whose allowlist equals its
declarations, and implementations keyed by tool id (`capability_supply.py:454-523`). The
composition will build it once per live run:

```
artifact_store = ArtifactStore(cfg.artifacts.artifact_root,
                               ArtifactRepository(conn, clock), clock)
supply = build_research_egress_supply(
    conn=conn, store=artifact_store, clock=clock,
    project_id=project_id, sandbox_policy=cfg.sandbox,
    autonomy_caps=cfg.autonomy_caps)   # P-AUTO-4 narrow-only rate knobs
invoker = CapabilityInvoker(
    registry=supply.registry,
    implementations=supply.implementations,
    clock=supply.machinery.clock,          # one clock with the driver (OPS-5A debt 1)
    ledger=InMemoryIdempotencyLedger(),
    sandbox_enabled=False)
recorder = RecordingCapabilityPort(invoker)   # D3
```

- No capability-level rate limiter: the envelope records `rate_decision="ungated"`
  (`invoke.py:798-808`) while the provider machinery's `ProviderRateLimiter` still gates the
  dial. That is stated, not hidden (§8).
- The supply builder currently accepts only `sandbox_policy`; the composition must also thread
  `cfg.autonomy_caps` into `build_live_fetch_wiring` (the builder needs a new
  `autonomy_caps` argument). Without it the capability path falls back to `sandbox_policy`,
  which carries no rate fields, and operator tightening is silently ignored — the same
  FIX-C1 class of bug the task-side path already fixed (`live_fetch.py:378-396, 450-455`).
  This is a composition correction, not a new authority.
- No `hazard_specs` on the invoker: the two tools declare none; provider hazard specs apply
  inside the walk/fetch driver. A declared-but-unregistered hazard spec would fail closed
  (`invoke.py:762-777`); none is declared.
- No `secrets=` values: the supply never receives a model key, and passing plaintext keys into
  the plane would be the leak this project avoids. The executor's inputs are provider ids,
  query terms and URLs. With an empty `secrets` tuple the observation substring scan is inert
  (`invoke.py:989-992`); the protection is that no key can enter the tool arguments or the
  observation, not that a scan runs. The event validator's secret scan applies to the
  withheld event payload (`event_validation.py:87-136`).
- The clock is the machinery's adapted clock. OPS-5A's first debt — a custom clock makes calls
  expire instantly because the driver compares against `time.monotonic` — is closed by using
  `supply.machinery.clock` for the invoker, not a second clock.

### 3.2 Grants, by `agent_profile`

A grant is the union of the **narrowed** `spec.tools` over every profile bound to the same
`agent_profile`, intersected with the supplied set; `tool_set_ids` is the one research-egress
set; `max_risk` is the maximum effective risk (both capabilities are MEDIUM). The key is
forced by the runtime (`run.py:1313`, `_grants.get(spec.agent_profile)`) and checked by the
invoker (`invoke.py:522-527`).

| `agent_profile` | Profiles | Supplied declared tools | Grant | Result |
| --- | --- | --- | --- | --- |
| `RESEARCHER` | `researcher` | `source_search, source_fetch` | yes, `set.research_egress`, MEDIUM | both calls reachable |
| `ADVERSARY` | `critic`, `verifier` | none | none | calls outside narrowed `tools` are `ROLE`-skipped |
| `DIRECTOR` | `planner`, `synthesizer` | none | none | same |
| `IMPLEMENTER` | `experimenter` | none | none | same |

The grant ids are code-derived (`grant.live.<agent_profile>`), never model-authored. A grant
opens no capability its profile's `spec.tools` does not contain: the runtime checks
`spec.tools` before the plane, and the plane re-checks the tool set and ceiling.

### 3.3 Withholding: one declaration at a time, named and journaled

Per the OPS-5 R3 ruling (`docs/idr/LIVE-CAPABILITY-PLANE.md:643-650`), a declaration the
registry cannot supply is **withheld, not refused at composition**:

- `(profile, agent_profile, capability_id)` is recorded once per declaration — ten pairs at
  this base (§1.2), not eight capability ids, because `artifact_store` and `evidence_inspect`
  are declared by more than one profile;
- the profile's `spec.tools` is narrowed to the supplied subset for the run (for a profile
  with none, `()`);
- one operator line enumerates the pairs (§6);
- one journal row records the supplied set, the withheld set and the granted
  `agent_profile`s (§3.4);
- a model that asks for a withheld id fails the existing `spec.tools` check (`run.py:1270-1274`)
  and lands as `ROLE`, recorded, with `TOOL_SKIPPED` feedback — the tick continues (R3's
  "the model may still ask for a withheld id").

A hard `CompositionError` on any unsupplied declaration would fail five of six profiles and
make live mode reachable only for a RESEARCHER-only workflow; it is rejected as the default
and remains one constant away (`UNSUPPLIED_TOOL_POLICY = "refuse"` in the OPS-5 note).

### 3.4 The withheld-set journal event

The charter allows exactly one new event kind beyond today's catalog. The note proposes:

- `EventType.CAPABILITY_PLANE_COMPOSED = "CapabilityPlaneComposed"` — the event that carries
  the withheld set (and the supplied/granted sets);
- written once per composed live run, in `build_live_composition`, after the grants and the
  withheld set are derived and **before** the first tick;
- payload (≤ 4 KiB, no secrets, no ids beyond capability/profile names):

```json
{"supplied": ["source_fetch", "source_search"],
 "granted": ["RESEARCHER"],
 "withheld": [{"profile": "critic", "agent_profile": "ADVERSARY",
               "capability_id": "evidence_inspect"}, "..."]}
```

- `correlation_id = "capability_plane:" + sha256(canonical payload)[:16]`; `caused_by =
  "composition"`; one row per composed run even when the same set repeats (the journal is
  append-only; the correlation makes the set queryable, not unique);
- the write goes through `EventRepository.append_transactional`
  (`repositories.py:876-935`) — an **existing** acquisition owner and an existing
  `BEGIN`/`COMMIT` site, so the certified census cannot move; the new call site adds no
  control-call literal;
- the catalog is derived from the enum (`event_validation.py:25-32`), so a new member is
  accepted without a second literal; the 4 KiB and secret validators run unchanged
  (`event_validation.py:139-151`);
- **failure is fail-closed**: a live run whose plane composition cannot be recorded refuses
  to compose, naming the project. An unrecorded capability plane is the same class of defect
  as an unjournaled egress. If the project row is absent, the run has nothing to do anyway.

**Placement and the lease.** The event is written at composition, **before** the controller
acquires its scheduler lease. It is an append-only *composition record*, not a task,
evidence or lease mutation; the CLI is the single composing process, and the journal's
single-writer discipline is about controller state, not about forbidding a pre-lease
composition record. If the Director wants every journal write under the fence, the same row
can be written at the first tick through the controller's fenced path; that is a different
placement, not a different payload. The note chooses composition because R3 says "at
composition" and the operator line must precede the first tick.

Rejected: no event (silence; the charter forbids); an event per pair (10+ rows and a new kind
used as a log stream); folding it into `IntentApplied` (it is not an intent and no intent is
applied); writing directly to `events` (a new write path around the repository).

### 3.5 The prompt: ids, schemas, handles, and the ordering rule

Two code-owned gates sit between the profile's declaration and a well-formed call, and
neither is a validator:

1. **`ModelRequest.tools` is an overloaded field.** The runtime means "what this stage may
   call"; the router means "this request requires a model that advertises native tool calls"
   (`router.py:1678-1679`) and "a capability-plane allowlist must be injected"
   (`:1544-1548`); the provider constructor refuses a profile that advertises them
   (`cloud.py:636-639`). OPS-5 Path A is adopted: `_model_request` sets `tools=()` and the ids
   travel in the prompt. This strengthens the native-tool boundary, not weakens it. The two
   router guards remain correct for any caller that does set `tools`.
2. **The contract never names a capability or its item shape.** `structured_fields` adds
   `tool_calls (array, optional)` (`run.py:314-327`; `cloud.py:209-231`), and OPS-17
   deliberately left the item schema unstated (`docs/OPS-17-NOTES.md:174-187`). A model must
   guess `{"capability_id", "arguments", "rationale"}` and the legal ids.

OPS-5B will add **one generated note on the `tool_calls` field**, built from the registry's
own declarations and the handle constants — not a hand-typed list:

- every legal `capability_id` for this profile, with its `Tool.summary` and its closed input
  fields (name, type, required, allowed values), sourced from
  `registry.enumerate(grant=grant)` and `registry.tool_for(...)`; the enumeration already
  excludes capabilities the grant cannot reach (`registry.py:263-291`), and the runtime
  filters to `spec.tools`;
- the item shape `{capability_id, arguments, rationale}` and the unknown-key rule;
- the observation handles and their citation mapping:
  `evidence/<artifact_id>` → `EVIDENCE_TRANSITION`'s `evidence:<artifact_id>`;
  `source_payload/<content_hash>` → source/claim refs `source_payload:<content_hash>`;
- the index conversion: an artifact entry id is `<artifact_type>:<artifact_id>`, so a
  `source_payload` entry becomes `evidence:<artifact_id>` by replacing the type prefix;
- the sequencing rule: proposals are admitted **before** the sibling tool batch
  (`run.py:704-724`), so an artifact observed this tick cannot be cited by a proposal in the
  same tick. A tool-only tick is not `proposals_raised` and the run continues; cite in the
  next tick. This is guidance from the runtime's order, not a new rule.

The note is prompt data, not authority. The runtime's `spec.tools` check, the plane's grant
and the gateway's `EVIDENCE_REF` remain the validators. A drift test will change a fake
registry declaration and assert the note follows, the same discipline as OPS-17's shape
drift tests.

**Wiring delta (phase 2, listed so the seam is not discovered late):**

- `build_live_composition` builds the supply, the invoker, the recorder, the per-
  `agent_profile` capability catalog and the withheld tuple; it returns them on
  `LiveComposition` for the CLI line and the journal event.
- `build_controller` gains named `capabilities`, `grants` and `capability_catalog`
  parameters and forwards them to `build_methodology_handler`; the runtime overflow
  `artifacts` stays `None` (this slice does not wire the overflow port).
- `build_methodology_handler` already accepts `capabilities`/`grants`/`artifacts`; it gains
  the opaque `capability_catalog` and passes it to `RuntimeWiring`.
- `RuntimeWiring`, `AgentRuntime` and the module-level `run()` gain the optional
  `capability_catalog` and pass it to `output_contract_for(spec, capability_catalog)`.
- The catalog is a plain mapping of prompt data (`capability_id`, summary, input fields)
  per `agent_profile`, built from `registry.enumerate(grant=grant)`; it is not a port, holds
  no authority, and cannot invoke anything. The plane re-authorizes every call.

**Why this is in D1 and not optional:** the charter's falsifier is scripted and would pass
with no prompt change; a live model would not. OPS-5 §2.1/F3 already required the section.
The cost is system-message bytes for the three profiles that declare `tool_calls`
(`researcher`, `experimenter`, `critic`); `researcher` gets the two real schemas,
`experimenter` and `critic` get the empty-reach statement. M1 counts the user prompt only
(`docs/OPS-7-NOTES.md`, memory `ops-live-run-chain`), so M1 and the LOOP baseline do not
move. The note records the system-byte delta at implementation time.

### 3.6 Rejected D1 alternatives

| Option | Cost | Verdict |
| --- | --- | --- |
| Fixed minimal set for every profile (OPS-5 C1b) | grants `source_search` to profiles that never declared it; the runtime refuses those calls anyway; registry/profile drift | rejected |
| Operator-configured capability list (C1c) | turns an authority surface into config; the codebase deliberately keeps allowlists and registries code-owned (`composition.py:105-123`) | rejected |
| Hard refuse at composition (C1a-strict) | five of six profiles fail; OPS-1 reverted in the slice meant to extend it | rejected as default |
| Path B: advertise native tools, set `supports_tool_calls=True`, delete the provider guard | the wire never carries native tool definitions; the router would believe a capability the transport never exercises; weakens a reviewed guard | rejected |
| Leave the prompt silent, rely on the falsifier's scripted reply | passes the test, fails the first live run; the item schema and ids stay guesses | rejected |

## 4. D2 — the profiles stop being narrowed

### 4.1 Delete `_model_only_profiles`, and state the three cases

`_model_only_profiles` (`composition.py:516-533`) is deleted. Its docstring's first sentence
is corrected where it lands: the provider refuses **native** tool-use blocks; it does not
refuse the runtime's JSON `tool_calls` field.

The replacement is per declaration, not per profile:

| Case | Profiles at this base | Composed `spec.tools` | Grant | `allows_tool_calls` | Contract prompts `tool_calls`? |
| --- | --- | --- | --- | --- | --- |
| **All declared tools supplied** | `researcher` | unchanged | yes | unchanged (true) | yes (profile data) |
| **Mixed: some supplied, some not** | none shipped | narrowed to the supplied subset | yes, over that subset | unchanged | per profile data; a profile that declares the field is prompted and can call the supplied subset |
| **No declared tool supplied** | `critic`, `experimenter`, `planner`, `synthesizer`, `verifier` | `()` | none | unchanged (true for `critic`, false for `verifier`; the other three had true) | per profile data; `critic` still prompts it, and a call is `ROLE`-skipped |

The mixed rule is a **correction to the OPS-5 note's empty-tuple wording**
(`LIVE-CAPABILITY-PLANE.md:241-249`): OPS-5 wrote "composed without a grant and with its
`tools` narrowed to the empty tuple". Under the later R3 clarification, withholding is per
declaration. Emptying a mixed profile would discard a capability the registry *does* supply,
and leaving its full declaration would make a withheld id pass `spec.tools` and reach the
plane, where a refusal is fatal (`run.py:1317-1331`) rather than the benign `ROLE` skip R3
promises. Narrowing `spec.tools` to the supplied subset is the only option that keeps both
promises. The Director can rule otherwise; §13 R2 records the choice.

The zero-supplied case deliberately **does not** re-apply `allows_tool_calls=False`. That is
the blanket narrowing D2 removes, and it hides the profile's declaration. The consequence is
stated rather than papered over: `critic` will be prompted for `tool_calls` it cannot execute,
because its profile data declares the field and R2 of OPS-5 says do not change profile data.
A call is the existing `ROLE` skip, recorded, with feedback; the withheld line and journal row
explain why. Editing `structured_fields` to remove the field is the alternative and it is out
of scope (R2).

### 4.2 The runtime batch rule

The OPS-5 §7.2 rule is retained and is load-bearing: a tool batch executes only when
**both** `spec.model_policy.allows_tool_calls` and `"tool_calls" ∈
spec.model_policy.structured_fields`. This closes F4 — a `verifier` reply carrying
`tool_calls` could execute while its profile says `allows_tool_calls: false`
(`run.py:1208-1239` currently reads only `spec.tools`). No profile file changes.

### 4.3 What a withheld profile's call does, exactly

1. `spec.tools` is `()` (or the supplied subset), so the id is outside it;
2. `_one_tool_call` refuses `ROLE`, emits `TOOL_SKIPPED`, appends `ToolFeedback` with the
   refusal and the invocation ref (`run.py:1270-1286`);
3. the tick continues; the run's other work is unaffected;
4. the gate's withheld event already names the pair, so the operator is not surprised.

This is the same branch the tree uses for a capability outside the declared tools; no new
severity rule.

### 4.4 Rejected D2 alternatives

| Option | Cost | Verdict |
| --- | --- | --- |
| Keep `_model_only_profiles`, layer a port behind it | every profile still has `allows_tool_calls=False`, so the runtime never reads `tool_calls`; the port is unreachable; the slice ships "landed but unreachable" | rejected |
| Empty a mixed profile's tool tuple (OPS-5's literal wording) | discards a supplied capability and contradicts per-declaration withholding | rejected; §13 R2 |
| Leave withheld ids in `spec.tools` | the plane refusal is fatal (`TOOL_FAILED`), not the R3 benign `ROLE` | rejected |
| Rewrite `structured_fields` for the unsupplied profiles | profile data change; OPS-5 R2 says no; needs its own gate and prompt measurement | rejected |

## 5. D3 — M2 becomes a number

### 5.1 Placement and lifetime

`RecordingCapabilityPort` (`eval/loop_observations.py:194-218`) wraps the `CapabilityInvoker`
and is the port the runtime sees:

```
CapabilityInvoker  →  RecordingCapabilityPort  →  AgentRuntime(capabilities=…)
                                                        ↑ one recorder per composed run
LiveVector(capabilities=recorder) ──────────────────────┘  (render reads .calls)
```

- one recorder per `build_live_composition`, held by `LiveVector` and passed through
  `build_controller` → `build_methodology_handler` → `RuntimeWiring` to every stage runtime;
- child runs use the same `AgentRuntime` (`_run_spec`), so their tool invocations are recorded
  by the same recorder — one composed run, one denominator;
- the recorder appends **before** delegation (`loop_observations.py:209-213`): an invocation
  the plane answers with a refusal or failure did happen and belongs in the denominator; a
  call refused before the port (unknown id, outside `spec.tools`, no port) never reaches it
  and is not a tool call.

### 5.2 The number and the line

`repeat_tool_rate` is the fraction of calls whose `(capability_id, arguments_digest)` has
already appeared; the first occurrence is not a repeat; an empty sequence is `0.0`
(`eval/loop_metrics.py:125-140`). The live vector renders:

```
M2(calls=0,repeat=0.000)          # a measured zero: the port existed and saw nothing
M2(calls=3,repeat=0.667)          # two of three calls repeated an earlier call
M2=n/a (no capability port on this run)   # only when the composition held no port
```

The hard-coded `M2=n/a` and the "M2 is n/a, never 0.0" honesty rule
(`eval/live_vector.py:16-18, 136-138`) are superseded for live compositions and rewritten in
the module docstring. The `n/a` sentinel survives exactly where `collect_scenario` already
uses it: a caller that built its own wiring with no port (`loop_observations.py:315-322`).

### 5.3 Rejected D3 alternatives

| Option | Cost | Verdict |
| --- | --- | --- |
| Per-stage recorder | each stage's M2 is a slice; the run aggregate becomes a sum of unmeasured parts; `n/a` per stage | rejected |
| Derive M2 from `TOOL_REQUESTED` / `TOOL_OBSERVED` events | requests include calls refused before the port; observations exclude failed calls; neither is the invocation denominator | rejected |
| Use `_RunState.tool_calls` | it is per runtime run and excludes nothing after the invoke, but it cannot span stages; the charter requires the port-level recorder | rejected as the source |
| Keep `n/a` | once a port exists, `n/a` is a claim nobody measured; a zero is the measurement | rejected |

## 6. D4 — the ledger line

Before the first tick, after composition succeeds, the CLI prints one capability line beside
the existing model line (which stays unchanged):

```
Model plane: live (tiers: m=...)
Capability plane: 2 supplied (source_fetch, source_search), in-process (no sandbox); granted 1 profile (RESEARCHER); withheld 10 declarations — critic/evidence_inspect, critic/contradiction_scan, experimenter/experiment_execute, experimenter/artifact_store, planner/graph_read, planner/artifact_store, synthesizer/artifact_store, synthesizer/provenance_read, verifier/evidence_inspect, verifier/statistic_check
```

- **One line**, before `ctrl.run` (`cli.py:606-614`); the withheld set is compact and complete.
  D1's "one line per withheld declaration" is satisfied by one entry per declaration in the
  line and in the event payload; if the Director wants ten physical lines, D4's one-line
  requirement must give way. The note chooses the single line.
- `in-process (no sandbox)` is the exact constant `IN_PROCESS_ENVIRONMENT`
  (`tools/capabilities/types.py:143`), not a paraphrase. It appears because both supplied
  tools declare network reach and run in the controller's process under R5.
- No key material, no arguments, no URLs, no fetched content: ids and counts only. The line is
  a composition statement, not an authority; the plane re-checks every call.
- **Drain-only byte-identical**: the live branch is not taken, composition is never entered,
  no capability line is printed, and `DRAIN_ONLY_OUTPUT` is unchanged
  (`tests/test_ops1_live_cli.py:43`).
- The line and the `CapabilityPlaneComposed` event are built from the same tuple; a test
  asserts the pair sets agree.

### 6.1 Rejected D4 alternatives

| Option | Cost | Verdict |
| --- | --- | --- |
| No capability line; let the withheld event be the only record | the operator does not know the run's reach before egress; the journal is not read before a run | rejected |
| Fold the capability facts into the existing `Model plane: live` line | one line mixes two planes; the withheld set makes it unreadable; OPS-1's mode statement loses its shape | rejected |
| Print one physical line per withheld declaration | eleven-plus lines before the first tick; D4 says one line; the event already carries one object per declaration | rejected |
| Print the line after the first tick / in the run report | the charter requires it before the first tick; the report is a diagnostic artifact, not the ledger | rejected |

## 7. D5 — the egress posture, restated

### 7.1 The surface

`sandboxed=False`, `environment="in-process (no sandbox)"`, in-process in the controller's
own process. There is no process isolation, no filesystem jail, no CPU/memory cap; the
sandbox config ships disabled (`config/hermes.toml`), and the plane's sandbox gate is only
consulted for `SANDBOX`-kind capabilities (`invoke.py:408-414`). The two supplied tools are
`TOOL` kind.

The code-owned allowlist is exactly four hosts (`research/live_fetch.py:82-88`):

| Host | Provider | Use |
| --- | --- | --- |
| `api.openalex.org` | OpenAlex | search and API fetch |
| `openalex.org` | OpenAlex | canonical record `source_url` |
| `eutils.ncbi.nlm.nih.gov` | PubMed | E-utilities |
| `pubmed.ncbi.nlm.nih.gov` | PubMed | canonical record `source_url` |

`allowlist_from_config` may **narrow** it from `sandbox.network_egress_allowlist`; an entry
outside the code-owned set is refused loudly (`live_fetch.py:117-162`). Config may never
widen it. Each provider's fetch URL must belong to that provider's own two-host surface; a
cross-provider URL refuses with `PROVIDER_HOST_MISMATCH` after the allowlist and before a dial
(`capability_supply.py:422-440`).

### 7.2 What refuses, and when

| Barrier | Site | Refusal |
| --- | --- | --- |
| Unparseable / relative URL | `security/egress.py:215-223` | `MALFORMED_URL` |
| Userinfo in the URL | `:224-227` | `CREDENTIALS_IN_URL` |
| Scheme not https | `:228-231` | `SCHEME_NOT_ALLOWED` |
| Origin not in the allowlist (including an explicit non-default port) | `:235-243` | `ORIGIN_NOT_ALLOWLISTED` |
| DNS resolution failure / no addresses | `:245-269` | `DNS_FAILURE` / `NO_ADDRESSES` |
| Any private, loopback, link-local or mixed address | `:270-284` | `ADDRESS_BLOCKED` |
| Host pin for the dial | `live_fetch.py:52-75` | the vetted address is pinned; a resolver flip cannot redirect the dial |
| Cross-provider host | `capability_supply.py:422-440` | `PROVIDER_HOST_MISMATCH` |
| Transport timeout | `live_fetch.py:91` (10 s default), `:410-416` | a transport error; the plane records a failure |
| Tool deadline | `capability_supply.py:175,189` (60 s) | the invoker discards an overrun result (`invoke.py:866-874`) |
| Fetch size ceiling | `capability_supply.py:130` (256 KiB) | the driver's typed failure |
| Search size ceiling / page / rows | `capability_supply.py:129, 127-128` | 1 MiB / one page / 25 rows |
| Empty or malformed search arguments | `capability_supply.py:538-566` | typed validation failure |
| A fetch with no URL | `capability_supply.py:353-357` | typed validation failure |
| Process-construct scan (OPS-5A debt 2) | `invoke.py:725-730` | an argument containing `;`, `&&`, `\|\|`, `$(`, a backtick or a process primitive refuses even though the tool is network-only; conservative, unchanged |

A pre-dial refusal is journaled as a metadata-only `provider_interactions` row with the
host and the rule's named code (`capability_supply.py:211-261`); no body, no query value, no
request is dialed. A success journals identity, redacted request metadata and a response
digest; `retain_body=False` (`capability_supply.py:287-294`). The process-construct scan
means a perfectly allowlisted URL containing `&&` still refuses before the egress gate; that
is OPS-5A debt 2, recorded and not fixed here.

### 7.3 The body-persistence change

The charter asks what changes if the artifact chain needs the bytes. **It needs them.** The
answer is precise:

- the **`provider_interactions` row stays body-less** (`retain_body=False`); its
  `response_body_hash` is the digest, never the bytes;
- the **fetched bytes are persisted once**, as a `source_payload` artifact in the existing
  content-addressed store (§9). That is a change from OPS-5A's "the capability path persists
  no body" statement, and the record must say so;
- no `provider_response` artifact is written for the fetch: the interaction sink receives
  `body=None`, and the artifact store receives the bytes under `source_payload`. This avoids
  a same-content, different-type collision with the provider-response artifact type.

### 7.4 What a live run can reach

| Capability | Local / remote | Hosts | What refuses |
| --- | --- | --- | --- |
| `source_search` | remote | the named provider's API host: `api.openalex.org` or `eutils.ncbi.nlm.nih.gov` | any other host, scheme, userinfo, non-public DNS, over-cap response, timeout, rate gate, empty query |
| `source_fetch` | remote | the named provider's surface: `{api.openalex.org, openalex.org}` or `{eutils.ncbi.nlm.nih.gov, pubmed.ncbi.nlm.nih.gov}` | any out-of-surface host before a dial, provider/host mismatch, missing URL, over-cap body, timeout, transport failure |
| `evidence_inspect`, `contradiction_scan`, `graph_read`, `provenance_read`, `statistic_check` | local — **unsupplied** | none | no implementation exists; `ToolCallContext` carries no connection or evidence view (`types.py:423-440`); withheld and named |
| `artifact_store` | local — **unsupplied by decision** | none | a `mutating=True` tool is refused `ROLE` (`invoke.py:558-565`); supplying it would let the model author bytes; §9.3 |
| `experiment_execute` | local — **unavailable** | none | needs `SANDBOX` kind + `sandbox_enabled=True`; the sandbox ships disabled (`invoke.py:412-417`) |
| model plane | remote | the dialect hosts in `composition.py:107-111` / the reviewed gateway | not part of the capability plane; unchanged by this slice |

A capability cannot reach the project database, the filesystem, a process, the model
credential, or any host outside the four. The one local durable effect this slice adds is the
`source_payload` artifact row and its file, written from provider bytes under a derived
identity (§9). That is the effect the Director must rule on.

### 7.5 Rejected D5 alternatives

| Option | Cost | Verdict |
| --- | --- | --- |
| `retain_body=True` and cite the `provider_response` artifact | writes the body twice or collides on the content hash; `provider_response` is not a source type, so claims cannot read it and `RETRACT_SOURCE` rejects it as a source | rejected |
| Keep the body-less posture and return only a transient handle | no citable row; the falsifier fails | rejected |
| Supply `artifact_store` so the model writes the body | model-authored bytes; plane refuses `mutating=True`; new authority | rejected |
| Declare `sandboxed=True` to satisfy the old authority rule | a false isolation record; OPS-5 R5 fixed this, and 5B does not regress it | rejected |
| Let config widen the allowlist | turns a code-owned egress surface into operator config; the posture is narrow-only | rejected |
| Journal the fetched body in the interaction row | violates the 4 KiB event/row discipline and the "refs and digests only" rule | rejected |

## 8. D6 — cost, without overclaiming

### 8.1 What bounds a run today

| Bound | Value / source | Scope |
| --- | --- | --- |
| Ticks per stage | `max_ticks` in each profile (`researcher` 4, `critic` 3, …) | per runtime run, read at `run.py:1622-1623` |
| Model calls per phase per tick | `max_model_calls_per_tick` (1–2) plus at most one OPS-15 retry | per phase, per tick (`run.py:823-829`) |
| Tool calls per batch | `max_tool_calls` (2–6) | **per tick batch**, not cumulative (`run.py:1217`) |
| Child runs / depth | `max_child_runs` ≤ 4, `max_delegation_depth` ≤ 1 | per run (`types.py:244-253`) |
| Run wall-clock | `deadline_seconds` (120–600) resolved once, checked at the tick, the close act and the review | per run (`run.py:1625-1644`) |
| Per-call transport timeout | 10 s default (`live_fetch.py:91`) | per HTTP request |
| Declared tool deadline | 60 s (`capability_supply.py:175,189`) | the invoker's bound; it cannot preempt Python, it discards a late result |
| Search rows / pages / bytes | ≤ 25 rows, 1 page, 1 MiB | per search call |
| Fetch sources / bytes / retries | 1 source, 256 KiB, 1 retry, no jitter | per fetch call |
| Provider rate gate | in-memory `ProviderRateLimiter`, code-owned defaults, resets on restart (`live_fetch.py:66-70`); the operator's narrow-only caps apply only if D1 threads `cfg.autonomy_caps` into the supply | per provider, time-windowed |
| Event payload | 4 KiB (`event_validation.py:23`) | every event |
| Prompt envelope | 4 KiB (`MAX_PAYLOAD_BYTES`) | index, feedback, payload envelopes |
| Project index entries | 40, 4 KiB (`docs/idr/LIVE-PROJECT-INDEX.md`) | per stage |

### 8.2 What does not bound a run

- **Tokens and dollars.** `per_run_tokens` is a provider-request counter and the methodology
  handler reports zero provider requests (`docs/OPS-15-NOTES.md:40-55`; OPS-16 recorded,
  unlanded). Model calls are not charged to it. The model ledger records input/output tokens
  per attempt as a diagnostic, not as a charge (`cli.py:637-652`).
- **Tool requests.** A capability's HTTP requests are not charged to the controller's budget:
  they happen inside the stage runtime, not inside a dispatch whose `HandlerResult` reports
  `provider_requests` (`source_handlers.py:369-389`). The capability path's requests are
  invisible to `per_run_tokens`.
- **Aggregate tool bytes.** The per-call caps bound one response; a run may make up to
  `max_ticks × max_tool_calls` calls per stage, across stages, and each fetch may persist
  256 KiB. There is no per-run byte or disk budget and no artifact GC. The backup includes
  the store, so disk spend is real.
- **A single in-flight call vs the run deadline.** `_one_tool_call` receives no run deadline
  (`run.py:1241-1244`); the invoker's deadline is the tool's 60 s (or the request's
  `deadline_seconds`, which the runtime leaves `None`). The supervisor checks before the batch
  item and after the tick, but a call already in flight can overrun the run deadline by up to
  the transport timeout (10 s default; 60 s tool bound). The result is discarded and the run
  terminates, but the wall-clock bound is "run deadline plus at most one in-flight call".
  §13 R8 proposes passing the remaining deadline into `InvokeRequest.deadline_seconds`; it is
  a small fix, not a claim.

**No run is spend-capped. No run is token-bounded. No run is dollar-bounded.** The only
honest statement is: bounded in ticks, model calls per tick, tool calls per batch, child runs,
per-call wall-clock and per-request bytes; not bounded in aggregate model tokens, aggregate
tool bytes, aggregate requests across ticks/stages, or dollars.

### 8.3 Rejected D6 alternatives

| Option | Cost | Verdict |
| --- | --- | --- |
| Describe `per_run_tokens` as the run's spend cap | it counts provider transport requests, and the methodology handler reports zero; a tool call inside the runtime is not charged; the statement would be false | rejected |
| Charge tool calls to `per_run_tokens` in this slice | the counter is a provider-request envelope with its own controller semantics; wiring the capability path into it is an accounting change (OPS-16), not a port | rejected as out of scope; OPS-16 remains the owner |
| Add a per-run tool-byte or dollar budget | a new budget surface with no ledger; the charter forbids new write paths and the slice has no metering source | rejected; record the absence instead |
| Make `max_tool_calls` cumulative rather than per batch | changes certified runtime semantics and the LOOP baseline; not this gate | rejected |
| Claim "bounded" because each call is capped | a per-call cap is not a per-run cap; aggregate bytes/requests grow with ticks and stages | rejected |

## 9. The artifact supply decision

### 9.1 The chosen chain

`source_fetch`, on a `FETCHED` outcome, records the payload:

1. The executor has the raw bytes and the transient `FetchedPayload`
   (`research_sources.py:498-514`) with `artifact.content_hash`, `media_type`, `size_bytes`.
2. It calls the injected `ArtifactStore.write` with:
   - `artifact_type="source_payload"` (the existing source taxonomy,
     `source_outcomes.py:93-95`);
   - `producer=f"capability:source_fetch:{profile}:{idempotency_key}"`;
   - `project_id=<the composition's project>`, `task_id=None`;
   - `artifact_id=payload.artifact.content_hash` (the derived content identity; see §9.2);
   - `metadata={"capability_id": "...", "provider": "...", "source_url_redacted": "...",
     "media_type": "...", "retrieved_at": "...", "idempotency_key": "...",
     "lease_generation": "..."}`.
3. The store writes the bytes atomically to the content-addressed path, then
   `ArtifactRepository.record` issues a plain `INSERT` on the autocommit connection
   (`artifacts/store.py:100-160`; `repositories.py:953-980`; `database.py:62-64`). No
   `BEGIN`/`COMMIT`, no new owner, no table.
4. The executor checks the returned row: `artifact_type == "source_payload"`,
   `content_hash` equals the fetched hash, and `project_id` equals the composition's project.
   A store dedup hit that is a different type or a foreign project is a typed refusal, not an
   uncitable handle.
5. The tool returns `ToolResult.artifacts = ("evidence/<artifact_id>",
   "source_payload/<content_hash>")` and a compact JSON payload with `artifact_id`,
   `content_hash`, `source_ref`, `status`, `url`, `media_type`, `size_bytes`,
   `retrieved_at`. It does **not** return the body text and it does **not** present
   `art_<hash24>` as citable.
6. `EVIDENCE_REF` now finds the row (`in_project(artifact_id, project_id)`); the claims path
   resolves `source_payload:<content_hash>` by content hash (`source_outcomes.py:477-519`);
   the project index lists the row as `source_payload:<artifact_id>`
   (`research/project_index.py:44-47`); a retraction resolves a bare id or
   `source_payload:<hash>` in-project (`gateway.py:1570-1616`); N9's `supersedes` edge can
   target it (`source_outcomes.py:161-183`).
7. `source_search` writes **no** artifact: a `source_result` row would be a discovery record
   without bytes, and the model cannot see the rows anyway (§1.5). Search remains
   discovery-only; `NO_FULL_TEXT` remains a result without an artifact. Both are stated
   limits, not silent omissions.

### 9.2 Identity: content hash, not a random row id

The store currently mints `artifact_id = uuid4()` (`artifacts/store.py:148`). The note adds
an optional `artifact_id` argument to `write`, defaulting to the UUID, and the capability
supply passes `payload.artifact.content_hash`. Why:

- the project's identity discipline is content-addressed
  (`fc_`/`cx_`/`cres_`/`fx_`/`retract_`, AGENTS.md; `research_sources.py:465` already derives
  `art_<hash>`);
- the index entry id becomes `source_payload:<hash>`, which is exactly the claims/source ref
  suffix; the model replaces only the type prefix for `EVIDENCE_TRANSITION`;
- a re-fetch of the same bytes dedups to the same row/id; the identity is stable without a
  row-minting clock;
- `EVIDENCE_REF` accepts any artifact id, and a hash is a valid id; the row's `content_hash`
  equals its `artifact_id`, so the two dereference keys agree.

A store dedup hit may return a **task-path** `source_payload` row with a UUID artifact id
(the task path still mints UUIDs); the handles use the actual row's `artifact_id` and
`content_hash`, so both forms are citable. The note does not change the task path.

### 9.3 Why `artifact_store` remains unsupplied

It is one of the declared capabilities OPS-5A did not supply. Supplying it would be the
wrong chain for evidence:

- a model-callable store lets the model **author** the bytes; evidence must be what the
  provider returned, not what the model says the provider returned;
- the plane refuses `mutating=True` tools (`invoke.py:558-565`); making it legal would require
  a plane change and a new authority decision;
- the model does not have the bytes to store: the tool payload text is not inlined into the
  prompt, and the model cannot read an arbitrary artifact;
- the chain's write belongs to the fetch executor, where the bytes and the project binding
  are already present.

The supply decision is therefore: **`artifact_store` stays withheld**, named and journaled;
the recording write is a capability-internal act, not a model-callable tool.

### 9.4 The ruling: recording vs authoring

The charter's invariant 1 says "no new write path; no transaction". This note argues the
artifact write is **not a new write path**:

- it uses the existing certified `ArtifactStore` → `ArtifactRepository` writer (IDR-008/013),
  the same one the task-side source path uses;
- it adds no table, no schema version, no transaction-control call, no acquisition owner and
  no census figure;
- it is the same class of act as OPS-5A's provider-interaction journaling: the tool already
  causes a durable metadata write from the transport; this adds the observation body under a
  derived, content-addressed identity;
- the tool cannot choose the content (the provider returns it), the type (`source_payload` is
  fixed), the identity (the store computes the hash), the project (the composition binds it),
  or the destination (the store's content-addressed path). It chooses only whether to fetch.

But the plane's `Tool.mutating` field says "a plane never authors state"
(`types.py:228-236`), and `_authorize` refuses a mutating tool. The note keeps
`mutating=False` under the definition the provider-interaction sink already uses: **recording
an observation is not authoring a decision.** If the Director reads `mutating` as "any
durable write", the honest alternatives are:

1. set `mutating=True` and extend the plane to permit observation recording — a plane change
   with its own gate, not this slice; or
2. leave the chain in memory — the falsifier fails and the project keeps zero artifacts.

There is no third option that produces a citable row without a write. This is the one supply
ruling the phase-1 note asks the Director to ratify. It is isolated here so it cannot be
mistaken for an implementation detail.

### 9.5 Consequences, stated

| Consequence | Why | Mitigation / follow-on |
| --- | --- | --- |
| `artifacts.task_id` is NULL | `ToolCallContext` carries no task id (`types.py:423-440`), the supply is composed per run, and the same FK-invalid reasoning as OPS-5A's `provider_interactions.task_id` applies | the row is project-scoped; metadata carries the idempotency key/lease; a future task-bound port can add the link |
| no `provenance_edges` | the capability has no task/outcome anchor to point at | `EVIDENCE_REF`, claims and retraction resolve by `project_id`/hash; ref graphs and requirement satisfaction will not see the row; a follow-on can add an edge when a task id exists |
| cross-project dedup refuses | `content_hash` is globally unique; the store returns an existing foreign row; `in_project` would fail and the index would hide it | the capability refuses with a typed error; edge-carried sharing would need an edge writer and an `in_project` change (out of scope) |
| the same bytes as a task-path `source_payload` reuse the UUID row | the store dedups by hash | handles use the row's actual values; both refs work |
| a different artifact type with the same hash refuses | `content_hash` UNIQUE + the R02 type discipline (`source_outcomes.py:1054-1062`) | fail closed; the bytes are not silently reused as a source |
| `source_artifact_is_web_derived` returns False | the predicate reads `metadata.source_result_ref` for `source_payload` (`source_outcomes.py:243-263`); the capability row has no such ref | correct for OpenAlex/PubMed (not in `WEB_SEARCH_PROVIDERS`); a future web-provider supply must set the ref or extend the predicate before it may claim evidence |
| no `source_result` row for search or `NO_FULL_TEXT` | discovery/no-text is not a fetched payload | follow-on: persist `source_result` rows or add a read/summary surface |
| the index may omit old artifacts | 40-entry/4 KiB cap (`docs/idr/LIVE-PROJECT-INDEX.md`) | `omitted` is truthful; the same-run handles cover the immediate next tick |
| disk grows | content-addressed store, no GC | backup already snapshots the store; a retention policy is a separate decision |

### 9.6 Rejected supply alternatives

| Option | Cost | Verdict |
| --- | --- | --- |
| In-memory only (OPS-5A's `retain_body=False` for everything) | no citable row; the falsifier fails; the project stays at zero artifacts | rejected |
| Supply `artifact_store` as a model-callable writer | model-authored bytes; plane refuses `mutating=True`; new authority | rejected |
| Route through `SourceOutcomeRepository.record` | requires a RUNNING SOURCE_* task and a task binding (`source_outcomes.py:376-411`); the tool call has no task row and tools may not write intents | rejected |
| A new intent kind that admits an observation | new event/intent/write path; the model would author evidence; violates the charter's invariant 1 | rejected |
| The runtime's `ArtifactOverflowPort` (`delegate.py:74-84`) | designed for oversized proposal bodies, `store(body, media_type)` only; no type/project/task semantics; a new runtime behavior | rejected |
| Filesystem-only (`raw_bytes_ref` without a DB row) | not citable; `EVIDENCE_REF` reads the DB | rejected |
| Type `evidence` instead of `source_payload` | the index id would match `evidence:<id>`, but claims' readable-text carrier set is `{source_payload}` (`claims.py:117`) and `read_payload_bytes` accepts only source types (`source_outcomes.py:477-519`); would need a claim-ground change | rejected |
| Register the task-side source handlers and make the model insert SOURCE_FETCH tasks | tools may not write intents; the model would need the source task admission shape (OPS-17 lists it as unstated); the artifact would arrive a tick later through a different authority path | rejected for this slice |

## 10. What must not change

| Invariant | How this design upholds it |
| --- | --- |
| **Certified census 124 / 28 (19/5/4) / 1 / 15 / 0** | no new table, schema version, transaction-control call or acquisition owner. `ArtifactRepository.record` is a plain `INSERT`; the store writes a file first; the withheld event rides `EventRepository.append_transactional`, an existing owner. `scripts/check_census.py` must pass unchanged. |
| **Single mutation path** | tools gather evidence; they never write intents. The artifact row is a recording of provider bytes, not a decision; every proposal still crosses `apply_intent`. |
| **Native `tool_use` blocks refused** | `_tool_refusal` (`tools/models/cloud.py`) is untouched; `_model_request` sets `tools=()`, so no native advertisement is added. |
| **Drain-only byte-identical** | the live branch is not entered; no supply, no artifact store, no capability line, no event; `DRAIN_ONLY_OUTPUT` unchanged; `ProviderHTTPTransport` remains booby-trapped in the regression test. |
| **B4 stays 24** | no governed ref-graph input moves; the new design note is not a governed doc. |
| **Governed docs untouched** | `docs/STATE.md`, `docs/API.md`, `docs/ARCHITECTURE.md` are not edited in phase 2 unless the Director schedules a separate doc gate. `docs/idr/LIVE-PROJECT-INDEX.md:132` ("the live composition narrows every profile to model-only and passes no capability port") becomes stale after 5B; it is an IDR record, not a governed contract, but the Director should note the drift. A B4 regeneration is **not** required for a docs-only phase-1 commit; if a governed doc moves in phase 2, B4 must be regenerated and the 24 re-pinned. |
| **No key material** | the supply never receives model credentials; the line/event/handles/metadata carry ids, counts, hosts and redacted URLs only; the event payload is scanned for secrets; no keys in the report or vector. |
| **OPS-18 read port stays read-only** | the new row is a **writer** beside it; `ProjectIndexReader` still does three `SELECT`s and three `COUNT`s, no transaction; the index is read once per stage. |
| **One new event kind** | `CapabilityPlaneComposed` only; no other event, no new table, no schema change. |
| **Server-side authority** | grants are derived in code from the profiles and the registry; no profile file, config value or model output mints a grant. |

## 11. Falsifiers → tests

The new test file (proposed `tests/test_ops5b_capability_composition.py`) plus the chartered
targeted files. The live-shaped tests use scripted model replies and a scripted inner HTTP
transport over the **real** chain (`RecordedTransport` → allowlist → host pin → HTTP), never
the network.

| Falsifier | Test shape | Assertion |
| --- | --- | --- |
| A live-shaped run with a scripted `tool_calls` reply executes the tool, and an artifact row exists afterwards that `EVIDENCE_REF` accepts | tick 1: `source_fetch` for an allowlisted URL, scripted HTTP response; the test reads the returned artifact id, then applies `EVIDENCE_TRANSITION("evidence:<id>")` through the real `apply_intent` | the executor ran once; the `artifacts` row exists in the project; `in_project` true; the transition is `ADMITTED`; the row's bytes re-derive the content hash; the interaction row has no body |
| The same, through a second tick | tick 1 tool-only; tick 2 scripted reply reads the artifact id from the temp DB and cites it | tick 1 does not stop (`proposals_raised` false); tick 2 admits the evidence transition; the vector's M2 is numeric |
| A capability a profile declares but the registry lacks is withheld, named, journaled, and the run proceeds | compose with the real profiles | `withheld` has the ten pairs; one `CapabilityPlaneComposed` row with the same pairs; `researcher` unchanged/ granted; `critic` tools `()`; a run proceeds |
| M2 is a number; zero calls reports a measured `0.0` | a live-shaped run whose scripted replies carry no tool calls | `M2(calls=0,repeat=0.000)`; n/a absent; a unit test with `capabilities=None` still renders n/a |
| The ledger line states `in-process (no sandbox)` and the withheld set | CLI live run | the line is printed before the first `model call`/tick; contains the constant, the two supplied ids, the ten pairs; no key; drain-only output unchanged |
| Out-of-allowlist host refuses before a dial | `source_fetch` with `https://evil.example/x` through the composed plane | `EgressRefused`/typed failure; no request reaches the inner transport; an `EGRESS_REFUSED` interaction row with the host and code; run `FAILED/TOOL_FAILED` |
| Drain-only byte-identical, transport booby-trapped | the OPS-1 test, unchanged | `DRAIN_ONLY_OUTPUT` exact; `ProviderHTTPTransport` never constructed; no capability line |
| The LOOP baseline unchanged | the baseline test | the pinned vector is unchanged; the capability note is system text, M1 unchanged for no-tool baselines |
| B4 = 24 | `tests/test_b4_ref_graphs.py` | 24 passed; no governed doc move |
| Census unchanged | `scripts/check_census.py` | PASS — 124 / 28 / 1 / 15 / 0 |
| The prompt names the ids/schemas/handles | a contract render with a fake registry | the `tool_calls` note follows the declaration (drift test); the item keys, both handle forms and the index prefix conversion appear; a profile with no grant gets no advertised ids |
| The index prefix mismatch is closed | add a `source_payload` artifact with a known id; an index-driven model cites the raw `source_payload:<id>` | raw ref refuses `MALFORMED_PAYLOAD`; the converted `evidence:<id>` admits; the test fails if the guidance is removed |
| The transient `art_` id is not citable | assert the tool payload/handles | no `art_<hash24>` in `artifacts`; the persisted row's id/hash are the only citations; `in_project("art_...")` false |
| The artifact write is idempotent and typed | call the same fetch twice; seed a same-hash different-type row; a foreign-project row | the same row/handles returned; the type/foreign cases refuse with a typed error; no uncitable handle |
| No key material in any output | scan the line, event, report, vector, handles and metadata for the key literal | absent |

Existing-test updates: `test_source_fetch_succeeds_against_the_allowlisted_provider`
currently asserts the fetched marker is in `payload["text"]`
(`tests/test_ops5_capabilities.py:285`). After 5B the payload carries handles and metadata,
not the body, so that assertion moves to the persisted bytes
(`ArtifactStore.read_verified(content_hash)` / the row's content hash). The same test's
interaction-row no-body assertions (`:298-300`) stay exactly as they are: the journal row
remains body-less while the artifact row carries the bytes. The search test's row payload is
unchanged; search is still a discovery result.

Test seam note: the live CLI test currently monkeypatches `composition.ProviderHTTPTransport`
(`tests/test_ops1_live_cli.py:162-166`). The capability wiring lives in
`research/live_fetch.py`, so the composed test should either monkeypatch
`live_fetch.ProviderHTTPTransport` or, preferably, inject a `capability_machinery` /
`capability_transport` through `build_live_composition` (the supply already accepts a
`machinery` injection, `capability_supply.py:467-492`). The note recommends the explicit
injection seam; it keeps the real allowlist/pin/recorded chain and avoids patching two
different symbols.

## 12. Gates (implementation phase)

1. Targeted: the new test file, `test_ops5_capabilities`, `test_capability_plane`,
   `test_ops1_live_cli`, `test_loop_observations`, `test_b4_ref_graphs`,
   `test_census_check`, plus `test_loop_baseline` and `test_ops18_project_index` (the
   index/evidence prefix case).
2. `scripts/run_tests.py` (full) under the heavy-gate lock, no exclusions.
3. `scripts/stamp_suite_count.py` then `--check`.
4. `scripts/check_census.py` — unchanged.
5. `uvx ruff check src tests scripts`; `uvx pyright src`; pyright with
   `pyrightconfig.tests.json`.
6. B4 ref graphs: 24; regenerate only if a governed doc moves (it should not).
7. LOOP baseline: unchanged; no re-baseline.
8. Drain-only snapshot and the `ProviderHTTPTransport` booby trap: unchanged.
9. For **this phase-1 commit**, the change is docs-only: the full suite must be green to
   prove no behavior change; `stamp_suite_count.py --check` must still read 5232;
   `check_census.py` must pass; ruff/pyright run. The raw results are in the phase-1 report,
   not inferred.

## 13. What I could not decide from the tree

| # | Ruling needed | Why the tree cannot settle it | Recommendation |
| --- | --- | --- | --- |
| **R1** | Is the capability executor's `source_payload` write "recording" (allowed) or "authoring state" (a new write path under invariant 1)? | Both readings are defensible: it reuses the existing store, but it is a new call site and the plane's `mutating` flag says a capability never authors state. Only the Director can choose the definition. | **Recording**, per §9.4; if not, the chain needs a plane change and cannot land in 5B. |
| **R2** | Mixed profile: supplied subset + grant, or withhold the whole profile? | OPS-5's literal wording says empty the tools; R3's per-declaration withholding says keep the supplied subset. No shipped profile is mixed, so the tree does not exercise it. | **Subset + grant** (§4.1); empty-tuple rejected as a capability loss. |
| **R3** | Include the bounded success `detail` in `ToolFeedback`? | Today success drops the notes, so the model cannot distinguish `NO_FULL_TEXT` from an empty search; the LOOP-2 text-withholding rule does not require dropping the tool's own bounded note. | **Yes**, with the envelope's 4 KiB cap and untrusted origin; this is a small runtime change, scoped in D1. |
| **R4** | Make `source_search` observations actionable (bounded structural summary or read capability)? | The model currently sees only size/digest; search is inert. A summary would inline provider metadata into the prompt; a read capability is OPS-5C. | **No in 5B**; record the limitation; the first real run can fetch a URL it knows. Revisit with a bounded structural summary (ids/URLs/years, no titles/abstracts) or OPS-5C. |
| **R5** | Cross-project content dedup: refuse, or add edge-carried sharing? | `content_hash` is globally unique; the store can return a foreign row; `EVIDENCE_REF` only checks `project_id`. Edge-sharing would need an edge writer and an `in_project` change. | **Refuse** the foreign row; fail closed. |
| **R6** | Event name and empty-set behavior; fail-closed on the event write? | The charter allows one new kind for the withheld set; the tree has no name or empty-set precedent. | **`CapabilityPlaneComposed`**, written for every live composition (empty withheld list included), fail-closed. |
| **R7** | Artifact id: content hash or UUID? | Both satisfy `EVIDENCE_REF`; the hash simplifies index/claims refs but changes the store's id-minting default (as an optional argument). | **Hash** for capability-written source payloads; task-path rows keep UUIDs. |
| **R8** | Pass the run's remaining deadline into the tool call? | `_one_tool_call` has no deadline argument; the invoker's deadline is the tool's 60 s. The overrun is bounded by the transport timeout but real. | **Pass the remaining deadline** in phase 2 (small, uses `InvokeRequest.deadline_seconds`); if deferred, the D6 wording "run deadline plus one in-flight call" must stand. |
| **R9** | Is the OPS-18 IDR's "narrows every profile to model-only" sentence corrected in this slice? | It becomes false; the charter says governed docs untouched, but an IDR is a decision record. | **Leave it** in phase 2; record the drift; a doc-gate correction is separate. |
| **R10** | Add the capability schema section to the prompt (F3)? | OPS-5 §2.1 required it; the charter's falsifier is scripted and would pass without it; the live model would guess. | **Yes**; it is D1's contract note, system text only, M1 unchanged. |

## 14. Claim boundary

This note claims what the tree does at `1e9266c`: the measured profile table (§1.2), the
absence of any capability→artifact write (§1.3), the exact `EVIDENCE_REF` predicate (§1.4),
the tool-feedback surface (§1.5), the hop-by-hop trace (§2), the egress surface and its
refusals (§7), and the bounds table (§8). It claims the decisions in §3–§9 and their rejected
alternatives. It does **not** claim that a live model will reliably emit a well-formed
`tool_calls` array or use the handles; that depends on the prompt note and is empirical. It
does **not** claim token or dollar boundedness, scientific validity, or replay-as-validity. It
does **not** claim that the artifact write is authorized until the Director rules on §9.4.

The one thing to read twice: **the port and the artifact write are different hops.** A run
that executes `source_fetch` and still writes no `artifacts` row has proved the port works and
the evidence chain does not. The falsifier is the row, not the call.

License: Apache-2.0 (LICENSE).
