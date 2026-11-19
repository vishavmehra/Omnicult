"""Market Lens for every state: state data on the atlas, profile and comparison of states nobody built, the moment calendar's
merged lists, Google Calendar's refresh (respx, no network) and the background auto-build of a live campaign's states (fake
sources, no network)."""

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.services import lens_autobuild, lens_moments
from tests.api.omnicult_support import API, add_member, client_for, seeded  # noqa: F401
from tests.api.test_demo_aamod import aamod, no_network  # noqa: F401
from tests.api.test_lens import demo_campaign, live_campaign, offline_live  # noqa: F401
from tests.api.test_lens_t3 import fakes  # noqa: F401
from tests.conftest import BOB


async def campaign_ids(client: httpx.AsyncClient, base: str) -> tuple[UUID, UUID]:
    campaign_id = UUID(base.split("/campaigns/")[1].split("/")[0])
    campaign = (await client.get(f"{API}/campaigns/{campaign_id}")).json()
    return campaign_id, UUID(campaign["project_id"])


async def name_states(client: httpx.AsyncClient, base: str, origin: str, *targets: str) -> UUID:
    """A saved brief naming the campaign's states (what the Campaign Desk writes)."""
    campaign_id, project_id = await campaign_ids(client, base)
    async with session() as s, s.begin():
        s.add(m.CampaignBriefRow(id=uuid4(), campaign_id=campaign_id, project_id=project_id, version_number=1,
                                 content={"regions": {"origin": origin, "targets": list(targets)}}, change_note=None, provenance={},
                                 created_by=None, created_at=utcnow()))
    return campaign_id


async def builds(*codes: str) -> int:
    async with read_session() as s:
        return int(await s.scalar(select(func.count(m.LensBuild.id)).where(m.LensBuild.region_code.in_(codes))) or 0)


# --- state data for every state ---------------------------------------------------------------------------------------


async def test_unbuilt_states_carry_published_data_in_the_atlas_profile_and_comparison(client: httpx.AsyncClient, seeded: Any) -> None:
    _, base = await live_campaign(client)
    atlas = (await client.get(f"{base}/atlas")).json()  # live, nothing built: State facts load their recording on first read
    assert atlas["summary"]["states_with_claims"] == 0 and atlas["summary"]["states_with_data"] == 36
    gj = next(s for s in atlas["states"] if s["code"] == "IN-GJ")
    assert gj["claims"] == 0 and gj["strength"] == "weak"  # the Evidence Meter is untouched by the data
    keys = {f["key"] for f in gj["data"]["figures"]}
    assert {"internet_per100", "literacy", "home_no_internet", "tourist_visits_domestic", "women_bank"} <= keys
    assert gj["data"]["languages"][0]["name"] == "Gujarati" and gj["data"]["languages"][0]["share"] > 80  # census 2011, as data
    assert gj["data"]["holidays"] > 0 and gj["data"]["holidays_year"] == utcnow().year
    ts = next(s for s in atlas["states"] if s["code"] == "IN-TS")
    assert ts["data"]["languages"][0]["share"] is None and ts["data"]["languages"][0]["role"] == "primary"  # no 2011 figure for Telangana
    assert {d["key"] for d in atlas["data_sources"]} >= {"state_facts", "census_2011", "public_holidays", "reference"}

    profile = (await client.get(f"{base}/regions/IN-GJ/profile")).json()
    assert profile["meter"]["claims"] == 0 and profile["data"]["figures"] and profile["campaign_role"] is None

    compare = (await client.get(f"{base}/compare", params={"region_code": ["IN-GJ", "IN-KA"]})).json()
    literacy = next(r for r in compare["data_rows"] if r["key"] == "literacy")
    values = {c["region_code"]: c["value"] for c in literacy["cells"]}
    assert set(values) == {"IN-GJ", "IN-KA"} and literacy["highest"] == [max(values, key=lambda k: values[k])]
    assert all(row["cells"][0]["period"] for row in compare["data_rows"] if row["cells"][0]["value"] is not None)


async def test_the_demo_reads_every_state_from_recordings_with_no_network(aamod: httpx.AsyncClient) -> None:
    with no_network():
        _, base = await demo_campaign(aamod)
        atlas = (await aamod.get(f"{base}/atlas")).json()
        ka = next(s for s in atlas["states"] if s["code"] == "IN-KA")
        assert ka["data"]["figures"] and ka["data"]["searches"] and ka["data"]["search_week"]
        assert {s["campaign_role"] for s in atlas["states"] if s["campaign_role"]} == {"origin", "target"}
        calendar = (await aamod.get(f"{base}/regions/IN-KL/calendar", params={"year": 2027})).json()
    assert calendar["window_basis"] == "campaign" and calendar["window"]  # the brief's own dates
    kinds = {e["kind"] for e in calendar["entries"]}
    assert {"public_holiday", "observance"} <= kinds
    google = [e for e in calendar["entries"] if any(s["label"].startswith("Google Calendar") for s in e["sources"])]
    assert google and all(e["date"].startswith("2027-") for e in google)
    assert not any("(Assam)" in e["name"] for e in calendar["entries"])  # another state's moment is not on Kerala's calendar
    onam = next(e for e in calendar["entries"] if e["name"].startswith("Onam") or e["name"].startswith("Thiruvonam"))
    assert onam["about"] and onam["about"]["url"].startswith("https://en.wikipedia.org/") and "Wikipedia" in onam["about"]["attribution"]
    assert all(e["why"] for e in calendar["entries"]) and {d["key"] for d in calendar["data_sources"]} >= {"google_calendar"}


# --- Google Calendar: the stored copy ------------------------------------------------------------------------------------


EVENTS = {"items": [
    {"id": "e1", "summary": "Diwali/Deepavali", "description": "Public holiday", "start": {"date": "2027-10-29"}, "htmlLink": "https://calendar.google.com/e1"},
    {"id": "e2", "summary": "Bhai Duj", "description": "Observance\nTo hide observances", "start": {"date": "2027-10-31"}},
]}


@respx.mock
async def test_a_refresh_stores_a_year_of_google_events_and_a_refused_key_is_typed(client: httpx.AsyncClient, seeded: Any) -> None:
    route = respx.get(url__regex=r"https://www\.googleapis\.com/calendar/v3/calendars/.+/events").mock(return_value=httpx.Response(200, json=EVENTS))
    async with session() as s, s.begin():
        assert await lens_moments.refresh_google(s, [2027], key="test-key") == {"2027": 2}
    assert route.called and route.calls.last.request.url.params["key"] == "test-key"
    events = await lens_moments.google_events("live", 2027)  # no key configured here: the stored copy is served as it is
    assert [(e.name, e.kind) for e in events] == [("Diwali/Deepavali", "public_holiday"), ("Bhai Duj", "observance")]
    route.mock(return_value=httpx.Response(403, json={"error": {}}))
    with pytest.raises(lens_moments.CalendarSourceError) as refused:
        async with session() as s, s.begin():
            await lens_moments.refresh_google(s, [2027], key="bad")
    assert refused.value.kind == "auth" and "bad" not in str(refused.value)
    assert len(await lens_moments.google_events("live", 2027)) == 2  # a failed pull leaves the stored year alone


# --- auto-build -----------------------------------------------------------------------------------------------------------


async def test_a_live_campaigns_states_are_built_in_the_background_once(
        client: httpx.AsyncClient, seeded: Any, fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LENS_AUTO_BUILD_PAUSE_SECONDS", "0")
    get_settings.cache_clear()
    _, base = await live_campaign(client)
    await name_states(client, base, "IN-TN", "IN-KL")
    started = await client.post(f"{base}/auto-build")
    assert started.status_code == 202, started.text
    body = started.json()
    assert body["enabled"] is True and body["running"] is True
    assert [(r["region_code"], r["role"]) for r in body["regions"]] == [("IN-TN", "origin"), ("IN-KL", "target")]
    assert {r["state"] for r in body["regions"]} <= {"queued", "building"}
    await lens_autobuild.worker.settle()
    done = (await client.get(f"{base}/auto-build")).json()
    assert done["running"] is False and [r["state"] for r in done["regions"]] == ["built", "built"]
    assert all(r["last_build"]["status"] in ("completed", "partial") for r in done["regions"])
    assert await builds("IN-TN", "IN-KL") == 2
    again = (await client.post(f"{base}/auto-build")).json()  # idempotent: built states are not queued again
    await lens_autobuild.worker.settle()
    assert again["running"] is False and await builds("IN-TN", "IN-KL") == 2
    radar = (await client.get(f"{base}/trend-radar")).json()  # the follow-up read the new festivals' attention
    assert {r["region_code"] for r in radar["regions"] if r["refreshed_at"]} == {"IN-TN", "IN-KL"}
    atlas = {s["code"]: s for s in (await client.get(f"{base}/atlas")).json()["states"]}
    assert atlas["IN-KL"]["claims"] > 0 and atlas["IN-KL"]["campaign_role"] == "target"


async def test_demo_campaigns_and_viewers_queue_nothing(client: httpx.AsyncClient, seeded: Any, client_for: Any, offline_live: None) -> None:
    _, demo = await demo_campaign(client)
    shown = (await client.post(f"{demo}/auto-build")).json()
    assert shown["enabled"] is False and shown["running"] is False
    project, base = await live_campaign(client)
    await name_states(client, base, "IN-WB")
    await add_member(UUID(project["workspace_id"]), "bob", "viewer")
    viewer = (await client_for(BOB).post(f"{base}/auto-build")).json()
    assert viewer["enabled"] is False and [r["state"] for r in viewer["regions"]] == ["waiting"]
    await lens_autobuild.worker.settle()
    assert await builds("IN-WB") == 0
