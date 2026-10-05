# ResearchSourceProvider Step 6 — Ix Structural Comparison (2026-08-14)

**§26 gate:** the post-implementation Ix comparison — pre-step-6 graph vs
post-step-6 graph, watching for new write paths, unexpected dependencies,
cycles, new execution surfaces, handler → repository flows, and
controller → provider → repository flows.

## Baselines

| Metric | Pre-step-6 (14:57–15:03, HEAD `d82228a`-era tree) | Post-step-6 (HEAD `44cced5`) |
|---|---|---|
| Files mapped | 106 | **110** (+4) |
| Regions | 30 | 31 |
| Systems | 11 | 10 |
| Modules | 19 | 21 |
| Smell claims | 146 (Orphan 112 / God 33 / Weak 1) | **153** (Orphan 116 / God 36 / Weak 1) |
| God module | `repositories.py` fan_in=20 fan_out=57 | `repositories.py` fan_in=22 fan_out=59 |

The +4 files are exactly the step-6 package: `source_templates.py`,
`source_handlers.py`, `source_outcomes.py`, `test_provider_orchestration.py`.

## Smell delta — all documented connection-graph artifact

The +7 smell claims (Orphan +4, God +3) are ALL the documented `chunks=0`
graph-ingestion artifact (the same class that produced the 112-file orphan
baseline — test files and files whose chunk-clustering didn't attach; the
earlier investigation ruling, `docs/ix/` 2026-08-14). Evidence the claims are
not real orphans: `source_outcomes.py` has **fan_in=5 fan_out=25** and
`source_handlers.py` **fan_in=2 fan_out=47** — they are connected in the call
graph; `test_provider_orchestration.py` fan_out=63 (the widest test — it
exercises the whole path, expected). None of the step-6 files is a real
unreferenced module.

## The four watch-items

1. **New write paths — NONE.** The only SQL statement in the new step-6 code
   is `INSERT OR IGNORE INTO provenance_edges` (edge idempotency, inside the
   commit transaction, `source_outcomes.py:555`). Every artifact row goes
   through the governed `ArtifactRepository.record` / `ArtifactStore.write`;
   zero `UPDATE`/`DELETE`/`REPLACE`; handlers contain **zero SQL** (grep-verified
   — handlers only call the `SourceRepos` boundary).
2. **Cycles — NONE.** Import-time acyclicity verified against the shipped
   interpreter: `controller → source_handlers → source_outcomes` and
   `repositories → source_outcomes` with the documented lazy import
   (`source_outcomes.__init__` resolves repository names at method time — the
   seam that breaks the back-edge). No import cycle; 874 passing tests over
   the full wiring corroborate.
3. **Handler → repository flow — single boundary.** `SourceTaskExecutionContext.repos`
   exposes exactly `record` / `dereference_ref` / `load_search_results`
   (fixture-asserted: no `conn` attribute, `repos._conn IS fenced`). No
   handler reaches the gateway, raw connection, task table, or evidence.
4. **Controller → provider → repository flow — one direction.** The controller
   dispatches the typed bundle; the handler calls the shipped read-only
   drivers (`walk`/`combine`/`fetch_batch`), then the ONE write method. No
   new execution surface, no second scheduler loop.

## God-module note

`repositories.py` grew fan_in 20→22 / fan_out 57→59 (the source-outcome
resolver import + the source slice's record methods). This is within the
documented single-write-path ruling (the investigation that preceded step 6:
the concentration is justified by the one-mutation-path discipline, and
`source_outcomes.py` IS the documented seam the source recording landed in —
the god-module cluster split remains a post-step-6 follow-up, unchanged).

## Rank delta

Baseline top dependents: `frozen_clock`(16), `Intent`(14), `Path`(13).
Post-step-6 top dependents add the provider-slice helpers
(`parse_query_hints`, `redact_params`, `compute_content_hash` …) — the
expected consequence of steps 1–6 landing the provider machinery, not a new
hot spot in the authority plane. The hottest MODULE remains `repositories.py`
(above).

## Verdict

**CLEAN — no structural regression from step 6.** Zero new write paths, zero
cycles, single handler→repository write boundary, one-directional
controller→provider→repository flow, and the only smell deltas are the
documented connection-graph artifact. The god-module concentration follows
the pre-existing documented ruling. This satisfies the §26 structural gate
for step 6; correctness certification remains with the independent adversarial
code audit + the external closure gate (both separate).

## Artifacts

- `docs/ix/map_20260814_step6.txt` — fresh `ix map .`
- `docs/ix/smells_20260814_step6.txt` — fresh `ix smells` (153 claims)
- `docs/ix/rank_dependents_modules_20260814_step6.txt` / `rank_importers_modules_20260814_step6.txt` — fresh `ix rank`
- archived alongside the baseline (`docs/ix/map_20260814.txt`, `smells_20260814.txt`, rank baselines) and mirrored to `~/.ix/reports/`
