"""Remake: Visuals and Remake: Sound (run types `remake_visual` and `remake_sound`, four stages each).

Visuals: loading_context -> generating_scene -> rendering_text -> checking_locked_regions.
Sound:   loading_context -> speaking_lines -> making_jingle -> assembling_track.

Pure: no database. Media goes in as bytes (the service loads assets) and comes out as bytes (the service stores them as
derived assets and records the operation). Model calls go only through the gateway's capability adapters
(`image_generation`, `tts`, `music`), each metered and budget-checked, each called at most once per output with no
app-level retry. In demo mode no provider is called: the committed demonstration output is used and everything else
(locked regions, text, checks, track assembly) still runs in code. Checks are computed in code, never by a model.
"""

import asyncio
import io
import time
from typing import Any, Literal, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from PIL import Image
from pydantic import BaseModel

from app.core.errors import UnsupportedCapability, ValidationFailed
from app.fixtures import remake_demo as fixtures
from app.llm.gateway import LLMError
from app.llm.media import LANGUAGE_CODES, MusicClip, SpeechAudio
from app.media import remake as pipeline
from app.media import textrender
from app.schemas.common import StepTrace
from app.schemas.runs import RunError
from app.workflows._common import DEMO_RUN_NOTE, STAGES, announce, execute, linear_graph, llm_error, local_step
from app.workflows.types import OutcomeStatus, WorkflowContext, WorkflowDeps

VISUAL, SOUND = "remake_visual", "remake_sound"
V1, V2, V3, V4 = STAGES[VISUAL]
A1, A2, A3, A4 = STAGES[SOUND]
VISUAL_PROMPT_VERSION = "remake-visual-v1"
SOUND_PROMPT_VERSION = "remake-sound-v1"
DEFAULT_JINGLE_PROMPT = (
    "A short, warm instrumental festive jingle for a family sweets advertisement: gentle percussion, flute and strings, "
    "uplifting and homely, clean modern mix."
)
INTERPRETATION_NOTE = "The scene is a model interpretation. Confirm props, symbols and styling with someone from the region."
NO_PLATE_NOTE = "No clean plate was supplied: the model was shown the finished creative, so leftover shapes of the old text are possible."
DEMO_VISUAL_NOTE = "Saved demonstration result: the scene is a committed fixture, not a live call. Locked regions, text and checks ran live in code."
DEMO_SOUND_NOTE = "Saved demonstration result: the speech clips are committed fixtures, not live calls. Timings and checks ran live in code."
UNREVIEWED_NOTE = "No native speaker has reviewed this audio; a code check cannot tell whether the pronunciation is right."
NO_JINGLE_DEMO = "Demo projects do not call the music model; the existing music bed is kept."
MAX_REFERENCE_SIDE = 1600  # the model sees a reduced copy of the layout; the stored output is full size


class LockedSpec(BaseModel):
    element_id: str
    label: str
    kind: str
    source: Literal["lock", "brand_kit_never_change"]
    bbox: list[float]


class TextSpec(BaseModel):
    element_id: str
    kind: str
    text: str
    language: str | None = None
    script: str | None = None
    bbox: list[float]


class ClaimIn(BaseModel):
    id: UUID
    handle: str
    category: str
    statement: str


class RemakeVisualInput(BaseModel):
    context: WorkflowContext
    source_version_id: UUID
    region_code: str
    region_name: str
    language: str
    language_name: str
    script: str
    plate_element_id: str
    scene_id: str | None = None
    locked: list[LockedSpec]
    texts: list[TextSpec]
    original: bytes | None = None
    plate: bytes | None = None
    reference: bytes | None = None
    original_asset_id: UUID | None = None
    plate_asset_id: UUID | None = None
    direction: str | None = None
    claims: list[ClaimIn] = []


class RemakeVisualOutcome(BaseModel):
    status: OutcomeStatus
    generated: bytes | None = None
    generated_mime: str = "image/png"
    composite: bytes | None = None
    width: int = 0
    height: int = 0
    engine: str | None = None
    source: Literal["provider", "demo_fixture"] = "provider"
    model: str | None = None
    location: str | None = None
    prompt: str | None = None
    locked_regions: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    limitations: list[str] = []
    steps: list[StepTrace] = []
    error: RunError | None = None


class VoiceLineIn(BaseModel):
    element_id: str
    text: str
    language: str | None = None
    window_ms: int | None = None
    back_translation: str | None = None


class RemakeSoundInput(BaseModel):
    context: WorkflowContext
    source_version_id: UUID
    region_code: str
    region_name: str
    language: str
    language_name: str
    script: str
    lines: list[VoiceLineIn]
    voice: str
    jingle: bool = False
    jingle_prompt: str | None = None
    max_lines: int = 8


class RemakeSoundOutcome(BaseModel):
    status: OutcomeStatus
    voiceover: bytes | None = None
    source: Literal["provider", "demo_fixture"] = "provider"
    voice: str | None = None
    language_code: str | None = None
    model: str | None = None
    location: str | None = None
    total_duration_ms: int = 0
    lines: list[dict[str, Any]] = []
    jingle: bytes | None = None
    jingle_meta: dict[str, Any] | None = None
    limitations: list[str] = []
    steps: list[StepTrace] = []
    error: RunError | None = None


# --- visuals ---------------------------------------------------------------------------------------------------


class VState(TypedDict, total=False):
    inp: RemakeVisualInput
    demo: bool
    original: Image.Image
    reference_png: bytes
    prompt: str
    client: Any
    fixture: Any
    generated: bytes
    generated_mime: str
    meta: dict[str, Any]
    composite: Any
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool


def visual_prompt(inp: RemakeVisualInput, *, has_plate: bool, has_reference: bool) -> str:
    parts = [
        f"Remake this festive advertising scene for an audience in {inp.region_name} ({inp.language_name}).",
        "The first image shows the layout with the protected areas already in place (logo, product pack, tagline). Keep every "
        "protected area, the framing and the composition exactly as they are, and keep calm, uncluttered space where the "
        "headline and copy will be added later.",
        "Change only the scene itself: props, tableware, textiles, lamps, flowers and lighting, so that it feels natural for the region.",
    ]
    if not has_plate:
        parts.append("The first image still carries text and graphics: remove them from the scene.")
    if has_reference:
        parts.append("The second image is the product pack: it must look identical wherever it appears.")
    if inp.direction:
        parts.append(f"Art direction written by the campaign owner: {inp.direction}")
    if inp.claims:
        notes = "; ".join(f"{c.statement[:160]}" for c in inp.claims[:5])
        parts.append(f"Sourced regional notes (use one only where it fits naturally; never invent customs beyond them): {notes}")
    parts.append("Photographic and realistic, with the same time of day and lighting quality as the first image.")
    return " ".join(parts)


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def _fail(state: VState, error: RunError, trace: StepTrace | None = None) -> dict:
    steps = [*state.get("steps", []), *([trace] if trace else [])]
    return {"steps": steps, "error": error, "stop": True}


async def loading_context(state: VState, config: RunnableConfig) -> dict:
    await announce(config, VISUAL, 0, "Loading the creative.")
    started, inp = time.perf_counter(), state["inp"]
    deps: WorkflowDeps = config["configurable"]["deps"]
    demo = inp.context.mode == "demo"
    original_bytes = inp.original or (fixtures.demo_original() if demo else None)
    if original_bytes is None:
        return _fail(state, RunError(code="VALIDATION_ERROR", stage=V1, retryable=False,
                                     message="The finished source creative is required. No image was generated."))
    plate_bytes = inp.plate or (fixtures.demo_plate() if demo and inp.original is None else None)
    try:
        original = await asyncio.to_thread(textrender.load_image, original_bytes)
        plate = await asyncio.to_thread(textrender.load_image, plate_bytes) if plate_bytes else None
    except ValidationFailed as exc:
        return _fail(state, RunError(code="VALIDATION_ERROR", stage=V1, retryable=False, message=f"{exc.message} No image was generated."))
    needed = {t.script or pipeline.dominant_script(t.text) for t in inp.texts}
    missing = [s for s in sorted(needed) if s in textrender.COMPLEX_SCRIPTS and textrender.shaping_engine() != "raqm"]
    if missing:  # before the paid call: unshaped script is never drawn, and a generated scene would be wasted
        return _fail(state, RunError(code="UNSUPPORTED_CAPABILITY", stage=V1, retryable=False,
                                     message=f"Text in {', '.join(missing)} cannot be rendered on this server (complex-script shaping is "
                                             "not installed). No image was generated."))
    for script in sorted(needed):
        if script in textrender.SCRIPT_FONTS and script not in textrender.available_scripts():
            return _fail(state, RunError(code="UNSUPPORTED_CAPABILITY", stage=V1, retryable=False,
                                         message=f"The bundled font for {script} is missing from this deployment. No image was generated."))
    layout = pipeline.paste_regions(pipeline.fit_cover(plate or original, original.size), original, [r.bbox for r in inp.locked]) if (
        inp.locked) else pipeline.fit_cover(plate or original, original.size)
    layout.thumbnail((MAX_REFERENCE_SIDE, MAX_REFERENCE_SIDE))
    prompt = visual_prompt(inp, has_plate=plate is not None, has_reference=inp.reference is not None)
    update: dict[str, Any] = {"original": original, "reference_png": _png(layout), "prompt": prompt, "demo": demo,
                              "limitations": [*([] if plate is not None else [NO_PLATE_NOTE])],
                              "steps": [local_step(V1, "remake_visual", "nativeproof", started)]}
    if demo:
        fixture = fixtures.visual_background(inp.region_code)
        if fixture is None:
            return _fail(state, RunError(code="UNSUPPORTED_CAPABILITY", stage=V1, retryable=False,
                                         message=f"The demonstration fixtures cover {', '.join(fixtures.demo_regions()) or 'no region'} only; "
                                                 "use a live project for other regions. Nothing was generated."))
        update["fixture"] = fixture
    else:
        client = deps.llm.capability("image_generation")
        if client is None:
            return _fail(state, RunError(code="PROVIDER_NOT_CONFIGURED", stage=V1, retryable=False,
                                         message="No image model is configured on this server. Nothing was generated."))
        update["client"] = client
    return update


async def generating_scene(state: VState, config: RunnableConfig) -> dict:
    await announce(config, VISUAL, 1, "Generating the regional scene.")
    inp, started = state["inp"], time.perf_counter()
    if state["demo"]:
        fixture = state["fixture"]
        trace = local_step(V2, "remake_visual", "fixture", started)
        trace = trace.model_copy(update={"prompt_version": fixture.prompt_version})
        return {"generated": fixture.data, "generated_mime": fixture.mime_type, "steps": [*state["steps"], trace],
                "meta": {"source": "demo_fixture", "model": fixture.model, "location": fixture.location},
                "limitations": [*state["limitations"], DEMO_VISUAL_NOTE]}
    original = state["original"]
    extras = [(inp.reference, _mime(inp.reference))] if inp.reference else []
    try:
        image = await state["client"].generate(
            state["prompt"], reference_image=state["reference_png"], reference_mime_type="image/png",
            aspect_ratio=pipeline.closest_aspect(*original.size), stage=V2, agent="remake_visual", extra_reference_images=extras,
        )
    except LLMError as exc:  # one call, never retried by the app; the gateway's own bounded retry already ran
        return _fail(state, llm_error(exc, V2, "No version was created."), exc.trace)
    return {"generated": image.image, "generated_mime": image.mime_type, "steps": [*state["steps"], image.trace],
            "meta": {"source": "provider", "model": image.model, "location": image.location},
            "limitations": [*state["limitations"], INTERPRETATION_NOTE]}


def _mime(data: bytes) -> str:
    return "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"


async def rendering_text(state: VState, config: RunnableConfig) -> dict:
    await announce(config, VISUAL, 2, "Rendering the regional text in code.")
    inp, started = state["inp"], time.perf_counter()
    try:
        generated = await asyncio.to_thread(lambda: Image.open(io.BytesIO(state["generated"])).convert("RGB"))
        composite = await asyncio.to_thread(
            pipeline.compose, state["original"], generated, [r.model_dump() for r in inp.locked],
            [t.model_dump() for t in inp.texts], inp.script, inp.language,
        )
    except UnsupportedCapability as exc:
        return _fail(state, RunError(code="UNSUPPORTED_CAPABILITY", stage=V3, retryable=False, message=exc.message),
                     local_step(V3, "remake_visual", "nativeproof", started, status="failed", error_code="UNSUPPORTED_CAPABILITY"))
    except Exception:  # an image the model returned that cannot be decoded or drawn on
        return _fail(state, RunError(code="RUN_FAILED", stage=V3, retryable=True,
                                     message="The generated image could not be processed. No version was created."),
                     local_step(V3, "remake_visual", "nativeproof", started, status="failed", error_code="RUN_FAILED"))
    return {"composite": composite, "steps": [*state["steps"], local_step(V3, "remake_visual", "nativeproof", started)]}


async def checking_locked_regions(state: VState, config: RunnableConfig) -> dict:
    await announce(config, VISUAL, 3, "Checking the locked regions.")
    started, composite = time.perf_counter(), state["composite"]
    broken = [r.element_id for r, ok in zip(state["inp"].locked, composite.locked_identical, strict=True) if not ok]
    step = local_step(V4, "remake_visual", "nativeproof", started, status="failed" if broken else "completed",
                      error_code="RUN_FAILED" if broken else None)
    if broken:  # never presented as a success: the stored image would not hold the protected pixels
        return _fail(state, RunError(code="RUN_FAILED", stage=V4, retryable=False,
                                     message=f"A locked region differs from the original ({', '.join(broken)}). Nothing was saved."), step)
    return {"steps": [*state["steps"], step]}


VISUAL_GRAPH = linear_graph(VState, [(V1, loading_context), (V2, generating_scene), (V3, rendering_text), (V4, checking_locked_regions)])


async def run_remake_visual(inp: RemakeVisualInput, deps: WorkflowDeps, progress: Any = None) -> RemakeVisualOutcome:
    state = await execute(VISUAL_GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    steps, error = state.get("steps", []), state.get("error")
    composite = state.get("composite")
    if error is not None or composite is None:
        return RemakeVisualOutcome(status="failed", steps=steps, error=error, limitations=state.get("limitations", []),
                                   prompt=state.get("prompt"))
    texts = composite.texts
    flagged = sum(1 for t in texts if not t["passed"])
    notes = [*state.get("limitations", []), *([DEMO_RUN_NOTE] if state["demo"] else []),
             *([f"{flagged} of {len(texts)} text boxes were flagged by the code checks; see the text checks."] if flagged else [])]
    meta = state["meta"]
    locked = [{**r.model_dump(), "identical": ok} for r, ok in zip(inp.locked, composite.locked_identical, strict=True)]
    return RemakeVisualOutcome(
        status="partial" if flagged else "completed", generated=state["generated"], generated_mime=state["generated_mime"],
        composite=composite.png, width=composite.width, height=composite.height, engine=composite.engine,
        source=meta["source"], model=meta["model"], location=meta["location"], prompt=state["prompt"],
        locked_regions=locked, texts=texts, limitations=list(dict.fromkeys(notes)), steps=steps,
    )


# --- sound -----------------------------------------------------------------------------------------------------


class SState(TypedDict, total=False):
    inp: RemakeSoundInput
    demo: bool
    tts: Any
    music: Any
    clips: list[tuple[VoiceLineIn, str, SpeechAudio | Any | None, list[str]]]  # (line, language, audio, problems)
    meta: dict[str, Any]
    jingle: MusicClip | None
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool


def _line_language(line: VoiceLineIn, target: str) -> str:
    return line.language if line.language in LANGUAGE_CODES else target


async def sound_loading_context(state: SState, config: RunnableConfig) -> dict:
    await announce(config, SOUND, 0, "Loading the lines.")
    started, inp = time.perf_counter(), state["inp"]
    deps: WorkflowDeps = config["configurable"]["deps"]
    demo = inp.context.mode == "demo"
    if not inp.lines or len(inp.lines) > inp.max_lines:
        return _fail(state, RunError(code="VALIDATION_ERROR", stage=A1, retryable=False,
                                     message=f"Remake: Sound speaks 1 to {inp.max_lines} lines per run. Nothing was generated."))
    update: dict[str, Any] = {"demo": demo, "steps": [local_step(A1, "remake_sound", "nativeproof", started)],
                              "limitations": [UNREVIEWED_NOTE]}
    if not demo:
        client = deps.llm.capability("tts")
        if client is None:
            return _fail(state, RunError(code="PROVIDER_NOT_CONFIGURED", stage=A1, retryable=False,
                                         message="No speech model is configured on this server. Nothing was generated."))
        update["tts"] = client
    return update


async def speaking_lines(state: SState, config: RunnableConfig) -> dict:
    await announce(config, SOUND, 1, "Speaking the lines.")
    inp, steps = state["inp"], list(state["steps"])
    clips: list[tuple[VoiceLineIn, str, Any, list[str]]] = []
    meta: dict[str, Any] = {}
    stopped: LLMError | None = None
    for line in inp.lines:
        language, problems = _line_language(line, inp.language), []
        audio: Any = None
        if stopped is not None:
            problems.append("Not spoken: an earlier line stopped the run.")
        elif language not in LANGUAGE_CODES:
            problems.append(f"The speech model does not support {language}.")
        elif state["demo"]:
            audio = fixtures.speech_clip(language, line.text, inp.voice)
            if audio is None:
                problems.append("No demonstration recording exists for this exact line and voice.")
            else:
                meta = {"source": "demo_fixture", "model": audio.model, "location": audio.location, "voice": audio.voice,
                        "language_code": audio.language_code}
        else:
            try:
                audio = await state["tts"].synthesize(line.text, language=language, voice=inp.voice, stage=A2, agent="remake_sound")
            except LLMError as exc:
                steps.append(exc.trace)
                problems.append(exc.message)
                if exc.code in ("BUDGET_EXCEEDED", "PROVIDER_NOT_CONFIGURED"):
                    stopped = exc  # nothing more is attempted
            else:
                steps.append(audio.trace)
                meta = {"source": "provider", "model": audio.model, "location": "global", "voice": audio.voice,
                        "language_code": audio.language_code}
        clips.append((line, language, audio, problems))
    if not any(a is not None for _, _, a, _ in clips):
        first = next((p for _, _, _, ps in clips for p in ps), "No line could be spoken.")
        code = stopped.code if stopped is not None else "RUN_FAILED"
        return {"clips": clips, "steps": steps, "stop": True, "error": RunError(
            code=code, stage=A2, retryable=code != "BUDGET_EXCEEDED", message=f"{first} No version was created.")}  # type: ignore[arg-type]
    return {"clips": clips, "meta": meta, "steps": steps}


async def making_jingle(state: SState, config: RunnableConfig) -> dict:
    await announce(config, SOUND, 2, "Making the jingle." if state["inp"].jingle else "No jingle requested.")
    inp, notes = state["inp"], list(state["limitations"])
    if not inp.jingle:
        return {"jingle": None}
    if state["demo"]:
        return {"jingle": None, "limitations": [*notes, NO_JINGLE_DEMO]}
    deps: WorkflowDeps = config["configurable"]["deps"]
    client = deps.llm.capability("music")
    if client is None:
        return {"jingle": None, "limitations": [*notes, "Lyria is not available on this server (Vertex AI only); no jingle was made."]}
    try:
        clip = await client.generate(inp.jingle_prompt or DEFAULT_JINGLE_PROMPT, stage=A3, agent="remake_sound")
    except LLMError as exc:  # the voice-over is kept; the jingle is an extra
        return {"jingle": None, "steps": [*state["steps"], exc.trace], "limitations": [*notes, f"No jingle was made: {exc.message}"]}
    return {"jingle": clip, "steps": [*state["steps"], clip.trace]}


async def assembling_track(state: SState, config: RunnableConfig) -> dict:
    await announce(config, SOUND, 3, "Assembling the voice-over.")
    started = time.perf_counter()
    spoken = [(line, lang, audio) for line, lang, audio, _ in state["clips"] if audio is not None]
    try:
        track, spans = pipeline.concat_wavs([a.wav for _, _, a in spoken])
    except ValueError as exc:
        return _fail(state, RunError(code="RUN_FAILED", stage=A4, retryable=False, message=f"{exc} No version was created."),
                     local_step(A4, "remake_sound", "nativeproof", started, status="failed", error_code="RUN_FAILED"))
    spans_by_id = {line.element_id: span for (line, _, _), span in zip(spoken, spans, strict=True)}
    results = []
    for line, language, audio, problems in state["clips"]:
        problems = list(problems)
        start, end = spans_by_id.get(line.element_id, (0, 0))
        duration = end - start
        fits = None if line.window_ms is None or audio is None else duration <= line.window_ms
        if fits is False:
            problems.append(f"The spoken line runs {duration / 1000:.1f} s; the scene it sat in lasts {line.window_ms / 1000:.1f} s.")
        results.append({"element_id": line.element_id, "text": line.text, "language": language, "start_ms": start, "end_ms": end,
                        "duration_ms": duration, "window_ms": line.window_ms, "fits_window": fits,
                        "back_translation": line.back_translation, "problems": problems, "spoken": audio is not None})
    return {"steps": [*state["steps"], local_step(A4, "remake_sound", "nativeproof", started)],
            "meta": {**state["meta"], "track": track, "results": results}}


SOUND_GRAPH = linear_graph(SState, [(A1, sound_loading_context), (A2, speaking_lines), (A3, making_jingle), (A4, assembling_track)])


async def run_remake_sound(inp: RemakeSoundInput, deps: WorkflowDeps, progress: Any = None) -> RemakeSoundOutcome:
    state = await execute(SOUND_GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    steps, error, meta = state.get("steps", []), state.get("error"), state.get("meta") or {}
    if error is not None or "track" not in meta:
        return RemakeSoundOutcome(status="failed", steps=steps, error=error, limitations=state.get("limitations", []))
    results = meta["results"]
    flagged = any(r["problems"] for r in results)
    jingle: MusicClip | None = state.get("jingle")
    notes = [*state.get("limitations", []), *([DEMO_SOUND_NOTE, DEMO_RUN_NOTE] if state["demo"] else [])]
    return RemakeSoundOutcome(
        status="partial" if flagged or (inp.jingle and jingle is None) else "completed", voiceover=meta["track"],
        source=meta["source"], voice=meta["voice"], language_code=meta["language_code"], model=meta["model"],
        location=meta["location"], total_duration_ms=max((r["end_ms"] for r in results), default=0), lines=results,
        jingle=jingle.wav if jingle else None,
        jingle_meta={"model": jingle.model, "location": jingle.location, "duration_ms": round(jingle.duration_seconds * 1000),
                     "prompt": inp.jingle_prompt or DEFAULT_JINGLE_PROMPT} if jingle else None,
        limitations=list(dict.fromkeys(notes)), steps=steps,
    )
