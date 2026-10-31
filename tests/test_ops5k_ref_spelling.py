"""OPS-5K — the ref spelling, the `spec` shape, and a report that shows the value.

Run 18 produced the programme's first real artifact, then refused the citation
twice:

    MALFORMED_PAYLOAD: payload.evidence_artifact_ref must be 'evidence:<artifact_id>'

The artifact existed and `EVIDENCE_REF` would have accepted it. The model copied
the observation handle (`evidence/<id>`) into a citation (`evidence:<id>`): two
separators for one reference, stated in adjacent sentences.

This file pins the three rulings:

1. **G1** — both spellings normalise to one canonical `evidence:<id>`. The id
   still dereferences through `in_project`; a ghost id under either spelling
   still refuses `EVIDENCE_REF`, and a ref with no prefix still refuses
   `MALFORMED_PAYLOAD`. Both spellings produce one transition id and one stored
   payload, so they are one reference rather than two.
2. **G2** — `payload.spec` has a stated shape, rendered from the validator's own
   constant. The sibling keys whose bespoke checks the validator also enforces
   (`iteration`, `max_retries`, the three nullable strings) are stated too;
   derived identity keys are not, because the contract forbids supplying them.
3. **G3** — a gateway refusal quotes the rejected value in its detail (bounded),
   and the runtime keeps the model's reply excerpt on the refusal, so the run
   report shows what was actually written instead of only what was required.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import hermes.research.gateway as gateway_module
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import AgentRuntime, output_contract_for
from hermes.agents.runtime.types import MALFORMED_PAYLOAD, RunLimits, TaskContext
from hermes.composition import live_contract_rules
from hermes.core.intents import Intent, IntentKind
from hermes.eval.live_vector import StageRunSnapshot
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
from hermes.research.capability_supply import artifact_handles
from hermes.research.evidence_transitions import (
    EVIDENCE_HANDLE_REF_PREFIX,
    EVIDENCE_REF_PREFIX,
    canonical_evidence_ref,
)
from hermes.research.gateway import (
    _MAX_REJECTED_VALUE_CHARS,
    _PAYLOAD_DICT_SHAPE,
    _PAYLOAD_INT_AT_LEAST_0_SHAPE,
    _PAYLOAD_INT_AT_LEAST_1_SHAPE,
    _PAYLOAD_LIST_SHAPE,
    _PAYLOAD_NULLABLE_STRING_SHAPE,
    EVIDENCE_REF,
    INTENT_PAYLOAD_SHAPES,
    GatewayRejection,
    apply_intent,
)
from hermes.run_report import build_run_report
from hermes.security.boundaries import UntrustedContent
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import ModelProposal, _contract_mapping

PROJECT = "p-ops5k"
OTHER = "p-ops5k-other"
ARTIFACT = "art_ops5k"
OTHER_ARTIFACT = "art_ops5k_other"
HASH = "a" * 64
OTHER_HASH = "b" * 64
CLOCK = "2026-10-26T12:00:00.000000+00:00"
LEASE = "gen-ops5k"

#: Every shape the `INSERT_TASK` validator enforces and the contract states.
EXPECTED_SHAPES = {
    "spec": _PAYLOAD_DICT_SHAPE,
    "inputs": _PAYLOAD_LIST_SHAPE,
    "outputs": _PAYLOAD_LIST_SHAPE,
    "dependencies": _PAYLOAD_LIST_SHAPE,
    "provenance": _PAYLOAD_LIST_SHAPE,
    "iteration": _PAYLOAD_INT_AT_LEAST_1_SHAPE,
    "max_retries": _PAYLOAD_INT_AT_LEAST_0_SHAPE,
    "parent_task_id": _PAYLOAD_NULLABLE_STRING_SHAPE,
    "cost_class": _PAYLOAD_NULLABLE_STRING_SHAPE,
    "concurrency_group": _PAYLOAD_NULLABLE_STRING_SHAPE,
}


def _db(*, other_artifact: bool = False) -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5K")
    ProjectRepository(conn, lambda: CLOCK).create(OTHER, "OPS-5K other")
    ArtifactRepository(conn, lambda: CLOCK).record(
        artifact_id=ARTIFACT, artifact_type="source_payload",
        content_hash=HASH, size_bytes=1, storage_path="seed/one",
        producer="test", project_id=PROJECT)
    if other_artifact:
        ArtifactRepository(conn, lambda: CLOCK).record(
            artifact_id=OTHER_ARTIFACT, artifact_type="source_payload",
            content_hash=OTHER_HASH, size_bytes=1, storage_path="seed/two",
            producer="test", project_id=OTHER)
    return conn


def _transition(ref: str, *, project_id: str = PROJECT) -> Intent:
    return Intent(
        kind=IntentKind.EVIDENCE_TRANSITION, proposed_by="RESEARCHER",
        project_id=project_id,
        payload={
            "evidence_artifact_ref": ref,
            "from_state": "SUPPORTED",
            "to_state": "ROBUST",
            "rationale": "the fetched source supports the rung",
        })


def _task(**extra: Any) -> Intent:
    payload: dict[str, Any] = {
        "task_id": "task-ops5k",
        "task_type": "AGENT_TASK",
        "idempotency_key": "idem-ops5k",
    }
    payload.update(extra)
    return Intent(kind=IntentKind.INSERT_TASK, proposed_by="RESEARCHER",
                  project_id=PROJECT, payload=payload)


def _shape_line(key: str, shape: str) -> str:
    return (f'For INSERT_TASK, the payload key "{key}" is optional '
            "(omitting it takes the validator's default); when supplied it "
            f"must be {shape}. Any other value is refused.")


def _mapping_with_rules(spec: Any) -> tuple[dict[str, Any], str]:
    mapping = _contract_mapping(output_contract_for(spec))
    assert mapping is not None
    available, payload_keys, payload_values, payload_shapes = (
        live_contract_rules())
    mapping["available_kinds"] = sorted(available)
    mapping["payload_keys"] = {
        kind: list(keys) for kind, keys in sorted(payload_keys.items())}
    mapping["payload_values"] = {
        kind: {key: list(values) for key, values in sets.items()}
        for kind, sets in sorted(payload_values.items())}
    mapping["payload_shapes"] = {
        kind: dict(shapes) for kind, shapes in sorted(payload_shapes.items())}
    return mapping, render_system(spec.name, mapping)


# ═══════════════ 1. G1 — one reference, two spellings ═══════════════


@pytest.mark.parametrize(("first", "second"), [
    (f"{EVIDENCE_REF_PREFIX}{ARTIFACT}", f"{EVIDENCE_HANDLE_REF_PREFIX}{ARTIFACT}"),
    (f"{EVIDENCE_HANDLE_REF_PREFIX}{ARTIFACT}", f"{EVIDENCE_REF_PREFIX}{ARTIFACT}"),
])
def test_both_spellings_resolve_to_one_reference(first: str, second: str) -> None:
    """The two spellings are one reference: same artifact, same transition id.

    The second admission is a duplicate, not a second transition — that is the
    normalisation, not a spelling tolerance that leaves two records behind.
    """
    conn = _db()
    try:
        admitted = apply_intent(conn, _transition(first))
        replay = apply_intent(conn, _transition(second))

        assert admitted.duplicate is False
        assert replay.duplicate is True
        assert replay.entity_id == admitted.entity_id
        rows = conn.execute(
            "SELECT payload_json FROM events WHERE event_type = ?",
            ("EvidenceTransitionProposed",)).fetchall()
        assert len(rows) == 1
        assert json.loads(rows[0]["payload_json"])[
            "evidence_artifact_ref"] == f"{EVIDENCE_REF_PREFIX}{ARTIFACT}"
    finally:
        conn.close()


def test_the_stored_ref_is_canonical_for_a_slash_admission() -> None:
    conn = _db()
    try:
        apply_intent(conn, _transition(
            f"{EVIDENCE_HANDLE_REF_PREFIX}{ARTIFACT}"))
        row = conn.execute(
            "SELECT payload_json FROM events WHERE event_type = ?",
            ("EvidenceTransitionProposed",)).fetchone()
        assert row is not None
        stored = json.loads(row["payload_json"])["evidence_artifact_ref"]
        assert stored == f"{EVIDENCE_REF_PREFIX}{ARTIFACT}"
        assert EVIDENCE_HANDLE_REF_PREFIX not in stored
    finally:
        conn.close()


def test_the_observation_handle_is_accepted_without_translation() -> None:
    """The handle the capability plane returns is a legal citation verbatim."""
    conn = _db()
    try:
        handle, _ = artifact_handles(
            {"artifact_id": ARTIFACT, "content_hash": HASH})
        assert handle.startswith(EVIDENCE_HANDLE_REF_PREFIX)
        result = apply_intent(conn, _transition(handle))
        assert result.entity_id
        assert result.duplicate is False
    finally:
        conn.close()


def test_the_handle_spelling_is_the_capability_plane_handle() -> None:
    """The alias is not a second literal: it is the handle's own prefix."""
    handle, _ = artifact_handles(
        {"artifact_id": ARTIFACT, "content_hash": HASH})
    assert handle == f"{EVIDENCE_HANDLE_REF_PREFIX}{ARTIFACT}"


def test_the_canonicalizer_accepts_exactly_the_two_spellings() -> None:
    assert canonical_evidence_ref(f"evidence:{ARTIFACT}") == (
        f"evidence:{ARTIFACT}")
    assert canonical_evidence_ref(f"evidence/{ARTIFACT}") == (
        f"evidence:{ARTIFACT}")
    assert canonical_evidence_ref("evidence") is None
    assert canonical_evidence_ref(f"source_payload:{HASH}") is None
    assert canonical_evidence_ref("evidence:") == "evidence:"
    assert canonical_evidence_ref("evidence/") == "evidence:"


@pytest.mark.parametrize("ref", [
    "evidence:ghost",
    "evidence/ghost",
])
def test_a_ghost_id_under_either_spelling_refuses_evidence_ref(ref: str) -> None:
    conn = _db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _transition(ref))
        assert info.value.code == EVIDENCE_REF
        assert "not in project" in info.value.reason
        assert ref in info.value.reason
    finally:
        conn.close()


@pytest.mark.parametrize("ref", [
    f"evidence:{OTHER_ARTIFACT}",
    f"evidence/{OTHER_ARTIFACT}",
])
def test_the_slash_spelling_does_not_bypass_project_scope(ref: str) -> None:
    conn = _db(other_artifact=True)
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _transition(ref))
        assert info.value.code == EVIDENCE_REF
        assert OTHER_ARTIFACT in info.value.reason
    finally:
        conn.close()


@pytest.mark.parametrize("ref", [
    "ghost",
    f"source_payload:{HASH}",
    "evidence",
    "evidence=art",
])
def test_a_ref_with_no_recognized_prefix_refuses_malformed_payload(
        ref: str) -> None:
    conn = _db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _transition(ref))
        assert info.value.code == MALFORMED_PAYLOAD
        assert f"'{EVIDENCE_REF_PREFIX}<artifact_id>'" in info.value.reason
        assert f"'{EVIDENCE_HANDLE_REF_PREFIX}<artifact_id>'" in info.value.reason
        assert ref in info.value.reason
    finally:
        conn.close()


@pytest.mark.parametrize("ref", ["evidence:", "evidence/"])
def test_an_empty_id_under_either_spelling_refuses_malformed_payload(
        ref: str) -> None:
    conn = _db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _transition(ref))
        assert info.value.code == MALFORMED_PAYLOAD
        assert "empty artifact id" in info.value.reason
    finally:
        conn.close()


# ═══════════════ 2. G2 — `spec` and the sibling shapes ═══════════════


def test_the_contract_states_the_spec_shape() -> None:
    _, rendered = _mapping_with_rules(load_profiles()["planner"])
    assert _shape_line("spec", _PAYLOAD_DICT_SHAPE) in rendered
    assert INTENT_PAYLOAD_SHAPES[IntentKind.INSERT_TASK]["spec"] == (
        _PAYLOAD_DICT_SHAPE)


def test_the_contract_states_every_enforced_shape() -> None:
    _, rendered = _mapping_with_rules(load_profiles()["planner"])
    for key, shape in EXPECTED_SHAPES.items():
        assert _shape_line(key, shape) in rendered


def test_the_shape_map_is_the_validator_shape_family() -> None:
    expected = {
        IntentKind.INSERT_TASK: dict(EXPECTED_SHAPES),
        # OPS-5Z Group E: the round's nested shapes are validated by
        # `hermes.research.verification`; the contract states the same
        # top-level family the validator enforces.
        IntentKind.REQUEST_ADDITIONAL_EXPERIMENT: {
            "claims": ("a list of exactly two claim objects "
                       "(ref, statement, source_ref)"),
            "conflict": ("the contradiction_scan conflict object "
                         "(kind, left, right, subject, date, detail)"),
            "mode": "one of the two modes derived from the claims' sources",
            "targets": ("a list of one (verify-one) or two, one per claim "
                        "(parallel-two), fetch targets "
                        "(claim_ref, provider, url)"),
        },
    }
    assert expected == INTENT_PAYLOAD_SHAPES


def test_spec_as_a_string_refuses_with_the_named_shape() -> None:
    conn = _db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _task(spec="not-a-dict"))
        assert info.value.code == MALFORMED_PAYLOAD
        assert info.value.reason.startswith(
            f"payload.spec must be {_PAYLOAD_DICT_SHAPE}")
        assert "'not-a-dict'" in info.value.reason
    finally:
        conn.close()


def test_spec_as_a_dict_drafts() -> None:
    conn = _db()
    try:
        result = apply_intent(conn, _task(spec={"goal": "run"}))
        assert result.entity_type == "task"
        assert result.row["spec"] == {"goal": "run"}
    finally:
        conn.close()


def test_an_omitted_spec_admits_an_empty_dict() -> None:
    conn = _db()
    try:
        result = apply_intent(conn, _task())
        assert result.row["spec"] == {}
    finally:
        conn.close()


@pytest.mark.parametrize(("key", "value", "shape"), [
    ("iteration", 0, _PAYLOAD_INT_AT_LEAST_1_SHAPE),
    ("iteration", "2", _PAYLOAD_INT_AT_LEAST_1_SHAPE),
    ("max_retries", -1, _PAYLOAD_INT_AT_LEAST_0_SHAPE),
    ("max_retries", "3", _PAYLOAD_INT_AT_LEAST_0_SHAPE),
    ("parent_task_id", 7, _PAYLOAD_NULLABLE_STRING_SHAPE),
    ("cost_class", 7, _PAYLOAD_NULLABLE_STRING_SHAPE),
    ("concurrency_group", 7, _PAYLOAD_NULLABLE_STRING_SHAPE),
])
def test_each_stated_scalar_shape_refuses(
        key: str, value: Any, shape: str) -> None:
    conn = _db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _task(**{key: value}))
        assert info.value.code == MALFORMED_PAYLOAD
        assert info.value.reason.startswith(f"payload.{key} must be {shape}")
    finally:
        conn.close()


def test_the_scalar_shapes_admit_legal_values() -> None:
    conn = _db()
    try:
        result = apply_intent(conn, _task(
            iteration=2, max_retries=0, parent_task_id="parent",
            cost_class="standard", concurrency_group="group"))
        assert result.row["iteration"] == 2
        assert result.row["max_retries"] == 0
        assert result.row["parent_task_id"] == "parent"
        assert result.row["cost_class"] == "standard"
        assert result.row["concurrency_group"] == "group"
    finally:
        conn.close()


def test_shape_drift_flows_into_the_contract(monkeypatch: Any) -> None:
    spec = load_profiles()["planner"]
    monkeypatch.setattr(gateway_module, "INTENT_PAYLOAD_SHAPES", {
        IntentKind.INSERT_TASK: {"spec": "a probe spec shape"}})

    _, rendered = _mapping_with_rules(spec)

    assert _shape_line("spec", "a probe spec shape") in rendered
    assert _shape_line("spec", _PAYLOAD_DICT_SHAPE) not in rendered
    assert _shape_line("inputs", _PAYLOAD_LIST_SHAPE) not in rendered


# ═══════════════ 3. G3 — the refused value reaches the report ═══════════════


def test_a_gateway_refusal_carries_the_rejected_ref_in_its_detail() -> None:
    ref = f"{EVIDENCE_HANDLE_REF_PREFIX}ghost-artifact"
    conn = _db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _transition(ref))
        assert ref in info.value.reason
        assert "ghost-artifact" in info.value.reason
    finally:
        conn.close()


def test_a_gateway_refusal_bounds_the_rejected_value() -> None:
    ref = f"{EVIDENCE_HANDLE_REF_PREFIX}" + "x" * 5_000
    conn = _db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _transition(ref))
        assert info.value.code == EVIDENCE_REF
        assert "..." in info.value.reason
        assert "chars)" in info.value.reason
        # The bound, not the 5 000-character value, rides the refusal. Two
        # quoted values appear (the parsed id and the raw ref), each bounded.
        assert len(info.value.reason) < 2 * _MAX_REJECTED_VALUE_CHARS + 200
    finally:
        conn.close()


def test_a_spec_refusal_carries_the_rejected_value_in_its_detail() -> None:
    conn = _db()
    try:
        with pytest.raises(GatewayRejection) as info:
            apply_intent(conn, _task(spec=["not", "a", "dict"]))
        assert "'not'" in info.value.reason
    finally:
        conn.close()


class _ReplyModel:
    """One scripted reply, carried both structured and as the raw excerpt."""

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier=request.tier,
            profile=request.profile,
            lease_generation=request.lease_generation,
            content=UntrustedContent(
                text=json.dumps(self.reply), origin="model.output"),
            structured=dict(self.reply))


def _report_for(result: Any) -> dict[str, Any]:
    return build_run_report(
        run_id="run_ops5k", project_id=PROJECT, started_at=CLOCK,
        ticks=result.ticks or 1,
        stage_runs=(StageRunSnapshot(stage="OBSERVATION", result=result),),
        ledger=(), notes=(), vector="")


def test_a_gateway_refusal_reaches_the_report_with_the_reply_excerpt() -> None:
    """The G1 refusal used to have an empty excerpt; the report now shows it."""
    ref = f"{EVIDENCE_HANDLE_REF_PREFIX}ghost-artifact"
    reply = {
        "kind": "EVIDENCE_TRANSITION",
        "rationale": "cite the artifact this stage fetched",
        "payload": {
            "evidence_artifact_ref": ref,
            "from_state": "SUPPORTED",
            "to_state": "ROBUST",
            "rationale": "the fetched source supports the rung",
        },
    }
    conn = _db()
    try:
        runtime = AgentRuntime(
            model=_ReplyModel(reply),
            orchestration=lambda intent: apply_intent(conn, intent))
        result = runtime.run("researcher", TaskContext(
            task_id="task-ops5k", project_id=PROJECT, lease_generation=LEASE,
            limits=RunLimits(max_ticks=1)))

        assert result.refusals
        refusal = result.refusals[0]
        assert ref in refusal.detail
        assert ref in refusal.excerpt

        report = _report_for(result)
        entry = report["refusals"][0]
        assert ref in entry["detail"]
        assert ref in entry["excerpt"]
    finally:
        conn.close()


def test_the_report_entry_is_bounded_by_the_configured_excerpt_cap() -> None:
    ref = f"{EVIDENCE_HANDLE_REF_PREFIX}" + "y" * 5_000
    reply = {
        "kind": "EVIDENCE_TRANSITION",
        "rationale": "cite the artifact this stage fetched",
        "payload": {
            "evidence_artifact_ref": ref,
            "from_state": "SUPPORTED",
            "to_state": "ROBUST",
            "rationale": "the fetched source supports the rung",
        },
    }
    conn = _db()
    try:
        runtime = AgentRuntime(
            model=_ReplyModel(reply),
            orchestration=lambda intent: apply_intent(conn, intent))
        result = runtime.run("researcher", TaskContext(
            task_id="task-ops5k", project_id=PROJECT, lease_generation=LEASE,
            limits=RunLimits(max_ticks=1)))

        report = build_run_report(
            run_id="run_ops5k", project_id=PROJECT, started_at=CLOCK,
            ticks=1,
            stage_runs=(StageRunSnapshot(stage="OBSERVATION", result=result),),
            ledger=(), notes=(), vector="", excerpt_bytes=128)
        entry = report["refusals"][0]
        assert len(entry["excerpt"].encode("utf-8")) <= 128
        assert entry["detail"]
    finally:
        conn.close()
