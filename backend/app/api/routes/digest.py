"""Live Pulse: Comment Pulse (feature 46), Weekly Digest (feature 48), and the Cloud Scheduler entry point of the digest.

Comment Pulse runs on the labelled sample comments (no channel can be connected in this build); counts and trends are
computed by code, sentiment and themes are a model interpretation. The Weekly Digest is generated from stored records,
stored one per campaign and ISO week, and exported to Markdown or PDF. Nothing is sent outbound.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import CurrentUser
from app.core.scheduler_auth import require_scheduler
from app.schemas import comment_pulse as cv
from app.schemas import digest as dv
from app.services import comment_pulse, digest

router = APIRouter(tags=["digest"])
COMMENTS = "/campaigns/{campaign_id}/pulse/comments"
DIGESTS = "/campaigns/{campaign_id}/pulse/digests"

Region = Annotated[str | None, Query(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$", description="ISO 3166-2 code, for example IN-TN.")]
Version = Annotated[str | None, Query(max_length=120, description="A version label exactly as Live Pulse lists it.")]
Language = Annotated[str | None, Query(pattern=r"^[a-z]{2}$", description="ISO 639-1 code, for example ta.")]
DateFrom = Annotated[date | None, Query(description="First day, inclusive.")]
DateTo = Annotated[date | None, Query(description="Last day, inclusive.")]


# --- Comment Pulse ---------------------------------------------------------------------------------------------


@router.get(COMMENTS + "/status", response_model=cv.CommentDatasetStatus)
async def get_comment_status(campaign_id: UUID, user: CurrentUser) -> cv.CommentDatasetStatus:
    return await comment_pulse.dataset_status(user.id, campaign_id)


@router.post(COMMENTS + "/sample", response_model=cv.CommentDatasetStatus)
async def load_sample_comments(campaign_id: UUID, user: CurrentUser) -> cv.CommentDatasetStatus:
    """Explicit action: load, or reload, the deterministic sample comments for this campaign (owner or editor).
    Reloading replaces them with identical rows; stored model readings are kept."""
    return await comment_pulse.load_sample(user.id, campaign_id)


@router.get(COMMENTS + "/summary", response_model=cv.CommentSummary)
async def get_comment_summary(
    campaign_id: UUID, user: CurrentUser, region: Region = None, version: Version = None, language: Language = None,
    date_from: DateFrom = None, date_to: DateTo = None,
) -> cv.CommentSummary:
    """Counts, language mix, daily and weekly trends and per region-and-version slices, all computed by code.
    Sentiment shares come from the newest model reading, when one exists."""
    return await comment_pulse.summary(user.id, campaign_id, comment_pulse.Filters(region, version, language, date_from, date_to))


@router.get(COMMENTS + "/themes", response_model=cv.CommentThemes)
async def get_comment_themes(
    campaign_id: UUID, user: CurrentUser, region: Region = None, version: Version = None, language: Language = None,
    date_from: DateFrom = None, date_to: DateTo = None,
) -> cv.CommentThemes:
    """The model's themes with counts and verbatim example comments, both chosen by code. Empty until a reading exists."""
    return await comment_pulse.themes(user.id, campaign_id, comment_pulse.Filters(region, version, language, date_from, date_to))


@router.get(COMMENTS, response_model=cv.CommentPage)
async def list_comments(
    campaign_id: UUID, user: CurrentUser, region: Region = None, version: Version = None, language: Language = None,
    date_from: DateFrom = None, date_to: DateTo = None,
    sentiment: Annotated[cv.SentimentLabel | None, Query(description="From the model reading.")] = None,
    theme: Annotated[str | None, Query(max_length=40, description="A theme id from /themes.")] = None,
    flag: Annotated[cv.FlagFilter | None, Query(description="Only comments that match a watch term.")] = None,
    sort: Annotated[cv.CommentSort, Query()] = "likes",
    limit: Annotated[int, Query(ge=1, le=100)] = 25, offset: Annotated[int, Query(ge=0)] = 0,
) -> cv.CommentPage:
    """Comments with their language, version anchor, watch-term matches and, when read, the model's sentiment and themes."""
    f = comment_pulse.Filters(region, version, language, date_from, date_to, sentiment, theme, flag)
    return await comment_pulse.list_comments(user.id, campaign_id, f, sort=sort, limit=limit, offset=offset)


@router.post(COMMENTS + "/read", response_model=cv.CommentReadResult)
async def read_comments(campaign_id: UUID, user: CurrentUser, body: cv.CommentReadRequest | None = None) -> cv.CommentReadResult:
    """Label sentiment and group themes: one model call in a live project, labelled fixtures in a demo project.
    The newest reading is reused unless `force` is set (owner or editor)."""
    return await comment_pulse.read(user.id, campaign_id, bool(body and body.force))


# --- Weekly Digest ---------------------------------------------------------------------------------------------


@router.get(DIGESTS, response_model=dv.DigestList)
async def list_digests(campaign_id: UUID, user: CurrentUser) -> dv.DigestList:
    """Stored digests, newest week first."""
    return await digest.list_digests(user.id, campaign_id)


@router.post(DIGESTS, response_model=dv.DigestCreated)
async def create_digest(campaign_id: UUID, user: CurrentUser, body: dv.DigestCreate | None = None) -> dv.DigestCreated:
    """Generate the digest of a week from stored records (owner or editor). A week that already has one returns it
    unchanged (`created` false); `regenerate` replaces it. No model is called."""
    return await digest.create_digest(user.id, campaign_id, body or dv.DigestCreate())


@router.get(DIGESTS + "/{digest_id}", response_model=dv.Digest)
async def get_digest(campaign_id: UUID, digest_id: UUID, user: CurrentUser) -> dv.Digest:
    return await digest.get_digest(user.id, campaign_id, digest_id)


@router.post(DIGESTS + "/{digest_id}/summary", response_model=dv.Digest)
async def add_digest_summary(campaign_id: UUID, digest_id: UUID, user: CurrentUser) -> dv.Digest:
    """Ask a model for a short summary of the stored digest (live projects only; 409 in a demo project). Code rejects the
    summary when it contains a number the digest does not hold."""
    return await digest.add_narrative(user.id, campaign_id, digest_id)


@router.get(DIGESTS + "/{digest_id}/export", response_class=Response, responses={200: {"description": "The digest as a file."}})
async def export_digest(
    campaign_id: UUID, digest_id: UUID, user: CurrentUser, fmt: Annotated[dv.ExportFormat, Query(alias="format")] = "md",
) -> Response:
    """Download the digest as Markdown or PDF, rendered by the Proof Report exporters. Nothing is sent anywhere."""
    exported = await digest.export(user.id, campaign_id, digest_id, fmt)
    return Response(
        exported.data, media_type=exported.media_type,
        headers={"Content-Disposition": f'attachment; filename="{exported.filename}"', "Cache-Control": "private, no-store"})


# --- Cloud Scheduler ---------------------------------------------------------------------------------------------


@router.post("/internal/digest/generate-weekly", response_model=dv.SchedulerRun, include_in_schema=False)
async def generate_weekly_digests(
    response: Response, _caller: Annotated[str, Depends(require_scheduler)], body: dv.SchedulerRequest | None = None,
) -> dv.SchedulerRun:
    """Called by Cloud Scheduler with a Google OIDC ID token for the configured service account and audience (anything else
    is refused). Generates one digest per active campaign for the last completed ISO week; idempotent per week. A failed
    campaign makes the response 500 so the scheduler retries; the retry only does what is missing."""
    result = await digest.generate_weekly(week_day=body.week_of if body else None)
    if result.failed:
        response.status_code = 500
    return result
