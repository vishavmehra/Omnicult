"""Search pulse: region mapping, shaping rows, one state's view, and the BigQuery client against a fake. No network."""

from datetime import date

import pytest
from google.api_core import exceptions as gax

from app.analytics import search_pulse as logic
from app.core.config import Settings
from app.integrations import google_trends as trends
from tests.support_bigquery import FakeBigQuery, dataset_rows

TODAY = date(2026, 11, 19)
SETTINGS = Settings(bigquery_project="p", search_pulse_weeks=12)  # type: ignore[call-arg]


def test_omnicult_codes_map_to_the_datasets_and_back() -> None:
    assert trends.dataset_region("IN-TN") == "IN-TN"
    assert [trends.dataset_region(c) for c in ("IN-CG", "IN-OD", "IN-TS")] == ["IN-CT", "IN-OR", "IN-TG"]
    assert trends.dataset_region("IN-LA") is None and trends.dataset_region("IN-DH") is None
    assert trends.omnicult_region("IN-CT") == "IN-CG" and trends.omnicult_region("IN-DD") is None and trends.omnicult_region("IN-XX") is None


def test_shape_keeps_the_newest_weeks_and_drops_states_the_app_does_not_have() -> None:
    rows = logic.shape(dataset_rows(date(2026, 11, 18)), weeks=12, code_for=trends.omnicult_region)
    assert {r["region_code"] for r in rows} == {"IN-TN", "IN-MH", "IN-CG"}  # IN-DD dropped, IN-CT renamed
    assert len({r["week"] for r in rows}) == 12  # 14 in the dataset
    assert len(rows) == 3 * 12 * 6
    assert all(r["percent_gain"] is None for r in rows if r["kind"] == "top")


def test_view_lists_the_latest_week_by_rank_with_each_terms_history() -> None:
    shaped = logic.shape(dataset_rows(date(2026, 11, 18)), weeks=12, code_for=trends.omnicult_region)
    shown = logic.view([r for r in shaped if r["region_code"] == "IN-TN"])
    assert shown["week"] == date(2026, 11, 15) and len(shown["weeks"]) == 12
    assert [t["rank"] for t in shown["top"]] == [3, 4, 5] and [t["rank"] for t in shown["rising"]] == [1, 2, 3]
    first = shown["top"][0]
    assert len(first["history"]) == 12 and first["history"][-1]["week"] == shown["week"]
    assert first["weeks_seen"] == sum(h["score"] is not None for h in first["history"]) and 0 < first["weeks_seen"] < 12  # nulls stay null
    assert shown["rising"][0]["percent_gain"] == 3000
    assert logic.view([]) == {"weeks": [], "week": None, "top": [], "rising": []}


def test_fetch_finds_the_newest_partition_with_free_dry_runs_and_runs_one_capped_query() -> None:
    bq = FakeBigQuery({date(2026, 11, 18): dataset_rows(date(2026, 11, 18))})
    fetched = trends.fetch_india(SETTINGS, client=bq, today=TODAY)
    assert fetched is not None and fetched.refresh_date == date(2026, 11, 18) and fetched.job_id == "job-1"
    assert bq.dry_runs == [date(2026, 11, 19), date(2026, 11, 18)]  # today's partition does not exist yet: 0 bytes
    assert len(bq.runs) == 1 and bq.runs[0]["cap"] == 2_000_000_000 and bq.runs[0]["since"] == date(2026, 8, 26)
    assert fetched.bytes_processed == 700_000_000
    assert {r["region_code"] for r in fetched.rows} == {"IN-TN", "IN-MH", "IN-CT", "IN-DD"}  # the fake filters by the region parameter


def test_fetch_skips_the_query_when_the_partition_is_already_stored() -> None:
    bq = FakeBigQuery({date(2026, 11, 18): dataset_rows(date(2026, 11, 18))})
    assert trends.fetch_india(SETTINGS, client=bq, today=TODAY, skip_refresh_date=date(2026, 11, 18)) is None
    assert bq.runs == []


def test_fetch_refuses_an_estimate_over_the_cap_and_a_dataset_with_no_recent_partition() -> None:
    bq = FakeBigQuery({date(2026, 11, 18): []}, bytes_per_partition=3_000_000_000)
    with pytest.raises(trends.TrendsQuota):
        trends.fetch_india(SETTINGS, client=bq, today=TODAY)
    assert bq.runs == []
    with pytest.raises(trends.TrendsError, match="no refresh_date partition"):
        trends.fetch_india(SETTINGS, client=FakeBigQuery({}), today=TODAY)


@pytest.mark.parametrize(("error", "kind"), [
    (gax.Forbidden("Access Denied: User does not have bigquery.jobs.create permission"), trends.TrendsPermission),
    (gax.Forbidden("quota", errors=[{"reason": "quotaExceeded"}]), trends.TrendsQuota),
    (gax.TooManyRequests("slow down"), trends.TrendsQuota),
    (gax.BadRequest("Query exceeded limit for bytes billed: 2000000000. 3000000000 or higher required."), trends.TrendsQuota),
    (gax.InternalServerError("boom"), trends.TrendsError),
])
def test_bigquery_failures_become_typed_errors(error: Exception, kind: type[trends.TrendsError]) -> None:
    bq = FakeBigQuery({date(2026, 11, 18): dataset_rows(date(2026, 11, 18))}, error=error)
    with pytest.raises(trends.TrendsError) as caught:
        trends.fetch_india(SETTINGS, client=bq, today=TODAY)
    assert type(caught.value) is kind


def test_no_project_is_not_configured() -> None:
    with pytest.raises(trends.TrendsNotConfigured):
        trends.make_client(Settings(bigquery_project=None, google_cloud_project=None))  # type: ignore[call-arg]
