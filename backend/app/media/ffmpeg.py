"""ffmpeg and ffprobe through subprocess, with timeouts and typed errors.

Both binaries are found on PATH (or at FFMPEG_PATH and FFPROBE_PATH) and detected once at startup. When one is missing,
video and audio work raises `MediaToolMissing` (HTTP 503 PROVIDER_NOT_CONFIGURED) with a message that says what to install;
images and text rendering never need them. Input files are untrusted: every command runs with `-protocol_whitelist file`
(no network or other protocols, even if a crafted container names one), no stdin, and a hard timeout.
"""

import asyncio
import logging
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.core.config import get_settings
from app.core.errors import ProviderNotConfigured, ValidationFailed

log = logging.getLogger("omnicult.media")
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
_PTS_TIME = re.compile(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)")
INSTALL_HINT = "Install ffmpeg (https://ffmpeg.org/download.html) and make sure ffmpeg and ffprobe are on PATH, or set FFMPEG_PATH and FFPROBE_PATH."


class MediaToolMissing(ProviderNotConfigured):
    """ffmpeg or ffprobe is not installed on this server."""


class MediaUnreadable(ValidationFailed):
    """ffprobe could not read the file as the media it claims to be."""


class MediaProcessingFailed(RuntimeError):
    """An ffmpeg step failed or timed out. The message is safe to show users."""


@dataclass(frozen=True)
class Tool:
    name: str
    path: str | None
    version: str | None
    message: str | None

    @property
    def available(self) -> bool:
        return self.path is not None and self.message is None


@dataclass(frozen=True)
class Tools:
    ffmpeg: Tool
    ffprobe: Tool


_tools: Tools | None = None


def _detect_one(name: str, configured: str) -> Tool:
    path = shutil.which(configured)
    if path is None:
        return Tool(name, None, None, f"{name} was not found ({configured!r}). {INSTALL_HINT}")
    try:
        done = subprocess.run([path, "-version"], capture_output=True, timeout=10, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        first = done.stdout.decode("utf-8", "replace").splitlines()[0] if done.returncode == 0 and done.stdout else ""
    except (OSError, subprocess.TimeoutExpired):
        first = ""
    match = re.search(rf"{name} version (\S+)", first)
    if not match:
        return Tool(name, None, None, f"{name} at {path} did not run. {INSTALL_HINT}")
    return Tool(name, path, match.group(1), None)


def detect_tools(*, force: bool = False) -> Tools:
    """Find and test both binaries (cached; `force` re-detects, for tests and settings changes)."""
    global _tools
    if _tools is None or force:
        settings = get_settings()
        _tools = Tools(_detect_one("ffmpeg", settings.ffmpeg_path), _detect_one("ffprobe", settings.ffprobe_path))
    return _tools


async def log_startup_tools() -> Tools:
    tools = await asyncio.to_thread(detect_tools)  # cached after the first call; tests re-detect with force=True
    for tool in (tools.ffmpeg, tools.ffprobe):
        if tool.available:
            log.info("media tool found", extra={"tool": tool.name, "version": tool.version})
        else:
            log.warning("media tool missing: video and audio features are unavailable", extra={"tool": tool.name})
    return tools


def require(name: Literal["ffmpeg", "ffprobe"]) -> str:
    tool = getattr(detect_tools(), name)
    if not tool.available:
        raise MediaToolMissing(f"Video and audio processing is unavailable: {tool.message}")
    return tool.path


async def _run(args: list[str], *, timeout: float, what: str) -> subprocess.CompletedProcess[bytes]:
    def go() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(args, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)

    try:
        return await asyncio.to_thread(go)
    except subprocess.TimeoutExpired:
        raise MediaProcessingFailed(f"{what} took longer than {int(timeout)} seconds and was stopped.") from None
    except OSError:
        raise MediaToolMissing(f"Video and audio processing is unavailable: {INSTALL_HINT}") from None


@dataclass
class ProbeResult:
    container: str | None
    duration_ms: int | None
    width: int | None
    height: int | None
    fps: float | None
    has_video: bool
    has_audio: bool
    video_codec: str | None
    audio_codec: str | None
    tags: dict[str, str] = field(default_factory=dict)  # raw container and stream tags; filter before any use


def _fps(value: str | None) -> float | None:
    try:
        num, _, den = (value or "").partition("/")
        rate = float(num) / float(den or 1)
        return round(rate, 3) if math.isfinite(rate) and rate > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def _seconds_to_ms(value: object) -> int | None:
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return round(seconds * 1000) if math.isfinite(seconds) and seconds >= 0 else None


def parse_probe(payload: dict) -> ProbeResult:
    """ffprobe's JSON as a ProbeResult. Pure, so it is tested without ffprobe."""
    fmt = payload.get("format") or {}
    streams = payload.get("streams") or []
    video = next(
        (s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = _seconds_to_ms(fmt.get("duration"))
    if duration is None:
        candidates = [d for d in (_seconds_to_ms(s.get("duration")) for s in streams) if d is not None]
        duration = max(candidates) if candidates else None
    tags = {str(k): str(v) for k, v in (fmt.get("tags") or {}).items()}
    for stream in streams:
        tags.update({f"{k}": str(v) for k, v in (stream.get("tags") or {}).items() if k not in tags})
    return ProbeResult(
        container=(str(fmt.get("format_name")).split(",")[0] if fmt.get("format_name") else None), duration_ms=duration,
        width=int(video["width"]) if video and video.get("width") else None,
        height=int(video["height"]) if video and video.get("height") else None,
        fps=_fps(video.get("avg_frame_rate")) if video else None, has_video=video is not None, has_audio=audio is not None,
        video_codec=video.get("codec_name") if video else None, audio_codec=audio.get("codec_name") if audio else None,
        tags=tags,
    )


async def probe_file(path: Path) -> ProbeResult:
    import json

    exe = require("ffprobe")
    args = [exe, "-v", "error", "-protocol_whitelist", "file", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    done = await _run(args, timeout=get_settings().media_probe_timeout_seconds, what="Reading the media file")
    if done.returncode != 0:
        raise MediaUnreadable("The file could not be read as video or audio. It may be corrupt or in an unsupported format.")
    try:
        payload = json.loads(done.stdout)
    except ValueError:
        raise MediaUnreadable("The file could not be read as video or audio.") from None
    return parse_probe(payload)


def parse_scene_times(stderr: str) -> list[int]:
    """Scene-change timestamps in ms from ffmpeg's `showinfo` lines."""
    return sorted({round(float(m.group(1)) * 1000) for m in _PTS_TIME.finditer(stderr)})


async def detect_scene_changes(path: Path, threshold: float) -> list[int]:
    exe = require("ffmpeg")
    args = [
        exe, "-nostdin", "-hide_banner", "-protocol_whitelist", "file", "-i", str(path), "-an", "-vf",
        f"select='gt(scene,{threshold:.3f})',showinfo", "-f", "null", "-",
    ]
    done = await _run(args, timeout=get_settings().media_tool_timeout_seconds, what="Scene detection")
    if done.returncode != 0:
        raise MediaProcessingFailed("Scene detection failed; the video could not be decoded.")
    return parse_scene_times(done.stderr.decode("utf-8", "replace"))


async def extract_frame(path: Path, at_ms: int, out: Path, *, max_width: int) -> bytes:
    """One JPEG frame at `at_ms`, no wider than `max_width`."""
    exe = require("ffmpeg")
    args = [
        exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file", "-ss", f"{at_ms / 1000:.3f}",
        "-i", str(path), "-frames:v", "1", "-vf", f"scale='min({max_width},iw)':-2", "-q:v", "3", "-y", str(out),
    ]
    done = await _run(args, timeout=get_settings().media_tool_timeout_seconds, what="Frame extraction")
    data = out.read_bytes() if out.exists() else b""
    if done.returncode != 0 or not data:
        raise MediaProcessingFailed(f"A frame at {at_ms} ms could not be extracted from the video.")
    return data


async def extract_audio(path: Path, out: Path, *, max_seconds: float) -> bytes:
    """The audio as mono 16 kHz 16-bit WAV (the form speech models expect)."""
    exe = require("ffmpeg")
    args = [
        exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file", "-i", str(path), "-vn", "-ac", "1",
        "-ar", "16000", "-c:a", "pcm_s16le", "-t", f"{max_seconds + 1:.0f}", "-y", str(out),
    ]
    done = await _run(args, timeout=get_settings().media_tool_timeout_seconds, what="Audio extraction")
    data = out.read_bytes() if out.exists() else b""
    if done.returncode != 0 or not data:
        raise MediaProcessingFailed("The audio track could not be extracted.")
    return data


async def mux_audio(video: Path, audio: Path, out: Path, *, max_seconds: float) -> bytes:
    """The video stream copied untouched, with `audio` (any format ffmpeg reads) as AAC, as one MP4 no longer than `max_seconds`
    (a shorter track just ends early; a caller that must not cut speech checks the lengths first)."""
    exe = require("ffmpeg")
    args = [
        exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file", "-i", str(video), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        "-t", f"{max_seconds:.3f}", "-y", str(out),
    ]
    done = await _run(args, timeout=get_settings().media_tool_timeout_seconds, what="Joining the voice-over")
    data = out.read_bytes() if out.exists() else b""
    if done.returncode != 0 or not data:
        raise MediaProcessingFailed("The voice-over could not be joined to the clip.")
    return data


async def overlay_png(video: Path, layer: Path, out: Path) -> bytes:
    """`layer` (a transparent PNG the size of the video) drawn over every frame, so what it holds is pixel-identical for the whole
    clip. The video is re-encoded (H.264, high quality); audio, when there is any, is copied untouched."""
    exe = require("ffmpeg")
    args = [
        exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file", "-i", str(video), "-i", str(layer),
        "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v]", "-map", "[v]", "-map", "0:a?", "-c:v", "libx264",
        "-preset", "medium", "-crf", "17", "-c:a", "copy", "-movflags", "+faststart", "-y", str(out),
    ]
    done = await _run(args, timeout=get_settings().media_tool_timeout_seconds, what="Drawing the brand elements over the clip")
    data = out.read_bytes() if out.exists() else b""
    if done.returncode != 0 or not data:
        raise MediaProcessingFailed("The brand elements could not be drawn over the clip.")
    return data


async def extract_frames(path: Path, folder: Path, *, every_ms: int, limit: int) -> list[tuple[int, Path]]:
    """Lossless frames at 0, `every_ms`, 2 x `every_ms` ... as (time in ms, PNG path), at most `limit` of them."""
    exe = require("ffmpeg")
    args = [
        exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file", "-i", str(path), "-an", "-vf",
        f"fps={1000 / every_ms:.6f}", "-frames:v", str(limit), "-y", str(folder / "f%03d.png"),
    ]
    done = await _run(args, timeout=get_settings().media_tool_timeout_seconds, what="Sampling frames")
    files = sorted(folder.glob("f*.png"))
    if done.returncode != 0 or not files:
        raise MediaProcessingFailed("Frames could not be sampled from the clip.")
    return [(index * every_ms, file) for index, file in enumerate(files)]
