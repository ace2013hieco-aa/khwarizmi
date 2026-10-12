# MERGE-LOG-CERT — land the CERT-GATE-RERUN certification line onto `main` (FF, LOCAL-ONLY)

Merge integrator record for the production declaration gate
(`cert/gate-rerun@a36d327`, audit verdict PASS with controls).
**Outcome: clean fast-forward, full gates green. `main` NOT advanced,
NOT pushed — D9 lapsed; merge + verification only. STOPPED BEFORE PUSH.**

Quarantined `cert/gate@ffdfccb` stays untouched and uncited throughout.

## Inputs

| Input | Value |
| --- | --- |
| Repository | `D:\New folder\research-agent` (`ace2013hieco-aa/khwarizmi-research`) |
| Worktree | `D:\New folder\merge-cert-wt` (isolated, branch `merge/cert`) |
| `main` local at task start | `1dd4c5e40e38375b765414e7db5d06050108eeb5` |
| `main` remote at task start | `1dd4c5e40e38375b765414e7db5d06050108eeb5` (unmoved) |
| Cert tip | `a36d327dc22615dbe36a13a3a1513d720dcaebaa` (`cert/gate-rerun`) |
| Cert scope | 5 files, +503/−0 (seeded set + 2 reviewers + measurement test + record) |
| Human approval | none — **D9 lapsed; no push under any circumstance** |

Topology (verified, not assumed):
`git merge-base main cert/gate-rerun` = `1dd4c5e` (== `main` tip),
`--is-ancestor` TRUE — the cert line descends directly from `main`;
clean FF expected and taken.

## Merge hashes

| Ref | Hash |
| --- | --- |
| `merge/cert` created off | `1dd4c5e` via `git worktree add -b merge/cert <wt> main` |
| FF advance | `1dd4c5e..a36d327` (`git merge --ff-only a36d327`) — zero conflicts |
| `merge/cert` post-FF | `a36d327` (identical hash — no `--no-ff`, no rewrite) |
| This log commit | (single commit, one file — hash recorded at commit time) |
| `main` old → new | `1dd4c5e` → **unchanged** |

Diffstat `main..a36d327` (`git diff HEAD a36d327 --stat` pre-FF):
`133` `docs/archive/CERT_GATE_RERUN_CERTIFICATION_2026-10-04.md`,
`159` `tests/cert_gate_rerun/reviewer_a.py`,
`121` `tests/cert_gate_rerun/reviewer_b.py`,
`1` `tests/cert_gate_rerun/seeded_errors.json`,
`89` `tests/cert_gate_rerun/test_reviewer_independence.py`
= 5 files, 503 insertions, 0 deletions. No `src/` changes on the merge
branch beyond the fast-forwarded cert commits themselves.

## Gate counts (on `merge/cert`, absolute paths, `PYTHONPATH=<worktree>/src`)

- Full suite: JUnit `tests=2699 errors=0 failures=0 skipped=0`,
  `EXIT:0` — passed 2699 = collected 2699 − 0 skips, reconciled
  (matches the director-verified cert-branch count; FF preserves hashes).
- CONTROL-1 statement: live `--collect-only` 2696 on tip pre-test-files;
  final tree 2699 (2696 + 3 independence tests); pass count reconciled
  both times, zero skips — the exact mismatch class that voided the
  prior attempt is absent.
- CONTROL-2 statement: commit order seeded (`fe7691c`) → reviewers
  (`030bc96`, separate files/authors/techniques) → measurement
  (`12cfa61`); measured `A 11/12, B 12/12, union 12/12`,
  disagreement `['fo-03']`, precision 1.0 both; twin-function design
  rejected and not used.
- `ruff check src tests`: `All checks passed!`
- `pyright src`: `0 errors, 0 warnings, 0 informations`.
- `pyright` tests project: `0 errors, 1 warning` — pre-existing
  `tests/test_research_program.py:144:23` (file untouched by this line).
- Census (§3.10): 121 calls (28B/27C/66R), 27 owners + 1 rollback-only,
  layers 18/5/4 — MATCH on this worktree.
- Boundary probes: planner data-only/deterministic/zero journal writes;
  replay 3 refusals with 0 live contacts; fetch scope 4 refusals + 18
  legal pass — all PASS.

## Residuals carried (from the certification record §6)

CLOSE: B3 shared ref, F1 harness, proxy opener construction,
operator hardcoded surface. DEFER with triggers: durable budget
counters (first unattended run), quarantine appeal (first appeal
request), vault manifest (consumer index need), X1/D2/C3 NOTEs
(note consumer proposal), proxy E2E proof (next provider change),
operator configurability (deployment policy). Prior `docs/STATE.md`
debt (F-01/F-02/A-01..A-04/D-01/D-02/B-01/B-03/F-03) carried unchanged.

## Conflicts — none

Fast-forward only; no merge commit, no manual hunks, no markers.
`git status` clean post-FF; this log is the sole additional commit
(docs-only, one file, no behavior change).
