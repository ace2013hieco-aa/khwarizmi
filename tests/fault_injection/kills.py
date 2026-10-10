"""Committed, opt-in fault-injection registry (AUDIT-P-AUTO-6 F1).

Each entry kills the SEAM that carries one deterministic envelope, at the very
attribute the envelope's own code reads, so a red leg proves the envelope is
load-bearing rather than decorative. These are the same seams the P-AUTO-6
temp plugins used (a no-op ``observe_failure`` for quarantine, a false deadline
check) plus the audit's independent rebuild (``build_loop_threshold``
inflation) - three seams, the same 3 + 1 failures.

Opt-in, twice over:

* ``HERMES_FAULT_KILL`` (comma/space separated kill names, or ``all``) selects
  the kills. Unset => this module patches NOTHING: ``selected()`` is empty,
  ``apply()`` refuses with ``FAULT_KILL_NOT_ENABLED``, and the default suite is
  pristine by construction.
* Selection is SCOPED to the file that owns the envelope claims
  (``Kill.claim_file``), so ``HERMES_FAULT_KILL=quarantine python -m pytest
  -p tests.fault_injection.plugin tests`` reddens exactly that file's
  envelope tests and leaves the rest of the suite green.
  NOTE: the ``-p tests.fault_injection.plugin`` flag is load-bearing — the
  plugin is deliberately NOT wired into ``tests/conftest.py`` and never
  loads implicitly, so without ``-p`` the env flag alone greens vacuously
  (exit 0, nothing patched).

Refusals are named (the repo's refusal-as-data convention):

* ``UNKNOWN_FAULT_KILL`` - a name outside the closed registry.
* ``FAULT_KILL_NOT_ENABLED`` - an in-process apply without the env opt-in.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

import pytest

FLAG = "HERMES_FAULT_KILL"
UNKNOWN_FAULT_KILL = "UNKNOWN_FAULT_KILL"
FAULT_KILL_NOT_ENABLED = "FAULT_KILL_NOT_ENABLED"

# The file whose tests make the envelope claims these kills disprove.
CLAIM_FILE = "tests/test_p_auto_6_loop.py"

QUARANTINE_RED_LEGS = (
    f"{CLAIM_FILE}::test_poison_task_quarantined_never_retried_silently",
    f"{CLAIM_FILE}::test_loop_pattern_trips_detector_at_threshold_and_quarantines",
    f"{CLAIM_FILE}::test_recovery_after_quarantine_legit_work_proceeds_and_idle_is_named",
)
DEADLINE_RED_LEGS = (
    f"{CLAIM_FILE}::test_hung_fetch_deadline_fires_typed_transient_no_hang",
)


def _kill_quarantine(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op the quarantine observer (the P-AUTO-6 temp-plugin seam)."""
    from hermes.research.autonomy_caps import LoopDetector

    monkeypatch.setattr(LoopDetector, "observe_failure",
                        lambda self, task_id, signature: "")


def _kill_loop_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inflate the loop threshold the controller builds (audit rebuild seam)."""
    from hermes.research import controller as controller_module

    monkeypatch.setattr(controller_module, "build_loop_threshold",
                        lambda operator=None: 10 ** 9)


def _kill_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the D1 deadline CHECK SITE (value still computed/threaded)."""
    from hermes.tools.providers import paginate

    monkeypatch.setattr(paginate, "_deadline_expired",
                        lambda deadline, clock: False)


@dataclass(frozen=True, slots=True)
class Kill:
    """One envelope seam that can be disabled, with its claim footprint."""

    name: str
    envelope: str
    seam: str
    claim_file: str
    apply: Callable[[pytest.MonkeyPatch], None]
    red_legs: tuple[str, ...]


ENVELOPE_KILLS: dict[str, Kill] = {
    "quarantine": Kill(
        name="quarantine",
        envelope="loop poison/quarantine (LoopDetector.observe_failure)",
        seam="src/hermes/research/autonomy_caps.py:424 LoopDetector.observe_failure",
        claim_file=CLAIM_FILE,
        apply=_kill_quarantine,
        red_legs=QUARANTINE_RED_LEGS,
    ),
    "loop_threshold": Kill(
        name="loop_threshold",
        envelope="loop repeat threshold (controller build_loop_threshold)",
        seam="src/hermes/research/controller.py:760 build_loop_threshold",
        claim_file=CLAIM_FILE,
        apply=_kill_loop_threshold,
        red_legs=QUARANTINE_RED_LEGS,
    ),
    "deadline": Kill(
        name="deadline",
        envelope="D1 dispatch deadline (paginate check site)",
        seam="src/hermes/tools/providers/paginate.py:181 _deadline_expired",
        claim_file=CLAIM_FILE,
        apply=_kill_deadline,
        red_legs=DEADLINE_RED_LEGS,
    ),
}


def known() -> tuple[str, ...]:
    """The closed registry's kill names (deterministic order)."""
    return tuple(sorted(ENVELOPE_KILLS))


def refuse_unknown(names: tuple[str, ...] | list[str]) -> None:
    """Raise ``UNKNOWN_FAULT_KILL`` for any name outside the registry."""
    unknown = sorted({name for name in names if name not in ENVELOPE_KILLS})
    if unknown:
        raise ValueError(
            f"{UNKNOWN_FAULT_KILL}: {unknown} are not in the closed "
            f"registry - known kills: {list(known())}")


def selected() -> tuple[str, ...]:
    """The kills ``HERMES_FAULT_KILL`` selects (empty when unset/blank)."""
    raw = os.environ.get(FLAG, "")
    names = [part.strip().lower() for part in raw.replace(",", " ").split()]
    names = [name for name in names if name]
    if not names:
        return ()
    if names == ["all"]:
        return known()
    refuse_unknown(names)
    return tuple(dict.fromkeys(names))


def apply(monkeypatch: pytest.MonkeyPatch, *names: str) -> tuple[str, ...]:
    """Apply kills to ``monkeypatch``; refused without the env opt-in.

    Explicit names must ALSO be env-selected, so no test can silently kill an
    envelope on a default run: the harness is never on by default.
    """
    requested = tuple(names) if names else selected()
    refuse_unknown(requested)
    enabled = selected()
    refused = [name for name in requested if name not in enabled]
    if refused:
        raise ValueError(
            f"{FAULT_KILL_NOT_ENABLED}: {refused} - set {FLAG}="
            f"{','.join(requested)} to opt in (the harness is never on by "
            f"default)")
    for name in requested:
        ENVELOPE_KILLS[name].apply(monkeypatch)
    return requested


def scoped(names: tuple[str, ...], nodeid: str) -> bool:
    """True when ``nodeid`` belongs to an owning file of a selected kill."""
    return any(nodeid.startswith(ENVELOPE_KILLS[name].claim_file)
               for name in names)


# The session's kill patches (see ``begin``/``end``), applied per scoped test.
_PATCH: pytest.MonkeyPatch | None = None


def begin(nodeid: str) -> tuple[str, ...]:
    """Apply the selected kills for a scoped test; a no-op otherwise.

    Called from the conftest hook before each test. With the flag unset this
    is one dict lookup and zero patches.
    """
    global _PATCH
    names = selected()
    if not names or _PATCH is not None or not scoped(names, nodeid):
        return ()
    patch = pytest.MonkeyPatch()
    _PATCH = patch
    return apply(patch, *names)


def end() -> None:
    """Undo whatever ``begin`` applied (no-op when nothing was applied)."""
    global _PATCH
    if _PATCH is not None:
        _PATCH.undo()
        _PATCH = None
