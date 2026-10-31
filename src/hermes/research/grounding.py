"""Grounding: does the cited artifact actually say what the claim says?

A deterministic, model-free check. The architecture's rule is that models
propose and never decide; this gate decides something, so it must decide from
bytes, not from an opinion. No provider is contacted, no model is asked, and the
same inputs give the same verdict forever.

Why binding and not containment
-------------------------------
An artifact that names both Brazil and India contains both figures. A swapped
claim therefore *passes* a containment test — the numbers are both in the text,
just attached to the wrong countries. That is precisely the failure this exists
to catch: a run asserted "India 5,275,035, Brazil 4,467,433" where the published
ordering is the other way round. So a figure must bind to a *subject*, and the
claim is grounded only when each figure binds, in the artifact, to the subject
the claim attaches it to.

Three states, not two
---------------------
``grounded``   every figure in the claim was found, bound to the right subject;
               or the claim asserts no figure and quotes the artifact's own
               prose verbatim (a quotation is the source saying it).
``caveated``   nothing checkable was asserted (no numeral at all), no bytes
               were available to check against, or the bytes could not be read
               as content. The claim is admissible and *marked* — a caveat is
               not a pass, and never renders as one.
``refused``    a figure was asserted and not found, or a numeral could not be
               attributed to any subject.

The middle state is the dangerous one: a model can escape a refusal by deleting
its figures. `unattributed_numeral` closes the cheaper route (keeping the figure
and dropping the subject); `UNCHECKED_NO_BYTES` makes the other route visible
rather than silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

__all__ = [
    "CaveatCode",
    "GroundingVerdict",
    "RefusalCode",
    "check_claim",
    "figures_in",
]

#: How far from a figure its subject may sit, in characters. A sentence is
#: usually under 200; 400 covers a long clause without letting a figure drift
#: into the next paragraph's subject.
MAX_BINDING_DISTANCE = 400

#: Words that break a binding: a figure on one side of them does not attach to a
#: subject on the other. Without this, "3,959,158 in Brazil and 3,769,523 in
#: India" attributes both figures to Brazil — found while building the fixture,
#: not by reasoning about it.
_COORDINATION = re.compile(r"\b(and|vs\.?|versus|while|whereas)\b|[;]", re.I)

#: A space is a thousands separator only in a *grouped* numeral (``3 959 158``).
#: Allowing one anywhere inside a number made ``COVID-19 12,345`` a single match
#: starting at the disease name's ``19``; the preceding ``-`` then discarded the
#: whole match, and a fabricated figure was caveated as "nothing asserted".
#: The alternation keeps the grouped form and nothing looser.
_NUMBER = re.compile(r"\d{1,3}(?:[ \u00a0]\d{3})+|\d[\d,._]*\d|\d")
_ORDINAL = re.compile(r"(st|nd|rd|th)\b", re.I)
#: A magnitude word after a numeral multiplies it. `million` is a scale, not a
#: dimension: 5.275035 million and 5,275,035 are the same quantity.
_SCALES = {"thousand": 1_000.0, "million": 1_000_000.0,
           "billion": 1_000_000_000.0, "trillion": 1_000_000_000_000.0}
def _in_clock(text: str, start: int, end: int) -> bool:
    """Is this numeral part of a clock time — `09:50:45`, `5:30`?

    A time is one fact, not three. The LIGO abstract opens "on September 14,
    2015 at 09:50:45 UTC", and both figure parsers read that as 9, 50 and 45 —
    three quantities a claim could bind to and be "grounded" by.
    """
    before = text[start - 1] if start else ""
    after = text[end] if end < len(text) else ""
    return before == ":" or after == ":"

_SCALE = re.compile(r"\s*(thousand|million|billion|trillion)\b", re.I)
_YEAR = re.compile(r"^(19|20)\d{2}\Z")

#: A verbatim claim is grounded even without a figure: the source states it in
#: the same words. A quotation must at least be a clause — one or two words can
#: occur in any source and assert nothing.
MIN_QUOTATION_WORDS = 5

#: A numeral that is part of a date is not an assertion. "on 1 September 2020"
#: contains two numerals and asserts neither — treating them as figures would
#: send a qualitative claim down the refusal path instead of the caveat path.
#: Found by a test, not by reading: the year rule alone let the day through.
_MONTH = (r"january|february|march|april|may|june|july|august|september|"
          r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|"
          r"nov|dec")
#: Capitalised only. With ``re.I`` the modal verb "may" matched the month May
#: and dropped the figure that preceded it — "Brazil 9,999,999 may be an
#: undercount" reported no assertion at all, so the gate caveated a wrong number
#: instead of refusing it. A month in running prose is capitalised; a modal verb
#: is not.
#: Capitalised, and "May" only in its full form: the lowercase modal "may"
#: matched the month and dropped the figure in front of it.
_MONTH_CAPITALISED = (
    r"January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec")
_DAY_THEN_MONTH = re.compile(r"^\s*(" + _MONTH_CAPITALISED + r")\b")
_MONTH_THEN_DAY = re.compile(r"(" + _MONTH_CAPITALISED + r")\s*\Z")


class RefusalCode(str, Enum):
    """A claim that must not be admitted as written."""

    #: A figure was asserted and no figure bound to its subject matches it.
    ASSERTION_NOT_FOUND = "assertion_not_found"
    #: A numeral is present but binds to no subject — "the total reached X".
    UNATTRIBUTED_NUMERAL = "unattributed_numeral"
    #: The claim dates its figures and the artifact dates its own differently.
    DATE_MISMATCH = "date_mismatch"


class CaveatCode(str, Enum):
    """A claim that is admitted, and marked.

    Deliberately a **different enum** from :class:`RefusalCode`: a caller that
    branches on a truthy ``code`` would read a caveat as a failure and invert
    the verdict. Separate types make that a type error rather than a bug.
    """

    #: No numeral at all — a qualitative claim. Nothing was checked.
    NO_CHECKABLE_ASSERTION = "no_checkable_assertion"
    #: Bytes were unavailable, so nothing *could* be checked.
    UNCHECKED_NO_BYTES = "unchecked_no_bytes"
    #: The claim dates its figures and the artifact names no date at all.
    UNDATED_SOURCE = "undated_source"
    #: The artifact's bytes exist, but its content could not be read. Nothing
    #: was checked — and "the reader could not read this" is a different fact
    #: from "the source states nothing".
    SOURCE_NOT_READABLE = "source_not_readable"


@dataclass(frozen=True, slots=True)
class Figure:
    """One numeral and where it sits."""

    value: float
    raw: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class GroundingVerdict:
    """The gate's answer. Exactly one of ``refusal``/``caveat`` is set."""

    grounded: bool
    refusal: RefusalCode | None = None
    detail: str = ""
    caveat: CaveatCode | None = None
    #: What the gate could not check, carried as data rather than implied away.
    unchecked: tuple[str, ...] = ()

    def is_caveated(self) -> bool:
        return self.caveat is not None


def _normalise(raw: str) -> float | None:
    """`3,959,158` / `3959158` / `3 959 158` / `3.96` → a float."""
    cleaned = raw.replace(",", "").replace("_", "").replace(" ", "")
    # A trailing period is punctuation, not a decimal point.
    cleaned = cleaned.rstrip(".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_quoted_json_value(text: str, start: int, end: int) -> bool:
    """Is this numeral the quoted value of a JSON field?

    ``"mag":"3087879971"`` is an identifier, not a statement about the world:
    OpenAlex's ``mag`` id was read as a quantity because it sits inside the
    JSON record. A numeral directly enclosed in double quotes whose opening
    quote follows a colon is a serialized field value; prose — including
    ``Total: 3,959,158`` and ``He said "3,959,158 cases"`` — is untouched.
    The seam fix means the gate is never *fed* serialization; this rule makes
    the identifier safe even if a caller hands it one anyway.
    """
    if start == 0 or end >= len(text):
        return False
    if text[start - 1] != '"' or text[end] != '"':
        return False
    return text[:start - 1].rstrip().endswith(":")


_MONTH_NUMBER = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
_MONTHS = "|".join(sorted(_MONTH_NUMBER, key=len, reverse=True))
#: ``1 September 2020`` / ``1 Sept 2020`` / ``September 1, 2020`` / ``2020-09-01``.
#: ``\Z`` not ``$``: this package forbids ``$`` (it matches before a trailing newline).
_DATE_DAY_MONTH = re.compile(
    r"\b(\d{1,2})\s+(" + _MONTHS + r")\.?,?\s+(\d{4})\b", re.I)
_DATE_MONTH_DAY = re.compile(
    r"\b(" + _MONTHS + r")\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_DAY_MONTH_BARE = re.compile(r"\b(\d{1,2})\s+(" + _MONTHS + r")\b", re.I)
_DATE_MONTH_DAY_BARE = re.compile(r"\b(" + _MONTHS + r")\.?\s+(\d{1,2})\b",
                                  re.I)


@dataclass(frozen=True, slots=True)
class Date:
    """One calendar date and where it sits. ``year`` is None when unstated."""

    year: int | None
    month: int
    day: int
    start: int
    end: int


def dates_in(text: str) -> tuple[Date, ...]:
    """Every calendar date the text names, in order, with its span.

    The year is optional: "as of 1 September" is a date, and requiring a year
    meant the incident's own phrasing produced no date at all and skipped the
    check entirely.

    Spans matter as much as values. A date that merely appears *somewhere* in a
    two-week table says nothing about the figure it is supposed to date — that
    is containment again, and containment is what let the incident through the
    first time.
    """
    found: list[Date] = []
    taken: list[tuple[int, int]] = []

    def add(year: int | None, month: int, day: int, start: int,
            end: int) -> None:
        found.append(Date(year=year, month=month, day=day, start=start,
                          end=end))
        taken.append((start, end))

    for match in _DATE_DAY_MONTH.finditer(text):
        month = _MONTH_NUMBER.get(match.group(2).lower())
        if month:
            add(int(match.group(3)), month, int(match.group(1)),
                match.start(), match.end())
    for match in _DATE_MONTH_DAY.finditer(text):
        month = _MONTH_NUMBER.get(match.group(1).lower())
        if month:
            add(int(match.group(3)), month, int(match.group(2)),
                match.start(), match.end())
    for match in _DATE_ISO.finditer(text):
        add(int(match.group(1)), int(match.group(2)), int(match.group(3)),
            match.start(), match.end())

    def overlaps(start: int, end: int) -> bool:
        return any(start < t_end and t_start < end for t_start, t_end in taken)

    # Year-less forms last, and never inside a span already read: "1 September
    # 2020" must not also yield a year-less "1 September".
    for match in _DATE_DAY_MONTH_BARE.finditer(text):
        month = _MONTH_NUMBER.get(match.group(2).lower())
        if month and not overlaps(match.start(), match.end()):
            add(None, month, int(match.group(1)), match.start(), match.end())
    for match in _DATE_MONTH_DAY_BARE.finditer(text):
        month = _MONTH_NUMBER.get(match.group(1).lower())
        if month and not overlaps(match.start(), match.end()):
            add(None, month, int(match.group(2)), match.start(), match.end())
    return tuple(sorted(found, key=lambda date: date.start))


def _dates_match(left: Date, right: Date) -> bool:
    """Same day; the year only has to agree when both state one."""
    if left.month != right.month or left.day != right.day:
        return False
    return left.year is None or right.year is None or left.year == right.year


def _nearest_date(text: str, figure: Figure,
                  dates: Sequence[Date]) -> Date | None:
    """The date closest to a figure — the one that dates it, if any does."""
    best: tuple[int, Date] | None = None
    for date in dates:
        distance = (figure.start - date.end if date.end <= figure.start
                    else date.start - figure.end if date.start >= figure.end
                    else 0)
        if distance > MAX_BINDING_DISTANCE:
            continue
        if best is None or distance < best[0]:
            best = (distance, date)
    return best[1] if best else None


def figures_in(text: str) -> tuple[Figure, ...]:
    """Every numeral in ``text``, excluding bare years.

    Years are excluded because "on 1 September 2020" is a date, not an
    assertion — counting it would make a qualitative claim look quantitative and
    send it down the refusal path instead of the caveat path.
    """
    found: list[Figure] = []
    for match in _NUMBER.finditer(text):
        raw = match.group(0)
        if _YEAR.match(raw.strip()):
            continue
        # "1 September" / "September 1" — a date component, not a figure.
        if _DAY_THEN_MONTH.match(text[match.end():]):
            continue
        if _MONTH_THEN_DAY.search(text[:match.start()]):
            continue
        # "COVID-19", "SARS-CoV-2": a numeral inside a name is not a quantity.
        # Without this the gate reads the 19 as an assertion and refuses a
        # correct claim about the disease.
        if match.start() and (text[match.start() - 1].isalnum()
                              or text[match.start() - 1] in "-_/"):
            continue
        # "mag":"3087879971": a serialized identifier is not a quantity.
        if _is_quoted_json_value(text, match.start(), match.end()):
            continue
        # "2nd", "3rd", "4th": an ordinal, not a count.
        if _ORDINAL.match(text[match.end():]):
            continue
        if _in_clock(text, match.start(), match.end()):
            continue
        value = _normalise(raw)
        if value is None:
            continue
        # "5.275035 million" is 5,275,035. Without folding the scale, a claim
        # written in millions and an artifact written in full were different
        # numbers, so a correct claim was refused. The scan compares canonical
        # values; the gate compared raw ones — the same defect, one seam over.
        scale = _SCALE.match(text[match.end():])
        if scale is not None:
            value *= _SCALES[scale.group(1).casefold()]
        found.append(Figure(value=value, raw=raw, start=match.start(),
                            end=match.end()))
    return tuple(found)


def _subjects(text: str, candidates: Sequence[str]) -> list[tuple[str, int, int]]:
    """Where each candidate subject appears, case-insensitively."""
    hits: list[tuple[str, int, int]] = []
    lowered = text.lower()
    for name in candidates:
        needle = name.lower()
        if not needle:
            # An empty name matches at every offset and never advances
            # ``start`` — an infinite loop, which is the absence of a verdict
            # rather than a wrong one. Refuse to consider it.
            continue
        start = 0
        while (index := lowered.find(needle, start)) != -1:
            hits.append((name, index, index + len(needle)))
            start = index + len(needle)
    return sorted(hits, key=lambda hit: hit[1])


def _bind(text: str, figure: Figure,
          hits: Sequence[tuple[str, int, int]]) -> str | None:
    """The subject this figure belongs to, or None.

    Nearest mention by absolute distance; a preceding mention wins a tie. A
    coordination word between the figure and its candidate breaks the binding,
    so a figure does not attach across "and"/"vs"/";".
    """
    best: tuple[int, int, str] | None = None
    for name, start, end in hits:
        if end <= figure.start:
            distance = figure.start - end
            precedes = 1
        elif start >= figure.end:
            distance = start - figure.end
            precedes = 0
        else:
            continue
        if distance > MAX_BINDING_DISTANCE:
            continue
        gap_start, gap_end = (end, figure.start) if precedes else (
            figure.end, start)
        if _COORDINATION.search(text[gap_start:gap_end]):
            continue
        key = (distance, -precedes, name)
        if best is None or key < best:
            best = key
    return best[2] if best else None


def _render(dates: Sequence[Date]) -> str:
    """`Date(2020, 9, 1)` → `2020-09-01`, for a refusal a reader can act on."""
    return ", ".join(
        f"{date.year:04d}-{date.month:02d}-{date.day:02d}" if date.year
        else f"{date.month:02d}-{date.day:02d}" for date in dates)


_QUOTE_PAIRS = {'"': '"', "'": "'", "\u201c": "\u201d", "\u2018": "\u2019"}


def _verbatim_quotation(statement: str, artifact_text: str) -> bool:
    """Does the claim quote the artifact verbatim (whitespace aside)?

    A figure-free claim cannot be checked by binding, and calling every such
    claim "nothing was checked" is the safe-but-blind answer. A claim that is
    a clause of the source's own prose is the one qualitative shape that can be
    confirmed by rule: the source says it, in those words. Shorter than a clause
    is not an assertion, so it is not grounded by containment.
    """
    quote = statement.strip()
    if len(quote) >= 2 and _QUOTE_PAIRS.get(quote[0]) == quote[-1]:
        quote = quote[1:-1].strip()
    words = quote.split()
    if len(words) < MIN_QUOTATION_WORDS:
        return False
    return (" ".join(words).casefold()
            in " ".join(artifact_text.split()).casefold())


def check_claim(statement: str, artifact_text: str | None, *,
                subjects: Iterable[str] = (),
                unreadable_detail: str = "") -> GroundingVerdict:
    """Does ``artifact_text`` support the figures ``statement`` asserts?

    ``subjects`` are the entities the claim is about (country names, say). The
    claim's own figures are bound to them, then each is looked for in the
    artifact bound to the same subject.

    ``unreadable_detail`` is the content reader's account of a read that fell
    back. The caller passes it instead of pretending the bytes were text; the
    verdict is then ``source_not_readable`` — a caveat that says the reader
    could not read the source, never a refusal that would blame the claim for
    a missing figure the reader could not see.
    """
    names = tuple(dict.fromkeys(subjects))
    if unreadable_detail:
        return GroundingVerdict(
            grounded=False, caveat=CaveatCode.SOURCE_NOT_READABLE,
            detail=f"the artifact's content could not be read: "
                   f"{unreadable_detail}",
            unchecked=("artifact_content",))
    claim_figures = figures_in(statement)
    if not claim_figures:
        if artifact_text is not None and _verbatim_quotation(
                statement, artifact_text):
            return GroundingVerdict(
                grounded=True,
                detail="the claim quotes the artifact's content verbatim")
        return GroundingVerdict(
            grounded=False, caveat=CaveatCode.NO_CHECKABLE_ASSERTION,
            detail="the claim asserts no figure, so nothing was checked",
            unchecked=("assertion",))
    if artifact_text is None:
        return GroundingVerdict(
            grounded=False, caveat=CaveatCode.UNCHECKED_NO_BYTES,
            detail="no artifact bytes were available to check against",
            unchecked=("artifact_bytes",))
    if not names:
        return GroundingVerdict(
            grounded=False, refusal=RefusalCode.UNATTRIBUTED_NUMERAL,
            detail="the claim names no subject to bind its figures to",
            unchecked=())

    # A claim that dates its figures can be wrong even when every figure is
    # real. The date must be the one that dates *the matched figure*, not one
    # that appears somewhere in the artifact: a two-week table names both weeks,
    # so containment over dates would pass exactly the claim that started this.
    claim_dates = dates_in(statement)
    artifact_dates = dates_in(artifact_text)
    if claim_dates and not artifact_dates:
        return GroundingVerdict(
            grounded=False, caveat=CaveatCode.UNDATED_SOURCE,
            detail=("the claim dates its figures and the artifact names no "
                    "date at all"),
            unchecked=("date",))

    claim_hits = _subjects(statement, names)
    artifact_hits = _subjects(artifact_text, names)
    artifact_figures = figures_in(artifact_text)

    grounded_because: list[str] = []
    matched: Figure | None = None
    for figure in claim_figures:
        subject = _bind(statement, figure, claim_hits)
        if subject is None:
            return GroundingVerdict(
                grounded=False, refusal=RefusalCode.UNATTRIBUTED_NUMERAL,
                detail=(f"{figure.raw} binds to no subject in the claim "
                        f"(subjects: {list(names)})"))
        matched = None
        for candidate in artifact_figures:
            if _bind(artifact_text, candidate, artifact_hits) != subject:
                continue
            if abs(candidate.value - figure.value) < 0.5:
                matched = candidate
                break
        if matched is None:
            return GroundingVerdict(
                grounded=False, refusal=RefusalCode.ASSERTION_NOT_FOUND,
                detail=(f"{subject} {figure.raw}: no figure bound to "
                        f"{subject!r} in the artifact matches it"),
                unchecked=())
        grounded_because.append(f"{subject} {figure.raw}")
        if claim_dates:
            # Bind the date on both sides. Asking whether *any* of the claim's
            # dates matches reopens the incident with one extra true date:
            # "… as of 1 September 2020 (published 18 September 2020)" matched
            # the artifact's 18 September and passed a claim that is wrong about
            # 1 September. The date that dates the claim's figure must be the
            # date that dates the artifact's figure.
            claim_date = _nearest_date(statement, figure, claim_dates)
            nearest = _nearest_date(artifact_text, matched, artifact_dates)
            if (claim_date is None or nearest is None
                    or not _dates_match(claim_date, nearest)):
                dated = (f"{nearest.year:04d}-{nearest.month:02d}-{nearest.day:02d}"
                         if nearest and nearest.year
                         else (f"{nearest.month:02d}-{nearest.day:02d}"
                               if nearest else "none"))
                return GroundingVerdict(
                    grounded=False, refusal=RefusalCode.DATE_MISMATCH,
                    detail=(f"{subject} {figure.raw} is dated {dated} in the "
                            f"artifact; the claim is dated "
                            f"{_render(claim_dates)}"),
                    unchecked=())
    # A grounded verdict must say what it grounded on. An operator reading the
    # journal saw `grounded: true` and an empty detail — the same shape as a
    # green badge with nothing behind it.
    dated = ""
    if claim_dates and matched is not None:
        matched_date = _nearest_date(artifact_text, matched, artifact_dates)
        if matched_date is not None:
            dated = (f" on {matched_date.year:04d}-{matched_date.month:02d}-"
                     f"{matched_date.day:02d}" if matched_date.year
                     else f" on {matched_date.month:02d}-{matched_date.day:02d}")
    return GroundingVerdict(
        grounded=True,
        detail=(f"the artifact states {', '.join(grounded_because)}{dated}, "
                f"bound to the subjects the claim names"))
