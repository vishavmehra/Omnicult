"""Remake: Video in a demo project: the committed Veo clip stands in for the model (no provider call, no confirmation, nothing
charged), while the start frame, the voice-over join and the checks still run in code on the real version data.

These use the COMMITTED demonstration fixtures, so they also prove the clip and its manifest are intact and usable."""

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.fixtures import remake_demo
from tests.api.media_support import requires_ffmpeg
from tests.api.omnicult_support import seeded  # noqa: F401
from tests.api.remake_support import API, build_world, finish
from tests.api.remake_video_support import mp4  # noqa: F401
from tests.api.test_remake_video import content, finish_video, start_video, video_output
from tests.api.test_remake_committed_fixtures import KEY_VISUAL_TAMIL

@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Demo runs never reach the network or start a subprocess: any outbound request or subprocess fails the test."""
    import asyncio

    import respx

    async def no_subprocess(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("demo runs must not start a subprocess")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_subprocess)
    with respx.mock(assert_all_called=False) as router:  # no route matches, so any outbound request fails
        yield router

pytestmark = [pytest.mark.usefixtures("seeded"), requires_ffmpeg]
FIXTURES = Path(remake_demo.__file__).resolve().parent / "omnicult_demo"


@pytest.fixture(autouse=True)
def no_network(offline: Any) -> Any:  # noqa: F811
    return offline


def key_visual_items() -> list[dict[str, Any]]:
    creatives = json.loads((FIXTURES / "creative_mh_original.json").read_text(encoding="utf-8"))["creatives"]
    items = []
    for e in creatives[1]["elements"]:
        item = {k: e[k] for k in ("id", "kind", "value", "language", "script", "bbox")}
        if e["id"] in KEY_VISUAL_TAMIL:
            item.update(value=KEY_VISUAL_TAMIL[e["id"]], language="ta", script="Taml")
        items.append(item)
    first = remake_demo.manifest()["speech"][0]  # the first caption, as the Tamil transcreation wrote it (the recording matches its text)
    items.append({"id": first["element_id_when_recorded"], "kind": "caption", "value": first["text"], "language": "ta", "script": "Taml",
                  "bbox": [0.1, 0.38, 0.8, 0.04], "scene_id": "mh-s1"})
    return items


async def demo_world(client: httpx.AsyncClient) -> Any:
    return await build_world(client, demo=True, assets=False, items=key_visual_items(), lock=("mh-kv-logo", "mh-kv-packshot", "mh-kv-tagline"))


def test_the_committed_clip_matches_its_manifest_and_stays_small():
    entry = remake_demo.manifest()["video"]["IN-TN"]
    data = (FIXTURES / "remake" / entry["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"] and len(data) == entry["size_bytes"] < 4 * 1024 * 1024
    assert (entry["model"], entry["location"], entry["seconds"], entry["resolution"]) == ("veo-3.1-fast-generate-001", "us-central1", 6, "720p")
    assert entry["prompt_version"] == "remake-video-v1" and entry["generated_at"] and "text" in entry["prompt"]
    assert remake_demo.demo_video_regions() == ["IN-TN"] and remake_demo.video_clip("IN-KL") is None
    clip = remake_demo.video_clip("IN-TN")
    assert clip is not None and clip.data == data and clip.seconds == 6 and clip.prompt == entry["prompt"]


async def test_a_demo_clip_needs_no_confirmation_no_provider_and_is_built_from_the_committed_fixtures(client: httpx.AsyncClient) -> None:
    world = await demo_world(client)
    caps = (await client.get(f"{API}/campaigns/{world.campaign}/remakes/capabilities")).json()
    assert caps["video"]["configured"] and caps["video"]["estimated_cost_usd"] == 0.0 and caps["demo_video_regions"] == ["IN-TN"]
    run = await finish_video(client, world, {"region_code": "IN-TN", "language": "ta"})  # no confirm_cost, no provider
    assert run["status"] == "completed" and run["mode"] == "demo", run["error"]
    out = await video_output(client, world, run)
    clip, saved = out["video"], remake_demo.manifest()["video"]["IN-TN"]
    assert out["mode"] == "demo" and out["estimated_cost_usd"] is None and clip["source"] == "demo_fixture" and clip["start_source"] == "demo_fixture"
    assert (clip["model"], clip["location"], clip["operation_id"]) == (saved["model"], saved["location"], None)
    assert clip["prompt"] == saved["prompt"]  # what the saved clip was really made from, not this project's own prompt
    assert (clip["width"], clip["height"], clip["duration_ms"], clip["with_voiceover"]) == (720, 1280, 6000, False)
    assert (await content(client, clip["video_url"])).content == (FIXTURES / "remake" / saved["file"]).read_bytes()
    assert [r["element_id"] for r in clip["kept_regions"]] == ["mh-kv-logo", "mh-kv-packshot", "mh-kv-tagline"]
    assert all(c["passed"] for c in clip["checks"]) and clip["start_frame_asset_id"]
    assert any("Saved demonstration result" in n for n in out["limitations"]) and any("cannot guarantee" in n for n in out["limitations"])
    frame = (await content(client, clip["start_frame_url"])).content
    assert frame[:8] == b"\x89PNG\r\n\x1a\n"


async def test_the_demo_preview_shows_the_saved_prompt_and_a_zero_cost(client: httpx.AsyncClient) -> None:
    world = await demo_world(client)
    plan = (await client.post(f"{API}/campaigns/{world.campaign}/remakes/video/preview", json={"region_code": "IN-TN", "language": "ta"})).json()
    assert plan["mode"] == "demo" and plan["can_run"] and plan["estimated_cost_usd"] == 0.0 and plan["model"] is None
    assert plan["price_per_second_usd"] is None and plan["prompt"] == remake_demo.manifest()["video"]["IN-TN"]["prompt"]
    assert (plan["start_frame"]["source"], plan["start_frame"]["width"], plan["start_frame"]["height"]) == ("demo_fixture", 720, 1280)
    assert plan["start_frame"]["preview_jpeg_base64"] and any("Saved demonstration clip" in n for n in plan["notes"])
    other = (await client.post(f"{API}/campaigns/{world.campaign}/remakes/video/preview", json={"region_code": "IN-KL", "language": "ml"})).json()
    assert not other["can_run"] and "IN-TN" in other["blocked_reason"]
    refused = await start_video(client, world, {"region_code": "IN-KL", "language": "ml"})
    assert refused.status_code == 409 and "IN-TN" in refused.text
    assert (await client.get(f"{API}/campaigns/{world.campaign}/versions")).json()["total"] == 1


async def test_a_demo_voiceover_of_the_version_is_joined_to_the_saved_clip_in_code(client: httpx.AsyncClient) -> None:
    world = await demo_world(client)
    first = remake_demo.manifest()["speech"][0]["element_id_when_recorded"]
    sound = await finish(client, world, "sound", {"region_code": "IN-TN", "language": "ta", "element_ids": [first]})
    assert sound["status"] == "completed", sound["error"]  # the recorded Tamil line, 4.7 s
    run = await finish_video(client, world, {"region_code": "IN-TN", "language": "ta"})
    assert run["status"] == "completed", run["error"]
    clip = (await video_output(client, world, run))["video"]
    assert clip["with_voiceover"] and 4000 < clip["voiceover_ms"] < 6000 and clip["video_asset_id"] != clip["silent_asset_id"]
    assert (await content(client, clip["silent_url"])).content == (FIXTURES / "remake" / "tn_video.mp4").read_bytes()  # the saved clip itself
    assert all(c["passed"] for c in clip["checks"] if c["name"] == "audio track")
