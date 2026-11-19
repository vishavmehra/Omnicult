"""Market Lens API: builds (demo fixtures and live with injected sources), the five reads, tenancy, roles, demo versus live
separation, source failures, rate limits and Data Health. No test touches the network: live builds use the offline
adapters (curated, census, holidays) plus fakes standing in for Wikidata and grounded research."""

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.db import models as m
from app.db.session import read_session
from app.integrations.culture import CultureService, build_culture_service
from app.integrations.culture.adapters.census import CensusSource
from app.integrations.culture.adapters.curated import CuratedReferenceSource
from app.integrations.culture.adapters.holidays_calendar import HolidaysCalendarSource
from app.integrations.culture.base import SourceBase, SourceDescriptor, SourceRateLimited
from app.schemas.claims import ClaimDraft
from app.services import lens as lens_service
from tests.api.omnicult_support import API, add_member, client_for, seeded  # noqa: F401
from tests.api.test_crud import make_campaign, make_project
from tests.conftest import BOB

YEARS = [2027]  # one year keeps the slow SQLite builds short; the calendar test asks for two


class RateLimitedWikidata(SourceBase):
    """Stands in for Wikidata after it answered 429 with a long Retry-After."""

    name = "wikidata"
    descriptor = SourceDescriptor(
        name="wikidata", source_type="knowledge_graph", supported_operations=frozenset({"related_signals"}), scope="test",
        coverage_limitations=[])

    async def related_signals(self, entity_id: str, *, region_code: str, limit: int = 10) -> list[ClaimDraft]:
        raise SourceRateLimited("wikidata", "related_signals", "query.wikidata.org asked us to wait; 988s of cool-down left")


class SlowSource(SourceBase):
    name = "slow"
    descriptor = SourceDescriptor(
        name="slow", source_type="public_dataset", supported_operations=frozenset({"audience_facts"}), scope="test",
        coverage_limitations=[])

    async def audience_facts(self, region_code: str) -> list[ClaimDraft]:
        await asyncio.sleep(5)
        return []


class UnconfiguredGrounding(SourceBase):
    name = "gemini_grounding"
    descriptor = SourceDescriptor(
        name="gemini_grounding", source_type="grounded_llm", supported_operations=frozenset({"related_signals"}), scope="test",
        coverage_limitations=[], requires_credentials=True)

    def is_configured(self) -> bool:
        return False


def offline_live_service(*extra: SourceBase) -> Callable[..., CultureService]:
    def make(settings: Settings, mode: str, *, include_grounding: bool) -> CultureService:
        if mode == "demo":  # demo campaigns in the same test still use the real fixture source
            return build_culture_service(settings, mode="demo")
        sources: list[Any] = [CuratedReferenceSource(), CensusSource(), HolidaysCalendarSource(), *extra]
        if include_grounding:
            sources.append(UnconfiguredGrounding())
        return CultureService(sources, mode="live")

    return make


@pytest.fixture
def offline_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live builds read the offline datasets and a rate-limited Wikidata; nothing reaches a network."""
    monkeypatch.setattr(lens_service, "make_culture_service", offline_live_service(RateLimitedWikidata()))
    monkeypatch.setenv("LENS_LIVE_BUILD_MIN_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()


async def demo_campaign(client: httpx.AsyncClient) -> tuple[dict[str, Any], str]:
    project = (await client.post(f"{API}/projects/demo")).json()
    campaign = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]
    return project, f"{API}/campaigns/{campaign['id']}/lens"


async def live_campaign(client: httpx.AsyncClient) -> tuple[dict[str, Any], str]:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    return project, f"{API}/campaigns/{campaign['id']}/lens"


async def build(client: httpx.AsyncClient, base: str, *codes: str, **extra: Any) -> dict[str, Any]:
    response = await client.post(f"{base}/builds", json={"region_codes": list(codes), "years": YEARS, **extra})
    assert response.status_code == 201, response.text
    return response.json()


async def built_demo(client: httpx.AsyncClient, *codes: str) -> tuple[dict[str, Any], str]:
    project, base = await demo_campaign(client)
    await build(client, base, *(codes or ("IN-MH", "IN-TN", "IN-KL", "IN-WB")))
    return project, base


# --- demo builds and the five reads -----------------------------------------------------------------------------------


async def test_a_demo_build_stores_fixture_claims_only(client: httpx.AsyncClient, seeded: Any) -> None:
    _, base = await demo_campaign(client)
    batch = await build(client, base, "IN-TN", "IN-AN")
    first, second = batch["builds"]
    assert [first["region_code"], second["region_code"]] == ["IN-TN", "IN-AN"]
    assert first["claim_count"] > 80 and second["claim_count"] > 10  # Andaman has public holidays only
    for b in batch["builds"]:
        assert b["mode"] == "demo" and b["status"] == "completed" and b["version"] == 1
        assert b["include_grounding"] is False and b["years"] == YEARS and b["sources_skipped"] == []
        assert {c["source"] for c in b["calls"]} == {"fixture"} and all(c["status"] in ("ok", "empty") for c in b["calls"])
    async with read_session() as s:
        claims = list((await s.execute(select(m.Claim))).scalars())
        assert claims and {c.mode for c in claims} == {"demo"} and {c.workspace_id for c in claims} != {None}
        titles = (await s.execute(select(m.ClaimSource.title, m.ClaimSource.source_identifier))).all()
        assert all(ident.startswith("fixture:") and "DEMO FIXTURE" not in (t or "") for t, ident in titles)  # the identifier separates fixtures; no title says so
        assert await s.scalar(select(func.count()).select_from(m.AuditLog).where(m.AuditLog.action == "lens.build")) == 2


async def test_rebuilding_versions_the_build_and_does_not_duplicate_claims(client: httpx.AsyncClient, seeded: Any) -> None:
    _, base = await demo_campaign(client)
    first = (await build(client, base, "IN-TN"))["builds"][0]
    async with read_session() as s:
        stored = await s.scalar(select(func.count()).select_from(m.Claim))
    second = (await build(client, base, "IN-TN"))["builds"][0]
    assert (first["version"], second["version"]) == (1, 2)
    assert second["created_claims"] == 0 and second["updated_claims"] == second["claim_count"] == first["claim_count"]
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.Claim)) == stored
    page = (await client.get(f"{base}/builds", params={"region_code": "IN-TN"})).json()
    assert page["total"] == 2 and [b["version"] for b in page["items"]] == [2, 1] and page["items"][0]["calls"] == []
    detail = (await client.get(f"{base}/regions/IN-TN/builds/{second['id']}")).json()
    assert detail["calls"] and detail["version"] == 2
    assert (await client.get(f"{base}/regions/IN-MH/builds/{second['id']}")).status_code == 404  # another state's build id


async def test_state_profile_shows_every_fact_as_a_claim_with_its_five_tags(client: httpx.AsyncClient, seeded: Any) -> None:
    _, base = await built_demo(client, "IN-TN")
    body = (await client.get(f"{base}/regions/IN-TN/profile")).json()
    assert body["mode"] == "demo" and body["mode_label"] == "" and body["region"]["code"] == "IN-TN"
    assert [s["key"] for s in body["sections"]] == ["languages", "festivals", "references", "tone", "trends"]
    assert body["meter"]["claims"] > 80 and body["meter"]["strength"] in ("partial", "solid")
    festivals = next(s for s in body["sections"] if s["key"] == "festivals")
    pongal = next(c for c in festivals["claims"] if c["subject"] == "festival:pongal" and c["attribute"] == "major_festival")
    assert pongal["kind"] == "observed" and pongal["confidence"] == "moderate" and len(pongal["sources"]) == 2
    assert len({s["independence_group"] for s in pongal["sources"]}) == 2  # independent groups: why it reaches Moderate
    assert all(src["excerpt"] and src["retrieved_at"] for src in pongal["sources"]) and pongal["scope"]["region_code"] == "IN-TN"
    assert all(c["attribute"] != "public_holiday_date" for s in body["sections"] for c in s["claims"])  # those are in the calendar
    assert festivals["elsewhere"][0]["view"] == "calendar" and festivals["elsewhere"][0]["claims"] > 20
    languages = next(s for s in body["sections"] if s["key"] == "languages")
    assert languages["claims"] and all(c["attribute"] not in ("language_share", "mother_tongue_speakers") for c in languages["claims"])
    assert {e["view"] for e in languages["elsewhere"]} == {"language_map"}
    assert {s["source_type"] for s in body["sources"]} >= {"census_2011", "holidays_package", "curated_reference", "wikipedia"}
    assert all(s["limitations"] for s in body["sources"] if s["source_type"] != "wikipedia_pageviews") and body["build"]["version"] == 1
    assert body["conflicts"] == [] and any("native reviewer" in text for text in body["limitations"])
    trends = next(s for s in body["sections"] if s["key"] == "trends")
    assert trends["claims"] and all(c["kind"] == "synthetic" and c["confidence"] != "high" for c in trends["claims"])  # fixture series


async def test_the_dahi_handi_disagreement_is_kept_and_shown_with_both_values(client: httpx.AsyncClient, seeded: Any) -> None:
    _, base = await built_demo(client, "IN-MH")
    body = (await client.get(f"{base}/regions/IN-MH/profile")).json()
    (conflict,) = body["conflicts"]
    assert conflict["status"] == "open" and "festival_day_relative_to_janmashtami" in conflict["reason"]
    values = {conflict["claim_a"]["value"], conflict["claim_b"]["value"]}
    assert values == {"same day as Krishna Janmashtami", "day after Krishna Janmashtami"}
    assert conflict["claim_a"]["effective_confidence"] == "low" and body["meter"]["open_conflicts"] == 1
    calendar = (await client.get(f"{base}/regions/IN-MH/calendar", params={"year": 2027})).json()
    assert [c["id"] for c in calendar["conflicts"]] == [conflict["id"]]
    dahi = next(t for t in calendar["timed"] if t["name"] == "Dahi Handi")
    assert dahi["conflict_ids"] == [conflict["id"]] and dahi["months_named"] == [8, 9]


async def test_the_calendar_dates_moments_with_sources_and_flags_a_campaign_window(client: httpx.AsyncClient, seeded: Any) -> None:
    _, base = await demo_campaign(client)
    await build(client, base, "IN-MH", years=[2026, 2027])
    window = {"window_from": "2027-10-04", "window_to": "2027-11-01"}
    body = (await client.get(f"{base}/regions/IN-MH/calendar", params={"year": 2027, **window})).json()
    assert body["year"] == 2027 and body["years_available"] == [2026, 2027] and body["window"] == {"date_from": "2027-10-04", "date_to": "2027-11-01"}
    assert len(body["months"]) == 12 and body["gaps"] == []
    october = body["months"][9]["dated"]
    diwali = next(d for d in october if d["name"] == "Diwali (Deepavali)")
    assert diwali["date"] == "2027-10-29" and diwali["in_window"] is True and diwali["date_basis"] == "public_holiday_list"
    assert diwali["festival_subject"] == "festival:diwali" and diwali["claim"]["sources"][0]["source_type"] == "holidays_package"
    assert diwali["claim"]["kind"] == "observed" and diwali["claim"]["scope"]["period"] == "2027"
    assert all(d["in_window"] is not None for month in body["months"] for d in month["dated"])
    festival = next(t for t in body["timed"] if t["name"] == "Diwali")
    assert festival["dated_for_year"] and "2027-10-29" in festival["dated_for_year"] and festival["may_overlap_window"] is True
    assert any("mid-October" in t["text"] for t in festival["timings"])  # the source's own words, not a computed date
    may_day = next(d for month in body["months"] for d in month["dated"] if d["name"] == "Maharashtra Day")
    assert may_day["date"] == "2027-05-01" and may_day["date_basis"] == "public_holiday_list"
    (second,) = may_day["also_stated_by"]  # the curated reference states the same date in its own words: kept as a second claim
    assert second["attribute"] == "moment_date" and second["sources"][0]["source_type"] == "curated_reference"
    shivaji = next(d for month in body["months"] for d in month["dated"] if d["name"] == "Shivaji Maharaj Jayanti")
    assert shivaji["date"] == "2027-02-19" and shivaji["date_basis"] == "source_text" and shivaji["claim"]["sources"][0]["excerpt"]
    nothing = (await client.get(f"{base}/regions/IN-MH/calendar", params={"year": 2031})).json()
    assert all(d["date_basis"] == "source_text" for month in nothing["months"] for d in month["dated"])  # annual dates only, no holiday list
    assert "2031" in nothing["gaps"][0] and "2026, 2027" in nothing["gaps"][0]
    assert (await client.get(f"{base}/regions/IN-MH/calendar")).json()["window"] is None


async def test_the_language_map_labels_2011_and_keeps_disagreeing_shares(client: httpx.AsyncClient, seeded: Any) -> None:
    _, base = await built_demo(client, "IN-MH", "IN-WB")
    body = (await client.get(f"{base}/language-map")).json()
    assert body["period"] == "2011" and body["code_mixing"]["status"] == "no_sourced_claims" and len(body["regions"]) == 36
    by_code = {r["region_code"]: r for r in body["regions"]}
    mh = by_code["IN-MH"]
    marathi = next(e for e in mh["languages"] if e["code"] == "mr")
    assert mh["has_census"] and marathi["role"] == "primary" and marathi["script"] == "Deva" and marathi["native_name"] == "मराठी"
    assert [s["percent"] for s in marathi["shares"]] == [68.93] and marathi["disputed"] is False
    assert marathi["shares"][0]["claim"]["scope"]["period"] == "2011" and marathi["shares"][0]["claim"]["kind"] == "calculated"
    assert marathi["shares"][0]["claim"]["sources"][0]["source_type"] == "census_2011"
    assert mh["languages"][0]["code"] == "mr"  # the principal language first
    assert any(e["code"] is None and e["name"] == "Bhili/Bhilodi" for e in mh["languages"])  # a census language with no ISO code
    hindi = next(e for e in by_code["IN-WB"]["languages"] if e["code"] == "hi")
    assert hindi["disputed"] is True and [s["percent"] for s in hindi["shares"]] == [6.96, 5.0] and len(by_code["IN-WB"]["conflicts"]) == 1
    ka = by_code["IN-KA"]
    assert by_code["IN-TN"]["has_census"] is False  # not built here: no shares, never a guess
    assert ka["has_census"] is False and ka["languages"] and all(e["shares"] == [] for e in ka["languages"])
    assert ka["languages"][0]["role"] == "primary" and ka["languages"][0]["script"] == "Knda"
    assert any("2011" in text for text in body["limitations"]) and {s["source_type"] for s in body["sources"]} >= {"census_2011", "wikipedia"}


async def test_the_atlas_lists_every_state_with_its_evidence_strength(client: httpx.AsyncClient, seeded: Any) -> None:
    _, base = await built_demo(client, "IN-MH", "IN-TN")
    empty = (await client.get(f"{base}/atlas")).json()  # two states built; the rest are not
    states = {s["code"]: s for s in empty["states"]}
    assert len(states) == 36 and empty["summary"]["states_total"] == 36 and empty["summary"]["states_with_claims"] == 2
    for code in ("IN-MH", "IN-TN"):
        assert states[code]["built"] is True and states[code]["claims"] > 80 and states[code]["last_build"]["version"] == 1
        assert states[code]["strength"] in ("partial", "solid") and states[code]["categories_covered"] >= 6
    ka = states["IN-KA"]
    assert ka["built"] is False and ka["claims"] == 0 and ka["strength"] == "weak" and ka["last_build"] is None
    assert ka["strength_reasons"] and ka["name"] == "Karnataka" and ka["primary_script"] == "Knda"
    assert states["IN-MH"]["open_conflicts"] == 1 and states["IN-TN"]["open_conflicts"] == 0 and states["IN-KL"]["built"] is False
    assert empty["mode_label"] == "" and {s["source_type"] for s in empty["sources"]} >= {"census_2011", "holidays_package"}
    await build(client, base, "IN-KA")  # a state with public holidays only stays weak: one category, no Moderate claim
    ka = {s["code"]: s for s in (await client.get(f"{base}/atlas")).json()["states"]}["IN-KA"]
    assert ka["built"] is True and ka["claims"] > 10 and ka["strength"] == "weak" and ka["categories_covered"] == 1
    assert ka["source_types"] == ["holidays_package"] and "language" in ka["missing_categories"]


async def test_compare_puts_states_side_by_side_and_shows_missing_evidence(client: httpx.AsyncClient, seeded: Any) -> None:
    _, base = await built_demo(client, "IN-MH", "IN-TN")
    response = await client.get(f"{base}/compare", params=[("region_code", "IN-MH"), ("region_code", "IN-TN"), ("region_code", "IN-KA")])
    assert response.status_code == 200, response.text
    body = response.json()
    assert [r["region"]["code"] for r in body["regions"]] == ["IN-MH", "IN-TN", "IN-KA"]
    ka = body["regions"][2]
    assert ka["claims"] == 0 and ka["strength"] == "weak" and ka["built"] is False and len(ka["missing_categories"]) == ka["categories_total"]
    rows = {r["key"]: r for r in body["rows"]}
    assert list(rows) == ["languages", "festivals", "moments", "food", "colour_symbol", "humour", "family_custom", "sensitivity"]
    festivals = rows["festivals"]
    assert [c["region_code"] for c in festivals["cells"]] == ["IN-MH", "IN-TN", "IN-KA"]
    assert festivals["cells"][2]["missing"] is True and festivals["cells"][2]["items"] == []
    mh_items = {i["label"]: i for i in festivals["cells"][0]["items"]}
    assert "Gudi Padwa" in mh_items and mh_items["Gudi Padwa"]["confidence"] in ("low", "moderate") and mh_items["Gudi Padwa"]["source_count"] >= 1
    assert rows["humour"]["cells"][1]["missing"] is True  # Tamil Nadu has no humour claim (a gap, not a statement)
    languages = rows["languages"]["cells"][0]["items"]
    assert any(i["label"].startswith("Marathi") and "(2011)" in i["label"] for i in languages)
    assert any("never imply" in text or "not that the two things mean the same" in text for text in body["limitations"])
    one = await client.get(f"{base}/compare", params=[("region_code", "IN-MH")])
    assert one.status_code == 422 and one.json()["error"]["code"] == "VALIDATION_ERROR"
    five = await client.get(f"{base}/compare", params=[("region_code", c) for c in ("IN-MH", "IN-TN", "IN-KL", "IN-WB", "IN-KA")])
    assert five.status_code == 422
    same = await client.get(f"{base}/compare", params=[("region_code", "IN-MH"), ("region_code", "IN-MH")])
    assert same.status_code == 422
    assert (await client.get(f"{base}/compare", params=[("region_code", "IN-MH"), ("region_code", "IN-ZZ")])).status_code == 404


# --- live builds: sources, failures, cool-downs ---------------------------------------------------------------------


async def test_a_live_build_stores_live_claims_and_reports_a_rate_limited_source(client: httpx.AsyncClient, seeded: Any, offline_live: None) -> None:
    _, base = await live_campaign(client)
    (b,) = (await build(client, base, "IN-TN", include_trends=False))["builds"]
    assert b["mode"] == "live" and b["status"] == "partial" and b["claim_count"] > 80
    errors = [c for c in b["calls"] if c["status"] == "error"]
    assert [(c["source"], c["error_type"]) for c in errors] == [("wikidata", "rate_limited")] and "988s" in errors[0]["error"]
    assert any("wikidata.related_signals failed (rate_limited)" in g for g in b["gaps"])
    assert b["sources_skipped"] == [] and b["include_grounding"] is False  # grounding is opt-in, so it is not a gap here
    async with read_session() as s:
        assert {c.mode for c in await s.scalars(select(m.Claim))} == {"live"}
        identifiers = list(await s.scalars(select(m.ClaimSource.source_identifier)))
        assert not any(i.startswith("fixture:") for i in identifiers)
    profile = (await client.get(f"{base}/regions/IN-TN/profile")).json()
    assert profile["mode"] == "live" and profile["build"]["status"] == "partial" and "Live sources" in profile["mode_label"]
    assert any("rate_limited" in g for g in profile["gaps"]) and profile["meter"]["claims"] == b["claim_count"]
    trends = next(s for s in profile["sections"] if s["key"] == "trends")
    assert trends["claims"] == [] and trends["empty_reason"]


async def test_requested_grounded_research_that_is_not_configured_is_reported_not_hidden(client: httpx.AsyncClient, seeded: Any, offline_live: None) -> None:
    _, base = await live_campaign(client)
    (b,) = (await build(client, base, "IN-KL", include_trends=False, include_grounding=True))["builds"]
    assert b["include_grounding"] is True and b["sources_skipped"] == ["gemini_grounding"]
    assert any("Grounded research was requested but is not configured" in g for g in b["gaps"])
    assert b["claim_count"] > 80  # the other sources still stored their claims


async def test_demo_and_live_claims_never_mix_in_one_workspace(client: httpx.AsyncClient, seeded: Any, offline_live: None) -> None:
    demo_project, demo_base = await built_demo(client, "IN-TN")
    live_project, live_base = await live_campaign(client)
    assert demo_project["workspace_id"] == live_project["workspace_id"]  # one tenant, two modes
    live_atlas = (await client.get(f"{live_base}/atlas")).json()
    assert live_atlas["mode"] == "live" and live_atlas["summary"]["claims"] == 0 and live_atlas["summary"]["states_with_claims"] == 0
    assert all(s["built"] is False for s in live_atlas["states"])
    profile = (await client.get(f"{live_base}/regions/IN-TN/profile")).json()
    assert profile["meter"]["claims"] == 0 and profile["build"] is None and profile["gaps"][0].startswith("No profile has been built")
    assert all(s["claims"] == [] for s in profile["sections"])
    (b,) = (await build(client, live_base, "IN-TN", include_trends=False))["builds"]
    assert b["version"] == 1  # versions count per mode
    demo_atlas = (await client.get(f"{demo_base}/atlas")).json()
    assert demo_atlas["mode"] == "demo" and demo_atlas["summary"]["states_with_claims"] == 1
    demo_claims = {s["code"]: s["claims"] for s in demo_atlas["states"]}["IN-TN"]
    live_claims = {s["code"]: s["claims"] for s in (await client.get(f"{live_base}/atlas")).json()["states"]}["IN-TN"]
    assert demo_claims > 0 and live_claims > 0 and live_claims != demo_claims  # the demo has its synthetic trend series
    assert (await client.get(f"{live_base}/builds")).json()["total"] == 1 and (await client.get(f"{demo_base}/builds")).json()["total"] == 1


async def test_live_builds_of_one_state_are_spaced_out(client: httpx.AsyncClient, seeded: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lens_service, "make_culture_service", offline_live_service())
    monkeypatch.setenv("LENS_LIVE_BUILD_MIN_INTERVAL_SECONDS", "600")
    get_settings.cache_clear()
    _, base = await live_campaign(client)
    await build(client, base, "IN-TN", include_trends=False)
    again = await client.post(f"{base}/builds", json={"region_codes": ["IN-TN"], "years": YEARS})
    assert again.status_code == 429 and again.json()["error"]["code"] == "RATE_LIMITED" and "seconds" in again.json()["error"]["message"]
    other = await client.post(f"{base}/builds", json={"region_codes": ["IN-AN"], "years": YEARS, "include_trends": False})
    assert other.status_code == 201  # another state is not affected
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.LensBuild).where(m.LensBuild.region_code == "IN-TN")) == 1  # the refused one left no row


async def test_a_slow_build_is_stopped_and_recorded_as_failed_with_nothing_stored(client: httpx.AsyncClient, seeded: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lens_service, "make_culture_service", offline_live_service(SlowSource()))
    monkeypatch.setenv("LENS_LIVE_BUILD_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("LENS_BUILD_TIMEOUT_SECONDS", "1")
    get_settings.cache_clear()
    _, base = await live_campaign(client)
    (b,) = (await build(client, base, "IN-TN", include_trends=False))["builds"]
    assert b["status"] == "failed" and b["claim_count"] == 0 and "longer than 1 seconds" in b["error"] and b["calls"] == []
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.Claim)) == 0
    atlas = {x["code"]: x for x in (await client.get(f"{base}/atlas")).json()["states"]}["IN-TN"]
    assert atlas["built"] is True and atlas["claims"] == 0 and atlas["last_build"]["status"] == "failed"


async def test_a_build_already_running_for_a_state_answers_409(client: httpx.AsyncClient, seeded: Any, offline_live: None) -> None:
    project, base = await live_campaign(client)
    key = (UUID(project["workspace_id"]), "IN-TN", "live")
    lens_service._RUNNING.add(key)
    try:
        response = await client.post(f"{base}/builds", json={"region_codes": ["IN-TN"]})
        assert response.status_code == 409 and "already running" in response.json()["error"]["message"]
    finally:
        lens_service._RUNNING.discard(key)


async def test_the_culture_call_log_feeds_data_health_without_counting_demo_fixtures(client: httpx.AsyncClient, seeded: Any, offline_live: None) -> None:
    demo_project, demo_base = await built_demo(client, "IN-TN")
    _, live_base = await live_campaign(client)
    await build(client, live_base, "IN-TN", include_trends=False, years=[2026, 2027])
    workspace = demo_project["workspace_id"]
    health = (await client.get(f"{API}/workspaces/{workspace}/data-health", params={"mode": "live"})).json()
    by_type = {s["source_type"]: s for s in health["sources"]}
    for source_type in ("census_2011", "holidays_package", "curated_reference", "wikidata"):
        assert by_type[source_type]["attempts_logged"] is True, source_type
    assert by_type["census_2011"]["attempts"] == 1 and by_type["census_2011"]["errors"] == 0
    assert by_type["wikidata"]["attempts"] == 1 and by_type["wikidata"]["errors"] == 1
    assert by_type["wikidata"]["last_error"]["code"] == "rate_limited" and by_type["wikidata"]["last_attempt_at"]
    assert by_type["holidays_package"]["attempts"] == 2  # one call per requested year
    demo_health = (await client.get(f"{API}/workspaces/{workspace}/data-health", params={"mode": "demo"})).json()
    demo_by_type = {s["source_type"]: s for s in demo_health["sources"]}
    assert demo_by_type["census_2011"]["fixture_claims"] > 0 and demo_by_type["census_2011"]["attempts"] == 1  # the live attempt, not the fixture's
    assert demo_by_type["census_2011"]["live_claims"] == 0


async def test_cached_calls_are_not_counted_as_attempts(client: httpx.AsyncClient, seeded: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.culture import InMemoryCacheStore

    cache = InMemoryCacheStore()
    monkeypatch.setattr(lens_service, "make_culture_service", lambda settings, mode, *, include_grounding: CultureService(
        [CensusSource(), HolidaysCalendarSource()], cache=cache, mode="live"))
    monkeypatch.setenv("LENS_LIVE_BUILD_MIN_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    project, base = await live_campaign(client)
    await build(client, base, "IN-TN", include_trends=False)
    (second,) = (await build(client, base, "IN-TN", include_trends=False))["builds"]
    assert all(c["cached"] for c in second["calls"])
    health = (await client.get(f"{API}/workspaces/{project['workspace_id']}/data-health")).json()
    assert {s["source_type"]: s["attempts"] for s in health["sources"]}["census_2011"] == 1


# --- access: tenancy, roles, validation ---------------------------------------------------------------------------------


async def test_another_workspace_sees_nothing_and_changes_nothing(client: httpx.AsyncClient, client_for: Any, seeded: Any) -> None:
    _, base = await built_demo(client, "IN-AN")
    bob = client_for(BOB)
    reads = ["atlas", "regions/IN-MH/profile", "regions/IN-MH/calendar", "language-map", "builds",
             "compare?region_code=IN-MH&region_code=IN-TN"]
    for path in reads:
        response = await bob.get(f"{base}/{path}")
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "NOT_FOUND"
    assert (await bob.post(f"{base}/builds", json={"region_codes": ["IN-TN"]})).status_code == 404
    assert (await bob.get(f"{API}/campaigns/{uuid4()}/lens/atlas")).status_code == 404
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.LensBuild)) == 1  # alice's build only
    assert (await client.get(f"{base}/atlas")).status_code == 200  # still reachable by its owner


@pytest.mark.parametrize(("role", "can_build"), [("owner", True), ("editor", True), ("reviewer", False), ("viewer", False)])
async def test_every_member_reads_but_only_editors_build(client: httpx.AsyncClient, client_for: Any, seeded: Any, role: str, can_build: bool) -> None:
    project, base = await demo_campaign(client)
    await add_member(UUID(project["workspace_id"]), "bob", role)
    bob = client_for(BOB)
    for path in ("atlas", "regions/IN-TN/profile", "language-map", "regions/IN-TN/calendar", "builds"):
        assert (await bob.get(f"{base}/{path}")).status_code == 200, path
    response = await bob.post(f"{base}/builds", json={"region_codes": ["IN-AN"], "years": YEARS})
    assert response.status_code == (201 if can_build else 403), response.text
    if not can_build:
        assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_requests_are_validated_and_unauthenticated_calls_refused(client: httpx.AsyncClient, seeded: Any, app: Any) -> None:
    _, base = await demo_campaign(client)
    cases = [
        ({"region_codes": []}, 422), ({"region_codes": ["tamil nadu"]}, 422), ({"region_codes": ["IN-TN"], "years": [1999]}, 422),
        ({"region_codes": ["IN-TN"], "years": [2026, 2027, 2028, 2029]}, 422), ({"region_codes": ["IN-TN"], "include_grounding": True}, 422),
        ({"region_codes": ["IN-ZZ"]}, 404), ({"region_codes": ["IN-TN"], "surprise": 1}, 422),
    ]
    for body, status in cases:
        response = await client.post(f"{base}/builds", json=body)
        assert response.status_code == status, (body, response.text)
    assert (await client.get(f"{base}/regions/IN-ZZ/profile")).status_code == 404
    assert (await client.get(f"{base}/regions/IN-ZZ/calendar")).status_code == 404
    assert (await client.get(f"{base}/regions/not-a-code/profile")).status_code == 422
    for params in ({"window_from": "2027-10-04"}, {"window_from": "2027-11-01", "window_to": "2027-10-04"}, {"year": 1900}):
        assert (await client.get(f"{base}/regions/IN-TN/calendar", params=params)).status_code == 422, params
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.LensBuild)) == 0
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as anonymous:
        assert (await anonymous.get(f"{base}/atlas")).status_code == 401
        assert (await anonymous.post(f"{base}/builds", json={"region_codes": ["IN-TN"]})).status_code == 401


async def test_a_live_request_for_too_many_states_is_refused_before_any_call(client: httpx.AsyncClient, seeded: Any, offline_live: None) -> None:
    _, base = await live_campaign(client)
    codes = ["IN-AN", "IN-AP", "IN-AR", "IN-AS", "IN-BR", "IN-CH", "IN-CG"]
    response = await client.post(f"{base}/builds", json={"region_codes": codes})
    assert response.status_code == 422 and "at most 6" in str(response.json()["error"]["details"])
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.LensBuild)) == 0


async def test_an_archived_brand_cannot_be_built_but_can_be_read(client: httpx.AsyncClient, seeded: Any, offline_live: None) -> None:
    project, base = await live_campaign(client)
    assert (await client.delete(f"{API}/projects/{project['id']}")).status_code == 204
    assert (await client.get(f"{base}/atlas")).status_code == 200
    assert (await client.post(f"{base}/builds", json={"region_codes": ["IN-TN"]})).status_code == 409


async def test_the_default_live_service_has_the_live_adapters_and_the_demo_service_none(seeded: Any) -> None:
    settings = get_settings()
    live = lens_service.make_culture_service(settings, "live", include_grounding=False)
    assert live.mode == "live" and {s.name for s in live.sources} >= {"wikidata", "wikipedia_pageviews", "census_2011", "curated", "holidays_calendar"}
    assert live.skipped_sources() == ["gemini_grounding"]  # not configured: no research capability was passed
    demo = lens_service.make_culture_service(settings, "demo", include_grounding=False)
    assert demo.mode == "fixture" and [s.name for s in demo.sources] == ["fixture"]
