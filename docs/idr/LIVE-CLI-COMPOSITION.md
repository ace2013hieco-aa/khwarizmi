# OPS-1 — let the CLI compose the live controller

| Item | Value |
| --- | --- |
| Task | OPS-1: `hermes run` should be able to compose the model plane it was built for |
| Base | `9054333` (`main`, rebased from the gate's `9f74279`) |
| Branch | `slice/ops-1-live-cli` |
| Phase | 1 — design gate; phase 2 — rulings recorded, implementation follows |
| Status | **RULED (2026-10-24)** — A2, B1, `--drain-only`, the durable-plus-vector reading of the trace, and the `STATE.md` wording; rulings below |

## Rulings (2026-10-24, Director) — phase 2

| # | Ruling | Effect |
| --- | --- | --- |
| **R1** | The per-invocation override is **`--drain-only`**, not `--dry-run` | The charter's `--dry-run` was wrong and is corrected here: the drain path writes (gates park, task rows transition), so a flag named `--dry-run` would lie about writes. §4 below is updated to the ruled name. |
| **R2** | The §4/§7 conflict was the **charter's**, and the gate's resolution stands | Live announces, drain-only is silent. The property this buys, and the reason it is the right resolution: **silence now means the model plane was never composed**, so "did this run spend anything?" is answerable from the output alone. |
| **R3** | "The trace is readable" means the **durable surfaces plus an in-process vector** | Durable: the journal (`hermes audit`, `IntentApplied` rows) and the binding's dispatch ledger (tier / provider / model / outcome / tokens). In-process: at **run end**, `loop_observations.collect_scenario(...)`'s primitives are collected and one `vector:` line is printed in live mode. Drain-only prints nothing extra. A collector failure never changes the run's exit code — it prints `vector: unavailable (<reason>)` and the run continues to its normal ending. |
| **R4** | The `doctor` model pre-flight is **OPS-2**, not OPS-1 | Nothing is added to `hermes doctor` in this slice. §10 item 3 is closed as deferred to OPS-2. |
| **R5** | The `STATE.md` replacement is approved, with the finding stated accurately | `docs/AUDIT-PLATFORM-MERGE.md` **does not exist** at this tree — fully dangling. `ROADMAP.md` **does exist** (56 lines, Step-4 regime roadmap); what does not exist is a **"Platform line" section** in it — dangling as a *section reference*. Drop both citations, saying which is which. Do not author citations to documents that live only on local branches. |
| **R6** | `docs/API.md` documents the new surface in the same slice | One regeneration covers both governed files (`STATE.md` + `API.md`): `b4-c1`/`c2`/`c4` move, `b4-c3` does not, edge sets stay `5/19/10/5`, **24 tests stay 24**. |

### R3 implementation reading (recorded so the ruling can be checked)

`collect_scenario` / `collect_run` operate on **one runtime run**: a `ProposalSet`, a
`CheckpointSurface`, and the `Supervisor` that holds the trace. None of those survive
`ctrl.run` — the handler builds a fresh `RuntimeWiring` per task dispatch and the wiring
is discarded with it. So the composition retains each stage's `(wiring, result)` in a
sink **during** the run, and the single hook **after `ctrl.run`** collects them: nothing is
computed inside the tick loop, and no runtime/controller file changes. Collection is at
run end, in-process, exactly as R3 requires. The sink is also where the `Supervisor` and
the `RecordingModelPort` live, so M0's trace digest and M1's prompt bytes come from the
objects that actually saw the run.

M2 is `n/a` in live mode by construction: the composed handler is given no
`capabilities` port, so no tool invocation can reach a recorder. Reporting `0.0` there
would be a claim nobody measured, and the collector's own discipline is `n/a`, never zero.

This note is the design gate, not the implementation. It decides where the
`CloudModelSpec` list comes from, what turns the live path on, how the run
reports what it did, and what the certified 2026-09-21 sentence in
`docs/STATE.md:162-171` becomes. It also records three things the tree says
that the charter does not: the two citations in that certified sentence are
already dangling at this base, `check_composition`'s "mismatch" branch becomes
structurally unreachable under the recommended option, and "the run's trace"
is not readable today without new plumbing.

## 0. Verdict summary

1. **Decision A — A2, a code-owned provider registry.** `[model_tiers]` stays
   the only operator surface: `provider:model` resolves through a shipped
   `provider_id -> (dialect, api_key_env)` table. The registry is an
   allowlist, and that is the point.
2. **Decision B — B1, non-empty tier refs turn the live path on, plus one
   per-invocation override — ruled `--drain-only` (R1).** The drain path still
   writes (gates park, task rows transition), so `--dry-run` would have been a
   name that lies about writes; the charter's flag name was corrected.
3. **Mode reporting has an internal conflict in the charter and I resolve it
   in favour of byte-identity.** §4 requires the summary to state the mode;
   §7 requires the drain-only path to be byte-identical to today's output.
   Resolution: **live announces itself, drain-only is silent.** Silence is
   the drain-only signal, and no line is added to any run that does not
   compose the model plane.
4. **The `STATE.md` sentence cannot stay true verbatim**, and it cannot be
   repaired by adding "when configured" alone — the earlier half ("the
   shipped CLI constructs the controller with no handlers") also becomes
   conditional. Exact wording in §5, with the B4 consequence and the
   pre-existing dangling-citation defect it inherits.
5. **"The run's trace is readable" — ruled (R3).** The runtime trace lives in
   a `Supervisor` created per dispatch inside the handler and is discarded with
   it (B-5: derived, deliberately not durable). Readable = the journal, the
   binding's **dispatch ledger** (tier, provider, model, outcome, tokens per
   attempt) **and** the in-process vector printed at run end. `Supervisor.trace`
   itself stays unreadable after the fact, by design.

## 1. The defect, verified at this base

- `cli._run` (`src/hermes/cli.py:473`) constructs `Controller` directly with
  `autonomy_operator=cfg.autonomy_caps` and **no** `task_handlers`. Its
  docstring states the posture plainly: "No model/handler injections exist at
  the CLI boundary, so execution is fail-closed by design."
- `composition.build_live_controller` (`src/hermes/composition.py:338`) does
  the whole job: `EnvCredentialResolver` → `CloudChatProvider` per provider →
  `bind_model_port` over `[model_tiers]` → `load_profiles` →
  `build_methodology_handler` → `Controller`.
- **There is no call site in `src/`.** The three `src` occurrences of the name
  are the definition, `__all__`, and the module docstring's usage example.
  The only call site in the tree is `tests/test_cloud_provider.py:647`, whose
  assertion is that the handler is registered — not that anything runs it.

So the model plane, the agent runtime and the methodology driver are built,
tested, and unreachable from the operator surface. This slice is the seam,
and only the seam.

## 2. What this slice turns on — and what it does not

`build_controller` registers exactly one handler template,
`methodology_run`. Therefore a live `hermes run`:

- **runs** `AGENT_TASK`s whose spec template is `methodology_run`, through the
  methodology driver, the agent runtime, the model plane, and
  `apply_intent` (the handler's orchestration is the controller's bound
  applier);
- **still leaves** `EXTRACT` tasks with the existing diagnostic
  (`extract_fn` is `None`);
- **still leaves** `GATE` tasks unhandled (`gate_verdict_fn` is `None`);
- **still parks** `HUMAN_GATE` tasks at `WAITING_HUMAN` — the controller
  resolves no verdict, and the CLI gains no gate surface;
- **composes no** `artifact_store`, grants, capabilities or sandbox, and
  **narrows every profile to `allows_tool_calls: false`** (a copy, never a
  profile-file edit). The cloud seam refuses a reply that carries a tool call,
  so the composition must not ask for one; with no capability port wired,
  nothing could execute it either. A live stage therefore runs on model
  drafting alone. This corrects a first reading of this bullet: an un-narrowed
  profile's request is refused by the router *before* any provider call
  (`MALFORMED_PAYLOAD`: no candidate serves a tool-declaring request from a
  model profile that does not advertise tools), so the refusal landed one layer
  earlier than "at the runtime's tool phase".

Consequence worth stating: a previously parked `methodology_run` task will
now execute on the next live run, and can move to `failed_typed` if its
document or plan is invalid. That is the intended behavior, and it changes the
summary's `failed` count for projects that hold such tasks.

## 3. Decision A — where the specs come from (recommend A2)

### A2 as proposed

A code-owned registry in `composition.py`, beside the builders that consume
it:

| `provider_id` | `dialect` | `api_key_env` | host |
| --- | --- | --- | --- |
| `anthropic` | `anthropic` | `ANTHROPIC_API_KEY` | canonical (empty override) |
| `openai` | `openai` | `OPENAI_API_KEY` | canonical (empty override) |

and one new pure resolver, `specs_from_tiers(cfg, *, environ=None)`:

1. `tier_refs_from_config(cfg)` (`composition.py:211`) — the existing
   convention, empty refs dropped.
2. For each ref: `parse_model_ref` (`router.py:658`), then registry lookup,
   then one `CloudModelSpec(provider_id, dialect, model_id, api_key_env)` per
   distinct `(provider_id, model_id)` pair. Tiers `s` and `c` may name the same
   pair; it yields one spec and two policy refs.
3. Every problem collected, then `check_composition` runs and its problems are
   merged, then **one** `CompositionError` naming all of them — the class's
   stated contract ("Names every problem at once").

Config is **byte-unchanged**: `[model_tiers]`'s documented comment
(`config/hermes.toml:40-45`) already says the only thing an operator must
learn. There is no second surface to keep in agreement with the first.

**Why A2.** A1 makes the operator declare a spec per provider *and* reference
it from a tier, which creates a config that can disagree with itself — and
`check_composition`'s "matches no CloudModelSpec" branch exists precisely to
report that self-inflicted disagreement. A3 collapses two dialects into one
and cannot express the tier system's purpose (a cheap `c`, a strong `m`),
while `_DIALECT_HOSTS` already ships two dialects.

**The risk, stated plainly.** A2 makes "which hosted providers may receive a
credential" a code-owned policy surface. That is deliberate: the host
allowlist (`composition.py:83-97`) is already code-owned for the same reason —
a key-bearing transport is never redirected by config. Adding a provider (or a
compatible gateway host) is a reviewed change, not a free-form config value.
It must be documented as a policy surface, and an unknown provider must
**never** be silently ignored or defaulted: it refuses, naming the ref.

### Failure modes (one row per condition in the charter's §3)

All refuse before the first tick. `_run` selects the live path and resolves
specs **before** `connect`, so no live refusal opens or migrates the database.

| Condition | Where caught | Message (rendered by `_run` as `Error: <joined>`) |
| --- | --- | --- |
| Unknown provider in a tier ref | registry lookup in `specs_from_tiers` | `tier 'm': provider 'gemini' is not in the model registry (known: anthropic, openai)` |
| Known provider, key absent | `check_composition` | `environment variable ANTHROPIC_API_KEY is not set` |
| Malformed ref (`m = "anthropic"`) | `parse_model_ref`, wrapped per tier | `tier 'm': model ref must be 'provider:model', got 'anthropic'` |
| Tier declared, spec mismatch | `check_composition` | `tier 'm' -> 'x:y' matches no CloudModelSpec` — **unreachable from config under A2** (specs are built from the refs, so every ref has a spec); retained as defence in depth and covered by a unit test |
| Spec with unknown dialect | `CloudModelSpec.__post_init__`, wrapped per provider | `provider 'x' declares an unknown dialect 'y' (known: anthropic, openai)` — **unreachable from config under A2** (the registry is code); pinned by a table test that every shipped entry's dialect is loadable |
| Key present but blank/whitespace | `check_composition` (`env.get(...).strip()`) | same as "key absent" |
| Empty tier refs | mode selection, not composition | no refusal — drain-only path |

Exit code `1` in every refusal row, matching `docs/API.md`'s documented
contract ("`0` success, `1` operational refusal/error"). The refusal line is
followed by one fixed hint: `Hint: re-run with --drain-only to skip the model
plane.` — kept in the CLI, not in `composition`, so the composition error text
stays a pure statement of what is wrong.

Two limitations recorded, not fixed here:

- `model_id` is **not** validated. A wrong model name fails at the provider
  (typed failure, first call), not at startup. A code table of model names
  would rot faster than it would help.
- Cost metadata defaults to `0.0` (`CloudModelSpec`'s declared defaults), so
  `ModelCallAccount.price_usd` is `0.0` in live mode under A2. **No surface may
  print a dollar figure from it.** The summary prints tokens, never price.

## 4. Decision B — what turns it on (recommend B1)

**B1.** Live iff `tier_refs_from_config(cfg)` is non-empty, i.e. iff at least
one `[model_tiers]` ref is non-blank — the project's own documented signal
(`config/hermes.toml:41-42`; `tier_refs_from_config` already filters empty
refs). Plus one per-invocation override that forces the drain-only path.

Rejected: **B2** adds a persistent switch that can disagree with the tiers
(`live_model = true` with empty tiers is a config that refuses), for no
capability B1 lacks; **B3** has no escape hatch, and the first thing an
operator needs when a key is missing is a way to drain anyway.

### The flag name

`--dry-run` is the wrong name in this system. The drain-only path **writes**:
it parks gates, transitions task rows, records outcomes. A flag whose name
promises no writes, on a path that writes, is exactly the kind of
misdescription the refusal-as-data and prohibited-claims disciplines exist to
prevent. Recommend `--drain-only` (one flag, no alias), help text:
"Drive the tick loop without composing the model plane (today's
fail-closed behavior); work still transitions and gates still park."

**Ruled R1:** the flag is `--drain-only`; the charter's `--dry-run` was
corrected, and no alias is shipped.

### Hazards B1 accepts

1. **A tier declared for a later run activates the next `hermes run`.** A
   config that was inert yesterday can spend money today. Mitigation: the run
   announces `Model plane: live` before the first tick and lists the resolved
   tiers, so the mode is never inferred after the fact.
2. **A config with tiers but no key used to drain successfully and will now
   exit 1.** That is the intended fail-closed behavior for a declared model
   plane, and `--drain-only` is the documented escape; the hint line above
   names it in the refusal.
3. **A live run is bounded but not free.** The controller's autonomy envelopes
   (`autonomy_caps`, `per_run_steps`, `per_run_tokens`) still bound the run;
   `--ticks` still bounds ticks. Neither is a dollar cap.

### Mode reporting, and the conflict in the charter

§4 of the charter requires the summary to state the mode; §7 requires
`--dry-run` with tiers to be byte-identical to the no-tier path. Both cannot
hold. I resolve it as: **only the live path announces.**

- **Live, before the first tick**, one line:
  `Model plane: live (tiers: c=anthropic:<model>, m=anthropic:<model>, s=openai:<model>)`
  (tiers sorted, each `tier=provider:model`).
- **Drain-only (no tiers, or `--drain-only`): nothing added.** The summary
  line, the notes, stderr, and the exit code are today's bytes.
- **After the run, live only**, one row per provider attempt, then a cap:
  `  model call 1: tier=m profile=researcher provider=anthropic model=<id> OK (in 812, out 96)`
  and, when more than 20 rows exist,
  `  ... N more model call(s) not shown (the ledger is in-process only)`.
  Refused-before-provider dispatches (`attempt == 0`) print `REFUSED (<code>)`
  with no token counts. No request content, no prompt, no price, no
  credential.

The operator rule becomes checkable: **silence means the model plane was
never composed, so no model call could have happened; a live run always says
so.** `hermes doctor` already prints the `[model_tiers]` section through
`config_to_string`, so the pre-flight view exists today.

## 5. The certified sentence

### Proposed replacement for `docs/STATE.md:162-171`

```
**Platform line (R1–R7 / W0–W4 / O1–O5) — landed; inert by default, reachable
only through a configured model plane.** The platform planes (R1–R7), the
wiring slices (W0–W4) and the O-series substrates (O1–O5) are committed on the
line as substrate: with `[model_tiers]` empty — the shipped default — the CLI
constructs the controller with no handlers, so none of it is reachable from the
shipped CLI. With at least one tier naming a registry provider, `hermes run`
composes the model plane and the methodology handler (OPS-1,
`docs/idr/LIVE-CLI-COMPOSITION.md`); that path is reachable from the shipped
CLI, and a run states its mode and names the provider it used. Reachability is
not certification, and no run output is evidence of scientific validity or
reproducibility. O2 is load-bearing (ratified by IDR-046); O1/O3/O4/O5 are
unwired and remain deferrable bulk — O1 pending its sidecar design gate, O5
pending a ranker design gate, O4 blocked on `ARCHITECTURE_DELTA` B-6. Only O2
is in scope for the certified tree; the rest is not a certified capability.
```

Three deliberate properties: it is **true by default** (empty tiers → exactly
today's reachability), it is **true when configured** without upgrading
reachability into validity, and it does not claim the whole platform line
became reachable — only the path the composed handler uses.

**The sentence cannot stay verbatim.** Both halves are falsified by the slice:
"landed but unreachable" and "constructs the controller with no handlers" are
true only while no model is configured. I see no reading under which the
certified text remains unconditionally true.

### Two citations in that paragraph are already dangling at this base

`docs/STATE.md:166` cites `AUDIT-PLATFORM-MERGE §B` and `:171` cites
`ROADMAP.md §Platform line`. Neither target exists at `9f74279`:
The two are different kinds of dangling. `AUDIT-PLATFORM-MERGE.md` does not
exist at this tree at all (it lives only on the local branch
`audit/platform-merge` at `1917490`). `ROADMAP.md` **does** exist at the root
(56 lines, the Step-4 regime roadmap); what does not exist is a **"Platform
line" section** in it (that section lives only on `fix/platform-docs` at
`8519681`). So one citation is to a missing document and the other is to a
missing section — both unresolvable, and the replacement drops both. This is pre-existing drift, not caused by OPS-1 —
but the slice must rewrite the paragraph anyway, so reproducing two citations
to nothing would be authoring a defect into a governed document.

The wording above **drops both pointers**. That is a documentation repair
inside a sentence this slice has to touch, and it should be recorded as such in
the merge log. If the Director wants them kept, the records must land first —
a separate governed edit with its own regeneration.

### B4 consequence (governed edit — deliberate regeneration required)

`docs/STATE.md` is a `CORPUS_REFS` member. `docs/API.md` is also a member and
also changes (the `run` syntax line and the mode/refusal contract; see §6.6).
So the implementation commit must include one deliberate regeneration per
`docs/gr3-b4/b4-fixtures/README.md` §Regenerating:

```
.venv/Scripts/python.exe -c "from pathlib import Path; \
from hermes.research.ref_graphs import build_all_reference_graphs, \
fixture_filename, reference_graph_bytes; [ \
(Path('docs/gr3-b4/b4-fixtures') / fixture_filename(g)).write_bytes( \
reference_graph_bytes(g)) for g in build_all_reference_graphs(Path('.').resolve())]"
```

Expected shape, to be verified by the implementation (not asserted here):

- `b4-c1`, `b4-c2`, `b4-c4` — regenerated (all three strata include both
  `docs/STATE.md` and `docs/API.md`).
- `b4-c3` — **unchanged** (IDR-only stratum, and the new note is not governed).
- Edge sets **identical** (`5 / 19 / 10 / 5`): the new citation target
  (`docs/idr/LIVE-CLI-COMPOSITION.md`) is outside `GOVERNED_CORPUS_REFS`, so it
  lands in `skipped`, never as an edge.
- `sources` counts unchanged (`6 / 12 / 8 / 4`).
- `skipped` lists **do** change: `+LIVE-CLI-COMPOSITION.md` (the new citation
  target), `-ROADMAP.md` if that pointer is dropped. (`AUDIT-PLATFORM-MERGE` is
  not a skipped token in the current fixtures.) Past regenerations recorded
  skipped-list deltas explicitly; this one must too.
- `tests/test_b4_ref_graphs.py` — **24 collected before and after** (verified
  at this base: 24). The digest moves; the count does not.

The regeneration is one event covering both files. Never regenerate for a
docs-only commit and then regenerate again for the code commit.

## 6. What changes in `_run` (outline, no code)

1. **Parser.** Add one flag to the `run` subparser: `--drain-only`
   (recommended name; §4). No other CLI surface changes.
2. **Order inside `_run`.** Keep the database-existence check first, byte for
   byte — a missing DB still prints `No database found. Run \`hermes init\`
   first.` and returns `1` regardless of tier config. Then select the mode.
3. **Pre-flight (pure, before `connect`).** If live: lazily import
   `hermes.composition`; call `specs_from_tiers(cfg)` — which resolves refs
   through the registry *and* runs `check_composition`, so the missing-key
   refusal is part of the pre-flight; catch `CompositionError` and emit
   `Error: <joined problems>` plus the one `Hint:` line; return `1`. Also call
   `load_profiles()` here (package-relative, `config.py:51`), so a broken
   profile tree refuses before the DB is touched. The builder validates and
   loads again; the double work is deliberate and negligible.
4. **Compose.** `composition.build_live_composition(cfg, conn, project_id=...,
   specs=..., environ=os.environ, autonomy_operator=cfg.autonomy_caps)` returns
   a frozen `LiveComposition(controller, binding)`. `build_live_controller`
   stays as the thin wrapper returning `.controller`, so the existing test and
   any future caller keep their contract. Still inside the existing `try` /
   `finally: conn.close()`.
5. **Drain-only.** Unchanged: `Controller(conn, project_id=...,
   autonomy_operator=cfg.autonomy_caps)`.
6. **Report.** Live: print the `Model plane: live (...)` line after the
   controller is constructed and before `ctrl.run`; after the run, print the
   summary (unchanged text), the notes (unchanged), then up to 20 ledger rows
   and the cap line. Drain-only: print exactly what `_run` prints today.
7. **`docs/API.md`** gains the flag and the mode/refusal contract in the
   `run` entry — two sentences, same governed regeneration as `STATE.md`.

No change to `controller.py`, the runtime, the gateway, the repositories, or
`composition`'s existing builders beyond the additive resolver and the
`LiveComposition` return.

## 7. Invariants, and how each is upheld

| # | Invariant | How |
| --- | --- | --- |
| 1 | No-config path byte-identical | Mode selection reads only `cfg`; drain-only executes today's statements. Pinned by a snapshot test over stdout, stderr, exit code, and journal rows. |
| 2 | Gates stay manual | No gate wiring added; the composed handler handles `methodology_run` only. Falsified by a live run that parks a `HUMAN_GATE` and records no resolution. |
| 3 | Single mutation path | The handler's orchestration is the controller's bound applier; no new writer, no direct repository calls from the CLI. |
| 4 | No new credential mechanism | `EnvCredentialResolver` only; refusal text names environment variables, never values; the summary prints tier/provider/model/tokens, never request content or price. |
| 5 | Census unchanged | No new transaction, owner, or import edge: `124 / 28 (19/5/4) / 1 / 15 / 0`. `scripts/check_census.py` must stay `PASS`. |
| 6 | Controller untouched | `_run` composes around it; `controller.py` and `agents/runtime/` are not edited. |

## 8. Falsifiers → tests (`tests/test_ops1_live_cli.py`)

1. **No tiers** → drain-only, asserted against a pinned snapshot of today's
   stdout/stderr/rc, with `hermes.composition.ProviderHTTPTransport`
   monkeypatched to fail if constructed (proving the model plane is never
   built). This is the slice's regression guard.
2. **Tiers + scripted transport** → one methodology stage executes end to end:
   the transport is injected by monkeypatching `hermes.composition.ProviderHTTPTransport`
   (the only socket seam; the composition, controller, handler, runtime and
   gateway stay real), the task reaches `SUCCEEDED`, `IntentApplied` rows are
   journaled, the summary says `live` and names the provider, and the
   `LiveComposition.binding.model_ledger()` rows are readable **after** the run.
   This is the definition of "trace" I recommend (§0.5).
3. **Tier configured, key absent** → rc `1`, message names the variable, no
   `Ran ... tick(s)` line, no new event rows, and the target task's status is
   unchanged (nothing half-processed). An existing DB is untouched by the
   refusal — no migration, no event rows — because the pre-flight precedes
   `connect`. With no DB, the `No database found` branch still wins over any
   tier problem (today's bytes, unchanged).
4. **Unknown provider** → rc `1`, message names the tier, provider, and the
   known set.
5. **Unknown dialect** → table test that every registry entry resolves to a
   loadable `CloudModelSpec`, plus a monkeypatched-registry test proving
   `specs_from_tiers` wraps `ValueError` into a `CompositionError` naming the
   provider (the config-reachable path cannot produce it).
6. **`--drain-only` with tiers** → byte-identical to falsifier 1's snapshot.
7. **Live run still parks `HUMAN_GATE`** → `WAITING_HUMAN`, `waiting on human`
   in the summary, no `HumanGateResolved`/`HumanDecisionReceived` row.
8. **Malformed ref** → rc `1`, `tier 'm': model ref must be 'provider:model'`.
9. **The vector line (R3)** → a live run prints exactly one `vector:` line; a
   failing collector prints `vector: unavailable (<reason>)` and the run's exit
   code is unchanged (falsified by making the collector raise).

## 9. Gates (implementation phase, per the charter)

1. Targeted: `tests/test_cloud_provider.py`, `tests/test_cli.py` (and
   `tests/test_cli_*` if present), the reconciliation tests, and the new OPS-1
   file.
2. `scripts/run_tests.py` (full).
3. `scripts/stamp_suite_count.py`, then `--check`.
4. `scripts/check_census.py` — unchanged.
5. `scripts/run_tests.py tests/test_b4_ref_graphs.py` — 24, **after** the
   deliberate regeneration.
6. `uvx ruff check src tests scripts`; `uvx pyright src`; pyright tests project.

Known environment failures on this host: four concurrency tests and
`test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory` are
intermittent (5 / 4 / 0 observed). Report what is observed, including `0
failed`; anything outside that set is a finding.

## 10. Previously open items — now resolved

1. **The flag name** — ruled `--drain-only` (R1).
2. **The meaning of "the run's trace is readable"** — ruled durable + vector
   (R3), with the implementation reading recorded above.
3. **`hermes doctor` pre-flight** — deferred to OPS-2 (R4); not built here.
4. **The `STATE.md` wording** — approved (R5), citations dropped with the
   distinction recorded in §5.
5. **Registry growth policy** — unchanged from the note: two providers now;
   adding one (or a gateway entry) is a later reviewed code change, and the
   host allowlist already fixes the host rule.

## 11. Implementation findings (phase 2, recorded not fixed)

1. **The multi-proposal wire form is unreachable through the router.**
   `ModelRouter._validate_output` requires a top-level `kind` in the injected
   allowlist, while `run._parse_structured` refuses a payload that carries both
   `kind` and `proposals` ("exactly one is allowed"). A reply that satisfies one
   is refused by the other, so the documented `{"proposals": [...]}` form can
   never be served. Live mode uses the single-proposal form
   (`kind` + `payload`). This is a pre-existing model-plane defect, outside this
   slice's invariant boundary (`controller.py` and `agents/runtime/` untouched);
   it needs its own gate.
2. **A reply cannot express "no proposals".** With the same validator, a reply
   without a top-level `kind` is a `ROLE` refusal, and a reply with one is a
   proposal. The plane has no silent wire form; every live call proposes. The
   review child therefore fails its own run (`MODEL_REFUSED`) while its parent's
   review verdict still passes on the child's empty proposal set. Also
   pre-existing, also not fixed here.

## 12. Claim boundary

This slice makes a configured model plane **reachable**, not **validated**. It
does not make any run's output evidence of scientific validity, does not
certify replay as validity, and does not certify any result the methodology
driver produces. The live path is fail-closed on composition only: unknown
provider, malformed ref, missing key, broken profile tree. Everything after
the first tick is the runtime's existing behavior, unchanged.
