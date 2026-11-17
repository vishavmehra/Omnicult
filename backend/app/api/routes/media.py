from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.media import MediaCapabilities, RenderTextRequest
from app.schemas.runs import RunAccepted
from app.schemas.xray import Creative, CreativeSummaryPage, Scene, ScenePage, XRayCreate
from app.services import media as media_service
from app.services import xray

router = APIRouter(tags=["media"])


@router.get("/media/capabilities", response_model=MediaCapabilities)
async def get_media_capabilities(user: CurrentUser) -> MediaCapabilities:
    """What this server can process: ffmpeg and ffprobe, complex-script text shaping, bundled fonts, and limits."""
    return await media_service.capabilities()


@router.post("/campaigns/{campaign_id}/creative-xrays", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def start_creative_xray(campaign_id: UUID, body: XRayCreate, user: CurrentUser) -> RunAccepted:
    """Break an uploaded image, video or audio into scenes (run_type creative_xray).

    Honours Idempotency-Key. 409 for an asset of another project or a derived file; 503 when the language model
    provider is not configured. The result is a creative with scenes: fetch it from the run's result URL.
    """
    return await xray.start_xray(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/creatives", response_model=CreativeSummaryPage)
async def list_creatives(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> CreativeSummaryPage:
    """Creatives of a campaign, newest first. Status mirrors each creative's latest X-Ray run."""
    return await xray.list_creatives(user.id, campaign_id, limit, offset)


@router.get("/creatives/{creative_id}", response_model=Creative)
async def get_creative(creative_id: UUID, user: CurrentUser) -> Creative:
    """The creative, its source asset, and what the current X-Ray run found: probe, transcript status, keyframes, limits."""
    return await xray.get_creative(user.id, creative_id)


@router.get("/creatives/{creative_id}/scenes", response_model=ScenePage)
async def list_scenes(
    creative_id: UUID, user: CurrentUser, limit: Limit = 50, offset: Offset = 0, run_id: UUID | None = None
) -> ScenePage:
    """Scenes in time order: those of the current run, or of the run named by `run_id`."""
    return await xray.list_scenes(user.id, creative_id, limit, offset, run_id)


@router.get("/creatives/{creative_id}/scenes/{scene_id}", response_model=Scene)
async def get_scene(creative_id: UUID, scene_id: UUID, user: CurrentUser) -> Scene:
    return await xray.get_scene(user.id, creative_id, scene_id)


@router.post(
    "/projects/{project_id}/media/render-text",
    response_class=Response,
    responses={200: {"description": "The rendered image.", "content": {"image/png": {}}}},
)
async def render_text_preview(project_id: UUID, body: RenderTextRequest, user: CurrentUser) -> Response:
    """Preview regional text drawn in code (Noto fonts, raqm shaping), with locked regions restored pixel for pixel.

    Nothing is stored. 501 for Indic text when complex-script shaping is not installed on the server; the response
    headers report the shaping engine, whether each box fit, and locked-region overlap.
    """
    png, result = await media_service.render_text_preview(user.id, project_id, body)
    return Response(png, media_type="image/png", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Omnicult-Shaping": result.engine,
        "X-Omnicult-Text-Fit": ",".join(str(p.fits).lower() for p in result.placements),
        "X-Omnicult-Overlaps-Locked": ",".join(str(p.overlaps_locked).lower() for p in result.placements),
        "X-Omnicult-Locked-Restored": str(result.locked_restored),
    })
