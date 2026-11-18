"""Fatigue Watch: a verdict needs a response signal and an exposure signal, and one noisy metric is never enough."""

from datetime import date, timedelta

from app.schemas.pulse_t3 import FatigueRow, FatigueSignal
from app.services import pulse_sample as sample
from app.services import pulse_t3_fatigue as f
from app.services.pulse_metrics import SeriesRow

CFG = f.FatigueConfig()
NAMES = {"IN-KL": "Kerala"}
SAMPLE = sample.generate_sample_rows()
DAYS = 21
START = date(2026, 10, 27)


def by_slice(rows: list[SeriesRow] = SAMPLE) -> dict[tuple[str, str], tuple[FatigueRow, dict]]:
    return {(region, version): (row, ctx) for region, version, row, ctx in f.assess(rows, CFG, NAMES)}


def signal(row: FatigueRow, name: str) -> FatigueSignal:
    return next(s for s in row.signals if s.name == name)


def synthetic(impressions: list[int], clicks: list[int], reach: list[int] | None = None, provisional_tail: int = 0) -> list[SeriesRow]:
    """One slice (one platform, one version, one region), a row per day and metric."""
    rows = []
    for i, (imp, clk) in enumerate(zip(impressions, clicks, strict=True)):
        day, prov = START + timedelta(days=i), i >= len(impressions) - provisional_tail
        values = {"impressions": imp, "clicks": clk, "video_views": imp // 4, "spend": imp / 10}
        if reach is not None:
            values["reach"] = reach[i]
        rows += [SeriesRow(day, "google_ads", "video_action", "v1", "IN-KL", metric, float(value), prov) for metric, value in values.items()]
    return rows


def test_sample_kerala_original_is_fatigued_on_three_signals() -> None:
    row, _ = by_slice()[("IN-KL", sample.ORIGINAL)]
    assert row.status == "fatigued" and row.pattern == "wearing_out" and row.signals_triggered == 3 and row.confidence == "Moderate"
    assert signal(row, "ctr_decay").triggered and signal(row, "frequency").triggered and signal(row, "repeated_exposure").triggered
    assert not signal(row, "view_rate_decay").triggered
    assert "wear-out" in row.reason and row.window_to == date(2026, 11, 14)


def test_high_exposure_with_response_holding_is_watch_not_fatigue() -> None:
    row, _ = by_slice()[("IN-KL", sample.ADAPTED_B)]
    assert row.status == "watch" and row.pattern == "steady" and row.confidence == "Low"
    assert signal(row, "frequency").triggered and not signal(row, "ctr_decay").triggered
    assert "no sign of wear-out" in row.reason


def test_falling_ctr_without_high_exposure_is_watch_and_says_repetition_is_not_the_likely_cause() -> None:
    row, _ = by_slice()[("IN-TN", sample.ORIGINAL)]
    assert row.status == "watch" and row.pattern == "wearing_out"
    assert signal(row, "ctr_decay").triggered and not signal(row, "frequency").triggered and not signal(row, "repeated_exposure").triggered
    assert "repetition is not the likely cause" in row.reason


def test_a_healthy_version_reads_healthy_and_every_signal_is_available() -> None:
    row, _ = by_slice()[("IN-MH", sample.ORIGINAL)]
    assert row.status == "healthy" and row.signals_triggered == 0 and all(s.available for s in row.signals)
    assert row.confidence == "Moderate"  # the generated sample never reads High


def test_a_drop_inside_the_daily_noise_does_not_count() -> None:
    impressions = [10_000] * DAYS
    # first week alternates 1.5% and 0.1% (mean 0.8%), last week alternates 1% and 0.1%: a 31% fall on a 7-day mean,
    # but far less than twice the day-to-day noise
    clicks = [150, 10, 150, 10, 150, 10, 150] + [100] * 7 + [100, 10, 100, 10, 100, 10, 100]
    rows = synthetic(impressions, clicks, reach=[min(5_000 * (i + 1), 40_000) for i in range(DAYS)])
    row = f.assess(rows, CFG, NAMES)[0][2]
    decay = signal(row, "ctr_decay")
    assert decay.available and not decay.triggered and "noise" in decay.detail
    assert row.status != "fatigued"


def test_a_steady_fall_beats_the_noise_and_pairs_with_high_frequency() -> None:
    impressions = [10_000] * DAYS
    clicks = [round(150 * 0.97 ** i) for i in range(DAYS)]
    reach = [min(2_000 * (i + 1), 14_000) for i in range(DAYS)]  # reach saturates: frequency climbs and new reach dries up
    row = f.assess(synthetic(impressions, clicks, reach), CFG, NAMES)[0][2]
    assert signal(row, "ctr_decay").triggered and signal(row, "frequency").triggered and row.status == "fatigued"


def test_without_reach_the_exposure_signals_are_unavailable_so_fatigue_cannot_be_claimed() -> None:
    impressions = [10_000] * DAYS
    clicks = [round(150 * 0.95 ** i) for i in range(DAYS)]
    row = f.assess(synthetic(impressions, clicks), CFG, NAMES)[0][2]
    assert signal(row, "ctr_decay").triggered
    assert not signal(row, "frequency").available and not signal(row, "repeated_exposure").available
    assert row.status == "watch" and row.confidence == "Low"


def test_provisional_days_are_not_used_and_a_short_series_is_not_assessed() -> None:
    short = synthetic([10_000] * 10, [100] * 10)
    row = f.assess(short, CFG, NAMES)[0][2]
    assert row.status == "not_enough_data" and row.signals == [] and row.window_from is None
    sparse = synthetic([300] * DAYS, [3] * DAYS)
    assert f.assess(sparse, CFG, NAMES)[0][2].status == "not_enough_data"
    tail = synthetic([10_000] * DAYS, [100] * (DAYS - 2) + [1, 1], reach=[2_000 * (i + 1) for i in range(DAYS)], provisional_tail=2)
    row = f.assess(tail, CFG, NAMES)[0][2]
    assert not signal(row, "ctr_decay").triggered  # a collapsed provisional day cannot look like a collapse


def test_low_from_the_start_and_flat_is_static_underperformance_not_wear_out() -> None:
    steady = synthetic([10_000] * DAYS, [60] * DAYS, reach=[3_000 * (i + 1) for i in range(DAYS)])
    strong = [r._replace(version_label="v2") for r in synthetic([10_000] * DAYS, [150] * DAYS, reach=[3_000 * (i + 1) for i in range(DAYS)])]
    rows = by_slice(steady + strong)
    assert rows[("IN-KL", "v1")][0].pattern == "static_low" and rows[("IN-KL", "v2")][0].pattern == "steady"
    assert not signal(rows[("IN-KL", "v1")][0], "ctr_decay").triggered


def test_thresholds_are_read_from_the_configuration() -> None:
    strict = f.assess(SAMPLE, f.FatigueConfig(ctr_decline_pct=0.5, view_rate_decline_pct=0.5, frequency_threshold=20), {})
    assert {row.status for _, _, row, _ in strict} <= {"healthy", "watch"} and not any(r.status == "fatigued" for _, _, r, _ in strict)
    loose = {(a, b): r for a, b, r, _ in f.assess(SAMPLE, f.FatigueConfig(ctr_decline_pct=0.03), {})}
    assert loose[("IN-MH", sample.ORIGINAL)].signals[0].triggered  # a 4.8% fall counts at a 3% threshold
