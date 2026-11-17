"""Live Pulse: the regional dashboard on the labelled sample dataset (no ad account can be connected in this build)."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser
from app.schemas import pulse as v
from app.services import pulse
from app.services.pulse_alerts import AlertConfig

router = APIRouter(prefix="/campaigns/{campaign_id}/pulse", tags=["pulse"])

DateFrom = Annotated[date | None, Query(description="First day, inclusive. Default: first day of the data.")]
DateTo = Annotated[date | None, Query(description="Last day, inclusive. Default: last day of the data.")]
PlatformFilter = Annotated[v.Platform | None, Query(description="Only rows of this platform.")]
RegionFilter = Annotated[
    str | None, Query(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$", description="ISO 3166-2 code, for example IN-TN.")
]
VersionFilter = Annotated[str | None, Query(max_length=120, description="A version label exactly as the dataset lists it.")]


@router.get("/metrics", response_model=v.MetricCatalogue)
async def get_metric_catalogue(campaign_id: UUID, user: CurrentUser) -> v.MetricCatalogue:
    """Metric definitions: unit, group, source platforms and, for calculated metrics, the formula (computed in code)."""
    return await pulse.metric_catalogue(user.id, campaign_id)


@router.get("/connections", response_model=v.PlatformConnectionList)
async def list_platform_connections(campaign_id: UUID, user: CurrentUser) -> v.PlatformConnectionList:
    """Read-only. Every platform is `not_connected`: connecting accounts is roadmap."""
    return await pulse.connections(user.id, campaign_id)


@router.get("/sample-dataset", response_model=v.DatasetStatus)
async def get_sample_dataset_status(campaign_id: UUID, user: CurrentUser) -> v.DatasetStatus:
    return await pulse.dataset_status(user.id, campaign_id)


@router.post("/sample-dataset", response_model=v.DatasetStatus)
async def load_sample_dataset(campaign_id: UUID, user: CurrentUser) -> v.DatasetStatus:
    """Explicit action: load, or reload, the deterministic sample dataset for this campaign (owner or editor).
    The data is generated and labelled as such everywhere; reloading replaces it with identical rows."""
    return await pulse.load_sample(user.id, campaign_id)


@router.get("/freshness", response_model=v.Freshness)
async def get_freshness(campaign_id: UUID, user: CurrentUser) -> v.Freshness:
    """Last updated time, the provisional window, and the statement that this is not real time."""
    return await pulse.freshness(user.id, campaign_id)


@router.get("/summary", response_model=v.RegionSummary)
async def get_region_summary(
    campaign_id: UUID, user: CurrentUser, date_from: DateFrom = None, date_to: DateTo = None,
    platform: PlatformFilter = None, version: VersionFilter = None, region: RegionFilter = None,
) -> v.RegionSummary:
    """Per-region cards: delivery, cost, response, video, outcome and creative health, each value with its platforms,
    date range, last updated time and provisional status."""
    return await pulse.region_summary(
        user.id, campaign_id, date_from=date_from, date_to=date_to, platform=platform, version=version, region=region)


@router.get("/timeseries", response_model=v.TimeSeries)
async def get_time_series(
    campaign_id: UUID, user: CurrentUser,
    metric: Annotated[list[str], Query(min_length=1, max_length=6, description="Repeat for several metrics.")],
    date_from: DateFrom = None, date_to: DateTo = None, platform: PlatformFilter = None, version: VersionFilter = None,
    region: RegionFilter = None, group_by: Annotated[v.GroupBy, Query()] = "none",
) -> v.TimeSeries:
    """Daily series per metric, optionally split by region, version or platform. Provisional days are flagged."""
    return await pulse.time_series(
        user.id, campaign_id, metrics=metric, date_from=date_from, date_to=date_to, platform=platform,
        version=version, region=region, group_by=group_by)


@router.get("/versions/compare", response_model=v.VersionComparison)
async def compare_versions(
    campaign_id: UUID, user: CurrentUser, metric: Annotated[list[str] | None, Query(max_length=10)] = None,
    date_from: DateFrom = None, date_to: DateTo = None, platform: PlatformFilter = None, region: RegionFilter = None,
    baseline: Annotated[str | None, Query(max_length=120, description="Default: the version that started first.")] = None,
) -> v.VersionComparison:
    """Versions side by side within each region they share, with differences against a baseline version."""
    return await pulse.compare_versions(
        user.id, campaign_id, metrics=metric or [], date_from=date_from, date_to=date_to, platform=platform,
        region=region, baseline=baseline)


@router.get("/alerts", response_model=v.AlertPreview)
async def get_alert_preview(
    campaign_id: UUID, user: CurrentUser,
    ctr_drop_pct: Annotated[float, Query(gt=0, le=1)] = 0.20,
    frequency_threshold: Annotated[float, Query(gt=1, le=20)] = 2.5,
    frequency_min_ctr_decline_pct: Annotated[float, Query(gt=0, le=1)] = 0.10,
    cost_spike_pct: Annotated[float, Query(gt=0, le=5)] = 0.30,
    min_conversions: Annotated[int, Query(ge=1, le=10000)] = 30,
) -> v.AlertPreview:
    """Deterministic alert rules over the sample dataset, labelled as a sample preview of Alerts (roadmap). Nothing is saved."""
    return await pulse.alert_preview(user.id, campaign_id, AlertConfig(
        ctr_drop_pct=ctr_drop_pct, frequency_threshold=frequency_threshold,
        frequency_min_ctr_decline_pct=frequency_min_ctr_decline_pct, cost_spike_pct=cost_spike_pct,
        min_conversions=min_conversions))


@router.get("/predicted-vs-actual", response_model=v.PredictedVsActual)
async def get_predicted_vs_actual(campaign_id: UUID, user: CurrentUser) -> v.PredictedVsActual:
    """`not_available` until real results exist. Never returns a fabricated calibration."""
    return await pulse.predicted_vs_actual(user.id, campaign_id)
