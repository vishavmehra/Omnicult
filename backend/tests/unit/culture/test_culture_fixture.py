"""Fixture source: deterministic, clearly labelled, and incapable of reaching the network."""

from datetime import UTC, date, datetime

import httpx
import pytest

from app.core.config import Settings
from app.integrations.culture import FixtureCultureSource, build_culture_service
from app.integrations.culture.adapters.wikipedia_pageviews import series_to_claim
from app.integrations.culture.fixture import FIXTURE_TIME


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("the fixture source must not touch the network")

    monkeypatch.setattr(httpx.AsyncClient, "send", boom)


async def snapshot(source: FixtureCultureSource) -> str:
    series = await source.trend_series("Pongal (festival)", region_code="IN-TN", start=date(2026, 1, 1), end=date(2026, 1, 20))
    parts = [
        (await source.resolve_entity("Pongal", language="en", region_code="IN-TN")).model_dump_json(),
        *(c.model_dump_json() for c in await source.related_signals("region:IN-TN", region_code="IN-TN", limit=500)),
        *(c.model_dump_json() for c in await source.audience_facts("IN-TN")),
        *(c.model_dump_json() for c in await source.moments("IN-TN", year=2026)),
        series.model_dump_json(),
    ]
    return "\n".join(parts)


async def test_two_instances_produce_identical_output():
    assert await snapshot(FixtureCultureSource()) == await snapshot(FixtureCultureSource())


async def test_every_source_is_marked_by_identifier_with_a_fixed_timestamp():
    source = FixtureCultureSource()
    claims = [*await source.related_signals("region:IN-KL", region_code="IN-KL", limit=500), *await source.audience_facts("IN-KL"),
              *await source.moments("IN-KL", year=2026)]
    assert claims and source.mode == "fixture" and FIXTURE_TIME == datetime(2026, 11, 17, tzinfo=UTC)
    for claim in claims:
        assert claim.retrieved_at == FIXTURE_TIME
        for s in claim.sources:
            assert s.source_identifier.startswith("fixture:") and "DEMO FIXTURE" not in s.title and s.retrieved_at == FIXTURE_TIME


async def test_trend_series_is_synthetic_by_identifier_and_kind():
    series = await FixtureCultureSource().trend_series("Onam", region_code="IN-KL", start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert "FIXTURE" not in series.caveat and series.source.source_identifier.startswith("fixture:")
    assert [e.language for e in series.editions] == ["ml", "en"] and len(series.editions[0].points) == 31
    claim = series_to_claim(series)
    assert claim.kind == "synthetic" and "not demand" in claim.value_text


async def test_recorded_entity_queries_resolve_like_the_live_adapter():
    source = FixtureCultureSource()
    pongal = await source.resolve_entity("Pongal", language="en", region_code="IN-TN")
    assert pongal.status == "ambiguous" and {"Q10253", "Q29271"} <= {c.entity_id for c in pongal.candidates}
    gudi = await source.resolve_entity("gudi padwa", language="en", region_code="IN-MH")
    assert gudi.status == "resolved" and gudi.entity.entity_id == "Q615384"
    assert (await source.resolve_entity("something never recorded")).status == "unresolved"
    assert all(c.source == "fixture" for c in pongal.candidates)


def test_demo_mode_service_is_fixture_only_and_uncached():
    service = build_culture_service(Settings(_env_file=None, app_env="test"), mode="demo")
    assert service.mode == "fixture" and [s.name for s in service.sources] == ["fixture"] and service.cache is None
    assert service.is_configured()


def test_live_mode_service_lists_every_adapter_and_skips_grounding_without_a_capability():
    service = build_culture_service(Settings(_env_file=None, app_env="test"), mode="live")
    assert [s.name for s in service.sources] == ["curated", "census_2011", "holidays_calendar", "wikidata", "wikipedia_pageviews",
                                                  "gemini_grounding"]
    assert service.skipped_sources() == ["gemini_grounding"] and service.cache is not None
