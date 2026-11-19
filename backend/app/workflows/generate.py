"""Generate studio workflows: `generate_image`, `generate_voice` and `generate_jingle`, four stages each.

Image: loading_brief -> generating_image -> compositing -> checking_output.
Voice: loading_lines -> speaking_lines -> assembling_track -> checking_timings.
Jingle: loading_brief -> composing_jingle -> shaping_clip -> checking_clip.

Pure: no database. Media goes in as bytes (the service loads the Brand Kit images) and comes out as bytes. Model calls go
only through the gateway's capability adapters (`image_generation`, `tts`, `music`), each metered and budget-checked, each
called at most once per output with no app-level retry. In demo mode no provider is called: the saved demonstration
inputs are used and everything else (compositing, lettering, pace, trimming, timings, checks) still runs in code.
A provider failure ends the run with its own error, kept on the run so the studio shows it.
"""

import asyncio
import io
import time
import wave
from typing import Any, Literal, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from PIL import Image
from pydantic import BaseModel

from app.core.errors import UnsupportedCapability, ValidationFailed
from app.fixtures import generate_demo as demo
from app.fixtures import remake_demo
from app.llm.gateway import LLMError
from app.llm.media import ASPECT_RATIOS, LANGUAGE_CODES, MAX_MUSIC_PROMPT_CHARS
from app.media import generate as media
from app.media import remake as pipeline
from app.media import textrender
from app.schemas import generate as g
from app.schemas.common import StepTrace
from app.schemas.runs import RunError
from app.workflows._common import STAGES, announce, execute, linear_graph, llm_error, local_step
from app.workflows.types import OutcomeStatus, WorkflowContext, WorkflowDeps

IMAGE, VOICE, JINGLE = "generate_image", "generate_voice", "generate_jingle"
I1, I2, I3, I4 = STAGES[IMAGE]
V1, V2, V3, V4 = STAGES[VOICE]
J1, J2, J3, J4 = STAGES[JINGLE]
IMAGE_PROMPT_VERSION = "generate-image-v2"
VOICE_PROMPT_VERSION = "generate-voice-v1"
JINGLE_PROMPT_VERSION = "generate-jingle-v1"
REFERENCE_DROPPED_NOTE = ("The Brand Kit product image was not sent to the model as a reference: the real product is placed in code, and a "
                          "reference showing the pack makes the model draw its own as well. Turn the product placement off to use it as a reference.")
INTERPRETATION_NOTE = "The scene is a model interpretation. Confirm props, symbols and styling with someone from the region."
UNREVIEWED_NOTE = "No native speaker has reviewed this audio; a code check cannot tell whether the pronunciation is right."
MUSIC_NOTE = "The music is a model interpretation of the hints; listen before using it, and check the rights position of AI music for your use."
GAP_MS = 450


class BrandPicture(BaseModel):
    id: str
    label: str
    asset_id: UUID | None = None
    data: bytes


class BrandBrief(BaseModel):
    """What the generators read from the Brand Kit and the brief. Everything is optional: a thin kit still generates."""

    tone: list[str] = []
    colours: list[tuple[str, str]] = []  # (name, hex)
    logos: list[BrandPicture] = []
    product: BrandPicture | None = None
    product_asset_ids: list[UUID] = []  # every Brand Kit product image, whichever one is placed
    logo_min_px: int = media.DEFAULT_LOGO_MIN_PX
    product_name: str | None = None
    objective: str | None = None
    primary_message: str | None = None
    festival_hook: str | None = None


class ClaimIn(BaseModel):
    id: UUID
    handle: str
    category: str
    statement: str


class GenerateImageInput(BaseModel):
    context: WorkflowContext
    request: g.GenerateImageRequest
    region_name: str
    language_name: str
    script: str
    brand: BrandBrief
    reference: bytes | None = None
    reference_asset_id: UUID | None = None
    claims: list[ClaimIn] = []


class GenerateImageOutcome(BaseModel):
    status: OutcomeStatus
    scene: bytes | None = None
    scene_mime: str = "image/png"
    composite: bytes | None = None
    width: int = 0
    height: int = 0
    engine: str | None = None
    source: Literal["provider", "demo_fixture"] = "provider"
    model: str | None = None
    location: str | None = None
    prompt: str | None = None
    placements: list[dict[str, Any]] = []
    headline: dict[str, Any] | None = None
    checks: list[dict[str, Any]] = []
    palette: list[str] = []
    limitations: list[str] = []
    reference_dropped: bool = False  # the reference was the Brand Kit pack while the real product was placed, so it was not sent
    steps: list[StepTrace] = []
    error: RunError | None = None


class VoiceLine(BaseModel):
    text: str
    language: str
    back_translation: str | None = None


class GenerateVoiceInput(BaseModel):
    context: WorkflowContext
    request: g.GenerateVoiceRequest
    region_name: str
    language_name: str
    lines: list[VoiceLine]
    max_lines: int = g.MAX_VOICE_LINES


class GenerateVoiceOutcome(BaseModel):
    status: OutcomeStatus
    track: bytes | None = None
    source: Literal["provider", "demo_fixture"] = "provider"
    voice: str | None = None
    pace_applied: bool = False
    language_code: str | None = None
    model: str | None = None
    location: str | None = None
    total_duration_ms: int = 0
    lines: list[dict[str, Any]] = []
    peaks: list[int] = []
    limitations: list[str] = []
    steps: list[StepTrace] = []
    error: RunError | None = None


class GenerateJingleInput(BaseModel):
    context: WorkflowContext
    request: g.GenerateJingleRequest
    region_name: str


class GenerateJingleOutcome(BaseModel):
    status: OutcomeStatus
    clip: bytes | None = None
    source: Literal["provider", "demo_fixture"] = "provider"
    model: str | None = None
    location: str | None = None
    prompt: str | None = None
    generated_seconds: float = 0.0
    duration_ms: int = 0
    sample_rate: int = 0
    channels: int = 0
    peaks: list[int] = []
    limitations: list[str] = []
    steps: list[StepTrace] = []
    error: RunError | None = None


def _fail(state: dict, error: RunError, trace: StepTrace | None = None) -> dict:
    return {"steps": [*state.get("steps", []), *([trace] if trace else [])], "error": error, "stop": True}


def _mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return "image/webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else "image/png"


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG")
    return out.getvalue()


# --- image ------------------------------------------------------------------------------------------------------


PURPOSE_PHRASE = {"key_visual": "campaign key visual", "social_post": "social media post image"}


def image_prompt(inp: GenerateImageInput, *, has_reference: bool) -> str:
    """The exact prompt for the image model. Pure, so a test can read it. It carries the person's idea, the brief and the Brand
    Kit as direction, never as facts about the region, and asks for clear space instead of lettering or a logo."""
    r, brand = inp.request, inp.brand
    parts = [
        f"Create a {PURPOSE_PHRASE[r.purpose]}{f' for {brand.product_name}' if brand.product_name else ''} for an audience in "
        f"{inp.region_name} ({inp.language_name}), in a {r.format} frame.",
        f"Creative direction written by the campaign owner: {r.idea}",
    ]
    if brand.objective:
        parts.append(f"Campaign objective: {brand.objective}")
    if brand.primary_message:
        parts.append(f"Message the picture should support: {brand.primary_message}")
    if brand.festival_hook:
        parts.append(f"Festival hook from the brief: {brand.festival_hook}")
    if r.use_brand_colours and brand.colours:
        parts.append("Brand palette to lean on: " + ", ".join(f"{name} {hexa}" for name, hexa in brand.colours[:6]) + ".")
    if brand.tone:
        parts.append("Brand tone: " + ", ".join(brand.tone[:6]) + ".")
    space = []
    if r.include_logo:
        space.append("the top-left corner for a logo")
    if r.headline:
        space.append("a calm band near the top for a headline")
    if r.include_product:
        space.append("the bottom-right for the product pack")
    if space:
        avoid = ["a logo", "any lettering", *(["any tin, jar, box, bottle or packaging of any kind"] if r.include_product else [])]
        parts.append("Keep " + ", ".join(space) + f" calm and uncluttered: those are added afterwards. Do not draw {', '.join(avoid[:-1])} or {avoid[-1]}.")
    if has_reference:
        parts.append("The attached image is a reference for look, colour and styling only. Do not copy it into the scene.")
    if inp.claims:
        notes = "; ".join(c.statement[:160] for c in inp.claims[:5])
        parts.append(f"Sourced regional notes (use one only where it fits naturally; never invent customs beyond them): {notes}")
    parts.append("Photographic and realistic, natural light.")
    return " ".join(parts)


class IState(TypedDict, total=False):
    inp: GenerateImageInput
    demo: bool
    client: Any
    prompt: str
    scene_fixture: Any
    reference: bytes | None
    reference_dropped: bool
    scene: bytes
    scene_mime: str
    meta: dict[str, Any]
    composite: Any
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool


def _decode(data: bytes) -> Image.Image:
    return textrender.load_image(data)


async def loading_brief(state: IState, config: RunnableConfig) -> dict:
    await announce(config, IMAGE, 0, "Reading the brief and the Brand Kit.")
    started, inp = time.perf_counter(), state["inp"]
    deps: WorkflowDeps = config["configurable"]["deps"]
    demo_mode = inp.context.mode == "demo"
    r = inp.request
    if r.format not in ASPECT_RATIOS or r.format not in media.FORMATS:
        return _fail(state, RunError(code="VALIDATION_ERROR", stage=I1, retryable=False, message="That format is not supported. Nothing was generated."))
    try:  # every picture is decoded before the paid call, so a bad file never wastes it
        for picture in [*inp.brand.logos, *([inp.brand.product] if inp.brand.product else [])]:
            await asyncio.to_thread(_decode, picture.data)
        if inp.reference:
            await asyncio.to_thread(_decode, inp.reference)
    except ValidationFailed as exc:
        return _fail(state, RunError(code="VALIDATION_ERROR", stage=I1, retryable=False, message=f"{exc.message} Nothing was generated."))
    if r.headline:
        foreign = pipeline.indic_scripts_in(r.headline) - {inp.script}
        if foreign:
            return _fail(state, RunError(code="VALIDATION_ERROR", stage=I1, retryable=False,
                                         message=f"The headline is in {', '.join(sorted(foreign))}, not {inp.script}. Write it in the "
                                                 "language's script. Nothing was generated."))
        needed = inp.script if inp.script in textrender.COMPLEX_SCRIPTS else None
        if needed and textrender.shaping_engine() != "raqm":  # before the paid call: unshaped script is never drawn
            return _fail(state, RunError(code="UNSUPPORTED_CAPABILITY", stage=I1, retryable=False,
                                         message=f"Text in {needed} cannot be rendered on this server (complex-script shaping is not "
                                                 "installed). Nothing was generated."))
        if inp.script in textrender.SCRIPT_FONTS and inp.script not in textrender.available_scripts():
            return _fail(state, RunError(code="UNSUPPORTED_CAPABILITY", stage=I1, retryable=False,
                                         message=f"The bundled font for {inp.script} is missing from this deployment. Nothing was generated."))
    # The real product is placed in code, so the Brand Kit pack is never also shown to the model: it would draw a second tin.
    dropped = (inp.reference is not None and r.include_product and inp.brand.product is not None and inp.reference_asset_id in inp.brand.product_asset_ids)
    reference = None if dropped else inp.reference
    prompt = image_prompt(inp, has_reference=reference is not None)
    update: dict[str, Any] = {"prompt": prompt, "demo": demo_mode, "reference": reference, "reference_dropped": dropped,
                              "limitations": [REFERENCE_DROPPED_NOTE] if dropped else [],
                              "steps": [local_step(I1, IMAGE, "omnicult", started)]}
    if demo_mode:
        fixture = demo.scene()
        if fixture is None:
            return _fail(state, RunError(code="UNSUPPORTED_CAPABILITY", stage=I1, retryable=False,
                                         message="This scene is not available on this server. Nothing was generated."))
        update["scene_fixture"] = fixture
    else:
        client = deps.llm.capability("image_generation")
        if client is None:
            return _fail(state, RunError(code="PROVIDER_NOT_CONFIGURED", stage=I1, retryable=False,
                                         message="No image model is configured on this server. Nothing was generated."))
        update["client"] = client
    return update


async def generating_image(state: IState, config: RunnableConfig) -> dict:
    await announce(config, IMAGE, 1, "Generating the scene.")
    inp, started = state["inp"], time.perf_counter()
    if state["demo"]:
        fixture = state["scene_fixture"]  # type: ignore[typeddict-item]
        trace = local_step(I2, IMAGE, "fixture", started).model_copy(update={"prompt_version": fixture.prompt_version})
        return {"scene": fixture.data, "scene_mime": fixture.mime_type, "steps": [*state["steps"], trace],
                "meta": {"source": "demo_fixture", "model": fixture.model, "location": fixture.location},
                "limitations": state["limitations"]}
    reference = state["reference"]
    try:  # one call, never retried by the app; the gateway's own bounded retry already ran
        image = await state["client"].generate(
            state["prompt"], reference_image=reference, reference_mime_type=_mime(reference) if reference else "image/png",
            aspect_ratio=inp.request.format, stage=I2, agent=IMAGE,
        )
    except LLMError as exc:
        return _fail(state, llm_error(exc, I2, "Nothing was saved."), exc.trace)
    return {"scene": image.image, "scene_mime": image.mime_type, "steps": [*state["steps"], image.trace],
            "meta": {"source": "provider", "model": image.model, "location": image.location},
            "limitations": [*state["limitations"], INTERPRETATION_NOTE]}


async def compositing(state: IState, config: RunnableConfig) -> dict:
    await announce(config, IMAGE, 2, "Placing the logo, the product and the headline in code.")
    inp, started = state["inp"], time.perf_counter()
    r, brand = inp.request, inp.brand

    def work() -> Any:
        scene = _decode(state["scene"])
        logos = [(p.id, _decode(p.data)) for p in brand.logos] if r.include_logo else []
        product = _decode(brand.product.data) if r.include_product and brand.product else None
        headline = {"text": r.headline, "language": inp.request.language} if r.headline else None
        return media.compose_image(scene, r.format, logo=logos, product=product, headline=headline, script=inp.script,
                                   language=inp.request.language, logo_min_px=brand.logo_min_px)

    try:
        composite = await asyncio.to_thread(work)
    except UnsupportedCapability as exc:
        return _fail(state, RunError(code="UNSUPPORTED_CAPABILITY", stage=I3, retryable=False, message=f"{exc.message} Nothing was saved."),
                     local_step(I3, IMAGE, "omnicult", started, status="failed", error_code="UNSUPPORTED_CAPABILITY"))
    except Exception:  # an image the model returned that cannot be decoded or drawn on
        return _fail(state, RunError(code="RUN_FAILED", stage=I3, retryable=True, message="The generated image could not be processed. Nothing was saved."),
                     local_step(I3, IMAGE, "omnicult", started, status="failed", error_code="RUN_FAILED"))
    return {"composite": composite, "steps": [*state["steps"], local_step(I3, IMAGE, "omnicult", started)]}


async def checking_output(state: IState, config: RunnableConfig) -> dict:
    await announce(config, IMAGE, 3, "Checking the finished image.")
    started, composite = time.perf_counter(), state["composite"]
    flagged = [c for c in composite.checks if not c["passed"]]
    notes = [f"{len(flagged)} of {len(composite.checks)} code checks were flagged; see the checks."] if flagged else []
    return {"limitations": [*state["limitations"], *notes], "steps": [*state["steps"], local_step(I4, IMAGE, "omnicult", started)]}


IMAGE_GRAPH = linear_graph(IState, [(I1, loading_brief), (I2, generating_image), (I3, compositing), (I4, checking_output)])


async def run_generate_image(inp: GenerateImageInput, deps: WorkflowDeps, progress: Any = None) -> GenerateImageOutcome:
    state = await execute(IMAGE_GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    steps, error, composite = state.get("steps", []), state.get("error"), state.get("composite")
    if error is not None or composite is None:
        return GenerateImageOutcome(status="failed", steps=steps, error=error, limitations=state.get("limitations", []), prompt=state.get("prompt"))
    meta = state["meta"]
    notes = [*state.get("limitations", [])]
    return GenerateImageOutcome(
        status="partial" if any(not c["passed"] for c in composite.checks) else "completed", scene=state["scene"], scene_mime=state["scene_mime"],
        composite=composite.png, width=composite.width, height=composite.height, engine=composite.engine, source=meta["source"],
        model=meta["model"], location=meta["location"], prompt=state["prompt"],
        placements=[{"kind": p.kind, "label": p.label, "bbox": p.bbox, "width_px": p.width_px} for p in composite.placements],
        headline=composite.headline, checks=composite.checks,
        palette=[h for _, h in inp.brand.colours[:6]] if inp.request.use_brand_colours else [],
        limitations=list(dict.fromkeys(notes)), steps=steps, reference_dropped=state["reference_dropped"],
    )


# --- voice ------------------------------------------------------------------------------------------------------


class VState(TypedDict, total=False):
    inp: GenerateVoiceInput
    demo: bool
    tts: Any
    clips: list[tuple[VoiceLine, Any, list[str]]]
    meta: dict[str, Any]
    track: bytes
    spans: list[tuple[int, int]]
    results: list[dict[str, Any]]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool


async def loading_lines(state: VState, config: RunnableConfig) -> dict:
    await announce(config, VOICE, 0, "Loading the lines.")
    started, inp = time.perf_counter(), state["inp"]
    deps: WorkflowDeps = config["configurable"]["deps"]
    demo_mode = inp.context.mode == "demo"
    if not inp.lines or len(inp.lines) > inp.max_lines:
        return _fail(state, RunError(code="VALIDATION_ERROR", stage=V1, retryable=False,
                                     message=f"A voice-over has 1 to {inp.max_lines} lines. Nothing was generated."))
    if inp.request.pace != "normal" and not media.can_retime():
        return _fail(state, RunError(code="UNSUPPORTED_CAPABILITY", stage=V1, retryable=False,
                                     message="This server cannot change the pace of audio (ffmpeg is not installed). Nothing was generated."))
    update: dict[str, Any] = {"demo": demo_mode, "steps": [local_step(V1, VOICE, "omnicult", started)], "limitations": [UNREVIEWED_NOTE]}
    if not demo_mode:
        client = deps.llm.capability("tts")
        if client is None:
            return _fail(state, RunError(code="PROVIDER_NOT_CONFIGURED", stage=V1, retryable=False,
                                         message="No speech model is configured on this server. Nothing was generated."))
        update["tts"] = client
    return update


async def speaking_lines(state: VState, config: RunnableConfig) -> dict:
    await announce(config, VOICE, 1, "Speaking the lines.")
    inp, steps = state["inp"], list(state["steps"])
    clips: list[tuple[VoiceLine, Any, list[str]]] = []
    meta: dict[str, Any] = {}
    stopped: LLMError | None = None
    first_failure: LLMError | None = None
    for line in inp.lines:
        problems: list[str] = []
        audio: Any = None
        if stopped is not None:
            problems.append("Not spoken: an earlier line stopped the run.")
        elif line.language not in LANGUAGE_CODES:
            problems.append(f"The speech model does not support {line.language}.")
        elif state["demo"]:
            audio = remake_demo.speech_clip(line.language, line.text, inp.request.voice)
            if audio is None:
                problems.append("This exact line and voice is not available in the demo.")
            else:
                meta = {"source": "demo_fixture", "model": audio.model, "location": audio.location, "voice": audio.voice,
                        "language_code": audio.language_code}
        else:
            try:
                audio = await state["tts"].synthesize(line.text, language=line.language, voice=inp.request.voice, stage=V2, agent=VOICE)
            except LLMError as exc:
                steps.append(exc.trace)
                problems.append(exc.message)
                first_failure = first_failure or exc
                if exc.code in ("BUDGET_EXCEEDED", "PROVIDER_NOT_CONFIGURED"):
                    stopped = exc  # nothing more is attempted
            else:
                steps.append(audio.trace)
                meta = {"source": "provider", "model": audio.model, "location": "global", "voice": audio.voice, "language_code": audio.language_code}
        clips.append((line, audio, problems))
    if not any(a is not None for _, a, _ in clips):
        first = next((p for _, _, ps in clips for p in ps), "No line could be spoken.")
        failure = stopped or first_failure
        code = failure.code if failure is not None else "RUN_FAILED"
        retryable = failure.retryable if failure is not None else False
        return {"clips": clips, "steps": steps, "stop": True,
                "error": RunError(code=code, stage=V2, retryable=retryable, message=f"{first} Nothing was saved.")}  # type: ignore[arg-type]
    return {"clips": clips, "meta": meta, "steps": steps}


async def assembling_track(state: VState, config: RunnableConfig) -> dict:
    await announce(config, VOICE, 2, "Joining the lines into one track.")
    inp, started = state["inp"], time.perf_counter()
    spoken = [(line, audio) for line, audio, _ in state["clips"] if audio is not None]
    tempo = media.PACE_TEMPO[inp.request.pace]
    try:
        wavs = await media.retime_all([a.wav for _, a in spoken], tempo)
        track, spans = pipeline.concat_wavs(wavs, GAP_MS)
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else "The speech could not be joined into one track."
        return _fail(state, RunError(code="RUN_FAILED", stage=V3, retryable=False, message=f"{message} Nothing was saved."),
                     local_step(V3, VOICE, "omnicult", started, status="failed", error_code="RUN_FAILED"))
    return {"track": track, "spans": spans, "steps": [*state["steps"], local_step(V3, VOICE, "omnicult", started)]}


async def checking_timings(state: VState, config: RunnableConfig) -> dict:
    await announce(config, VOICE, 3, "Checking the timings.")
    started = time.perf_counter()
    spans = iter(state["spans"])
    results = []
    for index, (line, audio, problems) in enumerate(state["clips"]):
        start, end = next(spans) if audio is not None else (0, 0)
        results.append({"index": index, "text": line.text, "language": line.language, "start_ms": start, "end_ms": end,
                        "duration_ms": end - start, "spoken": audio is not None, "back_translation": line.back_translation,
                        "problems": list(problems)})
    return {"results": results, "steps": [*state["steps"], local_step(V4, VOICE, "omnicult", started)]}


VOICE_GRAPH = linear_graph(VState, [(V1, loading_lines), (V2, speaking_lines), (V3, assembling_track), (V4, checking_timings)])


async def run_generate_voice(inp: GenerateVoiceInput, deps: WorkflowDeps, progress: Any = None) -> GenerateVoiceOutcome:
    state = await execute(VOICE_GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    steps, error = state.get("steps", []), state.get("error")
    results = state.get("results")
    if error is not None or results is None:
        return GenerateVoiceOutcome(status="failed", steps=steps, error=error, limitations=state.get("limitations", []))
    meta = state["meta"]
    notes = [*state.get("limitations", [])]
    track = state["track"]
    return GenerateVoiceOutcome(
        status="partial" if any(r["problems"] for r in results) else "completed", track=track, source=meta["source"], voice=meta["voice"],
        pace_applied=inp.request.pace != "normal", language_code=meta["language_code"], model=meta["model"], location=meta["location"],
        total_duration_ms=max((r["end_ms"] for r in results), default=0), lines=results, peaks=media.peaks(track),
        limitations=list(dict.fromkeys(notes)), steps=steps,
    )


# --- jingle -----------------------------------------------------------------------------------------------------


def jingle_prompt(region_name: str, mood: str, festival: str | None, instruments: list[str]) -> str:
    """The Lyria prompt from the person's hints (mood, festival, instruments) and the region's name; at most the model's limit."""
    parts = [f"A short instrumental jingle for an advertisement, {mood}."]
    if festival:
        parts.append(f"For the festival {festival}.")
    parts.append(f"For an audience in {region_name}.")
    if instruments:
        parts.append("Instruments: " + ", ".join(instruments) + ".")
    parts.append("No vocals, no speech, clean modern mix.")
    text = " ".join(parts)
    return text if len(text) <= MAX_MUSIC_PROMPT_CHARS else text[: MAX_MUSIC_PROMPT_CHARS - 1].rstrip() + "."


class JState(TypedDict, total=False):
    inp: GenerateJingleInput
    demo: bool
    client: Any
    prompt: str
    raw: bytes
    meta: dict[str, Any]
    clip: bytes
    info: dict[str, Any]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool


async def loading_hints(state: JState, config: RunnableConfig) -> dict:
    await announce(config, JINGLE, 0, "Reading the hints.")
    started, inp = time.perf_counter(), state["inp"]
    deps: WorkflowDeps = config["configurable"]["deps"]
    r = inp.request
    prompt = jingle_prompt(inp.region_name, r.mood, r.festival, list(r.instruments))
    update: dict[str, Any] = {"prompt": prompt, "demo": inp.context.mode == "demo", "limitations": [MUSIC_NOTE],
                              "steps": [local_step(J1, JINGLE, "omnicult", started)]}
    if inp.context.mode != "demo":
        client = deps.llm.capability("music")
        if client is None:
            return _fail(state, RunError(code="PROVIDER_NOT_CONFIGURED", stage=J1, retryable=False,
                                         message="Lyria is not available on this server (Vertex AI only). Nothing was generated."))
        update["client"] = client
    return update


async def composing_jingle(state: JState, config: RunnableConfig) -> dict:
    await announce(config, JINGLE, 1, "Composing the jingle.")
    started = time.perf_counter()
    if state["demo"]:
        wav, model, location, saved_prompt = demo.music_bed()
        trace = local_step(J2, JINGLE, "fixture", started).model_copy(update={"model_id": model})
        return {"raw": wav, "steps": [*state["steps"], trace], "prompt": saved_prompt,
                "meta": {"source": "demo_fixture", "model": model, "location": location},
                "limitations": state["limitations"]}
    try:
        clip = await state["client"].generate(state["prompt"], stage=J2, agent=JINGLE)
    except LLMError as exc:  # the provider's error is the run's error: shown, not hidden
        return _fail(state, llm_error(exc, J2, "Nothing was saved. The generator is still available."), exc.trace)
    return {"raw": clip.wav, "steps": [*state["steps"], clip.trace], "meta": {"source": "provider", "model": clip.model, "location": clip.location}}


async def shaping_clip(state: JState, config: RunnableConfig) -> dict:
    await announce(config, JINGLE, 2, "Cutting the clip to length.")
    started = time.perf_counter()
    try:
        clip = await asyncio.to_thread(media.trim_with_fade, state["raw"], state["inp"].request.seconds)
    except (wave.Error, EOFError):
        return _fail(state, RunError(code="RUN_FAILED", stage=J3, retryable=False, message="The music model returned audio that could not be read. Nothing was saved."),
                     local_step(J3, JINGLE, "omnicult", started, status="failed", error_code="RUN_FAILED"))
    return {"clip": clip, "steps": [*state["steps"], local_step(J3, JINGLE, "omnicult", started)]}


async def checking_clip(state: JState, config: RunnableConfig) -> dict:
    await announce(config, JINGLE, 3, "Checking the clip.")
    started = time.perf_counter()
    raw_samples, raw_channels, raw_rate = await asyncio.to_thread(media.wav_samples, state["raw"])
    samples, channels, rate = await asyncio.to_thread(media.wav_samples, state["clip"])
    info = {"generated_seconds": round(len(raw_samples) / (raw_channels * raw_rate), 2), "duration_ms": round(len(samples) * 1000 / (channels * rate)),
            "sample_rate": rate, "channels": channels, "peaks": await asyncio.to_thread(media.peaks, state["clip"])}
    return {"info": info, "steps": [*state["steps"], local_step(J4, JINGLE, "omnicult", started)]}


JINGLE_GRAPH = linear_graph(JState, [(J1, loading_hints), (J2, composing_jingle), (J3, shaping_clip), (J4, checking_clip)])


async def run_generate_jingle(inp: GenerateJingleInput, deps: WorkflowDeps, progress: Any = None) -> GenerateJingleOutcome:
    state = await execute(JINGLE_GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    steps, error, info = state.get("steps", []), state.get("error"), state.get("info")
    if error is not None or info is None:
        return GenerateJingleOutcome(status="failed", steps=steps, error=error, limitations=state.get("limitations", []), prompt=state.get("prompt"))
    meta = state["meta"]
    notes = [*state.get("limitations", [])]
    return GenerateJingleOutcome(
        status="completed", clip=state["clip"], source=meta["source"], model=meta["model"], location=meta["location"], prompt=state["prompt"],
        limitations=list(dict.fromkeys(notes)), steps=steps, **info,
    )
