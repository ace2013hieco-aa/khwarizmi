"""S6 Bounded event payloads (v4 §8.1, S6) — persistence-boundary validation.

Validates events at the persistence boundary, not only in callers. This is
the deterministic validator on the write path required by v4 §8.1/S6:

1. Payload size cap (default 4 KiB; larger payloads → artifact ref)
2. Event-type schema validation (known types only)
3. Secret rejection (tokens, passwords, private keys never in payloads)
4. Artifact-reference overflow path for large information

This validator is called by the repository's _append_event method before
the INSERT, so it cannot be bypassed by callers (IDR-013, S6).
"""
from __future__ import annotations

import json
import re
from typing import Any

from hermes.core.events import EventType

# Default payload size cap: 4 KiB (v4 §8.1, S6, §27 item 10/12)
DEFAULT_PAYLOAD_MAX_BYTES = 4096

# The canonical event catalog (v4 §8.1) — ONE authority: the `EventType`
# enum in `hermes.core.events`. ADV-05: validation DERIVES the accepted set
# from the enum instead of maintaining an independent literal set, so the two
# can never diverge again (the pre-fix literal set had silently accreted five
# names the enum never declared — `EvidenceTransitionProposed`,
# `BudgetExceeded`, `SourceRetracted`, `ThesisInvestigationCompleted`,
# `IterationAdvanced` — all now enum members).
KNOWN_EVENT_TYPES = frozenset(e.value for e in EventType)

# Secret patterns to reject in event payloads
# These are pattern matches on field names and values
_SECRET_FIELD_PATTERNS = re.compile(
    r"(?i)(password|passwd|pwd|secret|api_key|apikey|access_key|"
    r"private_key|client_secret|token|bearer|credential|auth_token)"
)

_SECRET_VALUE_PATTERNS = re.compile(
    r"(?i)("
    r"sk-[a-zA-Z0-9]{20,}"           # OpenAI-style API keys
    r"|gho_[a-zA-Z0-9]{36}"          # GitHub OAuth tokens
    r"|ghp_[a-zA-Z0-9]{36}"          # GitHub PAT tokens
    r"|ghs_[a-zA-Z0-9]{36}"          # GitHub server tokens
    r"|AKIA[A-Z0-9]{16}"             # AWS access keys
    r"|-----BEGIN [A-Z]+ PRIVATE KEY-----"  # PEM private keys
    r"|xox[baprs]-[a-zA-Z0-9-]+"    # Slack tokens
    r")"
)


class EventValidationError(Exception):
    """Raised when an event fails persistence-boundary validation (S6)."""

    def __init__(self, reason: str, field: str = ""):
        self.reason = reason
        self.field = field
        super().__init__(f"Event validation failed: {reason}" + (f" (field: {field})" if field else ""))


def validate_event_type(event_type: str) -> None:
    """Reject unknown event types (S6)."""
    if not event_type or not isinstance(event_type, str):
        raise EventValidationError("event_type must be a non-empty string", "event_type")
    if event_type not in KNOWN_EVENT_TYPES:
        raise EventValidationError(
            f"unknown event type '{event_type}' — not in v4 §8.1 catalog",
            "event_type",
        )


def validate_payload_size(payload: dict[str, Any] | None, max_bytes: int = DEFAULT_PAYLOAD_MAX_BYTES) -> None:
    """Reject oversized payloads (S6, default 4 KiB cap)."""
    if payload is None:
        return
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    if len(serialized) > max_bytes:
        raise EventValidationError(
            f"payload size {len(serialized)} bytes exceeds cap {max_bytes} — "
            f"use artifact reference instead (v4 §8.1/S6)",
            "payload_json",
        )


def validate_no_secrets(payload: dict[str, Any] | None) -> None:
    """Reject obvious secret-bearing fields/patterns (S6, §18).

    This is a defense-in-depth check, not a universal secret-content scanner.
    It catches:
    - Field NAMES matching secret patterns (password, token, api_key, etc.)
    - Field VALUES matching known secret FORMATS (sk-*, ghp_*, AKIA*, PEM keys,
      Slack tokens)

    It does NOT catch:
    - JWT bearer tokens in innocuous-named fields (value format not in the regex)
    - Plain password strings in innocuous-named fields (field name doesn't match)
    
    The primary defense is typed payload schemas with no secret fields (S6);
    this validator is the deterministic backstop on the write path.

    ADV-03: the walk is RECURSIVE over every permitted payload container
    (dict, list, tuple) — the pre-fix walker descended into dicts only, so a
    secret inside a list (e.g. ``{"evidence": [{"api_key": ...}]}``) or a
    bare secret string inside a list bypassed the scanner entirely. Field-name
    patterns apply to dict keys at every depth; value patterns apply to every
    string at every depth (including bare strings inside lists/tuples).
    """
    if payload is None:
        return

    def _walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                full_path = f"{path}.{key}" if path else key
                # Check field names for secret-like patterns
                if _SECRET_FIELD_PATTERNS.search(str(key)):
                    raise EventValidationError(
                        f"field name '{full_path}' matches secret pattern — "
                        f"secrets never enter payloads",
                        full_path,
                    )
                _walk(item, full_path)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                _walk(item, f"{path}[{index}]")
        elif isinstance(value, str) and _SECRET_VALUE_PATTERNS.search(value):
            # Check string values for known secret formats (at every depth,
            # including bare strings inside lists/tuples — ADV-03).
            raise EventValidationError(
                    f"value in '{path}' matches known secret format — rejected",
                    path,
                )

    _walk(payload, "")


def validate_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    max_payload_bytes: int = DEFAULT_PAYLOAD_MAX_BYTES,
) -> None:
    """Full persistence-boundary validation for an event (S6).

    Called by the repository's _append_event before INSERT. This is the
    deterministic validator on the write path required by v4 §8.1/S6.
    """
    validate_event_type(event_type)
    validate_payload_size(payload, max_payload_bytes)
    validate_no_secrets(payload)
