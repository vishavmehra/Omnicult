"""Review Links (feature 38): read-only links for stakeholders, scoped to chosen versions and regions.

Owner side (the existing workspace rules): any member lists links and the decisions left on them; creating or revoking a link
needs the owner or editor role on a project that is not archived. The secret is 32 random bytes, shown once, and only its
SHA-256 is stored. A link names (version, region) pairs of one campaign and an expiry (at most 30 days); revoking sets
`revoked_at` and the link stops working at once.

Reviewer side (no account): the secret travels in the Authorization header as `Review <secret>` and never in a URL or a log.
Every failure (unknown, expired, revoked, malformed) is the same 404, so a link reveals nothing about itself. A reviewer sees
the text of the chosen versions, their region and language, and this region's rights-confirmed creative files, and can leave one
decision or comment per call on a pair in scope. Nothing else is reachable: no ids of other versions, no evidence, no
verdicts, no other reviewers' comments. The reviewer's name is optional, typed by them, and never verified: the response says
whether the reviewer gave one. Decisions are advice recorded beside the Launch Room approvals; they never approve anything.

Public endpoints are rate limited per client address and per link (`app.core.ratelimit`), a link accepts a bounded number of
responses, and every response writes an audit entry (ids and the decision only; the reviewer's name and comment are not copied).
"""

import hashlib
import re
import secrets
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict, NotFound
from app.core.ratelimit import SlidingWindow
from app.db import blobs
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas import delivery as d
from app.services.asset_pack import TEXT_KINDS, region_creatives
from app.services.audit import record_audit
from app.services.common import get_owned, not_found, paginate, require_writable, touch
from app.services.versions import node_in

INVALID = "This review link is not valid. It may have expired or been revoked. Ask the person who sent it for a new link."
IDENTITY_NOTE = (
    "You do not need an account. If you give a name, the sender sees it as typed; it is not verified. "
    "Without a name, your response is recorded as anonymous."
)
MAX_TEXT = 2000
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_limiters: dict[str, SlidingWindow] = {}


def _limiter(name: str, limit: int) -> SlidingWindow:
    found = _limiters.get(name)
    if found is None or found.limit != limit:  # a changed setting (tests, a redeploy) starts a fresh window
        found = _limiters[name] = SlidingWindow(limit)
    return found


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def clean(text: str | None) -> str | None:
    """Reviewer-typed text with control characters removed. It is stored and returned as plain text, never as markup."""
    text = _CONTROL.sub("", text or "").strip()
    return text or None


# --- owner side --------------------------------------------------------------------------------------------------------------


def _status(link: m.ReviewLink, now: Any) -> d.LinkStatus:
    if link.revoked_at is not None:
        return "revoked"
    return "expired" if link.expires_at <= now else "active"


async def _summaries(s: AsyncSession, links: list[m.ReviewLink]) -> list[d.ReviewLinkSummary]:
    """Link views with the item labels, the decision counts and the creator's name, in a few batched queries."""
    if not links:
        return []
    version_ids = {UUID(i["version_id"]) for link in links for i in link.items}
    versions = {n.id: n for n in (await s.execute(select(m.VersionNode).where(m.VersionNode.id.in_(version_ids)))).scalars()}
    codes = {i["region_code"] for link in links for i in link.items}
    regions = {r.code: r.name for r in (await s.execute(select(m.Region).where(m.Region.code.in_(codes)))).scalars()}
    counts: dict[UUID, dict[str, int]] = {}
    last: dict[UUID, Any] = {}
    stats = (await s.execute(
        select(m.ReviewResponse.link_id, m.ReviewResponse.decision, func.count(), func.max(m.ReviewResponse.created_at))
        .where(m.ReviewResponse.link_id.in_([link.id for link in links])).group_by(m.ReviewResponse.link_id, m.ReviewResponse.decision)
    )).all()
    for link_id, decision, n, newest in stats:
        counts.setdefault(link_id, {})[decision] = int(n)
        last[link_id] = max(newest, last.get(link_id, newest))
    names = {u.id: u.display_name for u in (await s.execute(select(m.User).where(m.User.id.in_({link.created_by for link in links})))).scalars()}
    now = utcnow()
    out = []
    for link in links:
        c = counts.get(link.id, {})
        out.append(d.ReviewLinkSummary(
            id=link.id, campaign_id=link.campaign_id, label=link.label, note=link.note,
            items=[d.ReviewItemInfo(
                version_id=UUID(i["version_id"]), version_label=versions[UUID(i["version_id"])].label, region_code=i["region_code"],
                region_name=regions.get(i["region_code"], i["region_code"]), language=versions[UUID(i["version_id"])].language)
                for i in link.items],
            token_hint=link.token_hint, status=_status(link, now), expires_at=link.expires_at, revoked_at=link.revoked_at,
            created_at=link.created_at, created_by_name=names.get(link.created_by), response_count=sum(c.values()),
            decisions=d.ReviewDecisionCounts(approve=c.get("approve", 0), request_changes=c.get("request_changes", 0),
                                             reject=c.get("reject", 0), comment=c.get("comment", 0)),
            last_response_at=last.get(link.id), mode=link.mode,  # type: ignore[arg-type]
        ))
    return out


async def create_link(user_id: UUID, campaign_id: UUID, body: d.ReviewLinkCreate) -> d.ReviewLinkCreated:
    secret = secrets.token_urlsafe(32)
    now = utcnow()
    async with session() as s, s.begin():
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        require_writable(project)
        codes = {i.region_code for i in body.items}
        known = set((await s.execute(select(m.Region.code).where(m.Region.code.in_(codes)))).scalars())
        if codes - known:
            raise not_found("Region", "items.region_code")
        for item in body.items:
            await node_in(s, campaign, item.version_id, "items.version_id")
        link = m.ReviewLink(
            id=uuid4(), project_id=project.id, campaign_id=campaign.id, label=body.label, note=body.note,
            items=[{"version_id": str(i.version_id), "region_code": i.region_code} for i in body.items],
            token_hash=hash_secret(secret), token_hint=secret[-4:], expires_at=now + timedelta(days=body.expires_in_days),
            mode=project.mode, created_by=user_id, created_at=now,
        )
        s.add(link)
        await s.flush()
        touch(project)
        await record_audit(
            s, action="review_link.create", target_type="review_link", target_id=str(link.id), workspace_id=project.workspace_id,
            actor_user_id=user_id, detail={"campaign_id": str(campaign.id), "items": len(body.items), "expires_in_days": body.expires_in_days},
        )
        summary = (await _summaries(s, [link]))[0]
    return d.ReviewLinkCreated(**summary.model_dump(), token=secret, review_path=f"/review/{secret}")


async def list_links(user_id: UUID, campaign_id: UUID, limit: int, offset: int) -> d.ReviewLinkPage:
    async with read_session() as s:
        campaign, _ = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        stmt = select(m.ReviewLink).where(m.ReviewLink.campaign_id == campaign.id).order_by(m.ReviewLink.created_at.desc(), m.ReviewLink.id.desc())
        rows, total = await paginate(s, stmt, limit, offset)
        items = await _summaries(s, rows)
    return d.ReviewLinkPage(items=items, limit=limit, offset=offset, total=total)


async def revoke_link(user_id: UUID, link_id: UUID) -> d.ReviewLinkSummary:
    """Stop a link now. Revoking twice leaves the first revocation in place."""
    async with session() as s, s.begin():
        link, project = await get_owned(s, m.ReviewLink, link_id, user_id, "Review link")
        require_writable(project)
        if link.revoked_at is None:
            link.revoked_at, link.revoked_by = utcnow(), user_id
            touch(await s.get(m.Project, project.id))  # type: ignore[arg-type]
            await record_audit(
                s, action="review_link.revoke", target_type="review_link", target_id=str(link.id), workspace_id=project.workspace_id,
                actor_user_id=user_id, detail={"campaign_id": str(link.campaign_id)},
            )
        return (await _summaries(s, [link]))[0]


async def list_responses(
    user_id: UUID, campaign_id: UUID, limit: int, offset: int, *, link_id: UUID | None, version_id: UUID | None
) -> d.ReviewResponsePage:
    async with read_session() as s:
        campaign, _ = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        stmt = (
            select(m.ReviewResponse, m.ReviewLink.label, m.VersionNode.label, m.Region.name)
            .join(m.ReviewLink, m.ReviewLink.id == m.ReviewResponse.link_id)
            .join(m.VersionNode, m.VersionNode.id == m.ReviewResponse.version_id)
            .join(m.Region, m.Region.code == m.ReviewResponse.region_code)
            .where(m.ReviewResponse.campaign_id == campaign.id)
        )
        if link_id is not None:
            stmt = stmt.where(m.ReviewResponse.link_id == link_id)
        if version_id is not None:
            stmt = stmt.where(m.ReviewResponse.version_id == version_id)
        rows, total = await paginate(s, stmt.order_by(m.ReviewResponse.created_at.desc(), m.ReviewResponse.id.desc()), limit, offset)
    return d.ReviewResponsePage(items=[
        d.ReviewResponseView(
            id=r.id, link_id=r.link_id, link_label=link_label, version_id=r.version_id, version_label=version_label, region_code=r.region_code,
            region_name=region_name, decision=r.decision, comment=r.comment, reviewer_name=r.reviewer_name,  # type: ignore[arg-type]
            reviewer_kind=r.reviewer_kind, created_at=r.created_at, mode=r.mode)  # type: ignore[arg-type]
        for r, link_label, version_label, region_name in rows], limit=limit, offset=offset, total=total)


async def feedback_counts(s: AsyncSession, campaign_id: UUID) -> dict[tuple[UUID, str], d.PlanFeedback]:
    """Stakeholder decisions per (version, region), read by the Region Plan."""
    rows = (await s.execute(
        select(m.ReviewResponse.version_id, m.ReviewResponse.region_code, m.ReviewResponse.decision, func.count(), func.max(m.ReviewResponse.created_at))
        .where(m.ReviewResponse.campaign_id == campaign_id)
        .group_by(m.ReviewResponse.version_id, m.ReviewResponse.region_code, m.ReviewResponse.decision)
    )).all()
    found: dict[tuple[UUID, str], dict[str, Any]] = {}
    for version_id, region, decision, n, newest in rows:
        entry = found.setdefault((version_id, region), {"counts": {}, "at": newest})
        entry["counts"][decision] = int(n)
        entry["at"] = max(entry["at"], newest)
    return {
        key: d.PlanFeedback(counts=d.ReviewDecisionCounts(
            approve=e["counts"].get("approve", 0), request_changes=e["counts"].get("request_changes", 0),
            reject=e["counts"].get("reject", 0), comment=e["counts"].get("comment", 0)), latest_at=e["at"])
        for key, e in found.items()}


# --- reviewer side -------------------------------------------------------------------------------------------------------------


def _throttle(secret: str, client: str, *, write: bool = False) -> str:
    """Rate-limit by client address and by link; returns the secret's hash. The same 429 for every caller who goes over."""
    limit = get_settings().review_rate_per_minute
    digest = hash_secret(secret)
    _limiter("ip", limit).check(f"ip:{client}")
    _limiter("link", limit * 3).check(f"link:{digest}")
    if write:
        _limiter("write", max(1, limit // 3)).check(f"ip:{client}")
    return digest


async def _live_link(s: AsyncSession, digest: str) -> tuple[m.ReviewLink, m.Campaign, m.Project]:
    row = (await s.execute(select(m.ReviewLink).where(m.ReviewLink.token_hash == digest))).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.expires_at <= utcnow():
        raise NotFound(INVALID)
    campaign = await s.get(m.Campaign, row.campaign_id)
    project = await s.get(m.Project, row.project_id)
    if campaign is None or project is None:
        raise NotFound(INVALID)
    return row, campaign, project


async def open_review(secret: str, client: str) -> d.ReviewPage:
    digest = _throttle(secret, client)
    async with read_session() as s:
        link, campaign, project = await _live_link(s, digest)
        nodes = {n.id: n for n in (await s.execute(select(m.VersionNode).where(m.VersionNode.id.in_([UUID(i["version_id"]) for i in link.items])))).scalars()}
        regions = {r.code: r.name for r in (await s.execute(select(m.Region).where(m.Region.code.in_({i["region_code"] for i in link.items})))).scalars()}
        brand = await s.scalar(select(m.BrandKit.name).where(m.BrandKit.project_id == project.id))
        items: list[d.ReviewItemView] = []
        for i in link.items:
            node = nodes[UUID(i["version_id"])]
            creatives, _ = await region_creatives(s, campaign.id, i["region_code"])
            items.append(d.ReviewItemView(
                version_id=node.id, version_label=node.label, region_code=i["region_code"], region_name=regions.get(i["region_code"], i["region_code"]),
                language=node.language,
                elements=[d.ReviewElement(id=e["id"], kind=e["kind"], text=e["value"][:MAX_TEXT], language=e.get("language"))
                          for e in node.elements if e.get("kind") in TEXT_KINDS and isinstance(e.get("value"), str) and e["value"].strip()],
                creatives=[d.ReviewCreative(id=c.id, kind=c.kind, label=c.label, content_type=a.content_type, width=a.width, height=a.height)  # type: ignore[arg-type]
                           for c, a in creatives if c.kind in ("image", "video", "audio")],
            ))
    return d.ReviewPage(
        link_label=link.label, note=link.note, campaign_name=campaign.name, brand_name=brand or project.name, expires_at=link.expires_at,
        items=items, decisions=["approve", "request_changes", "reject", "comment"], identity_note=IDENTITY_NOTE, mode=link.mode,  # type: ignore[arg-type]
    )


async def submit(secret: str, client: str, body: d.ReviewSubmit) -> d.ReviewReceipt:
    return await record_response(_throttle(secret, client, write=True), body)


async def record_response(digest: str, body: d.ReviewSubmit) -> d.ReviewReceipt:
    """Store one response for the link whose secret hashes to `digest` (the throttled public path and the demo seed share it)."""
    name, comment = clean(body.reviewer_name), clean(body.comment)
    now = utcnow()
    async with session() as s, s.begin():
        link, campaign, project = await _live_link(s, digest)
        if project.status == "archived":
            raise Conflict("This campaign is archived, so it no longer takes responses.")
        if not any(i["version_id"] == str(body.version_id) and i["region_code"] == body.region_code for i in link.items):
            raise not_found("Version", "version_id")  # a pair outside the link's scope looks like any other missing thing
        used = await s.scalar(select(func.count()).select_from(m.ReviewResponse).where(m.ReviewResponse.link_id == link.id))
        if int(used or 0) >= get_settings().review_max_responses_per_link:
            raise Conflict("This link has reached the number of responses it accepts. Ask the sender for a new link.")
        row = m.ReviewResponse(
            id=uuid4(), link_id=link.id, project_id=project.id, campaign_id=campaign.id, version_id=body.version_id,
            region_code=body.region_code, decision=body.decision, comment=comment, reviewer_name=name,
            reviewer_kind="named" if name else "anonymous", mode=link.mode, created_at=now,
        )
        s.add(row)
        await record_audit(
            s, action="review_link.response", target_type="review_response", target_id=str(row.id), workspace_id=project.workspace_id,
            actor_user_id=None, detail={"link_id": str(link.id), "campaign_id": str(campaign.id), "version_id": str(body.version_id),
                                        "region": body.region_code, "decision": body.decision, "reviewer_kind": row.reviewer_kind},
        )
    return d.ReviewReceipt(id=row.id, version_id=row.version_id, region_code=row.region_code, decision=body.decision,
                           reviewer_kind=row.reviewer_kind, recorded_at=now)  # type: ignore[arg-type]


async def creative_file(secret: str, client: str, creative_id: UUID) -> Response:
    """One creative file of a region in scope, rights confirmed. The file is shown inline in a sandboxed context and cannot run."""
    digest = _throttle(secret, client)
    async with read_session() as s:
        link, campaign, _ = await _live_link(s, digest)
        for region_code in dict.fromkeys(i["region_code"] for i in link.items):
            creatives, _left = await region_creatives(s, campaign.id, region_code)
            hit = next((a for c, a in creatives if c.id == creative_id and c.kind in ("image", "video", "audio")), None)
            if hit is not None:
                break
        else:
            raise NotFound(INVALID)
    data = await blobs.read(hit)
    return Response(
        data, media_type=hit.content_type,
        headers=blobs.CONTENT_HEADERS | {"Content-Disposition": "inline", "Content-Security-Policy": "default-src 'none'; sandbox"},
    )
