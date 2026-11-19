"""The Live Pulse sample generator: deterministic, internally consistent, provisional days, labelled."""

import hashlib
import os
import subprocess
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import pytest

from app.services import pulse_sample as sample
from app.services.pulse_metrics import calculate, totals

BACKEND = Path(__file__).resolve().parents[3]
ROWS = sample.generate_sample_rows()


def by_slice() -> dict[tuple[str, str, str, str], dict[str, list]]:
    out: dict[tuple[str, str, str, str], dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in ROWS:
        out[(r.platform, r.channel, r.version_label, r.region_code)][r.metric].append(r)
    for metrics in out.values():
        for rows in metrics.values():
            rows.sort(key=lambda r: r.day)
    return out


SLICES = by_slice()


def test_shape_matches_the_brief() -> None:
    assert sample.DAYS == 21 and (sample.END - sample.START).days == 20
    assert {r.region_code for r in ROWS} == {"IN-MH", "IN-TN", "IN-KL", "IN-WB"}
    assert {r.platform for r in ROWS} == {"google_ads", "youtube"}
    assert len({r.version_label for r in ROWS}) == 3 and sample.ORIGINAL.endswith("(Marathi)")
    assert len(ROWS) == 4620  # 10 version-region pairs x 2 platforms x 21 days x 11 base metrics
    assert {r.day for r in ROWS} == {sample.START + timedelta(days=i) for i in range(sample.DAYS)}


def test_identical_on_every_call_and_in_every_process() -> None:
    assert sample.generate_sample_rows() == ROWS
    code = (
        "import hashlib; from app.services.pulse_sample import generate_sample_rows as g; "
        "print(hashlib.sha256(repr(g()).encode()).hexdigest())"
    )
    digests = {
        subprocess.run(
            [sys.executable, "-c", code], cwd=BACKEND, env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(BACKEND)},
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        for seed in ("1", "2")
    }
    assert len(digests) == 1  # not even Python's hash seed changes a value
    assert digests == {hashlib.sha256(repr(ROWS).encode()).hexdigest()}


@pytest.mark.parametrize("key", sorted(SLICES))
def test_each_slice_is_internally_consistent(key: tuple[str, str, str, str]) -> None:
    m = {name: [r.value for r in rows] for name, rows in SLICES[key].items()}
    days = len(m["impressions"])
    assert days == sample.DAYS
    cumulative = 0.0
    for i in range(days):
        impressions, clicks = m["impressions"][i], m["clicks"][i]
        assert impressions > 0 and 0 <= m["conversions"][i] <= clicks <= impressions
        assert m["spend"][i] > 0 and m["conversion_value"][i] >= 0
        assert 0 <= m["video_views"][i] <= impressions
        assert impressions >= m["video_q25"][i] >= m["video_q50"][i] >= m["video_q75"][i] >= m["video_q100"][i] >= 0
        cumulative += impressions
        assert m["reach"][i] <= cumulative  # nobody is reached more often than the ad was shown
        assert i == 0 or m["reach"][i] >= m["reach"][i - 1]  # cumulative reach never shrinks
    t = totals([r for rs in SLICES[key].values() for r in rs], sample.START, sample.END)
    assert t.sums["impressions"] >= t.sums["reach"] >= t.sums["clicks"]  # impressions >= reach >= clicks
    assert 0.002 <= calculate("ctr", t) <= 0.025  # plausible click-through rates
    assert 20 <= calculate("cpm", t) <= 200 and calculate("frequency", t) >= 1.0


def test_last_two_days_are_provisional_and_nothing_else() -> None:
    provisional = {r.day for r in ROWS if r.provisional}
    assert provisional == {sample.END, sample.END - timedelta(days=1)}
    assert all(r.provisional == (r.day in provisional) for r in ROWS)


def test_conversions_lag_on_the_provisional_days() -> None:
    per_day: dict = defaultdict(float)  # per-slice counts can be single digits; the lag shows in the daily total
    for r in ROWS:
        if r.metric == "conversions":
            per_day[r.day] += r.value
    days = sorted(per_day)
    average = sum(per_day[d] for d in days[-9:-2]) / 7  # the last 7 settled days
    assert per_day[days[-1]] < 0.7 * average and per_day[days[-2]] < 0.9 * average  # the newest days are under-reported


def test_sample_is_labelled() -> None:
    assert sample.SAMPLE_LABEL == "Live Pulse dataset"
    assert sample.LAST_UPDATED_AT.tzinfo is not None and sample.SAMPLE_LIMITATIONS
