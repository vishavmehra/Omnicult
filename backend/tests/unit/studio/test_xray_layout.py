"""The X-Ray layout: what code keeps of the model's layout proposals, and the Studio elements built from it."""

from types import SimpleNamespace
from uuid import uuid4

from app.agents.xray import LayoutOut
from app.media.types import PreparedFrame
from app.schemas.assets import VisualObservation
from app.services.remake import default_voice_lines
from app.services.versions import layout_elements, merge_marks
from app.workflows.xray import verify_layout

ASSET = uuid4()


def obs(id_: str, kind: str, description: str, bbox: list[float] | None) -> VisualObservation:
    return VisualObservation(id=id_, asset_id=ASSET, kind=kind, description=description, location=None, bbox=bbox)  # type: ignore[arg-type]


def test_only_layout_items_code_can_check_are_kept_all_from_one_keyframe():
    frames = [PreparedFrame("f1", 0, None, "image/png", b"1"), PreparedFrame("f2", 2000, None, "image/png", b"2")]
    observations = {"f1": [obs("vis-1", "text_in_image", "Text: 'दिवाळी म्हणजे फराळ!'", [0.1, 0.1, 0.5, 0.1]),
                           obs("vis-2", "object", "A teal tin", [0.6, 0.5, 0.3, 0.3]),
                           obs("vis-3", "text_in_image", "Aamod Festive Tin", [0.1, 0.8, 0.3, 0.05]),
                           obs("vis-4", "symbol", "A diya logo", None)],
                    "f2": [obs("vis-1", "text_in_image", "Order now", [0.2, 0.9, 0.3, 0.05])]}
    items = [LayoutOut(role="headline", frame="f1", observation="vis-1", text="दिवाळी म्हणजे फराळ!"),
             LayoutOut(role="packshot", frame="f1", observation="vis-2"),
             LayoutOut(role="product", frame="f1", observation="vis-3"),  # a product NAME is text, not the pack
             LayoutOut(role="logo", frame="f1", observation="vis-4"),  # no box from the vision model
             LayoutOut(role="body", frame="f1", observation="vis-1", text="A line nobody saw"),
             LayoutOut(role="cta", frame="f2", observation="vis-1", text="Order now")]  # another keyframe than the most cited
    dropped: dict[str, int] = {}
    kept = verify_layout(items, frames, observations, dropped)
    assert [(k.role, k.text, k.frame_ms, k.observation_id, k.bbox) for k in kept] == [
        ("headline", "दिवाळी म्हणजे फराळ!", 0, "vis-1", [0.1, 0.1, 0.5, 0.1]), ("packshot", None, 0, "vis-2", [0.6, 0.5, 0.3, 0.3])]
    assert dropped == {"layout": 4}


def test_an_icon_and_the_brand_name_beside_it_become_one_logo():
    items = [{"role": "logo", "bbox": [0.05, 0.12, 0.05, 0.035]}, {"role": "logo", "bbox": [0.11, 0.125, 0.15, 0.03]},
             {"role": "logo", "bbox": [0.4, 0.8, 0.1, 0.05]}, {"role": "headline", "bbox": [0.1, 0.4, 0.5, 0.05]}]
    merged = merge_marks(items)
    assert [i["bbox"] for i in merged if i["role"] == "logo"] == [[0.05, 0.12, 0.21, 0.035], [0.4, 0.8, 0.1, 0.05]]
    assert [i["role"] for i in merged].count("headline") == 1


def test_studio_elements_from_the_layout_carry_their_scene_box_and_where_the_box_came_from():
    keyframe, scene_id = uuid4(), uuid4()
    creative = SimpleNamespace(kind="video", asset_id=uuid4(), language="mr", analysis={"frames": [
        {"timestamp_ms": 300, "observations": [{"id": "vis-2", "description": "A diya logo"}]}]})
    scene = SimpleNamespace(id=scene_id, position=0, keyframe_asset_id=keyframe, payload={
        "layout": [{"role": "headline", "text": "दिवाळी म्हणजे फराळ!", "frame_ms": 300, "observation_id": "vis-1", "bbox": [0.27, 0.41, 0.46, 0.05]},
                   {"role": "logo", "text": None, "frame_ms": 300, "observation_id": "vis-2", "bbox": [0.05, 0.12, 0.21, 0.03]},
                   {"role": "tagline", "text": "Every bond, a little sweeter.", "frame_ms": 300, "observation_id": "vis-3", "bbox": [0.2, 0.9, 0.5, 0.02]}],
        "transcript": [{"id": "t1", "text": "दिवाळी आली की घरभर फराळाचा सुगंध दरवळतो.", "language": "mr"}]})
    elements = {e.id: e for e in layout_elements([(creative, [scene])])}  # type: ignore[list-item]
    assert list(elements) == ["film-s1-scene", "film-s1-logo", "film-s1-headline", "film-s1-tagline", "film-vo-1"]
    assert elements["film-s1-scene"].value == f"asset:{keyframe}" and elements["film-s1-scene"].bbox == [0.0, 0.0, 1.0, 1.0]
    head, logo, tag, line = elements["film-s1-headline"], elements["film-s1-logo"], elements["film-s1-tagline"], elements["film-vo-1"]
    assert (head.language, head.script, head.bbox_source, head.scene_id) == ("mr", "Deva", "model_detected", str(scene_id))
    assert (logo.value, logo.language, logo.bbox) == ("A diya logo", None, [0.05, 0.12, 0.21, 0.03])
    assert (tag.language, tag.script) == ("en", "Latn")
    assert (line.kind, line.bbox, line.bbox_source, line.scene_id) == ("voiceover", None, None, str(scene_id))


def test_remake_sound_speaks_the_script_and_falls_back_to_captions_never_both():
    script = [{"id": "vo-1", "kind": "voiceover", "value": "line"}, {"id": "cap-1", "kind": "caption", "value": "line"}]
    assert [e["id"] for e in default_voice_lines(script)] == ["vo-1"]
    audio_only = [{"id": "vo", "kind": "voiceover", "value": {"asset_id": "x"}}, {"id": "cap-1", "kind": "caption", "value": "line"}]
    assert [e["id"] for e in default_voice_lines(audio_only)] == ["cap-1"]


def test_the_video_logo_lockup_is_the_one_that_reads_on_the_scene_behind_it():
    import io

    from PIL import Image

    from app.services.remake_video import _logo_contrast

    def png(colour: tuple[int, int, int, int], size: tuple[int, int]) -> bytes:
        out = io.BytesIO()
        Image.new("RGBA", size, colour).save(out, format="PNG")
        return out.getvalue()

    dark_scene = Image.new("RGB", (1000, 1000), (20, 30, 30))
    wide_box = [0.05, 0.03, 0.2, 0.05]  # 200 x 50 px
    teal, cream = png((14, 77, 88, 255), (400, 100)), png((251, 241, 221, 255), (400, 100))
    assert _logo_contrast(cream, dark_scene, wide_box) > _logo_contrast(teal, dark_scene, wide_box)
    assert _logo_contrast(png((251, 241, 221, 255), (100, 100)), dark_scene, wide_box) == -1.0  # a square mark does not fit a wide box


def test_a_panel_reads_one_whole_scene_of_a_studio_version():
    from app.services.audience import studio_copy

    elements = [
        {"kind": "headline", "value": "தீபாவளி என்றாலே", "scene_id": "film-1"}, {"kind": "headline", "value": "பலகாரம்தான்!", "scene_id": "film-1"},
        {"kind": "headline", "value": "தீபாவளி என்றாலே இனிய", "scene_id": "kv"}, {"kind": "headline", "value": "பலகாரம்தான்!", "scene_id": "kv"},
        {"kind": "body", "value": "வீட்டு சுவை, இப்போது ஒரே டின்னில்", "scene_id": "kv"}, {"kind": "cta", "value": "இன்றே ஆர்டர் செய்யுங்கள்", "scene_id": "kv"},
        {"kind": "voiceover", "value": "spoken", "scene_id": "film-1"}, {"kind": "logo", "value": "a diya logo", "scene_id": "kv"}]
    assert studio_copy(elements) == {"headline": "தீபாவளி என்றாலே இனிய பலகாரம்தான்!", "body": "வீட்டு சுவை, இப்போது ஒரே டின்னில்",
                                     "call_to_action": "இன்றே ஆர்டர் செய்யுங்கள்"}
    assert studio_copy([{"kind": "logo", "value": "x"}]) == {}
