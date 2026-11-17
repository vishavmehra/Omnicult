"""Data the media pipeline hands to the Creative X-Ray workflow. Plain containers: no behaviour, no I/O."""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.schemas.common import StepTrace
from app.schemas.xray import MediaProbe, TranscribeStatus, TranscriptSegment


@dataclass
class PreparedFrame:
    frame_id: str  # f1, f2, ... in time order; the handle models and scenes cite
    timestamp_ms: int
    asset_id: UUID | None  # the stored keyframe asset; None for an image (its own frame)
    content_type: str
    data: bytes


@dataclass
class PreparedAudio:
    asset_id: UUID
    content_type: str
    data: bytes  # mono 16 kHz 16-bit WAV
    duration_ms: int | None


@dataclass
class PreparedMedia:
    probe: MediaProbe
    frames: list[PreparedFrame]
    audio: PreparedAudio | None
    thumbnail_asset_id: UUID | None
    sidecar_segments: list[dict] = field(default_factory=list)  # user-provided cues: {"start_ms", "end_ms", "text"}, redacted
    sidecar_notes: str | None = None  # user-provided plain notes, redacted; context for a model, never a transcript
    container_tags: dict[str, str] = field(default_factory=dict)  # allowlisted, redacted


@dataclass
class TranscribeResult:
    """What a gateway `transcribe` capability adapter returns (the shape VisionResult has for vision). `status.status` is
    transcribed, unavailable or failed; it never raises for provider problems, except LLMError when the gateway's deadline
    expires. `segments` are timed; `music_mood` is set only if the adapter really analysed the audio for it."""

    status: TranscribeStatus
    segments: list[TranscriptSegment]
    music_mood: str | None = None
    trace: StepTrace | None = None


class TranscribeLike(Protocol):
    """The `transcribe` capability: `LLMGateway.capability("transcribe")`, wired in app.workflows.build_workflow_deps."""

    def is_configured(self) -> bool: ...

    async def transcribe(
        self, audio: bytes, content_type: str, *, language: str | None, duration_ms: int | None, stage: str, agent: str
    ) -> TranscribeResult: ...


class MediaPipelineLike(Protocol):
    """What the workflow needs: both calls are idempotent and raise app.media.ffmpeg errors."""

    async def probe(self, asset_id: UUID) -> MediaProbe: ...

    async def extract(self, asset_id: UUID) -> PreparedMedia: ...
