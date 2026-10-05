"""TEXP-001 S3 — kernel acceptance tests (fixed-T chain, budget, seams).

Run: .venv/Scripts/python.exe -m pytest experiments/texp-001/test_kernel.py -q
Deterministic: seeded streams only; no wall-clock, no I/O.
"""

import pytest

from energy import SearchContext, reference_energy
from kernel import (
    BudgetCounter,
    BudgetOverrun,
    ChainConfig,
    initial_path,
    make_rng_stream,
    propose,
    run_chain,
)
from validator import validate_path

CTX = SearchContext(graph_id="g-tiny")


def E(path):
    return {"edge_type": path}


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


def cfg(**kw):
    args = {"temperature": 10.0, "budget": 500, "l_max": 2,
            "restart_prob": 0.0, "max_steps": 200}
    args.update(kw)
    return ChainConfig(**args)


def test_fixed_t_chain_end_to_end_vs_s1_s2():
    g = tiny_graph()
    rng = make_rng_stream("g-tiny", 1)
    init = initial_path(rng, g, validate_path, 2)
    assert validate_path(init).accepted
    res = run_chain(rng, init, g, validate_path, reference_energy, CTX,
                    BudgetCounter(500), cfg())
    assert res.accepted > 0
    assert validate_path(list(res.best_path)).accepted
    assert res.best_energy == float(len(res.best_path))
    assert not res.truncated


def test_counter_counts_rejected_and_restarts_exact():
    c = BudgetCounter(7)
    rng = make_rng_stream("g-tiny", 1)
    g = tiny_graph()
    init = initial_path(rng, g, validate_path, 2)
    res = run_chain(rng, init, g, validate_path, reference_energy, CTX,
                    c, cfg(restart_prob=1.0, max_steps=100))
    # initial eval (1) + 3 steps x (1 spend + 1 eval) = 7; 4th step sees
    # used == budget and truncates.
    assert (res.steps, res.restarts, res.accepted) == (3, 3, 0)
    assert res.budget_used == 7 and res.truncated


def test_counter_overrun_raises():
    c = BudgetCounter(2)
    c.evaluate(reference_energy, [E("supports")], CTX)
    c.evaluate(reference_energy, [E("supports")], CTX)
    with pytest.raises(BudgetOverrun):
        c.evaluate(reference_energy, [E("supports")], CTX)
    with pytest.raises(BudgetOverrun):
        c.spend(1)


def test_same_seed_byte_identical():
    g = tiny_graph()

    def once():
        rng = make_rng_stream("g-tiny", 9)
        init = initial_path(rng, g, validate_path, 2)
        return run_chain(rng, init, g, validate_path, reference_energy,
                         CTX, BudgetCounter(500), cfg())
    assert once() == once()


def test_different_streams_diverge():
    g = tiny_graph()

    def once(seed):
        rng = make_rng_stream("g-tiny", seed)
        init = initial_path(rng, g, validate_path, 2)
        return run_chain(rng, init, g, validate_path, reference_energy,
                         CTX, BudgetCounter(500), cfg())
    assert once(1) != once(2)


def test_streams_independent_by_construction():
    a = make_rng_stream("g1", 1)
    b = make_rng_stream("g1", 1)
    c = make_rng_stream("g1", 2)
    d = make_rng_stream("g1", 1, stream="restart")
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]
    assert [a.random() for _ in range(5)] != [c.random() for _ in range(5)]
    assert [a.random() for _ in range(5)] != [d.random() for _ in range(5)]


def test_kernel_never_touches_validator_internals():
    import re
    src = open(__file__.replace("test_kernel.py", "kernel.py"),
               encoding="utf-8").read()
    for token in ("EDGE_ALPHABET", "ADMISSIBLE_SEQUENCES",
                  "import validator", "from validator",
                  "VALIDATOR_PROVENANCE"):
        assert token not in src, token
def test_no_schedule_mechanism():
    import re
    src = open(__file__.replace("test_kernel.py", "kernel.py"),
               encoding="utf-8").read()
    for token in ("anneal", "cooling", "schedule", "alpha", "T_end", "T0"):
        assert re.search(r"\b" + token + r"\b", src) is None, token


def test_temperature_must_be_positive():
    g = tiny_graph()
    rng = make_rng_stream("g-tiny", 1)
    init = initial_path(rng, g, validate_path, 2)
    for bad in (0, 0.0, -1.5):
        with pytest.raises(ValueError):
            run_chain(rng, init, g, validate_path, reference_energy, CTX,
                      BudgetCounter(50), cfg(temperature=bad))


def test_lmax_enforced_and_metro_rejects_counted():
    g = tiny_graph()
    rng = make_rng_stream("g-tiny", 3)
    for _ in range(30):
        out = propose(rng, [{"src": "a", "dst": "b", "edge_type": "supports"}],
                      g, validate_path, 2)
        if out is not None:
            assert len(out) <= 2
            assert validate_path(out).accepted
    rng2 = make_rng_stream("g-tiny", 4)
    init = initial_path(rng2, g, validate_path, 2)
    res = run_chain(rng2, init, g, validate_path, reference_energy, CTX,
                    BudgetCounter(500), cfg(temperature=1e-9))
    assert res.metro_rejects > 0
    assert len(res.best_path) <= 2


def test_energies_in_memory_floats_only():
    import ast
    src = open(__file__.replace("test_kernel.py", "kernel.py"),
               encoding="utf-8").read()
    tree = ast.parse(src)
    allowed = {"__future__", "dataclasses", "hashlib", "math", "typing",
               "random"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] in allowed, a.name
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] in allowed, node.module
    g = tiny_graph()
    rng = make_rng_stream("g-tiny", 5)
    init = initial_path(rng, g, validate_path, 2)
    res = run_chain(rng, init, g, validate_path, reference_energy, CTX,
                    BudgetCounter(300), cfg())
    assert isinstance(res.best_energy, float)
