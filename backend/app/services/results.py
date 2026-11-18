"""Read side: runs, evidence, and the stored results of each run type.

Results embed the evidence records they reference (D-009). Each stored result keeps an
`evidence_ids` list, hydrated here in one query and always scoped to the run's project.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.db.session import read_session
from app.schemas.adaptations import Adaptation
from app.schemas.common import RunMetadata
from app.schemas.evidence import EvidencePage, EvidenceRecord, EvidenceType
from app.schemas.runs import Run, RunPage, RunStatus, RunType
from app.services.common import get_owned, get_project, paginate

API = "/api/v1"


# --- converters ------------------------------------------------------------------------


def to_run(run: m.AgentRun) -> Run:
    return Run(
        id=run.id, project_id=run.project_id, campaign_id=run.campaign_id, study_id=run.study_id,
        run_type=run.run_type, status=run.status, mode=run.mode,  # type: ignore[arg-type]
        progress=run.progress, result=run.result_ref, error=run.error,  # type: ignore[arg-type]
        created_at=run.created_at, started_at=run.started_at, completed_at=run.completed_at,
    )


def run_metadata(run: m.AgentRun) -> RunMetadata:
    return RunMetadata(
        run_id=run.id, mode=run.mode, started_at=run.started_at, completed_at=run.completed_at,  # type: ignore[arg-type]
        steps=run.steps,  # type: ignore[arg-type]
    )


def to_evidence(row: m.EvidenceRecord) -> EvidenceRecord:
    return EvidenceRecord.model_validate(row, from_attributes=True)


async def evidence_by_ids(s: AsyncSession, project_id: UUID, ids: list[Any]) -> list[EvidenceRecord]:
    """Evidence in the given order, restricted to the project; unknown ids are skipped."""
    wanted = list(dict.fromkeys(UUID(str(i)) for i in ids))
    if not wanted:
        return []
    stmt = select(m.EvidenceRecord).where(m.EvidenceRecord.project_id == project_id, m.EvidenceRecord.id.in_(wanted))
    rows = {row.id: row for row in (await s.execute(stmt)).scalars()}
    return [to_evidence(rows[i]) for i in wanted if i in rows]


async def to_adaptations(s: AsyncSession, rows: list[m.Adaptation]) -> list[Adaptation]:
    if not rows:
        return []
    evidence = {
        e.id: e for e in await evidence_by_ids(s, rows[0].project_id, [i for row in rows for i in row.evidence_ids])
    }
    return [
        Adaptation(
            id=row.id, project_id=row.project_id, campaign_id=row.campaign_id, run_id=row.run_id,
            source_content_version_id=row.source_content_version_id, parent_adaptation_id=row.parent_adaptation_id,
            origin=row.origin, mode=row.mode, market=row.market, label=row.label,  # type: ignore[arg-type]
            strategy=row.strategy, content=row.content, changes=row.changes, checks=row.checks,  # type: ignore[arg-type]
            warnings=row.warnings, limitations=row.limitations, context=row.context,  # type: ignore[arg-type]
            evidence=[evidence[UUID(str(i))] for i in row.evidence_ids if UUID(str(i)) in evidence],
            created_at=row.created_at,
        )
        for row in rows
    ]


async def get_run(user_id: UUID, run_id: UUID) -> Run:
    async with read_session() as s:
        run, _ = await get_owned(s, m.AgentRun, run_id, user_id, "Run")
    return to_run(run)


async def list_runs(
    user_id: UUID, project_id: UUID, limit: int, offset: int, run_type: RunType | None, campaign_id: UUID | None,
    study_id: UUID | None, status: RunStatus | None,
) -> RunPage:
    async with read_session() as s:
        await get_project(s, user_id, project_id)
        stmt = select(m.AgentRun).where(m.AgentRun.project_id == project_id)
        for column, value in (("run_type", run_type), ("campaign_id", campaign_id), ("study_id", study_id), ("status", status)):
            if value is not None:
                stmt = stmt.where(getattr(m.AgentRun, column) == value)
        rows, total = await paginate(s, stmt.order_by(m.AgentRun.created_at.desc(), m.AgentRun.id), limit, offset)
    return RunPage(items=[to_run(r) for r in rows], limit=limit, offset=offset, total=total)


async def list_evidence(
    user_id: UUID, project_id: UUID, limit: int, offset: int, run_id: UUID | None, evidence_type: EvidenceType | None
) -> EvidencePage:
    async with read_session() as s:
        await get_project(s, user_id, project_id)
        stmt = select(m.EvidenceRecord).where(m.EvidenceRecord.project_id == project_id)
        if run_id is not None:
            stmt = stmt.where(m.EvidenceRecord.source_run_id == run_id)
        if evidence_type is not None:
            stmt = stmt.where(m.EvidenceRecord.evidence_type == evidence_type)
        stmt = stmt.order_by(m.EvidenceRecord.created_at.desc(), m.EvidenceRecord.id)
        rows, total = await paginate(s, stmt, limit, offset)
    return EvidencePage(items=[to_evidence(r) for r in rows], limit=limit, offset=offset, total=total)


async def get_evidence(user_id: UUID, evidence_id: UUID) -> EvidenceRecord:
    async with read_session() as s:
        row, _ = await get_owned(s, m.EvidenceRecord, evidence_id, user_id, "Evidence record")
    return to_evidence(row)
