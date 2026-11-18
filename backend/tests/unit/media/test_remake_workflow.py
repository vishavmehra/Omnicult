"""The Remake workflows called directly, without a database: scene-window timing and the early refusals."""

from uuid import uuid4

from app.workflows import WorkflowDeps
from app.workflows.remake import RemakeSoundInput, RemakeVisualInput, VoiceLineIn, run_remake_sound, run_remake_visual
from app.workflows.types import BrandContext, WorkflowContext
from tests.api.remake_support import FakeLLM, FakeMusic, FakeSpeech


def context(mode: str = "live") -> WorkflowContext:
    return WorkflowContext(run_id=uuid4(), project_id=uuid4(), campaign_id=uuid4(), mode=mode, brand=BrandContext(name="Aamod"))  # type: ignore[arg-type]


def sound_input(lines: list[VoiceLineIn], **kw) -> RemakeSoundInput:
    return RemakeSoundInput(context=context(), source_version_id=uuid4(), region_code="IN-TN", region_name="Tamil Nadu", language="ta",
                            language_name="Tamil", script="Taml", lines=lines, voice="Sulafat", **kw)


async def test_a_spoken_line_longer_than_its_scene_is_flagged_and_the_run_is_partial():
    deps = WorkflowDeps(llm=FakeLLM({"tts": FakeSpeech(2.0), "music": FakeMusic()}))  # type: ignore[arg-type]
    lines = [VoiceLineIn(element_id="a", text="முதல் வரி", language="ta", window_ms=4000),
             VoiceLineIn(element_id="b", text="இரண்டாம் வரி", language="ta", window_ms=1500)]
    outcome = await run_remake_sound(sound_input(lines), deps)
    first, second = outcome.lines
    assert outcome.status == "partial" and first["fits_window"] is True and second["fits_window"] is False
    assert "2.0 s" in second["problems"][0] and "1.5 s" in second["problems"][0] and not first["problems"]
    assert (first["start_ms"], first["end_ms"], second["start_ms"]) == (0, 2000, 2450)


async def test_english_lines_are_spoken_in_english_and_unsupported_languages_are_reported():
    speech = FakeSpeech(1.0)
    deps = WorkflowDeps(llm=FakeLLM({"tts": speech}))  # type: ignore[arg-type]
    lines = [VoiceLineIn(element_id="a", text="Every bond, a little sweeter.", language="en"),
             VoiceLineIn(element_id="b", text="xx", language="ta")]
    outcome = await run_remake_sound(sound_input(lines), deps)
    assert [c["language"] for c in speech.calls] == ["en", "ta"] and outcome.status == "completed"


async def test_no_lines_or_too_many_lines_make_no_call():
    speech = FakeSpeech()
    deps = WorkflowDeps(llm=FakeLLM({"tts": speech}))  # type: ignore[arg-type]
    many = [VoiceLineIn(element_id=f"l{i}", text="x") for i in range(3)]
    outcome = await run_remake_sound(sound_input(many, max_lines=2), deps)
    assert outcome.status == "failed" and outcome.error.code == "VALIDATION_ERROR" and not speech.calls


async def test_a_visual_remake_without_the_original_is_refused_before_any_call():
    inp = RemakeVisualInput(context=context(), source_version_id=uuid4(), region_code="IN-TN", region_name="Tamil Nadu", language="ta",
                            language_name="Tamil", script="Taml", plate_element_id="plate", locked=[], texts=[])
    outcome = await run_remake_visual(inp, WorkflowDeps(llm=FakeLLM({})))  # type: ignore[arg-type]
    assert outcome.status == "failed" and outcome.error.code == "VALIDATION_ERROR" and "source creative" in outcome.error.message
