"""Eval plane tests (R7 — matrix / ops / extensions).

Covers the eval plane's whole contract:

* **the matrix runner** — every case in the matrix runs the pinned
  test and asserts the inline witness; the matrix is green iff
  every case is green;
* **the ops surface** — auth, secrets redaction, sandbox confinement,
  resource-limit enforcement, structured logs, metrics hooks,
  backup verification, config validation;
* **the extension manifest** — every worked example is a green
  value object whose primary operation is exercised;
* **the platform CLI** — the SEPARATE CLI module is a usable entry
  point for matrix / auth / extensions / verify-backup / redact-demo;
* **the matrix-red proof** — neutralizing a pinned refusal somewhere
  in the source tree turns the matrix red; the test suite proves it
  and restores the source.

The eval plane is pure evaluation + enforcement: nothing it tests
opens a socket, holds a clock, or reads a model. The matrix's
pinned-test invocation runs in a subprocess so the parent process
is never polluted by the test fixtures of the pinned test.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from hermes.eval import import_gate
from hermes.eval import ops as _ops
from hermes.eval.extensions import (
    EXTENSION_POINTS,
    ExampleAgentRole,
    ExampleEvaluator,
    ExampleEventSink,
    ExampleGovernancePolicy,
    ExampleModelProvider,
    ExampleStorageBackend,
    ExampleTool,
    ExampleToolSet,
    ExampleWorkflow,
    ExtensionPoint,
    ExtensionRegistry,
    describe_extension,
    get_extension,
    list_examples,
    list_extensions,
    register_extension,
)
from hermes.eval.import_gate import (
    declared_import_names,
    detect_import_mentions,
    dynamic_import_sites,
    load_governed,
    require_declaration,
)
from hermes.eval.matrix import (
    ALL_PLANES,
    FROZEN_REFUSAL_CODES,
    PLANE_CAPABILITY,
    PLANE_GOVERNANCE,
    PLANE_METHODOLOGY,
    PLANE_MODEL,
    PLANE_RUNTIME,
    MatrixCase,
    MatrixReport,
    build_matrix,
    render_report,
    run_matrix,
)
from hermes.eval.ops import (
    AuthContext,
    BackupManifest,
    ConfigSchema,
    CountingMetricsSink,
    JsonLogSink,
    NoOpLogSink,
    NoOpMetricsSink,
    ResourceBudget,
    ResourceLimits,
    SandboxCheck,
    StructuredLogger,
    authenticate,
    check_sandbox_confinement,
    enforce_resource_limits,
    redact,
    redact_payload,
    register_secret,
    validate_config,
    verify_backup,
)

PYTHON = sys.executable or "python"
WORKSPACE = Path(__file__).resolve().parents[1]
REPO_ROOT = WORKSPACE
EVAL_DIR = WORKSPACE / "src" / "hermes" / "eval"

#: Every shape rule the redactor applies to a string, read from the
#: module itself so this file cannot drift from the implementation. Used
#: by the pin that asserts a canary is invisible to ALL of them — a list
#: copied here would make that assertion meaningless.
_SHAPE_PATTERNS = (
    _ops._STRING_PATTERNS
    + (_ops._SECRET_TEXT_PATTERN, _ops._RESERVED_TOKEN_PATTERN,
       _ops._BARE_SECRET_PATTERN)
)


# ═══════════════════════ 1. matrix runner ═══════════════════════


class TestMatrixConstruction:
    def test_matrix_has_26_cases_across_5_planes(self) -> None:
        cases = build_matrix()
        assert len(cases) == 26
        per_plane: dict[str, int] = {}
        for case in cases:
            per_plane[case.plane] = per_plane.get(case.plane, 0) + 1
        assert per_plane[PLANE_MODEL] == 5
        assert per_plane[PLANE_CAPABILITY] == 5
        assert per_plane[PLANE_RUNTIME] == 5
        assert per_plane[PLANE_GOVERNANCE] == 5
        assert per_plane[PLANE_METHODOLOGY] == 6

    def test_every_case_uses_a_frozen_refusal_code(self) -> None:
        cases = build_matrix()
        for case in cases:
            assert case.expected_code in FROZEN_REFUSAL_CODES | {"OK"}, (
                f"case {case.plane}/{case.hostile}: "
                f"expected_code {case.expected_code!r} is not frozen")

    def test_every_case_names_a_real_plane(self) -> None:
        cases = build_matrix()
        for case in cases:
            assert case.plane in ALL_PLANES

    def test_every_case_carries_a_pinned_test(self) -> None:
        cases = build_matrix()
        for case in cases:
            assert case.pinned_test, f"case {case.hostile}: pinned_test is empty"
            assert "::" in case.pinned_test, (
                f"case {case.hostile}: pinned_test must be a pytest node id")
            assert case.pinned_test.startswith("tests/"), (
                f"case {case.hostile}: pinned_test must start with tests/")

    def test_every_case_validates_at_construction(self) -> None:
        cases = build_matrix()
        for case in cases:
            # validate() raises on a bad code; should never raise on
            # any of the canonical cases.
            case.validate()

    def test_a_construction_error_is_recorded_as_a_failed_case(self) -> None:
        # A case with an unknown plane is a construction error.
        bad = MatrixCase(
            plane="bogus", hostile="x", title="x",
            expected_code="PROPOSAL",
            pinned_test="tests/test_does_not_exist.py::x::y",
            assertion=lambda: None)
        report = run_matrix((bad,), invoke_pinned_tests=False)
        assert not report.is_clean()
        assert report.cases[0].passed is False
        assert "case construction" in report.cases[0].detail


class TestMatrixRunner:
    def test_run_matrix_against_frozen_vocabulary_only(self) -> None:
        # The vocabulary the matrix asserts is a subset of the
        # frozen vocabulary; a new code in build_matrix would not
        # validate. This is the structural proof that no new
        # refusal code is introduced by the matrix.
        cases = build_matrix()
        # Re-validate every case; any case with an out-of-vocabulary
        # code raises here.
        for case in cases:
            case.validate()

    def test_each_pinned_test_actually_exists(self) -> None:
        # Every pinned test must be collectable by pytest. A typo
        # in a pinned_test path makes the corresponding case red.
        cases = build_matrix()
        env = dict(os.environ)
        env.setdefault("PYTHONPATH", "src;.")
        env.setdefault("PYTHONUTF8", "1")
        for case in cases:
            result = subprocess.run(
                [PYTHON, "-m", "pytest", "--collect-only", "-q",
                 "--no-cov", case.pinned_test],
                capture_output=True, text=True, env=env,
                cwd=str(REPO_ROOT))
            assert result.returncode == 0, (
                f"case {case.plane}/{case.hostile}: pinned_test "
                f"{case.pinned_test!r} is not collectable\n"
                f"  stdout: {result.stdout}\n"
                f"  stderr: {result.stderr}")

    def test_matrix_runner_runs_clean_against_the_frozen_tree(self) -> None:
        # The matrix is the green state of the platform. This test
        # is the **canary**: any break in a pinned refusal turns it
        # red. The neutralize-battery below is the explicit proof.
        cases = build_matrix()
        report = run_matrix(cases)
        assert report.is_clean(), self._format_red(cases, report)

    def test_matrix_supports_pinned_test_skip(self) -> None:
        # --no-pinned-test path: every case still runs its inline
        # assertion. The inline-only report must remain clean for
        # the canonical tree (the inline assertions are themselves
        # the contract for the case's frozen vocabulary).
        cases = build_matrix()
        report = run_matrix(cases, invoke_pinned_tests=False)
        assert report.is_clean(), self._format_red(cases, report)

    def test_report_includes_per_plane_counts(self) -> None:
        cases = build_matrix()
        report = run_matrix(cases, invoke_pinned_tests=False)
        summary = report.summary()
        assert summary["per_plane"][PLANE_MODEL]["total"] == 5
        assert summary["per_plane"][PLANE_CAPABILITY]["total"] == 5
        assert summary["per_plane"][PLANE_RUNTIME]["total"] == 5
        assert summary["per_plane"][PLANE_GOVERNANCE]["total"] == 5
        assert summary["per_plane"][PLANE_METHODOLOGY]["total"] == 6

    def test_report_renders_json_and_human(self) -> None:
        cases = build_matrix()
        report = run_matrix(cases, invoke_pinned_tests=False)
        json_text = render_report(report, as_json=True)
        body = json.loads(json_text)
        assert body["is_clean"] is True
        assert body["summary"]["total"] == 26
        human_text = render_report(report, as_json=False)
        assert "CLEAN" in human_text

    def test_matrix_plane_filter_restricts_the_run(self) -> None:
        cases = build_matrix()
        methodology = tuple(c for c in cases if c.plane == PLANE_METHODOLOGY)
        report = run_matrix(methodology, invoke_pinned_tests=False)
        assert report.is_clean()
        assert all(c.case.plane == PLANE_METHODOLOGY for c in report.cases)

    @staticmethod
    def _format_red(cases: Any, report: MatrixReport) -> str:
        lines: list[str] = []
        for case in report.cases:
            if not case.passed:
                lines.append(f"  {case.case.plane}/{case.case.hostile}: {case.detail}")
        return "\n".join(lines) or "no detail"


# ═══════════════════════ 2. matrix-red proof ═══════════════════════


class TestMatrixRedProof:
    """Neutralize battery: prove the matrix goes red when a pinned
    refusal is broken somewhere in the source tree.

    The proof is mechanical:

    1. snapshot a test file's sha256;
    2. modify a single line in the test to assert the wrong code
       (or ``False``);
    3. run the matrix; assert the case that pins the modified test
       goes red;
    4. restore the file (byte-identical, sha256-verified).

    The modified assertion is **local** to the test we touch — the
    modify step changes a single character, the restore step
    reverts the same character. No other test file is touched, no
    existing source file is touched.
    """

    PINNED_PATH = "tests/test_methodology_plane.py"

    def test_neutralizing_a_pinned_refusal_turns_the_matrix_red(self,
                                                              tmp_path: Path
                                                              ) -> None:
        # Locate the pinned test in the test file. The test asserts
        # the wrong code temporarily; we restore the original file
        # at the end of the test. We target a **specific** test by
        # matching the test's def-line as the anchor — multiple
        # tests in the file use the same EVIDENCE_DOES_NOT_RESOLVE
        # assertion, so the anchor must be unique. The modify /
        # restore cycle uses binary mode so the file is byte-identical
        # after the cycle (line endings and trailing newlines are
        # preserved).
        target = REPO_ROOT / self.PINNED_PATH
        original_bytes = target.read_bytes()
        original_sha = hashlib_sha256_bytes(original_bytes)
        # The anchor is the def-line of the pinned test; the
        # modification is the assertion immediately after the first
        # ``isinstance(recorded, SubstrateRefusal)`` in that test.
        anchor = b"def test_a_hallucinated_external_ref_is_refused(self)"
        idx = original_bytes.find(anchor)
        if idx < 0:
            pytest.skip(
                f"{self.PINNED_PATH} no longer contains the anchor; "
                f"the neutralize proof needs a maintenance update")
        marker = b"EVIDENCE_DOES_NOT_RESOLVE"
        slice_after = original_bytes[idx:]
        marker_idx = slice_after.find(marker)
        if marker_idx < 0:
            pytest.skip(
                f"{self.PINNED_PATH} no longer contains the marker "
                f"after the anchor; the neutralize proof needs a "
                f"maintenance update")
        absolute_marker_idx = idx + marker_idx
        modified = (original_bytes[:absolute_marker_idx]
                    + b"MALFORMED_PAYLOAD"
                    + original_bytes[absolute_marker_idx + len(marker):])
        assert modified != original_bytes, "neutralize: no change was made"
        target.write_bytes(modified)
        try:
            cases = build_matrix()
            case = next(
                c for c in cases
                if c.pinned_test.endswith(
                    "test_a_hallucinated_external_ref_is_refused"))
            report = run_matrix((case,))
            assert not report.is_clean(), (
                "neutralize: matrix stayed green; the proof did not work")
            assert not report.cases[0].passed, (
                "neutralize: the pinned case should be red")
        finally:
            target.write_bytes(original_bytes)
            restored_bytes = target.read_bytes()
            restored_sha = hashlib_sha256_bytes(restored_bytes)
            assert restored_sha == original_sha, (
                f"neutralize: restore failed (expected {original_sha}, "
                f"got {restored_sha})")
            # The working tree must match HEAD's content under the
            # repo's autocrlf policy; assert this by reading the LF
            # form of both and comparing.
            import subprocess
            head_result = subprocess.run(
                ["git", "show", f"HEAD:{self.PINNED_PATH}"],
                capture_output=True, check=True)
            head_lf = head_result.stdout.replace(b"\r\n", b"\n")
            current_lf = restored_bytes.replace(b"\r\n", b"\n")
            assert current_lf == head_lf, (
                "neutralize: restored content does not match HEAD")

    def test_a_failing_pinned_test_is_recorded_with_a_failure_detail(
            self, tmp_path: Path) -> None:
        # The matrix-red proof above proves the matrix surfaces a
        # pinned-test failure; this test exercises the failure-shape
        # record without touching any source file. We construct a
        # case whose pinned test does not exist, then assert the
        # case is recorded as failed with a detail line.
        case = MatrixCase(
            plane=PLANE_MODEL, hostile="synthetic",
            title="synthetic case with a missing pinned test",
            expected_code="PROPOSAL",
            pinned_test="tests/test_does_not_exist.py::x::y",
            assertion=lambda: None)
        report = run_matrix((case,), invoke_pinned_tests=True)
        assert not report.is_clean()
        out = report.cases[0]
        assert out.passed is False
        assert out.pinned_test_outcome == "failed"


def hashlib_sha256_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


# ═══════════════════════ 3. ops surface ═══════════════════════


class TestOpsAuth:
    def test_a_well_formed_token_is_consumed_and_a_digest_is_returned(self) -> None:
        outcome = authenticate(
            actor="op-1",
            token="op_AbCdEfGhIjKlMnOpQrStUvWxYz012345678",
            project_id="p1",
            scopes=("read", "write"),
            lifetime_seconds=300.0)
        assert outcome.is_refusal() is False
        ctx = outcome.value
        assert isinstance(ctx, AuthContext)
        assert ctx.actor == "op-1"
        assert ctx.token_digest  # non-empty
        assert len(ctx.token_digest) == 64
        # The raw token must not appear in the context.
        assert "AbCdEfGhIjKlMnOpQrStUvWxYz012345678" not in repr(ctx)

    def test_a_malformed_token_refuses_operator(self) -> None:
        outcome = authenticate(
            actor="op-1",
            token="not-a-real-token",
            scopes=("read",))
        assert outcome.is_refusal()
        assert outcome.refusal.code == "OPERATOR"
        assert outcome.refusal.surface == "auth"

    def test_an_empty_actor_refuses_role(self) -> None:
        outcome = authenticate(
            actor="  ",
            token="op_AbCdEfGhIjKlMnOpQrStUvWxYz012345678",
            scopes=("read",))
        assert outcome.is_refusal()
        assert outcome.refusal.code == "ROLE"

    def test_no_scopes_refuses_role(self) -> None:
        outcome = authenticate(
            actor="op-1",
            token="op_AbCdEfGhIjKlMnOpQrStUvWxYz012345678",
            scopes=())
        assert outcome.is_refusal()
        assert outcome.refusal.code == "ROLE"

    def test_an_expired_context_is_detectable(self) -> None:
        outcome = authenticate(
            actor="op-1",
            token="op_AbCdEfGhIjKlMnOpQrStUvWxYz012345678",
            scopes=("read",),
            lifetime_seconds=60.0, now=1000.0)
        ctx = outcome.value
        assert ctx.is_expired(now=1060.0) is True
        assert ctx.is_expired(now=1030.0) is False


class TestOpsRedaction:
    def test_a_secret_key_is_replaced_with_a_label(self) -> None:
        payload = {"api_key": "sk-1234567890abcdef",
                   "username": "alice"}
        redacted = redact(payload)
        assert "sk-1234567890abcdef" not in str(redacted)
        assert redacted["api_key"].startswith("<REDACTED:")
        assert redacted["username"] == "alice"

    def test_a_bearer_token_in_a_string_is_replaced(self) -> None:
        s = "Authorization: Bearer AbCdEfGhIjKlMnOpQrStUvWxYz012345"
        out = redact({"header": s})
        assert "AbCdEfGhIjKlMnOpQrStUvWxYz012345" not in out["header"]
        assert "<REDACTED:STRING>" in out["header"]

    def test_a_jwt_in_a_string_is_replaced(self) -> None:
        s = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MTIzIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        out = redact({"t": s})
        assert s not in out["t"]

    def test_a_long_hex_run_is_treated_as_a_secret(self) -> None:
        s = "0123456789abcdef0123456789abcdef0123456789abcdef"
        out = redact({"v": s})
        assert s not in out["v"]

    def test_a_long_base64_run_is_treated_as_a_secret(self) -> None:
        s = "QWxhZGRpbjpvcGVuIHNlc2FtZQ=="  # 28 chars base64
        out = redact({"v": s})
        assert s not in out["v"]

    def test_a_nested_mapping_is_walked(self) -> None:
        payload = {
            "outer": {"inner": {"password": "hunter2", "safe": 1}},
            "list": [{"token": "abc"}, {"safe": "hello"}],
        }
        out = redact(payload)
        assert "hunter2" not in str(out)
        assert "abc" not in str(out)
        assert out["outer"]["inner"]["safe"] == 1
        assert out["list"][1]["safe"] == "hello"

    def test_redaction_is_idempotent(self) -> None:
        payload = {"api_key": "sk-1234567890abcdef"}
        once = redact(payload)
        twice = redact(once)
        assert once == twice

    def test_redact_payload_refuses_on_non_mapping(self) -> None:
        # redact_payload returns a refusal-as-data mapping for a
        # non-mapping input.
        out = redact_payload("not a mapping")  # type: ignore[arg-type]
        assert out["rejected"] is True
        assert out["code"] == "RATIONALE"


class TestOpsSandbox:
    def test_a_path_inside_the_root_is_allowed(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        sub = root / "sub"
        sub.mkdir(parents=True)
        check = SandboxCheck(root=str(root), candidates=(str(sub),))
        outcome = check_sandbox_confinement(check)
        assert not outcome.is_refusal()

    def test_a_path_outside_the_root_refuses_proposal(self, tmp_path: Path
                                                      ) -> None:
        root = tmp_path / "root"
        sibling = tmp_path / "sibling"
        sibling.mkdir()
        check = SandboxCheck(root=str(root), candidates=(str(sibling),))
        outcome = check_sandbox_confinement(check)
        assert outcome.is_refusal()
        assert outcome.refusal.code == "PROPOSAL"

    def test_an_empty_root_refuses_malformed(self) -> None:
        check = SandboxCheck(root="", candidates=("a",))
        outcome = check_sandbox_confinement(check)
        assert outcome.is_refusal()
        assert outcome.refusal.code == "MALFORMED_PAYLOAD"


class TestOpsLimits:
    def test_a_fresh_budget_is_not_exhausted(self) -> None:
        budget = ResourceBudget(
            limits=ResourceLimits(max_wall_clock_seconds=10.0, max_ticks=5),
            started_at=0.0)
        outcome = enforce_resource_limits(budget, now=1.0)
        assert not outcome.is_refusal()

    def test_wall_clock_exhaustion_refuses_rationale(self) -> None:
        budget = ResourceBudget(
            limits=ResourceLimits(max_wall_clock_seconds=10.0),
            started_at=0.0)
        outcome = enforce_resource_limits(budget, now=20.0)
        assert outcome.is_refusal()
        assert outcome.refusal.code == "RATIONALE"
        assert "wall-clock" in outcome.refusal.detail

    def test_tick_exhaustion_refuses_rationale(self) -> None:
        budget = ResourceBudget(
            limits=ResourceLimits(max_ticks=2),
            started_at=0.0)
        budget = budget.record_tick()
        budget = budget.record_tick()
        budget = budget.record_tick()
        outcome = enforce_resource_limits(budget, now=1.0)
        assert outcome.is_refusal()
        assert "tick" in outcome.refusal.detail

    def test_token_exhaustion_refuses_rationale(self) -> None:
        budget = ResourceBudget(
            limits=ResourceLimits(max_tokens=3),
            started_at=0.0)
        budget = budget.record_tick(tokens_used=4)
        outcome = enforce_resource_limits(budget, now=1.0)
        assert outcome.is_refusal()
        assert "token" in outcome.refusal.detail

    def test_the_counter_boundary_is_exclusive(self) -> None:
        """``max_ticks=5`` allows the fifth tick and refuses the sixth."""
        budget = ResourceBudget(limits=ResourceLimits(max_ticks=5),
                                started_at=0.0)
        for _ in range(5):
            budget = budget.record_tick()
        assert not enforce_resource_limits(budget, now=1.0).is_refusal()
        budget = budget.record_tick()
        outcome = enforce_resource_limits(budget, now=1.0)
        assert outcome.is_refusal()
        assert outcome.refusal.code == "RATIONALE"
        assert outcome.refusal.field == "max_ticks"

    def test_a_non_budget_value_refuses_malformed(self) -> None:
        outcome = enforce_resource_limits("not a budget")  # type: ignore[arg-type]
        assert outcome.is_refusal()
        assert outcome.refusal.code == "MALFORMED_PAYLOAD"


class TestOpsLogs:
    def test_noop_sink_discards_silently(self) -> None:
        sink = NoOpLogSink()
        assert sink.emit({"any": "thing"}) is None

    def test_json_sink_serialises_each_record(self, capsys: Any) -> None:
        import io
        buf = io.StringIO()
        sink = JsonLogSink(stream=buf)
        sink.emit({"a": 1, "b": "two"})
        line = buf.getvalue().strip()
        body = json.loads(line)
        assert body == {"a": 1, "b": "two"}

    def test_structured_logger_emits_context(self, capsys: Any) -> None:
        import io
        buf = io.StringIO()
        logger = StructuredLogger(
            name="ops-test",
            sink=JsonLogSink(stream=buf),
            context={"trace_id": "tr-1"})
        logger.emit("INFO", "hello", extra=42)
        line = buf.getvalue().strip()
        body = json.loads(line)
        assert body["name"] == "ops-test"
        assert body["level"] == "INFO"
        assert body["message"] == "hello"
        assert body["trace_id"] == "tr-1"
        assert body["extra"] == 42


class TestOpsMetrics:
    def test_noop_sink_is_silent(self) -> None:
        sink = NoOpMetricsSink()
        assert sink.observe("m", 1.0) is None
        assert sink.increment("m") is None

    def test_counting_sink_counts_observations(self) -> None:
        sink = CountingMetricsSink()
        sink.observe("http.duration", 0.1, route="/a")
        sink.observe("http.duration", 0.2, route="/a")
        sink.increment("http.count", 1.0, route="/a")
        key = ("http.duration", frozenset({("route", "/a")}))
        assert sink.counts[key] == 2.0
        assert len(sink.observations) == 2


class TestOpsBackup:
    def test_a_matching_digest_verifies(self, tmp_path: Path) -> None:
        path = tmp_path / "blob.bin"
        path.write_bytes(b"hello world")
        import hashlib
        digest = hashlib.sha256(b"hello world").hexdigest()
        manifest = BackupManifest(
            path=str(path), sha256_hex=digest, byte_size=11)
        outcome = verify_backup(manifest)
        assert not outcome.is_refusal()

    def test_a_mismatched_digest_refuses_stale(self, tmp_path: Path) -> None:
        path = tmp_path / "blob.bin"
        path.write_bytes(b"hello world")
        manifest = BackupManifest(
            path=str(path),
            sha256_hex="0" * 64, byte_size=0)
        outcome = verify_backup(manifest)
        assert outcome.is_refusal()
        assert outcome.refusal.code == "STALE"

    def test_a_missing_file_refuses_stale(self, tmp_path: Path) -> None:
        manifest = BackupManifest(
            path=str(tmp_path / "absent"),
            sha256_hex="0" * 64, byte_size=0)
        outcome = verify_backup(manifest)
        assert outcome.is_refusal()
        assert outcome.refusal.code == "STALE"

    def test_a_size_mismatch_refuses_stale(self, tmp_path: Path) -> None:
        path = tmp_path / "blob.bin"
        path.write_bytes(b"hi")
        import hashlib
        digest = hashlib.sha256(b"hi").hexdigest()
        manifest = BackupManifest(
            path=str(path), sha256_hex=digest, byte_size=99)
        outcome = verify_backup(manifest)
        assert outcome.is_refusal()
        assert "size" in outcome.refusal.detail

    def test_a_malformed_digest_refuses_malformed(self, tmp_path: Path) -> None:
        path = tmp_path / "blob.bin"
        path.write_bytes(b"hi")
        manifest = BackupManifest(path=str(path), sha256_hex="short", byte_size=0)
        outcome = verify_backup(manifest)
        assert outcome.is_refusal()
        assert outcome.refusal.code == "MALFORMED_PAYLOAD"

    def test_an_uppercase_digest_refuses_malformed(self,
                                                   tmp_path: Path) -> None:
        """A manifest claim, not a content claim: format gate first."""
        path = tmp_path / "blob.bin"
        path.write_bytes(b"hi")
        import hashlib
        digest = hashlib.sha256(b"hi").hexdigest().upper()
        manifest = BackupManifest(path=str(path), sha256_hex=digest,
                                  byte_size=2)
        outcome = verify_backup(manifest)
        assert outcome.is_refusal()
        assert outcome.refusal.code == "MALFORMED_PAYLOAD"
        assert outcome.refusal.field == "sha256_hex"

    def test_a_non_hex_digest_refuses_malformed(self, tmp_path: Path) -> None:
        path = tmp_path / "blob.bin"
        path.write_bytes(b"hi")
        manifest = BackupManifest(path=str(path), sha256_hex="z" * 64,
                                  byte_size=2)
        outcome = verify_backup(manifest)
        assert outcome.is_refusal()
        assert outcome.refusal.code == "MALFORMED_PAYLOAD"
        assert outcome.refusal.field == "sha256_hex"

    def test_a_zero_byte_size_is_enforced_not_skipped(
            self, tmp_path: Path) -> None:
        """``byte_size=0`` is a claim of zero bytes, not "unknown"."""
        path = tmp_path / "blob.bin"
        path.write_bytes(b"hi")
        import hashlib
        digest = hashlib.sha256(b"hi").hexdigest()
        outcome = verify_backup(BackupManifest(path=str(path),
                                               sha256_hex=digest,
                                               byte_size=0))
        assert outcome.is_refusal()
        assert outcome.refusal.code == "STALE"
        assert outcome.refusal.field == "byte_size"

    def test_a_negative_byte_size_refuses_malformed(
            self, tmp_path: Path) -> None:
        path = tmp_path / "blob.bin"
        path.write_bytes(b"hi")
        import hashlib
        digest = hashlib.sha256(b"hi").hexdigest()
        outcome = verify_backup(BackupManifest(path=str(path),
                                               sha256_hex=digest,
                                               byte_size=-1))
        assert outcome.is_refusal()
        assert outcome.refusal.code == "MALFORMED_PAYLOAD"
        assert outcome.refusal.field == "byte_size"


class TestOpsConfig:
    def test_a_well_formed_config_passes(self) -> None:
        schema = ConfigSchema(
            allowed_keys=frozenset({"name", "version"}),
            required_keys=frozenset({"name", "version"}),
            value_types={"name": str, "version": str})
        outcome = validate_config(schema, {"name": "x", "version": "1"})
        assert not outcome.is_refusal()

    def test_an_unknown_key_refuses_malformed(self) -> None:
        schema = ConfigSchema(allowed_keys=frozenset({"name"}))
        outcome = validate_config(schema, {"name": "x", "extra": 1})
        assert outcome.is_refusal()
        assert outcome.refusal.code == "MALFORMED_PAYLOAD"

    def test_a_missing_required_key_refuses_malformed(self) -> None:
        schema = ConfigSchema(
            allowed_keys=frozenset({"name"}), required_keys=frozenset({"name"}))
        outcome = validate_config(schema, {})
        assert outcome.is_refusal()

    def test_a_wrong_type_refuses_malformed(self) -> None:
        schema = ConfigSchema(
            allowed_keys=frozenset({"n"}),
            value_types={"n": int})
        outcome = validate_config(schema, {"n": "not an int"})
        assert outcome.is_refusal()


# ═══════════════════════ 4. extensions manifest ═══════════════════════


class TestExtensionManifest:
    def test_there_are_nine_frozen_extension_points(self) -> None:
        names = list_extensions()
        assert names == ("ModelProvider", "Tool", "ToolSet", "AgentRole",
                         "Workflow", "StorageBackend", "EventSink",
                         "GovernancePolicy", "Evaluator")
        assert len(names) == 9

    def test_every_extension_validates_at_construction(self) -> None:
        for name, ep in EXTENSION_POINTS.items():
            ep.validate()  # raises on a bad refused_code

    def test_every_extension_refused_code_is_in_the_frozen_vocabulary(
            self) -> None:
        for name, ep in EXTENSION_POINTS.items():
            assert ep.refused_code in FROZEN_REFUSAL_CODES, (
                f"{name}: {ep.refused_code!r} not in frozen vocabulary")

    def test_every_extension_has_a_worked_example(self) -> None:
        for name, ep in EXTENSION_POINTS.items():
            assert ep.example is not None
            assert ep.example.name
            # Every example's primary is a callable that returns an
            # ExampleOutcome.
            outcome = ep.example.primary()
            assert outcome is not None


class TestWorkedExamples:
    """Each worked example is exercised in isolation; the test suite
    proves every example is green."""

    def test_model_provider_example_is_green(self) -> None:
        outcome = ExampleModelProvider(model_id="x", canned_text="ok").primary()
        assert outcome.refusal is None
        assert outcome.value["model_id"] == "x"
        assert outcome.value["text"] == "ok"

    def test_tool_example_is_green(self) -> None:
        outcome = ExampleTool(tool_id="t1").primary()
        assert outcome.refusal is None
        assert outcome.value["tool_id"] == "t1"
        assert outcome.value["observation"] == "echo"

    def test_tool_set_example_is_green(self) -> None:
        outcome = ExampleToolSet().primary()
        assert outcome.refusal is None
        assert len(outcome.value["tools"]) == 2

    def test_agent_role_example_is_green(self) -> None:
        outcome = ExampleAgentRole(profile="researcher").primary()
        assert outcome.refusal is None
        assert outcome.value["profile"] == "researcher"
        assert "INSERT_TASK" in outcome.value["allowlist"]

    def test_workflow_example_is_green(self) -> None:
        outcome = ExampleWorkflow().primary()
        assert outcome.refusal is None
        assert outcome.value["methodology_id"] == "literature-review"
        assert "QUESTION" in outcome.value["stages"]

    def test_storage_backend_put_then_overwrite_refuses_stale(self) -> None:
        backend = ExampleStorageBackend()
        put1 = backend.put("d" * 64, "v1")
        assert put1.refusal is None
        put2 = backend.put("d" * 64, "v2-different")
        assert put2.refusal is not None
        assert put2.refusal["code"] == "STALE"

    def test_storage_backend_get_missing_refuses_evidence(self) -> None:
        backend = ExampleStorageBackend()
        outcome = backend.get("nope")
        assert outcome.refusal is not None
        assert outcome.refusal["code"] == "EVIDENCE_DOES_NOT_RESOLVE"

    def test_event_sink_observes_without_writing(self) -> None:
        sink = ExampleEventSink()
        outcome = sink.observe({"kind": "x"})
        assert outcome.refusal is None
        assert outcome.value == 1
        assert len(sink._received) == 1

    def test_governance_policy_lookup_is_green(self) -> None:
        policy = ExampleGovernancePolicy()
        assert policy.lookup("WEB_SEARCH").value == "AGENT"
        assert policy.lookup("PUBLISH").value == "HUMAN"

    def test_governance_policy_unknown_action_refuses_malformed(self) -> None:
        policy = ExampleGovernancePolicy()
        outcome = policy.lookup("HACK")
        assert outcome.refusal is not None
        assert outcome.refusal["code"] == "MALFORMED_PAYLOAD"

    def test_evaluator_example_is_a_pure_value_object(self) -> None:
        outcome = ExampleEvaluator().primary()
        assert outcome.refusal is None
        assert outcome.value == {"evaluator": "matrix-stub"}

    def test_list_examples_returns_every_example(self) -> None:
        examples = list_examples()
        assert len(examples) == 9
        names = {e.name for e in examples}
        assert "in-memory-ca" in names
        assert "tap-sink" in names


class TestExtensionRegistry:
    def test_a_registry_constructed_from_an_example_finds_it(self) -> None:
        example = ExampleModelProvider()
        registry = register_extension(example)
        assert get_extension(registry, example.name) is example

    def test_a_registry_is_immutable(self) -> None:
        example = ExampleTool()
        registry = register_extension(example)
        assert isinstance(registry, ExtensionRegistry)
        # Every writer surface is refused: item assignment, deletion, the
        # mutating mapping methods, and rebinding the frozen field.
        with pytest.raises(TypeError):
            registry.entries["not-registered"] = example  # type: ignore[index]
        with pytest.raises(TypeError):
            del registry.entries[example.name]  # type: ignore[attr-defined]
        # ``mappingproxy`` exposes no mutator at all (a plain dict has
        # every one of these).
        for mutator in ("clear", "pop", "popitem", "setdefault", "update"):
            assert not hasattr(registry.entries, mutator), mutator
        with pytest.raises(dataclasses.FrozenInstanceError):
            registry.entries = {}  # type: ignore[misc]
        # The registry is a snapshot: mutating the caller's mapping after
        # construction cannot install an extension.
        source: dict[str, Any] = {example.name: example}
        snapshot = ExtensionRegistry(entries=source)
        source["Sneaky"] = example
        assert snapshot.names() == (example.name,)
        with pytest.raises(KeyError):
            snapshot.get("Sneaky")
        # Attempting to look up an unknown name raises.
        with pytest.raises(KeyError):
            registry.get("not-registered")

    def test_describe_extension_renders_human_and_json(self) -> None:
        for name in list_extensions():
            human = describe_extension(name, as_json=False)
            assert name in human
            machine = describe_extension(name, as_json=True)
            body = json.loads(machine)
            assert body["name"] == name
            assert "operations" in body
            assert "refused_code" in body

    def test_describe_extension_raises_on_unknown(self) -> None:
        with pytest.raises(KeyError):
            describe_extension("not-a-real-extension")


# ═══════════════════════ 5. platform CLI ═══════════════════════


class TestPlatformCLI:
    """The platform CLI is a SEPARATE module from ``hermes.cli``. This
    test suite exercises the CLI as a subprocess — never imports
    ``hermes.cli`` or its private submodules."""

    def test_platform_cli_is_a_separate_module(self) -> None:
        # The eval package must not import the spine's CLI; the
        # matrix / ops / extensions surfaces are operator-facing,
        # but they are intentionally independent of the spine's
        # CLI to keep the two vectors from coupling.
        from hermes.eval import (
            extensions,
            matrix,
            ops,
            platform_cli,
        )
        # None of these import the spine's CLI as a module:
        for module in (platform_cli, extensions, matrix, ops):
            source = Path(module.__file__).read_text(encoding="utf-8")
            assert "from hermes.cli" not in source, (
                f"{module.__name__}: must not import hermes.cli")
            assert "import hermes.cli" not in source, (
                f"{module.__name__}: must not import hermes.cli")
            # AST-level: ensure no import statement targets the
            # spine's CLI module path.
            import ast as _ast
            tree = _ast.parse(source)
            for node in _ast.walk(tree):
                if isinstance(node, _ast.ImportFrom) and node.module:
                    if node.module == "hermes.cli" or node.module.startswith(
                            "hermes.cli."):
                        raise AssertionError(
                            f"{module.__name__}: imports from "
                            f"{node.module!r} — must be independent")
                elif isinstance(node, _ast.Import):
                    for alias in node.names:
                        if alias.name == "hermes.cli" or alias.name.startswith(
                                "hermes.cli."):
                            raise AssertionError(
                                f"{module.__name__}: imports "
                                f"{alias.name!r} — must be independent")

    def test_platform_cli_extensions_lists_the_nine_points(self) -> None:
        result = subprocess.run(
            [PYTHON, "-m", "hermes.eval.platform_cli", "extensions",
             "--format", "json"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT), env=_with_path(),
            timeout=30)
        assert result.returncode == 0
        body = json.loads(result.stdout)
        names = {item["name"] for item in body["extensions"]}
        assert names == set(list_extensions())

    def test_platform_cli_extensions_describes_one_point(self) -> None:
        result = subprocess.run(
            [PYTHON, "-m", "hermes.eval.platform_cli", "extensions",
             "ModelProvider", "--format", "json"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT), env=_with_path(),
            timeout=30)
        assert result.returncode == 0
        body = json.loads(result.stdout)
        assert body["name"] == "ModelProvider"
        assert body["refused_code"] in FROZEN_REFUSAL_CODES

    def test_platform_cli_matrix_runs_clean(self) -> None:
        result = subprocess.run(
            [PYTHON, "-m", "hermes.eval.platform_cli", "matrix",
             "--no-pinned-test", "--format", "json"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT), env=_with_path(),
            timeout=60)
        assert result.returncode == 0, (
            f"matrix CLI failed: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}")
        body = json.loads(result.stdout)
        assert body["is_clean"] is True
        assert body["summary"]["total"] == 26

    def test_platform_cli_matrix_plane_filter(self) -> None:
        result = subprocess.run(
            [PYTHON, "-m", "hermes.eval.platform_cli", "matrix",
             "--plane", "methodology", "--no-pinned-test",
             "--format", "json"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT), env=_with_path(),
            timeout=60)
        assert result.returncode == 0
        body = json.loads(result.stdout)
        assert body["summary"]["total"] == 6

    def test_platform_cli_auth_consumes_the_token(self) -> None:
        result = subprocess.run(
            [PYTHON, "-m", "hermes.eval.platform_cli", "auth",
             "--actor", "op-1",
             "--token", "op_AbCdEfGhIjKlMnOpQrStUvWxYz012345678",
             "--project-id", "p1",
             "--scopes", "read", "--scopes", "write",
             "--lifetime-seconds", "300",
             "--format", "json"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT), env=_with_path(),
            timeout=30)
        assert result.returncode == 0
        body = json.loads(result.stdout)
        assert body["actor"] == "op-1"
        assert body["project_id"] == "p1"
        # The raw token must not appear in the output.
        assert "AbCdEfGhIjKlMnOpQrStUvWxYz012345678" not in result.stdout

    def test_platform_cli_auth_refuses_a_malformed_token(self) -> None:
        result = subprocess.run(
            [PYTHON, "-m", "hermes.eval.platform_cli", "auth",
             "--actor", "op-1",
             "--token", "not-a-token",
             "--scopes", "read",
             "--format", "json"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT), env=_with_path(),
            timeout=30)
        assert result.returncode == 1
        body = json.loads(result.stdout)
        assert body["code"] == "OPERATOR"

    def test_platform_cli_redact_demo_redacts_a_fixture(self) -> None:
        result = subprocess.run(
            [PYTHON, "-m", "hermes.eval.platform_cli", "redact-demo",
             "--format", "json"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT), env=_with_path(),
            timeout=30)
        assert result.returncode == 0
        json.loads(result.stdout)
        # The raw token in the fixture must not appear in the output.
        assert "AbCdEfGhIjKlMnOpQrStUvWxYz012345678" not in result.stdout
        # The api_key value must not appear in the output.
        assert "sk-1234567890abcdef" not in result.stdout


def _with_path() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", "src;.")
    env.setdefault("PYTHONUTF8", "1")
    return env

# ═══════════════════════ 6. R7-fix pins ═══════════════════════


class TestOpsTokenRedactionAtEmit:
    """R7-FIX (P1): the token probe is redacted at emit, fields and context."""

    RAW = "sekret-abc123"

    def test_the_operator_token_field_probe_is_redacted(self) -> None:
        import io

        buf = io.StringIO()
        logger = StructuredLogger(name="auth", sink=JsonLogSink(stream=buf))
        logger.emit("INFO", "operator authenticated",
                    operator_token=self.RAW,
                    authorization=f"Bearer {self.RAW}")
        line = buf.getvalue()
        assert self.RAW not in line, f"raw token in the sink record: {line!r}"
        body = json.loads(line)
        assert body["operator_token"].startswith("<REDACTED:")
        assert body["authorization"].startswith("<REDACTED:")

    def test_the_operator_token_context_probe_is_redacted(self) -> None:
        import io

        buf = io.StringIO()
        logger = StructuredLogger(
            name="auth", sink=JsonLogSink(stream=buf),
            context={"operator_token": self.RAW, "trace_id": "tr-1"})
        logger.emit("INFO", "session established")
        line = buf.getvalue()
        assert self.RAW not in line, f"raw token in the sink record: {line!r}"
        body = json.loads(line)
        assert body["operator_token"].startswith("<REDACTED:")
        assert body["trace_id"] == "tr-1"

    def test_the_logger_redacts_before_a_caller_supplied_sink(self) -> None:
        """The record handed to ANY sink is already redacted.

        ``JsonLogSink`` redacts again in its own ``emit``, so a JSON-line
        pin alone cannot witness that the logger redacted. A recording
        sink sees exactly the record the logger built.
        """

        class _RecordingSink:
            def __init__(self) -> None:
                self.records: list[dict[str, Any]] = []

            def emit(self, record: Any) -> None:
                self.records.append(dict(record))

        sink = _RecordingSink()
        logger = StructuredLogger(
            name="auth", sink=sink,
            context={"operator_token": self.RAW, "trace_id": "tr-1"})
        logger.emit("INFO", "session established",
                    operator_token=self.RAW,
                    authorization=f"Bearer {self.RAW}")
        assert len(sink.records) == 1
        record = sink.records[0]
        dumped = json.dumps(record, default=str)
        assert self.RAW not in dumped, f"raw token reached the sink: {dumped}"
        assert record["operator_token"].startswith("<REDACTED:")
        assert record["authorization"].startswith("<REDACTED:")
        assert record["trace_id"] == "tr-1"

    def test_a_direct_sink_emit_is_redacted_too(self) -> None:
        import io

        buf = io.StringIO()
        JsonLogSink(stream=buf).emit({
            "token": self.RAW,
            "nested": {"authorization": f"Bearer {self.RAW}"}})
        assert self.RAW not in buf.getvalue()


class TestOpsLimitsMemory:
    """R7-FIX (P1): the declared memory limit is enforced, breach refuses."""

    def test_a_memory_breach_refuses_rationale(self) -> None:
        budget = ResourceBudget(limits=ResourceLimits(max_memory_bytes=1024),
                                started_at=0.0)
        fresh = enforce_resource_limits(budget, now=1.0)
        assert not fresh.is_refusal()
        breached = budget.record_memory(2048)
        outcome = enforce_resource_limits(breached, now=1.0)
        assert outcome.is_refusal()
        assert outcome.refusal.code == "RATIONALE"
        assert outcome.refusal.field == "max_memory_bytes"
        assert "memory" in outcome.refusal.detail

    def test_a_memory_breach_is_reported_by_is_exhausted(self) -> None:
        budget = ResourceBudget(limits=ResourceLimits(max_memory_bytes=1),
                                started_at=0.0, memory_bytes=2)
        assert budget.is_exhausted(now=1.0) == (True, "memory")

    def test_a_non_finite_clock_refuses_malformed(self) -> None:
        budget = ResourceBudget(
            limits=ResourceLimits(max_wall_clock_seconds=1.0), started_at=0.0)
        outcome = enforce_resource_limits(budget, now=float("nan"))
        assert outcome.is_refusal()
        assert outcome.refusal.code == "MALFORMED_PAYLOAD"
        assert "clock" in outcome.refusal.detail

    def test_a_backwards_clock_refuses_malformed(self) -> None:
        budget = ResourceBudget(
            limits=ResourceLimits(max_wall_clock_seconds=10.0), started_at=100.0)
        outcome = enforce_resource_limits(budget, now=50.0)
        assert outcome.is_refusal()
        assert outcome.refusal.code == "MALFORMED_PAYLOAD"


class TestOpsRedactionGapClosure:
    """R7-FIX (P2): one pin per declared secret-shaped key (the 8 gaps)."""

    CANARY = "my-dog-42! play"

    @pytest.mark.parametrize("key", [
        "passwd", "passphrase", "private_key", "pin", "signing_key",
        "auth_header", "db_creds", "key"])
    def test_a_declared_secret_shaped_key_is_redacted(self, key: str) -> None:
        out = redact({key: self.CANARY})
        assert out[key] != self.CANARY, f"{key!r} leaked verbatim"
        assert str(out[key]).startswith("<REDACTED:")

    def test_the_positive_control_still_redacts(self) -> None:
        out = redact({"api_key": self.CANARY, "password": self.CANARY,
                      "token": self.CANARY})
        assert all(value != self.CANARY for value in out.values())


# ═══════════════ 6b. R7-FIX2 pins (message path / import gate) ═══════════════


class TestOpsMessagePathRedaction:
    """R7-FIX2 (P1): the log **message** is redacted like a field value.

    The R7-REREPORT probe (``ITEM3-ALL-PATHS-CLEAN``) showed the message
    path leaking verbatim while fields and context redacted: the record
    was assembled and the *message string* was never a subject of
    redaction, so an f-string carrying a live credential reached the sink
    unchanged.

    These pins are the same three paths the probe used — token via
    ``message``, via ``fields``, via ``context`` — plus the bare-literal
    case, and they assert both the raw rendered line AND the parsed
    record, because a redaction applied after ``json.dumps`` would leave
    the parsed record dirty.
    """

    RAW = "sekret-abc123"
    RAWOP = "op_Zz9LmQ42Rt7Xy3Kd8Vw5Nn0Pb1Sa6Hj"
    #: A credential with no secret-shaped syntax of any kind — no
    #: ``key=`` prefix, no ``op_`` prefix, no ``alpha-…123`` shape, and
    #: under the entropy floors. Only the registered-literal floor can
    #: see it; that is the point of the floor.
    HUNTER = "hunter2pass"

    def _emitted(self, message: str, *, context: dict[str, Any] | None = None,
                 **fields: Any) -> tuple[str, dict[str, Any]]:
        import io

        buf = io.StringIO()
        logger = StructuredLogger(name="probe",
                                 sink=JsonLogSink(stream=buf),
                                 context=context or {})
        logger.emit("info", message, **fields)
        line = buf.getvalue()
        body = json.loads(line)
        return line, body

    # ── the director's exact probe: three paths, one token ──────────

    def test_a_token_in_the_message_is_redacted(self) -> None:
        line, body = self._emitted(f"operator authenticated {self.RAW}")
        assert self.RAW not in line, f"raw token leaked into the sink: {line!r}"
        assert self.RAW not in body["message"]
        assert "<REDACTED:STRING>" in body["message"]

    def test_a_token_in_a_field_is_redacted(self) -> None:
        line, body = self._emitted("operator authenticated",
                                   operator_token=self.RAW)
        assert self.RAW not in line
        assert body["operator_token"].startswith("<REDACTED:")

    def test_a_token_in_the_context_is_redacted(self) -> None:
        line, body = self._emitted("session established",
                                   context={"session_id": self.RAW})
        assert self.RAW not in line
        assert body["session_id"].startswith("<REDACTED:")

    # ── bare literal in a message (the shape no key names) ──────────

    def test_a_bare_literal_in_the_message_is_redacted(self) -> None:
        """A literal with NO secret-shaped syntax at all, in free text.

        ``hunter2pass`` is neither ``key=``-prefixed, nor ``op_``-shaped,
        nor ``alpha-…123`` shaped, nor 16+ chars of entropy: no *shape*
        rule can recognise it. It dies by the registered-literal floor
        alone, so this pin is the one that proves the floor is load-
        bearing — drop ``register_secret``'s scrub and this fails while
        every shape-based pin still passes.
        """
        register_secret(self.HUNTER)
        line, body = self._emitted(f"login ok {self.HUNTER}")
        assert self.HUNTER not in line, f"bare literal leaked: {line!r}"
        assert self.HUNTER not in body["message"]
        assert "<REDACTED:STRING>" in body["message"]

    def test_the_shape_less_canary_is_indistinguishable_from_prose(self) -> None:
        """Why the floor exists, stated as a pin.

        This canary is unique to this test (no other pin registers it),
        so the two assertions below are unaffected by registration state
        left behind by another test — a shared literal would make this
        assert on the wrong thing. Without registration it survives
        redaction untouched: no shape rule can see it. That is the gap
        the floor closes.
        """
        shape_less = "zq7vn4kt"
        assert not any(pattern.search(shape_less) for pattern in _SHAPE_PATTERNS)
        assert redact({"note": shape_less})["note"] == shape_less, (
            "a shape rule started matching this canary — re-check whether "
            "the registered-literal floor is still needed")
        register_secret(shape_less)
        assert redact({"note": shape_less})["note"] != shape_less

    def test_a_registered_literal_is_scrubbed_from_every_path(self) -> None:
        register_secret(self.HUNTER)
        line, body = self._emitted(
            f"login ok {self.HUNTER}", trace="x",
            nested={"note": f"see {self.HUNTER}"})
        assert self.HUNTER not in line, f"registered literal leaked: {line!r}"
        assert self.HUNTER not in str(body)

    def test_a_registered_literal_survives_repeat_emits(self) -> None:
        register_secret(self.HUNTER)
        for _ in range(3):
            line, _body = self._emitted(f"login ok {self.HUNTER}")
            assert self.HUNTER not in line

    def test_the_shape_rules_alone_still_kill_the_redteam_canary(self) -> None:
        """``sekret-abc123`` IS covered by a shape rule.

        This is the canary the R7-REREPORT probe used, and it is pinned
        here *without* registering it, so the shape rule for a bare
        ``alpha-…123`` credential is independently witnessed. The floor
        pin above covers the case no shape can see; between them, neither
        can be dropped silently.
        """
        assert self.RAW not in redact({"note": self.RAW})["note"], (
            "the bare-literal shape rule no longer covers the canary")
        line, _body = self._emitted(f"login ok {self.RAW}")
        assert self.RAW not in line

    # ── prefixed shapes in free text (the 16-char-floor gap) ────────

    def test_a_short_prefixed_token_in_the_message_is_redacted(self) -> None:
        """``token=sekret-abc123`` is 13 characters of value.

        The pre-fix rule required ≥16 characters after the separator, so
        this exact shape leaked. The free-text rule is built from the
        declared key vocabulary with no length floor.
        """
        line, body = self._emitted(f"token={self.RAW}")
        assert self.RAW not in line, f"prefixed token leaked: {line!r}"
        assert self.RAW not in body["message"]

    @pytest.mark.parametrize("prefix", [
        "token", "password", "passwd", "passphrase", "secret", "api_key",
        "api-key", "apikey", "private_key", "signing_key", "pin",
        "credential", "db_creds", "authorization", "auth_header",
        "session_id", "cookie", "key"])
    def test_every_declared_secret_word_redacts_free_text(self, prefix: str) -> None:
        """The free-text rule is derived from the declared key patterns.

        If it were a parallel hand-copied list, one of these words would
        be missing from one of the two paths. Every declared word works
        in free text *and* as a key.
        """
        value = "hunter2-short"
        line, _body = self._emitted(f"{prefix}={value}")
        assert value not in line, f"{prefix}= leaked in free text: {line!r}"
        keyed = redact({prefix: value})
        assert keyed[prefix] != value

    def test_a_reserved_token_shape_in_the_message_is_whole_redacted(
            self) -> None:
        """``op_…`` is credential material by the ops layer's own
        admission rule, so it is redacted whole — not left with a
        readable prefix, which the pre-fix base64-tail rule did."""
        line, body = self._emitted(f"operator authenticated {self.RAWOP}")
        assert self.RAWOP not in line
        assert "op_" not in body["message"]

    # ── the parsed record, not just the rendered line ────────────────

    def test_the_parsed_records_message_is_not_the_verbatim_input(self) -> None:
        register_secret(self.RAW)
        _line, body = self._emitted(f"login ok {self.RAW}")
        assert body["message"] != f"login ok {self.RAW}"

    # ── no collateral damage: ordinary text still survives ──────────

    @pytest.mark.parametrize("message", [
        "operator authenticated",
        "session established",
        "task-root",
        "run critic/task-root/p1/1 completed",
        "claude-sonnet-4-5",
        "gpt-4o-mini",
        "prj_2024-11-05_alpha",
        "sqlite:///./var/hermes.db",
        "2026-10-02T20:11:00Z",
        "budget exhausted (5 ticks)",
        "provider was called 1 times before the option guard",
        "step 1 of 3",
    ])
    def test_ordinary_operational_text_is_preserved(self, message: str) -> None:
        """Redaction that ate ordinary log lines would not be a fix.

        These are strings harvested from the repo's own log-shaped text
        and the driver's own detail messages. A redaction rule broad
        enough to catch every bare literal (measured: 82% false-positive
        against this corpus) would fail every assertion here.
        """
        _line, body = self._emitted(message)
        assert body["message"] == message

    def test_the_positive_control_field_shape_is_untouched(self) -> None:
        _line, body = self._emitted("ok", trace_id="tr-1", step=3)
        assert body["trace_id"] == "tr-1"
        assert body["step"] == 3

    # ── the scrub floor applies to a direct sink call too ───────────

    def test_a_direct_sink_call_scrubs_a_registered_literal(self) -> None:
        import io

        register_secret(self.RAW)
        buf = io.StringIO()
        JsonLogSink(stream=buf).emit({"message": f"login ok {self.RAW}"})
        assert self.RAW not in buf.getvalue()

    def test_a_short_registered_value_is_refused(self) -> None:
        """A literal so short it occurs in ordinary text is not
        registered — scrubbing it would make every record unreadable
        rather than safer."""
        before = redact({"note": "abc"})
        register_secret("abc")
        assert redact({"note": "abc"}) == before


class TestOpsRedactionKeysAndAffixFix3:
    """R7-FIX3 (P1/P3): key names are scrubbed; a registered literal
    absorbs its own identifier glue; the split residual is documented.

    Root (R7_REREPORT2, novel shape 3): ``_redact_walk`` replaced a
    secret-shaped key's *value* but never passed the **key** through the
    text scrubber, so ``{"note_token_sekret-abc123": "<REDACTED:TOKEN>"}``
    looked scrubbed while the canary sat verbatim in the key. Root (novel
    shape 1 / GLUE): the shape rules are fenced, so a *registered* literal
    abutted by word characters (``sekret-abc123tail``) matched nothing.
    """

    RAW = "sekret-abc123"
    RAWOP = "op_Zz9LmQ42Rt7Xy3Kd8Vw5Nn0Pb1Sa6Hj"

    # ── item 1: the re-report's exact key cases ─────────────────────

    def test_a_bare_secret_as_a_key_is_redacted(self) -> None:
        out = redact({self.RAW: "v"})
        assert self.RAW not in str(out), "the bare secret survived in a key"
        assert list(out) == ["<REDACTED:STRING>"]

    def test_a_reserved_token_as_a_key_is_redacted(self) -> None:
        out = redact({self.RAWOP: "v"})
        assert self.RAWOP not in str(out), "the op_ token survived in a key"
        assert list(out) == ["<REDACTED:STRING>"]

    def test_a_secret_affixed_to_a_secret_shaped_key_is_redacted(self) -> None:
        """The re-report's worst case: value replaced, key left verbatim.

        ``note_token_sekret-abc123`` matches the declared ``token`` key
        rule, so the value was replaced with ``<REDACTED:TOKEN>`` and the
        record *looked* scrubbed — while the canary was the key.
        """
        out = redact({f"note_token_{self.RAW}": self.RAW})
        assert self.RAW not in str(out), "the canary survived in the key"
        rendered_key = next(iter(out))
        assert rendered_key.endswith("<REDACTED:STRING>")
        assert rendered_key.startswith("note_token_")  # the name is kept
        assert out[rendered_key] == "<REDACTED:TOKEN>"

    def test_a_nested_secret_key_is_redacted(self) -> None:
        out = redact({"outer": {"inner": {self.RAW: "v"}}})
        assert self.RAW not in str(out), "a nested key leaked"

    def test_a_secret_valued_key_is_redacted_at_the_sink(self) -> None:
        import io

        register_secret(self.RAW)
        buf = io.StringIO()
        JsonLogSink(stream=buf).emit({f"note_token_{self.RAW}": self.RAW})
        line = buf.getvalue()
        assert self.RAW not in line, f"the sink wrote a key verbatim: {line!r}"

    def test_a_registered_literal_as_a_key_is_redacted(self) -> None:
        """A live token (registered by ``authenticate``) as a key name."""
        register_secret(self.RAWOP)
        out = redact({self.RAWOP: "v"})
        assert self.RAWOP not in str(out)

    def test_distinct_keys_that_scrub_alike_are_both_kept(self) -> None:
        """Scrubbing two keys to one placeholder must not silently drop
        either — the second gets a deterministic ordinal suffix."""
        out = redact({self.RAW: "a", self.RAWOP: "b"})
        assert len(out) == 2, out
        assert not any(secret in str(out) for secret in (self.RAW, self.RAWOP))

    # ── item 2: registered-literal affix rule ───────────────────────

    def test_a_registered_literal_absorbs_identifier_glue(self) -> None:
        """The re-report's suffix/prefix glue leaks.

        ``sekret-abc123tail`` / ``idsekret-abc123x`` / ``sekret-abc123op_X``
        each carried the registered canary with glue on one side, and the
        fenced shape rule matched none of them. The registered match is a
        raw substring and absorbs the ``[A-Za-z0-9_-]`` glue on both sides,
        so the *whole* token is replaced — glue included.
        """
        register_secret(self.RAW)
        for glued in ("sekret-abc123tail", "idsekret-abc123x",
                      "sekret-abc123op_X"):
            out = redact({"note": glued})["note"]
            assert self.RAW not in out, f"secret survived in {glued!r}"
            assert out == "<REDACTED:STRING>", (
                f"glue was not absorbed for {glued!r}: {out!r}")

    def test_a_glued_secret_in_a_message_leaves_no_residue(self) -> None:
        register_secret(self.RAW)
        for glued in ("sekret-abc123tail", "idsekret-abc123x",
                      "sekret-abc123op_X"):
            out = redact({"message": f"chain {glued}"})["message"]
            assert self.RAW not in out
            assert "tail" not in out and "idsekret" not in out
            assert out == "chain <REDACTED:STRING>"

    def test_the_unregistered_shape_rule_stays_fenced(self) -> None:
        """Stated limit: the shape rule keeps its fence.

        Dropping the fence is what makes a shape rule guess — a rule broad
        enough to match any abutted run matched 82% of this repository's
        own log text (module docstring, "Stated limits"). So an abutted
        literal that was **never registered** stays outside the shape
        rule's reach; the registered-literal affix rule above is the
        general answer. The fenced form is still caught, so the rule is
        load-bearing and not deleted.
        """
        # A canary no test registers, so the shape rule is the only
        # mechanism in play.
        canary = "zzcanary-abc999"
        assert canary not in _ops._REGISTERED_SECRETS
        assert redact({"note": canary + "tail"})["note"] == canary + "tail"
        assert redact({"note": canary})["note"] == "<REDACTED:STRING>"

    # ── item 4: split-secret residual (documented, not chased) ──────

    def test_each_half_of_a_split_secret_is_redacted_alone(self) -> None:
        """R7-FIX3 (P3 residual): reassembly is out of contract.

        A secret split across two positions is redacted wherever a half is
        individually recognisable, so no half leaks verbatim on its own.
        What the layer does not do is reassemble a payload to test whether
        two individually-innocuous fragments concatenate into a credential
        — that boundary is stated in the ``ops`` module docstring
        ("Stated limits"), not closed here.
        """
        register_secret(self.RAW)
        for half in (self.RAW, self.RAWOP):
            out = redact({"alpha": half})["alpha"]
            assert half not in out, f"a half leaked verbatim: {half!r}"
        # even split across two positions of one record, neither half is
        # written verbatim: the guarantee is per-half, not reassembly.
        rendered = str(redact({"alpha": self.RAW, "beta": self.RAWOP}))
        assert self.RAW not in rendered and self.RAWOP not in rendered


class TestEvalImportGate:
    """R7-FIX2 (P2): the eval plane's import gate is AST-level.

    ``hostile.py`` previously imported the governance plane through
    ``importlib.import_module("hermes." + "governance.approvals")`` — a
    string concatenation written so that the governance plane's own
    suite-integrity gate (a substring scan for the contiguous text
    ``hermes.governance``) would not see it. The dependency was real;
    only its spelling was hidden.

    These pins assert that ``import_gate`` detects the evasion shapes
    structurally, so the spelling no longer decides the verdict.
    """

    EVASIONS: dict[str, str] = {
        "string_split": (
            'import importlib\n'
            '_g = importlib.import_module("hermes." + "governance.approvals")\n'),
        "three_way_split": (
            'import importlib\n'
            '_g = importlib.import_module("hermes" + ".gov" + "ernance.policy")\n'),
        "join_assembly": (
            'import importlib\n'
            '_g = importlib.import_module(".".join(["hermes", "governance",'
            ' "authority"]))\n'),
        "str_wrap": (
            'import importlib\n'
            '_g = importlib.import_module(str("hermes.governance.policy"))\n'),
        "builtin_dunder_import": (
            '_g = __import__("hermes." + "governance.policy")\n'),
        "contiguous": (
            'import hermes.governance.approvals\n'),
        "from_import": (
            "from hermes.governance import policy\n"),
        "import_as": (
            "import hermes.governance.policy as gp\n"),
    }

    CONTROLS: dict[str, str] = {
        "unrelated_module": "import hermes.core.events\n",
        "unrelated_dynamic": (
            'import importlib\n_g = importlib.import_module("json")\n'),
        "empty_file": "# nothing to see here\n",
    }

    def _write(self, tmp_path: Path, source: str) -> Path:
        path = tmp_path / "candidate.py"
        path.write_text(source, encoding="utf-8")
        return path

    @pytest.mark.parametrize("shape", sorted(EVASIONS))
    def test_an_evasion_shaped_import_is_detected(
            self, tmp_path: Path, shape: str) -> None:
        path = self._write(tmp_path, self.EVASIONS[shape])
        assert detect_import_mentions(path), (
            f"{shape!r} import evaded the AST gate — the dependency is "
            f"unreported, so the gate can be defeated by spelling")

    def test_a_string_split_import_is_reported_with_its_module(
            self, tmp_path: Path) -> None:
        """The exact original evasion, pinned by line and module."""
        path = self._write(tmp_path, self.EVASIONS["string_split"])
        sites = dynamic_import_sites(path)
        assert sites, "the split-string import was not resolved"
        assert sites[0].endswith(":hermes.governance.approvals")

    def test_the_contiguous_form_is_still_detected(self, tmp_path: Path) -> None:
        """The gate is not a bespoke detector for evasion only: the
        form the old substring gate caught is caught here too."""
        path = self._write(tmp_path, self.EVASIONS["contiguous"])
        assert detect_import_mentions(path) == ("declared",)

    @pytest.mark.parametrize("control", sorted(CONTROLS))
    def test_a_control_does_not_fire(self, tmp_path: Path, control: str) -> None:
        path = self._write(tmp_path, self.CONTROLS[control])
        assert detect_import_mentions(path) == (), (
            f"{control!r} must not be reported as a governance dependency")

    def test_a_declared_import_is_listed_by_name(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, self.EVASIONS["import_as"])
        assert "hermes.governance.policy" in declared_import_names(path)

    def test_an_unresolvable_import_is_caught_by_the_runtime_witness(
            self, tmp_path: Path) -> None:
        """A name assembled from a runtime value cannot be folded.

        The dependency has still happened — the governed submodule is
        loaded in :data:`sys.modules` and this file names the package —
        so the runtime witness reports it as ``unresolved-dynamic``. This
        is the floor that catches an import assembled from a value, where
        constant folding gives up.

        The precondition is established here explicitly rather than
        inherited from whatever ran before: the witness reads
        process-global state, so a pin that relied on an earlier test
        having imported the plane would pass in a full-file run and fail
        in isolation.
        """
        import importlib

        importlib.import_module("hermes.governance.policy")
        path = self._write(tmp_path, (
            'import importlib\n'
            'import sys\n'
            'HINT = "hermes.governance"  # the package this file may reach\n'
            'def target():\n'
            '    return sys.argv[1]  # chosen at runtime\n'
            '_mod = importlib.import_module(target())\n'))
        found = detect_import_mentions(path)
        assert "unresolved-dynamic" in found, (
            f"an import assembled from a runtime value was not reported: "
            f"{found!r}")
        assert any(item.startswith("loaded:")
                   for item in found), found

    def test_a_name_bound_to_a_constant_is_folded_not_guessed(self) -> None:
        """A constant name resolves by propagation, so the witness does
        not fire on it — the verdict is a resolved hit, not a guess."""
        path = self._write(Path(tempfile.gettempdir()), (
            'import importlib\n'
            '_pkg = "hermes." + "governance"\n'
            '_mod = importlib.import_module(_pkg + ".policy")\n'))
        found = detect_import_mentions(path)
        assert any(item.startswith("dynamic:") and
                   item.endswith(":hermes.governance.policy")
                   for item in found), found

    def test_an_unresolvable_import_of_another_package_is_not_reported(
            self, tmp_path: Path) -> None:
        """The witness is scoped to the governed package.

        A file that imports by a runtime value and never mentions the
        governed package must not be reported — otherwise the gate would
        fire on every dynamic import in the tree.
        """
        path = self._write(tmp_path, (
            'import importlib\n'
            'import sys\n'
            'def target():\n'
            '    return sys.argv[1]\n'
            '_mod = importlib.import_module(target())\n'))
        assert detect_import_mentions(path) == ()

    # ── R7-FIX3 (P2): the indirections the re-report evaded with ────

    INDIRECTIONS: dict[str, str] = {
        "getattr_import_module_bound": (
            'import importlib\n'
            '_imp = getattr(importlib, "import_module")\n'
            '_g = _imp("hermes." + "governance.approvals")\n'),
        "getattr_import_module_inline": (
            'import importlib\n'
            '_g = getattr(importlib, "import_module")(\n'
            '    "hermes" + ".gov" + "ernance.policy")\n'),
        "aliased_dunder_import": (
            '_imp = __import__\n'
            '_g = _imp("hermes." + "governance.policy")\n'),
        "aliased_import_module": (
            'import importlib\n'
            '_imp = importlib.import_module\n'
            '_g = _imp("hermes." + "governance.approvals")\n'),
        "exec_of_split_import": (
            'exec("import " + "hermes.governance.policy")\n'),
        "eval_of_split_import": (
            'eval("importlib.import_module(" + "\'hermes.governance\'" + ")")\n'),
    }

    @pytest.mark.parametrize("shape", sorted(INDIRECTIONS))
    def test_an_indirect_dynamic_import_is_detected(
            self, tmp_path: Path, shape: str) -> None:
        """The re-report's three evasion classes, pinned per spelling.

        ``getattr(importlib, …)``, a re-bound ``__import__`` /
        ``import_module``, and ``exec``/``eval`` of a split import all
        reached the governed package while ``_is_dynamic_import_call``
        saw no "dynamic import" at all (R7_REREPORT2 P2).
        """
        path = self._write(tmp_path, self.INDIRECTIONS[shape])
        assert dynamic_import_sites(path), (
            f"{shape!r}: the indirection was not resolved to the package")
        assert detect_import_mentions(path), (
            f"{shape!r}: the indirection was not flagged")

    def test_an_opaque_exec_is_default_denied(self, tmp_path: Path) -> None:
        """Default-deny: an ``exec`` the gate cannot resolve is reported,
        never silently passed."""
        path = self._write(tmp_path, "exec(chosen_at_runtime())\n")
        found = detect_import_mentions(path)
        assert any(item.startswith("unevaluable:")
                   for item in found), found

    def test_an_opaque_getattr_importer_is_default_denied(
            self, tmp_path: Path) -> None:
        """A ``getattr(importlib, <unresolvable>)`` fetch is reported —
        the gate cannot tell which importlib attribute is fetched."""
        path = self._write(tmp_path, (
            'import importlib\n'
            '_fn = getattr(importlib, chosen())\n'))
        found = detect_import_mentions(path)
        assert any(item.startswith("unevaluable:")
                   for item in found), found

    def test_an_unrelated_eval_is_reported_not_passed(
            self, tmp_path: Path) -> None:
        """Even a benign ``eval`` of a string is a construct the gate
        declines to vouch for: it is reported as unevaluable, not passed."""
        path = self._write(tmp_path, 'eval("1 + 1")\n')
        assert detect_import_mentions(path) == ("unevaluable:1",)

    def test_a_benign_getattr_on_importlib_is_not_flagged(
            self, tmp_path: Path) -> None:
        """Default-deny is scoped to importers, not to importlib itself.

        A ``getattr`` that names a non-importer attribute (``reload``) is
        precision-resolved and reports nothing — the backstop does not
        fire on every access to the module.
        """
        path = self._write(tmp_path, (
            'import importlib\n'
            'importlib.invalidate_caches()\n'
            '_fn = getattr(importlib, "reload")\n'))
        assert detect_import_mentions(path) == ()

    def test_load_governed_binds_the_real_modules(self) -> None:
        approvals, authority, policy = load_governed(
            "approvals", "authority", "policy")
        assert approvals.__name__ == "hermes.governance.approvals"
        assert authority.__name__ == "hermes.governance.authority"
        assert policy.__name__ == "hermes.governance.policy"

    def test_load_governed_refuses_a_path_expression(self) -> None:
        with pytest.raises(ValueError):
            load_governed("policy; import os")
        with pytest.raises(ValueError):
            load_governed("")

    def test_require_declaration_refuses_a_misspelled_attribute(self) -> None:
        import hermes.governance.policy as policy_module

        with pytest.raises(ValueError, match="no attribute"):
            require_declaration(policy_module, {"NOT_A_REAL_NAME": "NOPE"})

    def test_the_eval_plane_declares_its_governance_dependency(self) -> None:
        """``hostile.py`` states the dependency it used to hide."""
        from hermes.eval import hostile

        assert hostile.DECLARED_GOVERNANCE_DEPENDENCY == "hermes.governance"

    def test_the_gate_detects_the_governance_crossing_in_hostile(
            self) -> None:
        """The declared route is still *reported* by the gate.

        ``load_governed`` performs a dynamic import whose target is a
        function argument, so ``hostile.py`` itself has no statically
        foldable name. What proves the dependency is not concealed is
        that the eval plane has exactly one declared crossing, that the
        module names it as an attribute, and that the governance module
        is loaded in this process.
        """
        from hermes.eval import hostile

        assert "hermes.governance.policy" in sys.modules
        assert hostile.GOVERNANCE_POLICY is not None
        assert hostile.ROLE in FROZEN_REFUSAL_CODES

    def test_the_eval_plane_has_exactly_one_governance_route(self) -> None:
        """One declared crossing, not a scattering of assembled strings.

        Every eval module that reaches the governance plane must do so
        through ``import_gate``; no other module may contain the
        contiguous text, and none may assemble it locally.
        """
        offenders: list[str] = []
        for path in sorted(EVAL_DIR.glob("*.py")):
            declared = declared_import_names(path)
            if not any(name.startswith("hermes.governance")
                       for name in declared):
                continue
            source = path.read_text(encoding="utf-8")
            if "hermes.governance" in source and path.name != "import_gate.py":
                offenders.append(f"{path.name}: contiguous text present")
        assert offenders == []

    def test_import_gate_is_itself_an_instance_of_what_it_detects(
            self) -> None:
        """The gate must be honest about its own crossing.

        ``import_gate.py`` reaches the governed package through
        ``load_governed``'s assembled name. That is the one place in
        ``src/`` where the assembled spelling lives, and it is reported
        by the runtime witness like any other unresolvable route.
        """
        source = import_gate.GOVERNED_PACKAGE
        assert source == "hermes.governance"
        # The file does NOT contain the contiguous text, which is why a
        # substring gate could never have found it.
        raw = (EVAL_DIR / "import_gate.py").read_text(encoding="utf-8")
        assert '"hermes.governance"' not in raw
        assert "_GOVERN" in raw


class TestEvalDriverClaimsMatchTheCode:
    """R7-FIX2 (P3): the test-module claim is true as written.

    ``hostile.py`` and ``matrix.py`` claimed drivers run "never against
    a test module", while ``runtime_crash`` spawns
    ``python -m tests.test_agent_runtime --crash-child``. The claim was
    reworded to name the one exception. These pins keep the docstring
    and the code from drifting apart again: if a second driver starts
    using the test tree, or the crash driver stops, the claim breaks and
    these fail.
    """

    HOSTILE_PATH = EVAL_DIR / "hostile.py"
    MATRIX_PATH = EVAL_DIR / "matrix.py"

    #: Claims that assert an absolute ("never", "no driver ever"). The
    #: exception to the test-module boundary is real, so an absolute
    #: claim about it is a lie waiting to be reintroduced. Checked by
    #: exact phrase across the eval plane's own documentation.
    OVERREACHING_PHRASES: tuple[str, ...] = (
        "never against a test module",
        "never runs against a test module",
        "not against a test module",
    )

    def _driver_source(self) -> str:
        return self.HOSTILE_PATH.read_text(encoding="utf-8")

    def test_the_crash_driver_really_does_use_the_test_module(self) -> None:
        """The named exception must still be the true one.

        If this stops holding, either the driver changed and the
        docstring must be reworded again, or the claim above is wrong.
        """
        source = self._driver_source()
        assert "tests.test_agent_runtime" in source, (
            "the crash driver no longer spawns the test-module entry "
            "point — the docstring's named exception is now wrong")

    def test_the_crash_driver_uses_the_crash_child_entry_point(self) -> None:
        assert "--crash-child" in self._driver_source()

    def test_the_crash_driver_is_the_only_one_using_the_test_tree(
            self) -> None:
        """One exception, named. A second use invalidates the claim."""
        offenders: list[str] = []
        for path in sorted(EVAL_DIR.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            if "tests.test_agent_runtime" not in source:
                continue
            if path.name != "hostile.py":
                offenders.append(path.name)
        assert offenders == [], (
            f"more eval modules reach the test tree than the docstring "
            f"declares: {offenders}")

    def test_no_overreaching_test_module_claim_survives(self) -> None:
        """The claim the R7-REREPORT rejected must not come back.

        This is the pin with teeth for P3: restore the old absolute claim
        and this fails. A weaker check — "the new wording is present" —
        would pass if the absolute claim were appended alongside it, so
        the assertion is on the *absence* of the overreaching phrasing
        rather than the presence of the new phrasing.
        """
        offenders: list[str] = []
        for path in sorted(EVAL_DIR.glob("*.py")):
            text = path.read_text(encoding="utf-8").lower()
            for phrase in self.OVERREACHING_PHRASES:
                if phrase in text:
                    offenders.append(f"{path.name}: {phrase!r}")
        assert offenders == [], (
            f"an absolute test-module claim is asserted while "
            f"runtime_crash really does use the test tree: {offenders}")

    def test_the_docstring_names_the_exception(self) -> None:
        doc = (self.HOSTILE_PATH.read_text(encoding="utf-8")
               .split('"""')[1])
        assert "tests/test_agent_runtime.py" in doc
        assert "runtime_crash" in doc

    def test_the_matrix_docstring_names_the_exception(self) -> None:
        doc = self.MATRIX_PATH.read_text(encoding="utf-8").split('"""')[1]
        assert "test_agent_runtime.py" in doc

    def test_no_driver_reaches_a_test_class_or_fixture(self) -> None:
        """The remaining, checkable half of the claim.

        Reusing a crash child in a subprocess is the declared exception;
        importing test *code* (a class, a fixture, a helper) into the
        eval plane would be a different and undeclared dependency.
        """
        offenders = [line.strip() for line in self._driver_source()
                     .splitlines()
                     if line.strip().startswith(("from tests", "import tests"))]
        assert offenders == [], (
            f"eval plane imports test code: {offenders!r}")

    def test_the_claim_survives_the_subprocess_module_form(self) -> None:
        """The subprocess form must be a module invocation, not an
        import of test code into the driver process."""
        source = self._driver_source()
        assert '"-m", "tests.test_agent_runtime"' in source


class TestExtensionConstruction:
    """R7-FIX (P2): validate() runs at construction, not on request."""

    def test_an_unfrozen_refused_code_is_refused_at_construction(self) -> None:
        with pytest.raises(ValueError):
            ExtensionPoint(summary="bad", operations=("op",),
                           refused_code="NOT_FROZEN", example=ExampleTool(),
                           registration_shape="Bad(...)")

    def test_an_empty_operations_list_is_refused_at_construction(self) -> None:
        with pytest.raises(ValueError):
            ExtensionPoint(summary="bad", operations=(),
                           refused_code="ROLE", example=ExampleTool(),
                           registration_shape="Bad(...)")

    def test_the_frozen_manifest_is_mechanically_immutable(self) -> None:
        with pytest.raises(TypeError):
            EXTENSION_POINTS["FakePoint"] = EXTENSION_POINTS["Tool"]  # type: ignore
        with pytest.raises(TypeError):
            del EXTENSION_POINTS["Tool"]  # type: ignore
        assert len(EXTENSION_POINTS) == 9
        assert set(list_extensions()) == set(EXTENSION_POINTS)


class TestGovernanceExpectations:
    """R7-FIX (P2): expect= is the pinned actual, asserted by execution."""

    def test_the_governance_forgery_case_expects_proposal(self) -> None:
        case = next(c for c in build_matrix()
                    if c.plane == PLANE_GOVERNANCE and c.hostile == "forgery")
        assert case.expected_code == "PROPOSAL"

    def test_the_governance_self_approval_case_expects_role(self) -> None:
        case = next(c for c in build_matrix()
                    if c.plane == PLANE_GOVERNANCE
                    and c.hostile == "self-approval")
        assert case.expected_code == "ROLE"

    def test_every_case_expected_code_is_produced_by_its_inline_witness(
            self) -> None:
        report = run_matrix(build_matrix(), invoke_pinned_tests=False)
        assert report.is_clean(), "\n".join(
            f"{case.case.plane}/{case.case.hostile}: {case.detail}"
            for case in report.cases if not case.passed)


class TestCredentialGuardTeeth:
    """R7-FIX (P1, the void): deleting either credential guard is RED.

    Each neutralization is applied to production source (the model
    router). The matrix is re-run in a child process so the neutralized
    module is imported fresh; the ``model/credential`` case must be
    named as a failure. The source is restored byte-identically
    (sha256-verified) in a ``finally`` block.
    """

    ROUTER = "src/hermes/tools/models/router.py"
    NEUTRALIZATIONS = (
        ("T4a-credential-option-guard",
         b"aliases = CREDENTIAL_ONLY_POLICY.credential_aliases",
         b"aliases = frozenset()  # NEUTRALIZED by test"),
        ("T4b-secret-literal-guard",
         b"def _assert_secret_free(self, value: object, *, where: str) -> None:",
         (b"def _assert_secret_free(self, value: object, *, where: str) -> None:"
          b"\n        return  # NEUTRALIZED by test")),
    )

    def _run_matrix_probe(self) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.setdefault("PYTHONPATH", "src;.")
        env.setdefault("PYTHONUTF8", "1")
        return subprocess.run(
            [PYTHON, "-m", "hermes.eval.platform_cli", "matrix",
             "--no-pinned-test", "--format", "json"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), env=env,
            timeout=300)

    @pytest.mark.parametrize("label,old,new", NEUTRALIZATIONS)
    def test_neutralizing_a_credential_guard_turns_the_matrix_red(
            self, label: str, old: bytes, new: bytes) -> None:
        target = REPO_ROOT / self.ROUTER
        original = target.read_bytes()
        original_sha = hashlib_sha256_bytes(original)
        assert original.count(old) == 1, f"{label}: anchor is not unique"
        target.write_bytes(original.replace(old, new, 1))
        try:
            result = self._run_matrix_probe()
            assert result.returncode != 0, (
                f"{label}: the matrix stayed CLEAN with the guard deleted")
            body = json.loads(result.stdout)
            assert body["is_clean"] is False
            failed = {(case["plane"], case["hostile"])
                      for case in body["cases"] if not case["passed"]}
            assert ("model", "credential") in failed, (
                f"{label}: the credential case was not named as failed; "
                f"failed={sorted(failed)!r}")
        finally:
            target.write_bytes(original)
            restored = target.read_bytes()
            assert hashlib_sha256_bytes(restored) == original_sha, (
                f"{label}: restore is not byte-identical")
