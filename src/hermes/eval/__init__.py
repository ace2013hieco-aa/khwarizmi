"""Eval plane — pure evaluation + enforcement (R7).

This package answers the question "does it prove/harden/expose the platform?"
It contains:

* ``matrix`` — the adversarial matrix runner: one command running every
  plane's hostile shapes (model / capability / runtime / governance /
  methodology), each case asserting the refusal code it pins;
* ``ops`` — the production surface: auth/credential handling, secrets
  redaction, sandbox confinement, resource-limit enforcement, structured
  logs, metrics/tracing hooks (no-op sinks by default), backup/restore
  verification, config validation;
* ``platform_cli`` — a SEPARATE CLI module that never imports
  ``src/hermes/cli.py``; it is the operator-facing entry for matrix /
  ops / extensions;
* ``extensions`` — the frozen extension-point manifest
  (ModelProvider / Tool / ToolSet / AgentRole / Workflow /
  StorageBackend / EventSink / GovernancePolicy / Evaluator).

Rules (R7 contract, ARCHITECTURE_DELTA §5):

* pure evaluation + enforcement — no plane writes; the matrix WRITES
  nothing durable (reports to stdout / a file outside the repo journal);
* no new intent kinds, no new event types, no new tables, no new
  authorities, no new refusal codes — every enforcement reuses the existing
  frozen vocabulary;
* no new dependencies (stdlib + the existing ``hermes.*`` surface only);
* silent passes are forbidden: an unasserted case fails the run.

This package imports the existing tests (the pinned references) where the
shape already exists; a new case is added only when no test pins it.
"""