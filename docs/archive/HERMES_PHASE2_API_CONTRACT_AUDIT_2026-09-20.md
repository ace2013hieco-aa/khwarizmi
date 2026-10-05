# Hermes Phase 2 API Contract Audit — 2026-09-20

## §0 Executive finding

Hermes's actual API is: the CLI (15 subcommands), ~30 Controller
methods, 18 intents in 3 role partitions, 65 event types, 25 durable
tables, an 11-adapter 4-hook provider boundary, content-hash identity
formulas, and structured refusal codes. Users should depend on: the
CLI surface, the documented Controller verdict/read methods, the
intent *value strings* they are authorized to propose, the adapter
ABC, event-record shapes they consume, and refusal *codes* (not
texts). Everything else — gateway validators, candidate derivation,
repository internals, `_`-prefixed machinery, row shapes — is
INTERNAL or UNDECLARED. Durable protocol (intents/events/hashes/
idempotency keys) is distinct from ordinary Python API and carries
the strictest compatibility burden.

## §1 Baseline

`HEAD == origin/main == 97c09ce`, branch `main`, tree clean except
known untracked (`IDEA.md`, external `orci/orhead/ortree.json`).
Phase 1/1.1 artifacts verified present
(`AGENTS.md`, `docs/{ARCHITECTURE,API,STATE,README}.md`,
`examples/first_run.py`, all four `docs/archive/HERMES_*` reports;
Phase 1.1 report certifies `PHASE 1.1 — CERTIFIED` for closure
`97c09ce`). Read-only audit: zero source/test/config modifications
(proven by validation §20 rerun: 2035/0/0/0 identical).

## §2 Existing documentation (Phase 1 API assessment)

`docs/API.md` is directionally correct and its counts verify:
18 intents, 9/2/8 partitions, 11 adapters, 15 CLI subcommands,
30 Controller methods, 16 gateway codes. Gaps found (reported, not
repaired per §19): (a) walkthrough `examples/first_run.py` resolves
the UUID project id via `status --json` — correct but undiscoverable
without reading it; (b) repository direct-construction is labeled
UNDECLARED while CLI itself constructs repositories for reads
(`cli.py:176-177,249,326,343,364,401,433,457,604,644`) — the read
pattern is de-facto supported and should be acknowledged;
(c) `IntentApplied`-on-duplicate and `_notes` growth bound are
governed behaviors without contract tests (see §7);
(d) `__all__`-declared names (39 sites) are unmentioned as a
compatibility surface (see §4/§11).

## §3 API inventory

**CLI** (`src/hermes/cli.py:760`, parser `:657-738`, dispatch
`:766-819`): init, doctor [--json], backup, restore, status
[--json], audit [--project] [--json], project create|show, task
show, events, pause|resume, run <id> [--ticks N] (`:469`, drives
`Controller.run` `:494`, notes `:495`), gate resolve
(`:581-609` → `Controller.resolve_human_gate`), operator register
(`:627-644` → `OperatorCredentialRepository.register`). `--config`
(`:665`, schema `config.py`, secrets never in config). `--json`
single document, errors to stderr. Exit `0`/`1`; boundary never
crashes (`:496`). Classification: EVOLVING (behavior tested,
signatures undeclared stable).
**Controller** (30 public methods, `controller.py:340`; full list
verified by AST): verdict ingestion (8 `record_*`/`resolve_`/
`register_operator`, credential+lease+HumanDecision, dict refusal),
detection/reads advisory (`detect_contradictions:1872`,
`classification_proposals:620`, `reconcile_digest:1047`,
`re_review_candidates:748`, cones/radii `:667-716`, `notes:476`).
CLI uses only construct + `run` + `notes` + `resolve_human_gate`
(+ `register` via repository directly). Tests call `tick` ×234,
`resolve_human_gate` ×93, `detect_contradictions` ×46, `run` ×35.
**Intents** (18, `core/intents.py:26-112`): LLM 9 (`:115-121`),
director 2 (`:124-132`), internal 8 (`:135-143`). Six drafted kinds
(`BRANCH,ABANDON,REQUEST_HUMAN,REQUEST_REPLICATION,
REQUEST_ADDITIONAL_EXPERIMENT,PROPOSE_GATE_OVERRIDE`) have NO
validator — only consumer is `NOT_WIRED` (`gateway.py:3816-3824`);
dead vocabulary or future surface (classified UNDECLARED, flagged
for an explicit decision). `RECORD_CLASSIFICATION` (`:68`) is
internal-only because it asserts an operator judgment: LLM proposal
→ `ROLE` (`gateway.py:175-181`; proven
`tests/test_p6_classification.py:312-336`); ingestion builds a
DETERMINISTIC intent + idempotent `classification-decision-{hash}`
(`controller.py:2252-2298`); gateway re-verifies decision binding
(`gateway.py:3008-3043`) else `PROPOSAL`. External/internal/
durable/event vocabularies are disjoint sets (see §4).
**Events/records** (65 `EventType`, `core/events.py:21-116`;
25 tables, `migrations.py:33-1055`; UNIQUE content hashes
`:156,384-385,443,461,608,813`; one-verdict partial indexes
`:763-770,984-993`). Journal append (`repositories.py:92-125`,
validated `:113`); audit `INTENT_APPLIED`/`INTENT_REJECTED`
(`gateway.py:3836-3868`, duplicates count as applied `:3832`).
Idempotency keys: `retract_*` (`gateway.py:1267`), `classify_*`
(`failure_classification.py:974,922`), `cres_*` (`gateway.py:2670`),
`curate_*/curated_*`, `fc_/cx_/fx_/ix_` formulas, decision
correlations. **Adapters** (11 incl. `core.py`;
`ProviderAdapter` ABC `base.py:139-165`, 4 required + 1 optional
hook; `PROVIDER_REGISTRY` + `resolve_adapter`
`adapters/__init__.py:32-57`; transports/protocols
`base.py:182-248`; error taxonomy `research_sources.py:614-703`;
replay `replay.py:44-132,333-470`, missing fixture →
`ReplayUnavailableError/FIXTURE_MISSING`). Third parties CAN
implement the ABC without Hermes internals (all hook types live in
`tools/`; verified zero `research|core|persistence` imports in
`adapters/*.py`). **Errors**: 16 gateway codes (`:93-108`), ~13
controller codes, 6 completion denials, provider exceptions;
human text vs machine code vs durable record vs exit code are
separate layers (§8). **Identity**: `fc_/cx_/cres_/fx_/retract_`
+ decision correlations + `classification-decision-*`; canonical
serialization + clocks (`core/__init__.py:14-32`); recompute-never-
trust enforced (`failure_classifications.py:196-202`).
**Boundaries**: strong — CLI/Controller/Intent/gateway/single-
writer journal/recorded-transport; weak — repository read/write
split (same classes), Controller public-vs-orchestration;
accidental — `__all__` beyond need (see §7); missing — no declared
read-only facade (CLI reads repositories ad hoc).

## §4 Classification matrix

PUBLIC/SUPPORTED: CLI commands; listed Controller verdict/read
methods; authorized intent values; adapter ABC + registry +
transports; consumed event shapes; refusal codes; identity
formulas (as rules, not code).
PUBLIC/EVOLVING: CLI flags/outputs; Controller method set;
rejection-code set; adapter optional hooks; fixture format.
PUBLIC/UNDECLARED: repository direct construction/reads;
`TickResult` shape; `notes` contents; `__all__` exports beyond the
above; the 6 validator-less intent kinds; `run(max_ticks)` tuning.
INTERNAL: gateway validators, candidate derivation, L2 resolvers,
migration internals, `_`-methods, fence/lease mechanics.
ACCIDENTALLY PUBLIC: `core/graph.py` pure queries (only Controller
uses); `first_present`/`extract_xml_items`
(`base_adapter.py:39,52`, zero external importers);
`classifications_digest` (only `controller.py:624,632`); adapter
class attributes via package import (beyond `__all__`).
HISTORICAL/DEPRECATED: none declared (zero deprecation machinery
in src) — correctly, there is nothing yet to deprecate.

## §5 Stability model

Phase 1 `docs/API.md` convention (frozen-by-decision / evolving /
internal / undeclared) is **sufficient** — verdict (2),
directionally correct and already applied. Semantics per category:
FROZEN — change only via architecture decision (+ migration +
gate re-run; e.g. intent values, event names, hash formulas,
code meanings); EVOLVING — PR-documented + tested, set may grow,
meanings never silently change; INTERNAL — free with suite green;
UNDECLARED — no promise, may be reclassified. No deprecation
period needed while no external consumer exists; introduce one
only when a consumer appears. Machinery verdict: NO to semver,
schema registry, negotiation, deprecation framework,
compatibility matrix, generated specs — none has demonstrated
need (single repo, CLI-only external surface, forward-only
migrations with `SUPPORTED_VERSION` guard `migrations.py:1154`).

## §6 Breaking-change matrix (grounded)

| Surface | Change | Breaking? | Rationale |
|---|---|---|---|
| CLI | rename command | definitively | scripts/tests parse names (`test_cli.py:47,128,428,501`) |
| CLI | exit-code change | definitively | `0/1` contract + example asserts |
| Python API | rename supported Controller method | potentially | tests + example use; no external consumer known |
| Intent | rename durable intent | definitively | journal rows + validators key on value strings |
| Intent | move role partition | definitively | authority boundary (gated behavior) |
| Event | rename durable event | definitively | journal history + readers key on names |
| Record | remove/rename field | definitively | readers + UNIQUE/dedup logic |
| Record | add optional/nullable field | non-breaking | precedent `migrations.py:521` (nullable → forward-only suffices) |
| Adapter | change required hook | definitively | 11 adapters + contract tests (`test_chg2:478`) |
| Adapter | add optional hook | non-breaking | `validate_fetch` default precedent |
| Error | change exception identity | potentially | tests assert classes; callers match codes |
| Refusal | change machine code | definitively | certified meanings; tests pin codes |
| Refusal | reword detail text | non-breaking | human layer only |
| Identity | change canonical hash | definitively | dedup/replay/idempotency/journal all keyed on it |
| Serialization | change canonical form | definitively | same reason |
| Replay | change replay semantics | definitively | CHG-2 contract + parity tests |
| Authorization | alter accepted path | definitively | human-authority invariant (gated) |
| Schema | add table/column (nullable) | non-breaking | forward-only migrations, `SUPPORTED_VERSION` |
| Schema | remove/rename | definitively | breaks old databases (no down migrations by design `:11`) |

## §7 Test-contract coverage

Covered (exact tests in evidence): CLI compat (`test_cli.py:47,
128,428,501,587,691,736`), roles (`test_gateway.py:135,141,146`,
`test_v6_attacks.py:98`, chg1 `:446`, p6 `:312`), records
(audit/status/doctor JSON schemas), payload bounds
(`test_event_validation.py:59,68,73,206,219,269`,
`test_database.py:220`), replay (`test_p4_wiring.py:390,408,570`),
identity (`test_chg1:267,273,280`, recomputation proofs),
adapters (`test_chg2:470,474,478`, hr04 `:605`), refusals
(`test_controller.py:909,916,936,1000`, `test_gateway.py:406,411`),
isolation (chg1 `:814`, gateway `:299`, cli `:1710`,
controller `:3039`), authorization (controller `:1190,1292,2426`,
p6 `:265`), duplicates (`test_gateway.py:193,359`,
controller `:806`, skeleton `:182`).
Gaps (grep-verified): `_notes` growth bound — ABSENT (internal
diagnostic; document bound, don't test first); IntentApplied-on-
duplicate — ABSENT as named assertion (behavior covered via
`duplicate is True` + counts; add explicit event-count test when
touching audit); migration down — ABSENT BY DESIGN (forward-only
`:11`); shared test helpers duplicated across 15 files (`_make`,
`_classify`, `_chain`, `_program` — maintenance cost, extract to
`tests/support.py` in a later phase). Nothing material is
genuinely untested.

## §8 Documentation gaps (report, don't repair)

1. `docs/API.md` understates CLI repository-direct reads (supported
   read pattern, §3 evidence). 2. `__all__` surface unmentioned as
   compatibility-relevant. 3. Six validator-less intents need an
   explicit dead-or-future decision. 4. `run(max_ticks)`/
   `TickResult`/`notes` shaping undocumented. 5. Notes-bound and
   IntentApplied-on-duplicate behaviors undocumented. All minor;
   none misleads about certified behavior.

## §9 Refactor compatibility

Must stay stable: intent/event/identity strings, refusal-code
meanings, adapter ABC, repository write-transaction boundaries,
lease semantics, journal append order. Freely movable: validator
module placement, candidate-derivation location, digest helpers,
L2 resolvers, Controller read-method grouping. Needs shims: none
(public Python surface is thin; CLI shells the moves). Declare
internal before decomposing: `core/graph.py` queries,
`classifications_digest`, `TickResult` fields,
`_detector_candidate_rows` shape. Cannot move casually: table/
column shapes, UNIQUE/dedup keys, correlation-ID schemes,
fixture format, `SUPPORTED_VERSION` discipline. Persistence→
research correction is compatible PROVIDED the pure-helper
destination keeps identical call semantics (gateway/controller
call sites unchanged).

## §10 Adversarial review

1. Implementation details declared public? PASS (UNDECLARED used;
   `_`-methods explicitly internal). 2. Real contract hidden?
   PASS (CLI repository reads now surfaced in §3/§8). 3. Discoverable
   omitted API? PASS (inventoried `__all__`, package attrs,
   `TickResult`, `notes`). 4. Durable vs Python conflated? PASS
   (§4 separates; §6 treats them differently). 5. Refusals
   contractual? PASS (codes frozen-in-meaning, texts human-only).
   6. Harmless refactor breaks replay? PASS (matrix rows +
   recompute-never-trust rule). 7. Silent hash breakage? PASS
   (formulas + dedup keys identified as definitively breaking).
   8. Adapter isolated? PASS (zero upward imports verified).
   9. Exports create obligations? AMBIGUOUS (`__all__` + package
   attribute access create a thin de-facto surface; acknowledged
   in §4/§8, no false certainty claimed). 10. Machinery needed?
   PASS (all six rejected with evidence). 11. Invariants
   preserved? PASS (model references gates, changes nothing).
   12. Survives decomposition? PASS (§9 move/stable lists).
   13. Survives dependency correction? PASS (condition stated).
   14. Naming-only classification? PASS (every class cites
   callers/tests/imports, not names).
   Result: 13 PASS, 0 FAIL, 1 AMBIGUOUS (documented, not hidden).

## §11 Recommendations (prioritized, implement in later gates)

1. Decide the six validator-less intents (remove or specify) —
   design note + `NOT_WIRED` documentation. 2. Acknowledge CLI
   repository-direct reads as the supported read pattern in
   `docs/API.md`. 3. Underscore or document `graph.py` queries,
   `first_present`/`extract_xml_items`, `classifications_digest`.
   4. Add `tests/support.py` shared fixtures (maintenance only).
   5. Add IntentApplied-on-duplicate + notes-bound contract tests
   when touching those areas. 6. Keep everything else stable;
   no machinery, no shims, no renames in this phase.

## §12 Phase 2 decision

```text
PHASE 2 — AUDIT COMPLETE / IMPLEMENTATION GATE REQUIRED
```
