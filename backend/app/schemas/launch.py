"""Launch Room contracts: Compare and Score `mvp-2`, the Readiness Board, and approvals (Omnicult features 36 and 37).

Observations are typed inputs produced elsewhere (Quick Read, Risk Check, transcreation checks, the Evidence Meter,
evidence conflicts). A model may supply observations; it never supplies a score or a verdict. Scores and verdicts are
computed by the deterministic rules in `app.analytics.scoring_v2` and `app.analytics.readiness`, and every response says
which rules, inputs and versions produced it. Quick Read inputs are synthetic and are labelled so.
"""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.schemas.common import ApiModel, DataMode, Label, MediumText, Page, RiskSeverity, ShortText

RegionCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")]
ShortId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]

ScoringVersion = Literal["mvp-2"]
ScoreDimension = Literal[
    "message_clarity", "brand_fidelity", "cultural_relevance", "sensitivity_risk", "objective_consistency"
]
Verdict = Literal["go", "fix", "rethink"]
FindingStatus = Literal["open", "resolved", "dismissed"]
ObjectiveStatus = Literal["met", "partly_met", "not_met"]
MeterStrength = Literal["weak", "partial", "solid"]
ConflictState = Literal["open", "review_requested", "resolved"]
ApprovalDecision = Literal["approve", "reject", "request_changes"]


# --- typed observations (inputs) ------------------------------------------------------------------


class Anchor(ApiModel):
    """Where in the creative a finding applies. Normalised 0-1 bbox [x, y, w, h]."""

    scene_id: str | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    bbox: Annotated[list[float], Field(min_length=4, max_length=4)] | None = None


class Provenance(ApiModel):
    """Where the observations came from. Differences between versions are disclosed, never hidden."""

    model_id: ShortId | None = Field(default=None, description="Model that produced the observations, when AI was involved.")
    prompt_version: ShortId | None = None
    criteria_version: ShortId | None = Field(default=None, description="Panel or evaluation criteria the observations used.")
    evidence_snapshot: ShortId | None = Field(default=None, description="Identifier of the evidence the observations drew on.")
    run_ids: Annotated[list[UUID], Field(max_length=10)] = []


class QuickReadObservation(ApiModel):
    """Counts from a small SYNTHETIC panel. Respondents are not real people and are not independent observations."""

    respondents: int = Field(ge=1, le=2000)
    understood: int = Field(ge=0, description="Respondents who restated the intended message correctly.")
    confused: int = Field(ge=0)
    positive: int = Field(ge=0)
    negative: int = Field(ge=0)
    relevant: int = Field(ge=0, description="Respondents who judged the language and references relevant to the region.")
    concerned: int = Field(ge=0, description="Respondents who raised a regional concern.")
    synthetic: Literal[True] = True
    evidence_ids: Annotated[list[UUID], Field(max_length=20)] = []

    @model_validator(mode="after")
    def _counts_fit_the_panel(self) -> Self:
        n = self.respondents
        if max(self.understood, self.confused, self.positive, self.negative, self.relevant, self.concerned) > n:
            raise ValueError("A count cannot exceed the number of respondents.")
        if self.understood + self.confused > n:
            raise ValueError("understood plus confused cannot exceed the number of respondents.")
        if self.positive + self.negative > n:
            raise ValueError("positive plus negative cannot exceed the number of respondents.")
        return self


class RiskFindingInput(ApiModel):
    id: ShortId
    severity: RiskSeverity
    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] = "other"
    status: FindingStatus = "open"
    blocks_go: bool = Field(default=False, description="While unresolved, this finding rules out a Go verdict.")
    source: Literal["deterministic_check", "model_assessment"] = "model_assessment"
    summary: ShortText
    claim_ids: Annotated[list[UUID], Field(max_length=20)] = []
    anchor: Anchor | None = None


class RiskCheckObservation(ApiModel):
    """A completed Risk Check. An empty list means it ran and found nothing; it is not proof that no risk exists."""

    findings: Annotated[list[RiskFindingInput], Field(max_length=100)] = []
    run_id: UUID | None = None

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        if len({f.id for f in self.findings}) != len(self.findings):
            raise ValueError("Finding ids must be unique.")
        return self


class TranscreationObservation(ApiModel):
    """Code-checked results for the regional copy: Brand Glossary compliance, back-translation and script."""

    lines_checked: int = Field(ge=1, le=500)
    glossary_violation_lines: int = Field(ge=0, description="Lines that lose a protected term or contain a prohibited one.")
    prohibited_term_lines: int = Field(default=0, ge=0, description="Subset of the violation lines with a prohibited term.")
    meaning_preserved_lines: int | None = Field(
        default=None, ge=0, description="Lines whose English back-translation kept the intended meaning; null if not checked."
    )
    script_error_lines: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _counts_fit_the_lines(self) -> Self:
        n = self.lines_checked
        if self.glossary_violation_lines > n or self.script_error_lines > n or (self.meaning_preserved_lines or 0) > n:
            raise ValueError("A count cannot exceed lines_checked.")
        if self.prohibited_term_lines > self.glossary_violation_lines:
            raise ValueError("prohibited_term_lines cannot exceed glossary_violation_lines.")
        return self


class ReferenceObservation(ApiModel):
    """Cultural references found in the creative and how many are backed by evidence claims."""

    references_checked: int = Field(ge=1, le=200)
    references_supported: int = Field(ge=0)

    @model_validator(mode="after")
    def _supported_fits(self) -> Self:
        if self.references_supported > self.references_checked:
            raise ValueError("references_supported cannot exceed references_checked.")
        return self


class ObjectiveCheck(ApiModel):
    """Whether the creative serves one campaign objective (a categorical observation; the score is computed in code)."""

    id: ShortId
    statement: ShortText
    status: ObjectiveStatus
    primary: bool = False


class EvidenceMeterObservation(ApiModel):
    """The Evidence Meter reading for the region (see GET /workspaces/{id}/regions/{code}/evidence-meter)."""

    strength: MeterStrength
    claims: int = Field(ge=0)
    supported_claims: int = Field(ge=0)
    open_conflicts: int = Field(default=0, ge=0)
    stale_claims: int = Field(default=0, ge=0)


class OpenConflictInput(ApiModel):
    conflict_id: UUID
    claim_ids: Annotated[list[UUID], Field(max_length=10)] = []
    relied_on: bool = Field(default=False, description="The creative relies on one of the conflicting claims.")
    status: ConflictState = "open"
    summary: ShortText


class VersionObservations(ApiModel):
    """Everything observed about one creative version in one region. Missing observations are reported, never assumed."""

    provenance: Provenance = Provenance()
    quick_read: QuickReadObservation | None = None
    risk_check: RiskCheckObservation | None = None
    transcreation: TranscreationObservation | None = None
    references: ReferenceObservation | None = None
    objective_checks: Annotated[list[ObjectiveCheck], Field(max_length=20)] = []
    evidence_meter: EvidenceMeterObservation | None = None
    open_conflicts: Annotated[list[OpenConflictInput], Field(max_length=50)] = []


# --- Compare and Score ----------------------------------------------------------------------------


class ScoreVersionInput(ApiModel):
    version_id: UUID
    label: Label
    observations: VersionObservations


class ScoreCompareRequest(ApiModel):
    region_code: RegionCode
    versions: Annotated[list[ScoreVersionInput], Field(min_length=2, max_length=4)]
    scoring_version: ScoringVersion = "mvp-2"

    @model_validator(mode="after")
    def _unique_versions(self) -> Self:
        if len({v.version_id for v in self.versions}) != len(self.versions):
            raise ValueError("version ids must be unique.")
        return self


class SignalUsed(ApiModel):
    signal: str = Field(description="Stable name of the input, e.g. quick_read.understood_share.")
    value: float = Field(description="The signal on a 0-100 scale (for sensitivity_risk, 100 means most risk).")
    weight: float = Field(description="Weight inside the dimension.")
    detail: str


class DimensionScore(ApiModel):
    dimension: ScoreDimension
    label: str
    value: float | None = Field(description="0-100, or null when no input was available.")
    higher_is_better: bool
    utility: float | None = Field(description="value, or 100 - value where lower is better.")
    weight: float = Field(description="Weight in the overall score.")
    rule_ids: list[str]
    inputs_used: list[SignalUsed]
    missing_inputs: list[str]
    explanation: str


class ScoreCard(ApiModel):
    version_id: UUID
    label: str
    scoring_version: ScoringVersion
    dimensions: list[DimensionScore]
    overall: float | None = Field(description="Weighted utility over the assessed dimensions; null below the minimum coverage.")
    coverage: float = Field(description="Share of the total weight that was assessed (0-1).")
    complete: bool = Field(description="Every dimension was assessed.")
    rule_ids: list[str] = Field(description="Every rule that shaped the card, in order.")
    limitations: list[str]
    provenance: Provenance


class ScoreComparability(ApiModel):
    same_scoring_version: bool
    same_model: bool
    same_prompt_version: bool
    same_criteria: bool
    same_evidence: bool
    same_dimensions_assessed: bool
    comparable: bool = Field(description="All of the above hold. When false, the ranking is not a like-for-like result.")
    notes: list[str]


class RankedVersion(ApiModel):
    rank: int
    version_id: UUID
    label: str
    overall: float | None


class VersionValue(ApiModel):
    version_id: UUID
    value: float | None


class DimensionDifference(ApiModel):
    dimension: ScoreDimension
    label: str
    spread: float = Field(description="Largest minus smallest assessed value, in points.")
    leader_version_id: UUID | None
    values: list[VersionValue]


class RuleDoc(ApiModel):
    rule_id: str
    applies_to: str
    description: str


class DimensionDoc(ApiModel):
    dimension: ScoreDimension
    label: str
    definition: str
    higher_is_better: bool
    weight: float


class ScoringMethodology(ApiModel):
    version: ScoringVersion
    scale: str
    dimensions: list[DimensionDoc]
    rules: list[RuleDoc]
    aggregation: str
    thresholds: dict[str, float]
    limitations: list[str]


class ScoreComparison(ApiModel):
    scoring_version: ScoringVersion
    region_code: str
    cards: list[ScoreCard]
    ranking: list[RankedVersion]
    meaningful_margin: bool = Field(description="The top two overall scores differ by at least the documented margin.")
    comparability: ScoreComparability
    major_differences: list[DimensionDifference]
    methodology: ScoringMethodology
    notes: list[str]


# --- Readiness Board ------------------------------------------------------------------------------


class ReadinessRequest(ApiModel):
    region_code: RegionCode
    version_id: UUID
    label: Label = "Version"
    observations: VersionObservations


class ReadinessIssue(ApiModel):
    rule_id: str
    priority: int = Field(description="Lower is more urgent.")
    effect: Literal["fix", "rethink"] = Field(description="The best verdict this issue allows.")
    summary: str
    action: str
    source: str = Field(description="The observation the rule read, e.g. quick_read or risk_check.")
    evidence_ids: list[UUID]


class RiskSummary(ApiModel):
    open_high: int
    open_medium: int
    open_low: int
    blocking: int = Field(description="Unresolved findings that rule out Go.")


class ReadinessAssessment(ApiModel):
    """The deterministic part of a verdict: everything the rules computed from the inputs."""

    verdict: Verdict = Field(description="A recommendation computed by rules. Only a person can approve a version.")
    main_reason: str
    highest_priority_issue: ReadinessIssue | None
    issues: list[ReadinessIssue]
    next_action: str
    supporting_evidence_ids: list[UUID]
    open_conflicts: list[OpenConflictInput]
    confidence_limitations: list[str]
    risk: RiskSummary
    evidence_strength: MeterStrength | None
    score: ScoreCard
    rule_version: str
    scoring_version: ScoringVersion
    rules_applied: list[str]
    provenance: Provenance


class ReadinessVerdict(ReadinessAssessment):
    id: UUID
    campaign_id: UUID
    region_code: str
    region_name: str
    version_id: UUID
    input_fingerprint: str = Field(description="SHA-256 of the canonical inputs: same inputs and rule version give the same verdict.")
    mode: DataMode
    is_latest: bool = Field(description="The newest verdict for this region and version.")
    computed_by: UUID
    computed_at: datetime


class ReadinessPage(Page[ReadinessVerdict]):
    pass


class ReadinessRuleDoc(ApiModel):
    rule_id: str
    effect: Literal["fix", "rethink"]
    priority: int
    description: str


class ReadinessRules(ApiModel):
    rule_version: str
    scoring_version: ScoringVersion
    verdict_meanings: dict[str, str]
    rules: list[ReadinessRuleDoc]
    thresholds: dict[str, float]
    notes: list[str]


class Approval(ApiModel):
    id: UUID
    campaign_id: UUID
    region_code: str
    version_id: UUID
    decision: ApprovalDecision
    reason: str
    decided_by: UUID
    decided_by_name: str | None
    decided_at: datetime
    readiness_verdict_id: UUID | None
    verdict_at_decision: Verdict | None = Field(description="The readiness recommendation in force when the person decided.")
    overrides_recommendation: bool = Field(description="Approved although the recommendation was not Go (or none existed).")
    mode: DataMode


class ApprovalCreate(ApiModel):
    region_code: RegionCode
    version_id: UUID
    decision: ApprovalDecision
    reason: MediumText
    readiness_verdict_id: UUID | None = Field(
        default=None, description="The verdict the person reviewed; defaults to the latest one for the region and version."
    )


class ApprovalPage(Page[Approval]):
    pass


class VersionReadiness(ApiModel):
    verdict: ReadinessVerdict
    history_count: int
    latest_approval: Approval | None


class RegionReadiness(ApiModel):
    region_code: str
    region_name: str
    versions: list[VersionReadiness] = Field(description="The newest verdict for each version, newest first.")


class ReadinessBoard(ApiModel):
    campaign_id: UUID
    regions: list[RegionReadiness]
    note: str

