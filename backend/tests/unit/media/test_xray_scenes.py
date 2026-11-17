"""Creative X-Ray verification in code (build_scenes): what a model proposes is kept only when it can be checked."""

from uuid import UUID, uuid4

from app.agents.xray import ClaimOut, InterpretationOut, ObservationOut, SceneOut
from app.media.types import PreparedFrame
from app.schemas.assets import VisualObservation
from app.schemas.xray import TranscriptSegment
from app.workflows.xray import build_scenes

ASSET = uuid4()
FRAMES = [PreparedFrame(f"f{i}", ms, uuid4(), "image/jpeg", b"x") for i, ms in ((1, 300), (2, 3500), (3, 6800))]


def seen(frame: str, kind: str, text: str) -> VisualObservation:
    return VisualObservation(id="vis-1", asset_id=ASSET, kind=kind, description=text, location="center")  # type: ignore[arg-type]


OBSERVATIONS = {
    "f1": [seen("f1", "text_in_image", 'Headline text: "Mahotsav Sale 50% OFF"')],
    "f2": [seen("f2", "person", "A woman in a green nine-yard saree lighting a lamp")],
    "f3": [seen("f3", "text_in_image", 'Button text: "Shop Now"')],
}
TRANSCRIPT = [
    TranscriptSegment(id="t1", start_ms=0, end_ms=2000, text="Celebrate Ganesh Chaturthi with us", source="transcription"),
    TranscriptSegment(id="t2", start_ms=7000, end_ms=9000, text="Free delivery across Maharashtra", source="transcription"),
    TranscriptSegment(id="t3", start_ms=None, end_ms=None, text="An untimed line", source="user_sidecar"),
]


def verified(drafts, **kwargs):
    base = dict(kind="video", duration_ms=10_000, frames=FRAMES, observations=OBSERVATIONS, transcript=TRANSCRIPT,
                music_mood=None, visual_ok=True)
    return build_scenes(drafts, **(base | kwargs))


def test_only_what_can_be_verified_survives() -> None:
    drafts = [
        SceneOut(start_ms=0, end_ms=3000, on_screen_text=["mahotsav  sale 50% off", "FAKE OFFER TEXT"], people=["a host", "A HOST"],
                 claims=[ClaimOut(quote="50% OFF", source="on_screen_text"), ClaimOut(quote="Best price guaranteed", source="transcript")]),
        SceneOut(start_ms=3000, end_ms=6500, people=["woman in a saree"], setting="a courtyard",
                 observations=[ObservationOut(ref="o1", text="A lamp is lit", category="festival", evidence=["f2", "nope"]),
                               ObservationOut(ref="o2", text="Invented thing", evidence=["f9"]),
                               ObservationOut(ref="o3", text="No evidence at all", evidence=[])],
                 interpretations=[InterpretationOut(text="Lighting a lamp suggests a festive blessing.", based_on=["o1", "o8"], category="festival"),
                                  InterpretationOut(text="Floating opinion", based_on=["o2"]),
                                  InterpretationOut(text="Based on nothing", based_on=[])]),
        SceneOut(start_ms=6500, end_ms=12_000, on_screen_text=["shop now"],
                 claims=[ClaimOut(quote="free delivery across maharashtra", source="on_screen_text")]),
    ]
    scenes, dropped, notes = verified(drafts)
    first, second, third = scenes
    assert [t.text for t in first.on_screen_text] == ["mahotsav sale 50% off"] and first.on_screen_text[0].frame_ms == 300
    assert [(c.text, c.source) for c in first.claims] == [("50% OFF", "on_screen_text")]  # the invented claim is gone
    assert first.people == ["a host"]  # deduplicated
    assert [o.id for o in second.cultural_observations] == ["o2.1"] and second.cultural_observations[0].evidence == ["f2"]
    assert [(i.id, i.based_on) for i in second.cultural_interpretations] == [("i2.1", ["o2.1"])]
    assert second.cultural_interpretations[0].limitations and "not an observed fact" in second.cultural_interpretations[0].limitations[0]
    assert third.end_ms == 10_000  # clamped to the duration
    assert third.on_screen_text[0].frame_ms == 6800
    assert [(c.source, c.segment_id) for c in third.claims] == [("transcript", "t2")]  # found in the transcript, so labelled so
    assert dropped == {"on_screen_text": 1, "claims": 1, "cultural_observations": 2, "cultural_interpretations": 2}
    assert notes == []


def test_the_transcript_and_keyframes_are_assigned_by_code_not_by_the_model() -> None:
    scenes, _, _ = verified([SceneOut(start_ms=0, end_ms=3000), SceneOut(start_ms=3000, end_ms=6500), SceneOut(start_ms=6500)])
    assert [[t.id for t in s.transcript] for s in scenes] == [["t1"], [], ["t2"]]  # untimed t3 belongs to no scene
    assert [s.keyframe_asset_id for s in scenes] == [f.asset_id for f in FRAMES]
    assert [s.frame_ms for s in scenes] == [[300], [3500], [6800]]
    assert scenes[2].end_ms == 10_000 and all(s.provenance["transcript"] == "transcribed" for s in scenes)
    assert scenes[0].provenance["cultural_interpretations"] == "interpretation"
    assert scenes[0].provenance["on_screen_text"] == "observed" and scenes[0].provenance["people"] == "model_generated"


def test_visual_fields_are_discarded_when_vision_did_not_run() -> None:
    draft = SceneOut(start_ms=0, end_ms=5000, on_screen_text=["Mahotsav Sale"], people=["a woman"], objects=["lamp"],
                     setting="home", claims=[ClaimOut(quote="Celebrate Ganesh Chaturthi with us", source="transcript")],
                     observations=[ObservationOut(ref="o1", text="Spoken festival name", evidence=["f1", "t1"])])
    scenes, dropped, _ = verified([draft], visual_ok=False, observations={})
    scene = scenes[0]
    assert (scene.on_screen_text, scene.people, scene.objects, scene.setting) == ([], [], [], None)
    assert dropped["visual_fields_without_vision"] == 1
    assert [c.segment_id for c in scene.claims] == ["t1"]  # speech does not need vision
    assert scene.cultural_observations[0].evidence == ["t1"]  # a frame nobody described is not evidence
    assert any("no vision model" in limit for limit in scene.limitations)


def test_no_model_output_gives_timing_only_scenes_from_the_keyframes() -> None:
    scenes, dropped, notes = verified(None)
    assert [(s.start_ms, s.end_ms) for s in scenes] == [(0, 3500), (3500, 6800), (6800, 10_000)] and dropped == {}
    assert all(not s.on_screen_text and not s.claims and not s.cultural_observations for s in scenes)
    assert all("not analysed" in s.limitations[0] for s in scenes) and [t.id for t in scenes[0].transcript] == ["t1"]


def test_scenes_with_impossible_times_are_dropped_and_overlaps_are_trimmed() -> None:
    scenes, dropped, _ = verified([
        SceneOut(start_ms=0, end_ms=4000), SceneOut(start_ms=3000, end_ms=6000),  # overlaps the first
        SceneOut(start_ms=8000, end_ms=7000),  # ends before it starts
        SceneOut(start_ms=20_000, end_ms=30_000),  # after the end of the video
    ])
    assert [(s.start_ms, s.end_ms) for s in scenes] == [(0, 4000), (4000, 6000)]  # the overlap is trimmed, not kept twice
    assert dropped == {"scene_times": 2}  # the backwards scene and the one after the end


def test_when_every_scene_is_invalid_the_keyframe_timings_are_used_and_said() -> None:
    scenes, dropped, notes = verified([SceneOut(start_ms=50_000, end_ms=60_000)])
    assert [(s.start_ms, s.end_ms) for s in scenes] == [(0, 3500), (3500, 6800), (6800, 10_000)]
    assert dropped == {"scene_times": 1} and "no scene with valid times" in notes[0]


def test_an_image_is_one_scene_without_a_duration() -> None:
    frame = PreparedFrame("f1", 0, None, "image/png", b"x")
    observations = {"f1": [seen("f1", "text_in_image", "Text: Diwali Dhamaka")]}
    drafts = [SceneOut(start_ms=0, on_screen_text=["diwali dhamaka", "Not there"], people=["a family"]),
              SceneOut(start_ms=500, people=["extra"]), SceneOut(start_ms=900)]
    scenes, dropped, _ = build_scenes(drafts, kind="image", duration_ms=None, frames=[frame], observations=observations,
                                      transcript=[], music_mood=None, visual_ok=True)
    assert len(scenes) == 1 and (scenes[0].start_ms, scenes[0].end_ms, scenes[0].keyframe_asset_id) == (0, None, None)
    assert [t.text for t in scenes[0].on_screen_text] == ["diwali dhamaka"] and scenes[0].people == ["a family"]
    assert dropped == {"on_screen_text": 1, "extra_scenes": 2}


def test_audio_only_has_scenes_without_keyframes_and_the_mood_comes_from_the_audio_capability() -> None:
    scenes, _, _ = build_scenes([SceneOut(start_ms=0, end_ms=4000), SceneOut(start_ms=4000)], kind="audio", duration_ms=9000, frames=[],
                                observations={}, transcript=TRANSCRIPT, music_mood="warm, festive", visual_ok=False)
    assert [(s.start_ms, s.end_ms, s.keyframe_asset_id, s.music_mood) for s in scenes] == [
        (0, 4000, None, "warm, festive"), (4000, 9000, None, "warm, festive")]
    assert [[t.id for t in s.transcript] for s in scenes] == [["t1"], ["t2"]]


def test_scene_ids_are_unique_uuids() -> None:
    scenes, _, _ = verified([SceneOut(start_ms=0, end_ms=5000), SceneOut(start_ms=5000, end_ms=9000)])
    assert len({s.id for s in scenes}) == 2 and all(isinstance(s.id, UUID) for s in scenes)
