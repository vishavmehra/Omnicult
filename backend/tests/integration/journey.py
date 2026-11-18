"""Shared request bodies and project helpers for the QA suites (tests/integration and tests/security)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.schemas.campaigns import Campaign, CampaignPage
from app.schemas.projects import Project
from tests.integration._support import API, parse

JAPAN = {"country_code": "JP", "display_name": "Japan"}
SEEDED_BRAND = "Northstar"
SEEDED_CAMPAIGN = "Autumn Launch Campaign"
SEEDED_HEADLINE = "Find your next great escape"

LIVE_PROJECT: dict[str, Any] = {
    "name": "QA Live Project",
    "brand_name": "Trailhead",
    "brand_voice": ["calm", "precise"],
    "protected_terms": ["Trailhead"],
    "prohibited_terms": ["cheap"],
    "target_markets": [JAPAN],
}
LIVE_CAMPAIGN: dict[str, Any] = {
    "name": "Spring Trail Campaign",
    "campaign_type": "advertisement",
    "original_content": {
        "headline": "Trails worth the early start",
        "body": "Trailhead layers for long days outside.",
        "call_to_action": "Shop the range",
        "reference_terms": ["trail running"],
    },
    "objective": "Check clarity before a Japan launch",
    "target_markets": [JAPAN],
}


async def create_live_project(client: httpx.AsyncClient, headers: dict[str, str], **overrides: Any) -> Project:
    response = await client.post(f"{API}/projects", json={**LIVE_PROJECT, **overrides}, headers=headers)
    project = parse(Project, response, 201)
    assert project.mode == "live", "POST /projects creates a live project"
    return project


async def create_live_campaign(
    client: httpx.AsyncClient, headers: dict[str, str], project_id: Any, **overrides: Any
) -> Campaign:
    response = await client.post(
        f"{API}/projects/{project_id}/campaigns", json={**LIVE_CAMPAIGN, **overrides}, headers=headers
    )
    return parse(Campaign, response, 201)


@dataclass
class Journey:
    headers: dict[str, str]
    project: Project
    campaign: Campaign

    @property
    def project_id(self) -> UUID:
        return self.project.id

    @property
    def campaign_id(self) -> UUID:
        return self.campaign.id

    @property
    def version_id(self) -> UUID:
        return self.campaign.current_version.id


async def create_demo(client: httpx.AsyncClient, headers: dict[str, str], *, check: bool = True) -> Journey:
    """POST /projects/demo, then read the seeded campaign."""
    project = parse(Project, await client.post(f"{API}/projects/demo", headers=headers), 201)
    page = parse(CampaignPage, await client.get(f"{API}/projects/{project.id}/campaigns", headers=headers))
    assert page.total >= 1 and page.items, "a demo project must be seeded with its campaign"
    campaign = parse(Campaign, await client.get(f"{API}/campaigns/{page.items[0].id}", headers=headers))
    if check:
        assert project.mode == "demo" and project.status == "active"
        assert project.brand.name == SEEDED_BRAND, f"seeded brand {project.brand.name!r}"
        assert any(m.country_code == "JP" for m in project.target_markets), "seeded market Japan missing"
        assert campaign.project_id == project.id and campaign.name == SEEDED_CAMPAIGN
        assert campaign.current_version.content.headline == SEEDED_HEADLINE
    return Journey(headers=headers, project=project, campaign=campaign)
