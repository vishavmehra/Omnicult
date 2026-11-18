"""Live Pulse Tier 3: Predicted vs Actual (44), saved Alerts (45) and Fatigue Watch (47).

Everything is computed in code from stored records: the stored readiness verdicts (which carry the Quick Read counts) and
the Pulse series. Responses built from series data carry the sample stamp from `app.schemas.pulse`. Class names are
prefixed (`Pva`, `AlertRule`, `AlertRecord`, `Fatigue`) so they cannot collide with the other schema modules.
"""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.common import ApiModel, Label
from app.schemas.pulse import SampleStamp, Unit

RegionCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")]
VersionLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Confidence = Literal["Low", "Moderate", "High"]

# --- Predicted vs Actual ---------------------------------------------------------------------------------------------

PvaMetric = Literal["ctr", "view_rate", "completion_100", "roas"]
PvaAgreement = Literal["agree", "near", "differ"]
PvaReading = Literal["mostly_agrees", "mixed", "mostly_disagrees", "too_few_pairs"]
Verdict = Literal["go", "fix", "rethink"]


class PvaQuickRead(ApiModel):
    respondents: int
    positive: int
    negative: int
    understood: int
    relevant: int
    favourable_share: float = Field(description="positive / respondents, from a simulated panel.")


class PvaPredicted(ApiModel):
    """What was stored before the results: the Launch Room verdict and score, and the Quick Read counts it read."""

    verdict_id: UUID
    verdict: Verdict
    overall_score: float | None
    scoring_version: str
    rule_version: str
    computed_at: datetime
    quick_read: PvaQuickRead | None = Field(description="Null when the verdict was computed without a Quick Read.")


class PvaActual(ApiModel):
    metric: PvaMetric
    value: float
    window_from: date
    window_to: date = Field(description="The last settled day: provisional days are never used.")
    settled_days: int
    impressions: float


class PvaCheck(ApiModel):
    """One predictor against the actual metric for one pair. Ranks run from 1 (highest); ties share an average rank."""

    predicted_value: float
    predicted_rank: float
    actual_rank: float
    rank_gap: float
    agreement: PvaAgreement = Field(description="agree: same rank. near: within one rank. differ: two or more ranks apart.")


class PvaPair(ApiModel):
    region_code: str
    region_name: str
    pulse_version: str
    version_id: UUID
    studio_label: str
    predicted: PvaPredicted
    actual: PvaActual
    launch_score: PvaCheck | None = Field(description="Null when the verdict has no overall score.")
    quick_read_favourable: PvaCheck | None = Field(description="Null when the pair has no Quick Read counts.")


class PvaSummary(ApiModel):
    predictor: Literal["launch_score", "quick_read_favourable"]
    label: str
    pairs: int
    agree: int
    near: int
    differ: int
    concordant: int = Field(description="Pairs of pairs ordered the same way by the prediction and by the result.")
    discordant: int
    tied: int
    kendall_tau_b: float | None = Field(description="Rank correlation of the two orderings, computed in code; null below 3 pairs.")
    reading: PvaReading


class PvaExcluded(ApiModel):
    region_code: str
    pulse_version: str
    reason: str


class PvaMethod(ApiModel):
    version: str
    steps: list[str]
    assumptions: list[str]


class PvaResult(SampleStamp):
    metric: PvaMetric
    metric_label: str
    unit: Unit
    method: PvaMethod
    pairs: list[PvaPair]
    summaries: list[PvaSummary]
    excluded: list[PvaExcluded]
    unlinked: int = Field(description="Version and region slots in the series with no Creative Studio link: never compared.")
    fingerprint: str = Field(description="SHA-256 of the inputs and the method version: the same inputs give the same fingerprint.")


class PvaLinkSlot(ApiModel):
    region_code: str
    region_name: str
    pulse_version: str
    version_id: UUID | None
    studio_label: str | None
    verdict: Verdict | None
    overall_score: float | None


class PvaCandidate(ApiModel):
    region_code: str
    version_id: UUID
    studio_label: str
    verdict: Verdict
    overall_score: float | None
    computed_at: datetime


class PvaLinkBoard(ApiModel):
    slots: list[PvaLinkSlot]
    candidates: list[PvaCandidate] = Field(description="Studio versions with a stored verdict, by region: what a slot can be linked to.")


class PvaLinkSet(ApiModel):
    region_code: RegionCode
    pulse_version: VersionLabel
    version_id: UUID | None = Field(description="Null removes the link.")


class PvaSnapshot(ApiModel):
    id: UUID
    metric: PvaMetric
    method_version: str
    fingerprint: str
    dataset_version: str
    pair_count: int
    created_at: datetime
    matches_current: bool = Field(description="True when recomputing today gives the same fingerprint: the stored comparison reproduces.")
    result: PvaResult


class PvaSnapshotCreate(ApiModel):
    metric: PvaMetric = "ctr"


class PvaSnapshotList(ApiModel):
    items: list[PvaSnapshot]


# --- Alerts ------------------------------------------------------------------------------------------------------------

AlertRuleType = Literal["ctr_drop", "frequency_fatigue", "cost_spike", "prediction_miss"]
AlertStatus = Literal["open", "acknowledged", "resolved"]
AlertEventKind = Literal["opened", "acknowledged", "resolved", "reopened"]
AlertTrigger = Literal["refresh", "manual", "scheduler", "user"]
AlertAction = Literal["acknowledge", "resolve", "reopen"]


class AlertRuleParams(ApiModel):
    """Thresholds, with the bounds of the alert preview. Only the fields an alert type reads may be set."""

    ctr_drop_pct: float | None = Field(default=None, gt=0, le=1, description="ctr_drop: CTR this far below the version's first week.")
    frequency_threshold: float | None = Field(default=None, gt=1, le=20, description="frequency_fatigue: frequency at or above this.")
    frequency_min_ctr_decline_pct: float | None = Field(
        default=None, gt=0, le=1, description="frequency_fatigue: and CTR at least this far below the first week.")
    cost_spike_pct: float | None = Field(default=None, gt=0, le=5, description="cost_spike: this far above the region average.")
    min_conversions: int | None = Field(default=None, ge=1, le=10000, description="cost_spike: conversions CPA needs in the week.")
    cost_metric: Literal["cpm", "cpa", "both"] | None = Field(default=None, description="cost_spike: which cost to watch.")
    min_rank_gap: int | None = Field(default=None, ge=1, le=20, description="prediction_miss: ranks between prediction and result.")


class AlertRuleCreate(ApiModel):
    name: Label
    alert_type: AlertRuleType
    region_code: RegionCode | None = Field(default=None, description="Null: every region.")
    version_label: VersionLabel | None = Field(default=None, description="Null: every version.")
    enabled: bool = True
    params: AlertRuleParams = Field(default_factory=AlertRuleParams)


class AlertRuleUpdate(ApiModel):
    name: Label | None = None
    region_code: RegionCode | None = None
    version_label: VersionLabel | None = None
    enabled: bool | None = None
    params: AlertRuleParams | None = None
    clear_region: bool = False
    clear_version: bool = False


class AlertRuleView(ApiModel):
    id: UUID
    name: str
    alert_type: AlertRuleType
    region_code: str | None
    version_label: str | None
    enabled: bool
    params: AlertRuleParams
    open_alerts: int
    created_at: datetime
    updated_at: datetime


class AlertRuleList(ApiModel):
    items: list[AlertRuleView]


class AlertRecordEvent(ApiModel):
    kind: AlertEventKind
    trigger: AlertTrigger
    at: datetime
    actor_user_id: UUID | None = Field(description="The person who acted or ran the evaluation; null for a refresh or a scheduled evaluation.")
    note: str | None
    observed_value: float | None


class AlertRecord(ApiModel):
    id: UUID
    rule_id: UUID | None
    rule_name: str
    alert_type: AlertRuleType
    region_code: str
    region_name: str
    version_label: str
    metric: str
    threshold: float
    observed_value: float
    comparison_value: float
    comparison: str
    window_from: date
    window_to: date
    suggested_action: str
    source_path: str = Field(description="API path of the data behind the alert.")
    status: AlertStatus
    resolution: str | None
    opened_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    events: list[AlertRecordEvent]


class AlertEvaluationView(ApiModel):
    id: UUID
    trigger: Literal["refresh", "manual", "scheduler"]
    period_key: str | None
    dataset_version: str
    evaluated_at: datetime
    rules_evaluated: int
    alerts_found: int
    opened: int
    reopened: int
    resolved: int
    not_evaluated: int


class AlertInbox(SampleStamp):
    items: list[AlertRecord]
    open: int
    acknowledged: int
    resolved: int
    evaluations: list[AlertEvaluationView] = Field(description="The latest evaluations, newest first.")


class AlertTransition(ApiModel):
    action: AlertAction
    note: Note | None = None


class AlertNotRead(ApiModel):
    rule_name: str
    region_code: str
    version_label: str
    reason: str


class AlertEvaluateResult(ApiModel):
    evaluation: AlertEvaluationView
    not_read: list[AlertNotRead] = Field(description="Version and region pairs a rule could not read, with the reason. Not read as 'no alert'.")


class AlertScheduleSummary(ApiModel):
    """The scheduler's call: every campaign with enabled rules, evaluated once per period."""

    period_key: str
    campaigns_with_rules: int
    evaluated: int
    already_evaluated: int
    no_data: int
    failed: int
    alerts_opened: int
    alerts_resolved: int


# --- Fatigue Watch -----------------------------------------------------------------------------------------------------

FatigueStatus = Literal["fatigued", "watch", "healthy", "not_enough_data"]
FatiguePattern = Literal["wearing_out", "static_low", "steady", "unknown"]
FatigueSignalName = Literal["ctr_decay", "view_rate_decay", "frequency", "repeated_exposure"]


class FatigueThresholds(ApiModel):
    ctr_decline_pct: float
    view_rate_decline_pct: float
    frequency_threshold: float


class FatigueSignal(ApiModel):
    name: FatigueSignalName
    label: str
    family: Literal["response", "exposure"]
    available: bool
    triggered: bool
    observed: float | None
    threshold: float | None
    unit: Unit
    detail: str


class FatiguePoint(ApiModel):
    date: date
    value: float | None
    provisional: bool


class FatigueRefresh(ApiModel):
    kind: Literal["studio_version", "pulse_version", "new_variant"]
    label: str
    detail: str
    version_id: UUID | None = Field(description="The Creative Studio version, when the suggestion is one.")
    verdict: Verdict | None
    overall_score: float | None


class FatigueRow(ApiModel):
    region_code: str
    region_name: str
    version_label: str
    status: FatigueStatus
    pattern: FatiguePattern
    signals_triggered: int
    confidence: Confidence
    reason: str = Field(description="Computed from the signals: what fell, what rose, and why that does or does not read as wear-out.")
    window_from: date | None
    window_to: date | None
    signals: list[FatigueSignal]
    ctr: list[FatiguePoint]
    frequency: list[FatiguePoint]
    refresh: list[FatigueRefresh]


class FatigueRegion(ApiModel):
    region_code: str
    region_name: str
    fatigued: int
    watch: int
    healthy: int
    not_enough_data: int
    rows: list[FatigueRow]


class FatigueReport(SampleStamp):
    thresholds: FatigueThresholds
    regions: list[FatigueRegion]
    method: list[str]
