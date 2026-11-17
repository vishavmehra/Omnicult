"""Shared setup for the Proof Vault tests: a campaign with target regions, claims, conflicts, and runs."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx

from app.db import models as m
from app.db.base import utcnow
from app.db.session import session
from app.services.metering import AiUsage, record_ai_usage
from tests.api.omnicult_support import NOW, draft, put_claims, source, workspace_of
from tests.api.test_crud import make_campaign, make_project

API = "/api/v1"


async def campaign_with_regions(client: httpx.AsyncClient, regions: tuple[str, ...] = ("IN-TN", "IN-KL")) -> dict[str, Any]:
    """A live project and campaign for alice whose target markets name the given regions."""
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    async with session() as s, s.begin():
        row = await s.get(m.Campaign, UUID(campaign["id"]))
        assert row is not None
        row.target_markets = [{"country_code": "IN", "display_name": "India", "region_code": code} for code in regions]
    return {"project": project, "campaign": campaign, "workspace_id": await workspace_of("alice")}


async def tamil_nadu_claims(workspace_id: UUID | None, *, conflict: bool = True) -> None:
    """Claims of several kinds for IN-TN and IN-KL, plus (by default) two that disagree."""
    wikimedia = source("wikimedia")
    gov = source("tn-gov", source_type="curated_reference")
    drafts = [
        draft("Pongal", sources=[wikimedia, gov], text="Pongal is the main harvest festival."),
        draft("Kolam", attribute="signature_symbol", category="symbol", kind="interpretation", sources=[],
              text="Kolam floor patterns are an auspicious symbol."),
        draft(0.8, attribute="literacy", category="demographic", kind="calculated",
              sources=[source("census", source_type="census_2011")], text="Literacy is about 80 percent."),
        draft("Onam", region="IN-KL", sources=[source("kl-gov", source_type="curated_reference")], text="Onam is the main harvest festival."),
    ]
    if conflict:
        drafts += [
            draft(0.89, attribute="language_share", category="language", sources=[source("census", source_type="census_2011")],
                  text="89 percent speak the main language."),
            draft(0.81, attribute="language_share", category="language",
                  sources=[source("wikimedia"), source("survey", source_type="curated_reference")],
                  text="81 percent speak the main language."),
        ]
    await put_claims(workspace_id, drafts)


async def add_run(
    project_id: str, campaign_id: str, *, run_type: str = "market_discovery", status: str = "completed",
    steps: list[dict] | None = None, error: dict | None = None, minutes_ago: int = 5, seconds: int = 12,
) -> UUID:
    started = utcnow() - timedelta(minutes=minutes_ago)
    run_id = uuid4()
    async with session() as s, s.begin():
        s.add(m.AgentRun(
            id=run_id, project_id=UUID(project_id), campaign_id=UUID(campaign_id), run_type=run_type, status=status,
            mode="live", steps=steps or [], error=error, created_at=started, started_at=started,
            completed_at=started + timedelta(seconds=seconds) if status != "running" else None, inputs={"request": {}},
        ))
    return run_id


def step(stage: str = "interpret", *, model: str = "gemini-3.5-flash-lite", prompt: str = "atlas.v1", cost: float | None = 0.002,
         tokens_in: int = 100, tokens_out: int = 50, status: str = "completed", error_code: str | None = None) -> dict:
    usage = {"input_tokens": tokens_in, "output_tokens": tokens_out, "total_tokens": tokens_in + tokens_out, "estimated_cost_usd": cost}
    return {"stage": stage, "agent": "atlas", "status": status, "provider": "google", "model_id": model,
            "prompt_version": prompt, "latency_ms": 800, "retries": 0, "fallback_used": False, "usage": usage,
            "error_code": error_code}


async def add_usage(
    run_id: UUID | None, campaign_id: str, project_id: str, *, cost: float, tokens_in: int = 100, tokens_out: int = 20,
    model: str = "gemini-3.5-flash-lite", prompt: str | None = "atlas.v1", status: str = "ok", error_code: str | None = None,
    capability: str = "text",
) -> None:
    await record_ai_usage(AiUsage(
        capability=capability, provider="google", model=model, prompt_version=prompt, input_tokens=tokens_in,
        output_tokens=tokens_out, estimated_cost_usd=cost, status=status, error_code=error_code, run_id=run_id,
        campaign_id=UUID(campaign_id), project_id=UUID(project_id),
    ))


__all__ = ["API", "NOW", "add_run", "add_usage", "campaign_with_regions", "step", "tamil_nadu_claims"]
