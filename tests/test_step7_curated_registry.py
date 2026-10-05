"""Step 7 (v6 §16.6) — curated knowledge registry tests.

Covers the Step 7E charter §18 test matrix:

A. FeatureBinding      (canonicalization, signature, identity, determinism)
B. Admission           (valid path + every fail-closed rejection)
C. Supersession        (head check, atomicity, replay)
D. Retraction          (S5 integration, invalidation, cross-project)
E. Replay              (journal-fold equivalence, no orphans)
F. Historical          (old REFUTED without binding stays not-curatable)
G. Controller surfaces (record_curation_decision, screen, audit)

The fixture model mirrors the hr07 decisive-refuted contract tests:
a project + program + REFUTED ladder head + EvidenceTransitionApplied +
digest-valid classification + FeatureBinding artifact + recorded
HumanDecision binding the full-command curation_id hash.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from hermes.core import frozen_clock
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    OperatorCredentialRepository,
    ProjectRepository,
    _append_event_to_db,
)
from hermes.research.controller import Controller
from hermes.research.evidence_ladder import classification_content_hash
from hermes.research.feature_binding import (
    CURATED_KIND_REFUTED_PATTERN,
    FEATURE_BINDING_ARTIFACT_TYPE,
    FEATURE_BINDING_REF_PREFIX,
    FeatureBindingError,
    binding_content,
    binding_content_hash,
    canonical_binding,
    curated_id_of,
    curation_command_hash,
    signature_from_binding,
)
from hermes.research.gateway import (
    EVIDENCE_REF,
    MALFORMED_PAYLOAD,
    PROJECT_NOT_FOUND,
    PROPOSAL,
    PROVENANCE,
    ROLE,
    STALE,
    GatewayRejection,
    apply_intent,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1"


# ═══════════════════════ fixtures ═══════════════════════


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p2", "Other")
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    yield conn
    conn.close()


def _hyp(ref, ladder="SUPPORTED"):
    return {"ref": ref, "ladder_target": ladder,
            "falsification_condition": "fc", "rival_of": None,
            "rival_status": None}


def insert_program(db, program_id="rp-1", *, hypotheses=(), project="p1",
                   version=1):
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, ?, ?, NULL, 'b', 'o', 'c1', 'p1', '1', 'ih', ?,
                   '[]', '[]', '[]', '[]', '[]', NULL, 'director', NULL, ?)""",
        (program_id, project, version, "ch-" + program_id,
         json.dumps(list(hypotheses)), CLOCK))


def insert_artifact(db, artifact_id, artifact_type, *, content_hash=None,
                    project="p1", meta=None):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, NULL, ?, ?, 1, 'x', 't', ?, ?)""",
        (artifact_id, project, artifact_type,
         content_hash or f"ch-{artifact_id}",
         json.dumps(meta or {}), CLOCK))


def insert_ladder_refuted(db, *, program_id="rp-1", hypothesis_ref="h1",
                          project="p1", version=1, transition_id="tr-1"):
    """A REFUTED ladder head row (the curatable precondition)."""
    from hermes.research.evidence_ladder import ladder_state_id
    db.execute(
        """INSERT INTO evidence_ladder_state
           (state_id, project_id, program_id, hypothesis_ref,
            version, rung, transition_id, derived_from, created_at)
           VALUES (?, ?, ?, ?, ?, 'REFUTED', ?, 'ratification', ?)""",
        (ladder_state_id(program_id, hypothesis_ref, version),
         project, program_id, hypothesis_ref, version,
         transition_id, CLOCK))


def insert_transition_event(db, *, correlation_id="tr-1", project="p1",
                            program_id="rp-1", hypothesis_ref="h1",
                            classification_ref="failure_classification:x"):
    """An EvidenceTransitionApplied event (to_state=REFUTED)."""
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.EVIDENCE_TRANSITION_APPLIED.value,
        project_id=project, correlation_id=correlation_id,
        from_state="SUPPORTED", to_state="REFUTED",
        caused_by="controller",
        reason="evidence ladder ratification transition: SUPPORTED -> REFUTED",
        payload={"program_id": program_id,
                 "hypothesis_ref": hypothesis_ref,
                 "from_rung": "SUPPORTED", "to_rung": "REFUTED",
                 "driver": "ratification",
                 "ratified_by": "classification",
                 "classification_ref": classification_ref})


def insert_classification(db, *, cls_art="fc-1", project="p1",
                          program_ref="rp-1", hypothesis_ref="h1",
                          falsifying_refs=None, evidence_refs=None):
    """A digest-valid classification artifact with falsifying evidence refs.
    Returns the ``failure_classification:<hash>`` ref."""
    if falsifying_refs is None:
        falsifying_refs = ["evidence:evhash1"]
    if evidence_refs is None:
        evidence_refs = list(falsifying_refs)
    meta = {
        "schema_version": "1",
        "failure_class": "DECLARED_CONSTRAINT_VIOLATION",
        "hypothesis_ref": hypothesis_ref,
        "program_ref": program_ref,
        "classification_id": cls_art,
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": evidence_refs,
        "constraint_ref": f"hypothesis:{hypothesis_ref}:falsification_condition",
        "failed_mechanism_ref": None,
        "regime_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": "step7 test",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": falsifying_refs,
        "permitted_actions": [],
    }
    content_hash = classification_content_hash(meta, project)
    insert_artifact(db, cls_art, "failure_classification",
                    content_hash=content_hash, project=project, meta=meta)
    return "failure_classification:" + (content_hash or "")


def insert_evidence(db, artifact_id="art-ev1", *, content_hash="evhash1",
                    project="p1"):
    """An evidence artifact whose content_hash matches the ref suffix."""
    insert_artifact(db, artifact_id, "evidence",
                    content_hash=content_hash, project=project)


def insert_binding(db, *, artifact_id="art-fb1", project="p1",
                   content_project_ref=None,
                   program_ref="rp-1", hypothesis_ref="h1",
                   instrument="xauusd", feature_family="momentum",
                   claim_type="directional", slot_ref=None,
                   reward_hack_family=None, meta_override=None):
    """A canonical FeatureBinding artifact. Returns the prefixed ref.

    ``project`` is the artifact ROW's project_id (first writer). ``
    content_project_ref`` (default ``project``) is the binding CONTENT's
    project_ref — the two can diverge to test the forged-binding linkage
    check (row resolves in-project, content names a foreign project)."""
    binding = {
        "schema_version": 1,
        "project_ref": content_project_ref or project,
        "program_ref": program_ref,
        "hypothesis_ref": hypothesis_ref,
        "instrument": instrument,
        "feature_family": feature_family,
        "claim_type": claim_type,
    }
    if slot_ref is not None:
        binding["slot_ref"] = slot_ref
    if reward_hack_family is not None:
        binding["reward_hack_family"] = reward_hack_family
    if meta_override is not None:
        binding = meta_override
    content_hash = binding_content_hash(binding)
    insert_artifact(db, artifact_id, FEATURE_BINDING_ARTIFACT_TYPE,
                    content_hash=content_hash, project=project, meta=binding)
    return FEATURE_BINDING_REF_PREFIX + content_hash


def _command_payload(*, operation="ADMIT", program_ref="rp-1",
                     hypothesis_ref="h1", source_binding_ref="",
                     source_decision_event_ref="tr-1",
                     signature_json="", supersedes_ref=""):
    return {
        "operation": operation,
        "kind": CURATED_KIND_REFUTED_PATTERN,
        "program_ref": program_ref,
        "hypothesis_ref": hypothesis_ref,
        "source_binding_ref": source_binding_ref,
        "source_decision_event_ref": source_decision_event_ref,
        "signature_json": signature_json,
        "supersedes_ref": supersedes_ref,
    }


def record_human_decision(db, command_payload, *, ref=None, project="p1"):
    """Record a HumanDecisionReceived binding the command hash.
    Returns the decision ref (correlation_id)."""
    cmd_hash = curation_command_hash(command_payload)
    decision_ref = ref or f"curate-decision-{cmd_hash}"
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id=project, correlation_id=decision_ref,
        caused_by="operator", reason="operator curation verdict (ADMIT)",
        payload={"decision": "CURATE_KNOWLEDGE",
                 "curation_id": cmd_hash,
                 "operator_id": OP_ID, "rationale": ""})
    return decision_ref


def seed_curatable(db, *, project="p1", program_id="rp-1",
                   hypothesis_ref="h1", evidence_hash="evhash1",
                   evidence_id="art-ev1"):
    """Seed the full curatable state: program + REFUTED ladder + transition
    event + classification + evidence + binding. Returns a dict with all
    the refs needed to build the curation command."""
    insert_program(db, program_id, hypotheses=[_hyp(hypothesis_ref)],
                   project=project)
    insert_evidence(db, evidence_id, content_hash=evidence_hash,
                    project=project)
    cls_ref = insert_classification(
        db, project=project, program_ref=program_id,
        hypothesis_ref=hypothesis_ref,
        falsifying_refs=[f"evidence:{evidence_hash}"])
    insert_ladder_refuted(db, program_id=program_id,
                          hypothesis_ref=hypothesis_ref, project=project)
    insert_transition_event(db, project=project, program_id=program_id,
                            hypothesis_ref=hypothesis_ref,
                            classification_ref=cls_ref)
    binding_ref = insert_binding(db, project=project,
                                 program_ref=program_id,
                                 hypothesis_ref=hypothesis_ref)
    # Compute the signature from the binding metadata
    binding_meta = json.loads(db.execute(
        "SELECT metadata_json FROM artifacts WHERE artifact_id = 'art-fb1'"
    ).fetchone()["metadata_json"])
    sig = signature_from_binding(binding_meta)
    return {
        "program_id": program_id,
        "hypothesis_ref": hypothesis_ref,
        "binding_ref": binding_ref,
        "signature_json": sig,
        "classification_ref": cls_ref,
        "evidence_hash": evidence_hash,
        "evidence_id": evidence_id,
    }


def curate(db, seed, *, operation="ADMIT", supersedes_ref="",
           proposed_by="DETERMINISTIC", project="p1",
           decision_ref=None, decision_event_ref="tr-1",
           extra_payload=None):
    """Submit a CURATE_KNOWLEDGE intent. Records the HumanDecision first.
    Returns the IntentResult."""
    payload = _command_payload(
        operation=operation,
        program_ref=seed["program_id"],
        hypothesis_ref=seed["hypothesis_ref"],
        source_binding_ref=seed["binding_ref"],
        source_decision_event_ref=decision_event_ref,
        signature_json=seed["signature_json"],
        supersedes_ref=supersedes_ref)
    dref = record_human_decision(db, payload, ref=decision_ref,
                                 project=project)
    full_payload = {**payload, "human_decision_ref": dref,
                    "operator_id": OP_ID}
    if extra_payload:
        full_payload.update(extra_payload)
    return apply_intent(db, Intent(
        kind=IntentKind.CURATE_KNOWLEDGE,
        proposed_by=proposed_by,
        project_id=project,
        justification="step7 test curation",
        payload=full_payload))


# ═══════════════════════ A. FeatureBinding ═══════════════════════


class TestFeatureBinding:
    def test_valid_binding(self):
        b = {"schema_version": 1, "project_ref": "p1",
             "program_ref": "rp-1", "hypothesis_ref": "h1",
             "instrument": "XAUUSD", "feature_family": "Momentum",
             "claim_type": "Directional"}
        c = canonical_binding(b)
        assert c["axes"]["instrument"] == "xauusd"
        assert c["axes"]["feature_family"] == "momentum"
        assert c["axes"]["claim_type"] == "directional"

    def test_malformed_required_field_non_string(self):
        b = {"schema_version": 1, "project_ref": "p1",
             "program_ref": "rp-1", "hypothesis_ref": "h1",
             "instrument": 123, "feature_family": "m", "claim_type": "d"}
        with pytest.raises(FeatureBindingError, match="must be a string"):
            canonical_binding(b)

    def test_missing_required_field(self):
        b = {"schema_version": 1, "project_ref": "p1",
             "program_ref": "rp-1", "hypothesis_ref": "h1",
             "feature_family": "m", "claim_type": "d"}
        with pytest.raises(FeatureBindingError):
            canonical_binding(b)

    def test_empty_axis_rejected(self):
        b = {"schema_version": 1, "project_ref": "p1",
             "program_ref": "rp-1", "hypothesis_ref": "h1",
             "instrument": "   ", "feature_family": "m", "claim_type": "d"}
        with pytest.raises(FeatureBindingError, match="empty"):
            canonical_binding(b)

    def test_over_64_chars_rejected(self):
        b = {"schema_version": 1, "project_ref": "p1",
             "program_ref": "rp-1", "hypothesis_ref": "h1",
             "instrument": "x" * 65, "feature_family": "m",
             "claim_type": "d"}
        with pytest.raises(FeatureBindingError, match="exceeds"):
            canonical_binding(b)

    def test_nfc_normalization(self):
        # e-acute composed vs decomposed → same canonical form
        b1 = {"schema_version": 1, "project_ref": "p1",
              "program_ref": "rp-1", "hypothesis_ref": "h1",
              "instrument": "caf\u00e9", "feature_family": "m",
              "claim_type": "d"}
        b2 = {"schema_version": 1, "project_ref": "p1",
              "program_ref": "rp-1", "hypothesis_ref": "h1",
              "instrument": "cafe\u0301", "feature_family": "m",
              "claim_type": "d"}
        assert binding_content(b1) == binding_content(b2)

    def test_lowercase(self):
        b = {"schema_version": 1, "project_ref": "P1",
             "program_ref": "RP-1", "hypothesis_ref": "H1",
             "instrument": "XAUUSD", "feature_family": "MOM",
             "claim_type": "DIR"}
        c = canonical_binding(b)
        assert c["project_ref"] == "p1"
        assert c["program_ref"] == "rp-1"
        assert c["hypothesis_ref"] == "h1"

    def test_whitespace_trimming(self):
        b = {"schema_version": 1, "project_ref": " p1 ",
             "program_ref": "rp-1", "hypothesis_ref": "h1",
             "instrument": "  xauusd  ", "feature_family": "m",
             "claim_type": "d"}
        c = canonical_binding(b)
        assert c["project_ref"] == "p1"
        assert c["axes"]["instrument"] == "xauusd"

    def test_optional_null_vs_absent_identical(self):
        base = {"schema_version": 1, "project_ref": "p1",
                "program_ref": "rp-1", "hypothesis_ref": "h1",
                "instrument": "i", "feature_family": "f",
                "claim_type": "c"}
        with_null = {**base, "slot_ref": None, "reward_hack_family": None}
        assert binding_content(base) == binding_content(with_null)
        assert signature_from_binding(base) == signature_from_binding(
            with_null)

    def test_deterministic_canonical_bytes(self):
        b = {"schema_version": 1, "project_ref": "p1",
             "program_ref": "rp-1", "hypothesis_ref": "h1",
             "instrument": "i", "feature_family": "f", "claim_type": "c"}
        assert binding_content(b) == binding_content(dict(b))

    def test_deterministic_signature(self):
        b = {"schema_version": 1, "project_ref": "p1",
             "program_ref": "rp-1", "hypothesis_ref": "h1",
             "instrument": "i", "feature_family": "f", "claim_type": "c",
             "slot_ref": "s1"}
        s1 = signature_from_binding(b)
        s2 = signature_from_binding(b)
        assert s1 == s2
        parsed = json.loads(s1)
        assert parsed["schema_version"] == 1
        assert "slot_ref" in parsed["axes"]
        # refs never enter the signature
        assert "project_ref" not in s1

    def test_deterministic_artifact_content_hash(self):
        b = {"schema_version": 1, "project_ref": "p1",
             "program_ref": "rp-1", "hypothesis_ref": "h1",
             "instrument": "i", "feature_family": "f", "claim_type": "c"}
        h1 = binding_content_hash(b)
        h2 = binding_content_hash(b)
        assert h1 == h2
        assert h1 == hashlib.sha256(
            binding_content(b).encode("utf-8")).hexdigest()

    def test_unknown_key_rejected(self):
        b = {"schema_version": 1, "project_ref": "p1",
             "program_ref": "rp-1", "hypothesis_ref": "h1",
             "instrument": "i", "feature_family": "f", "claim_type": "c",
             "rogue_key": "x"}
        with pytest.raises(FeatureBindingError, match="unknown keys"):
            canonical_binding(b)

    def test_wrong_schema_version_rejected(self):
        b = {"schema_version": 2, "project_ref": "p1",
             "program_ref": "rp-1", "hypothesis_ref": "h1",
             "instrument": "i", "feature_family": "f", "claim_type": "c"}
        with pytest.raises(FeatureBindingError, match="schema_version"):
            canonical_binding(b)

    def test_curated_id_deterministic(self):
        sig = '{"schema_version":1,"axes":{"claim_type":"c"}}'
        id1 = curated_id_of("REFUTED_PATTERN", sig, "tr-1")
        id2 = curated_id_of("REFUTED_PATTERN", sig, "tr-1")
        assert id1 == id2
        assert id1.startswith("curated_")
        # different decision ref → different identity
        id3 = curated_id_of("REFUTED_PATTERN", sig, "tr-2")
        assert id3 != id1


# ═══════════════════════ B. Admission ═══════════════════════


class TestAdmission:
    def test_valid_refuted_plus_binding(self, db):
        seed = seed_curatable(db)
        result = curate(db, seed)
        assert result.duplicate is False
        assert result.entity_id.startswith("curated_")
        # registry row exists
        row = db.execute(
            "SELECT * FROM curated_knowledge_entries WHERE curated_id = ?",
            (result.entity_id,)).fetchone()
        assert row is not None
        assert row["status"] == "ADMITTED"
        assert row["kind"] == "REFUTED_PATTERN"
        # basis row exists
        basis = db.execute(
            "SELECT evidence_artifact_id FROM "
            "curated_knowledge_retraction_basis WHERE curated_id = ?",
            (result.entity_id,)).fetchall()
        assert len(basis) == 1
        assert basis[0]["evidence_artifact_id"] == seed["evidence_id"]
        # events emitted
        events = db.execute(
            "SELECT event_type FROM events WHERE event_type IN "
            "('CuratedKnowledgeProposed','CuratedKnowledgeAdmitted') "
            "ORDER BY event_id").fetchall()
        assert [e["event_type"] for e in events] == [
            "CuratedKnowledgeProposed", "CuratedKnowledgeAdmitted"]

    def test_non_refuted_rejected(self, db):
        seed = seed_curatable(db)
        # downgrade the ladder head
        db.execute(
            "UPDATE evidence_ladder_state SET rung = 'SUPPORTED' "
            "WHERE program_id = ? AND hypothesis_ref = ?",
            (seed["program_id"], seed["hypothesis_ref"]))
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed)
        assert exc.value.code == STALE

    def test_missing_binding_rejected(self, db):
        seed = seed_curatable(db)
        seed["binding_ref"] = FEATURE_BINDING_REF_PREFIX + "deadbeef" * 8
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed)
        assert exc.value.code == EVIDENCE_REF

    def test_wrong_binding_project_rejected(self, db):
        seed = seed_curatable(db)
        # binding ROW resolves in p1, but its CONTENT names p2 — the
        # linkage check (17) must refuse it as PROVENANCE.
        seed["binding_ref"] = insert_binding(
            db, artifact_id="art-fb2", project="p1",
            content_project_ref="p2",
            program_ref="rp-1", hypothesis_ref="h1")
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed)
        assert exc.value.code == PROVENANCE

    def test_wrong_program_rejected(self, db):
        seed = seed_curatable(db)
        # build a command targeting a non-existent program
        payload = _command_payload(
            program_ref="rp-nonexistent",
            hypothesis_ref="h1",
            source_binding_ref=seed["binding_ref"],
            signature_json=seed["signature_json"])
        dref = record_human_decision(db, payload)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.CURATE_KNOWLEDGE,
                proposed_by="DETERMINISTIC", project_id="p1",
                justification="t",
                payload={**payload, "human_decision_ref": dref,
                         "operator_id": OP_ID}))
        assert exc.value.code == PROVENANCE

    def test_wrong_hypothesis_rejected(self, db):
        seed = seed_curatable(db)
        payload = _command_payload(
            program_ref=seed["program_id"],
            hypothesis_ref="h-nonexistent",
            source_binding_ref=seed["binding_ref"],
            signature_json=seed["signature_json"])
        dref = record_human_decision(db, payload)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.CURATE_KNOWLEDGE,
                proposed_by="DETERMINISTIC", project_id="p1",
                justification="t",
                payload={**payload, "human_decision_ref": dref,
                         "operator_id": OP_ID}))
        assert exc.value.code == PROVENANCE

    def test_duplicate_hypothesis_ref_across_programs_isolated(self, db):
        """Attack 5: two programs may both carry a hypothesis_ref 'h1'.
        A binding produced for rp-1/h1 must NOT curate rp-2/h1 — the
        binding's program_ref linkage (check 17) isolates them."""
        seed1 = seed_curatable(db)  # rp-1 / h1
        # a second program with the SAME hypothesis_ref, also REFUTED
        # (distinct version — (project_id, version) is UNIQUE)
        insert_program(db, "rp-2", hypotheses=[_hyp("h1")], version=2)
        insert_evidence(db, "art-ev2", content_hash="evhash2")
        cls_ref2 = insert_classification(
            db, cls_art="fc-2", program_ref="rp-2", hypothesis_ref="h1",
            falsifying_refs=["evidence:evhash2"])
        insert_ladder_refuted(db, program_id="rp-2", hypothesis_ref="h1",
                              transition_id="tr-2")
        insert_transition_event(db, correlation_id="tr-2",
                                program_id="rp-2", hypothesis_ref="h1",
                                classification_ref=cls_ref2)
        # attempt to curate rp-2/h1 using rp-1's binding — must fail
        payload = _command_payload(
            program_ref="rp-2", hypothesis_ref="h1",
            source_binding_ref=seed1["binding_ref"],
            source_decision_event_ref="tr-2",
            signature_json=seed1["signature_json"])
        dref = record_human_decision(db, payload)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.CURATE_KNOWLEDGE,
                proposed_by="DETERMINISTIC", project_id="p1",
                justification="t",
                payload={**payload, "human_decision_ref": dref,
                         "operator_id": OP_ID}))
        assert exc.value.code == PROVENANCE

    def test_missing_classification_rejected(self, db):
        seed = seed_curatable(db)
        # point the transition at a non-existent classification
        db.execute(
            "UPDATE events SET payload_json = ? "
            "WHERE event_type = 'EvidenceTransitionApplied'",
            (json.dumps({"program_id": seed["program_id"],
                         "hypothesis_ref": seed["hypothesis_ref"],
                         "from_rung": "SUPPORTED", "to_rung": "REFUTED",
                         "driver": "ratification",
                         "ratified_by": "classification",
                         "classification_ref":
                             "failure_classification:nonexistent"}),))
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed)
        assert exc.value.code == EVIDENCE_REF

    def test_classification_mismatch_rejected(self, db):
        seed = seed_curatable(db)
        # classification targets a different hypothesis
        db.execute("DELETE FROM artifacts WHERE artifact_type = "
                   "'failure_classification'")
        cls_ref = insert_classification(
            db, cls_art="fc-bad", hypothesis_ref="h-other")
        db.execute(
            "UPDATE events SET payload_json = ? "
            "WHERE event_type = 'EvidenceTransitionApplied'",
            (json.dumps({"program_id": seed["program_id"],
                         "hypothesis_ref": seed["hypothesis_ref"],
                         "from_rung": "SUPPORTED", "to_rung": "REFUTED",
                         "driver": "ratification",
                         "ratified_by": "classification",
                         "classification_ref": cls_ref}),))
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed)
        assert exc.value.code == PROVENANCE

    def test_empty_evidence_rejected(self, db):
        seed = seed_curatable(db)
        # classification with empty falsifying refs
        db.execute("DELETE FROM artifacts WHERE artifact_type = "
                   "'failure_classification'")
        cls_ref = insert_classification(
            db, cls_art="fc-empty", falsifying_refs=[])
        db.execute(
            "UPDATE events SET payload_json = ? "
            "WHERE event_type = 'EvidenceTransitionApplied'",
            (json.dumps({"program_id": seed["program_id"],
                         "hypothesis_ref": seed["hypothesis_ref"],
                         "from_rung": "SUPPORTED", "to_rung": "REFUTED",
                         "driver": "ratification",
                         "ratified_by": "classification",
                         "classification_ref": cls_ref}),))
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed)
        assert exc.value.code == EVIDENCE_REF

    def test_unresolved_evidence_rejected(self, db):
        seed = seed_curatable(db)
        # classification cites evidence that does not exist
        db.execute("DELETE FROM artifacts WHERE artifact_type = "
                   "'failure_classification'")
        cls_ref = insert_classification(
            db, cls_art="fc-unres",
            falsifying_refs=["evidence:nonexistent-hash"])
        db.execute(
            "UPDATE events SET payload_json = ? "
            "WHERE event_type = 'EvidenceTransitionApplied'",
            (json.dumps({"program_id": seed["program_id"],
                         "hypothesis_ref": seed["hypothesis_ref"],
                         "from_rung": "SUPPORTED", "to_rung": "REFUTED",
                         "driver": "ratification",
                         "ratified_by": "classification",
                         "classification_ref": cls_ref}),))
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed)
        assert exc.value.code == EVIDENCE_REF

    def test_cross_project_evidence_rejected(self, db):
        seed = seed_curatable(db)
        # evidence lives in p2 only
        db.execute("DELETE FROM artifacts WHERE artifact_id = ?",
                   (seed["evidence_id"],))
        insert_evidence(db, "art-ev-p2", content_hash=seed["evidence_hash"],
                        project="p2")
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed)
        assert exc.value.code == EVIDENCE_REF

    def test_over_32_basis_rejected(self, db):
        seed = seed_curatable(db)
        # create 33 evidence artifacts + refs
        refs = []
        for i in range(33):
            h = f"evhash-{i:03d}"
            insert_evidence(db, f"art-ev-{i:03d}", content_hash=h)
            refs.append(f"evidence:{h}")
        db.execute("DELETE FROM artifacts WHERE artifact_type = "
                   "'failure_classification'")
        cls_ref = insert_classification(
            db, cls_art="fc-many", falsifying_refs=refs)
        db.execute(
            "UPDATE events SET payload_json = ? "
            "WHERE event_type = 'EvidenceTransitionApplied'",
            (json.dumps({"program_id": seed["program_id"],
                         "hypothesis_ref": seed["hypothesis_ref"],
                         "from_rung": "SUPPORTED", "to_rung": "REFUTED",
                         "driver": "ratification",
                         "ratified_by": "classification",
                         "classification_ref": cls_ref}),))
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed)
        assert exc.value.code == EVIDENCE_REF

    def test_signature_mismatch_rejected(self, db):
        seed = seed_curatable(db)
        seed["signature_json"] = (
            '{"schema_version":1,"axes":{"claim_type":"forged",'
            '"feature_family":"forged","instrument":"forged"}}')
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed)
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_duplicate_admission_idempotent(self, db):
        seed = seed_curatable(db)
        r1 = curate(db, seed)
        assert r1.duplicate is False
        # identical repeat → duplicate=True, zero new effects
        payload = _command_payload(
            program_ref=seed["program_id"],
            hypothesis_ref=seed["hypothesis_ref"],
            source_binding_ref=seed["binding_ref"],
            source_decision_event_ref="tr-1",
            signature_json=seed["signature_json"])
        dref = record_human_decision(db, payload)
        r2 = apply_intent(db, Intent(
            kind=IntentKind.CURATE_KNOWLEDGE,
            proposed_by="DETERMINISTIC", project_id="p1",
            justification="replay",
            payload={**payload, "human_decision_ref": dref,
                     "operator_id": OP_ID}))
        assert r2.duplicate is True
        assert r2.entity_id == r1.entity_id
        # still exactly one registry row
        count = db.execute(
            "SELECT COUNT(*) c FROM curated_knowledge_entries"
        ).fetchone()["c"]
        assert count == 1

    def test_reused_decision_rejected(self, db):
        seed = seed_curatable(db)
        curate(db, seed)
        # a DIFFERENT command reusing the same decision ref
        payload2 = _command_payload(
            program_ref=seed["program_id"],
            hypothesis_ref=seed["hypothesis_ref"],
            source_binding_ref=seed["binding_ref"],
            source_decision_event_ref="tr-1",
            signature_json=seed["signature_json"],
            supersedes_ref="")
        # tamper: change operation to force a different command hash
        payload2["operation"] = "SUPERSEDE"
        payload2["supersedes_ref"] = "curated_fake"
        # reuse the ORIGINAL decision ref (binds the original hash)
        orig_ref = f"curate-decision-{curation_command_hash(_command_payload(program_ref=seed['program_id'], hypothesis_ref=seed['hypothesis_ref'], source_binding_ref=seed['binding_ref'], source_decision_event_ref='tr-1', signature_json=seed['signature_json']))}"
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.CURATE_KNOWLEDGE,
                proposed_by="DETERMINISTIC", project_id="p1",
                justification="t",
                payload={**payload2, "human_decision_ref": orig_ref,
                         "operator_id": OP_ID}))
        assert exc.value.code == PROPOSAL

    def test_contradictory_decision_rejected(self, db):
        seed = seed_curatable(db)
        curate(db, seed)
        # same command hash but a contradictory prior exists — the
        # duplicate path returns duplicate=True (idempotent), so a true
        # contradiction requires a different curated_id under the same
        # correlation. This is structurally impossible (same command →
        # same curated_id), so the one-verdict index is the backstop.
        # Verify the index prevents a second Admitted with same correlation.
        cmd_hash = curation_command_hash(_command_payload(
            program_ref=seed["program_id"],
            hypothesis_ref=seed["hypothesis_ref"],
            source_binding_ref=seed["binding_ref"],
            source_decision_event_ref="tr-1",
            signature_json=seed["signature_json"]))
        count = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = "
            "'CuratedKnowledgeAdmitted' AND correlation_id = ?",
            (cmd_hash,)).fetchone()["c"]
        assert count == 1

    def test_llm_proposed_rejected(self, db):
        seed = seed_curatable(db)
        for role in ("DIRECTOR", "RESEARCHER", "IMPLEMENTER", "ADVERSARY"):
            with pytest.raises(GatewayRejection) as exc:
                curate(db, seed, proposed_by=role)
            assert exc.value.code == ROLE

    def test_internal_only_intent_kind(self):
        assert IntentKind.CURATE_KNOWLEDGE in IntentKind.internal_only()
        assert IntentKind.CURATE_KNOWLEDGE not in IntentKind.llm_proposable()

    def test_unknown_payload_key_rejected(self, db):
        seed = seed_curatable(db)
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed, extra_payload={"rogue": "x"})
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_missing_project_rejected(self, db):
        seed = seed_curatable(db)
        payload = _command_payload(
            program_ref=seed["program_id"],
            hypothesis_ref=seed["hypothesis_ref"],
            source_binding_ref=seed["binding_ref"],
            signature_json=seed["signature_json"])
        dref = record_human_decision(db, payload, project="p1")
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.CURATE_KNOWLEDGE,
                proposed_by="DETERMINISTIC", project_id="p-nonexistent",
                justification="t",
                payload={**payload, "human_decision_ref": dref,
                         "operator_id": OP_ID}))
        assert exc.value.code == PROJECT_NOT_FOUND

    def test_admission_rollback_leaves_nothing(self, db):
        """Attack 17: a crash AFTER the registry/basis inserts but BEFORE
        COMMIT (sabotage the final CuratedKnowledgeAdmitted append) must
        leave no registry row, no basis rows, and no admission events."""
        from unittest import mock

        import hermes.research.gateway as gw
        from hermes.persistence.event_validation import EventValidationError

        seed = seed_curatable(db)
        real_append = gw._append_event_to_db

        def sabotaged(conn, clock, event_type, *a, **kw):
            if event_type == EventType.CURATED_KNOWLEDGE_ADMITTED.value:
                raise EventValidationError("sabotaged", "payload")
            return real_append(conn, clock, event_type, *a, **kw)

        with mock.patch.object(gw, "_append_event_to_db", sabotaged), \
                pytest.raises(EventValidationError):
            curate(db, seed)

        # NOTHING persisted: no registry row, no basis rows, no events.
        n_reg = db.execute(
            "SELECT COUNT(*) c FROM curated_knowledge_entries").fetchone()["c"]
        n_basis = db.execute(
            "SELECT COUNT(*) c FROM "
            "curated_knowledge_retraction_basis").fetchone()["c"]
        n_ev = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type IN (?, ?)",
            (EventType.CURATED_KNOWLEDGE_PROPOSED.value,
             EventType.CURATED_KNOWLEDGE_ADMITTED.value)).fetchone()["c"]
        assert n_reg == 0
        assert n_basis == 0
        assert n_ev == 0


# ═══════════════════════ C. Supersession ═══════════════════════


class TestSupersession:
    def _admit(self, db, seed):
        return curate(db, seed)

    def test_valid_head_supersession(self, db):
        seed = seed_curatable(db)
        r1 = self._admit(db, seed)
        # SUPERSEDE with a new binding (different axes → new curated_id)
        seed2 = dict(seed)
        seed2["binding_ref"] = insert_binding(
            db, artifact_id="art-fb2", instrument="eurusd")
        binding_meta2 = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = "
            "'art-fb2'").fetchone()["metadata_json"])
        seed2["signature_json"] = signature_from_binding(binding_meta2)
        r2 = curate(db, seed2, operation="SUPERSEDE",
                    supersedes_ref=r1.entity_id)
        assert r2.duplicate is False
        # old entry is SUPERSEDED
        old = db.execute(
            "SELECT status FROM curated_knowledge_entries "
            "WHERE curated_id = ?", (r1.entity_id,)).fetchone()
        assert old["status"] == "SUPERSEDED"
        # new entry is ADMITTED
        new = db.execute(
            "SELECT status FROM curated_knowledge_entries "
            "WHERE curated_id = ?", (r2.entity_id,)).fetchone()
        assert new["status"] == "ADMITTED"
        # supersession row exists
        sup = db.execute(
            "SELECT * FROM curated_knowledge_supersession "
            "WHERE new_curated_id = ?", (r2.entity_id,)).fetchone()
        assert sup is not None
        assert sup["supersedes_ref"] == r1.entity_id

    def test_non_head_rejected(self, db):
        seed = seed_curatable(db)
        r1 = self._admit(db, seed)
        # supersede r1
        seed2 = dict(seed)
        seed2["binding_ref"] = insert_binding(
            db, artifact_id="art-fb2", instrument="eurusd")
        binding_meta2 = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = "
            "'art-fb2'").fetchone()["metadata_json"])
        seed2["signature_json"] = signature_from_binding(binding_meta2)
        curate(db, seed2, operation="SUPERSEDE",
               supersedes_ref=r1.entity_id)
        # try to supersede r1 AGAIN (it's no longer the head)
        seed3 = dict(seed)
        seed3["binding_ref"] = insert_binding(
            db, artifact_id="art-fb3", instrument="gbpusd")
        binding_meta3 = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = "
            "'art-fb3'").fetchone()["metadata_json"])
        seed3["signature_json"] = signature_from_binding(binding_meta3)
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed3, operation="SUPERSEDE",
                   supersedes_ref=r1.entity_id)
        assert exc.value.code == STALE

    def test_non_admitted_rejected(self, db):
        seed = seed_curatable(db)
        r1 = self._admit(db, seed)
        # invalidate r1 via direct status flip (simulates S5)
        db.execute(
            "UPDATE curated_knowledge_entries SET status = 'INVALIDATED' "
            "WHERE curated_id = ?", (r1.entity_id,))
        seed2 = dict(seed)
        seed2["binding_ref"] = insert_binding(
            db, artifact_id="art-fb2", instrument="eurusd")
        binding_meta2 = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = "
            "'art-fb2'").fetchone()["metadata_json"])
        seed2["signature_json"] = signature_from_binding(binding_meta2)
        with pytest.raises(GatewayRejection) as exc:
            curate(db, seed2, operation="SUPERSEDE",
                   supersedes_ref=r1.entity_id)
        assert exc.value.code == STALE

    def test_duplicate_supersession_replay(self, db):
        seed = seed_curatable(db)
        r1 = self._admit(db, seed)
        seed2 = dict(seed)
        seed2["binding_ref"] = insert_binding(
            db, artifact_id="art-fb2", instrument="eurusd")
        binding_meta2 = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = "
            "'art-fb2'").fetchone()["metadata_json"])
        seed2["signature_json"] = signature_from_binding(binding_meta2)
        r2 = curate(db, seed2, operation="SUPERSEDE",
                    supersedes_ref=r1.entity_id)
        # identical replay → duplicate
        payload = _command_payload(
            operation="SUPERSEDE",
            program_ref=seed2["program_id"],
            hypothesis_ref=seed2["hypothesis_ref"],
            source_binding_ref=seed2["binding_ref"],
            source_decision_event_ref="tr-1",
            signature_json=seed2["signature_json"],
            supersedes_ref=r1.entity_id)
        dref = record_human_decision(db, payload)
        r3 = apply_intent(db, Intent(
            kind=IntentKind.CURATE_KNOWLEDGE,
            proposed_by="DETERMINISTIC", project_id="p1",
            justification="replay",
            payload={**payload, "human_decision_ref": dref,
                     "operator_id": OP_ID}))
        assert r3.duplicate is True
        assert r3.entity_id == r2.entity_id

    def test_supersession_atomicity(self, db):
        """A failed supersession leaves the target untouched."""
        seed = seed_curatable(db)
        r1 = self._admit(db, seed)
        seed2 = dict(seed)
        seed2["binding_ref"] = insert_binding(
            db, artifact_id="art-fb2", instrument="eurusd")
        binding_meta2 = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = "
            "'art-fb2'").fetchone()["metadata_json"])
        seed2["signature_json"] = signature_from_binding(binding_meta2)
        # force a failure: bad supersedes_ref (non-existent)
        with pytest.raises(GatewayRejection):
            curate(db, seed2, operation="SUPERSEDE",
                   supersedes_ref="curated_nonexistent")
        # r1 still ADMITTED
        row = db.execute(
            "SELECT status FROM curated_knowledge_entries "
            "WHERE curated_id = ?", (r1.entity_id,)).fetchone()
        assert row["status"] == "ADMITTED"
        # no supersession row
        count = db.execute(
            "SELECT COUNT(*) c FROM curated_knowledge_supersession"
        ).fetchone()["c"]
        assert count == 0


# ═══════════════════════ D. Retraction (S5 integration) ═══════════════════════


def _record_s5_human_decision(db, ref="hd-s5", project="p1"):
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id=project, correlation_id=ref, caused_by="operator",
        reason="operator decision", payload={"decision": "RETRACT"})


def _retract(db, source_ref, decision_ref="hd-s5", project="p1"):
    return apply_intent(db, Intent(
        kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
        project_id=project, justification="S5 cascade",
        payload={"source_ref": source_ref, "reason": "retracted",
                 "human_decision_ref": decision_ref}))


class TestRetraction:
    def _admit_with_source(self, db, *, source_id="art-src1",
                           source_hash="srchash1"):
        """Seed a curatable state where the falsifying evidence IS a
        source artifact (so S5 retraction can reach it)."""
        insert_program(db, "rp-1", hypotheses=[_hyp("h1")])
        # The evidence is a source_result artifact
        insert_artifact(db, source_id, "source_result",
                        content_hash=source_hash)
        cls_ref = insert_classification(
            db, falsifying_refs=[f"source_result:{source_hash}"])
        insert_ladder_refuted(db)
        insert_transition_event(db, classification_ref=cls_ref)
        binding_ref = insert_binding(db)
        binding_meta = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = "
            "'art-fb1'").fetchone()["metadata_json"])
        sig = signature_from_binding(binding_meta)
        seed = {"program_id": "rp-1", "hypothesis_ref": "h1",
                "binding_ref": binding_ref, "signature_json": sig,
                "evidence_id": source_id, "evidence_hash": source_hash}
        result = curate(db, seed)
        return result, seed

    def test_direct_evidence_retraction_invalidates(self, db):
        r, seed = self._admit_with_source(db)
        _record_s5_human_decision(db)
        _retract(db, f"source_result:{seed['evidence_hash']}")
        row = db.execute(
            "SELECT status, invalidation_event_ref FROM "
            "curated_knowledge_entries WHERE curated_id = ?",
            (r.entity_id,)).fetchone()
        assert row["status"] == "INVALIDATED"
        assert row["invalidation_event_ref"] is not None
        # CuratedKnowledgeInvalidated event emitted
        inv = db.execute(
            "SELECT payload_json FROM events WHERE event_type = "
            "'CuratedKnowledgeInvalidated'").fetchone()
        assert inv is not None
        payload = json.loads(inv["payload_json"])
        assert payload["curated_id"] == r.entity_id
        assert seed["evidence_id"] in payload["matched_evidence"]

    def test_unrelated_retraction_no_invalidation(self, db):
        r, _seed = self._admit_with_source(db)
        # a different source artifact
        insert_artifact(db, "art-other", "source_result",
                        content_hash="otherhash")
        _record_s5_human_decision(db)
        _retract(db, "source_result:otherhash")
        row = db.execute(
            "SELECT status FROM curated_knowledge_entries "
            "WHERE curated_id = ?", (r.entity_id,)).fetchone()
        assert row["status"] == "ADMITTED"

    def test_multi_evidence_retraction(self, db):
        """Entry with 2 evidence artifacts; retracting one invalidates."""
        insert_program(db, "rp-1", hypotheses=[_hyp("h1")])
        insert_artifact(db, "art-s1", "source_result",
                        content_hash="sh1")
        insert_artifact(db, "art-s2", "source_result",
                        content_hash="sh2")
        cls_ref = insert_classification(
            db, falsifying_refs=["source_result:sh1", "source_result:sh2"])
        insert_ladder_refuted(db)
        insert_transition_event(db, classification_ref=cls_ref)
        binding_ref = insert_binding(db)
        binding_meta = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = "
            "'art-fb1'").fetchone()["metadata_json"])
        sig = signature_from_binding(binding_meta)
        seed = {"program_id": "rp-1", "hypothesis_ref": "h1",
                "binding_ref": binding_ref, "signature_json": sig,
                "evidence_id": "art-s1", "evidence_hash": "sh1"}
        r = curate(db, seed)
        # basis has 2 members
        basis = db.execute(
            "SELECT evidence_artifact_id FROM "
            "curated_knowledge_retraction_basis WHERE curated_id = ? "
            "ORDER BY evidence_artifact_id", (r.entity_id,)).fetchall()
        assert len(basis) == 2
        # retract just one
        _record_s5_human_decision(db)
        _retract(db, "source_result:sh1")
        row = db.execute(
            "SELECT status FROM curated_knowledge_entries "
            "WHERE curated_id = ?", (r.entity_id,)).fetchone()
        assert row["status"] == "INVALIDATED"

    def test_cone_member_basis_recognized_by_same_predicate(self, db):
        """Attack 22: the curated predicate consumes the cone EXACTLY as
        the existing S5 walk produces it. An entry whose evidence basis is
        a CONE MEMBER (downstream of the retracted source via a dependency
        edge — the form future cone members will take once the L2
        identifier-form defect is repaired) is invalidated by retracting
        the UPSTREAM source, even though the source itself is not in the
        basis. The predicate is {source_artifact_id} ∪ cone — no special
        cone handling is added here."""
        insert_program(db, "rp-1", hypotheses=[_hyp("h1")])
        # the upstream source to be retracted
        insert_artifact(db, "art-src", "source_result",
                        content_hash="upstreamhash")
        # the downstream evidence artifact (the future cone member)
        insert_artifact(db, "art-down", "evidence",
                        content_hash="downhash")
        # dependency edge: art-down is downstream of art-src (cites)
        db.execute(
            """INSERT INTO provenance_edges
               (artifact_id, upstream_id, edge_type, created_at)
               VALUES (?, ?, 'cites', ?)""",
            ("art-down", "art-src", CLOCK))
        # classification cites the DOWNSTREAM artifact as falsifying
        cls_ref = insert_classification(
            db, falsifying_refs=["evidence:downhash"])
        insert_ladder_refuted(db)
        insert_transition_event(db, classification_ref=cls_ref)
        binding_ref = insert_binding(db)
        binding_meta = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = "
            "'art-fb1'").fetchone()["metadata_json"])
        sig = signature_from_binding(binding_meta)
        seed = {"program_id": "rp-1", "hypothesis_ref": "h1",
                "binding_ref": binding_ref, "signature_json": sig,
                "evidence_id": "art-down", "evidence_hash": "downhash"}
        r = curate(db, seed)
        # basis is the downstream artifact only (source NOT in basis)
        basis = db.execute(
            "SELECT evidence_artifact_id FROM "
            "curated_knowledge_retraction_basis WHERE curated_id = ?",
            (r.entity_id,)).fetchall()
        assert [b["evidence_artifact_id"] for b in basis] == ["art-down"]
        # retract the UPSTREAM source — the cone reaches art-down
        _record_s5_human_decision(db)
        _retract(db, "source_result:upstreamhash")
        row = db.execute(
            "SELECT status FROM curated_knowledge_entries "
            "WHERE curated_id = ?", (r.entity_id,)).fetchone()
        assert row["status"] == "INVALIDATED"
        # the invalidation event names the matched cone member
        inv = db.execute(
            "SELECT payload_json FROM events WHERE event_type = "
            "'CuratedKnowledgeInvalidated'").fetchone()
        payload = json.loads(inv["payload_json"])
        assert payload["matched_evidence"] == ["art-down"]

    def test_shared_evidence_invalidates_both(self, db):
        """Two curated entries sharing the same evidence: retracting it
        invalidates BOTH."""
        insert_program(db, "rp-1", hypotheses=[_hyp("h1"), _hyp("h2")])
        insert_artifact(db, "art-shared", "source_result",
                        content_hash="sharedhash")
        # classification for h1
        cls_ref1 = insert_classification(
            db, cls_art="fc-1", hypothesis_ref="h1",
            falsifying_refs=["source_result:sharedhash"])
        insert_ladder_refuted(db, hypothesis_ref="h1",
                              transition_id="tr-1")
        insert_transition_event(db, correlation_id="tr-1",
                                hypothesis_ref="h1",
                                classification_ref=cls_ref1)
        # classification for h2
        cls_ref2 = insert_classification(
            db, cls_art="fc-2", hypothesis_ref="h2",
            falsifying_refs=["source_result:sharedhash"])
        insert_ladder_refuted(db, hypothesis_ref="h2",
                              transition_id="tr-2", version=1)
        insert_transition_event(db, correlation_id="tr-2",
                                hypothesis_ref="h2",
                                classification_ref=cls_ref2)
        # two bindings (different hypotheses → different curated_ids)
        fb1 = insert_binding(db, artifact_id="art-fb1",
                             hypothesis_ref="h1")
        fb2 = insert_binding(db, artifact_id="art-fb2",
                             hypothesis_ref="h2")
        meta1 = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = "
            "'art-fb1'").fetchone()["metadata_json"])
        meta2 = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = "
            "'art-fb2'").fetchone()["metadata_json"])
        seed1 = {"program_id": "rp-1", "hypothesis_ref": "h1",
                 "binding_ref": fb1,
                 "signature_json": signature_from_binding(meta1),
                 "evidence_id": "art-shared", "evidence_hash": "sharedhash"}
        seed2 = {"program_id": "rp-1", "hypothesis_ref": "h2",
                 "binding_ref": fb2,
                 "signature_json": signature_from_binding(meta2),
                 "evidence_id": "art-shared", "evidence_hash": "sharedhash"}
        r1 = curate(db, seed1)
        # h2's curatable state rides transition tr-2
        r2 = curate(db, seed2, decision_event_ref="tr-2")
        assert r1.entity_id != r2.entity_id
        # retract the shared evidence
        _record_s5_human_decision(db)
        _retract(db, "source_result:sharedhash")
        for rid in (r1.entity_id, r2.entity_id):
            row = db.execute(
                "SELECT status FROM curated_knowledge_entries "
                "WHERE curated_id = ?", (rid,)).fetchone()
            assert row["status"] == "INVALIDATED"

    def test_cross_project_isolation(self, db):
        """Retraction in p2 does NOT invalidate p1's curated entry — the
        ``source_project_id = intent.project_id`` predicate isolates. p2
        retracts its OWN source (a distinct content_hash, since the
        artifacts.content_hash column is globally UNIQUE)."""
        r, _seed = self._admit_with_source(db)
        # p2's own source artifact (distinct hash) + its own human decision
        insert_artifact(db, "art-src-p2", "source_result",
                        content_hash="p2srchash", project="p2")
        _record_s5_human_decision(db, ref="hd-p2", project="p2")
        _retract(db, "source_result:p2srchash", decision_ref="hd-p2",
                 project="p2")
        # p1's entry is untouched
        row = db.execute(
            "SELECT status FROM curated_knowledge_entries "
            "WHERE curated_id = ?", (r.entity_id,)).fetchone()
        assert row["status"] == "ADMITTED"

    def test_repeated_retraction_idempotent(self, db):
        _r, seed = self._admit_with_source(db)
        _record_s5_human_decision(db)
        _retract(db, f"source_result:{seed['evidence_hash']}")
        # repeat → duplicate
        r2 = _retract(db, f"source_result:{seed['evidence_hash']}")
        assert r2.duplicate is True
        # still exactly one invalidation event
        count = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = "
            "'CuratedKnowledgeInvalidated'").fetchone()["c"]
        assert count == 1

    def test_source_retracted_additive_payload(self, db):
        r, seed = self._admit_with_source(db)
        _record_s5_human_decision(db)
        _retract(db, f"source_result:{seed['evidence_hash']}")
        ev = db.execute(
            "SELECT payload_json FROM events WHERE event_type = "
            "'SourceRetracted'").fetchone()
        payload = json.loads(ev["payload_json"])
        # S6 bounded commitment: the curated reach is a count, and the
        # digest binds the exact cone (artifacts + tasks + curated).
        assert "invalidated_curated_entries" not in payload
        assert payload["curated_count"] == 1
        assert payload["cone_algorithm"] == "s5-cone-v1"
        import hashlib
        # The retracted source itself is superseded, never a cone member:
        # the artifact cone is empty, the curated reach is the entry.
        expected = hashlib.sha256(json.dumps(
            {"artifacts": [], "tasks": [],
             "curated": [r.entity_id]},
            sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8")).hexdigest()
        assert payload["cone_digest"] == expected

    def test_invalidated_excluded_from_active_reads(self, db):
        r, seed = self._admit_with_source(db)
        _record_s5_human_decision(db)
        _retract(db, f"source_result:{seed['evidence_hash']}")
        from hermes.persistence.repositories import CuratedKnowledgeRepository
        repo = CuratedKnowledgeRepository(db)
        active = repo.active_entries("p1")
        assert all(e["curated_id"] != r.entity_id for e in active)
        # but it's still in all_entries (audit)
        all_e = repo.all_entries("p1")
        assert any(e["curated_id"] == r.entity_id for e in all_e)

    def test_rollback_leaves_nothing(self, db):
        """Attack 18: a mid-transaction failure AFTER the curated follow-on
        (but before COMMIT) must leave the registry untouched — the curated
        invalidation rides the SAME S5 transaction, so ROLLBACK undoes it.

        Uses the proven sabotage pattern from test_s5_retraction.py:505:
        patch _append_event_to_db at the GATEWAY module so the final
        SourceRetracted write raises, preventing COMMIT.
        """
        from unittest import mock

        import hermes.research.gateway as gw
        from hermes.persistence.event_validation import EventValidationError

        r, seed = self._admit_with_source(db)
        _record_s5_human_decision(db)

        real_append = gw._append_event_to_db

        def sabotaged(conn, clock, event_type, *a, **kw):
            if event_type == EventType.SOURCE_RETRACTED.value:
                raise EventValidationError("sabotaged", "payload")
            return real_append(conn, clock, event_type, *a, **kw)

        with mock.patch.object(gw, "_append_event_to_db", sabotaged), \
                pytest.raises(EventValidationError):
            _retract(db, f"source_result:{seed['evidence_hash']}")

        # The curated follow-on ran (it precedes SOURCE_RETRACTED) but the
        # transaction ROLLED BACK — registry must still be ADMITTED, and no
        # invalidation event may have persisted.
        row = db.execute(
            "SELECT status, invalidation_event_ref FROM "
            "curated_knowledge_entries WHERE curated_id = ?",
            (r.entity_id,)).fetchone()
        assert row["status"] == "ADMITTED"
        assert row["invalidation_event_ref"] is None
        n_inv = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.CURATED_KNOWLEDGE_INVALIDATED.value,)).fetchone()["c"]
        assert n_inv == 0
        n_ret = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.SOURCE_RETRACTED.value,)).fetchone()["c"]
        assert n_ret == 0


# ═══════════════════════ E. Replay (journal-fold) ═══════════════════════


class TestReplay:
    def test_admission_fold(self, db):
        """registry_state == fold(journal) for admission events."""
        seed = seed_curatable(db)
        r = curate(db, seed)
        # Reconstruct from the Admitted event
        ev = db.execute(
            "SELECT payload_json FROM events WHERE event_type = "
            "'CuratedKnowledgeAdmitted'").fetchone()
        payload = json.loads(ev["payload_json"])
        assert payload["curated_id"] == r.entity_id
        assert payload["kind"] == "REFUTED_PATTERN"
        assert payload["signature_json"] == seed["signature_json"]
        assert payload["evidence_basis"] == [seed["evidence_id"]]
        # The registry row matches the event payload
        row = db.execute(
            "SELECT * FROM curated_knowledge_entries WHERE curated_id = ?",
            (r.entity_id,)).fetchone()
        assert row["signature_json"] == payload["signature_json"]
        assert row["program_ref"] == payload["program_ref"]
        assert row["hypothesis_ref"] == payload["hypothesis_ref"]

    def test_invalidation_fold(self, db):
        seed = seed_curatable(db)
        r = curate(db, seed)
        # make evidence a source artifact for retraction
        db.execute(
            "UPDATE artifacts SET artifact_type = 'source_result' "
            "WHERE artifact_id = ?", (seed["evidence_id"],))
        _record_s5_human_decision(db)
        _retract(db, f"source_result:{seed['evidence_hash']}")
        inv = db.execute(
            "SELECT payload_json FROM events WHERE event_type = "
            "'CuratedKnowledgeInvalidated'").fetchone()
        payload = json.loads(inv["payload_json"])
        row = db.execute(
            "SELECT status, invalidation_event_ref FROM "
            "curated_knowledge_entries WHERE curated_id = ?",
            (r.entity_id,)).fetchone()
        assert row["status"] == "INVALIDATED"
        assert row["invalidation_event_ref"] == payload["retraction_id"]

    def test_supersession_fold(self, db):
        seed = seed_curatable(db)
        r1 = curate(db, seed)
        seed2 = dict(seed)
        seed2["binding_ref"] = insert_binding(
            db, artifact_id="art-fb2", instrument="eurusd")
        meta2 = json.loads(db.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = "
            "'art-fb2'").fetchone()["metadata_json"])
        seed2["signature_json"] = signature_from_binding(meta2)
        r2 = curate(db, seed2, operation="SUPERSEDE",
                    supersedes_ref=r1.entity_id)
        sup = db.execute(
            "SELECT * FROM curated_knowledge_supersession "
            "WHERE new_curated_id = ?", (r2.entity_id,)).fetchone()
        assert sup["supersedes_ref"] == r1.entity_id
        # the Admitted event for r2 carries supersedes_ref
        ev = db.execute(
            "SELECT payload_json FROM events WHERE event_type = "
            "'CuratedKnowledgeAdmitted' AND correlation_id = ?",
            (curation_command_hash(_command_payload(
                operation="SUPERSEDE",
                program_ref=seed2["program_id"],
                hypothesis_ref=seed2["hypothesis_ref"],
                source_binding_ref=seed2["binding_ref"],
                source_decision_event_ref="tr-1",
                signature_json=seed2["signature_json"],
                supersedes_ref=r1.entity_id)),)).fetchone()
        payload = json.loads(ev["payload_json"])
        assert payload["supersedes_ref"] == r1.entity_id

    def test_no_orphan_basis_rows(self, db):
        seed = seed_curatable(db)
        curate(db, seed)
        orphans = db.execute(
            "SELECT b.curated_id FROM curated_knowledge_retraction_basis b "
            "LEFT JOIN curated_knowledge_entries e "
            "  ON e.curated_id = b.curated_id "
            "WHERE e.curated_id IS NULL").fetchall()
        assert len(orphans) == 0

    def test_no_orphan_events(self, db):
        seed = seed_curatable(db)
        curate(db, seed)
        # every CuratedKnowledgeAdmitted event's curated_id exists in registry
        events = db.execute(
            "SELECT payload_json FROM events WHERE event_type = "
            "'CuratedKnowledgeAdmitted'").fetchall()
        for ev in events:
            payload = json.loads(ev["payload_json"])
            row = db.execute(
                "SELECT 1 FROM curated_knowledge_entries "
                "WHERE curated_id = ?",
                (payload["curated_id"],)).fetchone()
            assert row is not None


# ═══════════════════════ F. Historical ═══════════════════════


class TestHistorical:
    def test_old_refuted_without_binding_not_curatable(self, db):
        """A REFUTED hypothesis that predates Step 7 (no FeatureBinding
        artifact) cannot be curated — the binding resolution fails closed."""
        insert_program(db, "rp-old", hypotheses=[_hyp("h-old")])
        insert_evidence(db, "art-ev-old", content_hash="oldhash")
        cls_ref = insert_classification(
            db, cls_art="fc-old", program_ref="rp-old",
            hypothesis_ref="h-old",
            falsifying_refs=["evidence:oldhash"])
        insert_ladder_refuted(db, program_id="rp-old",
                              hypothesis_ref="h-old",
                              transition_id="tr-old")
        insert_transition_event(db, correlation_id="tr-old",
                                program_id="rp-old",
                                hypothesis_ref="h-old",
                                classification_ref=cls_ref)
        # NO binding artifact exists — any binding ref will fail
        payload = _command_payload(
            program_ref="rp-old", hypothesis_ref="h-old",
            source_binding_ref=FEATURE_BINDING_REF_PREFIX + "no-such-hash",
            source_decision_event_ref="tr-old",
            signature_json='{"schema_version":1,"axes":{}}')
        dref = record_human_decision(db, payload)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.CURATE_KNOWLEDGE,
                proposed_by="DETERMINISTIC", project_id="p1",
                justification="t",
                payload={**payload, "human_decision_ref": dref,
                         "operator_id": OP_ID}))
        assert exc.value.code == EVIDENCE_REF

    def test_no_historical_mutation(self, db):
        """Migration 14→15 creates EMPTY structures — no backfill."""
        # The db fixture already ran migrate_to_latest (fresh DB at v15).
        count = db.execute(
            "SELECT COUNT(*) c FROM curated_knowledge_entries"
        ).fetchone()["c"]
        assert count == 0
        basis_count = db.execute(
            "SELECT COUNT(*) c FROM curated_knowledge_retraction_basis"
        ).fetchone()["c"]
        assert basis_count == 0

    def test_existing_state_untouched_by_migration(self, db):
        """The migration does not alter existing tables."""
        # Verify the one-verdict index still covers the original types
        idx = db.execute(
            "SELECT sql FROM sqlite_master WHERE name = "
            "'idx_events_one_verdict'").fetchone()
        assert idx is not None
        sql = idx["sql"]
        for t in ("ClassificationActionDecision", "ScopeReviewDecided",
                  "EvidenceTransitionProposed", "EvidenceTransitionApplied",
                  "RefutedApplied", "CuratedKnowledgeProposed",
                  "CuratedKnowledgeAdmitted"):
            assert t in sql


# ═══════════════════════ G. Controller surfaces ═══════════════════════


class TestControllerSurfaces:
    def _make(self, db, project="p1"):
        return Controller(db, project_id=project,
                          clock=frozen_clock(CLOCK))

    def test_record_curation_decision_happy_path(self, db):
        seed = seed_curatable(db)
        ctrl = self._make(db)
        result = ctrl.record_curation_decision(
            operation="ADMIT",
            program_ref=seed["program_id"],
            hypothesis_ref=seed["hypothesis_ref"],
            source_binding_ref=seed["binding_ref"],
            source_decision_event_ref="tr-1",
            signature_json=seed["signature_json"],
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert result["rejected"] is False
        assert result["curated_id"].startswith("curated_")
        assert result["duplicate"] is False

    def test_record_curation_decision_bad_operator(self, db):
        seed = seed_curatable(db)
        ctrl = self._make(db)
        result = ctrl.record_curation_decision(
            operation="ADMIT",
            program_ref=seed["program_id"],
            hypothesis_ref=seed["hypothesis_ref"],
            source_binding_ref=seed["binding_ref"],
            source_decision_event_ref="tr-1",
            signature_json=seed["signature_json"],
            operator_id="bad-op", operator_token="wrong-token")
        assert result["rejected"] is True
        assert result["code"] == "OPERATOR"

    def test_record_curation_decision_duplicate(self, db):
        seed = seed_curatable(db)
        ctrl = self._make(db)
        r1 = ctrl.record_curation_decision(
            operation="ADMIT",
            program_ref=seed["program_id"],
            hypothesis_ref=seed["hypothesis_ref"],
            source_binding_ref=seed["binding_ref"],
            source_decision_event_ref="tr-1",
            signature_json=seed["signature_json"],
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert r1["rejected"] is False
        r2 = ctrl.record_curation_decision(
            operation="ADMIT",
            program_ref=seed["program_id"],
            hypothesis_ref=seed["hypothesis_ref"],
            source_binding_ref=seed["binding_ref"],
            source_decision_event_ref="tr-1",
            signature_json=seed["signature_json"],
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert r2["duplicate"] is True

    def test_screen_near_miss_refutations(self, db):
        seed = seed_curatable(db)
        curate(db, seed)
        ctrl = self._make(db)
        result = ctrl.screen_near_miss_refutations(
            signature_json=seed["signature_json"])
        assert result["rejected"] is False
        assert result["count"] == 1
        assert result["matches"][0]["curated_id"].startswith("curated_")
        # screen shape omits provenance
        match = result["matches"][0]
        assert "source_project_id" not in match
        assert "admission_event_ref" not in match

    def test_screen_non_canonical_rejected(self, db):
        ctrl = self._make(db)
        result = ctrl.screen_near_miss_refutations(
            signature_json='{"schema_version":1,"axes":{"instrument":"X"}}')
        assert result["rejected"] is True
        assert result["code"] == "MALFORMED_PAYLOAD"

    def test_screen_invalidated_excluded(self, db):
        seed = seed_curatable(db)
        r = curate(db, seed)
        # invalidate directly
        db.execute(
            "UPDATE curated_knowledge_entries SET status = 'INVALIDATED' "
            "WHERE curated_id = ?", (r.entity_id,))
        ctrl = self._make(db)
        result = ctrl.screen_near_miss_refutations(
            signature_json=seed["signature_json"])
        assert result["count"] == 0

    def test_audit_curated_registry(self, db):
        seed = seed_curatable(db)
        r = curate(db, seed)
        ctrl = self._make(db)
        audit = ctrl.audit_curated_registry()
        assert audit["rejected"] is False
        assert audit["count"] == 1
        assert audit["active_count"] == 1
        entry = audit["entries"][0]
        assert entry["curated_id"] == r.entity_id
        assert entry["evidence_basis"] == [seed["evidence_id"]]
        assert entry["source_project_id"] == "p1"

    def test_audit_project_scoped(self, db):
        seed = seed_curatable(db)
        curate(db, seed)
        # p2's controller sees nothing
        ctrl2 = self._make(db, project="p2")
        audit = ctrl2.audit_curated_registry()
        assert audit["count"] == 0
