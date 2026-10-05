"""Schema migrations (v4 §16.4) — versioned, forward-only (IDR-010).

Migration mechanism:
  - ``schema_version`` table tracks the applied version.
  - On startup: read version, compare against SUPPORTED_VERSION.
  - version == supported → proceed
  - version < supported  → run pending migrations in order
  - version > supported  → refuse to start (SchemaVersionError)
  - No "version 0" — a database without ``schema_version`` is version 0.

Migrations are forward-only. No down/rollback. If a rollback is ever needed,
it is a manual operation against a backup snapshot.
"""
from __future__ import annotations

import sqlite3

from hermes.core import Clock, utc_now

SUPPORTED_VERSION = 19


def _migrate_0_to_1(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 0 → 1: create all v1 tables (IDR-007).

    Tables: schema_version, scheduler_lock, projects, tasks,
    task_dependencies, events, artifacts.
    """
    ts = clock()

    # schema_version table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            applied_at  TEXT NOT NULL
        )
    """)

    # scheduler_lock (single-writer advisory lock, v4 §8)
    # F-02: Fixed PRIMARY_KEY typo → PRIMARY KEY; added owner column
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduler_lock (
            id          INTEGER PRIMARY KEY CHECK (id = 0),
            owner       TEXT NOT NULL,
            locked_at   TEXT NOT NULL
        )
    """)

    # projects (v4 §6.1, §6.2)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            project_id          TEXT PRIMARY KEY,
            name                TEXT NOT NULL,
            lifecycle_state     TEXT NOT NULL,
            operational_mode    TEXT NOT NULL DEFAULT 'ACTIVE',
            iteration           INTEGER NOT NULL DEFAULT 1,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            CHECK (lifecycle_state IN (
                'CREATED','SCOPING','LITERATURE_REVIEW','HYPOTHESIS_FORMULATION',
                'EXPERIMENT_DESIGN','DATA_ACQUISITION','DATA_VALIDATION',
                'IMPLEMENTATION','EXPERIMENTATION','ANALYSIS','VALIDATION',
                'ADVERSARIAL_REVIEW','REPLICATION','REPORTING','COMPLETED',
                'FAILED','ABANDONED'
            )),
            CHECK (operational_mode IN ('ACTIVE','AWAITING_HUMAN','PAUSED'))
        )
    """)

    # tasks (v4 §7 node contract)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id             TEXT PRIMARY KEY,
            project_id          TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            task_type           TEXT NOT NULL,
            profile             TEXT,
            idempotency_key     TEXT NOT NULL,
            attempt             INTEGER NOT NULL DEFAULT 1,
            status              TEXT NOT NULL DEFAULT 'PENDING',
            iteration           INTEGER NOT NULL DEFAULT 1,
            parent_task_id      TEXT,
            spec_json           TEXT NOT NULL DEFAULT '{}',
            inputs_json         TEXT,
            outputs_json        TEXT,
            provenance_json     TEXT,
            cost_class          TEXT,
            concurrency_group   TEXT,
            max_retries         INTEGER NOT NULL DEFAULT 3,
            created_at          TEXT NOT NULL,
            started_at          TEXT,
            completed_at        TEXT,
            last_heartbeat      TEXT,
            UNIQUE (idempotency_key, attempt),
            CHECK (task_type IN (
                'AGENT_TASK','TOOL_TASK','GATE','HUMAN_GATE','SUBGRAPH'
            )),
            CHECK (status IN (
                'PENDING','READY','RUNNING','SUCCEEDED','FAILED','RETRYING',
                'NO_SIGNAL','WAITING_HUMAN','WAITING_EXTERNAL',
                'CANCELLED','SKIPPED','INVALIDATED'
            ))
        )
    """)

    # task_dependencies (v4 §7 edges)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_dependencies (
            dependency_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id             TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            depends_on_task_id  TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            created_at          TEXT NOT NULL,
            UNIQUE (task_id, depends_on_task_id),
            CHECK (task_id != depends_on_task_id)
        )
    """)

    # events (v4 §8.1 append-only journal)
    # F-04: DB-level CHECK on payload size (defense-in-depth, S6)
    # The 4096-byte cap matches the application-level default (event_validation.py).
    # F-04 fix: SQLite length() counts CHARACTERS, not BYTES — a 2048-emoji
    # payload (8192 bytes) would pass. Using length(CAST(payload_json AS BLOB))
    # counts bytes, not characters, closing the gap between app and DB layers.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type          TEXT NOT NULL,
            project_id          TEXT REFERENCES projects(project_id),
            task_id             TEXT REFERENCES tasks(task_id),
            from_state          TEXT,
            to_state            TEXT,
            correlation_id      TEXT NOT NULL DEFAULT '',
            caused_by           TEXT,
            reason              TEXT,
            artifact_ids_json   TEXT,
            payload_json        TEXT,
            created_at          TEXT NOT NULL,
            CHECK (length(CAST(payload_json AS BLOB)) <= 4096)
        )
    """)

    # Index on events.project_id for replay queries
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id)"
    )

    # artifacts (v4 §16.1)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id         TEXT PRIMARY KEY,
            project_id          TEXT REFERENCES projects(project_id),
            task_id             TEXT REFERENCES tasks(task_id),
            artifact_type       TEXT NOT NULL,
            content_hash        TEXT NOT NULL UNIQUE,
            size_bytes          INTEGER NOT NULL,
            storage_path        TEXT NOT NULL,
            producer            TEXT NOT NULL,
            metadata_json       TEXT,
            created_at          TEXT NOT NULL
        )
    """)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_artifacts_hash ON artifacts(content_hash)"
    )

    # Record the migration
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (1, ts),
    )


def _migrate_1_to_2(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 1 → 2 (F-05, F-11, F-14).

    Adds:
    - Node contract fields to tasks: timeout, heartbeat_interval, retry_policy,
      permissions, and S13 skip-rate fields (sources_considered, sources_skipped,
      skip_reasons, skip_rate).
    - S1 ThesisEvidenceTable schema (v4 §9.1)
    - S12 DatasetManifest schema (v4 §15/S12)
    - S16 ScopeBrief schema (v4 §6.1/§11/S16)
    - Provenance edges table (v4 §14)
    - F-14: Additional CHECK constraints on tasks for new enum fields
    """
    ts = clock()

    # F-11: Add missing node contract columns to tasks
    conn.execute("ALTER TABLE tasks ADD COLUMN timeout INTEGER")
    conn.execute("ALTER TABLE tasks ADD COLUMN heartbeat_interval INTEGER DEFAULT 30")
    conn.execute("ALTER TABLE tasks ADD COLUMN retry_policy TEXT DEFAULT 'FIXED'")
    conn.execute("ALTER TABLE tasks ADD COLUMN permissions TEXT")

    # S13: Skip-rate fields (v4 §7/S13)
    conn.execute("ALTER TABLE tasks ADD COLUMN sources_considered INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE tasks ADD COLUMN sources_skipped INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE tasks ADD COLUMN skip_reasons TEXT")
    conn.execute("ALTER TABLE tasks ADD COLUMN skip_rate REAL DEFAULT 0.0")

    # S16: ScopeBrief — frozen, immutable, content-identified (v4 §6.1/§11/S16)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scope_briefs (
            brief_id        TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL REFERENCES projects(project_id),
            version         INTEGER NOT NULL DEFAULT 1,
            content_hash    TEXT NOT NULL,
            supersedes_id   TEXT REFERENCES scope_briefs(brief_id),
            scope_text_json TEXT NOT NULL,
            rationale       TEXT,
            created_at      TEXT NOT NULL,
            frozen_at       TEXT NOT NULL,
            UNIQUE (project_id, version)
        )
    """)

    # S1: ThesisEvidenceTable — thesis-mode evidence structure (v4 §9.1/S1)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS thesis_evidence (
            thesis_evidence_id  TEXT PRIMARY KEY,
            project_id          TEXT NOT NULL REFERENCES projects(project_id),
            thesis_ref          TEXT NOT NULL,
            verdict             TEXT NOT NULL CHECK (verdict IN (
                'THESIS_SUPPORTED', 'THESIS_PARTIALLY_SUPPORTED',
                'THESIS_CONTRADICTED', 'THESIS_INSUFFICIENT', 'THESIS_MIXED'
            )),
            round               INTEGER NOT NULL DEFAULT 1,
            counter_search_json TEXT,
            rows_json            TEXT NOT NULL,
            created_at          TEXT NOT NULL
        )
    """)

    # S12: DatasetManifest — external data index (v4 §15/S12)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dataset_manifests (
            manifest_id     TEXT PRIMARY KEY,
            project_id      TEXT REFERENCES projects(project_id),
            location        TEXT NOT NULL,
            format          TEXT,
            size_bytes      INTEGER,
            headers_json    TEXT,
            schema_observations_json TEXT,
            query_recipes_json TEXT,
            content_hash    TEXT NOT NULL,
            provenance_json TEXT,
            created_at      TEXT NOT NULL,
            immutable       INTEGER NOT NULL DEFAULT 1 CHECK (immutable = 1)
        )
    """)

    # v4 §14: Provenance edges — typed relationship graph
    conn.execute("""
        CREATE TABLE IF NOT EXISTS provenance_edges (
            edge_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_id     TEXT NOT NULL,
            upstream_id     TEXT NOT NULL,
            edge_type       TEXT NOT NULL CHECK (edge_type IN (
                'cites', 'derived_from', 'supersedes', 'used_as_input', 'justifies'
            )),
            created_at      TEXT NOT NULL,
            UNIQUE (artifact_id, upstream_id, edge_type),
            CHECK (artifact_id != upstream_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_provenance_artifact ON provenance_edges(artifact_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_provenance_upstream ON provenance_edges(upstream_id)"
    )

    # Index for scope_brief lookups
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scope_briefs_project ON scope_briefs(project_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_thesis_evidence_project ON thesis_evidence(project_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dataset_manifests_project ON dataset_manifests(project_id)"
    )

    # Record the migration
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (2, ts),
    )


def _migrate_2_to_3(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 2 → 3 (F-04 fix: byte-accurate payload CHECK).

    v2 schemas created by pre-fix code use ``CHECK (length(payload_json) <= 4096)``
    which counts CHARACTERS, not BYTES — a 2048-emoji payload (8192 bytes) passes.
    This migration recreates the events table with the byte-accurate CHECK:
    ``CHECK (length(CAST(payload_json AS BLOB)) <= 4096)``.

    No production DBs existed before this fix, so this migration is a safeguard
    for any v2 test database that still has the weak CHECK.
    """
    ts = clock()

    # Recreate events table with byte-accurate CHECK
    # SQLite has no ALTER TABLE ... DROP CONSTRAINT, so we recreate the table.
    conn.execute("CREATE TABLE IF NOT EXISTS events_new AS SELECT * FROM events")
    conn.execute("DROP TABLE events")
    conn.execute("""
        CREATE TABLE events (
            event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type          TEXT NOT NULL,
            project_id          TEXT REFERENCES projects(project_id),
            task_id             TEXT REFERENCES tasks(task_id),
            from_state          TEXT,
            to_state            TEXT,
            correlation_id      TEXT NOT NULL DEFAULT '',
            caused_by           TEXT,
            reason              TEXT,
            artifact_ids_json   TEXT,
            payload_json        TEXT,
            created_at          TEXT NOT NULL,
            CHECK (length(CAST(payload_json AS BLOB)) <= 4096)
        )
    """)
    conn.execute("INSERT INTO events SELECT * FROM events_new")
    conn.execute("DROP TABLE events_new")

    # Recreate indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id)")

    # Record the migration
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (3, ts),
    )


def _migrate_3_to_4(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 3 → 4 (IDR-018): ResearchProgram artifact schema.

    The approved Part 2 architecture (MERGE INTO EXISTING COMPONENT) adds a
    typed, immutable ``ResearchProgram`` — the project's epistemic contract:
    hypotheses, rivals, predictions, discrimination requirements, and the
    DERIVED evidence/gate obligations. No compiler service; the validator
    (research/programs.py) is a deterministic §5-style service and the write
    path is the repository, mirroring the ``scope_briefs`` pattern (frozen,
    versioned, supersession-edged, never updated/deleted).

    Table mirrors ``scope_briefs``: program identity is content-derived
    (``program_id = rp_<sha256[:24]>``), version tracks the supersession
    chain, ``UNIQUE (project_id, version)`` keeps one chain per project, and
    ``UNIQUE (project_id, content_hash)`` enforces idempotent duplicate
    handling at the DB level (a duplicate compilation returns the existing
    row, PA4-style).
    """
    ts = clock()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_programs (
            program_id          TEXT PRIMARY KEY,
            project_id          TEXT NOT NULL REFERENCES projects(project_id),
            version             INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            content_hash        TEXT NOT NULL,
            supersedes_id       TEXT REFERENCES research_programs(program_id),
            scope_ref           TEXT NOT NULL,
            epistemic_objective TEXT NOT NULL,
            compiler_version    TEXT NOT NULL,
            policy_version      TEXT NOT NULL,
            schema_version      TEXT NOT NULL,
            input_hash          TEXT NOT NULL,
            hypothesis_json     TEXT NOT NULL,
            prediction_json     TEXT NOT NULL,
            discrimination_json TEXT NOT NULL,
            evidence_json       TEXT NOT NULL,
            gate_json           TEXT NOT NULL,
            methodology_json    TEXT NOT NULL,
            task_graph_template_ref TEXT,
            produced_by         TEXT NOT NULL,
            reason              TEXT,
            created_at          TEXT NOT NULL,
            UNIQUE (project_id, version),
            UNIQUE (project_id, content_hash),
            CHECK (supersedes_id IS NULL OR supersedes_id != program_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_programs_project "
        "ON research_programs(project_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_programs_hash "
        "ON research_programs(content_hash)"
    )

    # Record the migration
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (4, ts),
    )


def _migrate_4_to_5(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 4 → 5 (IDR-026): ResearchClaim / ResearchAssumption substrate.

    The P7 CONTRA write path (IDR-026, IDR-025 substrate) persists the
    advisory ``ResearchClaim`` / ``ResearchAssumption`` artifacts:

    - ``research_claims`` / ``research_assumptions`` mirror the
      ``research_programs`` pattern: content-derived identity
      (``cl_<sha256[:24]>`` / ``as_<sha256[:24]>``), ``UNIQUE (project_id,
      content_hash)`` for per-artifact idempotency (PA4), head-only
      supersession with a self-supersede CHECK, no UPDATE/DELETE path.
    - ``claim_assumption_links`` is the normalized, FK-enforced relation
      behind the artifacts' ``assumption_ids[]`` / ``dependent_claim_ids[]``
      — the authoritative answer to "which assumptions does this claim depend
      on" (IDR-026 Decision 1).
    - Assumption ``status`` is the advisory lifecycle only
      (ACTIVE/SUSPENDED/SUPERSEDED) — never evidence, never obligations
      (v6 §29.2 rules 1–2, CT-R2/CT-R3).
    - No new event type: audit is the immutable rows + §14 provenance edges
      + the producing task's existing events (IDR-026 Decision 4).
    """
    ts = clock()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_claims (
            claim_id          TEXT PRIMARY KEY,
            project_id        TEXT NOT NULL REFERENCES projects(project_id),
            content_hash      TEXT NOT NULL,
            statement         TEXT NOT NULL,
            source_ref        TEXT NOT NULL,
            span_ref          TEXT,
            claim_type        TEXT,
            context_tags_json TEXT NOT NULL,
            schema_version    TEXT NOT NULL,
            extracted_by      TEXT NOT NULL,
            reason            TEXT,
            supersedes_id     TEXT REFERENCES research_claims(claim_id),
            created_at        TEXT NOT NULL,
            UNIQUE (project_id, content_hash),
            CHECK (supersedes_id IS NULL OR supersedes_id != claim_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_assumptions (
            assumption_id             TEXT PRIMARY KEY,
            project_id                TEXT NOT NULL REFERENCES projects(project_id),
            content_hash              TEXT NOT NULL,
            statement                 TEXT NOT NULL,
            context_tags_json         TEXT NOT NULL,
            supporting_artifact_refs_json TEXT NOT NULL,
            status                    TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('ACTIVE','SUSPENDED','SUPERSEDED')),
            schema_version            TEXT NOT NULL,
            reason                    TEXT,
            supersedes_id             TEXT REFERENCES research_assumptions(assumption_id),
            created_at                TEXT NOT NULL,
            UNIQUE (project_id, content_hash),
            CHECK (supersedes_id IS NULL OR supersedes_id != assumption_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS claim_assumption_links (
            claim_id       TEXT NOT NULL REFERENCES research_claims(claim_id),
            assumption_id  TEXT NOT NULL REFERENCES research_assumptions(assumption_id),
            UNIQUE (claim_id, assumption_id),
            CHECK (claim_id != assumption_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_claims_project "
        "ON research_claims(project_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_claims_hash "
        "ON research_claims(content_hash)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_claims_supersedes "
        "ON research_claims(supersedes_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_assumptions_project "
        "ON research_assumptions(project_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_assumptions_hash "
        "ON research_assumptions(content_hash)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_assumptions_supersedes "
        "ON research_assumptions(supersedes_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_claim_assumption_links_assumption "
        "ON claim_assumption_links(assumption_id)"
    )

    # Record the migration
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (5, ts),
    )


def _migrate_5_to_6(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 5 → 6 (V6-P7-A2-01): producing-task link on claim artifacts.

    The E03 task binding lives in the pipeline layer only (audit 2, A2-01):
    ``record_extraction`` could persist claims with no task anywhere, and the
    persisted rows carried no task reference. Migration 5→6 adds the
    ``producing_task_id`` FK on ``research_claims`` / ``research_assumptions``
    so the write path is schema-bound to the task graph:

    - ``producing_task_id TEXT REFERENCES tasks(task_id)`` (nullable: existing
      rows predate the binding; every new write records it).
    - ``ADD COLUMN`` is used (not a table rebuild) — the new column is
      nullable, so a forward-only migration suffices and no
      ``PRAGMA foreign_keys`` juggling is needed.

    No UPDATE/DELETE path exists on either table (immutable artifacts); the
    column is written once at insertion.
    """
    ts = clock()

    conn.execute(
        "ALTER TABLE research_claims ADD COLUMN producing_task_id TEXT "
        "REFERENCES tasks(task_id)"
    )
    conn.execute(
        "ALTER TABLE research_assumptions ADD COLUMN producing_task_id TEXT "
        "REFERENCES tasks(task_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_claims_task "
        "ON research_claims(producing_task_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_assumptions_task "
        "ON research_assumptions(producing_task_id)"
    )

    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (6, ts),
    )


def _migrate_7_to_8(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 7 → 8 (ADV-02): scheduler-lease generation fencing.

    The controller's ``scheduler_lock`` lease is acquired for a whole tick and
    only refreshed on re-acquisition, so a live controller whose tick outlasts
    the lease can keep writing after a second controller legitimately reclaimed
    the stale lock (the PA7-class stale-live-controller double-write). The
    lease needs a fencing token: a ``generation`` counter on the lock row,
    incremented on every ownership change (reclaim). A controller captures its
    generation at acquisition and every authoritative write it performs must
    re-validate ``owner + generation`` inside the write transaction — a stale
    controller's write fails closed (``LockLostError``), never silently lands.

    Non-destructive: existing lock rows default to generation 0 (the first
    reclaim bumps it to 1). Forward-only, in the standard migration tx.
    """
    ts = clock()

    conn.execute(
        "ALTER TABLE scheduler_lock ADD COLUMN generation INTEGER NOT NULL DEFAULT 0"
    )

    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (8, ts),
    )


def _migrate_6_to_7(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 6 → 7 (AR-03): persisted empty-result-set artifacts.

    The S1 round-2 counter-search compliance rule (§9.1) accepts
    ``counter_search: {result: NONE_FOUND}`` as a schema'd self-reported
    field — a Researcher could declare an empty counter-evidence search
    without ever performing one (AR-03). Migration 6→7 adds the
    ``empty_result_artifacts`` table so a ``NONE_FOUND`` verdict must
    reference a persisted artifact: the query terms actually run and the
    provider response actually received.

    - Content-addressed identity (``sr_<sha256>[:24]`` over query + provider
      response), ``UNIQUE (project_id, content_hash)`` for idempotency (PA4
      pattern), immutable — no UPDATE/DELETE path.
    - The artifact is a search *record*, never evidence: it certifies that a
      counter-search was performed and came back empty; it cannot promote or
      refute a claim (never-evidence rule, v6 §10).
    """
    ts = clock()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS empty_result_artifacts (
            artifact_id      TEXT PRIMARY KEY,
            project_id       TEXT NOT NULL REFERENCES projects(project_id),
            content_hash     TEXT NOT NULL,
            query_terms_json TEXT NOT NULL,
            provider_response_json TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            UNIQUE (project_id, content_hash)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_empty_result_artifacts_project "
        "ON empty_result_artifacts(project_id)"
    )

    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (7, ts),
    )


def _migrate_8_to_9(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 8 → 9 (Q-02 IDR-038 §3.1): per-requirement satisfaction links.

    The Q-02 obligation-fact derivation previously approximated "satisfied"
    as "every required artifact CLASS exists somewhere in the project" —
    class-level, not per-hypothesis. This migration adds the stored link that
    makes fulfillment per-requirement: a row records that a SPECIFIC artifact
    satisfies a SPECIFIC evidence requirement (identified by its claim_ref)
    of a SPECIFIC program.

    - ``program_requirement_satisfactions``: ``UNIQUE (program_id,
      requirement_ref, artifact_id)`` — an artifact satisfies a requirement at
      most once (idempotency, PA4 pattern); FKs enforce that the program, the
      artifact, and the project all exist.
    - The write path (IDR-038 §3.1) validates at admission: the requirement
      dereferences to a real evidence requirement of that program, the
      artifact belongs to the project, and its artifact_type is one of the
      requirement's ``required_artifacts`` classes — a link can never claim a
      class the requirement does not require.
    - Append-only: no UPDATE/DELETE path (the derivation recomputes
      satisfaction from the rows + artifact types; nothing stored is derived).
    - No new event type: audit is the immutable rows themselves.
    """
    ts = clock()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS program_requirement_satisfactions (
            satisfaction_id TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL REFERENCES projects(project_id),
            program_id      TEXT NOT NULL REFERENCES research_programs(program_id),
            requirement_ref TEXT NOT NULL,
            artifact_id     TEXT NOT NULL REFERENCES artifacts(artifact_id),
            created_at      TEXT NOT NULL,
            UNIQUE (program_id, requirement_ref, artifact_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS "
        "idx_program_requirement_satisfactions_project "
        "ON program_requirement_satisfactions(project_id)"
    )

    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (9, ts),
    )


def _migrate_9_to_10(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 9 → 10 (IDR-041: the Evidence Ladder APPLIED side).

    ``evidence_ladder_state`` — the derived ladder rung per (program,
    hypothesis), written ONLY by the deterministic APPLY pass: versioned,
    append-only (the ``research_programs`` / ``scope_briefs`` pattern),
    no UPDATE/DELETE path. The row is the CACHE of a derivation from
    ratified sources (F2) — never the authority: a tampered row re-derives
    to the true rung on the next pass.
    """
    ts = clock()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evidence_ladder_state (
            state_id        TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL REFERENCES projects(project_id),
            program_id      TEXT NOT NULL REFERENCES research_programs(program_id),
            hypothesis_ref  TEXT NOT NULL,
            version         INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            rung            TEXT NOT NULL
                            CHECK (rung IN ('SUPPORTED', 'ROBUST',
                                            'REPLICATED', 'REFUTED')),
            transition_id   TEXT NOT NULL,
            derived_from    TEXT NOT NULL
                            CHECK (derived_from IN ('obligations',
                                                    'ratification')),
            created_at      TEXT NOT NULL,
            UNIQUE (program_id, hypothesis_ref, version)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_ladder_project "
        "ON evidence_ladder_state(project_id)"
    )
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (10, ts),
    )


def _migrate_10_to_11(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 10 → 11 (red-team A4): operator credentials — the ratified
    proof-of-humanity for the operator verdict surfaces. Only the SHA-256
    TOKEN HASH is stored; the plaintext token exists only at the operator's
    hand, never in the DB or the journal."""
    ts = clock()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS operator_credentials (
            operator_id  TEXT PRIMARY KEY,
            token_hash   TEXT NOT NULL,
            name         TEXT NOT NULL,
            created_at   TEXT NOT NULL
        )"""
    )
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (11, ts),
    )


def _migrate_11_to_12(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 11 → 12 (audit F9): the journal enforces the
    one-verdict / one-transition contract at the SCHEMA level for the
    correlation-bearing event types that must be unique per correlation
    (one ClassificationActionDecision / ScopeReviewDecided per proposal;
    one EvidenceTransitionProposed / EvidenceTransitionApplied /
    RefutedApplied per transition id). A PARTIAL unique index scoped to
    those types with a non-empty correlation — IntentApplied etc. carry
    time-based correlations and stay unconstrained.

    Existing duplicates are REFUSED (the journal is append-only: rows are
    never deleted by a migration; the operator resolves them manually and
    re-runs) — never silently repaired."""
    ts = clock()
    dup = conn.execute(
        """SELECT event_type, correlation_id, COUNT(*) c FROM events
           WHERE correlation_id <> ''
             AND event_type IN ('ClassificationActionDecision',
                                'ScopeReviewDecided',
                                'EvidenceTransitionProposed',
                                'EvidenceTransitionApplied',
                                'RefutedApplied')
           GROUP BY event_type, correlation_id HAVING c > 1
           ORDER BY event_type, correlation_id LIMIT 5"""
    ).fetchall()
    if dup:
        rows = ", ".join(
            f"{r['event_type']}:{r['correlation_id']} (x{r['c']})"
            for r in dup)
        raise RuntimeError(
            "cannot migrate to schema 12: duplicate one-verdict rows exist "
            f"in the journal ({rows}) — the journal is append-only; resolve "
            "the duplicates manually before migrating (audit F9)")
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_events_one_verdict
           ON events(event_type, correlation_id)
           WHERE correlation_id <> ''
             AND event_type IN ('ClassificationActionDecision',
                                'ScopeReviewDecided',
                                'EvidenceTransitionProposed',
                                'EvidenceTransitionApplied',
                                'RefutedApplied')"""
    )
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (12, ts),
    )


def _migrate_12_to_13(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 12 → 13 (M1 / HR-02 closure): content-validation verdicts
    gate the Evidence Ladder.

    The ladder previously climbed on artifact CLASSES alone — four
    artifacts of the right type certified SUPPORTED with no content check
    (the audit's HR-02: ``derive_obligation_rung`` was pure set inclusion).
    This migration adds the verdict substrate that makes rung derivation
    consume CONTENT validation, never bare classes:

    - ``validation_verdicts``: one row per (project, artifact) recording
      that the artifact's content was validated (PASS/FAIL), keyed to the
      artifact's content hash (``input_hash`` must equal
      ``artifacts.content_hash`` — re-verified at read, never trusted from
      a stored field).
    - The satisfaction write path (IDR-038 §3.1 rule 5, this session)
      refuses a link whose artifact carries no dereferenceable PASS
      verdict covering its content; the derivation read reports only
      verdict-covered classes, so ``derive_obligation_rung`` refuses
      classes lacking verdicts by construction.

    Existing satisfaction links carry no verdicts and therefore no longer
    certify climbs (the intended behavior change: canned evidence stops
    climbing unless validation verdicts accompany it).
    """
    ts = clock()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS validation_verdicts (
            verdict_id      TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL REFERENCES projects(project_id),
            artifact_id     TEXT NOT NULL REFERENCES artifacts(artifact_id),
            input_hash      TEXT NOT NULL,
            verdict         TEXT NOT NULL CHECK (verdict IN ('PASS', 'FAIL')),
            created_at      TEXT NOT NULL,
            UNIQUE (project_id, artifact_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_validation_verdicts_project "
        "ON validation_verdicts(project_id)"
    )

    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (13, ts),
    )


def _migrate_13_to_14(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 13 → 14 (M4 / HR-05 closure): the closed claim
    support-state vocabulary.

    Claim admission was structural-only (audit HR-05, PROBE P4): a
    fabricated causal overclaim citing a nonexistent span was ADMITTED
    with zero errors, because the substrate could not mechanically
    distinguish directly-supported / partially-supported / inferred /
    speculative / contradicted claims. M4 closes that:

    - ``research_claims.support_state``: the admitted member of the closed
      vocabulary (DIRECT/PARTIAL/INFERRED/SPECULATIVE/CONTRADICTED/
      UNSUPPORTED). Every new write carries it (the validator requires it;
      the write path re-derives identity including it).
    - Pre-vocabulary rows are backfilled with ``UNSUPPORTED`` — the
      fail-closed reading: a row admitted before the vocabulary existed
      has no recorded support, never an invented one. The backfill is
      carried by the column's ``NOT NULL DEFAULT 'UNSUPPORTED'`` (SQLite
      applies the default to every pre-existing row on ADD COLUMN); no
      explicit UPDATE/DELETE is issued, so historical rows are preserved
      verbatim apart from the new column (UNSUPPORTED = "no support
      established", exactly the pre-vocabulary condition).

    The vocabulary is enforced in code (the validator's closed
    SUPPORT_STATES set + the write path's identity re-derivation), not by
    a column CHECK: SQLite's ALTER TABLE ADD COLUMN cannot carry a CHECK
    constraint, and a table rebuild for a single advisory column is
    schema churn with no authority-surface change.
    """
    ts = clock()

    conn.execute(
        "ALTER TABLE research_claims ADD COLUMN support_state TEXT "
        "NOT NULL DEFAULT 'UNSUPPORTED'"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_claims_support_state "
        "ON research_claims(support_state)"
    )

    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (14, ts),
    )


def _migrate_14_to_15(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 14 → 15 (Step 7, v6 §16.6): the curated knowledge registry.

    The journally-derived REFUTED_PATTERN reference index lands three
    structures (charter §5):

    - ``curated_knowledge_entries`` — one row per admitted curated entry.
      Content-derived identity (``curated_<sha256>`` over kind + signature +
      source decision event ref — the FeatureBinding ref is provenance, NOT
      identity, charter §6). Statuses ADMITTED / SUPERSEDED / INVALIDATED;
      no UPDATE/DELETE path except the chartered status transitions
      (supersession, S5-driven invalidation) — rows are never deleted.
    - ``curated_knowledge_retraction_basis`` — the immutable evidence-basis
      set per entry (charter §4, GAP-A resolution D2): the complete set of
      bare falsifying-evidence artifact_ids resolved at admission from the
      refuting classification's ``falsifying_evidence_refs``. Written
      atomically with the registry row; never mutated or deleted after
      admission. Indexed on ``evidence_artifact_id`` — the S5 retraction
      predicate's lookup key.
    - ``curated_knowledge_supersession`` — the supersession chain (one
      successor per entry; the target must be the current ADMITTED head,
      enforced at admission, never here).

    The one-verdict index (migration 12) is EXTENDED to cover the two
    admission events (``CuratedKnowledgeProposed`` /
    ``CuratedKnowledgeAdmitted``) — one admission per curation command. The
    extension discipline is dup-refuse, never repair, drop+recreate
    (migration 12 precedent): existing duplicate rows REFUSE the migration;
    the journal is append-only and the operator resolves manually.

    No historical fabrication: the migration creates EMPTY structures — no
    FeatureBindings are invented, no old REFUTED hypotheses are backfilled,
    no historical provenance is rewritten (charter §7.6–7.8).
    """
    ts = clock()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS curated_knowledge_entries (
            curated_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN ('REFUTED_PATTERN')),
            signature_json TEXT NOT NULL,
            source_project_id TEXT NOT NULL REFERENCES projects(project_id),
            source_binding_ref TEXT NOT NULL REFERENCES artifacts(artifact_id),
            source_decision_event_ref TEXT NOT NULL,
            program_ref TEXT NOT NULL,
            hypothesis_ref TEXT NOT NULL,
            admission_event_ref TEXT NOT NULL,
            admission_decision_ref TEXT NOT NULL,
            admitted_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ADMITTED'
                CHECK (status IN ('ADMITTED','SUPERSEDED','INVALIDATED')),
            invalidation_event_ref TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_curated_kind_status "
        "ON curated_knowledge_entries(kind, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_curated_signature "
        "ON curated_knowledge_entries(signature_json)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_curated_project_status "
        "ON curated_knowledge_entries(source_project_id, status)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS curated_knowledge_retraction_basis (
            curated_id TEXT NOT NULL
                REFERENCES curated_knowledge_entries(curated_id),
            evidence_artifact_id TEXT NOT NULL
                REFERENCES artifacts(artifact_id),
            PRIMARY KEY (curated_id, evidence_artifact_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_curated_basis_evidence "
        "ON curated_knowledge_retraction_basis(evidence_artifact_id)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS curated_knowledge_supersession (
            new_curated_id TEXT PRIMARY KEY
                REFERENCES curated_knowledge_entries(curated_id),
            supersedes_ref TEXT NOT NULL
                REFERENCES curated_knowledge_entries(curated_id),
            supersession_event_ref TEXT NOT NULL
        )
    """)

    # One-verdict extension (migration 12 discipline): dup-refuse, then
    # drop+recreate the partial unique index with the two admission types.
    dup = conn.execute(
        """SELECT event_type, correlation_id, COUNT(*) c FROM events
           WHERE correlation_id <> ''
             AND event_type IN ('CuratedKnowledgeProposed',
                                'CuratedKnowledgeAdmitted')
           GROUP BY event_type, correlation_id HAVING c > 1
           ORDER BY event_type, correlation_id LIMIT 5"""
    ).fetchall()
    if dup:
        rows = ", ".join(
            f"{r['event_type']}:{r['correlation_id']} (x{r['c']})"
            for r in dup)
        raise RuntimeError(
            "cannot migrate to schema 15: duplicate one-verdict rows exist "
            f"in the journal ({rows}) — the journal is append-only; resolve "
            "the duplicates manually before migrating (Step 7)")
    conn.execute("DROP INDEX IF EXISTS idx_events_one_verdict")
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_events_one_verdict
           ON events(event_type, correlation_id)
           WHERE correlation_id <> ''
             AND event_type IN ('ClassificationActionDecision',
                                'ScopeReviewDecided',
                                'EvidenceTransitionProposed',
                                'EvidenceTransitionApplied',
                                'RefutedApplied',
                                'CuratedKnowledgeProposed',
                                'CuratedKnowledgeAdmitted')"""
    )

    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (15, ts),
    )


def _migrate_15_to_16(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 15 → 16 (CHG-1 + CHG-2): contradiction lifecycle substrate
    and provider-interaction record substrate.

    Two additive structures; no existing row, column, index, or event is
    touched, and nothing historical is fabricated:

    - ``contradictions`` — one row per deterministically-detected
      classification conflict (CHG-1 CLASSIFICATION_CONFLICT). Identity
      is content-derived (``cx_<sha256>`` over type + canonical party
      pair); statuses OPEN / RESOLVED / SUPERSEDED; rows are never
      updated except the chartered status transitions (resolution,
      supersession) and never deleted. The table is derived working
      state: identity and active status recompute from classification
      artifacts + evidence references + invalidation state, so deleting
      these rows loses no underlying truth.
    - ``provider_interactions`` — one immutable row per recorded
      provider interaction (CHG-2): request/response identity, outcome
      kind, redacted request form, body content hash (bytes live in the
      artifact store), and evidence-artifact linkage. Rows are never
      updated or deleted; re-recording creates new rows. No secret
      material is stored (redacted at the record boundary).
    """
    ts = clock()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS contradictions (
            contradiction_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            type TEXT NOT NULL CHECK (type IN ('CLASSIFICATION_CONFLICT')),
            party_a TEXT NOT NULL REFERENCES artifacts(artifact_id),
            party_b TEXT NOT NULL REFERENCES artifacts(artifact_id),
            evidence_overlap_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN'
                CHECK (status IN ('OPEN','RESOLVED','SUPERSEDED')),
            detector_version TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            detection_event_ref TEXT NOT NULL,
            resolution_event_ref TEXT,
            resolution_rationale_digest TEXT,
            supersedes_ref TEXT REFERENCES contradictions(contradiction_id),
            created_at TEXT NOT NULL,
            CHECK (party_a != party_b),
            CHECK (party_a < party_b),
            CHECK (supersedes_ref != contradiction_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_contradictions_project_status "
        "ON contradictions(project_id, status)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS provider_interactions (
            interaction_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            task_id TEXT REFERENCES tasks(task_id),
            provider_id TEXT NOT NULL,
            adapter_version TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            normalized_request_hash TEXT NOT NULL,
            request_json TEXT NOT NULL,
            response_status_class TEXT NOT NULL,
            response_body_hash TEXT,
            outcome_kind TEXT NOT NULL,
            failure_class TEXT,
            retrieved_at TEXT NOT NULL,
            source_url_redacted TEXT NOT NULL,
            evidence_artifact_id TEXT REFERENCES artifacts(artifact_id),
            created_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_provider_interactions_task "
        "ON provider_interactions(task_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_provider_interactions_evidence "
        "ON provider_interactions(evidence_artifact_id)"
    )

    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (16, ts),
    )


def _migrate_16_to_17(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 16 → 17 (P4 closure remediation): add the
    ``provider_interactions.content_type`` column required by the P4
    recording path (hazard evaluation consults it on replay).

    The certified 15 → 16 migration shipped without this column, so
    databases upgraded through certified v16 can never acquire it by
    re-running 15 → 16 — every interaction write would fail. The
    column is introduced here and ONLY here (15 → 16 stays
    byte-identical to its certified form): fresh databases gain it on
    the 16 → 17 step of the same upgrade run, certified-v16 databases
    gain it when 17 applies. Purely additive: one nullable column,
    guarded by a pragma check so re-running over an already-correct
    schema is a no-op. No row is modified, no column reinterpreted, no
    backfill (NULL means "recorded before content-type tracking" —
    readers treat NULL as unknown, never as a value).
    """
    ts = clock()
    columns = {row["name"] for row in conn.execute(
        "SELECT name FROM pragma_table_info('provider_interactions')",
    ).fetchall()}
    if "content_type" not in columns:
        conn.execute(
            "ALTER TABLE provider_interactions "
            "ADD COLUMN content_type TEXT"
        )

    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (17, ts),
    )


def _migrate_17_to_18(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 17 → 18 (Step 3 FIX 1): advisory related_claim_ids on claims.

    ``research_claims.related_claim_ids_json`` stores the content-addressed
    cl_ IDs of other claims that a claim cross-references. This is advisory
    substrate only (v6 §29.2 rule 1) — the column is never read by any gate,
    SUPPORT_STATES, or the evidence ladder. It is written once at insertion
    (immutable artifact, no UPDATE/DELETE path) and parsed back through
    ``_claim_row_to_dict``.

    The column follows the same JSON-array-of-strings storage pattern as
    ``context_tags_json`` / ``supporting_artifact_refs_json``. ``ADD COLUMN``
    is used (not a table rebuild) — the new column is nullable with a
    ``NOT NULL DEFAULT '[]'`` so existing rows are backfilled with an empty
    cross-ref set, preserving Delta=0 for pre-vocabulary rows.
    """
    ts = clock()

    columns = {row["name"] for row in conn.execute(
        "SELECT name FROM pragma_table_info('research_claims')",
    ).fetchall()}
    if "related_claim_ids_json" not in columns:
        conn.execute(
            "ALTER TABLE research_claims ADD COLUMN "
            "related_claim_ids_json TEXT NOT NULL DEFAULT '[]'"
        )

    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (18, ts),
    )


def _migrate_18_to_19(conn: sqlite3.Connection, clock: Clock) -> None:
    """Migration 18 → 19 (parallel-regime-test substrate, ADR-041).

    Adds three advisory columns to ``research_programs`` for parallel-regime-test
    linkage (all-or-nothing: either all set or all NULL):

    - ``parent_program_id`` — the program this one runs alongside
    - ``parent_hypothesis_ref`` — the hypothesis this parallel program tests
    - ``target_regime`` — which regime this parallel program targets

    These are advisory metadata only — never read by any gate, SUPPORT_STATES,
    or the evidence ladder. Written once at insertion (immutable program, no
    UPDATE/DELETE path). ``ADD COLUMN`` is used (not a table rebuild) — the
    new columns are nullable with a ``NULL`` default so existing rows are
    backfilled with NULL, preserving Delta=0 for pre-existing programs.
    """
    ts = clock()
    columns = {row["name"] for row in conn.execute(
        "SELECT name FROM pragma_table_info('research_programs')",
    ).fetchall()}
    if "parent_program_id" not in columns:
        conn.execute(
            "ALTER TABLE research_programs ADD COLUMN parent_program_id TEXT"
        )
    if "parent_hypothesis_ref" not in columns:
        conn.execute(
            "ALTER TABLE research_programs ADD COLUMN parent_hypothesis_ref TEXT"
        )
    if "target_regime" not in columns:
        conn.execute(
            "ALTER TABLE research_programs ADD COLUMN target_regime TEXT"
        )
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (19, ts),
    )


# ── migration registry (indexed by version number) ──

_MIGRATIONS = [
    _migrate_0_to_1,  # version 0 → 1
    _migrate_1_to_2,  # version 1 → 2
    _migrate_2_to_3,  # version 2 → 3 (F-04 byte-accurate CHECK)
    _migrate_3_to_4,  # version 3 → 4 (IDR-018: ResearchProgram schema)
    _migrate_4_to_5,  # version 4 → 5 (IDR-026: ResearchClaim/Assumption substrate)
    _migrate_5_to_6,  # version 5 → 6 (V6-P7-A2-01: producing-task link)
    _migrate_6_to_7,  # version 6 → 7 (AR-03: empty-result-set artifacts)
    _migrate_7_to_8,  # version 7 → 8 (ADV-02: scheduler-lease generation fencing)
    _migrate_8_to_9,  # version 8 → 9 (Q-02: per-requirement satisfaction links)
    _migrate_9_to_10,  # version 9 → 10 (IDR-041: Evidence Ladder APPLIED side)
    _migrate_10_to_11,  # version 10 → 11 (red-team A4: operator credentials)
    _migrate_11_to_12,  # version 11 → 12 (audit F9: schema-level one-verdict index)
    _migrate_12_to_13,  # version 12 → 13 (M1/HR-02: content-validation verdicts gate the ladder)
    _migrate_13_to_14,  # version 13 → 14 (M4/HR-05: closed claim support-state vocabulary)
    _migrate_14_to_15,  # version 14 → 15 (Step 7: curated knowledge registry §16.6)
    _migrate_15_to_16,  # version 15 → 16 (CHG-1 contradiction substrate + CHG-2 provider-interaction records)
    _migrate_16_to_17,  # version 16 → 17 (P4 closure: provider_interactions.content_type remediation)
    _migrate_17_to_18,  # version 17 → 18 (Step 3 FIX 1: advisory related_claim_ids on claims)
    _migrate_18_to_19,  # version 18 → 19 (ADR-041: parallel-regime-test advisory columns on research_programs)
]


def migrate_to_latest(conn: sqlite3.Connection, clock: Clock | None = None) -> int:
    """Run all pending migrations. Returns the resulting schema version.

    Should be called once at startup. Migrations run in order within a
    transaction (IDR-010).
    """
    clk = clock or utc_now
    current = _get_version(conn)

    if current > SUPPORTED_VERSION:
        from hermes.persistence.database import SchemaVersionError
        raise SchemaVersionError(current, SUPPORTED_VERSION)

    for i in range(current, len(_MIGRATIONS)):
        migration = _MIGRATIONS[i]
        conn.execute("BEGIN")
        try:
            migration(conn, clk)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    return _get_version(conn)


def _get_version(conn: sqlite3.Connection) -> int:
    """Return the current schema version (0 if table doesn't exist).

    Returns MAX(version) so multiple migration records don't cause stale reads.
    """
    try:
        row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
        return row["v"] if row and row["v"] is not None else 0
    except sqlite3.OperationalError:
        return 0
