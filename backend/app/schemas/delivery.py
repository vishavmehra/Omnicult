"""Launch Room delivery contract: Review Links (38), Region Plan (39) and Asset Pack (40).

Review Links: an owner or editor shares chosen (version, region) pairs through a link whose secret is shown once and stored
only as a hash. A reviewer needs no account; the link opens a read-only page of exactly those pairs and accepts a decision
or a comment on each. Those decisions are advice to the people who approve (Launch Room approvals stay with signed-in
members); the reviewer's name is typed by them and never verified.

Region Plan: assembled by code from the Campaign Brief, the Moment Calendar, the Readiness Board, the human approvals and
the stakeholder feedback. Nothing in it is written by a model, and nothing in it is stored: it is read fresh each time.

Asset Pack: a ZIP for one region and the approved version, with a manifest that carries provenance and checksums.
"""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.schemas.common import ApiModel, DataMode, Label, Page, ShortText

RegionCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")]
ReviewDecision = Literal["approve", "request_changes", "reject", "comment"]
ReviewerKind = Literal["named", "anonymous"]
LinkStatus = Literal["active", "expired", "revoked"]
ReviewNote = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
ReviewerName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
DECISIONS_NEEDING_COMMENT: frozenset[str] = frozenset({"request_changes", "reject", "comment"})
MAX_ITEMS_PER_LINK = 20

# --- Review Links: owner side ----------------------------------------------------------------------------------------


class ReviewItem(ApiModel):
    """One thing a reviewer may see and decide on: a Creative Studio version of the campaign, for one region."""

    version_id: UUID
    region_code: RegionCode


class ReviewLinkCreate(ApiModel):
    label: Label = Field(description="Names the link in the list (for example the reviewer or the agency).")
    note: ShortText | None = Field(default=None, description="A message from you, shown to the reviewer above the creative.")
    items: Annotated[list[ReviewItem], Field(min_length=1, max_length=MAX_ITEMS_PER_LINK)]
    expires_in_days: Annotated[int, Field(ge=1, le=30)] = 7

    @model_validator(mode="after")
    def _distinct(self) -> "ReviewLinkCreate":
        keys = [(i.version_id, i.region_code) for i in self.items]
        if len(set(keys)) != len(keys):
            raise ValueError("Each version and region pair may appear once.")
        return self


class ReviewItemInfo(ApiModel):
    version_id: UUID
    version_label: str
    region_code: str
    region_name: str
    language: str | None


class ReviewDecisionCounts(ApiModel):
    approve: int
    request_changes: int
    reject: int
    comment: int


class ReviewLinkSummary(ApiModel):
    id: UUID
    campaign_id: UUID
    label: str
    note: str | None
    items: list[ReviewItemInfo]
    token_hint: str = Field(description="The last four characters of the secret, to tell links apart. The secret itself is never stored.")
    status: LinkStatus
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    created_by_name: str | None
    response_count: int
    decisions: ReviewDecisionCounts
    last_response_at: datetime | None
    mode: DataMode


class ReviewLinkCreated(ReviewLinkSummary):
    token: str = Field(description="The secret. Shown only in this response; keep it with the link.")
    review_path: str = Field(description="The page the reviewer opens, relative to the web app: /review/<token>.")


class ReviewLinkPage(Page[ReviewLinkSummary]):
    pass


class ReviewResponseView(ApiModel):
    id: UUID
    link_id: UUID
    link_label: str
    version_id: UUID
    version_label: str
    region_code: str
    region_name: str
    decision: ReviewDecision
    comment: str | None
    reviewer_name: str | None
    reviewer_kind: ReviewerKind
    created_at: datetime
    mode: DataMode


class ReviewResponsePage(Page[ReviewResponseView]):
    pass


# --- Review Links: reviewer side (no account; the secret travels in the Authorization header as "Review <secret>") ---------


class ReviewElement(ApiModel):
    id: str
    kind: str
    text: str = Field(description="Plain text. Rendered as text, never as markup.")
    language: str | None


class ReviewCreative(ApiModel):
    id: UUID
    kind: Literal["image", "video", "audio"]
    label: str
    content_type: str
    width: int | None
    height: int | None


class ReviewItemView(ApiModel):
    version_id: UUID
    version_label: str
    region_code: str
    region_name: str
    language: str | None
    elements: list[ReviewElement]
    creatives: list[ReviewCreative]


class ReviewPage(ApiModel):
    link_label: str
    note: str | None
    campaign_name: str
    brand_name: str
    expires_at: datetime
    items: list[ReviewItemView]
    decisions: list[ReviewDecision]
    identity_note: str = Field(description="What the sender will see about the reviewer.")
    mode: DataMode


class ReviewSubmit(ApiModel):
    version_id: UUID
    region_code: RegionCode
    decision: ReviewDecision
    comment: ReviewNote | None = None
    reviewer_name: ReviewerName | None = Field(default=None, description="Optional. Typed by the reviewer and not verified.")

    @model_validator(mode="after")
    def _comment_when_needed(self) -> "ReviewSubmit":
        if self.decision in DECISIONS_NEEDING_COMMENT and not self.comment:
            raise ValueError("Say what you would change or why, in a comment.")
        return self


class ReviewReceipt(ApiModel):
    id: UUID
    version_id: UUID
    region_code: str
    decision: ReviewDecision
    reviewer_kind: ReviewerKind
    recorded_at: datetime


# --- Region Plan ----------------------------------------------------------------------------------------------------------

PlanStatus = Literal["done", "todo", "warning", "blocked"]
PlanReadyState = Literal["ready", "ready_with_override", "not_ready"]
PlanEventKind = Literal["campaign_start", "campaign_end", "key_moment", "calendar_moment"]
PlanVersionState = Literal["approved", "candidate"]


class PlanCheck(ApiModel):
    id: str
    label: str
    status: PlanStatus
    detail: str


class PlanIssue(ApiModel):
    rule_id: str
    priority: int
    effect: Literal["fix", "rethink"]
    summary: str
    action: str


class PlanEvent(ApiModel):
    date: date
    kind: PlanEventKind
    title: str
    source: str | None = Field(description="Where the date comes from: the brief, or the Moment Calendar claim's source.")
    warning: str | None


class PlanBudget(ApiModel):
    currency: str
    amount: float
    share_of_total: float | None = Field(description="Fraction of the brief's total (0-1); null when the brief has no total.")
    sample: bool = Field(description="The brief marks these numbers as sample placeholders.")


class PlanChannel(ApiModel):
    id: str
    name: str
    format: str | None


class PlanApproval(ApiModel):
    id: UUID
    decision: Literal["approve", "reject", "request_changes"]
    decided_by_name: str | None
    decided_at: datetime
    reason: str
    verdict_at_decision: Literal["go", "fix", "rethink"] | None
    overrides_recommendation: bool


class PlanVersion(ApiModel):
    version_id: UUID
    label: str
    language: str | None
    state: PlanVersionState = Field(description="approved: a person approved it for this region. candidate: the newest version prepared for the region.")


class PlanReadiness(ApiModel):
    verdict: Literal["go", "fix", "rethink"]
    main_reason: str
    next_action: str
    computed_at: datetime
    rule_version: str
    issues: list[PlanIssue]


class PlanFeedback(ApiModel):
    counts: ReviewDecisionCounts
    latest_at: datetime | None


class PlanReady(ApiModel):
    state: PlanReadyState
    reasons: list[str]


class RegionPlanEntry(ApiModel):
    region_code: str
    region_name: str
    role: Literal["origin", "target"]
    languages: list[str]
    budget: PlanBudget | None
    channels: list[PlanChannel]
    version: PlanVersion | None
    approval: PlanApproval | None
    readiness: PlanReadiness | None
    feedback: PlanFeedback
    timeline: list[PlanEvent]
    checklist: list[PlanCheck]
    progress_done: int
    progress_total: int
    warnings: list[str] = Field(description="Date problems, disagreeing sources and stakeholder objections: things to look at before launch.")
    info: list[str] = Field(description="Facts worth knowing that are not problems, such as festivals the sources place in the campaign's months without an exact date.")
    ready: PlanReady
    pack_available: bool = Field(description="An Asset Pack can be built for this region now.")


class PlanWindow(ApiModel):
    start: date
    end: date
    timezone: str


class RegionPlan(ApiModel):
    campaign_id: UUID
    campaign_name: str
    mode: DataMode
    generated_at: datetime
    rule_version: str
    brief_version: int
    window: PlanWindow | None
    currency: str | None
    total_budget: float | None
    budget_sample: bool
    unallocated_budget: float | None
    regions: list[RegionPlanEntry]
    gaps: list[str]
    notes: list[str]
    source_line: str


# --- Asset Pack -------------------------------------------------------------------------------------------------------------

PackRole = Literal["copy_json", "copy_text", "captions", "creative", "brand_kit_file", "brand_kit_data", "checksums", "manifest"]
ChannelMatch = Literal["creative_ref", "format", "none"]


class PackFile(ApiModel):
    path: str
    role: PackRole
    size: int
    sha256: str
    source: str = Field(description="Where the file comes from, in words and ids (an uploaded asset, the version copy, the Brand Kit).")
    asset_id: UUID | None
    rights_confirmed_at: datetime | None
    channel: str = Field(description="The brief channel id the file is named for, or all.")
    also_channels: list[str] = Field(description="Other brief channels this one file serves; it is stored once.")
    channel_match: ChannelMatch = Field(description="How the channel was found: the brief points at the creative, the channel's format names its kind, or neither.")
    width: int | None
    height: int | None


class PackExcluded(ApiModel):
    kind: str
    label: str
    reason: str


class PackApproval(ApiModel):
    id: UUID
    decision: Literal["approve"]
    decided_by_name: str | None
    decided_at: datetime
    reason: str
    verdict_at_decision: Literal["go", "fix", "rethink"] | None
    overrides_recommendation: bool


class PackVersion(ApiModel):
    id: UUID
    label: str
    language: str | None
    region_code: str | None
    actor: Literal["user", "ai"]
    created_at: datetime


class PackChannel(ApiModel):
    id: str
    name: str
    format: str | None
    files: int


class AssetPackManifest(ApiModel):
    schema_version: str
    naming: str
    campaign_id: UUID
    campaign_name: str
    campaign_slug: str
    region_code: str
    region_name: str
    version: PackVersion
    approval: PackApproval
    channels: list[PackChannel]
    files: list[PackFile]
    excluded: list[PackExcluded]
    notes: list[str]
    mode: DataMode
    generated_at: datetime | None = Field(description="Set when the pack is built; null in a preview.")


class AssetPackPreview(ApiModel):
    region_code: str
    region_name: str
    can_build: bool
    blocked_reason: str | None
    approved_versions: list[PackVersion] = Field(description="Versions with a standing approval for this region, newest decision first.")
    manifest: AssetPackManifest | None
    url_ttl_seconds: int


class AssetPackCreate(ApiModel):
    region_code: RegionCode
    version_id: UUID | None = Field(default=None, description="An approved version of the region. Omitted: the newest approved one.")


class AssetPackSummary(ApiModel):
    id: UUID
    campaign_id: UUID
    region_code: str
    region_name: str
    version_id: UUID
    version_label: str
    filename: str
    byte_size: int
    sha256: str = Field(description="SHA-256 of the ZIP file.")
    file_count: int
    status: Literal["active", "expired"]
    expires_at: datetime
    created_at: datetime
    created_by_name: str | None
    mode: DataMode


class AssetPackCreated(AssetPackSummary):
    download_url: str = Field(description="Works without sign-in until it expires. Anyone holding it can download the pack.")
    manifest: AssetPackManifest


class AssetPackPage(Page[AssetPackSummary]):
    pass


class AssetPackDetail(AssetPackSummary):
    manifest: AssetPackManifest
