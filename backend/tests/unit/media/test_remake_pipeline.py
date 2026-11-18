"""Pure image and audio steps of Remake: locked pixels, text checks, the scrim, and the track assembly."""

import io
import wave

import pytest
from PIL import Image, ImageDraw

from app.media import remake as pipeline
from app.media import textrender

needs_raqm = pytest.mark.skipif(textrender.shaping_engine() != "raqm", reason="libraqm (complex-script shaping) is not available here")
TAMIL = "தீபாவளி என்றால் பலகாரம்!"


def original(size=(400, 500)) -> Image.Image:
    image = Image.new("RGB", size, (30, 60, 90))
    draw = ImageDraw.Draw(image)
    draw.rectangle((220, 250, 380, 400), fill=(200, 160, 40))  # the "tin"
    draw.rectangle((20, 20, 120, 50), fill=(250, 250, 250))  # the "logo"
    return image


def locked() -> list[dict]:
    return [{"element_id": "tin", "label": "packshot", "kind": "packshot", "source": "lock", "bbox": [0.55, 0.5, 0.4, 0.3]},
            {"element_id": "logo", "label": "logo", "kind": "logo", "source": "brand_kit_never_change", "bbox": [0.05, 0.04, 0.25, 0.06]}]


def text(element_id="h", value="Happy Diwali", bbox=(0.05, 0.12, 0.6, 0.12), **kw) -> dict:
    return {"element_id": element_id, "kind": kw.pop("kind", "headline"), "text": value, "language": kw.pop("language", "en"),
            "script": kw.pop("script", "Latn"), "bbox": list(bbox), **kw}


def test_closest_aspect_and_fit_cover_keep_the_original_proportions():
    assert pipeline.closest_aspect(1080, 1350) == "4:5" and pipeline.closest_aspect(1080, 1920) == "9:16"
    fitted = pipeline.fit_cover(Image.new("RGB", (1000, 500), "red"), (400, 500))
    assert fitted.size == (400, 500)


def test_scrim_darkens_the_top_and_bottom_bands_only():
    flat = Image.new("RGB", (100, 200), (200, 200, 200))
    out = pipeline.add_scrim(flat)
    assert out.getpixel((50, 0))[0] < 120 and out.getpixel((50, 199))[0] < 100 and out.getpixel((50, 100)) == (200, 200, 200)


def test_locked_regions_are_byte_identical_and_text_is_drawn_on_the_generated_scene():
    source, generated = original(), Image.new("RGB", (800, 1000), (160, 20, 20))  # a different size: fitted to the original
    result = pipeline.compose(source, generated, locked(), [text()], "Latn", "en")
    assert (result.width, result.height) == (400, 500) and result.locked_identical == [True, True]
    stored = Image.open(io.BytesIO(result.png)).convert("RGB")
    for region in locked():
        rect = textrender.pixel_rect(region["bbox"], source.size)
        assert stored.crop(rect).tobytes() == source.crop(rect).tobytes()
    assert stored.getpixel((10, 480)) != source.getpixel((10, 480))  # outside the regions the new scene shows
    box = result.texts[0]
    assert box["fits"] and box["script_ok"] and box["passed"] and box["color"] in ("#ffffff", "#111111") and box["font_size"] >= 10


def test_verify_locked_detects_a_changed_region():
    source = original()
    png = io.BytesIO()
    changed = source.copy()
    changed.putpixel((300, 300), (1, 2, 3))  # inside the tin
    changed.save(png, format="PNG")
    assert pipeline.verify_locked(png.getvalue(), source, locked()) == [False, True]


def test_text_that_overlaps_a_locked_region_is_flagged_and_the_locked_pixels_win():
    source = original()
    overlap = text("sub", "Order now", bbox=(0.5, 0.5, 0.45, 0.1))
    result = pipeline.compose(source, Image.new("RGB", (400, 500), (90, 10, 10)), locked(), [overlap], "Latn", "en")
    box = result.texts[0]
    assert box["overlaps_locked"] and not box["passed"] and result.locked_identical == [True, True]


def test_low_contrast_text_is_flagged_by_the_code_check():
    mid = Image.new("RGB", (400, 500), (122, 122, 122))  # neither white nor ink reaches 4.5:1 on this mid grey
    result = pipeline.compose(original(), mid, [], [text("small", "tiny print", bbox=(0.05, 0.9, 0.3, 0.02))], "Latn", "en")
    # the scrim darkens the bottom band, so use a band the scrim does not touch
    middle = pipeline.compose(original(), mid, [], [text("mid", "tiny print", bbox=(0.05, 0.45, 0.3, 0.02))], "Latn", "en")
    assert middle.texts[0]["low_contrast"] and any("contrast" in p.lower() for p in middle.texts[0]["problems"])
    assert result.texts[0]["contrast_ratio"] > middle.texts[0]["contrast_ratio"]


@needs_raqm
def test_tamil_text_is_shaped_and_checked_against_the_target_script():
    ok = pipeline.compose(original(), Image.new("RGB", (400, 500), (20, 40, 60)), [], [text(value=TAMIL, language="ta", script="Taml")], "Taml", "ta")
    assert ok.texts[0]["script_ok"] and ok.texts[0]["fits"] and ok.engine == "raqm"
    marathi = pipeline.compose(original(), Image.new("RGB", (400, 500), (20, 40, 60)), [],
                               [text(value="दिवाळी म्हणजे फराळ!", language="mr", script="Deva")], "Taml", "ta")
    box = marathi.texts[0]
    assert not box["script_ok"] and not box["passed"] and any("Deva" in p and "Taml" in p for p in box["problems"])


def test_indic_text_is_refused_when_shaping_is_unavailable(monkeypatch):
    monkeypatch.setattr(textrender, "shaping_engine", lambda: "basic")
    with pytest.raises(textrender.ShapingUnavailable):
        pipeline.compose(original(), Image.new("RGB", (400, 500)), [], [text(value=TAMIL, language="ta", script="Taml")], "Taml", "ta")


def wav(seconds: float, rate: int = 24000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(seconds * rate))
    return out.getvalue()


def test_concat_wavs_joins_clips_with_gaps_and_reports_spans():
    track, spans = pipeline.concat_wavs([wav(1.0), wav(0.5), wav(2.0)], gap_ms=400)
    assert spans == [(0, 1000), (1400, 1900), (2300, 4300)] and pipeline.duration_ms(track) == 4300


def test_clips_of_different_formats_are_not_joined():
    with pytest.raises(ValueError):
        pipeline.concat_wavs([wav(1.0, 24000), wav(1.0, 16000)])


def test_typographic_punctuation_is_drawn_in_latin_and_very_short_boxes_are_grown():
    assert textrender.char_script("\u00b7") == "Latn" and textrender.char_script("\u2022") == "Latn" and textrender.char_script("\u0964") is None
    assert pipeline.pad_small([0.1, 0.5, 0.3, 0.005], (1000, 1000)) == [0.1, 0.4935, 0.3, 0.018]
    assert pipeline.pad_small([0.1, 0.99, 0.3, 0.001], (1000, 1000))[1] == 0.9815  # stays inside the image
    assert pipeline.pad_small([0.1, 0.5, 0.3, 0.05], (1000, 1000)) == [0.1, 0.5, 0.3, 0.05]
