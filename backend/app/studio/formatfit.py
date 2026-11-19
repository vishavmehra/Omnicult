"""Format Fit (feature 24), version format-fit-v1. Pure, deterministic code: Pillow for pixels, no model, no network, no database.

What it does. It takes the creative as it is (a picture of known size, the boxes of its elements, which of them are locked)
and works out how it would sit in each channel format: where a crop window goes, or how it is padded, what that cuts off,
what falls outside the platform's safe zone, which text becomes too small to read, and whether a locked region is hurt. It
reports every one of those things and decides nothing: a plan changes no file. Applying a plan is a separate, explicit act.

Cropping and padding only. Nothing is stretched, generated or extended by a model: a crop keeps the pixels it keeps, and a
pad adds bars of one colour. A locked element (a logo, the pack, the tagline) must stay whole: the crop window is chosen to
keep every locked box inside it when that is possible, and a plan that cuts one is a conflict that cannot be applied.

Safe zones are working defaults for each format (how much of each edge platform interface usually covers). They are
planning values and are named as such; the platform's own current guidance is the authority.

Video: cut-downs are suggestions from the X-Ray scene timings. A scene is kept or dropped whole (the last scene, which holds the
end card, may be shortened); nothing is rendered.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from PIL import Image, ImageStat

FIT_VERSION = "format-fit-v1"
Strategy = Literal["crop", "pad", "native"]
Verdict = Literal["clean", "review", "conflict"]
TEXT_KINDS = frozenset({"headline", "body", "cta", "tagline", "caption", "voiceover"})
BASIS = "Working default for planning. Check the platform's current guidance before relying on it."
UPSCALE_REVIEW = 1.25
RETAINED_REVIEW = 0.5
TEXT_WHOLE = 0.97  # a text box this much inside the frame counts as whole
MIN_TEXT_PX = 24  # one line of text, on a frame whose shorter side is 1080 px
MIN_CAPTION_PX = 40  # the Brand Kit's typography rule for captions on a 1080 x 1920 frame


@dataclass(frozen=True)
class FormatSpec:
    id: str
    name: str
    ratio: str
    width: int
    height: int
    safe: tuple[float, float, float, float]  # top, right, bottom, left: the share of each edge the platform interface covers
    used_for: str
    channel_ids: tuple[str, ...]

    @property
    def aspect(self) -> float:
        return self.width / self.height

    @property
    def safe_rect(self) -> tuple[float, float, float, float]:
        top, right, bottom, left = self.safe
        return left, top, 1 - right, 1 - bottom


FORMATS: tuple[FormatSpec, ...] = (
    FormatSpec("1x1", "Square", "1:1", 1080, 1080, (0.04, 0.04, 0.04, 0.04), "Feed posts and carousels", ("instagram_square",)),
    FormatSpec("4x5", "Portrait", "4:5", 1080, 1350, (0.04, 0.04, 0.04, 0.04), "Facebook and Instagram feed", ("meta_feed", "instagram_feed", "facebook_feed")),
    FormatSpec("9x16", "Vertical", "9:16", 1080, 1920, (0.14, 0.06, 0.22, 0.06), "Reels, Shorts, Stories and WhatsApp Status",
               ("instagram_reels", "youtube_shorts", "whatsapp_status", "instagram_stories", "facebook_reels", "tiktok")),
    FormatSpec("16x9", "Landscape", "16:9", 1920, 1080, (0.05, 0.05, 0.05, 0.05), "YouTube, the web and connected TV", ("youtube", "youtube_video", "connected_tv")),
)
BY_ID = {f.id: f for f in FORMATS}
RATIO = re.compile(r"(?<!\d)(\d{1,2})\s*:\s*(\d{1,2})(?!\d)")


def format_for_channel(channel_id: str, name: str | None, format_text: str | None) -> FormatSpec | None:
    """The format a Campaign Brief channel runs in: by its known id, else by a ratio written in its name or format."""
    for spec in FORMATS:
        if channel_id in spec.channel_ids:
            return spec
    for text in (format_text, name):
        match = RATIO.search(text or "")
        if match:
            ratio = f"{int(match.group(1))}:{int(match.group(2))}"
            spec = next((f for f in FORMATS if f.ratio == ratio), None)
            if spec:
                return spec
    return None


def nearest_format(width: int, height: int) -> FormatSpec:
    return min(FORMATS, key=lambda f: abs(f.aspect - width / height))


# --- the plan for a picture ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Box:
    id: str
    kind: str
    bbox: tuple[float, float, float, float] | None  # normalised [x, y, w, h] of the source picture, or None when unknown
    locked: bool = False
    text: str | None = None


@dataclass(frozen=True)
class Layout:
    """Which part of the source is shown (`window`, source px) and where it lands in the output frame (`place`, output px)."""

    strategy: Strategy
    window: tuple[int, int, int, int]
    place: tuple[int, int, int, int]
    scale: float


@dataclass
class Placed:
    box: Box
    bbox_out: tuple[float, float, float, float] | None
    visible: float
    placement: Literal["kept", "cut", "outside", "unknown"]
    in_safe: bool | None
    overflow: list[str]
    text_px: float | None
    min_text_px: float | None


@dataclass
class Issue:
    code: str
    severity: Literal["conflict", "review", "info"]
    message: str
    element_id: str | None = None


@dataclass
class StrategyPlan:
    layout: Layout
    placed: list[Placed]
    issues: list[Issue]
    retained: float
    verdict: Verdict
    background: str | None = None


def _rect(box: Box, w: int, h: int) -> tuple[float, float, float, float]:
    x, y, bw, bh = box.bbox  # type: ignore[misc]
    return x * w, y * h, (x + bw) * w, (y + bh) * h


def _inter(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _out_rect(rect: tuple[float, float, float, float], layout: Layout, spec: FormatSpec) -> tuple[float, float, float, float]:
    """The element's rectangle in the output frame as shares of the frame (it may extend past the edges)."""
    wx, wy, _, _ = layout.window
    px, py, _, _ = layout.place
    k = layout.scale
    return (
        (px + (rect[0] - wx) * k) / spec.width, (py + (rect[1] - wy) * k) / spec.height,
        (px + (rect[2] - wx) * k) / spec.width, (py + (rect[3] - wy) * k) / spec.height,
    )


def _measure(box: Box, source: tuple[int, int], layout: Layout, spec: FormatSpec) -> Placed:
    if box.bbox is None:
        return Placed(box, None, 1.0, "unknown", None, [], None, None)
    rect = _rect(box, *source)
    area = max((rect[2] - rect[0]) * (rect[3] - rect[1]), 1e-9)
    wx, wy, ww, wh = layout.window
    visible = _inter(rect, (wx, wy, wx + ww, wy + wh)) / area
    out = _out_rect(rect, layout, spec)
    left, top, right, bottom = spec.safe_rect
    overflow = [side for side, hit in (("top", out[1] < top), ("right", out[2] > right), ("bottom", out[3] > bottom), ("left", out[0] < left)) if hit]
    # A locked box must be whole. A text box is measured with a little tolerance: its box usually has padding around the glyphs.
    whole = 0.999 if box.locked else TEXT_WHOLE
    placement: Literal["kept", "cut", "outside"] = "kept" if visible >= whole else "outside" if visible <= 0.001 else "cut"
    text_px = min_px = None
    if box.kind in TEXT_KINDS:
        lines = (box.text or "").count("\n") + 1
        text_px = (out[3] - out[1]) * spec.height / lines
        min_px = (MIN_CAPTION_PX if box.kind == "caption" else MIN_TEXT_PX) * min(spec.width, spec.height) / 1080
    inside = (max(0.0, out[0]), max(0.0, out[1]), min(1.0, out[2]) - max(0.0, out[0]), min(1.0, out[3]) - max(0.0, out[1]))
    # an element wholly outside the frame has no box in it (clipping alone left a negative width or height)
    return Placed(box, inside if inside[2] > 0 and inside[3] > 0 else None,
                  visible, placement, not overflow and placement == "kept", overflow, text_px, min_px)


def _cost(boxes: Sequence[Box], source: tuple[int, int], layout: Layout, spec: FormatSpec) -> float:
    """What a window costs: a cut locked box is worth far more than a cut text box, which is worth more than anything else."""
    total = 0.0
    for box in boxes:
        if box.bbox is None:
            continue
        placed = _measure(box, source, layout, spec)
        cut = 1.0 - placed.visible
        text = box.kind in TEXT_KINDS
        total += (1000.0 if box.locked else 100.0 if text else 1.0) * cut
        if placed.placement == "kept" and not placed.in_safe and (text or box.locked):
            total += 3.0 if box.locked else 10.0
    return total


def crop_layout(source: tuple[int, int], boxes: Sequence[Box], spec: FormatSpec) -> Layout:
    """The largest window of the output's aspect ratio, slid along its one free axis to the position that costs least."""
    w, h = source
    if w / h >= spec.aspect:
        ww, wh = round(h * spec.aspect), h
        candidates = [Layout("crop", (x, 0, ww, wh), (0, 0, spec.width, spec.height), spec.width / ww) for x in range(w - ww + 1)]
        centre = (w - ww) / 2
    else:
        ww, wh = w, round(w / spec.aspect)
        candidates = [Layout("crop", (0, y, ww, wh), (0, 0, spec.width, spec.height), spec.width / ww) for y in range(h - wh + 1)]
        centre = (h - wh) / 2
    return min(candidates, key=lambda c: (_cost(boxes, source, c, spec), abs(c.window[0] + c.window[1] - centre), c.window[0] + c.window[1]))


def pad_layout(source: tuple[int, int], spec: FormatSpec) -> Layout:
    """The whole picture, as large as fits, centred in the frame; the rest is bars of one colour."""
    w, h = source
    k = min(spec.width / w, spec.height / h)
    pw, ph = round(w * k), round(h * k)
    return Layout("pad", (0, 0, w, h), ((spec.width - pw) // 2, (spec.height - ph) // 2, pw, ph), k)


def native_layout(source: tuple[int, int], spec: FormatSpec) -> Layout:
    w, h = source
    return Layout("native", (0, 0, w, h), (0, 0, spec.width, spec.height), spec.width / w)


def assess(boxes: Sequence[Box], source: tuple[int, int], layout: Layout, spec: FormatSpec, *, background: str | None = None) -> StrategyPlan:
    """Everything the layout does to every element, and the issues it raises."""
    placed = [_measure(b, source, layout, spec) for b in boxes]
    issues: list[Issue] = []
    for p in placed:
        b = p.box
        text = b.kind in TEXT_KINDS
        if p.placement == "unknown":
            continue
        if b.locked and p.placement != "kept":
            issues.append(Issue("locked_cut", "conflict", f"Locked element {b.id} is {'cut off' if p.placement == 'cut' else 'outside the frame'} ({int(p.visible * 100)}% visible).", b.id))
        elif b.locked and not p.in_safe:
            issues.append(Issue("locked_unsafe", "review", f"Locked element {b.id} reaches into the {', '.join(p.overflow)} safe margin. It cannot be moved here.", b.id))
        elif text and p.placement != "kept":
            issues.append(Issue("text_cut", "conflict", f"Text {b.id} is {'cut off' if p.placement == 'cut' else 'outside the frame'} ({int(p.visible * 100)}% visible).", b.id))
        elif text and not p.in_safe:
            issues.append(Issue("text_unsafe", "review", f"Text {b.id} reaches into the {', '.join(p.overflow)} safe margin, where platform interface may cover it.", b.id))
        if text and p.placement == "kept" and p.text_px is not None and p.min_text_px is not None and p.text_px < p.min_text_px:
            issues.append(Issue("text_small", "review", f"Text {b.id} is about {p.text_px:.0f} px tall in the output; at least {p.min_text_px:.0f} px reads comfortably.", b.id))
    unknown = [p.box.id for p in placed if p.placement == "unknown"]
    if unknown:
        issues.append(Issue("no_position", "info", f"{len(unknown)} element(s) have no position on the picture and were not checked: {', '.join(unknown[:6])}{'…' if len(unknown) > 6 else ''}."))
    if layout.scale > UPSCALE_REVIEW:
        issues.append(Issue("upscaled", "review", f"The source is smaller than the output: it is enlarged {layout.scale:.2f} times and may look soft."))
    wx, wy, ww, wh = layout.window
    retained = (ww * wh) / (source[0] * source[1])
    if layout.strategy == "crop" and retained < RETAINED_REVIEW:
        issues.append(Issue("crop_loss", "review", f"Only {retained:.0%} of the picture remains after the crop."))
    if layout.strategy == "pad":
        px, py, pw, ph = layout.place
        bars = f"{px} px at the sides" if px else f"{py} px at the top and bottom"
        issues.append(Issue("padding", "info", f"The whole picture is kept; bars of {bars} fill the frame."))
    verdict: Verdict = "conflict" if any(i.severity == "conflict" for i in issues) else "review" if any(i.severity == "review" for i in issues) else "clean"
    return StrategyPlan(layout, placed, issues, retained, verdict, background)


def plan_strategies(boxes: Sequence[Box], source: tuple[int, int], spec: FormatSpec, *, background: str | None = None) -> list[StrategyPlan]:
    """Crop and pad (a picture already in the format's ratio needs neither: it is `native`)."""
    w, h = source
    if abs(w / h - spec.aspect) < 0.005:
        return [assess(boxes, source, native_layout(source, spec), spec)]
    return [assess(boxes, source, crop_layout(source, boxes, spec), spec), assess(boxes, source, pad_layout(source, spec), spec, background=background)]


def recommend(plans: Sequence[StrategyPlan]) -> Strategy | None:
    """The plan with the fewest conflicts, then the fewest review items; a tie goes to the crop (the earlier plan)."""
    if not plans:
        return None
    def rank(p: StrategyPlan) -> tuple[int, int]:
        return sum(i.severity == "conflict" for i in p.issues), sum(i.severity == "review" for i in p.issues)
    best = min(plans, key=rank)
    return best.layout.strategy


# --- pixels -------------------------------------------------------------------------------------------------------------


def edge_colour(image: Image.Image) -> str:
    """The mean colour of the picture's one-pixel border, as a hex string: bars that match the picture's own edge."""
    rgb = image.convert("RGB")
    w, h = rgb.size
    strips = [rgb.crop((0, 0, w, 1)), rgb.crop((0, h - 1, w, h)), rgb.crop((0, 0, 1, h)), rgb.crop((w - 1, 0, w, h))]
    means = [ImageStat.Stat(s).mean for s in strips]
    r, g, b = (round(sum(m[i] for m in means) / 4) for i in range(3))
    return f"#{r:02x}{g:02x}{b:02x}"


def render(image: Image.Image, layout: Layout, spec: FormatSpec, background: str) -> Image.Image:
    """The output frame at exactly the format's pixel size. A crop is resampled with Lanczos; a pad is the whole picture on a bar colour."""
    wx, wy, ww, wh = layout.window
    shown = image.convert("RGBA").crop((wx, wy, wx + ww, wy + wh))
    px, py, pw, ph = layout.place
    shown = shown.resize((pw, ph), Image.Resampling.LANCZOS)
    value = background.lstrip("#")
    canvas = Image.new("RGBA", (spec.width, spec.height), tuple(int(value[i : i + 2], 16) for i in (0, 2, 4)) + (255,))
    canvas.alpha_composite(shown, dest=(px, py))
    return canvas.convert("RGB")


# --- video cut-downs ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SceneBrief:
    id: str
    position: int
    start_ms: int
    end_ms: int
    summary: str | None = None
    kinds: frozenset[str] = frozenset()  # element kinds present in the scene
    locked_kinds: frozenset[str] = frozenset()


@dataclass
class Segment:
    scene_id: str
    position: int
    start_ms: int
    end_ms: int
    trimmed: bool
    reasons: list[str]


@dataclass
class Cutdown:
    target_ms: int
    duration_ms: int
    segments: list[Segment]
    dropped: list[dict[str, Any]]
    notes: list[str]
    feasible: bool = True
    score: int = 0


def scene_value(scene: SceneBrief, first: bool, last: bool) -> tuple[int, list[str]]:
    """What a scene is worth to keep, and why: the end card, the opening, the product, the headline, the call to action."""
    score, why = 1, []
    if last:
        score, why = score + 4, [*why, "End card: the call to action, logo and tagline"]
    if first:
        score, why = score + 2, [*why, "Opening scene"]
    if scene.kinds & {"product", "packshot"}:
        score, why = score + 2, [*why, "Shows the product"]
    if "headline" in scene.kinds:
        score, why = score + 1, [*why, "Carries a headline"]
    if "cta" in scene.kinds:
        score, why = score + 1, [*why, "Carries the call to action"]
    if scene.kinds & {"logo", "tagline"}:
        score, why = score + 1, [*why, "Carries the logo or tagline"]
    return score, why


UNIT = 100  # milliseconds per knapsack step


def suggest_cutdowns(scenes: Sequence[SceneBrief], targets_ms: Sequence[int]) -> list[Cutdown]:
    """For each target length: the scenes that keep the most value within it. The last scene is always kept and may be
    shortened; ties prefer the shorter total, then the earlier scenes. Nothing is rendered."""
    ordered = sorted(scenes, key=lambda s: s.position)[:40]
    if not ordered:
        return []
    values = [scene_value(s, i == 0, i == len(ordered) - 1) for i, s in enumerate(ordered)]
    last = ordered[-1]
    out: list[Cutdown] = []
    for target in sorted(set(targets_ms)):
        last_ms = last.end_ms - last.start_ms
        notes: list[str] = []
        chosen: list[int]
        trimmed_last = False
        if last_ms >= target:
            chosen, trimmed_last = [len(ordered) - 1], last_ms > target
            if trimmed_last:
                notes.append("Only the end card fits. It is shortened from its start; the voice-over and captions of that scene are not re-timed.")
        else:
            room = (target - last_ms) // UNIT
            items = [(i, -(-(s.end_ms - s.start_ms) // UNIT), values[i][0]) for i, s in enumerate(ordered[:-1])]
            table: dict[int, tuple[int, tuple[int, ...]]] = {0: (0, ())}
            for i, cost, score in items:
                for used, (have, picked) in sorted(table.items(), reverse=True):
                    new = used + cost
                    if new > room:
                        continue
                    candidate = (have + score, tuple(sorted((*picked, i))))
                    current = table.get(new)
                    if current is None or candidate[0] > current[0] or (candidate[0] == current[0] and candidate[1] < current[1]):
                        table[new] = candidate
            top = max(table.items(), key=lambda kv: (kv[1][0], -kv[0], tuple(-n for n in kv[1][1])))
            chosen = [*top[1][1], len(ordered) - 1]
        segments, total = [], 0
        for i in chosen:
            scene = ordered[i]
            end = scene.start_ms + target if trimmed_last and i == len(ordered) - 1 else scene.end_ms
            segments.append(Segment(scene.id, scene.position, scene.start_ms, end, end != scene.end_ms, values[i][1]))
            total += end - scene.start_ms
        kept = set(chosen)
        dropped = [{"scene_id": s.id, "position": s.position, "summary": s.summary, "duration_ms": s.end_ms - s.start_ms} for i, s in enumerate(ordered) if i not in kept]
        out.append(Cutdown(target, total, segments, dropped, notes, True, sum(values[i][0] for i in chosen)))
    return out
