"""Market Lens: deterministic helpers that turn stored claims into calendar entries, language rows and comparison rows.

No model, no network, no database: these functions read `ClaimView`s and return plain structures, so every rule is
testable on its own. They never set confidence and never choose between disagreeing claims.
"""

import re
from collections import defaultdict
from datetime import date
from typing import Any

from app.schemas import lens as v
from app.schemas.regions import ClaimView

MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
_MONTH_ALIASES = {
    **{name: i + 1 for i, name in enumerate(MONTH_NAMES)},
    **{name[:3]: i + 1 for i, name in enumerate(MONTH_NAMES) if name != "May"},
    "Sept": 9,
}
# ponytail: case-sensitive whole-word match; a sentence that starts with "May" would read as the month. The curated
# texts do not, and a wrong month only widens "may overlap" hints, never a date. Upgrade: a small month-in-context rule.
_MONTH_RE = re.compile(r"\b(" + "|".join(sorted(_MONTH_ALIASES, key=len, reverse=True)) + r")\b\.?")
_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_DAY_MONTH = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTH_NAMES) + r")$")
_MONTH_DAY = re.compile(r"^(" + "|".join(MONTH_NAMES) + r")\s+(\d{1,2})(?:st|nd|rd|th)?$")
TIMING_KEYS = ("month_text", "date_text", "date_stated", "dates_stated", "period")
NAMED_ATTRIBUTES = {"major_festival", "cultural_moment"}
HOLIDAY_ATTRIBUTE = "public_holiday_date"


# --- calendar ----------------------------------------------------------------------------------------------------


def months_named(text: str) -> list[int]:
    """Months a timing text names, in calendar order. Text with a year in it describes a past event, not a recurring
    time, so it names no months (the text is still shown as written)."""
    if _YEAR_RE.search(text):
        return []
    return sorted({_MONTH_ALIASES[m.group(1)] for m in _MONTH_RE.finditer(text)})


def parse_fixed_date(text: str, year: int) -> date | None:
    """`1 May`, `May 1` or `14th January` -> that day in `year`. Anything else (ranges, `14 or 15 April`, text with a year,
    lunar or regional-calendar wording) is not a date and returns None."""
    clean = " ".join(text.strip().split())
    match = _DAY_MONTH.match(clean)
    day, month = (int(match.group(1)), match.group(2)) if match else (None, None)
    if match is None:
        match = _MONTH_DAY.match(clean)
        if match is None:
            return None
        day, month = int(match.group(2)), match.group(1)
    try:
        return date(year, MONTH_NAMES.index(month) + 1, day)
    except ValueError:
        return None


def claim_name(view: ClaimView) -> str | None:
    """The thing a claim names: `value.name` (or `topic`), else the string value."""
    value = view.value
    if isinstance(value, dict):
        name = value.get("name") or value.get("topic")
        return str(name) if name else None
    return value if isinstance(value, str) else None


def timing_text(view: ClaimView) -> str | None:
    """The timing a claim states, verbatim, or None when the claim says nothing about when."""
    value = view.value
    if not isinstance(value, dict):
        return None
    for key in TIMING_KEYS:
        raw = value.get(key)
        if isinstance(raw, list):
            raw = "; ".join(str(x) for x in raw)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _in_window(day: date, window: v.LensWindow | None) -> bool | None:
    return None if window is None else window.date_from <= day <= window.date_to


def window_months(window: v.LensWindow) -> set[int]:
    months: set[int] = set()
    day = window.date_from.replace(day=1)
    while day <= window.date_to:
        months.add(day.month)
        day = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return months


def calendar_entries(
    views: list[ClaimView], *, year: int, window: v.LensWindow | None
) -> tuple[list[v.LensDatedMoment], list[v.LensTimedMoment]]:
    """Dated entries for `year` and the festivals and moments sources describe without an exact date.

    Dated: public-holiday claims whose scope period is `year`, plus curated moments whose source text is a plain day and
    month (an annual date; the year is the requested one). Timed: one entry per festival or moment subject, listing every
    timing statement as written, the months it names, and any public-holiday date linked to it."""
    dated: list[v.LensDatedMoment] = []
    holiday_dates: dict[str, list[date]] = defaultdict(list)
    for view in views:
        value = view.value if isinstance(view.value, dict) else {}
        if view.attribute == HOLIDAY_ATTRIBUTE and view.scope.period == str(year) and value.get("date"):
            day = date.fromisoformat(str(value["date"]))
            festival = value.get("curated_festival")
            dated.append(v.LensDatedMoment(
                key=f"{view.subject}:{day.isoformat()}", name=str(value.get("name") or view.subject), subject=view.subject,
                date=day, date_basis="public_holiday_list", festival_subject=festival, in_window=_in_window(day, window), claim=view,
                also_stated_by=[]))
            if festival:
                holiday_dates[festival].append(day)
    by_subject: dict[str, list[ClaimView]] = defaultdict(list)
    for view in views:
        if view.category in ("festival", "moment") and view.attribute != HOLIDAY_ATTRIBUTE:
            by_subject[view.subject].append(view)
    timed: list[v.LensTimedMoment] = []
    for subject, claims in by_subject.items():
        named = next((c for c in claims if c.attribute in NAMED_ATTRIBUTES and claim_name(c)), None) or next(
            (c for c in claims if isinstance(c.value, dict) and claim_name(c)), None)
        if named is None:
            continue  # only string-valued claims (for example a relative-day statement): reported through conflicts
        timings = [(text, c) for c in claims if (text := timing_text(c))]
        fixed = [(parse_fixed_date(text, year), text, c) for text, c in timings]
        for day, _, claim in fixed:
            if day is not None:
                dated.append(v.LensDatedMoment(
                    key=f"{subject}:{day.isoformat()}", name=claim_name(named) or subject, subject=subject, date=day,
                    date_basis="source_text", festival_subject=subject if subject.startswith("festival:") else None,
                    in_window=_in_window(day, window), claim=claim, also_stated_by=[]))
        remaining = [(text, c) for day, text, c in fixed if day is None]
        months = sorted({m for text, _ in remaining for m in months_named(text)})
        overlap = None if window is None else bool(set(months) & window_months(window)) or any(
            d for d in holiday_dates.get(subject, []) if _in_window(d, window))
        if not remaining and any(day is not None for day, _, _ in fixed):
            continue  # fully described by an annual date already placed on the calendar
        timed.append(v.LensTimedMoment(
            subject=subject, name=claim_name(named) or subject,
            timings=[v.LensTiming(text=text, attribute=c.attribute, claim=c) for text, c in remaining], months_named=months,
            dated_for_year=sorted(set(holiday_dates.get(subject, []))), may_overlap_window=overlap,
            conflict_ids=sorted({cid for c in claims for cid in c.conflict_ids}, key=str)))
    merged: dict[str, v.LensDatedMoment] = {}
    for entry in dated:  # the public-holiday entry comes first; a source text giving the same date is kept as a second claim
        if entry.key in merged:
            merged[entry.key].also_stated_by.append(entry.claim)
        else:
            merged[entry.key] = entry
    dated = sorted(merged.values(), key=lambda d: (d.date, d.name, d.key))
    timed.sort(key=lambda t: (min(t.months_named) if t.months_named else 13, t.name))
    return dated, timed


def months_of(dated: list[v.LensDatedMoment]) -> list[v.LensCalendarMonth]:
    return [
        v.LensCalendarMonth(month=i + 1, name=name, dated=[d for d in dated if d.date.month == i + 1])
        for i, name in enumerate(MONTH_NAMES)
    ]


# --- language map ------------------------------------------------------------------------------------------------

_SHARE_NAME = re.compile(r"^In the 2011 census, (.+?) was the mother tongue of ")


def share_language_name(view: ClaimView) -> str:
    """Display name of the language a census share claim is about. The census adapter writes it into the statement; a
    language without an ISO code is identified by its subject slug, which is the fallback."""
    match = _SHARE_NAME.match(view.value_text)
    if match:
        return match.group(1)
    slug = view.subject.split(":", 1)[-1]
    return slug.replace("_", " ").title()


def language_key(view: ClaimView) -> str:
    return view.scope.language or view.subject


# --- comparison --------------------------------------------------------------------------------------------------

COMPARE_ROWS: tuple[tuple[str, str, tuple[str, ...], frozenset[str]], ...] = (
    ("languages", "Languages", ("language",), frozenset({"principal_language", "official_language", "language_share"})),
    ("festivals", "Festivals", ("festival",), frozenset({"major_festival"})),
    ("moments", "Cultural moments", ("moment",), frozenset({"cultural_moment"})),
    ("food", "Food", ("food",), frozenset({"festive_food", "staple_food"})),
    ("colour_symbol", "Colours and symbols", ("colour", "symbol"), frozenset({"colour_association", "symbol_association"})),
    ("humour", "Humour and tone", ("humour",), frozenset({"humour_style"})),
    ("family_custom", "Family roles and customs", ("family", "custom"), frozenset({"family_custom", "custom"})),
    ("sensitivity", "Sensitivities", ("sensitivity",), frozenset({"sensitivity"})),
)
CELL_LIMIT = 12
TOP_SHARES = 3


def item_label(view: ClaimView) -> str:
    if view.attribute == "language_share" and isinstance(view.value, int | float):
        return f"{share_language_name(view)}: {view.value:g}% of the population (2011)"
    name = claim_name(view)
    if name:
        return name
    text = view.value_text
    return text if len(text) <= 90 else text[:89] + "…"


def _subject_key(view: ClaimView) -> str:
    return f"{view.subject}|{view.scope.language}" if view.attribute == "language_share" else view.subject


def _row_claims(views: list[ClaimView], categories: tuple[str, ...], attributes: frozenset[str]) -> list[ClaimView]:
    picked = [c for c in views if c.category in categories and c.attribute in attributes]
    shares = sorted((c for c in picked if c.attribute == "language_share" and isinstance(c.value, int | float)),
                    key=lambda c: (-float(c.value), share_language_name(c), str(c.id)))
    keep = {c.id for c in shares[:TOP_SHARES]}
    return [c for c in picked if c.attribute != "language_share" or c.id in keep]


def _newest(view: ClaimView) -> date | None:
    dates = [s.published_at or s.retrieved_at.date() for s in view.sources]
    return max(dates) if dates else None


def compare_rows(profiles: dict[str, list[ClaimView]]) -> list[v.LensCompareRow]:
    """Side-by-side rows over the same dimensions for every compared state. A state with no claim in a dimension gets a
    `missing` cell, which says the evidence is missing and nothing about the state. `also_in` and `shared_subjects` count
    only subjects that have a sourced claim; they never imply two things mean the same."""
    codes = list(profiles)
    rows: list[v.LensCompareRow] = []
    for key, title, categories, attributes in COMPARE_ROWS:
        picked = {code: _row_claims(profiles[code], categories, attributes) for code in codes}
        subjects = {code: {_subject_key(c) for c in claims} for code, claims in picked.items()}
        cells = []
        for code in codes:
            ordered = sorted(picked[code], key=lambda c: (item_label(c).casefold(), str(c.id)))
            items = [
                v.LensCompareItem(
                    label=item_label(c), subject=c.subject, attribute=c.attribute, claim_id=c.id, kind=c.kind,
                    confidence=c.effective_confidence, source_count=len(c.sources), newest_source_date=_newest(c), stale=c.stale,
                    in_conflict=bool(c.conflict_ids),
                    also_in=[o for o in codes if o != code and _subject_key(c) in subjects[o]])
                for c in ordered[:CELL_LIMIT]
            ]
            cells.append(v.LensCompareCell(region_code=code, total=len(ordered), items=items, missing=not ordered))
        shared = set.intersection(*subjects.values()) if subjects else set()
        rows.append(v.LensCompareRow(key=key, title=title, categories=list(categories), cells=cells, shared_subjects=len(shared)))
    return rows


# --- sources -----------------------------------------------------------------------------------------------------

SOURCE_INFO: dict[str, tuple[str, str, list[str]]] = {
    "census_2011": (
        "Census of India 2011", "Mother-tongue counts, table C-16, by state.",
        ["2011 data: more than a decade old, never a current language mix.",
         "Mother tongue is not proficiency, media language or purchase language.", "State level only: no city tier or age split."]),
    "holidays_package": (
        "Public holidays (python-holidays)", "Dates of notified public holidays by state, from an open-source package.",
        ["Only observances declared public holidays; many festivals are not.",
         "Movable dates follow the package release: verify before a launch."]),
    "curated_reference": (
        "Curated reference pages", "Short cited excerpts from government tourism pages and fact sheets, read on the date shown.",
        ["A snapshot, not a feed.", "Four states only.", "Mostly English-language sources; no native review."]),
    "wikipedia": (
        "Wikipedia", "Short cited excerpts (CC BY-SA 4.0) with the page as attribution.",
        ["Community-edited. All Wikimedia pages count as one independent source group."]),
    "wikidata": (
        "Wikidata", "Structured links between states, festivals and places (CC0).",
        ["Coverage is thin: many festivals carry no state link."]),
    "wikipedia_pageviews": (
        "Wikipedia pageviews", "How often articles about festivals were read.",
        ["Attention, not demand, purchase intent or market size."]),
    "gemini_grounding": (
        "Gemini with Google Search grounding", "Model summaries of web pages, with their citations.",
        ["Always an interpretation: the cited pages are not fetched or quoted here.", "Answers vary between runs."]),
}


def summarise_sources(views: list[ClaimView]) -> list[v.LensSourceSummary]:
    """One row per source family across the claims on a page, with its dates and its limits."""
    groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"claims": set(), "sources": set(), "published": [], "retrieved": []})
    for view in views:
        for source in view.sources:
            g = groups[source.source_type]
            g["claims"].add(view.id)
            g["sources"].add(source.source_identifier)
            if source.published_at:
                g["published"].append(source.published_at)
            g["retrieved"].append(source.retrieved_at)
    out = []
    for source_type, g in sorted(groups.items()):
        label, description, limits = SOURCE_INFO.get(source_type, (source_type, "", []))
        out.append(v.LensSourceSummary(
            source_type=source_type, label=label, description=description, claims=len(g["claims"]), sources=len(g["sources"]),
            newest_published_at=max(g["published"], default=None), oldest_published_at=min(g["published"], default=None),
            newest_retrieved_at=max(g["retrieved"], default=None), limitations=limits))
    return out
