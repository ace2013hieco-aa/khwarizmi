# OPS-5 — wire the capability plane into the live run

| Item | Value |
| --- | --- |
| Task | OPS-5: a live run must be able to *observe*, not only draft and review |
| Base | `c57465b` (`main`, OPS-1 merged) |
| Branch | `slice/ops-5-capabilities` |
| Phase | **1 — design gate. No code in this phase.** |
| Status | **PROPOSED (2026-10-24)** — C1–C5 decided subject to the five rulings in §12 |

## 0. Verdict summary

1. **The charter's §2 premise is half right, and the half that is wrong changes the
   slice.** The cloud provider does not refuse a JSON `tool_calls` field — that is
   true, and `_model_only_profiles`'s stated reason is false. But the provider
   **does** refuse, twice, on the way to a tool-bearing request, and the router
   refuses a third time. "The missing port is the blocker" is not yet a sufficient
   account: three code-owned gates sit between today's tree and a model call that
   can carry a `tool_calls` field (§1.2).
2. **The §2 verification the charter asked for: 3 of 6 profiles, not 6 of 6.** The
   output contract is built from `model_policy.structured_fields`
   (`agents/runtime/run.py:283-302`), and `planner`, `synthesizer` and `verifier`
   do not declare `tool_calls` (§2). A compliant model therefore never emits the
   field for those three — and a non-compliant one gets its whole reply refused
   while its tool calls still execute (§7.3, finding F4).
3. **No capability in the tree has an implementation.** Zero of the ten declared
   capability ids resolves to a `Tool` or an executor anywhere in `src/`. The only
   wired `CapabilityInvoker` is the hostile-evaluation rig
   (`eval/hostile.py:670`, tools `svc.echo`/`svc.scoped`). The capability plane
   has never run in production, so "wire the port" is not a wiring exercise: it is
   also a *supply* decision (§3).
4. **C1 — C1a, restated.** The registry is built from a code-owned capability set;
   grants are derived from the profiles' declared `tools`; the derivation is per
   **`agent_profile`**, not per profile name, because that is the key the runtime
   and the invoker both use (`run.py:1201`, `invoke.py:514`). A declaration the
   registry cannot supply is **withheld and named at composition**, not refused at
   call time — the hard-refusal reading of C1a is costed and rejected in §3.4
   because it makes live mode unreachable for every profile but `researcher`.
5. **C2 — the egress surface is exactly two capabilities, four hosts, in-process,
   allowlist-and-transport-only.** The host set is code-owned
   (`research/live_fetch.py:82`), config may narrow it and never widen it, a call
   naming any other host is refused by `EgressPolicy.vet` before a dial, and that
   refusal terminates the run exactly as C4 already does (§4).
6. **C3 — `RecordingCapabilityPort` is wired between the invoker and the runtime,
   one recorder per composed run.** M2 becomes a number for every stage whose
   profile carries a grant; `n/a` survives only for runs whose path has no port
   (which, after this slice, is the withheld profiles — stated, not silent).
7. **C4 — the current behaviour is kept, and written down.** A plane refusal or an
   observation failure terminates the run `FAILED/TOOL_FAILED`; a grant/declared-set
   mismatch is a benign skip (`ROLE`, recorded, the tick continues). No behaviour
   changes in this slice (§6).
8. **C5 — delete `_model_only_profiles`.** It is replaced by grant derivation plus
   one honest runtime rule: a stage may emit `tool_calls` only when *both*
   `allows_tool_calls` and `tool_calls ∈ structured_fields`, and `ModelRequest.tools`
   stops being used as a native-tool advertisement (§7).

The note also records six findings the charter did not anticipate — F1–F6 in
§8. Three of them (F4, F5, F6) are defects in or beside certified surfaces that
OPS-5 must route around rather than fix, and one (F5) is a security statement the
Director should see before approving egress.

## 1. The tree at this base

### 1.1 The live path as OPS-1 left it

`hermes run` with a non-empty `[model_tiers]` composes:

```
build_live_composition (composition.py:463)
  load_profiles() → _model_only_profiles()          # every allows_tool_calls := False
  build_model_binding(... )                          # no tool_allowlist
  RecordingModelPort(binding)                        # M1
  build_controller(..., model=recorder, supervisor, on_stage=vector.record)
    → build_methodology_handler(model=..., profiles=...)   # no capabilities, no grants
      → RuntimeWiring(model=..., profiles=..., grants=None, capabilities=None)
        → AgentRuntime(... capabilities=None, grants={})
```

The seam is already shaped for this slice: `build_methodology_handler` accepts
`grants` and `capabilities` and threads both into `RuntimeWiring`
(`research/task_handlers/__init__.py:249-322`), which passes them to
`AgentRuntime` (`agents/runtime/wiring.py:298-318`). Nothing in `research/` or in
the runtime needs a new constructor parameter. What is missing is (a) something to
put in those two arguments and (b) the removal of the narrowing that makes
`allows_tool_calls` unreachable.

The egress surface is currently **zero**: with no capability port, a tool call is
refused benignly (`run.py:1176-1186`) and no request ever leaves the process.

### 1.2 Why "the missing port is the blocker" is incomplete

The charter is right that `_tool_phase` reads `structured["tool_calls"]` — a JSON
field in the model's text reply — and that neither dialect's `_tool_refusal`
(`tools/models/cloud.py:293`, raised at `:385` and `:445`) fires on it. It is wrong
that nothing else blocks. Three gates do, and each is code-owned:

| # | Gate | Site | Fires when |
| --- | --- | --- | --- |
| G1 | **No tool allowlist injected** | `router.py:1476` | `request.tools` non-empty and `tool_allowlist` empty. `build_live_composition` calls `build_model_binding` without one (`composition.py:490-494`, factory at `:360`). Refusal: `MALFORMED_PAYLOAD`, "tools were requested but no tool allowlist is declared — the capability plane owns that allowlist and none was injected". |
| G2 | **Model does not advertise tool calls** | `router.py:1610` (`_unmet_needs`) | `request.tools` non-empty and `profile.supports_tool_calls` false. `CloudModelSpec.to_profile()` hard-codes `supports_tool_calls=False` (`composition.py:215`), and `CloudChatProvider.__init__` refuses a profile that advertises `True` (`cloud.py:488`). |
| G3 | **The contract never asks for the field** | `run.py:290-302` | `tool_calls` ∉ `structured_fields`. |

So there are two ways forward and they are not equivalent:

- **Path A (recommended): stop using `ModelRequest.tools` as the advertisement.** The
  runtime sets `tools=()`; the capability ids reach the model through the *prompt*
  (which is where the contract already asks for the field), and `allows_tool_calls`
  becomes a runtime policy rather than a model capability. G1 and G2 become
  unreachable for Hermes callers — they remain correct guards for any caller that
  does set `tools`, and the router is not weakened.
- **Path B: make the seam advertise.** Pass `tool_allowlist` from the registry, set
  `supports_tool_calls=True` in `to_profile()`, delete the constructor refusal at
  `cloud.py:488`, and let G3 alone prompt the field. This is fewer edits but it
  makes the provider's published invariant ("this seam never advertises them")
  false while the dialect body still carries no native tool definitions — an
  advertisement the wire does not honour.

Path B is rejected on that asymmetry: the router would *believe* a capability the
transport never exercises. Path A's cost is one runtime edit (`_model_request`),
which §7.2 states and justifies, plus finding F1 in §8.

## 2. §2 verification — does the contract prompt `tool_calls`?

The contract is `output_contract_for(spec)` (`run.py:283`): three fixed fields
(`kind`, `rationale`, `payload`) plus one `array` field per
`model_policy.structured_fields` entry (`_CONTRACT_SECTIONS`, `run.py:236-240`).
`render_system` then renders exactly those fields as prompt lines
(`cloud.py:225-252`). Measured at this base (`load_profiles()` →
`output_contract_for` → `render_system`):

| Profile | `allows_tool_calls` | `structured_fields` | declared `tools` | contract prompts `tool_calls`? |
| --- | --- | --- | --- | --- |
| `critic` | true | `[proposals, tool_calls]` | `evidence_inspect, contradiction_scan` | **yes** |
| `experimenter` | true | `[proposals, tool_calls, delegations]` | `experiment_execute, artifact_store` | **yes** |
| `planner` | true | `[proposals, delegations]` | `graph_read, artifact_store` | **no** |
| `researcher` | true | `[proposals, tool_calls]` | `source_search, source_fetch` | **yes** |
| `synthesizer` | true | `[proposals, delegations]` | `artifact_store, provenance_read` | **no** |
| `verifier` | false | `[proposals, delegations]` | `evidence_inspect, statistic_check` | **no** |

**Answer: three of six.** The charter's "all six shipped profiles do" is not what
the files say (`verifier.yaml:16`, `planner.yaml:17`, `synthesizer.yaml:16`).
Rendered system text for `verifier`, verbatim (this is the whole schema the model
is given):

```
Reply with exactly one JSON object and nothing else: no prose and no code fences. Its fields:
- kind (string, optional)
- rationale (string, required)
- payload (object, optional)
- proposals (array, optional)
- delegations (array, optional)
The "kind" field names the proposal kind.
The "rationale" field must be non-empty.
```

Three consequences, and the third is the one the charter will care about most:

1. For `planner`, `synthesizer` and `verifier` a compliant model **never** emits
   `tool_calls`; the slice is moot for those three until their
   `structured_fields` change (a profile-data edit, not a code edit — §12 R2).
2. `verifier` declares two tools **and** `allows_tool_calls: false` — two
   statements that disagree. Until this slice the disagreement was invisible
   because the runtime consulted neither: the only gate was `spec.tools`
   (`run.py:1158` — finding F4).
3. **A model that emits `tool_calls` anyway is refused wholesale for the three
   profiles that do not list it** — and its tool calls still run. See F4.

### 2.1 A second gap: the prompt never names a capability

`_build_call` puts the request's tool names into the provider payload
(`router.py:1672`, `"tools": sorted(request.tools)`), and `CloudChatProvider.invoke`
reads exactly `payload["prompt"]`, `payload["rationale"]` and
`call.output_contract` (`cloud.py:514-530`). `payload["tools"]` is dead data at the
cloud seam. So even for `researcher` the model is told *that* a `tool_calls` array
exists and never *which* `capability_id` values are legal (or what arguments they
take). A live model would have to guess; the falsifier's scripted reply does not.

OPS-5 must therefore carry one new prompt section — the declared capabilities and
their input schema, sourced from the registry's own declarations, rendered from a
new `payload["tool_schema"]` by `render_system`. Without it the slice passes its
falsifier and fails in the field. This is a real addition to the charter's
falsifier list (§10, F1-schema).

## 3. C1 — where the capability port comes from

### 3.1 The supply problem, stated first

The charter assumes a "shipped capability set". There is none. At this base:

- `CapabilityInvoker(...)` is constructed in exactly two places: `eval/hostile.py:670`
  (tools `svc.echo`, `svc.scoped`) and test files.
- `Tool(...)` constructions exist only in `eval/hostile.py:638,641` and
  `eval/extensions.py:221` (`ExampleTool`).
- Zero of the ten ids named by the profiles — `source_search`, `source_fetch`,
  `evidence_inspect`, `contradiction_scan`, `graph_read`, `artifact_store`,
  `provenance_read`, `statistic_check`, `experiment_execute` — resolves to a tool
  or an executor anywhere under `src/`.

The plane is therefore not "missing a port" in the sense of a forgotten argument;
it has never executed anything outside the hostile rig. C1 is a *supply* decision
disguised as a wiring decision.

### 3.2 What each declared capability would require

| Capability | Plane-legal today? | Why |
| --- | --- | --- |
| `source_search`, `source_fetch` | **yes, with care** | Network reach. **R5 (§14.2) supersedes the old ticket rule:** a `TOOL`-kind network capability is legal with `sandboxed=False` and records `in-process (no sandbox)`. The allowlisted transport, host pin, closed schema and timeout are the barriers (§4). |
| `evidence_inspect`, `contradiction_scan`, `graph_read`, `provenance_read`, `statistic_check` | **no** | These read the project's durable evidence. `ToolCallContext` carries `capability_id, tool_id, idempotency_key, lease_generation, profile, deadline_monotonic, scratch_dir` (`types.py`, pinned by the `capability_escalation` probe in `eval/hostile.py`) — no connection, no repository, no evidence view, by design. A tool can only see its arguments (≤ 4 KiB), and the run's own evidence is not among them. |
| `artifact_store` | **no** | An artifact store *writes*. `_authorize` refuses `mutating=True` with `ROLE` (`invoke.py:550`), and the plane's contract is that a capability never authors state. |
| `experiment_execute` | **no** | Needs `CapabilityKind.SANDBOX` + `sandbox_enabled=True`; `config/hermes.toml:47-58` ships `enabled = false`, and the invoker answers `SANDBOX_UNAVAILABLE` (`invoke.py:408-414`). No sandbox exists. |

So OPS-5 can honestly supply **two of ten**. The other eight are blocked by design
decisions the plane made deliberately (no ambient authority, no mutating tools, no
sandbox), not by missing glue. Either a later slice gives the plane a *read-only
evidence port* and a sandbox, or those declarations stay inert.

### 3.3 Decision — C1a, per-`agent_profile` grants, withheld-and-named

- **The registry** is built in `composition.py` from a code-owned declaration table
  (`_CAPABILITY_DECLARATIONS`): for each supplied capability, one `Tool` (with its
  closed input schema and risk), one `Capability`, one `ToolSet`
  (`set.research_egress`), and one executor. The allowlist passed to
  `CapabilityRegistry` is exactly the supplied id set — so registry membership
  equals allowlist membership by construction, and `drift_report()` is empty by
  test, not by hope.
- **Grants** are derived per `agent_profile`: the union of `spec.tools` over every
  profile bound to it, intersected with the supplied set; `tool_set_ids` is the
  tool set that contains them; `max_risk` is the maximum declared risk. This is
  forced by the key the runtime uses (`run.py:1201`, `_grants.get(spec.agent_profile)`)
  and the key the invoker checks (`invoke.py:514`, `grant.profile != request.profile`
  against `spec.agent_profile`). Per-profile-name grants are not expressible today.
  Today's two collisions are harmless because the runtime narrows first
  (`run.py:1158`, `capability_id not in spec.tools`): `DIRECTOR` (planner +
  synthesizer) and `ADVERSARY` (critic + verifier) each share exactly one
  capability (`artifact_store`, `evidence_inspect`) that both profiles declare.
  The note records this rather than adding a fourth authority axis.
- **`authority.allowed_capabilities` is redundant and stays that way.** The loader
  refuses a declaration outside `tools` (`config.py:507-513`), and no runtime path
  reads it. `tools` is the one source of truth the runtime enforces; grants derive
  from it, and the note does not introduce a third list.
- **A profile whose declared `tools` exceed the supplied set** is composed
  **without a grant and with its `tools` narrowed to the empty tuple for that run**,
  and the withheld pairs `(profile, capability)` are returned on
  `LiveComposition.withheld` and printed once:
  `capabilities: 2 supplied (source_search, source_fetch); withheld — planner: graph_read, artifact_store; …`.
  Nothing reaches call time to be refused: the stage cannot name what it does not
  declare, and it is not prompted for `tool_calls` either. This is the
  `UNSUPPLIED_TOOL_POLICY = "withhold"` constant in `composition.py`; the
  alternative value, `"refuse"`, raises `CompositionError` naming every pair.

### 3.4 Rejected alternatives, costed

| Option | Cost | Verdict |
| --- | --- | --- |
| **C1b — fixed minimal set for every profile** | Cheapest to build (one set, one grant, one loop). But it *discards* the pinned declarations: `critic` would be granted `source_search`, which its authority block never declared, and `run.py:1158` would then refuse every such call as outside its declared tools — so the grant buys nothing and the over-grant is visible only in the envelope. It also makes the registry's allowlist disagree with the profiles, which is precisely the drift `drift_report()` exists to catch. | rejected |
| **C1c — operator-configured list** | Turns an authority surface into config. The codebase's posture is the opposite one, twice: `_MODEL_REGISTRY` and `_DIALECT_HOSTS` are code-owned *because* a config value that names a credential target or a reach is a hole (`composition.py:105-123`). A `[capabilities]` table would be the same hole with a different name, and `allowlist_from_config`'s "narrow-only" rule would have nothing to narrow. | rejected |
| **C1a-strict — hard `CompositionError` on any unsupplied declaration** | The charter's literal wording. Measured cost: five of six profiles fail (`critic`, `experimenter`, `planner`, `synthesizer`, `verifier`), so every methodology — `LITERATURE_REVIEW_DOCUMENT` runs planner, researcher, experimenter, verifier, synthesizer, critic (`methodology/workflows.py:332-344`) — refuses to compose. Live mode would be reachable only for a RESEARCHER-only workflow, i.e. OPS-1 is effectively reverted in the slice that was meant to extend it. | rejected **as the default**, kept as `UNSUPPLIED_TOOL_POLICY = "refuse"` for a one-constant ruling |
| **C1a-withhold (recommended)** | Live runs keep working; the two research profiles (`researcher` 2/2, and `critic` once its declaration is reconciled) gain real observation; every withheld pair is named in the run output and in the vector, so silence is impossible. The cost is that "declared" and "usable" differ for four profiles, which the note makes loud rather than latent. | **accepted** |

### 3.5 What refuses at composition

- A declared capability with **no declaration in the registry** → the withheld path
  above names it, or `"refuse"` raises `CompositionError` with
  `profile 'planner' declares capability 'graph_read', which the capability plane does not supply`.
- A **supplied** capability whose declaration is incoherent (a `Tool` with no
  input schema, a `ToolSet` naming an unregistered id) → `CapabilityRegistry`
  raises at registration (`registry.py:105-232`), before the database is opened.
- A profile whose `tools` and `allowed_capabilities` disagree → the loader already
  refuses (`config.py:507-513`), unchanged.
- An executor missing for a registered tool → **not** a composition error today: the
  invoker answers `NOT_CONFIGURED` at call time (`invoke.py:823-828`). OPS-5 closes
  that gap at the registry boundary instead: the declaration table and the executor
  table are built from one literal, and a test asserts
  `set(implementations) == {tool ids}`.

## 4. C2 — the egress surface (the reason this is a gate)

### 4.1 What can be contacted

Two capabilities reach the network. Both go through the shipped live-fetch path:

```
source_search / source_fetch (capability)
  → executor  (composition-built; wraps ProviderMachinery)
    → _AllowlistedTransport            live_fetch.py:91   (EgressPolicy.vet → scheme, userinfo,
                                                             origin incl. explicit port, DNS
                                                             all-public, address pin)
      → ProviderHTTPTransport          (per-call timeout, size cap)
        → RecordedTransport            (record mode, journaled provider_interaction)
          → OpenalexAdapter | PubmedAdapter
```

The host set is **code-owned** and exactly four names
(`research/live_fetch.py:82-87`):

| Host | Provider | Use |
| --- | --- | --- |
| `api.openalex.org` | OpenAlex | search + fetch API |
| `openalex.org` | OpenAlex | canonical record source_url |
| `eutils.ncbi.nlm.nih.gov` | PubMed | E-utilities |
| `pubmed.ncbi.nlm.nih.gov` | PubMed | canonical record source_url |

`allowlist_from_config` (`live_fetch.py:209-256`) accepts an operator entry only if
its parsed host is already in that tuple, and refuses anything else loudly. Config
may **narrow**; config may never widen. An empty config yields the full set.

### 4.2 What "in-process with the sandbox disabled" means here

`config/hermes.toml:54` ships `[sandbox] enabled = false`. OPS-5 does not change
it, and a capability call runs in the **controller's own process**:

- no process isolation, no filesystem jail, no CPU/memory cap applied by the
  sandbox. `[sandbox] enabled` is read in exactly one place — `hermes doctor`
  (`cli.py:98`) — and `cpu_limit_seconds` / `memory_limit_mb`
  (`config.py:58-59`) are read nowhere at all; the capability plane takes
  `sandbox_enabled` as an injected boolean (`invoke.py:356`) and OPS-5 passes it
  `False`, because nothing exists to pass `True` to;
- the only barriers between the model's arguments and the outside world are the
  tool's closed input schema, `EgressPolicy.vet`, `HostPinnedTransport`, and the
  transport's timeout — in that order;
- the model **can** name a host: `source_fetch`'s declared inputs include a record
  URL/identifier, so an out-of-surface host is expressible. It is refused by
  `vet` before a dial (see §4.4).

**Finding F5, for the Director.** To pass the authority step, a network tool must
declare `sandboxed=True` (`invoke.py:558`), because `Tool.accepts_no_side_effects()`
is false for `network=True`. But `sandboxed` is a *declaration used as a
permission ticket*: the execution path consults `sandbox_enabled` only for
`CapabilityKind.SANDBOX` (`invoke.py:408-414`), so a `TOOL`-kind capability declaring
`sandboxed=True` executes even with the sandbox absent. OPS-5 must set that flag to
be legal at all, and it would be dishonest to leave the claim unqualified. The note
therefore requires the tool summary, the invocation envelope's `environment`
(`Tool.environment`, currently `""`) and the run's capability line to say
`in-process (no sandbox)`; the plane's conflation is recorded as debt for a
follow-on gate, not fixed here (fixing it is a plane change, not a port).

> **Superseded by R5 (§14.2).** The flag is **not** set. A `TOOL`-kind
> capability with network reach is legal with `sandboxed=False`; the envelope
> records `in-process (no sandbox)`. `sandboxed` remains required for a
> `SANDBOX`-kind capability's tool (`registry.py:167`, unchanged).

### 4.3 Where a live tool's egress is recorded

This is the question the charter does not ask and the slice cannot avoid. A
capability call produces an `InvocationEnvelope` in memory and a `ToolFeedback`
record in the run's state. It does **not** reach the journal unless something
writes. Two options:

| Option | What it means | Cost / risk |
| --- | --- | --- |
| **C2-i — reuse the persisting sink (recommended)** | The executor is built with the composition's `conn`/`store`/`clock`, exactly as `build_live_fetch_wiring` does (`live_fetch.py:372`), so `RecordedTransport` journals each interaction as `provider_interaction` through `make_persisting_sink` — an existing certified owner, no new transaction, no new SQL. Replay fixtures can then be produced from a live run, which is the invariant the provider seam exists for. | The executor closure holds a connection. The invoker still holds none (`invoke.py:339-347`), but a tool implementation now reaches a writer through an existing path. That is a *new caller* of an old writer, and the Director should say so explicitly. |
| **C2-ii — in-memory only** | No `sink`; the envelope and the run's digest are the only record. | A live capability's egress becomes unreplayable and unjournaled — a second egress path with weaker discipline than the task path. Rejected: it makes "recorded/transcript provider replay" false for the new surface. |

`make_persisting_sink` is not a new acquisition owner, and it opens no transaction
control call at all: it hands the interaction to `ProviderInteractionRepository`
(`persistence/provider_interactions.py:32`), whose `record` issues a plain
`INSERT` on the caller's connection, and writes the body bytes to the artifact
store. The census counts executed `BEGIN`/`COMMIT`/`ROLLBACK`/`SAVEPOINT`/`RELEASE`
calls, so this path cannot move a certified figure — it adds none (§9).

One binding requirement falls out of that: `persist_interaction` refuses an
interaction with no `project_id` (`provider_interactions.py:167-171`), so the
executor must bind `project_id` on the recorded transport exactly as the source
handlers do, and must bind a task-shaped linkage id. `ToolCallContext` carries no
task id, so the derivation uses the call's own `idempotency_key` — a value the
plane already computes deterministically from `(run_id, tick, index,
capability_id)` (`run.py:1196-1200`), never an authored identity.

### 4.4 A host outside the allowlist

Refused at `_AllowlistedTransport.request` → `EgressPolicy.vet` raises
`EgressRefused` → re-raised as `ProviderValidationError`. Inside the executor that
is an exception; `_execute` catches any exception at the tool boundary and records
`FAILED / TOOL_ERROR` with only the exception **class** (`invoke.py:843-848` — the
text is deliberately not recorded, since it can embed arguments). The run then
terminates exactly as C4 says (§6). This is deliberate and matches the existing
source-handler behaviour: an unallowlisted host is a wiring error, not a retryable
outage.

### 4.5 Capabilities that never leave the machine

| Capability | Local? | Evidence |
| --- | --- | --- |
| `evidence_inspect` | local — and **unsupplied** | no implementation; `ToolCallContext` carries no evidence view |
| `contradiction_scan` | local — unsupplied | same |
| `graph_read` | local — unsupplied | same |
| `provenance_read` | local — unsupplied | same |
| `statistic_check` | local — unsupplied | pure computation over arguments if ever implemented; no egress |
| `artifact_store` | local — **structurally impossible** | `mutating=True` tools are refused `ROLE` (`invoke.py:550`) |
| `experiment_execute` | local — **unavailable** | needs `sandbox_enabled`; ships `false` (`invoke.py:408-414`) |
| `source_search`, `source_fetch` | **remote** | four hosts, §4.1 |

I checked each one rather than assuming: the local six have no implementation at
this base, so their "never leaves the machine" property is currently vacuous — the
note claims nothing more than that no code path exists which could emit egress for
them, and that any future implementation must go through the same
`_AllowlistedTransport` if it ever needs one.

## 5. C3 — make M2 real

`RecordingCapabilityPort` (`eval/loop_observations.py:194-218`) records
`(capability_id, sha256(canonical arguments))` before delegating. OPS-5 wires it
**between the invoker and the runtime**:

```
CapabilityInvoker  →  RecordingCapabilityPort  →  AgentRuntime(capabilities=…)
                                                      ↑ one recorder per composed run
LiveVector(capabilities=recorder) ────────────────────┘  (render reads .calls)
```

- **One recorder per composed run**, per `collect_scenario`'s contract
  (`loop_observations.py:315-322`): the recorder is created in
  `build_live_composition`, held by `LiveVector`, and passed to every stage's
  runtime through the handler. A per-stage recorder would make each stage's M2 a
  slice of the run and the vector's aggregate a sum of unmeasured parts.
- **M2 is a number** for every run whose path includes the port. A run with zero
  tool calls reports `tool_calls=0, repeat_tool_rate=0.0` — a *measurement* of
  zero, which is what `scenario_metrics` computes over an empty sequence
  (`loop_metrics.py:125-140`), not the `n/a` sentinel.
- **`n/a` survives exactly where the port is absent**: the withheld profiles
  (§3.3). `LiveVector._render` currently hard-codes `M2=n/a`
  (`eval/live_vector.py:103`); it must render a number when the recorder saw any
  run, and `M2=n/a` only when the composition held no port at all. The distinction
  is stated in the line, e.g. `M2(calls=3,repeat=0.667)` or
  `M2=n/a (no capability port on this run)`.

What cannot be wrapped: a stage driven by a caller that builds its own
`RuntimeWiring` (every non-live caller). Those keep `n/a`, which is already the
collector's honest answer.

## 6. C4 — what a refused tool call means, today

No behaviour changes in this slice. The current rule is stated in `_one_tool_call`'s
own docstring (`run.py:1129-1155`) and is two-tiered:

| Condition | Refusal code | Batch | Run | Recorded as |
| --- | --- | --- | --- | --- |
| `tool_calls` is not a list of mappings | `MALFORMED_PAYLOAD` | refused whole | continues | refusal |
| batch size > `max_tool_calls` | `MALFORMED_PAYLOAD` | refused whole | continues | refusal |
| unknown key in a call | `MALFORMED_PAYLOAD` | refused whole | continues | refusal |
| no `capability_id` | `MALFORMED_PAYLOAD` | call skipped | continues | refusal |
| `capability_id` ∉ `spec.tools` | `ROLE` | call skipped | **continues** | refusal + `TOOL_SKIPPED` + feedback |
| no capability port wired | `ROLE` | call skipped | **continues** | refusal + `TOOL_SKIPPED` + feedback |
| arguments not a mapping | `MALFORMED_PAYLOAD` | call skipped | continues | refusal |
| **plane refused** (`CapabilityRefusal`: no grant, no tool set, ceiling, approval, sandbox, idempotency conflict, malformed) | plane's code | stops | **`FAILED` / `TOOL_FAILED`** | refusal + `TOOL_FAILED` + feedback |
| **observation failed** (`Observation.failure`: TOOL_ERROR, TIMEOUT, HAZARD, RATE_LIMIT*, SANDBOX_UNAVAILABLE, NOT_CONFIGURED, REDACTION_DENIED) | `MALFORMED_PAYLOAD` + failure detail | stops | **`FAILED` / `TOOL_FAILED`** | refusal + `TOOL_FAILED` + feedback |

Downstream, deterministically (`methodology_driver.py:542-546`): the stage's run is
not recorded, the chain stops, and the methodology's `termination` becomes
`TOOL_FAILED`. The handler then returns `status="completed"` if any *earlier* stage
admitted an intent, with the termination named in the reason
(`task_handlers/__init__.py:332-350`). **This is a wart worth ruling on later**: a
run whose later stage failed still reports `completed` at the task level. OPS-5 does
not change it (invariant 6), and the note records it as finding F6 so it is not
mistaken for this slice's behaviour.

**Is it what we want?** For a *plane* refusal or a failed observation, yes: the
work the run declared could not be done, and reporting a proposal set built beside
it would misstate the run. For a *grant or declaration* mismatch, the skip-and-tell
form is also right — it is the model's mistake, the run keeps its other work, and
LOOP-2 feeds the refusal back into the next tick. The one asymmetry OPS-5
introduces is that a **withheld profile never reaches that branch** (no grant, no
declared tools → the call is refused at `spec.tools` inspection), so the new supply
decision cannot create a fatal path that did not exist.

Terminal states the three falsifiers ride:

| Falsifier | Plane outcome | Run state | Task outcome |
| --- | --- | --- | --- |
| scripted `tool_calls` for a supplied capability | `Observation OK` | `SUCCEEDED` (terminal per profile) | completes; M2 numeric |
| a declared-but-unsupplied capability | withheld at composition; call refused `ROLE` as outside `spec.tools` | continues | completes without that stage's tool |
| fetch to a host outside the allowlist | `Observation FAILED(TOOL_ERROR)` | `FAILED/TOOL_FAILED` | stage not recorded; methodology terminates `TOOL_FAILED` (see F6 for the task-level label) |

## 7. C5 — profiles

### 7.1 `_model_only_profiles` is deleted

Its docstring contains the false premise ("The cloud provider refuses a reply that
carries a tool call") and its effect is a blanket narrowing that would make C1
inert. It is replaced by two things:

1. `_grantable_profiles(profiles, supplied)` — narrows a profile **only** when its
   declared tools exceed what the registry supplies, returns `(profiles, withheld)`,
   and is the single place the withheld pairs are computed (§3.3).
2. The runtime rule in §7.2.

The docstring's first sentence is corrected in place (this is the correction the
charter's §2 asks for): the provider refuses **native** tool-use blocks; the
runtime's tool path is a JSON field, which it does not refuse.

### 7.2 The one runtime edit, and why it is load-bearing

`_model_request` currently sets
`tools=tuple(spec.tools) if allows_tool_calls else ()` (`run.py:1573`). That field
is consumed by the router as *"this request requires a model that advertises native
tool calls"* (`router.py:1610`) and by `_require_contract` as *"a capability-plane
allowlist must be injected"* (`router.py:1476`). Both readings are wrong for this
path: the model is not being handed native tool definitions, it is being asked for
a JSON array.

So: **`tools=()` unconditionally**, and the capability ids move to the prompt
(§2.1). Two guards remain and are not weakened — they still fire for any caller
that sets `tools`, which is now only a test or a future native-tool seam.

The runtime rule that replaces the narrowing: a tool batch executes only when
**both** `spec.model_policy.allows_tool_calls` and `"tool_calls" in
spec.model_policy.structured_fields`. This closes F4 (a `verifier` reply could
execute `evidence_inspect` while claiming `allows_tool_calls: false`) without
touching the profile files, and it makes `structured_fields` mean what it says: the
field the contract asks for is the field the runtime will read.

### 7.3 The three gates, after this slice

| Gate | Before | After |
| --- | --- | --- |
| contract prompts `tool_calls` | `structured_fields` | unchanged (profile data — §12 R2) |
| runtime executes a batch | `capability_id ∈ spec.tools` | `allows_tool_calls ∧ tool_calls ∈ structured_fields ∧ capability_id ∈ spec.tools` |
| plane authorises a call | grant + tool set + ceiling + approvals + non-mutating | unchanged |
| "a stage declares no tools" | narrowing was **not** a no-op for `verifier` (already false) and was a *silent* no-op for the other five in the sense that execution depended on `spec.tools` alone | the narrowing is gone; a stage that declares no tools has `tools=()` and is never prompted for the field, so the batch is unreachable by construction |

## 8. Findings recorded, not fixed

| # | Finding | Consequence for OPS-5 |
| --- | --- | --- |
| **F1** | `ModelRequest.tools` is semantically overloaded: the runtime means "what this stage may call", the router means "native capability this model must have". | §1.2 Path A: stop setting it; correct the field's docstring in the same commit. |
| **F2** | `_model_only_profiles`'s stated reason is false for the JSON path (the charter's §2 correction). | Delete the function; correct the sentence where it lands. |
| **F3** | The prompt never names a legal `capability_id`; `payload["tools"]` is dead at the cloud seam. | §2.1: one new prompt section, sourced from the registry. |
| **F4** | `_tool_phase` executes `tool_calls` even when `structured_fields` does not list it, and even when the same reply was refused wholesale by `_validate_drafts` (`run.py:901-909`) for declaring that key. | §7.2's two-condition gate. |
| **F5** | `Tool.sandboxed` is a permission ticket, not an enforcement: a `TOOL`-kind network capability executes with `sandbox_enabled=False`. | **Superseded by R5 (§14.2):** the flag is NOT set; a `TOOL`-kind network capability is legal with `sandboxed=False`, and the envelope records `in-process (no sandbox)`. |
| **F6** | A methodology whose later stage failed still reports `completed` at the task level when an earlier stage admitted. | Out of scope; recorded for a LOOP/methodology gate. |

## 9. Invariants, and how each is upheld

| Invariant | How |
| --- | --- |
| **Drain-only byte-identical, still booby-trapped** | No code path changes when `[model_tiers]` is empty or `--drain-only` is given: composition is never entered, `ProviderHTTPTransport` is still monkeypatched to `pytest.fail` in the regression tests, and the recorded output stays byte-for-byte (`test_ops1_live_cli.py:DRAIN_ONLY_OUTPUT`). |
| **Single mutation path** | Tools return `Observation`s. They propose no intent, hold no `IntentApplier`, and the one write they can cause is a `provider_interaction` row through the existing persisting sink (C2-i) — an existing owner, not a new one. |
| **Native `tool_use` blocks stay refused** | `_tool_refusal` (`cloud.py:293`, `:385`, `:445`) is untouched; §1.2 Path A *avoids* the change that would have weakened the provider's advertisement guard. |
| **Census unchanged** | 124 / 28 (19/5/4) / 1 / 15 / 0. The slice adds no `BEGIN`, no `COMMIT`, no `ROLLBACK`, no `SAVEPOINT`, no `RELEASE`; the persistence sink rides `ProviderInteractionRepository`. `scripts/check_census.py` is the check. |
| **Keys never printed** | Model keys stay in the environment and in `Credential`; the capability path never touches them. The tool's `_secret_in` scan (`invoke.py:971`) applies to observations, and the envelope redacts inputs. The note requires the run's capability line to print ids and counts only. |
| **No new writer, no new transaction, no runtime change beyond the port** | One runtime edit (`_model_request`'s `tools`, §7.2) plus one `_tool_phase` condition, both justified as what the port needs to be reachable at all. No new table, no new event kind, no schema version change. |

## 10. Falsifiers → tests (`tests/test_ops5_capabilities.py`)

| Falsifier | Test shape | Assertion |
| --- | --- | --- |
| Live-shaped run with a scripted `tool_calls` reply | `hermes run` against a temp DB, scripted `_ScriptedTransport` returning a reply with `proposals` + `tool_calls[source_search]`, a stubbed executor | the executor ran once; the next tick's prompt contains a `<untrusted origin="runtime.observation" ...>` envelope; `vector:` prints `M2(calls=1,repeat=0.0)` — a number |
| Unsupplied declaration | compose with `UNSUPPLIED_TOOL_POLICY = "refuse"` | `CompositionError` names the profile and the capability |
| Unsupplied declaration (default policy) | compose with `"withhold"` | `LiveComposition.withheld` contains the pair; the CLI prints it; the profile's runtime tools are empty |
| Host outside the allowlist | executor built over a recording transport whose inner refuses; call `source_fetch` with `https://evil.example/x` | `EgressRefused`-derived refusal recorded; run `FAILED/TOOL_FAILED`; journal has the failure, not a request |
| Drain-only | the OPS-1 regression test, unchanged | byte-identical output; model plane never constructed |
| Native `tool_use` in a reply | anthropic reply with `{"type":"tool_use"}` | `_tool_refusal` (unchanged), run `MODEL_REFUSED` |
| No key material in any output | scan `capsys` + ledger + vector for the key literal | absent |
| F4 closed | `verifier` reply carrying `tool_calls` | refused as an unknown key; the executor is **not** called |
| Registry coherence | build the plane | `drift_report() == ()`; every registered tool has an executor; every grant's capability is in a tool set it opens |

## 11. Gates (implementation phase)

1. `test_ops5_capabilities` (new), `test_ops1_live_cli`, `test_cloud_provider`,
   `test_loop_observations`, `test_loop_baseline`, `test_p_auto_3_live_fetch`,
   `test_b4_ref_graphs`, `test_census_check`.
2. `scripts/run_tests.py` (full) under the heavy-gate lock.
3. `scripts/stamp_suite_count.py` then `--check`.
4. `scripts/check_census.py` — unchanged.
5. `scripts/run_tests.py tests/test_b4_ref_graphs.py` — 24; regenerate only if a
   governed doc moves. **Expected to move**: `docs/STATE.md`'s "live mode is
   model-only" sentence and `docs/API.md`'s run contract both become false when
   capabilities are wired. That is a governed edit — the B4 regeneration is part of
   the implementation commit, not a side effect, and this note says so before the
   fact.
6. `uvx ruff check src tests scripts`; `uvx pyright src`; pyright with
   `pyrightconfig.tests.json`.

## 12. What I could not decide from the tree

| # | Ruling needed | Why the tree cannot settle it | Recommendation |
| --- | --- | --- | --- |
| **R1** | Egress report: does a capability call journal `provider_interaction` rows (C2-i) or stay in-memory (C2-ii)? | Both are consistent with the census; only one is consistent with "recorded/transcript provider replay" for the new surface. It is a security-adjacent choice, which is this gate's whole subject. | **C2-i** |
| **R2** | Do `planner`, `synthesizer`, `verifier` gain `tool_calls` in `structured_fields` in this slice? | It is profile *data*, and it decides whether three of six profiles participate at all. Adding it would make them prompt for tools they cannot be supplied (§3.2) — increasing surface for no gain. | **No** in OPS-5; revisit when a read-only evidence port exists. |
| **R3** | `UNSUPPLIED_TOOL_POLICY`: `"withhold"` or `"refuse"`? | The charter says "refuse at composition"; the tree says that reverts OPS-1 for five of six profiles. This is a scope decision, not a fact. | **`"withhold"`**, with `"refuse"` one constant away |
| **R4** | Does a capability's fatal refusal *need* to terminate the run (C4), now that it is reachable? | The current rule is certified by LOOP-4 E7; changing it is a separate gate. The behaviour is defensible as-is. | **Keep**, record F6 separately |
| **R5** | Is the `sandboxed=True` declaration on an in-process network tool acceptable, given F5? | The plane offers no alternative that permits egress, and fixing the conflation is a plane change the charter's invariant 6 excludes. | **Accept with a qualified envelope**, file the plane debt |

The one thing I want the Director to read twice: OPS-5 as scoped supplies **two**
capabilities, and the profiles that can actually observe are `researcher` and
`critic` (the latter only if R2 is answered yes later). Everything else is
withheld and named. A live run after this slice is "able to research" in the narrow
sense of *search and fetch admitted sources* — not "able to read the project's own
evidence", which needs the read port that does not exist.

## 13. Claim boundary

This note claims: the measured profile/contract table (§2), the three blockers
(§1.2), the absence of implementations (§3.1), the plane-legality matrix (§3.2),
and the egress and failure tables (§4, §6) are what this tree does at `c57465b`.
It does not claim that a live model will reliably emit a well-formed `tool_calls`
array — that depends on the prompt section §2.1 adds, and the falsifier that proves
execution is *scripted*, as the charter specifies. It claims no scientific
validity, no replay-as-validity, and no capability to decide anything: every tool
observation is evidence, every proposal still crosses `apply_intent`.

## 14. Phase 2 rulings (2026-10-24)

Status: **RULED**. These rulings supersede §12's recommendations where they
differ. Phase 2 is split: **OPS-5A** (the two capabilities, the egress path and
the sandbox-flag correction) lands first; **OPS-5B** (composition wiring, grants,
withholding, the recorder, M2) follows only after 5A lands. They are not mixed in
one commit series.

### 14.1 Three corrections to the Director's charter

1. **Only three of six profiles prompt `tool_calls`** — the charter said all six.
   The Director misread the declaration table. `planner`, `synthesizer` and
   `verifier` declare `proposals` and `delegations` only.
2. **No capability set ships.** Zero of the ten declared ids has a `Tool` or an
   executor in `src/`; the only wired invoker is the hostile-evaluation rig. The
   charter assumed the registry had contents. **C1 is a supply decision, not a
   wiring decision.**
3. **The charter's "the missing port is the blocker" was incomplete** — three
   code-owned gates sit in front of a tool-bearing call (`router.py:1476`,
   `composition.py:215`, `cloud.py:488`, `run.py:290`).

### 14.2 Rulings

#### R1 — egress journals through the existing sink: **yes**

A network act that is not journaled is unobservable, and this project's posture
is that the record says what happened. Constraints, all mandatory:

- the journal row carries **refs and digests only** — never the fetched body,
  never a query string containing a credential, never a response excerpt;
- the existing 4 KiB event cap is respected (the row is metadata, not payload);
- a refusal (out-of-allowlist host) is journaled too, with the host and the
  reason.

#### R2 — do not widen the contract: **no**

`planner`, `synthesizer` and `verifier` do not gain `tool_calls` in this slice.
Note why it does not block: `researcher` — the only profile whose declared tools
leave the machine — already prompts the field. Widening a contract changes prompt
bytes for three profiles and needs its own measurement.

#### R3 — `withhold`, not hard refuse: **withhold, named, journaled**

A hard `CompositionError` fails five of six profiles (their declared local tools
cannot be supplied) and would revert OPS-1 in the slice meant to extend it. But
silence is not an option either: at composition, **one line per withheld
declaration**, naming the profile, the `agent_profile` and the capability; and a
journal event for the withheld set. The model may still ask for a withheld id —
that lands as the existing `ROLE` refusal, recorded.

#### R4 — terminal semantics: **unchanged**

A plane refusal or observation failure terminates `FAILED/TOOL_FAILED`; a grant
or declared-set mismatch is `ROLE`, recorded, and the tick continues. Do not
change this here. The wart you found — a later-stage `TOOL_FAILED` reporting
`completed` at the task level when an earlier stage admitted — is **recorded as
debt**, not fixed in this slice.

#### R5 — `sandboxed=True` on an in-process network tool: **NO. Fix the flag.**

Setting it would be a false record, the same class of error as "landed but
unreachable" — and this one is worse, because the field claims isolation.

The tree confirms your reading: `invoke.py:558` demands `sandboxed=True` for any
tool that does not accept no-side-effects, while `sandbox_enabled` is consulted
only for `CapabilityKind.SANDBOX` (`invoke.py:413`). So the flag is a
**permission ticket, not enforcement**.

**Ruling:** a `TOOL`-kind capability with network reach is **legal with
`sandboxed=False`**, provided that:

1. the egress allowlist applies (code-owned, config may narrow only);
2. the host pin, the closed request schema and the timeout apply;
3. **the record says `in-process (no sandbox)`** — in the ledger line and in any
   envelope detail that would otherwise imply isolation;
4. a test pins that a side-effecting tool **without** `sandboxed=True` is legal
   for `TOOL` kind and **illegal** for `SANDBOX` kind.

Do not weaken the `SANDBOX`-kind rule (`registry.py:167`). The distinction is:
*this tool runs in-process and we say so* versus *this tool requires isolation
and gets it*.

### 14.3 Implementation split

- **OPS-5A** — `source_search` and `source_fetch`, the R1 egress journaling path,
  and the R5 correction. No composition change: no registry wiring, no grants, no
  recorder.
- **OPS-5B** — registry + grants derived from `agent_profile`; the withheld set
  named and journaled (R3); the `RecordingCapabilityPort` between invoker and
  runtime so M2 is a number (C3); `_model_only_profiles` deleted (C5); the batch
  rule `allows_tool_calls AND tool_calls ∈ structured_fields`.
