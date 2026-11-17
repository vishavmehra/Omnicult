"""Inputs and outcomes of the Audience Lab workflows (Quick Read, Audience Study, Risk Check).

Like every workflow in this package they are pure: no database access. The service (`app.services.audience`) builds the
inputs from a snapshot stored when the run started, and persists what the outcome holds.
"""

from uuid import UUID

from pydantic import BaseModel

from app.schemas.audience import (
    AdCodeRef,
    Anchor,
    CreativeElementIn,
    CreativeSceneIn,
    GroundingClaim,
    QuickReadResponse,
    QuickReadSummary,
    RegionRef,
    StudyInterview,
    StudySummary,
)
from app.schemas.campaigns import CampaignContent
from app.schemas.common import StepTrace
from app.schemas.runs import RunError
from app.workflows.types import OutcomeStatus, WorkflowContext


class PanelMember(BaseModel):
    id: UUID
    ordinal: int
    state_code: str
    state_name: str
    language: str
    language_name: str
    city_tier: str
    age_band: str
    traits: dict[str, str]
    persona: str


class GroundingStats(BaseModel):
    cited_claim_ids: list[UUID] = []
    claim_supported: int = 0
    interpretation: int = 0
    dropped_handles: int = 0


class QuickReadInput(BaseModel):
    context: WorkflowContext
    region: RegionRef
    creative: CampaignContent
    intended_message: str | None = None
    participants: list[PanelMember]
    claims: list[GroundingClaim] = []
    seed: int = 42


class QuickReadOutcome(BaseModel):
    status: OutcomeStatus
    responses: dict[UUID, QuickReadResponse]
    summary: QuickReadSummary | None
    grounding: GroundingStats
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None


class AudienceStudyInput(BaseModel):
    context: WorkflowContext
    regions: list[RegionRef]
    content_version_id: UUID
    creative: CampaignContent
    intended_message: str | None = None
    participants: list[PanelMember]
    claims: list[GroundingClaim] = []
    depth: str = "standard"
    seed: int = 42


class AudienceStudyOutcome(BaseModel):
    status: OutcomeStatus
    interviews: dict[UUID, StudyInterview]
    summary: StudySummary | None
    grounding: GroundingStats
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None


class RiskCheckInput(BaseModel):
    context: WorkflowContext
    region: RegionRef
    product_category: str | None = None
    elements: list[CreativeElementIn]
    scenes: list[CreativeSceneIn] = []
    claims: list[GroundingClaim] = []


class DraftFinding(BaseModel):
    """A verified finding before it is stored: ids and status are assigned by the service."""

    element_id: str
    category: str
    severity: str
    blocks_go: bool
    confidence_label: str
    anchor: Anchor
    quote: str | None
    quote_start: int | None
    quote_end: int | None
    verification: str
    observation: str
    interpretation: str
    suggested_fix: str | None
    ad_codes: list[AdCodeRef]
    claim_ids: list[UUID]
    source: str
    severity_rules: list[dict[str, str]]
    limitations: list[str]


class DroppedCounts(BaseModel):
    unverified_quote: int = 0
    unknown_element: int = 0
    duplicate: int = 0
    invalid_references: int = 0  # handles removed from kept findings; informational

    @property
    def total(self) -> int:
        return self.unverified_quote + self.unknown_element + self.duplicate


class RiskCheckOutcome(BaseModel):
    status: OutcomeStatus
    findings: list[DraftFinding]
    dropped: DroppedCounts
    cited_claim_ids: list[UUID]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None
