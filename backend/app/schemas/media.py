"""Media tooling: what this server can process, and the request that renders regional text onto an image in code."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.schemas.common import ApiModel

Script = Literal["Deva", "Taml", "Mlym", "Beng", "Telu", "Knda", "Gujr", "Guru", "Orya", "Latn"]
BBox = Annotated[
    list[float],
    Field(min_length=4, max_length=4, description="[x, y, width, height], each from 0 to 1 of the image size."),
]
HexColour = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")]


def check_bbox(box: list[float]) -> list[float]:
    x, y, w, h = box
    if min(x, y) < 0 or w <= 0 or h <= 0 or x + w > 1.0 + 1e-9 or y + h > 1.0 + 1e-9:
        raise ValueError("A bbox is [x, y, width, height] inside the image: x, y >= 0, width, height > 0, ending by 1.")
    return box


class ToolStatus(ApiModel):
    available: bool
    version: str | None
    message: str | None = Field(description="Why the tool is unavailable, when it is.")


class MediaLimits(ApiModel):
    max_image_bytes: int
    max_media_bytes: int
    max_media_seconds: float


class MediaCapabilities(ApiModel):
    """Detected once at startup. Images and text rendering work without ffmpeg; video and audio need it."""

    ffmpeg: ToolStatus
    ffprobe: ToolStatus
    text_shaping: Literal["raqm", "basic"] = Field(
        description="raqm shapes Indic scripts correctly. basic renders Latin only: Indic text is refused, never drawn unshaped."
    )
    scripts: list[Script] = Field(description="Scripts with a bundled Noto font.")
    limits: MediaLimits


class TextShadow(ApiModel):
    dx: Annotated[int, Field(ge=-32, le=32)] = 2
    dy: Annotated[int, Field(ge=-32, le=32)] = 2
    blur: Annotated[float, Field(ge=0, le=16)] = 0
    color: HexColour = "#000000aa"


class TextBox(ApiModel):
    text: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    script: Script
    language: Annotated[str | None, StringConstraints(pattern=r"^[a-z]{2,3}$")] = Field(
        default=None, description="ISO 639 code; lets the font pick language-specific glyph forms (Marathi, Hindi)."
    )
    bbox: BBox
    align: Literal["left", "center", "right"] = "left"
    valign: Literal["top", "middle", "bottom"] = "top"
    color: HexColour = "#ffffff"
    bold: bool = False
    min_size_px: Annotated[int, Field(ge=6, le=400)] = 10
    max_size_px: Annotated[int, Field(ge=6, le=400)] = 96
    line_spacing: Annotated[float, Field(ge=0.7, le=2.0, description="Multiple of the font's own line height.")] = 1.0
    shadow: TextShadow | None = None

    @field_validator("bbox")
    @classmethod
    def _inside(cls, value: list[float]) -> list[float]:
        return check_bbox(value)

    @model_validator(mode="after")
    def _sizes(self) -> "TextBox":
        if self.min_size_px > self.max_size_px:
            raise ValueError("min_size_px must not exceed max_size_px.")
        return self


class LockedRegion(ApiModel):
    label: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    bbox: BBox

    @field_validator("bbox")
    @classmethod
    def _inside(cls, value: list[float]) -> list[float]:
        return check_bbox(value)


class RenderTextRequest(ApiModel):
    """Preview of the Remake: Visuals text step. The base is `base_asset_id` (a generated image), else the original,
    else a blank canvas. Text is drawn in code; then every locked region is restored pixel for pixel from
    `original_asset_id`, last, so text can never alter a protected logo or product. The answer is a PNG."""

    original_asset_id: UUID | None = None
    base_asset_id: UUID | None = None
    width: Annotated[int | None, Field(ge=16, le=4096)] = None
    height: Annotated[int | None, Field(ge=16, le=4096)] = None
    background: HexColour = "#202020"
    boxes: Annotated[list[TextBox], Field(min_length=1, max_length=12)]
    locked_regions: Annotated[list[LockedRegion], Field(max_length=8)] = []

    @model_validator(mode="after")
    def _canvas(self) -> "RenderTextRequest":
        if self.base_asset_id is None and self.original_asset_id is None and not (self.width and self.height):
            raise ValueError("Give original_asset_id or base_asset_id, or both width and height for a blank canvas.")
        if self.locked_regions and self.original_asset_id is None:
            raise ValueError("locked_regions are restored from original_asset_id, which is required with them.")
        return self
