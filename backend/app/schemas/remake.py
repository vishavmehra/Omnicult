"""Remake: Visuals and Remake: Sound (features 21 and 22).

Two run types. `remake_visual` generates a regional scene with the image model from the clean plate, restores the locked
regions pixel for pixel from the original, and draws the regional text in code (Noto fonts, raqm shaping).
`remake_sound` speaks the transcreated lines with the speech model, optionally with a short instrumental jingle.
Every output is a stored derived asset linked to a NEW version node through the operation engine (kind `remake`, actor
ai). Checks (locked pixels, text fit, contrast, script, timing) are computed in code, never by a model.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.common import ApiModel, Page
from app.schemas.versions import ElementId, LanguageCode, RegionCode

RemakeKind = Literal["visual", "sound"]
OutputSource = Literal["provider", "demo_fixture"]
LockSource = Literal["lock", "brand_kit_never_change"]
Direction = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]
VoiceName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9]{2,24}$")]
GEMINI_VOICES = ("Sulafat", "Kore", "Puck", "Charon", "Aoede", "Zephyr", "Leda", "Orus")
MAX_VOICE_LINES = 8


class RemakeVisualRequest(ApiModel):
    """Regional scene for one `scene` element. `confirm_cost` must be true for a live project: the image call costs money
    (the estimate is on GET /campaigns/{id}/remakes/capabilities) and is made once, never retried by the app."""

    version_id: UUID | None = Field(default=None, description="The version to remake from. Default: the newest.")
    region_code: RegionCode
    language: LanguageCode
    plate_element_id: ElementId | None = Field(
        default=None, description="The unlocked `scene` element to replace. Default: the first unlocked scene element."
    )
    original_asset_id: UUID | None = Field(
        default=None, description="The finished source creative (an image asset). Locked regions are restored from it. "
        "Required for a live project; a demo project falls back to the committed demonstration key visual."
    )
    plate_asset_id: UUID | None = Field(default=None, description="The clean plate: the same image without text or product.")
    reference_asset_id: UUID | None = Field(default=None, description="The product reference image shown to the model.")
    direction: Direction | None = Field(default=None, description="Art direction written by the person, shown to the model as theirs.")
    use_region_claims: bool = Field(default=True, description="Give the model a few of the region's sourced claims as direction.")
    confirm_cost: bool = False


class RemakeSoundRequest(ApiModel):
    version_id: UUID | None = None
    region_code: RegionCode
    language: LanguageCode
    element_ids: Annotated[list[ElementId], Field(min_length=1, max_length=MAX_VOICE_LINES)] | None = Field(
        default=None, description="Text elements to speak, in this order. Default: the version's voiceover and caption lines."
    )
    voice: VoiceName = "Sulafat"
    jingle: bool = Field(default=False, description="Also make a short instrumental jingle with Lyria (Vertex AI only).")
    jingle_prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)] | None = None
    confirm_cost: bool = False


# --- results ----------------------------------------------------------------------------------------


class LockedRegionResult(ApiModel):
    element_id: str
    label: str
    kind: str
    source: LockSource
    bbox: list[float]
    identical: bool = Field(description="Computed in code: the stored image holds exactly the original's pixels here.")


class TextRenderResult(ApiModel):
    element_id: str
    kind: str
    text: str
    language: str | None
    script: str
    bbox: list[float]
    font_size: int
    lines: list[str]
    fits: bool
    overlaps_locked: bool
    script_ok: bool = Field(description="The letters are in the expected script (or Latin brand words).")
    contrast_ratio: float = Field(description="Estimated from the mean background under the box and the text colour.")
    low_contrast: bool
    color: str
    problems: list[str]
    passed: bool


class VisualRemake(ApiModel):
    output_asset_id: UUID
    output_url: str
    plate_asset_id: UUID
    plate_url: str
    original_asset_id: UUID | None
    original_url: str | None
    source: OutputSource
    width: int
    height: int
    shaping_engine: str
    plate_element_id: str
    scene_id: str | None
    model: str | None
    location: str | None
    prompt: str | None
    prompt_version: str
    direction: str | None
    claim_ids: list[UUID]
    locked_regions: list[LockedRegionResult]
    texts: list[TextRenderResult]


class VoiceLineResult(ApiModel):
    element_id: str
    text: str
    language: str
    start_ms: int
    end_ms: int
    duration_ms: int
    window_ms: int | None = Field(description="Length of the scene the source line sat in, when known.")
    fits_window: bool | None
    back_translation: str | None = Field(description="English back-translation from the transcreation, when one is recorded.")
    problems: list[str]


class JingleResult(ApiModel):
    asset_id: UUID
    url: str
    model: str
    location: str
    duration_ms: int
    prompt: str


class SoundRemake(ApiModel):
    voiceover_asset_id: UUID
    voiceover_url: str
    source: OutputSource
    voice: str
    language_code: str
    model: str | None
    location: str | None
    total_duration_ms: int
    native_speaker_reviewed: bool = False
    lines: list[VoiceLineResult]
    jingle: JingleResult | None


class RemakeOutput(ApiModel):
    """One applied remake, read back from its operation. `passed` is false when any code check found a problem."""

    id: UUID = Field(description="The operation id.")
    campaign_id: UUID
    kind: RemakeKind
    run_id: UUID | None
    mode: Literal["live", "demo"]
    source_version_id: UUID
    result_version_id: UUID
    region_code: str
    language: str
    created_at: datetime
    estimated_cost_usd: float | None
    prompt_version: str | None
    passed: bool
    limitations: list[str]
    visual: VisualRemake | None
    sound: SoundRemake | None


class RemakePage(Page[RemakeOutput]):
    pass


class CapabilityStatus(ApiModel):
    configured: bool
    model: str | None
    location: str | None
    estimated_cost_usd: float | None = Field(description="Price-table estimate for one call; not a billed amount.")
    note: str | None = None


class RemakeCapabilities(ApiModel):
    mode: Literal["live", "demo"]
    image: CapabilityStatus
    speech: CapabilityStatus
    music: CapabilityStatus
    text_shaping: Literal["raqm", "basic"]
    voices: list[str]
    max_voice_lines: int
    run_budget_usd: float
    daily_budget_usd: float
    demo_regions: list[str] = Field(description="Regions the demonstration fixtures cover (demo projects only).")
