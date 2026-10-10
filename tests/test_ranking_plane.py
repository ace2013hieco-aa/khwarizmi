"""Ranking-plane tests (O5): classifier, determinism, refusals, savings.

Covers ``src/hermes/research/ranking.py`` only:

1. the Choice/Score/None classifier over tool/candidate sets — a unique
   strict winner is CHOICE, comparable alternatives are SCORE,
   inadmissible candidates are NONE and are never ranked;
2. determinism — 100x identical artifacts, input-order invariance,
   cross-process identity under different ``PYTHONHASHSEED`` values,
   version/policy pins (same facts + same triple ⇒ same ``ranking_id``),
   and the policy binding every public output carries (a blank version
   refuses);
3. the frozen refusal vocabulary — every malformed candidate set refuses
   ``MALFORMED_PAYLOAD``, the oversize facts envelope refuses ``RATIONALE``
   naming sizes only, and the refusal-as-data shape is exact;
4. structural discipline — no write surface, no LLM/probability/threshold
   vocabulary, no float constants, no scalar field on the artifacts, and
   nothing outside this plane and its test references it (not wired);
5. the measurement harness — per-shape calls-saved pinned from our own
   fixtures, including a shape where the ranker provably cannot help and a
   shape where it is honestly measured as harmful.

The published "26 -> 1" figure is NOT evidence (``ADOPTION_AUDIT_R2.md``
§0: popularity and benchmark figures are struck). The only savings
asserted anywhere in this file are the ones measured from the fixtures
below.
"""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from dataclasses import fields, replace
from pathlib import Path

import pytest

from hermes.research.ranking import (
    DEFAULT_RANKER_VERSION,
    DEFAULT_RANKING_POLICY_VERSION,
    FACT_DIMENSION_ORDER,
    FROZEN_RANKING_REFUSAL_CODES,
    MALFORMED_PAYLOAD,
    MAX_FACTS_ENVELOPE_BYTES,
    RANKING_INTEGRATION_POINT,
    RANKING_POLICY,
    RANKING_SCHEMA_VERSION,
    CandidateClass,
    CandidateFacts,
    CandidateJudgment,
    CandidateRankingArtifact,
    ClassificationReason,
    CostTier,
    FixtureTask,
    GrantState,
    MatchLevel,
    PolicyBinding,
    RankingComparison,
    RankingDiagnosticKind,
    RankingRefusal,
    RiskTier,
    candidate_set_envelope_bytes,
    classify_candidate_set,
    compare_against_baseline,
    decisive_key,
    ordering_key,
    rank_candidates,
    summarize_comparison,
    summarize_ranking,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

CHILDREN_SOURCE = (
    "import sys\n"
    "from hermes.research.ranking import (\n"
    "    CandidateFacts, CostTier, GrantState, MatchLevel, RiskTier,\n"
    "    rank_candidates,\n"
    ")\n"
    "def facts(ref, capability):\n"
    "    return CandidateFacts(\n"
    "        candidate_ref=ref, admissible=True, capability_match=capability,\n"
    "        scope_match=MatchLevel.EXACT, grant_state=GrantState.GRANTED,\n"
    "        cost_tier=CostTier.MEDIUM, risk_tier=RiskTier.LOW)\n"
    "cands = (facts('cand_gamma', MatchLevel.NONE),\n"
    "         facts('cand_beta', MatchLevel.PARTIAL),\n"
    "         facts('cand_alpha', MatchLevel.EXACT))\n"
    "r = rank_candidates(cands)\n"
    "sys.stdout.write(r.ranking_id + ':' + r.content_hash + ':' +\n"
    "                 r.ordering_policy)\n"
)

# ── helpers ──


def facts(
    ref: str,
    *,
    admissible: bool = True,
    capability: MatchLevel = MatchLevel.EXACT,
    scope: MatchLevel = MatchLevel.EXACT,
    grant: GrantState = GrantState.GRANTED,
    cost: CostTier = CostTier.MEDIUM,
    risk: RiskTier = RiskTier.LOW,
    successes: int = 0,
    failures: int = 0,
) -> CandidateFacts:
    return CandidateFacts(
        candidate_ref=ref,
        admissible=admissible,
        capability_match=capability,
        scope_match=scope,
        grant_state=grant,
        cost_tier=cost,
        risk_tier=risk,
        observed_successes=successes,
        observed_failures=failures,
    )


def _executable_source(module: object) -> str:
    """Module source with docstrings stripped, so authority checks scan
    real code — not the docstring that *documents* the absence of
    authority (the ``test_evaluation`` discipline)."""
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if (
            isinstance(
                node,
                (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body = node.body[1:]
    return ast.unparse(tree)


def _public_view(ranking: CandidateRankingArtifact) -> tuple[object, ...]:
    """The complete public artifact as a comparable tuple."""
    return (
        ranking.ranking_id,
        ranking.ranker_version,
        ranking.policy_version,
        ranking.schema_version,
        ranking.input_state_hash,
        ranking.ordering_policy,
        tuple(
            (j.candidate_ref, j.classification.value, j.reason.value, j.rank)
            for j in ranking.ranking
        ),
        tuple(
            (j.candidate_ref, j.classification.value, j.reason.value, j.rank)
            for j in ranking.excluded
        ),
        ranking.choice_ref,
        tuple((d.kind.value, d.detail) for d in ranking.diagnostics),
        ranking.content_hash,
    )


# ── the fixture task set (our fixtures or nothing) ──
#
# Each shape pins a measured baseline-vs-ranker call count. The baseline
# policy tries the candidates in the order presented; the ranker tries the
# ranked order; both count the 1-based position of ``success_ref``.

CAPABILITY_DECISIVE = FixtureTask(
    task_ref="capability-decisive",
    candidates=(
        facts("cand_gamma", capability=MatchLevel.NONE),
        facts("cand_delta", capability=MatchLevel.PARTIAL),
        facts("cand_beta", capability=MatchLevel.PARTIAL),
        facts("cand_alpha", capability=MatchLevel.EXACT),
    ),
    success_ref="cand_alpha",
    note="one exact-capability tool, presented last",
)

COST_DECISIVE = FixtureTask(
    task_ref="cost-decisive",
    candidates=(
        facts("cand_alpha", cost=CostTier.HIGH),
        facts("cand_gamma", capability=MatchLevel.NONE),
        facts("cand_beta", cost=CostTier.LOW),
    ),
    success_ref="cand_beta",
    note="equal capability, cheaper tool wins, presented last",
)

HISTORY_DECISIVE = FixtureTask(
    task_ref="history-decisive",
    candidates=(
        facts("cand_alpha", successes=0),
        facts("cand_gamma", successes=1),
        facts("cand_beta", successes=3),
    ),
    success_ref="cand_beta",
    note="equal facts, append-only success count wins",
)

AUTHORITY_EXCLUDED_DECOY = FixtureTask(
    task_ref="authority-excluded-decoy",
    candidates=(
        facts("cand_decoy", admissible=False, cost=CostTier.LOW, successes=9),
        facts("cand_beta", capability=MatchLevel.PARTIAL, cost=CostTier.LOW),
        facts(
            "cand_alpha",
            capability=MatchLevel.EXACT,
            scope=MatchLevel.PARTIAL,
            successes=1,
        ),
    ),
    success_ref="cand_alpha",
    note="best facts belong to an inadmissible candidate",
)

NO_DISCRIMINATION = FixtureTask(
    task_ref="no-discrimination",
    candidates=(
        facts("cand_alpha", successes=1),
        facts("cand_beta", successes=1),
    ),
    success_ref="cand_alpha",
    note="the decisive key is identical for both candidates",
)

FACTS_MISLEADING = FixtureTask(
    task_ref="facts-misleading",
    candidates=(
        facts("cand_alpha", capability=MatchLevel.PARTIAL),
        facts("cand_beta", capability=MatchLevel.NONE),
        facts("cand_gamma", capability=MatchLevel.EXACT),
    ),
    success_ref="cand_alpha",
    note="ground truth is not the fact-best candidate",
)

BASELINE_OPTIMAL = FixtureTask(
    task_ref="baseline-optimal",
    candidates=(
        facts("cand_alpha"),
        facts("cand_beta", capability=MatchLevel.PARTIAL),
    ),
    success_ref="cand_alpha",
    note="the presented order is already optimal",
)

FIXTURES = (
    CAPABILITY_DECISIVE,
    COST_DECISIVE,
    HISTORY_DECISIVE,
    AUTHORITY_EXCLUDED_DECOY,
    NO_DISCRIMINATION,
    FACTS_MISLEADING,
    BASELINE_OPTIMAL,
)

# shape -> (baseline_calls, ranked_calls, calls_saved)
PINNED_SAVINGS = (
    ("capability-decisive", 4, 1, 3),
    ("cost-decisive", 3, 1, 2),
    ("history-decisive", 3, 1, 2),
    ("authority-excluded-decoy", 3, 1, 2),
    ("no-discrimination", 1, 1, 0),
    ("facts-misleading", 1, 2, -1),
    ("baseline-optimal", 1, 1, 0),
)


class TestClassifier:
    def test_singleton_set_is_choice(self):
        result = classify_candidate_set((facts("cand_alpha"),))
        (judgment,) = result.ranking
        assert judgment.classification is CandidateClass.CHOICE
        assert judgment.reason is ClassificationReason.STRICT_WINNER
        assert judgment.rank == 1
        assert result.choice_ref == "cand_alpha"
        assert result.excluded == ()
        assert result.diagnostics == ()

    def test_unique_strict_winner_is_choice(self):
        result = classify_candidate_set(
            (facts("cand_beta", capability=MatchLevel.PARTIAL),
             facts("cand_alpha", capability=MatchLevel.EXACT))
        )
        assert result.choice_ref == "cand_alpha"
        assert result.ordered_refs == ("cand_alpha", "cand_beta")
        labels = result.classifications()
        assert labels == (("cand_alpha", "CHOICE"), ("cand_beta", "SCORE"))
        assert result.ranking[1].reason is ClassificationReason.RANKED_ALTERNATIVE

    def test_shared_decisive_head_has_no_choice(self):
        result = classify_candidate_set(
            (facts("cand_alpha", successes=2), facts("cand_beta", successes=2))
        )
        assert result.choice_ref is None
        assert {j.classification for j in result.ranking} == {CandidateClass.SCORE}
        assert [d.kind for d in result.diagnostics] == [
            RankingDiagnosticKind.NO_DECISIVE_CHOICE
        ]

    def test_fact_tie_is_broken_by_ref_only(self):
        # Identical decisive keys: the order is by candidate_ref, ascending.
        result = classify_candidate_set(
            (facts("cand_beta"), facts("cand_alpha"))
        )
        assert result.ordered_refs == ("cand_alpha", "cand_beta")

    def test_inadmissible_is_none_and_never_ranked(self):
        result = classify_candidate_set(
            (facts("cand_decoy", admissible=False, cost=CostTier.LOW, successes=9),
             facts("cand_alpha", capability=MatchLevel.PARTIAL))
        )
        assert result.ordered_refs == ("cand_alpha",)
        assert result.choice_ref == "cand_alpha"
        (excluded,) = result.excluded
        assert excluded.candidate_ref == "cand_decoy"
        assert excluded.classification is CandidateClass.NONE
        assert excluded.reason is ClassificationReason.INADMISSIBLE
        assert excluded.rank is None

    def test_no_admissible_candidate_ranks_nothing(self):
        result = classify_candidate_set(
            (facts("cand_alpha", admissible=False), facts("cand_beta", admissible=False))
        )
        assert result.ordered_refs == ()
        assert result.ranking == ()
        assert result.choice_ref is None
        assert len(result.excluded) == 2
        assert [d.kind for d in result.diagnostics] == [
            RankingDiagnosticKind.NO_ADMISSIBLE_CANDIDATE
        ]

    def test_every_input_candidate_gets_exactly_one_label(self):
        candidates = tuple(
            facts(ref, admissible=(ref != "cand_gamma"))
            for ref in ("cand_alpha", "cand_beta", "cand_gamma")
        )
        result = classify_candidate_set(candidates)
        labeled = [j.candidate_ref for j in (*result.ranking, *result.excluded)]
        assert sorted(labeled) == ["cand_alpha", "cand_beta", "cand_gamma"]
        assert len(labeled) == len(set(labeled))

    def test_ranks_are_contiguous_and_one_based(self):
        result = classify_candidate_set(
            (
                facts("cand_gamma", capability=MatchLevel.NONE),
                facts("cand_alpha", capability=MatchLevel.EXACT),
                facts("cand_beta", capability=MatchLevel.PARTIAL),
            )
        )
        assert [j.rank for j in result.ranking] == [1, 2, 3]

    def test_score_never_precedes_the_choice(self):
        result = classify_candidate_set(
            (facts("cand_alpha"), facts("cand_beta", capability=MatchLevel.PARTIAL))
        )
        assert result.ranking[0].classification is CandidateClass.CHOICE
        assert all(
            j.classification is CandidateClass.SCORE for j in result.ranking[1:]
        )

    def test_ranking_only_covers_the_admissible_set(self):
        result = classify_candidate_set(
            (facts("cand_decoy", admissible=False), facts("cand_alpha"))
        )
        assert set(result.ordered_refs) == {"cand_alpha"}

    def test_classification_is_input_order_invariant(self):
        candidates = (
            facts("cand_alpha", capability=MatchLevel.EXACT),
            facts("cand_beta", capability=MatchLevel.PARTIAL),
            facts("cand_gamma", admissible=False),
        )
        forward = classify_candidate_set(candidates)
        backward = classify_candidate_set(tuple(reversed(candidates)))
        assert forward.classifications() == backward.classifications()
        assert forward.choice_ref == backward.choice_ref

    def test_excluded_order_is_canonical_under_reversed_input(self):
        # O5_REDTEAM P3-1: with two inadmissible candidates the public
        # `excluded` order is part of the public view, so it must be
        # canonical (ref-sorted) — dropping the canonical ref sort flips it
        # and must fail this pin.
        candidates = (
            facts("zzz_bad", admissible=False),
            facts("aaa_bad", admissible=False),
            facts("cand_alpha", capability=MatchLevel.PARTIAL),
            facts("cand_beta", capability=MatchLevel.EXACT),
        )
        forward = classify_candidate_set(candidates)
        backward = classify_candidate_set(tuple(reversed(candidates)))
        expected = ["aaa_bad", "zzz_bad"]
        assert [j.candidate_ref for j in forward.excluded] == expected
        assert [j.candidate_ref for j in backward.excluded] == expected
        assert forward.classifications() == backward.classifications()
        artifact_forward = rank_candidates(candidates)
        artifact_backward = rank_candidates(tuple(reversed(candidates)))
        assert [j.candidate_ref for j in artifact_forward.excluded] == expected
        assert artifact_forward.ranking_id == artifact_backward.ranking_id
        assert artifact_forward.content_hash == artifact_backward.content_hash


class TestOrderingPolicy:
    def test_order_is_lexicographic_not_weighted(self):
        # A dominates on the FIRST dimension only; B dominates everywhere
        # else. A still ranks first — a weighted sum could not guarantee it.
        superior_first = facts(
            "cand_alpha",
            capability=MatchLevel.EXACT,
            scope=MatchLevel.NONE,
            grant=GrantState.UNKNOWN,
            cost=CostTier.UNKNOWN,
            risk=RiskTier.HIGH,
            failures=9,
        )
        inferior_first = facts(
            "cand_beta",
            capability=MatchLevel.PARTIAL,
            scope=MatchLevel.EXACT,
            grant=GrantState.GRANTED,
            cost=CostTier.LOW,
            risk=RiskTier.LOW,
            successes=9,
        )
        result = classify_candidate_set((inferior_first, superior_first))
        assert result.choice_ref == "cand_alpha"

    def test_unknown_grant_and_cost_sort_last(self):
        known = facts("cand_alpha", grant=GrantState.NOT_GRANTED, cost=CostTier.HIGH)
        unknown = facts(
            "cand_beta", grant=GrantState.UNKNOWN, cost=CostTier.UNKNOWN,
            successes=99,
        )
        result = classify_candidate_set((unknown, known))
        assert result.ordered_refs == ("cand_alpha", "cand_beta")

    def test_failures_only_break_after_successes(self):
        more_success = facts("cand_alpha", successes=2, failures=5)
        clean = facts("cand_beta", successes=1, failures=0)
        result = classify_candidate_set((clean, more_success))
        assert result.ordered_refs == ("cand_alpha", "cand_beta")

    def test_decisive_key_ignores_the_ref_and_ordering_key_appends_it(self):
        a = facts("cand_alpha", successes=1)
        b = facts("cand_beta", successes=1)
        assert decisive_key(a) == decisive_key(b)
        assert ordering_key(a) < ordering_key(b)

    def test_ordering_key_is_all_integers_then_the_ref(self):
        key = ordering_key(facts("cand_alpha"))
        assert len(key) == len(FACT_DIMENSION_ORDER) + 1
        assert all(isinstance(term, int) for term in key[:-1])
        assert key[-1] == "cand_alpha"

    def test_policy_string_is_lexicographic_and_pinned(self):
        assert "lexicographic" in RANKING_POLICY
        assert "weighted" not in RANKING_POLICY
        assert "threshold" not in RANKING_POLICY
        assert len(FACT_DIMENSION_ORDER) == 7


class TestDeterminismAndIdentity:
    def test_same_facts_same_identity(self):
        candidates = (
            facts("cand_alpha"),
            facts("cand_beta", capability=MatchLevel.PARTIAL),
        )
        first = rank_candidates(candidates)
        second = rank_candidates(candidates)
        assert first.ranking_id == second.ranking_id
        assert first.content_hash == second.content_hash
        assert _public_view(first) == _public_view(second)

    def test_repeated_100x_is_identical(self):
        candidates = (
            facts("cand_gamma", capability=MatchLevel.NONE),
            facts("cand_alpha", capability=MatchLevel.EXACT),
            facts("cand_beta", capability=MatchLevel.PARTIAL),
        )
        views = {_public_view(rank_candidates(candidates)) for _ in range(100)}
        assert len(views) == 1

    def test_input_order_invariant(self):
        candidates = (
            facts("cand_gamma", capability=MatchLevel.NONE),
            facts("cand_alpha", capability=MatchLevel.EXACT),
            facts("cand_beta", capability=MatchLevel.PARTIAL),
        )
        forward = rank_candidates(candidates)
        for permutation in (
            tuple(reversed(candidates)),
            (candidates[1], candidates[2], candidates[0]),
            (candidates[2], candidates[0], candidates[1]),
        ):
            other = rank_candidates(permutation)
            assert other.ranking_id == forward.ranking_id
            assert other.content_hash == forward.content_hash
            assert _public_view(other) == _public_view(forward)

    def test_different_facts_change_identity(self):
        base = rank_candidates((facts("cand_alpha"),))
        other = rank_candidates((facts("cand_alpha", cost=CostTier.LOW),))
        assert base.ranking_id != other.ranking_id

    def test_changed_ranker_version_changes_identity(self):
        base = rank_candidates((facts("cand_alpha"),), ranker_version="1.0.0")
        other = rank_candidates((facts("cand_alpha"),), ranker_version="1.0.1")
        assert base.ranking_id != other.ranking_id

    def test_changed_policy_version_changes_identity(self):
        base = rank_candidates((facts("cand_alpha"),), policy_version="tool-rank-2026.1")
        other = rank_candidates((facts("cand_alpha"),), policy_version="tool-rank-2026.2")
        assert base.ranking_id != other.ranking_id

    def test_changed_ordering_policy_changes_identity(self):
        base = rank_candidates((facts("cand_alpha"),))
        other = rank_candidates(
            (facts("cand_alpha"),), ordering_policy="lexicographic over: nothing"
        )
        assert base.ranking_id != other.ranking_id
        assert "nothing" in other.ordering_policy

    def test_version_strings_are_recorded(self):
        ranking = rank_candidates((facts("cand_alpha"),))
        assert ranking.ranker_version == DEFAULT_RANKER_VERSION
        assert ranking.policy_version == DEFAULT_RANKING_POLICY_VERSION
        assert ranking.schema_version == RANKING_SCHEMA_VERSION
        assert ranking.ordering_policy == RANKING_POLICY

    def test_ranking_id_is_content_addressed(self):
        ranking = rank_candidates((facts("cand_alpha"),))
        assert ranking.ranking_id == f"rank_{ranking.content_hash[:24]}"
        assert len(ranking.content_hash) == 64
        assert len(ranking.input_state_hash) == 64

    def test_cross_process_identity_is_stable(self):
        in_process = rank_candidates(
            (
                facts("cand_gamma", capability=MatchLevel.NONE),
                facts("cand_beta", capability=MatchLevel.PARTIAL),
                facts("cand_alpha", capability=MatchLevel.EXACT),
            )
        )
        expected = (
            f"{in_process.ranking_id}:{in_process.content_hash}:"
            f"{in_process.ordering_policy}"
        )
        outputs = []
        for seed in ("0", "1", "12345"):
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = (
                str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
            )
            completed = subprocess.run(
                [sys.executable, "-c", CHILDREN_SOURCE],
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            outputs.append(completed.stdout)
        assert outputs == [expected, expected, expected]

    def test_summary_is_deterministic_and_readable(self):
        ranking = rank_candidates(
            (facts("cand_alpha"), facts("cand_beta", capability=MatchLevel.PARTIAL))
        )
        summary = summarize_ranking(ranking)
        assert ranking.ranking_id in summary
        assert "choice: cand_alpha" in summary
        assert summary == summarize_ranking(ranking)

    def test_every_public_output_carries_a_version_binding(self):
        # O5_REDTEAM P2: the classifier's public output carried no version
        # string. Every public output of this plane now names the policy it
        # was produced under, and it is the same binding the artifact records.
        candidates = (
            facts("cand_alpha"),
            facts("cand_beta", capability=MatchLevel.PARTIAL),
        )
        classification = classify_candidate_set(candidates)
        ranking = rank_candidates(candidates)
        comparison = compare_against_baseline(FIXTURES)
        assert classification.binding == PolicyBinding()
        assert classification.binding.ranker_version == DEFAULT_RANKER_VERSION
        assert (
            classification.binding.policy_version
            == DEFAULT_RANKING_POLICY_VERSION
        )
        assert classification.binding.schema_version == RANKING_SCHEMA_VERSION
        assert classification.binding.ordering_policy == RANKING_POLICY
        assert (
            ranking.ranker_version,
            ranking.policy_version,
            ranking.schema_version,
            ranking.ordering_policy,
        ) == (
            classification.binding.ranker_version,
            classification.binding.policy_version,
            classification.binding.schema_version,
            classification.binding.ordering_policy,
        )
        assert (
            comparison.ranker_version,
            comparison.policy_version,
            comparison.schema_version,
        ) == (
            classification.binding.ranker_version,
            classification.binding.policy_version,
            classification.binding.schema_version,
        )
        assert comparison.fixture_set_version

    def test_no_public_output_type_is_unversioned(self):
        import hermes.research.ranking as ranking_module

        for output_type in (
            ranking_module.CandidateSetClassification,
            ranking_module.CandidateRankingArtifact,
            ranking_module.RankingComparison,
        ):
            names = {f.name for f in fields(output_type)}
            assert names & {"binding", "ranker_version"}, output_type.__name__

    def test_custom_binding_is_recorded_and_moves_no_label(self):
        candidates = (
            facts("cand_alpha"),
            facts("cand_beta", capability=MatchLevel.PARTIAL),
        )
        default = classify_candidate_set(candidates)
        custom = classify_candidate_set(
            candidates,
            ranker_version="9.9.9",
            policy_version="tool-rank-2099.9",
            ordering_policy="lexicographic over: nothing",
        )
        # a version change moves the binding, never a label
        assert custom.classifications() == default.classifications()
        assert custom.choice_ref == default.choice_ref
        assert custom.binding.ranker_version == "9.9.9"
        assert custom.binding.policy_version == "tool-rank-2099.9"
        assert custom.binding.ordering_policy == "lexicographic over: nothing"
        ranking = rank_candidates(candidates, ranker_version="9.9.9")
        assert ranking.ranker_version == "9.9.9"
        assert ranking.ranker_version != default.binding.ranker_version

    def test_blank_version_strings_refuse_malformed(self):
        # an unversioned output is exactly the P2 gap: it refuses
        for bad in ("", "   "):
            with pytest.raises(RankingRefusal) as exc:
                classify_candidate_set(
                    (facts("cand_alpha"),), ranker_version=bad
                )
            assert exc.value.code == MALFORMED_PAYLOAD
        with pytest.raises(RankingRefusal) as exc2:
            rank_candidates((facts("cand_alpha"),), policy_version="")
        assert exc2.value.code == MALFORMED_PAYLOAD
        with pytest.raises(RankingRefusal) as exc3:
            rank_candidates((facts("cand_alpha"),), ordering_policy="  ")
        assert exc3.value.code == MALFORMED_PAYLOAD


class TestAdvisoryOnly:
    def test_inadmissibility_is_the_authority_ranking_cannot_reverse(self):
        decoy = facts(
            "cand_decoy", admissible=False, cost=CostTier.LOW, successes=9
        )
        alpha = facts("cand_alpha", capability=MatchLevel.PARTIAL)
        ranking = rank_candidates((decoy, alpha))
        assert ranking.choice_ref == "cand_alpha"
        assert [j.candidate_ref for j in ranking.ranking] == ["cand_alpha"]
        assert [j.candidate_ref for j in ranking.excluded] == ["cand_decoy"]
        assert ranking.excluded[0].classification is CandidateClass.NONE

        # The ONLY way the decoy joins the ranking is the caller's own
        # admissibility flip — the plane never writes eligibility.
        flipped = rank_candidates((replace(decoy, admissible=True), alpha))
        assert flipped.choice_ref == "cand_decoy"
        assert flipped.excluded == ()

    def test_ranking_reorders_only_inside_the_admissible_set(self):
        candidates = (
            facts("cand_alpha", capability=MatchLevel.PARTIAL),
            facts("cand_beta", admissible=False),
            facts("cand_gamma", capability=MatchLevel.EXACT),
        )
        ranking = rank_candidates(candidates)
        admissible_refs = {
            f.candidate_ref for f in candidates if f.admissible
        }
        assert {j.candidate_ref for j in ranking.ranking} == admissible_refs
        assert [j.candidate_ref for j in ranking.excluded] == ["cand_beta"]

    def test_artifact_exposes_no_eligibility_or_score_field(self):
        ranking = rank_candidates((facts("cand_alpha"),))
        (judgment,) = ranking.ranking
        for banned in ("score", "value", "priority", "probability", "weight"):
            assert not hasattr(ranking, banned)
            assert not hasattr(judgment, banned)
        # There is no writable authority surface on the artifact.
        for banned in ("admissible_after", "eligible", "spend", "budget"):
            assert not hasattr(ranking, banned)

    def test_structural_no_write_surface(self):
        import hermes.research.ranking as ranking_module

        source = _executable_source(ranking_module)
        for banned in (
            "sqlite3",
            "INSERT INTO",
            "UPDATE ",
            "DELETE FROM",
            "repository",
            "Repository",
            "conn.execute",
            "from hermes.persistence",
            "import hermes.persistence",
        ):
            assert banned not in source, f"authority surface leaked: {banned}"

    def test_structural_no_llm_or_scalar_vocabulary(self):
        import hermes.research.ranking as ranking_module

        source = _executable_source(ranking_module)
        for banned in (
            "llm",
            "model",
            "probability",
            "threshold",
            "weight",
            "heuristic",
            "prompt",
            "random",
            "datetime",
            "socket",
            "urllib",
        ):
            assert banned not in source, f"forbidden vocabulary leaked: {banned}"

    def test_structural_no_float_constants(self):
        import hermes.research.ranking as ranking_module

        tree = ast.parse(inspect.getsource(ranking_module))
        floats = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, float)
        ]
        assert floats == []

    def test_fact_profile_has_no_float_or_score_field(self):
        names = {f.name for f in fields(CandidateFacts)}
        assert names == {
            "candidate_ref",
            "admissible",
            "capability_match",
            "scope_match",
            "grant_state",
            "cost_tier",
            "risk_tier",
            "observed_successes",
            "observed_failures",
        }
        for field in fields(CandidateFacts):
            assert "float" not in str(field.type)
        judgment_names = {f.name for f in fields(CandidateJudgment)}
        assert judgment_names == {
            "candidate_ref",
            "classification",
            "reason",
            "rank",
            "facts",
        }

    def test_module_is_not_wired(self):
        needles = (
            "hermes.research.ranking",
            "hermes.research import ranking",
            "classify_candidate_set",
            "rank_candidates",
            "compare_against_baseline",
        )
        offenders: list[str] = []
        for base in (REPO_ROOT / "src", REPO_ROOT / "tests"):
            for path in base.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                if path.name in ("ranking.py", "test_ranking_plane.py"):
                    continue
                text = path.read_text(encoding="utf-8")
                if any(needle in text for needle in needles):
                    offenders.append(str(path.relative_to(REPO_ROOT)))
        assert offenders == [], f"ranking plane is referenced elsewhere: {offenders}"


class TestRefusals:
    def test_frozen_vocabulary_is_exactly_two_codes(self):
        assert {MALFORMED_PAYLOAD, "RATIONALE"} == FROZEN_RANKING_REFUSAL_CODES

    def test_unknown_refusal_code_is_rejected(self):
        with pytest.raises(ValueError):
            RankingRefusal("NOT_A_FROZEN_CODE", "detail")

    def test_refusal_as_data_shape(self):
        refusal = RankingRefusal(MALFORMED_PAYLOAD, "detail")
        assert refusal.to_refusal() == {
            "rejected": True,
            "code": MALFORMED_PAYLOAD,
            "detail": "detail",
        }

    def test_empty_set_refuses_malformed(self):
        with pytest.raises(RankingRefusal) as exc:
            rank_candidates(())
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_not_iterable_refuses_malformed(self):
        with pytest.raises(RankingRefusal) as exc:
            rank_candidates(None)
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_non_fact_member_refuses_malformed(self):
        with pytest.raises(RankingRefusal) as exc:
            rank_candidates((facts("cand_alpha"), "not-a-fact"))
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_blank_ref_refuses_malformed(self):
        with pytest.raises(RankingRefusal) as exc:
            facts("   ")
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_duplicate_ref_refuses_malformed(self):
        with pytest.raises(RankingRefusal) as exc:
            rank_candidates((facts("cand_alpha"), facts("cand_alpha")))
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_negative_count_refuses_malformed(self):
        with pytest.raises(RankingRefusal) as exc:
            facts("cand_alpha", successes=-1)
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_out_of_vocabulary_level_refuses_malformed(self):
        with pytest.raises(RankingRefusal) as exc:
            facts("cand_alpha", capability="EXACT")  # type: ignore[arg-type]
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_missing_admissible_flag_is_required(self):
        with pytest.raises(TypeError):
            CandidateFacts(candidate_ref="cand_alpha")  # type: ignore[call-arg]

    def test_bad_envelope_budget_refuses_malformed(self):
        for budget in (0, -1, True, "4096"):
            with pytest.raises(RankingRefusal) as exc:
                rank_candidates((facts("cand_alpha"),), max_envelope_bytes=budget)
            assert exc.value.code == MALFORMED_PAYLOAD

    def test_envelope_bound_mirrors_the_payload_discipline(self):
        from hermes.persistence.event_validation import DEFAULT_PAYLOAD_MAX_BYTES

        assert MAX_FACTS_ENVELOPE_BYTES == DEFAULT_PAYLOAD_MAX_BYTES

    def test_oversize_envelope_refuses_rationale_names_sizes_only(self):
        marker = "SECRET_MARKER_DO_NOT_ECHO"
        oversize = tuple(
            facts(f"{marker}_{index:04d}_" + "x" * 300) for index in range(20)
        )
        with pytest.raises(RankingRefusal) as exc:
            rank_candidates(oversize)
        assert exc.value.code == "RATIONALE"
        detail = exc.value.detail
        assert marker not in detail
        assert str(MAX_FACTS_ENVELOPE_BYTES) in detail
        assert exc.value.to_refusal()["rejected"] is True

    def test_envelope_budget_is_a_caller_input(self):
        oversize = tuple(
            facts(f"cand_{index:04d}_" + "x" * 300) for index in range(20)
        )
        with pytest.raises(RankingRefusal):
            rank_candidates(oversize)
        ranking = rank_candidates(oversize, max_envelope_bytes=1_000_000)
        assert len(ranking.ranking) == 20
        assert ranking.choice_ref is None  # all 20 fact profiles are identical

    def test_at_bound_envelope_passes_and_one_byte_over_refuses(self):
        candidates = (facts("cand_alpha"), facts("cand_beta"))
        exact = candidate_set_envelope_bytes(candidates)
        assert exact == candidate_set_envelope_bytes(tuple(reversed(candidates)))
        ranking = rank_candidates(candidates, max_envelope_bytes=exact)
        # The bound is a gate, not an ordering input: identity is unchanged.
        assert ranking.ranking_id == rank_candidates(candidates).ranking_id
        with pytest.raises(RankingRefusal) as exc:
            rank_candidates(candidates, max_envelope_bytes=exact - 1)
        assert exc.value.code == "RATIONALE"

    def test_count_past_the_renderable_magnitude_refuses_malformed(self):
        # O5_REDTEAM 3e: a huge non-negative int used to escape as a raw
        # ValueError from canonical_json (CPython's int-to-str limit), on a
        # surface that may only refuse with a frozen code.
        with pytest.raises(RankingRefusal) as exc:
            facts("cand_alpha", successes=10 ** 5000)
        assert exc.value.code == MALFORMED_PAYLOAD
        with pytest.raises(RankingRefusal) as exc2:
            facts("cand_alpha", failures=10 ** 5000)
        assert exc2.value.code == MALFORMED_PAYLOAD
        # refusal-as-data, and the detail never echoes the magnitude
        assert exc.value.to_refusal()["rejected"] is True
        assert len(exc.value.detail) < 500

    def test_count_bound_is_renderability_not_a_merit_bound(self):
        # at the bound the count validates and the envelope gate refuses
        # (sizes only); past it the count rule refuses. Neither is a cutoff
        # over candidate merit.
        at_bound = 10 ** MAX_FACTS_ENVELOPE_BYTES - 1
        with pytest.raises(RankingRefusal) as exc:
            rank_candidates((facts("cand_alpha", successes=at_bound),))
        assert exc.value.code == "RATIONALE"
        with pytest.raises(RankingRefusal) as exc2:
            facts("cand_alpha", successes=10 ** MAX_FACTS_ENVELOPE_BYTES)
        assert exc2.value.code == MALFORMED_PAYLOAD

    def test_ref_outside_the_grammar_refuses_malformed(self):
        # O5_REDTEAM 3f: 'cand_alpha ' was a second identity for
        # 'cand_alpha', and a ref is echoed into public outputs.
        for bad in (
            "cand_alpha ",
            " cand_alpha",
            "cand alpha",
            "cand_alpha\n",
            "cand/alpha",
        ):
            with pytest.raises(RankingRefusal) as exc:
                facts(bad)
            assert exc.value.code == MALFORMED_PAYLOAD
            assert bad not in exc.value.detail
        # the canonical forms are untouched
        assert facts("cand_alpha").candidate_ref == "cand_alpha"
        assert facts("slot:tool_7").candidate_ref == "slot:tool_7"


class TestMeasurementHarness:
    def test_pinned_shapes_measured_savings(self):
        comparison = compare_against_baseline(FIXTURES)
        measured = tuple(
            (row.task_ref, row.baseline_calls, row.ranked_calls, row.calls_saved)
            for row in comparison.tasks
        )
        assert measured == PINNED_SAVINGS

    def test_totals_are_the_sums_of_tasks(self):
        comparison = compare_against_baseline(FIXTURES)
        assert comparison.total_baseline_calls == sum(
            row.baseline_calls for row in comparison.tasks
        )
        assert comparison.total_ranked_calls == sum(
            row.ranked_calls for row in comparison.tasks
        )
        assert comparison.total_calls_saved == sum(
            row.calls_saved for row in comparison.tasks
        )
        assert comparison.total_baseline_calls == 16
        assert comparison.total_ranked_calls == 8
        assert comparison.total_calls_saved == 8

    def test_no_help_shape_provably_cannot_save(self):
        comparison = compare_against_baseline((NO_DISCRIMINATION,))
        (row,) = comparison.tasks
        assert row.baseline_calls == 1
        assert row.ranked_calls == 1
        assert row.calls_saved == 0
        assert row.choice_ref is None
        # 1 is the call floor, so against this baseline no ordering can be
        # better: ranked_calls >= 1 == baseline_calls ⇒ saved <= 0.
        assert row.ranked_calls >= 1
        assert row.calls_saved <= 0

    def test_baseline_optimal_shape_saves_nothing(self):
        comparison = compare_against_baseline((BASELINE_OPTIMAL,))
        (row,) = comparison.tasks
        assert (row.baseline_calls, row.ranked_calls, row.calls_saved) == (1, 1, 0)
        assert row.choice_ref == "cand_alpha"

    def test_misleading_facts_are_reported_as_harmful(self):
        comparison = compare_against_baseline((FACTS_MISLEADING,))
        (row,) = comparison.tasks
        assert (row.baseline_calls, row.ranked_calls, row.calls_saved) == (1, 2, -1)
        assert row.calls_saved < 0

    def test_authority_excluded_decoy_is_not_reached_first(self):
        comparison = compare_against_baseline((AUTHORITY_EXCLUDED_DECOY,))
        (row,) = comparison.tasks
        assert row.ranked_order[0] == "cand_alpha"
        assert "cand_decoy" not in row.ranked_order
        assert ("cand_decoy", "NONE") in row.classifications
        assert row.calls_saved == 2

    def test_comparison_id_is_content_addressed(self):
        comparison = compare_against_baseline(FIXTURES)
        assert comparison.comparison_id == f"rankcmp_{comparison.content_hash[:24]}"
        assert len(comparison.content_hash) == 64

    def test_comparison_versions_recorded(self):
        comparison = compare_against_baseline(FIXTURES)
        assert comparison.ranker_version == DEFAULT_RANKER_VERSION
        assert comparison.policy_version == DEFAULT_RANKING_POLICY_VERSION
        assert comparison.schema_version == RANKING_SCHEMA_VERSION

    def test_harness_is_100x_deterministic(self):
        views = {
            (
                compare_against_baseline(FIXTURES).comparison_id,
                compare_against_baseline(FIXTURES).total_calls_saved,
            )
            for _ in range(100)
        }
        assert len(views) == 1

    def test_changed_versions_change_comparison_identity(self):
        base = compare_against_baseline(FIXTURES)
        other = compare_against_baseline(FIXTURES, policy_version="tool-rank-2026.2")
        assert base.comparison_id != other.comparison_id

    def test_fixture_success_ref_must_be_admissible(self):
        malformed = FixtureTask(
            task_ref="bad",
            candidates=(facts("cand_alpha", admissible=False),),
            success_ref="cand_alpha",
        )
        with pytest.raises(RankingRefusal) as exc:
            compare_against_baseline((malformed,))
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_fixture_success_ref_must_be_present(self):
        malformed = FixtureTask(
            task_ref="bad",
            candidates=(facts("cand_alpha"),),
            success_ref="cand_missing",
        )
        with pytest.raises(RankingRefusal) as exc:
            compare_against_baseline((malformed,))
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_empty_fixture_set_refuses(self):
        with pytest.raises(RankingRefusal) as exc:
            compare_against_baseline(())
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_non_fixture_member_refuses(self):
        with pytest.raises(RankingRefusal) as exc:
            compare_against_baseline((BASELINE_OPTIMAL, "not-a-fixture"))
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_summary_is_deterministic_table(self):
        comparison = compare_against_baseline(FIXTURES)
        summary = summarize_comparison(comparison)
        assert comparison.comparison_id in summary
        assert "TOTAL" in summary
        assert summary == summarize_comparison(comparison)

    def test_results_carry_expected_dataclasses(self):
        comparison = compare_against_baseline((BASELINE_OPTIMAL,))
        assert isinstance(comparison, RankingComparison)
        assert comparison.tasks[0].baseline_order == ("cand_alpha", "cand_beta")
        assert comparison.tasks[0].ranked_order == ("cand_alpha", "cand_beta")


class TestNamingAndVocabulary:
    def test_artifact_type_name_does_not_collide_with_the_idr019_type(self):
        # O5_REDTEAM P3-4: this plane's artifact shared its name with the
        # ratified IDR-019 CandidateRanking in evaluation.py, so a static
        # scan of the bare name hit two modules. The cut is deprecation-free:
        # no alias is left behind.
        import hermes.research.evaluation as evaluation
        import hermes.research.ranking as ranking_module

        assert hasattr(ranking_module, "CandidateRankingArtifact")
        assert not hasattr(ranking_module, "CandidateRanking")
        assert "CandidateRanking" not in ranking_module.__all__
        assert "CandidateRankingArtifact" in ranking_module.__all__
        evaluation_types = {
            node.name
            for node in ast.parse(inspect.getsource(evaluation)).body
            if isinstance(node, ast.ClassDef)
        }
        assert "CandidateRanking" in evaluation_types  # IDR-019 stays
        assert "CandidateRankingArtifact" not in evaluation_types
        plane_fields = {f.name for f in fields(CandidateRankingArtifact)}
        assert "ranking_id" in plane_fields

    def test_mirrored_cost_tier_stays_value_identical(self):
        # the one shared name this plane keeps on purpose is the level
        # mirror: pinned value-identical so a level change in evaluation.py
        # cannot silently diverge from this plane's ordering vocabulary
        from hermes.research.evaluation import CostTier as EvaluationCostTier

        assert {tier.value for tier in CostTier} == {
            tier.value for tier in EvaluationCostTier
        }


class TestIntegrationPoint:
    def test_integration_point_is_named_only(self):
        assert RANKING_INTEGRATION_POINT == "hermes.agents.runtime.run:tool-phase"
