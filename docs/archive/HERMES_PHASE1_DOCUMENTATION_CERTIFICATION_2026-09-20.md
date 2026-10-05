# Hermes Phase 1 Documentation Certification — 2026-09-20

## 1. Baseline

`HEAD == origin/main == adab69d` at start (branch `main`, Phase 0
final). Tree: no tracked modifications (untracked only: pre-existing
`.freebuff/`, `IDEA.md`, external `or*.json`, plus the new Phase 1
files below). No production-code change in this phase by construction
(all edits are `.md` except `examples/first_run.py`, which imports
only the public CLI surface).

## 2. Documentation inventory (pre-Phase 1)

89 root `.md` (design gates/audits/reviews/remediations + v3/v4/v6 +
README), `docs/{archive,diagrams,idr,ix}`, no `AGENTS.md`, no
CONTRIBUTING, no `examples/`, no API reference, no docs index.
Install/operate/test documented in README (`:11-19`, `:185-231`);
status frozen pre-N9/P7; placeholder claims stale (`:46`); ~17
"Phase 0: placeholder" stubs (3 actively misleading). Full inventory
method: per-file inbound-reference counts + role classification
(recorded in `HERMES_PHASE0_HYGIENE_CERTIFICATION_2026-09-20.md` §5
and the Phase 1 working notes).

## 3. Documents created/updated

- `AGENTS.md` (new, 139 lines): identity, 14 certified invariants
  with code pointers, change discipline, canonical test/typecheck
  commands, orientation map, history-pointer section.
- `docs/ARCHITECTURE.md` (new): §§3.1–3.11 from source (purpose,
  layer map, write/read paths, provider/authority/contradiction/
  replay/isolation/persistence-with-§3.10-debt/extension) + 4
  verified Mermaid diagrams (system, mutation/authority,
  contradiction lifecycle, replay).
- `docs/API.md` (new): CLI, Controller, intents, adapters, events/
  records, repositories, errors — each labeled PUBLIC/INTERNAL/
  UNDECLARED with the frozen/evolving/internal convention.
- `docs/STATE.md` (new): certified chain, authoritative docs,
  production vs historical, known debt, non-goals, next phase.
- `docs/README.md` (new): navigation tree with CURRENT/
  HISTORICAL/FUTURE labels.
- `examples/first_run.py` (new, executable, verified exit 0):
  CLI-only tour (init → doctor → project create → id-resolve via
  status --json → show → run → status → audit) on a temp config/DB.
- `README.md` (+11 lines): Documentation-map section linking the
  six entry points.

## 4. Architecture verification (source-checked claims)

Every invariant/boundary anchored to implementation (anchor-check
script: all 41 path refs resolve; every `file:line` verified):
`apply_intent` `gateway.py:3732`; tick/loop `controller.py:482,597`;
detector `controller.py:1872,1901,1967`; lease `:2426`; writer
`record_failure_classification:2162`, resolution `:2052`,
retraction `:1725`; intent partitions `intents.py:115,124,135`;
validators `gateway.py:1155,2364,2455,2857`; N1/predicate
`contradictions.py:75,106` + `source_outcomes.py:159`; schema v17
`migrations.py:20`; adapter ABC `tools/providers/base.py:139`,
registry `tools/providers/adapters/__init__.py:37`; replay
`tools/providers/replay.py:293`; debt imports enumerated verbatim
(§3.10); `hazards.py:137` exception recorded. No stale text copied
from historical reports (all claims re-derived).

## 5. API verification

Surfaces inventoried from code (CLI parser `cli.py:657-819`,
Controller public methods `:476-:3789`, `IntentKind` 18 members,
11 adapters, repository readers, 16+13+6+8 error vocabularies).
Stability: frozen-by-decision (intent/event/identity strings,
rejection-code meanings), evolving (validator strictness, read
shapes), internal (gateway internals, derivation), UNDECLARED where
undecided (direct repository construction). No versioning machinery
introduced (none warranted — CLI is the sole external surface).

## 6. Diagram verification

A (system): CLI→Controller→gateway→persistence/journal + provider/
replay branch — matches §3.2 table. B (mutation/authority):
command→HumanDecision→intent→apply_intent→validators→tx→journal
with refusal arm — matches §3.3 + codes. C (contradiction):
evidence→pair→detect→OPEN→HR-08/resolve/supersede + N9 edge —
matches P7-certified lifecycle + §3.7. D (replay): journal→replay→
state + byte-vs-validity split — matches §3.8 + N9 rule. Fences
balanced (5 opens/5 closes). No idealized components (every node is
a cited file/function).

## 7. Examples verification

Created: `examples/first_run.py` (CLI-only, temp config/DB,
deterministic, zero network). Executed: exit 0; empty project
runs "0 dispatched, 0 succeeded…"; UUID-id resolution via stable
`status --json` schema documented in-code (the `project create`
name-vs-id behavior from `cli.py:304-309` bit once during authoring
and is now pinned in the example). Deeper executable flows
deliberately NOT created: they would need test-identical fixture
scaffolding or invented simplifications — the N9/P7 suites remain
the executable specifications (recorded, not hidden).

## 8. Historical/current separation

Labels enforced (`docs/README.md`); `STATE.md` splits CERTIFIED /
KNOWN DEBT / PLANNED / DEFERRED; new docs never cite gate records
as contract (archive links only as evidence pointers);
`AGENTS.md` contains zero chronology. Residual: 83 root historical
docs remain unmarked in place (mass moves rejected in Phase 0 for
reference integrity) — mitigated by navigation + index, flagged as
the known remaining gap (NOT a certification failure: nothing
claims them as current).

## 9. Production-source impact

NONE. `git diff --stat` for src: empty (the 3 stub-docstring edits
were Phase 0 commit `1cb30fb`, pre-existing here). This phase adds
docs + one example script only. Ruff run includes `examples/`:
clean.

## 10. Validation

- Full suite: **2035 collected, 0 failed, 0 errors, 0 skips**
  (JUnit XML) — count identical to certified baseline.
- `ruff check src tests examples`: clean. (`git diff --check`:
  clean.)
- `pyright src`: 0 errors. Tests profile: 0 errors + 1
  pre-existing warning (`test_research_program.py:141`).
- Link/reference audit: 41 internal path refs resolve; all code
  anchors verified; mermaid fences balanced; example executed
  exit 0.

## 11. Adversarial review (14 questions)

(1) Historical mistaken for current: mitigated via labels +
navigation + STATE; residual root sprawl documented in §8. (2)
Mutation bypass after reading: explicitly forbidden (§3.3, AGENTS).
(3) Single path identified repeatedly. (4) Authority explicit
(§3.6, kind table). (5) Adapters isolated + exception recorded.
(6) Inversion documented as KNOWN DEBT, never presented fixed.
(7) Public/accidental split explicit (§API). (8) No invented
stability (UNDECLARED used). (9)(10) Tests/IDRs discoverable via
AGENTS + index. (11) Labels answer it. (12) Diagrams verified §6.
(13) No uncertified feature presented as certified (agents/stubs
marked non-production; tick-loop cited only as certified with its
record). (14) No claim exceeds evidence (§4 anchors). Fixes
applied during review: 4 bare path refs expanded to full paths;
 fences rechecked; example hardened for UUID ids.

## 12. Remaining gaps

Genuine, out of scope: root historical sprawl still in place
(needs Phase-1-planned archive pass with reference migration);
no per-seam worked examples beyond the CLI tour; accidental
publics not yet underscored; stability convention not yet ratified
as a decision. None blocks Phase 1 certification (docs are
accurate; gaps are labeled, not hidden).

## 13. Verdict

`PHASE 1 — CERTIFIED`
