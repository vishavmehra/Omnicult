"""Remake: Video as a run: plan it (the preview), validate and start it, build the workflow input, and persist the outcome.

One clip per request, from the regional key visual (the generated scene of a Remake: Visuals result with the locked regions
restored from the original, no text) or an image the person chose, plus a prompt built in code from the brief, the region and
the creative's scenes. The estimate is shown first, a live run needs `confirm_cost`, and the per-run AI budget is checked before
any call. The outcome becomes ONE `remake` operation (actor ai) that writes the clip into a NEW version node as a `scene`
element named `remake-video` whose value is `{"media": "video", "asset_id": ...}`: the source version is untouched, a locked
`remake-video` element refuses the whole operation (before the paid call, and again when the result is saved). Every file
(start frame, the clip as delivered, the clip with the voice-over) is a derived asset with its provenance in `media_info`.
"""

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.db import models as m
from app.db.session import read_session
from app.fixtures import remake_demo
from app.llm.media import VIDEO_RESOLUTION
from app.llm.registry import capability_model, estimate_cost, price_for
from app.media import remake_video as pipeline
from app.schemas import remake as r
from app.schemas import versions as v
from app.schemas.desk import BriefContent
from app.schemas.runs import RunAccepted, RunError
from app.services import studio_context as ctx
from app.services.assets import content_path
from app.services.common import conflict
from app.services.remake import (
    ROLES, _asset_row, _bytes, _cost, _fail_payload, _image_asset, _need_capability, _need_confirmation, _source, is_video_element,
    regions_around,
)
from app.services.results import API
from app.services.runs import _create_run
from app.services.versions import active_locks, campaign_for, record_operation
from app.studio.engine import Edit, OpSpec
from app.workflows.remake import LockedSpec
from app.workflows.types import BrandContext, WorkflowContext
from app.workflows.remake_video import (
    NEGATIVE_PROMPT, VIDEO_PROMPT_VERSION, RemakeVideoInput, RemakeVideoOutcome, VideoPromptParts, prepare_frame, video_prompt,
)

VIDEO_ELEMENT_ID = "remake-video"
MAX_SCENES = 4
FRAME_NOTES = {
    "remake_scene": "The generated scene of the Remake: Visuals result in this version, with the locked regions restored from the original. No text.",
    "asset": "The image you chose, used as it is.",
    "demo_fixture": "The scene of the key visual with the locked regions restored. No text.",
    "none": "No remade key visual exists in this version and no image was chosen: the clip is made from the prompt alone.",
}


@dataclass
class Plan:
    campaign: m.Campaign
    project: m.Project
    source: m.VersionNode
    region: m.Region
    language: m.Language
    seconds: int
    start_source: str
    original: m.Asset | None = None
    scene: m.Asset | None = None
    start: m.Asset | None = None
    locked: list[LockedSpec] = field(default_factory=list)
    voiceover_element: dict[str, Any] | None = None
    voiceover: m.Asset | None = None
    prompt: str = ""
    model: str | None = None
    estimate_usd: float | None = None
    blocked: str | None = None
    blocked_field: str = "version_id"
    notes: list[str] = field(default_factory=list)


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


async def _remade_scene(s: AsyncSession, project: m.Project, elements: list[dict[str, Any]]) -> tuple[dict[str, Any], m.Asset, m.Asset | None] | None:
    """The scene element whose value is a Remake: Visuals plate, that plate, and the finished creative it was made from."""
    for e in elements:
        if e["kind"] != "scene" or not isinstance(e.get("value"), str) or not e["value"].startswith("asset:"):
            continue
        plate_id = _uuid(e["value"][6:])
        plate = await s.get(m.Asset, plate_id) if plate_id else None
        if plate is not None and plate.project_id == project.id and plate.derived_role == ROLES["plate"]:
            original = await s.get(m.Asset, plate.parent_asset_id) if plate.parent_asset_id else None
            return e, plate, original
    return None


async def _voiceover(s: AsyncSession, project: m.Project, elements: list[dict[str, Any]]) -> tuple[dict[str, Any], m.Asset] | None:
    for e in elements:
        value = e.get("value")
        asset_id = _uuid(value.get("asset_id")) if e["kind"] == "voiceover" and isinstance(value, dict) else None
        asset = await s.get(m.Asset, asset_id) if asset_id else None
        if asset is not None and asset.project_id == project.id and asset.kind == "audio" and asset.upload_status == "stored":
            return e, asset
    return None


def _setting(payload: dict[str, Any]) -> str | None:
    """Where an original scene is set. Its objects are left out on purpose: they belong to the original region, and the
    start frame (not the original film) decides what the clip shows."""
    return " ".join(str(payload.get("setting") or "").split()) or None


async def _prompt_parts(s: AsyncSession, campaign: m.Campaign, region: m.Region, language: m.Language, direction: str | None,
                        has_frame: bool) -> VideoPromptParts:
    row = await s.scalar(select(m.CampaignBriefRow).where(m.CampaignBriefRow.campaign_id == campaign.id)
                         .order_by(m.CampaignBriefRow.version_number.desc()).limit(1))
    try:
        brief = BriefContent.model_validate(row.content) if row else None
    except ValidationError:
        brief = None
    product = None
    if brief and brief.product:
        product = f"{brief.product.name}. {brief.product.description or ''}".strip()
    scenes = (await s.execute(select(m.CreativeScene).where(m.CreativeScene.campaign_id == campaign.id)
                              .order_by(m.CreativeScene.position).limit(MAX_SCENES))).scalars()
    settings = [x for row_ in scenes if (x := _setting(row_.payload or {}))]
    return VideoPromptParts(region_name=region.name, language_name=language.name, product=product or campaign.name,
                            message=brief.primary_message if brief else None, settings=settings, direction=direction, has_start_frame=has_frame)


async def plan(s: AsyncSession, user_id: UUID, campaign_id: UUID, body: r.RemakeVideoRequest) -> Plan:
    settings = get_settings()
    campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
    source = await _source(s, campaign, body.version_id)
    region = await ctx.region_named(s, body.region_code)
    language = await ctx.language_named(s, body.language)
    locks = await active_locks(s, campaign.id)
    demo = project.mode == "demo"
    p = Plan(campaign, project, source, region, language, body.seconds, "none")
    p.model = capability_model(settings, "video")
    p.estimate_usd = 0.0 if demo else (estimate_cost(p.model, video_seconds=body.seconds).usd if p.model else None)
    if VIDEO_ELEMENT_ID in locks:
        p.blocked = f"Element '{VIDEO_ELEMENT_ID}' is locked. Unlock it to make a new clip."
    remade = await _remade_scene(s, project, source.elements)
    first_scene = next((e for e in source.elements if e["kind"] == "scene" and not is_video_element(e)), None)
    if demo:
        p.start_source = "demo_fixture"
        if remade:
            _, p.scene, p.original = remade
        scene_element = remade[0] if remade else first_scene
        p.locked = regions_around(source.elements, scene_element, locks)[0] if scene_element else []
        if body.region_code not in remake_demo.demo_video_regions() and p.blocked is None:
            p.blocked, p.blocked_field = (f"The demo covers {', '.join(remake_demo.demo_video_regions()) or 'no region'} only. "
                                          "Use a live project for other regions."), "region_code"
        if body.start_asset_id is not None:
            p.notes.append("Demo projects always start from the key visual; the image you chose is not used.")
    elif body.start_asset_id is not None:
        p.start = await _image_asset(s, user_id, project, body.start_asset_id, "start_asset_id")
        p.start_source = "asset"
    elif remade and remade[2] is not None:
        scene_element, p.scene, p.original = remade
        p.locked = regions_around(source.elements, scene_element, locks)[0]
        p.start_source = "remake_scene"
    if body.add_voiceover and (found := await _voiceover(s, project, source.elements)):
        p.voiceover_element, p.voiceover = found
    parts = await _prompt_parts(s, campaign, region, language, body.direction, p.start_source != "none")
    p.prompt = video_prompt(parts)
    if not demo and p.blocked is None and p.start_source == "none":
        p.notes.append(FRAME_NOTES["none"])
    return p


def _voiceover_plan(p: Plan) -> r.VideoVoiceoverPlan | None:
    if p.voiceover is None or p.voiceover_element is None:
        return None
    ms = p.voiceover.duration_ms
    fits = ms is not None and pipeline.voiceover_fits(ms, p.seconds * 1000)
    note = ("It fits the clip and will be joined (the video is copied; the audio is the voice-over only)." if fits else
            f"It runs {ms / 1000:.1f} s and the clip {p.seconds} s, so it will not be joined: speech is never cut. Speak fewer lines in "
            "Remake: Sound, or choose a longer clip." if ms else "Its length is unknown, so it will be joined only if it fits.")
    return r.VideoVoiceoverPlan(element_id=p.voiceover_element["id"], asset_id=p.voiceover.id, duration_ms=ms, will_join=bool(fits), note=note)


def _kept(p: Plan) -> list[r.LockedRegionPreview]:
    return [r.LockedRegionPreview(element_id=x.element_id, label=x.label, kind=x.kind, source=x.source, bbox=x.bbox) for x in p.locked]


async def _workflow_input(s: AsyncSession, p: Plan) -> RemakeVideoInput:
    """The workflow input with its bytes loaded, as the preview needs it (a run builds its own from the stored inputs)."""
    context = WorkflowContext(run_id=uuid4(), project_id=p.project.id, campaign_id=p.campaign.id, mode=p.project.mode,  # type: ignore[arg-type]
                              brand=BrandContext(name=p.campaign.name))
    return RemakeVideoInput(
        context=context, source_version_id=p.source.id, region_code=p.region.code, region_name=p.region.name, language=p.language.code,
        language_name=p.language.name, prompt=p.prompt, seconds=p.seconds, start_source=p.start_source,  # type: ignore[arg-type]
        original=await _bytes(s, str(p.original.id) if p.original else None), scene=await _bytes(s, str(p.scene.id) if p.scene else None),
        start_image=await _bytes(s, str(p.start.id) if p.start else None), locked=p.locked,
        original_asset_id=p.original.id if p.original else None, scene_asset_id=p.scene.id if p.scene else None,
        start_asset_id=p.start.id if p.start else None,
    )


async def preview(user_id: UUID, campaign_id: UUID, body: r.RemakeVideoRequest) -> r.RemakeVideoPreview:
    settings = get_settings()
    async with read_session() as s:
        p = await plan(s, user_id, campaign_id, body)
        inp = await _workflow_input(s, p)
        gateway = ctx.gateway_for("live") if p.project.mode == "live" else None
    demo = p.project.mode == "demo"
    frame_png, aspect, source = None, None, p.start_source
    problem = p.blocked
    try:
        frame_png, aspect, source = await prepare_frame(inp, demo)
    except ValidationFailed as exc:
        problem = problem or f"The start image cannot be used: {exc.message}"
    thumb = await asyncio.to_thread(pipeline.thumbnail_jpeg, frame_png) if frame_png else None
    size = pipeline.CANVAS.get(aspect or "") if aspect else None
    capable = demo or (gateway is not None and gateway.capability("video") is not None)
    if not capable and problem is None:
        problem = "No video model is configured on this server. Use a demo project or configure Google (Vertex AI)."
    within = demo or p.estimate_usd is None or settings.ai_run_budget_usd <= 0 or p.estimate_usd <= settings.ai_run_budget_usd
    if not within and problem is None:
        problem = (f"This clip is estimated at ${p.estimate_usd:.2f}, above the per-run AI budget of ${settings.ai_run_budget_usd:.2f}. "
                   f"Choose a shorter clip or raise AI_RUN_BUDGET_USD.")
    video_spec = price_for(p.model)[0] if p.model else None
    if demo and (saved := remake_demo.video_clip(p.region.code)):
        p.prompt = saved.prompt  # the saved clip was made from this prompt; the project's own would not match what plays
    return r.RemakeVideoPreview(
        mode=p.project.mode, can_run=problem is None, blocked_reason=problem, source_version_id=p.source.id,  # type: ignore[arg-type]
        region_code=p.region.code, language=p.language.code,
        start_frame=r.VideoStartFrame(
            source=source, description=FRAME_NOTES[source], aspect_ratio=aspect, width=size[0] if size else None,
            height=size[1] if size else None, preview_jpeg_base64=base64.b64encode(thumb).decode("ascii") if thumb else None),
        prompt=p.prompt, negative_prompt=NEGATIVE_PROMPT, prompt_version=VIDEO_PROMPT_VERSION, model=None if demo else p.model,
        location=None if demo else settings.google_video_location, seconds=p.seconds, resolution=VIDEO_RESOLUTION,
        price_per_second_usd=None if demo or not video_spec else video_spec.per_second, estimated_cost_usd=p.estimate_usd,
        run_budget_usd=settings.ai_run_budget_usd, within_budget=within, kept_regions=_kept(p), voiceover=_voiceover_plan(p), notes=p.notes,
    )


async def start(user_id: UUID, campaign_id: UUID, body: r.RemakeVideoRequest) -> RunAccepted:
    settings = get_settings()
    async with read_session() as s:
        p = await plan(s, user_id, campaign_id, body)
        _need_confirmation(p.project, body.confirm_cost)
        if p.blocked:
            raise conflict(p.blocked_field, p.blocked)
        if p.estimate_usd and 0 < settings.ai_run_budget_usd < p.estimate_usd:
            raise conflict("seconds", f"This clip is estimated at ${p.estimate_usd:.2f}, above the per-run AI budget of "
                                      f"${settings.ai_run_budget_usd:.2f}. Choose a shorter clip or raise AI_RUN_BUDGET_USD.")
    _need_capability(p.project, "video", "Remake: Video")
    inputs = {
        "request": body.model_dump(mode="json"), "source_version_id": str(p.source.id), "region_code": p.region.code,
        "region_name": p.region.name, "language": p.language.code, "language_name": p.language.name, "prompt": p.prompt,
        "negative_prompt": NEGATIVE_PROMPT, "seconds": p.seconds, "start_source": p.start_source, "locked": [x.model_dump() for x in p.locked],
        "original_asset_id": str(p.original.id) if p.original else None, "scene_asset_id": str(p.scene.id) if p.scene else None,
        "start_asset_id": str(p.start.id) if p.start else None, "voiceover_asset_id": str(p.voiceover.id) if p.voiceover else None,
        "direction": body.direction,
    }
    return await _create_run(user_id, p.project, "remake_video", inputs, campaign_id=p.campaign.id)


async def build_input(s: AsyncSession, run: m.AgentRun, context: Any) -> RemakeVideoInput:
    d = run.inputs
    asset = d.get("voiceover_asset_id")
    return RemakeVideoInput(
        context=context, source_version_id=UUID(d["source_version_id"]), region_code=d["region_code"], region_name=d["region_name"],
        language=d["language"], language_name=d["language_name"], prompt=d["prompt"], negative_prompt=d["negative_prompt"],
        seconds=d["seconds"], start_source=d["start_source"], original=await _bytes(s, d.get("original_asset_id")),
        scene=await _bytes(s, d.get("scene_asset_id")), start_image=await _bytes(s, d.get("start_asset_id")),
        locked=[LockedSpec(**x) for x in d["locked"]], voiceover=await _bytes(s, asset),
        voiceover_asset_id=UUID(asset) if asset else None,
        original_asset_id=UUID(d["original_asset_id"]) if d.get("original_asset_id") else None,
        scene_asset_id=UUID(d["scene_asset_id"]) if d.get("scene_asset_id") else None,
        start_asset_id=UUID(d["start_asset_id"]) if d.get("start_asset_id") else None,
    )


async def persist(s: AsyncSession, run: m.AgentRun, outcome: RemakeVideoOutcome, now: datetime) -> tuple[dict, tuple]:
    if outcome.status == "failed" or not outcome.clip or not outcome.silent_clip:
        return _fail_payload(run, outcome)
    d = run.inputs
    campaign, project = await s.get(m.Campaign, run.campaign_id), await s.get(m.Project, run.project_id)
    source = await s.get(m.VersionNode, UUID(d["source_version_id"]))
    assert campaign is not None and project is not None and source is not None
    provenance = {"run_id": str(run.id), "mode": run.mode, "region_code": d["region_code"], "language": d["language"],
                  "source": outcome.source, "model": outcome.model, "location": outcome.location, "prompt_version": VIDEO_PROMPT_VERSION,
                  "seconds": outcome.seconds, "estimated_cost_usd": _cost(outcome), "operation_id": outcome.operation_id}
    original_id = UUID(d["original_asset_id"]) if d.get("original_asset_id") else None
    name = f"{d['region_code']}-{d['language']}"
    stored: list[tuple[m.Asset, str, bytes]] = []
    frame_row = None
    if outcome.start_frame:
        frame_row, frame_key = _asset_row(run, project, ROLES["frame"], outcome.start_frame, "image/png", f"remake-video-start-{name}.png", now,
                                          parent=original_id, kind="image", provenance={**provenance, "part": "start frame"})
        stored.append((frame_row, frame_key, outcome.start_frame))
    video_facts = dict(width=outcome.width, height=outcome.height)
    silent_row, silent_key = _asset_row(run, project, ROLES["video"], outcome.silent_clip, "video/mp4", f"remake-video-{name}.mp4", now, parent=None,
                                        kind="video", duration_ms=outcome.duration_ms, provenance={**provenance, "part": "clip as delivered"},
                                        **video_facts)
    stored.append((silent_row, silent_key, outcome.silent_clip))
    final_row = silent_row
    if outcome.joined:
        final_row, final_key = _asset_row(run, project, ROLES["video"], outcome.clip, "video/mp4", f"remake-video-{name}-voiceover.mp4", now,
                                          parent=silent_row.id, kind="video", duration_ms=outcome.duration_ms,
                                          provenance={**provenance, "part": "clip with voice-over", "voiceover_asset_id": d.get("voiceover_asset_id")},
                                          **video_facts)
        stored.append((final_row, final_key, outcome.clip))
    value = {"media": "video", "asset_id": str(final_row.id), "mime_type": "video/mp4", "seconds": outcome.seconds,
             "duration_ms": outcome.duration_ms, "model": outcome.model, "prompt_version": VIDEO_PROMPT_VERSION, "ai_generated": True,
             "with_voiceover": outcome.joined, "silent_asset_id": str(silent_row.id),
             "start_frame_asset_id": str(frame_row.id) if frame_row else None}
    existing = next((e for e in source.elements if e["id"] == VIDEO_ELEMENT_ID), None)
    spec = OpSpec("remake", edits=[Edit(VIDEO_ELEMENT_ID, {"value": value})] if existing else [],
                  adds=[] if existing else [{"id": VIDEO_ELEMENT_ID, "kind": "scene", "value": value}],
                  region_code=d["region_code"], language=d["language"],
                  generation={"run_id": str(run.id), "provider": "google" if outcome.source == "provider" else "fixture",
                              "model_id": outcome.model, "prompt_version": VIDEO_PROMPT_VERSION, "mode": run.mode})
    targets = {VIDEO_ELEMENT_ID} if existing else set()
    detail = r.VideoRemake(
        video_asset_id=final_row.id, video_url=content_path(final_row.id), silent_asset_id=silent_row.id, silent_url=content_path(silent_row.id),
        start_frame_asset_id=frame_row.id if frame_row else None, start_frame_url=content_path(frame_row.id) if frame_row else None,
        start_source=outcome.start_source, source=outcome.source, with_voiceover=outcome.joined,
        voiceover_asset_id=UUID(d["voiceover_asset_id"]) if outcome.joined and d.get("voiceover_asset_id") else None,
        voiceover_ms=outcome.voiceover_ms, model=outcome.model, location=outcome.location, operation_id=outcome.operation_id,
        prompt=outcome.prompt, negative_prompt=outcome.negative_prompt, prompt_version=VIDEO_PROMPT_VERSION, direction=d.get("direction"),
        seconds=outcome.seconds, aspect_ratio=outcome.aspect_ratio, resolution=outcome.resolution, width=outcome.width, height=outcome.height,
        duration_ms=outcome.duration_ms, size_bytes=outcome.size_bytes,
        kept_regions=[r.LockedRegionPreview(**{k: x[k] for k in r.LockedRegionPreview.model_fields}) for x in outcome.locked_regions],
        checks=[r.VideoCheck(**c.model_dump()) for c in outcome.checks],
    ).model_dump(mode="json")
    passed = outcome.status == "completed"
    params = {"run_id": str(run.id), "mode": run.mode, "kind": "video", "passed": passed, "region_code": d["region_code"],
              "language": d["language"], "limitations": list(outcome.limitations), "video": detail}
    refused = None
    if targets & await active_locks(s, campaign.id):  # a lock set while the run was working: refuse, keep no output
        refused = v.Rejection(code="LOCKED", element_ids=sorted(targets),
                              message=f"Locked element(s) cannot be changed: {', '.join(sorted(targets))}. Unlock them first.")
        params = {"run_id": str(run.id), "kind": "video"}
    reason = (f"Made a {outcome.seconds} s clip for {d['region_name']}{f' with {outcome.model}' if outcome.model else ''}: "
              + ("the start frame is the regional key visual without its text" if outcome.start_frame else "no start frame, from the prompt alone")
              + ("; the voice-over is joined." if outcome.joined else "; the clip has no audio."))
    op, node = await record_operation(
        s, project=project, campaign=campaign, source=source, spec=spec, actor="ai", actor_user_id=run.created_by, reason=reason, claim_ids=[],
        params=params, label=f"Remake: Video · {d['region_name']}"[:80], prompt_version=VIDEO_PROMPT_VERSION,
        estimated_cost_usd=_cost(outcome), rejection=refused,
    )
    if node is None:
        refusal = op.rejection or {}
        outcome.error = RunError(code="CONFLICT", retryable=False, message=f"{refusal.get('message', 'The operation was refused.')} Nothing was saved.")
        return {"operation_id": str(op.id), "version_id": None, "limitations": list(outcome.limitations), "_status": "failed"}, ("operation", [op.id], "")
    from app.db import blobs

    keys: list[str] = []
    try:
        for row, key, data in stored:
            await blobs.store(key, data, row.content_type)
            keys.append(key)
            s.add(row)
            await s.flush()
            blobs.attach(s, row, data)
    except BaseException:
        await blobs.discard(keys)
        raise
    payload = {"operation_id": str(op.id), "version_id": str(node.id), "limitations": list(outcome.limitations),
               "_status": "completed" if passed else "partial"}
    return payload, ("operation", [op.id], f"{API}/campaigns/{campaign.id}/remakes/{op.id}")
