"""The India Country Pack: a versioned description of existing reference data, with its seed status and fingerprint."""

from typing import Any

import httpx

from app.reference import india, india_pack
from tests.api.omnicult_support import API, client_for, seeded  # noqa: F401
from tests.conftest import BOB

PINNED = ("1", "f9a55ff683f7e73e3199ae6a6b9866083385b5764707e0f1c086e5b76651d8a2")


def test_changing_the_reference_data_requires_a_new_pack_version() -> None:
    """If this fails, you changed regions, languages or moments: bump `india.PACK_VERSION`, then update PINNED."""
    assert (india.PACK_VERSION, india_pack.content_fingerprint()) == PINNED


async def test_the_pack_describes_regions_languages_sources_and_gaps(client: httpx.AsyncClient, seeded: Any) -> None:
    response = await client.get(f"{API}/country-packs/IN")
    assert response.status_code == 200, response.text
    pack = response.json()
    assert (pack["country_code"], pack["version"], pack["citation"]) == ("IN", "1", "Omnicult India Country Pack v1")
    assert pack["content_sha256"] == india_pack.content_fingerprint()
    assert (pack["regions"]["total"], pack["regions"]["states"], pack["regions"]["union_territories"]) == (36, 28, 8)
    assert pack["regions"]["demo_codes"] == ["IN-MH", "IN-TN", "IN-KL", "IN-WB"]
    assert pack["regions"]["list_path"] == "/api/v1/regions?country_code=IN"  # linked, not duplicated: no region rows here
    assert "regions" not in {k for k in pack if isinstance(pack[k], list)}
    assert pack["seed"]["loaded"] is True and pack["seed"]["regions_in_database"] == 36
    languages = {x["code"]: x for x in pack["languages"]}
    assert languages["ta"]["script"] == "Taml" and languages["ur"]["direction"] == "rtl" and languages["hi"]["region_count"] > 5
    assert {s["code"]: s["name"] for s in pack["scripts"]}["Deva"] == "Devanagari"
    assert [c["id"] for c in pack["calendar_sources"]] == ["moments", "holidays_calendar", "curated_references"]
    assert pack["ad_codes"]["entries"] > 10 and pack["ad_codes"]["sha256"] and pack["ad_codes"]["limitations"]
    assert pack["never_sampled"] and "caste" in pack["never_sampled"]
    assert any("Maithili" in g for g in pack["known_gaps"]) and any(g.startswith("ASCI index:") for g in pack["known_gaps"])
    assert {link["path"] for link in pack["links"]} >= {"/api/v1/regions?country_code=IN", "/api/v1/ad-codes"}


async def test_every_data_source_states_its_licence_review_honestly(client: httpx.AsyncClient, seeded: Any) -> None:
    sources = {s["id"]: s for s in (await client.get(f"{API}/country-packs/IN")).json()["data_sources"]}
    assert sources["wikidata"]["licence"] == "CC0 1.0" and sources["wikidata"]["licence_checked_on"] == "2026-11-17"
    assert sources["python-holidays"]["licence"] == "MIT"
    for s in sources.values():
        assert (s["licence_status"] == "checked") == (s["licence"] is not None and s["licence_checked_on"] is not None) or s["licence_status"] == "not_checked"
        if s["licence_status"] == "not_checked":
            assert s["licence_checked_on"] is None  # never a made-up review date
    assert sources["asci-code-index"]["retrieved_on"] and sources["census-2011-c16"]["retrieved_on"] == "2026-11-17"
    assert sources["wikidata"]["retrieved_on"] is None  # queried live


async def test_an_unseeded_database_is_reported_not_hidden(client: httpx.AsyncClient) -> None:
    seed = (await client.get(f"{API}/country-packs/IN")).json()["seed"]
    assert (seed["loaded"], seed["regions_in_database"], seed["pack_record_loaded"]) == (False, 0, False)


async def test_unknown_countries_and_anonymous_requests(client: httpx.AsyncClient, client_for: Any, seeded: Any) -> None:
    assert (await client.get(f"{API}/country-packs/FR")).status_code == 404
    assert (await client.get(f"{API}/country-packs/india")).status_code == 422
    assert (await client_for(BOB).get(f"{API}/country-packs/IN")).status_code == 200  # any signed-in user
    assert (await client_for({}).get(f"{API}/country-packs/IN")).status_code == 401
