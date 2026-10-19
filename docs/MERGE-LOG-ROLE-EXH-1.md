# MERGE-LOG-ROLE-EXH-1 — role-gate exhaustiveness closed, fail-closed (GAP-1 P1-5)

## Provenance

| Item | Value |
| --- | --- |
| Task | ROLE-EXH-1-MERGE (merge gate; local FF — the push is bundled with the sibling GAP-1 slices under one human D9 pin) |
| Base (`main` before) | `c368886` (RESOLVER-PARITY-1 landing tip) |
| Slice | `slice/role-exh-1@c6680b7` — branched at current `main`; **no restack needed**, no merge commit |
| Landed tip (FF'd to) | `c6680b7` — tree `ed95b29299c9c29f6c4f37195b3d35a53fdf2b91` |
| Merge worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` (exit 0); single-parent chain |
| Push | drafted, **NOT executed** — bundled with the GAP-1 fleet under one human D9 pin |

## Scope

```
src/hermes/research/gateway.py   |   9 +  0 -   (_require_role positive admission)
tests/test_role_exhaustiveness.py| 172 +  0 -   (16 pins, new)
docs/SUITE-COUNT.md              |   3 +  3 -   (4743 -> 4759)
```

The role gate's final branch was negative admission: a kind in none of the three
authority partitions (`director_only` / `internal_only` / `llm_proposable`) fell
through and was silently admitted for all four LLM agent profiles. All 19 current
kinds were partitioned, so the hole was latent — a forward-compatibility trap for
the next kind added without classification. The fix admits an LLM profile only
for kinds `in IntentKind.llm_proposable()`; the `director_only` and
`internal_only` early-return branches (and the DETERMINISTIC exclusion) are
untouched, so **no current (kind, profile) decision changes** — proven by the
matrix pins, not just asserted.

## Fail-on-base (applied-and-reverted mutation)

Agent run at base `c368886` with the fix absent and the test file present:
**4 failed, 12 passed** — all four
`test_a_kind_in_no_partition_is_refused_for_every_profile[DIRECTOR|RESEARCHER|
IMPLEMENTER|ADVERSARY]` (`DID NOT RAISE GatewayRejection`: base admits the
simulated unpartitioned member for the LLM profiles; DETERMINISTIC was refused
on base too). Same file at fix `475698c`: **16 passed**. Revert verified
(`git diff -- src/hermes/core/intents.py` = 0; post-revert re-run 16 passed).
Raw logs: `role-exh-1-fob-base.txt` / `role-exh-1-fob-fixed.txt`.

## Gates (raw)

Agent run (slice tip): fail-on-base recorded above; full suite `4756 passed,
3 skipped, 0 failed` (566.94s); stamp OK 4759; census PASS; B4 24/24; ruff
pass; pyright src 0/0/0; pyright tests 0 errors + 1 pre-existing warning.

Director re-derivation (landed tip `c6680b7`, heavy-gate lock held): full suite
`4756 passed, 3 skipped` in 555.41s (exit 0, none of the baseline reds fired);
stamp `--check` OK **4759**; census **PASS** (121 calls / 27 owners 18-5-4 /
1 rollback-only / 15 imports — unchanged); B4 `24 passed`; ruff
`All checks passed!`; pyright src 0/0/0; pyright tests 0 errors +
1 pre-existing warning (`test_research_program.py:144`); NOT-list scan of the
range diff **0 hits**.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| current admission decisions changed | **none** — matrix pins prove every (kind, profile) decision kept |
| `intents.py` partitions edited | **no** — byte-identical to base; fix is gateway-side |
| exhaustiveness guard forward-compatible | **PASS** — structural over the live enum, no counts; a new unclassified kind reds the union check |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `c368886` |
| `--check` drift | **PASS** — 4759 (4743 + 16) |
| census / B4 drift | **PASS** — unchanged |
| push without a human hash-pin | **none performed** |

## Notes for the sibling landings

- The guard enforces disjoint *effective* admission classes; the one permitted
  declaration-level overlap is `PROPOSE_RESEARCH_PROGRAM` in both
  `llm_proposable` and `director_only` (Director precedence) — pinned, not
  patched.
- CRED-1 (parallel slice) adds two `director_only` kinds; this guard passes
  with them classified, as designed.

## Prohibited-claims discipline

This gate certifies a fail-closed hardening of the role-admission path with
zero change to current decisions. It makes no validity, reproducibility, or
admissibility claim.

License: Apache-2.0 (LICENSE).
