"""Voice Director: the typed and spoken way to direct a version of a creative with the Studio's own tools.

A plan is made from one instruction (one model call) and stored with every step already validated in code. Nothing is
applied until a person confirms steps; a confirmation can only name steps of the stored plan, and each applied step is a new
version through the same services as the Studio UI. A locked element still refuses (409). Speech is transcribed first and
shown for correction; the audio is never stored.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas import direct as v
from app.services import voice_director as service

router = APIRouter(tags=["voice-director"])


@router.post("/campaigns/{campaign_id}/direct/transcribe", response_model=v.DirectTranscript)
async def transcribe_instruction(
    campaign_id: UUID,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="A short recording (WAV, WebM, Ogg or MP4), at most 4 MB and 60 seconds.")],
    language: Annotated[str | None, Form(pattern=r"^[a-z]{2,3}$", description="Expected spoken language (ISO 639-1), or leave empty.")] = None,
) -> v.DirectTranscript:
    """Speech to text for one instruction. The result is shown to the person to correct before it is planned. A demo project
    never calls a provider and says so instead of inventing a transcript; the audio is not stored."""
    data = await file.read(service.MAX_CLIP_BYTES + 1)  # bounded read; an oversize clip is refused by the service
    return await service.transcribe(user.id, campaign_id, data, language)


@router.post("/campaigns/{campaign_id}/direct/plans", status_code=status.HTTP_201_CREATED, response_model=v.DirectPlan)
async def create_direct_plan(campaign_id: UUID, body: v.DirectPlanRequest, user: CurrentUser) -> v.DirectPlan:
    """Turn an instruction about one version into a plan of steps (one model call, recorded as a voice_direct run). Every
    step is validated in code; a step code refused is kept as `blocked` with its reason. Nothing is applied."""
    return await service.create_plan(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/direct/plans", response_model=v.DirectPlanPage)
async def list_direct_plans(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> v.DirectPlanPage:
    """The campaign's plans, newest first."""
    return await service.list_plans(user.id, campaign_id, limit, offset)


@router.get("/campaigns/{campaign_id}/direct/plans/{plan_id}", response_model=v.DirectPlan)
async def get_direct_plan(campaign_id: UUID, plan_id: UUID, user: CurrentUser) -> v.DirectPlan:
    return await service.get_plan(user.id, campaign_id, plan_id)


@router.post("/campaigns/{campaign_id}/direct/plans/{plan_id}/apply", response_model=v.DirectPlan)
async def apply_direct_plan(campaign_id: UUID, plan_id: UUID, body: v.DirectApply, user: CurrentUser) -> v.DirectPlan:
    """Apply the steps the person confirmed, in plan order, each through the Studio's own services. A step the rules refuse
    (a locked element, a changed text) is recorded as refused and the others still run; the returned plan has every outcome."""
    return await service.apply_plan(user.id, campaign_id, plan_id, body)
