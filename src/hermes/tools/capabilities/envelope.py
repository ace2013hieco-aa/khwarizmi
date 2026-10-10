"""Capability plane — the invocation envelope (who / why / authority / inputs /
observation / artifact).

`ARCHITECTURE_DELTA.md` §2.2 requires that a capability call be reconstructible.
This module owns the record that makes that true, and it is built on **every**
invocation — success, hazard refusal, authority refusal, timeout, cancel and
idempotent replay alike. A refusal with no envelope would be exactly the
unreconstructible case worth auditing, so the builder always supplies an
observation section; a refusal sets it to `REFUSED` rather than leaving it out.

The plane still owns no durable state: `to_journal_note()` returns *data* for the
Orchestration API to journal (`repositories.py` remains the only journal writer,
§3.2). Nothing here writes, and nothing here mints an identity — `to_mapping()`
carries content digests, which are recomputed values rather than authored ids.

Redaction
---------
Recorded forms pass through `providers/redact.py`. The policy is
`RECORDING_POLICY`: credential-class names only, `default_deny=False`. The
provider wire policy's blanket default-deny is the wrong instrument here because
a capability's argument names come from a closed declared schema — an undeclared
name is a `MALFORMED_PAYLOAD` refusal, not something to mask — while a
credential-class name is refused outright before a call is built. Redaction is
therefore defence in depth behind two fail-closed guards, not the only control:

1. `undeclared_names()` — the closed schema (an undeclared argument refuses);
2. `credential_class_names()` — a credential-class name refuses, naming the
   parameter and never its value (the `RedactionError` rule).

`RECORDING_POLICY` is deliberately constructed here rather than imported from the
model plane: sibling planes must not depend on each other, and `redact.py` is
frozen by this round's no-existing-file-edits rule, so a shared constant is not
available. It is four lines of configuration derived from
`redact.DEFAULT_POLICY.credential_aliases` — the same aliases, no divergence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from hermes.tools.providers.redact import (
    DEFAULT_POLICY,
    RedactionPolicy,
    redact_params,
    redaction_policy_gaps,
)

__all__ = [
    "ENVELOPE_VERSION",
    "RECORDING_POLICY",
    "REQUIRED_SECTIONS",
    "EnvelopeAuthority",
    "EnvelopeInputs",
    "EnvelopeObservation",
    "InvocationEnvelope",
    "credential_class_names",
    "digest_of",
    "record_value",
    "redact_arguments",
    "redaction_gaps",
    "undeclared_names",
]

#: Envelope schema version. A future shape change bumps this rather than
#: reinterpreting an old record.
ENVELOPE_VERSION = "hermes-invocation-envelope/v1"

#: The sections that must be present on every recorded invocation.
REQUIRED_SECTIONS: tuple[str, ...] = (
    "who", "why", "authority", "inputs", "hazard", "rate_limit", "observation",
    "artifacts",
)

RECORDING_POLICY = RedactionPolicy(
    credential_aliases=DEFAULT_POLICY.credential_aliases,
    polite_identifiers=frozenset(),
    default_deny=False,
)


def record_value(value: Any) -> str:
    """One declared argument as a stable string for recording.

    Capability arguments are declared scalars (or arrays of scalars), so the
    recorded form is a flat string map. This is a deliberate difference from the
    model plane, which preserves nested structure: there the payload is a list of
    untrusted envelopes whose shape is part of the replay identity, whereas a
    capability argument set has no nesting to preserve.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return json.dumps([record_value(item) for item in value],
                          separators=(",", ":"))
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def redact_arguments(
    arguments: Mapping[str, Any],
    policy: RedactionPolicy = RECORDING_POLICY,
) -> dict[str, str]:
    """The redacted, recordable form of an argument set."""
    flat = {str(name): record_value(value) for name, value in arguments.items()}
    return redact_params(flat, policy)


def redaction_gaps(
    arguments: Mapping[str, Any],
    policy: RedactionPolicy = RECORDING_POLICY,
) -> tuple[str, ...]:
    """Names the policy cannot classify — the `redaction_policy_gap` note."""
    flat = {str(name): record_value(value) for name, value in arguments.items()}
    return redaction_policy_gaps(flat, policy)


def credential_class_names(
    names: Iterable[str],
    policy: RedactionPolicy = RECORDING_POLICY,
) -> tuple[str, ...]:
    """Names belonging to credential class, matched **exactly**.

    Exact rather than the policy's substring rule, for the same reason the model
    plane does it: a declared name such as `max_tokens` merely *contains* an
    alias, and the substring rule exists for open wire param dicts where
    `X-Api-Key` must not slip past. A capability's names come from a closed
    declared schema, so exactness is both sufficient and free of false positives.
    """
    aliases = policy.credential_aliases
    return tuple(sorted(
        str(name) for name in names if str(name).strip().lower() in aliases))


def undeclared_names(
    arguments: Mapping[str, Any],
    declared: Iterable[str],
) -> tuple[str, ...]:
    """Argument names the declared schema does not contain (closed schema)."""
    known = {str(name) for name in declared}
    return tuple(sorted(str(name) for name in arguments if str(name) not in known))


def digest_of(value: Any) -> str:
    """A content digest, recomputed here by rule.

    Recomputed, never authored or accepted from a caller: it identifies a
    recorded form for audit, and nothing in this plane treats it as an entity
    identity (§3.3).
    """
    raw = value if isinstance(value, bytes) else json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class EnvelopeAuthority:
    """The authority section: which grant decided, and how."""

    grant_id: str = ""
    profile: str = ""
    tool_sets: tuple[str, ...] = ()
    risk_ceiling: str = ""
    approved: bool = False
    decision: str = "NOT_EVALUATED"  # "GRANTED" | "REFUSED" | "NOT_EVALUATED"
    refusal_code: str = ""


@dataclass(frozen=True, slots=True)
class EnvelopeInputs:
    """The inputs section: the redacted argument form and its digest."""

    fields: Mapping[str, str] = field(default_factory=dict)
    digest: str = ""
    size_bytes: int = 0
    redaction_gaps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EnvelopeObservation:
    """The observation section — always present, even for a refusal."""

    status: str = "FAILED"
    failure: str = ""
    detail: str = ""
    digest: str = ""
    size_bytes: int = 0
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class InvocationEnvelope:
    """who → why → authority → what → result, recorded on every invocation.

    `is_complete()` is the provenance guarantee: all `REQUIRED_SECTIONS` are
    present and non-`None`. `reconstruct()` renders the narrative the journal note
    carries, so an auditor can answer who/why/what/result without re-deriving it.
    """

    capability_id: str
    tool_id: str
    invoked_at: str
    who_profile: str = ""
    lease_generation: str = ""
    why: str = ""
    idempotency_key: str = ""
    authority: EnvelopeAuthority = field(default_factory=EnvelopeAuthority)
    inputs: EnvelopeInputs = field(default_factory=EnvelopeInputs)
    hazard_class: str = ""
    hazard_reason: str = ""
    rate_decision: str = ""
    observation: EnvelopeObservation | None = None
    artifacts: tuple[str, ...] = ()
    envelope_version: str = ENVELOPE_VERSION

    # ── the provenance guarantee ──

    def sections(self) -> dict[str, Any]:
        return {
            "who": {"profile": self.who_profile,
                    "lease_generation": self.lease_generation},
            "why": self.why,
            "authority": {
                "grant_id": self.authority.grant_id,
                "profile": self.authority.profile,
                "tool_sets": list(self.authority.tool_sets),
                "risk_ceiling": self.authority.risk_ceiling,
                "approved": self.authority.approved,
                "decision": self.authority.decision,
                "refusal_code": self.authority.refusal_code,
            },
            "inputs": {
                "fields": dict(self.inputs.fields),
                "digest": self.inputs.digest,
                "size_bytes": self.inputs.size_bytes,
                "redaction_gaps": list(self.inputs.redaction_gaps),
            },
            "hazard": {"class": self.hazard_class, "reason": self.hazard_reason},
            "rate_limit": self.rate_decision,
            "observation": (
                None if self.observation is None else {
                    "status": self.observation.status,
                    "failure": self.observation.failure,
                    "detail": self.observation.detail,
                    "digest": self.observation.digest,
                    "size_bytes": self.observation.size_bytes,
                    "replayed": self.observation.replayed,
                }),
            "artifacts": list(self.artifacts),
        }

    def missing_sections(self) -> tuple[str, ...]:
        """Required sections that are absent or `None` (expected: empty)."""
        present = self.sections()
        return tuple(name for name in REQUIRED_SECTIONS
                     if name not in present or present[name] is None)

    def is_complete(self) -> bool:
        return not self.missing_sections()

    def to_mapping(self) -> dict[str, Any]:
        """The full record, ready for the Orchestration API to journal."""
        return {
            "envelope_version": self.envelope_version,
            "invoked_at": self.invoked_at,
            "capability_id": self.capability_id,
            "tool_id": self.tool_id,
            "idempotency_key": self.idempotency_key,
            **self.sections(),
        }

    def reconstruct(self) -> str:
        """The who → why → what → result narrative.

        Never empty, on every path: an unstated profile and an empty rationale
        are rendered as explicit markers rather than omitted, so "nobody said
        why" is visible in the record instead of invisible.
        """
        observation = self.observation
        parts = [
            f"who={self.who_profile or '<unstated>'}",
            f"lease={self.lease_generation or '<none>'}",
            f"why={self.why or '<unstated>'}",
            f"what={self.capability_id or '<none>'}/{self.tool_id or '<none>'}",
            f"authority={self.authority.decision}",
            f"result={observation.status if observation else '<missing>'}",
        ]
        if self.hazard_class and self.hazard_class != "NONE":
            parts.append(f"hazard={self.hazard_class}")
        if self.rate_decision:
            parts.append(f"rate={self.rate_decision}")
        if observation is not None and observation.failure:
            parts.append(f"failure={observation.failure}")
        if self.artifacts:
            parts.append(f"artifacts={len(self.artifacts)}")
        if self.idempotency_key:
            parts.append(f"key={self.idempotency_key}")
        return " | ".join(parts)

    def to_journal_note(self) -> dict[str, Any]:
        """A bounded, redacted note for a journal append by the Orchestration API.

        Returns data; it does not append. `repositories.py:92` remains the only
        journal writer (§3.2).
        """
        return {
            "envelope_version": self.envelope_version,
            "reconstruct": self.reconstruct(),
            "inputs_digest": self.inputs.digest,
            "observation_digest": (self.observation.digest
                                   if self.observation is not None else ""),
            "authority": self.authority.decision,
            "failure": (self.observation.failure
                        if self.observation is not None else ""),
            "complete": self.is_complete(),
        }
