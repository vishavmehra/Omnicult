"""A demo project with a text-only root version, and a way to start a (demo, fixture-model) transcreate run on it.

Run-engine tests (idempotency, limits, leases, metering) use this run: it needs no claims, glossary or media."""

from typing import Any

import httpx

API = "/api/v1"
ELEMENTS = [{"id": "cta", "kind": "cta", "value": "Shop now", "language": "en", "script": "Latn"}]
TRANSCREATE = {"region_code": "IN-MH", "language": "mr", "element_ids": ["cta"]}


async def demo_setup(client: httpx.AsyncClient, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """(project, campaign, root version) of a fresh demo project."""
    project = (await client.post(f"{API}/projects/demo", **kwargs)).json()
    campaign = (await client.get(f"{API}/projects/{project['id']}/campaigns", **kwargs)).json()["items"][0]
    root = (await client.post(
        f"{API}/campaigns/{campaign['id']}/versions",
        json={"elements": ELEMENTS, "region_code": "IN-MH", "language": "en"}, **kwargs,
    )).json()
    return project, campaign, root


def transcreate_url(campaign: dict[str, Any]) -> str:
    return f"{API}/campaigns/{campaign['id']}/transcreate"


async def start(client: httpx.AsyncClient, url: str, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    response = await client.post(url, json=body, **kwargs)
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["status"] == "queued" and accepted["status_url"] == f"{API}/runs/{accepted['run_id']}"
    return accepted
