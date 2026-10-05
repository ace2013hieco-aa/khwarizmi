"""boundaries — the M3 untrusted-content envelope (trust boundary).

The Phase 0 contract stub is here implemented as the boundary that must
exist BEFORE any LLM wiring (M3 / HR-02 closure): the injection points
(``extract_fn`` / ``task_handlers`` / ``gate_verdict_fn``) carry a
documented + typed untrusted-input wrapper requirement, and fetched /
search free-text reaches a judgment surface ONLY as ``UntrustedContent``.

Contract
--------
1. ``UntrustedContent`` is the ONLY representation of untrusted source
   text at the context boundary — a frozen value carrying ``text`` +
   ``origin`` + ``ref`` (the source-record ref the text came from).
2. Its string forms (``str`` / ``repr``) NEVER contain the payload: an
   accidental interpolation into a judgment prompt, a log line, an
   error message, or a digest yields a visible marker, never the text.
   Deliberate use is the explicit ``.text`` field — a grep-auditable
   unwrap (``.text`` occurs at the exact seam that decides to trust).
3. It is NOT a ``str``: pyright strict rejects it where ``str`` is
   expected, and ``isinstance(c, str)`` is False at runtime — there is
   no silent coercion path from untrusted text into a typed judgment.
4. Reading persisted fetched/search text goes through
   ``UntrustedContentView`` (research/source_handlers.py) whose
   accessors return ``UntrustedContent`` only — never a raw ``str``.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["UntrustedContent"]


@dataclass(frozen=True, slots=True)
class UntrustedContent:
    """One envelope of untrusted source text (fetched payload, search
    title/venue/query, future spec free-text).

    The ONLY way untrusted text may cross the context boundary. The
    payload is reachable exclusively through the explicit ``.text``
    field; ``str()``/``repr()`` (and therefore any ``f"{...}"``
    interpolation, logging, or error message) show a marker with the
    origin and length — never the text itself.
    """

    text: str
    origin: str      # e.g. 'fetched' | 'search_result.title' | 'spec.free_text'
    ref: str = ""    # the source-record ref / artifact ref the text came from

    def __repr__(self) -> str:
        # The marker is the ONLY string form: no payload can leak through
        # logging, prompts, or errors built by interpolation.
        return (f"<UntrustedContent origin={self.origin!r} "
                f"ref={self.ref!r} len={len(self.text)}>")

    def __str__(self) -> str:
        return self.__repr__()