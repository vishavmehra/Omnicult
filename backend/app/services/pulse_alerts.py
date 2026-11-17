"""Deterministic alert rules for Live Pulse (a preview of feature 45; thresholds are request parameters, not saved rules).

Rules read stored series only; no model is involved. They are conservative on purpose (handoff feature 45: "false or
incomplete data does not silently trigger misleading alerts"):
  * provisional days are never used, so a half-reported last day cannot look like a collapse;
  * a version in a region needs two non-overlapping settled weeks and enough impressions, else it is reported as
    skipped with the reason, never as "no alert";
  * a rule whose inputs are absent (for example frequency without reach) is skipped, not guessed.

Rules (all per version and region, platforms rolled up):
  ctr_drop            CTR of the last 7 settled days is at least `ctr_drop_pct` below the version's own first week.
  frequency_fatigue   frequency through the last settled day >= `frequency_threshold` while CTR is down by at least
                      `frequency_min_ctr_decline_pct` against the first week.
  cost_spike          CPM, or CPA, of the last 7 settled days exceeds the region's campaign average (all versions, all
                      settled days) by `cost_spike_pct` or more. CPA needs `min_conversions` in the window.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.services.pulse_metrics import MIN_IMPRESSIONS, SeriesRow, calculate, first_vs_recent, totals

AlertType = Literal["ctr_drop", "frequency_fatigue", "cost_spike"]


@dataclass(frozen=True)
class AlertConfig:
    ctr_drop_pct: float = 0.20
    frequency_threshold: float = 2.5
    frequency_min_ctr_decline_pct: float = 0.10
    cost_spike_pct: float = 0.30
    min_conversions: int = 30


@dataclass(frozen=True)
class Alert:
    alert_type: AlertType
    region_code: str
    version_label: str
    metric: str
    threshold: float
    observed_value: float
    comparison_value: float
    comparison: str
    window_from: date
    window_to: date
    suggested_action: str


@dataclass(frozen=True)
class Skipped:
    region_code: str
    version_label: str
    rule: str
    reason: str


@dataclass(frozen=True)
class Evaluation:
    alerts: list[Alert]
    skipped: list[Skipped]
    evaluated: int  # version-region pairs that could be compared


def _better_version(region_rows: dict[str, list[SeriesRow]], own: str, own_ctr: float | None) -> str | None:
    best: tuple[float, str] | None = None
    for version, rows in sorted(region_rows.items()):
        cmp = first_vs_recent(rows)
        ctr = None if cmp is None else calculate("ctr", cmp.recent)
        if version != own and ctr is not None and own_ctr is not None and ctr > own_ctr and (best is None or ctr > best[0]):
            best = (ctr, version)
    return None if best is None else f"{best[1]} is running at a CTR of {best[0] * 100:.2f}% in the same weeks."


def evaluate(rows: Iterable[SeriesRow], config: AlertConfig | None = None) -> Evaluation:
    cfg = config or AlertConfig()
    by_slice: dict[tuple[str, str], list[SeriesRow]] = defaultdict(list)
    by_region: dict[str, dict[str, list[SeriesRow]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_slice[(r.region_code, r.version_label)].append(r)
        by_region[r.region_code][r.version_label].append(r)
    alerts: list[Alert] = []
    skipped: list[Skipped] = []
    evaluated = 0
    for (region, version), slice_rows in sorted(by_slice.items()):
        cmp = first_vs_recent(slice_rows)
        if cmp is None:
            skipped.append(Skipped(region, version, "all", "Fewer than two non-overlapping settled weeks of data."))
            continue
        if min(cmp.baseline.sums.get("impressions", 0), cmp.recent.sums.get("impressions", 0)) < MIN_IMPRESSIONS:
            skipped.append(Skipped(region, version, "all", f"Fewer than {MIN_IMPRESSIONS} impressions in a comparison week."))
            continue
        evaluated += 1
        base_ctr, recent_ctr = calculate("ctr", cmp.baseline), calculate("ctr", cmp.recent)
        ctr_change = None if not base_ctr or recent_ctr is None else recent_ctr / base_ctr - 1
        window = dict(window_from=cmp.recent_from, window_to=cmp.recent_to)

        if ctr_change is None:
            skipped.append(Skipped(region, version, "ctr_drop", "CTR could not be calculated (no clicks or impressions)."))
        elif ctr_change <= -cfg.ctr_drop_pct:
            hint = _better_version(by_region[region], version, recent_ctr)
            alerts.append(Alert(
                "ctr_drop", region, version, "ctr", -cfg.ctr_drop_pct, ctr_change, base_ctr or 0.0,
                f"CTR change against the version's first week ({cmp.baseline_from} to {cmp.baseline_to}); first-week CTR in comparison_value.",
                suggested_action="Refresh the creative or rotate another version into this region. " + (hint or ""),
                **window,
            ))

        reach_totals = totals(slice_rows, cmp.recent_to, cmp.recent_to)
        frequency = calculate("frequency", reach_totals)
        if frequency is None:
            skipped.append(Skipped(region, version, "frequency_fatigue", "Reach is not reported, so frequency cannot be calculated."))
        elif frequency >= cfg.frequency_threshold and ctr_change is not None and ctr_change <= -cfg.frequency_min_ctr_decline_pct:
            alerts.append(Alert(
                "frequency_fatigue", region, version, "frequency", cfg.frequency_threshold, frequency,
                ctr_change, "CTR change against the version's first week.",
                suggested_action="Cap frequency or rotate a fresh version into this region before spending more.", **window,
            ))

        settled = [row for rows_ in by_region[region].values() for row in rows_ if not row.provisional]
        region_totals = totals(settled, min(r.day for r in settled), max(r.day for r in settled))
        for metric in ("cpm", "cpa"):
            observed, average = calculate(metric, cmp.recent), calculate(metric, region_totals)
            if metric == "cpa" and cmp.recent.sums.get("conversions", 0) < cfg.min_conversions:
                skipped.append(Skipped(region, version, "cost_spike:cpa", f"Fewer than {cfg.min_conversions} conversions in the week."))
                continue
            if observed is None or not average:
                skipped.append(Skipped(region, version, f"cost_spike:{metric}", f"{metric.upper()} could not be calculated."))
            elif observed / average - 1 >= cfg.cost_spike_pct:
                alerts.append(Alert(
                    "cost_spike", region, version, metric, cfg.cost_spike_pct, observed / average - 1, average,
                    f"Average {metric.upper()} of all versions in {region} over its settled days (rupees).",
                    suggested_action=(
                        "Review bids and the auction for this region before spending more."
                        if metric == "cpm" else "Review targeting and the landing flow for this version in this region."
                    ),
                    **window,
                ))
    return Evaluation(alerts, skipped, evaluated)
