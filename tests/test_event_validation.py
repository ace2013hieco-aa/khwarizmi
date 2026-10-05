"""F-04 tests: S6 bounded event payloads — persistence-boundary validation.

Tests that the event validation module rejects:
- Oversized payloads (>4 KiB)
- Unknown event types
- Secret-bearing payloads
- DB-level CHECK constraint enforcement
"""
from __future__ import annotations

import sqlite3

import pytest

from hermes.core import frozen_clock
from hermes.persistence.database import connect
from hermes.persistence.event_validation import (
    DEFAULT_PAYLOAD_MAX_BYTES,
    KNOWN_EVENT_TYPES,
    EventValidationError,
    validate_event,
    validate_event_type,
    validate_no_secrets,
    validate_payload_size,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository


@pytest.fixture
def mem_conn():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    yield conn
    conn.close()


class TestEventTypeValidation:
    def test_valid_event_type_accepted(self):
        validate_event_type("LifecycleTransition")
        validate_event_type("TaskCreated")
        validate_event_type("IterationAdvanced")

    def test_empty_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            validate_event_type("")

    def test_unknown_event_type_rejected(self):
        with pytest.raises(EventValidationError, match="unknown event type"):
            validate_event_type("BogusEventType")

    def test_known_types_include_phase1_events(self):
        assert "LifecycleTransition" in KNOWN_EVENT_TYPES
        assert "TaskStatusChanged" in KNOWN_EVENT_TYPES
        assert "IterationAdvanced" in KNOWN_EVENT_TYPES


class TestPayloadSizeValidation:
    def test_small_payload_accepted(self):
        validate_payload_size({"key": "value"})

    def test_none_payload_accepted(self):
        validate_payload_size(None)

    def test_empty_payload_accepted(self):
        validate_payload_size({})

    def test_oversized_payload_rejected(self):
        big_payload = {"data": "x" * (DEFAULT_PAYLOAD_MAX_BYTES + 100)}
        with pytest.raises(EventValidationError, match="exceeds cap"):
            validate_payload_size(big_payload, DEFAULT_PAYLOAD_MAX_BYTES)

    def test_boundary_size_payload_accepted(self):
        """A payload at exactly the cap should pass."""
        import json
        payload = {"x": "a" * 4000}
        serialized = len(json.dumps(payload).encode("utf-8"))
        if serialized <= DEFAULT_PAYLOAD_MAX_BYTES:
            validate_payload_size(payload, DEFAULT_PAYLOAD_MAX_BYTES)


class TestSecretRejection:
    def test_non_secret_payload_accepted(self):
        validate_no_secrets({"task_id": "abc", "status": "RUNNING"})

    def test_api_key_in_payload_rejected(self):
        with pytest.raises(EventValidationError, match="secret"):
            validate_no_secrets({"api_key": "sk-" + "x" * 40})

    def test_password_field_rejected(self):
        with pytest.raises(EventValidationError, match="secret pattern"):
            validate_no_secrets({"password": "hunter123"})

    def test_github_token_rejected(self):
        with pytest.raises(EventValidationError, match="secret"):
            validate_no_secrets({"credential": "ghp_" + "a" * 36})

    def test_nested_secret_rejected(self):
        with pytest.raises(EventValidationError, match="secret"):
            validate_no_secrets({
                "config": {
                    "auth_token": "sk-" + "b" * 40
                }
            })

    def test_pem_key_rejected(self):
        with pytest.raises(EventValidationError, match="secret"):
            validate_no_secrets({
                "key": "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."
            })

    def test_jwt_token_not_rejected(self):
        """Known limitation: JWT bearer tokens in innocuous field values
        are NOT rejected — the value pattern regex covers sk-, gho_, AKIA,
        PEM, Slack formats but not JWT. The defense is field-name-based
        plus known-format-based, not a universal secret-content scanner."""
        jwt = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
               "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
               "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
        # This does NOT raise — documented limitation
        validate_no_secrets({"data": jwt})

    def test_plain_password_in_innocuous_field_not_rejected(self):
        """Known limitation: a plain password in a field whose name does
        not match the secret field pattern (e.g. 'description') is NOT
        rejected. The defense catches 'password' as a field NAME, not as
        an arbitrary string value in any field."""
        # This does NOT raise — 'description' is not a secret field name,
        # and 'my hunter2 password' doesn't match known secret format patterns.
        validate_no_secrets({"description": "my hunter2 password"})

    # ── ADV-03: the scanner recurses into EVERY permitted container ──
    # (pre-fix the walker descended into dicts only — a secret inside a list
    # bypassed the scanner entirely).

    def test_secret_in_list_rejected(self):
        with pytest.raises(EventValidationError, match="secret"):
            validate_no_secrets({"evidence": ["sk-" + "x" * 40]})

    def test_secret_field_in_list_dict_rejected(self):
        # the ADV-03 probe: {"evidence": [{"api_key": "secret"}]}
        with pytest.raises(EventValidationError, match="secret pattern"):
            validate_no_secrets({"evidence": [{"api_key": "sk-" + "x" * 40}]})

    def test_secret_in_list_of_list_of_dict_rejected(self):
        with pytest.raises(EventValidationError, match="secret"):
            validate_no_secrets({
                "evidence": [[{"credential": "ghp_" + "a" * 36}]]})

    def test_secret_in_tuple_rejected(self):
        with pytest.raises(EventValidationError, match="secret"):
            validate_no_secrets({"evidence": ({"token": "sk-" + "y" * 40},)})

    def test_secret_value_in_nested_list_of_strings_rejected(self):
        with pytest.raises(EventValidationError, match="secret"):
            validate_no_secrets({
                "rows": [["sk-" + "z" * 40, "plain"]]})

    def test_legitimate_non_secret_content_in_lists_accepted(self):
        # over-blocking guard: ordinary research content in lists stays accepted
        validate_no_secrets({
            "evidence": [{"title": "A study of momentum effects",
                          "notes": ["figure 2", "appendix"]}]})
        validate_no_secrets({"rows": [["abstract text", "another row"]]})


class TestEventCatalogInvariant:
    """ADV-05 — ONE canonical event catalog: the persistence validator
    derives its accepted set from the EventType enum, so the two cannot
    diverge again (the pre-fix literal set had silently accreted five names
    the enum never declared, one of which — IterationAdvanced — is emitted
    by the system)."""

    def test_validator_catalog_derived_from_enum(self):
        from hermes.core.events import EventType

        assert frozenset(e.value for e in EventType) == KNOWN_EVENT_TYPES

    def test_every_enum_member_validates(self):
        from hermes.core.events import EventType

        for e in EventType:
            validate_event_type(e.value)  # no raise


class TestFullValidation:
    def test_valid_event_passes(self):
        validate_event("LifecycleTransition", {"from": "CREATED", "to": "SCOPING"})

    def test_oversized_event_rejected(self):
        with pytest.raises(EventValidationError, match="exceeds cap"):
            validate_event("TaskCreated", {"data": "x" * 5000})

    def test_secret_event_rejected(self):
        with pytest.raises(EventValidationError, match="secret"):
            validate_event("TaskCreated", {"api_key": "sk-" + "x" * 40})

    def test_unknown_type_event_rejected(self):
        with pytest.raises(EventValidationError, match="unknown event type"):
            validate_event("BogusType", {})


class TestDBLevelPayloadCheck:
    """F-14: DB-level CHECK constraint on payload_json byte size."""

    def test_db_rejects_oversized_payload(self, mem_conn):
        """The CHECK(length(CAST(payload_json AS BLOB)) <= 4096) constraint
        should reject oversized payloads even via raw SQL INSERT."""
        repo = ProjectRepository(mem_conn, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        repo.create("p1", "Test")

        with pytest.raises(sqlite3.IntegrityError):
            mem_conn.execute(
                """INSERT INTO events (event_type, project_id, payload_json, created_at)
                   VALUES ('TestEvent', 'p1', ?, '2026-01-01')""",
                ("x" * 5000,),
            )

    def test_db_rejects_oversized_multibyte_payload(self, mem_conn):
        """F-04 regression: SQLite length() counts CHARACTERS, not BYTES.
        The DB CHECK must use CAST(... AS BLOB) to count bytes. A 2048-emoji
        payload is 8192 bytes but only 2048 characters — the old CHECK
        (length(payload_json) <= 4096) would accept it. The byte-accurate
        CHECK (length(CAST(payload_json AS BLOB)) <= 4096) must reject it.
        """
        repo = ProjectRepository(mem_conn, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        repo.create("p1", "Test")

        # 2048 emoji chars = 8192 bytes (each emoji is 4 bytes in UTF-8)
        emoji_payload = "😀" * 2048
        assert len(emoji_payload.encode("utf-8")) == 8192  # 2x the 4096 byte cap

        with pytest.raises(sqlite3.IntegrityError):
            mem_conn.execute(
                """INSERT INTO events (event_type, project_id, payload_json, created_at)
                   VALUES ('TestEvent', 'p1', ?, '2026-01-01')""",
                (emoji_payload,),
            )

    def test_db_accepts_normal_payload(self, mem_conn):
        repo = ProjectRepository(mem_conn, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        repo.create("p1", "Test")

        mem_conn.execute(
            """INSERT INTO events (event_type, project_id, payload_json, created_at)
               VALUES ('TestEvent', 'p1', ?, '2026-01-01')""",
            ('{"key": "value"}',),
        )

    def test_db_accepts_multibyte_under_byte_cap(self, mem_conn):
        """A multibyte payload whose byte size is under 4096 should pass."""
        repo = ProjectRepository(mem_conn, clock=frozen_clock("2026-01-01T00:00:00.000000+00:00"))
        repo.create("p1", "Test")

        # 500 emoji chars = 2000 bytes (under 4096 byte cap)
        emoji_payload = "😀" * 500
        assert len(emoji_payload.encode("utf-8")) == 2000

        mem_conn.execute(
            """INSERT INTO events (event_type, project_id, payload_json, created_at)
               VALUES ('TestEvent', 'p1', ?, '2026-01-01')""",
            (emoji_payload,),
        )


class TestRepositoryEventValidation:
    """F-04: The repository's _append_event validates before INSERT."""

    def test_repository_rejects_oversized_payload(self, mem_conn):
        repo = ProjectRepository(mem_conn)
        repo.create("p1", "Test")
        with pytest.raises(EventValidationError, match="exceeds cap"):
            repo._append_event(
                event_type="LifecycleTransition",
                project_id="p1",
                payload={"data": "x" * 5000},
            )

    def test_repository_rejects_unknown_event_type(self, mem_conn):
        """Bypassing the normal event type should fail at the boundary."""
        repo = ProjectRepository(mem_conn)
        repo.create("p1", "Test")
        with pytest.raises(EventValidationError, match="unknown event type"):
            repo._append_event(event_type="CompletelyBogus", project_id="p1")
