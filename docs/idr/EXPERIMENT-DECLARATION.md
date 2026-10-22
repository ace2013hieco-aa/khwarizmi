# EXPERIMENT-DECLARATION — declare-experiment authority design (DESIGN ONLY)

**Status:** DESIGN (proposed — not implemented, not wired, not certified)
**Date:** 2026-10-11
**Base:** `origin/main` at `f6939129eb8429934c57db206a11480dab691ddb`
(`merge(license): removal + docling pin-bump integration; S4 triangle closed`)
**Branch:** `design/experiment-intent` (LOCAL-ONLY, NO PUSH)
**Worktree:** `D:\New folder\design-experiment-intent-wt` (isolated; `main` untouched)
**Scope:** docs + fixture tests only. Zero `src/` behavior change. No new
authority implemented. No execution semantics. No named products.

**Decides for:** what a future gated `DECLARE_EXPERIMENT` authority would look
like — payload, validator order, human-gate, registry shape queryable by the
M4 gate, what flips the structural-inadmissibility record, and what is
explicitly out of scope — so a later implementation charter has a falsifiable
target and the current refusal stays pinned until then.

## 0. Inputs (exact, verified at base — counts + file:line)

1. **EXPERIMENT-GATE-DOC-V2 resolution (b) — structural inadmissibility
   recorded.** `docs/ARCHITECTURE.md:92-97` (experiment-gated support,
   claim-ground G12; no registry or declaration intent exists; downgrade path
   INFERRED/SPECULATIVE) + `docs/STATE.md:93-105` (residual-debt bullet;
   `unverified_experiment_ref` for every experiment ref; hardened resolver
   fails closed; future registry + gated declaration intent is a future
   authority design, not a bug fix) + pin
   `tests/test_experiment_gate_pin_v2.py:1-71` (16 cases: 4 ref shapes ×
   DIRECT/PARTIAL refuse at `:57-61`; 4 ref shapes × INFERRED/SPECULATIVE
   admit at `:64-71`). Lineage: gate-doc commit `05c3217` (docs + pin) and
   its mainline successors `1cbf91b` / `cb63b1a`; B4 regen lesson `6665cde`
   (corpus doc edits without regenerated `docs/gr3-b4/b4-fixtures/` break 9
   `test_b4_ref_graphs.py` legs — regen is a line-owner duty, never a merge
   duty).
2. **M4 gate (shape + resolver, observed today).** Two layers in
   `src/hermes/research/claims.py`: (a) prefix shape — causal/experimental
   DIRECT/PARTIAL must cite `pre_registered_experiment:...`
   (`EXPERIMENT_ARTIFACT_TYPE` at `:98`; `SUPPORT_STATES` at `:89`;
   `CAUSAL_CLAIM_TYPES` at `:93`; `REF_SEP` at `:132`; shape rule
   `:619-637` refusing `causal_overclaim`); (b) existence gate — the cited
   experiment must dereference to an admitted in-project row via the injected
   resolver (`:638-658`, refusing `unverified_experiment_ref` at `:652`).
   Production wiring in `src/hermes/research/controller.py:5416-5442`:
   `_experiment_admitted` at `:5416-5420` returns `False` unconditionally
   (no store exists — fail closed), wired as
   `experiment_resolver=_experiment_admitted` at `:5442` into
   `validate_extraction`. The `STATE.md:103-105` note naming a prefix-only
   check at `main@ac1860a` is history: it describes the pre-claim-ground
   line, not the base tip (which carries both layers above).
3. **Existing intent kinds — no experiment kind (proved by enumeration).**
   `src/hermes/core/intents.py:26` defines **21** kinds; `git grep -n
   DECLARE_EXPERIMENT -- src tests docs` at base = **0 hits**. Enumerated:
   `INSERT_TASK, BRANCH, ABANDON, EVIDENCE_TRANSITION, REQUEST_HUMAN,
   REQUEST_REPLICATION, REQUEST_ADDITIONAL_EXPERIMENT,
   PROPOSE_GATE_OVERRIDE` (8) + `RECORD_CONTRADICTION,
   CONTRADICTION_RESOLUTION, RECORD_CLASSIFICATION,
   PROPOSE_RESEARCH_PROGRAM, PROPOSE_CLASSIFICATION_ACTION,
   RESOLVE_CLASSIFICATION_PROPOSAL, RECORD_SCOPE_REVIEW_DECISION,
   RETRACT_SOURCE, CURATE_KNOWLEDGE, EMIT_PARALLEL_REGIME_PROGRAM,
   ADMIT_TASK` (11) + `REVOKE_OPERATOR_CREDENTIAL,
   ROTATE_OPERATOR_CREDENTIAL` (2, director-only) = 21. Partitions:
   `llm_proposable` at `:135` = 9
   kinds; `director_only` at `:144` = 4 kinds; `internal_only` at
   `:158` = 9 kinds. The proposed `DECLARE_EXPERIMENT` below is absent
   from all three partitions by design (it is specified, not added).
   *(Counts refreshed at landing against `main@6e76fee`; the enumeration
   was authored when the vocabulary had 19 kinds, before CRED-1 added
   the two director-only credential kinds.)*
4. **Adapter boundary pattern (engines behind ports, never authorities).**
   `src/hermes/tools/providers/base.py:153` (`ProviderAdapter` ABC; 4 hooks
   `build_request:159`, `parse_page:164`, `extract_ids:170`,
   `build_fetch_request:176`; registry at
   `src/hermes/tools/providers/adapters/__init__.py:37`) + `RecordedTransport`
   at `src/hermes/tools/providers/replay.py:313` (record/replay, refusing
   inner transport) + determinism owns control
   (`src/hermes/research/evaluation.py:1-14`, no LLM in evaluation) +
   map rows `docs/ARCHITECTURE.md:16` (models sit behind ports),
   `:33-34` (adapter + replay rows), `:67-77` (research/provider boundary),
   `:79-90` (authority boundary; LLM-invokable set closed at
   `intents.py:124`). Single mutation path `apply_intent` at
   `src/hermes/research/gateway.py:4053` (map cites `:3961` — line drift,
   same function); refusal codes at `gateway.py:106-121` (map cites
   `:93-109` — same table, shifted by added codes); append-only journal
   (`src/hermes/core/events.py`, writer in repositories; no DELETE in `src/`);
   4 KiB event-payload discipline (`src/hermes/persistence/event_validation.py`,
   `RATIONALE`); project isolation (every resolver/detector/validator row is
   project-scoped; cross-project citation fails closed).

**NOT-topic scan (charter core requirement):** scoped inputs (the four items
above), this document, and the accompanying fixture tests were scanned for
named forbidden systems: **0 hits**. Any execution capability in this design
appears ONLY as the unnamed abstract phrase "execution engine" behind the
existing adapter boundary above — never as a named product, never in a
payload example, test, or fixture. (A pre-existing prose boundary sentence
elsewhere in the baseline map is outside the scoped inputs and is left
untouched by this slice; this design adds zero new named references.)

**Constraints respected:** determinism owns control; single mutation path
(`apply_intent` only); append-only journal; replay = byte/evidence
determinism only (never validity); human-authority fail-closed boundary;
bounded payloads; project isolation; prohibited-claims discipline;
archive-not-delete + head-only supersession; lease-fenced single writer;
content-hash identity; N1/N9 frozen semantics; no provider leakage into core;
no new persistence→research edges; minimal diffs (docs + 1 test file).

## 1. Proposed DECLARE_EXPERIMENT intent (specified, NOT implemented)

**Kind (proposed name):** `DECLARE_EXPERIMENT`. Absent from the 21-kind
vocabulary above (0 hits — §0.3). This section specifies it; no enum member,
validator, migration, or resolver is added in this slice (verified:
`git diff --stat` touches `docs/` + one `tests/` file only).

### 1.1 Payload schema (closed — unknown keys refuse, EC-F01 style)

Envelope is the standard `Intent { kind, proposed_by, project_id, payload,
justification }` (`intents.py`). Payload keys (7 closed; unknown key →
`MALFORMED_PAYLOAD`, `gateway.py:110`):

| Key | Type | Bounds | Notes |
|---|---|---|---|
| `experiment_key` | `str` | 1–64 chars, charset `[A-Za-z0-9_-]+`, must not contain `:` (`REF_SEP`, `claims.py:132`) | batch-local ref segment; full ref is `pre_registered_experiment:<experiment_key>` (`claims.py:98`) |
| `title` | `str` | 1–200 chars | human-readable declaration title; record, never authority |
| `hypothesis_ref` | `str` | 1–500 chars, free text | opaque in V1 (no dereference — avoids inventing a new authority edge) |
| `method_summary` | `str` | 1–3500 chars | what was declared; counted toward the 4 KiB total below |
| `engine_descriptor` | `str` | closed vocabulary `{"unspecified", "execution-engine"}` | abstract handle ONLY — the schema makes a named product unrepresentable; any other value refuses `MALFORMED_PAYLOAD` |
| `human_decision_ref` | `str` | 1–128 chars, names a `HumanDecisionReceived` journal row | ratification binding (see §1.3 rule 5); missing/unbound refuses `PROPOSAL` |
| `supersedes_ref` | `str \| None` | optional; when present, 1–128 chars naming the current head row | head-only supersession (see §1.3 rule 7); default `None` |

Global bounds: strict typing (no coercion); per-field maxima enforced both
at construction (cf. `Intent.__post_init__` + IDR-045 C5 precedent
`gateway.py:123-134`) and pre-write in the future validator; total serialized
payload ≤ 4 KiB per `event_validation.py` (`RATIONALE` on oversize, before any
write). Identity is content-derived and recomputed, never trusted: future
`experiment_id` = hash over `(project_id, experiment_key, title,
hypothesis_ref, method_summary, engine_descriptor)` (cf. `cl_`/`fc_`/`fx_`
precedents); idempotent re-declaration of byte-identical payload returns the
existing row plus an `IntentApplied` audit row (intended volume, cf.
`ARCHITECTURE.md` intentional-volume note).

### 1.2 Validator rules (ordered — mirrors the §3.3 write path)

Future `_validate_declare_experiment` (name only — not added here) would run,
in order, fail-closed with stable codes from `gateway.py:106-121`:

1. **Role gate** → `ROLE` (`:106`). Only the human-gated partition passes
   (see §1.3); any LLM/agent/Director `proposed_by` refuses.
2. **Project gate** → `PROJECT_NOT_FOUND` (`:109`). Envelope `project_id`
   must resolve; payload binding must match the envelope.
3. **Payload schema** → `MALFORMED_PAYLOAD` (`:110`); oversize →
   `RATIONALE` (pre-write, `event_validation.py`). Unknown keys, wrong
   types, charset/length/closed-vocab violations refuse here.
4. **Credential-exists** → `OPERATOR` (`:121`). Operator credential ratified;
   token never enters intents/events (per §3.6).
5. **HumanDecision dereference + hash binding** → `PROPOSAL` (`:119`).
   `human_decision_ref` must resolve to a `HumanDecisionReceived` journal row
   in-project whose payload binds the full-command hash
   (`record_operator_decision` precedent, IDR-040 §3; same shape as
   `RETRACT_SOURCE`/`CURATE_KNOWLEDGE`/`RECORD_SCOPE_REVIEW_DECISION`).
   Missing/forged/mismatched verdicts refuse — the human-gate.
6. **Domain: key + idempotency** → `IDEMPOTENCY_CONFLICT` (`:116`) /
   `STALE` (`:114`). Recomputed content id decides: byte-identical repeat =
   idempotent admit (audit row, no duplicate); same `experiment_key` with
   different bytes without a valid `supersedes_ref` refuses.
7. **Supersession: head-only** → `STALE`. `supersedes_ref`, when present,
   must name the current head row for that `experiment_key` in-project; a
   second supersede link onto one row refuses (same invariant as S5).
8. **Project isolation.** Admission and the §2 resolver are project-scoped;
   a ref resolving only in another project does not admit (fail-closed, same
   pattern as `EVIDENCE_DOES_NOT_RESOLVE`).
9. **Write** through the single mutation path only: repository write inside
   its owned transaction + journal append, via `apply_intent`
   (`gateway.py:4053`). No direct repository writes from orchestration, no
   direct SQL outside certified boundaries. Refusals return data
   (`GatewayRejection` + code), never silent success, never raise through
   the loop.

Effect on the M4 gate when (and only when) a future implementation lands:
the G12 `elif` at `claims.py:643-650` keeps its shape; the only change is
that `experiment_resolver(ref)` can return `True` for admitted head rows
instead of the current always-`False` stub (`controller.py:5416-5420`).
The M4 prefix-shape rule (`causal_overclaim`, `:619-637`) is unchanged.

### 1.3 Authority: who may propose / admit — human-gated by default

- **May propose:** OPERATOR human only, ingested as a DETERMINISTIC internal
  intent (the human has no agent profile — the `record_operator_decision`
  precedent, IDR-040 §3). The kind would join `internal_only`
  (`intents.py:158`, 9 kinds today → specified 10th) and must NOT appear
  in `llm_proposable` (`:135`) or `director_only` (`:144`).
- **May admit:** the deterministic gateway validator only. No model output
  decides the transition (`evaluation.py` determinism; v4 §2 principle 2).
- **Rationale (why human-gated is the default):** (a) admitting an
  experiment upgrades causal DIRECT/PARTIAL claims from refused to
  admittable — letting an LLM admit its own experiments would be a
  self-certifying loop, breaking "determinism owns control"; (b) it extends
  the certified human-authority fail-closed boundary (the 9 `internal_only`
  kinds including contradiction resolution, classification recording, source
  retraction, knowledge curation — same authorship argument: judgment belongs
  to the operator, the substrate re-validates deterministically); (c) it
  preserves the single mutation path, append-only history, content-hash
  identity, and refusal-as-data; (d) it keeps the prohibited-claims
  discipline (no model asserts execution validity or reproducibility);
  (e) it is fail-closed by default — any future relaxation (e.g. a
  Director-proposed draft + separate human admit) needs its own explicit
  design gate plus the owning certification slice re-run, never a silent
  widening. A missing/unbound `HumanDecisionReceived` row refuses the command.

## 2. Registry shape (admitted experiments queryable by the M4 gate)

A future `research_experiments` store (specified — NOT created here) that the
M4 resolver reads. Shape (minimal to satisfy the G12 protocol, nothing more):

- **Row:** `experiment_id` (content-hash, recomputed — cf. §1.1),
  `project_id` (scope key), `experiment_key` (unique per project head),
  `title`, `hypothesis_ref`, `method_summary`, `engine_descriptor` (closed
  vocab from §1.1), `status` (`ADMITTED` / `SUPERSEDED`), `supersedes_ref`
  (nullable head link), `declared_by` (operator id, never a token),
  `human_decision_ref` (journal binding), `journal_seq` / `created_tick`
  (ordering, never wall-clock authority), `payload_hash`.
- **Invariants (inherited, not invented):** append-only (no DELETE in `src/`;
  supersession/invalidation are new rows); head-only supersession (§1.2
  rule 7); project-scoped reads and writes (§1.2 rule 8); bounded payloads
  (§1.1); lease-fenced single writer for the admitting tick; reads
  re-resolve current state on every call, writers never trust a read
  (`ARCHITECTURE.md` §3.4); schema evolution by ADD-COLUMN-only guarded
  migrations, idempotent re-run (precedent `_migrate_19_to_20` at
  `src/hermes/persistence/migrations.py:1193-1222`, registry entry at
  `:1250`).
- **Queryable by the M4 gate (exact protocol):** the claims-layer type is
  `ExperimentResolver = Callable[[str], bool]` (G12 protocol). The future
  production resolver keeps the identical signature as today's stub
  (`controller.py:5416-5442`) and returns `True` iff the ref parses as
  `pre_registered_experiment:<key>` AND `<key>` resolves to an `ADMITTED`
  head row **in the same project**. `INFERRED`/`SPECULATIVE` claims never
  consult it (downgrade path unchanged); non-experiment sources still refuse
  `causal_overclaim` before reaching it. No second resolver, no cache, no
  cross-project fallback.

## 3. Migration path for the structural-inadmissibility record

**Today (pinned, green):** `ARCHITECTURE.md:92-97` + `STATE.md:93-105` record
structural inadmissibility; `controller.py:5416-5420` fails closed;
`test_experiment_gate_pin_v2.py:1-71` pins refusal-for-every-ref (8 legs) +
downgrade-admits (8 legs). This design changes none of that.

**What flips, when a future registry ships** (requires its own implementation
charter — this document is not permission to implement; architecture changes
need the full suite plus the owning gate slice re-run per `AGENTS.md`):

1. **Resolver body** (`controller.py:5416-5420`): always-`False` → registry
   lookup per §2 (same signature, same call site `:5442`). Fail-closed
   preserved: unknown / malformed / foreign-project / superseded refs still
   return `False` → `unverified_experiment_ref`.
2. **Pin test** (`test_experiment_gate_pin_v2.py`): retired/replaced by a
   registry-backed admission test — admitted head ref + DIRECT/PARTIAL
   admits; fabricated / bare-prefix / multi-segment-unknown / foreign-project
   / superseded refs still refuse `unverified_experiment_ref`; downgrade
   states still admit. Count lineage must be recorded exactly (cf. §5 of the
   claim-ground merge audit: 3783 → 3826 = 26 + 16 + 1).
3. **Records** (`ARCHITECTURE.md:92-97`, `STATE.md:93-105`): the
   "structurally inadmissible" paragraphs flip to "admitted via the gated
   registry" by **dated addendum** (IDR-SKELETON rule: never rewrite an
   existing record's decision text). The old pin's commit history stays.
4. **Migration + gates:** ADD-COLUMN-only store migration with guarded
   `pragma_table_info` + idempotent re-run (precedent above); full suite
   green; `ruff` + both `pyright` gates green; B4 fixtures regenerated and
   committed in the same line if any corpus doc (`ARCHITECTURE.md`,
   `STATE.md`, `API.md`, `IDR-024`, `IDR-028`) changes (lesson `6665cde` —
   the gate-doc line's 9 B4 failures came from editing the sweep sources
   without committing the regenerated content-addressed fixture).
5. **Non-flips:** M4 prefix-shape rule, downgrade path, adapter boundary
   (4 hooks + `RecordedTransport`), single mutation path, journal
   append-only, N1/N9 semantics, prohibited-claims discipline — all unchanged.

## 4. Explicit non-goals (what this authority will never be)

1. **No execution semantics.** The registry records *declarations*
   (pre-registration metadata). It never runs anything, schedules anything,
   interprets outcomes, scores validity, or touches the tick loop. Any
   "execution engine" in this design is the unnamed abstract capability
   behind the existing adapter boundary (`base.py:153-176`,
   `replay.py:313`) — it is never invoked, described, configured, or
   extended here; no new adapter, hook, executor, workflow, or telemetry.
2. **No named engines.** By charter constraint, no product, system, or
   strategy name appears in the schema (§1.1 closed `engine_descriptor`
   makes names unrepresentable), the registry (§2), the fixtures, the tests,
   or the examples. The NOT-topic scan for this slice is 0 hits (§0).
3. **No auto-admission.** No LLM-proposable path, no Director auto-admit, no
   prefix-only admission, no bulk import, no backfill inventing values
   (legacy-NULL no-backfill policy precedent applies: UNKNOWN stays NULL,
   never invented). Every admission needs a recorded, hash-bound human
   verdict (§1.2 rule 5); unwitnessed decisions refuse `PROPOSAL`.
4. **No validity or reproducibility claims.** Replay proves byte/evidence
   determinism only; the registry never certifies scientific validity and a
   declaration row is never presented as evidence of a result (advisory
   substrate rule, v6 §29.2). No digest/derived view is presented as
   authority.
5. **No new authority in this slice.** This document specifies; the
   accompanying tests prove the *specified* schema/validator logic against
   fixtures with a test-local pure replica (no `src/` import of a new kind,
   no gateway/validator/migration/resolver change). `DECLARE_EXPERIMENT`
   remains 0 hits in `src/` after this slice. Anything that would admit a
   real experiment ref is a future charter's job, gated as §3 lists.

## Acceptance (this slice)

- This document complete with all 4 sections (§1–§4) plus inputs (§0) and
  acceptance (§5).
- Fixture tests `tests/test_experiment_declaration_fixtures.py` green
  (design-replica schema/validator over fixtures: valid admits, 8 refusal
  legs, idempotency + supersession legs — no `src/` authority exercised).
- `uvx ruff check src tests` green; `uvx pyright src` (strict,
  `pyrightconfig.json`) green. `src/` diff empty.
- Branch `design/experiment-intent` LOCAL-ONLY, NO PUSH; isolated worktree;
  `git diff --stat` shows `docs/idr/EXPERIMENT-DECLARATION.md` + one
  `tests/` file only.

## Relation-to-baseline

Touches no certified invariant: no `src/` change, no intent added, no
resolver rewired, no migration, no adapter change, no journal change. It
operationalizes the deferred stance both records name ("a future authority
design, not a bug fix" — `STATE.md:101-102`) by writing that design down.
The follow-up implementation slice (if ever chartered) owes §3's flip list
plus the full suite and the P6/N9/P7/tick-loop owning-gate re-runs.
