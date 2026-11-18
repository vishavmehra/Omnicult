"""Workflow inputs and outcomes: the interface between the run engine (app/services/runs.py) and the
AI workflows. Workflows are pure (no DB access); the engine persists what they return."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import DataMode, StepTrace
from app.schemas.population import ReactionCategory
from app.schemas.projects import BrandExample

if TYPE_CHECKING:
    from app.integrations.culture import CultureService
    from app.llm import LLMGateway

OutcomeStatus = Literal["completed", "partial", "failed"]


class BrandContext(BaseModel):
    """Brand Memory as read by a run. Workflows never write it (D-036)."""

    name: str
    description: str | None = None
    positioning: str | None = None
    voice: list[str] = []
    communication_style: str | None = None
    target_audience: str | None = None
    audience_preferences: str | None = None
    preferred_terms: list[str] = []
    prohibited_terms: list[str] = []
    protected_terms: list[str] = []
    approved_examples: list[BrandExample] = []
    constraints: list[str] = []


class WorkflowContext(BaseModel):
    run_id: UUID
    project_id: UUID
    campaign_id: UUID | None = None
    mode: DataMode
    brand: BrandContext


class ProgressFn(Protocol):
    async def __call__(self, stage: str, completed_steps: int, total_steps: int, message: str) -> None: ...


class AssetBlob(BaseModel):
    """An uploaded image, loaded by the engine. Sent only to a verified vision model, never to a text model."""

    asset_id: UUID
    media_type: str
    data: bytes


class VisionAnalyzer(Protocol):
    """the `app.llm.vision.VisionClient`, reached through `LLMGateway.capability("vision")`.

    `observe` never raises for provider problems: it returns VisionResult(status: VisionStatus,
    observations: list[VisualObservation], trace: StepTrace | None)."""

    def is_configured(self) -> bool: ...

    async def observe(self, asset_id: UUID, image: bytes, content_type: str, *, stage: str, agent: str) -> Any: ...


@dataclass
class WorkflowDeps:
    llm: LLMGateway
    vision: VisionAnalyzer | None = None  # None: vision is unavailable (never a text model instead)
    media: Any = None  # the media pipeline (app/services/media.py): ffmpeg work and derived files; local, no provider
    transcribe: Any = None  # a `transcribe` capability adapter returning app.media.types.TranscribeResult; None: unavailable
    culture: CultureService | None = None  # the cultural-evidence layer (app/integrations/culture)


class FollowUpReply(BaseModel):
    """One synthetic answer (README §14.8); the engine stores it as a FollowUp, which then becomes a memory."""

    participant_id: UUID
    answer: str
    stance: ReactionCategory | None
    memory_refs: list[UUID]  # stored MemoryItem.ref_id values only
    model_id: str | None
    trace: StepTrace | None = None  # None for demo answers (no model call)


class GroupReply(BaseModel):
    """Answers of the sampled participants (the engine samples and tallies) plus a model summary of those answers."""

    answers: list[FollowUpReply]
    summary: str
    trace: StepTrace | None = None
