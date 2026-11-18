"""Uploaded creatives (images, short video and audio, files derived from them) and the visual observations a vision
model reports about images."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import ApiModel, Page

AssetKind = Literal["image", "video", "audio"]
UploadStatus = Literal["stored", "failed"]
ProcessingStatus = Literal["not_required", "pending", "processing", "ready", "failed"]
DerivedRole = Literal[
    "keyframe", "thumbnail", "audio_track",
    "remake_plate", "remake_visual", "remake_voiceover", "remake_music",
    "generate_image", "generate_voice", "generate_jingle",
]  # mirrors DERIVED_ROLES in app/db/models.py


class Asset(ApiModel):
    id: UUID
    project_id: UUID
    kind: AssetKind
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime
    content_url: str = Field(description="Authenticated API path that streams the file.")
    upload_status: UploadStatus
    processing_status: ProcessingStatus = Field(description="not_required for plain images; ffmpeg work for video and audio.")
    processing_error: str | None
    rights_confirmed: bool = Field(description="The uploader confirmed they hold the rights to use this file.")
    duration_ms: int | None = Field(description="Video and audio length; null for images.")
    width: int | None
    height: int | None
    parent_asset_id: UUID | None = Field(description="Set on files derived from an upload (keyframes, thumbnails, audio track).")
    derived_role: DerivedRole | None
    derived_at_ms: int | None = Field(description="Position of a keyframe in its parent video.")


class AssetPage(Page[Asset]):
    pass


class VisualObservation(ApiModel):
    """Something visibly present in an image, as reported by a vision model. Not an interpretation."""

    id: str
    asset_id: UUID
    kind: Literal["object", "text_in_image", "symbol", "person", "color_or_layout", "other"]
    description: str
    location: str | None = Field(description="Approximate position such as top-left; null when not reported.")


class VisionStatus(ApiModel):
    status: Literal["analyzed", "not_requested", "unavailable", "failed"]
    provider: str | None
    model_id: str | None
    message: str | None = Field(
        description="Why vision was unavailable or failed. Images are never passed to a text-only model instead."
    )


class DerivedAsset(ApiModel):
    id: UUID
    role: DerivedRole
    derived_at_ms: int | None
    content_type: str
    size_bytes: int
    content_url: str


class SidecarStatus(ApiModel):
    present: bool
    format: Literal["srt", "vtt", "text"] | None = None
    redacted: dict[str, int] = Field(description="Emails and phone numbers removed from the sidecar before any model use, by kind.")


class AssetStatus(ApiModel):
    """Where an asset is in upload and processing, and the files derived from it."""

    asset_id: UUID
    kind: AssetKind
    upload_status: UploadStatus
    processing_status: ProcessingStatus
    processing_error: str | None
    rights_confirmed: bool
    duration_ms: int | None
    sidecar: SidecarStatus
    metadata_redacted: dict[str, int] = Field(description="Emails and phone numbers removed from container metadata, by kind.")
    derived: list[DerivedAsset]


class AssetUrl(ApiModel):
    """How a client reads an asset's bytes: a short-lived signed Cloud Storage URL, or the authenticated stream."""

    asset_id: UUID
    kind: Literal["signed", "stream"]
    url: str
    expires_at: datetime | None = Field(description="Set for signed URLs; stream URLs need the Authorization header.")
