"""The labelled SAMPLE dataset behind the Live Pulse demo (no database, no network, no model).

Everything here is generated, not measured. It exists so the regional dashboard can be shown before an ad account is
connected. Every row carries `source_kind = "sample"` and every API response built from it says so
(`SAMPLE_LABEL`). It is never merged with rows from a connected account.

The generator is seeded: the same constants always give the same rows, so tests and demos are repeatable. The story it
tells is deliberate and small, so that the alert rules have something to find:
  * the Marathi original fits Maharashtra and fits the other three regions poorly;
  * in Kerala the original wears out fast (CTR falls, frequency climbs);
  * in West Bengal, adapted version A meets a costlier auction in its last week (CPM spike).
Numbers are internally consistent: per slice, impressions >= clicks >= conversions, video plays only shrink from 25% to
100%, cumulative reach never exceeds cumulative impressions or shrinks, conversions are credited late (the last two
days are provisional and under-reported).
"""

import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.services.pulse_metrics import SeriesRow

DATASET_VERSION = "pulse-sample-1"
SAMPLE_LABEL = "Sample data, not from a connected account"
START = date(2026, 10, 27)
DAYS = 21
END = START + timedelta(days=DAYS - 1)
PROVISIONAL_DAYS = 2
LAST_UPDATED_AT = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)
REGIONS = ("IN-MH", "IN-TN", "IN-KL", "IN-WB")
CONVERSION_LAG = {END: 0.45, END - timedelta(days=1): 0.75}  # share of the eventual conversions reported so far

ORIGINAL = "v1 Original (Marathi)"
ADAPTED_A = "v2 Adapted A (regional language)"
ADAPTED_B = "v3 Adapted B (local festival reference)"
VERSIONS: dict[str, tuple[str, ...]] = {
    ORIGINAL: REGIONS,
    ADAPTED_A: ("IN-TN", "IN-KL", "IN-WB"),
    ADAPTED_B: ("IN-TN", "IN-KL", "IN-WB"),
}


@dataclass(frozen=True)
class PlatformModel:
    platform: str
    channel: str
    daily_impressions: float
    ctr: float
    cpm: float  # rupees per thousand impressions
    view_rate: float
    quartiles: tuple[float, float, float, float]  # share of impressions played to 25 / 50 / 75 / 100 percent, at fit 1
    click_to_conversion: float


PLATFORM_MODELS = (
    PlatformModel("google_ads", "video_action", 60_000, 0.011, 95.0, 0.21, (0.32, 0.20, 0.14, 0.10), 0.022),
    PlatformModel("youtube", "shorts", 42_000, 0.006, 55.0, 0.31, (0.55, 0.38, 0.27, 0.20), 0.011),
)
REGION_SCALE = {"IN-MH": 1.0, "IN-TN": 0.8, "IN-KL": 0.45, "IN-WB": 0.9}
REGION_CPM = {"IN-MH": 1.15, "IN-TN": 0.95, "IN-KL": 1.0, "IN-WB": 0.85}
REGION_POOL = {"IN-MH": 700_000, "IN-TN": 520_000, "IN-KL": 150_000, "IN-WB": 600_000}  # people the ads can reach
REGION_ORDER_VALUE = {"IN-MH": 1350.0, "IN-TN": 1250.0, "IN-KL": 1180.0, "IN-WB": 1100.0}
FIT = {  # how well a version matches a region's audience (1.0 = the platform's average)
    (ORIGINAL, "IN-MH"): 1.30, (ORIGINAL, "IN-TN"): 0.65, (ORIGINAL, "IN-KL"): 0.60, (ORIGINAL, "IN-WB"): 0.70,
    (ADAPTED_A, "IN-TN"): 1.15, (ADAPTED_A, "IN-KL"): 1.05, (ADAPTED_A, "IN-WB"): 1.00,
    (ADAPTED_B, "IN-TN"): 1.00, (ADAPTED_B, "IN-KL"): 1.20, (ADAPTED_B, "IN-WB"): 0.95,
}
DAILY_CTR_DECAY = {  # compound daily loss of CTR (creative wear-out); the default is mild
    (ORIGINAL, "IN-KL"): 0.030, (ORIGINAL, "IN-TN"): 0.015, (ORIGINAL, "IN-WB"): 0.012,
}
DEFAULT_DECAY = 0.004
CPM_SPIKE = {(ADAPTED_A, "IN-WB"): (START + timedelta(days=12), 1.45)}  # (first day, multiplier)


def _noise(rng: random.Random, spread: float) -> float:
    return min(1 + 2.5 * spread, max(1 - 2.5 * spread, rng.gauss(1.0, spread)))


def _slice_rows(model: PlatformModel, version: str, region: str) -> list[SeriesRow]:
    rng = random.Random(f"{DATASET_VERSION}|{model.platform}|{version}|{region}")
    fit = FIT[(version, region)]
    decay = DAILY_CTR_DECAY.get((version, region), DEFAULT_DECAY)
    pool = REGION_POOL[region] * (1.15 if model.platform == "youtube" else 1.0)
    rows: list[SeriesRow] = []
    cumulative_impressions = 0
    cumulative_reach = 0
    for i in range(DAYS):
        day = START + timedelta(days=i)
        provisional = day > END - timedelta(days=PROVISIONAL_DAYS)
        ramp = (0.6, 0.85)[i] if i < 2 else 1.0  # the first days are the learning phase
        weekend = 1.12 if day.weekday() >= 5 else 1.0
        impressions = round(
            model.daily_impressions * REGION_SCALE[region] * (0.7 + 0.3 * fit) * ramp * weekend * _noise(rng, 0.05)
        )
        ctr = model.ctr * fit * (1 - decay) ** i * _noise(rng, 0.06)
        clicks = min(impressions, round(impressions * ctr))
        cpm = model.cpm * REGION_CPM[region] * _noise(rng, 0.04)
        spike = CPM_SPIKE.get((version, region))
        if spike and day >= spike[0]:
            cpm *= spike[1]
        spend = round(impressions * cpm / 1000, 2)
        hold = min(1.6, 0.6 + 0.4 * fit) * (1 - 0.004) ** i * _noise(rng, 0.03)
        quartile_noise = [_noise(rng, 0.01) for _ in range(4)]
        q = []
        for share, n in zip(model.quartiles, quartile_noise, strict=True):
            q.append(min(impressions, round(impressions * min(0.9, share * hold * n))))
        for k in range(1, 4):  # plays only shrink from 25% to 100%
            q[k] = min(q[k], q[k - 1])
        views = min(impressions, round(impressions * model.view_rate * hold * _noise(rng, 0.02)))
        eventual = min(clicks, round(clicks * model.click_to_conversion * fit * _noise(rng, 0.10)))
        conversions = round(eventual * CONVERSION_LAG.get(day, 1.0))
        value = round(conversions * REGION_ORDER_VALUE[region] * _noise(rng, 0.05), 2)
        cumulative_impressions += impressions
        new_reach = min(
            cumulative_impressions, round(pool * (1 - math.exp(-cumulative_impressions / pool)))
        )
        cumulative_reach = max(cumulative_reach, new_reach)
        values = {
            "impressions": impressions, "reach": cumulative_reach, "clicks": clicks, "spend": spend,
            "video_views": views, "video_q25": q[0], "video_q50": q[1], "video_q75": q[2], "video_q100": q[3],
            "conversions": conversions, "conversion_value": value,
        }
        rows.extend(
            SeriesRow(day, model.platform, model.channel, version, region, metric, float(v), provisional)
            for metric, v in values.items()
        )
    return rows


def generate_sample_rows() -> list[SeriesRow]:
    """All sample rows, in a stable order. Identical on every call."""
    return [
        row
        for version, regions in VERSIONS.items()
        for region in regions
        for model in PLATFORM_MODELS
        for row in _slice_rows(model, version, region)
    ]


SAMPLE_LIMITATIONS = (
    "Generated with a fixed seed. No real audience, ad platform or account stands behind these numbers.",
    "Real platforms report with a delay and credit conversions days later; the sample imitates that, so the last "
    f"{PROVISIONAL_DAYS} days are provisional and their conversions are under-reported.",
    "Differences between versions are descriptive. They are not an experiment, carry no significance test, and say "
    "nothing about how a real campaign would perform.",
)
