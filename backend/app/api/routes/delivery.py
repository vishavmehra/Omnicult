"""Launch Room delivery: Review Links, Region Plan and Asset Pack.

The reviewer endpoints (`/review...`) and the pack download take no bearer token: a review link's secret goes in the
Authorization header as `Review <secret>` (never in a URL, so it never reaches an access log), and a pack link carries its own
random token. Everything else follows the workspace rules of the rest of the Launch Room.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status

from app.api.deps import CurrentUser, Limit, Offset
from app.core.errors import NotFound
from app.schemas import delivery as d
from app.services import asset_pack, region_plan, review_links

router = APIRouter(tags=["launch room"])

ReviewAuth = Annotated[
    str | None, Header(alias="Authorization", description="`Review <secret>`: the secret of the review link, as sent to the reviewer.")
]
RegionFilter = Annotated[str, Query(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$", description="ISO 3166-2 region code.")]


def _secret(authorization: str | None) -> str:
    scheme, _, secret = (authorization or "").partition(" ")
    if scheme != "Review" or not 20 <= len(secret) <= 200:
        raise NotFound(review_links.INVALID)
    return secret


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# --- Review Links: owner side ---------------------------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/review-links", response_model=d.ReviewLinkCreated, status_code=status.HTTP_201_CREATED)
async def create_review_link(campaign_id: UUID, body: d.ReviewLinkCreate, user: CurrentUser) -> d.ReviewLinkCreated:
    """Share chosen versions and regions with someone who has no account. Needs the owner or editor role. The response is the
    only time the secret is shown; only its hash is stored. The link expires (at most 30 days) and can be revoked."""
    return await review_links.create_link(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/review-links", response_model=d.ReviewLinkPage)
async def list_review_links(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> d.ReviewLinkPage:
    """Links of the campaign, newest first, with their status and how many decisions each has received."""
    return await review_links.list_links(user.id, campaign_id, limit, offset)


@router.post("/review-links/{link_id}/revoke", response_model=d.ReviewLinkSummary)
async def revoke_review_link(link_id: UUID, user: CurrentUser) -> d.ReviewLinkSummary:
    """Stop a link now. Needs the owner or editor role. Decisions already left on it are kept."""
    return await review_links.revoke_link(user.id, link_id)


@router.get("/campaigns/{campaign_id}/review-responses", response_model=d.ReviewResponsePage)
async def list_review_responses(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, link_id: UUID | None = None, version_id: UUID | None = None
) -> d.ReviewResponsePage:
    """Decisions and comments reviewers left through links, newest first. They are advice: only a signed-in member approves."""
    return await review_links.list_responses(user.id, campaign_id, limit, offset, link_id=link_id, version_id=version_id)


# --- Review Links: reviewer side (no account) -----------------------------------------------------------------------------


@router.get("/review", response_model=d.ReviewPage)
async def open_review(request: Request, authorization: ReviewAuth = None) -> d.ReviewPage:
    """What a review link shows: the chosen versions as plain text, their region and language, and the region's creative files.
    404 for an unknown, expired or revoked link. Rate limited."""
    return await review_links.open_review(_secret(authorization), _client(request))


@router.post("/review/responses", response_model=d.ReviewReceipt, status_code=status.HTTP_201_CREATED)
async def submit_review(body: d.ReviewSubmit, request: Request, authorization: ReviewAuth = None) -> d.ReviewReceipt:
    """Leave a decision or a comment on one version and region of the link. Recorded against that version, anonymous unless the
    reviewer typed a name (never verified). Rate limited; a link accepts a bounded number of responses."""
    return await review_links.submit(_secret(authorization), _client(request), body)


@router.get(
    "/review/creatives/{creative_id}", response_class=Response,
    responses={200: {"description": "The creative file, inline, with a sandboxing Content-Security-Policy.", "content": {"image/*": {}, "video/*": {}, "audio/*": {}}}},
)
async def get_review_creative(creative_id: UUID, request: Request, authorization: ReviewAuth = None) -> Response:
    """One rights-confirmed creative file of a region in the link's scope."""
    return await review_links.creative_file(_secret(authorization), _client(request), creative_id)


# --- Region Plan ------------------------------------------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/region-plan", response_model=d.RegionPlan)
async def get_region_plan(campaign_id: UUID, user: CurrentUser) -> d.RegionPlan:
    """The launch plan per region, assembled by code from the brief, the Moment Calendar, the readiness verdicts, the approvals
    and the stakeholder feedback. Read fresh; nothing is stored and no model is called."""
    return await region_plan.build_plan(user.id, campaign_id)


@router.get(
    "/campaigns/{campaign_id}/region-plan/export", response_class=Response,
    responses={200: {"description": "The plan as a download.", "content": {"text/markdown": {"schema": {"type": "string"}}, "application/pdf": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def export_region_plan(
    campaign_id: UUID, user: CurrentUser, fmt: Annotated[Literal["markdown", "pdf"], Query(alias="format")] = "pdf"
) -> Response:
    """Download the plan as Markdown or PDF (the Proof export code). The PDF shows Indic text as a Latin transliteration."""
    data, media_type, filename, _ = await region_plan.export(user.id, campaign_id, fmt)
    return Response(data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"})


# --- Asset Pack -----------------------------------------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/asset-packs/preview", response_model=d.AssetPackPreview)
async def preview_asset_pack(campaign_id: UUID, region_code: RegionFilter, user: CurrentUser) -> d.AssetPackPreview:
    """What a pack for the region would hold: the approved version, the files that go in and the files left out with the reason."""
    return await asset_pack.preview(user.id, campaign_id, region_code)


@router.post("/campaigns/{campaign_id}/asset-packs", response_model=d.AssetPackCreated, status_code=status.HTTP_201_CREATED)
async def create_asset_pack(campaign_id: UUID, body: d.AssetPackCreate, user: CurrentUser) -> d.AssetPackCreated:
    """Build the ZIP on the server for a region's approved version and return a short-lived download link. Needs the owner or
    editor role; 409 when the region has no standing approval. Only rights-confirmed files go in."""
    return await asset_pack.create_pack(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/asset-packs", response_model=d.AssetPackPage)
async def list_asset_packs(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> d.AssetPackPage:
    """Packs built for the campaign, newest first, with whether each link is still active."""
    return await asset_pack.list_packs(user.id, campaign_id, limit, offset)


@router.get("/asset-packs/{pack_id}", response_model=d.AssetPackDetail)
async def get_asset_pack(pack_id: UUID, user: CurrentUser) -> d.AssetPackDetail:
    """One pack with its manifest (provenance and checksums)."""
    return await asset_pack.get_pack(user.id, pack_id)


@router.get("/asset-packs/{pack_id}/download", response_class=Response, responses={200: {"description": "The ZIP.", "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}})
async def download_asset_pack(pack_id: UUID, token: Annotated[str, Query(min_length=20, max_length=200)]) -> Response:
    """Download with the link's token instead of a bearer token. 404 for an unknown pack, a wrong token or an expired link."""
    return await asset_pack.download(pack_id, token)
