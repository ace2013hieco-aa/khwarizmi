"""CHG-2 — provider-interaction record persistence.

Operational provenance rows for recorded provider interactions (one row
per interaction, immutable, never updated or deleted). Bodies live in
the artifact store by content hash; this table carries identity,
outcome, redacted request form, and evidence linkage.

Write path discipline: redacted forms only (the transport redacts at
the record boundary); this module additionally scans the persisted
request form with the secret validator (defense in depth, same backstop
as the event journal) and refuses oversized request forms. Bodies are
content-hashed and verified on read.

Nothing here admits research state: rows are written inside admitted
task execution (the same category as artifact/edge writes) or by
explicit test/corpus tooling. No journal event is emitted per
interaction (bounded-cap rationale); the task's own lifecycle events
bound the execution, and content hashes link rows to artifacts.
"""
from __future__ import annotations

import json
from typing import Any

__all__ = [
    "ProviderInteractionRepository",
    "make_persisting_sink",
    "persist_interaction",
]


class ProviderInteractionRepository:
    """Read/write provider-interaction rows (CHG-2).

    Writes are explicit and immutable: no update or delete method
    exists. Reads are project-scoped and deterministic.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def record(
        self,
        *,
        interaction_id: str,
        project_id: str,
        task_id: str | None,
        provider_id: str,
        adapter_version: str,
        parser_version: str,
        normalized_request_hash: str,
        request_json: str,
        response_status_class: str,
        response_body_hash: str | None,
        outcome_kind: str,
        failure_class: str | None,
        content_type: str | None,
        retrieved_at: str,
        source_url_redacted: str,
        evidence_artifact_id: str | None,
        created_at: str,
    ) -> str:
        """Persist one interaction row. Raises on secret content,
        oversized request forms, or duplicate identity (re-record the
        same fixture id is a caller error — replays never write)."""
        from hermes.persistence.event_validation import (
            DEFAULT_PAYLOAD_MAX_BYTES,
            EventValidationError,
            validate_no_secrets,
        )
        try:
            request_obj = json.loads(request_json)
        except ValueError as exc:
            raise ValueError(
                f"interaction request form is not JSON: {exc}") from None
        validate_no_secrets(request_obj)
        if len(request_json.encode("utf-8")) > DEFAULT_PAYLOAD_MAX_BYTES:
            raise EventValidationError(
                f"interaction request form "
                f"{len(request_json.encode('utf-8'))} bytes exceeds cap "
                f"{DEFAULT_PAYLOAD_MAX_BYTES}",
                "request_json",
            )
        self._conn.execute(
            """INSERT INTO provider_interactions
               (interaction_id, project_id, task_id, provider_id,
                adapter_version, parser_version, normalized_request_hash,
                request_json, response_status_class, response_body_hash,
                outcome_kind, failure_class, content_type, retrieved_at,
                source_url_redacted, evidence_artifact_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (interaction_id, project_id, task_id, provider_id,
             adapter_version, parser_version, normalized_request_hash,
             request_json, response_status_class, response_body_hash,
             outcome_kind, failure_class, content_type, retrieved_at,
             source_url_redacted, evidence_artifact_id, created_at))
        return interaction_id

    def get(self, interaction_id: str, project_id: str) -> dict | None:
        """One interaction row by identity within a project, or None.

        Project-scoped by contract: interaction rows are operational
        records of one project's executions (unlike content-addressed
        artifact bytes, which are legitimately global). Cross-project
        reads must go through explicitly shared fixtures, never this
        reader.
        """
        row = self._conn.execute(
            "SELECT * FROM provider_interactions "
            "WHERE interaction_id = ? AND project_id = ?",
            (interaction_id, project_id)).fetchone()
        return dict(row) if row is not None else None

    def list_for_task(self, task_id: str) -> list[dict]:
        """Interaction rows for one task, deterministic
        (retrieved_at, interaction_id order)."""
        rows = self._conn.execute(
            "SELECT * FROM provider_interactions WHERE task_id = ? "
            "ORDER BY retrieved_at ASC, interaction_id ASC",
            (task_id,)).fetchall()
        return [dict(r) for r in rows]

    def list_for_evidence(self, evidence_artifact_id: str) -> list[dict]:
        """Interaction rows linked to one evidence artifact,
        deterministic order."""
        rows = self._conn.execute(
            "SELECT * FROM provider_interactions "
            "WHERE evidence_artifact_id = ? "
            "ORDER BY retrieved_at ASC, interaction_id ASC",
            (evidence_artifact_id,)).fetchall()
        return [dict(r) for r in rows]


def persist_interaction(
    conn: Any,
    clock: Any,
    store: Any,
    interaction: Any,
    body: bytes | None,
    *,
    project_id: str | None = None,
    task_id: str | None = None,
    evidence_artifact_id: str | None = None,
) -> str:
    """Persist one recorded interaction: body bytes to the artifact
    store (content-addressed, integrity-verifiable), then the
    interaction row. Returns the interaction id. Bodies must already
    respect the recording cap (the transport enforces it loudly).

    Idempotent on fixture identity: re-persisting the same interaction
    id with matching body hash is a no-op returning the id (retries
    re-request identical interactions); a conflicting body hash, or a
    row missing for any other integrity reason, re-raises — duplicate
    identities never silently diverge. Project/task linkage defaults
    to the interaction's bound execution context.
    """
    import sqlite3 as _sqlite3

    from hermes.tools.providers.replay import RecordedInteraction
    if not isinstance(interaction, RecordedInteraction):
        raise TypeError(
            "persist_interaction requires a RecordedInteraction, "
            f"got {type(interaction).__name__}")
    resolved_project = project_id if project_id is not None \
        else interaction.project_id
    resolved_task = task_id if task_id is not None else interaction.task_id
    if not isinstance(resolved_project, str) or not resolved_project:
        raise ValueError(
            "persist_interaction requires a project_id (explicit or "
            "bound on the interaction) — interactions are never "
            "project-less")
    if body is not None:
        import hashlib as _hashlib
        digest = _hashlib.sha256(body).hexdigest()
        if (interaction.response_body_hash is not None
                and digest != interaction.response_body_hash):
            raise ValueError(
                "recorded body bytes do not match the interaction's "
                "response_body_hash — refusing to persist")
        # Bodies live in the artifact store (content-addressed, deduped
        # by hash, integrity-verifiable) — the same substrate fetch
        # payloads use. The row below references them by hash.
        store.write(
            body, artifact_type="provider_response",
            producer=f"provider:{interaction.provider_id}",
            project_id=resolved_project, task_id=resolved_task)
    repo = ProviderInteractionRepository(conn)
    request_json = json.dumps(interaction.normalized_request,
                              sort_keys=True, ensure_ascii=False)
    # Clock convention: the provider Clock protocol (now_utc), with a
    # bare-callable fallback for test/simple clocks.
    now = clock.now_utc() if hasattr(clock, "now_utc") else clock()
    try:
        return repo.record(
            interaction_id=interaction.interaction_id,
            project_id=resolved_project,
            task_id=resolved_task,
            provider_id=interaction.provider_id,
            adapter_version=interaction.adapter_version,
            parser_version=interaction.parser_version,
            normalized_request_hash=interaction.request_hash,
            request_json=request_json,
            response_status_class=interaction.status_class,
            response_body_hash=interaction.response_body_hash,
            outcome_kind=interaction.outcome_kind,
            failure_class=interaction.failure_class,
            content_type=interaction.content_type,
            retrieved_at=interaction.retrieved_at,
            source_url_redacted=interaction.source_url_redacted,
            evidence_artifact_id=evidence_artifact_id,
            created_at=now)
    except _sqlite3.IntegrityError:
        # Possibly a retry re-persisting the identical interaction:
        # converge only when the stored row matches byte-for-byte on
        # identity fields; anything else (foreign-key failure from a
        # missing project/task, or a conflicting body) re-raises.
        existing = repo.get(interaction.interaction_id, resolved_project)
        if existing is not None and (
                existing["response_body_hash"]
                == interaction.response_body_hash
                and existing["normalized_request_hash"]
                == interaction.request_hash
                and existing["outcome_kind"] == interaction.outcome_kind):
            return str(existing["interaction_id"])
        raise


def make_persisting_sink(
    conn: Any,
    store: Any,
    clock: Any,
) -> Any:
    """Build a ``RecordedTransport`` sink closure persisting through
    :func:`persist_interaction` on the given connection/store/clock.

    The sink inherits project/task scope from each interaction's bound
    execution context (set by the handler choke point) — the closure
    itself carries no scope, so one sink serves every task. Writes run
    synchronously inside the calling task execution (lease-held tick
    when driven through handlers); rows are content-keyed and
    idempotent, so no fencing hazard arises beyond what the tick
    already serializes.
    """
    def _sink(interaction: Any, body: bytes | None) -> None:
        persist_interaction(conn, clock, store, interaction, body)

    return _sink
