"""TEXP-001 S2 — energy acceptance tests (blindness, determinism, finiteness,
C5 non-persistence).

Run: .venv/Scripts/python.exe -m pytest experiments/texp-001/test_energy.py -q
Deterministic: no RNG, no clock, no I/O.
"""

import math

import pytest

import energy as E
from energy import SearchContext, reference_energy


def ctx():
    return SearchContext(graph_id="g1")


def test_lengths_order_paths():
    assert reference_energy([], ctx()) == 0.0
    assert reference_energy([{"edge_type": "supports"}], ctx()) == 1.0
    assert reference_energy(
        [{"edge_type": "supports"}, {"edge_type": "entails"}], ctx()) == 2.0


def test_blindness_label_extras_ignored():
    clean = [{"edge_type": "supports"}, {"edge_type": "entails"}]
    smuggled = [dict(edge_type="supports", planted=True, label="bridge-7",
                      ground_truth=1),
                dict(edge_type="entails", is_hit=True)]
    assert reference_energy(smuggled, ctx()) == reference_energy(clean, ctx())


def test_blindness_context_rejects_label_kwargs():
    with pytest.raises(TypeError):
        SearchContext(graph_id="g1", planted=["p1"])  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        reference_energy([{"edge_type": "supports"}], object())


def test_deterministic_repeated_calls_agree():
    path = [{"edge_type": "refines"}, {"edge_type": "supports"}]
    assert reference_energy(path, ctx()) == reference_energy(path, ctx())


def test_finiteness_and_float():
    for n in (0, 1, 100):
        v = reference_energy([{"edge_type": "supports"}] * n, ctx())
        assert isinstance(v, float) and math.isfinite(v)


def test_malformed_path_raises_not_silent():
    with pytest.raises(TypeError):
        reference_energy(["supports"], ctx())
    with pytest.raises(TypeError):
        reference_energy("supports", ctx())


def test_c5_no_io_surface():
    import ast
    tree = ast.parse(open(E.__file__, encoding="utf-8").read())
    allowed_roots = {"__future__", "dataclasses", "typing"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] in allowed_roots, a.name
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] in allowed_roots, \
                node.module
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {
                "open", "print", "input", "exit", "quit", "compile",
                "eval", "exec", "__import__"}, node.func.id
