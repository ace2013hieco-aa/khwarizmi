"""Capability plane — Tool → ToolSet → Capability (ARCHITECTURE_DELTA §2.2).

The plane is the *one gated execution path* for bounded capabilities: it
declares what may run, decides whether a given caller may run it, gates the
call, and records an envelope. It is not an authority and holds no store: it
returns observations (untrusted, evidence-shaped) and refusals (data), and
admission is the Orchestration API's write boundary.

Module layout:
  types.py    — closed schemas: Tool, Capability, ToolSet, ToolGrant,
                CapabilitySet, InvokeRequest, ToolResult, Observation, plus the
                refusal-code provenance sets and the failure taxonomy.
  registry.py — declarations and discovery: `CapabilityRegistry.enumerate()`
                (operation 1) and the B-3 named-composition slot, with plugin
                participation as declared data only.
  invoke.py   — the gated execution path: `CapabilityInvoker.invoke()`
                (operation 2), pipeline order fixed and load-bearing.
  envelope.py — the who/why/authority/inputs/observation/artifact record built
                on *every* invocation, success, failure, refusal and replay.

Import direction (§2.2/§3.1): this package imports `hermes.tools.*` and stdlib
only, plus `hermes.security.boundaries` for the untrusted-content envelope every
observation payload must carry (that module is stdlib-only and imports nothing
from Hermes, so the direction is not weakened). It never imports
`hermes.research`, `hermes.core` or `hermes.persistence`. The two recorded
exceptions in the wider tree are untouched here: this plane reads hazard
*vocabulary* from `tools/providers/hazards.py` (a `hermes.tools` module, so
still inside the allowed direction).

Re-exports are deliberately absent: `hermes.tools.__init__` stays an empty
surface so that importing the tools package never grows an eager edge into the
research layer through `tools.research_sources`. Import
`hermes.tools.capabilities.invoke` (or `.registry`) directly.
"""

from __future__ import annotations

__all__: list[str] = []
