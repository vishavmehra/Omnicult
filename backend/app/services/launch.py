"""Launch Room service: score comparison, readiness verdicts with history, and human approvals.

Access (services.common): any workspace member reads; computing and storing a readiness verdict needs the owner or editor
role and an active project; recording an approval needs the owner, editor or reviewer role (a viewer cannot) and a
signed-in user. A campaign in a workspace the caller does not belong to is indistinguishable from a missing one (404).
Verdicts and approvals are append-only. A verdict is a recommendation; only `record_approval` records a decision, and it
always records a person.
"""

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import readiness as readiness_rules
from app.analytics import scoring_v2
from app.core.errors import Conflict, Forbidden
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas import launch as v
from app.services.audit import record_audit
from app.services.common import ARCHIVED, conflict, get_owned, not_found, paginate, require_writable, touch
from app.services.identity import READ_ONLY, REVIEW_ROLES

APPROVAL_NOTE = "A Go verdict is a recommendation computed by rules. Approvals are decisions recorded by people."


async def _region(s: AsyncSession, region_code: str) -> m.Region:
    region = await s.scalar(select(m.Region).where(m.Region.code == region_code))
    if region is None:
        raise not_found("Region", "region_code")
    return region


def fingerprint(region_code: str, version_id: UUID, observations: v.VersionObservations) -> str:
    """SHA-256 of everything the verdict depends on (inputs and rule versions, not the label or the clock)."""
    payload: dict[str, Any] = {
        "region": region_code, "version": str(version_id), "rules": readiness_rules.RULE_VERSION,
        "scoring": scoring_v2.SCORING_VERSION, "observations": observations.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# --- Compare and Score ----------------------------------------------------------------------------


async def compare_scores(user_id: UUID, campaign_id: UUID, body: v.ScoreCompareRequest) -> v.ScoreComparison:
    """mvp-2 score cards for 2-4 versions in one region, with comparability and major differences. Nothing is stored."""
    async with read_session() as s:
        await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        await _region(s, body.region_code)
    return scoring_v2.compare(body.region_code, body.versions)


# --- readiness ------------------------------------------------------------------------------------


def _verdict_view(row: m.ReadinessVerdict, region_code: str, region_name: str, *, is_latest: bool) -> v.ReadinessVerdict:
    return v.ReadinessVerdict.model_validate({
        **row.result, "id": row.id, "campaign_id": row.campaign_id, "region_code": region_code, "region_name": region_name,
        "version_id": row.version_id, "input_fingerprint": row.input_fingerprint, "mode": row.mode, "is_latest": is_latest,
        "computed_by": row.computed_by, "computed_at": row.computed_at,
    })


def _ranked(campaign_id: UUID) -> Any:
    """Per (region, version): rank 1 is the newest verdict, and n counts the history."""
    key = (m.ReadinessVerdict.region_id, m.ReadinessVerdict.version_id)
    return select(
        m.ReadinessVerdict.id,
        func.row_number().over(
            partition_by=key, order_by=(m.ReadinessVerdict.computed_at.desc(), m.ReadinessVerdict.id.desc())
        ).label("rn"),
        func.count().over(partition_by=key).label("n"),
    ).where(m.ReadinessVerdict.campaign_id == campaign_id).subquery()


async def _latest_verdict(s: AsyncSession, campaign_id: UUID, region_id: UUID, version_id: UUID) -> m.ReadinessVerdict | None:
    return (await s.execute(
        select(m.ReadinessVerdict)
        .where(m.ReadinessVerdict.campaign_id == campaign_id, m.ReadinessVerdict.region_id == region_id,
               m.ReadinessVerdict.version_id == version_id)
        .order_by(m.ReadinessVerdict.computed_at.desc(), m.ReadinessVerdict.id.desc()).limit(1)
    )).scalar_one_or_none()


async def compute_readiness(user_id: UUID, campaign_id: UUID, body: v.ReadinessRequest) -> tuple[v.ReadinessVerdict, bool]:
    """Compute and store the verdict. Returns (verdict, created); identical inputs under the same rules return the
    newest stored verdict instead of adding a duplicate row."""
    fp = fingerprint(body.region_code, body.version_id, body.observations)
    now = utcnow()
    async with session() as s, s.begin():
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        require_writable(project)
        region = await _region(s, body.region_code)
        latest = await _latest_verdict(s, campaign.id, region.id, body.version_id)
        # ponytail: two simultaneous identical requests can both insert; history stays correct. Add a unique index on
        # (campaign_id, region_id, version_id, input_fingerprint) if duplicate rows ever matter.
        if latest is not None and latest.input_fingerprint == fp:
            return _verdict_view(latest, region.code, region.name, is_latest=True), False
        assessment = readiness_rules.assess(body.version_id, body.label, body.observations)
        row = m.ReadinessVerdict(
            id=uuid4(), project_id=project.id, campaign_id=campaign.id, region_id=region.id, version_id=body.version_id,
            verdict=assessment.verdict, main_reason=assessment.main_reason, rule_version=assessment.rule_version,
            scoring_version=assessment.scoring_version, overall_score=assessment.score.overall, input_fingerprint=fp,
            inputs=body.observations.model_dump(mode="json"), result=assessment.model_dump(mode="json"),
            mode=project.mode, computed_by=user_id, computed_at=now,
        )
        s.add(row)
        await record_audit(
            s, action="readiness.compute", target_type="readiness_verdict", target_id=str(row.id),
            workspace_id=project.workspace_id, actor_user_id=user_id,
            detail={"region": region.code, "version_id": str(body.version_id), "verdict": row.verdict,
                    "rule_version": row.rule_version},
        )
        touch(project)
        await s.flush()
    return _verdict_view(row, region.code, region.name, is_latest=True), True


async def readiness_history(
    user_id: UUID, campaign_id: UUID, *, region_code: str | None, version_id: UUID | None, limit: int, offset: int
) -> v.ReadinessPage:
    """Every stored verdict, newest first, optionally for one region and version."""
    async with read_session() as s:
        campaign, _ = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        ranked = _ranked(campaign.id)
        stmt = (
            select(m.ReadinessVerdict, ranked.c.rn, m.Region.code, m.Region.name)
            .join(ranked, ranked.c.id == m.ReadinessVerdict.id)
            .join(m.Region, m.Region.id == m.ReadinessVerdict.region_id)
        )
        if region_code is not None:
            stmt = stmt.where(m.Region.id == (await _region(s, region_code)).id)
        if version_id is not None:
            stmt = stmt.where(m.ReadinessVerdict.version_id == version_id)
        rows, total = await paginate(
            s, stmt.order_by(m.ReadinessVerdict.computed_at.desc(), m.ReadinessVerdict.id.desc()), limit, offset
        )
    return v.ReadinessPage(
        items=[_verdict_view(row, code, name, is_latest=rn == 1) for row, rn, code, name in rows],
        limit=limit, offset=offset, total=total,
    )


async def readiness_board(user_id: UUID, campaign_id: UUID) -> v.ReadinessBoard:
    """The newest verdict for every version in every region, with its history size and latest human decision."""
    async with read_session() as s:
        campaign, _ = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        ranked = _ranked(campaign.id)
        verdicts = (await s.execute(
            select(m.ReadinessVerdict, ranked.c.n, m.Region.code, m.Region.name)
            .join(ranked, ranked.c.id == m.ReadinessVerdict.id)
            .join(m.Region, m.Region.id == m.ReadinessVerdict.region_id)
            .where(ranked.c.rn == 1)
            .order_by(m.Region.name, m.ReadinessVerdict.computed_at.desc(), m.ReadinessVerdict.id.desc())
        )).all()
        decisions = await _latest_approvals(s, campaign.id)
    regions: dict[str, v.RegionReadiness] = {}
    for row, count, code, name in verdicts:
        entry = regions.setdefault(code, v.RegionReadiness(region_code=code, region_name=name, versions=[]))
        entry.versions.append(v.VersionReadiness(
            verdict=_verdict_view(row, code, name, is_latest=True), history_count=int(count),
            latest_approval=decisions.get((row.region_id, row.version_id)),
        ))
    return v.ReadinessBoard(campaign_id=campaign.id, regions=list(regions.values()), note=APPROVAL_NOTE)


def readiness_rules_doc() -> v.ReadinessRules:
    return readiness_rules.RULES_DOC


# --- approvals ------------------------------------------------------------------------------------


def _approval_view(row: m.Approval, region_code: str, decided_by_name: str | None) -> v.Approval:
    return v.Approval(
        id=row.id, campaign_id=row.campaign_id, region_code=region_code, version_id=row.version_id,
        decision=row.decision, reason=row.reason, decided_by=row.decided_by,  # type: ignore[arg-type]
        decided_by_name=decided_by_name, decided_at=row.decided_at, readiness_verdict_id=row.readiness_verdict_id,
        verdict_at_decision=row.verdict_at_decision,  # type: ignore[arg-type]
        overrides_recommendation=row.overrides_recommendation, mode=row.mode,  # type: ignore[arg-type]
    )


def _approval_select() -> Any:
    return (
        select(m.Approval, m.Region.code, m.User.display_name)
        .join(m.Region, m.Region.id == m.Approval.region_id)
        .join(m.User, m.User.id == m.Approval.decided_by)
    )


async def _latest_approvals(s: AsyncSession, campaign_id: UUID) -> dict[tuple[UUID, UUID], v.Approval]:
    key = (m.Approval.region_id, m.Approval.version_id)
    ranked = select(
        m.Approval.id,
        func.row_number().over(partition_by=key, order_by=(m.Approval.decided_at.desc(), m.Approval.id.desc())).label("rn"),
    ).where(m.Approval.campaign_id == campaign_id).subquery()
    rows = (await s.execute(_approval_select().join(ranked, ranked.c.id == m.Approval.id).where(ranked.c.rn == 1))).all()
    return {(row.region_id, row.version_id): _approval_view(row, code, name) for row, code, name in rows}


async def record_approval(user_id: UUID, campaign_id: UUID, body: v.ApprovalCreate) -> v.Approval:
    """Record a person's decision on a version for a region, with the recommendation that was in force."""
    now = utcnow()
    async with session() as s, s.begin():
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        if project.access_role not in REVIEW_ROLES:
            raise Forbidden(READ_ONLY)
        if project.status == "archived":
            raise Conflict(ARCHIVED)
        region = await _region(s, body.region_code)
        if body.readiness_verdict_id is not None:
            verdict = await s.get(m.ReadinessVerdict, body.readiness_verdict_id)
            if verdict is None or (verdict.campaign_id, verdict.region_id, verdict.version_id) != (
                campaign.id, region.id, body.version_id
            ):
                raise conflict("readiness_verdict_id", "That verdict does not belong to this campaign, region and version.")
        else:
            verdict = await _latest_verdict(s, campaign.id, region.id, body.version_id)
        recommendation = verdict.verdict if verdict is not None else None
        row = m.Approval(
            id=uuid4(), project_id=project.id, campaign_id=campaign.id, region_id=region.id, version_id=body.version_id,
            decision=body.decision, reason=body.reason, readiness_verdict_id=verdict.id if verdict is not None else None,
            verdict_at_decision=recommendation, overrides_recommendation=body.decision == "approve" and recommendation != "go",
            mode=project.mode, decided_by=user_id, decided_at=now,
        )
        s.add(row)
        await record_audit(
            s, action=f"approval.{body.decision}", target_type="approval", target_id=str(row.id),
            workspace_id=project.workspace_id, actor_user_id=user_id,
            detail={"region": region.code, "version_id": str(body.version_id), "verdict_at_decision": recommendation,
                    "overrides_recommendation": row.overrides_recommendation},
        )
        touch(project)
        name = await s.scalar(select(m.User.display_name).where(m.User.id == user_id))
        await s.flush()
    return _approval_view(row, region.code, name)


async def list_approvals(
    user_id: UUID, campaign_id: UUID, *, region_code: str | None, version_id: UUID | None, limit: int, offset: int
) -> v.ApprovalPage:
    async with read_session() as s:
        campaign, _ = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        stmt = _approval_select().where(m.Approval.campaign_id == campaign.id)
        if region_code is not None:
            stmt = stmt.where(m.Approval.region_id == (await _region(s, region_code)).id)
        if version_id is not None:
            stmt = stmt.where(m.Approval.version_id == version_id)
        rows, total = await paginate(s, stmt.order_by(m.Approval.decided_at.desc(), m.Approval.id.desc()), limit, offset)
    return v.ApprovalPage(items=[_approval_view(row, code, name) for row, code, name in rows], limit=limit, offset=offset, total=total)


async def authorize_read(user_id: UUID, campaign_id: UUID) -> None:
    """404 unless the caller can reach the campaign (used by endpoints that serve static documentation)."""
    async with read_session() as s:
        await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
