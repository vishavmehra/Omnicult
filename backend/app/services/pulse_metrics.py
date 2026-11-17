"""Live Pulse metric definitions and deterministic calculations (no database, no model).

Only base metrics are stored (`metric_series`); every calculated metric is computed here from sums of base metrics.
A ratio whose denominator is zero (or absent) is `None`, never 0: "no delivery" is not "0% CTR".

Aggregation over a date range [from, to]:
  * additive base metrics (impressions, clicks, spend, ...) are summed over the range;
  * `reach` is cumulative: a slice's stored value is the unique people reached from the first day of data through that
    day, so the range value is the slice's last value inside the range, summed over slices. Reach is not deduplicated
    across slices (platforms, versions), so a roll-up can count one person more than once; `REACH_CAVEAT` says so;
  * `frequency` = impressions from the first day of data through `to` / reach at `to` (the same cumulative window).
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal, NamedTuple

MetricGroup = Literal[
    "delivery", "cost", "response", "video", "outcome", "site", "conversation", "brand", "creative_health"
]
Unit = Literal["count", "inr", "ratio", "multiple"]

REACH_CAVEAT = (
    "Reach is cumulative from the first day of data and is summed across the platforms and versions shown, so one "
    "person reached through two of them is counted twice."
)
WINDOW_DAYS = 7
MIN_IMPRESSIONS = 5000  # a window with fewer impressions is too thin to compare


class SeriesRow(NamedTuple):
    """One stored base-metric value, independent of where it was loaded from (database or the sample generator)."""

    day: date
    platform: str
    channel: str
    version_label: str
    region_code: str
    metric: str
    value: float
    provisional: bool


@dataclass(frozen=True)
class MetricDef:
    name: str
    label: str
    unit: Unit
    group: MetricGroup
    kind: Literal["base", "calculated"]
    description: str
    formula: str | None = None  # calculated metrics only, in terms of base metric names
    platforms: tuple[str, ...] = ()  # the platforms that report it (the product plan's "where it comes from")
    in_sample: bool = False
    in_google_ads: bool = False  # filled by the connector (app.integrations.google_ads)
    aggregation: Literal["sum", "cumulative", "ratio", "window_change"] = "sum"


def _base(name: str, label: str, unit: Unit, group: MetricGroup, description: str, platforms: tuple[str, ...], *,
          sample: bool = False, ads: bool = False, aggregation: Literal["sum", "cumulative"] = "sum") -> MetricDef:
    return MetricDef(name, label, unit, group, "base", description, None, platforms, sample, ads, aggregation)


def _calc(name: str, label: str, unit: Unit, group: MetricGroup, formula: str, description: str,
          platforms: tuple[str, ...], *, sample: bool = False, ads: bool = False,
          aggregation: Literal["ratio", "window_change"] = "ratio") -> MetricDef:
    return MetricDef(name, label, unit, group, "calculated", description, formula, platforms, sample, ads, aggregation)


ADS = ("google_ads", "meta")
VIDEO = ("google_ads", "youtube", "meta")
DEFINITIONS: tuple[MetricDef, ...] = (
    _base("impressions", "Impressions", "count", "delivery", "Times the ad was shown.", ADS + ("youtube",), sample=True, ads=True),
    _base("reach", "Reach", "count", "delivery", "Unique people reached, cumulative from the first day of data.",
          ("meta",), sample=True, aggregation="cumulative"),
    _calc("frequency", "Frequency", "multiple", "delivery", "impressions (cumulative) / reach",
          "Average times each reached person saw the ad.", ("meta",), sample=True),
    _base("spend", "Spend", "inr", "cost", "Amount spent, in Indian rupees.", ADS + ("youtube",), sample=True, ads=True),
    _calc("cpm", "CPM", "inr", "cost", "spend / impressions * 1000", "Cost per thousand impressions.",
          ADS + ("youtube",), sample=True, ads=True),
    _calc("cpc", "CPC", "inr", "cost", "spend / clicks", "Cost per click.", ADS + ("youtube",), sample=True, ads=True),
    _base("clicks", "Clicks", "count", "response", "Clicks on the ad.", ADS + ("youtube",), sample=True, ads=True),
    _calc("ctr", "CTR", "ratio", "response", "clicks / impressions", "Share of impressions that were clicked.",
          ADS + ("youtube",), sample=True, ads=True),
    _base("video_views", "Video views", "count", "video",
          "Views counted by the platform (Google Ads: TrueView views).", VIDEO, sample=True, ads=True),
    _calc("view_rate", "View rate", "ratio", "video", "video_views / impressions", "Share of impressions that became a view.",
          VIDEO, sample=True, ads=True),
    _base("video_q25", "Played to 25%", "count", "video", "Impressions where the viewer watched at least 25% of the video.",
          VIDEO, sample=True, ads=True),
    _base("video_q50", "Played to 50%", "count", "video", "Impressions where the viewer watched at least 50% of the video.",
          VIDEO, sample=True, ads=True),
    _base("video_q75", "Played to 75%", "count", "video", "Impressions where the viewer watched at least 75% of the video.",
          VIDEO, sample=True, ads=True),
    _base("video_q100", "Played to 100%", "count", "video", "Impressions where the viewer watched the whole video.",
          VIDEO, sample=True, ads=True),
    _calc("completion_25", "25% completion", "ratio", "video", "video_q25 / impressions",
          "Share of impressions played to 25%.", VIDEO, sample=True, ads=True),
    _calc("completion_50", "50% completion", "ratio", "video", "video_q50 / impressions",
          "Share of impressions played to 50%.", VIDEO, sample=True, ads=True),
    _calc("completion_75", "75% completion", "ratio", "video", "video_q75 / impressions",
          "Share of impressions played to 75%.", VIDEO, sample=True, ads=True),
    _calc("completion_100", "100% completion", "ratio", "video", "video_q100 / impressions",
          "Share of impressions played to the end.", VIDEO, sample=True, ads=True),
    _base("thruplays", "ThruPlays", "count", "video", "Plays of at least 15 seconds or to the end (Meta only).", ("meta",)),
    _base("conversions", "Conversions", "count", "outcome",
          "Conversions credited to the ad. Recent days under-report: conversions arrive days later.",
          ADS, sample=True, ads=True),
    _base("conversion_value", "Conversion value", "inr", "outcome", "Value of the conversions, in Indian rupees.",
          ADS, sample=True, ads=True),
    _calc("cpa", "CPA", "inr", "outcome", "spend / conversions", "Cost per conversion.", ADS, sample=True, ads=True),
    _calc("roas", "ROAS", "multiple", "outcome", "conversion_value / spend", "Conversion value per rupee spent.",
          ADS, sample=True, ads=True),
    _base("sessions", "Sessions", "count", "site", "Site sessions after the click (GA4).", ("ga4",)),
    _base("engaged_sessions", "Engaged sessions", "count", "site", "Sessions GA4 counts as engaged.", ("ga4",)),
    _calc("conversion_rate", "Conversion rate", "ratio", "site", "conversions / sessions",
          "Share of sessions that converted (GA4).", ("ga4",)),
    _base("comment_volume", "Comment volume", "count", "conversation", "Public comments on the campaign video (YouTube).",
          ("youtube",)),
    _base("share_of_search", "Share of search", "ratio", "brand", "The brand's share of searches in the state (Google Trends).",
          ("google_trends",)),
    _calc("ctr_change_vs_first_week", "CTR vs first week", "ratio", "creative_health",
          "(CTR of the last 7 settled days / CTR of the first 7 days) - 1",
          "Change in CTR against the version's own first week; negative means the ad is wearing out.",
          ADS + ("youtube",), sample=True, ads=True, aggregation="window_change"),
    _calc("view_rate_change_vs_first_week", "View rate vs first week", "ratio", "creative_health",
          "(view rate of the last 7 settled days / view rate of the first 7 days) - 1",
          "Change in view rate against the version's own first week.",
          VIDEO, sample=True, ads=True, aggregation="window_change"),
)
BY_NAME: dict[str, MetricDef] = {d.name: d for d in DEFINITIONS}
ADDITIVE = tuple(d.name for d in DEFINITIONS if d.kind == "base" and d.aggregation == "sum")


class Totals(NamedTuple):
    """Sums of base metrics over a range, for one set of rows. `provisional` names the base metrics with a provisional day."""

    sums: Mapping[str, float]
    cumulative_impressions: float
    provisional: frozenset[str]


def totals(rows: Iterable[SeriesRow], date_from: date, date_to: date) -> Totals:
    """Aggregate the rows' base metrics over [date_from, date_to] (see the module docstring for reach and frequency)."""
    sums: dict[str, float] = defaultdict(float)
    present: set[str] = set()
    provisional: set[str] = set()
    last_reach: dict[tuple[str, str, str, str], tuple[date, float]] = {}
    cumulative: dict[tuple[str, str, str, str], float] = defaultdict(float)
    for r in rows:
        slice_key = (r.platform, r.channel, r.version_label, r.region_code)
        if r.metric == "impressions" and r.day <= date_to:
            cumulative[slice_key] += r.value
        if not date_from <= r.day <= date_to:
            continue
        present.add(r.metric)
        if r.provisional:
            provisional.add(r.metric)
        if r.metric == "reach":
            if slice_key not in last_reach or r.day > last_reach[slice_key][0]:
                last_reach[slice_key] = (r.day, r.value)
        else:
            sums[r.metric] += r.value
    if "reach" in present:
        sums["reach"] = sum(value for _, value in last_reach.values())
    # cumulative impressions only over slices that report reach in the range, so that frequency compares like with like
    cum = sum(cumulative[k] for k in last_reach)
    return Totals({k: sums[k] for k in present}, cum, frozenset(provisional))


def _ratio(num: float | None, den: float | None, scale: float = 1.0) -> float | None:
    if num is None or not den:
        return None
    return num / den * scale


def calculate(name: str, t: Totals) -> float | None:
    """The value of one metric (base or calculated) from totals; None when it cannot be computed from what is present."""
    s = t.sums
    if name in BY_NAME and BY_NAME[name].kind == "base":
        return s.get(name)
    match name:
        case "ctr":
            return _ratio(s.get("clicks"), s.get("impressions"))
        case "cpm":
            return _ratio(s.get("spend"), s.get("impressions"), 1000)
        case "cpc":
            return _ratio(s.get("spend"), s.get("clicks"))
        case "cpa":
            return _ratio(s.get("spend"), s.get("conversions"))
        case "roas":
            return _ratio(s.get("conversion_value"), s.get("spend"))
        case "frequency":
            return _ratio(t.cumulative_impressions if "reach" in s else None, s.get("reach"))
        case "view_rate":
            return _ratio(s.get("video_views"), s.get("impressions"))
        case "conversion_rate":
            return _ratio(s.get("conversions"), s.get("sessions"))
        case _ if name.startswith("completion_"):
            return _ratio(s.get("video_q" + name.removeprefix("completion_")), s.get("impressions"))
    return None


INPUTS = {
    "ctr": ("clicks", "impressions"), "cpm": ("spend", "impressions"), "cpc": ("spend", "clicks"),
    "cpa": ("spend", "conversions"), "roas": ("conversion_value", "spend"), "frequency": ("impressions", "reach"),
    "view_rate": ("video_views", "impressions"), "conversion_rate": ("conversions", "sessions"),
    "completion_25": ("video_q25", "impressions"), "completion_50": ("video_q50", "impressions"),
    "completion_75": ("video_q75", "impressions"), "completion_100": ("video_q100", "impressions"),
}


def is_provisional(name: str, t: Totals) -> bool:
    """True when a day feeding this metric is still provisional."""
    return any(i in t.provisional for i in INPUTS.get(name, (name,)))


# --- creative health: the version's own first week against its latest settled week -------------------------------


class WindowComparison(NamedTuple):
    baseline: Totals
    recent: Totals
    baseline_from: date
    baseline_to: date
    recent_from: date
    recent_to: date


def first_vs_recent(rows: Iterable[SeriesRow], *, window_days: int = WINDOW_DAYS) -> WindowComparison | None:
    """The first `window_days` days of the rows against their last `window_days` settled (non-provisional) days.

    None when there are not enough settled days for two non-overlapping windows. Provisional days are excluded from the
    recent window, so a half-reported last day cannot look like a collapse.
    """
    rows = list(rows)
    days = sorted({r.day for r in rows})
    settled = sorted({r.day for r in rows if not r.provisional})
    if len(days) < window_days or len(settled) < window_days:
        return None
    baseline_from, baseline_to = days[0], days[0] + timedelta(days=window_days - 1)
    recent_to = settled[-1]
    recent_from = recent_to - timedelta(days=window_days - 1)
    if recent_from <= baseline_to:
        return None
    return WindowComparison(
        totals(rows, baseline_from, baseline_to), totals(rows, recent_from, recent_to),
        baseline_from, baseline_to, recent_from, recent_to,
    )


def window_change(name: str, rows: Iterable[SeriesRow]) -> float | None:
    """`ctr_change_vs_first_week` / `view_rate_change_vs_first_week` for the rows, None when not comparable."""
    metric = name.removesuffix("_change_vs_first_week")
    cmp = first_vs_recent(rows)
    if cmp is None or min(cmp.baseline.sums.get("impressions", 0), cmp.recent.sums.get("impressions", 0)) < MIN_IMPRESSIONS:
        return None
    base, recent = calculate(metric, cmp.baseline), calculate(metric, cmp.recent)
    return None if not base or recent is None else recent / base - 1


def values_of(names: Iterable[str], rows: list[SeriesRow], date_from: date, date_to: date) -> dict[str, tuple[float | None, bool]]:
    """(value, provisional) of each catalogue metric over the rows and range; the rows are aggregated once."""
    t = totals(rows, date_from, date_to)
    in_range = [r for r in rows if date_from <= r.day <= date_to]
    out: dict[str, tuple[float | None, bool]] = {}
    for name in names:
        if BY_NAME[name].aggregation == "window_change":
            out[name] = (window_change(name, in_range), False)
        else:
            out[name] = (calculate(name, t), is_provisional(name, t))
    return out


def value_of(name: str, rows: list[SeriesRow], date_from: date, date_to: date) -> tuple[float | None, bool]:
    return values_of([name], rows, date_from, date_to)[name]


def daily_totals(rows: Iterable[SeriesRow]) -> dict[date, Totals]:
    """`totals(rows, d, d)` for every day that has rows, in one pass. Reach and frequency use the cumulative windows
    described above (cumulative impressions run from the first day of data through that day)."""
    by_day: dict[date, list[SeriesRow]] = defaultdict(list)
    for r in rows:
        by_day[r.day].append(r)
    cumulative: dict[tuple[str, str, str, str], float] = defaultdict(float)
    out: dict[date, Totals] = {}
    for d in sorted(by_day):
        sums: dict[str, float] = defaultdict(float)
        provisional: set[str] = set()
        reach_slices: set[tuple[str, str, str, str]] = set()
        for r in by_day[d]:
            slice_key = (r.platform, r.channel, r.version_label, r.region_code)
            sums[r.metric] += r.value
            if r.metric == "impressions":
                cumulative[slice_key] += r.value
            elif r.metric == "reach":
                reach_slices.add(slice_key)
            if r.provisional:
                provisional.add(r.metric)
        out[d] = Totals(dict(sums), sum(cumulative[k] for k in reach_slices), frozenset(provisional))
    return out


def daily_values(name: str, rows: list[SeriesRow]) -> list[tuple[date, float | None, bool]]:
    """One (day, value, provisional) per day that has rows."""
    return [(d, calculate(name, t), is_provisional(name, t)) for d, t in daily_totals(rows).items()]
