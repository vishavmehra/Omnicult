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
