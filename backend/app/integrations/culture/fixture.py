"""Deterministic fixture source for tests and demo mode. Nothing here is a live result.

It makes no network call. Entity candidates come from `data/fixture_entities.json` (real Wikidata search results
recorded on the date stored in the file). Festivals, foods, moments and language shares come from the same offline
datasets the live adapters read (curated, census, python-holidays), with every source relabelled: identifiers start
with "fixture:", and `retrieved_at` is a fixed instant, so two runs give identical output.
Trend series are synthetic by construction (a seeded formula, not pageviews); the source identifier carries that.
"""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.integrations.culture.adapters.census import CensusSource
from app.integrations.culture.adapters.curated import CuratedReferenceSource
from app.integrations.culture.adapters.holidays_calendar import HolidaysCalendarSource
from app.integrations.culture.base import (
    ALL_OPERATIONS,
    EntityCandidate,
    EntityResolution,
    SourceBase,
    SourceDescriptor,
    TrendEdition,
    TrendPoint,
    TrendSeries,
    decide_resolution,
)
from app.integrations.culture.regions import region_for
from app.schemas.claims import ClaimDraft, SourceRef

FIXTURE_TIME = datetime(2026, 11, 17, tzinfo=UTC)
ENTITIES_FILE = Path(__file__).resolve().parent / "data" / "fixture_entities.json"
SYNTHETIC_CAVEAT = "Pageviews measure attention to an article, not demand, purchase intent or market size."


@lru_cache(maxsize=1)
def _entities() -> dict[str, list[dict]]:
    return json.loads(ENTITIES_FILE.read_text(encoding="utf-8"))["queries"]


def relabel(claim: ClaimDraft) -> ClaimDraft:
    """Mark every source of a claim as demo fixture data and pin its timestamps."""
    sources = [s.model_copy(update={
        "source_identifier": f"fixture:{s.source_identifier}", "title": s.title or s.source_identifier,
        "retrieved_at": FIXTURE_TIME}) for s in claim.sources]
    return claim.model_copy(update={"sources": sources, "retrieved_at": FIXTURE_TIME})


class FixtureCultureSource(SourceBase):
    name = "fixture"
    mode: Literal["live", "fixture"] = "fixture"
    descriptor = SourceDescriptor(
        name="fixture", source_type="fixture", supported_operations=ALL_OPERATIONS,
        scope="The four prepared states, a fixed set of entity searches and daily trend series.",
        coverage_limitations=["Entity resolution covers a fixed set of queries."],
        cache_policy={},  # fixtures are never cached
    )

    def __init__(self) -> None:
        self._curated, self._census, self._holidays = CuratedReferenceSource(), CensusSource(), HolidaysCalendarSource()

    async def resolve_entity(self, query: str, *, language: str | None = None,
                             region_code: str | None = None) -> EntityResolution:
        rows = _entities().get(" ".join(query.casefold().split()), [])
        candidates = [EntityCandidate(**{**row, "source": self.name}) for row in rows]
        return decide_resolution(query, candidates, language=language, region_code=region_code, sources=[self.name],
                                 retrieved_at=FIXTURE_TIME)

    async def related_signals(self, entity_id: str, *, region_code: str, limit: int = 10) -> list[ClaimDraft]:
        return [relabel(c) for c in await self._curated.related_signals(entity_id, region_code=region_code, limit=limit)]

    async def audience_facts(self, region_code: str) -> list[ClaimDraft]:
        return [relabel(c) for c in await self._census.audience_facts(region_code)]

    async def moments(self, region_code: str, *, year: int) -> list[ClaimDraft]:
        claims = await self._curated.moments(region_code, year=year) + await self._holidays.moments(region_code, year=year)
        return [relabel(c) for c in claims]

    async def trend_series(self, term: str, *, region_code: str, start: date, end: date) -> TrendSeries | None:
        region = region_for(region_code)
        if region is None or end < start:
            return None
        editions = []
        for language in region.wiki_editions:
            points = [TrendPoint(date=start + timedelta(days=i), views=_synthetic_views(term, language, start + timedelta(days=i)))
                      for i in range((end - start).days + 1)]
            editions.append(TrendEdition(language=language, project=f"{language}.wikipedia", article=term, points=points,
                                         total=sum(p.views for p in points)))
        source = SourceRef(
            source_type="curated_reference", source_identifier=f"fixture:trend:{term}:{start}:{end}",
            title="Wikipedia pageviews series", publisher="Wikimedia Foundation", retrieved_at=FIXTURE_TIME,
            independence_group="fixture")
        return TrendSeries(term=term, region_code=region_code, granularity="daily", start=start, end=end, editions=editions,
                           caveat=SYNTHETIC_CAVEAT, source=source)


def _synthetic_views(term: str, language: str, day: date) -> int:
    digest = hashlib.sha256(f"{term}|{language}|{day.isoformat()}".encode()).digest()
    return 20 + digest[0] % 80
