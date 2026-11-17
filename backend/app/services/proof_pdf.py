"""PDF export of a Proof Report with reportlab (pure Python; the same wheel installs on Windows and in the Linux image).

The PDF uses the standard Helvetica font, so it needs no font files and renders the same everywhere. reportlab places
glyphs one by one and cannot shape Indic scripts (conjuncts, vowel signs that move), so Devanagari, Bengali, Tamil,
Malayalam and the other Indic scripts are never drawn as glyphs: they are replaced by an approximate Latin
transliteration and the PDF says so (also returned as a notice). The original text stays exact in the JSON and Markdown
exports. # ponytail: upgrade path is Pillow with libraqm (the container ships libraqm and Noto) drawing each Indic run
as an image; add it when the PDF must show native script. Output is deterministic (`invariant`), so equal reports give equal bytes.
"""

import io
import unicodedata
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.schemas.proof import ProofReport
from app.services.proof_render import NOT_LEGAL, Block

INDIC_BLOCKS = (
    (0x0900, 0x097F, "Devanagari"), (0x0980, 0x09FF, "Bengali"), (0x0A00, 0x0A7F, "Gurmukhi"),
    (0x0A80, 0x0AFF, "Gujarati"), (0x0B00, 0x0B7F, "Odia"), (0x0B80, 0x0BFF, "Tamil"), (0x0C00, 0x0C7F, "Telugu"),
    (0x0C80, 0x0CFF, "Kannada"), (0x0D00, 0x0D7F, "Malayalam"),
)
VOWELS = {
    "A": "a", "AA": "aa", "I": "i", "II": "ii", "U": "u", "UU": "uu", "VOCALIC R": "ri", "VOCALIC RR": "rii",
    "VOCALIC L": "li", "VOCALIC LL": "lii", "E": "e", "EE": "ee", "AI": "ai", "O": "o", "OO": "oo", "AU": "au",
    "SHORT E": "e", "SHORT O": "o", "SHORT A": "a", "CANDRA E": "e", "CANDRA O": "o", "CANDRA A": "a", "AW": "aw",
}
SIGNS = {"VOCALIC R": "ri", "VOCALIC RR": "rii", "VOCALIC L": "li", "VOCALIC LL": "lii", "CANDRA E": "e",
         "CANDRA O": "o", "SHORT E": "e", "SHORT O": "o", "CANDRA A": "a"}
CONSONANTS = {"CA": "cha", "CHA": "chha", "LLLA": "zha", "SSA": "sha", "SHA": "sha", "NNNA": "na", "NNA": "na", "RRA": "ra",
              "LLA": "la", "NYA": "nya", "JNYA": "gya", "KSSA": "ksha"}
NOTICE = (
    "Text in {scripts} is shown as an approximate Latin transliteration in this PDF, because the PDF renderer cannot "
    "shape Indic scripts. The original text is unchanged in the JSON and Markdown exports."
)
WEIGHTS = {"Statement": 3, "Why": 3, "Error": 2, "Text": 4, "Meaning": 4, "Languages": 3, "Sources": 2, "Models": 2,
           "Prompt versions": 2, "Region": 1.5, "Flags": 1.2, "Kind": 1.5, "Category": 1.5, "Confidence": 1.3,
           "Supported": 1.3, "Categories": 1.4, "Open conflicts": 1.3}
MAX_CELL = 600


def _indic_script(ch: str) -> str | None:
    code = ord(ch)
    return next((name for lo, hi, name in INDIC_BLOCKS if lo <= code <= hi), None)


def transliterate(text: str) -> tuple[str, set[str]]:
    """Approximate Latin for Indic-script text, and the scripts found. Built from Unicode character names
    (for example DEVANAGARI LETTER KA, TAMIL VOWEL SIGN AA), so one routine serves every Indic block."""
    out: list[str] = []
    scripts: set[str] = set()
    inherent = False  # the last output is a consonant still carrying its inherent "a"
    for ch in text:
        script = _indic_script(ch)
        if script is None:
            out.append(ch)
            inherent = False
            continue
        scripts.add(script)
        rest = unicodedata.name(ch, "").partition(" ")[2]
        if rest.startswith("LETTER "):
            token = rest[7:]
            if token in VOWELS:
                out.append(VOWELS[token])
                inherent = False
            elif token.startswith("CHILLU "):
                out.append(token[7:].lower())
                inherent = False
            else:
                out.append(CONSONANTS.get(token, token.lower().replace(" ", "")))
                inherent = True
        elif rest.startswith("VOWEL SIGN "):
            token = rest[11:]
            if inherent and out and out[-1].endswith("a"):
                out[-1] = out[-1][:-1]
            out.append(SIGNS.get(token, token.lower()))
            inherent = False
        elif rest.endswith("VIRAMA"):
            if inherent and out and out[-1].endswith("a"):
                out[-1] = out[-1][:-1]
            inherent = False
        elif rest.endswith(("ANUSVARA", "CANDRABINDU")):
            out.append("m")
            inherent = False
        elif rest.endswith("VISARGA"):
            out.append("h")
            inherent = False
        elif rest.startswith("DIGIT "):
            out.append(str(unicodedata.digit(ch, 0)))
            inherent = False
        # NUKTA, accents and anything else without a Latin reading are dropped
    return "".join(out), scripts


def latinize(text: str) -> tuple[str, set[str]]:
    """Text the standard PDF font can draw: Indic transliterated, other characters folded to Latin-1 or '?'."""
    text, scripts = transliterate(unicodedata.normalize("NFC", text))
    safe = []
    for ch in text:
        if ch in "\t\n" or ch.isprintable():
            try:
                ch.encode("cp1252")
                safe.append(ch)
            except UnicodeEncodeError:
                base = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
                safe.append(base or "?")
    return "".join(safe), scripts


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    return {
        "p": ParagraphStyle("p", parent=base, fontName="Helvetica", fontSize=9, leading=12, spaceAfter=4),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=18, leading=22, spaceAfter=8),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=13, leading=16, spaceBefore=10, spaceAfter=4),
        "h3": ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=13, spaceBefore=6, spaceAfter=3),
        "note": ParagraphStyle("note", parent=base, fontName="Helvetica-Bold", fontSize=9, leading=12),
        "cell": ParagraphStyle("cell", parent=base, fontName="Helvetica", fontSize=7.5, leading=9.5, spaceAfter=0),
        "head": ParagraphStyle("head", parent=base, fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, spaceAfter=0),
    }


def to_pdf(report: ProofReport, blocks: list[Block], *, compress: bool = True) -> tuple[bytes, list[str]]:
    """(PDF bytes, notices). Notices say what the PDF changed, for example that Indic text is transliterated."""
    found: set[str] = set()

    def clean(value: object, cap: int = MAX_CELL) -> str:
        text, scripts = latinize(str(value))
        found.update(scripts)
        return escape(text if len(text) <= cap else text[: cap - 1] + "...")

    styles = _styles()
    width = A4[0] - 36 * mm
    story: list = []
    for block in blocks:
        kind = block[0]
        if kind in ("h1", "h2", "h3", "p"):
            story.append(Paragraph(clean(block[1], 4000), styles[kind]))
        elif kind == "note":
            box = Table([[Paragraph(clean(block[1], 4000), styles["note"])]], colWidths=[width])
            box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF4CC")),
                                     ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#B8860B")),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
            story += [box, Spacer(1, 4)]
        elif kind == "ul":
            story += [Paragraph(clean(item, 4000), styles["p"], bulletText="-") for item in block[1]]
        elif kind == "table" and block[2]:
            header, rows = block[1], block[2]
            weights = [WEIGHTS.get(h, 1) for h in header]
            widths = [width * w / sum(weights) for w in weights]
            data = [[Paragraph(clean(h), styles["head"]) for h in header]] + [
                [Paragraph(clean(cell), styles["cell"]) for cell in row] for row in rows]
            table = Table(data, colWidths=widths, repeatRows=1)
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#999999")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
            story += [table, Spacer(1, 6)]
        elif kind == "table":
            story.append(Paragraph("None.", styles["p"]))
    notices = [NOTICE.format(scripts=", ".join(sorted(found)))] if found else []
    if notices:
        story.insert(1, Paragraph(escape(notices[0]), styles["note"]))
    title = latinize(report.title)[0]
    footer = f"{title[:70]} | v{report.version_number} | {NOT_LEGAL}"

    def draw_footer(canvas, doc) -> None:  # noqa: ANN001  (reportlab callback)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(18 * mm, 10 * mm, footer)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"page {doc.page}")

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=title, author="Omnicult Proof Vault", subject="Proof Report (not legal clearance)", invariant=1,
        pageCompression=1 if compress else 0,
    ).build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue(), notices
