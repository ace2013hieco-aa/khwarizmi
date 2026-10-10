"""Methodology plane — the substrate ontology (R6).

What this package is
--------------------
A **research-substrate consumer over the runtime** (``ARCHITECTURE_DELTA.md``
§5, classification rule): it answers "does it verify/record research
knowledge?" and is therefore a consumer of the R4 runtime plane and the R5
governance plane, never a fourth authority, never a writer of durable state.

Module layout:
  substrate.py    — the missing ontology nodes and the provenance edges of the
                    research chain, with by-rule identity, project scope,
                    producing-task binding and the N9 predicate honoured.
  workflows.py    — one methodology expressed STRICTLY as configuration over
                    the R4 runtime (profiles + governance actions +
                    termination), swappable without touching runtime,
                    governance or model code.
  swap_test.py    — the methodology-swap fixture: a *second* configuration
                    that loads and runs on the same runtime (diagnostic only).

Import discipline (the round's own rule): this package imports the runtime's
public entry (``hermes.agents.runtime.run.run``) and the argument/return value
types of that entry, plus the governance plane's **public** authority-evaluation
entry and its request/context types — never an internal of either plane. It
names no model vendor.

Identity discipline (mirrors ``docs/ARCHITECTURE.md`` §3.8): every identity in
this package is **recomputed by rule at its write boundary and never
authored**. No caller supplies an id; a payload that carries one is refused.

Re-exports are deliberately absent (``__all__: list[str] = []``), matching
``tools/models/__init__.py``, ``tools/capabilities/__init__.py`` and
``agents/runtime/__init__.py``: importing ``hermes.methodology`` must not grow
an eager edge into the submodules. Import them directly.
"""

from __future__ import annotations

__all__: list[str] = []
