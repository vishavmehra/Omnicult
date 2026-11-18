"""Live Focus Group (lab-t3): a moderated, multi-turn discussion among synthetic participants drawn from an existing panel.

A moderator guide drives the session: each guide question is asked by the moderator (a turn the server writes from the
guide, never a model) and the chosen participants reply to the question and to each other, in turns. A person may
interject a question while the session runs; it is relayed at the next turn boundary. Text only.

Participants are the panel's synthetic participants, voiced from their stored response. Their stance, relation and themes
are the model's labels; every count, theme tally, split and position change below is computed by code from those labels.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.audience import (
    AudienceRunMetadata,
    CreativeCopy,
    GroundingSummary,
    PanelDisclosure,
    PanelParticipant,
    RegionRef,
)
from app.schemas.common import ApiModel, DataMode, MediumText, ShortText
from app.schemas.population import ReactionCategory, ReactionDistribution
from app.schemas.runs import RunError, RunProgress, RunStatus

FocusRelation = Literal["agrees", "disagrees", "builds_on", "new_point"]
FocusTurnKind = Literal["moderator", "participant", "researcher"]
FocusRoundKind = Literal["guide", "interjection"]
InterjectionStatus = Literal["pending", "taken", "dropped"]


class FocusGroupCreate(ApiModel):
    """Start a session on a finished Quick Read or Audience Study panel."""

    panel_run_id: UUID = Field(description="A completed Quick Read or Audience Study of this campaign; its participants speak.")
    participant_ids: Annotated[list[UUID], Field(min_length=2, max_length=12)] | None = Field(
        default=None, description="Speakers, from that panel. Leave out to let the server pick a seeded spread across the panel.")
    speakers: int = Field(default=6, ge=2, le=12, description="How many speakers when participant_ids is left out.")
    guide: Annotated[list[ShortText], Field(min_length=1, max_length=12)] | None = Field(
        default=None, description="The moderator's questions, in order. Leave out for the default guide.")
    seed: int = Field(default=42, ge=0)


class FocusGroupInterjectionCreate(ApiModel):
    text: MediumText = Field(description="A question or prompt from you. The moderator relays it at the next turn boundary.")


class FocusGroupInterjectionView(ApiModel):
    id: UUID
    run_id: UUID
    text: str
    status: InterjectionStatus
    created_at: datetime
    taken_at: datetime | None


class FocusGroupSpeaker(PanelParticipant):
    """A panel participant chosen to speak, with what their stored response says (the memory the session voices them from)."""

    stored_stance: ReactionCategory | None = Field(description="Their sentiment in the panel run's stored response.")
    stored_reaction: str | None = Field(description="Their first reaction in the panel run, as stored.")


class FocusGroupTurnView(ApiModel):
    id: UUID
    turn_index: int = Field(description="0-based position in the transcript; the T number a reply points at is turn_index + 1.")
    round_index: int
    kind: FocusTurnKind
    participant_id: UUID | None
    ordinal: int | None
    text: str
    reply_to_turn_index: int | None = Field(description="The earlier turn this one answers, when the reference checked out.")
    relation: FocusRelation | None
    stance: ReactionCategory | None = Field(description="The participant's own label for where they stand after this turn.")
    themes: list[str]
    claim_ids: list[UUID]
    basis: Literal["claim_supported", "interpretation"] | None = Field(
        description="claim_supported only when the turn cites an observed or calculated region claim; null for moderator and researcher turns.")
    interjection_id: UUID | None
    created_at: datetime


class FocusGroupRound(ApiModel):
    round_index: int
    kind: FocusRoundKind
    question: str
    answered: int = Field(description="Participant turns in this round.")
    stance: ReactionDistribution = Field(description="Stances of this round's participant turns, counted by code.")


class FocusGroupTheme(ApiModel):
    label: str
    participants: int = Field(description="Distinct speakers who raised it.")
    turn_indices: list[int]
    basis: Literal["interpretation"] = "interpretation"


class FocusGroupPosition(ApiModel):
    stance: ReactionCategory
    ordinals: list[int]
    turn_indices: list[int]


class FocusGroupDisagreement(ApiModel):
    kind: Literal["stance_split", "direct_challenge"]
    round_index: int
    question: str
    description: str
    positions: list[FocusGroupPosition]
    from_turn_index: int | None
    to_turn_index: int | None


class FocusGroupShift(ApiModel):
    participant_id: UUID
    ordinal: int
    from_stance: ReactionCategory
    to_stance: ReactionCategory
    from_turn_index: int
    to_turn_index: int


class FocusGroupSummary(ApiModel):
    turn_count: int
    participant_turns: int
    speakers_heard: int
    rounds: list[FocusGroupRound]
    themes: list[FocusGroupTheme]
    disagreements: list[FocusGroupDisagreement]
    shifts: list[FocusGroupShift]
    method: str


class FocusGroupResult(ApiModel):
    id: UUID
    campaign_id: UUID
    project_id: UUID
    status: RunStatus
    mode: DataMode
    panel_run_id: UUID
    panel_kind: Literal["quick_read", "audience_study"]
    regions: list[RegionRef]
    creative: CreativeCopy
    intended_message: str | None
    guide: list[str]
    speakers: list[FocusGroupSpeaker]
    turns: list[FocusGroupTurnView]
    interjections: list[FocusGroupInterjectionView]
    interjections_open: bool = Field(description="True while the session is still running and can relay a question.")
    summary: FocusGroupSummary
    grounding: GroundingSummary
    disclosure: PanelDisclosure
    limitations: list[str]
    error: RunError | None
    progress: RunProgress | None
    run_metadata: AudienceRunMetadata
    created_at: datetime
