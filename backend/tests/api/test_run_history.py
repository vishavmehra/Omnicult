"""Run History: cost aggregation rules, the campaign list with totals, run detail, and workspace isolation."""

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.db import models as m
from app.schemas.common import StepTrace
from app.services.run_history import history_item, totals_of, usage_totals
from tests.api.omnicult_support import add_member, client_for, seeded  # noqa: F401
from tests.api.proof_support import API, add_run, add_usage, campaign_with_regions, step
from tests.conftest import BOB


def event(cost: float, tin: int = 100, tout: int = 20, thinking: int = 0, status: str = "ok") -> m.AiUsageEvent:
    return m.AiUsageEvent(
        id=uuid4(), capability="text", provider="google", model="gemini-x", prompt_version="p.v1", input_tokens=tin,
        output_tokens=tout, thinking_tokens=thinking, estimated_cost_usd=cost, status=status)


def traces(*steps: dict) -> list[StepTrace]:
    return [StepTrace.model_validate(s) for s in steps]


def test_a_run_with_usage_events_is_costed_from_them_and_never_double_counted() -> None:
    steps = traces(step(cost=0.5, tokens_in=999, tokens_out=999))  # the same call, recorded in the stage trace too
    assert usage_totals(steps, [event(0.002), event(0.003, tin=10, tout=5, thinking=7)]) == (110, 25, 7, 0.005, "usage_events")


def test_without_events_cost_comes_from_the_stage_traces_and_missing_costs_stay_missing() -> None:
    both = traces(step(cost=0.002), step("brief", cost=0.003, tokens_in=10, tokens_out=5))
    assert usage_totals(both, []) == (110, 55, 0, 0.005, "run_steps")
    partial = traces(step(cost=0.002), step("brief", cost=None))
    assert usage_totals(partial, [])[3] == 0.002  # the known part; the run is flagged as costed from steps
    unknown = traces(step(cost=None))
    assert usage_totals(unknown, []) == (100, 50, 0, None, "none")  # tokens are known, cost is not
    assert usage_totals([], []) == (0, 0, 0, None, "none")
    thinking = traces({**step(), "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 40, "estimated_cost_usd": 0.1}})
    assert usage_totals(thinking, []) == (10, 5, 25, 0.1, "run_steps")  # total minus input and output is thinking


def run_row(**kw: Any) -> m.AgentRun:
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
    base = dict(id=uuid4(), project_id=uuid4(), campaign_id=uuid4(), run_type="risk_scan", status="completed", mode="live",
                steps=[], error=None, created_at=start, started_at=start, completed_at=start + timedelta(seconds=30), attempt=1)
    return m.AgentRun(**(base | kw))


def test_items_report_models_prompts_duration_errors_and_label_costs_as_estimates() -> None:
    row = run_row(steps=[step(model="m-a", prompt="x.v1"), step("b", model="m-b", prompt="x.v2", status="failed", error_code="TIMEOUT")],
                  status="failed", error={"code": "PROVIDER_TIMEOUT", "message": "Timed out.", "stage": "b", "retryable": True})
    item = history_item(row, [], uuid4(), resumable=False)
    assert (item.models, item.prompt_versions, item.providers) == (["m-a", "m-b"], ["x.v1", "x.v2"], ["google"])
    assert item.duration_ms == 30000 and item.failed_stages == ["b"] and item.error and item.error.code == "PROVIDER_TIMEOUT"
    assert item.cost_is_estimate is True and item.actual_cost_usd is None and item.operation == "Risk scan"
    assert (item.ai_calls, item.failed_ai_calls) == (2, 0)
    pending = history_item(run_row(status="running", completed_at=None), [event(0.1, status="error")], None, resumable=False)
    assert pending.duration_ms is None and pending.failed_ai_calls == 1 and pending.cost_basis == "usage_events"


def test_totals_cover_every_run_and_flag_runs_without_a_cost() -> None:
    costed = history_item(run_row(steps=[step(cost=0.01)]), [], None, resumable=False)
    free = history_item(run_row(status="failed", steps=[]), [], None, resumable=False)
    totals = totals_of([costed, free], (2, 0.004))
    assert (totals.runs, totals.runs_without_cost, totals.estimated_cost_usd) == (2, 1, 0.01)
    assert totals.by_status == {"completed": 1, "failed": 1} and (totals.unattributed_events, totals.unattributed_cost_usd) == (2, 0.004)


async def test_the_campaign_run_history_lists_runs_with_filters_pages_and_totals(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client)
    pid, cid = setup["project"]["id"], setup["campaign"]["id"]
    metered = await add_run(pid, cid, run_type="market_discovery", minutes_ago=30)
    await add_usage(metered, cid, pid, cost=0.004, tokens_in=300, tokens_out=60)
    await add_usage(metered, cid, pid, cost=0.001, tokens_in=50, tokens_out=10, status="error", error_code="RATE_LIMITED")
    traced = await add_run(pid, cid, run_type="risk_scan", minutes_ago=20, steps=[step(cost=0.002, model="m-b", prompt="risk.v1")])
    await add_run(pid, cid, run_type="campaign_rehearsal", status="failed", minutes_ago=10,
                  error={"code": "RUN_FAILED", "message": "The model returned invalid output.", "stage": "simulate", "retryable": True})
    await add_usage(None, cid, pid, cost=0.0007, capability="embeddings", prompt=None)  # a search embedding: no run
    page = (await client.get(f"{API}/campaigns/{cid}/run-history", params={"limit": 2})).json()
    assert page["total"] == 3 and len(page["items"]) == 2 and [i["run_type"] for i in page["items"]] == ["campaign_rehearsal", "risk_scan"]
    totals = page["totals"]  # over all three runs, not just this page
    assert totals["runs"] == 3 and totals["by_status"] == {"failed": 1, "completed": 2} and totals["runs_without_cost"] == 1
    assert totals["estimated_cost_usd"] == pytest.approx(0.007) and totals["input_tokens"] == 100 + 350 and totals["cost_is_estimate"] is True
    assert (totals["unattributed_events"], totals["unattributed_cost_usd"]) == (1, 0.0007)
    failed = page["items"][0]
    assert failed["error"]["message"] == "The model returned invalid output." and failed["failed_stages"] == ["simulate"]
    assert failed["estimated_cost_usd"] is None and failed["cost_basis"] == "none"
    rest = (await client.get(f"{API}/campaigns/{cid}/run-history", params={"limit": 2, "offset": 2})).json()
    only = rest["items"][0]
    assert [only["run_type"], only["cost_basis"], only["estimated_cost_usd"]] == ["market_discovery", "usage_events", 0.005]
    assert (only["ai_calls"], only["failed_ai_calls"], only["models"], only["prompt_versions"]) == (2, 1, ["gemini-3.5-flash-lite"], ["atlas.v1"])
    assert only["workspace_id"] == str(setup["workspace_id"]) and only["actual_cost_usd"] is None
    by_status = (await client.get(f"{API}/campaigns/{cid}/run-history", params={"status": "failed"})).json()
    assert by_status["total"] == 1 and by_status["totals"]["runs"] == 1
    by_type = (await client.get(f"{API}/campaigns/{cid}/run-history", params={"run_type": "risk_scan"})).json()
    assert [i["run_id"] for i in by_type["items"]] == [str(traced)] and by_type["items"][0]["cost_basis"] == "run_steps"


async def test_run_detail_shows_stages_metered_calls_and_references(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client)
    pid, cid = setup["project"]["id"], setup["campaign"]["id"]
    run_id = await add_run(pid, cid, steps=[step(), step("brief", model="m-b")])
    await add_usage(run_id, cid, pid, cost=0.002)
    detail = (await client.get(f"{API}/runs/{run_id}/history")).json()
    assert detail["run_id"] == str(run_id) and [s["stage"] for s in detail["steps"]] == ["interpret", "brief"]
    assert [(e["model"], e["estimated_cost_usd"], e["status"]) for e in detail["usage_events"]] == [("gemini-3.5-flash-lite", 0.002, "ok")]
    assert detail["input_ref"] == {"kind": "stored_run_inputs", "run_id": str(run_id), "content_version_id": None, "study_id": None, "fields": ["request"]}
    assert detail["output_ref"] is None and detail["resumable"] is False and detail["cost_is_estimate"] is True
    assert (await client.get(f"{API}/runs/{uuid4()}/history")).status_code == 404


async def test_run_history_cannot_cross_workspaces(seeded: Any, client: httpx.AsyncClient, client_for: Any) -> None:
    setup = await campaign_with_regions(client)
    pid, cid = setup["project"]["id"], setup["campaign"]["id"]
    run_id = await add_run(pid, cid)
    bob = client_for(BOB)
    assert (await bob.get(f"{API}/campaigns/{cid}/run-history")).status_code == 404
    assert (await bob.get(f"{API}/runs/{run_id}/history")).status_code == 404
    await add_member(UUID(str(setup["workspace_id"])), "bob", "viewer")
    assert (await bob.get(f"{API}/campaigns/{cid}/run-history")).json()["total"] == 1
    assert (await bob.get(f"{API}/runs/{run_id}/history")).status_code == 200
