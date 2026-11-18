"""The `transcribe` capability on a fake Gen AI client: gates, parsing of the model's plain-text timed lines, failure statuses,
metering and the gateway wrapper. No network, no audio file."""

import asyncio

import pytest

from app.llm import gateway as gateway_module
from app.llm.budget import BudgetGuard, InMemoryUsageSink, Meter
from app.llm.gateway import LLMError, LLMGateway
from app.llm.transcribe import (
    MAX_OUTPUT_TOKENS, MIN_OUTPUT_TOKENS, TranscribeClient, output_budget, output_shape, parse_clock, parse_transcript,
)
from tests.unit.llm.genai_fakes import FakeClient, api_error, blocked_prompt, reply, settings

MODEL = "gemini-3.8-flash"
WAV = b"RIFF" + b"0" * 64
MARATHI = "दिवाळी आली की घरभर फराळाचा सुगंध दरवळतो."
LIMIT = MIN_OUTPUT_TOKENS + 2048  # a 9 s clip: its sized budget plus gemini-3.8-flash's thinking headroom


def client_for(script, *, meter=None, **overrides) -> tuple[TranscribeClient, FakeClient]:
    fake = FakeClient(script)
    return TranscribeClient(settings(**overrides), client=fake, meter=meter, backoff_seconds=0), fake


async def run(client: TranscribeClient, **kwargs):
    return await client.transcribe(WAV, "audio/wav", language=kwargs.pop("language", "mr"),
                                   duration_ms=kwargs.pop("duration_ms", 9000), stage="transcribing", agent="transcribe")


async def test_speech_becomes_timed_segments_in_the_spoken_script():
    answer = "\n".join([
        "00:05.0 [EN]   Free   delivery before Bhau Beej ",
        f"00:00.5 [mr] {MARATHI}",
        "00:06.5 [Marathi] Order today",  # a language name instead of a code falls back to the hint
        "00:07.0 - 00:02.0 [mr] End before start",  # an end before the start is dropped
        "00:09.5 - 01:30.0 Past the clip",  # start and end are clamped to the clip
        "soon, no usable time",  # a line outside the format is ignored when other lines fit it
        "00:01.0 [mr]    ",  # no words: not a line
        "MUSIC:   warm,   festive  ",
    ])
    client, fake = client_for([reply(answer, prompt=900, out=120)])
    result = await run(client)

    assert (result.status.status, result.status.provider, result.status.model_id, result.status.message) == ("transcribed", "google", MODEL, None)
    assert [(s.id, s.start_ms, s.end_ms, s.language, s.text) for s in result.segments] == [
        ("x1", 500, 5000, "mr", MARATHI),  # no end given: the next line's start
        ("x2", 5000, 6500, "en", "Free delivery before Bhau Beej"),
        ("x3", 6500, 7000, "mr", "Order today"),
        ("x4", 7000, 9000, "mr", "End before start"),  # an end before the start is replaced by the estimate (the next line starts at 9000)
        ("x5", 9000, 9000, "mr", "Past the clip"),  # start and end clamped to the clip
    ]
    assert all(s.source == "transcription" for s in result.segments) and result.music_mood == "warm, festive"
    sent = fake.calls[0]
    assert sent.model == MODEL and sent.config.temperature == 1.0
    assert sent.config.response_mime_type is None and sent.config.response_json_schema is None  # plain text, no structured output
    assert sent.config.max_output_tokens == LIMIT
    text_part, audio_part = sent.contents[0].parts
    assert audio_part.inline_data.mime_type == "audio/wav" and audio_part.inline_data.data == WAV
    assert "ISO 639-1 code mr" in text_part.text
    assert result.trace.status == "completed" and result.trace.prompt_version == "transcribe-v2"
    assert result.trace.schema_version == "transcript-lines-v1" and result.trace.usage.input_tokens == 900
    assert result.trace.usage.estimated_cost_usd > 0


def test_the_line_parser_accepts_the_forms_a_model_writes_for_the_same_format():
    answer = "\n".join([
        "```text",
        "[00:01.5] [hi] bracketed time",
        "(0:03.25 to 0:04.5) range with words",
        "00:05,5: comma and colon",
        "1:02:03.0 | [ta] hours form",
        "```",
        "NO SPEECH",
    ])
    segments, mood = parse_transcript(answer, language=None, duration_ms=None)
    assert [(s.start_ms, s.end_ms, s.language, s.text) for s in segments] == [
        (1500, 3250, "hi", "bracketed time"), (3250, 4500, None, "range with words"), (5500, 3_723_000, None, "comma and colon"),
        (3_723_000, None, "ta", "hours form"),  # the last line has no end when the clip length is unknown
    ]
    assert mood is None


def test_a_line_without_an_end_gets_the_next_start_and_the_last_line_the_clip_end():
    answer = "00:01.0 a\n00:04.0 b\n00:08.0 c"

    def ends(duration: int | None) -> list[int | None]:
        return [s.end_ms for s in parse_transcript(answer, language=None, duration_ms=duration)[0]]

    assert ends(12_000) == [4000, 8000, 12_000] and ends(None) == [4000, 8000, None]
    assert ends(5000) == [4000, 5000, 5000]  # a line the model placed past the clip is clamped to its end
    given = parse_transcript("00:01.0 - 00:02.5 a\n00:04.0 b", language=None, duration_ms=9000)[0]
    assert [s.end_ms for s in given] == [2500, 9000]  # an end the model gave is kept


def test_no_speech_music_only_and_prose_are_told_apart():
    assert parse_transcript("NO SPEECH", language=None, duration_ms=None) == ([], None)
    assert parse_transcript("no speech.\nMUSIC: calm, instrumental", language=None, duration_ms=None) == ([], "calm, instrumental")
    for none in ("MUSIC: none", "music: No music.", "MUSIC:"):
        assert parse_transcript(f"00:01.0 hello\n{none}", language=None, duration_ms=None)[1] is None
    for prose in ("I hear music.", "", "   \n "):  # nothing in the format and not a declared absence: a format failure
        with pytest.raises(ValueError):
            parse_transcript(prose, language=None, duration_ms=None)


def test_the_output_budget_is_sized_to_the_clip_and_bounded():
    assert output_budget(29_400) == 882 and output_budget(60_000) == MAX_OUTPUT_TOKENS - 1200
    assert output_budget(2_000) == MIN_OUTPUT_TOKENS and output_budget(0) == output_budget(None) == MAX_OUTPUT_TOKENS
    assert output_budget(600_000) == MAX_OUTPUT_TOKENS


async def test_the_request_budget_follows_the_clip_length():
    client, fake = client_for([reply("00:01.0 hi"), reply("00:01.0 hi")])
    await client.transcribe(WAV, "audio/wav", language=None, duration_ms=29_400, stage="s", agent="a")
    await client.transcribe(WAV, "audio/wav", language=None, duration_ms=None, stage="s", agent="a")
    assert [c.config.max_output_tokens for c in fake.calls] == [882 + 2048, MAX_OUTPUT_TOKENS + 2048]


async def test_a_decoding_loop_is_cut_short_and_a_cut_off_answer_is_reported_as_such():
    loop = [f"00:{i:02d}.0 [mr] आमोद." for i in range(20, 26)]
    client, _ = client_for([reply("\n".join(["00:01.0 [en] Every bond, a little sweeter.", *loop]))])
    result = await run(client)
    assert [s.text for s in result.segments] == ["Every bond, a little sweeter.", "आमोद.", "आमोद."]  # two repeats are speech, the rest a loop
    again = "\n".join(f"00:0{i}.0 {text}" for i, text in enumerate(["a", "b", "a", "b", "a"]))
    client, _ = client_for([reply(again)])
    assert [s.text for s in (await run(client)).segments] == ["a", "b", "a", "b", "a"]  # alternating text is not a run

    runaway = "00:01.0 [mr] " + "आमोद " * 400  # one endless line, stopped by the limit
    client, _ = client_for([reply(runaway, prompt=1255, out=LIMIT)])
    result = await run(client)
    assert result.status.status == "failed" and "cut off at its length limit" in result.status.message
    assert result.trace.error_code == "RUN_FAILED" and result.trace.usage.output_tokens == LIMIT


async def test_a_clip_without_speech_is_transcribed_with_no_segments_and_keeps_the_music_mood():
    client, _ = client_for([reply("NO SPEECH\nMUSIC: calm, instrumental")])
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
    client, fake = client_for([reply("00:01.0 hi")])
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
    client, fake = client_for([reply("00:01.0 hi")], meter=meter)
    result = await run(client)
    assert fake.calls == [] and result.status.status == "failed" and result.trace.error_code == "BUDGET_EXCEEDED"


async def test_every_request_is_metered_under_the_transcribe_capability_including_failed_attempts():
    sink = InMemoryUsageSink()
    client, _ = client_for([reply("00:01.0 [en] hi", prompt=300, out=40)], meter=Meter(sink))
    await run(client)
    (event,) = sink.events
    assert (event.capability, event.model, event.status, event.prompt_version) == ("transcribe", MODEL, "ok", "transcribe-v2")
    assert (event.stage, event.agent, event.input_tokens, event.output_tokens, event.audio_seconds) == ("transcribing", "transcribe", 300, 40, 9.0)
    assert event.estimated_cost_usd > 0

    failing = InMemoryUsageSink()
    client, _ = client_for([api_error(503), api_error(503), api_error(503)], meter=Meter(failing))
    await run(client)
    assert [(e.status, e.error_code) for e in failing.events] == [("error", "PROVIDER_ERROR")] * 3


async def test_the_gateway_offers_it_behind_a_deadline_and_the_registry_prices_it():
    sink = InMemoryUsageSink()
    gw = LLMGateway(settings(), client=FakeClient([reply("00:00.0 [en] hello")]), usage_sink=sink)
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


async def test_an_answer_cut_off_mid_line_keeps_the_complete_lines_before_the_cut():
    done = ["00:01.0 [en] Every bond, a little sweeter.", "00:03.0 [mr] आमोद."]
    loop = ["00:06.0 [mr] आमोद."] * 30
    cut = "\n".join([*done, *loop, "00:08.0 [mr] आम"])  # the last line is the one the limit stopped
    client, _ = client_for([reply(cut, prompt=1255, out=LIMIT)])
    result = await run(client)
    assert result.status.status == "transcribed" and "cut off at its length limit" in result.status.message
    assert [s.text for s in result.segments] == ["Every bond, a little sweeter.", "आमोद.", "आमोद."]  # the loop is collapsed to two
    assert result.trace.status == "completed" and result.trace.usage.output_tokens == LIMIT


async def test_a_rejected_answer_is_logged_by_shape_never_by_content(caplog):
    cut = "00:01.0 [mr] first words\n00:02.0 [mr] secret words\n00:03.0 [mr] sec"
    assert output_shape(cut) == {"output_chars": len(cut), "lines": 3, "timed_lines": 3, "distinct_texts": 3}
    assert output_shape("I hear music.") == {"output_chars": 13, "lines": 1, "timed_lines": 0, "distinct_texts": 0}
    client, _ = client_for([reply("Here is the transcript:\nsecret words", prompt=1255, out=LIMIT)])
    with caplog.at_level("WARNING", logger="app.llm.transcribe"):
        result = await run(client)
    assert result.status.status == "failed"  # a cut-off answer with no line in the format keeps nothing
    record = next(r for r in caplog.records if r.getMessage() == "transcription output rejected")
    assert record.cut_off is True and record.lines == 2 and record.timed_lines == 0 and "secret words" not in repr(vars(record))
