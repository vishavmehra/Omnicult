"""Regional text rendered in code: shaping, wrapping, fitting, and the guarantee that locked regions stay byte-identical.

The locked-region and layout tests use Latin text and run everywhere. The Indic tests need libraqm (Linux container, and
Pillow's Windows wheel when it loads FriBiDi and HarfBuzz) and skip where it is missing; one more proves that Indic text
is refused, not drawn unshaped, when raqm is absent.
"""

import random
from io import BytesIO

import pytest
from PIL import Image, ImageFont

from app.core.errors import UnsupportedCapability
from app.media import textrender
from app.media.textrender import SCRIPT_FONTS, ShapingUnavailable, clusters, pixel_rect, render_text, split_runs
from app.schemas.media import LockedRegion, TextBox

HAS_RAQM = textrender.shaping_engine() == "raqm"
needs_raqm = pytest.mark.skipif(not HAS_RAQM, reason="libraqm (complex-script shaping) is not available here")
SAMPLES = {
    "Deva": ("mr", "महाराष्ट्रातील सणासुदीचा उत्साह"), "Taml": ("ta", "பொங்கல் சிறப்பு தள்ளுபடி"),
    "Mlym": ("ml", "ഓണം ആഘോഷങ്ങൾക്ക് പ്രത്യേക ഓഫറുകൾ"), "Beng": ("bn", "দুর্গাপূজার বিশেষ ছাড়"),
    "Telu": ("te", "సంక్రాంతి ప్రత్యేక ఆఫర్లు"), "Knda": ("kn", "ದೀಪಾವಳಿ ವಿಶೇಷ ರಿಯಾಯಿತಿ"),
    "Gujr": ("gu", "નવરાત્રિ વિશેષ ઓફર"), "Guru": ("pa", "ਲੋਹੜੀ ਦੀਆਂ ਵਧਾਈਆਂ"), "Orya": ("or", "ରଜ ପର୍ବ ବିଶେଷ ଛାଡ଼"),
}


def noisy(width: int, height: int, seed: int = 7) -> Image.Image:
    """Random pixels, so that a restored region can only match if it was copied exactly."""
    rng = random.Random(seed)
    return Image.frombytes("RGB", (width, height), bytes(rng.randrange(256) for _ in range(width * height * 3)))


def box(text: str = "Festive Sale", script: str = "Latn", bbox: list[float] | None = None, **kwargs: object) -> TextBox:
    return TextBox(text=text, script=script, bbox=bbox or [0.1, 0.1, 0.8, 0.3], **kwargs)  # type: ignore[arg-type]


def region_bytes(image: Image.Image, bbox: list[float]) -> bytes:
    return image.convert("RGBA").crop(pixel_rect(bbox, image.size)).tobytes()


# --- locked regions ------------------------------------------------------------------------------------


def test_locked_regions_are_byte_identical_to_the_original() -> None:
    original = noisy(240, 180)
    generated = Image.new("RGB", (120, 90), "#2a8f4e")  # an image model's output: another size, another look
    logo, product = [0.05, 0.05, 0.25, 0.2], [0.55, 0.5, 0.35, 0.4]
    result = render_text(
        [box("Mahotsav offer on everything", bbox=[0.0, 0.0, 1.0, 1.0], max_size_px=60)], base=generated, original=original,
        locked=[LockedRegion(label="logo", bbox=logo), LockedRegion(label="product", bbox=product)],
    )
    assert result.image.size == original.size and result.locked_restored == 2
    for region in (logo, product):
        assert region_bytes(result.image, region) == region_bytes(original, region)  # the same bytes, not merely similar
    assert result.placements[0].overlaps_locked  # the text box covers them, and the lock still won
    assert region_bytes(result.image, [0.4, 0.3, 0.1, 0.1]) != region_bytes(original, [0.4, 0.3, 0.1, 0.1])  # the rest was replaced


def test_locked_regions_survive_a_png_round_trip() -> None:
    original = noisy(200, 120, seed=3)
    locked = [LockedRegion(label="packshot", bbox=[0.2, 0.2, 0.5, 0.5])]
    result = render_text([box(bbox=[0.0, 0.7, 1.0, 0.3])], original=original, locked=locked)
    decoded = Image.open(BytesIO(textrender.encode_png(result.image)))
    assert region_bytes(decoded, locked[0].bbox) == region_bytes(original, locked[0].bbox)
    assert decoded.size == original.size and not result.placements[0].overlaps_locked


def test_no_locked_regions_means_nothing_is_restored() -> None:
    result = render_text([box()], original=noisy(100, 100))
    assert result.locked_restored == 0 and result.engine in ("raqm", "basic")


def test_text_stays_inside_its_box() -> None:
    base = Image.new("RGB", (300, 200), "#102030")
    text_box = box("A very long festive headline that wraps over several lines", bbox=[0.25, 0.25, 0.5, 0.5], max_size_px=80)
    result = render_text([text_box], base=base)
    x0, y0, x1, y1 = pixel_rect(text_box.bbox, base.size)
    for x, y in ((0, 0), (x0 - 1, y0 + 5), (x1 + 1, y0 + 5), (x0 + 5, y1 + 1), (299, 199)):
        assert result.image.getpixel((x, y))[:3] == base.getpixel((x, y))
    inside = region_bytes(result.image, text_box.bbox)
    assert inside != region_bytes(base, text_box.bbox) and result.placements[0].rect == (x0, y0, x1, y1)


# --- layout --------------------------------------------------------------------------------------------


def test_the_largest_size_that_fits_is_chosen_and_a_tiny_box_reports_no_fit() -> None:
    canvas = (400, 300)
    roomy = render_text([box("Sale", bbox=[0, 0, 1, 1], max_size_px=48)], canvas=canvas).placements[0]
    tight = render_text([box("Sale", bbox=[0, 0, 0.2, 0.1], max_size_px=48)], canvas=canvas).placements[0]
    assert roomy.fits and roomy.font_size == 48  # capped by max_size_px, not by the box
    assert tight.fits and tight.font_size < 48
    impossible = render_text([box("Many words in a box far too small", bbox=[0, 0, 0.05, 0.02], min_size_px=12)], canvas=canvas).placements[0]
    assert not impossible.fits and impossible.font_size == 12  # clipped to its box, and reported


def test_alignment_moves_the_ink() -> None:
    def ink_span(align: str) -> tuple[int, int]:
        image = render_text([box("Hi", bbox=[0, 0, 1, 0.5], align=align, max_size_px=30, color="#ffffff")], canvas=(300, 100),
                            background="#000000").image.convert("L")
        box_ = image.point(lambda v: 255 if v > 128 else 0).getbbox()
        assert box_ is not None
        return box_[0], box_[2]

    left, center, right = ink_span("left"), ink_span("center"), ink_span("right")
    assert left[0] < 20 and right[1] > 280 and abs((center[0] + center[1]) / 2 - 150) < 12


def test_a_shadow_adds_pixels_outside_the_glyphs() -> None:
    plain = render_text([box("Hi", bbox=[0, 0, 1, 1], max_size_px=40, color="#ffffff")], canvas=(200, 100), background="#808080").image
    shadowed = render_text(
        [box("Hi", bbox=[0, 0, 1, 1], max_size_px=40, color="#ffffff", shadow={"dx": 4, "dy": 4, "color": "#000000"})],
        canvas=(200, 100), background="#808080",
    ).image
    darker = sum(1 for p, q in zip(plain.convert("L").tobytes(), shadowed.convert("L").tobytes()) if q < p - 40)
    assert darker > 20


def test_words_wrap_and_explicit_newlines_are_kept() -> None:
    style = textrender._Style("Latn", False, 24, "basic", None)
    lines = textrender.wrap("one two three four five six seven", style, 120)
    assert len(lines) > 1 and all(style.width(line) <= 120 for line in lines)
    assert textrender.wrap("first\nsecond", style, 500) == ["first", "second"]


def test_a_word_wider_than_the_box_breaks_between_clusters_never_inside_one() -> None:
    word = "क्षत्रियाणां"  # conjuncts, a virama and vowel signs
    pieces = clusters(word)
    assert "".join(pieces) == word and len(pieces) < len(word)
    for piece in pieces:
        assert not textrender._is_mark(piece[0])  # a piece never starts with a vowel sign or virama
    for before, after in zip(pieces, pieces[1:]):
        assert before[-1] != "्"  # a halant stays joined to the letter that follows it


def test_a_line_splits_into_runs_by_script() -> None:
    assert split_runs("मराठी Omnicult 50%", "Deva") == [("Deva", "मराठी "), ("Latn", "Omnicult 50%")]
    assert split_runs("50% off", "Taml") == [("Taml", "50% "), ("Latn", "off")]  # leading common text takes the box's script
    assert split_runs("", "Deva") == []


def test_every_script_has_a_bundled_font_and_the_licence_ships_with_them() -> None:
    assert textrender.available_scripts() == list(SCRIPT_FONTS)
    for stem in SCRIPT_FONTS.values():
        for weight in ("Regular", "Bold"):
            assert (textrender.FONT_DIR / f"{stem}-{weight}.ttf").stat().st_size > 20_000
    licence = (textrender.FONT_DIR / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in licence and "Noto Project Authors" in licence


# --- Indic scripts -------------------------------------------------------------------------------------


@needs_raqm
@pytest.mark.parametrize("script", list(SAMPLES))
def test_each_indic_script_renders_inside_its_box(script: str) -> None:
    language, text = SAMPLES[script]
    canvas = (700, 160)
    placed = render_text([box(text, script, bbox=[0.05, 0.1, 0.9, 0.8], language=language, max_size_px=64)], canvas=canvas,
                         background="#000000")
    placement = placed.placements[0]
    assert placement.fits and placed.engine == "raqm" and placement.lines
    ink = placed.image.convert("L").point(lambda v: 255 if v > 90 else 0).getbbox()
    assert ink is not None
    x0, y0, x1, y1 = placement.rect
    assert x0 <= ink[0] and ink[2] <= x1 and y0 <= ink[1] and ink[3] <= y1


@needs_raqm
def test_shaping_really_happens() -> None:
    """Shaped and unshaped Devanagari differ in width: the conjunct and the vowel sign reorder only under raqm."""
    path = str(textrender.FONT_DIR / "NotoSansDevanagari-Regular.ttf")
    word = "क्षत्रिय"
    shaped = ImageFont.truetype(path, 48, layout_engine=ImageFont.Layout.RAQM).getlength(word)
    unshaped = ImageFont.truetype(path, 48, layout_engine=ImageFont.Layout.BASIC).getlength(word)
    assert shaped < unshaped
    rendered = textrender._font("Deva", False, 48, "raqm").getlength(word)
    assert rendered == shaped


@needs_raqm
def test_a_latin_name_inside_indic_text_uses_the_latin_font() -> None:
    mixed = render_text([box("ओम्निकल्ट Omnicult 50%", "Deva", bbox=[0, 0, 1, 1], max_size_px=48)], canvas=(600, 120), background="#000000")
    assert mixed.placements[0].fits and len(mixed.placements[0].lines) == 1


def test_indic_text_is_refused_not_drawn_unshaped_when_raqm_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(textrender, "shaping_engine", lambda: "basic")
    with pytest.raises(ShapingUnavailable) as caught:
        render_text([box("नमस्ते", "Deva")], canvas=(200, 100))
    assert isinstance(caught.value, UnsupportedCapability) and caught.value.status_code == 501
    assert "libraqm" in caught.value.message and "Devanagari" not in caught.value.message and "Deva" in caught.value.message
    latin = render_text([box("Sale", "Latn")], canvas=(200, 100))  # Latin keeps working on the basic layout
    assert latin.engine == "basic" and latin.placements[0].fits


def test_big_images_are_refused_before_decoding() -> None:
    from app.core.errors import ValidationFailed

    bomb = Image.new("1", (6000, 5000))  # 30 megapixels, tiny when compressed
    out = BytesIO()
    bomb.save(out, format="PNG")
    with pytest.raises(ValidationFailed, match="megapixels"):
        textrender.load_image(out.getvalue())
    with pytest.raises(ValidationFailed, match="could not be decoded"):
        textrender.load_image(b"\x89PNG\r\n\x1a\n" + bytes(50))
