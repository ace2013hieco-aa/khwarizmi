"""Q-02 EligibleTask mode — pure-level fixtures (design §13.1/6/7/9).

The ratified Model-B policy orders the controller's ALREADY-eligible task set
through the ActionEvaluation EligibleTask mode: pure, deterministic, no
scalar score, no LLM input. These fixtures pin the pure function's contract;
the controller consumption (dispatch application, boundaries, removal) lives
in test_controller_q02.py.

Maps design §13 acceptance tests 1 (eligible-vs-eligible), 6 (determinism),
7 (information provenance), 9 (tie behavior) plus the designed degeneracy and
versioning contract.
"""
from __future__ import annotations

from hermes.research.evaluation import (
    DIMENSION_ORDER,
    CostTier,
    DimensionLevel,
    EligibleTask,
    EligibleTaskRanking,
    TaskDiagnosticKind,
    evaluate_eligible_tasks,
    summarize_task_ranking,
)
from hermes.research.task_obligations import program_obligation_dimensions

DIM_KEYS = DIMENSION_ORDER


def _task(ref, cost=CostTier.UNKNOWN, dims=None, basis=(), created="2026-08-15T10:00:00"):
    return EligibleTask(
        task_ref=ref,
        template="extract",
        cost_class=cost,
        dimensions=dims or {},
        basis_refs=tuple(basis),
        created_at=created,
    )


def _ordered_refs(ranking: EligibleTaskRanking) -> list[str]:
    return [e.task_ref for e in ranking.comparison]


# ── §13.1 eligible-vs-eligible: the declared order ──

class TestEligibleVsEligible:
    def test_high_evidence_gap_dimension_orders_first(self):
        high = _task("t-a", CostTier.MEDIUM,
                     {"evidence_gap_closure": DimensionLevel.HIGH})
        low = _task("t-b", CostTier.MEDIUM)
        r = evaluate_eligible_tasks([low, high])
        assert _ordered_refs(r) == ["t-a", "t-b"]

    def test_dimension_levels_are_lexicographic(self):
        # Same dimension, different levels: HIGH > MEDIUM > LOW > NONE.
        tasks = [
            _task("none", CostTier.LOW, {}),
            _task("low", CostTier.LOW, {"evidence_gap_closure": DimensionLevel.LOW}),
            _task("high", CostTier.LOW, {"evidence_gap_closure": DimensionLevel.HIGH}),
            _task("medium", CostTier.LOW, {"evidence_gap_closure": DimensionLevel.MEDIUM}),
        ]
        r = evaluate_eligible_tasks(tasks)
        assert _ordered_refs(r) == ["high", "medium", "low", "none"]

    def test_cost_breaks_dimension_ties_low_first_unknown_last(self):
        tasks = [
            _task("t-unknown", CostTier.UNKNOWN,
                  {"rival_discrimination": DimensionLevel.MEDIUM}),
            _task("t-high-cost", CostTier.HIGH,
                  {"rival_discrimination": DimensionLevel.MEDIUM}),
            _task("t-low-cost", CostTier.LOW,
                  {"rival_discrimination": DimensionLevel.MEDIUM}),
        ]
        r = evaluate_eligible_tasks(tasks)
        assert _ordered_refs(r) == ["t-low-cost", "t-high-cost", "t-unknown"]

    def test_later_created_at_does_not_beat_higher_dimension(self):
        # created_at is the tie-break only — never the primary signal.
        later_high = _task("t-later", CostTier.LOW,
                           {"coverage": DimensionLevel.HIGH},
                           created="2026-08-15T11:00:00")
        earlier_low = _task("t-earlier", CostTier.LOW, {},
                            created="2026-08-15T09:00:00")
        r = evaluate_eligible_tasks([earlier_low, later_high])
        assert _ordered_refs(r) == ["t-later", "t-earlier"]


# ── §13.6 determinism: byte-identical ordering ──

class TestDeterminism:
    def test_same_inputs_same_ranking_identity(self):
        tasks = [
            _task("t-1", CostTier.MEDIUM, {"frontier_value": DimensionLevel.HIGH},
                  ("research_program:p1",), "2026-08-15T10:00:00"),
            _task("t-2", CostTier.LOW, {}, (), "2026-08-15T09:00:00"),
            _task("t-3", CostTier.UNKNOWN, {}, (), "2026-08-15T11:00:00"),
        ]
        a = evaluate_eligible_tasks(tasks)
        b = evaluate_eligible_tasks(list(reversed(tasks)))
        assert a == b
        assert a.ranking_id == b.ranking_id
        assert a.content_hash == b.content_hash
        assert a.input_state_hash == b.input_state_hash

    def test_version_triple_changes_identity(self):
        tasks = [_task("t-1"), _task("t-2")]
        base = evaluate_eligible_tasks(tasks)
        new_policy = evaluate_eligible_tasks(tasks, policy_version="task-eval-2026.2")
        new_eval = evaluate_eligible_tasks(tasks, evaluator_version="1.3.0")
        assert base.content_hash != new_policy.content_hash
        assert base.content_hash != new_eval.content_hash
        assert new_policy.policy_version == "task-eval-2026.2"
        assert base.evaluator_version == "1.2.0"  # v1.2: per-requirement satisfaction links
        assert base.schema_version == "1"

    def test_reordering_input_set_is_identity_preserving(self):
        tasks = [_task("t-a", CostTier.HIGH), _task("t-b", CostTier.LOW)]
        a = evaluate_eligible_tasks(tasks)
        b = evaluate_eligible_tasks([tasks[1], tasks[0]])
        assert a == b

    def test_ordering_is_total(self):
        # Identical dims+cost+created_at: task_ref is the unique final tie.
        tasks = [_task(f"t-{i:02d}") for i in range(20)]
        r = evaluate_eligible_tasks(tasks)
        assert len(r.comparison) == 20
        assert _ordered_refs(r) == sorted(f"t-{i:02d}" for i in range(20))


# ── §13.7 information provenance: basis_refs + no heuristic input ──

class TestProvenance:
    def test_basis_refs_round_trip_into_the_ranking(self):
        t = _task("t-1", CostTier.MEDIUM,
                  {"evidence_gap_closure": DimensionLevel.HIGH},
                  ("research_program:p1:evidence_requirement:0",))
        r = evaluate_eligible_tasks([t])
        ev = r.comparison[0]
        assert ev.basis_refs == ("research_program:p1:evidence_requirement:0",)
        # The basis is part of the content hash — it is auditable, not cosmetic.
        without_basis = evaluate_eligible_tasks(
            [_task("t-1", CostTier.MEDIUM,
                   {"evidence_gap_closure": DimensionLevel.HIGH})])
        assert r.content_hash != without_basis.content_hash

    def test_all_six_dimensions_carried_in_order(self):
        dims = dict.fromkeys(DIM_KEYS, DimensionLevel.HIGH)
        r = evaluate_eligible_tasks([_task("t-1", CostTier.LOW, dims)])
        ev = r.comparison[0]
        assert [k for k, _ in ev.dimensions] == list(DIM_KEYS)
        assert all(v == DimensionLevel.HIGH for _, v in ev.dimensions)

    def test_unknown_dimension_keys_are_ignored_not_ranked(self):
        # A heuristic/LLM label outside the ratified vocabulary cannot enter
        # the ordering: unknown keys fall out, the dimension stays NONE.
        t = _task("t-1", CostTier.LOW, {"llm_gut_feel": DimensionLevel.HIGH})
        r = evaluate_eligible_tasks([t])
        assert all(v == DimensionLevel.NONE for _, v in r.comparison[0].dimensions)
        assert any(d.kind == TaskDiagnosticKind.DEGENERATE_TO_BASELINE
                   for d in r.diagnostics)

    def test_v1_has_no_estimator_input(self):
        # The input surface is closed by construction: EligibleTask carries no
        # heuristic/estimator fields, and the function takes only the version
        # triple + policy text. The advisory labeling contract (design §8) is
        # satisfied vacuously — there is no estimator to label.
        import dataclasses
        fields = {f.name for f in dataclasses.fields(EligibleTask)}
        assert not (fields & {"estimator", "estimator_version", "roi_score",
                              "information_gain", "expected_value"})


# ── §13.9 tie behavior ──

class TestTieBreaking:
    def test_earlier_created_at_first_within_equal_policy(self):
        tasks = [
            _task("t-b", CostTier.MEDIUM, {}, (), "2026-08-15T10:00:00"),
            _task("t-a", CostTier.MEDIUM, {}, (), "2026-08-15T09:00:00"),
        ]
        r = evaluate_eligible_tasks(tasks)
        assert _ordered_refs(r) == ["t-a", "t-b"]

    def test_task_ref_breaks_identical_tasks(self):
        tasks = [_task("t-2", CostTier.LOW, {}, (), "2026-08-15T10:00:00"),
                 _task("t-1", CostTier.LOW, {}, (), "2026-08-15T10:00:00")]
        r = evaluate_eligible_tasks(tasks)
        assert _ordered_refs(r) == ["t-1", "t-2"]

    def test_tie_break_is_not_clock_or_process_order(self):
        # Reversed input order must not change the result (no stability leak).
        pair = [_task("t-2", CostTier.LOW, {}, (), "2026-08-15T10:00:00"),
                _task("t-1", CostTier.LOW, {}, (), "2026-08-15T10:00:00")]
        assert (_ordered_refs(evaluate_eligible_tasks(pair))
                == _ordered_refs(evaluate_eligible_tasks(list(reversed(pair)))))


# ── designed degeneracy + empty set ──

class TestDegeneracy:
    def test_all_none_degrades_to_baseline_with_diagnostic(self):
        tasks = [_task("t-2", CostTier.UNKNOWN, {}, (), "2026-08-15T10:00:00"),
                 _task("t-1", CostTier.UNKNOWN, {}, (), "2026-08-15T09:00:00")]
        r = evaluate_eligible_tasks(tasks)
        assert _ordered_refs(r) == ["t-1", "t-2"]  # created_at baseline
        kinds = [d.kind for d in r.diagnostics]
        assert TaskDiagnosticKind.DEGENERATE_TO_BASELINE in kinds

    def test_partial_facts_are_not_flagged_degenerate(self):
        tasks = [_task("t-1", CostTier.LOW,
                       {"coverage": DimensionLevel.MEDIUM}, (), "2026-08-15T09:00:00"),
                 _task("t-2", CostTier.LOW, {}, (), "2026-08-15T10:00:00")]
        r = evaluate_eligible_tasks(tasks)
        assert not any(d.kind == TaskDiagnosticKind.DEGENERATE_TO_BASELINE
                       for d in r.diagnostics)

    def test_empty_set_yields_empty_ranking_with_diagnostic(self):
        r = evaluate_eligible_tasks([])
        assert r.comparison == ()
        assert any(d.kind == TaskDiagnosticKind.EMPTY_ELIGIBLE_SET
                   for d in r.diagnostics)
        assert r.policy_version  # version triple still bound

    def test_summarize_is_deterministic_and_self_consistent(self):
        tasks = [_task("t-1", CostTier.MEDIUM,
                       {"frontier_value": DimensionLevel.HIGH},
                       ("research_program:p1",), "2026-08-15T10:00:00"),
                 _task("t-2", CostTier.LOW, {}, (), "2026-08-15T09:00:00")]
        r = evaluate_eligible_tasks(tasks)
        s = summarize_task_ranking(r)
        assert "EligibleTaskRanking" in s
        assert "task-eval-2026.1" in s
        assert s == summarize_task_ranking(r)


# ── §7 obligation-fact derivation (option C, evaluator v1.1) ──

def _program(pid="rp-1", *, hypotheses=(), evidence=(), discriminations=()):
    return {
        "program_id": pid,
        "hypotheses": list(hypotheses),
        "evidence_requirements": list(evidence),
        "discrimination_requirements": list(discriminations),
    }


def _hyp(ref, ladder="SUPPORTED", rival_of=None, rival_status=None):
    return {"ref": ref, "ladder_target": ladder,
            "falsification_condition": "fc", "rival_of": rival_of,
            "rival_status": rival_status}


def _req(claim_ref, ladder="SUPPORTED", artifacts=("a1", "a2")):
    return {"claim_ref": claim_ref, "ladder_target": ladder,
            "required_artifacts": list(artifacts), "associated_gates": []}


def _disc(ref="d1"):
    return {"ref": ref, "hypothesis_a": "ha", "hypothesis_b": "hb",
            "observable": "o", "expected_difference": "d",
            "required_condition": "c", "measurement_method_ref": "m"}


class TestObligationDerivation:
    def test_unmet_confirmatory_requirements_map_high(self):
        p = _program(evidence=[_req("h1"), _req("h2"), _req("h3")])
        dims, basis = program_obligation_dimensions([p])
        assert dims["evidence_gap_closure"] is DimensionLevel.HIGH
        assert len(basis) == 3
        assert all(b.startswith("research_program:rp-1:evidence_requirement:")
                   for b in basis)

    def test_single_unmet_maps_medium(self):
        p = _program(evidence=[_req("h1")])
        dims, _ = program_obligation_dimensions([p])
        assert dims["evidence_gap_closure"] is DimensionLevel.MEDIUM

    def test_satisfied_requirements_map_low(self):
        # Per-requirement (IDR-038 §3.1): each requirement fulfilled only by
        # its OWN linked classes — h1 is linked both classes, h2 is not.
        p = _program(evidence=[_req("h1"), _req("h2")])
        sat = {"rp-1": {"h1": frozenset({"a1", "a2"})}}
        dims, _ = program_obligation_dimensions([p], satisfactions=sat)
        # h1 satisfied, h2 outstanding → exactly 1 outstanding → MEDIUM.
        assert dims["evidence_gap_closure"] is DimensionLevel.MEDIUM
        sat2 = {"rp-1": {"h1": frozenset({"a1", "a2"}),
                         "h2": frozenset({"a1", "a2"})}}
        dims2, _ = program_obligation_dimensions([p], satisfactions=sat2)
        assert dims2["evidence_gap_closure"] is DimensionLevel.LOW

    def test_no_obligations_map_none(self):
        dims, basis = program_obligation_dimensions([_program()])
        assert dims["evidence_gap_closure"] is DimensionLevel.NONE
        assert dims["rival_discrimination"] is DimensionLevel.NONE
        assert dims["replication_value"] is DimensionLevel.NONE
        assert basis == ()

    def test_replication_value_from_replicated_targets(self):
        p = _program(evidence=[
            _req("h-rep", ladder="REPLICATED",
                 artifacts=("pre_registered_experiment", "replication_report")),
            _req("h-sup", ladder="SUPPORTED")])
        dims, _ = program_obligation_dimensions([p])
        assert dims["replication_value"] is DimensionLevel.MEDIUM  # 1 outstanding
        p2 = _program(evidence=[_req("h-sup", ladder="SUPPORTED")])
        dims2, _ = program_obligation_dimensions([p2])
        assert dims2["replication_value"] is DimensionLevel.NONE

    def test_rival_discrimination_from_unresolved_and_discriminations(self):
        p = _program(
            hypotheses=[_hyp("ha", rival_of="hb", rival_status="UNRESOLVED"),
                        _hyp("hb", rival_of="ha", rival_status="ACTIVE")],
            discriminations=[_disc("d1")])
        dims, basis = program_obligation_dimensions([p])
        assert dims["rival_discrimination"] is DimensionLevel.HIGH
        assert any("rival:ha" in b for b in basis)
        assert any("discrimination:d1" in b for b in basis)

    def test_active_only_rivals_map_low(self):
        p = _program(hypotheses=[
            _hyp("ha", rival_of="hb", rival_status="ACTIVE"),
            _hyp("hb", rival_of="ha", rival_status="ACTIVE")])
        dims, _ = program_obligation_dimensions([p])
        assert dims["rival_discrimination"] is DimensionLevel.LOW

    def test_no_stored_source_dimensions_are_always_none(self):
        dims, _ = program_obligation_dimensions([_program()])
        for d in ("contradiction_reduction", "frontier_value", "coverage"):
            assert dims[d] is DimensionLevel.NONE

    def test_malformed_entries_skipped_fail_closed(self):
        p = _program(evidence=[_req("h1"), "not-a-requirement", None],
                     hypotheses=[_hyp("ha", rival_of="hb", rival_status="UNRESOLVED"),
                                 123],
                     discriminations=[_disc("d1"), {}])
        dims, basis = program_obligation_dimensions([p])
        # The malformed requirement is skipped; the valid one still counts.
        assert dims["evidence_gap_closure"] is DimensionLevel.MEDIUM
        assert any("rival:ha" in b for b in basis)
        assert any("discrimination:d1" in b for b in basis)
        # A fully corrupt program never crashes and yields no facts.
        dims2, basis2 = program_obligation_dimensions([{"program_id": "bad"}])
        assert all(v is DimensionLevel.NONE for v in dims2.values())
        assert basis2 == ()

    def test_multi_program_aggregation(self):
        p1 = _program("rp-1", evidence=[_req("h1")])
        p2 = _program("rp-2", evidence=[_req("h2")])
        dims, basis = program_obligation_dimensions([p1, p2])
        assert dims["evidence_gap_closure"] is DimensionLevel.HIGH  # 2 outstanding
        assert len(basis) == 2
        assert basis == tuple(sorted(basis))

    def test_basis_refs_deduped_and_sorted(self):
        p = _program(evidence=[_req("h1"), _req("h1")])
        _, basis = program_obligation_dimensions([p])
        assert len(basis) == 1  # deduped
        assert basis == ("research_program:rp-1:evidence_requirement:h1",)


# ── structural purity of the derivation module (mirrors AC-04) ──

class TestCountMappingEdges:
    """Closure-directive follow-up (the count-mapping edges the
    reconciliation record still names): the count→level mapping's extreme
    inputs are deterministic and CAPPED — negative counts (unreachable
    from the increment-only derivation, pinned anyway), overflow counts
    (capped at HIGH, never beyond), zero totals (NONE), and malformed
    obligations (skipped — a corrupt program can never fabricate an
    outstanding fact)."""

    def test_negative_outstanding_maps_low_deterministically(self):
        from hermes.research.task_obligations import _obligation_level
        assert _obligation_level(-5, 5) is DimensionLevel.LOW
        assert _obligation_level(-1, 1) is DimensionLevel.LOW

    def test_overflow_maps_high_capped(self):
        from hermes.research.task_obligations import _obligation_level
        assert _obligation_level(10**9, 10**9) is DimensionLevel.HIGH
        assert _obligation_level(2, 10**9) is DimensionLevel.HIGH
        assert _obligation_level(10**9, 1) is DimensionLevel.HIGH

    def test_zero_total_maps_none_even_with_outstanding(self):
        from hermes.research.task_obligations import _obligation_level
        assert _obligation_level(0, 0) is DimensionLevel.NONE
        assert _obligation_level(5, 0) is DimensionLevel.NONE

    def test_malformed_obligation_skipped_never_a_fact(self):
        # empty required_artifacts -> skipped; only the valid requirement
        # counts, so exactly 1 outstanding -> MEDIUM, basis cites it only
        p = _program(evidence=[
            _req("h1"),
            {"claim_ref": "broken", "ladder_target": "SUPPORTED",
             "required_artifacts": []},
            "not-a-mapping",
        ])
        dims, basis = program_obligation_dimensions([p])
        assert dims["evidence_gap_closure"] is DimensionLevel.MEDIUM
        assert len(basis) == 1
        assert basis[0] == "research_program:rp-1:evidence_requirement:h1"


class TestObligationPurity:
    def test_no_write_surface(self):
        import hermes.research.task_obligations as to
        with open(to.__file__, encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("sqlite3", "INSERT INTO", "UPDATE ", "DELETE FROM",
                       "repository", "Repository", "conn.execute",
                       "from hermes.persistence", "import hermes.persistence",
                       "apply_intent"):
            assert banned not in src, f"authority surface leaked: {banned}"

    def test_imports_only_the_shared_vocabulary(self):
        import hermes.research.task_obligations as to
        with open(to.__file__, encoding="utf-8") as fh:
            src = fh.read()
        assert "from hermes.research.evaluation import DimensionLevel" in src
        assert "from hermes.research.controller" not in src
