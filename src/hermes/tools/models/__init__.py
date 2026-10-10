"""Model plane — the provider-independent LLM port (ARCHITECTURE_DELTA §2.1).

The plane is a *port*, not an authority: it reaches models and returns
proposals/observations. Nothing it emits may decide a transition
(`evaluation.py` discipline, `AGENTS.md` "Determinism owns control").

Module layout:
  router.py — the whole plane: ModelProvider port, ModelRouter, record/replay
              transport, structured-output validation, streaming envelope,
              tool-call translation, retry/fallback, per-call accounting.

Import direction (§2.1/§3.1): this package imports `hermes.tools.*` and stdlib
only, plus `hermes.security.boundaries` for the untrusted-content envelope that
§2.1 *Outputs* explicitly requires every model output to carry (that module is
stdlib-only and imports nothing from Hermes, so the direction is not weakened).
It never imports `hermes.research`, `hermes.core` or `hermes.persistence`.

Re-exports are deliberately absent: `hermes.tools.__init__` stays an empty
surface so that importing the tools package never grows an eager edge into the
model plane (and, transitively, into the research layer through
`tools.research_sources`). Import `hermes.tools.models.router` directly.
"""

from __future__ import annotations

__all__: list[str] = []
