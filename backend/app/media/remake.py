"""Pure image and audio steps of Remake: Visuals and Remake: Sound. No database, no provider, no network.

Visuals: the generated scene is fitted to the original's size, a legibility scrim is added, the regional text is drawn
with the Indic renderer (app/media/textrender.py), and every locked region is restored from the original LAST, so the
stored PNG holds exactly the original's pixels there. `verify_locked` proves it by decoding the stored bytes again.
Sound: speech clips are joined into one track with timings.
"""

import io
import wave
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageChops, ImageOps, ImageStat

from app.llm.media import ASPECT_RATIOS
from app.media import textrender
from app.schemas.media import LockedRegion, TextBox, TextShadow
from app.studio.checks import script_of

NEVER_CHANGE_KINDS = frozenset({"logo", "packshot", "product", "tagline"})  # the default Brand Kit never-change zones
TEXT_KINDS = frozenset({"headline", "body", "cta", "caption", "tagline"})
BOLD_KINDS = frozenset({"headline", "cta"})
MAX_BOX_TEXT = 400
WHITE, INK = "#ffffff", "#111111"
SHADOW = TextShadow(dx=2, dy=2, blur=3, color="#000000b0")
HALO = TextShadow(dx=0, dy=0, blur=4, color="#ffffffc0")  # dark text on a busy light scene was hard to read without it
MIN_BOX_PX = 18  # shortest text box drawn; shorter boxes are grown (a Tamil line is taller than a Latin one)
LARGE_TEXT_PX = 24  # at this size or above the contrast threshold is 3.0, below it 4.5 (WCAG large and normal text)


def closest_aspect(width: int, height: int) -> str:
    ratio = width / height
    return min(ASPECT_RATIOS, key=lambda a: abs(int(a.split(":")[0]) / int(a.split(":")[1]) - ratio))


def fit_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale and centre-crop to exactly `size` (no stretching)."""
    return ImageOps.fit(image.convert("RGB"), size, Image.Resampling.LANCZOS)


def safe_bbox(bbox: list[float]) -> list[float]:
    x, y, w, h = (float(v) for v in bbox)
    x, y = min(max(x, 0.0), 0.999), min(max(y, 0.0), 0.999)
    return [round(x, 5), round(y, 5), round(max(min(w, 1.0 - x), 0.001), 5), round(max(min(h, 1.0 - y), 0.001), 5)]


def pad_small(bbox: list[float], size: tuple[int, int]) -> list[float]:
    """Give a very short text box room for Indic ascenders and descenders: a box under MIN_BOX_PX is grown to it, centred."""
    height = size[1]
    if bbox[3] * height >= MIN_BOX_PX:
        return bbox
    grown = MIN_BOX_PX / height
    y = min(max(bbox[1] + bbox[3] / 2 - grown / 2, 0.0), 1.0 - grown)
    return [bbox[0], round(y, 5), bbox[2], round(grown, 5)]


def paste_regions(base: Image.Image, original: Image.Image, bboxes: list[list[float]]) -> Image.Image:
    """`base` with each region copied exactly from `original` (the same size): the layout the model sees."""
    out, source = base.convert("RGB"), original.convert("RGB")
    for bbox in bboxes:
        rect = textrender.pixel_rect(bbox, out.size)
        out.paste(source.crop(rect), rect[:2])
    return out


def add_scrim(image: Image.Image) -> Image.Image:
    """Darken the top and bottom bands a little so light text stays legible on any generated scene (done in code and
    recorded; the original creative had the same treatment)."""
    width, height = image.size
    out = image.convert("RGBA")
    for y0, y1, peak, from_top in ((0, int(height * 0.30), 150, True), (int(height * 0.62), height, 175, False)):
        gradient = Image.linear_gradient("L").resize((width, y1 - y0))
        if from_top:
            gradient = ImageOps.flip(gradient)
        layer = Image.new("RGBA", (width, y1 - y0), (0, 0, 0, 0))
        layer.putalpha(gradient.point(lambda v: v * peak // 255))
        out.alpha_composite(layer, dest=(0, y0))
    return out.convert("RGB")


def _linear(channel: float) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_linear(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def mean_luminance(image: Image.Image, rect: tuple[int, int, int, int]) -> float:
    data = image.crop(rect).convert("RGB").resize((12, 12), Image.Resampling.BOX).tobytes()
    pixels = [(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 3)]
    return sum(luminance(p) for p in pixels) / len(pixels)


def contrast_ratio(a: float, b: float) -> float:
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)


def dominant_script(text: str) -> str:
    counts: dict[str, int] = {}
    for char in text:
        script = script_of(char)
        if script and script != "Zzzz":
            counts[script] = counts.get(script, 0) + 1
    indic = {k: v for k, v in counts.items() if k != "Latn"}
    pool = indic or counts
    return max(pool, key=pool.get) if pool else "Latn"


def indic_scripts_in(text: str) -> set[str]:
    return {s for s in (script_of(c) for c in text) if s and s not in ("Latn", "Zzzz")}


@dataclass
class Composite:
    png: bytes
    width: int
    height: int
    engine: str
    texts: list[dict[str, Any]]
    locked_identical: list[bool]


def plan_box(spec: dict[str, Any], base: Image.Image, target_script: str, target_language: str) -> tuple[TextBox | None, dict[str, Any]]:
    """The TextBox for one text element and the code checks that need no rendering (script, contrast colour)."""
    text, problems = str(spec["text"]), []
    script = spec.get("script") if spec.get("script") in textrender.SCRIPT_FONTS else dominant_script(text)
    foreign = indic_scripts_in(text) - {target_script}
    if foreign:
        problems.append(f"The text is in {', '.join(sorted(foreign))}, not {target_script}: transcreate it for this region first.")
    bbox = pad_small(safe_bbox(spec["bbox"]), base.size)
    rect = textrender.pixel_rect(bbox, base.size)
    height_px = rect[3] - rect[1]
    bg = mean_luminance(base, rect)
    white, ink = contrast_ratio(1.0, bg), contrast_ratio(luminance((17, 17, 17)), bg)
    colour, ratio = (WHITE, white) if white >= ink else (INK, ink)
    meta: dict[str, Any] = {
        "element_id": spec["element_id"], "kind": spec["kind"], "text": text, "language": spec.get("language"), "script": script,
        "bbox": bbox, "color": colour, "contrast_ratio": ratio, "script_ok": not foreign,
    }
    if len(text) > MAX_BOX_TEXT:
        problems.append(f"The text is longer than {MAX_BOX_TEXT} characters and was not drawn.")
        meta["problems"] = problems
        return None, meta
    max_size = max(12, min(200, int(height_px * 0.9)))
    center = abs((bbox[0] + bbox[2] / 2) - 0.5) < 0.03
    box = TextBox(
        text=text, script=script, language=spec.get("language") if spec.get("language") and len(spec["language"]) <= 3 else None,
        bbox=bbox, align="center" if center else "left", valign="middle", color=colour, bold=spec["kind"] in BOLD_KINDS,
        min_size_px=9, max_size_px=max_size, shadow=SHADOW if colour == WHITE else HALO,
    )
    meta["problems"] = problems
    return box, meta


def compose(original: Image.Image, generated: Image.Image, locked: list[dict[str, Any]], texts: list[dict[str, Any]],
            target_script: str, target_language: str) -> Composite:
    """Generated scene + scrim, then text in code, then the locked regions from the original. Raises ShapingUnavailable
    when Indic text cannot be shaped on this server (never draws unshaped script)."""
    base = add_scrim(fit_cover(generated, original.size))
    boxes: list[TextBox] = []
    metas: list[dict[str, Any]] = []
    order: list[int] = []
    for spec in texts:
        box, meta = plan_box(spec, base, target_script, target_language)
        metas.append(meta)
        if box is not None:
            boxes.append(box)
            order.append(len(metas) - 1)
    regions = [LockedRegion(label=f"{r['label']}"[:40], bbox=safe_bbox(r["bbox"])) for r in locked]
    result = textrender.render_text(boxes, base=base, original=original, locked=regions)
    for placement, index in zip(result.placements, order, strict=True):
        meta = metas[index]
        meta.update(font_size=placement.font_size, lines=placement.lines, fits=placement.fits, overlaps_locked=placement.overlaps_locked)
    for meta in metas:
        meta.setdefault("font_size", 0)
        meta.setdefault("lines", [])
        meta.setdefault("fits", False)
        meta.setdefault("overlaps_locked", False)
        threshold = 3.0 if meta["font_size"] >= LARGE_TEXT_PX else 4.5
        meta["low_contrast"] = meta["contrast_ratio"] < threshold
        if not meta["fits"] and meta["font_size"]:
            meta["problems"].append("The text does not fit its box even at the smallest size; it is clipped.")
        if meta["overlaps_locked"]:
            meta["problems"].append("The text box overlaps a locked region; the locked pixels win, so the text is covered there.")
        if meta["low_contrast"] and meta["font_size"]:
            meta["problems"].append(f"Low contrast (about {meta['contrast_ratio']}:1 against the scene).")
        meta["passed"] = not meta["problems"]
    png = textrender.encode_png(result.image)
    return Composite(png, result.image.width, result.image.height, result.engine, metas, verify_locked(png, original, locked))


def verify_locked(png: bytes, original: Image.Image, locked: list[dict[str, Any]]) -> list[bool]:
    """For each locked region: do the stored bytes, decoded again, hold exactly the original's pixels?"""
    stored = Image.open(io.BytesIO(png)).convert("RGB")
    source = original.convert("RGB")
    out = []
    for region in locked:
        rect = textrender.pixel_rect(safe_bbox(region["bbox"]), source.size)
        out.append(ImageChops.difference(stored.crop(rect), source.crop(rect)).getbbox() is None)
    return out


# --- audio ----------------------------------------------------------------------------------------------------


def wav_params(data: bytes) -> tuple[int, int, int]:
    with wave.open(io.BytesIO(data)) as clip:
        return clip.getnchannels(), clip.getsampwidth(), clip.getframerate()


def wav_frames(data: bytes) -> bytes:
    with wave.open(io.BytesIO(data)) as clip:
        return clip.readframes(clip.getnframes())


def duration_ms(data: bytes) -> int:
    with wave.open(io.BytesIO(data)) as clip:
        return round(clip.getnframes() * 1000 / clip.getframerate())


def concat_wavs(clips: list[bytes], gap_ms: int = 450) -> tuple[bytes, list[tuple[int, int]]]:
    """One WAV from clips of the same format, with `gap_ms` of silence between them, and each clip's (start_ms, end_ms)."""
    if not clips:
        raise ValueError("No clips to join.")
    params = wav_params(clips[0])
    if any(wav_params(c) != params for c in clips):
        raise ValueError("The clips differ in format and cannot be joined.")
    channels, width, rate = params
    silence = bytes(int(rate * gap_ms / 1000) * channels * width)
    frames, spans, cursor = [], [], 0
    for index, clip in enumerate(clips):
        length = duration_ms(clip)
        if index:
            frames.append(silence)
            cursor += gap_ms
        frames.append(wav_frames(clip))
        spans.append((cursor, cursor + length))
        cursor += length
    out = io.BytesIO()
    with wave.open(out, "wb") as track:
        track.setnchannels(channels)
        track.setsampwidth(width)
        track.setframerate(rate)
        track.writeframes(b"".join(frames))
    return out.getvalue(), spans


def image_stat_brightness(image: Image.Image) -> float:  # kept for tests that assert the scrim darkens the bands
    return ImageStat.Stat(image.convert("L")).mean[0]
