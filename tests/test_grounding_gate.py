"""The grounding gate's falsifiers, including the two binding bugs found by
building realistic fixtures rather than reasoning about them."""

from __future__ import annotations

from hermes.research.grounding import (
    CaveatCode,
    RefusalCode,
    check_claim,
    figures_in,
)

# The published WHO figures for 1 September 2020 — Brazil ahead of India.
ARTIFACT = (
    "By 1 September 2020 the cumulative confirmed case counts reported to WHO "
    "stood at 3,959,158 in Brazil and 3,769,523 in India."
)
SUBJECTS = ("Brazil", "India")

# The claim a live run actually made: wrong magnitudes, reversed ordering.
REVERSED = "India 5,275,035, Brazil 4,467,433 as of that date."


class TestTheFalsifiers:
    def test_the_reversed_claim_is_refused(self) -> None:
        verdict = check_claim(REVERSED, ARTIFACT, subjects=SUBJECTS)
        assert verdict.grounded is False
        assert verdict.refusal is RefusalCode.ASSERTION_NOT_FOUND
        assert "India" in verdict.detail

    def test_the_correct_claim_is_grounded(self) -> None:
        claim = "Brazil 3,959,158, India 3,769,523 as of that date."
        verdict = check_claim(claim, ARTIFACT, subjects=SUBJECTS)
        assert verdict.grounded is True
        assert verdict.refusal is None and verdict.caveat is None

    def test_a_qualitative_claim_is_caveated_not_refused(self) -> None:
        verdict = check_claim("Brazil's trajectory was steeper.", ARTIFACT,
                              subjects=SUBJECTS)
        assert verdict.grounded is False
        assert verdict.refusal is None
        assert verdict.caveat is CaveatCode.NO_CHECKABLE_ASSERTION

    def test_no_bytes_is_caveated_not_grounded(self) -> None:
        verdict = check_claim("Brazil 3,959,158.", None, subjects=SUBJECTS)
        assert verdict.grounded is False
        assert verdict.caveat is CaveatCode.UNCHECKED_NO_BYTES

    def test_a_numeral_with_no_subject_is_refused(self) -> None:
        verdict = check_claim("The total reached 3,959,158.", ARTIFACT,
                              subjects=SUBJECTS)
        assert verdict.refusal is RefusalCode.UNATTRIBUTED_NUMERAL


class TestTheBindingBugs:
    """Both surfaced while building fixtures. Both are real."""

    def test_a_subject_after_its_figure_still_binds(self) -> None:
        # Forward-only binding refused this shape.
        text = "3,959,158 cases were confirmed in Brazil by that date."
        verdict = check_claim(text, ARTIFACT, subjects=SUBJECTS)
        assert verdict.grounded is True, verdict.detail

    def test_coordination_breaks_the_binding(self) -> None:
        # Distance-only binding attributed BOTH figures to Brazil, because
        # Brazil is the nearest preceding mention for the second one.
        claim = "3,959,158 in Brazil and 3,769,523 in India"
        verdict = check_claim(claim, ARTIFACT, subjects=SUBJECTS)
        assert verdict.grounded is True, verdict.detail

    def test_the_coordination_case_still_catches_a_swap(self) -> None:
        # The same shape with the figures swapped must fail, or the rule above
        # would have made the gate blind to exactly the case it exists for.
        claim = "3,769,523 in Brazil and 3,959,158 in India"
        verdict = check_claim(claim, ARTIFACT, subjects=SUBJECTS)
        assert verdict.refusal is RefusalCode.ASSERTION_NOT_FOUND


class TestWhatCountsAsAnAssertion:
    def test_a_year_is_not_an_assertion(self) -> None:
        # Counting "2020" would send a qualitative claim down the refusal path.
        assert figures_in("on 1 September 2020") == ()

    def test_thousands_separators_normalise(self) -> None:
        for raw in ("3,959,158", "3959158", "3 959 158"):
            assert figures_in(raw)[0].value == 3959158.0

    def test_a_decimal_keeps_its_scale(self) -> None:
        # This used to assert 3.96 — the unit-blind parse, pinned as correct.
        # "3.96 million" is 3,960,000; a claim written that way was refused
        # against an artifact stating the full number.
        assert figures_in("3.96 million")[0].value == 3_960_000.0

    def test_a_decimal_without_a_scale_is_unchanged(self) -> None:
        assert figures_in("the rate was 3.96")[0].value == 3.96


class TestDeterminism:
    def test_same_inputs_same_verdict(self) -> None:
        first = check_claim(REVERSED, ARTIFACT, subjects=SUBJECTS)
        second = check_claim(REVERSED, ARTIFACT, subjects=SUBJECTS)
        assert first == second

    def test_the_gate_contacts_nothing(self, monkeypatch) -> None:
        # A gate that needed a provider could not be replayed; this proves the
        # decision path never reaches the network.
        import socket

        def refuse(*args, **kwargs):
            raise AssertionError("the gate attempted a network call")

        monkeypatch.setattr(socket, "socket", refuse)
        assert check_claim(REVERSED, ARTIFACT, subjects=SUBJECTS).refusal


class TestTheEscapeHatch:
    """A discarded numeral is indistinguishable from an absent one, so a
    tokeniser bug becomes a caveat instead of a refusal. Each of these was one."""

    def test_may_is_a_modal_verb_not_a_month(self) -> None:
        # "may" matched the month and dropped the figure in front of it, so a
        # wrong number was caveated as qualitative rather than refused.
        assert figures_in("Brazil 9,999,999 may be an undercount.")
        verdict = check_claim("Brazil 9,999,999 may be an undercount.",
                              "Brazil 3,959,158 in total.", subjects=("Brazil",))
        assert verdict.refusal is RefusalCode.ASSERTION_NOT_FOUND

    def test_a_capitalised_month_is_still_a_date(self) -> None:
        assert figures_in("on 1 September 2020") == ()
        assert figures_in("September 1, 2020") == ()

    def test_a_blank_subject_name_does_not_hang(self) -> None:
        # An empty name matched at every offset and never advanced the scan:
        # the call never returned. A hang is the absence of a verdict.
        verdict = check_claim("Brazil 3,959,158.", "Brazil 3,959,158.",
                              subjects=("Brazil", ""))
        assert verdict.grounded is True

    def test_a_disease_name_is_not_a_quantity(self) -> None:
        # COVID-19's 19 was read as an assertion and refused correct prose.
        assert figures_in("COVID-19 cases rose.") == ()

    def test_an_ordinal_is_not_a_count(self) -> None:
        assert figures_in("the 2nd wave") == ()


class TestTheDateCheck:
    """The gap the incident actually fell through, now closed.

    The model's figures were real — an 18 September 2020 snapshot — asserted
    against a question about 1 September. Binding cannot see that: every figure
    is present and bound to the right country. A date comparison can.
    """

    SEPT_18 = ("On 18 September 2020 the cumulative confirmed counts stood at "
               "5,275,035 in India and 4,467,433 in Brazil.")
    CLAIM = "India 5,275,035, Brazil 4,467,433 as of 1 September 2020."

    def test_the_incident_is_refused_on_its_date(self) -> None:
        verdict = check_claim(self.CLAIM, self.SEPT_18,
                              subjects=("Brazil", "India"))
        assert verdict.refusal is RefusalCode.DATE_MISMATCH
        assert "2020-09-01" in verdict.detail
        assert "2020-09-18" in verdict.detail

    def test_the_same_figures_with_the_right_date_are_grounded(self) -> None:
        # The control: the date is what decides, not the figures.
        right = self.SEPT_18.replace("18 September", "1 September")
        verdict = check_claim(self.CLAIM, right, subjects=("Brazil", "India"))
        assert verdict.grounded is True, verdict.detail

    def test_an_undated_source_is_caveated_not_refused(self) -> None:
        verdict = check_claim(self.CLAIM, "5,275,035 in India, 4,467,433 in Brazil.",
                              subjects=("Brazil", "India"))
        assert verdict.refusal is None
        assert verdict.caveat is CaveatCode.UNDATED_SOURCE

    def test_a_claim_without_a_date_is_unaffected(self) -> None:
        verdict = check_claim("Brazil 3,959,158.", self.SEPT_18,
                              subjects=("Brazil", "India"))
        assert verdict.refusal is RefusalCode.ASSERTION_NOT_FOUND

    def test_an_iso_date_matches_a_written_one(self) -> None:
        claim = "India 5,275,035, Brazil 4,467,433 as of 2020-09-18."
        verdict = check_claim(claim, self.SEPT_18, subjects=("Brazil", "India"))
        assert verdict.grounded is True, verdict.detail


class TestTheDateBindsToTheFigure:
    """The first date rule was containment again, one layer up.

    It asked whether the claim's date appeared *anywhere* in the artifact. A
    two-week table names both weeks, so the incident passed: the figures bound
    to 18 September while the claim's 1 September sat in the other sentence.
    """

    TWO_WEEKS = ("Week ending 1 September 2020: Brazil 3,862,311, "
                 "India 3,691,166. Week ending 18 September 2020: "
                 "India 5,275,035, Brazil 4,467,433.")
    CLAIM = "India 5,275,035 and Brazil 4,467,433 as of 1 September 2020."

    def test_a_two_week_table_does_not_pass_the_incident(self) -> None:
        verdict = check_claim(self.CLAIM, self.TWO_WEEKS,
                              subjects=("Brazil", "India"))
        assert verdict.refusal is RefusalCode.DATE_MISMATCH
        # The refusal names the date that actually dates the figure.
        assert "2020-09-18" in verdict.detail
        assert "2020-09-01" in verdict.detail

    def test_the_right_week_still_passes(self) -> None:
        one_week = "Week ending 1 September 2020: India 5,275,035, Brazil 4,467,433."
        verdict = check_claim(self.CLAIM, one_week,
                              subjects=("Brazil", "India"))
        assert verdict.grounded is True, verdict.detail

    def test_a_year_less_claim_is_still_checked(self) -> None:
        # "as of 1 September" produced no date at all and skipped the check.
        claim = "India 5,275,035 and Brazil 4,467,433 as of 1 September."
        verdict = check_claim(claim, self.TWO_WEEKS,
                              subjects=("Brazil", "India"))
        assert verdict.refusal is RefusalCode.DATE_MISMATCH

    def test_a_year_less_claim_matches_a_year_ful_artifact(self) -> None:
        one_week = "Week ending 1 September 2020: India 5,275,035, Brazil 4,467,433."
        claim = "India 5,275,035 and Brazil 4,467,433 as of 1 September."
        verdict = check_claim(claim, one_week, subjects=("Brazil", "India"))
        assert verdict.grounded is True, verdict.detail


class TestASecondTrueDateDoesNotRescue:
    """`any` over the claim's dates reopened the incident with a parenthetical.

    "… as of 1 September 2020 (published 18 September 2020)" matched the
    artifact's 18 September and passed a claim that is wrong about 1 September.
    The date is now bound on both sides: the date that dates the claim's figure
    must be the date that dates the artifact's figure.
    """

    TWO_WEEKS = ("Week ending 1 September 2020: Brazil 3,862,311, "
                 "India 3,691,166. Week ending 18 September 2020: "
                 "India 5,275,035, Brazil 4,467,433.")

    def test_the_parenthetical_does_not_rescue_the_claim(self) -> None:
        claim = ("India 5,275,035 and Brazil 4,467,433 as of 1 September 2020 "
                 "(published 18 September 2020).")
        verdict = check_claim(claim, self.TWO_WEEKS,
                              subjects=("Brazil", "India"))
        assert verdict.refusal is RefusalCode.DATE_MISMATCH

    def test_the_correct_date_still_passes(self) -> None:
        claim = ("India 5,275,035 and Brazil 4,467,433 as of 18 September "
                 "2020 (published 20 September 2020).")
        verdict = check_claim(claim, self.TWO_WEEKS,
                              subjects=("Brazil", "India"))
        assert verdict.grounded is True, verdict.detail


class TestTheScaleIsNotADifferentNumber:
    """`5.275035 million` and `5,275,035` are the same quantity.

    The scan was fixed to compare canonical values; the gate compared raw ones,
    so a claim written in millions was refused against an artifact written in
    full — the same defect, one seam over. It survived the slice that fixed the
    scan because the two code paths parse figures separately.
    """

    ARTIFACT = "Brazil 5,275,035 cases on 18 September 2020."

    def test_a_claim_in_millions_matches_a_full_precision_artifact(self) -> None:
        verdict = check_claim("Brazil 5.275035 million cases as of 18 September 2020.",
                              self.ARTIFACT, subjects=("Brazil",))
        assert verdict.grounded is True, verdict.detail

    def test_the_scale_is_folded_at_parse(self) -> None:
        assert [figure.value for figure in
                figures_in("Brazil 5.275035 million cases")] == [5275035.0]

    def test_a_wrong_scaled_claim_is_still_refused(self) -> None:
        # The control: folding must not make every scaled number match.
        verdict = check_claim("Brazil 5.9 million cases as of 18 September 2020.",
                              self.ARTIFACT, subjects=("Brazil",))
        assert verdict.refusal is RefusalCode.ASSERTION_NOT_FOUND


class TestAClockIsNotThreeNumbers:
    """`09:50:45` is one time, not three quantities.

    The LIGO abstract — captured from Crossref, arXiv and Semantic Scholar —
    opens "on September 14, 2015 at 09:50:45 UTC". Both figure parsers read that
    as 9, 50 and 45, so a claim asserting "50" could bind to the seconds field
    and ground against a timestamp. Found by reading the real capture, not by a
    fixture written for the rule.
    """

    def test_the_clock_yields_no_figures(self) -> None:
        assert figures_in("at 09:50:45 UTC") == ()

    def test_the_real_quantities_survive(self) -> None:
        assert [f.raw for f in
                figures_in("at 09:50:45 UTC the sweep is 35 to 250 Hz")] == [
                    "35", "250"]

    def test_a_short_clock_is_also_skipped(self) -> None:
        assert [f.raw for f in figures_in("at 5:30 the rate was 42")] == ["42"]


class TestAGroundedVerdictNamesItsEvidence:
    """`grounded: true` with an empty detail is a green badge.

    The end-to-end run found it: the journal recorded a grounded verdict and no
    statement of what it grounded on, so an operator could not tell which figure
    and which subject carried the check.
    """

    ARTIFACT = "India reported 5,275,035 cases on 18 September 2020."

    def test_the_detail_names_the_figure_and_the_date(self) -> None:
        verdict = check_claim("India 5,275,035 cases as of 18 September 2020.",
                              self.ARTIFACT, subjects=("India",))
        assert verdict.grounded is True
        assert verdict.detail, "a grounded verdict must say what it grounded on"
        assert "5,275,035" in verdict.detail
        assert "2020-09-18" in verdict.detail
        assert "India" in verdict.detail

    def test_every_figure_is_named(self) -> None:
        artifact = ("India reported 5,275,035 cases on 18 September 2020 and "
                    "Brazil 4,467,433.")
        verdict = check_claim("India 5,275,035 and Brazil 4,467,433 cases.",
                              artifact, subjects=("India", "Brazil"))
        assert verdict.grounded is True
        assert "5,275,035" in verdict.detail and "4,467,433" in verdict.detail
