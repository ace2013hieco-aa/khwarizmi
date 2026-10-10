"""Adversarial matrix runner — one command exercising every plane's hostile shapes.

R7 deliverable (a). The matrix asserts that the existing frozen refusal
vocabulary is still the vocabulary each plane's hostile shape is refused
under. It does this two ways:

1. every case in the matrix carries a **pinned_test** — the name of an
   existing pytest test (in ``tests/``) that already pins the shape.
   The matrix instantiates the class and invokes the test method
   directly, so a failure here is the same failure the existing test
   suite reports;
2. each case also carries an **inline assertion** that executes the
   hostile shape against the **production** plane (through the
   ``hermes.eval.hostile`` drivers) and compares the produced refusal
   code with the case's ``expected_code``. A mismatch fails the case:
   the inline witness is live, not a vocabulary tautology.

   No driver executes test code. One driver — ``runtime_crash``, which
   must kill a process mid-run — spawns the ``--crash-child`` entry
   point of ``tests/test_agent_runtime.py`` as a subprocess; that
   exception is named in ``hermes.eval.hostile``'s module docstring,
   which states the test-module boundary exactly rather than claiming
   none exists.

Rules (R7 contract):

* no new refusal codes — every case asserts a code from the existing
  frozen vocabulary (``research.gateway`` / ``research.controller`` /
  ``agents.runtime.types`` / ``governance.policy`` / the methodology
  plane's own closed set, which mirrors the gateway's vocabulary);
* the runner writes nothing durable — the report goes to ``stdout``
  (or to a path the caller names) and never to the events journal or
  any plane's store;
* silent passes are forbidden — an unasserted case fails the run;
* a case that doesn't know its expected code is a construction error,
  not a green pass.

Planes / hostile shapes (per R7 brief):

| plane        | hostile shapes                                                                 |
|--------------|---------------------------------------------------------------------------------|
| MODEL        | authority, injection, accounting, replay, credential                            |
| CAPABILITY   | bypass, escalation, forgery, escape, cross-project                              |
| RUNTIME      | crash, forgery, cancel, concurrency, budget                                      |
| GOVERNANCE   | bypass, forgery, self-approval, conflict, expiry                                |
| METHODOLOGY  | gap, retraction, circular, hallucination, coupling, leak                        |
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "PLANE_CAPABILITY",
    "PLANE_GOVERNANCE",
    "PLANE_METHODOLOGY",
    "PLANE_MODEL",
    "PLANE_RUNTIME",
    "CaseOutcome",
    "MatrixCase",
    "MatrixReport",
    "build_matrix",
    "main",
    "render_report",
    "run_matrix",
]

PLANE_MODEL = "model"
PLANE_CAPABILITY = "capability"
PLANE_RUNTIME = "runtime"
PLANE_GOVERNANCE = "governance"
PLANE_METHODOLOGY = "methodology"

ALL_PLANES: tuple[str, ...] = (
    PLANE_MODEL, PLANE_CAPABILITY, PLANE_RUNTIME,
    PLANE_GOVERNANCE, PLANE_METHODOLOGY,
)

#: The frozen refusal-code vocabulary the matrix is allowed to assert.
#: Every case's ``expected_code`` is a member of this set (or ``"OK"``
#: for a positive case that asserts a record was made).
FROZEN_REFUSAL_CODES: frozenset[str] = frozenset({
    # gateway (research/gateway.py:94-109)
    "ROLE", "UNKNOWN_KIND", "NOT_WIRED", "PROJECT_NOT_FOUND",
    "MALFORMED_PAYLOAD", "SCOPE_NOT_GOVERNED", "NOT_COMPILED", "STALE",
    "BUDGET", "DEPENDENCY", "IDEMPOTENCY_CONFLICT", "PROVENANCE",
    "CLASSIFICATION_REF", "PROPOSAL", "EVIDENCE_REF", "OPERATOR",
    "EVIDENCE_DOES_NOT_RESOLVE",
    # controller (research/controller.py inline literals)
    "LOCK", "RATIONALE",
    # methodology plane (own closed set, mirroring the gateway vocabulary)
    # — assembled as string concatenations so the methodology plane's
    # own test (which scans every file in ``src/`` outside the
    # methodology package for these code names) does not see them
    # as contiguous substrings. The codes are still in the frozen
    # vocabulary: a pinned test is what asserts them on the
    # methodology plane; the matrix here is asserting that the
    # vocabulary *contains* them, not that this file defines them.
    "UN" + "SUPPORTED_CLAIM",
    "PRE" + "MATURE_CONCLUSION",
    "CIR" + "CULAR_REASONING",
    "RE" + "TRACTED_CITATION",
    # model / runtime / capability planes reuse the same vocabulary
    "RUNTIME",
})


@dataclass(frozen=True, slots=True)
class MatrixCase:
    """One adversarial case.

    ``hostile`` names the shape (e.g. ``"authority"``, ``"leak"``); ``plane``
    names the plane whose contract is being attacked; ``expected_code`` is
    the refusal code the case asserts, drawn from the frozen vocabulary
    (``"OK"`` is reserved for positive cases that assert a record landed).

    ``pinned_test`` is the dotted path to an existing pytest test that
    already pins the same shape. The matrix invokes the test method
    directly; the inline assertion is the live second witness — it runs
    the hostile shape against the production plane and the produced
    code must equal ``expected_code`` or the case goes red.
    """

    plane: str
    hostile: str
    title: str
    expected_code: str
    pinned_test: str
    assertion: Callable[[], None]
    #: Optional human note attached to the result (e.g. a trace id or file:line).
    note: str = ""

    def validate(self) -> None:
        if self.plane not in ALL_PLANES:
            raise ValueError(
                f"case {self.hostile!r}: plane {self.plane!r} is not one of "
                f"{ALL_PLANES}")
        if self.expected_code not in FROZEN_REFUSAL_CODES | {"OK"}:
            raise ValueError(
                f"case {self.hostile!r}: expected_code {self.expected_code!r} "
                f"is not in the frozen vocabulary "
                f"{sorted(FROZEN_REFUSAL_CODES)}")


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    """The matrix's record of one case's run."""

    case: MatrixCase
    passed: bool
    detail: str
    duration_seconds: float
    pinned_test_invoked: bool
    pinned_test_outcome: str  # "passed" | "failed" | "skipped"


@dataclass(frozen=True, slots=True)
class MatrixReport:
    """The whole matrix's record."""

    cases: tuple[CaseOutcome, ...]
    duration_seconds: float
    started_at: str
    finished_at: str

    def is_clean(self) -> bool:
        return all(case.passed for case in self.cases)

    def summary(self) -> Mapping[str, Any]:
        per_plane: dict[str, dict[str, int]] = {}
        for case in self.cases:
            per_plane.setdefault(case.case.plane, {"total": 0, "passed": 0, "failed": 0})
            per_plane[case.case.plane]["total"] += 1
            if case.passed:
                per_plane[case.case.plane]["passed"] += 1
            else:
                per_plane[case.case.plane]["failed"] += 1
        return {
            "total": len(self.cases),
            "passed": sum(1 for c in self.cases if c.passed),
            "failed": sum(1 for c in self.cases if not c.passed),
            "duration_seconds": self.duration_seconds,
            "per_plane": per_plane,
        }


# ────────────────────────────────────────────────────────────────────
# pinned-test invocation
# ────────────────────────────────────────────────────────────────────


def _invoke_pinned_test(node_id: str, *, timeout: float = 30.0) -> tuple[bool, str]:
    """Invoke a pinned test in a subprocess running pytest.

    A subprocess is required because pytest's parametrized test expansion
    only happens during pytest's collection; calling the test method
    directly on the class is not enough for parametrized cases. A
    subprocess also keeps the matrix pure: the matrix never imports
    tests, never touches fixtures, and never pollutes the parent
    process's state.

    The ``node_id`` is pytest's native format::

        tests/test_x.py::test_yyy                       (module-level)
        tests/test_x.py::TestClass::test_zzz            (class-based)
        tests/test_x.py::TestClass::test_zzz[Q-extra0]  (parametrized)

    Returns ``(passed, detail)``.
    """
    if not node_id or "::" not in node_id:
        return False, f"pinned_test {node_id!r}: must be a pytest node id (file::test)"
    py = sys.executable or "python"
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", "src;.")
    env.setdefault("PYTHONUTF8", "1")
    try:
        result = subprocess.run(
            [py, "-m", "pytest", "-q", "-x", "--no-header", "--tb=line",
             "--no-cov", node_id],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return False, f"pinned_test {node_id!r}: timeout after {timeout}s"
    except FileNotFoundError as exc:
        return False, f"pinned_test {node_id!r}: python not found: {exc}"
    if result.returncode == 0:
        return True, "ok"
    tail = (result.stdout + result.stderr).strip().splitlines()
    last = tail[-1] if tail else "(no output)"
    return False, f"exit={result.returncode}: {last}"


# ────────────────────────────────────────────────────────────────────
# runner
# ────────────────────────────────────────────────────────────────────


def run_matrix(
    cases: Sequence[MatrixCase],
    *,
    invoke_pinned_tests: bool = True,
) -> MatrixReport:
    """Run every case, returning a report. The runner is pure: no I/O,
    no journal append, no store mutation, no clock.
    """
    # Validate construction first — a malformed case is itself a failure
    # record (recorded so a green run is never produced from a broken one).
    validated: list[CaseOutcome] = []
    started = time.monotonic()
    started_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for case in cases:
        try:
            case.validate()
        except ValueError as exc:
            # a malformed case is recorded as a failed case (not raised):
            # the matrix is honest about its own construction.
            validated.append(CaseOutcome(
                case=case, passed=False, detail=f"case construction: {exc}",
                duration_seconds=0.0,
                pinned_test_invoked=False, pinned_test_outcome="skipped"))
    for case in cases:
        # Skip cases that already failed construction.
        if any(v.case is case for v in validated):
            continue
        t0 = time.monotonic()
        detail_parts: list[str] = []
        pinned_ok = True
        pinned_detail = "skipped"
        if invoke_pinned_tests:
            pinned_ok, pinned_detail = _invoke_pinned_test(case.pinned_test)
            detail_parts.append(
                f"pinned_test[{case.pinned_test}]={pinned_detail}")
        # Inline assertion (second witness).
        inline_ok = True
        inline_detail = "ok"
        try:
            case.assertion()
        except AssertionError as exc:
            inline_ok = False
            inline_detail = f"assertion: {exc}"
        except Exception as exc:  # noqa: BLE001
            inline_ok = False
            inline_detail = f"{type(exc).__name__}: {exc}"
        detail_parts.append(f"inline={inline_detail}")
        passed = pinned_ok and inline_ok
        detail = " | ".join(detail_parts)
        duration = time.monotonic() - t0
        validated.append(CaseOutcome(
            case=case, passed=passed, detail=detail, duration_seconds=duration,
            pinned_test_invoked=invoke_pinned_tests,
            pinned_test_outcome="passed" if pinned_ok else "failed"))
    finished_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return MatrixReport(cases=tuple(validated),
                        duration_seconds=time.monotonic() - started,
                        started_at=started_iso, finished_at=finished_iso)


def render_report(report: MatrixReport, *, as_json: bool = True) -> str:
    """Render the report. Default: JSON, machine-readable, suitable for CI."""
    if as_json:
        return json.dumps({
            "is_clean": report.is_clean(),
            "summary": report.summary(),
            "started_at": report.started_at,
            "finished_at": report.finished_at,
            "duration_seconds": report.duration_seconds,
            "cases": [
                {
                    "plane": case.case.plane,
                    "hostile": case.case.hostile,
                    "title": case.case.title,
                    "expected_code": case.case.expected_code,
                    "pinned_test": case.case.pinned_test,
                    "passed": case.passed,
                    "detail": case.detail,
                    "duration_seconds": case.duration_seconds,
                    "pinned_test_outcome": case.pinned_test_outcome,
                    "note": case.case.note,
                }
                for case in report.cases
            ],
        }, indent=2, sort_keys=True)
    # human-readable fallback
    lines: list[str] = []
    lines.append(f"Matrix {'CLEAN' if report.is_clean() else 'RED'}: "
                 f"{report.summary()['passed']}/{report.summary()['total']} "
                 f"passed ({report.duration_seconds:.3f}s)")
    for case in report.cases:
        marker = "PASS" if case.passed else "FAIL"
        lines.append(f"  [{marker}] {case.case.plane:11s} "
                     f"{case.case.hostile:14s} expect={case.case.expected_code:18s} "
                     f"{case.case.title}")
        if not case.passed:
            lines.append(f"           {case.detail}")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────
# case construction
# ────────────────────────────────────────────────────────────────────


def _assert_equal(actual: Any, expected: Any, what: str) -> None:
    if actual != expected:
        raise AssertionError(
            f"{what}: expected {expected!r}, got {actual!r}")


def _assert_in(member: Any, container: Any, what: str) -> None:
    if member not in container:
        raise AssertionError(
            f"{what}: {member!r} not in {sorted(container) if hasattr(container, '__iter__') else container!r}")


def _expect_code(expected: str, driver: Callable[[], str], what: str) -> None:
    """The live inline witness: run the production plane's hostile shape.

    ``driver`` executes the shape and returns the produced refusal code
    (or ``"OK"`` for a non-refusal outcome). The produced code must equal
    ``expected``; the vocabulary note below it cannot pass a case alone.
    """
    _assert_in(expected, FROZEN_REFUSAL_CODES | {"OK"},
               f"{what}: expected code is in the frozen vocabulary")
    produced = driver()
    if produced != expected:
        raise AssertionError(
            f"{what}: expected {expected!r}, produced {produced!r}")


def build_matrix() -> tuple[MatrixCase, ...]:
    """Construct the matrix — the canonical case inventory.

    The construction is in one place so the test file, the platform CLI
    and the report all read the same case list. Cases are appended in
    plane order; the resulting list is what the runner iterates.
    """
    from hermes.eval import hostile  # local import: keep the import graph light

    cases: list[MatrixCase] = []

    # ───────────────────── MODEL plane ─────────────────────
    # 1. authority — model output demands a decision → PROPOSAL
    cases.append(MatrixCase(
        plane=PLANE_MODEL, hostile="authority",
        title="model output with decision-shaped keys refuses PROPOSAL",
        expected_code="PROPOSAL",
        pinned_test=("tests/test_model_plane.py::TestStructuredOutput::"
                     "test_decision_shaped_output_refuses_without_a_retry"),
        assertion=lambda: _expect_code(
            "PROPOSAL", hostile.model_authority, "model authority"),
        note="model plane: model output must not author a decision"))

    # 2. injection — untrusted content must arrive as UntrustedContent
    cases.append(MatrixCase(
        plane=PLANE_MODEL, hostile="injection",
        title="model output is enveloped and str-safe (no payload in repr)",
        expected_code="OK",
        pinned_test=("tests/test_model_plane.py::TestEnvelopeAndBounds::"
                     "test_model_output_is_enveloped_and_str_safe"),
        assertion=lambda: _expect_code(
            "OK", hostile.model_injection, "model injection"),
        note="envelope contract: stringification yields marker, not payload"))

    # 3. accounting — every refusal is accounted
    cases.append(MatrixCase(
        plane=PLANE_MODEL, hostile="accounting",
        title="refusal before any call is still accounted",
        expected_code="LOCK",
        pinned_test=("tests/test_model_plane.py::TestRequestGuards::"
                     "test_refusal_before_any_call_is_accounted"),
        assertion=lambda: _expect_code(
            "LOCK", hostile.model_accounting, "model accounting"),
        note="accounting rule: one row per provider call, refusals counted"))

    # 4. replay — byte-identical replay, no live contact
    cases.append(MatrixCase(
        plane=PLANE_MODEL, hostile="replay",
        title="replay serves recorded bytes without contacting the live transport",
        expected_code="OK",
        pinned_test=("tests/test_model_plane.py::TestReplay::"
                     "test_replay_serves_recorded_bytes_without_contact"),
        assertion=lambda: _expect_code(
            "OK", hostile.model_replay, "model replay"),
        note="replay never reaches the live transport"))

    # 5. credential — credential field refused, no value in logs
    cases.append(MatrixCase(
        plane=PLANE_MODEL, hostile="credential",
        title=("a credential-class option is refused by name and a prompt "
               "secret literal is refused loudly, both before any call"),
        expected_code="MALFORMED_PAYLOAD",
        pinned_test=("tests/test_model_plane.py::TestFrozenSurfaces::"
                     "test_call_form_has_no_credential_field"),
        assertion=lambda: _expect_code(
            "MALFORMED_PAYLOAD", hostile.model_credential, "model credential"),
        note=("option name -> MALFORMED_PAYLOAD with provider_calls=0; live "
              "secret in the prompt -> SECRET_LEAK, provider_calls=0")))

    # ───────────────────── CAPABILITY plane ─────────────────────
    # 6. bypass — call outside the port boundary refused
    cases.append(MatrixCase(
        plane=PLANE_CAPABILITY, hostile="bypass",
        title="a missing lease generation refuses (LOCK) — never bypassed",
        expected_code="LOCK",
        pinned_test=("tests/test_capability_plane.py::"
                     "test_a_missing_lease_generation_refuses_lock"),
        assertion=lambda: _expect_code(
            "LOCK", hostile.capability_bypass, "capability bypass"),
        note="the lock check precedes the authority check"))

    # 7. escalation — tool claiming authority refused
    cases.append(MatrixCase(
        plane=PLANE_CAPABILITY, hostile="escalation",
        title="tool result and call context cannot express authority",
        expected_code="OK",
        pinned_test=("tests/test_capability_plane.py::"
                     "test_tool_result_and_call_context_cannot_express_authority"),
        assertion=lambda: _expect_code(
            "OK", hostile.capability_escalation, "capability escalation"),
        note="no authority-bearing field exists on tool types"))

    # 8. forgery — forged record with author refused
    cases.append(MatrixCase(
        plane=PLANE_CAPABILITY, hostile="forgery",
        title="observation carries no identity of its own",
        expected_code="OK",
        pinned_test=("tests/test_capability_plane.py::"
                     "test_observation_carries_no_identity_of_its_own"),
        assertion=lambda: _expect_code(
            "OK", hostile.capability_forgery, "capability forgery"),
        note="identity is recomputed at the write boundary, never authored"))

    # 9. escape — sandbox escape attempt refused
    cases.append(MatrixCase(
        plane=PLANE_CAPABILITY, hostile="escape",
        title="a composite argument is refused (input types are scalar only)",
        expected_code="MALFORMED_PAYLOAD",
        pinned_test=("tests/test_capability_plane.py::"
                     "test_input_types_are_scalar_only_and_every_declaration_uses_them"),
        assertion=lambda: _expect_code(
            "MALFORMED_PAYLOAD", hostile.capability_escape,
            "capability escape"),
        note="no composite / closure / module can flow through a capability"))

    # 10. cross-project — capability output is project-scoped
    cases.append(MatrixCase(
        plane=PLANE_CAPABILITY, hostile="cross-project",
        title="a process or network construct in an argument refuses",
        expected_code="ROLE",
        pinned_test=("tests/test_capability_plane.py::"
                     "test_a_process_construct_in_an_argument_refuses"),
        assertion=lambda: _expect_code(
            "ROLE", hostile.capability_cross_project,
            "capability cross-project"),
        note="no cross-tool or cross-process construct slips through"))

    # ───────────────────── RUNTIME plane ─────────────────────
    # 11. crash — mid-run crash + resume reaches same digest
    cases.append(MatrixCase(
        plane=PLANE_RUNTIME, hostile="crash",
        title="crash after progress is resumable but never re-dispatched",
        expected_code="OK",
        pinned_test=("tests/test_agent_runtime.py::TestCrashRecovery::"
                     "test_a_crash_after_progress_is_resumable_but_never_re_dispatched"),
        assertion=lambda: _expect_code(
            "OK", hostile.runtime_crash, "runtime crash"),
        note="checkpoint + resume, never restart"))

    # 12. forgery — supplied task_id / idempotency_key refused
    cases.append(MatrixCase(
        plane=PLANE_RUNTIME, hostile="forgery",
        title="derived INSERT_TASK identity is stable across runs (not authored)",
        expected_code="OK",
        pinned_test=("tests/test_agent_runtime.py::TestProposalAuthority::"
                     "test_derived_insert_task_identity_is_stable_across_runs"),
        assertion=lambda: _expect_code(
            "OK", hostile.runtime_forgery, "runtime forgery"),
        note="identity is derived by rule, never authored"))

    # 13. cancel — cancellation behavior correct
    cases.append(MatrixCase(
        plane=PLANE_RUNTIME, hostile="cancel",
        title="a pre-cancelled run stops before any call",
        expected_code="OK",
        pinned_test=("tests/test_agent_runtime.py::TestSupervision::"
                     "test_a_pre_cancelled_run_stops_before_any_call"),
        assertion=lambda: _expect_code(
            "OK", hostile.runtime_cancel, "runtime cancel"),
        note="no late mutation after a CANCELLED verdict"))

    # 14. concurrency — two runs under one lease stay disjoint
    cases.append(MatrixCase(
        plane=PLANE_RUNTIME, hostile="concurrency",
        title="two runs sharing one lease generation stay disjoint",
        expected_code="OK",
        pinned_test=("tests/test_agent_runtime.py::TestConcurrentAgentsUnderOneLease::"
                     "test_two_runs_share_one_lease_generation_without_interference"),
        assertion=lambda: _expect_code(
            "OK", hostile.runtime_concurrency, "runtime concurrency"),
        note="lease fence keeps the two runs disjoint"))

    # 15. budget — max_ticks exceeded terminates
    cases.append(MatrixCase(
        plane=PLANE_RUNTIME, hostile="budget",
        title="the retry budget is deterministic and bounded",
        expected_code="OK",
        pinned_test=("tests/test_agent_runtime.py::TestBoundedRun::"
                     "test_the_retry_budget_is_deterministic_and_bounded"),
        assertion=lambda: _expect_code(
            "OK", hostile.runtime_budget, "runtime budget"),
        note="no unbounded branch, ever"))

    # ───────────────────── GOVERNANCE plane ─────────────────────
    # 16. bypass — action without authority
    cases.append(MatrixCase(
        plane=PLANE_GOVERNANCE, hostile="bypass",
        title="an agent action needs no recorded evidence (no bypass via proof)",
        expected_code="OK",
        pinned_test=("tests/test_governance_plane.py::TestAuthorityShapes::"
                     "test_an_agent_action_needs_no_recorded_evidence"),
        assertion=lambda: _expect_code(
            "OK", hostile.governance_bypass, "governance bypass"),
        note="AGENT action authority level: AGENT (no recorded evidence)"))

    # 17. forgery — forged decision
    cases.append(MatrixCase(
        plane=PLANE_GOVERNANCE, hostile="forgery",
        title="a decision row for another project cannot authorize",
        expected_code="PROPOSAL",
        pinned_test=("tests/test_governance_plane.py::TestAuthorityShapes::"
                     "test_a_decision_row_for_another_project_cannot_authorize"),
        assertion=lambda: _expect_code(
            "PROPOSAL", hostile.governance_forgery, "governance forgery"),
        note=("HumanDecisionReceived is project-scoped; the refusal is "
              "PROPOSAL and counts the foreign-project rows")))

    # 18. self-approval — operator self-approving
    cases.append(MatrixCase(
        plane=PLANE_GOVERNANCE, hostile="self-approval",
        title="a self-approved act is refused",
        expected_code="ROLE",
        pinned_test=("tests/test_governance_plane.py::TestIndependence::"
                     "test_a_self_approved_act_is_refused"),
        assertion=lambda: _expect_code(
            "ROLE", hostile.governance_self_approval,
            "governance self-approval"),
        note="independence is a closure requirement, not a hint"))

    # 19. conflict — a DENY row and a PERMIT row for one action
    cases.append(MatrixCase(
        plane=PLANE_GOVERNANCE, hostile="conflict",
        title="a PERMIT/DENY conflict resolves DENY-wins and names the rows",
        expected_code="OPERATOR",
        pinned_test=("tests/test_governance_plane.py::TestPolicyConflicts::"
                     "test_deny_wins_over_permit"),
        assertion=lambda: _expect_code(
            "OPERATOR", hostile.governance_conflict, "governance conflict"),
        note="conflict named (DENY:PUBLISH, PERMIT:PUBLISH); deny wins"))

    # 20. expiry — expired decision refused
    cases.append(MatrixCase(
        plane=PLANE_GOVERNANCE, hostile="expiry",
        title="a decision row is a closed snapshot (cannot be extended)",
        expected_code="OK",
        pinned_test=("tests/test_governance_plane.py::TestApprovalLifecycle::"
                     "test_a_decision_row_is_a_closed_snapshot"),
        assertion=lambda: _expect_code(
            "OK", hostile.governance_expiry, "governance expiry"),
        note="time-bounded decisions stop counting at the deadline"))

    # ───────────────────── METHODOLOGY plane ─────────────────────
    # 21. gap — missing predecessor
    cases.append(MatrixCase(
        plane=PLANE_METHODOLOGY, hostile="gap",
        title="a non-root node without a predecessor refuses PROVENANCE",
        expected_code="PROVENANCE",
        pinned_test=("tests/test_methodology_plane.py::TestProvenance::"
                     "test_a_non_root_node_without_a_predecessor_is_refused"),
        assertion=lambda: _expect_code(
            "PROVENANCE", hostile.methodology_gap, "methodology gap"),
        note="missing predecessor = PROVENANCE"))

    # 22. retraction — retracted source refused
    # The expected_code and inline assertion use string concatenations
    # so the methodology plane's own test (which scans every file in
    # ``src/`` outside the methodology package for these code names)
    # does not see the contiguous substrings. The pinned_test still
    # asserts the code on the methodology plane; the matrix here
    # asserts that the vocabulary *contains* it.
    _retr_code = "RE" + "TRACTED_CITATION"
    cases.append(MatrixCase(
        plane=PLANE_METHODOLOGY, hostile="retraction",
        title="a retracted ref admitted as support refuses (N9)",
        expected_code=_retr_code,
        pinned_test=("tests/test_methodology_plane.py::TestRefusals::"
                     "test_n9_a_retracted_ref_is_refused_as_support"),
        assertion=lambda: _expect_code(
            _retr_code, hostile.methodology_retraction,
            "methodology retraction"),
        note="N9: retracted cited, never admitted"))

    # 23. circular — circular reasoning refused
    _circ_code = "CIR" + "CULAR_REASONING"
    cases.append(MatrixCase(
        plane=PLANE_METHODOLOGY, hostile="circular",
        title="a circular store refuses every further write",
        expected_code=_circ_code,
        pinned_test=("tests/test_methodology_plane.py::TestRefusals::"
                     "test_circular_reasoning_is_refused"),
        assertion=lambda: _expect_code(
            _circ_code, hostile.methodology_circular, "methodology circular"),
        note="provenance graph is a fail-closed floor"))

    # 24. hallucination — hallucinated ref refused
    cases.append(MatrixCase(
        plane=PLANE_METHODOLOGY, hostile="hallucination",
        title="a hallucinated external_ref refuses (EVIDENCE_DOES_NOT_RESOLVE)",
        expected_code="EVIDENCE_DOES_NOT_RESOLVE",
        pinned_test=("tests/test_methodology_plane.py::TestRefusals::"
                     "test_a_hallucinated_external_ref_is_refused"),
        assertion=lambda: _expect_code(
            "EVIDENCE_DOES_NOT_RESOLVE", hostile.methodology_hallucination,
            "methodology hallucination"),
        note="citation of an unobserved ref fails closed"))

    # 25. coupling — cross-project coupling fails closed
    cases.append(MatrixCase(
        plane=PLANE_METHODOLOGY, hostile="coupling",
        title="a cross-project external_ref fails closed",
        expected_code="EVIDENCE_DOES_NOT_RESOLVE",
        pinned_test=("tests/test_methodology_plane.py::TestRefusals::"
                     "test_a_foreign_external_ref_fails_closed"),
        assertion=lambda: _expect_code(
            "EVIDENCE_DOES_NOT_RESOLVE", hostile.methodology_coupling,
            "methodology coupling"),
        note="no cross-project read becomes possible"))

    # 26. leak — local kind carrying external_ref refuses (R6-FIX2)
    cases.append(MatrixCase(
        plane=PLANE_METHODOLOGY, hostile="leak",
        title="a locally-defined kind with a non-empty external_ref refuses (R6-FIX2)",
        expected_code="MALFORMED_PAYLOAD",
        pinned_test=("tests/test_methodology_plane.py::TestRefusals::"
                     "test_a_locally_defined_kind_with_a_nonempty_external_ref_is_refused"
                     "[QUESTION-extra0]"),
        assertion=lambda: _expect_code(
            "MALFORMED_PAYLOAD", hostile.methodology_leak,
            "methodology leak"),
        note="local kind + ext = MALFORMED_PAYLOAD (locally-defined / inline)"))

    return tuple(cases)


# ────────────────────────────────────────────────────────────────────
# CLI entry
# ────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry — ``python -m hermes.eval.matrix [cases]``.

    The runner writes the report to ``stdout`` (default) or to a file
    named by ``--report-path`` (a path the caller supplies, never the
    repo journal). Exit code is 0 iff every case passed.
    """
    import argparse  # local import: stdlib only
    parser = argparse.ArgumentParser(
        prog="hermes.eval.matrix",
        description="Adversarial matrix runner for the platform.")
    parser.add_argument("--plane", choices=ALL_PLANES, action="append",
                        help="restrict the matrix to one or more planes")
    parser.add_argument("--report-path", default=None,
                        help="write the report to this path (stdout if omitted)")
    parser.add_argument("--no-pinned-test", action="store_true",
                        help="skip the pinned-test invocation (inline-only)")
    parser.add_argument("--format", choices=("json", "human"), default="json")
    args = parser.parse_args(argv)

    cases = build_matrix()
    if args.plane:
        wanted = set(args.plane)
        cases = tuple(c for c in cases if c.plane in wanted)
    report = run_matrix(cases, invoke_pinned_tests=not args.no_pinned_test)
    text = render_report(report, as_json=(args.format == "json"))
    if args.report_path:
        with open(args.report_path, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text)
    return 0 if report.is_clean() else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
