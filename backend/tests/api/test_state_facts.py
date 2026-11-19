"""State facts API: demo campaigns read the recorded snapshot (no network); live campaigns read stored snapshots that are pulled from
data.gov.in when missing or past their cadence. respx stands in for data.gov.in: no test touches the network."""

import copy
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.scheduler_auth import get_verifier
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.integrations.culture.adapters.datagov import RESOURCES, DataGovClient
from app.integrations.culture.http import HttpFetcher
from app.services import state_facts
from app.services.state_facts import recorded
from tests.api.omnicult_support import API, add_member, client_for, seeded  # noqa: F401
from tests.api.test_demo_aamod import no_network
from tests.api.test_lens import demo_campaign, live_campaign
from tests.conftest import BOB

KEY = "api-test-key-9999"
HOST = "https://api.data.gov.in/resource/"
ACCOUNT, AUDIENCE = "scheduler@omnicult-test.iam.gserviceaccount.com", "https://api.omnicult.test"


@pytest.fixture(autouse=True)
def fast_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    async def nap(_: float) -> None:
        return None

    monkeypatch.setattr(state_facts, "DataGovClient", lambda key: DataGovClient(
        key, http=HttpFetcher("data_gov_in", user_agent="t", max_retries=1, backoff_seconds=0, sleep=nap)))
    state_facts._BACKOFF.clear()
    yield
    state_facts._BACKOFF.clear()


@pytest.fixture
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_GOV_IN_API_KEY", KEY)
    get_settings.cache_clear()


class Upstream:
    """data.gov.in as respx serves it: the recorded rows, an `updated_date` per resource, and an optional failure status."""

    def __init__(self, mock: respx.MockRouter) -> None:
        self.data = {saved["resource_id"]: {"updated": saved["updated_date"].replace("+00:00", "Z"), "records": copy.deepcopy(saved["records"])}
                     for saved in recorded()["resources"].values()}
        self.calls: list[tuple[str, int]] = []  # (resource id, limit)
        self.fail: int | None = None
        self.broken: set[str] = set()  # resource ids that answer 500
        self.keys: set[str] = set()
        mock.get(url__startswith=HOST).mock(side_effect=self.answer)

    def answer(self, request: httpx.Request) -> httpx.Response:
        rid, params = request.url.path.rsplit("/", 1)[1], request.url.params
        self.calls.append((rid, int(params["limit"])))
        self.keys.add(params["api-key"])
        if self.fail or rid in self.broken:
            return httpx.Response(self.fail or 500, json={"message": "no"})
        res = self.data[rid]
        start = int(params["offset"])
        page = res["records"][start:start + int(params["limit"])]
        return httpx.Response(200, json={"status": "ok", "total": len(res["records"]), "count": len(page), "updated_date": res["updated"], "records": page})

    def probes(self) -> int:
        return sum(1 for _, limit in self.calls if limit == 1)


@pytest.fixture
def upstream() -> Iterator[Upstream]:
    with respx.mock(assert_all_called=False) as mock:
        yield Upstream(mock)


def fact(body: dict[str, Any], key: str) -> dict[str, Any]:
    return next(f for g in body["groups"] for f in g["facts"] if f["key"] == key)


async def stored_rows() -> int:
    async with read_session() as s:
        return int(await s.scalar(select(func.count(m.StateFactSnapshot.id))) or 0)


# --- demo -------------------------------------------------------------------------------------------------------------------


async def test_a_demo_campaign_reads_the_recorded_snapshot_with_no_network_call_and_no_stored_rows(client: httpx.AsyncClient, seeded: Any) -> None:
    _, base = await demo_campaign(client)
    with no_network():
        body = (await client.get(f"{base}/regions/IN-TN/state-facts")).json()
        refreshed = await client.post(f"{base}/regions/IN-TN/state-facts/refresh")
        kerala = (await client.get(f"{base}/regions/IN-KL/state-facts")).json()
        maharashtra = (await client.get(f"{base}/regions/IN-MH/state-facts")).json()
        andaman = (await client.get(f"{base}/regions/IN-AN/state-facts")).json()
    assert body["mode"] == "demo" and body["region_name"] == "Tamil Nadu" and body["can_refresh"] is False
    assert [g["key"] for g in body["groups"]] == ["connectivity", "economy", "homes", "people", "visitors"]
    assert fact(body, "home_no_internet")["period"] == "2025" and fact(body, "tourist_visits_domestic")["unit"] == "million"
    internet = fact(body, "women_internet")
    assert (internet["value"], internet["national"], internet["period"]) == (46.9, 33.3, "2019-21")
    literacy = fact(body, "literacy")
    assert literacy["value"] == 80.09 and literacy["national"] == 72.98 and [(p["period"], p["value"]) for p in literacy["series"]] == [("2001", 73.45), ("2011", 80.09)]
    nsdp = fact(body, "nsdp")
    assert nsdp["value"] == 275583 and nsdp["period"] == "2022-23" and nsdp["national"] is None and len(nsdp["series"]) == 4
    spend = fact(body, "mpce")
    assert spend["value"] is None and [(p["label"], p["value"], p["period"]) for p in spend["parts"]] == [("Rural", 5701, "2023-24"), ("Urban", 8165, "2023-24")]
    assert all(p["national"] is not None for p in spend["parts"])
    assert [p["label"] for p in fact(body, "internet_per100")["parts"]] == ["Rural", "Urban"]
    assert refreshed.status_code == 200 and refreshed.json()["groups"] == body["groups"]
    for state in (kerala, maharashtra):  # every demo state is recorded in full, including the table that spells it "Maharastra"
        assert {f["key"] for g in state["groups"] for f in g["facts"]} == {f["key"] for g in body["groups"] for f in g["facts"]}
    assert andaman["groups"] and andaman["fetched_at"] is not None  # the recording holds every state
    assert await stored_rows() == 0
    assert (await client.get(f"{base}/regions/IN-XX/state-facts")).status_code == 404


# --- live: pull when missing, then serve the snapshot -------------------------------------------------------------------------


async def test_a_live_read_pulls_once_serves_the_snapshot_and_a_refresh_downloads_only_what_changed(
    client: httpx.AsyncClient, client_for: Callable[..., httpx.AsyncClient], seeded: Any, with_key: None, upstream: Upstream,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, base = await live_campaign(client)
    first = await client.get(f"{base}/regions/IN-TN/state-facts")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["mode"] == "live" and body["can_refresh"] is True and body["fetched_at"] is not None
    assert fact(body, "literacy")["value"] == 80.09 and fact(body, "women_internet")["national"] == 33.3
    assert len(upstream.calls) == len(RESOURCES) and upstream.probes() == 0 and upstream.keys == {KEY}
    assert KEY not in first.text
    rows = await stored_rows()
    assert rows > 50

    assert (await client.get(f"{base}/regions/IN-KL/state-facts")).status_code == 200
    assert len(upstream.calls) == len(RESOURCES)  # served from the snapshot: no second download

    assert (await client.post(f"{base}/regions/IN-TN/state-facts/refresh")).status_code == 429  # checked a moment ago
    monkeypatch.setattr(state_facts, "MANUAL_REFRESH_GAP", timedelta(0))
    again = await client.post(f"{base}/regions/IN-TN/state-facts/refresh")
    assert again.status_code == 200 and upstream.probes() == len(RESOURCES) and len(upstream.calls) == 2 * len(RESOURCES)  # one probe each, no download

    literacy = next(r for r in RESOURCES if r.key == "literacy")
    upstream.data[literacy.resource_id]["updated"] = "2026-11-01T00:00:00Z"
    tamil = next(rec for rec in upstream.data[literacy.resource_id]["records"] if rec["india_states_uts"] == "Tamil Nadu")
    tamil["census_2011"] = 81.5
    changed = (await client.post(f"{base}/regions/IN-TN/state-facts/refresh")).json()
    assert fact(changed, "literacy")["value"] == 81.5
    assert upstream.probes() == 2 * len(RESOURCES) and len(upstream.calls) == 3 * len(RESOURCES) + 1  # all probed, only literacy downloaded
    assert await stored_rows() == rows  # upserted in place

    await add_member(UUID(project["workspace_id"]), "bob", "viewer")
    bob = client_for(BOB)
    viewer = (await bob.get(f"{base}/regions/IN-TN/state-facts")).json()
    assert viewer["can_refresh"] is False and fact(viewer, "literacy")["value"] == 81.5
    assert (await bob.post(f"{base}/regions/IN-TN/state-facts/refresh")).status_code == 403


async def test_a_stale_copy_is_pulled_again_but_still_served_when_the_service_is_down(
    client: httpx.AsyncClient, seeded: Any, with_key: None, upstream: Upstream,
) -> None:
    _, base = await live_campaign(client)
    assert (await client.get(f"{base}/regions/IN-WB/state-facts")).status_code == 200
    calls = len(upstream.calls)
    async with session() as s, s.begin():  # every copy is now older than every cadence
        await s.execute(update(m.StateFactSnapshot).values(retrieved_at=utcnow() - timedelta(days=60)))
    upstream.fail = 503
    down = await client.get(f"{base}/regions/IN-WB/state-facts")
    assert down.status_code == 200 and fact(down.json(), "literacy")["value"] > 0  # the old snapshot, not an error
    assert len(upstream.calls) > calls
    after = len(upstream.calls)
    assert (await client.get(f"{base}/regions/IN-WB/state-facts")).status_code == 200
    assert len(upstream.calls) == after  # a failed pull is not retried on every read


# --- live: typed errors -------------------------------------------------------------------------------------------------------


async def test_without_a_key_or_a_snapshot_the_read_says_so_and_stores_nothing(client: httpx.AsyncClient, seeded: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATA_GOV_IN_API_KEY", raising=False)
    get_settings.cache_clear()
    _, base = await live_campaign(client)
    response = await client.get(f"{base}/regions/IN-TN/state-facts")
    assert response.status_code == 503 and response.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"
    assert "data.gov" not in response.text.lower() and await stored_rows() == 0


@pytest.mark.parametrize(("upstream_status", "status", "code"), [
    (401, 503, "PROVIDER_NOT_CONFIGURED"), (403, 503, "PROVIDER_NOT_CONFIGURED"), (429, 429, "RATE_LIMITED"), (500, 502, "PROVIDER_ERROR"),
])
async def test_upstream_failures_become_typed_errors_and_never_echo_the_key(
    client: httpx.AsyncClient, seeded: Any, with_key: None, upstream: Upstream, upstream_status: int, status: int, code: str,
) -> None:
    upstream.fail = upstream_status
    _, base = await live_campaign(client)
    response = await client.get(f"{base}/regions/IN-TN/state-facts")
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert KEY not in response.text and await stored_rows() == 0


# --- Cloud Scheduler ----------------------------------------------------------------------------------------------------------

URL = f"{API}/internal/signals/refresh"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def scheduler(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEDULER_SERVICE_ACCOUNT", ACCOUNT)
    monkeypatch.setenv("SCHEDULER_AUDIENCE", AUDIENCE)
    get_settings.cache_clear()
    good = {"email": ACCOUNT, "email_verified": True, "aud": AUDIENCE}

    def fake(token: str, audience: str) -> dict[str, Any]:
        if token != "good":
            raise ValueError("invalid")
        return good

    app.dependency_overrides[get_verifier] = lambda: fake


async def test_the_scheduler_refresh_is_guarded_and_idempotent(client: httpx.AsyncClient, scheduler: None, with_key: None, upstream: Upstream) -> None:
    assert (await client.post(URL)).status_code == 401
    assert (await client.post(URL, headers=bearer("bad"))).status_code == 401
    assert upstream.calls == []

    first = await client.post(URL, headers=bearer("good"))
    assert first.status_code == 200, first.text
    facts = first.json()["state_facts"]
    assert first.json()["search_pulse"] is None, "no BigQuery project here: Search pulse is skipped"
    assert (facts["updated"], facts["unchanged"], facts["failed"]) == (len(RESOURCES), 0, 0)
    rows = await stored_rows()
    second = (await client.post(URL, headers=bearer("good"))).json()["state_facts"]
    assert (second["updated"], second["unchanged"], second["failed"]) == (0, len(RESOURCES), 0)  # a probe each, no download
    assert upstream.probes() == len(RESOURCES) and await stored_rows() == rows


async def test_a_failed_resource_makes_the_scheduler_call_500_so_it_retries_while_the_others_still_run(
    client: httpx.AsyncClient, scheduler: None, with_key: None, upstream: Upstream,
) -> None:
    upstream.broken.add(RESOURCES[1].resource_id)
    response = await client.post(URL, headers=bearer("good"))
    body = response.json()["state_facts"]
    assert response.status_code == 500 and body["failed"] == 1 and body["updated"] == len(RESOURCES) - 1
    assert next(r for r in body["resources"] if r["resource"] == RESOURCES[1].key)["error_kind"] == "http"
    assert KEY not in response.text


async def test_the_scheduler_refresh_is_refused_when_scheduling_is_not_configured(client: httpx.AsyncClient, with_key: None) -> None:
    assert (await client.post(URL, headers=bearer("good"))).status_code == 403


async def test_the_all_states_recording_loads_every_state_once(client: httpx.AsyncClient) -> None:
    async with session() as s, s.begin():
        first = await state_facts.load_recording(s)
    assert (first.updated, first.failed) == (len(RESOURCES), 0)
    async with read_session() as s:
        regions = set((await s.execute(select(m.StateFactSnapshot.region_code))).scalars())
    assert len(regions) >= 36 and {"IN-TN", "IN-UP", "IN-LA"} <= regions
    async with session() as s, s.begin():
        again = await state_facts.load_recording(s)
    assert (again.updated, again.unchanged) == (0, len(RESOURCES))  # the same recording is not stored twice
