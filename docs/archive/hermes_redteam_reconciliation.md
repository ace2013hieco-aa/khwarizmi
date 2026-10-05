# HERMES RED-TEAM RECONCILIATION RECORD
## External Adversarial Report vs. Live Repository
## Baseline: HEAD ac770f7 (origin/main 64157ae + local F4/§8 fixes)

**Method:** every finding was reconciled against the live repository and its
tests (authority hierarchy: code > schema > tests > docs > report). Where the
report's attack was directly testable, it was probed live; where the finding
described design posture, the code path was traced end to end.

**Suite at reconciliation:** 1424 tests passing (up from 1323 at the second
audit's baseline `64157ae`), pyright 0, ruff clean.

| # | Finding | Severity (report) | Reconciliation | Verdict |
|---|---------|-------------------|----------------|---------|
| RT-01 | Retraction Cascade Gap | P1 | Chain exists and is deliberate; auto-downgrade is the ratified anti-pattern | CONFIRMED AS DESIGN — residual FUTURE DESIGN |
| RT-02 | Classifier-Conditional Gate | P1 | Action-shape gate fires regardless of class; named exploit impossible | REFUTED (TEST-VERIFIED) |
| RT-03 | Goodhart Obligation Padding | P2 | Count→level mapping is anti-Goodhart; padding cannot invert priority | REFUTED (PROBE + 2 regression tests) |
| RT-04 | SUCCEEDED-Intermediate Masking | P2 | Cone semantics correct for hard deps; soft-dep masking mitigated by provenance truthfulness | PARTIALLY VALID — by design, residual FUTURE DESIGN |
| RT-05 | Hazard Oracle Semantic Drift | P3 | Deterministic specs are the feature; sentinels mitigate; semantic ingestion deliberately absent | CONFIRMED AS DESIGN — residual FUTURE DESIGN |

---

## RT-01 — Retraction Cascade Gap (P1 reported)

**Claim:** a `ROBUST` hypothesis built on a later-`SourceRetracted` artifact
stays `ROBUST`; system relies on human reading the digest.

**Reconciliation (REPOSITORY-VERIFIED):** the chain is
`REMOVED_OR_RETRACTED` (hazard value-semantics, HZ-02 — never bare presence,
never from `NOT_OA`) → atomic idempotent `SourceRetracted` event → artifact
blast radius → `retracted_source_review_candidates` → Director digest → human
path. The "no automatic downgrade" is the **ratified epistemic posture**, not
an omission: epistemic review §20 pins "blast radius ≠ automatic invalidation"
and "observation must not silently mutate authority". The Evidence Ladder is
monotonic by contract; REFUTED is terminal; only the APPLY pass writes it, from
ratified facts. An automatic ladder downgrade on retraction would create a new
second writer and a silent authority mutation — the exact class of defect the
architecture forbids.

**Residual (FUTURE DESIGN, not a defect):** (1) a ratifiable *quarantine*
proposal action would give the operator a one-verdict path (vs. composing
REJECT_BRANCH); (2) the digest-ignored case is operator discipline, out of
substrate scope. Both recorded; neither built.

**Follow-up probe (F6 lens, committed after this record):** the emission
path was probed exactly as the closure directive demands. Two different
fetch tasks observing the SAME retracted source each record their own
append-only `SourceRetracted` audit event (per-observation fact, payload
carries `observed_by_task`) — no check-then-append race exists on either
emission path (pure appends inside the outcome transaction), and the
advisory dedupes the seeds to exactly one candidate. A forged event,
hand-inserted past every repository, cannot touch ladder state: the APPLY
pass derives from ratified facts only, and corrupt/unresolvable events
fail closed with observable notes. The Director-side
`record_source_retraction` path behaves identically (two records → two
journal events, advisory identical, nothing else written). All four
properties are regression-locked:
`test_two_observers_same_retraction_two_audit_events_one_seed`,
`test_forged_retraction_events_never_touch_ladder_state`,
`test_two_director_records_same_source_two_audit_events_one_seed`.

---

## RT-02 — Classifier-Conditional Human Gate (P1 reported)

**Claim:** an `IMPLEMENTATION_FAILURE` misclassification of a true framing
error lets `PROPOSE_MECHANISM_SUBSTITUTION` auto-admit, bypassing human scope
review.

**Reconciliation — REFUTED (TEST-VERIFIED):** `test_scope_routes_are_pending`
in `test_q04_gate_replay.py` runs the report's exact scenario — an
`IMPLEMENTATION_FAILURE` classification (EFFECTIVE by class) — and asserts
`ROUTE_TO_SCOPE_REVIEW`, `PROPOSE_SCOPE_NARROWING`, and
`PROPOSE_MECHANISM_SUBSTITUTION` all land **PENDING_HUMAN_APPROVAL**.
`test_non_authority_actions_stay_effective` pins the complement. The human
gate is **action-shape-driven** (`proposal_requires_human_confirmation`),
recomputed at proposal time, never class-driven. A wrong class can therefore
mis-route *advisory content*; it can never convert a proposal into authority.
The FRAMING_ERROR class-gate additionally exists for the advisory tier
(contributing-factor rule, TEST-VERIFIED everywhere). The residual "classifier
truth gap" is classifier accuracy — out of substrate scope, and correctly
assigned to the external *semantic* review, not the state-machine closure.

---

## RT-03 — Goodhart's Law in Q-02 Ordering (P2 reported)

**Claim:** a program padded with 50 trivial *satisfied* obligations inflates
its satisfaction metrics and outranks a harder program with 2 outstanding.

**Reconciliation — REFUTED (live probe + regression):** the ratified count→
level mapping is `NONE < LOW (all satisfied) < MEDIUM (1 outstanding) < HIGH
(≥2 outstanding)`. Satisfied obligations **floor at LOW** — completion volume
*reduces* the dimension, the inverse of the claimed exploit. Two regression
tests now pin it:

- `test_goodhart_padding_satisfied_obligations_never_wins` — 50 satisfied
  trivial obligations vs 2 outstanding: the high-value task dispatches FIRST
  despite being created later (HIGH > LOW).
- `test_goodhart_padding_outstanding_caps_at_high` — 50 *outstanding* trivial
  obligations vs 2 outstanding: the dimension caps at HIGH, so padding reaches
  **parity, never inversion**; the tie falls to `created_at` and the earlier
  (padded-program) task wins, confirming no priority theft.

**External-gate directive (report §7.3) stands, sharpened:** the auditor
should attack the *mapping itself* — negative/overflow counts, foreign-program
satisfaction links, cross-version link reuse — not volume.

---

## RT-04 — SUCCEEDED-Intermediate Masking (P2 reported)

**Claim:** A FAILED → B (fallback) SUCCEEDED → C: C executes blind to A's
failure; "epistemic chain continues on corrupted ground".

**Reconciliation — PARTIALLY VALID, by design:** the cone rule is a *hard-
blocking* predicate: a SUCCEEDED intermediate means downstream execution is
legitimate, and `test_succeeded_intermediate_breaks_the_blocking_chain` pins
it. The report's masking concern is real for *soft* dependencies, but the
artifact layer compensates: B's fallback artifacts are provenance-linked to B
(their actual producer), never to A — the epistemic chain is *truthfully
documented*, and A's failure cone + `re_review_candidates` surface in the same
digest as B's outputs. Nothing is corrupted; what is "masked" is only the
automatic *flagging* of C, which is the correct behavior for hard deps.

**Residual (FUTURE DESIGN, explicitly deferred by epistemic review §19):**
edge-propagation policy versioning — `cites / derived_from / supersedes /
used_as_input / justifies` do not share identical propagation semantics, and a
soft-dependency ("masked-by-fallback") edge kind would make the masking
visible in the graph. Recorded; not built.

---

## RT-05 — Hazard Oracle Semantic Drift (P3 reported)

**Claim:** a structurally valid "service unavailable" page evades the
deterministic hazard specs and gets ingested as a paper.

**Reconciliation — CONFIRMED AS DESIGN:** deterministic JSON hazard specs are
the *feature* — nothing from an untrusted provider influences state beyond the
structured hazard classification; semantic understanding is deliberately
absent from the ingestion path. Mitigations already present: `required_fields`
fetch-side drift sentinel (PS-08), `MALFORMED_200` path (FS-02), value-
semantics retraction markers (HZ-02), `count_semantics` registration
validation. The report's exact drift scenario is acknowledged as an
*unbounded* adversarial class no fixed spec list can exhaust.

**Residual (FUTURE DESIGN):** any semantic drift detector would reintroduce
the LLM/classifier dependency the architecture forbids at the ingestion
boundary; if ever built it must remain deterministic and advisory-only. The
correct defense-in-depth is downstream: a structurally-valid-but-garbage
artifact still enters as an artifact and is subject to the same provenance,
review, and human-gate machinery as everything else.

---

## External Closure Directives (updates the epistemic review §K list)

The report's §7 instructions stand, refined by the reconciliation:

1. **Retraction cascade** — **TEST-VERIFIED (closed by the follow-up probe
   commit `ffeb996`):** forging a `SourceRetracted` event moves no ladder
   state and applies nothing; corrupt/unresolvable events fail closed with
   notes; duplicates across observers or Director records are per-observation
   audit with an advisory that dedupes to one seed; the cross-project edge
   is closed too (`test_cross_project_retraction_never_leaks_between_projects`
   — a p2 event never seeds p1, and `artifact_id` is globally unique). The
   auditor should re-attack only the count-mapping edges the regression
   tests do not cover.
2. **Classifier truth gap** — **TEST-VERIFIED (probe-locked by the
   directive #2 probe):** a wrong-classification input can never reach
   state mutation, only proposal gating — across every gateway surface.
   The wrong class admits advisory proposals and decisions (a gated
   `PENDING_HUMAN_APPROVAL` proposal and the decision event are the ONLY
   effects), and every authority surface re-verifies (F2): the
   `EVIDENCE_TRANSITION` admission refuses a REJECT_BRANCH ratification
   whose class does not permit it; the APPLY re-verifies at apply time (a
   directly-written transition proposal whose ratification does not
   re-verify applies nothing); the bare-classification REFUTED driver
   requires the decisive-falsification citation (a
   `DECLARED_CONSTRAINT_VIOLATION` citing the wrong constraint applies
   nothing); and the S16 scope intake records the human verdict but never
   amends the program brief. Pinned by
   `TestDirective2ClassifierTruthGap` (4 tests) in
   `tests/test_q05_evidence_ladder.py`.
3. **Obligation padding** — **TEST-VERIFIED (closed by the count-mapping
   probe commit):** the count→level mapping's extreme inputs are pinned —
   negative counts map deterministically to LOW (unreachable from the
   increment-only derivation), overflow caps at HIGH, zero totals map to
   NONE, malformed obligations are skipped (never a fabricated fact),
   foreign-program satisfaction links are refused at admission (IDR-038
   rule 1), and a superseded ancestor's obligations never leak into a task
   linked only to the current program (only an explicit multi-link sums,
   capped at HIGH). The auditor's remaining target is the human-gate and
   proposal surfaces, not the mapping.
4. **Human-gate / one-verdict journal tamper** — **TEST-VERIFIED (closed
   by the F14-lens follow-up):** forged journal events can only DENY a
   verdict, never grant one. A forged duplicate `GatePassed` before a
   resolve neither blocks nor double-authorizes — the verdict still lands
   SUCCEEDED with exactly one `HumanGateResolved` (the one-verdict rule is
   keyed on the gate's `task_id`, in-transaction and fenced) and the second
   resolve is refused `NOT_WAITING`; a forged `HumanGateResolved` alone
   refuses the verdict (`ALREADY_RESOLVED`) with the gate left
   `WAITING_HUMAN`; and with a concurrent second controller the lease
   fence refuses the stale verdict (`LOCK`, nothing lands) while the
   forged `HumanGateResolved` denies even the race-winner's own resolve.
   Pinned by `test_11_forged_gate_events_can_refuse_but_never_authorize`
   and `test_11_forged_journal_events_cannot_bypass_one_verdict_under_race`.

## Second External Audit (HEAD 64157ae) — Reconciliation at 156b7ee

**Baseline delta:** the audit ran at `64157ae` (1323 passing, 36/36 + 46/46
probe files, verdict "no new P0/P1, no regressions"). Current HEAD
`156b7ee` carries that baseline plus the F6/F8/F9, retraction, digest-fold,
and count-mapping hardening — **1331 tests passing**. The audit's claim of
no new P0/P1 is re-confirmed at the later HEAD; its five consistency notes
were each verified against the live code:

| Note | Audit claim | Verification at HEAD 156b7ee | Disposition |
|------|-------------|------------------------------|-------------|
| N1 | F9 index omits `HumanGateResolved`; direct-SQL dup possible | CONFIRMED — but the proposed fix is structurally inapplicable: `HumanGateResolved` correlations are fresh UUIDs per resolve, so an `(event_type, correlation_id)` index cannot dedupe them. The one-verdict rule is correctly keyed on the gate's `task_id` by an in-transaction, fenced, journal-backed check (F14) — no race exists | CONFIRMED-BY-DESIGN; a per-task partial index (`ON events(task_id) WHERE event_type='HumanGateResolved'`) recorded as optional FUTURE defense-in-depth, not needed (direct SQL = tamper-grade) |
| N2 | RATIONALE cap (F3) is API-only; no `--rationale` flag on the CLI | CONFIRMED (`cli.py` resolve surface has no rationale argument; the 2000-char refusal verified working via the API) | OBSERVATION — the CLI simply does not expose rationale; adding the flag is a CLI-surface decision. FUTURE DESIGN if operators want rationale on the CLI |
| N3 | No CLI repair path for a corrupted credential row | CONFIRMED — `register` is refuse-on-existing and `verify` is fail-closed, so an F4-tampered row bricks the operator with no CLI recovery | OBSERVATION — operational gap, now DOCUMENTED: recover via direct SQL (`DELETE FROM operator_credentials WHERE operator_id = '<id>';`) then re-run `hermes operator register`. No code change |
| N4 | `reason`/`caused_by` not secret-scanned in `_append_event_to_db`; `concurrency_group` stored-but-unenforced | CONFIRMED — `validate_event` scans the payload only; reason/caused_by are free-text args. The writers are the operator or the controller's fixed reasons (self-disclosure, not injection) | OBSERVATION — the payload scanner is a deterministic backstop (S6), not a universal scanner; extending it to free-text reasons would not change the authority surface. `concurrency_group` is a deferred-policy column. Both recorded, no code change |
| N5 | Mode-event naming asymmetry (enter `AWAITING_HUMAN` logs `ModeChanged`, leave logs `ProjectResumed`) | CONFIRMED (`repositories.py` mode-event map) | OBSERVATION — catalog-named events (v4 §8.1); renaming would break the catalog contract. Cosmetic; recorded only |

**Count-mapping closure (the record's own directive #3):** probed live and
regression-locked — negative counts are unreachable (increment-only
derivation) and map deterministically to LOW when forced; overflow counts
cap at HIGH; zero totals map to NONE; malformed obligations are skipped;
foreign-program satisfaction links are refused at admission (IDR-038 rule 1,
`test_foreign_program_rejected` already pinned); and a superseded ancestor's
obligations never leak into a task linked only to the current program
(`test_superseded_ancestor_not_counted_unless_linked`), while an explicit
multi-link sums deterministically and caps at HIGH
(`test_explicit_multi_link_sums_obligations_capped`). The pure mapping edges
are pinned in `test_q02_eligible_ordering.py::TestCountMappingEdges`.

**N1 follow-up — the per-task partial index stays recorded-only (no
migration):** the proposed `ON events(task_id) WHERE
event_type='HumanGateResolved'` index would be pure defense-in-depth, and
it is deliberately NOT built. Reasons: (1) correctness never depends on it
— the F14 one-verdict check is a point `SELECT ... LIMIT 1` whose answer is
identical with or without an index (the index changes query planning only,
never the result, and the check's authority comes from the journal row
existing, not from how fast it is found); (2) the journal is append-only and
tamper-grade by construction (no UPDATE/DELETE path), so an index adds no
security delta — direct SQL is the threat model, and an index does not move
it; (3) resolves are human-rate and serialized by the scheduler lease, so
there is no measured latency pressure to justify schema churn; (4) a
migration would bump `schema_version` and re-verify across every test
database for zero authority-surface change, and a flag-gated variant would
add configuration surface whose only effect is a no-op. If a future
deployment ever measures resolve latency on a very large journal, the index
can be added then as a routine migration; this paragraph records the
decision so it is not relitigated.

**F4/F8/F9 hardening audit (fresh adversarial probe):** the three audit
hardening commits are re-attacked with fresh probes and hold. **F4 (PBKDF2
work factor):** the stored-iteration guard is EXACTLY the inclusive range —
one below MIN / one above MAX, non-numeric iterations, an algorithm tamper,
and a malformed field count are all refused WITHOUT running the hash (never
a stored-iteration DoS, never a degenerate weakening); end-to-end, rewriting
the stored credential row with an astronomical work factor only DENIES the
operator verdict (OPERATOR, gate untouched) and the same gate resolves
normally once the row is restored. A malformed-shape corpus fuzz (bad
prefixes, wrong algorithm, odd-length / invalid-hex salts, out-of-range or
non-numeric iterations, wrong field counts, binary junk, unicode, oversized
rows) confirms EVERY shape fails closed with zero KDF and never raises —
and it caught a real gap: a tampered NON-ASCII legacy row previously
crashed `hmac.compare_digest` (TypeError) instead of failing closed, now
fixed by comparing legacy values only when they are well-formed 64-hex
digests (`test_12_f4_malformed_stored_hash_corpus_never_runs_pbkdf2`).
The legacy fix is verified end to end: a direct-SQL 64-hex credential
still verifies at the repository, lands an APPROVED verdict through
`resolve_human_gate`, and resolves a gate through the CLI
(`test_12_f4_legacy_64hex_credential_verifies_end_to_end`,
`test_legacy_64hex_credential_gate_resolve_cli`); malformed legacy rows
(64 chars but not hex, or wrong length) fail closed, never raise.
**F8 (RefutedApplied payload):** at
EXTREME rival scale (3000) the truncation loop terminates and the stored
payload is valid by construction (re-validated against the same event cap),
with the exact full count recorded; a no-rivals falsification emits no
truncation note. **F9 (one-verdict schema index):** the partial unique index
refuses a direct-SQL duplicate for ALL five scoped correlation-bearing
types; and its scope EXCLUDES `HumanGateResolved` (the documented N1 gap) —
a duplicate correlation can insert at the schema level, and the app-level
F14 journal check is what covers it (a status-tampered second resolve is
refused `ALREADY_RESOLVED`). Pinned by
`test_12_f4_boundary_and_end_to_end_stored_row_tamper`,
`test_12_f4_malformed_stored_hash_corpus_never_runs_pbkdf2`, and
`test_11_f9_schema_index_scope_excludes_human_gate_resolved`
(`tests/test_controller.py`), and
`test_schema_index_refuses_duplicates_for_all_five_scoped_types`,
`test_extreme_rivals_payload_never_exceeds_cap`, and
`test_no_rivals_payload_full_no_truncation_note`
(`tests/test_q05_evidence_ladder.py`).

**Hardening audit at a glance (F2 / F4 / F8 / F9):**

| Hardening | Fresh probe (this audit) | Disposition | Pinned test(s) |
|-----------|--------------------------|-------------|----------------|
| **F2** — constant-work operator burn | Counting patch over `hashlib.pbkdf2_hmac`: the unknown-operator path burns EXACTLY one in-range KDF per verify (module dummy hash), parity on the known-operator path, and the burn is NOT skippable by stored-row tampering (it consults no row); gate-surface lens repeats the one-KDF budget at `resolve_human_gate` for all three outcomes (unknown id / wrong token / right token); the LOCK lens proves the scheduler-lease refusal is not a cheap oracle (the verify precedes the lock, so an invalid operator under a held lease still pays the burn — OPERATOR, never a fast LOCK — and a valid operator pays one KDF before the LOCK refusal); the CLI lens proves `hermes gate resolve` pays the same one-KDF budget per outcome at the operator's actual entry point; the ingestion lenses prove `record_operator_decision` and `record_scope_review_decision` pay one KDF on EVERY path (unratified OPERATOR, unknown-proposal PROPOSAL, success, idempotent duplicate, contradictory PROPOSAL, lease-held LOCK); the bounded-LOCK lens proves the refusal is exactly one KDF + a constant 4 SQL statements, with `scheduler_lock` schema-constrained to a single row (`CHECK id = 0`) so no table growth is even possible (2000 extra events rows change nothing); the register lenses prove the controller and CLI register surfaces pay one KDF whether the id is NEW (hash build), EXISTING with the SAME token (idempotent stored-hash match), or EXISTING with a DIFFERENT token (ratifiable-not-overwriteable refusal) — registration cannot reveal an existing id by response time; the tick lens proves the loop runs ZERO PBKDF2 and never reads `operator_credentials` across gate-parking, a real NO_SIGNAL recovery transition, and the lock_held idle tick; the parse-bound lens proves the stored-hash SHAPE CHECK is O(512) constant — a length guard fires before any split/int/fromhex, so a tampered row with a gigantic salt, iterations, or digest is refused with zero KDF and zero parse calls (an instrumented sqlite text_factory proves the parse never runs on oversized rows) — a giant stored row cannot slow the verify into a timing signal; the diagnostics lens proves the status / audit / backup / restore CLI surfaces perform ZERO PBKDF2 (read-only diagnostics and file ops with no credential-dependent work at all — the strongest parity: no KDF path to time); the interleaving lens proves two controllers registering/verifying on the shared credential table each pay one KDF per call with the row byte-identical throughout (a different-token register by the second controller is refused, never overwriteable, no shared-state corruption); the token lens proves the PRESENTED token cannot make the verify variable-cost — every in-range shape (unicode, control bytes, the 1024-char MAX, empty) pays exactly one KDF, and an oversized token is refused before any hashing with zero KDF (`_OPERATOR_TOKEN_MAX_LENGTH`, checked at register and verify; the refusal reveals only the attacker-known token length, never stored state); the re-register lens proves the idempotent register path cannot be a token-correctness oracle — 20 correct and 20 incorrect re-registers each pay exactly one KDF per attempt (id existence IS revealed by the register response by design; the secret is the token, never a timing tell); the purity lens proves `verify` is a pure function of (stored hash, token) — identical inputs give identical results across any ordering/interleaving, one KDF per call in every sequence, the outcome flips exactly when the stored hash is rewritten, and a batch of verifies never mutates the store; the refusal lens proves the wrong-token re-register error is byte-identical across every presented-token shape (length, content, encoding) with NO digits at all — it never echoes a token or hints at the STORED token's length (only the designed accept/refuse outcome discriminates); the brute-force lens proves the wrong-token surface has no fast-path batching — K sequential attempts pay exactly K KDF calls and wall time scales linearly with the attempt count (>= K x the measured single-attempt budget), so 1000 attempts cost >= 1000 KDF budgets (~90s+ at 210k iterations), the practical rate limit; the CLI-output lens proves `hermes operator register` prints refusals to STDOUT with a uniform exit code (1) across every wrong-token shape with byte-identical output and no token echo, and `hermes gate resolve` refuses an unknown id and a known id with a wrong token with the SAME text (modulo the attacker-supplied id) — the CLI adds no exit-code oracle and no id-existence leak; the round-trip lens documents the operator-facing latency (measured ~2026-08-16): one-KDF budget ~89ms, a wrong-token refusal ~92ms (KDF only, no writes), a full APPROVED resolve ~92ms (KDF + lease + journal — the write machinery is sub-ms, so the round trip is dominated by the single burn); the JSON-shape lens proves the status/audit `--json` schemas are fixed and operator-state-independent — registering a ratified operator leaves BOTH documents byte-identical (empty store), the populated key structure is identical to the empty structure (state changes only array lengths, never keys), and no operator/credential/token material appears anywhere in either document, so a `--json` consumer can observe only the intended project/task/event content; the backup-size lens proves the backup/restore CLI copy work is a PURE FUNCTION OF FILE SIZE, never of contents — two byte-identical stores holding different secrets produce identical backup bytes, every backup is an exhaustive copy (backup bytes == source bytes), growing the journal grows the backup by EXACTLY the file-size delta, and restore is the same pure byte copy (restored bytes == backup bytes, original token still verifies) — backup timing reveals only the public file size, never secrets; the cold-start lens proves the CLI ENTRY cost (interpreter + imports + config load) is a fixed additive cost independent of store contents — an empty and a populated (~350KB) store take the same cold-start time (measured ~156-180ms vs the ~90ms one-KDF budget on the reference machine, loose 3x+100ms bound), so even the CLI's startup latency cannot be a state oracle; the doctor-echo lens proves `doctor --json`'s `config` echo is a BIJECTIVE mirror of the operator-written config plus built-in constants — every path (database_path, backup_dir, artifact_root) is echoed byte-for-byte exactly as written, omitted fields fall back to the documented relative default strings (`backups`/`artifacts`/`workspace`/`providers`, never env/cwd-derived), and with NO config file the echo is exactly `default_config()` — so even a tampered config pointing at attacker-chosen paths leaks nothing beyond the tamperer's own values (no env vars, hostname, cwd, or runtime state); the audit-size lens proves `audit --json` output size is a PURE FUNCTION OF THE VISIBLE EVENT ROWS — two stores sharing the same p1 rows produce the same output SIZE even when hidden state differs (a ratified operator, a second project with 202 tasks), the size scales linearly with the returned count (~478 bytes/row, band measured in-test), a ghost project id yields `{"events": []}` (the empty shape no real project id can produce, since creation writes the ResearchCreated row), and the unfiltered view is exactly the union of the per-project rows — so audit size/timing reveals only the rows the audit trail is designed to expose, never hidden store state; the human-audit lens proves the HUMAN `audit` table shows the SAME rows as `--json` (ids printed in full — the `:12s` column is a minimum width, never an 8-char truncation — so its size signature is the same linear function of the visible rows with a smaller per-row constant), is hidden-state-invariant (the p1 view is byte-identical across stores sharing the same p1 rows), and NULL-project stale-admission rows (project_id=NULL fallback) appear ONLY in the unfiltered view (human and JSON alike), never under any `--project` filter including a ghost id; the status-tamper lens proves the HUMAN `status` table is a lossy, BOUNDED projection — the p1 section is byte-identical across hidden state, id fields are truncated to 8 chars (`task_id[:8]`) so a pathological id cannot blow up the output, enum fields (lifecycle/operational_mode/status/task_type) are DB-constrained by CHECKs (a 10KB lifecycle tamper is REJECTED at the store, so the table cannot be made variable-cost through them), and the one unbounded field (project name) is the tamperer's OWN value mirrored verbatim in both the human table and `--json` — no additional signal; the doctor-sandbox lens proves the Sandbox check detail is the ONE env-derived value in `doctor --json` — the shutil.which RESOLUTION of the configured runner appears as `runner -> <absolute path>` in the checks detail only when found (and only in the checks, never in the `config` echo, which holds the bare runner string), and as `runner not found` with NO path when missing — the resolution runs against the operator's OWN PATH (operator-controlled, not a secret), and the config echo stays env-free; the precedence lens pins the resolve_human_gate failure order as a DETERMINISTIC, documented matrix — VERDICT/RATIONALE (0 KDF, attacker-input fast paths, no protected fact) → OPERATOR (1 KDF) → LOCK → NOT_FOUND (project check precedes type/status) → NOT_HUMAN_GATE → NOT_WAITING → ALREADY_RESOLVED (journal truth fires even under status tamper) — every post-auth path exactly one KDF; the cross-project lens proves an operator resolving through a controller bound to a DIFFERENT project is refused NOT_FOUND with no state/events (the credential is system-wide by design; project scoping lives in the controller binding, and the CLI derives the task's own project when none is given); the journal-coherence lens proves the one legal verdict writes exactly one GatePassed + one HumanGateResolved + two TaskStatusChanged hops atomically while EVERY refusal path writes ZERO events; the replay-after-restore lens proves a ratified verdict survives backup+restore with exactly one legal outcome (restored journal still refuses, ALREADY_RESOLVED under status tamper, one HumanGateResolved row total); the events-CLI lens proves the `events` human lines print event_type/from_state/to_state with MIN-WIDTH formatting only (a tampered huge value is echoed verbatim — the tamperer's own row, mirrored identically in audit --json — never hidden state) and carry NO reason/payload/project/task ids (strict subset of the audit view); the output-echo lens proves `gate resolve` echoes ONLY attacker-supplied ids (a tampered stored hash is refused OPERATOR with the same shape as a wrong token, no content leak; a ghost task is a fast 0-KDF refusal revealing only public task existence); the auth-boundary lens pins the documented authorization model — the credential gates EXACTLY the verdict (and ingestion) surfaces while pause/resume/run are unauthenticated local machinery (0 KDF); the canary lens proves a registered canary token never appears anywhere (journal, audit/status/doctor/events outputs, backup snapshot bytes, raw DB bytes, every gate-resolve output) | **HOLDS** — a stopwatch cannot reveal operator validity at the repository, the gate surface, the LOCK path, the CLI, the two ingestion surfaces, the register surface, the stored-hash parse, anywhere in the tick loop, or any diagnostic surface | `test_12_f2_unknown_operator_burn_runs_one_pbkdf2_not_skippable`, `test_12_f2_gate_surface_constant_work_one_kdf_each`, `test_12_f2_lock_path_pays_one_kdf_not_a_cheap_oracle`, `test_12_f2_lock_path_bounded_work_size_independent`, `test_gate_resolve_cli_pays_one_pbkdf2_per_outcome`, `test_12_f2_operator_decision_refusals_pay_one_kdf_each`, `test_12_f2_scope_decision_refusals_pay_one_kdf_each`, `test_12_f2_register_surface_pays_one_kdf_each`, `test_operator_register_cli_pays_one_kdf_per_attempt`, `test_12_f2_tick_loop_never_runs_pbkdf2_or_reads_credentials`, `test_12_f2_hash_shape_parse_is_bounded`, `test_diagnostic_cli_surfaces_never_run_pbkdf2`, `test_12_f2_register_verify_interleaved_controllers_one_kdf_each`, `test_12_f2_verify_token_fuzz_one_kdf_bounded`, `test_12_f2_register_repeated_no_token_oracle`, `test_12_f2_verify_is_pure_function_of_hash_and_token`, `test_12_f2_register_refusal_reveals_no_token_shape`, `test_12_f2_wrong_token_brute_force_pays_linear_kdf_cost`, `test_register_cli_refusal_output_leaks_nothing_beyond_message`, `test_12_f2_operator_round_trip_latency_documented`, `test_status_audit_json_shape_operator_state_invisible`, `test_backup_restore_cost_is_size_proportional_not_content_dependent`, `test_cold_start_import_cost_is_state_independent`, `test_doctor_json_config_echo_leaks_only_operator_written_values`, `test_audit_json_output_size_is_visible_rows_only_not_an_oracle`, `test_audit_human_table_same_rows_null_project_unfiltered_only`, `test_status_human_table_hidden_state_invariant_and_bounded`, `test_doctor_sandbox_resolved_path_env_derived_only_in_checks`, `test_20_error_precedence_matrix_deterministic`, `test_20_cross_project_gate_resolution_refused`, `test_20_journal_coherence_each_outcome_exact_events`, `test_20_replay_after_restore_one_verdict_survives`, `test_events_cli_untruncated_fields_but_strict_subset`, `test_gate_resolve_output_echoes_only_attacker_input`, `test_verdict_requires_credential_operational_surfaces_do_not`, `test_cli_cross_project_gate_resolution`, `test_canary_token_never_leaks_any_surface, test_21_f15_paused_recovery_stays_no_signal_completes_after_resume, test_21_f15_paused_revert_fresh_heartbeat_no_requeue, test_21_f15_rejected_gate_wave_stops_recovery_still_completes, test_21_f15_rejected_gate_wave_redispatch_downstream, test_21_f15_recovery_before_dispatch_chained_gates, test_21_f15_exhausted_retry_race_property_schedules, test_21_f15_resolve_race_stall_is_surfaced_not_masked, test_21_f15_recovery_before_dispatch_chained_gates_rejected, test_21_f15_resolve_race_partial_lease_stall_surfaced, test_21_f15_chained_gates_property_schedules, test_21_f15_chained_gates_rejected_property_schedules, test_21_f15_resolve_race_third_gate_partial_lease_stall_surfaced, test_21_f15_completion_budget_deep_wide_graph_not_a_false_stall, test_21_f15_completion_budget_mixed_mesh_depth_x_width, test_21_f15_third_gate_partial_lease_stall_property_schedules, test_21_f15_completion_budget_huge_fan_scaled_never_exhausted (F15-audit recovery family: the ACTIVE-mode-gated second-miss hop, the mode-independent liveness revert, the wave-re-dispatch-past-a-failed-gate behavior, the chained-gate dep ordering, the exhausted-retry schedule property, the bounded-completion stall surfacing, the chained-gate REJECTED re-park, the partial-lease downstream stall, the third-gate partial-lease stall, and the completion-budget dependency-graph DoS lens) |
| **F4** — PBKDF2 work-factor bound | Stored-iteration guard is exactly the inclusive range: one below MIN / one above MAX, non-numeric iterations, an algorithm tamper, and a malformed field count all refuse WITHOUT running the hash; end-to-end, rewriting the stored row with an astronomical work factor only denies the verdict (gate untouched), and the same gate resolves normally after restore | **HOLDS** — no stored-iteration DoS window (no KDF work on refusal), no degenerate weakening | `test_12_f4_boundary_and_end_to_end_stored_row_tamper`, `test_12_f4_out_of_range_never_runs_pbkdf2` |
| **F8** — RefutedApplied payload bound | At extreme rival scale (3000) the truncation loop terminates and the stored payload re-validates against the same event cap, with the exact full count recorded; a no-rivals falsification emits no truncation note | **HOLDS** — the payload never exceeds the cap and counts stay exact under scale | `test_extreme_rivals_payload_never_exceeds_cap`, `test_no_rivals_payload_full_no_truncation_note` |
| **F9** — one-verdict schema index | The partial unique index refuses a direct-SQL duplicate for ALL five scoped correlation-bearing types; its scope EXCLUDES `HumanGateResolved` (the documented N1 gap) — the schema admits that duplicate and the app-level F14 journal check is what denies it (status-tampered second resolve refused `ALREADY_RESOLVED`) | **HOLDS-BY-DESIGN** — index scope + the F14 journal check cover the surface; the N1 partial index stays recorded-only | `test_schema_index_refuses_duplicates_for_all_five_scoped_types`, `test_11_f9_schema_index_scope_excludes_human_gate_resolved` |

Note: every F2 probe is order-independent by construction — the module
dummy hash is built lazily on first burn, so whichever verify/burn probe
ran first in a session would have paid the build's extra KDF; all twenty-three
probes now pre-warm the dummy before counting (the register surface builds
fresh hashes, the tick loop and the diagnostic surfaces never hash at all,
and the parse-bound probe instruments the stored-row parse, so each
counted KDF is exact regardless of execution order).

**Measured operator round trip (2026-08-16, dev machine; machine-specific):**
one-KDF budget at the shipped work factor (210k iterations) ≈ **89 ms**; a
wrong-token refusal at the `resolve_human_gate` surface ≈ **92 ms** (the
single KDF burn, no writes — the refusal changes nothing); a full APPROVED
resolve ≈ **92 ms** (one KDF + lease acquire/release + GatePassed /
HumanGateResolved journal writes + mode transitions — the write machinery
is sub-millisecond, so the operator-facing round trip is dominated by the
single constant-work burn). The practical consequence: 1000 sequential
wrong-token attempts cost ≈ 1000 × ~90 ms ≈ **90 s**, the brute-force rate
limit of the surface (pinned by
`test_12_f2_operator_round_trip_latency_documented`).

**Cold-start contrast (2026-08-16, same machine; machine-specific):** a
cold `hermes status --json` subprocess — interpreter + module imports +
config load + one status read — costs ≈ **156-180 ms** whether the store
is empty or holds a ratified operator plus 100 tasks (~350 KB DB): the
entry cost is a fixed additive constant (≈ 1.7x the one-KDF budget) that
is independent of store contents, so even the CLI's startup latency
cannot be a state oracle (pinned by
`test_cold_start_import_cost_is_state_independent`). Backup/restore are
full-file copies whose cost is exactly the DB byte size (backup bytes ==
source bytes; growth delta is byte-exact) — a public, stat-visible
quantity, never a content or secret signal (pinned by
`test_backup_restore_cost_is_size_proportional_not_content_dependent`).

**Verdict:** the two P1s reduce to one design posture (RT-01, deliberate) and
one impossibility (RT-02, test-pinned); RT-03 is refuted and locked; RT-04/RT-05
are accepted design with recorded FUTURE DESIGN residuals. No BLOCKER, no
MUST FIX. All four directives (#1, #2, #3, #4) AND the F4/F8/F9 hardening
are now closed by test/probe (each re-attacked with a fresh probe); the
only recorded-but-unbuilt item is N1's optional per-task partial index
(`ON events(task_id) WHERE event_type='HumanGateResolved'`), documented
above as FUTURE defense-in-depth only.

**Repository state (pushed):** all twenty closure commits — the F14
forged-journal edge (`bbecea2`), the forged-journal race probe (`5b80254`),
the directive #2 classifier-truth probe (`1650ece`), the F4/F8/F9 hardening
audit + local 3.14 gate (`11d2080`), the `.venv` rebuild + CI smoke
(`f7b6fd0`), the F2 constant-work burn probe + consolidated run docs
(`85332f9`), the F2 gate-surface / LOCK / CLI probes + pyright/ruff gates
(`d7bbd27`), the F2 ingestion + bounded-LOCK probes (`12fdc2f`), the F2
register + tick-loop probes with the diagram manifest, and the F2
hash-parse-bound + diagnostics probes with the profiled-gate script, the
interleaving + malformed-shape fuzz probes with the diagram refresh, and
the token-fuzz + legacy end-to-end probes with the token-length bound, and
the re-register no-oracle + purity probes, and the register-refusal + brute-force probes with the diagram refresh, and
the CLI-output + round-trip-latency probes, the JSON-shape + backup-size + cold-start probes, the doctor-echo + audit-size probes with the diagram fold, the human-audit + status-tamper + doctor-sandbox probes, the F15 live-worker race hardening (test_14_f15_live_worker_lease_protected now gates B's start on A's proven lease acquisition — the test's thread-vs-first-tick acquire race flaked once on CI 2026-08-16 under runner load; product logic was correct, the task still ended SUCCEEDED once — 10/10 local passes pre-fix, 5/5 post-fix, sibling hung-worker test untouched), and the composed control-plane audit (9 new probes: precedence matrix, cross-project, journal coherence, replay-after-restore, events-CLI, gate-resolve output echo, auth boundary, CLI cross-project, canary leak — verdict CLEAN, report in hermes_operator_control_plane_adversarial_review.md) — are on `origin/main` (khwarizmi-research), each with a green CI run (all six
jobs: test / typecheck / local-gate / profiled-gate / lint / audit). The
`local-gate` CI job enforces `uvx pyright src` (strict) and
`uvx ruff check src tests` on the smoke path, and the new `profiled-gate`
job runs `scripts/profiled_gate.sh` (tests-profile pyright + the
walking-skeleton smoke in one reproducible command), mirroring the
dedicated `typecheck`/`lint` jobs without duplicating them, so the
F2/F4/F8/F9 closure story is pinned against drift on every commit.
## F15-Audit Composition Findings + Q-05 Crossover (28ff259 + 1)

**Suite at reconciliation:** 1407 tests passing (fourteen composed probes),
pyright 0, ruff clean, CI green.

### Finding 1 — Hung worker behind a parked human gate was PERMANENTLY lost (fixed)

The section-28 composition probe (`test_21_f15_heartbeat_cliff_operator_during_transition`)
exposed a real defect at the boundary of the F15 horizon cliff and the
human gate: a worker whose lease expired while the wave was parked at a
gate was FAILED by the recovery ladder's second conclusive miss, but the
same-pass requeue leg (FAILED → RETRYING → RUNNING, IDR-029 Decision 4) is
gated on ACTIVE mode — so the task stayed FAILED (attempt 1, max_retries
not exhausted) forever, and the operator's later verdict never restarted
it. IDR-029 criterion 3 ("exactly one claim set, task SUCCEEDED") was
violated in the gate-parked interleaving.

Fix (smallest, architecture-consistent): the NO_SIGNAL → FAILED second-miss
hop is now mode-gated — it fires only while the project is ACTIVE. While
AWAITING_HUMAN/PAUSED the dead worker stays NO_SIGNAL; the conclusive
second miss fires on the first ACTIVE tick after the verdict, where the
Decision-4 chain completes in the same pass (requeue → attempt 2 →
re-execute → SUCCEEDED once). The liveness REVERT (fresh heartbeat →
RUNNING) stays mode-independent. Pinned by the composition probe: the
operator resolves the gate MID-transition (worker NO_SIGNAL, parked), the
verdict lands exactly once (one HumanGateResolved + one GatePassed + two
status hops, one gate SUCCEEDED), mode returns ACTIVE, and the worker is
requeued + re-executed exactly once (attempt 2, one claim set); A's late
handler write is discarded (fence/binding guard). A second resolve is
refused NOT_WAITING.

### Follow-up legs (a73007e + 1): PAUSED-then-resumed and REJECTED verdict

Two more interleavings pin the same mode-gated recovery fix: `test_21_f15_paused_recovery_stays_no_signal_completes_after_resume` pauses the project mid-execution (a plain `transition_mode` write, no scheduler lock needed) and asserts the hung worker stays NO_SIGNAL across repeated paused ticks (never FAILED, never requeued, attempt stays 1), then completes EXACTLY ONCE on the first ACTIVE tick after resume (attempt 2, one claim set, A's late write discarded); `test_21_f15_rejected_gate_wave_stops_recovery_still_completes` REJECTS the gate mid-transition and asserts the wave stops at the rejected gate (gate FAILED exactly once: one GateFailed + one HumanGateResolved, zero GatePassed, second resolve refused NOT_WAITING) while the dead worker still completes the Decision-4 chain exactly once. Both stable 3/3. Both folded into the horizon-cliff and one-verdict diagrams (render re-verified).

**Second follow-up legs (1a3b927 + 2): race, ordering, and re-park.** Three more probes complete the
composition family. `test_21_f15_operator_resolve_racing_recovery_first_miss` races the operator verdict
against B's mid-recovery tick loop (the resolve window is opened deterministically with B mid-tick, so
the overlap is proven by construction, not by LOCK-collision luck): exactly one verdict (one
HumanGateResolved + one GatePassed), the gate lands SUCCEEDED, and no FAILED hop precedes the verdict's
event in journal order — the F15-audit mode gate held under the race; the recovery chain then completes
exactly once (attempt 2, one claim set) and A's late write is discarded. `test_21_f15_recovery_before_dispatch_same_tick`
pins the tick's internal ordering deterministically: one tick that both requeues a dead worker (PAUSED
first miss) and dispatches a fresh task records every ext-1 hop before every ext-2 hop (journal `event_id`
order), ext-1 carries the RETRYING hop while ext-2 never does, and both completions land as two
distinguishable claim sets (distinct content — the PA4 dedup collapses identical statements).
`test_21_f15_second_gate_reparks_wave` drives a second gate in the same wave: gate-1 REJECTED returns the
mode to ACTIVE, and the very tick that completes the dead worker's recovery re-parks gate-2 at
AWAITING_HUMAN; the wave stops again until gate-2's own verdict (APPROVED) — each gate exactly one
verdict, zero cross-talk, one completion each. All three stable 3/3 and folded into the horizon-cliff and
one-verdict diagram manifests.

**Third follow-up legs (e07dfae + 1): dep-edge ordering, REJECTED-race, and schedule invariance.** Three
more probes complete the family. `test_21_f15_recovery_before_dispatch_dep_edge` makes the same-tick
ordering LOAD-BEARING: ext-2 depends on ext-1 (the requeued dead worker), so ext-2's claim is F-10-gated
on ext-1 SUCCEEDED — the journal order pins recovery-before-dispatch with the dependency edge in the way
(every ext-1 hop precedes every ext-2 hop; ext-1 carries the RETRYING hop, ext-2 never does).
`test_21_f15_rejected_verdict_race_retryable_task` (built on the shared `_run_f15_resolve_race_once`
helper) races a REJECTED verdict against B's mid-recovery tick loop on a RETRYABLE worker: exactly one
verdict (one HumanGateResolved + one GateFailed, zero GatePassed), the retryable worker is requeued and
re-executes exactly once (attempt 2, one claim set), no FAILED hop precedes the verdict in journal order,
and a second resolve is refused NOT_WAITING — attempts stay coherent under the race.
`test_21_f15_resolve_race_outcome_invariant_across_schedules` is a property-style test: six seeded random
schedules (varied B-loop pacing, resolve-loop pacing, and verdict) must ALL yield the same invariants —
exactly one verdict (never both), exactly one worker completion at attempt 2, one claim set, no FAILED
hop before the verdict, terminal second resolve — so the one-verdict/one-completion guarantees are a
pure function of the inputs, not of the scheduler. All folded into the horizon-cliff and one-verdict
diagram manifests (render re-verified).

**Fifth follow-up legs (next + 1): chained-gate ordering, exhausted-retry schedule property, and the bounded-completion stall-surfacing probe.**
Three more probes complete the F15 composition family. `test_21_f15_recovery_before_dispatch_chained_gates`
extends the dep-edge ordering to a CHAIN: gate-1 depends on the requeued dead worker and gate-2 depends
on gate-1, so gate-2's park is transitively gated on the worker's recovery. Tick 1 (paused) marks ext-1
NO_SIGNAL with BOTH gates PENDING; after resume, tick 2's recovery completes ext-1 (attempt 2) and
dispatches gate-1 to WAITING_HUMAN — the wave stops; the operator's APPROVED verdict resolves gate-1,
and the very next tick re-parks gate-2. Journal order pins every ext-1 hop before every gate-1 hop and
every gate-1 hop before every gate-2 hop, each gate parks exactly once (two HumanApprovalRequested),
and both verdicts land once (two GatePassed, zero GateFailed). `test_21_f15_exhausted_retry_race_property_schedules`
is a property-style invariance test for the exhausted-retry REJECTED race: five seeded random schedules
(varied B-loop and resolve pacing) must ALL yield worker FAILED at attempt 1 (never re-executed, zero
RETRYING hops, zero claims), exactly one HumanGateResolved + one GateFailed, zero GatePassed, no FAILED
hop before the verdict, mode ACTIVE, terminal second resolve NOT_WAITING.
`test_21_f15_resolve_race_stall_is_surfaced_not_masked` probes the helper's bounded completion budget
itself: a THIRD controller takes the scheduler lease the instant the APPROVED verdict lands (B's racing
loop is skipped entirely for the stall probe — the worker is still NO_SIGNAL, nothing else can recover
it) and is CONFIRMED holding it before the resolve returns; every post-verdict recovery tick is then a
LOCK refusal and the worker can never reach a terminal state, so the bounded budget FAILS LOUDLY
(`post-verdict recovery chain STALLED ... a held lease or deadlock was surfaced, never masked`) — the
completion loop is a genuine liveness check, never a mask. All folded into the horizon-cliff and
one-verdict diagram manifests (render re-verified).










**Twelfth follow-up legs (9ccf5d1 + 1): the mixed-mesh REJECTED-gate-2 x held-lease race, and the DOUBLE lease-handoff snapshot probe.**
Two probes complete the completion-budget and owner-snapshot stories. `test_21_f15_mixed_mesh_gate2_rejected_races_lease_holder` extends the gate-2 interleave with a HELD LEASE: a lease holder is armed the INSTANT gate-2 parks WAITING_HUMAN (the wave just stopped), so the operator's REJECTED verdict races it and is refused LOCK on every attempt (recorded via the new `gate2_refusals` sink) - gate-2 stays WAITING_HUMAN, the mode stays AWAITING_HUMAN, and the mesh chains never dispatch. The bounded budget then surfaces BOTH halves of the stall: the downstream chain (gate-2 AND the mesh tails - never the recovered worker, which already SUCCEEDED at attempt 2) in the stuck-task list, AND the lease itself via the blocking-owner snapshot (the holder controller-* id, never 'lock free'). The causal clause stays byte-identical to the healthy-graph false STALL - the owner line is what names the lease - and the same graph WITHOUT the holder completes (control, the plain gate-2 probe): the lease is what turns the interleave into a surfaced stall, never a mask. `test_21_f15_stalled_owner_snapshot_double_handoff` extends the lease-handoff probe to TWO owner changes mid-stall (handoff-1 at tick 3, handoff-2 at tick 5, each writing now+Nh so the older holder can never reclaim it and the locked_at ordering is strictly increasing): every snapshot before tick 3 names the live holder, ticks 3-4 name handoff-1, ticks 5+ name handoff-2 - and the FINAL STALLED message names ONLY the newest owner (handoff-2, whose locked_at is newest), never the holder and never the intermediate handoff-1. The atomic SELECT always reads the live row; the newest locked_at owner is authoritative even across two successive handoffs, and the message's named owner+locked_at equal the newest snapshot exactly.

**Eleventh follow-up legs (3aafb1f + 1): the mixed-mesh x REJECTED-gate-2 interleave, the STALLED blocking-owner lease-handoff probe, and the UNIFIED graph-scaled budget closed form.**
Three probes close the completion-budget story. `test_21_f15_completion_budget_mixed_mesh_gate2_rejected`
extends the mixed-shape mesh with a SECOND human gate (gate-2, dep gate-1) that parks WAITING_HUMAN the instant
gate-1 resolves and STOPS the wave: the operator then REJECTS gate-2 -> GateFailed, mode returns ACTIVE, and the
mesh chains (all dep gate-1 SUCCEEDED, never on the FAILED gate-2) dispatch one hop per tick. The bounded budget
must cover recovery + gate-2 park (tick 1) PLUS the gate-2 verdict PLUS the mesh hops: ticks used == 1 +
sum(depths); a budget of exactly sum(depths) (missing the interleave tick) false-STALLs naming the deepest mesh
level (never the worker or gate-2 - both terminal); the graph-scaled default completes; and journal order pins
the interleave (every ext-1 hop precedes every gate-2 hop, every gate-2 hop precedes every mesh hop). `test_21_f15_stalled_message_names_blocking_owner_row`'s sibling `test_21_f15_stalled_owner_snapshot_lease_handoff`
probes whether the STALLED blocking-owner snapshot can race a lease HANDOFF (the owner row is updated between the
last completion tick and the raise's SELECT): the snapshot is a single atomic SELECT of the live scheduler_lock
row, so it always reads the CURRENT owner+locked_at pair - the probe pins that every pre-handoff snapshot names
the SAME live holder (controller-*) with a locked_at, that a mid-stall handoff (the controller's own reclaim
write: UPDATE owner/locked_at, locked_at written +1h so the old holder can never reclaim it as stale inside the
window) is observed as the NEW owner by every post-handoff snapshot AND by the final STALLED message, and that
the message's named owner equals the newest snapshot owner exactly - the newest locked_at owner is authoritative;
the causal clause stays identical, the owner line is the discriminator. `test_21_f15_completion_budget_unified_closed_form` UNIFIES the graph-scaled budget: at max_calls_per_tick=1 the
post-verdict graph needs EXACTLY T = stall_depth + stall_wide_count + md*mw + sum(depths) + fan_total ticks (one
hop per tick across ALL shapes), and the scaled default is max(30, 10 + len(check_tasks) + T) - the SAME formula
for depth, wide, mesh, mixed mesh, fan, and any COMBINED graph (the combined five-shape case sums: 4 + 5 + 6 + 9
+ 7 = 31 ticks against budget 10 + check-set(13) + 31 = 54). The probe iterates a shape table and pins (a)
ticks_used == T, (b) completion_budget_scaled == the closed form, (c) budget == T - 1 false-STALLs, (d) budget
== T completes, (e) combined graphs sum.

**Tenth follow-up legs (f78bedd + 1): the mixed-shape mesh sum-of-depths pin, the STALLED blocking-owner discriminator, and the huge-fan headroom cap sweep.**
Three probes extend the completion-budget story. `test_21_f15_completion_budget_mixed_shape_mesh_sum_of_depths`
pins the NON-UNIFORM mesh formula via the new `stall_mesh_mixed=(depths,)` helper shape (per-chain hop counts):
shapes (2,5,7), (1,3,5,7), (3,6,9) each need SUM(depths) ticks at cap 1 (14, 16, 18 respectively), a budget of
sum-1 false-STALLs naming the healthy deepest mixed level, a budget of EXACTLY sum completes with
completion_ticks_used == sum, and the uniform max-depth x width product is NOT the requirement: for (2,5,7) the
product 7x3=21 exceeds the true 14, for (1,3,5,7) the product 7x4=28 exceeds the true 16, and for (3,6,9) the
product 9x3=27 exceeds the true 18 - the uniform formula cannot describe a mixed shape (only the degenerate
uniform case coincides with the sum). `test_21_f15_stalled_message_names_blocking_owner_row` probes
whether the STALLED message can distinguish a GENUINE held lease from a HEALTHY deep/wide false STALL: the
raise now snapshots the scheduler_lock owner row, so a genuine hold_lease_after_verdict stall names the
blocking owner (the holder controller id, controller-*) with its locked_at timestamp, while a healthy deep
(40-chain) or wide (300-fan) false STALL reports the lock FREE (no blocking owner row - the completion loop's
own ticks hold and release the lease, so no foreign owner exists at the raise). The causal clause stays
byte-identical across all three; the owner snapshot is the discriminator, pinned both ways. `test_21_f15_completion_budget_headroom_cap_sweep` sweeps max_calls_per_tick over 1, 2, 4, 8, 16, 32, 300 for
the 300-task fan: needed == ceil(300/cap) at EVERY cap, the graph-scaled budget is 312 regardless of cap, so
headroom (312 - needed) stays strictly positive at every cap (>= 12 at cap 1) - the scaled budget cannot be
exhausted by ANY cap choice, and only a genuine held-lease stall survives; a fixed budget of needed-1
false-STALLs at caps 1 and 8, and budget == needed completes at each - the headroom formula holds at every cap.

**Ninth follow-up legs (ceb52f1 + 1): the mesh exact-product-boundary pin, the deep-fan-chain total-nodes probe, and the huge-fan headroom measurement.**
Three probes pin the completion-budget formula precisely. `test_21_f15_completion_budget_mesh_exact_product_boundary`
pins the PRODUCT formula at the exact boundary: for several mesh shapes ((5,8) and (8,5) both 40, (6,6) = 36), a budget of EXACTLY depth*width completes the mesh (completion_ticks_used == product), while a budget of
depth*width - 1 false-STALLs it naming the healthy deepest level — confirming the requirement is EXACTLY the
product, neither over- nor under-sized, and the formula is pinned precisely rather than by a loose slack. `test_21_f15_completion_budget_deep_fan_chain_total_nodes` probes the widest possible graph shape:
a WIDENING fan (a fan-out at every chain level, an exponential tree — level k has width**(k-1) tasks, so the
total node count is (width**depth - 1)/(width - 1)) is seeded via the new `stall_fan=(depth, fan)` helper shape; its tick
requirement is the TOTAL NODE COUNT (each node is one tick at cap 1), and the graph-scaled budget adds exactly
that — a (4,3) tree (40 nodes) and a (3,4) tree (21 nodes) false-STALL under a fixed budget but complete under the
node-scaled budget, and the probe asserts each tree's tick need equals ITS OWN node count — the two shapes differ (40 vs 21), never a shared shape formula. `test_21_f15_completion_budget_huge_fan_headroom_measured` MEASURES the actual per-tick budget consumed by the
300-task huge fan via the new `completion_ticks_used` return and the `skip_racing_loop` deterministic
single-owner completion: the fan completes in EXACTLY ceil(300/8) = 38 ticks against the graph-scaled default budget of 10 + check-set(2) + 300 = 312,
so the measured HEADROOM is 312 - 38 = 274 ticks (~7x the needed budget) — the scaled budget is sized to the fan with documented
slack; the scaled budget cannot be exhausted by width, and only a genuine held
lease can trip it; the measured 38/312/274 figures are recorded here and in the diagram manifest.

**Eighth follow-up legs (b3b83b6 + 1): the mixed depth-x-width mesh budget lens, the third-gate partial-lease stall schedule property, and the huge dependency-fan budget probe.**
Three more probes close out the completion-budget story. `test_21_f15_completion_budget_mixed_mesh_depth_x_width`
(via the new `stall_mesh=(depth, width)` helper shape) seeds a MESH of `width` PARALLEL chains,
each `depth` hops long, all fanning out from the verdict gate: at max_calls_per_tick=1 every hop
is exactly one tick, so the graph needs depth*width ticks REGARDLESS of shape — a 5x8 mesh and
an 8x5 mesh both need 40 ticks. The probe pins that the requirement is the PRODUCT, not the
shape: a fixed budget below the product (35) false-STALLs BOTH shapes naming the healthy deepest
level (never the recovered worker), while the graph-scaled default budget (which now adds the
product: 10 + check-set + depth*width) completes both — only a genuine stall can exhaust a
budget sized to the mesh. `test_21_f15_third_gate_partial_lease_stall_property_schedules` adds
the property-style lens to the third-gate stall: five seeded schedules (varied resolve retry
pacing AND varied completion budgets, including budgets far ABOVE any healthy graph's need) ALL
surface the stall naming ext-mid AND ext-3 (the blocked intermediate and the third gate), never
the recovered worker ext-1 — the downstream-stall surfacing is a pure function of the held
lease, not of scheduling or of how long the budget runs. `test_21_f15_completion_budget_huge_fan_scaled_never_exhausted`
probes the huge dependency-fan: ONE verdict gate with 300 INDEPENDENT downstream extracts. At
the default 8 extracts/tick the fan needs 38 ticks — a FIXED 30-tick budget false-STALLs it,
naming the healthy tail (wide-300) with the byte-identical held-lease clause. But the
graph-scaled budget is SIZED TO THE FAN (adds the full 300), so a huge fan can NEVER exhaust it:
a fan of W needs at most W ticks at any per-tick cap, and the budget adds W — the scaled budget
is un-exhaustable by width, and only a genuine held-lease stall survives any budget. The probe
pins both halves: the fan cannot outrun the scaled budget, and the STALLED message cannot by
itself distinguish the fixed-budget false positive from a real lease stall (byte-identical
causal clause; the named task differs: wide-300 vs the worker).

**Seventh follow-up legs (14d6700 + 1): the REJECTED chained-gate schedule property, the third-gate partial-lease stall, and the completion-budget dependency-graph DoS lens.**
Three more probes complete the family. `test_21_f15_chained_gates_rejected_property_schedules`
(via `_run_f15_chained_gates_once(gate2_verdict="REJECTED", with_gate3=True)`) is a
property-style invariance test for the REJECTED middle verdict: five seeded random schedules
(varied park and resume pacing) must ALL yield gate-1 APPROVED, gate-2 REJECTED returning the
mode to ACTIVE, gate-3 (gated on gate-1 SUCCEEDED, never on the FAILED gate-2 — the mode
return is its eligibility gate) re-parked and APPROVED, with exactly three HumanGateResolved,
two GatePassed + one GateFailed, three HumanApprovalRequested (each gate parks exactly once),
one worker recovery at attempt 2 (one claim set), mode ACTIVE, terminal second resolve — the
REJECTED re-park guarantees are a pure function of the inputs, not of the scheduler. Note: the
helper gates gate-3 on gate-1 rather than making it fully independent because the helper's
ACTIVE phase-1 recovery window would let an independent gate-3 park early, flip the mode to
AWAITING_HUMAN, and mode-gate the worker's second-miss recovery forever (the deterministic db
probe uses PAUSED for that role; the REJECTED property is unchanged).
`test_21_f15_resolve_race_third_gate_partial_lease_stall_surfaced` extends the partial-lease
stall ONE HOP further downstream: the worker's post-verdict recovery SUCCEEDS (SUCCEEDED at
attempt 2), the first intermediate completes, but the SECOND downstream hop (ext-mid) — and
with it the third gate (ext-3, dep ext-mid) — stays blocked by a holder armed the moment the
worker recovers; the bounded budget surfaces the stall NAMING ext-mid AND ext-3 in the STALLED
message, never the recovered worker (the completion loop is a whole-chain liveness check, not a
worker-only mask).
`test_21_f15_completion_budget_deep_wide_graph_not_a_false_stall` is the dependency-graph DoS
lens on the bounded completion budget: a FIXED 30-tick count can be exhausted by a
LEGITIMATELY deep (40 chained extracts, one hop per tick) or wide (40 independent extracts at
max_calls_per_tick=1) post-verdict graph — the helper then raises a FALSE STALLED whose causal
clause ('a held lease or deadlock was surfaced, never masked') is byte-identical to a genuine
lease stall, so the error cannot by itself distinguish a held lease from a large healthy graph.
The probe pins (a) the false positive on both shapes (the healthy tail deep-40/wide-40 is
named), (b) the SAME graphs completing cleanly once the budget scales with the pending-graph
size (the new default: 30 + one tick per checked hop + slack), and (c) the byte-identical
causal clause across the false positive and a real hold_lease_after_verdict stall — the scaled
budget, not the message, is what separates the two. Disposition: the completion budget is a
test-helper liveness bound, not a product mechanism; it now scales with the graph it must
verify so a healthy large chain cannot be misreported as a held lease.

**Sixth follow-up legs (d29bc1a + 1): chained-gate REJECTED re-park, the partial-lease stall-surfacing path, and the chained-gate schedule property.**
Three more probes complete the family. `test_21_f15_recovery_before_dispatch_chained_gates_rejected`
extends the chained-gate ordering to a REJECTED middle verdict and a THIRD gate: gate-1 depends on the
requeued dead worker, gate-2 depends on gate-1, and gate-3 is INDEPENDENT (a FAILED dependency would
block it — the escape hatch is the mode return). Tick 1 (paused) marks ext-1 NO_SIGNAL with all three
gates PENDING; after resume, the recovery completes ext-1 (attempt 2) and gate-1 parks; gate-1 APPROVED;
gate-2 parks; gate-2 REJECTED returns the mode to ACTIVE; the very next tick re-parks gate-3. Journal
order pins every ext-1 hop before every gate-1 hop, every gate-1 hop before every gate-2 hop, every
gate-2 hop before every gate-3 hop; each gate parks exactly once (three HumanApprovalRequested); the
verdicts land once each (two GatePassed + one GateFailed); the mode returns ACTIVE. `test_21_f15_resolve_race_partial_lease_stall_surfaced`
probes the stall-surfacing path under a PARTIAL lease holder: the worker's post-verdict recovery ticks
SUCCEED (the worker reaches SUCCEEDED at attempt 2 and the intermediate ext-int completes) but a
downstream claim (ext-2, dep on ext-int, eligible only the tick after the recovery) stays blocked by a
holder armed the moment the worker recovers — the bounded completion budget surfaces the DOWNSTREAM
stall (STALLED naming ext-2) rather than silently succeeding on the worker's healthy shape: the
completion loop is a genuine chain-liveness check, never a worker-only mask (and the stuck-check now
lives inside the try, so the finally always releases A's thread and the holder even on the raise).
`test_21_f15_chained_gates_property_schedules` (on the new `_run_f15_chained_gates_once` helper) is a
property-style invariance test: five seeded random schedules (varied park and resume pacing) must ALL
yield two verdicts (gate-1 and gate-2 APPROVED), two gate parks, and one worker recovery at attempt 2
(one claim set), mode ACTIVE, terminal second resolve — the chained-gate guarantees are a pure function
of the inputs, not of the scheduler. All folded into the horizon-cliff and one-verdict diagram manifests
(render re-verified).

**Fourth follow-up legs (d9ed6f7 + 1): gate-dep ordering, exhausted-retry race, and re-park property.**
Three more probes complete the family. `test_21_f15_recovery_before_dispatch_gate_dep` makes the dep-edge
ordering LOAD-BEARING for a human gate: the requeued dead worker is the dependency of a HUMAN_GATE, so
the gate cannot park until the recovery completes the worker — the journal order pins every ext-1 hop
before every gate hop in the same tick, the gate parks exactly once (one HumanApprovalRequested), and
the mode returns AWAITING_HUMAN (the wave stops at the gate).
`test_21_f15_rejected_verdict_race_retries_exhausted` (via `_run_f15_resolve_race_once(worker_max_retries=1)`)
races a REJECTED verdict against B's mid-recovery tick loop on a worker whose retries are EXHAUSTED:
exactly one verdict (one HumanGateResolved + one GateFailed, zero GatePassed), the worker lands FAILED
at attempt 1 — never re-executed, zero RETRYING hops, zero claim sets — and no FAILED hop precedes the
verdict in journal order; the wave stops. `test_21_f15_second_gate_property_schedules` (on the new
`_run_f15_second_gate_once` helper) is a property-style test: five seeded random schedules of the
second-gate re-park must ALL yield exactly two HumanGateResolved (gate-1 REJECTED, gate-2 APPROVED:
one GateFailed + one GatePassed, zero cross-talk), one worker completion at attempt 2, one claim set,
mode ACTIVE, and a terminal second resolve — the re-park guarantees are schedule-independent. All
folded into the horizon-cliff and one-verdict diagram manifests (render re-verified).



The same composition exposed a second defect: A's late-returning stale
tick, after its acceptance was refused by the binding guard (task already
SUCCEEDED — case a of IDR29-02), continued its dispatch loop to the next
eligible task (the gate, now SUCCEEDED by the operator) and raised an
unhandled `TaskTransitionError` out of the tick (the PENDING → READY claim
validates BEFORE any write, so the generation fence never fired). The tick
contract is "never raises through the loop"; this crashed the controller
thread.

Fix (smallest): the dispatch claim now catches `TaskTransitionError` and
fails closed with a note ("status moved since discovery — recovery owns
it; skipped"), the exact IDR29-02 case-a semantics, so a stale/racing
controller skips the raced task instead of crashing. Product logic
unchanged for the honest path; the F15 cliff + hung-worker + live-worker
tests still pass.

### Finding 3 — Q-05 crossover holds: operator surfaces never touch epistemic state

`test_21_q05_operator_gate_resolution_never_touches_epistemic_state` seeds
live epistemic state (a research_program brief, a classification artifact
+ provenance edge, an APPLIED evidence_ladder_state row, a satisfaction
link, and an existing EvidenceTransitionApplied event), resolves a human
gate through the first-class operator surface, and asserts the ENTIRE
epistemic surface (research_programs, evidence_ladder_state,
thesis_evidence, research_claims, research_assumptions,
claim_assumption_links, program_requirement_satisfactions, artifacts,
provenance_edges) is byte-identical — same rows, same order — while the
journal gains ONLY the gate's own event types (TaskStatusChanged,
GatePassed, HumanGateResolved, ProjectResumed): zero
ClassificationAction*/EvidenceTransition*/ScopeReviewDecided events, zero
new ladder rows, zero new satisfaction links, zero program changes. The
only epistemic writer remains the controller tick's
`_apply_evidence_ladder_pass` (pinned by the Q-05 suite); no operator
surface reaches it.

**Cross-party confirmation (disposition — folded, corroboration only):**
the untracked `FRESH_REDTEAM_AUDIT.md` (an independent, READ-ONLY audit
from a separate session — zero tracked edits, audited at HEAD `f78bedd`)
independently re-derived the same Q-05 closures from live source
inspection and executable probes: the `contributing_factors` gate
remediation (source `requires_human_confirmation_for` line 823-835,
still present at current HEAD — a FRAMING_ERROR contributor on a
non-authority primary fires the gate, closing the prior MEDIUM), the
classifier-truth boundary (a wrong class can mis-route advisory content
but never convert a proposal into authority), the framework ADOPT
NARROWLY / REJECT postures for Q-05/Q-02/Q-04/Q-01, and the substrate
purity (no gateway/event/file/network writes from the classifier). Its
residuals (scope_briefs D5 label, Q-09/Q-07/CV-01 unstarted) match this
record's FUTURE-DESIGN dispositions. The audit file is cross-party
CORROBORATION of this record — recorded here so the Q-05 closure story
reads as two independent reviewers agreeing; the file itself remains
untracked source material (not a tracked artifact of this record).

### Governance observation — unsigned commits (IMPROVEMENT, not a blocker)

All closure commits on `origin/main` remain unsigned per GitHub metadata.
Recorded as a governance improvement candidate. The MINIMAL signed-tag
closure workflow the repo could adopt without new tooling: (1) `git tag -s`
closure commits (e.g. `v0.9-closure-f2`) with the operator's existing GPG
key — the key must be in `~/.gnupg` and GitHub configured to verify; (2)
`git push origin <tag>`; (3) record the tag hash in this reconciliation
record's commit list so a verifier runs `git tag -v <tag>` once; (4) tag
the closure DIRECTIVES (not every commit) — the RT rows' pinned tests +
commit ranges are the verification manifest. Nothing here blocks closure;
signing is a provenance convenience the repo can adopt when its
governance path is ratified.
