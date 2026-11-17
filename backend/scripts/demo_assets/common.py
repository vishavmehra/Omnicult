"""Shared helpers for the Omnicult demo asset scripts: paths, fonts, Indic text rendering, spend ledger.

Imported by `make_logo.py`, `generate.py` and `render.py` (run them with `uv run --script <file>`; each declares its
own dependencies inline). Heavy imports (Pillow, fontTools, google-genai) stay inside functions so the pure parts here
(paths, ledger) can be imported by the backend test suite.

Text is never drawn by an image model. Every Marathi and English string is rendered here with Pillow's raqm layout
(HarfBuzz shaping + FriBiDi), which Devanagari needs for matra reordering, conjuncts and reph. Pillow wheels load
FriBiDi at runtime: Linux `apt install libfribidi0`; Windows: put `libfribidi-0.dll` on PATH (for example MSYS2
`pacman -S mingw-w64-ucrt-x86_64-fribidi`, then `C:\\msys64\\ucrt64\\bin` on PATH). `require_raqm()` refuses to
render without it rather than produce broken Marathi.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # repository root (demo_assets -> scripts -> backend -> root)
FIXTURES = ROOT / "backend" / "app" / "fixtures" / "omnicult_demo"
CACHE = Path(os.environ.get("OMNICULT_DEMO_CACHE", Path.home() / ".cache" / "omnicult-demo-assets"))


def _docs_dir() -> Path:
    env = os.environ.get("OMNICULT_DOCS_DIR")
    if env:
        return Path(env)
    for parent in ROOT.parents:  # the worktree lives under NativeProof\.wt\<name>, the docs beside the repo
        if (parent / "omnicult-docs").is_dir():
            return parent / "omnicult-docs"
    return CACHE


LOG = _docs_dir() / "DEMO_ASSETS_LOG.md"  # outside git: every paid call with its estimated cost
BUDGET_USD = 2.00

GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")  # Vertex AI project for the paid steps (generate.py)

# Brand palette (mirrors brand_kit.json).
TEAL = (14, 77, 88)
MARIGOLD = (242, 163, 58)
CREAM = (251, 241, 221)
KUMKUM = (184, 50, 58)
BRASS = (201, 154, 59)
JAGGERY = (59, 38, 24)

# OFL fonts, pinned by SHA-256 (downloaded once into the cache, never committed).
_FONT_BASE = "https://github.com/notofonts/notofonts.github.io/raw/main/fonts"
FONTS = {
    "display": ("DMSerifDisplay-Regular.ttf", "https://github.com/google/fonts/raw/main/ofl/dmserifdisplay/DMSerifDisplay-Regular.ttf",
                "8cc3643535edf039aa5d95440a8542735e9197e4f4b8d9303e980fefbf5ab616"),
    "deva_serif_bold": ("NotoSerifDevanagari-Bold.ttf", f"{_FONT_BASE}/NotoSerifDevanagari/hinted/ttf/NotoSerifDevanagari-Bold.ttf",
                        "0544878a7b09ea1dc16d9de1f7a1f8cf82beb255d66a287712bb05a24336bcc0"),
    "deva_sans_semibold": ("NotoSansDevanagari-SemiBold.ttf", f"{_FONT_BASE}/NotoSansDevanagari/hinted/ttf/NotoSansDevanagari-SemiBold.ttf",
                           "943a11e02d0d282bed619951ab4dc9a4912e9fceb00441bf4aacd54fa57b6e63"),
    "deva_sans": ("NotoSansDevanagari-Regular.ttf", f"{_FONT_BASE}/NotoSansDevanagari/hinted/ttf/NotoSansDevanagari-Regular.ttf",
                  "4e3c66638958c3e2ab5d37f47a8deb89fffeb7be9985c665a519bbc7ba762313"),
    "latin_sans_semibold": ("NotoSans-SemiBold.ttf", f"{_FONT_BASE}/NotoSans/hinted/ttf/NotoSans-SemiBold.ttf",
                            "a4e91fd530ac2b4ef5367240144ff37d7d65d66cf76f2e9a2187b93c676f92d0"),
    "latin_sans": ("NotoSans-Regular.ttf", f"{_FONT_BASE}/NotoSans/hinted/ttf/NotoSans-Regular.ttf",
                   "478c558ea716033cd60c03438f628dfa75694dcf6b5f6d505a2f05fd2b4f3823"),
}


def font_path(key: str) -> Path:
    name, url, sha = FONTS[key]
    path = CACHE / "fonts" / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - pinned https URL, hash checked below
            path.write_bytes(response.read())
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        path.unlink()
        raise SystemExit(f"Font {name} failed its SHA-256 check; deleted, rerun to download again.")
    return path


# ---------------------------------------------------------------------------------------------------------------
# Indic text rendering (Pillow + raqm). A style lists fonts in fallback order; text is split into runs per font.


def require_raqm() -> None:
    from PIL import features

    if not features.check("raqm"):
        raise SystemExit("Pillow has no raqm layout (FriBiDi not found). Devanagari would render wrongly; see the "
                         "module docstring of scripts/demo_assets/common.py to enable it.")


_FONT_CACHE: dict = {}
_CMAPS: dict[str, set[int]] = {}


def _font(key: str, size: int):
    from PIL import ImageFont

    if (key, size) not in _FONT_CACHE:
        _FONT_CACHE[key, size] = ImageFont.truetype(str(font_path(key)), size, layout_engine=ImageFont.Layout.RAQM)
    return _FONT_CACHE[key, size]


def _cmap(key: str) -> set[int]:
    if key not in _CMAPS:
        from fontTools.ttLib import TTFont

        _CMAPS[key] = set(TTFont(str(font_path(key))).getBestCmap())
    return _CMAPS[key]


def runs(text: str, fonts: tuple[str, ...]) -> list[tuple[str, str]]:
    """Split `text` into (substring, font key) runs: each character takes the first font that has it; spaces and
    punctuation shared by several fonts stay in the current run so words are not fragmented."""
    out: list[list] = []
    for ch in text:
        able = [k for k in fonts if ord(ch) in _cmap(k)] or [fonts[0]]
        key = out[-1][1] if out and out[-1][1] in able else able[0]
        if out and out[-1][1] == key:
            out[-1][0] += ch
        else:
            out.append([ch, key])
    return [(t, k) for t, k in out]


def line_width(text: str, fonts: tuple[str, ...], size: int, language: str = "mr") -> float:
    return sum(_font(k, size).getlength(t, language=language) for t, k in runs(text, fonts))


def draw_line(draw, x: float, baseline: float, text: str, fonts: tuple[str, ...], size: int, fill,
              align: str = "left", language: str = "mr") -> tuple[int, int, int, int]:
    """Draw one line on `draw` with its baseline at `baseline`; returns the pixel bbox (x0, y0, x1, y1)."""
    width = line_width(text, fonts, size, language)
    x0 = x - width / 2 if align == "center" else x - width if align == "right" else x
    pen, box = x0, [10**9, 10**9, -(10**9), -(10**9)]
    for part, key in runs(text, fonts):
        font = _font(key, size)
        b = draw.textbbox((pen, baseline), part, font=font, anchor="ls", language=language)
        box = [min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3])]
        draw.text((pen, baseline), part, font=font, fill=fill, anchor="ls", language=language)
        pen += font.getlength(part, language=language)
    return tuple(int(v) for v in box)


def wrap(text: str, fonts: tuple[str, ...], size: int, max_width: float, language: str = "mr") -> list[str]:
    """Greedy word wrap on spaces (Marathi separates words with spaces)."""
    lines: list[str] = []
    for word in text.split():
        trial = f"{lines[-1]} {word}" if lines else word
        if lines and line_width(trial, fonts, size, language) <= max_width:
            lines[-1] = trial
        else:
            lines.append(word)
    return lines


def text_layer(lines: list[str], fonts: tuple[str, ...], size: int, fill, *, align: str = "center",
               line_gap: float = 1.25, shadow: tuple | None = (0, 4, 10, (0, 0, 0, 170)), pad: int = 40,
               pill: tuple | None = None, language: str = "mr"):
    """Render lines into a tight RGBA layer. Returns (image, ink bbox inside the image).

    shadow: (dx, dy, blur radius, rgba) soft drop shadow; pill: (rgba, radius, pad_x, pad_y) rounded box behind."""
    from PIL import Image, ImageDraw, ImageFilter

    if pill:
        pad = max(pad, pill[2] + 4, pill[3] + 4)
    asc, desc = _font(fonts[0], size).getmetrics()
    step = int(size * line_gap)
    width = int(max(line_width(t, fonts, size, language) for t in lines)) + 2 * pad
    height = asc + desc + step * (len(lines) - 1) + 2 * pad
    ink = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ink)
    x = width / 2 if align == "center" else width - pad if align == "right" else pad
    boxes = [draw_line(draw, x, pad + asc + i * step, t, fonts, size, fill, align, language) for i, t in enumerate(lines)]
    bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    out = Image.new("RGBA", ink.size, (0, 0, 0, 0))
    if pill:
        rgba, radius, px, py = pill
        ImageDraw.Draw(out).rounded_rectangle((bbox[0] - px, bbox[1] - py, bbox[2] + px, bbox[3] + py), radius, fill=rgba)
    if shadow:
        dx, dy, blur, rgba = shadow
        shade = Image.new("RGBA", ink.size, rgba)
        shade.putalpha(ink.getchannel("A").point(lambda a: a * rgba[3] // 255))
        out.alpha_composite(shade.filter(ImageFilter.GaussianBlur(blur)), (dx, dy))
    out.alpha_composite(ink)
    return out, bbox


# ---------------------------------------------------------------------------------------------------------------
# Spend ledger: one Markdown table row per paid call in LOG (outside git). The budget guard sums its cost column.

_HEADER = """# Demo asset generation log

Every Vertex AI call made by `backend/scripts/demo_assets/generate.py` for the Omnicult demo brand (Aamod). Budget:
USD {budget:.2f} in total. Costs are estimates from the response token counts and the published per-unit prices in
`backend/app/llm/registry.py` (gateway branch, `prices-2026-11-17`); image output tokens are priced at USD 60 per 1M
(USD 0.067 per 1K image), Lyria at USD 0.06 per 30 s clip. They are not billed amounts: check the billing report.
Failed calls that returned an error before generation are logged at USD 0.

| # | UTC time | step | model | location | params | status | latency ms | tokens in/out | est. USD | running USD | output |
|---|---|---|---|---|---|---|---|---|---|---|---|
"""
_COST_COLUMN = 10  # index in row.split("|")


def spent(log: Path = LOG) -> float:
    if not log.exists():
        return 0.0
    total = 0.0
    for row in log.read_text(encoding="utf-8").splitlines():
        cells = row.split("|")
        if len(cells) > _COST_COLUMN and cells[1].strip().isdigit():
            total += float(cells[_COST_COLUMN])
    return total


def guard(estimate_usd: float, log: Path = LOG, budget: float = BUDGET_USD) -> None:
    """Refuse a call whose worst-case estimate would take the logged total over the budget."""
    used = spent(log)
    if used + estimate_usd > budget:
        raise SystemExit(f"Budget guard: {used:.4f} spent + {estimate_usd:.4f} estimated > {budget:.2f} USD. Stopping.")


def record(step: str, model: str, location: str, params: str, status: str, latency_ms: int, tokens: str,
           usd: float, output: str, log: Path = LOG) -> float:
    """Append one row to the log and return the new running total."""
    log.parent.mkdir(parents=True, exist_ok=True)
    if not log.exists():
        log.write_text(_HEADER.format(budget=BUDGET_USD), encoding="utf-8")
    text = log.read_text(encoding="utf-8")
    n = sum(1 for row in text.splitlines() if len(row.split("|")) > _COST_COLUMN and row.split("|")[1].strip().isdigit())
    total = spent(log) + usd
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    clean = lambda s: str(s).replace("|", "/").replace("\n", " ")[:160]  # noqa: E731
    row = (f"| {n + 1} | {stamp} | {clean(step)} | {model} | {location} | {clean(params)} | {clean(status)} | {latency_ms} "
           f"| {tokens} | {usd:.4f} | {total:.4f} | {clean(output)} |\n")
    with log.open("a", encoding="utf-8") as fh:
        fh.write(row)
    return total


class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        return self

    @property
    def ms(self) -> int:
        return int((time.perf_counter() - self.start) * 1000)

    def __exit__(self, *exc):
        return False


def say(*parts) -> None:
    print(*parts, file=sys.stderr, flush=True)
