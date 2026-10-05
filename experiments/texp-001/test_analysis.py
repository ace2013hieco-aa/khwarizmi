"""TEXP-001 S6 — analysis + lock property tests (synthetic inputs only).

Run: .venv/Scripts/python.exe -m pytest experiments/texp-001/test_analysis.py -q
All inputs are hand-built synthetic datasets (known effects) or tmp JSON
files — never generator/sampler internals (analysis must not reach back
into the machinery it judges). Deterministic: fixed seeds throughout.
"""

import json
import math

import pytest

from analysis import (decide_outcome, evaluate_guardrails, load_results,
                      methods_agree, paired_bootstrap_ci, report_effect,
                      wilcoxon_signed_rank)
from lock import (FILL, assert_all_fill, canonical_lock_block,
                  lock_block_hash, lock_template)


def test_ci_covers_known_truth():
    diffs = [0.12, 0.08] * 20  # true mean exactly 0.10
    lo, hi = paired_bootstrap_ci(diffs, seed=3)
    assert lo <= 0.10 <= hi
    assert lo < hi


def test_ci_width_shrinks_with_n():
    import random
    rng = random.Random(11)
    small = [rng.gauss(0.1, 0.1) for _ in range(20)]
    rng = random.Random(11)
    big = [rng.gauss(0.1, 0.1) for _ in range(200)]
    w_small = paired_bootstrap_ci(small, seed=5)
    w_big = paired_bootstrap_ci(big, seed=5)
    assert (w_small[1] - w_small[0]) > (w_big[1] - w_big[0])
    m = sum(big) / len(big)
    assert w_big[0] <= m <= w_big[1]  # bootstrap mean tracks sample mean


def test_ci_rejects_garbage():
    with pytest.raises(ValueError):
        paired_bootstrap_ci([])
    with pytest.raises(ValueError):
        paired_bootstrap_ci([0.1, float("nan")])


def test_wilcoxon_agrees_on_clear_effect():
    diffs = [0.12, 0.08] * 20
    lo, hi = paired_bootstrap_ci(diffs, seed=3)
    assert lo > 0
    w = wilcoxon_signed_rank(diffs)
    assert w["W-"] == 0.0 and w["W+"] > 0
    assert methods_agree(diffs, (lo, hi)) is True


def test_wilcoxon_agrees_on_null():
    diffs = [0.05, -0.05] * 20  # perfectly symmetric null
    lo, hi = paired_bootstrap_ci(diffs, seed=3)
    assert lo <= 0 <= hi
    w = wilcoxon_signed_rank(diffs)
    assert w["W+"] == w["W-"]
    assert methods_agree(diffs, (lo, hi)) is True


def test_decide_outcome_branches():
    assert decide_outcome((0.06, 0.14), True, True, 0.10) == 1
    assert decide_outcome((0.06, 0.14), False, True, 0.10) == 2
    assert decide_outcome((-0.01, 0.03), True, True, 0.01) == 2
    assert decide_outcome((-0.14, -0.06), True, True, -0.10) == 3
    assert decide_outcome((0.06, 0.14), True, True, 0.10,
                          methods_agree_flag=False) == 2  # D7 default


def test_guardrails_trip_each():
    good = {"g1_violations": 0, "g2_hub_margin": 0.05,
            "g3_dup_margin": 0.05, "g4_overhead": 1.5,
            "g5_determinism": True}
    assert evaluate_guardrails(good)["pass"] is True
    for key, bad in (("g1_violations", 1), ("g2_hub_margin", 0.06),
                     ("g3_dup_margin", 0.06), ("g4_overhead", 1.6),
                     ("g5_determinism", False), ("g5_determinism", 1)):
        rec = dict(good, **{key: bad})
        out = evaluate_guardrails(rec)
        assert out["pass"] is False, key
    assert evaluate_guardrails({})["pass"] is False  # missing fails closed
    assert "scope" in evaluate_guardrails(good)


def test_scope_stamp_on_every_output():
    diffs = [0.1] * 10
    rep = report_effect(diffs, paired_bootstrap_ci(diffs, seed=1))
    assert "synthetic typed graphs only" in rep["scope"]
    assert set(rep) == {"mean", "ci", "n", "wilcoxon", "methods_agree",
                        "scope"}  # no p-value keys exist anywhere here
    assert rep["mean"] == pytest.approx(0.1)


def test_load_results_shape_checked(tmp_path):
    good = tmp_path / "r.json"
    good.write_text(json.dumps([{"recall": 0.5}]), encoding="utf-8")
    assert load_results(str(good)) == [{"recall": 0.5}]
    bad = tmp_path / "b.json"
    bad.write_text(json.dumps({"recall": 0.5}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_results(str(bad))


def test_lock_all_fill_and_stable():
    t = lock_template()
    assert assert_all_fill(t) == []
    assert t["arms"]["A1"] == FILL and t["delta_min"] == FILL
    assert t["hold_bar"] == FILL and t["validator_agreement"] == FILL
    s1 = canonical_lock_block(t)
    rebuilt = {}
    for k in reversed(list(t)):
        rebuilt[k] = t[k]
    assert canonical_lock_block(rebuilt) == s1  # order-invariant
    h = lock_block_hash(s1)
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
    assert lock_block_hash(s1) == h  # stable


def test_lock_detects_filled_field():
    t = lock_template()
    t["delta_min"] = 0.05
    assert "delta_min" in assert_all_fill(t)
