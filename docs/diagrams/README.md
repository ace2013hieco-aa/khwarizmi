# Hermes diagrams — architecture documentation & adversarial review

Every figure here is a **projection**, never authoritative state. Authority order: executable behavior / persisted state → ratified architecture / IDRs → tests → diagrams. If a figure conflicts with code, the code wins and the figure is wrong. Full discipline: `hermes_diagram_design_skill.md`; provenance of the external methodology: `hermes_diagram_design_integration.md`.

All figures follow the harvested **semantic-pattern → visual-type** routing (cathrynlavery/diagram-design v2.4 @ `09df49d8`, MIT — methodology only, no runtime dependency). Every figure carries its own provenance manifest (commit, files inspected, docs, tests, node status) and is verified against Hermes HEAD `ac770f7`.

| Figure | Semantic pattern → type | Question it answers | Verified at |
|---|---|---|---|
| [authority_trust_boundary.html](authority_trust_boundary.html) | Secure paved road → Architecture | Who may mutate what? | `ac770f7` |
| [one_verdict_gate_adversarial.html](one_verdict_gate_adversarial.html) | Paired policy-evaluation traces → Flowchart | Why do the two verdicts diverge, and what is refused? | `ac770f7` |
| [research_os_loop.html](research_os_loop.html) | Reinforcing loop → Loop | How does the Research OS feed itself? | `ac770f7` |
| [provider_search_fetch_recovery.html](provider_search_fetch_recovery.html) | Unstructured input → structured artifact + recovery → Data flow / Flowchart | How does provider content become artifacts, and what happens after a crash? | `ac770f7` |
| [horizon_cliff_late_handler.html](horizon_cliff_late_handler.html) | Sequential recovery with stale-write rejection → Flowchart | What happens to a handler that outlives the heartbeat horizon? | `ac770f7` |
| [ladder_refuted_drivers.html](ladder_refuted_drivers.html) | State transition with guards + attack gate funnel → State machine / Flowchart | What can and cannot reach REFUTED (the 29-attack map)? | `ac770f7` |
| [redteam_reconciliation.html](redteam_reconciliation.html) | Adversarial policy evaluation → Flowchart (attack lanes) | Where is each of the five red-team attacks stopped? | `203e2c2` |
| [digest_fold_adversarial.html](digest_fold_adversarial.html) | Policy evaluation under injected corruption → Flowchart (attack lanes) | Where is each digest-fold injection stopped? | `156b7ee` |

## Exports (PNG @1, PDF)

Rendered from the HTML (the HTML is the source of truth — PNG/PDF are derived exports, per the harvested output model). All exports re-verify at the manifest HEAD; re-export with the same command when a figure changes:

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless --disable-gpu   --screenshot=exports/<name>.png --window-size=1200,1400 file:///…/<name>.html   # ladder: 1200,1600
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless --disable-gpu   --print-to-pdf=exports/<name>.pdf file:///…/<name>.html
```

| Figure | PNG | PDF |
|---|---|---|
| authority_trust_boundary | [png](exports/authority_trust_boundary.png) | [pdf](exports/authority_trust_boundary.pdf) |
| one_verdict_gate_adversarial | [png](exports/one_verdict_gate_adversarial.png) | [pdf](exports/one_verdict_gate_adversarial.pdf) |
| research_os_loop | [png](exports/research_os_loop.png) | [pdf](exports/research_os_loop.pdf) |
| provider_search_fetch_recovery | [png](exports/provider_search_fetch_recovery.png) | [pdf](exports/provider_search_fetch_recovery.pdf) |
| horizon_cliff_late_handler | [png](exports/horizon_cliff_late_handler.png) | [pdf](exports/horizon_cliff_late_handler.pdf) |
| ladder_refuted_drivers | [png](exports/ladder_refuted_drivers.png) | [pdf](exports/ladder_refuted_drivers.pdf) |
| redteam_reconciliation | [png](exports/redteam_reconciliation.png) | [pdf](exports/redteam_reconciliation.pdf) |
| digest_fold_adversarial | [png](exports/digest_fold_adversarial.png) | [pdf](exports/digest_fold_adversarial.pdf) |

## Modes covered

- **Architecture mode** — authority_trust_boundary.html (every node carries file/module/authority/write capability in the manifest).
- **Adversarial review mode** — one_verdict_gate_adversarial.html (paired traces + refused paths: wrong token, tamper, crash rollback).
- **Research OS mode** — research_os_loop.html (8 stations + exactly one hub; all IMPLEMENTED; no second lifecycle model).
- **Provider / step-6 visualization** — provider_search_fetch_recovery.html (search/fetch pipelines, hazard boundary, retraction event, recovery decision).

## Mermaid interchange + render-path comparison

`mermaid/` holds a Mermaid source of the Research OS loop (`research_os_loop.mmd`), the skill's extractor IR digest, and a mermaid-cli render — an independent machine confirmation of the loop's structure (cycle + single hub) and a render-path comparison against the editorial figure. Per the harvested import flow the editorial HTML remains canonical; the `.mmd` is the portable interchange form (see `mermaid/README.md`).

## Regeneration rule

A figure is valid only against the HEAD named in its manifest. When the reviewed surface changes (controller, gateway, providers, ladder), re-verify the affected figure against the new HEAD and update the manifest — the same discipline as the Ix refresh. Diagrams are hand-authored HTML; nothing in `src/hermes` reads them.
