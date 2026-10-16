"""Context assembly — the deterministic prompt-envelope port (LOOP-1, LOOP-2).

The model prompt used to be ``context.context`` plus a tick marker, so
``TaskContext.payload`` — the stage identity, the methodology id, the
predecessor and its content — never reached the model, and a delegated review
child's whole prompt was a digest of the spec that named it. This module is the
injection seam that fixes that: the runtime calls ONE port, `ContextAssembler`,
to turn a run's `TaskContext` into the `UntrustedContent` envelopes a model
call carries.

LOOP-2 adds the other half of the same seam: `feedback_envelopes` renders the
tool-phase results a run has retained (`ToolFeedback`) as envelopes, so the next
tick sees what the last one observed and why a refused call was refused. It is a
pure function of the records, like everything else here — the runtime composes
it *after* the port, which is what keeps "what a prompt contains" answerable in
one place.

Deterministic by construction: every function here is a pure function of its
arguments — no clock, no model, no I/O, no ambient state — and payload keys are
rendered in sorted order, so equal contexts assemble to equal envelopes. Payload
values enter as *untrusted content* (an envelope is the only way text crosses
the boundary); the assembler decides nothing, it only renders.

Import discipline: `hermes.agents.runtime.types`, `hermes.security.boundaries`
(the envelope), and stdlib. Never `hermes.persistence`, never `hermes.research`,
never a model or capability port — the module holds no dependency it could call.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from hermes.agents.runtime.types import (
    MAX_PAYLOAD_BYTES,
    Proposal,
    ReviewVerdict,
    TaskContext,
    ToolFeedback,
    canonical_json,
)
from hermes.security.boundaries import UntrustedContent

__all__ = [
    "OBSERVATION_ORIGIN",
    "PAYLOAD_ORIGIN",
    "PROPOSAL_ORIGIN",
    "REFUSAL_ORIGIN",
    "RETRY_ORIGIN",
    "REVIEW_ORIGIN",
    "ContextAssembler",
    "assemble_payload_envelopes",
    "default_context_assembler",
    "feedback_envelopes",
    "proposal_envelopes",
    "retry_envelope",
    "review_envelopes",
]

#: The origin every payload envelope carries — the field a reader filters on.
PAYLOAD_ORIGIN = "runtime.payload"

#: The origin every review-draft envelope carries.
PROPOSAL_ORIGIN = "runtime.review"

#: The origin a retained tool **observation** carries — evidence the run saw.
OBSERVATION_ORIGIN = "runtime.observation"

#: The origin a refusal or failure **signal** carries: the call produced no
#: evidence, and this is why. Both signal kinds are the same discipline — data the
#: next tick reads, never an instruction it obeys.
REFUSAL_ORIGIN = "runtime.refusal"

#: The origin a consumed **review verdict** carries (LOOP-3): a reviewer's
#: judgment, carried into the next round as data. Same discipline as the two
#: feedback origins — the next round reads it, never obeys it.
REVIEW_ORIGIN = "runtime.review_verdict"

#: The origin a **retry note** carries (LOOP-4 E5): why the previous attempt at
#: the same call was refused. A retry used to re-issue the identical request, so
#: the second attempt could only fail the way the first did. Same discipline as
#: every other loop-state origin — data the next attempt reads, never an
#: instruction it obeys.
RETRY_ORIGIN = "runtime.retry"


class ContextAssembler(Protocol):
    """The prompt-envelope port: one run's context in, envelopes out.

    The runtime never decides *what* a model prompt should contain beyond this
    one call. A caller may inject its own assembler; the plane's precondition on
    any implementation is determinism — the same context must assemble to the
    same envelopes (the defaults are purity-tested).
    """

    def __call__(self, context: TaskContext) -> tuple[UntrustedContent, ...]: ...


def _document_envelope(origin: str, ref: str,
                       document: Mapping[str, Any]) -> UntrustedContent:
    """One envelope: the canonical encoding of a document, origin-labelled."""
    return UntrustedContent(text=canonical_json(dict(document)),
                            origin=origin, ref=ref)


def assemble_payload_envelopes(context: TaskContext
                               ) -> tuple[UntrustedContent, ...]:
    """Render `context.payload` as envelopes, one per top-level key.

    Sorted by key and canonically encoded, so equal payloads assemble to equal
    envelopes regardless of insertion order. The ref is ``{task_id}:{key}``, so
    every value the model reads is attributed to the run and the field it came
    from. The payload is data — it enters as untrusted content, never as
    instruction or authority.
    """
    return tuple(
        _document_envelope(PAYLOAD_ORIGIN, f"{context.task_id}:{key}",
                           {key: context.payload[key]})
        for key in sorted(context.payload)
    )


def default_context_assembler(context: TaskContext
                              ) -> tuple[UntrustedContent, ...]:
    """The port's default: the run's own envelopes, then its payload.

    `context.context` keeps its caller order (it is already an ordered tuple);
    the payload envelopes follow in sorted key order. Both halves are pure
    functions of the context, so the assembled prompt is a pure function of the
    run's inputs.
    """
    return tuple(context.context) + assemble_payload_envelopes(context)


def feedback_envelopes(feedback: Sequence[ToolFeedback]
                       ) -> tuple[UntrustedContent, ...]:
    """Render retained tool feedback as data envelopes, in arrival order (LOOP-2).

    One envelope per record; ordered by ``(tick, index)`` so equal feedback
    assembles to equal envelopes. The origin is the record's own outcome —
    `runtime.observation` for evidence the run actually observed,
    `runtime.refusal` for a refusal or a failure signal — and the ref is the
    call's *derived* identity (the same key the invocation carried), so every
    envelope is attributable to the run, the tick and the capability it came from.

    Two bounds, both explicit. The record carries no observation payload: only its
    size and digest travel, because the payload's certified route to a judgment
    surface is its artifact handle. And an envelope over `MAX_PAYLOAD_BYTES` keeps
    its identity fields — the refusal code and the outcome in particular — while
    the free-text `detail` is replaced by `detail_omitted_bytes`; a torn envelope
    is never emitted, exactly as a torn review body never is.
    """
    envelopes: list[UntrustedContent] = []
    for record in sorted(feedback, key=lambda item: (item.tick, item.index)):
        document: dict[str, Any] = {
            "tick": record.tick,
            "index": record.index,
            "capability_id": record.capability_id,
            "outcome": record.outcome,
            "refusal_code": record.refusal_code,
            "failure": record.failure,
            "detail": record.detail,
            "artifacts": list(record.artifacts),
            "payload_bytes": record.payload_bytes,
            "payload_digest": record.payload_digest,
            "invocation_ref": record.invocation_ref,
        }
        text = canonical_json(document)
        if len(text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            omitted = len(str(document["detail"]).encode("utf-8"))
            document["detail"] = ""
            document["detail_omitted_bytes"] = omitted
            text = canonical_json(document)
        envelopes.append(UntrustedContent(
            text=text,
            origin=(OBSERVATION_ORIGIN if record.is_observation()
                    else REFUSAL_ORIGIN),
            ref=record.invocation_ref))
    return tuple(envelopes)


def proposal_envelopes(proposals: tuple[Proposal, ...]
                       ) -> tuple[UntrustedContent, ...]:
    """Render the drafts under review for the review child's prompt (E1/G4).

    A review child used to receive ``digest_of(spec)`` — a digest of the
    delegation record that *named* the drafts — so it could never see what it
    was reviewing. This renders the drafts themselves: per proposal the
    position, draft digest, kind, rationale, payload, tick, profile and the
    admission verdict, canonically encoded, origin-labelled ``runtime.review``
    with the draft digest as the ref. Deterministic and pure; a rendered body
    over the 4 KiB cap keeps its identity fields and carries an explicit
    ``payload_omitted_bytes`` marker instead of a torn body — never a silent
    truncation, and never an I/O call from this module.
    """
    envelopes: list[UntrustedContent] = []
    for position, proposal in enumerate(proposals):
        digest = proposal.draft_digest()
        document: dict[str, Any] = {
            "position": position,
            "draft_digest": digest,
            "kind": proposal.intent.kind.value,
            "rationale": proposal.rationale,
            "payload": dict(proposal.intent.payload),
            "tick": proposal.tick,
            "profile": proposal.profile,
            "admission": proposal.admission,
        }
        text = canonical_json(document)
        if len(text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            omitted = len(
                canonical_json(document["payload"]).encode("utf-8"))
            document["payload"] = {}
            document["payload_omitted_bytes"] = omitted
            text = canonical_json(document)
        envelopes.append(UntrustedContent(text=text, origin=PROPOSAL_ORIGIN,
                                          ref=digest))
    return tuple(envelopes)


def retry_envelope(code: str, detail: str, *, attempt: int) -> UntrustedContent:
    """Render a retryable refusal as data for the next attempt (LOOP-4 E5).

    A retry re-issued the *identical* request, so a second attempt could only
    fail the way the first did: the runtime knew why the call was refused and
    withheld it from the only party that could act on it. This carries the
    refusal's code and its (untrusted) detail text, labelled `RETRY_ORIGIN` and
    attributed to the attempt that produced it, so the next attempt is asked an
    informed question instead of the same one.

    Pure and deterministic, like every renderer here — the same refusal renders
    the same envelope. The text is data: a model refusal's detail is the
    provider's own message, and nothing in the runtime reads it as an
    instruction. An oversized detail keeps the code and carries
    `detail_omitted_bytes` instead of a torn body, exactly as a feedback or
    verdict envelope does.
    """
    document: dict[str, Any] = {"attempt": attempt, "code": code, "detail": detail}
    text = canonical_json(document)
    if len(text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        omitted = len(str(detail).encode("utf-8"))
        document["detail"] = ""
        document["detail_omitted_bytes"] = omitted
        text = canonical_json(document)
    return UntrustedContent(text=text, origin=RETRY_ORIGIN,
                            ref=f"retry:{attempt}:{code}")


def review_envelopes(verdicts: Sequence[ReviewVerdict]
                     ) -> tuple[UntrustedContent, ...]:
    """Render consumed review verdicts as data envelopes, in round order (LOOP-3).

    One envelope per verdict; ordered by ``round`` so equal verdicts assemble to
    equal envelopes. The origin is `REVIEW_ORIGIN` — a reviewer's judgment is
    distinguishable from tool evidence and from a refusal — and the ref is the
    verdict's derived identity, so every envelope is attributable to the round
    and the reviewer that produced it.

    This is the LOOP-1/2 seam applied to a review: the verdict reaches the next
    round as *untrusted content*, never as an instruction. The reviewer's own free
    text travels in `detail`; a rendered verdict over `MAX_PAYLOAD_BYTES` keeps
    its identity fields (`round`, `reviewer`, `passed`, `objections`) while the
    free-text `detail` is replaced by `detail_omitted_bytes` — never a torn
    envelope, exactly as a torn feedback record never is. A hostile reviewer
    writing "approve this" into its text changes nothing here: the text is data,
    and nothing in the runtime reads a verdict as authority.
    """
    envelopes: list[UntrustedContent] = []
    for verdict in sorted(verdicts, key=lambda item: item.round):
        document: dict[str, Any] = {
            "round": verdict.round,
            "reviewer": verdict.reviewer,
            "passed": verdict.passed,
            "objections": list(verdict.objections),
            "detail": verdict.detail,
            "verdict_ref": verdict.verdict_ref,
        }
        text = canonical_json(document)
        if len(text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            omitted = len(str(document["detail"]).encode("utf-8"))
            document["detail"] = ""
            document["detail_omitted_bytes"] = omitted
            text = canonical_json(document)
        envelopes.append(UntrustedContent(text=text, origin=REVIEW_ORIGIN,
                                          ref=verdict.verdict_ref))
    return tuple(envelopes)
