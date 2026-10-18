# MERGE-LOG-CRES-DIGEST-1 — resolution digest populated from the bound decision (P3-17)

## Provenance

| Item | Value |
| --- | --- |
| Task | CRES-DIGEST-1-MERGE (merge gate; local FF — the push is bundled with the sibling slices under one human D9 pin) |
| Base (`main` before) | `20f8e16` (CX-OVERLAP-1 landing tip) |
| Slice | `slice/cres-digest-1@0142289`; **restacked** as `slice/cres-digest-1-restacked@5ba6127` (cherry-picks of `e9c3419` + `f8c49e0`; the slice's own re-stamp dropped and re-created for the combined count — **no rebase**, no merge commit) |
| Landed tip (FF'd to) | `5ba6127` — tree `c8003c1cdc70f58b0fa73c1687d77eba524ee8ab` |
| Merge worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` (exit 0); single-parent chain |
| Push | drafted, **NOT executed** — bundled with the remaining fleet under one human D9 pin |

## Scope

```
src/hermes/research/gateway.py           |  38 +  2 -   (fix)
tests/test_cres_digest_binding.py        | 576 +  0 -   (16 pins, new)
docs/SUITE-COUNT.md                      |   3 +  3 -   (4685 -> 4701)
```

**The fix (P3-17).** The resolution UPDATE now writes `resolution_rationale_digest` —
`sha256(rationale.encode("utf-8")).hexdigest()` over the rationale bytes of the **bound**
`HumanDecisionReceived` decision row (queried project-scoped, recomputed in-transaction; the
command payload stays exactly `{contradiction_id, human_decision_ref, operator_id}` and can never
substitute the value). NULL-safe policy pinned: absent/non-string rationale stores NULL (the
existing decision-binding validation remains the admission gate); an empty string digests as
`sha256(b"")`; an unencodable rationale refuses fail-closed (`PROPOSAL`, rolled back by the
existing handler — census unchanged). No schema change; the column pre-existed.

## The pins (`tests/test_cres_digest_binding.py`, 16)

Digest population (`test_resolution_stores_digest_of_bound_rationale`,
`test_empty_rationale_digests_empty_string`, `test_different_rationale_different_digest`,
`test_same_rationale_same_digest_across_contradictions`, `test_readback_via_repository_returns_digest`) ·
rationale policy (`test_absent_rationale_stores_null_without_new_refusal`,
`test_non_string_rationale_stores_null`, `test_unencodable_rationale_refused_fail_closed`) ·
replay (`test_replay_returns_duplicate_and_keeps_digest`, `test_replay_with_different_rationale_never_redigests`) ·
refusals (`test_fabricated_decision_still_proposal`, `test_superseded_target_still_stale`) ·
payload closure (`test_extra_rationale_key_refused`, `test_controller_submits_exactly_three_keys`) ·
append-only + identity (`test_event_prefix_and_row_history_preserved`,
`test_contradiction_identity_recomputed`).

## Fail-on-base (agent-run, scratch at `2b0228d` + the new test file)

**10 failed, 6 passed** (exit 1): base stores NULL — digest pins fail (`None == '<digest>'`), the
unencodable-rationale refusal does not raise, replay pins fail, the 3-key payload leaves NULL.
Scratch worktree removed.

## Gates (raw)

Agent run (slice tip): combined battery `276 passed`; full suite `4682 passed, 3 skipped` (exit 0);
stamp OK 4685 (own branch); census PASS (121 / 27 = 18-5-4 / 1 / 15, no new control calls);
B4 24/24; ruff pass; pyright src 0/0/0; pyright tests 0 errors + 1 pre-existing warning.

Director restacked-tip re-derivation (live): stamp `--check` OK **4701**; census **PASS**;
B4 `24 passed`; cross-slice battery (cres + chg1 + governance + HR-08 + cx + chg-dedup)
`292 passed`; ruff `All checks passed!`; NOT-list scan (range diff) **0 hits**.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits in the delta; only pre-existing clearance prose on the base tree |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `20f8e16` |
| dirty main-bound worktree | **PASS** — clean pre-FF and post-FF |
| `--check` drift | **PASS** — 4701 (4685 + 16) |
| schema / payload-keys change | **PASS** — none (frozen key set pinned; no migration) |
| census / B4 drift | **PASS** — unchanged |
| push without a human hash-pin | **none performed** |

## Bundled push plan (drafted, NOT executed)

One human D9 pin covers the single final tree (CHG-DEDUP-1 + CX-OVERLAP-1 + this landing +
RESOLVER-PARITY-1 + all merge logs): origin fast-forward `2b0228d → <final tip>`; public mirror
orphan-sync with tree = `<final tip>^{tree}`, parent = live mirror HEAD, exact-hash push, no force
(rule #5).

## Prohibited-claims discipline

This gate certifies a hygiene fix (dead column populated from the bound human decision) with
pinned NULL/refusal policy. It makes no validity, reproducibility, or admissibility claim.

License: Apache-2.0 (LICENSE).
