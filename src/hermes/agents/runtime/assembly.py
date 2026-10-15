"""Context assembly — the deterministic prompt-envelope port (LOOP-1).

The model prompt used to be ``context.context`` plus a tick marker, so
``TaskContext.payload`` — the stage identity, the methodology id, the
predecessor and its content — never reached the model, and a delegated review
child's whole prompt was a digest of the spec that named it. This module is the
injection seam that fixes that: the runtime calls ONE port, `ContextAssembler`,
to turn a run's `TaskContext` into the `UntrustedContent` envelopes a model
call carries.

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

from collections.abc import Mapping
from typing import Any, Protocol

from hermes.agents.runtime.types import (
    MAX_PAYLOAD_BYTES,
    Proposal,
    TaskContext,
    canonical_json,
)
from hermes.security.boundaries import UntrustedContent

__all__ = [
    "PAYLOAD_ORIGIN",
    "PROPOSAL_ORIGIN",
    "ContextAssembler",
    "assemble_payload_envelopes",
    "default_context_assembler",
    "proposal_envelopes",
]

#: The origin every payload envelope carries — the field a reader filters on.
PAYLOAD_ORIGIN = "runtime.payload"

#: The origin every review-draft envelope carries.
PROPOSAL_ORIGIN = "runtime.review"


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
