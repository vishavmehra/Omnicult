"""Market Lens search pulse: what a state searches for, from Google's public Trends dataset (BigQuery). Campaign-scoped reads
and an owner/editor refresh. Cloud Scheduler's daily refresh lives in `routes/state_facts.py` (`/internal/signals/refresh`)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from app.api.deps import CurrentUser
from app.schemas import lens_t3 as v
from app.services import lens, lens_search_pulse

router = APIRouter(tags=["lens"])

RegionPath = Annotated[str, Path(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$", description="ISO 3166-2:IN code, for example IN-TN.")]
BASE = "/campaigns/{campaign_id}/lens/regions/{code}/search-pulse"


@router.get(BASE, response_model=v.LensSearchPulse)
async def get_search_pulse(campaign_id: UUID, code: RegionPath, user: CurrentUser) -> v.LensSearchPulse:
    """The state's top and rising search terms of the latest week, with the weeks kept for each, as the dataset gives them.
    Live reads serve the stored snapshot and query BigQuery only when none is newer than 24 hours (failures: 429 quota, 502
    permission, 503 not configured, each with a `reason` detail). Demo campaigns read the recording."""
    return await lens_search_pulse.get_pulse(await lens.lens_context(user.id, campaign_id), code)


@router.post(BASE + "/refresh", response_model=v.LensSearchPulse)
async def refresh_search_pulse(campaign_id: UUID, code: RegionPath, user: CurrentUser) -> v.LensSearchPulse:
    """Look for a newer dataset partition now and store it for every state. Owner or editor role. A partition that is already
    stored is not queried again, so repeating this costs nothing."""
    return await lens_search_pulse.refresh_pulse(user.id, campaign_id, code)
