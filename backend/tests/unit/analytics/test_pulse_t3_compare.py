"""Predicted vs Actual: ranking, rank correlation and which pairs are compatible, on the labelled sample series."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.services import pulse_sample as sample
from app.services import pulse_t3_compare as c
from app.services.pulse_metrics import SeriesRow

NAMES = {"IN-MH": "Maharashtra", "IN-TN": "Tamil Nadu", "IN-KL": "Kerala", "IN-WB": "West Bengal"}
SAMPLE = sample.generate_sample_rows()
V1, V2 = sample.ORIGINAL, sample.ADAPTED_A


def prediction(region: str, version: str, score: float | None, positive: int | None = 8, *, scoring: str = "mvp-2") -> c.Prediction:
    return c.Prediction(
        region_code=region, pulse_version=version, version_id=uuid4(), studio_label=f"{region} studio", verdict_id=uuid4(),
        verdict="go", overall_score=score, scoring_version=scoring, rule_version="ready-1", input_fingerprint=f"fp-{region}-{version}",
        computed_at=datetime(2026, 11, 18, tzinfo=UTC),
        quick_read=None if positive is None else c.QuickReadCounts(respondents=12, positive=positive, negative=0, understood=10, relevant=8))


def actual_ctr(region: str, version: str) -> float:
    pair = c.compare([prediction(region, version, 50.0)], SAMPLE, "ctr", NAMES)[0]
    return pair[0].actual.value


def test_ranks_give_ties_the_mean_rank_and_one_to_the_highest() -> None:
    assert c.ranks([10, 30, 20]) == [3, 1, 2]
    assert c.ranks([5, 5, 1]) == [1.5, 1.5, 3]
    assert c.ranks([2, 2, 2]) == [2, 2, 2]


def test_kendall_counts_orderings_and_ties_exactly() -> None:
    assert c.kendall([1, 2, 3, 4], [10, 20, 30, 40]) == (6, 0, 0, 1.0)
    assert c.kendall([1, 2, 3, 4], [40, 30, 20, 10]) == (0, 6, 0, -1.0)
    # [1, 1, 2] against [3, 2, 1]: two discordant pairs and one pair tied in the prediction only, tau-b = -2 / sqrt(3 * 2)
    conc, disc, tied, tau = c.kendall([1, 1, 2], [3, 2, 1])
    assert (conc, disc, tied) == (0, 2, 1) and tau == pytest.approx(-2 / 6 ** 0.5)
    assert c.kendall([1, 1, 1], [1, 2, 3])[3] is None  # no spread in the prediction: no coefficient


def test_a_prediction_ordered_like_the_results_agrees_and_one_ordered_against_them_differs() -> None:
    cells = [("IN-MH", V1), ("IN-TN", V2), ("IN-KL", V2), ("IN-WB", V2)]
    results = {cell: actual_ctr(*cell) for cell in cells}
    best_first = sorted(cells, key=lambda k: -results[k])
    aligned = [prediction(r, v, 90.0 - 10 * i) for i, (r, v) in enumerate(best_first)]
    pairs, summaries, excluded = c.compare(aligned, SAMPLE, "ctr", NAMES)
    score = summaries[0]
    assert excluded == [] and score.pairs == 4 and score.agree == 4 and score.kendall_tau_b == 1.0 and score.reading == "mostly_agrees"
    assert all(p.launch_score and p.launch_score.rank_gap == 0 for p in pairs)
    reversed_ = [prediction(r, v, 40.0 + 10 * i) for i, (r, v) in enumerate(best_first)]
    pairs, summaries, _ = c.compare(reversed_, SAMPLE, "ctr", NAMES)
    assert summaries[0].kendall_tau_b == -1.0 and summaries[0].reading == "mostly_disagrees" and summaries[0].differ >= 2


def test_every_rank_check_is_taken_among_pairs_that_have_that_predictor() -> None:
    preds = [prediction("IN-MH", V1, 70.0, 6), prediction("IN-TN", V2, 80.0, None), prediction("IN-KL", V2, 60.0, 4)]
    pairs, summaries, _ = c.compare(preds, SAMPLE, "ctr", NAMES)
    by_cell = {(p.region_code, p.pulse_version): p for p in pairs}
    assert by_cell[("IN-TN", V2)].quick_read_favourable is None  # no Quick Read counts: not ranked on that predictor
    assert summaries[0].pairs == 3 and summaries[1].pairs == 2
    assert summaries[1].reading == "too_few_pairs" and summaries[1].kendall_tau_b is None


def test_a_pair_that_cannot_be_compared_is_left_out_with_its_reason() -> None:
    thin = [r for r in SAMPLE if not (r.region_code == "IN-KL" and r.version_label == V2 and r.day >= sample.START + timedelta(days=3))]
    preds = [
        prediction("IN-MH", V1, 70.0), prediction("IN-TN", V2, 80.0), prediction("IN-KL", V2, 60.0),
        prediction("IN-WB", V2, 55.0, scoring="mvp-1"), prediction("IN-MH", "v9 Never ran", 50.0),
    ]
    pairs, _, excluded = c.compare(preds, thin, "ctr", NAMES)
    reasons = {(e.region_code, e.pulse_version): e.reason for e in excluded}
    assert {(p.region_code, p.pulse_version) for p in pairs} == {("IN-MH", V1), ("IN-TN", V2)}
    assert "settled days" in reasons[("IN-KL", V2)]
    assert "scoring rules mvp-1" in reasons[("IN-WB", V2)]
    assert reasons[("IN-MH", "v9 Never ran")] == "No Pulse results for this version in this region."


def test_provisional_days_never_enter_the_actual_value() -> None:
    preds = [prediction("IN-MH", V1, 70.0)]
    pair = c.compare(preds, SAMPLE, "ctr", NAMES)[0][0]
    assert pair.actual.window_to.isoformat() == "2026-11-14" and pair.actual.settled_days == 19  # the last two days are provisional
    inflated = [r._replace(value=r.value * 100) if r.provisional and r.metric == "clicks" else r for r in SAMPLE]
    assert c.compare(preds, inflated, "ctr", NAMES)[0][0].actual.value == pair.actual.value


def test_the_fingerprint_follows_the_inputs_and_nothing_else() -> None:
    preds = [prediction("IN-MH", V1, 70.0), prediction("IN-TN", V2, 80.0)]
    first = c.compare(preds, SAMPLE, "ctr", NAMES)
    again = c.compare(preds, SAMPLE, "ctr", NAMES)
    assert c.fingerprint("ctr", "d1", first[0], first[2]) == c.fingerprint("ctr", "d1", again[0], again[2])
    assert c.fingerprint("ctr", "d1", first[0], first[2]) != c.fingerprint("view_rate", "d1", first[0], first[2])
    changed = c.compare([prediction("IN-MH", V1, 71.0), preds[1]], SAMPLE, "ctr", NAMES)
    assert c.fingerprint("ctr", "d1", changed[0], changed[2]) != c.fingerprint("ctr", "d1", first[0], first[2])


def test_series_rows_are_not_mutated() -> None:
    before = list(SAMPLE)
    c.compare([prediction("IN-MH", V1, 70.0)], SAMPLE, "roas", NAMES)
    assert before == SAMPLE and isinstance(SAMPLE[0], SeriesRow)
