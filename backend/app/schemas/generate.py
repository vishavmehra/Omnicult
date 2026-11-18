"""Generate studio: new creative assets made from the campaign's brief and Brand Kit (image, voice-over, jingle).

Three run types (`generate_image`, `generate_voice`, `generate_jingle`), each with four stages, through the same gateway,
budget guard and `confirm_cost` rule as Remake. Every output is a stored asset (`assets.derived_role` generate_*) with its
provenance in `media_info`; the run's `result` is one `GenerateItem`, so the gallery is the campaign's generate runs.
Lettering in an image is drawn in code (never by the image model); the logo and product image are composited in code;
loudness, timings and fit checks are computed in code. `GeneratorInfo` is the registry the client renders from, so a new
generator (for example video) appears in the studio only when the server lists it.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.common import ApiModel, Page
from app.schemas.remake import VoiceName
from app.schemas.runs import RunError
from app.schemas.versions import LanguageCode, RegionCode

GenerateKind = Literal["image", "voice", "jingle"]
GenerateSource = Literal["provider", "demo_fixture"]
GenerateStatus = Literal["completed", "partial", "failed"]
ImageFormat = Literal["1:1", "4:5", "9:16", "16:9"]
ImagePurpose = Literal["key_visual", "social_post"]
PaceName = Literal["slow", "normal", "brisk"]
Idea = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]
Headline = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
LineText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Hint = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
MAX_VOICE_LINES = 8
MAX_INSTRUMENTS = 5
JINGLE_SECONDS = (10, 15, 30)  # a clip is made at the model's fixed length and trimmed in code, so 30 is the most it can be


class GenerateImageRequest(ApiModel):
    """A key visual or social post for one region and format. Lettering is drawn in code in the region's script, the logo and
    product image are placed in code. `confirm_cost` must be true for a live project: the image call costs money."""

    region_code: RegionCode
    language: LanguageCode
    format: ImageFormat = "4:5"
    purpose: ImagePurpose = "key_visual"
    idea: Idea = Field(description="The scene and mood, in the person's words. Shown to the model as theirs.")
    headline: Headline | None = Field(default=None, description="Optional headline, drawn in code in the language's script.")
    include_logo: bool = True
    include_product: bool = True
    reference_asset_id: UUID | None = Field(
        default=None, description="A stored image of the project (a Brand Kit product image, an upload or a generated image)."
    )
    use_brand_colours: bool = True
    use_region_claims: bool = True
    confirm_cost: bool = False


class GenerateVoiceLineIn(ApiModel):
    text: LineText
    language: LanguageCode | None = Field(default=None, description="Overrides the request language for this line.")
    element_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")] | None = Field(
        default=None, description="The Studio element this line came from; used to find its English back-translation."
    )


class GenerateVoiceRequest(ApiModel):
    region_code: RegionCode
    language: LanguageCode
    lines: Annotated[list[GenerateVoiceLineIn], Field(min_length=1, max_length=MAX_VOICE_LINES)]
    voice: VoiceName = "Sulafat"
    pace: PaceName = Field(default="normal", description="Applied in code to the spoken clips (pitch is kept).")
    confirm_cost: bool = False


class GenerateJingleRequest(ApiModel):
    """A short instrumental from Lyria. The model makes a fixed-length clip; a shorter length is cut in code with a fade."""

    region_code: RegionCode
    mood: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    festival: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None
    instruments: Annotated[list[Hint], Field(max_length=MAX_INSTRUMENTS)] = []
    seconds: Literal[10, 15, 30] = 30
    confirm_cost: bool = False


class GenerateUseInStudioRequest(ApiModel):
    version_id: UUID | None = Field(default=None, description="The version to add the element to. Default: the newest.")


# --- results ----------------------------------------------------------------------------------------------------


class GenerateAssetRef(ApiModel):
    asset_id: UUID
    url: str = Field(description="API path of the file; it needs the same token as every other call.")
    content_type: str
    filename: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None


class GenerateCheck(ApiModel):
    """One check computed in code (never by a model)."""

    id: str
    label: str
    passed: bool
    detail: str | None = None


class GeneratePlacement(ApiModel):
    kind: Literal["logo", "product"]
    asset_id: UUID | None
    label: str
    bbox: list[float] = Field(description="[x, y, width, height], each from 0 to 1 of the finished image.")
    width_px: int


class GenerateTextResult(ApiModel):
    text: str
    script: str
    language: str | None
    bbox: list[float]
    font_size: int
    lines: list[str]
    fits: bool
    script_ok: bool
    contrast_ratio: float
    low_contrast: bool
    color: str
    problems: list[str]


class GenerateImageDetail(ApiModel):
    format: ImageFormat
    purpose: ImagePurpose
    width: int
    height: int
    shaping_engine: str
    scene: GenerateAssetRef = Field(description="The image model's scene alone, before anything was composited.")
    reference: GenerateAssetRef | None
    placements: list[GeneratePlacement]
    headline: GenerateTextResult | None
    checks: list[GenerateCheck]
    palette: list[str] = Field(description="Brand Kit colours given to the model as direction (hex).")
    claim_ids: list[UUID]


class GenerateLineResult(ApiModel):
    index: int
    text: str
    language: str
    start_ms: int
    end_ms: int
    duration_ms: int
    spoken: bool
    back_translation: str | None = Field(description="English back-translation from the transcreation, when one is recorded.")
    problems: list[str]


class GenerateVoiceDetail(ApiModel):
    voice: str
    pace: PaceName
    pace_applied: bool = Field(description="True when the clips were retimed in code; false when the pace was normal.")
    language_code: str
    total_duration_ms: int
    lines: list[GenerateLineResult]
    peaks: list[int] = Field(description="Loudness of the joined track in 96 equal slices, 0 to 100, computed from the audio.")
    native_speaker_reviewed: bool = False


class GenerateJingleDetail(ApiModel):
    mood: str
    festival: str | None
    instruments: list[str]
    requested_seconds: int
    generated_seconds: float = Field(description="Length of the clip as the model made it.")
    duration_ms: int
    sample_rate: int
    channels: int
    peaks: list[int]


class GenerateItem(ApiModel):
    """One generate run and what it made. `id` is the run id. A failed run keeps its error here so it is never hidden."""

    id: UUID
    campaign_id: UUID
    kind: GenerateKind
    status: GenerateStatus
    mode: Literal["live", "demo"]
    created_at: datetime
    title: str
    region_code: str
    language: str
    source: GenerateSource | None
    model: str | None
    location: str | None
    prompt_version: str
    prompt: str | None = Field(description="The prompt sent to the model, exactly. Null for speech.")
    estimated_cost_usd: float | None = Field(description="Price-table estimate for the calls this run made; not a billed amount.")
    latency_ms: int | None
    request: dict[str, Any] = Field(description="The validated request, without the cost confirmation.")
    asset: GenerateAssetRef | None
    image: GenerateImageDetail | None
    voice: GenerateVoiceDetail | None
    jingle: GenerateJingleDetail | None
    limitations: list[str]
    error: RunError | None
    studio_version_ids: list[UUID] = Field(default=[], description="Versions this output was added to as an element.")


class GenerateItemPage(Page[GenerateItem]):
    pass


class GenerateUsed(ApiModel):
    version_id: UUID
    operation_id: UUID
    element_id: str


# --- capabilities -----------------------------------------------------------------------------------------------


class GeneratorInfo(ApiModel):
    """One entry of the generator registry. The studio shows only the generators the server lists, and only an `available`
    one can run."""

    kind: GenerateKind
    run_type: Literal["generate_image", "generate_voice", "generate_jingle"]
    label: str
    available: bool
    model: str | None
    location: str | None
    estimated_cost_usd: float | None = Field(description="One run, price-table estimate; speech is per line. Not a billed amount.")
    note: str | None = None


class GenerateFormat(ApiModel):
    id: ImageFormat
    label: str
    width: int
    height: int


class GenerateVoiceInfo(ApiModel):
    name: str
    style: str | None = Field(description="The style label in Google's published voice list.")


class GenerateLanguage(ApiModel):
    code: str
    name: str
    script: str


class GenerateBrandColour(ApiModel):
    id: str
    name: str
    hex: str


class GenerateBrandImage(ApiModel):
    id: str
    label: str
    asset_id: UUID | None
    url: str | None


class GenerateBrandInfo(ApiModel):
    """What the generators read from the Brand Kit and the brief, so it can be shown beside the controls."""

    name: str
    tone: list[str]
    colours: list[GenerateBrandColour]
    logos: list[GenerateBrandImage]
    products: list[GenerateBrandImage]
    tagline: str | None
    product_name: str | None
    objective: str | None
    primary_message: str | None
    festival_hooks: list[str]


class GenerateVoiceOptions(ApiModel):
    voices: list[GenerateVoiceInfo]
    languages: list[GenerateLanguage]
    paces: list[PaceName]
    pace_supported: bool = Field(description="False when the server cannot retime audio; the pace control is then not shown.")
    max_lines: int
    max_line_chars: int
    sample_lines: list[LineText] = Field(description="Lines the demonstration recordings cover (demo projects only).")


class GenerateJingleOptions(ApiModel):
    moods: list[str]
    instruments: list[str]
    seconds: list[int]
    clip_seconds: int = Field(description="The length the model makes; a shorter length is cut in code.")


class GenerateCapabilities(ApiModel):
    mode: Literal["live", "demo"]
    generators: list[GeneratorInfo]
    formats: list[GenerateFormat]
    purposes: list[ImagePurpose]
    idea_chips: list[str]
    languages: list[GenerateLanguage] = Field(description="Languages a headline can be drawn in: those whose script has a bundled font.")
    voice: GenerateVoiceOptions
    jingle: GenerateJingleOptions
    brand: GenerateBrandInfo
    text_shaping: Literal["raqm", "basic"]
    scripts: list[str]
    run_budget_usd: float
    daily_budget_usd: float
