"""Generate studio over HTTP, through the real run engine and database. Every model is a fake (no network, no paid call).

Image: scene from the model, logo, product and Tamil headline composited in code. Voice-over: per-line speech joined into one
track with timings and a pace. Jingle: Lyria clip cut to length. Each stores campaign assets with provenance, appears in the
gallery, and a provider failure is kept on the run and shown, never hidden."""

import io
import wave
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.llm.gateway import LLMError
from app.media import generate as media
from app.schemas.common import StepTrace
from tests.api.generate_support import (  # noqa: F401
    API, TAMIL_HEADLINE, TAMIL_LINES, build_world, finish, image_body, item_of, jingle_body, png_bytes, rig, start, upload, voice_body,
)
from tests.api.omnicult_support import seeded  # noqa: F401

pytestmark = pytest.mark.usefixtures("seeded")


def adapter(rig: Any, name: str) -> Any:
    return rig.llm.adapters[name]


def provider_error(code: str = "PROVIDER_ERROR", message: str = "The provider failed.") -> LLMError:
    return LLMError(code, message, retryable=code != "CONTENT_BLOCKED",  # type: ignore[arg-type]
                    trace=StepTrace(stage="x", agent="fake", status="failed", provider="google", error_code=code))


# --- capabilities and the registry -------------------------------------------------------------------------------


async def test_capabilities_list_the_registry_the_brand_kit_and_the_voices(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    caps = (await client.get(f"{API}/campaigns/{world.campaign}/generate/capabilities")).json()
    assert caps["mode"] == "live"
    assert [(x["kind"], x["run_type"], x["available"]) for x in caps["generators"]] == [
        ("image", "generate_image", True), ("voice", "generate_voice", True), ("jingle", "generate_jingle", True)]
    assert all(x["estimated_cost_usd"] and x["estimated_cost_usd"] > 0 for x in caps["generators"])  # a price before anything runs
    assert [f["id"] for f in caps["formats"]] == ["1:1", "4:5", "9:16", "16:9"]
    assert [v["name"] for v in caps["voice"]["voices"]][:2] == ["Sulafat", "Kore"] and caps["voice"]["voices"][0]["style"] == "Warm"
    assert {"ta", "hi", "mr", "ml", "bn", "en"} <= {x["code"] for x in caps["voice"]["languages"]}
    brand = caps["brand"]
    assert [c["hex"] for c in brand["colours"]] == ["#0E4D58", "#F2A33A"] and brand["tone"] == ["warm", "familial"]
    assert brand["logos"][0]["asset_id"] == world.logo and brand["products"][0]["asset_id"] == world.product
    assert caps["jingle"]["seconds"] == [10, 15, 30] and caps["voice"]["max_lines"] == 8


async def test_a_generator_without_its_model_is_listed_unavailable_and_refused(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    rig.llm.adapters.pop("music")
    caps = (await client.get(f"{API}/campaigns/{world.campaign}/generate/capabilities")).json()
    assert {x["kind"]: x["available"] for x in caps["generators"]} == {"image": True, "voice": True, "jingle": False}
    refused = await start(client, world.campaign, "jingle", jingle_body())
    assert refused.status_code == 503 and "music" in refused.text


async def test_another_user_cannot_reach_the_campaign(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    other = {"Authorization": "Bearer dev-mallory"}
    assert (await client.get(f"{API}/campaigns/{world.campaign}/generate/capabilities", headers=other)).status_code == 404
    assert (await start(client, world.campaign, "image", image_body(world), headers=other)).status_code == 404


# --- image ---------------------------------------------------------------------------------------------------------


async def test_an_image_run_composites_logo_product_and_headline_in_code_and_stores_assets_with_provenance(
    client: httpx.AsyncClient, rig: Any,
) -> None:
    world = await build_world(client)
    photo = await upload(client, world.project, png_bytes((600, 800), (90, 120, 60)), "look.png")
    run = await finish(client, world.campaign, "image", image_body(
        world, headline=TAMIL_HEADLINE, reference_asset_id=photo, purpose="social_post"))
    assert run["status"] == "completed", run["error"]
    assert run["result"]["resource"] == "generation" and run["result"]["ids"] == [run["id"]]
    item = await item_of(client, world.campaign, run)
    # one paid call, the person's idea and the Brand Kit in the prompt, the format as the aspect ratio, the reference passed
    image = adapter(rig, "image_generation")
    assert len(image.calls) == 1 and image.calls[0]["aspect_ratio"] == "4:5" and image.calls[0]["reference_image"]
    prompt = image.calls[0]["prompt"]
    assert "Brass lamps on a teal table" in prompt and "Tamil Nadu" in prompt and "#0E4D58" in prompt and "warm" in prompt
    assert "social media post" in prompt and prompt == item["prompt"]
    # the finished picture: the exact format size, logo and product placed in code, the headline drawn in code in Tamil
    detail = item["image"]
    assert (detail["width"], detail["height"]) == (1080, 1350) and detail["shaping_engine"] == "raqm"
    assert [(p["kind"], p["asset_id"]) for p in detail["placements"]] == [("logo", world.logo), ("product", world.product)]
    assert detail["headline"]["script"] == "Taml" and detail["headline"]["fits"] and detail["headline"]["script_ok"]
    assert all(c["passed"] for c in detail["checks"]) and detail["palette"] == ["#0E4D58", "#F2A33A"]
    assert detail["reference"]["asset_id"] == photo
    final = Image.open(io.BytesIO((await client.get(item["asset"]["url"])).content))
    assert final.size == (1080, 1350)
    scene = Image.open(io.BytesIO((await client.get(detail["scene"]["url"])).content))
    assert scene.size == (800, 1000)  # the model's scene alone, kept for before and after
    # provenance: model, prompt version, cost and inputs, on the item and on the asset row
    assert (item["model"], item["prompt_version"], item["source"], item["mode"]) == ("gemini-3.1-flash-image", "generate-image-v2", "provider", "live")
    assert item["estimated_cost_usd"] == pytest.approx(0.067) and item["request"]["idea"] == "Brass lamps on a teal table"
    async with read_session() as s:
        rows = list((await s.execute(select(m.Asset).where(m.Asset.derived_role == "generate_image"))).scalars())
    final_row = next(r for r in rows if r.media_info["generate"]["part"] == "final")
    info = final_row.media_info["generate"]
    assert info["ai_generated"] is True and info["model"] == "gemini-3.1-flash-image" and info["prompt_version"] == "generate-image-v2"
    assert info["estimated_cost_usd"] == pytest.approx(0.067) and info["request"]["format"] == "4:5" and final_row.parent_asset_id is not None
    listed = (await client.get(f"{API}/projects/{world.project}/assets")).json()
    assert listed["total"] == 3  # the uploaded logo, product and reference photo; the generated files are derived
    # every generated file is also readable through the authorized asset routes (the metadata, not only the bytes)
    for asset_id in (item["asset"]["asset_id"], detail["scene"]["asset_id"]):
        meta = await client.get(f"{API}/assets/{asset_id}")
        assert meta.status_code == 200 and meta.json()["derived_role"] == "generate_image", meta.text
    status = await client.get(f"{API}/assets/{detail['scene']['asset_id']}/status")
    assert status.status_code == 200, status.text
    assert [d["role"] for d in status.json()["derived"]] == ["generate_image"] and status.json()["derived"][0]["id"] == item["asset"]["asset_id"]


@pytest.mark.parametrize(("fmt", "size"), [("1:1", (1080, 1080)), ("9:16", (1080, 1920)), ("16:9", (1920, 1080))])
async def test_every_format_is_produced_at_its_size(client: httpx.AsyncClient, rig: Any, fmt: str, size: tuple[int, int]) -> None:
    world = await build_world(client)
    run = await finish(client, world.campaign, "image", image_body(world, format=fmt))
    assert run["status"] == "completed", run["error"]
    item = await item_of(client, world.campaign, run)
    assert (item["image"]["width"], item["image"]["height"]) == size and item["image"]["headline"] is None
    assert adapter(rig, "image_generation").calls[0]["aspect_ratio"] == fmt


async def test_a_live_run_must_confirm_the_cost_before_any_call(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    response = await start(client, world.campaign, "image", image_body(world, confirm_cost=False))
    assert response.status_code == 422 and "Confirm the estimated cost" in response.text
    assert not adapter(rig, "image_generation").calls
    assert (await client.get(f"{API}/campaigns/{world.campaign}/generate/items")).json()["total"] == 0


async def test_a_headline_in_the_wrong_script_is_refused_before_the_paid_call(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    run = await finish(client, world.campaign, "image", image_body(world, headline="दीपावली की शुभकामनाएं"))  # Devanagari for a Tamil request
    assert run["status"] == "failed" and run["error"]["code"] == "VALIDATION_ERROR" and "Taml" in run["error"]["message"]
    assert not adapter(rig, "image_generation").calls


async def test_an_image_provider_error_is_kept_on_the_run_and_the_generator_stays_available(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    adapter(rig, "image_generation").error = provider_error("CONTENT_BLOCKED", "The image model blocked this request.")
    run = await finish(client, world.campaign, "image", image_body(world))
    assert run["status"] == "failed" and run["error"]["code"] == "CONTENT_BLOCKED" and "blocked" in run["error"]["message"]
    page = (await client.get(f"{API}/campaigns/{world.campaign}/generate/items")).json()
    assert page["total"] == 1 and page["items"][0]["status"] == "failed" and page["items"][0]["error"]["code"] == "CONTENT_BLOCKED"
    assert page["items"][0]["asset"] is None and page["items"][0]["kind"] == "image"
    adapter(rig, "image_generation").error = None  # the same generator runs again
    again = await finish(client, world.campaign, "image", image_body(world))
    assert again["status"] == "completed"


async def test_the_image_reference_must_be_a_stored_image_of_the_project(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    other = await build_world(client)
    refused = await start(client, world.campaign, "image", image_body(world, reference_asset_id=other.product))
    assert refused.status_code == 409 and not adapter(rig, "image_generation").calls


async def test_the_brand_kit_pack_is_not_sent_as_a_reference_while_the_real_product_is_placed_in_code(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    image = adapter(rig, "image_generation")
    run = await finish(client, world.campaign, "image", image_body(world, reference_asset_id=world.product))  # the pack, with the product placed
    assert run["status"] == "completed", run["error"]
    item = await item_of(client, world.campaign, run)
    assert len(image.calls) == 1 and image.calls[0]["reference_image"] is None and "attached image" not in image.calls[0]["prompt"]
    assert item["image"]["reference"] is None and any("not sent to the model as a reference" in n for n in item["limitations"])
    assert [p["kind"] for p in item["image"]["placements"]] == ["logo", "product"]
    # with the placement off the same pack is an ordinary reference, and nothing is dropped
    kept = await item_of(client, world.campaign, await finish(client, world.campaign, "image", image_body(
        world, reference_asset_id=world.product, include_product=False)))
    assert image.calls[1]["reference_image"] and kept["image"]["reference"]["asset_id"] == world.product
    assert not any("not sent to the model" in n for n in kept["limitations"])


# --- voice-over -------------------------------------------------------------------------------------------------


async def test_a_voice_run_speaks_each_line_and_joins_one_track_with_timings(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    run = await finish(client, world.campaign, "voice", voice_body(voice="Kore"))
    assert run["status"] == "completed", run["error"]
    item = await item_of(client, world.campaign, run)
    speech = adapter(rig, "tts")
    assert [c["text"] for c in speech.calls] == TAMIL_LINES and all(c["voice"] == "Kore" and c["language"] == "ta" for c in speech.calls)
    voice = item["voice"]
    assert [(x["start_ms"], x["end_ms"]) for x in voice["lines"]] == [(0, 1500), (1950, 3450)] and voice["total_duration_ms"] == 3450
    assert voice["voice"] == "Kore" and voice["language_code"] == "ta-IN" and len(voice["peaks"]) == 96 and max(voice["peaks"]) == 100
    assert all(x["back_translation"] is None for x in voice["lines"])  # only shown when a transcreation recorded one
    assert voice["native_speaker_reviewed"] is False and any("No native speaker" in n for n in item["limitations"])
    track = (await client.get(item["asset"]["url"])).content
    with wave.open(io.BytesIO(track)) as clip:
        assert round(clip.getnframes() * 1000 / clip.getframerate()) == 3450
    assert item["estimated_cost_usd"] == pytest.approx(0.002) and item["model"] == "gemini-3.8-flash-tts"
    assert item["title"].startswith("Voice-over · Tamil")


@pytest.mark.skipif(not media.can_retime(), reason="ffmpeg is not installed")
async def test_the_pace_is_applied_in_code_without_another_model_call(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    normal = await item_of(client, world.campaign, await finish(client, world.campaign, "voice", voice_body()))
    slow = await item_of(client, world.campaign, await finish(client, world.campaign, "voice", voice_body(pace="slow")))
    fast = await item_of(client, world.campaign, await finish(client, world.campaign, "voice", voice_body(pace="brisk")))
    assert fast["voice"]["total_duration_ms"] < normal["voice"]["total_duration_ms"] < slow["voice"]["total_duration_ms"]
    assert slow["voice"]["pace_applied"] and not normal["voice"]["pace_applied"]
    assert len(adapter(rig, "tts").calls) == 6  # two lines per run, whatever the pace


async def test_a_back_translation_is_shown_only_when_a_transcreation_recorded_one(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    # a transcreate operation records its lines, each with the English back-translation, on the campaign
    async with session() as s, s.begin():
        s.add(m.Operation(
            id=uuid4(), campaign_id=UUID(world.campaign), project_id=UUID(world.project), source_version_id=UUID(world.version),
            result_version_id=UUID(world.version), kind="transcreate", target_element_ids=["cap-1"],
            params={"lines": [{"element_id": "cap-1", "regional_copy": TAMIL_LINES[0],
                               "back_translation": "When Diwali comes the whole house smells of sweets.", "passed": True}]},
            reason="test", claim_ids=[], actor="ai", status="applied", created_at=utcnow()))
    body = voice_body(lines=[{"text": TAMIL_LINES[0], "element_id": "cap-1"}, {"text": TAMIL_LINES[1], "element_id": "cap-2"}])
    item = await item_of(client, world.campaign, await finish(client, world.campaign, "voice", body))
    assert [x["back_translation"] for x in item["voice"]["lines"]] == ["When Diwali comes the whole house smells of sweets.", None]


async def test_one_failed_line_gives_a_partial_track_and_all_failed_gives_the_provider_error(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    speech = adapter(rig, "tts")
    speech.fail_on = {TAMIL_LINES[1]: provider_error("PROVIDER_ERROR", "The speech model failed.")}
    run = await finish(client, world.campaign, "voice", voice_body())
    assert run["status"] == "partial", run["error"]
    item = await item_of(client, world.campaign, run)
    lines = item["voice"]["lines"]
    assert lines[0]["spoken"] and not lines[1]["spoken"] and "speech model failed" in lines[1]["problems"][0]
    speech.fail_on = {t: provider_error("PROVIDER_TIMEOUT", "The speech model timed out.") for t in TAMIL_LINES}
    failed = await finish(client, world.campaign, "voice", voice_body())
    assert failed["status"] == "failed" and failed["error"]["code"] == "PROVIDER_TIMEOUT" and failed["error"]["retryable"] is True


async def test_a_language_the_speech_model_does_not_cover_is_refused(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    response = await start(client, world.campaign, "voice", voice_body(lines=[{"text": "x", "language": "te"}]))
    assert response.status_code == 409 and "te" in response.text and not adapter(rig, "tts").calls


# --- jingle -----------------------------------------------------------------------------------------------------


async def test_a_jingle_is_cut_to_the_requested_length_with_a_fade_and_keeps_the_prompt(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    adapter(rig, "music").seconds = 12.0
    run = await finish(client, world.campaign, "jingle", jingle_body(seconds=10))
    assert run["status"] == "completed", run["error"]
    item = await item_of(client, world.campaign, run)
    music = adapter(rig, "music")
    assert len(music.calls) == 1 and music.calls[0]["stage"] == "composing_jingle"
    prompt = music.calls[0]["prompt"]
    assert "Warm and joyful" in prompt and "Deepavali" in prompt and "Tamil Nadu" in prompt and "flute, tabla" in prompt and len(prompt) <= 600
    assert prompt == item["prompt"]
    jingle = item["jingle"]
    assert jingle["requested_seconds"] == 10 and jingle["generated_seconds"] == 12.0 and jingle["duration_ms"] == 10000
    assert jingle["sample_rate"] == 48000 and jingle["channels"] == 2 and len(jingle["peaks"]) == 96
    assert jingle["peaks"][-1] < jingle["peaks"][0]  # the fade-out
    clip = (await client.get(item["asset"]["url"])).content
    with wave.open(io.BytesIO(clip)) as w:
        assert w.getnframes() == 10 * 48000
    assert item["model"] == "lyria-002" and item["estimated_cost_usd"] == pytest.approx(0.06) and item["language"] == ""


async def test_a_lyria_failure_is_shown_on_the_run_and_the_generator_stays_available(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    adapter(rig, "music").error = provider_error("PROVIDER_ERROR", "Lyria answered HTTP 500.")
    run = await finish(client, world.campaign, "jingle", jingle_body())
    assert run["status"] == "failed" and run["error"]["code"] == "PROVIDER_ERROR" and "HTTP 500" in run["error"]["message"]
    assert "still available" in run["error"]["message"] and run["error"]["stage"] == "composing_jingle"
    items = (await client.get(f"{API}/campaigns/{world.campaign}/generate/items", params={"kind": "jingle"})).json()
    assert items["total"] == 1 and items["items"][0]["status"] == "failed" and items["items"][0]["error"]["code"] == "PROVIDER_ERROR"
    caps = (await client.get(f"{API}/campaigns/{world.campaign}/generate/capabilities")).json()
    assert {x["kind"]: x["available"] for x in caps["generators"]}["jingle"] is True
    adapter(rig, "music").error = None
    assert (await finish(client, world.campaign, "jingle", jingle_body()))["status"] == "completed"


# --- gallery and Studio ----------------------------------------------------------------------------------------------


async def test_the_gallery_lists_every_kind_newest_first_and_filters_by_kind(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    runs = [await finish(client, world.campaign, kind, body) for kind, body in
            (("image", image_body(world)), ("voice", voice_body()), ("jingle", jingle_body()))]
    page = (await client.get(f"{API}/campaigns/{world.campaign}/generate/items")).json()
    assert [i["id"] for i in page["items"]] == [r["id"] for r in reversed(runs)] and page["total"] == 3
    only = (await client.get(f"{API}/campaigns/{world.campaign}/generate/items", params={"kind": "voice"})).json()
    assert [i["kind"] for i in only["items"]] == ["voice"]
    assert (await client.get(f"{API}/campaigns/{world.campaign}/generate/items/{runs[0]['id']}")).json()["kind"] == "image"
    missing = await client.get(f"{API}/campaigns/{world.campaign}/generate/items/{world.campaign}")
    assert missing.status_code == 404


async def test_use_in_studio_adds_the_output_as_an_element_of_a_new_version(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    runs = {k: await finish(client, world.campaign, k, b) for k, b in (("image", image_body(world)), ("voice", voice_body()), ("jingle", jingle_body()))}
    kinds = {}
    for kind, run in runs.items():
        response = await client.post(f"{API}/campaigns/{world.campaign}/generate/items/{run['id']}/use-in-studio", json={"version_id": world.version})
        assert response.status_code == 201, response.text
        used = response.json()
        node = (await client.get(f"{API}/campaigns/{world.campaign}/versions/{used['version_id']}")).json()
        added = next(e for e in node["elements"] if e["id"] == used["element_id"])
        kinds[kind] = added
        assert node["parent_id"] == world.version and node["actor"] == "user" and len(node["elements"]) == 2
        generation = node["settings"]["generation"]  # the new node records the run, model and prompt version of the file it holds
        assert generation["run_id"] == run["id"] and generation["prompt_version"] == f"generate-{kind}-v{2 if kind == 'image' else 1}" and generation["provider"] == "google"
        op = (await client.get(f"{API}/campaigns/{world.campaign}/operations/{used['operation_id']}")).json()
        assert op["kind"] == "manual_edit" and op["actor"] == "user" and op["params"]["generate"]["run_id"] == run["id"]
    item = await item_of(client, world.campaign, runs["image"])
    assert kinds["image"]["kind"] == "scene" and kinds["image"]["value"] == f"asset:{item['asset']['asset_id']}"
    assert kinds["voice"]["kind"] == "voiceover" and kinds["voice"]["value"]["ai_generated"] is True and len(kinds["voice"]["value"]["lines"]) == 2
    assert kinds["voice"]["language"] == "ta" and kinds["voice"]["script"] == "Taml"
    assert kinds["jingle"]["kind"] == "music" and kinds["jingle"]["value"]["model"] == "lyria-002"
    refreshed = await item_of(client, world.campaign, runs["image"])
    assert len(refreshed["studio_version_ids"]) == 1
    again = await client.post(f"{API}/campaigns/{world.campaign}/generate/items/{runs['image']['id']}/use-in-studio", json={"version_id": world.version})
    assert again.status_code == 201  # a different new version (the source was untouched), so the element id is free there
    twice = await client.post(f"{API}/campaigns/{world.campaign}/generate/items/{runs['image']['id']}/use-in-studio",
                              json={"version_id": (await client.get(f"{API}/campaigns/{world.campaign}/versions")).json()["items"][-1]["id"]})
    assert twice.status_code == 409 and "already" in twice.text


async def test_use_in_studio_needs_a_version_and_a_file(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client, version=False)
    run = await finish(client, world.campaign, "image", image_body(world))
    response = await client.post(f"{API}/campaigns/{world.campaign}/generate/items/{run['id']}/use-in-studio")
    assert response.status_code == 409 and "no version" in response.text
    adapter(rig, "music").error = provider_error()
    failed = await finish(client, world.campaign, "jingle", jingle_body())
    refused = await client.post(f"{API}/campaigns/{world.campaign}/generate/items/{failed['id']}/use-in-studio")
    assert refused.status_code == 409 and "no file" in refused.text


async def test_a_locked_element_does_not_block_adding_a_new_one(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    assert (await client.put(f"{API}/campaigns/{world.campaign}/locks/headline", json={"reason": "never change"})).status_code == 200
    run = await finish(client, world.campaign, "jingle", jingle_body())
    response = await client.post(f"{API}/campaigns/{world.campaign}/generate/items/{run['id']}/use-in-studio", json={"version_id": world.version})
    assert response.status_code == 201


# --- the run engine's guarantees ---------------------------------------------------------------------------------


async def test_a_retried_start_with_the_same_idempotency_key_is_one_run_and_one_paid_call(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    headers = {"Idempotency-Key": "generate-jingle-1"}
    first = await start(client, world.campaign, "jingle", jingle_body(), headers=headers)
    again = await start(client, world.campaign, "jingle", jingle_body(), headers=headers)
    assert first.status_code == again.status_code == 202 and first.json()["run_id"] == again.json()["run_id"]
    from tests.conftest import wait_for_run

    assert (await wait_for_run(client, first.json()["run_id"], timeout=60))["status"] == "completed"
    assert len(adapter(rig, "music").calls) == 1


async def test_a_budget_stop_is_the_runs_error_and_nothing_is_stored(client: httpx.AsyncClient, rig: Any) -> None:
    world = await build_world(client)
    adapter(rig, "image_generation").error = provider_error("BUDGET_EXCEEDED", "This call would pass the per-run budget.")
    run = await finish(client, world.campaign, "image", image_body(world))
    assert run["status"] == "failed" and run["error"]["code"] == "BUDGET_EXCEEDED"
    async with read_session() as s:
        assert (await s.execute(select(m.Asset).where(m.Asset.derived_role == "generate_image"))).first() is None
