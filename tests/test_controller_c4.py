"""C4 exploration floor — controller consumption (ratified design gate §5.2).

The controller applies the floor-aware ordering at dispatch when enabled,
persists every floor grant / F-C transition as an append-only
``FloorGrantRecorded`` event (the durable substrate — the ranking itself is
transient), and re-derives the F-C stagnation counter from those events +
the satisfaction links. These fixtures pin the consumption boundaries:
default-OFF (Delta=0), monopoly fire + event persistence, fail-closed
capacity rejection (AC-3), and the F-C decay / kill-switch transitions.

Pure-function fixtures live in test_c4_exploration_floor.py.
"""
from __future__ import annotations

import json

import pytest

from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.evaluation import FloorPolicy, FloorStagnationMode
from tests.test_controller_q02 import (
    insert_program,
    insert_task,
    make_controller,
)


@pytest.fixture
def db():
    """The Q-02 controller fixture shape (project p1 + dataset manifest
    dm-1), defined locally — this repo's convention is per-module fixtures
    (no cross-module fixture imports)."""
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


def _floor_events(db):
    return db.execute(
        "SELECT event_id, task_id, correlation_id, payload_json "
        "FROM events WHERE event_type = 'FloorGrantRecorded' "
        "ORDER BY event_id").fetchall()


def _seed_floor_grant(db, trajectory, round_index, sat, *, task_ref="t-n",
                      outstanding=(), event_id=None):
    """Seed a prior ``FloorGrantRecorded`` grant (the F-C history the
    controller re-derives). Mirrors the controller's payload shape."""
    payload = {
        "kind": "FLOOR_GRANTED",
        "trajectory": trajectory,
        "round_index": round_index,
        "task_ref": task_ref,
        "slot": 1,
        "counter_after": 0,
        "satisfaction_count": sat,
        "outstanding_obligations": list(outstanding),
    }
    db.execute(
        """INSERT INTO events
           (event_type, project_id, task_id, from_state, to_state,
            correlation_id, caused_by, reason, artifact_ids_json,
            payload_json, created_at)
           VALUES ('FloorGrantRecorded', 'p1', ?, NULL, NULL, '',
                   'controller', 'seeded floor history', '[]', ?, ?)""",
        (task_ref, json.dumps(payload),
         f"2026-01-01T00:00:{round_index:02d}.000000+00:00"),
    )


def _monopoly_setup(db):
    """Two leading-trajectory tasks (rp-A) + one non-leader (rp-B), all
    LOW cost / no dimensions so pure policy orders by created_at."""
    insert_program(db, "rp-A", version=1)
    insert_program(db, "rp-B", version=2)
    insert_task(db, "t-l1", cost_class="LOW",
                created_at="2026-01-01T01:00:00.000000+00:00",
                provenance=["research_program:rp-A"])
    insert_task(db, "t-l2", cost_class="LOW",
                created_at="2026-01-01T02:00:00.000000+00:00",
                provenance=["research_program:rp-A"])
    insert_task(db, "t-n", cost_class="LOW",
                created_at="2026-01-01T03:00:00.000000+00:00",
                provenance=["research_program:rp-B"])


# ── Delta=0: the floor is OFF by default ──

class TestDefaultOff:
    def test_floor_disabled_by_default_pure_policy_stands(self, db):
        order: list[str] = []
        _monopoly_setup(db)
        ctrl = make_controller(db, order=order, max_calls_per_tick=2)
        result = ctrl.tick()
        # Pure policy: created_at order — the leader's tasks run first.
        assert order == ["t-l1", "t-l2"]
        assert result.ordering_policy_version == "task-eval-2026.1"
        # No floor event is recorded when the floor is off.
        assert _floor_events(db) == []

    def test_floor_disabled_when_epistemic_ordering_off(self, db):
        order: list[str] = []
        _monopoly_setup(db)
        ctrl = make_controller(db, order=order, max_calls_per_tick=2,
                               enable_epistemic_ordering=False,
                               enable_exploration_floor=True)
        ctrl.tick()
        # The floor requires epistemic ordering; with it off, no floor.
        assert _floor_events(db) == []


# ── AC-2 at the controller: monopoly fires + event persisted ──

class TestMonopolyFire:
    def test_floor_promotes_non_leader_and_records_event(self, db):
        order: list[str] = []
        _monopoly_setup(db)
        ctrl = make_controller(db, order=order, max_calls_per_tick=2,
                               enable_exploration_floor=True)
        result = ctrl.tick()
        # The floor promotes t-n into the last available slot; the cap (2)
        # dispatches t-l1 then t-n (t-l2 is displaced beyond the cap).
        assert order == ["t-l1", "t-n"]
        # The dispatch records the floor-amended policy version.
        assert result.ordering_policy_version == "task-eval-2026.1-floor.1"
        # Exactly one FloorGrantRecorded event for the grant.
        events = _floor_events(db)
        grants = [e for e in events
                  if json.loads(e["payload_json"])["kind"] == "FLOOR_GRANTED"]
        assert len(grants) == 1
        p = json.loads(grants[0]["payload_json"])
        assert p["trajectory"] == "research_program:rp-B"
        assert p["task_ref"] == "t-n"
        assert p["slot"] == 1
        assert p["round_index"] == 0
        # correlation_id is the ranking_id (the transient ordering identity).
        assert grants[0]["correlation_id"].startswith("task_ord_")

    def test_diverse_set_is_inert_no_event(self, db):
        order: list[str] = []
        insert_program(db, "rp-A", version=1)
        insert_program(db, "rp-B", version=2)
        insert_task(db, "t-a", cost_class="LOW",
                    created_at="2026-01-01T01:00:00.000000+00:00",
                    provenance=["research_program:rp-A"])
        insert_task(db, "t-b", cost_class="LOW",
                    created_at="2026-01-01T02:00:00.000000+00:00",
                    provenance=["research_program:rp-B"])
        ctrl = make_controller(db, order=order, max_calls_per_tick=2,
                               enable_exploration_floor=True)
        ctrl.tick()
        assert order == ["t-a", "t-b"]
        assert _floor_events(db) == []


# ── AC-3 at the controller: fail-closed capacity validation ──

class TestCapacityRejection:
    def test_floor_slots_at_cap_rejected_at_construction(self, db):
        with pytest.raises(ValueError):
            make_controller(db, max_calls_per_tick=2,
                            enable_exploration_floor=True,
                            floor_policy=FloorPolicy(floor_slots=2))

    def test_floor_slots_below_cap_accepted(self, db):
        ctrl = make_controller(db, max_calls_per_tick=2,
                               enable_exploration_floor=True,
                               floor_policy=FloorPolicy(floor_slots=1))
        assert ctrl._enable_exploration_floor is True


# ── F-C decay at the controller ──

class TestFCDecay:
    POLICY = FloorPolicy(floor_stagnation_rounds=2,
                         floor_decay_cooldown_rounds=1,
                         floor_stagnation_mode=FloorStagnationMode.DECAY)

    def test_stagnant_grant_triggers_withdrawal_event(self, db):
        _monopoly_setup(db)
        # Seed 2 prior unproductive grants to rp-B (baseline + 1). The
        # current grant is the 2nd unproductive ⇒ decay fires.
        _seed_floor_grant(db, "research_program:rp-B", 0, 0)
        _seed_floor_grant(db, "research_program:rp-B", 1, 0)
        ctrl = make_controller(db, max_calls_per_tick=2,
                               enable_exploration_floor=True,
                               floor_policy=self.POLICY)
        ctrl.tick()
        kinds = [json.loads(e["payload_json"])["kind"]
                 for e in _floor_events(db)]
        assert "FLOOR_GRANTED" in kinds
        assert "FLOOR_ENTITLEMENT_WITHDRAWN" in kinds


# ── F-C kill-switch at the controller ──

class TestFCKillSwitch:
    POLICY = FloorPolicy(floor_stagnation_rounds=2,
                         floor_stagnation_mode=FloorStagnationMode.KILL_SWITCH)
    OUT = ("research_program:rp-B:evidence_requirement:h1",)

    def test_stagnant_grant_triggers_suspension_event(self, db):
        _monopoly_setup(db)
        _seed_floor_grant(db, "research_program:rp-B", 0, 0,
                          outstanding=self.OUT)
        _seed_floor_grant(db, "research_program:rp-B", 1, 0,
                          outstanding=self.OUT)
        ctrl = make_controller(db, max_calls_per_tick=2,
                               enable_exploration_floor=True,
                               floor_policy=self.POLICY)
        ctrl.tick()
        kinds = [json.loads(e["payload_json"])["kind"]
                 for e in _floor_events(db)]
        assert "FLOOR_GRANTED" in kinds
        assert "FLOOR_SUSPENDED" in kinds

    def test_suspended_trajectory_not_promoted(self, db):
        """Once suspended (seeded), the floor does not promote rp-B again —
        no new grant to rp-B this tick."""
        _monopoly_setup(db)
        # Seed a full suspension: baseline + 2 unproductive (reaches N=2 on
        # the 3rd grant) — derive_floor_states marks rp-B suspended.
        _seed_floor_grant(db, "research_program:rp-B", 0, 0,
                          outstanding=self.OUT)
        _seed_floor_grant(db, "research_program:rp-B", 1, 0,
                          outstanding=self.OUT)
        _seed_floor_grant(db, "research_program:rp-B", 2, 0,
                          outstanding=self.OUT)
        order: list[str] = []
        ctrl = make_controller(db, order=order, max_calls_per_tick=2,
                               enable_exploration_floor=True,
                               floor_policy=self.POLICY)
        ctrl.tick()
        # rp-B is suspended ⇒ no non-leader is floor-eligible ⇒ pure order.
        assert order == ["t-l1", "t-l2"]
        new_grants = [e for e in _floor_events(db)
                      if json.loads(e["payload_json"])["kind"]
                      == "FLOOR_GRANTED"
                      and json.loads(e["payload_json"])["round_index"] >= 3]
        assert new_grants == []


# ── event payload integrity ──

class TestEventPayload:
    def test_payload_is_validated_and_bounded(self, db):
        _monopoly_setup(db)
        ctrl = make_controller(db, max_calls_per_tick=2,
                               enable_exploration_floor=True)
        ctrl.tick()
        events = _floor_events(db)
        assert events
        for e in events:
            p = json.loads(e["payload_json"])
            # The S6 payload cap (4 KiB) holds — the floor payload is small.
            assert len(e["payload_json"].encode()) <= 4096
            assert p["kind"]
            assert p["trajectory"]


# ── merge-audit M2: the P-AUTO-1 seq artifact is not an ordering input ──

class TestSequencerArtifactNotAnOrderingParticipant:
    """The P-AUTO-1 sequencer admits a recorded-only artifact (PENDING,
    ``spec.template == "sequencer"``, never claimable). ``_monopoly_setup``
    stamps the real tasks AFTER the controller clock, so the artifact —
    admitted at tick time, i.e. at the clock — is the earliest row and
    carries no ``research_program:`` provenance. Unfiltered it would be the
    pure-policy leader, the leading trajectory would be nothing, and the
    monopoly would never be seen. The artifact is excluded at discovery; the
    fix is the exclusion, never a re-timing of these fixtures."""

    def test_floor_observables_are_clean_of_the_seq_artifact(self, db):
        order: list[str] = []
        _monopoly_setup(db)
        ctrl = make_controller(db, order=order, max_calls_per_tick=2,
                               enable_exploration_floor=True)
        result = ctrl.tick()
        seq_rows = [r["task_id"] for r in db.execute(
            "SELECT task_id FROM tasks WHERE task_id LIKE 'seq-%'")]
        assert len(seq_rows) == 1, "precondition: the sequencer admitted one"
        seq_id = seq_rows[0]
        assert seq_id not in order
        assert seq_id not in result.dispatched
        assert seq_id not in result.unhandled
        assert seq_id not in [e["task_id"] for e in _floor_events(db)]
        # The monopoly is still seen through the artifact's presence.
        assert result.ordering_policy_version == "task-eval-2026.1-floor.1"

    def test_ranking_is_the_real_eligible_set_only(self, db):
        _monopoly_setup(db)
        ctrl = make_controller(db)
        assert ctrl._acquire_lock()
        ctrl._sequencer_pass()
        seq_id = db.execute(
            "SELECT task_id FROM tasks WHERE task_id LIKE 'seq-%'"
        ).fetchone()[0]
        eligible = ctrl._discover_eligible()
        assert seq_id not in [t["task_id"] for t in eligible]
        ordered, ranking = ctrl._order_eligible(eligible)
        assert [t["task_id"] for t in ordered] == ["t-l1", "t-l2", "t-n"]
        assert ranking is not None
        assert [c.task_ref for c in ranking.comparison] == [
            "t-l1", "t-l2", "t-n"]
        ctrl._release_lock()
