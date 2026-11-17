"""Type a file by its magic bytes, never by filename or client header (the same discipline as image uploads).

`sniff(data, kind)` answers (content type, extension) when the bytes fit the declared kind, else None. ISO base media
files (mp4, mov, m4a) share one `ftyp` box, so the brand and the declared kind decide; ffprobe then confirms the streams.
"""

from app.schemas.assets import AssetKind

ALLOWED: dict[str, str] = {
    "image": "PNG, JPEG, or WebP",
    "video": "MP4, MOV, or WebM",
    "audio": "MP3, WAV, or M4A",
}
EXTENSIONS = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "video/mp4": "mp4", "video/quicktime": "mov",
    "video/webm": "webm", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/mp4": "m4a",
}
_AUDIO_BRANDS = (b"M4A ", b"M4B ", b"M4P ")
_EBML = b"\x1a\x45\xdf\xa3"


def _ftyp(data: bytes) -> bytes | None:
    """The major brand of an ISO base media file, or None."""
    return data[8:12] if len(data) >= 12 and data[4:8] == b"ftyp" else None


def _webm(data: bytes) -> bool:
    """WebM, not other Matroska: the EBML header names its DocType near the start."""
    return data.startswith(_EBML) and b"\x42\x82" in data[:64] and b"webm" in data[:64]


def _mp3(data: bytes) -> bool:
    if data.startswith(b"ID3"):
        return True
    # an MPEG audio frame header: 11 sync bits, then a valid version (not 01) and layer (not 00)
    return len(data) >= 3 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0 and data[1] & 0x18 != 0x08 and data[1] & 0x06 != 0x00


def sniff(data: bytes, kind: AssetKind) -> tuple[str, str] | None:
    if kind == "image":
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", "png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", "jpg"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp", "webp"
        return None
    brand = _ftyp(data)
    if kind == "video":
        if _webm(data):
            return "video/webm", "webm"
        if brand == b"qt  ":
            return "video/quicktime", "mov"
        if brand is not None and brand not in _AUDIO_BRANDS:
            return "video/mp4", "mp4"
        return None
    if kind == "audio":
        if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            return "audio/wav", "wav"
        if _mp3(data):
            return "audio/mpeg", "mp3"
        if brand is not None and brand != b"qt  ":
            return "audio/mp4", "m4a"
    return None
