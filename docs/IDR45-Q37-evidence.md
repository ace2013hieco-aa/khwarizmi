# IDR-045 Q3 / Q7 Evidence — Q-pass-narrow (read-only)

Branch: `idr-045/qpass-narrow` from `main@c2c8fa9`. No src/test/config change. This file is the sole write.

## Q3 — IntentApplied payload builders: direct examination

Claim to check (IDR-045 §4.5, §6 Q3): "5 IntentApplied payload builders" whose exact 4-key shape must be guarded by an "only when non-default" rule for D2 provenance fields.

Method: read `src/hermes/research/gateway.py:_append_audit_event` directly; search `src/` + `tests/` for dicts containing `"intent_kind"` and for any `set(payload)==` / `payload=={` exact-mapping assertion on an IntentApplied payload. No grep-pattern shortcut as proof.

### Builders (direct file:line)

- `src/hermes/research/gateway.py:4085-4090` — the sole IntentApplied/IntentRejected payload builder in `src/`:
  ```py
  payload = {
      "intent_kind": kind_label,
      "proposed_by": intent.proposed_by,
      "project_id": intent.project_id,
      "justification": intent.justification,
  }
  ```
  Called from `_append_audit_event:4068-4100`, which is the single audit writer (invoked at `gateway.py:4058`, `:4061`, `:4064`). No other `src/` dict builds an IntentApplied payload containing `intent_kind`.

- No other builder in `src/` or `tests/` constructs a dict with key `"intent_kind"` as a payload literal. `rg '"intent_kind"' src/ tests/` returns exactly 6 hits: 1 builder (`gateway.py:4086`) + 5 read/filter sites (`tests/test_gateway.py:462`, `:799`, `:815`, `:823`, `tests/test_walking_skeleton.py:205`). The audit-4 census (`reports/repo-state-audit-4-2026-09-29.md:804` `applied_pat = re.compile(r'"intent_kind"')`) counted the same pattern and reported "5 in tests" — direct reading shows those 5 are readers/filters, not builders.

Actual builder count: **1 in `src/`, 0 in `tests/`** (5 attributed builders do not exist as builders on direct inspection).

### Exact-mapping assertion?

Pattern `set(payload)=={...}` / `payload=={...intent_kind...}` over `tests/` returns no hit on an IntentApplied payload. The `set(payload)==` assertions that do exist cover unrelated payloads only:
- `tests/test_c1_slot_ref.py:286` — C1 slot compilation payload
- `tests/test_extraction_pipeline.py:141-148,154` — extraction payload
- `tests/test_s5_retraction.py:500`, `tests/test_s6a_retraction_ingestion.py:292` — retraction payloads
- `tests/test_cli.py:546,631` — `{"events"}`, `{"projects"}`

Confirmed: **no test asserts the IntentApplied payload as an exact 4-key mapping** (`reports/repo-state-audit-5-2026-09-29.md:547-548` reaches the same verdict with the same 8 `intent_kind` read hits; direct re-check at this commit reproduces it).

### "Only when non-default" holds?

There is no existing IntentApplied payload assertion to break, and the single builder at `gateway.py:4085-4090` is a plain dict literal. Adding D2 provenance keys (origin_kind, origin_ref, model_ref, run_id, prompt_template_version, charter_version) "only when non-default" keeps the default-constructed payload byte-identical (`justification` + 3 intent fields unchanged; missing keys treated as "origin unrecorded" by readers — `intents.py:167-174` shows Intent carries only 4 fields today, so the 4-key dict is the whole payload). Conditional insertion therefore satisfies IDR-045 §4.1 V2/V3 (default construction stays identical; pre-existing rows never backfilled).

## Q7 — Head vs sideways: does a B3C child become head?

### Current definition

- `src/hermes/persistence/repositories.py:1700-1706` `ResearchProgramRepository.current(project_id)` — `SELECT * FROM research_programs WHERE project_id=? ORDER BY version DESC LIMIT 1`
- `src/hermes/research/completion.py:104-114` `_current_program(conn, project_id)` — same query
- `src/hermes/research/controller.py:3524-3528` `_ladder_current_rung` and `:3661-3666` evidence-ladder write path — same pattern

All return max-version row. None filter on `parent_program_id` or `target_regime`.

### Parallel child version

`src/hermes/persistence/repositories.py:1600-1616` in `ResearchProgramRepository.record`:
- superseding program: `version = sup["version"]+1` (`:1598`)
- otherwise (no supersedes_ref): `SELECT MAX(version) AS v …` (`:1601-1604`); if head exists and `program.parent_program_id is None` refuse silent mutation (`:1605-1611`); then `# parallel-regime-test programs get the next version number (v=max+1)` (`:1612-1614`) and `version = (head["v"] or 0)+1 if parent_program_id else 1` (`:1616`).

Migration `src/hermes/persistence/migrations.py:1158-1185` (18→19) adds advisory columns `parent_program_id`, `parent_hypothesis_ref`, `target_regime` — no constraint, no index filtering, no change to `current()`.

### Verdict

**Yes — a B3C (ADR-041) parallel-regime-test child becomes head.** It is inserted at `version = max+1` and `current()` orders solely by `version DESC`. No `WHERE parent_program_id IS NULL` predicate exists in any of the three `current()` implementations above. Consequence is a "sideways" row masquerading as the chain head.

### Forced eligibility rule and consequences for the plan-once pass

The plan-once pass must choose one of three eligibility rules (mutually exclusive):

- **Replace-head**: `current()` row is the program to plan (whatever its `parent_program_id`). A B3C child replaces the primary chain head; the next `build_task_plan(current)` projects the child program's tasks, not the supersession chain's head. Consequence: admitting a B3C program silently re-targets plan admission; idempotence of the primary plan (`task_id` content-addressed from `program_id` at `src/hermes/research/task_plan.py:100-107`) is lost for the primary program; a second B3C emit would again steal head.

- **Run-alongside**: admit plans for every program version (`SELECT … ORDER BY version ASC` at `repositories.py:1711-1714` / `list_for_project`) or for every `research_programs` row with `parent_program_id IS NULL` ∪ all B3C rows, each as an independent DAG. Consequence: multiple active DAGs per project; the existing single-head assumption (`completion.py:278` `program = _current_program(…)`, controller `tick` single dispatch at `:589`) breaks; requires fan-out bookkeeping the IDR-045 D1 scope explicitly excludes.

- **Keyed-otherwise** (ADR-041-faithful): eligibility is keyed by `supersession chain head WHERE parent_program_id IS NULL` or by `MAX(version) WHERE parent_program_id IS NULL`, leaving B3C rows sideways (never head). Consequence: `current()` needs a filtered variant (or the pass queries `MAX(version) WHERE parent_program_id IS NULL` directly); plan-once stays idempotent on the primary chain; B3C children have no plan and never pollute `current()` — they remain advisory parallel experiments as ADR-041 intended. This is the only option consistent with the migration comment "they run alongside, not as replacements" (`repositories.py:1613`) without contradicting the live `current()` semantics.
