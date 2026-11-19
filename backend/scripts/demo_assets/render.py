# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=11", "fonttools>=4.50"]
# ///
"""Free, deterministic compositing of the demo creative from the generated raw media (no model calls).

    uv run --script backend/scripts/demo_assets/render.py pack   # tin cut-out + logo -> brand/pack.png, pack_reference.png
    uv run --script backend/scripts/demo_assets/render.py all    # plates, key visual, video, audio stems, creative JSON

Reads the raw outputs of generate.py from the cache and writes the committed fixtures under
backend/app/fixtures/omnicult_demo/. All Marathi and English text is rendered here with Pillow + raqm and Noto fonts;
the logo and the product pack are composited from the brand files, never drawn by the image model. Needs ffmpeg.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import shutil
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec  # noqa: E402
from common import BRASS, CACHE, CREAM, FIXTURES, KUMKUM, MARIGOLD, require_raqm, say, text_layer, wrap  # noqa: E402

RAW = CACHE / "raw"
BRAND = FIXTURES / "brand"
OUT = FIXTURES / "creative" / "mh_original"
REL = lambda p: p.relative_to(FIXTURES).as_posix()  # noqa: E731 - paths in JSON are relative to the fixture root
W, H, FPS = 1080, 1920, 30
KW, KH = 1080, 1350
SERIF = ("deva_serif_bold", "display")  # Devanagari headline face, Latin falls back to DM Serif Display
SANS = ("deva_sans_semibold", "latin_sans_semibold")
SMALL = ("deva_sans", "latin_sans")
DISPLAY = ("display",)


def _img():
    from PIL import Image

    return Image


def cover(im, size):
    Image = _img()
    scale = max(size[0] / im.width, size[1] / im.height)
    rs = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    x, y = (rs.width - size[0]) // 2, (rs.height - size[1]) // 2
    return rs.crop((x, y, x + size[0], y + size[1]))


def norm_bbox(box, size) -> list[float]:
    x0, y0, x1, y1 = box
    return [round(x0 / size[0], 4), round(y0 / size[1], 4), round((x1 - x0) / size[0], 4), round((y1 - y0) / size[1], 4)]


def place(canvas, layer, x: float, y: float, anchor: str = "lt") -> tuple[int, int, int, int]:
    """Composite a text_layer() result so its ink box is anchored at (x, y); anchor: l/m/r + t/b. Returns ink box."""
    image, ink = layer
    iw, ih = ink[2] - ink[0], ink[3] - ink[1]
    left = x - (iw / 2 if anchor[0] == "m" else iw if anchor[0] == "r" else 0)
    top = y - (ih if anchor[1] == "b" else 0)
    ox, oy = int(round(left - ink[0])), int(round(top - ink[1]))
    if canvas is not None:
        canvas.alpha_composite(image, (max(ox, 0), max(oy, 0)), (max(-ox, 0), max(-oy, 0)))
    return (ox + ink[0], oy + ink[1], ox + ink[2], oy + ink[3])


def logo(name: str, width: int):
    Image = _img()
    im = Image.open(BRAND / name).convert("RGBA")
    return im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)


# ---------------------------------------------------------------------------------------------------------------
# Pack: cut the generated tin out of its white background, clean the blank medallion and put the logo on it.


def find_medallion(tin) -> tuple[int, int, int, int]:
    """Bounding box of the cream label: flood-fill the light, warm region found in the middle of the tin's body
    (the lid top is also cream-coloured, so a plain colour threshold would merge them)."""
    from PIL import ImageChops, ImageDraw

    rgb, (w, h) = tin.convert("RGB"), tin.size
    px = rgb.load()
    hits = [(x, y) for y in range(int(h * 0.45), int(h * 0.75), 4) for x in range(int(w * 0.35), int(w * 0.65), 4)
            if (lambda r, g, b: r > 215 and g > 205 and b > 160 and 12 < r - b < 75)(*px[x, y])]
    assert hits, "no cream label found in the middle of the tin"
    seed = (sorted(p[0] for p in hits)[len(hits) // 2], sorted(p[1] for p in hits)[len(hits) // 2])
    ImageDraw.floodfill(rgb, seed, (255, 0, 255), thresh=40)
    r, g, b = rgb.split()
    filled = ImageChops.multiply(ImageChops.multiply(r.point(lambda v: 255 * (v == 255)), g.point(lambda v: 255 * (v == 0))),
                                 b.point(lambda v: 255 * (v == 255)))
    box = filled.getbbox()
    bw, bh = box[2] - box[0], box[3] - box[1]
    area = sum(filled.histogram()[255:])
    assert area > 0.6 * math.pi * bw * bh / 4 and abs(bw - bh) < 0.2 * max(bw, bh), f"medallion not found cleanly: {box}"
    return box


def pack() -> None:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    src = Image.open(RAW / "pack_raw.png").convert("RGB")
    w, h = src.size
    work, key = src.copy(), (255, 0, 255)
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 1), (w // 2, h - 2), (1, h // 2), (w - 2, h // 2)):
        if work.getpixel(seed) != key:
            ImageDraw.floodfill(work, seed, key, thresh=70)  # 70 also clears the faint grey contact shadow at the base
    r, g, b = work.split()
    bg = ImageChops.multiply(ImageChops.multiply(r.point(lambda v: 255 * (v == 255)), g.point(lambda v: 255 * (v == 0))),
                             b.point(lambda v: 255 * (v == 255)))
    tin = src.convert("RGBA")
    tin.putalpha(ImageChops.invert(bg).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1)))
    box = find_medallion(tin)
    (x0, y0, x1, y1), rx = box, (box[2] - box[0]) / 2

    def labelled(logo_file: str, scale: float):
        im = tin.copy()
        crop = im.crop(box)
        clean = crop.filter(ImageFilter.GaussianBlur(rx / 5))  # keeps the light fall-off, removes any stray marks
        mask = Image.new("L", crop.size, 0)
        ImageDraw.Draw(mask).ellipse((3, 3, crop.width - 4, crop.height - 4), fill=255)
        im.paste(clean, box[:2], mask.filter(ImageFilter.GaussianBlur(1)))
        mark = Image.open(BRAND / logo_file).convert("RGBA")
        lw = int(2 * rx * scale)
        lh = int(mark.height * lw / mark.width * (y1 - y0) / (x1 - x0))
        mark = mark.resize((lw, lh), Image.LANCZOS)
        im.alpha_composite(mark, (int((x0 + x1) / 2 - lw / 2), int((y0 + y1) / 2 - lh / 2)))
        return im

    branded = labelled("logo_stacked.png", 0.68)
    left, top, right, bottom = branded.getchannel("A").getbbox()
    margin = 12
    crop = (max(left - margin, 0), max(top - margin, 0), min(right + margin, w), min(bottom + margin, h))
    branded.crop(crop).save(BRAND / "pack.png", optimize=True)
    reference = Image.new("RGB", (w, h), (255, 255, 255))
    reference.paste(labelled("logo_mark.png", 0.72), (0, 0), tin.getchannel("A"))
    reference.save(BRAND / "pack_reference.png", optimize=True)
    pw, ph = crop[2] - crop[0], crop[3] - crop[1]
    medallion = norm_bbox((x0 - crop[0], y0 - crop[1], x1 - crop[0], y1 - crop[1]), (pw, ph))
    say(f"pack.png {pw}x{ph}; medallion bbox in pack.png (normalised x,y,w,h): {medallion}")
    (CACHE / "pack_regions.json").write_text(json.dumps({"size": [pw, ph], "medallion": medallion}), encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------
# Key visual (4:5 feed post).


def gradient(size, top_rgba, stop: float, bottom_rgba=None, start: float = 1.0, full: float = 1.0):
    """Vertical scrim: top_rgba fading to transparent at `stop` (fraction of height); optional bottom scrim rising
    from transparent at `start` to bottom_rgba at `full`."""
    Image = _img()
    w, h = size
    column = Image.new("RGBA", (1, h))
    for y in range(h):
        f = y / h
        a_top = max(0.0, 1 - f / stop) ** 1.6 if stop else 0
        a_bot = min(1.0, max(0.0, (f - start) / (full - start))) ** 1.2 if bottom_rgba and start < 1 else 0
        if a_bot > a_top:
            column.putpixel((0, y), (*bottom_rgba[:3], int(bottom_rgba[3] * a_bot)))
        else:
            column.putpixel((0, y), (*top_rgba[:3], int(top_rgba[3] * a_top)))
    return column.resize((w, h))


def packshot(height: int, canvas_size, x_center: float, bottom: float):
    """Branded pack scaled to `height` with a soft contact shadow; returns (layer, pack box)."""
    from PIL import Image, ImageDraw, ImageFilter

    pk = Image.open(BRAND / "pack.png").convert("RGBA")
    pk = pk.resize((round(pk.width * height / pk.height), height), Image.LANCZOS)
    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    x, y = int(x_center - pk.width / 2), int(bottom - pk.height)
    shadow = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((x + pk.width * 0.06, bottom - pk.height * 0.07, x + pk.width * 0.94, bottom + pk.height * 0.05),
                                   fill=(0, 0, 0, 150))
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(height / 22)))
    layer.alpha_composite(pk, (x, y))
    return layer, (x, y, x + pk.width, y + pk.height)


def keyvisual() -> list[dict]:
    from PIL import Image

    plate = Image.open(OUT / "keyvisual_plate.jpg").convert("RGBA")
    plate.alpha_composite(gradient((KW, KH), (6, 30, 34, 230), 0.34, (6, 24, 28, 246), 0.70, 0.86))
    els: list[dict] = []

    def add(eid, kind, value, box, lang="mr", script="Deva", locked=False):
        els.append({"id": eid, "kind": kind, "value": value, "language": lang, "script": script,
                    "bbox": norm_bbox(box, (KW, KH)) if box else None, "scene_id": None, "locked": locked})

    # Layout fitted to the plate: dark wall top-left (logo, headline), lantern top-right, food on the left, empty
    # tabletop lower-right (pack), information panel along the bottom.
    lg = logo("logo_reversed.png", 236)
    plate.alpha_composite(lg, (56, 36))
    add("mh-kv-logo", "logo", REL(BRAND / "logo_reversed.svg"), (56, 36, 56 + lg.width, 36 + lg.height), None, None, True)
    head = place(plate, text_layer(["दिवाळी म्हणजे", "फराळ!"], SERIF, 86, CREAM, align="left", line_gap=1.16,
                                   shadow=(0, 4, 14, (0, 0, 0, 220))), 56, 36 + lg.height + 24)
    add("mh-kv-headline", "headline", spec.KV_HEADLINE[0], head)
    pack_h = 400
    with Image.open(BRAND / "pack.png") as pk:
        pack_w = pk.width * pack_h / pk.height
    layer, box = packshot(pack_h, (KW, KH), KW - 40 - pack_w / 2, 1098)
    plate.alpha_composite(layer)
    add("mh-kv-packshot", "packshot", REL(BRAND / "pack.png"), box, None, None, True)
    sub = place(plate, text_layer([spec.KV_SUB[0]], SANS, 34, MARIGOLD, align="left", shadow=(0, 2, 8, (0, 0, 0, 230))),
                56, 1052)
    add("mh-kv-sub", "body", spec.KV_SUB[0], sub)
    name = place(plate, text_layer([spec.PRODUCT[0]], DISPLAY, 42, CREAM, align="left", language="en"), 56, sub[3] + 24)
    add("mh-kv-product-name", "body", spec.PRODUCT[0], name, "en", "Latn")
    hook = place(plate, text_layer([spec.CTA_HOOK[0]], SANS, 38, CREAM, align="left"), 56, name[3] + 22)
    add("mh-kv-cta-hook", "cta", spec.CTA_HOOK[0], hook)
    button = place(plate, text_layer([spec.CTA_BUTTON[0]], SANS, 30, CREAM, align="left", shadow=None,
                                     pill=(KUMKUM + (255,), 30, 26, 14)), 82, hook[3] + 34)
    add("mh-kv-cta-button", "cta", spec.CTA_BUTTON[0], (button[0] - 26, button[1] - 14, button[2] + 26, button[3] + 14))
    tag = place(plate, text_layer([spec.TAGLINE[0]], DISPLAY, 36, MARIGOLD, align="right", language="en"),
                KW - 56, (button[1] + button[3]) / 2 + 2, "rb")
    add("mh-kv-tagline", "tagline", spec.TAGLINE[0], tag, "en", "Latn", True)
    small = place(plate, text_layer([spec.SMALL_PRINT[0]], SMALL, 19, CREAM + (225,), align="left", shadow=None), 56, KH - 34, "lb")
    add("mh-kv-small-print", "body", spec.SMALL_PRINT[0], small)
    demo = place(plate, text_layer([spec.DEMO_LABEL[0]], ("latin_sans",), 15, CREAM + (165,), align="right", shadow=None,
                                   language="en"), KW - 56, KH - 34, "rb")
    add("mh-kv-demo-label", "body", spec.DEMO_LABEL[0], demo, "en", "Latn")
    plate.convert("RGB").save(OUT / "keyvisual.png", optimize=True)
    els.insert(0, {"id": "mh-kv-plate", "kind": "scene", "value": REL(OUT / "keyvisual_plate.jpg"), "language": None,
                   "script": None, "bbox": [0, 0, 1, 1], "scene_id": None, "locked": False})
    return els


# ---------------------------------------------------------------------------------------------------------------
# Audio: voice-over lines on a timeline, music bed, mix with ducking.


def read_wav(path: Path) -> tuple[array.array, int]:
    with wave.open(str(path)) as wav:
        assert wav.getsampwidth() == 2 and wav.getnchannels() == 1
        return array.array("h", wav.readframes(wav.getnframes())), wav.getframerate()


def trim(samples: array.array, rate: int, level: int = 600) -> array.array:
    loud = [i for i in range(0, len(samples), 32) if abs(samples[i]) > level]
    if not loud:
        return samples
    return samples[max(loud[0] - int(0.05 * rate), 0): min(loud[-1] + int(0.12 * rate), len(samples))]


def timeline() -> tuple[list[dict], dict[str, dict], dict[str, array.array], int]:
    """Scene windows and line start times from the trimmed voice-over durations (seconds)."""
    lines, rate = {}, 24000
    for line in spec.VO_LINES:
        samples, rate = read_wav(RAW / f"{line['id']}.wav")
        lines[line["id"]] = trim(samples, rate)
    dur = {k: len(v) / rate for k, v in lines.items()}
    scenes, at, t = [], {}, 0.0
    for i, scene in enumerate(spec.SCENES):
        line = next(l for l in spec.VO_LINES if l["scene"] == scene["id"])
        start = t
        at[line["id"]] = start + (0.5 if i == 0 else 0.35)
        t = max(at[line["id"]] + dur[line["id"]] + 0.45, start + 3.6)
        scenes.append({"id": scene["id"], "start": start, "end": t})
    end_lines = [l for l in spec.VO_LINES if l["scene"] == "mh-s5"]
    start, cursor = t, t + 0.55
    for line in end_lines:
        at[line["id"]] = cursor
        cursor += dur[line["id"]] + 0.45
    scenes.append({"id": "mh-s5", "start": start, "end": cursor - 0.45 + 1.3})
    timing = {k: {"start": at[k], "end": at[k] + dur[k]} for k in at}
    return scenes, timing, lines, rate


def write_voiceover(lines, timing, rate: int, total: float) -> Path:
    track = array.array("h", bytes(2 * int(total * rate)))
    for key, samples in lines.items():
        start = int(timing[key]["start"] * rate)
        track[start:start + len(samples)] = samples
    out = OUT / "voiceover_mr.wav"
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(1), wav.setsampwidth(2), wav.setframerate(rate), wav.writeframes(track.tobytes())
    return out


def write_music(total: float) -> Path | None:
    src = RAW / "music.wav"
    if not src.exists():
        say("no music.wav (Lyria failed or skipped): the video gets voice-over only")
        return None
    out = OUT / "music_bed.wav"
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(src), "-t", f"{total:.3f}", "-af",
                    f"afade=t=in:d=0.4,afade=t=out:st={total - 1.8:.3f}:d=1.8", "-ar", "32000", "-ac", "2", str(out)], check=True)
    return out


def ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise SystemExit("ffmpeg not found on PATH")
    return path


# ---------------------------------------------------------------------------------------------------------------
# Video: Ken Burns on the scene plates, kinetic Marathi text, captions, code-drawn end card; piped to ffmpeg.

PANS = {"mh-s1": (0.0, -0.6), "mh-s2": (0.5, 0.0), "mh-s3": (0.0, 0.3), "mh-s4": (-0.5, 0.0)}  # pan direction


def ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def fade(layer, alpha: float):
    if alpha >= 0.999:
        return layer
    out = layer.copy()
    out.putalpha(layer.getchannel("A").point(lambda a: int(a * alpha)))
    return out


def end_card_background():
    from PIL import Image, ImageDraw

    mask = Image.radial_gradient("L").resize((2400, 2400)).crop((1200 - W // 2, 1200 - 820, 1200 + W // 2, 1200 - 820 + H))
    bg = Image.composite(Image.new("RGB", (W, H), (7, 40, 46)), Image.new("RGB", (W, H), (22, 96, 108)), mask).convert("RGBA")
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(halo)
    for radius, count, dot in ((330, 72, 5), (372, 84, 4), (414, 96, 3)):  # rangoli-like dotted rings behind the pack
        for i in range(count):
            a = 2 * math.pi * i / count
            cx, cy = W / 2 + radius * math.cos(a), 830 + radius * math.sin(a)
            draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=BRASS + (70,))
    bg.alpha_composite(halo)
    return bg


def video() -> dict:
    from PIL import Image

    scenes, timing, lines, rate = timeline()
    total = scenes[-1]["end"]
    vo_path, music_path = write_voiceover(lines, timing, rate, total), write_music(total)
    els: list[dict] = []

    def add(eid, kind, value, box, scene_id, lang="mr", script="Deva", locked=False):
        els.append({"id": eid, "kind": kind, "value": value, "language": lang, "script": script,
                    "bbox": norm_bbox(box, (W, H)) if box else None, "scene_id": scene_id, "locked": locked})

    scrim = gradient((W, 760), (0, 0, 0, 170), 1.0)
    bug = logo("logo_reversed.png", 232)
    bug_xy = (54, 232)
    add("mh-vid-logo", "logo", REL(BRAND / "logo_reversed.svg"), (*bug_xy, bug_xy[0] + bug.width, bug_xy[1] + bug.height),
        None, None, None, True)
    photo = {}
    for scene in spec.SCENES:
        sid = scene["id"]
        big = cover(Image.open(RAW / f"{sid}.png").convert("RGB"), (round(W * 1.1), round(H * 1.1)))
        ost = text_layer(scene["ost"], SERIF, 94, CREAM, shadow=(0, 4, 16, (0, 0, 0, 210)))
        ost_box = place(None, ost, W / 2, scene.get("ost_y", 372), "mt")
        add(f"{sid}-headline".replace("mh-", "mh-vid-"), "headline", " ".join(scene["ost"]), ost_box, sid)
        label = None
        if scene.get("label"):
            label = text_layer([scene["label"]], DISPLAY, 54, MARIGOLD, shadow=(0, 3, 10, (0, 0, 0, 200)), language="en")
            add(f"{sid}-product-label".replace("mh-", "mh-vid-"), "body", scene["label"],
                place(None, label, W / 2, ost_box[3] + 26, "mt"), sid, "en", "Latn")
        add(f"{sid}-scene".replace("mh-", "mh-vid-"), "scene", REL(OUT / "scenes" / f"{sid}_{scene['name']}.jpg"), [0, 0, W, H], sid,
            None, None)
        for region in scene.get("regions", []):  # hand-calibrated on the plate; the Ken Burns move shifts them by < 6 %
            els.append({"id": f"{sid}-{region['id']}".replace("mh-", "mh-vid-"), "kind": region["kind"], "value": region["value"],
                        "language": None, "script": None, "bbox": region["bbox"], "scene_id": sid, "locked": region["locked"]})
        photo[sid] = {"big": big, "ost": ost, "ost_box": ost_box, "label": label}
    captions = {}
    for line in spec.VO_LINES:
        if line["scene"] == "mh-s5":
            continue  # the end card shows the CTA and tagline as on-screen text instead of captions
        layer = text_layer(wrap(line["text"], SANS, 46, 880), SANS, 46, CREAM, shadow=None, line_gap=1.3,
                           pill=((18, 14, 10, 170), 22, 28, 16))
        scene = next(s for s in spec.SCENES if s["id"] == line["scene"])
        box = place(None, layer, W / 2, scene.get("caption_y", 1300), "mt")
        captions[line["id"]] = (layer, box)
        add(line["id"].replace("mh-vo", "mh-vid-cap"), "caption", line["text"], (box[0] - 28, box[1] - 16, box[2] + 28, box[3] + 16),
            line["scene"])

    # End card layers (static positions, animated alpha / scale).
    bg = end_card_background()
    card = []  # (appear_at seconds after the card starts, layer image, xy)

    def card_text(eid, kind, text, fonts, size, color, y, lang="mr", script="Deva", delay=0.0, locked=False, **kw):
        layer = text_layer([text], fonts, size, color, language=lang, **kw)
        box = place(None, layer, W / 2, y, "mt")
        card.append((delay, layer, box))
        pill = kw.get("pill")
        bbox = (box[0] - pill[2], box[1] - pill[3], box[2] + pill[2], box[3] + pill[3]) if pill else box
        add(eid, kind, text, bbox, "mh-s5", lang, script, locked)
        return bbox

    greet = card_text("mh-vid-greeting", "headline", spec.GREETING[0], SERIF, 64, MARIGOLD, 300, delay=0.0)
    big_logo = logo("logo_reversed.png", 540)
    logo_xy = (int(W / 2 - big_logo.width / 2), greet[3] + 44)
    add("mh-vid-endcard-logo", "logo", REL(BRAND / "logo_reversed.svg"),
        (*logo_xy, logo_xy[0] + big_logo.width, logo_xy[1] + big_logo.height), "mh-s5", None, None, True)
    pack_layer, pack_box = packshot(520, (W, H), W / 2, 1130)
    add("mh-vid-packshot", "packshot", REL(BRAND / "pack.png"), pack_box, "mh-s5", None, None, True)
    name = card_text("mh-vid-product-name", "body", spec.PRODUCT[0], DISPLAY, 58, CREAM, 1168, "en", "Latn", 0.6)
    hook = card_text("mh-vid-cta-hook", "cta", spec.CTA_HOOK[0], SANS, 54, CREAM, name[3] + 34, delay=0.8)
    button = card_text("mh-vid-cta-button", "cta", spec.CTA_BUTTON[0], SANS, 42, CREAM, hook[3] + 44, delay=1.0, shadow=None,
                       pill=(KUMKUM + (255,), 40, 36, 20))
    tag = card_text("mh-vid-tagline", "tagline", spec.TAGLINE[0], DISPLAY, 46, MARIGOLD, button[3] + 40, "en", "Latn", 1.3, True)
    small = card_text("mh-vid-small-print", "body", spec.SMALL_PRINT[0], SMALL, 26, CREAM + (225,), tag[3] + 26, delay=1.5,
                      shadow=None)
    card_text("mh-vid-demo-label", "body", spec.DEMO_LABEL[0], ("latin_sans",), 21, CREAM + (165,), small[3] + 14, "en", "Latn",
              1.5, shadow=None)

    def photo_frame(sid: str, t: float):
        s = next(x for x in scenes if x["id"] == sid)
        p = min(max((t - s["start"]) / (s["end"] - s["start"]), 0.0), 1.1)  # crossfades sample just outside the scene
        big, zoom = photo[sid]["big"], 1.0 + 0.06 * p
        cw, ch = big.width / zoom, big.height / zoom
        px, py = PANS[sid]
        cx, cy = big.width / 2 + px * (big.width - cw) / 2, big.height / 2 + py * (big.height - ch) / 2
        frame = big.resize((W, H), Image.BILINEAR, box=(cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)).convert("RGBA")
        frame.alpha_composite(scrim)
        frame.alpha_composite(bug, bug_xy)
        k = ease((t - s["start"] - 0.2) / 0.45)
        if k > 0:
            ost, box = photo[sid]["ost"], photo[sid]["ost_box"]
            place(frame, (fade(ost[0], k), ost[1]), W / 2, box[1] + 26 * (1 - k), "mt")
            if photo[sid]["label"]:
                lk = ease((t - s["start"] - 0.6) / 0.45)
                if lk > 0:
                    place(frame, (fade(photo[sid]["label"][0], lk), photo[sid]["label"][1]), W / 2, box[3] + 26, "mt")
        for key, (layer, box) in captions.items():
            if next(l for l in spec.VO_LINES if l["id"] == key)["scene"] != sid:
                continue
            a = min(ease((t - timing[key]["start"] + 0.08) / 0.12), ease((timing[key]["end"] + 0.2 - t) / 0.12))
            if a > 0:
                place(frame, (fade(layer[0], a), layer[1]), W / 2, box[1], "mt")
        return frame

    def card_frame(t: float):
        s = scenes[-1]
        local = t - s["start"]
        frame = bg.copy()
        for delay, layer, box in card:
            a = ease((local - delay) / 0.4)
            if a > 0:
                place(frame, (fade(layer[0], a), layer[1]), (box[0] + box[2]) / 2, box[1] + 18 * (1 - a), "mt")
        a = ease((local - 0.15) / 0.4)
        if a > 0:
            frame.alpha_composite(fade(big_logo, a), logo_xy)
        k = ease((local - 0.25) / 0.6)
        if k >= 0.999:
            frame.alpha_composite(pack_layer)
        elif k > 0:
            scale = 0.9 + 0.1 * k
            shrunk = pack_layer.resize((round(W * scale), round(H * scale)), Image.BILINEAR)
            ox, oy = int((pack_box[0] + pack_box[2]) / 2 * (1 - scale)), int(pack_box[3] * (1 - scale))
            canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            canvas.alpha_composite(shrunk, (max(ox, 0), max(oy, 0)), (max(-ox, 0), max(-oy, 0)))
            frame.alpha_composite(fade(canvas, k))
        return frame

    def frame_at(t: float):
        xf = 0.4
        for i in range(len(scenes) - 1):
            boundary = scenes[i]["end"]
            if abs(t - boundary) < xf / 2:
                a, b = scene_frame(scenes[i]["id"], t), scene_frame(scenes[i + 1]["id"], t)
                return Image.blend(a, b, ease((t - boundary + xf / 2) / xf))
        current = next(s for s in scenes if t < s["end"]) if t < total else scenes[-1]
        return scene_frame(current["id"], t)

    def scene_frame(sid: str, t: float):
        return card_frame(t) if sid == "mh-s5" else photo_frame(sid, t)

    out = OUT / "video.mp4"
    frames = int(round(total * FPS))
    audio_inputs = ["-i", str(vo_path)] + (["-i", str(music_path)] if music_path else [])
    if music_path:
        graph = ("[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0,asplit=2[vo][key];"
                 "[2:a]aresample=48000,volume=-11dB[bed];[bed][key]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=400[duck];"
                 "[duck][vo]amix=inputs=2:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]")
    else:
        graph = "[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]"
    cmd = [ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           *audio_inputs, "-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "slow", "-crf", "21",
           "-maxrate", "2600k", "-bufsize", "5200k", "-pix_fmt", "yuv420p", "-g", "60", "-c:a", "aac", "-b:a", "128k",
           "-t", f"{frames / FPS:.3f}", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for n in range(frames):
        proc.stdin.write(frame_at(n / FPS).convert("RGB").tobytes())
        if n % 150 == 0:
            say(f"frame {n}/{frames}")
            if n == 450:
                frame_at(n / FPS).convert("RGB").save(CACHE / "preview_450.jpg")
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed")
    for t, name in ((2.6, "s1"), (scenes[1]["start"] + 2.4, "s2"), (scenes[2]["start"] + 2.4, "s3"), (scenes[3]["start"] + 2.4, "s4"),
                    (total - 0.5, "s5")):
        frame_at(t).convert("RGB").save(CACHE / f"check_{name}.jpg", quality=85)
    write_srt(timing)
    return {"scenes": scenes, "timing": timing, "elements": els, "total": total, "vo": vo_path, "music": music_path}


def ms(seconds: float) -> int:
    return int(round(seconds * 1000))


def write_srt(timing) -> None:
    stamp = lambda s: f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{int(s % 60):02d},{int(round(s % 1 * 1000)) % 1000:03d}"  # noqa: E731
    blocks = [f"{i}\n{stamp(timing[l['id']]['start'])} --> {stamp(timing[l['id']]['end'] + 0.2)}\n{l['text']}\n"
              for i, l in enumerate(spec.VO_LINES, 1)]
    (OUT / "captions_mr.srt").write_text("\n".join(blocks), encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------------------------------------------


def plates() -> None:
    from PIL import Image

    (OUT / "scenes").mkdir(parents=True, exist_ok=True)
    for scene in spec.SCENES:
        cover(Image.open(RAW / f"{scene['id']}.png").convert("RGB"), (W, H)).save(
            OUT / "scenes" / f"{scene['id']}_{scene['name']}.jpg", quality=90, optimize=True, progressive=True)
    cover(Image.open(RAW / "kv.png").convert("RGB"), (KW, KH)).save(OUT / "keyvisual_plate.jpg", quality=92, optimize=True,
                                                                     progressive=True)


def asset(path: Path, **extra) -> dict:
    data = path.read_bytes()
    return {"path": REL(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), **extra}


def probe(path: Path) -> dict:
    out = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=codec_name,width,height,r_frame_rate,sample_rate,channels", "-of", "json",
                          str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def write_json(kv_elements: list[dict], v: dict) -> None:
    info = probe(OUT / "video.mp4")
    duration_ms = ms(float(info["format"]["duration"]))
    scenes = []
    for s in v["scenes"]:
        src = next((x for x in spec.SCENES if x["id"] == s["id"]), None)
        scenes.append({
            "id": s["id"], "start_ms": ms(s["start"]), "end_ms": min(ms(s["end"]), duration_ms),
            "description": src["description"] if src else "Code-rendered end card: greeting, logo, Aamod Festive Tin packshot, "
                                                             "CTA, tagline and small print.",
            "plate": REL(OUT / "scenes" / f"{s['id']}_{src['name']}.jpg") if src else None,
            "on_screen_text_en": src["ost_en"] if src else None,
            "image_model": spec.IMAGE_MODEL if src else None,
            "image_prompt": src["prompt"] if src else None,
        })
    transcript = [{"id": l["id"], "start_ms": ms(v["timing"][l["id"]]["start"]), "end_ms": ms(v["timing"][l["id"]]["end"]),
                   "scene_id": l["scene"], "text": l["text"], "language": "mr", "script": "Deva",
                   "translation_en": l["en"], "burned_caption": l["scene"] != "mh-s5"} for l in spec.VO_LINES]
    vo_meta = {"path": REL(v["vo"]), "transcript_ids": [l["id"] for l in spec.VO_LINES], "model": spec.TTS_MODEL,
               "voice": spec.VOICE, "language_code": "mr-IN"}
    v["elements"].append({"id": "mh-vid-voiceover", "kind": "voiceover", "value": vo_meta, "language": "mr", "script": "Deva",
                          "bbox": None, "scene_id": None, "locked": False})
    if v["music"]:
        v["elements"].append({"id": "mh-vid-music", "kind": "music", "value": {"path": REL(v["music"]), "model": spec.MUSIC_MODEL,
                              "prompt": spec.MUSIC_PROMPT}, "language": None, "script": None, "bbox": None, "scene_id": None,
                              "locked": False})
    video_stream = next(s for s in info["streams"] if s["codec_name"] == "h264")
    doc = {
        "fixture": {"id": "omnicult-demo-creative-mh-original", "version": 1, "kind": "demo_fixture",
                    "label": "Original creative of the fictional brand Aamod; imagery and voice are AI-generated, "
                             "all text is rendered in code."},
        "brand_id": "demo-brand-aamod", "campaign_id": "demo-campaign-aamod-diwali-2027",
        "region_code": "IN-MH", "languages": ["mr", "en"], "scripts": ["Deva", "Latn"],
        "creatives": [
            {"id": "demo-creative-aamod-mh-video", "format": "vertical_video", "channel_fit": ["instagram_reels", "youtube_shorts"],
             "asset": asset(OUT / "video.mp4", mime_type="video/mp4", width=video_stream["width"], height=video_stream["height"],
                            fps=FPS, duration_ms=duration_ms),
             "scenes": scenes, "transcript": transcript,
             "captions": asset(OUT / "captions_mr.srt", mime_type="application/x-subrip"),
             "elements": v["elements"]},
            {"id": "demo-creative-aamod-mh-key-visual", "format": "feed_image", "channel_fit": ["meta_feed"],
             "asset": asset(OUT / "keyvisual.png", mime_type="image/png", width=KW, height=KH),
             "plate": asset(OUT / "keyvisual_plate.jpg", mime_type="image/jpeg", width=KW, height=KH,
                            image_model=spec.IMAGE_MODEL, image_prompt=spec.KV_PROMPT),
             "elements": kv_elements},
        ],
        "stems": {"voiceover": asset(v["vo"], mime_type="audio/wav"),
                  "music": asset(v["music"], mime_type="audio/wav") if v["music"] else None},
        "authoring_notes": {
            "label": "Author's intent, for demo QA only. Not evidence, not model output; never show these as findings.",
            "adaptation_hooks": spec.ADAPTATION_HOOKS, "deliberate_risks": spec.DELIBERATE_RISKS,
        },
        "provenance": {
            "prompt_version": spec.PROMPT_VERSION, "image_model": spec.IMAGE_MODEL, "image_location": "global",
            "tts_model": spec.TTS_MODEL, "music_model": spec.MUSIC_MODEL if v["music"] else None,
            "pack_reference": REL(BRAND / "pack_reference.png"),
            "text_rendering": "Pillow with raqm (HarfBuzz) layout; Noto Serif Devanagari, Noto Sans Devanagari, Noto Sans, "
                              "DM Serif Display (all OFL). No text was drawn by the image model.",
            "scripts": "backend/scripts/demo_assets/ (generate.py for model calls, render.py for compositing)",
            "spend_log": "kept outside the repository (omnicult-docs/DEMO_ASSETS_LOG.md)",
        },
    }
    path = FIXTURES / "creative_mh_original.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    say(f"wrote {path.name}: video {duration_ms} ms, {(OUT / 'video.mp4').stat().st_size / 1e6:.2f} MB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["pack", "kv", "all"], help="kv: plates and key visual only (layout check)")
    args = parser.parse_args()
    require_raqm()
    if args.step == "pack":
        return pack()
    plates()
    kv_elements = keyvisual()
    if args.step == "kv":
        return
    write_json(kv_elements, video())


if __name__ == "__main__":
    main()
