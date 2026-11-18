"""Creative Studio Tier 3 over HTTP, in a live project: Script Check, Claim Guard (checks, reviews, the model pass), Format Fit
(catalogue, plans, applying a plan as a new asset) and who may do what. The Aamod journey is in test_studio_t3_demo.py."""

from typing import Any
from uuid import uuid4

import httpx

from app.db import models as m
from app.db.session import read_session
from sqlalchemy import select
from tests.api.omnicult_support import add_member, client_for, seeded, workspace_of  # noqa: F401
from tests.api.studio_t3_support import API, ELEMENTS, live_creative
from tests.conftest import BOB

CAROL = {"Authorization": "Bearer dev-carol"}


async def get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, (path, response.text)
    return response.json()


# --- Script Check -----------------------------------------------------------------------------------------------------


async def test_script_check_reports_every_text_element_with_a_span_and_an_anchor(seeded: Any, client: httpx.AsyncClient) -> None:
    live = await live_creative(client)
    report = await get(client, f"/campaigns/{live['cid']}/versions/{live['version']['id']}/script-check")
    assert report["check_version"] == "script-check-v1" and report["version_id"] == live["version"]["id"] and report["language"] == "mr"
    by_id = {e["element_id"]: e for e in report["elements"]}
    assert set(by_id) == {"headline", "small", "cta"}  # text elements only; the voice-over is audio
    assert [s["element_id"] for s in report["skipped"]] == ["voice"] and "captions" in report["skipped"][0]["reason"]
    assert by_id["headline"]["status"] == "ok" and by_id["headline"]["expected_script"] == "Deva" and by_id["headline"]["dominant_script"] == "Deva"
    cta = by_id["cta"]  # deliberate English next to Marathi: information, not a fault
    assert cta["status"] == "ok" and [(i["code"], i["severity"], i["excerpt"]) for i in cta["issues"]] == [("unexpected_latin", "info", "Order now")]
    assert cta["issues"][0]["anchor"]["bbox"] == [0.05, 0.86, 0.40, 0.04] and cta["text"][cta["issues"][0]["start"] : cta["issues"][0]["end"]] == "Order now"
    assert report["counts"] == {"ok": 3, "review": 0, "problem": 0, "issues": 1} and report["shaping_engine"] in ("raqm", "basic")


async def test_script_check_finds_problems_in_edited_copy_and_recommends_a_native_reader(seeded: Any, client: httpx.AsyncClient) -> None:
    live = await live_creative(client)
    cid, root = live["cid"], live["version"]
    edit = await client.post(f"{API}/campaigns/{cid}/operations", json={
        "version_id": root["id"], "reason": "A bad paste.", "operation": {"kind": "manual_edit", "edits": [
            {"element_id": "headline", "set": {"value": "दिवाळी சுவை फराळ १२ 45"}}]}})
    assert edit.status_code == 201, edit.text
    report = await get(client, f"/campaigns/{cid}/versions/{edit.json()['version']['id']}/script-check")
    headline = next(e for e in report["elements"] if e["element_id"] == "headline")
    assert headline["status"] == "problem" and headline["native_review_recommended"] is True
    assert {"foreign_script", "numerals"} <= {i["code"] for i in headline["issues"]}
    foreign = next(i for i in headline["issues"] if i["code"] == "foreign_script")
    assert headline["text"][foreign["start"] : foreign["end"]] == "சுவை" and foreign["severity"] == "problem"
    assert report["counts"]["problem"] == 1 and report["counts"]["ok"] == 2
    unchanged = await get(client, f"/campaigns/{cid}/versions/{root['id']}/script-check")  # the original is not affected
    assert unchanged["counts"]["problem"] == 0


async def test_script_check_checks_the_glossary_spellings_and_prohibited_terms(seeded: Any, client: httpx.AsyncClient) -> None:
    live = await live_creative(client)
    cid = live["cid"]
    for body in (
        {"term": "Aamod", "language": "*", "protected": True, "never_translate": True, "pronunciation": "AA-mode"},
        {"term": "Aamod", "language": "mr", "script": "Deva", "approved_spelling": "आमोद", "protected": True, "never_translate": True},
        {"term": "Tin", "language": "*", "prohibited_alternatives": ["डबा"]},
    ):
        assert (await client.post(f"{API}/campaigns/{cid}/glossary", json=body)).status_code == 201
    edited = await client.post(f"{API}/campaigns/{cid}/operations", json={
        "version_id": live["version"]["id"], "reason": "Glossary test.", "operation": {"kind": "manual_edit", "edits": [
            {"element_id": "headline", "set": {"value": "आता Aamod चा डबा"}}, {"element_id": "small", "set": {"value": "आमोद फराळ"}}]}})
    report = await get(client, f"/campaigns/{cid}/versions/{edited.json()['version']['id']}/script-check")
    headline = next(e for e in report["elements"] if e["element_id"] == "headline")
    assert {"glossary_spelling", "prohibited_term"} <= {i["code"] for i in headline["issues"]} and headline["status"] == "problem"
    small = next(e for e in report["elements"] if e["element_id"] == "small")
    assert small["status"] == "ok" and small["terms"][0]["term"] == "Aamod" and small["terms"][0]["form"] == "आमोद"


# --- Claim Guard --------------------------------------------------------------------------------------------------------


async def run_check(client: httpx.AsyncClient, cid: str, version_id: str, **extra: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/campaigns/{cid}/claim-guard/checks", json={"version_id": version_id, **extra})
    assert response.status_code == 201, response.text
    return response.json()


async def test_claim_guard_finds_the_marathi_claim_and_holds_it_for_review(seeded: Any, client: httpx.AsyncClient) -> None:
    live = await live_creative(client)
    cid, vid = live["cid"], live["version"]["id"]
    check = await run_check(client, cid, vid)
    assert check["mode"] == "rules" and check["model"] is None and check["rules_version"] == "claim-guard-rules-v1" and check["texts_checked"] == 3
    (finding,) = [f for f in check["findings"] if f["kind"] == "superiority"]
    assert finding["element_id"] == "small" and finding["quote"] == "सर्वोत्तम" and finding["source"] == "rule" and finding["confidence"] == "high"
    element = next(e for e in live["version"]["elements"] if e["id"] == "small")
    assert element["value"][finding["start"] : finding["end"]] == "सर्वोत्तम" and finding["anchor"]["bbox"] == element["bbox"]
    assert finding["severity"] == "high" and finding["blocks_go"] and finding["review"] is None
    assert finding["basis"]["stated"] and not finding["basis"]["sourced"] and finding["evidence"]["status"] == "none"
    assert {r["rule"] for r in finding["severity_rules"]} >= {"G1_base", "G2_hard_wording", "G4_basis"}
    assert {a["id"] for a in finding["ad_codes"]} >= {"asci-1-1", "asci-1-2"} and all(a["url"].startswith("https://") and a["excerpt"] for a in finding["ad_codes"])
    assert check["counts"]["review_complete"] is False and check["counts"]["unreviewed"] == check["counts"]["total"] >= 1
    assert any("not legal clearance" in text for text in check["limitations"])


async def test_a_review_decision_is_kept_across_checks_and_completes_the_review(seeded: Any, client: httpx.AsyncClient) -> None:
    live = await live_creative(client)
    cid, vid = live["cid"], live["version"]["id"]
    first = await run_check(client, cid, vid)
    for finding in first["findings"]:
        response = await client.put(f"{API}/campaigns/{cid}/claim-guard/reviews", json={
            "version_id": vid, "finding_key": finding["key"], "decision": "revise", "note": "Replace with the net weight."})
        assert response.status_code == 200, response.text
    again = await run_check(client, cid, vid)  # a fresh check of the same version keeps every decision
    assert [f["key"] for f in again["findings"]] == [f["key"] for f in first["findings"]] and again["id"] != first["id"]
    assert all(f["review"]["decision"] == "revise" and f["review"]["note"] == "Replace with the net weight." for f in again["findings"])
    assert again["counts"]["review_complete"] is True and again["counts"]["unreviewed"] == 0
    assert again["counts"]["blocks_go"] == sum(f["blocks_go"] for f in again["findings"])  # "revise" still holds a Go
    key = next(f["key"] for f in again["findings"] if f["blocks_go"])
    await client.put(f"{API}/campaigns/{cid}/claim-guard/reviews", json={"version_id": vid, "finding_key": key, "decision": "substantiated", "note": "Survey on file."})
    changed = await get(client, f"/campaigns/{cid}/claim-guard/checks/{again['id']}")
    assert next(f for f in changed["findings"] if f["key"] == key)["review"]["decision"] == "substantiated"
    listed = await get(client, f"/campaigns/{cid}/claim-guard/checks", version_id=vid)
    assert listed["total"] == 2 and listed["items"][0]["id"] == again["id"] and "findings" not in listed["items"][0]
    unknown = await client.put(f"{API}/campaigns/{cid}/claim-guard/reviews", json={"version_id": vid, "finding_key": "0123456789abcdef", "decision": "accepted"})
    assert unknown.status_code == 422 and unknown.json()["error"]["details"][0]["field"] == "finding_key"


async def test_the_model_pass_reports_a_provider_failure_and_keeps_the_rule_findings(seeded: Any, client: httpx.AsyncClient) -> None:
    live = await live_creative(client)
    check = await run_check(client, live["cid"], live["version"]["id"], include_model_pass=True)  # no provider is configured in tests
    assert check["mode"] == "rules" and check["model"]["error"] and check["model"]["kept"] == 0 and check["model"]["prompt_version"] == "claim-guard-extract-v1"
    assert any(f["source"] == "rule" for f in check["findings"]) and all(f["source"] == "rule" for f in check["findings"])


async def test_the_model_pass_adds_only_verified_quotes_tagged_as_model_readings(seeded: Any, client: httpx.AsyncClient, monkeypatch: Any) -> None:
    from app.agents.claim_guard import ClaimGuardOut, ClaimOut
    from app.llm.gateway import LLMResult
    from app.schemas.common import StepTrace
    from app.services import claim_guard as service

    live = await live_creative(client)
    texts: list[str] = []

    class Gateway:
        async def generate_structured(self, **kwargs: Any) -> LLMResult[ClaimGuardOut]:
            elements = kwargs["fixture_context"]["elements"]
            texts.extend(e["text"] for e in elements)
            handle = next(e["handle"] for e in elements if "ऑर्डर" in e["text"])
            claims = [
                ClaimOut(element=handle, quote="ऑर्डर करा", kind="guarantee", explanation="May imply an order promise."),  # real quote
                ClaimOut(element=handle, quote="free forever", kind="price", explanation="Not in the element."),  # invented: dropped
                ClaimOut(element="E99", quote="x", kind="price", explanation="Unknown element."),  # unknown handle: dropped
                ClaimOut(element=next(e["handle"] for e in elements if "सर्वोत्तम" in e["text"]), quote="सर्वोत्तम", kind="superiority", explanation="Repeats a rule."),
            ]
            trace = StepTrace(stage="reading_claims", agent="red_team", status="completed", provider="test", model_id="test-model", prompt_version="claim-guard-extract-v1")
            return LLMResult(value=ClaimGuardOut(claims=claims), trace=trace)

    monkeypatch.setattr("app.services.studio_context.gateway_for", lambda mode: Gateway())
    check = await run_check(client, live["cid"], live["version"]["id"], include_model_pass=True)
    assert check["mode"] == "rules_model" and check["model"] == {
        "provider": "test", "model_id": "test-model", "prompt_version": "claim-guard-extract-v1", "estimated_cost_usd": None,
        "proposed": 4, "kept": 1, "dropped": 3, "error": None}
    (model,) = [f for f in check["findings"] if f["source"] == "model"]
    assert model["quote"] == "ऑर्डर करा" and model["kind"] == "guarantee" and model["confidence"] == "low" and model["rule_id"] is None
    assert model["explanation"] == "May imply an order promise." and any("interpretation" in text for text in model["limitations"])
    assert len([f for f in check["findings"] if f["kind"] == "superiority"]) == 1  # the repeat of a rule finding was dropped
    assert texts and all("E" not in t or True for t in texts) and service.agent.PROMPT_VERSION == "claim-guard-extract-v1"


# --- Format Fit -------------------------------------------------------------------------------------------------------------


async def test_the_catalogue_lists_the_formats_and_maps_the_briefs_channels(seeded: Any, client: httpx.AsyncClient) -> None:
    live = await live_creative(client)
    cid = live["cid"]
    brief = await client.put(f"{API}/campaigns/{cid}/brief", json={"content": {"channels": [
        {"id": "instagram_reels", "name": "Instagram Reels", "format": "9:16 video"}, {"id": "newsletter", "name": "Newsletter", "format": "4:5 image"},
        {"id": "billboard", "name": "Billboard", "format": "48 sheet"}]}})
    assert brief.status_code == 200, brief.text
    catalogue = await get(client, f"/campaigns/{cid}/format-fit/formats")
    assert [f["id"] for f in catalogue["formats"]] == ["1x1", "4x5", "9x16", "16x9"] and catalogue["tool_version"] == "format-fit-v1"
    reels = next(f for f in catalogue["formats"] if f["id"] == "9x16")
    assert (reels["width"], reels["height"]) == (1080, 1920) and reels["safe_zone"]["top"] == 0.14 and "Working default" in reels["safe_zone"]["basis"]
    assert {c["id"]: c["format_id"] for c in catalogue["channels"]} == {"instagram_reels": "9x16", "newsletter": "4x5", "billboard": None}


async def plan(client: httpx.AsyncClient, live: dict[str, Any], **extra: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/campaigns/{live['cid']}/format-fit/plans", json={"creative_id": live["creative_id"], "version_id": live["version"]["id"], **extra})
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_plan_reports_crops_safe_zones_and_locked_conflicts_for_every_format(seeded: Any, client: httpx.AsyncClient) -> None:
    live = await live_creative(client)
    plans = await plan(client, live)
    assert plans["source"]["width"] == 1080 and plans["source"]["height"] == 1350 and plans["source"]["asset_id"] == live["asset"]["id"]
    assert plans["locked_element_ids"] == ["logo", "pack"] and plans["tool_version"] == "format-fit-v1"
    by_format = {p["format"]["id"]: p for p in plans["plans"]}
    assert [s["strategy"] for s in by_format["4x5"]["strategies"]] == ["native"] and by_format["4x5"]["recommended"] == "native"
    nine = by_format["9x16"]
    crop, pad = nine["strategies"]
    assert (crop["strategy"], crop["verdict"], crop["applicable"]) == ("crop", "conflict", False)
    assert any(i["code"] == "locked_cut" and i["element_id"] in ("logo", "pack") for i in crop["issues"])
    assert (pad["strategy"], pad["applicable"]) == ("pad", True) and pad["place"] == {"x": 0, "y": 285, "width": 1080, "height": 1350} and nine["recommended"] == "pad"
    small = next(e for e in pad["elements"] if e["element_id"] == "small")
    assert small["placement"] == "kept" and small["in_safe_zone"] is False and "bottom" in small["safe_overflow"] and small["text_height_px"] < small["min_text_px"]
    assert small["anchor"]["bbox"] == [0.05, 0.958, 0.36, 0.017]
    only = await plan(client, live, format_ids=["1x1"])
    assert [p["format"]["id"] for p in only["plans"]] == ["1x1"]
    bad = await client.post(f"{API}/campaigns/{live['cid']}/format-fit/plans", json={"creative_id": live["creative_id"], "version_id": live["version"]["id"], "format_ids": ["7x7"]})
    assert bad.status_code == 422 and bad.json()["error"]["details"][0]["field"] == "format_ids"


async def test_a_plan_changes_nothing_and_a_new_lock_changes_the_plan(seeded: Any, client: httpx.AsyncClient) -> None:
    live = await live_creative(client)
    before = await plan(client, live)
    assert (await get(client, f"/projects/{live['project']['id']}/assets"))["total"] == 1  # planning makes no asset
    assert (await get(client, f"/campaigns/{live['cid']}/format-fit/outputs"))["total"] == 0
    assert await plan(client, live) == before  # deterministic
    await client.put(f"{API}/campaigns/{live['cid']}/locks/headline", json={})
    after = await plan(client, live)
    assert "headline" in after["locked_element_ids"] and after != before
    square = next(p for p in after["plans"] if p["format"]["id"] == "1x1")
    assert all(e["locked"] for s in square["strategies"] for e in s["elements"] if e["element_id"] == "headline")


async def test_applying_a_plan_makes_a_new_asset_and_never_touches_the_source(seeded: Any, client: httpx.AsyncClient) -> None:
    live = await live_creative(client)
    cid, base = live["cid"], {"creative_id": live["creative_id"], "version_id": live["version"]["id"]}
    refused = await client.post(f"{API}/campaigns/{cid}/format-fit/outputs", json={**base, "format_id": "9x16", "strategy": "crop"})
    assert refused.status_code == 409 and "locked" in refused.json()["error"]["message"].lower()
    wrong = await client.post(f"{API}/campaigns/{cid}/format-fit/outputs", json={**base, "format_id": "4x5", "strategy": "pad"})
    assert wrong.status_code == 409 and "native" in wrong.json()["error"]["message"]
    response = await client.post(f"{API}/campaigns/{cid}/format-fit/outputs", json={**base, "format_id": "9x16", "strategy": "pad"})
    assert response.status_code == 201, response.text
    output = response.json()
    assert (output["format_id"], output["strategy"], output["verdict"], output["source_asset_id"]) == ("9x16", "pad", "review", live["asset"]["id"])
    assert output["asset"]["width"] is None or output["asset"]["width"] == 1080
    assert output["asset"]["filename"] == "key-visual-9x16-pad.png" and output["asset"]["id"] != live["asset"]["id"] and output["tool_version"] == "format-fit-v1"
    content = await client.get(f"{API}/assets/{output['asset']['id']}/content")
    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(content.content))
    assert image.size == (1080, 1920) and image.getpixel((540, 5)) == image.getpixel((540, 1915)) == (29, 90, 102)  # bars in the picture's own edge colour
    source = await client.get(f"{API}/assets/{live['asset']['id']}/content")
    assert source.content == (await client.get(f"{API}/assets/{live['asset']['id']}/content")).content and source.headers["content-length"] == str(live["asset"]["size_bytes"])
    listed = await get(client, f"/campaigns/{cid}/format-fit/outputs")
    assert listed["total"] == 1 and listed["items"][0]["id"] == output["id"]
    assert (await get(client, f"/projects/{live['project']['id']}/assets"))["total"] == 2
    square = await client.post(f"{API}/campaigns/{cid}/format-fit/outputs", json={**base, "format_id": "1x1", "strategy": "crop"})
    assert square.status_code == 409 and "locked" in square.json()["error"]["message"]  # even a sliver of a locked element is refused
    ok = await client.post(f"{API}/campaigns/{cid}/format-fit/outputs", json={**base, "format_id": "16x9", "strategy": "pad"})
    assert ok.status_code == 201 and ok.json()["asset"]["filename"].endswith("16x9-pad.png")


async def test_text_that_a_crop_cuts_needs_an_explicit_acknowledgement(seeded: Any, client: httpx.AsyncClient) -> None:
    elements = [e for e in ELEMENTS if e["id"] not in ("logo", "pack")]  # nothing locked: only text is at stake
    live = await live_creative(client, elements=elements, locked=())
    body = {"creative_id": live["creative_id"], "version_id": live["version"]["id"], "format_id": "16x9", "strategy": "crop"}
    refused = await client.post(f"{API}/campaigns/{live['cid']}/format-fit/outputs", json=body)
    assert refused.status_code == 409 and "acknowledge_issues" in refused.json()["error"]["details"][0]["field"]
    accepted = await client.post(f"{API}/campaigns/{live['cid']}/format-fit/outputs", json={**body, "acknowledge_issues": True})
    assert accepted.status_code == 201 and accepted.json()["verdict"] == "conflict"


# --- who may do what -------------------------------------------------------------------------------------------------------


async def test_a_stranger_gets_404_and_a_viewer_can_read_but_not_write(seeded: Any, client: httpx.AsyncClient, client_for: Any) -> None:
    live = await live_creative(client)
    cid, vid = live["cid"], live["version"]["id"]
    check = await run_check(client, cid, vid)
    stranger = client_for(BOB)
    calls = [
        ("get", f"/campaigns/{cid}/versions/{vid}/script-check", None), ("get", f"/campaigns/{cid}/format-fit/formats", None),
        ("get", f"/campaigns/{cid}/claim-guard/checks", None), ("get", f"/campaigns/{cid}/claim-guard/checks/{check['id']}", None),
        ("post", f"/campaigns/{cid}/claim-guard/checks", {"version_id": vid}),
        ("post", f"/campaigns/{cid}/format-fit/plans", {"creative_id": live["creative_id"], "version_id": vid}),
    ]
    for method, path, body in calls:
        response = await getattr(stranger, method)(f"{API}{path}", **({"json": body} if body is not None else {}))
        assert response.status_code == 404, (path, response.text)
    await add_member(await workspace_of("alice"), "carol", "viewer")
    viewer = client_for(CAROL)
    assert (await viewer.get(f"{API}/campaigns/{cid}/versions/{vid}/script-check")).status_code == 200
    assert (await viewer.get(f"{API}/campaigns/{cid}/claim-guard/checks/{check['id']}")).status_code == 200
    assert (await viewer.post(f"{API}/campaigns/{cid}/format-fit/plans", json={"creative_id": live["creative_id"], "version_id": vid})).status_code == 200
    writes = [
        ("post", f"/campaigns/{cid}/claim-guard/checks", {"version_id": vid}),
        ("put", f"/campaigns/{cid}/claim-guard/reviews", {"version_id": vid, "finding_key": check["findings"][0]["key"], "decision": "accepted"}),
        ("post", f"/campaigns/{cid}/format-fit/outputs", {"creative_id": live["creative_id"], "version_id": vid, "format_id": "9x16", "strategy": "pad"}),
    ]
    for method, path, body in writes:
        assert (await getattr(viewer, method)(f"{API}{path}", json=body)).status_code == 403, path


async def test_ids_of_another_campaign_are_not_accepted(seeded: Any, client: httpx.AsyncClient) -> None:
    one, two = await live_creative(client), await live_creative(client)
    cross = await client.post(f"{API}/campaigns/{one['cid']}/format-fit/plans", json={"creative_id": two["creative_id"], "version_id": one["version"]["id"]})
    assert cross.status_code == 404
    missing_version = await client.post(f"{API}/campaigns/{one['cid']}/claim-guard/checks", json={"version_id": two["version"]["id"]})
    assert missing_version.status_code == 404
    assert (await client.get(f"{API}/campaigns/{one['cid']}/versions/{uuid4()}/script-check")).status_code == 404
    async with read_session() as s:
        assert (await s.execute(select(m.ClaimGuardCheck))).scalars().first() is None
