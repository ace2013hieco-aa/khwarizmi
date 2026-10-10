"""Tests for the approved ResearchProgram architecture (IDR-018, Part 2 P2 slice).

Covers the acceptance criteria of the Part 2 package (AC-01..04, 06..09, 11),
all five compilation verdicts, the repository write-path contract (validate-
before-write, idempotency, immutability, supersession), the migration, the
intent-kind contract, and the Part 3 adversarial cases A-L scoped to P2.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from hermes.core import frozen_clock
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
from hermes.research import regimes
from hermes.research.programs import (
    CompilationError,
    CompilationResult,
    CompilationStatus,
    LadderTarget,
    RivalStatus,
    compile_from_payload,
    compile_research_program,
    program_to_dict,
    summarize,
)

# ── helpers ──

def base_payload(**overrides) -> dict:
    """A schema-valid confirmatory draft: H1 (SUPPORTED) vs rival H0 (ACTIVE)."""
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
             "required_condition": "trend_up", "measurement_method_ref": "method-1"},
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
    conn.execute(
        """INSERT INTO scope_briefs
           (brief_id, project_id, version, content_hash, supersedes_id,
            scope_text_json, rationale, created_at, frozen_at)
           VALUES (?, ?, 2, ?, 'brief-1', ?, NULL, ?, ?)""",
        ("brief-2", "p1", "briefhash2", json.dumps({"scope": "y"}),
         "2026-01-02T00:00:00.000000+00:00",
         "2026-01-02T00:00:00.000000+00:00"),
    )
    yield conn
    conn.close()


@pytest.fixture
def repos(db):
    return (
        ProjectRepository(db),
        ResearchProgramRepository(db),
        EventRepository(db),
    )


def compile_payload(payload: dict, project_id: str = "p1", **ctx) -> object:
    """Compile a payload with governance context (scope hash default brief-1)."""
    return compile_from_payload(
        payload,
        project_id=project_id,
        scope_content_hash=ctx.get("scope_content_hash", "briefhash1"),
        superseded_program_ids=ctx.get("superseded_program_ids", frozenset()),
        known_program_ids=ctx.get("known_program_ids", frozenset()),
        known_hypothesis_refs=ctx.get("known_hypothesis_refs", frozenset()),
    )


# ── AC-01 / AC-08 / AC-09: determinism and identity ──

class TestDeterminism:
    def test_ac01_same_inputs_same_identity(self):
        r1 = compile_payload(base_payload())
        r2 = compile_payload(base_payload())
        assert r1.status == CompilationStatus.COMPILED
        assert r2.status == CompilationStatus.COMPILED
        assert r1.program.content_hash == r2.program.content_hash
        assert r1.program.program_id == r2.program.program_id
        assert r1.program.input_hash == r2.program.input_hash
        # Identical structure: derived obligations and gates
        assert r1.program.evidence_requirements == r2.program.evidence_requirements
        assert r1.program.gate_requirements == r2.program.gate_requirements

    # ── ADV-06: identity equals an INDEPENDENTLY constructed preimage ──
    # (test-local canonicalizer + plain hashlib — never the production helper
    # re-run on itself; a drift in the canonical contract would fail here).

    def _canonicalize(value):
        import json as _json

        if isinstance(value, dict):
            return {k: TestDeterminism._canonicalize(v)
                    for k, v in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            items = [TestDeterminism._canonicalize(v) for v in value]
            if items and all(isinstance(i, dict) for i in items):
                return sorted(
                    items,
                    key=lambda i: _json.dumps(
                        i, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False))
            if items and all(not isinstance(i, (dict, list, tuple)) for i in items):
                return sorted(items, key=str)
            return items
        return value

    def test_adv06_content_hash_independently_recomputed(self):
        import hashlib
        import json as _json

        r = compile_payload(base_payload())
        prog = r.program
        # The canonical content preimage: the program's own semantic fields
        # (program_to_dict minus the IDENTITY OUTPUTS — input_hash,
        # content_hash, supersedes_ref are never inputs to the content hash).
        preimage = program_to_dict(prog)
        for key in ("input_hash", "content_hash", "supersedes_ref",
                    "parent_program_id", "parent_hypothesis_ref",
                    "target_regime"):
            preimage.pop(key)
        serialized = _json.dumps(
            TestDeterminism._canonicalize(preimage), sort_keys=True,
            separators=(",", ":"), ensure_ascii=False)
        expected = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        assert prog.content_hash == expected

    def test_adv06_input_hash_independently_recomputed(self):
        import hashlib
        import json as _json

        r = compile_payload(base_payload())
        prog = r.program
        # The documented input-identity contract: SHA-256 over the
        # governance-relevant inputs with SORTED refs/constraints.
        preimage = {
            "scope_ref": prog.scope_ref,
            "scope_content_hash": prog.scope_content_hash,
            "hypothesis_refs": sorted(h.ref for h in prog.hypotheses),
            "prediction_refs": sorted(p.ref for p in prog.predictions),
            "discrimination_refs": sorted(
                d.ref for d in prog.discrimination_requirements),
            "constraints": sorted(prog.methodology_constraints),
            "compiler_version": prog.compiler_version,
            "policy_version": prog.policy_version,
            "schema_version": prog.schema_version,
            "supersedes_ref": prog.supersedes_ref,
        }
        # parallel-regime-test linkage: emitted ONLY when non-None, matching
        # input_hash_of (AC-1: None values would perturb the identity).
        if prog.parent_program_id is not None:
            preimage["parent_program_id"] = prog.parent_program_id
            preimage["parent_hypothesis_ref"] = prog.parent_hypothesis_ref
            preimage["target_regime"] = prog.target_regime
        serialized = _json.dumps(
            TestDeterminism._canonicalize(preimage), sort_keys=True,
            separators=(",", ":"), ensure_ascii=False)
        expected = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        assert prog.input_hash == expected

    def test_adv06_program_id_derived_from_content_hash(self):
        r = compile_payload(base_payload())
        assert r.program.program_id == "rp_" + r.program.content_hash[:24]

    def test_adversarial_d_same_semantics_different_ordering(self):
        """Same semantic input with different ordering → identical identity."""
        p1 = base_payload()
        p1_reordered = base_payload(
            predictions=list(reversed(p1["predictions"])),
            hypotheses=list(reversed(p1["hypotheses"])),
        )
        p2 = base_payload(methodology_constraints=["icss-v1", "extra"])
        p3 = base_payload(methodology_constraints=["extra", "icss-v1"])
        r1 = compile_payload(p1)
        r1r = compile_payload(p1_reordered)
        r2 = compile_payload(p2)
        r3 = compile_payload(p3)
        for r in (r1, r1r, r2, r3):
            assert r.status == CompilationStatus.COMPILED, r.errors
        assert r1.program.content_hash == r1r.program.content_hash
        assert r2.program.content_hash == r3.program.content_hash

    def test_ac08_changed_compiler_version_changes_identity(self):
        r1 = compile_payload(base_payload(compiler_version="1.0.0"))
        r2 = compile_payload(base_payload(compiler_version="1.1.0"))
        assert r1.program.program_id != r2.program.program_id
        assert r1.program.content_hash != r2.program.content_hash

    def test_ac09_changed_scope_content_hash_changes_input_hash(self):
        r1 = compile_payload(base_payload(), scope_content_hash="briefhash1")
        r2 = compile_payload(base_payload(), scope_content_hash="briefhash2")
        assert r1.program.input_hash != r2.program.input_hash

    def test_ac09_changed_scope_brief_requires_new_program(self):
        """A new frozen brief version (new scope_ref) ⇒ new program identity."""
        r1 = compile_payload(base_payload())
        r2 = compile_payload(base_payload(scope_ref="brief-2"),
                             scope_content_hash="briefhash2")
        assert r1.program.program_id != r2.program.program_id
        assert r1.program.scope_ref == "brief-1"
        assert r2.program.scope_ref == "brief-2"

    def test_parallel_regime_changed_target_regime_changes_identity(self):
        """B1 #6: two programs identical except for target_regime must produce
        DIFFERENT content_hash/program_id (proving the field feeds identity).
        Step 4 / S-R2: target_regime must be a registered versioned tag, so
        the identity-bearing pair shown here is registered-regime vs no
        regime (the all-None ordinary case); the distinct-registered-tag pair
        is the companion test below (restored by MERGE/conditions C2)."""
        parent = "rp_knownparent00000000000000000"
        hyp = "H1"
        r1 = compile_payload(base_payload(),
                             known_program_ids=frozenset({parent}),
                             known_hypothesis_refs=frozenset({hyp}))
        assert r1.status == CompilationStatus.COMPILED, r1.errors
        r2 = compile_payload(
            base_payload(
                parent_program_id=parent,
                parent_hypothesis_ref=hyp,
                target_regime="ICSS-v1:low-vol",
            ),
            known_program_ids=frozenset({parent}),
            known_hypothesis_refs=frozenset({hyp}),
        )
        assert r2.status == CompilationStatus.COMPILED, r2.errors
        # Registered regime present ⇒ different identity from ordinary.
        assert r1.program.content_hash != r2.program.content_hash
        assert r1.program.program_id != r2.program.program_id

    def test_parallel_regime_distinct_registered_tags_change_identity(
            self, monkeypatch):
        """MERGE/conditions C2: two DISTINCT registered target_regime tags must
        produce DIFFERENT content_hash/program_id — the identity-uniqueness
        property the S-R2 test edit had dropped.

        The shipped registry holds exactly ONE entry (IDR-044 D1), so no two
        distinct registered tags exist in production; the property is
        therefore exercised against a synthetic two-entry registry built from
        the public substrate. The widening is test-only and scoped:
        ``monkeypatch`` restores ``REGISTRY``, and the synthetic tag is
        asserted unregistered first, so this can never mask a production gap.
        """
        registered = {d.ref.tag for d in regimes.REGISTRY}
        assert "ICSS-v1:high-vol" not in registered, (
            "the synthetic companion tag must not already be registered")
        synthetic = regimes.RegimeDefinition(
            regime_id="high-vol",
            version="ICSS-v1",
            predicate=lambda snapshot: False,
            notes="synthetic companion entry (test-only; not a registry seed)")
        monkeypatch.setattr(
            regimes, "REGISTRY", regimes.REGISTRY | {synthetic})
        # The widening is real: the synthetic pair resolves as registered.
        parsed = regimes.parse_regime_ref("ICSS-v1:high-vol")
        assert regimes.resolve_regime(parsed).ref.tag == "ICSS-v1:high-vol"

        parent = "rp_knownparent00000000000000000"
        hyp = "H1"
        tags = ("ICSS-v1:low-vol", "ICSS-v1:high-vol")
        compiled = [
            compile_payload(
                base_payload(parent_program_id=parent,
                             parent_hypothesis_ref=hyp,
                             target_regime=tag),
                known_program_ids=frozenset({parent}),
                known_hypothesis_refs=frozenset({hyp}),
            )
            for tag in tags
        ]
        for r, tag in zip(compiled, tags):
            assert r.status == CompilationStatus.COMPILED, (tag, r.errors)
        first, second = compiled
        assert first.program.content_hash != second.program.content_hash
        assert first.program.program_id != second.program.program_id

    def test_parallel_regime_unregistered_versioned_tag_rejected(self):
        """Step 4 / S-R2 wiring (IDR-044): a well-formed versioned tag whose
        (version, id) pair is NOT registered is refused (UNREGISTERED_REGIME)
        — a known id under an unknown version is never silently accepted."""
        parent = "rp_knownparent00000000000000000"
        hyp = "H1"
        for tag in ("ICSS-v1:high-vol", "ICSS-v2:low-vol"):
            r = compile_payload(
                base_payload(parent_program_id=parent,
                             parent_hypothesis_ref=hyp,
                             target_regime=tag),
                known_program_ids=frozenset({parent}),
                known_hypothesis_refs=frozenset({hyp}),
            )
            assert r.status == CompilationStatus.INVALID, tag
            assert r.program is None
            assert [e.code for e in r.errors] == ["UNREGISTERED_REGIME"], tag

    def test_parallel_regime_bare_id_rejected(self):
        """Step 4 / S-R2 wiring (IDR-044): the bare/unversioned form is no
        longer admitted — UNVERSIONED_REGIME replaces the old free-string
        acceptance. (A single-colon tag like 'low:vol' is well-formed under
        the first-colon convention — version 'low', id 'vol' — and is
        refused as UNREGISTERED_REGIME instead; covered below.)

        MERGE/conditions C2: the arbitrary free-string form the pre-S-R2
        refusal tests used as filler ('regime-A') is asserted refused HERE,
        so those tests no longer depend on the regime value being invalid.
        """
        parent = "rp_knownparent00000000000000000"
        hyp = "H1"
        for tag in ("low-vol", "ICSS-v1:", "regime-A"):
            r = compile_payload(
                base_payload(parent_program_id=parent,
                             parent_hypothesis_ref=hyp,
                             target_regime=tag),
                known_program_ids=frozenset({parent}),
                known_hypothesis_refs=frozenset({hyp}),
            )
            assert r.status == CompilationStatus.INVALID, tag
            assert r.program is None
            assert [e.code for e in r.errors] == ["UNVERSIONED_REGIME"], tag

    def test_parallel_regime_ordinary_program_delta_zero(self):
        """B1 #7: a program with all three parallel-regime fields None must
        compile to the identical content_hash/program_id as a pre-regime
        program given identical other inputs (AC-1 Delta=0)."""
        r1 = compile_payload(base_payload())  # ordinary: all None
        r2 = compile_payload(base_payload())  # ordinary: all None
        assert r1.status == CompilationStatus.COMPILED
        assert r2.status == CompilationStatus.COMPILED
        # Identical ordinary programs must agree — the all-None case does
        # not perturb identity.
        assert r1.program.content_hash == r2.program.content_hash
        assert r1.program.program_id == r2.program.program_id
        assert r1.program.input_hash == r2.program.input_hash
        # The all-None fields must not corrupt the DB serialization.
        d = program_to_dict(r1.program)
        assert d["parent_program_id"] is None
        assert d["parent_hypothesis_ref"] is None
        assert d["target_regime"] is None

    def test_adversarial_g_changed_hypothesis_changes_program(self):
        changed = base_payload()
        changed["hypotheses"][0]["falsification_condition"] = "different condition"
        r1 = compile_payload(base_payload())
        r2 = compile_payload(changed)
        assert r1.program.content_hash != r2.program.content_hash


# ── AC-02 / AC-03 / AC-04: malformed, incomplete, contradictory ──

class TestValidationVerdicts:
    def test_ac02_malformed_proposal_fails_closed_invalid(self):
        r = compile_payload("not-a-dict")
        assert r.status == CompilationStatus.INVALID
        assert r.program is None
        assert r.errors and r.errors[0].code == "PAYLOAD_NOT_DICT"

        malformed = [
            base_payload(hypotheses=[]),            # no hypotheses
            base_payload(epistemic_objective=""),  # missing objective
            base_payload(scope_ref=""),            # missing scope
            base_payload(compiler_version=""),     # missing version
            base_payload(schema_version="3"),      # schema mismatch (C1: "1"
            # and "2" are the supported versions; "3" is unsupported)
        ]
        for payload in malformed:
            r = compile_payload(payload)
            assert r.status == CompilationStatus.INVALID, r.errors
            assert r.program is None

    def test_ac02_unknown_keys_fail_closed(self):
        """The schema is closed: evidence status / task state / graph fields
        have no home in a ResearchProgram (adversarial J, K)."""
        p = base_payload(status="SUPPORTED")          # promoting evidence
        r = compile_payload(p)
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "UNKNOWN_PAYLOAD_KEY" for e in r.errors)

        p = base_payload(graph_input={"claim": "x"})  # graph-derived input
        r = compile_payload(p)
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "UNKNOWN_PAYLOAD_KEY" for e in r.errors)

    def test_ac02_bad_enum_fails_closed(self):
        p = base_payload()
        p["hypotheses"][0]["ladder_target"] = "SORTED"
        r = compile_payload(p)
        assert r.status == CompilationStatus.INVALID
        assert r.program is None

    def test_ac02_unresolvable_refs_invalid(self):
        p = base_payload()
        p["predictions"][0]["claim_ref"] = "NOPE"
        r = compile_payload(p)
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "UNRESOLVABLE_CLAIM" for e in r.errors)

    def test_ac02_self_rival_invalid(self):
        p = base_payload()
        p["hypotheses"][0] = {
            "ref": "H1", "ladder_target": "SUPPORTED",
            "falsification_condition": "x", "rival_of": "H1",
            "rival_status": "ACTIVE"}
        r = compile_payload(p)
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "SELF_RIVAL" for e in r.errors)

    def test_ac03_incomplete_missing_predictions(self):
        """E1: a confirmatory hypothesis without predictions ⇒ INCOMPLETE."""
        p = base_payload(predictions=[])
        r = compile_payload(p)
        assert r.status == CompilationStatus.INCOMPLETE
        assert any(e.code == "E1_PREDICTIONS_MISSING" for e in r.errors)
        assert any(e.code == "E4_DISCRIMINATION_NO_PREDICTIONS" for e in r.errors)
        assert r.program is None

    def test_ac03_incomplete_missing_rival_coverage(self):
        """E5: a confirmatory program with no rival record ⇒ INCOMPLETE."""
        p = base_payload(
            hypotheses=[base_payload()["hypotheses"][0]],  # H1 only
            predictions=[base_payload()["predictions"][0]],  # P1 for H1 only
            discrimination_requirements=[],
        )
        r = compile_payload(p)
        assert r.status == CompilationStatus.INCOMPLETE
        assert any(e.code == "E5_RIVAL_COVERAGE" for e in r.errors)

    def test_ac04_contradictory_predictions(self):
        """Same claim, same observable+condition, conflicting directions."""
        p = base_payload(predictions=[
            {"ref": "P1", "claim_ref": "H1", "observable": "20d_returns",
             "direction": "FOR", "condition": "trend_up"},
            {"ref": "P1b", "claim_ref": "H1", "observable": "20d_returns",
             "direction": "AGAINST", "condition": "trend_up"},
        ])
        r = compile_payload(p)
        assert r.status == CompilationStatus.CONTRADICTORY
        assert any(e.code == "PREDICTION_CONFLICT" for e in r.errors)
        assert r.program is None

    def test_ac04_contradictory_discrimination(self):
        """E4: a discrimination requirement whose hypotheses predict
        identically cannot discriminate."""
        p = base_payload(predictions=[
            {"ref": "P1", "claim_ref": "H1", "observable": "20d_returns",
             "direction": "FOR", "condition": "trend_up"},
            {"ref": "P0", "claim_ref": "H0", "observable": "20d_returns",
             "direction": "FOR", "condition": "trend_up"},
        ])
        r = compile_payload(p)
        assert r.status == CompilationStatus.CONTRADICTORY
        assert any(e.code == "E4_DISCRIMINATION_NO_DIFFERENCE" for e in r.errors)

    def test_unsupported_template_ref(self):
        """GR7 template instantiation is P6 — a program requiring one is
        UNSUPPORTED, never silently instantiated (adversarial I)."""
        p = base_payload(task_graph_template_ref="template-1")
        r = compile_payload(p)
        assert r.status == CompilationStatus.UNSUPPORTED
        assert any(e.code == "UNSUPPORTED_TEMPLATE" for e in r.errors)
        assert r.program is None

    def test_scope_not_governed_invalid(self):
        """Governance: compilation without the frozen brief's hash fails."""
        r = compile_payload(base_payload(), scope_content_hash=None)
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "SCOPE_NOT_GOVERNED" for e in r.errors)

    def test_unresolvable_supersedes_invalid(self):
        p = base_payload(supersedes_ref="rp_deadbeef")
        r = compile_payload(p, superseded_program_ids=frozenset())
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "UNRESOLVABLE_SUPERSEDES" for e in r.errors)

    def test_errors_are_structured(self):
        p = base_payload(predictions=[])
        r = compile_payload(p)
        for err in r.errors:
            assert isinstance(err, CompilationError)
            assert err.code and err.field_path and err.requirement
            assert err.explanation and err.suggested_next_action


# ── ADR-041: parallel-regime-test linkage refusals (all-or-nothing) ──

class TestParallelRegimeRefusals:
    """The four refusals guarding parallel-regime linkage.

    Each case is isolated so the asserted code is the ONLY error: the four
    checks are independent ``if``s after the partial check, so a fixture
    setting several of the three fields at once would let one code mask
    another.
    """

    PARENT = "rp_knownparent00000000000000000"
    HYP = "H1"

    def test_parallel_regime_partial_fields_rejected(self):
        """PARTIAL_PARALLEL_REGIME_TEST_FIELDS (programs.py:806): linkage is
        all-or-nothing — one or two of the three fields set is partial.
        MERGE/conditions C2: the regime value here is the REGISTERED tag, so
        the partial-linkage code is the ONLY error reported — the property is
        isolated (the free-string refusal is covered by the bare/unversioned
        test above)."""
        # 1-of-3 (target_regime only): the other two remain None.
        r1 = compile_payload(base_payload(target_regime="ICSS-v1:low-vol"))
        # 2-of-3 (parent + target): parent_hypothesis_ref left None.
        r2 = compile_payload(
            base_payload(parent_program_id=self.PARENT,
                         target_regime="ICSS-v1:low-vol"),
            known_program_ids=frozenset({self.PARENT}),
        )
        for r in (r1, r2):
            assert r.status == CompilationStatus.INVALID
            assert r.program is None
            assert [e.code for e in r.errors] == [
                "PARTIAL_PARALLEL_REGIME_TEST_FIELDS"]

    def test_parallel_regime_unresolvable_parent_rejected(self):
        """UNRESOLVABLE_PARENT_PROGRAM (programs.py:817). MERGE/conditions C2:
        the registered regime isolates the parent-resolution code."""
        r = compile_payload(
            base_payload(parent_program_id="rp_missing0000000000000000000",
                         parent_hypothesis_ref=self.HYP,
                         target_regime="ICSS-v1:low-vol"),
            known_program_ids=frozenset({self.PARENT}),
            known_hypothesis_refs=frozenset({self.HYP}),
        )
        assert r.status == CompilationStatus.INVALID
        assert r.program is None
        assert [e.code for e in r.errors] == ["UNRESOLVABLE_PARENT_PROGRAM"]

    def test_parallel_regime_unresolvable_parent_hypothesis_rejected(self):
        """UNRESOLVABLE_PARENT_HYPOTHESIS (programs.py:825). MERGE/conditions
        C2: the registered regime isolates the hypothesis-resolution code."""
        r = compile_payload(
            base_payload(parent_program_id=self.PARENT,
                         parent_hypothesis_ref="H-missing",
                         target_regime="ICSS-v1:low-vol"),
            known_program_ids=frozenset({self.PARENT}),
            known_hypothesis_refs=frozenset({self.HYP}),
        )
        assert r.status == CompilationStatus.INVALID
        assert r.program is None
        assert [e.code for e in r.errors] == ["UNRESOLVABLE_PARENT_HYPOTHESIS"]

    def test_parallel_regime_blank_target_regime_rejected(self):
        """Blank target_regime is refused by the retained blank guard
        (INVALID_TARGET_REGIME, programs.py:835 — blank strings are blank
        before they are versioned); non-blank non-versioned regimes are
        refused by the registry wiring (UNVERSIONED_REGIME, covered above)."""
        for blank in ("", "   ", " \t\n"):
            r = compile_payload(
                base_payload(parent_program_id=self.PARENT,
                             parent_hypothesis_ref=self.HYP,
                             target_regime=blank),
                known_program_ids=frozenset({self.PARENT}),
                known_hypothesis_refs=frozenset({self.HYP}),
            )
            assert r.status == CompilationStatus.INVALID, blank
            assert r.program is None
            assert [e.code for e in r.errors] == ["INVALID_TARGET_REGIME"], blank


# ── COMPILED happy path: derivation, gates, E8 ──

class TestCompiledProgram:
    def test_compiled_derives_obligations(self):
        r = compile_payload(base_payload())
        assert r.status == CompilationStatus.COMPILED
        prog = r.program
        assert prog.program_id.startswith("rp_")
        assert len(prog.evidence_requirements) == 1
        req = prog.evidence_requirements[0]
        assert req.claim_ref == "H1"
        assert req.ladder_target == LadderTarget.SUPPORTED
        assert "pre_registered_experiment" in req.required_artifacts
        assert "statistical_analysis" in req.required_artifacts
        assert "adversarial_critique" in req.required_artifacts

    def test_compiled_gates_include_mandatory_human_gates(self):
        """Adversarial L: no execution path without the required gates."""
        r = compile_payload(base_payload())
        gates = r.program.gate_requirements
        assert "hypothesis" in gates
        assert "pre_compute" in gates
        assert "pre_live" in gates
        assert "data" in gates and "leakage" in gates and "statistical" in gates
        assert "methodology" in gates and "adversarial" in gates

    def test_ac07_compiled_program_carries_no_evidence_status(self):
        """E8: the program defines obligations, never evidence status.

        ``ladder_target`` appears as a *declared target* (what must be
        established) — the schema has no per-claim status field, and the
        payload-level unknown-key rejection (AC-02) closes that door. Here we
        assert the compiled program carries no status-like keys at all."""
        r = compile_payload(base_payload())
        serialized = json.dumps(program_to_dict(r.program), default=str)
        for status_key in ("evidence_status", "claim_status", "verdict",
                           "promotion", "ladder_status"):
            assert status_key not in serialized
        assert not hasattr(r.program, "status")

    def test_ac11_rival_preserved_first_class(self):
        """E5: ACTIVE rival with a distinct prediction is preserved."""
        r = compile_payload(base_payload())
        prog = r.program
        refs = [h.ref for h in prog.hypotheses]
        assert "H1" in refs and "H0" in refs
        h0 = next(h for h in prog.hypotheses if h.ref == "H0")
        assert h0.rival_of == "H1"
        assert h0.rival_status == RivalStatus.ACTIVE
        assert h0.ladder_target == LadderTarget.SPECULATIVE

    def test_ac11_unresolved_rival_preserved(self):
        """An UNRESOLVED rival is recorded, not collapsed or forced ACTIVE."""
        p = base_payload()
        p["hypotheses"][1]["rival_status"] = "UNRESOLVED"
        r = compile_payload(p)
        assert r.status == CompilationStatus.COMPILED
        h0 = next(h for h in r.program.hypotheses if h.ref == "H0")
        assert h0.rival_status == RivalStatus.UNRESOLVED

    def test_ac11_identical_rival_rejected(self):
        """E5 rule 3: a rival that predicts exactly what its primary predicts
        is a checkbox rival — INCOMPLETE, never silently kept."""
        p = base_payload(predictions=[
            {"ref": "P1", "claim_ref": "H1", "observable": "20d_returns",
             "direction": "FOR", "condition": "trend_up"},
            {"ref": "P0", "claim_ref": "H0", "observable": "20d_returns",
             "direction": "FOR", "condition": "trend_up"},
        ])
        # E4 fires CONTRADICTORY for the discrimination requirement; drop it
        # so only the E5 check applies.
        p["discrimination_requirements"] = []
        r = compile_payload(p)
        assert r.status == CompilationStatus.INCOMPLETE
        assert any(e.code == "E5_RIVAL_NOT_DISTINGUISHABLE" for e in r.errors)

    def test_summarize_is_deterministic(self):
        r = compile_payload(base_payload())
        s1 = summarize(r.program)
        s2 = summarize(r.program)
        assert s1 == s2
        assert "H1" in s1 and "hypothesis" in s1.lower()


# ── repository write path (AC-06, E9, idempotency, supersession) ──

class TestResearchProgramRepository:
    def test_ac06_record_rejects_non_compiled(self, repos):
        _, rp, _ = repos
        bad = compile_payload(base_payload(predictions=[]))
        assert bad.status != CompilationStatus.COMPILED
        with pytest.raises(ResearchProgramError):
            rp.record("p1", bad)

    def test_ac06_no_direct_mutation_bypass(self, repos):
        """The repository has no update/delete — immutability is structural,
        and there is no write path that bypasses the COMPILED gate."""
        _, rp, _ = repos
        assert not hasattr(rp, "update")
        assert not hasattr(rp, "delete")

    def test_record_compiled_persists_and_emits_event(self, repos):
        _, rp, events = repos
        result = compile_payload(base_payload())
        row = rp.record("p1", result, produced_by="director", reason="hypothesis gate")
        assert row["program_id"] == result.program.program_id
        assert row["content_hash"] == result.program.content_hash
        assert row["version"] == 1
        assert row["supersedes_id"] is None
        assert row["project_id"] == "p1"
        # derived obligations persisted
        assert row["evidence_requirements"][0]["claim_ref"] == "H1"
        assert "hypothesis" in row["gate_requirements"]
        # event emitted atomically
        events_for = events.list_for_project("p1")
        assert any(e["event_type"] == "ResearchProgramCompiled" for e in events_for)

    def test_duplicate_record_is_idempotent(self, repos):
        _, rp, events = repos
        r1 = compile_payload(base_payload())
        rp.record("p1", r1)
        count_before = len(events.list_for_project("p1"))
        row2 = rp.record("p1", compile_payload(base_payload()))
        count_after = len(events.list_for_project("p1"))
        assert row2["program_id"] == r1.program.program_id
        assert count_after == count_before  # no duplicate event

    def test_record_requires_scope_brief(self, repos):
        _, rp, _ = repos
        # scope "brief-3" does not exist
        result = compile_payload(base_payload(scope_ref="brief-3"),
                                 scope_content_hash="briefhash3")
        assert result.status == CompilationStatus.COMPILED
        with pytest.raises(ResearchProgramError):
            rp.record("p1", result)

    def test_record_without_supersession_rejected_when_chain_exists(self, repos):
        _, rp, _ = repos
        rp.record("p1", compile_payload(base_payload()))
        # A second non-superseding program would be a silent overwrite (E9)
        p2 = base_payload(
            epistemic_objective="A different objective entirely")
        with pytest.raises(ResearchProgramError):
            rp.record("p1", compile_payload(p2))

    def test_supersession_creates_new_version_history_preserved(self, repos):
        _, rp, _ = repos
        v1 = compile_payload(base_payload())
        row1 = rp.record("p1", v1)

        p2 = base_payload(
            epistemic_objective="Amended: momentum and reversal both tested",
            supersedes_ref=row1["program_id"],
        )
        v2 = compile_payload(
            p2,
            superseded_program_ids=frozenset({row1["program_id"]}),
        )
        assert v2.status == CompilationStatus.COMPILED
        row2 = rp.record("p1", v2)
        assert row2["version"] == 2
        assert row2["supersedes_id"] == row1["program_id"]

        # current() = head; list preserves both; v1 immutable
        assert rp.current("p1")["program_id"] == row2["program_id"]
        chain = rp.list_for_project("p1")
        assert [r["version"] for r in chain] == [1, 2]
        assert rp.get(row1["program_id"])["epistemic_objective"] == \
            row1["epistemic_objective"]

    def test_supersede_with_identical_content_rejected(self, repos):
        _, rp, _ = repos
        row1 = rp.record("p1", compile_payload(base_payload()))
        p2 = base_payload(supersedes_ref=row1["program_id"])
        v2 = compile_payload(
            p2,
            superseded_program_ids=frozenset({row1["program_id"]}),
        )
        assert v2.status == CompilationStatus.COMPILED
        with pytest.raises(ResearchProgramError):
            rp.record("p1", v2)

    def test_supersede_non_head_rejected(self, repos):
        _, rp, _ = repos
        row1 = rp.record("p1", compile_payload(base_payload()))
        p2 = base_payload(epistemic_objective="v2 objective",
                          supersedes_ref=row1["program_id"])
        rp.record("p1", compile_payload(
            p2,
            superseded_program_ids=frozenset({row1["program_id"]}),
        ))
        # try superseding v1 (not the head) with a new program
        p3 = base_payload(epistemic_objective="v3 objective",
                          supersedes_ref=row1["program_id"])
        v3 = compile_payload(
            p3,
            superseded_program_ids=frozenset({row1["program_id"]}),
        )
        assert v3.status == CompilationStatus.COMPILED
        with pytest.raises(ResearchProgramError):
            rp.record("p1", v3)

    def test_adversarial_h_superseded_program_still_readable(self, repos):
        _, rp, _ = repos
        row1 = rp.record("p1", compile_payload(base_payload()))
        p2 = base_payload(epistemic_objective="v2 objective",
                          supersedes_ref=row1["program_id"])
        rp.record("p1", compile_payload(
            p2,
            superseded_program_ids=frozenset({row1["program_id"]}),
        ))
        # superseded v1 remains immutable and queryable (E9, §16.1)
        v1 = rp.get(row1["program_id"])
        assert v1["version"] == 1
        assert v1["epistemic_objective"] == row1["epistemic_objective"]


# ── intent contract (Part 2 §8: a gateway-admitted proposal, Director-only) ──

class TestIntentContract:
    def test_propose_research_program_is_llm_proposable(self):
        assert IntentKind.PROPOSE_RESEARCH_PROGRAM in IntentKind.llm_proposable()

    def test_propose_research_program_is_director_only(self):
        assert IntentKind.PROPOSE_RESEARCH_PROGRAM in IntentKind.director_only()

    def test_propose_research_program_not_internal_only(self):
        assert IntentKind.PROPOSE_RESEARCH_PROGRAM not in IntentKind.internal_only()

    def test_intent_instantiates(self):
        intent = Intent(
            kind=IntentKind.PROPOSE_RESEARCH_PROGRAM,
            proposed_by="director",
            project_id="p1",
            payload=base_payload(),
            justification="hypothesis gate pack",
        )
        assert intent.is_llm_proposable()
        assert not intent.is_internal_only()


# ── migration (Part 3 §23) ──

class TestMigration:
    def test_fresh_db_migrates_to_latest(self):
        conn = connect(":memory:")
        migrate_to_latest(conn)
        assert get_schema_version(conn) == SUPPORTED_VERSION == 20  # Q-02: 8 → 9; IDR-041: 9 → 10; A4: 10 → 11; F9: 11 → 12; M1: 12 → 13; M4: 13 → 14; Step 7: 14 → 15; CHG-1/CHG-2: 15 → 16; P4 closure: 16 → 17; Step 3 FIX 1: 17 → 18 (advisory related_claim_ids); 18 → 19 (ADR-041: parallel-regime-test columns on research_programs)
        conn.close()

    def test_migration_replay_idempotent(self):
        conn = connect(":memory:")
        migrate_to_latest(conn)
        migrate_to_latest(conn)
        assert get_schema_version(conn) == 20
        conn.close()

    def test_v3_to_v4_upgrade_path(self):
        """A v3 database upgrades to v4 without losing existing data."""
        import hermes.persistence.migrations as m
        conn = connect(":memory:")
        clock = frozen_clock("2026-01-01T00:00:00.000000+00:00")
        for fn in m._MIGRATIONS[:3]:   # migrate 0 → 3
            conn.execute("BEGIN")
            fn(conn, clock)
            conn.execute("COMMIT")
        assert get_schema_version(conn) == 3
        # v3 data survives
        ProjectRepository(conn).create("p1", "Test")
        conn.execute(
            """INSERT INTO scope_briefs (brief_id, project_id, version,
               content_hash, supersedes_id, scope_text_json, rationale,
               created_at, frozen_at)
               VALUES (?, ?, 1, ?, NULL, ?, NULL, ?, ?)""",
            ("brief-1", "p1", "briefhash1", "{}",
             "2026-01-01T00:00:00.000000+00:00",
             "2026-01-01T00:00:00.000000+00:00"),
        )
        migrate_to_latest(conn)
        assert get_schema_version(conn) == 20
        assert ProjectRepository(conn).get("p1")["lifecycle_state"] == "CREATED"
        # new tables usable after upgrade
        rp = ResearchProgramRepository(conn)
        result = compile_from_payload(
            base_payload(), project_id="p1",
            scope_content_hash="briefhash1")
        row = rp.record("p1", result)
        assert row["version"] == 1
        conn.close()

    def test_future_version_rejected(self):
        conn = connect(":memory:")
        migrate_to_latest(conn)
        # rollback past 17→18 to simulate a v17 database
        conn.execute("DELETE FROM schema_version WHERE version IN (17, 18)")
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (999, 'x')")
        from hermes.persistence.database import SchemaVersionError
        with pytest.raises(SchemaVersionError):
            migrate_to_latest(conn)
        conn.close()

    def test_foreign_keys_enforced(self):
        """research_programs.project_id references projects (FK integrity)."""
        conn = connect(":memory:")
        migrate_to_latest(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO research_programs
                   (program_id, project_id, version, content_hash,
                    scope_ref, epistemic_objective, compiler_version,
                    policy_version, schema_version, input_hash,
                    hypothesis_json, prediction_json, discrimination_json,
                    evidence_json, gate_json, methodology_json, produced_by,
                    created_at)
                   VALUES ('rp_x', 'no-such-project', 1, 'h',
                           'b', 'o', 'c', 'p', '1', 'i',
                           '[]', '[]', '[]', '[]', '[]', '[]', 'd', 't')""")
        conn.close()


# ── Remediation regression tests (post-audit, R-01 .. R-04) ──

class TestRemediation:
    """Regression tests for defects confirmed by the post-implementation
    hostile re-verification. Each test fails if the original defect returns."""

    def test_r01_determinism_two_confirmatory_order_invariant(self):
        """R-01: derived evidence_requirements follow hypothesis input order;
        two confirmatory hypotheses in different order must still compile to
        the identical content hash."""
        def payload(order):
            return base_payload(
                hypotheses=[
                    {"ref": h, "ladder_target": "SUPPORTED",
                     "falsification_condition": "f",
                     "rival_of": None, "rival_status": None}
                    for h in order
                ] + [
                    {"ref": "H0", "ladder_target": "SPECULATIVE",
                     "falsification_condition": "f",
                     "rival_of": "H1", "rival_status": "UNRESOLVED"},
                ],
                predictions=[
                    {"ref": f"P{h}", "claim_ref": h, "observable": "obs",
                     "direction": "FOR", "condition": "c"} for h in order
                ],
                discrimination_requirements=[],
            )
        r1 = compile_payload(payload(["H1", "H2"]))
        r2 = compile_payload(payload(["H2", "H1"]))
        assert r1.status == CompilationStatus.COMPILED, r1.errors
        assert r2.status == CompilationStatus.COMPILED, r2.errors
        assert r1.program.content_hash == r2.program.content_hash
        assert r1.program.program_id == r2.program.program_id

    def test_r02_write_path_rejects_bogus_scope_hash(self, repos):
        """R-02: a program compiled against a hash that is not the frozen
        brief's actual content hash is rejected at the write path — the
        governance context is enforced by the repository, not trusted from
        the caller."""
        _, rp, _ = repos
        bogus = compile_payload(base_payload(),
                                scope_content_hash="GARBAGE-NOT-THE-BRIEF-HASH")
        assert bogus.status == CompilationStatus.COMPILED  # validator: non-None
        with pytest.raises(ResearchProgramError):
            rp.record("p1", bogus)
        # nothing was persisted
        assert rp.current("p1") is None

    def test_r02_write_path_accepts_matching_scope_hash(self, repos):
        _, rp, _ = repos
        good = compile_payload(base_payload(), scope_content_hash="briefhash1")
        row = rp.record("p1", good)
        assert row["program_id"] == good.program.program_id

    def test_r03_non_string_ref_fails_closed(self):
        """R-03: malformed LLM output (a numeric ref) is rejected, never
        coerced into a plausible string."""
        p = base_payload()
        p["hypotheses"][0]["ref"] = 123
        r = compile_payload(p)
        assert r.status == CompilationStatus.INVALID
        assert r.program is None
        assert any(e.code == "MALFORMED_PAYLOAD" for e in r.errors)

    def test_r03_non_string_objective_fails_closed(self):
        p = base_payload(epistemic_objective={"text": "objective"})
        r = compile_payload(p)
        assert r.status == CompilationStatus.INVALID
        assert any(e.code == "MALFORMED_PAYLOAD" for e in r.errors)

    def test_ecf01_nested_unknown_keys_rejected(self):
        """EC-F01: unknown keys nested inside hypothesis/prediction/
        discrimination entries are rejected, not silently dropped."""
        p = base_payload()
        p["hypotheses"][0]["status"] = "SUPPORTED"
        p["hypotheses"][0]["sql"] = "DROP TABLE tasks"
        r = compile_payload(p)
        assert r.status == CompilationStatus.INVALID
        assert r.program is None
        nested = [e for e in r.errors if e.code == "UNKNOWN_PAYLOAD_KEY"
                  and e.field_path == "payload.hypotheses[0]"]
        assert nested, r.errors

    def test_ecf01_nested_unknown_keys_predictions_and_discrimination(self):
        p = base_payload()
        p["predictions"][0]["gate_override"] = True
        p["discrimination_requirements"][0]["bypass"] = True
        r = compile_payload(p)
        assert r.status == CompilationStatus.INVALID
        paths = {e.field_path for e in r.errors}
        assert "payload.predictions[0]" in paths
        assert "payload.discrimination_requirements[0]" in paths

    def test_ecf02_typed_draft_fails_closed(self):
        """EC-F02: a malformed *typed* draft returns an INVALID verdict
        (MALFORMED_DRAFT) instead of raising."""
        from hermes.research.programs import (
            HypothesisSpec,
            LadderTarget,
            ResearchProgramDraft,
        )
        draft = ResearchProgramDraft(
            scope_ref="brief-1", epistemic_objective="o",
            hypotheses=(HypothesisSpec(
                ref=123, ladder_target=LadderTarget.SPECULATIVE,
                falsification_condition="f"),),
        )
        r = compile_research_program(
            draft, project_id="p1", scope_content_hash="bh")
        assert r.status == CompilationStatus.INVALID
        assert r.program is None
        assert any(e.code == "MALFORMED_DRAFT" for e in r.errors)

    def test_ecf02_valid_typed_draft_still_compiles(self):
        from hermes.research.programs import (
            HypothesisSpec,
            LadderTarget,
            ResearchProgramDraft,
        )
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

    def test_r04_failure_injection_no_partial_state(self, db):
        """R-04: if the DB write fails mid-transaction, no program row and
        no ResearchProgramCompiled event remain (command→validate→apply→
        event is atomic, IDR-013).

        Deterministic injection: a trigger aborts the INSERT. The repository
        must roll back the whole transaction.
        """
        conn = db
        db.execute(
            "CREATE TRIGGER trg_fail_rp BEFORE INSERT ON research_programs "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
        rp = ResearchProgramRepository(conn)
        events = EventRepository(conn)
        result = compile_from_payload(base_payload(), project_id="p1",
                                      scope_content_hash="briefhash1")
        with pytest.raises(sqlite3.IntegrityError):
            rp.record("p1", result)
        assert rp.current("p1") is None
        assert rp.list_for_project("p1") == []
        compiled_events = [e for e in events.list_for_project("p1")
                           if e["event_type"] == "ResearchProgramCompiled"]
        assert compiled_events == []


# ── EC-V6-11..20: persistence integrity boundary (Step 5, v6 §28.2 Model D) ──

class TestIntegrityBoundary:
    """The repository never blindly trusts a caller-claimed COMPILED object.

    Identity (``content_hash`` / ``program_id`` / ``input_hash`` /
    ``schema_version``) and the derived obligations are re-derived with the
    compiler's OWN pure helpers at the write path — one deterministic
    derivation, never two (EC-V6-11..16). Every mismatch fails closed: no
    row, no ResearchProgramCompiled event. Genuine compilations and genuine
    idempotent duplicates are unaffected.
    """

    def _compiled(self, **ctx) -> object:
        return compile_from_payload(
            base_payload(), project_id="p1",
            scope_content_hash=ctx.get("scope_content_hash", "briefhash1"))

    def _compiled_events(self, db) -> list:
        return [e for e in EventRepository(db).list_for_project("p1")
                if e["event_type"] == "ResearchProgramCompiled"]

    def _as_compiled(self, program) -> object:
        return CompilationResult(CompilationStatus.COMPILED, (), program)

    def test_ec_v6_11_forged_content_hash_rejected(self, db, repos):
        from dataclasses import replace
        result = self._compiled()
        forged = replace(result.program, content_hash="forged-content-hash")
        with pytest.raises(ResearchProgramIntegrityError):
            repos[1].record("p1", self._as_compiled(forged))
        assert repos[1].list_for_project("p1") == []
        assert self._compiled_events(db) == []

    def test_ec_v6_11_forged_program_id_rejected(self, db, repos):
        from dataclasses import replace
        result = self._compiled()
        forged = replace(result.program, program_id="rp_attacker-chosen")
        with pytest.raises(ResearchProgramIntegrityError):
            repos[1].record("p1", self._as_compiled(forged))
        assert repos[1].list_for_project("p1") == []
        assert self._compiled_events(db) == []

    def test_ec_v6_13_forged_input_hash_rejected(self, db, repos):
        from dataclasses import replace
        result = self._compiled()
        forged = replace(result.program, input_hash="forged-input-hash")
        with pytest.raises(ResearchProgramIntegrityError):
            repos[1].record("p1", self._as_compiled(forged))
        assert repos[1].list_for_project("p1") == []
        assert self._compiled_events(db) == []

    def test_ec_v6_14_obligation_divergence_rejected(self, db, repos):
        """Self-consistent forged hashes over empty obligations still fail:
        obligations are derived from hypotheses, never declared (EC-V6-14)."""
        from dataclasses import replace

        from hermes.research.programs import (
            content_hash_of,
            input_hash_of,
            program_id_of,
        )
        result = self._compiled()
        forged = replace(
            result.program,
            evidence_requirements=(),
            gate_requirements=(),
        )
        forged = replace(
            forged,
            content_hash=content_hash_of(forged),
            input_hash=input_hash_of(forged),
            program_id=program_id_of(content_hash_of(forged)),
        )
        assert forged.content_hash == content_hash_of(forged)
        with pytest.raises(ResearchProgramIntegrityError):
            repos[1].record("p1", self._as_compiled(forged))
        assert repos[1].list_for_project("p1") == []
        assert self._compiled_events(db) == []

    def test_ec_v6_15_forged_schema_version_rejected(self, db, repos):
        """schema_version is part of the approved identity contract: a
        self-consistent object claiming schema "999" is rejected — the
        validator would reject it as INVALID, and the write path must not
        persist what the validator cannot (EC-V6-15)."""
        from dataclasses import replace

        from hermes.research.programs import (
            content_hash_of,
            input_hash_of,
            program_id_of,
        )
        result = self._compiled()
        forged = replace(result.program, schema_version="999")
        forged = replace(
            forged,
            content_hash=content_hash_of(forged),
            input_hash=input_hash_of(forged),
            program_id=program_id_of(content_hash_of(forged)),
        )
        with pytest.raises(ResearchProgramIntegrityError):
            repos[1].record("p1", self._as_compiled(forged))
        assert repos[1].list_for_project("p1") == []
        assert self._compiled_events(db) == []

    def test_ec_v6_15_stale_version_tamper_rejected_by_identity(self, db, repos):
        """Changing a version field WITHOUT re-deriving identity is caught by
        the content-hash check (identity integrity) — versions are inputs of
        the identity, never caller-editable metadata (EC-V6-15)."""
        from dataclasses import replace
        result = self._compiled()
        forged = replace(result.program, compiler_version="999.999.999")
        with pytest.raises(ResearchProgramIntegrityError):
            repos[1].record("p1", self._as_compiled(forged))
        assert repos[1].list_for_project("p1") == []
        assert self._compiled_events(db) == []

    def test_ec_v6_16_multi_field_forge_rejected(self, db, repos):
        """The strongest Step 4 exploit — every identity field hand-forged on
        a hand-built COMPILED object — is rejected; nothing persists."""
        from dataclasses import replace

        from hermes.research.programs import CompilationResult
        forged = replace(
            self._compiled().program,
            program_id="rp_handbuilt_forged_id",
            content_hash="deadbeef_content",
            input_hash="deadbeef_input",
            schema_version="999",
            hypotheses=(),
            predictions=(),
            evidence_requirements=(),
            gate_requirements=(),
        )
        result = CompilationResult(CompilationStatus.COMPILED, (), forged)
        with pytest.raises(ResearchProgramIntegrityError):
            repos[1].record("p1", result)
        assert repos[1].list_for_project("p1") == []
        assert self._compiled_events(db) == []

    def test_ec_v6_17_genuine_compile_persists(self, db, repos):
        result = self._compiled()
        row = repos[1].record("p1", result)
        assert row["program_id"] == result.program.program_id
        assert row["content_hash"] == result.program.content_hash
        assert repos[1].current("p1")["program_id"] == result.program.program_id
        assert len(self._compiled_events(db)) == 1

    def test_ec_v6_18_genuine_idempotent_duplicate_returns_existing(self, db, repos):
        result = self._compiled()
        first = repos[1].record("p1", result)
        second = repos[1].record("p1", self._compiled())
        assert second["program_id"] == first["program_id"]
        assert len(repos[1].list_for_project("p1")) == 1
        assert len(self._compiled_events(db)) == 1

    def test_ec_v6_20_validator_compiled_survives_helpers(self):
        """The shared derivation is THE validator's derivation: a genuinely
        compiled program always re-derives to its own identity."""
        from hermes.research.programs import (
            content_hash_of,
            derive_program_obligations,
            input_hash_of,
            program_id_of,
        )
        result = self._compiled()
        p = result.program
        assert p.content_hash == content_hash_of(p)
        assert p.input_hash == input_hash_of(p)
        assert p.program_id == program_id_of(p.content_hash)
        ev, gates = derive_program_obligations(p.hypotheses)
        assert ev == p.evidence_requirements
        assert gates == p.gate_requirements

    # ── AR-01 write-path epistemic re-validation (V6 defense) ──

    def _reidentify(self, forged):
        """Re-derive identity so the forged object is self-consistent
        (passes EC-V6-11..16) — the AR-01 attack's core: correct hashes,
        wrong epistemic content."""
        from dataclasses import replace

        from hermes.research.programs import (
            content_hash_of,
            input_hash_of,
            program_id_of,
        )
        forged = replace(
            forged,
            content_hash=content_hash_of(forged),
            input_hash=input_hash_of(forged),
            program_id=program_id_of(content_hash_of(forged)),
        )
        assert forged.content_hash == content_hash_of(forged)
        assert forged.input_hash == input_hash_of(forged)
        assert forged.program_id == program_id_of(forged.content_hash)
        return forged

    def test_ar01_missing_predictions_rejected_at_write_path(self, db, repos):
        """AR-01 exact example: a confirmatory hypothesis with NO prediction,
        self-consistently re-hashed. Identity and obligations re-derive
        correctly (predictions do not feed the obligation derivation), so
        the pre-AR-01 write path would have persisted it. Now the pure
        E-check re-run (E1) fails closed."""
        from dataclasses import replace
        result = self._compiled()
        forged = replace(
            result.program,
            # drop P1 — H1 (SUPPORTED) loses its only prediction
            predictions=tuple(p for p in result.program.predictions
                               if p.ref != "P1"),
        )
        forged = self._reidentify(forged)
        with pytest.raises(ResearchProgramIntegrityError, match="E1_PREDICTIONS_MISSING"):
            repos[1].record("p1", self._as_compiled(forged))
        assert repos[1].list_for_project("p1") == []
        assert self._compiled_events(db) == []

    def test_ar01_missing_rival_coverage_rejected_at_write_path(self, db, repos):
        """AR-01 class: a confirmatory program whose rival linkage is
        stripped, self-consistently re-hashed — E5 (rival coverage) fails
        closed at the write path."""
        from dataclasses import replace
        result = self._compiled()
        forged = replace(
            result.program,
            hypotheses=tuple(
                replace(h, rival_of=None, rival_status=None)
                for h in result.program.hypotheses),
        )
        forged = self._reidentify(forged)
        with pytest.raises(ResearchProgramIntegrityError, match="E5_RIVAL_COVERAGE"):
            repos[1].record("p1", self._as_compiled(forged))
        assert repos[1].list_for_project("p1") == []

    def test_ar01_prediction_conflict_rejected_at_write_path(self, db, repos):
        """AR-01 class: a claim predicting both directions for the same
        observable+condition, self-consistently re-hashed — the compiler
        would refuse it CONTRADICTORY, and the write path now refuses to
        persist it (contradiction rule re-run)."""
        from dataclasses import replace

        from hermes.research.programs import PredictionDirection
        result = self._compiled()
        p0 = result.program.predictions[0]  # P1, FOR, 20d_returns/trend_up
        conflict = replace(p0, ref="P1b",
                           direction=PredictionDirection.AGAINST)
        forged = replace(
            result.program,
            predictions=result.program.predictions + (conflict,),
        )
        forged = self._reidentify(forged)
        with pytest.raises(ResearchProgramIntegrityError, match="PREDICTION_CONFLICT"):
            repos[1].record("p1", self._as_compiled(forged))
        assert repos[1].list_for_project("p1") == []

    def test_ar01_genuine_program_still_persists(self, db, repos):
        """The re-validation must not reject what the validator accepts."""
        result = self._compiled()
        row = repos[1].record("p1", result)
        assert row["program_id"] == result.program.program_id
        assert len(self._compiled_events(db)) == 1
