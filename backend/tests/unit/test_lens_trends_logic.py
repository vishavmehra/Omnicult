"""Trend Radar arithmetic and article selection: windows, thresholds, edition normalisation, confidence. Pure functions."""

from datetime import date

import pytest

from app.analytics import lens_trends as t

FIRST = date(2024, 11, 1)


def series(values: list[int], first: date = FIRST) -> list[t.MonthPoint]:
    return [t.MonthPoint(t.add_months(first, i), v) for i, v in enumerate(values)]


def flat_edition(n: int = 24, total: int = 1_000_000, first: date = FIRST) -> list[t.MonthPoint]:
    return series([total] * n, first)


# --- monthly -------------------------------------------------------------------------------------------------------


def test_daily_points_sum_into_months_and_a_missing_month_inside_the_series_is_zero() -> None:
    points = [(date(2025, 1, 5), 10), (date(2025, 1, 20), 5), (date(2025, 3, 2), 7)]
    assert [(p.month, p.views) for p in t.monthly(points)] == [(date(2025, 1, 1), 15), (date(2025, 2, 1), 0), (date(2025, 3, 1), 7)]


def test_months_before_the_first_point_are_not_invented_and_an_empty_series_is_empty() -> None:
    assert t.monthly([]) == []
    assert t.monthly([(date(2025, 6, 1), 9)])[0].month == date(2025, 6, 1)


def test_add_months_crosses_year_ends_both_ways() -> None:
    assert t.add_months(date(2025, 11, 1), 3) == date(2026, 2, 1)
    assert t.add_months(date(2025, 2, 1), -3) == date(2024, 11, 1)


# --- measure -------------------------------------------------------------------------------------------------------


def test_a_clear_rise_over_two_years_is_rising_with_its_windows_and_numbers() -> None:
    m = t.measure(series([100] * 12 + [200] * 12), flat_edition())
    assert m.direction == "rising" and m.normalised
    assert m.recent_mean == 200 and m.prior_mean == 100 and m.change == pytest.approx(1.0) and m.raw_change == pytest.approx(1.0)
    assert m.recent_share == pytest.approx(200.0) and m.prior_share == pytest.approx(100.0)  # per million edition views
    assert m.slope_per_month and m.slope_per_month > 0 and m.edition_change == pytest.approx(0.0)
    assert m.recent_window == (date(2025, 11, 1), date(2026, 10, 1)) and m.prior_window == (date(2024, 11, 1), date(2025, 10, 1))
    assert m.quarter_window == (date(2026, 8, 1), date(2026, 10, 1)) and m.quarter_year_ago_window == (date(2025, 8, 1), date(2025, 10, 1))


def test_a_clear_fall_is_falling_and_a_change_inside_twenty_percent_is_steady() -> None:
    assert t.measure(series([300] * 12 + [150] * 12), flat_edition()).direction == "falling"
    m = t.measure(series([100, 110, 95, 105, 100, 108, 102, 98, 104, 110, 100, 106] * 2), flat_edition())
    assert m.direction == "steady" and m.change is not None and abs(m.change) < t.CHANGE_THRESHOLD


def test_a_fall_that_only_follows_the_whole_edition_is_not_a_fall() -> None:
    """The regional editions lost a third or more of their readers: the article fell with them, so its share held."""
    edition = series([1_000_000] * 12 + [600_000] * 12)
    m = t.measure(series([1000] * 12 + [600] * 12), edition)
    assert m.raw_change == pytest.approx(-0.4) and m.edition_change == pytest.approx(-0.4)
    assert m.change == pytest.approx(0.0) and m.direction == "steady"
    raw_only = t.measure(series([1000] * 12 + [600] * 12))
    assert raw_only.direction == "falling" and not raw_only.normalised and "not adjusted" in raw_only.reasons[-1]


def test_an_article_that_falls_faster_than_its_edition_is_falling_in_share() -> None:
    m = t.measure(series([1000] * 12 + [300] * 12), series([1_000_000] * 12 + [800_000] * 12))
    assert m.change == pytest.approx(-0.625) and m.direction == "falling"


def test_the_label_uses_two_whole_years_so_a_festival_that_moves_is_compared_with_itself() -> None:
    # the peak sits in a different quarter each year, but each year has one peak: no change between years
    year_a = [50, 50, 50, 50, 50, 50, 50, 900, 900, 50, 50, 50]
    year_b = [50, 50, 50, 50, 900, 900, 50, 50, 50, 50, 50, 50]
    m = t.measure(series(year_a + year_b), flat_edition())
    assert m.direction == "steady" and m.change == pytest.approx(0.0)


def test_a_year_that_is_up_while_the_line_through_both_years_slopes_down_is_mixed() -> None:
    m = t.measure(series([4000] + [100] * 11 + [560] * 12), flat_edition())
    assert m.change is not None and m.change >= t.CHANGE_THRESHOLD
    assert m.slope_per_month is not None and m.slope_per_month < 0
    assert m.direction == "mixed" and "slope" in m.reasons[0]


def test_the_last_three_months_pointing_the_other_way_is_said_but_does_not_change_the_label() -> None:
    m = t.measure(series([100] * 12 + [300] * 9 + [100] * 3), flat_edition())
    assert m.direction == "rising" and m.quarter_change == pytest.approx(0.0)
    m = t.measure(series([300] * 12 + [300] * 9 + [90] * 3), flat_edition())
    assert m.quarter_change == pytest.approx(-0.7) and m.direction == "steady" and "points the other way" in m.reasons[0]


def test_fewer_than_two_years_or_too_few_views_is_insufficient_with_a_reason() -> None:
    short = t.measure(series([100] * 23), flat_edition(23))
    assert short.direction == "insufficient" and "Only 23 months" in short.reasons[0]
    thin = t.measure(series([2, 3, 1, 2, 4, 3, 2, 3, 4, 2, 9, 12] * 2), flat_edition())
    assert thin.direction == "insufficient" and "Fewer than 30 views" in thin.reasons[0]
    assert t.measure([]).direction == "insufficient"


def test_no_views_in_the_earlier_year_is_not_a_percentage() -> None:
    m = t.measure(series([0] * 12 + [90] * 12), flat_edition())
    assert m.direction == "insufficient" and m.change is None and "nothing to compare" in m.reasons[0]


def test_an_edition_total_that_misses_a_month_falls_back_to_raw_views_and_says_so() -> None:
    m = t.measure(series([100] * 12 + [200] * 12), flat_edition(23))
    assert not m.normalised and m.direction == "rising" and any("not adjusted" in r for r in m.reasons)


# --- confidence ----------------------------------------------------------------------------------------------------


def test_confidence_is_low_when_the_direction_cannot_be_read_or_the_counts_are_small() -> None:
    assert t.confidence(t.measure(series([1, 2, 3])), None, fixture=False)[0] == "low"
    level, reasons = t.confidence(t.measure(series([30] * 12 + [60] * 12), flat_edition()), None, fixture=False)
    assert level == "low" and "views a month" in reasons[0]  # rising, but about 60 views a month
    mixed = t.measure(series([4000] + [100] * 11 + [560] * 12), flat_edition())
    assert t.confidence(mixed, None, fixture=False)[0] == "low"
    unadjusted = t.measure(series([500] * 12 + [900] * 12))
    level, reasons = t.confidence(unadjusted, None, fixture=False)
    assert level == "low" and "Not adjusted" in reasons[0]


def test_two_years_at_a_hundred_views_is_moderate_and_solid_counts_with_every_view_agreeing_is_high() -> None:
    moderate = t.measure(series([100] * 12 + [200] * 12), flat_edition())
    assert t.confidence(moderate, None, fixture=False)[0] == "moderate" and moderate.direction == "rising"
    solid = t.measure(series([400] * 12 + [800] * 12), flat_edition())
    assert t.confidence(solid, None, fixture=False)[0] == "high"
    english_falling = t.measure(series([400] * 12 + [200] * 12), flat_edition())
    level, reasons = t.confidence(solid, english_falling, fixture=False)
    assert level == "moderate" and any("English edition reads falling" in r for r in reasons)
    lately_falling = t.measure(series([400] * 12 + [900] * 9 + [200] * 3), flat_edition())
    assert lately_falling.direction == "rising" and t.confidence(lately_falling, None, fixture=False)[0] == "moderate"


def test_a_fixture_series_never_reaches_high() -> None:
    solid = t.measure(series([400] * 12 + [800] * 12), flat_edition())
    level, reasons = t.confidence(solid, None, fixture=True)
    assert level == "moderate" and not any("fixture" in r.lower() for r in reasons)


# --- which article --------------------------------------------------------------------------------------------------


def test_a_festival_gets_its_own_article_never_the_states() -> None:
    claims = [
        ("festival:puthandu", [("wikipedia", "https://en.wikipedia.org/wiki/Puthandu"), ("wikipedia", "https://en.wikipedia.org/wiki/Tamil_Nadu")]),
        ("festival:thaipusam", [("wikipedia", "https://en.wikipedia.org/wiki/Tamil_Nadu")]),
        ("festival:deepavali", [("wikipedia", "https://en.wikipedia.org/wiki/Diwali")]),
        ("festival:pongal", [("wikipedia", "https://en.wikipedia.org/wiki/Pongal_(festival)"), ("curated_reference", "https://example.org/x")]),
        ("region:IN-TN", [("wikipedia", "https://en.wikipedia.org/wiki/Tamil_Nadu")]),
    ]
    assert t.festival_articles(claims, "Tamil Nadu") == [
        ("festival:puthandu", "Puthandu"), ("festival:deepavali", "Diwali"), ("festival:pongal", "Pongal (festival)")]


def test_two_festivals_citing_one_article_give_one_term() -> None:
    claims = [("festival:diwali", [("wikipedia", "https://en.wikipedia.org/wiki/Diwali")]),
              ("festival:deepavali", [("wikipedia", "https://en.wikipedia.org/wiki/Diwali")])]
    assert t.festival_articles(claims, "Maharashtra") == [("festival:diwali", "Diwali")]
