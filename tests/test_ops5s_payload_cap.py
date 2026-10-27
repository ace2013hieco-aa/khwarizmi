"""OPS-5S — the 4 KiB cap a model cannot see.

Run 33 admitted nothing: four proposals in one run, every one refused

    RATIONALE: the model proposal exceeded the 4096-byte cap (4656 bytes)

The number was chosen before any model had written against it, by analogy with
the journal's event-payload cap — and a proposal is not a journal row. Two
defects came out of that analogy, and this file pins both:

1. **The bound measured the rationale twice.** `_proposal` read the rationale
   out of `structured` into `rationale_text`, then serialised both. A 2288-byte
   reply measured 4504 bytes; 4356 of them were the same 2178-byte rationale
   counted twice. So the prompt's "the whole reply must be at most 4096 bytes"
   was false by a factor of ~2: the largest reply that could fit was ~2.3 KB.

2. **The cap was not the journal's.** The payload that must fit 4096 bytes is
   the *derived intent payload*, checked per draft in `_emit_drafts`. Raising
   the reply bound does not touch it, which is what keeps a runaway proposal
   refusing (§5.5) while a verbose one gets through.

What is pinned here, in the charter's order: the new bound and its arithmetic,
a 5 KB proposal accepted, twice the bound still refused, the refusal naming the
actual size and the bound, the rationale charged once, the payload bound
unchanged, and the contract stating both bounds to the model.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import hermes.agents.runtime.run as run_module
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import output_contract_for
from hermes.agents.runtime.types import (
    MAX_PAYLOAD_BYTES,
    RATIONALE,
    TaskStatus,
    Termination,
)
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import (
    MAX_PROPOSAL_BYTES,
    FieldSpec,
    ModelArtifactOverflow,
    OutputContract,
    _canonical_bytes,
    _contract_mapping,
    _without_rationale,
)
from tests.test_agent_runtime import (
    ScriptedModel,
    _one_tick,
    _proposal,
    _runtime,
)
from tests.test_model_plane import (
    ScriptedProvider,
    _profile,
    _request,
    _response,
    _router,
)

PROFILE = "planner"

#: The four sizes run 33 wrote, in the order it wrote them (charter §1).
RUN_33_SIZES = (4656, 5666, 4873, 5221)

#: The stage's contract shape: a short structured payload and long prose.
TRANSITION_CONTRACT = OutputContract(
    name="evidence_transition",
    fields=(
        FieldSpec("kind", "string"),
        FieldSpec("rationale", "string"),
        FieldSpec("payload", "object", required=False),
    ),
    kind_field="kind",
    rationale_field="rationale",
    proposable_kinds=("EVIDENCE_TRANSITION",),
)

TRANSITION_PAYLOAD = {"evidence_ref": "art:9f2c", "state": "RATIFIED"}


def _reply(target_bytes: int) -> tuple[str, int]:
    """A run-33-shaped reply of exactly about `target_bytes` UTF-8 bytes.

    The structured payload is a handful of keys and the prose is everything
    else, which is the shape that failed: a verbose rationale spending the
    budget the structure needs.
    """
    base = json.dumps({"kind": "EVIDENCE_TRANSITION", "rationale": "",
                       "payload": TRANSITION_PAYLOAD}, separators=(",", ":"))
    rationale_len = max(1, target_bytes - len(base))
    text = json.dumps({"kind": "EVIDENCE_TRANSITION",
                       "rationale": "a" * rationale_len,
                       "payload": TRANSITION_PAYLOAD}, separators=(",", ":"))
    return text, len(text.encode("utf-8"))


def _invoke(text: str) -> Any:
    """One real round trip through the plane, with `text` as the model's reply."""
    provider = ScriptedProvider("alpha", (_profile(),), [_response(text)])
    return _router([provider],
                   proposable=frozenset({"EVIDENCE_TRANSITION"})).invoke(
        _request(output_contract=TRANSITION_CONTRACT))


# ── 1. the bound, and the arithmetic for it ──


class TestTheBound:
    def test_the_proposal_cap_is_the_payload_cap_plus_a_rationale(self) -> None:
        """8192 = 4096 (largest journal payload) + 4096 (its rationale).

        The old value was the journal cap itself, adopted by analogy. The new
        one is the sum of the two things a proposal actually carries: the
        payload the journal will take, and a rationale as large as the payload
        it justifies.
        """
        assert MAX_PROPOSAL_BYTES == 8192
        assert MAX_PROPOSAL_BYTES == MAX_PAYLOAD_BYTES * 2

    def test_the_journal_cap_did_not_move(self) -> None:
        """Raising the reply bound must not widen the row bound (§5.5)."""
        assert MAX_PAYLOAD_BYTES == 4096

    @pytest.mark.parametrize("size", RUN_33_SIZES)
    def test_every_size_run_33_wrote_is_under_the_new_bound(self, size: int) -> None:
        """The measurement the charter rests on: four samples, none absurd."""
        assert size < MAX_PROPOSAL_BYTES

    def test_the_largest_observation_leaves_room_for_the_shape_that_failed(
            self) -> None:
        """5666 is the worst case observed; 8192 leaves 2526 bytes over it."""
        largest = max(RUN_33_SIZES)
        assert MAX_PROPOSAL_BYTES - largest == 2526
        assert largest / MAX_PROPOSAL_BYTES < 0.70


# ── 2. the falsifiers, by name ──


class TestTheFalsifiers:
    def test_a_proposal_at_5_kb_is_accepted(self) -> None:
        """Falsifier 1a: 5 KB is inside the new bound, and it drafts."""
        text, size = _reply(5120)
        assert 5000 <= size <= 5200, size
        result = _invoke(text)

        assert result.overflow is None
        assert result.structured["payload"] == TRANSITION_PAYLOAD

    def test_a_proposal_at_twice_the_new_bound_still_refuses(self) -> None:
        """Falsifier 1b: 16384 is an overflow, not a bigger proposal."""
        text, size = _reply(MAX_PROPOSAL_BYTES * 2)
        assert size > MAX_PROPOSAL_BYTES

        result = _invoke(text)

        assert result.overflow is not None
        assert result.overflow.size_bytes > MAX_PROPOSAL_BYTES
        # Nothing survives the overflow: the body is all that is left of it.
        assert result.structured == {}

    def test_the_refusal_names_the_actual_size_and_the_bound(self) -> None:
        """Falsifier 2: the message states both numbers, as it did before."""
        overflow = ModelArtifactOverflow(body=b"x" * 16384, size_bytes=16384)
        result = _runtime(ScriptedModel({
            PROFILE: [_proposal({}, overflow=overflow)]})).run(
                PROFILE, _one_tick())

        assert result.refusal_codes() == (RATIONALE,)
        detail = result.refusals[0].detail
        assert f"{MAX_PROPOSAL_BYTES}-byte cap" in detail
        assert "16384 bytes" in detail

    def test_an_over_cap_proposal_still_fails_the_run(self) -> None:
        """Falsifier 5: raising the cap did not soften the refusal."""
        overflow = ModelArtifactOverflow(body=b"x" * 16384, size_bytes=16384)
        result = _runtime(ScriptedModel({
            PROFILE: [_proposal({}, overflow=overflow)]})).run(
                PROFILE, _one_tick())

        assert result.state == TaskStatus.FAILED.value
        assert result.termination == Termination.MODEL_REFUSED.value

    def test_the_message_says_which_happened(self) -> None:
        """Falsifier 3, the arm that is live: no port, so not preserved.

        The two behaviours stay separate — "preserved" and "parsed" are
        different sentences, and this composition wires no port, so the message
        must not claim a reference it does not have.
        """
        overflow = ModelArtifactOverflow(body=b"x" * 9000, size_bytes=9000)
        result = _runtime(ScriptedModel({
            PROFILE: [_proposal({}, overflow=overflow)]})).run(
                PROFILE, _one_tick())

        detail = result.refusals[0].detail
        assert "no artifact overflow port is wired" in detail
        assert "preserved as" not in detail
        assert detail.endswith("an overflowed body is not parsed")


# ── 3. what the cap measures: the rationale, once ──


class TestWhatTheCapMeasures:
    def test_a_verbose_rationale_does_not_spend_the_structures_budget_twice(
            self) -> None:
        """The defect, as a falsifier: 5 KB of reply with 4.8 KB of prose.

        Counted twice (the old body) this reply measures ~9.8 KB and would
        overflow 8192. Counted once it is 5 KB, and it drafts.
        """
        text, size = _reply(5120)
        parsed = json.loads(text)
        doubled = len(_canonical_bytes({
            "structured": parsed,
            "rationale": parsed["rationale"],
            "tool_calls": [],
        }))
        assert doubled > MAX_PROPOSAL_BYTES, (
            "the fixture must be one the old measurement refused")

        result = _invoke(text)

        assert result.overflow is None
        assert size < MAX_PROPOSAL_BYTES

    def test_the_body_carries_the_rationale_once(self) -> None:
        """An overflow body is an audit artifact: nothing in it is duplicated."""
        text, _ = _reply(MAX_PROPOSAL_BYTES * 2)
        rationale = json.loads(text)["rationale"]

        result = _invoke(text)

        assert result.overflow is not None
        body = result.overflow.body
        assert body.count(rationale.encode("utf-8")) == 1

        parsed = json.loads(body.decode("utf-8"))
        assert parsed["rationale"] == rationale
        assert "rationale" not in parsed["structured"]

    def test_the_measured_body_is_the_reply_plus_the_envelope_tax(self) -> None:
        """The number the plane refuses on is the reply, not twice a part of it.

        Measured directly: an overflowing reply reports `size_bytes`, and that
        number is within the envelope's own keys (`structured`, `rationale`,
        `tool_calls` — tens of bytes) of the reply the model wrote.
        """
        text, size = _reply(MAX_PROPOSAL_BYTES * 2)

        result = _invoke(text)

        assert result.overflow is not None
        assert abs(result.overflow.size_bytes - size) < 64, (
            result.overflow.size_bytes, size)
        # …and the same body is what the overflow carries.
        assert len(result.overflow.body) == result.overflow.size_bytes

    def test_the_runtime_still_reads_the_rationale_from_structured(self) -> None:
        """Lifting it out of the *body* must not lift it out of the proposal."""
        text, _ = _reply(2048)
        result = _invoke(text)

        assert result.overflow is None
        assert result.structured["rationale"] == json.loads(text)["rationale"]

    def test_a_contract_without_a_rationale_field_is_untouched(self) -> None:
        """No rationale field, no lifting: the body is the structured output."""
        structured = {"text": "hello"}
        assert _without_rationale(structured, None) == structured
        assert _without_rationale(
            structured, OutputContract(name="plain")) == structured


# ── 4. the payload bound is a different bound, and it still bites ──


class TestThePayloadBound:
    def test_a_reply_under_the_new_cap_can_still_refuse_its_payload(self) -> None:
        """§5.5 at the journal boundary: 8 KiB of reply, 5 KiB of payload.

        The reply is legal and the draft is not, because the payload is what
        the journal has to hold. Raising the reply bound must not move this.
        """
        result = _runtime(ScriptedModel({
            "researcher": [_proposal({"kind": "EVIDENCE_TRANSITION",
                                      "rationale": "a legal reply",
                                      "payload": {"blob": "z" * 5000}})]})).run(
            "researcher", _one_tick())

        assert result.refusal_codes() == (RATIONALE,)
        detail = result.refusals[0].detail
        assert f"over the {MAX_PAYLOAD_BYTES}-byte cap" in detail
        assert "5011 bytes" in detail

    def test_the_derived_payload_arm_still_refuses_too(self) -> None:
        """The other payload site: INSERT_TASK, whose identity keys are added.

        It refuses without naming a size (the payload was never handed over),
        and the wording is the "rather than truncated" one the charter quotes.
        """
        result = _runtime(ScriptedModel({
            PROFILE: [_proposal({"kind": "INSERT_TASK",
                                 "rationale": "a legal reply",
                                 "payload": {"blob": "z" * 5000}})]})).run(
            PROFILE, _one_tick())

        assert result.refusal_codes() == (RATIONALE,)
        detail = result.refusals[0].detail
        assert f"over the {MAX_PAYLOAD_BYTES}-byte cap" in detail
        assert "refused rather than truncated" in detail

    def test_a_payload_refusal_does_not_end_the_run_but_an_overflow_does(
            self) -> None:
        """The two sites' dispositions differ, and that is the design.

        A draft over the payload cap is one refused proposal: nothing was
        written and the tick's other drafts may still land, so the run carries
        on. A whole-proposal overflow leaves *no* draft at all (`structured` is
        emptied), so the tick produced nothing and the run ends.
        """
        payload_case = _runtime(ScriptedModel({
            "researcher": [_proposal({"kind": "EVIDENCE_TRANSITION",
                                      "rationale": "r",
                                      "payload": {"blob": "z" * 5000}})]})).run(
            "researcher", _one_tick())

        overflow_case = _runtime(ScriptedModel({
            PROFILE: [_proposal({}, overflow=ModelArtifactOverflow(
                body=b"x" * 9000, size_bytes=9000))]})).run(
            PROFILE, _one_tick())

        assert payload_case.state != TaskStatus.FAILED.value
        assert overflow_case.state == TaskStatus.FAILED.value
        assert (payload_case.termination
                != overflow_case.termination)

    def test_the_two_caps_are_named_separately_in_the_contract(self) -> None:
        """One number for the reply, one for the row — never one for both."""
        contract = output_contract_for(load_profiles()[PROFILE])

        assert contract.max_proposal_bytes == MAX_PROPOSAL_BYTES
        assert contract.max_payload_bytes == MAX_PAYLOAD_BYTES


# ── 5. what the model can see ──


class TestWhatTheModelCanSee:
    def _rendered(self) -> tuple[dict[str, Any], str]:
        contract = output_contract_for(load_profiles()[PROFILE])
        mapping = _contract_mapping(contract)
        assert mapping is not None
        return mapping, render_system(PROFILE, mapping)

    def test_the_contract_carries_both_bounds(self) -> None:
        mapping, _ = self._rendered()
        assert mapping["max_proposal_bytes"] == MAX_PROPOSAL_BYTES
        assert mapping["max_payload_bytes"] == MAX_PAYLOAD_BYTES

    def test_the_reply_cap_is_stated_with_a_countable_proxy(self) -> None:
        """§4.3: a bound in bytes alone is a bound a model cannot check.

        The sentence states the byte cap and the character equivalence a model
        can estimate while writing, so "how close am I" has an answer that does
        not require counting UTF-8.
        """
        _, rendered = self._rendered()
        assert (f"The whole reply must be at most {MAX_PROPOSAL_BYTES} bytes"
                in rendered)
        assert f"about {MAX_PROPOSAL_BYTES} characters" in rendered
        assert "non-ASCII" in rendered

    def test_the_payload_cap_is_stated_at_all(self) -> None:
        """The bound that refuses drafts was never in a contract sentence."""
        _, rendered = self._rendered()
        assert (f"Each proposal's payload must fit the journal's "
                f"{MAX_PAYLOAD_BYTES}-byte cap" in rendered)

    def test_both_statements_are_generated_from_their_constants(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Neither number is hand-typed into the prompt."""
        monkeypatch.setattr(run_module, "MAX_PROPOSAL_BYTES", 4096)
        monkeypatch.setattr(run_module, "MAX_PAYLOAD_BYTES", 1024)

        contract = output_contract_for(load_profiles()[PROFILE])
        mapping = _contract_mapping(contract)
        assert mapping is not None
        rendered = render_system(PROFILE, mapping)

        assert "at most 4096 bytes" in rendered
        assert "journal's 1024-byte cap" in rendered
        assert "at most 8192 bytes" not in rendered

    def test_a_contract_without_the_bounds_says_nothing_about_them(self) -> None:
        mapping = _contract_mapping(OutputContract(name="stale"))
        assert mapping is not None
        rendered = render_system(PROFILE, mapping)

        assert "at most" not in rendered
        assert "journal's" not in rendered
