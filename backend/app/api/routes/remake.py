"""Remake: Visuals, Remake: Sound and Remake: Video (features 21 to 23). All start runs (202, Idempotency-Key honoured); the
result of a run is one applied `remake` operation, read back here with its checks, costs and assets."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas import remake as r
from app.schemas.runs import RunAccepted
from app.services import remake, remake_video

router = APIRouter(tags=["remake"])


@router.get("/campaigns/{campaign_id}/remakes/capabilities", response_model=r.RemakeCapabilities)
async def remake_capabilities(campaign_id: UUID, user: CurrentUser) -> r.RemakeCapabilities:
    """Which models are configured, what one call is estimated to cost, the voices, and the budgets. Makes no call."""
    return await remake.capabilities(user.id, campaign_id)


@router.post("/campaigns/{campaign_id}/remakes/visual", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def start_remake_visual(campaign_id: UUID, body: r.RemakeVisualRequest, user: CurrentUser) -> RunAccepted:
    """Regional scene for one scene element (run_type remake_visual). A live project must set `confirm_cost`; 409 when the
    scene element is locked or the version has none; 503 when no image model is configured."""
    return await remake.start_visual(user.id, campaign_id, body)


@router.post("/campaigns/{campaign_id}/remakes/sound", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def start_remake_sound(campaign_id: UUID, body: r.RemakeSoundRequest, user: CurrentUser) -> RunAccepted:
    """Speak a version's voiceover or caption lines (run_type remake_sound), optionally with a Lyria jingle."""
    return await remake.start_sound(user.id, campaign_id, body)


@router.post("/campaigns/{campaign_id}/remakes/video/preview", response_model=r.RemakeVideoPreview)
async def preview_remake_video(campaign_id: UUID, body: r.RemakeVideoRequest, user: CurrentUser) -> r.RemakeVideoPreview:
    """The start frame, the exact prompt, the cost and the voice-over plan of a clip, before any paid call. Makes no model
    call and costs nothing; `confirm_cost` is ignored here."""
    return await remake_video.preview(user.id, campaign_id, body)


@router.post("/campaigns/{campaign_id}/remakes/video", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def start_remake_video(campaign_id: UUID, body: r.RemakeVideoRequest, user: CurrentUser) -> RunAccepted:
    """One short clip with Veo (run_type remake_video). A live project must set `confirm_cost`; 409 when the `remake-video`
    element is locked, the clip is estimated above the per-run AI budget, or (demo) the region has no saved clip; 503 when no
    video model is configured. At most one clip per request."""
    return await remake_video.start(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/remakes", response_model=r.RemakePage)
async def list_remakes(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, kind: r.RemakeKind | None = None,
    run_id: Annotated[UUID | None, Query()] = None,
) -> r.RemakePage:
    """Applied remakes, newest first. `run_id` finds the output of one run."""
    return await remake.list_remakes(user.id, campaign_id, limit, offset, kind, run_id)


@router.get("/campaigns/{campaign_id}/remakes/{operation_id}", response_model=r.RemakeOutput)
async def get_remake(campaign_id: UUID, operation_id: UUID, user: CurrentUser) -> r.RemakeOutput:
    return await remake.get_remake(user.id, campaign_id, operation_id)
