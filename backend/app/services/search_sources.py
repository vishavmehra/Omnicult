"""Search document sources for the records other streams write: Creative X-Ray scenes, Risk Check findings and Creative
Studio versions (SearchKind `scene`, `finding`, `version`). Registered through `register_document_source`, so every search
syncs them into the index on read, exactly like claims: content hashing means only new or changed documents are embedded,
and a removed record leaves the index.

Each source reads only its own project's rows; a demo project is never indexed (demo projects follow the existing search
rule: `status: unavailable`, no lexical stand-in). Only the current X-Ray analysis of a creative is searchable, so a
replaced analysis leaves the index. Model-generated text keeps its label in `evidence_type`, `claim_type` and `note`.
"""

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.retrieval import SearchDocument
from app.schemas.graph import GraphRef
from app.schemas.versions import TEXT_KINDS
from app.services.results import API
from app.services.search import register_document_source

MAX_RECORD_DOCUMENTS = 2000  # ponytail: newest first per kind; move to a per-campaign index when a project outgrows it


def _scene_text(payload: dict) -> str:
    parts: list[str] = []
    if texts := [t.get("text", "") for t in payload.get("on_screen_text", [])]:
        parts.append("On-screen text: " + "; ".join(texts) + ".")
    if spoken := [t.get("text", "") for t in payload.get("transcript", [])]:
        parts.append("Spoken: " + " ".join(spoken))
    seen = [x for x in (payload.get("setting"), *payload.get("people", []), *payload.get("objects", [])) if x]
    if seen:
        parts.append("Seen (model-generated): " + "; ".join(seen) + ".")
    if claims := [c.get("text", "") for c in payload.get("claims", [])]:
        parts.append("Claims made: " + "; ".join(claims) + ".")
    if observed := [o.get("text", "") for o in payload.get("cultural_observations", [])]:
        parts.append("Cultural observations (model-generated): " + " ".join(observed))
    if read := [r.get("text", "") for r in payload.get("cultural_interpretations", [])]:
        parts.append("Cultural readings (a model's interpretation, not fact): " + " ".join(read))
    return " ".join(parts)


def _clock(ms: int | None) -> str:
    return "" if ms is None else f"{ms // 60000}:{ms // 1000 % 60:02d}"


@register_document_source
async def scene_documents(s: AsyncSession, project: m.Project) -> list[SearchDocument]:
    """The scenes of each creative's current X-Ray analysis."""
    if project.mode != "live":
        return []
    rows = (await s.execute(
        select(m.CreativeScene, m.CreativeAsset)
        .join(m.CreativeAsset, and_(m.CreativeAsset.id == m.CreativeScene.creative_asset_id, m.CreativeAsset.current_run_id == m.CreativeScene.run_id))
        .where(m.CreativeScene.project_id == project.id)
        .order_by(m.CreativeScene.created_at.desc(), m.CreativeScene.id).limit(MAX_RECORD_DOCUMENTS)
    )).all()
    documents = []
    for scene, creative in rows:
        text = _scene_text(scene.payload or {})
        if not text:
            continue
        span = f", {_clock(scene.start_ms)}-{_clock(scene.end_ms)}" if scene.end_ms is not None else ""
        documents.append(SearchDocument(
            kind="scene", source_id=str(scene.id), title=f"{creative.label}: scene {scene.position + 1}{span}", text=text,
            ref=GraphRef(resource="scene", id=str(scene.id), url=f"{API}/creatives/{creative.id}/scenes/{scene.id}"),
            evidence_type="model_interpretation", claim_type="interpreted", retrieval_mode="generated",
            created_at=scene.created_at, region_code=creative.region_code,
            note=f"Scene {scene.position + 1} of the {creative.kind} \"{creative.label}\", read by Creative X-Ray. Partly model-generated.",
        ))
    return documents


@register_document_source
async def finding_documents(s: AsyncSession, project: m.Project) -> list[SearchDocument]:
    """Risk Check findings of the project's campaigns, with their review status in the note."""
    if project.mode != "live":
        return []
    rows = (await s.execute(
        select(m.RiskFindingRow, m.AudienceRun).join(m.AudienceRun, m.AudienceRun.id == m.RiskFindingRow.run_id)
        .where(m.AudienceRun.project_id == project.id, m.AudienceRun.kind == "risk_check")
        .order_by(m.RiskFindingRow.created_at.desc(), m.RiskFindingRow.id).limit(MAX_RECORD_DOCUMENTS)
    )).all()
    documents = []
    for finding, run in rows:
        deterministic = finding.source == "deterministic_check"
        text = f"Observation: {finding.observation} Interpretation: {finding.interpretation}"
        if finding.suggested_fix:
            text += f" Suggested fix: {finding.suggested_fix}"
        documents.append(SearchDocument(
            kind="finding", source_id=str(finding.id), title=f"{finding.category.replace('_', ' ').capitalize()} ({finding.severity})",
            text=text, ref=GraphRef(resource="finding", id=str(finding.id), url=f"{API}/campaigns/{run.campaign_id}/risk-checks/{run.id}/findings"),
            evidence_type="deterministic_calculation" if deterministic else "model_interpretation",
            claim_type="derived" if deterministic else "interpreted", retrieval_mode="generated", created_at=finding.created_at,
            region_code=(run.region_codes or [None])[0],
            note=f"A Risk Check finding ({finding.status}). A screening aid for human review, not legal advice.",
        ))
    return documents


@register_document_source
async def version_documents(s: AsyncSession, project: m.Project) -> list[SearchDocument]:
    """Creative Studio versions: their label and the text of their copy elements."""
    if project.mode != "live":
        return []
    nodes = (await s.execute(
        select(m.VersionNode).where(m.VersionNode.project_id == project.id)
        .order_by(m.VersionNode.created_at.desc(), m.VersionNode.id).limit(MAX_RECORD_DOCUMENTS)
    )).scalars()
    documents = []
    for node in nodes:
        copy = [f"{e['kind']}: {e['value']}" for e in node.elements if e.get("kind") in TEXT_KINDS and isinstance(e.get("value"), str) and e["value"].strip()]
        if not copy:
            continue
        by_person = node.actor == "user"
        documents.append(SearchDocument(
            kind="version", source_id=str(node.id), title=node.label, text=" ".join(copy),
            ref=GraphRef(resource="version", id=str(node.id), url=f"{API}/campaigns/{node.campaign_id}/versions/{node.id}"),
            evidence_type="user_input" if by_person else "model_interpretation", claim_type=None if by_person else "interpreted",
            retrieval_mode="user_input" if by_person else "generated", created_at=node.created_at, region_code=node.region_code,
            note="A creative version written by a person." if by_person else "A creative version written by an AI operation; not reviewed by a native speaker unless a person says so.",
        ))
    return documents
