"""Live Pulse Tier 3 over HTTP: Predicted vs Actual with its links and snapshots, saved Alerts with their lifecycle, Fatigue Watch,
the scheduler's internal call, roles and tenancy. Nothing here reaches a network or a model."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.scheduler_auth import get_verifier
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.services import pulse_sample as sample
from app.services import pulse_t3_alerts
from tests.api.launch_support import observations_json, quick_read
from tests.api.omnicult_support import API, add_member, client_for, seeded  # noqa: F401
from tests.api.test_crud import make_campaign, make_project
from tests.conftest import BOB

V1, V2, V3 = sample.ORIGINAL, sample.ADAPTED_A, sample.ADAPTED_B
CELLS = [("IN-MH", V1, 4, 3), ("IN-TN", V2, 9, 8), ("IN-KL", V2, 6, 5), ("IN-WB", V2, 7, 6)]  # region, Pulse version, understood, positive
SERIES_TYPES = {"ctr_drop", "frequency_fatigue", "cost_spike"}


class Campaign:
    def __init__(self, project: dict[str, Any], campaign_id: str) -> None:
        self.project, self.id = project, campaign_id
        self.base = f"{API}/campaigns/{campaign_id}/pulse"

    @property
    def uuid(self) -> UUID:
        return UUID(self.id)


async def campaign_of(client: httpx.AsyncClient, *, load: bool = True) -> Campaign:
    project = await make_project(client)
    c = Campaign(project, (await make_campaign(client, project["id"]))["id"])
    if load:
        assert (await client.post(f"{c.base}/sample-dataset")).status_code == 200
    return c


async def verdict(client: httpx.AsyncClient, c: Campaign, region: str, understood: int, positive: int, label: str = "Studio") -> UUID:
    """A Studio version of the campaign and a stored readiness verdict for it in one region."""
    node_id = uuid4()
    async with session() as s, s.begin():
        s.add(m.VersionNode(id=node_id, campaign_id=c.uuid, project_id=UUID(c.project["id"]), label=f"{label} {region}", actor="user",
                            settings={}, elements=[{"id": "h", "kind": "headline", "value": "x"}], created_at=utcnow()))
    body = {"region_code": region, "version_id": str(node_id), "observations": observations_json(
        quick_read=quick_read(understood=understood, positive=positive, relevant=positive).model_dump(mode="json"))}
    response = await client.post(f"{API}/campaigns/{c.id}/readiness", json=body)
    assert response.status_code in (200, 201), response.text
    return node_id


async def linked(client: httpx.AsyncClient, c: Campaign, cells: list[tuple[str, str, int, int]] = CELLS) -> dict[tuple[str, str], UUID]:
    out = {}
    for region, version, understood, positive in cells:
        out[(region, version)] = await verdict(client, c, region, understood, positive)
        put = await client.put(f"{c.base}/predicted-actual/links", json={"region_code": region, "pulse_version": version, "version_id": str(out[(region, version)])})
        assert put.status_code == 200, put.text
    return out


def keys(alerts: list[dict[str, Any]]) -> set[tuple[str, str, str, str]]:
    return {(a["alert_type"], a["region_code"], a["version_label"], a["metric"]) for a in alerts}


# --- Predicted vs Actual ----------------------------------------------------------------------------------------------------


async def test_nothing_is_compared_until_versions_are_linked(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    body = (await client.get(f"{c.base}/predicted-actual")).json()
    assert body["pairs"] == [] and body["unlinked"] == 10 and body["method"]["version"] == "pva-rank-1"
    assert {s["reading"] for s in body["summaries"]} == {"too_few_pairs"}
    board = (await client.get(f"{c.base}/predicted-actual/links")).json()
    assert len(board["slots"]) == 10 and all(s["version_id"] is None for s in board["slots"]) and board["candidates"] == []
    assert (await client.get(f"{c.base}/predicted-actual?metric=cpm")).status_code == 422  # only metrics where higher is better


async def test_linked_versions_are_compared_by_rank_against_settled_results(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    ids = await linked(client, c)
    body = (await client.get(f"{c.base}/predicted-actual?metric=ctr")).json()
    assert [(p["region_code"], p["pulse_version"]) for p in body["pairs"]] == sorted((r, v) for r, v, *_ in CELLS)
    assert body["unlinked"] == 6 and body["excluded"] == [] and body["is_sample"] is True
    summary = body["summaries"][0]
    assert summary["predictor"] == "launch_score" and summary["pairs"] == 4 and summary["agree"] + summary["near"] + summary["differ"] == 4
    assert summary["concordant"] + summary["discordant"] + summary["tied"] == 6 and -1 <= summary["kendall_tau_b"] <= 1
    for p in body["pairs"]:
        assert p["version_id"] == str(ids[(p["region_code"], p["pulse_version"])]) and p["predicted"]["verdict"] in {"go", "fix", "rethink"}
        assert p["actual"]["window_to"] == "2026-11-14" and p["actual"]["settled_days"] == 19  # provisional days excluded
        check = p["launch_score"]
        assert check["rank_gap"] == abs(check["predicted_rank"] - check["actual_rank"]) and check["predicted_value"] == p["predicted"]["overall_score"]
        # the actual value is the regional summary's CTR for that version over the same settled days
        card = (await client.get(f"{c.base}/summary", params={"region": p["region_code"], "version": p["pulse_version"], "date_to": "2026-11-14"})).json()["regions"][0]
        ctr = next(x for g in card["groups"] for x in g["metrics"] if x["metric"] == "ctr")
        assert ctr["value"] == pytest.approx(p["actual"]["value"])
    best = max(body["pairs"], key=lambda p: p["predicted"]["overall_score"])
    assert best["launch_score"]["predicted_rank"] == 1  # rank 1 is the highest stored score
    assert (await client.get(f"{c.base}/predicted-actual?metric=roas")).json()["metric_label"] == "ROAS"
    again = (await client.get(f"{c.base}/predicted-actual?metric=ctr")).json()
    assert again["fingerprint"] == body["fingerprint"]  # same inputs, same fingerprint


async def test_a_link_to_a_version_without_a_verdict_is_listed_as_not_compared(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    bare = uuid4()
    async with session() as s, s.begin():
        s.add(m.VersionNode(id=bare, campaign_id=c.uuid, project_id=UUID(c.project["id"]), label="No verdict yet", actor="user",
                            settings={}, elements=[], created_at=utcnow()))
    put = await client.put(f"{c.base}/predicted-actual/links", json={"region_code": "IN-TN", "pulse_version": V2, "version_id": str(bare)})
    assert put.status_code == 200
    assert next(s for s in put.json()["slots"] if s["region_code"] == "IN-TN" and s["pulse_version"] == V2)["studio_label"] == "No verdict yet"
    body = (await client.get(f"{c.base}/predicted-actual")).json()
    assert body["pairs"] == [] and "No Launch Room verdict" in body["excluded"][0]["reason"]


async def test_link_validation_unlinking_and_scoping(client: httpx.AsyncClient, seeded: Any) -> None:
    c, other = await campaign_of(client), await campaign_of(client)
    mine, theirs = await verdict(client, c, "IN-TN", 8, 6), await verdict(client, other, "IN-TN", 8, 6)
    put = lambda **body: client.put(f"{c.base}/predicted-actual/links", json={"region_code": "IN-TN", "pulse_version": V2, **body})  # noqa: E731
    assert (await put(version_id=str(theirs))).status_code == 404  # a version of another campaign
    assert (await client.put(f"{c.base}/predicted-actual/links", json={"region_code": "IN-MH", "pulse_version": V2, "version_id": str(mine)})).status_code == 422  # v2 never ran in MH
    assert (await put(version_id=str(mine))).status_code == 200 and (await put(version_id=str(mine))).status_code == 200  # idempotent
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.PulseVersionLink)) == 1
    unlinked = (await put(version_id=None)).json()
    assert next(s for s in unlinked["slots"] if s["region_code"] == "IN-TN" and s["pulse_version"] == V2)["version_id"] is None


async def test_snapshots_store_the_comparison_dedupe_and_say_whether_it_still_reproduces(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    ids = await linked(client, c)
    first = await client.post(f"{c.base}/predicted-actual/snapshots", json={"metric": "ctr"})
    assert first.status_code == 200, first.text
    snap = first.json()
    assert snap["pair_count"] == 4 and snap["matches_current"] is True and snap["method_version"] == "pva-rank-1"
    assert (await client.post(f"{c.base}/predicted-actual/snapshots", json={"metric": "ctr"})).json()["id"] == snap["id"]  # same inputs: no duplicate
    other_metric = (await client.post(f"{c.base}/predicted-actual/snapshots", json={"metric": "view_rate"})).json()
    assert other_metric["id"] != snap["id"]
    # a new verdict for one version changes what the comparison reads: the old snapshot no longer reproduces
    await client.post(f"{API}/campaigns/{c.id}/readiness", json={"region_code": "IN-TN", "version_id": str(ids[("IN-TN", V2)]), "observations": observations_json(
        quick_read=quick_read(understood=2, positive=1, relevant=1).model_dump(mode="json"))})
    history = (await client.get(f"{c.base}/predicted-actual/snapshots")).json()["items"]
    assert [i["id"] for i in history] == [other_metric["id"], snap["id"]]
    assert {i["metric"]: i["matches_current"] for i in history} == {"ctr": False, "view_rate": False}
    renewed = (await client.post(f"{c.base}/predicted-actual/snapshots", json={"metric": "ctr"})).json()
    assert renewed["id"] != snap["id"] and renewed["matches_current"] is True
    assert (await client.get(f"{c.base}/predicted-actual/snapshots")).json()["items"][0]["id"] == renewed["id"]


# --- Alerts: rules ---------------------------------------------------------------------------------------------------------


async def test_rules_are_saved_per_campaign_with_the_previews_bounds_and_defaults(client: httpx.AsyncClient, seeded: Any) -> None:
    c, other = await campaign_of(client), await campaign_of(client)
    made = await client.post(f"{c.base}/alert-rules", json={"name": "Kerala CTR", "alert_type": "ctr_drop", "region_code": "IN-KL"})
    assert made.status_code == 201, made.text
    rule = made.json()
    assert rule["params"]["ctr_drop_pct"] == 0.2 and rule["params"]["min_conversions"] is None and rule["enabled"] is True
    for bad in ({"ctr_drop_pct": 0}, {"ctr_drop_pct": 1.5}, {"frequency_threshold": 2}, {"min_rank_gap": 2}):  # out of bounds, or not read by a ctr_drop rule
        response = await client.post(f"{c.base}/alert-rules", json={"name": "Bad", "alert_type": "ctr_drop", "params": bad})
        assert response.status_code == 422, bad
    assert (await client.post(f"{c.base}/alert-rules", json={"name": "Bad", "alert_type": "frequency_fatigue", "params": {"frequency_threshold": 1}})).status_code == 422
    assert (await client.post(f"{c.base}/alert-rules", json={"name": "Bad", "alert_type": "cost_spike", "params": {"cost_spike_pct": 5.5}})).status_code == 422
    assert (await client.post(f"{c.base}/alert-rules", json={"name": "Bad", "alert_type": "ctr_drop", "region_code": "IN-XX"})).status_code == 422  # not in the series
    patched = await client.patch(f"{c.base}/alert-rules/{rule['id']}", json={"params": {"ctr_drop_pct": 0.35}, "name": "Kerala CTR (35%)"})
    assert patched.json()["params"]["ctr_drop_pct"] == 0.35 and patched.json()["name"] == "Kerala CTR (35%)"
    assert (await client.patch(f"{c.base}/alert-rules/{rule['id']}", json={"params": {"cost_spike_pct": 0.5}})).status_code == 422
    assert (await client.patch(f"{c.base}/alert-rules/{rule['id']}", json={"clear_region": True})).json()["region_code"] is None
    assert [r["name"] for r in (await client.get(f"{c.base}/alert-rules")).json()["items"]] == ["Kerala CTR (35%)"]
    assert (await client.get(f"{other.base}/alert-rules")).json()["items"] == []  # rules belong to their campaign
    assert (await client.patch(f"{other.base}/alert-rules/{rule['id']}", json={"enabled": False})).status_code == 404
    assert (await client.delete(f"{c.base}/alert-rules/{rule['id']}")).status_code == 204
    assert (await client.get(f"{c.base}/alert-rules")).json()["items"] == []


async def test_default_rules_are_four_and_only_for_a_campaign_with_none(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client, load=False)  # rules do not need the series
    made = await client.post(f"{c.base}/alert-rules/defaults")
    assert made.status_code == 201
    assert [r["alert_type"] for r in made.json()["items"]] == ["ctr_drop", "frequency_fatigue", "cost_spike", "prediction_miss"]
    assert made.json()["items"][2]["params"] == {
        "ctr_drop_pct": None, "frequency_threshold": None, "frequency_min_ctr_decline_pct": None, "cost_spike_pct": 0.3,
        "min_conversions": 30, "cost_metric": "both", "min_rank_gap": None}
    assert (await client.post(f"{c.base}/alert-rules/defaults")).status_code == 409
    assert (await client.get(f"{c.base}/alert-inbox")).status_code == 409  # the inbox reads the series: not loaded yet


# --- Alerts: evaluation and lifecycle --------------------------------------------------------------------------------------


async def test_saved_rules_flag_what_the_preview_flags_and_nothing_twice(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await client.post(f"{c.base}/alert-rules/defaults")
    preview = (await client.get(f"{c.base}/alerts")).json()["alerts"]
    ran = await client.post(f"{c.base}/alert-inbox/evaluate")
    assert ran.status_code == 200, ran.text
    inbox = (await client.get(f"{c.base}/alert-inbox")).json()
    assert keys(inbox["items"]) >= {(a["alert_type"], a["region_code"], a["version_label"], a["metric"]) for a in preview}
    assert {a["alert_type"] for a in inbox["items"]} <= SERIES_TYPES | {"prediction_miss"}
    assert inbox["open"] == len(inbox["items"]) and inbox["acknowledged"] == inbox["resolved"] == 0 and inbox["is_sample"] is True
    for a in inbox["items"]:
        assert a["status"] == "open" and a["rule_name"] and a["suggested_action"] and a["source_path"].startswith(f"/api/v1/campaigns/{c.id}/pulse/")
        assert [e["kind"] for e in a["events"]] == ["opened"] and a["events"][0]["trigger"] in ("manual", "refresh")
    again = (await client.post(f"{c.base}/alert-inbox/evaluate")).json()["evaluation"]
    assert again["opened"] == again["reopened"] == again["resolved"] == 0  # idempotent: nothing new, nothing changed
    after = (await client.get(f"{c.base}/alert-inbox")).json()
    assert [(a["id"], [e["kind"] for e in a["events"]]) for a in after["items"]] == [(a["id"], ["opened"]) for a in inbox["items"]]
    assert len(after["evaluations"]) == 2 and after["evaluations"][0]["trigger"] == "manual"


async def test_an_alert_can_be_acknowledged_resolved_and_reopened_and_a_decision_stands(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await client.post(f"{c.base}/alert-rules", json={"name": "CTR", "alert_type": "ctr_drop"})
    await client.post(f"{c.base}/alert-inbox/evaluate")
    alert = (await client.get(f"{c.base}/alert-inbox")).json()["items"][0]
    move = lambda action, note=None: client.post(f"{c.base}/alert-inbox/{alert['id']}/transition", json={"action": action, "note": note})  # noqa: E731
    assert (await move("reopen")).status_code == 409  # only a resolved alert is reopened
    acknowledged = (await move("acknowledge", "Looking into it")).json()
    assert acknowledged["status"] == "acknowledged" and acknowledged["events"][-1]["note"] == "Looking into it"
    assert acknowledged["events"][-1]["actor_user_id"] is not None and acknowledged["acknowledged_at"] is not None
    assert (await move("acknowledge")).status_code == 409
    resolved = (await move("resolve", "Refreshed the creative")).json()
    assert resolved["status"] == "resolved" and resolved["resolution"] == "manual" and resolved["resolved_at"] is not None
    assert (await move("resolve")).status_code == 409
    await client.post(f"{c.base}/alert-inbox/evaluate")  # the same data still fires: a person's decision stands
    assert (await client.get(f"{c.base}/alert-inbox?status=resolved")).json()["items"][0]["status"] == "resolved"
    reopened = (await move("reopen")).json()
    assert reopened["status"] == "open" and reopened["resolution"] is None and reopened["acknowledged_at"] is None
    assert [e["kind"] for e in reopened["events"]] == ["opened", "acknowledged", "resolved", "reopened"]
    counts = (await client.get(f"{c.base}/alert-inbox")).json()
    assert counts["open"] >= 1 and counts["acknowledged"] == 0 and counts["resolved"] == 0
    assert (await client.post(f"{c.base}/alert-inbox/{uuid4()}/transition", json={"action": "resolve"})).status_code == 404


async def test_a_condition_that_clears_resolves_its_alert_and_one_that_returns_reopens_it(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    made = (await client.post(f"{c.base}/alert-rules", json={"name": "CTR", "alert_type": "ctr_drop", "params": {"ctr_drop_pct": 0.1}})).json()
    first = (await client.post(f"{c.base}/alert-inbox/evaluate")).json()["evaluation"]
    assert first["opened"] >= 2
    await client.patch(f"{c.base}/alert-rules/{made['id']}", json={"params": {"ctr_drop_pct": 0.9}})  # nothing falls 90%
    cleared = (await client.post(f"{c.base}/alert-inbox/evaluate")).json()["evaluation"]
    assert cleared["resolved"] == first["opened"] and cleared["opened"] == 0
    items = (await client.get(f"{c.base}/alert-inbox")).json()["items"]
    assert {a["status"] for a in items} == {"resolved"} and {a["resolution"] for a in items} == {"cleared"}
    assert [e["kind"] for e in items[0]["events"]] == ["opened", "resolved"] and items[0]["events"][-1]["trigger"] == "manual"
    await client.patch(f"{c.base}/alert-rules/{made['id']}", json={"params": {"ctr_drop_pct": 0.1}})
    back = (await client.post(f"{c.base}/alert-inbox/evaluate")).json()["evaluation"]
    assert back["reopened"] == first["opened"] and back["opened"] == 0
    again = (await client.get(f"{c.base}/alert-inbox")).json()["items"]
    assert {a["status"] for a in again} == {"open"} and [e["kind"] for e in again[0]["events"]] == ["opened", "resolved", "reopened"]
    assert {a["id"] for a in again} == {a["id"] for a in items}  # the same alerts, one history


async def test_switching_a_rule_off_or_deleting_it_resolves_its_alerts_and_keeps_the_history(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    rule = (await client.post(f"{c.base}/alert-rules", json={"name": "Cost", "alert_type": "cost_spike", "params": {"cost_metric": "cpm"}})).json()
    await client.post(f"{c.base}/alert-inbox/evaluate")
    items = (await client.get(f"{c.base}/alert-inbox")).json()["items"]
    assert items and {a["metric"] for a in items} == {"cpm"} and (await client.get(f"{c.base}/alert-rules")).json()["items"][0]["open_alerts"] == len(items)
    await client.patch(f"{c.base}/alert-rules/{rule['id']}", json={"enabled": False})
    await client.post(f"{c.base}/alert-inbox/evaluate")
    assert {a["resolution"] for a in (await client.get(f"{c.base}/alert-inbox")).json()["items"]} == {"rule_disabled"}
    await client.patch(f"{c.base}/alert-rules/{rule['id']}", json={"enabled": True})
    assert (await client.post(f"{c.base}/alert-inbox/evaluate")).json()["evaluation"]["reopened"] == len(items)
    assert (await client.delete(f"{c.base}/alert-rules/{rule['id']}")).status_code == 204
    kept = (await client.get(f"{c.base}/alert-inbox")).json()["items"]
    assert len(kept) == len(items) and {a["resolution"] for a in kept} == {"rule_removed"} and {a["rule_id"] for a in kept} == {None}
    assert {a["rule_name"] for a in kept} == {"Cost"} and kept[0]["events"][-1]["note"] == "The rule was deleted."


async def test_a_slice_a_rule_cannot_read_is_reported_and_its_alert_is_not_cleared(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await client.post(f"{c.base}/alert-rules", json={"name": "CTR", "alert_type": "ctr_drop", "params": {"ctr_drop_pct": 0.1}, "region_code": "IN-KL"})
    await client.post(f"{c.base}/alert-inbox/evaluate")
    before = (await client.get(f"{c.base}/alert-inbox")).json()["items"]
    assert before
    async with session() as s, s.begin():  # the first week of Kerala's results goes missing
        await s.execute(delete(m.MetricSeries).where(
            m.MetricSeries.campaign_id == c.uuid, m.MetricSeries.region_code == "IN-KL", m.MetricSeries.day < sample.START + timedelta(days=7)))
    result = (await client.post(f"{c.base}/alert-inbox/evaluate")).json()
    assert result["evaluation"]["resolved"] == 0 and result["evaluation"]["not_evaluated"] == len(result["not_read"]) >= 1
    assert {n["region_code"] for n in result["not_read"]} == {"IN-KL"} and "settled weeks" in result["not_read"][0]["reason"]
    assert {a["status"] for a in (await client.get(f"{c.base}/alert-inbox")).json()["items"]} == {"open"}  # unknown is not cleared


async def test_prediction_miss_needs_three_compared_pairs_and_then_flags_rank_gaps(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await client.post(f"{c.base}/alert-rules", json={"name": "Miss", "alert_type": "prediction_miss", "params": {"min_rank_gap": 1}})
    short = (await client.post(f"{c.base}/alert-inbox/evaluate")).json()
    assert short["evaluation"]["alerts_found"] == 0 and "at least 3 pairs" in short["not_read"][0]["reason"]
    await linked(client, c)
    ran = (await client.post(f"{c.base}/alert-inbox/evaluate")).json()["evaluation"]
    pairs = (await client.get(f"{c.base}/predicted-actual")).json()["pairs"]
    expected = {(p["region_code"], p["pulse_version"]) for p in pairs if p["launch_score"]["rank_gap"] >= 1}
    inbox = (await client.get(f"{c.base}/alert-inbox")).json()["items"]
    assert ran["alerts_found"] == len(expected) == len(inbox) and {(a["region_code"], a["version_label"]) for a in inbox} == expected
    assert all(a["alert_type"] == "prediction_miss" and a["metric"] == "prediction_rank_gap" and "Predicted rank" in a["comparison"] for a in inbox)
    assert all(a["threshold"] == 1 and a["observed_value"] >= 1 for a in inbox)


async def test_a_sample_refresh_runs_the_saved_rules(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    assert (await client.get(f"{c.base}/alert-inbox")).json()["evaluations"] == []  # no rules at the first load: nothing evaluated
    await client.post(f"{c.base}/alert-rules/defaults")
    assert (await client.post(f"{c.base}/sample-dataset")).status_code == 200
    inbox = (await client.get(f"{c.base}/alert-inbox")).json()
    assert [e["trigger"] for e in inbox["evaluations"]] == ["refresh"] and inbox["open"] > 0
    assert {a["events"][0]["trigger"] for a in inbox["items"]} == {"refresh"}


# --- Fatigue Watch ------------------------------------------------------------------------------------------------------------


async def test_fatigue_flags_the_worn_out_version_with_its_reason_and_a_refresh(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    kerala = await verdict(client, c, "IN-KL", 6, 5, "Kerala adaptation")
    report = (await client.get(f"{c.base}/fatigue")).json()
    assert report["is_sample"] is True and report["thresholds"] == {"ctr_decline_pct": 0.1, "view_rate_decline_pct": 0.1, "frequency_threshold": 2.5}
    assert [r["region_code"] for r in report["regions"]] == ["IN-MH", "IN-TN", "IN-KL", "IN-WB"] and len(report["method"]) == 4
    rows = {(r["region_code"], r["version_label"]): r for region in report["regions"] for r in region["rows"]}
    worn = rows[("IN-KL", V1)]
    assert worn["status"] == "fatigued" and worn["pattern"] == "wearing_out" and worn["signals_triggered"] == 3 and worn["confidence"] == "Moderate"
    assert {s["name"] for s in worn["signals"] if s["triggered"]} == {"ctr_decay", "frequency", "repeated_exposure"} and "wear-out" in worn["reason"]
    assert len(worn["ctr"]) == 21 and worn["ctr"][-1]["provisional"] is True and len(worn["frequency"]) == 21
    kinds = [x["kind"] for x in worn["refresh"]]
    assert kinds == ["pulse_version", "studio_version"] and worn["refresh"][0]["label"] == V3
    studio = worn["refresh"][1]
    assert studio["version_id"] == str(kerala) and studio["verdict"] in {"go", "fix"} and "Kerala adaptation IN-KL" in studio["label"]
    assert rows[("IN-MH", V1)]["status"] == "healthy" and rows[("IN-MH", V1)]["refresh"] == []
    kl = next(r for r in report["regions"] if r["region_code"] == "IN-KL")
    assert kl["fatigued"] == 1 and kl["watch"] == 2 and kl["healthy"] == 0 and kl["not_enough_data"] == 0


async def test_fatigue_suggests_a_new_variant_when_nothing_else_is_ready_and_filters_by_region(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    only = (await client.get(f"{c.base}/fatigue?region=IN-KL&version={V1.replace(' ', '%20')}")).json()
    assert [r["region_code"] for r in only["regions"]] == ["IN-KL"] and [r["version_label"] for r in only["regions"][0]["rows"]] == [V1]
    refresh = only["regions"][0]["rows"][0]["refresh"]
    assert [x["kind"] for x in refresh] == ["pulse_version"]  # no Studio version has a verdict yet; Adapted B is running better
    strict = (await client.get(f"{c.base}/fatigue?ctr_decline_pct=0.9&frequency_threshold=20")).json()
    assert all(r["status"] != "fatigued" for region in strict["regions"] for r in region["rows"])
    for bad in ("ctr_decline_pct=0", "frequency_threshold=1", "view_rate_decline_pct=1.5", "region=KL"):
        assert (await client.get(f"{c.base}/fatigue?{bad}")).status_code == 422, bad
    assert (await client.get(f"{c.base}/fatigue?region=IN-ZZ")).status_code == 422


async def test_fatigue_needs_the_sample_to_be_loaded(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client, load=False)
    for path in ("fatigue", "predicted-actual", "predicted-actual/links", "alert-inbox"):
        assert (await client.get(f"{c.base}/{path}")).status_code == 409, path


# --- roles and tenancy ---------------------------------------------------------------------------------------------------------


async def test_other_workspaces_cannot_reach_any_of_it(client: httpx.AsyncClient, client_for: Any, seeded: Any) -> None:
    c = await campaign_of(client)
    rule = (await client.post(f"{c.base}/alert-rules", json={"name": "CTR", "alert_type": "ctr_drop"})).json()
    await client.post(f"{c.base}/alert-inbox/evaluate")
    alert = (await client.get(f"{c.base}/alert-inbox")).json()["items"][0]
    bob = client_for(BOB)
    calls = [
        ("get", "predicted-actual", None), ("get", "predicted-actual/links", None), ("get", "predicted-actual/snapshots", None),
        ("put", "predicted-actual/links", {"region_code": "IN-TN", "pulse_version": V2, "version_id": None}),
        ("post", "predicted-actual/snapshots", {"metric": "ctr"}), ("get", "alert-rules", None),
        ("post", "alert-rules", {"name": "x", "alert_type": "ctr_drop"}), ("patch", f"alert-rules/{rule['id']}", {"enabled": False}),
        ("delete", f"alert-rules/{rule['id']}", None), ("post", "alert-rules/defaults", None), ("get", "alert-inbox", None),
        ("post", "alert-inbox/evaluate", None), ("post", f"alert-inbox/{alert['id']}/transition", {"action": "resolve"}), ("get", "fatigue", None),
    ]
    for method, path, body in calls:
        response = await getattr(bob, method)(f"{c.base}/{path}", **({"json": body} if body is not None else {}))
        assert response.status_code == 404, (method, path, response.text)
    assert (await client.get(f"{c.base}/alert-inbox")).json()["items"][0]["status"] == "open"  # untouched


@pytest.mark.parametrize(("role", "can_write"), [("owner", True), ("editor", True), ("reviewer", False), ("viewer", False)])
async def test_every_member_reads_and_only_owners_and_editors_change(client: httpx.AsyncClient, client_for: Any, seeded: Any, role: str, can_write: bool) -> None:
    c = await campaign_of(client)
    rule = (await client.post(f"{c.base}/alert-rules", json={"name": "CTR", "alert_type": "ctr_drop"})).json()
    await client.post(f"{c.base}/alert-inbox/evaluate")
    alert = (await client.get(f"{c.base}/alert-inbox")).json()["items"][0]
    await add_member(UUID(c.project["workspace_id"]), "bob", role)
    bob = client_for(BOB)
    for path in ("predicted-actual", "predicted-actual/links", "predicted-actual/snapshots", "alert-rules", "alert-inbox", "fatigue"):
        assert (await bob.get(f"{c.base}/{path}")).status_code == 200, path
    writes = [  # in this order: the rule is switched off and deleted last, after its alert has been acted on
        ("post", f"alert-inbox/{alert['id']}/transition", {"action": "acknowledge"}), ("post", "alert-rules", {"name": "Mine", "alert_type": "ctr_drop"}),
        ("post", "alert-inbox/evaluate", None), ("post", "predicted-actual/snapshots", {"metric": "ctr"}),
        ("put", "predicted-actual/links", {"region_code": "IN-TN", "pulse_version": V2, "version_id": None}),
        ("patch", f"alert-rules/{rule['id']}", {"enabled": False}), ("delete", f"alert-rules/{rule['id']}", None),
    ]
    for method, path, body in writes:
        response = await getattr(bob, method)(f"{c.base}/{path}", **({"json": body} if body is not None else {}))
        assert (response.status_code < 300) == can_write, (role, method, path, response.status_code, response.text)
        if not can_write:
            assert response.status_code == 403


# --- Cloud Scheduler ---------------------------------------------------------------------------------------------------------

ACCOUNT, AUDIENCE = "scheduler@omnicult-test.iam.gserviceaccount.com", "https://api.omnicult.test"
URL = f"{API}/internal/pulse/evaluate-alerts"
Claims = dict[str, Any]


@pytest.fixture
def scheduler(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Cloud Scheduler configured, with a fake token verifier: a token's text names the claims it stands for."""
    monkeypatch.setenv("SCHEDULER_SERVICE_ACCOUNT", ACCOUNT)
    monkeypatch.setenv("SCHEDULER_AUDIENCE", AUDIENCE)
    get_settings.cache_clear()
    seen: dict[str, Any] = {"audiences": []}
    tokens: dict[str, Claims] = {"good": {"email": ACCOUNT, "email_verified": True, "aud": AUDIENCE}}

    def fake(token: str, audience: str) -> Claims:
        seen["audiences"].append(audience)
        if token not in tokens:
            raise ValueError("Token used too late, or signature invalid.")
        return tokens[token]

    app.dependency_overrides[get_verifier] = lambda: fake
    seen["tokens"] = tokens
    return seen


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_the_scheduler_endpoint_is_refused_unless_both_settings_are_present(client: httpx.AsyncClient, app: FastAPI) -> None:
    app.dependency_overrides[get_verifier] = lambda: (lambda token, audience: {"email": ACCOUNT, "email_verified": True})  # even a verifier that accepts everything
    for headers in ({}, bearer("anything")):
        response = await client.post(URL, headers=headers)
        assert response.status_code == 403 and response.json()["error"]["code"] == "FORBIDDEN" and "not enabled" in response.json()["error"]["message"]
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SCHEDULER_SERVICE_ACCOUNT", ACCOUNT)  # the audience is still missing
        get_settings.cache_clear()
        assert (await client.post(URL, headers=bearer("anything"))).status_code == 403
    get_settings.cache_clear()
    assert URL in {p for p in app.openapi()["paths"]}  # documented in the contract, and guarded


async def test_only_the_configured_service_account_with_a_valid_token_is_let_in(client: httpx.AsyncClient, scheduler: dict[str, Any]) -> None:
    scheduler["tokens"].update({
        "other": {"email": "someone-else@omnicult-test.iam.gserviceaccount.com", "email_verified": True},
        "unverified": {"email": ACCOUNT, "email_verified": False}, "no-email": {"sub": "123"},
        "shout": {"email": ACCOUNT.upper(), "email_verified": True}})
    for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}, bearer("garbage")):
        response = await client.post(URL, headers=headers)
        assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer", headers
    for token in ("other", "unverified", "no-email"):
        assert (await client.post(URL, headers=bearer(token))).status_code == 403, token
    assert (await client.post(URL, headers=bearer("good"))).status_code == 200
    assert (await client.post(URL, headers=bearer("shout"))).status_code == 200  # an email compares case-insensitively
    assert set(scheduler["audiences"]) == {AUDIENCE}  # the verifier is always given the configured audience, never the caller's
    assert (await client.post(URL, headers={"Authorization": "Bearer dev-alice"})).status_code == 401  # a user token is not a scheduler token


async def test_scheduled_evaluation_covers_every_campaign_once_per_period(client: httpx.AsyncClient, client_for: Any, scheduler: dict[str, Any], seeded: Any) -> None:
    mine, theirs, bare = await campaign_of(client), await campaign_of(client_for(BOB)), await campaign_of(client, load=False)
    for owner, c in ((client, mine), (client_for(BOB), theirs), (client, bare)):
        await owner.post(f"{c.base}/alert-rules/defaults")
    quiet = await campaign_of(client)  # a campaign with no rules is not part of the run
    first = (await client.post(URL, headers=bearer("good"))).json()
    assert first["campaigns_with_rules"] == 3 and first["evaluated"] == 2 and first["no_data"] == 1 and first["failed"] == 0
    assert first["already_evaluated"] == 0 and first["alerts_opened"] > 0 and first["period_key"] == utcnow().strftime("%Y-%m-%d")
    inbox = (await client.get(f"{mine.base}/alert-inbox")).json()
    assert [e["trigger"] for e in inbox["evaluations"]] == ["scheduler"] and inbox["evaluations"][0]["period_key"] == first["period_key"]
    assert {a["events"][0]["trigger"] for a in inbox["items"]} == {"scheduler"} and {a["events"][0]["actor_user_id"] for a in inbox["items"]} == {None}
    assert (await client_for(BOB).get(f"{theirs.base}/alert-inbox")).json()["open"] > 0  # each campaign is evaluated in its own workspace
    second = (await client.post(URL, headers=bearer("good"))).json()
    assert second["evaluated"] == 0 and second["already_evaluated"] == 2 and second["alerts_opened"] == 0  # same period: nothing changes
    after = (await client.get(f"{mine.base}/alert-inbox")).json()
    assert len(after["evaluations"]) == 1 and [a["events"] for a in after["items"]] == [a["events"] for a in inbox["items"]]
    assert (await client.get(f"{quiet.base}/alert-inbox")).json()["evaluations"] == []
    async with session() as s, s.begin():  # a new period evaluates again, and unchanged data changes nothing
        await s.execute(m.PulseAlertEvaluation.__table__.update().values(period_key="2000-01-01"))
    third = (await client.post(URL, headers=bearer("good"))).json()
    assert third["evaluated"] == 2 and third["alerts_opened"] == 0 and third["alerts_resolved"] == 0


async def test_one_failing_campaign_does_not_stop_the_run_and_archived_projects_are_skipped(
    client: httpx.AsyncClient, scheduler: dict[str, Any], seeded: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken, fine, archived = await campaign_of(client), await campaign_of(client), await campaign_of(client)
    for c in (broken, fine, archived):
        await client.post(f"{c.base}/alert-rules/defaults")
    async with session() as s, s.begin():
        (await s.get(m.Project, UUID(archived.project["id"]))).status = "archived"
    real = pulse_t3_alerts.run_evaluation

    async def flaky(s: Any, project: Any, campaign_id: UUID, *args: Any, **kwargs: Any) -> Any:
        if campaign_id == broken.uuid:
            raise RuntimeError("boom")
        return await real(s, project, campaign_id, *args, **kwargs)

    monkeypatch.setattr(pulse_t3_alerts, "run_evaluation", flaky)
    summary = (await client.post(URL, headers=bearer("good"))).json()
    assert summary["campaigns_with_rules"] == 2 and summary["evaluated"] == 1 and summary["failed"] == 1
    assert (await client.get(f"{fine.base}/alert-inbox")).json()["evaluations"][0]["trigger"] == "scheduler"
    assert (await client.get(f"{broken.base}/alert-inbox")).json()["evaluations"] == []  # a failed run leaves no half-written period
    monkeypatch.setattr(pulse_t3_alerts, "run_evaluation", real)
    retry = (await client.post(URL, headers=bearer("good"))).json()
    assert retry["evaluated"] == 1 and retry["already_evaluated"] == 1  # the failed campaign is picked up on the next call


def test_a_period_is_the_utc_day_or_an_hour_bucket() -> None:
    from datetime import UTC, datetime

    at = datetime(2026, 11, 18, 14, 35, tzinfo=UTC)
    assert pulse_t3_alerts.period_key(at, 24) == "2026-11-18"
    assert pulse_t3_alerts.period_key(at, 6) == "2026-11-18T12"
    assert pulse_t3_alerts.period_key(at, 1) == "2026-11-18T14"
