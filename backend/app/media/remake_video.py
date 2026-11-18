"""Pure steps of Remake: Video. No database, no provider, no network (ffmpeg and ffprobe run as local processes).

The start frame: the regional key visual WITHOUT its text (the generated scene with the locked regions restored from the
original, exactly the layout Remake: Visuals shows its model) is placed on a Veo canvas (720x1280 or 1280x720). Regional text
is never part of it: a video model would animate and garble it, so any on-screen text is added in code after the clip, or
the clip has none. The voice-over join copies the video stream and never cuts speech: a track longer than the clip is not
joined. `inspect_clip` measures the delivered file; nothing here trusts what a model says about its own output.
"""

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

from app.media import ffmpeg, textrender
from app.media import remake as stills

CANVAS = {"9:16": (720, 1280), "16:9": (1280, 720)}  # Veo 3.1 takes these two aspect ratios; 720p is the requested resolution
BLUR_RADIUS = 28
EXTENSION_DIM = 0.78  # the blurred extension is a little darker than the picture, so the picture reads as the subject
JOIN_TOLERANCE_MS = 250  # a voice-over this much longer than the clip is still joined (ffmpeg trims the silence at its end)


def aspect_for(size: tuple[int, int]) -> str:
    """The Veo aspect ratio that suits an image: portrait and square pictures go to 9:16, landscape to 16:9."""
    return "9:16" if size[1] >= size[0] else "16:9"


def build_layout(original: Image.Image, scene: Image.Image | None, locked_bboxes: list[list[float]]) -> Image.Image:
    """The key visual without text: `scene` (or the original when there is none) fitted to the original's size, with every
    locked region copied back from the original."""
    base = stills.fit_cover(scene or original, original.size)
    return stills.paste_regions(base, original, locked_bboxes) if locked_bboxes else base


def start_frame(layout: Image.Image, aspect_ratio: str | None = None) -> tuple[bytes, str, tuple[int, int]]:
    """(PNG bytes, aspect ratio, canvas size). The picture is contained, never cropped or stretched, on a canvas whose empty
    bands are a blurred, dimmed extension of the picture itself, so no brand element is cut off."""
    aspect = aspect_ratio or aspect_for(layout.size)
    width, height = CANVAS[aspect]
    picture = layout.convert("RGB")
    scale = min(width / picture.width, height / picture.height)
    fitted = picture.resize((max(1, round(picture.width * scale)), max(1, round(picture.height * scale))), Image.Resampling.LANCZOS)
    canvas = stills.fit_cover(picture, (width, height)).filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    canvas = ImageEnhance.Brightness(canvas).enhance(EXTENSION_DIM)
    canvas.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return textrender.encode_png(canvas), aspect, (width, height)


def thumbnail_jpeg(png: bytes, max_side: int = 480) -> bytes:
    """A small JPEG of a frame for the preview (the full frame is what the model receives)."""
    import io

    image = Image.open(io.BytesIO(png)).convert("RGB")
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=82)
    return out.getvalue()


@dataclass(frozen=True)
class ClipFacts:
    """What ffprobe read from the delivered file."""

    container: str | None
    video_codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    duration_ms: int | None
    has_video: bool
    has_audio: bool
    size_bytes: int


async def inspect_clip(video: bytes) -> ClipFacts:
    """Probe `video` (written to a temporary file). Raises ffmpeg.MediaToolMissing or ffmpeg.MediaUnreadable."""
    with tempfile.TemporaryDirectory(prefix="remake-video-") as tmp:
        path = Path(tmp) / "clip.mp4"
        await asyncio.to_thread(path.write_bytes, video)
        probe = await ffmpeg.probe_file(path)
    return ClipFacts(probe.container, probe.video_codec, probe.width, probe.height, probe.fps, probe.duration_ms, probe.has_video,
                     probe.has_audio, len(video))


async def join_voiceover(video: bytes, voiceover_wav: bytes, clip_ms: int) -> bytes:
    """The clip with the voice-over as its audio track. The caller has checked the track fits (`voiceover_fits`)."""
    with tempfile.TemporaryDirectory(prefix="remake-video-") as tmp:
        folder = Path(tmp)
        await asyncio.to_thread(lambda: (folder / "clip.mp4").write_bytes(video))
        await asyncio.to_thread(lambda: (folder / "voice.wav").write_bytes(voiceover_wav))
        return await ffmpeg.mux_audio(folder / "clip.mp4", folder / "voice.wav", folder / "joined.mp4", max_seconds=clip_ms / 1000)


def voiceover_fits(voiceover_ms: int, clip_ms: int) -> bool:
    return voiceover_ms <= clip_ms + JOIN_TOLERANCE_MS
