"""The pure steps of Remake: Video: the start frame, the voice-over join and the clip inspection. ffmpeg tests skip without it."""

import io
import wave
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from app.media import ffmpeg
from app.media import remake_video as pipeline
from tests.api.media_support import requires_ffmpeg
from tests.api.remake_support import png_bytes, wav_bytes


def striped(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGB", size, (30, 60, 90))
    for x in range(0, size[0], 10):
        image.paste((200, 160, 40), (x, 0, x + 4, size[1]))
    return image


def test_a_portrait_key_visual_is_contained_on_a_9_16_canvas_without_being_cropped_or_stretched():
    layout = striped((400, 500))  # 4:5
    png, aspect, size = pipeline.start_frame(layout)
    frame = Image.open(io.BytesIO(png)).convert("RGB")
    assert (aspect, size, frame.size) == ("9:16", (720, 1280), (720, 1280))
    fitted = layout.resize((720, 900), Image.Resampling.LANCZOS)
    top = (1280 - 900) // 2
    assert ImageChops.difference(frame.crop((0, top, 720, top + 900)), fitted).getbbox() is None  # the picture, whole and centred
    bar = frame.crop((0, 0, 720, top))
    assert bar.getbbox() and ImageChops.difference(bar, Image.new("RGB", bar.size, (0, 0, 0))).getbbox()  # a blurred extension, not black bars


def test_a_landscape_picture_goes_to_16_9_and_the_aspect_follows_the_shape():
    assert pipeline.aspect_for((400, 500)) == "9:16" and pipeline.aspect_for((500, 500)) == "9:16" and pipeline.aspect_for((800, 450)) == "16:9"
    png, aspect, size = pipeline.start_frame(striped((800, 450)))
    assert (aspect, size, Image.open(io.BytesIO(png)).size) == ("16:9", (1280, 720), (1280, 720))


def test_locked_regions_are_copied_back_from_the_original_into_the_layout():
    original = striped((400, 500))
    scene = Image.new("RGB", (200, 250), (160, 40, 30))  # the generated scene is another size: it is fitted, not stretched
    layout = pipeline.build_layout(original, scene, [[0.55, 0.5, 0.4, 0.3]])
    assert layout.size == original.size
    box = (int(0.55 * 400), int(0.5 * 500), int(0.95 * 400), int(0.8 * 500))
    assert ImageChops.difference(layout.crop(box), original.crop(box)).getbbox() is None
    assert layout.getpixel((5, 5)) == (160, 40, 30)  # outside the region it is the new scene
    assert pipeline.build_layout(original, None, []).tobytes() == original.tobytes()  # no scene and no locks: the original itself


def test_the_preview_thumbnail_is_a_small_jpeg_of_the_frame():
    png, _, _ = pipeline.start_frame(striped((400, 500)))
    thumb = pipeline.thumbnail_jpeg(png, 320)
    image = Image.open(io.BytesIO(thumb))
    assert image.format == "JPEG" and max(image.size) == 320 and image.size == (180, 320)


def test_a_voiceover_that_is_longer_than_the_clip_is_never_joined():
    assert pipeline.voiceover_fits(5900, 6000) and pipeline.voiceover_fits(6200, 6000)  # within the tolerance
    assert not pipeline.voiceover_fits(6300, 6000) and not pipeline.voiceover_fits(19000, 6000)


@requires_ffmpeg
async def test_the_voiceover_is_joined_with_the_video_copied_and_the_clip_inspected(tmp_path: Path):
    from tests.api.media_support import make_video

    source = make_video(tmp_path / "clip.mp4", scenes=1, seconds_each=3, audio=False)
    video = source.read_bytes()
    before = await pipeline.inspect_clip(video)
    assert (before.has_video, before.has_audio, before.video_codec, before.width) == (True, False, "h264", 320)
    joined = await pipeline.join_voiceover(video, wav_bytes(2.0), before.duration_ms or 3000)
    after = await pipeline.inspect_clip(joined)
    assert (after.has_video, after.has_audio, after.video_codec) == (True, True, "h264")  # the video stream is copied, not re-encoded
    assert after.duration_ms == pytest.approx(before.duration_ms, abs=100) and after.container == "mov"  # mp4 family


@requires_ffmpeg
async def test_a_file_that_is_not_video_is_unreadable_and_a_missing_tool_is_reported(monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(ffmpeg.MediaUnreadable):
        await pipeline.inspect_clip(b"not a video at all" * 20)
    monkeypatch.setattr(ffmpeg, "detect_tools", lambda force=False: ffmpeg.Tools(
        ffmpeg.Tool("ffmpeg", None, None, "ffmpeg was not found"), ffmpeg.Tool("ffprobe", None, None, "ffprobe was not found")))
    with pytest.raises(ffmpeg.MediaToolMissing):
        await pipeline.inspect_clip(png_bytes())


def test_wav_helper_makes_a_real_track():
    with wave.open(io.BytesIO(wav_bytes(1.0))) as clip:
        assert clip.getnframes() == 24000


# --- brand elements: wiped from the frame, drawn in code, measured in the clip ---------------------------------------------

import subprocess  # noqa: E402
import tempfile  # noqa: E402

from tests.api.remake_video_support import big_mp4, logo_png  # noqa: E402

LOGO_BOX = [0.1, 0.05, 0.4, 0.1]  # key-visual coordinates
TAGLINE_BOX = [0.1, 0.8, 0.8, 0.1]


def specs() -> list[pipeline.BrandSpec]:
    return [pipeline.BrandSpec(element_id="kv-logo", role="logo", label="logo", bbox=LOGO_BOX, image=logo_png()),
            pipeline.BrandSpec(element_id="kv-tagline", role="tagline", label="tagline", bbox=TAGLINE_BOX, text="Every bond, a little sweeter.",
                               language="en", script="Latn")]


def overlay_for(size: tuple[int, int] = (180, 320), brand: list[pipeline.BrandSpec] | None = None) -> pipeline.Overlay:
    frame = Image.new("RGB", size, (0, 128, 128))
    return pipeline.build_overlay(size, (400, 500), "9:16", frame, brand or specs(), None, "Latn")


def test_a_wiped_region_is_filled_from_its_surroundings_and_nothing_else_changes():
    image = Image.new("RGB", (400, 500), (30, 60, 90))
    for x in range(40, 140, 6):  # a busy mark where the logo was
        image.paste((250, 250, 250), (x, 30, x + 3, 60))
    wiped = pipeline.wipe_region(image, [0.1, 0.06, 0.25, 0.06])
    assert max(wiped.crop((40, 30, 140, 60)).getextrema()[0][1], 0) < 60  # smooth: no white strokes survive in the box
    assert ImageChops.difference(wiped.crop((0, 200, 400, 500)), image.crop((0, 200, 400, 500))).getbbox() is None  # far away: untouched


def test_the_layout_wipes_brand_boxes_from_the_plate_and_still_pastes_the_other_locked_regions():
    original = striped((400, 500))
    scene = Image.new("RGB", (400, 500), (160, 40, 30))
    other = [0.55, 0.5, 0.4, 0.3]
    layout = pipeline.build_layout(original, scene, [other], [LOGO_BOX])
    box = (int(0.55 * 400), int(0.5 * 500), int(0.95 * 400), int(0.8 * 500))
    assert ImageChops.difference(layout.crop(box), original.crop(box)).getbbox() is None  # a locked region that is not drawn in code
    inside, beside = layout.getpixel((int(0.3 * 400), int(0.1 * 500))), layout.getpixel((5, int(0.1 * 500)))
    assert all(abs(a - b) < 25 for a, b in zip(inside, beside, strict=True))  # inside the logo box: the plate (as beside it), not the original's stripes


def test_a_key_visual_box_keeps_its_position_and_scale_in_the_frame():
    assert pipeline.placement((400, 500), "9:16") == (0, 190, 720, 900, 720, 1280)
    assert pipeline.in_frame([0.0, 0.0, 1.0, 1.0], (400, 500), "9:16") == [0.0, round(190 / 1280, 5), 1.0, round(900 / 1280, 5)]
    assert pipeline.in_frame([0.5, 0.5, 0.25, 0.1], (400, 500), "9:16") == [0.5, round((190 + 450) / 1280, 5), 0.25, round(90 / 1280, 5)]


def test_the_overlay_holds_the_logo_and_the_tagline_on_a_transparent_layer_at_the_clip_resolution():
    overlay = overlay_for()
    layer = Image.open(io.BytesIO(overlay.png))
    assert layer.mode == "RGBA" and layer.size == (180, 320) and [p.role for p in overlay.placed] == ["logo", "tagline"]
    assert layer.getpixel((2, 2))[3] == 0  # nothing outside the elements
    logo, tagline = (p.rect for p in overlay.placed)
    assert layer.crop(logo).getchannel("A").getextrema()[1] == 255 and layer.crop(tagline).getchannel("A").getextrema()[1] == 255
    assert logo[1] < tagline[1]  # the logo is above the tagline, as in the key visual


def test_a_logo_without_a_brand_kit_file_falls_back_to_the_source_patch_and_says_so():
    original = striped((400, 500))
    brand = [pipeline.BrandSpec(element_id="kv-logo", role="logo", label="logo", bbox=LOGO_BOX)]
    overlay = pipeline.build_overlay((180, 320), (400, 500), "9:16", Image.new("RGB", (180, 320)), brand, original, "Latn")
    assert len(overlay.placed) == 1 and any("No Brand Kit file is linked" in n and "patch" in n for n in overlay.notes)
    assert Image.open(io.BytesIO(overlay.png)).crop(overlay.placed[0].rect).getchannel("A").getextrema() == (255, 255)
    assert pipeline.build_overlay((180, 320), (400, 500), "9:16", Image.new("RGB", (180, 320)), brand, None, "Latn").placed == []


def test_text_in_another_script_is_left_out_not_drawn():
    headline = pipeline.BrandSpec(element_id="kv-h", role="headline", label="headline", bbox=[0.1, 0.2, 0.7, 0.1], text="தீபாவளி", language="ta", script="Taml")
    overlay = pipeline.build_overlay((180, 320), (400, 500), "9:16", Image.new("RGB", (180, 320)), [headline], None, "Deva")
    assert overlay.placed == [] and any("headline was left out" in n for n in overlay.notes)  # Tamil text in a Devanagari region: transcreate first


def test_the_drift_measure_is_zero_for_the_drawing_and_large_for_anything_else():
    overlay = overlay_for()
    layer = Image.open(io.BytesIO(overlay.png)).convert("RGBA")
    rect = overlay.placed[0].rect
    same = Image.new("RGB", layer.size, (0, 128, 128))
    same.paste(layer, (0, 0), layer)
    assert pipeline.drift(same, layer, rect) == pytest.approx(0, abs=2)
    assert pipeline.drift(Image.new("RGB", layer.size, (0, 128, 128)), layer, rect) > pipeline.DRIFT_LIMIT  # the drawing is missing
    assert pipeline.drift(same, Image.new("RGBA", layer.size, (0, 0, 0, 0)), rect) is None  # nothing drawn: nothing to compare


@requires_ffmpeg
async def test_the_overlay_is_applied_to_every_frame_and_a_check_of_the_final_clip_passes():
    overlay = overlay_for((720, 1280))
    final = await pipeline.apply_overlay(big_mp4(6), overlay)
    facts = await pipeline.inspect_clip(final)
    assert (facts.width, facts.height, facts.video_codec, facts.has_audio) == (720, 1280, "h264", False)
    assert facts.duration_ms == pytest.approx(6000, abs=100)
    results = await pipeline.check_brand(final, overlay)
    assert [(r.role, r.sampled, r.failed_ms, r.checkable) for r in results] == [("logo", 12, [], True), ("tagline", 12, [], True)]  # every 0.5 s
    assert max(r.worst for r in results) < pipeline.DRIFT_LIMIT / 3  # codec noise only


@requires_ffmpeg
async def test_the_overlay_leaves_an_audio_track_untouched(tmp_path: Path):
    from tests.api.media_support import make_video

    with_audio = make_video(tmp_path / "clip.mp4", scenes=1, seconds_each=2, audio=True)
    final = await pipeline.apply_overlay(with_audio.read_bytes(), overlay_for((320, 240)))
    facts = await pipeline.inspect_clip(final)
    assert facts.has_audio and facts.has_video and facts.duration_ms == pytest.approx(2000, abs=150)


@requires_ffmpeg
async def test_a_clip_without_the_drawing_fails_every_sampled_frame_with_its_timestamp():
    results = await pipeline.check_brand(big_mp4(6), overlay_for((720, 1280)))  # the model clip as delivered: no brand elements in it
    assert all(r.failed_ms == [i * 500 for i in range(12)] for r in results)


@requires_ffmpeg
async def test_an_element_that_vanishes_after_three_seconds_is_flagged_from_then_on():
    overlay = overlay_for((720, 1280))
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / "clip.mp4").write_bytes(big_mp4(6))
        (folder / "layer.png").write_bytes(overlay.png)
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(folder / "clip.mp4"), "-i", str(folder / "layer.png"),
                        "-filter_complex", "[0:v][1:v]overlay=0:0:enable='lt(t,3)',format=yuv420p[v]", "-map", "[v]", "-c:v", "libx264",
                        "-crf", "17", str(folder / "drift.mp4")], check=True, capture_output=True, timeout=120)
        drifted = (folder / "drift.mp4").read_bytes()
    results = await pipeline.check_brand(drifted, overlay)
    assert all(r.failed_ms == [3000, 3500, 4000, 4500, 5000, 5500] and r.sampled == 12 for r in results)
