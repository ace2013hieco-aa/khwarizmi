"""OPS-5Z2 — a refused draft tells the model what to fix.

Run 40 reached five of nine stages and stopped at `EVIDENCE` because the model
cited `evidence:obs-sars-covid-40-…` — a ref it invented — where the admitted
artifact was required. Its `OBSERVATION` stage had `max_ticks: 3` and the model
used more than one tick, and the earlier tick's refusal was never in front of it:
`_emit_drafts` appended the refusal to `state.refusals`, emitted
`PROPOSAL_REFUSED`, and the next tick asked the *same* question.

The battery pins, in order: the refusal a malformed payload produces reaches the
next tick's prompt as an origin-marked, canonically escaped envelope; a citation
the spine refuses carries the refused ref; a clean tick's prompt is unchanged
(zero envelopes, tick marker only — the LOOP baseline pins the corpus-wide
bytes); the note appears at most once per refused draft and the tick budget still
stops a model that fails every time; a gather tick is untouched; and a refusal
the model cannot repair is never re-prompted.

Authority is untouched and that is asserted, not assumed: every envelope here is
untrusted content, and nothing in the runtime reads a refusal as an instruction.
A green battery is not evidence about any hypothesis.
"""

from __future__ import annotations

import json
from typing import Any

from hermes.agents.runtime.assembly import (
    CONTRACT_FEEDBACK_ORIGIN,
    draft_feedback_envelope,
)
from hermes.agents.runtime.checkpoint import InMemoryCheckpointStore
from hermes.agents.runtime.run import ACTIONABLE_SPINE_CODES
from hermes.agents.runtime.types import (
    MALFORMED_PAYLOAD,
    MAX_PAYLOAD_BYTES,
    PROPOSAL,
    RATIONALE,
    ROLE,
    RuntimeRefusal,
    canonical_json,
)
from hermes.core.intents import Intent, IntentRejectedError
from hermes.security.boundaries import UntrustedContent
from hermes.tools.models.router import ModelRefusal
from tests.test_loop4_hygiene import (
    _Applied,
    _Capabilities,
    _context,
    _draft,
    _Model,
    _profile,
    _runtime,
)

# A payload the runtime's draft schema refuses: a list where a mapping belongs.
BAD_PAYLOAD = {
    "proposals": [{"kind": "INSERT_TASK", "rationale": "because",
                   "payload": ["not-a-mapping"]}],
}


def _notes(prompt: tuple[Any, ...]) -> list[Any]:
    return [part for part in prompt if part.origin == CONTRACT_FEEDBACK_ORIGIN]


def _documents(prompt: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [json.loads(part.text) for part in _notes(prompt)]


# ═══════════════════ falsifier 1 — a malformed payload reaches the next tick ══


def test_a_refused_draft_reaches_the_next_ticks_prompt() -> None:
    """The refusal is data the next tick reads, not a line in the report.

    Tick 1 proposes a list where the draft schema requires a mapping;
    `_validate_drafts` refuses it and records it. Tick 2 used to be asked the
    identical question — the refusal existed only in `state.refusals` and the
    `PROPOSAL_REFUSED` event. It now carries the refusal: code, detail, and the
    kind of draft that was refused, origin-labelled and canonically encoded.
    """
    lead = _profile("lead", max_ticks=2)
    model = _Model({"lead": [BAD_PAYLOAD, _draft()]})
    runtime = _runtime(model, profiles={"lead": lead})

    result = runtime.run("lead", _context())

    assert result.state == "SUCCEEDED"
    assert len(model.calls) == 2
    # The first attempt had nothing to be told: a clean start is still clean.
    assert _notes(model.prompt_for("lead", 0)) == []

    notes = _notes(model.prompt_for("lead", 1))
    assert len(notes) == 1
    assert isinstance(notes[0], UntrustedContent)
    assert notes[0].origin == CONTRACT_FEEDBACK_ORIGIN
    assert notes[0].ref == f"draft_feedback:1:0:{MALFORMED_PAYLOAD}"
    assert json.loads(notes[0].text) == {
        "tick": 1,
        "kind": "INSERT_TASK",
        "code": MALFORMED_PAYLOAD,
        "detail": "proposal 0 payload is list, not a mapping",
    }
    # Read as data, never re-emitted as an instruction: the envelope is the only
    # way the refusal crosses the boundary, and it carries no raw model excerpt.
    assert result.refusal_codes() == (MALFORMED_PAYLOAD,)


def test_the_envelope_escapes_a_detail_that_quotes_the_model() -> None:
    """OPS-15's escaping, applied to a draft refusal: canonical JSON, round-trip.

    The detail is system-generated but may quote model output (a payload key, a
    ref). It travels inside a JSON document, so a quote or a newline in it is
    escaped by the encoding rather than by hand.
    """
    detail = 'proposal 0 declares unknown keys: ["a\\"b\\n"] — ref \'x:y\''
    refusal = RuntimeRefusal(code=MALFORMED_PAYLOAD, detail=detail, tick=3,
                             kind="INSERT_TASK", model_actionable=True)

    envelope = draft_feedback_envelope(refusal, index=1)

    assert envelope.text == canonical_json({
        "tick": 3, "kind": "INSERT_TASK", "code": MALFORMED_PAYLOAD,
        "detail": detail})
    assert json.loads(envelope.text)["detail"] == detail


# ═══════════════════ falsifier 2 — a citation that names nothing admitted ═════


class _SpineRefuser:
    """An Orchestration API that refuses the first intent with a spine code."""

    def __init__(self, *, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        self.calls: list[Intent] = []

    def __call__(self, intent: Intent) -> Any:
        self.calls.append(intent)
        if len(self.calls) == 1:
            error = IntentRejectedError(intent.kind, self.reason)
            # `GatewayRejection` carries the code as an attribute; the plane
            # reads it as a value, never by parsing the message.
            error.code = self.code  # type: ignore[attr-defined]
            raise error
        return _Applied(entity_id="ent_0002", duplicate=False)


INVENTED = "evidence:obs-sars-covid-40-brazil-india-cases-sep1-2020"


def _citation() -> dict[str, Any]:
    return {
        "proposals": [{
            "kind": "EVIDENCE_TRANSITION",
            "rationale": "cite the observation I recorded",
            "payload": {"evidence_artifact_ref": INVENTED,
                        "from_state": "SUPPORTED",
                        "to_state": "ROBUST",
                        "rationale": "cite the observation I recorded"},
        }],
    }


def test_a_citation_that_names_nothing_admitted_carries_its_ref() -> None:
    """The refused ref travels to the next tick; that is what the model must fix.

    Run 40's shape: the draft cites an observation handle where an admitted
    artifact was required, the spine refuses it (`EVIDENCE_REF`), and the run
    used to keep asking without ever saying which ref was refused.
    """
    # `converged` rather than `proposals_raised`: a spine refusal still returns a
    # draft digest (`_emit_intent` always builds the `Proposal`), so
    # `proposals_raised` would end the stage on the refused draft and the next
    # tick — the whole subject here — would never run.
    lead = _profile("lead", max_ticks=2, stop_when="converged",
                    kinds=("EVIDENCE_TRANSITION",))
    applier = _SpineRefuser(
        code="EVIDENCE_REF",
        reason=f"evidence artifact 'obs-sars-covid-40-…' (from {INVENTED!r}) "
               f"not in project 'p1'")
    model = _Model({"lead": [_citation(),
                             _draft(kind="EVIDENCE_TRANSITION",
                                    payload={"evidence_artifact_ref": INVENTED})]})
    runtime = _runtime(model, profiles={"lead": lead}, applier=applier)

    runtime.run("lead", _context())

    documents = _documents(model.prompt_for("lead", 1))
    assert len(documents) == 1
    assert INVENTED in documents[0]["detail"]
    # The plane's closed vocabulary names the refusal `PROPOSAL`; the spine's own
    # code stays visible inside the detail rather than being dropped.
    assert documents[0]["code"] == PROPOSAL
    assert "spine code EVIDENCE_REF" in documents[0]["detail"]
    assert documents[0]["kind"] == "EVIDENCE_TRANSITION"


def test_a_governance_refusal_from_the_spine_is_not_re_prompted() -> None:
    """The split is the *spine's* code, not the plane's: same code, no feedback.

    Both refusals are recorded as `PROPOSAL` by the plane's closed vocabulary.
    Only the citation one is the model's to repair, so only it reaches a prompt —
    a governance denial would spend a tick on a question whose answer cannot move.
    """
    assert "EVIDENCE_REF" in ACTIONABLE_SPINE_CODES
    assert PROPOSAL not in ACTIONABLE_SPINE_CODES

    lead = _profile("lead", max_ticks=2, stop_when="converged",
                    kinds=("EVIDENCE_TRANSITION",))
    applier = _SpineRefuser(code=PROPOSAL,
                            reason="the proposal was already decided differently")
    model = _Model({"lead": [_citation(),
                             _draft(kind="EVIDENCE_TRANSITION",
                                    payload={"evidence_artifact_ref": INVENTED})]})
    runtime = _runtime(model, profiles={"lead": lead}, applier=applier)

    result = runtime.run("lead", _context())

    assert result.refusal_codes() == (PROPOSAL,)
    assert _notes(model.prompt_for("lead", 1)) == []


# ═══════════════════ falsifier 3 — a clean tick is byte-identical ═════════════


def test_a_clean_tick_carries_only_the_tick_marker() -> None:
    """Nothing is appended when no draft was refused.

    The prompt of a run that is working must not move: an empty queue adds no
    envelope, so the first prompt is exactly the assembler's output plus the tick
    marker — here the context declares no envelopes, so that is one part. The
    corpus-wide guard is `test_loop_baseline`'s pinned prompt bytes and trace
    digests, which run unchanged.
    """
    lead = _profile("lead", max_ticks=2)
    model = _Model({"lead": [_draft()]})
    runtime = _runtime(model, profiles={"lead": lead})

    result = runtime.run("lead", _context())

    assert result.state == "SUCCEEDED"
    prompt = model.prompt_for("lead", 0)
    assert [part.origin for part in prompt] == ["runtime.tick"]
    assert prompt[0].text == "tick 1 of 2"


# ═══════════════════ falsifier 4 — once per refusal, and the budget still bites


def _unknown_keys(name: str) -> dict[str, Any]:
    return {"proposals": [{"kind": "INSERT_TASK", "rationale": "because",
                           name: 1}]}


def test_the_note_appears_once_per_refusal_and_the_tick_budget_still_stops() -> None:
    """Three refusals, three prompts, one note each — and the run stops.

    A queue that was never cleared would re-inject tick 1's refusal into tick 3
    (stale feedback, a growing prompt); one cleared too eagerly would leave tick 3
    silent. Each prompt carries exactly the *previous* tick's refusal.
    """
    lead = _profile("lead", max_ticks=3)
    model = _Model({"lead": [_unknown_keys("bogus1"), _unknown_keys("bogus2"),
                             _unknown_keys("bogus3")]})
    runtime = _runtime(model, profiles={"lead": lead})

    result = runtime.run("lead", _context())

    assert len(model.calls) == 3
    assert len(result.refusals) == 3
    assert _notes(model.prompt_for("lead", 0)) == []
    second = _documents(model.prompt_for("lead", 1))
    third = _documents(model.prompt_for("lead", 2))
    assert len(second) == 1 and "bogus1" in second[0]["detail"]
    assert len(third) == 1 and "bogus2" in third[0]["detail"]
    assert "bogus1" not in third[0]["detail"]
    # The stage's tick budget is still the bound: a model that fails every time
    # is not re-asked a fourth time.
    assert result.state == "SUCCEEDED"
    assert result.termination == "TICK_LIMIT"


def test_the_in_tick_retry_keeps_the_note_it_did_not_produce() -> None:
    """Two model calls in one tick are the same question, so both carry the note.

    A contract-shape refusal re-asks inside the tick (OPS-15). Dropping the
    previous tick's draft refusal there would make the re-asked question
    amnesiac about the thing it is being asked to repair — the LOOP-4 E5 rule.
    The note is scoped to the *tick*, not to the call.
    """
    lead = _profile("lead", max_ticks=2, max_model_calls_per_tick=2)
    model = _Model({"lead": [
        BAD_PAYLOAD,
        ModelRefusal(code=MALFORMED_PAYLOAD, detail="kind missing",
                     contract_feedback=True),
        _draft(),
    ]})
    runtime = _runtime(model, profiles={"lead": lead})

    runtime.run("lead", _context())

    assert len(model.calls) == 3
    retry = model.prompt_for("lead", 2)
    assert [part.origin for part in retry].count(
        CONTRACT_FEEDBACK_ORIGIN) == 2  # the tick-1 draft note and the retry note
    assert [document["code"] for document in _documents(retry)] == [
        MALFORMED_PAYLOAD, MALFORMED_PAYLOAD]


# ═══════════════════ falsifier 5 — a gather tick is unaffected ════════════════


def test_a_gather_tick_queues_nothing() -> None:
    """A tool call and no proposal was never refused, so nothing is owed."""
    lead = _profile("lead", max_ticks=2, capabilities=("source_fetch",),
                    fields=("proposals", "tool_calls"))
    gather = {"tool_calls": [{"capability_id": "source_fetch",
                              "arguments": {"url": "https://example.test/x"},
                              "rationale": "gather before proposing"}]}
    model = _Model({"lead": [gather, _draft()]})
    capabilities = _Capabilities()
    runtime = _runtime(model, profiles={"lead": lead},
                       capabilities=capabilities)

    result = runtime.run("lead", _context())

    assert result.state == "SUCCEEDED"
    assert len(capabilities.requests) == 1
    prompt = model.prompt_for("lead", 1)
    assert _notes(prompt) == []
    # The gather tick's own result is still what the next tick reads.
    assert [part.origin for part in prompt].count("runtime.observation") == 1


# ═══════════════════ the marker: site-set, durable, backward compatible ═══════


def test_a_draft_refusal_the_model_cannot_repair_is_not_queued() -> None:
    """The authority branch opts out; every other draft site is the model's.

    `refuses_by_authority` refuses a kind the profile may never propose — an
    internal-only kind, here — and a re-prompt cannot change the partition.
    """
    lead = _profile("lead", max_ticks=2)
    forbidden = {"proposals": [{"kind": "CONTRADICTION_RESOLUTION",
                                "rationale": "resolve it",
                                "payload": {}}]}
    model = _Model({"lead": [forbidden, _draft()]})
    runtime = _runtime(model, profiles={"lead": lead})

    result = runtime.run("lead", _context())

    # An internal-only kind is a partition breach (`ROLE`); a kind declared in
    # `requires_human_for` is `PROPOSAL`. Neither is the model's to repair.
    assert result.refusal_codes() == (ROLE,)
    assert not result.refusals[0].model_actionable
    assert _notes(model.prompt_for("lead", 1)) == []


def test_a_pending_refusal_is_checkpointed_until_it_is_consumed() -> None:
    """A crash between the refused tick and its consumer must not forget it."""
    lead = _profile("lead", max_ticks=2)
    store = InMemoryCheckpointStore()
    context = _context()
    run_id = context.resolved_run_id("lead")
    seen: list[Any] = []
    holder: list[_Model] = []

    def on_call(_request: Any) -> None:
        # The second call is tick 2: the store still holds tick 1's checkpoint,
        # which is the one written between the refusal and its consumer.
        if len(holder[0].calls) == 2:
            seen.append(store.get(run_id))

    model = _Model({"lead": [BAD_PAYLOAD, _draft()]}, on_call=on_call)
    holder.append(model)
    runtime = _runtime(model, profiles={"lead": lead}, checkpoints=store)
    runtime.run("lead", context)

    after_tick_one = seen[0]
    assert after_tick_one is not None
    assert [refusal.code for refusal in after_tick_one.draft_feedback] == [
        MALFORMED_PAYLOAD]
    assert after_tick_one.draft_feedback[0].model_actionable is True
    # And the terminal checkpoint has consumed it: the queue is not a second,
    # slower-growing history.
    final = store.get(run_id)
    assert final is not None and final.draft_feedback == ()


def test_the_marker_round_trips_and_a_legacy_mapping_defaults_to_false() -> None:
    """A record written before this marker existed is still readable, and is not
    silently upgraded into a re-prompt."""
    legacy = RuntimeRefusal.from_mapping({"code": MALFORMED_PAYLOAD,
                                          "detail": "written before OPS-5Z2"})
    assert legacy.model_actionable is False

    marked = RuntimeRefusal(code=PROPOSAL, detail="citation", tick=2,
                            kind="EVIDENCE_TRANSITION", model_actionable=True)
    assert RuntimeRefusal.from_mapping(marked.to_mapping()) == marked


def test_a_payload_over_the_cap_is_queued_too() -> None:
    """The bound a draft can exceed is the model's to fix: shrink it."""
    lead = _profile("lead", max_ticks=2)
    oversized = {"proposals": [{
        "kind": "INSERT_TASK", "rationale": "because",
        "payload": {"goal": "g" * MAX_PAYLOAD_BYTES}}]}
    model = _Model({"lead": [oversized, _draft()]})
    runtime = _runtime(model, profiles={"lead": lead})

    result = runtime.run("lead", _context())

    assert RATIONALE in result.refusal_codes()
    documents = _documents(model.prompt_for("lead", 1))
    queued = [document for document in documents if document["code"] == RATIONALE]
    assert len(queued) == 1
    assert "over the" in queued[0]["detail"]


def test_the_envelope_keeps_identity_and_drops_an_oversized_detail() -> None:
    """The 4 KiB rule is shared with OPS-15, not re-implemented with a corner."""
    detail = "x" * (MAX_PAYLOAD_BYTES + 16)
    refusal = RuntimeRefusal(code=MALFORMED_PAYLOAD, detail=detail, tick=9,
                             kind="INSERT_TASK", model_actionable=True)

    envelope = draft_feedback_envelope(refusal, index=0)

    assert len(envelope.text.encode("utf-8")) <= MAX_PAYLOAD_BYTES
    document = json.loads(envelope.text)
    assert document["code"] == MALFORMED_PAYLOAD
    assert document["tick"] == 9 and document["kind"] == "INSERT_TASK"
    assert document["detail"] == ""
    assert document["detail_omitted_bytes"] == len(detail.encode("utf-8"))


def test_a_spine_refusal_does_not_end_a_proposals_raised_stage() -> None:
    """A refused draft raised nothing, so the stage gets its next tick.

    This replaces the OPS-5Z2 pin that asserted the defect. `_emit_drafts` still
    returns a digest for every draft it hands the spine, but `raised` now counts
    **admitted/duplicate** proposals. The first citation is refused
    (`EVIDENCE_REF`); the stage continues, the next tick's prompt carries the
    refusal note, and the second citation — which the applier admits — ends the
    stage through the same `proposals_raised` policy. Run 40's shape, on the
    runtime side.
    """
    lead = _profile("lead", max_ticks=3, kinds=("EVIDENCE_TRANSITION",))
    store = InMemoryCheckpointStore()
    context = _context()
    applier = _SpineRefuser(code="EVIDENCE_REF", reason=f"bad ref {INVENTED}")
    model = _Model({"lead": [_citation(),
                             _draft(kind="EVIDENCE_TRANSITION",
                                    payload={"evidence_artifact_ref": INVENTED})]})
    runtime = _runtime(model, profiles={"lead": lead}, applier=applier,
                       checkpoints=store)

    result = runtime.run("lead", context)

    assert len(model.calls) == 2, (
        "the refused draft must not consume the stage's ticks")
    assert result.termination == "STOP_WHEN"
    assert result.refusal_codes() == (PROPOSAL,)
    documents = _documents(model.prompt_for("lead", 1))
    assert len(documents) == 1
    assert INVENTED in documents[0]["detail"]
    assert documents[0]["code"] == PROPOSAL
    final = store.get(context.resolved_run_id("lead"))
    assert final is not None
    assert final.draft_feedback == (), (
        "the note was read by the tick it was queued for")


def test_the_queue_holds_only_what_a_draft_site_queued() -> None:
    """`refuse()` never auto-queues: a tool-phase refusal stays out of the slot."""
    from hermes.agents.runtime.run import _RunState

    state = _RunState(profile="lead")
    unmarked = state.refuse(MALFORMED_PAYLOAD, "a tool call needs a capability_id",
                            tick=1)
    state.queue_draft_feedback(unmarked)
    assert state.draft_feedback == []

    marked = state.refuse(RATIONALE, "payload over the cap", tick=1,
                          model_actionable=True)
    state.queue_draft_feedback(marked)
    assert [item.code for item in state.draft_feedback] == [RATIONALE]
    # One history, one queue: the refusal is recorded once either way.
    assert [item.code for item in state.refusals] == [MALFORMED_PAYLOAD, RATIONALE]
