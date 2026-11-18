"""Remake: Visuals and Remake: Sound (features 21 and 22). Both start runs (202, Idempotency-Key honoured); the result of
a run is one applied `remake` operation, read back here with its checks, costs and assets."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas import remake as r
from app.schemas.runs import RunAccepted
from app.services import remake

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
