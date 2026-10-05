"""Recorder-boundary redaction — the ONLY place a request form is created.

Step 1 of the Part 3 implementation (IDR-030 decision point 3 — the redaction
contract is ratified). Pure, stdlib-only, zero I/O.

Rules (contract §7, blueprint §6.2, PS-02/PS2-04/PS3-07):
- Credential-class param/header/path-segment names → ``"<redacted>"``.
- Polite-pool identifiers (`email`, `tool`) are *sent* on the wire but redacted in
  every record → ``"<redacted:<name>>"``.
- Unknown names → redacted under `default_deny` (fail-closed) with the name
  reported via `redaction_policy_gaps` so the policy set can be completed.
- Headers: `Authorization`, cookies, and any credential-class header name are
  redacted (PS-09).
- URLs: query params redacted; userinfo masked; a credential-class PATH SEGMENT
  masks the following segment (PS3-07 — a credential in a ``/{token}/…`` route).
- `RedactionError` (fail-closed, raised by the recorder when redaction cannot run)
  names the offending parameter, NEVER its value (PS3-07).

Redaction is applied once, at the recorder boundary — before logging, provenance,
events, or error messages; the S6 secrets-out validator remains the write-path
backstop (defense in depth, not the primary control).
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = [
    "DEFAULT_POLICY",
    "RedactionPolicy",
    "redact_headers",
    "redact_params",
    "redact_url",
    "redaction_policy_gaps",
]

# Header names that are credential-class regardless of the alias set (PS-09).
_CREDENTIAL_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie",
})


@dataclass(frozen=True)
class RedactionPolicy:
    """The redaction classification policy (contract §7 — the set is config)."""

    credential_aliases: frozenset[str]
    polite_identifiers: frozenset[str]
    default_deny: bool = True


DEFAULT_POLICY = RedactionPolicy(
    credential_aliases=frozenset({
        "api_key", "apikey", "key", "token", "access_token", "auth",
        "password", "secret", "signature",
    }),
    polite_identifiers=frozenset({"email", "tool"}),
)


def _classify(name: str, policy: RedactionPolicy) -> str | None:
    """Return the redaction form for a param/header NAME, or None to keep it.

    Classification is on the lowercased name (case-insensitive aliases).
    Returns the literal replacement, or None when the name is safe to keep.
    """
    key = name.lower()
    if key in policy.credential_aliases:
        return "<redacted>"
    if key in policy.polite_identifiers:
        return f"<redacted:{key}>"
    for alias in policy.credential_aliases:
        if alias in key:  # e.g. "X-Api-Key", "access_token_2"
            return "<redacted>"
    for polite in policy.polite_identifiers:
        if polite in key:
            return f"<redacted:{polite}>"
    return None


def redact_params(params: dict[str, str], policy: RedactionPolicy) -> dict[str, str]:
    """Redact a request-parameter dict. Unknown names are redacted under
    `default_deny` (fail-closed); the names are reported by
    `redaction_policy_gaps` so the policy set can be completed."""
    out: dict[str, str] = {}
    for name, value in params.items():
        replacement = _classify(name, policy)
        if replacement is not None:
            out[name] = replacement
        elif policy.default_deny:
            out[name] = "<redacted>"
        else:
            out[name] = value
    return out


def redaction_policy_gaps(params: dict[str, str], policy: RedactionPolicy) -> tuple[str, ...]:
    """Names that default-deny redacted because the policy cannot classify them —
    the `redaction_policy_gap` note content (contract §7.2). Deterministic order."""
    return tuple(
        name
        for name in sorted(params)
        if _classify(name, policy) is None and policy.default_deny
    )


def redact_headers(headers: dict[str, str], policy: RedactionPolicy) -> dict[str, str]:
    """Redact credential-class headers (PS-09): `Authorization`, cookies, and any
    header whose name contains a credential alias or polite identifier."""
    out: dict[str, str] = {}
    for name, value in headers.items():
        key = name.lower()
        if key in _CREDENTIAL_HEADERS:
            out[name] = "<redacted>"
            continue
        replacement = _classify(name, policy)
        if replacement is not None:
            out[name] = replacement
        elif policy.default_deny:
            out[name] = "<redacted>"
        else:
            out[name] = value
    return out


def _redact_path_segments(path: str, policy: RedactionPolicy) -> str:
    """PS3-07 — mask a credential in a ``/{token}/…`` route: a path segment whose
    lowercased name is a credential alias masks the FOLLOWING segment."""
    segments = path.split("/")
    out: list[str] = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        if seg and seg.lower() in policy.credential_aliases and i + 1 < len(segments):
            out.append(seg)
            out.append("<redacted>")
            i += 2
            continue
        out.append(seg)
        i += 1
    return "/".join(out)


def redact_url(url: str, policy: RedactionPolicy) -> str:
    """Redact a URL: query params (same classification as `redact_params`),
    userinfo, and credential-class path segments (PS3-07). Deterministic output —
    query params re-encoded in sorted order."""
    parts = urlsplit(url)
    # userinfo (user:pass@host) is credential-class by construction
    netloc = parts.netloc
    if "@" in netloc:
        netloc = "<redacted>@" + netloc.rsplit("@", 1)[1]
    # query params — same classification as the params dict
    raw_query: list[tuple[str, str]] = parse_qsl(parts.query, keep_blank_values=True)
    redacted_query: list[tuple[str, str]] = []
    for name, value in raw_query:
        replacement = _classify(name, policy)
        if replacement is not None:
            redacted_query.append((name, replacement))
        elif policy.default_deny:
            redacted_query.append((name, "<redacted>"))
        else:
            redacted_query.append((name, value))
    query = urlencode(sorted(redacted_query))
    path = _redact_path_segments(parts.path, policy)
    return urlunsplit((parts.scheme, netloc, path, query, ""))
