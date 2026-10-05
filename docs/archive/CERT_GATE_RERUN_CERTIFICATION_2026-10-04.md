# CERT-GATE-RERUN certification record — production declaration gate (2026-10-04)

Branch `cert/gate-rerun`, LOCAL-ONLY, NO PUSH. Base `main@1dd4c5e`.
Prior void attempt on `cert/gate@ffdfccb` is quarantined: never cited,
never built on. This record stands on fresh evidence only.

## §1 Lineage (commits in order)

| # | Hash | Subject |
| --- | --- | --- |
| 0 | `1dd4c5e` | base `main` (verified tip; live collection 2696) |
| 1 | `fe7691c` | CONTROL-2 seeded error set (§9.1, data before reviewers) |
| 2 | `030bc96` | CONTROL-2 reviewers A (AST, auditor) + B (lexical, held-out) |
| 3 | `12cfa61` | CONTROL-2 independence measurement (A 11/12, B 12/12, union 12/12) |
| 4 | (style commit) | ruff/pyright-clean of CONTROL-2 files, behavior-preserving only (A: nested-if merge ×2; B by held-out author: nested-if merge + direct return; measurement: `set()` operand fix); re-measured identical (A 11/12, B 12/12, union 12/12, `['fo-03']`) |
| 5 | (this record + checklist) | certification record + deployment checklist |

Changed files: `tests/cert_gate_rerun/seeded_errors.json`,
`tests/cert_gate_rerun/reviewer_a.py`,
`tests/cert_gate_rerun/reviewer_b.py`,
`tests/cert_gate_rerun/test_reviewer_independence.py`,
`docs/archive/CERT_GATE_RERUN_CERTIFICATION_2026-10-04.md` (this file).

## §2 Inputs verified

- `docs/ARCHITECTURE.md` §3.10: census re-measured exactly —
  121 executed tx calls (28 BEGIN / 27 COMMIT / 66 ROLLBACK), 27 owners
  + 1 rollback-only (`ClaimAssumptionRepository._validate_supersede_target`,
  `repositories.py` ~`:2401-2417`), persistence 18 / gateway 5 / Controller 4,
  15 persistence→research imports. Overall MATCH.
- DG-4 (`HERMES_DG4_…_2026-09-21.md`) §4 and DG-6 (`HERMES_DG6_…_2026-09-21.md`)
  §5 re-confirmed as the census authority; DG-5 exceptions remain certified.
- Audit trail on `main`: P-AUTO-1..6 merge logs + audits, H2, scan-fix
  (`docs/MERGE-LOG-*.md`, `docs/MERGE-AUDIT-*.md`), `docs/STATE.md`
  (F-01/F-02/A-01..A-04/D-01/D-02/B-01/B-03/F-03 carried unchanged —
  this gate neither reopens nor closes them).

## §3 CONTROL-1 — full suite, reconciled

- Live `--collect-only` on tip: **2696** collected.
- Full run `EXIT:0`; JUnit: `tests=2696 errors=0 failures=0 skipped=0`.
- Passed = 2696 − 0 − 0 − 0 = **2696**; collection == pass count, zero
  skips. No mismatch (the exact failure mode of the void attempt).
- `ruff check src tests`: `All checks passed!`
- `pyright src`: `0 errors, 0 warnings, 0 informations`.
- `pyright` tests project: `0 errors, 1 warning` — pre-existing
  `tests/test_research_program.py:144:23` (file untouched by this gate).

## §4 CONTROL-2 — seeded-error reviewer test (§9.1)

Seeded set: 12 defectives (INJECTION ×3, SECRET ×3, FAILOPEN ×3,
UNBOUNDED ×3) + 4 clean controls (`seeded_errors.json`, v1).
Reviewer A: auditor-authored, AST technique (`reviewer_a.py`).
Reviewer B: held-out author, lexical technique, written from the seed
spec without ever opening reviewer A (`reviewer_b.py`; separate file —
twin-function design explicitly rejected and not used).
Commit order: seeded (`fe7691c`) → reviewers (`030bc96`) →
measurement (`12cfa61`). Non-circularity by construction.

Measured (`test_reviewer_independence.py`, 3 passed):
`A recall: 11/12, B recall: 12/12, union: 12/12, advantage: +0,
disagreements: ['fo-03']`.
A misses fo-03 (approval tautology); B catches it — observed
disagreement from genuinely different techniques. Precision 1.0 both
(zero clean flags). Independence advantage: the pair holds 12/12
despite A's blind spot — robustness no single reviewer provides.

## §5 Boundary probes (fresh, pasted)

P1 planner authority — PASS:
`import-surface hits: []`; `nodes: 3 payloads: 3 journal rows
before/after planner: 1/1`; `P1 PASS: planner is data-only,
deterministic, zero journal writes`.
(`task_plan.py` imports no sqlite/persistence/gateway/socket; plan →
nodes/payloads pure and deterministic.)

P2 model egress — PASS:
`missing-fixture refused: no fixture for 'fx_1d9153ca…'`;
`corrupt-fixture refused: corrupt fixture: missing 'fixture_id'`;
`parser-mismatch refused: … pins parser '1', replay requires '2'`;
`P2 PASS: replay serves fixtures only; live transport contacted 0 times`.

P3 fetch scope — PASS: 4 scope refusals
(`VALID_NEGATIVE`/`REWRITE_SUSPECT`/`CURSOR_TRAP` at FETCH,
`NO_FULL_TEXT` at SEARCH); `legal verdicts passed: 18
(FETCH 8, SEARCH 10)`; `P3 PASS: scope confinement holds`.

## §6 Parked residuals — close or defer

| Residual | Disposition | Rationale (director-grade) |
| --- | --- | --- |
| durable budget counters (`autonomy_caps.py:76-77,295-338`; breach pinned ×11, durability ×0) | DEFER — trigger: first scheduled unattended run | Breach semantics pinned; durability changes failure semantics (persist vs re-grant) and needs schema/journal design + product ruling; per-run caps bound any restart re-grant. |
| quarantine appeal + un-quarantine (no `UNQUARANTINE`/appeal intent; quarantine+reimport pinned ×6) | DEFER — trigger: first operator appeal request | Quarantine is terminal FAILED + human-visible, never silent; an appeal path is a new intent kind = design gate by §3.11. Boot-failure fail-open bounded by DB task states. |
| B3 producer-side shared ref (`projection.py:70-74,308-365`) | CLOSE | Pinned: `test_b3_retraction_matches_shared_artifact_ref` + 5 production-shape tests. |
| vault manifest idea (only notes + `.projection-cursor` emitted) | DEFER — trigger: a vault consumer needs an index | Idea-stage; cursor + stable names suffice; new derived file needs consumer contract first. |
| X1/D2/C3 vault NOTEs (zero such channels; 30 `_note_once` keys surveyed) | DEFER — trigger: a cross-cutting note consumer is proposed | No consumer exists; current key namespaces cover all surfaces. |
| F1 harness (fault injection ×5, closed-loop seeded faults ×6, seq faults ×2) | CLOSE | Pinned across `test_failure_injection.py`, `test_p_auto_6_loop.py`, `test_p_auto_1_sequencer.py`. |
| proxy-path (`http.py:166-172` empty `ProxyHandler`) | CLOSE construction + DEFER E2E (trigger: next provider-surface change) | Opener pinned (`test_guarded_opener_ignores_https_proxy`); live E2E bypass-proof absent but allowlist is enforced below the opener. |
| operator knobs (`repositories.py:964-987` hardcoded; 24 behavior tests) | CLOSE hardcoded surface + DEFER configurability (non-goal) | No configurable/rotation surface exists to misconfigure; rotation is deployment policy, trigger-gated. |

## §7 Deployment checklist

1. Python 3.14, `uv sync` clean; full suite + ruff + pyrights green on
   the deployed commit (this record, §3).
2. Operator credential bootstrapped via `register_operator` before any
   verdict surface; no default credentials.
3. Single writer: scheduler lease held for verdict/cascade writes;
   `LOCK` contention refuses fail-closed; `lock_lost` aborts+rolls back.
4. Journal on durable SQLite (WAL-capable); backups snapshot the DB
   file; history never rewritten (no DELETE in `src/`).
5. Live provider paths run record-mode first; deploy fixtures with the
   release; replay refuses without a fixture (P2).
6. Human gates terminal with one-verdict rule; `HumanDecisionReceived`
   rows bound to command hashes (PROPOSAL refusal otherwise).
7. Budget envelopes at ratified values (`autonomy_caps.py` table);
   unattended runs stay scheduled-only until residual 1 closes.
8. Quarantine monitored: poison tasks FAILED + human-visible; appeal is
   manual operator action until residual 2 closes.
9. Retraction fencing active: N9 predicate + fail-closed dereference.
10. Vault notes labeled derived views; cursor persisted; never presented
    as authority (prohibited-claims discipline).
11. Outputs declare no scientific reproducibility/validity; replay
    proves bytes only.
12. No NOT-scope engines deployed with this release.

## §8 Verdict

Every gate above is green: CONTROL-1 reconciled (2696/2696/0 skips),
CONTROL-2 independent and measured, census MATCH, three boundaries
probed PASS, residuals closed-or-deferred with triggers, checklist
complete. Verdict: **PASS** — for the certified control-plane scope
only. This PASS declares nothing about scientific validity,
reproducibility, or any NOT-scope topic.
