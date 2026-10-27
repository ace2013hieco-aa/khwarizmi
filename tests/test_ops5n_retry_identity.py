"""OPS-5N — a retry that changes its request is a new act.

The capability key used to be `digest(run, tick, index, capability)`: a
*position* in a transcript. The plane's ledger compares the request (capability,
profile, arguments), so a Controller retry that re-entered tick 1 with the same
position and a fresh model sample looked like a key reused for a different act
and was refused `IDEMPOTENCY_CONFLICT` — the repair mechanism refused by the
attempt it was trying to correct (run 30).

This battery pins, in order: the end-to-end shape (a retry that changes its
request executes; a byte-identical retry replays **within the composing
process**), the derivation's inputs (every field of the act moves the key; the
raw arguments are the preimage, not the redacted record form), the plane's
`IDEMPOTENCY_CONFLICT` branch staying live for a hand-minted key, and the
task-id derivation staying byte-identical (OPS-5O owns that defect).

Nothing here touches the task-id derivation: the two pinned values below are
today's, and a change to either is a different slice's decision.
"""

from __future__ import annotations

import re

from hermes.agents.runtime.types import (
    ProposalSet,
    child_idempotency_key_of,
    child_task_id_of,
    digest_of,
    tool_idempotency_key_of,
)
from hermes.security.boundaries import UntrustedContent
from hermes.tools.capabilities.envelope import redact_arguments
from hermes.tools.capabilities.types import (
    IDEMPOTENCY_CONFLICT,
    CapabilityRefusal,
    InvokeRequest,
    Observation,
)
from tests.test_capability_plane import build_rig, observation_of, refusal_of
from tests.test_loop4_hygiene import (
    _context,
    _draft,
    _Model,
    _profile,
    _runtime,
)

RUN = "run_5f1b13d0"
CAPABILITY = "source_search"
PROFILE = "researcher"


def _key(arguments: dict[str, object], *, run: str = RUN, tick: int = 1,
         index: int = 0, capability: str = CAPABILITY,
         profile: str = PROFILE) -> str:
    """The derived key for one act, spelled once so every test names the act."""
    return tool_idempotency_key_of(run, tick, index, capability, profile,
                                   arguments)


# ═══════════════ the end-to-end shape: a Controller retry ═══════════════


class _LedgerPlane:
    """The plane's idempotency *rule* without the plane.

    A scripted capability port that remembers one settled observation per key
    and applies `_replayed_or_conflict`'s decision, so a runtime-level test can
    see the refusal run 30 saw rather than a fake that never refuses.
    """

    def __init__(self) -> None:
        self.requests: list[InvokeRequest] = []
        self.executions = 0
        self.replays = 0
        self._settled: dict[str, tuple[str, Observation]] = {}

    def invoke(self, request: InvokeRequest) -> Observation | CapabilityRefusal:
        self.requests.append(request)
        digest = digest_of({
            "capability_id": request.capability_id,
            "profile": request.profile,
            "arguments": redact_arguments(dict(request.arguments)),
        })
        prior = self._settled.get(request.idempotency_key)
        if prior is not None and prior[0] != digest:
            return CapabilityRefusal(
                code=IDEMPOTENCY_CONFLICT,
                detail=f"idempotency key {request.idempotency_key!r} was "
                       f"already used for a different request — a retry must "
                       f"be the same act",
                capability_id=request.capability_id,
                profile=request.profile)
        observation = Observation(
            capability_id=request.capability_id,
            status="OK",
            payload=UntrustedContent(
                text=f"results for {request.arguments.get('query', '')}",
                origin="scripted.tool", ref="tool:source_search"),
            idempotency_key=request.idempotency_key,
            replayed=prior is not None)
        if prior is None:
            self.executions += 1
        else:
            self.replays += 1
        self._settled[request.idempotency_key] = (digest, observation)
        return observation

    def keys(self) -> list[str]:
        return [request.idempotency_key for request in self.requests]

    def queries(self) -> list[object]:
        return [request.arguments.get("query") for request in self.requests]


def _search_profile():
    return _profile("researcher", max_ticks=1, capabilities=(CAPABILITY,),
                    fields=("proposals", "tool_calls"))


def _search_turn(query: str, *, goal: str = "g") -> dict[str, object]:
    return _draft(payload={"goal": goal},
                  tool_calls=[{"capability_id": CAPABILITY,
                               "arguments": {"query": query},
                               "rationale": "find a source"}])


def _run_once(model: _Model, plane: _LedgerPlane) -> ProposalSet:
    """One attempt of the same stage: same task, same run id, new model reply."""
    runtime = _runtime(model, profiles={"researcher": _search_profile()},
                       capabilities=plane)
    return runtime.run("researcher", _context(task_id="task-root"))


def test_a_retry_that_changes_its_request_executes_as_a_distinct_act() -> None:
    """Run 30, minimal: the same stage re-entered with a new question.

    Two runs with the same `run_id` are two attempts of one stage — the
    Controller's retry. The model asks something different the second time
    (a fresh sample), which used to recompute the first attempt's key and be
    refused. It must now be a second act.
    """
    plane = _LedgerPlane()
    model = _Model({"researcher": [_search_turn("alpha"),
                                   _search_turn("beta")]})

    first = _run_once(model, plane)
    second = _run_once(model, plane)

    assert first.state == "SUCCEEDED"
    assert second.state == "SUCCEEDED"
    assert first.run_id == second.run_id
    assert plane.queries() == ["alpha", "beta"]
    assert len(set(plane.keys())) == 2
    assert (plane.executions, plane.replays) == (2, 0)
    assert second.refusal_codes() == ()


def test_a_byte_identical_retry_recomputes_the_key_and_replays() -> None:
    """Determinism after the change: same act, same key, recorded answer."""
    plane = _LedgerPlane()
    model = _Model({"researcher": [_search_turn("alpha"),
                                   _search_turn("alpha")]})

    first = _run_once(model, plane)
    second = _run_once(model, plane)

    assert first.state == "SUCCEEDED"
    assert second.state == "SUCCEEDED"
    assert len(set(plane.keys())) == 1
    assert (plane.executions, plane.replays) == (1, 1)
    assert plane.queries() == ["alpha", "alpha"]


def test_two_searches_in_one_tick_are_two_acts() -> None:
    """Indices 0 and 1 are two positions *and* two acts — no conflict."""
    plane = _LedgerPlane()
    turn = _draft(
        payload={"goal": "g"},
        tool_calls=[
            {"capability_id": CAPABILITY,
             "arguments": {"query": "alpha"}, "rationale": "first"},
            {"capability_id": CAPABILITY,
             "arguments": {"query": "beta"}, "rationale": "second"},
        ])
    model = _Model({"researcher": [turn]})

    result = _run_once(model, plane)

    assert result.state == "SUCCEEDED"
    assert plane.queries() == ["alpha", "beta"]
    assert len(set(plane.keys())) == 2
    assert (plane.executions, plane.replays) == (2, 0)


# ═══════════════ the derivation names the act ═══════════════


def test_the_key_changes_with_every_field_of_the_act() -> None:
    """Each declared part of an act is part of its identity."""
    base = {"query": "alpha"}
    reference = _key(base)

    assert _key(base) == reference
    assert _key(base, run="run_other") != reference
    assert _key(base, tick=2) != reference
    assert _key(base, index=1) != reference
    assert _key(base, capability="source_fetch") != reference
    assert _key(base, profile="critic") != reference
    assert _key({"query": "beta"}) != reference


def test_the_key_is_still_a_64_character_sha256() -> None:
    """Length is a surface: prompt byte counts record it, so it cannot move."""
    assert re.fullmatch(r"[0-9a-f]{64}", _key({"query": "alpha"}))


def test_the_key_digests_raw_arguments_not_the_redacted_record_form() -> None:
    """Redaction is a journal-presentation rule, never an identity rule.

    `redact_arguments` masks by name and by *substring*: a field called
    `sort_key` or `keywords` is masked because it contains a credential alias.
    Digesting the masked form would give two different requests one key — a
    different act replaying the first act's answer — so the preimage is the
    raw validated arguments. The masked form stays what the ledger *records*.
    """
    assert _key({"api_key": "one"}) != _key({"api_key": "two"})
    assert _key({"sort_key": "asc"}) != _key({"sort_key": "desc"})
    assert _key({"keywords": ["a"]}) != _key({"keywords": ["b"]})
    # Canonical, not ordered: the same act writes the same key.
    assert _key({"a": 1, "b": 2}) == _key({"b": 2, "a": 1})


# ═══════════════ the plane's own defence stays live ═══════════════


def test_a_hand_minted_key_that_collides_still_refuses() -> None:
    """The runtime can no longer reach this branch; other callers still must."""
    rig = build_rig()
    rig.call("cap.echo", key="hand-minted", arguments={"text": "hi"})
    refusal = refusal_of(rig.call("cap.echo", key="hand-minted",
                                  arguments={"text": "other"}))
    assert refusal.code == IDEMPOTENCY_CONFLICT
    assert "different request" in refusal.detail
    assert rig.calls == ["svc.echo"]


def test_a_derived_key_from_the_plane_side_replays_but_never_conflicts() -> None:
    """Same key ⇒ same request, so the derived path can only ever replay."""
    rig = build_rig()
    key = _key({"text": "hi"}, capability="cap.echo", profile="analyst")
    first = observation_of(rig.call("cap.echo", key=key,
                                    arguments={"text": "hi"}))
    second = observation_of(rig.call("cap.echo", key=key,
                                     arguments={"text": "hi"}))
    assert first.replayed is False
    assert second.replayed is True
    assert rig.calls == ["svc.echo"]
    assert rig.ledger.keys() == (key,)


# ═══════════════ the task id is untouched (OPS-5O owns it) ═══════════════


def test_the_task_id_derivation_is_byte_identical_to_today() -> None:
    """Pinned, not fixed: the content-blind id is a separate gate.

    OPS-5N changes the capability key only. These two values are today's and
    must not move under this slice; if they ever do, it is OPS-5O's decision
    and its own evidence, never a side effect of a retry fix.
    """
    assert child_task_id_of("task-root", "critic", 0) == (
        "task_653a31078e995eee1ce2a831fd0e8bc5")
    assert child_idempotency_key_of("task-root", "critic", 0, {"a": 1}) == (
        "d8918c687f3bc6faffb04e69af3eb49fe8177f4f7703f8225f671129aa21db11")


def test_the_capability_key_is_not_part_of_any_task_id() -> None:
    """The two identities are disjoint: a retry fix cannot move a task id."""
    arguments = {"query": "alpha"}
    before = (child_task_id_of("task-root", "critic", 0),
              child_idempotency_key_of("task-root", "critic", 0, {"a": 1}))
    _key(arguments, run="another-run", tick=9, index=3)
    after = (child_task_id_of("task-root", "critic", 0),
             child_idempotency_key_of("task-root", "critic", 0, {"a": 1}))
    assert before == after
