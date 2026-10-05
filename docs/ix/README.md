# IX Report Archive — Hermes Research

Versioned snapshots of the global IX (System Intelligence) reports for this
repo, per the house convention ("archive the reports from every ix command").
The raw timestamped runs also live in `~/.ix/reports/` (the ix launcher writes
one file per command) with the per-scope smells-diff chain
(`~/.ix/reports/smells/latest_research_agent.json`); this directory pins the
notable runs to the repo so they version with the code.

Baseline: **2026-08-14** — map re-ingested (rev 36), 146 smell claims
(god_module=33, orphan_file=112, weak_component_member=1).
Refresh: **2026-08-15** — scoped analysis re-run at HEAD `dc84673`
(smells rev 56), 200 smell claims (god_module=48, orphan_file=151,
weak_component_member=1).
Re-refresh: **2026-08-15** — scoped analysis re-run at HEAD `f96a566`
(epistemic-architecture review, smells rev 62), 203 smell claims
(god_module=48 — unchanged, orphan_file=154 — the +3 are the new hostile
test files / governance docs referenced only via text links,
weak_component_member=1). Class rank stable: TaskRepository 115,
ProjectRepository 100, Controller 44 — no new authority nodes, no new
scheduler loops from the F1/F2/F3/F6/F7/F8/F9 operator-loop and ladder
hardening.
Re-refresh: **2026-09-19** — full IX command run at HEAD `2328399`
(map rev 89 → 132, smells rev 136), 269 smell rows
(god_module=71 / orphan_file=197 / weak_component_member=1); class rank
TaskRepository 198, ProjectRepository 174, Intent 168, Controller 75.
Rulings + per-command results: `full_run_20260919.md`.

## Reports

| File | Source command | Notes |
|---|---|---|
| `map_20260814.txt` | `ix map .` | system map after re-ingest (161 files changed since the previous ingest) |
| `map_20260815.txt` | `ix map .` | **raw ingest error** — the global-map patch commit hit an ArangoDB unique-constraint collision (409/1210, conflicting `_key`); the global map could not be re-archived. The scoped pipeline (smells/rank/doctor/subsystems below) computed fresh; see §Map-ingest backend issue |
| `subsystems_20260815.txt` | `ix subsystems --all-items` | current structural overview (133 files · 29 regions · 11 systems) — the working alternative to `ix map` while the backend issue is open |
| `smells_20260814.txt` | `ix smells` | 146 claims, grouped (God Module 33 / Weak Component 1 / Orphan File 112) |
| `smells_20260815.txt` | `ix smells` | **200 claims** (rev 56), grouped (God Module 48 / Weak Component 1 / Orphan File 151) |
| `smells_diff_20260814.txt` | `ix-smells-diff` | diff vs. the previous scoped snapshot (rev 36): +18 god_module, −2 orphan (gateway.py + research_sources.py resolved), repositories.py god_module 0.65 → 0.8 |
| `smells_diff_20260815.txt` | `ix-smells-diff` | diff rev 36 → rev 56: **+54 added / −1 removed** — see the 2026-08-15 rulings below |
| `rank_dependents_modules_20260814.txt` | `ix rank --by dependents --kind module` | most-depended-upon symbols (Intent, Path, NodeContract, compute_content_hash) |
| `rank_dependents_modules_20260815.txt` | `ix rank --by dependents --kind module` | fresh symbol ranking at HEAD `dc84673` |
| `rank_dependents_classes_20260814.txt` | `ix rank --by dependents --kind class` | TaskRepository (78), ProjectRepository (75), RequestSpec (35), EventRepository (26), WalkRequest (24), ResearchProgramRepository (22), NodeContract (22), NotFoundError (19), SearchResult / RedactionPolicy / ProviderHazardSpec (16), Controller (16) |
| `rank_dependents_classes_20260815.txt` | `ix rank --by dependents --kind class --top 20` | fresh class ranking — see the 2026-08-15 rank findings |
| `rank_importers_modules_20260814.txt` | `ix rank --by importers --kind module` | the import surface (typing/json/re/pytest + the core payload types) |
| `rank_importers_modules_20260815.txt` | `ix rank --by importers --kind module` | fresh import surface |
| `doctor_20260815.txt` | `ix doctor` | all checks passed (backend reachable, 188010 nodes, 482832 edges, no conflicts, schema v3) |
| `map_20260919.txt` | `ix map .` | rev 89 → 132 at HEAD `2328399` (3 stale files, 1.1s ingest, zero patch failures); 170 files · 41 regions |
| `subsystems_20260919.txt` | `ix subsystems --all-items` | post-map structural overview (pre-map capture: 170 files · 42 regions) |
| `smells_20260919.txt` | `ix smells` | **269 rows** at rev 136 (god_module=71 / orphan_file=197 / weak_component_member=1) |
| `smells_diff_20260919.txt` | manual smells-diff (bundled script failed — see `full_run_20260919.md` §Incidents) | rev 56 → rev 136; by-smell exact, added/removed undercount same-basename collisions |
| `rank_dependents_classes_20260919.txt` | `ix rank --by dependents --kind class --top 20` | TaskRepository 198 / ProjectRepository 174 / Intent 168 / Controller 75 / OperatorCredentialRepository 52 (new) |
| `rank_dependents_modules_20260919.txt` | `ix rank --by dependents --kind module` | post-map |
| `rank_importers_classes_20260919.txt` | `ix rank --by importers --kind class --top 20` | post-map |
| `rank_importers_modules_20260919.txt` | `ix rank --by importers --kind module` | post-map — metric degenerate (all counts 1), archived as-is, not cited |
| `doctor_20260919.txt` | `ix doctor` | all checks passed (global 249749 nodes / 124877 edges; scoped stats 10966 nodes / 35258 edges in `stats_20260919.txt`) |
| `full_run_20260919.md` | full-run manifest | every ix family: result, deltas, rulings, incidents, skipped commands |
| `step6_structural_comparison_20260814.md` | step-6 comparison run | step-6 slice structural comparison vs the pre-step-6 baseline |

## Investigation rulings (2026-08-14, retained)

1. **`repositories.py` god-module — justified concentration, bounded split still pending.** The ruling stands: the single-write-path architecture funnels every mutation through the one persistence authority, and the P7/source cluster shares only generic helpers. The 2026-08-14 action was "land step 6, then split the P7/source cluster into `persistence/repositories/claims.py` + `sources.py` in one mechanical commit." Step 6 has since landed (`source_outcomes.py`); the mechanical split remains an open, operator-owned refactor — NOT an Ix-mandated deletion and NOT urgent (no correctness defect).
2. **The 112 orphan_file claims — ZERO dead-code defects.** Classification still holds: the Markdown/TOML/YAML corpus is referenced only via text links the import/call graph does not model; the v3-era placeholder scaffolding (`agents/*`, `research/{evidence,gates,integrity_gates,provenance,reconcile,registration}.py`, `engineering/*`, `recovery/{heartbeat,leases}.py`, `security/boundaries.py`, `tools/{execution,models,reporting,sandbox}.py`, `vault/projection.py`) is intentional and kept.
3. **Rank findings — the load-bearing surface matches the architecture.**

## Investigation rulings (2026-08-15 refresh, at HEAD `dc84673`)

### 1. god_module 33 → 48: the +15 are the Q-05/Q-02/Q-04/step-6 modules and their test batteries — same justified-concentration pattern

The 2026-08-14 ruling (single-write-path authority) covers the production additions: `failure_classifications.py` (the Q-05 persistence slice — one repository + the pure digest), `source_handlers.py` + `source_outcomes.py` (step 6 task-side orchestration + one write boundary), `intents.py` (the mutation payload vocabulary), and `e2e_operator_loop.py` (a script). The remaining additions are **test files** (`test_controller_q02.py`, `test_controller_q04.py`, `test_q04_*` ×5, `test_q05_*` ×3, `test_provider_orchestration.py`, `test_program_obligations.py`) — large golden-fixture batteries, god-module-flagged by line count by design, not a structural smell. `test_artifacts.py` was removed from the claim set. **No new structural defect; no split action.**

### 2. orphan_file 112 → 151: the +39 are documentation and config, zero dead-code defects

Every added orphan is Markdown/TOML/JSON referenced only via text links — IDR-032…041, the `hermes_*.md` design/audit/review records (Q-02/Q-04/Q-05, surviving-ideas, ResearchSourceProvider step-6), `HERMES_RED_TEAM_AUDIT_20260815.md`, `pyrightconfig.json`/`pyrightconfig.tests.json`, `step6_closure_candidate_evidence_map.md`, `step6_structural_comparison_20260814.md`, and the Q-05 review records (`hermes_q05_independent_review.md`, `hermes_q05_q02_current_state_review.md`). The import/call graph has no edge kind for text links (the 2026-08-14 classification verbatim). **No orphan claim corresponds to accidentally-unreferenced live code.** The 2026-08-14 observation that `gateway.py` + `research_sources.py` resolved still holds; no production module regressed into the claim set.

### 3. Rank findings — the epistemic vocabulary is now load-bearing

- **TaskRepository (78 → 115) + ProjectRepository (75 → 100)** remain the most-depended-upon classes — the single-write-path authority is the hottest surface, as designed.
- **Controller 16 → 44** — the Q-02 dispatch policy, Q-04 cone/review surfaces, the Evidence-Ladder APPLY executor, and the operator-loop work made the ONE execution authority substantially more load-bearing. Consistent with design (no second scheduler appeared).
- **New top-tier classes from the surviving-ideas stages:** `FailureClassificationRepository` (49) — the Q-05 advisory store; `SourceOutcomeRepository` (38) — step 6; `FailureClass` (31) + `FalsificationRecord` (19) — the Q-05 taxonomy vocabulary; `ProgramRequirementSatisfactionRepository` (24) — the Q-02 satisfaction links. The epistemic vocabulary is structurally integrated, not bolted on.
- `Intent` remains the most-depended-upon symbol — the one-mutation-path contract, still confirmed.

## Map-ingest backend issue (open, environmental)

`ix map .` re-ingests fine (39s, resolves today's symbols — `ix search`/`ix locate` find `classifications_digest` / `FailureClassificationRepository`), but the **global-map patch commit fails** with `Error: Ingest committed nothing: all 19 patches failed to commit` — every file reports an ArangoDB 409/1210 unique-constraint violation on `_key` (`ix map . --verbose`). The scoped pipeline (`ix smells`, `ix-smells-diff`, `ix rank`, `ix doctor`, `ix subsystems`) builds its own fresh snapshots and is unaffected — the 2026-08-15 archives below are current. The global map archive could not be regenerated; `map_20260815.txt` records the raw error and `subsystems_20260815.txt` is the working structural overview. Likely fixable via `ix docker`/`ix reset` on the local index — **not run** (would reset the local ix store); revisit if the global map is needed.

## Re-run

```bash
ix map .                 # re-ingest after code changes (backend commit issue open — see above)
ix subsystems --all-items   # working structural overview while the map backend is broken
ix smells                # grouped report (archived to ~/.ix/reports/)
ix-smells-diff           # diff vs the last scoped snapshot (appends to the archive)
# NOTE 2026-09-19: ix-smells-diff fails on this machine (stale ix under Git
# Bash + update notice merged into JSON) and corrupted latest_*.json; the
# 20260919 diff was produced manually — see full_run_20260919.md §Incidents.
ix rank --by dependents --kind class --top 20
ix doctor
# copy the notable reports here per the convention
```
