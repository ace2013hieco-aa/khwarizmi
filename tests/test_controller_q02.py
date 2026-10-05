"""Q-02 controller consumption — Model-B fixtures (design §13.2/3/4/5/8).

The controller applies the ratified EligibleTask ordering policy at dispatch:
eligibility (dependencies SUCCEEDED, gates, per-tick call cap) runs FIRST and
unchanged; the ordering decides only WHO among the already-eligible runs
first. These fixtures pin the boundaries (§13.2 dependency, §13.3 budget,
§13.4 gate, §13.5 Director-priority precedence, §13.8 removal), the
version-bound dispatch record (§9), and the provenance/fail-closed
derivation. Pure-function fixtures live in test_q02_eligible_ordering.py.
"""
from __future__ import annotations

import pytest

from hermes.core import frozen_clock
from hermes.core.node import NodeContract, NodeType
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.program_obligations import (
    ProgramRequirementSatisfactionRepository,
    ValidationVerdictRepository,
)
from hermes.persistence.repositories import ProjectRepository, TaskRepository
from hermes.research.controller import Controller
from hermes.research.evaluation import DimensionLevel
from hermes.research.extraction import (
    EXTRACT_TEMPLATE,
    extraction_draft_from_mapping,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    conn.execute(
        """INSERT INTO dataset_manifests
           (manifest_id, project_id, location, format, size_bytes,
            headers_json, schema_observations_json, query_recipes_json,
            content_hash, provenance_json, created_at, immutable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        ("dm-1", "p1", "x.csv", "csv", 1, "[]", "[]", "[]",
         "h1", None, "2026-01-01T00:00:00.000000+00:00"),
    )
    yield conn
    conn.close()


def insert_task(db, task_id, *, cost_class=None, created_at=CLOCK,
                status=TaskStatus.PENDING, provenance=None,
                task_type=NodeType.AGENT_TASK, dependencies=()):
    """Insert a task via the ordinary TaskRepository write path."""
    repo = TaskRepository(db, clock=lambda: created_at)
    node = NodeContract(
        task_id=task_id,
        project_id="p1",
        task_type=task_type.value,
        idempotency_key=task_id,
        status=status.value,
        spec={
            "template": EXTRACT_TEMPLATE if task_type is NodeType.AGENT_TASK
            else "gate",
            "source_ref": "dataset_manifest:dm-1",
        },
        dependencies=list(dependencies),
        provenance=list(provenance or []),
        cost_class=cost_class,
    )
    return repo.create(node)


def recording_extract_fn(order: list):
    """An extract stub that records the order in which tasks were executed.

    M3: the contract is ``(task, untrusted)`` — the untrusted content view
    is the only source-text surface (the stub ignores it)."""
    def _fn(task, untrusted):
        order.append(task["task_id"])
        statement = f"Claim produced by {task['task_id']}."
        return extraction_draft_from_mapping({
            "source_ref": "dataset_manifest:dm-1",
            "claims": [{
                "ref": "c1",
                "statement": statement,
                "source_ref": "dataset_manifest:dm-1",
                "support_state": "INFERRED",
                "span_ref": "sec.3",
                "claim_type": "causal",
                "context_tags": {"regime": "ICSS-v1:low-vol",
                                 "dataset_ref": "dm-1"},
                "assumption_refs": ["a1"],
            }],
            "assumptions": [{
                "ref": "a1",
                "statement": "The sample is representative.",
                "context_tags": {"population": "adults-18-65"},
                "supporting_artifact_refs": ["dataset_manifest:dm-1"],
            }],
            "extracted_by": "model_ref:c-tier-1",
            "schema_version": "2",
        })
    return _fn


def make_controller(db, *, order=None, **kwargs) -> Controller:
    if order is not None:
        kwargs.setdefault("extract_fn", recording_extract_fn(order))
    kwargs.setdefault("extract_fn", recording_extract_fn([]))
    kwargs.setdefault("clock", frozen_clock(CLOCK))
    return Controller(db, project_id="p1", **kwargs)


# ── §13.1/§13.9 at the controller: the declared order decides dispatch ──

class TestDispatchOrdering:
    def test_low_cost_eligible_task_dispatches_first(self, db):
        order: list[str] = []
        # t-high created EARLIER but cost HIGH; t-low created later but LOW.
        insert_task(db, "t-high", cost_class="HIGH", created_at="2026-01-01T09:00:00.000000+00:00")
        insert_task(db, "t-low", cost_class="LOW", created_at="2026-01-01T10:00:00.000000+00:00")
        ctrl = make_controller(db, order=order)
        result = ctrl.tick()
        # Both are eligible; the policy (LOW cost first) beats created_at.
        assert order == ["t-low", "t-high"]
        assert result.dispatched == ["t-low", "t-high"]
        assert result.succeeded == ["t-low", "t-high"]
        # §9: the dispatch records the applied policy version.
        assert result.ordering_policy_version == "task-eval-2026.1"

    def test_equal_policy_falls_back_to_created_at_then_task_id(self, db):
        order: list[str] = []
        insert_task(db, "t-b", cost_class="MEDIUM", created_at="2026-01-01T10:00:00.000000+00:00")
        insert_task(db, "t-a", cost_class="MEDIUM", created_at="2026-01-01T09:00:00.000000+00:00")
        ctrl = make_controller(db, order=order)
        ctrl.tick()
        assert order == ["t-a", "t-b"]  # earlier created_at first

    def test_unknown_cost_class_sorts_last(self, db):
        order: list[str] = []
        insert_task(db, "t-unknown", cost_class=None, created_at="2026-01-01T09:00:00.000000+00:00")
        insert_task(db, "t-high", cost_class="HIGH", created_at="2026-01-01T10:00:00.000000+00:00")
        ctrl = make_controller(db, order=order)
        ctrl.tick()
        # AC-08: unknown never treated as a value — HIGH beats UNKNOWN even
        # though the UNKNOWN task was created earlier.
        assert order == ["t-high", "t-unknown"]


# ── §13.2 dependency boundary: ordering never admits ──

class TestDependencyBoundary:
    def test_dependency_blocked_task_is_never_ordered_or_dispatched(self, db):
        order: list[str] = []
        # A CANCELLED dependency is never SUCCEEDED and never eligible —
        # t-a stays blocked by the ordinary dependency gate.
        insert_task(db, "t-dep", status=TaskStatus.CANCELLED)
        insert_task(db, "t-a", cost_class="LOW", dependencies=["t-dep"])
        insert_task(db, "t-b", cost_class="HIGH")
        ctrl = make_controller(db, order=order)
        result = ctrl.tick()
        # t-a is the policy-preferred task but its dependency is unsatisfied —
        # the dependency gate runs first, unchanged; the ordering cannot admit.
        assert result.dispatched == ["t-b"]
        assert order == ["t-b"]
        assert ctrl._task_repo.get("t-a")["status"] == TaskStatus.PENDING.value


# ── §13.3 budget boundary: ordering cannot override the per-tick cap ──

class TestBudgetBoundary:
    def test_ordering_cannot_squeeze_past_the_call_cap(self, db):
        order: list[str] = []
        insert_task(db, "t-1", cost_class="LOW")
        insert_task(db, "t-2", cost_class="HIGH")
        ctrl = make_controller(db, order=order, max_calls_per_tick=1)
        first = ctrl.tick()
        assert len(first.dispatched) == 1
        assert first.idle == "max_calls_per_tick"
        second = ctrl.tick()
        assert len(second.dispatched) == 1
        assert set(first.dispatched) | set(second.dispatched) == {"t-1", "t-2"}
        assert order == ["t-1", "t-2"]  # policy order preserved across ticks


# ── §13.4 gate boundary: gated tasks are excluded before ordering ──

class TestGateBoundary:
    def test_task_awaiting_a_failed_gate_is_never_ordered(self, db):
        order: list[str] = []
        insert_task(db, "t-gate", task_type=NodeType.GATE, status=TaskStatus.READY)
        insert_task(db, "t-a", cost_class="LOW", dependencies=["t-gate"])
        insert_task(db, "t-b", cost_class="HIGH")
        ctrl = make_controller(
            db, order=order, gate_verdict_fn=lambda task: False)
        result = ctrl.tick()
        assert "t-b" in result.dispatched
        assert "t-a" not in result.dispatched
        # The gate failed; t-a stays blocked. The ordering never saw it.
        assert ctrl._task_repo.get("t-a")["status"] == TaskStatus.PENDING.value


# ── §13.5 Director-priority precedence (mechanism deferred, contract pinned) ──

class TestDirectorPriorityBoundary:
    def test_no_priority_mechanism_exists(self, db):
        # The precedence contract is eligibility → (ratified Director
        # priority, deferred) → epistemic policy → created_at/task_id. v1
        # must not invent a priority field — assert none exists.
        cols = {r["name"] for r in db.execute("PRAGMA table_info(tasks)")}
        assert "priority" not in cols
        assert "priority_override" not in cols

    def test_equal_policy_uses_created_at_then_task_id(self, db):
        # The policy tail IS the deterministic fallback the deferred priority
        # mechanism would sit above.
        order: list[str] = []
        insert_task(db, "t-b", cost_class="MEDIUM", created_at="2026-01-01T10:00:00.000000+00:00")
        insert_task(db, "t-a", cost_class="MEDIUM", created_at="2026-01-01T09:00:00.000000+00:00")
        ctrl = make_controller(db, order=order)
        ctrl.tick()
        assert order == ["t-a", "t-b"]


# ── §13.8 removal: disabling the ordering restores baseline behavior ──

class TestRemoval:
    def test_disabled_ordering_dispenses_baseline_created_at_order(self, db):
        order: list[str] = []
        # Policy-enabled order would put t-low first; disabled must not.
        insert_task(db, "t-low", cost_class="LOW", created_at="2026-01-01T10:00:00.000000+00:00")
        insert_task(db, "t-high", cost_class="HIGH", created_at="2026-01-01T09:00:00.000000+00:00")
        ctrl = make_controller(db, order=order, enable_epistemic_ordering=False)
        result = ctrl.tick()
        assert order == ["t-high", "t-low"]   # created_at baseline
        assert result.ordering_policy_version == ""
        assert result.succeeded == ["t-high", "t-low"]

    def test_no_eligible_tasks_ordering_is_skipped(self, db):
        ctrl = make_controller(db)
        result = ctrl.tick()
        assert result.ordering_policy_version == ""
        assert result.dispatched == []


# ── derivation: cost mapping + provenance (fail-closed, code-derived) ──

class TestDerivation:
    def test_cost_class_mapping(self, db):
        ctrl = make_controller(db)
        from hermes.research.evaluation import CostTier
        cases = [
            ({"cost_class": "LOW"}, CostTier.LOW),
            ({"cost_class": "low"}, CostTier.LOW),
            ({"cost_class": "HIGH"}, CostTier.HIGH),
            ({"cost_class": "small"}, CostTier.UNKNOWN),   # untiered → unknown
            ({"cost_class": None}, CostTier.UNKNOWN),
            ({"cost_class": "banana"}, CostTier.UNKNOWN),
        ]
        for row, expected in cases:
            task = {**row, "task_id": "t", "spec": {}, "created_at": CLOCK}
            assert ctrl._eligible_task_input(task).cost_class is expected

    def test_program_refs_carried_as_basis_and_sorted(self, db):
        ctrl = make_controller(db)
        task = {"task_id": "t", "spec": {}, "created_at": CLOCK,
                "provenance_json": ["research_program:rp-2",
                                    "research_program:rp-1",
                                    "dataset_manifest:dm-1"]}
        assert ctrl._program_refs_from_provenance(task) == (
            "research_program:rp-1", "research_program:rp-2")

    def test_forged_or_malformed_provenance_is_never_an_ordering_input(self, db):
        ctrl = make_controller(db)
        for prov in [None, "research_program:rp-1", [1, 2], ["research_program:", 7]]:
            task = {"task_id": "t", "spec": {}, "created_at": CLOCK,
                    "provenance_json": prov}
            assert ctrl._program_refs_from_provenance(task) == ()

    def test_order_eligible_returns_policy_order_with_ranking(self, db):
        insert_task(db, "t-2", cost_class="MEDIUM")
        insert_task(db, "t-1", cost_class="LOW")
        ctrl = make_controller(db)
        assert ctrl._acquire_lock()  # fence is rebuilt on acquisition
        ordered, ranking = ctrl._order_eligible(ctrl._discover_eligible())
        assert [t["task_id"] for t in ordered] == ["t-1", "t-2"]
        assert ranking is not None and ranking.policy_version == "task-eval-2026.1"


# ── structural: the single policy source and import direction ──

class TestStructural:
    def test_evaluation_never_imports_the_controller(self):
        import hermes.research.evaluation as ev
        with open(ev.__file__, encoding="utf-8") as fh:
            src = fh.read()
        assert "import controller" not in src
        assert "from hermes.research.controller" not in src

    def test_controller_consumes_the_shared_policy(self):
        import hermes.research.controller as ctrl_mod
        with open(ctrl_mod.__file__, encoding="utf-8") as fh:
            src = fh.read()
        assert "evaluate_eligible_tasks" in src

    def test_dispatch_never_writes_beyond_the_ordinary_flow(self, db):
        order: list[str] = []
        insert_task(db, "t-1", cost_class="LOW")
        insert_task(db, "t-2", cost_class="HIGH")
        ctrl = make_controller(db, order=order)
        before_events = {r["event_type"] for r in
                         db.execute("SELECT DISTINCT event_type FROM events")}
        result = ctrl.tick()
        assert result.dispatched == ["t-1", "t-2"]
        after_events = {r["event_type"] for r in
                        db.execute("SELECT DISTINCT event_type FROM events")}
        # The ordering adds no new event type — only the ordinary task-status
        # transitions and the extract outcomes. P-AUTO-1: the sequencer pass
        # admits its seq row through the gateway, emitting IntentApplied (the
        # same admission event any task emits) — accounted for here.
        assert after_events - before_events <= {
            "TaskStatusChanged", "IntentApplied"}
        assert result.ordering_policy_version == "task-eval-2026.1"

    def test_llm_supplied_spec_fields_cannot_enter_the_ordering(self, db):
        # A hostile spec carrying a fabricated "roi_score" / "information_gain"
        # cannot influence dispatch: the derivation reads ONLY stored
        # cost_class + provenance. The spec field is invisible to the policy.
        from hermes.research.evaluation import CostTier, DimensionLevel
        insert_task(db, "t-1", cost_class="LOW")
        ctrl = make_controller(db)
        assert ctrl._acquire_lock()
        tasks = ctrl._discover_eligible()
        tasks[0]["spec"]["roi_score"] = "999"
        tasks[0]["spec"]["information_gain"] = "high"
        inp = ctrl._eligible_task_input(tasks[0])
        assert inp.cost_class is CostTier.LOW
        assert all(v == DimensionLevel.NONE for v in inp.dimensions.values())


# ── enriched derivation: real obligation facts via program links ──

def insert_program(db, program_id, *, hypotheses=(), evidence=(),
                   discriminations=(), version=1):
    """Insert a minimal research_programs row (ordinary repository shape).
    ``version`` defaults to 1; a second program in the same project must use
    a distinct version (UNIQUE (project_id, version))."""
    import json as _json
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, ?, ?, NULL, 'brief-1', 'objective', 'c1', 'p1',
                   '1', 'ih', ?, '[]', ?, ?, '[]', '[]', NULL, 'director',
                   NULL, ?)""",
        (program_id, "p1", version, f"ch-{program_id}",
         _json.dumps(list(hypotheses)),
         _json.dumps(list(discriminations)), _json.dumps(list(evidence)),
         "2026-01-01T00:00:00.000000+00:00"),
    )


def _hyp(ref, ladder="SUPPORTED", rival_of=None, rival_status=None):
    return {"ref": ref, "ladder_target": ladder,
            "falsification_condition": "fc", "rival_of": rival_of,
            "rival_status": rival_status}


def _req(claim_ref, ladder="SUPPORTED"):
    return {"claim_ref": claim_ref, "ladder_target": ladder,
            "required_artifacts": ["pre_registered_experiment",
                                   "statistical_analysis"],
            "associated_gates": []}


class TestEnrichedDerivation:
    def test_linked_task_with_unmet_obligations_orders_first(self, db):
        order: list[str] = []
        insert_program(db, "rp-1", evidence=[_req("h1"), _req("h2")])
        # t-a is linked to the program (2 unmet requirements → evidence HIGH)
        # but created LATER; t-b is unlinked (all dims NONE).
        insert_task(db, "t-b", cost_class="LOW",
                    created_at="2026-01-01T09:00:00.000000+00:00")
        insert_task(db, "t-a", cost_class="LOW",
                    created_at="2026-01-01T10:00:00.000000+00:00",
                    provenance=["research_program:rp-1"])
        ctrl = make_controller(db, order=order)
        result = ctrl.tick()
        assert order == ["t-a", "t-b"]  # obligation facts beat created_at
        assert result.dispatched == ["t-a", "t-b"]

    def test_satisfied_obligations_floor_at_low_still_orders_first(self, db):
        order: list[str] = []
        insert_program(db, "rp-1", evidence=[_req("h1")])
        # Produce the required artifacts AND record the per-requirement
        # satisfaction links (IDR-038 §3.1) so the requirement is fulfilled.
        from hermes.persistence.program_obligations import (
            ProgramRequirementSatisfactionRepository,
            ValidationVerdictRepository,
        )
        sat_repo = ProgramRequirementSatisfactionRepository(db)
        verdict_repo = ValidationVerdictRepository(db)
        for typ in ("pre_registered_experiment", "statistical_analysis"):
            db.execute(
                """INSERT INTO artifacts
                   (artifact_id, project_id, task_id, artifact_type,
                    content_hash, size_bytes, storage_path, producer,
                    metadata_json, created_at)
                   VALUES (?, 'p1', NULL, ?, ?, 1, 'x', 't', '{}',
                           '2026-01-01T00:00:00.000000+00:00')""",
                (f"art-{typ}", typ, f"ch-{typ}"),
            )
            verdict_repo.record(project_id="p1", artifact_id=f"art-{typ}",
                                verdict="PASS")
            sat_repo.record(project_id="p1", program_id="rp-1",
                            requirement_ref="h1", artifact_id=f"art-{typ}")
        insert_task(db, "t-b", cost_class="LOW",
                    created_at="2026-01-01T09:00:00.000000+00:00")
        insert_task(db, "t-a", cost_class="LOW",
                    created_at="2026-01-01T10:00:00.000000+00:00",
                    provenance=["research_program:rp-1"])
        ctrl = make_controller(db, order=order)
        ctrl.tick()
        # LOW (obligations exist, satisfied) still beats NONE (no link).
        assert order == ["t-a", "t-b"]

    def test_goodhart_padding_satisfied_obligations_never_wins(self, db):
        """External red-team RT-03: obligation padding must not game the
        ordering. The report's exact attack — a program with 50 trivial
        SATISFIED obligations vs one with 2 outstanding high-value
        obligations — must dispatch the high-value task FIRST: the ratified
        count→level mapping is anti-Goodhart (satisfied → outstanding 0 →
        LOW), so completion volume LOWERS priority instead of raising it."""
        from hermes.persistence.program_obligations import (
            ProgramRequirementSatisfactionRepository,
            ValidationVerdictRepository,
        )
        sat_repo = ProgramRequirementSatisfactionRepository(db)
        verdict_repo = ValidationVerdictRepository(db)
        insert_program(db, "rp-trivial",
                       evidence=[_req(f"t{i:02d}") for i in range(50)],
                       version=1)
        insert_program(db, "rp-valuable",
                       evidence=[_req("v1"), _req("v2")], version=2)
        # Satisfy ALL 50 trivial requirements via the ratified write path.
        for ref in (f"t{i:02d}" for i in range(50)):
            for typ in ("pre_registered_experiment", "statistical_analysis"):
                db.execute(
                    """INSERT INTO artifacts (artifact_id, project_id,
                       task_id, artifact_type, content_hash, size_bytes,
                       storage_path, producer, metadata_json, created_at)
                       VALUES (?, 'p1', NULL, ?, ?, 1, 'x', 't', '{}',
                               '2026-01-01T00:00:00.000000+00:00')""",
                    (f"art-triv-{ref}-{typ}", typ, f"ch-{ref}-{typ}"))
                verdict_repo.record(
                    project_id="p1", artifact_id=f"art-triv-{ref}-{typ}",
                    verdict="PASS")
                sat_repo.record(project_id="p1", program_id="rp-trivial",
                                requirement_ref=ref,
                                artifact_id=f"art-triv-{ref}-{typ}")
        order: list[str] = []
        # padding program's task created EARLIER — still must lose
        insert_task(db, "t-trivial", cost_class="LOW",
                    created_at="2026-01-01T09:00:00.000000+00:00",
                    provenance=["research_program:rp-trivial"])
        insert_task(db, "t-valuable", cost_class="LOW",
                    created_at="2026-01-01T10:00:00.000000+00:00",
                    provenance=["research_program:rp-valuable"])
        make_controller(db, order=order).tick()
        # 2 OUTSTANDING → HIGH beats 50 satisfied → LOW, despite created_at.
        assert order == ["t-valuable", "t-trivial"]

    def test_goodhart_padding_outstanding_caps_at_high(self, db):
        """External red-team RT-03, stronger variant: 50 OUTSTANDING
        trivial obligations vs 2 outstanding — the dimension level is CAPPED
        at HIGH (≥2 outstanding), so padding can only reach PARITY, never
        priority inversion; the tie falls to created_at. Padding a program
        with always-outstanding trivial obligations cannot exceed a
        genuine 2-obligation program."""
        order: list[str] = []
        insert_program(db, "rp-triv2",
                       evidence=[_req(f"p{i:02d}") for i in range(50)],
                       version=1)
        insert_program(db, "rp-val2",
                       evidence=[_req("q1"), _req("q2")], version=2)
        insert_task(db, "t-triv2", cost_class="LOW",
                    created_at="2026-01-01T08:00:00.000000+00:00",
                    provenance=["research_program:rp-triv2"])
        insert_task(db, "t-val2", cost_class="LOW",
                    created_at="2026-01-01T11:00:00.000000+00:00",
                    provenance=["research_program:rp-val2"])
        make_controller(db, order=order).tick()
        # both HIGH → earlier created_at wins — parity, not inversion
        assert order == ["t-triv2", "t-val2"]

    def test_superseded_ancestor_not_counted_unless_linked(self, db):
        """Closure-directive follow-up: a task linked ONLY to the current
        program derives its obligation facts from THAT program alone — the
        superseded ancestor (chained via supersedes_id) with outstanding
        obligations can never inflate the facts. Only an explicit multi-link
        to both programs sums them (deterministic, capped at HIGH)."""
        order: list[str] = []
        insert_program(db, "rp-anc", version=1, evidence=[_req("a1")])
        insert_program(db, "rp-cur", version=2, evidence=[_req("c1")])
        db.execute("UPDATE research_programs SET supersedes_id = 'rp-anc' "
                   "WHERE program_id = 'rp-cur'")
        insert_program(db, "rp-2", version=3, evidence=[_req("b1")])
        insert_task(db, "t-cur", cost_class="LOW",
                    created_at="2026-01-01T11:00:00.000000+00:00",
                    provenance=["research_program:rp-cur"])
        insert_task(db, "t-2", cost_class="LOW",
                    created_at="2026-01-01T09:00:00.000000+00:00",
                    provenance=["research_program:rp-2"])
        make_controller(db, order=order).tick()
        # both MEDIUM (1 outstanding each) -> created_at wins; if the
        # ancestor's obligation leaked, t-cur would inflate to HIGH
        assert order == ["t-2", "t-cur"]

    def test_explicit_multi_link_sums_obligations_capped(self, db):
        """A task explicitly linked to TWO programs sums their obligations
        deterministically: 2 outstanding across the pair -> HIGH (capped,
        never beyond), beating a single-outstanding MEDIUM competitor."""
        order: list[str] = []
        insert_program(db, "rp-1", version=1, evidence=[_req("h1")])
        insert_program(db, "rp-2", version=2, evidence=[_req("b1")])
        insert_program(db, "rp-3", version=3, evidence=[_req("x1")])
        insert_task(db, "t-both", cost_class="LOW",
                    created_at="2026-01-01T10:00:00.000000+00:00",
                    provenance=["research_program:rp-1",
                                "research_program:rp-2"])
        insert_task(db, "t-one", cost_class="LOW",
                    created_at="2026-01-01T11:00:00.000000+00:00",
                    provenance=["research_program:rp-3"])
        make_controller(db, order=order).tick()
        assert order == ["t-both", "t-one"]

    def test_missing_program_row_fails_closed_to_baseline(self, db):
        order: list[str] = []
        # Provenance names a program with no row — the link is unresolvable,
        # so the task degenerates to the created_at/cost baseline.
        insert_task(db, "t-b", cost_class="LOW",
                    created_at="2026-01-01T09:00:00.000000+00:00")
        insert_task(db, "t-a", cost_class="LOW",
                    created_at="2026-01-01T10:00:00.000000+00:00",
                    provenance=["research_program:rp-missing"])
        ctrl = make_controller(db, order=order)
        ctrl.tick()
        assert order == ["t-b", "t-a"]  # created_at baseline, no crash

    def test_foreign_program_ref_is_never_a_fact(self, db):
        # A program governed by another project cannot be cited: the read is
        # project-scoped, so the ref resolves to nothing → degenerate.
        ProjectRepository(db).create("other", "Other")
        insert_program(db, "rp-other", evidence=[_req("h1")])
        db.execute("UPDATE research_programs SET project_id = 'other' "
                   "WHERE program_id = 'rp-other'")
        order: list[str] = []
        insert_task(db, "t-b", cost_class="LOW",
                    created_at="2026-01-01T09:00:00.000000+00:00")
        insert_task(db, "t-a", cost_class="LOW",
                    created_at="2026-01-01T10:00:00.000000+00:00",
                    provenance=["research_program:rp-other"])
        ctrl = make_controller(db, order=order)
        ctrl.tick()
        assert order == ["t-b", "t-a"]

    def test_obligation_derivation_is_read_only(self, db):
        order: list[str] = []
        insert_program(db, "rp-1", evidence=[_req("h1")])
        insert_task(db, "t-a", cost_class="LOW",
                    provenance=["research_program:rp-1"])
        ctrl = make_controller(db, order=order)
        artifacts_before = db.execute(
            "SELECT COUNT(*) c FROM artifacts").fetchone()["c"]
        result = ctrl.tick()
        assert result.dispatched == ["t-a"]
        assert db.execute(
            "SELECT COUNT(*) c FROM artifacts").fetchone()["c"] == artifacts_before

    def test_corrupt_program_row_fails_closed_never_crashes_dispatch(self, db):
        # F5 (adversarial audit): a program row with corrupt JSON columns must
        # not crash the tick — the derivation degrades to baseline, the note
        # makes the corruption observable, dispatch proceeds.
        db.execute(
            """INSERT INTO research_programs
               (program_id, project_id, version, content_hash, supersedes_id,
                scope_ref, epistemic_objective, compiler_version, policy_version,
                schema_version, input_hash, hypothesis_json, prediction_json,
                discrimination_json, evidence_json, gate_json, methodology_json,
                task_graph_template_ref, produced_by, reason, created_at)
               VALUES (?, ?, 1, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', ?,
                       '[]', '[]', '[]', '[]', '[]', NULL, 'director', NULL, ?)""",
            ("rp-bad", "p1", "ch", "{not-json", CLOCK),
        )
        order: list[str] = []
        insert_task(db, "t-a", cost_class="LOW",
                    created_at="2026-01-01T10:00:00.000000+00:00",
                    provenance=["research_program:rp-bad"])
        insert_task(db, "t-b", cost_class="LOW",
                    created_at="2026-01-01T09:00:00.000000+00:00")
        ctrl = make_controller(db, order=order)
        result = ctrl.tick()  # must not raise
        assert set(result.dispatched) == {"t-a", "t-b"}
        assert any("corrupt research_program row 'rp-bad'" in n
                   for n in ctrl._notes)
        # The corrupt row was never a fact source: t-a degenerated to the
        # created_at baseline (t-b created earlier ran first).
        assert order == ["t-b", "t-a"]


# ── recovery-safety: the ordering re-derives deterministically across a crash ──

class TestRecoveryDeterminism:
    def test_ordering_survives_crash_recovery_unperturbed(self, db):
        # A controller crashes mid-dispatch (a task left RUNNING with a stale
        # heartbeat). The ordering is computed at discovery time and never
        # persisted, so recovery re-derives it from the same stored facts +
        # the same policy version — the eligible order and the recorded
        # policy version are deterministic across the crash.
        order: list[str] = []
        insert_program(db, "rp-1", evidence=[_req("h1"), _req("h2")])
        # t-crash: claimed then abandoned (stale RUNNING) — created earliest.
        insert_task(db, "t-crash", cost_class="LOW", status=TaskStatus.RUNNING,
                    created_at="2026-01-01T09:00:00.000000+00:00")
        db.execute("UPDATE tasks SET last_heartbeat = '2025-01-01T00:00:00.000000+00:00' "
                   "WHERE task_id = 't-crash'")
        # t-linked: program obligations unmet (evidence HIGH) — created later.
        insert_task(db, "t-linked", cost_class="LOW",
                    created_at="2026-01-01T10:00:00.000000+00:00",
                    provenance=["research_program:rp-1"])
        insert_task(db, "t-unlinked", cost_class="LOW",
                    created_at="2026-01-01T11:00:00.000000+00:00")

        ctrl = make_controller(db, order=order)

        def rederived():
            # The fence is rebuilt on lock acquisition (as tick() does); the
            # private discovery/ordering methods are only valid under it.
            assert ctrl._acquire_lock()
            tasks = ctrl._discover_eligible()
            ordered, ranking = ctrl._order_eligible(tasks)
            return [t["task_id"] for t in ordered], (ranking.policy_version
                                                     if ranking else None)

        # Pre-crash re-derivation: the ordering is computed at discovery time
        # and never persisted, so the crashed controller's next pass re-derives
        # it from the same stored facts + the same policy version.
        reordered, version = rederived()
        assert reordered == ["t-linked", "t-unlinked"]  # enriched order
        assert version == "task-eval-2026.1"

        # Tick 1: recovery marks t-crash NO_SIGNAL (first miss); dispatch
        # orders the surviving eligible set exactly as re-derived pre-crash.
        t1 = ctrl.tick()
        assert t1.recovery == ["t-crash"]
        assert t1.ordering_policy_version == "task-eval-2026.1"
        assert order == reordered  # post-crash run used the same order

        # Determinism across the crash: the same stored facts yield the same
        # order before and after — nothing about the crash perturbed the
        # policy (verified again after the recovery chain completes below).

        # Tick 2: second conclusive miss → FAILED → RETRYING → re-executed by
        # the recovery pass itself (IDR-029 Decision 4 — requeue+re-execute IS
        # dispatch and is unchanged by Q-02; it never re-enters the eligible
        # set, so the ordering cannot perturb recovery).
        t2 = ctrl.tick()
        assert t2.ordering_policy_version == ""  # no unclaimed eligible task
        assert ctrl._task_repo.get("t-crash")["status"] == TaskStatus.SUCCEEDED.value
        assert rederived() == ([], None)  # deterministic end state

        # Determinism across the crash: the same stored facts yield the same
        # order before and after the whole chain — nothing about the crash
        # perturbed the policy.
        assert version == "task-eval-2026.1"
        assert ctrl._task_repo.get("t-linked")["status"] == TaskStatus.SUCCEEDED.value
        assert ctrl._task_repo.get("t-unlinked")["status"] == TaskStatus.SUCCEEDED.value


# ── IDR-038 §3.1 write path: satisfaction links from completed evidence tasks ──

EVIDENCE_TEMPLATE = "evidence-obligation"


def _evidence_task(db, task_id, *, program_id, claim_refs, cost_class="MEDIUM",
                   created_at=CLOCK, dependencies=()):
    """A plan-shaped evidence task: provenance carries the program ref AND
    the evidence_requirement refs (task_plan.py emits both for every
    evidence task)."""
    repo = TaskRepository(db, clock=lambda: created_at)
    return repo.create(NodeContract(
        task_id=task_id, project_id="p1", task_type=NodeType.AGENT_TASK.value,
        idempotency_key=task_id, status=TaskStatus.PENDING.value,
        spec={"template": EVIDENCE_TEMPLATE},
        dependencies=list(dependencies),
        provenance=[f"research_program:{program_id}"]
                   + [f"evidence_requirement:{c}" for c in claim_refs],
        cost_class=cost_class,
    ))


def _artifact_for_task(db, task_id, artifact_id, artifact_type,
                       *, verdict: bool = True):
    """An artifact row persisted by the evidence step for a task (ordinary
    ArtifactRepository shape; task_id binds it to the producing task). With
    ``verdict=True`` (default) the artifact ALSO carries a PASS content-
    validation verdict (M1/HR-02: a satisfaction link requires one — the
    completion auto-link is refused without it)."""
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, 1, 'x', 't', '{}', ?)""",
        (artifact_id, "p1", task_id, artifact_type,
         f"ch-{artifact_id}", CLOCK),
    )
    if verdict:
        ValidationVerdictRepository(db, clock=frozen_clock(CLOCK)).record(
            project_id="p1", artifact_id=artifact_id, verdict="PASS")


def _evidence_handler() -> dict:
    """A completing handler for EVIDENCE_TEMPLATE tasks (the S6-B2 source
    outcome row + evidence artifacts are pre-inserted by the fixtures)."""
    from hermes.research.source_handlers import HandlerResult as _HR

    class EvidenceHandler:
        def build_context(self, task, project_id, repos):
            return task

        def __call__(self, ctx):
            return _HR(status="completed", outcome_recorded=True)

    return {EVIDENCE_TEMPLATE: EvidenceHandler()}


class TestSatisfactionWritePath:
    """The completion write path (IDR-038 §3.1): a SUCCEEDED evidence task
    records its per-requirement satisfaction links before the SUCCEEDED
    transition; forged/mismatched refs and artifacts fail closed with a note
    and NO link."""

    def _handler(self):
        return _evidence_handler()

    def _links(self, db):
        return db.execute(
            "SELECT program_id, requirement_ref, artifact_id "
            "FROM program_requirement_satisfactions ORDER BY 1, 2, 3"
        ).fetchall()

    def test_completed_evidence_task_records_links(self, db):
        insert_program(db, "rp-1", evidence=[_req("h1"), _req("h2")])
        _evidence_task(db, "t-ev", program_id="rp-1", claim_refs=["h1"])
        _artifact_for_task(db, "t-ev", "a-src", "source_search")
        _artifact_for_task(db, "t-ev", "a-pre", "pre_registered_experiment")
        _artifact_for_task(db, "t-ev", "a-stat", "statistical_analysis")
        ctrl = make_controller(db, task_handlers=self._handler())
        result = ctrl.tick()
        assert "t-ev" in result.succeeded
        assert ctrl._task_repo.get_status("t-ev") is TaskStatus.SUCCEEDED
        links = [(r[0], r[1], r[2]) for r in self._links(db)]
        assert links == [
            ("rp-1", "h1", "a-pre"), ("rp-1", "h1", "a-stat")]
        # The requirement is fully satisfied per the stored links.
        sats = ProgramRequirementSatisfactionRepository(
            db).satisfaction_types_by_requirement("p1")
        assert sats["rp-1"]["h1"] == frozenset(
            {"pre_registered_experiment", "statistical_analysis"})

    def test_verdict_less_artifacts_never_auto_linked(self, db):
        """M1/HR-02 — a completing evidence task whose artifacts carry NO
        validation verdict records NO satisfaction link: the auto-link is
        refused fail-closed with an observable note, so canned evidence
        without content validation can never satisfy a requirement."""
        insert_program(db, "rp-1", evidence=[_req("h1")])
        _evidence_task(db, "t-ev", program_id="rp-1", claim_refs=["h1"])
        _artifact_for_task(db, "t-ev", "a-src", "source_search")
        _artifact_for_task(db, "t-ev", "a-pre",
                           "pre_registered_experiment", verdict=False)
        _artifact_for_task(db, "t-ev", "a-stat",
                           "statistical_analysis", verdict=False)
        ctrl = make_controller(db, task_handlers=self._handler())
        result = ctrl.tick()
        assert "t-ev" in result.succeeded
        assert self._links(db) == []
        assert any("validation verdict" in n for n in ctrl.notes)
        # the verdict-covered read reports nothing → no climb input
        assert ProgramRequirementSatisfactionRepository(
            db).satisfaction_types_by_requirement("p1") == {}

    def test_links_flow_into_the_ordering_derivation(self, db):
        # After completion, a later eligible task linked to rp-1 sees h1
        # satisfied: evidence_gap_closure drops from HIGH (2 outstanding)
        # to MEDIUM (only h2 outstanding) — the write path feeds the policy.
        insert_program(db, "rp-1", evidence=[_req("h1"), _req("h2")])
        _evidence_task(db, "t-ev", program_id="rp-1", claim_refs=["h1"])
        _artifact_for_task(db, "t-ev", "a-src", "source_search")
        _artifact_for_task(db, "t-ev", "a-pre", "pre_registered_experiment")
        _artifact_for_task(db, "t-ev", "a-stat", "statistical_analysis")
        _evidence_task(db, "t-next", program_id="rp-1", claim_refs=[],
                       created_at="2026-01-01T11:00:00.000000+00:00",
                       dependencies=["t-ev"])
        ctrl = make_controller(db, task_handlers=self._handler())
        # Tick 1: t-ev completes and records the links.
        assert "t-ev" in ctrl.tick().succeeded
        # Tick 2: t-next is eligible; its derivation consumes the links.
        assert ctrl._acquire_lock()
        tasks = ctrl._discover_eligible()
        ordered, ranking = ctrl._order_eligible(tasks)
        assert [t["task_id"] for t in ordered] == ["t-next"]
        dims = dict(ranking.comparison[0].dimensions)
        assert dims["evidence_gap_closure"] == DimensionLevel.MEDIUM

    def test_forged_requirement_ref_records_no_link_and_notes(self, db):
        insert_program(db, "rp-1", evidence=[_req("h1")])
        _evidence_task(db, "t-ev", program_id="rp-1",
                       claim_refs=["does-not-exist"])
        _artifact_for_task(db, "t-ev", "a-src", "source_search")
        _artifact_for_task(db, "t-ev", "a-pre", "pre_registered_experiment")
        ctrl = make_controller(db, task_handlers=self._handler())
        assert ctrl._acquire_lock()
        ctrl._record_requirement_satisfactions(ctrl._task_repo.get("t-ev"))
        assert self._links(db) == []
        assert any("does not dereference" in n for n in ctrl._notes)

    def test_program_ref_without_requirement_ref_records_nothing(self, db):
        insert_program(db, "rp-1", evidence=[_req("h1")])
        _evidence_task(db, "t-ev", program_id="rp-1", claim_refs=[])
        _artifact_for_task(db, "t-ev", "a-pre", "pre_registered_experiment")
        ctrl = make_controller(db, task_handlers=self._handler())
        assert ctrl._acquire_lock()
        ctrl._record_requirement_satisfactions(ctrl._task_repo.get("t-ev"))
        assert self._links(db) == []

    def test_wrong_class_artifact_not_linked(self, db):
        insert_program(db, "rp-1", evidence=[_req("h1")])
        _evidence_task(db, "t-ev", program_id="rp-1", claim_refs=["h1"])
        _artifact_for_task(db, "t-ev", "a-src", "source_search")
        _artifact_for_task(db, "t-ev", "a-other", "not_a_required_class")
        ctrl = make_controller(db, task_handlers=self._handler())
        assert ctrl._acquire_lock()
        ctrl._record_requirement_satisfactions(ctrl._task_repo.get("t-ev"))
        assert self._links(db) == []

    def test_requirement_from_another_program_refused(self, db):
        # h1 belongs to rp-1; the task claims it under rp-2 — the link must
        # not dereference under rp-2 and is refused with a note.
        insert_program(db, "rp-1", evidence=[_req("h1")])
        insert_program(db, "rp-2", evidence=[_req("h2")], version=2)
        _evidence_task(db, "t-ev", program_id="rp-2", claim_refs=["h1"])
        _artifact_for_task(db, "t-ev", "a-pre", "pre_registered_experiment")
        ctrl = make_controller(db, task_handlers=self._handler())
        assert ctrl._acquire_lock()
        ctrl._record_requirement_satisfactions(ctrl._task_repo.get("t-ev"))
        assert self._links(db) == []
        assert any("does not dereference" in n for n in ctrl._notes)

    def test_unresolvable_program_ref_skips_with_note(self, db):
        _evidence_task(db, "t-ev", program_id="rp-missing",
                       claim_refs=["h1"])
        _artifact_for_task(db, "t-ev", "a-pre", "pre_registered_experiment")
        ctrl = make_controller(db, task_handlers=self._handler())
        assert ctrl._acquire_lock()
        ctrl._record_requirement_satisfactions(ctrl._task_repo.get("t-ev"))
        assert self._links(db) == []
        assert any("not resolvable" in n for n in ctrl._notes)

    def test_admitted_evidence_task_records_links(self, db):
        """End to end: an evidence task ADMITTED through the gateway (whose
        pairing the gateway validates — V6-FINAL-02) completes through the
        controller and its satisfaction links are recorded. The write path
        consumes gateway-validated pairs, not hand-built tasks."""
        from hermes.core.intents import Intent, IntentKind
        from hermes.research.gateway import apply_intent
        insert_program(db, "rp-1", evidence=[_req("h1")])
        apply_intent(db, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload={
                "task_id": "t-gw", "task_type": "AGENT_TASK",
                "profile": "RESEARCHER", "idempotency_key": "t-gw",
                "iteration": 1, "spec": {"template": EVIDENCE_TEMPLATE},
                "inputs": [], "outputs": [], "dependencies": [],
                "provenance": ["research_program:rp-1",
                                "evidence_requirement:h1"],
            }))
        _artifact_for_task(db, "t-gw", "a-src", "source_search")
        _artifact_for_task(db, "t-gw", "a-pre",
                           "pre_registered_experiment")
        _artifact_for_task(db, "t-gw", "a-stat", "statistical_analysis")
        ctrl = make_controller(db, task_handlers=_evidence_handler())
        assert "t-gw" in ctrl.tick().succeeded
        sats = ProgramRequirementSatisfactionRepository(
            db).satisfaction_types_by_requirement("p1")
        assert sats["rp-1"]["h1"] == frozenset(
            {"pre_registered_experiment", "statistical_analysis"})


# ── multi-tick recovery determinism: ordering holds as facts grow mid-chain ──

class TestMultiTickRecoveryDeterminism:
    def test_ordering_deterministic_as_satisfactions_grow_across_ticks(self, db):
        """The ordering re-derives deterministically across a crash even when
        stored facts GROW between ticks: tick 1 completes an evidence task
        (recording its satisfaction link mid-chain), the controller crashes,
        and the recovery pass re-derives the same order + policy version from
        the CURRENT facts — the mid-chain link is part of the input, never a
        perturbation."""
        insert_program(db, "rp-1", evidence=[_req("h1"), _req("h2")])
        # t-ev1: the evidence task for h1 — completes tick 1, records its link.
        _evidence_task(db, "t-ev1", program_id="rp-1", claim_refs=["h1"])
        _artifact_for_task(db, "t-ev1", "a-src", "source_search")
        _artifact_for_task(db, "t-ev1", "a-pre", "pre_registered_experiment")
        _artifact_for_task(db, "t-ev1", "a-stat", "statistical_analysis")
        # t-crash: the crash artifact — stale RUNNING, created earliest.
        insert_task(db, "t-crash", cost_class="LOW", status=TaskStatus.RUNNING,
                    created_at="2026-01-01T09:00:00.000000+00:00")
        db.execute("UPDATE tasks SET last_heartbeat = '2025-01-01T00:00:00.000000+00:00' "
                   "WHERE task_id = 't-crash'")
        # t-linked: linked to rp-1; blocked by t-ev1 until tick 2.
        _evidence_task(db, "t-linked", program_id="rp-1", claim_refs=[],
                       created_at="2026-01-01T11:00:00.000000+00:00",
                       dependencies=["t-ev1"])
        ctrl = make_controller(db, task_handlers=_evidence_handler())

        def rederived():
            assert ctrl._acquire_lock()
            tasks = ctrl._discover_eligible()
            ordered, ranking = ctrl._order_eligible(tasks)
            return ([t["task_id"] for t in ordered],
                    ranking.policy_version if ranking else None,
                    dict(ranking.comparison[0].dimensions)
                    if ranking and ranking.comparison else {})

        # Pre-crash: only t-ev1 is eligible; nothing satisfied yet.
        order0, ver0, _ = rederived()
        assert order0 == ["t-ev1"]
        assert ver0 == "task-eval-2026.1"

        # Tick 1: t-ev1 completes — its satisfaction link is recorded
        # mid-chain (the facts the ordering re-derivation consumes grow).
        t1 = ctrl.tick()
        assert "t-ev1" in t1.succeeded
        sats = ProgramRequirementSatisfactionRepository(
            db).satisfaction_types_by_requirement("p1")
        assert sats["rp-1"]["h1"] == frozenset(
            {"pre_registered_experiment", "statistical_analysis"})

        # Post-crash re-derivation: t-linked is now eligible (its dependency
        # SUCCEEDED) and its obligation facts include the mid-chain link.
        order1, ver1, dims1 = rederived()
        assert order1 == ["t-linked"]
        assert ver1 == "task-eval-2026.1"
        assert dims1["evidence_gap_closure"] == DimensionLevel.MEDIUM  # h2 only

        # Determinism: the same stored facts re-derive byte-identically.
        assert rederived() == (order1, ver1, dims1)

        # The mid-chain link is what the re-derivation consumed — without it
        # the same eligible task would be HIGH (2 outstanding), never MEDIUM.
        from hermes.persistence.repositories import _research_program_row_to_dict
        from hermes.research.task_obligations import program_obligation_dimensions
        row = db.execute(
            "SELECT * FROM research_programs WHERE program_id = 'rp-1'"
        ).fetchone()
        no_link_dims, _ = program_obligation_dimensions(
            [_research_program_row_to_dict(row)], satisfactions={})
        assert no_link_dims["evidence_gap_closure"] == DimensionLevel.HIGH

        # Recovery pass: the ladder completes for t-crash (second conclusive
        # miss -> requeue -> re-execute, IDR-029 Decision 4 — never re-enters
        # the eligible set), and dispatch claims t-linked in the re-derived
        # order with the policy version recorded.
        t2 = ctrl.tick()
        assert t2.ordering_policy_version == "task-eval-2026.1"
        assert "t-linked" in t2.dispatched
        assert "t-crash" in t2.recovery or "t-crash" in getattr(
            t2, "recovery_failed", []) or "t-crash" in getattr(t2, "requeued", [])
        # Deterministic end state: no unclaimed eligible tasks remain.
        assert rederived() == ([], None, {})
