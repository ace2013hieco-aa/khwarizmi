# HERMES v6 — STEP 5 TRUST-BOUNDARY REMEDIATION REPORT

Independent verifier, continuing the closure review. Step 4 concluded
**TRUST BOUNDARY SOUND WITH P2 HARDENING** with findings EC-V6-10..16 and a MUST-FIX list
(trust-model statement + two wording corrections) plus SHOULD-FIX P2 hardening (EC-V6-11/12).
This step implements that remediation in the working tree.

**No release/ratification verdict is issued in this step** — the standing §27 item 43
external gate remains.

**All evidence below is fresh runtime evidence against HEAD `7de1135f` + the Step 5 diff**
(modified: `src/hermes/research/programs.py`, `src/hermes/persistence/repositories.py`,
`tests/test_research_program.py`, `hermes_research_architecture_v6.md`, `docs/idr/IDR-018.md`;
untracked: `docs/idr/hermes_v6_step5_trust_boundary_remediation_report.md`).

---

## A. Baseline and Pre-Fix Reproduction (at HEAD, before the diff)

| Probe | Result |
|---|---|
| Full suite (baseline) | 374 passed / 0 failed / exit 0 / 6.68s (Python 3.14.1) |
| A — strongest exploit (hand-built multi-forge COMPILED) | PERSISTED: `rp_handbuilt_forged_id`, version 1, forged hashes/versions verbatim, `produced_by="ADVERSARY"`, `ResearchProgramCompiled` event emitted, became `current()` |
| B — idempotency collision | second **different** program with the same forged `content_hash` returned the first row (`rp_coll1`) — PA4 idempotency forgeable, E9 identical-content rejection defeated |
| C — obligation divergence | `ladder_target=SUPPORTED` hypothesis persisted with `evidence_requirements=[]`, `gate_requirements=[]` (validator would derive 1 evidence / 8 gates) |

Pre-fix controls: same content through the real validator → `INVALID`
(`SCHEMA_VERSION_MISMATCH`, `E1_PREDICTIONS_MISSING`, `E5_RIVAL_COVERAGE`) — the write path
persisted what the validator could not produce.

## B. Root Cause

The write-path gate (E6/E7) checks the *verdict* (`result.compiled`), not the *object*:
`content_hash`, `input_hash`, `program_id`, `schema_version`, and the derived obligations are
caller-assignable dataclass fields stored verbatim (EC-V6-01, EC-V6-11..14). `COMPILED` is a
public dataclass with no receipt or token; nothing re-derived the deterministic proof the
format itself carries.

## C. Remediation Implemented (design constraints honored)

**Constraint compliance:** no re-run of the epistemic validator at the write path; no gateway
built; no second authority; `produced_by` remains informational; genuine-path hashes
byte-identical (all 374 baseline tests pass unmodified).

1. **`src/hermes/research/programs.py` — shared pure helpers (one derivation, never two).**
   `_build_program` was refactored to use the new public functions, so the compiler and the
   repository share a single deterministic derivation:
   - `canonical_content_dict(program)` — the canonical content dict (identity source of truth)
   - `content_hash_of(program)` / `input_hash_of(program)` / `program_id_of(content_hash)`
   - `derive_program_obligations(hypotheses)` → `(evidence_requirements, gate_requirements)`
2. **`src/hermes/persistence/repositories.py` — integrity boundary in `record()`.**
   New `ResearchProgramIntegrityError(ResearchProgramError)`. After the R-02 governance check
   and **before** `BEGIN IMMEDIATE`, `record()` re-derives and compares:
   - `content_hash` (EC-V6-11) — kills raw forgery **and** the idempotency collision
   - `program_id == "rp_" + content_hash[:24]` (EC-V6-12, folded into 11)
   - `input_hash` (EC-V6-13, folded into 11)
   - `schema_version == PROGRAM_SCHEMA_VERSION` (EC-V6-15) — a program the validator would
     reject as `INVALID` cannot persist
   - `evidence_requirements`/`gate_requirements` == `derive_program_obligations(hypotheses)`
     (EC-V6-14) — obligations are derived, never declared; catches self-consistent forgeries
     over empty obligations
   Fail-closed: any mismatch raises before the transaction → no row, no
   `ResearchProgramCompiled` event, no partial state.
3. **Explicitly NOT changed:** no whitelist on `compiler_version`/`policy_version` (a
   self-consistent version is identity-consistent; version validity is the validator's
   epistemic domain — v6 §4.4); no `apply_intent`/gateway; `evaluation.py` untouched.

## D. Regression Tests Added (10, `tests/test_research_program.py::TestIntegrityBoundary`)

| Test | Verifies |
|---|---|
| `test_ec_v6_11_forged_content_hash_rejected` | forged content_hash → reject, 0 rows, 0 events |
| `test_ec_v6_11_forged_program_id_rejected` | forged program_id → reject |
| `test_ec_v6_13_forged_input_hash_rejected` | forged input_hash → reject |
| `test_ec_v6_14_obligation_divergence_rejected` | self-consistent hashes + empty obligations → reject |
| `test_ec_v6_15_forged_schema_version_rejected` | self-consistent `schema_version="999"` → reject |
| `test_ec_v6_15_stale_version_tamper_rejected_by_identity` | version tamper without re-hash → caught by content-hash check |
| `test_ec_v6_16_multi_field_forge_rejected` | the Step 4 strongest exploit → reject, 0 rows, 0 events |
| `test_ec_v6_17_genuine_compile_persists` | genuine path unaffected (row + event + head) |
| `test_ec_v6_18_genuine_idempotent_duplicate_returns_existing` | genuine duplicate idempotent, 1 row, 1 event |
| `test_ec_v6_20_validator_compiled_survives_helpers` | shared derivation == validator's derivation (self-consistency) |

## E. Post-Fix Verification — Full Suite

`.venv/Scripts/python.exe scripts/run_tests.py -v` → **384 passed, 0 failed, exit 0,
6.68s** (374 baseline + 10 EC-V6 regressions; `test_research_program.py` now 65 tests).
All 374 pre-existing tests pass **unmodified** — genuine-path hashes are byte-identical
after the refactor (verified by AC-01/R-01 determinism tests and R-02 governance tests).

## F. Post-Fix Attack Battery (`probe_s5_postfix.py`, all fresh DBs)

| # | Attack | Post-fix result |
|---|---|---|
| 1 | Multi-field forge (Step 4 exploit, `produced_by="ADVERSARY"`) | **REJECTED** (`ResearchProgramIntegrityError`), 0 rows, 0 program events |
| 2 | Hash collision: different content, forged shared `content_hash` | **REJECTED** (no idempotent collapse); first row intact; genuine duplicate still idempotent |
| 3 | Obligations divergence (hashes re-derived consistently) | **REJECTED**, 0 rows, 0 program events |
| 4a | Self-consistent `schema_version="999"` | **REJECTED** (EC-V6-15) |
| 4b | Self-consistent `compiler_version="999.999.999"` | persists (documented: validator's domain, no whitelist) |
| 5 | Forged scope hash (R-02 governance) | **REJECTED** (`ResearchProgramError`, R-02) — unchanged |
| 6 | `produced_by="DIRECTOR"` on genuine compile | persists (E9 provenance, informational) |
| 7 | Genuine compile / genuine duplicate | persist / idempotent (1 row, 1 event) — unchanged |

**Battery result: ALL PASS (12/12 assertions).**

## G. Step 3 Battery Regression Re-Run (post-fix)

| Probe | Pre-fix | Post-fix |
|---|---|---|
| `probe_a.py` A1–A6 (validator bypass) | PERSISTED ×6 | all **REJECTED** with `ResearchProgramIntegrityError` |
| `probe_b.py` B1–B6 | unchanged | unchanged (no admission surface) |
| `probe_c.py` C1–C10 | fail-closed | fail-closed (unchanged) |
| `probe_d.py` D1–D9 (governance) | D2b write-path reject | unchanged (R-02 intact) |
| `probe_v.py` V1–V6 | rejected | rejected (unchanged) |
| `probe_atomic.py` / `probe_atomic_p5.py` P1–P5 | no half-state | no half-state (unchanged) |
| `probe_f.py` F1–F10 | invariants hold | invariants hold (unchanged) |
| `probe_g.py` B-surfaces | no authority hits | no authority hits (unchanged) |

## H. Finding Closure Matrix

| Finding (Step 3/4) | Severity | Closure |
|---|---|---|
| EC-V6-01 `record()` trusts COMPILED flag | P2 | **CLOSED** — integrity boundary re-derives identity + derived state at the write path (EC-V6-16 regression) |
| EC-V6-02 `PROPOSE_RESEARCH_PROGRAM` both llm_proposable and director_only | P3 | Unchanged (gateway contract, deferred) |
| EC-V6-03 no admission function | P3 | Unchanged (honestly deferred, §28.5) |
| EC-V6-04 duplicates kept as distinct entries | P3 obs. | Unchanged (documented) |
| EC-V6-05 unknown dimension → NONE | P3 minor | Unchanged (documented) |
| EC-V6-06 KeyError on typed violation | P3 minor | Unchanged (documented) |
| EC-V6-07 immutability API vs DB level | P3 doc | Unchanged (documented; raw SQL out of contract) |
| EC-V6-08 §28.2 "rejected at validator and write path" wording | P3 doc | **CLOSED** — v6 §28.2 Failure semantics rewritten (write path only for hash mismatch) |
| EC-V6-09 verified positives | — | Re-verified post-fix (D/E/G) |
| EC-V6-10 trust model unstated | P2 doc | **CLOSED** — normative TRUST MODEL (hybrid, layered) statement added to v6 §28.2 + IDR-018 addendum |
| EC-V6-11 identity never re-derived; PA4 forgeable | P2 | **CLOSED** — content_hash/program_id/input_hash re-derived at write path; collision killed |
| EC-V6-12 schema_version not repo-checked | P2 | **CLOSED** — `PROGRAM_SCHEMA_VERSION` comparison at write path |
| EC-V6-13 produced_by advisory | P3 doc | **CLOSED** — documented in v6 §28.2 trust model + IDR-018 addendum; tested (F6) |
| EC-V6-14 obligation divergence | P2 | **CLOSED** — `derive_program_obligations` comparison at write path |
| EC-V6-15 evaluator exclusion completeness | INFO | Unchanged (noted for Part 2 integration) |
| EC-V6-16 evidence-ladder guard re-pin | INFO | Unchanged (re-pin when Evidence lands) |
| IDR-018 §5 "(E6/E7 — no direct mutation bypass)" overclaim | P2 doc | **CLOSED** — §5 rewritten: structural + write-path mechanisms named precisely |

## I. Diff Summary (working tree)

- `src/hermes/research/programs.py`: +`derive_program_obligations`,
  +`canonical_content_dict`, +`content_hash_of`, +`input_hash_of`, +`program_id_of`;
  `_build_program` refactored onto them (`dataclasses.replace`). No behavior change to the
  validator; genuine identity byte-identical.
- `src/hermes/persistence/repositories.py`: +`ResearchProgramIntegrityError`;
  `record()` integrity block (5 checks) between R-02 and the transaction; docstring updated.
- `tests/test_research_program.py`: +10 regression tests (65 total).
- `hermes_research_architecture_v6.md`: §28.2 TRUST MODEL (normative) + Authority boundaries
  + Failure semantics corrected (EC-V6-08/10); §28.4 +5 integrity rows; §28.6 counts 374→384,
  55→65.
- `docs/idr/IDR-018.md`: §5 wording corrected; new "Integrity-boundary remediation addendum".

## J. Residual Risks (documented, not remediated this step)

1. **Admission is still P3.** The integrity boundary proves *self-consistency*, not *origin*:
   a legitimate caller can still compile genuinely-consistent content. Origin/admission
   enforcement (who may propose, `director_only()`) is the P3 gateway's contract (EC-V6-02/03).
2. **Self-consistent forged version triple persists** (documented, tested): no whitelist;
   version validity is the validator's epistemic domain.
3. **Raw SQL and non-repository writers** remain out of contract (EC-V6-07); SQLite has no
   triggers on `research_programs` (D8) — the repository is the only sanctioned writer.
4. **P2 trust model** still assumes the documented single-operator local-host model
   (v6 §27 / Step 4 §N): the boundary defends against accidental or sloppy callers and
   makes forgery detectable/fail-closed; it is not a capability-security boundary against a
   hostile process with filesystem access.

## K. Required Actions Outstanding (for the final gate)

1. Re-verify this working-tree diff at the §27 item 43 external gate (the remediation is
   implemented + regression-tested, not self-cleared).
2. P3: gateway admission for `PROPOSE_RESEARCH_PROGRAM` (`apply_intent` →
   `compile_from_payload` → human gate → `record()`); bind admission to the calling context,
   never to the `produced_by` string.
3. Part 2 integration (IDR-019): complete candidate-set sourcing; carry the
   "advisory, never authorizes" invariant into the integration row (EC-V6-15 note).
4. Evidence Ladder landing: re-pin §27 item 45 by regression (EC-V6-16).

## L. Conclusion

**REMEDIATION COMPLETE — READY FOR FINAL INDEPENDENT REVIEW.**

The P2 trust-boundary findings from Step 4 are closed with a structural integrity boundary
that preserves the approved Model D layering: the validator stays the epistemic authority,
the repository re-verifies governance (R-02) **and now** artifact self-consistency
(EC-V6-11..16) with the compiler's own derivation helpers, and admission remains the P3
gateway's contract. Every Step 4 exploit now fails closed with no row and no event; all 384
tests pass; genuine behavior, idempotency, governance, and atomicity are regression-proven
unchanged. No ratification verdict is issued here — the standing external gate remains.
