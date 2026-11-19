"""Remake in a demo project: the committed demonstration outputs stand in for the models (no provider call), while the
locked-region restoration, the text, the checks and the track assembly still run in code on the real version data."""

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from app.fixtures import remake_demo
from app.media import textrender
from tests.api.omnicult_support import seeded  # noqa: F401
from tests.api.remake_support import API, LINES, build_world, elements, finish, output_of, png_bytes, start, wav_bytes
from tests.api.offline import offline  # noqa: F401  (blocks outbound HTTP and subprocesses)

pytestmark = pytest.mark.usefixtures("seeded")


@pytest.fixture(autouse=True)
def no_network(offline: Any) -> Any:  # noqa: F811
    return offline


@pytest.fixture(autouse=True)
def demo_fixtures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A small synthetic fixture set in place of the committed one: one Tamil Nadu scene and two spoken lines."""
    root = tmp_path / "remake"
    root.mkdir()
    (root / "tn.png").write_bytes(png_bytes((864, 1080), (150, 50, 20)))
    speech = []
    for index, text in enumerate((LINES["cap-1"], LINES["cap-2"]), 1):
        (root / f"ta{index}.wav").write_bytes(wav_bytes(1.0 + index / 2))
        speech.append({"language": "ta", "voice": "Sulafat", "text": text, "file": f"ta{index}.wav", "model": "gemini-3.8-flash-tts",
                       "location": "global", "language_code": "ta-IN", "duration_ms": int(1000 + index * 500)})
    (root / "manifest.json").write_text(json.dumps({"visual": {"IN-TN": {
        "file": "tn.png", "mime_type": "image/png", "model": "gemini-3.1-flash-image", "location": "global",
        "prompt_version": "remake-visual-v1", "generated_at": "2026-11-18"}}, "speech": speech}), encoding="utf-8")
    monkeypatch.setattr(remake_demo, "REMAKE", root)
    remake_demo.manifest.cache_clear()
    yield root
    remake_demo.manifest.cache_clear()


async def test_a_demo_visual_remake_needs_no_provider_and_still_restores_locked_pixels_in_code(client: httpx.AsyncClient) -> None:
    world = await build_world(client, demo=True, assets=False)
    run = await finish(client, world, "visual", {"region_code": "IN-TN", "language": "ta", "use_region_claims": False})
    assert run["status"] == "completed" and run["mode"] == "demo", run["error"]
    out = await output_of(client, world, run)
    visual = out["visual"]
    assert out["mode"] == "demo" and visual["source"] == "demo_fixture" and visual["model"] == "gemini-3.1-flash-image"
    assert out["estimated_cost_usd"] is None and not any(w in n.lower() for n in out["limitations"] for w in ("fixture", "demonstration"))
    original = Image.open(io.BytesIO(remake_demo.demo_original())).convert("RGB")
    stored = Image.open(io.BytesIO((await client.get(visual["output_url"])).content)).convert("RGB")
    assert stored.size == original.size and visual["original_asset_id"] is None
    assert all(r["identical"] for r in visual["locked_regions"]) and len(visual["locked_regions"]) == 2
    for region in visual["locked_regions"]:
        rect = textrender.pixel_rect(region["bbox"], original.size)
        assert stored.crop(rect).tobytes() == original.crop(rect).tobytes()
    assert all(t["script_ok"] for t in visual["texts"]) and visual["shaping_engine"] == "raqm"


async def test_a_demo_region_without_a_fixture_fails_honestly_and_creates_nothing(client: httpx.AsyncClient) -> None:
    world = await build_world(client, demo=True, assets=False)
    run = await finish(client, world, "visual", {"region_code": "IN-KL", "language": "ml", "use_region_claims": False})
    assert run["status"] == "failed" and run["error"]["code"] == "UNSUPPORTED_CAPABILITY" and "IN-TN" in run["error"]["message"]
    assert (await client.get(f"{API}/campaigns/{world.campaign}/versions")).json()["total"] == 1


async def test_a_demo_sound_remake_matches_recordings_by_exact_text_and_voice(client: httpx.AsyncClient) -> None:
    world = await build_world(client, demo=True, assets=False)
    run = await finish(client, world, "sound", {"region_code": "IN-TN", "language": "ta", "jingle": True})
    assert run["status"] == "partial" and run["mode"] == "demo", run["error"]  # partial only because Lyria is not called in a demo
    out = await output_of(client, world, run)
    sound = out["sound"]
    assert sound["source"] == "demo_fixture" and sound["jingle"] is None and sound["voice"] == "Sulafat"
    assert [(x["start_ms"], x["end_ms"]) for x in sound["lines"]] == [(0, 1500), (1950, 3950)]
    assert any("music bed is kept" in n for n in out["limitations"]) and out["estimated_cost_usd"] is None
    other_voice = await finish(client, world, "sound", {"region_code": "IN-TN", "language": "ta", "voice": "Kore"})
    assert other_voice["status"] == "failed" and "not available in the demo" in other_voice["error"]["message"]


async def test_a_demo_line_without_a_recording_is_reported_not_voiced(client: httpx.AsyncClient) -> None:
    items = elements()
    items[-2]["value"] = "ஒரு புதிய வரி."  # cap-2 changed after the fixtures were recorded
    world = await build_world(client, demo=True, assets=False, items=items)
    run = await finish(client, world, "sound", {"region_code": "IN-TN", "language": "ta"})
    assert run["status"] == "partial"
    lines = {x["element_id"]: x for x in (await output_of(client, world, run))["sound"]["lines"]}
    assert not lines["cap-1"]["problems"] and lines["cap-2"]["duration_ms"] == 0 and "not available in the demo" in lines["cap-2"]["problems"][0]


async def test_demo_projects_skip_the_cost_confirmation_and_never_reach_a_provider(client: httpx.AsyncClient) -> None:
    world = await build_world(client, demo=True, assets=False)
    response = await start(client, world, "visual", {"region_code": "IN-TN", "language": "ta", "confirm_cost": False, "use_region_claims": False})
    assert response.status_code == 202
    caps = (await client.get(f"{API}/campaigns/{world.campaign}/remakes/capabilities")).json()
    assert caps["mode"] == "demo" and caps["image"]["model"] is None and caps["demo_regions"] == ["IN-TN"]
    assert caps["image"]["estimated_cost_usd"] == 0.0
