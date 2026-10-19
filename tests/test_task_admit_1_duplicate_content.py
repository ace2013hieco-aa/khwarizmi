"""TASK-ADMIT-1 (GAP-1 P1-6, ruling D3-A) — fail-closed task-id admission.

At base, ``_validate_insert_task`` returns the existing row ``duplicate=True``
on ANY ``task_id`` match — no content or project comparison. A differing
proposal looks admitted and a foreign-project row can be returned. Post-fix,
``duplicate=True`` is returned ONLY when the incoming admission content
matches the stored content exactly (per the pinned canonical domain below)
AND the row belongs to the same project; both mismatches refuse with
``IDEMPOTENCY_CONFLICT`` (refusal-as-data, never silent success, never the
foreign row returned as "yours").

The pinned canonical byte domain of "exact content match": the task's
admission-content projection — ``task_type``, ``profile``,
``idempotency_key``, ``iteration``, ``parent_task_id``, ``spec``, ``inputs``,
``outputs``, ``dependencies``, ``provenance``, ``cost_class``,
``concurrency_group``, ``max_retries`` — serialized with
``json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)``
over PARSED structures on both sides (the row is read through
``TaskRepository.get``, which parses the ``*_json`` columns; the intent
payload is a dict on the wire — raw stored JSON text is never compared).

Consequences, pinned here:

- key order and JSON formatting are representation, not content: they
  normalize away (no false refusal of a logical replay);
- ``dependencies`` compares as a SET: the edges live in ``task_dependencies``
  rows whose readback order is a query-plan artifact (SQLite may serve the
  ``UNIQUE(task_id, depends_on_task_id)`` index scan, observed while
  validating this fix), never content — a same-set/different-order replay
  must stay a duplicate;
- every other list (``inputs``/``outputs``/``provenance``, arrays inside
  ``spec``) round-trips as a single JSON array, so its order is content:
  a reordered array is a differing command and refuses fail-closed;
- runtime state (``attempt``, ``status``, timestamps) is never part of
  identity: a requeue or a status transition must not turn an exact replay
  into a refusal.

``task_repo.get`` keeps its ID-keyed signature unchanged; the comparison is
validator-side.
"""
from __future__ import annotations

import json

import pytest

from hermes.core.intents import Intent, IntentKind
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    EventRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.research.gateway import (
    IDEMPOTENCY_CONFLICT,
    GatewayRejection,
    apply_intent,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"


def frozen_clock(ts: str = CLOCK):
    return lambda: ts


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    ProjectRepository(conn).create("p2", "Other")
    yield conn
    conn.close()


def task_payload(**overrides) -> dict:
    """A schema-valid INSERT_TASK payload (t1 / p1 by default)."""
    payload = {
        "task_id": "t1",
        "task_type": "AGENT_TASK",
        "profile": "RESEARCHER",
        "idempotency_key": "idem-1",
        "iteration": 1,
        "spec": {"program_id": "rp_abc", "plan_kind": "evidence_obligation"},
        "inputs": [],
        "outputs": ["evidence:SUPPORTED"],
        "dependencies": [],
        "provenance": ["spec:payload-v1"],
    }
    payload.update(overrides)
    return payload


def admit(
    conn,
    payload: dict,
    *,
    project_id: str = "p1",
    kind: IntentKind = IntentKind.INSERT_TASK,
    proposed_by: str = "DIRECTOR",
):
    return apply_intent(
        conn,
        Intent(kind=kind, proposed_by=proposed_by, project_id=project_id,
               payload=payload),
        clock=frozen_clock(),
    )


def events(conn, event_type: str, project_id: str = "p1") -> list[dict]:
    return [e for e in EventRepository(conn).list_for_project(project_id)
            if e["event_type"] == event_type]


class TestExactReplayIsDuplicate:
    def test_exact_replay_returns_duplicate_with_byte_compatible_shape(self, db):
        """Replay determinism (load-bearing): an exact replay of the same
        INSERT_TASK intent still returns ``duplicate=True`` and the stored
        row, with no new ``TaskCreated``."""
        payload = task_payload()
        first = admit(db, payload)
        assert first.duplicate is False

        replay = admit(db, payload)
        assert replay.duplicate is True
        assert replay.kind is IntentKind.INSERT_TASK
        assert replay.entity_type == "task"
        assert replay.entity_id == "t1"
        assert replay.event_type == first.event_type == "TaskCreated"
        assert replay.row == first.row
        assert len(events(db, "TaskCreated")) == 1
        # The duplicate admission is still audited (IntentApplied, no gate).
        assert len(events(db, "IntentApplied")) == 2

    def test_key_order_variant_is_duplicate(self, db):
        """Same logical content with different dict key order (incl. nested
        spec) is a duplicate, never a false refusal."""
        payload = task_payload()
        admit(db, payload)
        reordered: dict = {}
        for key in reversed(list(payload)):
            value = payload[key]
            if isinstance(value, dict):
                value = {k: value[k] for k in reversed(list(value))}
            reordered[key] = value
        assert list(reordered) != list(payload)  # the variant is real
        replay = admit(db, reordered)
        assert replay.duplicate is True

    def test_json_formatting_variant_is_duplicate(self, db):
        """A serializer variant — the same payload round-tripped through
        differently formatted JSON text — is a duplicate: the comparison
        canonicalizes parsed structures, never raw JSON text (the stored
        ``spec_json``/``inputs_json`` separators differ from the canonical
        compact form by construction)."""
        payload = task_payload()
        admit(db, payload)
        raw = db.execute(
            "SELECT spec_json FROM tasks WHERE task_id = 't1'").fetchone()[0]
        assert ", " in raw  # repository writes non-compact separators
        variant = json.loads(json.dumps(payload, indent=2, sort_keys=True))
        replay = admit(db, variant)
        assert replay.duplicate is True

    def test_tuple_vs_list_serializer_variant_is_duplicate(self, db):
        """Tuples serialize as JSON arrays: a tuple in the incoming spec is
        the same content as the stored parsed list."""
        admit(db, task_payload(spec={"tags": ["a", "b"]}))
        replay = admit(db, task_payload(spec={"tags": ("a", "b")}))
        assert replay.duplicate is True

    def test_default_expansion_variant_is_duplicate(self, db):
        """Omitting the optional fields is the same admission content as
        spelling them out at their NodeContract defaults."""
        minimal = {
            "task_id": "t1",
            "task_type": "AGENT_TASK",
            "idempotency_key": "idem-1",
        }
        first = admit(db, minimal)
        assert first.duplicate is False
        expanded = {
            "task_id": "t1",
            "task_type": "AGENT_TASK",
            "profile": None,
            "idempotency_key": "idem-1",
            "iteration": 1,
            "spec": {},
            "inputs": [],
            "outputs": [],
            "dependencies": [],
            "provenance": [],
            "cost_class": None,
            "concurrency_group": None,
            "max_retries": 3,
            "parent_task_id": None,
        }
        replay = admit(db, expanded)
        assert replay.duplicate is True

    def test_dependency_set_order_variant_is_duplicate(self, db):
        """Dependency edges are a set: a same-set/different-order payload is
        the same logical content, never a false refusal (the stored readback
        order is a SQLite query-plan artifact — observed live while
        validating this fix on the plan-admission second pass)."""
        deps = ["t2", "t3"]
        for dep in deps:
            admit(db, task_payload(
                task_id=dep, idempotency_key=f"idem-{dep}"))
        admit(db, task_payload(dependencies=["t2", "t3"]))
        replay = admit(db, task_payload(dependencies=["t3", "t2"]))
        assert replay.duplicate is True

    def test_runtime_state_change_does_not_break_replay_duplicate(self, db):
        """Status is runtime state, not content: a transition between the
        first admission and the replay keeps the replay a duplicate."""
        payload = task_payload()
        admit(db, payload)
        TaskRepository(db, frozen_clock()).transition_status(
            "t1", TaskStatus.READY)
        replay = admit(db, payload)
        assert replay.duplicate is True
        assert replay.row["status"] == TaskStatus.READY.value


class TestContentMismatchRefuses:
    @pytest.mark.parametrize(
        ("kind", "proposed_by"),
        [(IntentKind.INSERT_TASK, "DIRECTOR"),
         (IntentKind.ADMIT_TASK, "DETERMINISTIC")],
    )
    def test_differing_spec_refuses(self, db, kind, proposed_by):
        payload = task_payload()
        admit(db, payload)
        variant = task_payload(
            spec={"program_id": "rp_abc", "plan_kind": "source_fetch"})
        with pytest.raises(GatewayRejection) as exc:
            admit(db, variant, kind=kind, proposed_by=proposed_by)
        assert exc.value.code == IDEMPOTENCY_CONFLICT
        # Nothing mutated; the refusal is journalled (refusal-as-data).
        assert len(events(db, "TaskCreated")) == 1
        assert len(events(db, "IntentApplied")) == 1
        assert len(events(db, "IntentRejected")) == 1
        rejected = events(db, "IntentRejected")[0]
        assert json.loads(rejected["payload_json"])["intent_kind"] == kind.value
        # The stored row is byte-identical to the admitted content.
        row = TaskRepository(db).get("t1")
        assert row["spec"] == {"program_id": "rp_abc",
                               "plan_kind": "evidence_obligation"}

    def test_differing_outputs_refuses(self, db):
        admit(db, task_payload())
        with pytest.raises(GatewayRejection) as exc:
            admit(db, task_payload(outputs=["evidence:REFUTED"]))
        assert exc.value.code == IDEMPOTENCY_CONFLICT
        assert TaskRepository(db).get("t1")["outputs"] == ["evidence:SUPPORTED"]

    def test_reordered_list_refuses(self, db):
        """A JSON array is content, not a serializer variant: a reordered
        list is a differing command and refuses fail-closed."""
        admit(db, task_payload(outputs=["evidence:SUPPORTED", "evidence:WEAK"]))
        with pytest.raises(GatewayRejection) as exc:
            admit(db, task_payload(outputs=["evidence:WEAK", "evidence:SUPPORTED"]))
        assert exc.value.code == IDEMPOTENCY_CONFLICT

    def test_differing_scalar_field_refuses(self, db):
        admit(db, task_payload())
        with pytest.raises(GatewayRejection) as exc:
            admit(db, task_payload(max_retries=5))
        assert exc.value.code == IDEMPOTENCY_CONFLICT
        assert TaskRepository(db).get("t1")["max_retries"] == 3


class TestForeignProjectRowRefuses:
    def test_same_task_id_foreign_project_refuses(self, db):
        """The row belongs to p1; a p2 intent claiming the same task_id is
        refused — the foreign row is never returned as p2's admission."""
        first = admit(db, task_payload(), project_id="p1")
        assert first.duplicate is False
        with pytest.raises(GatewayRejection) as exc:
            admit(db, task_payload(), project_id="p2")
        assert exc.value.code == IDEMPOTENCY_CONFLICT
        assert "p1" in exc.value.reason  # the owning project is named
        assert TaskRepository(db).list_for_project("p2") == []
        assert TaskRepository(db).get("t1")["project_id"] == "p1"
        assert len(events(db, "IntentRejected", "p2")) == 1

    def test_project_mismatch_checked_before_content(self, db):
        """Project ownership is the first axis: a foreign-project intent is
        refused as a project conflict even when its content differs too."""
        admit(db, task_payload(), project_id="p1")
        with pytest.raises(GatewayRejection) as exc:
            admit(db, task_payload(spec={"other": "spec"}), project_id="p2")
        assert exc.value.code == IDEMPOTENCY_CONFLICT
        assert "p1" in exc.value.reason
