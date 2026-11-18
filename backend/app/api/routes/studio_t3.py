"""Creative Studio, Tier 3: Format Fit, Claim Guard and Script Check.

All three read a version of the campaign's version tree and are authorized like the rest of Studio (a stranger gets 404, a
viewer or reviewer cannot write). Format Fit plans and Script Check only read; applying a plan, running a check and
recording a review are the writes. Nothing here is legal clearance: Claim Guard findings are warnings for human review.
"""

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas import studio_t3 as t
from app.services import claim_guard, format_fit, script_check

router = APIRouter(tags=["creative-studio-tier3"])

# --- Format Fit -----------------------------------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/format-fit/formats", response_model=t.FormatFitCatalogue)
async def format_fit_formats(campaign_id: UUID, user: CurrentUser) -> t.FormatFitCatalogue:
    """The channel formats Format Fit plans for (1:1, 4:5, 9:16, 16:9) with their working safe zones, and the formats the
    Campaign Brief's channels run in."""
    return await format_fit.catalogue(user.id, campaign_id)


@router.post("/campaigns/{campaign_id}/format-fit/plans", response_model=t.FormatFitPlans)
async def format_fit_plans(campaign_id: UUID, body: t.FormatFitPlanRequest, user: CurrentUser) -> t.FormatFitPlans:
    """Plan a creative of this campaign for each format: crop window or padding, what is cut, safe-zone and text-size
    problems, locked-region conflicts. For a video: cut-down suggestions from its scene timings. Deterministic, stores nothing."""
    return await format_fit.plan(user.id, campaign_id, body)


@router.post("/campaigns/{campaign_id}/format-fit/outputs", status_code=status.HTTP_201_CREATED, response_model=t.FormatFitOutput)
async def format_fit_apply(campaign_id: UUID, body: t.FormatFitApply, user: CurrentUser) -> t.FormatFitOutput:
    """Make the picture a plan describes and store it as a new asset. The plan is recomputed on the server. 409 when it would
    cut a locked element, or has conflicts that were not acknowledged. The source asset is never changed."""
    return await format_fit.apply(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/format-fit/outputs", response_model=t.FormatFitOutputPage)
async def format_fit_outputs(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 50, offset: Offset = 0, creative_id: UUID | None = None
) -> t.FormatFitOutputPage:
    """Pictures made by Format Fit, newest first."""
    return await format_fit.list_outputs(user.id, campaign_id, limit, offset, creative_id)


# --- Script Check ---------------------------------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/versions/{version_id}/script-check", response_model=t.ScriptReport)
async def script_check_report(campaign_id: UUID, version_id: UUID, user: CurrentUser) -> t.ScriptReport:
    """Every text element of a version, checked in code for script, mixed scripts, numerals, joiners, Brand Glossary spellings
    and protected or prohibited terms, with a character span for each issue. Nothing is stored and no model is called."""
    return await script_check.script_report(user.id, campaign_id, version_id)


# --- Claim Guard ----------------------------------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/claim-guard/checks", status_code=status.HTTP_201_CREATED, response_model=t.ClaimGuardCheck)
async def claim_guard_run(campaign_id: UUID, body: t.ClaimGuardRun, user: CurrentUser) -> t.ClaimGuardCheck:
    """Find the claims in a version's copy (wording rules first; with `include_model_pass`, a model second pass whose quotes are
    verified in code), grade each against the Brand Kit claims policy, the campaign's evidence and the ASCI index, and store the check."""
    return await claim_guard.run_check(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/claim-guard/checks", response_model=t.ClaimGuardCheckPage)
async def claim_guard_checks(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, version_id: UUID | None = None
) -> t.ClaimGuardCheckPage:
    """Stored checks, newest first, with how many findings still wait for a person's review."""
    return await claim_guard.list_checks(user.id, campaign_id, limit, offset, version_id)


@router.get("/campaigns/{campaign_id}/claim-guard/checks/{check_id}", response_model=t.ClaimGuardCheck)
async def claim_guard_check(campaign_id: UUID, check_id: UUID, user: CurrentUser) -> t.ClaimGuardCheck:
    return await claim_guard.get_check(user.id, campaign_id, check_id)


@router.put("/campaigns/{campaign_id}/claim-guard/reviews", response_model=t.ClaimGuardReview)
async def claim_guard_review(campaign_id: UUID, body: t.ClaimGuardReviewRequest, user: CurrentUser) -> t.ClaimGuardReview:
    """Record a person's decision about one finding of a version. Replaces an earlier decision about the same finding."""
    return await claim_guard.review_finding(user.id, campaign_id, body)
