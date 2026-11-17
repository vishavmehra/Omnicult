"""Live Pulse calculated metrics, aggregation, creative-health windows, and the alert rules."""

from datetime import date, timedelta

import pytest

from app.services import pulse_sample as sample
from app.services.pulse_alerts import AlertConfig, evaluate
from app.services.pulse_metrics import (
    BY_NAME, DEFINITIONS, INPUTS, SeriesRow, Totals, calculate, daily_values, first_vs_recent, is_provisional,
    totals, value_of, window_change,
)

D0 = date(2026, 10, 1)


def totals_of(**sums: float) -> Totals:
    return Totals(sums, sums.pop("cum", 0.0), frozenset())  # type: ignore[arg-type]


def test_formulas() -> None:
    t = Totals(
        {"impressions": 100_000, "clicks": 1_000, "spend": 8_000.0, "conversions": 40, "conversion_value": 32_000.0,
         "video_views": 25_000, "video_q25": 40_000, "video_q50": 25_000, "video_q75": 18_000, "video_q100": 12_000,
         "reach": 40_000, "sessions": 800},
        cumulative_impressions=100_000, provisional=frozenset(),
    )
    assert calculate("ctr", t) == pytest.approx(0.01)
    assert calculate("cpm", t) == pytest.approx(80.0)  # 8000 / 100000 * 1000
    assert calculate("cpc", t) == pytest.approx(8.0)
    assert calculate("cpa", t) == pytest.approx(200.0)
    assert calculate("roas", t) == pytest.approx(4.0)
    assert calculate("frequency", t) == pytest.approx(2.5)
    assert calculate("view_rate", t) == pytest.approx(0.25)
    assert [calculate(f"completion_{q}", t) for q in (25, 50, 75, 100)] == pytest.approx([0.4, 0.25, 0.18, 0.12])
    assert calculate("conversion_rate", t) == pytest.approx(0.05)
    assert calculate("impressions", t) == 100_000  # base metrics pass through


def test_no_denominator_is_none_never_zero() -> None:
    empty = Totals({"impressions": 0, "clicks": 0, "spend": 120.0, "conversions": 0}, 0, frozenset())
    for name in ("ctr", "cpm", "cpc", "cpa", "roas", "view_rate", "frequency", "completion_100", "conversion_rate"):
        assert calculate(name, empty) is None, name
    assert calculate("clicks", Totals({}, 0, frozenset())) is None  # absent base metric
    assert calculate("nonsense", empty) is None


def test_every_calculated_metric_has_a_formula_and_known_inputs() -> None:
    for d in DEFINITIONS:
        assert (d.formula is not None) == (d.kind == "calculated"), d.name
        if d.kind == "calculated" and d.aggregation == "ratio":
            assert set(INPUTS[d.name]) <= {b.name for b in DEFINITIONS if b.kind == "base"}, d.name
    assert {d.group for d in DEFINITIONS} == {
        "delivery", "cost", "response", "video", "outcome", "site", "conversation", "brand", "creative_health"}
    assert BY_NAME["ctr"].formula == "clicks / impressions" and BY_NAME["cpm"].unit == "inr"


def row(day: date, metric: str, value: float, *, provisional: bool = False, platform: str = "google_ads",
        version: str = "v1", region: str = "IN-TN") -> SeriesRow:
    return SeriesRow(day, platform, "video_action", version, region, metric, value, provisional)


def test_reach_is_cumulative_not_summed_over_days() -> None:
    rows = []
    for i, reach in enumerate((100, 180, 240, 280)):
        rows += [row(D0 + timedelta(days=i), "impressions", 150), row(D0 + timedelta(days=i), "reach", reach)]
    full = totals(rows, D0, D0 + timedelta(days=3))
    assert full.sums["reach"] == 280 and full.sums["impressions"] == 600
    assert calculate("frequency", full) == pytest.approx(600 / 280)
    window = totals(rows, D0 + timedelta(days=2), D0 + timedelta(days=3))  # a later window: reach through its last day
    assert window.sums["reach"] == 280 and window.sums["impressions"] == 300
    assert calculate("frequency", window) == pytest.approx(600 / 280)  # impressions through the end, same cumulative window


def test_reach_sums_over_slices_but_each_slice_counts_once() -> None:
    rows = [
        row(D0, "reach", 100, platform="google_ads"), row(D0 + timedelta(days=1), "reach", 150, platform="google_ads"),
        row(D0, "reach", 60, platform="youtube"), row(D0 + timedelta(days=1), "reach", 90, platform="youtube"),
    ]
    assert totals(rows, D0, D0 + timedelta(days=1)).sums["reach"] == 240


def test_provisional_flag_follows_the_inputs_of_each_metric() -> None:
    rows = [
        row(D0, "impressions", 1000), row(D0, "clicks", 10), row(D0, "conversions", 2),
        row(D0 + timedelta(days=1), "impressions", 1000, provisional=True),
        row(D0 + timedelta(days=1), "clicks", 10, provisional=True),
        row(D0 + timedelta(days=1), "conversions", 0, provisional=True),
    ]
    settled = totals(rows, D0, D0)
    assert not is_provisional("ctr", settled) and not is_provisional("cpa", settled)
    recent = totals(rows, D0, D0 + timedelta(days=1))
    assert is_provisional("ctr", recent) and is_provisional("conversions", recent)
    assert value_of("ctr", rows, D0, D0)[1] is False and value_of("ctr", rows, D0, D0 + timedelta(days=1))[1] is True


def weekly_rows(days: int, ctr_of_day, *, provisional_last: int = 0, version: str = "v1", region: str = "IN-TN") -> list[SeriesRow]:
    rows: list[SeriesRow] = []
    for i in range(days):
        d, prov = D0 + timedelta(days=i), i >= days - provisional_last
        rows += [
            row(d, "impressions", 10_000, provisional=prov, version=version, region=region),
            row(d, "clicks", round(10_000 * ctr_of_day(i)), provisional=prov, version=version, region=region),
            row(d, "spend", 900.0, provisional=prov, version=version, region=region),
            row(d, "conversions", 40, provisional=prov, version=version, region=region),
        ]
    return rows


def test_window_change_compares_the_first_week_with_the_latest_settled_week() -> None:
    rows = weekly_rows(21, lambda i: 0.01 if i < 7 else 0.008, provisional_last=2)
    cmp = first_vs_recent(rows)
    assert cmp is not None and cmp.baseline_from == D0 and cmp.recent_to == D0 + timedelta(days=18)  # day 19-20 are provisional
    assert window_change("ctr_change_vs_first_week", rows) == pytest.approx(-0.2)


def test_provisional_days_cannot_look_like_a_collapse() -> None:
    steady = weekly_rows(21, lambda i: 0.01, provisional_last=2)
    collapsed = [r._replace(value=0.0) if r.provisional and r.metric == "clicks" else r for r in steady]
    assert window_change("ctr_change_vs_first_week", collapsed) == pytest.approx(0.0)
    assert evaluate(collapsed).alerts == []


def test_not_enough_settled_data_is_skipped_not_silently_ok() -> None:
    short = weekly_rows(10, lambda i: 0.01)
    assert first_vs_recent(short) is None and window_change("ctr_change_vs_first_week", short) is None
    result = evaluate(short)
    assert result.alerts == [] and result.evaluated == 0 and [s.rule for s in result.skipped] == ["all"]
    thin = [r._replace(value=r.value / 100) if r.metric in ("impressions", "clicks") else r for r in weekly_rows(21, lambda i: 0.01)]
    assert evaluate(thin).evaluated == 0 and "impressions" in evaluate(thin).skipped[0].reason


def test_daily_values_use_each_days_own_totals() -> None:
    rows = weekly_rows(3, lambda i: [0.01, 0.02, 0.03][i], provisional_last=1)
    series = daily_values("ctr", rows)
    assert [(d, round(v, 3), p) for d, v, p in series] == [
        (D0, 0.01, False), (D0 + timedelta(days=1), 0.02, False), (D0 + timedelta(days=2), 0.03, True)]


SAMPLE_ALERTS = {
    ("ctr_drop", "IN-KL", sample.ORIGINAL, "ctr"),
    ("frequency_fatigue", "IN-KL", sample.ORIGINAL, "frequency"),
    ("cost_spike", "IN-TN", sample.ORIGINAL, "cpa"),
    ("cost_spike", "IN-WB", sample.ORIGINAL, "cpa"),
    ("cost_spike", "IN-WB", sample.ADAPTED_A, "cpm"),
}


def keys(result) -> set[tuple[str, str, str, str]]:  # type: ignore[no-untyped-def]
    return {(a.alert_type, a.region_code, a.version_label, a.metric) for a in result.alerts}


def test_alert_rules_find_the_designed_story_in_the_sample() -> None:
    result = evaluate(sample.generate_sample_rows())
    assert keys(result) == SAMPLE_ALERTS and result.evaluated == 10
    by_type = {(a.alert_type, a.region_code, a.version_label): a for a in result.alerts}
    drop = by_type[("ctr_drop", "IN-KL", sample.ORIGINAL)]
    assert drop.observed_value <= -0.20 and drop.threshold == -0.20 and "Adapted B" in drop.suggested_action
    assert drop.window_to == sample.END - timedelta(days=2)  # the last settled day, never a provisional one
    assert by_type[("frequency_fatigue", "IN-KL", sample.ORIGINAL)].observed_value >= 2.5
    assert by_type[("cost_spike", "IN-WB", sample.ADAPTED_A)].observed_value >= 0.30


def test_alert_thresholds_are_configurable_and_deterministic() -> None:
    rows = sample.generate_sample_rows()
    assert evaluate(rows, AlertConfig(ctr_drop_pct=0.10)).alerts != evaluate(rows).alerts
    assert any(a.alert_type == "ctr_drop" and a.region_code == "IN-TN" for a in evaluate(rows, AlertConfig(ctr_drop_pct=0.10)).alerts)
    quiet = evaluate(rows, AlertConfig(ctr_drop_pct=0.9, frequency_threshold=50, cost_spike_pct=5.0))
    assert quiet.alerts == [] and quiet.evaluated == 10
    assert evaluate(rows) == evaluate(rows)


def test_a_rule_without_its_inputs_is_skipped_with_a_reason() -> None:
    no_reach = [r for r in sample.generate_sample_rows() if r.metric != "reach"]
    result = evaluate(no_reach)
    assert not any(a.alert_type == "frequency_fatigue" for a in result.alerts)
    assert {s.rule for s in result.skipped} >= {"frequency_fatigue"}
    assert any("Reach is not reported" in s.reason for s in result.skipped)


def test_one_pass_daily_totals_equal_the_per_day_aggregation() -> None:
    from app.services.pulse_metrics import daily_totals

    rows = [r for r in sample.generate_sample_rows() if r.region_code == "IN-KL"]
    daily = daily_totals(rows)
    assert len(daily) == sample.DAYS
    for day in (sample.START, sample.START + timedelta(days=9), sample.END):
        expected = totals(rows, day, day)
        assert dict(daily[day].sums) == pytest.approx(dict(expected.sums))
        assert daily[day].cumulative_impressions == pytest.approx(expected.cumulative_impressions)
        assert daily[day].provisional == expected.provisional
