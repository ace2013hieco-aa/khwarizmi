"""Governance control plane — pure policy + evaluation (ARCHITECTURE_DELTA §2.5).

The control plane *owns* the authority vocabulary, the refusal vocabulary and its
FROZEN meanings, project isolation and the human-authority boundary (§2.5
*Owns*). This package implements that ownership as **data plus pure evaluation**
over the spine's already-recorded evidence — nothing here enforces, mutates,
writes or decides a transition.

Module layout:

  policy.py    — the versioned action→authority matrix as DATA (v2: every check
                 input — binding key, target key, head key, approval window — is
                 policy-owned, never request-supplied), plus the closed refusal
                 vocabulary this plane may emit. The matrix carries no behaviour:
                 `Policy`/`PolicyRow` are values, `resolve()` applies deny-wins.
  approvals.py — the approval lifecycle (MISSING / PENDING / APPROVED / DENIED /
                 EXPIRED) derived from recorded `HumanDecisionReceived` rows.
                 Denials are returned as refusal-as-data, never silently.
  authority.py — authority evaluation: given a request and the recorded rows
                 (operator credentials + human-decision rows), returns ALLOWED or
                 a refusal in the FROZEN vocabulary, naming the evidence rows it
                 read. The evaluation is total (it never raises to its caller) and
                 it enforces *independence*: an operator's own recorded decision
                 does not authorize that operator's act.

Import direction (§2.5, §3.1)
-----------------------------
This package imports the standard library and its own modules — no `hermes.*`
module at all. It therefore holds no connection, opens no transaction, appends no
journal row (`repositories.py:92` remains the only journal writer), reads no
clock and touches no file. The row snapshots it evaluates are *handed to it* by
its caller; the caller (today: a test, or a future read-side surface) owns the
read. Those rows are evaluated as given: resolving them from the journal, and
proving they were recorded, is the enforcement path's act — a documented trust
boundary, not a check this plane can perform.

State ladder (honest record)
----------------------------
DESIGNED → IMPLEMENTED: the policy matrix, the authority evaluation and the
approval lifecycle are implemented and tested here. **Not WIRED**: no existing
file imports this package, so no production entry point reaches it and the
spine's own enforcement points (§2.5 *Enforcement points*) are unchanged. Wiring
a caller, or giving this plane any enforcement role, is a Governance change — a
design gate, not an R-round component (§2.5 *Change rule*).

Re-exports are deliberately absent (`__all__: list[str] = []`, matching
`tools/models/__init__.py`, `tools/capabilities/__init__.py` and
`agents/runtime/__init__.py`): importing `hermes.governance` must not grow an
eager edge into the matrix. Import `hermes.governance.policy`,
`hermes.governance.authority` or `hermes.governance.approvals` directly.
"""

from __future__ import annotations

__all__: list[str] = []
