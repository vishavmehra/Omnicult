"""Creative X-Ray: break an uploaded creative into scenes (run_type creative_xray, five stages).

probing_media -> extracting_media -> transcribing -> observing_frames -> structuring_scenes

Nothing is faked. A transcript comes from a `transcribe` capability or the uploader's own SRT/VTT sidecar, else it is
marked unavailable with the reason. Frames are described by the `vision` capability (images never go to a text model). One
`generate_structured` call proposes scenes from those observations; then code assigns the transcript by time, attaches
keyframes, and DROPS anything it cannot verify: on-screen text must appear in that scene's frame observations, a claim
must quote the scene's on-screen text or transcript, an observation must cite real frames or segments, an interpretation
must rest on an observation of its scene. Visual fields are discarded when vision did not run. Dropped counts are reported.
Workflows are pure: media work and storage go through `deps.media`; persistence is the engine's (app/services/xray.py).
"""

import asyncio
import time
from collections.abc import Sequence
from typing import Any, TypedDict
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from app.agents import xray as agent
from app.core.errors import NotFound, ValidationFailed
from app.llm.gateway import LLMError
from app.media.ffmpeg import MediaProcessingFailed, MediaToolMissing
from app.media.types import PreparedFrame, PreparedMedia
from app.schemas.assets import AssetKind, VisionStatus, VisualObservation
from app.schemas.common import StepTrace
from app.schemas.runs import RunError
from app.schemas.xray import (
    SCENE_PROVENANCE,
    AdClaim,
    MediaProbe,
    OnScreenText,
    Provenance,
    SceneInterpretation,
    SceneObservation,
    TranscribeStatus,
    TranscriptSegment,
    normalise,
)
from app.workflows._common import (
    DEMO_RUN_NOTE,
    DEMO_UPLOADS_MESSAGE,
    NO_VISION_MESSAGE,
    execute,
    linear_graph,
    llm_error,
    local_step,
    merge_steps,
    outcome_status,
)
from app.workflows.types import OutcomeStatus, ProgressFn, WorkflowContext, WorkflowDeps

RUN = "creative_xray"
STAGES = ("probing_media", "extracting_media", "transcribing", "observing_frames", "structuring_scenes")
S1, S2, S3, S4, S5 = STAGES
AGENT = "cultural_xray"
PROVIDER = "nativeproof"
VISION_CONCURRENCY = 4
VISION_GIVE_UP_AFTER = 2  # provider failures before any keyframe succeeded; the rest are skipped instead of each waiting out a deadline
PROVIDER_DOWN = frozenset({"PROVIDER_TIMEOUT", "PROVIDER_ERROR"})
SKIPPED_FRAME = "Skipped: the vision provider failed on the earlier keyframes."
MAX_SEGMENTS = 300
PROMPT_TRANSCRIPT_CHARS = 12_000  # what the model is shown of a transcript or of the uploader's notes
PROMPT_NOTES_CHARS = 4_000
NO_TRANSCRIBE = "No transcription capability is configured on this server, and no SRT or VTT sidecar was uploaded. The transcript is unavailable; nothing was invented."
INTERPRETATION_NOTE = "A model's cultural reading. It is not an observed fact; confirm it with people from the region."
DEMO_FIXTURE_NOTE = "Demo fixtures do not cover Creative X-Ray; the scenes below are keyframe timings only."
RESOLUTION = {  # the MediaError -> RunError mapping
    MediaToolMissing: ("PROVIDER_NOT_CONFIGURED", False),
    ValidationFailed: ("RUN_FAILED", False),
    MediaProcessingFailed: ("RUN_FAILED", True),
    NotFound: ("RUN_FAILED", False),
}


class XRayInput(BaseModel):
    context: WorkflowContext
    creative_asset_id: UUID
    campaign_id: UUID
    asset_id: UUID
    kind: AssetKind
    region_code: str | None = None
    region_name: str | None = None
    language: str | None = None


class FrameOut(BaseModel):
    id: str
    timestamp_ms: int
    asset_id: UUID | None
    observations: list[VisualObservation]


class SceneDraft(BaseModel):
    """A verified scene, ready to store (identity and keyframe URL are added by the service)."""

    id: UUID
    position: int
    start_ms: int
    end_ms: int | None
    keyframe_asset_id: UUID | None
    frame_ms: list[int]
    on_screen_text: list[OnScreenText]
    transcript: list[TranscriptSegment]
    people: list[str]
    gestures: list[str]
    setting: str | None
    objects: list[str]
    colours: list[str]
    music_mood: str | None
    claims: list[AdClaim]
    cultural_observations: list[SceneObservation]
    cultural_interpretations: list[SceneInterpretation]
    provenance: dict[str, Provenance]
    limitations: list[str]


class XRayOutcome(BaseModel):
    status: OutcomeStatus
    probe: MediaProbe | None
    transcribe: TranscribeStatus
    vision: VisionStatus
    frames: list[FrameOut]
    transcript: list[TranscriptSegment]
    sidecar_notes: str | None
    scenes: list[SceneDraft]
    dropped: dict[str, int]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None


class State(TypedDict, total=False):
    inp: XRayInput
    probe: MediaProbe
    prepared: PreparedMedia
    transcribe: TranscribeStatus
    transcript: list[TranscriptSegment]
    music_mood: str | None
    vision: VisionStatus
    observations: dict[str, list[VisualObservation]]
    scenes: list[SceneDraft]
    dropped: dict[str, int]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


# --- deterministic checks (pure, tested without a model) ------------------------------------------------


def _clean(items: Sequence[str], limit: int, width: int = 160) -> list[str]:
    seen: dict[str, str] = {}
    for item in items:
        text = " ".join(str(item).split())[:width]
        if text:
            seen.setdefault(text.casefold(), text)
    return list(seen.values())[:limit]


def _segments_in(transcript: list[TranscriptSegment], start: int, end: int | None, last: bool) -> list[TranscriptSegment]:
    """Timed segments whose midpoint falls in the scene. Untimed segments belong to no scene."""
    picked = []
    for seg in transcript:
        if seg.start_ms is None or seg.end_ms is None:
            continue
        mid = (seg.start_ms + seg.end_ms) / 2
        if mid >= start and (end is None or mid < end or (last and mid <= end)):
            picked.append(seg)
    return picked


def _frames_in(frames: list[PreparedFrame], start: int, end: int | None) -> list[PreparedFrame]:
    inside = [f for f in frames if f.timestamp_ms >= start and (end is None or f.timestamp_ms < end)]
    if inside or not frames:
        return inside
    middle = start if end is None else (start + end) / 2  # a scene between two keyframes borrows the nearest one
    return [min(frames, key=lambda f: abs(f.timestamp_ms - middle))]


def scene_bounds(
    drafts: Sequence[agent.SceneOut], kind: str, duration_ms: int | None, dropped: dict[str, int]
) -> list[tuple[int, int | None, agent.SceneOut | None]]:
    """Ordered, non-overlapping (start, end, draft) inside the creative. Invalid scenes are dropped and counted."""
    if kind == "image" or not duration_ms:
        if kind == "image" and len(drafts) > 1:
            dropped["extra_scenes"] = len(drafts) - 1
        return [(0, None, drafts[0] if drafts else None)]
    bounds: list[tuple[int, int | None, agent.SceneOut | None]] = []
    ordered = sorted(drafts, key=lambda d: d.start_ms)
    cursor = 0
    for index, draft in enumerate(ordered):
        start = max(draft.start_ms, cursor)
        following = ordered[index + 1].start_ms if index + 1 < len(ordered) else duration_ms
        end = min(draft.end_ms if draft.end_ms is not None else following, duration_ms)
        if start >= duration_ms or end <= start:
            dropped["scene_times"] = dropped.get("scene_times", 0) + 1
            continue
        bounds.append((start, end, draft))
        cursor = end
    return bounds


def skeleton_bounds(kind: str, duration_ms: int | None, frames: list[PreparedFrame]) -> list[tuple[int, int | None, None]]:
    """Timing-only scenes from the keyframes (video), or one scene (image, audio)."""
    if kind == "image" or not duration_ms:
        return [(0, None, None)]
    if kind == "audio" or not frames:
        return [(0, duration_ms, None)]
    starts = [0, *[f.timestamp_ms for f in frames[1:]]]
    ends = [*starts[1:], duration_ms]
    return [(start, end, None) for start, end in zip(starts, ends) if end > start]


def build_scenes(
    drafts: Sequence[agent.SceneOut] | None, *, kind: str, duration_ms: int | None, frames: list[PreparedFrame],
    observations: dict[str, list[VisualObservation]], transcript: list[TranscriptSegment], music_mood: str | None,
    visual_ok: bool,
) -> tuple[list[SceneDraft], dict[str, int], list[str]]:
    """Verified scenes, what was dropped (by kind), and limitations. `drafts=None` builds timing-only scenes."""
    dropped: dict[str, int] = {}
    notes: list[str] = []
    bounds: list[tuple[int, int | None, agent.SceneOut | None]]
    if drafts:
        bounds = scene_bounds(drafts, kind, duration_ms, dropped)
        if not bounds:
            bounds = skeleton_bounds(kind, duration_ms, frames)  # type: ignore[assignment]
            notes.append("The model returned no scene with valid times; these scenes are keyframe timings only.")
    else:
        bounds = skeleton_bounds(kind, duration_ms, frames)  # type: ignore[assignment]
        if drafts is not None:
            notes.append("The model returned no scenes; these scenes are keyframe timings only.")
    # a frame that no vision model described is not evidence for anything
    described = {f.frame_id for f in frames if observations.get(f.frame_id)} if visual_ok else set()
    valid_handles = {s.id for s in transcript} | described
    scenes: list[SceneDraft] = []
    for position, (start, end, draft) in enumerate(bounds):
        last = position == len(bounds) - 1
        in_frames = _frames_in(frames, start, end)
        segments = _segments_in(transcript, start, end, last)
        limits: list[str] = []
        texts: list[OnScreenText] = []
        claims: list[AdClaim] = []
        observed: list[SceneObservation] = []
        readings: list[SceneInterpretation] = []
        lists: dict[str, list[str]] = {"people": [], "gestures": [], "objects": [], "colours": []}
        setting: str | None = None
        if draft is not None:
            if visual_ok:
                for quote in draft.on_screen_text:
                    needle = normalise(quote)
                    hit = next(
                        (f for f in in_frames if needle and any(needle in normalise(o.description) for o in observations.get(f.frame_id, []))),
                        None,
                    )
                    if hit is None:
                        dropped["on_screen_text"] = dropped.get("on_screen_text", 0) + 1
                    elif all(normalise(t.text) != needle for t in texts):
                        texts.append(OnScreenText(text=" ".join(quote.split()), frame_ms=hit.timestamp_ms))
                lists = {"people": _clean(draft.people, 8), "gestures": _clean(draft.gestures, 8),
                         "objects": _clean(draft.objects, 12), "colours": _clean(draft.colours, 8)}
                setting = _clean([draft.setting or ""], 1, 200)[0] if draft.setting and draft.setting.strip() else None
            elif draft.on_screen_text or draft.people or draft.gestures or draft.objects or draft.colours or draft.setting:
                dropped["visual_fields_without_vision"] = dropped.get("visual_fields_without_vision", 0) + 1
                limits.append("Visual details were discarded: no vision model described the keyframes.")
            for claim in draft.claims:
                needle = normalise(claim.quote)
                if not needle:
                    continue
                if any(needle in normalise(t.text) for t in texts):
                    claims.append(AdClaim(text=" ".join(claim.quote.split()), source="on_screen_text", segment_id=None))
                    continue
                seg = next((s for s in segments if needle in normalise(s.text)), None)
                if seg is not None:
                    claims.append(AdClaim(text=" ".join(claim.quote.split()), source="transcript", segment_id=seg.id))
                else:
                    dropped["claims"] = dropped.get("claims", 0) + 1
            by_ref: dict[str, str] = {}
            for n, obs in enumerate(draft.observations, 1):
                evidence = [h for h in dict.fromkeys(obs.evidence) if h in valid_handles]
                if not evidence or not obs.text.strip():
                    dropped["cultural_observations"] = dropped.get("cultural_observations", 0) + 1
                    continue
                oid = f"o{position + 1}.{n}"
                by_ref[obs.ref.strip().lower()] = oid
                observed.append(SceneObservation(id=oid, text=" ".join(obs.text.split()), category=obs.category, evidence=evidence))
            for n, reading in enumerate(draft.interpretations, 1):
                basis = [by_ref[r.strip().lower()] for r in dict.fromkeys(reading.based_on) if r.strip().lower() in by_ref]
                if not basis or not reading.text.strip():
                    dropped["cultural_interpretations"] = dropped.get("cultural_interpretations", 0) + 1
                    continue
                readings.append(SceneInterpretation(
                    id=f"i{position + 1}.{n}", text=" ".join(reading.text.split()), based_on=basis, category=reading.category,
                    limitations=[INTERPRETATION_NOTE],
                ))
        else:
            limits.append("Timing and transcript only: the scene content was not analysed.")
        first = in_frames[0] if in_frames else None
        scenes.append(SceneDraft(
            id=uuid4(), position=position, start_ms=start, end_ms=end, keyframe_asset_id=first.asset_id if first else None,
            frame_ms=[f.timestamp_ms for f in in_frames], on_screen_text=texts, transcript=segments, people=lists["people"],
            gestures=lists["gestures"], setting=setting, objects=lists["objects"], colours=lists["colours"],
            music_mood=music_mood, claims=claims, cultural_observations=observed, cultural_interpretations=readings,
            provenance=dict(SCENE_PROVENANCE), limitations=limits,
        ))
    dropped = {k: v for k, v in dropped.items() if v}
    return scenes, dropped, notes


# --- stages ---------------------------------------------------------------------------------------------


async def _announce(config: RunnableConfig, index: int, message: str) -> None:
    progress = config["configurable"].get("progress")
    if progress is not None:
        if config["configurable"]["mode"] == "demo":
            message = message.rstrip(".") + " (demo fixtures)."
        await progress(STAGES[index], index, len(STAGES), message)


def _media_error(exc: Exception, stage: str) -> RunError:
    code, retryable = next((v for t, v in RESOLUTION.items() if isinstance(exc, t)), ("RUN_FAILED", True))
    message = getattr(exc, "message", None) or str(exc) or "The media could not be processed."
    return RunError(code=code, message=f"{message} No scenes were saved.", stage=stage, retryable=retryable)  # type: ignore[arg-type]


async def probing_media(state: State, config: RunnableConfig) -> dict:
    await _announce(config, 0, "Reading the media file.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    try:
        probe = await deps.media.probe(inp.asset_id)
    except (MediaToolMissing, ValidationFailed, MediaProcessingFailed, NotFound) as exc:
        return {"error": _media_error(exc, S1), "stop": True,
                "steps": [local_step(S1, AGENT, PROVIDER, started, status="failed", error_code="RUN_FAILED")]}
    return {"probe": probe, "steps": [local_step(S1, AGENT, PROVIDER, started)]}


async def extracting_media(state: State, config: RunnableConfig) -> dict:
    await _announce(config, 1, "Extracting keyframes and audio.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    try:
        prepared = await deps.media.extract(inp.asset_id)
    except (MediaToolMissing, ValidationFailed, MediaProcessingFailed, NotFound) as exc:
        return {"error": _media_error(exc, S2), "stop": True,
                "steps": [*state["steps"], local_step(S2, AGENT, PROVIDER, started, status="failed", error_code="RUN_FAILED")]}
    return {"prepared": prepared, "steps": [*state["steps"], local_step(S2, AGENT, PROVIDER, started)]}


def _capability(deps: WorkflowDeps, name: str) -> Any | None:
    direct = getattr(deps, name, None)
    if direct is not None:
        return direct
    try:
        return deps.llm.capability(name)
    except Exception:  # the gateway has no adapter of this name yet: the capability is simply unavailable
        return None


def _segments_from(result: Any, language: str | None) -> list[TranscriptSegment]:
    out: list[TranscriptSegment] = []
    for raw in list(getattr(result, "segments", []) or [])[:MAX_SEGMENTS]:
        get = (lambda k, r=raw: r.get(k)) if isinstance(raw, dict) else (lambda k, r=raw: getattr(r, k, None))
        text = " ".join(str(get("text") or "").split())[:500]
        if not text:
            continue

        def ms(value: Any) -> int | None:
            return round(float(value)) if isinstance(value, (int, float)) and value >= 0 else None

        out.append(TranscriptSegment(
            id=f"t{len(out) + 1}", start_ms=ms(get("start_ms")), end_ms=ms(get("end_ms")), text=text, source="transcription",
            language=get("language") or language,
        ))
    return out


async def transcribing(state: State, config: RunnableConfig) -> dict:
    await _announce(config, 2, "Getting the transcript.")
    started, deps, inp, prepared = time.perf_counter(), config["configurable"]["deps"], state["inp"], state["prepared"]
    mode = config["configurable"]["mode"]
    steps = list(state["steps"])
    mood: str | None = None

    def done(status: TranscribeStatus, segments: list[TranscriptSegment], *, step: StepTrace | None = None, partial: bool = False) -> dict:
        note = [f"Transcript: {status.message}"] if status.message and status.status in ("unavailable", "failed") else []
        update: dict = {"transcribe": status, "transcript": segments, "music_mood": mood,
                        "steps": [*steps, step or local_step(S3, AGENT, PROVIDER, started, status="completed" if status.status in ("transcribed", "from_sidecar") else "skipped")],
                        "limitations": [*state.get("limitations", []), *note]}
        if status.status in ("unavailable", "failed") or partial:
            update["partial"] = True
        return update

    def status(value: str, message: str | None = None, provider: str | None = None, model: str | None = None) -> TranscribeStatus:
        return TranscribeStatus(status=value, provider=provider, model_id=model, message=message)  # type: ignore[arg-type]

    if inp.kind == "image":
        return done(status("not_applicable", "Images have no audio."), [])
    if prepared.sidecar_segments:
        segments = [
            TranscriptSegment(id=f"t{i}", start_ms=s["start_ms"], end_ms=s["end_ms"], text=s["text"], source="user_sidecar", language=inp.language)
            for i, s in enumerate(prepared.sidecar_segments[:MAX_SEGMENTS], 1)
        ]
        return done(status("from_sidecar", "The uploader's own SRT or VTT file; not a model transcription."), segments)
    if prepared.audio is None:
        return done(status("not_applicable", "The file has no audio track."), [])
    if mode == "demo":
        return done(status("unavailable", DEMO_UPLOADS_MESSAGE), [])
    capability = _capability(deps, "transcribe")
    if capability is None:
        return done(status("unavailable", NO_TRANSCRIBE), [])
    try:
        result = await capability.transcribe(
            prepared.audio.data, prepared.audio.content_type, language=inp.language, duration_ms=prepared.audio.duration_ms,
            stage=S3, agent="transcribe",
        )
    except LLMError as exc:
        return done(status("failed", exc.message, exc.trace.provider, exc.trace.model_id), [], step=exc.trace)
    reported = getattr(result, "status", None)
    reported_status = getattr(reported, "status", reported)
    provider, model = getattr(reported, "provider", None), getattr(reported, "model_id", None)
    trace = getattr(result, "trace", None)
    if reported_status != "transcribed":
        message = getattr(reported, "message", None) or "The transcription capability did not return a transcript."
        return done(status("unavailable" if reported_status == "unavailable" else "failed", message, provider, model), [], step=trace)
    mood = getattr(result, "music_mood", None)
    segments = _segments_from(result, inp.language)
    if not segments:
        return done(status("failed", "The transcription returned no text.", provider, model), [], step=trace)
    return done(status("transcribed", None, provider, model), segments, step=trace)


async def observing_frames(state: State, config: RunnableConfig) -> dict:
    await _announce(config, 3, "Describing keyframes.")
    started, deps, inp, prepared = time.perf_counter(), config["configurable"]["deps"], state["inp"], state["prepared"]
    mode = config["configurable"]["mode"]
    notes = list(state.get("limitations", []))
    steps = list(state["steps"])
    if not prepared.frames:
        status = VisionStatus(status="not_requested", provider=None, model_id=None, message="Audio has no frames to describe.")
        return {"vision": status, "observations": {}, "steps": [*steps, local_step(S4, "vision", None, started, status="skipped")]}
    if mode == "demo" or deps.vision is None:
        message = DEMO_UPLOADS_MESSAGE if mode == "demo" else NO_VISION_MESSAGE
        status = VisionStatus(status="unavailable", provider=None, model_id=None, message=message)
        return {"vision": status, "observations": {}, "partial": True, "limitations": [*notes, f"Vision: {message}"],
                "steps": [*steps, local_step(S4, "vision", None, started, status="skipped")]}
    gate = asyncio.Semaphore(VISION_CONCURRENCY)
    total, finished, ok, down = len(prepared.frames), 0, 0, 0

    async def one(frame: PreparedFrame) -> tuple[PreparedFrame, VisionStatus, list[VisualObservation], StepTrace | None]:
        nonlocal finished, ok, down
        async with gate:
            if down >= VISION_GIVE_UP_AFTER and not ok:  # the provider is down: do not spend a deadline per frame
                outcome = (frame, VisionStatus(status="failed", provider=None, model_id=None, message=SKIPPED_FRAME), [], None)
            else:
                try:
                    result = await deps.vision.observe(
                        frame.asset_id or inp.asset_id, frame.data, frame.content_type, stage=S4, agent="vision")
                    outcome = (frame, result.status, list(result.observations), result.trace)
                except LLMError as exc:  # the gateway deadline expired; the frame never goes to a text model instead
                    failed = VisionStatus(status="failed", provider=exc.trace.provider, model_id=exc.trace.model_id, message=exc.message)
                    outcome = (frame, failed, [], exc.trace)
        finished += 1
        ok += outcome[1].status == "analyzed"
        down += outcome[3] is not None and outcome[3].error_code in PROVIDER_DOWN
        await _announce(config, 3, f"Describing keyframes ({finished} of {total} done).")
        return outcome

    results = await asyncio.gather(*(one(f) for f in prepared.frames))
    observations = {frame.frame_id: obs for frame, _, obs, _ in results}
    statuses = [status for _, status, _, _ in results]
    analysed = [s for s in statuses if s.status == "analyzed"]
    traces = [t for *_, t in results if t is not None]
    failed = len(statuses) - len(analysed)
    overall = analysed[0] if analysed else next((s for s in statuses if s.message != SKIPPED_FRAME), statuses[-1])
    update: dict = {"vision": overall, "observations": observations,
                    "steps": [*steps, merge_steps(S4, "vision", traces, started) if traces else local_step(S4, "vision", None, started, status="skipped")]}
    if failed:
        update["partial"] = True
        update["limitations"] = [*notes, f"Vision: {failed} of {len(statuses)} keyframes could not be described"
                                 + (f" ({overall.message})." if not analysed and overall.message else ".")]
    return update


def _prompt_transcript(transcript: list[TranscriptSegment]) -> tuple[list[dict], int]:
    """Segments for the prompt (whole segments only, in order, within PROMPT_TRANSCRIPT_CHARS) and how many were left out."""
    shown: list[dict] = []
    used = 0
    for seg in transcript:
        used += len(seg.text)
        if used > PROMPT_TRANSCRIPT_CHARS:
            break
        shown.append(seg.model_dump(include={"id", "start_ms", "end_ms", "text", "source"}))
    return shown, len(transcript) - len(shown)


def _prompt_frames(prepared: PreparedMedia, observations: dict[str, list[VisualObservation]]) -> list[dict]:
    return [
        {"id": f.frame_id, "at_ms": f.timestamp_ms,
         "observations": [{"kind": o.kind, "description": o.description, "location": o.location} for o in observations.get(f.frame_id, [])]}
        for f in prepared.frames
    ]


async def structuring_scenes(state: State, config: RunnableConfig) -> dict:
    await _announce(config, 4, "Building the scene list.")
    started, deps, inp, prepared = time.perf_counter(), config["configurable"]["deps"], state["inp"], state["prepared"]
    steps, notes = list(state["steps"]), list(state.get("limitations", []))
    observations, transcript = state.get("observations", {}), state.get("transcript", [])
    probe = state["probe"]
    vision_ok = state["vision"].status == "analyzed" and any(observations.get(f.frame_id) for f in prepared.frames)
    kwargs = dict(kind=inp.kind, duration_ms=probe.duration_ms, frames=prepared.frames, observations=observations,
                  transcript=transcript, music_mood=state.get("music_mood"), visual_ok=vision_ok)
    shown, left_out = _prompt_transcript(transcript)
    notes_text = prepared.sidecar_notes[:PROMPT_NOTES_CHARS] if prepared.sidecar_notes else None
    if left_out:
        notes.append(f"The model was shown the first {len(shown)} of {len(transcript)} transcript segments; the rest was too long to send.")
    if prepared.sidecar_notes and len(prepared.sidecar_notes) > PROMPT_NOTES_CHARS:
        notes.append(f"The model was shown the first {PROMPT_NOTES_CHARS} characters of the uploader's notes.")
    has_material = vision_ok or bool(transcript) or bool(prepared.sidecar_notes)
    update: dict[str, Any] = {}
    drafts = None
    trace: StepTrace | None = None
    if not has_material and not deps.llm.is_fixture:  # a fixture model is the demo's: it is asked, and may have an answer
        notes.append("No keyframe observations, transcript, or notes were available, so the scenes hold timing only.")
        update["partial"] = True
    else:
        try:
            result = await agent.structure_scenes(
                deps.llm, stage=S5,
                creative={"kind": inp.kind, "duration_ms": probe.duration_ms, "target_region": inp.region_name or inp.region_code,
                          "declared_language": inp.language, "has_audio": probe.has_audio},
                frames=_prompt_frames(prepared, observations), transcript=shown, notes=notes_text, tags=prepared.container_tags,
            )
            drafts, trace = result.value.scenes, result.trace
        except LLMError as exc:
            trace = exc.trace
            update["partial"] = True
            if deps.llm.is_fixture:
                notes.append(DEMO_FIXTURE_NOTE)
            else:
                update["error"] = llm_error(exc, S5, "Keyframe observations and the keyframes were saved; scenes hold timing only.")
    scenes, dropped, extra = build_scenes(drafts, **kwargs)  # type: ignore[arg-type]
    if extra:
        update["partial"] = True
    if dropped:
        notes.append("Items the model produced that could not be verified were removed: "
                     + ", ".join(f"{count} {kind.replace('_', ' ')}" for kind, count in dropped.items()) + ".")
    step = trace or local_step(S5, AGENT, PROVIDER, started, status="skipped")
    return update | {"scenes": scenes, "dropped": dropped, "limitations": [*notes, *extra], "steps": [*steps, step]}


GRAPH = linear_graph(State, [
    (S1, probing_media), (S2, extracting_media), (S3, transcribing), (S4, observing_frames), (S5, structuring_scenes),
])


async def run_creative_xray(inp: XRayInput, deps: WorkflowDeps, progress: ProgressFn | None = None) -> XRayOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": [], "dropped": {}}, deps, progress, inp.context.mode)
    prepared: PreparedMedia | None = state.get("prepared")
    observations = state.get("observations", {})
    unavailable = VisionStatus(status="not_requested", provider=None, model_id=None, message=None)
    demo = [DEMO_RUN_NOTE] if inp.context.mode == "demo" else []
    return XRayOutcome(
        status=outcome_status(state), probe=state.get("probe"),
        transcribe=state.get("transcribe") or TranscribeStatus(status="not_applicable", provider=None, model_id=None, message=None),
        vision=state.get("vision") or unavailable,
        frames=[FrameOut(id=f.frame_id, timestamp_ms=f.timestamp_ms, asset_id=f.asset_id, observations=observations.get(f.frame_id, []))
                for f in (prepared.frames if prepared else [])],
        transcript=state.get("transcript", []), sidecar_notes=prepared.sidecar_notes if prepared else None,
        scenes=state.get("scenes", []), dropped=state.get("dropped", {}),
        limitations=list(dict.fromkeys([*demo, *state.get("limitations", [])])), steps=state.get("steps", []), error=state.get("error"),
    )
