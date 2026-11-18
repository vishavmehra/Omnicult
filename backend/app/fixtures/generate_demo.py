"""Deterministic demonstration inputs for the Generate studio (demo projects; no provider call, no network).

Nothing new is committed: every file is one the Remake demo already ships. The scene is the clean key-visual plate of the
Aamod demo creative (a model image with no logo, tin or lettering on it, and the lower right left empty, so the logo, product
and headline placed in code are the only ones in the finished picture), the speech clips are the saved Tamil recordings (matched by exact text and voice, so audio is never played against
words it does not say), the jingle is the saved Lyria music bed, and the logo and product images are the fictional Aamod
Brand Kit files. In a demo run the compositing, the headline lettering, the pace, the trimming, the timings and the checks
still run in code on these inputs.
"""

import json
from functools import lru_cache
from pathlib import Path

from app.fixtures import remake_demo as remake

ROOT = remake.ROOT
BRAND = ROOT / "brand"
SPEECH_LANGUAGE, SPEECH_VOICE = "ta", "Sulafat"
MUSIC_ELEMENT = "mh-vid-music"
MUSIC_PROMPT_FALLBACK = "Warm, joyful Indian festive instrumental for a family Diwali advertisement."


@lru_cache(maxsize=1)
def _creative_provenance() -> dict:
    try:
        return json.loads((ROOT / "creative_mh_original.json").read_text(encoding="utf-8")).get("provenance", {})
    except (OSError, ValueError):
        return {}


def scene() -> remake.FixtureImage | None:
    """The clean plate (no logo, tin or tagline baked in), with the model and prompt version the demo creative records for it.
    Not the Remake region scenes: those are finished creatives that already carry a logo, a tin and a tagline."""
    facts = _creative_provenance()
    if not remake.PLATE.is_file() or not all(facts.get(k) for k in ("image_model", "image_location", "prompt_version")):
        return None
    return remake.FixtureImage(remake.PLATE.read_bytes(), "image/jpeg", facts["image_model"], facts["image_location"], facts["prompt_version"], "")


def brand_file(source_path: str | None) -> bytes | None:
    """A Brand Kit image of the fictional demo brand by the file name the kit names (`brand/logo.png`), else None."""
    if not source_path:
        return None
    path = BRAND / Path(source_path).name
    return path.read_bytes() if path.is_file() else None


def sample_lines() -> list[str]:
    """The lines the saved recordings cover, in the order they were recorded."""
    return [e["text"] for e in remake.manifest().get("speech", []) if e["language"] == SPEECH_LANGUAGE and e["voice"] == SPEECH_VOICE]


@lru_cache(maxsize=1)
def music_bed() -> tuple[bytes, str, str, str]:
    """(wav bytes, model, location, the prompt it was made with), from the saved Lyria music bed of the demo creative."""
    prompt = MUSIC_PROMPT_FALLBACK
    try:
        document = json.loads((ROOT / "creative_mh_original.json").read_text(encoding="utf-8"))
        stack = [document]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if node.get("id") == MUSIC_ELEMENT and isinstance(node.get("value"), dict) and node["value"].get("prompt"):
                    prompt = node["value"]["prompt"]
                    break
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    except (OSError, ValueError):
        pass
    return remake.MUSIC_BED.read_bytes(), "lyria-002", "us-central1", prompt
