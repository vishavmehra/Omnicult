"""Helpers for the Remake: Video tests: a fake Veo adapter (no network, no paid call) that returns a real small MP4."""

import io
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image, ImageDraw

from app.schemas.common import StepTrace, Usage


@lru_cache(maxsize=8)
def mp4(seconds: int = 6, *, portrait: bool = True) -> bytes:
    """A real MP4 (h264, no audio) of solid colour: 180x320 or 320x180, `seconds` long. Needs ffmpeg."""
    size = "180x320" if portrait else "320x180"
    with tempfile.TemporaryDirectory(prefix="fake-veo-") as tmp:
        out = Path(tmp) / "clip.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c=teal:s={size}:r=24:d={seconds}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)],
                       check=True, capture_output=True, timeout=120)
        return out.read_bytes()


@lru_cache(maxsize=4)
def big_mp4(seconds: int = 6) -> bytes:
    """A solid-colour 720x1280 clip, the size Veo delivers at 720p (the text of a brand overlay is real-sized there). Needs ffmpeg."""
    with tempfile.TemporaryDirectory(prefix="fake-veo-") as tmp:
        out = Path(tmp) / "big.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=teal:s=720x1280:r=24:d={seconds}",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)], check=True, capture_output=True, timeout=120)
        return out.read_bytes()


def logo_png(size: tuple[int, int] = (300, 90)) -> bytes:
    """A logo-like PNG with transparency: a white disc and a bar on nothing."""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, size[1] - 4, size[1] - 4), fill=(255, 255, 255, 255))
    draw.rectangle((size[1] + 10, size[1] // 3, size[0] - 6, 2 * size[1] // 3), fill=(255, 255, 255, 255))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class FakeVideo:
    """Stands in for `LLMGateway.capability("video")`: records every call, answers with `clip` (or raises `error`)."""

    def __init__(self, clip: bytes | None = None, *, error: Exception | None = None, cost: float = 0.48) -> None:
        self.clip, self.error, self.cost, self.calls = clip, error, cost, []

    async def generate(self, prompt: str, **kwargs: Any) -> Any:
        self.calls.append({"prompt": prompt, **kwargs})
        if self.error:
            raise self.error
        trace = StepTrace(stage=kwargs["stage"], agent=kwargs["agent"], status="completed", provider="google",
                          model_id="veo-3.1-fast-generate-001", latency_ms=5, usage=Usage(estimated_cost_usd=self.cost))
        return SimpleNamespace(video=self.clip if self.clip is not None else mp4(kwargs["seconds"], portrait=kwargs["aspect_ratio"] == "9:16"), mime_type="video/mp4",
                               seconds=kwargs["seconds"], aspect_ratio=kwargs["aspect_ratio"], resolution="720p",
                               with_start_image=kwargs.get("start_image") is not None, operation_id="op-1234",
                               model="veo-3.1-fast-generate-001", location="us-central1", trace=trace)
