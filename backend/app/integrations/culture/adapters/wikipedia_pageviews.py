"""Wikimedia pageviews by language edition: an attention signal, never a demand signal.

`term` is a Wikidata Q-id or an English Wikipedia article title. Wikidata sitelinks give the matching article in the
regional edition (ta, ml, bn, mr, hi) and English, so a Tamil reader's attention to Pongal is read from the Tamil page,
not from a translated guess. Wikipedia readership is not representative of a region's population.
Pageview data: CC0 (Wikimedia Foundation). Earliest data: 2015-07-01.
"""

import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.integrations.culture.base import (
    CultureSourceError,
    SourceBase,
    SourceDescriptor,
    SourceValidationError,
    TrendEdition,
    TrendPoint,
    TrendSeries,
    now_utc,
)
from app.integrations.culture.http import HttpFetcher
from app.integrations.culture.regions import region_for
from app.schemas.claims import ClaimDraft, ClaimScope, SourceRef

PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/all-access/user/{article}/{granularity}/{start}/{end}"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
EARLIEST = date(2015, 7, 1)
QID = re.compile(r"^Q[1-9]\d{0,12}$")
CAVEAT = (
    "Pageviews count reads of a Wikipedia article (all access methods, user traffic). They measure attention, "
    "not demand, purchase intent or market size, and Wikipedia readers are not a representative sample of a region."
)


class WikipediaPageviewsSource(SourceBase):
    name = "wikipedia_pageviews"
    descriptor = SourceDescriptor(
        name="wikipedia_pageviews", source_type="trend_series", supported_operations=frozenset({"trend_series"}),
        scope="Wikipedia language editions ta, ml, bn, mr, hi, en; daily or monthly; from 2015-07-01.",
        coverage_limitations=[
            "Attention, not demand: it counts article reads.",
            "Regional-language articles are often small, so counts can be low or noisy.",
            "An article is matched through Wikidata sitelinks; a term with no sitelink returns no series.",
            "Edition, not geography: the regional edition is read mostly, not only, from that region.",
        ],
        cache_policy={"trend_series": timedelta(hours=12)},
    )

    def __init__(self, *, user_agent: str, timeout: float = 15.0, client: httpx.AsyncClient | None = None,
                 max_retries: int = 2, backoff_seconds: float = 0.5, sleep: Any = None) -> None:
        extra = {"sleep": sleep} if sleep is not None else {}
        self.http = HttpFetcher("wikipedia_pageviews", user_agent=user_agent, timeout=timeout, client=client,
                                max_retries=max_retries, backoff_seconds=backoff_seconds, **extra)

    async def trend_series(self, term: str, *, region_code: str, start: date, end: date) -> TrendSeries | None:
        region = region_for(region_code)
        if region is None or end < start or end < EARLIEST:
            return None
        start = max(start, EARLIEST)
        titles = await self._sitelinks(term.strip(), region.wiki_editions)
        if not titles:
            return None
        granularity = "daily" if (end - start).days <= 92 else "monthly"
        editions: list[TrendEdition] = []
        first_url = ""
        for language in region.wiki_editions:
            title = titles.get(language)
            if title is None:
                continue
            project, article = f"{language}.wikipedia", title.replace(" ", "_")
            url = PAGEVIEWS.format(project=project, article=quote(article, safe=""), granularity=granularity,
                                   start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))
            first_url = first_url or url
            points = await self._points(url)
            editions.append(TrendEdition(language=language, project=project, article=title, points=points,
                                         total=sum(p.views for p in points)))
        if not editions:
            return None
        return TrendSeries(
            term=term, region_code=region_code, granularity=granularity, start=start, end=end, editions=editions,
            caveat=CAVEAT, source=SourceRef(
                source_type="wikipedia_pageviews", source_identifier=f"pageviews:{term}:{start}:{end}", url=first_url,
                title=f"Pageviews for {term}", publisher="Wikimedia Foundation", retrieved_at=now_utc(),
                independence_group="wikimedia"))

    async def _sitelinks(self, term: str, editions: tuple[str, ...]) -> dict[str, str]:
        wikis = [f"{e}wiki" for e in editions]
        params: dict[str, Any] = {"action": "wbgetentities", "props": "sitelinks", "sitefilter": "|".join(wikis),
                                  "format": "json"}
        params.update({"ids": term} if QID.match(term) else {"sites": "enwiki", "titles": term})
        data = await self.http.get_json(WIKIDATA_API, params, operation="trend_series")
        if not isinstance(data, dict) or not isinstance(data.get("entities"), dict):
            raise SourceValidationError(self.name, "trend_series", "wbgetentities returned no entities object")
        for entity in data["entities"].values():
            links = entity.get("sitelinks") if isinstance(entity, dict) else None
            if links:
                return {e: links[f"{e}wiki"]["title"] for e in editions if f"{e}wiki" in links}
        return {}

    async def _points(self, url: str) -> list[TrendPoint]:
        try:
            data = await self.http.get_json(url, operation="trend_series")
        except CultureSourceError as exc:
            if exc.status_code == 404:  # the API answers 404 when it holds no data for the page and range
                return []
            raise
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise SourceValidationError(self.name, "trend_series", "pageviews response has no items list")
        points: list[TrendPoint] = []
        for item in data["items"]:
            stamp = str(item["timestamp"])
            points.append(TrendPoint(date=date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])), views=int(item["views"])))
        return points


def series_to_claim(series: TrendSeries) -> ClaimDraft:
    """A calculated claim (totals and peaks computed from observed counts), labelled attention, not demand.
    A fixture series (source identifier starting "fixture:") is synthetic by construction and is typed that way."""
    editions = []
    for e in series.editions:
        peak = max(e.points, key=lambda p: p.views, default=None)
        editions.append({"language": e.language, "article": e.article, "total_views": e.total,
                         "peak_date": peak.date.isoformat() if peak else None, "peak_views": peak.views if peak else None})
    parts = [f"{e['language']}: {e['total_views']:,}" for e in editions]
    return ClaimDraft(
        subject=f"term:{series.term}", attribute="wikipedia_attention", category="trend",
        value={"term": series.term, "unit": "pageviews", "granularity": series.granularity,
               "start": series.start.isoformat(), "end": series.end.isoformat(), "editions": editions, "caveat": series.caveat},
        value_text=(f"Wikipedia pageviews for {series.term}, {series.start} to {series.end}: {'; '.join(parts)}. "
                    "This is attention to an article, not demand."),
        scope=ClaimScope(region_code=series.region_code, period=f"{series.start}/{series.end}"),
        kind="synthetic" if series.source.source_identifier.startswith("fixture:") else "calculated",
        sources=[series.source], retrieved_at=series.source.retrieved_at)
