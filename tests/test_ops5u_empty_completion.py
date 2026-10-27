"""OPS-5U — an empty completion is a failed sample, not a bad request.

Runs 32, 34, 35 and 36 each died the same way, and run 36 gave the body::

    "choices": [{"index": 0, "message": {"role": "assistant", "content": "",
                 "reasoning_content": "We are the planner agent. We need to
                 produce a single JSON object with kind, rationale, payload. …"}}]

A well-formed 200 whose ``content`` was empty because the model spent the whole
output budget on hidden reasoning. The plane already named the fact and named it
*permanent*, so one such sample killed the run with no retry: a sampling
variance was classified as an unanswerable request.

The change has two halves, and this file pins both:

1. **The sample is retryable.** ``content`` empty with
   ``finish_reason == "length"`` is raised in the transient channel carrying the
   hazard class ``EMPTY_COMPLETION`` — never ``MALFORMED_200``: the body parsed
   and the envelope was valid, the *draft* is what is missing — and the plane
   spends its ordinary retry budget on it, on the same candidate, exactly like a
   429 or a 500.
2. **Running out of samples fails the stage with the budget named.** A walk
   whose every attempt answered no draft ends as refusal-as-data under the
   frozen ``MALFORMED_PAYLOAD`` code carrying the provider's own sentence — the
   one that names ``output budget`` and ``max_output_tokens`` — instead of as an
   availability error that says nothing about what to raise.

The falsifiers, in the charter's order:

- an empty completion is retried and a subsequent good sample lets the stage
  proceed (``TestTheWalkIsRetried``, ``TestTheStage``);
- a persistent empty completion still fails the stage, with a code that names
  the budget (``test_a_walk_that_never_drafts_ends_as_a_refusal_naming_the_budget``,
  ``test_a_persistent_empty_completion_fails_the_stage_and_names_the_budget``);
- a 400/402 is still permanent — no retry (``TestWhatMustNotChange``);
- the retry budget bounds the attempts
  (``test_the_retry_budget_bounds_the_attempts``);
- baseline and census unchanged (the existing gate tests, run in the same
  targeted set).

The third finding is pinned at the end: the budget ``1677e7e`` declared for a
reasoning model never reached any live call. The wire carries the *smallest* of
three declared numbers, and two of them seal the raise — the plane policy's
4096 default for a cap-less call, and the planner profile's own ask of 3072,
which is what runs 32–36 actually ran at.
``TestTheDeclaredBudgetNeverReachedTheWire`` pins those numbers and the one
that binds; this slice changes none of them, because the number is inside the
recorded request body.

No network: every transport here is scripted, and ``_provider`` pins the egress
guard to a hermetic resolver.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from hermes.agents.runtime.config import load_profiles
from hermes.cli import main
from hermes.composition import (
    _PROVIDER_MAX_OUTPUT_TOKENS,
    CloudModelSpec,
    EnvCredentialResolver,
    build_cloud_provider,
    build_model_binding,
)
from hermes.config import HermesConfig, ModelTierConfig
from hermes.core.task_status import TaskStatus
from hermes.tools.models.router import (
    EMPTY_COMPLETION,
    MALFORMED_PAYLOAD,
    REFUSAL_CODES,
    ModelPlanePolicy,
    ModelProposal,
    ModelRefusal,
    ModelRequest,
    ModelRouter,
)
from hermes.tools.providers.base import TransportResponse
from hermes.tools.research_sources import (
    ProviderUnavailableError,
    RetryPolicy,
    TransientProviderError,
)
from tests.test_cloud_provider import (
    _PUBLIC,
    KEY,
    ScriptedTransport,
    _call,
    _openai_reply,
    _provider,
)
from tests.test_model_plane import (
    DIRECTOR_CONTRACT,
    _policy,
    _request,
    _router,
)
from tests.test_ops1_live_cli import (
    _install_transport,
    _methodology_task,
    _project,
    _ScriptedTransport,
    _status,
)
from tests.test_ops10_run_report import _config, _report_files

#: The reasoning model these runs were on: a code-owned 32 KiB output budget
#: (`_PROVIDER_MAX_OUTPUT_TOKENS`, 1677e7e).
REASONING_MODEL = "tokenharbor:deepseek-v4.1-flash"
REASONING_KEY = "TOKENHARBOR_API_KEY"

#: The reasoning run 36 was killed by, kept verbatim in the message field so the
#: "no reasoning text anywhere" pin has something hostile to look for.
RUN_36_REASONING = (
    "We are the planner agent. We need to produce a single JSON object with "
    "kind, rationale, payload. …")

#: The draft the *plane* accepts for `DIRECTOR_CONTRACT`: a kind and a rationale.
PLANE_DRAFT = json.dumps({"kind": "INSERT_TASK", "rationale": "because"})

#: The one draft the live path accepts for a one-stage document (OPS-5I: the
#: single-proposal form is the only one the plane and the runtime both accept).
LIVE_DRAFT = json.dumps({
    "rationale": "one ordinary task",
    "kind": "INSERT_TASK",
    "payload": {"spec": {"goal": "stage output"}},
    "delegations": [],
})

#: The frozen model-plane budget for a provider that declares nothing
#: (`DEFAULT_MAX_OUTPUT_TOKENS`) — the control for the wire pin below.
DEFAULT_BUDGET = 4_096

#: The budget `_PROVIDER_MAX_OUTPUT_TOKENS` declares for the reasoning provider.
DECLARED_BUDGET = 32_768


# ── helpers ──


def _no_draft(*, reasoning: str = RUN_36_REASONING,
              completion: int = 4_096) -> TransportResponse:
    """The reply this slice is about: a 200, an empty draft, a spent budget."""
    body = {
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "",
                        "reasoning_content": reasoning},
            "finish_reason": "length",
        }],
        "usage": {"prompt_tokens": 40, "completion_tokens": completion},
    }
    return TransportResponse(status=200, body=json.dumps(body).encode("utf-8"),
                             content_type="application/json")


def _status_response(status: int) -> TransportResponse:
    return TransportResponse(status=status, body=b"{}",
                             content_type="application/json")


def _plane_policy(**overrides: Any) -> ModelPlanePolicy:
    """One candidate and no fallbacks: the walk ends where it began.

    The default retry policy is `RetryPolicy(max_retries=2)`, so a walk that
    never drafts spends three attempts — the same shape the live plane has,
    where the policy's own default is three retries.
    """
    overrides.setdefault("tier_refs", {"s": "openai:test-gpt"})
    overrides.setdefault("fallback_chain", ())
    return _policy(**overrides)


def _rig(transport: ScriptedTransport, *,
         policy: ModelPlanePolicy | None = None
         ) -> tuple[ModelRouter, ModelRequest]:
    """The real cloud provider behind the real router, with a scripted edge."""
    provider = _provider(transport, dialect="openai")
    router = _router([provider],
                     policy=policy if policy is not None else _plane_policy())
    request = _request(tier="s", output_contract=DIRECTOR_CONTRACT)
    return router, request


# ═══════════════ 1. an empty completion is a retried sample ═══════════════


class TestTheWalkIsRetried:
    def test_a_no_draft_sample_is_retried_and_the_next_sample_answers(self) -> None:
        """Falsifier 1 — one empty sample costs one attempt, not the run."""
        transport = ScriptedTransport(_no_draft(), _openai_reply(PLANE_DRAFT))
        router, request = _rig(transport)

        result = router.invoke(request)

        assert isinstance(result, ModelProposal)
        assert result.structured["kind"] == "INSERT_TASK"
        assert len(transport.specs) == 2, "the sample was not retried"
        assert router.provider_attempts == 2
        rows = router.accounting()
        assert [row.outcome for row in rows] == ["TRANSIENT", "OK"]
        assert rows[0].attempt == 1
        assert rows[1].attempt == 2

    def test_the_failed_sample_is_legible_in_the_ledger(self) -> None:
        """The class says what happened; the status says it happened inside 200."""
        transport = ScriptedTransport(_no_draft(), _openai_reply(PLANE_DRAFT))
        router, request = _rig(transport)

        router.invoke(request)

        row = router.accounting()[0]
        assert row.outcome == "TRANSIENT"
        assert row.failure_class == EMPTY_COMPLETION
        assert row.http_status == 200
        assert "output budget" in row.failure_detail
        assert "max_output_tokens" in row.failure_detail

    def test_the_retried_attempt_asks_the_same_declared_question(self) -> None:
        """Same budget, same call: the retry is a new *sample*, not a new ask."""
        transport = ScriptedTransport(_no_draft(), _openai_reply(PLANE_DRAFT))
        router, request = _rig(transport)

        router.invoke(request)

        first, second = (json.loads(spec.body) for spec in transport.specs)
        assert first["max_tokens"] == second["max_tokens"] == DEFAULT_BUDGET
        rows = router.accounting()
        assert rows[0].normalized_request == rows[1].normalized_request

    @pytest.mark.parametrize("max_retries", [0, 1, 3])
    def test_the_retry_budget_bounds_the_attempts(self, max_retries: int) -> None:
        """Falsifier 4 — the bound is the policy's, and it is visible."""
        transport = ScriptedTransport(_no_draft())
        policy = _plane_policy(retry_policy=RetryPolicy(
            max_retries=max_retries, base_delay_seconds=1.0,
            max_delay_seconds=30.0, jitter=True))
        router, request = _rig(transport, policy=policy)

        result = router.invoke(request)

        assert isinstance(result, ModelRefusal)
        assert len(transport.specs) == max_retries + 1
        assert router.provider_attempts == max_retries + 1
        assert [row.attempt for row in router.accounting()] == \
            list(range(1, max_retries + 2))

    def test_a_walk_that_never_drafts_ends_as_a_refusal_naming_the_budget(
            self) -> None:
        """Falsifier 2 — the stage fails, and the record says what to raise."""
        transport = ScriptedTransport(_no_draft())
        router, request = _rig(transport)

        result = router.invoke(request)

        assert isinstance(result, ModelRefusal)
        assert result.code == MALFORMED_PAYLOAD
        assert "EMPTY_COMPLETION" in result.detail
        assert "output budget" in result.detail
        assert "max_output_tokens" in result.detail
        assert "3 attempt(s)" in result.detail
        # Terminal: the runtime must not spend its own re-prompt on a budget.
        assert result.contract_feedback is False

    def test_the_terminal_refusal_invents_no_ledger_row(self) -> None:
        """One row per provider attempt — the refusal is not a fourth call."""
        transport = ScriptedTransport(_no_draft())
        router, request = _rig(transport)

        result = router.invoke(request)

        assert isinstance(result, ModelRefusal)
        rows = router.accounting()
        assert len(rows) == len(transport.specs) == 3
        assert [row.attempt for row in rows] == [1, 2, 3]
        assert all(row.outcome == "TRANSIENT" for row in rows)
        # The refusal is accounted against the attempt that ended the walk.
        assert result.account is not None
        assert result.account.attempt == 3
        assert result.provider_id == "openai"
        assert result.model_id == "test-gpt"

    def test_the_reasoning_text_is_never_recorded(self) -> None:
        """No reasoning text in the ledger, the refusal or the failure detail."""
        marker = "MARKER-REASONING-2f7b1e"
        transport = ScriptedTransport(_no_draft(reasoning=marker))
        router, request = _rig(transport)

        result = router.invoke(request)

        assert isinstance(result, ModelRefusal)
        assert marker not in result.detail
        rendered = json.dumps([dataclasses.asdict(row)
                               for row in router.accounting()], default=str)
        assert marker not in rendered
        assert "reasoning" not in rendered.lower()

    def test_a_still_empty_walk_still_ends_in_a_refusal(self) -> None:
        """The retry is not a licence to loop: the last attempt ends it."""
        transport = ScriptedTransport(_no_draft(), _no_draft(), _no_draft())
        router, request = _rig(transport)

        result = router.invoke(request)

        assert isinstance(result, ModelRefusal)
        assert len(transport.specs) == 3

    def test_a_draft_after_two_empty_samples_still_answers(self) -> None:
        """The variance is real: three samples, one draft, one proposal."""
        transport = ScriptedTransport(_no_draft(), _no_draft(),
                                      _openai_reply(PLANE_DRAFT))
        router, request = _rig(transport)

        result = router.invoke(request)

        assert isinstance(result, ModelProposal)
        assert [row.outcome for row in router.accounting()] == \
            ["TRANSIENT", "TRANSIENT", "OK"]


# ═══════════════════ 2. what must not change ═══════════════════


class TestWhatMustNotChange:
    @pytest.mark.parametrize("status", [400, 402])
    def test_a_400_or_402_is_still_permanent_and_called_once(
            self, status: int) -> None:
        """Falsifier 3 — a permanent failure is not retried by this slice."""
        transport = ScriptedTransport(_status_response(status))
        router, request = _rig(transport)

        with pytest.raises(ProviderUnavailableError):
            router.invoke(request)

        assert len(transport.specs) == 1, "a permanent failure was retried"
        rows = router.accounting()
        assert [row.outcome for row in rows] == ["PERMANENT"]
        assert rows[0].attempt == 1
        assert rows[0].failure_class != EMPTY_COMPLETION

    def test_a_500_is_still_an_availability_failure(self) -> None:
        """The other transient shape keeps its own ending, unchanged."""
        transport = ScriptedTransport(_status_response(500))
        router, request = _rig(transport)

        with pytest.raises(ProviderUnavailableError):
            router.invoke(request)

        assert router.provider_attempts == 3
        rows = router.accounting()
        assert all(row.outcome == "TRANSIENT" for row in rows)
        assert all(row.failure_class != EMPTY_COMPLETION for row in rows)

    def test_empty_completion_is_not_a_refusal_code(self) -> None:
        """No new code: the frozen subset is exactly what it was."""
        assert EMPTY_COMPLETION not in REFUSAL_CODES
        assert MALFORMED_PAYLOAD in REFUSAL_CODES

    def test_an_empty_completion_with_stop_is_still_a_raw_reply(self) -> None:
        """Only ``finish_reason == "length"`` is this failure."""
        transport = ScriptedTransport(_openai_reply(""))
        provider = _provider(transport, dialect="openai")

        response = provider.invoke(_call(provider, provider_id="openai",
                                         model_id="test-gpt"))

        assert response.text == ""
        assert response.finish_reason == "stop"

    def test_the_provider_edge_raises_the_retryable_class(self) -> None:
        """The classification is at the edge, where the body is read."""
        transport = ScriptedTransport(_no_draft())
        provider = _provider(transport, dialect="openai")

        with pytest.raises(TransientProviderError) as info:
            provider.invoke(_call(provider, provider_id="openai",
                                  model_id="test-gpt"))

        assert info.value.hazard_class == EMPTY_COMPLETION
        assert info.value.http_status == 200
        assert info.value.recordable is True


# ═══════════════ 3. the stage: live, through the CLI ═══════════════


class TestTheStage:
    """The falsifiers at the surface the runs died on: the live CLI."""

    def _run(self, tmp_path: Path, monkeypatch: Any, *replies: TransportResponse,
             tiers: Mapping[str, str] | None = None, ticks: int = 1,
             key: str = REASONING_KEY) -> tuple[int, Any, Path, Any]:
        monkeypatch.setenv(key, KEY)
        transport = _ScriptedTransport(*replies)
        _install_transport(monkeypatch, transport)
        db = _project(tmp_path, _methodology_task())
        report_dir = tmp_path / "reports"
        cfg = _config(tmp_path, db, tiers=dict(tiers or {"m": REASONING_MODEL}),
                      run_dir=report_dir)
        rc = main(["--config", str(cfg), "run", "p1", "--ticks", str(ticks)])
        return rc, transport, report_dir, db

    @staticmethod
    def _report(report_dir: Path) -> dict[str, Any]:
        files = _report_files(report_dir)
        assert len(files) == 1, "the live run wrote no report"
        loaded: dict[str, Any] = json.loads(files[0].read_text(encoding="utf-8"))
        return loaded

    def test_a_live_stage_proceeds_after_one_empty_sample(
            self, tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
        """Falsifier 1, live: the run 36 body then a draft — the stage runs."""
        rc, _transport, report_dir, db = self._run(
            tmp_path, monkeypatch, _no_draft(), _openai_reply(LIVE_DRAFT))

        captured = capsys.readouterr()

        assert rc == 0
        assert _status(db, "meth-1") == TaskStatus.SUCCEEDED.value
        assert ("  model call 1: tier=m provider=tokenharbor "
                "model=deepseek-v4.1-flash TRANSIENT status=200 "
                "class=EMPTY_COMPLETION") in captured.out
        assert ("  model call 2: tier=m provider=tokenharbor "
                "model=deepseek-v4.1-flash OK") in captured.out
        report = self._report(report_dir)
        # The planner's retried tick, then its declared review child's own call.
        outcomes = [row["outcome"] for row in report["model_attempts"]]
        assert outcomes[:2] == ["TRANSIENT", "OK"]
        assert report["model_attempts"][0]["failure_class"] == EMPTY_COMPLETION
        assert report["stages"][0]["state"] == TaskStatus.SUCCEEDED.value

    def test_a_persistent_empty_completion_fails_the_stage_and_names_the_budget(
            self, tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
        """Falsifier 2, live: the run fails, and the record says what to raise."""
        rc, _transport, report_dir, db = self._run(
            tmp_path, monkeypatch, _no_draft())

        captured = capsys.readouterr()

        assert rc == 0, "an exhausted budget is a typed failure, not a crash"
        assert "Error:" not in captured.out
        status = _status(db, "meth-1")
        assert status == TaskStatus.RETRYING.value, status

        lines = [line for line in captured.out.splitlines()
                 if line.startswith("  model call ")]
        assert len(lines) == 4, "the retry budget is three retries plus the first"
        assert all("TRANSIENT status=200 class=EMPTY_COMPLETION" in line
                   for line in lines)

        report = self._report(report_dir)
        attempts = report["model_attempts"]
        assert [row["attempt"] for row in attempts] == [1, 2, 3, 4]
        assert all("output budget" in row["failure_detail"]
                   for row in attempts)
        assert all(row["failure_class"] == EMPTY_COMPLETION
                   for row in attempts)

        stage = report["stages"][0]
        assert stage["state"] == TaskStatus.FAILED.value
        assert stage["termination"] == "MODEL_REFUSED"
        assert stage["refusals"] == 1
        refusals = [entry for entry in report["refusals"]
                    if entry["code"] == MALFORMED_PAYLOAD]
        assert len(refusals) == 1
        assert "EMPTY_COMPLETION" in refusals[0]["detail"]
        assert "output budget" in refusals[0]["detail"]

    def test_the_stage_that_ends_here_records_no_draft(self) -> None:
        """A stage that failed produced nothing — not a silent success."""
        transport = ScriptedTransport(_no_draft())
        router, request = _rig(transport)

        result = router.invoke(request)

        assert isinstance(result, ModelRefusal)


# ═════════ 4. the declared budget's reach: what actually bound ═════════


class TestTheDeclaredBudgetNeverReachedTheWire:
    """``1677e7e`` raised a provider's budget; no live call ever carried it.

    Pinned because the plane's own records cannot tell the difference: the
    output bound a call carries is the *minimum* of three declared numbers
    (``router.py:_max_output_tokens``), and two of them seal the raise.

    1. the plane policy's ceiling — the composition's class default,
       ``DEFAULT_MAX_OUTPUT_TOKENS`` = 4096;
    2. the model profile's ceiling — for the reasoning model, the spec's
       declared budget (``_PROVIDER_MAX_OUTPUT_TOKENS["tokenharbor"]`` = 32768);
    3. the request's own ask — live, the stage profile's declaration
       (``profiles/planner.yaml: model_policy.max_output_tokens`` = 3072).

    A cap-less call is clamped to 4096 by (1), and every live call asks 3072 by
    (3), which is below both. So raising the provider's declared budget cannot
    change a live call in either direction, and runs 32–36 did not establish
    "the budget was not the only variable" — the budget variable was never
    varied at the surface they ran on. What they ran at was 3072.

    This slice changes no budget. The number is part of the recorded request
    body, and recorded fixtures are keyed by the redacted request
    (``normalized_request``, IDR-046 D4), so moving it is a declared-data change
    that has to be paired with a re-record — never a side effect of a
    classification fix.
    """

    @staticmethod
    def _binding(declared: int) -> tuple[Any, ScriptedTransport, Any]:
        spec = CloudModelSpec(provider_id="tokenharbor", dialect="openai",
                              model_id="deepseek-v4.1-flash",
                              api_key_env=REASONING_KEY,
                              max_output_tokens=declared)
        transport = ScriptedTransport(_openai_reply(PLANE_DRAFT))
        credentials = EnvCredentialResolver({"tokenharbor": REASONING_KEY},
                                            environ={REASONING_KEY: KEY})
        provider = build_cloud_provider([spec], credentials=credentials,
                                        transport=transport, resolve=_PUBLIC)
        cfg = HermesConfig(model_tiers=ModelTierConfig(m=REASONING_MODEL))
        binding = build_model_binding(cfg, [provider], credentials=credentials,
                                      default_tier="m")
        return binding, transport, provider

    def test_the_declaration_is_real_and_the_plane_default_seals_it(self) -> None:
        """(2) declares 32768, (1) answers 4096 — and the wire is (1)."""
        assert _PROVIDER_MAX_OUTPUT_TOKENS["tokenharbor"] == DECLARED_BUDGET
        binding, transport, provider = self._binding(DECLARED_BUDGET)

        assert provider.describe()[0].max_output_tokens == DECLARED_BUDGET

        result = binding.invoke(_request(tier="m",
                                         output_contract=DIRECTOR_CONTRACT))

        assert isinstance(result, ModelProposal)
        row = binding.model_ledger()[0]
        assert row.normalized_request["max_output_tokens"] == DEFAULT_BUDGET
        assert json.loads(transport.specs[0].body)["max_tokens"] == DEFAULT_BUDGET

    @pytest.mark.parametrize("asked,expected",
                             [(3_072, 3_072), (8_192, DEFAULT_BUDGET),
                              (1_000_000, DEFAULT_BUDGET)])
    def test_a_request_may_lower_the_cap_and_never_raise_it(
            self, asked: int, expected: int) -> None:
        """(3) under (1): the ask may lower the cap; nothing passes 4096."""
        binding, transport, _unused_provider = self._binding(DECLARED_BUDGET)
        assert isinstance(binding, object)

        result = binding.invoke(_request(tier="m", max_output_tokens=asked,
                                         output_contract=DIRECTOR_CONTRACT))

        assert isinstance(result, ModelProposal)
        assert json.loads(transport.specs[0].body)["max_tokens"] == expected

    def test_the_live_wire_carries_the_profiles_own_ask(
            self, tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
        """The live number: 3072 — the stage's declaration, under both ceilings.

        This is the number runs 32–36 were issued at, and the number this
        slice's retry re-asks: up to three samples at 3072, never one at 32768.
        """
        ask = load_profiles()["planner"].model_policy.max_output_tokens
        assert ask == 3_072
        assert ask < DEFAULT_BUDGET < DECLARED_BUDGET

        rc, transport, _report_dir, _db = TestTheStage()._run(
            tmp_path, monkeypatch, _openai_reply(LIVE_DRAFT))
        capsys.readouterr()

        assert rc == 0
        assert json.loads(transport.specs[0].body)["max_tokens"] == ask
