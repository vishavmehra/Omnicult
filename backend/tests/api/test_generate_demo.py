"""Generate in the Aamod demo project: saved fixtures stand in for the models (no provider call, no network), while the
compositing, the headline lettering, the pace, the trimming, the timings and the checks still run in code. Every generator
works without a credential and nothing is charged."""

import io
import wave
from typing import Any

import httpx
import pytest
from PIL import Image

from app.core.config import get_settings
from app.fixtures import generate_demo
from app.media import generate as media
from tests.api.generate_support import API, TAMIL_HEADLINE, finish, item_of, png_bytes, rig, start  # noqa: F401
from tests.api.omnicult_support import seeded  # noqa: F401
from tests.api.offline_support import offline  # noqa: F401  (blocks outbound HTTP and asyncio subprocesses)

pytestmark = pytest.mark.usefixtures("seeded")


@pytest.fixture(autouse=True)
def no_network(offline: Any) -> Any:  # noqa: F811
    return offline


@pytest.fixture
async def aamod(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    """The shared client with the Aamod seed on (the suite pins the legacy seed for the pre-Omnicult tests)."""
    monkeypatch.setenv("DEMO_SEED", "aamod")
    get_settings.cache_clear()
    return client


async def demo_campaign(client: httpx.AsyncClient) -> str:
    project = (await client.post(f"{API}/projects/demo")).json()
    return (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]["id"]


async def test_every_generator_works_in_the_demo_without_a_provider_or_a_cost_confirmation(aamod: httpx.AsyncClient) -> None:
    client = aamod
    campaign = await demo_campaign(client)
    caps = (await client.get(f"{API}/campaigns/{campaign}/generate/capabilities")).json()
    assert caps["mode"] == "demo" and all(x["available"] and x["estimated_cost_usd"] == 0.0 and x["model"] is None for x in caps["generators"])
    assert [v["name"] for v in caps["voice"]["voices"]] == ["Sulafat"] and [x["code"] for x in caps["voice"]["languages"]] == ["ta"]
    sample = caps["voice"]["sample_lines"]
    assert sample == generate_demo.sample_lines() and len(sample) == 4
    assert caps["brand"]["name"] == "Aamod" and len(caps["brand"]["colours"]) >= 4 and caps["brand"]["logos"]

    # image: the saved scene, the Aamod logo and tin placed in code, a Tamil headline drawn in code (any region)
    run = await finish(client, campaign, "image", {"region_code": "IN-KL", "language": "ta", "format": "9:16", "idea": "A festive table",
                                                  "headline": TAMIL_HEADLINE, "use_region_claims": False})
    assert run["status"] == "completed" and run["mode"] == "demo", run["error"]
    item = await item_of(client, campaign, run)
    assert item["source"] == "demo_fixture" and item["model"] == "gemini-3.1-flash-image" and item["estimated_cost_usd"] is None
    assert not any(w in n.lower() for n in item["limitations"] for w in ("fixture", "demonstration"))
    detail = item["image"]
    assert (detail["width"], detail["height"]) == (1080, 1920) and {p["kind"] for p in detail["placements"]} == {"logo", "product"}
    assert detail["headline"]["script"] == "Taml" and detail["headline"]["fits"] and all(c["passed"] for c in detail["checks"])
    assert Image.open(io.BytesIO((await client.get(item["asset"]["url"])).content)).size == (1080, 1920)

    # voice: the saved recordings, matched by exact text and voice; the track and timings are assembled in code
    run = await finish(client, campaign, "voice", {"region_code": "IN-TN", "language": "ta", "lines": [{"text": t} for t in sample]})
    assert run["status"] == "completed" and run["mode"] == "demo", run["error"]
    item = await item_of(client, campaign, run)
    voice = item["voice"]
    assert item["source"] == "demo_fixture" and voice["voice"] == "Sulafat" and len(voice["lines"]) == 4 and voice["lines"][0]["start_ms"] == 0
    assert voice["total_duration_ms"] == voice["lines"][-1]["end_ms"] > 17000 and max(voice["peaks"]) == 100
    assert all(b["start_ms"] - a["end_ms"] == 450 for a, b in zip(voice["lines"], voice["lines"][1:]))
    if media.can_retime():
        fast = await item_of(client, campaign, await finish(client, campaign, "voice", {
            "region_code": "IN-TN", "language": "ta", "pace": "brisk", "lines": [{"text": t} for t in sample]}))
        assert fast["voice"]["total_duration_ms"] < voice["total_duration_ms"] and fast["voice"]["pace_applied"]

    # jingle: the saved Lyria clip cut to length in code
    run = await finish(client, campaign, "jingle", {"region_code": "IN-TN", "mood": "Warm and joyful", "festival": "Deepavali", "seconds": 10})
    assert run["status"] == "completed" and run["mode"] == "demo", run["error"]
    item = await item_of(client, campaign, run)
    assert item["source"] == "demo_fixture" and item["model"] == "lyria-002" and item["jingle"]["duration_ms"] == 10000
    assert item["jingle"]["generated_seconds"] > 29 and not any(w in n.lower() for n in item["limitations"] for w in ("fixture", "demonstration"))
    with wave.open(io.BytesIO((await client.get(item["asset"]["url"])).content)) as clip:
        assert clip.getnframes() == 10 * clip.getframerate()

    gallery = (await client.get(f"{API}/campaigns/{campaign}/generate/items")).json()
    assert gallery["total"] >= 3 and {i["kind"] for i in gallery["items"]} == {"image", "voice", "jingle"}
    assert all(i["mode"] == "demo" and i["estimated_cost_usd"] is None for i in gallery["items"])


async def test_a_demo_line_without_a_recording_is_reported_not_voiced(aamod: httpx.AsyncClient) -> None:
    client = aamod
    campaign = await demo_campaign(client)
    lines = generate_demo.sample_lines()[:1] + ["ஒரு புதிய வரி."]  # the second line was never recorded
    run = await finish(client, campaign, "voice", {"region_code": "IN-TN", "language": "ta", "lines": [{"text": t} for t in lines]})
    assert run["status"] == "partial"
    voice = (await item_of(client, campaign, run))["voice"]
    assert voice["lines"][0]["spoken"] and not voice["lines"][1]["spoken"] and "not available in the demo" in voice["lines"][1]["problems"][0]
    only = await finish(client, campaign, "voice", {"region_code": "IN-TN", "language": "ta", "lines": [{"text": lines[1]}]})
    assert only["status"] == "failed" and "not available in the demo" in only["error"]["message"]


async def test_a_demo_project_still_checks_the_headline_script_before_composing(aamod: httpx.AsyncClient) -> None:
    client = aamod
    campaign = await demo_campaign(client)
    run = await finish(client, campaign, "image", {"region_code": "IN-TN", "language": "ta", "idea": "x", "headline": "दीपावली", "use_region_claims": False})
    assert run["status"] == "failed" and run["error"]["code"] == "VALIDATION_ERROR"
    accepted = await start(client, campaign, "jingle", {"region_code": "IN-TN", "mood": "calm", "seconds": 15})
    assert accepted.status_code == 202
