"""Regions and their languages (reference data; readable by every signed-in user)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.db import models as m
from app.db.session import read_session
from app.schemas import regions as v
from app.services.common import paginate

ROLE_ORDER = {"primary": 0, "secondary": 1, "code_mixed": 2}


async def languages_by_region(s: AsyncSession, region_ids: list[UUID]) -> dict[UUID, list[v.RegionLanguage]]:
    result: dict[UUID, list[v.RegionLanguage]] = {rid: [] for rid in region_ids}
    if not region_ids:
        return result
    rows = await s.execute(
        select(m.RegionLanguageProfile, m.Language)
        .join(m.Language, m.Language.code == m.RegionLanguageProfile.language_code)
        .where(m.RegionLanguageProfile.region_id.in_(region_ids))
    )
    for profile, lang in sorted(rows.all(), key=lambda pair: (ROLE_ORDER[pair[0].role], pair[1].name)):
        result[profile.region_id].append(v.RegionLanguage(
            code=lang.code, name=lang.name, native_name=lang.native_name, script=profile.script,
            role=profile.role,  # type: ignore[arg-type]
        ))
    return result


def to_region(region: m.Region, languages: list[v.RegionLanguage]) -> v.Region:
    return v.Region(
        id=region.id, code=region.code, name=region.name, country_code=region.country_code,
        kind=region.kind,  # type: ignore[arg-type]
        primary_language=region.primary_language_code, primary_script=region.primary_script, languages=languages,
    )


async def list_regions(country_code: str, limit: int, offset: int) -> v.RegionPage:
    stmt = select(m.Region).where(m.Region.country_code == country_code, m.Region.is_active).order_by(m.Region.name)
    async with read_session() as s:
        rows, total = await paginate(s, stmt, limit, offset)
        languages = await languages_by_region(s, [r.id for r in rows])
    return v.RegionPage(items=[to_region(r, languages[r.id]) for r in rows], limit=limit, offset=offset, total=total)


async def get_region(code: str) -> v.Region:
    async with read_session() as s:
        region = await s.scalar(select(m.Region).where(m.Region.code == code, m.Region.is_active))
        if region is None:
            raise NotFound("Region was not found.")
        return to_region(region, (await languages_by_region(s, [region.id]))[region.id])
