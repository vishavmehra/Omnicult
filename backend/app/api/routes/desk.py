"""Campaign Desk: the versioned Campaign Brief, the Brand Kit, and the Today view."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas import desk as v
from app.services import desk, desk_today

router = APIRouter(tags=["campaign-desk"])


@router.get("/campaigns/{campaign_id}/brief", response_model=v.CampaignBrief)
async def get_brief(campaign_id: UUID, user: CurrentUser) -> v.CampaignBrief:
    """The current brief. A campaign with no saved brief returns version 0 with content derived from the campaign record."""
    return await desk.get_brief(user.id, campaign_id)


@router.put("/campaigns/{campaign_id}/brief", response_model=v.CampaignBrief)
async def save_brief(campaign_id: UUID, body: v.BriefUpdate, user: CurrentUser) -> v.CampaignBrief:
    """Replace the brief. Changed content becomes the next version; unchanged content is a no-op. Demo campaigns return 409."""
    return await desk.save_brief(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/brief/versions", response_model=v.BriefVersionPage)
async def list_brief_versions(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> v.BriefVersionPage:
    return await desk.list_brief_versions(user.id, campaign_id, limit, offset)


@router.get("/campaigns/{campaign_id}/brief/versions/{version}", response_model=v.BriefVersion)
async def get_brief_version(campaign_id: UUID, version: int, user: CurrentUser) -> v.BriefVersion:
    return await desk.get_brief_version(user.id, campaign_id, version)


@router.get("/projects/{project_id}/brand-kit", response_model=v.BrandKit)
async def get_brand_kit(project_id: UUID, user: CurrentUser) -> v.BrandKit:
    """The brand record and the Brand Kit design, with calculated contrast ratios and the Brand Glossary's size."""
    return await desk.get_brand_kit(user.id, project_id)


@router.put("/projects/{project_id}/brand-kit", response_model=v.BrandKit)
async def save_brand_kit(project_id: UUID, body: v.KitUpdate, user: CurrentUser) -> v.BrandKit:
    """Replace the design half of the Brand Kit. Term lists are edited through PUT /projects/{id}/brand. Demo brands return 409."""
    return await desk.save_brand_kit(user.id, project_id, body)


@router.get("/desk/today", response_model=v.TodayView)
async def get_today(
    user: CurrentUser,
    campaign_id: Annotated[UUID | None, Query(description="Limit the view to one campaign.")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Activity rows returned.")] = 30,
) -> v.TodayView:
    """What changed, open evidence conflicts, readiness verdicts and next actions across the caller's campaigns."""
    return await desk_today.today(user.id, campaign_id, limit)
