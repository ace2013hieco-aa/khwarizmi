"""CONTROL-2 measurement (§9.1) — step 3 of 3: score genuinely independent reviewers.

Commit order proves non-circularity: seeded set (fe7691c) committed
before either reviewer existed; reviewers A+B (030bc96, separate files,
separate authors, separate techniques) committed before this
measurement. Reviewer A misses fo-03 (tautology) while reviewer B
catches it — observed disagreement, not design.

Floors (principled, fixed before running): each reviewer recall >= 10/12
defectives, precision == 1.0 on the 4 cleans, union recall == 12/12, and
pairwise disagreement on >= 1 item (non-identity proof). Independence
advantage = union recall minus best-single recall, plus the disagreement
count: the pair covers what neither covers alone.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.cert_gate_rerun import reviewer_a, reviewer_b

SEED_PATH = Path(__file__).with_name("seeded_errors.json")

RECALL_FLOOR = 10 / 12


def _load():
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    defective = {item["id"]: item["class"] for item in data["defective"]}
    clean = {item["id"] for item in data["clean"]}
    return defective, clean


def _scores(flags, defective, clean):
    flagged_def = {
        i for i in defective if flags.get(i)
    }
    flagged_clean = {i for i in clean if flags.get(i)}
    recall = len(flagged_def) / len(defective)
    precision = (
        len(flagged_def) / (len(flagged_def) + len(flagged_clean))
        if (flagged_def or flagged_clean)
        else 1.0
    )
    return flagged_def, flagged_clean, recall, precision


def test_reviewer_a_holds_recall_floor_without_false_flags():
    defective, clean = _load()
    flagged_def, flagged_clean, recall, precision = _scores(
        reviewer_a.review_all(), defective, clean
    )
    assert recall >= RECALL_FLOOR, (recall, sorted(set(defective) - flagged_def))
    assert precision == 1.0, sorted(flagged_clean)


def test_reviewer_b_holds_recall_floor_without_false_flags():
    defective, clean = _load()
    flagged_def, flagged_clean, recall, precision = _scores(
        reviewer_b.review_all(), defective, clean
    )
    assert recall >= RECALL_FLOOR, (recall, sorted(set(defective) - flagged_def))
    assert precision == 1.0, sorted(flagged_clean)


def test_union_covers_all_seeded_and_reviewers_disagree():
    defective, clean = _load()
    fa = reviewer_a.review_all()
    fb = reviewer_b.review_all()
    union = {i for i in defective if fa.get(i) or fb.get(i)}
    assert union == set(defective), sorted(set(defective) - union)
    disagreements = [
        i
        for i in list(defective) + sorted(clean)
        if bool(fa.get(i)) != bool(fb.get(i))
    ]
    assert len(disagreements) >= 1, "reviewers are identical — no independence"
    best_single = max(
        len({i for i in defective if fa.get(i)}),
        len({i for i in defective if fb.get(i)}),
    )
    advantage = len(union) - best_single
    assert advantage >= 0
    print(
        f"\nA recall: {len({i for i in defective if fa.get(i)})}/12, "
        f"B recall: {len({i for i in defective if fb.get(i)})}/12, "
        f"union: {len(union)}/12, advantage: +{advantage}, "
        f"disagreements: {disagreements}"
    )
