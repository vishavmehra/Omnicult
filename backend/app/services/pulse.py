"""Live Pulse service: the labelled sample dataset and the regional dashboard built on it.

Access follows the campaign: a campaign in a workspace the caller does not belong to is a 404; loading the sample
needs an owner or editor role. Series are read from `metric_series` with `source_kind = 'sample'` only: this build has
no connected account, and sample rows must never be mixed with real ones.
"""

from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime
from typing import NamedTuple
from urllib.parse import urlencode
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, ValidationFailed
from app.db import models as m
from app.db.session import read_session, session
from app.reference.india import REGIONS
from app.schemas import pulse as v
from app.schemas.common import ErrorDetail
from app.services import pulse_sample as sample
from app.services.audit import record_audit
from app.services.common import get_owned, require_writable
from app.services.pulse_alerts import AlertConfig, evaluate
from app.services.pulse_metrics import (
    BY_NAME, DEFINITIONS, INPUTS, REACH_CAVEAT, SeriesRow, calculate, daily_totals, is_provisional, values_of,
)

REGION_NAMES = {r.code: r.name for r in REGIONS}
CARD_GROUPS: tuple[v.MetricGroup, ...] = ("delivery", "cost", "response", "video", "outcome", "creative_health")
DEFAULT_COMPARE = ("ctr", "cpm", "cpa", "roas", "view_rate", "completion_100", "ctr_change_vs_first_week")
PLATFORM_LABELS = {"google_ads": "Google Ads", "youtube": "YouTube", "meta": "Meta Ads", "ga4": "GA4"}
ROADMAP_NOTE = "Roadmap: connecting ad accounts is not available in this build. Pulse shows the labelled sample dataset only."
NOT_LOADED = "The sample dataset is not loaded for this campaign. Load it first with POST /campaigns/{id}/pulse/sample-dataset."
CATALOGUE_NOTES = (
    "Calculated metrics are computed in code from stored base metrics; a ratio with no denominator is null, never 0.",
    "Metrics with in_sample=false are defined for the product but have no values in the sample dataset.",
    REACH_CAVEAT,
)


class Loaded(NamedTuple):
    rows: list[SeriesRow]
    dataset_version: str
    last_updated_at: datetime


async def _campaign(s: AsyncSession, user_id: UUID, campaign_id: UUID, *, writable: bool = False) -> m.Project:
    _, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
    if writable:
        require_writable(project)
    return project


async def _load(s: AsyncSession, campaign_id: UUID) -> Loaded:
    cols = (m.MetricSeries.day, m.MetricSeries.platform, m.MetricSeries.channel, m.MetricSeries.version_label,
            m.MetricSeries.region_code, m.MetricSeries.metric, m.MetricSeries.value, m.MetricSeries.provisional)
    stmt = select(*cols, m.MetricSeries.dataset_version, m.MetricSeries.last_updated_at).where(
        m.MetricSeries.campaign_id == campaign_id, m.MetricSeries.source_kind == "sample")
    found = (await s.execute(stmt)).all()
    if not found:
        raise Conflict(NOT_LOADED)
    return Loaded([SeriesRow(*r[:8]) for r in found], found[0][8], max(r[9] for r in found))


def _stamp(loaded: Loaded) -> dict:
    return {
        "label": sample.SAMPLE_LABEL, "dataset_version": loaded.dataset_version,
        "last_updated_at": loaded.last_updated_at, "limitations": list(sample.SAMPLE_LIMITATIONS),
    }


def _bad(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


def _span(rows: list[SeriesRow], date_from: date | None, date_to: date | None) -> tuple[date, date]:
    first, last = min(r.day for r in rows), max(r.day for r in rows)
    start, end = date_from or first, date_to or last
    if start > end:
        raise _bad("date_from", "date_from must not be after date_to.")
    return start, end


def _filter(rows: list[SeriesRow], region: str | None = None, version: str | None = None,
            platform: str | None = None) -> list[SeriesRow]:
    for field, value, present in (
        ("region", region, {r.region_code for r in rows}),
        ("version", version, {r.version_label for r in rows}),
        ("platform", platform, {r.platform for r in rows}),
    ):
        if value is not None and value not in present:
            raise _bad(field, f"Not in the sample dataset. Available: {', '.join(sorted(present))}.")
    return [
        r for r in rows
        if (region is None or r.region_code == region) and (version is None or r.version_label == version)
        and (platform is None or r.platform == platform)
    ]


def _check_metrics(names: list[str], *, daily: bool = False) -> None:
    for name in names:
        d = BY_NAME.get(name)
        if d is None:
            raise _bad("metric", f"Unknown metric '{name}'. See GET /campaigns/{{id}}/pulse/metrics.")
        if not d.in_sample:
            raise _bad("metric", f"'{name}' has no values in the sample dataset.")
        if daily and d.aggregation == "window_change":
            raise _bad("metric", f"'{name}' compares two weeks; it is a single value, not a daily series.")


def _platform_index(rows: list[SeriesRow], date_from: date, date_to: date) -> Callable[[str], list[str]]:
    """name -> the platforms with rows feeding that metric inside the range."""
    seen: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if date_from <= r.day <= date_to:
            seen[r.metric].add(r.platform)

    def platforms_of(name: str) -> list[str]:
        inputs = {"impressions"} if BY_NAME[name].aggregation == "window_change" else set(INPUTS.get(name, (name,)))
        return sorted(set().union(*(seen[i] for i in inputs)))

    return platforms_of


# --- sample dataset -----------------------------------------------------------------------


def _status(rows: list[SeriesRow], last_updated_at: datetime | None, dataset_version: str) -> v.DatasetStatus:
    prov = [r.day for r in rows if r.provisional]
    return v.DatasetStatus(
        loaded=bool(rows), label=sample.SAMPLE_LABEL, dataset_version=dataset_version, last_updated_at=last_updated_at,
        row_count=len(rows), date_from=min((r.day for r in rows), default=None),
        date_to=max((r.day for r in rows), default=None), provisional_from=min(prov, default=None),
        regions=sorted({r.region_code for r in rows}), versions=sorted({r.version_label for r in rows}),
        platforms=sorted({r.platform for r in rows}),
        note=("Generated, deterministic sample data. " if rows else "Not loaded. ") + sample.SAMPLE_LABEL + ".",
    )


async def dataset_status(user_id: UUID, campaign_id: UUID) -> v.DatasetStatus:
    async with read_session() as s:
        await _campaign(s, user_id, campaign_id)
        try:
            loaded = await _load(s, campaign_id)
        except Conflict:
            return _status([], None, sample.DATASET_VERSION)
    return _status(loaded.rows, loaded.last_updated_at, loaded.dataset_version)


async def load_sample(user_id: UUID, campaign_id: UUID) -> v.DatasetStatus:
    """Replace the campaign's sample rows with a fresh copy of the generated dataset (identical on every call)."""
    rows = sample.generate_sample_rows()
    async with session() as s, s.begin():
        project = await _campaign(s, user_id, campaign_id, writable=True)
        await s.execute(m.MetricSeries.__table__.delete().where(
            m.MetricSeries.campaign_id == campaign_id, m.MetricSeries.source_kind == "sample"))
        await s.execute(insert(m.MetricSeries), [
            {
                "id": uuid4(), "workspace_id": project.workspace_id, "project_id": project.id, "campaign_id": campaign_id,
                "day": r.day, "platform": r.platform, "channel": r.channel, "version_label": r.version_label,
                "region_code": r.region_code, "metric": r.metric, "value": r.value, "provisional": r.provisional,
                "source_kind": "sample", "dataset_version": sample.DATASET_VERSION,
                "last_updated_at": sample.LAST_UPDATED_AT,
            }
            for r in rows
        ])
        await record_audit(
            s, action="pulse.sample_dataset.load", target_type="campaign", target_id=str(campaign_id),
            workspace_id=project.workspace_id, actor_user_id=user_id,
            detail={"dataset_version": sample.DATASET_VERSION, "rows": len(rows)},
        )
    from app.services import pulse_t3_alerts  # local import: that module reads this one

    await pulse_t3_alerts.evaluate_after_refresh(user_id, campaign_id)  # saved alert rules run on every refresh
    return _status(rows, sample.LAST_UPDATED_AT, sample.DATASET_VERSION)


# --- catalogue, platform status, predicted vs actual --------------------------------------


async def metric_catalogue(user_id: UUID, campaign_id: UUID) -> v.MetricCatalogue:
    async with read_session() as s:
        await _campaign(s, user_id, campaign_id)
    return v.MetricCatalogue(
        items=[
            v.MetricDefinition(
                name=d.name, label=d.label, unit=d.unit, group=d.group, kind=d.kind, formula=d.formula,
                description=d.description, platforms=list(d.platforms), in_sample=d.in_sample, aggregation=d.aggregation,
            )
            for d in DEFINITIONS
        ],
        notes=list(CATALOGUE_NOTES),
    )


async def connections(user_id: UUID, campaign_id: UUID) -> v.PlatformConnectionList:
    """Read-only status per platform. Nothing in this build writes a connection, so every platform reads not connected."""
    async with read_session() as s:
        project = await _campaign(s, user_id, campaign_id)
        stored = {}
        if project.workspace_id is not None:
            found = await s.execute(select(m.PlatformConnection).where(m.PlatformConnection.workspace_id == project.workspace_id))
            stored = {c.platform: c for c in found.scalars()}
    items = []
    for platform in ("google_ads", "youtube", "meta", "ga4"):
        row = stored.get(platform)
        items.append(v.PlatformConnectionStatus(
            platform=platform, label=PLATFORM_LABELS[platform],  # type: ignore[arg-type]
            status=row.status if row else "not_connected",  # type: ignore[arg-type]
            last_sync_at=row.last_sync_at if row else None, scopes=list(row.scopes) if row else [], note=ROADMAP_NOTE,
        ))
    return v.PlatformConnectionList(items=items, note=ROADMAP_NOTE)


async def predicted_vs_actual(user_id: UUID, campaign_id: UUID) -> v.PredictedVsActual:
    """Never fabricates a calibration: with no real results there is nothing to compare, and sample rows do not count."""
    async with read_session() as s:
        await _campaign(s, user_id, campaign_id)
        real = int(await s.scalar(select(func.count()).select_from(m.MetricSeries).where(
            m.MetricSeries.campaign_id == campaign_id, m.MetricSeries.source_kind != "sample")) or 0)
    return v.PredictedVsActual(
        reason=(
            "Not available. Predicted vs Actual compares the panel's read with real regional results, and no real "
            "results exist for this campaign. The sample dataset is generated and is never compared with predictions."
            if real == 0 else
            "Not available in this build. Real result rows exist, but the calibration method (compatible observations, "
            "stored calibration history) is roadmap, so no comparison is shown."
        ),
        real_result_rows=real,
        requirements=[
            "Real results from a connected account or a test account, with source records.",
            "A stored panel prediction for the same region, version, metric and period.",
            "A documented method for comparing only compatible observations.",
        ],
    )


# --- dashboard ----------------------------------------------------------------------------


def _metric_value(name: str, result: tuple[float | None, bool], platforms: list[str], region: str,
                  version: str | None, date_from: date, date_to: date, last_updated_at: datetime) -> v.MetricValue:
    d = BY_NAME[name]
    return v.MetricValue(
        metric=name, label=d.label, unit=d.unit, group=d.group, value=result[0], provisional=result[1],
        platforms=platforms, region_code=region, version_label=version,
        date_from=date_from, date_to=date_to, last_updated_at=last_updated_at,
    )


async def region_summary(user_id: UUID, campaign_id: UUID, *, date_from: date | None, date_to: date | None,
                         platform: str | None, version: str | None, region: str | None) -> v.RegionSummary:
    async with read_session() as s:
        await _campaign(s, user_id, campaign_id)
        loaded = await _load(s, campaign_id)
    start, end = _span(loaded.rows, date_from, date_to)
    rows = _filter(loaded.rows, region, version, platform)
    cards = []
    for code in sorted({r.region_code for r in rows}):
        rrows = [r for r in rows if r.region_code == code]
        results = values_of([d.name for d in DEFINITIONS if d.in_sample], rrows, start, end)
        platforms_of = _platform_index(rrows, start, end)
        groups = [
            v.GroupCard(group=g, metrics=[
                _metric_value(d.name, results[d.name], platforms_of(d.name), code, version, start, end, loaded.last_updated_at)
                for d in DEFINITIONS if d.group == g and d.in_sample
            ])
            for g in CARD_GROUPS
        ]
        cards.append(v.RegionCard(
            region_code=code, region_name=REGION_NAMES.get(code, code),
            versions=sorted({r.version_label for r in rrows}), groups=groups,
        ))
    return v.RegionSummary(
        **_stamp(loaded), date_from=start, date_to=end, platform=platform,  # type: ignore[arg-type]
        version_label=version, regions=cards,
        caveats=[REACH_CAVEAT, "Metrics marked provisional include days that are still being reported."],
    )


async def time_series(user_id: UUID, campaign_id: UUID, *, metrics: list[str], date_from: date | None,
                      date_to: date | None, platform: str | None, version: str | None, region: str | None,
                      group_by: str) -> v.TimeSeries:
    _check_metrics(metrics, daily=True)
    async with read_session() as s:
        await _campaign(s, user_id, campaign_id)
        loaded = await _load(s, campaign_id)
    start, end = _span(loaded.rows, date_from, date_to)
    rows = _filter(loaded.rows, region, version, platform)
    key: Callable[[SeriesRow], str | None] = {
        "none": lambda r: None, "region": lambda r: r.region_code, "version": lambda r: r.version_label,
        "platform": lambda r: r.platform,
    }[group_by]
    groups: dict[str | None, list[SeriesRow]] = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    daily = {k: daily_totals(groups[k]) for k in groups}
    platforms_in = {k: _platform_index(groups[k], start, end) for k in groups}
    series = []
    for name in metrics:
        d = BY_NAME[name]
        for k in sorted(groups, key=lambda x: x or ""):
            points = [(day, calculate(name, t), is_provisional(name, t)) for day, t in daily[k].items() if start <= day <= end]
            series.append(v.Series(
                metric=name, label=d.label, unit=d.unit,
                region_code=region if group_by != "region" else k, version_label=version if group_by != "version" else k,
                platform=platform if group_by != "platform" else k,  # type: ignore[arg-type]
                platforms=platforms_in[k](name), provisional_from=min((p[0] for p in points if p[2]), default=None),
                points=[v.SeriesPoint(date=day, value=value, provisional=prov) for day, value, prov in points],
            ))
    return v.TimeSeries(
        **_stamp(loaded), date_from=start, date_to=end, group_by=group_by,  # type: ignore[arg-type]
        series=series, caveats=[REACH_CAVEAT] if {"reach", "frequency"} & set(metrics) else [],
    )


async def compare_versions(user_id: UUID, campaign_id: UUID, *, metrics: list[str], date_from: date | None,
                           date_to: date | None, platform: str | None, region: str | None,
                           baseline: str | None) -> v.VersionComparison:
    names = metrics or list(DEFAULT_COMPARE)
    _check_metrics(names)
    async with read_session() as s:
        await _campaign(s, user_id, campaign_id)
        loaded = await _load(s, campaign_id)
    start, end = _span(loaded.rows, date_from, date_to)
    if baseline is not None:
        _filter(loaded.rows, version=baseline)  # a baseline label that is not in the dataset is a 422
    rows = _filter(loaded.rows, region, None, platform)
    caveats = list(sample.SAMPLE_LIMITATIONS[2:]) + ["Versions that ran in only some regions are compared only where they overlap."]
    comparisons = []
    for code in sorted({r.region_code for r in rows}):
        rrows = [r for r in rows if r.region_code == code]
        versions = sorted({r.version_label for r in rrows}, key=lambda x: (min(r.day for r in rrows if r.version_label == x), x))
        if len(versions) < 2:
            continue
        if baseline is not None and baseline not in versions:
            caveats.append(f"{REGION_NAMES.get(code, code)} skipped: the baseline version did not run there.")
            continue
        base = baseline or versions[0]
        results = {
            ver: values_of(names, [r for r in rrows if r.version_label == ver], start, end) for ver in versions
        }
        base_values = {n: results[base][n][0] for n in names}
        columns = []
        for ver in versions:
            vrows = [r for r in rrows if r.version_label == ver]
            metrics_out = []
            for n in names:
                value, prov = results[ver][n]
                delta = None if ver == base or value is None or base_values[n] is None else value - base_values[n]
                pct = None if delta is None or not base_values[n] else delta / base_values[n]
                d = BY_NAME[n]
                metrics_out.append(v.ComparedMetric(
                    metric=n, label=d.label, unit=d.unit, value=value, provisional=prov,
                    delta_vs_baseline=delta, delta_pct_vs_baseline=pct,
                ))
            columns.append(v.VersionColumn(
                version_label=ver, is_baseline=ver == base, first_day=min(r.day for r in vrows),
                last_day=max(r.day for r in vrows), metrics=metrics_out,
            ))
        comparisons.append(v.RegionComparison(
            region_code=code, region_name=REGION_NAMES.get(code, code), baseline_version=base, versions=columns))
    return v.VersionComparison(
        **_stamp(loaded), date_from=start, date_to=end, platform=platform,  # type: ignore[arg-type]
        regions=comparisons, caveats=caveats,
    )


async def freshness(user_id: UUID, campaign_id: UUID) -> v.Freshness:
    async with read_session() as s:
        await _campaign(s, user_id, campaign_id)
        loaded = await _load(s, campaign_id)
    prov = sorted({r.day for r in loaded.rows if r.provisional})
    return v.Freshness(
        **_stamp(loaded), date_from=min(r.day for r in loaded.rows), date_to=max(r.day for r in loaded.rows),
        provisional_from=prov[0] if prov else None, provisional_days=len(prov),
        refresh="None. The sample is static; it is never refreshed from an ad platform.",
        platforms=sorted({r.platform for r in loaded.rows}),
        notes=[
            "Not real time. Real ad platforms report with a delay and some conversions arrive days later, so recent days "
            "are marked provisional.",
            f"The last {len(prov)} days are provisional; conversions on them are under-reported.",
        ],
    )


# --- alert preview ------------------------------------------------------------------------


async def alert_preview(user_id: UUID, campaign_id: UUID, config: AlertConfig) -> v.AlertPreview:
    async with read_session() as s:
        await _campaign(s, user_id, campaign_id)
        loaded = await _load(s, campaign_id)
    result = evaluate(loaded.rows, config)
    first, last = min(r.day for r in loaded.rows), max(r.day for r in loaded.rows)

    def source_path(metric: str, region: str, version: str) -> str:
        query = urlencode({"metric": metric, "region": region, "version": version, "date_from": first.isoformat(),
                           "date_to": last.isoformat()})
        return f"/api/v1/campaigns/{campaign_id}/pulse/timeseries?{query}"

    return v.AlertPreview(
        **_stamp(loaded),
        thresholds=v.AlertThresholds(
            ctr_drop_pct=config.ctr_drop_pct, frequency_threshold=config.frequency_threshold,
            frequency_min_ctr_decline_pct=config.frequency_min_ctr_decline_pct, cost_spike_pct=config.cost_spike_pct,
            min_conversions=config.min_conversions,
        ),
        alerts=[
            v.PulseAlert(
                alert_type=a.alert_type, campaign_id=str(campaign_id), region_code=a.region_code,
                version_label=a.version_label, metric=a.metric, threshold=a.threshold, observed_value=a.observed_value,
                comparison_value=a.comparison_value, comparison=a.comparison, window_from=a.window_from,
                window_to=a.window_to, as_of=a.window_to, suggested_action=a.suggested_action,
                source_path=source_path(a.metric, a.region_code, a.version_label),
                label=sample.SAMPLE_LABEL,
            )
            for a in result.alerts
        ],
        skipped=[v.SkippedRule(region_code=s.region_code, version_label=s.version_label, rule=s.rule, reason=s.reason)
                 for s in result.skipped],
        evaluated=result.evaluated,
        note=(
            "Preview of Alerts (roadmap feature 45). The rules run over the sample dataset only, provisional days are "
            "never used, thresholds are request parameters, and nothing is saved or sent."
        ),
    )
