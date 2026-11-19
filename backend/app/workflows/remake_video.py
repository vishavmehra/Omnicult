"""Remake: Video (run type `remake_video`, four stages): loading_context -> generating_video -> adding_voiceover -> checking_clip.

One short regional clip from Veo 3.1 on Vertex AI. Pure: no database. Images and audio go in as bytes (the service loads the
assets) and the clip comes out as bytes (the service stores it as a derived asset and records the operation).

The model is called through the gateway's `video` capability adapter, once per run, never retried by the app (a retry could
start and bill a second clip), metered and budget-checked. The start frame is the regional key visual WITHOUT its text: any
on-screen text is added in code after the clip, or the clip has none. Video models cannot guarantee that locked brand
elements stay undistorted from frame to frame, so the run says so, and every check is computed in code from the delivered file
(ffprobe), never by a model. In demo mode no provider is called: the committed demonstration clip is used and the start frame,
the voice-over join and the checks still run in code.
"""

import asyncio
import time
from typing import Any, Literal, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from app.core.errors import ValidationFailed
from app.fixtures import remake_demo as fixtures
from app.llm.gateway import LLMError
from app.llm.media import VIDEO_SECONDS
from app.media import ffmpeg, textrender
from app.media import remake_video as pipeline
from app.media.remake import duration_ms as wav_ms
from app.schemas.common import StepTrace
from app.schemas.runs import RunError
from app.workflows._common import STAGES, announce, execute, linear_graph, llm_error, local_step
from app.workflows.remake import LockedSpec
from app.workflows.types import OutcomeStatus, WorkflowContext, WorkflowDeps

VIDEO = "remake_video"
V1, V2, V3, V4 = STAGES[VIDEO]
VIDEO_PROMPT_VERSION = "remake-video-v1"
NEGATIVE_PROMPT = "text, letters, subtitles, captions, watermark, extra logos, warped packaging, distorted product, blurry, low quality"
INTERPRETATION_NOTE = "The clip is a model interpretation. Confirm props, symbols and motion with someone from the region."
NO_TEXT_NOTE = "The clip has no on-screen text: the model is never asked to draw it, and any text would be added in code."
LOCK_NOTE = ("Video models cannot guarantee that the logo, the pack and the tagline stay undistorted from frame to frame. They are "
             "in the start frame and the prompt asks for them unchanged, but nothing here proves it: review the clip frame by frame "
             "before use.")
NO_FRAME_NOTE = "No remade key visual was available, so the clip was generated from the prompt alone: the logo and the pack are not in it."
OWN_FRAME_NOTE = "The start frame is the image chosen for this run; locked regions are only as the image holds them."
UNREVIEWED_NOTE = "The voice-over is machine speech; no native speaker has reviewed it."
DURATION_TOLERANCE_MS = 1000  # the delivered length may differ from the requested one by this much before the check is flagged
StartSource = Literal["remake_scene", "asset", "demo_fixture", "none"]


class VideoPromptParts(BaseModel):
    """What the art-directed prompt is made from (all read from the project by the service)."""

    region_name: str
    language_name: str
    product: str | None = None
    message: str | None = None  # the brief's primary message
    settings: list[str] = []  # where the original film's scenes are set (not what they show: the first frame decides that)
    direction: str | None = None
    has_start_frame: bool = True


def _clip(text: str | None, limit: int) -> str:
    """`text` cut to `limit` characters at a sentence end when one is near enough, else at a word: never mid-word."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= limit // 3:
        return cut[: end + 1]
    return cut[: cut.rfind(" ")].rstrip(",;:- ") + "."


def video_prompt(parts: VideoPromptParts) -> str:
    """A short, plain-English shot description. Deterministic: the same inputs give the same prompt, so the preview shows
    exactly what is sent. It never contains text to be rendered (the model is not asked to write anything)."""
    lines = [f"A short, calm festive advertising shot for an audience in {parts.region_name} ({parts.language_name}-speaking)."]
    if parts.product:
        lines.append(f"Product: {_clip(parts.product, 240)}")
    if parts.message:
        lines.append(f"The campaign says: {_clip(parts.message, 140)}")
    settings = "; ".join(_clip(x, 90).rstrip(".") for x in parts.settings[:3])
    if settings and parts.has_start_frame:
        lines.append(f"Pacing follows the original film (its settings: {settings}); the first frame, not the film, decides what is shown.")
    elif settings:
        lines.append(f"The settings follow the original film: {settings}.")
    if parts.has_start_frame:
        lines.append("The first frame is the finished scene. Keep the product tin, the logo and the tagline exactly as they appear in "
                     "it: sharp, undistorted and in the same place. Keep the framing and the composition.")
    lines.append("Gentle, natural motion only: a slow camera push-in, flickering lamp light, a soft breeze moving garlands and flowers, "
                 "a little steam. No new people appear.")
    if parts.direction:
        lines.append(f"Art direction written by the campaign owner: {_clip(parts.direction, 400)}")
    lines.append("No text, letters, subtitles, captions or watermarks anywhere. Photographic and realistic, "
                 + ("warm light consistent with the first frame." if parts.has_start_frame else "warm, natural light."))
    return " ".join(lines)


class RemakeVideoInput(BaseModel):
    context: WorkflowContext
    source_version_id: UUID
    region_code: str
    region_name: str
    language: str
    language_name: str
    prompt: str
    negative_prompt: str = NEGATIVE_PROMPT
    seconds: int = 6
    start_source: StartSource = "none"
    original: bytes | None = None  # the finished source creative (locked regions are restored from it)
    scene: bytes | None = None  # the generated regional scene from Remake: Visuals
    start_image: bytes | None = None  # an image chosen for this run, used as it is
    locked: list[LockedSpec] = []
    voiceover: bytes | None = None
    voiceover_asset_id: UUID | None = None
    original_asset_id: UUID | None = None
    scene_asset_id: UUID | None = None
    start_asset_id: UUID | None = None


class VideoCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class RemakeVideoOutcome(BaseModel):
    status: OutcomeStatus
    clip: bytes | None = None  # the file to play: with the voice-over when it was joined
    silent_clip: bytes | None = None  # the clip as the model delivered it
    joined: bool = False
    voiceover_ms: int | None = None
    start_frame: bytes | None = None
    start_source: StartSource = "none"
    aspect_ratio: str | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    size_bytes: int = 0
    seconds: int = 0
    resolution: str = "720p"
    source: Literal["provider", "demo_fixture"] = "provider"
    model: str | None = None
    location: str | None = None
    operation_id: str | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    locked_regions: list[dict[str, Any]] = []
    checks: list[VideoCheck] = []
    limitations: list[str] = []
    steps: list[StepTrace] = []
    error: RunError | None = None


class GState(TypedDict, total=False):
    inp: RemakeVideoInput
    demo: bool
    client: Any
    fixture: Any
    frame: bytes | None
    aspect: str
    source: StartSource
    meta: dict[str, Any]
    raw: bytes
    mime: str
    final: bytes
    joined: bool
    facts: Any
    checks: list[VideoCheck]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool


def _fail(state: GState, error: RunError, trace: StepTrace | None = None) -> dict:
    return {"steps": [*state.get("steps", []), *([trace] if trace else [])], "error": error, "stop": True}


def _check(name: str, passed: bool, detail: str) -> VideoCheck:
    return VideoCheck(name=name, passed=passed, detail=detail)


async def prepare_frame(inp: RemakeVideoInput, demo: bool) -> tuple[bytes | None, str, StartSource]:
    """(start frame PNG or None, aspect ratio, where it came from). Raises ValidationFailed for an image that cannot be read.
    Shared with the preview, so what is shown is what a run would send."""
    source: StartSource = inp.start_source
    if demo:  # demo projects always start from the committed key visual and scene; their own choices would not match the saved clip
        original_bytes = inp.original or fixtures.demo_original()
        scene_bytes = inp.scene or fixtures.demo_scene(inp.region_code)
        source = "demo_fixture"
    else:
        original_bytes, scene_bytes = inp.original, inp.scene
    if source in ("remake_scene", "demo_fixture") and original_bytes:
        original = await asyncio.to_thread(textrender.load_image, original_bytes)
        scene = await asyncio.to_thread(textrender.load_image, scene_bytes) if scene_bytes else None
        layout = await asyncio.to_thread(pipeline.build_layout, original, scene, [r.bbox for r in inp.locked])
    elif source == "asset" and inp.start_image:
        layout = await asyncio.to_thread(textrender.load_image, inp.start_image)
    else:
        return None, "9:16", "none"
    frame, aspect, _ = await asyncio.to_thread(pipeline.start_frame, layout)
    return frame, aspect, source


async def loading_context(state: GState, config: RunnableConfig) -> dict:
    await announce(config, VIDEO, 0, "Preparing the start frame.")
    started, inp = time.perf_counter(), state["inp"]
    deps: WorkflowDeps = config["configurable"]["deps"]
    demo = inp.context.mode == "demo"
    if inp.seconds not in VIDEO_SECONDS or not inp.prompt.strip():
        return _fail(state, RunError(code="VALIDATION_ERROR", stage=V1, retryable=False,
                                     message=f"A clip needs a prompt and lasts {', '.join(map(str, VIDEO_SECONDS))} seconds. Nothing was generated."))
    update: dict[str, Any] = {"demo": demo}
    if demo:
        fixture = fixtures.video_clip(inp.region_code)
        if fixture is None:
            return _fail(state, RunError(code="UNSUPPORTED_CAPABILITY", stage=V1, retryable=False,
                                         message=f"The demo covers {', '.join(fixtures.demo_video_regions()) or 'no region'} "
                                                 "only; use a live project for other regions. Nothing was generated."))
        update["fixture"] = fixture
    try:
        frame, aspect, source = await prepare_frame(inp, demo)
    except ValidationFailed as exc:
        return _fail(state, RunError(code="VALIDATION_ERROR", stage=V1, retryable=False, message=f"{exc.message} Nothing was generated."))
    if not demo:
        client = deps.llm.capability("video")
        if client is None:
            return _fail(state, RunError(code="PROVIDER_NOT_CONFIGURED", stage=V1, retryable=False,
                                         message="No video model is configured on this server. Nothing was generated."))
        update["client"] = client
    notes = [INTERPRETATION_NOTE, NO_TEXT_NOTE, *([LOCK_NOTE] if frame else []), *([OWN_FRAME_NOTE] if source == "asset" else []),
             *([NO_FRAME_NOTE] if source == "none" else [])]
    update.update(frame=frame, aspect=aspect, source=source, limitations=notes, steps=[local_step(V1, VIDEO, "omnicult", started)])
    return update


async def generating_video(state: GState, config: RunnableConfig) -> dict:
    await announce(config, VIDEO, 1, "Generating the clip." if not state["demo"] else "Loading the saved clip.")
    inp, started = state["inp"], time.perf_counter()
    if state["demo"]:
        fixture = state["fixture"]
        trace = local_step(V2, VIDEO, "fixture", started).model_copy(update={"prompt_version": fixture.prompt_version})
        return {"raw": fixture.data, "mime": fixture.mime_type, "steps": [*state["steps"], trace],
                "meta": {"source": "demo_fixture", "model": fixture.model, "location": fixture.location, "operation_id": None,
                         "prompt": fixture.prompt},  # the saved clip was made from this prompt, whatever the project's own would be
                "limitations": state["limitations"]}
    try:
        clip = await state["client"].generate(
            inp.prompt, start_image=state["frame"], start_mime_type="image/png", seconds=inp.seconds, aspect_ratio=state["aspect"],
            negative_prompt=inp.negative_prompt, stage=V2, agent=VIDEO,
        )
    except LLMError as exc:  # one call, never retried by the app; an accepted request may still be billed (the message says so)
        return _fail(state, llm_error(exc, V2, "No version was created."), exc.trace)
    return {"raw": clip.video, "mime": clip.mime_type, "steps": [*state["steps"], clip.trace],
            "meta": {"source": "provider", "model": clip.model, "location": clip.location, "operation_id": clip.operation_id}}


async def adding_voiceover(state: GState, config: RunnableConfig) -> dict:
    await announce(config, VIDEO, 2, "Joining the voice-over." if state["inp"].voiceover else "No voice-over to join.")
    inp, started, notes = state["inp"], time.perf_counter(), list(state["limitations"])
    raw = state["raw"]
    if not inp.voiceover:
        return {"final": raw, "joined": False, "steps": [*state["steps"], local_step(V3, VIDEO, "omnicult", started)]}
    try:
        facts = await pipeline.inspect_clip(raw)
        clip_ms = facts.duration_ms or inp.seconds * 1000
        vo_ms = await asyncio.to_thread(wav_ms, inp.voiceover)
        if not pipeline.voiceover_fits(vo_ms, clip_ms):
            notes.append(f"The voice-over runs {vo_ms / 1000:.1f} s and the clip {clip_ms / 1000:.1f} s, so it was not joined: speech is "
                         "never cut. Speak fewer lines in Remake: Sound, or make a longer clip.")
            return {"final": raw, "joined": False, "limitations": notes, "steps": [*state["steps"], local_step(V3, VIDEO, "omnicult", started)]}
        final = await pipeline.join_voiceover(raw, inp.voiceover, clip_ms)
    except (ffmpeg.MediaToolMissing, ffmpeg.MediaProcessingFailed, ffmpeg.MediaUnreadable, ValueError) as exc:
        notes.append(f"The voice-over was not joined: {getattr(exc, 'message', None) or str(exc)}")  # the silent clip is kept
        return {"final": raw, "joined": False, "limitations": notes, "steps": [*state["steps"], local_step(V3, VIDEO, "omnicult", started)]}
    return {"final": final, "joined": True, "limitations": [*notes, UNREVIEWED_NOTE], "steps": [*state["steps"], local_step(V3, VIDEO, "omnicult", started)]}


async def checking_clip(state: GState, config: RunnableConfig) -> dict:
    await announce(config, VIDEO, 3, "Checking the clip.")
    inp, started, notes = state["inp"], time.perf_counter(), list(state["limitations"])
    checks: list[VideoCheck] = []
    facts = None
    try:
        facts = await pipeline.inspect_clip(state["final"])
    except ffmpeg.MediaToolMissing as exc:
        notes.append(f"The clip was not checked: {exc.message}")
    except ffmpeg.MediaUnreadable:
        return _fail(state, RunError(code="RUN_FAILED", stage=V4, retryable=False,
                                     message="The delivered file could not be read as video. Nothing was saved."),
                     local_step(V4, VIDEO, "omnicult", started, status="failed", error_code="RUN_FAILED"))
    if facts is not None:
        checks.append(_check("readable video", facts.has_video, f"{facts.container or 'unknown container'}, {facts.video_codec or 'unknown codec'}"
                             if facts.has_video else "The file has no video stream."))
        if facts.duration_ms is not None:
            wanted = inp.seconds * 1000
            ok = abs(facts.duration_ms - wanted) <= DURATION_TOLERANCE_MS
            checks.append(_check("length", ok, f"{facts.duration_ms / 1000:.1f} s delivered, {inp.seconds} s requested"))
        if facts.width and facts.height:
            checks.append(_check("shape", (facts.width < facts.height) == (state["aspect"] == "9:16"),
                                 f"{facts.width}x{facts.height}, asked for {state['aspect']}"))
        checks.append(_check("audio track", facts.has_audio == state["joined"],
                             "The voice-over is the only audio." if state["joined"] else "No audio: the model was asked for none."))
        if not facts.has_video:
            return _fail(state, RunError(code="RUN_FAILED", stage=V4, retryable=False, message="The delivered file has no video. Nothing was saved."),
                         local_step(V4, VIDEO, "omnicult", started, status="failed", error_code="RUN_FAILED"))
    return {"facts": facts, "checks": checks, "limitations": notes, "steps": [*state["steps"], local_step(V4, VIDEO, "omnicult", started)]}


VIDEO_GRAPH = linear_graph(GState, [(V1, loading_context), (V2, generating_video), (V3, adding_voiceover), (V4, checking_clip)])


async def run_remake_video(inp: RemakeVideoInput, deps: WorkflowDeps, progress: Any = None) -> RemakeVideoOutcome:
    state = await execute(VIDEO_GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    steps, error = state.get("steps", []), state.get("error")
    if error is not None or "final" not in state or "checks" not in state:
        return RemakeVideoOutcome(status="failed", steps=steps, error=error, limitations=state.get("limitations", []), prompt=inp.prompt)
    meta, facts, checks = state["meta"], state.get("facts"), state["checks"]
    flagged = [c for c in checks if not c.passed]
    notes = [*state["limitations"],
             *([f"{len(flagged)} of {len(checks)} code checks were flagged; see the checks."] if flagged else [])]
    return RemakeVideoOutcome(
        status="partial" if flagged else "completed", clip=state["final"], silent_clip=state["raw"], joined=state["joined"],
        voiceover_ms=await asyncio.to_thread(wav_ms, inp.voiceover) if state["joined"] and inp.voiceover else None,
        start_frame=state.get("frame"), start_source=state["source"], aspect_ratio=state["aspect"],
        width=facts.width if facts else None, height=facts.height if facts else None, duration_ms=facts.duration_ms if facts else None,
        size_bytes=len(state["final"]), seconds=inp.seconds, source=meta["source"], model=meta["model"], location=meta["location"],
        operation_id=meta["operation_id"], prompt=meta.get("prompt") or inp.prompt, negative_prompt=inp.negative_prompt,
        locked_regions=[r.model_dump() for r in inp.locked] if state.get("frame") and state["source"] != "asset" else [],
        checks=checks, limitations=list(dict.fromkeys(notes)), steps=steps,
    )
