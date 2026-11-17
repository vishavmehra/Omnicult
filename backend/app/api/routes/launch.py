from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, Limit, Offset, RegisteredUser
from app.schemas import launch as v
from app.services import launch

router = APIRouter(tags=["launch room"])
RegionFilter = Annotated[str | None, Query(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$", description="ISO 3166-2 region code.")]


@router.post("/campaigns/{campaign_id}/scores/compare", response_model=v.ScoreComparison)
async def compare_scores(campaign_id: UUID, body: v.ScoreCompareRequest, user: CurrentUser) -> v.ScoreComparison:
    """Compare 2-4 versions in one region under scoring version mvp-2. The scores are computed by fixed rules from the
    supplied observations; nothing is stored and no model is called. Every dimension lists its rules and inputs, and the
    comparability block discloses any difference in model, prompt, criteria or evidence between the versions."""
    return await launch.compare_scores(user.id, campaign_id, body)


@router.post(
    "/campaigns/{campaign_id}/readiness", response_model=v.ReadinessVerdict, status_code=status.HTTP_201_CREATED,
    responses={200: {"model": v.ReadinessVerdict, "description": "Identical inputs: the newest stored verdict."}},
)
async def compute_readiness(
    campaign_id: UUID, body: v.ReadinessRequest, user: CurrentUser, response: Response
) -> v.ReadinessVerdict:
    """Compute the Go / Fix / Rethink recommendation for one version in one region and store it with its history.
    Needs the owner or editor role. The verdict is a recommendation only; it never approves anything."""
    verdict, created = await launch.compute_readiness(user.id, campaign_id, body)
    if not created:
        response.status_code = status.HTTP_200_OK
    return verdict


@router.get("/campaigns/{campaign_id}/readiness", response_model=v.ReadinessBoard)
async def get_readiness_board(campaign_id: UUID, user: CurrentUser) -> v.ReadinessBoard:
    """The Readiness Board: the newest verdict for each version, grouped by region, with the latest human decision."""
    return await launch.readiness_board(user.id, campaign_id)


@router.get("/campaigns/{campaign_id}/readiness/history", response_model=v.ReadinessPage)
async def list_readiness_history(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, region_code: RegionFilter = None,
    version_id: UUID | None = None,
) -> v.ReadinessPage:
    """Every stored verdict, newest first, optionally for one region and version."""
    return await launch.readiness_history(
        user.id, campaign_id, region_code=region_code, version_id=version_id, limit=limit, offset=offset
    )


@router.get("/campaigns/{campaign_id}/readiness/rules", response_model=v.ReadinessRules)
async def get_readiness_rules(campaign_id: UUID, user: CurrentUser) -> v.ReadinessRules:
    """The documented verdict rules, thresholds and priorities in force (rule version and scoring version)."""
    await launch.authorize_read(user.id, campaign_id)
    return launch.readiness_rules_doc()


@router.post("/campaigns/{campaign_id}/approvals", response_model=v.Approval, status_code=status.HTTP_201_CREATED)
async def record_approval(campaign_id: UUID, body: v.ApprovalCreate, user: RegisteredUser) -> v.Approval:
    """Record a person's decision (approve, reject, request changes) on a version for a region, with a reason.
    Needs the owner, editor or reviewer role (403 for viewers). The decision and the readiness recommendation in force
    are stored; approving against a non-Go recommendation is allowed and is flagged `overrides_recommendation`."""
    return await launch.record_approval(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/approvals", response_model=v.ApprovalPage)
async def list_approvals(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, region_code: RegionFilter = None,
    version_id: UUID | None = None,
) -> v.ApprovalPage:
    """Human decisions, newest first, optionally for one region and version."""
    return await launch.list_approvals(
        user.id, campaign_id, region_code=region_code, version_id=version_id, limit=limit, offset=offset
    )
