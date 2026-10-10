"""Runtime plane — the durable agent loop (ARCHITECTURE_DELTA §2.3).

The plane is a *port*, never an authority. One runtime drives every profile;
profiles are **configuration** (`profiles/*.yaml`), not classes. A run is
bounded, emits intent *proposals* only, and executes nothing except what the
Orchestration API's `apply_intent` admits.

Module layout:
  types.py      — the closed value vocabulary: `TaskContext`, `RunLimits`,
                  `Proposal`, `ProposalSet`, `RuntimeRefusal`,
                  `DelegationRecord`, `Checkpoint`, `TraceEvent`, plus the
                  derived-by-rule id helpers and the refusal-code provenance
                  sets. No behaviour beyond pure derivation.
  config.py     — profile configuration loaded from YAML *as data* (a
                  deterministic, dependency-free subset parser: the minimal-core
                  policy forbids adding a YAML dependency), validated fail-closed.
  checkpoint.py — the checkpoint/resume store port with in-memory and
                  file-backed (atomic-replace, lock-free) implementations.
  delegate.py   — subagent dispatch/completion as **child tasks**: the B-2
                  derived-record shape (no private lock, no restart
                  re-dispatch, lease-generation attribution, artifact-ref
                  overflow).
  supervisor.py — cancel / retry / timeout, the streaming execution trace, and
                  the crash-recovery NO_SIGNAL chain.
  projection.py — the B-5 read-side projection: pure, recomputed, never a
                  second durable log (carries the mechanical purity test).
  run.py        — `run(profile, task_context) -> ProposalSet`: the bounded loop.

Import direction (§2.3/§3.1): this package imports ports (`hermes.tools.models`,
`hermes.tools.capabilities`), `hermes.core` types, `hermes.security.boundaries`
for the untrusted-content envelope, and stdlib. It **never** imports
`hermes.persistence`, a repository, or SQL: it holds no connection, opens no
transaction, and appends no journal row (`repositories.py:92` remains the only
journal writer). Every durable effect leaves as a proposal.

Re-exports are deliberately absent (`__all__: list[str] = []`, matching
`tools/models/__init__.py` and `tools/capabilities/__init__.py`): importing
`hermes.agents` must not grow an eager edge into this package. Import
`hermes.agents.runtime.run` (or `.checkpoint`, `.delegate`, `.projection`,
`.supervisor`) directly.
"""

from __future__ import annotations

__all__: list[str] = []
