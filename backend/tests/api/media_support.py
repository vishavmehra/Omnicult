"""Shared helpers for the media stream tests: tiny files with real magic bytes, a generated test video (only when ffmpeg
exists), fakes for the probe, the media pipeline, vision and transcription, and a scripted language model."""

import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.llm.fixture import FixtureLLMProvider
from app.llm.gateway import LLMGateway
from app.media import ffmpeg
from app.media.types import PreparedAudio, PreparedFrame, PreparedMedia, TranscribeResult
from app.schemas.assets import VisionStatus, VisualObservation
from app.schemas.common import StepTrace
from app.schemas.xray import MediaProbe, TranscribeStatus, TranscriptSegment

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
requires_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg and ffprobe are not installed")

MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + bytes(64)
MOV = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  " + bytes(64)
M4A = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00M4A mp42" + bytes(64)
WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01\x42\xf2\x81\x04\x42\xf3\x81\x08\x42\x82\x84webm" + bytes(64)
MKV = b"\x1a\x45\xdf\xa3\xa3\x42\x86\x81\x01\x42\xf7\x81\x01\x42\x82\x88matroska" + bytes(64)
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(64)
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + bytes(64)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def probe_result(*, duration_ms: int = 9000, has_video: bool = True, has_audio: bool = True,
                 tags: dict[str, str] | None = None) -> ffmpeg.ProbeResult:
    return ffmpeg.ProbeResult(
        container="mov", duration_ms=duration_ms, width=320 if has_video else None, height=240 if has_video else None,
        fps=25.0 if has_video else None, has_video=has_video, has_audio=has_audio, video_codec="h264" if has_video else None,
        audio_codec="aac" if has_audio else None, tags=tags or {},
    )


def fake_probe(monkeypatch: pytest.MonkeyPatch, result: ffmpeg.ProbeResult | None = None) -> list[int]:
    """Replace ffprobe for upload tests that need no real media. Returns the list of probed sizes."""
    from app.services import media as media_service

    probed: list[int] = []

    async def probe_bytes(data: bytes, content_type: str) -> ffmpeg.ProbeResult:
        probed.append(len(data))
        return result or probe_result()

    monkeypatch.setattr(media_service, "probe_bytes", probe_bytes)
    return probed


def make_video(path: Path, *, scenes: int = 3, seconds_each: int = 3, audio: bool = True) -> Path:
    """A real test video: solid colour scenes (scene changes at multiples of seconds_each) and a sine tone."""
    colours = ["red", "blue", "green", "yellow", "white"]
    inputs: list[str] = []
    for i in range(scenes):
        inputs += ["-f", "lavfi", "-i", f"color=c={colours[i % 5]}:s=320x240:r=25:d={seconds_each}"]
    labels = "".join(f"[{i}:v]" for i in range(scenes))
    args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *inputs]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:d={scenes * seconds_each}"]
    args += ["-filter_complex", f"{labels}concat=n={scenes}:v=1:a=0,format=yuv420p[v]", "-map", "[v]"]
    if audio:
        args += ["-map", f"{scenes}:a", "-c:a", "aac", "-shortest"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", str(path)]
    subprocess.run(args, check=True, capture_output=True, timeout=120)
    return path


def make_audio(path: Path, seconds: int = 4) -> Path:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=330:d={seconds}",
         str(path)], check=True, capture_output=True, timeout=60,
    )
    return path


def media_probe(kind: str = "video", duration_ms: int | None = 9000) -> MediaProbe:
    return MediaProbe(
        kind=kind, container="mov", duration_ms=duration_ms, width=320, height=240, fps=25.0,  # type: ignore[arg-type]
        has_video=kind != "audio", has_audio=kind != "image", video_codec="h264", audio_codec="aac",
    )


class FakeMedia:
    """The media pipeline without ffmpeg: three keyframes and an audio track, or an image's single frame."""

    def __init__(self, kind: str = "video", *, audio: bool = True, sidecar_segments: list[dict] | None = None,
                 notes: str | None = None, fail: Exception | None = None, extract_fail: Exception | None = None,
                 stored_frames: bool = True) -> None:
        """`stored_frames=False` gives the frames no asset id: for tests that save scenes, where a made-up keyframe asset
        would break the database's foreign key (the real pipeline stores real keyframe assets)."""
        self.kind, self.audio, self.sidecar_segments, self.notes = kind, audio, sidecar_segments or [], notes
        self.fail, self.extract_fail = fail, extract_fail
        self.frame_ids: list[UUID | None] = [uuid4() if stored_frames else None for _ in range(3)]
        self.calls: list[str] = []

    async def probe(self, asset_id: UUID) -> MediaProbe:
        self.calls.append("probe")
        if self.fail:
            raise self.fail
        return media_probe(self.kind, None if self.kind == "image" else 9000)

    async def extract(self, asset_id: UUID) -> PreparedMedia:
        self.calls.append("extract")
        if self.extract_fail:
            raise self.extract_fail
        if self.kind == "image":
            frames = [PreparedFrame("f1", 0, None, "image/png", b"frame-1")]
        elif self.kind == "audio":
            frames = []
        else:
            frames = [PreparedFrame(f"f{i}", ms, self.frame_ids[i - 1], "image/jpeg", f"frame-{i}".encode())
                      for i, ms in ((1, 300), (2, 3500), (3, 6800))]
        audio = PreparedAudio(uuid4(), "audio/wav", b"wav", 9000) if self.audio and self.kind != "image" else None
        return PreparedMedia(probe=media_probe(self.kind, None if self.kind == "image" else 9000), frames=frames, audio=audio,
                             thumbnail_asset_id=None, sidecar_segments=self.sidecar_segments, sidecar_notes=self.notes)


class FakeVision:
    """Reports what a test says is visible in each frame (looked up by the frame's bytes)."""

    def __init__(self, seen: dict[bytes, list[tuple[str, str]]] | None = None, *, fail_on: set[bytes] | None = None,
                 default: list[tuple[str, str]] | None = None) -> None:
        """`seen` maps a frame's bytes to what is visible in it; `default` is what any other frame shows."""
        self.seen, self.fail_on, self.default, self.calls = seen or {}, fail_on or set(), default or [], 0

    def is_configured(self) -> bool:
        return True

    async def observe(self, asset_id: UUID, image: bytes, content_type: str, *, stage: str, agent: str) -> Any:
        from types import SimpleNamespace

        self.calls += 1
        if image in self.fail_on:
            status = VisionStatus(status="failed", provider="fake", model_id="fake-vision", message="The vision provider failed.")
            return SimpleNamespace(status=status, observations=[], trace=None)
        observations = [
            VisualObservation(id=f"vis-{i}", asset_id=asset_id, kind=kind, description=text, location="center")  # type: ignore[arg-type]
            for i, (kind, text) in enumerate(self.seen.get(image, self.default), 1)
        ]
        status = VisionStatus(status="analyzed", provider="fake", model_id="fake-vision", message=None)
        trace = StepTrace(stage=stage, agent=agent, status="completed", provider="fake", model_id="fake-vision")
        return SimpleNamespace(status=status, observations=observations, trace=trace)


class FakeTranscribe:
    """A `transcribe` capability adapter returning app.media.types.TranscribeResult (the interface the gateway must offer)."""

    def __init__(self, segments: list[tuple[int, int, str]] | None = None, *, status: str = "transcribed",
                 music_mood: str | None = None) -> None:
        self.segments, self.status, self.music_mood, self.calls = segments or [], status, music_mood, []

    async def transcribe(self, audio: bytes, content_type: str, *, language: str | None, duration_ms: int | None,
                         stage: str, agent: str) -> TranscribeResult:
        self.calls.append(language)
        message = None if self.status == "transcribed" else "The speech model is not available."
        return TranscribeResult(
            status=TranscribeStatus(status=self.status, provider="fake", model_id="fake-stt", message=message),  # type: ignore[arg-type]
            segments=[TranscriptSegment(id=f"x{i}", start_ms=a, end_ms=b, text=t, source="transcription", language=language)
                      for i, (a, b, t) in enumerate(self.segments, 1)],
            music_mood=self.music_mood,
            trace=StepTrace(stage=stage, agent=agent, status="completed", provider="fake", model_id="fake-stt"),
        )


def scripted_llm(responder: Any, *, seen: list[dict] | None = None) -> LLMGateway:
    """The real gateway (schema validation, repair, traces) over a provider that answers xray-scenes-v1 from `responder(context)`."""
    from tests.unit.workflows.scenario import offline_settings  # noqa: PLC0415

    def respond(context: Any) -> dict:
        if seen is not None:
            seen.append(dict(context))
        return responder(context)

    return LLMGateway(offline_settings(), provider=FixtureLLMProvider({"xray-scenes-v1": respond}))


class ScriptedProvider:
    """A provider that is not the demo fixture: it answers with `text_for(request)` and records every request."""

    name = "scripted"

    def __init__(self, text_for: Any) -> None:
        self.text_for, self.requests = text_for, []

    async def complete(self, request: Any) -> Any:
        from app.llm.gateway import Completion

        self.requests.append(request)
        return Completion(text=self.text_for(request))


def live_llm(provider: ScriptedProvider) -> LLMGateway:
    """A gateway that behaves as in live mode (is_fixture False) over a scripted provider; no network."""
    from app.core.config import Settings

    settings = Settings(
        _env_file=None, qloo_api_key=None, google_cloud_project="qa-test-project",
        gemini_model_fast="test-model", gemini_model_default="test-model", gemini_model_reasoning="test-model",
    )
    return LLMGateway(settings, provider=provider, backoff_seconds=0)


SEEN = {
    b"frame-1": [("text_in_image", 'Headline text: "Mahotsav Sale 50% OFF"'), ("symbol", "A brand logo, top-left")],
    b"frame-2": [("person", "A woman in a green nine-yard saree lighting a lamp"), ("object", "A brass lamp")],
    b"frame-3": [("text_in_image", 'Button text: "Shop Now"')],
}
SEGMENTS = [(0, 2000, "Celebrate Ganesh Chaturthi with us"), (7000, 9000, "Free delivery across Maharashtra")]


def standard(context: dict) -> dict:
    """A plausible model answer built from what the workflow showed it, plus one invented quote and one invented claim."""
    frames, duration = context["frames"], context["creative"]["duration_ms"]
    scenes = []
    for i, frame in enumerate(frames):
        quoted = [o["description"].split('"')[1] for o in frame["observations"] if o["kind"] == "text_in_image" and '"' in o["description"]]
        scenes.append({
            "start_ms": 0 if i == 0 else frame["at_ms"], "end_ms": frames[i + 1]["at_ms"] if i + 1 < len(frames) else duration,
            "on_screen_text": quoted + (["Invented Banner"] if i == 0 else []),
            "people": ["a woman in a saree"] if i == 1 else [], "objects": ["brass lamp"] if i == 1 else [],
            "claims": [{"quote": "50% OFF", "source": "on_screen_text"}, {"quote": "Number one in India", "source": "transcript"}] if i == 0 else [],
            "observations": [{"ref": "o1", "text": "A lamp is being lit", "category": "festival", "evidence": ["f2"]}] if i == 1 else [],
            "interpretations": [{"text": "Lighting a lamp can signal a festive blessing.", "based_on": ["o1"], "category": "festival"}] if i == 1 else [],
        })
    return {"scenes": scenes}


def real_png(width: int = 64, height: int = 48, colour: str = "#c06030") -> bytes:
    """A small decodable PNG (the fake PNG in the older asset tests is only a header)."""
    from io import BytesIO

    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (width, height), colour).save(out, format="PNG")
    return out.getvalue()
