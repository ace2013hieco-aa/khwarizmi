"""TEXP-001 S4 — arm + tuning acceptance tests (single-variable, budget,
determinism; NO tuning runs — harness mechanics only).

Run: .venv/Scripts/python.exe -m pytest experiments/texp-001/test_arms.py -q
Deterministic: seeded streams only; no wall-clock, no I/O.
"""

import dataclasses

import pytest

from arms import flat_energy, make_a0, make_a1, make_a2, run_arm
from energy import SearchContext, reference_energy
from kernel import BudgetCounter, initial_path, make_rng_stream
from tuning import (N_TUNE_DEFAULT, ROBUSTNESS_MARGIN, TuningSpace,
                    robustness_fraction, sample_configs, select_best)
from validator import validate_path

CTX = SearchContext(graph_id="g-tiny")


def tiny_graph():
    def e(s, d, t):
        return {"src": s, "dst": d, "edge_type": t}
    return {
        "a": [e("a", "b", "supports"), e("a", "c", "supports"),
              e("a", "d", "entails")],
        "b": [e("b", "c", "supports"), e("b", "e", "refines")],
        "c": [e("c", "e", "supports"), e("c", "f", "entails")],
        "d": [e("d", "e", "analogous_to")],
        "e": [e("e", "f", "supports")],
        "f": [],
    }


def test_single_variable_a1_a2_differ_only_in_temperatures():
    a1 = make_a1(5.0, reference_energy, validate_path, budget=200,
                 steps=60, n_segments=4)
    a2 = make_a2(50.0, 0.9, 0.5, reference_energy, validate_path,
                 budget=200, steps=60, n_segments=4)
    assert a1.energy_fn is a2.energy_fn
    assert a1.validator_fn is a2.validator_fn
    for f in ("restart_prob", "l_max", "budget", "steps_per_segment"):
        assert getattr(a1, f) == getattr(a2, f), f
    assert a1.arm_id != a2.arm_id  # the label differs; the machinery matches
    assert a2.temperatures[0] == 50.0
    assert all(t >= 0.5 for t in a2.temperatures)
    assert list(a2.temperatures) == sorted(a2.temperatures, reverse=True)


def test_no_schedule_in_a1():
    a1 = make_a1(7.0, reference_energy, validate_path)
    assert len(set(a1.temperatures)) == 1


def test_a2_rejects_bad_hyperparameters():
    for kw in ({"alpha": 1.5}, {"alpha": 0.0}, {"t_end": 0.0},
               {"t0": -1.0}, {"n_segments": 0}):
        base = {"t0": 50.0, "alpha": 0.9, "t_end": 0.5,
                "energy": reference_energy, "validator": validate_path}
        base.update(kw)
        with pytest.raises(ValueError):
            make_a2(**base)
    with pytest.raises(ValueError):
        make_a1(0.0, reference_energy, validate_path)


def test_a0_temperature_irrelevant_no_energy():
    g = tiny_graph()

    def once(temps):
        a0 = make_a0(validate_path, budget=200, steps=60, n_segments=2)
        a0 = dataclasses.replace(a0, temperatures=temps)
        rng = make_rng_stream("g-tiny", 31)
        init = initial_path(rng, g, validate_path, 2)
        return run_arm(a0, g, init, rng, CTX)
    r1 = once((1.0,) * 2)
    r999 = once((999.0,) * 2)
    # ChainResult carries temperature, so normalize it: everything else
    # must be identical (temperature provably irrelevant to an A0 walk).
    norm = lambda segs: [dataclasses.replace(s, temperature=0.0)
                         for s in segs]
    assert norm(r1) == norm(r999)
    assert all(s.metro_rejects == 0 for s in r1)
    assert sum(s.accepted for s in r1) > 0


def test_budget_counted_identically_across_arms():
    g = tiny_graph()
    specs = [
        make_a0(validate_path, budget=150, steps=40, n_segments=2),
        make_a1(5.0, reference_energy, validate_path, budget=150,
                steps=40, n_segments=2),
        make_a2(50.0, 0.9, 0.5, reference_energy, validate_path,
                budget=150, steps=40, n_segments=2),
    ]
    for spec in specs:
        rng = make_rng_stream("g-tiny", 41)
        init = initial_path(rng, g, validate_path, 2)
        segs = run_arm(spec, g, init, rng, CTX)
        total = sum(s.budget_used for s in segs)
        assert total <= spec.budget, (spec.arm_id, total)
    assert sum(s.budget_used for s in run_arm(
        specs[0], g, initial_path(make_rng_stream("g-tiny", 41), g,
                                  validate_path, 2),
        make_rng_stream("g-tiny", 41), CTX)) > 0


def test_arms_run_end_to_end_linkage_sane():
    g = tiny_graph()
    for spec in (
            make_a1(5.0, reference_energy, validate_path, budget=120,
                    steps=30, n_segments=2),
            make_a2(50.0, 0.9, 0.5, reference_energy, validate_path,
                    budget=120, steps=30, n_segments=2)):
        rng = make_rng_stream("g-tiny", 51)
        init = initial_path(rng, g, validate_path, 2)
        segs = run_arm(spec, g, init, rng, CTX)
        assert len(segs) == 2
        for s in segs:
            assert validate_path(list(s.best_path)).accepted
            assert s.temperature in spec.temperatures


def test_tuning_determinism_and_selection():
    space = TuningSpace(arm_id="A1", ranges={"T": (1.0, 100.0)}, n_configs=5)

    def once(seed):
        import random
        return sample_configs(random.Random(seed), space)
    assert once(7) == once(7)
    assert once(7) != once(8)
    assert all(1.0 <= c["T"] <= 100.0 for c in once(7))
    scored = [({"T": 1.0}, 0.5), ({"T": 2.0}, 0.9), ({"T": 3.0}, 0.9)]
    assert select_best(scored) == {"T": 2.0}  # ties keep first
    # 0.9 - 0.85 == 0.050000000000000044 in float arithmetic, which is NOT
    # <= 0.05: the margin comparison is strict float <= (pinned here, so a
    # future reader cannot mistake it for tolerant).
    assert robustness_fraction([0.9, 0.85, 0.5]) == pytest.approx(1 / 3)
    assert robustness_fraction([0.9, 0.86, 0.5]) == pytest.approx(2 / 3)
    assert robustness_fraction([]) == 0.0
    assert N_TUNE_DEFAULT == 60 and ROBUSTNESS_MARGIN == 0.05
    with pytest.raises(ValueError):
        sample_configs(__import__("random").Random(1), TuningSpace(
            arm_id="A1", ranges={}, n_configs=5))
    with pytest.raises(ValueError):
        select_best([])


def test_tuning_imports_no_runners():
    # tuning.py is pure config math: it must not import (and therefore
    # cannot execute) arms, kernel, validator, or energy — TUNE runs at
    # P4, never from this harness.
    src = open(__file__.replace("test_arms.py", "tuning.py"),
               encoding="utf-8").read()
    for token in ("import arms", "import kernel", "import validator",
                  "import energy", "run_arm", "run_chain",
                  "reference_energy", "validate_path"):
        assert token not in src, token


def test_arms_hygiene_no_io():
    import ast
    for mod in ("arms", "tuning"):
        src = open(__file__.replace("test_arms.py", mod + ".py"),
                   encoding="utf-8").read()
        tree = ast.parse(src)
        per_mod = {"arms": {"__future__", "dataclasses", "typing",
                            "kernel"},
                   "tuning": {"__future__", "dataclasses", "typing"}}
        allowed = per_mod[mod]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] in allowed, a.name
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] in allowed, \
                    node.module
