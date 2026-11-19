"""Recorded public data behind the Aamod demo of Trend Radar and Category Shelf. Nothing here is a live result.

`lens_t3/recorded.json` was written by `scripts/record_lens_t3_fixtures.py` on the date it records: monthly Wikipedia pageviews
(regional edition and English, with each edition's own monthly total) for the festival articles the demo claims cite, the category topics and the brands and products
Wikidata links to the demo states, plus the Wikidata shelf discovery itself. These are retrieved numbers, not a formula. Demo mode
reads them without a network call, labels every source `fixture:`, and a term that was not recorded has no
series, so the radar shows it as not read instead of drawing one.
"""

import json
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from app.integrations.culture.base import (
    SourceBase,
    SourceDescriptor,
    TrendEdition,
    TrendPoint,
    TrendSeries,
)
from app.integrations.culture.regions import region_for
from app.integrations.culture.shelf import CategoryPack, ShelfDiscovery
from app.schemas.claims import SourceRef

RECORDED_FILE = Path(__file__).resolve().parent / "lens_t3" / "recorded.json"


@lru_cache(maxsize=1)
def recorded() -> dict[str, Any]:
    return json.loads(RECORDED_FILE.read_text(encoding="utf-8"))


def recorded_at() -> datetime:
    return datetime.combine(date.fromisoformat(recorded()["recorded_on"]), datetime.min.time(), tzinfo=UTC)


def recorded_window() -> tuple[date, date]:
    window = recorded()["window"]
    return date.fromisoformat(window["start"]), date.fromisoformat(window["end"])


def recorded_label() -> str:
    return f"recorded {recorded_at():%d %b %Y}".replace(" 0", " ")


class RecordedPageviewsSource(SourceBase):
    """Answers `trend_series` from the recording; a (term, state) pair that was not recorded has no series."""

    name = "fixture"
    mode: Literal["live", "fixture"] = "fixture"
    descriptor = SourceDescriptor(
        name="fixture", source_type="fixture", supported_operations=frozenset({"trend_series"}),
        scope="Wikipedia pageviews for the covered states.",
        coverage_limitations=[],
        cache_policy={})

    async def trend_series(self, term: str, *, region_code: str, start: date, end: date) -> TrendSeries | None:
        found = recorded()["series"].get(f"{term}|{region_code}")
        region = region_for(region_code)
        if found is None or region is None:
            return None
        editions = []
        for e in found["editions"]:
            points = [TrendPoint(date=date.fromisoformat(f"{month}-01"), views=int(views)) for month, views in e["points"]]
            totals = recorded().get("baselines", {}).get(e["project"])
            baseline = [TrendPoint(date=date.fromisoformat(f"{month}-01"), views=int(views)) for month, views in totals] if totals else None
            editions.append(TrendEdition(language=e["language"], project=e["project"], article=e["article"], points=points,
                                         total=sum(p.views for p in points), baseline=baseline))
        first, last = recorded_window()
        source = SourceRef(
            source_type="wikipedia_pageviews", source_identifier=f"fixture:pageviews:{term}:{region_code}", url=found["url"],
            title=f"Wikipedia pageviews for {term}", publisher="Wikimedia Foundation",
            retrieved_at=recorded_at(), independence_group="wikimedia")
        return TrendSeries(
            term=term, region_code=region_code, granularity="monthly", start=first, end=last, editions=editions,
            caveat="Pageviews: attention to an article, not search volume and not demand.", source=source)


class RecordedShelfSource:
    """The recorded Wikidata discovery for the demo's category; every other category is not recorded."""

    async def discover(self, pack: CategoryPack) -> ShelfDiscovery:
        found = recorded()["shelf"].get(pack.key)
        if found is None:
            return ShelfDiscovery(
                pack_key=pack.key, entities=[], excluded=[], calls=[], retrieved_at=recorded_at(),
                gaps=[f"Only the {_recorded_pack_labels()} category is available here; '{pack.label}' is not."])
        return ShelfDiscovery.model_validate({**found, "calls": [], "retrieved_at": recorded_at()})


def _recorded_pack_labels() -> str:
    from app.integrations.culture.shelf import pack_by_key

    return " and ".join(p.label for key in recorded()["shelf"] if (p := pack_by_key(key)) is not None)
