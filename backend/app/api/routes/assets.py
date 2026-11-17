from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Response, UploadFile, status

from app.api.deps import CurrentUser, Limit, Offset
from app.media.sidecar import MAX_SIDECAR_BYTES
from app.schemas.assets import Asset, AssetKind, AssetPage, AssetStatus, AssetUrl
from app.services import assets as service

router = APIRouter(tags=["assets"])


@router.post("/projects/{project_id}/assets", status_code=status.HTTP_201_CREATED, response_model=Asset)
async def upload_asset(
    project_id: UUID,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
    kind: Annotated[AssetKind, Form()],
    rights_confirmed: Annotated[bool, Form(description="Required for video and audio: you hold the rights to this file.")] = False,
    sidecar: Annotated[
        UploadFile | None, File(description="Optional UTF-8 SRT, WebVTT or plain-text notes for a video or audio upload.")
    ] = None,
) -> Asset:
    """Upload an image (5 MB), or a video (MP4, MOV, WebM) or audio (MP3, WAV, M4A) of at most 50 MB and 60 seconds.

    Type and size are checked from the file's bytes; video and audio need `rights_confirmed` and ffprobe. A text sidecar
    and the container's metadata are redacted of emails and phone numbers before any model can use them.
    """
    data = await file.read(service.max_bytes(kind) + 1)  # bounded read; oversize is rejected by the service
    side = await sidecar.read(MAX_SIDECAR_BYTES + 1) if sidecar is not None else None
    return await service.upload_asset(user.id, project_id, kind, file.filename, data, rights_confirmed=rights_confirmed, sidecar=side)


@router.get("/projects/{project_id}/assets", response_model=AssetPage)
async def list_assets(
    project_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, kind: AssetKind | None = None,
    include_derived: bool = False,
) -> AssetPage:
    """Uploads, newest first. Keyframes, thumbnails and audio tracks derived from an upload are hidden unless asked for."""
    return await service.list_assets(user.id, project_id, limit, offset, kind, include_derived)


@router.get("/assets/{asset_id}", response_model=Asset)
async def get_asset(asset_id: UUID, user: CurrentUser) -> Asset:
    return await service.get_asset(user.id, asset_id)


@router.get("/assets/{asset_id}/status", response_model=AssetStatus)
async def get_asset_status(asset_id: UUID, user: CurrentUser) -> AssetStatus:
    """Upload and processing status, the redaction counts, and the files derived from the asset."""
    return await service.asset_status(user.id, asset_id)


@router.get("/assets/{asset_id}/url", response_model=AssetUrl)
async def get_asset_url(asset_id: UUID, user: CurrentUser) -> AssetUrl:
    """A short-lived signed URL for a Cloud Storage object, or the authenticated stream path (local and database storage)."""
    return await service.asset_url(user.id, asset_id)


@router.get(
    "/assets/{asset_id}/content",
    response_class=Response,
    responses={200: {"description": "The file bytes.", "content": {"image/*": {}, "video/*": {}, "audio/*": {}}}},
)
async def get_asset_content(asset_id: UUID, user: CurrentUser) -> Response:
    return await service.asset_content(user.id, asset_id)
