# P2-5 — untrusted-text unwrap audit (single-seam claim)

- **Slice:** `slice/unwrap-audit` (local-only, never pushed)
- **Base:** `332614ca2b8093369e8e590a0facd63a380dc536`
- **Triage input:** `AUDIT-GAP-1-TRIAGE.md` §P2-5 (`VALID-narrowed`:
  "the accident-barrier characterization holds; the single-seam claim does
  not")
- **Scope:** audit only. No provider prompt bytes, replay fixture, or
  durable record changes. No provider internals touched beyond the two
  documented seams.
- **Pins:** `tests/test_p2_5_unwrap_audit.py`.

## 1. Question

`src/hermes/research/prompt_assembly.py` described itself as the single
grep-auditable `.text` unwrap. The triage found trust-relevant `.text`
reads outside it (`run.py`, `types.py`, `capability_handler.py`,
`invoke.py`) plus the deliberate provider seams. This audit classifies
each site by *what value is read*, *which untrusted source produced it*,
*where the value flows*, and *whether the envelope contract holds at that
downstream surface*.

Verdict vocabulary:

- **COVERED** — the envelope contract holds downstream. The read either
  never happens here (the seam) or yields only a non-payload derivative
  (size, digest, token estimate) or a round-tripped envelope. Raw text
  does not reach a prompt, a tool argument, a log line, or an error
  message.
- **DELIBERATE SEAM** — a named, documented accessor whose whole purpose
  is to expose the payload to a caller that has decided to use it.
- **UNWRAPPED** — a bypass with no documented rationale and no envelope
  at the downstream surface.

`COVERED` is a statement about this tree's data flow, not a security
property. The envelope is an **accident barrier**: it makes the ordinary
mistake (interpolating an envelope into a string) visible. It is not an
access-control or sandbox mechanism.

## 2. Per-site verdicts

| # | Site | Value read (untrusted origin) | Downstream flow | Verdict |
| :-- | :--- | :--- | :--- | :--- |
| S1 | `src/hermes/research/prompt_assembly.py:141` (`_require_envelope`), `:195`, `:223` | No payload read: markers must already be `UntrustedContent`; rendering uses `str(marker)` (the marker string form) | Assembled prompt text (marker + origin/ref/len, never payload) | **COVERED** (the seam) |
| S2 | `src/hermes/agents/runtime/run.py:320` (`_tool_feedback`) | Observed capability payload (`Observation.payload`, an `UntrustedContent`) | Prompt envelope carries `payload_bytes` + `payload_digest` only (`assembly.py:164-165`); the record has no text field | **COVERED** (derivative-only) |
| S3 | `src/hermes/agents/runtime/run.py:1495` (`_validate_inputs`) | Context envelope payload | A `RATIONALE` refusal code when the byte length exceeds the bound; no text leaves the guard | **COVERED** (derivative-only; found by this audit, not in the triage list) |
| S4 | `src/hermes/agents/runtime/types.py:295` (`TaskContext.digest`) | Context envelope payload | `digest_of(...)` input only; the digest is hex | **COVERED** (derivative-only) |
| S5 | `src/hermes/agents/runtime/types.py:317` (`TaskContext.to_mapping`) | Context envelope payload | Checkpoint JSON (`run.py:1589`, `checkpoint.py:166`); `from_mapping` re-wraps every item in `UntrustedContent` (`types.py:347-351`); prompts read the envelopes, not the mapping | **COVERED** (round-trip) — residual: raw text at rest in the checkpoint file |
| S6 | `src/hermes/research/task_handlers/capability_handler.py:253` (`ObservationHandoff.payload_text`) | Observed capability payload | Only on an explicit named call; `as_record()` (`:263-285`) carries origin/ref, never text. No production caller today | **DELIBERATE SEAM** (documented accessor) |
| S7 | `src/hermes/tools/capabilities/invoke.py:684-685` (`_replayed_or_conflict`) | Prior observation payload | `observation_digest` in the replay envelope (`:960-966`); `to_journal_note()` carries the digest, not text (`envelope.py:307+`) | **COVERED** (derivative-only) |
| S8 | `src/hermes/tools/providers/crawl4ai_provider.py:233-236` (`Crawl4aiPage.payload`) | Fetched/rendered markdown | Explicit accessor used by `to_record()`; `from_record()` re-wraps (`:249-265`) | **DELIBERATE SEAM** (documented) |
| S9 | `src/hermes/tools/providers/crawl4ai_provider.py:381-384` | Rendered raw/cited/reference markdown | SHA-256 provenance fields only (hex) | **COVERED** (derivative-only; found by this audit) |
| S10 | `src/hermes/tools/providers/docling_provider.py:382-389` (`DoclingDocument.payload`) | Extracted document text | Explicit accessor for digest, span location, and record serialization; record load re-wraps (`:466-488`) | **DELIBERATE SEAM** (documented) |
| S11 | `src/hermes/tools/models/router.py:1630` (`_estimate_context_tokens`) | Request prompt envelopes | Character count → token estimate; no text | **COVERED** (derivative-only; adjacent boundary) |
| S12 | `src/hermes/tools/models/router.py:1661-1670` (`_build_call`) | Request prompt envelopes | Provider call payload: text is finally materialised here, by construction | **DELIBERATE SEAM** (wire boundary; unavoidable, documented in the code) |
| S13 | `src/hermes/tools/models/router.py:635-641` (`ModelStreamResult.text`) | Model output chunks | Caller-chosen concatenation; model output is never an authority | **DELIBERATE SEAM** (documented accessor; adjacent boundary) |

**UNWRAPPED: none.** Every audited read is either derivative-only
(S2-S4, S7, S9, S11), a documented accessor (S6, S8, S10, S13), or the
deliberate provider-wire materialisation (S12); no read is an
undocumented route into a prompt, log, or error string. The triage's
narrow finding is confirmed in a stronger form: the single-seam claim is
false because there are **four documented unwrap accessors** (S6, S8,
S10, S13), two prompt paths (`prompt_assembly` for the
researcher/extract stub; `agents.runtime.ContextAssembler` +
`router._build_call` for the agent runtime), and derivative reads at
S2-S4, S7, S9, S11.

## 3. Documented unwrap seams (AST-scanned set)

The pin scans every `src/hermes/**/*.py` function whose docstring says
"unwrap" and whose body reads a `.text` attribute. The set is exactly:

| Seam | Contract |
| :--- | :--- |
| `capability_handler.py:ObservationHandoff.payload_text` | Observation payload for an admission validator; record form excludes text |
| `router.py:ModelStreamResult.text` | Model output concatenation for a caller that has decided to use it |
| `crawl4ai_provider.py:Crawl4aiPage.payload` | Fetched markdown for the raw record round-trip |
| `docling_provider.py:DoclingDocument.payload` | Extracted text for digest/span/record operations |

Adding a new docstring-declared unwrap without updating this table and
the pin fails the suite. The counts are a **grep/AST census**, not a
capability boundary.

## 4. Residual gaps (reported, not fixed)

1. **No runtime enforcement.** `UntrustedContent.text` is a public
   dataclass field. Any caller can read it; `isinstance` checks only
   catch accidental *use as a string*, not deliberate unwrapping. The
   contract is convention plus type-checker friction.
2. **Two prompt paths, not one.** `prompt_assembly` handles the
   researcher/extract path; `agents.runtime` assembles envelopes and the
   model router materialises them at the provider wire. A single-seam
   audit cannot be claimed for the tree.
3. **Raw text at rest.** `TaskContext.to_mapping()` and the provider
   `to_record()` forms persist payload text in checkpoint/record JSON.
   The text is re-enveloped on load and never becomes a prompt by that
   path, but the files are not authenticated or encrypted. This is data
   at rest, not a judgment surface.
4. **Envelopes label; they do not sanitize.** A hostile payload still
   reaches the model as data when a legitimate caller sends it. The
   defense is downstream: model output proposes, deterministic code and
   human-authority gates decide. Prompt injection can influence a
   proposal; it cannot decide a transition.
5. **Out of slice.** `.text`-adjacent rendering in `vault/projection.py`
   and the corpus-pack layer scrub are not audited here; they are not
   prompt assembly paths.

## 5. Honest claim

> The envelope is an accident barrier. Ordinary interpolation of
> untrusted content into a prompt, log line, or error yields a visible
> marker instead of the payload, and every audited route either reads no
> payload, consumes only a derived size/digest, or is the deliberate
> provider-wire materialisation of caller-supplied prompt text (S12).
> It is not a security guarantee: explicit `.text` unwraps are ordinary
> Python attribute reads, envelopes do not sanitize, raw text persists
> in derived checkpoint/record files, and prompt injection remains a
> possibility for any caller that deliberately unwraps.

Replay determinism is unchanged: this slice alters no prompt bytes and
no fixture.
