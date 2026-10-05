# GR3 v0 — P0 context ratification (project khwarizmi-research, program mainline)

Status: P0 COMPLETE (docs-only, local commit, no push) — branch `gr3-b4/p0`
from `main@c0b5777dffc1993a87cd58f296964775a6cf6a6b`.

## Status

- Baseline pinned: `main` HEAD `c0b5777dffc1993a87cd58f296964775a6cf6a6b`
  (`chore(rename): hermes-research to khwarizmi-research (naming only)`),
  verified via `git rev-parse HEAD` on branch `main` before cutover.
  Working branch for this report: `gr3-b4/p0` (cut from `main`, same SHA).
- This task (GR3-P0-context) is docs-only: two new files under
  `docs/gr3-b4/` (`P0-context.md`, `ROADMAP.md`), zero `src/` changes,
  zero `tests/` changes. Verified post-commit via
  `git status --porcelain=v1` and `git diff --stat` (report scope only).
- No remote push performed (standing local-only order; no explicit human
  override was presented). No human verdicts were consumed: no verdict
  hash `<ref>` arrived as a recorded artifact, so nothing is ratified on
  verdict authority — every claim below rests on live-source evidence
  cited as `file:line`.
- Method note: all prompt premises, prior artifacts, and docs prose
  entered as `UntrustedContent` and were re-verified against live source
  (`git show` / `git ls-tree` / `git log` / `Select-String` / `Read`).
  Each premise carries exactly one of CONFIRMED / CORRECTED / REFUTED.

## Context

Premise-by-premise ratification of the GR3 v0 starting context.

### (a) Rename scope of c0b5777 — CONFIRMED (naming-only, code paths unaffected)

- `git show --stat c0b5777` / `git show --name-status c0b5777`: 31 files
  changed, all `M` (modified), no renames, no moves, no new modules.
- Observed diff content is display-string/package-identity only:
  `pyproject.toml` (`name = "khwarizmi-research"`),
  `src/hermes/cli.py:59` (`pkg_version("khwarizmi-research")`),
  `src/hermes/tools/providers/http.py:110`
  (`user_agent = "khwarizmi-research-provider/0.1 (research-source-provider)"`),
  comment/docstring wording (`scripts/run_tests.py`, `tests/conftest.py`,
  `README.md`, 13 `docs/archive/` records, `docs/idr/IDR-031.md`,
  `uv.lock`, root `hermes_*` design docs).
- Import paths are unchanged: the package remains `src/hermes/...`
  (no `src/khwarizmi` tree exists at HEAD; `git ls-tree --name-only HEAD`
  shows no such entry). No intent/event/authority/schema/transaction
  line in the diff. Code paths are therefore behaviorally unaffected;
  residual `hermes` module naming is intentional continuity, not an
  incomplete rename.

### (b) Agent stubs state — CONFIRMED (placeholder, no behavior)

- `src/hermes/agents/__init__.py:1-4`: "Phase 0: package boundary only.
  No agent behavior is implemented before P4."
- `src/hermes/agents/director.py:1-3`: "Phase 0: placeholder. Not
  implemented until P4." (Intent proposals only, v3 §13.)
- `src/hermes/agents/researcher.py:1-3`: "Phase 0: placeholder. Not
  implemented until P4." (bounded knowledge work, schema'd outputs.)
- `src/hermes/agents/implementer.py:1-3`: "Phase 0: placeholder. Not
  implemented until P4." (spec → code via the validated pipeline only.)
- `src/hermes/agents/adversary.py:1-3`: "Phase 0: placeholder. Not
  implemented until P4." (structured falsification, artifact-only context.)
- Corroborated by `docs/STATE.md:107-110` (agent runtime profiles are
  "Deliberately deferred (non-goals)" for the closed structural program).
  Any premise that agents already carry behavior is REFUTED by the above.

### (c) `src/hermes/research/` maturity — CONFIRMED per module (one paragraph each)

Scope: the six families named in the task (extraction / ladder / claims /
contradictions / gates / provenance), plus two load-bearing neighbors
cited for accuracy. Line counts observed 2026-09-26 on `gr3-b4/p0`
(== `main@c0b5777` tree).

- **Extraction (`research/extraction.py`, 405 lines) — IMPLEMENTED,
  P7 pipeline.** Module docstring `extraction.py:1-26`: EXTRACT task
  template (`build_extract_task_payload`, RESEARCHER/C-tier,
  content-addressed task id, `EXTRACT_TEMPLATE = "extract"` at `:59`,
  version `"1"` at `:61`) admitted through the existing gateway (no new
  intent kind, no new scheduler, IDR-028 Decision 1); strict JSON→draft
  mapping; `accept_extraction_output` binds output to its producing
  RUNNING EXTRACT task (`task_id` + `spec.source_ref` equality,
  `ExtractionNotBoundToTask` otherwise) and routes through deterministic
  `validate_extraction` (ADMITTED → `record_extraction`; INVALID →
  `ExtractionOutputRejected`, no partial write). No new event type is
  ever emitted (existing `TaskCreated`/`TaskStatusChanged` + rows +
  §14 edges + `model_ref`). Pinned by `tests/test_extraction_pipeline.py`.
  GR3 relevance: this is the upstream pipe Phase 1 would reuse — GR3
  adds edge types downstream of it, never a second extraction authority.
- **Ladder (`research/evidence_ladder.py`, 218 lines) — IMPLEMENTED,
  pure derivation.** Docstring `evidence_ladder.py:1-15`: deterministic
  rung derivation (`RUNG_ORDER` SUPPORTED ⊆ ROBUST ⊆ REPLICATED at
  `:32-36`, terminal REFUTED at `:38-45`, `rung_above` / 
...[truncated 9113 chars]