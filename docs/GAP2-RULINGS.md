# GAP2-RULINGS — design-gate record for the Part-2 gap adjudication

Dispositions of the human design gate for the Part-2 gaps adjudicated
by `AUDIT-GAP-2-TRIAGE.md`. Documentation only: no behavior change; the
queued slices below are not executed here and each runs under its own
gate discipline.

- **Input report:** `Khwarizmi Gap and Hardening Priority Report, Part 2`
  (Oct 11 2026; report base `de99ae6`, not an ancestor of this line).
- **Triage input:** `AUDIT-GAP-2-TRIAGE.md` on `audit/gap-2-triage`
  @ `ab9ff74` (triage base `main@51cb10b`; verdicts: VALID 12 ·
  STALE 3 · DESIGN-OWNED 2 · NEEDS-INVESTIGATION 1 = 18).
- **Base:** `main@e565cd8dce6219869599ee6a01529b1539af2218` (verified
  local `main` == `origin/main`).
- **Scope:** the report's Director questions Q1–Q4, every adjudicated
  item P1-9…P3-18, the approved fix-slice queue, and the claim
  alignments this ruling set demands. No push; local-only.

## 1. Director-question rulings (Q1–Q4)

Numbering source: the triage record pins `Director Q1` (P1-11),
`Director question 3` (P2-22), and `Director question 4` (P3-13)
explicitly; the operational-independence ruling below answers the
remaining Director question carried by the same adjudication bundle
(P1-12/P2-21/P3-16).

| Q | Subject (triage item) | Ruling |
| :--- | :--- | :--- |
| **Q1** | Verdict semantics — acknowledge vs invalidate-and-reconcile (P1-11) | **ACKNOWLEDGE.** `RESOLVED` means the human reviewed and closed the contradiction. The verdict decides nothing between the parties and invalidates neither — both parties remain valid under the frozen N1 rule. Program completion requires that no UNREVIEWED (OPEN) conflict remains; no outcome payload is implied. An invalidate-and-reconcile verdict model is **out of scope this release** (future design track; P7 lifecycle + frozen N1 + human-authority boundary gate). |
| **Q2** | Lifecycle driver / operational independence (P1-12, P2-21; P3-16) | **OPERATIONAL INDEPENDENCE INTENDED.** No lifecycle driver ships this release: the controller tick reads mode only and never reads or advances lifecycle state; terminal lifecycle states stay operationally unreachable. Refusal-as-data for lifecycle transitions (P3-16) is deferred to the driver design (WP9) — no translation point exists today. |
| **Q3** | Quiescence as a completion condition (P2-22) | **NOT CONSULTED.** The completion contract stands unchanged: running tasks, human gates beyond mandatory, budget exhaustion and READY absence are deliberately INSUFFICIENT conditions and never part of the epistemic completion predicate (`completion.py:9-17`). Quiescence is not adopted as a condition this release. |
| **Q4** | Retraction scope (P3-13) | **PER-PROJECT INTENDED; GLOBAL PROPAGATION REJECTED.** Per-project retraction is the direct consequence of the certified project-isolation invariant. A retraction cascade propagating across projects is rejected; rationale recorded in §4. |

## 2. Item dispositions (P1-9 … P3-18)

| Item | Triage verdict | Disposition |
| :--- | :--- | :--- |
| P1-9 | VALID | Queued **CHG-DEDUP-1**: skip already-recorded pairs before submit (+ incremental candidates + multi-tick journal test). Suppressing duplicate `IntentApplied` rows is prohibited (append-only journal; pinned test). Gate: journal writer / `apply_intent`. |
| P1-10 | VALID | Queued **HR8-1**: predicate recomputes conflicts over fresh candidate rows (same-transaction, read-only). Gate: HR-08 completion choke point re-run. |
| P1-11 | VALID | Ruled Q1 (ACKNOWLEDGE). Claim alignments executed (§5); any verdict-model change is future scope. |
| P1-12 | VALID | Ruled Q2. Driver deferred (WP9); lifecycle module docstring aligned (§5). |
| P2-15 | VALID | Resolved doc-only in this slice: shared (edge-reachable) evidence is NOT cross-project citable; `_evidence_resolver` docstring aligned (§5). Code relaxation stays gate-blocked (project isolation). |
| P2-16 | NEEDS-INVESTIGATION | **RULED A — DOCUMENT THE BOUNDARY.** Documented in `docs/triage/P2-16-DETECTOR-BLIND-SPOTS.md`: the closed six-prefix evidence set and seven-field candidate row are accepted, with the coupling obligation recorded in `src/hermes/research/contradiction_candidates.py` and `src/hermes/persistence/failure_classifications.py` (`slice/p2-16-boundary`). B (diagnostic) and C (contract extension) declined — the ref-kind gap is unreachable by construction and the dimensional gap has no agreed semantics. **Last open GAP-2 item; no behavior change.** |
| P2-17 | VALID | Queued **CX-OVERLAP-1**: store the fresh in-transaction overlap on the recorded row. Gate: RECORD validator (N9-adjacent). |
| P2-18 | STALE | No action — eager S5 supersession predates the report base (`24225df`). |
| P2-19 | STALE | No action — gates can never be empty (executed probe). |
| P2-20 | VALID | Deferred with the driver design (WP9): edge guards + decision enforcement ride with the driver. Gate: lifecycle table + single-write path. |
| P2-21 | VALID (latent) | Ruled Q2. Tick terminal-lifecycle handling deferred with the driver; gate: tick loop. |
| P2-22 | DESIGN-OWNED | Ruled Q3. Contract unchanged; no code action. |
| P3-13 | DESIGN-OWNED | Ruled Q4. Per-project semantics stand; rejection rationale recorded (§4). |
| P3-14 | STALE | No action — supersession fires in production via the S5 retraction follow-on. |
| P3-15 | VALID (latent) | Queued **RESOLVER-PARITY-1**: one shared evidence-ref resolver + parity test. Behavior change feeds the N1 pair rule (gate); parity test alone needs no gate. |
| P3-16 | VALID (latent) | Ruled Q2 / deferred: refusal-as-data handling lands with the WP9 driver design. |
| P3-17 | VALID | Queued **CRES-DIGEST-1**: populate `resolution_rationale_digest` from the bound decision digest, or drop the column (decided in-slice). Gate: resolution path / schema. |
| P3-18 | VALID | Document-and-accept (this record): orphan decision rows on refused verdicts are bounded (deterministic `correlation_id` dedup; 4 KiB cap) and the gateway still refuses fail-closed; controller-side pre-validation rejected as TOCTOU-weak (§4). No gate (surface ordering). |

## 3. Approved fix slices queued

| Slice | Item | Change shape | Owning gate (re-run before merge) |
| :--- | :--- | :--- | :--- |
| **HR8-1** | P1-10 | in-predicate conflict recompute over fresh candidate rows, same-transaction read-only | HR-08 completion choke point |
| **CHG-DEDUP-1** | P1-9 | upstream skip of already-recorded pairs (+ incremental candidates + multi-tick journal test) | append-only journal / `apply_intent` |
| **CX-OVERLAP-1** | P2-17 | store the fresh in-transaction overlap on the recorded row | RECORD validator (N9-adjacent) |
| **CRES-DIGEST-1** | P3-17 | populate the resolution digest from the bound decision, or drop the column — decided in-slice | resolution path / schema |
| **RESOLVER-PARITY-1** | P3-15 | single shared evidence-ref resolver + parity test | N1 pair rule if behavior changes; gate-exempt if test-only |

## 4. Rejected / deferred alternatives (rationale)

- **Global retraction propagation — REJECTED (Q4).** A cross-project
  retraction cascade would weaken the certified project-isolation
  invariant; per-project retraction is the intended semantics, and
  every resolver staying project-scoped is what fail-closed citation
  depends on.
- **Invalidate-and-reconcile verdicts — out of scope this release
  (Q1).** Needs its own design gate (P7-certified lifecycle, frozen N1,
  human-authority fail-closed boundary). Until then `RESOLVED` is
  acknowledgment only.
- **Quiescence as a completion condition — NOT adopted (Q3).** The
  HR-08 predicate remains epistemic-only; the intent is that a
  parked/slow operation never blocks or manufactures completion.
- **Suppressing duplicate `IntentApplied` audit rows — PROHIBITED
  (P1-9).** Contradicts the append-only journal and the pinned
  duplicate-audit test; the accepted direction is upstream dedup only.
- **Controller-side verdict-target pre-validation — REJECTED (P3-18).**
  TOCTOU-weak; the gateway remains the fail-closed refusal point and
  the orphan decision rows are bounded and accepted (§2).
- **Lifecycle driver, edge guards, tick terminal handling,
  refusal-as-data translation — DEFERRED (P1-12, P2-20, P2-21,
  P3-16)** to the WP9 driver design; each carries its own
  certified-surface gate.

## 5. Claim alignments executed in this slice

- `README.md` (Limits): completion denial now states the verdict
  closes — acknowledges the conflict, decides nothing between the
  parties, invalidates neither.
- `docs/ARCHITECTURE.md` §3.7: reviewed and deliberately left
  byte-identical — it is a governed corpus member (`CORPUS_REFS`), so
  any edit forces a deliberate B4 fixture regeneration
  (`docs/gr3-b4/b4-fixtures/README.md` §Regenerating), which this
  slice excludes; the §3.7 flow asserts lifecycle closure only and
  already carries the N1 neither-party-invalidated clause.
- `src/hermes/research/gateway.py` `_validate_contradiction_resolution`
  docstring: "resolving" → "closing" + explicit acknowledge-semantics
  sentence.
- `src/hermes/core/lifecycle.py` module docstring: stale
  `request_transition()` reference replaced with the real mutation path
  (`ProjectRepository.transition_lifecycle`); no-driver statement added.
- `src/hermes/persistence/failure_classifications.py`
  `_evidence_resolver` docstring (P2-15): the artifact row must belong
  to the citing project; shared edge-reachable evidence is not citable.

## 6. Search proof — nothing further to align

- No repo text asserts global/cross-project retraction propagation
  (Q4) or orphan-free decision rows (P3-18) — nothing to change beyond
  this record.
- Judge demo already aligned: `docs/judge-demo/DEMO-TRANSCRIPT.txt` S6
  `RESULT: COMPLETION DENIED (OPEN_CONTRADICTION)`.

License: Apache-2.0 (LICENSE).
