"""W3 wiring tests — the methodology execution driver (`WIRING_DESIGN.md` BIND-5).

These fixtures prove the *binding*, not the planes: the methodology plane's own
ontology/identity/driver tests live in `tests/test_methodology_plane.py`, and the
W2 runtime wiring's tests in `tests/test_wiring_w2.py`. This suite is
self-contained — it builds its own model port, applier, profiles and inputs, so a
change to another suite's fixtures cannot silently weaken a wiring assertion.

What is proved, one group each:

- **projection** — a parsed workflow document projects onto per-stage tasks
  (task ids, attribution, declared predecessor) as pure, deterministic data;
- **preflight-stop** — the governance consult runs before a consequential stage
  and a denial stops the run *there*, with the governance plane's own code,
  never as a silent skip;
- **admissions** — every stage's durable footprint is named as the existing write
  boundary (`apply_intent`) the run's intents reached, counted per stage;
- **derived-only limit** — substrate nodes stay derived working state; a durable
  chain / `mnode_` ref is refused, not implemented (§8 item 9), and the claim
  limits are pinned;
- **reconstruction** — the chain is recomputed from the derived store, purely,
  matching across runs and changing when the store changes;
- **refusal mapping** — a malformed document maps to `MALFORMED_PAYLOAD`; a
  substrate refusal stops the run as data; a failed stage never reports COMPLETE;
- **no write surface** — the module's imports and identifiers are checked
  mechanically, and the driver adds no new governance consumer.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import hermes.research.task_handlers.methodology_driver as driver_module
from hermes.agents.runtime.config import ProfileSpec, load_profiles, parse_profile
from hermes.agents.runtime.types import LOCK, digest_of
from hermes.agents.runtime.wiring import RuntimeWiring
from hermes.core.intents import Intent
from hermes.methodology.substrate import (
    CHAIN_KINDS,
    RETRACTED_CITATION,
    ChainReconstruction,
    SubstrateRefusal,
    SubstrateStore,
    reconstruct_chain,
)
from hermes.methodology.swap_test import engineering_investigation
from hermes.methodology.workflows import (
    LITERATURE_REVIEW_DOCUMENT,
    MethodologyInputs,
    MethodologyRefusal,
    parse_methodology,
)
from hermes.research.task_handlers.methodology_driver import (
    ADMISSION_BOUNDARY,
    DURABILITY_GATE,
    MethodologyExecution,
    claim_limits,
    is_consequential,
    parse_workflow,
    preflight,
    project_stage,
    refuse_durable_claim,
    run_methodology,
    stage_projections,
)
from hermes.tools.models.router import ModelProposal, ModelRequest

DRIVER_PATH = Path(str(driver_module.__file__))

PROJECT = "p-w3"
TASK = "task-w3"
LEASE = "lease-gen-w3"
OTHER_PROJECT = "p-w3-other"

#: The citation refs a grounded run cites, all registered in-project.
REFS: dict[str, str] = {
    "HYPOTHESIS": "hypothesis:program-w3/h1",
    "PREDICTION": "prediction:program-w3/h1/p1",
    "EVIDENCE": "evidence:evidence-w3/e1",
    "CLAIM": "claim:claim-w3/c1",
}

#: The profiles a `literature-review` document declares. Custom (not the shipped
#: data) so the fixtures control termination and authority directly.
STAGE_PROFILES = ("planner", "researcher", "experimenter", "verifier",
                  "synthesizer", "critic")


# ═══════════════════════ fakes ═══════════════════════


class FakeClock:
    """A frozen clock: the runtime only needs a monotonic number here."""

    def __call__(self) -> str:
        return "2026-10-06T00:00:00.000000+00:00"

    def now_utc(self) -> str:
        return self()

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, seconds: float) -> None:
        return None


def _proposal(request: ModelRequest, structured: dict[str, Any]) -> ModelProposal:
    return ModelProposal(provider_id="scripted", model_id="scripted",
                         tier="research", profile=request.profile,
                         lease_generation=request.lease_generation,
                         structured=dict(structured))


class SilentModel:
    """A `ModelPort` that records every call and proposes nothing."""

    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def invoke(self, request: ModelRequest) -> ModelProposal:
        self.calls.append(request)
        return _proposal(request, {})


class ProposingModel:
    """A `ModelPort` proposing one ordinary `INSERT_TASK` draft per call."""

    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def invoke(self, request: ModelRequest) -> ModelProposal:
        self.calls.append(request)
        return _proposal(request, {
            "kind": "INSERT_TASK",
            "rationale": "because",
            "payload": {"goal": f"stage {request.profile}"},
        })


@dataclass(frozen=True, slots=True)
class _Applied:
    """The shape `run._apply` reads off an injected Orchestration API result."""

    entity_id: str
    duplicate: bool


class RecordingApplier:
    """The spine's injection point as a recording double (the `apply_intent` seam)."""

    def __init__(self) -> None:
        self.calls: list[Intent] = []

    def __call__(self, intent: Intent) -> _Applied:
        self.calls.append(intent)
        key = digest_of({"kind": intent.kind.value,
                         "payload": dict(intent.payload)})
        return _Applied(entity_id="ent_" + key[:12], duplicate=False)


def _profile(name: str, *, max_ticks: int = 1, max_proposals: int = 5,
             stop_when: str = "proposals_raised") -> ProfileSpec:
    return parse_profile({
        "name": name,
        "role": f"{name} role",
        "agent_profile": "RESEARCHER",
        "model_policy": {"tier": "research", "structured_fields": ["proposals"]},
        "tools": [],
        "authority": {"proposable_kinds": ["INSERT_TASK"]},
        "termination": {"max_ticks": max_ticks, "max_proposals": max_proposals,
                        "stop_when": stop_when},
    }, source=name)


def _stage_profiles() -> dict[str, ProfileSpec]:
    return {name: _profile(name) for name in STAGE_PROFILES}


def _inputs(question: str = "does the effect hold?",
            *, refs: dict[str, str] | None = None,
            retracted: tuple[str, ...] = ()) -> MethodologyInputs:
    table = REFS if refs is None else refs
    return MethodologyInputs(
        question=question,
        external_refs=dict(table),
        admission_refs=tuple(table.values()),
        retracted_refs=tuple(retracted))


class Rig:
    """One wired runtime over a recording spine — the W3 test rig."""

    def __init__(self, *, model: Any = None, profiles: Any = None,
                 lease: str = LEASE) -> None:
        self.model = model if model is not None else SilentModel()
        self.applier = RecordingApplier()
        self.wiring = RuntimeWiring(
            model=self.model,
            orchestration=self.applier,
            lease_generation=lease,
            profiles=profiles if profiles is not None else _stage_profiles(),
            clock=FakeClock())

    def run(self, config: Any = None, *, inputs: MethodologyInputs | None = None,
            project_id: str = PROJECT, task_id: str = TASK
            ) -> MethodologyExecution | MethodologyRefusal:
        document = (parse_methodology(dict(LITERATURE_REVIEW_DOCUMENT))
                    if config is None else config)
        return run_methodology(
            document,
            _inputs() if inputs is None else inputs,
            wiring=self.wiring, project_id=project_id, task_id=task_id)


# ═══════════════════════ 1. projection ═══════════════════════


def test_the_projection_maps_every_stage_to_one_task() -> None:
    config = parse_methodology(dict(LITERATURE_REVIEW_DOCUMENT))
    projections = stage_projections(config, project_id=PROJECT, task_id=TASK,
                                    lease_generation=LEASE)
    assert [projection.stage for projection in projections] == list(
        config.stage_kinds())
    assert len(projections) == len(config.stages)
    assert all(p.task_id == f"{TASK}:{p.stage}" for p in projections)
    assert all(p.context.task_id == p.task_id for p in projections)
    assert all(p.context.project_id == PROJECT for p in projections)
    assert all(p.context.lease_generation == LEASE for p in projections)
    assert all(p.context.payload["methodology_id"] == config.methodology_id
               for p in projections)


def test_the_projection_names_the_declared_predecessor_stage() -> None:
    config = parse_methodology(dict(LITERATURE_REVIEW_DOCUMENT))
    projections = stage_projections(config, project_id=PROJECT, task_id=TASK,
                                    lease_generation=LEASE)
    assert projections[0].predecessor_stage == ""
    assert [p.predecessor_stage for p in projections[1:]] == [
        p.stage for p in projections[:-1]]


def test_the_projection_is_pure_document_data() -> None:
    config = parse_methodology(dict(LITERATURE_REVIEW_DOCUMENT))
    first = stage_projections(config, project_id=PROJECT, task_id=TASK,
                              lease_generation=LEASE)
    second = stage_projections(config, project_id=PROJECT, task_id=TASK,
                               lease_generation=LEASE)
    assert [p.to_mapping() for p in first] == [p.to_mapping() for p in second]
    # The recorded predecessor *node* is a run product, never a projected field:
    # the projection is a function of the document alone.
    projection = project_stage(config, config.stages[1], project_id=PROJECT,
                               task_id=TASK, lease_generation=LEASE,
                               predecessor_stage=config.stages[0].stage)
    assert set(projection.context.payload) == {
        "stage", "methodology_id", "predecessor_stage"}
    assert set(projection.to_mapping()) == {
        "stage", "profile", "governance_action", "required", "task_id",
        "project_id", "lease_generation", "predecessor_stage"}


def test_only_a_declared_governance_action_is_consequential() -> None:
    stages = {stage.stage: stage
              for stage in parse_methodology(dict(
                  LITERATURE_REVIEW_DOCUMENT)).stages}
    assert is_consequential(stages["QUESTION"]) is True     # WEB_SEARCH
    assert is_consequential(stages["EXPERIMENT"]) is True   # SANDBOX_RUN
    assert is_consequential(stages["PREDICTION"]) is False  # no action declared


# ═══════════════════════ 2. preflight → stop ═══════════════════════


def test_preflight_answers_the_verdict_and_a_denial_as_data() -> None:
    stages = {stage.stage: stage
              for stage in parse_methodology(dict(
                  LITERATURE_REVIEW_DOCUMENT)).stages}
    verdict, denial = preflight(stages["QUESTION"], _inputs(), project_id=PROJECT,
                                actor="tester", rationale="q")
    assert verdict != "" and denial is None
    denied = replace(stages["OBSERVATION"], governance_action="EVIDENCE_DELETE")
    _, refusal = preflight(denied, _inputs(), project_id=PROJECT,
                           actor="tester", rationale="q")
    assert isinstance(refusal, MethodologyRefusal)
    assert refusal.code == "ROLE"          # the governance plane's own code
    assert refusal.source == "governance"


def _denying_config(stage_kind: str, action: str = "EVIDENCE_DELETE") -> Any:
    document = dict(LITERATURE_REVIEW_DOCUMENT)
    stages = [dict(stage) for stage in document["stages"]]
    for stage in stages:
        if stage["stage"] == stage_kind:
            stage["governance_action"] = action
    document["stages"] = stages
    return parse_methodology(document)


def test_a_preflight_denial_stops_the_run_before_the_first_stage() -> None:
    rig = Rig()
    outcome = rig.run(_denying_config("QUESTION"))
    assert isinstance(outcome, MethodologyRefusal)
    assert (outcome.source, outcome.stage, outcome.code) == (
        "governance", "QUESTION", "ROLE")
    assert rig.model.calls == []          # the denied stage never ran
    assert rig.applier.calls == []        # and nothing was admitted


def test_a_preflight_denial_stops_at_its_own_stage_never_a_silent_skip() -> None:
    rig = Rig()
    outcome = rig.run(_denying_config("OBSERVATION"))
    assert isinstance(outcome, MethodologyRefusal)
    assert (outcome.source, outcome.stage) == ("governance", "OBSERVATION")
    # QUESTION, HYPOTHESIS, PREDICTION and EXPERIMENT ran; OBSERVATION did not,
    # and no later stage ran either — the run stops where the denial lands.
    assert rig.model.call_count == 4


# ═══════════════════════ 3. stage run + admissions ═══════════════════════


def test_a_wired_run_records_every_stage_and_reconstructs_the_chain() -> None:
    rig = Rig()
    outcome = rig.run()
    assert isinstance(outcome, MethodologyExecution)
    assert outcome.termination == "COMPLETE"
    assert [record.stage for record in outcome.stages] == list(CHAIN_KINDS)
    reconstruction = outcome.reconstruction()
    assert isinstance(reconstruction, ChainReconstruction)
    assert reconstruction.kinds() == CHAIN_KINDS
    assert reconstruction.complete() is True


def test_every_stage_carries_the_wiring_lease_tag() -> None:
    rig = Rig()
    outcome = rig.run()
    assert isinstance(outcome, MethodologyExecution)
    assert outcome.lease_generation == LEASE
    assert all(record.lease_generation == LEASE for record in outcome.stages)
    for record in outcome.stages:
        events = rig.wiring.trace(record.run_id)
        assert events
        assert all(event.lease_generation == LEASE for event in events)


def test_every_stage_admission_names_the_existing_write_boundary() -> None:
    rig = Rig(model=ProposingModel())
    outcome = rig.run()
    assert isinstance(outcome, MethodologyExecution)
    assert ADMISSION_BOUNDARY == "apply_intent"
    admissions = outcome.admissions()
    assert [ref.stage for ref in admissions] == list(CHAIN_KINDS)
    assert {ref.boundary for ref in admissions} == {ADMISSION_BOUNDARY}
    # The applier's counter is cumulative; the driver reports the per-stage delta.
    assert [ref.intents_applied for ref in admissions] == [1] * len(CHAIN_KINDS)
    assert len(rig.applier.calls) == len(CHAIN_KINDS)
    assert all(intent.kind.value == "INSERT_TASK" for intent in rig.applier.calls)


def test_a_silent_stage_admits_nothing() -> None:
    rig = Rig(model=SilentModel())
    outcome = rig.run()
    assert isinstance(outcome, MethodologyExecution)
    assert rig.applier.calls == []
    assert [ref.intents_applied for ref in outcome.admissions()] == (
        [0] * len(CHAIN_KINDS))


def test_a_lost_lease_stops_the_run_with_lock_and_records_nothing() -> None:
    rig = Rig()
    rig.wiring.lose_lease("the lease was lost before the run")
    outcome = rig.run()
    assert isinstance(outcome, MethodologyExecution)
    assert outcome.stages == ()
    assert outcome.termination == LOCK
    assert outcome.store.nodes == {}
    assert rig.model.calls == []
    assert rig.applier.calls == []


def test_a_second_workflow_runs_on_the_same_wiring_instances() -> None:
    rig = Rig()
    first = rig.run()
    first_calls = rig.model.call_count
    second = rig.run(engineering_investigation(), project_id=OTHER_PROJECT,
                     task_id="task-w3-b")
    assert isinstance(first, MethodologyExecution)
    assert isinstance(second, MethodologyExecution)
    assert first.methodology_id != second.methodology_id
    assert first.termination == second.termination == "COMPLETE"
    assert first_calls == len(first.stages)        # this document: one tick/stage
    # The same model, applier and wiring served both documents — a second
    # document is configuration, never a second runtime or scheduler — and the
    # second document's declared per-stage bound (2 ticks) is what it consumed.
    assert rig.model.call_count == first_calls + 2 * len(second.stages)
    assert all(record.lease_generation == LEASE for record in second.stages)


# ═══════════════════════ 4. derived-only limit (§8 item 9) ═══════════════


def test_the_claim_limits_are_the_bind_five_limits() -> None:
    limits = claim_limits()
    assert limits.may_claim("stage_execution")
    assert limits.may_claim("stage_outcomes")
    assert limits.may_claim("stage_digests")
    assert limits.may_claim("admissions_via_apply_intent")
    for claim in ("durable_substrate_state", "durable_chain", "mnode_refs",
                  "medge_refs"):
        assert limits.may_claim(claim) is False
        assert claim in limits.not_claimable
    assert limits.gate == DURABILITY_GATE


def test_a_durable_chain_claim_is_refused_not_implemented() -> None:
    for claim in ("durable_substrate_state", "durable_chain", "mnode_refs",
                  "medge_refs"):
        refusal = refuse_durable_claim(claim)
        assert isinstance(refusal, MethodologyRefusal)
        assert refusal.code == "MALFORMED_PAYLOAD"   # frozen, no new code
        assert refusal.source == "claim-limits"
        assert claim in refusal.detail
        assert "§8 item 9" in refusal.detail


def test_a_wired_run_establishes_no_durable_substrate_state() -> None:
    rig = Rig(model=SilentModel())
    outcome = rig.run()
    assert isinstance(outcome, MethodologyExecution)
    # The only durable side is the injected boundary; a silent run reached it
    # with nothing. The derived store lives and dies in-process.
    assert rig.applier.calls == []
    assert isinstance(outcome.store, SubstrateStore)
    assert all(record.node_id.startswith("mnode_") for record in outcome.stages)
    assert outcome.claim_limits().may_claim("durable_chain") is False
    assert outcome.claim_limits().may_claim("mnode_refs") is False
    # And the module has no durable write surface it could have used.
    assert _imports_of(DRIVER_PATH) == set(DRIVER_IMPORTS)
    assert _code_identifiers(DRIVER_PATH) & FORBIDDEN_NAMES == set()


# ═══════════════════════ 5. reconstruction ═══════════════════════


def test_reconstruction_is_recomputed_and_matches_across_runs() -> None:
    first = Rig().run()
    second = Rig().run()
    assert isinstance(first, MethodologyExecution)
    assert isinstance(second, MethodologyExecution)
    assert first.digest() == second.digest()
    live = first.reconstruction()
    other = second.reconstruction()
    assert isinstance(live, ChainReconstruction)
    assert isinstance(other, ChainReconstruction)
    assert live.digest() == other.digest()


def test_reconstruction_is_recomputed_from_the_derived_store() -> None:
    outcome = Rig().run()
    assert isinstance(outcome, MethodologyExecution)
    rebuilt = SubstrateStore.from_mapping(outcome.store.to_mapping())
    recomputed = reconstruct_chain(rebuilt, outcome.question_id)
    live = outcome.reconstruction()
    assert isinstance(recomputed, ChainReconstruction)
    assert isinstance(live, ChainReconstruction)
    assert recomputed.digest() == live.digest()
    assert outcome.reconstruction().digest() == live.digest()  # no cached view


def test_the_reconstruction_reads_live_derived_state_not_a_frozen_claim() -> None:
    outcome = Rig().run()
    assert isinstance(outcome, MethodologyExecution)
    assert isinstance(outcome.reconstruction(), ChainReconstruction)
    outcome.store.nodes.clear()
    after = outcome.reconstruction()
    assert isinstance(after, SubstrateRefusal)
    assert after.code == "PROVENANCE"


# ═══════════════════════ 6. refusal mapping ═══════════════════════


def test_a_malformed_document_maps_to_malformed_payload() -> None:
    outcome = parse_workflow({"stages": [
        {"stage": "QUESTION", "profile": "planner"}]})
    assert isinstance(outcome, MethodologyRefusal)
    assert outcome.code == "MALFORMED_PAYLOAD"
    assert outcome.source == "parse"
    assert "id" in outcome.detail


def test_an_unknown_stage_is_refused_at_load() -> None:
    document = dict(LITERATURE_REVIEW_DOCUMENT)
    document["stages"] = [*document["stages"],
                          {"stage": "MYSTERY", "profile": "planner"}]
    outcome = parse_workflow(document)
    assert isinstance(outcome, MethodologyRefusal)
    assert outcome.code == "MALFORMED_PAYLOAD"


def test_a_valid_document_parses_to_a_config() -> None:
    config = parse_workflow(dict(LITERATURE_REVIEW_DOCUMENT))
    assert not isinstance(config, MethodologyRefusal)
    assert config.methodology_id == "literature-review"


def test_a_substrate_refusal_stops_the_run_as_data() -> None:
    rig = Rig()
    outcome = rig.run(inputs=_inputs(retracted=(REFS["EVIDENCE"],)))
    assert isinstance(outcome, MethodologyRefusal)
    assert (outcome.source, outcome.code, outcome.stage) == (
        "substrate", RETRACTED_CITATION, "EVIDENCE")


def test_a_stage_whose_run_failed_never_reports_complete() -> None:
    rig = Rig(profiles={})          # no profile is declared for any stage
    outcome = rig.run()
    assert isinstance(outcome, MethodologyExecution)
    assert outcome.termination == "MALFORMED_PAYLOAD"
    assert outcome.termination != "COMPLETE"
    assert outcome.stages == ()
    assert outcome.store.nodes == {}
    assert isinstance(outcome.reconstruction(), SubstrateRefusal)


def test_the_driver_runs_the_shipped_profiles_too() -> None:
    rig = Rig(profiles=load_profiles())
    outcome = rig.run()
    assert isinstance(outcome, MethodologyExecution)
    assert outcome.termination == "COMPLETE"
    assert [record.stage for record in outcome.stages] == list(CHAIN_KINDS)


# ═══════════════════════ 7. no write surface (mechanical) ═══════════════

#: Exactly what the driver may import: its plane, its runtime binding, core types.
DRIVER_IMPORTS = frozenset({
    "__future__", "dataclasses", "typing",
    "hermes.agents.runtime.types",
    "hermes.agents.runtime.wiring",
    "hermes.core.task_status",
    "hermes.methodology",
    "hermes.methodology.substrate",
    "hermes.methodology.workflows",
})

#: Names a module with a write surface would mention.
FORBIDDEN_NAMES = frozenset({
    "conn", "connection", "cursor", "commit", "rollback", "execute",
    "executemany", "sqlite3", "transaction", "repository", "Repository", "BEGIN",
})

#: Module prefixes the driver must never reach for.
FORBIDDEN_MODULES = ("hermes.persistence", "hermes.research.gateway")


def _tree_of(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports_of(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree_of(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _code_identifiers(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(_tree_of(path)):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


def test_the_driver_imports_its_plane_and_runtime_binding_only() -> None:
    imports = _imports_of(DRIVER_PATH)
    assert imports == set(DRIVER_IMPORTS)
    assert not [name for name in imports
                if name.startswith(FORBIDDEN_MODULES)]


def test_the_driver_names_no_writer_or_transaction() -> None:
    assert _code_identifiers(DRIVER_PATH) & FORBIDDEN_NAMES == set()


def test_the_driver_defines_no_new_vocabulary() -> None:
    tree = _tree_of(DRIVER_PATH)
    constants: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    constants.add(target.id)
    assert constants == {"ADMISSION_BOUNDARY", "DURABILITY_GATE"}
    source = DRIVER_PATH.read_text(encoding="utf-8")
    for code in ("UNSUPPORTED_CLAIM", "PREMATURE_CONCLUSION", "CIRCULAR_REASONING",
                 "RETRACTED_CITATION"):
        assert code not in source


def test_the_driver_adds_no_governance_consumer() -> None:
    # The preflight goes through the methodology plane's already-declared consumer;
    # the driver itself names the governance plane nowhere. (The R5 allowlist gate,
    # `test_governance_plane.py::test_the_plane_is_wired_to_nothing`, scans for this
    # exact string across all of `src/hermes`.)
    source = DRIVER_PATH.read_text(encoding="utf-8")
    assert "hermes.governance" not in source
