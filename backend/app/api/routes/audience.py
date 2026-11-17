"""Audience Lab: Quick Read, Audience Study, Ask the Panel and Risk Check (Omnicult).

Runs start with 202 and finish in the background; poll the result resource. Send an Idempotency-Key header on the POST that
starts a run so a retry returns the run it already created. Every participant and answer is synthetic. Risk Check findings
are for human review and are never legal clearance.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, Limit, Offset
from app.core.errors import NotFound
from app.reference.ad_codes import AdCodeEntry, AdCodeIndex, get_entry, load_index
from app.schemas import audience as v
from app.services import audience

router = APIRouter(tags=["audience-lab"])


@router.get("/audience-lab/sampling-options", response_model=v.SamplingOptions)
async def get_sampling_options(user: CurrentUser) -> v.SamplingOptions:
    """The only dimensions a panel may be sampled by, their values, the protected traits that are refused, and the limits."""
    return audience.sampling_options()


@router.get("/ad-codes", response_model=AdCodeIndex)
async def get_ad_code_index(user: CurrentUser) -> AdCodeIndex:
    """The ad-code reference index: exact, cited excerpts of the public ASCI code. A partial index, not legal advice."""
    return load_index()


@router.get("/ad-codes/{entry_id}", response_model=AdCodeEntry)
async def get_ad_code(entry_id: str, user: CurrentUser) -> AdCodeEntry:
    entry = get_entry(entry_id)
    if entry is None:
        raise NotFound("Ad-code entry was not found.")
    return entry


# --- Quick Read ----------------------------------------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/quick-reads", status_code=status.HTTP_202_ACCEPTED, response_model=v.AudienceRunAccepted)
async def start_quick_read(campaign_id: UUID, body: v.QuickReadCreate, user: CurrentUser) -> v.AudienceRunAccepted:
    """Run a small synthetic panel on one creative version for one region, grounded in the region's claims."""
    return await audience.start_quick_read(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/quick-reads", response_model=v.AudienceRunPage)
async def list_quick_reads(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> v.AudienceRunPage:
    return await audience.list_runs(user.id, campaign_id, "quick_read", limit, offset)


@router.get("/campaigns/{campaign_id}/quick-reads/{run_id}", response_model=v.QuickReadResult)
async def get_quick_read(campaign_id: UUID, run_id: UUID, user: CurrentUser) -> v.QuickReadResult:
    return await audience.get_result(user.id, campaign_id, run_id, "quick_read")


# --- Audience Study ------------------------------------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/audience-studies", status_code=status.HTTP_202_ACCEPTED, response_model=v.AudienceRunAccepted)
async def start_audience_study(campaign_id: UUID, body: v.AudienceStudyCreate, user: CurrentUser) -> v.AudienceRunAccepted:
    """A bounded synthetic study (20 participants up to the server limit) sampled by state, language, city tier and age band."""
    return await audience.start_audience_study(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/audience-studies", response_model=v.AudienceRunPage)
async def list_audience_studies(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> v.AudienceRunPage:
    return await audience.list_runs(user.id, campaign_id, "audience_study", limit, offset)


@router.get("/campaigns/{campaign_id}/audience-studies/{run_id}", response_model=v.AudienceStudyResult)
async def get_audience_study(campaign_id: UUID, run_id: UUID, user: CurrentUser) -> v.AudienceStudyResult:
    return await audience.get_result(user.id, campaign_id, run_id, "audience_study")


# --- Ask the Panel -------------------------------------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/panels/{run_id}/participants", response_model=v.PanelParticipantPage)
async def list_panel_participants(
    campaign_id: UUID, run_id: UUID, user: CurrentUser, limit: Limit = 100, offset: Offset = 0
) -> v.PanelParticipantPage:
    """The panel of a Quick Read or Audience Study run (run_id is that run's id)."""
    return await audience.list_participants(user.id, campaign_id, run_id, limit, offset)


@router.post("/campaigns/{campaign_id}/panels/{run_id}/questions", status_code=status.HTTP_201_CREATED, response_model=v.PanelQuestion)
async def ask_the_panel(campaign_id: UUID, run_id: UUID, body: v.AskPanelCreate, user: CurrentUser) -> v.PanelQuestion:
    """Ask one participant, a subgroup (by state, language, city tier, age band) or the whole panel. Answers come from each
    participant's stored response and earlier answers. 409 when the panel has no usable responses."""
    return await audience.ask_panel(user.id, campaign_id, run_id, body)


@router.get("/campaigns/{campaign_id}/panels/{run_id}/questions", response_model=v.PanelQuestionPage)
async def list_panel_questions(
    campaign_id: UUID, run_id: UUID, user: CurrentUser,
    participant_id: Annotated[UUID | None, Query(description="Only questions this participant answered.")] = None,
    limit: Limit = 20, offset: Offset = 0,
) -> v.PanelQuestionPage:
    return await audience.list_questions(user.id, campaign_id, run_id, participant_id, limit, offset)


# --- Risk Check ----------------------------------------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/risk-checks", status_code=status.HTTP_202_ACCEPTED, response_model=v.AudienceRunAccepted)
async def start_risk_check(campaign_id: UUID, body: v.RiskCheckCreate, user: CurrentUser) -> v.AudienceRunAccepted:
    """Check a creative's elements against the region's claims and the ASCI ad-code index. Screening for human review only."""
    return await audience.start_risk_check(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/risk-checks", response_model=v.AudienceRunPage)
async def list_risk_checks(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> v.AudienceRunPage:
    return await audience.list_runs(user.id, campaign_id, "risk_check", limit, offset)


@router.get("/campaigns/{campaign_id}/risk-checks/{run_id}", response_model=v.RiskCheckResult)
async def get_risk_check(campaign_id: UUID, run_id: UUID, user: CurrentUser) -> v.RiskCheckResult:
    return await audience.get_result(user.id, campaign_id, run_id, "risk_check")


@router.get("/campaigns/{campaign_id}/risk-checks/{run_id}/findings", response_model=v.RiskFindingPage)
async def list_risk_check_findings(
    campaign_id: UUID, run_id: UUID, user: CurrentUser,
    finding_status: Annotated[v.FindingStatus | None, Query(alias="status")] = None,
    severity: Annotated[v.Severity | None, Query()] = None,
    category: Annotated[v.RiskCategory | None, Query()] = None,
    limit: Limit = 50, offset: Offset = 0,
) -> v.RiskFindingPage:
    return await audience.list_findings(
        user.id, campaign_id, run_id, status=finding_status, severity=severity, category=category, limit=limit, offset=offset)


@router.patch("/campaigns/{campaign_id}/risk-checks/{run_id}/findings/{finding_id}", response_model=v.RiskFinding)
async def update_risk_check_finding(
    campaign_id: UUID, run_id: UUID, finding_id: UUID, body: v.RiskFindingUpdate, user: CurrentUser
) -> v.RiskFinding:
    """Record a person's decision: accepted, dismissed (with a reason), fixed, or open again. Severity and blocks_go never change."""
    return await audience.update_finding(user.id, campaign_id, run_id, finding_id, body)
