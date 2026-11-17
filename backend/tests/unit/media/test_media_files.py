"""File sniffing, keyframe selection and text sidecars: pure code, no ffmpeg, no database, no model."""

import pytest

from app.media.keyframes import select_keyframe_times
from app.media.sidecar import SidecarError, clean_tags, parse_sidecar, redact
from app.media.sniff import sniff
from tests.api.media_support import M4A, MKV, MOV, MP3, MP4, PNG, WAV, WEBM

# --- sniffing by magic bytes ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "kind", "expected"),
    [
        (PNG, "image", ("image/png", "png")),
        (b"\xff\xd8\xff\xe0" + bytes(20), "image", ("image/jpeg", "jpg")),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 " + bytes(8), "image", ("image/webp", "webp")),
        (MP4, "video", ("video/mp4", "mp4")),
        (MOV, "video", ("video/quicktime", "mov")),
        (WEBM, "video", ("video/webm", "webm")),
        (WAV, "audio", ("audio/wav", "wav")),
        (MP3, "audio", ("audio/mpeg", "mp3")),
        (b"\xff\xfb\x90\x00" + bytes(40), "audio", ("audio/mpeg", "mp3")),  # a bare MPEG frame, no ID3 tag
        (M4A, "audio", ("audio/mp4", "m4a")),
        (MP4, "audio", ("audio/mp4", "m4a")),  # a generic ISO brand may be audio only: ffprobe decides
    ],
)
def test_sniff_accepts_what_the_bytes_say(data: bytes, kind: str, expected: tuple[str, str]) -> None:
    assert sniff(data, kind) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (PNG, "video"), (PNG, "audio"), (WAV, "image"), (WAV, "video"), (MP4, "image"),
        (MKV, "video"),  # Matroska is not WebM
        (WEBM, "audio"), (M4A, "video"), (MOV, "audio"),
        (b"RIFF\x00\x00\x00\x00AVI LIST" + bytes(8), "video"),
        (b"#EXTM3U\n#EXT-X-VERSION:3\nhttp://example.com/a.ts\n", "video"),  # an HLS playlist is text, never a video
        (b"\xff\xf1" + bytes(20), "audio"),  # AAC ADTS: layer bits 00 are not MPEG audio
        (b"", "video"), (b"plain text pretending to be media", "audio"),
    ],
)
def test_sniff_refuses_everything_else(data: bytes, kind: str) -> None:
    assert sniff(data, kind) is None  # type: ignore[arg-type]


# --- keyframe selection --------------------------------------------------------------------------------


def gaps(times: list[int], duration: int) -> list[int]:
    return [b - a for a, b in zip(times, [*times[1:], duration])]


def test_a_static_video_still_gets_a_frame_every_few_seconds() -> None:
    times = select_keyframe_times([], 20_000, min_gap_ms=1000, max_gap_ms=4000, max_count=16)
    assert times[0] == 300  # near the start, not frame 0 (fades from black)
    assert max(gaps(times, 20_000)) <= 4000


def test_scene_changes_are_kept_with_a_minimum_spacing() -> None:
    times = select_keyframe_times([2500, 2900, 3100, 6000, 6400], 10_000, min_gap_ms=1000, max_gap_ms=4000)
    assert 2500 in times and 6000 in times  # the first of each burst
    assert not {2900, 3100, 6400} & set(times)  # inside the minimum gap of the previous frame
    assert all(b - a >= 1000 for a, b in zip(times, times[1:]))


def test_the_frame_cap_is_respected_and_the_opening_frame_stays() -> None:
    scenes = list(range(1000, 59_000, 1000))
    times = select_keyframe_times(scenes, 60_000, max_count=16)
    assert len(times) == 16 and times[0] == 300 and times == sorted(set(times))
    assert max(gaps(times, 60_000)) <= 8000  # thinning is even: no hole opens up


def test_very_short_media_and_degenerate_input() -> None:
    assert select_keyframe_times([], 0) == [] and select_keyframe_times([], -5) == []
    assert select_keyframe_times([], 50) == [0]
    assert select_keyframe_times([900_000], 1000) == [300]  # a scene change beyond the end is ignored
    assert select_keyframe_times([500, 700], 1500, max_count=1) == [300]


def test_no_frame_lands_after_the_last_decodable_moment() -> None:
    times = select_keyframe_times([9990], 10_000)
    assert max(times) <= 9900


# --- text sidecar, redaction, container tags -----------------------------------------------------------


def test_emails_and_phone_numbers_are_replaced_with_markers_and_counted() -> None:
    text = "Mail priya.sharma+ads@example.co.in or call +91 98765 43210, 098765-43210 or 9876543210. Ref 2026-11-17."
    cleaned, counts = redact(text)
    assert counts == {"email": 1, "phone": 3}
    assert "@" not in cleaned and "98765" not in cleaned and "43210" not in cleaned
    assert "[email removed]" in cleaned and cleaned.count("[phone removed]") == 3
    assert "2026-11-17" in cleaned  # a date is not a phone number


@pytest.mark.parametrize("text", ["Sale 50% off until 31/12/2026", "Order #12345", "Call us 1800", "00:01:02,500 --> 00:01:04,000", "v1.2.3.4"])
def test_ordinary_numbers_are_left_alone(text: str) -> None:
    assert redact(text) == (text, {})


SRT = "1\n00:00:00,500 --> 00:00:02,000\nNamaste, write to asha@example.com\n\n2\n00:00:02,500 --> 00:00:04,000\nCall 9876543210 today\n"
VTT = "WEBVTT\n\n00:01.000 --> 00:03.500\nHello there\n\n1:02:03.004 --> 1:02:05.000\nLine one\nline two\n"


def test_srt_is_parsed_into_timed_redacted_segments() -> None:
    sidecar = parse_sidecar(SRT.encode())
    assert sidecar.format == "srt" and sidecar.redacted == {"email": 1, "phone": 1}
    assert sidecar.segments == [
        {"start_ms": 500, "end_ms": 2000, "text": "Namaste, write to [email removed]"},
        {"start_ms": 2500, "end_ms": 4000, "text": "Call [phone removed] today"},
    ]
    assert "asha" not in sidecar.text and "98765" not in sidecar.text


def test_vtt_cues_and_hour_timestamps() -> None:
    sidecar = parse_sidecar(b"\xef\xbb\xbf" + VTT.encode())
    assert sidecar.format == "vtt"
    assert [(s["start_ms"], s["end_ms"], s["text"]) for s in sidecar.segments] == [
        (1000, 3500, "Hello there"), (3_723_004, 3_725_000, "Line one line two"),
    ]


def test_plain_notes_have_no_segments() -> None:
    sidecar = parse_sidecar("Festival campaign. Contact: ravi@brand.in".encode())
    assert sidecar.format == "text" and sidecar.segments == [] and sidecar.redacted == {"email": 1}
    assert sidecar.text == "Festival campaign. Contact: [email removed]"


@pytest.mark.parametrize(
    "data",
    [b"", b"   \n", b"\xff\xfe\x00bad", b"a\x00b", pytest.param(b"x" * (200 * 1024 + 1), id="over-200-kb")],
)
def test_an_unusable_sidecar_is_refused_with_a_message(data: bytes) -> None:
    with pytest.raises(SidecarError):
        parse_sidecar(data)


def test_container_tags_are_filtered_to_an_allowlist_and_redacted() -> None:
    tags = {
        "title": "Diwali Sale", "Comment": "shot by ravi@brand.in, 9876543210", "location": "+19.0760+072.8777/",
        "com.apple.quicktime.model": "iPhone", "artist": "Asha Rao", "encoder": "Lavf63", "LANGUAGE": "mar",
    }
    kept, redacted, dropped = clean_tags(tags)
    assert kept == {"title": "Diwali Sale", "comment": "shot by [email removed], [phone removed]", "encoder": "Lavf63", "language": "mar"}
    assert redacted == {"email": 1, "phone": 1} and dropped == 3  # location, device and author tags never reach a model
