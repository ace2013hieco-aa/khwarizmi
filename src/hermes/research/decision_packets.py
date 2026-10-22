"""DECISION-PACKETS — precomputed, read-only operator decision packets.

Throughput today is bounded by operator attention, not by compute: the
deterministic controller parks a wave at a HUMAN_GATE, leaves a
classification-action proposal PENDING_HUMAN_APPROVAL, or records an OPEN
contradiction, and the operator must then hand-assemble the evidence for
each pending verdict before deciding. This module PRECOMPUTES that assembly
so the operator can decide, not dig.

Authority boundary (non-negotiable)
-----------------------------------
This module is a *view*, never a writer and never a decider:

- It never imports or calls ``apply_intent`` / any gateway validator, never
  touches the operator-credential store, and issues no row-mutating
  statement — it opens only ``SELECT`` reads against the project's own rows.
- ``required_authority`` on every packet is the coordinate of the *existing*
  human-authority gate: an operator credential (A4) plus a recorded
  ``HumanDecisionReceived`` journal row. A packet is DATA for a human; it
  carries no ratifying field, no token, and no operator identity.
- Building every packet for every pending verdict leaves the journal and
  every mutable row byte-identical — there is no auto-ratification path and
  none can be added here (the negative test in
  ``tests/test_decision_packets.py`` pins exactly this: a packet alone never
  ratifies).

Determinism
-----------
Every function is pure over the project's rows: no clock, no randomness, no
I/O beyond the SELECTs. ``collect_pending_verdicts`` returns a deterministically
ordered tuple; ``assemble_packet`` returns a canonical (sort_keys) body with
``content_hash`` recomputed from the body — never trusted from storage — and
``build_decision_queue`` folds it all into one content-hashed, byte-pinned
document. Identical rows always yield identical bytes.

Queue ordering
--------------
``order_pending_verdicts`` orders by a deterministic, total key with
*completion-blocking contradictions first* (HR-08: an OPEN contradiction
touching the current program's classifications denies ``COMPLETED`` outright),
then mandatory gates, then remaining contradictions, then advisory proposals:

    tier 0  contradiction that blocks completion (OPEN_CONTRADICTION denial)
    tier 1  human gate that blocks completion (GATE_NOT_PASSED denial)
    tier 2  any other OPEN contradiction
    tier 3  any remaining pending verdict (advisory proposals)

The tier is derived from the authoritative ``can_complete_research`` denials
(never a stored flag), and the key ``(tier, kind, subject_ref)`` is a total
order — the output is independent of input order.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from hermes.persistence.failure_classifications import (
    FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
    FAILURE_CLASSIFICATION_REF_PREFIX,
)
from hermes.research.completion import (
    GATE_NOT_PASSED,
    OPEN_CONTRADICTION,
    can_complete_research,
)
from hermes.research.failure_classification import (
    FailureClass,
    PermittedAction,
    parse_contributing_factors,
    proposal_requires_human_confirmation,
)

__all__ = [
    "MAX_CONE_DEPTH",
    "MAX_CONE_NODES",
    "PACKET_HASH_PREFIX",
    "PACKET_VERSION",
    "PENDING_VERDICT",
    "QUEUE_HASH_PREFIX",
    "QUEUE_VERSION",
    "REQUIRED_AUTHORITY",
    "VERDICT_CLASSIFICATION_ACTION_PROPOSAL",
    "VERDICT_CONTRADICTION_RESOLUTION",
    "VERDICT_HUMAN_GATE",
    "VERDICT_KINDS",
    "PendingVerdict",
    "assemble_packet",
    "build_decision_queue",
    "canonical_packet_json",
    "collect_pending_verdicts",
    "order_pending_verdicts",
]

PACKET_VERSION = 1
QUEUE_VERSION = 1
PACKET_HASH_PREFIX = "dp_"
QUEUE_HASH_PREFIX = "dq_"

#: Cone bounds — a packet is a bounded summary, never a full-graph dump.
MAX_CONE_DEPTH = 4
MAX_CONE_NODES = 64

#: The closed verdict-kind vocabulary — one member per existing human-verdict
#: surface. No member is introduced here; each names a verdict path that
#: already exists and already requires a ratified operator decision.
VERDICT_HUMAN_GATE = "HUMAN_GATE"
VERDICT_CLASSIFICATION_ACTION_PROPOSAL = "CLASSIFICATION_ACTION_PROPOSAL"
VERDICT_CONTRADICTION_RESOLUTION = "CONTRADICTION_RESOLUTION"
VERDICT_KINDS: tuple[str, ...] = (
    VERDICT_HUMAN_GATE,
    VERDICT_CLASSIFICATION_ACTION_PROPOSAL,
    VERDICT_CONTRADICTION_RESOLUTION,
)

#: The coordinate of the EXISTING human-authority gate every verdict path
#: enforces. Recorded for the operator; the enforcing code lives at the
#: gateway/admission boundary and is untouched by this module.
REQUIRED_AUTHORITY: tuple[str, ...] = (
    "OPERATOR_CREDENTIAL",
    "RATIFIED_HUMAN_DECISION",
)

PENDING_VERDICT = "PENDING"

# ── queue tiers (deterministic priority; completion-blocking first) ──
_TIER_BLOCKING_CONTRADICTION = 0
_TIER_BLOCKING_GATE = 1
_TIER_OTHER_CONTRADICTION = 2
_TIER_ADVISORY = 3

#: The recorded classification metadata fields whose pairwise delta is the
#: operator's central question on a contradiction (fixed order via sort).
_CONTRADICTION_DIFF_FIELDS: tuple[str, ...] = (
    "confidence",
    "contributing_factors",
    "failure_class",
    "hypothesis_ref",
    "program_ref",
)


@dataclass(frozen=True, slots=True)
class PendingVerdict:
    """One undecided human verdict the operator must ratify.

    ``kind`` is a member of ``VERDICT_KINDS``; ``subject_ref`` is the durable
    identity of the thing awaiting the verdict (a ``task_id``, a proposal's
    ``correlation_id``, or a ``contradiction_id``). ``blocking_completion`` is
    derived from the authoritative HR-08 denials (it is True iff a denial
    currently names this subject), and ``blocking_reason`` explains it in
    operator-facing terms. Nothing here can ratify anything.
    """

    kind: str
    subject_ref: str
    project_id: str
    required_authority: tuple[str, ...]
    blocking_completion: bool
    blocking_reason: str


def _canonical_json(value: Any) -> str:
    """Canonical JSON (sort_keys, tight separators) — one byte form per value."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _content_hash(prefix: str, body: Any) -> str:
    """Content-derived identity over the canonical body — recomputed, never trusted."""
    raw = _canonical_json(body).encode("utf-8")
    return prefix + hashlib.sha256(raw).hexdigest()[:24]


def canonical_packet_json(packet: dict[str, Any]) -> str:
    """The canonical JSON of a packet's BODY (``content_hash`` stripped).

    Pins a packet's bytes for the byte-pin test and lets any consumer recompute
    the hash. Raises ``ValueError`` on a non-mapping input (fail-closed).
    """
    if not isinstance(packet, dict):
        raise ValueError("a decision packet is a mapping")
    body = {k: v for k, v in packet.items() if k != "content_hash"}
    return _canonical_json(body)


def _completion_denial_subjects(
    conn: sqlite3.Connection, project_id: str, code: str,
) -> set[str]:
    """The subjects of every completion denial carrying ``code`` (HR-08).

    Reuses the authoritative predicate rather than re-deriving eligibility:
    ``can_complete_research`` is pure, read-only and fail-closed, so this
    inherits its contract exactly.
    """
    eligibility = can_complete_research(conn, project_id)
    return {d.subject for d in eligibility.denials if d.code == code}


def _gate_requirement(spec_json: str | None) -> str | None:
    """The ``gate_requirement`` a gate task carries, or None when unreadable."""
    try:
        spec = json.loads(spec_json or "{}")
    except (TypeError, ValueError):
        return None
    if not isinstance(spec, dict):
        return None
    gate = spec.get("gate_requirement")
    return gate if isinstance(gate, str) and gate else None


def _classification_artifact(
    conn: sqlite3.Connection, project_id: str, classification_ref: Any,
) -> sqlite3.Row | None:
    """Dereference a ``failure_classification:<hash>`` ref to its artifact row."""
    if not isinstance(classification_ref, str) or not classification_ref.startswith(
        FAILURE_CLASSIFICATION_REF_PREFIX
    ):
        return None
    digest = classification_ref[len(FAILURE_CLASSIFICATION_REF_PREFIX):]
    return conn.execute(
        "SELECT artifact_id, artifact_type, content_hash, metadata_json "
        "FROM artifacts WHERE project_id = ? AND artifact_type = ? "
        "AND content_hash = ?",
        (project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE, digest),
    ).fetchone()


def _proposal_requires_confirmation(
    conn: sqlite3.Connection, project_id: str,
    classification_ref: Any, action: Any,
) -> bool | None:
    """Recompute the proposal gate from recorded rows (F2), never the stored state.

    Returns True/False when the classification + action dereference and the
    class is readable; ``None`` when anything fails to resolve (fail-closed:
    an unresolvable proposal is never a false pending item — the controller
    replay's exact posture).
    """
    row = _classification_artifact(conn, project_id, classification_ref)
    if row is None:
        return None
    try:
        meta = json.loads(row["metadata_json"] or "{}")
    except (TypeError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    try:
        failure_class = FailureClass(meta.get("failure_class"))
        action_member = PermittedAction(action) if isinstance(action, str) else None
    except ValueError:
        return None
    if action_member is None:
        return None
    return proposal_requires_human_confirmation(
        failure_class, action_member,
        parse_contributing_factors(meta.get("contributing_factors")),
    )


def _pending_classification_proposals(
    conn: sqlite3.Connection, project_id: str,
) -> list[tuple[str, dict[str, Any]]]:
    """Undecided PENDING_HUMAN_APPROVAL proposals, deterministic by event_id.

    The gate is RECOMPUTED (never read from the stored admission state): a
    proposal is pending iff its class/action actually requires human
    confirmation and no ``ClassificationActionDecision`` exists for its
    correlation. A corrupt payload or an unresolvable classification is
    skipped — never a false pending item.
    """
    rows = conn.execute(
        "SELECT event_id, correlation_id, payload_json, created_at "
        "FROM events WHERE project_id = ? AND event_type = ? "
        "ORDER BY event_id",
        (project_id, "ClassificationActionProposed"),
    ).fetchall()
    pending: list[tuple[str, dict[str, Any]]] = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        gate = _proposal_requires_confirmation(
            conn, project_id,
            payload.get("classification_ref"), payload.get("action"))
        if not gate:
            continue
        already = conn.execute(
            "SELECT 1 FROM events WHERE event_type = ? AND correlation_id = ?",
            ("ClassificationActionDecision", r["correlation_id"]),
        ).fetchone()
        if already is not None:
            continue
        pending.append((r["correlation_id"], {
            "event_id": r["event_id"],
            "created_at": r["created_at"],
            "classification_ref": payload.get("classification_ref"),
            "action": payload.get("action"),
            "candidate_artifact_ref": payload.get("candidate_artifact_ref"),
            "rationale": payload.get("rationale", ""),
        }))
    return pending


def collect_pending_verdicts(
    conn: sqlite3.Connection, project_id: str,
) -> tuple[PendingVerdict, ...]:
    """Every undecided human verdict for ``project_id``, deterministically ordered.

    Sources (all read-only, all project-scoped):

    - OPEN ``contradictions`` rows (awaiting ``CONTRADICTION_RESOLUTION``);
    - ``HUMAN_GATE`` tasks in ``WAITING_HUMAN`` with no ``HumanGateResolved``
      journal row (awaiting the operator gate verdict);
    - ``ClassificationActionProposed`` events whose gate recomputes True and
      which carry no ``ClassificationActionDecision`` (awaiting the
      classification-action verdict).

    Blocking flags come from ``can_complete_research`` denials, so "blocking"
    means exactly "currently denies COMPLETED". Ordered by
    ``(kind, subject_ref)`` — input-order independent.
    """
    blocking_contradictions = _completion_denial_subjects(
        conn, project_id, OPEN_CONTRADICTION)
    blocking_gates = _completion_denial_subjects(conn, project_id, GATE_NOT_PASSED)

    found: list[PendingVerdict] = []

    for row in conn.execute(
        "SELECT contradiction_id FROM contradictions "
        "WHERE project_id = ? AND status = 'OPEN' ORDER BY contradiction_id",
        (project_id,),
    ).fetchall():
        cid = row["contradiction_id"]
        blocking = cid in blocking_contradictions
        found.append(PendingVerdict(
            kind=VERDICT_CONTRADICTION_RESOLUTION,
            subject_ref=cid,
            project_id=project_id,
            required_authority=REQUIRED_AUTHORITY,
            blocking_completion=blocking,
            blocking_reason=(
                "OPEN contradiction denies COMPLETED (HR-08 "
                "OPEN_CONTRADICTION) — resolve through the ratified human "
                "verdict path"
                if blocking else
                "OPEN contradiction does not currently touch the program's "
                "classifications; adjudication is still owed, but it does "
                "not by itself deny COMPLETED"),
        ))

    for row in conn.execute(
        "SELECT task_id, spec_json FROM tasks "
        "WHERE project_id = ? AND task_type = 'HUMAN_GATE' "
        "AND status = 'WAITING_HUMAN' ORDER BY task_id",
        (project_id,),
    ).fetchall():
        task_id = row["task_id"]
        resolved = conn.execute(
            "SELECT 1 FROM events WHERE task_id = ? "
            "AND event_type = 'HumanGateResolved' LIMIT 1", (task_id,),
        ).fetchone()
        if resolved is not None:
            continue
        requirement = _gate_requirement(row["spec_json"])
        blocking = requirement is not None and requirement in blocking_gates
        found.append(PendingVerdict(
            kind=VERDICT_HUMAN_GATE,
            subject_ref=task_id,
            project_id=project_id,
            required_authority=REQUIRED_AUTHORITY,
            blocking_completion=blocking,
            blocking_reason=(
                f"mandatory gate {requirement!r} has no GatePassed event "
                "— denies COMPLETED (HR-08 GATE_NOT_PASSED)"
                if blocking else
                "parked human gate pending an operator verdict; "
                "waiting, not itself a completion denial"),
        ))

    for proposal_id, _payload in _pending_classification_proposals(
            conn, project_id):
        found.append(PendingVerdict(
            kind=VERDICT_CLASSIFICATION_ACTION_PROPOSAL,
            subject_ref=proposal_id,
            project_id=project_id,
            required_authority=REQUIRED_AUTHORITY,
            blocking_completion=False,
            blocking_reason=(
                "advisory classification-action proposal — it PROPOSES an "
                "action; the action's own authority is unchanged, so the "
                "proposal never denies COMPLETED"),
        ))

    return tuple(sorted(found, key=lambda v: (v.kind, v.subject_ref)))


def _tier(verdict: PendingVerdict) -> int:
    """The deterministic queue tier of a pending verdict."""
    if verdict.kind == VERDICT_CONTRADICTION_RESOLUTION:
        return (_TIER_BLOCKING_CONTRADICTION if verdict.blocking_completion
                else _TIER_OTHER_CONTRADICTION)
    if verdict.kind == VERDICT_HUMAN_GATE and verdict.blocking_completion:
        return _TIER_BLOCKING_GATE
    return _TIER_ADVISORY


def order_pending_verdicts(
    verdicts: tuple[PendingVerdict, ...] | list[PendingVerdict],
) -> tuple[PendingVerdict, ...]:
    """Order pendings by ``(tier, kind, subject_ref)`` — a total, stable order.

    Completion-blocking contradictions come first (tier 0), then mandatory
    gates (tier 1), then other contradictions (tier 2), then advisory
    proposals (tier 3). The key is total, so the result depends only on the
    *set* of pendings, never on their input order.
    """
    return tuple(sorted(verdicts,
                        key=lambda v: (_tier(v), v.kind, v.subject_ref)))


def _artifact_detail(conn: sqlite3.Connection, project_id: str, ref: str) -> dict:
    """Detail for an artifact node; ``resolved`` False when the row is absent."""
    row = conn.execute(
        "SELECT artifact_type, content_hash, size_bytes FROM artifacts "
        "WHERE project_id = ? AND artifact_id = ?", (project_id, ref),
    ).fetchone()
    if row is None:
        return {"resolved": False}
    return {
        "resolved": True,
        "artifact_type": row["artifact_type"],
        "content_hash": row["content_hash"],
        "size_bytes": row["size_bytes"],
    }


def _task_detail(conn: sqlite3.Connection, project_id: str, task_id: str) -> dict:
    """Detail for a task node; ``resolved`` False when the row is absent."""
    row = conn.execute(
        "SELECT task_type, status FROM tasks "
        "WHERE project_id = ? AND task_id = ?", (project_id, task_id),
    ).fetchone()
    if row is None:
        return {"resolved": False}
    return {"resolved": True, "task_type": row["task_type"],
            "status": row["status"]}


def _cone(
    conn: sqlite3.Connection, project_id: str,
    seed_artifacts: list[str], seed_tasks: list[str],
) -> list[dict[str, Any]]:
    """Bounded BFS cone over provenance_edges (upstream) + explicit task nodes.

    Deterministic: neighbours are visited in sorted order, the walk stops at
    ``MAX_CONE_DEPTH`` / ``MAX_CONE_NODES``, and the result is sorted by
    ``(depth, node_kind, node_ref)``.
    """
    nodes: dict[tuple[str, str], dict[str, Any]] = {}
    for ref in seed_tasks:
        nodes[("task", ref)] = {
            "node_kind": "task", "node_ref": ref, "depth": 0,
            "detail": _task_detail(conn, project_id, ref),
        }
    frontier = sorted(set(seed_artifacts))
    depth = 0
    while frontier and depth <= MAX_CONE_DEPTH and len(nodes) < MAX_CONE_NODES:
        nxt: list[str] = []
        for ref in frontier:
            key = ("artifact", ref)
            if key in nodes:
                continue
            if len(nodes) >= MAX_CONE_NODES:
                break
            nodes[key] = {
                "node_kind": "artifact", "node_ref": ref, "depth": depth,
                "detail": _artifact_detail(conn, project_id, ref),
            }
            for edge in conn.execute(
                "SELECT upstream_id FROM provenance_edges "
                "WHERE artifact_id = ? ORDER BY upstream_id", (ref,),
            ).fetchall():
                up = edge["upstream_id"]
                if ("artifact", up) not in nodes:
                    nxt.append(up)
        frontier = sorted(set(nxt))
        depth += 1
    return [nodes[k] for k in sorted(nodes, key=lambda k: (k[0], k[1]))]


def _metadata_of(
    conn: sqlite3.Connection, project_id: str, artifact_id: str,
) -> dict[str, Any]:
    """Parsed classification metadata of an artifact; {} when unreadable."""
    row = conn.execute(
        "SELECT metadata_json FROM artifacts "
        "WHERE project_id = ? AND artifact_id = ?", (project_id, artifact_id),
    ).fetchone()
    if row is None:
        return {}
    try:
        meta = json.loads(row["metadata_json"] or "{}")
    except (TypeError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _render(value: Any) -> str:
    """One stable string rendering for a diff side (JSON for containers)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return _canonical_json(value)


def _contradiction_diffs(
    conn: sqlite3.Connection, project_id: str, contradiction_id: str,
) -> list[dict[str, Any]]:
    """The recorded metadata delta + evidence overlap of the two parties."""
    row = conn.execute(
        "SELECT party_a, party_b, evidence_overlap_json FROM contradictions "
        "WHERE project_id = ? AND contradiction_id = ?",
        (project_id, contradiction_id),
    ).fetchone()
    if row is None:
        return []
    party_a, party_b = row["party_a"], row["party_b"]
    meta_a = _metadata_of(conn, project_id, party_a)
    meta_b = _metadata_of(conn, project_id, party_b)
    diffs: list[dict[str, Any]] = []
    for field in _CONTRADICTION_DIFF_FIELDS:
        left, right = _render(meta_a.get(field)), _render(meta_b.get(field))
        diffs.append({
            "field": field, "left": left, "right": right,
            "left_ref": party_a, "right_ref": party_b,
            "subject": f"contradiction:{contradiction_id}",
        })
    try:
        overlap = json.loads(row["evidence_overlap_json"] or "[]")
    except (TypeError, ValueError):
        overlap = []
    if not isinstance(overlap, list):
        overlap = []
    refs = sorted(r for r in overlap if isinstance(r, str) and r)
    diffs.append({
        "field": "evidence_overlap", "left": "", "right": _canonical_json(refs),
        "left_ref": party_a, "right_ref": party_b,
        "subject": f"contradiction:{contradiction_id}",
    })
    return sorted(diffs, key=lambda d: str(d["field"]))


def _proposal_diffs(
    conn: sqlite3.Connection, project_id: str, proposal_id: str,
) -> list[dict[str, Any]]:
    """The proposal's asserted change vs the classification's recorded facts."""
    payload: dict[str, Any] = {}
    for _pid, p in _pending_classification_proposals(conn, project_id):
        if _pid == proposal_id:
            payload = p
            break
    if not payload:
        return []
    classification_ref = payload.get("classification_ref")
    row = _classification_artifact(conn, project_id, classification_ref)
    recorded_action = ""
    if row is not None:
        meta = _metadata_of(conn, project_id, row["artifact_id"])
        recorded_action = _render(meta.get("failure_class"))
    diffs = [
        {"field": "action", "left": "", "right": _render(payload.get("action")),
         "left_ref": "", "right_ref": str(classification_ref or ""),
         "subject": f"proposal:{proposal_id}"},
        {"field": "candidate_artifact_ref", "left": "",
         "right": _render(payload.get("candidate_artifact_ref")),
         "left_ref": "", "right_ref": str(classification_ref or ""),
         "subject": f"proposal:{proposal_id}"},
        {"field": "classification_failure_class", "left": recorded_action,
         "right": "", "left_ref": str(classification_ref or ""),
         "right_ref": str(classification_ref or ""),
         "subject": f"proposal:{proposal_id}"},
    ]
    return sorted(diffs, key=lambda d: str(d["field"]))


def _gate_diffs(
    conn: sqlite3.Connection, project_id: str, task_id: str,
) -> list[dict[str, Any]]:
    """The gate's requirement + the current status of each dependency task."""
    rows = conn.execute(
        "SELECT t.task_id, t.status FROM task_dependencies d "
        "JOIN tasks t ON t.task_id = d.depends_on_task_id "
        "WHERE d.task_id = ? ORDER BY t.task_id", (task_id,),
    ).fetchall()
    diffs = [{
        "field": "dependency_status", "left": r["task_id"], "right": r["status"],
        "left_ref": r["task_id"], "right_ref": task_id,
        "subject": f"gate:{task_id}",
    } for r in rows]
    spec = conn.execute(
        "SELECT spec_json FROM tasks WHERE project_id = ? AND task_id = ?",
        (project_id, task_id)).fetchone()
    requirement = _gate_requirement(spec["spec_json"] if spec is not None else None)
    diffs.append({
        "field": "gate_requirement", "left": "", "right": requirement or "",
        "left_ref": "", "right_ref": task_id, "subject": f"gate:{task_id}",
    })
    return sorted(diffs, key=lambda d: (str(d["field"]), str(d["left"])))


def _seed_artifacts(
    conn: sqlite3.Connection, project_id: str, verdict: PendingVerdict,
) -> list[str]:
    """The seed artifact refs for a verdict's evidence cone (deduped, sorted)."""
    seeds: set[str] = set()
    if verdict.kind == VERDICT_CONTRADICTION_RESOLUTION:
        row = conn.execute(
            "SELECT party_a, party_b, evidence_overlap_json FROM contradictions "
            "WHERE project_id = ? AND contradiction_id = ?",
            (project_id, verdict.subject_ref)).fetchone()
        if row is not None:
            seeds.update((row["party_a"], row["party_b"]))
            try:
                overlap = json.loads(row["evidence_overlap_json"] or "[]")
            except (TypeError, ValueError):
                overlap = []
            if isinstance(overlap, list):
                seeds.update(r for r in overlap if isinstance(r, str) and r)
    elif verdict.kind == VERDICT_CLASSIFICATION_ACTION_PROPOSAL:
        for pid, payload in _pending_classification_proposals(conn, project_id):
            if pid != verdict.subject_ref:
                continue
            row = _classification_artifact(
                conn, project_id, payload.get("classification_ref"))
            if row is not None:
                seeds.add(row["artifact_id"])
            candidate = payload.get("candidate_artifact_ref")
            if isinstance(candidate, str) and candidate:
                seeds.add(candidate)
    else:  # VERDICT_HUMAN_GATE — artifacts produced by the gate + its deps.
        rows = conn.execute(
            "SELECT artifact_id FROM artifacts WHERE project_id = ? AND "
            "(task_id = ? OR task_id IN (SELECT depends_on_task_id "
            "FROM task_dependencies WHERE task_id = ?))",
            (project_id, verdict.subject_ref, verdict.subject_ref),
        ).fetchall()
        seeds.update(r["artifact_id"] for r in rows)
    return sorted(seeds)


def _seed_tasks(verdict: PendingVerdict) -> list[str]:
    """The task nodes a verdict's cone explicitly includes."""
    if verdict.kind == VERDICT_HUMAN_GATE:
        return [verdict.subject_ref]
    return []


def assemble_packet(
    conn: sqlite3.Connection, project_id: str, verdict: PendingVerdict,
) -> dict[str, Any]:
    """Assemble one deterministic packet: evidence cone + diffs + content hash.

    Read-only and pure over the project's rows. The returned mapping's
    ``content_hash`` is recomputed from its canonical body
    (``canonical_packet_json``), never trusted from storage. The packet carries
    no ratifying field — it is evidence for a human, not a decision.
    """
    if verdict.project_id != project_id:
        raise ValueError("verdict belongs to a different project")
    if verdict.kind not in VERDICT_KINDS:
        raise ValueError(f"unknown verdict kind {verdict.kind!r}")

    if verdict.kind == VERDICT_CONTRADICTION_RESOLUTION:
        diffs = _contradiction_diffs(conn, project_id, verdict.subject_ref)
    elif verdict.kind == VERDICT_CLASSIFICATION_ACTION_PROPOSAL:
        diffs = _proposal_diffs(conn, project_id, verdict.subject_ref)
    else:
        diffs = _gate_diffs(conn, project_id, verdict.subject_ref)

    cone = _cone(conn, project_id,
                 _seed_artifacts(conn, project_id, verdict),
                 _seed_tasks(verdict))

    body: dict[str, Any] = {
        "packet_version": PACKET_VERSION,
        "project_id": project_id,
        "verdict": {
            "state": PENDING_VERDICT,
            "kind": verdict.kind,
            "subject_ref": verdict.subject_ref,
            "required_authority": list(verdict.required_authority),
            "blocking_completion": verdict.blocking_completion,
            "blocking_reason": verdict.blocking_reason,
            "tier": _tier(verdict),
        },
        "evidence_cone": cone,
        "diffs": diffs,
    }
    return {**body, "content_hash": _content_hash(PACKET_HASH_PREFIX, body)}


def build_decision_queue(
    conn: sqlite3.Connection, project_id: str,
) -> dict[str, Any]:
    """The one-call, content-hashed decision queue for a project (read-only).

    Collects every pending verdict, orders it (completion-blocking
    contradictions first), and assembles one packet per verdict in that order.
    Pure and side-effect-free: calling it leaves the journal and every mutable
    row byte-identical, so it can never ratify, dispatch or mutate anything.
    """
    ordered = order_pending_verdicts(collect_pending_verdicts(conn, project_id))
    items = [assemble_packet(conn, project_id, v) for v in ordered]
    body: dict[str, Any] = {
        "queue_version": QUEUE_VERSION,
        "project_id": project_id,
        "items": items,
    }
    return {**body, "content_hash": _content_hash(QUEUE_HASH_PREFIX, body)}
