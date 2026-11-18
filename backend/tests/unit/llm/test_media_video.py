"""The Veo video adapter on a scripted HTTP fake: the long-running operation flow, its failures and its metering. No network."""

import base64

import pytest

from app.llm import media
from app.llm.budget import BudgetGuard, InMemoryUsageSink, Meter, run_scope
from app.llm.gateway import LLMError, ProviderError
from tests.unit.llm.genai_fakes import settings
from tests.unit.llm.test_media_and_grounding import png

BASE = "https://us-central1-aiplatform.googleapis.com/v1/projects/test-project/locations/us-central1/publishers/google/models/veo-3.1-fast-generate-001"
OPERATION = "projects/test-project/locations/us-central1/publishers/google/models/veo-3.1-fast-generate-001/operations/op-1234"
CLIP = b"\x00\x00\x00\x18ftypmp42" + b"\x01" * 64


def vertex(**kw):
    return settings(google_genai_backend="vertex", google_cloud_project="test-project", **kw)


def done(videos=None, **response):
    return {"name": OPERATION, "done": True, "response": {"@type": "type.googleapis.com/cloud.ai.large_models.vision.GenerateVideoResponse",
                                                          "videos": videos if videos is not None else [], **response}}


def inline(data: bytes = CLIP) -> list[dict]:
    return [{"bytesBase64Encoded": base64.b64encode(data).decode(), "mimeType": "video/mp4"}]


class Script:
    """Answers `predictLongRunning` once and each `fetchPredictOperation` from the list; records every call."""

    def __init__(self, polls: list, *, start: dict | Exception | None = None) -> None:
        self.polls, self.start, self.calls, self.slept = list(polls), start if start is not None else {"name": OPERATION}, [], []

    async def __call__(self, url, body, headers):
        self.calls.append((url, body))
        if url.endswith(":predictLongRunning"):
            if isinstance(self.start, Exception):
                raise self.start
            return self.start
        item = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
        if isinstance(item, Exception):
            raise item
        return item

    async def sleeper(self, seconds: float) -> None:
        self.slept.append(seconds)


def client(script: Script, *, sink: InMemoryUsageSink | None = None, run_budget: float = 0, daily: float = 5, **kw) -> media.VideoClient:
    sink = sink or InMemoryUsageSink()
    meter = Meter(sink, BudgetGuard(sink, run_budget_usd=run_budget, daily_budget_usd=daily))
    kw = {"poll_seconds": 5.0, "max_wait_seconds": 20.0, **kw}
    return media.VideoClient(vertex(**{"llm_max_retries": kw.pop("retries", 1)}), meter=meter, poster=script, sleeper=script.sleeper,
                             backoff_seconds=0, **kw)


async def test_a_clip_is_started_once_polled_until_done_and_read_from_the_inline_bytes():
    script = Script([{"name": OPERATION, "done": False}, {"name": OPERATION}, done(inline())])
    sink = InMemoryUsageSink()
    veo = client(script, sink=sink)
    assert veo.is_configured() and veo.model == "veo-3.1-fast-generate-001"
    clip = await veo.generate("A calm festive shot", start_image=png(8, 8), seconds=6, aspect_ratio="9:16", negative_prompt="text, watermark")
    starts = [c for c in script.calls if c[0].endswith(":predictLongRunning")]
    polls = [c for c in script.calls if c[0].endswith(":fetchPredictOperation")]
    assert len(starts) == 1 and len(polls) == 3 and script.slept == [5.0, 5.0, 5.0]  # one paid request; waiting is free
    url, body = starts[0]
    assert url == f"{BASE}:predictLongRunning" and polls[0][0] == f"{BASE}:fetchPredictOperation"
    assert polls[0][1] == {"operationName": OPERATION}
    instance, parameters = body["instances"][0], body["parameters"]
    assert instance["prompt"] == "A calm festive shot" and instance["image"]["mimeType"] == "image/png"
    assert base64.b64decode(instance["image"]["bytesBase64Encoded"]) == png(8, 8)
    assert parameters == {"sampleCount": 1, "durationSeconds": 6, "aspectRatio": "9:16", "resolution": "720p", "generateAudio": False,
                          "negativePrompt": "text, watermark"}  # generateAudio defaults to true on Veo: it is always sent as false
    assert "storageUri" not in parameters  # delivered inline: no bucket
    assert (clip.video, clip.mime_type, clip.seconds, clip.operation_id, clip.with_start_image) == (CLIP, "video/mp4", 6, "op-1234", True)
    assert (clip.model, clip.location) == ("veo-3.1-fast-generate-001", "us-central1")
    assert clip.trace.usage.estimated_cost_usd == pytest.approx(6 * 0.08)  # the video-only 720p rate, per generated second
    assert [(e.capability, e.status) for e in sink.events] == [("video", "ok")]
    assert sink.events[0].estimated_cost_usd == pytest.approx(0.48) and sink.events[0].audio_seconds == 0


async def test_without_a_start_image_the_request_is_text_only():
    script = Script([done(inline())])
    await client(script).generate("A shot", seconds=4, aspect_ratio="16:9")
    assert "image" not in script.calls[0][1]["instances"][0] and script.calls[0][1]["parameters"]["durationSeconds"] == 4


async def test_a_failed_start_request_is_typed_not_billed_and_never_retried():
    script = Script([done(inline())], start=ProviderError("HTTP 400", transient=False))
    sink = InMemoryUsageSink()
    with pytest.raises(LLMError) as caught:
        await client(script, sink=sink).generate("x")
    assert caught.value.code == "PROVIDER_ERROR" and "bill" not in caught.value.message and not caught.value.retryable
    assert len(script.calls) == 1 and sink.events[0].status == "error" and not sink.events[0].estimated_cost_usd

    transient = Script([done(inline())], start=ProviderError("HTTP 503", transient=True))
    with pytest.raises(LLMError) as caught:
        await client(transient).generate("x")
    assert caught.value.code == "PROVIDER_ERROR" and caught.value.retryable and len(transient.calls) == 1  # a second start could bill twice


async def test_an_operation_without_a_name_is_a_failure():
    script = Script([done(inline())], start={})
    with pytest.raises(LLMError) as caught:
        await client(script).generate("x")
    assert caught.value.code == "PROVIDER_ERROR" and len(script.calls) == 1


async def test_a_transient_poll_failure_is_retried_but_the_start_is_not_repeated():
    script = Script([ProviderError("HTTP 503", transient=True), done(inline())])
    clip = await client(script, retries=2).generate("x")
    assert clip.video == CLIP and sum(c[0].endswith(":predictLongRunning") for c in script.calls) == 1


async def test_a_clip_that_never_finishes_times_out_without_a_retry_and_counts_as_spent():
    script = Script([{"name": OPERATION, "done": False}])
    sink = InMemoryUsageSink()
    with pytest.raises(LLMError) as caught:
        await client(script, sink=sink, poll_seconds=5.0, max_wait_seconds=20.0).generate("x", seconds=8)
    error = caught.value
    assert error.code == "PROVIDER_TIMEOUT" and not error.retryable and "may still bill" in error.message and "20 seconds" in error.message
    assert sum(c[0].endswith(":fetchPredictOperation") for c in script.calls) == 4  # 20 s at 5 s
    assert sink.events[0].status == "error" and sink.events[0].error_code == "PROVIDER_TIMEOUT"
    assert sink.events[0].estimated_cost_usd == pytest.approx(8 * 0.08)  # billing is unknown after an accepted request: counted


async def test_an_operation_that_reports_an_error_is_failed_and_costs_nothing():
    script = Script([{"name": OPERATION, "done": True, "error": {"code": 13, "message": "internal"}}])
    sink = InMemoryUsageSink()
    with pytest.raises(LLMError) as caught:
        await client(script, sink=sink).generate("x")
    assert caught.value.code == "PROVIDER_ERROR" and "bill" not in caught.value.message
    assert sink.events[0].estimated_cost_usd == 0.0


async def test_a_filtered_video_is_content_blocked_and_costs_nothing():
    script = Script([done([], raiMediaFilteredCount=1, raiMediaFilteredReasons=["blocked"])])
    sink = InMemoryUsageSink()
    with pytest.raises(LLMError) as caught:
        await client(script, sink=sink).generate("x")
    assert caught.value.code == "CONTENT_BLOCKED" and not caught.value.retryable
    assert sink.events[0].estimated_cost_usd == 0.0 and "may still bill" not in caught.value.message


async def test_a_delivery_that_is_not_inline_bytes_is_refused_not_guessed():
    script = Script([done([{"gcsUri": "gs://bucket/clip.mp4", "mimeType": "video/mp4"}])])
    with pytest.raises(LLMError) as caught:
        await client(script).generate("x")
    assert caught.value.code == "PROVIDER_ERROR" and not caught.value.retryable


async def test_a_clip_over_the_budget_is_refused_before_any_request():
    script = Script([done(inline())])
    sink = InMemoryUsageSink()
    with run_scope("run-1"), pytest.raises(LLMError) as caught:
        await client(script, sink=sink, run_budget=0.30).generate("x", seconds=6)  # 6 s is about $0.48
    assert caught.value.code == "BUDGET_EXCEEDED" and "run" in caught.value.message and not script.calls
    with pytest.raises(LLMError) as caught:
        await client(script, sink=sink, daily=0.30).generate("x", seconds=6)
    assert caught.value.code == "BUDGET_EXCEEDED" and not script.calls
    with run_scope("run-2"):  # 6 s fits the default per-run budget of $0.50; 8 s ($0.64) does not
        await client(script, run_budget=0.50).generate("x", seconds=6)
        with pytest.raises(LLMError):
            await client(Script([done(inline())]), run_budget=0.50).generate("x", seconds=8)


def test_the_price_table_prices_video_by_the_second_and_registers_the_model():
    from app.llm import registry

    assert registry.supports("veo-3.1-fast-generate-001", "video") and registry.supports("veo-3.1-lite-generate-001", "video")
    assert registry.estimate_cost("veo-3.1-fast-generate-001", video_seconds=8).usd == pytest.approx(0.64)
    assert registry.estimate_cost("veo-3.1-fast-generate-001", video_seconds=6).usd < 0.50  # fits the default per-run budget
    assert registry.capability_model(settings(), "video") == "veo-3.1-fast-generate-001"


async def test_bad_input_and_unconfigured_backends_are_caught_before_a_call():
    script = Script([done(inline())])
    veo = client(script)
    for bad in ({"seconds": 5}, {"aspect_ratio": "4:5"}, {"start_image": b"x", "start_mime_type": "image/gif"}):
        with pytest.raises(ValueError):
            await veo.generate("x", **bad)
    with pytest.raises(ValueError):
        await veo.generate("   ")
    assert not script.calls
    assert not media.VideoClient(settings(google_genai_backend="gemini_api", gemini_api_key="k")).is_configured()
