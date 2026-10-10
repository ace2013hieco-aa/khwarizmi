"""Production surface — auth, secrets, sandbox, limits, logs, metrics, backup, config.

R7 deliverable (b). Every enforcement in this module reuses the existing
frozen refusal vocabulary (``research.gateway`` / ``research.controller`` /
``agents.runtime.types`` / ``governance.policy`` / the methodology plane's
closed set, mirrored in ``matrix.FROZEN_REFUSAL_CODES``) — a new code is
introduced nowhere in this package.

Pure evaluation + enforcement: nothing here opens SQLite, opens a socket,
holds a clock, or reads a model. ``ops`` is the operator-facing surface; the
``apply_intent`` gateway is the **only** writer, and the ops layer refuses
any request that would author durable state outside that path.

Rules (R7 contract, ARCHITECTURE_DELTA §5):

* secrets never enter logs, never enter events, never enter intents;
* metrics / tracing hooks are no-op sinks by default — a caller may inject
  one and the no-op remains the safe default;
* sandbox confinement is a **boolean check**, not a sandbox itself: the
  caller states the sandbox path; the check returns a refusal if the
  declared scope escapes its root;
* resource limits are **enforced** by a wall-clock fence and a
  tick / token / memory budget the caller reports on the value
  object it threads through the run;
* backup / restore verification is a **digest** check — the caller
  supplies a file and a manifest, the check refuses if the digest does
  not match;
* config validation is a closed schema — unknown keys refuse, never
  silently dropped.

Stated limits (R7-FIX3). Two residual boundaries are recorded here
rather than chased, because both are properties of the problem:

* **Shape rules stay fenced.** The *shape* rules (`_BARE_SECRET_PATTERN`,
  `_RESERVED_TOKEN_PATTERN`) keep their `(?<!…)` / `(?!…)` word-boundary
  fences, so they do not match a credential abutted by more identifier
  characters. Dropping the fence is what makes a shape rule guess, and a
  rule broad enough to catch every bare literal was measured, against
  5,155 tokens harvested from this repository's own ``src/`` and
  ``tests/``, to destroy **82%** of ordinary log text
  (``R7_FIX2_REPORT.md`` §P1.3). The general answer to an abutted
  literal is therefore the **registered-literal affix rule**
  (:func:`_scrub_registered_literals`): a credential the caller actually
  holds is matched as a raw substring and absorbs its own glue, with no
  fence and no false-positive cost.
* **Split-secret reassembly is out of contract.** Redaction is applied
  per string (:func:`_redact_text`). A single secret split across two
  *positions* is redacted wherever either half is individually
  recognisable, but the layer does not reassemble a payload to test
  whether two individually-innocuous fragments concatenate into a
  credential. Multi-record reassembly is out of contract: the guarantee
  is that no half leaks verbatim *individually*, not that a reader
  cannot join two harmless fragments.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

from hermes.eval.matrix import FROZEN_REFUSAL_CODES

__all__ = [
    "OPS_REFUSAL_CODES",
    "AuthContext",
    "AuthError",
    "BackupManifest",
    "ConfigSchema",
    "ConfigValidationError",
    "CountingMetricsSink",
    "JsonLogSink",
    "NoOpLogSink",
    "NoOpMetricsSink",
    "OpsOutcome",
    "OpsRefusal",
    "Redaction",
    "ResourceBudget",
    "ResourceLimits",
    "SandboxCheck",
    "StructuredLogger",
    "authenticate",
    "check_sandbox_confinement",
    "enforce_resource_limits",
    "redact",
    "redact_payload",
    "register_secret",
    "validate_config",
    "verify_backup",
]

#: The refusal codes the ops surface is allowed to emit. A subset of the
#: frozen vocabulary — the ops layer never authors a state transition, so
#: it can only fail to act, not approve one.
OPS_REFUSAL_CODES: frozenset[str] = frozenset({
    "OPERATOR", "LOCK", "RATIONALE", "MALFORMED_PAYLOAD",
    "PROPOSAL", "ROLE", "STALE",
})


@dataclass(frozen=True, slots=True)
class OpsRefusal:
    """A refusal-as-data value returned by every ops surface.

    The shape mirrors the gateway's ``GatewayRejection`` so an ops-layer
    refusal is consumed by the same client code that consumes a
    spine-layer refusal. The code is always a member of
    :data:`OPS_REFUSAL_CODES` (a subset of the frozen vocabulary).
    """

    code: str
    detail: str
    surface: str   # which ops surface refused (auth / redact / sandbox / ...)
    field: str = ""

    def __post_init__(self) -> None:
        if self.code not in OPS_REFUSAL_CODES:
            raise ValueError(
                f"OpsRefusal code {self.code!r} is not in OPS_REFUSAL_CODES "
                f"{sorted(OPS_REFUSAL_CODES)}")
        if self.code not in FROZEN_REFUSAL_CODES:
            raise ValueError(
                f"OpsRefusal code {self.code!r} is not in FROZEN_REFUSAL_CODES "
                f"{sorted(FROZEN_REFUSAL_CODES)}")

    def as_dict(self) -> dict[str, Any]:
        return {"rejected": True, "code": self.code, "detail": self.detail,
                "surface": self.surface, "field": self.field}


@dataclass(frozen=True, slots=True)
class OpsOutcome:
    """The result of an ops-layer call. Either it is a ``value`` or a
    ``refusal``; the two are mutually exclusive.

    Constructing with both or with neither is an error — every ops call
    either acted or refused, never both, never neither.
    """

    value: Any = None
    refusal: OpsRefusal | None = None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.refusal is None):
            raise ValueError(
                f"OpsOutcome must have exactly one of value/refusal: "
                f"value={self.value!r}, refusal={self.refusal!r}")

    @classmethod
    def ok(cls, value: Any) -> "OpsOutcome":
        return cls(value=value)

    @classmethod
    def refused(cls, refusal: OpsRefusal) -> "OpsOutcome":
        return cls(refusal=refusal)

    def is_refusal(self) -> bool:
        return self.refusal is not None


# ────────────────────────────────────────────────────────────────────
# auth / credential handling
# ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AuthContext:
    """The verified operator-credential context.

    A token is never stored in this object — only its digest and a
    non-sensitive display label. The raw token is consumed at the auth
    boundary and dropped on the floor; the digest travels with the
    context so an audit trail can verify it without ever seeing the
    token.

    The context is *non-authoritative*: a final authority check still
    requires a recorded ``HumanDecisionReceived`` journal row
    (``research.gateway.py`` §"Spine's enforcement chain"). An ops
    context proves the operator is who they say they are; it does not
    prove a specific action was approved.
    """

    actor: str
    token_digest: str
    issued_at: float
    expires_at: float
    scopes: tuple[str, ...] = ()
    project_id: str = ""

    def is_expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at


class AuthError(ValueError):
    """Auth boundary rejected the supplied credentials."""


# Recognized token shapes (intentionally narrow; the ops layer is
# conservative about what it accepts).
_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^op_[A-Za-z0-9_\-]{16,128}\Z"),       # operator token
    re.compile(r"^svc_[A-Za-z0-9_\-]{16,128}\Z"),       # service token
    re.compile(r"^read_[A-Za-z0-9_\-]{16,128}\Z"),      # read-only token
)


def authenticate(
    *,
    actor: str,
    token: str,
    project_id: str = "",
    scopes: Sequence[str] = (),
    lifetime_seconds: float = 3600.0,
    now: float | None = None,
    clock: Callable[[], float] = time.time,
) -> OpsOutcome:
    """Verify an operator credential and return an :class:`AuthContext`.

    The auth boundary consumes the token and returns **only its
    digest** — the raw token never appears in the returned value, in
    any log, in any event, or in any intent payload. This is the
    "credentials never into intents/events/logs" rule from R7 (b).

    A token is malformed if its shape is unrecognised; a token is
    refused if the actor name is empty or if the requested scopes
    are empty (an actor with no scopes cannot act).
    """
    surface = "auth"
    if not isinstance(actor, str) or not actor.strip():
        return OpsOutcome.refused(OpsRefusal(
            code="ROLE", surface=surface,
            detail="auth: actor name is empty or non-string",
            field="actor"))
    if not isinstance(token, str) or not any(p.match(token) for p in _TOKEN_PATTERNS):
        return OpsOutcome.refused(OpsRefusal(
            code="OPERATOR", surface=surface,
            detail=f"auth: token does not match any known shape "
                   f"({[p.pattern for p in _TOKEN_PATTERNS]})",
            field="token"))
    if not scopes:
        return OpsOutcome.refused(OpsRefusal(
            code="ROLE", surface=surface,
            detail="auth: an actor must declare at least one scope",
            field="scopes"))
    # Token is well-formed; consume it. The digest is what travels.
    # Registering the consumed literal is what makes the *scrub* floor
    # work: from here on this exact credential is scrubbed out of every
    # log record, on every path, including free text that carries no
    # secret-shaped syntax. Shape matching cannot do this — the raw token
    # only has to look like *some* word to reach a log line.
    register_secret(token)
    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    issued_at = clock() if now is None else now
    expires_at = issued_at + max(0.0, float(lifetime_seconds))
    return OpsOutcome.ok(AuthContext(
        actor=actor, token_digest=token_digest,
        issued_at=issued_at, expires_at=expires_at,
        scopes=tuple(scopes), project_id=str(project_id)))


# ────────────────────────────────────────────────────────────────────
# secrets redaction
# ────────────────────────────────────────────────────────────────────


#: Regex patterns the redactor uses. Each pattern is anchored to the
#: start of a key in a payload mapping. Adding to this list is the
#: ONLY way to widen redaction coverage — there is no implicit name
#: match (a key must be declared).
_DEFAULT_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)^.*token.*$"), "TOKEN"),
    (re.compile(r"(?i)^.*password.*$"), "PASSWORD"),
    (re.compile(r"(?i)^.*passwd.*$"), "PASSWD"),
    (re.compile(r"(?i)^.*passphrase.*$"), "PASSPHRASE"),
    (re.compile(r"(?i)^.*secret.*$"), "SECRET"),
    (re.compile(r"(?i)^.*api[_-]?key.*$"), "API_KEY"),
    (re.compile(r"(?i)^.*private[_-]?key.*$"), "PRIVATE_KEY"),
    (re.compile(r"(?i)^.*signing[_-]?key.*$"), "SIGNING_KEY"),
    (re.compile(r"(?i)^key$|^.*[_-]key$"), "KEY"),
    (re.compile(r"(?i)^pin([_-].*)?$|^.*[_-]pin([_-].*)?$"), "PIN"),
    (re.compile(r"(?i)^.*credential.*$"), "CREDENTIAL"),
    (re.compile(r"(?i)^.*db[_-]?creds?.*$"), "DB_CREDS"),
    (re.compile(r"(?i)^.*authorization.*$"), "AUTHORIZATION_HEADER"),
    (re.compile(r"(?i)^.*auth[_-]?header.*$"), "AUTH_HEADER"),
    (re.compile(r"(?i)^.*session[_-]?id.*$"), "SESSION_ID"),
    (re.compile(r"(?i)^.*cookie.*$"), "COOKIE"),
)


@dataclass(frozen=True, slots=True)
class Redaction:
    """The redaction policy.

    ``patterns`` is a tuple of ``(regex, label)``; a key whose name
    matches a regex is replaced with the label. ``placeholder`` is
    the literal value that replaces the original value. ``replacement_format``
    formats the placeholder (e.g. ``"<{label}>"`` -> ``"<TOKEN>"``).
    """

    patterns: tuple[tuple[re.Pattern[str], str], ...] = _DEFAULT_REDACTION_PATTERNS
    placeholder: str = "<REDACTED:{label}>"

    @classmethod
    def default(cls) -> "Redaction":
        return cls()


def _is_secret_key(key: Any, patterns: Sequence[tuple[re.Pattern[str], str]]
                   ) -> str | None:
    """Return the redaction label for ``key`` if it matches a pattern, else
    ``None``. The key is matched as a string."""
    if not isinstance(key, str):
        return None
    for pattern, label in patterns:
        if pattern.match(key):
            return label
    return None


#: The redaction label declared for each secret-key pattern, lowercased.
#: The label is the ops layer's own statement of what it considers secret
#: material, so it is the vocabulary the free-text rule below is built
#: from. Deriving the text rule from the declared labels (rather than a
#: hand-copied word list) is what keeps the key path and the text path on
#: one list: widening a declaration widens both, and a secret word cannot
#: be redacted in one position but not the other.
def _declared_secret_words() -> tuple[str, ...]:
    words: set[str] = set()
    for _pattern, label in _DEFAULT_REDACTION_PATTERNS:
        words.add(label.lower())
        # ``api_key`` also covers the ``api-key`` and ``apikey`` spellings,
        # and a longer key that ends in a declared word (``operator_token``)
        # is caught by the prefix group in the pattern below.
        for part in label.lower().split("_"):
            if part:
                words.add(part)
    return tuple(sorted(words, key=len, reverse=True))


_SECRET_TEXT_PATTERN: re.Pattern[str] = re.compile(
    r"(?i)\b[A-Za-z0-9]*_?(?:" +
    "|".join(re.escape(w) for w in _declared_secret_words()) +
    r")\s*[=:]\s*(?:bearer\s+|basic\s+)?[^\s,;)\]}\"']+"
)

#: Reserved tokens the ops layer itself recognizes
#: (``ops._TOKEN_PATTERNS``). A token-shaped word in free text is
#: credential material by the ops layer's own admission rule, so it is
#: redacted whole rather than only past its 16th character.
_RESERVED_TOKEN_PATTERN: re.Pattern[str] = re.compile(
    r"(?<![A-Za-z0-9])(?:op|svc|read)_[A-Za-z0-9_-]{8,}(?![A-Za-z0-9])"
)

#: A bare, keyword-less credential shape: ``<alpha>-<alpha…><digits>``.
#:
#: This is the only rule that catches a secret interpolated into a log
#: message with nothing around it — no key name, no ``bearer`` prefix, no
#: reserved prefix, and too short for the entropy floors above. It was
#: chosen by measurement, not taste: against 5,155 tokens harvested from
#: this repository's own source and tests, this shape is the one rule
#: that catches that case with **zero** false positives. The rejected
#: alternatives are recorded in ``R7_FIX2_REPORT.md`` — a rule with more
#: separators matches model ids and dates (``claude-3-5-sonnet-20241022``),
#: one allowing ``_`` matches ``abstract_sha256`` and ``MALFORMED_200``,
#: and one matching any 10+ character run matches 82% of all log text.
#:
#: The shape is deliberately narrow, and the registered-literal floor
#: below remains the general answer: shape matching covers what a shape
#: can recognise, and :func:`register_secret` covers the credential the
#: caller actually holds. The fence is kept by measurement: a rule that
#: also matched an abutted literal matched 82% of the repository's own
#: log-shaped text (module docstring, "Stated limits"). An abutted
#: *registered* literal is closed by the affix rule instead
#: (:func:`_scrub_registered_literals`), which needs no fence because it
#: matches an exact literal rather than a shape.
_BARE_SECRET_PATTERN: re.Pattern[str] = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]{4,}-[A-Za-z]*[A-Za-z]\d{3,}(?![A-Za-z0-9])"
)

#: Secrets registered at runtime. A caller holding a live credential
#: registers it once (``register_secret``); every later record is scrubbed
#: of that exact literal, on every path. Shape matching cannot cover a
#: value carrying no secret-shaped syntax, so registered literals are the
#: floor beneath the patterns — the same fail-closed guard the model plane
#: applies to its own live credentials
#: (``tools/models/router.py`` ``_assert_secret_free``).
_REGISTERED_SECRETS: frozenset[str] = frozenset()


def register_secret(value: str | None) -> None:
    """Register a live secret literal so every redaction scrubs it.

    Idempotent. A value shorter than 8 characters is refused rather than
    registered: a literal that short occurs in ordinary text, and
    scrubbing it would make every record unreadable rather than safer.
    """
    global _REGISTERED_SECRETS
    if not isinstance(value, str) or len(value) < 8:
        return
    _REGISTERED_SECRETS = _REGISTERED_SECRETS | {value}


#: The identifier alphabet absorbed as *glue* around a registered
#: literal. A registered credential abutted by word characters is still
#: that credential — ``sekret-abc123tail`` carries the secret, and
#: stopping the redaction at ``…123`` would leave the credential's own
#: suffix readable (the re-report's "suffix glue" leak). The class is
#: exactly ``[A-Za-z0-9_-]``: whitespace, punctuation and the
#: placeholder's own ``<`` / ``>`` delimiters are not absorbed, so a
#: neighbouring token is never swallowed.
_GLUE_CHARS: frozenset[str] = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789_-")


def _scrub_registered_literals(text: str) -> str:
    """Replace every registered literal with the placeholder, absorbing
    adjacent ``[A-Za-z0-9_-]`` glue into the same replacement.

    A registered literal is matched as a **raw substring**, with no
    word-boundary fence: the caller told us this exact byte sequence is
    credential material, so an occurrence abutted by further identifier
    characters (``sekret-abc123tail``, ``idsekret-abc123x``,
    ``sekret-abc123op_Zz9…``) is the same secret wearing a suffix or a
    prefix, not a different word. The fence that protects the *shape*
    rules from false positives is deliberately absent here — a shape has
    to guess, an exact literal does not (module docstring, "Stated
    limits").

    Linear scan, not a regex: a variable literal with a ``*`` glue class
    on both sides invites backtracking, and a log payload is not a place
    to spend it. Iteration is over the sorted set, so the result is
    independent of ``PYTHONHASHSEED``; the scan re-reads its own output so
    a chain of two registered literals is scrubbed whole.
    """
    if not _REGISTERED_SECRETS:
        return text
    for secret in sorted(_REGISTERED_SECRETS):
        pieces: list[str] = []
        cursor = 0
        length = len(text)
        span = len(secret)
        while cursor < length:
            hit = text.find(secret, cursor)
            if hit < 0:
                pieces.append(text[cursor:])
                break
            start = hit
            while start > 0 and text[start - 1] in _GLUE_CHARS:
                start -= 1
            end = hit + span
            while end < length and text[end] in _GLUE_CHARS:
                end += 1
            pieces.append(text[cursor:start])
            pieces.append("<REDACTED:STRING>")
            cursor = end
        text = "".join(pieces)
    return text


def redact(value: Any, policy: Redaction | None = None) -> Any:
    """Recursively redact a JSON-like value.

    Strings matching common secret patterns (``bearer …``, ``token=…``,
    long base64 / hex) are replaced with ``<REDACTED:STRING>``. A mapping
    **key** is scrubbed by the same text rules as a value, so a secret
    spelled into a key name is removed too; keys matching the policy's
    regex list additionally have their *values* replaced with the
    policy's placeholder. Lists are walked; primitives other than strings
    are returned unchanged.

    The redaction is **deterministic** and **idempotent**: redacting a
    redacted value returns the same redacted value, and a value that
    is not a secret is returned byte-for-byte unchanged.
    """
    if policy is None:
        policy = Redaction.default()
    return _redact_walk(value, policy, _seen=set())


# A small list of common in-string secret shapes. These are *value-side*
# guards: a free-text payload may contain a bearer token or an API key
# even though the field name is innocuous.
_STRING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.=]{16,}"),
    re.compile(r"(?i)(?:api[_-]?key|token|secret)\s*[=:]\s*[A-Za-z0-9_\-\.=]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"(?<![A-Za-z0-9])[A-Fa-f0-9]{32,}(?![A-Za-z0-9])"),    # 32+ hex chars
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9])"),  # 20+ base64 chars
)


def _redact_text(value: str) -> str:
    """Scrub one free-text string: declared shapes first, then registered
    literals, then the reserved-token shapes.

    Every string in a payload passes through here, whatever position it
    occupies — a field value, a context value, the ``message`` text of a
    log record, or a mapping **key**. That is the point: no position is
    a separate surface with weaker rules, it is the same rules applied to
    a string.
    """
    out = value
    # Order matters, most specific first. ``op_<token>`` must be consumed
    # by the reserved-token rule BEFORE the entropy rules run: the
    # base64-tail rule matches the tail of a reserved token and would
    # otherwise consume it, leaving the ``op_`` prefix readable — a
    # partly-redacted credential that still advertises its own shape.
    out = _RESERVED_TOKEN_PATTERN.sub("<REDACTED:STRING>", out)
    out = _SECRET_TEXT_PATTERN.sub("<REDACTED:STRING>", out)
    out = _BARE_SECRET_PATTERN.sub("<REDACTED:STRING>", out)
    for pat in _STRING_PATTERNS:
        out = pat.sub("<REDACTED:STRING>", out)
    # Registered literals last: an exact literal is the most specific
    # fact we hold, and a replacement can only ever remove the secret
    # from the string, never introduce another. Unlike a shape, the
    # registered match is unfenced and absorbs its own identifier glue
    # (``sekret-abc123tail`` → one placeholder), which is how an abutted
    # literal is closed without widening the shape rules.
    out = _scrub_registered_literals(out)
    return out


def _redact_walk(value: Any, policy: Redaction,
                 _seen: set[int]) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        # Guard against cycles in pathological payloads.
        if id(value) in _seen:
            return value
        _seen.add(id(value))
        result: dict[Any, Any] = {}
        for k, v in value.items():
            # The KEY is a string in the payload like any other, so it
            # passes through the same scrubber a value does. Before this,
            # a secret spelled into a key name reached the sink verbatim
            # while its *value* was replaced — `{"note_token_<secret>":
            # "<REDACTED:TOKEN>"}` looks scrubbed and is not. Both the
            # affix case (secret tucked inside a secret-shaped name) and
            # the bare/reserved-token case are covered, because the key
            # is scrubbed first and the label rule below only decides
            # whether the value is replaced.
            safe_key = _redact_walk(k, policy, _seen)
            if isinstance(safe_key, str) and safe_key in result:
                # Two distinct keys scrubbed to the same placeholder:
                # keep both rather than let one silently overwrite the
                # other. The suffix is an ordinal, never secret material.
                suffix = 2
                while f"{safe_key}#{suffix}" in result:
                    suffix += 1
                safe_key = f"{safe_key}#{suffix}"
            label = _is_secret_key(k, policy.patterns)
            if label is not None:
                result[safe_key] = policy.placeholder.format(label=label)
            else:
                result[safe_key] = _redact_walk(v, policy, _seen)
        return result
    if isinstance(value, (list, tuple)):
        if id(value) in _seen:
            return value
        _seen.add(id(value))
        walked = [_redact_walk(item, policy, _seen) for item in value]
        return type(value)(walked)
    return value


def redact_payload(payload: Mapping[str, Any],
                   policy: Redaction | None = None) -> Mapping[str, Any]:
    """Redact a payload mapping. Convenience wrapper used by the audit path.

    Refuses with ``RATIONALE`` if the payload is not a mapping (the
    redaction expects a structured shape, not a free-form value).
    """
    if not isinstance(payload, Mapping):
        return {"rejected": True, "code": "RATIONALE",
                "detail": "redact_payload: payload is not a mapping",
                "surface": "redact"}
    return redact(dict(payload), policy)  # type: ignore[return-value]


# ────────────────────────────────────────────────────────────────────
# sandbox confinement
# ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SandboxCheck:
    """A confinement declaration. The path is the declared scope root;
    the candidates are the paths an executor may touch.
    """
    root: str
    candidates: tuple[str, ...]

    def all_within(self) -> bool:
        """True iff every candidate is contained in the root."""
        root_abs = os.path.realpath(self.root)
        for c in self.candidates:
            try:
                c_abs = os.path.realpath(c)
            except (OSError, ValueError):
                return False
            # Containment: c is within root if root is a prefix of c
            # (and they're not the same file). On Windows the prefix
            # match is case-insensitive; the test suite is OS-agnostic.
            if not _path_within(c_abs, root_abs):
                return False
        return True


def _path_within(candidate: str, root: str) -> bool:
    """True iff ``candidate`` is the root or under the root.

    Cross-platform: on Windows the comparison is case-insensitive.
    """
    norm = os.path.normpath
    c = norm(candidate)
    r = norm(root)
    if os.name == "nt":
        c = c.lower()
        r = r.lower()
    if c == r:
        return True
    # Use os.path.commonpath for a robust check; if the commonpath
    # equals the root, the candidate is inside it. (Commonpath raises
    # if paths are on different drives — we treat that as a refusal.)
    try:
        common = os.path.commonpath([c, r])
    except ValueError:
        return False
    return common == r


def check_sandbox_confinement(check: SandboxCheck) -> OpsOutcome:
    """Verify that every candidate path is contained in the root.

    Refuses with ``MALFORMED_PAYLOAD`` if the root is empty or not a
    string. Refuses with ``PROPOSAL`` if any candidate escapes the
    root. Returns the check on success — the caller may rely on the
    type for downstream logging.
    """
    surface = "sandbox"
    if not isinstance(check, SandboxCheck):
        return OpsOutcome.refused(OpsRefusal(
            code="MALFORMED_PAYLOAD", surface=surface,
            detail="sandbox: not a SandboxCheck"))
    if not isinstance(check.root, str) or not check.root.strip():
        return OpsOutcome.refused(OpsRefusal(
            code="MALFORMED_PAYLOAD", surface=surface,
            detail="sandbox: root is empty or non-string",
            field="root"))
    if not check.all_within():
        return OpsOutcome.refused(OpsRefusal(
            code="PROPOSAL", surface=surface,
            detail="sandbox: at least one candidate escapes the declared root",
            field="candidates"))
    return OpsOutcome.ok(check)


# ────────────────────────────────────────────────────────────────────
# resource-limit enforcement
# ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """The closed resource-limit vocabulary. None = unbounded (forbidden
    in production but allowed in tests).

    The counters are **exclusive** bounds: with ``max_ticks=5`` the
    fifth tick is allowed and the sixth refuses. The same boundary
    holds for ``max_tokens`` and ``max_memory_bytes``.
    """
    max_wall_clock_seconds: float | None = None
    max_ticks: int | None = None
    max_tokens: int | None = None
    max_memory_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    """The mutable state of a single execution's resource budget.
    The owner checks ``is_exhausted`` after every step and stops
    immediately on a refusal.
    """
    limits: ResourceLimits
    started_at: float
    ticks: int = 0
    tokens: int = 0
    memory_bytes: int = 0
    last_check_at: float = 0.0

    def is_exhausted(self, now: float | None = None) -> tuple[bool, str]:
        """True + the exhausted dimension, else ``(False, "")``.

        Fail-closed on a malformed clock reading: a ``now`` that is not
        a finite number, is earlier than ``started_at``, or moves
        backwards relative to ``last_check_at`` is reported as
        ``"clock"`` rather than silently comparing false. The wall
        clock and the counters are caller-reported by contract — the
        value object is frozen, so the enforcement sees the value the
        caller threads back, and a caller that keeps a stale binding
        can bypass it (documented limit, not a silent one).
        """
        if self.limits.max_wall_clock_seconds is not None:
            now_t = now if now is not None else time.time()
            if (not isinstance(now_t, (int, float))
                    or not math.isfinite(float(now_t))
                    or float(now_t) < self.started_at
                    or (self.last_check_at
                        and float(now_t) < self.last_check_at)):
                return True, "clock"
            if (float(now_t) - self.started_at) > self.limits.max_wall_clock_seconds:
                return True, "wall_clock"
        if self.limits.max_ticks is not None and self.ticks > self.limits.max_ticks:
            return True, "ticks"
        if self.limits.max_tokens is not None and self.tokens > self.limits.max_tokens:
            return True, "tokens"
        if (self.limits.max_memory_bytes is not None
                and self.memory_bytes > self.limits.max_memory_bytes):
            return True, "memory"
        return False, ""

    def record_tick(self, tokens_used: int = 0) -> "ResourceBudget":
        # Frozen dataclass: ``record_tick`` returns a fresh instance
        # with the updated counters, never mutating in place.
        return replace(self,
                      ticks=self.ticks + 1,
                      tokens=self.tokens + int(tokens_used))

    def record_memory(self, bytes_used: int) -> "ResourceBudget":
        # The caller reports the observed usage; enforcement refuses
        # whatever the caller reports (it cannot audit the process).
        return replace(self, memory_bytes=int(bytes_used))

    def with_check_at(self, now: float) -> "ResourceBudget":
        return replace(self, last_check_at=now)


def enforce_resource_limits(
    budget: ResourceBudget,
    *,
    now: float | None = None,
) -> OpsOutcome:
    """Refuse if any limit is exhausted. The caller is expected to call
    this after every step; the function is **pure** (no I/O, no clock
    read unless ``now`` is None).
    """
    surface = "limits"
    if not isinstance(budget, ResourceBudget):
        return OpsOutcome.refused(OpsRefusal(
            code="MALFORMED_PAYLOAD", surface=surface,
            detail="limits: not a ResourceBudget"))
    exhausted, kind = budget.is_exhausted(now=now)
    if exhausted:
        if kind == "wall_clock":
            return OpsOutcome.refused(OpsRefusal(
                code="RATIONALE", surface=surface,
                detail=f"limits: wall-clock budget exhausted "
                       f"({budget.limits.max_wall_clock_seconds}s)",
                field="max_wall_clock_seconds"))
        if kind == "ticks":
            return OpsOutcome.refused(OpsRefusal(
                code="RATIONALE", surface=surface,
                detail=f"limits: tick budget exhausted "
                       f"({budget.limits.max_ticks} ticks)",
                field="max_ticks"))
        if kind == "tokens":
            return OpsOutcome.refused(OpsRefusal(
                code="RATIONALE", surface=surface,
                detail=f"limits: token budget exhausted "
                       f"({budget.limits.max_tokens} tokens)",
                field="max_tokens"))
        if kind == "memory":
            return OpsOutcome.refused(OpsRefusal(
                code="RATIONALE", surface=surface,
                detail=f"limits: memory budget exhausted "
                       f"({budget.limits.max_memory_bytes} bytes)",
                field="max_memory_bytes"))
        if kind == "clock":
            return OpsOutcome.refused(OpsRefusal(
                code="MALFORMED_PAYLOAD", surface=surface,
                detail="limits: clock reading is malformed (non-finite, "
                       "before started_at, or moving backwards)",
                field="now"))
    return OpsOutcome.ok(budget)


# ────────────────────────────────────────────────────────────────────
# structured JSON logs
# ────────────────────────────────────────────────────────────────────


class NoOpLogSink:
    """A log sink that discards every record. The default."""

    def emit(self, record: Mapping[str, Any]) -> None:
        return None


class JsonLogSink:
    """A log sink that serialises each record as one JSON line to a stream.

    The default stream is :data:`sys.stdout`; a caller may pass a
    different stream (an open file, a ``io.StringIO``, etc.) for
    testing or to redirect the audit trail.
    """

    def __init__(self, stream: Any = None) -> None:
        if stream is None:
            import sys
            stream = sys.stdout
        self._stream = stream

    def emit(self, record: Mapping[str, Any]) -> None:
        # Defense in depth: ``StructuredLogger.emit`` redacts every record
        # it builds before calling this sink; a direct caller of the sink
        # is redacted here too, so no sink call can write a secret-shaped
        # key or value verbatim. Any value that is not JSON-serialisable
        # is coerced to its repr afterwards.
        safe_record = redact(record)
        try:
            line = json.dumps(_safe_json(safe_record), sort_keys=True,
                              ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            line = json.dumps({"_log_error": str(exc)}, sort_keys=True)
        self._stream.write(line + "\n")
        flush = getattr(self._stream, "flush", None)
        if callable(flush):
            with contextlib.suppress(Exception):
                flush()


def _safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    if isinstance(value, Mapping):
        return {str(k): _safe_json(v) for k, v in value.items()}
    return repr(value)


@dataclass(frozen=True, slots=True)
class StructuredLogger:
    """The structured logger: a name, a sink, a context, and a redactor.

    ``context`` is a frozen mapping included in every record. Every
    field value, every context value **and the message text itself**
    passes through :func:`redact` before the record reaches the sink — a
    secret-shaped key or value is replaced with its redaction placeholder
    and never written verbatim, whatever the caller passed.

    The message is redacted by the same rules as a field value, not by a
    weaker message-only rule: the record is assembled first and the whole
    record is passed through one redaction, so a secret interpolated into
    ``f"authenticated {token}"`` is scrubbed exactly as the same token
    passed as a field would be. ``JsonLogSink`` redacts again on its own
    side as defense in depth.
    """

    name: str
    sink: Any = field(default_factory=NoOpLogSink)
    context: Mapping[str, Any] = field(default_factory=dict)
    redaction: Redaction = field(default_factory=Redaction.default)

    def emit(self, level: str, message: str, **fields: Any) -> None:
        record: dict[str, Any] = {
            "ts": time.time(),
            "name": self.name,
            "level": str(level),
            # The message is redacted with the record below, in the same
            # pass as every field and context value.
            "message": str(message),
        }
        for k, v in self.context.items():
            record.setdefault(str(k), v)
        for k, v in fields.items():
            record[str(k)] = v
        # Redact at emit: the record the sink receives carries no
        # secret-shaped key or value in any position.
        self.sink.emit(redact(record, self.redaction))


# ────────────────────────────────────────────────────────────────────
# metrics / tracing hooks (no-op sinks by default)
# ────────────────────────────────────────────────────────────────────


class NoOpMetricsSink:
    """A metrics sink that discards every observation. The default."""

    def observe(self, name: str, value: float, **labels: Any) -> None:
        return None

    def increment(self, name: str, value: float = 1.0, **labels: Any) -> None:
        return None


class CountingMetricsSink:
    """A simple metrics sink that counts observations.

    Useful for tests and for a low-cardinality audit summary. A
    production deployment would replace this with a Prometheus / OTLP
    adapter.
    """

    def __init__(self) -> None:
        self.counts: dict[tuple[str, frozenset[tuple[str, str]]], float] = {}
        self.observations: list[tuple[str, float, dict[str, Any]]] = []

    def _key(self, name: str, labels: Mapping[str, Any]) -> tuple[str, frozenset[tuple[str, str]]]:
        return (name, frozenset((str(k), str(v)) for k, v in labels.items()))

    def observe(self, name: str, value: float, **labels: Any) -> None:
        self.observations.append((str(name), float(value), dict(labels)))
        key = self._key(name, labels)
        self.counts[key] = self.counts.get(key, 0.0) + 1.0

    def increment(self, name: str, value: float = 1.0, **labels: Any) -> None:
        key = self._key(name, labels)
        self.counts[key] = self.counts.get(key, 0.0) + float(value)


#: The default metrics sink. Every consumer in this package uses it
#: unless the caller wires a different one in.
DEFAULT_METRICS_SINK: Any = NoOpMetricsSink()


# ────────────────────────────────────────────────────────────────────
# backup / restore verification
# ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BackupManifest:
    """A manifest for a single backup artifact.

    ``sha256_hex`` is the digest the caller declares for the file at
    ``path``. The verification re-derives the digest and refuses if
    the two do not match.
    """
    path: str
    sha256_hex: str
    byte_size: int


def _digest_file(path: str) -> tuple[str, int]:
    h = hashlib.sha256()
    total = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
            total += len(chunk)
    return h.hexdigest(), total


#: A declared SHA-256 digest: exactly 64 lowercase hex characters.
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}\Z")


def verify_backup(manifest: BackupManifest) -> OpsOutcome:
    """Verify that the file at ``manifest.path`` matches its declared digest.

    Refuses with ``MALFORMED_PAYLOAD`` if the manifest is malformed.
    Refuses with ``STALE`` if the digest does not match (the
    on-disk content is no longer what the manifest claims).
    """
    surface = "backup"
    if not isinstance(manifest, BackupManifest):
        return OpsOutcome.refused(OpsRefusal(
            code="MALFORMED_PAYLOAD", surface=surface,
            detail="backup: not a BackupManifest"))
    # Format gate first: a declared digest that is not 64 lowercase hex
    # chars is a malformed *manifest*, not a stale artifact. Without
    # this, "A" * 64 and "z" * 64 reach the content comparison and are
    # reported as STALE (a claim about the file) rather than
    # MALFORMED_PAYLOAD (a claim about the manifest).
    if not manifest.sha256_hex or _SHA256_HEX_RE.match(
            manifest.sha256_hex) is None:
        return OpsOutcome.refused(OpsRefusal(
            code="MALFORMED_PAYLOAD", surface=surface,
            detail="backup: sha256_hex must be 64 lowercase hex chars",
            field="sha256_hex"))
    if manifest.byte_size < 0:
        return OpsOutcome.refused(OpsRefusal(
            code="MALFORMED_PAYLOAD", surface=surface,
            detail="backup: byte_size must not be negative",
            field="byte_size"))
    try:
        actual, size = _digest_file(manifest.path)
    except FileNotFoundError:
        return OpsOutcome.refused(OpsRefusal(
            code="STALE", surface=surface,
            detail=f"backup: file {manifest.path!r} does not exist",
            field="path"))
    except OSError as exc:
        return OpsOutcome.refused(OpsRefusal(
            code="STALE", surface=surface,
            detail=f"backup: cannot read {manifest.path!r}: {exc}",
            field="path"))
    if actual != manifest.sha256_hex:
        return OpsOutcome.refused(OpsRefusal(
            code="STALE", surface=surface,
            detail=f"backup: digest mismatch on {manifest.path!r}: "
                   f"declared={manifest.sha256_hex}, actual={actual}",
            field="sha256_hex"))
    # The declared size is enforced unconditionally — ``byte_size`` is a
    # required field, so there is no "0 means unknown" escape hatch.
    if size != manifest.byte_size:
        return OpsOutcome.refused(OpsRefusal(
            code="STALE", surface=surface,
            detail=f"backup: size mismatch on {manifest.path!r}: "
                   f"declared={manifest.byte_size}, actual={size}",
            field="byte_size"))
    return OpsOutcome.ok(manifest)


# ────────────────────────────────────────────────────────────────────
# config validation
# ────────────────────────────────────────────────────────────────────


class ConfigValidationError(ValueError):
    """A config refused by the closed schema."""


@dataclass(frozen=True, slots=True)
class ConfigSchema:
    """A closed config schema: a frozenset of allowed keys plus a
    mapping of required keys to their value type.

    Adding to the schema is the only way to allow a new config key;
    there is no implicit allow / passthrough.
    """
    allowed_keys: frozenset[str]
    required_keys: frozenset[str] = frozenset()
    value_types: Mapping[str, type] = field(default_factory=dict)

    def validate(self, data: Mapping[str, Any], *,
                 surface: str = "config") -> OpsOutcome:
        if not isinstance(data, Mapping):
            return OpsOutcome.refused(OpsRefusal(
                code="MALFORMED_PAYLOAD", surface=surface,
                detail="config: payload is not a mapping"))
        unknown = sorted(set(data) - self.allowed_keys)
        if unknown:
            return OpsOutcome.refused(OpsRefusal(
                code="MALFORMED_PAYLOAD", surface=surface,
                detail=f"config: unknown keys: {unknown}",
                field=",".join(unknown)))
        missing = sorted(self.required_keys - set(data))
        if missing:
            return OpsOutcome.refused(OpsRefusal(
                code="MALFORMED_PAYLOAD", surface=surface,
                detail=f"config: missing required keys: {missing}",
                field=",".join(missing)))
        for key, expected in self.value_types.items():
            if key in data and not isinstance(data[key], expected):
                return OpsOutcome.refused(OpsRefusal(
                    code="MALFORMED_PAYLOAD", surface=surface,
                    detail=f"config: key {key!r} has wrong type "
                           f"(expected {expected.__name__}, got "
                           f"{type(data[key]).__name__})",
                    field=key))
        return OpsOutcome.ok(dict(data))


def validate_config(schema: ConfigSchema, data: Mapping[str, Any],
                    *, surface: str = "config") -> OpsOutcome:
    """Convenience wrapper: validates ``data`` against ``schema``."""
    return schema.validate(data, surface=surface)
