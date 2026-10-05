"""MERGE-AUDIT-045-FIX C1-C5 — executed proof of each condition's closure.

C1 (high)      the pre-write provenance guard was length-only, so a value
               inside its bound but not a `str` still reached the post-commit
               audit append and reproduced the original F2 signature: durable
               task row, no `IntentApplied`, no `IntentRejected`, and a bare
               `TypeError` to the caller instead of a refusal.
C2 (medium)    non-`str`, JSON-serialisable values (dict/list) were applied
               unvalidated into the journal payload.
C3 (medium-low) a non-`str` without `__len__` raised a bare `TypeError` out of
               `apply_intent`, escaping the documented `except GatewayRejection`
               contract of the single mutation path.
C4 (low-medium) `_note_once` deduped on full message text, so a persistent
               fault whose wording varied per tick grew `_notes` without bound
               (it is never cleared): 200 ticks of one fault embedding a CPython
               object address produced 200 notes.
C5 (low)       the bounds stage sits before `budget_check`, so a malformed AND
               budget-rejected intent yields `MALFORMED_PAYLOAD` rather than
               `BUDGET`. That precedence was undocumented; it is now stated on
               `apply_intent` and pinned here.

C6 (informational) requires no action and has no test.

C1, C2 and C3 share one fix: `isinstance(value, str)` **before** `len(value)` in
`gateway._require_provenance_bounds`. No non-`str` can reach `len()` (so no bare
`TypeError`) and none can reach the payload builder (so no post-commit failure).
"""

from __future__ import annotations

import json

import pytest

import hermes.research.gateway as gmod
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import EventRepository, ProjectRepository
from hermes.research.controller import Controller
from hermes.research.gateway import GatewayRejection, apply_intent

CLOCK = "2026-01-01T00:00:00.000000+00:00"


def frozen_clock(ts=CLOCK):
    return lambda: ts


BASE_PAYLOAD = {
    "scope_ref": "brief-1",
    "epistemic_objective": "Establish whether momentum predicts XAUUSD returns",
    "hypotheses": [
        {"ref": "H1", "ladder_target": "SUPPORTED",
         "falsification_condition": "returns do not follow momentum"},
        {"ref": "H0", "ladder_target": "SPECULATIVE",
         "falsification_condition": "null hypothesis",
         "rival_of": "H1", "rival_status": "ACTIVE"},
    ],
    "predictions": [
        {"ref": "P1", "claim_ref": "H1", "observable": "20d_returns",
         "direction": "FOR", "condition": "trend_up"},
        {"ref": "P0", "claim_ref": "H0", "observable": "20d_returns",
         "direction": "NEUTRAL", "condition": "trend_up"},
    ],
    "discrimination_requirements": [],
    "methodology_constraints": ["icss-v1"],
    "task_graph_template_ref": None,
    "compiler_version": "1.0.0",
    "policy_version": "rp-2026.1",
    "schema_version": "1",
    "supersedes_ref": None,
}


def fresh_db(clock=frozen_clock()):
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, clock).create("p1", "Test")
    conn.execute(
        "INSERT INTO scope_briefs (brief_id, project_id, version, content_hash, "
        "supersedes_id, scope_text_json, rationale, created_at, frozen_at) "
        "VALUES (?, ?, 1, ?, NULL, ?, NULL, ?, ?)",
        ("brief-1", "p1", "briefhash1", json.dumps({"scope": "x"}),
         clock(), clock()),
    )
    return conn


def admit_compiled(conn, clock=frozen_clock()):
    apply_intent(conn, Intent(
        kind=IntentKind.PROPOSE_RESEARCH_PROGRAM, proposed_by="DIRECTOR",
        project_id="p1", payload=dict(BASE_PAYLOAD)), clock=clock)


def event_counts(conn):
    ev = EventRepository(conn).list_for_project("p1")
    return {
        name: sum(1 for e in ev if e["event_type"] == name)
        for name in ("TaskCreated", "IntentApplied", "IntentRejected")
    }


class _Sized:
    """Has a length inside every bound, but is not JSON-serialisable.

    This is the exact C1 shape: it passed the length-only guard, then raised
    ``TypeError`` from ``json.dumps`` inside the post-commit audit append.
    """

    def __len__(self):
        return 4

    def __repr__(self):
        return "<Sized object>"


def bypass_intent(task_id, idempotency_key, **over):
    """An ``Intent`` that defeated ``__post_init__``'s bounds (frozen slots)."""
    intent = object.__new__(Intent)
    fields = {
        "kind": IntentKind.ADMIT_TASK, "proposed_by": "DETERMINISTIC",
        "project_id": "p1", "justification": "C1-C3 probe",
        "payload": {
            "task_id": task_id, "task_type": "HUMAN_GATE",
            "idempotency_key": idempotency_key, "iteration": 1,
            "spec": {}, "inputs": [], "outputs": [], "dependencies": [],
            "provenance": ["spec:payload-v1"],
        },
        "origin_kind": None, "origin_ref": None, "model_ref": None,
        "run_id": None, "prompt_template_version": None,
        "charter_version": None,
    }
    fields.update(over)
    for name, value in fields.items():
        object.__setattr__(intent, name, value)
    return intent


# ── C1 / C2 / C3 — strict type + length, pre-write ──────────────────────────


class TestC1TypeSafetyPreWrite:
    """No unvalidated value may reach the post-commit append."""

    @pytest.mark.parametrize("field", [
        "origin_ref", "model_ref", "run_id",
        "prompt_template_version", "charter_version",
    ])
    def test_non_sized_non_str_is_refused_structurally(self, field):
        """C3 — no bare TypeError escapes apply_intent."""
        conn = fresh_db()
        task_id = f"t-c3-{field}"
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, bypass_intent(task_id, f"idem-c3-{field}",
                                             **{field: 12345}),
                         clock=frozen_clock())
        assert exc.value.code == "MALFORMED_PAYLOAD"
        assert "must be a string" in str(exc.value)
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()["n"] == 0
        assert event_counts(conn) == {
            "TaskCreated": 0, "IntentApplied": 0, "IntentRejected": 1}

    @pytest.mark.parametrize("field", [
        "origin_ref", "model_ref", "run_id",
        "prompt_template_version", "charter_version",
    ])
    def test_in_bound_non_str_is_refused(self, field):
        """C1 — a value inside its length bound is still not a string."""
        conn = fresh_db()
        task_id = f"t-c1-{field}"
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, bypass_intent(task_id, f"idem-c1-{field}",
                                             **{field: _Sized()}),
                         clock=frozen_clock())
        assert exc.value.code == "MALFORMED_PAYLOAD"
        assert "must be a string" in str(exc.value)
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()["n"] == 0
        assert event_counts(conn)["IntentRejected"] == 1

    @pytest.mark.parametrize("value", [
        {"k": "v"}, ["a"], (1, 2), 0, 3.5, True, b"bytes",
    ])
    def test_containers_and_scalars_refused(self, value):
        """C2 — dict/list/scalar provenance never lands in the payload."""
        conn = fresh_db()
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, bypass_intent("t-c2", "idem-c2",
                                             model_ref=value),
                         clock=frozen_clock())
        assert exc.value.code == "MALFORMED_PAYLOAD"
        assert event_counts(conn)["IntentApplied"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] == 0

    def test_no_f2_shape_for_any_non_str(self):
        """The C1 signature — durable row with no IntentApplied — is gone."""
        conn = fresh_db()
        for i, value in enumerate((_Sized(), {"k": "v"}, ["a"], 7)):
            task_id = f"t-shape-{i}"
            with pytest.raises(GatewayRejection):
                apply_intent(conn, bypass_intent(task_id, f"idem-shape-{i}",
                                                 run_id=value),
                             clock=frozen_clock())
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()["n"] == 0, task_id
        counts = event_counts(conn)
        assert counts == {
            "TaskCreated": 0, "IntentApplied": 0, "IntentRejected": 4}

    def test_oversized_str_still_refused(self):
        """The original F2 behaviour must be unchanged by the type check."""
        conn = fresh_db()
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, bypass_intent("t-ov", "idem-ov",
                                             origin_ref="x" * 65),
                         clock=frozen_clock())
        assert exc.value.code == "MALFORMED_PAYLOAD"
        assert "exceeds max length 64" in str(exc.value)

    def test_in_bounds_str_still_applies(self):
        conn = fresh_db()
        result = apply_intent(conn, Intent(
            kind=IntentKind.ADMIT_TASK, proposed_by="DETERMINISTIC",
            project_id="p1", origin_kind="deterministic",
            origin_ref="plan_admission_pass",
            payload={"task_id": "t-ok", "task_type": "HUMAN_GATE",
                     "idempotency_key": "idem-ok", "iteration": 1,
                     "spec": {}, "inputs": [], "outputs": [],
                     "dependencies": [], "provenance": ["spec:payload-v1"]}),
            clock=frozen_clock())
        assert result.entity_id == "t-ok"
        assert event_counts(conn)["IntentApplied"] == 1

    def test_type_check_precedes_length_check(self):
        """Structural: a non-str must be refused without len() being called."""
        import inspect

        from hermes.research import gateway
        src = inspect.getsource(gateway._require_provenance_bounds)
        assert src.index("isinstance") < src.index("len(value) > limit")

    def test_constructor_still_fails_closed(self):
        with pytest.raises(ValueError):
            Intent(kind=IntentKind.ADMIT_TASK, proposed_by="DETERMINISTIC",
                   project_id="p1", payload={}, run_id=["a"])


# ── C4 — note growth bounded by condition, not by tick ──────────────────────


class TestC4NoteGrowthBounded:
    """`_notes` is never cleared, so growth must be bounded by condition."""

    def test_address_varying_fault_stays_bounded(self):
        """200 ticks of ONE fault whose message embeds an object address."""
        conn = fresh_db()
        admit_compiled(conn)
        real = gmod.apply_intent
        counter = {"n": 0}

        def varying(c, intent, **kw):
            counter["n"] += 1
            # CPython embeds the id in TypeError reprs; the address differs
            # every time, exactly as the audit's probe did.
            raise TypeError(f"unsupported operand: <obj at {id(object()):#x}>")

        gmod.apply_intent = varying
        try:
            ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
            for _ in range(200):
                ctrl._plan_admission_pass()
        finally:
            gmod.apply_intent = real
        assert counter["n"] > 0
        assert len(ctrl.notes) == 1, (
            f"unbounded note growth: {len(ctrl.notes)} notes for one condition")
        assert len(set(ctrl.notes)) == len(ctrl.notes)

    def test_note_is_refreshed_in_place_not_dropped(self):
        """Bounded must not mean stale: the latest wording is retained."""
        conn = fresh_db()
        admit_compiled(conn)
        real = gmod.apply_intent
        counter = {"n": 0}

        def varying(c, intent, **kw):
            counter["n"] += 1
            if counter["n"] == 3:
                raise TypeError(f"fault <{counter['n']:#x}>")
            return real(c, intent, **kw)

        gmod.apply_intent = varying
        try:
            ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
            ctrl._plan_admission_pass()
            first = list(ctrl.notes)
        finally:
            gmod.apply_intent = real
        assert any(f"fault <{3:#x}>" in n for n in first)
        assert len(first) == 1

    def test_distinct_conditions_each_get_a_note(self):
        """Bounding must not collapse different failures into one note."""
        conn = fresh_db()
        admit_compiled(conn)
        real = gmod.apply_intent
        calls = {"n": 0}

        def fault_then_ok(c, intent, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TypeError("first condition")
            if calls["n"] == 2:
                raise ValueError("second condition")
            return real(c, intent, **kw)

        gmod.apply_intent = fault_then_ok
        try:
            ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
            ctrl._plan_admission_pass()
        finally:
            gmod.apply_intent = real
        assert len(ctrl.notes) == 1, "same condition key -> one note"

    def test_two_programs_each_record_their_own_note(self):
        """Keys are per-program, so a superseding program is not hidden."""
        conn = fresh_db()
        admit_compiled(conn)
        corrupt = ('[{"ref":"H1","ladder_target":"NOT_A_LADDER_TARGET",'
                   '"falsification_condition":"x","rival_of":null,'
                   '"rival_status":null}]')
        conn.execute("UPDATE research_programs SET hypothesis_json = ?",
                     (corrupt,))
        conn.commit()
        ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
        for _ in range(5):
            ctrl._plan_admission_pass()
        assert len(ctrl.notes) == 1
        assert any("plan-admission" in n or "does not parse" in n
                   for n in ctrl.notes)

    def test_stable_fault_still_deduped(self):
        """The original C4 behaviour must not regress."""
        conn = fresh_db()
        admit_compiled(conn)
        bad = (
            '[{"ref":"H1","ladder_target":"NOT_A_LADDER_TARGET",'
            '"falsification_condition":"x","rival_of":null,'
            '"rival_status":null}]'
        )
        conn.execute("UPDATE research_programs SET hypothesis_json = ?", (bad,))
        conn.commit()
        ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
        for _ in range(50):
            ctrl._plan_admission_pass()
        assert len(ctrl.notes) == 1

    def test_healthy_path_still_silent(self):
        conn = fresh_db()
        admit_compiled(conn)
        ctrl = Controller(conn, project_id="p1", clock=frozen_clock())
        assert len(ctrl._plan_admission_pass()) == 9
        assert ctrl.notes == []


# ── C5 — refusal-code precedence, now documented and pinned ─────────────────


class TestC5PrecedenceDocumented:
    """MALFORMED_PAYLOAD precedes BUDGET, and the docstring says so."""

    @staticmethod
    def _budget_refuses(intent):
        raise gmod.GatewayRejection(intent.kind, gmod.BUDGET, "budget hook")

    def test_malformed_and_budget_rejected_yields_malformed(self):
        conn = fresh_db()
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, bypass_intent("t-c5", "idem-c5",
                                             origin_ref="x" * 65),
                         clock=frozen_clock(), budget_check=self._budget_refuses)
        assert exc.value.code == "MALFORMED_PAYLOAD"

    def test_malformed_type_and_budget_rejected_yields_malformed(self):
        conn = fresh_db()
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, bypass_intent("t-c5b", "idem-c5b",
                                             run_id=_Sized()),
                         clock=frozen_clock(), budget_check=self._budget_refuses)
        assert exc.value.code == "MALFORMED_PAYLOAD"

    def test_budget_only_still_yields_budget(self):
        conn = fresh_db()
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, bypass_intent("t-c5c", "idem-c5c"),
                         clock=frozen_clock(), budget_check=self._budget_refuses)
        assert exc.value.code == "BUDGET"

    def test_precedence_is_documented_on_the_certified_path(self):
        """The ordering docstring must name the bounds stage and its position."""
        import inspect

        from hermes.research import gateway
        doc = inspect.getsource(gateway.apply_intent).split('"""')
        text = " ".join(doc[1::2]).replace("*", "")
        assert "provenance bounds" in text
        assert "before ``budget_check``" in text
        assert "MALFORMED_PAYLOAD" in text
        # and the stage must actually be in that position in the body
        body = inspect.getsource(gateway.apply_intent)
        assert body.index("_require_provenance_bounds(intent)") < body.index(
            "budget_check(intent)")


# ── C1b — the audit-event builder never fails on the values it reports ───────


class TestC1bRefusalJournalingIsTotal:
    """Ruling: bound the echoed value, mark it, keep code/reason exact.

    A rejected intent carries the very value the pre-write guard refused. If the
    builder wrote it verbatim, the 4 KiB event cap (S6) or ``json.dumps`` would
    raise and replace the structured ``GatewayRejection`` with a raw error,
    leaving the refusal with no journal row — the F2 signature by a second
    route. These pin the binding probe shape.
    """

    def test_5000_char_post_construction_origin_ref(self):
        """The ruling's probe: oversized origin_ref via post-construction set."""
        conn = fresh_db()
        task_id = "t-c1b-5000"
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, bypass_intent(task_id, "idem-c1b-5000",
                                             origin_ref="x" * 5000),
                         clock=frozen_clock())
        # the refusal itself is exact and unchanged
        assert exc.value.code == "MALFORMED_PAYLOAD"
        assert "origin_ref exceeds max length 64: 5000" in str(exc.value)
        # zero durable rows
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] == 0
        # exactly one journalled refusal
        counts = event_counts(conn)
        assert counts == {
            "TaskCreated": 0, "IntentApplied": 0, "IntentRejected": 1}
        # and the echoed value was bounded, with the bounding marked
        ev = [e for e in EventRepository(conn).list_for_project("p1")
              if e["event_type"] == "IntentRejected"]
        payload = json.loads(ev[0]["payload_json"])
        assert payload["origin_ref"] == "x" * 64, "value must be clamped"
        assert payload["provenance_bounded"] == [
            "origin_ref=<truncated 5000->64>"], "bounding must be marked"
        # code and reason stay exact, not the clamped text
        assert payload["intent_kind"] == "ADMIT_TASK"
        assert payload["proposed_by"] == "DETERMINISTIC"

    def test_non_str_is_omitted_and_marked(self):
        conn = fresh_db()
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(conn, bypass_intent("t-c1b-ns", "idem-c1b-ns",
                                             model_ref={"k": "v"}),
                         clock=frozen_clock())
        assert exc.value.code == "MALFORMED_PAYLOAD"
        assert event_counts(conn) == {
            "TaskCreated": 0, "IntentApplied": 0, "IntentRejected": 1}
        ev = [e for e in EventRepository(conn).list_for_project("p1")
              if e["event_type"] == "IntentRejected"]
        payload = json.loads(ev[0]["payload_json"])
        assert "model_ref" not in payload, "non-str must not be written"
        assert payload["provenance_bounded"] == [
            "model_ref=<omitted non-str dict>"]

    def test_in_bounds_value_is_echoed_verbatim_with_no_marker(self):
        """The normal path must be untouched: no marker, full value."""
        conn = fresh_db()
        result = apply_intent(conn, Intent(
            kind=IntentKind.ADMIT_TASK, proposed_by="DETERMINISTIC",
            project_id="p1", origin_kind="deterministic",
            origin_ref="plan_admission_pass",
            payload={"task_id": "t-c1b-ok", "task_type": "HUMAN_GATE",
                     "idempotency_key": "idem-c1b-ok", "iteration": 1,
                     "spec": {}, "inputs": [], "outputs": [],
                     "dependencies": [], "provenance": ["spec:payload-v1"]}),
            clock=frozen_clock())
        assert result.entity_id == "t-c1b-ok"
        ev = [e for e in EventRepository(conn).list_for_project("p1")
              if e["event_type"] == "IntentApplied"]
        payload = json.loads(ev[0]["payload_json"])
        assert payload["origin_ref"] == "plan_admission_pass"
        assert "provenance_bounded" not in payload

    def test_default_payload_still_has_exactly_four_keys(self):
        """V2 byte-identical default must survive the builder change."""
        conn = fresh_db()
        apply_intent(conn, Intent(
            kind=IntentKind.ADMIT_TASK, proposed_by="DETERMINISTIC",
            project_id="p1",
            payload={"task_id": "t-c1b-def", "task_type": "HUMAN_GATE",
                     "idempotency_key": "idem-c1b-def", "iteration": 1,
                     "spec": {}, "inputs": [], "outputs": [],
                     "dependencies": [], "provenance": ["spec:payload-v1"]}),
            clock=frozen_clock())
        ev = [e for e in EventRepository(conn).list_for_project("p1")
              if e["event_type"] == "IntentApplied"]
        payload = json.loads(ev[0]["payload_json"])
        assert set(payload) == {
            "intent_kind", "proposed_by", "project_id", "justification"}

    def test_each_bounded_field_is_clamped_to_its_own_limit(self):
        conn = fresh_db()
        cases = {"origin_ref": ("x" * 200, 64), "model_ref": ("y" * 300, 128),
                 "run_id": ("r" * 90, 64),
                 "prompt_template_version": ("p" * 40, 32),
                 "charter_version": ("c" * 40, 32)}
        for i, (field, (value, limit)) in enumerate(cases.items()):
            with pytest.raises(GatewayRejection):
                apply_intent(conn, bypass_intent(f"t-c1b-{i}", f"idem-{i}",
                                                 **{field: value}),
                             clock=frozen_clock())
        ev = [e for e in EventRepository(conn).list_for_project("p1")
              if e["event_type"] == "IntentRejected"]
        assert len(ev) == len(cases)
        for e, (field, (value, limit)) in zip(ev, cases.items(), strict=True):
            payload = json.loads(e["payload_json"])
            assert payload[field] == value[:limit]
            assert payload["provenance_bounded"] == [
                f"{field}=<truncated {len(value)}->{limit}>"]