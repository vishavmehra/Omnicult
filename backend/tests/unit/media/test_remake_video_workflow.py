"""The Remake: Video workflow called directly, without a database: the paid call, the voice-over join, the checks and the
refusals that happen before any money is spent. The model is a fake; nothing touches the network."""

from uuid import uuid4

import pytest

from app.llm.gateway import LLMError
from app.media import ffmpeg
from app.schemas.common import StepTrace
from app.workflows import WorkflowDeps
from app.workflows.remake import LockedSpec
from app.workflows.remake_video import NEGATIVE_PROMPT, RemakeVideoInput, VideoPromptParts, run_remake_video, video_prompt
from app.workflows.types import BrandContext, WorkflowContext
from tests.api.media_support import requires_ffmpeg
from tests.api.remake_support import FakeLLM, png_bytes, wav_bytes
from tests.api.remake_video_support import FakeVideo, mp4

LOCKED = [LockedSpec(element_id="kv-logo", label="logo", kind="logo", source="lock", bbox=[0.05, 0.04, 0.25, 0.06]),
          LockedSpec(element_id="kv-pack", label="packshot", kind="packshot", source="brand_kit_never_change", bbox=[0.55, 0.5, 0.4, 0.3])]


def context(mode: str = "live") -> WorkflowContext:
    return WorkflowContext(run_id=uuid4(), project_id=uuid4(), campaign_id=uuid4(), mode=mode, brand=BrandContext(name="Aamod"))  # type: ignore[arg-type]


def video_input(mode: str = "live", **kw) -> RemakeVideoInput:
    base = dict(context=context(mode), source_version_id=uuid4(), region_code="IN-TN", region_name="Tamil Nadu", language="ta",
                language_name="Tamil", prompt="A calm festive shot.", seconds=6, start_source="remake_scene",
                original=png_bytes(finished=True), scene=png_bytes((800, 1000), (160, 40, 30)), locked=LOCKED)
    return RemakeVideoInput(**(base | kw))  # type: ignore[arg-type]


def deps(video: FakeVideo | None) -> WorkflowDeps:
    return WorkflowDeps(qloo=None, llm=FakeLLM({"video": video} if video else {}))  # type: ignore[arg-type]


# --- the prompt --------------------------------------------------------------------------------------------------


def test_the_prompt_is_built_in_code_from_the_brief_the_region_and_the_scenes_and_never_asks_for_text():
    parts = VideoPromptParts(region_name="Tamil Nadu", language_name="Tamil", product="Aamod Festive Tin. A teal tin of sweets.",
                             message="Home-style festive sweets, ready to gift.", settings=["A kitchen at dusk", "A balcony in the evening."],
                             direction="Slow push-in on the lamp.")
    prompt = video_prompt(parts)
    assert prompt == video_prompt(parts)  # deterministic: the preview shows exactly what is sent
    for expected in ("Tamil Nadu", "Aamod Festive Tin", "Home-style festive sweets", "its settings: A kitchen at dusk; A balcony in the evening)",
                     "Slow push-in on the lamp.",
                     "Keep the product tin, the logo and the tagline exactly", "No text, letters, subtitles, captions or watermarks"):
        assert expected in prompt
    assert len(prompt) < 1500 and prompt.isascii()  # Indic text is never part of a video prompt
    assert "first frame" not in video_prompt(parts.model_copy(update={"has_start_frame": False}))  # no frame, nothing to keep unchanged
    long = VideoPromptParts(region_name="Kerala", language_name="Malayalam", product="Tin. " + "A sentence about the tin that goes on. " * 12)
    assert "…" not in video_prompt(long) and "Product: Tin. A sentence about the tin that goes on." in video_prompt(long)
    assert "text" in NEGATIVE_PROMPT and "subtitles" in NEGATIVE_PROMPT


# --- the paid call and what follows -----------------------------------------------------------------------------


@requires_ffmpeg
async def test_a_live_run_makes_one_call_with_the_start_frame_and_checks_the_delivered_clip():
    video = FakeVideo()
    outcome = await run_remake_video(video_input(), deps(video))
    assert outcome.status == "completed" and outcome.error is None
    assert len(video.calls) == 1  # one clip per run, never retried by the app
    call = video.calls[0]
    assert (call["seconds"], call["aspect_ratio"], call["start_mime_type"], call["negative_prompt"]) == (6, "9:16", "image/png", NEGATIVE_PROMPT)
    assert call["prompt"] == "A calm festive shot." and call["start_image"][:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    import io

    assert Image.open(io.BytesIO(call["start_image"])).size == (720, 1280)  # the 4:5 key visual contained on a 9:16 canvas
    assert outcome.start_frame == call["start_image"] and outcome.start_source == "remake_scene" and not outcome.joined
    assert outcome.clip == outcome.silent_clip and (outcome.model, outcome.operation_id, outcome.source) == ("veo-3.1-fast-generate-001", "op-1234", "provider")
    assert [(c.name, c.passed) for c in outcome.checks] == [("readable video", True), ("length", True), ("shape", True), ("audio track", True)]
    assert (outcome.width, outcome.height, outcome.aspect_ratio) == (180, 320, "9:16") and outcome.duration_ms == pytest.approx(6000, abs=100)
    assert [s.stage for s in outcome.steps] == ["loading_context", "generating_video", "adding_voiceover", "checking_clip"]
    assert sum(s.usage.estimated_cost_usd for s in outcome.steps if s.usage) == pytest.approx(0.48)
    assert [r["element_id"] for r in outcome.locked_regions] == ["kv-logo", "kv-pack"]
    notes = " ".join(outcome.limitations)
    assert "cannot guarantee" in notes and "no on-screen text" in notes and "model interpretation" in notes


@requires_ffmpeg
async def test_the_voiceover_is_joined_when_it_fits_and_the_audio_check_follows():
    outcome = await run_remake_video(video_input(voiceover=wav_bytes(4.0)), deps(FakeVideo()))
    assert outcome.status == "completed" and outcome.joined and outcome.voiceover_ms == 4000
    assert outcome.clip != outcome.silent_clip and any("machine speech" in n for n in outcome.limitations)
    assert next(c for c in outcome.checks if c.name == "audio track").passed


@requires_ffmpeg
async def test_a_voiceover_longer_than_the_clip_is_kept_out_and_the_clip_stays_silent():
    outcome = await run_remake_video(video_input(voiceover=wav_bytes(9.0)), deps(FakeVideo()))
    assert outcome.status == "completed" and not outcome.joined and outcome.clip == outcome.silent_clip
    assert any("never cut" in n and "9.0 s" in n for n in outcome.limitations)


@requires_ffmpeg
async def test_a_run_without_a_start_frame_says_so_and_sends_the_prompt_alone():
    video = FakeVideo()
    outcome = await run_remake_video(video_input(start_source="none", original=None, scene=None, locked=[]), deps(video))
    assert video.calls[0]["start_image"] is None and outcome.start_frame is None and outcome.start_source == "none"
    notes = " ".join(outcome.limitations)
    assert "prompt alone" in notes and "cannot guarantee" not in notes and outcome.locked_regions == []


@requires_ffmpeg
async def test_a_chosen_image_is_used_as_it_is_with_no_locked_regions_claimed():
    video = FakeVideo()
    outcome = await run_remake_video(video_input(start_source="asset", original=None, scene=None, locked=[], start_image=png_bytes((600, 400))),
                                     deps(video))
    assert video.calls[0]["aspect_ratio"] == "16:9" and outcome.start_source == "asset" and outcome.locked_regions == []
    assert any("image chosen for this run" in n for n in outcome.limitations)


@requires_ffmpeg
async def test_a_clip_of_the_wrong_length_is_flagged_not_hidden():
    outcome = await run_remake_video(video_input(), deps(FakeVideo(clip=mp4(3))))
    assert outcome.status == "partial" and not next(c for c in outcome.checks if c.name == "length").passed
    assert any("1 of 4 code checks were flagged" in n for n in outcome.limitations)


@requires_ffmpeg
async def test_a_file_that_is_not_video_fails_the_run_and_nothing_is_kept():
    outcome = await run_remake_video(video_input(), deps(FakeVideo(clip=b"this is not a video" * 10)))
    assert outcome.status == "failed" and outcome.clip is None and outcome.error.code == "RUN_FAILED" and "Nothing was saved" in outcome.error.message


async def test_a_missing_ffmpeg_keeps_the_clip_and_says_it_was_not_checked(monkeypatch: pytest.MonkeyPatch):
    gone = ffmpeg.Tools(ffmpeg.Tool("ffmpeg", None, None, "ffmpeg was not found"), ffmpeg.Tool("ffprobe", None, None, "ffprobe was not found"))
    monkeypatch.setattr(ffmpeg, "detect_tools", lambda force=False: gone)
    outcome = await run_remake_video(video_input(voiceover=wav_bytes(2.0)), deps(FakeVideo(clip=b"\x00\x00\x00\x18ftypmp42" + bytes(64))))
    assert outcome.status == "completed" and outcome.checks == [] and not outcome.joined
    notes = " ".join(outcome.limitations)
    assert "voice-over was not joined" in notes and "was not checked" in notes


# --- failures -----------------------------------------------------------------------------------------------------


async def test_a_provider_failure_fails_the_run_with_its_trace_and_creates_nothing():
    trace = StepTrace(stage="generating_video", agent="remake_video", status="failed", provider="google", error_code="PROVIDER_TIMEOUT")
    error = LLMError("PROVIDER_TIMEOUT", "The provider did not respond. The request was accepted, so Google may still bill it.",
                     retryable=False, trace=trace)
    video = FakeVideo(error=error)
    outcome = await run_remake_video(video_input(), deps(video))
    assert outcome.status == "failed" and outcome.clip is None and len(video.calls) == 1
    assert outcome.error.code == "PROVIDER_TIMEOUT" and outcome.error.stage == "generating_video" and not outcome.error.retryable
    assert "No version was created." in outcome.error.message and "may still bill" in outcome.error.message
    assert outcome.steps[-1] is trace


async def test_a_run_with_no_video_model_is_refused_before_any_call():
    outcome = await run_remake_video(video_input(), deps(None))
    assert outcome.status == "failed" and outcome.error.code == "PROVIDER_NOT_CONFIGURED" and "Nothing was generated" in outcome.error.message


async def test_an_unreadable_start_image_and_a_bad_length_are_refused_before_any_call():
    video = FakeVideo()
    outcome = await run_remake_video(video_input(original=b"junk"), deps(video))
    assert outcome.status == "failed" and outcome.error.code == "VALIDATION_ERROR" and not video.calls
    outcome = await run_remake_video(video_input(seconds=7), deps(video))
    assert outcome.status == "failed" and outcome.error.code == "VALIDATION_ERROR" and not video.calls
