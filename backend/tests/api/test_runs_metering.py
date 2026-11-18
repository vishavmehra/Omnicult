"""Run idempotency and leases, AI usage metering, and the audit log."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.core.auth import dev_user_id
from app.core.idempotency import idempotency_key_var
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.services.audit import record_audit
from app.services.metering import AiUsage, record_ai_usage, spend_usd
from tests.api.omnicult_support import add_member, client_for, seeded, workspace_of  # noqa: F401
from tests.api.run_support import API, TRANSCREATE, demo_setup, start, transcreate_url
from tests.conftest import BOB, wait_for_run


@pytest.fixture(autouse=True)
def reference_data(seeded: Any) -> Any:  # the regions a transcreate run names
    return seeded


@pytest.fixture(autouse=True)
def clean_key() -> Any:
    idempotency_key_var.set(None)
    yield
    idempotency_key_var.set(None)


async def run_rows() -> list[m.AgentRun]:
    async with read_session() as s:
        return list((await s.execute(select(m.AgentRun))).scalars())


async def test_a_retried_request_returns_the_run_it_already_created(client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_setup(client)
    url = transcreate_url(campaign)
    headers = {"Idempotency-Key": "launch-2026-11-17:transcreate"}
    first = await start(client, url, TRANSCREATE, headers=headers)
    retry = await client.post(url, json=TRANSCREATE, headers=headers)
    assert retry.status_code == 202 and retry.json()["run_id"] == first["run_id"]
    await wait_for_run(client, first["run_id"])
    later = await client.post(url, json=TRANSCREATE, headers=headers)  # still the same run once it has finished
    assert later.json()["run_id"] == first["run_id"] and later.json()["status"] == "completed"
    assert len(await run_rows()) == 1
    fresh = await start(client, url, TRANSCREATE)  # no key: a new run, as before
    assert fresh["run_id"] != first["run_id"]


async def test_a_key_is_scoped_to_the_user_and_cannot_be_reused_for_a_different_request(
    client: httpx.AsyncClient, client_for: Any
) -> None:
    _, campaign, _ = await demo_setup(client)
    headers = {"Idempotency-Key": "same-key"}
    first = await start(client, transcreate_url(campaign), TRANSCREATE, headers=headers)
    await wait_for_run(client, first["run_id"])
    other_project, other_campaign, _ = await demo_setup(client)  # the same key for a request on another project
    reused = await client.post(transcreate_url(other_campaign), json=TRANSCREATE, headers=headers)
    assert other_project["id"] != campaign["project_id"]
    assert reused.status_code == 409 and "Idempotency-Key" in reused.json()["error"]["message"]
    bob = client_for(BOB)
    _, bobs_campaign, _ = await demo_setup(bob)
    bobs = await start(bob, transcreate_url(bobs_campaign), TRANSCREATE, headers=headers)
    assert bobs["run_id"] != first["run_id"]  # another user may use the same key


async def test_an_invalid_key_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{API}/projects", headers={"Idempotency-Key": "has spaces!"})
    assert response.status_code == 422 and response.json()["error"]["details"][0]["field"] == "Idempotency-Key"
    assert (await client.get(f"{API}/projects", headers={"Idempotency-Key": "k" * 129})).status_code == 422
    assert (await client.get(f"{API}/projects", headers={"Idempotency-Key": "ok_key-1.2:3"})).status_code == 200


async def test_the_database_refuses_a_second_run_with_the_same_user_and_key(client: httpx.AsyncClient) -> None:
    from sqlalchemy.exc import IntegrityError

    _, campaign, _ = await demo_setup(client)
    first = await start(client, transcreate_url(campaign), TRANSCREATE, headers={"Idempotency-Key": "k1"})
    await wait_for_run(client, first["run_id"])
    original = (await run_rows())[0]
    async with session() as s:
        s.add(m.AgentRun(
            id=uuid4(), project_id=original.project_id, run_type="transcreate", status="queued", mode="demo",
            created_by=original.created_by, idempotency_key="k1", created_at=utcnow(),
        ))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_runs_record_who_created_them_and_their_lease(client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_setup(client)
    accepted = await start(client, transcreate_url(campaign), TRANSCREATE)
    await wait_for_run(client, accepted["run_id"])
    [run] = await run_rows()
    assert run.created_by == dev_user_id("alice") and run.idempotency_key is None
    assert run.attempt == 1 and run.heartbeat_at is not None
    assert run.lease_expires_at is not None and run.lease_expires_at > run.heartbeat_at + timedelta(minutes=10)


async def test_the_active_run_limit_counts_the_users_own_runs_across_workspaces(client: httpx.AsyncClient, client_for: Any) -> None:
    """A teammate's runs in a shared workspace do not use up the caller's limit."""
    project, campaign, _ = await demo_setup(client)
    await add_member(UUID(project["workspace_id"]), "bob", "editor")
    async with session() as s, s.begin():
        for _ in range(2):  # bob already has two active runs in alice's project
            s.add(m.AgentRun(id=uuid4(), project_id=UUID(project["id"]), run_type="transcreate",
                             status="running", mode="demo", created_by=dev_user_id("bob"), created_at=utcnow()))
    accepted = await client.post(transcreate_url(campaign), json=TRANSCREATE)
    assert accepted.status_code == 202  # alice has none of her own
    blocked = await client_for(BOB).post(transcreate_url(campaign), json=TRANSCREATE)
    assert blocked.status_code == 429


async def test_a_viewer_cannot_start_runs(client: httpx.AsyncClient, client_for: Any) -> None:
    project, campaign, _ = await demo_setup(client)
    await add_member(UUID(project["workspace_id"]), "bob", "viewer")
    response = await client_for(BOB).post(transcreate_url(campaign), json=TRANSCREATE)
    assert response.status_code == 403
    assert await run_rows() == []


# --- metering and audit -------------------------------------------------------------------


async def test_usage_events_are_stored_and_summed(app: Any) -> None:
    ws = await workspace_of("alice")
    user = dev_user_id("alice")
    first = AiUsage(
        capability="text", provider="google", model="gemini-3.5-flash-lite", prompt_version="atlas.v1",
        input_tokens=1200, output_tokens=300, thinking_tokens=50, estimated_cost_usd=0.0021, latency_ms=840,
        workspace_id=ws, user_id=user,
    )
    await record_ai_usage(first)
    await record_ai_usage(first.model_copy(update={"estimated_cost_usd": 0.004, "capability": "vision"}))
    await record_ai_usage(AiUsage(capability="text", provider="google", model="m", status="error", error_code="RATE_LIMITED"))
    async with read_session() as s:
        rows = (await s.execute(select(m.AiUsageEvent).order_by(m.AiUsageEvent.created_at))).scalars().all()
    assert [r.capability for r in rows] == ["text", "vision", "text"]
    stored = rows[0]
    assert (stored.provider, stored.model, stored.prompt_version) == ("google", "gemini-3.5-flash-lite", "atlas.v1")
    assert (stored.input_tokens, stored.output_tokens, stored.thinking_tokens, stored.latency_ms) == (1200, 300, 50, 840)
    assert stored.status == "ok" and rows[2].status == "error" and rows[2].error_code == "RATE_LIMITED"
    assert round(await spend_usd(workspace_id=ws), 6) == 0.0061
    assert round(await spend_usd(user_id=user), 6) == 0.0061
    assert await spend_usd(workspace_id=uuid4()) == 0.0
    assert await spend_usd(since=utcnow() + timedelta(days=1)) == 0.0


async def test_usage_can_join_the_callers_transaction_and_link_to_a_run(client: httpx.AsyncClient) -> None:
    project, campaign, _ = await demo_setup(client)
    accepted = await start(client, transcreate_url(campaign), TRANSCREATE)
    run_id = UUID(accepted["run_id"])
    await wait_for_run(client, accepted["run_id"])
    async with session() as s, s.begin():
        await record_ai_usage(AiUsage(
            capability="text", provider="google", model="m", estimated_cost_usd=0.01, run_id=run_id,
            project_id=UUID(project["id"]),
        ), s=s)
    assert await spend_usd(run_id=run_id) == 0.01
    # a rolled-back transaction leaves no event behind
    with pytest.raises(RuntimeError):
        async with session() as s, s.begin():
            await record_ai_usage(AiUsage(capability="text", provider="google", model="m", estimated_cost_usd=5, run_id=run_id), s=s)
            raise RuntimeError("provider failed")
    assert await spend_usd(run_id=run_id) == 0.01


async def test_negative_usage_is_refused() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AiUsage(capability="text", provider="p", model="m", input_tokens=-1)
    with pytest.raises(ValidationError):
        AiUsage(capability="text", provider="p", model="m", estimated_cost_usd=-0.1)


async def test_audit_rows_carry_actor_target_and_request(app: Any) -> None:
    ws = await workspace_of("alice")
    async with session() as s, s.begin():
        await record_audit(s, action="workspace.create", target_type="workspace", target_id=str(ws), workspace_id=ws,
                           actor_user_id=dev_user_id("alice"), detail={"kind": "personal"})
        await record_audit(s, action="system.sweep", target_type="runs")
    async with read_session() as s:
        rows = (await s.execute(select(m.AuditLog).order_by(m.AuditLog.created_at))).scalars().all()
        assert await s.scalar(select(func.count(m.AuditLog.id))) == 2
    assert (rows[0].action, rows[0].target_id, rows[0].actor_user_id, rows[0].detail) == (
        "workspace.create", str(ws), dev_user_id("alice"), {"kind": "personal"})
    assert rows[1].actor_user_id is None and rows[1].workspace_id is None  # the system acting
