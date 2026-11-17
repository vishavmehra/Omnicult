"""Wikipedia pageviews adapter: recorded exchange for Pongal (festival) in the Tamil and English editions."""

from datetime import date

import httpx
import pytest

from app.integrations.culture.adapters.wikipedia_pageviews import EARLIEST, WikipediaPageviewsSource, series_to_claim
from app.integrations.culture.base import SourceHttpError
from tests.unit.culture.culture_helpers import UA, load_recording, no_sleep, replay_client, scripted_client


async def recorded_series():
    call = load_recording("pageviews_pongal")["call"]
    async with replay_client("pageviews_pongal") as client:
        return await WikipediaPageviewsSource(user_agent=UA, client=client).trend_series(
            call["term"], region_code=call["region_code"], start=date.fromisoformat(call["start"]), end=date.fromisoformat(call["end"]))


async def test_series_reads_the_regional_and_english_editions_from_wikidata_sitelinks():
    series = await recorded_series()
    ta, en = series.editions
    assert (ta.language, ta.project, ta.article) == ("ta", "ta.wikipedia", "தைப்பொங்கல்")  # the Tamil title, not a translation guess
    assert (en.language, en.article) == ("en", "Pongal (festival)")
    assert ta.total == sum(p.views for p in ta.points) == 27_284 and en.total == 169_615
    assert series.granularity == "monthly" and len(ta.points) == 12 and ta.points[0].date == date(2025, 11, 1)
    assert series.unit == "pageviews" and "not demand" in series.caveat


async def test_source_ref_and_claim_are_labelled_attention_not_demand():
    series = await recorded_series()
    source = series.source
    assert source.source_type == "wikipedia_pageviews" and source.publisher == "Wikimedia Foundation"
    assert source.url.startswith("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/ta.wikipedia/") and source.retrieved_at.tzinfo
    claim = series_to_claim(series)
    assert claim.category == "trend" and claim.kind == "calculated" and claim.attribute == "wikipedia_attention"
    assert claim.scope.region_code == "IN-TN" and claim.scope.period == "2025-11-01/2026-10-31"
    assert "attention to an article, not demand" in claim.value_text and claim.sources == [source]
    assert [e["language"] for e in claim.value["editions"]] == ["ta", "en"] and claim.value["editions"][0]["peak_views"] > 0


async def test_a_missing_page_range_is_an_empty_edition_not_an_error():
    sitelinks = httpx.Response(200, json={"entities": {"Q1": {"sitelinks": {"tawiki": {"title": "X"}, "enwiki": {"title": "X"}}}}})
    views = httpx.Response(200, json={"items": [{"timestamp": "2026010100", "views": 5}]})
    async with scripted_client([sitelinks, httpx.Response(404, json={"detail": "no data"}), views]) as client:
        series = await WikipediaPageviewsSource(user_agent=UA, client=client).trend_series(
            "Q1", region_code="IN-TN", start=date(2026, 1, 1), end=date(2026, 1, 31))
    assert [(e.language, e.total, len(e.points)) for e in series.editions] == [("ta", 0, 0), ("en", 5, 1)]
    assert series.granularity == "daily"


async def test_a_term_without_sitelinks_has_no_series():
    async with scripted_client([httpx.Response(200, json={"entities": {"-1": {"missing": ""}}})]) as client:
        assert await WikipediaPageviewsSource(user_agent=UA, client=client).trend_series(
            "Nothing", region_code="IN-TN", start=date(2026, 1, 1), end=date(2026, 1, 31)) is None


async def test_invalid_ranges_and_regions_make_no_request():
    async with scripted_client([]) as client:  # any request would raise
        source = WikipediaPageviewsSource(user_agent=UA, client=client)
        assert await source.trend_series("Pongal", region_code="IN-GJ", start=date(2026, 1, 1), end=date(2026, 2, 1)) is None
        assert await source.trend_series("Pongal", region_code="IN-TN", start=date(2026, 2, 1), end=date(2026, 1, 1)) is None
        assert await source.trend_series("Pongal", region_code="IN-TN", start=date(2010, 1, 1), end=date(2014, 1, 1)) is None


async def test_the_start_is_clipped_to_the_first_available_day():
    sitelinks = httpx.Response(200, json={"entities": {"Q1": {"sitelinks": {"enwiki": {"title": "X"}}}}})
    seen: list[httpx.Request] = []
    async with scripted_client([sitelinks, httpx.Response(404), httpx.Response(404)], seen) as client:
        series = await WikipediaPageviewsSource(user_agent=UA, client=client).trend_series(
            "Q1", region_code="IN-MH", start=date(2010, 1, 1), end=date(2016, 1, 1))
    assert series.start == EARLIEST and "/20150701/20160101" in str(seen[1].url)


async def test_server_errors_are_typed_after_bounded_retries():
    sitelinks = httpx.Response(200, json={"entities": {"Q1": {"sitelinks": {"enwiki": {"title": "X"}}}}})
    async with scripted_client([sitelinks, *[httpx.Response(500)] * 3]) as client:
        source = WikipediaPageviewsSource(user_agent=UA, client=client, sleep=no_sleep)
        with pytest.raises(SourceHttpError):
            await source.trend_series("Q1", region_code="IN-MH", start=date(2026, 1, 1), end=date(2026, 1, 31))
