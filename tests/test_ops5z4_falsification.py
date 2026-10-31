"""OPS-5Z4 — falsification capabilities that can look at evidence.

Three declared ids had no implementation: ``evidence_inspect``,
``contradiction_scan`` and ``statistic_check``. The critic and the verifier
reviewed prose against prose. This file is the falsification of the fix:

* the real 33,727-byte OpenAlex record is read as *content*, not as the
  metadata prefix — and its abstract states no figure, so none is invented;
* the real 5,590-byte cookie wall yields nothing at all;
* a figure binds to the subject and date a claim gives it;
* the incident ordering (India 5,275,035, Brazil 4,467,433, "Brazil was ahead")
  is reported as a conflict, and two claims that agree are not;
* a total wrong by one digit is inconsistent, a correct one is consistent;
* each of the three has a **red proof**: with the rule stubbed to "no problem"
  the same assertion that passes in the real test now fails.

The capability path is the shipped supply and the shipped invoker: a grant, a
registry, an artifact store and the project-scoped read. No network is dialed
and no model is involved.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pytest

from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import TOOL_CALL_KEYS, AgentRuntime
from hermes.agents.runtime.types import RunLimits, TaskContext
from hermes.artifacts.store import ArtifactStore
from hermes.composition import build_capability_tool_notes, plan_capability_plane
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
from hermes.research import capability_supply as supply_module
from hermes.research.capability_supply import (
    FALSIFICATION_CAPABILITY_IDS,
    FALSIFICATION_TOOL_SET_ID,
    INSPECT_ARTIFACT_MISSING,
    INSPECT_INTEGRITY_REFUSED,
    INSPECT_REF_MALFORMED,
    RESEARCH_CAPABILITY_IDS,
    RESEARCH_EGRESS_TOOL_SET_ID,
    SCAN_CLAIMS_MISSING,
    SCAN_REFS_MISMATCH,
    SCAN_TOO_MANY_CLAIMS,
    STATISTIC_BASIS_MISSING,
    SUPPLIED_CAPABILITY_IDS,
    ResearchEgressSupply,
    build_research_egress_supply,
)
from hermes.research.inspection import (
    ArithmeticVerdict,
    ClaimText,
    Inspection,
    conflicts_between,
    facts_in,
)
from hermes.research.live_fetch import ALLOWLIST_HOSTS, build_live_fetch_wiring
from hermes.tools.capabilities.content import read_content
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.types import (
    CapabilityRefusal,
    InvokeRequest,
    Observation,
    RiskLevel,
    ToolGrant,
)
from hermes.tools.models.router import ModelProposal

CLOCK = "2026-10-30T09:00:00.000000+00:00"
PROJECT = "p-ops5z4"
OTHER_PROJECT = "p-ops5z4-other"
PROFILE = "ADVERSARY"

FIXTURES = Path(__file__).parent / "fixtures" / "source_payloads"
OPENALEX_WORK = FIXTURES / "openalex_work_33727.json"
COOKIE_WALL = FIXTURES / "pubmed_cookie_wall_5590.html"

#: The incident, as three claims: two figures and the ordering that reverses
#: one of them. The figures live in C1/C2 and the assertion in C3, which is the
#: shape a pair-wise scan cannot see.
INCIDENT = [
    ("C1", "India reported 5,275,035 cases on 18 September 2020."),
    ("C2", "Brazil 4,467,433 cases on 18 September 2020."),
    ("C3", "Brazil was ahead of India on 18 September 2020."),
]

RISKS = {
    "source_fetch": "MEDIUM", "source_search": "MEDIUM",
    "evidence_inspect": "LOW", "contradiction_scan": "LOW",
    "statistic_check": "LOW",
}


class Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 1000.0


@pytest.fixture
def rig(tmp_path: Path):
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5Z4")
    ProjectRepository(conn, lambda: CLOCK).create(OTHER_PROJECT, "other")
    store = ArtifactStore(
        str(tmp_path / "store"),
        ArtifactRepository(conn, lambda: CLOCK),
        clock=lambda: CLOCK)
    wiring = build_live_fetch_wiring(conn, store, lambda: CLOCK)
    supply = build_research_egress_supply(
        conn=conn, store=store, clock=lambda: CLOCK, project_id=PROJECT,
        machinery=wiring.machinery, allowlist=ALLOWLIST_HOSTS)
    invoker = CapabilityInvoker(
        registry=supply.registry,
        implementations=supply.implementations,
        clock=Clock(),
        ledger=InMemoryIdempotencyLedger(),
        sandbox_enabled=False)
    yield conn, store, invoker, supply
    conn.close()


def _invoke(invoker: CapabilityInvoker, capability_id: str,
            arguments: dict[str, Any], *, key: str,
            sets: Iterable[str] = (FALSIFICATION_TOOL_SET_ID,),
            risk: str = RiskLevel.LOW.value,
            ) -> Observation | CapabilityRefusal:
    return invoker.invoke(InvokeRequest(
        capability_id=capability_id,
        arguments=arguments,
        idempotency_key=key,
        lease_generation="lease-gen-ops5z4",
        profile=PROFILE,
        rationale="falsify the claim before accepting it",
        grant=ToolGrant(
            grant_id="grant.ops5z4",
            profile=PROFILE,
            tool_set_ids=frozenset(sets),
            max_risk=risk),
        deadline_seconds=10.0))


def _payload(observation: Observation) -> dict[str, Any]:
    assert observation.payload is not None
    return json.loads(observation.payload.text)


def _admit(store: ArtifactStore, data: bytes, artifact_id: str, *,
           project_id: str = PROJECT,
           content_format: str = "") -> dict[str, Any]:
    metadata = {"content_format": content_format} if content_format else None
    return store.write(
        data, "source_payload", "test.ops5z4", project_id=project_id,
        artifact_id=artifact_id, metadata=metadata)


def _inspect(invoker: CapabilityInvoker, ref: str, *, key: str,
             subjects: list[str] | None = None) -> Observation:
    arguments: dict[str, Any] = {"ref": ref}
    if subjects is not None:
        arguments["subjects"] = subjects
    result = _invoke(invoker, "evidence_inspect", arguments, key=key)
    assert isinstance(result, Observation), result
    assert result.ok(), result.detail
    return result


def _scan(invoker: CapabilityInvoker, refs: list[str], statements: list[str],
          *, key: str) -> Observation:
    result = _invoke(
        invoker, "contradiction_scan",
        {"refs": refs, "statements": statements}, key=key)
    assert isinstance(result, Observation), result
    assert result.ok(), result.detail
    return result


def _check(invoker: CapabilityInvoker, statement: str, *, key: str,
           base_refs: list[str] | None = None) -> Observation:
    arguments: dict[str, Any] = {"statement": statement}
    if base_refs is not None:
        arguments["base_refs"] = base_refs
    result = _invoke(invoker, "statistic_check", arguments, key=key)
    assert isinstance(result, Observation), result
    assert result.ok(), result.detail
    return result


# ═══════════════ the pure extraction, on the real bytes ═══════════════


def test_the_real_openalex_record_is_read_as_content_not_metadata() -> None:
    raw = OPENALEX_WORK.read_bytes()
    assert len(raw) == 33727
    document = json.loads(raw)
    read = read_content(raw, format="openalex")
    text = read.text

    assert read.state == "content"
    assert text.startswith(document["title"][:40])
    facts = facts_in(read)

    # The abstract is a modelling study and states no figure and no date. The
    # record's metadata does (publication_date 2020-09-27, cited_by_count 34);
    # a byte-prefix read, or a whole-record scan, would report them as facts.
    assert facts.figures == ()
    assert facts.dates == ()
    assert document["publication_date"] not in text


def test_the_real_cookie_wall_yields_no_invented_fact() -> None:
    raw = COOKIE_WALL.read_bytes()
    assert len(raw) == 5590
    facts = facts_in(read_content(raw, format="html"))
    assert facts.figures == ()
    assert facts.dates == ()
    assert facts.quotes == ()


def test_a_year_is_a_date_but_a_grouped_thousand_is_not() -> None:
    facts = facts_in(
        "In 2020 the agency counted 2,020 cases and 34 deaths.")
    literals = [figure.literal for figure in facts.figures]
    # `2020` is the date; `2,020` and `34` are figures.
    assert "2020" not in literals
    assert literals == ["2,020", "34"]
    assert [date.iso for date in facts.dates] == []


def test_a_figure_binds_to_the_subject_and_date_the_record_gives_it() -> None:
    record = {
        "title": "Containment estimates",
        "abstract": (
            "Hubei averted 1,200 cases between 23 January 2020 and "
            "2 February 2020, and the reproduction number fell to 0.9."),
    }
    facts = facts_in(read_content(json.dumps(record).encode("utf-8"),
                                  format="openalex"))

    figures = {figure.literal: figure for figure in facts.figures}
    assert figures["1,200"].entity == "Hubei"
    assert figures["1,200"].date == "2020-01-23"
    assert figures["0.9"].unit == ""
    assert {date.iso for date in facts.dates} == {
        "2020-01-23", "2020-02-02"}


# ═══════════════ evidence_inspect ═══════════════


def test_evidence_inspect_reports_the_admitted_artifacts_facts(rig) -> None:
    _conn, store, invoker, _supply = rig
    row = _admit(store, OPENALEX_WORK.read_bytes(), "art-openalex",
                 content_format="openalex")
    observation = _inspect(invoker, f"evidence/{row['artifact_id']}",
                           key="inspect-openalex")

    facts = _payload(observation)["facts"]
    assert facts["figures"] == []
    assert facts["dates"] == []
    assert "no date, figure or quoted span" in observation.detail


def test_evidence_inspect_reads_the_content_and_its_bound_figures(rig) -> None:
    _conn, store, invoker, _supply = rig
    record = {
        "title": "Containment estimates",
        "abstract": "Hubei averted 1,200 cases between 23 January 2020 and "
                    "2 February 2020.",
    }
    row = _admit(store, json.dumps(record).encode("utf-8"), "art-estimate",
                 content_format="openalex")
    observation = _inspect(invoker, f"evidence/{row['artifact_id']}",
                           key="inspect-estimate")

    figures = _payload(observation)["facts"]["figures"]
    assert len(figures) == 1
    assert figures[0]["entity"] == "Hubei"
    assert figures[0]["literal"] == "1,200"
    assert figures[0]["date"] == "2020-01-23"
    assert "Hubei 1,200" in observation.detail


def test_evidence_inspect_subject_filter_keeps_only_matching_figures(rig) -> None:
    _conn, store, invoker, _supply = rig
    row = _admit(
        store,
        b"Hubei averted 1,200 cases. Brazil reported 4,467,433 cases.",
        "art-two-subjects")
    observation = _inspect(invoker, f"evidence/{row['artifact_id']}",
                           key="inspect-filter", subjects=["Hubei"])
    literals = [figure["literal"]
                for figure in _payload(observation)["facts"]["figures"]]
    assert literals == ["1,200"]


def test_evidence_inspect_never_reads_another_projects_artifact(rig) -> None:
    _conn, store, invoker, _supply = rig
    row = _admit(store, b"India 5,275,035 cases.", "art-other-project",
                 project_id=OTHER_PROJECT)
    result = _invoke(invoker, "evidence_inspect",
                     {"ref": f"evidence/{row['artifact_id']}"},
                     key="inspect-other-project")

    assert isinstance(result, Observation), result
    payload = _payload(result)
    assert payload["status"] == "REFUSED"
    assert payload["code"] == INSPECT_ARTIFACT_MISSING


def test_evidence_inspect_refuses_a_path_shaped_ref(rig) -> None:
    _conn, _store, invoker, _supply = rig
    for ref in ("/etc/passwd", "../../secrets", "C:/Windows/win.ini"):
        result = _invoke(invoker, "evidence_inspect", {"ref": ref},
                         key=f"inspect-path-{ref}")
        assert isinstance(result, Observation), result
        payload = _payload(result)
        assert payload["status"] == "REFUSED"
        assert payload["code"] == INSPECT_REF_MALFORMED


def test_evidence_inspect_refuses_bytes_that_no_longer_verify(rig) -> None:
    _conn, store, invoker, _supply = rig
    row = _admit(store, b"India 5,275,035 cases.", "art-tampered")
    path = Path(store._root) / str(row["storage_path"])
    path.write_bytes(b"India 9,999,999 cases.")
    result = _invoke(invoker, "evidence_inspect",
                     {"ref": f"evidence/{row['artifact_id']}"},
                     key="inspect-tampered")

    assert isinstance(result, Observation), result
    payload = _payload(result)
    assert payload["status"] == "REFUSED"
    assert payload["code"] == INSPECT_INTEGRITY_REFUSED
    assert "no longer re-derives" in payload["detail"]


# ═══════════════ contradiction_scan ═══════════════


def _assert_incident_conflict_reported(invoker: CapabilityInvoker,
                                       key: str) -> None:
    """The check both the real test and its red proof call."""
    observation = _scan(invoker, [ref for ref, _ in INCIDENT],
                        [text for _, text in INCIDENT], key=key)
    conflicts = _payload(observation)["conflicts"]
    assert any(item["kind"] == "ORDER" for item in conflicts), conflicts
    assert "4,467,433" in observation.detail
    assert "5,275,035" in observation.detail


def test_the_incident_ordering_is_reported_as_a_conflict(rig) -> None:
    _conn, _store, invoker, _supply = rig
    _assert_incident_conflict_reported(invoker, "scan-incident")


def test_claims_that_agree_report_no_conflict(rig) -> None:
    _conn, _store, invoker, _supply = rig
    observation = _scan(
        invoker, ["A", "B"],
        ["India 5,275,035 cases on 18 September 2020.",
         "India reported 5,275,035 cases as of 18 September 2020."],
        key="scan-agree")
    assert _payload(observation)["conflicts"] == []
    assert "no conflict" in observation.detail


def test_the_same_subject_with_two_figures_on_one_date_is_reported(rig) -> None:
    _conn, _store, invoker, _supply = rig
    conflicts = _payload(_scan(
        invoker, ["A", "B"],
        ["India 5,275,035 cases on 18 September 2020.",
         "India 5,275,045 cases on 18 September 2020."],
        key="scan-quantity"))["conflicts"]
    assert [item["kind"] for item in conflicts] == ["QUANTITY"]
    assert conflicts[0]["subject"] == "India"


def test_a_scan_needs_statements_and_aligned_refs(rig) -> None:
    _conn, _store, invoker, _supply = rig
    empty = _invoke(invoker, "contradiction_scan",
                    {"statements": []}, key="scan-empty")
    assert isinstance(empty, Observation), empty
    assert _payload(empty)["code"] == SCAN_CLAIMS_MISSING

    misaligned = _invoke(
        invoker, "contradiction_scan",
        {"statements": ["India 5,275,035 cases.",
                        "Brazil 4,467,433 cases."],
         "refs": ["A"]},
        key="scan-misaligned")
    assert isinstance(misaligned, Observation), misaligned
    assert _payload(misaligned)["code"] == SCAN_REFS_MISMATCH


# ═══════════════ statistic_check ═══════════════


def test_a_total_wrong_by_one_digit_is_inconsistent(rig) -> None:
    _conn, _store, invoker, _supply = rig
    observation = _check(
        invoker,
        "India 5,275,035 and Brazil 4,467,433, a total of 9,742,469 cases.",
        key="check-wrong-total")
    payload = _payload(observation)
    assert payload["status"] == "INCONSISTENT"
    assert payload["operator"] == "sum"
    assert payload["computed"] == 9742468.0
    assert payload["asserted"] == "9,742,469"
    assert "inconsistent" in observation.detail


def test_a_correct_total_is_consistent(rig) -> None:
    _conn, _store, invoker, _supply = rig
    payload = _payload(_check(
        invoker,
        "India 5,275,035 and Brazil 4,467,433, a total of 9,742,468 cases.",
        key="check-right-total"))
    assert payload["status"] == "CONSISTENT"
    assert payload["computed"] == 9742468.0


def test_a_percentage_is_recomputed(rig) -> None:
    _conn, _store, invoker, _supply = rig
    wrong = _payload(_check(invoker, "25% of 400 is 120.", key="check-pct"))
    assert wrong["status"] == "INCONSISTENT"
    assert wrong["computed"] == 100.0

    right = _payload(_check(invoker, "25% of 400 is 100.", key="check-pct-ok"))
    assert right["status"] == "CONSISTENT"


def test_an_unasserted_computation_is_not_a_verdict(rig) -> None:
    _conn, _store, invoker, _supply = rig
    payload = _payload(_check(invoker, "50% of 200", key="check-unasserted"))
    assert payload["status"] == "UNPARSEABLE"
    assert payload["computed"] is None


def test_base_refs_supply_the_components_of_a_stated_total(rig) -> None:
    _conn, store, invoker, _supply = rig
    india = _admit(store, b"India reported 5,275,035 cases.", "art-india")
    brazil = _admit(store, b"Brazil reported 4,467,433 cases.", "art-brazil")
    bases = [f"evidence/{india['artifact_id']}",
             f"evidence/{brazil['artifact_id']}"]

    good = _payload(_check(invoker, "The total is 9,742,468 cases.",
                           key="check-bases-ok", base_refs=bases))
    assert good["status"] == "CONSISTENT"
    assert good["computed"] == 9742468.0

    bad = _payload(_check(invoker, "The total is 9,742,469 cases.",
                          key="check-bases-bad", base_refs=bases))
    assert bad["status"] == "INCONSISTENT"


def test_a_missing_basis_ref_is_a_named_refusal(rig) -> None:
    _conn, _store, invoker, _supply = rig
    result = _invoke(invoker, "statistic_check",
                     {"statement": "The total is 9,742,468 cases.",
                      "base_refs": ["evidence/art-absent"]},
                     key="check-missing-basis")
    assert isinstance(result, Observation), result
    payload = _payload(result)
    assert payload["status"] == "REFUSED"
    assert payload["code"] == STATISTIC_BASIS_MISSING


# ═══════════════ red proofs — the rule is load-bearing ═══════════════


def test_red_proof_without_the_conflict_rules_the_scan_finds_nothing(
        rig, monkeypatch: pytest.MonkeyPatch) -> None:
    _conn, _store, invoker, _supply = rig
    monkeypatch.setattr(supply_module, "conflicts_between",
                        lambda claims: ())
    with pytest.raises(AssertionError):
        _assert_incident_conflict_reported(invoker, "scan-red")


def test_red_proof_without_extraction_the_inspection_finds_no_fact(
        rig, monkeypatch: pytest.MonkeyPatch) -> None:
    _conn, store, invoker, _supply = rig
    monkeypatch.setattr(
        supply_module, "facts_in",
        lambda text: Inspection((), (), (), (), 0, False))
    row = _admit(
        store,
        b"Hubei averted 1,200 cases between 23 January 2020 and "
        b"2 February 2020.",
        "art-red-extract")

    with pytest.raises(AssertionError):
        observation = _inspect(invoker, f"evidence/{row['artifact_id']}",
                               key="inspect-red")
        assert _payload(observation)["facts"]["figures"], observation.detail


def test_red_proof_a_check_that_always_agrees_hides_a_wrong_total(
        rig, monkeypatch: pytest.MonkeyPatch) -> None:
    _conn, _store, invoker, _supply = rig
    monkeypatch.setattr(
        supply_module, "check_derivation",
        lambda statement, bases=(): ArithmeticVerdict(
            status="CONSISTENT", operator="sum", asserted="", computed=None,
            detail="stub"))
    with pytest.raises(AssertionError):
        payload = _payload(_check(
            invoker,
            "India 5,275,035 and Brazil 4,467,433, a total of 9,742,469.",
            key="check-red"))
        assert payload["status"] == "INCONSISTENT", payload


# ═══════════════ supply, plan, and grant authority ═══════════════


def test_every_supplied_capability_has_an_implementation(rig) -> None:
    _conn, _store, _invoker, supply = rig
    assert set(supply.implementations) == set(SUPPLIED_CAPABILITY_IDS)
    assert set(supply.registry.capability_ids()) == set(SUPPLIED_CAPABILITY_IDS)


def test_the_supplied_ids_name_the_egress_pair_and_the_falsification_trio() -> None:
    assert RESEARCH_CAPABILITY_IDS == ("source_fetch", "source_search")
    assert FALSIFICATION_CAPABILITY_IDS == (
        "contradiction_scan", "evidence_inspect", "statistic_check")
    assert SUPPLIED_CAPABILITY_IDS == (
        "contradiction_scan", "evidence_inspect", "source_fetch",
        "source_search", "statistic_check")


def _plan(supply: ResearchEgressSupply):
    return plan_capability_plane(
        load_profiles(), supplied=SUPPLIED_CAPABILITY_IDS, risks=RISKS,
        tool_sets=supply.tool_sets)


def test_the_plan_keeps_the_critic_and_verifier_and_withholds_the_rest(rig) -> None:
    _conn, _store, _invoker, supply = rig
    plan = _plan(supply)

    assert plan.profiles["critic"].tools == (
        "evidence_inspect", "contradiction_scan")
    assert plan.profiles["verifier"].tools == (
        "evidence_inspect", "statistic_check")
    assert plan.profiles["verifier"].model_policy.allows_tool_calls is True
    assert "tool_calls" in plan.profiles["verifier"].model_policy.structured_fields

    assert plan.grants["ADVERSARY"].tool_set_ids == frozenset(
        {FALSIFICATION_TOOL_SET_ID})
    assert plan.grants["RESEARCHER"].tool_set_ids == frozenset(
        {RESEARCH_EGRESS_TOOL_SET_ID})
    assert set(plan.grants) == {"ADVERSARY", "RESEARCHER"}

    withheld = {(item.agent_profile, item.profile, item.capability_id)
                for item in plan.withheld}
    assert withheld == {
        ("DIRECTOR", "planner", "graph_read"),
        ("DIRECTOR", "planner", "artifact_store"),
        ("DIRECTOR", "synthesizer", "artifact_store"),
        ("DIRECTOR", "synthesizer", "provenance_read"),
        ("IMPLEMENTER", "experimenter", "experiment_execute"),
        ("IMPLEMENTER", "experimenter", "artifact_store"),
    }
    assert "critic/evidence_inspect" not in plan.capability_line
    assert "withheld 6 declaration(s)" in plan.capability_line


def test_the_generated_tool_note_names_the_falsifiers_it_can_call(rig) -> None:
    _conn, _store, _invoker, supply = rig
    notes = build_capability_tool_notes(
        _plan(supply), supply, item_keys=TOOL_CALL_KEYS)

    assert "evidence_inspect" in notes["critic"]
    assert "contradiction_scan" in notes["critic"]
    assert "source_search" not in notes["critic"]
    assert "statistic_check" in notes["verifier"]


def test_a_grant_that_opens_only_egress_cannot_reach_a_falsifier(rig) -> None:
    _conn, store, invoker, _supply = rig
    row = _admit(store, b"India 5,275,035 cases.", "art-authority")
    result = _invoke(
        invoker, "evidence_inspect", {"ref": f"evidence/{row['artifact_id']}"},
        key="inspect-wrong-set", sets=(RESEARCH_EGRESS_TOOL_SET_ID,))
    assert isinstance(result, CapabilityRefusal), result
    assert result.code == "ROLE"
    assert "not reachable through any tool set" in result.detail


class _ToolThenRead:
    """A critic that calls the inspector on every tick, reading last tick's result."""

    def __init__(self, ref: str) -> None:
        self.ref = ref
        self.requests: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.requests.append(request)
        return ModelProposal(
            provider_id="script", model_id="script", tier="m",
            profile=request.profile,
            lease_generation=request.lease_generation,
            structured={"tool_calls": [{
                "capability_id": "evidence_inspect",
                "arguments": {"ref": self.ref},
                "rationale": "read the admitted artifact before judging it",
            }]})


def test_a_critic_run_reads_the_tool_result_on_the_next_tick(rig) -> None:
    _conn, store, _invoker, supply = rig
    row = _admit(
        store,
        b"Hubei averted 1,200 cases between 23 January 2020 and "
        b"2 February 2020.",
        "art-critic-tick")
    plan = _plan(supply)
    model = _ToolThenRead(f"evidence/{row['artifact_id']}")
    runtime = AgentRuntime(
        model=model,
        orchestration=lambda intent: None,
        capabilities=_invoker,
        profiles=plan.profiles,
        grants=plan.grants)
    runtime.run("critic", TaskContext(
        task_id="t1", project_id=PROJECT, lease_generation="gen",
        limits=RunLimits(max_ticks=3, max_tool_calls=4)))

    assert len(model.requests) == 3
    first = "\n".join(part.text for part in model.requests[0].prompt)
    second = "\n".join(part.text for part in model.requests[1].prompt)
    # The first prompt cannot contain the fact: the tool has not run yet.
    assert "1,200" not in first
    # The second does, through the retained feedback envelope.
    assert "Hubei" in second and "1,200" in second
    assert any(part.origin == "runtime.observation"
               for part in model.requests[1].prompt)


def test_the_falsification_set_is_its_own_declared_composition(rig) -> None:
    _conn, _store, _invoker, supply = rig
    sets = {declared.set_id: declared for declared in supply.tool_sets}
    assert set(sets) == {RESEARCH_EGRESS_TOOL_SET_ID,
                         FALSIFICATION_TOOL_SET_ID}
    assert sets[FALSIFICATION_TOOL_SET_ID].capability_ids == (
        FALSIFICATION_CAPABILITY_IDS)
    assert sets[RESEARCH_EGRESS_TOOL_SET_ID].capability_ids == (
        RESEARCH_CAPABILITY_IDS)
    # The two compositions are disjoint: opening one never opens the other.
    assert not set(sets[FALSIFICATION_TOOL_SET_ID].capability_ids) & set(
        sets[RESEARCH_EGRESS_TOOL_SET_ID].capability_ids)


def test_a_batch_over_the_scan_cap_is_refused_not_truncated(rig) -> None:
    """Thirteen claims used to report thirteen and analyse twelve.

    The thirteenth was dropped silently, so a conflict between the first and
    the thirteenth came back as "no conflict found" — a false pass on the most
    damaging input the capability has.
    """
    _conn, _store, invoker, _supply = rig
    neutral = [f"Japan {100 + index} cases on 1 January 2021." for index in range(11)]
    statements = (["India 5,275,035 cases on 18 September 2020."] + neutral
                  + ["India 5,275,045 cases on 18 September 2020."])
    assert len(statements) == 13

    payload = _payload(_invoke(invoker, "contradiction_scan",
                               {"statements": statements}, key="scan-over-cap"))
    assert payload["status"] == "REFUSED"
    assert payload["code"] == SCAN_TOO_MANY_CLAIMS


def test_a_batch_at_the_scan_cap_is_analysed(rig) -> None:
    # The control: the refusal is a cap, not a wall.
    _conn, _store, invoker, _supply = rig
    neutral = [f"Japan {100 + index} cases on 1 January 2021." for index in range(10)]
    statements = (["India 5,275,035 cases on 18 September 2020."] + neutral
                  + ["India 5,275,045 cases on 18 September 2020."])
    assert len(statements) == 12

    payload = _payload(_invoke(invoker, "contradiction_scan",
                               {"statements": statements}, key="scan-at-cap"))
    assert payload.get("status") != "REFUSED"
    assert payload["conflicts"], "the first and last claim conflict"


class TestTheEntityIsTheNameNotTheDate:
    """A figure binds to a name. Months and weekdays are capitalised too.

    "On 18 September 2020, India reported 5,275,035" bound the figure to
    *September*, so a swap between two countries on the same date produced no
    conflict — a false pass. Three rules were wrong: the entity was the first
    capitalised token rather than the last; a window ending at a clause break
    had an empty last part; and `|` did not end a clause, so a table row bled
    into the one above it.
    """

    def test_a_date_first_sentence_binds_the_name(self) -> None:
        facts = facts_in("On 18 September 2020, India reported 5,275,035 cases.")
        assert [(f.value, f.entity) for f in facts.figures] == [(5275035.0, "India")]

    def test_a_newline_row_binds_its_own_cell(self) -> None:
        table = ("Week ending 1 September 2020\nIndia\n5,275,035\n"
                 "Brazil\n4,467,433\n")
        facts = facts_in(table)
        assert [(f.value, f.entity) for f in facts.figures] == [
            (5275035.0, "India"), (4467433.0, "Brazil")]

    def test_a_pipe_row_binds_its_own_cell(self) -> None:
        table = ("Week ending 1 September 2020 | India | 5,275,035 | "
                 "Brazil | 4,467,433")
        facts = facts_in(table)
        assert [(f.value, f.entity) for f in facts.figures] == [
            (5275035.0, "India"), (4467433.0, "Brazil")]

    def test_a_sentence_initial_adjective_is_not_the_name(self) -> None:
        # "New cases in Brazil" bound to "New".
        facts = facts_in("New cases in Brazil reached 4,467,433.")
        assert [(f.value, f.entity) for f in facts.figures] == [(4467433.0, "Brazil")]

    def test_a_possessive_is_the_same_name(self) -> None:
        # "India's" and "India" were different entities — a false refusal.
        facts = facts_in("India's tally was 5,275,045 cases.")
        assert [(f.value, f.entity) for f in facts.figures] == [(5275045.0, "India")]

    def test_a_swap_on_one_date_is_now_a_conflict(self) -> None:
        # The false pass this class exists for.
        found = conflicts_between((
            ClaimText("a", "On 18 September 2020, India reported 5,275,035 cases."),
            ClaimText("b", "On 18 September 2020, Brazil reported 5,275,035 cases."),
        ))
        assert [conflict.kind for conflict in found] == ["ATTRIBUTION"]


def test_a_clock_time_is_not_three_figures() -> None:
    """The inspection parser split `09:50:45` into 9, 50 and 45.

    The same defect as the gate's, in the other parser — the LIGO capture
    exposed both at once because its abstract opens with a timestamp.
    """
    facts = facts_in("at 09:50:45 UTC the signal sweeps from 35 to 250 Hz")
    assert [figure.value for figure in facts.figures] == [35.0, 250.0]
