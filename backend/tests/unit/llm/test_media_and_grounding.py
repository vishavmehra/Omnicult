"""Image generation, text to speech and grounded research adapters on a fake Gen AI client. No network."""

import io
import struct
import wave

import pytest
from google.genai import types

from app.llm import media
from app.llm.budget import BudgetGuard, InMemoryUsageSink, Meter
from app.llm.gateway import LLMError, LLMGateway
from app.llm.grounding import GroundedResearchClient
from tests.unit.llm.genai_fakes import FakeClient, api_error, blob_reply, blocked_prompt, reply, settings


def png(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"


def pcm(seconds: float, rate: int = 24000) -> bytes:
    return b"\x00\x01" * int(seconds * rate)


# --- image generation -------------------------------------------------------------------------------------------


def image_client(script, **kw) -> tuple[media.ImageGenerationClient, FakeClient]:
    fake = FakeClient(script)
    return media.ImageGenerationClient(settings(), client=fake, backoff_seconds=0, **kw), fake


async def test_image_generation_returns_png_bytes_with_metadata_and_never_asks_for_text():
    client, fake = image_client([blob_reply(png(1024, 768), "image/png", text="a note")])
    result = await client.generate("A pongal pot at dawn", aspect_ratio="4:3")
    assert (result.image[:8], result.mime_type, result.width, result.height) == (b"\x89PNG\r\n\x1a\n", "image/png", 1024, 768)
    assert (result.model, result.location, result.text) == ("gemini-3.1-flash-image", "global", "a note")
    sent = fake.calls[0]
    assert sent.config.response_modalities == ["IMAGE"] and sent.config.image_config.aspect_ratio == "4:3"
    prompt = sent.contents[0].parts[0].text
    assert prompt.startswith("A pongal pot at dawn") and media.NO_TEXT_DIRECTIVE in prompt
    assert result.trace.provider == "google" and result.trace.usage.estimated_cost_usd == pytest.approx(0.067 + 8 * 0.5 / 1e6)


async def test_reference_image_is_sent_as_a_second_part_and_text_can_be_allowed():
    client, fake = image_client([blob_reply(png(8, 8), "image/png")])
    await client.generate("restyle this", reference_image=b"\x89PNGref", reference_mime_type="image/png", allow_text=True)
    parts = fake.calls[0].contents[0].parts
    assert media.NO_TEXT_DIRECTIVE not in parts[0].text
    assert parts[1].inline_data.data == b"\x89PNGref" and parts[1].inline_data.mime_type == "image/png"


async def test_image_generation_client_is_built_at_global_even_when_text_uses_a_region(monkeypatch):
    seen, warmed = [], []

    async def warm(configured):
        warmed.append(configured.google_cloud_project)

    monkeypatch.setattr(media.google, "warm_credentials", warm)
    monkeypatch.setattr(media.google, "build_client", lambda s, **kw: seen.append(kw) or FakeClient([blob_reply(png(2, 2), "image/png")]))
    client = media.ImageGenerationClient(settings(google_cloud_location="asia-south1"))
    await client.generate("x")
    assert seen[0]["location"] == "global"
    assert warmed == ["test-project"]  # a client the adapter builds itself waits for the credentials first (off the event loop)


async def test_an_injected_client_never_touches_credentials(monkeypatch):
    async def forbidden(configured):
        raise AssertionError("credentials must not be loaded for an injected client")

    monkeypatch.setattr(media.google, "warm_credentials", forbidden)
    client, _ = image_client([blob_reply(png(2, 2), "image/png")])
    await client.generate("x")


async def test_image_generation_failures_are_typed():
    client, _ = image_client([reply("I cannot draw that")])  # text only, no image part
    with pytest.raises(LLMError) as caught:
        await client.generate("x")
    assert caught.value.code == "PROVIDER_ERROR" and not caught.value.retryable

    client, fake = image_client([blocked_prompt("IMAGE_SAFETY"), blob_reply(png(2, 2), "image/png")])
    with pytest.raises(LLMError) as caught:
        await client.generate("x")
    assert caught.value.code == "CONTENT_BLOCKED" and len(fake.calls) == 1

    client, fake = image_client([api_error(503), blob_reply(png(2, 2), "image/png")])
    assert (await client.generate("x")).trace.retries == 1


async def test_image_inputs_are_validated_before_any_call():
    client, fake = image_client([])
    for kwargs in ({"prompt": "  "}, {"prompt": "x", "aspect_ratio": "7:3"},
                   {"prompt": "x", "reference_image": b"0" * (media.MAX_REFERENCE_BYTES + 1)}):
        with pytest.raises(ValueError):
            await client.generate(**kwargs)
    assert fake.calls == []


async def test_image_budget_blocks_the_call_and_usage_records_one_image():
    sink = InMemoryUsageSink()
    tight = Meter(sink, BudgetGuard(sink, run_budget_usd=0, daily_budget_usd=0.01))
    fake = FakeClient([blob_reply(png(2, 2), "image/png")])
    with pytest.raises(LLMError) as caught:
        await media.ImageGenerationClient(settings(), client=fake, meter=tight).generate("x")
    assert caught.value.code == "BUDGET_EXCEEDED" and fake.calls == []
    ok = FakeClient([blob_reply(png(2, 2), "image/png")])
    await media.ImageGenerationClient(settings(), client=ok, meter=Meter(sink)).generate("x")
    (event,) = sink.events
    assert (event.capability, event.images, event.status) == ("image_generation", 1, "ok") and event.estimated_cost_usd > 0.067


def test_png_size_reads_only_png_headers():
    assert media.png_size(png(640, 480)) == (640, 480) and media.png_size(b"\xff\xd8\xff") is None


# --- text to speech ---------------------------------------------------------------------------------------------


def tts_client(script, **overrides) -> tuple[media.TTSClient, FakeClient]:
    fake = FakeClient(script)
    return media.TTSClient(settings(**overrides), client=fake, backoff_seconds=0), fake


async def test_tts_returns_a_wav_with_the_right_language_voice_and_duration():
    client, fake = tts_client([blob_reply(pcm(2.0), "audio/L16;codec=pcm;rate=24000")])
    audio = await client.synthesize("பொங்கல் வாழ்த்துக்கள்", language="ta", voice="Puck")
    with wave.open(io.BytesIO(audio.wav)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 24000, 48000)
    assert (audio.duration_seconds, audio.language_code, audio.voice, audio.model) == (2.0, "ta-IN", "Puck", "gemini-3.8-flash-tts")
    config = fake.calls[0].config
    assert config.response_modalities == ["AUDIO"] and config.speech_config.language_code == "ta-IN"
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"
    assert audio.trace.usage.estimated_cost_usd > 0


async def test_tts_honours_the_sample_rate_in_the_mime_type():
    client, _ = tts_client([blob_reply(pcm(1.0, 16000), "audio/L16;codec=pcm;rate=16000")])
    audio = await client.synthesize("hello")
    assert audio.sample_rate == 16000 and audio.duration_seconds == 1.0


async def test_tts_validates_input_and_reports_failures():
    client, fake = tts_client([])
    for kwargs in ({"text": ""}, {"text": "x" * (media.MAX_TTS_CHARS + 1)}, {"text": "hi", "language": "fr"},
                   {"text": "hi", "voice": "Kore; drop"}):
        with pytest.raises(ValueError):
            await client.synthesize(**kwargs)
    assert fake.calls == []
    client, _ = tts_client([reply("no audio here")])
    with pytest.raises(LLMError) as caught:
        await client.synthesize("hi")
    assert caught.value.code == "PROVIDER_ERROR"


def test_tts_covers_the_project_languages():
    assert set(media.LANGUAGE_CODES) == {"en", "hi", "mr", "ta", "ml", "bn"}


def test_pcm_to_wav_roundtrip():
    with wave.open(io.BytesIO(media.pcm_to_wav(b"\x00\x00" * 100))) as w:
        assert w.getnframes() == 100


# --- grounded research ------------------------------------------------------------------------------------------


def grounding(*chunks, queries=("pongal date",)) -> types.GroundingMetadata:
    return types.GroundingMetadata(
        web_search_queries=list(queries),
        grounding_chunks=[types.GroundingChunk(web=types.GroundingChunkWeb(uri=uri, title=title)) for uri, title in chunks],
    )


async def test_grounded_research_returns_text_citations_and_metadata():
    meta = grounding(("https://a.example/x", "a.example"), ("https://a.example/x", "dup"), ("https://b.example/y", None))
    fake = FakeClient([reply("Pongal is celebrated in January.", prompt=96, out=20, thoughts=30, grounding=meta)])
    client = GroundedResearchClient(settings(), client=fake, backoff_seconds=0)
    answer = await client.research("Which festival marks the harvest in Tamil Nadu?")
    assert answer.text == "Pongal is celebrated in January." and answer.model == "gemini-3.8-flash"
    assert [(c.url, c.title) for c in answer.citations] == [("https://a.example/x", "a.example"), ("https://b.example/y", None)]
    assert answer.citations[0].retrieved_at.tzinfo is not None and answer.web_search_queries == ["pongal date"]
    assert answer.grounding_metadata["web_search_queries"] == ["pongal date"]
    config = fake.calls[0].config
    assert config.tools[0].google_search is not None and "untrusted_data" in config.system_instruction
    assert answer.trace.usage.output_tokens == 50 and answer.trace.usage.estimated_cost_usd > 0.014  # + per-request grounding


async def test_an_answer_without_sources_has_no_invented_citations_and_no_grounding_charge():
    sink = InMemoryUsageSink()
    client = GroundedResearchClient(settings(), client=FakeClient([reply("Unsure.")]), meter=Meter(sink), backoff_seconds=0)
    answer = await client.research("question")
    assert answer.citations == [] and answer.web_search_queries == [] and answer.grounding_metadata == {}
    assert sink.events[0].estimated_cost_usd < 0.014


async def test_grounded_research_errors_and_configuration():
    client = GroundedResearchClient(settings(), client=FakeClient([blocked_prompt()]), backoff_seconds=0)
    with pytest.raises(LLMError) as caught:
        await client.research("question")
    assert caught.value.code == "CONTENT_BLOCKED"
    with pytest.raises(ValueError):
        await GroundedResearchClient(settings(), client=FakeClient([])).research("  ")
    off = GroundedResearchClient(settings(google_cloud_project=None))
    assert not off.is_configured()
    with pytest.raises(LLMError) as caught:
        await off.research("q")
    assert caught.value.code == "PROVIDER_NOT_CONFIGURED"


# --- through the gateway ----------------------------------------------------------------------------------------


async def test_gateway_exposes_every_capability_behind_deadlines_and_one_meter():
    gw = LLMGateway(settings(), client=FakeClient(), usage_sink=InMemoryUsageSink())
    for name in ("embeddings", "vision", "transcribe", "image_generation", "tts", "grounded_research"):
        wrapper = gw.capability(name)
        assert wrapper is not None and wrapper.is_configured(), name
        assert wrapper._provider == "google" and wrapper._model
    assert gw.capability("embeddings")._batch_size == 1
    assert LLMGateway(settings(google_cloud_project=None)).capability("image_generation") is None
    assert LLMGateway(settings(), fixture=True).capability("tts") is None
    assert LLMGateway(settings(gemini_model_image="gemini-3.8-flash")).capability("image_generation") is None  # wrong capability


def test_speech_pcm_unwraps_a_wav_so_its_header_is_never_played() -> None:
    from app.llm.media import pcm_to_wav, speech_pcm

    pcm = bytes([1, 0, 2, 0, 3, 0, 4, 0])
    assert speech_pcm(pcm, "audio/L16;codec=pcm;rate=24000") == (pcm, 24000)
    assert speech_pcm(pcm_to_wav(pcm, 22050), "audio/wav") == (pcm, 22050)  # the header is gone, the rate comes from it
