"""The committed Remake demonstration fixtures (generated once on Vertex AI): intact, small, and usable end to end in a demo
project with no provider call."""

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.fixtures import remake_demo
from tests.api.omnicult_support import seeded  # noqa: F401
from tests.api.remake_support import API, build_world, finish, output_of
from tests.api.test_demo_journey import offline  # noqa: F401

pytestmark = pytest.mark.usefixtures("seeded")
FIXTURES = Path(remake_demo.__file__).resolve().parent / "omnicult_demo"
KEY_VISUAL_TAMIL = {
    "mh-kv-headline": "தீபாவளி என்றால் பலகாரம்!", "mh-kv-sub": "வீட்டுச் சுவையில் பலகாரம், இப்போது ஒரே டின்னில்",
    "mh-kv-product-name": "ஆமோத் ஃபெஸ்டிவ் டின்*", "mh-kv-cta-hook": "பண்டிகைக்கு முன் வீடு தேடி வரும்",
    "mh-kv-cta-button": "இன்றே ஆர்டர் செய்யுங்கள் · Order now", "mh-kv-small-print": "*நிகர எடை 750 கிராம்.",
    "mh-kv-demo-label": "கற்பனை பிராண்ட் · Omnicult டெமோ படைப்பு",
}


def test_the_committed_manifest_matches_its_files_and_stays_small():
    manifest = remake_demo.manifest()
    folder = FIXTURES / "remake"
    assert manifest["visual"].keys() == {"IN-TN"} and remake_demo.demo_regions() == ["IN-TN"]
    files = [manifest["visual"]["IN-TN"], *manifest["speech"]]
    for entry in files:
        assert hashlib.sha256((folder / entry["file"]).read_bytes()).hexdigest() == entry["sha256"], entry["file"]
    assert sum(p.stat().st_size for p in folder.iterdir()) < 3 * 1024 * 1024
    assert [e["language"] for e in manifest["speech"]] == ["ta"] * 4 and {e["voice"] for e in manifest["speech"]} == {"Sulafat"}
    assert all(e["model"] == "gemini-3.8-flash-tts" and e["location"] == "global" for e in manifest["speech"])
    assert manifest["visual"]["IN-TN"]["model"] == "gemini-3.1-flash-image" and manifest["visual"]["IN-TN"]["generated_at"]


async def test_the_committed_fixtures_remake_the_tamil_key_visual_and_voice_over_in_a_demo_project(client: httpx.AsyncClient, offline: Any) -> None:  # noqa: F811
    creatives = json.loads((FIXTURES / "creative_mh_original.json").read_text(encoding="utf-8"))["creatives"]
    items = []
    for e in creatives[1]["elements"]:
        item = {k: e[k] for k in ("id", "kind", "value", "language", "script", "bbox")}
        if e["id"] in KEY_VISUAL_TAMIL:
            item.update(value=KEY_VISUAL_TAMIL[e["id"]], language="ta", script="Taml")
        items.append(item)
    for index, entry in enumerate(remake_demo.manifest()["speech"], 1):  # the video's four captions, as the Tamil transcreation wrote them
        items.append({"id": entry["element_id_when_recorded"], "kind": "caption", "value": entry["text"], "language": "ta", "script": "Taml",
                      "bbox": [0.1, 0.38, 0.8, 0.04], "scene_id": f"mh-s{index}"})  # the film's scenes, not the key visual
    world = await build_world(client, demo=True, assets=False, items=items, lock=("mh-kv-logo", "mh-kv-packshot", "mh-kv-tagline"))

    run = await finish(client, world, "visual", {"region_code": "IN-TN", "language": "ta", "use_region_claims": False})
    assert run["status"] == "completed" and run["mode"] == "demo", run["error"]
    visual = (await output_of(client, world, run))["visual"]
    assert visual["source"] == "demo_fixture" and all(r["identical"] for r in visual["locked_regions"]) and len(visual["texts"]) == 7
    assert all(t["passed"] for t in visual["texts"]), [t for t in visual["texts"] if not t["passed"]]

    sound_run = await finish(client, world, "sound", {"region_code": "IN-TN", "language": "ta"})
    assert sound_run["status"] == "completed", sound_run["error"]
    sound = (await output_of(client, world, sound_run))["sound"]
    assert sound["source"] == "demo_fixture" and [x["element_id"] for x in sound["lines"]] == [
        "mh-vid-cap-1", "mh-vid-cap-2", "mh-vid-cap-3", "mh-vid-cap-4"]
    assert sound["total_duration_ms"] > 17_000 and not any(x["problems"] for x in sound["lines"])
    assert (await client.get(f"{API}/campaigns/{world.campaign}/remakes")).json()["total"] == 2
