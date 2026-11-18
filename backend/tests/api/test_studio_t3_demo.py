"""Creative Studio Tier 3 on the Aamod demo journey: one seed, then the planted Marathi claim, the transcreated versions, the key
visual and the film are read through the same endpoints the interface uses, with no provider and no network."""

from io import BytesIO
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from PIL import Image
from sqlalchemy import select

from app.core.auth import dev_user_id
from app.core.config import get_settings
from app.db import models as m
from app.db.session import read_session
from app.services.demo_journey import scene_uuid
from app.services.studio_t3_demo import seed_studio_t3_demo

API = "/api/v1"
PLANTED = "सर्वोत्तम"


@pytest.fixture
async def aamod(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The shared client with the Aamod seed on, and every outbound request refused: a pass shows no provider was reached."""
    monkeypatch.setenv("DEMO_SEED", "aamod")
    get_settings.cache_clear()
    with respx.mock(assert_all_called=False):
        yield client


async def get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, (path, response.text)
    return response.json()


async def check_of(client: httpx.AsyncClient, cid: str, version_id: str, **extra: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/campaigns/{cid}/claim-guard/checks", json={"version_id": version_id, **extra})
    assert response.status_code == 201, response.text
    return response.json()


async def test_the_aamod_journey_through_format_fit_claim_guard_and_script_check(aamod: httpx.AsyncClient) -> None:
    client = aamod
    project = (await client.post(f"{API}/projects/demo")).json()
    cid = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]["id"]
    versions = (await get(client, f"/campaigns/{cid}/versions", limit=100))["items"]
    by_label = {v["label"]: v["id"] for v in versions}
    root = next(v["id"] for v in versions if v["parent_id"] is None)
    final = {code: by_label[f"{name}: unsourced claim replaced"] for code, name in (("ta", "Tamil Nadu"), ("ml", "Kerala"), ("bn", "West Bengal"))}
    first = {code: by_label[f"Transcreation: {name}"] for code, name in (("ta", "Tamil (IN-TN)"), ("ml", "Malayalam (IN-KL)"), ("bn", "Bengali (IN-WB)"))}

    # -- Claim Guard: the planted claim is found by the wording rules, on the end card and on the key visual ---------------------------------
    rules = await check_of(client, cid, root)
    assert rules["mode"] == "rules" and rules["model"] is None and rules["counts"]["by_kind"] == {"superiority": 2}
    claims = {f["element_id"]: f for f in rules["findings"]}
    assert set(claims) == {"mh-vid-small-print", "mh-kv-small-print"}
    video_claim = claims["mh-vid-small-print"]
    assert video_claim["quote"] == PLANTED and video_claim["source"] == "rule" and video_claim["rule_id"] == "superiority.deva"
    assert video_claim["severity"] == "high" and video_claim["blocks_go"] and video_claim["confidence"] == "high" and video_claim["review"] is None
    assert video_claim["policy"]["status"] == "forbidden" and "Superiority" in video_claim["policy"]["rule"]
    assert video_claim["basis"] == {"stated": True, "wording": "पसंतीनुसार", "sourced": False} and video_claim["evidence"]["status"] == "none"
    assert {a["id"] for a in video_claim["ad_codes"]} >= {"asci-1-1", "asci-1-2"}
    assert video_claim["anchor"]["scene_id"] == str(scene_uuid(UUID(project["id"]), "mh-s5")) and video_claim["anchor"]["start_ms"] == 19912
    assert "महाराष्ट्रातील सर्वोत्तम फराळ टिन" in video_claim["phrase"] and claims["mh-kv-small-print"]["anchor"]["scene_id"] is not None

    # -- the optional second pass is a labelled fixture here, tagged as a model interpretation ----------------------------------------
    both = await check_of(client, cid, root, include_model_pass=True)
    assert both["mode"] == "rules_model" and both["model"]["provider"] == "fixture" and both["model"]["error"] is None and both["model"]["kept"] == 2
    model = [f for f in both["findings"] if f["source"] == "model"]
    assert {f["element_id"] for f in model} == {"mh-vid-cta-hook", "mh-kv-cta-hook"} and all(f["kind"] == "guarantee" and f["confidence"] == "low" for f in model)
    assert both["counts"]["total"] == 4 and both["counts"]["review_complete"] is False and [f["key"] for f in both["findings"] if f["source"] == "rule"] == [f["key"] for f in rules["findings"]]

    # -- the transcreations leave the small print alone, so the claim travels with them until the corrected versions replace it ----------
    for code in ("ta", "ml", "bn"):
        carried = [f for f in (await check_of(client, cid, first[code]))["findings"] if f["kind"] == "superiority"]
        assert {f["quote"] for f in carried} == {PLANTED} and all(f["policy"]["status"] == "forbidden" for f in carried), code
        assert (await check_of(client, cid, final[code]))["counts"]["by_kind"].get("superiority") is None, code

    # -- the demo hook seeds the same check the interface opens on ---------------------------------------------------------------------------
    check_id = await seed_studio_t3_demo(dev_user_id("alice"), UUID(cid), UUID(root))
    seeded = await get(client, f"/campaigns/{cid}/claim-guard/checks/{check_id}")
    assert seeded["mode"] == "rules_model" and seeded["counts"]["by_kind"] == {"superiority": 2, "guarantee": 2}

    # -- Script Check: the journey's own copy passes the real code checks; the back-translation and glossary are read ---------------------
    original = await get(client, f"/campaigns/{cid}/versions/{root}/script-check")
    assert original["counts"]["problem"] == 0 and original["counts"]["ok"] >= 20 and original["language"] == "mr" and original["glossary_terms"] >= 5
    names = {e["element_id"]: e for e in original["elements"]}
    caption = names["mh-vid-cap-3"]
    assert caption["status"] == "ok" and {t["term"] for t in caption["terms"]} >= {"Aamod Festive Tin"} and all(t["pronunciation"] is None or t["pronunciation"] for t in caption["terms"])
    assert caption["issues"] == [] and caption["anchor"]["scene_id"] and caption["anchor"]["bbox"]
    assert [s["element_id"] for s in original["skipped"]] == ["mh-vid-voiceover"]
    tamil = await get(client, f"/campaigns/{cid}/versions/{final['ta']}/script-check")
    assert tamil["counts"]["problem"] == 0 and tamil["language"] == "ta" and {e["expected_script"] for e in tamil["elements"]} <= {"Taml", "Latn"}
    back = {e["element_id"]: e["back_translation"] for e in tamil["elements"] if e["back_translation"]}
    assert back["mh-vid-cap-3"]["state"] == "current" and back["mh-vid-cap-3"]["clean"] is True and back["mh-vid-cap-3"]["text"].startswith("That same taste")
    assert back["mh-vid-cta-hook"]["state"] == "edited" and back["mh-vid-cta-hook"]["clean"] is None  # a Tweak Chip changed it after the transcreation
    edited_hook = next(e for e in tamil["elements"] if e["element_id"] == "mh-vid-cta-hook")
    assert edited_hook["native_review_recommended"] is True
    kerala = await get(client, f"/campaigns/{cid}/versions/{final['ml']}/script-check")
    variant = next(i for e in kerala["elements"] for i in e["issues"] if i["code"] == "glossary_variant")
    assert variant["severity"] == "review" and "grammatical ending" in variant["message"] and kerala["counts"]["review"] >= 1

    # -- Format Fit: the key visual and the film ---------------------------------------------------------------------------------------------
    async with read_session() as s:
        creatives = {c.kind: c for c in (await s.execute(select(m.CreativeAsset))).scalars()}
    picture, film = str(creatives["image"].id), str(creatives["video"].id)
    plans = (await client.post(f"{API}/campaigns/{cid}/format-fit/plans", json={"creative_id": picture, "version_id": root})).json()
    assert plans["source"]["width"] == 1080 and plans["source"]["height"] == 1350 and plans["locked_element_ids"] == ["mh-kv-logo", "mh-kv-packshot", "mh-kv-tagline"]
    by_format = {p["format"]["id"]: p for p in plans["plans"]}
    assert by_format["4x5"]["recommended"] == "native" and by_format["9x16"]["recommended"] == "pad"
    nine = {s["strategy"]: s for s in by_format["9x16"]["strategies"]}
    assert nine["crop"]["verdict"] == "conflict" and not nine["crop"]["applicable"] and nine["pad"]["applicable"]
    small = next(e for e in nine["pad"]["elements"] if e["element_id"] == "mh-kv-small-print")
    assert small["in_safe_zone"] is False and small["text_height_px"] < small["min_text_px"]
    catalogue = await get(client, f"/campaigns/{cid}/format-fit/formats")
    assert {c["id"]: c["format_id"] for c in catalogue["channels"]} == {"instagram_reels": "9x16", "youtube_shorts": "9x16", "meta_feed": "4x5"}
    output = (await client.post(f"{API}/campaigns/{cid}/format-fit/outputs", json={
        "creative_id": picture, "version_id": root, "format_id": "1x1", "strategy": "pad"}))
    assert output.status_code == 201, output.text
    pixels = Image.open(BytesIO((await client.get(f"{API}/assets/{output.json()['asset']['id']}/content")).content))
    assert pixels.size == (1080, 1080) and output.json()["background"].startswith("#")
    cut_down = (await client.post(f"{API}/campaigns/{cid}/format-fit/plans", json={"creative_id": film, "version_id": root})).json()
    assert [p["format"]["id"] for p in cut_down["plans"]] == ["9x16"] and cut_down["plans"][0]["strategies"][0]["strategy"] == "native"
    end_card = str(scene_uuid(UUID(project["id"]), "mh-s5"))
    targets = {c["target_ms"]: c for c in cut_down["cutdowns"]}
    assert set(targets) == {6000, 15000, 20000} and all(c["segments"][-1]["scene_id"] == end_card for c in targets.values())
    assert targets[6000]["segments"][0]["trimmed"] and all(c["duration_ms"] <= c["target_ms"] for c in targets.values())
    assert any("End card" in r for r in targets[15000]["segments"][-1]["reasons"])
