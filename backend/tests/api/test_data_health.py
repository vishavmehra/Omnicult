"""Data Health: freshness rules, cache state, call-log honesty, region coverage, and workspace isolation."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.db.base import utcnow
from app.services import data_health
from app.services.data_health import cache_state, claim_state, freshness_label
from app.services.metering import AiUsage, record_ai_usage
from tests.api.omnicult_support import add_member, client_for, draft, put_claims, seeded, source, workspace_of  # noqa: F401
from tests.api.proof_support import API
from tests.conftest import BOB

CLOCK = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def test_freshness_label_rules() -> None:
    assert freshness_label(0, 0, 0) == "unknown"
    assert freshness_label(4, 0, 0) == "fresh"
    assert freshness_label(4, 1, 0) == "aging" and freshness_label(4, 0, 2) == "aging"
    assert freshness_label(4, 1, 1) == "aging"  # under half expired
    assert freshness_label(4, 2, 0) == "expired"  # half or more past their expiry
    assert freshness_label(1, 1, 0) == "expired"


def test_cache_state_separates_fixtures_from_stored_live_copies() -> None:
    assert [cache_state(0, 0), cache_state(3, 0), cache_state(0, 2), cache_state(1, 1)] == ["none", "stored_live", "fixture", "mixed"]


def fake_claim(**kw: Any) -> Any:
    return SimpleNamespace(**({"id": uuid4(), "expires_at": None, "scope": {}} | kw))


def fake_source(published: date | None, source_type: str = "wikidata") -> Any:
    return SimpleNamespace(source_type=source_type, independence_group="g", published_at=published, retrieved_at=CLOCK, excerpt=None)


def test_a_claim_past_its_expiry_is_expired_an_old_observed_source_is_aging_the_rest_fresh() -> None:
    now = CLOCK
    assert claim_state(fake_claim(expires_at=now - timedelta(seconds=1)), [fake_source(date(2026, 1, 1))], now) == "expired"
    assert claim_state(fake_claim(expires_at=now + timedelta(days=1)), [fake_source(date(2026, 1, 1))], now) == "fresh"
    assert claim_state(fake_claim(), [fake_source(date(2011, 3, 1), "census_2011")], now) == "aging"  # two years or older
    assert claim_state(fake_claim(), [fake_source(date(2025, 6, 1))], now) == "fresh"
    # an expired claim stays expired whatever its sources say
    assert claim_state(fake_claim(expires_at=now), [fake_source(date(2011, 3, 1))], now) == "expired"


async def put(ws: UUID | None, value: Any, *, expires: datetime | None = None, region: str | None = "IN-TN", attribute: str = "major_festival",
              source_type: str = "wikidata", published: date | None = date(2026, 1, 1), mode: str = "live", group: str = "wikimedia",
              category: str = "festival") -> None:
    d = draft(value, attribute=attribute, category=category, region=region, sources=[source(group, published, source_type=source_type)])
    d.expires_at = expires
    await put_claims(ws, [d], mode=mode)


def by_type(health: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["source_type"]: s for s in health["sources"]}


async def test_source_health_reports_last_retrieval_freshness_and_counts(seeded: Any, client: httpx.AsyncClient) -> None:
    ws = await workspace_of("alice")
    future, past = utcnow() + timedelta(days=30), utcnow() - timedelta(days=1)
    await put(ws, "Pongal", expires=future)
    await put(ws, "Thai Pusam", expires=past, attribute="minor_festival")
    await put(ws, "Aadi Perukku", expires=future, attribute="monsoon_festival")
    await put(ws, 0.8, attribute="literacy", source_type="census_2011", published=date(2011, 3, 1), group="census", category="demographic")
    health = (await client.get(f"{API}/workspaces/{ws}/data-health")).json()
    sources = by_type(health)
    wikidata = sources["wikidata"]
    assert (wikidata["claims"], wikidata["fresh_claims"], wikidata["aging_claims"], wikidata["expired_claims"]) == (3, 2, 0, 1)
    assert wikidata["freshness"] == "aging" and wikidata["cache_state"] == "stored_live" and wikidata["region_codes"] == ["IN-TN"]
    assert wikidata["last_retrieved_at"] == "2026-11-17T12:00:00Z" and wikidata["live_claims"] == 3 and wikidata["fixture_claims"] == 0
    census = sources["census_2011"]
    assert (census["claims"], census["aging_claims"], census["expired_claims"], census["freshness"]) == (1, 1, 0, "aging")
    assert health["mode"] == "live" and health["rules"]["stale_window_years"] == 2 and any("never calls a source" in x for x in health["limitations"])
    await put(ws, "Kolam day", expires=past, attribute="other_festival")  # now two of four are expired
    assert by_type((await client.get(f"{API}/workspaces/{ws}/data-health")).json())["wikidata"]["freshness"] == "expired"


async def test_attempts_are_reported_only_where_they_are_logged(seeded: Any, client: httpx.AsyncClient) -> None:
    ws = await workspace_of("alice")
    await put(ws, "Pongal")
    health = by_type((await client.get(f"{API}/workspaces/{ws}/data-health")).json())
    wikidata = health["wikidata"]
    assert (wikidata["attempts_logged"], wikidata["attempts"], wikidata["errors"], wikidata["last_error"]) == (False, None, None, None)
    assert "not logged" in wikidata["limitations"][0]
    grounding = health["gemini_grounding"]  # logged through ai_usage_events, even with no claim stored from it
    assert (grounding["attempts_logged"], grounding["attempts"], grounding["errors"], grounding["claims"], grounding["freshness"]) == (True, 0, 0, 0, "unknown")
    for status, code in (("ok", None), ("error", "RATE_LIMITED"), ("error", "PROVIDER_TIMEOUT")):
        await record_ai_usage(AiUsage(capability="grounded_research", provider="google", model="gemini-x", status=status,
                                      error_code=code, workspace_id=ws))
    await record_ai_usage(AiUsage(capability="text", provider="google", model="gemini-x", workspace_id=ws))  # not a retrieval
    await record_ai_usage(AiUsage(capability="grounded_research", provider="google", model="gemini-x", status="error",
                                  error_code="OTHER_WORKSPACE", workspace_id=await workspace_of("bob")))
    grounding = by_type((await client.get(f"{API}/workspaces/{ws}/data-health")).json())["gemini_grounding"]
    assert (grounding["attempts"], grounding["errors"], grounding["last_error"]["code"]) == (3, 2, "PROVIDER_TIMEOUT")
    assert grounding["last_attempt_at"] and grounding["attempts_logged"] is True


async def test_a_registered_call_log_is_used_for_its_source_type(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_health, "CALL_LOG_READERS", dict(data_health.CALL_LOG_READERS))
    stamp = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)

    async def reader(s: Any, workspace_id: UUID) -> data_health.CallStats:
        return data_health.CallStats(attempts=7, errors=2, last_attempt_at=stamp, last_error=(stamp, "HTTP_500"))

    data_health.register_call_log("wikidata", reader)
    ws = await workspace_of("alice")
    await put(ws, "Pongal")
    wikidata = by_type((await client.get(f"{API}/workspaces/{ws}/data-health")).json())["wikidata"]
    assert (wikidata["attempts"], wikidata["errors"], wikidata["attempts_logged"], wikidata["limitations"]) == (7, 2, True, [])
    assert wikidata["last_error"] == {"at": "2026-11-16T08:00:00Z", "code": "HTTP_500"} and wikidata["last_attempt_at"] == "2026-11-16T08:00:00Z"


async def test_region_coverage_matches_the_evidence_meter_and_shows_thin_regions(seeded: Any, client: httpx.AsyncClient) -> None:
    ws = await workspace_of("alice")
    await put(ws, "Pongal")
    await put(ws, 0.8, attribute="literacy", source_type="census_2011", published=date(2011, 3, 1), group="census", category="demographic")
    health = (await client.get(f"{API}/workspaces/{ws}/data-health")).json()
    regions = {r["region_code"]: r for r in health["regions"]}
    assert len(regions) == 36  # every state and union territory, so a thin region is visible, not omitted
    tn, mh = regions["IN-TN"], regions["IN-MH"]
    assert (tn["claims"], tn["supported_claims"], tn["categories_covered"], tn["categories_total"]) == (2, 2, 2, 14)
    assert tn["strength"] == "weak" and tn["source_types"] == ["census_2011", "wikidata"] and tn["newest_source_date"] == "2026-01-01"
    assert "festival" not in tn["missing_categories"] and "food" in tn["missing_categories"]
    assert (mh["claims"], mh["strength"], mh["strength_reasons"]) == (0, "weak", ["No claims are recorded for this region yet."])
    meter = (await client.get(f"{API}/workspaces/{ws}/regions/IN-TN/evidence-meter")).json()
    assert (meter["claims"], meter["supported_claims"], meter["strength"], meter["sources"]) == (tn["claims"], tn["supported_claims"], tn["strength"], tn["sources"])


async def test_demo_fixtures_and_live_claims_are_never_mixed(seeded: Any, client: httpx.AsyncClient) -> None:
    ws = await workspace_of("alice")
    await put(ws, "Pongal")
    await put(None, "Onam", region="IN-KL", mode="demo", group="fixture")
    live = by_type((await client.get(f"{API}/workspaces/{ws}/data-health")).json())["wikidata"]
    demo = by_type((await client.get(f"{API}/workspaces/{ws}/data-health", params={"mode": "demo"})).json())["wikidata"]
    assert (live["claims"], live["cache_state"], live["fixture_claims"]) == (1, "stored_live", 0)
    assert (demo["claims"], demo["cache_state"], demo["live_claims"], demo["fixture_claims"]) == (1, "fixture", 0, 1)


async def test_data_health_shows_a_workspace_only_its_own_and_shared_claims(seeded: Any, client: httpx.AsyncClient, client_for: Any) -> None:
    alice, bob_ws = await workspace_of("alice"), await workspace_of("bob")
    await put(alice, "Pongal", source_type="wikidata")
    await put(None, "Onam", region="IN-KL", source_type="wikipedia", group="wikimedia2")  # shared reference claim
    bob = client_for(BOB)
    mine = by_type((await bob.get(f"{API}/workspaces/{bob_ws}/data-health")).json())
    assert "wikidata" not in mine and mine["wikipedia"]["claims"] == 1  # alice's claim is invisible; the shared one is not
    assert (await bob.get(f"{API}/workspaces/{alice}/data-health")).status_code == 404
    assert (await client.get(f"{API}/workspaces/{bob_ws}/data-health")).status_code == 404
    await add_member(alice, "bob", "viewer")
    assert "wikidata" in by_type((await bob.get(f"{API}/workspaces/{alice}/data-health")).json())
