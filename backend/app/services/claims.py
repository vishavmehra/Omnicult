"""Claims: persist `ClaimDraft`s, recompute confidence in code, record conflicts, and report evidence quality.

Producers (the culture sources) hand over drafts; nothing a draft says about confidence is trusted, because drafts carry
none. A repeated retrieval of the same statement adds its sources to the existing claim instead of duplicating it.
Shared reference claims have `workspace_id` NULL, are visible to every workspace and are never changed by one workspace.
"""

import hashlib
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import get_args
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.confidence import (
    Candidate,
    compute_confidence,
    detect_conflicts,
    freshness_cutoff,
    is_observation,
    is_stale,
    recommend_selection,
    scope_key,
    source_date,
    value_fingerprint,
)
from app.core.errors import Conflict as ConflictError
from app.core.errors import NotFound
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas import regions as v
from app.schemas.claims import ClaimCategory, ClaimDraft, ClaimScope
from app.services.audit import record_audit
from app.services.identity import REVIEW_ROLES, require_workspace_role
from app.services.regions import languages_by_region, to_region

CATEGORIES: tuple[str, ...] = get_args(ClaimCategory)
LIVE_STATUSES = ("active", "needs_review")  # claims that are shown and compared; rejected and superseded are history
KIND_STRENGTH = {"observed": 0, "calculated": 1, "synthetic": 2, "interpretation": 3, "unverified": 4}
NO_SOURCE_KINDS = frozenset({"interpretation", "unverified"})
DOWNGRADE = {"high": "moderate", "moderate": "low", "low": "low"}

# Evidence Meter thresholds. A region below any "partial" bar is weak; "solid" needs every bar (documented in docs/).
WEAK_MIN_SUPPORTED = 5
WEAK_MIN_CATEGORIES = 3
SOLID_MIN_SUPPORTED = 15
SOLID_MIN_CATEGORIES = 6
SOLID_MAX_STALE_SHARE = 0.25
SOLID_MIN_MODERATE_SHARE = 0.5


@dataclass
class UpsertResult:
    claims: list[m.Claim] = field(default_factory=list)
    created: int = 0
    updated: int = 0
    conflicts_opened: int = 0
    rejected: list[tuple[int, str]] = field(default_factory=list)  # (index in the input list, why it was not stored)


def claim_key(workspace_id: UUID | None, mode: str, draft: ClaimDraft) -> str:
    """Identity of a statement: who owns it, subject, attribute, scope and value (not its kind or sources)."""
    parts = [str(workspace_id or "shared"), mode, draft.subject, draft.attribute, scope_key(draft.scope),
             value_fingerprint(draft.value)]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _draft_problem(draft: ClaimDraft) -> str | None:
    if draft.kind not in NO_SOURCE_KINDS and not draft.sources:
        return f"A {draft.kind} claim needs at least one source."
    if not draft.value_text.strip():
        return "value_text is empty."
    return None


async def upsert_claims(
    s: AsyncSession, drafts: list[ClaimDraft], *, workspace_id: UUID | None, mode: str = "live", now: datetime | None = None
) -> UpsertResult:
    """Store drafts as claims (adding sources to claims that already exist), recompute every touched claim's
    confidence, and record conflicts for the workspace. Invalid drafts are reported in `rejected`, never stored."""
    now = now or utcnow()
    result = UpsertResult()
    region_ids: dict[str, UUID | None] = {}
    touched: list[m.Claim] = []
    for index, draft in enumerate(drafts):
        problem = _draft_problem(draft)
        if problem:
            result.rejected.append((index, problem))
            continue
        code = draft.scope.region_code
        if code and code not in region_ids:
            region_ids[code] = await s.scalar(select(m.Region.id).where(m.Region.code == code))
        key = claim_key(workspace_id, mode, draft)
        claim = await s.scalar(select(m.Claim).where(m.Claim.claim_key == key))
        if claim is None:
            claim = m.Claim(
                id=uuid4(), workspace_id=workspace_id, region_id=region_ids.get(code) if code else None, claim_key=key,
                subject=draft.subject, attribute=draft.attribute, category=draft.category, value=draft.value,
                value_text=draft.value_text, scope=draft.scope.model_dump(), kind=draft.kind, confidence="low",
                confidence_reason="", published_at=draft.published_at, retrieved_at=draft.retrieved_at,
                expires_at=draft.expires_at, status="active", mode=mode, created_at=now, updated_at=now,
            )
            s.add(claim)
            await s.flush()
            result.created += 1
        else:
            _merge_into(claim, draft, now)
            result.updated += 1
        existing = {(src.source_type, src.source_identifier) for src in await _sources(s, [claim.id])}
        for ref in draft.sources:
            if (ref.source_type, ref.source_identifier) not in existing:
                existing.add((ref.source_type, ref.source_identifier))
                s.add(m.ClaimSource(id=uuid4(), claim_id=claim.id, **ref.model_dump()))
        await s.flush()
        await recompute_confidence(s, claim, now=now)
        touched.append(claim)
    result.claims = touched
    if workspace_id is not None and touched:
        keys = {(c.subject, c.attribute) for c in touched}
        result.conflicts_opened = await sync_conflicts(s, workspace_id, mode=mode, keys=keys, now=now)
    return result


def _merge_into(claim: m.Claim, draft: ClaimDraft, now: datetime) -> None:
    """A re-retrieved statement keeps its identity: newest dates win and the strongest kind wins."""
    if KIND_STRENGTH[draft.kind] < KIND_STRENGTH[claim.kind]:
        claim.kind = draft.kind
    claim.retrieved_at = max(claim.retrieved_at, draft.retrieved_at)
    if draft.published_at and (claim.published_at is None or draft.published_at > claim.published_at):
        claim.published_at = draft.published_at
    if draft.expires_at and (claim.expires_at is None or draft.expires_at > claim.expires_at):
        claim.expires_at = draft.expires_at
    claim.updated_at = now


async def _sources(s: AsyncSession, ids: list[UUID]) -> list[m.ClaimSource]:
    rows = await s.execute(select(m.ClaimSource).where(m.ClaimSource.claim_id.in_(ids)))
    return list(rows.scalars())


async def recompute_confidence(s: AsyncSession, claim: m.Claim, *, now: datetime) -> None:
    """Set confidence and its reason from the claim's sources. The only place a claim's confidence is written."""
    sources = await _sources(s, [claim.id])
    level, reason = compute_confidence(
        claim.kind,  # type: ignore[arg-type]
        sources,
        now=now,
        reviewer_confirmed=any(src.source_type == "reviewer" for src in sources),
        campaign_agreement=any(src.source_type == "campaign_result" for src in sources),
    )
    claim.confidence, claim.confidence_reason, claim.updated_at = level, reason, now


# --- conflicts ----------------------------------------------------------------------------


async def sync_conflicts(
    s: AsyncSession, workspace_id: UUID, *, mode: str = "live", region_id: UUID | None = None,
    keys: set[tuple[str, str]] | None = None, now: datetime | None = None,
) -> int:
    """Record, for one workspace, every pair of visible claims (its own plus shared ones) that disagree. Idempotent:
    existing conflicts are kept as they are, including their decisions. Returns the number of new conflicts."""
    now = now or utcnow()
    stmt = select(m.Claim).where(
        or_(m.Claim.workspace_id == workspace_id, m.Claim.workspace_id.is_(None)),
        m.Claim.mode == mode, m.Claim.status.in_(LIVE_STATUSES),
    )
    if region_id is not None:
        stmt = stmt.where(m.Claim.region_id == region_id)
    if keys:
        stmt = stmt.where(or_(*[and_(m.Claim.subject == sub, m.Claim.attribute == attr) for sub, attr in keys]))
    claims = list((await s.execute(stmt.order_by(m.Claim.created_at, m.Claim.id))).scalars())
    found = detect_conflicts(claims)
    if not found:
        return 0
    sources: dict[UUID, list[m.ClaimSource]] = defaultdict(list)
    for src in await _sources(s, [c.id for c in claims]):
        sources[src.claim_id].append(src)
    opened = 0
    for draft in found:
        first, second = sorted((draft.claim_a, draft.claim_b), key=lambda c: c.id.int)
        exists = await s.scalar(select(m.Conflict.id).where(
            m.Conflict.workspace_id == workspace_id, m.Conflict.claim_a_id == first.id, m.Conflict.claim_b_id == second.id))
        if exists is not None:
            continue
        choice, why = recommend_selection(_candidate(first, sources), _candidate(second, sources))
        s.add(m.Conflict(
            id=uuid4(), workspace_id=workspace_id, region_id=first.region_id or second.region_id, claim_a_id=first.id,
            claim_b_id=second.id, reason=draft.reason, current_selection=choice, selection_reason=why, status="open",
            created_at=now, updated_at=now,
        ))
        opened += 1
    await s.flush()
    return opened


def _candidate(claim: m.Claim, sources: dict[UUID, list[m.ClaimSource]]) -> Candidate:
    dates = [source_date(src) for src in sources.get(claim.id, []) if is_observation(src)]
    specificity = sum(1 for k, val in claim.scope.items() if k != "country" and val)
    return Candidate(claim.kind, claim.confidence, max(dates) if dates else None, specificity)


async def resolve_conflict(
    user_id: UUID, workspace_id: UUID, conflict_id: UUID, decision: str, note: str | None
) -> v.Conflict:
    """Record a reviewer's decision: accept the value in use, switch to the other, or request a native review."""
    now = utcnow()
    async with session() as s, s.begin():
        await require_workspace_role(s, user_id, workspace_id, REVIEW_ROLES)
        conflict = await s.scalar(select(m.Conflict).where(m.Conflict.id == conflict_id, m.Conflict.workspace_id == workspace_id))
        if conflict is None:
            raise NotFound("Conflict was not found.")
        if decision == "switch":
            conflict.current_selection = "b" if conflict.current_selection == "a" else "a"
            conflict.selection_reason = f"Switched by a reviewer on {now.date().isoformat()}."
            conflict.status = "resolved"
        elif decision == "accept":
            conflict.selection_reason = f"Accepted by a reviewer on {now.date().isoformat()}."
            conflict.status = "resolved"
        elif decision == "request_review":
            conflict.status = "review_requested"
        else:
            raise ConflictError("Unknown decision.")
        conflict.updated_at = now
        s.add(m.ConflictResolution(
            id=uuid4(), conflict_id=conflict.id, decided_by=user_id, decision=decision,
            selection_after=conflict.current_selection, note=note, decided_at=now,
        ))
        await record_audit(
            s, action=f"conflict.{decision}", target_type="conflict", target_id=str(conflict.id),
            workspace_id=workspace_id, actor_user_id=user_id, detail={"status": conflict.status},
        )
        await s.flush()
        views = await _conflict_views(s, workspace_id, [conflict])
    return views[0]


async def list_conflicts(
    user_id: UUID, workspace_id: UUID, *, region_code: str | None, status: str | None, mode: str, limit: int, offset: int
) -> tuple[list[v.Conflict], int]:
    """The workspace's conflicts, open first. Conflicts among visible claims that were never recorded (shared reference
    claims that disagree) are recorded first, so a workspace sees every disagreement it relies on."""
    region_id: UUID | None = None
    async with session() as s, s.begin():
        await require_workspace_role(s, user_id, workspace_id)
        if region_code is not None:
            region_id = await s.scalar(select(m.Region.id).where(m.Region.code == region_code))
            if region_id is None:
                raise NotFound("Region was not found.")
        await sync_conflicts(s, workspace_id, mode=mode, region_id=region_id)
    async with read_session() as s:
        stmt = select(m.Conflict).where(m.Conflict.workspace_id == workspace_id)
        if region_id is not None:
            stmt = stmt.where(m.Conflict.region_id == region_id)
        if status is not None:
            stmt = stmt.where(m.Conflict.status == status)
        stmt = stmt.order_by(
            (m.Conflict.status == "resolved"), m.Conflict.created_at, m.Conflict.id
        )
        rows = list((await s.execute(stmt)).scalars())
        page = rows[offset : offset + limit]
        return await _conflict_views(s, workspace_id, page), len(rows)


async def _conflict_views(s: AsyncSession, workspace_id: UUID, conflicts: list[m.Conflict]) -> list[v.Conflict]:
    if not conflicts:
        return []
    claim_ids = {c.claim_a_id for c in conflicts} | {c.claim_b_id for c in conflicts}
    open_by_claim = await _open_conflicts_by_claim(s, workspace_id)
    claims = {c.id: c for c in (await s.execute(select(m.Claim).where(m.Claim.id.in_(claim_ids)))).scalars()}
    sources: dict[UUID, list[m.ClaimSource]] = defaultdict(list)
    for src in await _sources(s, list(claim_ids)):
        sources[src.claim_id].append(src)
    regions = {r.id: r.code for r in (await s.execute(select(m.Region))).scalars()}
    history: dict[UUID, list[m.ConflictResolution]] = defaultdict(list)
    rows = await s.execute(
        select(m.ConflictResolution).where(m.ConflictResolution.conflict_id.in_([c.id for c in conflicts]))
        .order_by(m.ConflictResolution.decided_at, m.ConflictResolution.id)
    )
    for row in rows.scalars():
        history[row.conflict_id].append(row)
    now = utcnow()
    return [
        v.Conflict(
            id=c.id, workspace_id=c.workspace_id, region_code=regions.get(c.region_id) if c.region_id else None,
            status=c.status,  # type: ignore[arg-type]
            reason=c.reason, current_selection=c.current_selection,  # type: ignore[arg-type]
            selection_reason=c.selection_reason,
            claim_a=_claim_view(claims[c.claim_a_id], sources, open_by_claim, now),
            claim_b=_claim_view(claims[c.claim_b_id], sources, open_by_claim, now),
            resolutions=[
                v.ConflictResolutionView(
                    id=r.id, decision=r.decision, selection_after=r.selection_after,  # type: ignore[arg-type]
                    note=r.note, decided_by=r.decided_by, decided_at=r.decided_at,
                )
                for r in history[c.id]
            ],
            created_at=c.created_at, updated_at=c.updated_at,
        )
        for c in conflicts
    ]


async def _open_conflicts_by_claim(s: AsyncSession, workspace_id: UUID) -> dict[UUID, list[UUID]]:
    """Claim id -> unresolved conflicts it is part of (open or waiting for a review) in this workspace."""
    rows = await s.execute(
        select(m.Conflict.id, m.Conflict.claim_a_id, m.Conflict.claim_b_id)
        .where(m.Conflict.workspace_id == workspace_id, m.Conflict.status != "resolved")
    )
    by_claim: dict[UUID, list[UUID]] = defaultdict(list)
    for conflict_id, a, b in rows.all():
        by_claim[a].append(conflict_id)
        by_claim[b].append(conflict_id)
    return by_claim


# --- views --------------------------------------------------------------------------------


def _claim_view(
    claim: m.Claim, sources: dict[UUID, list[m.ClaimSource]], open_by_claim: dict[UUID, list[UUID]], now: datetime
) -> v.ClaimView:
    claim_sources = sorted(sources.get(claim.id, []), key=lambda src: (source_date(src), src.source_identifier), reverse=True)
    conflict_ids = open_by_claim.get(claim.id, [])
    return v.ClaimView(
        id=claim.id, shared=claim.workspace_id is None, subject=claim.subject, attribute=claim.attribute,
        category=claim.category,  # type: ignore[arg-type]
        value=claim.value, value_text=claim.value_text, scope=ClaimScope.model_validate(claim.scope),
        kind=claim.kind,  # type: ignore[arg-type]
        confidence=claim.confidence,  # type: ignore[arg-type]
        effective_confidence=DOWNGRADE[claim.confidence] if conflict_ids else claim.confidence,  # type: ignore[arg-type]
        confidence_reason=claim.confidence_reason,
        sources=[
            v.SourceView(
                id=src.id, source_type=src.source_type, source_identifier=src.source_identifier, url=src.url,
                title=src.title, publisher=src.publisher, published_at=src.published_at, retrieved_at=src.retrieved_at,
                excerpt=src.excerpt, independence_group=src.independence_group,
            )
            for src in claim_sources
        ],
        published_at=claim.published_at, retrieved_at=claim.retrieved_at, expires_at=claim.expires_at,
        status=claim.status,  # type: ignore[arg-type]
        stale=_claim_stale(claim, claim_sources, now), conflict_ids=conflict_ids,
    )


def _claim_stale(claim: m.Claim, sources: list[m.ClaimSource], now: datetime) -> bool:
    if claim.expires_at is not None and claim.expires_at <= now:
        return True
    return any(is_observation(src) for src in sources) and is_stale(sources, now=now)


async def build_region_profile(
    user_id: UUID, workspace_id: UUID, region_code: str, *, mode: str = "live", now: datetime | None = None
) -> v.RegionProfile:
    """The region, its Evidence Meter, and its claims grouped by category (every category is listed, empty ones too)."""
    now = now or utcnow()
    async with session() as s, s.begin():  # a write session: unrecorded conflicts between visible claims are recorded
        await require_workspace_role(s, user_id, workspace_id)
        region = await s.scalar(select(m.Region).where(m.Region.code == region_code, m.Region.is_active))
        if region is None:
            raise NotFound("Region was not found.")
        await sync_conflicts(s, workspace_id, mode=mode, region_id=region.id, now=now)
    async with read_session() as s:
        claims = list((await s.execute(
            select(m.Claim).where(
                or_(m.Claim.workspace_id == workspace_id, m.Claim.workspace_id.is_(None)),
                m.Claim.region_id == region.id, m.Claim.mode == mode, m.Claim.status.in_(LIVE_STATUSES),
            ).order_by(m.Claim.category, m.Claim.attribute, m.Claim.created_at, m.Claim.id)
        )).scalars())
        sources: dict[UUID, list[m.ClaimSource]] = defaultdict(list)
        for src in await _sources(s, [c.id for c in claims]) if claims else []:
            sources[src.claim_id].append(src)
        open_by_claim = await _open_conflicts_by_claim(s, workspace_id)
        review_requested = (await s.execute(
            select(m.Conflict.claim_a_id, m.Conflict.claim_b_id)
            .where(m.Conflict.workspace_id == workspace_id, m.Conflict.status == "review_requested")
        )).all()
        languages = (await languages_by_region(s, [region.id]))[region.id]
    views = [_claim_view(c, sources, open_by_claim, now) for c in claims]
    flagged = {claim_id for pair in review_requested for claim_id in pair}
    meter = compute_meter(region, workspace_id, mode, claims, sources, views, flagged, now)
    return v.RegionProfile(
        region=to_region(region, languages), workspace_id=workspace_id, mode=mode,  # type: ignore[arg-type]
        meter=meter,
        categories=[v.CategoryClaims(category=cat, claims=[c for c in views if c.category == cat]) for cat in CATEGORIES],  # type: ignore[arg-type]
    )


def compute_meter(
    region: m.Region, workspace_id: UUID, mode: str, claims: list[m.Claim], sources: dict[UUID, list[m.ClaimSource]],
    views: list[v.ClaimView], flagged: set[UUID], now: datetime,
) -> v.EvidenceMeter:
    """Evidence Meter (handoff 6.4). Deterministic; thresholds are the module constants above."""
    distinct = {(src.source_type, src.source_identifier): src for c in claims for src in sources.get(c.id, [])}
    dates = sorted(source_date(src) for src in distinct.values())
    cutoff = freshness_cutoff(now)
    supported = {c.id for c in claims if c.kind in ("observed", "calculated") and any(is_observation(x) for x in sources.get(c.id, []))}
    by_category = {cat: [c for c in claims if c.category == cat] for cat in CATEGORIES}
    coverage = [
        v.CategoryCoverage(category=cat, claims=len(items), supported_claims=sum(1 for c in items if c.id in supported))  # type: ignore[arg-type]
        for cat, items in by_category.items()
    ]
    covered = sum(1 for item in coverage if item.supported_claims > 0)
    stale = sum(1 for view in views if view.stale)
    needs_review = sum(
        1 for c in claims if c.status == "needs_review" or c.kind in NO_SOURCE_KINDS or c.id in flagged
    )
    open_conflicts = len({cid for view in views for cid in view.conflict_ids})
    breakdown = v.ConfidenceBreakdown(
        low=sum(1 for c in claims if c.confidence == "low"),
        moderate=sum(1 for c in claims if c.confidence == "moderate"),
        high=sum(1 for c in claims if c.confidence == "high"),
    )
    strength, reasons = _strength(len(claims), len(supported), covered, open_conflicts, stale, breakdown)
    freshness = v.SourceFreshness(
        newest_source_date=dates[-1] if dates else None,
        oldest_source_date=dates[0] if dates else None,
        median_age_days=int(statistics.median((now.date() - d).days for d in dates)) if dates else None,
        fresh_source_share=round(sum(1 for d in dates if d > cutoff) / len(dates), 3) if dates else None,
    )
    return v.EvidenceMeter(
        region_code=region.code, region_name=region.name, workspace_id=workspace_id, mode=mode,  # type: ignore[arg-type]
        sources=len(distinct), claims=len(claims), supported_claims=len(supported), freshness=freshness,
        categories_total=len(CATEGORIES), categories_covered=covered, coverage=coverage, open_conflicts=open_conflicts,
        stale_claims=stale, needs_review_claims=needs_review, confidence=breakdown, strength=strength,  # type: ignore[arg-type]
        strength_reasons=reasons,
    )


def _strength(
    total: int, supported: int, covered: int, open_conflicts: int, stale: int, breakdown: v.ConfidenceBreakdown
) -> tuple[str, list[str]]:
    if total == 0:
        return "weak", ["No claims are recorded for this region yet."]
    weak = []
    if supported < WEAK_MIN_SUPPORTED:
        weak.append(f"Only {supported} supported claims (at least {WEAK_MIN_SUPPORTED} needed to rate beyond weak).")
    if covered < WEAK_MIN_CATEGORIES:
        weak.append(f"Only {covered} categories have a supported claim (at least {WEAK_MIN_CATEGORIES} needed).")
    if breakdown.moderate + breakdown.high == 0:
        weak.append("No claim reaches Moderate confidence.")
    if weak:
        return "weak", weak
    gaps = []
    if supported < SOLID_MIN_SUPPORTED:
        gaps.append(f"{supported} supported claims; {SOLID_MIN_SUPPORTED} needed for solid.")
    if covered < SOLID_MIN_CATEGORIES:
        gaps.append(f"{covered} categories covered; {SOLID_MIN_CATEGORIES} needed for solid.")
    if open_conflicts:
        gaps.append(f"{open_conflicts} unresolved conflict(s).")
    if stale / total > SOLID_MAX_STALE_SHARE:
        gaps.append(f"{stale} of {total} claims are stale.")
    if (breakdown.moderate + breakdown.high) / total < SOLID_MIN_MODERATE_SHARE:
        gaps.append("Fewer than half of the claims reach Moderate confidence.")
    return ("partial", gaps) if gaps else ("solid", [])
