# MERGE-LOG-LICENSE — removal + pin-bump integration (S4 triangle closed)

- Branch `merge/license` off `origin/main @ 8b81c080f67427453e907f62f8328dcdad693ccb`, LOCAL-ONLY.
  D9 LAPSED — merge + verify ONLY. **STOP BEFORE PUSH. No push under any circumstance.**
- Base drift check: `git diff d106874..origin/main --stat` over every overlapping path
  (`pyproject.toml`, `uv.lock`, provider, S1 test, recorder, fixtures, LICENSE/NOTICE) is **empty**,
  so all three lines apply patch-exactly onto the base.

## Lineage (all carried patch-exact; resolutions listed below, nothing else)

| line | commit | subject | disposition |
|---|---|---|---|
| bump | `30fb494` | fix(pin): docling 2.131.0 → 2.132.0 + S1 fixture-diff migration | carried fully (pin, lockfile, provider constant, test pins, 4-paper re-records) |
| removal | `4ac805d` | chore(licensing): drop the arXiv perpetual-licence S1 fixture, attribute the CC BY 4.0 set | carried fully (PDF+JSON+MANIFEST-entry deletions, ATTRIBUTION.md, recorder narrowing, docstring trims) |
| license | `8fd941f` | chore(licensing): relicense to Apache-2.0 + ship LICENSE | rode along — overlap check: `pyproject.toml` hunks disjoint (license/SPDX fields vs docling pin), no semantic overlap; `LICENSE` is a new file; NOTICE and the fixture attribution untouched by this line |

Method: `cherry-pick -n` in order bump → license → removal (each applied cleanly except the
two predicted conflicts below). No `src/` change beyond the two carried lines' hunks
(provider docstring trim + pin constant); no behavior adaptation.

## Collision resolution — REMOVAL WINS (predicted, 2 spots, deletions only)

`2510.02557v1.json` was re-recorded by the bump and deleted by the removal.
Legal exposure outranks fixture freshness: the paper must not exist in the tree in any form.

1. `tests/fixtures/s1_docling/2510.02557v1.json`: modify/delete conflict → resolved with
   `git rm` (removal wins; the bump's re-record of this paper is discarded).
2. `tests/fixtures/s1_docling/MANIFEST.json`: content conflict → resolved by deleting the bump's
   re-recorded 2510 entry block and keeping the bump's new 2.132.0 digests for the 3 kept papers.
   All other hunks (provider, S1 test, `pyproject.toml`, recorder) auto-merged — verified disjoint below.

## 2510-absence proof (merged tree)

- Filename: `Get-ChildItem -Recurse -Include *2510*` → **empty** (no PDF, JSON, or any other file).
- Content hashes: `git grep` for the PDF SHA-256
  (`0986ffe4…6d6d781`) and the re-recorded payload prefix (`57bdcbcd…`) → **empty**.
- Extraction prose: `git grep` for three long verbatim quotes from the removed extraction
  ("modeling self-interested behavior", "conditioned policy optimization", "reduce skills atrophy") → **empty**.
- Classified `2510` mentions (not remnants): `ATTRIBUTION.md:27` prohibition record (carried line);
  `scripts/s1_docling_record.py:40` do-not-revendor comment (carried line); `audits/AUDIT-H2-REDTEAM.md:96`
  pre-existing audit table row (on base, untouched by all lines — history rewrite out of scope per removal);
  `2603.24639v2.json:2227` float `331.52510540000003` (substring coincidence in kept-paper coordinates);
  `docs/diagrams/exports/one_verdict_gate_adversarial.pdf` xref offsets (`0000025105`, PDF object
  positions, not content — verified by byte inspection); `uv.lock` wheel-hash substrings
  (cryptography/pandas, pre-existing). Any byte remnant would have failed the merge — none found.

## S1 battery — green on 3 papers with the new pin

`pytest tests/test_s1_docling_provider.py tests/test_fetch_m1_docling_controller_wiring.py` →
**35 passed** (live legs executed, not skipped). Fixture records carry `version 2.132.0` on all
3 kept papers with matching digests; the bump's fixture-diff evidence (3 payload-identical papers +
1 content-preserving block reorder) stands as recorded in the bump commit.

## Gates (worktree `.venv`, docling 2.132.0, `PYTHONPATH=<worktree>/src`)

- Full suite: `scripts/run_tests.py -q` → **exit 0** (4357 collected; exactly 8 fewer than the
  4-paper tree — the removed paper's 8 parametrized tests).
- `uvx ruff check src tests` → **clean**.
- `uvx pyright src` → **0 errors**. `uvx pyright --pythonpath <abs worktree venv> --project
  pyrightconfig.tests.json` → **0 errors**, 1 warning (`test_research_program.py:144`
  `reportSelfClsParameterName` — pre-existing, file untouched by this merge).
- Audit verdict: `uv audit` → **1 finding** (was 10): all 9 docling/docling-slim rows gone
  (2.132.0 reports `vulnerabilities: []`); only `GHSA-8mgp-746c-j5xp` (nltk, no fix, NO-reachability,
  ACCEPT-RISK) remains — explicitly out of scope, untouched.

## S4 closure statement

License closure verified across the pinned set, not assumed: docling + docling-slim 2.132.0 both
`license_expression: MIT` (unchanged), neither yanked; `uv.lock` holds 179 packages before and after
with zero added/removed and all other pins identical; the slim `standard` extra dependency set is
unchanged. S4 conditions C1–C6 concern untouched components. The pin is an S4-audited artifact,
so an S4 delta re-audit of 2.132.0 stays a follow-up — this merge claims closure of the *license
facts*, never of the re-audit.

STOP BEFORE PUSH — end of log.
