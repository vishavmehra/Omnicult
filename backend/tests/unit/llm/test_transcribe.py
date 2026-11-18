"""The `transcribe` capability on a fake Gen AI client: gates, validation of the model's timed segments, failure statuses,
metering and the gateway wrapper. No network, no audio file."""

import asyncio
import json

import pytest

from app.llm import gateway as gateway_module
from app.llm.budget import BudgetGuard, InMemoryUsageSink, Meter
from app.llm.gateway import LLMError, LLMGateway
from app.llm.transcribe import TranscribeClient, parse_clock
from tests.unit.llm.genai_fakes import FakeClient, api_error, blocked_prompt, reply, settings

MODEL = "gemini-3.8-flash"
WAV = b"RIFF" + b"0" * 64
MARATHI = "दिवाळी आली की घरभर फराळाचा सुगंध दरवळतो."


def client_for(script, *, meter=None, **overrides) -> tuple[TranscribeClient, FakeClient]:
    fake = FakeClient(script)
    return TranscribeClient(settings(**overrides), client=fake, meter=meter, backoff_seconds=0), fake


async def run(client: TranscribeClient, **kwargs):
    return await client.transcribe(WAV, "audio/wav", language=kwargs.pop("language", "mr"),
                                   duration_ms=kwargs.pop("duration_ms", 9000), stage="transcribing", agent="transcribe")


async def test_speech_becomes_timed_segments_in_the_spoken_script():
    output = {"segments": [
        {"start": "00:05.0", "end": "00:08.9", "text": "  Free   delivery before Bhau Beej ", "language": "EN"},
        {"start": "00:00.5", "end": "00:04.4", "text": MARATHI, "language": "mr"},
        {"start": 6.5, "end": 99, "text": "Order today", "language": "not a code!"},  # numbers, past the clip, bad language
        {"start": "00:07.0", "end": "00:02.0", "text": "End before start", "language": None},
        {"start": "soon", "end": None, "text": "No usable time"},
        {"start": "00:01.0", "end": "00:02.0", "text": "   "},  # no words: dropped
    ], "music_mood": "  warm,   festive  "}
    client, fake = client_for([reply(json.dumps(output, ensure_ascii=False), prompt=900, out=120)])
    result = await run(client)

    assert (result.status.status, result.status.provider, result.status.model_id, result.status.message) == ("transcribed", "google", MODEL, None)
    assert [(s.id, s.start_ms, s.end_ms, s.language, s.text) for s in result.segments] == [
        ("x1", 500, 4400, "mr", MARATHI),
        ("x2", 5000, 8900, "en", "Free delivery before Bhau Beej"),
        ("x3", 6500, 9000, "mr", "Order today"),  # end clamped to the clip; an unusable language falls back to the hint
        ("x4", 7000, None, "mr", "End before start"),
        ("x5", None, None, "mr", "No usable time"),  # untimed segments come last
    ]
    assert all(s.source == "transcription" for s in result.segments) and result.music_mood == "warm, festive"
    sent = fake.calls[0]
    assert sent.model == MODEL and sent.config.temperature == 1.0 and sent.config.response_mime_type == "application/json"
    assert sent.config.response_json_schema["properties"]["segments"]["maxItems"] == 80  # a loop cannot run past it
    text_part, audio_part = sent.contents[0].parts
    assert audio_part.inline_data.mime_type == "audio/wav" and audio_part.inline_data.data == WAV
    assert "ISO 639-1 code mr" in text_part.text
    assert result.trace.status == "completed" and result.trace.prompt_version == "transcribe-v1"
    assert result.trace.schema_version == "transcript-v1" and result.trace.usage.input_tokens == 900
    assert result.trace.usage.estimated_cost_usd > 0


async def test_a_decoding_loop_is_cut_short_and_a_cut_off_answer_is_reported_as_such():
    loop = [{"start": f"00:{i:02d}.0", "end": f"00:{i + 1:02d}.0", "text": "आमोद."} for i in range(20, 26)]
    real = [{"start": "00:01.0", "end": "00:03.0", "text": "Every bond, a little sweeter."}]
    client, _ = client_for([reply(json.dumps({"segments": real + loop}, ensure_ascii=False))])
    result = await run(client)
    assert [s.text for s in result.segments] == ["Every bond, a little sweeter.", "आमोद.", "आमोद."]  # two repeats are speech, the rest a loop
    again = [{"start": f"00:0{i}.0", "end": f"00:0{i}.5", "text": text} for i, text in enumerate(["a", "b", "a", "b", "a"])]
    client, _ = client_for([reply(json.dumps({"segments": again}))])
    assert [s.text for s in (await run(client)).segments] == ["a", "b", "a", "b", "a"]  # alternating text is not a run

    truncated = '{"segments": [{"start": "00:01.0", "end": "00:02.0", "text": "' + "आमोद " * 400
    client, _ = client_for([reply(truncated, prompt=1255, out=5048)])  # 3000 + the model's 2048 thinking headroom
    result = await run(client)
    assert result.status.status == "failed" and "cut off at its length limit" in result.status.message
    assert result.trace.error_code == "RUN_FAILED" and result.trace.usage.output_tokens == 5048


async def test_a_clip_without_speech_is_transcribed_with_no_segments_and_keeps_the_music_mood():
    client, _ = client_for([reply(json.dumps({"segments": [], "music_mood": "calm, instrumental"}))])
    result = await run(client, language=None)
    assert result.status.status == "transcribed" and result.segments == [] and result.music_mood == "calm, instrumental"
    assert "No speech" in result.status.message


async def test_models_without_audio_support_and_missing_credentials_are_unavailable_and_nothing_is_sent():
    for overrides, message in (
        ({"gemini_model_default": "some-text-only-model"}, "not a registered audio-capable Gemini model"),
        ({"gemini_model_default": "gemini-embedding-2"}, "not a registered audio-capable Gemini model"),
        ({"gemini_model_default": "gemini-2.5-flash"}, "not a registered audio-capable Gemini model"),  # not verified for audio
    ):
        client, fake = client_for([], **overrides)
        result = await run(client)
        assert not client.is_configured() and fake.calls == []
        assert result.status.status == "unavailable" and message in result.status.message
        assert result.segments == [] and result.trace is None and result.status.provider is None
    result = await run(TranscribeClient(settings(google_cloud_project=None)))
    assert result.status.status == "unavailable" and "credentials are not configured" in result.status.message


async def test_unsupported_audio_fails_without_a_request():
    client, fake = client_for([reply("{}")])
    for audio, content_type, duration in ((WAV, "audio/mpeg", 9000), (b"", "audio/wav", 9000),
                                          (b"0" * (3 * 1024 * 1024 + 1), "audio/wav", 9000), (WAV, "audio/wav", 120_000)):
        result = await client.transcribe(audio, content_type, language=None, duration_ms=duration, stage="s", agent="a")
        assert result.status.status == "failed" and result.segments == []
    assert fake.calls == []


async def test_invalid_output_and_provider_errors_fail_with_a_message_never_a_raise():
    client, _ = client_for([reply("I hear music.")])
    result = await run(client)
    assert result.status.status == "failed" and "did not match" in result.status.message and result.trace.error_code == "RUN_FAILED"

    client, fake = client_for([api_error(503)] * 3)
    result = await run(client)
    assert len(fake.calls) == 3  # the first request plus llm_max_retries=2
    assert result.status.status == "failed" and "transcript is unavailable" in result.status.message
    assert result.trace.error_code == "PROVIDER_ERROR" and result.segments == []

    client, fake = client_for([blocked_prompt("PROHIBITED_CONTENT")])
    result = await run(client)
    assert len(fake.calls) == 1 and result.status.status == "failed" and result.trace.error_code == "CONTENT_BLOCKED"
    assert "safety filter" in result.status.message


async def test_budget_exhaustion_fails_the_transcript_and_sends_nothing():
    sink = InMemoryUsageSink()
    meter = Meter(sink, BudgetGuard(sink, run_budget_usd=0, daily_budget_usd=0.000001))
    client, fake = client_for([reply("{}")], meter=meter)
    result = await run(client)
    assert fake.calls == [] and result.status.status == "failed" and result.trace.error_code == "BUDGET_EXCEEDED"


async def test_every_request_is_metered_under_the_transcribe_capability_including_failed_attempts():
    sink = InMemoryUsageSink()
    client, _ = client_for([reply(json.dumps({"segments": [{"start": "0:01", "end": "0:02", "text": "hi"}]}), prompt=300, out=40)],
                           meter=Meter(sink))
    await run(client)
    (event,) = sink.events
    assert (event.capability, event.model, event.status, event.prompt_version) == ("transcribe", MODEL, "ok", "transcribe-v1")
    assert (event.stage, event.agent, event.input_tokens, event.output_tokens, event.audio_seconds) == ("transcribing", "transcribe", 300, 40, 9.0)
    assert event.estimated_cost_usd > 0

    failing = InMemoryUsageSink()
    client, _ = client_for([api_error(503), api_error(503), api_error(503)], meter=Meter(failing))
    await run(client)
    assert [(e.status, e.error_code) for e in failing.events] == [("error", "PROVIDER_ERROR")] * 3


async def test_the_gateway_offers_it_behind_a_deadline_and_the_registry_prices_it():
    sink = InMemoryUsageSink()
    gw = LLMGateway(settings(), client=FakeClient([reply(json.dumps({"segments": [{"start": "0:00", "end": "0:03", "text": "hello"}]}))]),
                    usage_sink=sink)
    wrapper = gw.capability("transcribe")
    assert wrapper is not None and wrapper.is_configured() and wrapper._provider == "google" and wrapper._model == MODEL
    result = await wrapper.transcribe(WAV, "audio/wav", language="en", duration_ms=3000, stage="transcribing", agent="transcribe")
    assert [s.text for s in result.segments] == ["hello"] and sink.events[0].capability == "transcribe"
    assert LLMGateway(settings(google_cloud_project=None)).capability("transcribe") is None
    assert LLMGateway(settings(), fixture=True).capability("transcribe") is None  # demo uploads never reach a provider
    assert LLMGateway(settings(gemini_model_default="gemini-embedding-2")).capability("transcribe") is None


async def test_an_expired_deadline_is_an_llm_error_the_workflow_handles(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(gateway_module.CAPABILITY_LIMITS, "transcribe", (0.05, 0.05))
    gw = LLMGateway(settings(), client=FakeClient([lambda call: asyncio.sleep(5)]), usage_sink=InMemoryUsageSink())
    with pytest.raises(LLMError) as caught:
        await gw.capability("transcribe").transcribe(WAV, "audio/wav", language=None, duration_ms=3000, stage="transcribing", agent="t")
    assert caught.value.code == "PROVIDER_TIMEOUT" and caught.value.trace.stage == "transcribing"


def test_clock_values_parse_to_milliseconds_and_junk_does_not():
    assert [parse_clock(v) for v in ("00:03.5", "1:05", "01:02:03", "7", "7,25", " 0:00 ")] == [3500, 65000, 3_723_000, 7000, 7250, 0]
    assert [parse_clock(v) for v in (None, "", "abc", "-3", "nan", "inf", "1:xx", "99999999")] == [None] * 8
