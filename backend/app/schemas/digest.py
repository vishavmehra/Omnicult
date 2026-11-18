"""Weekly Digest (feature 48): a plain-language summary of one campaign week, generated from stored records.

`DigestContent` is computed entirely by code (counts, deltas, rule-based actions); it never holds model output. The
optional `narrative` is a short model-written summary kept apart from it and always labelled "Model interpretation"; it is
dropped when it contains a number the digest does not hold. A digest is stored, one per campaign and ISO week, and nothing
is sent anywhere: it is read in the app or exported to Markdown or PDF.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.comment_pulse import CommentQuote, SentimentCounts
from app.schemas.common import ApiModel, DataMode

DigestTrigger = Literal["manual", "scheduler"]
SourceWorkspace = Literal["desk", "lens", "studio", "lab", "launch", "pulse", "proof"]
Verdict = Literal["go", "fix", "rethink"]
ExportFormat = Literal["md", "pdf"]


class DigestWeek(ApiModel):
    iso_year: int
    iso_week: int
    label: str = Field(description="For example 2026-W46.")
    start: date = Field(description="Monday, India Standard Time.")
    end: date = Field(description="Sunday, India Standard Time.")
    timezone: Literal["Asia/Kolkata"] = "Asia/Kolkata"


class DigestSource(ApiModel):
    """Where a line comes from, so a reader can open the record behind it."""

    workspace: SourceWorkspace
    view: str | None = Field(description="A view inside the workspace, for example comments.")
    ref: str | None = Field(description="An id inside the workspace, for example a version id.")


# --- what changed --------------------------------------------------------------------------------------------


class DigestChangeCounts(ApiModel):
    creative_versions: int
    content_versions: int
    verdicts: int
    approvals: int
    agent_runs: int
    audience_runs: int
    conflicts_opened: int
    conflicts_resolved: int
    risk_findings: int


class DigestVersionChange(ApiModel):
    id: UUID
    label: str
    region_code: str | None
    actor: Literal["user", "ai"]
    created_at: datetime
    source: DigestSource


class DigestVerdictChange(ApiModel):
    region_code: str
    region_name: str
    version_label: str
    verdict: Verdict
    main_reason: str
    computed_at: datetime
    source: DigestSource


class DigestRunLine(ApiModel):
    kind: str
    status: str
    count: int


class DigestWhatChanged(ApiModel):
    counts: DigestChangeCounts
    versions: list[DigestVersionChange]
    verdicts: list[DigestVerdictChange]
    runs: list[DigestRunLine]
    truncated: bool = Field(description="True when a list holds only the newest records of the week.")


# --- pulse movement and alerts -------------------------------------------------------------------------------


class DigestMetricMove(ApiModel):
    metric: str
    label: str
    unit: Literal["count", "inr", "ratio", "multiple"]
    current: float | None
    previous: float | None
    delta: float | None
    delta_pct: float | None


class DigestSliceMove(ApiModel):
    region_code: str
    region_name: str
    version_label: str
    metrics: list[DigestMetricMove]


class DigestAlertLine(ApiModel):
    alert_type: Literal["ctr_drop", "frequency_fatigue", "cost_spike"]
    region_code: str
    region_name: str
    version_label: str
    headline: str
    suggested_action: str
    source_path: str = Field(description="API path of the time series behind the alert.")


class DigestPulse(ApiModel):
    available: bool
    reason: str | None = Field(description="Why there is no movement to show, when `available` is false.")
    source: str = Field(description="One quiet line naming where the figures come from.")
    window_from: date | None = Field(description="First day of the 7 settled days compared.")
    window_to: date | None
    previous_from: date | None
    previous_to: date | None
    settled_through: date | None = Field(description="The last settled day on or before the end of the week.")
    provisional_days_excluded: int
    slices: list[DigestSliceMove]
    alerts: list[DigestAlertLine]
    alerts_evaluated: int
    alerts_skipped: int


# --- comments ----------------------------------------------------------------------------------------------


class DigestThemeLine(ApiModel):
    id: str
    label: str = Field(description="Model interpretation.")
    summary: str = Field(description="Model interpretation.")
    comments: int
    quote: CommentQuote | None


class DigestFlagged(ApiModel):
    id: UUID
    ref: str
    text: str
    region_code: str
    version_label: str
    language: str
    kind: Literal["planted_claim", "cultural_misstep"]
    label: str
    likes: int
    source: DigestSource


class DigestComments(ApiModel):
    available: bool
    reason: str | None
    source: str
    window_from: date | None
    window_to: date | None
    comments_total: int
    comments_in_window: int
    claim_mentions_in_window: int
    cultural_mentions_in_window: int
    sentiment: SentimentCounts | None = Field(description="Model labels of the comments in the window. Null without a reading.")
    themes: list[DigestThemeLine]
    flagged: list[DigestFlagged]


# --- open items and next actions -----------------------------------------------------------------------------


class DigestConflictItem(ApiModel):
    id: UUID
    region_code: str | None
    region_name: str | None
    reason: str
    status: str
    created_at: datetime
    source: DigestSource


class DigestRiskItem(ApiModel):
    id: UUID
    severity: Literal["low", "medium", "high"]
    category: str
    element_id: str
    observation: str
    blocks_go: bool
    source: DigestSource


class DigestNotReady(ApiModel):
    region_code: str
    region_name: str
    version_label: str
    verdict: Verdict
    main_reason: str
    computed_at: datetime
    source: DigestSource


class DigestOpenItems(ApiModel):
    as_of: datetime = Field(description="Open items are read when the digest is generated, not as they stood on the week's last day.")
    conflicts: list[DigestConflictItem]
    conflicts_total: int
    risk_findings: list[DigestRiskItem]
    risk_findings_total: int
    not_ready: list[DigestNotReady]


class DigestAction(ApiModel):
    priority: Literal[1, 2, 3]
    text: str
    why: str
    rule: str = Field(description="The fixed rule that produced this action.")
    source: DigestSource


class DigestContent(ApiModel):
    schema_version: Literal["digest-v1"] = "digest-v1"
    campaign_name: str
    mode: DataMode
    as_of: datetime
    week: DigestWeek
    what_changed: DigestWhatChanged
    pulse: DigestPulse
    comments: DigestComments
    open_items: DigestOpenItems
    next_actions: list[DigestAction]
    limitations: list[str]


class DigestNarrative(ApiModel):
    """The optional short summary a model wrote from the digest's own numbers. A model interpretation, not a record."""

    text: str
    label: Literal["Model interpretation"] = "Model interpretation"
    provider: str
    model_id: str | None
    prompt_version: str
    estimated_cost_usd: float | None
    created_at: datetime


class Digest(ApiModel):
    id: UUID
    campaign_id: UUID
    revision: int = Field(description="1 on first generation; each regeneration of the same week adds one.")
    mode: DataMode
    trigger: DigestTrigger
    content: DigestContent
    content_sha256: str = Field(description="Hash of `content`: equal records give an equal hash.")
    narrative: DigestNarrative | None
    generated_at: datetime


class DigestCounts(ApiModel):
    changes: int
    alerts: int
    open_items: int
    actions: int


class DigestSummary(ApiModel):
    id: UUID
    week: DigestWeek
    revision: int
    trigger: DigestTrigger
    generated_at: datetime
    has_narrative: bool
    counts: DigestCounts


class DigestList(ApiModel):
    items: list[DigestSummary]
    current_week: DigestWeek = Field(description="The ISO week in progress today (India Standard Time).")
    narrative_available: bool = Field(description="False in a demo project: the model summary is for live projects only.")


class DigestCreate(ApiModel):
    week_of: date | None = Field(default=None, description="Any date inside the week to summarise. Default: the week in progress.")
    regenerate: bool = Field(default=False, description="Replace the stored digest of that week with a fresh one (revision + 1).")


class DigestCreated(ApiModel):
    created: bool = Field(description="False when the week already had a digest and it was returned unchanged.")
    digest: Digest


class SchedulerFailure(ApiModel):
    campaign_id: UUID
    error: str


class SchedulerRun(ApiModel):
    week: DigestWeek
    campaigns: int
    generated: int
    already_existed: int
    skipped_no_data: int
    failed: int
    failures: list[SchedulerFailure]


class SchedulerRequest(ApiModel):
    week_of: date | None = Field(default=None, description="Any date inside the week. Default: the last completed ISO week (India Standard Time).")
