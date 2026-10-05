# HERMES DG-4 — Repository Structural Design Review + Adversarial Closure Gate

**Date:** 2026-09-21
**Authorizing baseline:** `0f86189cf52b606bf149e58f4d3348414aa6a940`
**Scope:** `src/hermes/persistence/` (the repository layer) — read-only design gate
**Report:** this file (the only repository change DG-4 makes)

---

## §0 Executive verdict

```text
DG-4 — REPOSITORY DESIGN GATE PASSED / ONE SEAM AUTHORIZED
```

The repository layer is **not** decomposable, and this gate says so with evidence rather
than opinion. Measured physically on `0f86189`:

* `src/hermes/persistence/` is **10 modules / 6,976 lines / 40 classes / 53 module-level
  functions**, and contains **11 of the 25 transaction-acquisition owners in the
  repository** (plus one rollback-only participant) out of **113 executed
  transaction-control calls** across persistence, gateway and Controller.
* Exactly **two** methods in the entire persistence package do not use `self`, and
  **seven more** never declare a `self` parameter — i.e. nine symbols already *are* free
  functions the class is nominally hosting. That mechanical fact, not line count, is the
  only seam class this gate could find.
* Every other candidate is load-bearing on one of: transaction ownership, transaction
  snapshot, identity authorship or verification, event/journal ownership, rollback
  boundary, N9 retraction, project scoping, or authority/lease.

**One seam is authorized** (§19–§20): the smallest of the mechanically-pure symbols —
`SourceOutcomeRepository._proposed_set` (`source_outcomes.py:456-467`, 12 lines) →
module-level private `_proposed_set(outcome, outcome_kind)` in the same file. It has one
caller, runs **before** `BEGIN IMMEDIATE`, performs **no** read, no write, no SQL, no
identity authorship, no event, no refusal, and no test imports it privately.

**Everything else is rejected**, including the parts of the repository layer that look
most attractive from a distance (the N9 predicates, the shared event writer, the
obligation/verdict writers, the lease lock, the row→dict helpers, the cross-layer private
imports, and the persistence→research inversion).

**DG-5 is required** — not as a formality, but because this gate found three structural
facts that a repository-only gate cannot resolve:

1. **`_is_extract_spec` is triplicated, byte-for-byte, across three layers**
   (`persistence/repositories.py:1820`, `research/extraction.py:309`,
   `research/gateway.py:3231`). The repository copy documents that it exists so that
   "admission and the write path never disagree" — an invariant currently held by
   *three copies staying in sync*, not by a shared implementation. Consolidating it
   requires editing gateway admission code, which is outside DG-4's authorization.
2. **Two research-layer modules import a *private* persistence helper**
   (`research/gateway.py:1487` and `research/completion.py:63`).
3. **The documented inversion is exactly three cycle pairs, and it is real**
   (§10), including a persistence-authored durable identifier that is computed by
   calling *upward* into `research.programs`.

**Honest alternative.** A reviewer who requires zero motion for zero coupling gain may
choose `DG-4 — NO SAFE REPOSITORY REDUCTION` instead; §19 states the case for that
reading explicitly. What is **not** defensible is splitting a repository class, moving a
transaction owner, or relocating a resolver — §17 forbids all three with per-candidate
reasons.

---

## §1 Baseline identity

```text
repository          github.com/ace2013hieco-aa/khwarizmi-research
branch              main
HEAD                0f86189cf52b606bf149e58f4d3348414aa6a940
origin/main         0f86189cf52b606bf149e58f4d3348414aa6a940    (HEAD == origin/main)
ancestry            03ff3e4 (DG-3C) → f54af56 (S-4 impl) → 0f86189 (S-4 cert)
tracked changes     none (working tree clean)
untracked (pre-existing, untouched)
                    IDEA.md, Prompts/, orci.json, orhead.json, ortree.json
```

Certification chain verified present in `docs/archive/`:

```text
HERMES_DG2_CONTROLLER_STRUCTURAL_DESIGN_GATE_2026-09-20.md
HERMES_DG3A_S2_VERDICT_SEAM_DESIGN_GATE_2026-09-20.md
HERMES_DG3B_GATEWAY_STRUCTURAL_DESIGN_GATE_2026-09-20.md
HERMES_DG3C_TRANSACTION_PRESERVING_VALIDATOR_REDUCTION_GATE_2026-09-21.md
HERMES_S2_HUMAN_DECISION_APPEND_CERTIFICATION_2026-09-20.md
HERMES_S3_L2_RESOLUTION_EXTRACTION_CERTIFICATION_2026-09-20.md
HERMES_S4_S5_CONE_CLOSURE_EXTRACTION_CERTIFICATION_2026-09-21.md
```

`git log --oneline -6`:

```text
0f86189 docs(archive): certify S4 S5 cone closure extraction
f54af56 refactor(gateway): extract S5 cone closure
03ff3e4 docs(archive): complete DG-3C validator reduction design gate
dffe907 docs(archive): certify S-3 gateway L2 extraction
df57650 refactor(gateway): extract S5 L2 upstream resolution
65e82c0 docs(archive): complete DG-3B gateway structural design gate
```

Nothing in this gate modifies, stages, renames or reinterprets the five untracked items.

---

## §2 Source/document authority

The physical source wins wherever a document disagrees. Four document claims were
tested, not assumed:

| # | Document claim | Physical finding | Disposition |
| - | -------------- | ---------------- | ----------- |
| D-1 | `docs/ARCHITECTURE.md:140` — "Repositories own one `BEGIN IMMEDIATE` transaction each (`repositories.py`, `failure_classifications.py:233`, `source_outcomes.py:294`, `database.py:113`)" | **113 executed control calls / 25 acquisition owners + 1 rollback-only participant** across three layers; `repositories.py` alone holds **10 acquisition owners**, 8 of them `BEGIN IMMEDIATE`, 2 plain `BEGIN`; `EventRepository.append_transactional:803,815` opens `BEGIN` **twice per call** (retry path) | **DOCUMENTATION DRIFT** — see §4 |
| D-2 | `docs/ARCHITECTURE.md:37-45` (§3.3 normative write path) — "repository.write (own `BEGIN IMMEDIATE`) → journal append → COMMIT" | Correct as a *description of the primary path*, incomplete as a *rule*: the owner census in §4 shows 5 gateway-owned and 4 Controller-owned transactions on certified paths | **DOCUMENTATION DRIFT** (over-generalization), individual non-repository owners are **INTENTIONAL ARCHITECTURAL EXCEPTION** |
| D-3 | `docs/ARCHITECTURE.md:148-155` — "KNOWN ARCHITECTURAL DEBT … `persistence/` imports `research/` … held together by lazy imports at **three documented cycle pairs**" | **Exactly three** cycle pairs, and the *listed line numbers are stale* (§10) | **Verified in substance; line references refreshed** |
| D-4 | `docs/ARCHITECTURE.md:157-160` — "`Controller` (76 methods), `gateway.py` (~40 validators), and `repositories.py` (14 classes) … split only mechanically, with the owning gate re-run per split" | `repositories.py` now has **19 classes** (not 14); the "split only mechanically" instruction is consistent with DG-4's negative map | **DOCUMENTATION DRIFT (stale count); instruction upheld** |

No claim in this report rests on a prior gate's conclusion where the source could be
re-measured. Where a prior gate's number is reused (gateway 5 owners, DG-3B §7), it was
re-derived here and matches.

---

## §3 Repository inventory

`src/hermes/persistence/` — measured with `ast`, not estimated:

| Module | Lines | Classes | Module-level functions |
| ------ | ----: | ------: | ---------------------- |
| `__init__.py` | 4 | 0 | 0 |
| `backup.py` | 267 | 1 (`BackupResult`) | `create_backup`, `_assert_no_live_lease`, `restore_backup`, `retain_last_n` |
| `database.py` | 178 | 2 (`SchemaVersionError`, `DatabaseLockError`) | `_configure_pragmas`, `connect`, `get_schema_version`, `assert_schema_version`, `acquire_writer_lock`, `release_writer_lock`, `get_lock_owner`, `integrity_check`, `foreign_key_check` |
| `event_validation.py` | 151 | 1 (`EventValidationError`) | `validate_event_type`, `validate_payload_size`, `validate_no_secrets`, `validate_event` |
| `failure_classifications.py` | 795 | 4 (3 error types + `FailureClassificationRepository`, 12 methods) | `classifications_digest` |
| `migrations.py` | 1180 | 0 | 19 (`_migrate_0_to_1` … `_migrate_16_to_17`, `migrate_to_latest`, `_get_version`) |
| `program_obligations.py` | 339 | 4 (2 error types + `ValidationVerdictRepository` 3 m, `ProgramRequirementSatisfactionRepository` 3 m) | `validation_verdict_id_of`, `satisfaction_id_of` |
| `provider_interactions.py` | 247 | 1 (`ProviderInteractionRepository`, 5 m) | `persist_interaction`, `make_persisting_sink` |
| `repositories.py` | 2754 | 19 | 10 (`_json_dumps`, `_json_loads`, `_append_event_to_db`, `_operator_token_hash`, `_burn_dummy_operator_work`, `_token_hash_matches`, `_research_program_row_to_dict`, `_claim_row_to_dict`, `_assumption_row_to_dict`, `_is_extract_spec`) |
| `source_outcomes.py` | 1061 | 6 (4 error types, `SourceRepos`, `SourceOutcomeRepository` 18 m) | `_source_artifact_resolves`, `source_artifact_retracted` |
| **total** | **6976** | **40** | **53** |

Class concentration in `repositories.py` (19 classes; the four largest):

```text
ResearchProgramRepository  1160-1753   593 lines  11 methods
ClaimAssumptionRepository  1834-2406   573 lines  12 methods
TaskRepository              382-715    334 lines  12 methods
ProjectRepository           144-377    234 lines  10 methods
```

Concentration is real but §14 is explicit: **a class is not split because it is large.**
No class in this package has a demonstrated internal ownership boundary that DG-4 could
find; every candidate boundary crossed a transaction, an event, an identity author, or a
resolver (§17).

---

## §4 Transaction-owner census

Mechanical criterion: an **executed** `.execute("BEGIN…"|"COMMIT"|"ROLLBACK"|"SAVEPOINT"|"RELEASE")`
call whose argument is a string literal — AST-derived, so docstring/comment prose (e.g.
`repositories.py:798`, `gateway.py:512`, `database.py:108`) is excluded by construction.

```text
executed control calls: 113
acquisition owners:      25
rollback-only participants: 1
```

| Layer | File | Owner (class-qualified) | BEGIN | COMMIT | ROLLBACK |
| ----- | ---- | ----------------------- | ----: | -----: | -------: |
| persistence | `database.py` | `acquire_writer_lock` | 1 IMMEDIATE | — | 1 |
| persistence | `database.py` | `release_writer_lock` | 1 IMMEDIATE | 1 | — |
| persistence | `failure_classifications.py` | `FailureClassificationRepository.record` | 1 IMMEDIATE | 1 | 2 |
| persistence | `migrations.py` | `migrate_to_latest` | 1 (plain) | 1 | 1 |
| persistence | `repositories.py` | `ProjectRepository.create` | 1 (plain) | 1 | 1 |
| persistence | `repositories.py` | `ProjectRepository.transition_lifecycle` | 1 IMMEDIATE | 1 | 1 |
| persistence | `repositories.py` | `ProjectRepository.transition_mode` | 1 IMMEDIATE | 1 | 1 |
| persistence | `repositories.py` | `ProjectRepository.advance_iteration` | 1 IMMEDIATE | 1 | 1 |
| persistence | `repositories.py` | `TaskRepository.create` | 1 (plain) | 1 | 1 |
| persistence | `repositories.py` | `TaskRepository.transition_status` | 1 IMMEDIATE | 1 | 1 |
| persistence | `repositories.py` | `TaskRepository.invalidate` | 1 IMMEDIATE | 1 | 1 |
| persistence | `repositories.py` | `EventRepository.append_transactional` | **2** (plain) | 1 | 2 |
| persistence | `repositories.py` | `ResearchProgramRepository.record` | 1 IMMEDIATE | **2** | **6** |
| persistence | `repositories.py` | `ClaimAssumptionRepository.record_extraction` | 1 IMMEDIATE | 1 | 4 |
| persistence | `repositories.py` | `EmptyResultArtifactRepository.record` | 1 IMMEDIATE | 1 | 1 |
| persistence | `source_outcomes.py` | `SourceOutcomeRepository.record` | 1 IMMEDIATE | 1 | 2 |
| **participant** | `repositories.py` | `ClaimAssumptionRepository._validate_supersede_target` | — | — | **3** |
| research | `gateway.py` | `_decision_append_transactional` | 1 IMMEDIATE | 1 | 3 |
| research | `gateway.py` | `_validate_retract_source` | 1 IMMEDIATE | 1 | 4 |
| research | `gateway.py` | `_validate_curate_knowledge` | 1 IMMEDIATE | 1 | 8 |
| research | `gateway.py` | `_validate_record_contradiction` | 1 IMMEDIATE | 1 | 8 |
| research | `gateway.py` | `_validate_contradiction_resolution` | 1 IMMEDIATE | 1 | 5 |
| research | `controller.py` | `Controller.resolve_human_gate` | 1 (plain) | 1 | 1 |
| research | `controller.py` | `Controller._acquire_lock` | 1 IMMEDIATE | 1 | 2 |
| research | `controller.py` | `Controller._persist_floor_transitions` | 1 (plain) | 1 | 1 |
| research | `controller.py` | `Controller._write_ladder_transition` | 1 (plain) | 1 | 1 |

**Layer totals:** persistence **16** owners (11 in `repositories.py`, 1 each in
`failure_classifications`, `source_outcomes`, `migrations`, 2 in `database`), gateway
**5**, Controller **4**.

### §4a Reconciliation of D-1 — the `docs/ARCHITECTURE.md:140` claim

The sentence "repositories own one `BEGIN IMMEDIATE` transaction each" fails in **three
independent ways**, each verified:

1. **Not one per repository.** `repositories.py` alone has 11 acquisition owners;
   `ResearchProgramRepository.record` alone performs 6 rollbacks and 2 commits.
2. **Not always `IMMEDIATE`.** Four acquisitions use plain `BEGIN`
   (`repositories.py:154`, `:400`, `:803`, `:815`) and one in `migrations.py:1160`.
   `EventRepository.append_transactional` deliberately re-enters with plain `BEGIN` for
   its retry path — its own docstring at `repositories.py:798` records that this
   transaction control was *moved into persistence from the gateway* (`ADD-01`).
3. **Repositories are not the only owners.** Gateway owns 5 (all `BEGIN IMMEDIATE`) and
   the Controller owns 4, on certified paths (`resolve_human_gate` — the S-2/HumanDecision
   surface; `_acquire_lock` — the scheduler lease; `_persist_floor_transitions`;
   `_write_ladder_transition`).

**Classification: `DOCUMENTATION DRIFT`** for the general claim, and
`INTENTIONAL ARCHITECTURAL EXCEPTION` for each non-repository owner individually — they
are the certified S5 / CHG-1 / Step-7 / S-2 designs, not accidents. This is the same
finding DG-3B §3(d) recorded from the gateway side; DG-4 now confirms it from the
persistence side by independent measurement. **DG-4 does not change either.** The
documentation correction is *not* authorized here (see §21).

### §4b Transaction participation ≠ ownership

Two persistence modules contain **zero** transaction control and are therefore
**participants**, never owners:

* `program_obligations.py` — 0 control calls. `ValidationVerdictRepository.record`
  (`:96-135`) reads, derives `verdict_id = validation_verdict_id_of(...)`, and INSERTs
  into `validation_verdicts` on `self._conn`; `ProgramRequirementSatisfactionRepository.record`
  is reached from `controller.py:3020` (inside `Controller._record_requirement_satisfactions`,
  `controller.py:2959`, which owns no transaction control of its own).
* `provider_interactions.py` — 0 control calls. `persist_interaction`
  (`:134`) writes `provider_interactions` rows through a sink closure
  (`make_persisting_sink`, `:228`) driven from the provider transport; its own docstring
  (`:241-245`) records the justification: "rows are content-keyed and idempotent, so no
  fencing hazard arises beyond what the tick already serializes".

Adversarial question 22 (§23) is answered by this distinction: a symbol being *inside* a
transaction is not the same as *owning* one, and neither condition permits DG-4 to move
it.

---

## §5 Responsibility census

Every persistence module classified by which responsibilities it actually discharges
(`R` read, `V` validation, `I` identity, `M` mutation, `E` event, `T` transaction,
`A` authority, `G` graph/resolution, `D` domain rule, `X` exception/rollback,
`S` serialization):

| Module | R | V | I | M | E | T | A | G | D | X | S |
| ------ | - | - | - | - | - | - | - | - | - | - | - |
| `repositories.py` | ● | ● | ● (author+verify) | ● | ● | ● (11 owners) | ● verify | ● `research_programs` | ● | ● | ● |
| `source_outcomes.py` | ● | ● | ● verify | ● | ● (delegated) | ● (1 owner) | — | ● edge-carried resolution | ● | ● | ● |
| `failure_classifications.py` | ● | ● | ● verify | ● | — | ● (1 owner) | — | ● evidence resolver | ● | ● | ● |
| `program_obligations.py` | ● | ● | ● **author** | ● | — | participant | — | ● obligation satisfaction | ● | ● | ● |
| `provider_interactions.py` | ● | ● | consume | ● | — | participant | — | — | — | ● | ● |
| `event_validation.py` | — | ● | — | — | ● pre-write gate | — | — | — | ● | ● | — |
| `database.py` | ● | — | — | ● `scheduler_lock` | — | ● lease (2 owners) | ● lease/fence | — | — | ● | — |
| `migrations.py` | ● | ● | — | ● | ● schema only | ● (1 owner) | — | — | — | ● | — |
| `backup.py` | ● | ● | — | filesystem | — | — | — lease check | — | — | ● | — |
| `__init__.py` | — | — | — | — | — | — | — | — | — | — | — |

Two observations that matter for §19:

1. **Identity appears in three different modes** — authored (`program_obligations.py`
   `validation_verdict_id_of`/`satisfaction_id_of`, `repositories.py` `uuid.uuid4()`
   correlation ids), verified (`repositories.py:1300-1320`, `:1997-2026`,
   `source_outcomes.py:436`, `:830-859`), and consumed (`_append_event_to_db` callers).
   Extraction is only safe in the *consume* mode.
2. **`repositories.py` is the only module that touches all eleven responsibilities.** That
   is the concentration §14 asks about, and §17 explains why it is nonetheless not
   splittable: the responsibilities are not separable along *ownership* lines — the
   mutations, their events, their identities and their rollbacks share one connection and
   one snapshot.

---

## §6 Pure-seam census

Mechanical criterion (AST, not substring grep — every candidate below was inspected with
its *own* identifier surface, docstrings excluded where they mention banned words like
`BEGIN`):

**(a) Methods whose body never uses `self`** — the whole package has exactly two:

```text
source_outcomes.py:456   SourceOutcomeRepository._proposed_set       12 lines  impure tokens: none
source_outcomes.py:800   SourceOutcomeRepository._verify_reused_row  61 lines  impure tokens: none
```

**(b) Methods that never declare a `self` parameter** (already free functions):

```text
failure_classifications.py:507  FailureClassificationRepository._metadata            42 lines
repositories.py:2544            CuratedKnowledgeRepository._entry_row                 22 lines
repositories.py:2668            ContradictionRepository._row                          25 lines
repositories.py:2695            ContradictionRepository._party_active                 18 lines
source_outcomes.py:452          SourceOutcomeRepository._sha256                        3 lines
source_outcomes.py:988          SourceOutcomeRepository._search_outcome_metadata      25 lines
source_outcomes.py:1015         SourceOutcomeRepository._fetch_outcome_metadata       47 lines
(reference: research/controller.py:121 Controller._FencedConnection._is_write) — outside persistence
```

**(c) Module-level functions with no impure token** (no `conn`/`execute`/`commit`/
`rollback`/`EventType`/`_reject`/`hashlib`/`uuid`/clock):

```text
backup.py:239                       retain_last_n(backup_dir, n)          filesystem, not a DB seam
event_validation.py:63              validate_event_type(event_type)
event_validation.py:74              validate_payload_size(payload, max_bytes)
repositories.py:80                  _json_dumps(value)
repositories.py:86                  _json_loads(value)
repositories.py:1007                _burn_dummy_operator_work(token)      authority timing side-channel
repositories.py:1756                _research_program_row_to_dict(row)
repositories.py:1768                _claim_row_to_dict(row)
repositories.py:1775                _assumption_row_to_dict(row)
repositories.py:1820                _is_extract_spec(spec)                triplicated (§10d)
```

**(d) Inert statement runs inside transaction bodies.** A recursive scan of every
persistence function for maximal runs of ≥4 statements with no I/O call produced a long
list (e.g. `failure_classifications.record:137-220`, `:241-313`;
`source_outcomes._validate_task_binding:479-501`, `:508-548`, `:567-595`, `:604-671`;
`repositories.record:1262-1287`, `:1306-1364`, `:1385-1497`). **Every one of them is a
false positive of the scan's granularity, not a seam**: they are composed of
`conn.execute(...)` statements whose *SQL literal* is a multi-line string, so the run
boundary falls between statements rather than around them. This is recorded because a
future agent will otherwise "rediscover" these as candidates. The only *statement-level*
pure region DG-3C ever found in the gateway was one 11-line closure; persistence has no
equivalent that is not already a free function.

**Classification of the census:**

| Symbol | Class | Why |
| ------ | ----- | --- |
| `_proposed_set` (456) | **GREEN — selected** | one caller *before* `BEGIN`; takes only in-memory objects; no I/O; `self` unused |
| `_verify_reused_row` (800) | YELLOW — deferred | same purity class, but called *inside* `_commit`'s transaction and raises integrity errors; needs its own gate (§18) |
| `_search_outcome_metadata`, `_fetch_outcome_metadata`, `_sha256` | NOT-A-SEAM | already free functions (no `self` parameter); extraction relocates nothing |
| `_metadata`, `_entry_row`, `_row`, `_party_active` | NOT-A-SEAM | ditto — row→dict mappers with no owner beyond their repository |
| `validate_event_type`, `validate_payload_size` | NOT-A-SEAM | already the shared pure validators of the event gate (single consumer path) |
| `_json_dumps`, `_json_loads` | YELLOW → DG-5 | genuinely shared, but consumed *across layers as private symbols* (§10c) |
| `_research_program_row_to_dict`, `_claim_row_to_dict`, `_assumption_row_to_dict` | YELLOW → DG-5 | consumed across layers (`research/completion.py:63`, `controller.py`) as private symbols |
| `_is_extract_spec` | RED for DG-4, DG-5 required | triplicated predicate; consolidation touches gateway admission (§10d) |
| `_burn_dummy_operator_work` | RED | authority timing side-channel; imported by 4 test files |
| `retain_last_n` | NOT-A-SEAM | filesystem retention, unrelated to DB structure |

---

## §7 Transaction-snapshot analysis

The rule this gate applies is not "read-only ⇒ safe" but:

> Moving a read out of its transaction is unsafe unless the exact observation the code
> makes (pre-transaction / post-BEGIN / post-mutation / post-event) is unchanged.

### §7a Snapshot-bound reads (RED — must stay where they are)

| Read | Site | Observes | Why it cannot move |
| ---- | ---- | -------- | ------------------ |
| idempotency read | `source_outcomes.py:690-697` (`_resolve_idempotency`, called at `:298`, i.e. **inside** `record`'s tx opened at `:294`) | post-BEGIN state | the `NEW`/`IDENTICAL`/`DIVERGENT` decision is the whole point of the transaction; a pre-BEGIN read re-introduces the race the tx exists to close |
| artifact reuse read | `source_outcomes.py:728` (`self._artifacts.get_by_hash` inside `_commit`) | post-BEGIN state | `SD-04` documents "get-by-hash-first, **inside the transaction**" |
| key-read/validate pair | `repositories.py:1502-1520` (`ResearchProgramRepository.record`) | post-BEGIN | `F-01`: "read + validate INSIDE `BEGIN IMMEDIATE`" is the certified pattern (also `:211-219`, `:274-286`, `:532-538`, `:637-646`) |
| task-binding re-read | `source_outcomes.py:604-671` (`_validate_task_binding`) | post-BEGIN | V6-P7-A2-01/02/03: the producing task is re-checked **inside** the write transaction "so it is atomic with the write" |
| N9 re-resolution | `repositories.py` retraction-adjacent reads; gateway in-tx re-resolve | post-BEGIN | N9 does not trust upstream filtering (see §12) |
| supersession target read | `repositories.py:2300-2330` (`_validate_supersede_target`) | post-BEGIN | it ROLLBACKs the caller's transaction on refusal (3 sites) |
| duplicate/event-existence reads | `repositories.py:806-821` (`EventRepository.append_transactional` retry) | post-BEGIN | the retry path re-enters `BEGIN` deliberately |

### §7b Snapshot-free candidates (the only GREEN space)

| Symbol | Reads inside body | Conn in signature | Snapshot relationship |
| ------ | ----------------: | ----------------- | --------------------- |
| `_proposed_set` (`source_outcomes.py:456`) | **0** | no | **none** — pure function of the caller's in-memory `outcome` object; called at `:292`, i.e. *before* `BEGIN IMMEDIATE` at `:294` |
| `_verify_reused_row` (`source_outcomes.py:800`) | **0** | no | **none** — pure comparison of two dicts supplied by the caller at `:735`; runs inside the tx but observes nothing |

Both were verified at AST level: their identifier surfaces contain no `conn`, no `.execute`,
no `commit`/`rollback`, no `EventType`, no `_reject`, no `hashlib`, no `uuid`, no clock.
`_proposed_set` does call `outcome_record_hash(outcome, outcome_kind)` — a deterministic
pure derivation imported from `hermes.tools.research_sources` (`source_outcomes.py:45`) —
and reads `r.content_hash` / `f.artifact.content_hash` attributes off in-memory objects.
Neither touches the database at all, so **no extraction can change what they observe**.

### §7c The distinction that kills the attractive candidates

`_source_artifact_resolves` (`source_outcomes.py:96`) *looks* like a pure resolver, and its
consumers are spread across three modules. But it takes `conn` as its first parameter and
executes a 5-parameter (6 with `upstream_task_id`) `EXISTS`/join query — it is a
**transaction-participating reader**, not a pure function. Moving it would move a read
that currently observes the caller's snapshot (gateway calls it at `gateway.py:2262`
*inside* the N9 transaction). Same for `source_artifact_retracted` (`:159`). Both are RED
(§12).

---

## §8 Identity authorship (persistence layer)

| Category | Symbol / site | Mode | Inside a tx? | Notes |
| -------- | ------------- | ---- | ------------ | ----- |
| correlation ids | `uuid.uuid4()` × 8 — `repositories.py:166, 218, 278, 326, 435, 536, 644, 1500` | **AUTHOR (non-deterministic)** | computed before `BEGIN` in every case | correlation tokens on events; not content identity, and the event payload already carries them; recorded here because it means `events` rows are not reproducible from inputs alone |
| durable identifier authorship | `program_obligations.py:53-60` `validation_verdict_id_of`, `:166-175` `satisfaction_id_of` | **AUTHOR** | called *inside* the caller's write path (`:126`, `:286`) | computed via `canonical_json` + `sha256_hex` **lazily imported from `hermes.research.programs`** (`:55`, `:169`) — persistence authoring a durable id by calling upward (§10b) |
| content-hash **verification** | `repositories.py:1300-1320` (program: `content_hash_of`, `input_hash_of`, `program_id_of` re-derived and compared), `:1997-2026` (`claim_id_of`/`assumption_id_of`), `:2455-2457` (`empty_result_content_hash_of`/`empty_result_id_of`) | VERIFY | yes | the certified "re-derive, never trust the caller" pattern (EC-V6 / IDR-026) |
| payload-hash verification | `source_outcomes.py:436-444` (`self._sha256(raw_bytes) != artifact.content_hash`), `:966-970` (`FD-06`), `:830-859` (`OB-02` re-verification of a reused row) | VERIFY | yes | includes the *only* `hashlib` use in the source-outcome path, deliberately localised in `_sha256` (`:451-454`) |
| authority hashing | `repositories.py:959` (`pbkdf2$sha256$` prefix), `_operator_token_hash` (`:987`), `_token_hash_matches` (`:1019-1060`), `_burn_dummy_operator_work` (`:1007-1017`) | VERIFY + timing equalisation | n/a | credential verification, not admission; `_burn_dummy_operator_work` exists so a missing credential costs the same time as a wrong token |
| event identity | `_append_event_to_db` (`repositories.py:92-128`) | AUTHOR (event row) | n/a | the single event writer (§9) |

**Consequence for §19:** the only identity mode that can be relocated is *consume*. The
selected candidate `_proposed_set` **consumes** hashes (it does not compute the outcome
hash itself — `outcome_record_hash` does — and it authors nothing), so relocating it moves
no identity authorship. This was checked explicitly rather than assumed.

---

## §9 Journal / event ownership

One writer, one place:

```text
def _append_event_to_db(conn, clock, event_type, project_id=None, task_id=None,
                        from_state=None, to_state=None, correlation_id=None,
                        caused_by=None, reason=None, artifact_ids=None, payload=None)
    repositories.py:92–128        # INSERT INTO events (…)   — payload gated by event_validation
```

Call sites (AST-derived):

```text
persistence/repositories.py:162, 249, 304, 342, 373, 430, 603, 666, 711, 806, 816, 1596, 1749
persistence/source_outcomes.py:777 (lazy import), :779
research/gateway.py            (imports + calls it)
research/controller.py         (imports + calls it)
research/verdict_decisions.py:20  (the S-2 certified seam)
tests: test_controller.py:3257, test_q05_evidence_ladder.py:494/522/707,
       test_s1_detector_rows.py:212, test_s5_retraction.py:102   (private imports)
scripts/adversarial_probe_s5.py
```

**Atomicity contract, verified by reading the call sites:** the event insert happens on the
caller's connection *inside the caller's transaction*, after the state mutation and before
`COMMIT` — e.g. `source_outcomes.py:779` sits inside `record`'s `BEGIN IMMEDIATE … COMMIT`
(`:294 … :302`), and the per-repository `_append_event` wrappers
(`repositories.py:365-380`, `:703-716`, `:1741-1752`) exist only to pass the repository's
`conn`/`clock` through. `event_validation.validate_event` gates the payload **before** the
INSERT (`event_validation.py:11`, `:146`).

**Verdict: RED — do not touch.** The writer is already centralised; relocating it changes
nothing structurally, would disturb the `mutation → event → commit` ordering that the
gateway (5 owners), the Controller (4 owners) and 7 test files depend on, and `ADD-01`
(documented in `repositories.py:370`, `:708`, `:1746`) is the precedent showing that the
*only* correct direction for event/transaction alignment was inward, into the repository.
DG-4 does not invert a certified precedent.

---

## §10 Persistence → research dependency map (the inversion)

16 import statements, all verified (`ast`), with the three cycle pairs that hold them
together:

| # | Site | Imported symbols | Needed for | Class | DG-5 disposition |
| - | ---- | ---------------- | ---------- | ----- | ---------------- |
| 1 | `failure_classifications.py:52` | `FAILURE_CLASS_SCHEMA_VERSION, FailureClass, FailureClassification, FailureClassificationDraft, FalsificationRecord, PermittedAction, classify_failure, parse_contributing_factors, permitted_actions_for` | domain classification at write time | **domain logic leaking upward** | **YELLOW** — pure and deterministic, but it *is* the certified failure-classification semantics |
| 2 | `program_obligations.py:55` | `canonical_json, sha256_hex` (lazy) | `validation_verdict_id_of` | pure primitives, identity-critical | **GREEN** (move downward) — with a canonicalization-equivalence proof |
| 3 | `program_obligations.py:169` | `canonical_json, sha256_hex` (lazy) | `satisfaction_id_of` | ditto | **GREEN** |
| 4 | `repositories.py:52` | `CLAIM_SCHEMA_VERSION, DEREFERENCE_DIMENSIONS, REF_SEP, ContextResolver, ExtractionResult, ExtractionVerdict, assumption_id_of, claim_id_of` | claim/assumption write path | domain types + identity derivation | **YELLOW** (`assumption_id_of`/`claim_id_of` are authorship) |
| 5 | `repositories.py:62` | `EXTRACT_TEMPLATE` | EXTRACT task-output acceptance | a single vocabulary constant | **GREEN** — the cheapest real cleanup; blocks only because it is admission vocabulary (§10d) |
| 6 | `repositories.py:63` | `CompilationResult, CompilationStatus` | program record | protocol/type surface | **YELLOW** |
| 7 | `repositories.py:64` | `EmptyResultResolver` | empty-result write path | resolver protocol | **YELLOW** |
| 8 | `repositories.py:236` | `can_complete_research` (lazy) | completion rule consulted by a repository read path | domain rule | **YELLOW** — cycle pair (c); the lazy import hides an eager reversal |
| 9 | `repositories.py:1259` | `program_to_dict` (lazy) | program record | serialization | **GREEN/YELLOW** |
| 10 | `repositories.py:1298` | `SUPPORTED_PROGRAM_SCHEMA_VERSIONS, content_hash_of, derive_program_obligations, input_hash_of, program_id_of, validate_program_epistemic` (lazy) | inside `ResearchProgramRepository.record` | **identity authorship + epistemic validation + obligation derivation** | **RED until DG-5 proves the derivation unchanged** |
| 11 | `repositories.py:1379` | `_SLOT_REF_MAX_LENGTH, _SLOT_REF_RE, MAX_SLOT_RATIONALE` (lazy) | slot validation | private constants of the domain | **YELLOW** (persistence reaching into *private* research constants) |
| 12 | `repositories.py:2440` | `empty_result_content_hash_of, empty_result_id_of` (lazy) | `EmptyResultArtifactRepository.record` | identity authority | **RED until DG-5** |
| 13 | `source_outcomes.py:40` | `FetchedPayload` | fetch outcome type | protocol type | **YELLOW** |
| 14 | `source_outcomes.py:41` | `SOURCE_FETCH_TEMPLATE, SOURCE_SEARCH_TEMPLATE` | source task templates | vocabulary constants | **GREEN** |
| 15 | `source_outcomes.py:45` | `content_hash_of_search_result, observation_hash_of_search_result, outcome_record_hash, search_result_from_mapping, search_result_to_mapping` | source-outcome identity authoring/verification | **identity authorship inside a transaction** | **RED until DG-5** |
| 16 | `repositories.py:51` | `_source_artifact_resolves` — *persistence → persistence* | artifact resolution | intra-package | see §10c |

### §10a Cycle pairs (exactly three, matching `ARCHITECTURE.md:148-155`)

```text
(a) hermes.persistence.repositories  ⇄  hermes.persistence.source_outcomes
      eager: repositories.py:51      → source_outcomes
      lazy:  source_outcomes.py:777  → repositories
(b) hermes.persistence.repositories  ⇄  hermes.research.extraction
      eager: repositories.py:62      → research.extraction
      lazy:  research/extraction.py  → persistence.repositories
(c) hermes.persistence.repositories  ⇄  hermes.research.completion
      lazy:  repositories.py:236     → research.completion
      eager: research/completion.py:63 → persistence.repositories
```

The document's count is **correct**; its *line references* (`:52, :62-64, :236, :1259,
:1298, :1379, :2440`, `source_outcomes.py:41`) are stale for four entries and omit
`program_obligations.py:55,169`, `source_outcomes.py:40`, and `repositories.py:51`
(persistence-internal). DG-4 records the refresh; §21 forbids acting on it here.

### §10b Is a research import “bad by default”? No.

Each import was asked the three §13 questions:

1. *Is this domain logic leaking upward, or a pure primitive whose ownership is merely
   misplaced?* — Split: items 2/3/5/9/14 are pure primitives or constants (misplaced
   ownership); items 1/4/10/12/15 are **domain/identity logic** consumed by the write path.
2. *Can the primitive move downward without changing behaviour?* — For items 2/3/5/14,
   yes in principle (they are pure functions of their arguments).
3. *Would moving it require changing transaction boundaries or resolver semantics?* —
   **No for items 2/3/5/14; yes for items 1/4/10/12/15** (they are evaluated inside
   certification-critical transaction bodies: `:1300-1320` and `:1997-2026` re-derive
   identity after `BEGIN IMMEDIATE`).

The third question is the decisive one, exactly as §13 requires. That is why the
persistence→research inversion is **not** classified as a defect DG-4 may repair: the
majority of the load-bearing imports are evaluated *inside transactions* whose certified
behaviour depends on the derivation running there.

### §10c Cross-layer *private* imports (a distinct, smaller finding)

```text
research/gateway.py:1487        from hermes.persistence.repositories import _json_loads
research/completion.py:63       from hermes.persistence.repositories import _research_program_row_to_dict
persistence/failure_classifications.py:448, 476, 497, 555, 584   from …repositories import _json_loads
```

These are not the inversion (research→persistence is the *allowed* direction) but they do
reach into another layer's **private** namespace. Consolidating `_json_loads`/
`_json_dumps` into a neutral home, or replacing `_research_program_row_to_dict` with a
public read method, is a **cross-layer** change (it edits `research/`) and is therefore
out of DG-4's authorization → **DG-5**, classified YELLOW.

### §10d `_is_extract_spec` — triplicated across three layers

```text
persistence/repositories.py:1820   def _is_extract_spec(spec) -> bool      # used at :2089
research/extraction.py:309         def _is_extract_spec(spec) -> bool      # used at  :368
research/gateway.py:3231           def _is_extract_spec(spec) -> bool      # used at  :3266
```

All three implement the same normalised comparison against `EXTRACT_TEMPLATE`, and the
repository copy's docstring states the intent: "the same comparison the gateway applies at
admission (V6-P7-E01), so admission and the write path never disagree." That invariant is
today maintained by **three independent copies of a predicate whose divergence is exactly
the failure it is meant to prevent**. This is the strongest structural finding in the
gate — and it is *not* a repository seam: the owning constant is
`research/extraction.py:59`, and the admission copy sits in the gateway's EXTRACT
admission path (authority-adjacent). Consolidating it edits three layers and one
admission predicate. **RED for DG-4; the single highest-value item for DG-5.**

---

## §11 Database / table ownership

Writers discovered by literal-SQL scan (statement forms `INSERT INTO` / `UPDATE` /
`DELETE FROM`; two regex tokens — `last_heartbeat`, `timestamps` — were column names, not
tables, and are excluded):

| Table | Writers | Atomic invariant |
| ----- | ------- | ---------------- |
| `projects` | `repositories.py` (`ProjectRepository`) | lifecycle/mode transitions own their tx (`:154`, `:219`, `:286`, `:327`) |
| `tasks` | `repositories.py`, `research/controller.py`, `research/gateway.py` | **three layers**; task lifecycle is the gateway's task-binding contract |
| `task_dependencies` | `repositories.py` | written with `tasks` inside one tx |
| `artifacts` | `repositories.py`, `research/gateway.py` | content-addressed; `UNIQUE(content_hash)` global (migration 1) |
| `provenance_edges` | `repositories.py`, `source_outcomes.py` | the N9 resolution substrate (§12) |
| `events` | `repositories.py` (`_append_event_to_db`), `migrations.py` (schema copy only) | append-only; must commit with the mutation that caused it |
| `scheduler_lock` | `persistence/database.py`, `research/controller.py` | the single-writer lease; two layers |
| `operator_credentials` | `repositories.py` | authority material |
| `research_programs` | `repositories.py` | head-only supersession, content-addressed versioning |
| `research_claims`, `research_assumptions` | `repositories.py` | one-shot acceptance, immutable |
| `empty_result_artifacts` | `repositories.py` | content-addressed, `UNIQUE(project_id, content_hash)` |
| `validation_verdicts`, `program_requirement_satisfactions` | `program_obligations.py` | **no own transaction** (participants, §4b) |
| `provider_interactions` | `provider_interactions.py` | **no own transaction**; content-keyed and idempotent by design |
| `contradictions` | `research/gateway.py` | gateway-exclusive; `BEGIN IMMEDIATE` at `gateway.py:2412` |
| `curated_knowledge_entries` | `research/gateway.py` | gateway-exclusive; one atomic admission (`gateway.py:2054`) |
| `curated_knowledge_retraction_basis` | `research/gateway.py` | gateway-exclusive; written with the retraction basis in one tx (`gateway.py:1151`) |
| `curated_knowledge_supersession` | `research/gateway.py` | gateway-exclusive |
| `evidence_ladder_state` | `research/controller.py` | Controller-owned floor transitions (`controller.py:2788`) |
| `schema_version` | `migrations.py` | forward-only |

No table is written by two *transactions*: multi-writer tables are written by different
layers on **different code paths**, never concurrently, which is why the lease exists.
Nothing here supports "one repository per table" (explicitly forbidden in §26).

---

## §12 N9 safety

The retraction invariant lives in two module-level predicates in `source_outcomes.py`:

```text
_source_artifact_resolves(conn, project_id, content_hash, artifact_type,
                          *, upstream_task_id=None) -> bool     :96–156
source_artifact_retracted(conn, project_id, artifact_id)       -> bool   :159–…
```

`_source_artifact_resolves` additionally carries the project-scoping model for source
artifacts: the artifact row is **global** (`content_hash` UNIQUE), so ownership is
**edge-carried** — resolution requires reachability from a task of the project through
`derived_from` edges (hop 1 or hop 2), and with `upstream_task_id` given, from *that*
task (`R01`). `S6-A1` makes the ref prefix part of resolution so a `source_result:` ref
can never dereference a `source_payload` row.

Consumers (re-derived, not quoted from prior reports):

```text
_source_artifact_resolves   persistence/failure_classifications.py, persistence/repositories.py:51,
                            research/gateway.py, tests/test_provider_orchestration.py:845
source_artifact_retracted   persistence/failure_classifications.py:50, :378, :411,
                            research/contradiction_candidates.py:16, :62,
                            research/gateway.py:65, :2262,
                            tests/test_n9_retraction_admission.py:43, :241, :261, :262, :340, :341
```

**Verdict: RED / NOT-A-SEAM.** Both take `conn` and execute SQL against the caller's
snapshot; `repositories.py:51` imports `_source_artifact_resolves` eagerly while
`source_outcomes.py:777` imports back lazily (cycle pair (a)), so relocation would disturb
the exact topology that currently holds. More decisively: they are the predicate surface
of a protected invariant, and §17 requires conservative classification. Tests import them
directly (`test_n9_retraction_admission.py`, `test_provider_orchestration.py:845`), so an
inventory of what must be pinned exists — and none of it needs to move.

---

## §13 Project-isolation analysis

Three distinct scoping models coexist, all intentional:

1. **Explicit `project_id` column scoping.** `ArtifactRepository.exists_in_project`
   (`repositories.py:906-916`), `metadata_json_by_hash`, `program_obligations.py:100-106`
   (`WHERE artifact_id = ? AND project_id = ?`), `failure_classifications.py:625-626`
   (`WHERE content_hash = ? AND artifact_type = ? AND project_id = ?`).
2. **Edge-carried scoping** (source artifacts): §12 above.
3. **Global-by-key, caller-scoped** — `ArtifactRepository.get_by_hash`
   (`repositories.py:881-890`) filters on `content_hash` **only**, with no `project_id`.
   This is `SD-04`'s documented content-addressing rule, reused inside
   `SourceOutcomeRepository._commit` (`source_outcomes.py:728`) and in
   `failure_classifications.py:272`. Project ownership there is supplied by the *caller*
   (task binding + the project-scoped INSERT), not by the lookup.

Model 3 is the same contract S-3 certified for the L2 resolver (`global-by-key` +
caller-side emission). **It must not be "corrected" here** — and the selected candidate
touches none of it: `_proposed_set` takes no `project_id` and issues no query, and
`_verify_reused_row` compares caller-supplied dicts. A candidate that *does* touch model 3
(a pre-BEGIN reuse check, or a project-filtered variant of `get_by_hash`) would be RED,
because it would change which rows a write path can see.

---

## §14 Authority / security analysis

The repository layer **verifies** authority material and **never decides admission**:

| Concern | Site | Owner of the decision |
| ------- | ---- | --------------------- |
| credential storage/verify | `repositories.py:959` (`pbkdf2$sha256$` format), `_operator_token_hash` (`:987-999`), `_token_hash_matches` (`:1019-1060`), `OperatorCredentialRepository.register` (`:1078`), `.verify` (`:1112`) | repository verifies the token; **Controller/Gateway** decide whether the intent is admitted |
| timing equalisation | `_burn_dummy_operator_work` (`:1007-1017`) | repository; imported privately by `tests/test_cli.py`, `tests/test_controller.py`, `tests/test_q04_gate_replay.py`, `tests/test_q05_ratification_consumers.py` → **RED** |
| HumanDecision | `research/verdict_decisions.py` (S-2, certified) using `_append_event_to_db` | Gateway |
| lease / single writer | `database.acquire_writer_lock:94`, `release_writer_lock:131`, `get_lock_owner:163`, `scheduler_lock` writes in `database.py` **and** `controller.py:2330`; fenced writes via `Controller._FencedConnection` (`controller.py:121-193`, `_is_write:148`) | Controller |
| project admission | none in persistence; gateway project gate | Gateway |

**Ordering claim, verified:** no persistence module participates in the
`credential/decision → mutation` ordering other than as the target of a mutation the
Controller/Gateway has already authorised. The write paths that *do* contain authority
re-checks (`source_outcomes._validate_task_binding`, `program_obligations` project check)
run **inside** the caller's transaction — i.e. authority ordering is deliberately
*re-verified at the persistence boundary*, not relocated there.

**Consequence:** any candidate that would move `register`/`verify`/`_token_hash_matches`/
`_burn_dummy_operator_work`, or that would let a write path perform its own credential or
HumanDecision check, is RED — including all of `database.py`'s lease functions (they are
transaction owners *and* the fencing mechanism).

---

## §15 Failure / rollback analysis

Observed rollback idioms (all guarded, all inside the owning function):

| Failure point | Durable state | Event state | Rollback owner | Candidate impact |
| ------------- | ------------- | ----------- | -------------- | ---------------- |
| `_proposed_set` (pre-BEGIN, `:292`) | none | none | n/a — no transaction yet | **none** — pure arithmetic on in-memory objects |
| `_resolve_idempotency` read (`:690-697`) | none | none | `record` | refusal (`DIVERGENT` → `SourceOutcomeConflictError` at `_commit:697-704`) must stay inside the tx |
| `_verify_reused_row` raise (`:800-861`) | nothing written for that record | none | `SourceOutcomeRepository.record` (`:305`, `:308`) | the raise must abort the tx; relocating the *function* does not change that, but it is a rollback-relevant boundary → YELLOW, deferred |
| artifact `INSERT` mid-loop (`_commit:735-760`) | partial rows until rollback | none | `record` | atomic-all-or-nothing across records + edges + retraction events |
| edge `INSERT OR IGNORE` (`:761-767`) | — | — | `record` | same tx |
| retraction audit event (`:771-790`) | — | `SourceRetracted` | `record` | **must commit with the outcome row** — the documented "observation and event are one atomic fact" |
| `ResearchProgramRepository.record` late failures | — | — | 6 rollback sites (`:1516-1563`) | supersession/version invariants |
| `ClaimAssumptionRepository.record_extraction` | — | — | 4 rollback sites (`:2146-2283`) + `_validate_supersede_target` (`:2311-2327`) | one-shot acceptance; note the three rollbacks raised from a *helper* — see Q22 |
| `EventRepository.append_transactional` retry | — | — | `BEGIN → ROLLBACK → BEGIN → COMMIT` (`:803-823`) | two attempts, documented `retry_without_project` |
| journal-failure | mutation already applied | event insert fails | the owning transaction | today the mutation is rolled back with the event — any extraction must not alter that |
| lease loss | — | `lock_lost` + rollback (`controller.py:2362`) | Controller | not a repository seam |

No candidate in §17 changes a rollback boundary. The one candidate *inside* a rollback
scope (`_verify_reused_row`) is deferred rather than authorised, precisely so this gate
never has to argue that moving a raising helper is rollback-neutral.

---

## §16 Test architecture

The persistence surface is characterised by integration tests, not unit tests of internals:

| Test file | Lines | What it proves for persistence |
| --------- | ----: | ------------------------------ |
| `tests/test_repositories.py` | 322 | task/project repositories, lifecycle invariants, `advance_iteration` |
| `tests/test_q05_persistence.py` | 1522 | the Q-05 persistence slice end-to-end |
| `tests/test_provider_orchestration.py` | 2442 | `SourceOutcomeRepository.record` one-shot semantics: **OB-01 divergence (`DIVERGENT`)**, identical re-acceptance (`IDENTICAL`), fetch retry with changed observation metadata being IDENTICAL, `_source_artifact_resolves` (imported at `:845`) |
| `tests/test_concurrency.py` | — | single-writer lease, lock contention |
| `tests/test_failure_injection.py` | — | rollback/failure behaviour |
| `tests/test_n9_retraction_admission.py` | — | N9 predicates directly (`:241-262`, `:340-341`) |
| `tests/test_program_obligations.py` | — | verdict/satisfaction identity (`validation_verdict_id_of`, `satisfaction_id_of`) |
| `tests/test_chg2_providers.py`, `test_p4_wiring.py`, `test_provider_fetch.py`, `test_provider_hazards.py`, `test_provider_ratelimit.py`, `test_provider_walk.py`, `test_hr04_source_identifier_capture.py` | — | provider interaction persistence, source identifier capture |
| `tests/test_database.py` | — | migrations, pragmas, lock helpers |

**Private-helper test coupling (9 sites, all pre-existing):**

```text
_append_event_to_db        test_controller.py:3257, test_q05_evidence_ladder.py:494/522/707,
                           test_s1_detector_rows.py:212, test_s5_retraction.py:102
_research_program_row_to_dict  test_controller_q02.py:966
_migrate_2_to_3            test_database.py:268
_source_artifact_resolves  test_provider_orchestration.py:845
```

**Coupling specifically for the selected candidate: none.** `_proposed_set`,
`_verify_reused_row`, `_prepare_search` and `_fetch_outcome_metadata` are imported by
**zero** test files (verified by repository-wide search), so relocating the selected symbol
cannot break a test import and cannot require editing a test — an unusually clean
characterization surface, and the decisive practical reason it is the cheapest safe seam.

**Missing characterization (to be added by the implementation gate, §20):**
`_proposed_set` has no direct test; it is only exercised indirectly through
`SourceOutcomeRepository.record`'s `IDENTICAL`/`DIVERGENT` outcomes. Three additive pins
close that gap.

---

## §17 Negative map

Every meaningful candidate considered, with the reason it is not GREEN. (Redundancy is
intentional: the point of a negative map is that a future agent finds *its* idea here.)

| # | Candidate | Location | Class | Why |
| - | --------- | -------- | ----- | --- |
| N-1 | `ProjectRepository.create` | `repositories.py:154` | RED — tx owner | owns `BEGIN`/`COMMIT`/`ROLLBACK` |
| N-2 | `ProjectRepository.transition_lifecycle` / `transition_mode` / `advance_iteration` | `:219` / `:286` / `:327` | RED — tx owner | read+validate inside `BEGIN IMMEDIATE` (`F-01`) |
| N-3 | `TaskRepository.create` / `transition_status` / `invalidate` | `:400` / `:538` / `:646` | RED — tx owner | same; `invalidate` feeds the S5 cascade |
| N-4 | `EventRepository.append_transactional` | `:803-823` | RED — tx owner, journal | two-attempt `BEGIN`/retry; five test files import the writer family |
| N-5 | `ResearchProgramRepository.record` | `:1502-1627` | RED — tx owner + identity authorship | `content_hash_of`/`program_id_of`/`validate_program_epistemic` re-derivation inside the tx; 6 rollbacks |
| N-6 | `ClaimAssumptionRepository.record_extraction` | `:2066-2296` | RED — tx owner + identity | `claim_id_of`/`assumption_id_of` verification inside the tx |
| N-7 | `ClaimAssumptionRepository._validate_supersede_target` | `:2306-2330` | RED — rollback boundary | the only rollback-only *participant*: it rolls back the **caller's** transaction |
| N-8 | `EmptyResultArtifactRepository.record` | `:2468-2483` | RED — tx owner + identity | `empty_result_id_of`/`empty_result_content_hash_of` |
| N-9 | `FailureClassificationRepository.record` | `failure_classifications.py:233-341` | RED — tx owner | `content_hash` identity + evidence resolver |
| N-10 | `classifications_digest` | `failure_classifications.py:633-795` | RED — read path of a certified digest | consumed at `controller.py:624`; advisory digest, but relocating changes nothing |
| N-11 | `_evidence_resolver` / `dereference_failure_classification_ref` | `:388` / `:610` | RED — N9-adjacent resolver | calls `source_artifact_retracted` (`:378`, `:411`) |
| N-12 | `SourceOutcomeRepository.record` | `source_outcomes.py:268-309` | RED — tx owner | `BEGIN IMMEDIATE` at `:294` |
| N-13 | `_resolve_idempotency` | `source_outcomes.py:682-700` | RED — snapshot-bound read | observes post-BEGIN state; defines `NEW`/`IDENTICAL`/`DIVERGENT` |
| N-14 | `_validate_task_binding` | `source_outcomes.py:471-671` | RED — snapshot-bound + authority-adjacent | re-checks the producing task inside the tx (V6-P7-A2) |
| N-15 | `_commit` | `source_outcomes.py:704-798` | RED — the only writer of this slice | records + edges + retraction events in one tx |
| N-16 | `_prepare_search` / `_prepare_fetch` | `:864` / `:903` | NOT-A-SEAM | in-tx record constructors; already perform no I/O, so extraction relocates nothing |
| N-17 | `_search_outcome_metadata` / `_fetch_outcome_metadata` | `:988` / `:1015` | NOT-A-SEAM | already free functions (no `self` parameter) |
| N-18 | `_sha256` | `:451-454` | NOT-A-SEAM | already a `@staticmethod`; the local `hashlib` import is deliberate |
| N-19 | `_source_artifact_resolves` | `source_outcomes.py:96-156` | RED — N9 + snapshot | `conn`-taking read; 4 consumer modules + a test import; part of cycle pair (a) |
| N-20 | `source_artifact_retracted` | `source_outcomes.py:159-…` | RED — N9 predicate | consumed by gateway in-tx (`gateway.py:2262`) and `contradiction_candidates.py:62` |
| N-21 | `SourceRepos` / `read_payload` | `:185-226` | NOT-A-SEAM | a façade over three repositories; splitting it creates an interface for its own sake |
| N-22 | `_append_event_to_db` | `repositories.py:92-128` | RED — journal owner | already the single writer; 7 test files + `research/verdict_decisions.py` depend on it |
| N-23 | `_operator_token_hash` / `_token_hash_matches` / `_burn_dummy_operator_work` / `register` / `verify` | `repositories.py:987-1134` | RED — authority | credential verification + timing equalisation; 4 test files import `_burn_dummy_operator_work` |
| N-24 | `acquire_writer_lock` / `release_writer_lock` / `get_lock_owner` | `database.py:94-170` | RED — lease + tx owner | the single-writer mechanism and its fencing |
| N-25 | `migrate_to_latest` + `_migrate_*` | `migrations.py:1145-1168` | RED — tx owner, forward-only schema | 18 sequential migration functions; splitting them is churn with a schema risk |
| N-26 | `validate_event_type` / `validate_payload_size` / `validate_no_secrets` | `event_validation.py:63-136` | NOT-A-SEAM | already the pure pre-INSERT gate with a single consumer path |
| N-27 | `_json_dumps` / `_json_loads` | `repositories.py:80-89` | YELLOW → DG-5 | shared across layers **as private symbols** (`gateway.py:1487`, `failure_classifications.py:448…`) |
| N-28 | `_research_program_row_to_dict` / `_claim_row_to_dict` / `_assumption_row_to_dict` | `repositories.py:1756-1783` | YELLOW → DG-5 | row→dict mappers consumed by `research/completion.py:63` and `controller.py` as private symbols; the clean fix is a public read method, not a relocated helper |
| N-29 | `_is_extract_spec` | `repositories.py:1820-1831` | RED for DG-4 (DG-5) | triplicated predicate (§10d); consolidation edits gateway admission |
| N-30 | `validation_verdict_id_of` / `satisfaction_id_of` | `program_obligations.py:53-60`, `:166-175` | RED — identity authorship via upward import | persistence authors durable ids using `research.programs` primitives |
| N-31 | `ValidationVerdictRepository.record` / `ProgramRequirementSatisfactionRepository.record` | `program_obligations.py:76-163`, `:187-304` | RED — transaction participants | no own `BEGIN`; reached from `controller.py:3020`; moving them changes who shares the caller's snapshot |
| N-32 | `persist_interaction` / `make_persisting_sink` / `ProviderInteractionRepository` | `provider_interactions.py:32-247` | RED — transaction participants + content-keyed writer | documented idempotency justification; sink closure is passed into live provider execution |
| N-33 | `create_backup` / `restore_backup` / `retain_last_n` | `backup.py:51-267` | NOT-A-SEAM | filesystem, lease-checking, not repository structure |
| N-34 | split `repositories.py` into per-domain modules | whole file | FORBIDDEN | no ownership boundary exists: the mutations, events, identities and rollbacks share one connection and one snapshot (§5) |
| N-35 | introduce a repository interface / unit-of-work / transaction manager | — | FORBIDDEN | §26 |
| N-36 | every persistence→research import (§10) | 16 sites | YELLOW/RED → DG-5 | items 1/4/10/12/15 are evaluated **inside** certified transaction bodies |
| **G-1** | **`SourceOutcomeRepository._proposed_set`** | **`source_outcomes.py:456-467`** | **GREEN — authorized** | see §18/§19 |
| G-2 | `SourceOutcomeRepository._verify_reused_row` | `source_outcomes.py:800-861` | YELLOW — deferred | pure, but in-tx and raises; requires its own gate |

---

## §18 Candidate comparison

The `§18` table the gate requests, reduced to the candidates that survived the negative
map plus the two that did (one of which is deferred):

| Candidate | Function | Region | Mechanism | Tx preserved? | Authority preserved? | Identity preserved? | Journal preserved? | Refusal preserved? | Isolation preserved? | Verdict |
| --------- | -------- | ------ | --------- | ------------- | -------------------- | ------------------- | ------------------ | ------------------ | -------------------- | ------- |
| G-1 | `SourceOutcomeRepository._proposed_set` | `source_outcomes.py:456-467` (12 lines) | R2 local helper decomposition → module-level private fn | yes — runs *before* `BEGIN` at `:294`, and opens none | yes — no credential/decision code | yes — consumes hashes, authors none | yes — no event touch | yes — raises nothing | yes — no query, no `project_id` | **GREEN — authorized** |
| G-2 | `SourceOutcomeRepository._verify_reused_row` | `source_outcomes.py:800-861` (61 lines) | R2 | yes (no I/O) but **inside** `_commit` | yes | verification only | yes | **no** — raises `SourceOutcomeIntegrityError` at 4 sites | yes | **YELLOW — deferred to its own gate** |
| N-27 | `_json_loads` / `_json_dumps` | `repositories.py:80-89` | R1 module move | n/a | n/a | n/a | n/a | n/a | n/a | **YELLOW — cross-layer, DG-5** |
| N-29 | `_is_extract_spec` (×3) | 3 modules | dedup | n/a (predicate) | **touches admission** | n/a | n/a | refusal-equivalent (write refusal) | n/a | **RED for DG-4 — DG-5** |
| N-19/N-20 | N9 predicates | `source_outcomes.py:96`, `:159` | R1 | no (conn-bound reads) | n/a | consumer/verify | n/a | n/a | **isolation-critical** | **RED** |
| N-22 | `_append_event_to_db` | `repositories.py:92` | R1 | journal owner | n/a | event author | **is** the journal | n/a | n/a | **RED** |
| N-24 | lease locks | `database.py:94`, `:131` | — | tx owners | **is** the lease | n/a | n/a | n/a | n/a | **RED** |
| N-30 | `*_id_of` in persistence | `program_obligations.py:53`, `:166` | R1 | participant | n/a | **authors identity** | n/a | n/a | n/a | **RED** |

Selection rule applied (§25): among GREEN-class candidates, prefer fewer callers →
`_proposed_set` (1) and `_verify_reused_row` (1) tie; fewer invariants → `_proposed_set`
(one frozenset derivation vs four integrity verdicts); smaller semantic surface →
`_proposed_set` (12 lines vs 61); no transaction ownership → tie (neither owns one, but
`_proposed_set` does not even run **inside** one); no identity authorship → tie; no journal
→ tie; no research inversion → tie; no private-test import → tie; smaller test surface →
`_proposed_set`. **G-1 wins every discriminating criterion.**

---

## §19 Selected implementation seam

```text
G-1  GREEN — IMPLEMENTATION AUTHORIZED (one seam only)

symbol        SourceOutcomeRepository._proposed_set
source        src/hermes/persistence/source_outcomes.py:456-467   (12 lines)
destination   module level, SAME FILE — inserted after
              source_artifact_retracted (ends :180), two blank lines,
              before the @dataclass(frozen=True) class SourceRepos
new shape     def _proposed_set(outcome: object, outcome_kind: str) -> frozenset[str]
caller        source_outcomes.py:292  →  proposed = _proposed_set(outcome, outcome_kind)
signature     (self) dropped; parameter order, defaults, annotations,
              docstring and body otherwise unchanged
new module    none        new import   none        __all__ change   none
production diff  1 file, 2 hunks (~13 added / ~12 removed)
test diff        tests/test_provider_orchestration.py, append-only (3 pins, §20)
```

**Why this is a genuine seam and not cosmetics.** `_proposed_set` is declared as an
instance method but never touches `self`. It is therefore *already* a free function of
`(outcome, outcome_kind)`; the class merely hosts it, which (a) advertises a false
dependency on a repository instance, and (b) makes "this computation performs no I/O" a
convention rather than a mechanically checkable property. After the move, that property is
enforced by a pin (§20, pin 2) in the same way S-4 made the S5 closure's purity executable.
The unit is also the smallest thing in the package that satisfies every §7/§8 criterion:
**0 reads, 0 writes, 0 SQL, 0 events, 0 refusals, 0 identity authorship, 0 `project_id`,
runs before `BEGIN IMMEDIATE`, and no test imports it.**

**Second-order benefit (stated because it is real, not to inflate the change):** after the
move, `SourceOutcomeRepository` contains **exactly one** remaining self-less method
(`_verify_reused_row`), which makes the *next* gate's candidate trivial to locate
mechanically instead of by inspection.

**Deliberately NOT included.** `_verify_reused_row` (G-2) is the natural sibling and is
**not** authorized: it raises `SourceOutcomeIntegrityError` at four sites inside `_commit`'s
transaction. Moving a raising helper out of a rollback scope is a question this gate does
not need to answer, so it is deferred to its own gate with its own pins (§18, §17 G-2).

**Honest alternative — the case for `NO SAFE REDUCTION`.** A reviewer can reasonably
prefer `DG-4 — NO SAFE REPOSITORY REDUCTION` on two grounds: (i) the gain is structural
explicitness, not coupling reduction — net file length will grow slightly; (ii) the symbol
has exactly one caller and is 12 lines long, so the blast radius of leaving it alone is
zero. That reading is **defensible and was weighed**. It was not chosen because the
alternative to authorizing it is not "leave the file as it is" but "the same extraction
happens later, informally, without a brief" — and because DG-3C/S-4 established the
precedent that a mechanically-pure, transaction-free unit is worth making structurally
explicit while the proof is cheap. Nothing else in the repository layer is authorized by
this choice.

---

## §20 Implementation brief

```text
Candidate ID        G-1
Exact source lines  src/hermes/persistence/source_outcomes.py:456-467
Exact destination   module level in the same file, between :180 and the
                    `class SourceRepos` declaration
Current caller(s)   exactly one — source_outcomes.py:292 (inside
                    SourceOutcomeRepository.record, BEFORE BEGIN IMMEDIATE at :294)
New caller shape    proposed = _proposed_set(outcome, outcome_kind)
Inputs              outcome: object (an in-memory search/fetch outcome),
                    outcome_kind: str ("search" | anything else → fetch branch)
Outputs             frozenset[str] — the outcome-record hash plus every
                    per-result / per-payload content hash
Free variables      outcome_record_hash (module import, :45), getattr,
                    frozenset, set.add
Transaction         none — the function opens none and receives no conn
Transaction snapshot  not applicable — it performs no read, and its call site
                    precedes the transaction
Identity            CONSUME only (authors nothing, hashes nothing itself)
Journal             none
Authority           none (no credential / HumanDecision / lease code)
N9                  unrelated (no retraction predicate, no provenance read)
Project isolation   none introduced, none removed — takes no project_id and
                    issues no query; scoping remains caller-side
Exception behaviour unchanged — the function raises nothing
Required characterization tests   3 additive pins (§below)
Expected production diff          +13 / −12 in source_outcomes.py (2 hunks)
Expected test diff                append-only block in
                                  tests/test_provider_orchestration.py
Forbidden changes   every item in §21, and specifically: do NOT convert it to a
                    @staticmethod (that keeps the misleading `self.` dispatch and
                    defeats the purpose); do NOT touch _verify_reused_row; do not
                    add a module, an import, a cache, a log line, or a project
                    filter; do not reorder the branches; do not replace
                    `outcome_record_hash` with an inline hash
Rollback plan       revert the single commit; the change is self-contained and
                    has no migration, schema or data surface
```

### Characterization pins (exactly three, additive)

**P-DG4-1 — semantics equivalence.** With small hand-built outcome objects: a search
outcome with two `per_provider` results → exactly `{outcome_record_hash(o,"search")} ∪
{r.content_hash ×2}`; a fetch outcome with `per_source` entries → the `f.artifact.content_hash`
set; empty result list → the singleton hash-set; observation-only differences (timestamps,
logs) → **unchanged** set; repeated calls are equal and `frozenset`-typed.

**P-DG4-2 — purity / containment.** (a) signature check: the module-level function takes
`(outcome, outcome_kind)` only — no `self`, no `conn`; (b) AST-level assertion that its
code contains none of `conn`, `.execute`, `BEGIN`/`COMMIT`/`ROLLBACK`, `_append_event`,
`EventType`, `_reject`, `hashlib`, `uuid`, `time` (node-wise so the docstring cannot be
mistaken for code — the S-4 pin pattern); (c) no duplicate ownership:
`not hasattr(SourceOutcomeRepository, "_proposed_set")` and
`source_outcomes._proposed_set` is the object `record` uses.

**P-DG4-3 — call-site equivalence.** Through the *real* `SourceOutcomeRepository.record`
path (reusing the file's existing fixtures): identical re-acceptance stays `IDENTICAL`
(reuse, no duplicate rows) and a changed aggregate stays `DIVERGENT`
(`SourceOutcomeConflictError`), and the value compared inside `_resolve_idempotency` equals
`_proposed_set(outcome, kind)` for the same inputs. No existing assertion is modified.

---

## §21 Forbidden scope

Explicitly **not** authorized by DG-4, at any later time without a new gate:

* splitting any repository class (§17 N-34);
* moving, merging or retiring any of the 25 transaction owners (§4);
* moving `_append_event_to_db` or any event construction (§9);
* moving or rewriting `_source_artifact_resolves` / `source_artifact_retracted` (§12);
* moving `_verify_reused_row` (G-2 — needs its own gate);
* consolidating `_is_extract_spec` (§10d) — **DG-5**, because it edits the gateway's
  EXTRACT admission path;
* relocating `_json_loads`/`_json_dumps` or `_*_row_to_dict` (§10c) — **DG-5**, cross-layer;
* touching any persistence→research import (§10) — **DG-5**;
* changing `get_by_hash`'s global-by-key semantics or adding a project filter to it (§13);
* touching `program_obligations.py` / `provider_interactions.py` write paths (§4b);
* correcting `docs/ARCHITECTURE.md:140` — **recommended for the DG-5 report**, not this one;
* any dependency injection, unit-of-work, transaction manager, repository interface,
  event bus, ORM, CQRS, service layer, registry or plugin machinery (§26);
* any change outside `source_outcomes.py` + the three additive pins.

---

## §22 Validation

Read-only gate: **no production or test change was made.** All five required gates were run
on the unchanged tree at `0f86189`.

| Gate | Command | Result |
| ---- | ------- | ------ |
| full suite | `.venv/Scripts/python.exe scripts/run_tests.py -q` | **exit 0**, output reached `[100%]`, **zero `F`/`E` markers**, no failures/errors/skips introduced. The pytest summary line is suppressed by the host-venv teardown issue already documented in `scripts/run_tests.py` — hence the explicit exit-code capture below |
| collected count | `python -m pytest --collect-only -q` (summed) | **2057 tests in 63 files** — identical to the S-4 certified baseline; no test added, removed or renamed |
| ruff | `uvx ruff check src tests` | `All checks passed!` |
| pyright | `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| profiled gate | `./scripts/profiled_gate.sh` | **exit 0** — `profiled typecheck + walking-skeleton smoke: OK`; the single pre-existing warning `tests/test_research_program.py:141:23 - warning: Instance methods should take a "self" parameter (reportSelfClsParameterName)` is unchanged and in a file this gate does not touch (same warning documented by S-3 and S-4) |
| diff hygiene | `git diff --check` | clean |
| working tree | `git status --short` | only the five pre-existing untracked items (`IDEA.md`, `Prompts/`, `orci.json`, `orhead.json`, `ortree.json`) |

No failure was pre-existing-vs-caused ambiguity: the suite passes, so nothing needed
explaining away, and no production code was modified to make a gate green.

---

## §23 Adversarial review — 30 questions

| # | Question | Verdict | Evidence / disposition |
| - | -------- | ------- | ---------------------- |
| 1 | Did we inventory every persistence module? | **PASS** | 10 modules, §3 (incl. `__init__.py`); AST walk of `src/hermes/persistence/**` |
| 2 | Every repository class? | **PASS** | 40 classes enumerated with method counts, §3 |
| 3 | Every transaction owner? | **PASS** | 113 executed control calls → 25 acquisition owners + 1 rollback-only participant, §4 |
| 4 | Distinguish repository-owned from gateway-owned? | **PASS** | §4 table split by layer (persistence 16 / gateway 5 / Controller 4) |
| 5 | Verify boundaries from source, not docs? | **PASS** | D-1 refuted from AST evidence; four doc claims tested, §2 |
| 6 | Identify transaction-snapshot-dependent reads? | **PASS** | §7a lists 7 read classes with their observation points |
| 7 | Identify all identity authorship? | **PASS** | §8: `uuid.uuid4` ×8, `validation_verdict_id_of`, `satisfaction_id_of`, verification sites, authority hashing |
| 8 | Identify all journal writers? | **PASS** | §9: one writer `_append_event_to_db:92`, 13 in-package call sites + 3 research callers + 7 test importers |
| 9 | Preserve `mutation → event → commit` ordering? | **PASS** | §9 + §15: no candidate changes it; `source_outcomes.py:779` verified inside `:294…:302` |
| 10 | Inspect rollback behaviour? | **PASS** | §15 failure matrix; note `EventRepository.append_transactional` 2×`BEGIN` and `_validate_supersede_target`'s 3 rollbacks |
| 11 | Inspect duplicate semantics? | **PASS** | one-shot `NEW`/`IDENTICAL`/`DIVERGENT` (`_resolve_idempotency:682`), `UNIQUE(project_id, content_hash)` per-table, idempotent reuse |
| 12 | Inspect project isolation? | **PASS** | §13: three coexisting models, all intentional |
| 13 | Inspect N9-sensitive paths? | **PASS** | §12: predicates + all consumers re-derived |
| 14 | Inspect authority ordering? | **PASS** | §14: repository verifies, Controller/Gateway decides; lease/fence mapped |
| 15 | Inspect lazy persistence→research imports? | **PASS** | §10: all 16 sites, eager vs lazy classified, 3 cycle pairs |
| 16 | Distinguish pure helpers from domain logic? | **PASS** | §6 classification + §10b three-question test |
| 17 | Distinguish pure helpers from transaction-bound reads? | **PASS** | §7b vs §7c (`_source_artifact_resolves` named explicitly) |
| 18 | Identify artificial seams that should remain intact? | **PASS** | N-16/N-17/N-18/N-21/N-26/N-33 |
| 19 | Complete negative map? | **PASS** | §17: 38 candidate rows — 36 rejected, G-1 authorized, G-2 deferred |
| 20 | Avoid line-count decomposition? | **PASS** | §14 rejects splitting `repositories.py` despite 2754 lines / 19 classes |
| 21 | Avoid broad repository splitting? | **PASS** | N-34 forbidden; §21 |
| 22 | Avoid transaction-manager abstractions? | **PASS** | §21; no new abstraction is proposed anywhere in the brief |
| 23 | Avoid changing certified behaviour? | **PASS** | zero production diff in this gate; §19 restricts the future one |
| 24 | Avoid changing public API semantics? | **PASS** | the selected symbol is private, has one caller, no `__all__`, no test import |
| 25 | Inspect test coupling to private helpers? | **PASS** | §16: 9 pre-existing private imports; **0** for G-1 |
| 26 | Identify what must be pinned before future extraction? | **PASS** | §20 three pins for G-1; G-2 deferred pending its own pins |
| 27 | Separate DG-4 decisions from DG-5? | **PASS** | §10/§10c/§10d → DG-5; §21 forbids acting on them here |
| 28 | Select at most one first seam? | **PASS** | exactly one (G-1); G-2 explicitly deferred, not co-authorized |
| 29 | Could an implementer execute it without extra permission? | **PASS** | §20 fixes destination, shape, caller, pins, diff size, rollback and forbids the `@staticmethod` variant by name |
| 30 | If no safe seam exists, prove why? | **NOT APPLICABLE** (a seam exists) — the proof obligation is discharged instead by §17's 36 rejected candidates |
| 31 | Mistake line count for coupling? | **PASS** | §0/§6: the criterion is the `self`-surface, not size |
| 32 | Move anything depending on SQLite isolation? | **PASS** | §7a — nothing snapshot-dependent is authorized |
| 33 | Change lock acquisition timing? | **PASS** | `database.py:94/131` + `controller.py:2330` untouched |
| 34 | Change exception propagation / rollback scope? | **PASS** | G-1 raises nothing; `_verify_reused_row` (which does) is deferred precisely for this reason |
| 35 | Create a module cycle or new public API? | **PASS** | no module, no import, no `__all__`, no package export |
| 36 | Merely relocate complexity instead of reducing coupling? | **PASS (qualified)** | For G-1 the gain is *explicitness + enforceability*, not coupling reduction — stated plainly in §19 rather than dressed up. All candidates where relocation would only move complexity (N-16…N-21, N-26, N-33) are classified NOT-A-SEAM |

**Unresolved / qualified items — explicit disposition (required before the gate closes):**

* **Q36 (qualified).** The selected seam is a *structural-explicitness* reduction, not a
  coupling reduction. Disposition: accepted and disclosed; §19 states the
  `NO SAFE REPOSITORY REDUCTION` alternative in full so a reviewer can overrule it.
* **Documentation drift D-1/D-2/D-4.** Disposition: **not repaired here** (that would be a
  documentation change outside §28's allowance). Recommended disposition: fold the
  corrected transaction-owner model into the **DG-5** report, which will already be
  editing the inversion documentation.
* **`_prompts`/`Prompts/`, `IDEA.md`, `orci.json`, `orhead.json`, `ortree.json`.**
  Disposition: external/untracked, never read for authority, never staged.

**No `FAIL` was recorded. No unresolved item blocks the verdict.**

---

## §24 Final verdict

```text
DG-4 — REPOSITORY DESIGN GATE PASSED / ONE SEAM AUTHORIZED
```

Authorized: **one** seam only — `SourceOutcomeRepository._proposed_set`
(`src/hermes/persistence/source_outcomes.py:456-467`) becoming module-level private
`_proposed_set(outcome, outcome_kind)` in the same file, with the three additive
characterization pins in §20.

Not authorized by this verdict: any second seam (including the sibling
`_verify_reused_row`), any repository class split, any transaction-owner movement, any
event/resolver/identity/authority relocation, the `_is_extract_spec` triplication
consolidation, the cross-layer private-helper imports, the persistence→research inversion,
the `ARCHITECTURE.md` drift correction, and everything listed in §21.

**DG-5 status:** required, not optional. DG-4 hands it three concrete, evidence-backed
items (§10): the 16-site inversion with the cycle-pair topology that holds it together,
the three-way duplicated `_is_extract_spec` predicate that currently protects the
"admission and write path never disagree" invariant by copy-synchronisation, and the two
research modules reaching into persistence's private namespace.

**The gate's durable product is the negative map (§17).** The repository layer is now
*provably* not decomposable along its visible lines of responsibility — 36 rejected
candidates with per-candidate reasons — which forecloses a whole class of future
well-intentioned refactors that would otherwise look mechanically attractive.
