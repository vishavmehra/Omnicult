"""Live Pulse API: the labelled sample dataset, the regional dashboard, alert preview, platform status, tenancy."""

from datetime import date, timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.services import pulse_sample as sample
from tests.api.omnicult_support import API, add_member, client_for  # noqa: F401
from tests.api.test_crud import make_campaign, make_project
from tests.conftest import BOB

LABEL = "Live Pulse dataset"
ROWS = 4620


async def campaign_of(client: httpx.AsyncClient) -> tuple[dict[str, Any], str]:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    return project, f"{API}/campaigns/{campaign['id']}/pulse"


async def loaded(client: httpx.AsyncClient) -> tuple[dict[str, Any], str]:
    project, base = await campaign_of(client)
    response = await client.post(f"{base}/sample-dataset")
    assert response.status_code == 200, response.text
    return project, base


def assert_labelled(body: dict[str, Any]) -> None:
    assert body["is_sample"] is True and body["label"] == LABEL and body["source_kind"] == "sample"
    assert body["dataset_version"] == sample.DATASET_VERSION and body["limitations"]
    assert not any(w in x.lower() for x in body["limitations"] for w in ("demo", "fixture", "sample", "no real audience"))


async def test_nothing_is_loaded_until_the_explicit_action(client: httpx.AsyncClient) -> None:
    _, base = await campaign_of(client)
    status = (await client.get(f"{base}/sample-dataset")).json()
    assert status["loaded"] is False and status["row_count"] == 0 and status["is_sample"] is True and status["note"] == "Not loaded."
    for path in ("summary", "timeseries?metric=ctr", "versions/compare", "alerts", "freshness"):
        response = await client.get(f"{base}/{path}")
        assert response.status_code == 409 and "not loaded" in response.json()["error"]["message"], path
    assert (await client.get(f"{base}/metrics")).status_code == 200  # the catalogue needs no data


async def test_load_and_reload_give_identical_labelled_rows(client: httpx.AsyncClient) -> None:
    _, base = await loaded(client)
    first = (await client.get(f"{base}/sample-dataset")).json()
    assert first["loaded"] is True and first["row_count"] == ROWS and first["is_sample"] is True and first["label"] == LABEL
    assert first["regions"] == ["IN-KL", "IN-MH", "IN-TN", "IN-WB"] and first["platforms"] == ["google_ads", "youtube"]
    assert first["date_from"] == "2026-10-27" and first["date_to"] == "2026-11-16" and first["provisional_from"] == "2026-11-15"
    summary = (await client.get(f"{base}/summary")).json()
    again = await client.post(f"{base}/sample-dataset")
    assert again.status_code == 200 and again.json() == first  # refresh replaces the rows with identical ones
    assert (await client.get(f"{base}/summary")).json() == summary
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.MetricSeries)) == ROWS  # replaced, not appended
        assert set(await s.scalars(select(m.MetricSeries.source_kind).distinct())) == {"sample"}
        assert set(await s.scalars(select(m.MetricSeries.dataset_version).distinct())) == {sample.DATASET_VERSION}
        audit = await s.scalar(select(func.count()).select_from(m.AuditLog).where(m.AuditLog.action == "pulse.sample_dataset.load"))
        assert audit == 2


async def test_every_data_response_carries_the_sample_label(client: httpx.AsyncClient) -> None:
    _, base = await loaded(client)
    version = quote(sample.ORIGINAL)
    for path in ("summary", "timeseries?metric=ctr&metric=reach", f"timeseries?metric=cpm&group_by=region&version={version}",
                 "versions/compare", "alerts", "freshness"):
        response = await client.get(f"{base}/{path}")
        assert response.status_code == 200, (path, response.text)
        assert_labelled(response.json())
    summary = (await client.get(f"{base}/summary")).json()
    for card in summary["regions"]:
        for group in card["groups"]:
            for value in group["metrics"]:
                assert value["source_kind"] == "sample" and value["platforms"] and value["last_updated_at"]
                assert value["date_from"] == "2026-10-27" and value["date_to"] == "2026-11-16" and value["region_code"] == card["region_code"]
    for alert in (await client.get(f"{base}/alerts")).json()["alerts"]:
        assert alert["is_sample"] is True and alert["label"] == LABEL
    for series in (await client.get(f"{base}/timeseries?metric=ctr&group_by=version")).json()["series"]:
        assert series["source_kind"] == "sample"


async def test_catalogue_lists_groups_formulas_and_what_the_sample_lacks(client: httpx.AsyncClient) -> None:
    _, base = await campaign_of(client)
    catalogue = (await client.get(f"{base}/metrics")).json()
    items = {i["name"]: i for i in catalogue["items"]}
    assert {i["group"] for i in items.values()} == {
        "delivery", "cost", "response", "video", "outcome", "site", "conversation", "brand", "creative_health"}
    assert items["ctr"]["formula"] == "clicks / impressions" and items["ctr"]["kind"] == "calculated"
    assert items["cpm"]["formula"] == "spend / impressions * 1000" and items["roas"]["formula"] == "conversion_value / spend"
    assert items["impressions"]["formula"] is None and items["spend"]["unit"] == "inr"
    assert items["sessions"]["in_sample"] is False and items["comment_volume"]["in_sample"] is False
    assert items["ctr"]["in_sample"] is True and items["thruplays"]["platforms"] == ["meta"]


async def test_summary_cards_group_metrics_and_flag_provisional_values(client: httpx.AsyncClient) -> None:
    _, base = await loaded(client)
    summary = (await client.get(f"{base}/summary")).json()
    assert [c["region_code"] for c in summary["regions"]] == ["IN-KL", "IN-MH", "IN-TN", "IN-WB"]
    tn = next(c for c in summary["regions"] if c["region_code"] == "IN-TN")
    assert tn["region_name"] == "Tamil Nadu" and len(tn["versions"]) == 3
    assert [g["group"] for g in tn["groups"]] == ["delivery", "cost", "response", "video", "outcome", "creative_health"]
    values = {v["metric"]: v for g in tn["groups"] for v in g["metrics"]}
    assert 0.002 < values["ctr"]["value"] < 0.025 and values["ctr"]["provisional"] is True  # the range includes day 20
    assert values["impressions"]["value"] >= values["reach"]["value"] >= values["clicks"]["value"] > 0
    assert values["cpm"]["unit"] == "inr" and values["roas"]["unit"] == "multiple"
    assert values["ctr_change_vs_first_week"]["value"] is not None and values["ctr_change_vs_first_week"]["provisional"] is False
    settled = (await client.get(f"{base}/summary?date_to=2026-11-14&region=IN-TN")).json()
    assert [c["region_code"] for c in settled["regions"]] == ["IN-TN"] and settled["date_to"] == "2026-11-14"
    for group in settled["regions"][0]["groups"]:
        assert all(v["provisional"] is False for v in group["metrics"]), group["group"]
    one_platform = (await client.get(f"{base}/summary?platform=youtube&region=IN-TN")).json()
    assert {p for g in one_platform["regions"][0]["groups"] for v in g["metrics"] for p in v["platforms"]} == {"youtube"}


async def test_summary_ctr_matches_the_series_it_is_built_from(client: httpx.AsyncClient) -> None:
    _, base = await loaded(client)
    series = (await client.get(f"{base}/timeseries?metric=clicks&metric=impressions&region=IN-MH")).json()["series"]
    clicks = sum(p["value"] for p in next(s for s in series if s["metric"] == "clicks")["points"])
    impressions = sum(p["value"] for p in next(s for s in series if s["metric"] == "impressions")["points"])
    summary = (await client.get(f"{base}/summary?region=IN-MH")).json()
    ctr = next(v for g in summary["regions"][0]["groups"] for v in g["metrics"] if v["metric"] == "ctr")
    assert ctr["value"] == pytest.approx(clicks / impressions)


async def test_time_series_split_range_and_provisional_points(client: httpx.AsyncClient) -> None:
    _, base = await loaded(client)
    body = (await client.get(f"{base}/timeseries?metric=ctr&metric=conversions&group_by=region")).json()
    assert body["group_by"] == "region" and len(body["series"]) == 8
    ctr_mh = next(s for s in body["series"] if s["metric"] == "ctr" and s["region_code"] == "IN-MH")
    assert len(ctr_mh["points"]) == 21 and ctr_mh["version_label"] is None and ctr_mh["platform"] is None
    assert [p["date"] for p in ctr_mh["points"] if p["provisional"]] == ["2026-11-15", "2026-11-16"]
    assert ctr_mh["provisional_from"] == "2026-11-15" and ctr_mh["platforms"] == ["google_ads", "youtube"]
    ranged = (await client.get(f"{base}/timeseries?metric=ctr&region=IN-MH&date_from=2026-11-01&date_to=2026-11-03")).json()
    assert [p["date"] for p in ranged["series"][0]["points"]] == ["2026-11-01", "2026-11-02", "2026-11-03"]
    assert ranged["series"][0]["provisional_from"] is None and ranged["series"][0]["region_code"] == "IN-MH"
    reach = (await client.get(f"{base}/timeseries?metric=reach&metric=frequency&region=IN-TN&version={quote(sample.ORIGINAL)}&platform=google_ads")).json()
    values = [p["value"] for p in next(s for s in reach["series"] if s["metric"] == "reach")["points"]]
    assert values == sorted(values) and reach["caveats"] and reach["series"][0]["version_label"] == sample.ORIGINAL
    by_platform = (await client.get(f"{base}/timeseries?metric=cpm&group_by=platform&region=IN-KL")).json()
    assert {s["platform"] for s in by_platform["series"]} == {"google_ads", "youtube"}


@pytest.mark.parametrize(("query", "field"), [
    ("metric=nope", "metric"),
    ("metric=ctr_change_vs_first_week", "metric"),  # a two-week comparison is not a daily series
    ("metric=sessions", "metric"),  # defined for the product, not in the sample
    ("metric=ctr&region=IN-XX", "region"),
    ("metric=ctr&version=v9", "version"),
    ("metric=ctr&platform=ga4", "platform"),
    ("metric=ctr&date_from=2026-11-10&date_to=2026-11-01", "date_from"),
])
async def test_time_series_refuses_what_the_dataset_cannot_answer(client: httpx.AsyncClient, query: str, field: str) -> None:
    _, base = await loaded(client)
    response = await client.get(f"{base}/timeseries?{query}")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"][0]["field"] == field


async def test_version_comparison_within_shared_regions(client: httpx.AsyncClient) -> None:
    _, base = await loaded(client)
    body = (await client.get(f"{base}/versions/compare?metric=ctr&metric=cpm")).json()
    assert {r["region_code"] for r in body["regions"]} == {"IN-KL", "IN-TN", "IN-WB"}  # Maharashtra ran one version only
    tn = next(r for r in body["regions"] if r["region_code"] == "IN-TN")
    assert tn["baseline_version"] == sample.ORIGINAL and [c["version_label"] for c in tn["versions"]][0] == sample.ORIGINAL
    base_col = tn["versions"][0]
    assert base_col["is_baseline"] is True and all(m_["delta_vs_baseline"] is None for m_ in base_col["metrics"])
    base_ctr = next(m_["value"] for m_ in base_col["metrics"] if m_["metric"] == "ctr")
    adapted = next(c for c in tn["versions"] if c["version_label"] == sample.ADAPTED_A)
    ctr = next(m_ for m_ in adapted["metrics"] if m_["metric"] == "ctr")
    assert ctr["delta_vs_baseline"] == pytest.approx(ctr["value"] - base_ctr)
    assert ctr["delta_pct_vs_baseline"] == pytest.approx(ctr["delta_vs_baseline"] / base_ctr) and ctr["delta_vs_baseline"] > 0
    assert any("no significance test" in c or "experiment" in c for c in body["caveats"])
    chosen = (await client.get(f"{base}/versions/compare?region=IN-TN&baseline={quote(sample.ADAPTED_B)}")).json()
    assert chosen["regions"][0]["baseline_version"] == sample.ADAPTED_B
    default_metrics = {m_["metric"] for m_ in chosen["regions"][0]["versions"][0]["metrics"]}
    assert {"ctr", "cpm", "cpa", "roas", "ctr_change_vs_first_week"} <= default_metrics
    assert (await client.get(f"{base}/versions/compare?baseline=v9")).status_code == 422
    skipped = (await client.get(f"{base}/versions/compare?baseline={quote(sample.ADAPTED_A)}")).json()
    assert {r["region_code"] for r in skipped["regions"]} == {"IN-KL", "IN-TN", "IN-WB"}


async def test_freshness_states_provisional_and_not_real_time(client: httpx.AsyncClient) -> None:
    _, base = await loaded(client)
    body = (await client.get(f"{base}/freshness")).json()
    assert body["is_real_time"] is False and body["provisional_days"] == 2 and body["provisional_from"] == "2026-11-15"
    assert body["last_updated_at"].startswith("2026-11-17T06:00") and body["refresh"] == "Not refreshed automatically."
    assert any("report with a delay" in n for n in body["notes"])


async def test_alert_preview_is_labelled_deterministic_and_linked_to_its_data(client: httpx.AsyncClient) -> None:
    _, base = await loaded(client)
    body = (await client.get(f"{base}/alerts")).json()
    assert body["evaluated"] == 10 and "roadmap" in body["note"].lower() and body["thresholds"]["ctr_drop_pct"] == 0.2
    got = {(a["alert_type"], a["region_code"], a["version_label"], a["metric"]) for a in body["alerts"]}
    assert got == {
        ("ctr_drop", "IN-KL", sample.ORIGINAL, "ctr"), ("frequency_fatigue", "IN-KL", sample.ORIGINAL, "frequency"),
        ("cost_spike", "IN-TN", sample.ORIGINAL, "cpa"), ("cost_spike", "IN-WB", sample.ORIGINAL, "cpa"),
        ("cost_spike", "IN-WB", sample.ADAPTED_A, "cpm"),
    }
    drop = next(a for a in body["alerts"] if a["alert_type"] == "ctr_drop")
    assert drop["threshold"] == -0.2 and drop["observed_value"] < -0.2 and drop["as_of"] == "2026-11-14"  # settled days only
    assert drop["suggested_action"] and drop["campaign_id"] in base
    linked = await client.get(drop["source_path"])  # the alert points at the series it was computed from
    assert linked.status_code == 200 and linked.json()["series"][0]["region_code"] == "IN-KL"
    assert (await client.get(f"{base}/alerts")).json() == body
    strict = (await client.get(f"{base}/alerts?ctr_drop_pct=0.9&frequency_threshold=15&cost_spike_pct=5")).json()
    assert strict["alerts"] == [] and strict["thresholds"]["cost_spike_pct"] == 5
    loose = (await client.get(f"{base}/alerts?ctr_drop_pct=0.1")).json()
    assert any(a["alert_type"] == "ctr_drop" and a["region_code"] == "IN-TN" for a in loose["alerts"])
    assert (await client.get(f"{base}/alerts?ctr_drop_pct=0")).status_code == 422


async def test_predicted_vs_actual_is_not_available_and_never_fabricated(client: httpx.AsyncClient) -> None:
    project, base = await loaded(client)  # sample rows exist; they must not count as real results
    body = (await client.get(f"{base}/predicted-vs-actual")).json()
    assert body["status"] == "not_available" and body["real_result_rows"] == 0 and body["calibration_claimed"] is False
    assert "no real results" in body["reason"] and len(body["requirements"]) == 3 and "items" not in body
    campaign_id = UUID(base.split("/campaigns/")[1].split("/")[0])
    async with session() as s, s.begin():
        s.add(m.MetricSeries(
            id=uuid4(), project_id=UUID(project["id"]), campaign_id=campaign_id, day=date(2026, 11, 1), platform="google_ads",
            channel="video_action", version_label="v1", region_code="IN-MH", metric="impressions", value=10.0,
            provisional=False, source_kind="live", dataset_version="x", last_updated_at=utcnow()))
    again = (await client.get(f"{base}/predicted-vs-actual")).json()
    assert again["status"] == "not_available" and again["real_result_rows"] == 1 and again["calibration_claimed"] is False


async def test_sample_rows_never_mix_with_other_sources(client: httpx.AsyncClient) -> None:
    project, base = await loaded(client)
    before = (await client.get(f"{base}/summary?region=IN-MH")).json()
    campaign_id = UUID(base.split("/campaigns/")[1].split("/")[0])
    async with session() as s, s.begin():
        for kind in ("live", "test_account"):
            s.add(m.MetricSeries(
                id=uuid4(), project_id=UUID(project["id"]), campaign_id=campaign_id, day=date(2026, 11, 1),
                platform="google_ads", channel="video_action", version_label=sample.ORIGINAL, region_code="IN-MH",
                metric="impressions", value=9_999_999.0, provisional=False, source_kind=kind, dataset_version="x",
                last_updated_at=utcnow()))
    assert (await client.get(f"{base}/summary?region=IN-MH")).json() == before
    assert (await client.get(f"{base}/sample-dataset")).json()["row_count"] == ROWS
    await client.post(f"{base}/sample-dataset")  # a reload replaces sample rows only
    async with read_session() as s:
        kinds = dict((await s.execute(select(m.MetricSeries.source_kind, func.count()).group_by(m.MetricSeries.source_kind))).all())
    assert kinds == {"sample": ROWS, "live": 1, "test_account": 1}


async def test_platform_connections_are_a_read_only_roadmap_list(client: httpx.AsyncClient) -> None:
    project, base = await campaign_of(client)
    body = (await client.get(f"{base}/connections")).json()
    assert [(i["platform"], i["status"]) for i in body["items"]] == [
        ("google_ads", "not_connected"), ("youtube", "not_connected"), ("meta", "not_connected"), ("ga4", "not_connected")]
    assert body["connect_available"] is False and all("Roadmap" in i["note"] for i in body["items"])
    assert all(i["last_sync_at"] is None and i["scopes"] == [] for i in body["items"])
    for method in ("post", "put", "patch", "delete"):  # there is no connect, revoke or sync action
        assert (await getattr(client, method)(f"{base}/connections")).status_code in (404, 405)
    async with session() as s, s.begin():  # a stored row is read back as it is
        s.add(m.PlatformConnection(id=uuid4(), workspace_id=UUID(project["workspace_id"]), platform="ga4", status="test_account"))
    again = (await client.get(f"{base}/connections")).json()
    assert next(i for i in again["items"] if i["platform"] == "ga4")["status"] == "test_account"


async def test_other_workspaces_cannot_reach_a_campaigns_pulse(client: httpx.AsyncClient, client_for: Any) -> None:
    _, base = await loaded(client)
    bob = client_for(BOB)
    for method, path in (
        ("get", "metrics"), ("get", "connections"), ("get", "sample-dataset"), ("post", "sample-dataset"),
        ("get", "freshness"), ("get", "summary"), ("get", "timeseries?metric=ctr"), ("get", "versions/compare"),
        ("get", "alerts"), ("get", "predicted-vs-actual"),
    ):
        response = await getattr(bob, method)(f"{base}/{path}")
        assert response.status_code == 404, (method, path, response.text)
        assert response.json()["error"]["code"] == "NOT_FOUND"
    assert (await bob.get(f"{API}/campaigns/{uuid4()}/pulse/summary")).status_code == 404
    assert (await client.get(f"{base}/sample-dataset")).json()["row_count"] == ROWS  # untouched


async def test_a_stranger_cannot_load_sample_rows_into_a_campaign(client: httpx.AsyncClient, client_for: Any) -> None:
    _, base = await campaign_of(client)
    assert (await client_for(BOB).post(f"{base}/sample-dataset")).status_code == 404
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.MetricSeries)) == 0


@pytest.mark.parametrize(("role", "can_load"), [("owner", True), ("editor", True), ("reviewer", False), ("viewer", False)])
async def test_roles_read_every_member_but_only_editors_load(client: httpx.AsyncClient, client_for: Any, role: str, can_load: bool) -> None:
    project, base = await loaded(client)
    await add_member(UUID(project["workspace_id"]), "bob", role)
    bob = client_for(BOB)
    assert (await bob.get(f"{base}/summary")).status_code == 200 and (await bob.get(f"{base}/alerts")).status_code == 200
    response = await bob.post(f"{base}/sample-dataset")
    assert response.status_code == (200 if can_load else 403), response.text
    if not can_load:
        assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_an_archived_project_is_read_only(client: httpx.AsyncClient) -> None:
    project, base = await loaded(client)
    assert (await client.delete(f"{API}/projects/{project['id']}")).status_code == 204
    assert (await client.get(f"{base}/summary")).status_code == 200
    assert (await client.post(f"{base}/sample-dataset")).status_code == 409


async def test_unauthenticated_requests_are_refused(app: Any) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as anonymous:
        assert (await anonymous.get(f"{API}/campaigns/{uuid4()}/pulse/summary")).status_code == 401
        assert (await anonymous.post(f"{API}/campaigns/{uuid4()}/pulse/sample-dataset")).status_code == 401


def test_the_sample_window_is_what_the_tests_assume() -> None:
    assert sample.START == date(2026, 10, 27) and sample.END == sample.START + timedelta(days=20)
