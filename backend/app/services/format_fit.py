"""Format Fit (feature 24): how a creative sits in each channel format, and, only when a person asks, a picture made from a plan.

Planning is deterministic code over the creative's picture, the boxes of the version's elements and the version's locks
(`app.studio.formatfit`); it reads, scores and reports, and changes nothing. Applying a plan is a separate request: the
server recomputes the plan itself (it never trusts a rectangle sent by a client), refuses a plan that would cut a locked
element, renders the pixels with Pillow, and stores the result as a new asset through the same upload path as every other
asset. The original asset is never touched.
"""

import asyncio
import hashlib
from io import BytesIO
from uuid import UUID, uuid4

from PIL import Image
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.db import blobs
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.media import textrender
from app.schemas import studio_t3 as t
from app.schemas.common import ErrorDetail
from app.services import assets as asset_service
from app.services import desk
from app.services.audit import record_audit
from app.services.common import conflict, not_found, paginate, touch
from app.services.studio_t3_common import anchor_of, scene_timings, text_of
from app.services.versions import active_locks, campaign_for, node_in
from app.studio import formatfit as fit

CUTDOWN_TARGETS_MS = (6_000, 15_000, 20_000)
NOT_BOXED = frozenset({"scene", "voiceover", "music"})  # a background plate fills the frame by design; audio has no place on it
VIDEO_NOTE = "Video is not reframed here: the cut-downs are suggestions from the scene timings, and nothing is rendered."
IMAGE_NOTE = "Plans use cropping and padding only. Nothing is stretched or redrawn, and the original asset is never changed."


# --- views --------------------------------------------------------------------------------------------------------------


def format_view(spec: fit.FormatSpec) -> t.FormatFitFormat:
    top, right, bottom, left = spec.safe
    return t.FormatFitFormat(
        id=spec.id, name=spec.name, ratio=spec.ratio, width=spec.width, height=spec.height, used_for=spec.used_for,
        safe_zone=t.FormatFitSafeZone(top=top, right=right, bottom=bottom, left=left, basis=fit.BASIS))


def _rect(values: tuple[int, int, int, int]) -> t.FormatFitRect:
    return t.FormatFitRect(x=values[0], y=values[1], width=values[2], height=values[3])


def _issue(i: fit.Issue) -> t.FormatFitIssue:
    return t.FormatFitIssue(code=i.code, severity=i.severity, message=i.message, element_id=i.element_id)


def _strategy_view(plan: fit.StrategyPlan, elements: dict[str, dict], timings: dict) -> t.FormatFitStrategyPlan:
    placed = []
    for p in plan.placed:
        e = elements[p.box.id]
        placed.append(t.FormatFitElement(
            element_id=p.box.id, kind=e["kind"], locked=p.box.locked, text=p.box.text, bbox_source=list(p.box.bbox) if p.box.bbox else None,
            bbox_output=[round(v, 5) for v in p.bbox_out] if p.bbox_out else None, visible_share=round(p.visible, 4), placement=p.placement,
            in_safe_zone=p.in_safe, safe_overflow=p.overflow,  # type: ignore[arg-type]
            text_height_px=round(p.text_px, 1) if p.text_px is not None else None, min_text_px=round(p.min_text_px, 1) if p.min_text_px is not None else None,
            anchor=anchor_of(e, timings)))
    layout = plan.layout
    return t.FormatFitStrategyPlan(
        strategy=layout.strategy, verdict=plan.verdict, window=_rect(layout.window), place=_rect(layout.place), scale=round(layout.scale, 4),
        retained_share=round(plan.retained, 4), background=plan.background, elements=placed, issues=[_issue(i) for i in plan.issues],
        applicable=not any(i.code == "locked_cut" for i in plan.issues))  # type: ignore[arg-type]


# --- what a plan reads ------------------------------------------------------------------------------------------------------


class _Source:
    """The creative's picture or video, its scenes, and the boxes of the version's elements that belong to it."""

    def __init__(self, creative: m.CreativeAsset, asset: m.Asset, scenes: list[m.CreativeScene], elements: list[dict], locks: set[str],
                 size: tuple[int, int], timings: dict, data: bytes | None) -> None:
        self.creative, self.asset, self.scenes, self.elements, self.locks, self.size, self.timings, self.data = creative, asset, scenes, elements, locks, size, timings, data
        self.boxes = [
            fit.Box(e["id"], e["kind"], tuple(e["bbox"]) if e.get("bbox") else None, e["id"] in locks or bool(e.get("locked")), text_of(e))  # type: ignore[arg-type]
            for e in elements if e["kind"] not in NOT_BOXED
        ]


async def _load(user_id: UUID, campaign_id: UUID, creative_id: UUID, version_id: UUID, *, writable: bool) -> tuple[m.Project, m.Campaign, m.VersionNode, _Source]:
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=writable)
        node = await node_in(s, campaign, version_id, "version_id")
        creative = await s.get(m.CreativeAsset, creative_id)
        if creative is None or creative.campaign_id != campaign.id:
            raise not_found("Creative", "creative_id")
        if creative.kind == "audio":
            raise conflict("creative_id", "Format Fit works on a picture or a video. This creative is audio.")
        asset = await s.get(m.Asset, creative.asset_id)
        assert asset is not None
        scenes = list((await s.execute(select(m.CreativeScene).where(
            m.CreativeScene.creative_asset_id == creative.id, m.CreativeScene.run_id == creative.current_run_id).order_by(m.CreativeScene.position))).scalars())
        every_scene = set((await s.execute(select(m.CreativeScene.id).where(m.CreativeScene.campaign_id == campaign.id))).scalars())
        locks = await active_locks(s, campaign.id)
        elements = [dict(e) for e in node.elements]
        timings = await scene_timings(s, campaign.id, elements)
    mine_ids = {str(sc.id) for sc in scenes}
    linked = any(str(e.get("scene_id")) in {str(i) for i in every_scene} for e in elements)
    if linked:
        mine = [e for e in elements if e.get("scene_id") in mine_ids]
    else:  # elements that no X-Ray scene claims (a version made from copy alone) belong to the picture being planned
        mine = [e for e in elements if not e.get("scene_id")] if creative.kind == "image" else []
    data: bytes | None = None
    if creative.kind == "image":
        data = await blobs.read(asset)
        try:
            size = await asyncio.to_thread(lambda: Image.open(BytesIO(data)).size)  # type: ignore[arg-type]
        except Exception:
            raise ValidationFailed("The picture could not be read.") from None
        if size[0] * size[1] > textrender.MAX_PIXELS:
            raise ValidationFailed("The picture is larger than the 16 megapixel limit.")
    else:
        if not asset.width or not asset.height:
            raise conflict("creative_id", "This video has no known size yet. Wait for its processing to finish.")
        size = (asset.width, asset.height)
    return project, campaign, node, _Source(creative, asset, scenes, mine, locks, size, timings, data)


def _specs(ids: list[str] | None) -> list[fit.FormatSpec]:
    if ids is None:
        return list(fit.FORMATS)
    unknown = [i for i in ids if i not in fit.BY_ID]
    if unknown:
        raise ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field="format_ids", message=f"Unknown format {unknown[0]}.")])
    return [fit.BY_ID[i] for i in dict.fromkeys(ids)]


async def _plans(src: _Source, specs: list[fit.FormatSpec], background: str | None) -> list[tuple[fit.FormatSpec, list[fit.StrategyPlan]]]:
    bar = background
    if src.data is not None and bar is None:
        image = await asyncio.to_thread(lambda: Image.open(BytesIO(src.data)))  # type: ignore[arg-type]
        bar = await asyncio.to_thread(fit.edge_colour, image)
    return [(spec, fit.plan_strategies(src.boxes, src.size, spec, background=bar)) for spec in specs]


# --- the catalogue and the plans ---------------------------------------------------------------------------------------------


async def catalogue(user_id: UUID, campaign_id: UUID) -> t.FormatFitCatalogue:
    async with read_session() as s:
        await campaign_for(s, user_id, campaign_id)
    brief = (await desk.get_brief(user_id, campaign_id)).content
    channels = []
    for channel in brief.channels:
        spec = fit.format_for_channel(channel.id, channel.name, channel.format)
        channels.append(t.FormatFitChannel(id=channel.id, name=channel.name, format_text=channel.format, format_id=spec.id if spec else None))
    return t.FormatFitCatalogue(formats=[format_view(f) for f in fit.FORMATS], channels=channels, tool_version=fit.FIT_VERSION)


async def plan(user_id: UUID, campaign_id: UUID, body: t.FormatFitPlanRequest) -> t.FormatFitPlans:
    _, campaign, node, src = await _load(user_id, campaign_id, body.creative_id, body.version_id, writable=False)
    by_id = {e["id"]: e for e in src.elements}
    kind = src.creative.kind
    notes = [IMAGE_NOTE if kind == "image" else VIDEO_NOTE]
    cutdowns: list[t.FormatFitCutdown] = []
    if kind == "image":
        planned = await _plans(src, _specs(body.format_ids), body.background)
    else:
        spec = fit.nearest_format(*src.size)
        planned = [(spec, [fit.assess(src.boxes, src.size, fit.native_layout(src.size, spec), spec)])]
        notes.append(f"A video is checked in the format it already has ({spec.ratio}). Reframing it to another ratio needs a re-edit.")
        cutdowns = _cutdowns(src)
    plans = []
    for spec, strategies in planned:
        plans.append(t.FormatFitPlan(format=format_view(spec), strategies=[_strategy_view(p, by_id, src.timings) for p in strategies], recommended=fit.recommend(strategies)))
    if not src.boxes:
        notes.append("No element of this version is positioned on this creative, so only the crop geometry could be planned.")
    return t.FormatFitPlans(
        creative_id=src.creative.id, version_id=node.id, locked_element_ids=sorted(src.locks & {b.id for b in src.boxes} | {b.id for b in src.boxes if b.locked}),
        source=t.FormatFitSource(asset_id=src.asset.id, kind=kind, width=src.size[0], height=src.size[1], sha256=src.asset.sha256, label=src.creative.label),  # type: ignore[arg-type]
        plans=plans, cutdowns=cutdowns, notes=notes, tool_version=fit.FIT_VERSION)


def _cutdowns(src: _Source) -> list[t.FormatFitCutdown]:
    scenes = [
        fit.SceneBrief(
            str(sc.id), n, sc.start_ms, sc.end_ms or sc.start_ms, (sc.payload or {}).get("setting"),
            frozenset(e["kind"] for e in src.elements if str(e.get("scene_id")) == str(sc.id)))
        for n, sc in enumerate(src.scenes, 1) if sc.end_ms is not None
    ]
    total = (scenes[-1].end_ms - scenes[0].start_ms) if scenes else 0
    targets = [x for x in CUTDOWN_TARGETS_MS if x <= total - 1_000]
    return [
        t.FormatFitCutdown(
            target_ms=c.target_ms, duration_ms=c.duration_ms, score=c.score, notes=c.notes,
            segments=[t.FormatFitSegment(scene_id=g.scene_id, position=g.position, start_ms=g.start_ms, end_ms=g.end_ms, trimmed=g.trimmed, reasons=g.reasons) for g in c.segments],
            dropped=[t.FormatFitDropped(**d) for d in c.dropped])
        for c in fit.suggest_cutdowns(scenes, targets)
    ]


# --- applying a plan ---------------------------------------------------------------------------------------------------------


def _encode(image: Image.Image, limit: int) -> tuple[bytes, str]:
    """Lossless PNG; a high-quality JPEG when the PNG is over the upload limit. Anything still over the limit is refused."""
    png = textrender.encode_png(image)
    if len(png) <= limit:
        return png, "png"
    out = BytesIO()
    image.convert("RGB").save(out, format="JPEG", quality=92, optimize=True)
    if out.tell() > limit:
        raise ValidationFailed(f"The output is larger than the {limit // (1024 * 1024)} MB image limit even as a JPEG.")
    return out.getvalue(), "jpg"


def _output_view(row: m.FormatFitOutput, asset: m.Asset) -> t.FormatFitOutput:
    p = row.plan
    return t.FormatFitOutput(
        id=row.id, campaign_id=row.campaign_id, version_id=row.version_id, creative_id=row.creative_id, format_id=row.format_id,  # type: ignore[arg-type]
        strategy=row.strategy, asset=asset_service.to_asset(asset), source_asset_id=row.source_asset_id, verdict=p["verdict"],  # type: ignore[arg-type]
        issues=[t.FormatFitIssue.model_validate(i) for i in p["issues"]], window=t.FormatFitRect.model_validate(p["window"]),
        place=t.FormatFitRect.model_validate(p["place"]), scale=p["scale"], background=p.get("background"), tool_version=p["tool_version"],
        created_by=row.created_by, created_at=row.created_at)


async def apply(user_id: UUID, campaign_id: UUID, body: t.FormatFitApply) -> t.FormatFitOutput:
    project, campaign, node, src = await _load(user_id, campaign_id, body.creative_id, body.version_id, writable=True)
    if src.creative.kind != "image" or src.data is None:
        raise conflict("creative_id", "Only a picture can be fitted to a format here. A video gets cut-down suggestions, not a rendered file.")
    spec = _specs([body.format_id])[0]
    (_, strategies), = await _plans(src, [spec], body.background)
    chosen = next((p for p in strategies if p.layout.strategy == body.strategy), None)
    if chosen is None:
        offered = ", ".join(p.layout.strategy for p in strategies)
        raise conflict("strategy", f"This picture does not have a {body.strategy} plan for {spec.ratio}. Available: {offered}.")
    cut = [i for i in chosen.issues if i.code == "locked_cut"]
    if cut:
        raise conflict("strategy", "This plan would cut a locked element and cannot be applied: " + "; ".join(i.message for i in cut))
    conflicts = [i for i in chosen.issues if i.severity == "conflict"]
    if conflicts and not body.acknowledge_issues:
        raise conflict("acknowledge_issues", "This plan cuts text that is part of the copy. Confirm that you accept it (acknowledge_issues) or choose another plan: "
                       + "; ".join(i.message for i in conflicts))
    background = chosen.background or body.background or "#ffffff"

    def make() -> tuple[bytes, str]:
        image = Image.open(BytesIO(src.data))  # type: ignore[arg-type]
        image.load()
        return _encode(fit.render(image, chosen.layout, spec, background), get_settings().max_image_bytes)

    data, extension = await asyncio.to_thread(make)
    stem = asset_service.safe_filename(src.asset.filename).rsplit(".", 1)[0]
    filename = f"{stem}-{spec.ratio.replace(':', 'x')}-{chosen.layout.strategy}.{extension}"
    asset = await asset_service.upload_asset(user_id, project.id, "image", filename, data)
    plan_record = {
        "tool_version": fit.FIT_VERSION, "verdict": chosen.verdict, "issues": [_issue(i).model_dump(mode="json") for i in chosen.issues],
        "window": _rect(chosen.layout.window).model_dump(), "place": _rect(chosen.layout.place).model_dump(), "scale": round(chosen.layout.scale, 4),
        "background": background if chosen.layout.strategy == "pad" else None, "output_sha256": hashlib.sha256(data).hexdigest(),
        "output_size": [spec.width, spec.height], "source_sha256": src.asset.sha256, "locked": sorted(b.id for b in src.boxes if b.locked),
    }
    row = m.FormatFitOutput(
        id=uuid4(), project_id=project.id, campaign_id=campaign.id, version_id=node.id, creative_id=src.creative.id, source_asset_id=src.asset.id,
        output_asset_id=asset.id, format_id=spec.id, strategy=chosen.layout.strategy, plan=plan_record, created_by=user_id, created_at=utcnow())
    async with session() as s, s.begin():
        s.add(row)
        await s.flush()
        project_row = await s.get(m.Project, project.id)
        assert project_row is not None
        await record_audit(s, action="studio.format_fit_applied", target_type="format_fit_output", target_id=str(row.id), workspace_id=project_row.workspace_id,
                           actor_user_id=user_id, detail={"version_id": str(node.id), "format": spec.id, "strategy": chosen.layout.strategy, "asset_id": str(asset.id)})
        touch(project_row)
        stored = await s.get(m.Asset, asset.id)
        assert stored is not None
    return _output_view(row, stored)


async def list_outputs(user_id: UUID, campaign_id: UUID, limit: int, offset: int, creative_id: UUID | None = None) -> t.FormatFitOutputPage:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        stmt = select(m.FormatFitOutput).where(m.FormatFitOutput.campaign_id == campaign.id)
        if creative_id is not None:
            stmt = stmt.where(m.FormatFitOutput.creative_id == creative_id)
        rows, total = await paginate(s, stmt.order_by(m.FormatFitOutput.created_at.desc(), m.FormatFitOutput.id), limit, offset)
        assets = {a.id: a for a in (await s.execute(select(m.Asset).where(m.Asset.id.in_([r.output_asset_id for r in rows])))).scalars()} if rows else {}
    return t.FormatFitOutputPage(items=[_output_view(r, assets[r.output_asset_id]) for r in rows], limit=limit, offset=offset, total=total)
