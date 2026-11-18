"""Campaign Desk: the versioned brief, the Brand Kit, the demo seam (with the real fixture files) and the Today view."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.db import models as m
from app.db.session import read_session, session
from app.schemas import desk as v
from app.services import desk
from tests.api.delivery_support import add_version
from tests.api.launch_support import observations_json
from tests.api.omnicult_support import API, add_member, client_for, draft, put_claims, seeded, source  # noqa: F401
from tests.api.test_crud import make_campaign, make_project
from tests.conftest import BOB

FIXTURES = Path(__file__).resolve().parents[2] / "app" / "fixtures" / "omnicult_demo"
BRIEF_FIXTURE = json.loads((FIXTURES / "campaign_brief.json").read_text(encoding="utf-8"))
KIT_FIXTURE = json.loads((FIXTURES / "brand_kit.json").read_text(encoding="utf-8"))


async def live_campaign(client: httpx.AsyncClient) -> dict[str, Any]:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    return {"project": project, "id": campaign["id"], "brief": f"{API}/campaigns/{campaign['id']}/brief"}


def fixture_brief(**changes: Any) -> dict[str, Any]:
    """The fixture brief as a person would send it to a live project: the budget label is the author's (here: real numbers)."""
    brief = desk.brief_from_fixture(BRIEF_FIXTURE).model_dump(mode="json")
    brief["budget"]["sample"] = False
    return brief | changes


# --- brief --------------------------------------------------------------------------------------------------


async def test_a_campaign_without_a_brief_reads_version_zero_derived_from_the_campaign(client: httpx.AsyncClient) -> None:
    c = await live_campaign(client)
    brief = (await client.get(c["brief"])).json()
    assert (brief["version"], brief["saved"], brief["version_count"]) == (0, False, 0)
    assert brief["completeness"]["complete"] is False and "objective" in brief["completeness"]["missing"]
    assert brief["editable"] is True and brief["locked_reason"] is None and brief["created_at"] is None


async def test_saving_versions_the_brief_and_mirrors_regions_and_objective_onto_the_campaign(client: httpx.AsyncClient) -> None:
    c = await live_campaign(client)
    saved = await client.put(c["brief"], json={"content": fixture_brief(), "change_note": "First full brief", "expected_version": 0})
    assert saved.status_code == 200, saved.text
    brief = saved.json()
    assert (brief["version"], brief["saved"], brief["change_note"]) == (1, True, "First full brief")
    assert brief["completeness"] == {"complete": True, "missing": [], "filled": 8, "required": 8}
    assert brief["content"]["budget"]["sample"] is False  # a live project keeps the author's label
    assert brief["content"]["languages"]["IN-TN"] == ["ta", "en"] and brief["content"]["scripts"]["IN-KL"] == ["Mlym", "Latn"]

    campaign = (await client.get(f"{API}/campaigns/{c['id']}")).json()
    assert campaign["objective"] == BRIEF_FIXTURE["objective"]
    assert [t["display_name"] for t in campaign["target_markets"]] == ["Tamil Nadu", "Kerala", "West Bengal"]
    assert all(set(t) == {"country_code", "display_name"} for t in campaign["target_markets"])  # the Market contract stays country-level
    async with read_session() as s:
        stored = await s.scalar(select(m.Campaign.target_markets).where(m.Campaign.id == UUID(c["id"])))
    assert [t["region_code"] for t in stored] == ["IN-TN", "IN-KL", "IN-WB"]  # what services.campaign_regions reads

    unchanged = (await client.put(c["brief"], json={"content": fixture_brief()})).json()
    assert unchanged["version"] == 1  # identical content adds no version
    changed = (await client.put(c["brief"], json={"content": fixture_brief(objective="A shorter objective."), "change_note": "Tighten the objective", "expected_version": 1})).json()
    assert changed["version"] == 2 and changed["version_count"] == 2

    versions = (await client.get(f"{c['brief']}/versions")).json()
    assert [x["version"] for x in versions["items"]] == [2, 1] and versions["items"][0]["changed_fields"] == ["objective"]
    assert "regions" in versions["items"][1]["changed_fields"]  # the first version reports what it set
    old = (await client.get(f"{c['brief']}/versions/1")).json()
    assert old["content"]["objective"] == BRIEF_FIXTURE["objective"] and old["version"] == 1
    assert (await client.get(f"{c['brief']}/versions/9")).status_code == 404


async def test_a_stale_editor_gets_409_instead_of_overwriting(client: httpx.AsyncClient) -> None:
    c = await live_campaign(client)
    await client.put(c["brief"], json={"content": fixture_brief()})
    stale = await client.put(c["brief"], json={"content": fixture_brief(objective="Mine"), "expected_version": 0})
    assert stale.status_code == 409 and "version 1 is now current" in stale.json()["error"]["message"]


async def test_invalid_briefs_are_rejected_with_the_field_that_is_wrong(client: httpx.AsyncClient) -> None:
    c = await live_campaign(client)
    good = fixture_brief()

    async def reject(content: dict[str, Any], needle: str) -> None:
        response = await client.put(c["brief"], json={"content": content})
        assert response.status_code == 422, (needle, response.text)
        assert needle in json.dumps(response.json()), response.text

    await reject(good | {"regions": {"origin": "IN-MH", "targets": ["IN-ZZ"]}}, "not an Indian state")
    await reject(good | {"regions": {"origin": "IN-MH", "targets": ["IN-MH"]}}, "not also a target")
    await reject(good | {"languages": {**good["languages"], "IN-GJ": ["gu"]}}, "neither the origin nor a target")
    await reject(good | {"scripts": {**good["scripts"], "IN-TN": ["Deva"]}}, "is written in Taml")
    await reject(good | {"budget": {**good["budget"], "total": 1000.0}}, "more than the total")
    await reject(good | {"dates": {**good["dates"], "end": "2027-09-01"}}, "cannot end before it starts")
    await reject(good | {"dates": {**good["dates"], "sources": []}}, "unknown sources")
    await reject(good | {"dates": {**good["dates"], "sources": [{**good["dates"]["sources"][0], "url": "javascript:alert(1)"}, good["dates"]["sources"][1]]}}, "url")
    await reject(good | {"channels": [good["channels"][0], good["channels"][0]]}, "Channel ids must be unique")
    await reject(good | {"unknown": 1}, "unknown")
    assert (await client.get(c["brief"])).json()["version"] == 0  # nothing was saved


async def test_roles_and_tenancy_apply_to_the_brief(client: httpx.AsyncClient, client_for: Any) -> None:
    c = await live_campaign(client)
    assert (await client_for(BOB).get(c["brief"])).status_code == 404  # another workspace cannot tell it exists
    await add_member(UUID(c["project"]["workspace_id"]), "bob", "viewer")
    viewer = client_for(BOB)
    read = (await viewer.get(c["brief"])).json()
    assert read["editable"] is False and "read-only" in read["locked_reason"]
    assert (await viewer.put(c["brief"], json={"content": fixture_brief()})).status_code == 403


async def test_a_demo_project_brief_is_read_only_and_its_budget_is_always_sample(client: httpx.AsyncClient) -> None:
    project = (await client.post(f"{API}/projects/demo")).json()
    campaign = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]
    url = f"{API}/campaigns/{campaign['id']}/brief"
    brief = (await client.get(url)).json()
    assert brief["mode"] == "demo" and brief["editable"] is False and "fixed" in brief["locked_reason"]
    assert (await client.put(url, json={"content": fixture_brief()})).status_code == 409


# --- demo seam (real fixture files) ---------------------------------------------------------------------------


async def seed_demo(client: httpx.AsyncClient) -> dict[str, Any]:
    c = await live_campaign(client)
    async with session() as s, s.begin():
        await desk.apply_demo_brief_and_brand(
            s, project_id=UUID(c["project"]["id"]), campaign_id=UUID(c["id"]), brief=BRIEF_FIXTURE, brand_kit=KIT_FIXTURE
        )
    return c


async def test_the_seam_maps_both_fixture_files_onto_the_schema(client: httpx.AsyncClient) -> None:
    c = await seed_demo(client)
    brief = (await client.get(c["brief"])).json()
    content = brief["content"]
    assert brief["version"] == 1 and brief["provenance"]["source"] == "demo_fixture" and "Demonstration fixture" in brief["provenance"]["label"]
    assert brief["completeness"]["complete"] is True
    assert content["regions"] == {"origin": "IN-MH", "targets": ["IN-TN", "IN-KL", "IN-WB"]}
    assert content["languages"] == BRIEF_FIXTURE["languages"] and content["scripts"] == BRIEF_FIXTURE["scripts"]
    assert [ch["id"] for ch in content["channels"]] == [ch["id"] for ch in BRIEF_FIXTURE["channels"]]
    assert content["channels"][0]["creative_ref"] == "demo-creative-aamod-mh-video"
    assert content["budget"]["sample"] is True and content["budget"]["total"] == 2400000 and sum(content["budget"]["by_region"].values()) == 2400000
    assert content["dates"]["start"] == "2027-10-04" and len(content["dates"]["key_moments"]) == 5 and len(content["dates"]["sources"]) == 2
    assert content["success_metric"]["primary"]["id"] == "cost_per_order" and len(content["success_metric"]["secondary"]) == 2
    assert content["product"]["price"] == {"currency": "INR", "amount": 899} and content["cta"]["original"]["region_code"] == "IN-MH"
    assert content["original_creative_refs"] == BRIEF_FIXTURE["original_creative_ids"] and len(content["constraints"]) == 4

    campaign = (await client.get(f"{API}/campaigns/{c['id']}")).json()
    assert campaign["name"] == BRIEF_FIXTURE["name"] and campaign["objective"] == BRIEF_FIXTURE["objective"]
    assert [t["display_name"] for t in campaign["target_markets"]] == ["Tamil Nadu", "Kerala", "West Bengal"]

    kit = (await client.get(f"{API}/projects/{c['project']['id']}/brand-kit")).json()
    design = kit["design"]
    assert (kit["revision"], kit["saved"], kit["provenance"]["source"]) == (1, True, "demo_fixture")
    assert kit["name"] == "Aamod" and kit["voice"] == KIT_FIXTURE["tone_of_voice"]["traits"]
    assert kit["protected_terms"] == [t["term"] for t in KIT_FIXTURE["protected_terms"]]
    assert design["fictional"] is True and design["tagline"]["locked"] is True and design["tagline"]["translate"] is False
    assert [x["id"] for x in design["logo"]["lockups"]] == ["primary", "reversed", "stacked", "mark"]
    assert design["logo"]["lockups"][0]["source_path"] == "brand/logo.png" and design["logo"]["lockups"][0]["vector_path"] == "brand/logo.svg"
    assert len(design["colours"]) == 6 and len(design["fonts"]) == 10 and len(design["never_change"]) == 3 and len(design["product_images"]) == 2
    assert design["never_change"][1]["regions"] == {"medallion_bbox": [0.3182, 0.4355, 0.3622, 0.3925]}
    assert design["claims_policy"]["forbidden"] and design["tone_of_voice"]["dont"]
    brand = (await client.get(f"{API}/projects/{c['project']['id']}/brand")).json()
    assert brand["name"] == "Aamod" and brand["voice"] == kit["voice"] and brand["target_audience"].startswith("Adults who buy")
    assert any("Do not claim" in x for x in brand["constraints"]) and brand["approved_examples"][0]["text"] == "Every bond, a little sweeter."


async def test_contrast_is_calculated_and_matches_the_ratios_the_fixture_declares(client: httpx.AsyncClient) -> None:
    c = await seed_demo(client)
    kit = (await client.get(f"{API}/projects/{c['project']['id']}/brand-kit")).json()
    declared = {(p["text"], p["background"]): p["ratio"] for p in KIT_FIXTURE["contrast"]["pairs"]}
    got = {(r["text"], r["background"]): r for r in kit["contrast"]}
    assert set(got) == set(declared)
    for key, ratio in declared.items():
        assert abs(got[key]["ratio"] - ratio) <= 0.01, (key, got[key]["ratio"], ratio)
    assert got[("brass", "peacock-teal")]["grade"] == "AA large" and got[("ghee-cream", "peacock-teal")]["grade"] == "AAA"
    assert got[("marigold", "peacock-teal")]["grade"] == "AA"


async def test_the_seam_is_idempotent_and_relinks_images_to_uploads_of_the_same_name(client: httpx.AsyncClient) -> None:
    c = await seed_demo(client)
    async with session() as s, s.begin():  # a second run with unchanged fixtures adds nothing
        await desk.apply_demo_brief_and_brand(
            s, project_id=UUID(c["project"]["id"]), campaign_id=UUID(c["id"]), brief=BRIEF_FIXTURE, brand_kit=KIT_FIXTURE
        )
    assert (await client.get(c["brief"])).json()["version_count"] == 1
    kit_url = f"{API}/projects/{c['project']['id']}/brand-kit"
    kit = (await client.get(kit_url)).json()
    assert kit["revision"] == 1 and all(x["asset_id"] is None for x in kit["design"]["logo"]["lockups"])

    logo = (FIXTURES / "brand" / "logo.png").read_bytes()
    upload = await client.post(f"{API}/projects/{c['project']['id']}/assets", files={"file": ("logo.png", logo, "image/png")}, data={"kind": "image"})
    assert upload.status_code == 201, upload.text
    async with session() as s, s.begin():
        assert await desk.link_kit_assets(s, UUID(c["project"]["id"])) == 1
    linked = (await client.get(kit_url)).json()["design"]["logo"]["lockups"]
    assert linked[0]["asset_id"] == upload.json()["id"] and linked[1]["asset_id"] is None


async def test_the_seam_rejects_a_campaign_from_another_project(client: httpx.AsyncClient) -> None:
    a, b = await live_campaign(client), await live_campaign(client)
    async with session() as s:
        with pytest.raises(ValidationFailed, match="invalid"):
            await desk.apply_demo_brief_and_brand(
                s, project_id=UUID(a["project"]["id"]), campaign_id=UUID(b["id"]), brief=BRIEF_FIXTURE, brand_kit=KIT_FIXTURE
            )


# --- brand kit ----------------------------------------------------------------------------------------------


def kit_design(**changes: Any) -> dict[str, Any]:
    base = {
        "colours": [{"id": "ink", "name": "Ink", "hex": "#101010", "role": "Text"}, {"id": "paper", "name": "Paper", "hex": "#FFFFFF"}],
        "contrast_pairs": [{"text": "ink", "background": "paper"}],
        "fonts": [{"family": "Noto Sans", "weights": [400, 600], "scripts": ["Latn"]}],
        "tagline": {"text": "Every bond, a little sweeter.", "language": "en", "script": "Latn", "locked": True, "translate": False},
        "never_change": [{"id": "logo", "description": "The logo, in every lockup.", "regions": {"box": [0.1, 0.1, 0.2, 0.2]}}],
    }
    return base | changes


async def test_the_brand_kit_saves_revisions_and_calculates_contrast(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await live_campaign(client)
    url = f"{API}/projects/{c['project']['id']}/brand-kit"
    empty = (await client.get(url)).json()
    assert (empty["revision"], empty["saved"], empty["editable"], empty["name"]) == (0, False, True, "Acme")
    assert empty["glossary"] == {"term_count": 0, "protected_count": 0, "never_translate_count": 0, "languages": []}

    saved = await client.put(url, json={"design": kit_design(), "expected_revision": 0})
    assert saved.status_code == 200, saved.text
    kit = saved.json()
    assert kit["revision"] == 1 and kit["contrast"][0]["ratio"] == 19.03 and kit["contrast"][0]["grade"] == "AAA"
    assert kit["protected_terms"] == ["Acme"]  # the brand record is read, not copied

    assert (await client.put(url, json={"design": kit_design()})).json()["revision"] == 1  # unchanged
    tagline = {**kit_design()["tagline"], "locked": False}
    assert (await client.put(url, json={"design": kit_design(tagline=tagline), "expected_revision": 1})).json()["revision"] == 2
    stale = await client.put(url, json={"design": kit_design(), "expected_revision": 1})
    assert stale.status_code == 409

    term = await client.post(f"{API}/campaigns/{c['id']}/glossary", json={"term": "Acme", "language": "*", "protected": True, "never_translate": True})
    assert term.status_code == 201, term.text
    assert (await client.get(url)).json()["glossary"] == {"term_count": 1, "protected_count": 1, "never_translate_count": 1, "languages": []}


async def test_the_brand_kit_rejects_bad_references_and_foreign_images(client: httpx.AsyncClient) -> None:
    c = await live_campaign(client)
    url = f"{API}/projects/{c['project']['id']}/brand-kit"
    bad_pair = await client.put(url, json={"design": kit_design(contrast_pairs=[{"text": "ink", "background": "nope"}])})
    assert bad_pair.status_code == 422 and "unknown colour" in bad_pair.text
    bad_hex = await client.put(url, json={"design": kit_design(colours=[{"id": "ink", "name": "Ink", "hex": "red"}], contrast_pairs=[])})
    assert bad_hex.status_code == 422
    foreign = await client.put(url, json={"design": kit_design(product_images=[{"id": "pack", "asset_id": str(uuid4())}])})
    assert foreign.status_code == 422 and "not one of this brand's uploads" in foreign.text
    assert (await client.get(url)).json()["revision"] == 0


async def test_a_demo_brand_kit_cannot_be_changed(client: httpx.AsyncClient) -> None:
    project = (await client.post(f"{API}/projects/demo")).json()
    url = f"{API}/projects/{project['id']}/brand-kit"
    assert (await client.get(url)).json()["editable"] is False
    assert (await client.put(url, json={"design": kit_design()})).status_code == 409


# --- Today --------------------------------------------------------------------------------------------------


async def test_today_reports_real_rows_next_actions_readiness_and_conflicts(client: httpx.AsyncClient, seeded: Any) -> None:
    empty = (await client.get(f"{API}/desk/today")).json()
    assert empty["campaigns"] == [] and empty["activity"] == [] and empty["conflicts"] == [] and empty["limitations"]

    c = await live_campaign(client)
    await client.put(c["brief"], json={"content": fixture_brief(), "change_note": "Brief for Today"})
    await put_claims(UUID(c["project"]["workspace_id"]), [
        draft("Pongal", attribute="major_festival", sources=[source("wikimedia")]),
        draft("Onam", attribute="major_festival", sources=[source("census", source_type="census_2011"), source("survey", source_type="curated_reference")]),
    ])
    # a verdict must name a real version of this campaign (a made-up id is a 404 now)
    version = await add_version({"pid": UUID(c["project"]["id"]), "cid": UUID(c["id"])})
    verdict = await client.post(f"{API}/campaigns/{c['id']}/readiness", json={
        "region_code": "IN-TN", "version_id": str(version), "observations": observations_json(),
    })
    assert verdict.status_code == 201, verdict.text

    today = (await client.get(f"{API}/desk/today")).json()
    (card,) = today["campaigns"]
    assert card["campaign_id"] == c["id"] and card["brief_version"] == 1 and card["brief_complete"] is True
    assert card["region_codes"] == ["IN-TN", "IN-KL", "IN-WB"]
    assert [(r["region_code"], r["verdict"]) for r in card["readiness"]] == [("IN-TN", "go")]
    actions = {a["id"].split(":", 1)[1]: a for a in card["next_actions"]}
    assert "quick-read" in actions and "risk-check" in actions and "creative" in actions
    assert "version-IN-KL" in actions and "report" in actions and "brief" not in actions
    assert [a["priority"] for a in card["next_actions"]] == sorted(a["priority"] for a in card["next_actions"])

    kinds = {e["kind"] for e in today["activity"]}
    assert {"brief", "verdict"} <= kinds
    times = [e["at"] for e in today["activity"]]
    assert times == sorted(times, reverse=True)
    assert next(e for e in today["activity"] if e["kind"] == "verdict")["title"] == "Tamil Nadu: Go"

    (conflict,) = today["conflicts"]
    assert conflict["region_code"] == "IN-TN" and c["id"] in conflict["campaign_ids"] and conflict["status"] == "open"
    assert any(a["id"].startswith(f"{c['id']}:conflict-") for a in card["next_actions"])

    one = (await client.get(f"{API}/desk/today", params={"campaign_id": c["id"], "limit": 1})).json()
    assert len(one["campaigns"]) == 1 and len(one["activity"]) == 1 and len(one["conflicts"]) == 1


async def test_today_never_shows_another_workspaces_campaigns(client: httpx.AsyncClient, client_for: Any, seeded: Any) -> None:
    c = await live_campaign(client)
    bob = client_for(BOB)
    assert (await bob.get(f"{API}/desk/today")).json()["campaigns"] == []
    assert (await bob.get(f"{API}/desk/today", params={"campaign_id": c["id"]})).status_code == 404


def test_the_brief_schema_is_fit_to_the_fixture_without_losing_fields() -> None:
    brief = desk.brief_from_fixture(BRIEF_FIXTURE)
    dumped = brief.model_dump(mode="json")
    for key in ("objective", "regions", "languages", "scripts", "primary_message", "constraints"):
        assert dumped[key] == BRIEF_FIXTURE[key], key
    assert dumped["dates"]["key_moments"] == [{**x, "note": x.get("note")} for x in BRIEF_FIXTURE["dates"]["key_moments"]]
    assert dumped["budget"] | {"sample": False} == {**BRIEF_FIXTURE["budget"], "sample": False}
    assert isinstance(v.BriefContent.model_validate(dumped), v.BriefContent)
