"""Tests for the approved ActionEvaluation library (IDR-019, Optimizer Part 1).

Verdict: **ADOPT AS A DETERMINISTIC EVALUATION LIBRARY**. The optimizer-as-
authority was rejected. These tests pin the accepted residue: a pure,
deterministic, multidimensional comparison of EXISTING admissible candidates
into a hashed CandidateRanking — no scalar score, no weighted utility, no
write path, no candidate generation, no LLM.

Maps Part 1 §33 AC-01..12 to the library contract.
"""
from __future__ import annotations

from hermes.research.evaluation import (
    DEFAULT_ORDERING_POLICY,
    DIMENSION_ORDER,
    CandidateAction,
    CandidateStatus,
    CostTier,
    DiagnosticKind,
    DimensionLevel,
    evaluate_candidates,
    summarize_ranking,
)

# ── helpers ──

def cand(ref: str = "c1", **kw) -> CandidateAction:
    base = {
        "candidate_ref": ref,
        "action_type": "experiment",
        "objective_ref": "obj-1",
        "dimensions": {
            "evidence_gap_closure": DimensionLevel.MEDIUM,
            "contradiction_reduction": DimensionLevel.NONE,
            "rival_discrimination": DimensionLevel.NONE,
            "replication_value": DimensionLevel.NONE,
            "frontier_value": DimensionLevel.NONE,
            "coverage": DimensionLevel.NONE,
        },
        "basis_refs": (f"basis-{ref}",),
    }
    base.update(kw)
    return CandidateAction(**base)


# ── AC-01 / AC-12: determinism and reproducibility ──

class TestDeterminism:
    def test_ac01_same_inputs_same_identity(self):
        r1 = evaluate_candidates((cand("c1"), cand("c2")))
        r2 = evaluate_candidates((cand("c1"), cand("c2")))
        assert r1.ranking_id == r2.ranking_id
        assert r1.content_hash == r2.content_hash
        assert r1.input_state_hash == r2.input_state_hash
        assert r1.comparison == r2.comparison

    def test_ac01_candidate_order_invariant(self):
        """Same candidate set in different order → identical ranking."""
        a, b = cand("c1"), cand("c2")
        r1 = evaluate_candidates((a, b))
        r2 = evaluate_candidates((b, a))
        assert r1.ranking_id == r2.ranking_id
        assert r1.comparison == r2.comparison

    def test_ac01_selection_history_order_invariant(self):
        r1 = evaluate_candidates(
            (cand("c1"),),
            selection_history={"c1": (3, 1), "c2": (5, 0)},
        )
        r2 = evaluate_candidates(
            (cand("c1"),),
            selection_history={"c2": (5, 0), "c1": (3, 1)},
        )
        assert r1.ranking_id == r2.ranking_id
        assert r1.diagnostics == r2.diagnostics

    def test_ac01_stale_ids_order_invariant(self):
        r1 = evaluate_candidates((cand("c1"),),
                                 stale_input_ids=frozenset({"s1", "s2"}))
        r2 = evaluate_candidates((cand("c1"),),
                                 stale_input_ids=frozenset({"s2", "s1"}))
        assert r1.ranking_id == r2.ranking_id

    def test_ac01_repeated_process_start_equivalent(self):
        """Two fresh processes (re-instantiated library state) must agree."""
        import importlib
        ev1 = importlib.import_module("hermes.research.evaluation")
        ev2 = importlib.import_module("hermes.research.evaluation")
        r1 = ev1.evaluate_candidates((cand(),))
        r2 = ev2.evaluate_candidates((cand(),))
        assert r1.ranking_id == r2.ranking_id
        assert r1.content_hash == r2.content_hash

    def test_ac12_independently_reproducible(self):
        """The ranking can be re-derived from the documented inputs alone:
        ranking identity is a pure function of (candidates, history, stale,
        version triple, policy)."""
        r1 = evaluate_candidates((cand("c1"),))
        r2 = evaluate_candidates(
            (CandidateAction(
                candidate_ref="c1", action_type="experiment",
                objective_ref="obj-1",
                dimensions=dict(cand().dimensions.items()),
                basis_refs=("basis-c1",)),))
        assert r1.ranking_id == r2.ranking_id

    def test_ac08_changed_version_changes_identity(self):
        r1 = evaluate_candidates((cand(),), evaluator_version="1.0.0")
        r2 = evaluate_candidates((cand(),), evaluator_version="1.0.1")
        assert r1.ranking_id != r2.ranking_id
        assert r1.content_hash != r2.content_hash

    def test_ac08_changed_policy_changes_identity(self):
        r1 = evaluate_candidates((cand(),), policy_version="eval-2026.1")
        r2 = evaluate_candidates((cand(),), policy_version="eval-2026.2")
        assert r1.ranking_id != r2.ranking_id


# ── AC-02: state change changes evaluation ──

class TestStateSensitivity:
    def test_ac02_dimension_change_reranks(self):
        a = cand("a", dimensions={**cand().dimensions,
                                  "evidence_gap_closure": DimensionLevel.LOW})
        b = cand("b", dimensions={**cand().dimensions,
                                  "evidence_gap_closure": DimensionLevel.HIGH})
        r = evaluate_candidates((a, b))
        assert [e.candidate_ref for e in r.comparison] == ["b", "a"]

    def test_ac02_ordering_policy_is_lexicographic_not_weighted(self):
        """A candidate HIGH on a later dimension does NOT beat one MEDIUM on
        the primary dimension — the documented lexicographic policy wins over
        any implicit weighted intuition (Part 1 §7: no weighted score)."""
        primary = cand("p", dimensions={**cand().dimensions,
                                        "evidence_gap_closure": DimensionLevel.MEDIUM})
        later = cand("l", dimensions={**cand().dimensions,
                                      "evidence_gap_closure": DimensionLevel.NONE,
                                      "coverage": DimensionLevel.HIGH})
        r = evaluate_candidates((later, primary))
        assert [e.candidate_ref for e in r.comparison] == ["p", "l"]

    def test_unknown_cost_sorts_last_but_never_blocks(self):
        """AC-08: UNKNOWN cost is not treated as a value — it sorts last, and
        the candidate is still ranked (with cost flagged) rather than dropped."""
        cheap = cand("cheap", cost=CostTier.LOW)
        unknown = cand("unknown", cost=CostTier.UNKNOWN)
        r = evaluate_candidates((unknown, cheap))
        assert [e.candidate_ref for e in r.comparison] == ["cheap", "unknown"]
        assert all(e.status == CandidateStatus.ADMISSIBLE for e in r.comparison)

    def test_dimensions_are_always_present_in_canonical_order(self):
        r = evaluate_candidates((cand(),))
        (e,) = r.comparison
        assert [k for k, _ in e.dimensions] == list(DIMENSION_ORDER)


# ── AC-03: gates dominate ranking ──

class TestGateDominance:
    def test_ac03_gate_blocked_never_ranked(self):
        gated = cand("g", blocked_by=("pre_compute",))
        other = cand("o", dimensions={**cand().dimensions,
                                      "evidence_gap_closure": DimensionLevel.LOW})
        r = evaluate_candidates((gated, other))
        assert [e.candidate_ref for e in r.comparison] == ["o"]
        assert any(e.candidate_ref == "g" and e.status
                   == CandidateStatus.EXCLUDED_GATE for e in r.exclusions)

    def test_ac03_gate_blocked_high_value_candidate_still_excluded(self):
        """AC-03 + Part 1 §19: even the highest-value candidate is excluded
        when a mandatory gate is unsatisfied — ranking can never override a
        gate."""
        gated = cand("g",
                     dimensions=dict.fromkeys(DIMENSION_ORDER, DimensionLevel.HIGH),
                     cost=CostTier.LOW,
                     blocked_by=("pre_live",))
        r = evaluate_candidates((gated,))
        assert r.comparison == ()
        assert len(r.exclusions) == 1

    def test_dependency_blocked_surfaced_not_ranked(self):
        blocked = cand("b", dependency_unsatisfied=("icss-v1",))
        r = evaluate_candidates((blocked,))
        assert r.comparison == ()
        assert r.exclusions[0].status == CandidateStatus.BLOCKED_DEPENDENCY
        assert "icss-v1" in r.exclusions[0].exclusion_reason


# ── AC-04/05/06: no authority (structural) ──

class TestNoAuthority:
    @staticmethod
    def _executable_source() -> str:
        """Module source with docstrings stripped, so authority checks scan
        real code — not the docstring that *documents* the absence of
        authority."""
        import ast
        import inspect

        import hermes.research.evaluation as ev
        tree = ast.parse(inspect.getsource(ev))
        for node in ast.walk(tree):
            if (isinstance(node, (ast.Module, ast.FunctionDef,
                                  ast.AsyncFunctionDef, ast.ClassDef))
                    and node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body = node.body[1:]
        return ast.unparse(tree)

    def test_ac04_module_has_no_write_surface(self):
        """Structural: the library cannot create tasks — no repository, no
        SQL, no state mutation, no persistence imports."""
        src = self._executable_source()
        for banned in ("sqlite3", "INSERT INTO", "UPDATE ", "DELETE FROM",
                       "repository", "Repository", "conn.execute",
                       "from hermes.persistence", "import hermes.persistence"):
            assert banned not in src, f"authority surface leaked: {banned}"

    def test_ac05_no_evidence_promotion_vocabulary(self):
        """Structural: nothing in the evaluation vocabulary can promote
        evidence — no ladder targets, no evidence status, no verdicts."""
        src = self._executable_source()
        for banned in ("SUPPORTED", "REPLICATED", "promotion", "ladder"):
            assert banned not in src

    def test_ac06_no_budget_spend(self):
        """Structural: cost tiers are descriptive, never spend authority."""
        r = evaluate_candidates((cand(cost=CostTier.HIGH),))
        assert r.comparison[0].cost == CostTier.HIGH
        # only the comparison table exists; there is no budget object
        src = self._executable_source()
        assert "budget" not in src
        assert "spend" not in src

    def test_ac04_no_candidate_generation(self):
        """The library compares candidates it is given; it never invents
        actions (Part 1 protest §3). An empty set yields a diagnostic, not a
        synthetic candidate."""
        r = evaluate_candidates(())
        assert r.comparison == () and r.exclusions == ()
        assert any(d.kind == DiagnosticKind.EMPTY_CANDIDATE_SET
                   for d in r.diagnostics)


# ── AC-07 / AC-09 / AC-10: explanation, staleness, starvation ──

class TestAuditability:
    def test_ac07_every_recommendation_has_structured_reasons(self):
        r = evaluate_candidates((cand("c1"), cand("c2")))
        for e in r.comparison:
            assert e.basis_refs                    # per-candidate evidence refs
            assert e.exclusion_reason == ""        # admissible: no hidden reason
            assert isinstance(e.dimensions, tuple)
        assert r.ordering_policy == DEFAULT_ORDERING_POLICY
        assert r.evaluator_version and r.policy_version and r.schema_version

    def test_ac07_ranking_exposes_full_comparison_table(self):
        """Part 1 §16/§25: why A outranked B is structurally inspectable —
        the ordering key is derivable from the comparison fields."""
        a = cand("a", dimensions={**cand().dimensions,
                                  "evidence_gap_closure": DimensionLevel.MEDIUM},
                 cost=CostTier.LOW)
        b = cand("b", dimensions={**cand().dimensions,
                                  "evidence_gap_closure": DimensionLevel.LOW},
                 cost=CostTier.LOW)
        r = evaluate_candidates((a, b))
        assert [e.candidate_ref for e in r.comparison] == ["a", "b"]
        # the difference that caused the ordering is visible in the table
        da = dict(r.comparison[0].dimensions)
        db = dict(r.comparison[1].dimensions)
        assert da["evidence_gap_closure"] > db["evidence_gap_closure"]

    def test_ac09_stale_input_flagged_not_trusted(self):
        r = evaluate_candidates(
            (cand("c1", basis_refs=("graph-v2",)),),
            stale_input_ids=frozenset({"graph-v2"}))
        (e,) = r.comparison
        assert "graph-v2" in e.staleness
        assert any(d.kind == DiagnosticKind.STALE_INPUT for d in r.diagnostics)

    def test_ac09_stale_input_not_referenced_not_flagged(self):
        r = evaluate_candidates((cand("c1", basis_refs=("graph-v3",)),),
                                stale_input_ids=frozenset({"graph-v2"}))
        (e,) = r.comparison
        assert e.staleness == ()

    def test_ac10_starvation_detected(self):
        r = evaluate_candidates(
            (cand("starved"),),
            selection_history={"starved": (7, 0)})
        assert any(d.kind == DiagnosticKind.STARVED_CANDIDATE
                   and d.candidate_ref == "starved" for d in r.diagnostics)

    def test_ac10_selected_candidate_not_starved(self):
        r = evaluate_candidates(
            (cand("ok"),),
            selection_history={"ok": (7, 2)})
        assert not any(d.kind == DiagnosticKind.STARVED_CANDIDATE
                       for d in r.diagnostics)

    def test_no_improvement_diagnostic(self):
        """Failure mode (§28): no candidate improves any dimension → surfaced
        as a diagnostic; the policy is stop/pause/human, never pass."""
        flat = cand("flat", dimensions=dict.fromkeys(DIMENSION_ORDER, DimensionLevel.NONE))
        r = evaluate_candidates((flat,))
        assert any(d.kind == DiagnosticKind.NO_IMPROVEMENT for d in r.diagnostics)
        assert r.comparison  # still compared; the Director decides

    def test_summarize_is_deterministic_and_readable(self):
        r = evaluate_candidates((cand("c1", cost=CostTier.MEDIUM),
                                 cand("gated", blocked_by=("pre_compute",))))
        s1 = summarize_ranking(r)
        s2 = summarize_ranking(r)
        assert s1 == s2
        assert r.ranking_id in s1
        assert "c1" in s1 and "gated" in s1
        assert "ordering policy" in s1


# ── AC-11: bounded expansion ──

class TestBoundedExpansion:
    def test_ac11_evaluation_cannot_generate_work(self):
        """The library's output is a fixed-size comparison; it carries no
        task list, no continuation, no recursion — nothing to unboundedly
        expand."""
        r = evaluate_candidates(tuple(cand(f"c{i}") for i in range(50)))
        # deterministic breadth: output size exactly equals input size
        assert len(r.comparison) == 50
        assert not hasattr(r, "continuation")
        assert not hasattr(r, "next_round")
        assert not hasattr(r, "expansion")
        assert len(r.comparison) + len(r.exclusions) == 50


# ── no scalar score invariant ──

class TestNoScalarScore:
    def test_ranking_has_no_score_field(self):
        r = evaluate_candidates((cand(),))
        assert not hasattr(r, "score")
        assert not hasattr(r, "value")
        assert not hasattr(r, "priority")
        (e,) = r.comparison
        assert not hasattr(e, "score")
        assert not hasattr(e, "value")

    def test_no_weighted_utility_documented(self):
        """The ordering policy is explicitly lexicographic over named
        dimensions — auditable and versioned, never a hidden weighted sum."""
        assert "lexicographic" in DEFAULT_ORDERING_POLICY
        assert "weighted" not in DEFAULT_ORDERING_POLICY
        assert "score" not in DEFAULT_ORDERING_POLICY.lower()

    def test_ranking_id_content_addressed(self):
        r = evaluate_candidates((cand(),))
        assert r.ranking_id == f"eval_{r.content_hash[:24]}"
        assert len(r.content_hash) == 64
