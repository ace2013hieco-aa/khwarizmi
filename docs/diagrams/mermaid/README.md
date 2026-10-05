# Mermaid redraw of the Research OS loop — render-path comparison

Source of truth: **`research_os_loop.mmd`** is a portable interchange source of the loop (same 9 concepts as `../research_os_loop.html`). Per the harvested import flow (`cathrynlavery/diagram-design` v2.4 — "redraw, never convert"), the editorial figure in `../research_os_loop.html` is the redraw: it keeps the *content* (nodes, edges, cycle, hub) and discards Mermaid's computed layout. The editorial HTML remains the canonical figure; this directory exists to compare render paths.

## Files

| File | What | From |
|---|---|---|
| `research_os_loop.mmd` | Mermaid flowchart source (9 nodes, 16 labeled edges, LR) | hand-authored |
| `ir_digest.json` | Extractor IR digest — `mermaid_extract.py --json` (skill script, run untrusted-data discipline) | extractor |
| `research_os_loop_mermaid.svg` | Mermaid's own dagre auto-layout (`mmdc`, mermaid-cli + installed Chrome via puppeteer-config) | mermaid-cli |
| `research_os_loop_mermaid.png` | raster of the Mermaid SVG (headless Chrome) | Chrome |
| `puppeteer-config.json` | mermaid-cli → local Chrome (no Chromium download) | local |

## Extractor findings (independent confirmation)

The IR digest — computed by the skill's extractor, not by Hermes — independently confirms the semantic structure the editorial Loop figure encodes:

- `nodes_total: 9` (8 stations + 1 hub), `edges_total: 16` (8 ring + 8 spokes), all labeled, zero dangling;
- `has_cycle: true` — the closing feedback edge (Dispatch → ResearchProgram) is real;
- hub detection: **TG** (Task graph + event journal) is the highest-degree node — the Loop type's "exactly one hub" requirement, machine-verified.

## Render-path comparison

| Aspect | Mermaid auto-layout (`_mermaid.svg`) | Editorial figure (`../research_os_loop.html`) |
|---|---|---|
| Layout | dagre LR — long horizontal chain, ring structure implied but not drawn | radial ring + hub, ring order = derivation order |
| Connectors | straight/curved auto-routed | orthogonal, grayscale-safe styles |
| Semantics | dashed spokes lost in default theme (only line style differs) | dashed spokes + explicit `writes` labels + legend |
| Focal emphasis | none (theme default) | Q-02 focal node |
| Density | 9 nodes / 16 edges (same content) | same content, zoned |
| Authority | renderer output only | projection with provenance manifest |

**Verdict per the skill:** the redraw wins — same content, editorial layout, semantic encoding that survives grayscale, and a provenance manifest. The Mermaid source remains useful as the interchange/portable form (issues, external tools, quick edits); any change to the loop must land in BOTH the `.mmd` (source) and the HTML (canonical figure), then re-run the comparison.

## Re-run commands

```bash
python <skill>/scripts/mermaid_extract.py research_os_loop.mmd --json --out ir_digest.json
npx -y @mermaid-js/mermaid-cli -i research_os_loop.mmd -o research_os_loop_mermaid.svg -p puppeteer-config.json
chrome --headless --screenshot=research_os_loop_mermaid.png file:///…/research_os_loop_mermaid.svg
```
