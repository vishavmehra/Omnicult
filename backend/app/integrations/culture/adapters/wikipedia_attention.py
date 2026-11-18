"""Wikipedia pageviews with the edition's total readership beside them (Trend Radar).

An article's views fall when the whole edition's readership falls, and on the regional editions it has fallen by a third or
more in a year. Read alone, nearly every article would look "falling" for a reason that has nothing to do with the topic. So
each edition's own monthly total (`/aggregate/{project}/all-access/user/monthly`, the same user-traffic definition) is read
once and kept on the edition as `baseline`; `app.analytics.lens_trends` then reads attention as a share of that readership.

A subclass, so the adapter the Market Lens build uses is unchanged. If the baseline cannot be read the edition is returned
without one and the radar says its direction is not adjusted; nothing is guessed.
"""

from datetime import date

from app.integrations.culture.adapters.wikipedia_pageviews import WikipediaPageviewsSource
from app.integrations.culture.base import CultureSourceError, SourceValidationError, TrendPoint, TrendSeries

AGGREGATE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/aggregate/{project}/all-access/user/monthly/{start}/{end}"


class WikipediaAttentionSource(WikipediaPageviewsSource):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._totals: dict[tuple[str, date, date], list[TrendPoint] | None] = {}  # per source: one read per edition and window

    async def trend_series(self, term: str, *, region_code: str, start: date, end: date) -> TrendSeries | None:
        series = await super().trend_series(term, region_code=region_code, start=start, end=end)
        if series is None or series.granularity != "monthly":
            return series
        for edition in series.editions:
            edition.baseline = await self._edition_totals(edition.project, series.start, series.end)
        return series

    async def _edition_totals(self, project: str, start: date, end: date) -> list[TrendPoint] | None:
        key = (project, start, end)
        if key not in self._totals:
            url = AGGREGATE.format(project=project, start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))
            try:
                data = await self.http.get_json(url, operation="trend_series")
                if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                    raise SourceValidationError(self.name, "trend_series", "aggregate response has no items list")
                points = []
                for item in data["items"]:
                    stamp = str(item["timestamp"])
                    points.append(TrendPoint(date=date(int(stamp[:4]), int(stamp[4:6]), 1), views=int(item["views"])))
                self._totals[key] = points or None
            except CultureSourceError:
                return None  # a failure is not kept: the next refresh asks again
        return self._totals[key]
