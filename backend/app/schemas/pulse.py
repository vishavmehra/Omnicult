"""Live Pulse: metric catalogue, the labelled sample dataset, the regional dashboard, alert previews, platform status.

Every response built from series data extends `SampleStamp`: `is_sample` is always true and `label` always reads
"Sample data, not from a connected account". Nothing here reads a live ad account; none can be connected in this build.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel

SourceKind = Literal["sample", "test_account", "live"]
Platform = Literal["google_ads", "youtube", "meta", "ga4"]
ConnectionStatus = Literal["not_connected", "test_account", "connected"]
MetricGroup = Literal["delivery", "cost", "response", "video", "outcome", "site", "conversation", "brand", "creative_health"]
Unit = Literal["count", "inr", "ratio", "multiple"]
GroupBy = Literal["none", "region", "version", "platform"]
AlertType = Literal["ctr_drop", "frequency_fatigue", "cost_spike"]


class SampleStamp(ApiModel):
    """Carried by every response that holds series data, so a chart can never lose its label."""

    is_sample: Literal[True] = True
    label: str = Field(description="Always 'Sample data, not from a connected account'.")
    source_kind: Literal["sample"] = "sample"
    dataset_version: str
    last_updated_at: datetime = Field(description="When the sample was generated (a fixed instant), not when it was loaded.")
    limitations: list[str]


# --- catalogue ----------------------------------------------------------------------------


class MetricDefinition(ApiModel):
    name: str
    label: str
    unit: Unit
    group: MetricGroup
    kind: Literal["base", "calculated"]
    formula: str | None = Field(description="Calculated metrics only, in terms of base metric names. Computed in code.")
    description: str
    platforms: list[str] = Field(description="Where the metric comes from in the product plan; not a claim that it is connected.")
    in_sample: bool = Field(description="False: defined for the product, but the sample dataset has no values for it.")
    aggregation: Literal["sum", "cumulative", "ratio", "window_change"]


class MetricCatalogue(ApiModel):
    items: list[MetricDefinition]
    notes: list[str]


# --- dataset ------------------------------------------------------------------------------


class DatasetStatus(ApiModel):
    loaded: bool
    is_sample: Literal[True] = True
    label: str
    source_kind: Literal["sample"] = "sample"
    dataset_version: str
    last_updated_at: datetime | None
    row_count: int
    date_from: date | None
    date_to: date | None
    provisional_from: date | None
    regions: list[str]
    versions: list[str]
    platforms: list[str]
    note: str


# --- dashboard ----------------------------------------------------------------------------


class MetricValue(ApiModel):
    """One number with everything a reader needs to judge it (handoff 43: source, platform, region, range, time, status)."""

    metric: str
    label: str
    unit: Unit
    group: MetricGroup
    value: float | None = Field(description="Null when it cannot be calculated (for example CTR with no impressions).")
    provisional: bool
    source_kind: Literal["sample"] = "sample"
    platforms: list[str]
    region_code: str
    version_label: str | None
    date_from: date
    date_to: date
    last_updated_at: datetime


class GroupCard(ApiModel):
    group: MetricGroup
    metrics: list[MetricValue]


class RegionCard(ApiModel):
    region_code: str
    region_name: str
    versions: list[str]
    groups: list[GroupCard]


class RegionSummary(SampleStamp):
    date_from: date
    date_to: date
    platform: Platform | None
    version_label: str | None
    regions: list[RegionCard]
    caveats: list[str]


class SeriesPoint(ApiModel):
    date: date
    value: float | None
    provisional: bool


class Series(ApiModel):
    metric: str
    label: str
    unit: Unit
    region_code: str | None
    version_label: str | None
    platform: Platform | None
    platforms: list[str]
    source_kind: Literal["sample"] = "sample"
    provisional_from: date | None
    points: list[SeriesPoint]


class TimeSeries(SampleStamp):
    date_from: date
    date_to: date
    group_by: GroupBy
    series: list[Series]
    caveats: list[str]


class ComparedMetric(ApiModel):
    metric: str
    label: str
    unit: Unit
    value: float | None
    provisional: bool
    delta_vs_baseline: float | None = Field(description="Version value minus the baseline version's value; null for the baseline itself.")
    delta_pct_vs_baseline: float | None = Field(description="delta / baseline value; null when the baseline is zero or absent.")


class VersionColumn(ApiModel):
    version_label: str
    is_baseline: bool
    first_day: date
    last_day: date
    metrics: list[ComparedMetric]


class RegionComparison(ApiModel):
    region_code: str
    region_name: str
    baseline_version: str
    versions: list[VersionColumn]


class VersionComparison(SampleStamp):
    date_from: date
    date_to: date
    platform: Platform | None
    regions: list[RegionComparison]
    caveats: list[str]


class Freshness(SampleStamp):
    date_from: date
    date_to: date
    provisional_from: date | None
    provisional_days: int
    is_real_time: Literal[False] = False
    refresh: str
    platforms: list[str]
    notes: list[str]


# --- alerts (preview of feature 45) -------------------------------------------------------


class AlertThresholds(ApiModel):
    ctr_drop_pct: float
    frequency_threshold: float
    frequency_min_ctr_decline_pct: float
    cost_spike_pct: float
    min_conversions: int


class PulseAlert(ApiModel):
    alert_type: AlertType
    campaign_id: str
    region_code: str
    version_label: str
    metric: str
    threshold: float
    observed_value: float
    comparison_value: float
    comparison: str
    window_from: date
    window_to: date
    as_of: date
    suggested_action: str
    source_path: str = Field(description="API path of the time series behind the alert.")
    is_sample: Literal[True] = True
    label: str


class SkippedRule(ApiModel):
    region_code: str
    version_label: str
    rule: str
    reason: str


class AlertPreview(SampleStamp):
    thresholds: AlertThresholds
    alerts: list[PulseAlert]
    skipped: list[SkippedRule]
    evaluated: int = Field(description="Version-region pairs with enough settled data to be compared.")
    note: str


# --- predicted vs actual and platform status ----------------------------------------------


class PredictedVsActual(ApiModel):
    status: Literal["not_available"] = "not_available"
    reason: str
    real_result_rows: int = Field(description="Rows of real (test account or live) results stored for the campaign.")
    calibration_claimed: Literal[False] = False
    requirements: list[str]


class PlatformConnectionStatus(ApiModel):
    platform: Platform
    label: str
    status: ConnectionStatus
    last_sync_at: datetime | None
    scopes: list[str]
    note: str


class PlatformConnectionList(ApiModel):
    items: list[PlatformConnectionStatus]
    connect_available: Literal[False] = False
    note: str
