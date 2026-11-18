"""Project search (contracts/README §13, D-034): semantic retrieval over persisted project content.

Each search first syncs the project's searchable content into the index (evidence, Brand Memory examples,
risk findings, Cultural DNA items, adaptations). Content hashing means only new or changed sources are
embedded, and removed sources leave the index. Demo projects and live projects without a configured
embedding model get `status: unavailable`; there is never a lexical stand-in.
"""

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import session
from app.llm.budget import UsageContext, usage_scope
from app.retrieval import IndexedChunk, RetrievalService, SearchDocument, get_retrieval_service
from app.retrieval.service import (
    adaptation_document,
    brand_example_documents,
    claim_document,
    claim_source_document,
    evidence_document,
    profile_item_document,
    risk_finding_document,
)
from app.schemas.graph import GraphRef
from app.schemas.profiles import ProfileItem
from app.schemas.risk import RiskFinding
from app.schemas.search import SearchKind, SearchResults
from app.services.claims import LIVE_STATUSES
from app.services.common import get_project
from app.services.projects import to_brand
from app.services.results import to_adaptations, to_evidence

log = logging.getLogger(__name__)

MAX_CLAIM_DOCUMENTS = 2000  # ponytail: newest-updated claims first; move to a per-region index when a workspace outgrows it
DocumentSource = Callable[[AsyncSession, m.Project], Awaitable[list[SearchDocument]]]
DOCUMENT_SOURCES: list[DocumentSource] = []


def register_document_source(source: DocumentSource) -> DocumentSource:
    """Add a searchable kind (scenes, findings, versions): `async def (session, project) -> list[SearchDocument]` with
    documents of that SearchKind. Every search and indexing pass calls it, so the documents stay in step with the
    stream's own tables. The source must only return documents the project's workspace may see."""
    DOCUMENT_SOURCES.append(source)
    return source


class DbRetrievalStore:
    """RetrievalStore over the `embeddings` table. One row per chunk: `source_id` is `<source>#<chunk>`,
    chunk metadata lives in `metadata`. A chunk not yet embedded has an empty model and vector."""

    async def replace_source(self, project_id: UUID, kind: SearchKind, source_id: str, chunks: list[IndexedChunk]) -> None:
        now = utcnow()
        try:
            async with session() as s, s.begin():
                await s.execute(delete(m.Embedding).where(
                    m.Embedding.project_id == project_id, m.Embedding.source_kind == kind,
                    m.Embedding.source_id.in_(await _row_ids(s, project_id, kind, source_id)),
                ))
                for chunk in chunks:
                    model, dims, config = _space_parts(chunk.space)
                    s.add(m.Embedding(
                        project_id=project_id, source_kind=kind, source_id=f"{source_id}#{chunk.chunk_index}",
                        text=chunk.text, model=model, dims=dims, config_version=config, vector=chunk.vector or [],
                        meta={
                            "source_id": source_id, "chunk_index": chunk.chunk_index, "title": chunk.title,
                            "content_hash": chunk.content_hash, "ref": chunk.ref.model_dump(),
                            "evidence_type": chunk.evidence_type, "claim_type": chunk.claim_type,
                            "retrieval_mode": chunk.retrieval_mode, "space": chunk.space,
                            "region_code": chunk.region_code, "note": chunk.note,
                            "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
                        },
                        created_at=now, updated_at=now,
                    ))
        except IntegrityError:
            log.info("concurrent index write for one source; keeping the stored copy")

    async def list_chunks(
        self, project_id: UUID, kinds: Sequence[SearchKind] | None = None, *, vectors: bool = True
    ) -> list[IndexedChunk]:
        stmt = select(m.Embedding).where(m.Embedding.project_id == project_id)
        if kinds is not None:
            stmt = stmt.where(m.Embedding.source_kind.in_(list(kinds)))
        if not vectors:
            stmt = stmt.options(defer(m.Embedding.vector))  # thousands of floats as JSON per chunk; only ranking reads them
        async with session() as s:
            rows = (await s.execute(stmt)).scalars().all()
        chunks = []
        for row in rows:
            meta = row.meta or {}
            created = meta.get("created_at")
            chunks.append(IndexedChunk(
                project_id=row.project_id, kind=row.source_kind, source_id=meta["source_id"],  # type: ignore[arg-type]
                chunk_index=meta["chunk_index"], title=meta["title"], text=row.text, content_hash=meta["content_hash"],
                ref=GraphRef(**meta["ref"]), evidence_type=meta.get("evidence_type"), claim_type=meta.get("claim_type"),
                retrieval_mode=meta.get("retrieval_mode"), created_at=datetime.fromisoformat(created) if created else None,
                space=meta.get("space"), vector=list(row.vector) if vectors and row.vector else None,
                region_code=meta.get("region_code"), note=meta.get("note"),
            ))
        return chunks


async def _row_ids(s: AsyncSession, project_id: UUID, kind: str, source_id: str) -> list[str]:
    stmt = select(m.Embedding.source_id, m.Embedding.meta).where(
        m.Embedding.project_id == project_id, m.Embedding.source_kind == kind
    )
    return [row_id for row_id, meta in (await s.execute(stmt)).all() if (meta or {}).get("source_id") == source_id]


def _space_parts(space: str | None) -> tuple[str, int, str]:
    """(model, dims, config_version) columns from an EmbeddingSpace key; empty for chunks not yet embedded."""
    if not space:
        return "", 0, ""
    provider_and_model, dims, config = space.rsplit(":", 2)
    return provider_and_model.split(":", 1)[1], int(dims), config


async def claim_documents(s: AsyncSession, project: m.Project) -> list[SearchDocument]:
    """Claims the project's workspace can see (its own and the shared reference claims) in the project's mode, with
    each claim's sources. Another workspace's claims never appear."""
    if project.workspace_id is None:
        return []
    claims = list((await s.execute(
        select(m.Claim).where(
            or_(m.Claim.workspace_id == project.workspace_id, m.Claim.workspace_id.is_(None)),
            m.Claim.mode == project.mode, m.Claim.status.in_(LIVE_STATUSES),
        ).order_by(m.Claim.updated_at.desc(), m.Claim.id).limit(MAX_CLAIM_DOCUMENTS)
    )).scalars())
    if not claims:
        return []
    by_claim: dict[UUID, list[m.ClaimSource]] = defaultdict(list)
    for source in (await s.execute(select(m.ClaimSource).where(m.ClaimSource.claim_id.in_([c.id for c in claims])))).scalars():
        by_claim[source.claim_id].append(source)
    region_ids = {c.region_id for c in claims if c.region_id}
    codes = {rid: code for rid, code in (await s.execute(
        select(m.Region.id, m.Region.code).where(m.Region.id.in_(region_ids)))).all()} if region_ids else {}
    documents: list[SearchDocument] = []
    for claim in claims:
        code = codes.get(claim.region_id) if claim.region_id else None
        documents.append(claim_document(
            claim_id=claim.id, workspace_id=project.workspace_id, region_code=code, attribute=claim.attribute,
            value_text=claim.value_text, kind=claim.kind, confidence=claim.confidence, source_count=len(by_claim[claim.id]),
            mode=claim.mode, created_at=claim.created_at,
        ))
        documents += [
            claim_source_document(
                source_id=src.id, claim_id=claim.id, workspace_id=project.workspace_id, region_code=code,
                source_type=src.source_type, title=src.title, publisher=src.publisher, excerpt=src.excerpt,
                claim_text=claim.value_text, claim_kind=claim.kind, mode=claim.mode, created_at=src.retrieved_at,
            )
            for src in by_claim[claim.id]
        ]
    return documents


async def project_documents(s: AsyncSession, project_id: UUID) -> list[SearchDocument]:
    """Every searchable source currently persisted for the project."""
    documents: list[SearchDocument] = []
    evidence = (await s.execute(select(m.EvidenceRecord).where(m.EvidenceRecord.project_id == project_id))).scalars()
    documents += [evidence_document(to_evidence(row)) for row in evidence]
    brand = (await s.execute(select(m.BrandKit).where(m.BrandKit.project_id == project_id))).scalar_one_or_none()
    if brand is not None:
        documents += brand_example_documents(project_id, to_brand(brand))
    adaptations = list((await s.execute(select(m.Adaptation).where(m.Adaptation.project_id == project_id))).scalars())
    documents += [adaptation_document(adaptation) for adaptation in await to_adaptations(s, adaptations)]
    for row in (await s.execute(select(m.RiskFinding).where(m.RiskFinding.project_id == project_id))).scalars():
        try:
            finding = RiskFinding.model_validate({**row.payload, "id": row.id, "status": row.status,
                                                  "status_note": row.status_note, "updated_at": row.updated_at})
        except ValidationError:
            log.warning("risk finding %s not indexed: payload does not match the schema", row.id)
            continue
        documents.append(risk_finding_document(row.scan_id, finding, row.created_at))
    for profile in (await s.execute(select(m.CulturalProfile).where(m.CulturalProfile.project_id == project_id))).scalars():
        for item in (profile.result or {}).get("items", []):
            try:
                documents.append(profile_item_document(profile.id, ProfileItem.model_validate(item), profile.created_at))
            except ValidationError:
                log.warning("profile item in %s not indexed: does not match the schema", profile.id)
    project = await s.get(m.Project, project_id)
    if project is not None:
        documents += await claim_documents(s, project)
        for source in DOCUMENT_SOURCES:
            documents += await source(s, project)
    return documents


async def sync_index(service: RetrievalService, store: DbRetrievalStore, project_id: UUID,
                     documents: list[SearchDocument]) -> None:
    await service.index_documents(project_id, documents)
    present = {(document.kind, document.source_id) for document in documents}
    stale = {(c.kind, c.source_id) for c in await store.list_chunks(project_id, vectors=False)} - present
    for kind, source_id in stale:
        await service.remove(project_id, kind, source_id)  # type: ignore[arg-type]


async def search(
    user_id: UUID, project_id: UUID, q: str, kinds: list[SearchKind] | None, limit: int, region_code: str | None = None
) -> SearchResults:
    store = DbRetrievalStore()
    async with session() as s:
        project = await get_project(s, user_id, project_id)
        documents = await project_documents(s, project_id) if project.mode == "live" else []
    service = get_retrieval_service("live" if project.mode == "live" else "demo", get_settings(), store)
    with usage_scope(UsageContext(workspace_id=project.workspace_id, project_id=project_id, user_id=user_id)):  # embedding calls
        if service.is_configured():
            await sync_index(service, store, project_id, documents)
        return await service.search(project_id, q, kinds, limit, region_code=region_code)


from app.services import search_sources  # noqa: E402,F401  (registers the scene, finding and version sources)
