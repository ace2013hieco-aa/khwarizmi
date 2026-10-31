"""Methodology plane tests (R6 — substrate ontology + methodology-as-config).

Covers the plane's whole contract:

- **node inventory** — the five kinds this plane defines are exactly the chain
  steps the repo is missing; the four it references are cited by ref and never
  redefined or re-identified;
- **identity recomputed at the write boundary** — a node's id is derived from
  its content, project and producing task; a caller-supplied id is refused; the
  same content derives the same id;
- **provenance on every transition** — the edge set is derived from the nodes'
  predecessor declarations, and a transition outside the chain map, an
  unrecorded predecessor or a missing predecessor is refused;
- **project scope** — a ref that resolves in another project fails closed with
  the repo's own ``EVIDENCE_DOES_NOT_RESOLVE`` shape;
- **N9** — a retracted ref is cited, never admitted: ``RETRACTED_CITATION`` on
  an admitted ref, accepted (and flagged) on a cited one;
- **the refusal set** — unsupported claim, missing provenance, hallucinated
  evidence, circular reasoning, premature conclusion;
- **contradiction detection** as an advisory, order-independent read;
- **full reconstruction** QUESTION → … → CONCLUSION from the recorded state;
- **methodology as config** — one shipped methodology, swappable with a second
  document on the same runtime, and the module invariants that keep the plane
  out of the runtime's and governance's internals.

The plane is not an authority: nothing asserted here decides a transition, and
nothing here asserts the standing of any result.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pytest

from hermes.agents.runtime.config import load_profiles
from hermes.governance import policy as governance_policy
from hermes.methodology import substrate as substrate_module
from hermes.methodology import swap_test as swap_module
from hermes.methodology import workflows as workflows_module
from hermes.methodology.substrate import (
    ALLOWED_TRANSITIONS,
    AUTHORED_ID_KEYS,
    CHAIN_KINDS,
    CIRCULAR_REASONING,
    EVIDENCE_DOES_NOT_RESOLVE,
    MALFORMED_PAYLOAD,
    MINTED_NODE_KINDS,
    NEW_NODE_KINDS,
    PREMATURE_CONCLUSION,
    PRIOR_ART_UNBACKED,
    PROVENANCE,
    RATIONALE,
    REF_NAMESPACES,
    REFERENCED_NODE_KINDS,
    REQUIRED_PREDECESSOR,
    RETRACTED_CITATION,
    SUBSTRATE_REFUSAL_CODES,
    UNSUPPORTED_CLAIM,
    ChainReconstruction,
    RefBacking,
    SubstrateFormatError,
    SubstrateNode,
    SubstrateRefusal,
    SubstrateStore,
    check_provenance_graph,
    cited_but_inadmissible,
    detect_contradictions,
    digest_of,
    is_admissible,
    node_contradiction_id_of,
    node_id_of,
    provenance_edges,
    reconstruct_chain,
    resolve_endpoint,
    resolve_ref,
    write_node,
)
from hermes.methodology.swap_test import (
    ENGINEERING_INVESTIGATION_DOCUMENT,
    chain_inputs,
    engineering_investigation,
    fixture_provenance,
    run_swap_probe,
)
from hermes.methodology.workflows import (
    GOVERNANCE_ACTIONS,
    LITERATURE_REVIEW_DOCUMENT,
    MethodologyConfig,
    MethodologyConfigError,
    MethodologyInputs,
    MethodologyRefusal,
    MethodologyRun,
    literature_review,
    methodology_identity,
    parse_methodology,
    run_methodology,
)
from hermes.tools.models.router import ModelProposal

PACKAGE = Path(substrate_module.__file__).resolve().parent
SRC_ROOT = PACKAGE.parents[0]
PROJECT_ID = "p1"
REFS = {
    "HYPOTHESIS": "hypothesis:program-h1/h1",
    "PREDICTION": "prediction:program-h1/h1/p1",
    "EVIDENCE": "evidence:evidence-e1",
    "CLAIM": "claim:claim-c1",
}
MODEL_VENDORS = ("openai", "anthropic", "gemini", "claude", "gpt-", "llama",
                 "deepseek", "mistral", "nvidia", "qwen", "grok", "cohere")
PROHIBITED_CLAIM_WORDS = ("reproduc", "scientific", "validity", "guarantee")


# ═══════════════════════ fakes ═══════════════════════


class ScriptedModel:
    """A `ModelPort` that raises nothing and proposes nothing."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier="research",
            profile=request.profile, lease_generation="gen-1", structured={})


class RecordingApplier:
    """An Orchestration API fake — records intents, admits none by default."""

    def __init__(self) -> None:
        self.intents: list[Any] = []

    def __call__(self, intent: Any) -> Any:
        self.intents.append(intent)
        raise AssertionError(
            "the methodology probe raises no intent; a draft here is unexpected")


#: The agent's evidence ref for the plane/wiring fakes. It is admitted by the
#: model's proposal, never seeded (OPS-5D).
AGENT_EVIDENCE = "evidence:agent-e1"


class GroundedModel:
    """A ModelPort proposing the agent's evidence transition where allowed.

    The researcher (HYPOTHESIS/OBSERVATION) and verifier (EVIDENCE) profiles
    may propose EVIDENCE_TRANSITION. The selector ignores the HYPOTHESIS run
    and uses the OBSERVATION/EVIDENCE run, so the chain has an agent-derived
    evidence ref without any seed.
    """

    def __init__(self, evidence_ref: str = AGENT_EVIDENCE) -> None:
        self.calls: list[Any] = []
        self.evidence_ref = evidence_ref

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        structured: dict[str, Any] = {}
        if (request.profile in ("researcher", "verifier")
                and not any(part.origin == "runtime.review"
                            for part in request.prompt)):
            structured = {
                "kind": "EVIDENCE_TRANSITION",
                "rationale": "grounded evidence from the agent's observation",
                "payload": {
                    "evidence_artifact_ref": self.evidence_ref,
                    "from_state": "SUPPORTED",
                    "to_state": "ROBUST",
                    "rationale": "the observed source supports the rung",
                },
            }
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier="research",
            profile=request.profile, lease_generation="gen-1",
            structured=structured)


def _request_stage(request: Any) -> str:
    """The stage this request's payload names, or ``""``."""
    for part in request.prompt:
        if part.origin != "runtime.payload":
            continue
        try:
            document = json.loads(part.text)
        except ValueError:
            continue
        if isinstance(document, dict) and "stage" in document:
            return str(document["stage"])
    return ""


class ExperimentProseModel(GroundedModel):
    """GroundedModel, plus the EXPERIMENT stage's own prose.

    The fixture supplies HYPOTHESIS/PREDICTION/CLAIM through ``stage_content``;
    the experiment is left to the model, so this model proves the proposal's
    ``statement`` becomes the node's ``test``.
    """

    def invoke(self, request: Any) -> ModelProposal:
        if _request_stage(request) == "EXPERIMENT":
            self.calls.append(request)
            return ModelProposal(
                provider_id="scripted", model_id="scripted", tier="research",
                profile=request.profile,
                lease_generation=request.lease_generation,
                structured={
                    "kind": "INSERT_TASK",
                    "rationale": "the discriminating run",
                    "statement": "Run the measurement with the intervention on.",
                    "payload": {},
                })
        return super().invoke(request)


@dataclass(frozen=True, slots=True)
class _Applied:
    """The shape `run._apply` reads off an injected Orchestration API result."""

    entity_id: str
    duplicate: bool = False


class AdmittingApplier:
    """An Orchestration API fake that admits every intent and records it."""

    def __init__(self) -> None:
        self.intents: list[Any] = []

    def __call__(self, intent: Any) -> _Applied:
        self.intents.append(intent)
        return _Applied(entity_id=f"ent_{len(self.intents):04d}")


# ═══════════════════════ helpers ═══════════════════════


def _fresh(project_id: str = PROJECT_ID, *, refs: Mapping[str, str] = REFS,
           retracted: tuple[str, ...] = (),
           evidence_backing: str = "FETCHED") -> SubstrateStore:
    """A store with every fixture ref admitted, and a named backing for each.

    The evidence ref defaults to FETCHED (the fixture's source_payload stand-in)
    so a supported claim records; every other ref is ROW. Tests that need an
    all-ROW evidence pass ``evidence_backing="ROW"``.
    """
    store = SubstrateStore()
    for kind, ref in refs.items():
        origin = evidence_backing if kind == "EVIDENCE" else "ROW"
        store.admit_ref(ref, project_id,
                        backing=RefBacking(origin=origin, witness="RESOLVER"))
    for ref in retracted:
        store.retract(ref)
    return store


def _node(kind: str, *, content: Mapping[str, Any], task: str = "t",
          project_id: str = PROJECT_ID, rationale: str = "because"
          ) -> SubstrateNode:
    return SubstrateNode(kind=kind, project_id=project_id,
                         producing_task_id=task, content=dict(content),
                         rationale=rationale)


def _id_or_fail(store: SubstrateStore, node: SubstrateNode) -> str:
    recorded = write_node(store, node)
    assert isinstance(recorded, str), recorded
    return recorded


def _build_chain(store: SubstrateStore, *, project_id: str = PROJECT_ID,
                 supported: bool = True, stop_at: str = "CONCLUSION",
                 observation_admitted: tuple[str, ...] = ()
                 ) -> dict[str, str]:
    """A full, well-formed chain in ``store`` — the reconstruction fixture.

    OPS-5Y: HYPOTHESIS, PREDICTION and CLAIM are minted — each carries its own
    statement and ``origin: "MINTED"``, and none carries an ``external_ref``.
    EVIDENCE remains the one citation, backed by the refs ``_fresh`` admitted.
    ``stop_at`` cuts the fixture after the named stage (the N9 and citation
    probes need the chain *before* EVIDENCE or CLAIM).
    """
    ids: dict[str, str] = {}
    ids["QUESTION"] = _id_or_fail(store, _node(
        "QUESTION", task="t1", project_id=project_id,
        content={"question": "does the effect hold across the sample?"}))
    ids["HYPOTHESIS"] = _id_or_fail(store, _node(
        "HYPOTHESIS", task="t2", project_id=project_id,
        content={"statement": "the effect holds across the sample",
                 "origin": "MINTED",
                 "predecessors": (ids["QUESTION"],)}))
    ids["PREDICTION"] = _id_or_fail(store, _node(
        "PREDICTION", task="t3", project_id=project_id,
        content={"statement": "a larger sample shows the same effect",
                 "origin": "MINTED",
                 "predecessors": (ids["HYPOTHESIS"],)}))
    ids["EXPERIMENT"] = _id_or_fail(store, _node(
        "EXPERIMENT", task="t4", project_id=project_id,
        content={"test": "run the measurement on a larger sample",
                 "predecessors": (ids["PREDICTION"],)}))
    observation_content: dict[str, Any] = {
        "predecessors": (ids["EXPERIMENT"],),
        # An observation must cite the artifact it observed. This fixture
        # claimed to be "a full, well-formed chain" while its OBSERVATION cited
        # nothing — which is the hole the substrate now refuses, so the fixture
        # was describing a chain that could not have been built.
        "cited_refs": (REFS["EVIDENCE"],)}
    if observation_admitted:
        observation_content["admitted_refs"] = observation_admitted
    ids["OBSERVATION"] = _id_or_fail(store, _node(
        "OBSERVATION", task="t5", project_id=project_id,
        content=observation_content))
    if stop_at == "OBSERVATION":
        return ids
    ids["EVIDENCE"] = _id_or_fail(store, _node(
        "EVIDENCE", task="t6", project_id=project_id,
        content={"external_ref": REFS["EVIDENCE"],
                 "predecessors": (ids["OBSERVATION"],)}))
    if stop_at == "EVIDENCE":
        return ids
    claim_content: dict[str, Any] = {
        "statement": "the observed sample supports the effect",
        "origin": "MINTED",
        "predecessors": (ids["EVIDENCE"],)}
    if supported:
        claim_content["admitted_refs"] = (REFS["EVIDENCE"],)
    ids["CLAIM"] = _id_or_fail(store, _node(
        "CLAIM", task="t7", project_id=project_id, content=claim_content))
    if stop_at == "CLAIM":
        return ids
    ids["CRITIQUE"] = _id_or_fail(store, _node(
        "CRITIQUE", task="t8", project_id=project_id,
        content={"subject_ref": ids["CLAIM"],
                 "predecessors": (ids["CLAIM"],)}))
    ids["CONCLUSION"] = _id_or_fail(store, _node(
        "CONCLUSION", task="t9", project_id=project_id,
        content={"question_ref": ids["QUESTION"],
                 "predecessors": (ids["CRITIQUE"],)}))
    return ids


def _module_source(module: Any) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


def _package_sources() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8")
            for path in sorted(PACKAGE.glob("*.py"))}


def _hermes_imports(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names
                         if alias.name.startswith("hermes"))
        elif (isinstance(node, ast.ImportFrom) and node.module
                and node.module.startswith("hermes")):
            found.add(node.module)
    return found


def _module_imports(module: Any) -> set[str]:
    return _hermes_imports(_module_source(module))


def _imported_names(module: Any) -> set[str]:
    """Names ``module`` binds by importing (module itself, not its package)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(_module_source(module))):
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0]
                         for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _repo_codes() -> tuple[set[str], set[str]]:
    """Codes the repo defines: gateway module constants, controller literals."""
    gateway = (SRC_ROOT / "research" / "gateway.py").read_text(encoding="utf-8")
    controller = (SRC_ROOT / "research" / "controller.py").read_text(
        encoding="utf-8")
    constants = re.compile(r'^([A-Z][A-Z0-9_]*) = "([A-Z][A-Z0-9_]*)"', re.M)
    literals = re.compile(r'"([A-Z][A-Z0-9_]{2,})"')
    return ({match.group(2) for match in constants.finditer(gateway)},
            {match.group(1) for match in literals.finditer(controller)})


# ═══════════════════════ 1. node inventory ═══════════════════════


class TestNodeInventory:
    def test_the_defined_kinds_are_exactly_the_chain_steps_the_run_produces(
            self) -> None:
        assert frozenset(
            {"QUESTION", "HYPOTHESIS", "PREDICTION", "EXPERIMENT",
             "OBSERVATION", "CLAIM", "CRITIQUE", "CONCLUSION"}) == \
            NEW_NODE_KINDS
        assert frozenset({"EVIDENCE"}) == REFERENCED_NODE_KINDS
        assert frozenset({"HYPOTHESIS", "PREDICTION", "CLAIM"}) == \
            MINTED_NODE_KINDS

    def test_the_two_kind_sets_partition_the_chain(self) -> None:
        assert frozenset(CHAIN_KINDS) == NEW_NODE_KINDS | REFERENCED_NODE_KINDS
        assert not NEW_NODE_KINDS & REFERENCED_NODE_KINDS
        assert MINTED_NODE_KINDS <= NEW_NODE_KINDS

    def test_the_transition_map_is_exactly_the_chain(self) -> None:
        for index, kind in enumerate(CHAIN_KINDS[:-1]):
            assert ALLOWED_TRANSITIONS[kind] == (CHAIN_KINDS[index + 1],)
        assert ALLOWED_TRANSITIONS["CONCLUSION"] == ()
        assert {
            successor: predecessor
            for predecessor, successors in ALLOWED_TRANSITIONS.items()
            for successor in successors} == REQUIRED_PREDECESSOR

    def test_only_the_citation_kind_carries_a_ref_namespace(self) -> None:
        # OPS-5Y: REF_NAMESPACES stays the artifact-ref grammar (four
        # namespaces); EVIDENCE is the only node kind whose identity is a
        # citation. The three minted kinds cite through `cited_refs`.
        assert set(REF_NAMESPACES) >= REFERENCED_NODE_KINDS
        assert set(REF_NAMESPACES) - REFERENCED_NODE_KINDS == {
            "HYPOTHESIS", "PREDICTION", "CLAIM"}
        assert len(set(REF_NAMESPACES.values())) == len(REF_NAMESPACES)

    def test_the_plane_never_imports_the_ontology_it_references(self) -> None:
        for module in (substrate_module, workflows_module):
            imports = _module_imports(module)
            assert not [name for name in imports if name.startswith(
                "hermes.research")], imports
        assert _module_imports(substrate_module) == set()

    def test_the_plane_defines_no_existing_identity_function(self) -> None:
        source = _module_source(substrate_module)
        for name in ("program_id_of", "claim_id_of", "assumption_id_of",
                     "classification_content_hash", "ladder_state_id",
                     "obligation_transition_id", "content_hash_of"):
            assert f"def {name}(" not in source

    def test_the_package_holds_only_its_own_modules(self) -> None:
        assert sorted(_package_sources()) == [
            "__init__.py", "substrate.py", "swap_test.py", "workflows.py"]


# ═══════════════════════ 2. identity recomputed at the write boundary ══════


class TestIdentity:
    def test_a_node_id_is_derived_and_matches_the_rule(self) -> None:
        store = _fresh()
        node = _node("QUESTION", content={"question": "q?"})
        recorded = _id_or_fail(store, node)
        assert recorded.startswith("mnode_")
        assert recorded == node_id_of("QUESTION", PROJECT_ID, "t",
                                      {"question": "q?"})

    def test_the_same_content_derives_the_same_id(self) -> None:
        one = node_id_of("QUESTION", "p", "t", {"question": "q?"})
        two = node_id_of("QUESTION", "p", "t", {"question": "q?"})
        assert one == two

    def test_project_and_producing_task_are_part_of_the_identity(self) -> None:
        base = node_id_of("QUESTION", "p1", "t1", {"question": "q?"})
        assert base != node_id_of("QUESTION", "p2", "t1", {"question": "q?"})
        assert base != node_id_of("QUESTION", "p1", "t2", {"question": "q?"})

    @pytest.mark.parametrize("key", AUTHORED_ID_KEYS)
    def test_a_caller_supplied_id_is_refused(self, key: str) -> None:
        store = _fresh()
        recorded = write_node(store, _node(
            "QUESTION", content={"question": "q?", key: "mnode_forged"}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == MALFORMED_PAYLOAD
        assert "authored identity" in recorded.detail

    def test_a_refusal_is_the_documented_shape(self) -> None:
        store = _fresh()
        recorded = write_node(store, _node("QUESTION", content={}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.as_dict()["rejected"] is True
        assert set(recorded.as_dict()) == {"rejected", "code", "detail"}

    def test_the_same_node_written_twice_is_idempotent(self) -> None:
        store = _fresh()
        node = _node("QUESTION", content={"question": "q?"})
        first = _id_or_fail(store, node)
        second = _id_or_fail(store, node)
        assert first == second
        assert len(store.nodes) == 1

    def test_a_producing_task_binding_is_mandatory(self) -> None:
        store = _fresh()
        recorded = write_node(store, _node("QUESTION", task="  ",
                                           content={"question": "q?"}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == MALFORMED_PAYLOAD
        assert "producing_task_id" in recorded.detail

    def test_a_project_scope_is_mandatory(self) -> None:
        store = _fresh()
        recorded = write_node(store, _node("QUESTION", project_id="",
                                           content={"question": "q?"}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == MALFORMED_PAYLOAD
        assert "project_id" in recorded.detail

    def test_a_minted_kind_without_a_statement_is_refused(self) -> None:
        # OPS-5Y: HYPOTHESIS is no longer a citation. It is minted, and the
        # property that replaces "it must carry someone else's ref" is "it must
        # carry its own asserted content".
        store = _fresh()
        question_id = _id_or_fail(store, _node("QUESTION",
                                               content={"question": "q?"}))
        recorded = write_node(store, _node(
            "HYPOTHESIS", content={"origin": "MINTED",
                                   "predecessors": (question_id,)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == MALFORMED_PAYLOAD
        assert "statement" in recorded.detail

    def test_a_citation_must_carry_its_own_namespace(self) -> None:
        store = _fresh()
        recorded = write_node(store, _node(
            "EVIDENCE", content={"external_ref": REFS["CLAIM"]}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == MALFORMED_PAYLOAD
        assert "namespace" in recorded.detail


# ═══════════════════════ 3. provenance on every transition ═══════════════════


class TestProvenance:
    def test_edges_are_derived_from_predecessor_declarations(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        edges = provenance_edges(store)
        assert len(edges) == len(CHAIN_KINDS) - 1
        assert {edge.edge_type for edge in edges} == {
            f"{CHAIN_KINDS[index]}->{CHAIN_KINDS[index + 1]}"
            for index in range(len(CHAIN_KINDS) - 1)}
        by_target = {edge.to_ref: edge for edge in edges}
        assert by_target[ids["HYPOTHESIS"]].from_ref == ids["QUESTION"]
        assert by_target[ids["HYPOTHESIS"]].edge_type == "QUESTION->HYPOTHESIS"

    def test_an_edge_id_is_recomputed_by_rule(self) -> None:
        store = _fresh()
        _build_chain(store)
        edge = provenance_edges(store)[0]
        assert edge.edge_id().startswith("medge_")
        assert edge.edge_id() == edge.edge_id()

    def test_a_non_root_node_without_a_predecessor_is_refused(self) -> None:
        store = _fresh()
        recorded = write_node(store, _node(
            "HYPOTHESIS", content={"statement": "the conjecture",
                                   "origin": "MINTED"}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == PROVENANCE
        assert "no predecessor" in recorded.detail

    def test_a_transition_outside_the_chain_map_is_refused(self) -> None:
        store = _fresh()
        question_id = _id_or_fail(store, _node("QUESTION",
                                               content={"question": "q?"}))
        recorded = write_node(store, _node(
            "PREDICTION", content={"statement": "the prediction",
                                   "origin": "MINTED",
                                   "predecessors": (question_id,)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == PROVENANCE
        assert "not in the chain map" in recorded.detail

    def test_an_unrecorded_predecessor_is_refused(self) -> None:
        store = _fresh()
        recorded = write_node(store, _node(
            "HYPOTHESIS", content={"statement": "the conjecture",
                                   "origin": "MINTED",
                                   "predecessors": ("mnode_absent",)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == PROVENANCE
        assert "not recorded" in recorded.detail

    def test_a_cross_project_predecessor_fails_closed(self) -> None:
        store = _fresh()
        question_id = _id_or_fail(store, _node("QUESTION",
                                               content={"question": "q?"}))
        store.nodes[question_id] = SubstrateNode(
            kind="QUESTION", project_id="p2", producing_task_id="t",
            content={"question": "q?"})
        recorded = write_node(store, _node(
            "HYPOTHESIS", content={"statement": "the conjecture",
                                   "origin": "MINTED",
                                   "predecessors": (question_id,)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == EVIDENCE_DOES_NOT_RESOLVE

    def test_the_root_declares_no_predecessor(self) -> None:
        store = _fresh()
        recorded = write_node(store, _node(
            "QUESTION", content={"question": "q?",
                                 "predecessors": ("mnode_x",)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == MALFORMED_PAYLOAD


# ═══════════════════════ 4. the refusal set ═══════════════════════


class TestRefusals:
    def test_an_unsupported_claim_is_refused(self) -> None:
        store = _fresh()
        question_id = _id_or_fail(store, _node("QUESTION",
                                               content={"question": "q?"}))
        hypothesis_id = _id_or_fail(store, _node(
            "HYPOTHESIS", content={"statement": "the conjecture",
                                   "origin": "MINTED",
                                   "predecessors": (question_id,)}))
        prediction_id = _id_or_fail(store, _node(
            "PREDICTION", content={"statement": "the prediction",
                                   "origin": "MINTED",
                                   "predecessors": (hypothesis_id,)}))
        experiment_id = _id_or_fail(store, _node(
            "EXPERIMENT", content={"test": "the discriminating step",
                                    "predecessors": (prediction_id,)}))
        observation_id = _id_or_fail(store, _node(
            "OBSERVATION", content={"predecessors": (experiment_id,),
                                    "cited_refs": (REFS["EVIDENCE"],)}))
        evidence_id = _id_or_fail(store, _node(
            "EVIDENCE", content={"external_ref": REFS["EVIDENCE"],
                                 "predecessors": (observation_id,)}))
        recorded = write_node(store, _node(
            "CLAIM", content={"statement": "the claim",
                              "origin": "MINTED",
                              "predecessors": (evidence_id,)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == UNSUPPORTED_CLAIM
        assert "admitted evidence" in recorded.detail

    def test_a_supported_claim_is_recorded(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        assert ids["CLAIM"].startswith("mnode_")

    def test_hallucinated_evidence_is_refused(self) -> None:
        store = _fresh()
        recorded = write_node(store, _node(
            "QUESTION", content={"question": "q?",
                                 "admitted_refs": ("evidence:never-seen",)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == EVIDENCE_DOES_NOT_RESOLVE
        assert "does not resolve" in recorded.detail

    def test_a_ref_with_no_known_namespace_does_not_resolve(self) -> None:
        store = _fresh()
        outcome = resolve_ref(store, PROJECT_ID, "mystery:thing")
        assert isinstance(outcome, SubstrateRefusal)
        assert outcome.code == EVIDENCE_DOES_NOT_RESOLVE

    def test_cross_project_citation_fails_closed(self) -> None:
        store = _fresh()
        store.admit_ref("claim:foreign", "p2", backing=RefBacking("ROW", "RESOLVER"))
        recorded = write_node(store, _node(
            "QUESTION", content={"question": "q?",
                                 "admitted_refs": ("claim:foreign",)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == EVIDENCE_DOES_NOT_RESOLVE
        assert "project-scoped" in recorded.detail

    def test_n9_a_retracted_ref_is_refused_as_support(self) -> None:
        store = _fresh(retracted=(REFS["EVIDENCE"],))
        recorded = write_node(store, _node(
            "QUESTION", content={"question": "q?",
                                 "admitted_refs": (REFS["EVIDENCE"],)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == RETRACTED_CITATION
        assert is_admissible(store, PROJECT_ID, REFS["EVIDENCE"]) is False

    def test_n9_a_retracted_ref_may_still_be_cited(self) -> None:
        store = _fresh(retracted=(REFS["EVIDENCE"],))
        recorded = _id_or_fail(store, _node(
            "QUESTION", content={"question": "q?",
                                 "cited_refs": (REFS["EVIDENCE"],)}))
        node = store.nodes[recorded]
        assert node.cited_refs() == (REFS["EVIDENCE"],)
        assert cited_but_inadmissible(store, node) == (REFS["EVIDENCE"],)

    def test_n9_a_retracted_claim_breaks_the_supported_claim(self) -> None:
        # The chain records EVIDENCE while its ref is admissible; the source is
        # then retracted, and the claim that admits it refuses. The claim is
        # minted (OPS-5Y); support is still the admitted evidence ref.
        store = _fresh()
        ids = _build_chain(store, stop_at="EVIDENCE")
        store.retract(REFS["EVIDENCE"])
        recorded = write_node(store, _node(
            "CLAIM", content={"statement": "the claim",
                              "origin": "MINTED",
                              "admitted_refs": (REFS["EVIDENCE"],),
                              "predecessors": (ids["EVIDENCE"],)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == RETRACTED_CITATION

    def test_circular_reasoning_is_refused(self) -> None:
        # A cycle cannot be created through `write_node` — a node's identity is
        # derived from content that cannot name the id it will receive — so it
        # is built directly here: two recorded nodes that name each other as
        # predecessor. The fail-closed floor reports it and refuses every
        # further write onto the store.
        first = _node("HYPOTHESIS",
                      content={"statement": "the conjecture",
                               "origin": "MINTED",
                               "predecessors": ("mnode_second",)})
        second = _node("PREDICTION",
                       content={"statement": "the prediction",
                                "origin": "MINTED",
                                "predecessors": ("mnode_first",)})
        cyclic = SubstrateStore(nodes={"mnode_first": first,
                                       "mnode_second": second})
        reported = check_provenance_graph(cyclic)
        assert isinstance(reported, SubstrateRefusal)
        assert reported.code == CIRCULAR_REASONING
        further = write_node(cyclic, _node("QUESTION",
                                           content={"question": "other?"}))
        assert isinstance(further, SubstrateRefusal)
        assert further.code == CIRCULAR_REASONING

    def test_an_acyclic_store_reports_no_cycle(self) -> None:
        store = _fresh()
        _build_chain(store)
        assert check_provenance_graph(store) is None

    def test_a_premature_conclusion_is_refused(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        foreign = _id_or_fail(store, _node(
            "QUESTION", task="tz", content={"question": "a different question?"}))
        recorded = write_node(store, _node(
            "CONCLUSION", task="ty",
            content={"question_ref": foreign,
                     "predecessors": (ids["CRITIQUE"],)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == PREMATURE_CONCLUSION
        assert "not in its own lineage" in recorded.detail

    def test_the_refusal_vocabulary_is_closed_and_grounded(self) -> None:
        gateway_codes, controller_codes = _repo_codes()
        assert MALFORMED_PAYLOAD in gateway_codes
        assert PROVENANCE in gateway_codes
        assert RATIONALE in controller_codes
        assert frozenset({
            MALFORMED_PAYLOAD, RATIONALE, PROVENANCE,
            EVIDENCE_DOES_NOT_RESOLVE, UNSUPPORTED_CLAIM,
            PREMATURE_CONCLUSION, CIRCULAR_REASONING, RETRACTED_CITATION,
            PRIOR_ART_UNBACKED}) == SUBSTRATE_REFUSAL_CODES

    def test_the_planes_own_codes_do_not_redefine_a_repo_code(self) -> None:
        gateway_codes, controller_codes = _repo_codes()
        own = {UNSUPPORTED_CLAIM, PREMATURE_CONCLUSION, CIRCULAR_REASONING,
               RETRACTED_CITATION, PRIOR_ART_UNBACKED}
        assert not own & gateway_codes
        assert not own & controller_codes
        others: dict[str, list[str]] = {code: [] for code in own}
        for path in sorted((SRC_ROOT).rglob("*.py")):
            if path.parent == PACKAGE:
                continue
            text = path.read_text(encoding="utf-8")
            for code in own:
                if code in text:
                    others[code].append(path.name)
        assert all(not names for names in others.values()), others

    def test_evidence_does_not_resolve_is_the_repos_own_code(self) -> None:
        text = (SRC_ROOT / "research" / "failure_classification.py").read_text(
            encoding="utf-8")
        assert '"EVIDENCE_DOES_NOT_RESOLVE"' in text

    # ── P1 (items 4+6): a citation's own external_ref is resolved ──

    def test_a_hallucinated_external_ref_is_refused(self) -> None:
        # EVIDENCE is the one citation kind: its own external_ref must resolve
        # under admission semantics, so a ref nobody observed fails closed
        # instead of being recorded.
        store = _fresh()
        ids = _build_chain(store, stop_at="OBSERVATION")
        recorded = write_node(store, _node(
            "EVIDENCE", content={"external_ref": "evidence:never-seen",
                                 "predecessors": (ids["OBSERVATION"],)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == EVIDENCE_DOES_NOT_RESOLVE
        assert "does not resolve" in recorded.detail

    def test_a_foreign_external_ref_fails_closed(self) -> None:
        # Identical bytes owned by another project: the citation's own ref is
        # resolved in *this* project and fails closed across projects.
        store = _fresh()
        store.admit_ref("evidence:foreign", "p2", backing=RefBacking("ROW", "RESOLVER"))
        ids = _build_chain(store, stop_at="OBSERVATION")
        recorded = write_node(store, _node(
            "EVIDENCE", content={"external_ref": "evidence:foreign",
                                 "predecessors": (ids["OBSERVATION"],)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == EVIDENCE_DOES_NOT_RESOLVE
        assert "project-scoped" in recorded.detail

    def test_a_retracted_external_ref_is_refused(self) -> None:
        # N9 on the citation's own ref: a retracted ref is never admitted as
        # support, and it is nowhere invisible on the position that carries it.
        store = _fresh(retracted=(REFS["EVIDENCE"],))
        ids = _build_chain(store, stop_at="OBSERVATION")
        recorded = write_node(store, _node(
            "EVIDENCE", content={"external_ref": REFS["EVIDENCE"],
                                 "predecessors": (ids["OBSERVATION"],)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == RETRACTED_CITATION
        assert is_admissible(store, PROJECT_ID, REFS["EVIDENCE"]) is False

    # ── P2 item 3: a node may not admit its own external ref ──

    def test_a_node_cannot_admit_its_own_external_ref(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        recorded = write_node(store, _node(
            "EVIDENCE", task="t-self",
            content={"external_ref": REFS["EVIDENCE"],
                     "admitted_refs": (REFS["EVIDENCE"],),
                     "predecessors": (ids["OBSERVATION"],)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == CIRCULAR_REASONING
        assert "itself" in recorded.detail

    # ── P2 item 4X: a CRITIQUE's subject_ref is dereferenced ──

    def test_a_critique_with_a_ghost_subject_is_refused(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        recorded = write_node(store, _node(
            "CRITIQUE", task="t-ghost",
            content={"subject_ref": "mnode_ghost",
                     "predecessors": (ids["CLAIM"],)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == PROVENANCE
        assert "not recorded" in recorded.detail

    def test_a_critique_with_a_foreign_subject_fails_closed(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        store.nodes["mnode_foreign"] = SubstrateNode(
            kind="CLAIM", project_id="p2", producing_task_id="t",
            content={})
        recorded = write_node(store, _node(
            "CRITIQUE", task="t-foreign",
            content={"subject_ref": "mnode_foreign",
                     "predecessors": (ids["CLAIM"],)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == EVIDENCE_DOES_NOT_RESOLVE

    def test_resolve_endpoint_resolves_a_recorded_node(self) -> None:
        # `resolve_endpoint` is wired into the critique subject check above; it
        # is also a public read in its own right, pinned here.
        store = _fresh()
        ids = _build_chain(store)
        assert resolve_endpoint(store, PROJECT_ID, ids["CLAIM"]) == ids["CLAIM"]
        missing = resolve_endpoint(store, PROJECT_ID, "mnode_absent")
        assert isinstance(missing, SubstrateRefusal)
        assert missing.code == PROVENANCE

    # ── R6-FIX2 (E3): external_ref discipline is total in both directions ──
    #
    # The shape rule (`substrate._kind_refusal`) refuses a locally-defined kind
    # carrying a non-empty ``external_ref`` with ``MALFORMED_PAYLOAD`` —
    # ``external_ref`` is the citation key for *existing-kind* artifacts only.
    # Referenced kinds keep the existing require-non-empty + namespace match.
    # The legal-state pins below are one per local kind, in both directions,
    # so neither half can silently regress without a test turning red.

    @pytest.mark.parametrize("kind,extra",
                             [("QUESTION", {"question": "q?"}),
                              ("HYPOTHESIS", {"statement": "s",
                                              "origin": "MINTED"}),
                              ("PREDICTION", {"statement": "p",
                                              "origin": "MINTED"}),
                              ("EXPERIMENT", {}),
                              ("OBSERVATION", {}),
                              ("CRITIQUE",
                               {"subject_ref": "mnode_x"}),
                              ("CLAIM", {"statement": "c",
                                         "origin": "MINTED"}),
                              ("CONCLUSION",
                               {"question_ref": "mnode_x"})])
    def test_a_locally_defined_kind_with_a_nonempty_external_ref_is_refused(
            self, kind: str, extra: Mapping[str, Any]) -> None:
        # A local kind carrying a citation-shaped external_ref fails the shape
        # gate: locally-defined nodes carry their content inline; ``external_ref``
        # is for cited existing-kind artifacts only.
        store = _fresh()
        recorded = write_node(store, _node(
            kind, task="t-local-ext",
            content={**extra, "external_ref": "evidence:any/e1"}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == MALFORMED_PAYLOAD
        assert "locally-defined" in recorded.detail
        assert "inline" in recorded.detail

    @pytest.mark.parametrize("kind,content",
                             [("QUESTION", {"question": "q?"}),
                              ("EXPERIMENT", {}),
                              ("OBSERVATION", {}),
                              ("CRITIQUE",
                               {"subject_ref": "mnode_x"}),
                              ("CONCLUSION",
                               {"question_ref": "mnode_x"})])
    def test_a_locally_defined_kind_with_no_external_ref_is_admitted(
            self, kind: str, content: Mapping[str, Any]) -> None:
        # E2 adjudication: a local kind with an absent or empty external_ref
        # is a *correct* admission (its content is carried inline). This is the
        # legal-state pin — without it, a future "fix" that flipped local-kind
        # ext-required to ext-forbidden would not surface here.
        store = _fresh()
        # For CRITIQUE / CONCLUSION / EXPERIMENT / OBSERVATION we need a
        # recorded predecessor and (for CRITIQUE / CONCLUSION) a recorded
        # subject / question; build the chain up to the relevant predecessor
        # and then write the new node, with no ``external_ref`` at all.
        if kind == "QUESTION":
            body = dict(content)
        elif kind in {"EXPERIMENT", "OBSERVATION"}:
            ids = _build_chain(store)
            pred = ids["PREDICTION"] if kind == "EXPERIMENT" else ids["EXPERIMENT"]
            body = {"predecessors": (pred,)}
            if kind == "EXPERIMENT":
                # The pin is about external_ref, not content — but an
                # experiment must still say what it would run.
                body["test"] = "the discriminating step"
            if kind == "OBSERVATION":
                # The pin is about external_ref, not content — but an
                # observation must still cite what it observed.
                body["cited_refs"] = (REFS["EVIDENCE"],)
        elif kind == "CRITIQUE":
            ids = _build_chain(store)
            body = {"subject_ref": ids["CLAIM"],
                    "predecessors": (ids["CLAIM"],)}
        elif kind == "CONCLUSION":
            ids = _build_chain(store)
            body = {"question_ref": ids["QUESTION"],
                    "predecessors": (ids["CRITIQUE"],)}
        else:
            body = {}
        assert "external_ref" not in body, (
            f"the local-kind pin body must carry no external_ref at all; "
            f"{kind} body is {body}")
        recorded = write_node(store, _node(kind, task="t-local-noext",
                                           content=body))
        assert isinstance(recorded, str), (
            f"{kind} with no external_ref must be admitted as a legal-state "
            f"pin; got {recorded!r}")
        assert recorded.startswith("mnode_")

    @pytest.mark.parametrize("kind",
                             sorted(REFERENCED_NODE_KINDS))
    def test_a_referenced_kind_with_an_empty_external_ref_is_refused(
            self, kind: str) -> None:
        # E2 adjudication: the existing-rule side is already pinned by
        # ``test_an_existing_kind_node_cannot_be_minted_only_cited``; this
        # parametrises it across every referenced kind so a future
        # kind-specific exception surfaces here.
        store = _fresh()
        recorded = write_node(store, _node(
            kind, task=f"t-{kind}-empty",
            content={"external_ref": ""}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == MALFORMED_PAYLOAD
        assert "external_ref" in recorded.detail

    @pytest.mark.parametrize("kind",
                             sorted(REFERENCED_NODE_KINDS))
    def test_a_referenced_kind_with_a_wrong_namespace_is_refused(
            self, kind: str) -> None:
        # The existing-rule side, namespace mismatch — already pinned by
        # ``test_a_citation_must_carry_its_own_namespace``; this parametrises
        # it across every referenced kind.
        store = _fresh()
        wrong = next(ref for ref_kind, ref in REFS.items() if ref_kind != kind)
        recorded = write_node(store, _node(
            kind, task=f"t-{kind}-wrong-ns",
            content={"external_ref": wrong}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == MALFORMED_PAYLOAD
        assert "namespace" in recorded.detail


# ═══════════════════════ 5. the minted kinds (OPS-5Y) ═══════════════════════


class TestMintedKinds:
    """HYPOTHESIS, PREDICTION and CLAIM carry inline content, never a citation."""

    def test_each_minted_kind_records_inline_content(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        for kind in ("HYPOTHESIS", "PREDICTION", "CLAIM"):
            node = store.nodes[ids[kind]]
            assert node.content["origin"] == "MINTED"
            assert isinstance(node.content["statement"], str)
            assert node.content["statement"].strip()
            assert "external_ref" not in node.content

    def test_a_minted_kind_needs_the_minted_origin(self) -> None:
        store = _fresh()
        question_id = _id_or_fail(store, _node("QUESTION",
                                               content={"question": "q?"}))
        for origin in ("", "FETCHED", "PRIOR_ART"):
            recorded = write_node(store, _node(
                "HYPOTHESIS", task=f"t-{origin or 'absent'}",
                content={"statement": "the conjecture", "origin": origin,
                         "predecessors": (question_id,)}))
            assert isinstance(recorded, SubstrateRefusal)
            assert recorded.code == MALFORMED_PAYLOAD
            assert "origin" in recorded.detail

    def test_a_conjecture_may_not_admit_support(self) -> None:
        store = _fresh()
        question_id = _id_or_fail(store, _node("QUESTION",
                                               content={"question": "q?"}))
        recorded = write_node(store, _node(
            "HYPOTHESIS", content={"statement": "the conjecture",
                                   "origin": "MINTED",
                                   "admitted_refs": (REFS["EVIDENCE"],),
                                   "predecessors": (question_id,)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == MALFORMED_PAYLOAD
        assert "admitted_refs" in recorded.detail

    def test_a_claim_may_admit_only_evidence_refs(self) -> None:
        store = _fresh()
        ids = _build_chain(store, stop_at="EVIDENCE")
        recorded = write_node(store, _node(
            "CLAIM", content={"statement": "the claim", "origin": "MINTED",
                              "admitted_refs": (REFS["CLAIM"],),
                              "predecessors": (ids["EVIDENCE"],)}))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == MALFORMED_PAYLOAD
        assert "evidence:" in recorded.detail

    def test_a_minted_node_may_cite_a_prior_art_ref(self) -> None:
        store = _fresh()
        question_id = _id_or_fail(store, _node("QUESTION",
                                               content={"question": "q?"}))
        recorded = _id_or_fail(store, _node(
            "HYPOTHESIS", content={"statement": "the conjecture",
                                   "origin": "MINTED",
                                   "cited_refs": (REFS["CLAIM"],),
                                   "predecessors": (question_id,)}))
        node = store.nodes[recorded]
        assert node.cited_refs() == (REFS["CLAIM"],)
        assert "external_ref" not in node.content


# ═══════════════════════ 6. direct support — D(C) (OPS-5Y) ══════════════════


class TestDirectSupport:
    """The claim's own admitted refs and its EVIDENCE predecessor's citation.

    The wider closure is computed only to explain a refusal; it is never the
    sufficiency test.
    """

    def _minted_claim(self, ids: Mapping[str, str],
                      admitted: tuple[str, ...], task: str = "t-claim"
                      ) -> SubstrateNode:
        return _node(
            "CLAIM", task=task,
            content={"statement": "the observed sample supports the effect",
                     "origin": "MINTED",
                     "admitted_refs": admitted,
                     "predecessors": (ids["EVIDENCE"],)})

    def test_an_all_row_support_graph_is_refused(self) -> None:
        # Falsifier: every direct ref is ROW-backed. The claim refuses even
        # though it admits a real, resolving evidence ref.
        store = _fresh(evidence_backing="ROW")
        ids = _build_chain(store, stop_at="EVIDENCE")
        recorded = write_node(store, self._minted_claim(
            ids, (REFS["EVIDENCE"],)))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == UNSUPPORTED_CLAIM
        assert "direct support" in recorded.detail
        assert "capability:source_fetch" in recorded.detail
        assert f"{REFS['EVIDENCE']} (ROW)" in recorded.detail

    def test_a_fetched_artifact_elsewhere_does_not_launder_row_support(
            self) -> None:
        # The review's laundering case: a fetched artifact is an ancestor's
        # admission. It is in S(C), not in D(C), so the claim still refuses and
        # the detail names the wider closure as explanation only.
        fetched_elsewhere = "evidence:z-fetched"
        store = _fresh(evidence_backing="ROW")
        store.admit_ref(fetched_elsewhere, PROJECT_ID,
                        backing=RefBacking("FETCHED", "RESOLVER"))
        ids = _build_chain(store, stop_at="EVIDENCE",
                           observation_admitted=(fetched_elsewhere,))
        recorded = write_node(store, self._minted_claim(
            ids, (REFS["EVIDENCE"],)))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == UNSUPPORTED_CLAIM
        assert fetched_elsewhere in recorded.detail
        assert "wider closure" in recorded.detail
        assert "reachability is not support" in recorded.detail

    def test_a_fetched_direct_admission_records(self) -> None:
        # The other half of the falsifier: the same shape with a FETCHED
        # direct ref records.
        store = _fresh()  # the evidence ref is FETCHED
        ids = _build_chain(store, stop_at="EVIDENCE")
        recorded = write_node(store, self._minted_claim(
            ids, (REFS["EVIDENCE"],)))
        assert isinstance(recorded, str), recorded

    def test_the_evidence_predecessor_alone_anchors_the_claim(self) -> None:
        # D(C) includes the direct EVIDENCE predecessor's citation even when
        # the claim's admitted set names a different (ROW) ref. Here the
        # predecessor cites the FETCHED ref, so the claim records.
        store = _fresh()
        ids = _build_chain(store, stop_at="EVIDENCE")
        other = "evidence:other-row"
        store.admit_ref(other, PROJECT_ID, backing=RefBacking("ROW", "RESOLVER"))
        recorded = write_node(store, self._minted_claim(ids, (other,)))
        assert isinstance(recorded, str), recorded

    def test_no_admitted_evidence_is_refused_exactly_as_before(self) -> None:
        # The D(C) change narrows the invariant; it does not replace the old
        # no-admitted-evidence refusal (the same code and the same sentence).
        store = _fresh()
        ids = _build_chain(store, stop_at="EVIDENCE")
        recorded = write_node(store, self._minted_claim(ids, ()))
        assert isinstance(recorded, SubstrateRefusal)
        assert recorded.code == UNSUPPORTED_CLAIM
        assert recorded.detail.startswith(
            "a CLAIM carries no admitted evidence ref")


# ═══════════════════════ 7. contradiction detection ═══════════════════════


class TestContradictionDetection:
    def _two_critiques(self, store: SubstrateStore, ids: dict[str, str],
                       first: str, second: str, task_a: str = "ta",
                       task_b: str = "tb") -> None:
        _id_or_fail(store, _node(
            "CRITIQUE", task=task_a,
            content={"subject_ref": ids["CLAIM"], "assertion": first,
                     "predecessors": (ids["CLAIM"],)}))
        _id_or_fail(store, _node(
            "CRITIQUE", task=task_b,
            content={"subject_ref": ids["CLAIM"], "assertion": second,
                     "predecessors": (ids["CLAIM"],)}))

    def test_opposing_assertions_about_one_subject_are_reported(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        self._two_critiques(store, ids, "SUPPORTS", "REFUTES")
        found = detect_contradictions(store)
        assert len(found) == 1
        assert found[0].subject_ref == ids["CLAIM"]
        assert {found[0].assertion_a, found[0].assertion_b} == {
            "SUPPORTS", "REFUTES"}

    def test_the_pair_id_is_order_independent(self) -> None:
        assert node_contradiction_id_of("a", "b") == \
            node_contradiction_id_of("b", "a")
        assert node_contradiction_id_of("a", "b").startswith("mcon_")

    def test_agreement_is_not_a_contradiction(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        self._two_critiques(store, ids, "SUPPORTS", "SUPPORTS")
        assert detect_contradictions(store) == ()

    def test_detection_is_a_read_and_idempotent(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        self._two_critiques(store, ids, "SUPPORTS", "REFUTES")
        before = store.to_mapping()
        assert detect_contradictions(store) == detect_contradictions(store)
        assert store.to_mapping() == before

    def test_detection_is_project_scoped(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        self._two_critiques(store, ids, "SUPPORTS", "REFUTES")
        assert detect_contradictions(store, project_id="p-other") == ()


# ═══════════════════════ 6. reconstruction ═══════════════════════


class TestReconstruction:
    def test_the_full_chain_reconstructs_from_the_recorded_state(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        result = reconstruct_chain(store, ids["QUESTION"])
        assert isinstance(result, ChainReconstruction)
        assert result.complete() is True
        assert result.kinds() == CHAIN_KINDS
        assert result.conclusion_id() == ids["CONCLUSION"]

    def test_reconstruction_reads_state_only(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        reloaded = SubstrateStore.from_mapping(store.to_mapping())
        first = reconstruct_chain(store, ids["QUESTION"])
        second = reconstruct_chain(reloaded, ids["QUESTION"])
        assert isinstance(first, ChainReconstruction)
        assert isinstance(second, ChainReconstruction)
        assert first.digest() == second.digest()

    def test_reconstruction_is_deterministic(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        first = reconstruct_chain(store, ids["QUESTION"])
        second = reconstruct_chain(store, ids["QUESTION"])
        assert isinstance(first, ChainReconstruction)
        assert isinstance(second, ChainReconstruction)
        assert first.to_mapping() == second.to_mapping()

    def test_an_unknown_question_refuses(self) -> None:
        store = _fresh()
        _build_chain(store)
        outcome = reconstruct_chain(store, "mnode_absent")
        assert isinstance(outcome, SubstrateRefusal)
        assert outcome.code == PROVENANCE

    def test_a_missing_stage_refuses(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        del store.nodes[ids["OBSERVATION"]]
        outcome = reconstruct_chain(store, ids["QUESTION"])
        assert isinstance(outcome, SubstrateRefusal)
        assert outcome.code == PROVENANCE

    def test_an_ambiguous_stage_is_refused(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        _id_or_fail(store, _node(
            "CRITIQUE", task="t-extra",
            content={"subject_ref": ids["CLAIM"],
                     "predecessors": (ids["CLAIM"],)}))
        outcome = reconstruct_chain(store, ids["QUESTION"])
        assert isinstance(outcome, SubstrateRefusal)
        assert outcome.code == MALFORMED_PAYLOAD

    def test_a_forged_record_does_not_reconstruct(self) -> None:
        store = _fresh()
        ids = _build_chain(store)
        store.nodes[ids["PREDICTION"]] = SubstrateNode(
            kind="PREDICTION", project_id=PROJECT_ID, producing_task_id="t3",
            content={"external_ref": REFS["PREDICTION"] + "-tampered",
                     "predecessors": (ids["HYPOTHESIS"],)})
        outcome = reconstruct_chain(store, ids["QUESTION"])
        assert isinstance(outcome, SubstrateRefusal)
        assert outcome.code == MALFORMED_PAYLOAD
        assert "establish its own identity" in outcome.detail

    def test_a_store_round_trips_its_closed_mapping(self) -> None:
        store = _fresh()
        _build_chain(store)
        body = store.to_mapping()
        assert SubstrateStore.from_mapping(body).to_mapping() == body
        with pytest.raises(SubstrateFormatError):
            SubstrateStore.from_mapping({"nodes": {}, "surprise": 1})

    def test_a_forged_root_does_not_reconstruct(self) -> None:
        # The root QUESTION is re-derived at the reconstruction boundary, not
        # trusted from the caller's key.
        store = _fresh()
        ids = _build_chain(store)
        store.nodes[ids["QUESTION"]] = SubstrateNode(
            kind="QUESTION", project_id=PROJECT_ID, producing_task_id="t1",
            content={"question": "TAMPERED QUESTION?"})
        outcome = reconstruct_chain(store, ids["QUESTION"])
        assert isinstance(outcome, SubstrateRefusal)
        assert outcome.code == MALFORMED_PAYLOAD
        assert "establish its own identity" in outcome.detail

    def test_from_mapping_refuses_a_forged_key(self) -> None:
        # A mapping key is not trusted: a record whose content does not derive
        # the key it is stored under never enters the store.
        store = _fresh()
        _build_chain(store)
        body = store.to_mapping()
        real = sorted(body["nodes"])[0]
        body["nodes"]["mnode_forged"] = body["nodes"].pop(real)
        with pytest.raises(SubstrateFormatError) as error:
            SubstrateStore.from_mapping(body)
        assert "disagrees with the id its content derives" in str(error.value)


# ═══════════════════════ 7. methodology as config ═══════════════════════


class TestMethodologyConfig:
    def test_exactly_one_methodology_ships(self) -> None:
        assert literature_review().methodology_id == "literature-review"
        assert engineering_investigation().methodology_id == \
            "engineering-investigation"

    def test_the_shipped_methodology_loads_and_is_versioned(self) -> None:
        config = literature_review()
        # OPS-5F: document version 2 declared a per-stage tick budget and each
        # stage's objective. OPS-5Y: version 3 asks the three minted stages for
        # a statement instead of a citation identity that has no producer.
        assert config.version == "3"
        assert config.stage_kinds() == CHAIN_KINDS
        assert config.termination.max_stages == len(CHAIN_KINDS)
        assert methodology_identity(config).startswith("mth_")

    def test_the_config_digest_tracks_the_document(self) -> None:
        config = literature_review()
        assert config.digest() == config.digest()
        assert config.digest() == digest_of(config.to_mapping())
        other = dict(LITERATURE_REVIEW_DOCUMENT)
        other["version"] = "4"
        assert parse_methodology(other).digest() != config.digest()

    def test_every_stage_names_a_real_governance_action(self) -> None:
        for config in (literature_review(), engineering_investigation()):
            for stage in config.stages:
                if stage.governance_action:
                    assert stage.governance_action in GOVERNANCE_ACTIONS

    def test_the_config_round_trips_its_closed_mapping(self) -> None:
        config = literature_review()
        assert parse_methodology(config.to_mapping()).to_mapping() == \
            config.to_mapping()

    def test_an_unknown_key_is_refused(self) -> None:
        body = dict(LITERATURE_REVIEW_DOCUMENT)
        body["surprise"] = 1
        with pytest.raises(MethodologyConfigError):
            parse_methodology(body)

    def test_a_stage_out_of_chain_order_is_refused(self) -> None:
        body = dict(LITERATURE_REVIEW_DOCUMENT)
        stages = list(body["stages"])
        stages[1], stages[2] = stages[2], stages[1]
        body["stages"] = stages
        with pytest.raises(MethodologyConfigError):
            parse_methodology(body)

    def test_a_conclusion_without_its_lineage_is_refused(self) -> None:
        body = dict(LITERATURE_REVIEW_DOCUMENT)
        body["stages"] = [stage for stage in body["stages"]
                          if stage["stage"] != "EXPERIMENT"]
        with pytest.raises(MethodologyConfigError) as error:
            parse_methodology(body)
        assert "lineage" in str(error.value)

    def test_an_unknown_governance_action_is_refused(self) -> None:
        body = dict(LITERATURE_REVIEW_DOCUMENT)
        stages = [dict(stage) for stage in body["stages"]]
        stages[0]["governance_action"] = "DO_SOMETHING_NEW"
        body["stages"] = stages
        with pytest.raises(MethodologyConfigError):
            parse_methodology(body)

    def test_an_unsupported_schema_version_is_refused(self) -> None:
        body = dict(LITERATURE_REVIEW_DOCUMENT)
        body["schema_version"] = "99"
        with pytest.raises(MethodologyConfigError):
            parse_methodology(body)

    def test_the_config_names_no_profile_class_only_profile_names(self) -> None:
        declared = set(load_profiles())
        for config in (literature_review(), engineering_investigation()):
            assert all(isinstance(stage.profile, str) for stage in config.stages)
            assert set(config.profiles()) <= declared

    def test_a_declared_toolset_is_refused(self) -> None:
        # The plane cannot enforce a toolset (the runtime's run() exposes no
        # toolset surface), so a declared one is an inert control and is refused
        # at load — never parsed and silently ignored.
        with_toolset_stage = dict(LITERATURE_REVIEW_DOCUMENT)
        stages = [dict(stage) for stage in with_toolset_stage["stages"]]
        stages[1]["toolset"] = ["source_search"]
        with_toolset_stage["stages"] = stages
        with pytest.raises(MethodologyConfigError) as stage_error:
            parse_methodology(with_toolset_stage)
        assert "toolset" in str(stage_error.value)
        with_toolset_doc = dict(LITERATURE_REVIEW_DOCUMENT)
        with_toolset_doc["toolset"] = ["source_search"]
        with pytest.raises(MethodologyConfigError) as doc_error:
            parse_methodology(with_toolset_doc)
        assert "toolset" in str(doc_error.value)


# ═══════════════════════ 8. the methodology swap ═══════════════════════


class TestMethodologySwap:
    def test_a_second_methodology_loads_and_runs_on_the_same_runtime(self) -> None:
        model = GroundedModel()
        orchestration = AdmittingApplier()
        profiles = load_profiles()
        evidence = run_swap_probe(model=model, orchestration=orchestration,
                                  profiles=profiles)
        assert not isinstance(evidence, MethodologyRefusal)
        assert evidence.documents_differ() is True
        assert evidence.same_runtime is True
        assert evidence.both_complete() is True
        assert evidence.first_chain == CHAIN_KINDS
        assert evidence.second_chain == CHAIN_KINDS

    def test_the_swap_touches_no_runtime_governance_or_model_module(self) -> None:
        source = _module_source(swap_module)
        imported = _hermes_imports(source)
        assert imported == {
            "hermes.methodology.substrate", "hermes.methodology.workflows"}
        assert "run(" not in source.replace("run_methodology(", "").replace(
            "run_swap_probe(", "")

    def test_the_two_documents_differ_only_as_configuration(self) -> None:
        first = literature_review()
        second = engineering_investigation()
        assert first.profiles() != second.profiles()
        assert first.termination != second.termination
        assert first.digest() != second.digest()

    def test_the_swap_probe_uses_the_same_model_object(self) -> None:
        model = GroundedModel()
        evidence = run_swap_probe(model=model, orchestration=AdmittingApplier(),
                                  profiles=load_profiles())
        assert not isinstance(evidence, MethodologyRefusal)
        assert model.call_count >= len(CHAIN_KINDS) * 2

    def test_the_swap_fixture_is_the_only_second_document(self) -> None:
        assert ENGINEERING_INVESTIGATION_DOCUMENT["methodology_id"] != \
            LITERATURE_REVIEW_DOCUMENT["methodology_id"]


# ═══════════════════════ 9. the driver ═══════════════════════


class TestMethodologyRun:
    def _run(self, config: MethodologyConfig, project_id: str = "p-run",
             inputs: MethodologyInputs | None = None, *,
             model: Any = None, orchestration: Any = None,
             provenance: Any = fixture_provenance
             ) -> MethodologyRun | MethodologyRefusal:
        return run_methodology(
            config, project_id, "task-run", "gen-1",
            inputs if inputs is not None
            else chain_inputs(project_id, "does it hold?"),
            model=GroundedModel() if model is None else model,
            orchestration=(AdmittingApplier() if orchestration is None
                           else orchestration),
            profiles=load_profiles(),
            provenance_of=provenance)

    def test_the_driver_runs_every_stage_through_the_runtime(self) -> None:
        run = self._run(literature_review())
        assert isinstance(run, MethodologyRun)
        assert run.termination == "COMPLETE"
        assert [stage.stage for stage in run.stages] == list(CHAIN_KINDS)
        assert all(stage.run_digest for stage in run.stages)

    def test_the_driver_records_a_reconstructable_chain(self) -> None:
        run = self._run(literature_review())
        assert isinstance(run, MethodologyRun)
        result = run.reconstruction()
        assert isinstance(result, ChainReconstruction)
        assert result.kinds() == CHAIN_KINDS
        assert result.complete() is True

    def test_the_experiment_records_the_test_the_model_proposed(self) -> None:
        """OPS-5ZM: the stage's prose arrives on the proposal's `statement`
        and lands on the node as `test`; the node never carries a minted
        `statement`/`origin` pair for an experiment."""
        base = chain_inputs("p-experiment-prose", "does it hold?")
        inputs = MethodologyInputs(
            question=base.question,
            stage_content={kind: dict(content)
                           for kind, content in base.stage_content.items()
                           if kind != "EXPERIMENT"})
        run = self._run(literature_review(),
                        project_id="p-experiment-prose", inputs=inputs,
                        model=ExperimentProseModel())
        assert isinstance(run, MethodologyRun), run
        experiment = run.store.nodes_of_kind("EXPERIMENT")[0][1]
        assert experiment.content["test"] == (
            "Run the measurement with the intervention on.")
        assert "statement" not in experiment.content
        assert "origin" not in experiment.content

    def test_a_row_backed_evidence_ref_stops_the_chain_at_claim(self) -> None:
        # The EVIDENCE node records (a citation may be ROW), and the claim
        # refuses: support needs a fetched anchor in D(C).
        run = self._run(
            literature_review(), project_id="p-row",
            provenance=lambda project_id, ref: (
                "ROW" if str(ref).startswith("evidence:") else None))
        assert isinstance(run, MethodologyRefusal), run
        assert run.code == UNSUPPORTED_CLAIM
        assert run.stage == "CLAIM"

    def test_the_run_digest_is_deterministic(self) -> None:
        first = self._run(literature_review())
        second = self._run(literature_review())
        assert isinstance(first, MethodologyRun)
        assert isinstance(second, MethodologyRun)
        assert first.digest() == second.digest()

    def test_every_node_carries_the_project_and_the_producing_task(self) -> None:
        run = self._run(literature_review())
        assert isinstance(run, MethodologyRun)
        for node in run.store.nodes.values():
            assert node.project_id == "p-run"
            assert node.producing_task_id.startswith("task-run:")

    def test_a_governance_refusal_travels_verbatim(self) -> None:
        document = dict(LITERATURE_REVIEW_DOCUMENT)
        stages = [dict(stage) for stage in document["stages"]]
        stages[0]["governance_action"] = "EVIDENCE_DELETE"  # REVIEWER/RESTRICTED
        document["stages"] = stages
        outcome = self._run(parse_methodology(document))
        assert isinstance(outcome, MethodologyRefusal)
        assert outcome.source == "governance"
        assert outcome.stage == "QUESTION"
        assert outcome.code == "ROLE"

    def test_a_retracted_agent_evidence_ref_stops_at_evidence(self) -> None:
        # The evidence ref is agent-derived (the model proposes it) and the
        # caller's N9 projection retracts it. The OBSERVATION node may cite it
        # (a mention); the EVIDENCE node's own external_ref refuses it, so the
        # run stops there rather than recording a lineage it cannot support.
        base = chain_inputs("p-n9", "does it hold?")
        inputs = MethodologyInputs(
            question=base.question,
            external_refs=base.external_refs,
            admission_refs=base.admission_refs,
            stage_content=base.stage_content,
            retracted_refs=(AGENT_EVIDENCE,))
        run = self._run(literature_review(), project_id="p-n9", inputs=inputs,
                        model=GroundedModel(AGENT_EVIDENCE))
        assert isinstance(run, MethodologyRefusal)
        assert run.source == "substrate"
        assert run.code == RETRACTED_CITATION
        assert run.stage == "EVIDENCE"

    def test_an_unobserved_prior_art_ref_fails_closed(self) -> None:
        # A minted node may cite prior art, but the citation must resolve: the
        # statement is supplied so the shape gate passes and the citation is
        # what refuses.
        base = chain_inputs("p-ghost", "does it hold?")
        inputs = MethodologyInputs(
            question=base.question,
            external_refs={"HYPOTHESIS": "hypothesis:h",
                           "PREDICTION": "prediction:p",
                           "CLAIM": "claim:c"},
            stage_content=base.stage_content)
        run = self._run(literature_review(), project_id="p-ghost",
                        inputs=inputs)
        assert isinstance(run, MethodologyRefusal)
        assert run.source == "substrate"
        assert run.code == EVIDENCE_DOES_NOT_RESOLVE

    def test_a_seed_evidence_ref_is_refused(self) -> None:
        # The fake the run-13 seed carried cannot enter the run: the evidence
        # position is agent-derived. The refusal happens before any model call.
        base = chain_inputs("p-seed", "does it hold?")
        cases = (
            MethodologyInputs(
                question=base.question,
                external_refs={**base.external_refs,
                               "EVIDENCE": "evidence:fake"},
                admission_refs=base.admission_refs),
            MethodologyInputs(
                question=base.question,
                external_refs=base.external_refs,
                admission_refs=base.admission_refs + ("evidence:fake",)),
            MethodologyInputs(
                question=base.question,
                external_refs=base.external_refs,
                admission_refs=base.admission_refs,
                stage_content={"EVIDENCE": {
                    "external_ref": "evidence:fake"}}),
        )
        for number, inputs in enumerate(cases):
            model = GroundedModel()
            run = self._run(literature_review(), project_id=f"p-seed-{number}",
                            inputs=inputs, model=model)
            assert isinstance(run, MethodologyRefusal)
            assert run.source == "inputs"
            assert run.code == MALFORMED_PAYLOAD
            assert model.calls == []

    def test_a_stage_whose_run_failed_never_reports_complete(self) -> None:
        # Every stage names a profile the runtime does not declare, so every
        # `run()` returns state=FAILED. The driver reads `ProposalSet.state`: the
        # failed stage is not recorded and the run does not report COMPLETE.
        document = dict(LITERATURE_REVIEW_DOCUMENT)
        stages = [dict(stage) for stage in document["stages"]]
        for stage in stages:
            stage["profile"] = "undeclared-profile"
        document["stages"] = stages
        run = self._run(parse_methodology(document))
        assert isinstance(run, MethodologyRun)
        assert run.termination == MALFORMED_PAYLOAD
        assert run.termination != "COMPLETE"
        assert run.stages == ()
        assert run.store.nodes == {}
        assert isinstance(run.reconstruction(), SubstrateRefusal)

    def test_a_stage_limit_stops_the_run(self) -> None:
        document = dict(LITERATURE_REVIEW_DOCUMENT)
        document["stages"] = [stage for stage in document["stages"]
                              if stage["stage"] != "CONCLUSION"]
        document["termination"] = dict(document["termination"])
        document["termination"]["max_stages"] = 3
        run = self._run(parse_methodology(document))
        assert isinstance(run, MethodologyRun)
        assert run.termination == "STAGE_LIMIT"
        assert len(run.stages) == 3

    def test_the_run_mapping_is_serialisable(self) -> None:
        run = self._run(literature_review())
        assert isinstance(run, MethodologyRun)
        body = run.to_mapping()
        assert body["methodology_id"] == "literature-review"
        assert [stage["stage"] for stage in body["stages"]] == list(CHAIN_KINDS)

    # ── R6-FIX2 (E3): the driver cannot smuggle an external_ref past the
    # shape rule via ``stage_content`` for a locally-defined kind ──

    def test_a_local_kind_with_a_stage_content_external_ref_is_refused(
            self) -> None:
        # ``MethodologyInputs.stage_content`` lets a caller override a stage's
        # content. The driver hands whatever the override supplies to
        # ``write_node`` verbatim — the substrate's shape rule is what
        # enforces that a QUESTION (a locally-defined kind) cannot carry an
        # ``external_ref``. The run refuses at QUESTION with
        # ``MALFORMED_PAYLOAD``; the shape rule, not the driver's own
        # defaults, is the enforcement. The refusal carries source ==
        # ``"substrate"`` so the failure is attributable to the substrate's
        # shape gate, not the driver.
        base = chain_inputs("p-smuggle", "does it hold?")
        inputs = MethodologyInputs(
            question=base.question,
            external_refs=base.external_refs,
            admission_refs=base.admission_refs,
            stage_content={"QUESTION": {"question": base.question,
                                        "external_ref": "evidence:smuggled/e1"}})
        run = self._run(literature_review(), project_id="p-smuggle",
                        inputs=inputs)
        assert isinstance(run, MethodologyRefusal)
        assert run.source == "substrate"
        assert run.code == MALFORMED_PAYLOAD
        assert run.stage == "QUESTION"
        assert "locally-defined" in run.detail


# ═══════════════════════ 10. module invariants ═══════════════════════


class TestModuleInvariants:
    def test_the_package_exports_nothing_eagerly(self) -> None:
        from hermes.methodology import __all__
        assert __all__ == []

    def test_import_direction_is_the_declared_surface(self) -> None:
        allowed = {
            "substrate.py": set(),
            "__init__.py": set(),
            "workflows.py": {
                "hermes.agents.runtime.run",
                "hermes.agents.runtime.types",
                "hermes.governance.authority",
                "hermes.methodology.substrate",
            },
            "swap_test.py": {
                "hermes.methodology.substrate",
                "hermes.methodology.workflows",
            },
        }
        for name, source in _package_sources().items():
            assert _hermes_imports(source) <= allowed[name], name

    def test_no_module_imports_a_runtime_internal_or_a_governance_internal(
            self) -> None:
        for name, source in _package_sources().items():
            imports = _hermes_imports(source)
            assert not [item for item in imports if item.startswith(
                "hermes.agents.runtime.") and item not in (
                    "hermes.agents.runtime.run", "hermes.agents.runtime.types")
            ], name
            assert not [item for item in imports if item.startswith(
                "hermes.governance.") and item !=
                "hermes.governance.authority"], name
            assert not [item for item in imports if item.startswith(
                "hermes.persistence")], name
            assert "hermes.tools" not in imports, name
            assert "hermes.core" not in imports, name

    def test_the_driver_uses_only_the_public_authority_entry(self) -> None:
        source = _module_source(workflows_module)
        assert "evaluate_authority(" in source
        assert "policy=" not in source
        assert "_evaluate_authority" not in source
        assert "GOVERNANCE_POLICY" not in source

    def test_no_module_opens_a_connection_or_writes(self) -> None:
        banned = {"open", "execute", "executemany", "commit", "connect",
                  "append", "write", "remove", "unlink"}
        for name, source in _package_sources().items():
            tree = ast.parse(source)
            called = {node.func.id for node in ast.walk(tree)
                      if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Name)}
            assert not banned & called, (name, banned & called)
            for token in ("INSERT INTO", "UPDATE ", "DELETE FROM", "SELECT ",
                          "PRAGMA", "sqlite3", "repositories"):
                assert token not in source, (name, token)

    def test_no_module_reads_a_clock_or_holds_mutable_module_state(self) -> None:
        for name, source in _package_sources().items():
            assert "datetime.now" not in source, name
            assert "time.time" not in source, name
            assert "time.monotonic" not in source, name
        tree = ast.parse(_module_source(substrate_module))
        assignments = [node for node in tree.body
                       if isinstance(node, ast.Assign)]
        for node in assignments:
            targets = {target.id for target in node.targets
                       if isinstance(target, ast.Name)}
            assert not targets & {"cache", "state", "registry"}, targets

    def test_no_module_names_a_model_vendor(self) -> None:
        for name, source in _package_sources().items():
            lowered = source.lower()
            for vendor in MODEL_VENDORS:
                assert vendor not in lowered, (name, vendor)

    def test_no_module_states_a_prohibited_claim(self) -> None:
        pattern = re.compile("|".join(PROHIBITED_CLAIM_WORDS), re.I)
        for name, source in _package_sources().items():
            match = pattern.search(source)
            assert match is None, (name, match.group(0) if match else "")

    def test_no_module_names_a_new_intent_kind_or_event_type(self) -> None:
        source = _module_source(substrate_module)
        assert "IntentKind" not in source
        assert "from hermes.core" not in source
        kinds = (SRC_ROOT / "core" / "intents.py").read_text(encoding="utf-8")
        for code in (UNSUPPORTED_CLAIM, PREMATURE_CONCLUSION,
                     CIRCULAR_REASONING, RETRACTED_CITATION):
            assert code not in kinds

    def test_the_planes_node_kinds_are_not_intent_kinds(self) -> None:
        kinds = (SRC_ROOT / "core" / "intents.py").read_text(encoding="utf-8")
        for kind in CHAIN_KINDS:
            assert f'= "{kind}"' not in kinds

    def test_the_governance_action_vocabulary_is_pinned_to_the_plane(self) -> None:
        # The stage vocabulary is a hand-copy: the plane may not import the
        # governance plane's internals but the suite may, so the copy is pinned
        # to its source. A newly governed action (or one removed) fails here
        # instead of silently drifting.
        assert set(governance_policy.ACTIONS) == GOVERNANCE_ACTIONS

    def test_no_dead_publics_and_no_missing_exports(self) -> None:
        # 9X: the dead convenience read is gone; the endpoint resolver is wired
        # and exported. 9Y: every public module symbol is in `__all__`.
        assert not hasattr(substrate_module, "stage_sequence")
        assert "resolve_endpoint" in substrate_module.__all__
        assert "CIRCULAR_REASONING" in substrate_module.__all__
        assert "METHODOLOGY_SCHEMA_VERSION" in workflows_module.__all__
        assert "TERMINATION_KEYS" in workflows_module.__all__
        assert "STAGE_TOOLSET_KEYS" not in workflows_module.__all__
        for module in (substrate_module, workflows_module, swap_module):
            for name in module.__all__:
                assert hasattr(module, name), (module.__name__, name)
            imported = _imported_names(module)
            defined = {name for name in vars(module)
                       if not name.startswith("_") and not name.startswith("@")
                       and name not in imported}
            assert defined <= set(module.__all__), (
                module.__name__, sorted(defined - set(module.__all__)))

    def test_refs_guard_raises_on_a_referenced_node_without_a_ref(self) -> None:
        node = _node("EVIDENCE", content={})
        with pytest.raises(SubstrateFormatError) as raised:
            substrate_module._refs_refusal(_fresh(), node)
        assert "reached _refs_refusal with an empty external_ref" in str(
            raised.value)
