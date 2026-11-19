"""Market Lens Tier 3 API: Trend Radar and Category Shelf. Demo campaigns read the recording (the Aamod journey, no network);
live campaigns run against fakes standing in for Wikimedia and Wikidata. No test touches the network."""

import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from app.core.auth import dev_user_id
from app.core.config import get_settings
from app.db import models as m
from app.db.session import read_session
from app.integrations.culture import CultureService
from app.integrations.culture.base import (
    SourceBase,
    SourceDescriptor,
    SourceRateLimited,
    TrendEdition,
    TrendPoint,
    TrendSeries,
)
from app.integrations.culture.regions import region_for
from app.integrations.culture.shelf import CategoryPack, ShelfDiscovery, ShelfEntity, ShelfExcluded, ShelfPlace
from app.schemas.claims import SourceRef
from app.services import lens_t3 as shared
from app.services.lens_t3 import seed_lens_t3_demo
from tests.api.omnicult_support import API, add_member, client_for, seeded  # noqa: F401
from tests.api.test_demo_aamod import aamod, no_network  # noqa: F401
from tests.api.test_lens import build, live_campaign, offline_live  # noqa: F401
from tests.conftest import BOB

NOW = datetime(2026, 11, 18, tzinfo=UTC)


async def aamod_campaign(client: httpx.AsyncClient) -> tuple[dict[str, Any], str]:
    project = (await client.post(f"{API}/projects/demo")).json()
    campaign = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]
    return project, f"{API}/campaigns/{campaign['id']}/lens"


# --- demo: the recording, no network ------------------------------------------------------------------------------------


@pytest.fixture
def unseeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """The demo journey fills both views itself (its lens hook). The tests that exercise the refresh start from a demo campaign
    nobody has refreshed yet, so the journey's hook is switched off for them."""
    async def nothing(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(shared, "seed_lens_t3_demo", nothing)


async def test_the_demo_trend_radar_reads_the_recording_and_keeps_history(aamod: httpx.AsyncClient, unseeded: None) -> None:
    client = aamod
    with no_network():
        project, base = await aamod_campaign(client)
        empty = (await client.get(f"{base}/trend-radar")).json()
        assert empty["summary"]["items"] == 0 and empty["refreshed_at"] is None
        assert [r["region_code"] for r in empty["regions"]] == ["IN-MH", "IN-TN", "IN-KL", "IN-WB"]  # the brief's origin and targets
        assert all("not been refreshed" in r["gaps"][0] for r in empty["regions"])

        response = await client.post(f"{base}/trend-radar/refresh", json={})
        assert response.status_code == 200, response.text
        radar = response.json()
        again = (await client.post(f"{base}/trend-radar/refresh", json={"region_codes": ["IN-TN"]})).json()
    assert radar["mode"] == "demo" and radar["source_line"] == ""
    assert radar["category"]["pack_key"] == "festive_sweets_snacks" and radar["category"]["status"] == "matched"
    assert radar["moments_window"] == {"date_from": "2027-10-04", "date_to": "2027-11-01"} and radar["moments_window_basis"] == "campaign_dates"
    assert radar["method"]["version"] == "attention-windows-v2" and radar["method"]["year_months"] == 12 and "never changes the label" in radar["method"]["description"]
    items = [i for r in radar["regions"] for i in r["items"]]
    assert radar["summary"]["items"] == len(items) > 15
    assert {i["term_kind"] for i in items} == {"festival", "category"}
    for item in items:
        assert item["confidence"] in ("low", "moderate")  # a demo fixture never reaches High
        assert item["source"]["publisher"] == "Wikimedia Foundation" and item["source"]["kind"] == "observed"
        assert item["primary"]["normalised"] is True and len(item["primary"]["series"]) == 24
        assert all(month["per_million"] is not None for month in item["primary"]["series"])
        if item["direction"] != "insufficient":
            assert item["windows"]["recent_from"] == "2025-11" and item["windows"]["recent_to"] == "2026-10"
            assert item["windows"]["quarter_ago_from"] == "2025-08" and item["change"] is not None
        if item["basis"] == "regional_edition":
            assert item["primary"]["is_regional"] and item["reference"]["language"] == "en"
    assert any(i["direction"] in ("rising", "falling", "steady") for i in items)
    assert all(any("not search volume" in text for text in radar["limitations"]) for _ in [0])
    # festivals inside the campaign dates come first and the Moment Calendar's dated moments link to their attention
    tn = next(r for r in radar["regions"] if r["region_code"] == "IN-TN")
    assert tn["moments"] and all(mo["date"] is None or "2027-10-04" <= mo["date"] <= "2027-11-01" for mo in tn["moments"])
    assert all(mo["timing_text"] for mo in tn["moments"] if mo["date"] is None)  # no exact day: the source's own words instead
    assert any(mo["term_key"] for r in radar["regions"] for mo in r["moments"])
    assert any("has no series for this state" in g for g in tn["gaps"])  # a festival the recording does not hold is said, not drawn
    # a second refresh keeps the first reading as history
    twice = next(i for r in again["regions"] if r["region_code"] == "IN-TN" for i in r["items"] if i["label"] == "Pongal (festival)")
    assert twice["snapshots"] == 2 and len(twice["history"]) == 1 and twice["history"][0]["direction"] == twice["direction"]
    async with read_session() as s:
        assert await s.scalar(select(func.count(m.LensTrendBatch.id)).where(m.LensTrendBatch.mode == "demo")) == 2


async def test_the_demo_hook_fills_both_views_once_and_a_viewer_cannot_refresh(aamod: httpx.AsyncClient, client_for: Any) -> None:
    client = aamod
    with no_network():
        project, base = await aamod_campaign(client)
        campaign_id = UUID(base.split("/campaigns/")[1].split("/")[0])
        user_id = dev_user_id("alice")
        assert (await client.get(f"{base}/trend-radar")).json()["summary"]["items"] > 0, "the journey ran the hook itself"
        await seed_lens_t3_demo(user_id, campaign_id)
        await seed_lens_t3_demo(user_id, campaign_id)  # idempotent
        radar = (await client.get(f"{base}/trend-radar")).json()
        shelf = (await client.get(f"{base}/category-shelf")).json()
    assert radar["summary"]["items"] > 0 and radar["can_refresh"] is True
    assert shelf["snapshot"]["version"] == 1 and shelf["history"] == []
    async with read_session() as s:
        assert await s.scalar(select(func.count(m.LensTrendBatch.id))) == 1

    await add_member(UUID(project["workspace_id"]), "bob", "viewer")
    bob = client_for(BOB)
    assert (await bob.get(f"{base}/trend-radar")).json()["can_refresh"] is False
    assert (await bob.get(f"{base}/category-shelf")).status_code == 200
    assert (await bob.post(f"{base}/trend-radar/refresh", json={})).status_code == 403
    assert (await bob.post(f"{base}/category-shelf/refresh", json={})).status_code == 403


async def test_the_demo_category_shelf_lists_what_wikidata_records_and_leaves_the_rest_unknown(aamod: httpx.AsyncClient, unseeded: None) -> None:
    client = aamod
    with no_network():
        _, base = await aamod_campaign(client)
        first = await client.post(f"{base}/category-shelf/refresh", json={})
        assert first.status_code == 200, first.text
        shelf = (await client.post(f"{base}/category-shelf/refresh", json={})).json()
    assert shelf["mode"] == "demo" and shelf["source_line"] == ""
    assert shelf["category"]["pack_label"] == "Festive sweets and snacks"
    assert shelf["snapshot"]["version"] == 2 and [h["version"] for h in shelf["history"]] == [1]
    regions = {r["region_code"]: r for r in shelf["regions"]}
    mh = {e["label"]: e for e in regions["IN-MH"]["entities"]}
    haldirams = mh["Haldiram's"]
    assert haldirams["kind"] == "brand" and haldirams["founded_year"] == 1937 and "Maharashtra" in haldirams["basis"]
    assert haldirams["wikidata_url"].startswith("https://www.wikidata.org/wiki/Q") and haldirams["attention"]["direction"] in ("rising", "falling", "steady", "mixed", "insufficient")
    assert haldirams["attention"]["confidence"] in ("low", "moderate") and haldirams["sources"][0]["kind"] == "observed"
    zam = mh["Zam zam sweets"]  # no Wikipedia article: attention is absent and says why, the fields it lacks are named
    assert zam["attention"] is None and "No Wikipedia article" in zam["attention_note"]
    assert any("headquarters or origin" in e["unknown"] for e in shelf["unplaced"])  # what Wikidata lacks is named, not filled
    assert [e["label"] for e in regions["IN-TN"]["entities"]] == ["Sri Krishna Sweets"] and "links no festive sweets and snacks" in regions["IN-KL"]["gaps"][0]
    assert regions["IN-WB"]["entities"] == [] and "links no festive sweets and snacks" in regions["IN-WB"]["gaps"][0]
    assert shelf["unplaced"] and all(e["places"] == [] or not e["attention"] for e in shelf["unplaced"])
    assert shelf["excluded"] and all(x["reason"] and x["url"].startswith("https://www.wikidata.org/wiki/Q") for x in shelf["excluded"])
    text = json.dumps(shelf).lower()
    for forbidden in ('"price"', '"sales"', '"market_share"', '"revenue"', '"ad_spend"'):
        assert forbidden not in text
    assert any("no prices, sales" in line.lower() for line in shelf["limitations"])


# --- live: fakes --------------------------------------------------------------------------------------------------------


class FakePageviews(SourceBase):
    name = "wikipedia_pageviews"
    descriptor = SourceDescriptor(
        name="wikipedia_pageviews", source_type="trend_series", supported_operations=frozenset({"trend_series"}), scope="test",
        coverage_limitations=[])

    def __init__(self, *, fail: bool = False, missing: set[str] | None = None) -> None:
        self.fail, self.missing, self.asked = fail, missing or set(), []

    async def trend_series(self, term: str, *, region_code: str, start: date, end: date) -> TrendSeries | None:
        self.asked.append((term, region_code))
        if self.fail:
            raise SourceRateLimited("wikipedia_pageviews", "trend_series", "HTTP 429 (server asks to retry after 99s)")
        if term in self.missing:
            return None
        region = region_for(region_code)
        assert region is not None
        months = [date(2024 + (10 + i) // 12, (10 + i) % 12 + 1, 1) for i in range(24)]
        editions = []
        for language, level in ((region.language, 400), ("en", 4000)):
            points = [TrendPoint(date=d, views=level if i < 12 else level * 2) for i, d in enumerate(months)]
            editions.append(TrendEdition(
                language=language, project=f"{language}.wikipedia", article=term, points=points, total=sum(p.views for p in points),
                baseline=[TrendPoint(date=d, views=1_000_000) for d in months]))
        source = SourceRef(source_type="wikipedia_pageviews", source_identifier=f"pageviews:{term}", url="https://example.org/pv",
                           retrieved_at=NOW, independence_group="wikimedia")
        return TrendSeries(term=term, region_code=region_code, granularity="monthly", start=months[0], end=date(2026, 10, 31),
                           editions=editions, caveat="test", source=source)


class FakeShelf:
    def __init__(self) -> None:
        self.calls = 0

    async def discover(self, pack: CategoryPack) -> ShelfDiscovery:
        self.calls += 1
        entity = ShelfEntity(
            entity_id="Q7585868", label="Test Sweets", description="chain of confectionery stores", kind="brand", classes=["business"],
            website=None, founded_year=None, places=[ShelfPlace(entity_id="Q1", label="Coimbatore")], region_codes=["IN-TN"],
            region_basis="headquarters Coimbatore, which Wikidata places in Tamil Nadu", wikipedia_languages=2,
            sitelinks={"en": "Test Sweets"}, wikidata_url="https://www.wikidata.org/wiki/Q7585868")
        return ShelfDiscovery(
            pack_key=pack.key, entities=[entity], excluded=[ShelfExcluded(entity_id="Q9", label="A film", reason="A film.")], gaps=[],
            calls=[], retrieved_at=NOW)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch, offline_live: None) -> dict[str, Any]:
    pageviews, shelf = FakePageviews(), FakeShelf()
    state: dict[str, Any] = {"pageviews": pageviews, "shelf": shelf}
    monkeypatch.setattr(shared, "make_trend_service", lambda settings, mode: CultureService([state["pageviews"]], mode="live"))
    monkeypatch.setattr(shared, "make_shelf_source", lambda settings, mode: state["shelf"])
    monkeypatch.setenv("LENS_TREND_MIN_INTERVAL_SECONDS", "300")
    get_settings.cache_clear()
    return state


async def test_a_live_radar_reads_the_regional_edition_stores_a_snapshot_and_spaces_refreshes(
        client: httpx.AsyncClient, seeded: Any, fakes: dict[str, Any]) -> None:
    _, base = await live_campaign(client)
    await build(client, base, "IN-TN")  # live claims from the offline sources: festivals with their Wikipedia articles
    refreshed = await client.post(f"{base}/trend-radar/refresh", json={"region_codes": ["IN-TN"], "max_terms": 2})
    assert refreshed.status_code == 200, refreshed.text
    radar = refreshed.json()
    assert radar["mode"] == "live" and radar["source_line"].startswith("Public data: Wikipedia pageviews")
    assert radar["category"]["status"] == "no_category"  # no category stated: no category topics are read, and it is said
    tn = radar["regions"][0]
    assert tn["supported"] and tn["edition_language"] == "ta" and len(tn["items"]) == 2
    item = tn["items"][0]
    assert item["direction"] == "rising" and item["change"] == pytest.approx(1.0) and item["basis"] == "regional_edition"
    assert item["confidence"] == "high"  # 800 views a month, the English edition and the last three months agree with the year
    assert item["primary"]["language"] == "ta" and item["reference"]["language"] == "en"
    assert any("category" in g for g in tn["gaps"])
    assert sorted(t for t, _ in fakes["pageviews"].asked) == sorted(i["term"] for i in tn["items"])
    async with read_session() as s:
        assert await s.scalar(select(func.count(m.LensTrendSnapshot.id)).where(m.LensTrendSnapshot.mode == "live")) == 2
        assert await s.scalar(select(func.count(m.CultureCall.id)).where(m.CultureCall.mode == "live", m.CultureCall.source == "wikipedia_pageviews")) == 2

    spaced = await client.post(f"{base}/trend-radar/refresh", json={"region_codes": ["IN-TN"]})
    assert spaced.status_code == 429 and "IN-TN was refreshed" in spaced.json()["error"]["message"]
    too_many = await client.post(f"{base}/trend-radar/refresh", json={"region_codes": ["IN-MH", "IN-TN", "IN-KL", "IN-WB"]})
    assert too_many.status_code == 422  # a request holds at most 4 states; live takes 3: refused before any call
    too_many = await client.post(f"{base}/trend-radar/refresh", json={"region_codes": ["IN-MH", "IN-KL", "IN-WB", "IN-TN"][:3] + ["IN-KA"]})
    assert too_many.status_code == 422


async def test_a_source_that_fails_or_a_state_without_an_edition_is_reported_not_hidden(
        client: httpx.AsyncClient, seeded: Any, fakes: dict[str, Any]) -> None:
    _, base = await live_campaign(client)
    await build(client, base, "IN-TN")
    fakes["pageviews"] = FakePageviews(fail=True)
    radar = (await client.post(f"{base}/trend-radar/refresh", json={"region_codes": ["IN-TN", "IN-KA"], "max_terms": 2})).json()
    tn, ka = radar["regions"]
    assert tn["items"] == [] and any("could not be read (rate_limited)" in g for g in tn["gaps"])
    assert ka["supported"] is False and "No regional-language Wikipedia edition is mapped for Karnataka" in ka["gaps"][0]
    async with read_session() as s:
        assert await s.scalar(select(func.count(m.LensTrendSnapshot.id))) == 0  # nothing was invented to fill the gap
        errors = await s.scalar(select(func.count(m.CultureCall.id)).where(
            m.CultureCall.status == "error", m.CultureCall.source == "wikipedia_pageviews"))
    assert errors == 2  # both terms asked; each failure is in the log Data Health reads

    fakes["pageviews"] = FakePageviews(missing={"Pongal (festival)", "Puthandu", "Diwali"})
    again = (await client.post(f"{base}/trend-radar/refresh", json={"region_codes": ["IN-TN"], "max_terms": 3})).status_code
    assert again == 429  # still inside the minimum interval: a failed refresh is a refresh, the source is not hammered


async def test_a_live_shelf_needs_a_category_pack_then_stores_versions_and_reads_attention(
        client: httpx.AsyncClient, seeded: Any, fakes: dict[str, Any]) -> None:
    _, base = await live_campaign(client)
    unread = (await client.get(f"{base}/category-shelf", params=[("region_code", "IN-TN")])).json()
    assert unread["category"]["status"] == "no_category" and unread["snapshot"] is None and unread["can_refresh"] is False
    assert len(unread["packs"]) >= 4
    refused = await client.post(f"{base}/category-shelf/refresh", json={"region_codes": ["IN-TN"]})
    assert refused.status_code == 422 and "Choose one of" in refused.json()["error"]["details"][0]["message"]
    assert (await client.post(f"{base}/category-shelf/refresh", json={"pack_key": "nope"})).status_code == 422

    chosen = await client.post(f"{base}/category-shelf/refresh", json={"pack_key": "festive_sweets_snacks", "region_codes": ["IN-TN"]})
    assert chosen.status_code == 200, chosen.text
    shelf = chosen.json()
    assert shelf["category"]["status"] == "chosen" and shelf["snapshot"]["version"] == 1 and shelf["source_line"].startswith("Public data: Wikidata")
    entity = shelf["regions"][0]["entities"][0]
    assert entity["label"] == "Test Sweets" and entity["attention"]["direction"] == "rising" and entity["attention"]["language"] == "ta"
    assert entity["unknown"] == ["founded", "official website"] and shelf["excluded"][0]["reason"] == "A film."
    assert fakes["pageviews"].asked == [("Q7585868", "IN-TN")]
    # the pack this campaign last chose is the one a plain read shows
    assert (await client.get(f"{base}/category-shelf", params=[("region_code", "IN-TN")])).json()["snapshot"]["version"] == 1
    spaced = await client.post(f"{base}/category-shelf/refresh", json={"pack_key": "festive_sweets_snacks"})
    assert spaced.status_code == 429


async def test_another_workspace_sees_nothing_of_either_view(client: httpx.AsyncClient, client_for: Any, seeded: Any, fakes: dict[str, Any]) -> None:
    _, base = await live_campaign(client)
    bob = client_for(BOB)
    for method, path, body in (("get", "trend-radar", None), ("get", "category-shelf", None),
                               ("post", "trend-radar/refresh", {}), ("post", "category-shelf/refresh", {})):
        response = await (bob.get(f"{base}/{path}") if method == "get" else bob.post(f"{base}/{path}", json=body))
        assert response.status_code == 404, path
    assert (await client.get(f"{base}/trend-radar", params=[("region_code", "IN-ZZ")])).status_code == 404
    assert (await client.post(f"{base}/trend-radar/refresh", json={"surprise": 1})).status_code == 422
