"""Creative X-Ray: a creative broken into scenes. Observation (what is seen or heard) stays apart from interpretation
(a cultural reading); every quoted item was verified in code against the frame observations or the transcript."""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.assets import Asset, AssetKind, VisionStatus, VisualObservation
from app.schemas.claims import ClaimCategory
from app.schemas.common import Anchor, ApiModel, DataMode, Page, RunMetadata
from app.schemas.runs import RunStatus

RegionCode = Annotated[str, StringConstraints(pattern=r"^IN-[A-Z]{2}$")]
LanguageCode = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}$")]
Provenance = Literal["observed", "transcribed", "user_provided", "model_generated", "interpretation"]
TranscriptSource = Literal["transcription", "user_sidecar"]
TranscribeState = Literal["transcribed", "from_sidecar", "not_applicable", "unavailable", "failed"]

# What each scene field is. Never set by a model: code sets it.
SCENE_PROVENANCE: dict[str, Provenance] = {
    "on_screen_text": "observed",  # a vision model's reading of a frame, kept only when found in its frame observations
    "transcript": "transcribed",
    "people": "model_generated",
    "gestures": "model_generated",
    "setting": "model_generated",
    "objects": "model_generated",
    "colours": "model_generated",
    "music_mood": "model_generated",
    "claims": "model_generated",  # the quote is verified in code; whether it is a claim is the model's reading
    "cultural_observations": "model_generated",
    "cultural_interpretations": "interpretation",
    "layout": "model_generated",  # the role is the model's reading; the box is the vision model's; the cited ids are checked in code
}
_SPACES = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Case- and spacing-insensitive form used to find a quote in observations (no OCR, no fuzzy matching)."""
    return _SPACES.sub(" ", text).strip().casefold()


class XRayCreate(ApiModel):
    """Start Creative X-Ray on an uploaded asset (run_type creative_xray)."""

    asset_id: UUID
    label: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] = None
    region_code: RegionCode | None = Field(default=None, description="Market the creative is read for; optional.")
    language: LanguageCode | None = Field(default=None, description="Declared spoken language; helps transcription.")


class MediaProbe(ApiModel):
    kind: AssetKind
    container: str | None
    duration_ms: int | None
    width: int | None
    height: int | None
    fps: float | None
    has_video: bool
    has_audio: bool
    video_codec: str | None
    audio_codec: str | None


class TranscribeStatus(ApiModel):
    status: TranscribeState
    provider: str | None
    model_id: str | None
    message: str | None = Field(description="Why there is no transcript, when there is none. A transcript is never invented.")


class TranscriptSegment(ApiModel):
    id: str
    start_ms: int | None
    end_ms: int | None
    text: str
    source: TranscriptSource
    language: str | None = None


class OnScreenText(ApiModel):
    text: str
    frame_ms: int | None = Field(description="Keyframe at which a vision model reported this text.")


class LayoutItem(ApiModel):
    """One part of a scene's layout: an on-screen text, logo or pack, with the box a vision model located it in."""

    role: Literal["headline", "body", "cta", "tagline", "caption", "logo", "product", "packshot"] = Field(
        description="The part it plays, as a model read it.")
    text: str | None = Field(description="Text roles: the text as the vision model reported it. Null for a logo or pack.")
    frame_ms: int = Field(description="The keyframe the box belongs to.")
    observation_id: str = Field(description="The vision observation (vis-N) of that keyframe the box comes from.")
    bbox: list[float] = Field(min_length=4, max_length=4, description="[x, y, w, h], each 0-1 of the keyframe.")


class AdClaim(ApiModel):
    text: str = Field(description="The exact quote, found in the scene's on-screen text or transcript.")
    source: Literal["on_screen_text", "transcript"]
    segment_id: str | None = None


class SceneObservation(ApiModel):
    id: str
    text: str
    category: ClaimCategory | None
    evidence: list[str] = Field(description="Frame ids (f1, f2, ...) and transcript segment ids (t1, ...) it rests on.")
    claim_ids: list[UUID] = Field(default=[], description="Regional claims linked to this observation; filled by later steps.")


class SceneInterpretation(ApiModel):
    id: str
    text: str = Field(description="A model's cultural reading. Not an observed fact.")
    based_on: list[str] = Field(description="Ids of the observations in this scene it is based on.")
    category: ClaimCategory | None
    limitations: list[str]
    claim_ids: list[UUID] = []




class Scene(ApiModel):
    id: UUID
    creative_asset_id: UUID
    campaign_id: UUID
    asset_id: UUID
    run_id: UUID
    position: int
    start_ms: int
    end_ms: int | None = Field(description="Null for an image, which is one scene without a duration.")
    keyframe_asset_id: UUID | None
    keyframe_url: str | None = Field(description="Authenticated API path of the scene's keyframe image.")
    frame_ms: list[int] = Field(description="Timestamps of the keyframes this scene was read from.")
    on_screen_text: list[OnScreenText]
    transcript: list[TranscriptSegment]
    people: list[str]
    gestures: list[str]
    setting: str | None
    objects: list[str]
    colours: list[str]
    music_mood: str | None = Field(description="Null unless an audio capability reported it; never guessed from video.")
    claims: list[AdClaim]
    cultural_observations: list[SceneObservation]
    cultural_interpretations: list[SceneInterpretation]
    layout: list[LayoutItem] = Field(default=[], description="Where the scene's text, logo and pack sit, located by a vision model.")
    provenance: dict[str, Provenance]
    limitations: list[str]
    anchor: Anchor
    created_at: datetime


class ScenePage(Page[Scene]):
    pass


class FrameRecord(ApiModel):
    id: str
    timestamp_ms: int
    asset_id: UUID | None = Field(description="The derived keyframe asset; null for an image, which is its own frame.")
    url: str
    observations: list[VisualObservation]


class CreativeAnalysis(ApiModel):
    """What the current run found about the creative as a whole."""

    probe: MediaProbe
    transcribe: TranscribeStatus
    vision: VisionStatus
    frames: list[FrameRecord]
    transcript: list[TranscriptSegment]
    sidecar_notes: str | None = Field(description="The user's own notes, redacted of emails and phone numbers; never a transcript.")
    limitations: list[str]
    dropped: dict[str, int] = Field(description="Model items removed because code could not verify them, by kind.")


class CreativeSummary(ApiModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    asset_id: UUID
    kind: AssetKind
    label: str
    region_code: str | None
    language: str | None
    mode: DataMode | None
    status: RunStatus | None = Field(description="Status of the latest X-Ray run, which this record always mirrors.")
    latest_run_id: UUID | None
    current_run_id: UUID | None
    scene_count: int
    duration_ms: int | None
    thumbnail_url: str | None
    created_at: datetime
    updated_at: datetime


class CreativeSummaryPage(Page[CreativeSummary]):
    pass


class Creative(CreativeSummary):
    asset: Asset
    analysis: CreativeAnalysis | None
    limitations: list[str]
    run_metadata: RunMetadata | None
