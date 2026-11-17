"""Idempotent loader for the reference tables. Run through `python -m scripts.seed_reference_data` (or call
`seed_reference_data(session)` in a test). Re-running updates rows in place and never duplicates them."""

from typing import NamedTuple
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.db.base import utcnow
from app.reference import india


class SeedCounts(NamedTuple):
    languages: int
    regions: int
    profiles: int
    moments: int
    packs: int


async def seed_reference_data(s: AsyncSession) -> SeedCounts:
    """Upsert India's languages, regions, language profiles, curated moments and the country pack."""
    now = utcnow()
    for row in india.LANGUAGES:
        language = await s.get(m.Language, row.code)
        if language is None:
            language = m.Language(code=row.code)
            s.add(language)
        language.name, language.native_name, language.script = row.name, row.native_name, row.script
        language.direction, language.code_standard, language.is_active = row.direction, row.standard, True
    await s.flush()

    regions: dict[str, m.Region] = {}
    for row in india.REGIONS:
        region = await s.get(m.Region, india.region_id(row.code))
        if region is None:
            region = m.Region(id=india.region_id(row.code), code=row.code, created_at=now)
            s.add(region)
        region.country_code, region.name, region.kind = india.COUNTRY, row.name, row.kind
        region.primary_language_code, region.primary_script = row.primary, india.SCRIPT_OF[row.primary]
        region.is_active = True
        regions[row.code] = region
    await s.flush()

    profiles = 0
    for row in india.REGIONS:
        for role, codes in (("primary", (row.primary,)), ("secondary", row.secondary)):
            for code in codes:
                profile = await s.scalar(select(m.RegionLanguageProfile).where(
                    m.RegionLanguageProfile.region_id == regions[row.code].id,
                    m.RegionLanguageProfile.language_code == code,
                ))
                if profile is None:
                    profile = m.RegionLanguageProfile(
                        id=uuid4(), region_id=regions[row.code].id, language_code=code, role=role, script="",
                    )
                    s.add(profile)
                profile.role, profile.script, profile.notes = role, india.SCRIPT_OF[code], india.LANGUAGE_NOTE
                profiles += 1
    moments = 0
    for row in india.MOMENTS:
        region_id = regions[row.region].id if row.region else None
        moment = await s.scalar(select(m.RegionalMoment).where(
            m.RegionalMoment.country_code == india.COUNTRY, m.RegionalMoment.slug == row.slug,
            m.RegionalMoment.region_id.is_(None) if region_id is None else m.RegionalMoment.region_id == region_id,
        ))
        if moment is None:
            moment = m.RegionalMoment(id=uuid4(), country_code=india.COUNTRY, slug=row.slug, region_id=region_id)
            s.add(moment)
        moment.name, moment.kind, moment.recurrence = row.name, row.kind, "annual"
        moment.typical_months, moment.calendar = list(row.months), row.calendar
        moment.notes = f"{row.notes} {india.MOMENT_NOTE}"
        moments += 1
    pack = await s.scalar(select(m.CountryPack).where(
        m.CountryPack.country_code == india.COUNTRY, m.CountryPack.version == india.PACK_VERSION))
    if pack is None:
        pack = m.CountryPack(id=uuid4(), country_code=india.COUNTRY, version=india.PACK_VERSION, created_at=now)
        s.add(pack)
    pack.pack, pack.source = india.PACK, india.PACK_SOURCE
    await s.flush()
    return SeedCounts(len(india.LANGUAGES), len(regions), profiles, moments, 1)
