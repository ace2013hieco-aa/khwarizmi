"""OPS-18 — the bounded project index (the read port).

Run 10's evidence, scope and dependency refusals shared one defect: the model
could not see which durable ids existed in the project. The index is one
`runtime.project_index` envelope per stage: content-free entries (`id`, `kind`,
`label`), project-scoped, ordered, capped at 40 entries and 4 KiB, with an
explicit `omitted` marker. Chain nodes come from the run's in-memory store, not
SQL; a fresh process has none.

These tests pin the approved shape and all six falsifiers: the envelope appears,
empty is explicit, truncation is honest, another project never enters, the
transaction count is identical with and without the index, a cited index id
admits, and the LOOP baseline is untouched.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import pytest

from hermes.agents.runtime.assembly import (
    PROJECT_INDEX_MAX_ENTRIES,
    PROJECT_INDEX_ORIGIN,
    ProjectIndexChainNode,
    ProjectIndexEntry,
    ProjectIndexView,
    project_index_envelope,
)
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.wiring import RuntimeWiring
from hermes.cli import main
from hermes.core.node import NodeContract
from hermes.methodology.workflows import MethodologyInputs, parse_methodology
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.research.gateway import apply_intent
from hermes.research.project_index import ProjectIndexReader
from hermes.research.task_handlers.methodology_driver import (
    MethodologyExecution,
    MethodologyRefusal,
    run_methodology,
)
from hermes.tools.models.router import ModelProposal, ModelRequest
from tests.test_ops1_live_cli import (
    KEY,
    _anthropic_reply,
    _config,
    _install_transport,
    _methodology_task,
    _project,
    _proposal_reply,
)
from tests.test_ops1_live_cli import (
    _ScriptedTransport as _LiveTransport,
)

PROJECT = "p-ops18"
OTHER = "p-ops18-other"
TASK = "meth-ops18"
LEASE = "gen-ops18"
QUESTION = "does the effect hold across the sample?"
TS = "2026-10-25T00:00:00+00:00"


# ── fixtures: real rows, real bounded reads ──


def _db(*projects: str) -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    for project in projects or (PROJECT,):
        ProjectRepository(conn).create(project, project)
    return conn


def _task(conn: Any, project: str, task_id: str, *,
          task_type: str = "AGENT_TASK", status: str | None = None,
          spec: dict[str, Any] | None = None) -> None:
    TaskRepository(conn).create(NodeContract(
        task_id=task_id, project_id=project, task_type=task_type,
        profile="RESEARCHER", idempotency_key=f"idem-{project}-{task_id}",
        spec=dict(spec or {})))
    if status is not None:
        conn.execute("UPDATE tasks SET status = ? WHERE task_id = ?",
                     (status, task_id))


def _artifact(conn: Any, project: str, artifact_id: str, *,
              artifact_type: str = "evidence",
              metadata: dict[str, Any] | None = None) -> None:
    ArtifactRepository(conn).record(
        artifact_id, artifact_type,
        hashlib.sha256(f"{project}:{artifact_id}".encode()).hexdigest(),
        1, f"/tmp/{project}/{artifact_id}", "test",
        project_id=project, metadata=dict(metadata or {}))


def _brief(conn: Any, project: str, brief_id: str, *,
           version: int = 1, scope_text: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO scope_briefs (brief_id, project_id, version, "
        "content_hash, scope_text_json, rationale, created_at, frozen_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (brief_id, project, version,
         hashlib.sha256(f"{project}:{brief_id}".encode()).hexdigest(),
         json.dumps(scope_text or {}), "", TS, TS))


def _chain(project: str, suffix: str = "00",
           kind: str = "QUESTION") -> ProjectIndexChainNode:
    return ProjectIndexChainNode(
        project_id=project, node_id=f"mnode_{suffix:0>32}", kind=kind)


def _doc(request: ModelRequest) -> dict[str, Any]:
    parts = [part for part in request.prompt
             if part.origin == PROJECT_INDEX_ORIGIN]
    assert len(parts) == 1, [part.origin for part in request.prompt]
    document = json.loads(parts[0].text)
    assert isinstance(document, dict)
    return document


# ── a model and a spine for driver-level tests ──


class _SilentModel:
    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelProposal:
        self.calls.append(request)
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier="research",
            profile=request.profile,
            lease_generation=request.lease_generation, structured={})


@dataclass(frozen=True, slots=True)
class _Applied:
    entity_id: str
    duplicate: bool


class _Applier:
    def __call__(self, intent: Any) -> _Applied:
        return _Applied(entity_id="ent_1", duplicate=False)


def _one_stage(stage: str = "QUESTION", profile: str = "planner") -> Any:
    return parse_methodology({
        "schema_version": "1", "methodology_id": "probe", "version": "1",
        "name": "probe", "description": "one stage",
        "stages": [{"stage": stage, "profile": profile}],
        "termination": {"max_stages": 1, "max_ticks_per_stage": 1,
                        "max_proposals_per_stage": 1,
                        "deadline_seconds": 30}})


def _two_stages() -> Any:
    return parse_methodology({
        "schema_version": "1", "methodology_id": "probe", "version": "1",
        "name": "probe", "description": "two stages",
        "stages": [{"stage": "QUESTION", "profile": "planner"},
                   {"stage": "HYPOTHESIS", "profile": "researcher"}],
        "termination": {"max_stages": 2, "max_ticks_per_stage": 1,
                        "max_proposals_per_stage": 1,
                        "deadline_seconds": 30}})


def _wiring(model: Any, orchestration: Any = None) -> RuntimeWiring:
    return RuntimeWiring(
        model=model, orchestration=orchestration or _Applier(),
        lease_generation=LEASE, profiles=load_profiles())


def _run(config: Any, conn: Any, model: Any, provider: Any = ...,
         orchestration: Any = None, project: str = PROJECT
         ) -> MethodologyExecution | MethodologyRefusal:
    kwargs: dict[str, Any] = {}
    if provider is not ...:
        kwargs["project_index"] = provider
    return run_methodology(
        config, MethodologyInputs(question=QUESTION),
        wiring=_wiring(model, orchestration), project_id=project,
        task_id=TASK, **kwargs)


# ── 1. the envelope: present, ordered, bounded ──


def test_a_stage_prompt_carries_the_index_from_real_rows() -> None:
    conn = _db(PROJECT)
    try:
        _task(conn, PROJECT, "task-index-target")
        _artifact(conn, PROJECT, "evidence-index-target")
        _brief(conn, PROJECT, "sb-index-target")
        model = _SilentModel()
        _run(_one_stage(), conn, model, ProjectIndexReader(conn))

        document = _doc(model.calls[0])
        by_id = {entry["id"]: entry for entry in document["entries"]}
        assert by_id["task-index-target"]["kind"] == "task"
        assert by_id["task-index-target"]["label"] == "PENDING AGENT_TASK"
        assert by_id["evidence:evidence-index-target"]["kind"] == "artifact"
        assert by_id["evidence:evidence-index-target"]["label"] == "evidence"
        assert by_id["sb-index-target"]["kind"] == "scope_brief"
        assert by_id["sb-index-target"]["label"] == "v1"
        assert document["omitted"] == 0
        parts = [part for part in model.calls[0].prompt
                 if part.origin == PROJECT_INDEX_ORIGIN]
        assert parts[0].ref == f"{PROJECT}:project_index"
    finally:
        conn.close()


def test_empty_project_is_explicit_not_silent() -> None:
    conn = _db("p-empty")
    try:
        view = ProjectIndexReader(conn)("p-empty")
        assert view.entries == ()
        assert view.total == 0
        envelope = project_index_envelope("p-empty", view)
        assert json.loads(envelope.text) == {"entries": [], "omitted": 0}
        assert envelope.origin == PROJECT_INDEX_ORIGIN
        assert envelope.ref == "p-empty:project_index"
    finally:
        conn.close()


def test_the_entry_cap_and_byte_cap_keep_omitted_truthful() -> None:
    conn = _db(PROJECT, "p-long")
    try:
        for index in range(50):
            _task(conn, PROJECT, f"task-{index:03d}")
        view = ProjectIndexReader(conn)(PROJECT)
        assert len(view.entries) == PROJECT_INDEX_MAX_ENTRIES
        assert view.total == 50
        document = json.loads(project_index_envelope(PROJECT, view).text)
        assert document["omitted"] == 10
        assert len(document["entries"]) == 40

        for index in range(40):
            _artifact(conn, "p-long",
                      f"evidence-{index:02d}-{'x' * 300}",
                      artifact_type="evidence")
        long_view = ProjectIndexReader(conn)("p-long")
        long_envelope = project_index_envelope("p-long", long_view)
        long_document = json.loads(long_envelope.text)
        assert len(long_envelope.text.encode("utf-8")) <= 4096
        assert long_document["omitted"] > 0
        assert len(long_document["entries"]) < len(long_view.entries)
        assert long_document["omitted"] == (
            long_view.total - len(long_document["entries"]))
    finally:
        conn.close()


def test_the_index_is_ordered_by_kind_then_id() -> None:
    conn = _db(PROJECT)
    try:
        _task(conn, PROJECT, "task-b")
        _task(conn, PROJECT, "task-a")
        _brief(conn, PROJECT, "sb-b", version=2)
        _brief(conn, PROJECT, "sb-a", version=1)
        _artifact(conn, PROJECT, "evidence-b")
        _artifact(conn, PROJECT, "evidence-a")
        first_node = _chain(PROJECT, "01")
        second_node = _chain(PROJECT, "02")
        view = ProjectIndexReader(conn)(PROJECT, [second_node, first_node])
        assert [(entry.kind, entry.id) for entry in view.entries] == [
            ("task", "task-a"), ("task", "task-b"),
            ("scope_brief", "sb-a"), ("scope_brief", "sb-b"),
            ("artifact", "evidence:evidence-a"),
            ("artifact", "evidence:evidence-b"),
            ("chain_node", first_node.node_id),
            ("chain_node", second_node.node_id),
        ]
    finally:
        conn.close()


# ── 2. project scope and the content bound ──


def test_another_projects_rows_with_overlapping_prefixes_never_appear() -> None:
    conn = _db(PROJECT, OTHER)
    try:
        _task(conn, PROJECT, "task-00-shared-prefix-p1")
        _task(conn, OTHER, "task-00-shared-prefix-p2")
        _artifact(conn, PROJECT, "evidence-00-shared-prefix-p1")
        _artifact(conn, OTHER, "evidence-00-shared-prefix-p2")
        _brief(conn, PROJECT, "sb-00-shared-prefix-p1")
        _brief(conn, OTHER, "sb-00-shared-prefix-p2")
        chain = [_chain(PROJECT, "01"), _chain(OTHER, "02")]

        view = ProjectIndexReader(conn)(PROJECT, chain)
        ids = {entry.id for entry in view.entries}
        assert "task-00-shared-prefix-p1" in ids
        assert "evidence:evidence-00-shared-prefix-p1" in ids
        assert "sb-00-shared-prefix-p1" in ids
        assert chain[0].node_id in ids
        for foreign in (
                "task-00-shared-prefix-p2",
                "evidence:evidence-00-shared-prefix-p2",
                "sb-00-shared-prefix-p2",
                chain[1].node_id):
            assert foreign not in ids

        # Every shown entry resolves in the named project, or is its chain node.
        for entry in view.entries:
            if entry.kind == "task":
                assert conn.execute(
                    "SELECT 1 FROM tasks WHERE task_id = ? AND project_id = ?",
                    (entry.id, PROJECT)).fetchone() is not None
            elif entry.kind == "artifact":
                carrier, _, artifact_id = entry.id.partition(":")
                assert conn.execute(
                    "SELECT 1 FROM artifacts WHERE artifact_id = ? "
                    "AND artifact_type = ? AND project_id = ?",
                    (artifact_id, carrier, PROJECT)).fetchone() is not None
            elif entry.kind == "scope_brief":
                assert conn.execute(
                    "SELECT 1 FROM scope_briefs WHERE brief_id = ? "
                    "AND project_id = ?", (entry.id, PROJECT)).fetchone() is not None
            else:
                assert entry.id.startswith("mnode_")
                assert PROJECT in {node.project_id for node in chain
                                   if node.node_id == entry.id}
    finally:
        conn.close()


def test_the_envelope_carries_no_content_and_no_admissibility_wording() -> None:
    conn = _db(PROJECT)
    try:
        _task(conn, PROJECT, "task-secret", spec={
            "goal": "TOP SECRET TASK CONTENT"})
        _artifact(conn, PROJECT, "evidence-secret", metadata={
            "secret": "ARTIFACT BODY CONTENT"})
        _brief(conn, PROJECT, "sb-secret", scope_text={
            "text": "SCOPE BRIEF CONTENT"})
        view = ProjectIndexReader(conn)(PROJECT, [
            _chain(PROJECT, "01", "HYPOTHESIS")])
        envelope = project_index_envelope(PROJECT, view)
        document = json.loads(envelope.text)

        assert set(document) == {"entries", "omitted"}
        for entry in document["entries"]:
            assert set(entry) == {"id", "kind", "label"}
        for sentinel in ("TOP SECRET TASK CONTENT", "ARTIFACT BODY CONTENT",
                         "SCOPE BRIEF CONTENT"):
            assert sentinel not in envelope.text
        assert not re.search(r"\b(available|valid|approved)\b",
                             envelope.text, re.IGNORECASE)
    finally:
        conn.close()


# ── 3. the read is read-only: the stage's control count does not move ──


def test_the_stage_transaction_count_is_identical_with_and_without_the_index(
) -> None:
    conn = _db(PROJECT)
    try:
        _task(conn, PROJECT, "task-seed")

        def control_statements(provider: Any) -> tuple[list[str], Any]:
            seen: list[str] = []
            conn.set_trace_callback(seen.append)
            try:
                model = _SilentModel()
                execution = _run(
                    _one_stage(), conn, model,
                    ProjectIndexReader(conn) if provider else ...)
            finally:
                conn.set_trace_callback(None)
            controls = [
                statement for statement in seen
                if statement.strip().upper().startswith(
                    ("BEGIN", "COMMIT", "ROLLBACK"))]
            return controls, execution

        without, without_execution = control_statements(False)
        with_index, with_execution = control_statements(True)
        assert isinstance(without_execution, MethodologyExecution)
        assert isinstance(with_execution, MethodologyExecution)
        assert with_index == without
        assert with_index == []
    finally:
        conn.close()


# ── 4. per-stage freshness and the in-memory chain half ──


def test_the_index_is_read_once_per_stage_and_chain_nodes_are_not_tasks() -> None:
    conn = _db(PROJECT)
    try:
        _task(conn, PROJECT, "task-seed")
        model = _SilentModel()
        execution = _run(
            _two_stages(), conn, model, ProjectIndexReader(conn))
        # The second stage may stop on a substrate floor; the read we are
        # pinning happens before the model call either way.
        assert isinstance(execution, (MethodologyExecution, MethodologyRefusal))
        assert len(model.calls) >= 2

        first = _doc(model.calls[0])
        second = _doc(model.calls[1])
        assert all(entry["kind"] != "chain_node"
                   for entry in first["entries"])
        chain_entries = [entry for entry in second["entries"]
                         if entry["kind"] == "chain_node"]
        assert chain_entries, "the first stage's node must reach the second index"
        assert chain_entries[0]["id"].startswith("mnode_")
        assert chain_entries[0]["label"] == (
            "QUESTION chain node (not a task id)")
        assert any(entry["kind"] == "task" for entry in second["entries"])
    finally:
        conn.close()


class _CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, project_id: str,
                 chain_nodes: Any) -> ProjectIndexView:
        self.calls += 1
        entry = ProjectIndexEntry(
            id=f"probe-{self.calls}", kind="task", label="PENDING AGENT_TASK")
        return ProjectIndexView(entries=(entry,), total=1)


def test_a_provider_is_called_once_per_stage_with_fresh_values() -> None:
    conn = _db(PROJECT)
    try:
        model = _SilentModel()
        provider = _CountingProvider()
        _run(_two_stages(), conn, model, provider)
        assert provider.calls == 2
        assert _doc(model.calls[0])["entries"][0]["id"] == "probe-1"
        assert _doc(model.calls[1])["entries"][0]["id"] == "probe-2"
    finally:
        conn.close()


def test_a_read_failure_fails_the_stage_instead_of_silently_omitting() -> None:
    conn = _db(PROJECT)
    try:
        class _Boom:
            def __call__(self, project_id: str, chain_nodes: Any) -> Any:
                raise RuntimeError("project index read failed")

        model = _SilentModel()
        with pytest.raises(RuntimeError, match="project index read failed"):
            _run(_one_stage(), conn, model, _Boom())
        assert model.calls == []
    finally:
        conn.close()


# ── 5. a cited id from the index admits ──


class _IndexCitingModel:
    """Read the index envelope, then cite an id it actually showed."""

    def __init__(self, kind: str, target_label: str = "") -> None:
        self.kind = kind
        self.target_label = target_label
        self.calls: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelProposal:
        self.calls.append(request)
        if not any(part.origin == PROJECT_INDEX_ORIGIN
                   for part in request.prompt):
            # The review child receives proposal envelopes, not the index.
            return ModelProposal(
                provider_id="scripted", model_id="scripted", tier="research",
                profile=request.profile,
                lease_generation=request.lease_generation,
                structured={"rationale": "nothing to object to",
                            "proposals": []})
        document = _doc(request)
        candidates = [entry for entry in document["entries"]
                      if entry["kind"] == self.kind
                      and (not self.target_label
                           or entry["label"] == self.target_label)]
        assert candidates, document
        target = candidates[0]["id"]
        if self.kind == "task":
            structured = {
                "kind": "INSERT_TASK", "rationale": "citing the index",
                "payload": {"spec": {"goal": "from the index"},
                            "dependencies": [target]}}
        else:
            structured = {
                "kind": "EVIDENCE_TRANSITION",
                "rationale": "citing the index",
                "payload": {"evidence_artifact_ref": target,
                            "from_state": "SUPPORTED",
                            "to_state": "ROBUST",
                            "rationale": "the index named the artifact"}}
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier="research",
            profile=request.profile,
            lease_generation=request.lease_generation,
            structured=structured)


def _real_applier(conn: Any) -> Any:
    return lambda intent: apply_intent(conn, intent)


def test_a_task_id_cited_from_the_index_no_longer_refuses_missing_dependency(
) -> None:
    conn = _db(PROJECT)
    try:
        _task(conn, PROJECT, "task-index-target")
        model = _IndexCitingModel("task")
        execution = _run(
            _one_stage(profile="researcher"), conn, model,
            ProjectIndexReader(conn), orchestration=_real_applier(conn))
        assert isinstance(execution, MethodologyExecution)
        assert execution.stages[0].state == "SUCCEEDED"
        assert execution.stages[0].intents_applied >= 1
        assert conn.execute(
            "SELECT 1 FROM task_dependencies WHERE depends_on_task_id = ?",
            ("task-index-target",)).fetchone() is not None
    finally:
        conn.close()


def test_an_evidence_ref_cited_from_the_index_no_longer_refuses_not_in_project(
) -> None:
    conn = _db(PROJECT)
    try:
        _artifact(conn, PROJECT, "evidence-index-target")
        model = _IndexCitingModel("artifact", target_label="evidence")
        execution = _run(
            _one_stage(profile="verifier"), conn, model,
            ProjectIndexReader(conn), orchestration=_real_applier(conn))
        assert isinstance(execution, MethodologyExecution)
        assert execution.stages[0].state == "SUCCEEDED"
        assert execution.stages[0].intents_applied >= 1
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = ?",
            ("EvidenceTransitionProposed",)).fetchone()[0] >= 1
    finally:
        conn.close()


# ── 6. the live composition actually injects it ──


def test_the_live_composition_renders_the_project_index(
        tmp_path: Any, capsys: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    transport = _LiveTransport(_anthropic_reply(_proposal_reply()))
    _install_transport(monkeypatch, transport)
    db = _project(tmp_path, _methodology_task())
    cfg = _config(tmp_path, db, {"m": "anthropic:test-model"})

    rc = main(["--config", str(cfg), "run", "p1", "--ticks", "2"])
    capsys.readouterr()
    assert rc == 0
    assert transport.specs
    body = json.dumps(json.loads(transport.specs[0].body))
    assert "runtime.project_index" in body
    assert "entries" in body
    assert "meth-1" in body
