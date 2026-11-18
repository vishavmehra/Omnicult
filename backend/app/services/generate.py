"""Generate studio: start a generator run, build its input, store its output as campaign assets, read the gallery.

Three generators (image, voice-over, jingle) sit in one registry, `GENERATORS`; a new one (for example video) is one more
entry plus its workflow, and the studio shows only what this module lists. Starting a run follows Remake: a live project
must `confirm_cost` before any paid call, a missing model is a 503 before the run exists, and the gateway's budget guard
stops a call that would pass the per-run or daily ceiling. A finished run keeps ONE `GenerateItem` in `agent_runs.result`
(the gallery is the campaign's generate runs, failed ones included so a provider error is never hidden); every output file is
an `assets` row (`derived_role` generate_*) with its provenance in `media_info`. Nothing here calls a provider: the
workflows do, through the gateway.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ProviderNotConfigured, ValidationFailed
from app.db import blobs
from app.db import models as m
from app.db.session import read_session, session
from app.fixtures import generate_demo as demo
from app.llm.media import LANGUAGE_CODES, MUSIC_CLIP_SECONDS
from app.llm.registry import capability_model, estimate_cost
from app.media import generate as media
from app.media import textrender
from app.schemas import generate as g
from app.schemas.common import ErrorDetail
from app.schemas.desk import BriefContent, KitDesign
from app.schemas.remake import GEMINI_VOICES
from app.schemas.runs import RunAccepted, RunError
from app.services import studio_context as ctx
from app.services.assets import content_path
from app.services.common import conflict, get_owned, not_found, paginate
from app.services.results import API
from app.services.runs import _create_run
from app.services.versions import campaign_for, newest_node, node_in, record_operation
from app.studio.engine import OpSpec
from app.workflows import generate as flow
from app.workflows.types import WorkflowContext

MAX_PROMPT_CLAIMS = 5
CLAIM_CATEGORIES = ("festival", "symbol", "colour", "food", "moment", "custom")
SPEECH_LINE_SECONDS = 5.0  # a typical line, for the per-line estimate only
VOICE_STYLES = {"Sulafat": "Warm", "Kore": "Firm", "Puck": "Upbeat", "Charon": "Informative", "Aoede": "Breezy",
                "Zephyr": "Bright", "Leda": "Youthful", "Orus": "Firm"}  # the labels in Google's published voice list
IDEA_CHIPS = ["Warm evening light", "A gift being handed over", "Close on the product", "Family around a table",
              "Clean studio backdrop", "Festive lamps and flowers", "Morning light, calm and airy", "Hands at work"]
MOODS = ["Warm and joyful", "Uplifting and homely", "Calm and festive", "Bright and energetic", "Elegant and modern", "Playful"]
INSTRUMENTS = ["flute", "sitar", "tabla", "dhol", "veena", "strings", "bells", "harmonium", "santoor", "nadaswaram"]
NAMES = {"image": "Image", "voice": "Voice-over", "jingle": "Jingle"}


@dataclass(frozen=True)
class Generator:
    """One entry of the generator registry."""

    kind: str
    run_type: str
    label: str
    capability: str  # the gateway adapter it needs
    role: str  # assets.derived_role of its outputs
    prompt_version: str


GENERATORS: dict[str, Generator] = {x.kind: x for x in (
    Generator("image", "generate_image", "Image", "image_generation", "generate_image", flow.IMAGE_PROMPT_VERSION),
    Generator("voice", "generate_voice", "Voice-over", "tts", "generate_voice", flow.VOICE_PROMPT_VERSION),
    Generator("jingle", "generate_jingle", "Jingle", "music", "generate_jingle", flow.JINGLE_PROMPT_VERSION),
)}
BY_RUN_TYPE = {x.run_type: x for x in GENERATORS.values()}


# --- starting runs ------------------------------------------------------------------------------------------------


def _need_confirmation(project: m.Project, confirmed: bool) -> None:
    if project.mode == "live" and not confirmed:
        raise ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(
            field="confirm_cost", message="This makes a paid model call. Confirm the estimated cost first.")])


def _need_capability(project: m.Project, generator: Generator) -> None:
    if project.mode == "live" and ctx.gateway_for("live").capability(generator.capability) is None:
        raise ProviderNotConfigured(f"Live {generator.label.lower()} generation is unavailable: no {generator.capability.replace('_', ' ')} "
                                    "model is configured on the server. Use a demo project or configure Google (Vertex AI).")


async def _image_asset(s: AsyncSession, user_id: UUID, project: m.Project, asset_id: UUID | None, field: str) -> m.Asset | None:
    if asset_id is None:
        return None
    row, _ = await get_owned(s, m.Asset, asset_id, user_id, "Asset", field)
    if row.project_id != project.id:
        raise conflict(field, "The asset belongs to another project.")
    if row.kind != "image" or row.upload_status != "stored":
        raise conflict(field, "Only a stored image asset can be used here.")
    return row


async def _kit(s: AsyncSession, project_id: UUID) -> KitDesign | None:
    row = await s.scalar(select(m.BrandKitDesignRow).where(m.BrandKitDesignRow.project_id == project_id))
    return KitDesign.model_validate(row.design) if row else None


async def _brief(s: AsyncSession, campaign_id: UUID) -> BriefContent | None:
    row = await s.scalar(select(m.CampaignBriefRow).where(m.CampaignBriefRow.campaign_id == campaign_id)
                         .order_by(m.CampaignBriefRow.version_number.desc()).limit(1))
    return BriefContent.model_validate(row.content) if row else None


async def start_image(user_id: UUID, campaign_id: UUID, body: g.GenerateImageRequest) -> RunAccepted:
    generator = GENERATORS["image"]
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        _need_confirmation(project, body.confirm_cost)
        region = await ctx.region_named(s, body.region_code)
        language = await ctx.language_named(s, body.language)
        reference = await _image_asset(s, user_id, project, body.reference_asset_id, "reference_asset_id")
        if body.headline and language.script not in textrender.SCRIPT_FONTS:
            raise conflict("language", f"No bundled font covers {language.script}, so a headline cannot be drawn for {language.name}.")
        claims = []
        if body.use_region_claims:
            digest = await ctx.region_claims(s, project, region)
            claims = [c for c in digest if c["category"] in CLAIM_CATEGORIES][:MAX_PROMPT_CLAIMS]
    _need_capability(project, generator)
    inputs = {
        "request": body.model_dump(mode="json", exclude={"confirm_cost"}), "region_name": region.name, "language_name": language.name,
        "script": language.script, "reference_asset_id": str(reference.id) if reference else None,
        "claims": [{"id": c["id"], "handle": c["handle"], "category": c["category"], "statement": c["statement"]} for c in claims],
    }
    return await _create_run(user_id, project, generator.run_type, inputs, campaign_id=campaign.id)


async def _back_translations(s: AsyncSession, campaign_id: UUID) -> dict[tuple[str, str], str]:
    """(element_id, regional copy) -> English back-translation, from the campaign's applied transcreate operations."""
    ops = (await s.execute(select(m.Operation).where(
        m.Operation.campaign_id == campaign_id, m.Operation.kind == "transcreate", m.Operation.status == "applied"
    ).order_by(m.Operation.created_at))).scalars()
    found: dict[tuple[str, str], str] = {}
    for op in ops:
        for line in (op.params or {}).get("lines", []):
            if line.get("back_translation") and line.get("passed", True):
                found[(line["element_id"], line["regional_copy"])] = line["back_translation"]
    return found


async def start_voice(user_id: UUID, campaign_id: UUID, body: g.GenerateVoiceRequest) -> RunAccepted:
    generator = GENERATORS["voice"]
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        _need_confirmation(project, body.confirm_cost)
        region = await ctx.region_named(s, body.region_code)
        language = await ctx.language_named(s, body.language)
        back = await _back_translations(s, campaign.id)
        lines = []
        for index, line in enumerate(body.lines):
            code = line.language or body.language
            if code not in LANGUAGE_CODES:
                raise conflict(f"lines.{index}.language", f"The speech model does not support {code}.")
            lines.append({"text": line.text, "language": code, "back_translation": back.get((line.element_id, line.text)) if line.element_id else None})
    _need_capability(project, generator)
    inputs = {"request": body.model_dump(mode="json", exclude={"confirm_cost"}), "region_name": region.name,
              "language_name": language.name, "lines": lines}
    return await _create_run(user_id, project, generator.run_type, inputs, campaign_id=campaign.id)


async def start_jingle(user_id: UUID, campaign_id: UUID, body: g.GenerateJingleRequest) -> RunAccepted:
    generator = GENERATORS["jingle"]
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        _need_confirmation(project, body.confirm_cost)
        region = await ctx.region_named(s, body.region_code)
    _need_capability(project, generator)
    inputs = {"request": body.model_dump(mode="json", exclude={"confirm_cost"}), "region_name": region.name}
    return await _create_run(user_id, project, generator.run_type, inputs, campaign_id=campaign.id)


# --- run engine hooks ---------------------------------------------------------------------------------------------


async def _asset_bytes(s: AsyncSession, project_id: UUID, asset_id: UUID | None) -> bytes | None:
    if asset_id is None:
        return None
    row = await s.get(m.Asset, asset_id)
    if row is None or row.project_id != project_id or row.kind != "image" or row.upload_status != "stored":
        return None
    return await blobs.read(row)


def _kit_ids(kit: KitDesign | None) -> dict[str, Any]:
    """The Brand Kit asset behind each picture the image workflow used, for provenance: {logos: {lockup id: asset id}, product}."""
    logos = {x.id: str(x.asset_id) for x in (kit.logo.lockups if kit else []) if x.asset_id}
    product = next((str(x.asset_id) for x in (kit.product_images if kit else []) if x.asset_id), None)
    return {"logos": logos, "product": product}


async def _brand_brief(s: AsyncSession, project_id: UUID, campaign_id: UUID | None, mode: str, brand_tone: list[str], region_code: str) -> flow.BrandBrief:
    """The Brand Kit and brief as the image workflow reads them (the pictures are loaded here, so only a run reads them)."""
    kit = await _kit(s, project_id)
    brief = await _brief(s, campaign_id) if campaign_id else None
    logos: list[flow.BrandPicture] = []
    product: flow.BrandPicture | None = None
    if kit is not None:
        for lockup in kit.logo.lockups:
            data = await _asset_bytes(s, project_id, lockup.asset_id) or (demo.brand_file(lockup.source_path) if mode == "demo" else None)
            if data:
                logos.append(flow.BrandPicture(id=lockup.id, label=lockup.use, asset_id=lockup.asset_id, data=data))
        for image in kit.product_images:
            data = await _asset_bytes(s, project_id, image.asset_id) or (demo.brand_file(image.source_path) if mode == "demo" else None)
            if data:
                product = flow.BrandPicture(id=image.id, label=image.description or image.id, asset_id=image.asset_id, data=data)
                break
    festival = brief.cta.festival_hook if brief and brief.cta else None
    moments = [km.name for km in (brief.dates.key_moments if brief and brief.dates else []) if not km.region_codes or region_code in km.region_codes]
    hook = "; ".join(x for x in [festival, *moments[:2]] if x) or None
    return flow.BrandBrief(
        tone=(kit.tone_of_voice.traits if kit and kit.tone_of_voice.traits else brand_tone),
        colours=[(c.name, c.hex) for c in kit.colours] if kit else [], logos=logos, product=product,
        product_asset_ids=[x.asset_id for x in (kit.product_images if kit else []) if x.asset_id],
        logo_min_px=(kit.logo.min_width_px.get("horizontal") if kit else None) or media.DEFAULT_LOGO_MIN_PX,
        product_name=brief.product.name if brief and brief.product else None, objective=brief.objective if brief else None,
        primary_message=brief.primary_message if brief else None, festival_hook=hook,
    )


async def build_input(s: AsyncSession, run: m.AgentRun, context: WorkflowContext) -> Any:
    d = run.inputs
    if run.run_type == "generate_voice":
        request = g.GenerateVoiceRequest.model_validate(d["request"])
        return flow.GenerateVoiceInput(context=context, request=request, region_name=d["region_name"], language_name=d["language_name"],
                                       lines=[flow.VoiceLine(**x) for x in d["lines"]])
    if run.run_type == "generate_jingle":
        return flow.GenerateJingleInput(context=context, request=g.GenerateJingleRequest.model_validate(d["request"]), region_name=d["region_name"])
    request = g.GenerateImageRequest.model_validate(d["request"])
    brand = await _brand_brief(s, run.project_id, run.campaign_id, run.mode, list(context.brand.voice), request.region_code)
    reference_id = UUID(d["reference_asset_id"]) if d.get("reference_asset_id") else None
    return flow.GenerateImageInput(
        context=context, request=request, region_name=d["region_name"], language_name=d["language_name"], script=d["script"], brand=brand,
        reference=await _asset_bytes(s, run.project_id, reference_id), reference_asset_id=reference_id,
        claims=[flow.ClaimIn(**x) for x in d.get("claims", [])],
    )


def _cost(outcome: Any) -> float | None:
    costs = [t.usage.estimated_cost_usd for t in outcome.steps if t.usage and t.usage.estimated_cost_usd is not None]
    return round(sum(costs), 6) if costs else None


def _latency(outcome: Any) -> int | None:
    values = [t.latency_ms for t in outcome.steps if t.model_id and t.latency_ms is not None]
    return sum(values) if values else None


def _ref(row: m.Asset) -> g.GenerateAssetRef:
    return g.GenerateAssetRef(asset_id=row.id, url=content_path(row.id), content_type=row.content_type, filename=row.filename,
                              width=row.width, height=row.height, duration_ms=row.duration_ms)


def _row(run: m.AgentRun, project: m.Project, role: str, data: bytes, content_type: str, filename: str, now: datetime, *, kind: str,
         parent: UUID | None = None, width: int | None = None, height: int | None = None, duration_ms: int | None = None,
         provenance: dict[str, Any]) -> tuple[m.Asset, str]:
    asset_id = uuid4()
    key = blobs.object_key(run.created_by or project.owner_id, asset_id)
    return m.Asset(
        id=asset_id, project_id=project.id, kind=kind, filename=filename, content_type=content_type, size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(), storage_name=key, created_at=now, parent_asset_id=parent, derived_role=role,
        width=width, height=height, duration_ms=duration_ms, media_info={"generate": {**provenance, "ai_generated": True}},
    ), key


def _fail_payload(outcome: Any) -> tuple[dict, tuple]:
    return {"limitations": list(outcome.limitations), "_status": "failed"}, ("generation", [], "")


async def persist(s: AsyncSession, run: m.AgentRun, outcome: Any, now: datetime) -> tuple[dict, tuple]:
    generator = BY_RUN_TYPE[run.run_type]
    produced = {"image": getattr(outcome, "composite", None), "voice": getattr(outcome, "track", None), "jingle": getattr(outcome, "clip", None)}[generator.kind]
    if outcome.status == "failed" or not produced:
        return _fail_payload(outcome)
    d = run.inputs
    project = await s.get(m.Project, run.project_id)
    assert project is not None
    request = d["request"]
    cost = _cost(outcome)
    provenance = {"run_id": str(run.id), "campaign_id": str(run.campaign_id), "kind": generator.kind, "mode": run.mode, "source": outcome.source,
                  "model": outcome.model, "location": outcome.location, "prompt_version": generator.prompt_version,
                  "estimated_cost_usd": cost, "request": request}
    stored: list[tuple[m.Asset, str, bytes]] = []
    image = voice = jingle = None
    if generator.kind == "image":
        kit_ids = _kit_ids(await _kit(s, run.project_id))
        ext = "jpg" if outcome.scene_mime == "image/jpeg" else "png"
        scene_row, scene_key = _row(run, project, generator.role, outcome.scene, outcome.scene_mime, f"generate-scene-{request['region_code']}.{ext}", now,
                                    kind="image", provenance={**provenance, "part": "scene"})
        final_row, final_key = _row(run, project, generator.role, outcome.composite, "image/png",
                                    f"generate-image-{request['region_code']}-{request['format'].replace(':', 'x')}.png", now, kind="image",
                                    parent=scene_row.id, width=outcome.width, height=outcome.height, provenance={**provenance, "part": "final"})
        stored = [(scene_row, scene_key, outcome.scene), (final_row, final_key, outcome.composite)]
        reference = await s.get(m.Asset, UUID(d["reference_asset_id"])) if d.get("reference_asset_id") and not outcome.reference_dropped else None
        headline = g.GenerateTextResult(**{k: outcome.headline[k] for k in g.GenerateTextResult.model_fields}) if outcome.headline else None
        def asset_of(p: dict[str, Any]) -> UUID | None:
            found = kit_ids["logos"].get(p["label"]) if p["kind"] == "logo" else kit_ids["product"]
            return UUID(found) if found else None

        placements = [g.GeneratePlacement(kind=p["kind"], label=p["label"], bbox=p["bbox"], width_px=p["width_px"], asset_id=asset_of(p))
                      for p in outcome.placements]
        image = g.GenerateImageDetail(
            format=request["format"], purpose=request["purpose"], width=outcome.width, height=outcome.height, shaping_engine=outcome.engine or "raqm",
            scene=_ref(scene_row), reference=_ref(reference) if reference else None, placements=placements, headline=headline,
            checks=[g.GenerateCheck(**c) for c in outcome.checks], palette=list(outcome.palette),
            claim_ids=[UUID(c["id"]) for c in d.get("claims", [])],
        )
        primary = final_row
        title = f"{'Key visual' if request['purpose'] == 'key_visual' else 'Social post'} · {d['region_name']} · {request['format']}"
        region, language, prompt = request["region_code"], request["language"], outcome.prompt
    elif generator.kind == "voice":
        row, key = _row(run, project, generator.role, outcome.track, "audio/wav", f"generate-voiceover-{request['language']}.wav", now, kind="audio",
                        duration_ms=outcome.total_duration_ms, provenance={**provenance, "part": "final", "voice": outcome.voice})
        stored = [(row, key, outcome.track)]
        voice = g.GenerateVoiceDetail(
            voice=outcome.voice or request["voice"], pace=request["pace"], pace_applied=outcome.pace_applied, language_code=outcome.language_code or "",
            total_duration_ms=outcome.total_duration_ms, lines=[g.GenerateLineResult(**x) for x in outcome.lines], peaks=list(outcome.peaks),
        )
        primary = row
        title = f"Voice-over · {d['language_name']} · {len(outcome.lines)} line{'s' if len(outcome.lines) != 1 else ''}"
        region, language, prompt = request["region_code"], request["language"], None
    else:
        row, key = _row(run, project, generator.role, outcome.clip, "audio/wav",
                        f"generate-jingle-{request['region_code']}-{request['seconds']}s.wav", now, kind="audio", duration_ms=outcome.duration_ms,
                        provenance={**provenance, "part": "final", "prompt": outcome.prompt})
        stored = [(row, key, outcome.clip)]
        jingle = g.GenerateJingleDetail(
            mood=request["mood"], festival=request.get("festival"), instruments=list(request.get("instruments", [])), requested_seconds=request["seconds"],
            generated_seconds=outcome.generated_seconds, duration_ms=outcome.duration_ms, sample_rate=outcome.sample_rate, channels=outcome.channels,
            peaks=list(outcome.peaks),
        )
        primary = row
        title = f"Jingle · {d['region_name']}{' · ' + request['festival'] if request.get('festival') else ''}"
        region, language, prompt = request["region_code"], "", outcome.prompt
    item = g.GenerateItem(
        id=run.id, campaign_id=run.campaign_id, kind=generator.kind, status=outcome.status, mode=run.mode, created_at=run.created_at,  # type: ignore[arg-type]
        title=title, region_code=region, language=language, source=outcome.source, model=outcome.model, location=outcome.location,
        prompt_version=generator.prompt_version, prompt=prompt, estimated_cost_usd=cost, latency_ms=_latency(outcome), request=request,
        asset=_ref(primary), image=image, voice=voice, jingle=jingle, limitations=list(outcome.limitations), error=None,
    )
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
    item = item.model_copy(update={"asset": _ref(primary)})
    return ({"item": item.model_dump(mode="json"), "limitations": list(outcome.limitations), "_status": outcome.status},
            ("generation", [run.id], f"{API}/campaigns/{run.campaign_id}/generate/items/{run.id}"))


# --- reads --------------------------------------------------------------------------------------------------------


def to_item(run: m.AgentRun) -> g.GenerateItem:
    """The stored item of a finished run, or a failed item rebuilt from the run (its request and its error)."""
    generator = BY_RUN_TYPE[run.run_type]
    stored = (run.result or {}).get("item")
    if stored:
        return g.GenerateItem.model_validate(stored)
    d = run.inputs or {}
    request = d.get("request", {})
    return g.GenerateItem(
        id=run.id, campaign_id=run.campaign_id, kind=generator.kind, status="failed", mode=run.mode, created_at=run.created_at,  # type: ignore[arg-type]
        title=f"{generator.label} · {d.get('region_name', request.get('region_code', ''))}", region_code=str(request.get("region_code", "")),
        language=str(request.get("language", "")), source=None, model=None, location=None, prompt_version=generator.prompt_version, prompt=None,
        estimated_cost_usd=None, latency_ms=None, request=request, asset=None, image=None, voice=None, jingle=None,
        limitations=list((run.result or {}).get("limitations", [])), error=RunError.model_validate(run.error) if run.error else None,
    )


async def list_items(user_id: UUID, campaign_id: UUID, limit: int, offset: int, kind: str | None) -> g.GenerateItemPage:
    types = [GENERATORS[kind].run_type] if kind else [x.run_type for x in GENERATORS.values()]
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        stmt = select(m.AgentRun).where(m.AgentRun.campaign_id == campaign.id, m.AgentRun.run_type.in_(types),
                                        m.AgentRun.status.in_(("completed", "partial", "failed"))).order_by(m.AgentRun.created_at.desc(), m.AgentRun.id)
        rows, total = await paginate(s, stmt, limit, offset)
    return g.GenerateItemPage(items=[to_item(r) for r in rows], limit=limit, offset=offset, total=total)


async def get_item(user_id: UUID, campaign_id: UUID, run_id: UUID) -> g.GenerateItem:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        run = await s.get(m.AgentRun, run_id)
        if run is None or run.campaign_id != campaign.id or run.run_type not in BY_RUN_TYPE or run.status not in ("completed", "partial", "failed"):
            raise not_found("Generated item")
    return to_item(run)


# --- use in Studio ------------------------------------------------------------------------------------------------


def _studio_element(item: g.GenerateItem, language_script: str | None) -> dict[str, Any]:
    """The element a generated output becomes in a Studio version, in the shapes Remake already writes."""
    assert item.asset is not None
    short = str(item.id).split("-")[0]
    if item.kind == "image":
        return {"id": f"gen-image-{short}", "kind": "scene", "value": f"asset:{item.asset.asset_id}"}
    if item.kind == "voice":
        voice = item.voice
        assert voice is not None
        value = {"asset_id": str(item.asset.asset_id), "voice": voice.voice, "language_code": voice.language_code, "model": item.model,
                 "ai_generated": True, "native_speaker_reviewed": False,
                 "lines": [{"element_id": f"line-{x.index + 1}", "start_ms": x.start_ms, "end_ms": x.end_ms} for x in voice.lines if x.spoken]}
        return {"id": f"gen-voice-{short}", "kind": "voiceover", "value": value, "language": item.language, "script": language_script}
    return {"id": f"gen-jingle-{short}", "kind": "music",
            "value": {"asset_id": str(item.asset.asset_id), "model": item.model, "prompt": item.prompt, "ai_generated": True}}


async def use_in_studio(user_id: UUID, campaign_id: UUID, run_id: UUID, body: g.GenerateUseInStudioRequest) -> g.GenerateUsed:
    """Add a generated output to a Studio version as a new element (a new version node; the source is untouched)."""
    async with session() as s, s.begin():
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        run = await s.get(m.AgentRun, run_id)
        if run is None or run.campaign_id != campaign.id or run.run_type not in BY_RUN_TYPE:
            raise not_found("Generated item")
        item = to_item(run)
        if item.asset is None or item.status == "failed":
            raise conflict("run_id", "This run made no file to add.")
        source = await node_in(s, campaign, body.version_id, "version_id") if body.version_id else await newest_node(s, campaign.id)
        if source is None:
            raise conflict("version_id", "This campaign has no version yet. Create one in Creative Studio first.")
        script = None
        if item.kind == "voice":
            language = await s.get(m.Language, item.language)
            script = language.script if language else None
        element = _studio_element(item, script)
        if any(e["id"] == element["id"] for e in source.elements):
            raise conflict("version_id", "This output is already an element of that version.")
        op, node = await record_operation(
            s, project=project, campaign=campaign, source=source, actor="user", actor_user_id=user_id,
            spec=OpSpec("manual_edit", adds=[element], generation={  # the node says which run made the file it now holds
                "run_id": str(run.id), "provider": "google" if item.source == "provider" else "fixture", "model_id": item.model,
                "prompt_version": item.prompt_version, "mode": item.mode}),
            reason=f"Added the generated {NAMES[item.kind].lower()} \"{item.title}\" as an element.", claim_ids=[],
            params={"generate": {"run_id": str(run.id), "kind": item.kind, "asset_id": str(item.asset.asset_id)}},
            label=f"Added {NAMES[item.kind].lower()}: {item.title}"[:80], prompt_version=item.prompt_version,
        )
        if node is None:
            refusal = op.rejection or {}
            raise conflict("version_id", refusal.get("message", "The operation was refused."))
        used = [*item.studio_version_ids, node.id]
        run.result = {**(run.result or {}), "item": item.model_copy(update={"studio_version_ids": used}).model_dump(mode="json")}
        return g.GenerateUsed(version_id=node.id, operation_id=op.id, element_id=element["id"])


# --- capabilities -------------------------------------------------------------------------------------------------


async def capabilities(user_id: UUID, campaign_id: UUID) -> g.GenerateCapabilities:
    settings = get_settings()
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id)
        kit, brief = await _kit(s, project.id), await _brief(s, campaign.id)
        brand = (await s.execute(select(m.BrandKit).where(m.BrandKit.project_id == project.id))).scalar_one_or_none()
        every = list((await s.execute(select(m.Language).where(m.Language.is_active).order_by(m.Language.name))).scalars())
        languages = [x for x in every if x.code in LANGUAGE_CODES]
        asset_ids = [x.asset_id for x in [*(kit.logo.lockups if kit else []), *(kit.product_images if kit else [])] if x.asset_id]
        stored = set((await s.execute(select(m.Asset.id).where(m.Asset.project_id == project.id, m.Asset.id.in_(asset_ids), m.Asset.upload_status == "stored"))).scalars()) if asset_ids else set()
    is_demo = project.mode == "demo"
    gateway = None if is_demo else ctx.gateway_for("live")

    def info(generator: Generator, estimate: float | None, location: str | None, note: str | None = None) -> g.GeneratorInfo:
        model = capability_model(settings, generator.capability)  # type: ignore[arg-type]
        if is_demo:
            return g.GeneratorInfo(kind=generator.kind, run_type=generator.run_type, label=generator.label, available=True, model=None, location=None,  # type: ignore[arg-type]
                                   estimated_cost_usd=0.0, note="Saved demonstration output: no provider is called.")
        ok = gateway is not None and gateway.capability(generator.capability) is not None
        return g.GeneratorInfo(kind=generator.kind, run_type=generator.run_type, label=generator.label, available=ok, model=model if ok else None,  # type: ignore[arg-type]
                               location=location if ok else None, estimated_cost_usd=estimate if ok else None, note=note)

    image, tts, music = (capability_model(settings, n) for n in ("image_generation", "tts", "music"))  # type: ignore[arg-type]
    clip_note = f"The model makes a {int(MUSIC_CLIP_SECONDS)} s clip; a shorter length is cut in code and still billed as one clip."
    generators = [
        info(GENERATORS["image"], estimate_cost(image, input_tokens=3000, images=1).usd if image else None, "global"),
        info(GENERATORS["voice"], estimate_cost(tts, input_tokens=20, audio_seconds=SPEECH_LINE_SECONDS).usd if tts else None, "global",
             "The estimate is for one line; every line is one call."),
        info(GENERATORS["jingle"], estimate_cost(music, audio_seconds=MUSIC_CLIP_SECONDS).usd if music else None, settings.google_music_location, clip_note),
    ]
    sample = demo.sample_lines() if is_demo else []
    voices = [GEMINI_VOICES[0]] if is_demo else list(GEMINI_VOICES)
    lang_rows = [x for x in languages if x.code == demo.SPEECH_LANGUAGE] if is_demo else languages
    scripts = textrender.available_scripts()
    drawable = [g.GenerateLanguage(code=x.code, name=x.name, script=x.script) for x in every if x.script in scripts]
    colours = [g.GenerateBrandColour(id=c.id, name=c.name, hex=c.hex) for c in kit.colours] if kit else []
    moments = [km.name for km in (brief.dates.key_moments if brief and brief.dates else [])]
    return g.GenerateCapabilities(
        mode=project.mode,  # type: ignore[arg-type]
        generators=generators,
        formats=[g.GenerateFormat(id=k, label=media.FORMAT_LABELS[k], width=w, height=h) for k, (w, h) in media.FORMATS.items()],  # type: ignore[arg-type]
        purposes=["key_visual", "social_post"], idea_chips=IDEA_CHIPS, languages=drawable,
        voice=g.GenerateVoiceOptions(
            voices=[g.GenerateVoiceInfo(name=n, style=VOICE_STYLES.get(n)) for n in voices],
            languages=[g.GenerateLanguage(code=x.code, name=x.name, script=x.script) for x in lang_rows],
            paces=["slow", "normal", "brisk"] if media.can_retime() else ["normal"], pace_supported=media.can_retime(),  # type: ignore[arg-type]
            max_lines=g.MAX_VOICE_LINES, max_line_chars=300, sample_lines=sample,
        ),
        jingle=g.GenerateJingleOptions(moods=MOODS, instruments=INSTRUMENTS, seconds=list(g.JINGLE_SECONDS), clip_seconds=int(MUSIC_CLIP_SECONDS)),
        brand=g.GenerateBrandInfo(
            name=brand.name if brand else project.name, tone=list(kit.tone_of_voice.traits) if kit and kit.tone_of_voice.traits else list(brand.voice if brand else []),
            colours=colours,
            logos=[g.GenerateBrandImage(id=x.id, label=x.use, asset_id=x.asset_id if x.asset_id in stored else None,
                                        url=content_path(x.asset_id) if x.asset_id in stored else None) for x in (kit.logo.lockups if kit else [])],
            products=[g.GenerateBrandImage(id=x.id, label=x.description or x.id, asset_id=x.asset_id if x.asset_id in stored else None,
                                           url=content_path(x.asset_id) if x.asset_id in stored else None) for x in (kit.product_images if kit else [])],
            tagline=kit.tagline.text if kit and kit.tagline else None, product_name=brief.product.name if brief and brief.product else None,
            objective=brief.objective if brief else None, primary_message=brief.primary_message if brief else None,
            festival_hooks=moments[:6],
        ),
        text_shaping=textrender.shaping_engine(), scripts=list(scripts), run_budget_usd=settings.ai_run_budget_usd, daily_budget_usd=settings.ai_daily_budget_usd,
    )

