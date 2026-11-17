"""Text that travels with an upload: a sidecar file (SRT, WebVTT, or plain notes) and the container's metadata tags.

Before any of it can reach a model, emails and phone numbers are found and replaced with a marker, and the counts are
kept. Container tags are filtered to an allowlist first (location, device and author tags are never kept). The original,
unredacted text is not stored anywhere.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

MAX_SIDECAR_BYTES = 200 * 1024
MAX_TAG_CHARS = 300
TAG_ALLOWLIST = ("title", "comment", "description", "synopsis", "language", "creation_time", "encoder")

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
# a run of 10 to 15 digits with common separators, not part of a timestamp, date, path, or longer word
PHONE = re.compile(r"(?<![\w/:.,])(?:\+|00)?\d(?:[ \t().\-]?\d){8,16}(?![\w:])")
MARKERS = {"email": "[email removed]", "phone": "[phone removed]"}
_CUE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})")


def redact(text: str) -> tuple[str, dict[str, int]]:
    """The text with emails and phone numbers replaced by markers, and how many of each were removed."""
    counts = {"email": 0, "phone": 0}

    def email(_: re.Match[str]) -> str:
        counts["email"] += 1
        return MARKERS["email"]

    def phone(match: re.Match[str]) -> str:
        digits = len(re.sub(r"\D", "", match.group()))
        if not 10 <= digits <= 15:
            return match.group()
        counts["phone"] += 1
        return MARKERS["phone"]

    cleaned = PHONE.sub(phone, EMAIL.sub(email, text))
    return cleaned, {kind: n for kind, n in counts.items() if n}


def merge_counts(*groups: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for group in groups:
        for kind, n in group.items():
            merged[kind] = merged.get(kind, 0) + n
    return merged


def clean_tags(tags: dict[str, str]) -> tuple[dict[str, str], dict[str, int], int]:
    """(allowlisted tags with PII redacted, redaction counts, number of tags dropped). Keys compare case-insensitively."""
    kept: dict[str, str] = {}
    redacted: dict[str, int] = {}
    dropped = 0
    for key, value in tags.items():
        name = key.strip().lower()
        if name not in TAG_ALLOWLIST or not isinstance(value, str):
            dropped += 1
            continue
        text, counts = redact(_printable(value)[:MAX_TAG_CHARS])
        kept[name] = text
        redacted = merge_counts(redacted, counts)
    return kept, redacted, dropped


def _printable(text: str) -> str:
    return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C").strip()


@dataclass
class Sidecar:
    format: Literal["srt", "vtt", "text"]
    text: str  # redacted; for srt and vtt the cue text only
    segments: list[dict] = field(default_factory=list)  # {"start_ms", "end_ms", "text"}, redacted
    redacted: dict[str, int] = field(default_factory=dict)


class SidecarError(ValueError):
    """The sidecar is unusable; the message is safe to show the uploader."""


def _ms(hours: str | None, minutes: str, seconds: str, millis: str) -> int:
    return ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def parse_sidecar(data: bytes) -> Sidecar:
    if len(data) > MAX_SIDECAR_BYTES:
        raise SidecarError(f"The text sidecar is larger than {MAX_SIDECAR_BYTES // 1024} KB.")
    try:
        raw = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SidecarError("The text sidecar must be UTF-8 text.") from None
    if "\x00" in raw or not raw.strip():
        raise SidecarError("The text sidecar must be non-empty UTF-8 text.")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    cues = _cues(raw)
    if cues:
        segments, counts = [], {}
        for start, end, body in cues:
            text, found = redact(_printable(body))
            counts = merge_counts(counts, found)
            if text:
                segments.append({"start_ms": start, "end_ms": end, "text": text})
        fmt: Literal["srt", "vtt", "text"] = "vtt" if raw.lstrip().startswith("WEBVTT") else "srt"
        return Sidecar(fmt, "\n".join(s["text"] for s in segments), segments, counts)
    text, counts = redact(_printable(raw))
    return Sidecar("text", text, [], counts)


def _cues(raw: str) -> list[tuple[int, int, str]]:
    """Timed cues of an SRT or WebVTT file; empty when the text has no cue timings."""
    cues = []
    for block in re.split(r"\n{2,}", raw):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            match = _CUE.search(line)
            if match:
                g = match.groups()
                body = " ".join(part.strip() for part in lines[i + 1 :] if part.strip())
                cues.append((_ms(*g[:4]), _ms(*g[4:]), body))
                break
    return cues
