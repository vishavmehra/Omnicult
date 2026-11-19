"""Creative X-Ray over HTTP, through the real run engine: upload, start, scenes, access control, failures.

Models and media are replaced by the fakes in media_support (no network); the real ffmpeg is used only by the test that is
marked for it."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db import models as m
from app.db.session import read_session
from app.media import ffmpeg
from app.media.ffmpeg import MediaProcessingFailed, MediaToolMissing
from app.schemas.xray import SCENE_PROVENANCE
from app.services.media import MediaPipeline
from app.workflows import WorkflowDeps
from tests.api.media_support import (
    MP4,
    SEEN,
    SEGMENTS,
    FakeMedia,
    FakeTranscribe,
    FakeVision,
    fake_probe,
    make_video,
    real_png,
    requires_ffmpeg,
    scripted_llm,
    standard,
)
from tests.api.omnicult_support import add_member, seed, workspace_of
from tests.api.test_crud import make_campaign, make_project
from tests.conftest import BOB, wait_for_run

API = "/api/v1"
USABLE = {"completed", "partial"}


@dataclass
class Rig:
    """What the patched build_workflow_deps hands to every X-Ray run. `media=None` means the real MediaPipeline."""

    llm: Any
    vision: Any
    transcribe: Any = None
    media: Any = None


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Rig:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "qa-test-project")  # Vertex AI is configured; every call is faked
    for tier in ("GEMINI_MODEL_FAST", "GEMINI_MODEL_DEFAULT", "GEMINI_MODEL_REASONING"):
        monkeypatch.setenv(tier, "test-model")
    get_settings.cache_clear()
    holder = Rig(llm=scripted_llm(standard), vision=FakeVision(SEEN))

    def build(mode: str, settings: Any) -> WorkflowDeps:
        return WorkflowDeps(llm=holder.llm, vision=holder.vision, media=holder.media or MediaPipeline(),  # type: ignore[arg-type]
                            transcribe=holder.transcribe)

    monkeypatch.setattr("app.workflows.build_workflow_deps", build)
    return holder


async def upload(client: httpx.AsyncClient, project_id: str, kind: str, data: bytes, *, rights: bool = True, **kwargs: Any) -> dict[str, Any]:
    response = await client.post(
        f"{API}/projects/{project_id}/assets", files={"file": ("ad.bin", data, "application/octet-stream")},
        data={"kind": kind, "rights_confirmed": "true" if rights else "false"}, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


async def start(client: httpx.AsyncClient, campaign_id: str, body: dict[str, Any], **kwargs: Any) -> httpx.Response:
    return await client.post(f"{API}/campaigns/{campaign_id}/creative-xrays", json=body, **kwargs)


async def run_xray(client: httpx.AsyncClient, campaign_id: str, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    response = await start(client, campaign_id, body, **kwargs)
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["run_type"] == "creative_xray" and accepted["status"] == "queued"
    return await wait_for_run(client, accepted["run_id"], timeout=90)


@dataclass
class Setup:
    project: str
    campaign: str
    asset: str


@pytest.fixture
async def video(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> Setup:
    project = (await make_project(client))["id"]
    campaign = (await make_campaign(client, project))["id"]
    fake_probe(monkeypatch)
    return Setup(project, campaign, (await upload(client, project, "video", MP4))["id"])


# --- the happy path --------------------------------------------------------------------------------------


async def test_x_ray_saves_verified_scenes_linked_to_the_asset_and_the_campaign(client: httpx.AsyncClient, rig: Rig, video: Setup) -> None:
    rig.media, rig.transcribe = FakeMedia(stored_frames=False), FakeTranscribe(SEGMENTS)
    body = {"asset_id": video.asset, "region_code": "IN-MH", "language": "mr", "label": "Ganesh festival ad"}
    run = await run_xray(client, video.campaign, body, headers={"Idempotency-Key": "xray-1"})
    assert run["status"] == "completed" and run["mode"] == "live" and run["error"] is None
    assert run["progress"] == {"stage": "completed", "completed_steps": 5, "total_steps": 5, "message": "Complete."}
    creative_id = run["result"]["ids"][0]
    assert run["result"] == {"resource": "creative_xray", "ids": [creative_id], "url": f"{API}/creatives/{creative_id}"}

    creative = (await client.get(run["result"]["url"])).json()
    assert (creative["status"], creative["mode"], creative["scene_count"], creative["kind"]) == ("completed", "live", 3, "video")
    assert (creative["label"], creative["region_code"], creative["language"]) == ("Ganesh festival ad", "IN-MH", "mr")
    assert creative["asset_id"] == video.asset == creative["asset"]["id"] and creative["campaign_id"] == video.campaign
    assert creative["latest_run_id"] == creative["current_run_id"] == run["id"]
    analysis = creative["analysis"]
    assert analysis["probe"]["duration_ms"] == 9000 and analysis["transcribe"]["status"] == "transcribed"
    assert analysis["vision"]["status"] == "analyzed" and [f["id"] for f in analysis["frames"]] == ["f1", "f2", "f3"]
    assert analysis["frames"][0]["observations"][0]["description"].startswith("Headline text") and analysis["frames"][0]["url"].endswith("/content")
    assert [t["text"] for t in analysis["transcript"]] == [t for *_, t in SEGMENTS] and analysis["dropped"] == {"on_screen_text": 1, "claims": 1}
    assert [s["stage"] for s in creative["run_metadata"]["steps"]] == [
        "probing_media", "extracting_media", "transcribing", "observing_frames", "structuring_scenes"]
    assert any("could not be verified were removed" in limit for limit in creative["limitations"])

    page = (await client.get(f"{API}/creatives/{creative_id}/scenes")).json()
    assert page["total"] == 3 and [s["position"] for s in page["items"]] == [0, 1, 2]
    first = page["items"][0]
    assert (first["start_ms"], first["end_ms"]) == (0, 3500) and [t["text"] for t in first["on_screen_text"]] == ["Mahotsav Sale 50% OFF"]
    assert [c["text"] for c in first["claims"]] == ["50% OFF"] and [t["id"] for t in first["transcript"]] == ["t1"]
    assert (first["asset_id"], first["campaign_id"], first["run_id"], first["creative_asset_id"]) == (video.asset, video.campaign, run["id"], creative_id)
    assert first["anchor"] == {"scene_id": first["id"], "start_ms": 0, "end_ms": 3500, "bbox": None} and first["provenance"] == dict(SCENE_PROVENANCE)
    second = page["items"][1]
    assert second["cultural_observations"][0]["id"] == "o2.1" and second["cultural_interpretations"][0]["based_on"] == ["o2.1"]
    assert "not an observed fact" in second["cultural_interpretations"][0]["limitations"][0]
    assert (await client.get(f"{API}/creatives/{creative_id}/scenes/{first['id']}")).json() == first
    assert (await client.get(f"{API}/creatives/{creative_id}/scenes/{uuid4()}")).status_code == 404
    listed = (await client.get(f"{API}/campaigns/{video.campaign}/creatives")).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == creative_id and listed["items"][0]["scene_count"] == 3

    # the same Idempotency-Key is the same run; a new request is a new run of the same creative, with its own scenes
    again = await start(client, video.campaign, body, headers={"Idempotency-Key": "xray-1"})
    assert again.status_code == 202 and again.json()["run_id"] == run["id"]
    second_run = await run_xray(client, video.campaign, body)
    assert second_run["id"] != run["id"] and second_run["result"]["ids"] == [creative_id]
    assert (await client.get(f"{API}/campaigns/{video.campaign}/creatives")).json()["total"] == 1  # one creative per (campaign, asset)
    newest = (await client.get(f"{API}/creatives/{creative_id}/scenes")).json()
    assert newest["total"] == 3 and {s["run_id"] for s in newest["items"]} == {second_run["id"]}
    older = (await client.get(f"{API}/creatives/{creative_id}/scenes", params={"run_id": run["id"]})).json()
    assert older["total"] == 3 and {s["run_id"] for s in older["items"]} == {run["id"]}  # history is kept
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.CreativeScene)) == 6


async def test_a_missing_transcript_makes_the_run_partial_and_media_failures_keep_earlier_scenes(
    client: httpx.AsyncClient, rig: Rig, video: Setup
) -> None:
    body = {"asset_id": video.asset}
    rig.media = FakeMedia(stored_frames=False)  # no transcribe capability and no sidecar
    partial = await run_xray(client, video.campaign, body)
    assert partial["status"] == "partial" and partial["result"] is not None and partial["error"] is None
    creative = (await client.get(partial["result"]["url"])).json()
    assert creative["status"] == "partial" and creative["analysis"]["transcribe"]["status"] == "unavailable"
    assert any(limit.startswith("Transcript:") for limit in creative["limitations"]) and creative["scene_count"] == 3

    rig.media = FakeMedia(fail=MediaToolMissing("Video and audio processing is unavailable: ffmpeg was not found."))
    missing = await run_xray(client, video.campaign, body)
    assert missing["status"] == "failed" and missing["result"] is None
    assert missing["error"] == {"code": "PROVIDER_NOT_CONFIGURED", "stage": "probing_media", "retryable": False,
                                "message": "Video and audio processing is unavailable: ffmpeg was not found. No scenes were saved."}
    rig.media = FakeMedia(extract_fail=MediaProcessingFailed("Scene detection took longer than 90 seconds and was stopped."))
    stuck = await run_xray(client, video.campaign, body)
    assert stuck["status"] == "failed" and stuck["error"]["retryable"] is True and stuck["error"]["stage"] == "extracting_media"

    after = (await client.get(f"{API}/creatives/{creative['id']}")).json()
    assert after["status"] == "failed" and after["latest_run_id"] == stuck["id"]  # the status mirrors the latest run
    assert after["current_run_id"] == partial["id"] and after["scene_count"] == 3  # the last good analysis is still there
    assert (await client.get(f"{API}/creatives/{creative['id']}/scenes")).json()["total"] == 3


async def test_an_image_needs_no_ffmpeg_and_is_one_scene_with_a_stored_thumbnail(client: httpx.AsyncClient, rig: Rig) -> None:
    rig.vision = FakeVision(default=[("text_in_image", 'Headline text: "Diwali Dhamaka"')])
    rig.llm = scripted_llm(lambda ctx: {"scenes": [{"start_ms": 0, "on_screen_text": ["diwali dhamaka", "Never shown"], "people": ["a family"]}]})
    project = (await make_project(client))["id"]
    campaign = (await make_campaign(client, project))["id"]
    asset = await upload(client, project, "image", real_png(), rights=False)
    assert asset["processing_status"] == "not_required"

    run = await run_xray(client, campaign, {"asset_id": asset["id"]})  # the real MediaPipeline: Pillow only
    assert run["status"] == "completed", run["error"]
    creative = (await client.get(run["result"]["url"])).json()
    assert creative["kind"] == "image" and creative["asset"]["id"] == asset["id"] and creative["scene_count"] == 1
    assert (creative["analysis"]["probe"]["kind"], creative["analysis"]["probe"]["width"]) == ("image", 64)
    assert creative["analysis"]["transcribe"]["status"] == "not_applicable" and creative["analysis"]["dropped"] == {"on_screen_text": 1}
    (scene,) = (await client.get(f"{API}/creatives/{creative['id']}/scenes")).json()["items"]
    assert (scene["start_ms"], scene["end_ms"], scene["keyframe_asset_id"]) == (0, None, None)
    assert scene["keyframe_url"] == asset["content_url"]  # an image is its own keyframe
    assert [t["text"] for t in scene["on_screen_text"]] == ["diwali dhamaka"] and scene["people"] == ["a family"]

    status = (await client.get(f"{API}/assets/{asset['id']}/status")).json()
    assert status["processing_status"] == "ready" and [d["role"] for d in status["derived"]] == ["thumbnail"]
    thumb = status["derived"][0]
    assert creative["thumbnail_url"] == thumb["content_url"]
    shown = await client.get(thumb["content_url"])
    assert shown.status_code == 200 and shown.headers["content-type"] == "image/jpeg" and shown.content[:3] == b"\xff\xd8\xff"
    refused = await start(client, campaign, {"asset_id": thumb["id"]})  # a derived file is not a creative
    assert refused.status_code == 409 and refused.json()["error"]["details"][0]["field"] == "asset_id"


# --- validation and access -------------------------------------------------------------------------------


async def test_start_requests_are_validated(client: httpx.AsyncClient, rig: Rig, video: Setup) -> None:
    other_project = (await make_project(client))["id"]
    foreign = await upload(client, other_project, "image", real_png(), rights=False)
    refused = await start(client, video.campaign, {"asset_id": foreign["id"]})
    assert refused.status_code == 409 and "another project" in refused.json()["error"]["message"]
    assert (await start(client, video.campaign, {"asset_id": str(uuid4())})).status_code == 404
    assert (await start(client, str(uuid4()), {"asset_id": video.asset})).status_code == 404
    for bad in ({"asset_id": video.asset, "region_code": "XX-1"}, {"asset_id": video.asset, "language": "mar"}, {"asset_id": video.asset, "extra": 1},
                {}):
        assert (await start(client, video.campaign, bad)).status_code == 422
    await seed()  # with the India reference data loaded, a region code must be a real one
    unknown = await start(client, video.campaign, {"asset_id": video.asset, "region_code": "IN-ZZ"})
    assert unknown.status_code == 409 and unknown.json()["error"]["details"][0]["field"] == "region_code"
    rig.media = FakeMedia(stored_frames=False)
    ok = await run_xray(client, video.campaign, {"asset_id": video.asset, "region_code": "IN-TN"})
    assert ok["status"] in USABLE
    assert (await client.get(f"{API}/creatives/{ok['result']['ids'][0]}")).json()["region_code"] == "IN-TN"


async def test_a_live_x_ray_needs_a_configured_model(client: httpx.AsyncClient, video: Setup) -> None:
    response = await start(client, video.campaign, {"asset_id": video.asset})
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "PROVIDER_NOT_CONFIGURED" and "Live Creative X-Ray is unavailable" in error["message"]


async def test_viewers_read_but_cannot_start_and_other_workspaces_see_nothing(client: httpx.AsyncClient, rig: Rig, video: Setup) -> None:
    rig.media, rig.transcribe = FakeMedia(stored_frames=False), FakeTranscribe(SEGMENTS)
    run = await run_xray(client, video.campaign, {"asset_id": video.asset})
    creative_id = run["result"]["ids"][0]
    scene_id = (await client.get(f"{API}/creatives/{creative_id}/scenes")).json()["items"][0]["id"]
    body = {"asset_id": video.asset}

    for denied in (  # a user outside the workspace cannot tell any of it exists
        start(client, video.campaign, body, headers=BOB), client.get(f"{API}/campaigns/{video.campaign}/creatives", headers=BOB),
        client.get(f"{API}/creatives/{creative_id}", headers=BOB), client.get(f"{API}/creatives/{creative_id}/scenes", headers=BOB),
        client.get(f"{API}/creatives/{creative_id}/scenes/{scene_id}", headers=BOB), client.get(f"{API}/runs/{run['id']}", headers=BOB),
    ):
        response = await denied
        assert response.status_code == 404, response.text
        assert creative_id not in response.text

    await add_member(await workspace_of("alice"), "bob", "viewer")
    assert (await client.get(f"{API}/creatives/{creative_id}", headers=BOB)).status_code == 200
    assert (await client.get(f"{API}/creatives/{creative_id}/scenes/{scene_id}", headers=BOB)).status_code == 200
    forbidden = await start(client, video.campaign, body, headers=BOB)
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "FORBIDDEN"
    await add_member(await workspace_of("alice"), "bob", "editor")
    allowed = await start(client, video.campaign, body, headers=BOB)
    assert allowed.status_code == 202
    assert (await wait_for_run(client, allowed.json()["run_id"], timeout=60, headers=BOB))["status"] in USABLE


# --- demo and the real binaries --------------------------------------------------------------------------


async def test_a_demo_project_never_sends_an_upload_to_a_model(client: httpx.AsyncClient) -> None:
    project = (await client.post(f"{API}/projects/demo")).json()
    campaign = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]
    asset = await upload(client, project["id"], "image", real_png(), rights=False)
    run = await run_xray(client, campaign["id"], {"asset_id": asset["id"]})  # the real deps for demo: fixture model, no vision
    assert run["mode"] == "demo" and run["status"] == "partial", run["error"]
    creative = (await client.get(run["result"]["url"])).json()
    assert creative["mode"] == "demo" and creative["analysis"]["vision"]["status"] == "unavailable"
    assert "Demo projects do not analyze uploads" in creative["analysis"]["vision"]["message"]
    assert any("keyframe timings only" in limit for limit in creative["limitations"])
    (scene,) = (await client.get(f"{API}/creatives/{creative['id']}/scenes")).json()["items"]
    assert scene["on_screen_text"] == [] and scene["people"] == [] and any("not analysed" in limit for limit in scene["limitations"])


@requires_ffmpeg
async def test_real_ffmpeg_end_to_end_with_a_sidecar_transcript(client: httpx.AsyncClient, rig: Rig, tmp_path: Any) -> None:
    ffmpeg.detect_tools(force=True)
    rig.vision = FakeVision(default=[("text_in_image", 'Headline text: "Big Sale"')])
    project = (await make_project(client))["id"]
    campaign = (await make_campaign(client, project))["id"]
    srt = b"1\n00:00:00,500 --> 00:00:02,500\nBig Sale this week\n\n2\n00:00:07,000 --> 00:00:08,500\nVisit us today\n"
    response = await client.post(
        f"{API}/projects/{project}/assets", data={"kind": "video", "rights_confirmed": "true"},
        files={"file": ("ad.mp4", make_video(tmp_path / "ad.mp4").read_bytes(), "video/mp4"), "sidecar": ("ad.srt", srt, "text/plain")})
    assert response.status_code == 201, response.text
    asset = response.json()

    run = await run_xray(client, campaign, {"asset_id": asset["id"], "language": "en"})
    assert run["status"] == "completed", run["error"]  # transcript from the sidecar, vision and model faked
    creative = (await client.get(run["result"]["url"])).json()
    assert creative["analysis"]["transcribe"]["status"] == "from_sidecar" and creative["thumbnail_url"]
    assert [t["source"] for t in creative["analysis"]["transcript"]] == ["user_sidecar", "user_sidecar"]
    scenes = (await client.get(f"{API}/creatives/{creative['id']}/scenes")).json()["items"]
    assert len(scenes) >= 3 and scenes[0]["start_ms"] == 0 and abs(scenes[-1]["end_ms"] - 9000) < 200
    assert all(a["end_ms"] <= b["start_ms"] for a, b in zip(scenes, scenes[1:]))
    assert all(s["keyframe_asset_id"] and s["keyframe_url"] for s in scenes)  # real stored keyframes
    frame = await client.get(scenes[1]["keyframe_url"])
    assert frame.status_code == 200 and frame.content[:3] == b"\xff\xd8\xff" and (await client.get(scenes[1]["keyframe_url"], headers=BOB)).status_code == 404
    assert [t["text"] for t in scenes[0]["on_screen_text"]] == ["Big Sale"] and scenes[0]["claims"] == []
    assert any(t["id"] == "t1" for t in scenes[0]["transcript"]) and any(t["id"] == "t2" for s in scenes for t in s["transcript"])
    status = (await client.get(f"{API}/assets/{asset['id']}/status")).json()
    assert status["processing_status"] == "ready" and status["sidecar"]["format"] == "srt"
    assert {d["role"] for d in status["derived"]} == {"keyframe", "thumbnail", "audio_track"}
    assert isinstance(UUID(scenes[0]["keyframe_asset_id"]), UUID)
