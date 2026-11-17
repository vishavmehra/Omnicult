"""Creative X-Ray service: registers an uploaded asset as a campaign creative, starts the `creative_xray` run, and reads
creatives and scenes back. The run engine calls `build_input` and `persist` (services/runs.py) like it does for the
other run-backed features. A creative's status always mirrors its latest run; scenes of earlier runs stay stored and are
reachable with `run_id`.
"""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas.assets import VisionStatus
from app.schemas.runs import RunAccepted
from app.schemas.xray import (
    Anchor,
    Creative,
    CreativeAnalysis,
    CreativeSummary,
    CreativeSummaryPage,
    FrameRecord,
    MediaProbe,
    Scene,
    ScenePage,
    TranscribeStatus,
    TranscriptSegment,
    XRayCreate,
)
from app.services.assets import content_path, to_asset
from app.services.common import conflict, get_owned, not_found, paginate, require_writable
from app.services.results import API, run_metadata
from app.services.runs import USABLE, _check_provider, _create_run
from app.workflows.xray import XRayInput, XRayOutcome

PENDING = "The X-Ray run has not finished, or it failed before producing a result."
PAYLOAD_FIELDS = {
    "frame_ms", "on_screen_text", "transcript", "people", "gestures", "setting", "objects", "colours", "music_mood", "claims",
    "cultural_observations", "cultural_interpretations", "provenance", "limitations",
}


async def _region_name(s: AsyncSession, code: str | None) -> str | None:
    if code is None:
        return None
    return await s.scalar(select(m.Region.name).where(m.Region.code == code))


async def start_xray(user_id: UUID, campaign_id: UUID, body: XRayCreate) -> RunAccepted:
    async with read_session() as s:
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        require_writable(project)
        asset, _ = await get_owned(s, m.Asset, body.asset_id, user_id, "Asset", "asset_id")
        if asset.project_id != project.id:
            raise conflict("asset_id", "The asset belongs to another project.")
        if asset.parent_asset_id is not None:
            raise conflict("asset_id", "This is a file derived from an upload (a keyframe, thumbnail or audio track). Analyse the original.")
        if asset.upload_status != "stored":
            raise conflict("asset_id", "The asset's file is not available; upload it again.")
        if body.region_code is not None and await _region_name(s, body.region_code) is None:
            if await s.scalar(select(func.count()).select_from(m.Region)):  # reference data is loaded: the code must exist
                raise conflict("region_code", "No such region.")
    _check_provider(project.mode, "creative_xray")  # before a creative row exists for a run that cannot start
    creative = await _get_or_create(project.id, campaign.id, asset, body)
    accepted = await _create_run(
        user_id, project, "creative_xray", {"creative_asset_id": str(creative)}, campaign_id=campaign.id
    )
    async with session() as s, s.begin():
        row = await s.get(m.CreativeAsset, creative)
        assert row is not None
        started, latest = await s.get(m.AgentRun, accepted.run_id), await s.get(m.AgentRun, row.latest_run_id) if row.latest_run_id else None
        if started is not None and (latest is None or started.created_at >= latest.created_at):  # a replayed old key must not rewind it
            row.latest_run_id = accepted.run_id
    return accepted


async def _get_or_create(project_id: UUID, campaign_id: UUID, asset: m.Asset, body: XRayCreate) -> UUID:
    for attempt in range(2):
        try:
            async with session() as s, s.begin():
                row = await s.scalar(
                    select(m.CreativeAsset).where(m.CreativeAsset.campaign_id == campaign_id, m.CreativeAsset.asset_id == asset.id)
                )
                if row is None:
                    now = utcnow()
                    row = m.CreativeAsset(
                        id=uuid4(), project_id=project_id, campaign_id=campaign_id, asset_id=asset.id, kind=asset.kind,
                        label=body.label or asset.filename, region_code=body.region_code, language=body.language,
                        created_at=now, updated_at=now,
                    )
                    s.add(row)
                else:  # a repeat analysis may change the market or language; a label only when given
                    row.region_code, row.language = body.region_code, body.language
                    if body.label:
                        row.label = body.label
                await s.flush()
                return row.id
        except IntegrityError:  # two first requests for the same (campaign, asset) raced; the other one wins
            if attempt:
                raise
    raise AssertionError("unreachable")


# --- run engine hooks ----------------------------------------------------------------------------------


async def build_input(s: AsyncSession, run: m.AgentRun, types: Any, context: Any, grounding: list[Any]) -> XRayInput:
    creative = await s.get(m.CreativeAsset, UUID(run.inputs["creative_asset_id"]))
    assert creative is not None
    return XRayInput(
        context=context, creative_asset_id=creative.id, campaign_id=creative.campaign_id, asset_id=creative.asset_id,
        kind=creative.kind,  # type: ignore[arg-type]
        region_code=creative.region_code, region_name=await _region_name(s, creative.region_code), language=creative.language,
    )


async def persist(
    s: AsyncSession, run: m.AgentRun, outcome: XRayOutcome, new_ids: list[str], now: Any
) -> tuple[dict, tuple[str, list, str]]:
    creative = await s.get(m.CreativeAsset, UUID(run.inputs["creative_asset_id"]))
    assert creative is not None
    if outcome.status in USABLE:
        for scene in outcome.scenes:
            s.add(m.CreativeScene(
                id=scene.id, project_id=run.project_id, creative_asset_id=creative.id, campaign_id=creative.campaign_id,
                asset_id=creative.asset_id, run_id=run.id, position=scene.position, start_ms=scene.start_ms, end_ms=scene.end_ms,
                keyframe_asset_id=scene.keyframe_asset_id, payload=scene.model_dump(mode="json", include=PAYLOAD_FIELDS),
                created_at=now,
            ))
        creative.current_run_id = run.id
        creative.analysis = {
            "probe": outcome.probe.model_dump(mode="json") if outcome.probe else None,
            "transcribe": outcome.transcribe.model_dump(mode="json"), "vision": outcome.vision.model_dump(mode="json"),
            "frames": [f.model_dump(mode="json") for f in outcome.frames],
            "transcript": [t.model_dump(mode="json") for t in outcome.transcript], "sidecar_notes": outcome.sidecar_notes,
            "limitations": list(outcome.limitations), "dropped": dict(outcome.dropped),
        }
    creative.latest_run_id = run.id
    creative.updated_at = now
    return {"creative_id": str(creative.id), "limitations": list(outcome.limitations)}, (
        "creative_xray", [creative.id], f"{API}/creatives/{creative.id}")


# --- reads ---------------------------------------------------------------------------------------------


def to_scene(row: m.CreativeScene, creative: m.CreativeAsset) -> Scene:
    keyframe = row.keyframe_asset_id or (creative.asset_id if creative.kind == "image" else None)
    return Scene.model_validate({
        **row.payload, "id": row.id, "creative_asset_id": row.creative_asset_id, "campaign_id": row.campaign_id,
        "asset_id": row.asset_id, "run_id": row.run_id, "position": row.position, "start_ms": row.start_ms,
        "end_ms": row.end_ms, "keyframe_asset_id": row.keyframe_asset_id,
        "keyframe_url": content_path(keyframe) if keyframe else None,
        "anchor": Anchor(scene_id=str(row.id), start_ms=row.start_ms, end_ms=row.end_ms).model_dump(),
        "created_at": row.created_at,
    })


async def _summary(s: AsyncSession, row: m.CreativeAsset, asset: m.Asset) -> CreativeSummary:
    run = await s.get(m.AgentRun, row.latest_run_id) if row.latest_run_id else None
    count = await s.scalar(
        select(func.count()).select_from(m.CreativeScene).where(m.CreativeScene.run_id == row.current_run_id)
        .where(m.CreativeScene.creative_asset_id == row.id)
    ) if row.current_run_id else 0
    thumbnail = await s.scalar(
        select(m.Asset.id).where(m.Asset.parent_asset_id == row.asset_id, m.Asset.derived_role == "thumbnail")
        .order_by(m.Asset.created_at.desc()).limit(1)
    )
    return CreativeSummary(
        id=row.id, project_id=row.project_id, campaign_id=row.campaign_id, asset_id=row.asset_id, kind=row.kind,  # type: ignore[arg-type]
        label=row.label, region_code=row.region_code, language=row.language, mode=run.mode if run else None,  # type: ignore[arg-type]
        status=run.status if run else None,  # type: ignore[arg-type]
        latest_run_id=row.latest_run_id, current_run_id=row.current_run_id, scene_count=int(count or 0),
        duration_ms=asset.duration_ms, thumbnail_url=content_path(thumbnail) if thumbnail else (
            content_path(row.asset_id) if row.kind == "image" else None),
        created_at=row.created_at, updated_at=row.updated_at,
    )


async def list_creatives(user_id: UUID, campaign_id: UUID, limit: int, offset: int) -> CreativeSummaryPage:
    async with read_session() as s:
        await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        stmt = (
            select(m.CreativeAsset, m.Asset).join(m.Asset, m.Asset.id == m.CreativeAsset.asset_id)
            .where(m.CreativeAsset.campaign_id == campaign_id)
        )
        rows, total = await paginate(
            s, stmt.order_by(m.CreativeAsset.created_at.desc(), m.CreativeAsset.id), limit, offset)
        items = [await _summary(s, creative, asset) for creative, asset in rows]
    return CreativeSummaryPage(items=items, limit=limit, offset=offset, total=total)


def _analysis(stored: dict | None, creative: m.CreativeAsset) -> CreativeAnalysis | None:
    if not stored or not stored.get("probe"):
        return None
    frames = [
        FrameRecord(
            id=f["id"], timestamp_ms=f["timestamp_ms"], asset_id=f.get("asset_id"),
            url=content_path(f.get("asset_id") or creative.asset_id),
            observations=f["observations"],
        )
        for f in stored.get("frames", [])
    ]
    return CreativeAnalysis(
        probe=MediaProbe.model_validate(stored["probe"]), transcribe=TranscribeStatus.model_validate(stored["transcribe"]),
        vision=VisionStatus.model_validate(stored["vision"]), frames=frames,
        transcript=[TranscriptSegment.model_validate(t) for t in stored.get("transcript", [])],
        sidecar_notes=stored.get("sidecar_notes"), limitations=list(stored.get("limitations", [])),
        dropped=dict(stored.get("dropped", {})),
    )


async def get_creative(user_id: UUID, creative_id: UUID) -> Creative:
    async with read_session() as s:
        row, _ = await get_owned(s, m.CreativeAsset, creative_id, user_id, "Creative")
        asset = await s.get(m.Asset, row.asset_id)
        assert asset is not None
        summary = await _summary(s, row, asset)
        run = await s.get(m.AgentRun, row.latest_run_id) if row.latest_run_id else None
        analysis = _analysis(row.analysis, row)
    return Creative(
        **summary.model_dump(), asset=to_asset(asset), analysis=analysis,
        limitations=analysis.limitations if analysis else [PENDING], run_metadata=run_metadata(run) if run else None,
    )


async def list_scenes(user_id: UUID, creative_id: UUID, limit: int, offset: int, run_id: UUID | None) -> ScenePage:
    async with read_session() as s:
        creative, _ = await get_owned(s, m.CreativeAsset, creative_id, user_id, "Creative")
        chosen = run_id or creative.current_run_id
        if chosen is None:
            return ScenePage(items=[], limit=limit, offset=offset, total=0)
        stmt = select(m.CreativeScene).where(m.CreativeScene.creative_asset_id == creative.id, m.CreativeScene.run_id == chosen)
        rows, total = await paginate(s, stmt.order_by(m.CreativeScene.position), limit, offset)
    return ScenePage(items=[to_scene(r, creative) for r in rows], limit=limit, offset=offset, total=total)


async def get_scene(user_id: UUID, creative_id: UUID, scene_id: UUID) -> Scene:
    async with read_session() as s:
        creative, _ = await get_owned(s, m.CreativeAsset, creative_id, user_id, "Creative")
        row = await s.get(m.CreativeScene, scene_id)
        if row is None or row.creative_asset_id != creative.id:
            raise not_found("Scene")
    return to_scene(row, creative)

