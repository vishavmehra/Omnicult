"""Creative Studio, Tier 3 contract: Format Fit (24), Claim Guard (27) and Script Check (28).

All three read a version of the campaign's version tree and write nothing except what a person asks for: Format Fit makes
a new asset when a plan is applied, Claim Guard stores a check and a person's review decisions. Verdicts, severities and
statuses are computed by code (`app.studio`); a model only ever proposes a claim for Claim Guard's optional second pass, and
code verifies its quote. Nothing here is legal clearance: findings are warnings for human review.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.assets import Asset
from app.schemas.audience import AdCodeRef, AppliedRuleView
from app.schemas.common import Anchor, ApiModel, Page
from app.schemas.versions import ElementKind

# --- Format Fit -----------------------------------------------------------------------------------------------------

FitStrategy = Literal["crop", "pad", "native"]
FitVerdict = Literal["clean", "review", "conflict"]
HexColour = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
FormatId = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,2}x[0-9]{1,2}$")]


class FormatFitSafeZone(ApiModel):
    top: float = Field(description="Share of the frame's height the platform interface usually covers at the top.")
    right: float
    bottom: float
    left: float
    basis: str = Field(description="What the numbers are: working defaults, not a platform's own specification.")


class FormatFitFormat(ApiModel):
    id: FormatId
    name: str
    ratio: str
    width: int
    height: int
    used_for: str
    safe_zone: FormatFitSafeZone


class FormatFitChannel(ApiModel):
    """A channel of the Campaign Brief and the format it runs in (matched by its id, else by a ratio in its format text)."""

    id: str
    name: str
    format_text: str | None
    format_id: FormatId | None = Field(description="Null when the channel's format is not one of ours; it is then not planned for.")


class FormatFitCatalogue(ApiModel):
    formats: list[FormatFitFormat]
    channels: list[FormatFitChannel]
    tool_version: str


class FormatFitPlanRequest(ApiModel):
    creative_id: UUID
    version_id: UUID
    format_ids: list[FormatId] | None = Field(default=None, max_length=8, description="Default: every format.")
    background: HexColour | None = Field(default=None, description="Bar colour for a pad; default is the picture's own edge colour.")


class FormatFitRect(ApiModel):
    x: float
    y: float
    width: float
    height: float


class FormatFitElement(ApiModel):
    element_id: str
    kind: ElementKind
    locked: bool
    text: str | None
    bbox_source: list[float] | None = Field(description="Normalised [x, y, w, h] of the source picture; null when the element has no position.")
    bbox_output: list[float] | None = Field(description="Normalised [x, y, w, h] in the output frame, clipped to the frame; null when unknown.")
    visible_share: float = Field(description="Share of the element's area that stays inside the output frame.")
    placement: Literal["kept", "cut", "outside", "unknown"]
    in_safe_zone: bool | None
    safe_overflow: list[Literal["top", "right", "bottom", "left"]]
    text_height_px: float | None = Field(description="Estimated height of one line of this text in the output, in pixels.")
    min_text_px: float | None
    anchor: Anchor


class FormatFitIssue(ApiModel):
    code: str
    severity: Literal["conflict", "review", "info"]
    message: str
    element_id: str | None


class FormatFitStrategyPlan(ApiModel):
    strategy: FitStrategy
    verdict: FitVerdict = Field(description="Computed in code: conflict (a locked or text element is cut), review (safe zone, small text, enlargement) or clean.")
    window: FormatFitRect = Field(description="The part of the source that is shown, in source pixels.")
    place: FormatFitRect = Field(description="Where it lands in the output frame, in output pixels.")
    scale: float
    retained_share: float
    background: HexColour | None
    elements: list[FormatFitElement]
    issues: list[FormatFitIssue]
    applicable: bool = Field(description="False when a locked element would be cut: such a plan cannot be applied.")


class FormatFitPlan(ApiModel):
    format: FormatFitFormat
    strategies: list[FormatFitStrategyPlan]
    recommended: FitStrategy | None = Field(description="The plan with the fewest conflicts, then review items. A suggestion; the person chooses.")


class FormatFitSource(ApiModel):
    asset_id: UUID
    kind: Literal["image", "video", "audio"]
    width: int | None
    height: int | None
    sha256: str
    label: str


class FormatFitSegment(ApiModel):
    scene_id: str
    position: int
    start_ms: int
    end_ms: int
    trimmed: bool
    reasons: list[str]


class FormatFitDropped(ApiModel):
    scene_id: str
    position: int
    summary: str | None
    duration_ms: int


class FormatFitCutdown(ApiModel):
    target_ms: int
    duration_ms: int
    score: int
    segments: list[FormatFitSegment]
    dropped: list[FormatFitDropped]
    notes: list[str]


class FormatFitPlans(ApiModel):
    creative_id: UUID
    version_id: UUID
    source: FormatFitSource
    locked_element_ids: list[str]
    plans: list[FormatFitPlan] = Field(description="One per format for a picture; for a video, only the format it already has.")
    cutdowns: list[FormatFitCutdown] = Field(description="Video only: scene selections for shorter lengths, from the X-Ray scene timings.")
    notes: list[str]
    tool_version: str


class FormatFitApply(ApiModel):
    creative_id: UUID
    version_id: UUID
    format_id: FormatId
    strategy: FitStrategy
    background: HexColour | None = None
    acknowledge_issues: bool = Field(
        default=False, description="Needed when the plan has conflicts other than a cut locked element (which is always refused)."
    )


class FormatFitOutput(ApiModel):
    id: UUID
    campaign_id: UUID
    version_id: UUID
    creative_id: UUID
    format_id: FormatId
    strategy: FitStrategy
    asset: Asset
    source_asset_id: UUID
    verdict: FitVerdict
    issues: list[FormatFitIssue]
    window: FormatFitRect
    place: FormatFitRect
    scale: float
    background: HexColour | None
    tool_version: str
    created_by: UUID | None
    created_at: datetime


class FormatFitOutputPage(Page[FormatFitOutput]):
    pass


# --- Script Check -----------------------------------------------------------------------------------------------------

ScriptStatus = Literal["ok", "review", "problem"]
ScriptSeverity = Literal["problem", "review", "info"]


class ScriptReportIssue(ApiModel):
    code: str
    severity: ScriptSeverity
    message: str
    start: int | None = Field(description="Character offset of the span in the element's text; null when the issue is about the whole text.")
    end: int | None
    excerpt: str | None
    anchor: Anchor


class ScriptReportTerm(ApiModel):
    """A Brand Glossary term found in the text, with its pronunciation guidance."""

    term: str
    form: str = Field(description="The characters as they appear in the text.")
    pronunciation: str | None
    protected: bool
    start: int
    end: int


class ScriptReportBack(ApiModel):
    """The English back-translation a transcreation stored for this element, and whether it still describes the text."""

    state: Literal["current", "edited"] = Field(description="edited: the text was changed after the transcreation, so the back-translation no longer applies.")
    text: str
    clean: bool | None = Field(description="Whether the protected and prohibited term checks pass on it; null when it no longer applies.")
    operation_id: UUID


class ScriptReportElement(ApiModel):
    element_id: str
    kind: ElementKind
    text: str
    language: str | None
    declared_script: str | None
    expected_script: str | None
    dominant_script: str | None
    shares: dict[str, float] = Field(description="Share of the letters in each script, after brand terms are set aside.")
    status: ScriptStatus
    native_review_recommended: bool
    issues: list[ScriptReportIssue]
    terms: list[ScriptReportTerm]
    back_translation: ScriptReportBack | None
    anchor: Anchor


class ScriptReportSkipped(ApiModel):
    element_id: str
    kind: ElementKind
    reason: str


class ScriptReportCounts(ApiModel):
    ok: int
    review: int
    problem: int
    issues: int


class ScriptReport(ApiModel):
    version_id: UUID
    campaign_id: UUID
    region_code: str | None
    language: str | None
    check_version: str
    shaping_engine: Literal["raqm", "basic"] = Field(description="The server's text-shaping engine: raqm shapes Indic scripts for rendering.")
    glossary_terms: int
    counts: ScriptReportCounts
    elements: list[ScriptReportElement]
    skipped: list[ScriptReportSkipped]
    limitations: list[str]


# --- Claim Guard ------------------------------------------------------------------------------------------------------

ClaimKind = Literal["superiority", "comparative", "price", "health", "guarantee", "financial"]
ClaimSeverity = Literal["low", "medium", "high"]
ClaimConfidence = Literal["low", "moderate", "high"]
ClaimSource = Literal["rule", "model"]
ReviewDecision = Literal["substantiated", "revise", "accepted", "not_a_claim"]


class ClaimGuardPolicy(ApiModel):
    status: Literal["forbidden", "not_listed", "no_policy"]
    rule: str | None = Field(description="The policy line or term that applies, when one does.")
    source: str | None


class ClaimGuardEvidenceItem(ApiModel):
    source: Literal["campaign_brief", "region_claim"]
    claim_id: UUID | None
    statement: str
    kind: str | None = Field(description="The evidence claim's kind (observed, calculated, ...), when it is a region claim.")
    confidence: str | None
    note: str


class ClaimGuardEvidence(ApiModel):
    status: Literal["found", "mismatch", "none"] = Field(
        description="found: related evidence is on file (a person decides whether it covers this wording); mismatch: a price differs from the brief; none."
    )
    items: list[ClaimGuardEvidenceItem]


class ClaimGuardBasis(ApiModel):
    stated: bool
    wording: str | None
    sourced: bool = Field(description="Whether a source, sample size or date is shown near the named basis.")


class ClaimGuardReview(ApiModel):
    finding_key: str
    decision: ReviewDecision
    note: str | None
    reviewed_by: UUID | None
    reviewed_at: datetime


class ClaimGuardFinding(ApiModel):
    key: str = Field(description="Stable identity of the finding in its version; reviews are kept against it.")
    element_id: str
    element_kind: ElementKind
    kind: ClaimKind
    source: ClaimSource = Field(description="rule: a wording pattern matched in code. model: a second-pass model reading whose quote code verified (a model interpretation).")
    rule_id: str | None
    quote: str = Field(description="The matched wording, exactly as it is in the element.")
    start: int
    end: int
    phrase: str = Field(description="The clause the wording sits in.")
    anchor: Anchor
    severity: ClaimSeverity
    blocks_go: bool
    confidence: ClaimConfidence = Field(description="How sure the match is that this wording is a claim of this kind. A rule certainty, not a probability; a model reading is Low.")
    severity_rules: list[AppliedRuleView]
    policy: ClaimGuardPolicy
    evidence: ClaimGuardEvidence
    basis: ClaimGuardBasis
    ad_codes: list[AdCodeRef]
    explanation: str
    limitations: list[str]
    review: ClaimGuardReview | None = Field(description="The person's decision about this finding, when there is one. Every finding needs one before approval.")


class ClaimGuardCounts(ApiModel):
    total: int
    high: int
    medium: int
    low: int
    reviewed: int
    unreviewed: int
    blocks_go: int
    by_kind: dict[str, int]
    review_complete: bool = Field(description="True when every finding has a decision. Not clearance: it only means a person looked at each one.")


class ClaimGuardModelRun(ApiModel):
    provider: str | None
    model_id: str | None
    prompt_version: str
    estimated_cost_usd: float | None
    proposed: int
    kept: int
    dropped: int = Field(description="Proposals removed in code: a quote not found in its element, an unknown element or kind, or a repeat of a rule finding.")
    error: str | None


class ClaimGuardPolicyView(ApiModel):
    forbidden: list[str]
    allowed: list[str]
    prohibited_terms: list[str]


class ClaimGuardCheckSummary(ApiModel):
    id: UUID
    campaign_id: UUID
    version_id: UUID
    region_code: str | None
    language: str | None
    mode: Literal["rules", "rules_model"]
    rules_version: str
    counts: ClaimGuardCounts
    created_by: UUID | None
    created_at: datetime


class ClaimGuardCheck(ClaimGuardCheckSummary):
    findings: list[ClaimGuardFinding]
    texts_checked: int
    policy: ClaimGuardPolicyView
    model: ClaimGuardModelRun | None
    limitations: list[str]


class ClaimGuardCheckPage(Page[ClaimGuardCheckSummary]):
    pass


class ClaimGuardRun(ApiModel):
    version_id: UUID
    include_model_pass: bool = Field(default=False, description="Add a second pass in which a model proposes implied claims. Its quotes are verified in code and tagged as model interpretation.")


class ClaimGuardReviewRequest(ApiModel):
    version_id: UUID
    finding_key: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
    decision: ReviewDecision
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None



