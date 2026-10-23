# GAP1-RULINGS — design-gate record for the Part-1 gap adjudication

Dispositions of the human design gate for the Part-1 gaps adjudicated by
`AUDIT-GAP-1-TRIAGE.md`. Documentation only: this slice changes no
behavior; the queued slices below are not executed here and each runs
under its own gate discipline.

- **Input report:** `Khwarizmi Gap and Hardening Priority Report, Part 1`
  (Oct 11 2026; report base `de99ae6`, not an ancestor of this line).
- **Triage input:** `AUDIT-GAP-1-TRIAGE.md` on `audit/gap-1-triage`
  @ `1a812f0` (triage base `main@51cb10b`; verdicts: ALREADY-FIXED 6 ·
  VALID 29 · DESIGN-OWNED 2 = 37).
- **Base:** `ce415708a844d3e561d5e1eeba096429cae2ee15` (the pushed `dev`
  tip; the wave-1 landings are ancestors).
- **Scope:** rulings D1–D12, the wave-1 execution record, and the D5-A
  document-and-accept posture recorded in `docs/STATE.md`.

## 1. Rulings (D1–D12)

| ID | Topic / question | Ruling |
| :--- | :--- | :--- |
| **D1** | Journal tamper-evidence (P1-1): abort triggers now, or hash chain + re-chain? | **A — ADOPT THE TAMPER-EVIDENT JOURNAL DESIGN; STAGE S NOW.** Landed as stage S: `BEFORE UPDATE` / `BEFORE DELETE` abort triggers on `events` (TAMPER-1). The hash chain + re-chain tool is **TAMPER-2**, chartered-deferred, **NOT dropped**. Residual honesty: the triggers deter in-DB `UPDATE`/`DELETE` only; DB-file-level swap or `DROP TRIGGER` is **NOT covered** (TAMPER-2 territory). |
| **D2** | Experiment registry / declaration authority (P1-2): design now, implement now, or defer both? | **B — MERGE THE DESIGN RECORD + FIXTURE PINS ONLY.** `design/experiment-intent@331efa5` carries `docs/idr/EXPERIMENT-DECLARATION.md` + `tests/test_experiment_declaration_fixtures.py`; implementation is deferred. **Coupling:** D6's `REQUEST_ADDITIONAL_EXPERIMENT` wiring is PARKED behind D2. |
| **D3** | Task admission content/project blindness (P1-6): compare content, derive identity, or accept aliasing? | **A — FAIL-CLOSED ON CONTENT/PROJECT.** `duplicate=True` only for an exact content replay in the same project; a differing proposal and a foreign-project row refuse `IDEMPOTENCY_CONFLICT` (project checked before content), refusals-as-data. Canonical byte domain defined and pinned: `_TASK_CONTENT_FIELDS` = 13 admission fields (`task_type`, `profile`, `idempotency_key`, `iteration`, `parent_task_id`, `spec`, `inputs`, `outputs`, `dependencies`, `provenance`, `cost_class`, `concurrency_group`, `max_retries`), `dependencies` normalized as a sorted set, compact canonical JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`) over parsed structures on both sides; non-serialisable content refuses `MALFORMED_PAYLOAD`. |
| **D4** | `condition_type` never set (P2-1): add the key, remap `UNDETERMINED`, or leave it? | **A — ADD THE `condition_type` KEY + HASH-VERSION BUMP.** Queue the command-field change with the hash-version bump; the dual-read/migration posture is recorded as part of that slice. |
| **D5** | Operator-credential lifecycle boundary / key custody: document-and-accept, or open a key-custody design track? | **A — DOCUMENT-AND-ACCEPT (HUMAN OVERRIDE of the recommended B).** The boundary is accepted as-is: director-only credential intents, a single acquisition owner, archive-not-delete (revoke is terminal). No key-custody IDR unless that work is ever scoped to include key custody. The model-API-key policy (human-held, env-only, never wired) is unchanged. This is boundary acceptance, not a validity/reproducibility claim. Posture written in `docs/STATE.md`. |
| **D6** | Declared-but-unwired intent kinds (P2-8): wire, remove, or pin as declared? | **A — PIN THE DECLARED-BUT-UNWIRED KINDS.** Staged wiring couplings: `BRANCH` / `ABANDON` / `REQUEST_HUMAN` behind R2 / P1-12; `REQUEST_ADDITIONAL_EXPERIMENT` parked behind D2; `REQUEST_REPLICATION` / `PROPOSE_GATE_OVERRIDE` own gates. |
| **D7** | Credential lifecycle + token handling (P1-3/P1-4/P2-13): revoke/rotate, expiry, env vs stdin? | **A — REVOKE + ROTATE; TOKEN VIA STDIN PREFERRED OVER ENV.** Two director-only intent kinds through `apply_intent` (one new acquisition owner); revoke is terminal and archive-not-delete; legacy hashes rehash on a successful verify only; token input via stdin (`--token-stdin`), no env-var channel; **no expiry**. |
| **D8** | License/hygiene remainder (P1-7): full legal program or minimal honesty? | **A — MINIMAL HONESTY.** Path scrub, PDF audit, NOTICE trademark line, and a recorded CLA/DCO posture. |
| **D9** | Windows-only CI (P2-12): add Linux CI, keep Windows-only, or fallback-only? | **A — FULL `ubuntu-latest` CI JOB.** Windows-specific baseline-red fallout is handled as follow-up fixes; a fallback smoke job remains. |
| **D10** | HR-08 single-edge guard / SQL bypass (P2-9): structural pin now, or wait for the driver? | **A — STRUCTURAL PIN + EXPLICIT D1 DEPENDENCY.** Pin the edge set into `COMPLETED` == `{REPORTING}`. The SQL-bypass coverage claim is **VOID if D1 slips**. The pin is **HR08-PIN-1** (landed as `b722b97`; merge log `docs/MERGE-LOG-HR08-PIN-1.md`). |
| **D11** | Operator-attention throughput / decision packets (P3-10): adopt the precomputed-packet slice? | **A — VERIFY + LAND DECISION-PACKETS.** Verify then land `slice/decision-packets@eee771c` (`decision_packets.py` + tests); read-only precomputation only, the fail-closed human-authority boundary is unchanged. |
| **D12** | Audit event separate transaction (P2-7): keep the crash window, pre-validate, or fuse? | **A — SAME-TRANSACTION AUDIT APPEND.** The design note must include a census re-derivation before landing. |

## 2. Execution status, couplings, evidence

| ID | Status | Amendments / couplings | Evidence |
| :--- | :--- | :--- | :--- |
| **D1** | **LANDED** (TAMPER-1, `1556706`; merge log `02013b8` — and TAMPER-2, `c110f94`; merge log `docs/MERGE-LOG-TAMPER-2.md`) | Stage S absorbs GAP-1 P3-5: the 2→3 table rebuild re-creates the triggers. TAMPER-2 completes the design: per-event chain by migration v23 (backfilled in `event_id` order), the writer chains every append, `DROP TRIGGER` becomes a named structural finding, and `journal verify` / `journal rechain` are the explicit-only entry points. DB-file swap and tail truncation remain **anchor-dependent** (P2-4); `created_at` stays outside the preimage. | `docs/idr/TAMPER-EVIDENT-JOURNAL.md` (TAMPER-2 addendum A1-A8); `src/hermes/persistence/journal_chain.py`; `src/hermes/persistence/migrations.py` (`_migrate_20_to_21`, `_migrate_22_to_23`); `tests/test_journal_append_only_triggers.py`; `tests/test_tamper_2_journal_chain.py`; `tests/journal_tamper.py`; `docs/MERGE-LOG-TAMPER-1.md`, `docs/MERGE-LOG-TAMPER-2.md`. |
| **D2** | **LANDED** (EXPERIMENT-MERGE, `20e5d98`; merge log `d86ceeb`) | Design record + fixture pins only; implementation deferred. D6 `REQUEST_ADDITIONAL_EXPERIMENT` wiring remains parked behind this. Landing reconciliation refreshed the stale kind count 19→21 (director-only 2→4). | `design/experiment-intent@331efa5` (`docs/idr/EXPERIMENT-DECLARATION.md`, `tests/test_experiment_declaration_fixtures.py`); triage P1-2 (ancestor check: not an ancestor of base). |
| **D3** | **LANDED** (TASK-ADMIT-1, `f2b6cae`; merge log `ee09c7d`) | Intended W4 delta: re-emitted observation → `failed_typed` with `IDEMPOTENCY_CONFLICT`, sanctioned by WIRING_DESIGN BIND-1 (see §3). CLI F2 seeds repaired (no assertion weakened). | `src/hermes/research/gateway.py:4197` (`_TASK_CONTENT_FIELDS`), `:4235` (`_validate_insert_task`); `tests/test_task_admit_1_duplicate_content.py`; `docs/MERGE-LOG-TASK-ADMIT-1.md`. |
| **D4** | **LANDED** (COND-TYPE, `dc4c509`; merge log `efeb1f4`) | `condition_type` key + command-hash **v2**; v1 verify-only dual-read admits the default `UNDETERMINED` only; stored hashes never rehashed. | Triage P2-1 (base `gateway.py:3209-3215` closed keys; default `UNDETERMINED`). |
| **D5** | **LANDED** (this record + `docs/STATE.md`) | Human override of the recommended key-custody IDR; no key-custody IDR unless that work is ever scoped. Model-API-key policy unchanged. Executable credential subset delivered by D7. | §4 below; `docs/STATE.md` intentional-architecture entry; `docs/ARCHITECTURE.md` §3.10 (credential acquisition owner); `docs/MERGE-LOG-CRED-1.md`. |
| **D6** | **LANDED** (WIRE-6, `3df7dc8`; merge log `ec5af26`) | Pinned as declared with **zero `src` changes**. Couplings unchanged: `BRANCH`/`ABANDON`/`REQUEST_HUMAN` behind R2 / P1-12; `REQUEST_ADDITIONAL_EXPERIMENT` behind D2; `REQUEST_REPLICATION`/`PROPOSE_GATE_OVERRIDE` own gates. | `tests/test_wire_6_pins.py` (AST-derived dispatch coverage; the uncovered remainder is exactly the six; `NOT_WIRED` fallback and the coupling map pinned; wiring `BRANCH` or weakening the fallback fails the pin); `docs/MERGE-LOG-WIRE-6.md`. |
| **D7** | **LANDED** (CRED-1, `b989b6d`; merge log `ce41570`) | Migration 21→22 (`operator_credentials.revoked_at`); census +3 calls / +1 acquisition owner (persistence 19); rehash only on successful resolve; no expiry. | `src/hermes/core/intents.py:128-129`; `src/hermes/persistence/migrations.py:1275` (`_migrate_21_to_22`); `tests/test_cred1_credential_lifecycle.py`, `tests/test_cred1_rehash_on_verify.py`, `tests/test_cred1_token_stdin.py`; `docs/API.md`; `docs/MERGE-LOG-CRED-1.md`. |
| **D8** | **LANDED** (D8-HYGIENE, `41d1117`; merge log `3193e23`) | Minimal honesty scope only; no broader legal program. Path scrub covers live surfaces; dated evidence records keep the paths they ran with. No asset deleted or modified. | `docs/ASSET-PROVENANCE.md` (11 PDFs + 10 companions, licences recorded), `CONTRIBUTING.md` (Apache-2.0 inbound/outbound, DCO `Signed-off-by`, no CLA), `NOTICE` trademark line (no registration claimed); `docs/MERGE-LOG-D8-HYGIENE.md`. |
| **D9** | **LANDED** (LINUX-CI, `050188d`; merge log `1c12c03`) | Three additive `ubuntu-latest` jobs; Windows jobs byte-identical; first-run risk profile recorded as follow-up evidence in `docs/LINUX-CI.md`. | Triage P2-12 (CI `windows-latest` on every job); `.github/workflows/ci.yml`. |
| **D10** | **LANDED** (HR08-PIN-1, `b722b97`; merge log `docs/MERGE-LOG-HR08-PIN-1.md`) | Explicit D1 dependency: the SQL-bypass coverage claim is void if D1 slips. | Triage P2-9; `tests/test_hr08_completed_edge_pin.py`; `src/hermes/research/lifecycle.py:83`, `:114`; `src/hermes/research/completion.py:51-58`, `:315`. |
| **D11** | **LANDED** (DECISION-PACKETS, `c4f084c`; merge log `7d08c2e`) | Verified read-only precomputation (zero mutation-capable calls, no authority, project-scoped, deterministic, bounded); human-authority boundary unchanged. | `slice/decision-packets@eee771c` (`src/hermes/research/decision_packets.py`, `tests/test_decision_packets.py`; not an ancestor of base); triage P3-10. |
| **D12** | **LANDED** (AUDIT-TXN, `5ef14f8`; merge log `docs/MERGE-LOG-AUDIT-TXN.md`) | The audit row is appended **inside the mutation's transaction** on all 13 branches / 10 owners (5 persistence, 5 gateway), carried as an explicit `AuditRecord` parameter. Duplicates and rejections keep their own transaction (no mutation to strand). Census **re-derived and unchanged**: 124 / 28 (19/5/4) / 1 / 15 / 0, `BEGIN 29, COMMIT 28, ROLLBACK 67` — no governed-doc change, no B4 regeneration. | Design note: `docs/idr/IDR-013.md` addendum A1.1-A1.6 (call-path inventory, mechanism, invariants, census proof). Evidence: `tests/test_audit_txn_atomicity.py` (40 pins — forward/backward crash windows, adjacency, refusals, duplicates, chain); `src/hermes/research/gateway.py` (`apply_intent`, `_write_audit_event`); `src/hermes/persistence/repositories.py` (`AuditRecord`, 5 owners); `docs/MERGE-LOG-AUDIT-TXN.md`. |

## 3. Execution record (Waves 1–2)

Wave 1 (four slices) landed on the base commit `c368886`
(RESOLVER-PARITY-1 landing tip) as fast-forward-only local merges, then
wave 1b (four slices) restacked and landed on top; the chain was pushed
as one to `dev`. Wave 2 (six slices) landed serially on the pushed tip
with the same discipline; its per-slice evidence lives in
`docs/MERGE-LOG-*.md` and the suite chain below.

| Slice | Ruling / item | Landed tip | Merge-log commit | Scope evidence |
| :--- | :--- | :--- | :--- | :--- |
| ROLE-EXH-1 | P1-5 | `c6680b7` | `8cb9d94` | `_require_role` positive admission; 16 pins; zero current (kind, profile) decisions changed |
| TASK-ADMIT-1 | P1-6 / D3-A | `f2b6cae` | `ee09c7d` | fail-closed content/project admission; 14 pins; canonical byte domain pinned |
| TAMPER-1 | P1-1 / D1-A | `1556706` | `02013b8` | append-only triggers stage S; 9 pins; 24 tamper sites routed through one helper |
| CRED-1 | P1-3/P1-4/P2-13 / D7-A | `b989b6d` | `ce41570` | revoke/rotate + rehash-on-verify + token stdin; 31 pins; census delta |

**Suite chain (collected, `docs/SUITE-COUNT.md`):**

| Stage | Tip | Collected | Delta |
| :--- | :--- | :--- | :--- |
| Base | `c368886` | 4743 | — |
| ROLE-EXH-1 | `c6680b7` | 4759 | +16 |
| TASK-ADMIT-1 | `f2b6cae` | 4773 | +14 |
| TAMPER-1 | `1556706` | 4807 | +34 |
| CRED-1 | `b989b6d` | 4838 | +31 |
| ASSERTS-1 / FENCE-FUZZ-1 / HR08-PIN-1 / RULINGS-GAP1-1 | `6e76fee` | 4861 | +23 |
| HYGIENE-2 | `c8692e2` | 4866 | +5 |
| COND-TYPE | `dc4c509` | 4878 | +12 |
| HYGIENE-1 | `e01b636` | 4886 | +8 |
| EXPERIMENT-MERGE | `20e5d98` | 4917 | +31 |
| DECISION-PACKETS | `c4f084c` | 4929 | +12 |
| LINUX-CI | `050188d` | 4929 | 0 |

- **Wave 2 push record (`5e470fa`).**
- **Final suite at `5e470fa`:** 4926 passed / 3 skipped / 0 failed
  (collected 4929), after two cross-slice census-pin refreshes for the
  ruled COND-TYPE refusal site (MALFORMED_PAYLOAD 121→122, total
  266→267).
- **Census at `5e470fa`:** 124 transaction-control calls / 28
  acquisition owners (persistence 19), one rollback-only participant,
  15 persistence→research imports — unchanged through Wave 2.
- **Push:** `dev` advanced `6e76fee` → `5e470fa` (fast-forward,
  single-parent chain).
- **Mirror sync:** `617bcf5` (tree `668211ce`), tree-equal to the `dev`
  tip `5e470fa`.
- **Migration chain:** still **v22**; HYGIENE-1's `2 → 3` rebuild now
  uses explicit DDL (fresh-DB path only; triggers do not exist at v2).
- **W4 intended delta:** HYGIENE-1 P3-7b — a repeat human decision
  under the same correlation with different content now refuses
  `IDEMPOTENCY_CONFLICT` instead of silently returning the first;
  CRES-DIGEST replay pins aligned, digest never moves. Recorded in
  `docs/MERGE-LOG-HYGIENE-1.md`.

- **Wave 1 push record (`ce41570`).**
- **Final suite at `ce41570`:** 4835 passed / 3 skipped / 0 failed
  (collected 4838).
- **Census at `ce41570`:** 124 transaction-control calls / 28
  acquisition owners (persistence 19), one rollback-only participant,
  15 persistence→research imports — unchanged from CRED-1; constants,
  `AGENTS.md`, and `docs/ARCHITECTURE.md` §3.10 agree.
- **Push:** `dev` advanced `c368886` → `ce41570` (fast-forward,
  single-parent chain).
- **Mirror sync:** `546aba7` (tree `6a69828`), tree-equal to the `dev`
  tip `ce41570`.
- **Migration chain:** now **v22** — TAMPER-1 `20 → 21` (append-only
  triggers) and CRED-1 `21 → 22` (`operator_credentials.revoked_at`,
  nullable, no backfill); `SUPPORTED_VERSION = 22`.
- **W4 intended-delta flag:** `tests/test_wiring_w4.py::test_a_re_emitted_observation_is_idempotent`
  now pins the re-emitted record as a differing proposal —
  `failed_typed`, reason contains `IDEMPOTENCY_CONFLICT`,
  `outcome_recorded is False` — while the substantive pins hold (one
  child row, one port execution). Sanctioned by WIRING_DESIGN BIND-1
  ("re-emit is idempotent (`IDEMPOTENCY_CONFLICT` or duplicate-same-row
  per boundary)") and recorded in `docs/MERGE-LOG-TASK-ADMIT-1.md`
  §Intended delta. Not an unnoticed pin change.

## 4. D5-A posture (document-and-accept)

D5-A is a human override of the recommended option B (a key-custody
design track). The operator-credential lifecycle boundary is
documented-and-accepted as-is: credential mutations are director-only
intents admitted through `apply_intent`; the lifecycle write has a
single acquisition owner (`OperatorCredentialRepository._apply_credential_mutation`);
revoke is terminal and archive-not-delete. No key-custody IDR is opened
unless that work is ever scoped to include key custody. The
model-API-key policy (human-held, env-only, never wired) remains
unchanged. This is boundary acceptance only — not a validity,
reproducibility, or admissibility claim. The operative paragraph lives
in `docs/STATE.md` (Intentional architecture).

## 5. Claim alignment — nothing further to change

- The triage's already-fixed items (P0-1, P0-2, P1-7 core, P1-8, P2-14,
  P3-12) need no ruling text; their landing hashes are recorded in
  `AUDIT-GAP-1-TRIAGE.md`.
- Per the triage's live probes, no repo text asserts file-level journal
  tamper-evidence (D1), a shipped experiment registry (D2), a wired
  `REQUEST_ADDITIONAL_EXPERIMENT` (D6), credential expiry (D7), a Linux
  CI job (D9), hash-chain coverage (D10), or a same-transaction audit
  append (D12) — nothing to change beyond this record.

License: Apache-2.0 (LICENSE).
