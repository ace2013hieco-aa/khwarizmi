"""OPS-5Y — prior art is produced, or it is not asserted.

The slice's own pins, in the order the design gate lists them:

- the seeding path (§12.8): dry-run by default, one ``INSERT_TASK`` through
  ``apply_intent``, no fabricated prior art;
- ``statement`` on the draft contract (once that surface lands);
- minted HYPOTHESIS/PREDICTION/CLAIM nodes (no citation identity);
- ref backing at intake (``PRIOR_ART_UNBACKED``);
- the direct-support rule ``D(C)`` and the two required falsifiers;
- the depth field on ``TaskStatusChanged`` and its rendering.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import DRAFT_KEYS, output_contract_for
from hermes.agents.runtime.types import Proposal, digest_of
from hermes.agents.runtime.wiring import RuntimeWiring
from hermes.core.intents import Intent, IntentKind
from hermes.methodology import workflows as workflows_module
from hermes.methodology.substrate import (
    MINTED_NODE_KINDS,
    PRIOR_ART_UNBACKED,
    PROVENANCE,
    RefBacking,
    SubstrateRefusal,
    SubstrateStore,
)
from hermes.methodology.swap_test import CHAIN_STATEMENTS
from hermes.methodology.workflows import (
    LITERATURE_REVIEW_DOCUMENT,
    MethodologyInputs,
    MethodologyRefusal,
    MethodologyRun,
    parse_methodology,
    run_methodology,
)
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.chain_refs import RefProvenanceReader, parse_ref
from hermes.research.controller import Controller
from hermes.research.gateway import apply_intent
from hermes.research.task_handlers import build_methodology_handler
from hermes.research.task_handlers.methodology_driver import (
    run_methodology as driver_run_methodology,
)
from hermes.tools.models.router import ModelProposal

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = REPO_ROOT / "scripts" / "seed_methodology_run.py"
CLOCK = "2026-10-28T12:00:00.000000+00:00"


def _load_seed() -> Any:
    spec = importlib.util.spec_from_file_location("seed_methodology_run",
                                                  SEED_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = _load_seed()


def _journal(path: Path) -> None:
    conn = connect(path)
    migrate_to_latest(conn)
    conn.close()


def _seed_args(journal: Path, project: str = "p-seed",
               question: str = "does it hold?") -> list[str]:
    return ["--db", str(journal), "--project", project,
            "--question", question]


# ═══════════════════════ 1. the seeding path (§12.8) ═══════════════════════


def test_the_seed_is_a_dry_run_by_default(tmp_path: Path, capsys: Any) -> None:
    journal = tmp_path / "hermes.db"
    _journal(journal)
    assert seed.main(_seed_args(journal)) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["dry_run"] is True
    assert plan["project"] == "p-seed"
    assert plan["task_id"] == "meth-p-seed"
    assert plan["question"] == "does it hold?"
    assert plan["admission_refs"] == []
    assert plan["external_refs"] == {}
    assert plan["stages"] == [
        "QUESTION", "HYPOTHESIS", "PREDICTION", "EXPERIMENT", "OBSERVATION",
        "EVIDENCE", "CLAIM", "CRITIQUE", "CONCLUSION"]

    conn = connect(journal)
    try:
        assert conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0
    finally:
        conn.close()


def test_apply_seeds_one_task_through_apply_intent(
        tmp_path: Path, capsys: Any) -> None:
    journal = tmp_path / "hermes.db"
    _journal(journal)
    assert seed.main(_seed_args(journal) + ["--apply"]) == 0
    out = capsys.readouterr().out
    assert "project created: p-seed" in out
    assert "task admitted:" in out

    conn = connect(journal)
    try:
        project = conn.execute(
            "SELECT * FROM projects WHERE project_id = 'p-seed'").fetchone()
        assert project is not None
        task = conn.execute(
            "SELECT * FROM tasks WHERE task_id = 'meth-p-seed'").fetchone()
        assert task is not None
        assert task["status"] == "PENDING"
        spec = json.loads(task["spec_json"])
        assert spec["template"] == "methodology_run"
        assert spec["inputs"]["question"] == "does it hold?"
        assert spec["inputs"]["admission_refs"] == []
        assert spec["inputs"]["external_refs"] == {}
        assert len(spec["methodology"]["stages"]) == 9
        # The seed itself adds no research row: one project, one task.
        assert conn.execute(
            "SELECT COUNT(*) c FROM research_claims").fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM research_programs").fetchone()["c"] == 0
    finally:
        conn.close()


def test_apply_refuses_to_reuse_a_project(tmp_path: Path,
                                          capsys: Any) -> None:
    journal = tmp_path / "hermes.db"
    _journal(journal)
    assert seed.main(_seed_args(journal) + ["--apply"]) == 0
    assert seed.main(_seed_args(journal) + ["--apply"]) == 1
    assert "already exists" in capsys.readouterr().err


def test_the_methodology_can_be_copied_from_a_task(tmp_path: Path,
                                                   capsys: Any) -> None:
    journal = tmp_path / "hermes.db"
    _journal(journal)
    conn = connect(journal)
    try:
        ProjectRepository(conn, lambda: CLOCK).create("p-source", "source")
        document = dict(seed.LITERATURE_REVIEW_DOCUMENT)
        document["stages"] = [dict(stage) for stage in document["stages"][:3]]
        document["termination"] = {**dict(document["termination"]),
                                   "max_stages": 3}
        apply_intent(conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p-source",
            payload={
                "task_id": "meth-source", "task_type": "AGENT_TASK",
                "profile": "RESEARCHER",
                "spec": {"template": "methodology_run",
                         "methodology": document},
                "idempotency_key": "k-meth-source", "iteration": 1,
                "inputs": [], "outputs": [], "dependencies": [],
                "provenance": [], "cost_class": "LOW",
            }), clock=lambda: CLOCK)
    finally:
        conn.close()

    assert seed.main(_seed_args(journal, project="p-copy")
                     + ["--methodology-from-task", "meth-source",
                        "--apply"]) == 0
    conn = connect(journal)
    try:
        spec = json.loads(conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id = 'meth-p-copy'"
        ).fetchone()["spec_json"])
        assert len(spec["methodology"]["stages"]) == 3
        assert spec["methodology"]["termination"]["max_stages"] == 3
    finally:
        conn.close()


def test_a_missing_journal_is_refused_not_created(tmp_path: Path,
                                                  capsys: Any) -> None:
    journal = tmp_path / "absent.db"
    assert seed.main(_seed_args(journal)) == 1
    assert "does not exist" in capsys.readouterr().err
    assert not journal.exists()


def test_the_seeded_intent_carries_no_authored_prior_art(
        tmp_path: Path) -> None:
    # The script builds one intent; its spec inputs are exactly what the
    # caller named. Nothing else is registered, and the evidence position is
    # absent by construction (OPS-5D).
    intent = seed.build_intent(
        project_id="p1", task_id="meth-p1", question="q?",
        methodology=seed.LITERATURE_REVIEW_DOCUMENT,
        admission_refs=("claim:cl_x",),
        external_refs={"CLAIM": "claim:cl_x"},
        provider="a-provider", profile="RESEARCHER", max_retries=3)
    inputs = intent.payload["spec"]["inputs"]
    assert inputs["admission_refs"] == ["claim:cl_x"]
    assert inputs["external_refs"] == {"CLAIM": "claim:cl_x"}
    assert "EVIDENCE" not in inputs["external_refs"]
    assert "Intended provider: a-provider" in intent.justification
    assert intent.kind is IntentKind.INSERT_TASK


# ═══════════════════════ 2. the draft contract (§6.2) ═══════════════════════


def _proposal(statement: str = "") -> Proposal:
    return Proposal(
        intent=Intent(kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                      project_id="p1", payload={"spec": {"a": 1}},
                      justification="because"),
        rationale="the rationale", tick=1, profile="researcher",
        agent_profile="RESEARCHER", lease_generation="gen",
        statement=statement)


def test_the_draft_vocabulary_carries_statement() -> None:
    assert "statement" in DRAFT_KEYS


def test_every_profile_contract_offers_the_statement_field() -> None:
    for name, spec in load_profiles().items():
        contract = output_contract_for(spec)
        fields = {field.name: field for field in contract.fields}
        assert "statement" in fields, name
        assert fields["statement"].type == "string"
        assert fields["statement"].required is False
        assert "statement" in dict(contract.field_notes)


def test_a_proposal_without_a_statement_keeps_the_previous_digest() -> None:
    proposal = _proposal()
    expected = digest_of({
        "profile": proposal.profile,
        "agent_profile": proposal.agent_profile,
        "kind": proposal.intent.kind.value,
        "project_id": proposal.intent.project_id,
        "payload": dict(proposal.intent.payload),
        "justification": proposal.intent.justification,
        "rationale": proposal.rationale,
        "artifact_ref": proposal.artifact_ref,
    })
    assert proposal.draft_digest() == expected
    assert "statement" not in proposal.to_mapping()


def test_a_statement_moves_the_digest_and_the_mapping() -> None:
    without = _proposal()
    with_statement = _proposal("the asserted content")
    assert with_statement.draft_digest() != without.draft_digest()
    assert with_statement.to_mapping()["statement"] == "the asserted content"
    assert Proposal.from_mapping(with_statement.to_mapping()) == with_statement


# ═══════════════════════ 3. the minted kinds (§4.3, §6) ═══════════════════════


class _SilentModel:
    """A model port that proposes nothing and records the calls."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier="research",
            profile=request.profile,
            lease_generation=request.lease_generation, structured={})


class _AdmittingApplier:
    def __init__(self) -> None:
        self.intents: list[Intent] = []

    def __call__(self, intent: Intent) -> Any:
        self.intents.append(intent)

        class _Applied:
            entity_id = f"ent_{len(self.intents):04d}"
            duplicate = False

        return _Applied()


def _short_document(stages: int) -> Any:
    document = dict(LITERATURE_REVIEW_DOCUMENT)
    document["stages"] = [dict(stage) for stage in
                          document["stages"][:stages]]
    document["termination"] = {**dict(document["termination"]),
                               "max_stages": stages}
    return parse_methodology(document)


def test_a_fresh_run_mints_hypothesis_and_prediction_without_refs() -> None:
    """Falsifier: a fresh project with no refs reaches PREDICTION.

    No ``external_refs`` and no ``admission_refs`` are supplied. The statements
    come from the caller's stage content; the nodes are minted, not cited, and
    the reconstruction stops at the first absent stage rather than at
    HYPOTHESIS.
    """
    config = _short_document(3)
    run = run_methodology(
        config, "p-mint", "task-mint", "gen-1",
        MethodologyInputs(question="does the effect hold?",
                          stage_content=CHAIN_STATEMENTS),
        model=_SilentModel(), orchestration=_AdmittingApplier(),
        profiles=load_profiles())
    assert isinstance(run, MethodologyRun), run
    assert run.termination == "COMPLETE"
    assert [outcome.content_origin for outcome in run.stages] == [
        "", "MINTED", "MINTED"]
    for kind in ("HYPOTHESIS", "PREDICTION"):
        entries = run.store.nodes_of_kind(kind)
        assert len(entries) == 1, kind
        node = entries[0][1]
        assert kind in MINTED_NODE_KINDS
        assert node.content["origin"] == "MINTED"
        assert node.content["statement"].strip()
        assert "external_ref" not in node.content
        assert "run-minted conjecture" in node.rationale
        assert "prior-art citation" not in node.rationale
    reconstruction = run.reconstruction()
    assert isinstance(reconstruction, SubstrateRefusal)
    assert reconstruction.code == PROVENANCE
    assert "EXPERIMENT" in reconstruction.detail
    assert not hasattr(workflows_module, "_PRIOR_ART_LABEL")


def test_default_content_cites_a_seeded_ref_it_never_identifies_with() -> None:
    """An operator's external_refs value becomes a citation on a minted node."""
    inputs = MethodologyInputs(
        question="q?", external_refs={"HYPOTHESIS": "claim:cl_prior"})
    content = workflows_module._default_content(
        "HYPOTHESIS", inputs, "", "", statement="the run's conjecture")
    assert content["cited_refs"] == ("claim:cl_prior",)
    assert "external_ref" not in content
    assert content["statement"] == "the run's conjecture"
    assert content["origin"] == "MINTED"


def test_a_backed_claim_ref_seeds_into_an_existing_project(
        tmp_path: Path, capsys: Any) -> None:
    """The script checks the same port the run will: a row, or no seed."""
    journal = tmp_path / "hermes.db"
    _journal(journal)
    conn = connect(journal)
    try:
        ProjectRepository(conn, lambda: CLOCK).create("p-prior", "prior")
        conn.execute(
            """INSERT INTO research_claims
               (claim_id, project_id, content_hash, statement, source_ref,
                schema_version, extracted_by, reason, created_at,
                context_tags_json)
               VALUES ('cl_prior', 'p-prior', 'h1', 'X causes Y',
                       'source_result:s1', '1', 't', NULL, ?, '{}')""",
            (CLOCK,))
    finally:
        conn.close()

    assert seed.main(_seed_args(journal, project="p-prior")
                     + ["--allow-existing-project",
                        "--admission-ref", "claim:cl_prior",
                        "--apply"]) == 0
    conn = connect(journal)
    try:
        spec = json.loads(conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id = 'meth-p-prior'"
        ).fetchone()["spec_json"])
        assert spec["inputs"]["admission_refs"] == ["claim:cl_prior"]
    finally:
        conn.close()


def test_a_ref_on_a_fresh_project_is_refused(tmp_path: Path,
                                             capsys: Any) -> None:
    journal = tmp_path / "hermes.db"
    _journal(journal)
    assert seed.main(_seed_args(journal)
                     + ["--admission-ref", "claim:cl_prior"]) == 1
    assert "fresh project" in capsys.readouterr().err


def test_an_unbacked_ref_in_an_existing_project_is_refused(
        tmp_path: Path, capsys: Any) -> None:
    journal = tmp_path / "hermes.db"
    _journal(journal)
    conn = connect(journal)
    try:
        ProjectRepository(conn, lambda: CLOCK).create("p-empty", "empty")
    finally:
        conn.close()
    assert seed.main(_seed_args(journal, project="p-empty")
                     + ["--allow-existing-project",
                        "--admission-ref", "claim:cl_missing"]) == 1
    assert "does not resolve to a row" in capsys.readouterr().err


# ═══════════════════════ 4. ref backing (§3) ═══════════════════════


def test_an_unbacked_registration_is_refused() -> None:
    store = SubstrateStore()
    refused = store.admit_ref("hypothesis:prior-art-sars30/h1", "p1")
    assert isinstance(refused, SubstrateRefusal)
    assert refused.code == PRIOR_ART_UNBACKED
    assert "assertion is not an artifact" in refused.detail
    assert store.resolving_refs == {}


def test_the_port_is_the_only_witness_and_it_is_explicit() -> None:
    store = SubstrateStore()
    assert store.admit_ref(
        "claim:cl_1", "p1",
        backing=RefBacking(origin="FETCHED", witness="RESOLVER")) is None
    assert store.resolving_refs == {"claim:cl_1": "p1"}
    assert store.ref_backing == {"claim:cl_1": "FETCHED"}
    unmapped = store.admit_ref(
        "claim:cl_2", "p1", backing=RefBacking(origin="INFERRED"))
    assert isinstance(unmapped, SubstrateRefusal)
    assert unmapped.code == PRIOR_ART_UNBACKED


def test_a_store_without_a_backing_mapping_reads_as_all_row() -> None:
    store = SubstrateStore()
    store.admit_ref("evidence:e1", "p1",
                    backing=RefBacking("FETCHED", "GATEWAY"))
    body = store.to_mapping()
    body.pop("ref_backing")
    reloaded = SubstrateStore.from_mapping(body)
    assert reloaded.resolving_refs == {"evidence:e1": "p1"}
    assert reloaded.ref_backing == {}


def test_the_ref_grammar_is_exact() -> None:
    assert parse_ref("evidence:abc") == ("evidence", ("abc",))
    assert parse_ref("claim:cl_1") == ("claim", ("cl_1",))
    assert parse_ref("hypothesis:rp_1/h1") == ("hypothesis", ("rp_1", "h1"))
    assert parse_ref("prediction:rp_1/h1/p1") == (
        "prediction", ("rp_1", "h1", "p1"))
    for bad in ("", "evidence:", "claim:", "hypothesis:rp_1",
                "hypothesis:rp_1/h1/x", "prediction:rp_1/h1",
                "prediction:rp_1//p1", "mystery:x"):
        assert parse_ref(bad) is None, bad


def _prior_rows(conn: Any) -> None:
    conn.execute(
        """INSERT INTO research_claims
           (claim_id, project_id, content_hash, statement, source_ref,
            schema_version, extracted_by, reason, created_at,
            context_tags_json)
           VALUES ('cl_prior', 'p1', 'h1', 'X causes Y',
                   'source_result:s1', '1', 't', NULL, ?, '{}')""",
        (CLOCK,))
    conn.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, scope_ref,
            epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            produced_by, created_at)
           VALUES ('rp_1', 'p1', 1, 'h2', 'sb_1', 'o', 'c', 'p', '1', 'i',
                   ?, ?, '[]', '[]', '[]', '{}', 't', ?)""",
        ('[{"ref": "h1"}]', '[{"ref": "p1", "claim_ref": "h1"}]', CLOCK))


def test_the_reader_classifies_rows_by_externality(tmp_path: Path) -> None:
    journal = tmp_path / "hermes.db"
    _journal(journal)
    conn = connect(journal)
    try:
        ProjectRepository(conn, lambda: CLOCK).create("p1", "p1")
        _prior_rows(conn)
        conn.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type, content_hash,
                size_bytes, storage_path, producer, metadata_json, created_at)
               VALUES ('fetched', 'p1', NULL, 'source_payload', 'fetched', 1,
                       'store/fetched', 'capability:source_fetch:test', '{}',
                       ?)""", (CLOCK,))
        conn.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type, content_hash,
                size_bytes, storage_path, producer, metadata_json, created_at)
               VALUES ('modelled', 'p1', NULL, 'provider_response', 'modelled',
                       1, 'store/modelled', 'model:test', '{}', ?)""",
            (CLOCK,))
        reader = RefProvenanceReader(conn)
        assert reader("p1", "evidence:fetched") == "FETCHED"
        assert reader("p1", "evidence:modelled") == "ROW"
        assert reader("p1", "evidence:absent") is None
        assert reader("p1", "claim:cl_prior") == "ROW"
        assert reader("p1", "claim:cl_absent") is None
        assert reader("p1", "hypothesis:rp_1/h1") == "ROW"
        assert reader("p1", "hypothesis:rp_1/h2") is None
        assert reader("p1", "prediction:rp_1/h1/p1") == "ROW"
        assert reader("p1", "prediction:rp_1/h1/p2") is None
        assert reader("p1", "prediction:rp_1/h2/p1") is None
        # Project isolation: the same rows are invisible to another project.
        assert reader("p2", "claim:cl_prior") is None
        assert reader("p2", "evidence:fetched") is None
        assert reader("p2", "hypothesis:rp_1/h1") is None
    finally:
        conn.close()


def _one_stage() -> Any:
    document = dict(LITERATURE_REVIEW_DOCUMENT)
    document["stages"] = [dict(document["stages"][0])]
    document["termination"] = {**dict(document["termination"]),
                               "max_stages": 1}
    return parse_methodology(document)


def test_the_plane_refuses_an_unbacked_admission_ref_before_any_call() -> None:
    model = _SilentModel()
    outcome = run_methodology(
        _one_stage(), "p-intake", "t", "g",
        MethodologyInputs(question="q?",
                          admission_refs=("hypothesis:prior-art-sars30/h1",)),
        model=model, orchestration=_AdmittingApplier(),
        profiles=load_profiles())
    assert isinstance(outcome, MethodologyRefusal)
    assert outcome.code == PRIOR_ART_UNBACKED
    assert outcome.source == "inputs"
    assert model.calls == []


def test_the_live_driver_refuses_an_unbacked_ref_before_any_call() -> None:
    model = _SilentModel()
    wiring = RuntimeWiring(
        model=model, orchestration=_AdmittingApplier(),
        lease_generation="g", profiles=load_profiles())
    outcome = driver_run_methodology(
        _one_stage(),
        MethodologyInputs(
            question="q?",
            admission_refs=("prediction:prior-art-sars30/h1/p1",)),
        wiring=wiring, project_id="p-intake", task_id="t")
    assert isinstance(outcome, MethodologyRefusal)
    assert outcome.code == PRIOR_ART_UNBACKED
    assert outcome.source == "inputs"
    assert model.calls == []


# ═══════════════════════ 5. depth as a field (§6.3) ═══════════════════════

DEPTH_PATH = REPO_ROOT / "scripts" / "depth_report.py"


def _load_depth_report() -> Any:
    spec = importlib.util.spec_from_file_location("depth_report", DEPTH_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


depth_report = _load_depth_report()


def _depth_spine(project: str) -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(project, project)
    return conn


def _admit_method(conn: Any, project: str, task_id: str) -> None:
    apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id=project,
        payload={
            "task_id": task_id, "task_type": "AGENT_TASK",
            "profile": "RESEARCHER",
            "spec": {"template": "methodology_run",
                     "methodology": dict(LITERATURE_REVIEW_DOCUMENT),
                     "inputs": {"question": "does it hold?",
                                "stage_content": dict(CHAIN_STATEMENTS)}},
            "idempotency_key": f"idem-{task_id}", "iteration": 1,
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": "LOW",
        }), clock=lambda: CLOCK)


def _tick(conn: Any, model: Any, project: str, *,
          provenance: Any = None) -> Any:
    handler = build_methodology_handler(
        model=model, profiles=load_profiles(), provenance_of=provenance)
    ctrl = Controller(conn, project_id=project,
                      task_handlers={"methodology_run": handler},
                      clock=lambda: CLOCK)
    return ctrl.tick()


def _failed_payload(conn: Any, task_id: str) -> tuple[dict[str, Any], str]:
    row = conn.execute(
        "SELECT payload_json, reason FROM events WHERE event_type="
        "'TaskStatusChanged' AND task_id = ? AND to_state = 'FAILED' "
        "ORDER BY event_id DESC LIMIT 1", (task_id,)).fetchone()
    assert row is not None, "the dispatch wrote no FAILED transition"
    return json.loads(row["payload_json"]), str(row["reason"])


def _stage_of(request: Any) -> str:
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


class _TaskModel:
    """A model that proposes one ordinary task on every tick."""

    def invoke(self, request: Any) -> ModelProposal:
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier="research",
            profile=request.profile,
            lease_generation=request.lease_generation,
            structured={"kind": "INSERT_TASK", "rationale": "one task",
                        "payload": {"spec": {"goal": "the stage output"}}})


class _CiteEvidenceModel:
    """OBSERVATION proposes an EVIDENCE_TRANSITION citing ``ref``."""

    def __init__(self, ref: str) -> None:
        self.ref = ref
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        structured: dict[str, Any] = {}
        if (_stage_of(request) == "OBSERVATION"
                and not any(part.origin == "runtime.review"
                            for part in request.prompt)):
            structured = {
                "kind": "EVIDENCE_TRANSITION",
                "rationale": "cite the observed artifact",
                "payload": {"evidence_artifact_ref": self.ref,
                            "from_state": "SUPPORTED",
                            "to_state": "ROBUST",
                            "rationale": "the artifact supports the rung"},
            }
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier="research",
            profile=request.profile,
            lease_generation=request.lease_generation,
            structured=structured)


def test_the_failed_event_carries_the_depth_field_at_observation() -> None:
    """Gate 7's first stop discriminator: nothing fetched, so nothing observed.

    The stop moved from EVIDENCE to OBSERVATION when an observation with no
    cited artifact stopped being recordable: the refusal now names the stage
    that failed rather than the citation the run could not have made.
    """
    conn = _depth_spine("p-depth-evidence")
    try:
        _admit_method(conn, "p-depth-evidence", "t-depth-evidence")
        out = _tick(conn, _SilentModel(), "p-depth-evidence")
        assert out.retried == ["t-depth-evidence"]
        payload, reason = _failed_payload(conn, "t-depth-evidence")
        assert payload == {
            "stages_recorded": 4,
            "stages_declared": 9,
            "stage_reached": "OBSERVATION",
            "refusal_code": "MALFORMED_PAYLOAD",
        }
        assert reason.startswith("MALFORMED_PAYLOAD")

        report = depth_report.build(conn, "p-depth-evidence")
        row = report["depth"][0]
        assert row["depth_source"] == "field"
        assert row["stages_recorded"] == 4
        assert row["stages_declared"] == 9
        assert row["stage_reached"] == "OBSERVATION"
        assert row["refusal_code"] == "MALFORMED_PAYLOAD"
        assert row["backing_class"] is None
        rendered = depth_report.render(report)
        assert 'depth_source: "field"' in rendered
        assert "OBSERVATION" in rendered
        assert "MALFORMED_PAYLOAD" in rendered
    finally:
        conn.close()


def test_the_failed_event_carries_the_backing_at_claim() -> None:
    """Gate 7's second stop: EVIDENCE over model-authored bytes reads ROW."""
    ref = "evidence:modelled-response"
    conn = _depth_spine("p-depth-claim")
    try:
        conn.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type, content_hash,
                size_bytes, storage_path, producer, metadata_json, created_at)
               VALUES ('modelled-response', 'p-depth-claim', NULL,
                       'provider_response', 'modelled-response', 1,
                       'store/modelled', 'model:test', '{}', ?)""",
            (CLOCK,))
        _admit_method(conn, "p-depth-claim", "t-depth-claim")
        out = _tick(conn, _CiteEvidenceModel(ref), "p-depth-claim",
                    provenance=RefProvenanceReader(conn))
        assert out.retried == ["t-depth-claim"]
        payload, reason = _failed_payload(conn, "t-depth-claim")
        assert payload == {
            "stages_recorded": 6,
            "stages_declared": 9,
            "stage_reached": "CLAIM",
            "refusal_code": "UNSUPPORTED_CLAIM",
            "backing_class": "ROW",
        }
        assert reason.startswith("UNSUPPORTED_CLAIM")

        report = depth_report.build(conn, "p-depth-claim")
        row = report["depth"][0]
        assert row["depth_source"] == "field"
        assert row["stage_reached"] == "CLAIM"
        assert row["refusal_code"] == "UNSUPPORTED_CLAIM"
        assert row["backing_class"] == "ROW"
    finally:
        conn.close()


def test_a_completed_run_reports_its_depth_to_its_caller() -> None:
    """The completed branch reports depth too; the driver is the handler's."""
    conn = _depth_spine("p-depth-complete")
    try:
        _admit_method(conn, "p-depth-complete", "t-depth-complete")
        row = conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id = 't-depth-complete'"
        ).fetchone()
        spec = json.loads(row["spec_json"])
        spec["methodology"]["stages"] = [
            dict(stage) for stage in spec["methodology"]["stages"][:1]]
        spec["methodology"]["termination"]["max_stages"] = 1
        spec["inputs"] = {"question": "does it hold?"}
        from hermes.research.task_handlers import _WiringContext
        handler = build_methodology_handler(model=_TaskModel(),
                                            profiles=load_profiles())
        entry = handler.bind_controller(
            orchestration=lambda intent: apply_intent(conn, intent,
                                                      clock=lambda: CLOCK),
            lease_generation=lambda: "gen")
        result = entry(_WiringContext(
            task={"task_id": "t-depth-complete", "spec": spec},
            project_id="p-depth-complete"))
        assert result.status == "completed"
        assert result.stage_depth == 1
        assert result.stage_reached == "QUESTION"
        assert result.stages_declared == 1
        assert result.refusal_code == ""
    finally:
        conn.close()
