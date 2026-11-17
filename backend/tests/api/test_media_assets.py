"""Video and audio uploads over HTTP: sniffing, limits, rights, redaction, status, derived files, signed URLs.

The probe is faked in most tests (they need no ffmpeg); the ones that use the real binaries are marked and skip without them."""

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db import blobs
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.media import ffmpeg
from app.services.media import MediaPipeline
from tests.api.media_support import (
    M4A,
    MKV,
    MOV,
    MP4,
    PNG,
    WAV,
    WEBM,
    fake_probe,
    make_video,
    probe_result,
    requires_ffmpeg,
)
from tests.api.test_asset_storage_gcs import BUCKET, FakeBlob, FakeGcs, use
from tests.api.test_crud import make_project
from tests.conftest import BOB

API = "/api/v1"

async def upload(client: httpx.AsyncClient, project_id: str, kind: str, data: bytes, *, name: str = "file.bin", rights: bool | None = True,
                 sidecar: bytes | None = None, **kwargs: Any) -> httpx.Response:
    form: dict[str, str] = {"kind": kind}
    if rights is not None:
        form["rights_confirmed"] = "true" if rights else "false"
    files: dict[str, Any] = {"file": (name, data, "application/octet-stream")}
    if sidecar is not None:
        files["sidecar"] = ("notes.srt", sidecar, "text/plain")
    return await client.post(f"{API}/projects/{project_id}/assets", files=files, data=form, **kwargs)


async def asset_rows() -> list[m.Asset]:
    async with read_session() as s:
        return list((await s.execute(select(m.Asset).order_by(m.Asset.created_at))).scalars())


async def blob_count() -> int:
    async with read_session() as s:
        return int(await s.scalar(select(func.count()).select_from(m.AssetBlob)) or 0)


@pytest.fixture
async def project(client: httpx.AsyncClient) -> str:
    return (await make_project(client))["id"]


# --- accepted uploads ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "data", "content_type", "probe"),
    [
        ("video", MP4, "video/mp4", probe_result()),
        ("video", MOV, "video/quicktime", probe_result()),
        ("video", WEBM, "video/webm", probe_result()),
        ("audio", WAV, "audio/wav", probe_result(has_video=False)),
        ("audio", M4A, "audio/mp4", probe_result(has_video=False)),
    ],
)
async def test_video_and_audio_are_accepted_with_their_facts(
    client: httpx.AsyncClient, project: str, monkeypatch: pytest.MonkeyPatch, kind: str, data: bytes, content_type: str, probe: Any
) -> None:
    probed = fake_probe(monkeypatch, probe)
    response = await upload(client, project, kind, data, name="../../ad.bin")
    assert response.status_code == 201, response.text
    asset = response.json()
    assert (asset["kind"], asset["content_type"], asset["filename"], asset["size_bytes"]) == (kind, content_type, "ad.bin", len(data))
    assert (asset["upload_status"], asset["processing_status"], asset["rights_confirmed"]) == ("stored", "pending", True)
    assert asset["duration_ms"] == 9000 and asset["parent_asset_id"] is None and asset["derived_role"] is None
    assert (asset["width"], asset["height"]) == ((320, 240) if kind == "video" else (None, None))
    assert probed == [len(data)]
    streamed = await client.get(asset["content_url"])
    assert streamed.status_code == 200 and streamed.content == data and streamed.headers["content-type"] == content_type
    assert streamed.headers["x-content-type-options"] == "nosniff"
    assert (await client.get(f"{API}/assets/{asset['id']}")).json() == asset
    page = (await client.get(f"{API}/projects/{project}/assets", params={"kind": kind})).json()
    assert page["total"] == 1 and page["items"][0]["id"] == asset["id"]


async def test_images_keep_working_and_need_no_processing(client: httpx.AsyncClient, project: str) -> None:
    plain = (await upload(client, project, "image", PNG, rights=None)).json()
    confirmed = (await upload(client, project, "image", PNG, rights=True)).json()
    assert (plain["processing_status"], plain["rights_confirmed"], plain["duration_ms"]) == ("not_required", False, None)
    assert confirmed["rights_confirmed"] is True and confirmed["processing_status"] == "not_required"


# --- rights, sniffing and limits -----------------------------------------------------------------------


async def test_rights_confirmation_is_required_for_video_and_audio(client: httpx.AsyncClient, project: str, monkeypatch: pytest.MonkeyPatch) -> None:
    probed = fake_probe(monkeypatch)
    for rights in (None, False):
        for kind, data in (("video", MP4), ("audio", WAV)):
            response = await upload(client, project, kind, data, rights=rights)
            assert response.status_code == 422, response.text
            error = response.json()["error"]
            assert error["code"] == "VALIDATION_ERROR" and error["details"][0]["field"] == "rights_confirmed"
    assert probed == [] and await asset_rows() == [] and await blob_count() == 0  # refused before anything ran or was stored


REFUSED = {
    "png-as-video": ("video", PNG), "wav-as-video": ("video", WAV), "matroska-as-video": ("video", MKV), "m4a-as-video": ("video", M4A),
    "hls-playlist": ("video", b"#EXTM3U\nhttp://example.com/x.ts\n"), "empty-video": ("video", b""), "png-as-audio": ("audio", PNG),
    "webm-as-audio": ("audio", WEBM), "mov-as-audio": ("audio", MOV), "mp4-as-image": ("image", MP4), "wav-as-image": ("image", WAV),
}


@pytest.mark.parametrize(("kind", "data"), REFUSED.values(), ids=REFUSED.keys())
async def test_the_type_comes_from_the_bytes_and_must_match_the_kind(
    client: httpx.AsyncClient, project: str, monkeypatch: pytest.MonkeyPatch, kind: str, data: bytes
) -> None:
    probed = fake_probe(monkeypatch)
    response = await upload(client, project, kind, data, name="looks-fine.mp4")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert probed == [] and await asset_rows() == [] and await blob_count() == 0


async def test_size_and_duration_limits(client: httpx.AsyncClient, project: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_MEDIA_BYTES", str(len(MP4)))
    get_settings.cache_clear()
    probed = fake_probe(monkeypatch)
    assert (await upload(client, project, "video", MP4)).status_code == 201  # exactly at the limit
    big = await upload(client, project, "video", MP4 + b"\x00")
    assert big.status_code == 422 and "limit" in big.json()["error"]["message"] and probed == [len(MP4)]
    monkeypatch.setenv("MAX_MEDIA_BYTES", str(50 * 1024 * 1024))
    get_settings.cache_clear()
    cases = [
        (probe_result(duration_ms=60_000), 201, None), (probe_result(duration_ms=61_000), 422, "61 seconds long; the limit is 60 seconds"),
        (probe_result(duration_ms=0), 422, "could not be determined, or it is empty"),
        (probe_result(has_video=False), 422, "no video stream"),
    ]
    for result, status, message in cases:
        fake_probe(monkeypatch, result)
        response = await upload(client, project, "video", MP4)
        assert response.status_code == status, response.text
        if message:
            assert message in response.json()["error"]["message"]
    fake_probe(monkeypatch, probe_result(has_video=True))
    audio = await upload(client, project, "audio", WAV)  # an "audio" file that carries video is not audio only
    assert audio.status_code == 422 and "not audio only" in audio.json()["error"]["message"]
    assert len(await asset_rows()) == 2  # the at-limit upload and the 60 s upload; nothing else was stored
    assert await blob_count() == 2


async def test_a_missing_ffprobe_is_a_clear_503_and_images_still_upload(client: httpx.AsyncClient, project: str, monkeypatch: pytest.MonkeyPatch) -> None:
    gone = ffmpeg.Tool("ffprobe", None, None, "ffprobe was not found ('ffprobe'). Install ffmpeg (https://ffmpeg.org/download.html).")
    monkeypatch.setattr(ffmpeg, "_tools", ffmpeg.Tools(ffmpeg.Tool("ffmpeg", None, None, "ffmpeg was not found."), gone))
    response = await upload(client, project, "video", MP4)
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "PROVIDER_NOT_CONFIGURED" and "Video and audio processing is unavailable" in error["message"]
    assert "Install ffmpeg" in error["message"] and await asset_rows() == []
    assert (await upload(client, project, "image", PNG, rights=None)).status_code == 201
    capabilities = (await client.get(f"{API}/media/capabilities")).json()
    assert capabilities["ffmpeg"]["available"] is False and "was not found" in capabilities["ffmpeg"]["message"]
    assert capabilities["limits"] == {"max_image_bytes": 5 * 1024 * 1024, "max_media_bytes": 50 * 1024 * 1024, "max_media_seconds": 60.0}
    assert capabilities["text_shaping"] in ("raqm", "basic") and "Deva" in capabilities["scripts"] and "Latn" in capabilities["scripts"]


# --- privacy: sidecar and metadata ---------------------------------------------------------------------


SRT = b"1\n00:00:00,500 --> 00:00:02,000\nNamaste, write to asha@example.com\n\n2\n00:00:02,500 --> 00:00:04,000\nCall 9876543210\n"


async def test_sidecar_and_container_metadata_are_redacted_before_any_model_can_see_them(
    client: httpx.AsyncClient, project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    tags = {"title": "Diwali Sale", "comment": "shot by ravi@brand.in, call 9123456780", "location": "+19.0760+072.8777/",
            "com.apple.quicktime.model": "iPhone 15"}
    fake_probe(monkeypatch, probe_result(tags=tags))
    response = await upload(client, project, "video", MP4, sidecar=SRT)
    assert response.status_code == 201, response.text
    asset_id = response.json()["id"]
    status = (await client.get(f"{API}/assets/{asset_id}/status")).json()
    assert status["sidecar"] == {"present": True, "format": "srt", "redacted": {"email": 1, "phone": 1}}
    assert status["metadata_redacted"] == {"email": 1, "phone": 1}
    row = next(r for r in await asset_rows() if str(r.id) == asset_id)
    stored = json.dumps(row.media_info)
    for secret in ("asha@", "ravi@", "9876543210", "9123456780", "iPhone", "19.0760"):
        assert secret not in stored  # the raw values are not kept anywhere
    assert row.media_info["tags"]["title"] == "Diwali Sale" and "[email removed]" in row.media_info["tags"]["comment"]
    assert row.media_info["tags_dropped"] == 2 and row.media_info["sidecar"]["segments"][1]["text"] == "Call [phone removed]"


async def test_a_bad_sidecar_is_refused_and_images_take_none(client: httpx.AsyncClient, project: str, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_probe(monkeypatch)
    for bad in (b"\xff\xfe\x00binary", b"   ", b"x" * (200 * 1024 + 1)):
        response = await upload(client, project, "video", MP4, sidecar=bad)
        assert response.status_code == 422 and response.json()["error"]["details"][0]["field"] == "sidecar", response.text
    on_image = await upload(client, project, "image", PNG, sidecar=SRT)
    assert on_image.status_code == 422 and on_image.json()["error"]["details"][0]["field"] == "sidecar"
    assert await asset_rows() == [] and await blob_count() == 0


# --- status, derived files, URLs, access ---------------------------------------------------------------


async def test_status_lists_derived_files_and_the_lists_hide_them(client: httpx.AsyncClient, project: str, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_probe(monkeypatch)
    video = (await upload(client, project, "video", MP4)).json()
    parent_id = UUID(video["id"])
    async with session() as s, s.begin():
        for role, at_ms, kind, ctype in (("keyframe", 300, "image", "image/jpeg"), ("thumbnail", None, "image", "image/jpeg"), ("audio_track", None, "audio", "audio/wav")):
            row = m.Asset(project_id=UUID(project), kind=kind, filename=f"{role}.bin", content_type=ctype, size_bytes=3, sha256="0" * 64,
                          storage_name=f"x/{role}-{parent_id}", created_at=utcnow(), parent_asset_id=parent_id, derived_role=role, derived_at_ms=at_ms)
            s.add(row)
            await s.flush()
            s.add(m.AssetBlob(asset_id=row.id, project_id=row.project_id, data=b"abc"))
    status = (await client.get(f"{API}/assets/{video['id']}/status")).json()
    assert {d["role"] for d in status["derived"]} == {"keyframe", "thumbnail", "audio_track"}
    assert all(d["content_url"].endswith(f"/assets/{d['id']}/content") for d in status["derived"])
    assert (await client.get(f"{API}/projects/{project}/assets")).json()["total"] == 1  # only the upload
    everything = (await client.get(f"{API}/projects/{project}/assets", params={"include_derived": "true"})).json()
    assert everything["total"] == 4
    derived = next(a for a in everything["items"] if a["derived_role"] == "keyframe")
    assert derived["parent_asset_id"] == video["id"] and derived["derived_at_ms"] == 300


async def test_other_workspaces_get_404_for_every_media_endpoint(client: httpx.AsyncClient, project: str, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_probe(monkeypatch)
    video = (await upload(client, project, "video", MP4)).json()
    for request in (
        client.get(f"{API}/assets/{video['id']}/status", headers=BOB), client.get(f"{API}/assets/{video['id']}/url", headers=BOB),
        client.get(f"{API}/assets/{video['id']}/content", headers=BOB), upload(client, project, "video", MP4, headers=BOB),
        client.post(f"{API}/projects/{project}/media/render-text", headers=BOB,
                    json={"width": 100, "height": 100, "boxes": [{"text": "x", "script": "Latn", "bbox": [0, 0, 1, 1]}]}),
    ):
        response = await request
        assert response.status_code == 404, response.text
    assert (await client.get(f"{API}/assets/{video['id']}/status")).status_code == 200  # the owner still can


async def test_the_url_endpoint_streams_for_database_storage(client: httpx.AsyncClient, project: str) -> None:
    asset = (await upload(client, project, "image", PNG, rights=None)).json()
    url = (await client.get(f"{API}/assets/{asset['id']}/url")).json()
    assert url == {"asset_id": asset["id"], "kind": "stream", "url": asset["content_url"], "expires_at": None}


class SigningBlob(FakeBlob):
    def generate_signed_url(self, **kwargs: Any) -> str:
        self.gcs.signed.append((self.key, kwargs))
        if self.gcs.sign_fails:
            raise RuntimeError("no signing credentials, and a secret detail")
        return f"https://storage.example.test/{BUCKET}/{self.key}?X-Goog-Signature=abc"


class SigningGcs(FakeGcs):
    def __init__(self) -> None:
        super().__init__()
        self.signed: list[tuple[str, dict]] = []
        self.sign_fails = False

    def blob(self, key: str) -> SigningBlob:
        return SigningBlob(self, key)


async def test_the_url_endpoint_signs_for_cloud_storage_and_falls_back_to_the_stream(
    client: httpx.AsyncClient, test_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = SigningGcs()
    use(monkeypatch, ASSET_STORAGE_BACKEND="gcs", GCS_BUCKET=BUCKET, MEDIA_SIGNED_URL_SECONDS="300")
    monkeypatch.setattr(blobs, "_gcs", fake)
    project_id = (await make_project(client))["id"]
    asset = (await upload(client, project_id, "image", PNG, rights=None)).json()
    before = utcnow()
    signed = (await client.get(f"{API}/assets/{asset['id']}/url")).json()
    (key, kwargs), = fake.signed
    assert signed["kind"] == "signed" and signed["url"] == f"https://storage.example.test/{BUCKET}/{key}?X-Goog-Signature=abc"
    assert kwargs["version"] == "v4" and kwargs["method"] == "GET" and kwargs["expiration"] == timedelta(seconds=300)
    assert kwargs["response_type"] == "image/png" and kwargs["response_disposition"] == "inline"
    expires = datetime.fromisoformat(signed["expires_at"])
    assert before + timedelta(seconds=290) < expires < before + timedelta(seconds=320)
    calls = len(fake.signed)
    assert (await client.get(f"{API}/assets/{asset['id']}/url", headers=BOB)).status_code == 404
    assert len(fake.signed) == calls  # ownership is checked before anything is signed
    fake.sign_fails = True  # Cloud Run without signing permission: the stream endpoint still works
    fallback = (await client.get(f"{API}/assets/{asset['id']}/url")).json()
    assert fallback["kind"] == "stream" and fallback["url"] == asset["content_url"] and "secret" not in json.dumps(fallback)


# --- the real binaries ---------------------------------------------------------------------------------


@requires_ffmpeg
async def test_real_upload_probe_and_processing_store_derived_files_once(client: httpx.AsyncClient, project: str, tmp_path: Any) -> None:
    ffmpeg.detect_tools(force=True)
    video = make_video(tmp_path / "ad.mp4", scenes=3, seconds_each=3).read_bytes()
    response = await upload(client, project, "video", video, name="ad.mp4")
    assert response.status_code == 201, response.text
    asset = response.json()
    assert abs(asset["duration_ms"] - 9000) < 200 and (asset["width"], asset["height"]) == (320, 240)
    assert asset["processing_status"] == "pending"

    prepared = await MediaPipeline().extract(UUID(asset["id"]))
    assert prepared.probe.has_audio and prepared.audio is not None and prepared.audio.data[:4] == b"RIFF"
    times = [f.timestamp_ms for f in prepared.frames]
    assert times[0] == 300 and len(times) >= 3 and times == sorted(times)
    assert any(abs(t - 3000) < 200 for t in times) and any(abs(t - 6000) < 200 for t in times)  # the scene changes
    assert all(b - a <= 4000 for a, b in zip(times, times[1:])) and all(f.data[:3] == b"\xff\xd8\xff" for f in prepared.frames)

    status = (await client.get(f"{API}/assets/{asset['id']}/status")).json()
    assert status["processing_status"] == "ready" and status["processing_error"] is None
    roles = [d["role"] for d in status["derived"]]
    assert roles.count("keyframe") == len(times) and roles.count("thumbnail") == 1 and roles.count("audio_track") == 1
    keyframe = next(d for d in status["derived"] if d["role"] == "keyframe")
    shown = await client.get(keyframe["content_url"])
    assert shown.status_code == 200 and shown.headers["content-type"] == "image/jpeg" and shown.content[:3] == b"\xff\xd8\xff"
    assert (await client.get(keyframe["content_url"], headers=BOB)).status_code == 404
    assert (await client.get(f"{API}/projects/{project}/assets")).json()["total"] == 1

    again = await MediaPipeline().extract(UUID(asset["id"]))  # processing is ready: the stored files are reused
    assert [f.asset_id for f in again.frames] == [f.asset_id for f in prepared.frames]
    assert (await client.get(f"{API}/assets/{asset['id']}/status")).json()["derived"] == status["derived"]


@requires_ffmpeg
async def test_real_upload_refuses_a_long_video_and_unreadable_media(client: httpx.AsyncClient, project: str, tmp_path: Any) -> None:
    ffmpeg.detect_tools(force=True)
    long_video = make_video(tmp_path / "long.mp4", scenes=1, seconds_each=61, audio=False).read_bytes()
    response = await upload(client, project, "video", long_video, name="long.mp4")
    assert response.status_code == 422 and "limit is 60 seconds" in response.json()["error"]["message"]
    corrupt = await upload(client, project, "video", MP4, name="corrupt.mp4")  # right magic bytes, nothing playable
    assert corrupt.status_code == 422 and "could not be read as video or audio" in corrupt.json()["error"]["message"]
    assert await asset_rows() == [] and await blob_count() == 0
