"""P-AUTO-1 deterministic sequencer tests.

Tests for the deterministic sequencer pass that:
- Reads READY tasks + dependencies + terminal states + ladder/failure signals
- Emits ADMIT_TASK with proposed_by=DETERMINISTIC through apply_intent only
- Dependency-respect ordering (topological sort)
- No-op when nothing ready
- Starvation-freedom (documented in code/test docstring)
"""

from __future__ import annotations

import json

from hermes.core import advancing_clock, frozen_clock
from hermes.core.intents import Intent, IntentKind
from hermes.core.node import NodeContract, NodeType
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    OperatorCredentialRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.research.controller import Controller
from hermes.research.extraction import build_extract_task_payload
from hermes.research.gateway import apply_intent

CLOCK = "2026-01-01T00:00:00.000000+00:00"
LATER = "2026-06-01T00:00:00.000000+00:00"


def _setup_db_with_dataset():
    """Create a fresh DB with project, operator, and dataset manifest."""
    clock = frozen_clock(CLOCK)
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, clock).create("p1", "Test")
    OperatorCredentialRepository(conn, clock).register("op-1", "token-1234", "Test Operator")
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, CLOCK),
    )
    return conn, clock


def _admit_extract_task(conn, clock, source_ref="dataset_manifest:dm-1"):
    """Admit an EXTRACT task via the gateway."""
    result = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1", payload=build_extract_task_payload(source_ref)))
    return result.entity_id


def _plain_task(conn, task_id, created_at, *, cost_class="LOW"):
    """A dependency-free AGENT_TASK stamped at ``created_at``. Template ``x``
    is unhandled by the controller, so the row stays PENDING: a pure ordering
    input that is never claimed and never terminalized."""
    return TaskRepository(conn, clock=frozen_clock(created_at)).create(
        NodeContract(
            task_id=task_id, project_id="p1",
            task_type=NodeType.AGENT_TASK.value, idempotency_key=task_id,
            status=TaskStatus.PENDING.value, spec={"template": "x"},
            dependencies=[], provenance=[], cost_class=cost_class))


def _stale_seq_row(conn, task_id):
    """A second recorded-only artifact (distinct ready set ⇒ distinct
    content-addressed id) left PENDING, as an earlier pass would leave it."""
    return TaskRepository(conn, clock=frozen_clock(CLOCK)).create(
        NodeContract(
            task_id=task_id, project_id="p1",
            task_type=NodeType.TOOL_TASK.value, idempotency_key=task_id,
            status=TaskStatus.PENDING.value,
            spec={"template": "sequencer", "sequence": [],
                  "sequencer_version": 1},
            dependencies=[], provenance=[], cost_class="LOW"))


def _latest_sequence(conn):
    """The ``sequence`` recorded by the newest non-CANCELLED artifact."""
    row = conn.execute(
        "SELECT spec_json FROM tasks WHERE task_id LIKE 'seq-%' "
        "AND status != 'CANCELLED' ORDER BY created_at DESC LIMIT 1").fetchone()
    return json.loads(row["spec_json"])["sequence"]


class TestSequencerOrderingDeterminism:
    """The sequencer produces the same order for the same ready task set."""

    def test_same_ready_set_yields_same_sequence_idempotent(self):
        """Re-running the sequencer pass with identical ready tasks emits
        the same sequencer task_id (idempotent ADMIT_TASK)."""
        conn, clock = _setup_db_with_dataset()
        _admit_extract_task(conn, clock)

        ctrl = Controller(conn, project_id="p1", clock=clock)

        # First tick: sequencer runs, creates sequencer task
        ctrl.tick()
        seq_tasks_1 = [r[0] for r in conn.execute(
            "SELECT task_id FROM tasks WHERE task_id LIKE 'seq-%'")]
        assert len(seq_tasks_1) == 1
        seq_id_1 = seq_tasks_1[0]

        # Second tick: same ready set (extract still PENDING, sequencer exists)
        # should NOT create a new sequencer task
        ctrl.tick()
        seq_tasks_2 = [r[0] for r in conn.execute(
            "SELECT task_id FROM tasks WHERE task_id LIKE 'seq-%'")]
        assert len(seq_tasks_2) == 1
        assert seq_tasks_2[0] == seq_id_1

    def test_deterministic_order_across_ticks(self):
        """The topological order is deterministic and stable across ticks."""
        conn, clock = _setup_db_with_dataset()
        # Admit two independent extract tasks
        extract_id_1 = _admit_extract_task(conn, clock, "dataset_manifest:dm-1")
        # Need a second dataset for the second task
        conn.execute(
            """INSERT INTO dataset_manifests
               (manifest_id, project_id, location, format, size_bytes,
                headers_json, schema_observations_json, query_recipes_json,
                content_hash, provenance_json, created_at, immutable)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            ("dm-2", "p1", "y.csv", "csv", 1, "[]", "[]", "[]",
             "h2", None, CLOCK),
        )
        extract_id_2 = _admit_extract_task(conn, clock, "dataset_manifest:dm-2")

        ctrl = Controller(conn, project_id="p1", clock=clock)
        ctrl.tick()

        # Get the sequencer task and verify its sequence
        seq_row = conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id LIKE 'seq-%'").fetchone()
        assert seq_row is not None
        import json
        spec = json.loads(seq_row["spec_json"])
        sequence = spec.get("sequence", [])

        # Both extract tasks should be in the sequence (order may vary but is deterministic)
        assert set(sequence) == {extract_id_1, extract_id_2}
        # Run again - sequence should be identical
        ctrl.tick()
        seq_row_2 = conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id LIKE 'seq-%'").fetchone()
        spec_2 = json.loads(seq_row_2["spec_json"])
        assert spec_2.get("sequence") == sequence


class TestSequencerDependencyRespect:
    """The sequencer respects task dependencies in its ordering."""

    def test_dependent_task_not_sequenced_until_dep_succeeded(self):
        """A task with an unsatisfied dependency is not sequenced until the
        dependency reaches SUCCEEDED."""
        conn, clock = _setup_db_with_dataset()
        extract_id_1 = _admit_extract_task(conn, clock)

        # Admit a second extract task that depends on the first
        conn.execute(
            """INSERT INTO dataset_manifests
               (manifest_id, project_id, location, format, size_bytes,
                headers_json, schema_observations_json, query_recipes_json,
                content_hash, provenance_json, created_at, immutable)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            ("dm-2", "p1", "y.csv", "csv", 1, "[]", "[]", "[]",
             "h2", None, CLOCK),
        )
        extract_id_2 = _admit_extract_task(conn, clock, "dataset_manifest:dm-2")

        # Add dependency: extract_id_2 depends on extract_id_1
        conn.execute(
            "INSERT INTO task_dependencies (task_id, depends_on_task_id, created_at) VALUES (?, ?, ?)",
            (extract_id_2, extract_id_1, CLOCK),
        )

        ctrl = Controller(conn, project_id="p1", clock=clock)
        ctrl.tick()

        # Only extract_id_1 should be in the sequence (extract_id_2 not READY)
        seq_row = conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id LIKE 'seq-%' "
            "AND status != 'CANCELLED' ORDER BY created_at DESC LIMIT 1").fetchone()
        assert seq_row is not None
        import json
        spec = json.loads(seq_row["spec_json"])
        sequence = spec.get("sequence", [])
        assert sequence == [extract_id_1]
        assert extract_id_2 not in sequence

        # Mark extract_id_1 as SUCCEEDED
        conn.execute("UPDATE tasks SET status='SUCCEEDED' WHERE task_id=?", (extract_id_1,))

        # Next tick: extract_id_2 should now be READY and sequenced
        # (extract_id_1 is SUCCEEDED, so not sequenced)
        ctrl.tick()
        seq_row_2 = conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id LIKE 'seq-%' "
            "AND status != 'CANCELLED' ORDER BY created_at DESC LIMIT 1").fetchone()
        spec_2 = json.loads(seq_row_2["spec_json"])
        sequence_2 = spec_2.get("sequence", [])
        # Only extract_id_2 is READY now (extract_id_1 is SUCCEEDED)
        assert sequence_2 == [extract_id_2]

    def test_independent_tasks_any_deterministic_order(self):
        """Independent tasks are ordered deterministically (lexicographic tie-break)."""
        conn, clock = _setup_db_with_dataset()
        conn.execute(
            """INSERT INTO dataset_manifests
               (manifest_id, project_id, location, format, size_bytes,
                headers_json, schema_observations_json, query_recipes_json,
                content_hash, provenance_json, created_at, immutable)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            ("dm-2", "p1", "y.csv", "csv", 1, "[]", "[]", "[]",
             "h2", None, CLOCK),
        )
        extract_id_1 = _admit_extract_task(conn, clock, "dataset_manifest:dm-1")
        extract_id_2 = _admit_extract_task(conn, clock, "dataset_manifest:dm-2")

        ctrl = Controller(conn, project_id="p1", clock=clock)
        ctrl.tick()

        seq_row = conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id LIKE 'seq-%'").fetchone()
        assert seq_row is not None
        import json
        spec = json.loads(seq_row["spec_json"])
        sequence = spec.get("sequence", [])

        # Both tasks in sequence
        assert set(sequence) == {extract_id_1, extract_id_2}
        # Order should be lexicographically sorted (deterministic tie-break)
        assert sequence == sorted([extract_id_1, extract_id_2])


class TestSequencerNoOpWhenIdle:
    """The sequencer is a no-op when there are no READY tasks."""

    def test_no_ready_tasks_no_sequencer_task(self):
        """When no tasks are READY/PENDING/RETRYING, sequencer emits nothing."""
        conn, clock = _setup_db_with_dataset()
        ctrl = Controller(conn, project_id="p1", clock=clock)

        # No tasks admitted - sequencer should be no-op
        ctrl.tick()
        seq_count = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE task_id LIKE 'seq-%'").fetchone()[0]
        assert seq_count == 0

    def test_completed_tasks_not_sequenced(self):
        """Tasks in terminal states (SUCCEEDED/FAILED) are not sequenced."""
        conn, clock = _setup_db_with_dataset()
        extract_id = _admit_extract_task(conn, clock)

        ctrl = Controller(conn, project_id="p1", clock=clock)
        # First tick: admit extract, but don't run it (no extract_fn)
        ctrl.tick()
        # Manually mark as SUCCEEDED
        conn.execute("UPDATE tasks SET status='SUCCEEDED' WHERE task_id=?", (extract_id,))

        # Second tick: no READY tasks (extract is SUCCEEDED, sequencer is PENDING but filtered)
        ctrl.tick()
        # Should not create a NEW sequencer task (existing one is filtered from ready)
        seq_count = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE task_id LIKE 'seq-%'").fetchone()[0]
        assert seq_count == 1  # Original sequencer task still exists, no new one


class TestSequencerStarvationFreedom:
    """Starvation-freedom: every READY task is included on every tick.

    The order derives from the dependency DAG (content-addressed
    task_ids, fixed dependency edges, lexicographic tie-break), never
    from arrival time or priority. Positions may shift as the ready set
    changes; inclusion is what cannot be permanently denied.
    """

    def test_starvation_freedom_documented(self):
        """Starvation-freedom note required by P-AUTO-1 (corrected: F2).

        The true property (inclusion plus fixed-set stability):
        1. The same ready set always yields the same topological order
        2. A task's inclusion never depends on arrival time or priority
        3. New tasks cannot permanently displace existing ones — both
           stay sequenced; only relative positions may shift
        4. The order is recomputed every tick and stable per ready set
        """
        # Property 2, exercised: inclusion is total over the ready set —
        # cost class is an ordering input, never an admission one.
        conn, clock = _setup_db_with_dataset()
        extract_id = _admit_extract_task(conn, clock)
        _plain_task(conn, "t-high", LATER, cost_class="HIGH")
        _plain_task(conn, "t-low", LATER)
        Controller(conn, project_id="p1", clock=clock).tick()
        assert set(_latest_sequence(conn)) == {extract_id, "t-high", "t-low"}

    def test_new_ready_task_does_not_starve_existing(self):
        """A newly-ready task cannot permanently precede an existing ready task."""
        conn, clock = _setup_db_with_dataset()
        extract_id_1 = _admit_extract_task(conn, clock)

        ctrl = Controller(conn, project_id="p1", clock=clock)
        ctrl.tick()

        # Get first sequence
        seq_row_1 = conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id LIKE 'seq-%'").fetchone()
        import json
        spec_1 = json.loads(seq_row_1["spec_json"])
        seq_1 = spec_1.get("sequence", [])
        assert extract_id_1 in seq_1

        # Add a second task (independent)
        conn.execute(
            """INSERT INTO dataset_manifests
               (manifest_id, project_id, location, format, size_bytes,
                headers_json, schema_observations_json, query_recipes_json,
                content_hash, provenance_json, created_at, immutable)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            ("dm-2", "p1", "y.csv", "csv", 1, "[]", "[]", "[]",
             "h2", None, CLOCK),
        )
        extract_id_2 = _admit_extract_task(conn, clock, "dataset_manifest:dm-2")

        # The new task is PENDING/READY. Re-run sequencer.
        ctrl.tick()

        # The existing task should still be in the sequence (not starved)
        # Get the latest (non-CANCELLED) sequencer task
        seq_row_2 = conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id LIKE 'seq-%' "
            "AND status != 'CANCELLED' ORDER BY created_at DESC LIMIT 1").fetchone()
        spec_2 = json.loads(seq_row_2["spec_json"])
        seq_2 = spec_2.get("sequence", [])
        assert extract_id_1 in seq_2
        assert extract_id_2 in seq_2
        # The relative order is deterministic (lexicographic)
        assert seq_2 == sorted([extract_id_1, extract_id_2])


class TestSequencerIntegration:
    """Integration tests for the sequencer pass in the tick loop."""

    def test_sequencer_runs_in_tick_loop(self):
        """The sequencer pass runs as part of the controller tick."""
        conn, clock = _setup_db_with_dataset()
        _admit_extract_task(conn, clock)

        ctrl = Controller(conn, project_id="p1", clock=clock)
        ctrl.tick()

        # Sequencer should have created a task
        seq_count = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE task_id LIKE 'seq-%'").fetchone()[0]
        assert seq_count == 1

    def test_sequencer_uses_deterministic_provenance(self):
        """Sequencer ADMIT_TASK uses deterministic provenance fields."""
        conn, clock = _setup_db_with_dataset()
        _admit_extract_task(conn, clock)

        ctrl = Controller(conn, project_id="p1", clock=clock)
        ctrl.tick()

        # Check IntentApplied event for sequencer
        events = conn.execute(
            "SELECT payload_json FROM events WHERE event_type='IntentApplied' "
            "AND payload_json LIKE '%sequencer%'").fetchall()
        assert len(events) == 1
        import json
        payload = json.loads(events[0]["payload_json"])
        assert payload.get("proposed_by") == "DETERMINISTIC"
        assert payload.get("origin_kind") == "deterministic"
        assert payload.get("origin_ref") == "sequencer_pass"

    def test_sequencer_respects_project_isolation(self):
        """Sequencer only sequences tasks in its own project."""
        conn, clock = _setup_db_with_dataset()
        # Create second project
        ProjectRepository(conn, clock).create("p2", "Test2")
        OperatorCredentialRepository(conn, clock).register("op-2", "token-5678", "Test Operator 2")
        conn.execute(
            """INSERT INTO dataset_manifests
               (manifest_id, project_id, location, format, size_bytes,
                headers_json, schema_observations_json, query_recipes_json,
                content_hash, provenance_json, created_at, immutable)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            ("dm-3", "p2", "z.csv", "csv", 1, "[]", "[]", "[]",
             "h3", None, CLOCK),
        )

        extract_id_1 = _admit_extract_task(conn, clock)
        # Admit task in project 2
        apply_intent(conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p2", payload=build_extract_task_payload("dataset_manifest:dm-3")))

        # Run controller for p1
        ctrl1 = Controller(conn, project_id="p1", clock=clock)
        ctrl1.tick()

        # Sequencer for p1 should only see p1's task
        seq_row = conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id LIKE 'seq-p1-%'").fetchone()
        assert seq_row is not None
        import json
        spec = json.loads(seq_row["spec_json"])
        sequence = spec.get("sequence", [])
        assert sequence == [extract_id_1]

        # Run controller for p2
        ctrl2 = Controller(conn, project_id="p2", clock=clock)
        ctrl2.tick()

        # Sequencer for p2 should only see p2's task
        seq_row_2 = conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id LIKE 'seq-p2-%'").fetchone()
        assert seq_row_2 is not None
        spec_2 = json.loads(seq_row_2["spec_json"])
        sequence_2 = spec_2.get("sequence", [])
        assert len(sequence_2) == 1
        assert sequence_2[0].startswith("extract_")


class TestSequencerNamespaceFix:
    """F1: sequencer rows are predicated on spec.template, not the ID prefix."""

    def test_user_seq_prefix_task_is_sequenced_never_cancelled(self):
        """A user task_id starting with seq- is sequenced, never CANCELLED."""
        conn, clock = _setup_db_with_dataset()
        payload = build_extract_task_payload("dataset_manifest:dm-1")
        payload["task_id"] = "seq-trap"
        payload["idempotency_key"] = "seq-trap-key"
        result = apply_intent(conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1", payload=payload))
        assert result.entity_id == "seq-trap"

        ctrl = Controller(conn, project_id="p1", clock=clock)
        ctrl.tick()
        ctrl.tick()

        status = conn.execute(
            "SELECT status FROM tasks WHERE task_id='seq-trap'").fetchone()[0]
        assert status != "CANCELLED"
        seq_row = conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id LIKE 'seq-p1-%' "
            "AND status != 'CANCELLED' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert seq_row is not None
        import json
        sequence = json.loads(seq_row["spec_json"]).get("sequence", [])
        assert "seq-trap" in sequence

    def test_genuine_sequencer_task_still_superseded(self):
        """Supersede-cancel still fires for real template-marked seq rows."""
        conn, clock = _setup_db_with_dataset()
        _admit_extract_task(conn, clock)
        ctrl = Controller(conn, project_id="p1", clock=clock)
        ctrl.tick()
        first = [r[0] for r in conn.execute(
            "SELECT task_id FROM tasks WHERE task_id LIKE 'seq-%'")]
        assert len(first) == 1
        # Admit a second task: the ready set changes, so the next pass
        # supersedes the first sequencer row with a new one.
        conn.execute(
            """INSERT INTO dataset_manifests
               (manifest_id, project_id, location, format, size_bytes,
                headers_json, schema_observations_json, query_recipes_json,
                content_hash, provenance_json, created_at, immutable)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            ("dm-2", "p1", "y.csv", "csv", 1, "[]", "[]", "[]",
             "h2", None, CLOCK),
        )
        _admit_extract_task(conn, clock, "dataset_manifest:dm-2")
        ctrl.tick()
        rows = {r[0]: r[1] for r in conn.execute(
            "SELECT task_id, status FROM tasks WHERE task_id LIKE 'seq-%'")}
        assert len(rows) == 2
        assert rows[first[0]] == "CANCELLED"
        assert [s for s in rows.values() if s != "CANCELLED"] != []


class TestSequencerCycleFallback:
    """F4: the cycle fallback orders by (created_at, task_id)."""

    def test_cycle_fallback_is_created_at_then_task_id_deterministic(self):
        """A cyclic ready subgraph falls back deterministically (tied stamps)."""
        conn, clock = _setup_db_with_dataset()
        task_a = _admit_extract_task(conn, clock)
        conn.execute(
            """INSERT INTO dataset_manifests
               (manifest_id, project_id, location, format, size_bytes,
                headers_json, schema_observations_json, query_recipes_json,
                content_hash, provenance_json, created_at, immutable)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            ("dm-2", "p1", "y.csv", "csv", 1, "[]", "[]", "[]",
             "h2", None, CLOCK),
        )
        task_b = _admit_extract_task(conn, clock, "dataset_manifest:dm-2")
        # A genuine cycle (unreachable via discovery, which requires
        # SUCCEEDED deps): force the subgraph through the pass directly.
        conn.execute(
            "INSERT INTO task_dependencies (task_id, depends_on_task_id, created_at)"
            " VALUES (?, ?, ?)",
            (task_a, task_b, CLOCK),
        )
        conn.execute(
            "INSERT INTO task_dependencies (task_id, depends_on_task_id, created_at)"
            " VALUES (?, ?, ?)",
            (task_b, task_a, CLOCK),
        )
        # Gateway admission stamps real time: pin tied created_at values so
        # the test deterministically exercises the task_id tiebreak branch.
        conn.execute(
            "UPDATE tasks SET created_at = ? WHERE task_id IN (?, ?)",
            (CLOCK, task_a, task_b),
        )
        ctrl = Controller(conn, project_id="p1", clock=clock)
        # Discovery requires SUCCEEDED deps, so a genuine cycle never
        # surfaces through it: replay full-shape rows (same shaping as
        # _discover_eligible) past the eligibility filter for this tick.
        # Only the sequencer and dispatch passes consume discovery, and
        # dispatch parks EXTRACT tasks as unhandled (no extract_fn wired).
        def cyclic_rows():
            import json as _json
            out = []
            rows = conn.execute(
                "SELECT * FROM tasks WHERE project_id = 'p1' "
                "AND task_id NOT LIKE 'seq-%'").fetchall()
            for r in rows:
                d = dict(r)
                spec = d.pop("spec_json") or {}
                if isinstance(spec, str):
                    try:
                        spec = _json.loads(spec)
                    except ValueError:
                        spec = {}
                d["spec"] = spec
                out.append(d)
            return out
        ctrl._discover_eligible = cyclic_rows  # type: ignore[method-assign]
        ctrl.tick()
        assert any("cycle detected" in note for note in ctrl.notes)
        seq_row = conn.execute(
            "SELECT task_id, spec_json FROM tasks WHERE task_id LIKE 'seq-%' "
            "AND status != 'CANCELLED'").fetchone()
        assert seq_row is not None
        import json
        sequence = json.loads(seq_row["spec_json"]).get("sequence", [])
        # Tied created_at values break on task_id: fully deterministic.
        assert sequence == sorted([task_a, task_b])
        assert sequence == sorted(
            [task_a, task_b],
            key=lambda tid: (CLOCK, tid))


class TestSequencerArtifactOutOfDispatchOrdering:
    """Merge-audit M1/M2: the recorded-only artifact is not dispatch work.

    The artifact is admitted PENDING and is never terminalized, so under a
    live (advancing) clock its stamp precedes every task admitted after the
    pass that produced it. Left in the eligible set it would be the
    pure-policy ``(created_at, task_id)`` leader, a C4 floor input, and a
    permanent defeat of every ``if not tasks:`` idle consumer.
    """

    def _live(self):
        conn = connect(":memory:")
        migrate_to_latest(conn)
        clock = advancing_clock(CLOCK)
        ProjectRepository(conn, clock).create("p1", "Test")
        _plain_task(conn, "t-later", LATER)
        return conn, clock

    def test_artifact_is_absent_from_the_eligible_set_and_the_ranking(self):
        conn, clock = self._live()
        ctrl = Controller(conn, project_id="p1", clock=clock)
        result = ctrl.tick()
        seq_rows = [r["task_id"] for r in conn.execute(
            "SELECT task_id FROM tasks WHERE task_id LIKE 'seq-%'")]
        assert len(seq_rows) == 1, "precondition: the sequencer admitted one"
        seq_id = seq_rows[0]

        assert seq_id not in result.unhandled
        assert seq_id not in result.dispatched
        assert result.unhandled == ["t-later"]

        # The fence is rebuilt on lock acquisition (as tick() does); the
        # private discovery/ordering methods are only valid under it.
        assert ctrl._acquire_lock()
        eligible = ctrl._discover_eligible()
        assert [t["task_id"] for t in eligible] == ["t-later"]
        ordered, ranking = ctrl._order_eligible(eligible)
        assert [t["task_id"] for t in ordered] == ["t-later"]
        assert ranking is not None
        assert [c.task_ref for c in ranking.comparison] == ["t-later"]
        ctrl._release_lock()

    def test_inert_artifact_leaves_the_eligible_set_empty(self):
        """M1: with the only real task terminal, the eligible set must be
        empty even though the artifact is still PENDING — otherwise the
        dispatch pass is never idle again and the Q-04 §3.4 cone diagnostic
        is silenced for the rest of the project's life."""
        conn, clock = self._live()
        ctrl = Controller(conn, project_id="p1", clock=clock)
        ctrl.tick()
        repo = TaskRepository(conn, clock=clock)
        for nxt in (TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.SUCCEEDED):
            repo.transition_status("t-later", nxt, caused_by="test")
        assert conn.execute(
            "SELECT status FROM tasks WHERE task_id LIKE 'seq-%'"
        ).fetchone()[0] == TaskStatus.PENDING.value, "never terminalized"

        assert ctrl._acquire_lock()
        assert ctrl._discover_eligible() == []
        ctrl._release_lock()


class TestSequencerFaultNotes:
    """Merge-audit M3/M4: the notes channel reports faults — not routine
    absence — and keeps one entry per faulted row."""

    def test_first_pass_records_no_get_fault_note(self):
        """M3: no prior artifact for this ready set IS the normal first pass.
        Recording it as a fault put a spurious line on the public ``notes``
        surface of every project's first sequencer pass."""
        conn, clock = _setup_db_with_dataset()
        _admit_extract_task(conn, clock)
        ctrl = Controller(conn, project_id="p1", clock=clock)
        ctrl.tick()
        assert conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE task_id LIKE 'seq-%'"
        ).fetchone()[0] == 1, "precondition: the artifact was admitted"
        assert not [n for n in ctrl.notes if "get fault" in n]

    def test_distinct_cancel_faults_keep_distinct_notes(self, monkeypatch):
        """M4: one constant key collapsed every cancel fault into a single
        last-writer-wins entry. The key is scoped to the row that faulted,
        per the documented ``<surface>:<condition>:<identity>`` convention."""
        conn, clock = _setup_db_with_dataset()
        _admit_extract_task(conn, clock)
        stale_a = "seq-p1-stale000000000000000000000a"
        stale_b = "seq-p1-stale000000000000000000000b"
        _stale_seq_row(conn, stale_a)
        _stale_seq_row(conn, stale_b)
        ctrl = Controller(conn, project_id="p1", clock=clock)
        real = TaskRepository.transition_status

        def _refuse_seq_cancels(self, task_id, *args, **kwargs):
            if task_id.startswith("seq-"):
                raise RuntimeError(f"cancel refused for {task_id}")
            return real(self, task_id, *args, **kwargs)

        monkeypatch.setattr(TaskRepository, "transition_status",
                            _refuse_seq_cancels)
        assert ctrl._acquire_lock()
        ctrl._sequencer_pass()
        ctrl._release_lock()

        faults = [n for n in ctrl.notes if "cancel fault" in n]
        assert len(faults) == 2
        assert any(stale_a in n for n in faults)
        assert any(stale_b in n for n in faults)
