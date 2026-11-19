"""Search pulse API: demo campaigns read the recorded snapshot (BigQuery is never built); live campaigns read the stored snapshot
and query a fake BigQuery only when none is newer than 24 hours. No test touches the network or Google credentials."""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select, update

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.integrations import google_trends as trends
from app.services import lens_search_pulse as service
from tests.api.omnicult_support import API, add_member, client_for, seeded  # noqa: F401
from tests.api.test_demo_aamod import aamod  # noqa: F401
from tests.api.test_lens import live_campaign
from tests.api.test_lens_t3 import aamod_campaign
from tests.api.test_pulse_t3 import bearer, scheduler  # noqa: F401
from tests.conftest import BOB
from tests.support_bigquery import FakeBigQuery, dataset_rows

PARTITION = date(2026, 11, 18)


@pytest.fixture(autouse=True)
def fresh_state() -> None:
    service._state.update(until=0.0, error=None)


class Nov19(date):
    @classmethod
    def today(cls) -> date:  # the app asks for the newest partition counting back from today
        return date(2026, 11, 19)


@pytest.fixture
def bq(monkeypatch: pytest.MonkeyPatch) -> FakeBigQuery:
    fake = FakeBigQuery({PARTITION: dataset_rows(PARTITION)})
    monkeypatch.setattr(trends, "date", Nov19)
    monkeypatch.setattr(trends, "make_client", lambda settings: fake)
    return fake


@pytest.fixture
def no_bigquery(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(settings: Any) -> Any:
        raise AssertionError("demo mode must never build a BigQuery client")

    monkeypatch.setattr(trends, "make_client", refuse)


def url(base: str, code: str, tail: str = "") -> str:
    return f"{base}/regions/{code}/search-pulse{tail}"


async def stored_rows() -> int:
    async with read_session() as s:
        return await s.scalar(select(func.count(m.LensSearchPulse.id))) or 0


# --- demo: the recording ------------------------------------------------------------------------------------------------------


async def test_demo_reads_the_recorded_snapshot_and_never_builds_a_client(aamod: httpx.AsyncClient, no_bigquery: None) -> None:
    project, base = await aamod_campaign(aamod)
    pulse = (await aamod.get(url(base, "IN-TN"))).json()
    assert pulse["mode"] == "demo" and pulse["supported"] and pulse["can_refresh"] is False
    assert pulse["week"] == "2026-11-15" and len(pulse["weeks"]) == 12 and pulse["refresh_date"] == "2026-11-18"
    assert len(pulse["top"]) == 23 and len(pulse["rising"]) == 25
    first = pulse["top"][0]
    assert first["rank"] == 3 and first["term"] == "denmark vs norway" and first["score"] == 100 and first["week"] == "2026-11-15"
    assert first["history"][-1]["week"] == "2026-11-15" and first["weeks_seen"] == sum(h["score"] is not None for h in first["history"])
    assert pulse["rising"][0]["percent_gain"] == 9950
    gold = next(t for t in pulse["top"] if t["term"] == "gold rate today")
    mh = (await aamod.get(url(base, "IN-MH"))).json()
    assert gold["score"] != next(t for t in mh["top"] if t["term"] == "gold rate today")["score"], "scores are the state's own"
    for code in ("IN-MH", "IN-KL", "IN-WB"):
        assert (await aamod.get(url(base, code))).json()["top"]
    assert await stored_rows() == 0, "demo stores nothing"


async def test_demo_states_outside_the_recording_and_states_google_lacks_say_so(aamod: httpx.AsyncClient, no_bigquery: None) -> None:
    _, base = await aamod_campaign(aamod)
    other = (await aamod.get(url(base, "IN-KA"))).json()  # the recording covers every state Google reports
    assert other["supported"] and other["top"] and other["gaps"] == []
    ladakh = (await aamod.get(url(base, "IN-LA"))).json()
    assert ladakh["supported"] is False and ladakh["top"] == [] and ladakh["can_refresh"] is False
    assert (await aamod.get(url(base, "IN-ZZ"))).status_code == 404
    assert (await aamod.post(url(base, "IN-TN", "/refresh"))).json()["top"], "a demo refresh answers with the recording"


async def test_a_viewer_cannot_refresh(aamod: httpx.AsyncClient, client_for: Any, no_bigquery: None) -> None:
    project, base = await aamod_campaign(aamod)
    await add_member(UUID(project["workspace_id"]), "bob", "viewer")
    bob = client_for(BOB)
    assert (await bob.get(url(base, "IN-TN"))).status_code == 200
    assert (await bob.post(url(base, "IN-TN", "/refresh"))).status_code == 403


# --- live: stored snapshot, query only when stale -------------------------------------------------------------------------------


async def test_live_read_queries_when_nothing_is_stored_then_serves_the_snapshot(client: httpx.AsyncClient, seeded: Any, bq: FakeBigQuery) -> None:
    _, base = await live_campaign(client)
    pulse = (await client.get(url(base, "IN-TN"))).json()
    assert pulse["mode"] == "live" and pulse["refresh_date"] == "2026-11-18" and pulse["week"] == "2026-11-15"
    assert [t["rank"] for t in pulse["top"]] == [3, 4, 5] and len(pulse["weeks"]) == 12 and pulse["can_refresh"] is True
    assert len(bq.runs) == 1
    async with read_session() as s:
        row = (await s.execute(select(m.LensSearchPulse).where(m.LensSearchPulse.region_code == "IN-TN"))).scalars().first()
        regions = set((await s.execute(select(m.LensSearchPulse.region_code).distinct())).scalars())
        audit = await s.scalar(select(func.count(m.AuditLog.id)).where(m.AuditLog.action == "lens.search_pulse_refresh"))
    assert row is not None and row.job_id == "job-1" and row.bytes_processed == 700_000_000 and row.refresh_date == PARTITION
    assert regions == {"IN-TN", "IN-MH", "IN-CG"}, "every state in one query; the dataset's IN-CT is Omnicult's IN-CG; IN-DD has no Omnicult state"
    assert await stored_rows() == 3 * 12 * 6 and audit == 1
    assert (await client.get(url(base, "IN-MH"))).json()["top"] and (await client.get(url(base, "IN-CG"))).json()["top"]
    assert len(bq.runs) == 1, "a fresh snapshot is served, not queried again"


async def test_a_stale_snapshot_is_served_when_nothing_newer_exists_and_is_replaced_when_there_is(
        client: httpx.AsyncClient, seeded: Any, bq: FakeBigQuery) -> None:
    _, base = await live_campaign(client)
    await client.get(url(base, "IN-TN"))
    async with session() as s, s.begin():
        await s.execute(update(m.LensSearchPulse).values(retrieved_at=utcnow() - timedelta(days=2)))
    service._state["until"] = 0.0
    assert (await client.get(url(base, "IN-TN"))).json()["top"]
    assert len(bq.runs) == 1, "the newest partition is the one stored: dry runs only, no bytes"

    newer = date(2026, 11, 19)
    bq.partitions[newer] = dataset_rows(newer)
    service._state["until"] = 0.0
    pulse = (await client.get(url(base, "IN-TN"))).json()
    assert len(bq.runs) == 2 and pulse["refresh_date"] == "2026-11-19"
    assert await stored_rows() == 3 * 12 * 6, "a refresh replaces a state's rows; partitions are never mixed"


async def test_owner_refresh_queries_once_and_a_repeat_costs_nothing(client: httpx.AsyncClient, seeded: Any, bq: FakeBigQuery) -> None:
    _, base = await live_campaign(client)
    first = await client.post(url(base, "IN-MH", "/refresh"))
    assert first.status_code == 200 and first.json()["top"] and len(bq.runs) == 1
    assert (await client.post(url(base, "IN-MH", "/refresh"))).status_code == 200
    assert len(bq.runs) == 1
    assert (await client.post(url(base, "IN-LA", "/refresh"))).status_code == 422
    assert (await client.get(url(base, "IN-LA"))).json()["supported"] is False
    assert len(bq.runs) == 1


async def test_a_viewer_cannot_refresh_live(client: httpx.AsyncClient, client_for: Any, seeded: Any, bq: FakeBigQuery) -> None:
    project, base = await live_campaign(client)
    await add_member(UUID(project["workspace_id"]), "bob", "viewer")
    bob = client_for(BOB)
    assert (await bob.post(url(base, "IN-TN", "/refresh"))).status_code == 403
    assert bq.runs == [] and bq.dry_runs == []


@pytest.mark.parametrize(("error", "status", "reason"), [
    (trends.TrendsQuota("cap"), 429, "quota"),
    (trends.TrendsPermission("no jobUser"), 502, "permission"),
    (trends.TrendsNotConfigured("no project"), 503, "not_configured"),
])
async def test_failures_are_typed_and_not_retried_at_once(
        client: httpx.AsyncClient, seeded: Any, bq: FakeBigQuery, error: Exception, status: int, reason: str) -> None:
    _, base = await live_campaign(client)
    bq.error = error
    failed = await client.get(url(base, "IN-TN"))
    assert failed.status_code == status, failed.text
    assert {"field": "reason", "message": reason} in failed.json()["error"]["details"]
    again = await client.get(url(base, "IN-TN"))
    assert again.status_code == status and len(bq.dry_runs) == 2, "the failure is remembered for ten minutes: no new BigQuery call"
    assert await stored_rows() == 0


async def test_a_failing_refresh_still_serves_what_is_stored(client: httpx.AsyncClient, seeded: Any, bq: FakeBigQuery) -> None:
    _, base = await live_campaign(client)
    await client.get(url(base, "IN-TN"))
    async with session() as s, s.begin():
        await s.execute(update(m.LensSearchPulse).values(retrieved_at=utcnow() - timedelta(days=3)))
    service._state["until"] = 0.0
    bq.partitions[date(2026, 11, 19)] = dataset_rows(date(2026, 11, 19))
    bq.error = trends.TrendsQuota("cap")
    stale = await client.get(url(base, "IN-TN"))
    assert stale.status_code == 200 and stale.json()["refresh_date"] == "2026-11-18"
    assert (await client.post(url(base, "IN-TN", "/refresh"))).status_code == 429, "an explicit refresh reports the failure"


# --- the daily scheduler call ---------------------------------------------------------------------------------------------------


async def test_the_scheduler_endpoint_refreshes_once_per_partition(
        client: httpx.AsyncClient, seeded: Any, bq: FakeBigQuery, scheduler: dict[str, Any]) -> None:
    refresh = f"{API}/internal/signals/refresh"
    assert (await client.post(refresh)).status_code == 401
    assert (await client.post(refresh, headers=bearer("forged"))).status_code == 401
    bq.error = trends.TrendsPermission("no jobUser")
    assert (await client.post(refresh, headers=bearer("good"))).status_code == 502, "a failed run answers 5xx so the scheduler retries"
    bq.error = None
    first = await client.post(refresh, headers=bearer("good"))
    assert first.status_code == 200, first.text
    body = first.json()["search_pulse"]
    assert body["skipped"] is False and body["refresh_date"] == "2026-11-18" and body["states"] == 3 and body["rows"] == 3 * 12 * 6
    assert body["bytes_processed"] == 700_000_000 and body["job_id"] == "job-1"
    second = (await client.post(refresh, headers=bearer("good"))).json()["search_pulse"]
    assert second["skipped"] is True and second["rows"] == 0 and len(bq.runs) == 1

    bq.partitions[date(2026, 11, 19)] = dataset_rows(date(2026, 11, 19))
    third = (await client.post(refresh, headers=bearer("good"))).json()["search_pulse"]
    assert third["skipped"] is False and third["refresh_date"] == "2026-11-19" and len(bq.runs) == 2


async def test_the_scheduler_endpoint_is_closed_without_scheduler_settings(client: httpx.AsyncClient, seeded: Any, bq: FakeBigQuery) -> None:
    assert (await client.post(f"{API}/internal/signals/refresh", headers=bearer("good"))).status_code == 403
    assert bq.dry_runs == []
