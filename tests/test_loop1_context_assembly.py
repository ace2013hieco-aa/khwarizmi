"""LOOP-1 — the context-assembly port: purity, payload rendering, review drafts.

The port (`hermes.agents.runtime.assembly`) is the E1/G2 keystone: the runtime's
model prompt is the injected assembler's output, so a run's payload reaches the
model and a review child sees the drafts it reviews. These are *purity* tests as
much as behaviour tests — the defaults must be pure functions of the run's
inputs (equal contexts assemble to equal envelopes; no clock, no model, no I/O),
because a non-pure assembler would make a prompt a function of ambient state and
break the determinism the loop is built on.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import hermes.agents.runtime.assembly as assembly_module
from hermes.agents.runtime.assembly import (
    PAYLOAD_ORIGIN,
    PROPOSAL_ORIGIN,
    assemble_payload_envelopes,
    default_context_assembler,
    proposal_envelopes,
)
from hermes.agents.runtime.config import ProfileSpec, parse_profile
from hermes.agents.runtime.run import AgentRuntime
from hermes.agents.runtime.types import Proposal, TaskContext
from hermes.core.intents import Intent, IntentKind
from hermes.security.boundaries import UntrustedContent
from hermes.tools.models.router import ModelProposal, ModelRequest

ASSEMBLY_PATH = Path(str(assembly_module.__file__))

#: Exactly what the module may import: its own types, the envelope, stdlib.
#: ``json``, ``re`` and ``html`` joined this set for OPS-5Z3: the evidence
#: excerpt selects an artifact's *content* — an OpenAlex abstract reconstructed
#: from its inverted index, HTML reduced to text — instead of taking a byte
#: prefix. All three are pure, deterministic and touch nothing: no clock, no
#: model, no I/O, which is what this invariant exists to protect.
ALLOWED_IMPORTS = frozenset({
    "__future__", "collections.abc", "typing",
    "hermes.agents.runtime.types",
    "hermes.security.boundaries",
    # OPS-5Z4: the content extractor is one implementation in the capability
    # layer, shared with `evidence_inspect` so the model and the falsifier read
    # the same text. It imports nothing but stdlib, so the purity rule holds —
    # and the runtime's import direction (`hermes.tools.capabilities`) is the
    # one the module-invariant test enforces.
    "hermes.tools.capabilities.content",
})

#: Names a module that could touch the world would mention.
FORBIDDEN_NAMES = frozenset({
    "open", "connect", "execute", "invoke", "sleep", "urlopen", "sqlite3",
    "subprocess", "environ", "socket",
})

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


# ═══════════════════════ helpers ═══════════════════════


def _context(*, payload: dict[str, Any] | None = None,
             context: tuple[UntrustedContent, ...] = (),
             task_id: str = "task-1") -> TaskContext:
    return TaskContext(task_id=task_id, project_id="p-1",
                       lease_generation="gen-1",
                       payload=payload if payload is not None else {},
                       context=context)


def _profile(name: str, *, stop_when: str = "no_proposals",
             review: dict[str, Any] | None = None,
             max_ticks: int = 1) -> ProfileSpec:
    document: dict[str, Any] = {
        "name": name,
        "role": f"{name} role",
        "agent_profile": "RESEARCHER",
        "model_policy": {"tier": "research", "structured_fields": ["proposals"]},
        "tools": [],
        "authority": {"proposable_kinds": ["INSERT_TASK"]},
        "termination": {"max_ticks": max_ticks, "max_proposals": 5,
                        "stop_when": stop_when},
    }
    if review is not None:
        document["review"] = review
    return parse_profile(document, source=name)


def _proposal(request: ModelRequest, structured: dict[str, Any]
              ) -> ModelProposal:
    return ModelProposal(provider_id="scripted", model_id="scripted",
                         tier="research", profile=request.profile,
                         lease_generation=request.lease_generation,
                         structured=dict(structured))


@dataclass(frozen=True, slots=True)
class _Applied:
    entity_id: str
    duplicate: bool


class _Applier:
    def __init__(self) -> None:
        self.calls: list[Intent] = []

    def __call__(self, intent: Intent) -> _Applied:
        self.calls.append(intent)
        return _Applied(entity_id=f"ent_{len(self.calls):04d}", duplicate=False)


class _ScriptedModel:
    """Records every request; proposes only where the script says so."""

    def __init__(self, script: dict[str, list[dict[str, Any]]] | None = None
                 ) -> None:
        self.calls: list[ModelRequest] = []
        self._script = dict(script or {})

    def invoke(self, request: ModelRequest) -> ModelProposal:
        self.calls.append(request)
        queue = self._script.get(request.profile, [])
        structured = queue.pop(0) if queue else {}
        return _proposal(request, structured)


# ═══════════════════════ 1. the pure defaults ═══════════════════════


def test_payload_envelopes_are_sorted_by_key_and_insertion_order_free() -> None:
    first = _context(payload={"z": 1, "a": {"x": [1, 2]}, "m": "v"})
    second = _context(payload={"m": "v", "a": {"x": [1, 2]}, "z": 1})
    left = assemble_payload_envelopes(first)
    right = assemble_payload_envelopes(second)
    assert left == right
    assert [envelope.ref for envelope in left] == [
        "task-1:a", "task-1:m", "task-1:z"]
    assert all(envelope.origin == PAYLOAD_ORIGIN for envelope in left)
    assert left[0].text == '{"a":{"x":[1,2]}}'


def test_the_default_assembler_keeps_the_caller_envelopes_then_the_payload() -> None:
    prior = UntrustedContent(text="prior", origin="spec.prior", ref="r1")
    context = _context(payload={"stage": "QUESTION"}, context=(prior,))
    assembled = default_context_assembler(context)
    assert assembled[0] == prior
    assert assembled[1].origin == PAYLOAD_ORIGIN
    assert json.loads(assembled[1].text) == {"stage": "QUESTION"}
    # Same inputs, same envelopes — the port's precondition.
    assert default_context_assembler(context) == assembled


def test_review_envelopes_are_deterministic_and_carry_the_draft() -> None:
    proposal = Proposal(
        intent=Intent(kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                      project_id="p-1", payload={"goal": "g"},
                      justification="delegate to lead"),
        rationale="the draft under review", tick=2, profile="lead",
        agent_profile="RESEARCHER", lease_generation="gen-1")
    first = proposal_envelopes((proposal,))
    second = proposal_envelopes((proposal,))
    assert first == second
    document = json.loads(first[0].text)
    assert document["kind"] == "INSERT_TASK"
    assert document["rationale"] == "the draft under review"
    assert document["payload"] == {"goal": "g"}
    assert _HEX64.match(document["draft_digest"])
    assert first[0].origin == PROPOSAL_ORIGIN
    assert first[0].ref == document["draft_digest"]


def test_an_oversize_review_body_is_omitted_explicitly_never_truncated() -> None:
    proposal = Proposal(
        intent=Intent(kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                      project_id="p-1", payload={"blob": "x" * 4000},
                      justification="delegate to lead"),
        rationale="big", tick=1, profile="lead", agent_profile="RESEARCHER",
        lease_generation="gen-1")
    document = json.loads(proposal_envelopes((proposal,))[0].text)
    assert document["payload"] == {}
    assert document["payload_omitted_bytes"] > 4000
    assert document["kind"] == "INSERT_TASK"  # identity fields survive


def test_the_assembly_module_is_pure_no_clock_no_model_no_io() -> None:
    tree = ast.parse(ASSEMBLY_PATH.read_text(encoding="utf-8"))
    imports: set[str] = set()
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
    assert imports == set(ALLOWED_IMPORTS)
    assert identifiers & FORBIDDEN_NAMES == set()


# ═══════════════════════ 2. the runtime honours the port ═══════════════════════


def test_an_injected_assembler_owns_the_prompt_and_the_tick_stays_last() -> None:
    model = _ScriptedModel()
    marker = UntrustedContent(text="custom envelope", origin="probe.custom",
                              ref="mark")
    runtime = AgentRuntime(model=model, orchestration=_Applier(),
                           profiles={"lead": _profile("lead")},
                           assembler=lambda context: (marker,))
    result = runtime.run("lead", _context(payload={"ignored": True}))

    assert result.state == "SUCCEEDED"
    assert model.calls
    prompt = model.calls[0].prompt
    assert prompt[:-1] == (marker,)
    assert prompt[-1].origin == "runtime.tick"
    assert prompt[-1].text.startswith("tick 1 of ")


def test_the_default_prompt_carries_the_run_payload() -> None:
    model = _ScriptedModel()
    runtime = AgentRuntime(model=model, orchestration=_Applier(),
                           profiles={"lead": _profile("lead")})
    result = runtime.run("lead", _context(payload={
        "stage": "QUESTION", "methodology_id": "literature-review"}))

    assert result.state == "SUCCEEDED"
    prompt = model.calls[0].prompt
    carried = [envelope for envelope in prompt
               if envelope.origin == PAYLOAD_ORIGIN]
    joined = "\n".join(envelope.text for envelope in carried)
    assert "QUESTION" in joined
    assert "literature-review" in joined


def test_a_review_child_receives_the_drafts_not_the_spec_digest() -> None:
    reviewer_review = {"reviewer_profile": "reviewer", "required": True,
                       "max_review_rounds": 1}
    model = _ScriptedModel({"lead": [{
        "kind": "INSERT_TASK", "rationale": "the draft under review",
        "payload": {"goal": "g"}}]})
    applier = _Applier()
    runtime = AgentRuntime(
        model=model, orchestration=applier,
        profiles={"lead": _profile("lead", stop_when="proposals_raised",
                                   review=reviewer_review),
                  "reviewer": _profile("reviewer")})
    result = runtime.run("lead", _context(task_id="task-rev"))

    assert result.state == "SUCCEEDED"
    review_calls = [request for request in model.calls
                    if request.profile == "reviewer"]
    assert review_calls, "the review child did not run"
    prompt = review_calls[0].prompt
    drafts = [envelope for envelope in prompt
              if envelope.origin == PROPOSAL_ORIGIN]
    assert drafts, "the reviewer's prompt carries no draft envelopes"
    document = json.loads(drafts[0].text)
    assert document["kind"] == "INSERT_TASK"
    assert document["rationale"] == "the draft under review"
    payload = document["payload"]
    assert payload["goal"] == "g"
    # The derived identity fields travel with the draft (never authored).
    assert {"task_id", "idempotency_key", "profile",
            "task_type"} <= set(payload)
    # The old shape — a bare digest of the delegation spec — is gone.
    assert not any(_HEX64.match(envelope.text) for envelope in prompt)
