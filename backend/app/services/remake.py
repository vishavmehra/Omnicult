"""Remake: Visuals and Remake: Sound as runs: validate and start them, build the workflow input, and persist the outcome.

The outcome becomes ONE `remake` operation through the same engine as every other change (actor ai, reason, prompt
version, cost): the scene (or voice-over) asset is written into a NEW version node, the source version is untouched, and a
locked element refuses the whole operation (checked before any paid call, and again when the result is saved). Every
output is a derived asset (`assets.derived_role` remake_*) with its provenance in `media_info`.
"""

import hashlib
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ProviderNotConfigured, ValidationFailed
from app.db import blobs
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session
from app.llm.media import VIDEO_SECONDS
from app.llm.registry import capability_model, estimate_cost, price_for
from app.media import remake as pipeline
from app.media import textrender
from app.schemas import remake as r
from app.schemas import versions as v
from app.schemas.common import ErrorDetail
from app.schemas.runs import RunAccepted, RunError
from app.services import studio_context as ctx
from app.services.assets import content_path
from app.services.common import conflict, get_owned, not_found, paginate
from app.services.results import API
from app.services.runs import _create_run
from app.services.versions import active_locks, campaign_for, newest_node, node_in, record_operation
from app.studio.engine import Edit, OpSpec
from app.workflows.remake import (
    SOUND_PROMPT_VERSION, VISUAL_PROMPT_VERSION, ClaimIn, LockedSpec, RemakeSoundInput, RemakeVisualInput, TextSpec, VoiceLineIn,
)

CLAIM_CATEGORIES = ("festival", "symbol", "colour", "food", "moment", "custom")
MAX_PROMPT_CLAIMS = 5
VOICE_KINDS = ("voiceover", "caption")
SPEECH_ESTIMATE_SECONDS = 5.0  # a typical caption line, for the per-line estimate only
ROLES = {"plate": "remake_plate", "visual": "remake_visual", "voiceover": "remake_voiceover", "music": "remake_music",
         "video": "remake_video", "frame": "remake_frame"}
DEFAULT_VIDEO_SECONDS = 6  # 6 s at the Fast model's 720p rate fits the default per-run AI budget; 8 s needs AI_RUN_BUDGET_USD raised


# --- starting runs -------------------------------------------------------------------------------------------


def _need_confirmation(project: m.Project, confirmed: bool) -> None:
    if project.mode == "live" and not confirmed:
        raise ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(
            field="confirm_cost", message="This makes a paid model call. Confirm the estimated cost first.")])


def _need_capability(project: m.Project, name: str, label: str) -> None:
    if project.mode == "live" and ctx.gateway_for("live").capability(name) is None:
        raise ProviderNotConfigured(f"Live {label} is unavailable: no {name.replace('_', ' ')} model is configured on the server. "
                                    "Use a demo project or configure Google (Vertex AI).")


async def _image_asset(s: AsyncSession, user_id: UUID, project: m.Project, asset_id: UUID | None, field: str) -> m.Asset | None:
    if asset_id is None:
        return None
    row, _ = await get_owned(s, m.Asset, asset_id, user_id, "Asset", field)
    if row.project_id != project.id:
        raise conflict(field, "The asset belongs to another project.")
    if row.kind != "image" or row.upload_status != "stored":
        raise conflict(field, "Only a stored image asset can be used here.")
    return row


def _element_dict(e: dict[str, Any]) -> dict[str, Any]:
    return {"id": e["id"], "kind": e["kind"], "value": e.get("value"), "language": e.get("language"), "script": e.get("script"),
            "bbox": e.get("bbox"), "scene_id": e.get("scene_id"), "locked": bool(e.get("locked"))}


async def _source(s: AsyncSession, campaign: m.Campaign, version_id: UUID | None) -> m.VersionNode:
    source = await node_in(s, campaign, version_id, "version_id") if version_id else await newest_node(s, campaign.id)
    if source is None:
        raise conflict("version_id", "This campaign has no version yet. Create one first (POST /campaigns/{id}/versions).")
    return source


def regions_around(elements: list[dict[str, Any]], plate: dict, locks: set[str]) -> tuple[list[LockedSpec], list[TextSpec]]:
    """The locked regions and the text boxes that share `plate`'s scene: what Remake: Visuals restores and draws, and what
    Remake: Video carries into its start frame."""
    group = [e for e in elements if e.get("scene_id") == plate.get("scene_id") and e["id"] != plate["id"]]
    locked, texts = [], []
    for e in group:
        if not e.get("bbox"):
            continue
        by_lock = e["id"] in locks or bool(e.get("locked"))
        if by_lock or e["kind"] in pipeline.NEVER_CHANGE_KINDS:
            locked.append(LockedSpec(element_id=e["id"], label=e["kind"], kind=e["kind"],
                                     source="lock" if by_lock else "brand_kit_never_change", bbox=e["bbox"]))
        elif e["kind"] in pipeline.TEXT_KINDS and isinstance(e.get("value"), str) and e["value"].strip():
            texts.append(TextSpec(element_id=e["id"], kind=e["kind"], text=e["value"], language=e.get("language"),
                                  script=e.get("script"), bbox=e["bbox"]))
    return locked, texts


def plan_visual(elements: list[dict[str, Any]], plate_element_id: str | None, locks: set[str]) -> tuple[dict, list[LockedSpec], list[TextSpec]]:
    """The scene element to replace, the locked regions around it and the text boxes to draw, from one version's elements."""
    by_id = {e["id"]: e for e in elements}
    if plate_element_id is not None:
        plate = by_id.get(plate_element_id)
        if plate is None:
            raise conflict("plate_element_id", f"Element '{plate_element_id}' does not exist in this version.")
        if plate["kind"] != "scene" or is_video_element(plate):
            raise conflict("plate_element_id", f"Only a scene element can be remade; '{plate_element_id}' is a "
                           f"{'video clip' if is_video_element(plate) else plate['kind']}.")
    else:
        plate = next((e for e in elements if e["kind"] == "scene" and not is_video_element(e) and e["id"] not in locks), None)
        if plate is None:
            raise conflict("plate_element_id", "This version has no unlocked scene element to remake.")
    if plate["id"] in locks:
        raise conflict("plate_element_id", f"Element '{plate['id']}' is locked. Unlock it to remake it.")
    locked, texts = regions_around(elements, plate, locks)
    return plate, locked, texts


def is_video_element(element: dict[str, Any]) -> bool:
    """The `scene` element Remake: Video writes holds a clip, not a still: Remake: Visuals never offers it."""
    return isinstance(element.get("value"), dict) and element["value"].get("media") == "video"


async def start_visual(user_id: UUID, campaign_id: UUID, body: r.RemakeVisualRequest) -> RunAccepted:
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        _need_confirmation(project, body.confirm_cost)
        source = await _source(s, campaign, body.version_id)
        region = await ctx.region_named(s, body.region_code)
        language = await ctx.language_named(s, body.language)
        plate, locked, texts = plan_visual(source.elements, body.plate_element_id, await active_locks(s, campaign.id))
        original = await _image_asset(s, user_id, project, body.original_asset_id, "original_asset_id")
        plate_asset = await _image_asset(s, user_id, project, body.plate_asset_id, "plate_asset_id")
        reference = await _image_asset(s, user_id, project, body.reference_asset_id, "reference_asset_id")
        if project.mode == "live" and original is None:
            raise conflict("original_asset_id", "Choose the finished source creative: locked regions are restored from it.")
        claims = []
        if body.use_region_claims:
            digest = await ctx.region_claims(s, project, region)
            claims = [c for c in digest if c["category"] in CLAIM_CATEGORIES][:MAX_PROMPT_CLAIMS]
    _need_capability(project, "image_generation", "Remake: Visuals")
    inputs = {
        "request": body.model_dump(mode="json"), "source_version_id": str(source.id), "region_code": region.code,
        "region_name": region.name, "language": language.code, "language_name": language.name, "script": language.script,
        "plate_element_id": plate["id"], "scene_id": plate.get("scene_id"), "locked": [x.model_dump() for x in locked],
        "texts": [x.model_dump() for x in texts], "original_asset_id": str(original.id) if original else None,
        "plate_asset_id": str(plate_asset.id) if plate_asset else None, "reference_asset_id": str(reference.id) if reference else None,
        "direction": body.direction, "claims": [{"id": c["id"], "handle": c["handle"], "category": c["category"],
                                                 "statement": c["statement"]} for c in claims],
    }
    return await _create_run(user_id, project, "remake_visual", inputs, campaign_id=campaign.id)


async def _back_translations(s: AsyncSession, campaign_id: UUID, source: m.VersionNode) -> dict[tuple[str, str], str]:
    """(element_id, regional copy) -> English back-translation, from the transcreate operations that made this version or
    one of its ancestors."""
    ids, node = [], source
    for _ in range(50):
        ids.append(node.id)
        if node.parent_id is None:
            break
        node = await s.get(m.VersionNode, node.parent_id)
        if node is None:
            break
    ops = (await s.execute(select(m.Operation).where(
        m.Operation.campaign_id == campaign_id, m.Operation.kind == "transcreate", m.Operation.status == "applied",
        m.Operation.result_version_id.in_(ids)).order_by(m.Operation.created_at))).scalars()
    found: dict[tuple[str, str], str] = {}
    for op in ops:
        for line in (op.params or {}).get("lines", []):
            if line.get("back_translation") and line.get("passed", True):
                found[(line["element_id"], line["regional_copy"])] = line["back_translation"]
    return found


async def _scene_window(s: AsyncSession, campaign_id: UUID, scene_id: str | None) -> int | None:
    try:
        row = await s.get(m.CreativeScene, UUID(str(scene_id))) if scene_id else None
    except ValueError:
        return None
    if row is None or row.campaign_id != campaign_id or row.end_ms is None:
        return None
    return max(0, row.end_ms - row.start_ms)


async def start_sound(user_id: UUID, campaign_id: UUID, body: r.RemakeSoundRequest) -> RunAccepted:
    settings = get_settings()
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        _need_confirmation(project, body.confirm_cost)
        source = await _source(s, campaign, body.version_id)
        region = await ctx.region_named(s, body.region_code)
        language = await ctx.language_named(s, body.language)
        locks = await active_locks(s, campaign.id)
        by_id = {e["id"]: e for e in source.elements}
        if body.element_ids is None:
            chosen = [e for e in source.elements if e["kind"] in VOICE_KINDS and isinstance(e.get("value"), str) and e["value"].strip()]
            if not chosen:
                raise conflict("element_ids", "This version has no voiceover or caption line to speak. Choose text elements.")
        else:
            chosen = []
            for index, element_id in enumerate(body.element_ids):
                e, field = by_id.get(element_id), f"element_ids.{index}"
                if e is None:
                    raise conflict(field, f"Element '{element_id}' does not exist in this version.")
                if e["kind"] not in v.TEXT_KINDS or not isinstance(e.get("value"), str) or not e["value"].strip():
                    raise conflict(field, f"Only text elements can be spoken; '{element_id}' is a {e['kind']}.")
                chosen.append(e)
        if len(chosen) > settings.remake_max_voice_lines:
            raise conflict("element_ids", f"A run speaks at most {settings.remake_max_voice_lines} lines; choose fewer.")
        for kind, wanted in (("voiceover", True), ("music", body.jingle)):
            locked = [e for e in source.elements if e["kind"] == kind and e["id"] in locks]
            if wanted and locked and len(locked) == sum(1 for e in source.elements if e["kind"] == kind):
                raise conflict("element_ids", f"Element '{locked[0]['id']}' is locked. Unlock it to remake it.")
        back = await _back_translations(s, campaign.id, source)
        lines = []
        for e in chosen:
            lines.append({"element_id": e["id"], "text": e["value"], "language": e.get("language"),
                          "window_ms": await _scene_window(s, campaign.id, e.get("scene_id")),
                          "back_translation": back.get((e["id"], e["value"]))})
    _need_capability(project, "tts", "Remake: Sound")
    if body.jingle:
        _need_capability(project, "music", "the Remake jingle")
    inputs = {
        "request": body.model_dump(mode="json"), "source_version_id": str(source.id), "region_code": region.code,
        "region_name": region.name, "language": language.code, "language_name": language.name, "script": language.script,
        "lines": lines, "voice": body.voice, "jingle": body.jingle, "jingle_prompt": body.jingle_prompt,
    }
    return await _create_run(user_id, project, "remake_sound", inputs, campaign_id=campaign.id)


# --- run engine hooks ---------------------------------------------------------------------------------------------


async def _bytes(s: AsyncSession, asset_id: str | None) -> bytes | None:
    if not asset_id:
        return None
    row = await s.get(m.Asset, UUID(asset_id))
    return await blobs.read(row) if row is not None else None


async def build_input(s: AsyncSession, run: m.AgentRun, types: Any, context: Any, grounding: Any) -> Any:
    if run.run_type == "remake_video":
        from app.services import remake_video

        return await remake_video.build_input(s, run, context)
    d = run.inputs
    common = {"context": context, "source_version_id": UUID(d["source_version_id"]), "region_code": d["region_code"],
              "region_name": d["region_name"], "language": d["language"], "language_name": d["language_name"], "script": d["script"]}
    if run.run_type == "remake_sound":
        return RemakeSoundInput(**common, lines=[VoiceLineIn(**x) for x in d["lines"]], voice=d["voice"], jingle=d["jingle"],
                                jingle_prompt=d.get("jingle_prompt"), max_lines=get_settings().remake_max_voice_lines)
    return RemakeVisualInput(
        **common, plate_element_id=d["plate_element_id"], scene_id=d.get("scene_id"), locked=[LockedSpec(**x) for x in d["locked"]],
        texts=[TextSpec(**x) for x in d["texts"]], original=await _bytes(s, d.get("original_asset_id")),
        plate=await _bytes(s, d.get("plate_asset_id")), reference=await _bytes(s, d.get("reference_asset_id")),
        original_asset_id=UUID(d["original_asset_id"]) if d.get("original_asset_id") else None,
        plate_asset_id=UUID(d["plate_asset_id"]) if d.get("plate_asset_id") else None, direction=d.get("direction"),
        claims=[ClaimIn(**x) for x in d.get("claims", [])],
    )


def _cost(outcome: Any) -> float | None:
    costs = [t.usage.estimated_cost_usd for t in outcome.steps if t.usage and t.usage.estimated_cost_usd is not None]
    return round(sum(costs), 6) if costs else None


def _model_ids(outcome: Any) -> list[str]:
    return list(dict.fromkeys(t.model_id for t in outcome.steps if t.model_id))


def _asset_row(run: m.AgentRun, project: m.Project, role: str, data: bytes, content_type: str, filename: str, now: datetime, *,
               parent: UUID | None, kind: str, width: int | None = None, height: int | None = None, duration_ms: int | None = None,
               provenance: dict[str, Any]) -> tuple[m.Asset, str]:
    asset_id = uuid4()
    key = blobs.object_key(run.created_by or project.owner_id, asset_id)
    row = m.Asset(
        id=asset_id, project_id=project.id, kind=kind, filename=filename, content_type=content_type, size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(), storage_name=key, created_at=now, parent_asset_id=parent, derived_role=role,
        width=width, height=height, duration_ms=duration_ms, media_info={"remake": {**provenance, "ai_generated": True}},
    )
    return row, key


def _fail_payload(run: m.AgentRun, outcome: Any) -> tuple[dict, tuple]:
    return {"operation_id": None, "version_id": None, "limitations": list(outcome.limitations), "_status": "failed"}, ("operation", [], "")


async def persist(s: AsyncSession, run: m.AgentRun, outcome: Any, new_ids: list[str], now: datetime) -> tuple[dict, tuple]:
    if run.run_type == "remake_video":
        from app.services import remake_video

        return await remake_video.persist(s, run, outcome, now)
    visual = run.run_type == "remake_visual"
    produced = outcome.composite if visual else outcome.voiceover  # type: ignore[union-attr]
    if outcome.status == "failed" or not produced:
        return _fail_payload(run, outcome)
    d = run.inputs
    campaign, project = await s.get(m.Campaign, run.campaign_id), await s.get(m.Project, run.project_id)
    source = await s.get(m.VersionNode, UUID(d["source_version_id"]))
    assert campaign is not None and project is not None and source is not None
    stored: list[tuple[m.Asset, str, bytes]] = []
    provenance = {"run_id": str(run.id), "mode": run.mode, "region_code": d["region_code"], "language": d["language"],
                  "source": outcome.source, "model": outcome.model, "location": outcome.location,
                  "prompt_version": VISUAL_PROMPT_VERSION if visual else SOUND_PROMPT_VERSION}
    original_id = UUID(d["original_asset_id"]) if d.get("original_asset_id") else None
    detail: dict[str, Any]
    if visual:
        plate_row, plate_key = _asset_row(run, project, ROLES["plate"], outcome.generated, outcome.generated_mime,
                                          f"remake-scene-{d['region_code']}.{'jpg' if outcome.generated_mime == 'image/jpeg' else 'png'}",
                                          now, parent=original_id, kind="image", provenance={**provenance, "part": "generated scene"})
        out_row, out_key = _asset_row(run, project, ROLES["visual"], outcome.composite, "image/png",
                                      f"remake-visual-{d['region_code']}-{d['language']}.png", now, parent=original_id, kind="image",
                                      width=outcome.width, height=outcome.height, provenance={**provenance, "part": "finished creative"})
        stored = [(plate_row, plate_key, outcome.generated), (out_row, out_key, outcome.composite)]
        spec = OpSpec("remake", edits=[Edit(d["plate_element_id"], {"value": f"asset:{plate_row.id}"})], region_code=d["region_code"],
                      language=d["language"], generation={"run_id": str(run.id), "provider": "google" if outcome.source == "provider" else "fixture",
                                                          "model_id": outcome.model, "prompt_version": VISUAL_PROMPT_VERSION, "mode": run.mode})
        targets = {d["plate_element_id"]}
        claim_ids = [UUID(c["id"]) for c in d.get("claims", [])]
        detail = {"visual": r.VisualRemake(
            output_asset_id=out_row.id, output_url=content_path(out_row.id), plate_asset_id=plate_row.id, plate_url=content_path(plate_row.id),
            original_asset_id=original_id, original_url=content_path(original_id) if original_id else None, source=outcome.source,
            width=outcome.width, height=outcome.height, shaping_engine=outcome.engine or "raqm", plate_element_id=d["plate_element_id"],
            scene_id=d.get("scene_id"), model=outcome.model, location=outcome.location, prompt=outcome.prompt,
            prompt_version=VISUAL_PROMPT_VERSION, direction=d.get("direction"), claim_ids=claim_ids,
            locked_regions=[r.LockedRegionResult(**x) for x in outcome.locked_regions], texts=[r.TextRenderResult(**x) for x in outcome.texts],
        ).model_dump(mode="json")}
        reason = (f"Remade the scene for {d['region_name']} ({d['language_name']}): a new background from the image model, "
                  f"{len(outcome.locked_regions)} locked region(s) restored from the original, {len(outcome.texts)} text box(es) drawn in code.")
        label = f"Remake: Visuals · {d['region_name']}"[:80]
    else:
        vo_row, vo_key = _asset_row(run, project, ROLES["voiceover"], outcome.voiceover, "audio/wav",
                                    f"remake-voiceover-{d['language']}.wav", now, parent=None, kind="audio",
                                    duration_ms=outcome.total_duration_ms, provenance={**provenance, "voice": outcome.voice})
        stored = [(vo_row, vo_key, outcome.voiceover)]
        voiceover_value = {"asset_id": str(vo_row.id), "voice": outcome.voice, "language_code": outcome.language_code, "model": outcome.model,
                           "ai_generated": True, "native_speaker_reviewed": False,
                           "lines": [{"element_id": x["element_id"], "start_ms": x["start_ms"], "end_ms": x["end_ms"]} for x in outcome.lines if x["spoken"]]}
        edits, adds, targets = [], [], set()
        vo_element = next((e for e in source.elements if e["kind"] == "voiceover"), None)
        if vo_element is not None:
            edits.append(Edit(vo_element["id"], {"value": voiceover_value, "language": d["language"], "script": d["script"]}))
            targets.add(vo_element["id"])
        else:
            adds.append({"id": "remake-voiceover", "kind": "voiceover", "value": voiceover_value, "language": d["language"], "script": d["script"]})
        jingle = None
        if outcome.jingle:
            mu_row, mu_key = _asset_row(run, project, ROLES["music"], outcome.jingle, "audio/wav", f"remake-jingle-{d['language']}.wav", now,
                                        parent=None, kind="audio", duration_ms=outcome.jingle_meta["duration_ms"],
                                        provenance={**provenance, "model": outcome.jingle_meta["model"], "location": outcome.jingle_meta["location"]})
            stored.append((mu_row, mu_key, outcome.jingle))
            jingle = r.JingleResult(asset_id=mu_row.id, url=content_path(mu_row.id), **outcome.jingle_meta)
            music_value = {"asset_id": str(mu_row.id), "model": outcome.jingle_meta["model"], "prompt": outcome.jingle_meta["prompt"], "ai_generated": True}
            music_element = next((e for e in source.elements if e["kind"] == "music"), None)
            if music_element is not None:
                edits.append(Edit(music_element["id"], {"value": music_value}))
                targets.add(music_element["id"])
            else:
                adds.append({"id": "remake-music", "kind": "music", "value": music_value})
        spec = OpSpec("remake", edits=edits, adds=adds, region_code=d["region_code"], language=d["language"],
                      generation={"run_id": str(run.id), "provider": "google" if outcome.source == "provider" else "fixture",
                                  "model_id": outcome.model, "prompt_version": SOUND_PROMPT_VERSION, "mode": run.mode})
        claim_ids = []
        detail = {"sound": r.SoundRemake(
            voiceover_asset_id=vo_row.id, voiceover_url=content_path(vo_row.id), source=outcome.source, voice=outcome.voice or d["voice"],
            language_code=outcome.language_code or "", model=outcome.model, location=outcome.location,
            total_duration_ms=outcome.total_duration_ms, lines=[r.VoiceLineResult(**{k: x[k] for k in r.VoiceLineResult.model_fields}) for x in outcome.lines],
            jingle=jingle,
        ).model_dump(mode="json")}
        reason = (f"Spoke {sum(1 for x in outcome.lines if x['spoken'])} line(s) in {d['language_name']} with the {outcome.voice} voice"
                  + ("; made a short jingle." if outcome.jingle else "."))
        label = f"Remake: Sound · {d['language_name']}"[:80]
    passed = outcome.status == "completed"
    params = {"run_id": str(run.id), "mode": run.mode, "kind": "visual" if visual else "sound", "passed": passed,
              "region_code": d["region_code"], "language": d["language"], "limitations": list(outcome.limitations), **detail}
    locks = await active_locks(s, campaign.id)
    refused = None
    if targets & locks:  # a lock set while the run was working: refuse, keep no output
        blocked = sorted(targets & locks)
        refused = v.Rejection(code="LOCKED", element_ids=blocked, message=f"Locked element(s) cannot be changed: {', '.join(blocked)}. Unlock them first.")
        params = {"run_id": str(run.id), "kind": params["kind"]}
    op, node = await record_operation(
        s, project=project, campaign=campaign, source=source, spec=spec, actor="ai", actor_user_id=run.created_by, reason=reason,
        claim_ids=claim_ids, params=params, label=label, prompt_version=VISUAL_PROMPT_VERSION if visual else SOUND_PROMPT_VERSION,
        estimated_cost_usd=_cost(outcome), rejection=refused,
    )
    if node is None:
        refusal = op.rejection or {}
        outcome.error = RunError(code="CONFLICT", retryable=False, message=f"{refusal.get('message', 'The operation was refused.')} Nothing was saved.")
        return {"operation_id": str(op.id), "version_id": None, "limitations": list(outcome.limitations), "_status": "failed"}, ("operation", [op.id], "")
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


# --- reads -----------------------------------------------------------------------------------------------------


def to_output(op: m.Operation) -> r.RemakeOutput:
    p = op.params or {}
    return r.RemakeOutput(
        id=op.id, campaign_id=op.campaign_id, kind=p["kind"], run_id=UUID(p["run_id"]) if p.get("run_id") else None,
        mode=p.get("mode", "live"), source_version_id=op.source_version_id, result_version_id=op.result_version_id,  # type: ignore[arg-type]
        region_code=str(p.get("region_code") or ""), language=str(p.get("language") or ""), created_at=op.created_at, estimated_cost_usd=op.estimated_cost_usd, prompt_version=op.prompt_version,
        passed=bool(p.get("passed")), limitations=list(p.get("limitations", [])),
        visual=r.VisualRemake.model_validate(p["visual"]) if p.get("visual") else None,
        sound=r.SoundRemake.model_validate(p["sound"]) if p.get("sound") else None,
        video=r.VideoRemake.model_validate(p["video"]) if p.get("video") else None,
    )


async def list_remakes(user_id: UUID, campaign_id: UUID, limit: int, offset: int, kind: str | None, run_id: UUID | None) -> r.RemakePage:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        stmt = select(m.Operation).where(m.Operation.campaign_id == campaign.id, m.Operation.kind == "remake",
                                         m.Operation.status == "applied").order_by(m.Operation.created_at.desc(), m.Operation.id)
        rows = list((await s.execute(stmt)).scalars())
    # ponytail: filtered in Python; a campaign holds a handful of remakes. Index the run id if that ever stops being true.
    items = [to_output(op) for op in rows if (kind is None or (op.params or {}).get("kind") == kind)
             and (run_id is None or (op.params or {}).get("run_id") == str(run_id))]
    return r.RemakePage(items=items[offset:offset + limit], limit=limit, offset=offset, total=len(items))


async def get_remake(user_id: UUID, campaign_id: UUID, operation_id: UUID) -> r.RemakeOutput:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        op = await s.get(m.Operation, operation_id)
        if op is None or op.campaign_id != campaign.id or op.kind != "remake" or op.status != "applied":
            raise not_found("Remake")
    return to_output(op)


async def capabilities(user_id: UUID, campaign_id: UUID) -> r.RemakeCapabilities:
    from app.fixtures import remake_demo

    settings = get_settings()
    async with read_session() as s:
        _, project = await campaign_for(s, user_id, campaign_id)
    demo = project.mode == "demo"
    gateway = None if demo else ctx.gateway_for("live")

    def status(name: str, estimate: float | None, location: str | None) -> r.CapabilityStatus:
        model = capability_model(settings, name)  # type: ignore[arg-type]
        if demo:
            return r.CapabilityStatus(configured=True, model=None, location=None, estimated_cost_usd=0.0,
                                      note="Demonstration fixtures: no provider is called.")
        ok = gateway is not None and gateway.capability(name) is not None
        return r.CapabilityStatus(configured=ok, model=model if ok else None, location=location if ok else None,
                                  estimated_cost_usd=estimate if ok else None)

    image, tts, music, video = (capability_model(settings, n) for n in ("image_generation", "tts", "music", "video"))  # type: ignore[arg-type]
    return r.RemakeCapabilities(
        mode=project.mode,  # type: ignore[arg-type]
        image=status("image_generation", estimate_cost(image, input_tokens=3000, images=1).usd if image else None, "global"),
        speech=status("tts", estimate_cost(tts, input_tokens=20, audio_seconds=SPEECH_ESTIMATE_SECONDS).usd if tts else None, "global"),
        music=status("music", estimate_cost(music, audio_seconds=30).usd if music else None, settings.google_music_location),
        text_shaping=textrender.shaping_engine(), voices=list(r.GEMINI_VOICES), max_voice_lines=settings.remake_max_voice_lines,
        run_budget_usd=settings.ai_run_budget_usd, daily_budget_usd=settings.ai_daily_budget_usd,
        demo_regions=remake_demo.demo_regions() if demo else [],
        video=status("video", estimate_cost(video, video_seconds=DEFAULT_VIDEO_SECONDS).usd if video else None, settings.google_video_location),
        video_seconds=list(VIDEO_SECONDS), video_default_seconds=DEFAULT_VIDEO_SECONDS,
        video_price_per_second_usd=price_for(video)[0].per_second if video and not demo else None,
        demo_video_regions=remake_demo.demo_video_regions() if demo else [],
    )
