"""Message Check (lab-t3): does the intended message land in each region? A lighter Quick Read.

Each synthetic participant reads only the regional copy, then restates the message in their own words and says what they
remember. A separate comparison step marks, for every key point of the intended message, whether the restatement carried
it and whether it was recalled, and names a misreading when the restatement says something else. Everything after that is
code: each participant's score and verdict follow the published rules, and every rate is a count over the participants
who completed. Wording overlap with the intended message is shown only as a wording measure: similarity is not proof of
understanding, and a restatement that echoes the words can still miss the point.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.schemas.audience import (
    AudienceRunMetadata,
    CreativeCopy,
    PanelDescription,
    PanelDisclosure,
    PanelParticipant,
    RegionCode,
    RegionRef,
    SamplingPlan,
    VersionRef,
)
from app.schemas.campaigns import CampaignContent
from app.schemas.common import ApiModel, DataMode, ShortText
from app.schemas.runs import RunError, RunProgress, RunStatus

PointCoverage = Literal["yes", "partly", "no"]
MessageVerdict = Literal["understood", "partly", "missed", "misread"]
KeyPoint = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]


class MessageCheckTarget(ApiModel):
    """One region to check and the copy that region is shown."""

    region_code: RegionCode
    content_version_id: UUID | None = Field(default=None, description="A stored content version. Defaults to the campaign's current version.")
    version_ref: VersionRef | None = Field(default=None, description="Opaque reference to a version node; stored, not joined.")
    creative: CampaignContent | None = Field(default=None, description="Regional copy to test instead of a stored version (for example a Studio version).")

    @model_validator(mode="after")
    def _one_source(self) -> "MessageCheckTarget":
        if self.creative is not None and self.content_version_id is not None:
            raise ValueError("Give either content_version_id or creative, not both.")
        return self


class MessageCheckCreate(ApiModel):
    """Check whether the intended message survives in each target region."""

    targets: Annotated[list[MessageCheckTarget], Field(min_length=1, max_length=6)]
    intended_message: ShortText | None = Field(default=None, description="Defaults to the primary message of the campaign brief.")
    key_points: Annotated[list[KeyPoint], Field(min_length=1, max_length=5)] | None = Field(
        default=None, description="The parts of the message a reader must carry away. Defaults to the message split by code.")
    size_per_region: int = Field(default=8, ge=3, description="Synthetic participants per region. The upper bound is a server setting.")
    sampling: SamplingPlan = Field(
        default=SamplingPlan(), description="Languages, city tiers and age bands. States come from the targets; do not list them here.")
    seed: int = Field(default=42, ge=0)

    @field_validator("targets")
    @classmethod
    def _distinct_regions(cls, value: list[MessageCheckTarget]) -> list[MessageCheckTarget]:
        codes = [t.region_code for t in value]
        if len(set(codes)) != len(codes):
            raise ValueError("List each region once.")
        return value


class MessageCheckPoint(ApiModel):
    id: str = Field(description="K1, K2, ...")
    text: str


class MessageCheckPointJudgement(ApiModel):
    point_id: str
    restated: PointCoverage = Field(description="The comparison step's label: did the restatement carry this point?")
    recalled: bool = Field(description="Did the participant's unprompted recall include it?")


class MessageCheckMisreading(ApiModel):
    label: str
    why: str


class MessageCheckResponse(ApiModel):
    is_synthetic: Literal[True] = True
    restated: str = Field(description="The message in the participant's own words (may be in their language).")
    restated_en: str = Field(description="An English gloss, written by the same model, used for the comparison and the wording measure.")
    recall: list[str]
    points: list[MessageCheckPointJudgement]
    misreading: MessageCheckMisreading | None
    score: float | None = Field(description="Mean over key points: yes 1, partly 0.5, no 0. Null when the comparison did not cover the participant.")
    verdict: MessageVerdict | None = Field(description="From the published rules over the points and the misreading; computed by code.")
    wording_overlap: float | None = Field(description="Share of words held in common with the intended message, 0 to 1. A wording measure only.")


class MessageCheckParticipant(PanelParticipant):
    response: MessageCheckResponse | None


class MessageCheckRates(ApiModel):
    denominator: int = Field(description="Participants whose restatement was compared. Rates are counts over this number.")
    failed: int = Field(description="Participants left out because the model returned nothing usable for them.")
    understood: int
    partly: int
    missed: int
    misread: int
    understood_rate: float | None


class MessageCheckPointRate(ApiModel):
    point_id: str
    text: str
    restated_yes: int
    restated_partly: int
    restated_no: int
    recalled: int
    denominator: int


class MessageCheckExample(ApiModel):
    participant_id: UUID
    ordinal: int
    language_name: str
    restated: str
    restated_en: str


class MessageCheckMisreadingGroup(ApiModel):
    label: str
    participants: int
    examples: list[MessageCheckExample]


class MessageCheckLanguageRow(ApiModel):
    language: str
    language_name: str
    rates: MessageCheckRates


class MessageCheckRegion(ApiModel):
    region: RegionRef
    creative: CreativeCopy
    version_ref: str | None
    rates: MessageCheckRates
    points: list[MessageCheckPointRate]
    by_language: list[MessageCheckLanguageRow]
    misreadings: list[MessageCheckMisreadingGroup]
    recommendations: list[str] = Field(description="Written by code from the counts above; each names the numbers it rests on.")


class MessageCheckSummary(ApiModel):
    overall: MessageCheckRates
    regions: list[MessageCheckRegion]
    rules: list[str]
    rules_version: str


class MessageCheckResult(ApiModel):
    id: UUID
    campaign_id: UUID
    project_id: UUID
    status: RunStatus
    mode: DataMode
    intended_message: str
    intended_message_source: Literal["request", "brief"]
    key_points: list[MessageCheckPoint]
    key_points_source: Literal["request", "split_by_code"]
    panel: PanelDescription
    participants: list[MessageCheckParticipant]
    summary: MessageCheckSummary | None
    disclosure: PanelDisclosure
    limitations: list[str]
    error: RunError | None
    progress: RunProgress | None
    run_metadata: AudienceRunMetadata
    created_at: datetime

