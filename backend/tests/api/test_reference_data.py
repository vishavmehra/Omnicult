"""Reference data: 36 Indian states and union territories, languages and scripts, and an idempotent seed."""

from typing import Any

import httpx
from sqlalchemy import func, select

from app.db import models as m
from app.db.session import read_session, session
from app.reference import india
from app.reference.seed import seed_reference_data
from tests.api.omnicult_support import API, seed, seeded  # noqa: F401

DEMO_PRIMARY = {"IN-MH": "mr", "IN-TN": "ta", "IN-KL": "ml", "IN-WB": "bn"}


def test_all_36_states_and_union_territories_are_listed_once() -> None:
    codes = [r.code for r in india.REGIONS]
    assert len(codes) == 36 and len(set(codes)) == 36
    assert all(code.startswith("IN-") and len(code) == 5 for code in codes)
    kinds = [r.kind for r in india.REGIONS]
    assert kinds.count("state") == 28 and kinds.count("union_territory") == 8
    assert set(india.DEMO_REGIONS) <= set(codes)


def test_every_language_and_script_a_region_uses_is_defined() -> None:
    known = {row.code for row in india.LANGUAGES}
    for region in india.REGIONS:
        assert {region.primary, *region.secondary} <= known, region.code
        assert region.primary not in region.secondary, region.code
    scripts = {row.script for row in india.LANGUAGES}
    assert {"Deva", "Taml", "Mlym", "Beng", "Latn"} <= scripts  # the contract's demo scripts
    assert {r.code for r in india.LANGUAGES} >= {"mr", "ta", "ml", "bn", "hi", "en"}  # the contract's demo languages
    assert all(row.direction == "rtl" for row in india.LANGUAGES if row.script == "Arab")
    assert all(len(row.code) == 2 for row in india.LANGUAGES if row.standard == "iso639-1")
    assert all(len(row.code) == 3 for row in india.LANGUAGES if row.standard == "iso639-3")


def test_region_ids_are_stable() -> None:
    assert india.region_id("IN-TN") == india.region_id("IN-TN") != india.region_id("IN-KL")


async def test_seed_loads_the_reference_tables(app: Any) -> None:
    async with session() as s, s.begin():
        counts = await seed_reference_data(s)
    assert (counts.languages, counts.regions, counts.packs) == (len(india.LANGUAGES), 36, 1)
    async with read_session() as s:
        regions = {r.code: r for r in (await s.execute(select(m.Region))).scalars()}
        assert len(regions) == 36
        for code, language in DEMO_PRIMARY.items():
            assert regions[code].primary_language_code == language
        assert regions["IN-TN"].primary_script == "Taml" and regions["IN-MH"].primary_script == "Deva"
        assert regions["IN-WB"].primary_script == "Beng" and regions["IN-KL"].primary_script == "Mlym"
        pack = (await s.execute(select(m.CountryPack))).scalar_one()
        assert pack.country_code == "IN" and len(pack.pack["region_codes"]) == 36
        assert "religion" in pack.pack["never_sampled"] and pack.pack["sampling_dimensions"]["city_tier"][0] == "tier1"
        primary = (await s.execute(
            select(m.RegionLanguageProfile.region_id).where(m.RegionLanguageProfile.role == "primary"))).scalars().all()
        assert len(primary) == len(set(primary)) == 36  # exactly one primary language per region
        national = await s.scalar(select(func.count(m.RegionalMoment.id)).where(m.RegionalMoment.region_id.is_(None)))
        assert national == 4
        tn_moments = (await s.execute(
            select(m.RegionalMoment.slug).where(m.RegionalMoment.region_id == india.region_id("IN-TN")))).scalars().all()
        assert set(tn_moments) == {"pongal", "puthandu"}


async def test_seed_is_idempotent_and_repairs_changed_rows(app: Any) -> None:
    await seed()
    async with session() as s, s.begin():  # someone edits a row by hand
        tn = await s.get(m.Region, india.region_id("IN-TN"))
        assert tn is not None
        tn.name = "Wrong"
    await seed()
    await seed()
    async with read_session() as s:
        counts = {
            table: await s.scalar(select(func.count()).select_from(table))
            for table in (m.Language, m.Region, m.RegionLanguageProfile, m.RegionalMoment, m.CountryPack)
        }
        assert counts[m.Region] == 36 and counts[m.CountryPack] == 1 and counts[m.Language] == len(india.LANGUAGES)
        assert counts[m.RegionalMoment] == len(india.MOMENTS)
        assert (await s.get(m.Region, india.region_id("IN-TN"))).name == "Tamil Nadu"  # type: ignore[union-attr]


async def test_regions_api_lists_regions_with_languages(seeded: Any, client: httpx.AsyncClient) -> None:
    page = (await client.get(f"{API}/regions")).json()
    assert page["total"] == 36 and len(page["items"]) == 36
    names = [r["name"] for r in page["items"]]
    assert names == sorted(names)
    tn = next(r for r in page["items"] if r["code"] == "IN-TN")
    assert tn["primary_language"] == "ta" and tn["primary_script"] == "Taml" and tn["kind"] == "state"
    assert [(lang["code"], lang["role"], lang["script"]) for lang in tn["languages"]] == [
        ("ta", "primary", "Taml"), ("en", "secondary", "Latn")]
    first_page = (await client.get(f"{API}/regions", params={"limit": 10, "offset": 30})).json()
    assert len(first_page["items"]) == 6 and first_page["total"] == 36
    assert (await client.get(f"{API}/regions", params={"country_code": "US"})).json()["total"] == 0


async def test_one_region_and_unknown_region(seeded: Any, client: httpx.AsyncClient) -> None:
    kerala = (await client.get(f"{API}/regions/IN-KL")).json()
    assert kerala["name"] == "Kerala" and kerala["languages"][0]["code"] == "ml"
    assert (await client.get(f"{API}/regions/IN-ZZ")).status_code == 404
    assert (await client.get(f"{API}/regions/not-a-code")).status_code == 422


async def test_regions_need_authentication(seeded: Any, client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{API}/regions", headers={"Authorization": ""})).status_code == 401
