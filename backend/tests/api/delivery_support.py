"""Builders for the Launch Room delivery tests: a live campaign with versions, registered creatives and stored files."""

import hashlib
from typing import Any
from uuid import UUID, uuid4

import httpx

from app.core.auth import dev_user_id
from app.db import blobs
from app.db import models as m
from app.db.base import utcnow
from app.db.session import session
from tests.api.launch_support import observations_json
from tests.api.omnicult_support import API
from tests.api.test_crud import make_campaign, make_project

TN, KL, MH = "IN-TN", "IN-KL", "IN-MH"
SECRET_PREFIX = "Review "


async def campaign_of(client: httpx.AsyncClient) -> dict[str, Any]:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    return {"project": project, "pid": UUID(project["id"]), "cid": UUID(campaign["id"]), "id": campaign["id"],
            "workspace_id": project["workspace_id"], "base": f"{API}/campaigns/{campaign['id']}"}


async def add_version(c: dict[str, Any], label: str = "Tamil", region: str | None = TN, language: str | None = "ta",
                      elements: list[dict[str, Any]] | None = None) -> UUID:
    node = m.VersionNode(
        id=uuid4(), campaign_id=c["cid"], project_id=c["pid"], label=label, actor="user", region_code=region, language=language, settings={},
        elements=elements or [
            {"id": "headline", "kind": "headline", "value": f"{label} headline", "language": language},
            {"id": "logo", "kind": "logo", "value": "brand/logo.png"},
            {"id": "cta", "kind": "cta", "value": "Order now"},
        ], created_at=utcnow())
    async with session() as s, s.begin():
        s.add(node)
    return node.id


async def add_asset(c: dict[str, Any], *, filename: str = "visual.png", data: bytes = b"\x89PNG-bytes", kind: str = "image",
                    content_type: str = "image/png", rights: bool = True, recorded_sha: str | None = None, user: str = "alice") -> m.Asset:
    asset_id = uuid4()
    now = utcnow()
    asset = m.Asset(
        id=asset_id, project_id=c["pid"], kind=kind, filename=filename, content_type=content_type, size_bytes=len(data),
        sha256=recorded_sha or hashlib.sha256(data).hexdigest(), storage_name=blobs.object_key(dev_user_id(user), asset_id), created_at=now,
        rights_confirmed=rights, rights_confirmed_at=now if rights else None, width=1080, height=1350)
    async with session() as s, s.begin():
        s.add(asset)
        await s.flush()
        s.add(m.AssetBlob(asset_id=asset_id, project_id=c["pid"], data=data))
    return asset


async def add_creative(c: dict[str, Any], asset: m.Asset, *, label: str, region: str | None, kind: str = "image") -> UUID:
    row = m.CreativeAsset(id=uuid4(), project_id=c["pid"], campaign_id=c["cid"], asset_id=asset.id, kind=kind, label=label, region_code=region,
                          created_at=utcnow(), updated_at=utcnow())
    async with session() as s, s.begin():
        s.add(row)
    return row.id


async def add_scene(c: dict[str, Any], creative_id: UUID, asset: m.Asset, start_ms: int, end_ms: int | None) -> UUID:
    run_id = uuid4()
    scene = m.CreativeScene(id=uuid4(), project_id=c["pid"], creative_asset_id=creative_id, campaign_id=c["cid"], asset_id=asset.id,
                            run_id=run_id, position=0, start_ms=start_ms, end_ms=end_ms, payload={}, created_at=utcnow())
    async with session() as s, s.begin():
        s.add(m.AgentRun(id=run_id, project_id=c["pid"], campaign_id=c["cid"], run_type="creative_xray", status="completed", mode="live",
                         created_at=utcnow()))
        await s.flush()
        s.add(scene)
    return scene.id


async def approve(client: httpx.AsyncClient, c: dict[str, Any], version_id: UUID, region: str = TN, decision: str = "approve") -> dict[str, Any]:
    response = await client.post(f"{c['base']}/approvals", json={"region_code": region, "version_id": str(version_id), "decision": decision,
                                                                 "reason": "Reviewed with the regional lead."})
    assert response.status_code == 201, response.text
    return response.json()


async def compute(client: httpx.AsyncClient, c: dict[str, Any], version_id: UUID, region: str = TN, **changes: Any) -> dict[str, Any]:
    response = await client.post(f"{c['base']}/readiness", json={"region_code": region, "version_id": str(version_id),
                                                                 "observations": observations_json(**changes)})
    assert response.status_code in (200, 201), response.text
    return response.json()


def review_headers(secret: str) -> dict[str, str]:
    """The reviewer's only credential. Authorization is replaced, so a signed-in client's own token is not sent."""
    return {"Authorization": SECRET_PREFIX + secret}
