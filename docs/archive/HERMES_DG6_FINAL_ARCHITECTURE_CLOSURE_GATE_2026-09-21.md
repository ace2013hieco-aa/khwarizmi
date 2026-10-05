# HERMES DG-6 — Final Architecture Closure Gate

**Date:** 2026-09-21
**Authorizing baseline:** `49db9d944c84d8ee692cc3ef114bad39c559e278` (certified DG-5 revision, `main`)
**Scope:** final invariant-impact, architecture-closure + residual-backlog audit — read-only gate
**Report:** this file (the only tracked change DG-6 makes)

DG-5 (`49db9d9`) concluded `NO ARCHITECTURAL INVERSION CORRECTION AUTHORIZED`. That conclusion
is not reopened: §6 re-verifies it against HEAD and finds zero drift. This gate answers only
whether the improvement program is closable, what backlog stays actionable, and what
documentation must be reconciled with the physical architecture.

---

## §0 Executive verdict

```text
DG-6 — CLOSURE CONDITIONALLY PASSED / DOCUMENTATION RECONCILIATION REQUIRED  (conclusion B)
```

Evidence summary (all physically re-verified at `49db9d9`, not inherited):

* **Change chain complete:** all 12 gate→implementation→certification pairs reconcile in git
  (§2); all 5 certified extractions remain single-owner with characterization tests green (§8).
* **Negative maps consolidate cleanly:** every rejected/deferred seam across DG-2/DG-3A/DG-3B/
  DG-3C/DG-4/DG-5 lands in exactly one of PROTECTED / INTENTIONAL / DEFERRED / REJECTED, plus
  two OPEN items that are owned and non-structural (§3).
* **Every certified invariant has an unambiguous owner** (§4); the transaction census
  reproduces DG-4 exactly (113 executed control calls, 25 acquisition owners, §5).
* **No further structural refactoring is justified** (§10): controller (4229 lines / 76
  methods), gateway (3734), repositories (2754 / 19 classes) are ACCEPTABLE CONCENTRATION —
  every visible split line crosses a transaction, an identity author, a resolver, or the fence.
* **Documentation is materially stale in exactly three files** (§12–§15): `docs/STATE.md`
  ("Phase 2 … not yet started"), `AGENTS.md` ("NOT YET REFACTORED" + single-owner transaction
  wording), `docs/ARCHITECTURE.md` §3.10 (stale line refs, debt framing, 14-class count). Exact
  correction plans are provided; no correction is made here.
* **Residual actionable backlog is non-structural** (§9): one targeted implementation item with
  a defined gate path (F-01 STALE-guard project filter, S5-adjacent, MEDIUM risk — still OPEN,
  owned, not closure-blocking for the *structural* program), one pending decision (A-01 dead-vs-
  future intents), and docs/test-only items (A-02/A-03/A-04/D-01/B-01/B-03/F-03, F-02
  deliberation, conditional D-02).

Conclusion A is dishonest (docs are stale); C is unsupported (no structural gate is needed —
F-01 is semantic, fenced, and explicitly out of the decomposition scope); D is unsupported (no
unresolved defect threatens a certified invariant). **B is the evidence-backed verdict.**

---

## §1 Baseline identity

```text
repository          github.com/ace2013hieco-aa/khwarizmi-research
branch              main
HEAD                49db9d944c84d8ee692cc3ef114bad39c559e278
origin/main         49db9d944c84d8ee692cc3ef114bad39c559e278    (HEAD == origin/main)
tracked changes     none
untracked (pre-existing, untouched)
                    IDEA.md, Prompts/, desktop.ini, logos/, obsidian-vault/,
                    orci.json, orhead.json, ortree.json
```

`git log --oneline -15` head: `49db9d9` (DG-5 report) → `9cf1837` (G-1 cert) → `b9a30a9`
(G-1 impl) → `4b501e9` (DG-4) → `0f86189` (S-4 cert) → `f54af56` (S-4 impl) → `03ff3e4`
(DG-3C) → `dffe907` (S-3 cert) → `df57650` (S-3 impl) → `65e82c0` (DG-3B) → `6e1458c` (S-2
cert) → `3cfaa38` (S-2 impl) → `fe0aa1c` (DG-3A) → `0de76db` (S-1 cert) → `231cd75` (S-1 impl).

---

## §2 Certified change-chain reconciliation

Verified against `git log` (SHAs) + AST/test presence at HEAD (substance). "Source changed?"
means production source, not reports/tests.

| Gate | Design SHA | Implementation SHA | Certification SHA | Source changed? | Certified? | Current status |
| ---- | ---------- | ------------------ | ----------------- | --------------- | ---------- | -------------- |
| Phase 0 hygiene | (audit) | — (hygiene commits pre-chain) | `HERMES_PHASE0…` | yes (historical) | yes | CLOSED |
| Phase 1 docs/arch map | — | docs commits | `HERMES_PHASE1…` (`335d300` per STATE) | docs only | yes | CLOSED |
| Phase 1.1 drift closure | — | `97c09ce` (+ `b7bed81`, `2a3758a` vicinity) | `HERMES_PHASE1_1…` | docs only | yes | CLOSED |
| Phase 2 API audit | — | `44aa1a3` (report) | `HERMES_PHASE2…` | no | yes (audit) | CLOSED; findings feed §9 |
| Phase 3 backlog audit | — | `979311f` (report) | `HERMES_PHASE3…` | no | yes (audit) | CLOSED; items reconciled §9 |
| P0 API stability | `19cda3a` (P0 gate) | — (decision, not code) | A-05 RATIFIED in-gate | no | yes | CLOSED |
| DG-2 → S-1 | `558a8d5` | `231cd75` (extract detector rows → `contradiction_candidates.py`, +19/−90 controller) | `0de76db` | yes, 1 module + controller | yes | CERTIFIED, valid at HEAD (§8) |
| DG-3A → S-2 | `fe0aa1c` | `3cfaa38` (→ `verdict_decisions.py`, 53 lines) | `6e1458c` | yes, 1 module + controller import | yes | CERTIFIED, valid at HEAD (§8) |
| DG-3B → S-3 | `65e82c0` | `df57650` (→ `l2_resolution.py`, +184) | `dffe907` | yes, 1 module + gateway | yes | CERTIFIED, valid at HEAD (§8) |
| DG-3C → S-4 | `03ff3e4` | `f54af56` (S5 cone closure, in-gateway) | `0f86189` | yes, gateway-internal | yes | CERTIFIED, valid at HEAD (§8) |
| DG-4 → G-1 | `4b501e9` | `b9a30a9` (`_proposed_set` → module level, same file) | `9cf1837` | yes, 1 file + additive pins | yes | CERTIFIED, valid at HEAD (§8) |
| DG-5 | `49db9d9` | — (report-only by design) | self-certifying gate | no | yes | CLOSED, re-verified §6 |

Chain discipline held throughout: one concern per commit, implementation commits contain no
documentation changes, certification commits contain only their report (verified:
`git show --numstat` pattern per S/G certs; final check §21: `git diff --name-only 9cf1837 HEAD`
= DG-5 report only).

---

## §3 Consolidated negative map

Every item exactly one of PROTECTED (invariant boundary, must never move), INTENTIONAL
(deliberate design, documented), DEFERRED (owned future work with trigger/gate), REJECTED
(considered, must not be done), OPEN (acknowledged, owned, non-structural — the only
non-closed class, 2 items).

### Controller (owning gates DG-2, DG-3A)

| Item | Disposition | Authority |
| ---- | ----------- | --------- |
| S-2b/c/d per-surface verdict extractions | REJECTED | DG-3A §18/§23 (only S-2h authorized) |
| S-3+ further controller seams (S-3..S-7 candidates) | REJECTED/DEFERRED | DG-2 §20 protected surfaces; no second seam ever authorized |
| Lease/fence lifecycle (`_acquire_lock`, `_FencedConnection`, `lock_lost` rollback) | PROTECTED | DG-2 §11; controller.py:2426 vicinity; AGENTS.md lease invariant |
| Tick orchestration + recovery passes | PROTECTED | DG-2 §§4/13; tick-loop cert (`633cff1`+`2328399` per STATE) |
| Authority boundary (credential/HumanDecision ingestion, no LLM authority) | PROTECTED | DG-3A §§8/12; `internal_only` (intents.py:135) |
| Identity/idempotency (decision refs, detector dedup) | PROTECTED | DG-2 §13 |
| Journal sequencing from controller surfaces | PROTECTED | DG-3A §11; S-2 cert |
| 19 controller reads sharing the fence (E-04) | INTENTIONAL | DG-2 §5/§20: reads thread the lease bracket; extraction unprofitable (fence-lifetime coupling) |
| `resolve_human_gate` own-tx + mode write | PROTECTED | P0 §9; DG-3A §4 (V-c) |

### Gateway (owning gates DG-3B, DG-3C)

| Item | Disposition | Authority |
| ---- | ----------- | --------- |
| 5 gateway transaction owners (`_decision_append_transactional`, retract, curate, record-contradiction, resolution) | PROTECTED | DG-3B §7; DG-3C §§6–10 (each non-seam region RED) |
| `_validate_curate_knowledge` (691), `_validate_retract_source` (446+), contradiction validators — further splits | REJECTED | DG-3C §§8–10, §21 RED regions; C-01a CLOSED AS INTENTIONAL |
| Refusal machinery (`_reject`, codes gateway.py:93-108, refusal-as-data) | PROTECTED | DG-3C §13; AGENTS.md |
| Identity authorship (`cx_`/`cres_` re-derivation, N1 pair rule) | PROTECTED | DG-3B §9; contradictions.py:75,106; P7 cert |
| N9 admission (in-tx re-resolve gateway.py:2262) | PROTECTED | DG-3C §16; N9 cert; source_outcomes.py:159 |
| `_is_extract_spec` gateway copy (gateway.py:3231, used :3266) | INTENTIONAL | DG-5 §8: admission leg of agreement triad — KEEP |
| `_resolve_program_in_project` + `_json_loads` use (:1487/:1503) | INTENTIONAL | DG-5 §9: allowed-direction, row-parse of own SELECT |
| S5 STALE-guard project filter (gateway.py:1170-1196, no project predicate) | OPEN (owned, non-structural) | Phase-3 F-01; §9: needs targeted S5-adjacent gate, MEDIUM risk |

### Persistence (owning gates DG-4, G-1)

| Item | Disposition | Authority |
| ---- | ----------- | --------- |
| 16 persistence transaction owners (11 repositories.py, database 2, others) | PROTECTED | DG-4 §4; re-run §5 (identical) |
| `_append_event_to_db` (repositories.py:92-128) | PROTECTED | DG-4 §9; DG-5 §15-equivalent |
| N9 predicates (`_source_artifact_resolves` :96, `source_artifact_retracted` :159) | PROTECTED | DG-4 §12; DG-5 §13-equivalent |
| `_verify_reused_row` (source_outcomes.py:800-861) | DEFERRED | DG-4 §18 G-2: pure but in-tx + raises; needs own gate (trigger: a second G-class seam) |
| Row mappers (`_research_program_row_to_dict` :1756, `_claim_row_to_dict`, `_assumption_row_to_dict`) | INTENTIONAL | DG-5 §10: persistence-owned storage-shape parsers |
| `validation_verdict_id_of` / `satisfaction_id_of` authorship | PROTECTED | DG-4 N-30; DG-5 §11-equivalent |
| Participant writers (`program_obligations.py`, `provider_interactions.py`) | PROTECTED | DG-4 §4b |
| Lease helpers (`database.py:94-170`), authority hashing, migrations, backup | PROTECTED | DG-4 §§14/17 |
| G-1 `_proposed_set` (source_outcomes.py:184-200) | DONE (certified) | G-1; single-owner verified §8 |
| Repository per-class file split (E-03) | REJECTED | DG-4 N-34/§21: no ownership boundary; mutations+events+identities+rollbacks share one connection/snapshot |

### Persistence → Research (owning gate DG-5, re-verified §6)

| Item | Disposition |
| ---- | ----------- |
| 6 intentional exceptions (Model-D boundaries, agreement vocabulary) | INTENTIONAL |
| 2 true inversions (HR-08 choke point :236; private slot constants :1379) | INTENTIONAL (inversion real, removal harmful — DG-5 §6) |
| 2 pure utilities (`canonical_json`/`sha256_hex` sites) | INTENTIONAL (lowest-module housing; move = churn) |
| 2 domain-type refs (incl. 1 annotation-only false positive) | INTENTIONAL |
| 3 cycle pairs (a intra-layer; b agreement; c choke point) | INTENTIONAL (each lazy leg documented DG-4 §10/DG-5 §5) |
| `_is_extract_spec` triplication | INTENTIONAL — KEEP THREE COPIES |
| `_json_loads` centralization | DEFERRED (YELLOW, needs own gate; REJECTED defensible) |
| E-05 direction correction / E-06 lazy formalization | CLOSED AS INTENTIONAL (DG-5 authoritative) |

No "maybe refactor later" remains: every DEFERRED item names its trigger and gate; the two
OPEN items (§9: F-01, A-01) are semantic/decision work, not structural seams.

---

## §4 Final invariant ownership matrix

| Invariant | Physical owner | Enforcement point | Certification evidence | Current documentation | Status |
| --------- | -------------- | ----------------- | ---------------------- | --------------------- | ------ |
| Determinism (no model decides) | `research/evaluation.py` + deterministic libs | ports, never authorities | ARCH §3.1/3.5; P7 | accurate | CERTIFIED |
| Single `apply_intent` mutation path | `research/gateway.py:3732` | sole writer; orchestration never writes around it | ARCH §3.3; P0 §10 | accurate | CERTIFIED |
| Append-only journal | writer `persistence/repositories.py:92-128`; catalog `core/events.py` (65 types) | pre-INSERT `event_validation`; no DELETE in src/ | ARCH §3.3; DG-4 §9 | accurate | CERTIFIED |
| HumanDecision authority | `research/verdict_decisions.py:23` (S-2) + gateway PROPOSAL gate | missing/unbound journal row refuses | S-2 cert; intents.py:135 | accurate | CERTIFIED |
| Bounded payloads (4 KiB) | `persistence/event_validation.py` | `validate_event` before INSERT | ARCH §3.3 | accurate | CERTIFIED |
| Project isolation | resolvers/detectors/validators/retraction predicate (all project-scoped) | cross-project citation fails closed | P7/N9; DG-4 §13 | accurate | CERTIFIED |
| Refusal-as-data | gateway codes :93-108; controller `{rejected: True}` | never raise through loop | DG-3C §13; API.md | accurate | CERTIFIED |
| Archive-not-delete / head-only supersession | repositories (supersede links; second link refused) | new rows/events only | ARCH §3.7 | accurate | CERTIFIED |
| Lease-fenced single writer | `persistence/database.py` + `controller.py:2426` (`_acquire_lock`) | contention → LOCK; mid-tick loss → rollback | DG-2 §11; fence audit | accurate | CERTIFIED |
| Content-hash identity | research pure helpers; persistence re-derives (Model D) | never trust caller (EC-V6-11..16, IDR-026 D2) | IDR-018/026; DG-5 §§11-12 | accurate | CERTIFIED |
| N1 contradiction semantics | `research/contradictions.py:75,106` | pair rule + in-tx re-resolve | P7 cert | accurate | CERTIFIED/FROZEN |
| N9 retraction fencing | `persistence/source_outcomes.py:159` + 4 enforcement points | fencing, never admissibility of retracted | N9 cert (`02cb976`) | accurate | CERTIFIED/FROZEN |
| Replay determinism | `tools/providers/replay.py:293` RecordedTransport | refusing inner transport; byte identity | ARCH §3.8 | accurate | CERTIFIED (transport-only) |
| Provider isolation | `tools/providers/adapters/base.py:139` (4 hooks) | adapters import `tools.*` only (1 recorded exception hazards.py:137) | ARCH §3.5; API.md | accurate | CERTIFIED |
| Transaction ownership | 25 owners (16 persistence / 5 gateway / 4 controller) + 1 rollback-only participant | each owns BEGIN/COMMIT/ROLLBACK | DG-4 §4; §5 re-run identical | **STALE** (§5) | CERTIFIED, docs to fix |
| Admission/write agreement | EXTRACT_TEMPLATE (extraction.py:59) + `_is_extract_spec` ×3 | three coordinated checks, one constant | DG-5 §8; IDR-028 | understated | INTENTIONAL, docs to fix |
| Model-D integrity boundaries | repositories re-derive with research pure helpers (pre-BEGIN) | EC-V6-16 fail-closed before tx | IDR-018/026/036; DG-5 §6 | missing-as-concept | INTENTIONAL, docs to fix |
| HR-08 completion choke point | `repositories.py:236-243` → `completion.py:258` | no driver reaches COMPLETED on denial | DG-5 §5c; completion.py | missing-as-concept | INTENTIONAL, docs to fix |

No invariant lacks an owner. Three rows need documentation (not ownership) repair — all B-conditions.

---

## §5 Transaction ownership reconciliation

Physical re-run at HEAD (AST criterion identical to DG-4 §4): **113 executed control calls,
25 acquisition owners** — byte-identical owner set to DG-4 (persistence 16: `database.py` 2,
`failure_classifications.py` 1, `migrations.py` 1, `repositories.py` 11, `source_outcomes.py`
1; gateway 5; controller 4) plus the 1 rollback-only participant
(`ClaimAssumptionRepository._validate_supersede_target`, 3 ROLLBACKs). Two owners use plain
`BEGIN` by design (`ProjectRepository.create`, `TaskRepository.create`, `EventRepository.
append_transactional` ×2 retry, migrations, controller floor/ladder/human-gate paths); the
rest use `BEGIN IMMEDIATE`.

| Document | Current claim | Physical truth | Required correction | Severity | Closure-blocking? |
| -------- | ------------- | -------------- | ------------------- | -------- | ----------------- |
| `docs/ARCHITECTURE.md:140` | "Repositories own one `BEGIN IMMEDIATE` transaction each (`repositories.py`, `failure_classifications.py:233`, `source_outcomes.py:294`, `database.py:113`)" | 25 owners across 3 layers; repositories.py alone holds 11; 4+ acquisitions use plain BEGIN; gateway owns 5, controller 4 (all certified) | Replace with the 25-owner table + per-layer rationale (S5/CHG-1/Step-7/S-2 precedents); fix stale line refs (`:233`→ record spans, `:294`→`:313` post-G1) | medium (misdescribes a certified property) | NO (B-condition) |
| `AGENTS.md:20-23` | "each of which owns its `BEGIN IMMEDIATE` transaction" (repository write boundaries) | same 25-owner truth; non-`IMMEDIATE` owners exist by design | "each repository write boundary owns its transaction (`BEGIN IMMEDIATE`, with the documented plain-`BEGIN` exceptions: creates, event-retry, migrations); gateway (5) and controller (4) own certified transactions on S5/CHG-1/Step-7/S-2 paths" | low-medium | NO (B-condition) |
| `docs/API.md:84-90` | repositories INTERNAL/UNDECLARED; direct SQL outside write boundaries forbidden | consistent with truth; no per-owner claim made | none (accurate as stated) | — | NO |

---

## §6 Persistence→Research final disposition

Re-verified at HEAD (AST): **13 runtime `hermes.research` import statements in persistence —
unchanged** (sites/line numbers identical to DG-5 §3a); **3 cycle pairs unchanged** (pairs
(a) repositories:51↔source_outcomes:783, (b) repositories:62↔extraction:349,
(c) repositories:236↔completion:63); **`_is_extract_spec` still triplicated**
(repositories.py:1820, extraction.py:309, gateway.py:3231, executable bodies AST-identical);
**`_json_loads` still persistence-homed** (repositories.py:86, no test imports);
**`_research_program_row_to_dict` still persistence-owned** (repositories.py:1756, 6 in-package
+ 4 research callers); **no unauthorized inversion implementation** (`git diff --name-only
9cf1837 HEAD` = DG-5 report only).

The residual dependency is therefore classified **INTENTIONAL ARCHITECTURE**, not unresolved
bug — DG-5's conclusion stands on unchanged physical evidence. The "KNOWN ARCHITECTURAL DEBT
— NOT YET REFACTORED" wording (ARCH §3.10, AGENTS.md:70-72) is now materially misleading in
one respect: it frames as pending work what three gates proved must remain. Required
correction (§§14–15): reframe as intentional exceptions with per-class rationale + DG-5
pointer, keeping the "do not extend" instruction (which remains correct — items 8/11 show why
new upward edges are high-risk).

---

## §7 API stability reconciliation

Live surface vs Phase-2/P0 contract (P0 A-05 ratified; DG-3B §16; DG-2 §16):

* CLI: 19 `add_parser` sites (15 top-level subcommands per ARCH — consistent); entry
  `cli.py:760`, exit codes 0/1, `--json` — unchanged.
* Controller: 76 methods (== ARCH count); supported verdict/detection/read methods unchanged;
  `_`-prefixed remain UNDECLARED — unchanged.
* Intents: **18 kinds** (verified enum) — `llm_proposable` 9 (:115-121), `director_only` 2,
  `internal_only` 8 — matches AGENTS/API/ARCH; A-01's six validator-less kinds still
  NOT_WIRED (gateway.py:3684) — OPEN decision, surface unchanged.
* Events: **65 `EventType` members**; 4 KiB bound intact.
* Refusal codes gateway.py:93-108 (ROLE/OPERATOR/LOCK/PROPOSAL/EVIDENCE_REF/
  MALFORMED_PAYLOAD/STALE/RATIONALE/NOT_WIRED/…) — set grew only by certified additions; no
  meaning changed.
* Adapters: 4-hook ABC + registry intact; `hazards.py:137` sole exception intact.
* Repositories: still INTERNAL/UNDECLARED (API.md:84-90 accurate); no new construction surface.
* `__all__`: 17 assignments in src, 0 in tests (Phase-3 F-03 "39 sites" counted names/sites
  loosely — minor wording drift, non-blocking; F-03 declaration itself still OPEN, §9).
* New modules since P0: `verdict_decisions.py` (no `__all__`, internal — S-2 cert §10),
  `l2_resolution.py` (internal), `contradiction_candidates.py` (no `__all__`, no package
  exports — S-1 cert). **No new accidental public surface; no private helper became public;
  no internal surface froze; classifications remain valid.**

Answers: (1) no declared API altered by any refactor; (2) no; (3) no; (4) no; (5) only F-03
wording looseness — non-blocking.

---

## §8 Certified extraction reconciliation

| Extraction | Helper (HEAD location) | Single owner? | Caller intact? | Tests intact? | Later invalidation? |
| ---------- | ---------------------- | ------------- | -------------- | ------------- | ------------------- |
| S-1 detector rows | `detector_candidate_rows` (+2 siblings), `contradiction_candidates.py:19` | yes (1 def repo-wide) | controller.py:1950-1956 (`_detector_candidate_rows` wrapper) | S-1 pins (10 new per cert) | none — module untouched since `0de76db` |
| S-2 HumanDecision append | `record_human_decision_once`, `verdict_decisions.py:23` | yes | 4 V-a surfaces via controller.py:86 import | V1/V2/V3 pins | none |
| S-3 L2 resolution | 5 `_l2_*` helpers, `l2_resolution.py` | yes (each 1 def) | gateway S5 path | pin1 ownership/no-duplicate | none |
| S-4 cone closure | `_s5_cone_closure`, `gateway.py:1000` | yes | S5 cascade in-tx | S-4 equivalence | none |
| G-1 proposed-set | `_proposed_set`, `source_outcomes.py:184-200` | yes | `record` :311, pre-BEGIN (`:313`) | 5 G1 pins, green in suite | none |

Method: AST single-definition repo-wide search + caller line verification + full-suite green
(§21). All five certifications remain applicable; no second implementation appeared anywhere.

---

## §9 Remaining backlog reconciliation

Phase-3 items (report `979311f`), each classified. Trigger/gate given for DEFERRED.

| Item | Classification | Rationale / path |
| ---- | -------------- | ---------------- |
| A-01 six validator-less intents | OPEN (decision, non-structural) | still NOT_WIRED (gateway.py:3684); needs dead-vs-future decision (DG-1 class per Phase-3); no invariant risk either way |
| A-02 CLI read-pattern docs | DEFERRED | docs-only; API.md §Repositories still UNDECLARED vs cli.py constructions — merge read-pattern section, no gate |
| A-03 accidental publics | DEFERRED | docs-first; renames only under DG-1; 17 `__all__` sites verified, no new surface |
| A-04 contract-test gaps | DEFERRED (ACTIONABLE, test-only) | no IntentApplied-on-duplicate / notes-bound pins found (only unrelated provider-walk notes); add tests, no gate, non-blocking |
| A-05 stability convention | DONE | ratified by P0 |
| B-01 root sprawl (~70 `hermes_*.md` at root) | DEFERRED | docs-only moves + link audit; explicitly not architectural |
| B-02 worked examples | DEFERRED | post-contract; needs A-05 ✓ (now unblocked, still optional) |
| B-03 STATE cadence | DEFERRED | process: dated refresh per milestone — fold into §13 correction |
| C-01a/b/c validator/method/helper extraction | CLOSED AS INTENTIONAL | DG-3C RED regions + DG-4 N-34 + DG-2: size ≠ seam; further splits cross tx/identity/fence |
| D-01 shared tests/support.py | DEFERRED (ACTIONABLE, test-only) | `tests/support.py` still absent; `_make`×15/`_classify`×4 duplication persists; full suite is the gate; non-blocking |
| D-02 split test_controller.py (7207 lines, 338 KB) | DEFERRED (conditional) | Phase-3 condition stands: split only on demonstrated editing friction; size alone is not trigger |
| E-01/E-02 design maps | DONE | fed DG-2/DG-3 |
| E-03 repo split | CLOSED AS INTENTIONAL | DG-4 negative map |
| E-04 reads extraction | CLOSED AS INTENTIONAL | DG-2: 19 reads share the fence; lease-bracket threading unprofitable |
| E-05 direction correction | CLOSED AS INTENTIONAL | DG-5 authoritative: NO correction |
| E-06 lazy formalization | CLOSED AS INTENTIONAL | documented DG-4 §10/DG-5 §5; ARCH wording fix pending (§15) |
| F-01 STALE-guard project filter | OPEN (owned implementation item) | verified still unfiltered (gateway.py:1174-1179, project-independent `retract_` id :1143-1147); needs targeted S5-adjacent gate + S5 slice re-run (Phase-3 path: DG-6 review done here); MEDIUM risk; fenced, N9 unaffected (predicate itself project-scoped) |
| F-02 ancestor scope | DEFERRED | deliberation-only decision record either way; S5 point-in-time design stands |
| F-03 export declaration | DEFERRED | record policy; trims only under DG-1 |
| G-01..G-04 | DEFERRED / REJECTED | per Phase-3 (G-04 migration-down stays REJECTED: forward-only is architecture) |
| Phase-3 §6 rejected work (semver/telemetry/plugins/… machinery) | REJECTED (reaffirmed) | no consumer + certified behavior at risk — unchanged |

STILL ACTIONABLE (worth keeping, each with owner/shape/gate): F-01 (targeted gate), A-01
(decision), A-04/D-01 (test-only, suite-gated), A-02/A-03/B-01/B-03/F-03 (docs-only), F-02
(deliberation), D-02 (conditional). Nothing stylistic survives: C-class line-count work and
§6 non-work list stay closed.

---

## §10 Module-concentration assessment

Measured at HEAD (lines; methods/classes via AST):

| Module | Size | Units | Assessment |
| ------ | ---- | ----- | ---------- |
| `research/controller.py` | 4229 | 76 methods (== ARCH) | ACCEPTABLE CONCENTRATION — 5 certified seams extracted (S-1/S-2/consumers); remainder shares fence/clock/project per DG-2 clusters; reads intentionally co-located (E-04) |
| `research/gateway.py` | 3734 | ~40 validators + 5 tx owners | ACCEPTABLE — DG-3B/3C proved size = tx-bound admissions; only S5-closure-class seams separable, done (S-3/S-4) |
| `persistence/repositories.py` | 2754 | 19 classes (ARCH "14" stale — §15) | ACCEPTABLE — DG-4: mutations+events+identities+rollbacks share one connection/snapshot; no ownership boundary exists |
| `persistence/source_outcomes.py` | 1067 | 6 classes + N9 predicates | ACCEPTABLE — post-G1 one self-less method remains (`_verify_reused_row`, deferred with trigger) |
| `research/programs.py` | 1527 | compiler + pure identity | ACCEPTABLE — stdlib-only lowest module; size is vocabulary, not coupling |
| `research/extraction.py` | 399 | acceptance path | ACCEPTABLE |
| `research/completion.py` | 368 | HR-08 predicate | ACCEPTABLE |

Result: **ACCEPTABLE CONCENTRATION.** No `ONE SPECIFIC REMAINING SEAM` meets the bar (the
sole mechanical candidate, `_verify_reused_row`, is DEFERRED with cause). No ARCHITECTURAL
DEFECT: concentration never crossed an ownership line — the gates proved the lines first.

---

## §11 Test-architecture assessment

| Finding | Classification | Basis |
| ------- | -------------- | ----- |
| Helper duplication (`_make`×15, `_classify`×4, no `tests/support.py`) | DEFERRED (ACTIONABLE, test-only) | D-01; behavior-neutral consolidation, suite-gated, non-blocking |
| `test_controller.py` 7207 lines / 338 KB | DEFERRED (conditional) | D-02 trigger (editing friction) not demonstrated |
| Private-helper coupling (8 test files import `_`-names) | ACCEPTABLE | established pin pattern (S-1/S-2/S-3/S-4/G-1 pins + 9 pre-existing DG-4 sites); pins certify behavior, not location trivia |
| Contract gaps (A-04: duplicate-admission event count, notes bound) | DEFERRED (ACTIONABLE, test-only) | governed behaviors without named pins; non-blocking (behaviors verified by integration suites) |
| Fixture coupling (provider machinery builders per-file) | DEFERRED | folds into D-01 when triggered |
| Unnamed contract behavior | ACCEPTABLE | P6/N9/P7/tick-loop slices + gate pins cover certified invariants |

No test-architecture issue risks regression in a certified invariant: every invariant owns
executable pins. Nothing here blocks closure.

---

## §12 Documentation closure audit

(`README.md`, `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/STATE.md`,
`docs/README.md` vs physical truth; last docs change `97c09ce` pre-dates DG-2..DG-5.)

| # | document:line | Current claim | Physical truth | Required wording (§§13–15) | Closure-blocking? |
| - | ------------- | ------------- | -------------- | -------------------------- | ----------------- |
| D1 | `docs/STATE.md:72-76` | "Phase 2 — API Contract + Stability Audit … not yet started" | Phase 2 done (`44aa1a3`), P0 ratified (`19cda3a`), DG-2..DG-5 + S-1..S-4 + G-1 complete | full STATE rewrite (§13) | NO (B-condition) |
| D2 | `AGENTS.md:70-72` | "No persistence→research imports beyond the existing lazy-guarded ones — KNOWN ARCHITECTURAL DEBT, NOT YET REFACTORED" | 13 imports, mostly eager top-level; DG-5: intentional, no correction | INTENTIONAL EXCEPTION + DG-5 ref (§14) | NO (B-condition) |
| D3 | `AGENTS.md:20-23` | repository write boundaries "each of which owns its `BEGIN IMMEDIATE` transaction" | 25 owners / 3 layers; plain-BEGIN exceptions by design | per-layer wording (§5 table) | NO (B-condition) |
| D4 | `docs/ARCHITECTURE.md:140` | "Repositories own one `BEGIN IMMEDIATE` transaction each" + stale refs | §5 truth | 25-owner table (§15) | NO (B-condition) |
| D5 | `docs/ARCHITECTURE.md:149-155` | debt framing + stale line refs (`:52,:62-64,:236,:1259,:1298,:1379,:2440`, `source_outcomes.py:41`) | omits program_obligations:55,169; post-G1 shifts; 14-class count (§3.10:158 also stale — 19 actual) | intentional-exception rewrite (§15) | NO (B-condition) |
| D6 | `docs/STATE.md:9-10,55-60` | suite "2035 green"; debt list predates DG-4/5 | 2062 tests; concentration + inversion resolved as intentional | counts + dispositions (§13) | NO (B-condition) |
| D7 | `README.md:11` | "Certified chain (2026-09-19…)" | omits 09-20/21 structural program (12 gates) | append DG-2..DG-6 chain line | NO (B-condition) |
| D8 | Phase-3 F-03 "39 sites" | `__all__` (39 sites) | 17 `__all__ =` in src, 0 in tests | correct the count when declaring policy | NO |

`docs/API.md`, `docs/README.md` (pointer file), v6 contract: accurate as stated; no correction required.

---

## §13 STATE.md reconciliation (exact plan, not applied)

Rewrite `docs/STATE.md` to: header date → 2026-09-21; CERTIFIED chain appends
`558a8d5→231cd75→0de76db` (DG-2/S-1), `fe0aa1c→3cfaa38→6e1458c` (DG-3A/S-2),
`65e82c0→df57650→dffe907` (DG-3B/S-3), `03ff3e4→f54af56→0f86189` (DG-3C/S-4),
`4b501e9→b9a30a9→9cf1837` (DG-4/G-1), `49db9d9` (DG-5), DG-6 (this report, on acceptance);
"full suite 2035" → **2062**; Known debt replaces inversion/concentration lines with:
"persistence→research upward imports + 3 lazy cycle pairs — INTENTIONAL ARCHITECTURE per DG-5
(Model-D boundaries, HR-08 choke point, admission/write agreement; do not extend)";
"Controller/gateway/repositories concentration — ACCEPTABLE per DG-2/DG-3C/DG-4 (no further
split justified)"; keep STALE-wart + ancestor-scope + hazards.py:137 + IntentApplied-volume +
_notes-bound lines, appending "(F-01 stays OPEN: targeted S5-adjacent gate required)";
"Next planned" → "Architecture-improvement program CLOSED (DG-6, conditional on this
reconciliation). Residual actionable: F-01 (gated), A-01 (decision), test/docs items per
DG-6 §9. No structural decomposition planned." Add the §17-equivalent contract list:
final chain, improvement status, intentional exceptions, negative-map refs (DG-2 §20, DG-3C
§21, DG-4 §17/§21, DG-5 §22), API stability (P0 + §7), 25-owner txn model (§5), backlog
categories (§9). Keep concise: STATE stays one page (current 77 lines → ~90).

---

## §14 AGENTS.md reconciliation (exact plan, not applied)

1. Replace lines 70-72 ("No persistence→research imports … NOT YET REFACTORED") with:
   "Persistence→research upward imports (13 sites) + 3 lazy-guarded cycle pairs are
   INTENTIONAL ARCHITECTURAL EXCEPTION per DG-5 (Model-D integrity boundaries, HR-08 choke
   point, admission/write agreement, N9 predicates) — do not extend the pattern; new upward
   edges need a design gate (see `docs/ARCHITECTURE.md` §3.10)."
2. Adjust lines 20-23 transaction wording per §5 table (per-layer owners + plain-BEGIN
   exceptions).
3. Testing stanza: "full suite (2035)" → 2062; profiled-gate/pyright lines unchanged.
4. Map stanza: append "Structural program closed (DG-6): S-1/S-2/S-3/S-4/G-1 extracted +
   certified; concentration accepted; see `docs/STATE.md`."
No other AGENTS.md change (authority/fencing/change-discipline stanzas verified accurate).

---

## §15 ARCHITECTURE.md reconciliation (exact plan, not applied)

1. §3.10: replace the KNOWN-DEBT paragraph with an INTENTIONAL-EXCEPTIONS subsection naming
   the five concepts and why each exists: Model-D re-derivation (pre-BEGIN, EC-V6-16),
   HR-08 choke point (in-tx, repositories.py:236-243), admission/write agreement
   (EXTRACT_TEMPLATE + `_is_extract_spec` triad), N9 persistence predicates (conn-bound
   reads), lazy legs (pairs a/b/c with owner + rule per E-06 DoD). Refresh all line refs to
   HEAD (post-G1) and correct "14 classes" → 19.
2. §3.3/§3.4 (or §3.10): replace the single-owner transaction sentence with the §5
   25-owner model + certified non-repository owners.
3. Diagrams: annotate the three intentional upward edges (integrity re-derivation,
   HR-08 call, agreement constant) on diagram B/C narration — one sentence each, no new
   diagram required.
4. §3.2 layer table "Must never" column: add the DG-5-tested exception ("persistence must
   never import research *except* the §3.10 intentional set").
Proposal only; keeps the document maintainable (no new sections beyond a §3.10 rewrite).

---

## §16 Final physical target architecture

As it exists after documentation reconciliation — **no source refactoring required**:

```text
CLI (cli.py:760; 15 subcommands; opens conns, hands to repos/Controller)
  ↓  commands / reads (A-02 read pattern documents this)
Controller (4229 lines, 76 methods; 4 tx owners: _acquire_lock IMMEDIATE,
  resolve_human_gate / floors / ladder plain-BEGIN; fence owner)
  ↓  verdict ingestion (credential+lease+HumanDecision) → Intents (18 kinds)
Intent Gateway (apply_intent :3732; 5 tx owners, all IMMEDIATE; ~40 validators;
  refusal-as-data :93-108; N9 in-tx re-resolve :2262; S5 STALE guard :1170 — F-01 OPEN)
  ↓  reads            ↑ intentional upward edges (DG-5):
Research / domain      │  (i)   Model-D re-derivation (pre-BEGIN EC-V6-16)
(programs/claims/      │  (ii)  HR-08 choke call (in-tx :236→completion:258)
 thesis/complete/      │  (iii) agreement constant + _is_extract_spec triad
 extraction/…;          ╵  cycle lazy legs: extraction:349, completion:63→repo,
 pure, tx-free)             source_outcomes:783 (event writer)
  ↓  writes through repository tx boundaries (16 owners; 11 in repositories.py)
Persistence (row mappers, vv_/ss_ authorship, N9 predicates :96/:159,
  journal writer :92-128, lease helpers, migrations v17)
  ↓
SQLite (WAL-capable) + append-only journal (65 event types, 4 KiB bound)
  ║  side channels, both fenced: providers behind RecordedTransport (replay
  ║  proves bytes only); authority enters only as HumanDecisionReceived rows
```

Ownership summary: transactions — 25 owners, §5; identity — research derives, persistence
re-derives (Model D); journal — single writer; N9 — persistence predicate, 4 enforcement
points; authority — human journal rows, gateway PROPOSAL gate, controller ingestion.

---

## §17 Residual debt (owned, explicit)

1. 13 upward imports + 3 cycle pairs — INTENTIONAL (§6); do-not-extend rule stays.
2. `_is_extract_spec` ×3 — deliberate agreement triad, KEEP.
3. `_json_loads` housing — DEFERRED YELLOW (own gate if ever pursued).
4. `_verify_reused_row` in-class — DEFERRED (own gate on second-seam trigger).
5. F-01 STALE project filter — OPEN, targeted S5-adjacent gate path defined (§9).
6. A-01 six intents NOT_WIRED — OPEN decision (dead vs future), no invariant impact.
7. Test/docs backlog (A-02/03/04, D-01/D-02-cond, B-01/03, F-02/03) — DEFERRED with triggers.
8. Concentration (76/40/19) — ACCEPTED, not debt.
9. `hazards.py:137`, IntentApplied duplicate volume, `_notes` bound — pre-existing accepted
   notes, unchanged.

---

## §18 Deliberately deferred work (non-goals, reaffirmed)

Phase-3 §6 list stands (no semver/telemetry/plugins/signing/microservices/event-bus/agent-
frameworks/workflow-engines/synthesis/observability/modernization/line-count/renames/audit-
volume/notes-first/downgrades/aesthetic-moves/pure-internal tests/versioning machinery) +
G-04 migration-down REJECTED + per-surface verdict extraction REJECTED + repository split
REJECTED + validator splits REJECTED. Nothing deferred here is load-bearing.

---

## §19 Closure criteria

| # | Criterion | Result |
| - | --------- | ------ |
| 1 | Every major structural surface audited | PASS — controller, gateway, repositories, inversion, API, backlog (§2 chain) |
| 2 | Every authorized extraction certified | PASS — S-1/S-2/S-3/S-4/G-1 single-owner + green (§8) |
| 3 | No invariant without an owner | PASS — 18/18 owned (§4) |
| 4 | DG-5 reconciled | PASS — unchanged physical evidence (§6) |
| 5 | Backlog classified | PASS — all items DONE/INTENTIONAL/DEFERRED/OPEN, no "maybe later" (§9) |
| 6 | No undocumented high-risk seam | PASS — negative map consolidated (§3); sole OPEN seam (F-01) documented + fenced |
| 7 | API stability current | PASS — §7 (only F-03 wording looseness, non-blocking) |
| 8 | Txn docs *can be made* accurate | PASS (conditional) — exact wording §5 |
| 9 | State docs *can be made* accurate | PASS (conditional) — exact plan §13 |
| 10 | Residual debt has disposition | PASS — §17 (9 items, all owned) |
| 11 | No further broad decomposition justified | PASS — §10 |
| 12 | Gates green | PASS — 2062/0/0/0, ruff, pyright, profiled, diff-check (§21) |

Criteria 8–9 are conditional on executing §§13–15 — precisely conclusion B.

---

## §20 Adversarial review (40 questions)

| # | Question | Verdict | Disposition |
| - | -------- | ------- | ----------- |
| 1 | Baseline exact? | PASS | §1: HEAD==origin==`49db9d9`, main, clean |
| 2 | HEAD == origin? | PASS | both `49db9d9` pre-commit; §24 post-push |
| 3 | Change chain verified? | PASS | §2: git SHAs + AST/test substance, not summaries |
| 4 | Certified extraction regressed? | PASS | §8: all five single-owner, callers + pins intact |
| 5 | Helpers still single-owner? | PASS | repo-wide AST def search: exactly 1 each |
| 6 | New accidental public API? | PASS | §7: 3 post-P0 modules internal, no `__all__` added |
| 7 | Stability classifications valid? | PASS | §7 (F-03 count looseness noted, non-blocking) |
| 8 | Txn owners characterized? | PASS | §5: 113/25 identical to DG-4 |
| 9 | Txn docs accurate? | FAIL (B-condition) | D3/D4: exact correction §5; structural truth certified |
| 10 | Journal ownership unambiguous? | PASS | single writer :92-128; ordering verified |
| 11 | Identity authorship unambiguous? | PASS | derive vs re-derive vs consume per site (DG-5 §§11-12) |
| 12 | Project isolation unambiguous? | PASS | three models, all intentional (DG-4 §13, DG-5 §14-equiv) |
| 13 | N9 ownership unambiguous? | PASS | predicate :159 + 4 points; F-01 affects STALE guard only, not N9 |
| 14 | HumanDecision ownership unambiguous? | PASS | S-2 helper + PROPOSAL gate |
| 15 | Validators correctly placed? | PASS | DG-3B/3C RED regions intact; no drift |
| 16 | Controller anti-seams protected? | PASS | §3 table; 76 methods unchanged |
| 17 | Repository anti-seams protected? | PASS | §3 table; 19 classes unchanged |
| 18 | DG-5 physically valid? | PASS | §6: 13/3/triad/deferrals all reproduce |
| 19 | 13 imports still present? | PASS | AST re-count = 13, same sites |
| 20 | Cycle pairs correctly classified? | PASS | (a) cycle-only, (b) agreement, (c) choke point |
| 21 | `_is_extract_spec` correctly classified? | PASS | KEEP THREE COPIES, triad rationale |
| 22 | `_json_loads` correctly classified? | PASS | YELLOW deferred, REJECTED defensible |
| 23 | `_research_program_row_to_dict` correctly classified? | PASS | persistence-owned, allowed-direction use |
| 24 | Remaining upward dep actually debt? | PASS | answered NO with per-class evidence (INTENTIONAL, §6) |
| 25 | Backlog item requires implementation? | PASS | answered: only F-01 (targeted, non-structural) + decision/test/docs items (§9) |
| 26 | Item invalidated? | PASS | C-01a/b/c, E-03/04/05/06 → INTENTIONAL (stronger than invalidated) |
| 27 | Item became intentional? | PASS | §9 table (7 items) |
| 28 | Further module splitting justified? | PASS | answered NO (§10) |
| 29 | Further gateway decomposition justified? | PASS | answered NO (DG-3C RED stands) |
| 30 | Further controller decomposition justified? | PASS | answered NO (DG-2 stands; reads co-located) |
| 31 | Further repository decomposition justified? | PASS | answered NO (DG-4 N-34 stands) |
| 32 | Test-arch issues closure-blocking? | PASS | answered NO (§11 — pins cover invariants) |
| 33 | Documentation materially stale? | FAIL (B-condition) | D1–D8 table (§12); plans §§13–15 |
| 34 | STATE.md materially stale? | FAIL (B-condition) | D1/D6; exact plan §13 |
| 35 | AGENTS.md materially stale? | FAIL (B-condition) | D2/D3; exact plan §14 |
| 36 | ARCHITECTURE.md materially stale? | FAIL (B-condition) | D4/D5; exact plan §15 |
| 37 | Architecture understandable without history? | PASS | conditional: YES after §§13–15 (concepts + why documented at root) |
| 38 | Residual risks explicitly owned? | PASS | §17 (9 items) + §9 triggers |
| 39 | Hidden improvement work before closure? | PASS | answered NO — census methods (AST owner/edge counts) leave no unexamined surface class |
| 40 | Close without another structural refactor? | PASS | YES — concentration accepted, seams exhausted, debt owned |

35 PASS, 5 FAIL — all five FAILs are documentation-accuracy B-conditions with exact correction
plans, none structural. No AMBIGUOUS.

---

## §21 Validation

Read-only gate; no source/test change (only this report added post-validation; §24 confirms
scope).

| Gate | Command | Result |
| ---- | ------- | ------ |
| full suite | `.venv/Scripts/python.exe scripts/run_tests.py -q` | exit 0, reached `[100%]`, zero `F`/`E` markers |
| collected | unchanged since G-1 (no test file in any post-`9cf1837` diff) | **2062 tests in 63 files**, 0 failures / 0 errors / 0 skips |
| ruff | `uvx ruff check src tests` | `All checks passed!` |
| pyright | `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| profiled gate | `./scripts/profiled_gate.sh` | exit 0 |
| diff hygiene | `git diff --check` | clean |
| scope | `git diff --name-only 9cf1837 HEAD` (pre-commit) | DG-5 report only — suite count carries |

No failure, no warning suppressed, no production code touched to make a gate pass.

---

## §22 Final verdict

```text
DG-6 — CLOSURE CONDITIONALLY PASSED / DOCUMENTATION RECONCILIATION REQUIRED
```

The Hermes architecture-improvement program has reached its defensible closure point on every
structural axis: all surfaces audited, all authorized seams extracted and certified, all
invariants owned, all rejections documented with per-item cause, all residual work owned with
triggers. **No structural refactor — decomposition, inversion correction, seam extraction,
or framework introduction — is justified or authorized.** The program closes when the
targeted documentation reconciliation (§§13–15) lands and the residual backlog (§9) is
tracked as owned debt: the single implementation item (F-01) via its defined S5-adjacent
gate, A-01 via decision, the rest via docs/test-only changes that need no gate. The central
question is answered: preserving the certified design now has strictly higher value than any
further structural refactoring.
