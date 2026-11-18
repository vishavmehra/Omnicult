"""The Launch Room delivery features on the Aamod demo journey: `delivery_demo.seed_launch_delivery` populates the three tabs
through the real services, with no provider and no network, and never touches a live project."""

import io
import json
import zipfile
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.core.auth import dev_user_id
from app.core.errors import Conflict
from app.services import delivery_demo
from tests.api.delivery_support import TN, add_version, campaign_of
from tests.api.omnicult_support import API, seeded  # noqa: F401
from tests.api.test_demo_aamod import aamod, no_network  # noqa: F401


async def test_the_hook_populates_review_links_the_region_plan_and_the_asset_pack(aamod: httpx.AsyncClient) -> None:
    client = aamod
    project = (await client.post(f"{API}/projects/demo")).json()
    campaign_id = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]["id"]
    base = f"{API}/campaigns/{campaign_id}"
    with no_network():
        first = await delivery_demo.seed_launch_delivery(dev_user_id("alice"), UUID(campaign_id))
        again = await delivery_demo.seed_launch_delivery(dev_user_id("alice"), UUID(campaign_id))
        assert first == {"rights_confirmed": 6, "approvals": 2, "review_links": 1, "review_responses": 2}
        assert again == {"rights_confirmed": 0, "approvals": 0, "review_links": 0, "review_responses": 0}

        plan = (await client.get(f"{base}/region-plan")).json()
        states = {r["region_code"]: (r["ready"]["state"], r["version"]["state"], r["pack_available"]) for r in plan["regions"]}
        assert states == {"IN-MH": ("not_ready", "candidate", False), "IN-TN": ("ready", "approved", True),
                          "IN-KL": ("not_ready", "candidate", False), "IN-WB": ("ready", "approved", True)}
        assert plan["mode"] == "demo" and plan["budget_sample"] is True and plan["source_line"].startswith("Source: demo fixtures")
        mh = next(r for r in plan["regions"] if r["region_code"] == "IN-MH")
        assert [e["title"] for e in mh["timeline"] if e["kind"] == "key_moment"][:2] == ["Dhanteras", "Narak Chaturdashi"]
        assert {c["id"]: c["status"] for c in mh["checklist"]}["creatives"] == "done"
        kl = next(r for r in plan["regions"] if r["region_code"] == "IN-KL")
        assert kl["feedback"]["counts"]["request_changes"] == 1 and any("asked for changes" in w for w in kl["warnings"])

        blocked = (await client.get(f"{base}/asset-packs/preview", params={"region_code": "IN-MH"})).json()
        assert blocked["can_build"] is False
        pack = await client.post(f"{base}/asset-packs", json={"region_code": TN})
        assert pack.status_code == 201, pack.text
        zf = zipfile.ZipFile(io.BytesIO((await client.get(pack.json()["download_url"])).content))
        names = zf.namelist()
        assert sum(n.startswith("brand-kit/logo-") for n in names) == 4 and "brand-kit/brand-kit.json" in names and "manifest.json" in names
        assert any(n.startswith("captions/") and n.endswith(".srt") for n in names) and any(n.startswith("copy/") and n.endswith(".json") for n in names)
        assert not any(n.startswith("creatives/") for n in names), "the Maharashtra film and key visual are not Tamil Nadu's files"
        manifest = json.loads(zf.read("manifest.json"))
        assert {x["label"] for x in manifest["excluded"] if x["kind"] == "creative"} == {"Maharashtra film (Marathi), 29 s", "Maharashtra key visual (Marathi), feed post"}
        assert manifest["mode"] == "demo" and manifest["approval"]["verdict_at_decision"] == "go" and manifest["approval"]["overrides_recommendation"] is False

        links = (await client.get(f"{base}/review-links")).json()
        assert links["total"] == 1 and links["items"][0]["response_count"] == 2 and links["items"][0]["mode"] == "demo"
        assert links["items"][0]["decisions"] == {"approve": 1, "request_changes": 1, "reject": 0, "comment": 0}
        responses = (await client.get(f"{base}/review-responses")).json()["items"]
        assert {r["reviewer_kind"] for r in responses} == {"named", "anonymous"}
        assert (await client.get(f"{base}/approvals")).json()["total"] == 2


async def test_the_hook_refuses_a_live_project(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await add_version(c)
    with pytest.raises(Conflict):
        await delivery_demo.seed_launch_delivery(dev_user_id("alice"), c["cid"])
