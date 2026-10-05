# TEXP-001 S1 — SOURCES.md (per-element provenance)

Binding rule: every element below is labeled TRANSCRIBED (with exact
source) or STIPULATED (with authorizing terms). Nothing is presented as
transcribed that is not. GR3-doc absence is declared, not papered over.

| Element | Provenance | Status |
|---|---|---|
| Edge alphabet (14 classes: `supports`, `contradicts`, `entails`, `refines`, `analogous_to`, `tested_by`, `produced_by`, `depends_on`, `invalidates`, `requires`, `blocks`, `applies_to`, `observed_in`, `replicated_by`) | `hermes_research_architecture_v6.md` §14 line 780 ("Unified edge catalog" list), transcribed live 2026-09-25 (14 classes extracted programmatically and eyeball-checked) | TRANSCRIBED |
| `ADMISSIBLE_SEQUENCES` (8 entries in `validator.py`) | None — no sequences table exists anywhere checked | STIPULATED per v1.3 terms (minimal table; per-entry `# STIPULATED` comments in code). Any production use requires the real GR3 sequences. |
| `ADMISSIBLE_SEQUENCES` ℓ3/ℓ4 entries (2 entries, S5-unify) | None — bounded to D2 strata needs (ℓ∈{2,3,4}); nothing decorative | STIPULATED per S5-unify authorization (per-entry `# STIPULATED (S5-unify…)` comments). Opens K-S5a (see S5-unify-report). |
| `VALIDATOR_PROVENANCE` flag | Authored here to seed K2 (P1 audit) | STIPULATED-in-form (it describes, not derives); lock `validator_ref` must quote it |
| Module shape, reason codes, test plan | Original authorship for this task | ORIGINAL |
| GR3 proposal document | Searched: repo-wide file glob (no `*GR3*` file), v6 full-text ("admissible sequence": 0 hits; no "GR3 proposal" file reference) | ABSENT (declared) |
| TEXP-001 spec v1.2 input | Untracked worktree file `docs/texp-001/TEXP-001-spec-v1.2.md`, 205 lines, sha256 `94b19e9d010a0ee592daef296e1ce1d1126c6adacce45a5cb00febc6ef6e19d3` (confirmed pre-build; never committed) | INPUT OF RECORD |

Third-party code: none copied or imported. No Ditto code (EPL-2.0
constraint honored — nothing from any external codebase is reproduced
here); no FaceChain content. The "Ditto patterns may inform shape"
permission was not needed: the validator is a closed-vocabulary
prefix-table check whose shape follows the production F5 hook
(`ClaimAssumptionRepository._dereference_artifact_ref`,
`persistence/repositories.py:1943-1990`) and the v6 edge vocabulary.
