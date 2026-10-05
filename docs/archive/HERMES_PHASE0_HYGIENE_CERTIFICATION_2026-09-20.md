# Hermes Phase 0 Hygiene Certification — 2026-09-20

## 1. Baseline

`HEAD == origin/main == 14fc64a` at start (branch `main`, tree clean
except pre-existing untracked `.freebuff/`, `IDEA.md`). Certified chain
P6 → N9 → P7 → tick-loop untouched throughout (no src/test behavior
changes; verified by full suite + gates below).

## 2. Initial uncommitted-file inventory

- `.freebuff/` — operator tool audit workspace (nested `.freebuff/`
  dirs, `audit2/` third-party source audits, logs). Local/generated
  only; contains no repository source. Now ignored (§4).
- `IDEA.md` (7 lines) — left untouched, see §9.
- `docs/archive/P7_MAINLINE_CERTIFICATION_2026-09-19.md`,
  `docs/archive/POST_P6_TICK_LOOP_CERTIFICATION_2026-09-19.md`,
  `docs/archive/HERMES_ARCHITECTURE_REPOSITORY_IMPROVEMENT_AUDIT_2026-09-20.md`.

## 3. Certification-report discrepancy resolution

Tick-loop report said 2, audit said 3. Physical truth: 3 uncommitted
(the audit report itself is the third; the N9 merge report was already
committed inside `14fc64a`). All three verified certification-evidence
only (matching SHAs/results of their gates), then closed in commit A.

## 4. `.gitignore` changes

Added `.ruff_cache/` + `.freebuff/` (with scoping comment). Verified
via `git check-ignore`. Minimal: no broad categories added. IDEA.md
deliberately NOT ignored (operator decision pending, §9).

## 5. Markdown inventory summary

89 root `.md` files. Method: per-file inbound-reference count across
root + `docs/idr` (script `Temp/opencode/mdinv.py`). Result: nearly
every file is referenced (README cites most audits; IDRs cite
designs; root docs cross-reference), so mass moves would rewrite
historical records. Only 8 files had zero inbound references; of
those, 2 are active/recent (`hermes_current_epistemic_architecture_
review.md`, `hermes_architecture_harvest_v2_addendum.md` — pair-split
risk) and were left in place.
Classification applied: KEEP at root = README.md, v6 architecture
source of truth, active designs/contracts/gates, lineage docs
(v3/v4), `steal.md` (active proposal), current-state reviews.
MOVE = 6 zero-inbound closed certification/audit/gate artifacts (§6).

## 6. Files moved and why

All via `git mv` (rename detection 100%, similarity 100%), zero
outbound markdown links in moved files (verified), zero inbound
references (verified), so no reference updates were required.
Remaining bare-name mentions live in historical pinned records
(`docs/ix/*.txt` snapshots, diagram provenance manifests) and one
glob pattern in the closure-gate package — intentionally not
rewritten (history preservation):

- `hermes_redteam_reconciliation.md` → `docs/archive/`
- `hermes_researchsourceprovider_step6_r01_resolver_audit.md` → `docs/archive/`
- `hermes_step4_s5_s7_decision_gate.md` (+ `_hashes.md` companion, pair
  kept together) → `docs/archive/`
- `hermes_step6_reconcile_design_gate.md` → `docs/archive/`
- `hermes_v6_fence_audit.md` → `docs/archive/`

Root `.md` count: 89 → 83. All other moves deferred to Phase 1 docs
architecture (documented ambiguity, not silently decided).

## 7. README changes

One factual paragraph appended after the post-v6 progression block:
certified chain P6 (`ff79bb6`) → N9 (`02cb976`, PR #1) → P7
CERTIFIED/CLOSED → tick-loop CERTIFIED (`633cff1`+`2328399`), suite
2035/0, Ruff/Pyright clean, report paths, archive note. No redesign,
no marketing, no architectural-claim changes.

## 8. Stub-pointer changes (docstring-only, CRLF-consistent)

Verified real homes first; edited 3, left 14+ untouched:

- `research/reconcile.py` → `Controller.tick()` (`controller.py:482`).
- `research/gates.py` → `MANDATORY_HUMAN_GATES` (`programs.py:157`),
  HUMAN_GATE nodes (`task_plan.py`), `resolve_human_gate/
  _park_human_gate` (`controller.py:1246/4268`).
- `research/evidence.py` → `evidence_ladder.py`.
- Left: `registration.py`, `provenance.py`, `integrity_gates.py`
  (no crisp single home — guessing would misdirect);
  `agents/*`, `engineering/*`, `recovery/*`, `vault/*`, `tools/*`,
  `artifacts/{cache,retention}` (genuine deferred/future-work
  stubs, not misleading about current behavior).

## 9. `IDEA.md` classification

- classification: LOCAL/PROJECT NOTE (personal agent-directive:
  Director role/posture prompt for the operator's own agent usage).
- reason: content is operator-tooling instruction, not project
  documentation, architecture, or certification material; 0 inbound
  references.
- recommended future location: keep out of version control
  (operator-local file); NOT committed, NOT ignored by this gate
  (minimal-scope rule) — operator decision.
- Left untouched.

## 10. Full test results

**2035 collected, 0 failed, 0 errors, 0 skips** (JUnit XML,
post-hygiene tree). Count unchanged from certified baseline —
no test was modified.

## 11. Static-analysis results

- `ruff check src tests`: clean.
- `pyright src`: 0 errors, 0 warnings.
- Tests profile: 0 errors + 1 pre-existing warning
  (`test_research_program.py:141`, untouched).
Identical to certified baseline.

## 12. Final diff scope

Commits A–C only: (A) 3 report files, +813; (B) `.gitignore` +4,
6 renames similarity 100%; (C) README +2, 3 stub docstrings
(+10/−6). No production source behavior (docstrings only), no
tests, no dependencies. `orci.json`/`orhead.json`/`ortree.json`
(untracked root JSON, alphaXiv/OpenResearch GitHub API data,
timestamped 09:29 during this session by external operator
tooling — not produced by any gate command) were investigated,
left uncommitted, and excluded from all commits.

## 13. Commit SHAs

- A `3f52fa3` docs(archive): close P7, tick-loop, architecture-audit
  certification reports.
- B `966d6aa` chore(repo): ignore local caches, archive closed
  audit/gate records (amended once, pre-push, to include the
  `.gitignore` hunk the first attempt dropped — own unpushed
  commit only; no certified history touched).
- C `1cb30fb` docs: refresh README certification status, point
  placeholder stubs at real implementations.
- D (this report) — SHA recorded in handoff after push.

## 14. Remote CI

Recorded in handoff (push + run watched to green).

## 15. Final repository state

`HEAD == origin/main`, tree clean except `IDEA.md` +
`or*.json` (external, uncommitted, documented). Root `.md`: 83.
Certified behavior unchanged (suite + gates identical to baseline).
Phase 1 ready: YES — docs architecture is now unblocked (archive/
convention established, ambiguous moves documented, not decided).
