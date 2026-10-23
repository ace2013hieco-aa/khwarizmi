# MERGE-LOG-D8-HYGIENE — minimal honesty: path scrub, binary-asset provenance, NOTICE trademark, CLA/DCO posture (GAP-1 P1-7 / ruling D8-A)

## Provenance

| Item | Value |
| --- | --- |
| Task | D8-HYGIENE (merge gate; local FF — the push is bundled with the wave-3a fleet under one human D9 pin) |
| Base (`main` before) | `332614c` (wave-2 rulings record) |
| Slice | `slice/d8-hygiene@2c209f7`; **restacked** as `slice/d8-hygiene-restacked@41d1117` (4 cherry-picks; the slice carried no re-stamp — it adds no tests — so the count is unchanged at 4929; no rebase, no merge commit) |
| Landed tip (FF'd to) | `41d1117d74d1da26929991869f1109fd65856e84` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — bundled with the wave-3a fleet under one human D9 pin |

## Scope

```
CONTRIBUTING.md                             | 15 ++   (new: Apache-2.0 + DCO, no CLA)
NOTICE                                      |  4 +-   (trademark line; no registration claim)
docs/ASSET-PROVENANCE.md                    | 39 ++   (new: 11 PDFs + 10 companions)
scripts/adversarial_probe_s5.py             |  3 +-   (sys.path literal -> repo-relative)
scripts/run_tests.py                        |  2 +-   (venv path in docstring -> elided)
scripts/s1_docling_record.py                |  2 +-   (--source-root example -> placeholder)
tests/fixtures/s1_docling/{3 records,MANIFEST}.json | 10 +- (source_path_at_capture -> relative)
```

## What was certified

- **D8-A path scrub (live files only).** Four absolute developer paths left
  the runnable surface: the hardcoded `sys.path` insert in
  `scripts/adversarial_probe_s5.py` (now `Path(__file__).resolve().parents[1] /
  "src"`), a venv path in `scripts/run_tests.py`'s docstring, the
  `--source-root` example in `scripts/s1_docling_record.py`, and the
  `source_path_at_capture` values in the three s1-docling capture records plus
  `MANIFEST.json` (now `papers/<name>.pdf`; the PDF SHA-256 pins are untouched).
- **Residual absolute paths (justified, not scrubbed).** 85 tracked files still
  contain a developer path. Every one is a **dated evidence record** —
  `docs/MERGE-LOG-*.md`, `docs/MERGE-AUDIT-*.md`, `docs/LOOP-4-*.md`,
  `docs/CLEANUP-A3.md`, `audits/AUDIT-H2-REDTEAM.md` — plus two research-method
  notes in `hermes_research_architecture_v6.md` recording where a corpus lived.
  These record what was actually run on which machine; rewriting them would
  falsify the record (the same policy that keeps `docs/archive/**` untouched).
  **Zero hits remain in `src/`, `tests/`, `scripts/`, `.github/`, or any
  `*.toml`/`*.yml`/`*.cfg`/`*.ini`.**
- **D8-A binary-asset provenance.** `docs/ASSET-PROVENANCE.md` inventories all
  **11 tracked PDFs** — 8 generated diagram exports (Apache-2.0, HTML is the
  source of truth, diagram methodology credited MIT ideas-only) and 3 vendored
  arXiv fixtures (CC BY 4.0, attribution in
  `tests/fixtures/s1_docling/ATTRIBUTION.md`, SHA-256 pinned in `MANIFEST.json`)
  — plus the 8 export PNGs and the Mermaid SVG/PNG pair. Count verified against
  `git ls-files "*.pdf"` (11) and `docs/diagrams/exports/*.png` (8). **No asset
  deleted or modified.**
- **D8-A NOTICE.** One true, minimal line: the project name is a trademark of
  the project owner, no registration claimed. The Crawl4AI attribution is
  preserved byte-for-byte; only a trailing newline was added.
- **D8-A CLA/DCO posture.** `CONTRIBUTING.md` records Apache-2.0 inbound =
  outbound, a DCO 1.1 `Signed-off-by` trailer requirement, and **no separate
  CLA**; third-party material keeps its own licence via `NOTICE` and
  `docs/ASSET-PROVENANCE.md`.

## B4

No governed document was edited (`CONTRIBUTING.md` and
`docs/ASSET-PROVENANCE.md` are new ungoverned files; `NOTICE` is not in the
corpus). **B4 stays 24 and byte-identical — no regeneration.**

## Gates (raw, at restacked tip `41d1117`)

- `stamp_suite_count.py --check`: `OK: docs\SUITE-COUNT.md collected=4929 matches the live collect`
- `run_tests.py tests/test_b4_ref_graphs.py`: **24 passed**
- `check_census.py`: **PASS** — 124 transaction-control calls / 28 owners
  (persistence 19, gateway 5, Controller 4) / 1 rollback-only / 15 imports / 0
  outside certified layers
- `ruff check src tests scripts`: `All checks passed!`
- Full suite: batch-end gate at the combined wave-3a tip (recorded in
  `docs/MERGE-LOG-WAVE-3A.md`), per the landing protocol.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit | **PASS** — 0 hits (word-boundary scan at the batch tip) |
| behavior change | **none** — docs, docstrings, path literals, and one JSON provenance field; no code path changes |
| census shift | **none** — 124 / 28 / 19 / 15 unchanged |
| B4 digests moved | **no** — no governed doc touched |
| asset deletion | **none** — inventory only |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies repository hygiene only: which paths are published, what
the binary assets are and under what licence, a trademark assertion that claims
no registration, and the contribution sign-off posture. It makes no validity,
reproducibility, or admissibility claim, and no statement about the licence of
anything not listed in `docs/ASSET-PROVENANCE.md`.

License: Apache-2.0 (LICENSE).
