"""ASSET_STORAGE_BACKEND=database: asset bytes live in a table, behind the owner's access check."""

import httpx
from sqlalchemy import func, select

from app.db import models as m
from app.db.session import read_session
from tests.api.test_crud import make_project
from tests.conftest import BOB

API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + bytes(64)


async def upload(client: httpx.AsyncClient, project_id: str, **kwargs: object) -> httpx.Response:
    return await client.post(f"{API}/projects/{project_id}/assets", data={"kind": "image"},
                             files={"file": ("../../photo.png", PNG, "image/png")}, **kwargs)  # type: ignore[arg-type]


async def rows() -> tuple[list[tuple[str, object]], int]:
    """(storage_name, owner) per asset, and the number of database blobs."""
    async with read_session() as s:
        assets = (await s.execute(select(m.Asset.storage_name, m.Project.owner_id)
                                  .join(m.Project, m.Project.id == m.Asset.project_id))).all()
        return [tuple(a) for a in assets], int(await s.scalar(select(func.count()).select_from(m.AssetBlob)) or 0)


async def test_database_backend_round_trip_and_isolation(client: httpx.AsyncClient) -> None:
    project = await make_project(client)
    asset = (await upload(client, project["id"])).json()
    content = await client.get(asset["content_url"])
    assert content.status_code == 200 and content.content == PNG
    assert content.headers["content-type"] == "image/png" and content.headers["x-content-type-options"] == "nosniff"
    (key, owner), = (await rows())[0]
    assert key == f"{owner}/{asset['id']}" and (await rows())[1] == 1
    assert (await client.get(f"{API}/assets/{asset['id']}", headers=BOB)).status_code == 404
    assert (await client.get(asset["content_url"], headers=BOB)).status_code == 404
