"""C1 — ``slot_ref`` design-concept identity: Step 3 acceptance fixtures.

Implements the C1 design gate's acceptance criteria (AC-1..AC-8) and the
ratified Option A schema-version contract
(``hermes_c1_step3_schema_version_spec_conflict.md``, operator ratification
2026-08-21): a supported program-schema-version set ``{"1", "2"}`` with
``"2"`` current/default, v1 identity and validity preserved, unsupported
versions rejected consistently at both the validation and persistence
boundaries.

AC-1 (Delta=0) is THE gate. Its golden hashes were captured from the LIVE
pre-C1 compiler (``PROGRAM_SCHEMA_VERSION == "1"``, no ``slot_ref``) by
``scripts/_capture_prec1_golden.py`` immediately before any Step 3
production change, and are hardcoded here with that provenance. If the
canonical-content contract ever drifts, these fixtures fail loudly — that
is the point.
"""
import json

import pytest

from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect, get_schema_version
from hermes.persistence.migrations import SUPPORTED_VERSION, migrate_to_latest
from hermes.persistence.repositories import (
    EventRepository,
    ProjectRepository,
    ResearchProgramError,
    ResearchProgramIntegrityError,
    ResearchProgramRepository,
)
from hermes.research.gateway import (
    MALFORMED_PAYLOAD,
    GatewayRejection,
    apply_intent,
)
from hermes.research.programs import (
    PROGRAM_SCHEMA_VERSION,
    SUPPORTED_PROGRAM_SCHEMA_VERSIONS,
    CompilationResult,
    CompilationStatus,
    HypothesisSpec,
    LadderTarget,
    ResearchProgramDraft,
    canonical_content_dict,
    compile_from_payload,
    compile_research_program,
    content_hash_of,
)

# ── AC-1 golden hashes (pre-C1 compiler, captured 2026-08-21) ──
# base_confirmatory: the schema-valid confirmatory draft below, compiled with
#   PROGRAM_SCHEMA_VERSION == "1" and no slot_ref anywhere.
GOLDEN_BASE_CONTENT = (
    "5d4a7f3f72e96d4dc6779541367755df4a209fbfd8d189b66d30ad8aea660b96")
GOLDEN_BASE_INPUT = (
    "a36b4c46a2eb1e2573f83dbb119f62502826de70dbc841648294cf94cd6c397f")
GOLDEN_BASE_ID = "rp_5d4a7f3f72e96d4dc6779541"
# minimal_speculative: a single SPECULATIVE hypothesis, schema_version "1".
GOLDEN_MIN_CONTENT = (
    "3d6de28cadd37c0e37e086c01ce061a9c5323e3c891076e7d516d42bf8283255")
GOLDEN_MIN_INPUT = (
    "73bc433508bf5baa09df0e49997615ef971872721dedf723134f74b704fee86a")
GOLDEN_MIN_ID = "rp_3d6de28cadd37c0e37e086c0"


def base_payload(**overrides) -> dict:
    """A schema-valid confirmatory draft: H1 (SUPPORTED) vs rival H0 (ACTIVE).

    Carries ``schema_version="1"`` explicitly — the pre-C1 shape. This is the
    exact payload the AC-1 golden hashes were derived from.
    """
    payload = {
        "scope_ref": "brief-1",
        "epistemic_objective": "Establish whether momentum predicts XAUUSD returns",
        "hypotheses": [
            {"ref": "H1", "ladder_target": "SUPPORTED",
             "falsification_condition": "returns do not follow momentum",
             "rival_of": None, "rival_status": None},
            {"ref": "H0", "ladder_target": "SPECULATIVE",
             "falsification_condition": "null hypothesis",
             "rival_of": "H1", "rival_status": "ACTIVE"},
        ],
        "predictions": [
            {"ref": "P1", "claim_ref": "H1", "observable": "20d_returns",
             "direction": "FOR", "condition": "trend_up"},
            {"ref": "P0", "claim_ref": "H0", "observable": "20d_returns",
             "direction": "NEUTRAL", "condition": "trend_up"},
        ],
        "discrimination_requirements": [
            {"ref": "D1", "hypothesis_a": "H1", "hypothesis_b": "H0",
             "observable": "20d_returns",
             "expected_difference": "H1 positive, H0 zero",
             "required_condition": "trend_up",
             "measurement_method_ref": "method-1"},
        ],
        "methodology_constraints": ["icss-v1"],
        "task_graph_template_ref": None,
        "compiler_version": "1.0.0",
        "policy_version": "rp-2026.1",
        "schema_version": "1",
        "supersedes_ref": None,
    }
    payload.update(overrides)
    return payload


def compile_payload(payload, project_id="p1", **ctx):
    return compile_from_payload(
        payload, project_id=project_id,
        scope_content_hash=ctx.get("scope_content_hash", "briefhash1"),
        superseded_program_ids=ctx.get("superseded_program_ids", frozenset()),
        slot_vocabulary=ctx.get("slot_vocabulary", frozenset()),
    )


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    conn.execute(
        """INSERT INTO scope_briefs
           (brief_id, project_id, version, content_hash, supersedes_id,
            scope_text_json, rationale, created_at, frozen_at)
           VALUES (?, ?, 1, ?, NULL, ?, NULL, ?, ?)""",
        ("brief-1", "p1", "briefhash1", json.dumps({"scope": "x"}),
         "2026-01-01T00:00:00.000000+00:00",
         "2026-01-01T00:00:00.000000+00:00"),
    )
    yield conn
    conn.close()


@pytest.fixture
def program_repo(db):
    return ResearchProgramRepository(db)


def proposal_intent(payload=None, project_id="p1"):
    return Intent(
        kind=IntentKind.PROPOSE_RESEARCH_PROGRAM,
        proposed_by="DIRECTOR",
        project_id=project_id,
        payload=payload if payload is not None else base_payload(),
        justification="c1 proposal via gateway",
    )


def insert_program_row(db, program_id, *, version, hypotheses,
                       project_id="p1"):
    """Insert an immutable research_programs row directly (ordinary shape)."""
    db.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, ?, ?, NULL, 'brief-1', 'objective', 'c1', 'p1',
                   '1', 'ih', ?, '[]', '[]', '[]', '[]', '[]', NULL,
                   'director', NULL, ?)""",
        (program_id, project_id, version, f"ch-{program_id}",
         json.dumps(list(hypotheses)),
         "2026-01-01T00:00:00.000000+00:00"),
    )


def hyp(ref, slot_ref=None, ladder="SUPPORTED"):
    d = {"ref": ref, "ladder_target": ladder,
         "falsification_condition": "fc", "rival_of": None,
         "rival_status": None}
    if slot_ref is not None:
        d["slot_ref"] = slot_ref
    return d


# ── Ratified Option A: the schema-version contract ──

class TestSchemaVersionContract:
    def test_supported_set_is_exactly_1_and_2(self):
        assert frozenset({"1", "2"}) == SUPPORTED_PROGRAM_SCHEMA_VERSIONS

    def test_current_default_version_is_2(self):
        assert PROGRAM_SCHEMA_VERSION == "2"
        # A draft built without an explicit schema_version defaults to "2".
        draft = ResearchProgramDraft(
            scope_ref="brief-1", epistemic_objective="o",
            hypotheses=(HypothesisSpec(
                ref="H1", ladder_target=LadderTarget.SPECULATIVE,
                falsification_condition="f"),),
            compiler_version="1.0.0", policy_version="rp",
        )
        assert draft.schema_version == "2"

    def test_payload_omitting_schema_version_defaults_to_2(self):
        p = base_payload()
        del p["schema_version"]
        r = compile_payload(p)
        assert r.status == CompilationStatus.COMPILED, r.errors
        assert r.program.schema_version == "2"

    @pytest.mark.parametrize("version", ["1", "2"])
    def test_supported_versions_compile(self, version):
        r = compile_payload(base_payload(schema_version=version))
        assert r.status == CompilationStatus.COMPILED, r.errors
        assert r.program.schema_version == version

    @pytest.mark.parametrize("version", ["3", "0", "999", ""])
    def test_unsupported_versions_rejected_at_validation(self, version):
        r = compile_payload(base_payload(schema_version=version))
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "SCHEMA_VERSION_MISMATCH" for e in r.errors)

    def test_v1_program_persists_at_write_path(self, db, program_repo):
        """v1 validity preserved at the persistence boundary (ratified)."""
        result = compile_payload(base_payload(schema_version="1"))
        assert result.program.schema_version == "1"
        row = program_repo.record("p1", result)
        assert row["schema_version"] == "1"
        assert row["content_hash"] == GOLDEN_BASE_CONTENT

    def test_unsupported_version_rejected_at_write_path(self, db, program_repo):
        """The write path rejects an unsupported version exactly as the
        validator does — the two boundaries agree (EC-V6-15, ratified)."""
        from dataclasses import replace

        from hermes.research.programs import input_hash_of, program_id_of
        result = compile_payload(base_payload(schema_version="1"))
        forged = replace(result.program, schema_version="999")
        forged = replace(
            forged,
            content_hash=content_hash_of(forged),
            input_hash=input_hash_of(forged),
            program_id=program_id_of(content_hash_of(forged)),
        )
        with pytest.raises(ResearchProgramIntegrityError):
            program_repo.record(
                "p1", CompilationResult(CompilationStatus.COMPILED, (), forged))
        assert program_repo.list_for_project("p1") == []


# ── AC-1 — identity stability (Delta=0 for the existing corpus) ──

class TestAC1DeltaZero:
    def test_ac1_base_confirmatory_hash_unchanged(self):
        """The pre-C1 confirmatory program recompiles to the IDENTICAL
        content_hash / input_hash / program_id under the post-C1 compiler."""
        r = compile_payload(base_payload())
        assert r.status == CompilationStatus.COMPILED, r.errors
        assert r.program.content_hash == GOLDEN_BASE_CONTENT
        assert r.program.input_hash == GOLDEN_BASE_INPUT
        assert r.program.program_id == GOLDEN_BASE_ID

    def test_ac1_minimal_speculative_hash_unchanged(self):
        draft = ResearchProgramDraft(
            scope_ref="brief-1", epistemic_objective="o",
            hypotheses=(HypothesisSpec(
                ref="H1", ladder_target=LadderTarget.SPECULATIVE,
                falsification_condition="f"),),
            compiler_version="1.0.0", policy_version="rp",
            schema_version="1",
        )
        r = compile_research_program(
            draft, project_id="p1", scope_content_hash="bh")
        assert r.status == CompilationStatus.COMPILED, r.errors
        assert r.program.content_hash == GOLDEN_MIN_CONTENT
        assert r.program.input_hash == GOLDEN_MIN_INPUT
        assert r.program.program_id == GOLDEN_MIN_ID

    def test_ac1_no_slot_ref_key_in_canonical_dict(self):
        """The non-None-only rule: a slot-less hypothesis emits NO slot_ref
        key (a naive None-emission would rehash the corpus)."""
        r = compile_payload(base_payload())
        for h in canonical_content_dict(r.program)["hypotheses"]:
            assert "slot_ref" not in h

    def test_ac1_slotless_admission_event_shape_unchanged(self, db):
        """A slot-less admission event payload is byte-identical to the
        pre-C1 shape (no new_slot_declarations key)."""
        apply_intent(db, proposal_intent())
        events = [e for e in EventRepository(db).list_for_project("p1")
                  if e["event_type"] == "ResearchProgramCompiled"]
        assert len(events) == 1
        payload = json.loads(events[0]["payload_json"])
        assert set(payload) == {
            "program_id", "content_hash", "version", "supersedes_ref",
            "scope_ref"}


# ── AC-2 — slot participation in identity ──

class TestAC2SlotParticipation:
    def _slotted(self, slot_ref):
        p = base_payload()
        p["hypotheses"][0]["slot_ref"] = slot_ref
        p["new_slot_declarations"] = [
            {"slot_ref": slot_ref, "rationale": "abstract function"}]
        return p

    def test_slot_change_changes_program_id(self):
        with_slot = compile_payload(self._slotted("slot:generate_upward_force"))
        without = compile_payload(base_payload())
        assert with_slot.status == CompilationStatus.COMPILED
        assert without.status == CompilationStatus.COMPILED
        assert with_slot.program.program_id != without.program.program_id
        assert with_slot.program.content_hash != without.program.content_hash

    def test_same_slot_same_program_id(self):
        r1 = compile_payload(self._slotted("slot:generate_upward_force"))
        r2 = compile_payload(self._slotted("slot:generate_upward_force"))
        assert r1.program.program_id == r2.program.program_id
        assert r1.program.content_hash == r2.program.content_hash

    def test_different_slot_different_program_id(self):
        r1 = compile_payload(self._slotted("slot:generate_upward_force"))
        r2 = compile_payload(self._slotted("slot:reduce_drag"))
        assert r1.program.program_id != r2.program.program_id


# ── AC-3 — closed vocabulary ──

class TestAC3ClosedVocabulary:
    def test_vocabulary_slot_admitted_without_declaration(self):
        p = base_payload()
        p["hypotheses"][0]["slot_ref"] = "slot:existing"
        r = compile_payload(p, slot_vocabulary=frozenset({"slot:existing"}))
        assert r.status == CompilationStatus.COMPILED, r.errors

    def test_undeclared_slot_refused(self):
        p = base_payload()
        p["hypotheses"][0]["slot_ref"] = "slot:not_in_vocab"
        r = compile_payload(p, slot_vocabulary=frozenset({"slot:existing"}))
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "E6_SLOT_UNDECLARED" for e in r.errors)

    def test_validly_declared_new_slot_admitted(self):
        p = base_payload()
        p["hypotheses"][0]["slot_ref"] = "slot:brand_new"
        p["new_slot_declarations"] = [
            {"slot_ref": "slot:brand_new", "rationale": "new function"}]
        r = compile_payload(p, slot_vocabulary=frozenset({"slot:existing"}))
        assert r.status == CompilationStatus.COMPILED, r.errors

    def test_redeclaring_existing_slot_refused(self):
        p = base_payload()
        p["hypotheses"][0]["slot_ref"] = "slot:existing"
        p["new_slot_declarations"] = [
            {"slot_ref": "slot:existing", "rationale": "already there"}]
        r = compile_payload(p, slot_vocabulary=frozenset({"slot:existing"}))
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "E6_SLOT_ALREADY_DECLARED" for e in r.errors)

    def test_orphan_declaration_refused(self):
        p = base_payload()
        p["new_slot_declarations"] = [
            {"slot_ref": "slot:orphan", "rationale": "never used"}]
        r = compile_payload(p)
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "E6_SLOT_DECLARATION_UNUSED" for e in r.errors)

    @pytest.mark.parametrize("bad", [
        "SLOT:upper",          # wrong-case prefix
        "slot:BadCase",        # non-snake_case label
        "slot:",               # empty label
        "slot:9lead",          # label must start with a letter
        "noslot:label",        # missing slot: prefix
        "slot:" + "a" * 130,   # over the 128-char cap
    ])
    def test_malformed_slot_refused(self, bad):
        p = base_payload()
        p["hypotheses"][0]["slot_ref"] = bad
        r = compile_payload(p)
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "E6_SLOT_MALFORMED" for e in r.errors)

    def test_empty_rationale_refused(self):
        p = base_payload()
        p["hypotheses"][0]["slot_ref"] = "slot:needs_reason"
        p["new_slot_declarations"] = [
            {"slot_ref": "slot:needs_reason", "rationale": "   "}]
        r = compile_payload(p)
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "E6_SLOT_MALFORMED" for e in r.errors)


# ── AC-4 — vocabulary is append-only and replay-stable ──

class TestAC4AppendOnlyReplayStable:
    def test_vocabulary_pure_function_of_rows_order_independent(self, db):
        repo = ResearchProgramRepository(db)
        # Order A: v1 carries slot:a, v2 carries slot:b.
        insert_program_row(db, "rp-a1", version=1,
                           hypotheses=[hyp("H1", slot_ref="slot:a")])
        insert_program_row(db, "rp-a2", version=2,
                           hypotheses=[hyp("H1", slot_ref="slot:b")])
        vocab_a = repo.slot_vocabulary("p1")

        # Order B (fresh project): same two rows, reversed admission order.
        ProjectRepository(db).create("p2", "Test2")
        insert_program_row(db, "rp-b2", version=2,
                           hypotheses=[hyp("H1", slot_ref="slot:b")],
                           project_id="p2")
        insert_program_row(db, "rp-b1", version=1,
                           hypotheses=[hyp("H1", slot_ref="slot:a")],
                           project_id="p2")
        vocab_b = repo.slot_vocabulary("p2")

        assert vocab_a == vocab_b == frozenset({"slot:a", "slot:b"})

    def test_superseded_slot_remains_in_vocabulary(self, db):
        """A slot from an old (superseded) version is never retired."""
        repo = ResearchProgramRepository(db)
        insert_program_row(db, "rp-old", version=1,
                           hypotheses=[hyp("H1", slot_ref="slot:abandoned")])
        insert_program_row(db, "rp-new", version=2,
                           hypotheses=[hyp("H1", slot_ref="slot:current")])
        vocab = repo.slot_vocabulary("p1")
        assert "slot:abandoned" in vocab
        assert "slot:current" in vocab

    def test_pre_c1_rows_tolerated(self, db):
        """A row whose hypotheses carry NO slot_ref key contributes nothing
        (dual-consumer deserializer tolerance)."""
        repo = ResearchProgramRepository(db)
        insert_program_row(db, "rp-prec1", version=1,
                           hypotheses=[hyp("H1")])  # no slot_ref key
        assert repo.slot_vocabulary("p1") == frozenset()


# ── AC-5 — rationale provenance ──

class TestAC5RationaleProvenance:
    def _slotted_payload(self, rationale):
        p = base_payload()
        p["hypotheses"][0]["slot_ref"] = "slot:generate_upward_force"
        p["new_slot_declarations"] = [
            {"slot_ref": "slot:generate_upward_force",
             "rationale": rationale}]
        return p

    def test_rationale_in_event_not_in_content(self, db):
        apply_intent(db, proposal_intent(payload=self._slotted_payload(
            "Abstract function: produce upward force")))

        events = [e for e in EventRepository(db).list_for_project("p1")
                  if e["event_type"] == "ResearchProgramCompiled"]
        assert len(events) == 1
        event_payload = json.loads(events[0]["payload_json"])
        assert event_payload["new_slot_declarations"] == [
            {"slot_ref": "slot:generate_upward_force",
             "rationale": "Abstract function: produce upward force"}]

        # The rationale / declaration never enters the canonical content dict.
        r = compile_payload(self._slotted_payload(
            "Abstract function: produce upward force"))
        canonical = canonical_content_dict(r.program)
        assert "new_slot_declarations" not in canonical
        blob = json.dumps(canonical)
        assert "Abstract function: produce upward force" not in blob
        # The declaration never alters content_hash: same slotted hypothesis
        # with a DIFFERENT rationale text hashes identically.
        r2 = compile_payload(self._slotted_payload("totally different words"))
        assert r.program.content_hash == r2.program.content_hash


# ── AC-6 — no authority leak ──

class TestAC6NoAuthorityLeak:
    def test_no_new_intent_kind(self):
        """C1 introduces no new intent kind. (Step-5 update: the vocabulary
        gained exactly one member AFTER C1 closed — RETRACT_SOURCE, the
        ratified v6 §7/S5 cascade trigger authorized by the Step 4 decision
        gate §9.3. Step-7 update: CURATE_KNOWLEDGE, the ratified v6 §16.6
        curated-registry admission trigger authorized by the Step 7E
        charter — an internal-only, never-LLM-proposable kind. CHG-1
        update: RECORD_CONTRADICTION, the ratified contradiction-lifecycle
        recording trigger authorized by the CHG-1 ratification gate — an
        internal-only, never-LLM-proposable kind (CONTRADICTION_RESOLUTION
        was already declared; CHG-1 wires it as internal-only). P6
        update: RECORD_CLASSIFICATION, the ratified operator-asserted
        failure-classification admission trigger — an internal-only,
        never-LLM-proposable kind (judgment authorship is the
        operator's; the substrate re-validates everything). ADR-041 B3
        update: EMIT_PARALLEL_REGIME_PROGRAM, the ratified
        controller-originated parallel-regime-test emission trigger —
        an internal-only, never-LLM-proposable kind. The deterministic
        controller consumes APPROVED PROPOSE_PARALLEL_REGIME_TEST
        proposals and emits this intent to have the gateway clone the
        parent program substance and record a child. All are
        post-C1 authorities, not C1 authority leaks: C1 itself still adds
        nothing, and the set below pins the post-ADR-041 canonical
        vocabulary so any FUTURE unratified kind still fails.)"""
        expected = {
            "INSERT_TASK", "BRANCH", "ABANDON", "EVIDENCE_TRANSITION",
            "REQUEST_HUMAN", "REQUEST_REPLICATION",
            "REQUEST_ADDITIONAL_EXPERIMENT", "PROPOSE_GATE_OVERRIDE",
            "CONTRADICTION_RESOLUTION", "PROPOSE_RESEARCH_PROGRAM",
            "PROPOSE_CLASSIFICATION_ACTION", "RESOLVE_CLASSIFICATION_PROPOSAL",
            "RECORD_SCOPE_REVIEW_DECISION",
            "RETRACT_SOURCE",  # v6 §7/S5 (Step 4 gate §9.3 authorization)
            "CURATE_KNOWLEDGE",  # v6 §16.6 (Step 7E charter authorization)
            "RECORD_CONTRADICTION",  # CHG-1 contradiction lifecycle
            "RECORD_CLASSIFICATION",  # P6 operator-asserted classification
            "EMIT_PARALLEL_REGIME_PROGRAM",  # ADR-041 B3 internal-only emission
            "ADMIT_TASK",
        }
        assert {k.value for k in IntentKind} == expected

    def test_no_migration(self, db):
        """C1 adds no migration: the DB schema version is unchanged."""
        assert get_schema_version(db) == SUPPORTED_VERSION == 19

    def test_q02_dimension_set_unchanged(self):
        """slot_ref adds no Q-02 dimension."""
        from hermes.research.evaluation import DIMENSION_ORDER
        assert DIMENSION_ORDER == (
            "evidence_gap_closure", "contradiction_reduction",
            "rival_discrimination", "replication_value", "frontier_value",
            "coverage",
        )

    def test_slot_ref_not_an_eligibility_or_ordering_input(self):
        """slot_ref is identity metadata: it never appears in the canonical
        content dict's obligation/gate structures."""
        p = base_payload()
        p["hypotheses"][0]["slot_ref"] = "slot:x"
        p["new_slot_declarations"] = [{"slot_ref": "slot:x", "rationale": "r"}]
        r = compile_payload(p)
        assert r.status == CompilationStatus.COMPILED
        # Obligations are derived from ladder_target alone — slot-blind.
        slotted = compile_payload(p)
        unslotted = compile_payload(base_payload())
        assert (slotted.program.evidence_requirements
                == unslotted.program.evidence_requirements)
        assert (slotted.program.gate_requirements
                == unslotted.program.gate_requirements)


# ── AC-7 — supersession-chain reachability + fail-closed ──

class TestAC7Reachability:
    def test_grandparent_slot_resolved(self, db):
        """E6's vocabulary spans the FULL supersession history (grandparent
        programs included), not just the chain head."""
        repo = ResearchProgramRepository(db)
        insert_program_row(db, "rp-grand", version=1,
                           hypotheses=[hyp("H1", slot_ref="slot:ancient")])
        insert_program_row(db, "rp-parent", version=2,
                           hypotheses=[hyp("H1", slot_ref="slot:middle")])
        vocab = repo.slot_vocabulary("p1")
        assert vocab == frozenset({"slot:ancient", "slot:middle"})

        # A new program may USE the grandparent slot without re-declaring it.
        p = base_payload()
        p["hypotheses"][0]["slot_ref"] = "slot:ancient"
        r = compile_payload(p, slot_vocabulary=vocab)
        assert r.status == CompilationStatus.COMPILED, r.errors

    def test_corrupt_row_fails_closed(self, db):
        """A corrupt hypothesis_json raises (refuses) rather than silently
        shrinking the vocabulary."""
        repo = ResearchProgramRepository(db)
        db.execute(
            """INSERT INTO research_programs
               (program_id, project_id, version, content_hash, supersedes_id,
                scope_ref, epistemic_objective, compiler_version,
                policy_version, schema_version, input_hash, hypothesis_json,
                prediction_json, discrimination_json, evidence_json, gate_json,
                methodology_json, task_graph_template_ref, produced_by, reason,
                created_at)
               VALUES ('rp-corrupt', 'p1', 1, 'ch-corrupt', NULL, 'brief-1',
                       'o', 'c1', 'p1', '1', 'ih', 'NOT-VALID-JSON', '[]',
                       '[]', '[]', '[]', '[]', NULL, 'director', NULL, ?)""",
            ("2026-01-01T00:00:00.000000+00:00",),
        )
        with pytest.raises(ResearchProgramError):
            repo.slot_vocabulary("p1")

    def test_gateway_refuses_on_corrupt_vocabulary(self, db):
        """End-to-end: a corrupt row makes the gateway reject the whole
        admission (reject, never crash)."""
        db.execute(
            """INSERT INTO research_programs
               (program_id, project_id, version, content_hash, supersedes_id,
                scope_ref, epistemic_objective, compiler_version,
                policy_version, schema_version, input_hash, hypothesis_json,
                prediction_json, discrimination_json, evidence_json, gate_json,
                methodology_json, task_graph_template_ref, produced_by, reason,
                created_at)
               VALUES ('rp-corrupt', 'p1', 1, 'ch-corrupt', NULL, 'brief-1',
                       'o', 'c1', 'p1', '1', 'ih', 'NOT-VALID-JSON', '[]',
                       '[]', '[]', '[]', '[]', NULL, 'director', NULL, ?)""",
            ("2026-01-01T00:00:00.000000+00:00",),
        )
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, proposal_intent())
        assert exc.value.code == MALFORMED_PAYLOAD


# ── AC-8 — rivals may share a slot ──

class TestAC8RivalsShareSlot:
    def test_two_active_rivals_same_slot_compile(self):
        """Two ACTIVE rivals carrying the SAME slot_ref with structurally
        distinct predictions (E5 satisfied) compile; E5 is unaffected by
        slot equality."""
        p = base_payload()
        # H1 (primary) and H0 (ACTIVE rival) both fill the same slot.
        p["hypotheses"][0]["slot_ref"] = "slot:explain_momentum"
        p["hypotheses"][1]["slot_ref"] = "slot:explain_momentum"
        p["new_slot_declarations"] = [
            {"slot_ref": "slot:explain_momentum",
             "rationale": "the mechanism that explains momentum returns"}]
        r = compile_payload(p)
        assert r.status == CompilationStatus.COMPILED, r.errors
        # Both hypotheses carry the slot.
        slots = {h.slot_ref for h in r.program.hypotheses}
        assert slots == {"slot:explain_momentum"}


# ── Adversarial closure gate: write-path E6 re-validation (vocabulary poisoning) ──

class TestWritePathSlotDiscipline:
    """The repository is the integrity boundary — a forged COMPILED object
    that bypasses the gateway must not pollute the append-only vocabulary.

    Prior to the closure-gate fix, ``ResearchProgramRepository.record``
    re-validated identity (EC-V6-11..16) and epistemic checks (AR-01) but
    not E6 slot discipline. A valid-format but undeclared slot, a malformed
    slot, or an orphan declaration could be persisted via a direct
    ``record`` bypass and would permanently poison the vocabulary.
    """

    def _forged(self, db, slot_ref, extra_hypotheses=None):
        from dataclasses import replace

        from hermes.research.programs import (
            HypothesisSpec,
            LadderTarget,
            RivalStatus,
            content_hash_of,
            input_hash_of,
            program_id_of,
        )

        base = base_payload()
        r = compile_payload(base)
        hyp = HypothesisSpec(
            ref="H1", ladder_target=LadderTarget.SUPPORTED,
            falsification_condition="fc", slot_ref=slot_ref)
        rival = HypothesisSpec(
            ref="H0", ladder_target=LadderTarget.SPECULATIVE,
            falsification_condition="null",
            rival_of="H1", rival_status=RivalStatus.ACTIVE)
        hyps = (hyp, rival) if extra_hypotheses is None else extra_hypotheses
        forged = replace(r.program, hypotheses=hyps)
        forged = replace(
            forged,
            content_hash=content_hash_of(forged),
            input_hash=input_hash_of(forged),
            program_id=program_id_of(content_hash_of(forged)),
        )
        return forged

    def test_write_path_rejects_undeclared_slot(self, db, program_repo):
        forged = self._forged(db, "slot:evil_undeclared")
        with pytest.raises(ResearchProgramIntegrityError):
            program_repo.record(
                "p1", CompilationResult(CompilationStatus.COMPILED, (), forged))
        assert program_repo.list_for_project("p1") == []

    def test_write_path_rejects_malformed_slot(self, db, program_repo):
        forged = self._forged(db, "slot:BadCase")
        with pytest.raises(ResearchProgramIntegrityError):
            program_repo.record(
                "p1", CompilationResult(CompilationStatus.COMPILED, (), forged))
        assert program_repo.list_for_project("p1") == []

    def test_write_path_rejects_overlong_slot(self, db, program_repo):
        forged = self._forged(db, "slot:" + "a" * 130)
        with pytest.raises(ResearchProgramIntegrityError):
            program_repo.record(
                "p1", CompilationResult(CompilationStatus.COMPILED, (), forged))
        assert program_repo.list_for_project("p1") == []

    def test_write_path_rejects_orphan_declaration(self, db, program_repo):
        base = compile_payload(base_payload())
        assert base.status == CompilationStatus.COMPILED
        with pytest.raises(ResearchProgramIntegrityError):
            program_repo.record(
                "p1", base,
                new_slot_declarations=[{"slot_ref": "slot:orphan", "rationale": "r"}])
        assert program_repo.list_for_project("p1") == []

    def test_write_path_rejects_redeclared_slot(self, db, program_repo):
        # Legitimately admit slot:legit via the gateway, then try to re-declare
        # it via a direct record bypass with a different program content.
        p = base_payload()
        p["hypotheses"][0]["slot_ref"] = "slot:legit"
        p["new_slot_declarations"] = [
            {"slot_ref": "slot:legit", "rationale": "initial"}]
        apply_intent(db, proposal_intent(payload=p))
        assert program_repo.slot_vocabulary("p1") == frozenset({"slot:legit"})
        # Forge a second program that also declares slot:legit
        from dataclasses import replace

        from hermes.research.programs import (
            HypothesisSpec,
            LadderTarget,
            RivalStatus,
            content_hash_of,
            input_hash_of,
            program_id_of,
        )
        clean = compile_payload(base_payload())
        hyp = HypothesisSpec(
            ref="H1", ladder_target=LadderTarget.SUPPORTED,
            falsification_condition="fc", slot_ref="slot:legit")
        rival = HypothesisSpec(
            ref="H0", ladder_target=LadderTarget.SPECULATIVE,
            falsification_condition="null",
            rival_of="H1", rival_status=RivalStatus.ACTIVE)
        forged = replace(
            clean.program,
            epistemic_objective="different objective for redeclaration",
            hypotheses=(hyp, rival),
        )
        forged = replace(
            forged,
            content_hash=content_hash_of(forged),
            input_hash=input_hash_of(forged),
            program_id=program_id_of(content_hash_of(forged)),
        )
        with pytest.raises(ResearchProgramIntegrityError):
            program_repo.record(
                "p1", CompilationResult(CompilationStatus.COMPILED, (), forged),
                new_slot_declarations=[{"slot_ref": "slot:legit", "rationale": "redeclaration"}])
        # Original row still the only one
        assert len(program_repo.list_for_project("p1")) == 1

    def test_write_path_accepts_valid_new_slot(self, db, program_repo):
        forged = self._forged(db, "slot:brand_new")
        row = program_repo.record(
            "p1", CompilationResult(CompilationStatus.COMPILED, (), forged),
            new_slot_declarations=[{"slot_ref": "slot:brand_new", "rationale": "valid reason"}])
        assert row["program_id"] == forged.program_id
        assert program_repo.slot_vocabulary("p1") == frozenset({"slot:brand_new"})

    def test_write_path_accepts_reuse_of_existing_vocab_without_declaration(self, db, program_repo):
        # Gateway path for the initial slot
        p = base_payload()
        p["hypotheses"][0]["slot_ref"] = "slot:reused"
        p["new_slot_declarations"] = [
            {"slot_ref": "slot:reused", "rationale": "r"}]
        apply_intent(db, proposal_intent(payload=p))
        head = program_repo.current("p1")
        # Direct record reuse without declaration, with supersession
        from dataclasses import replace

        from hermes.research.programs import (
            HypothesisSpec,
            LadderTarget,
            RivalStatus,
            content_hash_of,
            input_hash_of,
            program_id_of,
        )
        # Build a superseding program that reuses the slot without declaration
        hyp = HypothesisSpec(
            ref="H1", ladder_target=LadderTarget.SUPPORTED,
            falsification_condition="fc", slot_ref="slot:reused")
        rival = HypothesisSpec(
            ref="H0", ladder_target=LadderTarget.SPECULATIVE,
            falsification_condition="null",
            rival_of="H1", rival_status=RivalStatus.ACTIVE)
        clean = compile_payload(base_payload())
        forged = replace(
            clean.program,
            epistemic_objective="superseding reuse",
            hypotheses=(hyp, rival),
            supersedes_ref=head["program_id"],
        )
        forged = replace(
            forged,
            content_hash=content_hash_of(forged),
            input_hash=input_hash_of(forged),
            program_id=program_id_of(content_hash_of(forged)),
        )
        row = program_repo.record(
            "p1", CompilationResult(CompilationStatus.COMPILED, (), forged),
            new_slot_declarations=[])
        assert row["supersedes_id"] == head["program_id"]
