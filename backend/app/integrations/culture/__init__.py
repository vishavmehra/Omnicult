"""Culture data layer: cited regional claims from open sources.

Public interface: build_culture_service, CultureService, RegionProfileBuilder and the neutral result models. Adapters
live in `adapters/`; every claim they return is a ClaimDraft with full SourceRef provenance.
"""

from typing import Literal

import httpx

from app.core.config import Settings
from app.integrations.culture.adapters.census import CensusSource
from app.integrations.culture.adapters.curated import CuratedReferenceSource
from app.integrations.culture.adapters.grounding import GroundedResearch, GroundingSource
from app.integrations.culture.adapters.holidays_calendar import HolidaysCalendarSource
from app.integrations.culture.adapters.wikidata import WikidataSource
from app.integrations.culture.adapters.wikipedia_pageviews import WikipediaPageviewsSource
from app.integrations.culture.base import (
    CallLogRecord,
    CultureSource,
    CultureSourceError,
    EntityCandidate,
    EntityResolution,
    SourceDescriptor,
    TrendSeries,
)
from app.integrations.culture.fixture import FixtureCultureSource
from app.integrations.culture.profile import RegionProfile, RegionProfileBuilder
from app.integrations.culture.service import CacheStore, CultureService, InMemoryCacheStore


def build_culture_service(settings: Settings, *, mode: Literal["live", "demo"] = "live", research: GroundedResearch | None = None,
                          cache: CacheStore | None = None, client: httpx.AsyncClient | None = None) -> CultureService:
    """demo -> the deterministic fixture source only (no network). live -> every adapter; the grounding adapter is
    skipped (reported as not configured) unless a grounded_research capability is passed in."""
    if mode == "demo":
        return CultureService([FixtureCultureSource()], mode="fixture")
    http = dict(user_agent=settings.wikimedia_user_agent, timeout=settings.culture_http_timeout_seconds, client=client)
    sources: list[CultureSource] = [
        CuratedReferenceSource(), CensusSource(), HolidaysCalendarSource(), WikidataSource(**http),
        WikipediaPageviewsSource(**http), GroundingSource(research)]
    return CultureService(sources, cache=cache if cache is not None else InMemoryCacheStore(), mode="live")


__all__ = [
    "CacheStore", "CallLogRecord", "CultureService", "CultureSource", "CultureSourceError", "EntityCandidate",
    "EntityResolution", "FixtureCultureSource", "InMemoryCacheStore", "RegionProfile", "RegionProfileBuilder",
    "SourceDescriptor", "TrendSeries", "build_culture_service",
]
