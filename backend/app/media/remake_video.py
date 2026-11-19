"""Pure steps of Remake: Video. No database, no provider, no network (ffmpeg and ffprobe run as local processes).

The start frame: the regional key visual WITHOUT its text (the generated scene with the locked regions restored from the
original, exactly the layout Remake: Visuals shows its model) is placed on a Veo canvas (720x1280 or 1280x720). Regional text
is never part of it: a video model would animate and garble it, so any on-screen text is added in code after the clip, or
the clip has none. The voice-over join copies the video stream and never cuts speech: a track longer than the clip is not
joined. `inspect_clip` measures the delivered file; nothing here trusts what a model says about its own output.

Brand elements (logo, tagline, product tin, headline) are drawn in code, never by the model. The start frame has them wiped out
(`wipe_region`); `build_overlay` draws them on one transparent layer at the clip's resolution (the Brand Kit files, text through the
Indic renderer); `apply_overlay` puts that layer over every frame with ffmpeg; `check_brand` then samples the FINAL clip every
0.5 s and compares each element's box with the layer, so a drift (or an overlay bug) is measured, not assumed.
"""

import asyncio
import io
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps, ImageStat
from pydantic import BaseModel

from app.core.errors import ValidationFailed
from app.media import ffmpeg, textrender
from app.media import remake as stills

CANVAS = {"9:16": (720, 1280), "16:9": (1280, 720)}  # Veo 3.1 takes these two aspect ratios; 720p is the requested resolution
BLUR_RADIUS = 28
EXTENSION_DIM = 0.78  # the blurred extension is a little darker than the picture, so the picture reads as the subject
JOIN_TOLERANCE_MS = 250  # a voice-over this much longer than the clip is still joined (ffmpeg trims the silence at its end)
SAMPLE_EVERY_MS = 500  # the final clip is sampled this often for the brand check
SAMPLE_LIMIT = 40  # at most this many frames (20 s of clip)
DRIFT_LIMIT = 18.0  # mean absolute difference (0-255, over the element's opaque pixels) above which a frame is flagged
OPAQUE = 250  # overlay alpha at or above this counts as "drawn" for the comparison
WIPE_PAD_PX = 10  # how far past an element's box the start frame is wiped (a model's copy of a mark is never exactly the box)
WIPED_ROLES = ("logo", "tagline")  # wiped from the start frame; the tin stays in it (the overlay covers it exactly), headlines have no place in the scene
ROLE_LABELS = {"logo": "Logo", "tagline": "Tagline", "tin": "Product tin", "headline": "Headline"}
BrandRole = Literal["logo", "tagline", "tin", "headline"]


def aspect_for(size: tuple[int, int]) -> str:
    """The Veo aspect ratio that suits an image: portrait and square pictures go to 9:16, landscape to 16:9."""
    return "9:16" if size[1] >= size[0] else "16:9"


class BrandSpec(BaseModel):
    """One brand element to draw in code over the clip. `bbox` is [x, y, w, h] in the key visual (the original creative)."""

    element_id: str
    role: BrandRole
    label: str
    bbox: list[float]
    text: str | None = None  # tagline and headline: what to render
    language: str | None = None
    script: str | None = None
    asset_id: UUID | None = None  # logo and tin: the Brand Kit file (a PNG with transparency)
    image: bytes | None = None  # that file's bytes, loaded by the service


def placement(size: tuple[int, int], aspect: str) -> tuple[int, int, int, int, int, int]:
    """(x, y, w, h, canvas_w, canvas_h): where a picture of `size` sits, contained, on the Veo canvas of `aspect`."""
    width, height = CANVAS[aspect]
    scale = min(width / size[0], height / size[1])
    w, h = max(1, round(size[0] * scale)), max(1, round(size[1] * scale))
    return (width - w) // 2, (height - h) // 2, w, h, width, height


def in_frame(bbox: list[float], layout_size: tuple[int, int], aspect: str) -> list[float]:
    """A key-visual bbox as a bbox of the whole start frame (and so of the clip): the same position and scale."""
    x, y, w, h, cw, ch = placement(layout_size, aspect)
    bx, by, bw, bh = bbox
    return [round((x + bx * w) / cw, 5), round((y + by * h) / ch, 5), round(bw * w / cw, 5), round(bh * h / ch, 5)]


def _edge(image: Image.Image, box: tuple[int, int, int, int], size: tuple[int, int]) -> Image.Image:
    """A thin strip of `image` (a few pixels thick, averaged to one) stretched over `size`: one edge of a wipe."""
    strip = image.crop(box)
    vertical = box[2] - box[0] < box[3] - box[1]
    strip = strip.resize((1, strip.height) if vertical else (strip.width, 1), Image.Resampling.BOX)
    return strip.filter(ImageFilter.GaussianBlur(max(3, max(strip.size) // 8))).resize(size, Image.Resampling.NEAREST)


def wipe_region(image: Image.Image, bbox: list[float]) -> Image.Image:
    """`image` with the region smoothly filled from the pixels around it (no model, no source pixels): a calm patch where a
    brand element will be drawn in code. The fill blends the four surrounding edges and is feathered into the picture."""
    out = image.convert("RGB")
    width, height = out.size
    x0, y0, x1, y1 = textrender.pixel_rect(bbox, out.size)
    pad = WIPE_PAD_PX
    x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(width, x1 + pad), min(height, y1 + pad)
    w, h = x1 - x0, y1 - y0
    if w < 4 or h < 4:
        return out
    gap, thick = 3, 3
    left = _edge(out, (max(0, x0 - gap - thick), y0, max(1, x0 - gap), y1), (w, h))
    right = _edge(out, (min(width - 1, x1 + gap), y0, min(width, x1 + gap + thick), y1), (w, h))
    top = _edge(out, (x0, max(0, y0 - gap - thick), x1, max(1, y0 - gap)), (w, h))
    bottom = _edge(out, (x0, min(height - 1, y1 + gap), x1, min(height, y1 + gap + thick)), (w, h))
    ramp = Image.linear_gradient("L")
    across = ramp.transpose(Image.Transpose.ROTATE_90).resize((w, h))  # black at the left, white at the right
    down = ramp.resize((w, h))  # black at the top, white at the bottom
    fill = Image.blend(Image.composite(right, left, across), Image.composite(bottom, top, down), 0.5)
    feather = max(2, min(pad // 2, w // 4, h // 4))  # the blend stays inside the padding: the box itself is fully replaced
    mask = Image.new("L", (w, h), 0)
    mask.paste(255, (feather, feather, w - feather, h - feather))
    out.paste(fill, (x0, y0), mask.filter(ImageFilter.GaussianBlur(feather / 2)))
    return out


def build_layout(original: Image.Image, scene: Image.Image | None, locked_bboxes: list[list[float]],
                 wipe_bboxes: list[list[float]] | None = None) -> Image.Image:
    """The key visual without text: `scene` (or the original when there is none) fitted to the original's size, with every
    region in `wipe_bboxes` (brand elements that are drawn in code later) wiped and every one in `locked_bboxes` copied back
    from the original. When anything is wiped, the legibility scrim of the finished creative is applied first, so the text
    drawn later reads the way it does in the key visual."""
    base = stills.fit_cover(scene or original, original.size)
    if wipe_bboxes:
        base = stills.add_scrim(base)
        for bbox in wipe_bboxes:
            base = wipe_region(base, bbox)
    return stills.paste_regions(base, original, locked_bboxes) if locked_bboxes else base


def start_frame(layout: Image.Image, aspect_ratio: str | None = None) -> tuple[bytes, str, tuple[int, int]]:
    """(PNG bytes, aspect ratio, canvas size). The picture is contained, never cropped or stretched, on a canvas whose empty
    bands are a blurred, dimmed extension of the picture itself, so no brand element is cut off."""
    aspect = aspect_ratio or aspect_for(layout.size)
    x, y, w, h, width, height = placement(layout.size, aspect)
    picture = layout.convert("RGB")
    fitted = picture.resize((w, h), Image.Resampling.LANCZOS)
    canvas = stills.fit_cover(picture, (width, height)).filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    canvas = ImageEnhance.Brightness(canvas).enhance(EXTENSION_DIM)
    canvas.paste(fitted, (x, y))
    return textrender.encode_png(canvas), aspect, (width, height)


def thumbnail_jpeg(png: bytes, max_side: int = 480) -> bytes:
    """A small JPEG of a frame for the preview (the full frame is what the model receives)."""
    import io

    image = Image.open(io.BytesIO(png)).convert("RGB")
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=82)
    return out.getvalue()


@dataclass(frozen=True)
class ClipFacts:
    """What ffprobe read from the delivered file."""

    container: str | None
    video_codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    duration_ms: int | None
    has_video: bool
    has_audio: bool
    size_bytes: int


async def inspect_clip(video: bytes) -> ClipFacts:
    """Probe `video` (written to a temporary file). Raises ffmpeg.MediaToolMissing or ffmpeg.MediaUnreadable."""
    with tempfile.TemporaryDirectory(prefix="remake-video-") as tmp:
        path = Path(tmp) / "clip.mp4"
        await asyncio.to_thread(path.write_bytes, video)
        probe = await ffmpeg.probe_file(path)
    return ClipFacts(probe.container, probe.video_codec, probe.width, probe.height, probe.fps, probe.duration_ms, probe.has_video,
                     probe.has_audio, len(video))


async def join_voiceover(video: bytes, voiceover_wav: bytes, clip_ms: int) -> bytes:
    """The clip with the voice-over as its audio track. The caller has checked the track fits (`voiceover_fits`)."""
    with tempfile.TemporaryDirectory(prefix="remake-video-") as tmp:
        folder = Path(tmp)
        await asyncio.to_thread(lambda: (folder / "clip.mp4").write_bytes(video))
        await asyncio.to_thread(lambda: (folder / "voice.wav").write_bytes(voiceover_wav))
        return await ffmpeg.mux_audio(folder / "clip.mp4", folder / "voice.wav", folder / "joined.mp4", max_seconds=clip_ms / 1000)


def voiceover_fits(voiceover_ms: int, clip_ms: int) -> bool:
    return voiceover_ms <= clip_ms + JOIN_TOLERANCE_MS


# --- brand elements: drawn in code, then measured ---------------------------------------------------------------


@dataclass
class PlacedItem:
    element_id: str
    role: str
    label: str
    rect: tuple[int, int, int, int]  # pixels of the clip


@dataclass
class Overlay:
    png: bytes  # RGBA, the size of the clip
    size: tuple[int, int]
    placed: list[PlacedItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _artwork(spec: BrandSpec, original: Image.Image | None, rect: tuple[int, int, int, int]) -> tuple[Image.Image | None, str | None]:
    """(RGBA tile the size of `rect`, a note) for a logo or tin: the Brand Kit file contained in the box, else the source
    creative's own pixels for that box (opaque), else nothing."""
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    name = ROLE_LABELS[spec.role].lower()
    problem = None
    if spec.image:
        try:
            art = ImageOps.contain(textrender.load_image(spec.image).convert("RGBA"), (w, h), Image.Resampling.LANCZOS)
            tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            tile.alpha_composite(art, ((w - art.width) // 2, (h - art.height) // 2))
            return tile, None
        except ValidationFailed:
            problem = f"The Brand Kit file for the {name} could not be read"
    lead = problem or f"No Brand Kit file is linked for the {name}"
    if original is not None:
        crop = original.convert("RGB").crop(textrender.pixel_rect(spec.bbox, original.size)).resize((w, h), Image.Resampling.LANCZOS)
        return crop.convert("RGBA"), f"{lead}: the patch from the source creative is used."
    return None, f"{lead}, and there is no source creative: it was left out."


def build_overlay(size: tuple[int, int], layout_size: tuple[int, int], aspect: str, frame: Image.Image, specs: list[BrandSpec],
                  original: Image.Image | None, target_script: str) -> Overlay:
    """One transparent RGBA layer of `size` (the clip resolution) holding every element at the position and scale it has in the
    remade key visual. Logos and tins are Brand Kit files; text is rendered with the Indic renderer in the element's own script
    (the tagline) or the region script (the headline). Text in another script is left out, never drawn unshaped or untranslated."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    backdrop = frame.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    placed: list[PlacedItem] = []
    notes: list[str] = []
    boxes, box_items = [], []
    for spec in specs:
        name = ROLE_LABELS[spec.role]
        bbox = in_frame(stills.safe_bbox(spec.bbox), layout_size, aspect)
        rect = textrender.pixel_rect(bbox, size)
        item = PlacedItem(spec.element_id, spec.role, name, rect)
        text = (spec.text or "").strip()
        if spec.role in ("logo", "tin") or (spec.role == "tagline" and not text):
            tile, note = _artwork(spec, original, rect)
            if note:
                notes.append(note)
            if tile is not None:
                layer.alpha_composite(tile, rect[:2])
                placed.append(item)
            continue
        if not text:
            notes.append(f"The {name.lower()} has no text, so none was drawn.")
            continue
        script = spec.script if spec.role == "tagline" and spec.script in textrender.SCRIPT_FONTS else target_script
        box, meta = stills.plan_box({"element_id": spec.element_id, "kind": spec.role, "text": text, "language": spec.language,
                                     "script": spec.script, "bbox": bbox}, backdrop, script, spec.language or "")
        if box is None or not meta["script_ok"]:
            notes.append(f"The {name.lower()} was left out: " + (meta["problems"][0] if meta["problems"] else "it could not be drawn."))
            continue
        boxes.append(box)
        box_items.append(item)
    if boxes:
        try:
            result = textrender.render_text(boxes, canvas=size, background="#00000000")
        except textrender.ShapingUnavailable as exc:
            notes.append(f"The text was left out: {getattr(exc, 'message', str(exc))}")
        else:
            layer.alpha_composite(result.image)
            for drawn, item in zip(result.placements, box_items, strict=True):
                placed.append(item)
                if not drawn.fits:
                    notes.append(f"The {item.label.lower()} does not fit its box even at the smallest size and is clipped.")
    out = io.BytesIO()
    layer.save(out, format="PNG")
    return Overlay(out.getvalue(), size, placed, notes)


async def apply_overlay(video: bytes, overlay: Overlay) -> bytes:
    """`video` with the overlay drawn over every frame (audio, if any, is copied). Raises ffmpeg.MediaToolMissing or
    ffmpeg.MediaProcessingFailed."""
    with tempfile.TemporaryDirectory(prefix="remake-video-") as tmp:
        folder = Path(tmp)
        await asyncio.to_thread(lambda: (folder / "clip.mp4").write_bytes(video))
        await asyncio.to_thread(lambda: (folder / "layer.png").write_bytes(overlay.png))
        return await ffmpeg.overlay_png(folder / "clip.mp4", folder / "layer.png", folder / "branded.mp4")


@dataclass
class BrandResult:
    element_id: str
    role: str
    label: str
    sampled: int
    failed_ms: list[int]
    worst: float | None  # the largest mean difference seen; None when nothing opaque could be compared
    checkable: bool


def drift(frame: Image.Image, layer: Image.Image, rect: tuple[int, int, int, int]) -> float | None:
    """Mean absolute difference (0-255, all channels) between a frame and the overlay layer inside `rect`, over the pixels the
    layer draws opaquely (elsewhere the scene shows through and may legitimately move). None when the layer draws nothing there."""
    tile = layer.crop(rect)
    mask = tile.getchannel("A").point(lambda v: 255 if v >= OPAQUE else 0)
    if mask.getbbox() is None:
        return None
    if frame.size != layer.size:
        frame = frame.resize(layer.size, Image.Resampling.LANCZOS)
    core = mask.filter(ImageFilter.MinFilter(3))  # the interior: codec blur at the edges of strokes is not drift
    diff = ImageChops.difference(frame.convert("RGB").crop(rect), tile.convert("RGB"))
    return sum(ImageStat.Stat(diff, core if core.getbbox() else mask).mean) / 3


def compare_frames(frames: list[tuple[int, Image.Image]], overlay: Overlay) -> list[BrandResult]:
    layer = Image.open(io.BytesIO(overlay.png)).convert("RGBA")
    results = []
    for item in overlay.placed:
        failed, worst, checkable = [], None, False
        for at_ms, frame in frames:
            value = drift(frame, layer, item.rect)
            if value is None:
                continue
            checkable = True
            worst = value if worst is None else max(worst, value)
            if value > DRIFT_LIMIT:
                failed.append(at_ms)
        results.append(BrandResult(item.element_id, item.role, item.label, len(frames), failed, worst, checkable))
    return results


async def check_brand(video: bytes, overlay: Overlay) -> list[BrandResult]:
    """Sample the FINAL clip every SAMPLE_EVERY_MS and compare each element box with the overlay layer. Raises
    ffmpeg.MediaToolMissing or ffmpeg.MediaProcessingFailed."""
    with tempfile.TemporaryDirectory(prefix="remake-video-") as tmp:
        folder = Path(tmp)
        (folder / "frames").mkdir()
        await asyncio.to_thread(lambda: (folder / "clip.mp4").write_bytes(video))
        files = await ffmpeg.extract_frames(folder / "clip.mp4", folder / "frames", every_ms=SAMPLE_EVERY_MS, limit=SAMPLE_LIMIT)

        def go() -> list[BrandResult]:
            frames = []
            for at_ms, path in files:
                with Image.open(path) as image:
                    frames.append((at_ms, image.convert("RGB")))
            return compare_frames(frames, overlay)

        return await asyncio.to_thread(go)
