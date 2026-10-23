# Binary asset provenance

Inventory of every binary document tracked in the repository
(`git ls-files "*.pdf"` plus the raster/vector companions), with origin
and licence status. Audit scope: D8 / GAP-1 P1-7 remainder. Assets are
recorded here, not removed.

## PDFs

| Path | Origin | Licence | Notes |
|---|---|---|---|
| `docs/diagrams/exports/authority_trust_boundary.pdf` | Generated export of `docs/diagrams/authority_trust_boundary.html` (hand-authored project figure; headless-Chrome print-to-pdf) | Apache-2.0 (project) | Derived export; the HTML is the source of truth and carries its own provenance manifest. Diagram methodology referenced from `cathrynlavery/diagram-design` v2.4 @ `09df49d8` (MIT), ideas only, no code adopted. |
| `docs/diagrams/exports/digest_fold_adversarial.pdf` | Generated export of `docs/diagrams/digest_fold_adversarial.html` | Apache-2.0 (project) | Same derivation and methodology note. |
| `docs/diagrams/exports/horizon_cliff_late_handler.pdf` | Generated export of `docs/diagrams/horizon_cliff_late_handler.html` | Apache-2.0 (project) | Same derivation and methodology note. |
| `docs/diagrams/exports/ladder_refuted_drivers.pdf` | Generated export of `docs/diagrams/ladder_refuted_drivers.html` | Apache-2.0 (project) | Same derivation and methodology note. |
| `docs/diagrams/exports/one_verdict_gate_adversarial.pdf` | Generated export of `docs/diagrams/one_verdict_gate_adversarial.html` | Apache-2.0 (project) | Same derivation and methodology note. |
| `docs/diagrams/exports/provider_search_fetch_recovery.pdf` | Generated export of `docs/diagrams/provider_search_fetch_recovery.html` | Apache-2.0 (project) | Same derivation and methodology note. |
| `docs/diagrams/exports/redteam_reconciliation.pdf` | Generated export of `docs/diagrams/redteam_reconciliation.html` | Apache-2.0 (project) | Same derivation and methodology note. |
| `docs/diagrams/exports/research_os_loop.pdf` | Generated export of `docs/diagrams/research_os_loop.html` | Apache-2.0 (project) | Same derivation and methodology note. |
| `tests/fixtures/s1_docling/papers/2305.10601v2.pdf` | arXiv 2305.10601v2, vendored verbatim | CC BY 4.0 | Attribution, title, authors, and source: `tests/fixtures/s1_docling/ATTRIBUTION.md`. SHA-256 pinned in `MANIFEST.json`. |
| `tests/fixtures/s1_docling/papers/2506.05109v1.pdf` | arXiv 2506.05109v1, vendored verbatim | CC BY 4.0 | Same attribution record; SHA-256 pinned in `MANIFEST.json`. |
| `tests/fixtures/s1_docling/papers/2603.24639v2.pdf` | arXiv 2603.24639v2, vendored verbatim | CC BY 4.0 | Same attribution record; SHA-256 pinned in `MANIFEST.json`. |

## Related binary assets

These are not PDFs but share the origin of the exports above.

| Path | Origin | Licence |
|---|---|---|
| `docs/diagrams/exports/*.png` (8 files) | Raster exports of the corresponding `docs/diagrams/*.html` figures | Apache-2.0 (project) |
| `docs/diagrams/mermaid/research_os_loop_mermaid.svg` | Mermaid auto-layout render of the hand-authored `research_os_loop.mmd` | Apache-2.0 (project) |
| `docs/diagrams/mermaid/research_os_loop_mermaid.png` | Raster of the Mermaid SVG | Apache-2.0 (project) |

## Findings

- All 11 tracked PDFs have recorded provenance and a licence compatible
  with redistribution in this Apache-2.0 repository.
- No unlicensed PDF or orphaned binary document was found.
- No asset was deleted or modified by this audit.
