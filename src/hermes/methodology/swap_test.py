"""Methodology plane — the methodology-swap fixture (diagnostic only).

Not a shipped methodology. This module exists to make one claim checkable — a
*second* methodology document loads, checks out and runs on the **same** runtime
instances as the shipped one, with no runtime, governance or model code touched
— and to hand the test suite a grounded way to build a complete chain's inputs.

``engineering-investigation`` differs from ``literature-review`` where a
methodology may legitimately differ: which profile runs which stage, the
termination bounds, and which governance actions the stages perform. It shares
nothing with the shipped document but the schema and the chain — which is the
point: the runtime is not specialised per methodology.

The probe reads no clock, holds no lease, writes nothing durable and names no
model vendor: it drives ``run_methodology``, which drives the runtime's public
entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from hermes.methodology.substrate import CHAIN_KINDS, ChainReconstruction
from hermes.methodology.workflows import (
    LITERATURE_REVIEW_DOCUMENT,
    METHODOLOGY_SCHEMA_VERSION,
    MethodologyConfig,
    MethodologyInputs,
    MethodologyRefusal,
    MethodologyRun,
    parse_methodology,
    run_methodology,
)

__all__ = [
    "ENGINEERING_INVESTIGATION_DOCUMENT",
    "SwapEvidence",
    "chain_inputs",
    "engineering_investigation",
    "run_swap_probe",
]

ENGINEERING_INVESTIGATION_DOCUMENT: Mapping[str, Any] = {
    "schema_version": METHODOLOGY_SCHEMA_VERSION,
    "methodology_id": "engineering-investigation",
    "version": "1",
    "name": "engineering-investigation",
    "description": (
        "A build-and-observe investigation: frame the question, state what is "
        "believed about the mechanism, pre-register the discriminating "
        "prediction, run the instrumented step, observe it directly rather "
        "than from a source, admit the evidence, state the claim, take "
        "adversarial critique and draw the conclusion. Different profile "
        "composition, bounds and governance actions from "
        "literature-review — the same runtime."),
    "stages": [
        {"stage": "QUESTION", "profile": "planner",
         "governance_action": "WEB_SEARCH"},
        {"stage": "HYPOTHESIS", "profile": "researcher",
         "governance_action": "WEB_SEARCH"},
        {"stage": "PREDICTION", "profile": "planner"},
        {"stage": "EXPERIMENT", "profile": "experimenter",
         "governance_action": "SANDBOX_RUN"},
        {"stage": "OBSERVATION", "profile": "experimenter",
         "governance_action": "WEB_READ"},
        {"stage": "EVIDENCE", "profile": "verifier"},
        {"stage": "CLAIM", "profile": "verifier"},
        {"stage": "CRITIQUE", "profile": "critic"},
        {"stage": "CONCLUSION", "profile": "synthesizer"},
    ],
    "termination": {
        "max_stages": 9,
        "max_ticks_per_stage": 2,
        "max_proposals_per_stage": 2,
        "deadline_seconds": 240,
    },
}


def engineering_investigation() -> MethodologyConfig:
    """The swap fixture's methodology, re-parsed from its document."""
    return parse_methodology(dict(ENGINEERING_INVESTIGATION_DOCUMENT))


def chain_inputs(project_id: str, question: str, *, suffix: str = "",
                 retracted: tuple[str, ...] = ()) -> MethodologyInputs:
    """Grounded inputs for a full chain in ``project_id``.

    The external refs a referenced-kind stage cites and the refs that resolve
    in the project are built once, here, so a caller never has to invent one:
    a ref that is not registered resolves nowhere and the substrate refuses it.
    ``retracted`` names refs the caller has observed retracted (the N9
    projection) — they resolve, but they are never admissible as support.
    """
    tag = suffix or project_id
    refs = {
        "HYPOTHESIS": f"hypothesis:program-{tag}/h1",
        "PREDICTION": f"prediction:program-{tag}/h1/p1",
        "EVIDENCE": f"evidence:evidence-{tag}/e1",
        "CLAIM": f"claim:claim-{tag}/c1",
    }
    return MethodologyInputs(
        question=question,
        external_refs=refs,
        admission_refs=tuple(refs.values()),
        retracted_refs=tuple(retracted))


@dataclass(frozen=True, slots=True)
class SwapEvidence:
    """What the swap probe measured — two documents, one runtime."""

    first_id: str
    first_digest: str
    second_id: str
    second_digest: str
    same_runtime: bool
    first_termination: str
    second_termination: str
    first_chain: tuple[str, ...]
    second_chain: tuple[str, ...]

    def documents_differ(self) -> bool:
        return (self.first_id != self.second_id
                and self.first_digest != self.second_digest)

    def both_complete(self) -> bool:
        return (self.first_chain == CHAIN_KINDS
                and self.second_chain == CHAIN_KINDS)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "first_id": self.first_id,
            "first_digest": self.first_digest,
            "second_id": self.second_id,
            "second_digest": self.second_digest,
            "same_runtime": self.same_runtime,
            "first_termination": self.first_termination,
            "second_termination": self.second_termination,
            "first_chain": list(self.first_chain),
            "second_chain": list(self.second_chain),
            "documents_differ": self.documents_differ(),
            "both_complete": self.both_complete(),
        }


def _chain_of(run: MethodologyRun) -> tuple[str, ...]:
    reconstruction = run.reconstruction()
    if isinstance(reconstruction, ChainReconstruction):
        return reconstruction.kinds()
    return ()


def run_swap_probe(
    *,
    model: Any,
    orchestration: Any,
    project_id: str = "p-swap",
    task_id: str = "task-swap",
    lease_generation: str = "gen-swap",
    profiles: Mapping[str, Any] | None = None,
    capabilities: Any = None,
) -> SwapEvidence | MethodologyRefusal:
    """Load and run both methodologies on the same runtime instances.

    The *same* ``model``, ``orchestration``, ``profiles`` and ``capabilities``
    objects are handed to both runs — nothing is rebuilt per methodology, and
    no runtime, governance or model module is touched.
    """
    first_config = parse_methodology(dict(LITERATURE_REVIEW_DOCUMENT))
    second_config = engineering_investigation()
    first = run_methodology(
        first_config, project_id, task_id, lease_generation,
        chain_inputs(project_id, "does the effect hold across the sample?"),
        model=model, orchestration=orchestration, profiles=profiles,
        capabilities=capabilities)
    if isinstance(first, MethodologyRefusal):
        return first
    second = run_methodology(
        second_config, project_id, f"{task_id}-2", lease_generation,
        chain_inputs(project_id, "what mechanism explains the measured drift?"),
        model=model, orchestration=orchestration, profiles=profiles,
        capabilities=capabilities)
    if isinstance(second, MethodologyRefusal):
        return second
    return SwapEvidence(
        first_id=first.methodology_id,
        first_digest=first_config.digest(),
        second_id=second.methodology_id,
        second_digest=second_config.digest(),
        same_runtime=True,
        first_termination=first.termination,
        second_termination=second.termination,
        first_chain=_chain_of(first),
        second_chain=_chain_of(second))
