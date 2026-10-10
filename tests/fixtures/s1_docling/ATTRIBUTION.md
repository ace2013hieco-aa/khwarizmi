# S1 docling fixture attribution

The three PDFs under `papers/` are redistributed **verbatim** — byte-identical to the
arXiv downloads, pinned by the per-paper SHA-256 in `MANIFEST.json`. Each is licensed
**CC BY 4.0**, which permits redistribution in any medium provided attribution is
given. Attribution for each paper follows (title, authors, source, licence).

| arXiv ID | Title | Authors | Licence | Source |
|---|---|---|---|---|
| 2305.10601v2 | Tree of Thoughts: Deliberate Problem Solving with Large Language Models | Shunyu Yao, Dian Yu, Jeffrey Zhao, Izhak Shafran, Thomas L. Griffiths, Yuan Cao, Karthik Narasimhan | CC BY 4.0 | https://arxiv.org/abs/2305.10601v2 · https://creativecommons.org/licenses/by/4.0/ |
| 2506.05109v1 | Truly Self-Improving Agents Require Intrinsic Metacognitive Learning | Tennison Liu, Mihaela van der Schaar | CC BY 4.0 | https://arxiv.org/abs/2506.05109v1 · https://creativecommons.org/licenses/by/4.0/ |
| 2603.24639v2 | Experiential Reflective Learning for Self-Improving LLM Agents | Marc-Antoine Allard, Arnaud Teinturier, Victor Xing, Gautier Viaud | CC BY 4.0 | https://arxiv.org/abs/2603.24639v2 · https://creativecommons.org/licenses/by/4.0/ |

Licence facts were read from each paper's own metadata (`/License` plus the XMP
`dc:rights` property) and cross-checked against the versioned arXiv abstract page's
licence link, on 2026-10-10. Where a paper carries no licence metadata of its own
(2305.10601v2, 2506.05109v1) the abstract page link is the sole source.

**Changes made:** none to the PDFs. The sibling `<arXiv-id>.json` fixtures are derived
works — a docling structural extraction of each paper plus a handful of short verbatim
quotations used as claim surrogates (4–5 quotes, 454–826 characters per paper, selected
by the deterministic rules in `scripts/s1_docling_record.py`). Quotations are reproduced
verbatim and unaltered; page and bbox are recorded alongside each one.

## Not included

`2510.02557v1.pdf` — *Orchestrating Human-AI Teams: The Manager Agent as a Unifying
Research Challenge* (Charlie Masters, Advaith Vellanki, Jiangbo Shangguan, Bart Kultys,
Jonathan Gilmore, Alastair Moore, Stefano V. Albrecht) — is **not** redistributed here.

Its licence is the **arXiv.org perpetual, non-exclusive licence 1.0**
(http://arxiv.org/licenses/nonexclusive-distrib/1.0/, as recorded both in the PDF's
`/License` metadata and on its abstract page). Per arXiv's own licence page that licence
"gives limited rights to arXiv to distribute the article, and also limits re-use of any
type from other entities or individuals"
(https://info.arxiv.org/help/license/index.html) — so the paper, and the extraction
fixture derived from its text, cannot be carried in this (or any public) repository.
Both files were removed on 2026-10-10; its `MANIFEST.json` entry was removed with them,
and `scripts/s1_docling_record.py` no longer lists it as part of the vendored capture
set. History still holds the bytes — removal here keeps the current tree clean, and a
history rewrite is a separate decision.
