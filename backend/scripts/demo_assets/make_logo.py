# /// script
# requires-python = ">=3.12"
# dependencies = ["fonttools>=4.50", "uharfbuzz>=0.40", "pillow>=11"]
# ///
"""Draw the Aamod logo (fictional demo brand) as SVG and export PNGs.

    uv run --script backend/scripts/demo_assets/make_logo.py

The mark is a lit diya inside a teal disc: a marigold flame (festive light), a cream lamp bowl and three rangoli
dots. The wordmark "Aamod" is DM Serif Display (OFL) shaped with HarfBuzz and converted to outlines, so the SVGs need
no font. PNGs are rendered from the SVGs by a headless Chromium browser (Edge or Chrome) on a transparent background.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BRASS, CREAM, FIXTURES, MARIGOLD, TEAL, font_path, say  # noqa: E402

OUT = FIXTURES / "brand"
hexc = lambda rgb: "#%02X%02X%02X" % rgb  # noqa: E731

# 200 x 200 mark, drawn back to front.
MARK = f"""<circle cx="100" cy="100" r="98" fill="{hexc(TEAL)}"/>
<circle cx="100" cy="100" r="88" fill="none" stroke="{hexc(BRASS)}" stroke-width="3"/>
<path d="M100,38 C108,58 124,74 123,94 C122,110 112,119 100,119 C88,119 78,110 77,94 C76,74 92,58 100,38 Z" fill="{hexc(MARIGOLD)}"/>
<path d="M100,68 C105,81 112,90 111,100 C110,109 105,113 100,113 C95,113 90,109 89,100 C88,90 95,81 100,68 Z" fill="{hexc(CREAM)}"/>
<path d="M44,120 C70,131 130,131 156,120 C150,146 128,160 100,160 C72,160 50,146 44,120 Z" fill="{hexc(CREAM)}"/>
<path d="M44,120 C70,131 130,131 156,120" fill="none" stroke="{hexc(BRASS)}" stroke-width="3" stroke-linecap="round"/>
<circle cx="82" cy="173" r="4.5" fill="{hexc(BRASS)}"/><circle cx="100" cy="177" r="4.5" fill="{hexc(BRASS)}"/>
<circle cx="118" cy="173" r="4.5" fill="{hexc(BRASS)}"/>"""


def wordmark(text: str, size: float, x: float, baseline: float, fill: str) -> tuple[str, float]:
    """SVG paths for `text` set in DM Serif Display at `size` units, left edge `x`; returns (svg, advance width)."""
    import uharfbuzz as hb
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.ttLib import TTFont

    path = str(font_path("display"))
    tt = TTFont(path)
    glyphs, order, upem = tt.getGlyphSet(), tt.getGlyphOrder(), tt["head"].unitsPerEm
    font = hb.Font(hb.Face(hb.Blob.from_file_path(path)))
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True})
    scale, pen_x, parts = size / upem, 0, []
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        pen = SVGPathPen(glyphs)
        glyphs[order[info.codepoint]].draw(pen)
        tx, ty = x + (pen_x + pos.x_offset) * scale, baseline - pos.y_offset * scale
        parts.append(f'<path d="{pen.getCommands()}" transform="matrix({scale:.5f},0,0,{-scale:.5f},{tx:.2f},{ty:.2f})"/>')
        pen_x += pos.x_advance
    return f'<g fill="{fill}">{"".join(parts)}</g>', pen_x * scale


def svg(width: float, height: float, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" '
            f'height="{height:.0f}">\n<title>Aamod (fictional brand, Omnicult demo)</title>\n{body}\n</svg>\n')


def horizontal(word_fill: str) -> str:
    pad, size = 10, 158
    words, w = wordmark("Aamod", size, pad + 200 + 34, pad + 100 + 0.35 * size, word_fill)
    return svg(pad + 200 + 34 + w + pad, 200 + 2 * pad, f'<g transform="translate({pad},{pad})">{MARK}</g>\n{words}')


def stacked(word_fill: str) -> str:
    size = 118
    _, w = wordmark("Aamod", size, 0, 0, word_fill)
    width = max(200, w) + 20
    words, _ = wordmark("Aamod", size, (width - w) / 2, 200 + 22 + 0.7 * size, word_fill)
    return svg(width, 200 + 22 + 0.7 * size + 0.12 * size + 14, f'<g transform="translate({(width - 200) / 2:.2f},4)">{MARK}</g>\n{words}')


def browser() -> str:
    for candidate in (os.environ.get("CHROME_PATH"), r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                      r"C:\Program Files\Google\Chrome\Application\chrome.exe", shutil.which("chromium"),
                      shutil.which("google-chrome"), shutil.which("msedge")):
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit("No Chromium-based browser found for SVG export; set CHROME_PATH.")


def export_png(svg_text: str, out: Path, width: int) -> None:
    """Render the SVG at `width` px (height from its viewBox) on a transparent background."""
    import re

    from PIL import Image

    vw, vh = (float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg_text).groups())
    height = round(width * vh / vw)
    sized = re.sub(r'width="[\d.]+" height="[\d.]+"', f'width="{width}" height="{height}"', svg_text, count=1)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "logo.svg"
        src.write_text(sized, encoding="utf-8")
        subprocess.run([browser(), "--headless", "--disable-gpu", "--hide-scrollbars", "--default-background-color=00000000",
                        f"--window-size={width},{height}", f"--screenshot={out}", src.as_uri()],
                       check=True, capture_output=True, timeout=120)
    with Image.open(out) as im:
        assert im.size == (width, height) and im.mode == "RGBA", (im.size, im.mode)
        assert im.getpixel((0, 0))[3] == 0, "background is not transparent"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    teal, cream = hexc(TEAL), hexc(CREAM)
    files = {
        "logo_mark": (svg(200, 200, MARK), 1024),
        "logo": (horizontal(teal), 1600),  # on light backgrounds
        "logo_reversed": (horizontal(cream), 1600),  # on teal or dark photography
        "logo_stacked": (stacked(teal), 1000),  # pack medallion
    }
    for name, (text, width) in files.items():
        (OUT / f"{name}.svg").write_text(text, encoding="utf-8", newline="\n")
        export_png(text, OUT / f"{name}.png", width)
        say(f"wrote {name}.svg and {name}.png")


if __name__ == "__main__":
    main()
