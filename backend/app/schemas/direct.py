"""Voice Director contract (feature 26, and the Command Bar's typed Voice Director): an instruction about one version of a
creative becomes a plan of steps over the Studio tools that already exist, and nothing runs until the user confirms.

The model only proposes the plan. Every step is validated in code before it is shown (element ids exist, locked elements
are refused, the region and language come from the reference lists), and the server stores the validated plan, so a
confirmation can only apply steps the server itself produced. Applying a step goes through the same services as the
Studio UI and makes a new version as actor `ai` with the instruction as its reason.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.common import ApiModel, DataMode, Page

DirectSource = Literal["typed", "voice"]
DirectStepKind = Literal[
    "propose_chips", "apply_chip", "edit_element", "lock_element", "unlock_element", "restore_version", "transcreate", "navigate"
]
DirectWorkspace = Literal["desk", "lens", "studio", "lab", "launch", "pulse", "proof"]
DirectStepStatus = Literal["proposed", "blocked", "applying", "applied", "refused", "failed"]
DirectBlockCode = Literal["LOCKED", "UNKNOWN", "INVALID", "CHECKS_FAILED"]
DirectPlanStatus = Literal["proposed", "partial", "applied", "refused", "unsupported"]
DirectTranscribeStatus = Literal["transcribed", "unavailable", "failed"]

Instruction = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
# What the plan can do, in words. Shown when a request cannot be turned into steps.
SUPPORTED_ACTIONS: tuple[str, ...] = (
    "Propose Tweak Chips for a line of copy",
    "Apply a Tweak Chip that was already proposed",
    "Change the text of a line of copy",
    "Lock or unlock an element",
    "Restore an earlier version",
    "Transcreate lines into a regional language",
    "Open a workspace",
)


class DirectBlock(ApiModel):
    code: DirectBlockCode
    message: str


class DirectStepResult(ApiModel):
    message: str
    version_id: UUID | None = None
    operation_id: UUID | None = None
    run_id: UUID | None = Field(default=None, description="A Transcreate run started by this step (it makes its version when it finishes).")
    chip_ids: list[UUID] = []
    chip_version_id: UUID | None = Field(default=None, description="propose_chips: the version the proposed chips belong to.")


class DirectStep(ApiModel):
    id: str = Field(description="s1, s2, ... in the order the steps run.")
    kind: DirectStepKind
    title: str = Field(description="What the step does, written by code from the validated parameters.")
    rationale: str = Field(description="Why the model proposed it: a model interpretation, not evidence.")
    element_id: str | None = None
    version_id: UUID | None = Field(default=None, description="restore_version: the version to restore.")
    chip_id: UUID | None = None
    region_code: str | None = None
    language: str | None = None
    element_ids: list[str] = []
    workspace: DirectWorkspace | None = None
    before: str | None = Field(default=None, description="The current text of the element the step changes.")
    after: str | None = Field(default=None, description="The text the step would write.")
    changes_data: bool = Field(description="True when applying makes a new version or changes a lock.")
    uses_model: bool = Field(description="True when applying calls a model again (Tweak Chips, Transcreate).")
    needs_confirmation: bool = Field(description="False only for opening a workspace.")
    status: DirectStepStatus
    blocked: DirectBlock | None = Field(default=None, description="Why code refused the step at planning time.")
    result: DirectStepResult | None = None


class DirectPlanRequest(ApiModel):
    version_id: UUID | None = Field(default=None, description="The version the instruction is about; defaults to the newest.")
    instruction: Instruction
    source: DirectSource = "typed"
    transcript: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = Field(
        default=None, description="Voice only: the transcript as the model heard it, before the person corrected it."
    )


class DirectPlan(ApiModel):
    id: UUID
    campaign_id: UUID
    version_id: UUID = Field(description="The version the plan starts from.")
    source: DirectSource
    instruction: str
    transcript: str | None
    mode: DataMode
    status: DirectPlanStatus
    supported: bool
    summary: str | None = Field(description="The model's reading of the instruction: a model interpretation.")
    refusal: str | None = Field(description="Why the instruction could not be turned into steps.")
    supported_actions: list[str] = Field(description="What a plan can contain; listed in full when nothing could be planned.")
    steps: list[DirectStep]
    notes: list[str]
    run_id: UUID | None
    provider: str | None
    model_id: str | None
    prompt_version: str | None
    estimated_cost_usd: float | None = Field(description="An estimate from the price table for the planning call; null when unknown.")
    created_at: datetime
    updated_at: datetime


class DirectPlanPage(Page[DirectPlan]):
    pass


class DirectApply(ApiModel):
    step_ids: list[Annotated[str, StringConstraints(pattern=r"^s[0-9]{1,2}$")]] = Field(
        min_length=1, max_length=8, description="The steps the person confirmed. Only these run, in plan order."
    )


class DirectTranscript(ApiModel):
    status: DirectTranscribeStatus
    transcript: str = Field(description="What the model heard, in the language spoken. Empty when there is none; never invented.")
    language: str | None
    duration_ms: int | None
    provider: str | None
    model_id: str | None
    message: str | None = Field(description="Why there is no transcript, when there is none.")
