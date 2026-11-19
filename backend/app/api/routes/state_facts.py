"""State facts: official state-wise statistics (data.gov.in) for a state, with the all-India figure beside it.

Campaign-scoped like the rest of Market Lens: the campaign's brand decides demo (a recorded snapshot, no network call) or live
(the stored snapshot, pulled when missing or older than the dataset's cadence). The internal route is for Cloud Scheduler."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response

from app.api.deps import CurrentUser
from app.core.scheduler_auth import require_scheduler
from app.schemas import state_facts as v
from app.services import lens, state_facts

router = APIRouter(tags=["lens"])

RegionPath = Annotated[str, Path(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$", description="ISO 3166-2:IN code, for example IN-TN.")]
FACTS_URL = "/campaigns/{campaign_id}/lens/regions/{region_code}/state-facts"


@router.get(FACTS_URL, response_model=v.StateFacts)
async def get_state_facts(campaign_id: UUID, region_code: RegionPath, user: CurrentUser) -> v.StateFacts:
    """State facts: literacy, urban share, phone and internet use, income and spending for one state, each with its period and
    the all-India figure where the dataset has one. 503 when the live data key is missing, 429 when its quota is used up and
    502 or 504 when the service is down, each only when no stored copy can be served."""
    return await state_facts.get_state_facts(await lens.lens_context(user.id, campaign_id), region_code)


@router.post(FACTS_URL + "/refresh", response_model=v.StateFacts)
async def refresh_state_facts(campaign_id: UUID, region_code: RegionPath, user: CurrentUser) -> v.StateFacts:
    """Check every dataset now and store what changed (an unchanged dataset costs one small request). Owner or editor role.
    Demo campaigns have nothing to pull. A minute's gap between refreshes (429)."""
    return await state_facts.refresh_for_user(user.id, campaign_id, region_code)


@router.post("/internal/datagov/refresh", response_model=v.StateFactsRefreshSummary, tags=["internal"], include_in_schema=False)
async def refresh_for_scheduler(response: Response, _caller: Annotated[str, Depends(require_scheduler)]) -> v.StateFactsRefreshSummary:
    """Called by Cloud Scheduler with a Google OIDC ID token for the configured service account and audience (anything else is
    refused). Re-pulls every dataset whose source changed; idempotent. A failed dataset makes the response 500 so the scheduler
    retries; the retry only repeats what is missing or changed."""
    summary = await state_facts.refresh_scheduled()
    if summary.failed:
        response.status_code = 500
    return summary
