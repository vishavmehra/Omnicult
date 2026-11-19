"""Trend Radar arithmetic: monthly attention series in, a stated direction out.

Pure functions, no model, no network, no database. The input is a series of Wikipedia pageviews (attention, never search
volume and never demand); the output says what the numbers did over named windows, with the method and thresholds in plain
sight so a reader can check it. Nothing here forecasts: a "rising" label describes the past year, not the next one.

Method `attention-windows-v2`:

* The series is monthly, 24 whole months ending with the last complete month. Months before the first observed month are
  "no article yet" and are left out; a month inside the series that the API did not return had no recorded views and counts
  as zero.
* Attention is read as a share of the edition's own readership (views per million edition views), because the regional
  Wikipedias have lost a third or more of their readers in a year and every article falls with them. Where the edition's
  totals are missing the raw views are used and the result says it is not adjusted.
* Festival articles peak around the festival, and a lunar festival moves from year to year, so a short window mostly measures
  where the festival fell. The reading therefore compares whole years: `recent` is the last 12 months, `prior` the 12 before.
  `change` is mean(recent) / mean(prior) - 1 on that share. A series needs all 24 months to be read.
* `slope` is the least-squares line through every month of the series, as a share of the series mean per month.
* rising: change >= +20% and slope > 0. falling: change <= -20% and slope < 0. steady: change within +-20%. mixed: the change
  crossed +-20% but the slope points the other way. insufficient: fewer than 24 months, or fewer than 30 views a month in both
  years.
* `quarter_change` is the last three months against the same three months a year earlier. It is shown beside the label as
  "lately" and, when it points clearly the other way, says so; it never changes the label.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Literal
from urllib.parse import unquote, urlparse

METHOD_VERSION = "attention-windows-v2"
YEAR_MONTHS = 12
QUARTER_MONTHS = 3
MIN_MONTHS = 2 * YEAR_MONTHS
CHANGE_THRESHOLD = 0.20
MIN_MEAN_VIEWS = 30.0  # below this in both years a percentage change is noise
THIN_MEAN_VIEWS = 100.0  # below this the direction is shown with Low confidence
SOLID_MEAN_VIEWS = 300.0

Direction = Literal["rising", "falling", "steady", "mixed", "insufficient"]
Level = Literal["low", "moderate", "high"]


@dataclass(frozen=True)
class MonthPoint:
    month: date  # first day of the month
    views: int


@dataclass
class Measure:
    direction: Direction
    months: int  # months in the series, gaps filled
    first_month: date | None
    last_month: date | None
    normalised: bool = False  # read as a share of the edition's readership
    recent_mean: float | None = None  # mean monthly views, last 12 months (always raw views)
    prior_mean: float | None = None  # mean monthly views, the 12 before
    raw_change: float | None = None  # raw views, recent / prior - 1
    edition_change: float | None = None  # the whole edition's views, recent / prior - 1
    recent_share: float | None = None  # mean views per million edition views, last 12 months
    prior_share: float | None = None
    change: float | None = None  # recent / prior - 1 on the basis the label uses (share when normalised, else raw views)
    slope_per_month: float | None = None  # slope as a share of the series mean, per month, on that basis
    quarter_change: float | None = None  # last 3 months against the same 3 months a year earlier, on that basis
    recent_window: tuple[date, date] | None = None  # first day of the first month, first day of the last month
    prior_window: tuple[date, date] | None = None
    quarter_window: tuple[date, date] | None = None
    quarter_year_ago_window: tuple[date, date] | None = None
    reasons: list[str] = field(default_factory=list)


def month_start(day: date) -> date:
    return day.replace(day=1)


def add_months(day: date, n: int) -> date:
    index = day.year * 12 + (day.month - 1) + n
    return date(index // 12, index % 12 + 1, 1)


def monthly(points: list[tuple[date, int]]) -> list[MonthPoint]:
    """Daily or monthly points to one point per calendar month, internal gaps filled with zero.

    Months before the first point are not invented, and the series ends with its last point."""
    totals: dict[date, int] = {}
    for day, views in points:
        totals[month_start(day)] = totals.get(month_start(day), 0) + views
    if not totals:
        return []
    out: list[MonthPoint] = []
    month, last = min(totals), max(totals)
    while month <= last:
        out.append(MonthPoint(month, totals.get(month, 0)))
        month = add_months(month, 1)
    return out


def _mean(values: list[int]) -> float:
    return sum(values) / len(values)


def _slope(values: list[int]) -> float:
    """Least-squares slope as a share of the series mean per month; 0 for a flat or empty series."""
    n = len(values)
    mean = _mean(values)
    if n < 2 or mean == 0:
        return 0.0
    x_mean = (n - 1) / 2
    num = sum((x - x_mean) * (y - mean) for x, y in zip(range(n), values, strict=True))
    den = sum((x - x_mean) ** 2 for x in range(n))
    return (num / den) / mean


def _opposed(direction: Direction, quarter_change: float) -> bool:
    if direction == "rising":
        return quarter_change <= -CHANGE_THRESHOLD
    if direction == "falling":
        return quarter_change >= CHANGE_THRESHOLD
    return abs(quarter_change) >= CHANGE_THRESHOLD  # steady over the year, but the last quarter moved a lot


def measure(series: list[MonthPoint], baseline: list[MonthPoint] | None = None) -> Measure:
    """The direction of attention over the series, with every number the label rests on.

    `baseline` is the edition's total views for the same months; when it covers every month the series is read as a share of it."""
    if not series:
        return Measure("insufficient", 0, None, None, reasons=["No pageviews were recorded for this article in the period."])
    raw = [p.views for p in series]
    out = Measure("insufficient", len(series), series[0].month, series[-1].month)
    if len(series) < MIN_MONTHS:
        out.reasons.append(
            f"Only {len(series)} months of data; {MIN_MONTHS} are needed to compare a year with the year before it.")
        return out
    last = series[-1].month
    out.recent_window = (add_months(last, 1 - YEAR_MONTHS), last)
    out.prior_window = (add_months(last, 1 - 2 * YEAR_MONTHS), add_months(last, -YEAR_MONTHS))
    out.quarter_window = (add_months(last, 1 - QUARTER_MONTHS), last)
    out.quarter_year_ago_window = (add_months(last, 1 - QUARTER_MONTHS - YEAR_MONTHS), add_months(last, -YEAR_MONTHS))
    out.recent_mean, out.prior_mean = _mean(raw[-YEAR_MONTHS:]), _mean(raw[-2 * YEAR_MONTHS:-YEAR_MONTHS])
    if out.prior_mean > 0:
        out.raw_change = out.recent_mean / out.prior_mean - 1
    totals = {p.month: p.views for p in baseline or []}
    values: list[float] = [float(v) for v in raw]
    if totals and all(totals.get(p.month, 0) > 0 for p in series):
        out.normalised = True
        edition = [totals[p.month] for p in series]
        values = [v / t * 1_000_000 for v, t in zip(raw, edition, strict=True)]
        out.recent_share, out.prior_share = _mean(values[-YEAR_MONTHS:]), _mean(values[-2 * YEAR_MONTHS:-YEAR_MONTHS])
        out.edition_change = _mean(edition[-YEAR_MONTHS:]) / _mean(edition[-2 * YEAR_MONTHS:-YEAR_MONTHS]) - 1
    else:
        out.reasons.append(
            "The edition's total readership was not available, so the direction is raw views, not adjusted for a fall or rise of the whole edition.")
    out.slope_per_month = _slope(values)
    quarter, quarter_ago = _mean(values[-QUARTER_MONTHS:]), _mean(values[-YEAR_MONTHS - QUARTER_MONTHS:-YEAR_MONTHS])
    if quarter_ago > 0:
        out.quarter_change = quarter / quarter_ago - 1
    if max(out.recent_mean, out.prior_mean) < MIN_MEAN_VIEWS:
        out.reasons.insert(0, f"Fewer than {MIN_MEAN_VIEWS:.0f} views a month in both years: too few to read a direction.")
        return out
    recent, prior = (out.recent_share, out.prior_share) if out.normalised else (out.recent_mean, out.prior_mean)
    if not prior:
        out.reasons.insert(0, "No views in the earlier year, so there is nothing to compare the last year with.")
        return out
    out.change = recent / prior - 1  # type: ignore[operator]
    slope = out.slope_per_month
    if out.change >= CHANGE_THRESHOLD:
        out.direction = "rising" if slope > 0 else "mixed"
    elif out.change <= -CHANGE_THRESHOLD:
        out.direction = "falling" if slope < 0 else "mixed"
    else:
        out.direction = "steady"
    if out.direction == "mixed":
        out.reasons.insert(0, "The last year moved by more than 20% but the slope through the two years points the other way.")
    elif out.quarter_change is not None and _opposed(out.direction, out.quarter_change):
        out.reasons.insert(0, (
            f"The last three months are {abs(out.quarter_change):.0%} {'below' if out.quarter_change < 0 else 'above'} "
            "the same months a year earlier, which points the other way."))
    return out


def confidence(primary: Measure, secondary: Measure | None, *, fixture: bool) -> tuple[Level, list[str]]:
    """How firmly the data supports the stated direction. Never a probability and never a forecast.

    Low: the direction is insufficient or mixed, or the counts are small. Moderate: two full years at 100+ views a month.
    High needs every available view to agree: 300+ views a month, and the last three months and the English edition not
    pointing the other way. Demo fixtures are capped at Moderate."""
    mean = primary.recent_mean or 0.0
    if primary.direction in ("insufficient", "mixed"):
        return "low", [primary.reasons[0] if primary.reasons else "The direction is not clear."]
    if not primary.normalised:
        return "low", ["Not adjusted for the whole edition's readership: a fall or rise of the edition would read as this article's."]
    if mean < THIN_MEAN_VIEWS:
        return "low", [f"About {mean:.0f} views a month: counts this small move easily."]
    level: Level = "moderate"
    why = ["Two full years of data at 100 or more views a month."]
    quarter_ok = primary.quarter_change is None or not _opposed(primary.direction, primary.quarter_change)
    english_ok = secondary is None or secondary.direction in ("insufficient", primary.direction)
    if mean >= SOLID_MEAN_VIEWS and quarter_ok and english_ok:
        level, why = "high", ["300 or more views a month; the last three months and the English edition agree with the year."]
    else:
        if not quarter_ok:
            why.append("The last three months point the other way.")
        if not english_ok and secondary is not None:
            why.append(f"The English edition reads {secondary.direction}, not {primary.direction}.")
    if fixture and level == "high":
        level, why = "moderate", ["Two full years of data at 100 or more views a month."]
    return level, why


# --- which articles to read ------------------------------------------------------------------------------------------

_SKIP_TITLES = ("culture of", "list of", "tourism in", "economy of", "history of")


def festival_articles(claims: Iterable[tuple[str, Iterable[tuple[str, str | None]]]], region_name: str) -> list[tuple[str, str]]:
    """(festival subject, English Wikipedia title) for each festival whose own article is cited, in claim order.

    `claims` is (subject, [(source_type, url)]) per claim. A festival's claims often cite the state's article too; that
    article says nothing about the festival, so a title equal to the state's name (or a "Culture of ..." overview) is
    never used, and a festival with no article of its own is left out rather than matched to something else."""
    titles: dict[str, list[str]] = {}
    for subject, sources in claims:
        if not subject.startswith("festival:"):
            continue
        found = titles.setdefault(subject, [])
        for source_type, url in sources:
            if source_type == "wikipedia" and url and "en.wikipedia.org/wiki/" in url:
                title = unquote(urlparse(url).path.rsplit("/", 1)[-1]).replace("_", " ")
                if title not in found:
                    found.append(title)
    out: list[tuple[str, str]] = []
    used: set[str] = set()
    for subject, found in titles.items():
        usable = [t for t in found if t.casefold() != region_name.casefold() and not t.casefold().startswith(_SKIP_TITLES)]
        word = subject.split(":", 1)[1].replace("_", " ").split()[0]
        pick = next((t for t in usable if word in t.casefold()), None) or (usable[0] if usable else None)
        if pick and pick not in used:
            used.add(pick)
            out.append((subject, pick))
    return out
