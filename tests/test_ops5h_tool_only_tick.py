"""OPS-5H — a tick may carry a tool call and no proposal.

Run 16's `OBSERVATION` tick 1 formed the call correctly and was refused
``ROLE: model proposed kind None`` because the model plane's kind check ran
before anything could notice that the reply was *gathering*. The runtime already
read a proposal-free reply as no drafts and ran the tool phase regardless; the
only gate was the plane's.

This file pins the exemption through the **real router under the live
``researcher`` contract** — not a scripted model port, which is why OPS-5F's
fetch-then-cite test stayed green while the live path failed:

1. run 16's reply is accepted, the tool executes, no draft is produced and the
   stage continues to its next tick;
2. the predicate is exactly as stated: a non-empty action array and no proposal;
3. a reply with neither a proposal nor a call still refuses ``ROLE`` with
   today's detail, and a malformed kind beside a call still refuses ``ROLE``;
4. a stage that only ever calls tools ends at its tick bound with
   ``TICK_LIMIT`` — ``max_ticks`` is the only thing stopping a spin;
5. the full three-tick sequence (search, fetch, cite) works with the plane in
   the path and the real gateway: the ``EVIDENCE`` node's ref is the fetched
   artifact;
6. the note no longer offers the multi-proposal form, and a multi-form reply
   still refuses at one of the two checks (OPS-5I).

The shape is prompt data and validation; the capability plane and the gateway
remain the authority, exactly as before.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

import pytest

from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import (
    TOOL_CALLS_FIELD,
    AgentRuntime,
    output_contract_for,
)
from hermes.agents.runtime.types import (
    MALFORMED_PAYLOAD,
    ROLE,
    RunLimits,
    TaskContext,
    Termination,
)
from hermes.core.intents import IntentKind
from hermes.methodology.workflows import literature_review
from hermes.research.capability_supply import RESEARCH_EGRESS_TOOL_SET_ID
from hermes.research.task_handlers.methodology_driver import (
    MethodologyExecution,
)
from hermes.tools.capabilities.types import (
    InvokeRequest,
    Observation,
    RiskLevel,
    ToolGrant,
)
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import (
    ModelProposal,
    ModelRefusal,
    OutputContract,
    _contract_mapping,
)
from hermes.tools.research_sources import RetryPolicy
from tests.test_loop4_hygiene import _Applier
from tests.test_model_plane import (
    ScriptedProvider,
    _policy,
    _request,
    _response,
    _router,
)
from tests.test_model_plane import _profile as _model_profile
from tests.test_ops5f_stage_budget import (
    FETCH_HASH,
    TOPIC,
    _artifact_rows,
    _node_content,
    _stage_calls,
    _transition_events,
)
from tests.test_ops5f_stage_budget import rig as _ops5f_rig

# Re-exported under its own name so pytest registers OPS-5F's rig here: real
# gateway, real capability supply, real artifact rows, scripted HTTP edge.
rig = _ops5f_rig

PROJECT = "p-ops5h"
TASK = "task-ops5h"
LEASE = "gen-ops5h"

RESEARCHER = load_profiles()["researcher"]
PROPOSABLE = frozenset(RESEARCHER.authority.proposable_kinds)

#: Run 16's reply, as the design gate records it (§1.1). The two long strings
#: are elided there; the shape is what the gate is about.
RUN_16: dict[str, Any] = {
    "rationale": ("Begin evidence acquisition by searching PubMed for "
                  "peer-reviewed literature …"),
    "tool_calls": [
        {"capability_id": "source_search",
         "arguments": {"provider": "pubmed",
                       "topic": "SARS 2003 containment vers…"}},
    ],
}

#: The proposal a later tick makes once it has gathered.
PROPOSAL: dict[str, Any] = {
    "kind": "INSERT_TASK",
    "rationale": "the search found a source worth a follow-up task",
    "payload": {"goal": "read the source the search returned"},
}

#: The single-proposal form's refusal detail, byte-identical to today's.
NEITHER_DETAIL = (
    "model proposed kind None, outside the injected proposable allowlist")


def _contract() -> OutputContract:
    return output_contract_for(RESEARCHER)


def _plane(replies: list[dict[str, Any]]):
    """A real router over a scripted provider, under the live contract."""
    provider = ScriptedProvider(
        "alpha", (_model_profile(),),
        [_response(json.dumps(reply)) for reply in replies])
    router = _router(
        [provider],
        policy=_policy(
            tier_refs={"research": "alpha:m1"}, fallback_chain=(),
            # One attempt: a retryable shape refusal would otherwise re-prompt
            # and change which detail the test observes.
            retry_policy=RetryPolicy(max_retries=0, base_delay_seconds=0.0,
                                     max_delay_seconds=0.0, jitter=False)),
        proposable=PROPOSABLE)
    return router, provider


def _invoke(reply: dict[str, Any], *,
            contract: OutputContract | None = None) -> Any:
    router, _ = _plane([reply])
    return router.invoke(_request(
        tier="research", profile="researcher",
        output_contract=contract if contract is not None else _contract()))


# ═══════════════ 1. run 16 is accepted ═══════════════


def test_run_16s_exact_reply_is_accepted_by_the_live_contract() -> None:
    result = _invoke(RUN_16)

    assert isinstance(result, ModelProposal), result
    assert result.structured["tool_calls"] == RUN_16["tool_calls"]
    assert "kind" not in result.structured
    # No retry, no second provider call: the reply was valid the first time.
    assert result.account is not None
    assert result.account.attempt == 1


# ═══════════════ 2. the predicate, exactly ═══════════════

_ABSENT = object()


def _reply(kind: object = _ABSENT, calls: object = _ABSENT) -> dict[str, Any]:
    reply: dict[str, Any] = {"rationale": "gather before proposing"}
    if kind is not _ABSENT:
        reply["kind"] = kind
    if calls is not _ABSENT:
        reply["tool_calls"] = calls
    return reply


_ONE_CALL = [{"capability_id": "source_search",
              "arguments": {"provider": "openalex", "topic": "crispr"},
              "rationale": "find a source"}]


@pytest.mark.parametrize(
    ("kind", "calls", "accepted", "code"),
    [
        # a non-empty action array and no proposal: valid with no kind
        (_ABSENT, _ONE_CALL, True, ""),
        (None, _ONE_CALL, True, ""),
        ("", _ONE_CALL, True, ""),
        ("  ", _ONE_CALL, True, ""),
        # a proposal beside the call is still checked
        ("GATHER", _ONE_CALL, False, ROLE),
        ("INSERT_TASK", _ONE_CALL, True, ""),
        # neither a proposal nor a call: today's refusal
        (_ABSENT, _ABSENT, False, ROLE),
        (_ABSENT, [], False, ROLE),
        ("", _ABSENT, False, ROLE),
        # a declared-type slip is not masked by a call
        (5, _ONE_CALL, False, MALFORMED_PAYLOAD),
        (None, _ABSENT, False, MALFORMED_PAYLOAD),
        # an action field of the wrong type is a shape failure
        (_ABSENT, "not-a-list", False, MALFORMED_PAYLOAD),
        # proposal-only replies are untouched
        ("INSERT_TASK", _ABSENT, True, ""),
        ("GATHER", _ABSENT, False, ROLE),
    ],
)
def test_the_predicate_is_exactly_as_stated(
        kind: object, calls: object, accepted: bool, code: str) -> None:
    result = _invoke(_reply(kind, calls))

    if accepted:
        assert isinstance(result, ModelProposal), result
        assert result.structured.get("kind") in (None, "INSERT_TASK")
    else:
        assert isinstance(result, ModelRefusal), result
        assert result.code == code
        assert result.contract_feedback is True


def test_a_reply_with_neither_refuses_with_todays_detail() -> None:
    result = _invoke(_reply())

    assert isinstance(result, ModelRefusal)
    assert result.code == ROLE
    assert result.detail == NEITHER_DETAIL
    assert result.contract_feedback is True


def test_a_malformed_kind_beside_a_call_still_refuses_role() -> None:
    result = _invoke(_reply("GATHER", _ONE_CALL))

    assert isinstance(result, ModelRefusal)
    assert result.code == ROLE
    assert result.detail == (
        "model proposed kind 'GATHER', outside the injected proposable allowlist")


def test_a_contract_with_no_action_field_behaves_exactly_as_today() -> None:
    """The LOOP baseline's guarantee: `action_field == ""` is today's code."""
    contract = replace(_contract(), action_field="")
    result = _invoke(RUN_16, contract=contract)

    assert isinstance(result, ModelRefusal)
    assert result.code == ROLE
    assert result.detail == NEITHER_DETAIL


# ═══════════════ 3. the runtime: the tick gathers and continues ═══════════════


class _CapturingSupply:
    """A capability port that records the request the runtime actually made."""

    def __init__(self) -> None:
        self.requests: list[InvokeRequest] = []

    def invoke(self, request: InvokeRequest) -> Observation:
        self.requests.append(request)
        return Observation(capability_id=request.capability_id, status="OK",
                           artifacts=("evidence/art_ops5h",))


def _runtime(replies: list[dict[str, Any]], *, capabilities: Any = None,
             max_ticks: int = 2, max_tool_calls: int = 1,
             review: bool = False) -> tuple[Any, AgentRuntime]:
    router, _ = _plane(replies)
    spec = (RESEARCHER if review
            else replace(RESEARCHER,
                         review=replace(RESEARCHER.review, required=False)))
    runtime = AgentRuntime(
        model=router,
        orchestration=_Applier(),
        capabilities=capabilities,
        profiles={"researcher": spec},
        grants={"RESEARCHER": ToolGrant(
            grant_id="grant.live.researcher", profile="RESEARCHER",
            tool_set_ids=frozenset({RESEARCH_EGRESS_TOOL_SET_ID}),
            max_risk=RiskLevel.MEDIUM.value)})
    context = TaskContext(
        task_id=TASK, project_id=PROJECT, lease_generation=LEASE,
        limits=RunLimits(max_ticks=max_ticks, max_tool_calls=max_tool_calls))
    return runtime.run("researcher", context), runtime


def _kinds(runtime: AgentRuntime, run_id: str, tick: int | None = None
           ) -> list[str]:
    return [event.kind for event in runtime.supervisor.events(run_id)
            if tick is None or event.tick == tick]


def test_a_gathering_tick_runs_the_tool_and_the_stage_continues() -> None:
    capabilities = _CapturingSupply()
    result, runtime = _runtime([RUN_16, PROPOSAL], capabilities=capabilities)

    assert result.state == "SUCCEEDED"
    assert result.termination == Termination.STOP_WHEN.value
    assert result.ticks == 2
    # The call ran; nothing was drafted on tick 1; tick 2's proposal is the
    # only one, and it was admitted.
    assert result.tool_calls == 1
    assert len(capabilities.requests) == 1
    assert capabilities.requests[0].capability_id == "source_search"
    assert len(result.proposals) == 1
    assert len(result.admitted()) == 1
    assert result.refusal_codes() == ()

    tick1 = _kinds(runtime, result.run_id, tick=1)
    assert tick1 == ["TICK_STARTED", "MODEL_REQUESTED", "TOOL_REQUESTED",
                     "TOOL_OBSERVED", "CHECKPOINT_WRITTEN"]
    assert "MODEL_REFUSED" not in _kinds(runtime, result.run_id)
    assert "PROPOSAL_DRAFTED" not in tick1
    checkpoint = next(
        event for event in runtime.supervisor.events(result.run_id)
        if event.tick == 1 and event.kind == "CHECKPOINT_WRITTEN")
    assert checkpoint.detail["proposals"] == 0


def test_a_stage_that_only_calls_tools_ends_at_its_tick_bound() -> None:
    capabilities = _CapturingSupply()
    result, runtime = _runtime(
        [RUN_16, RUN_16, RUN_16], capabilities=capabilities,
        max_ticks=3, max_tool_calls=1, review=True)

    assert result.state == "SUCCEEDED"
    assert result.termination == Termination.TICK_LIMIT.value
    assert result.ticks == 3
    assert result.proposals == ()
    assert result.tool_calls == 3
    assert result.refusal_codes() == ()
    assert "MODEL_REFUSED" not in _kinds(runtime, result.run_id)
    # A stage that never proposes is reviewed by nobody.
    assert runtime.delegation_records(run_id=result.run_id) == ()


def test_a_proposal_only_tick_is_unchanged() -> None:
    result, runtime = _runtime([PROPOSAL], max_ticks=2)

    assert result.state == "SUCCEEDED"
    assert result.termination == Termination.STOP_WHEN.value
    assert result.ticks == 1
    assert result.tool_calls == 0
    assert [proposal.intent.kind for proposal in result.proposals] == [
        IntentKind.INSERT_TASK]
    kinds = _kinds(runtime, result.run_id, tick=1)
    assert kinds[:6] == [
        "TICK_STARTED", "MODEL_REQUESTED", "PROPOSAL_DRAFTED",
        "INTENT_EMITTED", "INTENT_ADMITTED", "CHECKPOINT_WRITTEN"]
    # The stop is the run's terminal act, not an extra tick.
    assert kinds[6:] == ["RUN_TERMINATED", "CHECKPOINT_WRITTEN"]


# ═══════════════ 4. the three-tick sequence, plane in the path ═══════════════


def _parts(call: Any) -> list[dict[str, Any]]:
    return list(call.payload["prompt"])


def _tick_of(parts: list[dict[str, Any]]) -> tuple[int, int]:
    for part in parts:
        if part["origin"] != "runtime.tick":
            continue
        match = re.fullmatch(r"tick (\d+) of (\d+)", part["text"])
        if match is not None:
            return int(match.group(1)), int(match.group(2))
    return 0, 0


def _feedback(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for part in parts:
        if not str(part["origin"]).startswith("runtime.observation"):
            continue
        try:
            document = json.loads(part["text"])
        except ValueError:
            continue
        if isinstance(document, dict):
            records.append(document)
    return records


def _handle(parts: list[dict[str, Any]]) -> str:
    for record in reversed(_feedback(parts)):
        match = re.search(r"search_handle=(search_[0-9a-f]{64})",
                          str(record.get("detail", "")))
        if match is not None:
            return match.group(1)
    return ""


def _artifact(parts: list[dict[str, Any]]) -> str:
    for record in reversed(_feedback(parts)):
        for ref in record.get("artifacts") or ():
            if str(ref).startswith("evidence/"):
                return str(ref)
    return ""


def _search_reply(topic: str) -> dict[str, Any]:
    return {
        "rationale": "gather the prior art before proposing anything",
        "tool_calls": [{
            "capability_id": "source_search",
            "arguments": {"provider": "openalex", "topic": topic,
                          "max_results": 2},
            "rationale": "find a source before citing one",
        }],
    }


class _GatheringProvider:
    """A provider that answers from the tick marker and the retained feedback.

    Every reply is a *wire* reply: the real router validates it, so this is the
    live path and not a model port that hands the runtime a finished proposal.
    """

    provider_id = "alpha"

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.replies: list[dict[str, Any]] = []

    def describe(self) -> tuple[Any, ...]:
        return (_model_profile(),)

    def invoke(self, call: Any) -> Any:
        self.calls.append(call)
        parts = _parts(call)
        tick, total = _tick_of(parts)
        if total == 1:
            # HYPOTHESIS: one tick, gather the prior art, propose nothing.
            reply = _search_reply("prior art for the hypothesis")
        elif tick == 1:
            reply = _search_reply(TOPIC)
        elif tick == 2:
            handle = _handle(parts)
            assert handle, "the search handle did not reach the next tick"
            reply = {
                "rationale": "fetch the top-ranked row the search returned",
                "tool_calls": [{
                    "capability_id": "source_fetch",
                    "arguments": {"provider": "openalex",
                                  "search_handle": handle, "row_index": 0},
                    "rationale": "fetch before citing",
                }],
            }
        else:
            artifact = _artifact(parts)
            assert artifact, "the fetched artifact did not reach the next tick"
            reply = {
                "kind": "EVIDENCE_TRANSITION",
                "rationale": "cite the artifact this stage fetched",
                "payload": {
                    "evidence_artifact_ref": "evidence:" + artifact.split("/", 1)[1],
                    "from_state": "SUPPORTED",
                    "to_state": "ROBUST",
                    "rationale": "the fetched source supports the rung",
                },
            }
        self.replies.append(reply)
        return _response(json.dumps(reply))


class _PlaneForResearcher:
    """The real router for the stage under test; the OPS-5F harness elsewhere.

    The falsifier is about the researcher stage's three ticks. Every researcher
    call — HYPOTHESIS and OBSERVATION — goes through the plane; the other
    profiles keep OPS-5F's scripted port, whose replies are not what this test
    is measuring.
    """

    def __init__(self, router: Any) -> None:
        self._router = router
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> Any:
        self.calls.append(request)
        if request.profile == "researcher":
            return self._router.invoke(request)
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier=request.tier,
            profile=request.profile,
            lease_generation=request.lease_generation, structured={})


def test_the_three_tick_sequence_cites_the_fetched_artifact(rig: Any) -> None:
    provider = _GatheringProvider()
    router = _router(
        [provider],
        policy=_policy(tier_refs={"research": "alpha:m1"}, fallback_chain=()),
        proposable=frozenset(
            IntentKind.llm_proposable() | IntentKind.director_only()))
    dispatcher = _PlaneForResearcher(router)

    execution = rig.run(dispatcher)

    assert isinstance(execution, MethodologyExecution), execution
    assert execution.termination == "COMPLETE"
    assert [record.stage for record in execution.stages] == [
        "QUESTION", "HYPOTHESIS", "PREDICTION", "EXPERIMENT", "OBSERVATION",
        "EVIDENCE", "CLAIM", "CRITIQUE", "CONCLUSION"]

    # Three ticks, three wire replies, each accepted by the plane.
    calls = _stage_calls(dispatcher, "OBSERVATION")
    assert len(calls) == 3
    assert not [row for row in router.accounting() if row.refusal_code]

    # One artifact row — the fetch's — and the EVIDENCE node cites exactly it.
    rows = _artifact_rows(rig.conn)
    assert len(rows) == 1
    assert rows[0]["artifact_id"] == FETCH_HASH
    ref = f"evidence:{FETCH_HASH}"
    assert _node_content(execution, "EVIDENCE")["external_ref"] == ref
    assert _node_content(execution, "OBSERVATION")["cited_refs"] == (ref,)

    # The gateway admitted the transition, and the stage stopped on its
    # proposal rather than on the tick bound.
    assert len(_transition_events(rig.conn)) == 1
    record = next(record for record in execution.stages
                  if record.stage == "OBSERVATION")
    assert record.termination == Termination.STOP_WHEN.value


# ═══════════════ 5. the note no longer offers the multi form (OPS-5I) ═══════════════


def test_the_note_no_longer_offers_the_multi_proposal_form() -> None:
    for name, spec in load_profiles().items():
        rendered = render_system(name, _contract_mapping(output_contract_for(spec)))
        assert "omit it in the multi-proposal form" not in rendered
        assert "Choose exactly one proposal form" not in rendered
        assert "multi-proposal form requires" not in rendered
        assert ("the single-proposal form is the only proposal form in this "
                "build") in rendered
        assert ('a reply carrying a non-empty "proposals" array is refused'
                ) in rendered
        assert ("- proposals (array, optional; not usable in this build; a "
                "non-empty array is refused)") in rendered


def test_a_multi_form_reply_refuses_without_a_top_level_kind() -> None:
    """The plane's kind check runs first — OPS-5I's first line reference."""
    result = _invoke({
        "rationale": "cite it",
        "proposals": [{"kind": "INSERT_TASK", "rationale": "a task",
                       "payload": {}}],
    })

    assert isinstance(result, ModelRefusal)
    assert result.code == ROLE
    assert result.detail == NEITHER_DETAIL


def test_a_multi_form_reply_with_a_top_level_kind_refuses_at_the_runtime() -> None:
    """The both-forms check runs second — OPS-5I's second line reference."""
    result, _ = _runtime([{
        "kind": "INSERT_TASK",
        "rationale": "both forms in one reply",
        "payload": {"goal": "a task"},
        "proposals": [{"kind": "INSERT_TASK", "rationale": "a task",
                       "payload": {"goal": "a task"}}],
    }], max_ticks=1)

    assert result.refusal_codes() == (MALFORMED_PAYLOAD,)
    assert "both the single-proposal and the multi-proposal form" in (
        result.refusals[0].detail)
    assert result.proposals == ()


# ═══════════════ 6. the sentence ═══════════════


def test_the_gathering_sentence_reaches_exactly_the_three_profiles() -> None:
    declared = {"researcher", "experimenter", "critic"}
    for name, spec in load_profiles().items():
        rendered = render_system(name, _contract_mapping(output_contract_for(spec)))
        sentence = ("A reply that proposes nothing is valid when it calls a "
                    "tool: omit")
        if name in declared:
            assert sentence in rendered, name
            assert output_contract_for(spec).action_field == TOOL_CALLS_FIELD
        else:
            assert sentence not in rendered, name
            assert output_contract_for(spec).action_field == ""


def test_the_sentence_is_rendered_from_the_injected_names() -> None:
    contract = replace(
        _contract(), single_form_field="proposal_kind",
        multi_form_field="proposal_list", action_field="actions")
    rendered = render_system("researcher", _contract_mapping(contract))

    assert ('omit the "proposal_kind" and "proposal_list" fields and output a '
            'non-empty "actions" array') in rendered
    assert '"tool_calls" array' not in rendered


def test_the_sentence_costs_187_bytes() -> None:
    mapping = _contract_mapping(_contract())
    assert mapping is not None
    without = render_system("researcher", {**mapping, "action_field": ""})
    with_sentence = render_system("researcher", mapping)

    assert len(with_sentence.encode("utf-8")) - len(without.encode("utf-8")) == 187
    sentence = next(line for line in with_sentence.splitlines()
                    if line.startswith("A reply that proposes nothing"))
    assert len(sentence.encode("utf-8")) == 186


# ═══════════════ 7. the stage's objective is unchanged ═══════════════


def test_the_observation_stage_still_declares_three_ticks() -> None:
    observation = next(stage for stage in literature_review().stages
                       if stage.stage == "OBSERVATION")
    assert observation.max_ticks == 3
