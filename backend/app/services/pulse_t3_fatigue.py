"""Fatigue Watch: is a creative wearing out in a region? Pure code over Pulse series rows (no database, no model).

One noisy metric never makes a verdict (handoff 47). A version in a region is read through four signals in two families:

  response  ctr_decay         CTR of the last 7 settled days against the version's own first week.
            view_rate_decay   view rate, the same way.
  exposure  frequency         frequency through the last settled day.
            repeated_exposure new reach per impression in the last week is at most a quarter of the first week's.

A decay counts only when it is larger than the day-to-day noise in the same series: the difference between the two weekly
means must be at least twice its standard error. Fatigue needs a response signal AND an exposure signal. One family alone
is "watch" with the reason it falls short, and nothing triggered is "healthy". The static-versus-rising reading of the
cost alerts is kept: a version whose CTR is already far below its region's average in the first week and does not decay is
"static_low", weak from the start rather than worn out.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from math import sqrt
from statistics import mean, variance

from app.schemas import pulse_t3 as v
from app.services.pulse_metrics import (
    MIN_IMPRESSIONS, WINDOW_DAYS, SeriesRow, WindowComparison, calculate, daily_totals, first_vs_recent, is_provisional, totals,
)

NOISE_MULTIPLE = 2.0  # a decay must be this many standard errors of the weekly means
SATURATION_RATIO = 0.25  # new reach per impression in the last week at most this share of the first week's
STATIC_GAP = 0.25  # first-week CTR this far below the region's average, with no decay, is static underperformance


@dataclass(frozen=True)
class FatigueConfig:
    ctr_decline_pct: float = 0.10
    view_rate_decline_pct: float = 0.10
    frequency_threshold: float = 2.5


def _pct(x: float) -> str:
    return f"{abs(x) * 100:.0f}%"


def _ratio_pct(x: float) -> str:
    pct = x * 100
    return f"{pct:.2f}%" if abs(pct) < 10 else f"{pct:.1f}%"


def _daily(metric: str, rows: list[SeriesRow], first: date, last: date) -> list[float]:
    values = [calculate(metric, t) for day, t in sorted(daily_totals(rows).items()) if first <= day <= last]
    return [x for x in values if x is not None]


def _noise_ok(metric: str, rows: list[SeriesRow], cmp: WindowComparison) -> bool:
    """True when the weekly means differ by at least NOISE_MULTIPLE standard errors of their difference (needs 2+ days a week)."""
    first = _daily(metric, rows, cmp.baseline_from, cmp.baseline_to)
    last = _daily(metric, rows, cmp.recent_from, cmp.recent_to)
    if len(first) < 2 or len(last) < 2:
        return False
    se = sqrt(variance(first) / len(first) + variance(last) / len(last))
    return mean(first) - mean(last) >= NOISE_MULTIPLE * se if se > 0 else mean(first) > mean(last)


def _decay(name: v.FatigueSignalName, label: str, metric: str, threshold: float, rows: list[SeriesRow], cmp: WindowComparison) -> v.FatigueSignal:
    base, recent = calculate(metric, cmp.baseline), calculate(metric, cmp.recent)
    shown = "CTR" if metric == "ctr" else "View rate"
    if not base or recent is None:
        return v.FatigueSignal(name=name, label=label, family="response", available=False, triggered=False, observed=None,
                               threshold=-threshold, unit="ratio", detail=f"{shown} could not be calculated in both weeks.")
    change = recent / base - 1
    falling = change <= -threshold
    noisy = falling and not _noise_ok(metric, rows, cmp)
    detail = f"{shown} was {_ratio_pct(base)} in the first week and {_ratio_pct(recent)} in the last settled week, {_pct(change)} {'below' if change < 0 else 'above'} the first week."
    if noisy:
        detail += " That is within the day-to-day noise, so it does not count."
    return v.FatigueSignal(name=name, label=label, family="response", available=True, triggered=falling and not noisy,
                           observed=change, threshold=-threshold, unit="ratio", detail=detail)


def _reach_at(rows: list[SeriesRow], day: date) -> float | None:
    t = totals(rows, day, day)
    return t.sums.get("reach")


def _exposure(rows: list[SeriesRow], cmp: WindowComparison, cfg: FatigueConfig) -> list[v.FatigueSignal]:
    frequency = calculate("frequency", totals(rows, cmp.recent_to, cmp.recent_to))
    if frequency is None:
        freq = v.FatigueSignal(name="frequency", label="Frequency", family="exposure", available=False, triggered=False, observed=None,
                               threshold=cfg.frequency_threshold, unit="multiple", detail="Reach is not reported, so frequency cannot be calculated.")
    else:
        freq = v.FatigueSignal(
            name="frequency", label="Frequency", family="exposure", available=True, triggered=frequency >= cfg.frequency_threshold,
            observed=frequency, threshold=cfg.frequency_threshold, unit="multiple",
            detail=f"Each person reached has seen the ad {frequency:.2f} times on average through the last settled day (threshold {cfg.frequency_threshold:.2f}).")
    reach_first, reach_before, reach_last = (
        _reach_at(rows, cmp.baseline_to), _reach_at(rows, cmp.recent_from - timedelta(days=1)), _reach_at(rows, cmp.recent_to))
    imp_first, imp_last = cmp.baseline.sums.get("impressions", 0.0), cmp.recent.sums.get("impressions", 0.0)
    if None in (reach_first, reach_before, reach_last) or not imp_first or not imp_last or not reach_first:
        repeat = v.FatigueSignal(name="repeated_exposure", label="Repeated exposure", family="exposure", available=False, triggered=False,
                                 observed=None, threshold=SATURATION_RATIO, unit="ratio",
                                 detail="Reach is not reported for both weeks, so new reach cannot be compared.")
    else:
        rate_first = reach_first / imp_first  # type: ignore[operator]
        rate_last = (reach_last - reach_before) / imp_last  # type: ignore[operator]
        share = rate_last / rate_first
        repeat = v.FatigueSignal(
            name="repeated_exposure", label="Repeated exposure", family="exposure", available=True, triggered=share <= SATURATION_RATIO,
            observed=share, threshold=SATURATION_RATIO, unit="ratio",
            detail=f"New people reached per impression in the last week were {share * 100:.0f}% of the first week's (flagged at {SATURATION_RATIO * 100:.0f}% or less): the ad is reaching people who have already seen it.")
    return [freq, repeat]


def _points(metric: str, rows: list[SeriesRow]) -> list[v.FatiguePoint]:
    return [
        v.FatiguePoint(date=day, value=calculate(metric, t), provisional=is_provisional(metric, t))
        for day, t in sorted(daily_totals(rows).items())
    ]


def _region_ctr(rows: Iterable[SeriesRow]) -> float | None:
    rows = [r for r in rows if not r.provisional]
    if not rows:
        return None
    return calculate("ctr", totals(rows, min(r.day for r in rows), max(r.day for r in rows)))


def _confidence(status: str, triggered: int, available: int) -> v.Confidence:
    """Low, Moderate or High from how many signals could be read and agree. The sample dataset is generated, so High is not offered."""
    if status == "fatigued":
        return "Moderate" if triggered >= 3 else "Low"
    if status == "healthy":
        return "Moderate" if available == 4 else "Low"
    return "Low"


def _reason(status: str, pattern: str, signals: dict[str, v.FatigueSignal]) -> str:
    trig = [s for s in signals.values() if s.triggered]
    if status == "fatigued":
        resp = [s for s in trig if s.family == "response"]
        expo = [s for s in trig if s.family == "exposure"]
        return (
            "Response is falling while exposure is high: " + " ".join(s.detail for s in resp + expo)
            + " Both move together, which points at wear-out rather than one noisy metric."
        )
    if status == "watch":
        resp = [s for s in trig if s.family == "response"]
        if resp:
            return (
                " ".join(s.detail for s in resp)
                + " Exposure is not high, so repetition is not the likely cause; creative fit, audience or timing could be."
            )
        return " ".join(s.detail for s in trig) + " Response is holding, so there is no sign of wear-out yet."
    if status == "healthy":
        return "No signal crossed its threshold: response is holding and exposure is not high." + (
            " CTR sat well below the region's average from the first week, so this is weak from the start rather than worn out."
            if pattern == "static_low" else "")
    return ""


def assess(
    rows: Iterable[SeriesRow], cfg: FatigueConfig, region_names: dict[str, str],
) -> list[tuple[str, str, v.FatigueRow, dict]]:
    """One FatigueRow per (region, version), in order, each with the context the service needs to suggest a refresh."""
    by_slice: dict[tuple[str, str], list[SeriesRow]] = defaultdict(list)
    by_region: dict[str, list[SeriesRow]] = defaultdict(list)
    for r in rows:
        by_slice[(r.region_code, r.version_label)].append(r)
        by_region[r.region_code].append(r)
    out = []
    for (region, version), slice_rows in sorted(by_slice.items()):
        cmp = first_vs_recent(slice_rows)
        name = region_names.get(region, region)
        ctr_points, freq_points = _points("ctr", slice_rows), _points("frequency", slice_rows)
        base = dict(region_code=region, region_name=name, version_label=version, ctr=ctr_points, frequency=freq_points, refresh=[])
        if cmp is None or min(cmp.baseline.sums.get("impressions", 0), cmp.recent.sums.get("impressions", 0)) < MIN_IMPRESSIONS:
            reason = (f"Fewer than two non-overlapping settled weeks of data ({WINDOW_DAYS} days each)." if cmp is None
                      else f"Fewer than {MIN_IMPRESSIONS} impressions in a comparison week.")
            out.append((region, version, v.FatigueRow(
                status="not_enough_data", pattern="unknown", signals_triggered=0, confidence="Low", reason=reason,
                window_from=None, window_to=None, signals=[], **base), {"recent_ctr": None}))
            continue
        signals = [
            _decay("ctr_decay", "CTR decay", "ctr", cfg.ctr_decline_pct, slice_rows, cmp),
            _decay("view_rate_decay", "View-rate decay", "view_rate", cfg.view_rate_decline_pct, slice_rows, cmp),
            *_exposure(slice_rows, cmp, cfg),
        ]
        by_name = {s.name: s for s in signals}
        response = any(s.triggered for s in signals if s.family == "response")
        exposure = any(s.triggered for s in signals if s.family == "exposure")
        triggered = sum(s.triggered for s in signals)
        status = "fatigued" if response and exposure else "watch" if response or exposure else "healthy"
        # static versus rising: weak from the first week and not decaying, compared with the region's other versions
        pattern = "steady"
        if by_name["ctr_decay"].triggered:
            pattern = "wearing_out"
        else:
            others = [r for r in by_region[region] if r.version_label != version and r.day <= cmp.baseline_to]
            region_ctr, first_ctr = _region_ctr(others), calculate("ctr", cmp.baseline)
            if region_ctr and first_ctr is not None and first_ctr / region_ctr - 1 <= -STATIC_GAP:
                pattern = "static_low"
        row = v.FatigueRow(
            status=status, pattern=pattern, signals_triggered=triggered,
            confidence=_confidence(status, triggered, sum(s.available for s in signals)),
            reason=_reason(status, pattern, by_name), window_from=cmp.baseline_from, window_to=cmp.recent_to,
            signals=signals, **base)
        out.append((region, version, row, {"recent_ctr": calculate("ctr", cmp.recent)}))
    return out
