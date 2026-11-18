"""Regional text rendered in code (Remake: Visuals): correct Indic shaping, wrapping, size fitting, colour and shadow,
composited onto an image, with protected regions restored pixel for pixel from the original.

Why code and not the image model: generated Indic script is often wrong. Why raqm: Devanagari, Tamil, Malayalam, Bengali,
Telugu, Kannada, Gujarati, Gurmukhi and Odia need OpenType shaping (conjuncts, vowel signs that reorder around the base
letter), which Pillow performs only through libraqm (with FriBiDi and HarfBuzz). The Linux container installs it. Where
raqm is missing (a plain Windows development machine) Latin text still renders, and Indic text is REFUSED with
`ShapingUnavailable` rather than drawn unshaped, because wrongly shaped script is worse than no text. `shaping_engine()`
reports which mode this process is in.

Fonts are the bundled Noto Sans TTFs under app/assets/fonts (SIL Open Font License, OFL.txt). A line is split into runs by
script (Latin letters use Noto Sans, Indic letters their own script's font; digits, spaces and punctuation follow their
neighbours), so a Tamil line holding a Latin brand name draws both correctly.

Order: text first, locked regions last. A protected logo or product is therefore byte-identical to the original in the
result even if a text box overlaps it; the overlap is reported on the placement.
"""

import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

from app.core.errors import UnsupportedCapability, ValidationFailed
from app.schemas.media import LockedRegion, TextBox

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
SCRIPT_FONTS: dict[str, str] = {
    "Deva": "NotoSansDevanagari", "Taml": "NotoSansTamil", "Mlym": "NotoSansMalayalam", "Beng": "NotoSansBengali",
    "Telu": "NotoSansTelugu", "Knda": "NotoSansKannada", "Gujr": "NotoSansGujarati", "Guru": "NotoSansGurmukhi",
    "Orya": "NotoSansOriya", "Latn": "NotoSans",
}
COMPLEX_SCRIPTS = frozenset(SCRIPT_FONTS) - {"Latn"}
_BLOCKS = (
    (0x0900, 0x097F, "Deva"), (0xA8E0, 0xA8FF, "Deva"), (0x0980, 0x09FF, "Beng"), (0x0A00, 0x0A7F, "Guru"),
    (0x0A80, 0x0AFF, "Gujr"), (0x0B00, 0x0B7F, "Orya"), (0x0B80, 0x0BFF, "Taml"), (0x0C00, 0x0C7F, "Telu"),
    (0x0C80, 0x0CFF, "Knda"), (0x0D00, 0x0D7F, "Mlym"),
)
MAX_PIXELS = 16_800_000  # about 4096 x 4096: a decoded RGBA copy of this is 67 MB
MAX_LINES = 40


class ShapingUnavailable(UnsupportedCapability):
    """Indic text needs libraqm and this process does not have it."""


def shaping_engine() -> Literal["raqm", "basic"]:
    return "raqm" if features.check("raqm") else "basic"


def available_scripts() -> list[str]:
    return [script for script, stem in SCRIPT_FONTS.items() if (FONT_DIR / f"{stem}-Regular.ttf").is_file()]


@lru_cache(maxsize=128)
def _font(script: str, bold: bool, size: int, engine: str) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / f"{SCRIPT_FONTS[script]}-{'Bold' if bold else 'Regular'}.ttf"
    layout = ImageFont.Layout.RAQM if engine == "raqm" else ImageFont.Layout.BASIC
    return ImageFont.truetype(str(path), size, layout_engine=layout)


def char_script(ch: str) -> str | None:
    """The script a character belongs to; None for common characters (space, digits, punctuation, joiners, dandas)."""
    code = ord(ch)
    if code in (0x0964, 0x0965):
        return None
    for low, high, script in _BLOCKS:
        if low <= code <= high:
            return script
    if code > 0x7F and unicodedata.category(ch)[0] in "PS":
        return "Latn"  # typographic punctuation (middle dot, bullet, dashes, quotes): the Indic fonts lack it, so it is drawn in Latin
    return "Latn" if unicodedata.category(ch).startswith("L") else None


def split_runs(text: str, primary: str) -> list[tuple[str, str]]:
    """(script, text) runs. Common characters stay with the run before them (or the box's primary script at the start)."""
    runs: list[tuple[str, str]] = []
    for ch in text:
        script = char_script(ch) or (runs[-1][0] if runs else primary)
        if runs and runs[-1][0] == script:
            runs[-1] = (script, runs[-1][1] + ch)
        else:
            runs.append((script, ch))
    return runs


def _is_mark(ch: str) -> bool:
    return unicodedata.category(ch) in ("Mn", "Mc", "Me") or ch in "‌‍"


def clusters(word: str) -> list[str]:
    """Split a word into pieces that are safe to break between: a base letter keeps its vowel signs and marks, and a
    consonant followed by a virama (halant) stays joined to the next letter, so a conjunct is never cut."""
    pieces: list[str] = []
    for ch in word:
        joins = pieces and (_is_mark(ch) or unicodedata.combining(pieces[-1][-1]) == 9 or pieces[-1][-1] == "‍")
        if joins:
            pieces[-1] += ch
        else:
            pieces.append(ch)
    return pieces


@dataclass(frozen=True)
class _Style:
    primary: str
    bold: bool
    size: int
    engine: str
    language: str | None

    def width(self, text: str) -> float:
        total = 0.0
        for script, run in split_runs(text, self.primary):
            font = _font(script, self.bold, self.size, self.engine)
            total += font.getlength(run, language=self.language) if self.engine == "raqm" else font.getlength(run)
        return total


def wrap(text: str, style: _Style, max_width: float) -> list[str]:
    """Greedy word wrap, honouring newlines; a word wider than the box breaks only between clusters."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            if not word:
                continue
            candidate = f"{line} {word}" if line else word
            if style.width(candidate) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = ""
            if style.width(word) <= max_width:
                line = word
                continue
            for piece in clusters(word):  # a single word too wide for the box
                if line and style.width(line + piece) > max_width:
                    lines.append(line)
                    line = piece
                else:
                    line += piece
        lines.append(line)
        if len(lines) > MAX_LINES:
            break
    return lines[:MAX_LINES]


@dataclass
class TextPlacement:
    rect: tuple[int, int, int, int]
    font_size: int
    lines: list[str]
    fits: bool  # False when even min_size_px does not fit the box; the text is clipped to it
    overlaps_locked: bool = False


@dataclass
class RenderResult:
    image: Image.Image
    placements: list[TextPlacement]
    locked_restored: int
    engine: str = field(default_factory=shaping_engine)


def pixel_rect(bbox: list[float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    """A normalised [x, y, w, h] as pixel (x0, y0, x1, y1). The one rounding rule used to crop and to paste."""
    width, height = size
    x, y, w, h = bbox
    x0, y0 = round(x * width), round(y * height)
    x1, y1 = round((x + w) * width), round((y + h) * height)
    return max(0, x0), max(0, y0), min(width, max(x1, x0 + 1)), min(height, max(y1, y0 + 1))


def _rgba(colour: str) -> tuple[int, int, int, int]:
    value = colour.lstrip("#")
    parts = [int(value[i : i + 2], 16) for i in range(0, len(value), 2)]
    return (parts[0], parts[1], parts[2], parts[3] if len(parts) == 4 else 255)


def _metrics(style: _Style) -> tuple[int, int]:
    """(ascent, descent) of the tallest font a line in this style can use (its own script and Latin)."""
    fonts = [_font(script, style.bold, style.size, style.engine).getmetrics() for script in {style.primary, "Latn"}]
    return max(m[0] for m in fonts), max(m[1] for m in fonts)


def _natural_height(style: _Style) -> int:
    ascent, descent = _metrics(style)
    return ascent + descent


def _layout(box: TextBox, width: int, height: int, engine: str) -> tuple[_Style, list[str], bool]:
    """The largest font size (min_size_px to max_size_px) at which the wrapped text fits the box."""

    def fit(size: int) -> tuple[_Style, list[str], bool]:
        style = _Style(box.script, box.bold, size, engine, box.language)
        lines = wrap(box.text, style, width)
        block = len(lines) * _natural_height(style) * box.line_spacing
        widest = max((style.width(line) for line in lines), default=0)
        return style, lines, block <= height and widest <= width and len(lines) <= MAX_LINES

    low, high, best = box.min_size_px, box.max_size_px, None
    while low <= high:
        mid = (low + high) // 2
        result = fit(mid)
        if result[2]:
            best, low = result, mid + 1
        else:
            high = mid - 1
    return best or fit(box.min_size_px)


def _draw_box(box: TextBox, size: tuple[int, int], engine: str) -> tuple[Image.Image, TextPlacement]:
    width, height = size
    style, lines, fits = _layout(box, width, height, engine)
    line_h = _natural_height(style) * box.line_spacing
    ascent = _metrics(style)[0]
    block = line_h * len(lines)
    top = {"top": 0.0, "middle": (height - block) / 2, "bottom": height - block}[box.valign]
    top = max(0.0, top) if fits else 0.0

    def paint(colour: tuple[int, int, int, int], dx: int = 0, dy: int = 0) -> Image.Image:
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for index, line in enumerate(lines):
            x = {"left": 0.0, "center": (width - style.width(line)) / 2, "right": width - style.width(line)}[box.align]
            baseline = top + index * line_h + (line_h - _natural_height(style)) / 2 + ascent
            for script, run in split_runs(line, style.primary):
                font = _font(script, style.bold, style.size, engine)
                extra = {"language": style.language} if engine == "raqm" and style.language else {}
                draw.text((x + dx, baseline + dy), run, font=font, fill=colour, anchor="ls", **extra)
                x += font.getlength(run, **extra)
        return layer

    text_layer = paint(_rgba(box.color))
    if box.shadow:
        shadow = paint(_rgba(box.shadow.color), box.shadow.dx, box.shadow.dy)
        if box.shadow.blur:
            shadow = shadow.filter(ImageFilter.GaussianBlur(box.shadow.blur))
        text_layer = Image.alpha_composite(shadow, text_layer)
    return text_layer, TextPlacement((0, 0, width, height), style.size, lines, fits)


def render_text(
    boxes: list[TextBox], *, base: Image.Image | None = None, original: Image.Image | None = None,
    locked: list[LockedRegion] | None = None, canvas: tuple[int, int] | None = None, background: str = "#202020",
) -> RenderResult:
    """Draw `boxes` on `base` (else `original`, else a blank `canvas`), then restore every `locked` region from `original`.

    The result has the original's size when there is an original (a differently sized `base`, such as a generated image,
    is resized to it first so that restored regions copy 1:1)."""
    engine = shaping_engine()
    if engine != "raqm":
        needing = sorted({box.script for box in boxes if box.script in COMPLEX_SCRIPTS})
        if needing:
            raise ShapingUnavailable(
                f"Text in {', '.join(needing)} cannot be rendered on this server: complex-script shaping (libraqm with "
                "FriBiDi and HarfBuzz) is not installed. The Linux container includes it; Latin text still renders."
            )
    missing = [box.script for box in boxes if not (FONT_DIR / f"{SCRIPT_FONTS[box.script]}-Regular.ttf").is_file()]
    if missing:
        raise ShapingUnavailable(f"The bundled font for {missing[0]} is missing from this deployment.")
    source = base if base is not None else original
    if source is not None:
        target = original.size if original is not None else source.size
        image = source.convert("RGBA")
        if image.size != target:
            image = image.resize(target, Image.Resampling.LANCZOS)
    else:
        assert canvas is not None
        image = Image.new("RGBA", canvas, _rgba(background))
    placements: list[TextPlacement] = []
    locked = locked or []
    rects = [pixel_rect(region.bbox, image.size) for region in locked]
    for box in boxes:
        x0, y0, x1, y1 = pixel_rect(box.bbox, image.size)
        layer, placement = _draw_box(box, (x1 - x0, y1 - y0), engine)
        image.alpha_composite(layer, dest=(x0, y0))
        placement.rect = (x0, y0, x1, y1)
        placement.overlaps_locked = any(x0 < r[2] and r[0] < x1 and y0 < r[3] and r[1] < y1 for r in rects)
        placements.append(placement)
    restored = 0
    if original is not None and rects:
        reference = original.convert("RGBA")
        for rect in rects:
            image.paste(reference.crop(rect), rect[:2])
            restored += 1
    return RenderResult(image=image, placements=placements, locked_restored=restored, engine=engine)


def load_image(data: bytes) -> Image.Image:
    """Decode an uploaded image with a pixel cap (a decompression bomb is refused, never decoded)."""
    try:
        image = Image.open(BytesIO(data))
        if image.width * image.height > MAX_PIXELS:
            raise ValidationFailed(f"The image is larger than {MAX_PIXELS // 1_000_000} megapixels.")
        image.load()
    except ValidationFailed:
        raise
    except Exception:
        raise ValidationFailed("The image could not be decoded.") from None
    return image


def encode_png(image: Image.Image) -> bytes:
    """Lossless PNG (never JPEG: restored regions must stay identical). Opaque images drop the alpha channel."""
    if image.mode == "RGBA" and image.getchannel("A").getextrema() == (255, 255):
        image = image.convert("RGB")
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
