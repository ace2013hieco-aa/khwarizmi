"""OPS-5Z — the false passes the three audits found, except the one that is a gate.

The triage (`docs/OPS-5Z-TRIAGE.md`) calls a *false pass* a wrong answer
reported as correct. Seven of the eight are closed here, each with a test, and
each new rule carries a red proof: stub the rule out and the same assertion
fails. The eighth (E1, a reported conflict with no consequence) is reclassified
as a design gate: the semantics are decided — record, never force — but the
only honest mechanism changes the capability plane's frozen output shape,
which the eval matrix and the closed-observation tests refuse without a design
decision. Its argument is in the triage, not simulated here.

The cases that matter most are the **near misses**. A contradiction rule that
fires on everything is worse than no rule, so the ordering tests pin the
sentences the rule must leave alone: different months, different dates, the
same ordering twice, and a single sentence that states a change rather than a
contradiction. The audit's own false-positive sentence
(``"Brazil was ahead of India in September but behind in October"``) is used
verbatim, not composed to fit the rule.

The content tests use the real 33,727-byte OpenAlex record the fetch path
actually returns. The Crossref, wrapper and PubMed shapes are built here from
the audit's description because no fixture for them exists in the repository.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Iterable

import pytest

from hermes.artifacts.store import ArtifactStore
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
from hermes.research import capability_supply as supply_module
from hermes.research import inspection as inspection_module
from hermes.research.capability_supply import (
    FALSIFICATION_TOOL_SET_ID,
    build_research_egress_supply,
)
from hermes.research.inspection import (
    ClaimText,
    conflicts_between,
    describe_inspection,
    facts_in,
    filter_inspection,
)
from hermes.research.live_fetch import ALLOWLIST_HOSTS, build_live_fetch_wiring
from hermes.tools.capabilities.content import read_content, semantic_text
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.types import (
    InvokeRequest,
    Observation,
    RiskLevel,
    ToolGrant,
)

CLOCK = "2026-10-30T14:00:00.000000+00:00"
PROJECT = "p-ops5z-audit"
PROFILE = "ADVERSARY"
FIXTURES = Path(__file__).parent / "fixtures" / "source_payloads"
OPENALEX_WORK = FIXTURES / "openalex_work_33727.json"

#: The audit's B1: two orderings, no comparable per-entity figure on one side.
B1 = [
    ("A", "Brazil was ahead of India on 1 September 2020."),
    ("B", "India led Brazil by 300,000 on 1 September 2020."),
]

#: The audit's B2: a claim and its negation.
B2 = [
    ("A", "Brazil was ahead of India."),
    ("B", "Brazil was not ahead of India."),
]

#: The audit's B3: the same quantity, two spellings.
B3 = [
    ("A", "India 5,275,035 cases on 18 September 2020."),
    ("B", "Brazil 5.275035 million cases on 18 September 2020."),
]


class Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 1000.0


def _scan_pure(pairs: Iterable[tuple[str, str]]):
    return conflicts_between([ClaimText(ref, text) for ref, text in pairs])


def _kinds(pairs: Iterable[tuple[str, str]]) -> list[str]:
    return [conflict.kind for conflict in _scan_pure(pairs)]


# ═══════════════════════ the capability rig ═══════════════════════


class Rig:
    def __init__(self, conn: Any, store: ArtifactStore,
                 supply: Any) -> None:
        self.conn = conn
        self.store = store
        self.supply = supply
        self.invoker = CapabilityInvoker(
            registry=supply.registry,
            implementations=supply.implementations,
            clock=Clock(),
            ledger=InMemoryIdempotencyLedger(),
            sandbox_enabled=False)

    def invoke(self, capability_id: str, arguments: dict[str, Any], *,
               key: str) -> Observation:
        result = self.invoker.invoke(InvokeRequest(
            capability_id=capability_id,
            arguments=arguments,
            idempotency_key=key,
            lease_generation="lease-ops5z-audit",
            profile=PROFILE,
            rationale="falsify the claim before accepting it",
            grant=ToolGrant(
                grant_id="grant.ops5z-audit",
                profile=PROFILE,
                tool_set_ids=frozenset({FALSIFICATION_TOOL_SET_ID}),
                max_risk=RiskLevel.LOW.value),
            deadline_seconds=10.0))
        assert isinstance(result, Observation), result
        assert result.ok(), result.detail
        return result

    def scan(self, pairs: Iterable[tuple[str, str]], *, key: str) -> Observation:
        items = list(pairs)
        return self.invoke(
            "contradiction_scan",
            {"refs": [ref for ref, _ in items],
             "statements": [text for _, text in items]},
            key=key)

    def inspect(self, ref: str, *, key: str) -> Observation:
        return self.invoke("evidence_inspect", {"ref": ref}, key=key)

    def admit(self, data: bytes, artifact_id: str, *,
              content_format: str = "") -> dict[str, Any]:
        metadata = ({"content_format": content_format}
                    if content_format else None)
        return self.store.write(
            data, "source_payload", "test.ops5z-audit", project_id=PROJECT,
            artifact_id=artifact_id, metadata=metadata)


@pytest.fixture
def rig(tmp_path: Path):
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create(PROJECT, "OPS-5Z audit")
    store = ArtifactStore(
        str(tmp_path / "store"),
        ArtifactRepository(conn, lambda: CLOCK),
        clock=lambda: CLOCK)
    wiring = build_live_fetch_wiring(conn, store, lambda: CLOCK)
    supply = build_research_egress_supply(
        conn=conn, store=store, clock=lambda: CLOCK, project_id=PROJECT,
        machinery=wiring.machinery, allowlist=ALLOWLIST_HOSTS)
    yield Rig(conn, store, supply)
    conn.close()


def _payload(observation: Observation) -> dict[str, Any]:
    assert observation.payload is not None
    return json.loads(observation.payload.text)


# ═══════════════ A1 — the conflict cap reports what it cut ═══════════════


def _many_conflicts() -> list[tuple[str, str]]:
    """Twelve claims, every pair a QUANTITY conflict: 66 in total."""
    return [(f"c{index}", f"India {100 + index} cases on 18 September 2020.")
            for index in range(12)]


def _assert_the_conflict_cap_is_reported(observation: Observation) -> None:
    payload = _payload(observation)
    assert payload["conflicts_total"] == 66
    assert len(payload["conflicts"]) == 16
    assert payload["truncated"] is True
    assert "showing 16 of 66" in observation.detail


def test_the_conflict_cap_reports_the_total_it_did_not_return(rig) -> None:
    observation = rig.scan(_many_conflicts(), key="a1-truncated")
    _assert_the_conflict_cap_is_reported(observation)


def test_the_scan_within_the_cap_says_it_is_not_truncated(rig) -> None:
    observation = rig.scan(B2, key="a1-complete")
    payload = _payload(observation)
    assert payload["conflicts_total"] == len(payload["conflicts"]) == 1
    assert payload["truncated"] is False
    assert "showing" not in observation.detail


def test_red_proof_without_the_total_the_cap_looks_complete(
        rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The old scanner returned the prefix; the payload claimed 16 conflicts."""
    real = inspection_module.conflicts_between
    monkeypatch.setattr(
        supply_module, "conflicts_between",
        lambda claims: real(claims)[:inspection_module.MAX_CONFLICTS])
    with pytest.raises(AssertionError):
        _assert_the_conflict_cap_is_reported(
            rig.scan(_many_conflicts(), key="a1-red"))


# ═══════════════ A2 — the figure cap sets the flag it has ═══════════════


def _seventy_figures() -> str:
    return ". ".join(f"Entity{index} reported {1000 + index} cases"
                     for index in range(70)) + "."


def _assert_the_figure_cap_is_reported(inspection) -> None:
    assert len(inspection.figures) == 64
    assert inspection.truncated is True
    assert inspection.figures_truncated is True
    assert inspection.window_truncated is False


def test_seventy_figures_set_the_truncation_flag() -> None:
    inspection = facts_in(_seventy_figures())
    _assert_the_figure_cap_is_reported(inspection)


def test_the_figure_cap_reaches_the_payload_and_the_note(rig) -> None:
    row = rig.admit(_seventy_figures().encode("utf-8"), "art-seventy")
    observation = rig.inspect(f"evidence/{row['artifact_id']}", key="a2-payload")
    payload = _payload(observation)
    facts = payload["facts"]
    assert len(facts["figures"]) == 64
    assert facts["truncated"] is True
    assert facts["figures_truncated"] is True
    assert facts["window_truncated"] is False
    assert "figures capped at 64" in observation.detail
    # The note must not blame the text window: every character was read.
    assert "read first" not in observation.detail


def test_a_filtered_view_does_not_say_the_source_stated_no_figure() -> None:
    inspection = filter_inspection(facts_in(_seventy_figures()), ["Nowhere"])
    assert inspection.figures == ()
    assert inspection.figures_truncated is True
    note = describe_inspection(inspection, "art-filtered")
    assert "no date, figure" in note
    assert "capped at 64" in note


def test_a_long_text_and_a_figure_cap_are_named_separately() -> None:
    figures = ". ".join(f"Entity{index} reported {1000 + index} cases"
                        for index in range(70))
    inspection = facts_in(figures + " " + "x" * (
        inspection_module.MAX_ANALYSIS_CHARS + 10))
    assert inspection.window_truncated is True
    assert inspection.figures_truncated is True
    assert inspection.truncated is True


def test_red_proof_without_the_figure_flag_the_payload_looks_complete(
        rig, monkeypatch: pytest.MonkeyPatch) -> None:
    real = inspection_module.facts_in

    def unflagged(text: str):
        return dataclasses.replace(
            real(text), truncated=False, figures_truncated=False,
            window_truncated=False)

    monkeypatch.setattr(supply_module, "facts_in", unflagged)
    row = rig.admit(_seventy_figures().encode("utf-8"), "art-seventy-red")
    observation = rig.inspect(f"evidence/{row['artifact_id']}", key="a2-red")
    with pytest.raises(AssertionError):
        facts = _payload(observation)["facts"]
        assert facts["truncated"] is True


# ═══════════════ B1/B2 — orderings the numeric rules cannot see ═══════════════


def test_an_ordering_conflict_with_no_per_entity_figures_is_reported() -> None:
    found = _scan_pure(B1)
    assert [conflict.kind for conflict in found] == ["ORDER"]
    assert "Brazil" in found[0].subject and "India" in found[0].subject
    assert "2020-09-01" in found[0].date


def test_a_claim_and_its_negation_is_reported() -> None:
    found = _scan_pure(B2)
    assert [conflict.kind for conflict in found] == ["ORDER"]
    assert "not" in found[0].detail


def test_a_preposed_negation_is_read() -> None:
    found = _scan_pure([
        ("A", "It is not the case that Brazil was ahead of India."),
        ("B", "Brazil led India."),
    ])
    assert [conflict.kind for conflict in found] == ["ORDER"]


def test_both_negated_relations_can_hold_together() -> None:
    # "not ahead" and "not behind" are both true when the two are equal.
    assert _kinds([
        ("A", "Brazil was not ahead of India."),
        ("B", "Brazil was not behind India."),
    ]) == []


def test_a_negated_relation_is_not_reversed_into_its_opposite() -> None:
    # "did not lead" is not "India led Brazil"; only the negation of ahead.
    assert _kinds([
        ("A", "Brazil led India."),
        ("B", "Brazil did not lead India."),
    ]) == ["ORDER"]


def test_the_audit_false_positive_sentence_does_not_contradict_itself() -> None:
    """The audit's named trap, verbatim.

    "Brazil was ahead of India in September but behind in October" states a
    change. A rule that reads both clauses as one undated assertion calls the
    sentence a contradiction with itself. This rule compares *different*
    claims, and keeps month scopes apart.
    """
    assert _kinds([(
        "A", "Brazil was ahead of India in September but behind in October.")]) == []
    # Two claims about different months are a change too, not a conflict.
    assert _kinds([
        ("A", "Brazil was ahead of India in September."),
        ("B", "Brazil was behind India in October."),
    ]) == []
    # Two claims about different days are not a conflict.
    assert _kinds([
        ("A", "Brazil was ahead of India on 1 September 2020."),
        ("B", "Brazil was behind India on 1 October 2020."),
    ]) == []


def test_a_bare_month_does_not_answer_a_dated_claim() -> None:
    # "in September" cannot be proven the same instant as 1 September.
    assert _kinds([
        ("A", "Brazil was ahead of India in September."),
        ("B", "Brazil was behind India on 1 September 2020."),
    ]) == []


def test_the_same_ordering_stated_twice_is_not_a_conflict() -> None:
    assert _kinds([
        ("A", "Brazil was ahead of India."),
        ("B", "Brazil led India."),
    ]) == []


def test_a_month_scope_still_conflicts_on_that_month() -> None:
    # The control for the near miss: the same month does conflict.
    assert _kinds([
        ("A", "Brazil was ahead of India in September."),
        ("B", "India led Brazil in September."),
    ]) == ["ORDER"]


def test_a_real_repository_sentence_is_read_and_not_composed_to_fit() -> None:
    """An ordering sentence this rule was not designed around.

    Verbatim from ``docs/OPS-5Z-DESIGN.md``, including the prose line wrap
    between the two names. The relation is ``overtook`` and the scope is a bare
    month after the object — neither is the shape the B1/B2 tests use.
    """
    sentence = (
        "India overtook\nBrazil on 7 September, so the ordering was correct "
        "for the date the model used and wrong only for the date asked.")
    # The line wrap does not swallow the month after the object.
    found = _scan_pure([
        ("A", sentence),
        ("B", "India trailed Brazil in September."),
    ])
    assert [conflict.kind for conflict in found] == ["ORDER"]
    assert "september" in found[0].date.casefold()

    # The same real sentence against a compatible reading is silent.
    assert _kinds([
        ("A", sentence),
        ("B", "Brazil was behind India in September."),
    ]) == []


def test_red_proof_without_the_ordering_rule_b1_and_b2_are_false_passes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        inspection_module, "_order_statement_conflicts",
        lambda analysed: [])
    assert _kinds(B1) == []
    assert _kinds(B2) == []
    with pytest.raises(AssertionError):
        assert [conflict.kind for conflict in _scan_pure(B1)] == ["ORDER"]


def test_the_capability_payload_carries_the_three_new_conflict_shapes(rig) -> None:
    """B1, B2 and B3 through the shipped executor, not only the pure rule."""
    expected = (("b1", B1, "ORDER"), ("b2", B2, "ORDER"),
                ("b3", B3, "ATTRIBUTION"))
    for name, pairs, kind in expected:
        observation = rig.scan(pairs, key=f"new-shape-{name}")
        payload = _payload(observation)
        assert payload["conflicts_total"] == 1, (name, payload)
        assert payload["truncated"] is False, name
        assert [item["kind"] for item in payload["conflicts"]] == [kind], name
        assert kind in observation.detail, name


# ═══════════════ B3 — the same quantity, two spellings ═══════════════


def test_a_decimal_magnitude_is_the_same_quantity_as_grouped_digits() -> None:
    facts = {
        text: facts_in(text).figures[0]
        for _ref, text in B3
    }
    india = facts[B3[0][1]]
    brazil = facts[B3[1][1]]
    assert india.canonical == brazil.canonical == 5_275_035.0
    assert india.literal != brazil.literal

    found = _scan_pure(B3)
    assert [conflict.kind for conflict in found] == ["ATTRIBUTION"]
    assert "5,275,035" in found[0].detail
    assert "5.275035 million" in found[0].detail


def test_a_scale_suffix_on_the_same_entity_is_a_quantity_conflict() -> None:
    assert _kinds([
        ("A", "Brazil 1 million cases on 18 September 2020."),
        ("B", "Brazil 2 million cases on 18 September 2020."),
    ]) == ["QUANTITY"]


def test_red_proof_with_literal_comparison_b3_is_a_false_pass(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The shipped rule compared literals; the two spellings never met."""
    # `_same_number` is the canonical comparison. Without it, 5,275,035 and
    # 5.275035 million are two different numbers — the old literal guard.
    monkeypatch.setattr(inspection_module, "_same_number",
                        lambda left, right: False)
    assert _kinds(B3) == []
    with pytest.raises(AssertionError):
        assert [conflict.kind for conflict in _scan_pure(B3)] == [
            "ATTRIBUTION"]


# ═══════════════ C1–C3 / D1 — metadata is not content ═══════════════

#: Constructed from the audit's description; no Crossref fixture exists here.
CROSSREF = json.dumps({
    "status": "ok",
    "message": {
        "title": ["Containment estimates for COVID-19"],
        "abstract": ("<jats:p>Hubei averted 1,200 cases between "
                     "23 January 2020 and 2 February 2020.</jats:p>"),
        "issued": {"date-parts": [[2020, 9, 18]]},
        "is-referenced-by-count": 34,
        "DOI": "10.1234/example",
    },
}).encode("utf-8")

#: Constructed from the audit's description (PubMed is a supported provider).
PUBMED = b"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticle>
  <MedlineCitation>
    <PMID>32456789</PMID>
    <Article>
      <Journal><JournalIssue><PubDate><Year>2020</Year><Month>Sep</Month>
        <Day>18</Day></PubDate></JournalIssue></Journal>
      <ArticleTitle>Containment estimates</ArticleTitle>
      <Abstract><AbstractText>Hubei averted 1,200 cases between
        23 January 2020 and 2 February 2020.</AbstractText></Abstract>
    </Article>
  </MedlineCitation>
</PubmedArticle>
"""

#: A record carrying both spellings of the same abstract (D1).
DUPLICATE_ABSTRACT = json.dumps({
    "title": "T",
    "abstract": "Hubei averted 1,200 cases on 23 January 2020.",
    "abstract_inverted_index": {
        "Hubei": [0], "averted": [1], "1,200": [2], "cases": [3],
        "on": [4], "23": [5], "January": [6], "2020.": [7],
    },
}).encode("utf-8")


def test_a_crossref_record_is_read_field_wise_not_mined() -> None:
    read = read_content(CROSSREF, format="crossref")
    assert read.state == "content"
    assert read.fields == ("title", "abstract")
    assert "is-referenced-by-count" not in read.text
    assert "2020-09-18" not in read.text

    facts = facts_in(read)
    assert [figure.literal for figure in facts.figures] == ["1,200"]
    assert [figure.entity for figure in facts.figures] == ["Hubei"]
    assert {date.iso for date in facts.dates} == {
        "2020-01-23", "2020-02-02"}


def test_the_real_openalex_work_inside_a_search_wrapper_is_not_metadata() -> None:
    work = json.loads(OPENALEX_WORK.read_text(encoding="utf-8"))
    wrapper = json.dumps({
        "meta": {"count": 1, "page": 1, "per_page": 25},
        "results": [work],
    }).encode("utf-8")

    read = read_content(wrapper, format="openalex")
    assert read.state == "content"
    assert read.fields == ("title", "display_name", "abstract")
    assert work["publication_date"] not in read.text
    assert '"cited_by_count"' not in read.text

    facts = facts_in(read)
    assert facts.figures == ()
    assert facts.dates == ()


def test_pubmed_xml_is_read_field_wise_not_tag_stripped() -> None:
    read = read_content(PUBMED, format="pubmed")
    assert read.state == "content"
    assert read.fields == ("title", "abstract")
    # The PMID and the publication date are metadata, not prose.
    assert "32456789" not in read.text
    assert "Sep" not in read.text

    facts = facts_in(read)
    assert [figure.literal for figure in facts.figures] == ["1,200"]
    assert [figure.entity for figure in facts.figures] == ["Hubei"]
    assert {date.iso for date in facts.dates} == {
        "2020-01-23", "2020-02-02"}


def test_an_unmodelled_xml_document_is_not_content() -> None:
    read = read_content(
        b'<?xml version="1.0"?><crossref><published>2020-09-18</published>'
        b"<count>34</count></crossref>", format="crossref")
    assert read.state == "unreadable"
    assert read.fields == ()
    assert "does not parse as JSON" in read.detail


def test_a_record_that_carries_both_abstracts_states_it_once() -> None:
    read = read_content(DUPLICATE_ABSTRACT, format="openalex")
    assert read.state == "content"
    assert read.fields == ("title", "abstract")
    assert read.text.count("1,200") == 1
    facts = facts_in(read)
    assert [figure.literal for figure in facts.figures] == ["1,200"]
    assert len(facts.dates) == 1


def test_evidence_inspect_over_a_crossref_artifact_reports_no_metadata(
        rig) -> None:
    row = rig.admit(CROSSREF, "art-crossref", content_format="crossref")
    observation = rig.inspect(f"evidence/{row['artifact_id']}",
                              key="c1-inspect")
    payload = _payload(observation)
    assert payload["read"]["fields"] == ["title", "abstract"]
    assert [figure["literal"] for figure in payload["facts"]["figures"]] == [
        "1,200"]


def test_a_wrapper_with_no_content_field_is_unreadable_not_prose() -> None:
    read = read_content(json.dumps({"meta": {"count": 0}, "results": []})
                        .encode("utf-8"), format="openalex")
    assert read.state == "unreadable"
    assert read.fields == ()
    assert "no content field" in read.detail


def test_the_generic_content_reader_still_reads_plain_text() -> None:
    # The control against "refuse everything": plain text is still content.
    read = read_content(b"Hubei averted 1,200 cases.")
    assert read.state == "content"
    assert read.fields == ("text",)
    assert semantic_text(b"Hubei averted 1,200 cases.").text == (
        "Hubei averted 1,200 cases.")
