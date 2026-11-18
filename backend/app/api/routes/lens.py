"""Market Lens: build region profiles from the culture sources, then read them as an atlas, a state profile, a comparison,
a moment calendar and a language map. Campaign-scoped: the campaign's brand decides demo (fixtures) or live (real sources)."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from app.api.deps import CurrentUser, Limit, Offset
from app.core.errors import ValidationFailed
from app.db.base import utcnow
from app.schemas import lens as v
from app.schemas.common import ErrorDetail
from app.services import lens, lens_views

router = APIRouter(prefix="/campaigns/{campaign_id}/lens", tags=["lens"])

RegionPath = Annotated[str, Path(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$", description="ISO 3166-2:IN code, for example IN-TN.")]


@router.post("/builds", response_model=v.LensBuildBatch, status_code=201)
async def build_profiles(campaign_id: UUID, body: v.LensBuildRequest, user: CurrentUser) -> v.LensBuildBatch:
    """Build, or refresh, the profile of each state: gather claims from the culture sources, store them with provenance and
    computed confidence, and save a versioned build record. Owner or editor role.

    Demo campaigns use the labelled fixture source only. Live campaigns call the live sources with their cool-downs: a state
    built less than LENS_LIVE_BUILD_MIN_INTERVAL_SECONDS ago answers 429, and rate-limited or unconfigured sources are
    reported in the build's `gaps`, `calls` and `status` (partial), never hidden."""
    return await lens.build_regions(user.id, campaign_id, body)


@router.get("/builds", response_model=v.LensBuildPage)
async def list_builds(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0,
    region_code: Annotated[str | None, Query(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")] = None,
) -> v.LensBuildPage:
    """Build history of the workspace in the campaign's mode, newest first."""
    return await lens.list_builds(await lens.lens_context(user.id, campaign_id), region_code, limit, offset)


@router.get("/regions/{region_code}/builds/{build_id}", response_model=v.LensBuildView)
async def get_build(campaign_id: UUID, region_code: RegionPath, build_id: UUID, user: CurrentUser) -> v.LensBuildView:
    """One build with its source calls (status, cache hit, duration, error type)."""
    return await lens.build_detail(await lens.lens_context(user.id, campaign_id), region_code, build_id)


@router.get("/atlas", response_model=v.LensAtlas)
async def get_atlas(campaign_id: UUID, user: CurrentUser) -> v.LensAtlas:
    """Culture Atlas: every state and union territory with what is known and how strong the evidence is (Evidence Meter
    rating), plus the source families and their dates."""
    return await lens_views.atlas(await lens.lens_context(user.id, campaign_id))


@router.get("/regions/{region_code}/profile", response_model=v.LensStateProfile)
async def get_state_profile(campaign_id: UUID, region_code: RegionPath, user: CurrentUser) -> v.LensStateProfile:
    """State Profile: languages, festivals and moments, cultural references, humour and tone, public attention, open
    conflicts and the Evidence Meter. Every fact is a claim with source, date, kind, scope and confidence."""
    return await lens_views.state_profile(await lens.lens_context(user.id, campaign_id), region_code)


@router.get("/compare", response_model=v.LensCompare)
async def compare_states(
    campaign_id: UUID, user: CurrentUser,
    region_code: Annotated[list[Annotated[str, Query(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")]], Query(description="Repeat for 2 to 4 states.")],
) -> v.LensCompare:
    """Region Compare: 2 to 4 states side by side on the same dimensions, with missing evidence shown as missing."""
    return await lens_views.compare(await lens.lens_context(user.id, campaign_id), region_code)


@router.get("/regions/{region_code}/calendar", response_model=v.LensCalendar)
async def get_moment_calendar(
    campaign_id: UUID, region_code: RegionPath, user: CurrentUser,
    year: Annotated[int | None, Query(ge=2000, le=2100, description="Default: the current year.")] = None,
    window_from: Annotated[date | None, Query(description="Start of a campaign window to compare moments against.")] = None,
    window_to: Annotated[date | None, Query(description="End of the window, inclusive.")] = None,
) -> v.LensCalendar:
    """Moment Calendar: dated moments for a year (each date a claim with its source) and the festivals sources describe
    without an exact date. Disagreeing sources stay as separate claims with their conflict. An optional window flags moments
    inside it."""
    if (window_from is None) != (window_to is None):
        raise ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field="window_from", message="Give window_from and window_to together.")])
    if window_from and window_to and window_from > window_to:
        raise ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field="window_from", message="window_from must not be after window_to.")])
    window = v.LensWindow(date_from=window_from, date_to=window_to) if window_from and window_to else None
    return await lens_views.calendar(await lens.lens_context(user.id, campaign_id), region_code, year or utcnow().year, window)


@router.get("/language-map", response_model=v.LensLanguageMap)
async def get_language_map(campaign_id: UUID, user: CurrentUser) -> v.LensLanguageMap:
    """Language Map: languages and scripts of every state (reference data) with Census 2011 mother-tongue shares where a
    build stored them, labelled 2011."""
    return await lens_views.language_map(await lens.lens_context(user.id, campaign_id))
