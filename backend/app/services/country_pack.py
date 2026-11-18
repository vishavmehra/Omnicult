"""Builds the Country Pack description from the modules and tables that already hold the India reference data."""

from functools import lru_cache
from importlib import metadata

from sqlalchemy import func, select

from app.core.errors import NotFound
from app.db import models as m
from app.db.session import read_session
from app.integrations.culture.adapters.census import CensusSource, load_census
from app.integrations.culture.adapters.curated import CuratedReferenceSource, load_curated
from app.integrations.culture.adapters.holidays_calendar import HolidaysCalendarSource
from app.integrations.culture.regions import REGIONS as CULTURE_REGIONS
from app.reference import india, india_pack
from app.reference.ad_codes import load_index
from app.schemas import country_packs as v


@lru_cache(maxsize=1)
def _holidays() -> tuple[str | None, int | None]:
    """(installed python-holidays version, India subdivisions it supports); (None, None) when it cannot be read."""
    try:
        import holidays

        return metadata.version("holidays"), len(holidays.India.subdivisions)
    except Exception:  # noqa: BLE001 - a missing optional package must not fail the description
        return None, None


def _languages() -> list[v.PackLanguage]:
    used: dict[str, int] = {}
    for region in india.REGIONS:
        for code in {region.primary, *region.secondary}:
            used[code] = used.get(code, 0) + 1
    return [
        v.PackLanguage(code=r.code, name=r.name, native_name=r.native_name, script=r.script, direction=r.direction,  # type: ignore[arg-type]
                       code_standard=r.standard, region_count=used.get(r.code, 0))  # type: ignore[arg-type]
        for r in india.LANGUAGES
    ]


def _scripts() -> list[v.PackScript]:
    by_script: dict[str, list[str]] = {}
    for row in india.LANGUAGES:
        by_script.setdefault(row.script, []).append(row.code)
    return [v.PackScript(code=c, name=india_pack.SCRIPT_NAMES.get(c, c), language_codes=by_script[c]) for c in sorted(by_script)]


def _calendar_sources() -> list[v.PackCalendarSource]:
    version, subdivisions = _holidays()
    curated = [f for code in CULTURE_REGIONS if (f := load_curated(code)) is not None]
    as_of = max((f.retrieved_on.isoformat() for f in curated), default=None)
    hol = HolidaysCalendarSource.descriptor
    cur = CuratedReferenceSource.descriptor
    return [
        v.PackCalendarSource(
            id="moments", name="Regional moments", version=india.PACK_VERSION, as_of=None, entries=len(india.MOMENTS),
            description="Festivals, holidays and seasons with typical months and calendar type (solar, lunisolar, civil), national or per state.",
            coverage="National and IN-MH, IN-TN, IN-KL, IN-WB.",
            limitations=[india.MOMENT_NOTE]),
        v.PackCalendarSource(
            id="holidays_calendar", name="Public holidays (python-holidays)", version=version, as_of=None, entries=subdivisions,
            description="Public-holiday dates by state for any year the installed package supports. The entry count is the number of India subdivisions it supports.",
            coverage=hol.scope, limitations=list(hol.coverage_limitations)),
        v.PackCalendarSource(
            id="curated_references", name="Curated festival and custom references", version=curated[0].dataset_version if curated else None,
            as_of=as_of, entries=sum(len(f.entries) for f in curated),
            description="Festivals, foods, colours, symbols, customs and sensitivities, each entry citing a page and an exact excerpt.",
            coverage=cur.scope, limitations=list(cur.coverage_limitations)),
    ]


def _ad_codes() -> v.PackAdCodes:
    index = load_index()
    return v.PackAdCodes(
        dataset=index.dataset, version=index.version, publisher=index.publisher, edition=index.source.edition,
        entries=len(index.entries), topics=sorted({t for e in index.entries for t in e.topics}), retrieved_on=index.retrieved_at,
        source_url=index.source.url, landing_page=index.source.landing_page, sha256=index.source.sha256,
        limitations=list(index.limitations))


def _data_sources() -> list[v.PackDataSource]:
    census = load_census()
    curated = [f for code in CULTURE_REGIONS if (f := load_curated(code)) is not None]
    retrieved = {
        "census-2011-c16": census.get("retrieved_on"),
        "curated-references": max((f.retrieved_on.isoformat() for f in curated), default=None),
        "asci-code-index": load_index().retrieved_at,
    }
    return [
        v.PackDataSource(
            id=n.id, name=n.name, used_for=n.used_for, url=n.url, licence=n.licence, licence_status=n.licence_status,
            licence_checked_on=india_pack.LICENCES_CHECKED_ON if n.licence_status == "checked" else None,
            licence_note=n.licence_note, retrieved_on=retrieved.get(n.id))
        for n in india_pack.SOURCE_NOTES
    ]


def _gaps() -> list[str]:
    gaps = list(india_pack.STATIC_GAPS)
    gaps.extend(f"ASCI index: {text}" for text in load_index().limitations)
    return gaps


async def _seed_status() -> v.PackSeedStatus:
    async with read_session() as s:
        regions = await s.scalar(select(func.count(m.Region.id)).where(m.Region.country_code == india.COUNTRY, m.Region.is_active))
        languages = await s.scalar(select(func.count(m.Language.code)).where(m.Language.is_active))
        moments = await s.scalar(select(func.count(m.RegionalMoment.id)).where(m.RegionalMoment.country_code == india.COUNTRY))
        pack = await s.scalar(select(m.CountryPack).where(
            m.CountryPack.country_code == india.COUNTRY, m.CountryPack.version == india.PACK_VERSION))
    counts = (int(regions or 0), int(languages or 0), int(moments or 0))
    want = (len(india.REGIONS), len(india.LANGUAGES), len(india.MOMENTS))
    return v.PackSeedStatus(
        loaded=pack is not None and all(c >= w for c, w in zip(counts, want, strict=True)),
        regions_in_database=counts[0], regions_expected=want[0], languages_in_database=counts[1], languages_expected=want[1],
        moments_in_database=counts[2], moments_expected=want[2], pack_record_loaded=pack is not None,
        pack_loaded_at=pack.created_at if pack else None)


async def get_country_pack(country_code: str) -> v.CountryPack:
    if country_code != india.COUNTRY:
        raise NotFound("No country pack exists for that country. Available: IN.")
    states = sum(1 for r in india.REGIONS if r.kind == "state")
    return v.CountryPack(
        country_code=india.COUNTRY, name=india.PACK["name"], version=india.PACK_VERSION,
        citation=f"Omnicult India Country Pack v{india.PACK_VERSION}", content_sha256=india_pack.content_fingerprint(),
        notes=india.PACK["notes"], seed=await _seed_status(),
        regions=v.PackRegions(
            total=len(india.REGIONS), states=states, union_territories=len(india.REGIONS) - states,
            demo_codes=list(india.DEMO_REGIONS), list_path=f"/api/v1/regions?country_code={india.COUNTRY}"),
        languages=_languages(), scripts=_scripts(), calendar_sources=_calendar_sources(), ad_codes=_ad_codes(),
        data_sources=_data_sources(),
        sampling_dimensions=[v.PackDimension(name=n, description=d, values=list(vals)) for n, d, vals in india_pack.SAMPLING_DIMENSIONS],
        never_sampled=list(india.PACK["never_sampled"]), known_gaps=_gaps(),
        links=[
            v.PackLink(label="Regions and their languages", path=f"/api/v1/regions?country_code={india.COUNTRY}"),
            v.PackLink(label="ASCI ad-code index", path="/api/v1/ad-codes"),
        ])
