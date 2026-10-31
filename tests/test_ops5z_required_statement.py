"""OPS-5Z — a requirement is either declared or it is not.

The slice makes the `statement` field conditional: required when the reply
*proposes* in a stage whose node carries model prose, optional for a gather
tick and for every other stage. OPS-5ZM adds `EXPERIMENT` to that set: its
prose is the test it would run, and the node carries it as `test`. These are
the falsifiers from the design note, each as a test.

The distinction that matters is between "the model was told" and "the gate
enforces it". Before this slice the matrix showed three stages where the gate
required a statement the contract did not — the model was never told, and every
run died at the draft instead of at the prompt.
"""

from __future__ import annotations

import json

import pytest

from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import output_contract_for
from hermes.methodology.workflows import (
    MethodologyInputs,
    _default_content,
    _stage_requires_statement,
)
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import (
    MALFORMED_PAYLOAD,
    ModelRouter,
    _contract_mapping,
    _Refusal,
)

PROFILES = "src/hermes/agents/runtime/profiles"


def _spec(name: str):
    return load_profiles(directory=PROFILES)[name]


def _router() -> ModelRouter:
    """A router with no provider: `_validate_output` is pure over the contract."""
    router = object.__new__(ModelRouter)
    router._proposable_kinds = frozenset({"HYPOTHESIS", "PREDICTION"})
    return router


def _reply(**over: object) -> str:
    body = {"rationale": "because", "kind": "HYPOTHESIS", "payload": {}}
    body.update(over)
    return json.dumps(body)


# ── the contract ────────────────────────────────────────────────────────────


def test_a_minting_contract_marks_the_statement_conditionally() -> None:
    """`required` must stay False. A gather tick raises no proposal and must
    still validate — that is why the marker is `required_when_proposing`."""
    contract = output_contract_for(_spec("researcher"), requires_statement=True)
    field = next(f for f in contract.fields if f.name == "statement")
    assert field.required is False
    assert field.required_when_proposing is True


def test_a_non_minting_contract_is_unchanged() -> None:
    """Default False, so every existing caller keeps today's contract."""
    contract = output_contract_for(_spec("researcher"))
    field = next(f for f in contract.fields if f.name == "statement")
    assert field.required is False
    assert field.required_when_proposing is False


def test_the_mapping_carries_the_marker_only_when_true() -> None:
    """The mapping is digested; a non-minting mapping must be byte-identical."""
    plain = _contract_mapping(output_contract_for(_spec("researcher")))
    marked = _contract_mapping(
        output_contract_for(_spec("researcher"), requires_statement=True))
    assert plain is not None and marked is not None
    assert all("required_when_proposing" not in f for f in plain["fields"])
    statement = next(f for f in marked["fields"] if f["name"] == "statement")
    assert statement["required_when_proposing"] is True


# ── the rendered line ───────────────────────────────────────────────────────


def test_the_rendered_line_says_the_requirement_once() -> None:
    """Gate 8: `optional; optional: ...` said it twice. The slot states it, so
    the note must not repeat it."""
    mapping = _contract_mapping(
        output_contract_for(_spec("researcher"), requires_statement=True))
    text = render_system("researcher", mapping)
    line = next(ln for ln in text.splitlines()
                if ln.strip().startswith("- statement"))
    assert "required when the reply proposes" in line
    assert "optional; optional" not in line
    assert "optional:" not in line


def test_a_non_minting_line_still_states_optional_exactly_once() -> None:
    mapping = _contract_mapping(output_contract_for(_spec("planner")))
    text = render_system("planner", mapping)
    line = next(ln for ln in text.splitlines()
                if ln.strip().startswith("- statement"))
    assert "(string, optional;" in line
    assert line.count("optional") == 1


def test_the_experiment_line_names_the_test_it_requires() -> None:
    """OPS-5ZM: the experiment's prose lands on the node as `test`, but the
    model writes it in the proposal's `statement`. The prompt has to say so in
    the same place it states the requirement."""
    mapping = _contract_mapping(
        output_contract_for(_spec("experimenter"), requires_statement=True))
    text = render_system("experimenter", mapping)
    line = next(ln for ln in text.splitlines()
                if ln.strip().startswith("- statement"))
    assert "required when the reply proposes" in line
    assert "experiment's discriminating test" in line


# ── the router ──────────────────────────────────────────────────────────────


def test_a_proposing_reply_without_a_statement_is_refused() -> None:
    contract = output_contract_for(_spec("researcher"), requires_statement=True)
    with pytest.raises(_Refusal) as caught:
        _router()._validate_output(contract, _reply())
    assert caught.value.code == MALFORMED_PAYLOAD
    # The refusal must be the informed re-prompt, not a terminal failure.
    assert caught.value.contract_feedback is True
    assert caught.value.retryable is True


def test_a_proposing_reply_with_a_blank_statement_is_refused() -> None:
    contract = output_contract_for(_spec("researcher"), requires_statement=True)
    with pytest.raises(_Refusal):
        _router()._validate_output(contract, _reply(statement="   "))


def test_a_proposing_reply_with_a_statement_validates() -> None:
    contract = output_contract_for(_spec("researcher"), requires_statement=True)
    parsed = _router()._validate_output(
        contract, _reply(statement="Under Z, X is associated with Y."))
    assert parsed["statement"].startswith("Under Z")


def test_a_gather_tick_still_validates() -> None:
    """OPS-5H: a minting stage may call a tool and raise no proposal. That reply
    has no statement and must not be refused — the whole reason the marker is
    conditional rather than `required=True`."""
    contract = output_contract_for(_spec("researcher"), requires_statement=True)
    tick = json.dumps({
        "rationale": "gathering", "payload": {},
        "tool_calls": [{"capability_id": "search", "arguments": {},
                        "rationale": "need the evidence first"}]})
    parsed = _router()._validate_output(contract, tick)
    assert "statement" not in parsed


def test_a_non_minting_contract_does_not_refuse_a_proposal() -> None:
    contract = output_contract_for(_spec("planner"))
    parsed = _router()._validate_output(contract, _reply(kind="HYPOTHESIS"))
    assert "statement" not in parsed


# ── the helper both drivers share ───────────────────────────────────────────


def test_a_minting_stage_requires_it_when_no_override_is_supplied() -> None:
    inputs = MethodologyInputs(question="q")
    assert _stage_requires_statement("HYPOTHESIS", inputs) is True


def test_a_supplied_statement_suppresses_the_requirement() -> None:
    """When the caller supplies the statement the model is not its source, so
    it is not required from the model — `_stage_prose`'s first precedence."""
    inputs = MethodologyInputs(
        question="q", stage_content={"HYPOTHESIS": {"statement": "supplied"}})
    assert _stage_requires_statement("HYPOTHESIS", inputs) is False


def test_an_empty_supplied_statement_does_not_suppress_it() -> None:
    inputs = MethodologyInputs(
        question="q", stage_content={"HYPOTHESIS": {"statement": "   "}})
    assert _stage_requires_statement("HYPOTHESIS", inputs) is True


def test_a_projection_without_inputs_requires_it() -> None:
    """A projection that cannot see the override must not promise the model
    that the statement is optional."""
    assert _stage_requires_statement("CLAIM", None) is True


def test_the_experiment_stage_requires_its_test() -> None:
    """OPS-5ZM: the experiment's prose is its test, and it is required exactly
    as a minting stage's statement is."""
    assert _stage_requires_statement("EXPERIMENT", MethodologyInputs(
        question="q")) is True


def test_a_supplied_test_suppresses_the_experiment_requirement() -> None:
    inputs = MethodologyInputs(
        question="q", stage_content={"EXPERIMENT": {"test": "run it"}})
    assert _stage_requires_statement("EXPERIMENT", inputs) is False


def test_default_content_puts_the_prose_on_the_experiment_test_key() -> None:
    """The proposal's one prose field is `statement`; the node's key is `test`.
    A node that carried `statement` would be indistinguishable from a minted
    assertion, which an experiment is not."""
    content = _default_content(
        "EXPERIMENT", MethodologyInputs(question="q"), "mnode_pred", "mnode_q",
        statement="run the measurement on a larger sample")
    assert content["test"] == "run the measurement on a larger sample"
    assert "statement" not in content


@pytest.mark.parametrize("stage", ["QUESTION", "OBSERVATION",
                                   "EVIDENCE", "CRITIQUE", "CONCLUSION"])
def test_a_non_prose_stage_never_requires_it(stage: str) -> None:
    assert _stage_requires_statement(stage, None) is False
