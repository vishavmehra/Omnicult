"""Proof Vault contract: Proof Report v2 (registered sections), Run History, and Data Health.

Every section of a report carries `kind_labels`: which of the five content kinds it holds and what in it has that kind.
The kinds are the claim kinds of the evidence model (`ClaimKind`): observed, calculated, synthetic, interpretation,
unverified. A section a stream has not wired yet is `missing` with a reason, never empty content that looks complete.
"""

from datetime import date, datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.campaigns import CampaignContent, CampaignType, EvaluationCriteria
from app.schemas.claims import ClaimCategory, ClaimKind, ConfidenceLevel
from app.schemas.common import Anchor, ApiModel, DataMode, Market, Page, StepTrace
from app.schemas.regions import (
    CategoryClaims,
    ConflictResolutionView,
    ConflictStatus,
    EvidenceMeter,
    EvidenceStrength,
    Region,
)
from app.schemas.runs import RunError, RunProgress, RunResultRef, RunStatus, RunType

ContentKind = ClaimKind
CONTENT_KINDS: tuple[str, ...] = ("observed", "calculated", "synthetic", "interpretation", "unverified")
RegionCodeStr = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")]
SectionId = Literal[
    "campaign_brief",
    "target_regions",
    "region_claims",
    "evidence_meter",
    "conflicts",
    "creative_versions",
    "xray_findings",
    "risk_findings",
    "transcreation",
    "audience_results",
    "readiness",
    "approvals",
    "live_performance",
    "limitations",
    "run_history",
]
ReportStatus = Literal["complete", "partial"]


class KindLabel(ApiModel):
    kind: ContentKind
    applies_to: str = Field(description="What in this section has this kind, in plain words.")


# --- run history (feature 52) ---------------------------------------------------------------------------------


class RunInputRef(ApiModel):
    """Where a run's inputs are stored. The inputs themselves are not repeated here."""

    kind: Literal["stored_run_inputs"]
    run_id: UUID
    content_version_id: UUID | None
    study_id: UUID | None
    fields: list[str] = Field(description="Names of the stored input fields.")


class UsageEventView(ApiModel):
    id: UUID
    capability: str
    provider: str
    model: str
    prompt_version: str | None
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    estimated_cost_usd: float = Field(description="Estimate from the registry price table; not a provider invoice.")
    latency_ms: int | None
    status: str
    error_code: str | None
    created_at: datetime


class RunHistoryItem(ApiModel):
    run_id: UUID
    workspace_id: UUID | None
    project_id: UUID
    campaign_id: UUID | None
    study_id: UUID | None
    run_type: RunType
    operation: str = Field(description="Plain-language name of the run type.")
    status: RunStatus
    mode: DataMode
    models: list[str] = Field(description="Models that served the run's calls (usage events and recorded stages).")
    providers: list[str]
    prompt_versions: list[str]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None = Field(description="completed_at minus started_at; null until both exist.")
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None = Field(description="Estimate; null when no cost was recorded for the run.")
    cost_basis: Literal["usage_events", "run_steps", "none"] = Field(
        description="usage_events: metered per call; run_steps: summed from the run's stage traces; none: nothing recorded."
    )
    cost_is_estimate: Literal[True] = Field(description="Costs are estimates from a price table, never provider invoices.")
    actual_cost_usd: float | None = Field(description="Always null: provider invoices are not read by this application.")
    ai_calls: int
    failed_ai_calls: int
    error: RunError | None
    failed_stages: list[str]
    resumable: bool = Field(description="True when the run saved a checkpoint that POST /runs/{id}/resume can continue from.")
    attempt: int


class RunHistoryDetail(RunHistoryItem):
    progress: RunProgress | None
    steps: list[StepTrace]
    usage_events: list[UsageEventView]
    input_ref: RunInputRef
    output_ref: RunResultRef | None


class RunHistoryTotals(ApiModel):
    """Over every run that matches the filters, not only the page."""

    runs: int
    by_status: dict[str, int]
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    estimated_cost_usd: float
    runs_without_cost: int = Field(description="Runs with no recorded cost; the total is therefore a lower bound when above 0.")
    unattributed_events: int = Field(description="Usage events of the campaign that belong to no run (for example search embeddings).")
    unattributed_cost_usd: float
    cost_is_estimate: Literal[True]


class RunHistoryPage(Page[RunHistoryItem]):
    totals: RunHistoryTotals


# --- report section content -----------------------------------------------------------------------------------


class CampaignVersionRef(ApiModel):
    id: UUID
    version_number: int
    content: CampaignContent
    created_at: datetime


class BrandSummary(ApiModel):
    name: str
    description: str | None
    voice: list[str]
    target_audience: str | None
    preferred_terms: list[str]
    prohibited_terms: list[str]
    protected_terms: list[str]


class BriefMarket(Market):
    region_code: str | None = Field(default=None, description="ISO 3166-2 region, when the campaign targets one.")


class CampaignBriefContent(ApiModel):
    campaign_id: UUID
    name: str
    campaign_type: CampaignType
    objective: str | None
    target_markets: list[BriefMarket]
    evaluation_weights: EvaluationCriteria
    current_version: CampaignVersionRef
    version_count: int
    brand: BrandSummary


class TargetRegionsContent(ApiModel):
    source: Literal["campaign", "request"] = Field(description="Where the region codes came from.")
    regions: list[Region]
    unknown_codes: list[str] = Field(description="Requested codes that match no active region; they are not reported on.")


class RegionClaimsBlock(ApiModel):
    region_code: str
    region_name: str
    claim_count: int
    categories: list[CategoryClaims] = Field(description="Every category; an empty one is a visible gap.")


class RegionClaimsContent(ApiModel):
    regions: list[RegionClaimsBlock]
    claim_count: int
    kind_counts: dict[str, int]


class EvidenceMeterContent(ApiModel):
    meters: list[EvidenceMeter]


class ReportConflictSide(ApiModel):
    claim_id: UUID
    value_text: str
    kind: ContentKind
    confidence: ConfidenceLevel
    source_count: int


class ReportConflict(ApiModel):
    id: UUID
    region_code: str | None
    status: ConflictStatus
    reason: str
    current_selection: Literal["a", "b"]
    selection_reason: str
    side_a: ReportConflictSide
    side_b: ReportConflictSide
    decisions: list[ConflictResolutionView] = Field(description="Reviewer decisions, oldest first.")
    created_at: datetime
    updated_at: datetime


class ConflictsContent(ApiModel):
    open: list[ReportConflict] = Field(description="Open, or waiting for a native review.")
    resolved: list[ReportConflict]
    truncated: bool = Field(description="True when a region had more conflicts than the report carries.")


class RunHistoryContent(ApiModel):
    totals: RunHistoryTotals
    runs: list[RunHistoryItem]
    truncated: bool


class LimitationsContent(ApiModel):
    items: list[str]
    not_legal_clearance: str


# Typed shapes for sections that other streams provide. Until a stream registers its provider the section is `missing`.


class CreativeVersionItem(ApiModel):
    version_id: UUID
    label: str
    parent_version_id: UUID | None
    operation: str | None
    actor: Literal["user", "ai"] | None
    created_at: datetime | None
    summary: str
    claim_ids: list[UUID]
    kind: ContentKind


class CreativeVersionsContent(ApiModel):
    versions: list[CreativeVersionItem] = Field(description="Version nodes of the campaign, oldest first.")
    comparison_summary: str | None = Field(description="Code-written comparison of the newest version with the original; null with one version.")
    truncated: bool = Field(default=False, description="True when the campaign has more versions than the report carries.")


XRayField = Literal["on_screen_text", "ad_claim", "cultural_observation", "cultural_interpretation"]


class XRayFinding(ApiModel):
    id: str
    observation: str
    anchor: Anchor | None
    claim_ids: list[UUID]
    confidence: ConfidenceLevel | None = Field(description="Null: no confidence is computed for an X-Ray reading.")
    kind: ContentKind
    field: XRayField = Field(default="cultural_observation", description="Which part of the scene the finding comes from.")
    creative_label: str | None = None


class XRayContent(ApiModel):
    findings: list[XRayFinding]
    creatives: int = Field(default=0, description="Creatives whose current analysis the findings come from.")
    scenes: int = Field(default=0, description="Scenes read.")
    truncated: bool = Field(default=False, description="True when there were more findings than the report carries.")


class TranscreationItem(ApiModel):
    id: str
    region_code: str
    language: str | None
    source_version_id: UUID | None
    result_version_id: UUID | None
    summary: str
    back_translation: str | None
    glossary_issues: list[str]
    claim_ids: list[UUID]
    kind: ContentKind


class TranscreationContent(ApiModel):
    items: list[TranscreationItem]
    truncated: bool = Field(default=False, description="True when there were more lines than the report carries.")


class AudienceResultItem(ApiModel):
    id: str
    method: Literal["quick_read", "audience_study", "ask_the_panel"]
    region_code: str | None
    respondent_count: int = Field(description="Synthetic respondents; never independent human observations.")
    summary: str
    disagreement: str | None
    limitations: list[str]
    kind: Literal["synthetic"] = "synthetic"
    run_id: UUID | None = None
    mode: DataMode = "live"
    model_ids: list[str] = Field(default=[], description="Models that generated the respondents; empty for demo fixtures.")
    created_at: datetime | None = None


class AudienceResultsContent(ApiModel):
    results: list[AudienceResultItem]
    truncated: bool = Field(default=False, description="True when there were more results than the report carries.")


class RiskFindingItem(ApiModel):
    id: str
    severity: Literal["low", "medium", "high"]
    category: str
    description: str
    anchor: Anchor | None
    ad_code_ref: str | None
    status: str | None
    kind: ContentKind
    region_code: str | None = None
    run_id: UUID | None = None
    interpretation: str | None = Field(default=None, description="Why it may matter; a model interpretation unless kind is calculated.")
    suggested_fix: str | None = None
    blocks_go: bool = Field(default=False, description="Computed by risk-rules-v1; counts toward the readiness verdict while unresolved.")
    claim_ids: list[UUID] = []


class RiskFindingsContent(ApiModel):
    findings: list[RiskFindingItem]
    disclaimer: str = Field(description="A Risk Check is an aid to human review, not legal advice.")
    run_ids: list[UUID] = Field(default=[], description="The Risk Check runs the findings come from (newest usable run per region).")


class ReadinessVerdictRef(ApiModel):
    verdict_id: UUID
    region_code: str
    version_id: UUID
    verdict: Literal["go", "fix", "rethink"]
    main_reason: str
    computed_at: datetime


class ReadinessContent(ApiModel):
    verdict: Literal["go", "fix", "rethink"]
    main_reason: str
    highest_priority_issue: str | None
    next_action: str
    open_conflicts: int
    confidence_limitations: list[str]
    rule_version: str
    kind: Literal["calculated"] = "calculated"
    verdict_id: UUID | None = None
    region_code: str | None = None
    version_id: UUID | None = None
    computed_at: datetime | None = None
    other_verdicts: list[ReadinessVerdictRef] = Field(
        default=[], description="The newest verdict of every other region and version, newest first. The headline is the newest overall."
    )
    note: str = Field(default="A recommendation computed by fixed rules. It is not an approval and not a forecast.")


class ApprovalItem(ApiModel):
    id: str
    version_id: UUID | None
    approver_user_id: UUID | None
    role: str | None
    decision: Literal["approved", "changes_requested", "rejected"]
    note: str | None
    decided_at: datetime
    kind: Literal["observed"] = "observed"
    region_code: str | None = None
    approver_name: str | None = None
    verdict_at_decision: Literal["go", "fix", "rethink"] | None = None
    overrides_recommendation: bool = Field(default=False, description="Approved although the recommendation was not Go (or none existed).")


class ApprovalsContent(ApiModel):
    approvals: list[ApprovalItem]


class LivePerformanceItem(ApiModel):
    region_code: str | None
    version_label: str | None = Field(default=None, description="The creative version the figures belong to, as the data source labels it.")
    metric: str
    value: float | str | None
    period: str | None
    provisional: bool
    source: str
    kind: ContentKind


class LivePerformanceContent(ApiModel):
    items: list[LivePerformanceItem]
    sample_data: bool = Field(description="True when the figures are a labelled sample, not a connected account.")
    dataset_version: str | None = None
    note: str = Field(default="")


# --- sections ---------------------------------------------------------------------------------------------------


class SectionBase(ApiModel):
    title: str
    status: Literal["available", "missing"]
    missing_reason: str | None = Field(description="Set exactly when status is missing.")
    kind_labels: list[KindLabel] = Field(description="Empty only for a missing section.")


class CampaignBriefSection(SectionBase):
    id: Literal["campaign_brief"]
    content: CampaignBriefContent | None


class TargetRegionsSection(SectionBase):
    id: Literal["target_regions"]
    content: TargetRegionsContent | None


class RegionClaimsSection(SectionBase):
    id: Literal["region_claims"]
    content: RegionClaimsContent | None


class EvidenceMeterSection(SectionBase):
    id: Literal["evidence_meter"]
    content: EvidenceMeterContent | None


class ConflictsSection(SectionBase):
    id: Literal["conflicts"]
    content: ConflictsContent | None


class CreativeVersionsSection(SectionBase):
    id: Literal["creative_versions"]
    content: CreativeVersionsContent | None


class XRaySection(SectionBase):
    id: Literal["xray_findings"]
    content: XRayContent | None


class RiskFindingsSection(SectionBase):
    id: Literal["risk_findings"]
    content: RiskFindingsContent | None


class TranscreationSection(SectionBase):
    id: Literal["transcreation"]
    content: TranscreationContent | None


class AudienceResultsSection(SectionBase):
    id: Literal["audience_results"]
    content: AudienceResultsContent | None


class ReadinessSection(SectionBase):
    id: Literal["readiness"]
    content: ReadinessContent | None


class ApprovalsSection(SectionBase):
    id: Literal["approvals"]
    content: ApprovalsContent | None


class LivePerformanceSection(SectionBase):
    id: Literal["live_performance"]
    content: LivePerformanceContent | None


class LimitationsSection(SectionBase):
    id: Literal["limitations"]
    content: LimitationsContent | None


class RunHistorySection(SectionBase):
    id: Literal["run_history"]
    content: RunHistoryContent | None


ProofSection = Annotated[
    Union[
        CampaignBriefSection,
        TargetRegionsSection,
        RegionClaimsSection,
        EvidenceMeterSection,
        ConflictsSection,
        CreativeVersionsSection,
        XRaySection,
        RiskFindingsSection,
        TranscreationSection,
        AudienceResultsSection,
        ReadinessSection,
        ApprovalsSection,
        LivePerformanceSection,
        LimitationsSection,
        RunHistorySection,
    ],
    Field(discriminator="id"),
]
SECTION_MODELS: dict[str, type[SectionBase]] = {
    "campaign_brief": CampaignBriefSection,
    "target_regions": TargetRegionsSection,
    "region_claims": RegionClaimsSection,
    "evidence_meter": EvidenceMeterSection,
    "conflicts": ConflictsSection,
    "creative_versions": CreativeVersionsSection,
    "xray_findings": XRaySection,
    "risk_findings": RiskFindingsSection,
    "transcreation": TranscreationSection,
    "audience_results": AudienceResultsSection,
    "readiness": ReadinessSection,
    "approvals": ApprovalsSection,
    "live_performance": LivePerformanceSection,
    "limitations": LimitationsSection,
    "run_history": RunHistorySection,
}


# --- reports ----------------------------------------------------------------------------------------------------


class MissingSection(ApiModel):
    id: SectionId
    title: str
    reason: str


class AssemblyInfo(ApiModel):
    method: Literal["deterministic"]
    model_called: Literal[False] = Field(description="No model is called to assemble a report; sections read stored records.")
    registry_version: str
    section_ids: list[str] = Field(description="Sections in report order.")


class ProofReportCreate(ApiModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    region_codes: Annotated[list[RegionCodeStr], Field(max_length=10)] | None = Field(
        default=None,
        description="Regions to report on. Omitted: the regions the campaign targets. A campaign with none gives a report "
        "whose region sections are missing.",
    )


class ProofReportSummary(ApiModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    workspace_id: UUID | None
    campaign_version_id: UUID | None = Field(description="The campaign content version the report describes.")
    version_number: int = Field(description="Snapshot number for the campaign; a snapshot is never changed.")
    title: str
    status: ReportStatus = Field(description="partial when any section is missing.")
    mode: DataMode
    content_sha256: str = Field(description="Hash of the report's sections: equal inputs give an equal hash.")
    created_at: datetime


class ProofReport(ProofReportSummary):
    schema_version: Literal["proof-report-v2"]
    generated_by: UUID | None
    target_region_codes: list[str]
    sections: list[ProofSection]
    missing_sections: list[MissingSection]
    referenced_claim_ids: list[UUID] = Field(description="Every claim the report shows; each is fetchable and linkable.")
    referenced_conflict_ids: list[UUID]
    kind_legend: list[KindLabel] = Field(description="What each of the five content kinds means.")
    legal_notice: str
    assembly: AssemblyInfo


class ProofReportPage(Page[ProofReportSummary]):
    pass


class ProofSectionInfo(ApiModel):
    id: SectionId
    title: str
    order: int
    wired: bool = Field(description="False while only the placeholder provider is registered (the section reports missing).")


class ProofExportCreate(ApiModel):
    format: Literal["json", "markdown", "pdf"]


class ProofExport(ApiModel):
    id: UUID
    report_id: UUID
    format: Literal["json", "markdown", "pdf"]
    filename: str
    content_type: str
    byte_size: int
    sha256: str
    download_url: str = Field(description="API path with a one-time-use-style token; works without a bearer token until expires_at.")
    expires_at: datetime
    notices: list[str] = Field(description="For example, that Indic text is shown transliterated in the PDF.")


# --- data health (feature 53) ----------------------------------------------------------------------------------

Freshness = Literal["fresh", "aging", "expired", "unknown"]
CacheState = Literal["fixture", "stored_live", "mixed", "none"]


class SourceCallError(ApiModel):
    at: datetime
    code: str | None


class CapabilityCallHealth(ApiModel):
    """One AI capability's recorded calls (chat, vision, transcribe, ...) for a provider source."""

    capability: str
    attempts: int
    errors: int
    last_success_at: datetime | None


class SourceHealth(ApiModel):
    source_type: str
    sources: int = Field(description="Distinct source records behind the workspace's visible claims.")
    claims: int
    live_claims: int
    fixture_claims: int
    cache_state: CacheState = Field(
        description="fixture: demo fixtures only; stored_live: stored copies of live retrievals; mixed: both. "
        "Data Health reads stored copies; it never calls a source."
    )
    last_retrieved_at: datetime | None = Field(description="Newest successful retrieval stored.")
    oldest_retrieved_at: datetime | None
    freshness: Freshness
    fresh_claims: int
    aging_claims: int = Field(description="Not expired, but no observed source is under two years old.")
    expired_claims: int = Field(description="Past their stated expiry; a refresh is due.")
    attempts: int | None = Field(description="Recorded retrieval attempts; null when this source's attempts are not logged.")
    errors: int | None
    last_attempt_at: datetime | None
    last_error: SourceCallError | None
    last_success_at: datetime | None = Field(
        default=None, description="Newest successful recorded call; null when none, or when attempts are not logged."
    )
    capabilities: list[CapabilityCallHealth] = Field(
        default_factory=list, description="Per capability call counts, for sources that are AI providers (vertex_ai)."
    )
    attempts_logged: bool
    region_codes: list[str]
    limitations: list[str]


class RegionCoverage(ApiModel):
    region_code: str
    region_name: str
    strength: EvidenceStrength
    strength_reasons: list[str]
    claims: int
    supported_claims: int
    categories_covered: int
    categories_total: int
    missing_categories: list[ClaimCategory]
    sources: int
    source_types: list[str]
    newest_source_date: date | None
    open_conflicts: int
    stale_claims: int


class FreshnessRules(ApiModel):
    expired_share_for_expired: float
    stale_window_years: int
    notes: list[str]


class DataHealth(ApiModel):
    workspace_id: UUID
    mode: DataMode
    generated_at: datetime
    sources: list[SourceHealth]
    regions: list[RegionCoverage]
    rules: FreshnessRules
    limitations: list[str]
