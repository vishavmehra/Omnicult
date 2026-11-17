"""ffmpeg and ffprobe handling: parsing, a missing binary, failures and timeouts (no ffmpeg needed), and the real binaries
when they are installed (those tests skip otherwise)."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.core.config import get_settings
from app.core.errors import ProviderNotConfigured, ValidationFailed
from app.media import ffmpeg
from tests.api.media_support import HAS_FFMPEG, make_audio, make_video, requires_ffmpeg

PROBE_VIDEO = {
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "9.000000",
               "tags": {"title": "Diwali", "major_brand": "isom"}},
    "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720, "avg_frame_rate": "30000/1001",
         "disposition": {"attached_pic": 0}, "tags": {"handler_name": "VideoHandler"}},
        {"codec_type": "audio", "codec_name": "aac", "tags": {"language": "mar"}},
    ],
}


def test_probe_json_is_parsed_into_facts() -> None:
    result = ffmpeg.parse_probe(PROBE_VIDEO)
    assert (result.container, result.duration_ms, result.width, result.height) == ("mov", 9000, 1280, 720)
    assert result.fps == pytest.approx(29.97, abs=0.01) and result.has_video and result.has_audio
    assert (result.video_codec, result.audio_codec) == ("h264", "aac")
    assert result.tags["title"] == "Diwali" and result.tags["language"] == "mar"


def test_cover_art_is_not_a_video_stream() -> None:
    payload = {"format": {"format_name": "mov,mp4,m4a", "duration": "12.5"}, "streams": [
        {"codec_type": "audio", "codec_name": "aac"},
        {"codec_type": "video", "codec_name": "mjpeg", "width": 600, "height": 600, "disposition": {"attached_pic": 1}},
    ]}
    result = ffmpeg.parse_probe(payload)
    assert result.has_audio and not result.has_video and result.duration_ms == 12_500 and result.width is None


@pytest.mark.parametrize("duration", [None, "N/A", "nan", "-3", "inf"])
def test_a_missing_or_nonsense_duration_falls_back_to_the_streams_or_none(duration: Any) -> None:
    payload: dict[str, Any] = {"format": {"duration": duration}, "streams": [{"codec_type": "audio", "duration": "4.2"}]}
    assert ffmpeg.parse_probe(payload).duration_ms == 4200
    payload["streams"] = [{"codec_type": "audio"}]
    assert ffmpeg.parse_probe(payload).duration_ms is None


def test_scene_times_are_read_from_showinfo_lines() -> None:
    stderr = (
        "[Parsed_showinfo_1 @ 0x1] n:   0 pts:  75000 pts_time:3 duration: 1\n"
        "[Parsed_showinfo_1 @ 0x1] n:   1 pts: 150000 pts_time:6.04 duration: 1\n"
        "[Parsed_showinfo_1 @ 0x1] n:   2 pts: 150000 pts_time:6.04 duration: 1\n"  # a repeat collapses
        "frame=  1 fps=0.0 q=-0.0 Lsize=N/A time=00:00:09.00\n"
    )
    assert ffmpeg.parse_scene_times(stderr) == [3000, 6040]


# --- a missing binary is a clear typed error -----------------------------------------------------------


@pytest.fixture
def no_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FFMPEG_PATH", "ffmpeg-is-not-installed-here")
    monkeypatch.setenv("FFPROBE_PATH", "ffprobe-is-not-installed-here")
    get_settings.cache_clear()
    monkeypatch.setattr(ffmpeg, "_tools", None)
    yield
    get_settings.cache_clear()


def test_a_missing_binary_is_detected_and_named(no_ffmpeg: None) -> None:
    tools = ffmpeg.detect_tools(force=True)
    assert not tools.ffmpeg.available and not tools.ffprobe.available
    assert "ffmpeg-is-not-installed-here" in (tools.ffmpeg.message or "") and "Install ffmpeg" in (tools.ffmpeg.message or "")
    with pytest.raises(ffmpeg.MediaToolMissing) as caught:
        ffmpeg.require("ffprobe")
    assert isinstance(caught.value, ProviderNotConfigured) and caught.value.status_code == 503
    assert "Video and audio processing is unavailable" in caught.value.message


async def test_every_ffmpeg_entry_point_raises_the_typed_error(no_ffmpeg: None, tmp_path: Path) -> None:
    ffmpeg.detect_tools(force=True)
    src = tmp_path / "x.mp4"
    src.write_bytes(b"x")
    for call in (
        ffmpeg.probe_file(src), ffmpeg.detect_scene_changes(src, 0.3), ffmpeg.extract_frame(src, 0, tmp_path / "f.jpg", max_width=100),
        ffmpeg.extract_audio(src, tmp_path / "a.wav", max_seconds=60),
    ):
        with pytest.raises(ffmpeg.MediaToolMissing):
            await call


# --- failures and timeouts, with the subprocess faked --------------------------------------------------


@pytest.fixture
def fake_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = ffmpeg.Tool("ffmpeg", "/bin/ffmpeg", "9.0", None)
    monkeypatch.setattr(ffmpeg, "_tools", ffmpeg.Tools(tool, ffmpeg.Tool("ffprobe", "/bin/ffprobe", "9.0", None)))


async def test_ffprobe_failure_is_a_clear_validation_error(fake_tools: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def failing(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, 1, b"", b"Invalid data found when processing input /secret/server/path")

    monkeypatch.setattr(subprocess, "run", failing)
    with pytest.raises(ffmpeg.MediaUnreadable) as caught:
        await ffmpeg.probe_file(tmp_path / "bad.mp4")
    assert isinstance(caught.value, ValidationFailed) and caught.value.status_code == 422
    assert "secret" not in caught.value.message  # ffprobe's own text (paths) is never passed on


async def test_ffprobe_output_that_is_not_json_is_unreadable(fake_tools: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, b"not json", b""))
    with pytest.raises(ffmpeg.MediaUnreadable):
        await ffmpeg.probe_file(tmp_path / "bad.mp4")


async def test_a_command_that_hangs_is_stopped_and_reported(fake_tools: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def hang(args: Any, **kwargs: Any) -> None:
        assert kwargs["timeout"] > 0 and kwargs["stdin"] == subprocess.DEVNULL  # bounded, and never reads our stdin
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(ffmpeg.MediaProcessingFailed, match="took longer than"):
        await ffmpeg.detect_scene_changes(tmp_path / "slow.mp4", 0.3)


async def test_every_command_runs_with_a_file_only_protocol_whitelist(fake_tools: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def record(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, b'{"format": {"duration": "1"}, "streams": []}', b"")

    monkeypatch.setattr(subprocess, "run", record)
    out = tmp_path / "out.jpg"
    out.write_bytes(b"jpeg")
    await ffmpeg.probe_file(tmp_path / "in.mp4")
    await ffmpeg.detect_scene_changes(tmp_path / "in.mp4", 0.3)
    await ffmpeg.extract_frame(tmp_path / "in.mp4", 500, out, max_width=640)
    assert len(seen) == 3
    for args in seen:  # a crafted container cannot make ffmpeg open a network address or another protocol
        assert args[args.index("-protocol_whitelist") + 1] == "file"


# --- the real binaries ---------------------------------------------------------------------------------


@pytest.fixture
def real_tools() -> None:
    ffmpeg.detect_tools(force=True)


@requires_ffmpeg
async def test_real_probe_scene_detection_frames_and_audio(real_tools: None, tmp_path: Path) -> None:
    video = make_video(tmp_path / "three.mp4", scenes=3, seconds_each=3)
    probe = await ffmpeg.probe_file(video)
    assert probe.has_video and probe.has_audio and probe.duration_ms == pytest.approx(9000, abs=200)
    assert (probe.width, probe.height) == (320, 240)
    scenes = await ffmpeg.detect_scene_changes(video, 0.3)
    assert len(scenes) == 2 and abs(scenes[0] - 3000) < 150 and abs(scenes[1] - 6000) < 150
    frame = await ffmpeg.extract_frame(video, 4500, tmp_path / "f.jpg", max_width=160)
    assert frame[:3] == b"\xff\xd8\xff" and len(frame) > 100
    wav = await ffmpeg.extract_audio(video, tmp_path / "a.wav", max_seconds=60)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE" and len(wav) > 16000 * 2 * 8  # mono 16 kHz 16-bit, about 9 s


@requires_ffmpeg
async def test_real_probe_of_audio_and_of_garbage(real_tools: None, tmp_path: Path) -> None:
    audio = await ffmpeg.probe_file(make_audio(tmp_path / "tone.wav", seconds=4))
    assert audio.has_audio and not audio.has_video and audio.duration_ms == pytest.approx(4000, abs=100)
    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(b"\x00\x00\x00\x18ftypisom" + bytes(200))
    with pytest.raises(ffmpeg.MediaUnreadable):
        await ffmpeg.probe_file(garbage)


def test_this_machine_status_is_reported_honestly() -> None:
    tools = ffmpeg.detect_tools(force=True)
    assert tools.ffmpeg.available == HAS_FFMPEG
