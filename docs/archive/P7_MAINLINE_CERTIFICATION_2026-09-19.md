# P7 Mainline Certification — 2026-09-19

## 1. Exact repository identity

- Repository: `ace2013hieco-aa/khwarizmi-research`; branch `main`.
- `HEAD == origin/main == 14fc64a` (verified post-fetch).
- Tree clean: no tracked modifications (untracked only: pre-existing
  `.freebuff/`, `IDEA.md`, recorded separately, untouched).
- `02cb976` is an ancestor of HEAD; `docs/archive/
  N9_MAINLINE_MERGE_CERTIFICATION_2026-09-19.md` present.

## 2. Certified baseline

`14fc64a` (N9 merge `e37cd00` + certification report). Prior P7 verdict B
(at `ff79bb6`, N9 missing); N9 design/implementation/mainline-merge all A.
This run closes P7 on the actual mainline. No production code modified by
this gate (read-only experiments; DBs/scripts in temp).

## 3. `ff79bb6 → 14fc64a` change audit (inspected diff, not messages)

1. N9 implementation (`02cb976`): `source_outcomes.py` +25 (predicate),
   `failure_classifications.py` ±36 (substrate + in-tx re-check),
   `controller.py` N9 hunks (import, derivation filter, docstring),
   `gateway.py` ±31 (resolver + in-tx re-resolution).
2. N9 tests: `tests/test_n9_retraction_admission.py` (new, 21 tests).
3. N9 certification/report docs (`docs/archive/`, wiring audit).
4. Main-side CHG-1: `tests/test_chg1_contradictions.py` +34 (known).
5. Other: IX report docs; controller ACTIVE-loop wiring (`633cff1`:
   per-tick `_detect_contradictions_pass()` on the held lease/fence,
   lease-wrapper split of `detect_contradictions`)
   + loop-notes diagnostic (`2328399`).
- `gateway.py` / `failure_classifications.py` / `source_outcomes.py`
  deltas are exactly the N9 hunks (hunk-header audit).
- S5 cone/markers/events, `_source_artifact_resolves`, N1
  (`contradictions.py:106-162` untouched), admission/derivation/
  resolution semantics: unchanged except the N9 additions.
- Old P7 assumptions hold: standalone `detect_contradictions()` keeps
  P7-baseline semantics (lease-wrapped same-body pass).

## 4. Positive workflow evidence (mainline, `p7a_main.py`)

Recorded OpenAlex search+fetch via production handlers
(`source_search_11732ec7086c4fc5760ab2b2`,
`source_fetch_dd8660eed278bd3e11ef2d6d`, 2 `RECORDED_SUCCESS`
interactions, fixtures `fx_7e81…`, `fx_0b1a…`) → evidence
`source_result:a42a8a0b…886` (`art_a42a…886`).
A: `fc_cdfb9f7623a11a85471a0452` (`classify_0bfc…`, `DECLARED_CONSTRAINT_
VIOLATION`, task `t-analysis-1`, journal event 15).
B: `fc_f40614d61fe2a106ce1cf3c5` (`classify_dc66…`, `IMPLEMENTATION_
FAILURE`, task `t-analysis-2`, journal event 17).
Detect → `cx_244a7f06b08f965406518815` OPEN (event 19, corr = cx ID,
`cx-detect-v1`, canonical order); re-detect duplicates, 1 row.
HR-08: `eligible False`, `[OPEN_CONTRADICTION]`; walked to REPORTING →
`TransitionError: … HR-08 … OPEN_CONTRADICTION:cx_244a…`; status OPEN;
`rp-2` head unaffected.
Unauth ×4: `OPERATOR` / `PROPOSAL` (hd-ghost) / `ROLE` (DIRECTOR) /
`LOCK` (held lease); OPEN; 0 resolution events.
Authorized: event 37 (verdict, rationale) → event 38
(`ContradictionResolved`, corr `cres_40f202386337c77177ca10ff`,
`resolution_event_ref` set) → RESOLVED; re-detect `recorded: []`.
Retry: denials `[]`, transition `COMPLETED-ALLOWED`; `p1` = COMPLETED.
IDs identical to the `ff79bb6` run (cross-baseline determinism).

## 5. N1–N10 matrix (mainline)

| Control | Setup | Expected | Observed | Result |
|---|---|---|---|---|
| N1 same twice | re-record A | duplicate, same entity | `duplicate True`, same ID | PASS |
| N2 same class | two IF, disjoint ev | no record | `recorded: []` | PASS |
| N3 no overlap | DCV/ev1 + IF/ev2 | no record | `recorded: []` | PASS |
| N4 invalidated party | mark A INVALIDATED | excluded + hand-built refused | `[]`, `EVIDENCE_REF` | PASS |
| N5 cross-project | p1/p2 well-formed + p2 cites p1 ev | refuse cross, per-project `[]` | `MALFORMED_PAYLOAD` (`EVIDENCE_DOES_NOT_RESOLVE`, foreign), `[], []` | PASS |
| N6 unauth | §7 four attempts | OPEN, 0 events | as observed | PASS |
| N7 reopen | re-detect RESOLVED | duplicate, stays RESOLVED | `duplicates 1`, RESOLVED | PASS |
| N8 resolution-as-party | event-ID + kind strings as party | `EVIDENCE_REF` ×2 | as observed | PASS |
| N9 invalidated evidence | retract → fresh pair | write refuse + detect `[]` | `[True, True]`, `[]` (was `[False, False]`, `[cx_65fc…]` pre-N9) | PASS |
| N10 self-resolution | kind boundaries | internal-only, non-proposable | all four assertions true | PASS |

N9 suite file on mainline: 21/21 (`tests/
test_n9_retraction_admission.py`).

## 6. N9 closure evidence (mainline, Phase 4)

Retract `source_result:a42a…` (production `record_source_retraction_decision`)
→ fresh v2.0 citation: `rejected True`, `MALFORMED_PAYLOAD`,
`EVIDENCE_DOES_NOT_RESOLVE` in detail, 0 new rows; `detect: []`.
Pre-retraction rows cannot become usable again (row persists, resolution
excludes it). Production path throughout (`record_failure_classification`
→ `apply_intent` → gateway → repository).

## 7. Invalidation/supersession evidence (mainline, Phase 6)

Supersede chain: `cx_6cd1…` SUPERSEDED by `cx_0cc7…` (event 16, corr
`…:superseded-by:…`), history retained, no DELETE, supersede-resolved
→ `PROPOSAL`. S5 retraction: cone invalidates both parties
(`invalidation_marker`, `invalidated_by=rd-retract_…`), contradiction
SUPERSEDED (event 11, corr `…:superseded:retract_…`). Re-review while
OPEN seeds both parties with `reached_via="contradiction"`. N9 code did
not alter S5 (S5 hunks absent from merge delta; `TestN9B` +
`test_supersession_path_unaffected` green).

## 8. Authority evidence (mainline, Phase 7)

§4 S9 + N9 adversarial: bad credential `OPERATOR`, fabricated verdict
`PROPOSAL`, wrong role `ROLE`, held lease `LOCK`, journal-failure
rollback (0 rows), classifier cannot resolve (kind-boundary
assertions). Authorized: decision event → resolved event → RESOLVED
(§4). LLM surfaces propose nothing (`llm_proposable` excludes both
kinds).

## 9. HR-08 evidence (mainline, Phase 8)

OPEN → `eligible False` + choke naming the contradiction (§4);
RESOLVED → denial cleared + `COMPLETED-ALLOWED`. Superseded party's
program: `rp-2`-head unaffected (no `OPEN_CONTRADICTION`); retracted-cone
programs lose the denial once superseded (re-detect `[]`).

## 10. Determinism evidence (mainline, Phase 9)

Rebuild-identical: entities `fc_1473…`/`fc_5410…`, commands
`classify_f676…`/`classify_89d2…`, contradiction `cx_8bd1…` in both
builds. Cross-run: replay reproduces A/B/cx IDs exactly
(`fc_cdfb…`, `fc_f406…`, `cx_244a…`). Canonical ordering asserted on
rows. Task/lease UUIDs correctly excluded from identity.

## 11. Project-isolation evidence (mainline, Phase 10)

p2 detector `[]`, 0 p2 contradiction rows, p2 completion denial only
`NO_PROGRAM`, p2 re-review 0 items; cross-project citation refused at
write with foreign-evidence detail. NO CROSS-PROJECT CONTRADICTION;
NO CROSS-PROJECT EVIDENCE ADMISSION.

## 12. Journal/replay evidence (mainline, Phase 11)

Scenario journal: 15/17 (classification verdicts) → 19 (DETECTED, corr
cx) → 37 (resolution verdict) → 38 (RESOLVED, corr `cres_…`); final
status RESOLVED, project COMPLETED. Supersession/invalidation correla-
tions present; no DELETE anywhere in `src` (grep-verified); mutable
projection preserved. Replay of fixtures reproduces hashes + IDs
(§10 cross evidence).

## 13. Zero-live-contact evidence (mainline, Phase 12)

`RefusingTransport.contacted == 0` in record-replay, replayed-semantics,
and missing-fixture runs; missing fixture → FAILED (fail-closed).
Refusal raises `AssertionError("live provider contacted")` on any
contact — never raised.

## 14. Full regression (mainline, Phase 13)

**2035 collected, 0 failed, 0 errors, 0 skips** (JUnit XML; +1 vs the
2034 branch certification = main-side chg1 additions, explained).
Certified subset re-run: 156/156 (n9 21 + chg1 53 + chg2 26 + p4 16 +
p6 27 + hr08 13).

## 15. Static analysis (mainline, Phase 13)

`ruff check src tests`: clean. `pyright src`: 0 errors. Tests profile:
0 errors + 1 pre-existing warning (`test_research_program.py:141`,
untouched).

## 16. Out-of-scope verification (Phase 14)

This gate modified nothing (tree: only this report will be added;
`git status` otherwise shows pre-existing untracked only). STALE
project-filter wart: present, unmodified. Ancestor semantics:
unmodified. Tick-loop wiring (`633cff1`/`2328399`): present on main,
exercised only for a non-certifying interaction check (OPEN cx +
`run()`: 1 row retained, still OPEN, duplicate-idempotent; loop-notes
surface exists) — documented, NOT certified. No contradiction/provider
semantics changed.

## 17. Final verdict

### A — P7 CERTIFIED / CLOSED

Complete workflow, N1–N10 (incl. N9), invalidation/supersession,
authority, HR-08, determinism, isolation, journal/replay, zero live
contact, and full regression all pass on `14fc64a` with no unexplained
discrepancy.
