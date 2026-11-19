"""Remake: Video over HTTP, through the real run engine, operation engine and database.

The model is a fake that returns a real small MP4 (no network, no paid call); ffmpeg and ffprobe are the real local tools.
Estimates, confirmation, the budget guard, locks, the voice-over join and the stored provenance are asserted on the results."""

import base64
import io
from typing import Any
from uuid import UUID

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models as m
from app.db.session import read_session
from app.llm.gateway import LLMError
from app.schemas.common import StepTrace
from tests.api.media_support import requires_ffmpeg
from tests.api.omnicult_support import client_for, seeded  # noqa: F401
from tests.api.remake_support import (
    API, FakeLLM, FakeSpeech, World, build_world, element, elements, finish, png_bytes, rig, start, upload_image, visual_body,  # noqa: F401
)
from tests.api.remake_video_support import FakeVideo, mp4
from tests.conftest import wait_for_run

pytestmark = [pytest.mark.usefixtures("seeded"), requires_ffmpeg]


def video_body(world: World, **extra: Any) -> dict[str, Any]:
    return {"region_code": "IN-TN", "language": "ta", "confirm_cost": True, **extra}


async def with_video(rig: Any, video: FakeVideo | None = None) -> FakeVideo:
    video = video or FakeVideo()
    rig.llm.adapters["video"] = video
    return video


async def remade_world(client: httpx.AsyncClient, rig: Any, **kw: Any) -> tuple[World, str]:
    """A world whose newest version holds a Remake: Visuals scene (the start frame of a clip). Returns it and that version's id."""
    world = await build_world(client, **kw)
    run = await finish(client, world, "visual", visual_body(world))
    assert run["status"] == "completed", run["error"]
    versions = (await client.get(f"{API}/campaigns/{world.campaign}/versions")).json()["items"]
    return world, max(versions, key=lambda v: v["created_at"])["id"]


async def start_video(client: httpx.AsyncClient, world: World, body: dict[str, Any], **kw: Any) -> httpx.Response:
    return await client.post(f"{API}/campaigns/{world.campaign}/remakes/video", json=body, **kw)


async def finish_video(client: httpx.AsyncClient, world: World, body: dict[str, Any]) -> dict[str, Any]:
    response = await start_video(client, world, body)
    assert response.status_code == 202, response.text
    assert response.json()["run_type"] == "remake_video"
    return await wait_for_run(client, response.json()["run_id"], timeout=120)


async def video_output(client: httpx.AsyncClient, world: World, run: dict[str, Any]) -> dict[str, Any]:
    page = (await client.get(f"{API}/campaigns/{world.campaign}/remakes", params={"run_id": run["id"]})).json()
    assert page["total"] == 1, page
    return page["items"][0]


async def content(client: httpx.AsyncClient, url: str) -> httpx.Response:
    response = await client.get(url)
    assert response.status_code == 200, response.text
    return response


# --- a clip from the remade key visual ---------------------------------------------------------------------------------


async def test_a_clip_starts_from_the_remade_scene_and_lands_in_a_new_version_with_its_provenance(client: httpx.AsyncClient, rig: Any) -> None:
    world, remade = await remade_world(client, rig)
    video = await with_video(rig)
    run = await finish_video(client, world, video_body(world, direction="Slow push-in on the lamp."))
    assert run["status"] == "completed", run["error"]
    assert run["result"]["resource"] == "operation"
    out = await video_output(client, world, run)
    clip = out["video"]
    # one paid call, the start frame is the layout on a 9:16 canvas, the prompt carries the region and the direction, audio is off
    assert len(video.calls) == 1
    call = video.calls[0]
    assert (call["seconds"], call["aspect_ratio"], call["start_mime_type"]) == (6, "9:16", "image/png")
    assert Image.open(io.BytesIO(call["start_image"])).size == (720, 1280)
    assert "Tamil Nadu" in call["prompt"] and "Slow push-in on the lamp." in call["prompt"] and call["prompt"].isascii()
    assert "Brand graphics are added afterwards" in call["prompt"] and "never draw any logo" in call["prompt"]  # the model is told to leave the brand elements to code
    assert "exactly as they appear" not in call["prompt"] and not any(e["value"] in call["prompt"] for e in elements() if e["kind"] in ("headline", "cta"))
    # a NEW version: a `remake-video` scene element holds the clip; the source version is untouched
    new = (await client.get(f"{API}/campaigns/{world.campaign}/versions/{out['result_version_id']}")).json()
    old = (await client.get(f"{API}/campaigns/{world.campaign}/versions/{remade}")).json()
    assert new["parent_id"] == remade and new["actor"] == "ai" and out["source_version_id"] == remade
    added = {e["id"]: e for e in new["elements"]}["remake-video"]
    assert added["kind"] == "scene" and added["value"]["media"] == "video" and added["value"]["asset_id"] == clip["video_asset_id"]
    assert added["value"]["ai_generated"] is True and "remake-video" not in {e["id"] for e in old["elements"]}
    assert len(new["elements"]) == len(old["elements"]) + 1
    # operation: actor ai, reason, prompt version and the estimated cost recorded; kind remake shows in the Version Tree as an AI proposal
    op = (await client.get(f"{API}/campaigns/{world.campaign}/operations/{out['id']}")).json()
    assert (op["kind"], op["actor"], op["prompt_version"], op["status"]) == ("remake", "ai", "remake-video-v2", "applied")
    assert op["estimated_cost_usd"] == pytest.approx(0.48) and "Tamil Nadu" in op["reason"] and "6 s clip" in op["reason"]
    assert out["kind"] == "video" and out["passed"] and out["mode"] == "live" and out["estimated_cost_usd"] == pytest.approx(0.48)
    # what the clip says about itself
    assert (clip["source"], clip["start_source"], clip["model"], clip["location"]) == ("provider", "remake_scene", "veo-3.1-fast-generate-001", "us-central1")
    assert (clip["seconds"], clip["resolution"], clip["aspect_ratio"], clip["operation_id"]) == (6, "720p", "9:16", "op-1234")
    assert clip["audio_generated_by_model"] is False and not clip["with_voiceover"] and clip["video_asset_id"] == clip["silent_asset_id"]
    assert [r["element_id"] for r in clip["kept_regions"]] == ["kv-pack"]  # the pack has no Brand Kit file here, so it stays in the frame as pixels
    assert all(c["passed"] for c in clip["checks"]) and clip["prompt_version"] == "remake-video-v2"
    brand = {c["name"]: c for c in clip["checks"] if c["element_id"]}  # the logo and headline are drawn in code over every frame, then measured
    assert {c["element_id"] for c in brand.values()} == {"kv-logo", "kv-headline"} and all(c["sampled"] >= 10 and c["failed_at_ms"] == [] for c in brand.values())
    assert all("held for all" in c["detail"] for c in brand.values())
    assert any("drawn in code over every frame" in n for n in out["limitations"]) and any("no on-screen text" in n for n in out["limitations"])
    # the files: the clip plays as video/mp4, the start frame is the PNG the model received
    file = await content(client, clip["video_url"])
    assert file.headers["content-type"].startswith("video/mp4") and file.content == mp4(6)
    assert (await content(client, clip["start_frame_url"])).content == call["start_image"]
    async with read_session() as s:
        rows = {r.derived_role: r for r in (await s.execute(select(m.Asset).where(m.Asset.derived_role.in_(["remake_video", "remake_frame"])))).scalars()}
    assert set(rows) == {"remake_video", "remake_frame"} and rows["remake_video"].kind == "video"
    info = rows["remake_video"].media_info["remake"]
    assert (info["model"], info["prompt_version"], info["seconds"], info["ai_generated"]) == ("veo-3.1-fast-generate-001", "remake-video-v2", 6, True)
    assert info["estimated_cost_usd"] == pytest.approx(0.48) and info["run_id"] == run["id"]
    assert rows["remake_frame"].parent_asset_id == UUID(world.original)  # the start frame descends from the finished creative


async def test_the_voiceover_of_the_version_is_joined_when_it_fits_and_a_second_clip_edits_the_same_element(client: httpx.AsyncClient, rig: Any) -> None:
    world, _ = await remade_world(client, rig)
    rig.llm.adapters["tts"] = FakeSpeech(1.5)
    sound = await finish(client, world, "sound", {"region_code": "IN-TN", "language": "ta", "confirm_cost": True, "element_ids": ["cap-1"]})
    assert sound["status"] == "completed", sound["error"]
    video = await with_video(rig)
    run = await finish_video(client, world, video_body(world))
    assert run["status"] == "completed", run["error"]
    clip = (await video_output(client, world, run))["video"]
    assert clip["with_voiceover"] and clip["voiceover_ms"] == 1500 and clip["video_asset_id"] != clip["silent_asset_id"]
    assert (await content(client, clip["silent_url"])).content == mp4(6)  # the clip as delivered is kept
    joined = (await content(client, clip["video_url"])).content
    assert joined != mp4(6) and joined[4:8] == b"ftyp"
    async with read_session() as s:
        row = await s.get(m.Asset, UUID(clip["video_asset_id"]))
        assert row.parent_asset_id == UUID(clip["silent_asset_id"]) and row.media_info["remake"]["part"] == "clip with voice-over"
    # a second clip from the newest version edits `remake-video` instead of adding a second element
    second = await finish_video(client, world, video_body(world, seconds=4))
    assert second["status"] == "completed", second["error"]
    out = await video_output(client, world, second)
    new = (await client.get(f"{API}/campaigns/{world.campaign}/versions/{out['result_version_id']}")).json()
    ids = [e["id"] for e in new["elements"]]
    assert ids.count("remake-video") == 1 and out["video"]["seconds"] == 4 and len(video.calls) == 2
    assert out["estimated_cost_usd"] == pytest.approx(0.48)  # the fake's trace; the real adapter prices 4 s at $0.32 (unit test)


async def test_a_voiceover_longer_than_the_clip_is_not_joined_and_the_plan_says_so(client: httpx.AsyncClient, rig: Any) -> None:
    world, _ = await remade_world(client, rig)
    rig.llm.adapters["tts"] = FakeSpeech(7.0)
    assert (await finish(client, world, "sound", {"region_code": "IN-TN", "language": "ta", "confirm_cost": True, "element_ids": ["cap-1"]}))["status"] == "completed"
    await with_video(rig)
    plan = (await client.post(f"{API}/campaigns/{world.campaign}/remakes/video/preview", json=video_body(world))).json()
    assert plan["voiceover"]["will_join"] is False and "never cut" in plan["voiceover"]["note"] and plan["voiceover"]["duration_ms"] == 7000
    run = await finish_video(client, world, video_body(world))
    clip = (await video_output(client, world, run))["video"]
    assert run["status"] == "completed" and not clip["with_voiceover"] and clip["video_asset_id"] == clip["silent_asset_id"]
    off = (await client.post(f"{API}/campaigns/{world.campaign}/remakes/video/preview", json=video_body(world, add_voiceover=False))).json()
    assert off["voiceover"] is None


# --- the preview, the estimate and the guards --------------------------------------------------------------------------


async def test_the_preview_shows_the_frame_the_prompt_and_the_cost_and_makes_no_call(client: httpx.AsyncClient, rig: Any) -> None:
    world, remade = await remade_world(client, rig)
    video = await with_video(rig)
    response = await client.post(f"{API}/campaigns/{world.campaign}/remakes/video/preview", json={"region_code": "IN-TN", "language": "ta", "direction": "Lamp glow."})
    assert response.status_code == 200, response.text
    plan = response.json()
    assert not video.calls and plan["can_run"] and plan["blocked_reason"] is None and plan["mode"] == "live"
    assert plan["source_version_id"] == remade and plan["model"] == "veo-3.1-fast-generate-001" and plan["location"] == "us-central1"
    assert (plan["seconds"], plan["resolution"], plan["prompt_version"]) == (6, "720p", "remake-video-v2")
    assert plan["price_per_second_usd"] == pytest.approx(0.08) and plan["estimated_cost_usd"] == pytest.approx(0.48)
    assert plan["run_budget_usd"] == pytest.approx(0.50) and plan["within_budget"]
    frame = plan["start_frame"]
    assert (frame["source"], frame["aspect_ratio"], frame["width"], frame["height"]) == ("remake_scene", "9:16", 720, 1280)
    assert Image.open(io.BytesIO(base64.b64decode(frame["preview_jpeg_base64"]))).format == "JPEG"
    assert "Lamp glow." in plan["prompt"] and "Tamil Nadu" in plan["prompt"] and "text" in plan["negative_prompt"]
    assert [x["element_id"] for x in plan["kept_regions"]] == ["kv-pack"] and any("drawn in code over every frame" in n for n in plan["notes"])
    # the preview never needs the confirmation; the run does
    refused = await start_video(client, world, {"region_code": "IN-TN", "language": "ta"})
    assert refused.status_code == 422 and refused.json()["error"]["details"][0]["field"] == "confirm_cost" and not video.calls


async def test_a_clip_estimated_above_the_run_budget_is_refused_before_any_call_until_the_budget_is_raised(
    client: httpx.AsyncClient, rig: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, _ = await remade_world(client, rig)
    video = await with_video(rig)
    refused = await start_video(client, world, video_body(world, seconds=8))
    assert refused.status_code == 409 and "$0.64" in refused.text and "AI_RUN_BUDGET_USD" in refused.text and not video.calls
    plan = (await client.post(f"{API}/campaigns/{world.campaign}/remakes/video/preview", json=video_body(world, seconds=8))).json()
    assert plan["estimated_cost_usd"] == pytest.approx(0.64) and not plan["within_budget"] and not plan["can_run"] and "budget" in plan["blocked_reason"]
    monkeypatch.setenv("AI_RUN_BUDGET_USD", "1.0")
    get_settings.cache_clear()
    run = await finish_video(client, world, video_body(world, seconds=8))
    assert run["status"] == "completed", run["error"] and len(video.calls) == 1 and video.calls[0]["seconds"] == 8


async def test_one_clip_per_request_even_when_the_request_is_repeated_with_the_same_key(client: httpx.AsyncClient, rig: Any) -> None:
    world, _ = await remade_world(client, rig)
    video = await with_video(rig)
    body, headers = video_body(world), {"Idempotency-Key": "clip-1"}
    first = await start_video(client, world, body, headers=headers)
    again = await start_video(client, world, body, headers=headers)
    assert first.status_code == again.status_code == 202 and first.json()["run_id"] == again.json()["run_id"]
    await wait_for_run(client, first.json()["run_id"], timeout=120)
    assert len(video.calls) == 1


async def test_capabilities_list_the_video_model_the_lengths_and_the_rate_without_a_call(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    video = await with_video(rig)
    caps = (await client.get(f"{API}/campaigns/{world.campaign}/remakes/capabilities")).json()
    assert caps["video"]["configured"] and caps["video"]["model"] == "veo-3.1-fast-generate-001" and caps["video"]["location"] == "us-central1"
    assert caps["video"]["estimated_cost_usd"] == pytest.approx(0.48) and caps["video_seconds"] == [4, 6, 8] and caps["video_default_seconds"] == 6
    assert caps["video_price_per_second_usd"] == pytest.approx(0.08) and not video.calls
    rig.llm = FakeLLM({})
    assert (await client.get(f"{API}/campaigns/{world.campaign}/remakes/capabilities")).json()["video"]["configured"] is False


async def test_a_live_clip_is_unavailable_when_no_video_model_is_configured(client: httpx.AsyncClient, rig: Any) -> None:
    world, _ = await remade_world(client, rig)
    rig.llm = FakeLLM({})
    response = await start_video(client, world, video_body(world))
    assert response.status_code == 503 and "video model" in response.json()["error"]["message"]
    plan = (await client.post(f"{API}/campaigns/{world.campaign}/remakes/video/preview", json=video_body(world))).json()
    assert not plan["can_run"] and "video model" in plan["blocked_reason"]


# --- other start frames -------------------------------------------------------------------------------------------------


async def test_a_chosen_image_is_the_start_frame_and_a_foreign_one_is_refused(client: httpx.AsyncClient, rig: Any) -> None:
    from tests.api.test_crud import make_project

    world = await build_world(client)
    video = await with_video(rig)
    picture = await upload_image(client, world.project, png_bytes((600, 400), (10, 120, 110)))
    run = await finish_video(client, world, video_body(world, start_asset_id=picture))
    assert run["status"] == "completed", run["error"]
    clip = (await video_output(client, world, run))["video"]
    assert (clip["start_source"], clip["aspect_ratio"], clip["kept_regions"]) == ("asset", "16:9", [])
    assert Image.open(io.BytesIO(video.calls[0]["start_image"])).size == (1280, 720)
    other = await make_project(client)
    foreign = await upload_image(client, other["id"], png_bytes())
    refused = await start_video(client, world, video_body(world, start_asset_id=foreign))
    assert refused.status_code == 409 and "start_asset_id" in refused.text and len(video.calls) == 1


async def test_without_any_start_frame_the_clip_is_made_from_the_prompt_alone_and_says_so(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    video = await with_video(rig)
    plan = (await client.post(f"{API}/campaigns/{world.campaign}/remakes/video/preview", json=video_body(world))).json()
    assert plan["start_frame"]["source"] == "none" and plan["start_frame"]["preview_jpeg_base64"] is None and any("prompt alone" in n for n in plan["notes"])
    run = await finish_video(client, world, video_body(world))
    assert run["status"] == "completed", run["error"]
    out = await video_output(client, world, run)
    assert video.calls[0]["start_image"] is None and out["video"]["start_source"] == "none" and out["video"]["start_frame_asset_id"] is None
    assert any("prompt alone" in n for n in out["limitations"])


# --- failures, locks and access -----------------------------------------------------------------------------------------


async def test_a_provider_failure_creates_no_version_and_no_asset_and_is_reported_honestly(client: httpx.AsyncClient, rig: Any) -> None:
    world, _ = await remade_world(client, rig)
    trace = StepTrace(stage="generating_video", agent="x", status="failed", provider="google", error_code="PROVIDER_TIMEOUT")
    await with_video(rig, FakeVideo(error=LLMError("PROVIDER_TIMEOUT", "Veo did not respond. The request was accepted, so Google may still bill it.",
                                                    retryable=False, trace=trace)))
    versions = (await client.get(f"{API}/campaigns/{world.campaign}/versions")).json()["total"]
    run = await finish_video(client, world, video_body(world))
    assert run["status"] == "failed" and run["error"]["code"] == "PROVIDER_TIMEOUT" and run["error"]["stage"] == "generating_video"
    assert run["error"]["retryable"] is False and "may still bill" in run["error"]["message"]
    assert (await client.get(f"{API}/campaigns/{world.campaign}/versions")).json()["total"] == versions
    assert (await client.get(f"{API}/campaigns/{world.campaign}/remakes", params={"kind": "video"})).json()["total"] == 0
    async with read_session() as s:
        assert (await s.execute(select(m.Asset).where(m.Asset.derived_role.in_(["remake_video", "remake_frame"])))).first() is None


async def test_a_locked_clip_element_refuses_a_new_clip_before_any_call_and_a_late_lock_keeps_no_output(client: httpx.AsyncClient, rig: Any) -> None:
    world, _ = await remade_world(client, rig)
    video = await with_video(rig)
    assert (await finish_video(client, world, video_body(world)))["status"] == "completed"
    assert (await client.put(f"{API}/campaigns/{world.campaign}/locks/remake-video", json={"reason": "approved clip"})).status_code == 200
    refused = await start_video(client, world, video_body(world))
    assert refused.status_code == 409 and "locked" in refused.text and len(video.calls) == 1
    plan = (await client.post(f"{API}/campaigns/{world.campaign}/remakes/video/preview", json=video_body(world))).json()
    assert not plan["can_run"] and "locked" in plan["blocked_reason"]
    # a lock set while the paid call is running refuses the operation and keeps no file
    await client.delete(f"{API}/campaigns/{world.campaign}/locks/remake-video")
    real = video.generate

    async def lock_then_answer(prompt: str, **kwargs: Any) -> Any:
        await client.put(f"{API}/campaigns/{world.campaign}/locks/remake-video", json={"reason": "late lock"})
        return await real(prompt, **kwargs)

    video.generate = lock_then_answer  # type: ignore[method-assign]
    run = await finish_video(client, world, video_body(world))
    assert run["status"] == "failed" and run["error"]["code"] == "CONFLICT" and run["result"] is None
    rejected = (await client.get(f"{API}/campaigns/{world.campaign}/operations", params={"kind": "remake", "status": "rejected"})).json()
    assert rejected["total"] == 1 and rejected["items"][0]["rejection"]["code"] == "LOCKED"
    async with read_session() as s:
        clips = (await s.execute(select(m.Asset).where(m.Asset.derived_role == "remake_video"))).scalars().all()
    assert len(clips) == 1  # only the first run's clip


async def test_remake_visuals_never_offers_the_clip_element_as_a_scene_to_replace(client: httpx.AsyncClient, rig: Any) -> None:
    world, _ = await remade_world(client, rig)
    await with_video(rig)
    assert (await finish_video(client, world, video_body(world)))["status"] == "completed"
    refused = await start(client, world, "visual", visual_body(world, plate_element_id="remake-video"))
    assert refused.status_code == 409 and "video clip" in refused.text


async def test_only_an_editor_can_make_a_clip_and_a_stranger_cannot_even_preview(client: httpx.AsyncClient, rig: Any, client_for: Any) -> None:
    from tests.api.omnicult_support import add_member, workspace_of

    world, _ = await remade_world(client, rig)
    video = await with_video(rig)
    await add_member(await workspace_of("alice"), "bob", "viewer")
    bob = client_for({"Authorization": "Bearer dev-bob"})
    assert (await bob.post(f"{API}/campaigns/{world.campaign}/remakes/video", json=video_body(world))).status_code == 403
    stranger = client_for({"Authorization": "Bearer dev-mallory"})
    assert (await stranger.post(f"{API}/campaigns/{world.campaign}/remakes/video/preview", json=video_body(world))).status_code == 404
    assert not video.calls
