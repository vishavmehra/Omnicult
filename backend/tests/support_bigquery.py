"""A fake BigQuery client for the search pulse tests: no test touches the network or Google credentials."""

from datetime import date, timedelta
from typing import Any

WEEKS = 14  # the fake dataset holds 14 Sundays; the app keeps the newest 12


def dataset_rows(refresh_date: date, *, regions: tuple[str, ...] = ("IN-TN", "IN-MH", "IN-CT", "IN-DD"), terms: int = 3) -> list[dict[str, Any]]:
    """Rows as the UNION ALL query returns them: the same terms for every state and week, scores per state and week."""
    latest = refresh_date - timedelta(days=(refresh_date.weekday() + 1) % 7)  # the Sunday on or before
    rows = []
    for ri, region in enumerate(regions):
        for w in range(WEEKS):
            week = latest - timedelta(days=7 * (WEEKS - 1 - w))
            for i in range(terms):
                score = None if (w + i) % 3 == 0 else min(100, 10 * (ri + 1) + w + i)
                rows.append({"kind": "top", "week": week, "region_code": region, "term": f"term {i}", "rank": i + 3, "score": score, "percent_gain": None})
                rows.append({"kind": "rising", "week": week, "region_code": region, "term": f"rise {i}", "rank": i + 1, "score": score, "percent_gain": 1000 * (terms - i)})
    return rows


class FakeJob:
    def __init__(self, rows: list[dict[str, Any]], processed: int, job_id: str) -> None:
        self._rows, self.total_bytes_processed, self.total_bytes_billed, self.job_id = rows, processed, processed, job_id

    def result(self, timeout: float | None = None) -> list[dict[str, Any]]:
        return self._rows


class FakeBigQuery:
    """`partitions` maps refresh_date -> rows. A missing partition estimates 0 bytes, like the real one."""

    def __init__(self, partitions: dict[date, list[dict[str, Any]]], *, bytes_per_partition: int = 700_000_000, error: Exception | None = None) -> None:
        self.partitions, self.bytes, self.error = partitions, bytes_per_partition, error
        self.dry_runs: list[date] = []
        self.runs: list[dict[str, Any]] = []

    def query(self, sql: str, job_config: Any) -> FakeJob:
        params = {p.name: (p.values if hasattr(p, "values") else p.value) for p in job_config.query_parameters}
        day = params["refresh_date"]
        assert params["country"] == "IN" and "refresh_date = @refresh_date" in sql and "@regions" in sql  # always filtered
        if job_config.dry_run:
            self.dry_runs.append(day)
            return FakeJob([], self.bytes if day in self.partitions else 0, "dry")
        if self.error:
            raise self.error
        assert job_config.maximum_bytes_billed, "every real query carries the bytes cap"
        wanted = set(params["regions"])
        rows = [r for r in self.partitions[day] if r["region_code"] in wanted]
        self.runs.append({"day": day, "cap": job_config.maximum_bytes_billed, "since": params["since"]})
        return FakeJob(rows, self.bytes, f"job-{len(self.runs)}")
