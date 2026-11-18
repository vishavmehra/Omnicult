"""Inputs and outcomes of the Audience Lab session workflows (Live Focus Group, Buzz Simulator, Message Check; lab-t3).

Like every workflow in this package they hold no database access: the service builds the inputs from a snapshot stored when
the run started and hands the workflow small callbacks (`FocusIO`, `BuzzIO`) to save what it produced as it goes.
"""

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from app.schemas.audience import GroundingClaim
from app.schemas.campaigns import CampaignContent
from app.schemas.common import StepTrace
from app.schemas.runs import RunError
from app.workflows.audience_types import PanelMember
from app.workflows.types import OutcomeStatus, WorkflowContext

# --- Live Focus Group -----------------------------------------------------------------------------------------------


class FocusSpeaker(PanelMember):
    """A panel member chosen to speak, with what their stored response says."""

    stance: str | None = None
    first_reaction: str | None = None
    restated: str | None = None


class FocusGroupInput(BaseModel):
    context: WorkflowContext
    creative: CampaignContent
    intended_message: str | None = None
    speakers: list[FocusSpeaker]
    guide: list[str]
    claims: list[GroundingClaim] = []
    max_interjections: int = 5
    seed: int = 42


class DraftTurn(BaseModel):
    index: int
    round_index: int
    kind: str  # moderator | participant | researcher
    participant_id: UUID | None = None
    ordinal: int | None = None
    text: str
    reply_to: int | None = None
    relation: str | None = None
    stance: str | None = None
    themes: list[str] = []
    claim_ids: list[UUID] = []
    interjection_id: UUID | None = None


class FocusIO(Protocol):
    async def save_turn(self, turn: DraftTurn) -> None: ...

    async def take_interjections(self, limit: int) -> list[tuple[UUID, str]]:
        """Pending interjections, oldest first, marked as taken. At most `limit`."""
        ...


class FocusGroupOutcome(BaseModel):
    status: OutcomeStatus
    turns: list[DraftTurn]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None


# --- Buzz Simulator -------------------------------------------------------------------------------------------------


class DraftAct(BaseModel):
    id: UUID
    round_index: int
    participant_id: UUID
    action: str
    text: str | None = None
    text_en: str | None = None
    message_gloss: str | None = None
    stance: str
    topics: list[str] = []
    parent_act_id: UUID | None = None
    exposed_by: UUID | None = None
    wording_overlap: float | None = None


class BuzzIO(Protocol):
    async def save_acts(self, acts: list[DraftAct]) -> None: ...


class BuzzInput(BaseModel):
    context: WorkflowContext
    creative: CampaignContent
    intended_message: str | None = None
    participants: list[PanelMember]
    platform: str = "instagram"
    rounds: int = 3
    initial_exposure: float = 0.25
    degree: int = 4
    seed: int = 42


class BuzzOutcome(BaseModel):
    status: OutcomeStatus
    acts: list[DraftAct]
    network: dict[str, list[str]]
    seed_exposed: list[str]
    exposed_by: dict[str, str | None]
    rounds_run: int
    ended: str
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None


# --- Message Check --------------------------------------------------------------------------------------------------


class CheckTarget(BaseModel):
    region_code: str
    region_name: str
    creative: CampaignContent
    version_ref: str | None = None


class MessageCheckInput(BaseModel):
    context: WorkflowContext
    intended_message: str
    key_points: dict[str, str]  # K1 -> text
    targets: list[CheckTarget]
    participants: list[PanelMember]
    seed: int = 42


class ReadingRecord(BaseModel):
    restated: str
    restated_en: str
    recall: list[str]


class JudgementRecord(BaseModel):
    coverage: dict[str, str]  # K1 -> yes | partly | no
    recalled: dict[str, bool]
    misreading: tuple[str, str] | None = None


class MessageCheckOutcome(BaseModel):
    status: OutcomeStatus
    readings: dict[UUID, ReadingRecord]
    judgements: dict[UUID, JudgementRecord]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None
