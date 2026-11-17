"""ASSET_STORAGE_BACKEND=gcs (a fake google-cloud-storage client; no network) and =local (a temporary directory)."""

import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from google.api_core import exceptions as gexc
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.db import blobs
from app.db import models as m
from app.db.session import read_session
from tests.api.test_crud import make_project
from tests.conftest import BOB

API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + bytes(64)
BUCKET = "test-bucket"
PROVIDER_DETAIL = "upstream detail that must never reach a client"


class FakeBlob:
    def __init__(self, gcs: "FakeGcs", key: str) -> None:
        self.gcs, self.key = gcs, key

    def _enter(self, call: str, timeout: Any) -> None:
        self.gcs.calls.append((call, self.key))
        assert timeout == blobs.GCS_TIMEOUT  # every call is bounded
        if self.gcs.fail:
            raise self.gcs.fail.pop(0)(PROVIDER_DETAIL)

    def upload_from_string(self, data: bytes, content_type: str, if_generation_match: int, timeout: Any) -> None:
        self._enter("upload", timeout)
        if if_generation_match == 0 and self.key in self.gcs.objects:
            raise gexc.PreconditionFailed(PROVIDER_DETAIL)
        self.gcs.objects[self.key] = data
        self.gcs.content_types[self.key] = content_type

    def download_as_bytes(self, timeout: Any) -> bytes:
        self._enter("download", timeout)
        if self.key not in self.gcs.objects:
            raise gexc.NotFound(PROVIDER_DETAIL)
        return self.gcs.objects[self.key]

    def delete(self, timeout: Any) -> None:
        self._enter("delete", timeout)
        if self.gcs.objects.pop(self.key, None) is None:
            raise gexc.NotFound(PROVIDER_DETAIL)


class FakeGcs:
    """The slice of google.cloud.storage.Client the backend uses; `fail` queues exception types, one per call."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []
        self.buckets: set[str] = set()
        self.fail: list[type[Exception]] = []

    def bucket(self, name: str) -> Any:
        self.buckets.add(name)
        return self

    def blob(self, key: str) -> FakeBlob:
        return FakeBlob(self, key)


def use(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


@pytest.fixture
def gcs(test_settings: None, monkeypatch: pytest.MonkeyPatch) -> FakeGcs:
    fake = FakeGcs()
    use(monkeypatch, ASSET_STORAGE_BACKEND="gcs", GCS_BUCKET=BUCKET)
    monkeypatch.setattr(blobs, "_gcs", fake)
    return fake


async def upload(client: httpx.AsyncClient, project_id: str, **kwargs: Any) -> httpx.Response:
    return await client.post(f"{API}/projects/{project_id}/assets", data={"kind": "image"},
                             files={"file": ("../../photo.png", PNG, "image/png")}, **kwargs)


async def stored() -> tuple[list[tuple[str, object]], int]:
    """(storage_name, owner) per asset row, and the number of database blobs."""
    async with read_session() as s:
        assets = (await s.execute(select(m.Asset.storage_name, m.Project.owner_id)
                                  .join(m.Project, m.Project.id == m.Asset.project_id))).all()
        return [tuple(a) for a in assets], int(await s.scalar(select(func.count()).select_from(m.AssetBlob)) or 0)


async def test_gcs_upload_read_rollback_and_isolation(client: httpx.AsyncClient, gcs: FakeGcs,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    project = await make_project(client)
    response = await upload(client, project["id"])
    assert response.status_code == 201, response.text
    asset = response.json()
    (key, owner), = (await stored())[0]
    assert key == f"{owner}/{asset['id']}" and (await stored())[1] == 0  # no bytes in the database
    assert gcs.objects == {key: PNG} and gcs.content_types[key] == "image/png" and gcs.buckets == {BUCKET}
    assert "photo" not in key  # the object name is server-generated, never the uploaded filename

    content = await client.get(asset["content_url"])
    assert content.status_code == 200 and content.content == PNG and content.headers["cache-control"] == "private, no-store"
    calls = len(gcs.calls)
    assert (await client.get(asset["content_url"], headers=BOB)).status_code == 404
    assert (await upload(client, project["id"], headers=BOB)).status_code == 404
    assert len(gcs.calls) == calls  # ownership is checked before Cloud Storage is called

    gcs.objects.clear()  # the object is gone but the row is not
    missing = await client.get(asset["content_url"])
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"

    def broken(project: m.Project) -> None:
        raise RuntimeError("the asset transaction failed")

    monkeypatch.setattr("app.services.assets.touch", broken)
    assert (await upload(client, project["id"])).status_code == 500
    assert [call for call, _ in gcs.calls[-2:]] == ["upload", "delete"]  # the orphaned object was removed
    assert gcs.objects == {} and len((await stored())[0]) == 1  # rolled back in both places


async def test_gcs_failures_are_mapped_and_quiet(client: httpx.AsyncClient, gcs: FakeGcs,
                                                 caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    project = await make_project(client)

    gcs.fail = [gexc.ServiceUnavailable]
    response = await upload(client, project["id"])
    assert response.status_code == 502 and response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert PROVIDER_DETAIL not in response.text and (await stored())[0] == []

    gcs.fail = [gexc.DeadlineExceeded]
    timed_out = await upload(client, project["id"])
    assert timed_out.status_code == 504 and timed_out.json()["error"]["code"] == "PROVIDER_TIMEOUT"

    gcs.fail = [gexc.Forbidden]
    refused = await upload(client, project["id"])
    assert refused.status_code == 502 and PROVIDER_DETAIL not in refused.text

    logged = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "asset storage unavailable" in logged and PROVIDER_DETAIL not in logged


async def test_gcs_never_overwrites_an_existing_object(gcs: FakeGcs) -> None:
    await blobs.store("owner/asset", b"first", "image/png")
    with pytest.raises(Exception, match="unavailable"):
        await blobs.store("owner/asset", b"second", "image/png")  # if_generation_match=0 refuses the overwrite
    assert gcs.objects["owner/asset"] == b"first"


def test_gcs_backend_fails_fast_without_a_bucket() -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, asset_storage_backend="gcs", gcs_bucket=None)
    assert "GCS_BUCKET" in str(caught.value)
    assert Settings(_env_file=None, asset_storage_backend="gcs", gcs_bucket=BUCKET).gcs_bucket == BUCKET
    assert Settings(_env_file=None, asset_storage_backend="database").gcs_bucket is None


async def test_local_backend_round_trip(client: httpx.AsyncClient, test_settings: None, monkeypatch: pytest.MonkeyPatch,
                                        tmp_path: Path) -> None:
    root = tmp_path / "assets"
    use(monkeypatch, ASSET_STORAGE_BACKEND="local")
    monkeypatch.setattr(blobs, "LOCAL_ROOT", root)
    project = await make_project(client)
    asset = (await upload(client, project["id"])).json()
    (key, _), = (await stored())[0]
    assert (root / key).read_bytes() == PNG and (await stored())[1] == 0
    assert (await client.get(asset["content_url"])).content == PNG
    (root / key).unlink()
    assert (await client.get(asset["content_url"])).status_code == 404

    await blobs.store("a/b", b"x", "image/png")
    await blobs.discard(["a/b", "never/existed"])  # best effort: no error for a missing file
    assert not (root / "a" / "b").exists()
    with pytest.raises(Exception, match="not found"):
        blobs._local_path("../../escape")  # keys that leave the storage root are refused
