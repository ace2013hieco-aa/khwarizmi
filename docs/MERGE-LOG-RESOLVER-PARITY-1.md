# MERGE-LOG-RESOLVER-PARITY-1 — resolver parity pinned, test-only (P3-15)

## Provenance

| Item | Value |
| --- | --- |
| Task | RESOLVER-PARITY-1-MERGE (merge gate; local FF — the push is bundled with the sibling slices under one human D9 pin) |
| Base (`main` before) | `9ff786e` (CRES-DIGEST-1 landing tip) |
| Slice | `slice/resolver-parity-1@9fb38c9`; **restacked** as `slice/resolver-parity-1-restacked@977478a` (cherry-pick of `6f87c8a`; the slice's own re-stamp dropped and re-created for the combined count — **no rebase**, no merge commit) |
| Landed tip (FF'd to) | `977478a` — tree `eaa607def2014b477994b6a9702d9c2ffb4c997e` |
| Merge worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` (exit 0); single-parent chain |
| Push | drafted, **NOT executed** — bundled with the fleet under one human D9 pin |

## Scope

```
tests/test_resolver_parity.py    | 328 +  0 -   (42 pins, new)
docs/SUITE-COUNT.md              |   3 +  3 -   (4701 -> 4743)
```

**Test-only by design (ruling R10).** Zero production behavior change — the two evidence-ref
resolvers (`_cx_resolve_evidence_ref` in `gateway.py`; `detector_resolve_ref` in
`contradiction_candidates.py`) are pinned to agree on the six typed prefixes (`evidence`,
`source_result`, `source_payload`, `source_search`, `failure_classification`, `feature_binding`),
to share the web bar, and to fail closed on cross-project refs; the bare-ID divergence is pinned
explicitly (gateway returns `None`; the detector resolves a project-scoped row; bare + web refuse
on both sides). A behavior change would feed the frozen N1 pair rule and needs its own gate — none
was made. The one observed asymmetry beyond bare-ID (a retracted typed ref: gateway `None` vs
detector resolving at the resolver level) is the certified N9 layering applied one level up in
`detector_candidate_rows` (pinned by `tests/test_n9_resolve_path_pin.py`), recorded in the new
suite's module docstring, not patched.

## Non-vacuity (in lieu of fail-on-base — no behavior change)

In-test intermediates (row/hash assertions before each resolution; `source_artifact_is_web_derived`
true on every refused web row; p2-side positive controls on cross-project pins; web-bar spy
assertions receiving exactly the looked-up id, `[]` on the gateway bare short-circuit); plus two
locally applied-and-reverted mutations: gateway bare path altered → exactly the 3 bare-ID pins
fail; detector bare path → `None` → exactly the 3 corresponding pins fail (3 failed / 39 passed
each). Working tree clean after revert; full suite re-confirmed green.

## Gates (raw)

Agent run (slice tip): combined battery `127 passed`; full suite `4708 passed, 3 skipped`
(exit 0); stamp OK 4711 (own branch); census PASS; B4 24/24; ruff pass; pyright src 0/0/0;
pyright tests 0 errors + 1 pre-existing warning.

Director restacked-tip re-derivation (live): stamp `--check` OK **4743**; census **PASS**;
B4 `24 passed`; battery (`res_parity` + `s1_detector_rows` + `chg1` + `n9_retraction` +
`n9_resolve` + `hr8_blind_window`) `140 passed`; ruff `All checks passed!`; NOT-list scan
(range diff, word-boundary) **0 hits** (raw case-insensitive scan flags only "i**tse**lf"
substring noise).

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| real divergence beyond documented bare-ID/web | **none** — the retracted-ref asymmetry is the certified N9 layering, recorded not patched |
| src change needed | **none** — delta is tests + stamp only |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `9ff786e` |
| `--check` drift | **PASS** — 4743 (4701 + 42) |
| census / B4 drift | **PASS** — unchanged |
| push without a human hash-pin | **none performed** |

## Bundled push plan (drafted, NOT executed)

One human D9 pin covers the single final tree (CHG-DEDUP-1 + CX-OVERLAP-1 + CRES-DIGEST-1 +
this landing + all merge logs): origin fast-forward `2b0228d → <final tip>`; public mirror
orphan-sync with tree = `<final tip>^{tree}`, parent = live mirror HEAD, exact-hash push, no force
(rule #5).

## Prohibited-claims discipline

This gate certifies a parity-test-only slice pinning resolver agreement and the documented
divergences. It makes no validity, reproducibility, or admissibility claim.

License: Apache-2.0 (LICENSE).
