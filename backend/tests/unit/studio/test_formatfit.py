"""Format Fit (feature 24): deterministic crop and pad plans, safe zones, locked regions, text size, cut-downs and pixels."""

from PIL import Image

from app.studio import formatfit as ff

SOURCE = (1080, 1350)  # the demo key visual: 4:5
LOGO = ff.Box("logo", "logo", (0.05, 0.03, 0.22, 0.05), locked=True)
PACK = ff.Box("pack", "packshot", (0.57, 0.52, 0.40, 0.30), locked=True)
HEAD = ff.Box("head", "headline", (0.05, 0.10, 0.42, 0.13), text="दिवाळी म्हणजे फराळ!")
SMALL = ff.Box("small", "body", (0.05, 0.958, 0.36, 0.017), text="*small print")
BOXES = [LOGO, PACK, HEAD, SMALL]


def plan(spec_id: str, boxes: list[ff.Box] = BOXES, source: tuple[int, int] = SOURCE) -> list[ff.StrategyPlan]:
    return ff.plan_strategies(boxes, source, ff.BY_ID[spec_id], background="#ffffff")


def test_a_picture_already_in_the_ratio_gets_one_native_plan() -> None:
    (native,) = plan("4x5")
    assert native.layout.strategy == "native" and native.layout.window == (0, 0, 1080, 1350) and native.retained == 1.0


def test_the_crop_window_keeps_locked_boxes_whole_when_it_can() -> None:
    crop, pad = plan("1x1", [LOGO, HEAD])  # a square window of the 4:5 picture can hold the top boxes: slide to the top
    assert crop.layout.strategy == "crop" and crop.layout.window[1] <= 40 and crop.layout.window[2:] == (1080, 1080)  # the logo sits 40 px down
    assert crop.verdict != "conflict" and all(p.placement == "kept" for p in crop.placed)
    assert pad.layout.strategy == "pad" and pad.retained == 1.0


def test_a_crop_that_cuts_a_locked_box_is_a_conflict_that_cannot_be_applied() -> None:
    crop, pad = plan("9x16")  # 9:16 from 4:5 loses a third of the width: the logo and the pack cannot both stay
    assert crop.verdict == "conflict" and any(i.code == "locked_cut" for i in crop.issues)
    assert pad.verdict != "conflict" and ff.recommend([crop, pad]) == "pad"


def test_safe_zone_overflow_and_small_text_are_reported_per_element() -> None:
    (native,) = plan("4x5")
    small = next(p for p in native.placed if p.box.id == "small")
    assert small.in_safe is False and small.overflow == ["bottom"] and small.text_px is not None and small.text_px < small.min_text_px  # type: ignore[operator]
    assert {"text_unsafe", "text_small"} <= {i.code for i in native.issues}
    head = next(p for p in native.placed if p.box.id == "head")
    assert head.in_safe and head.placement == "kept"


def test_pad_places_the_whole_picture_centred_and_scales_it() -> None:
    _, pad = plan("9x16")
    assert pad.layout.place == (0, 285, 1080, 1350) and pad.layout.scale == 1.0
    _, wide = plan("16x9")
    assert wide.layout.window == (0, 0, 1080, 1350) and wide.layout.place[2:] == (864, 1080) and wide.layout.scale == 0.8
    assert any(i.code == "padding" for i in pad.issues)


def test_an_enlarged_crop_is_flagged() -> None:
    crop, _ = plan("9x16", [HEAD])
    assert crop.layout.scale > 1.25 and any(i.code == "upscaled" for i in crop.issues)


def test_elements_without_a_position_are_listed_not_guessed() -> None:
    (native,) = plan("4x5", [ff.Box("x", "headline", None, text="hi"), HEAD])
    assert next(p for p in native.placed if p.box.id == "x").placement == "unknown"
    assert any(i.code == "no_position" and "x" in i.message for i in native.issues)


def test_the_plan_is_deterministic() -> None:
    first, second = plan("1x1"), plan("1x1")
    assert [(p.layout, p.verdict, [i.message for i in p.issues]) for p in first] == [(p.layout, p.verdict, [i.message for i in p.issues]) for p in second]


def test_channels_map_to_formats_by_id_then_by_the_ratio_in_their_text() -> None:
    assert ff.format_for_channel("instagram_reels", "Reels", None).id == "9x16"  # type: ignore[union-attr]
    assert ff.format_for_channel("custom", "Newsletter", "4:5 image").id == "4x5"  # type: ignore[union-attr]
    assert ff.format_for_channel("custom", "Billboard", "48 sheet") is None


def test_render_makes_exactly_the_format_size_and_a_pad_keeps_every_pixel() -> None:
    image = Image.new("RGB", SOURCE, "#336699")
    image.paste(Image.new("RGB", (100, 100), "#ff0000"), (30, 30))
    crop, pad = plan("1x1", [LOGO])
    out = ff.render(image, crop.layout, ff.BY_ID["1x1"], "#ffffff")
    assert out.size == (1080, 1080) and out.getpixel((60, 60)) == (255, 0, 0)
    padded = ff.render(image, pad.layout, ff.BY_ID["1x1"], "#ffffff")
    assert padded.size == (1080, 1080) and padded.getpixel((5, 5)) == (255, 255, 255) and padded.getpixel((540, 540)) == (51, 102, 153)
    assert ff.edge_colour(image) == "#336699"


def scenes() -> list[ff.SceneBrief]:
    spec = [(0, 4700, {"headline"}), (4700, 10200, {"headline"}), (10200, 15000, {"product", "headline"}), (15000, 19900, {"headline"}),
            (19900, 29400, {"packshot", "logo", "tagline", "cta"})]
    return [ff.SceneBrief(f"s{n}", n, a, b, None, frozenset(k)) for n, (a, b, k) in enumerate(spec, 1)]


def test_cutdowns_always_keep_the_end_card_and_fit_the_target() -> None:
    by_target = {c.target_ms: c for c in ff.suggest_cutdowns(scenes(), [6000, 15000, 20000])}
    assert [(g.scene_id, g.trimmed) for g in by_target[6000].segments] == [("s5", True)] and by_target[6000].duration_ms == 6000
    assert "re-timed" in by_target[6000].notes[0]
    assert by_target[15000].segments[-1].scene_id == "s5" and by_target[15000].duration_ms <= 15000
    twenty = by_target[20000]
    assert twenty.segments[-1].scene_id == "s5" and twenty.duration_ms <= 20000 and "s3" in {g.scene_id for g in twenty.segments}  # the product scene earns a place
    assert {d["scene_id"] for d in twenty.dropped} == {f"s{n}" for n in range(1, 6)} - {g.scene_id for g in twenty.segments}


def test_cutdowns_are_chronological_and_reasoned() -> None:
    (cut,) = ff.suggest_cutdowns(scenes(), [20000])
    assert [g.position for g in cut.segments] == sorted(g.position for g in cut.segments)
    assert any("End card" in r for r in cut.segments[-1].reasons)
