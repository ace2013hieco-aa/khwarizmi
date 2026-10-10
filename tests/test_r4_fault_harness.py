"""Guard battery for the committed fault registry (AUDIT-P-AUTO-6 F1 / R-4).

Proves the harness contract itself so the red legs in
``tests/test_p_auto_6_loop.py`` can never be silently re-disarmed:

* default OFF is the real default: ``selected()`` is empty and naming a kill
  refuses (``FAULT_KILL_NOT_ENABLED``) unless ``HERMES_FAULT_KILL`` opts in;
* the registry is CLOSED: unknown names refuse
  (``UNKNOWN_FAULT_KILL``), before a single test runs;
* each kill really kills its seam (asserted on the observable effect, not
  just on a call);
* kills stay SCOPED to their claim file, so ``HERMES_FAULT_KILL=all
  python -m pytest -p tests.fault_injection.plugin tests`` can only redden
  the claims, never the rest of the suite (NOTE: the ``-p`` flag is
  load-bearing — without it the env flag alone greens vacuously);
* the four red-leg nodeids still exist in the claim file.

Runs green BOTH ways: with the flag unset (the default suite) and inside a
``HERMES_FAULT_KILL=all`` suite -- this file's nodeids are outside the claim
file, so the plugin patches nothing while these tests run.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.fault_injection import kills

CLAIM = "tests/test_p_auto_6_loop.py"

# Documented seam locations: a source move must fail here, loudly.
SEAMS = {
    "quarantine": "autonomy_caps.py:424",
    "loop_threshold": "controller.py:760",
    "deadline": "paginate.py:181",
}


@pytest.fixture()
def flag_off(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Force the opt-in flag unset for the test, restoring it afterwards."""
    monkeypatch.delenv(kills.FLAG, raising=False)
    return monkeypatch


def test_default_off_selects_nothing_and_patches_nothing(
        flag_off: pytest.MonkeyPatch) -> None:
    assert kills.selected() == ()
    assert kills.apply(flag_off) == ()
    assert kills.begin(CLAIM + "::test_poison_task_quarantined_never_retried_silently") == ()
    assert kills._PATCH is None  # asserting the inert path
    from hermes.research.autonomy_caps import LOOP_PATTERN_QUARANTINED, LoopDetector
    detector = LoopDetector(repeat_threshold=1)
    assert detector.observe_failure("t", "boom") == LOOP_PATTERN_QUARANTINED


def test_default_off_refuses_an_explicit_kill(
        flag_off: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match=kills.FAULT_KILL_NOT_ENABLED):
        kills.apply(flag_off, "quarantine")
    flag_off.setenv(kills.FLAG, "deadline")
    with pytest.raises(ValueError, match=kills.FAULT_KILL_NOT_ENABLED):
        kills.apply(flag_off, "quarantine")


def test_unknown_names_refuse_loudly(flag_off: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match=kills.UNKNOWN_FAULT_KILL):
        kills.refuse_unknown(["bogus"])
    flag_off.setenv(kills.FLAG, "bogus,deadline")
    with pytest.raises(ValueError, match=kills.UNKNOWN_FAULT_KILL):
        kills.selected()


def test_selection_parsing(flag_off: pytest.MonkeyPatch) -> None:
    flag_off.setenv(kills.FLAG, " deadline,quarantine ")
    assert kills.selected() == ("deadline", "quarantine")
    flag_off.setenv(kills.FLAG, "ALL")
    assert kills.selected() == kills.known()
    flag_off.setenv(kills.FLAG, "   ")
    assert kills.selected() == ()


def test_registry_is_closed_and_pinned(flag_off: pytest.MonkeyPatch) -> None:
    assert kills.known() == ("deadline", "loop_threshold", "quarantine")
    assert set(kills.ENVELOPE_KILLS) == set(kills.known())
    for name, kill in kills.ENVELOPE_KILLS.items():
        assert kill.name == name
        assert kill.claim_file == CLAIM
        assert SEAMS[name] in kill.seam
        assert kill.red_legs
        assert all(leg.startswith(CLAIM + "::") for leg in kill.red_legs)


def test_quarantine_kill_noops_the_observer(flag_off: pytest.MonkeyPatch) -> None:
    from hermes.research.autonomy_caps import LoopDetector
    flag_off.setenv(kills.FLAG, "quarantine")
    assert kills.apply(flag_off, "quarantine") == ("quarantine",)
    assert LoopDetector(repeat_threshold=1).observe_failure("t", "boom") == ""


def test_loop_threshold_kill_inflates_the_threshold(
        flag_off: pytest.MonkeyPatch) -> None:
    from hermes.research import controller
    assert controller.build_loop_threshold() < 10 ** 9
    flag_off.setenv(kills.FLAG, "loop_threshold")
    assert kills.apply(flag_off, "loop_threshold") == ("loop_threshold",)
    assert controller.build_loop_threshold() == 10 ** 9


def test_deadline_kill_disables_the_check_site(
        flag_off: pytest.MonkeyPatch) -> None:
    from hermes.tools.providers import paginate

    class Clock:
        @staticmethod
        def monotonic() -> float:
            return 100.0

    assert paginate._deadline_expired(50.0, Clock) is True
    flag_off.setenv(kills.FLAG, "deadline")
    assert kills.apply(flag_off, "deadline") == ("deadline",)
    assert paginate._deadline_expired(50.0, Clock) is False


def test_kills_are_scoped_to_their_claim_file() -> None:
    assert kills.scoped(("quarantine", "deadline"), CLAIM + "::test_x") is True
    assert kills.scoped(
        ("quarantine",),
        "tests/test_r4_fault_harness.py::test_kills_are_scoped_to_their_claim_file",
    ) is False


@pytest.mark.parametrize(
    "nodeid", kills.QUARANTINE_RED_LEGS + kills.DEADLINE_RED_LEGS)
def test_red_leg_nodeids_exist_in_the_claim_file(nodeid: str) -> None:
    claim_path = Path(__file__).resolve().parent / "test_p_auto_6_loop.py"
    tree = ast.parse(claim_path.read_text(encoding="utf-8"))
    functions = {node.name for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
    _, _, test_name = nodeid.partition("::")
    assert test_name in functions
