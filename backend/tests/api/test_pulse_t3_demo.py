"""The Aamod demo journey's Live Pulse Tier 3 hook: seeded over the real services, deterministic, idempotent, offline."""

from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import func, select

from app.db import models as m
from app.db.session import read_session
from app.services import pulse_sample as sample
from app.services import pulse_t3_demo
from tests.api.omnicult_support import seeded  # noqa: F401
from tests.api.test_pulse_t3 import V2, Campaign, campaign_of, verdict


async def journey_campaign(client: httpx.AsyncClient) -> tuple[Campaign, UUID]:
    """A campaign with the sample loaded and a stored readiness verdict per region, like the demo journey leaves it."""
    c = await campaign_of(client)
    await verdict(client, c, "IN-MH", 4, 3, "Original")
    for region, understood, positive in (("IN-TN", 9, 8), ("IN-KL", 6, 5), ("IN-WB", 7, 6)):
        await verdict(client, c, region, understood, positive, "Adaptation")
    async with read_session() as s:
        return c, await s.scalar(select(m.Project.owner_id).where(m.Project.id == UUID(c.project["id"])))


async def test_the_hook_links_versions_adds_rules_evaluates_and_stores_a_comparison(client: httpx.AsyncClient, seeded: Any) -> None:
    c, owner = await journey_campaign(client)
    await pulse_t3_demo.seed_pulse_t3(owner, c.uuid)
    board = (await client.get(f"{c.base}/predicted-actual/links")).json()
    assert {(s["region_code"], s["pulse_version"]) for s in board["slots"] if s["version_id"]} == {
        ("IN-MH", sample.ORIGINAL), ("IN-TN", V2), ("IN-KL", V2), ("IN-WB", V2)}
    body = (await client.get(f"{c.base}/predicted-actual")).json()
    assert len(body["pairs"]) == 4 and body["summaries"][0]["pairs"] == 4 and body["unlinked"] == 6
    rules = (await client.get(f"{c.base}/alert-rules")).json()["items"]
    assert [r["alert_type"] for r in rules] == ["ctr_drop", "frequency_fatigue", "cost_spike", "prediction_miss"]
    inbox = (await client.get(f"{c.base}/alert-inbox")).json()
    assert inbox["acknowledged"] == 1 and inbox["open"] >= 3 and len(inbox["evaluations"]) == 1
    acknowledged = next(a for a in inbox["items"] if a["status"] == "acknowledged")
    assert acknowledged["region_code"] == "IN-KL" and acknowledged["alert_type"] == "ctr_drop" and acknowledged["events"][-1]["note"]
    snapshots = (await client.get(f"{c.base}/predicted-actual/snapshots")).json()["items"]
    assert len(snapshots) == 1 and snapshots[0]["matches_current"] is True and snapshots[0]["pair_count"] == 4


async def test_the_hook_is_idempotent(client: httpx.AsyncClient, seeded: Any) -> None:
    c, owner = await journey_campaign(client)
    await pulse_t3_demo.seed_pulse_t3(owner, c.uuid)
    first = (await client.get(f"{c.base}/alert-inbox")).json()
    await pulse_t3_demo.seed_pulse_t3(owner, c.uuid)
    second = (await client.get(f"{c.base}/alert-inbox")).json()
    assert [a["events"] for a in second["items"]] == [a["events"] for a in first["items"]]
    async with read_session() as s:
        assert [await s.scalar(select(func.count()).select_from(t)) for t in (m.PulseVersionLink, m.PulseAlertRule, m.PulseComparisonSnapshot)] == [4, 4, 1]
    assert len(second["evaluations"]) == 2  # the second call evaluates again and finds nothing new
    assert second["evaluations"][0]["opened"] == second["evaluations"][0]["resolved"] == 0
