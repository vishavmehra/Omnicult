"""Remake: Visuals and Remake: Sound over HTTP, through the real run engine, operation engine and database.

Every model is a fake (no network, no paid call). Locked pixels, labels, costs, budgets and refusals are asserted on the
stored results."""

import io
from typing import Any
from uuid import UUID

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.llm.budget import BudgetGuard, InMemoryUsageSink
from app.llm.gateway import LLMError, LLMGateway
from app.media import textrender
from app.schemas.common import StepTrace
from tests.api.omnicult_support import client_for, seeded  # noqa: F401
from tests.api.remake_support import (
    API, LINES, FakeImage, FakeLLM, FakeMusic, FakeSpeech, build_world, element, elements, finish, output_of, png_bytes, rig,  # noqa: F401
    start, visual_body, wav_bytes,
)
from tests.unit.llm.genai_fakes import FakeClient, blob_reply

pytestmark = pytest.mark.usefixtures("seeded")


async def asset_bytes(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url)
    assert response.status_code == 200, response.text
    return response.content


def adapter(rig: Any, name: str) -> Any:
    return rig.llm.adapters[name]


# --- Remake: Visuals ----------------------------------------------------------------------------------------------


async def test_visual_remake_creates_a_new_version_with_locked_pixels_identical_and_text_drawn_in_code(
    client: httpx.AsyncClient, rig: Any,
) -> None:
    world = await build_world(client)
    run = await finish(client, world, "visual", visual_body(world, direction="Brass lamps and a kolam."))
    assert run["status"] == "completed", run["error"]
    assert run["result"]["resource"] == "operation"
    out = await output_of(client, world, run)
    visual = out["visual"]
    # one paid call, with the layout (plate + locked regions) as the first reference, and the person's direction in the prompt
    image = adapter(rig, "image_generation")
    assert len(image.calls) == 1 and image.calls[0]["aspect_ratio"] == "4:5" and image.calls[0]["reference_image"]
    assert "Brass lamps and a kolam." in image.calls[0]["prompt"] and "Tamil Nadu" in image.calls[0]["prompt"]
    # a NEW version: the scene element points at the generated plate; the source version is untouched
    new = (await client.get(f"{API}/campaigns/{world.campaign}/versions/{out['result_version_id']}")).json()
    old = (await client.get(f"{API}/campaigns/{world.campaign}/versions/{world.version}")).json()
    by_new = {e["id"]: e for e in new["elements"]}
    assert new["parent_id"] == world.version and new["actor"] == "ai" and (new["region_code"], new["language"]) == ("IN-TN", "ta")
    assert by_new["kv-plate"]["value"] == f"asset:{visual['plate_asset_id']}"
    assert {e["id"]: e["value"] for e in old["elements"]}["kv-plate"] == "creative/plate.jpg"
    assert {k: v["value"] for k, v in by_new.items() if k != "kv-plate"} == {e["id"]: e["value"] for e in old["elements"] if e["id"] != "kv-plate"}
    # operation: actor ai, reason, prompt version and cost recorded
    op = (await client.get(f"{API}/campaigns/{world.campaign}/operations/{out['id']}")).json()
    assert (op["kind"], op["actor"], op["prompt_version"], op["status"]) == ("remake", "ai", "remake-visual-v2", "applied")
    assert op["estimated_cost_usd"] == pytest.approx(0.067) and "Tamil Nadu" in op["reason"] and op["params"]["run_id"] == run["id"]
    assert out["estimated_cost_usd"] == pytest.approx(0.067) and out["passed"] and out["mode"] == "live"
    # locked regions: never-change kinds and the lock, each proven identical from the STORED bytes
    original = Image.open(io.BytesIO(await asset_bytes(client, f"{API}/assets/{world.original}/content"))).convert("RGB")
    stored = Image.open(io.BytesIO(await asset_bytes(client, visual["output_url"]))).convert("RGB")
    assert {r["element_id"]: r["source"] for r in visual["locked_regions"]} == {
        "kv-logo": "lock", "kv-pack": "brand_kit_never_change"}
    assert all(r["identical"] for r in visual["locked_regions"]) and stored.size == original.size
    for region in visual["locked_regions"]:
        rect = textrender.pixel_rect(region["bbox"], original.size)
        assert stored.crop(rect).tobytes() == original.crop(rect).tobytes()
    assert stored.getpixel((5, 495)) != original.getpixel((5, 495))
    # Tamil text rendered in code with shaping, fit and contrast checks
    texts = {t["element_id"]: t for t in visual["texts"]}
    assert set(texts) == {"kv-headline", "kv-cta", "cap-1", "cap-2"} and visual["shaping_engine"] == "raqm"
    assert all(t["script_ok"] and t["fits"] for t in texts.values()) and visual["source"] == "provider"
    # derived assets, hidden from the upload list, carrying provenance and the AI-generated flag
    async with read_session() as s:
        rows = {r.derived_role: r for r in (await s.execute(select(m.Asset).where(m.Asset.derived_role.like("remake_%")))).scalars()}
    assert set(rows) == {"remake_plate", "remake_visual"}
    assert rows["remake_visual"].parent_asset_id is not None and rows["remake_visual"].media_info["remake"]["ai_generated"] is True
    assert rows["remake_visual"].media_info["remake"]["model"] == "gemini-3.1-flash-image"
    listed = (await client.get(f"{API}/projects/{world.project}/assets")).json()
    assert listed["total"] == 2  # the original and the plate; the remake outputs are derived


async def test_a_locked_scene_element_is_refused_before_any_paid_call(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client, lock=("kv-logo", "kv-plate"))
    response = await start(client, world, "visual", visual_body(world, plate_element_id="kv-plate"))
    assert response.status_code == 409 and "locked" in response.text and not adapter(rig, "image_generation").calls
    assert (await client.get(f"{API}/campaigns/{world.campaign}/remakes")).json()["total"] == 0


async def test_a_lock_set_while_the_run_works_refuses_the_operation_and_keeps_no_output(
    client: httpx.AsyncClient, rig: Any,
) -> None:
    world = await build_world(client)
    image = adapter(rig, "image_generation")
    real = image.generate

    async def lock_then_answer(prompt: str, **kwargs: Any) -> Any:
        await client.put(f"{API}/campaigns/{world.campaign}/locks/kv-plate", json={"reason": "late lock"})
        return await real(prompt, **kwargs)

    image.generate = lock_then_answer  # type: ignore[method-assign]
    run = await finish(client, world, "visual", visual_body(world))
    assert run["status"] == "failed" and run["error"]["code"] == "CONFLICT" and run["result"] is None
    rejected = (await client.get(f"{API}/campaigns/{world.campaign}/operations", params={"kind": "remake", "status": "rejected"})).json()
    assert rejected["total"] == 1 and rejected["items"][0]["rejection"]["code"] == "LOCKED"
    async with read_session() as s:
        assert (await s.execute(select(m.Asset).where(m.Asset.derived_role.like("remake_%")))).first() is None
    versions = (await client.get(f"{API}/campaigns/{world.campaign}/versions")).json()
    assert versions["total"] == 1


async def test_a_live_remake_needs_cost_confirmation_and_the_original(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    refused = await start(client, world, "visual", visual_body(world, confirm_cost=False))
    assert refused.status_code == 422 and refused.json()["error"]["details"][0]["field"] == "confirm_cost"
    no_original = await start(client, world, "visual", {"region_code": "IN-TN", "language": "ta", "confirm_cost": True})
    assert no_original.status_code == 409 and "original_asset_id" in no_original.text
    assert not adapter(rig, "image_generation").calls


async def test_a_provider_failure_creates_no_version_and_is_reported_honestly(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    trace = StepTrace(stage="generating_scene", agent="x", status="failed", provider="google", error_code="PROVIDER_ERROR")
    rig.llm.adapters["image_generation"] = FakeImage(error=LLMError("PROVIDER_ERROR", "The model provider is temporarily unavailable.",
                                                                    retryable=True, trace=trace))
    run = await finish(client, world, "visual", visual_body(world))
    assert run["status"] == "failed" and run["error"]["code"] == "PROVIDER_ERROR" and run["error"]["stage"] == "generating_scene"
    assert (await client.get(f"{API}/campaigns/{world.campaign}/versions")).json()["total"] == 1
    assert (await client.get(f"{API}/campaigns/{world.campaign}/remakes")).json()["total"] == 0


async def test_indic_text_without_shaping_fails_before_the_paid_call(client: httpx.AsyncClient, rig: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    world = await build_world(client)
    monkeypatch.setattr(textrender, "shaping_engine", lambda: "basic")
    run = await finish(client, world, "visual", visual_body(world))
    assert run["status"] == "failed" and run["error"]["code"] == "UNSUPPORTED_CAPABILITY" and not adapter(rig, "image_generation").calls


async def test_text_still_in_the_source_language_is_flagged_and_the_run_is_partial(client: httpx.AsyncClient, rig: Any) -> None:
    items = elements()
    items[3] = element("kv-headline", "headline", "दिवाळी म्हणजे फराळ!", [0.05, 0.12, 0.7, 0.12], language="mr", script="Deva")
    world = await build_world(client, items=items)
    run = await finish(client, world, "visual", visual_body(world))
    assert run["status"] == "partial"
    visual = (await output_of(client, world, run))["visual"]
    flagged = [t for t in visual["texts"] if not t["passed"]]
    assert [t["element_id"] for t in flagged] == ["kv-headline"] and "transcreate" in flagged[0]["problems"][0]
    assert (await output_of(client, world, run))["passed"] is False


async def test_the_real_gateway_adapter_records_the_cost_and_a_tight_budget_refuses_the_call(
    client: httpx.AsyncClient, rig: Any,
) -> None:
    world = await build_world(client)
    sink = InMemoryUsageSink()
    fake = FakeClient([blob_reply(png_bytes((800, 1000), (160, 40, 30)), "image/png")])
    rig.llm = LLMGateway(get_settings(), client=fake, backoff_seconds=0, usage_sink=sink,
                         budget=BudgetGuard(sink, run_budget_usd=0.50, daily_budget_usd=5.0))
    run = await finish(client, world, "visual", visual_body(world))
    assert run["status"] == "completed" and len(fake.calls) == 1
    out = await output_of(client, world, run)
    assert out["estimated_cost_usd"] == pytest.approx(0.067 + 1500 * 0.5 / 1e6 + 8 * 0.5 / 1e6, rel=0.2)
    assert [(e.capability, e.run_id) for e in sink.events] == [("image_generation", run["id"])]

    # the same call with a run budget below one image: refused before it is sent, nothing is stored
    tight_sink, refused_client = InMemoryUsageSink(), FakeClient([blob_reply(png_bytes(), "image/png")])
    rig.llm = LLMGateway(get_settings(), client=refused_client, backoff_seconds=0, usage_sink=tight_sink,
                         budget=BudgetGuard(tight_sink, run_budget_usd=0.01, daily_budget_usd=5.0))
    run = await finish(client, world, "visual", visual_body(world))
    assert run["status"] == "failed" and run["error"]["code"] == "BUDGET_EXCEEDED" and not refused_client.calls
    assert (await client.get(f"{API}/campaigns/{world.campaign}/remakes")).json()["total"] == 1  # only the first one


async def test_visual_is_unavailable_when_no_image_model_is_configured(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    rig.llm = FakeLLM({})
    response = await start(client, world, "visual", visual_body(world))
    assert response.status_code == 503 and "image generation model" in response.json()["error"]["message"]


# --- Remake: Sound -------------------------------------------------------------------------------------------------


async def test_sound_remake_speaks_the_caption_lines_with_the_voice_and_records_the_new_version(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    async with session() as s, s.begin():  # a recorded transcreation gives the lines their English back-translation
        s.add(m.Operation(
            campaign_id=UUID(world.campaign), project_id=UUID(world.project), source_version_id=UUID(world.version),
            result_version_id=UUID(world.version), kind="transcreate", target_element_ids=["cap-1"], params={"lines": [
                {"element_id": "cap-1", "regional_copy": LINES["cap-1"], "back_translation": "When Deepavali comes, the aroma fills the house.",
                 "passed": True}]}, reason="t", claim_ids=[], actor="ai", status="applied", created_at=utcnow()))
    run = await finish(client, world, "sound", {"region_code": "IN-TN", "language": "ta", "confirm_cost": True, "voice": "Sulafat"})
    assert run["status"] == "completed", run["error"]
    out = await output_of(client, world, run)
    sound = out["sound"]
    speech = adapter(rig, "tts")
    assert [(c["text"], c["language"], c["voice"]) for c in speech.calls] == [(LINES["cap-1"], "ta", "Sulafat"), (LINES["cap-2"], "ta", "Sulafat")]
    assert [(x["element_id"], x["start_ms"], x["end_ms"]) for x in sound["lines"]] == [("cap-1", 0, 1500), ("cap-2", 1950, 3450)]
    assert sound["lines"][0]["back_translation"].startswith("When Deepavali") and sound["lines"][1]["back_translation"] is None
    assert (sound["voice"], sound["language_code"], sound["model"], sound["native_speaker_reviewed"]) == ("Sulafat", "ta-IN", "gemini-3.8-flash-tts", False)
    assert out["estimated_cost_usd"] == pytest.approx(0.002) and sound["total_duration_ms"] == 3450 and sound["jingle"] is None
    track = await asset_bytes(client, sound["voiceover_url"])
    assert track[:4] == b"RIFF" and len(track) > 3450 * 48 * 0.9
    new = (await client.get(f"{API}/campaigns/{world.campaign}/versions/{out['result_version_id']}")).json()
    voice = {e["id"]: e for e in new["elements"]}["vo"]
    assert voice["value"]["asset_id"] == sound["voiceover_asset_id"] and voice["value"]["ai_generated"] is True
    assert (voice["language"], voice["script"]) == ("ta", "Taml") and new["parent_id"] == world.version
    op = (await client.get(f"{API}/campaigns/{world.campaign}/operations/{out['id']}")).json()
    assert (op["kind"], op["actor"], op["prompt_version"]) == ("remake", "ai", "remake-sound-v1")


async def test_sound_adds_a_voiceover_and_a_jingle_element_when_the_version_has_none(client: httpx.AsyncClient, rig: Any) -> None:
    items = [e for e in elements() if e["id"] != "vo"]
    world = await build_world(client, items=items)
    run = await finish(client, world, "sound", {"region_code": "IN-TN", "language": "ta", "confirm_cost": True, "jingle": True,
                                                "element_ids": ["cap-2"]})
    assert run["status"] == "completed", run["error"]
    out = await output_of(client, world, run)
    assert len(adapter(rig, "tts").calls) == 1 and len(adapter(rig, "music").calls) == 1 and out["sound"]["jingle"]["model"] == "lyria-002"
    assert out["estimated_cost_usd"] == pytest.approx(0.061)
    new = (await client.get(f"{API}/campaigns/{world.campaign}/versions/{out['result_version_id']}")).json()
    added = {e["id"]: e for e in new["elements"]}
    assert added["remake-voiceover"]["kind"] == "voiceover" and added["remake-music"]["value"]["asset_id"] == out["sound"]["jingle"]["asset_id"]
    assert len(new["elements"]) == len(items) + 2


async def test_a_failed_line_makes_the_run_partial_and_a_failed_jingle_keeps_the_voiceover(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    trace = StepTrace(stage="speaking_lines", agent="x", status="failed", provider="google", error_code="CONTENT_BLOCKED")
    blocked = LLMError("CONTENT_BLOCKED", "The model declined to process this content.", retryable=False, trace=trace)
    rig.llm.adapters["tts"] = FakeSpeech(fail_on={LINES["cap-1"]: blocked})
    rig.llm.adapters["music"] = FakeMusic(error=LLMError("PROVIDER_ERROR", "unavailable", retryable=True, trace=trace))
    run = await finish(client, world, "sound", {"region_code": "IN-TN", "language": "ta", "confirm_cost": True, "jingle": True})
    assert run["status"] == "partial"
    out = await output_of(client, world, run)
    lines = {x["element_id"]: x for x in out["sound"]["lines"]}
    assert lines["cap-1"]["problems"] and lines["cap-1"]["duration_ms"] == 0 and not lines["cap-2"]["problems"]
    assert out["sound"]["jingle"] is None and any("No jingle" in n for n in out["limitations"]) and out["passed"] is False


async def test_a_budget_stop_on_the_first_line_speaks_nothing_more_and_creates_no_version(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    trace = StepTrace(stage="speaking_lines", agent="x", status="failed", provider="google", error_code="BUDGET_EXCEEDED")
    stop = LLMError("BUDGET_EXCEEDED", "The run AI budget ($0.01) was reached, so no further model call was made.", retryable=False, trace=trace)
    speech = FakeSpeech(fail_on={LINES["cap-1"]: stop})
    rig.llm.adapters["tts"] = speech
    run = await finish(client, world, "sound", {"region_code": "IN-TN", "language": "ta", "confirm_cost": True})
    assert run["status"] == "failed" and run["error"]["code"] == "BUDGET_EXCEEDED" and len(speech.calls) == 1
    assert (await client.get(f"{API}/campaigns/{world.campaign}/versions")).json()["total"] == 1


async def test_sound_refuses_a_locked_voiceover_and_too_many_lines(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client, lock=("kv-logo", "vo"))
    locked = await start(client, world, "sound", {"region_code": "IN-TN", "language": "ta", "confirm_cost": True})
    assert locked.status_code == 409 and "locked" in locked.text and not adapter(rig, "tts").calls
    many = [element(f"c{i}", "caption", f"line {i}", None, language="en", script="Latn") for i in range(9)]
    world = await build_world(client, items=many, lock=())
    too_many = await start(client, world, "sound", {"region_code": "IN-TN", "language": "ta", "confirm_cost": True})
    assert too_many.status_code == 409 and "at most 8" in too_many.text


async def test_remake_needs_write_access_and_is_invisible_to_strangers(client: httpx.AsyncClient, rig: Any, client_for: Any) -> None:
    from tests.api.omnicult_support import add_member, workspace_of

    world = await build_world(client)
    await add_member(await workspace_of("alice"), "bob", "viewer")
    bob = client_for({"Authorization": "Bearer dev-bob"})
    forbidden = await bob.post(f"{API}/campaigns/{world.campaign}/remakes/visual", json=visual_body(world))
    assert forbidden.status_code == 403
    assert (await bob.get(f"{API}/campaigns/{world.campaign}/remakes")).status_code == 200
    stranger = client_for({"Authorization": "Bearer dev-mallory"})
    assert (await stranger.get(f"{API}/campaigns/{world.campaign}/remakes")).status_code == 404
    assert (await stranger.post(f"{API}/campaigns/{world.campaign}/remakes/sound", json={"region_code": "IN-TN", "language": "ta"})).status_code == 404


async def test_capabilities_report_models_estimates_and_budgets_without_a_call(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    caps = (await client.get(f"{API}/campaigns/{world.campaign}/remakes/capabilities")).json()
    assert caps["mode"] == "live" and caps["image"]["configured"] and caps["image"]["location"] == "global"
    assert caps["image"]["estimated_cost_usd"] == pytest.approx(0.067 + 3000 * 0.5 / 1e6) and caps["music"]["estimated_cost_usd"] == pytest.approx(0.06)
    assert caps["text_shaping"] in ("raqm", "basic") and "Sulafat" in caps["voices"] and caps["max_voice_lines"] == 8
    assert not adapter(rig, "image_generation").calls
    rig.llm = FakeLLM({})
    assert (await client.get(f"{API}/campaigns/{world.campaign}/remakes/capabilities")).json()["image"]["configured"] is False
