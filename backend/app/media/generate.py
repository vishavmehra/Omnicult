"""Pure image and audio steps of the Generate studio. No database, no provider, no network.

Image: the generated scene is fitted to the format, a legibility scrim is added when there is a headline, the logo and the
product image are placed in code, and the headline is drawn with the Indic renderer (app/media/textrender.py). The model
never draws lettering. Audio: speech clips are retimed (pace), a jingle is cut to length with a fade-out, and loudness
peaks are computed from the samples.
"""

import array
import asyncio
import io
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from app.media import ffmpeg, textrender
from app.media import remake as pipeline

FORMATS: dict[str, tuple[int, int]] = {"1:1": (1080, 1080), "4:5": (1080, 1350), "9:16": (1080, 1920), "16:9": (1920, 1080)}
FORMAT_LABELS = {"1:1": "Square", "4:5": "Portrait", "9:16": "Story", "16:9": "Landscape"}
PACE_TEMPO = {"slow": 0.85, "normal": 1.0, "brisk": 1.15}  # ffmpeg atempo keeps the pitch; 0.5 to 2.0 is its range
PEAK_SLICES = 96
FADE_MS = 600
DEFAULT_LOGO_MIN_PX = 160
MARGIN = 0.05


@dataclass
class Placed:
    kind: str
    label: str
    bbox: list[float]
    width_px: int


@dataclass
class ImageComposite:
    png: bytes
    width: int
    height: int
    engine: str
    placements: list[Placed]
    headline: dict[str, Any] | None
    checks: list[dict[str, Any]]


def _fit_width(image: Image.Image, width: int, max_height: int) -> Image.Image:
    ratio = min(width / image.width, max_height / image.height)
    return image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))), Image.Resampling.LANCZOS)


def _bbox(x: int, y: int, size: tuple[int, int], canvas: tuple[int, int]) -> list[float]:
    return [round(x / canvas[0], 5), round(y / canvas[1], 5), round(size[0] / canvas[0], 5), round(size[1] / canvas[1], 5)]


def pick_lockup(lockups: list[tuple[str, Image.Image]], dark: bool) -> tuple[str, Image.Image] | None:
    """The reversed lockup on a dark scene, the primary one on a light scene, else the first. Lockups are (id, image)."""
    if not lockups:
        return None
    wanted = "reversed" if dark else "primary"
    return next((x for x in lockups if wanted in x[0]), lockups[0])


def compose_image(
    scene: Image.Image, fmt: str, *, logo: list[tuple[str, Image.Image]], product: Image.Image | None, headline: dict[str, Any] | None,
    script: str, language: str, logo_min_px: int = DEFAULT_LOGO_MIN_PX, logo_asset: Any = None, product_asset: Any = None,
) -> ImageComposite:
    """The finished creative. Raises ShapingUnavailable when the headline's script cannot be shaped on this server (the
    caller checks this before any paid call). `headline` is {text, language} or None."""
    size = FORMATS[fmt]
    wide = fmt == "16:9"
    base = pipeline.fit_cover(scene, size)
    if headline:
        base = pipeline.add_scrim(base)
    canvas = base.convert("RGBA")
    placed: list[Placed] = []
    checks: list[dict[str, Any]] = [{"id": "size", "label": "Output size", "passed": canvas.size == size, "detail": f"{canvas.width} x {canvas.height}"}]
    margin = round(size[0] * MARGIN)
    if logo:
        top_left = (margin, margin, round(size[0] * (0.22 if wide else 0.34)), round(size[1] * 0.12))
        dark = pipeline.mean_luminance(base, (top_left[0], top_left[1], top_left[0] + top_left[2], top_left[1] + top_left[3])) < 0.35
        picked = pick_lockup(logo, dark)
        assert picked is not None
        lid, mark = picked
        mark = _fit_width(mark.convert("RGBA"), top_left[2], top_left[3])
        canvas.alpha_composite(mark, dest=(margin, margin))
        placed.append(Placed("logo", lid, _bbox(margin, margin, mark.size, size), mark.width))
        checks.append({"id": "logo_size", "label": "Logo at or above the Brand Kit minimum width", "passed": mark.width >= logo_min_px,
                       "detail": f"{mark.width} px; the minimum is {logo_min_px} px"})
    if product is not None:
        box_w, box_h = round(size[0] * (0.26 if wide else 0.38)), round(size[1] * (0.46 if wide else 0.32))
        shown = _fit_width(product.convert("RGBA"), box_w, box_h)
        x, y = size[0] - margin - shown.width, size[1] - margin - shown.height
        canvas.alpha_composite(shown, dest=(x, y))
        placed.append(Placed("product", "product", _bbox(x, y, shown.size, size), shown.width))
    texts: dict[str, Any] | None = None
    engine = textrender.shaping_engine()
    if headline:
        top = (0.05 + 0.12 + 0.02) if logo else 0.08
        bbox = [0.06, 0.2 if wide else round(top, 3), 0.5 if wide else 0.88, 0.3 if wide else 0.16]
        spec = {"element_id": "headline", "kind": "headline", "text": headline["text"], "language": headline.get("language"),
                "script": script, "bbox": bbox}
        box, meta = pipeline.plan_box(spec, canvas.convert("RGB"), script, language)
        if box is not None:
            result = textrender.render_text([box], base=canvas)
            placement = result.placements[0]
            canvas, engine = result.image, result.engine
            meta.update(font_size=placement.font_size, lines=placement.lines, fits=placement.fits)
        for key, default in (("font_size", 0), ("lines", []), ("fits", False)):
            meta.setdefault(key, default)
        meta["low_contrast"] = meta["contrast_ratio"] < (3.0 if meta["font_size"] >= pipeline.LARGE_TEXT_PX else 4.5)
        if not meta["fits"] and meta["font_size"]:
            meta["problems"].append("The headline does not fit its box even at the smallest size; it is clipped.")
        if meta["low_contrast"] and meta["font_size"]:
            meta["problems"].append(f"Low contrast (about {meta['contrast_ratio']}:1 against the scene).")
        texts = meta
        checks += [
            {"id": "headline_script", "label": "Headline is in the expected script", "passed": bool(meta["script_ok"]),
             "detail": None if meta["script_ok"] else "; ".join(meta["problems"])},
            {"id": "headline_fits", "label": "Headline fits its box", "passed": bool(meta["fits"]), "detail": f"{meta['font_size']} px"},
            {"id": "headline_contrast", "label": "Headline contrast", "passed": not meta["low_contrast"],
             "detail": f"about {meta['contrast_ratio']}:1"},
        ]
    png = textrender.encode_png(canvas)
    return ImageComposite(png, canvas.width, canvas.height, engine, placed, texts, checks)


# --- audio --------------------------------------------------------------------------------------------------------


def wav_samples(data: bytes) -> tuple[array.array, int, int]:
    """(16-bit samples, channels, sample rate). Raises wave.Error on anything but 16-bit PCM."""
    with wave.open(io.BytesIO(data)) as clip:
        if clip.getsampwidth() != 2:
            raise wave.Error("Only 16-bit PCM audio is supported.")
        channels, rate = clip.getnchannels(), clip.getframerate()
    start = data.find(b"data", 12)  # the header's frame count is not trusted (Lyria's is wrong): read to the end of the file
    if start < 0:
        raise wave.Error("The audio has no data chunk.")
    payload = data[start + 8:]
    samples = array.array("h")
    samples.frombytes(payload[: len(payload) // (2 * channels) * 2 * channels])
    return samples, channels, rate


def peaks(data: bytes, slices: int = PEAK_SLICES) -> list[int]:
    """Loudness per slice of the track, 0 to 100 (the largest sample in the slice over the loudest in the track)."""
    samples, _, _ = wav_samples(data)
    if not samples:
        return [0] * slices
    step = max(1, -(-len(samples) // slices))
    maxima = [max(abs(v) for v in samples[i:i + step]) for i in range(0, len(samples), step)][:slices]
    top = max(maxima) or 1
    return [round(m * 100 / top) for m in maxima] + [0] * (slices - len(maxima))


def trim_with_fade(data: bytes, seconds: float, fade_ms: int = FADE_MS) -> bytes:
    """The first `seconds` of a 16-bit PCM WAV, with a linear fade-out over the last `fade_ms`. A clip shorter than `seconds`
    is only faded."""
    samples, channels, rate = wav_samples(data)
    frames = min(len(samples) // channels, round(seconds * rate))
    out = samples[: frames * channels]
    fade = min(frames, round(rate * fade_ms / 1000))
    for i in range(fade):
        gain = (fade - i) / fade
        for c in range(channels):
            index = (frames - fade + i) * channels + c
            out[index] = int(out[index] * gain)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(channels)
        clip.setsampwidth(2)
        clip.setframerate(rate)
        clip.writeframes(out.tobytes())
    return buffer.getvalue()


def can_retime() -> bool:
    return ffmpeg.detect_tools().ffmpeg.available


async def retime(data: bytes, tempo: float) -> bytes:
    """`data` played at `tempo` (1.0 = unchanged) with the pitch kept, through ffmpeg's atempo filter."""
    if abs(tempo - 1.0) < 1e-6:
        return data
    exe = ffmpeg.require("ffmpeg")
    with tempfile.TemporaryDirectory() as folder:
        source, target = Path(folder) / "in.wav", Path(folder) / "out.wav"
        source.write_bytes(data)
        args = [exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file", "-i", str(source),
                "-filter:a", f"atempo={tempo:.3f}", "-c:a", "pcm_s16le", "-y", str(target)]
        done = await ffmpeg._run(args, timeout=60, what="Changing the pace")  # noqa: SLF001 - same package
        out = target.read_bytes() if target.exists() else b""
    if done.returncode != 0 or not out:
        raise ffmpeg.MediaProcessingFailed("The pace could not be changed.")
    return out


async def retime_all(clips: list[bytes], tempo: float) -> list[bytes]:
    return list(await asyncio.gather(*(retime(c, tempo) for c in clips)))
