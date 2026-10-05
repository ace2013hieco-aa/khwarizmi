# HERMES S-2 — HumanDecision Idempotent-Append Extraction Certification

## §0 Verdict

```text
S-2 — CERTIFIED
```

## §1 Identity

| Item | Value |
|---|---|
| Repository | `github.com/ace2013hieco-aa/khwarizmi-research` (origin verified) |
| Branch | `main` |
| Baseline SHA | `fe0aa1c3dbf9dd8eea9528236564ea5610f8952b` |
| Baseline check | `HEAD == origin/main == fe0aa1c…`, no staged/unstaged tracked changes; untracked only the known items |
| Implementation SHA | `3cfaa38ac9233c7449816792adf7177670ac59c6` |
| Certification SHA | the commit that adds this file — a document cannot embed its own hash; by construction it is the direct child of `3cfaa38` with parent relationship proven in §11 and `HEAD == origin/main` verified after the push |
| Final HEAD | `HEAD == origin/main` = certification commit (§11) |
| Working tree at close | known untracked only: `IDEA.md`, `Prompts/`, `orci.json`, `orhead.json`, `ortree.json` — untouched, unstaged, uncommitted |

### Provenance disclosure (operator-authorized adoption)

Two S-2 artifacts pre-existed in the working tree as **untracked files
created after the baseline commit** by an interrupted prior attempt
(mtimes 2026-09-20 17:16/17:18; baseline commit 16:37; never committed on
any branch; the helper was inert — zero references in `src/`):

- `src/hermes/research/verdict_decisions.py` (the DG-3A §17 helper)
- `tests/test_s2_human_decision_append.py` (the S-2 suite, 5 tests)

This was a working-tree inconsistency vs the expected state (DG-3A §1:
"clean except known untracked") and — per §0/§13 of the implementation
task — was reported and **not** silently adopted. Under explicit operator
authorization the files were adopted, re-verified against the baseline
and the DG-3A specification, and completed. The mandated ordering was
preserved and evidenced: the adopted suite ran **5/5 green against the
untouched baseline Controller**, and the completed 6-test suite ran
**6/6 green against the untouched baseline Controller**, both *before*
any production edit (§8). The original run additionally surfaced one
real defect in the prior attempt — the C-S2-2 failure injection targeted
only the controller's append seam and would have failed after the
extraction — fixed before the production change (§4).

## §2 Authorization

Reference: **DG-3A S-2 Per-Surface Verdict Seam Design Gate**
(`docs/archive/HERMES_DG3A_S2_VERDICT_SEAM_DESIGN_GATE_2026-09-20.md`,
committed at `fe0aa1c`), which returned
`DG-3A — S-2 DESIGN GATE PASSED / IMPLEMENTATION AUTHORIZED`.

Authorized, exactly one unit (S-2h): extract the shared
idempotent-`HumanDecision` append step used by the four V-a verdict
surfaces, as
`record_human_decision_once(*, conn, clock, project_id, correlation_id,
caused_by, reason, payload) -> bool` (§17 shape).

Explicitly rejected by DG-3A and **not** performed: per-surface verdict
method moves (§18 anti-seams); lease acquisition/release; fence
validation; HumanDecision authorization/verification; gateway admission;
intent construction; journal writing; `IntentApplied`; identity/correlation
generation; persistence transaction ownership; V-b/V-c/V-d changes.
The four V-a surfaces remain structurally intact.

## §3 Pre-change evidence (baseline `fe0aa1c`, physical source)

Four V-a sites and their shared operation (method spans AST-measured
on both revisions; HD block line ranges verified by full reads):

| Surface | Method span @ baseline → @ HEAD | HD check-append block @ baseline |
|---|---|---|
| Curation | `controller.py:1595–1719` → `1596–1713` | `controller.py:1682–1694` |
| Source-retraction decision | `controller.py:1721–1866` → `1715–1853` | `controller.py:1830–1842` |
| Resolution | `controller.py:1981–2089` → `1968–2069` | `controller.py:2054–2066` |
| Classification | `controller.py:2091–2238` → `2071–2211` | `controller.py:2202–2214` |

Shared sequence (13 lines, four times): existence SELECT then conditional
append —

```sql
SELECT 1 FROM events WHERE project_id = ?
AND event_type = 'HumanDecisionReceived'
AND correlation_id = ? LIMIT 1
```

```python
if existing is None:
    _append_event_to_db(
        self._fenced, self._clock, "HumanDecisionReceived",
        project_id=self._project_id, correlation_id=decision_ref,
        caused_by="operator", reason=<per-surface>, payload=decision_payload)
```

Mechanical identity proof (AST, read-only):

- The helper's SQL constant equals **all four** baseline SELECT constants
  (Python folds the implicit string concatenation; comparison is exact).
- The append call shape is identical: positional
  `(conn, clock, "HumanDecisionReceived")`,
  keywords `{project_id, correlation_id, caused_by, reason, payload}`.
- The only per-surface divergence is `reason`, exactly:
  `f"operator curation verdict ({operation})"`,
  `"operator source-retraction verdict"`,
  `"operator contradiction-resolution verdict"`,
  `"operator classification verdict"` — all four preserved verbatim at
  the new call sites.
- No canonical helper existed at baseline: zero references to
  `record_human_decision_once` outside the (then inert) untracked module
  and the DG-3A document.

Surrounding boundaries (baseline):

- Transaction: no transaction owned by the HD step; it rides the caller's
  context. `_acquire_lock` opens/commits its own lease transaction
  (`controller.py:2355–2396`), `_release_lock` deletes the lock row
  (`2398–2402`); the surfaces' `try/finally` brackets own release.
- Lease/fence: the append runs inside the lease bracket and writes via
  `self._fenced` (`_FencedConnection` gates writes against the captured
  lease generation).
- Authority ordering: input checks → `_verify_operator` → decision-identity
  derivation → rationale size check → `_acquire_lock` → HD check-append →
  intent build → `apply_intent` → result/refusal mapping → `finally:
  _release_lock`.
- Gateway ordering: `apply_intent(self._fenced, intent,
  clock=self._clock)` executes immediately after the HD append; the audit
  event `EventType.INTENT_APPLIED` (`events.py:45`) is written by the
  gateway (`gateway.py:3852`), which owns all of its transactions.

## §4 Characterization

`tests/test_s2_human_decision_append.py` — 6 tests, green on the
untouched baseline **before** the production change and with byte-identical
assertions **after** (runs in §8):

| Test | Requirement | Proves |
|---|---|---|
| `TestCS21IdempotentDoubleRecord::test_classification_double_submit_one_decision` | C-S2-1 | same command twice → 2nd `duplicate=True`, same `entity_id`, exactly one `HumanDecisionReceived` row (duplicate, never refusal) |
| `TestCS21…::test_resolution_double_submit_one_decision` | C-S2-1 | same for the resolution surface |
| `TestCS22FailurePropagation::test_classification_append_failure_raises_no_gateway_no_state` | C-S2-2 | forced append failure raises through the caller, zero artifacts/events written, no gateway admission |
| `TestCS22…::test_resolution_append_failure_raises_no_gateway_no_state` | C-S2-2 | same for a second surface (DG-3A §19 V4): event count unchanged, contradiction row unchanged, lease still released by the caller's `finally` |
| `TestCS23Ordering::test_decision_precedes_resolution_admission` | C-S2-3 | `HumanDecisionReceived.event_id < ContradictionResolved.event_id` (verify → lock → HD → gateway) |
| `TestCS25Isolation::test_foreign_decision_ref_refused` | C-S2-5 | a p1 decision correlation replayed into p2 is refused fail-closed (`PROPOSAL`); no second HD |

C-S2-4 (per-surface equivalence) and C-S2-6 (existing-suite preservation)
are covered by **delegation**, per DG-3A §19 ("reference, do not
duplicate"): the existing per-surface suites keep their own duplicate and
scoping assertions and were re-run unchanged before and after:

- curation duplicate semantics: `test_step7_curated_registry.py:717–731`,
  `:966`, `:1240`, `:1551`; `:1515` (`duplicate=False` fresh);
- retraction-decision duplicate: `test_s6a_retraction_ingestion.py:516–521`;
  `test_s5_l2_resolution.py:633–637`; `test_n9_retraction_admission.py:698`;
- classification duplicate: `test_p6_classification.py:216`, `:511`;
- resolution duplicate: `test_chg1_contradictions.py:278`, `:297`.

### Adaptations disclosed (no assertion weakened)

1. **Adopted-suite fix (pre-production).** The prior attempt's C-S2-2
   test mocked `controller._append_event_to_db` only; after the extraction
   the verdict's first append executes in the new module, so the injection
   would no longer intercept and the test would fail (DID NOT RAISE).
   Before any production edit, the injection was retargeted to patch both
   seams; every assertion is unchanged, and the pin now holds pre- and
   post-extraction. The S-2 test method was renamed for clarity
   (`test_append_failure_…` → `test_classification_append_failure_…`).
2. **Two existing certified tests retargeted (assertion-preserving).**
   `test_p6_classification.py::TestDeterminism::test_journal_failure_rolls_back`
   and `test_n9_retraction_admission.py::TestN9Adversarial::test_journal_failure_rolls_back`
   injected failure the same way. Post-extraction the injected exception
   no longer fired (2 failures observed before the fix — the only two
   failures in the whole change). The again-identical injection targets
   both seams; **every assertion is byte-identical** (including the
   rollback / `_fc_count(db) == 0` / `real_append is …` assertions). No
   test was weakened, deleted, or reinterpreted; see §8/§10 for counts.

## §5 Implementation

| Item | Value |
|---|---|
| Helper path | `src/hermes/research/verdict_decisions.py` (new, 53 lines) |
| Helper symbol | `record_human_decision_once(*, conn, clock, project_id, correlation_id, caused_by, reason, payload) -> bool` (function at lines 23–53) |
| Import site | `controller.py:86` (`from hermes.research.verdict_decisions import record_human_decision_once`) |
| Call sites (post) | `controller.py:1683` curation, `:1824` retraction-decision, `:2041` resolution, `:2182` classification |
| Return | `bool` (True = recorded now, False = already present) — **ignored by all four callers**, exactly as today |
| Responsibility | exactly the existence check + one conditional append; nothing else |

The helper contains **no** transaction begin/commit/rollback, lease
acquire/release, fence acquire/validate, authorization decision, gateway
call, journal append beyond the one conditional event,
`IntentApplied`, identity generation, or UUID/random/time/provider
dependency. Its only imports: `__future__`, `typing.Any`,
`hermes.persistence.repositories._append_event_to_db` (the same writer
the four sites already called). Module body is docstring + 3 imports +
the function; no `__all__`, no exports (`hermes/research/__init__.py`
untouched), INTERNAL implementation location only.

## §6 Invariant proof

| Invariant | Result | Evidence |
|---|---|---|
| Transaction | PASS | helper owns none (AST scan: no `BEGIN`/`COMMIT`/`ROLLBACK`); caller `try/finally` bracket and gateway/repository transaction ownership unchanged; only the 4 inner blocks changed (`git show --stat`) |
| Lease | PASS | `_acquire_lock`/`_release_lock` bodies untouched (only line numbers shift); CS22 resolution test proves the lease is still released on failure |
| Fence | PASS | same `self._fenced` object passed as `conn`; `_FencedConnection` untouched; helper never references fence symbols |
| Authority | PASS | `_verify_operator` call sites, ordering and fail-closed refusals untouched; helper performs no check; adversarial authority suites green |
| Gateway | PASS | `apply_intent` call sites untouched at the same positions; gateway.py has **zero** changes; `IntentApplied` remains gateway-owned (`gateway.py:3852`) |
| Identity | PASS | no `uuid`/`hashlib`/`random`/`datetime`/`utc_now` in helper (AST scan: forbidden symbols NONE); correlation/payload arrive as caller-built parameters and pass through unchanged |
| Idempotency | PASS | check-then-append preserved verbatim (identical SQL + conditional append); duplicate stays `duplicate=True` (CS21 + delegated suites) |
| Journal | PASS | same single conditional `HumanDecisionReceived` row, same writer, same position; HD-before-intent order pinned by CS23 |
| Replay | PASS | no timestamps/randomness authored; clock and correlation passed through; deterministic event identity unchanged; replay suites green in the full run |
| Isolation | PASS | `project_id` explicit in the signature and in the SELECT predicate; cross-project probe refused (CS25) |
| N9 | PASS | `source_outcomes.py:159` predicate and all N9 paths byte-identical (`git show --stat` touches no N9 file); N9 suite 21/21 green |

## §7 Behavioral equivalence

Before = baseline `fe0aa1c`; after = implementation `3cfaa38`.

| Property | Before | After | Result |
|---|---|---|---|
| HumanDecision inputs | `(self._fenced, self._clock, project, ref, "operator", reason, payload)` | same values as explicit kwargs | PASS |
| Project scope | `self._project_id` predicate | same value as parameter | PASS |
| Correlation identity | caller-derived `decision_ref` | same value passed through | PASS |
| SQL/write operation | existence SELECT + conditional `_append_event_to_db` | byte-identical SQL, identical writer and call shape (AST-proven) | PASS |
| Duplicate behavior | duplicate ⇒ skip append, proceed | identical | PASS |
| Exception behavior | append failure propagates (no catch) | identical (helper has no try/except) | PASS |
| Connection/transaction | `self._fenced`, caller's context | same object, same context | PASS |
| Ordering vs gateway | HD append immediately before intent/`apply_intent` | same position (same lines region); CS23 event-id ordering | PASS |
| Journal effects | ≤1 `HumanDecisionReceived` per correlation | identical; CS21 counts == 1 | PASS |
| Replay effects | identical events on replay | identical (same correlation/idempotency semantics) | PASS |
| Public surface | 76 Controller methods | 76 methods, **0 signature diffs** (AST comparison) | PASS |

Test-count proof: affected slice 360 → 361 (the +1 is the additive
resolution failure pin; the other 360 assertions identical), full suite
2045 → 2051 (+6 S-2 tests) — all green both sides.

## §8 Validation

| Gate | Command | Result |
|---|---|---|
| Adopted suite vs untouched baseline (pre-production) | `.venv/Scripts/python.exe scripts/run_tests.py tests/test_s2_human_decision_append.py` | **5 passed** (adopted form), then **6 passed** after completion — before any production edit |
| S-2 suite post-extraction | same | **6 passed** |
| Affected slice pre-extraction | `… scripts/run_tests.py tests/test_{p6_classification,chg1_contradictions,step7_curated_registry,s5_l2_resolution,s6a_retraction_ingestion,n9_retraction_admission,controller,s2_human_decision_append}.py` | **360 passed** (5:18) |
| Affected slice post-extraction | same | **361 passed** (5:22) |
| N9 alone | `… scripts/run_tests.py tests/test_n9_retraction_admission.py` | **21 passed** |
| Full suite (final frozen tree) | `.venv/Scripts/python.exe scripts/run_tests.py` | **2051 passed in 372.98s** — 0 failed, 0 errors, 0 skipped (2045 baseline + 6 S-2) |
| Ruff | `uvx ruff check src tests` | **All checks passed** (3 issues found and fixed pre-commit: 1 import sort + 2 SIM117 in the new test file only) |
| Pyright src | `uvx pyright src` | **0 errors, 0 warnings, 0 informations** |
| Pyright tests profile | `uvx pyright --pythonpath .venv/Scripts/python.exe --project pyrightconfig.tests.json` | **0 errors, 1 warning** — pre-existing `test_research_program.py:141` (untouched; same warning recorded in the S-1 certification) |
| Profiled gate | `./scripts/profiled_gate.sh` | **OK** (profiled pyright + walking-skeleton smoke 5 passed) |
| Whitespace | `git diff --check` | clean |
| CI | `.github/workflows/ci.yml`, triggered by the push to `main` | jobs (`test`, `typecheck`, `local-gate`, `profiled-gate`, `lint`, `audit`) mirror the local invocations above; all local mirrors green pre-push |

No tooling configuration was modified. No test was skipped or weakened.

## §9 Adversarial review

All 24 questions from the implementation task §10, answered against the
actual diff:

1. Lease boundary moved? **PASS** — lock methods untouched (only shifted line numbers).
2. Fence check moved? **PASS** — `_FencedConnection` untouched; same conn object passes through.
3. Transaction boundary moved? **PASS** — no BEGIN/COMMIT/ROLLBACK in the helper; caller/gateway tx ownership unchanged.
4. Helper acquired/released a transaction? **PASS** — none (AST scan).
5. Helper generated an identity? **PASS** — no uuid/hashlib/random/datetime; correlation is an input.
6. Helper altered a correlation? **PASS** — passed through verbatim to SELECT and append.
7. Duplicate became refusal? **PASS** — CS21 (both surfaces) + delegated suite duplicate assertions green.
8. HumanDecision moved after the gateway call? **PASS** — call position identical; CS23 ordering.
9. `IntentApplied` moved? **PASS** — gateway.py zero changes; still gateway-owned (`:3852`).
10. Journal ordering changed? **PASS** — same write set/order; CS23 + full suite green.
11. Authorization ordering changed? **PASS** — `_verify_operator` untouched; helper performs no authority.
12. Failure propagation changed? **PASS** — no catch added; CS22 ×2 + the two retargeted certified journal-failure tests green.
13. Project isolation weakened? **PASS** — explicit `project_id`; CS25 cross-project refusal.
14. Helper publicly reachable? **PASS** — no `__all__`, no package export, no API doc entry, 4 src callers only.
15. Any Controller signature changed? **PASS** — AST diff over the full class: 76 → 76 methods, signature diffs **NONE**.
16. Gateway/repository code changed? **PASS** — diff touches controller.py + 3 test files only.
17. N9 protection changed? **PASS** — N9 files untouched; suite 21/21.
18. Replay/determinism changed? **PASS** — no authored time/randomness; full suite incl. replay green.
19. External/provider behavior appeared? **PASS** — no provider imports; helper deps: repositories append writer only.
20. Unrelated refactor included? **PASS** — diff is the seam + its tests (+ the two disclosed assertion-preserving retargets).
21. Genuine semantic commonality (not textual)? **PASS** — AST-proven: identical SQL constant ×4, identical append shape, identical kwargs; only `reason` varies (parameterized).
22. Callable outside the caller-owned transaction context? **PASS** — internal module, 4 call sites all inside lease-bracketed verdict bodies; helper owns no transaction; no new call path introduced.
23. Helper owns responsibility DG-3A kept in the caller? **PASS** — only the check-then-append; lease/authority/identity/intent/gateway/tx remain caller/gateway-owned.
24. Four V-a sites still recognizable? **PASS** — same names/signatures/docstrings/order; only the 13-line inner block became a 6–7-line call.

Result: **24 PASS / 0 FAIL / 0 blockers.**

## §10 Scope audit

Implementation commit `3cfaa38` — 5 files, +422/−52:

| File | Change |
|---|---|
| `src/hermes/research/verdict_decisions.py` | new (53 lines) — the authorized helper |
| `src/hermes/research/controller.py` | 1 import + 4 call-site substitutions (+25/−52) |
| `tests/test_s2_human_decision_append.py` | new (334 lines, 6 tests) |
| `tests/test_p6_classification.py` | +5 (assertion-preserving injection retarget, §4) |
| `tests/test_n9_retraction_admission.py` | +5 (assertion-preserving injection retarget, §4) |

No other production, test, schema, gateway, journal, migration, docs or
config file changed. Known untracked items (`IDEA.md`, `Prompts/`,
`orci.json`, `orhead.json`, `ortree.json`) were not modified, staged,
deleted, or committed. No later structural seam was started (no DG-3B,
no gateway extraction, no S-3).

## §11 Git proof

```text
baseline             fe0aa1c3dbf9dd8eea9528236564ea5610f8952b   (HEAD == origin/main)
                     └─ implementation commit follows
implementation       3cfaa38ac9233c7449816792adf7177670ac59c6   parent: fe0aa1c
                     subject: refactor(controller): extract S-2 HumanDecision idempotent append
                     └─ certification commit follows
certification        <this commit>                               parent: 3cfaa38
                     subject: docs(archive): certify S-2 HumanDecision append extraction
final HEAD == origin/main verified after push (see closing git record)
```

Both commits were pushed to `origin/main`; the certification commit is the
final `HEAD`. The self-hash is intentionally not embedded (§1).

## §12 Verdict

```text
S-2 — CERTIFIED
```

All success criteria met: baseline verified at `fe0aa1c`; DG-3A
authorization followed exactly (one shared helper, four substitutions,
characterization-first ordering evidenced on the untouched baseline);
four verdict surfaces not extracted; transaction/lease/fence/authority
ownership unchanged; gateway remains authoritative; `IntentApplied`
stays in the gateway; identity/idempotency generation stays caller-owned;
N9 untouched and green; project isolation explicit; replay deterministic;
all characterization and existing tests pass (2051/2051 full suite);
Ruff and Pyright clean; adversarial review 24/24; implementation and
certification are separate commits, both pushed; `HEAD == origin/main`.
