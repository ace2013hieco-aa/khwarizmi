# MERGE-LOG-OPS-1 — the CLI composes the live controller (wave 4, first item)

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-1: let `hermes run` compose the model plane and the methodology handler |
| Base (`main` before) | `9054333` (OPS-4A landed) |
| Slice | `slice/ops-1-live-cli` — five commits plus one Director correction, **fast-forwarded** |
| Landed tip | `5bd23099c55c2887d9bac98eb87b6f02d45498cb` (tree `a75c0ed4…`) |

Commits: `53b400b` (design gate) → `75ae5c4` (rulings R1–R6) → `aedcfcd` (implementation) →
`266fb26` (governed docs + regeneration) → `a1feaa7` (API.md repair + regeneration) →
`5bd2309` (Director correction, below).

## What landed

- **A2 — a code-owned provider registry** `provider_id → (dialect, api_key_env)`
  (`anthropic`, `openai`). Specs are built from the tier refs, so `[model_tiers]` stays
  byte-unchanged and `check_composition`'s mismatch branch becomes unreachable — kept as
  defence in depth.
- **B1 — live iff `tier_refs_from_config(cfg)` is non-empty**, plus **`--drain-only`** for one
  invocation. The flag is named for what it does: the drain path still writes (gates park,
  rows transition), so `--dry-run` would have been a lie. The Director's charter said
  `--dry-run`; the ruling corrected it.
- **Pre-flight before `connect`** — a refused live run never opens or migrates the database.
- **Mode line, ledger, vector** — live prints `Model plane: live (tiers: …)`, one `model call`
  row per attempt (tier/provider/model/outcome/tokens, **never a price**, capped at 20), and
  one `vector:` line. Drain-only prints none of them, so **silence means the model plane was
  never composed** — a property you can check from the output alone.
- `build_live_composition(...)` returning a frozen `LiveComposition`, with
  `build_live_controller` kept as the thin wrapper.

## The drain-only guarantee

The agent captured today's output from a scratch worktree at `9054333` and from `HEAD`, with
two separate interpreters, and the diff was **empty** — same exit code, same line, empty
stderr in both. The bytes are pinned as `DRAIN_ONLY_OUTPUT` and the model transport is
**booby-trapped** during that test (`ProviderHTTPTransport` → `pytest.fail`), so a composed
plane fails the guard instead of hiding behind an unchanged snapshot. That is the right shape
for this test: it would catch the failure that matters.

## The material finding: live mode is model-only

`build_live_composition` wires **no capability port**, and `_model_only_profiles` narrows a
*copy* of every profile to `allows_tool_calls=False` so the request declares no tools at all.
The cloud provider refuses a reply that carries a tool call, so asking for one could only fail
later.

The consequence is bigger than the slice: **a live run drafts and reviews, and observes
nothing.** M2 is `n/a` for a structural reason, not an incidental one. OPS-4's first real run
will be a text-only run — proposals grounded in the prompt and prior context, with no
literature retrieval.

This does not make the slice wrong — it is scoped to the model plane and says so. But it means
**OPS-5 (capability/provider wiring) is not an optional side quest; it is the difference
between an agent that can think and one that can look things up.** The roadmap treats it as
parallel; it should be treated as next.

## The Director correction (recorded, not quietly fixed)

`test_ops1_live_cli.py` shipped a docstring claiming a **pre-existing plane defect**: *"the
plane's validator requires a top-level `kind` and the parser refuses `kind` + `proposals`
together, so the documented multi-proposal form is unreachable through the router."*

That is **false**. `agents/runtime/run.py:640` admits `proposals` whenever the profile declares
it in `structured_fields` — and all six shipped profiles do — while `:648` refuses only when
**both** forms appear in one reply, which is correct. The multi-proposal form is in active use:
`tests/test_loop2_feedback.py::_draft` drives it and passes.

The single-proposal choice was fine; the justification was not. The correction (`5bd2309`)
replaces the claim with the real reason — the contract's `kind_field` prompts for a top-level
kind (`tools/models/cloud.py:240-243`) — and states that the earlier claim was wrong. A phantom
defect in a docstring is worse than no note: it invites someone to "fix" working code.

## B4 regeneration (two rounds, both deliberate)

`docs/STATE.md` **and** `docs/API.md` are governed, so `b4-c1`/`b4-c2`/`b4-c4` moved twice:
once for the content edit, once after the first `API.md` edit was found to have swallowed a
list separator — fusing `run` and `gate resolve` into one sentence and leaving an unclosed
inline span in a governed corpus member. The agent fixed the cause and regenerated rather than
shipping a mangled sentence with matching digests.

| fixture | before | after | edges | sources | skipped |
| --- | --- | --- | --- | --- | --- |
| `b4-c1-p1a-baseline` | `f8a80697…` | **`cdeb67d6…`** | 5 | 6 | 21 |
| `b4-c2-expanded-cohort` | `1b8aaec7…` | **`6a0ad579…`** | 19 | 12 | 28 |
| `b4-c3-idr-design-chain` | `eef41946…` | `eef41946…` (unchanged) | 10 | 8 | 15 |
| `b4-c4-authority-spine` | `ddc877b0…` | **`652e6a81…`** | 5 | 4 | 18 |

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted (CLI, cloud, composition, loop, B4, census, controller) | **245 passed** |
| Full suite | **5080 passed / 3 skipped / 0 failed** (5083 collected) |
| `stamp_suite_count.py --check` | `collected=5083` |
| `check_census.py` | **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0 |
| B4 ref graphs | **24 passed** after both regenerations |
| `ruff` / `pyright src` / tests | clean / **0/0/0** / **0 errors, 1 known warning** |
| Invariant surfaces | **0 files** — `controller.py`, `agents/runtime/`, `loop_metrics.py` untouched |
| Drain-only snapshot | **diff empty**, transport booby-trapped |

## Residuals

1. **No capability port in live mode** — see the material finding above. OPS-5 is the gate.
2. **The vector is in-process only.** Traces and checkpoints are in-memory (B-5 refuses
   durability), so `vector:` exists only in the run's own output. A durable run report needs a
   second slice.
3. **`doctor` says nothing about the model plane** — deliberately OPS-2.
4. **No dollar figure anywhere** — cost metadata defaults to `0.0`, so the ledger carries
   tokens only. Anyone who later wants spend reporting must first make the metadata real.

License: Apache-2.0 (LICENSE).
