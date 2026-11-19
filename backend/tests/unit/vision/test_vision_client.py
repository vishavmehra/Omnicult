"""VisionClient on a fake Gen AI client: multimodal-model gate, observation parsing, failure statuses."""

import json
from uuid import uuid4

from app.llm.budget import BudgetGuard, InMemoryUsageSink, Meter
from app.llm.vision import VisionClient
from tests.unit.llm.genai_fakes import FakeClient, api_error, blocked_prompt, reply, settings

MODEL = "gemini-3.5-flash-lite"  # vision runs on the fast model (registry.capability_model)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
ASSET = uuid4()


def client_for(script, *, meter=None, **overrides) -> tuple[VisionClient, FakeClient]:
    fake = FakeClient(script)
    return VisionClient(settings(**overrides), client=fake, meter=meter, backoff_seconds=0), fake


async def test_visible_elements_become_observations():
    output = {"observations": [
        {"kind": "text_in_image", "description": "Find your next great escape", "location": "top", "box_2d": [100, 50, 200, 950]},
        {"kind": "text", "description": "Explore the collection", "location": "bottom-right"},
        {"kind": "mood", "description": "orange   circle", "location": None},
    ]}
    client, fake = client_for([reply(json.dumps(output), prompt=600, out=60)])
    result = await client.observe(ASSET, PNG, "image/png")

    assert (result.status.status, result.status.provider, result.status.model_id) == ("analyzed", "google", MODEL)
    assert [(o.id, o.kind) for o in result.observations] == [
        ("vis-1", "text_in_image"), ("vis-2", "text_in_image"), ("vis-3", "other")]
    assert result.observations[2].description == "orange circle" and result.observations[0].asset_id == ASSET
    # box_2d [ymin, xmin, ymax, xmax] on a 0-1000 grid becomes [x, y, w, h] in 0-1; no box, no bbox
    assert result.observations[0].bbox == [0.05, 0.1, 0.9, 0.1] and result.observations[1].bbox is None
    sent = fake.calls[0]
    assert sent.model == MODEL and sent.config.temperature == 1.0 and sent.config.response_mime_type == "application/json"
    assert sent.config.response_json_schema is None  # JSON mode; with the schema enforced the models left the boxes out
    assert sent.config.thinking_config is None  # flash-lite has no thinking levels
    image_part = sent.contents[0].parts[1]
    assert image_part.inline_data.mime_type == "image/png" and image_part.inline_data.data == PNG
    assert result.trace.status == "completed" and result.trace.prompt_version == "vision-observe-v4"
    assert result.trace.usage.input_tokens == 600 and result.trace.usage.estimated_cost_usd > 0


async def test_non_multimodal_or_missing_models_never_receive_images():
    for overrides, message in (
        ({"gemini_model_fast": "some-text-only-model"}, "not a registered multimodal Gemini model"),
        ({"gemini_model_fast": "gemini-embedding-2"}, "not a registered multimodal Gemini model"),
    ):
        client, fake = client_for([], **overrides)
        result = await client.observe(ASSET, PNG, "image/png")
        assert not client.is_configured() and fake.calls == []
        assert result.status.status == "unavailable" and message in (result.status.message or "")
        assert result.observations == [] and result.trace is None
    unconfigured = VisionClient(settings(google_cloud_project=None))
    result = await unconfigured.observe(ASSET, PNG, "image/png")
    assert result.status.status == "unavailable" and "credentials are not configured" in result.status.message


async def test_a_reply_that_boxes_nothing_it_saw_is_asked_for_once_more():
    unboxed = {"observations": [{"kind": "object", "description": "a tin"}]}
    boxed = {"observations": [{"kind": "object", "description": "a tin", "box_2d": [500, 500, 800, 900]}]}
    client, fake = client_for([reply(json.dumps(unboxed)), reply(json.dumps(boxed))])
    result = await client.observe(ASSET, PNG, "image/png")
    assert len(fake.calls) == 2 and result.observations[0].bbox == [0.5, 0.5, 0.4, 0.3]
    client, fake = client_for([reply(json.dumps(unboxed)), reply(json.dumps(unboxed))])
    result = await client.observe(ASSET, PNG, "image/png")
    assert len(fake.calls) == 2 and result.status.status == "analyzed" and result.observations[0].bbox is None  # the second answer stands
    client, fake = client_for([reply(json.dumps({"observations": [{"kind": "color_or_layout", "description": "teal"}]}))])
    assert (await client.observe(ASSET, PNG, "image/png")).status.status == "analyzed" and len(fake.calls) == 1  # nothing to box


async def test_unsupported_images_fail_without_a_request():
    client, fake = client_for([reply("{}")])
    for image, content_type in ((PNG, "image/gif"), (b"", "image/png"), (b"0" * (5 * 1024 * 1024 + 1), "image/png")):
        result = await client.observe(ASSET, image, content_type)
        assert result.status.status == "failed"
    assert fake.calls == []


async def test_invalid_output_and_provider_errors_fail_with_a_message():
    client, fake = client_for([reply("I see a mountain."), reply("Still no JSON.")])
    result = await client.observe(ASSET, PNG, "image/png")
    assert len(fake.calls) == 2  # an unparseable reply is asked for once more, then the frame fails
    assert result.status.status == "failed" and "did not match" in result.status.message
    assert result.trace.error_code == "RUN_FAILED"

    client, fake = client_for([api_error(503)] * 3)
    result = await client.observe(ASSET, PNG, "image/png")
    assert len(fake.calls) == 3  # the first request plus llm_max_retries=2
    assert result.status.status == "failed" and "text analysis continues" in result.status.message
    assert result.trace.error_code == "PROVIDER_ERROR"


async def test_a_safety_block_is_reported_as_content_blocked_without_failing_the_text_analysis():
    client, fake = client_for([blocked_prompt("IMAGE_SAFETY")])
    result = await client.observe(ASSET, PNG, "image/png")
    assert len(fake.calls) == 1 and result.status.status == "failed"
    assert "safety filter" in result.status.message and result.trace.error_code == "CONTENT_BLOCKED"


async def test_budget_exhaustion_fails_the_image_but_keeps_the_text_analysis():
    sink = InMemoryUsageSink()
    meter = Meter(sink, BudgetGuard(sink, run_budget_usd=0, daily_budget_usd=0.000001))
    client, fake = client_for([reply("{}")], meter=meter)
    result = await client.observe(ASSET, PNG, "image/png")
    assert fake.calls == [] and result.status.status == "failed" and result.trace.error_code == "BUDGET_EXCEEDED"
    assert "text analysis continues" in result.status.message


def test_default_model_is_registered_as_multimodal():
    from app.llm.registry import spec_for

    assert spec_for(settings().gemini_model_default).multimodal_input
