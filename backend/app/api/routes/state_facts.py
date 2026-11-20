"""State facts: official state-wise statistics (data.gov.in and Google Data Commons) for a state, with the all-India figure beside it.

Campaign-scoped like the rest of Market Lens: the campaign's brand decides demo (a recorded snapshot, no network call) or live
(the stored snapshot, pulled when missing or older than the source's cadence). The internal route is Cloud Scheduler's
daily refresh of every stored public-data signal."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.core.errors import AppError, ProviderNotConfigured
from app.core.scheduler_auth import require_scheduler
from app.schemas import state_facts as v
from app.services import lens, lens_moments, lens_search_pulse, state_facts

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


@router.post("/internal/signals/refresh", include_in_schema=False)
async def refresh_signals_for_scheduler(response: Response, _caller: Annotated[str, Depends(require_scheduler)]) -> dict[str, Any]:
    """Called once a day by Cloud Scheduler with a Google OIDC ID token for the configured service account and audience
    (anything else is refused). Refreshes each configured public-data signal: Search pulse (Google Trends in BigQuery) and
    State facts (Google Data Commons live; data.gov.in when its key is mounted). Both are idempotent, so a retry repeats only
    what is missing or changed. A failed source makes the call fail (Search pulse with its typed error, State facts with 500) so the scheduler retries; one source failing never
    stops the other."""
    pulse, pulse_error = None, None
    try:
        pulse = await lens_search_pulse.refresh_scheduled()
    except ProviderNotConfigured:
        pass  # no BigQuery project on this server: nothing to refresh
    except AppError as error:
        pulse_error = error
    facts = await state_facts.refresh_scheduled()  # None when no State facts source has a key on this server
    calendar, calendar_failed = None, False
    if get_settings().google_public_api_key:  # Moment Calendar: Google's Holidays in India, this year and the next
        try:
            calendar = await lens_moments.refresh_scheduled()
        except lens_moments.CalendarSourceError as error:
            calendar_failed, calendar = True, {"error": error.kind}
    if pulse_error is not None:
        raise pulse_error
    if (facts is not None and facts.failed) or calendar_failed:
        response.status_code = 500
    return {"search_pulse": pulse and pulse.model_dump(mode="json"), "state_facts": facts and facts.model_dump(mode="json"),
            "moment_calendar": calendar}
