"""Market Lens Tier 3: Trend Radar (rising and falling public attention) and Category Shelf (brands and products Wikidata records
in the campaign's category). Campaign-scoped like the rest of Market Lens: the campaign's brand decides demo (recorded fixtures,
no network call) or live (Wikimedia and Wikidata, polite and rate-limited)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser
from app.schemas import lens_t3 as v
from app.services import lens, lens_shelf, lens_trends

router = APIRouter(prefix="/campaigns/{campaign_id}/lens", tags=["lens"])

RegionQuery = Annotated[
    list[Annotated[str, Query(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")]] | None,
    Query(description="Repeat for each state (ISO 3166-2:IN). Default: the campaign's states."),
]


@router.get("/trend-radar", response_model=v.LensTrendRadar)
async def get_trend_radar(campaign_id: UUID, user: CurrentUser, region_code: RegionQuery = None) -> v.LensTrendRadar:
    """Trend Radar: for each state, which public attention is rising or falling, computed from stored Wikipedia pageviews with
    the window and method stated, plus the moments in the campaign's dates. Attention, never search volume or demand. Reads
    never call a source; they show what a refresh stored."""
    return await lens_trends.get_radar(await lens.lens_context(user.id, campaign_id), region_code)


@router.post("/trend-radar/refresh", response_model=v.LensTrendRadar)
async def refresh_trend_radar(campaign_id: UUID, body: v.LensTrendRefreshRequest, user: CurrentUser) -> v.LensTrendRadar:
    """Read the pageviews again and keep the new readings next to the old ones. Owner or editor role.

    Demo campaigns read the recording and make no network call. Live campaigns call free public APIs: a state refreshed less
    than LENS_TREND_MIN_INTERVAL_SECONDS ago answers 429, and a source that fails is reported in that state's `gaps`."""
    return await lens_trends.refresh_radar(user.id, campaign_id, body)


@router.get("/category-shelf", response_model=v.LensShelf)
async def get_category_shelf(
    campaign_id: UUID, user: CurrentUser, region_code: RegionQuery = None,
    pack_key: Annotated[str | None, Query(max_length=60, description="Read a category other than the one the brand kit names.")] = None,
) -> v.LensShelf:
    """Category Shelf: the brands and products Wikidata records in the campaign's category, by the state it links them to, with
    public signals. Unknown fields stay unknown; nothing about price, sales or share is ever shown."""
    return await lens_shelf.get_shelf(await lens.lens_context(user.id, campaign_id), region_code, pack_key)


@router.post("/category-shelf/refresh", response_model=v.LensShelf)
async def refresh_category_shelf(campaign_id: UUID, body: v.LensShelfRefreshRequest, user: CurrentUser) -> v.LensShelf:
    """Discover the category again and keep the result as a new version. Owner or editor role.

    Demo campaigns read the recording. Live campaigns make about a dozen free Wikidata requests, then read pageviews for the
    best-referenced items; the same category is not read again within LENS_SHELF_MIN_INTERVAL_SECONDS (429)."""
    return await lens_shelf.refresh_shelf(user.id, campaign_id, body)
