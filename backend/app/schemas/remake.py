"""Remake: Visuals, Remake: Sound (features 21 and 22) and Remake: Video (feature 23).

Three run types. `remake_visual` generates a regional scene with the image model from the clean plate, restores the locked
regions pixel for pixel from the original, and draws the regional text in code (Noto fonts, raqm shaping).
`remake_sound` speaks the transcreated lines with the speech model, optionally with a short instrumental jingle.
Every output is a stored derived asset linked to a NEW version node through the operation engine (kind `remake`, actor
ai). Checks (locked pixels, text fit, contrast, script, timing) are computed in code, never by a model.
`remake_video` makes one short clip with Veo 3.1 on Vertex AI from the regional key visual (without its text) and an
art-directed prompt, optionally joined with the Remake: Sound voice-over in code. It is the most expensive remake: the
estimate is shown first and `confirm_cost` is required, one clip per request.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.common import ApiModel, Page
from app.schemas.versions import ElementId, LanguageCode, RegionCode

RemakeKind = Literal["visual", "sound", "video"]
VideoStartSource = Literal["remake_scene", "asset", "demo_fixture", "none"]
VideoSeconds = Literal[4, 6, 8]
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


class RemakeVideoRequest(ApiModel):
    """One clip of the regional key visual. `confirm_cost` must be true for a live project: the Veo call costs money (the
    estimate is on the preview and on GET /campaigns/{id}/remakes/capabilities) and is made once, never retried by the app.
    The start frame is, in this order: `start_asset_id`; the generated scene of a Remake: Visuals result in the version (its
    locked regions restored from the original, no text); otherwise the clip is made from the prompt alone."""

    version_id: UUID | None = Field(default=None, description="The version to remake from. Default: the newest.")
    region_code: RegionCode
    language: LanguageCode
    seconds: VideoSeconds = Field(default=6, description="Clip length. Billed per second at the model's published rate.")
    start_asset_id: UUID | None = Field(default=None, description="An image asset of the project to use as the start frame.")
    direction: Direction | None = Field(default=None, description="Art direction written by the person, shown to the model as theirs.")
    add_voiceover: bool = Field(default=True, description="Join the version's Remake: Sound voice-over when it fits the clip.")
    confirm_cost: bool = False


# --- results ----------------------------------------------------------------------------------------


class LockedRegionPreview(ApiModel):
    element_id: str
    label: str
    kind: str
    source: LockSource
    bbox: list[float]


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


class VideoCheck(ApiModel):
    name: str
    passed: bool = Field(description="Computed in code from the delivered file.")
    detail: str
    element_id: str | None = Field(default=None, description="Set for a brand-element check (logo, tagline, product tin, headline): the element drawn in code over the clip.")
    sampled: int | None = Field(default=None, description="Brand checks: how many frames sampled from the finished clip were compared.")
    failed_at_ms: list[int] = Field(default=[], description="Brand checks: the sampled frames (ms into the clip) in which the element did not match its drawing.")


class VideoRemake(ApiModel):
    video_asset_id: UUID = Field(description="The file to play: with the voice-over when one was joined.")
    video_url: str
    silent_asset_id: UUID = Field(description="The clip as the model delivered it (no audio).")
    silent_url: str
    start_frame_asset_id: UUID | None
    start_frame_url: str | None
    start_source: VideoStartSource
    source: OutputSource
    with_voiceover: bool
    voiceover_asset_id: UUID | None
    voiceover_ms: int | None
    model: str | None
    location: str | None
    operation_id: str | None = Field(description="The provider's operation id, for the billing report.")
    prompt: str | None
    negative_prompt: str | None
    prompt_version: str
    direction: str | None
    seconds: int = Field(description="The length asked for; `duration_ms` is what the file holds.")
    aspect_ratio: str | None
    resolution: str
    width: int | None
    height: int | None
    duration_ms: int | None
    size_bytes: int
    audio_generated_by_model: bool = Field(default=False, description="Always false: the model is asked for no audio.")
    kept_regions: list[LockedRegionPreview] = Field(description="Regions carried into the start frame from the original. A video model cannot guarantee they stay unchanged.")
    checks: list[VideoCheck]


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
    video: VideoRemake | None = None


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
    video: CapabilityStatus = Field(description="Remake: Video. `estimated_cost_usd` is for the default length.")
    video_seconds: list[int] = Field(description="The clip lengths the model accepts.")
    video_default_seconds: int
    video_price_per_second_usd: float | None = Field(description="The price-table rate per generated second (720p, no model audio).")
    demo_video_regions: list[str] = Field(default=[], description="Regions the demonstration clip covers (demo projects only).")


class VideoStartFrame(ApiModel):
    source: VideoStartSource
    description: str
    aspect_ratio: str | None
    width: int | None
    height: int | None
    preview_jpeg_base64: str | None = Field(description="A reduced JPEG of the exact start frame, base64. Null when there is none.")


class VideoVoiceoverPlan(ApiModel):
    element_id: str
    asset_id: UUID | None
    duration_ms: int | None
    will_join: bool
    note: str


class RemakeVideoPreview(ApiModel):
    """What a run would do, with the exact prompt and the cost, before any paid call. Makes no model call and costs nothing."""

    mode: Literal["live", "demo"]
    can_run: bool
    blocked_reason: str | None
    source_version_id: UUID | None
    region_code: str
    language: str
    start_frame: VideoStartFrame
    prompt: str
    negative_prompt: str
    prompt_version: str
    model: str | None
    location: str | None
    seconds: int
    resolution: str
    price_per_second_usd: float | None
    estimated_cost_usd: float | None = Field(description="Seconds times the price-table rate. An estimate, not a billed amount; 0 for demo projects.")
    run_budget_usd: float
    within_budget: bool
    kept_regions: list[LockedRegionPreview]
    voiceover: VideoVoiceoverPlan | None
    notes: list[str]
