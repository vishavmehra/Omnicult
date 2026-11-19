"""The pure steps of the Generate studio: format sizes, logo and product placement, headline checks, loudness peaks, trimming
with a fade, and the prompts. No database, no provider, no network."""

import io
import wave
from uuid import uuid4

import pytest
from PIL import Image

from app.fixtures import generate_demo, remake_demo
from app.media import generate as media
from app.media import textrender
from app.schemas import generate as g
from app.workflows import generate as flow
from app.workflows.types import BrandContext, WorkflowContext
from tests.api.generate_support import TAMIL_HEADLINE, png_bytes, wav_bytes


def scene(colour: tuple[int, int, int] = (20, 40, 60)) -> Image.Image:
    return Image.open(io.BytesIO(png_bytes((700, 900), colour))).convert("RGB")


def mark(size: tuple[int, int] = (900, 260)) -> Image.Image:
    return Image.open(io.BytesIO(png_bytes(size, (240, 240, 230), alpha=True)))


@pytest.mark.parametrize("fmt", list(media.FORMATS))
def test_each_format_is_composed_at_its_exact_size_with_the_logo_and_product_in_the_brand_corners(fmt: str) -> None:
    out = media.compose_image(scene(), fmt, logo=[("primary", mark())], product=mark((500, 480)), headline=None, script="Taml", language="ta")
    assert (out.width, out.height) == media.FORMATS[fmt] and Image.open(io.BytesIO(out.png)).size == media.FORMATS[fmt]
    logo, product = out.placements
    assert (logo.kind, product.kind) == ("logo", "product")
    assert logo.bbox[0] < 0.1 and logo.bbox[1] < 0.1  # top left
    assert product.bbox[0] + product.bbox[2] > 0.9 and product.bbox[1] + product.bbox[3] > 0.9  # bottom right
    assert out.headline is None and all(c["passed"] for c in out.checks if c["id"] == "size")


def test_a_logo_narrower_than_the_brand_kit_minimum_is_flagged_not_hidden() -> None:
    out = media.compose_image(scene(), "1:1", logo=[("primary", mark())], product=None, headline=None, script="Latn", language="en", logo_min_px=900)
    check = next(c for c in out.checks if c["id"] == "logo_size")
    assert check["passed"] is False and "900" in check["detail"]


def test_the_reversed_lockup_is_chosen_on_a_dark_scene_and_the_primary_on_a_light_one() -> None:
    lockups = [("primary", mark()), ("reversed", mark())]
    dark = media.compose_image(scene((10, 10, 10)), "1:1", logo=lockups, product=None, headline=None, script="Latn", language="en")
    light = media.compose_image(scene((240, 240, 240)), "1:1", logo=lockups, product=None, headline=None, script="Latn", language="en")
    assert dark.placements[0].label == "reversed" and light.placements[0].label == "primary"


def test_a_tamil_headline_is_drawn_in_code_with_script_fit_and_contrast_checks() -> None:
    out = media.compose_image(scene(), "4:5", logo=[], product=None, headline={"text": TAMIL_HEADLINE, "language": "ta"}, script="Taml", language="ta")
    assert textrender.shaping_engine() == "raqm"
    head = out.headline
    assert head is not None and head["script"] == "Taml" and head["script_ok"] and head["fits"] and head["font_size"] > 0 and not head["problems"]
    plain = media.compose_image(scene(), "4:5", logo=[], product=None, headline=None, script="Taml", language="ta")
    assert out.png != plain.png  # the lettering changed pixels
    assert {c["id"] for c in out.checks} >= {"headline_script", "headline_fits", "headline_contrast"}


def test_peaks_are_computed_from_the_samples_and_a_silent_track_is_flat() -> None:
    loud = media.peaks(wav_bytes(1.0))
    assert len(loud) == media.PEAK_SLICES and set(loud) == {100}
    silent = media.peaks(wav_bytes(1.0, loud=0))
    assert silent == [0] * media.PEAK_SLICES


def test_trimming_cuts_to_length_and_fades_the_end_and_a_shorter_clip_is_only_faded() -> None:
    clip = wav_bytes(3.0, 48000, 2, loud=10000)
    cut = media.trim_with_fade(clip, 2.0)
    samples, channels, rate = media.wav_samples(cut)
    assert (channels, rate, len(samples) // channels) == (2, 48000, 96000)
    assert samples[0] == 10000 and abs(samples[-1]) < 500  # full level at the start, almost silent at the end
    short = media.trim_with_fade(wav_bytes(1.0, 48000, 2), 5.0)
    with wave.open(io.BytesIO(short)) as w:
        assert w.getnframes() == 48000


def test_a_wav_with_a_wrong_header_frame_count_is_read_to_the_end_of_the_file() -> None:
    data = bytearray(wav_bytes(1.0, 48000, 2))
    data[40:44] = (0xFFFFFFFF).to_bytes(4, "little")  # Lyria's data length is not trustworthy
    samples, channels, rate = media.wav_samples(bytes(data))
    assert len(samples) == 96000 and (channels, rate) == (2, 48000)


@pytest.mark.skipif(not media.can_retime(), reason="ffmpeg is not installed")
async def test_retiming_changes_the_length_and_keeps_the_format() -> None:
    clip = wav_bytes(2.0)
    slow, fast = await media.retime(clip, 0.85), await media.retime(clip, 1.15)
    seconds = [len(media.wav_samples(x)[0]) / 24000 for x in (slow, clip, fast)]
    assert seconds[0] > seconds[1] > seconds[2] and 2.2 < seconds[0] < 2.5 and 1.6 < seconds[2] < 1.9
    assert await media.retime(clip, 1.0) is clip


def test_the_demo_inputs_are_the_saved_remake_files() -> None:
    scene_fixture = generate_demo.scene()
    assert scene_fixture is not None and scene_fixture.mime_type == "image/jpeg"
    # the clean plate, never a finished Remake creative (those already carry a logo, a tin and a tagline of their own)
    assert scene_fixture.data == remake_demo.PLATE.read_bytes() and scene_fixture.data != remake_demo.visual_background("IN-TN").data
    assert (scene_fixture.model, scene_fixture.location, scene_fixture.prompt_version) == ("gemini-3.1-flash-image", "global", "aamod-mh-original-v2")
    assert len(generate_demo.sample_lines()) == 4 and generate_demo.brand_file("brand/logo.png")
    wav, model, _, prompt = generate_demo.music_bed()
    assert model == "lyria-002" and wav[:4] == b"RIFF" and "dholki" in prompt


def test_the_jingle_prompt_carries_the_hints_and_stays_within_the_models_limit() -> None:
    prompt = flow.jingle_prompt("Tamil Nadu", "warm and joyful", "Deepavali", ["flute", "tabla"])
    assert "warm and joyful" in prompt and "Deepavali" in prompt and "Tamil Nadu" in prompt and "flute, tabla" in prompt and "No vocals" in prompt
    assert len(flow.jingle_prompt("Tamil Nadu", "x" * 120, "y" * 80, ["z" * 40] * 5)) <= 600


def test_the_image_prompt_asks_for_clear_space_not_lettering_and_marks_the_ideas_as_the_owners() -> None:
    request = g.GenerateImageRequest(region_code="IN-TN", language="ta", idea="Brass lamps", headline="x")
    brand = flow.BrandBrief(tone=["warm"], colours=[("Teal", "#0E4D58")], product_name="Festive Tin", objective="Sell more tins")
    inp = flow.GenerateImageInput(context=WorkflowContext(run_id=uuid4(), project_id=uuid4(), mode="live", brand=BrandContext(name="Aamod")),
                                  request=request, region_name="Tamil Nadu", language_name="Tamil", script="Taml", brand=brand)
    prompt = flow.image_prompt(inp, has_reference=False)
    assert "written by the campaign owner: Brass lamps" in prompt and "Festive Tin" in prompt and "brand's: Teal." in prompt
    # colours by name only (hex codes were drawn as swatches), and a full-bleed photograph (a "calm band" was drawn as a blank strip)
    assert "#0E4D58" not in prompt and "Never show colour swatches" in prompt and "no borders, bands" in prompt
    assert "top-left corner" in prompt and "upper third" in prompt and "Do not draw a logo" in prompt and "attached image" not in prompt
    assert "headline" not in prompt  # named, the model lettered words of the prompt into that space (seen live)
    assert "attached image" in flow.image_prompt(inp, has_reference=True)


def test_the_image_prompt_names_the_packaging_to_avoid_only_when_the_real_product_is_placed() -> None:
    brand = flow.BrandBrief(product_name="Festive Tin")

    def prompt(**extra: bool) -> str:
        request = g.GenerateImageRequest(region_code="IN-TN", language="ta", idea="Brass lamps", **extra)
        inp = flow.GenerateImageInput(context=WorkflowContext(run_id=uuid4(), project_id=uuid4(), mode="live", brand=BrandContext(name="Aamod")),
                                      request=request, region_name="Tamil Nadu", language_name="Tamil", script="Taml", brand=brand)
        return flow.image_prompt(inp, has_reference=False)

    assert "tin, jar, box, bottle or packaging of any kind" in prompt(include_product=True)
    assert "packaging" not in prompt(include_product=False) and "Do not draw a logo" in prompt(include_product=False)
