"""Cross-cutting pipeline invariants — true regardless of which slice landed.

Every other test file in this tree tests one slice's claim. This file tests the
properties that must hold *whatever* changed, because the failures this project
has actually suffered were never "slice N broke slice N-1" — they were one
layer disagreeing with another about a value, and no per-slice test was looking.

Three of these were once known to fail; the observation and experiment
content rules have since landed, so only the conclusion-over-an-empty-middle
hole remains. Each hole is marked ``xfail(strict=True)`` separately — one
marker covering two holes let a partial fix leave the other one untested while
the suite went green: the suite stays green, the hole is recorded, and when
someone fixes it the strict marker turns into a failure that forces its own
removal. That is the point — a hole with a marker cannot be forgotten, and
cannot be quietly declared fixed.

The list, and why each one earns a place:

1. **A claim is never supported by a non-fetched artifact.** OPS-5Y's ``D(C)``.
2. **A claim with no admitted evidence refuses exactly as it always has.** The
   narrowing must not have replaced the old rule.
3. **Every refusal code the substrate emits is declared.** A code a consumer
   cannot branch on is a refusal that is not data.
4. **Every field the contract declares reaches the prompt.** A field the
   renderer drops is one the model is never told about while the validator
   still refuses its absence — the OPS-5Z shape.
5. **No chain kind accepts an empty node.** *The observation and experiment
   rules landed in turn; the conclusion hole below is the remaining middle.*
6. **A conclusion drawn over an empty middle is refused.** *Known to fail: the
   completeness check reads kinds, never content.*
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "src/hermes/agents/runtime/profiles"
RATCHET = ROOT / "docs/STRUCTURE-RATCHET.json"

# The venv installs `hermes` editable against the *main* checkout, so a bare
# import in a worktree silently tests a different branch — a defect injected
# into this tree's substrate.py passed the suite. Put this tree first.
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import structure_map  # noqa: E402  # pyright: ignore[reportMissingImports]

from hermes.agents.runtime.config import load_profiles  # noqa: E402
from hermes.agents.runtime.run import output_contract_for  # noqa: E402
from hermes.methodology import substrate as S  # noqa: E402
from hermes.methodology import workflows as W  # noqa: E402
from hermes.tools.models.cloud import render_system  # noqa: E402
from hermes.tools.models.router import _contract_mapping  # noqa: E402
from tests.test_methodology_plane import (  # noqa: E402
    PROJECT_ID,
    REFS,
    _build_chain,
    _fresh,
)

# 0 ─────────────────────────────────────────────────────────────────────────

def test_the_suite_imports_this_tree_not_another_checkout() -> None:
    """A gate that tests someone else's branch is worse than no gate.

    The venv installs `hermes` editable against the main checkout, so before
    this guard a defect injected into *this* tree's substrate passed the whole
    suite while the code under test came from a different branch.
    """
    # Checked in a *fresh* interpreter, so the answer does not depend on which
    # module happened to import `hermes` first. In a worktree that shares the
    # venv's editable install, the answer is "the main checkout" unless
    # PYTHONPATH puts this tree's src first — and then a full-suite run from
    # here is not evidence about this tree.
    probe = subprocess.run(
        [sys.executable, "-c",
         "import hermes.methodology.substrate as s; print(s.__file__)"],
        capture_output=True, text=True, encoding="utf-8", timeout=120)
    loaded = Path(probe.stdout.strip()).resolve()
    assert ROOT.resolve() in loaded.parents, (
        f"hermes resolves to {loaded}, outside {ROOT} — the suite is testing "
        f"another checkout. Run with PYTHONPATH={ROOT / 'src'}")


def _claim(ids: dict[str, str], admitted: tuple[str, ...]) -> S.SubstrateNode:    return S.SubstrateNode(
        kind="CLAIM", project_id=PROJECT_ID, producing_task_id="t-claim",
        content={"statement": "the observed sample supports the effect",
                 "origin": "MINTED",
                 "admitted_refs": admitted,
                 "predecessors": (ids["EVIDENCE"],)},
        rationale="r")


# 1 ─────────────────────────────────────────────────────────────────────────

def test_a_claim_is_never_supported_by_a_non_fetched_artifact() -> None:
    """D(C): a ROW-backed admission cannot anchor a claim."""
    store = _fresh(evidence_backing="ROW")
    ids = _build_chain(store, stop_at="EVIDENCE")
    recorded = S.write_node(store, _claim(ids, (REFS["EVIDENCE"],)))
    assert isinstance(recorded, S.SubstrateRefusal), (
        "a claim anchored only by a non-fetched artifact was recorded")
    assert recorded.code == S.UNSUPPORTED_CLAIM


# 2 ─────────────────────────────────────────────────────────────────────────

def test_a_claim_without_admitted_evidence_refuses_as_it_always_has() -> None:
    """The narrowing adds a rule; it does not replace the old one."""
    store = _fresh(evidence_backing="FETCHED")
    ids = _build_chain(store, stop_at="EVIDENCE")
    recorded = S.write_node(store, _claim(ids, ()))
    assert isinstance(recorded, S.SubstrateRefusal)
    assert recorded.code == S.UNSUPPORTED_CLAIM
    assert "chain position, not support" in recorded.detail


# 3 ─────────────────────────────────────────────────────────────────────────

def test_every_refusal_code_the_substrate_emits_is_declared() -> None:
    """A refusal code outside the vocabulary is one no consumer can branch on."""
    source = Path(S.__file__).read_text(encoding="utf-8")
    emitted = set(re.findall(r"_refuse\(\s*(?:\n\s*)?([A-Z][A-Z_]{2,})", source))
    undeclared = sorted(emitted - set(S.SUBSTRATE_REFUSAL_CODES))
    assert not undeclared, f"emitted but not declared: {undeclared}"


# 4 ─────────────────────────────────────────────────────────────────────────

def test_every_declared_field_reaches_the_prompt() -> None:
    """A field the renderer drops is one the model is never told about."""
    missing: dict[str, list[str]] = {}
    for name, spec in sorted(load_profiles(directory=PROFILES).items()):
        contract = output_contract_for(spec)
        mapping = _contract_mapping(contract)
        text = (render_system(name, mapping) if mapping else "").lower()
        absent = [f.name for f in contract.fields if f.name.lower() not in text]
        if absent:
            missing[name] = absent
    assert not missing, f"declared but not rendered: {missing}"


# 5 ─────────────────────────────────────────────────────────────────────────

def test_an_empty_experiment_is_refused() -> None:
    """The stage whose job is 'describe the discriminating test' records nothing."""
    store = _fresh(evidence_backing="FETCHED")
    ids = _build_chain(store, stop_at="PREDICTION")
    recorded = S.write_node(store, S.SubstrateNode(
        kind="EXPERIMENT", project_id=PROJECT_ID, producing_task_id="t",
        content={"predecessors": (ids["PREDICTION"],)}, rationale="r"))
    assert isinstance(recorded, S.SubstrateRefusal), (
        "an EXPERIMENT node recorded with no content")
    assert recorded.code == S.MALFORMED_PAYLOAD
    assert "test" in recorded.detail


def test_a_well_formed_experiment_carries_its_test() -> None:
    """The complement: a node that names its test is recorded, and the test
    survives on the node — a rule that refuses everything would be no rule."""
    store = _fresh(evidence_backing="FETCHED")
    ids = _build_chain(store, stop_at="PREDICTION")
    recorded = S.write_node(store, S.SubstrateNode(
        kind="EXPERIMENT", project_id=PROJECT_ID, producing_task_id="t",
        content={"test": "run the measurement on a larger sample",
                 "predecessors": (ids["PREDICTION"],)}, rationale="r"))
    assert isinstance(recorded, str), recorded
    assert store.nodes[recorded].content["test"] == (
        "run the measurement on a larger sample")


def test_an_empty_observation_is_refused() -> None:
    """An observation that cites nothing still counts as a recorded stage."""
    store = _fresh(evidence_backing="FETCHED")
    ids = _build_chain(store, stop_at="EXPERIMENT")
    recorded = S.write_node(store, S.SubstrateNode(
        kind="OBSERVATION", project_id=PROJECT_ID, producing_task_id="t",
        content={"predecessors": (ids["EXPERIMENT"],)}, rationale="r"))
    assert isinstance(recorded, S.SubstrateRefusal), (
        "an OBSERVATION node recorded with no content")


@pytest.mark.xfail(
    strict=True,
    reason="_support_refusal's CONCLUSION branch compares node kinds, never "
           "content, so a conclusion records over a chain whose experiment and "
           "observation recorded nothing. The third-party audit drove this "
           "end-to-end; this test is that drive. Fix the check, delete the "
           "marker.")
def test_a_conclusion_over_an_empty_middle_is_refused() -> None:
    """Completeness by kind presence is not completeness."""
    store = _fresh(evidence_backing="FETCHED")
    ids = _build_chain(store, stop_at="CRITIQUE")
    recorded = S.write_node(store, S.SubstrateNode(
        kind="CONCLUSION", project_id=PROJECT_ID, producing_task_id="t",
        content={"question_ref": ids["QUESTION"],
                 "predecessors": (ids["CRITIQUE"],)},
        rationale="r"))
    assert isinstance(recorded, S.SubstrateRefusal), (
        "a CONCLUSION recorded over a chain with an empty EXPERIMENT and "
        "OBSERVATION")


# 7 ─────────────────────────────────────────────────────────────────────────

def test_no_new_layer_edge_or_cycle_since_the_ratchet() -> None:
    """The structural gate, enforced from pytest as well as the script.

    A new cross-layer edge is a boundary that did not exist yesterday, and a
    contract disagreement needs one to travel along. Nothing else in this suite
    looks at imports, so a change that quietly couples two layers would pass
    every other test in the tree.
    """
    if not RATCHET.exists():
        pytest.skip("no structural ratchet recorded")
    ratchet = json.loads(RATCHET.read_text(encoding="utf-8"))
    report = structure_map.build(ROOT / "src/hermes")
    delta = structure_map.compare(report, ratchet)
    assert not delta["new_edges"], (
        f"new layer edge(s) since the ratchet: {delta['new_edges']} — record "
        f"it with --allow \"<reason>\" or remove the import")
    assert not delta["new_cycles"], (
        f"new cycle(s) since the ratchet: {delta['new_cycles']} — two "
        f"subsystems just became one")


# 8 ─────────────────────────────────────────────────────────────────────────

def test_the_minting_stages_and_the_non_minting_stages_share_profiles() -> None:
    """The premise OPS-5Z rests on: a per-profile flag cannot express the rule.

    If this ever stops being true, the stage-conditional design loses its
    justification and the next reader should know.
    """
    by_profile: dict[str, set[str]] = {}
    for stage in W.LITERATURE_REVIEW_DOCUMENT["stages"]:
        by_profile.setdefault(stage["profile"], set()).add(stage["stage"])
    shared = {profile: stages for profile, stages in by_profile.items()
              if len(stages) > 1}
    assert shared, (
        "no profile serves two stages; the stage-conditional requirement may "
        "now be expressible per profile")
    minting = set(W.MINTED_NODE_KINDS) if hasattr(W, "MINTED_NODE_KINDS") else set()
    if minting:
        for profile, stages in shared.items():
            assert not (stages <= minting or not stages & minting), (
                f"profile {profile} serves only one side of the split: "
                f"{sorted(stages)}")
