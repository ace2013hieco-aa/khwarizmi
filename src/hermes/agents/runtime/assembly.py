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
from typing import Any, NamedTuple, Protocol

from hermes.agents.runtime.types import (
    MAX_PAYLOAD_BYTES,
    Proposal,
    ReviewVerdict,
    RuntimeRefusal,
    TaskContext,
    ToolFeedback,
    canonical_json,
)
from hermes.security.boundaries import UntrustedContent
from hermes.tools.capabilities.content import ContentRead, read_content

__all__ = [
    "CONTRACT_FEEDBACK_ORIGIN",
    "EVIDENCE_EXCERPT_MAX_BYTES",
    "EVIDENCE_ORIGIN",
    "OBSERVATION_ORIGIN",
    "PAYLOAD_ORIGIN",
    "PROJECT_INDEX_MAX_ENTRIES",
    "PROJECT_INDEX_ORIGIN",
    "PROPOSAL_ORIGIN",
    "REFUSAL_ORIGIN",
    "RETRY_ORIGIN",
    "REVIEW_ORIGIN",
    "TASK_ORIGIN",
    "ContextAssembler",
    "ProjectIndexChainNode",
    "ProjectIndexEntry",
    "ProjectIndexPort",
    "ProjectIndexView",
    "assemble_payload_envelopes",
    "contract_feedback_envelope",
    "default_context_assembler",
    "draft_feedback_envelope",
    "evidence_envelope",
    "feedback_envelopes",
    "project_index_envelope",
    "proposal_envelopes",
    "retry_envelope",
    "review_envelopes",
    "task_input_envelope",
]

#: The origin every payload envelope carries — the field a reader filters on.
PAYLOAD_ORIGIN = "runtime.payload"

#: The origin the operator's task input carries (OPS-7): the question and the
#: refs the task supplied. It is deliberately neither ``runtime.payload`` (the
#: stage's structural identity) nor ``runtime.tick`` (loop state): a reader can
#: tell operator-supplied text from both.
TASK_ORIGIN = "runtime.task"

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

#: The origin a **contract-shape** refusal carries: the previous reply was
#: refused by output validation and the next call is asked to repair it. Two
#: renderers share it because the signal is the same one — OPS-15's
#: `contract_feedback_envelope` (the whole reply failed the declared contract
#: before any draft existed, re-asked inside the same tick) and OPS-5Z2's
#: `draft_feedback_envelope` (a draft was refused after the reply was parsed,
#: carried into the next tick). Distinct from `RETRY_ORIGIN` so an operator can
#: tell the LOOP-4 rationale retry from a contract refusal. Same discipline:
#: data the next attempt reads, never an instruction it obeys.
CONTRACT_FEEDBACK_ORIGIN = "runtime.contract_feedback"

#: The origin the OPS-18 project index carries: a bounded, content-free list of
#: ids that exist in this project. It is data the model reads for orientation,
#: never an instruction and never an admissibility claim — the gateway remains
#: the only validator.
PROJECT_INDEX_ORIGIN = "runtime.project_index"

#: The origin the OPS-5L admitted-evidence envelope carries: the one evidence
#: ref the run admitted, and its artifact id. It is a run-level fact, distinct
#: from the predecessor's content (`runtime.payload`) and from the operator's
#: task input (`runtime.task`); the gateway remains the only validator.
EVIDENCE_ORIGIN = "runtime.evidence"

#: The hard entry cap of one project index. Entries are ordered before the cap
#: is applied; the tail is the truncation priority. The renderer additionally
#: holds the canonical envelope to `MAX_PAYLOAD_BYTES`.
PROJECT_INDEX_MAX_ENTRIES = 40

#: The most artifact bytes the evidence envelope will try to excerpt before
#: the whole canonical document is trimmed to `MAX_PAYLOAD_BYTES`. This is a
#: starting point, never a promise: the binary search below lowers it until the
#: escaped envelope fits, so the shared 4 KiB bound is the only real bound.
EVIDENCE_EXCERPT_MAX_BYTES = 3072


class ProjectIndexEntry(NamedTuple):
    """One index entry: the id, what kind of id it is, and a one-line label.

    No content field exists on purpose. An entry cannot carry an artifact body,
    node content, rationale, scope text or another project's row because there
    is nowhere to put it.

    A ``NamedTuple`` rather than a dataclass: this module is purity-tested on an
    exact import set (LOOP-1), and ``typing`` is already one of its imports. The
    semantics are the ones the design needs — immutable, ordered, attribute
    access — with no new dependency for a module that must hold none.
    """

    id: str
    kind: str
    label: str


class ProjectIndexChainNode(NamedTuple):
    """One chain node offered by the run's in-memory store.

    ``project_id`` travels with the node so the reader can enforce the project
    bound again, even though the driver already filters the store. The reader
    never queries a table for these: the store is derived working state (B-5),
    absent in a fresh process.
    """

    project_id: str
    node_id: str
    kind: str


class ProjectIndexView(NamedTuple):
    """The adapter's final list plus the true pre-truncation total.

    ``entries`` are already ordered and entry-capped by the adapter; ``total``
    counts every entry the project held, so the renderer can report a truthful
    ``omitted`` marker after its byte cap as well.
    """

    entries: tuple[ProjectIndexEntry, ...]
    total: int


class ProjectIndexPort(Protocol):
    """Read one project's index — the composition-injected read seam.

    The runtime and the handler call this port; they do not import persistence.
    A provider that raises fails the stage: a silently missing index would be
    indistinguishable from an empty project.
    """

    def __call__(self, project_id: str,
                 chain_nodes: Sequence[ProjectIndexChainNode],
                 ) -> ProjectIndexView: ...


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


def project_index_envelope(project_id: str, view: ProjectIndexView,
                           ) -> UntrustedContent:
    """Render one bounded project index as a ``runtime.project_index`` envelope.

    The document is exactly ``{"entries": [{"id", "kind", "label"}, ...],
    "omitted": N}``. There is no content field. ``omitted`` is the true count
    of entries not shown: the adapter has already applied the 40-entry cap, and
    this renderer applies the same 4 KiB bound every other prompt envelope
    uses, dropping entries from the tail until the canonical document fits. A
    truncated index therefore never looks complete.

    Pure and deterministic: no clock, no I/O, no ambient state. The values are
    stored ids/types and closed-vocabulary labels, but they still enter as
    untrusted content — data the model reads, never instructions it obeys and
    never an admissibility claim.
    """
    entries = list(view.entries)
    while True:
        document = {
            "entries": [
                {"id": entry.id, "kind": entry.kind, "label": entry.label}
                for entry in entries
            ],
            "omitted": max(0, int(view.total) - len(entries)),
        }
        text = canonical_json(document)
        if len(text.encode("utf-8")) <= MAX_PAYLOAD_BYTES:
            break
        if not entries:
            break
        entries.pop()
    return UntrustedContent(
        text=text,
        origin=PROJECT_INDEX_ORIGIN,
        ref=f"{project_id}:project_index")


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


def task_input_envelope(
    *,
    task_id: str,
    question: str,
    external_refs: Mapping[str, str],
    admission_refs: Sequence[str],
) -> UntrustedContent:
    """Render the operator's task input as one ``runtime.task`` envelope.

    The question is free text; the refs are **ids**, never fetched content —
    there is nothing fetched at projection time. The document is canonical, so
    equal inputs assemble to equal envelopes, and every value enters as
    untrusted content: data the model reads, never an instruction it obeys.
    The origin is `TASK_ORIGIN`, which keeps operator text distinguishable
    from the stage payload and from loop state.

    This is the OPS-7 seam: the driver projects the task input into the run's
    context, and the default assembler renders it beside every other payload.
    """
    return _document_envelope(
        TASK_ORIGIN,
        f"{task_id}:task_input",
        {
            "question": question,
            "external_refs": dict(external_refs),
            "admission_refs": sorted(admission_refs),
        },
    )


def _decode_prefix(raw: bytes, limit: int) -> str:
    """Decode the longest clean UTF-8 prefix of ``raw[:limit]``.

    A cut through a multi-byte character is trimmed back to the last complete
    character, so the returned text is always a contiguous prefix of the bytes
    rather than a replacement-smeared approximation. Deterministic and pure.
    """
    chunk = raw[:limit]
    while chunk:
        try:
            return chunk.decode("utf-8")
        except UnicodeDecodeError as exc:
            chunk = chunk[:exc.start]
    return ""


def _excerpt_document(read: ContentRead, raw: bytes,
                      limit: int) -> dict[str, Any]:
    """One excerpt document: the text, whether content was left out, and the
    artifact's true size (never the excerpt's).

    OPS-5Z3: the text is a prefix of the artifact's *content*, not of its bytes.
    A 3 KB prefix of a 33 KB OpenAlex record is a title and a list of author
    affiliations — the abstract begins at byte 31,556 — so bounding the bytes
    gave the stage a prompt that could not support a claim about the source
    while looking as though it could. The content is extracted first, then
    bounded.

    OPS-5Z5: a read that failed says so. ``read`` carries the state and
    ``detail`` names what could not be read.

    OPS-5Z Group C: the excerpt's ``read`` field is the three-state vocabulary
    (``content`` / ``fallback`` / ``unreadable``). A fallback's or an
    unreadable read's bytes *are* rendered — a model may read a blob, and
    dropping the source was a cost with no safety benefit — but they are
    labelled, so neither the model nor a consumer can mistake them for the
    artifact's prose. Only a read with no text at all renders none.
    """
    content = read.text
    encoded = content.encode("utf-8")
    # Two different omissions, and a reader needs to tell them apart:
    # ``extracted`` — the text was *selected* from the artifact, so fields the
    # artifact carries are absent even when nothing was cut; ``truncated`` — the
    # selected text itself did not fit the bound. Reporting only ``truncated``
    # would say "false" over a 33 KB record reduced to its abstract, which reads
    # as "you are seeing everything". A fallback is not an extraction; a
    # partial read (title without its abstract) is.
    extracted = (read.is_content and bool(content)
                 and content != raw.decode("utf-8", "replace"))
    if len(encoded) <= limit:
        document: dict[str, Any] = {
            "text": content, "truncated": False, "extracted": extracted,
            "bytes": len(raw), "read": read.state.value,
            "format": read.format}
        if not read.is_content or read.detail:
            document["detail"] = read.detail
            document["fields"] = list(read.fields)
        return document
    document = {
        "text": _decode_prefix(encoded, limit),
        "truncated": True,
        "extracted": extracted,
        "bytes": len(raw),
        "read": read.state.value,
        "format": read.format,
    }
    if not read.is_content or read.detail:
        document["detail"] = read.detail
        document["fields"] = list(read.fields)
    return document


def evidence_envelope(*, task_id: str,
                      evidence_ref: str,
                      artifact_bytes: bytes | None = None,
                      artifact_format: str = "",
                      read_failure: str = "",
                      ) -> UntrustedContent:
    """Render the run's admitted evidence ref as a ``runtime.evidence`` envelope.

    OPS-5L: the EVIDENCE stage must know the ref the run admitted. Without
    ``artifact_bytes`` the document is exactly ``{"evidence_ref":
    "evidence:<artifact_id>", "artifact_id": "<artifact_id>"}`` — the ref, its
    artifact id and nothing else.

    OPS-5Z3: a stage that must describe or quote the source cannot do so from
    an id. When the caller supplies the artifact's bytes, the document gains a
    bounded ``excerpt``: the clean UTF-8 prefix, whether bytes were left out,
    and the artifact's true size. The whole canonical document — not just the
    excerpt — is held to the shared ``MAX_PAYLOAD_BYTES`` bound by trimming the
    prefix until it fits; a truncated excerpt says so. The bytes enter as
    untrusted content in the same origin-labelled document, and are never
    copied into an event payload.

    The ref must already be canonical. The caller is the live methodology
    driver, whose selector canonicalises the admitted proposal's raw payload
    before it gets here; a non-canonical ref is a programming error, refused
    loudly rather than rendered as a half-document. Pure and deterministic: the
    bytes are an argument, never a read, so equal inputs assemble to equal
    envelopes.

    OPS-5Z5: ``read_failure`` is the caller's account of a wired read that
    returned no bytes. Without it, a missing artifact and an intentionally
    ref-only envelope look identical — the silent caveat the audit found. The
    OPS-5L ref-only shape is unchanged when neither argument is supplied.

    OPS-5Z Group C: ``artifact_format`` is the shape the fetch path declared
    for these bytes. The read dispatches on it; the envelope never guesses.
    The excerpt's ``read`` is the three-state vocabulary, and the read is
    computed once for the whole binary search rather than once per probe.
    """
    prefix = "evidence:"
    ref = str(evidence_ref)
    if not ref.startswith(prefix) or len(ref) == len(prefix):
        raise ValueError(
            "evidence_envelope requires a canonical "
            "'evidence:<artifact_id>' ref")
    artifact_id = ref[len(prefix):]
    document: dict[str, Any] = {"evidence_ref": ref,
                                "artifact_id": artifact_id}
    if artifact_bytes is not None:
        read = read_content(artifact_bytes, format=artifact_format)
        # Binary-search the largest prefix whose escaped document fits. The
        # ref and id are fixed, and the empty-excerpt document always fits,
        # so a candidate exists; `best` is still defaulted for the type.
        low, high = 0, min(len(artifact_bytes), EVIDENCE_EXCERPT_MAX_BYTES)
        best: dict[str, Any] | None = None
        while low <= high:
            middle = (low + high) // 2
            candidate = dict(
                document,
                excerpt=_excerpt_document(read, artifact_bytes, middle))
            if len(canonical_json(candidate).encode("utf-8")) <= MAX_PAYLOAD_BYTES:
                best = candidate
                low = middle + 1
            else:
                high = middle - 1
        document = best if best is not None else dict(
            document,
            excerpt={"text": "", "truncated": True,
                     "bytes": len(artifact_bytes), "read": read.state.value,
                     "format": read.format})
    elif read_failure:
        # A wired read that returned nothing is a fact the stage must see:
        # omitting the excerpt entirely is the same document as a ref-only
        # envelope, and the model cannot tell "no source" from "not read".
        document["excerpt"] = {
            "text": "", "read": "unreadable", "detail": str(read_failure)}
    return _document_envelope(
        EVIDENCE_ORIGIN,
        f"{task_id}:evidence",
        document,
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


def _bounded_refusal_text(document: dict[str, Any], detail: str) -> str:
    """The one bounding rule every refusal envelope applies (OPS-15, OPS-5Z2).

    Canonical JSON, and — when that would exceed `MAX_PAYLOAD_BYTES` — the
    free-text `detail` is replaced by its byte length under
    `detail_omitted_bytes`, keeping every identity field. A torn envelope is never
    emitted. Shared rather than copied so "escaped the way OPS-15 escapes it" is a
    structural fact: a second renderer cannot drift from the first.
    """
    text = canonical_json(document)
    if len(text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        omitted = len(str(detail).encode("utf-8"))
        document["detail"] = ""
        document["detail_omitted_bytes"] = omitted
        text = canonical_json(document)
    return text


def contract_feedback_envelope(code: str, detail: str, *,
                               attempt: int) -> UntrustedContent:
    """Render a contract-shape refusal as data for the next attempt (OPS-15).

    Same shape and bounds as `retry_envelope`, with its own origin and ref: a
    whole-reply output-validation refusal is a different signal from the LOOP-4
    rationale retry, and an operator reading the prompt should be able to tell
    them apart. The content is the refusal's code and detail only — never the
    raw model excerpt, the normalized request or the ledger. The detail is
    system-generated but may echo model output, so it is untrusted data: the
    envelope is the boundary, and nothing in the runtime reads it as an
    instruction.

    Pure and deterministic; an oversized detail keeps the code and attempt and
    carries `detail_omitted_bytes` instead of a torn body.
    """
    document: dict[str, Any] = {"attempt": attempt, "code": code, "detail": detail}
    return UntrustedContent(
        text=_bounded_refusal_text(document, detail),
        origin=CONTRACT_FEEDBACK_ORIGIN,
        ref=f"contract_feedback:{attempt}:{code}")


def draft_feedback_envelope(refusal: RuntimeRefusal, *,
                            index: int) -> UntrustedContent:
    """Render a **refused draft** as data for the next tick's model call (OPS-5Z2).

    The runtime refused the draft and told nobody who could act on it: the refusal
    went into `state.refusals` and the `PROPOSAL_REFUSED` event, and the next tick
    re-asked the identical question, so the model spent its remaining ticks making
    the same mistake. This carries the refusal's code, the detail that names what
    was wrong (the refused payload, the citation that names nothing admitted) and
    the kind of draft it was, so the next tick's proposal is informed.

    Same origin and same bounding rule as `contract_feedback_envelope` — both are
    "your reply was refused; here is what to repair", and a model or an operator
    should not have to learn two signal shapes. The document differs because the
    identity differs: a draft refusal belongs to a *tick* and a draft, not to a
    whole-reply *attempt*, and says so instead of overloading `attempt`.

    Pure and deterministic; `index` is the refusal's position in the pending
    queue, which is what makes the ref unique when one reply produced two refused
    drafts with the same code.
    """
    document: dict[str, Any] = {
        "tick": refusal.tick,
        "kind": refusal.kind,
        "code": refusal.code,
        "detail": refusal.detail,
    }
    return UntrustedContent(
        text=_bounded_refusal_text(document, refusal.detail),
        origin=CONTRACT_FEEDBACK_ORIGIN,
        ref=f"draft_feedback:{refusal.tick}:{index}:{refusal.code}")


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
