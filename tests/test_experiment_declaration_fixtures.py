"""Fixture pins for the declare-experiment authority DESIGN.

Design slice only: this module implements NO new authority. It proves the
specified schema/validator logic of ``docs/idr/EXPERIMENT-DECLARATION.md``
§1–§2 against fixtures with a test-local pure replica (no ``src/`` import
for the new kind, no gateway/validator/migration/resolver change, no DB, no
clock). A separate baseline lock asserts the 21-kind enumeration still holds
(no experiment kind) via a read-only ``src`` import.

Conventions mirrored (names only, test-local values):
ROLE / PROJECT_NOT_FOUND / MALFORMED_PAYLOAD / OPERATOR / PROPOSAL /
IDEMPOTENCY_CONFLICT / STALE / RATIONALE.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

import pytest

from hermes.core.intents import IntentKind

# ── baseline lock (§0.3: 21 kinds, no experiment kind) ──

_EXPECTED_KIND_COUNT = 22  # OPS-5Z Group E adds RECORD_VERIFICATION_OUTCOME


def test_intent_vocabulary_has_no_experiment_kind():
    kinds = {k.value for k in IntentKind}
    assert len(kinds) == _EXPECTED_KIND_COUNT
    assert "DECLARE_EXPERIMENT" not in kinds


def test_experiment_kind_in_no_partition():
    assert "DECLARE_EXPERIMENT" not in {k.value for k in IntentKind.llm_proposable()}
    assert "DECLARE_EXPERIMENT" not in {k.value for k in IntentKind.internal_only()}
    assert "DECLARE_EXPERIMENT" not in {k.value for k in IntentKind.director_only()}


# ── design replica (§1.1–§1.2, §2: pure, deterministic, no src writes) ──

DESIGN_CLOSED_KEYS = frozenset({
    "experiment_key",
    "title",
    "hypothesis_ref",
    "method_summary",
    "engine_descriptor",
    "human_decision_ref",
    "supersedes_ref",
})

ENGINE_DESCRIPTORS = frozenset({"unspecified", "execution-engine"})

_KEY_RE = re.compile(r"[A-Za-z0-9_-]+\Z")

MAX_KEY = 64
MAX_TITLE = 200
MAX_HYPOTHESIS = 500
MAX_METHOD = 3500
MAX_DECISION_REF = 128
MAX_SUPERSEDES_REF = 128
MAX_TOTAL_BYTES = 4096

# Stable refusal codes (names mirror the gateway table; values are local).
ROLE = "ROLE"
PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"
OPERATOR = "OPERATOR"
PROPOSAL = "PROPOSAL"
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
STALE = "STALE"
RATIONALE = "RATIONALE"


@dataclass(frozen=True, slots=True)
class DesignResult:
    admitted: bool
    code: str | None
    experiment_id: str | None


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def design_experiment_id(project_id: str, payload: Mapping[str, object]) -> str:
    """Content-hash identity (recomputed, never trusted)."""
    body = {
        "project_id": project_id,
        "experiment_key": payload["experiment_key"],
        "title": payload["title"],
        "hypothesis_ref": payload["hypothesis_ref"],
        "method_summary": payload["method_summary"],
        "engine_descriptor": payload["engine_descriptor"],
    }
    return "ex_" + hashlib.sha256(_canonical(body)).hexdigest()[:16]


def validate_design_declaration(
    payload: Mapping[str, object],
    *,
    proposed_by: str,
    project_id: str,
    project_exists: bool,
    credential_ok: bool,
    human_decision_ok: bool,
    admitted_heads: Mapping[str, str],
) -> DesignResult:
    """Test-local replica of the §1.2 ordered validator (pure)."""
    # 1. Role gate: human-gated default — only DETERMINISTIC ingestion passes.
    if proposed_by != "DETERMINISTIC":
        return DesignResult(admitted=False, code=ROLE, experiment_id=None)
    # 2. Project gate.
    if not project_exists or not project_id:
        return DesignResult(admitted=False, code=PROJECT_NOT_FOUND, experiment_id=None)
    # 3. Payload schema: closed keys, strict types, bounds, closed vocab.
    if set(payload.keys()) - DESIGN_CLOSED_KEYS or set(payload.keys()) != set(
        DESIGN_CLOSED_KEYS - {"supersedes_ref"} | {"supersedes_ref"}
    ):
        # Unknown key or missing key (all 7 keys required; supersedes may be None).
        unknown = set(payload.keys()) - DESIGN_CLOSED_KEYS
        missing = DESIGN_CLOSED_KEYS - set(payload.keys())
        if unknown or missing:
            return DesignResult(admitted=False, code=MALFORMED_PAYLOAD, experiment_id=None)
    key = payload["experiment_key"]
    title = payload["title"]
    hypothesis = payload["hypothesis_ref"]
    method = payload["method_summary"]
    engine = payload["engine_descriptor"]
    decision = payload["human_decision_ref"]
    supersedes = payload["supersedes_ref"]
    if (
        not isinstance(key, str)
        or not (1 <= len(key) <= MAX_KEY)
        or _KEY_RE.match(key) is None
        or ":" in key
    ):
        return DesignResult(admitted=False, code=MALFORMED_PAYLOAD, experiment_id=None)
    if not isinstance(title, str) or not (1 <= len(title) <= MAX_TITLE):
        return DesignResult(admitted=False, code=MALFORMED_PAYLOAD, experiment_id=None)
    if not isinstance(hypothesis, str) or not (1 <= len(hypothesis) <= MAX_HYPOTHESIS):
        return DesignResult(admitted=False, code=MALFORMED_PAYLOAD, experiment_id=None)
    if not isinstance(method, str) or not (1 <= len(method) <= MAX_METHOD):
        return DesignResult(admitted=False, code=MALFORMED_PAYLOAD, experiment_id=None)
    if not isinstance(engine, str) or engine not in ENGINE_DESCRIPTORS:
        return DesignResult(admitted=False, code=MALFORMED_PAYLOAD, experiment_id=None)
    if not isinstance(decision, str) or not (1 <= len(decision) <= MAX_DECISION_REF):
        return DesignResult(admitted=False, code=MALFORMED_PAYLOAD, experiment_id=None)
    if supersedes is not None and (
        not isinstance(supersedes, str) or not (1 <= len(supersedes) <= MAX_SUPERSEDES_REF)
    ):
        return DesignResult(admitted=False, code=MALFORMED_PAYLOAD, experiment_id=None)
    if len(_canonical(dict(payload))) > MAX_TOTAL_BYTES:
        return DesignResult(admitted=False, code=RATIONALE, experiment_id=None)
    # 4. Credential-exists.
    if not credential_ok:
        return DesignResult(admitted=False, code=OPERATOR, experiment_id=None)
    # 5. HumanDecision dereference + hash binding.
    if not human_decision_ok:
        return DesignResult(admitted=False, code=PROPOSAL, experiment_id=None)
    # 6-7. Domain: idempotency + head-only supersession.
    new_id = design_experiment_id(project_id, payload)
    head_id = admitted_heads.get(key if isinstance(key, str) else "")
    if head_id is None:
        if supersedes is not None:
            return DesignResult(admitted=False, code=STALE, experiment_id=None)
        return DesignResult(admitted=True, code=None, experiment_id=new_id)
    if new_id == head_id:
        return DesignResult(admitted=True, code=None, experiment_id=new_id)
    if supersedes != head_id:
        # Same key, different bytes, without naming the current head.
        if supersedes is None:
            return DesignResult(admitted=False, code=IDEMPOTENCY_CONFLICT, experiment_id=None)
        return DesignResult(admitted=False, code=STALE, experiment_id=None)
    return DesignResult(admitted=True, code=None, experiment_id=new_id)


def _valid_payload(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "experiment_key": "exp-001",
        "title": "Declared effect of alpha on beta",
        "hypothesis_ref": "H1: alpha reduces beta under gamma conditions",
        "method_summary": "Pre-registered comparison with fixed window and seed.",
        "engine_descriptor": "execution-engine",
        "human_decision_ref": "hd_abc123",
        "supersedes_ref": None,
    }
    base.update(over)
    return base


def _ctx(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "proposed_by": "DETERMINISTIC",
        "project_id": "proj-1",
        "project_exists": True,
        "credential_ok": True,
        "human_decision_ok": True,
        "admitted_heads": {},
    }
    base.update(over)
    return base


def _validate(payload: Mapping[str, object], ctx: Mapping[str, object]) -> DesignResult:
    admitted_heads = ctx["admitted_heads"]
    assert isinstance(admitted_heads, dict)
    return validate_design_declaration(
        payload,
        proposed_by=str(ctx["proposed_by"]),
        project_id=str(ctx["project_id"]),
        project_exists=bool(ctx["project_exists"]),
        credential_ok=bool(ctx["credential_ok"]),
        human_decision_ok=bool(ctx["human_decision_ok"]),
        admitted_heads=admitted_heads,
    )


def test_valid_declaration_admits_with_stable_id():
    r = _validate(_valid_payload(), _ctx())
    assert r.admitted and r.code is None and r.experiment_id is not None
    again = _validate(_valid_payload(), _ctx())
    assert again.experiment_id == r.experiment_id


def test_unspecified_engine_descriptor_admits():
    r = _validate(_valid_payload(engine_descriptor="unspecified"), _ctx())
    assert r.admitted and r.code is None


@pytest.mark.parametrize("proposed_by", ["LLM", "DIRECTOR", "RESEARCHER", "OPERATOR"])
def test_non_deterministic_proposer_refuses_role(proposed_by: str):
    r = _validate(_valid_payload(), _ctx(proposed_by=proposed_by))
    assert not r.admitted and r.code == ROLE


def test_missing_project_refuses():
    r = _validate(_valid_payload(), _ctx(project_exists=False))
    assert not r.admitted and r.code == PROJECT_NOT_FOUND


def test_bad_credential_refuses_operator():
    r = _validate(_valid_payload(), _ctx(credential_ok=False))
    assert not r.admitted and r.code == OPERATOR


def test_missing_human_decision_refuses_proposal():
    r = _validate(_valid_payload(), _ctx(human_decision_ok=False))
    assert not r.admitted and r.code == PROPOSAL


def test_unknown_key_refuses_malformed():
    payload = _valid_payload()
    payload["extra_key"] = "nope"
    r = _validate(payload, _ctx())
    assert not r.admitted and r.code == MALFORMED_PAYLOAD


def test_missing_key_refuses_malformed():
    payload = _valid_payload()
    del payload["title"]
    r = _validate(payload, _ctx())
    assert not r.admitted and r.code == MALFORMED_PAYLOAD


@pytest.mark.parametrize(
    "field,value",
    [
        ("experiment_key", "has:colon"),
        ("experiment_key", "has space"),
        ("experiment_key", ""),
        ("experiment_key", "x" * 65),
        ("title", ""),
        ("title", "t" * 201),
        ("hypothesis_ref", ""),
        ("method_summary", ""),
        ("engine_descriptor", "custom-engine-x"),
        ("engine_descriptor", ""),
        ("human_decision_ref", ""),
    ],
)
def test_field_bounds_refuse_malformed(field: str, value: str):
    r = _validate(_valid_payload(**{field: value}), _ctx())
    assert not r.admitted and r.code == MALFORMED_PAYLOAD


def test_oversize_total_refuses_rationale():
    r = _validate(_valid_payload(method_summary="m" * MAX_METHOD), _ctx())
    # Single max-length method field stays within the 4 KiB total: admits.
    assert r.admitted and r.code is None
    oversized = _valid_payload(
        method_summary="m" * MAX_METHOD,
        title="t" * MAX_TITLE,
        hypothesis_ref="h" * MAX_HYPOTHESIS,
    )
    assert len(_canonical(oversized)) > MAX_TOTAL_BYTES
    r2 = _validate(oversized, _ctx())
    assert not r2.admitted and r2.code == RATIONALE


def test_idempotent_repeat_admits_same_id():
    payload = _valid_payload()
    first = _validate(payload, _ctx())
    assert first.admitted and first.experiment_id is not None
    heads = {str(payload["experiment_key"]): str(first.experiment_id)}
    second = _validate(payload, _ctx(admitted_heads=heads))
    assert second.admitted and second.experiment_id == first.experiment_id


def test_same_key_different_bytes_without_supersedes_refuses_conflict():
    payload = _valid_payload()
    first = _validate(payload, _ctx())
    assert first.experiment_id is not None
    heads = {str(payload["experiment_key"]): str(first.experiment_id)}
    changed = _valid_payload(title="A different declared title")
    r = _validate(changed, _ctx(admitted_heads=heads))
    assert not r.admitted and r.code == IDEMPOTENCY_CONFLICT


def test_supersedes_non_head_refuses_stale():
    payload = _valid_payload()
    first = _validate(payload, _ctx())
    assert first.experiment_id is not None
    heads = {str(payload["experiment_key"]): str(first.experiment_id)}
    changed = _valid_payload(title="A different declared title", supersedes_ref="ex_deadbeef")
    r = _validate(changed, _ctx(admitted_heads=heads))
    assert not r.admitted and r.code == STALE


def test_supersedes_head_admits_new_id():
    payload = _valid_payload()
    first = _validate(payload, _ctx())
    assert first.experiment_id is not None
    heads = {str(payload["experiment_key"]): str(first.experiment_id)}
    changed = _valid_payload(title="A different declared title", supersedes_ref=first.experiment_id)
    r = _validate(changed, _ctx(admitted_heads=heads))
    assert r.admitted and r.code is None and r.experiment_id != first.experiment_id


def test_supersedes_without_existing_head_refuses_stale():
    r = _validate(_valid_payload(supersedes_ref="ex_deadbeef"), _ctx())
    assert not r.admitted and r.code == STALE


def test_registry_lookup_shape_is_project_scoped():
    """The §2 resolver contract: same key in another project does not admit."""
    payload = _valid_payload()
    first = _validate(payload, _ctx(project_id="proj-1"))
    assert first.experiment_id is not None
    # Resolver for proj-2 sees an empty head map: no cross-project fallback.
    other = _validate(payload, _ctx(project_id="proj-2", admitted_heads={}))
    assert other.admitted and other.code is None
    # Same bytes under a different project yield a different content id.
    assert other.experiment_id != first.experiment_id
