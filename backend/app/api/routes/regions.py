from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.common import CountryCode, DataMode
from app.schemas.regions import EvidenceMeter, Region, RegionPage, RegionProfile
from app.services import claims, regions

router = APIRouter(tags=["regions"])

RegionCode = Annotated[str, Path(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$", description="ISO 3166-2 code, for example IN-TN.")]
Mode = Annotated[DataMode, Query(description="live claims, or labeled demo fixtures; the two are never mixed.")]


@router.get("/regions", response_model=RegionPage)
async def list_regions(
    user: CurrentUser, country_code: CountryCode = "IN", limit: Limit = 100, offset: Offset = 0
) -> RegionPage:
    """Regions of a country (all 36 Indian states and union territories for IN), with their languages."""
    return await regions.list_regions(country_code, limit, offset)


@router.get("/regions/{region_code}", response_model=Region)
async def get_region(region_code: RegionCode, user: CurrentUser) -> Region:
    return await regions.get_region(region_code)


@router.get("/workspaces/{workspace_id}/regions/{region_code}/profile", response_model=RegionProfile)
async def get_region_profile(
    workspace_id: UUID, region_code: RegionCode, user: CurrentUser, mode: Mode = "live"
) -> RegionProfile:
    """The region's claims grouped by category, each with its five tags, plus the Evidence Meter.
    Shows shared reference claims and the workspace's own claims. 404 for a workspace the caller does not belong to."""
    return await claims.build_region_profile(user.id, workspace_id, region_code, mode=mode)


@router.get("/workspaces/{workspace_id}/regions/{region_code}/evidence-meter", response_model=EvidenceMeter)
async def get_evidence_meter(
    workspace_id: UUID, region_code: RegionCode, user: CurrentUser, mode: Mode = "live"
) -> EvidenceMeter:
    """Sources, supported claims, freshness, coverage, open conflicts, stale claims and claims needing review.
    A region with weak evidence is rated weak."""
    return (await claims.build_region_profile(user.id, workspace_id, region_code, mode=mode)).meter
