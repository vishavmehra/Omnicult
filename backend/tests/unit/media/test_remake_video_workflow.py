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
    return WorkflowDeps(llm=FakeLLM({"video": video} if video else {}))  # type: ignore[arg-type]


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
    assert "cannot guarantee" in notes and "never asked to draw text" in notes and "model interpretation" in notes


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


# --- brand elements: the model never draws them -------------------------------------------------------------------------

import io  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from PIL import Image  # noqa: E402

from app.media import remake_video as pipeline  # noqa: E402
from app.media.remake_video import BrandSpec  # noqa: E402
from tests.api.remake_video_support import big_mp4, logo_png  # noqa: E402

TAGLINE = "Every bond, a little sweeter."
TAGLINE_BOX = [0.1, 0.82, 0.8, 0.1]
LOCKED_ALL = [*LOCKED, LockedSpec(element_id="kv-tagline", label="tagline", kind="tagline", source="brand_kit_never_change", bbox=TAGLINE_BOX)]


def brand() -> list[BrandSpec]:
    return [BrandSpec(element_id="kv-logo", role="logo", label="logo", bbox=LOCKED[0].bbox, image=logo_png()),
            BrandSpec(element_id="kv-tagline", role="tagline", label="tagline", bbox=TAGLINE_BOX, text=TAGLINE, language="en", script="Latn")]


def branded_input(**kw) -> RemakeVideoInput:
    return video_input(**({"brand": brand(), "locked": LOCKED_ALL} | kw))


async def frame_at(clip: bytes, at_ms: int = 0) -> Image.Image:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / "c.mp4").write_bytes(clip)
        (folder / "f").mkdir()
        files = await ffmpeg.extract_frames(folder / "c.mp4", folder / "f", every_ms=500, limit=at_ms // 500 + 1)
        with Image.open(files[-1][1]) as image:
            return image.convert("RGB")


def test_a_prompt_with_brand_elements_drawn_in_code_keeps_a_band_clear_and_never_asks_for_brand_marks():
    parts = VideoPromptParts(region_name="Tamil Nadu", language_name="Tamil", product="Aamod Festive Tin. A teal tin.", pinned=["logo", "tagline", "tin"],
                             clear_bands=["upper", "lower"])
    prompt = video_prompt(parts)
    assert prompt == video_prompt(parts) and prompt.isascii()
    assert "Keep the upper and lower bands of the frame clear and calm for brand graphics" in prompt
    assert "never draw or change any logo, label or lettering" in prompt and "camera is locked off" in prompt
    assert "exactly as they appear" not in prompt and "push-in" not in prompt  # the model is not asked to keep (draw) the marks, nor to move the scene under them
    assert "lower band " in video_prompt(parts.model_copy(update={"clear_bands": ["lower"]})) and "bands" not in video_prompt(parts.model_copy(update={"clear_bands": ["lower"]}))
    assert "Keep the" not in video_prompt(parts.model_copy(update={"clear_bands": []})).split("Brand graphics")[0].split("locked off")[-1]  # only a tin: no band to keep clear


@requires_ffmpeg
async def test_the_brand_layer_is_drawn_over_the_clip_the_model_delivers_and_every_element_holds():
    video = FakeVideo(clip=big_mp4())
    outcome = await run_remake_video(branded_input(), deps(video))
    assert outcome.status == "completed" and outcome.error is None and len(video.calls) == 1
    assert outcome.silent_clip == big_mp4() and outcome.clip != outcome.silent_clip  # the model's file is kept as delivered; the final one carries the overlay
    brand_checks = {c.element_id: c for c in outcome.checks if c.element_id}
    assert set(brand_checks) == {"kv-logo", "kv-tagline"} and [c.name for c in brand_checks.values()] == ["Logo", "Tagline"]
    assert all(c.passed and c.frames_checked == 12 and c.failed_at_ms == [] and c.detail == "held for all 12 frames" for c in brand_checks.values())
    logo = pipeline.in_frame(LOCKED[0].bbox, (400, 500), "9:16")
    x0, y0, x1, y1 = (round(v) for v in (logo[0] * 720, logo[1] * 1280, (logo[0] + logo[2]) * 720, (logo[1] + logo[3]) * 1280))
    disc = ((x0 + 28), (y0 + 27))  # the middle of the logo disc in the box
    final, silent = await frame_at(outcome.clip, 3000), await frame_at(outcome.silent_clip, 3000)
    assert min(final.getpixel(disc)) > 235 and max(silent.getpixel(disc)) < 160  # drawn in code in the final clip, absent from the model's
    assert [r["element_id"] for r in outcome.locked_regions] == ["kv-pack"]  # the drawn elements are not "kept as pixels"
    notes = " ".join(outcome.limitations)
    assert "drawn in code over every frame" in notes and "Locked regions that are not drawn in code (packshot)" in notes


def pixel_in(frame: Image.Image, box: list[float], fx: float = 0.5, fy: float = 0.5) -> tuple[int, ...]:
    """The pixel at (fx, fy) inside a key-visual box, as it sits in the 720x1280 frame."""
    b = pipeline.in_frame(box, (400, 500), "9:16")
    return frame.getpixel((round((b[0] + b[2] * fx) * 720), round((b[1] + b[3] * fy) * 1280)))


@requires_ffmpeg
async def test_the_start_frame_is_the_plate_with_the_brand_regions_wiped_not_the_finished_creative():
    video = FakeVideo(clip=big_mp4())
    outcome = await run_remake_video(branded_input(), deps(video))
    frame = Image.open(io.BytesIO(video.calls[0]["start_image"])).convert("RGB")
    assert frame.size == (720, 1280) and outcome.start_frame == video.calls[0]["start_image"]
    plate, creative = (160, 40, 30), (30, 60, 90)
    middle = pixel_in(frame, [0.0, 0.4, 0.05, 0.1])  # away from every element and from the scrim bands
    assert all(abs(a - b) < 6 for a, b in zip(middle, plate, strict=True)) and not all(abs(a - b) < 40 for a, b in zip(middle, creative, strict=True))
    for box in (LOCKED[0].bbox, TAGLINE_BOX):  # the logo and the tagline: wiped, so the plate shows (as it does just beside the box)
        beside = pixel_in(frame, [0.0, box[1], 0.03, box[3]])
        assert max(pixel_in(frame, box)) < 200 and all(abs(a - b) < 25 for a, b in zip(pixel_in(frame, box), beside, strict=True))
    assert all(abs(a - b) < 12 for a, b in zip(pixel_in(frame, LOCKED[1].bbox), (200, 160, 40), strict=True))  # the pack has no Brand Kit file: pasted as before


@requires_ffmpeg
async def test_no_brand_text_is_sent_to_the_model():
    video = FakeVideo(clip=big_mp4())
    parts = VideoPromptParts(region_name="Tamil Nadu", language_name="Tamil", product="Aamod Festive Tin. A teal tin.", pinned=["logo", "tagline"],
                             clear_bands=["upper", "lower"])
    await run_remake_video(branded_input(prompt=video_prompt(parts), brand=[*brand(), BrandSpec(element_id="kv-h", role="headline", label="headline",
                           bbox=[0.1, 0.2, 0.7, 0.1], text="Diwali is sweets", language="en", script="Latn")]), deps(video))
    call = video.calls[0]
    sent = " ".join([call["prompt"], call["negative_prompt"]])
    assert TAGLINE not in sent and "Diwali is sweets" not in sent and "every bond" not in sent.lower()
    assert "tagline" not in call["prompt"].lower() and "Keep the product tin, the logo and the tagline exactly" not in call["prompt"]
    assert call["start_image"][:8] == b"\x89PNG\r\n\x1a\n"  # an image only: the plate with calm patches where the elements go


@requires_ffmpeg
async def test_an_element_that_does_not_match_its_drawing_marks_the_run_partial_in_plain_words(monkeypatch: pytest.MonkeyPatch):
    async def no_overlay(video: bytes, overlay: object) -> bytes:  # an overlay bug: the clip comes back without the elements
        return video

    monkeypatch.setattr(pipeline, "apply_overlay", no_overlay)
    outcome = await run_remake_video(branded_input(), deps(FakeVideo(clip=big_mp4())))
    assert outcome.status == "partial" and outcome.clip is not None  # the clip is kept, flagged
    flagged = {c.name: c for c in outcome.checks if c.element_id and not c.passed}
    assert set(flagged) == {"Logo", "Tagline"} and flagged["Logo"].failed_at_ms == [i * 500 for i in range(12)]
    assert flagged["Logo"].detail == "drifted at 0.0 s, 0.5 s, 1.0 s, 1.5 s and 8 more (12 of 12 frames)"
    notes = " ".join(outcome.limitations)
    assert "Logo drifted at 0.0 s" in notes and "Tagline drifted at 0.0 s" in notes and "code checks were flagged" in notes


@requires_ffmpeg
async def test_the_voiceover_joins_the_branded_clip_and_the_elements_still_hold():
    outcome = await run_remake_video(branded_input(voiceover=wav_bytes(4.0)), deps(FakeVideo(clip=big_mp4())))
    assert outcome.status == "completed" and outcome.joined and outcome.clip != outcome.silent_clip
    assert all(c.passed for c in outcome.checks if c.element_id) and next(c for c in outcome.checks if c.name == "audio track").passed


async def test_a_missing_ffmpeg_keeps_the_clip_flags_the_elements_as_not_drawn_and_never_claims_a_check(monkeypatch: pytest.MonkeyPatch):
    gone = ffmpeg.Tools(ffmpeg.Tool("ffmpeg", None, None, "ffmpeg was not found"), ffmpeg.Tool("ffprobe", None, None, "ffprobe was not found"))
    monkeypatch.setattr(ffmpeg, "detect_tools", lambda force=False: gone)
    outcome = await run_remake_video(branded_input(), deps(FakeVideo(clip=b"\x00\x00\x00\x18ftypmp42" + bytes(64))))
    assert outcome.status == "completed" and outcome.checks == []  # nothing could be checked, and nothing is claimed
    assert any("was not checked" in n for n in outcome.limitations) and any("could not be drawn over the clip" in n for n in outcome.limitations)


@requires_ffmpeg
async def test_a_tin_drawn_in_code_stays_in_the_start_frame_and_the_overlay_covers_it_for_every_frame():
    pack = BrandSpec(element_id="kv-pack", role="tin", label="tin", bbox=LOCKED[1].bbox, image=logo_png())
    video = FakeVideo(clip=big_mp4())
    outcome = await run_remake_video(branded_input(brand=[*brand(), pack]), deps(video))
    frame = Image.open(io.BytesIO(video.calls[0]["start_image"])).convert("RGB")
    assert all(abs(a - b) < 12 for a, b in zip(pixel_in(frame, LOCKED[1].bbox), (200, 160, 40), strict=True))  # not wiped: the frame keeps the pack
    held = {c.name: c for c in outcome.checks if c.element_id}
    assert set(held) == {"Logo", "Tagline", "Product tin"} and all(c.passed and c.frames_checked == 12 for c in held.values())
    assert [r["element_id"] for r in outcome.locked_regions] == ["kv-pack"]  # still carried into the frame as pixels; the checks say it is also drawn
