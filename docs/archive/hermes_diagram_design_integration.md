# Hermes × diagram-design — Integration & Provenance Record

**Date:** 2026-08-15
**Disposition:** ENGINEERING / DOCUMENTATION TOOL — **methodology harvested, zero source code adopted, no runtime dependency, no new Hermes subsystem.**

---

## 1. Source provenance (inspected live, not from the README)

| Item | Value |
|---|---|
| Repository | `https://github.com/cathrynlavery/diagram-design` |
| Source commit (shallow clone inspected) | `09df49d8d1a1c7fb2efdfcdc7a2a0713534350a6` |
| Skill version | `2.4` (SKILL.md front matter: `version: "2.4"`) |
| License | MIT (Copyright (c) 2025 Cathryn Lavery); `THIRD_PARTY_LICENSES.md` present |
| Diagram types | 27 visual types |
| Output model | static HTML with inline SVG (default), SVG/PNG derived from HTML |
| Motion | optional (`reveal`/`step`/`loop`), never changes static meaning |
| Redraw support | draw.io / Mermaid import (extractors: `skills/diagram-design/scripts/drawio_extract.py`, `mermaid_extract.py`, `self_check.py`) |
| Clients | Claude Code, Codex, Pi (marketplace + `npx skills add`) |

## 2. Files examined

- `skills/diagram-design/SKILL.md` (philosophy, 27-type selection table, connector rules, taste gate)
- `skills/diagram-design/references/semantic-patterns.md` (pattern routing table + per-pattern primitives, budgets, anti-patterns, static fallbacks)
- `skills/diagram-design/references/type-architecture.md` (zones, orthogonal connectors, bridge/hop, port selection)
- `skills/diagram-design/references/type-loop.md` (parametric loop: 5–8 stations + exactly one hub, deterministic geometry)
- `skills/diagram-design/references/output-spec.md` (format/size/detail/audience dials)
- `skills/diagram-design/references/export.md`, `style-guide.md`, `onboarding.md`, `profiles.md` (sampled)
- `docs/adr/0002-semantic-patterns-do-not-expand-the-taxonomy.md` (pattern discipline)
- `commands/*.md`, `prompts/*.md`, `scripts/*.py` (inspected; **not adopted**)

## 3. What was harvested

**Methodology only.** The following concepts were re-expressed as Hermes governance (`hermes_diagram_design_skill.md`):

1. **Semantic pattern → visual type routing** (the core idea): decide the reader's semantic question first (authority boundary, policy evaluation, recovery, provenance, loop), then the visual type. Hermes-specific routing table included.
2. **Diagrams are projections, not state** — the authority hierarchy (code/state > ratified architecture > tests > diagrams) and the "diagram is wrong, fix the diagram" rule.
3. **The four Hermes modes**: architecture, authority/trust-boundary, adversarial review, Research OS.
4. **Output model**: standalone static HTML with inline SVG; four dials; motion optional.
5. **Design rules**: density 4/10, ≤9 primary nodes, 1–2 focal nodes, grayscale-safe semantics (line style + stop symbols + labels, never color alone), mandatory orthogonal connectors, zone grouping, bridge-the-less-important-arrow.
6. **Anti-pattern catalog** (harvested + Hermes-specific: no second scheduler, no diagram authority, no drawing unverified components).

**Explicitly NOT harvested:** no code from `scripts/` or `commands/`; no `npx`/marketplace packaging; no style-guide tokens; no runtime dependency in `pyproject.toml`; nothing imported by `src/hermes`. The skill is a review-time workflow, not a production path.

## 4. Hermes boundary discipline

- No `DiagramService` / `DiagramScheduler` / `DiagramAuthority` / `DiagramGraphDatabase` / `DiagramRepository` was created.
- No diagram file is read by Hermes at runtime; no new gate, scheduler, or evidence path.
- Every diagram in `docs/diagrams/` carries a provenance manifest and marks each node's status (IMPLEMENTED / DESIGNED / DEFERRED / UNVERIFIED).
- If a diagram conflicts with code or a ratified IDR, the code wins and the diagram is corrected — the conflict itself is recorded as a finding.

## 5. Example artifacts produced (docs/diagrams/)

| File | Semantic pattern → type | Purpose |
|---|---|---|
| `authority_trust_boundary.html` | Secure paved road → Architecture | Who may mutate what: Agent → Intent → Gateway → Repository → State; forbidden bypass stopped |
| `one_verdict_gate_adversarial.html` | Paired policy-evaluation traces → Flowchart | APPROVED vs REJECTED verdict traces, crash rollback, tamper refusal |
| `research_os_loop.html` | Reinforcing loop → Loop | ResearchProgram → … → Q-02 → dispatch, hub = task graph/journal |
| `provider_search_fetch_recovery.html` | Unstructured input → structured artifact + recovery → Data flow / Flowchart | SOURCE_SEARCH / SOURCE_FETCH through hazards to artifacts; crash recovery |
| `README.md` | — | Index + per-diagram provenance manifests |

Each HTML is self-contained (inline SVG + CSS), static, grayscale-safe, and cross-checked against the Hermes code at HEAD `ac770f7` (see the manifest in each file).

## 6. Verification status

- Hermes suite unaffected (no runtime change): the existing 1321 tests + pyright 0 + ruff clean remain the gate.
- Every node in the example diagrams was grep-verified against `src/hermes` at `ac770f7`; the manifest names the files/tests.
- External repo inspected at `09df49d8`; no dependency introduced, nothing vendored.
