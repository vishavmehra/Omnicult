"""Deterministic demonstration outputs for Remake: Visuals, Remake: Sound and Remake: Video (demo projects; no provider call).

The files under `omnicult_demo/remake/` were generated ONCE with the live image and speech models (the generation is
logged outside the repository) and are committed so a demo project can show a Tamil remake without a credential. They are
the model's output, nothing else: in a demo run the locked-region restoration, the regional text, every check and the
track assembly still run in code on the real version data. Speech fixtures match a line only by its exact text, language
and voice, so audio is never played against text it does not say. The clip fixture (`video` in the manifest) is one Veo 3.1
Fast clip generated once from the Tamil Nadu start frame; the start frame, the voice-over join and the checks still run in code.
"""

import json
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "omnicult_demo"
REMAKE = ROOT / "remake"
ORIGINAL = ROOT / "creative" / "mh_original" / "keyvisual.png"
PLATE = ROOT / "creative" / "mh_original" / "keyvisual_plate.jpg"
MUSIC_BED = ROOT / "creative" / "mh_original" / "music_bed.wav"


@dataclass(frozen=True)
class FixtureImage:
    data: bytes
    mime_type: str
    model: str
    location: str
    prompt_version: str
    generated_at: str


@dataclass(frozen=True)
class FixtureSpeech:
    wav: bytes
    model: str
    location: str
    voice: str
    language_code: str
    duration_ms: int


@dataclass(frozen=True)
class FixtureVideo:
    data: bytes
    mime_type: str
    model: str
    location: str
    prompt_version: str
    generated_at: str
    seconds: int
    prompt: str


@lru_cache(maxsize=1)
def manifest() -> dict:
    path = REMAKE / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"visual": {}, "speech": [], "video": {}}


def demo_regions() -> list[str]:
    return sorted(manifest().get("visual", {}))


def visual_background(region_code: str) -> FixtureImage | None:
    entry = manifest().get("visual", {}).get(region_code)
    if entry is None or not (REMAKE / entry["file"]).is_file():
        return None
    return FixtureImage((REMAKE / entry["file"]).read_bytes(), entry["mime_type"], entry["model"], entry["location"],
                        entry["prompt_version"], entry["generated_at"])


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", " ".join(text.split()))


def speech_clip(language: str, text: str, voice: str) -> FixtureSpeech | None:
    for entry in manifest().get("speech", []):
        if entry["language"] == language and entry["voice"] == voice and _norm(entry["text"]) == _norm(text):
            path = REMAKE / entry["file"]
            if path.is_file():
                return FixtureSpeech(path.read_bytes(), entry["model"], entry["location"], entry["voice"], entry["language_code"],
                                     entry["duration_ms"])
    return None


def demo_original() -> bytes:
    return ORIGINAL.read_bytes()


def demo_plate() -> bytes:
    return PLATE.read_bytes()


def demo_video_regions() -> list[str]:
    return sorted(code for code, entry in manifest().get("video", {}).items() if (REMAKE / entry["file"]).is_file())


def video_clip(region_code: str) -> FixtureVideo | None:
    entry = manifest().get("video", {}).get(region_code)
    if entry is None or not (REMAKE / entry["file"]).is_file():
        return None
    return FixtureVideo((REMAKE / entry["file"]).read_bytes(), entry["mime_type"], entry["model"], entry["location"], entry["prompt_version"],
                        entry["generated_at"], entry["seconds"], entry["prompt"])


def demo_scene(region_code: str) -> bytes | None:
    """The committed regional scene (the Remake: Visuals fixture) a demo video starts from."""
    scene = visual_background(region_code)
    return scene.data if scene else None
