"""Extra reference images for image generation, and the Lyria music adapter, on fakes. No network."""

import base64
import io
import wave

import pytest

from app.llm import media
from app.llm.budget import BudgetGuard, InMemoryUsageSink, Meter
from app.llm.gateway import LLMError
from tests.unit.llm.genai_fakes import FakeClient, blob_reply, settings
from tests.unit.llm.test_media_and_grounding import png


def wav_bytes(seconds: float = 1.0, rate: int = 48000, channels: int = 2) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(seconds * rate * channels))
    return out.getvalue()


def vertex(**kw):
    return settings(google_genai_backend="vertex", google_cloud_project="test-project", **kw)


async def test_extra_reference_images_follow_the_first_reference_in_order():
    fake = FakeClient([blob_reply(png(8, 8), "image/png")])
    client = media.ImageGenerationClient(settings(), client=fake, backoff_seconds=0)
    await client.generate("remake", reference_image=b"layout", extra_reference_images=[(b"pack", "image/jpeg")])
    parts = fake.calls[0].contents[0].parts
    assert [p.inline_data.data for p in parts[1:]] == [b"layout", b"pack"] and parts[2].inline_data.mime_type == "image/jpeg"


async def test_extra_references_need_a_first_reference_and_are_bounded():
    client = media.ImageGenerationClient(settings(), client=FakeClient([]), backoff_seconds=0)
    with pytest.raises(ValueError):
        await client.generate("x", extra_reference_images=[(b"a", "image/png")])
    with pytest.raises(ValueError):
        await client.generate("x", reference_image=b"a", extra_reference_images=[(b"b", "image/png")] * 3)


async def test_music_posts_to_the_vertex_predict_url_and_reads_the_clip():
    seen = []

    async def poster(url, body, headers):
        seen.append((url, body))
        return {"predictions": [{"bytesBase64Encoded": base64.b64encode(wav_bytes(2.0)).decode(), "mimeType": "audio/wav"}]}

    sink = InMemoryUsageSink()
    client = media.MusicClient(vertex(), meter=Meter(sink, BudgetGuard(sink, run_budget_usd=0, daily_budget_usd=5)), poster=poster, backoff_seconds=0)
    assert client.is_configured()
    clip = await client.generate("warm festive jingle", seed=7)
    url, body = seen[0]
    assert url == ("https://us-central1-aiplatform.googleapis.com/v1/projects/test-project/locations/us-central1"
                   "/publishers/google/models/lyria-002:predict")
    assert body["instances"][0] == {"prompt": "warm festive jingle", "negative_prompt": "vocals, speech", "seed": 7}
    assert body["parameters"] == {}  # a seed and sample_count are mutually exclusive
    assert (clip.duration_seconds, clip.sample_rate, clip.channels, clip.location) == (2.0, 48000, 2, "us-central1")
    assert clip.trace.usage.estimated_cost_usd == pytest.approx(0.06)
    assert [e.capability for e in sink.events] == ["music"] and sink.events[0].estimated_cost_usd == pytest.approx(0.06)


async def test_music_is_unconfigured_off_vertex_and_refuses_over_budget_without_a_call():
    assert not media.MusicClient(settings(google_genai_backend="gemini_api", gemini_api_key="k")).is_configured()
    called = []

    async def poster(url, body, headers):
        called.append(1)
        return {}

    sink = InMemoryUsageSink()
    tight = Meter(sink, BudgetGuard(sink, run_budget_usd=0, daily_budget_usd=0.01))
    with pytest.raises(LLMError) as caught:
        await media.MusicClient(vertex(), meter=tight, poster=poster).generate("x")
    assert caught.value.code == "BUDGET_EXCEEDED" and not called


async def test_music_failures_are_typed_and_a_bad_clip_is_not_returned():
    async def empty(url, body, headers):
        return {"predictions": [{}]}

    with pytest.raises(LLMError) as caught:
        await media.MusicClient(vertex(), poster=empty, backoff_seconds=0).generate("x")
    assert caught.value.code == "PROVIDER_ERROR" and not caught.value.retryable

    async def garbage(url, body, headers):
        return {"predictions": [{"bytesBase64Encoded": base64.b64encode(b"not a wav").decode()}]}

    with pytest.raises(LLMError) as caught:
        await media.MusicClient(vertex(), poster=garbage, backoff_seconds=0).generate("x")
    assert caught.value.code == "PROVIDER_ERROR"


def test_wav_info_derives_the_duration_from_the_bytes():
    assert media.wav_info(wav_bytes(1.5, rate=24000, channels=1)) == (24000, 1, 1.5)


async def test_music_reads_the_documented_audio_content_field_as_well():
    async def poster(url, body, headers):
        return {"predictions": [{"audioContent": base64.b64encode(wav_bytes(1.0)).decode(), "mimeType": "audio/wav"}],
                "model": "lyria-002"}

    clip = await media.MusicClient(vertex(), poster=poster, backoff_seconds=0).generate("festive")
    assert (clip.duration_seconds, clip.model) == (1.0, "lyria-002")
    assert clip.wav.startswith(b"RIFF")  # the bytes are stored as they came: a WAV


async def test_music_asks_the_shared_credentials_for_its_token_and_never_runs_a_new_lookup(monkeypatch):
    class Credentials:
        valid, token, refreshed = False, None, 0

        def refresh(self, request):
            self.refreshed += 1
            self.token, self.valid = "token-from-refresh", True

    shared = Credentials()
    monkeypatch.setattr(media.google, "load_credentials", lambda: shared)

    def no_lookup(*args, **kwargs):  # google.auth.default() runs the gcloud CLI (48 to 200 s)
        raise AssertionError("a fresh Application Default Credentials lookup was started")

    monkeypatch.setattr("google.auth.default", no_lookup)
    first = await media.MusicClient._headers()
    second = await media.MusicClient._headers()
    assert first["Authorization"] == "Bearer token-from-refresh" and first["Content-Type"] == "application/json"
    assert second == first and shared.refreshed == 1  # a valid token is reused, not refreshed per call


async def test_music_http_statuses_become_typed_errors_and_the_api_message_is_logged_not_shown(caplog):
    import respx

    url = "https://us-central1-aiplatform.googleapis.com/v1/projects/test-project/locations/us-central1/publishers/google/models/lyria-002:predict"
    client = media.MusicClient(vertex(llm_max_retries=0), backoff_seconds=0)

    async def headers():
        return {}

    client._headers = headers  # no token: the HTTP layer is what is under test
    with respx.mock:
        route = respx.post(url)
        route.respond(400, json={"error": {"status": "INVALID_ARGUMENT", "message": "prompt rejected: names an artist"}})
        with caplog.at_level("WARNING", logger="app.llm.media"), pytest.raises(LLMError) as caught:
            await client.generate("in the style of someone")
        assert caught.value.code == "PROVIDER_ERROR" and not caught.value.retryable
        assert "artist" not in caught.value.message
        record = next(r for r in caplog.records if r.getMessage() == "provider error")
        assert record.provider_http == 400 and record.provider_status == "INVALID_ARGUMENT" and "artist" in record.provider_detail
        route.respond(504, text="gateway timeout")
        with pytest.raises(LLMError) as caught:
            await client.generate("x")
        assert caught.value.code == "PROVIDER_TIMEOUT" and caught.value.retryable
        route.respond(200, json={"predictions": [{"audioContent": base64.b64encode(wav_bytes(1.0)).decode()}]})
        assert (await client.generate("x")).duration_seconds == 1.0
