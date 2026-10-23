# MERGE-LOG-UNWRAP-AUDIT — untrusted-text unwrap audit and the scoped single-seam claim (GAP-1 P2-5)

## Provenance

| Item | Value |
| --- | --- |
| Task | UNWRAP-AUDIT (merge gate; local FF — the push is bundled with the wave-3a fleet under one human D9 pin) |
| Base (`main` before) | `3193e23` (D8-HYGIENE landing + its merge log) |
| Slice | `slice/unwrap-audit@cd79bfb`; **restacked** as `slice/unwrap-audit-restacked@5def094` (5 cherry-picks; the slice's two re-stamps dropped and re-created once for the combined count — no rebase, no merge commit) |
| Landed tip (FF'd to) | `5def094d104495ec38f9be35f4de36eb0d22ee7c` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — bundled with the wave-3a fleet under one human D9 pin |

## Scope

```
docs/P2-5-UNWRAP-AUDIT.md        | 122 ++  (new: per-site audit)
src/hermes/research/prompt_assembly.py | 6 +- (module docstring only)
tests/test_p2_5_unwrap_audit.py  | 356 ++  (new: 11 pins)
docs/SUITE-COUNT.md              |  +3 -3  (4940)
```

## Accepted deviation from "docs + tests only"

The slice edits **one `src` file, docstring only**:
`prompt_assembly.py`'s module docstring claimed the single grep-auditable
`.text` unwrap lives "nowhere in this module", which was the false single-seam
framing this audit exists to correct. The new text states that the module
reads no envelope `.text`, points at `docs/P2-5-UNWRAP-AUDIT.md` for the
documented seams, and calls the envelope an accident barrier rather than a
security guarantee.

Verified as **zero-behaviour**: the pin asserts
`_text_reads(prompt_assembly) == []` (no `ast.Attribute(attr="text")` node
anywhere in the module), and the assembled-prompt test still shows the marker
form with the hostile payload absent. No prompt template, prompt byte, replay
fixture, or durable record changed.

## What was certified

- **Per-site classification with file:line evidence** — 13 sites, each with
  the value read, its untrusted origin, and its downstream flow:
  - **COVERED (the seam)** — `prompt_assembly.py:141` (`_require_envelope`),
    `:195`, `:223`: markers only, `str(marker)`, no payload.
  - **COVERED (derivative-only)** — `run.py:320` (`_tool_feedback`: bytes +
    digest), `run.py:1495` (`_validate_inputs`: length bound → `RATIONALE`),
    `types.py:295` (`digest`), `types.py:317` (`to_mapping`, round-tripped by
    `from_mapping`), `invoke.py:684-685` (`_replayed_or_conflict`: digest),
    `crawl4ai_provider.py:381-384` (SHA-256 only), `router.py:1630` (char count
    → token estimate).
  - **DELIBERATE SEAM (documented accessor)** —
    `capability_handler.py:253` (`ObservationHandoff.payload_text`),
    `crawl4ai_provider.py:233-236` (`Crawl4aiPage.payload`),
    `docling_provider.py:382-389` (`DoclingDocument.payload`),
    `router.py:635-641` (`ModelStreamResult.text`), and the unavoidable
    provider-wire materialisation at `router.py:1661-1670` (`_build_call`).
  - **UNWRAPPED: none.**
- **The single-seam claim is withdrawn, not repaired.** There are four
  documented unwrap accessors and two prompt paths (`prompt_assembly` for the
  researcher/extract path; `agents.runtime.ContextAssembler` +
  `router._build_call` for the agent runtime). The audit says so in the
  document and pins the accessor set by AST scan
  (`test_the_documented_unwrap_seams_are_the_audited_set`), so a new
  docstring-declared unwrap fails the suite.
- **Residual gaps reported, not fixed** — no runtime enforcement
  (`UntrustedContent.text` is a public field), two prompt paths, raw text at
  rest in checkpoint/record JSON, envelopes label but do not sanitize, and
  `.text`-adjacent rendering in `vault/projection.py` left out of scope.
- **Honest claim** — the envelope is an *accident barrier*. The document
  explicitly refuses any security-guarantee or injection-proofing reading and
  keeps replay determinism distinct from validity.

## Gates (raw, at restacked tip `5def094`)

- `tests/test_p2_5_unwrap_audit.py`: **11 passed**
- `tests/test_p_auto_2_prompts.py tests/test_loop1_context_assembly.py`: **24 passed** (no prompt-byte drift)
- `stamp_suite_count.py --check`: `OK: docs\SUITE-COUNT.md collected=4940 matches the live collect` (4929 + 11)
- `ruff check src tests scripts`: `All checks passed!`
- Full suite: batch-end gate at the combined wave-3a tip (recorded in
  `docs/MERGE-LOG-WAVE-3A.md`).

## STOP-condition checks

| Condition | Result |
| --- | --- |
| prompt-byte change | **none** — the only `src` edit is the module docstring; the prompt pins pass unchanged |
| replay-fixture change | **none** — no fixture touched |
| behaviour change | **none** — no executable statement altered |
| security over-claim | **none** — the document withdraws the single-seam claim and refuses a security-guarantee reading |
| census shift | **none** — no transaction-control code touched |
| B4 digests moved | **no** — no governed doc touched |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies a data-flow classification of `.text` reads in this tree.
`COVERED` is a statement about this tree's routes, not a security property; the
envelope is an accident barrier, not access control. No validity,
reproducibility, or admissibility claim is made, and nothing here claims that
prompt injection is prevented.

License: Apache-2.0 (LICENSE).
