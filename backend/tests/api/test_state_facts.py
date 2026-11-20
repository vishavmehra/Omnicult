"""State facts API: demo campaigns read the recorded snapshots (no network); live campaigns read stored snapshots that are pulled from
data.gov.in and Google Data Commons when missing or past their cadence. respx stands in for both: no test touches the network."""

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
from app.integrations.culture.adapters import datacommons as dc
from app.integrations.culture.adapters.datacommons import DataCommonsClient
from app.integrations.culture.adapters.datagov import RESOURCES, DataGovClient
from app.integrations.culture.http import HttpFetcher
from app.services import state_facts
from app.services.state_facts import recorded, recorded_datacommons
from tests.api.omnicult_support import API, add_member, client_for, seeded  # noqa: F401
from tests.api.test_demo_aamod import no_network
from tests.api.test_lens import demo_campaign, live_campaign
from tests.conftest import BOB

KEY = "api-test-key-9999"
DC_KEY = "dc-api-test-key-7777"
HOST = "https://api.data.gov.in/resource/"
ACCOUNT, AUDIENCE = "scheduler@omnicult-test.iam.gserviceaccount.com", "https://api.omnicult.test"


@pytest.fixture(autouse=True)
def fast_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    async def nap(_: float) -> None:
        return None

    monkeypatch.setattr(state_facts, "DataGovClient", lambda key: DataGovClient(
        key, http=HttpFetcher("data_gov_in", user_agent="t", max_retries=1, backoff_seconds=0, sleep=nap)))
    monkeypatch.setattr(state_facts, "DataCommonsClient", lambda key: DataCommonsClient(
        key, http=HttpFetcher("data_commons", user_agent="t", max_retries=1, backoff_seconds=0, sleep=nap)))
    state_facts._BACKOFF.clear()
    yield
    state_facts._BACKOFF.clear()


@pytest.fixture
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_GOV_IN_API_KEY", KEY)
    get_settings.cache_clear()


@pytest.fixture
def with_dc_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_COMMONS_API_KEY", DC_KEY)
    get_settings.cache_clear()


class DcUpstream:
    """Google Data Commons as respx serves it: the two recorded responses (a latest-figures request and a series request)."""

    def __init__(self, mock: respx.MockRouter) -> None:
        recording = recorded_datacommons()
        self.latest, self.series = copy.deepcopy(recording["latest"]), copy.deepcopy(recording["series"])
        self.calls: list[httpx.Request] = []
        self.fail: int | None = None
        mock.get(url__startswith=dc.API).mock(side_effect=self.answer)

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.fail:
            return httpx.Response(self.fail, json={"message": "no"})
        return httpx.Response(200, json=self.latest if request.url.params.get("date") == "LATEST" else self.series)

    def set_value(self, variable: str, region_code: str, value: float) -> None:
        """Change what the source says for one state, as a newer release would."""
        entity = self.latest["byVariable"][variable]["byEntity"][dc.DCIDS[region_code]]
        entity["orderedFacets"][0]["observations"][0]["value"] = value


class Upstream:
    """data.gov.in as respx serves it: the recorded rows, an `updated_date` per resource, and an optional failure status.
    `dc` serves Google Data Commons from the same router (used only when DATA_COMMONS_API_KEY is set)."""

    def __init__(self, mock: respx.MockRouter) -> None:
        self.dc = DcUpstream(mock)
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
    assert [g["key"] for g in body["groups"]] == ["population", "connectivity", "economy", "homes", "people", "health", "visitors"]
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
    people = fact(body, "population")  # Google Data Commons, recorded: a projection series, drawn as a trend
    assert (people["unit"], people["period"], round(people["value"], 3), people["national"]) == ("million", "2026", 77.609, None)
    assert [p["period"] for p in people["series"]] == [str(y) for y in range(2011, 2027)]
    assert (fact(body, "sex_ratio")["value"], fact(body, "sex_ratio")["unit"], fact(body, "sex_ratio")["period"]) == (1033, "whole", "2015")
    wage = fact(body, "wage_monthly")
    assert (wage["value"], wage["national"], wage["period"], wage["unit"]) == (20707.75, 21036.19, "2024-02", "inr")
    assert fact(body, "household_size")["unit"] == "decimal" and {f["key"] for g in body["groups"] if g["key"] == "health" for f in g["facts"]} == {"anaemia_women", "stunting"}
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
    assert (first.updated, first.failed) == (len(RESOURCES) + 1, 0)  # every data.gov.in resource and Data Commons
    async with read_session() as s:
        regions = set((await s.execute(select(m.StateFactSnapshot.region_code))).scalars())
    assert len(regions) >= 36 and {"IN-TN", "IN-UP", "IN-LA"} <= regions
    async with read_session() as s:
        dc_rows = list((await s.execute(select(m.StateFactSnapshot).where(m.StateFactSnapshot.resource_id.startswith(dc.RESOURCE_PREFIX)))).scalars())
    assert {r.resource_id for r in dc_rows} == {v.resource_id for v in dc.VARIABLES} and all(r.provenance and r.provenance["facet"] for r in dc_rows)
    assert all(r.retrieved_at.date().isoformat() == recorded_datacommons()["recorded_on"] for r in dc_rows)
    async with session() as s, s.begin():
        again = await state_facts.load_recording(s)
    assert (again.updated, again.unchanged) == (0, len(RESOURCES) + 1)  # the same recording is not stored twice


# --- Google Data Commons: live, merged with the recorded data.gov.in figures ------------------------------------------------


async def dc_rows() -> list[Any]:
    async with read_session() as s:
        return list((await s.execute(select(m.StateFactSnapshot).where(m.StateFactSnapshot.resource_id.startswith(dc.RESOURCE_PREFIX)))).scalars())


async def seeded_recordings() -> None:
    async with session() as s, s.begin():
        await state_facts.load_recording(s)


async def test_a_live_read_pulls_data_commons_once_stores_it_with_its_provenance_and_serves_the_snapshot(
    client: httpx.AsyncClient, seeded: Any, with_dc_key: None, upstream: Upstream,
) -> None:
    _, base = await live_campaign(client)
    first = await client.get(f"{base}/regions/IN-TN/state-facts")
    assert first.status_code == 200, first.text
    body = first.json()
    assert fact(body, "population")["period"] == "2026" and fact(body, "sex_ratio")["value"] == 1033 and fact(body, "wage_monthly")["national"] == 21036.19
    assert not any(f["key"] == "literacy" for g in body["groups"] for f in g["facts"])  # data.gov.in has no key here and nothing stored
    assert [r.url.params.get("date") for r in upstream.dc.calls] == ["LATEST", None]  # two requests fetch every state
    assert all(r.headers["X-API-Key"] == DC_KEY and DC_KEY not in str(r.url) for r in upstream.dc.calls)
    assert DC_KEY not in first.text and upstream.calls == []  # data.gov.in was not asked: it has no key
    rows = await dc_rows()
    assert len(rows) > 800 and all(r.provenance["facet"] and r.provenance["variable"] for r in rows) and {r.region_code for r in rows} >= {"IN-TN", "IN-LA", "IN"}
    assert (await client.get(f"{base}/regions/IN-KL/state-facts")).status_code == 200
    assert len(upstream.dc.calls) == 2  # served from the snapshot


async def test_the_read_merges_the_recorded_data_gov_in_figures_with_live_data_commons_figures(
    client: httpx.AsyncClient, seeded: Any, with_dc_key: None, upstream: Upstream,
) -> None:
    await seeded_recordings()  # what the seed job does on the deployed service
    _, base = await live_campaign(client)
    before = (await client.get(f"{base}/regions/IN-TN/state-facts")).json()
    assert upstream.dc.calls == [] and upstream.calls == []  # a fresh copy is served without a call
    upstream.dc.set_value("Count_Person_Female_AsAFractionOf_Count_Person_Male", "IN-TN", 1040.0)
    async with session() as s, s.begin():  # the Data Commons copy is now past its cadence
        await s.execute(update(m.StateFactSnapshot).where(m.StateFactSnapshot.resource_id.startswith(dc.RESOURCE_PREFIX))
                        .values(retrieved_at=utcnow() - timedelta(days=30)))
    after = (await client.get(f"{base}/regions/IN-TN/state-facts")).json()
    assert len(upstream.dc.calls) == 2 and upstream.calls == []  # data.gov.in stays a recorded source: no key, no call
    assert fact(before, "sex_ratio")["value"] == 1033 and fact(after, "sex_ratio")["value"] == 1040
    keys = {f["key"] for g in after["groups"] for f in g["facts"]}
    assert {"literacy", "nsdp", "women_internet", "population", "wage_monthly", "stunting"} <= keys  # both sources in one answer
    assert [g["key"] for g in after["groups"]] == ["population", "connectivity", "economy", "homes", "people", "health", "visitors"]
    assert fact(after, "literacy") == fact(before, "literacy")  # nothing of data.gov.in changed


async def test_when_data_commons_fails_the_stored_copy_is_served_beside_the_data_gov_in_figures(
    client: httpx.AsyncClient, seeded: Any, with_dc_key: None, upstream: Upstream,
) -> None:
    await seeded_recordings()
    _, base = await live_campaign(client)
    stored = await dc_rows()
    async with session() as s, s.begin():
        await s.execute(update(m.StateFactSnapshot).values(retrieved_at=utcnow() - timedelta(days=60)))
    upstream.dc.fail = 503
    down = await client.get(f"{base}/regions/IN-TN/state-facts")
    assert down.status_code == 200
    assert fact(down.json(), "sex_ratio")["value"] == 1033 and fact(down.json(), "literacy")["value"] == 80.09
    assert len(upstream.dc.calls) == 2  # tried once (two requests, each retried once is bounded by the client), then left alone
    after = len(upstream.dc.calls)
    assert (await client.get(f"{base}/regions/IN-WB/state-facts")).status_code == 200
    assert len(upstream.dc.calls) == after  # a failed pull is not retried on every read
    assert len(await dc_rows()) == len(stored)  # nothing was removed


@pytest.mark.parametrize(("upstream_status", "status", "code"), [
    (401, 503, "PROVIDER_NOT_CONFIGURED"), (403, 503, "PROVIDER_NOT_CONFIGURED"), (429, 429, "RATE_LIMITED"), (500, 502, "PROVIDER_ERROR"),
])
async def test_data_commons_failures_with_nothing_stored_are_typed_and_never_echo_the_key(
    client: httpx.AsyncClient, seeded: Any, with_dc_key: None, upstream: Upstream, upstream_status: int, status: int, code: str,
) -> None:
    upstream.dc.fail = upstream_status
    _, base = await live_campaign(client)
    response = await client.get(f"{base}/regions/IN-TN/state-facts")
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert DC_KEY not in response.text and "data commons" not in response.text.lower() and await dc_rows() == []


async def test_the_scheduler_refreshes_data_commons_only_when_it_has_a_key_and_stores_what_changed(
    client: httpx.AsyncClient, scheduler: None, with_dc_key: None, upstream: Upstream,
) -> None:
    first = await client.post(URL, headers=bearer("good"))
    assert first.status_code == 200, first.text
    facts = first.json()["state_facts"]
    assert [(r["resource"], r["status"]) for r in facts["resources"]] == [("datacommons", "updated")] and facts["failed"] == 0
    assert upstream.calls == [] and DC_KEY not in first.text
    rows = len(await dc_rows())
    second = (await client.post(URL, headers=bearer("good"))).json()["state_facts"]
    assert (second["updated"], second["unchanged"], second["failed"]) == (0, 1, 0) and len(await dc_rows()) == rows  # same figures: only checked
    upstream.dc.set_value("Mean_WagesMonthly_Worker", "IN-TN", 21000.0)
    third = (await client.post(URL, headers=bearer("good"))).json()["state_facts"]
    assert (third["updated"], third["unchanged"]) == (1, 0) and len(await dc_rows()) == rows  # updated in place
    tamil = next(r for r in await dc_rows() if (r.region_code, r.metric) == ("IN-TN", "wage_monthly"))
    assert tamil.value == 21000.0 and tamil.period == "2024-02"


async def test_a_scheduler_call_with_no_state_facts_key_skips_them_and_a_failing_data_commons_makes_it_500(
    client: httpx.AsyncClient, scheduler: None, upstream: Upstream, monkeypatch: pytest.MonkeyPatch,
) -> None:
    none = await client.post(URL, headers=bearer("good"))
    assert none.status_code == 200 and none.json()["state_facts"] is None and upstream.dc.calls == [] and upstream.calls == []
    monkeypatch.setenv("DATA_COMMONS_API_KEY", DC_KEY)
    monkeypatch.setenv("DATA_GOV_IN_API_KEY", KEY)
    get_settings.cache_clear()
    upstream.dc.fail = 500
    response = await client.post(URL, headers=bearer("good"))
    body = response.json()["state_facts"]
    assert response.status_code == 500 and body["failed"] == 1 and body["updated"] == len(RESOURCES)  # data.gov.in still ran
    assert next(r for r in body["resources"] if r["resource"] == "datacommons")["error_kind"] == "http" and DC_KEY not in response.text


async def test_a_manual_refresh_checks_data_commons_then_asks_to_wait(
    client: httpx.AsyncClient, seeded: Any, with_dc_key: None, upstream: Upstream, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seeded_recordings()
    _, base = await live_campaign(client)
    first = await client.post(f"{base}/regions/IN-TN/state-facts/refresh")
    assert first.status_code == 200 and len(upstream.dc.calls) == 2 and upstream.calls == []
    assert fact(first.json(), "population")["period"] == "2026"
    assert (await client.post(f"{base}/regions/IN-TN/state-facts/refresh")).status_code == 429  # checked a moment ago
    monkeypatch.setattr(state_facts, "MANUAL_REFRESH_GAP", timedelta(0))
    assert (await client.post(f"{base}/regions/IN-TN/state-facts/refresh")).status_code == 200 and len(upstream.dc.calls) == 4


async def test_a_variable_that_comes_back_empty_keeps_its_stored_figures_while_the_others_update(
    client: httpx.AsyncClient, scheduler: None, with_dc_key: None, upstream: Upstream,
) -> None:
    assert (await client.post(URL, headers=bearer("good"))).status_code == 200
    stored = [r for r in await dc_rows() if r.metric == "stunting"]
    assert stored
    upstream.dc.latest["byVariable"].pop("Count_Person_YearsUpto5_ConditionStunted_AsAFractionOf_Count_Person_Upto5Years")
    upstream.dc.set_value("IndexScore_SustainableDevelopmentGoal", "IN-KL", 80.0)
    again = (await client.post(URL, headers=bearer("good"))).json()["state_facts"]
    assert (again["updated"], again["failed"]) == (1, 0)
    assert len([r for r in await dc_rows() if r.metric == "stunting"]) == len(stored)
    assert next(r for r in await dc_rows() if (r.region_code, r.metric) == ("IN-KL", "sdg_score")).value == 80.0
