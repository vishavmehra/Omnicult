"""Usage and Credits: the rules for what a cost is, who sees what, the demo split, today against the budget, and failures.
No network and no provider: rows are written straight into `ai_usage_events`."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.services.usage import Call, breakdown, budget_status, seed_demo_usage, series, tally
from tests.api.omnicult_support import API, add_member, client_for, seed, seeded  # noqa: F401
from tests.conftest import ALICE, BOB


def call(**kw: Any) -> Call:
    base: dict[str, Any] = dict(
        id=uuid4(), at=utcnow(), capability="chat", provider="google", model="gemini-3.8-flash", status="ok", error_code=None,
        input_tokens=100, output_tokens=10, thinking_tokens=0, cost=0.01, project_id=None, campaign_id=None, user_id=None,
        run_id=None, project_mode="live")
    return Call(**(base | kw))


# --- the cost rules (pure) -----------------------------------------------------------------------------------------


def test_a_missing_cost_is_never_counted_as_zero() -> None:
    priced, failed, no_usage = call(), call(status="error", error_code="PROVIDER_TIMEOUT", cost=0, input_tokens=0, output_tokens=0), call(cost=0, input_tokens=0, output_tokens=0)
    assert [c.cost_recorded for c in (priced, failed, no_usage)] == [True, False, False]
    assert tally([failed, no_usage]).estimated_cost_usd is None  # calls exist, no cost recorded anywhere
    mixed = tally([priced, failed, no_usage])
    assert (mixed.estimated_cost_usd, mixed.without_cost, mixed.calls) == (0.01, 2, 3)
    assert tally([]).estimated_cost_usd == 0  # no calls at all: nothing happened, so 0 is true
    assert call(cost=0).cost_recorded  # tokens were reported and the model is priced at 0: a real 0
    assert call(status="error", cost=0.004).cost_recorded  # a failed call that did bill keeps its cost


def test_a_fixture_call_has_a_true_zero_cost_and_is_counted_apart() -> None:
    fixture = call(provider="fixture", model="demo-fixture", cost=0, input_tokens=0, output_tokens=0)
    t = tally([fixture, fixture])
    assert (t.estimated_cost_usd, t.fixture, t.without_cost, t.recorded) == (0.0, 2, 0, 0)
    (row,) = breakdown([fixture], lambda c: c.capability)
    assert (row.estimated_cost_usd, row.fixture_calls, row.calls_without_cost) == (0.0, 1, 0)


def test_breakdown_orders_by_cost_then_calls_and_flags_models_without_a_price() -> None:
    rows = breakdown([call(model="gemini-3.8-flash"), call(model="mystery", cost=0.03), call(model="gemini-3.8-flash", cost=0.01)],
                     lambda c: f"{c.provider} / {c.model}", with_price=True)
    assert [(r.key, r.price_known, r.estimated_cost_usd) for r in rows] == [
        ("google / mystery", False, 0.03), ("google / gemini-3.8-flash", True, 0.02)]


def test_series_fills_quiet_days_and_the_budget_never_goes_negative() -> None:
    today = utcnow().date()
    points = series([call(at=utcnow())], today - timedelta(days=2), today)
    assert [(p.day == today, p.calls) for p in points] == [(False, 0), (False, 0), (True, 1)]
    over = budget_status([call(cost=7.0)], scope="workspace", day=today, active_runs=0, daily=5.0, per_run=0.5, max_active=2)
    assert (over.status, over.remaining_usd, over.used_share) == ("reached", 0.0, 1.4)
    near = budget_status([call(cost=4.5)], scope="workspace", day=today, active_runs=1, daily=5.0, per_run=0.0, max_active=2)
    assert (near.status, near.remaining_usd, near.run_budget_usd) == ("near", 0.5, None)
    off = budget_status([call()], scope="workspace", day=today, active_runs=0, daily=0.0, per_run=0.5, max_active=2)
    assert (off.status, off.daily_budget_usd, off.remaining_usd) == ("unlimited", None, None)
    own = budget_status([call(cost=4.5)], scope="own", day=today, active_runs=0, daily=5.0, per_run=0.5, max_active=2)
    assert (own.status, own.remaining_usd, own.used_share, own.spent_today_usd) == ("ok", None, None, 4.5)


# --- the report through the API ------------------------------------------------------------------------------------


async def team(client: httpx.AsyncClient) -> UUID:
    response = await client.post(f"{API}/workspaces", json={"name": "Studio"})
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def event(workspace: UUID, user: UUID | None, **kw: Any) -> None:
    base: dict[str, Any] = dict(
        id=uuid4(), workspace_id=workspace, user_id=user, capability="chat", provider="google", model="gemini-3.8-flash",
        input_tokens=100, output_tokens=10, thinking_tokens=0, estimated_cost_usd=0.01, status="ok", created_at=utcnow())
    async with session() as s, s.begin():
        s.add(m.AiUsageEvent(**(base | kw)))


async def project(workspace: UUID, owner: UUID, name: str, mode: str = "live") -> m.Project:
    async with session() as s, s.begin():
        row = m.Project(id=uuid4(), owner_id=owner, workspace_id=workspace, name=name, mode=mode)
        s.add(row)
    return row


async def user_id(label: str) -> UUID:
    from app.core.auth import dev_user_id

    return dev_user_id(label)


@pytest.fixture
async def filled(client: httpx.AsyncClient, client_for: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Alice owns a team workspace; bob is an editor in it. A live project, a demo project, and a spread of calls."""
    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "1.00")
    get_settings.cache_clear()
    ws = await team(client)
    alice, bob = await user_id("alice"), await user_id("bob")
    await add_member(ws, "bob", "editor")
    live, demo = await project(ws, alice, "Aamod launch"), await project(ws, alice, "Demo", "demo")
    campaign, run = uuid4(), uuid4()
    async with session() as s, s.begin():
        s.add(m.Campaign(id=campaign, project_id=live.id, name="Diwali", campaign_type="advertisement", evaluation_criteria={}))
        await s.flush()
        s.add(m.AgentRun(id=run, project_id=live.id, campaign_id=campaign, run_type="transcreate", mode="live", created_by=alice, status="completed"))
    at = {"project_id": live.id, "campaign_id": campaign}
    await event(ws, alice, run_id=run, **at)  # priced 0.01
    await event(ws, alice, status="error", error_code="PROVIDER_TIMEOUT", estimated_cost_usd=0.0, input_tokens=0, output_tokens=0, **at)
    await event(ws, alice, estimated_cost_usd=0.0, input_tokens=0, output_tokens=0, **at)  # no usage reported
    await event(ws, bob, capability="embeddings", model="gemini-embedding", estimated_cost_usd=0.002, **at)
    await event(ws, bob, model="mystery-model", estimated_cost_usd=0.01)  # no project, a model with no price entry
    await event(ws, bob, estimated_cost_usd=0.5, created_at=utcnow() - timedelta(days=3), **at)
    for _ in range(2):
        await event(ws, alice, provider="fixture", model="demo-fixture", estimated_cost_usd=0.0, input_tokens=0, output_tokens=0, project_id=demo.id)
    return {"ws": ws, "alice": alice, "bob": bob, "run": run, "demo": demo.id, "live": live.id, "campaign": campaign,
            "bob_client": client_for(BOB)}


async def report(client: httpx.AsyncClient, ws: UUID, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/workspaces/{ws}/usage/report", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_an_owner_sees_the_workspace_with_honest_costs(client: httpx.AsyncClient, filled: dict[str, Any]) -> None:
    r = await report(client, filled["ws"], days=7)
    assert (r["scope"], r["mode"], r["calls"], r["failed_calls"], r["fixture_calls"]) == ("workspace", "live", 6, 1, 0)
    assert r["estimated_cost_usd"] == 0.522 and r["calls_without_cost"] == 2 and r["actual_cost_usd"] is None
    assert any("Vertex trial credit" in n for n in r["notes"]) and any("estimates" in n for n in r["notes"])
    assert [(x["key"], x["calls"]) for x in r["by_capability"]] == [("chat", 5), ("embeddings", 1)]
    models = {x["key"]: x for x in r["by_model"]}
    assert models["google / mystery-model"]["price_known"] is False and models["google / gemini-3.8-flash"]["price_known"] is True
    assert models["google / gemini-3.8-flash"]["calls_without_cost"] == 2
    assert len(r["by_user"]) == 2 and all(x["label"] for x in r["by_user"])
    projects = {x["key"]: x["label"] for x in r["by_project"]}
    assert projects[str(filled["live"])] == "Aamod launch" and projects["none"] == "Not tied to a project"
    assert [x["label"] for x in r["by_campaign"] if x["key"] == str(filled["campaign"])] == ["Diwali"]
    run = next(x for x in r["by_run"] if x["key"] == str(filled["run"]))
    assert run["label"].startswith("Transcreation ") and run["calls"] == 1
    assert len(r["series"]) == 7 and sum(p["calls"] for p in r["series"]) == 6
    assert [p["calls"] for p in r["series"]][-1] == 5 and [p["calls"] for p in r["series"]][3] == 1  # today and three days ago


async def test_failed_calls_are_listed_with_their_error_codes(client: httpx.AsyncClient, filled: dict[str, Any]) -> None:
    r = await report(client, filled["ws"])
    assert r["failure_codes"] == [{"error_code": "PROVIDER_TIMEOUT", "calls": 1}]
    (failure,) = r["failures"]
    assert (failure["error_code"], failure["project_name"], failure["campaign_name"], failure["model"]) == ("PROVIDER_TIMEOUT", "Aamod launch", "Diwali", "gemini-3.8-flash")


async def test_today_against_the_daily_budget(client: httpx.AsyncClient, filled: dict[str, Any]) -> None:
    b = (await report(client, filled["ws"]))["budget"]
    assert (b["scope"], b["daily_budget_usd"], b["run_budget_usd"], b["max_active_runs_per_user"]) == ("workspace", 1.0, 0.5, 2)
    assert (b["spent_today_usd"], b["remaining_usd"], b["status"], b["calls_today"], b["calls_today_without_cost"]) == (0.022, 0.978, "ok", 7, 2)
    assert b["used_share"] == 0.022 and b["active_runs"] == 0 and b["resets_at"] > b["day"]


async def test_the_demo_project_is_reported_apart_and_plainly_as_fixtures(client: httpx.AsyncClient, filled: dict[str, Any]) -> None:
    r = await report(client, filled["ws"], mode="demo")
    assert (r["mode"], r["calls"], r["fixture_calls"], r["calls_without_cost"], r["estimated_cost_usd"]) == ("demo", 2, 2, 0, 0.0)
    assert any("saved fixtures" in n for n in r["notes"])
    assert [(x["label"], x["calls"]) for x in r["by_project"]] == [("Demo", 2)]
    assert r["failures"] == [] and r["by_model"][0]["key"] == "fixture / demo-fixture"


async def test_other_roles_see_only_their_own_calls(filled: dict[str, Any]) -> None:
    r = await report(filled["bob_client"], filled["ws"], days=7)
    assert (r["scope"], r["calls"], r["estimated_cost_usd"]) == ("own", 3, 0.512) and len(r["by_user"]) == 1
    assert r["failures"] == [] and any("your own calls" in n.lower() for n in r["notes"])
    assert r["budget"]["remaining_usd"] is None and r["budget"]["used_share"] is None  # workspace headroom stays with owners
    summary = (await filled["bob_client"].get(f"{API}/workspaces/{filled['ws']}/usage", params={"days": 7})).json()
    assert (summary["scope"], summary["calls"]) == ("own", 3)  # the settings panel reads the same rule


async def test_a_window_with_only_unpriced_calls_has_no_cost_rather_than_zero(client: httpx.AsyncClient) -> None:
    ws = await team(client)
    await event(ws, await user_id("alice"), status="error", error_code="RATE_LIMITED", estimated_cost_usd=0.0)
    r = await report(client, ws)
    assert (r["calls"], r["estimated_cost_usd"], r["calls_without_cost"]) == (1, None, 1)
    assert r["by_capability"][0]["estimated_cost_usd"] is None and r["budget"]["spent_today_usd"] is None
    empty = await report(client, await team(client))
    assert (empty["calls"], empty["estimated_cost_usd"], empty["failures"], empty["failure_codes"]) == (0, 0, [], [])


async def test_access_and_validation(client: httpx.AsyncClient, client_for: Any) -> None:
    ws = await team(client)
    base = f"{API}/workspaces/{ws}/usage/report"
    assert (await client_for(BOB).get(base)).status_code == 404  # not a member
    assert (await client.get(base, params={"days": 0})).status_code == 422
    assert (await client.get(base, params={"mode": "sandbox"})).status_code == 422
    assert (await client_for({}).get(base)).status_code == 401


# --- the demo hook -------------------------------------------------------------------------------------------------


async def test_the_demo_hook_records_one_fixture_call_per_fixture_stage_and_is_idempotent(client: httpx.AsyncClient) -> None:
    ws, alice = await team(client), await user_id("alice")
    demo, live = await project(ws, alice, "Demo", "demo"), await project(ws, alice, "Live")
    step = lambda stage, provider="fixture", agent="cultural_xray": {"stage": stage, "agent": agent, "status": "completed", "provider": provider, "model_id": "demo-fixture"}  # noqa: E731
    steps = [step("structuring_scenes"), step("transcribing"), step("observing_frames", agent="vision"), step("probing_media", provider="omnicult")]
    async with session() as s, s.begin():
        for p in (demo, live):
            s.add(m.AgentRun(id=uuid4(), project_id=p.id, run_type="creative_xray", mode="demo", created_by=alice, steps=steps))
    async with session() as s, s.begin():
        assert await seed_demo_usage(s, demo.id) == 3 and await seed_demo_usage(s, live.id) == 0  # a live project is never seeded
    async with session() as s, s.begin():
        assert await seed_demo_usage(s, demo.id) == 0  # already there
    async with read_session() as s:
        rows = (await s.execute(select(m.AiUsageEvent.capability, m.AiUsageEvent.provider, m.AiUsageEvent.estimated_cost_usd))).all()
    assert sorted(rows) == [("chat", "fixture", 0.0), ("transcribe", "fixture", 0.0), ("vision", "fixture", 0.0)]
    r = await report(client, ws, mode="demo")
    assert (r["calls"], r["fixture_calls"], r["estimated_cost_usd"]) == (3, 3, 0.0)
