"""Deterministic falsification: facts, conflicts, arithmetic.

Three capabilities ask three questions a model answers badly and unverifiably:

* **what does this artifact actually say?** ``facts_in`` returns the dates it
  names, the figures it states with the subject each binds to, and the quoted
  spans, all extracted by rule.
* **can these claims both be true?** ``conflicts_between`` reports the pairs
  that cannot, from the numbers and the orderings the text states.
* **does this derived figure follow from its base?** ``check_derivation``
  recomputes a total, a difference, a ratio or a percentage and compares.

Nothing here reads a clock, a network, a database or a model. The same text
yields the same facts forever, which is the point: a falsification a reviewer
is shown can be re-derived from the bytes that produced it, and a red test can
prove the check is load-bearing rather than decorative.

What that buys is coverage of the mechanical cases. What it costs is every
case that needs paraphrase, coreference or world knowledge — a conflict phrased
in two vocabularies, a figure whose subject is a pronoun. Those are *not*
found here, and the capability reports what it read instead of guessing. The
model keeps the judgement: this module says "these two cannot both be true";
it never says which one is right, and never proposes a correction.

The extraction is deliberately conservative. A figure with no subject to bind
to is reported with the nearest following noun (``"there were 5,275,035
cases"`` binds to ``cases``); a number inside a date span is a date, not a
figure; a bare single digit is skipped because ``Figure 1`` and ``Section 2``
are not statistics. Every one of those choices loses something, and each is
stated here rather than hidden.

OPS-5Z Group C: ``facts_in`` also takes the content reader's typed result. It
mines only a ``content`` read; a ``fallback`` (an undeclared serialization) or
an ``unreadable`` artifact yields no facts and a ``not_mined`` reason. The one
non-stdlib import below is the content model, which is itself stdlib-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from hermes.tools.capabilities.content import ContentRead, ContentState

__all__ = [
    "ArithmeticVerdict",
    "ClaimText",
    "Conflict",
    "DateFact",
    "FigureFact",
    "Inspection",
    "check_derivation",
    "conflicts_between",
    "describe_conflicts",
    "describe_inspection",
    "describe_verdict",
    "facts_document",
    "facts_in",
    "filter_inspection",
]

#: Bounds. An artifact may be 256 KiB; the analysis window and every result
#: list are capped so one call cannot turn a tick into a scan of the run.
#: ``MAX_FIGURES`` and ``MAX_CONFLICTS`` are *reported* caps: the payload says
#: what was cut and how much was found. A cap that returns a prefix while
#: claiming the whole is the ``MAX_SCAN_CLAIMS`` false pass with another name.
MAX_ANALYSIS_CHARS = 200_000
MAX_FIGURES = 64
MAX_DATES = 48
MAX_QUOTES = 8
MAX_SUBJECTS = 32
MAX_SCAN_CLAIMS = 12
MAX_CONFLICTS = 16
MAX_CLAIM_CHARS = 8_000
#: The model-visible note, before the runtime's own 1 KiB detail bound.
NOTE_MAX_CHARS = 900

# ── dates ──

_MONTH_NUMBERS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_MONTH_ALTERNATION = "|".join(
    sorted(_MONTH_NUMBERS, key=len, reverse=True))

_DATE_DMY = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
    rf"(?P<month>{_MONTH_ALTERNATION})\.?,?\s+(?P<year>\d{{4}})\b",
    re.IGNORECASE)
_DATE_MDY = re.compile(
    rf"\b(?P<month>{_MONTH_ALTERNATION})\.?\s+"
    rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<year>\d{{4}})\b",
    re.IGNORECASE)
_DATE_ISO = re.compile(
    r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b")
_DATE_NUMERIC = re.compile(
    r"\b(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})\b")
_DATE_MONTH_YEAR = re.compile(
    rf"\b(?P<month>{_MONTH_ALTERNATION})\.?,?\s+(?P<year>\d{{4}})\b",
    re.IGNORECASE)

#: A figure: grouped thousands, a decimal, or both. The lookarounds keep
#: identifiers (``art-1``, ``abc123``, ``evidence/9``) out of the count.
_FIGURE = re.compile(
    r"(?<![\w.,/-])"
    r"(?P<literal>-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?![\w])")

_UNIT = re.compile(
    r"\s*(?P<unit>%|percent(?:age\s+points?)?\b|million\b|billion\b|"
    r"trillion\b|thousand\b)",
    re.IGNORECASE)

_MAGNITUDE: dict[str, float] = {
    "thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12,
}

_QUOTE = re.compile(r"[\u201c\"](?P<quote>[^\u201d\"\n]{12,240})[\u201d\"]")
_GUILLEMET = re.compile(r"\u00ab(?P<quote>[^\u00bb\n]{12,240})\u00bb")

_WORD = re.compile(r"[A-Za-z][A-Za-z'\u2019.-]*|\d+(?:[.,]\d+)*")

_CLAUSE_BREAK = re.compile(
    r"[.;:!?\n\t|]|[\u2014\u2013]|\b(?:while|whereas|but|although|though)\b",
    re.IGNORECASE)

#: A blank line is a paragraph boundary; a single newline is a row boundary.
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\r?\n")

#: Words that are never the entity a figure belongs to. Months and weekdays are
#: capitalised in running prose, so "On 18 September 2020, India reported
#: 5,275,035" bound the figure to *September* — a date read as a subject.
_NON_ENTITY_WORDS = frozenset({
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "week", "weeks", "month", "months", "year", "years", "day",
    "days", "ending", "ending", "cumulative", "total", "totals",
})

_LEADING_STOPWORDS = frozenset({
    "the", "a", "an", "that", "this", "these", "those", "its", "their",
    "his", "her", "was", "were", "is", "are", "of", "in", "on", "at", "by",
    "for", "from", "to", "with", "and", "but", "while", "whereas", "however",
    "meanwhile", "there", "here", "as", "or",
})

_TRAILING_STOPWORDS = frozenset({
    "reported", "reports", "recorded", "records", "totalled", "totaled",
    "reached", "stands", "stood", "had", "has", "have", "was", "were", "is",
    "are", "be", "been", "of", "at", "in", "on", "with", "by", "to", "from",
    "approximately", "about", "nearly", "roughly", "over", "under", "more",
    "fewer", "than", "around", "some", "per", "each", "every", "totalling",
    "totaling", "including", "includes", "included", "showed", "shows",
    "saw", "sees", "remains", "remained", "now", "then", "and", "or",
    "averted", "rose", "grew", "fell", "dropped", "increased",
    "decreased", "declined", "jumped", "exceeded", "accounted",
    "added", "lost", "gained", "estimated", "projects", "projected",
})


@dataclass(frozen=True, slots=True)
class DateFact:
    """One date the text names, with the literal that named it."""

    iso: str
    literal: str
    position: int


@dataclass(frozen=True, slots=True)
class FigureFact:
    """One stated figure, the phrase before it, and the date it binds to.

    ``subject`` is the surface phrase the extractor found before the number
    (``"India reported"`` -> ``"India"``); ``entity`` is its last token, which
    is what conflict matching compares. Both are heuristics: ``entity`` is a
    name only as far as the last word of a noun phrase is a name.
    """

    subject: str
    entity: str
    literal: str
    value: float
    unit: str
    magnitude: float
    canonical: float
    date: str
    position: int


@dataclass(frozen=True, slots=True)
class Inspection:
    """What one text states, extracted deterministically.

    ``truncated`` is true when anything was left out — either the analysis
    window or the figure cap. The two causes are named separately so a reader
    is never told "the first N characters were read" when every character was
    read and only the figure list was cut (OPS-5Z audit N-H).
    """

    dates: tuple[DateFact, ...]
    figures: tuple[FigureFact, ...]
    quotes: tuple[str, ...]
    subjects: tuple[str, ...]
    analyzed_chars: int
    truncated: bool
    window_truncated: bool = False
    figures_truncated: bool = False
    #: Why nothing was mined (a ``fallback`` or ``unreadable`` read), or "".
    #: An empty inspection with a reason is a different fact from an empty
    #: inspection without one, and a consumer must be able to tell them apart.
    not_mined: str = ""

    def is_empty(self) -> bool:
        return not (self.dates or self.figures or self.quotes)


def _iso_date(year: int, month: int, day: int | None = None) -> str | None:
    if not 1 <= month <= 12 or not 1000 <= year <= 9999:
        return None
    if day is None:
        return f"{year:04d}-{month:02d}"
    if not 1 <= day <= 31:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _date_spans(text: str) -> list[tuple[int, int, str, str]]:
    """``(start, end, iso, literal)`` for every date, most specific first.

    Overlapping matches are dropped in favour of the earliest/longest one, so
    ``18 September 2020`` is one date and not also a month-year.
    """
    found: list[tuple[int, int, str, str]] = []
    for match in _DATE_ISO.finditer(text):
        iso = _iso_date(int(match.group("year")), int(match.group("month")),
                        int(match.group("day")))
        if iso is not None:
            found.append((match.start(), match.end(), iso, match.group(0)))
    for match in _DATE_NUMERIC.finditer(text):
        iso = _iso_date(int(match.group("year")), int(match.group("month")),
                        int(match.group("day")))
        if iso is not None:
            found.append((match.start(), match.end(), iso, match.group(0)))
    for pattern in (_DATE_DMY, _DATE_MDY):
        for match in pattern.finditer(text):
            month = _MONTH_NUMBERS.get(match.group("month").casefold())
            if month is None:
                continue
            iso = _iso_date(int(match.group("year")), month,
                            int(match.group("day")))
            if iso is not None:
                found.append((match.start(), match.end(), iso, match.group(0)))
    for match in _DATE_MONTH_YEAR.finditer(text):
        month = _MONTH_NUMBERS.get(match.group("month").casefold())
        if month is None:
            continue
        iso = _iso_date(int(match.group("year")), month)
        if iso is not None:
            found.append((match.start(), match.end(), iso, match.group(0)))
    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    kept: list[tuple[int, int, str, str]] = []
    for start, end, iso, literal in found:
        if any(start < other_end and other_start < end
               for other_start, other_end, _, _ in kept):
            continue
        kept.append((start, end, iso, literal))
    kept.sort(key=lambda item: item[0])
    return kept


def _paragraph_bounds(text: str, position: int) -> tuple[int, int]:
    start = text.rfind("\n\n", 0, position)
    start = 0 if start < 0 else start + 2
    end = text.find("\n\n", position)
    end = len(text) if end < 0 else end
    return start, end


def _same_date(left: str, right: str) -> bool:
    """Equal, or equal at the coarser of the two resolutions."""
    if not left or not right:
        return False
    if left == right:
        return True
    return left.startswith(right) or right.startswith(left)


def _nearest_date(spans: Sequence[tuple[int, int, str, str]], text: str,
                  position: int) -> str:
    """The date a figure at ``position`` binds to, or ``""``.

    A preceding date in the same paragraph wins within 500 characters (the
    usual ``"India 5,275,035 as of 18 September"`` shape puts it after, so a
    following date is also accepted within 200). Binding is a surface
    heuristic and says so: a sentence naming two dates binds every figure in
    it to the closer one.
    """
    lower, upper = _paragraph_bounds(text, position)
    preceding = [span for span in spans
                 if lower <= span[0] and span[1] <= position]
    if preceding:
        span = preceding[-1]
        if position - span[1] <= 500:
            return span[2]
    following = [span for span in spans
                 if position <= span[0] and span[1] <= upper]
    if following:
        span = following[0]
        if span[0] - position <= 200:
            return span[2]
    return ""


def _in_clock(text: str, start: int, end: int) -> bool:
    """Is this numeral part of a clock time — `09:50:45`, `5:30`?

    A time is one fact, not three. The LIGO abstract opens "on September 14,
    2015 at 09:50:45 UTC", and both figure parsers read that as 9, 50 and 45 —
    three quantities a claim could bind to and be "grounded" by.
    """
    before = text[start - 1] if start else ""
    after = text[end] if end < len(text) else ""
    return before == ":" or after == ":"


def _tokens_before(text: str, start: int) -> str:
    """The phrase before a figure, inside its own paragraph and clause.

    A *blank* line ends the subject phrase: a record's title and its abstract
    are separate paragraphs, so a PubMed abstract that begins with ``1,200``
    must not bind the figure to the title's ``Containment``. A single newline
    is a table's row/cell boundary, not a paragraph — in
    ``"India\\n5,275,035"`` the cell above is the subject — so only a blank
    line resets. An empty last clause means "no subject before the figure";
    ``_subject_after`` then binds the nearest following noun.
    """
    window = text[max(0, start - 90):start]
    paragraphs = _PARAGRAPH_BREAK.split(window)
    window = paragraphs[-1] if paragraphs else window
    parts = [part for part in _CLAUSE_BREAK.split(window) if part.strip()]
    clause = parts[-1] if parts else ""
    tokens = _WORD.findall(clause)
    if not tokens:
        return ""
    picked = tokens[-6:]
    while picked and picked[-1].casefold() in _TRAILING_STOPWORDS:
        picked.pop()
    while picked and picked[0].casefold() in _LEADING_STOPWORDS:
        picked.pop(0)
    return " ".join(picked).strip(" ,;:-")


def _entity_of(subject: str) -> str:
    """The named token of a subject phrase, as a surface heuristic.

    The first capitalised word is the entity in a phrase like ``"Hubei
    averted"``; when nothing is capitalised (``"the reproduction number
    fell"``) the last token is the noun the figure modifies. This is a
    heuristic and says so: two different organisations with the same
    capitalised word look identical here, which is what the caller sees.
    """
    tokens = subject.split(" ")
    for token in reversed(tokens):
        stripped = _bare_name(token)
        if stripped[:1].isupper() and stripped.casefold() not in _NON_ENTITY_WORDS:
            return stripped
    return _bare_name(tokens[-1]) if tokens else ""


def _bare_name(token: str) -> str:
    """A token without the punctuation that makes "India's" a different name."""
    return (token.strip(" ,;:-()[]")
            .removesuffix("'s").removesuffix("\u2019s"))


def _subject_after(text: str, end: int) -> str:
    tail = _WORD.findall(text[end:end + 40])
    picked: list[str] = []
    for token in tail:
        if not picked and token.casefold() in _LEADING_STOPWORDS:
            continue
        picked.append(token)
        if len(picked) == 2:
            break
    while picked and picked[-1].casefold() in _TRAILING_STOPWORDS:
        picked.pop()
    return " ".join(picked)


def _figure_facts(text: str, spans: Sequence[tuple[int, int, str, str]]
                  ) -> tuple[list[FigureFact], int]:
    """The first ``MAX_FIGURES`` figures, and how many were found in total.

    The second value is the *full* count, not the returned list's length: a
    caller that reports 64 while 70 were stated is the silent-prefix defect
    this pair exists to make impossible. It costs one integer per match, not a
    second parse.
    """
    figures: list[FigureFact] = []
    total = 0
    for match in _FIGURE.finditer(text):
        if any(start <= match.start() < end for start, end, _, _ in spans):
            continue
        literal = match.group("literal")
        digits = literal.replace(",", "").lstrip("-")
        if (not literal.startswith("-") and "." not in digits
                and "," not in literal
                and len(digits) == 4 and digits.isdigit()
                and 1900 <= int(digits) <= 2100):
            # A standalone year is a date, not a statistic. A year with a
            # thousands separator or a decimal is a figure.
            continue
        unit_match = _UNIT.match(text, match.end())
        raw_unit = unit_match.group("unit").casefold() if unit_match else ""
        if raw_unit in ("percent", "percentage point", "percentage points"):
            unit = "%"
        elif raw_unit.startswith("percentage point"):
            unit = "pp"
        else:
            unit = raw_unit
        if not unit and len(digits) == 1:
            # "Figure 1", "Section 2": a bare digit is a label far more often
            # than a statistic, and one false fact costs more than a missed one.
            continue
        if _in_clock(text, match.start(), match.end()):
            continue
        total += 1
        if len(figures) >= MAX_FIGURES:
            # Keep counting, so the caller can say how much it did not return.
            continue
        magnitude = _MAGNITUDE.get(raw_unit, 1.0)
        value = float(literal.replace(",", ""))
        subject = _tokens_before(text, match.start())
        if not subject:
            subject = _subject_after(text, match.end())
        entity = _entity_of(subject)
        figures.append(FigureFact(
            subject=subject,
            entity=entity,
            literal=literal,
            value=value,
            unit=unit,
            magnitude=magnitude,
            canonical=value * magnitude,
            date=_nearest_date(spans, text, match.start()),
            position=match.start(),
        ))
    return figures, total


def facts_in(source: str | ContentRead) -> Inspection:
    """Extract dates, figures and quoted spans from prose. Pure.

    ``source`` is either prose (a claim's statement) or the typed result of a
    content read. Only a ``content`` read is mined: a ``fallback`` is a raw
    serialization and an ``unreadable`` artifact has no prose, so both return
    an empty inspection whose ``not_mined`` says why. Returning the empty
    inspection alone would read as "the source states nothing" — the false
    pass this distinction exists to end.
    """
    if isinstance(source, ContentRead) and source.state != ContentState.CONTENT:
        return Inspection(
            dates=(), figures=(), quotes=(), subjects=(),
            analyzed_chars=0, truncated=False,
            not_mined=(f"the artifact was not mined: its read state is "
                       f"{source.state.value}"
                       + (f" ({source.detail})" if source.detail else "")))
    text = source.text if isinstance(source, ContentRead) else str(source)
    analyzed = text[:MAX_ANALYSIS_CHARS]
    spans = _date_spans(analyzed)
    dates = tuple(
        DateFact(iso=iso, literal=literal, position=start)
        for start, _end, iso, literal in spans[:MAX_DATES])
    figure_list, figure_total = _figure_facts(analyzed, spans)
    figures = tuple(figure_list)
    window_truncated = len(text) > len(analyzed)
    figures_truncated = figure_total > len(figures)
    quotes: list[str] = []
    for pattern in (_QUOTE, _GUILLEMET):
        for match in pattern.finditer(analyzed):
            quote = " ".join(match.group("quote").split())
            if quote and quote not in quotes:
                quotes.append(quote)
            if len(quotes) >= MAX_QUOTES:
                break
    subjects: list[str] = []
    for figure in figures:
        if figure.subject and figure.subject.casefold() not in {
                item.casefold() for item in subjects}:
            subjects.append(figure.subject)
        if len(subjects) >= MAX_SUBJECTS:
            break
    return Inspection(
        dates=dates,
        figures=figures,
        quotes=tuple(quotes),
        subjects=tuple(subjects),
        analyzed_chars=len(analyzed),
        truncated=window_truncated or figures_truncated,
        window_truncated=window_truncated,
        figures_truncated=figures_truncated,
    )


def filter_inspection(inspection: Inspection,
                      subjects: Sequence[str]) -> Inspection:
    """Keep only figures whose subject mentions one of ``subjects``.

    Case-insensitive substring match on the surface phrase. An empty subject
    list means "everything"; dates and quotes are always kept because they are
    what a claim's figures are read against.
    """
    wanted = [item.strip().casefold() for item in subjects if item.strip()]
    if not wanted:
        return inspection
    figures = tuple(
        figure for figure in inspection.figures
        if any(term in figure.subject.casefold()
               or term == figure.entity.casefold() for term in wanted))
    return Inspection(
        dates=inspection.dates,
        figures=figures,
        quotes=inspection.quotes,
        subjects=tuple(dict.fromkeys(
            figure.subject for figure in figures if figure.subject)),
        analyzed_chars=inspection.analyzed_chars,
        truncated=inspection.truncated,
        window_truncated=inspection.window_truncated,
        figures_truncated=inspection.figures_truncated,
        not_mined=inspection.not_mined,
    )


def facts_document(inspection: Inspection) -> dict[str, Any]:
    """The canonical JSON form of an inspection (the observation payload)."""
    return {
        "dates": [{"iso": date.iso, "literal": date.literal}
                  for date in inspection.dates],
        "figures": [{
            "subject": figure.subject,
            "entity": figure.entity,
            "literal": figure.literal,
            "value": figure.value,
            "unit": figure.unit,
            "magnitude": figure.magnitude,
            "canonical": figure.canonical,
            "date": figure.date,
        } for figure in inspection.figures],
        "quotes": list(inspection.quotes),
        "subjects": list(inspection.subjects),
        "analyzed_chars": inspection.analyzed_chars,
        "truncated": inspection.truncated,
        "window_truncated": inspection.window_truncated,
        "figures_truncated": inspection.figures_truncated,
        "not_mined": inspection.not_mined,
    }


def _bound(text: str) -> str:
    if len(text) <= NOTE_MAX_CHARS:
        return text
    marker = f" [note truncated at {NOTE_MAX_CHARS} chars]"
    return text[:NOTE_MAX_CHARS - len(marker)] + marker


def describe_inspection(inspection: Inspection, ref: str,
                        read: Any = None) -> str:
    """The bounded, model-visible summary of one inspection.

    It is a note, not the payload: the full facts ride the observation payload
    and its digest. Everything here is source-derived text, and the runtime
    renders it inside an untrusted envelope.

    OPS-5Z5: ``read`` is the content reader's :class:`ContentRead`. When the
    read fell back, the note says so and names what was readable. Without it,
    "no figure was found" over an unreadable artifact is read as "the source
    states no figures" — the exact exoneration this note must never give.

    OPS-5Z Group C: a ``not_mined`` inspection is reported as exactly that. An
    undeclared serialization is not "a source that states nothing"; the note
    names the state and the reason, and never a bare empty list.
    """
    state = str(getattr(read, "state", ContentState.CONTENT)
                or ContentState.CONTENT) if read is not None else "content"
    detail = str(getattr(read, "detail", "") or "")
    fields = ", ".join(str(name) for name in getattr(read, "fields", ()) or ())
    unread = state != ContentState.CONTENT
    # A partial read is content for what it extracted (a title is prose) and
    # says what it could not read; its note scopes the negative the same way.
    partial = state == ContentState.CONTENT and bool(detail)
    scope = (f" (read: {fields or 'nothing'}"
             + (f"; {detail}" if detail else "") + ")") \
        if (unread or partial) else ""
    if inspection.not_mined:
        return _bound(f"{ref}: no fact was extracted — "
                      f"{inspection.not_mined}")
    if inspection.is_empty():
        if unread or partial:
            return _bound(f"{ref}: no date, figure or quoted span was found "
                          f"in the text that could be read{scope}")
        # A negative fact report must state its window: the record may carry
        # dates and counts in metadata the content model does not read.
        where = f" in the content ({fields})" if fields else ""
        caveat = ""
        if inspection.figures_truncated:
            caveat = (" (the figure list was capped at "
                      f"{MAX_FIGURES}; a filtered view can be empty while the "
                      "source stated more)")
        elif inspection.window_truncated:
            caveat = (f" (only the first {inspection.analyzed_chars} "
                      "characters were read)")
        return _bound(f"{ref}: no date, figure or quoted span was found"
                      f"{where}{caveat}")
    parts = [(f"{ref}: {len(inspection.dates)} date(s), "
              f"{len(inspection.figures)} figure(s), "
              f"{len(inspection.quotes)} quote(s)")]
    if unread or partial:
        parts.append(("not read" if unread else "partial read") + scope)
    if inspection.window_truncated:
        parts.append(f"read first {inspection.analyzed_chars} chars")
    if inspection.figures_truncated:
        # The cap is named. "truncated" alone would leave the reader guessing
        # whether the text was cut or the figure list — a different fact.
        parts.append(f"figures capped at {MAX_FIGURES}; more were stated")
    if inspection.dates:
        dates = ", ".join(date.iso for date in inspection.dates[:4])
        parts.append(f"dates: {dates}")
    if inspection.figures:
        shown = "; ".join(
            f"{figure.entity or '?'} {figure.literal}{figure.unit}"
            + (f" @{figure.date}" if figure.date else "")
            for figure in inspection.figures[:6])
        more = len(inspection.figures) - 6
        parts.append(f"figures: {shown}" + (f" (+{more} more)" if more > 0
                                            else ""))
    return _bound("; ".join(parts))


# ── conflicts ──


@dataclass(frozen=True, slots=True)
class ClaimText:
    """One claim to scan: a ref the caller owns, and the statement."""

    ref: str
    text: str


@dataclass(frozen=True, slots=True)
class Conflict:
    """Two claims that cannot both be true, and why — never which is right."""

    kind: str
    left: str
    right: str
    subject: str
    date: str
    detail: str


_QUANTITY = "QUANTITY"
_ATTRIBUTION = "ATTRIBUTION"
_ORDER = "ORDER"

_SUPERLATIVE = re.compile(
    r"(?P<subject>[A-Za-z][A-Za-z .'\u2019-]{1,60}?)\s+"
    r"(?:was|were|is|are)\s+(?:the\s+)?"
    r"(?P<rank>highest|largest|biggest|greatest|most)\b(?P<metric>[^.;]*)",
    re.IGNORECASE)

#: An explicit ordering assertion naming two subjects. Capitalised words only:
#: an ordering claim is about named entities, and a lower-case match would fire
#: on ordinary prose ("costs exceeded revenue") with no figure to bind to.
_LEAD = re.compile(
    r"(?P<a>[A-Z][A-Za-z'\u2019.-]*)\s+"
    r"(?:was|is|were|are|had|has|have)?\s*"
    r"(?:ahead\s+of|leading|led|surpassed|overtaken|overtook|outpaced|"
    r"exceeded)\s+(?P<b>[A-Z][A-Za-z'\u2019.-]*)")


#: An ordering assertion stated in prose, with no per-entity figure:
#: ``X was ahead of Y``, ``X led Y``, ``Y trailed X``, ``X was behind Y``.
#: Read over named entities only (a capitalised name), because a lower-case
#: match fires on ordinary prose ("costs exceed revenue") with nothing to
#: compare. The relation is the directional word, not the figure — the audit's
#: B1 has no figure on one side at all.
_ORDER_NAME = (
    r"[A-Z][A-Za-z'\u2019.-]*(?:\s+(?:the\s+|of\s+)?[A-Z][A-Za-z'\u2019.-]*)*")
_ORDER_GAP_WORD = (
    r"was|were|is|are|had|has|have|did|does|do|not|never|also|still|now|"
    r"then|already|further|again|consistently|clearly|well|far|"
    r"significantly|slightly|just|widely")
_ORDER_GAP = rf"(?P<gap>(?:(?:{_ORDER_GAP_WORD})\s+){{0,6}})"
_ORDER_RELATION = (
    r"(?P<relation>ahead\s+of|leading|leads|lead|led|outpaced|outpaces|"
    r"surpassed|surpasses|overtook|overtaken|exceeded|exceeds|behind|"
    r"trailing|trails|trailed|lagged\s+behind|lags\s+behind|fell\s+behind|"
    r"fallen\s+behind)")
_ORDER_OBJECT = rf"(?P<b>(?:the\s+)?{_ORDER_NAME})"

_ORDER_ASSERTION = re.compile(
    rf"(?P<a>{_ORDER_NAME})\s+{_ORDER_GAP}{_ORDER_RELATION}\s+{_ORDER_OBJECT}")
#: ``It is not the case that X was ahead of Y``: the negation sits before the
#: subject, so the gap-based rule cannot see it. Kept as its own pattern.
_ORDER_NEGATED_CASE = re.compile(
    rf"(?:(?:It|it)\s+(?:is|was)\s+)?not\s+(?:the\s+)?case\s+that\s+"
    rf"(?P<a>{_ORDER_NAME})\s+{_ORDER_GAP}{_ORDER_RELATION}\s+{_ORDER_OBJECT}")
_ORDER_NEGATION = re.compile(r"\b(?:not|never)\b", re.IGNORECASE)
_ORDER_BEHIND = re.compile(r"behind|trail|lag|fell|fallen", re.IGNORECASE)
_BARE_MONTH = re.compile(
    rf"\b(?P<month>{_MONTH_ALTERNATION})\b", re.IGNORECASE)

#: The three possible states of a named pair: first ahead, first behind,
#: equal. Ordering assertions are compared as the sets of states they allow.
_ORDER_STATE_AHEAD = 0
_ORDER_STATE_BEHIND = 1
_ORDER_STATE_EQUAL = 2
_ORDER_ALL_STATES = frozenset(
    {_ORDER_STATE_AHEAD, _ORDER_STATE_BEHIND, _ORDER_STATE_EQUAL})


@dataclass(frozen=True, slots=True)
class _OrderAssertion:
    """One ``X ahead of Y``-shaped statement, with its scope and polarity."""

    first: str
    second: str
    ahead: bool
    negated: bool
    scope: str
    position: int


def _order_name(raw: str) -> str:
    name = " ".join(raw.split()).strip(" ,;:-()[].")
    if name.casefold().startswith("the "):
        name = name[4:]
    return _bare_name(name)


def _order_scope(text: str, spans: Sequence[tuple[int, int, str, str]],
                 position: int) -> str:
    """The time scope of one assertion, or ``""`` when it states none.

    A full date wins. Otherwise a bare month name is kept as a *coarse* scope:
    ``"Brazil was ahead of India in September but behind in October"`` states
    two different scopes, and a rule that discarded them would call the
    sentence a contradiction with itself. A month with no year cannot be
    compared to a full date here; that is a documented miss, not a guessed
    match.

    A single newline is treated as a space for this reading only: a wrapped
    prose line ("India overtook\\nBrazil on 7 September") is one clause, and a
    scope that fell off at the line break would silently drop the date. The
    substitution is one-for-one, so every recorded position still addresses the
    same character.
    """
    scope_text = text.replace("\n", " ")
    start = 0
    for match in _CLAUSE_BREAK.finditer(scope_text, 0, position):
        start = match.end()
    following = _CLAUSE_BREAK.search(scope_text, position)
    end = following.start() if following is not None else len(scope_text)
    dated = [(abs(span_start - position), iso)
             for span_start, span_end, iso, _literal in spans
             if span_start >= start and span_end <= end]
    if dated:
        dated.sort()
        return dated[0][1]
    month = _BARE_MONTH.search(scope_text[start:end])
    if month is not None:
        return "month:" + month.group("month").casefold()
    return ""


def _order_assertions(text: str,
                      spans: Sequence[tuple[int, int, str, str]]
                      ) -> list[_OrderAssertion]:
    """Every explicit ordering assertion in ``text``, outermost match wins."""
    raw: list[tuple[int, int, _OrderAssertion]] = []
    for pattern, forced_negated in ((_ORDER_NEGATED_CASE, True),
                                    (_ORDER_ASSERTION, False)):
        for match in pattern.finditer(text):
            first = _order_name(match.group("a"))
            second = _order_name(match.group("b"))
            if not first or not second:
                continue
            if len(first) < 2 or len(second) < 2:
                # One-letter names are placeholders in documentation ("A was
                # ahead of B") far more often than entities. Rejecting them
                # keeps the rule's vocabulary honest without a gazetteer.
                continue
            if first.casefold() == second.casefold():
                continue
            relation = match.group("relation").casefold()
            negated = forced_negated or bool(
                _ORDER_NEGATION.search(match.group("gap")))
            raw.append((match.start(), match.end(), _OrderAssertion(
                first=first,
                second=second,
                ahead=not _ORDER_BEHIND.search(relation),
                negated=negated,
                scope=_order_scope(text, spans, match.start("relation")),
                position=match.start("relation"))))
    raw.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    kept: list[_OrderAssertion] = []
    kept_spans: list[tuple[int, int]] = []
    for start, end, assertion in raw:
        if any(start < other_end and other_start < end
               for other_start, other_end in kept_spans):
            continue
        kept.append(assertion)
        kept_spans.append((start, end))
    kept.sort(key=lambda assertion: assertion.position)
    return kept


def _order_allowed(assertion: _OrderAssertion) -> frozenset[int]:
    """The pair states this assertion permits, in canonical pair order."""
    first_key = assertion.first.casefold()
    second_key = assertion.second.casefold()
    first_is_lower = first_key <= second_key
    # ``ahead`` is stated of the first name. Translate it to canonical order.
    higher_is_first = assertion.ahead
    ahead_in_canonical = (higher_is_first if first_is_lower
                          else not higher_is_first)
    positive = frozenset(
        {_ORDER_STATE_AHEAD if ahead_in_canonical else _ORDER_STATE_BEHIND})
    return positive if not assertion.negated else _ORDER_ALL_STATES - positive


def _order_pair(assertion: _OrderAssertion) -> tuple[str, str]:
    first, second = sorted((assertion.first.casefold(),
                            assertion.second.casefold()))
    return first, second


def _same_order_scope(left: str, right: str) -> bool:
    if left == right:
        return True
    if not left or not right:
        return False
    if left.startswith("month:") or right.startswith("month:"):
        # A bare month is a different scope from a dated claim: comparing them
        # would let "in September" answer a claim about 1 September.
        return False
    return _same_date(left, right)


def _scope_text(scope: str) -> str:
    if scope.startswith("month:"):
        month = scope.split(":", 1)[1]
        return month[:1].upper() + month[1:]
    return scope


def _order_sentence(assertion: _OrderAssertion) -> str:
    relation = "ahead of" if assertion.ahead else "behind"
    negation = "not " if assertion.negated else ""
    return f"{assertion.first} was {negation}{relation} {assertion.second}"


def _order_statement_conflicts(analysed: Sequence[tuple[str, str, Inspection]]
                               ) -> list[Conflict]:
    """Two ordering assertions about one pair that cannot both be true.

    The audit's B1 has no per-entity figures, and B2 is a claim and its
    negation; neither shape reaches the numeric rules. This rule reads the
    ordering words themselves and compares the *sets of states* each assertion
    permits — so ``ahead`` against ``behind``, and ``ahead`` against ``not
    ahead``, conflict, while ``not ahead`` against ``not behind`` (consistent
    with equality) does not.

    Scope is part of the key. Two assertions about different dates or months
    are not compared: "ahead in September, behind in October" is a change, not
    a contradiction. Only assertions from *different* claims are compared, so
    one sentence cannot contradict itself.
    """
    found: list[Conflict] = []
    claims: list[tuple[str, _OrderAssertion]] = []
    seen: set[tuple[str, tuple[str, str], bool, bool, str]] = set()
    for ref, text, _inspection in analysed:
        body = text[:MAX_CLAIM_CHARS]
        spans = _date_spans(body)
        for assertion in _order_assertions(body, spans):
            # A claim that repeats the same assertion adds nothing, and a
            # pathological 8,000-character claim could otherwise turn the
            # pairwise comparison quadratic for no gain.
            key = (ref, _order_pair(assertion), assertion.ahead,
                   assertion.negated, assertion.scope)
            if key in seen:
                continue
            seen.add(key)
            claims.append((ref, assertion))
    for index, (left_ref, left) in enumerate(claims):
        for right_ref, right in claims[index + 1:]:
            if left_ref == right_ref:
                continue
            if _order_pair(left) != _order_pair(right):
                continue
            if not _same_order_scope(left.scope, right.scope):
                continue
            if _order_allowed(left) & _order_allowed(right):
                continue
            date = left.scope or right.scope
            found.append(Conflict(
                kind=_ORDER,
                left=left_ref,
                right=right_ref,
                subject=f"{left.first} / {left.second}",
                date=date,
                detail=(f"{left_ref} states {_order_sentence(left)}, but "
                        f"{right_ref} states {_order_sentence(right)}"
                        + (f" (scope: {_scope_text(date)})" if date else
                           " with no stated date"))))
    return found


def _units_compatible(left: FigureFact, right: FigureFact) -> bool:
    if left.unit and right.unit:
        return left.unit == right.unit
    # A percentage and a count are never the same quantity, even when the
    # numbers happen to be equal.
    return left.unit != "%" and right.unit != "%"


def _same_dimension(left: FigureFact, right: FigureFact) -> bool:
    """True when two figures measure the same kind of thing.

    ``million``/``billion`` are *scales*, already folded into ``canonical``;
    they are not different dimensions. ``%`` and percentage points are. This is
    what makes ``5,275,035`` and ``5.275035 million`` the same stated figure
    (OPS-5Z audit N-D) without making ``50`` and ``50%`` the same claim.
    """
    special = {"%", "pp"}
    if left.unit in special or right.unit in special:
        return left.unit == right.unit
    return True


def _same_number(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-9 * max(abs(left), abs(right), 1.0)


def _same_entity(left: FigureFact, right: FigureFact) -> bool:
    return bool(left.entity) and left.entity.casefold() == right.entity.casefold()


def _quantity_conflicts(left_ref: str, left: Inspection,
                        right_ref: str, right: Inspection) -> list[Conflict]:
    found: list[Conflict] = []
    for a in left.figures:
        for b in right.figures:
            if not (_same_entity(a, b) and a.date and b.date):
                continue
            if not _same_date(a.date, b.date):
                continue
            if not _same_dimension(a, b):
                continue
            if _same_number(a.canonical, b.canonical):
                continue
            date = a.date if len(a.date) >= len(b.date) else b.date
            found.append(Conflict(
                kind=_QUANTITY,
                left=left_ref,
                right=right_ref,
                subject=a.entity,
                date=date,
                detail=(f"{a.entity} {a.literal}{a.unit} in {left_ref} vs "
                        f"{b.literal}{b.unit} in {right_ref} on {date}")))
    return found


def _canonical_text(value: float) -> str:
    """A canonical value as a reader would write it: grouped, no lost digit."""
    if value == int(value):
        return f"{int(value):,}"
    text = f"{value:,.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _figure_text(figure: FigureFact) -> str:
    """A literal and its unit with the spacing a reader expects."""
    if figure.unit and not figure.unit.startswith("%"):
        return f"{figure.literal} {figure.unit}"
    return f"{figure.literal}{figure.unit}"


def _attribution_conflicts(left_ref: str, left: Inspection,
                           right_ref: str, right: Inspection) -> list[Conflict]:
    found: list[Conflict] = []
    for a in left.figures:
        for b in right.figures:
            if not a.entity or not b.entity:
                continue
            if a.entity.casefold() == b.entity.casefold():
                continue
            # The *quantity* is what repeats, not the surface spelling. A
            # copied figure is `5,275,035` in one claim and `5.275035 million`
            # in another; comparing literals made those two different numbers
            # and reported no conflict (OPS-5Z audit N-D).
            if not _same_dimension(a, b):
                continue
            if not _same_number(a.canonical, b.canonical):
                continue
            if a.date and b.date and not _same_date(a.date, b.date):
                continue
            if (a.date and not b.date) or (b.date and not a.date):
                continue
            # Two different subjects sharing one exact figure is the shape a
            # copied number takes. Small round numbers repeat innocently, so
            # the rule only fires on a figure with a thousand separator, a
            # decimal, or a percentage.
            if not any("," in figure.literal or "." in figure.literal
                       or figure.unit == "%" for figure in (a, b)):
                continue
            date = a.date or b.date
            found.append(Conflict(
                kind=_ATTRIBUTION,
                left=left_ref,
                right=right_ref,
                subject=f"{a.entity} / {b.entity}",
                date=date,
                detail=(f"the same quantity {_canonical_text(a.canonical)} is "
                        f"stated as {_figure_text(a)} for {a.entity} in "
                        f"{left_ref} and as {_figure_text(b)} for {b.entity} "
                        f"in {right_ref}")))
    return found


def _superlatives(text: str) -> list[tuple[str, str]]:
    claims: list[tuple[str, str]] = []
    for match in _SUPERLATIVE.finditer(text):
        subject = " ".join(match.group("subject").split())
        subject = subject.split(" ")[-1] if subject else ""
        metric = " ".join(match.group("metric").split()).casefold()
        if subject:
            claims.append((subject, metric))
    return claims


def _order_conflicts(left_ref: str, left: Inspection, left_text: str,
                     right_ref: str, right: Inspection,
                     right_text: str) -> list[Conflict]:
    found: list[Conflict] = []
    left_ranks = {subject.casefold(): metric
                  for subject, metric in _superlatives(left_text)}
    right_ranks = {subject.casefold(): metric
                   for subject, metric in _superlatives(right_text)}
    for left_subject, left_metric in left_ranks.items():
        for right_subject, right_metric in right_ranks.items():
            if left_subject == right_subject:
                continue
            if left_metric != right_metric:
                continue
            found.append(Conflict(
                kind=_ORDER,
                left=left_ref,
                right=right_ref,
                subject=f"{left_subject} / {right_subject}",
                date="",
                detail=(f"both {left_ref} and {right_ref} assert a different "
                        f"subject is the highest {left_metric or 'rank'}")))
        # A superlative contradicted by a larger peer figure on the same date.
        for figure in right.figures:
            if not figure.entity:
                continue
            if figure.entity.casefold() == left_subject:
                continue
            if not figure.date:
                continue
            own = next((item for item in left.figures
                        if item.entity.casefold() == left_subject), None)
            if own is None or not own.date:
                continue
            if not _same_date(own.date, figure.date):
                continue
            if not _units_compatible(own, figure):
                continue
            if figure.canonical <= own.canonical:
                continue
            found.append(Conflict(
                kind=_ORDER,
                left=left_ref,
                right=right_ref,
                subject=f"{left_subject} / {figure.entity}",
                date=figure.date,
                detail=(f"{left_ref} calls {left_subject} the highest, but "
                        f"{right_ref} gives {figure.entity} "
                        f"{figure.literal}{figure.unit} > {own.literal}"
                        f"{own.unit} on {figure.date}")))
    return found


def _lead_conflicts(analysed: Sequence[tuple[str, str, Inspection]]
                    ) -> list[Conflict]:
    """An "A ahead of B" assertion the figures on that date reverse.

    Read over the *whole* set, not one pair: the incident shape is one claim
    carrying the numbers and another carrying the ordering, and a pair-wise
    scan never sees both sides of that. A lead assertion with no figure for
    one side is not refutable here and is left alone.
    """
    figures = [(ref, figure) for ref, _text, inspection in analysed
               for figure in inspection.figures]
    found: list[Conflict] = []
    for ref, text, _inspection in analysed:
        for match in _LEAD.finditer(text):
            leader = match.group("a").casefold()
            trailer = match.group("b").casefold()
            if leader == trailer:
                continue
            for _lead_ref, lead_figure in figures:
                if lead_figure.entity.casefold() != leader:
                    continue
                if not lead_figure.date:
                    continue
                for behind_ref, behind_figure in figures:
                    if behind_figure.entity.casefold() != trailer:
                        continue
                    if not _same_date(lead_figure.date,
                                      behind_figure.date):
                        continue
                    if not _units_compatible(lead_figure, behind_figure):
                        continue
                    if behind_figure.canonical <= lead_figure.canonical:
                        continue
                    found.append(Conflict(
                        kind=_ORDER,
                        left=ref,
                        right=behind_ref,
                        subject=f"{leader} / {trailer}",
                        date=lead_figure.date,
                        detail=(f"{ref} says {match.group('a')} was ahead "
                                f"of {match.group('b')}, but {behind_ref} "
                                f"gives {behind_figure.literal}"
                                f"{behind_figure.unit} for "
                                f"{match.group('b')} against "
                                f"{lead_figure.literal}{lead_figure.unit} "
                                f"for {match.group('a')} on "
                                f"{lead_figure.date}")))
    return found


def _dedupe(conflicts: Iterable[Conflict]) -> tuple[Conflict, ...]:
    """Distinct conflicts, deterministically ordered — never capped here.

    The cap belongs to the capability that reports a bounded payload, because
    only it can say how many conflicts it did not return. Capping in the pure
    function made the count indistinguishable from the truth (OPS-5Z audit
    N-H: 136 conflicts, 16 returned, nothing said so).
    """
    seen: set[tuple[str, str, str, str, str]] = set()
    kept: list[Conflict] = []
    for conflict in conflicts:
        key = (conflict.kind, conflict.left, conflict.right,
               conflict.subject.casefold(), conflict.date)
        if key in seen:
            continue
        seen.add(key)
        kept.append(conflict)
    kept.sort(key=lambda item: (item.kind, item.date, item.subject.casefold(),
                                item.left, item.right))
    return tuple(kept)


def conflicts_between(claims: Sequence[ClaimText]) -> tuple[Conflict, ...]:
    """Every pair of ``claims`` that cannot both be true. Pure.

    Four rules, all numeric or lexical and all replayable:

    * ``QUANTITY`` — same subject, same date, different figures;
    * ``ATTRIBUTION`` — the same stated quantity on two different subjects;
    * ``ORDER`` — mutually exclusive superlatives, a superlative a larger
      peer figure on the same date contradicts, an "A ahead of B" assertion
      the figures on that date reverse, or two ordering assertions about the
      same pair and scope that cannot both hold (including a claim and its
      negation).

    The returned sequence is **complete**: the caller bounds what it renders
    and reports the total. A conflict is a *report*. It does not rank the
    claims, decide which side rests on a weaker source, or suppress either.
    """
    analysed = [
        (claim.ref, claim.text[:MAX_CLAIM_CHARS], facts_in(claim.text))
        for claim in claims[:MAX_SCAN_CLAIMS]]
    found: list[Conflict] = []
    for index in range(len(analysed)):
        left_ref, left_text, left = analysed[index]
        for other in range(index + 1, len(analysed)):
            right_ref, right_text, right = analysed[other]
            found.extend(_quantity_conflicts(left_ref, left,
                                             right_ref, right))
            found.extend(_attribution_conflicts(left_ref, left,
                                                right_ref, right))
            found.extend(_order_conflicts(left_ref, left, left_text,
                                          right_ref, right, right_text))
    found.extend(_lead_conflicts(analysed))
    found.extend(_order_statement_conflicts(analysed))
    return _dedupe(found)


def describe_conflicts(conflicts: Sequence[Conflict],
                       claims_read: int, total: int | None = None) -> str:
    """The bounded, model-visible summary of one scan.

    ``total`` is how many conflicts the scan produced before the payload cap;
    when it exceeds ``len(conflicts)`` the note says so. A prefix presented as
    the whole set is the silent-truncation false pass (OPS-5Z audit N-H).
    """
    if not conflicts:
        return _bound(f"read {claims_read} claim(s); no conflict found by the "
                      f"numeric, attribution or ordering rules")
    shown = (f"showing {len(conflicts)} of {total}" if total is not None
             and total > len(conflicts) else "")
    parts = [f"read {claims_read} claim(s); "
             f"{total if total is not None else len(conflicts)} conflict(s)"
             + (f"; {shown} — the rest are counted, not shown" if shown else "")]
    for conflict in conflicts:
        parts.append(f"{conflict.kind} {conflict.left} vs {conflict.right}: "
                     f"{conflict.detail}")
    return _bound("; ".join(parts))


# ── arithmetic ──

#: A number in prose: grouped thousands or plain digits, optional decimal.
#: The grouped form must end on a digit, so a trailing comma is punctuation.
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"

_PERCENT_OF = re.compile(
    rf"(?P<p>-?{_NUM})\s*(?:%|percent(?:age\s+points?)?)\s+of\s+"
    rf"(?P<base>{_NUM})", re.IGNORECASE)
_OUT_OF = re.compile(
    rf"(?P<a>{_NUM})\s+(?:out of|of)\s+"
    rf"(?P<b>{_NUM})\s*(?:,|is|was|=)?\s*(?:or\s+)?"
    rf"(?P<c>{_NUM})\s*(?:%|percent)", re.IGNORECASE)
_ASSERTED = re.compile(
    rf"(?:=|equals|is|was|amounts?\s+to|totals?|gives?|comes?\s+to|"
    rf"works?\s+out\s+to|or)\s+(?P<r>-?{_NUM})\s*(?P<unit>%|"
    rf"percent(?:age\s+points?)?)?", re.IGNORECASE)
_CHANGE_FROM_TO = re.compile(
    rf"from\s+(?P<a>{_NUM})\s+to\s+(?P<b>{_NUM})", re.IGNORECASE)
_CHANGE_BY = re.compile(
    rf"(?P<verb>rose|increased|grew|fell|decreased|declined|dropped|"
    rf"was\s+up|was\s+down|up|down)\s+by\s+"
    rf"(?P<p>{_NUM})\s*(?:%|percent)", re.IGNORECASE)
_DIFFERENCE = re.compile(
    rf"(?:difference\s+(?:between|of)\s+)?(?P<a>{_NUM})\s+"
    rf"(?:minus|less)\s+(?P<b>{_NUM})\s+"
    rf"(?:=|is|was|equals)\s+(?P<c>{_NUM})", re.IGNORECASE)
_RATIO = re.compile(
    rf"(?P<a>{_NUM})\s+(?:per|for\s+every)\s+"
    rf"(?P<b>{_NUM})\s*(?:=|is|was|equals)\s+"
    rf"(?P<c>{_NUM})", re.IGNORECASE)
_TOTAL_WORD = re.compile(
    r"\b(?:total|totals|sum|sums|combined|altogether|in\s+all)\b",
    re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ArithmeticVerdict:
    """What ``check_derivation`` decided, with both numbers.

    ``status`` is one of ``CONSISTENT``, ``INCONSISTENT``, ``UNPARSEABLE``
    (no derivation pattern was found) or ``NO_BASIS`` (a pattern was found but
    a base figure is missing). Only the first two are verdicts about the
    arithmetic; the last two say the check could not run, which is a different
    statement and is never reported as agreement.
    """

    status: str
    operator: str
    asserted: str
    computed: float | None
    detail: str


CONSISTENT = "CONSISTENT"
INCONSISTENT = "INCONSISTENT"
UNPARSEABLE = "UNPARSEABLE"
NO_BASIS = "NO_BASIS"


def _number(literal: str) -> float:
    return float(literal.replace(",", ""))


def _decimals(literal: str) -> int:
    return len(literal.split(".", 1)[1]) if "." in literal else 0


def _close(computed: float, literal: str) -> bool:
    """Half a unit in the asserted figure's last stated place.

    Rounding is agreement; a changed digit is not. ``33.3`` against a computed
    ``33.333...`` passes (one decimal, tolerance 0.05); ``9,742,469`` against
    ``9,742,468`` fails (integer, tolerance 0.5).
    """
    asserted = _number(literal)
    tolerance = 0.5 * (10 ** -_decimals(literal)) + 1e-9
    return abs(computed - asserted) <= tolerance


def _verdict(operator: str, asserted: str, computed: float,
             formula: str) -> ArithmeticVerdict:
    status = CONSISTENT if _close(computed, asserted) else INCONSISTENT
    return ArithmeticVerdict(
        status=status,
        operator=operator,
        asserted=asserted,
        computed=computed,
        detail=(f"{formula} = {computed:.6g}; asserted {asserted} — "
                f"{status.casefold()}"))


def _asserted_after(text: str, start: int) -> str:
    match = _ASSERTED.search(text, start)
    return match.group("r") if match is not None else ""


def check_derivation(statement: str,
                     bases: Sequence[FigureFact] = ()) -> ArithmeticVerdict:
    """Recompute a derived figure and compare it to the one asserted. Pure.

    Tried in order, first structural match wins: ``out of ... or X%``,
    ``X% of Y is Z``, ``from A to B ... by X%``, ``A minus B is C``,
    ``A per B is C``, and a stated total over stated components. ``bases``
    supplies components extracted from another artifact when the statement
    names only the total — the case where the arithmetic lives in one source
    and the components in another.

    Unparseable is not a pass: it is ``UNPARSEABLE``, and a missing base is
    ``NO_BASIS``. The capability exists so that "I could not check" is
    distinguishable from "I checked and it holds".
    """
    text = statement[:MAX_CLAIM_CHARS]
    figures = facts_in(text).figures

    match = _OUT_OF.search(text)
    if match is not None:
        part, whole, stated = (match.group("a"), match.group("b"),
                               match.group("c"))
        if _number(whole) == 0:
            return ArithmeticVerdict(
                status=NO_BASIS, operator="percent_of",
                asserted=stated, computed=None,
                detail="the whole is zero; a percentage is undefined")
        computed = _number(part) / _number(whole) * 100.0
        return _verdict("percent_of", stated, computed,
                        f"({part} / {whole}) * 100")

    match = _PERCENT_OF.search(text)
    if match is not None:
        percent, base = match.group("p"), match.group("base")
        stated = _asserted_after(text, match.end())
        if not stated:
            return ArithmeticVerdict(
                status=UNPARSEABLE, operator="percent_of", asserted="",
                computed=None,
                detail=(f"{percent}% of {base} states no result to check — "
                        "an unasserted computation is not a claim"))
        computed = _number(percent) / 100.0 * _number(base)
        return _verdict("percent_of", stated, computed,
                        f"{percent}% of {base}")

    match = _CHANGE_FROM_TO.search(text)
    if match is not None:
        before, after = match.group("a"), match.group("b")
        stated_match = _CHANGE_BY.search(text)
        if stated_match is not None and _number(before) != 0:
            stated, verb = stated_match.group("p"), stated_match.group("verb")
            computed = ((_number(after) - _number(before))
                        / _number(before) * 100.0)
            direction_up = computed > 0
            says_up = verb.casefold() in {"rose", "increased", "grew", "up",
                                          "was up"}
            if direction_up != says_up:
                return ArithmeticVerdict(
                    status=INCONSISTENT, operator="percent_change",
                    asserted=stated, computed=computed,
                    detail=(f"from {before} to {after} is a "
                            f"{computed:.6g}% change but the text says "
                            f"{verb} by {stated}% — the direction is wrong"))
            return _verdict("percent_change", stated, abs(computed),
                            f"({after} - {before}) / {before} * 100")
        return ArithmeticVerdict(
            status=UNPARSEABLE, operator="percent_change", asserted="",
            computed=None,
            detail=(f"from {before} to {after} states no percentage, and no "
                    "percentage is a claim to check"))

    match = _DIFFERENCE.search(text)
    if match is not None:
        return _verdict("difference", match.group("c"),
                        _number(match.group("a")) - _number(match.group("b")),
                        f"{match.group('a')} - {match.group('b')}")

    match = _RATIO.search(text)
    if match is not None:
        divisor = _number(match.group("b"))
        if divisor == 0:
            return ArithmeticVerdict(
                status=NO_BASIS, operator="ratio", asserted=match.group("c"),
                computed=None, detail="the divisor is zero; the ratio is "
                "undefined")
        return _verdict("ratio", match.group("c"),
                        _number(match.group("a")) / divisor,
                        f"{match.group('a')} / {match.group('b')}")

    if _TOTAL_WORD.search(text):
        asserted_figures = [
            figure for figure in figures
            if _TOTAL_WORD.search(
                text[max(0, figure.position - 24):figure.position])]
        if not asserted_figures and len(figures) >= 2:
            asserted_figures = [figures[-1]]
        if asserted_figures:
            asserted = asserted_figures[0]
            operands = [figure for figure in figures
                        if figure is not asserted]
            if len(operands) < 2 and bases:
                operands = list(bases)
            if len(operands) < 2:
                return ArithmeticVerdict(
                    status=NO_BASIS, operator="sum", asserted=asserted.literal,
                    computed=None,
                    detail=(f"a total of {asserted.literal} is stated but "
                            f"{len(operands)} component(s) were found — "
                            "nothing to add"))
            computed = sum(figure.canonical for figure in operands)
            formula = " + ".join(figure.literal for figure in operands)
            return _verdict("sum", asserted.literal, computed, formula)

    return ArithmeticVerdict(
        status=UNPARSEABLE,
        operator="",
        asserted="",
        computed=None,
        detail=("no derivation pattern was found (a percentage of, a change "
                "from/to, a difference, a ratio, or a stated total over its "
                "components)"),
    )


def describe_verdict(verdict: ArithmeticVerdict) -> str:
    """The bounded, model-visible summary of one arithmetic check."""
    operator = f" ({verdict.operator})" if verdict.operator else ""
    return _bound(f"{verdict.status}{operator}: {verdict.detail}")
