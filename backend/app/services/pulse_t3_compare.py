"""Predicted vs Actual: the comparison itself, pure code (no database, no model, no network).

What is compared is an ORDER, never a value. A Launch Room score or a share of simulated respondents is not a CTR and is
never turned into one. For the pairs that have both a stored prediction and a settled Pulse result, each pair is ranked on
the prediction and on the actual metric (1 = highest, ties share an average rank), and the two rankings are put side by
side: per pair the gap in ranks, over all pairs Kendall's tau-b.

Only compatible observations are paired (handoff 44): a pair needs a link between the Pulse version label and a Studio
version in that region, a stored verdict for it, settled Pulse days with enough impressions, and the same scoring rules as
the other pairs. Everything left out is returned with its reason.
"""

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import sqrt
from uuid import UUID

from app.schemas import pulse_t3 as v
from app.services.pulse_metrics import BY_NAME, MIN_IMPRESSIONS, SeriesRow, calculate, totals

METHOD_VERSION = "pva-rank-1"
MIN_SETTLED_DAYS = 7
MIN_PAIRS_FOR_TAU = 3
TAU_STRONG = 0.5  # |tau| at or above this reads as mostly agreeing / mostly disagreeing
METRICS: tuple[v.PvaMetric, ...] = ("ctr", "view_rate", "completion_100", "roas")
PREDICTORS: dict[str, str] = {
    "launch_score": "Launch Room score",
    "quick_read_favourable": "Quick Read: share of respondents who reacted positively",
}

METHOD = v.PvaMethod(
    version=METHOD_VERSION,
    steps=[
        "Pair: a Pulse version and a Creative Studio version are paired only where you linked them for that region. A version with no link is never compared.",
        "Predicted: the newest stored Launch Room verdict for that Studio version and region gives the overall score, and the Quick Read counts it read give the share of respondents who reacted positively.",
        "Actual: the chosen Pulse metric over the version's settled days in that region, all platforms together. Provisional days are left out.",
        "Rank: the pairs are ranked on each prediction and on the actual metric, 1 being highest. Only ranks are compared; a score or a panel share is never turned into a predicted result.",
        "Read: same rank is agree, one rank apart is near, two or more apart is differ. Kendall's tau-b is how often two pairs fall in the same order in both rankings; it needs at least three pairs.",
    ],
    assumptions=[
        "The pairs come from different regions, so from different audiences and baselines; the ranking mixes them.",
        "Each version is read over its own settled days, shown on every pair.",
        "The respondents of a Quick Read panel are not independent observations, and a Launch Room score is a rule-based reading of stored observations, not a forecast.",
        "With fewer than about eight pairs the agreement describes what happened; it does not test anything.",
    ],
)


@dataclass(frozen=True)
class QuickReadCounts:
    respondents: int
    positive: int
    negative: int
    understood: int
    relevant: int


@dataclass(frozen=True)
class Prediction:
    """A stored verdict, already tied to a Pulse version label and a region by a link."""

    region_code: str
    pulse_version: str
    version_id: UUID
    studio_label: str
    verdict_id: UUID
    verdict: str
    overall_score: float | None
    scoring_version: str
    rule_version: str
    input_fingerprint: str
    computed_at: datetime
    quick_read: QuickReadCounts | None


@dataclass(frozen=True)
class _Actual:
    value: float
    window_from: date
    window_to: date
    settled_days: int
    impressions: float


def metric_label(metric: str) -> str:
    return BY_NAME[metric].label


def ranks(values: Sequence[float]) -> list[float]:
    """1 = highest. Equal values share the mean of the ranks they span."""
    order = sorted(range(len(values)), key=lambda i: -values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def kendall(predicted: Sequence[float], actual: Sequence[float]) -> tuple[int, int, int, float | None]:
    """(concordant, discordant, tied, tau-b) over every pair of pairs. tau-b is None when either ordering has no spread."""
    conc = disc = tied_p = tied_a = both = 0
    for i in range(len(predicted)):
        for j in range(i + 1, len(predicted)):
            sp, sa = _sign(predicted[i] - predicted[j]), _sign(actual[i] - actual[j])
            if sp == 0 and sa == 0:
                both += 1
            elif sp == 0:
                tied_p += 1
            elif sa == 0:
                tied_a += 1
            elif sp == sa:
                conc += 1
            else:
                disc += 1
    denominator = sqrt((conc + disc + tied_p) * (conc + disc + tied_a))
    tau = None if denominator == 0 else (conc - disc) / denominator
    return conc, disc, tied_p + tied_a + both, tau


def _agreement(gap: float) -> v.PvaAgreement:
    return "agree" if gap == 0 else "near" if gap <= 1 else "differ"


def _actual(rows: list[SeriesRow], metric: str) -> _Actual | str:
    """The metric over the slice's settled days, or the reason it cannot be read."""
    settled = sorted({r.day for r in rows if not r.provisional})
    if len(settled) < MIN_SETTLED_DAYS:
        return f"Fewer than {MIN_SETTLED_DAYS} settled days of results."
    first, last = settled[0], settled[-1]
    t = totals([r for r in rows if not r.provisional], first, last)
    impressions = t.sums.get("impressions", 0.0)
    if impressions < MIN_IMPRESSIONS:
        return f"Fewer than {MIN_IMPRESSIONS} impressions in the settled days."
    value = calculate(metric, t)
    if value is None:
        return f"{metric_label(metric)} cannot be calculated: the ratio has no denominator."
    return _Actual(value, first, last, len(settled), impressions)


def _checks(items: list[tuple[int, float, float]]) -> dict[int, v.PvaCheck]:
    """items: (pair index, predicted value, actual value). Ranks are taken among these items only, like with like."""
    if len(items) < 2:
        return {}
    pr, ar = ranks([i[1] for i in items]), ranks([i[2] for i in items])
    return {
        idx: v.PvaCheck(predicted_value=pv, predicted_rank=p, actual_rank=a, rank_gap=abs(p - a), agreement=_agreement(abs(p - a)))
        for (idx, pv, _), p, a in zip(items, pr, ar, strict=True)
    }


def _summary(predictor: str, items: list[tuple[int, float, float]], checks: dict[int, v.PvaCheck]) -> v.PvaSummary:
    counts = Counter(c.agreement for c in checks.values())
    conc, disc, tied, tau = kendall([i[1] for i in items], [i[2] for i in items]) if len(items) >= 2 else (0, 0, 0, None)
    reading: v.PvaReading
    if len(items) < MIN_PAIRS_FOR_TAU:
        reading, tau = "too_few_pairs", None
    elif tau is None:
        reading = "mixed"
    else:
        reading = "mostly_agrees" if tau >= TAU_STRONG else "mostly_disagrees" if tau <= -TAU_STRONG else "mixed"
    return v.PvaSummary(
        predictor=predictor, label=PREDICTORS[predictor], pairs=len(items),  # type: ignore[arg-type]
        agree=counts["agree"], near=counts["near"], differ=counts["differ"], concordant=conc, discordant=disc, tied=tied,
        kendall_tau_b=None if tau is None else round(tau, 4), reading=reading,
    )


def compare(
    predictions: Sequence[Prediction], rows: Sequence[SeriesRow], metric: str, region_names: dict[str, str],
) -> tuple[list[v.PvaPair], list[v.PvaSummary], list[v.PvaExcluded]]:
    """The pairs, the per-predictor summaries and what was left out, in a stable order (region, then version)."""
    excluded: list[v.PvaExcluded] = []
    usable = sorted(predictions, key=lambda p: (p.region_code, p.pulse_version))
    scoring = Counter(p.scoring_version for p in usable)
    keep = max(sorted(scoring), key=lambda s: scoring[s]) if scoring else None
    kept: list[tuple[Prediction, _Actual]] = []
    for p in usable:
        if p.scoring_version != keep:
            excluded.append(v.PvaExcluded(
                region_code=p.region_code, pulse_version=p.pulse_version,
                reason=f"Scored under scoring rules {p.scoring_version}; the other pairs use {keep}, so they are not compared."))
            continue
        slice_rows = [r for r in rows if r.region_code == p.region_code and r.version_label == p.pulse_version]
        if not slice_rows:
            excluded.append(v.PvaExcluded(region_code=p.region_code, pulse_version=p.pulse_version,
                                          reason="No Pulse results for this version in this region."))
            continue
        actual = _actual(slice_rows, metric)
        if isinstance(actual, str):
            excluded.append(v.PvaExcluded(region_code=p.region_code, pulse_version=p.pulse_version, reason=actual))
            continue
        kept.append((p, actual))

    score_items = [(i, p.overall_score, a.value) for i, (p, a) in enumerate(kept) if p.overall_score is not None]
    quick_items = [
        (i, p.quick_read.positive / p.quick_read.respondents, a.value)
        for i, (p, a) in enumerate(kept) if p.quick_read is not None and p.quick_read.respondents > 0
    ]
    score_checks, quick_checks = _checks(score_items), _checks(quick_items)

    pairs = []
    for i, (p, a) in enumerate(kept):
        qr = p.quick_read
        pairs.append(v.PvaPair(
            region_code=p.region_code, region_name=region_names.get(p.region_code, p.region_code), pulse_version=p.pulse_version,
            version_id=p.version_id, studio_label=p.studio_label,
            predicted=v.PvaPredicted(
                verdict_id=p.verdict_id, verdict=p.verdict, overall_score=p.overall_score,  # type: ignore[arg-type]
                scoring_version=p.scoring_version, rule_version=p.rule_version, computed_at=p.computed_at,
                quick_read=None if qr is None or qr.respondents == 0 else v.PvaQuickRead(
                    respondents=qr.respondents, positive=qr.positive, negative=qr.negative, understood=qr.understood,
                    relevant=qr.relevant, favourable_share=qr.positive / qr.respondents)),
            actual=v.PvaActual(
                metric=metric, value=a.value, window_from=a.window_from, window_to=a.window_to,  # type: ignore[arg-type]
                settled_days=a.settled_days, impressions=a.impressions),
            launch_score=score_checks.get(i), quick_read_favourable=quick_checks.get(i),
        ))
    summaries = [_summary("launch_score", score_items, score_checks), _summary("quick_read_favourable", quick_items, quick_checks)]
    return pairs, summaries, excluded


def fingerprint(metric: str, dataset_version: str, pairs: Sequence[v.PvaPair], excluded: Sequence[v.PvaExcluded]) -> str:
    """SHA-256 of what the comparison read: the same stored verdicts and series under the same method give the same value."""
    payload = {
        "method": METHOD_VERSION, "metric": metric, "dataset": dataset_version,
        "pairs": [
            [p.region_code, p.pulse_version, str(p.version_id), str(p.predicted.verdict_id), p.predicted.overall_score,
             None if p.predicted.quick_read is None else p.predicted.quick_read.favourable_share,
             round(p.actual.value, 9), p.actual.window_from.isoformat(), p.actual.window_to.isoformat()]
            for p in pairs
        ],
        "excluded": [[e.region_code, e.pulse_version, e.reason] for e in excluded],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
