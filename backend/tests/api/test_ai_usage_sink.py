"""Every gateway call is stored in `ai_usage_events` (the database sink the app installs at startup), with workspace,
project, campaign, user and run where known, failed attempts included; and the synchronous Tweak Chips call is
limited per user and per workspace. Fake providers and fake Gen AI clients only: no network, no paid call."""

import asyncio
import json
import sys
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.core.auth import dev_user_id
from app.core.config import get_settings
from app.db import models as m
from app.db.session import read_session
from app.fixtures.demo_studio import RESPONDERS as STUDIO_RESPONDERS
from app.llm.budget import UsageContext, UsageEvent, usage_scope
from app.llm.fixture import FixtureLLMProvider
from app.llm.gateway import Completion, LLMError, LLMGateway, ProviderError
from app.schemas.common import Usage
from app.db.base import utcnow
from app.services import metering, studio_context
from app.services.metering import AiUsage, DbUsageSink, record_ai_usage, spend_usd
from tests.api import fake_workflows
from tests.api.omnicult_support import draft, put_claims, seeded, source, workspace_of  # noqa: F401
from tests.api.test_crud import make_campaign, make_project
from tests.api.test_runs import demo_setup, discovery_body, start
from tests.api.test_studio_ai import FESTIVAL, demo_studio
from tests.api.test_demo_journey import offline  # noqa: F401  (blocks outbound HTTP and subprocesses)
from tests.conftest import wait_for_run
from tests.unit.llm.genai_fakes import FakeClient, api_error, embedding_reply, reply, settings as genai_settings
from google.genai import types

API = "/api/v1"
ELEMENTS = [{"id": "cta", "kind": "cta", "value": "Shop now", "language": "en", "script": "Latn"}]


@pytest.fixture(autouse=True)
def no_network(offline: Any) -> Any:  # noqa: F811
    return offline


class Ping(BaseModel):
    ok: bool


class Scripted(FixtureLLMProvider):
    """A provider that is not the demo fixture, reports token usage, and can be held open or made to fail."""

    name = "scripted"

    def __init__(self, responders: dict[str, Callable], *, output_tokens: int = 20) -> None:
        super().__init__(responders)
        self.output_tokens, self.gate, self.started, self.error = output_tokens, None, asyncio.Event(), None

    async def complete(self, request: Any) -> Completion:
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        done = await super().complete(request)
        return Completion(text=done.text, usage=Usage(input_tokens=10, output_tokens=self.output_tokens, total_tokens=10 + self.output_tokens))


def use_provider(monkeypatch: pytest.MonkeyPatch, provider: Scripted) -> None:
    """Live projects use `provider` for Tweak Chips (a real LLMGateway over it: metering, budgets, validation)."""
    monkeypatch.setattr(studio_context, "gateway_for", lambda mode: LLMGateway(get_settings(), provider=provider, backoff_seconds=0))


async def live_studio(client: httpx.AsyncClient) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """A live project and campaign with a root version and one festival claim for IN-MH."""
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    await put_claims(await workspace_of("alice"), [
        draft("Diwali", region="IN-MH", category="festival", sources=[source("wikimedia")], text=FESTIVAL)], mode="live")
    root = (await client.post(f"{API}/campaigns/{campaign['id']}/versions",
                              json={"elements": ELEMENTS, "region_code": "IN-MH", "language": "en"})).json()
    return project, campaign, root


def chips_url(campaign: dict[str, Any]) -> str:
    return f"{API}/campaigns/{campaign['id']}/chips/generate"


def chips_body(root: dict[str, Any]) -> dict[str, Any]:
    return {"version_id": root["id"], "element_id": "cta", "region_code": "IN-MH"}


async def events(**where: Any) -> list[m.AiUsageEvent]:
    async with read_session() as s:
        stmt = select(m.AiUsageEvent).order_by(m.AiUsageEvent.created_at, m.AiUsageEvent.id)
        for name, value in where.items():
            stmt = stmt.where(getattr(m.AiUsageEvent, name) == value)
        return list((await s.execute(stmt)).scalars())


# --- a synchronous call ------------------------------------------------------------------------------------------------


async def test_a_synchronous_call_is_recorded_with_workspace_project_campaign_and_user(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    use_provider(monkeypatch, Scripted(STUDIO_RESPONDERS))
    project, campaign, root = await live_studio(client)
    response = await client.post(chips_url(campaign), json=chips_body(root))
    assert response.status_code == 201, response.text
    (row,) = await events(campaign_id=UUID(campaign["id"]))
    assert (row.capability, row.provider, row.prompt_version, row.status, row.error_code) == ("chat", "google", "tweak-chips-v1", "ok", None)
    assert (row.input_tokens, row.output_tokens) == (10, 20) and row.estimated_cost_usd > 0 and row.latency_ms is not None
    assert row.workspace_id == await workspace_of("alice") and row.project_id == UUID(project["id"])
    assert row.user_id == dev_user_id("alice") and row.run_id is None


# --- a run -------------------------------------------------------------------------------------------------------------


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> fake_workflows.FakeWorkflows:
    return fake_workflows.install(monkeypatch)


def call_the_gateway_first(monkeypatch: pytest.MonkeyPatch, provider: Scripted, calls: int = 1) -> list[Any]:
    """The fake discovery workflow first makes `calls` real gateway calls; their outcomes (value or LLMError) are returned."""
    package = sys.modules["app.workflows"]
    original, outcomes = package.run_discovery, []

    async def with_model_calls(inp: Any, deps: Any, progress: Any) -> Any:
        gateway = LLMGateway(get_settings(), provider=provider, backoff_seconds=0)
        for _ in range(calls):
            try:
                outcomes.append((await gateway.generate_structured(
                    task="extraction", stage="resolving_references", agent="test", system="s", user="u", schema=Ping,
                    prompt_version="ping-v1")).value)
            except LLMError as exc:
                outcomes.append(exc)
        return await original(inp, deps, progress)

    monkeypatch.setattr(package, "run_discovery", with_model_calls)
    return outcomes


async def test_a_runs_model_calls_are_recorded_against_the_run(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows, monkeypatch: pytest.MonkeyPatch) -> None:
    call_the_gateway_first(monkeypatch, Scripted({"ping-v1": lambda ctx: {"ok": True}}), calls=2)
    project, campaign, _ = await demo_setup(client)
    accepted = await start(client, f"{API}/projects/{project['id']}/discoveries", discovery_body(campaign["id"]))
    await wait_for_run(client, accepted["run_id"])
    rows = await events(run_id=UUID(accepted["run_id"]))
    assert [(r.capability, r.prompt_version, r.status) for r in rows] == [("chat", "ping-v1", "ok")] * 2
    assert {r.workspace_id for r in rows} == {await workspace_of("alice")} and {r.project_id for r in rows} == {UUID(project["id"])}
    assert {r.campaign_id for r in rows} == {UUID(campaign["id"])} and {r.user_id for r in rows} == {dev_user_id("alice")}
    assert round(await spend_usd(run_id=UUID(accepted["run_id"])), 8) == round(sum(r.estimated_cost_usd for r in rows), 8) > 0
    history = (await client.get(f"{API}/runs/{accepted['run_id']}/history")).json()
    assert history["cost_basis"] == "usage_events" and history["ai_calls"] == 2 and history["failed_ai_calls"] == 0


async def test_the_run_budget_reads_spend_back_from_the_usage_table(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows, monkeypatch: pytest.MonkeyPatch) -> None:
    # one call reports two million output tokens (about $5, over the $0.50 run budget): the run's next call is refused
    outcomes = call_the_gateway_first(monkeypatch, Scripted({"ping-v1": lambda ctx: {"ok": True}}, output_tokens=2_000_000), calls=2)
    project, campaign, _ = await demo_setup(client)
    accepted = await start(client, f"{API}/projects/{project['id']}/discoveries", discovery_body(campaign["id"]))
    await wait_for_run(client, accepted["run_id"])
    assert isinstance(outcomes[0], Ping) and isinstance(outcomes[1], LLMError) and outcomes[1].code == "BUDGET_EXCEEDED"
    assert "AI_RUN_BUDGET_USD" in outcomes[1].message
    assert len(await events(run_id=UUID(accepted["run_id"]))) == 1  # a refused call never reached the provider, so no attempt


# --- capability calls ----------------------------------------------------------------------------------------------------


async def test_capability_calls_are_recorded_and_a_provider_failure_is_still_an_attempt(seeded: Any, client: httpx.AsyncClient) -> None:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    where = UsageContext(workspace_id=await workspace_of("alice"), project_id=UUID(project["id"]),
                         campaign_id=UUID(campaign["id"]), user_id=dev_user_id("alice"))
    speech = json.dumps({"segments": [{"start": "0:00", "end": "0:02", "text": "hello"}], "music_mood": None})
    seen = json.dumps({"observations": [{"kind": "object", "description": "a lamp", "location": None}]})
    grounded = types.GroundingMetadata(
        web_search_queries=["pongal"], grounding_chunks=[types.GroundingChunk(web=types.GroundingChunkWeb(uri="https://a.example/x", title="a"))])
    fake = FakeClient(
        generate=[reply(speech, prompt=500, out=40), api_error(503), api_error(503), api_error(503), reply(seen, prompt=700, out=30),
                  reply("Pongal is in January.", prompt=90, out=20, grounding=grounded)],
        embed=[embedding_reply([[0.1, 0.2, 0.3]], tokens=7)])
    gateway = LLMGateway(genai_settings(), client=fake, backoff_seconds=0)
    with usage_scope(where):
        heard = await gateway.capability("transcribe").transcribe(b"RIFFwav", "audio/wav", language="mr", duration_ms=9000, stage="t", agent="a")
        failed = await gateway.capability("vision").observe(UUID(project["id"]), b"\x89PNG0", "image/png")  # 503 three times
        saw = await gateway.capability("vision").observe(UUID(project["id"]), b"\x89PNG0", "image/png")
        await gateway.capability("grounded_research").research("When is Pongal?")
        await gateway.capability("embeddings").embed(["a lamp"])
    assert heard.status.status == "transcribed" and failed.status.status == "failed" and saw.status.status == "analyzed"
    rows = await events(campaign_id=UUID(campaign["id"]))
    assert [(r.capability, r.status, r.error_code) for r in rows] == [
        ("transcribe", "ok", None), ("vision", "error", "PROVIDER_ERROR"), ("vision", "error", "PROVIDER_ERROR"),
        ("vision", "error", "PROVIDER_ERROR"), ("vision", "ok", None), ("grounded_research", "ok", None), ("embeddings", "ok", None)]
    assert {(r.workspace_id, r.project_id, r.user_id, r.provider) for r in rows} == {
        (where.workspace_id, where.project_id, where.user_id, "google")} and {r.run_id for r in rows} == {None}
    transcribe, *_, search, embedding = rows
    assert (transcribe.model, transcribe.prompt_version, transcribe.input_tokens, transcribe.output_tokens) == ("gemini-3.8-flash", "transcribe-v1", 500, 40)
    assert all(r.estimated_cost_usd == 0 and r.input_tokens == 0 for r in rows[1:4])  # failed attempts bill nothing
    assert search.estimated_cost_usd >= 0.014  # the grounding fee is inside the stored cost
    assert embedding.model == "gemini-embedding-2" and embedding.input_tokens == 7 and embedding.estimated_cost_usd > 0


async def test_an_unattributed_call_is_still_recorded(seeded: Any, client: httpx.AsyncClient) -> None:
    gateway = LLMGateway(get_settings(), provider=Scripted({"ping-v1": lambda ctx: {"ok": True}}), backoff_seconds=0)
    await gateway.generate_structured(task="extraction", stage="s", agent="a", system="s", user="u", schema=Ping, prompt_version="ping-v1")
    (row,) = await events()
    assert (row.capability, row.workspace_id, row.project_id, row.campaign_id, row.user_id, row.run_id) == ("chat", None, None, None, None, None)


async def test_a_chat_provider_failure_is_recorded_for_every_attempt(seeded: Any, client: httpx.AsyncClient) -> None:
    provider = Scripted({})
    provider.error = ProviderError("HTTP 503", transient=True)
    gateway = LLMGateway(get_settings(), provider=provider, backoff_seconds=0)
    with pytest.raises(LLMError) as caught:
        await gateway.generate_structured(task="creative_adaptation", stage="s", agent="a", system="s", user="u", schema=Ping, prompt_version="ping-v1")
    assert caught.value.code == "PROVIDER_ERROR"
    rows = await events()
    assert len(rows) == 3  # the first request plus LLM_MAX_RETRIES (this task has one model in its chain)
    assert {(r.status, r.error_code, r.estimated_cost_usd) for r in rows} == {("error", "PROVIDER_ERROR", 0.0)}


# --- limits on the synchronous call -------------------------------------------------------------------------------------


async def test_a_workspace_over_its_daily_budget_gets_429_naming_the_limit_before_any_model_call(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = Scripted(STUDIO_RESPONDERS)
    use_provider(monkeypatch, provider)
    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "1.00")
    get_settings.cache_clear()
    _, campaign, root = await live_studio(client)
    await record_ai_usage(AiUsage(capability="chat", provider="google", model="gemini-3.8-flash", estimated_cost_usd=1.5,
                                  workspace_id=await workspace_of("alice")))
    response = await client.post(chips_url(campaign), json=chips_body(root))
    error = response.json()["error"]
    assert response.status_code == 429 and error["code"] == "RATE_LIMITED"
    assert "AI_DAILY_BUDGET_USD" in error["message"] and "$1.00" in error["message"] and "$1.50" in error["message"]
    assert not provider.started.is_set() and (await client.get(f"{API}/campaigns/{campaign['id']}/chips")).json()["total"] == 0
    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "2.00")  # a ceiling above the spend lets the call through
    get_settings.cache_clear()
    assert (await client.post(chips_url(campaign), json=chips_body(root))).status_code == 201


async def test_the_gateways_own_daily_ceiling_also_answers_429_naming_the_setting(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    use_provider(monkeypatch, Scripted(STUDIO_RESPONDERS))
    _, campaign, root = await live_studio(client)
    await record_ai_usage(AiUsage(capability="chat", provider="google", model="gemini-3.8-flash", estimated_cost_usd=10.0,
                                  workspace_id=await workspace_of("bob")))  # another workspace spent the day's budget (default $5)
    response = await client.post(chips_url(campaign), json=chips_body(root))
    error = response.json()["error"]
    assert response.status_code == 429 and error["code"] == "BUDGET_EXCEEDED" and "AI_DAILY_BUDGET_USD" in error["message"]


async def test_a_user_with_too_many_synchronous_requests_in_flight_gets_429_and_is_released_afterwards(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = Scripted(STUDIO_RESPONDERS)
    provider.gate = asyncio.Event()
    use_provider(monkeypatch, provider)
    monkeypatch.setenv("MAX_ACTIVE_RUNS_PER_USER", "1")
    get_settings.cache_clear()
    _, campaign, root = await live_studio(client)
    first = asyncio.create_task(client.post(chips_url(campaign), json=chips_body(root)))
    await asyncio.wait_for(provider.started.wait(), 10)  # the first request is inside the model call
    second = await client.post(chips_url(campaign), json=chips_body(root))
    error = second.json()["error"]
    assert second.status_code == 429 and error["code"] == "RATE_LIMITED"
    assert "MAX_ACTIVE_RUNS_PER_USER" in error["message"] and "limit 1" in error["message"]
    provider.gate.set()
    assert (await first).status_code == 201
    assert (await client.post(chips_url(campaign), json=chips_body(root))).status_code == 201  # the slot was released


async def test_a_failed_call_releases_the_users_slot(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = Scripted(STUDIO_RESPONDERS)
    provider.error = ProviderError("rejected", transient=False)
    use_provider(monkeypatch, provider)
    monkeypatch.setenv("MAX_ACTIVE_RUNS_PER_USER", "1")
    get_settings.cache_clear()
    _, campaign, root = await live_studio(client)
    for _ in range(2):  # a 1-slot limit would answer 429 on the second try if the failed first call kept its slot
        assert (await client.post(chips_url(campaign), json=chips_body(root))).status_code == 502
    provider.error = None
    assert (await client.post(chips_url(campaign), json=chips_body(root))).status_code == 201


async def test_demo_projects_are_not_limited_because_they_call_no_provider(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "0.01")
    monkeypatch.setenv("MAX_ACTIVE_RUNS_PER_USER", "1")
    get_settings.cache_clear()
    await record_ai_usage(AiUsage(capability="chat", provider="google", model="m", estimated_cost_usd=5.0, workspace_id=await workspace_of("alice")))
    cid, root = await demo_studio(client)
    response = await client.post(chips_url({"id": cid}), json=chips_body(root))
    assert response.status_code == 201, response.text
    assert await events(campaign_id=UUID(cid)) == []  # fixtures record no usage


async def test_the_sink_ignores_run_scopes_that_are_not_run_rows_and_a_failing_spend_query_reads_as_zero(seeded: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    sink = DbUsageSink()
    await sink.record(UsageEvent(timestamp=utcnow(), capability="chat", provider="google", model="m", status="ok", run_id="run-1",
                                 estimated_cost_usd=0.25, input_tokens=None, output_tokens=None))
    (row,) = await events()
    assert (row.run_id, row.estimated_cost_usd, row.input_tokens, row.output_tokens, row.thinking_tokens) == (None, 0.25, 0, 0, 0)
    assert await sink.spent_usd(run_id="run-1") == 0.0 and await sink.spent_usd(run_id=str(uuid4())) == 0.0
    assert round(await sink.spent_usd(), 2) == 0.25

    def locked() -> Any:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(metering, "read_session", locked)  # metering never fails the call it measures
    assert await sink.spent_usd() == 0.0
