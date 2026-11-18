"""Campaign Desk Today: what changed, what is open and what to do next, across the caller's campaigns.

Everything here is read from rows the workspaces already wrote (briefs, runs, operations, verdicts, approvals, creatives,
reports, conflicts). Next actions are fixed rules over those rows; no model writes any of it. The view is bounded: at most
25 brands, 60 campaigns, and 60 rows from each event source before they are merged.
"""

from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session
from app.schemas import desk as v
from app.services import claims
from app.services.common import get_owned, visible_projects
from app.services.desk import REGION_NAME, REQUIRED_LABELS, completeness, derived_content

PROJECT_LIMIT, CAMPAIGN_LIMIT, SOURCE_LIMIT = 25, 60, 60
RUN_META: dict[str, tuple[str, str]] = {
    "market_discovery": ("lens", "Market discovery"), "cultural_profile": ("lens", "Cultural profile"),
    "market_comparison": ("lens", "Market comparison"), "campaign_rehearsal": ("lab", "Campaign rehearsal"),
    "risk_scan": ("lab", "Risk scan"), "population_study": ("lab", "Population study"),
    "social_simulation": ("lab", "Social simulation"), "campaign_adaptation": ("studio", "Campaign adaptation"),
    "transcreate": ("studio", "Transcreation"), "creative_xray": ("studio", "Creative X-Ray"),
    "voice_direct": ("studio", "Voice Director"),
    "campaign_evaluation": ("launch", "Campaign evaluation"), "campaign_arena": ("launch", "Campaign arena"),
}
AUDIENCE_LABEL = {"quick_read": "Quick Read", "audience_study": "Audience Study", "risk_check": "Risk Check", "focus_group": "Focus Group",
                  "buzz_sim": "Buzz Simulator", "message_check": "Message Check"}
OPERATION_LABEL = {
    "manual_edit": "Manual edit", "replace_text": "Text replacement", "transcreate": "Transcreation", "apply_chip": "Tweak Chip",
    "swap_reference": "Reference swap", "change_setting": "Setting change", "tone_shift": "Tone shift", "restore": "Restore",
}
STATUS_WORD = {
    "completed": "finished", "partial": "finished with gaps", "failed": "failed", "running": "is running", "queued": "is queued",
    "cancelled": "was cancelled",
}
VERDICT_WORD = {"go": "Go", "fix": "Fix", "rethink": "Rethink"}
DECISION_WORD = {"approve": "Approved", "reject": "Rejected", "request_changes": "Changes requested"}
LIMITATIONS = [
    "Activity lists rows the workspaces saved: briefs, runs, operations, verdicts, approvals, creatives and reports. Live Pulse refreshes and claim retrievals are not listed.",
    "Next actions are fixed rules over saved records. They are not model suggestions and they do not predict results.",
]


def _run_meta(run_type: str) -> tuple[str, str]:
    if run_type in RUN_META:
        return RUN_META[run_type]
    return ("lens" if "market" in run_type or "cultur" in run_type else "desk", run_type.replace("_", " ").capitalize())


def _message(blob: dict[str, Any] | None) -> str | None:
    text = (blob or {}).get("message")
    return str(text)[:240] if text else None


class _Ctx:
    """The campaigns in scope and the lookups every event source needs."""

    def __init__(self, projects: list[m.Project], campaigns: list[m.Campaign]) -> None:
        self.projects = {p.id: p for p in projects}
        self.campaigns = {c.id: c for c in campaigns}
        self.region: dict[UUID, tuple[str, str]] = {}  # region id -> (code, name)
        self.brands: dict[UUID, str] = {}  # project id -> brand name

    def event(self, kind: str, row_id: Any, at: datetime, workspace: str, title: str, detail: str | None, actor: str | None, project_id: UUID, campaign_id: UUID | None) -> v.TodayEvent:
        project = self.projects[project_id]
        campaign = self.campaigns.get(campaign_id) if campaign_id else None
        return v.TodayEvent(
            id=f"{kind}:{row_id}", at=at, workspace=workspace, kind=kind, title=title, detail=detail, actor=actor,  # type: ignore[arg-type]
            mode=project.mode, project_id=project_id, brand_name=self.brands.get(project_id, project.name), campaign_id=campaign_id,  # type: ignore[arg-type]
            campaign_name=campaign.name if campaign else None,
        )


async def _scope(user_id: UUID, campaign_id: UUID | None) -> _Ctx:
    async with read_session() as s:
        if campaign_id is not None:
            campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
            projects, campaigns = [project], [campaign]
        else:
            stmt = select(m.Project).where(visible_projects(user_id), m.Project.status == "active")
            projects = list((await s.execute(stmt.order_by(m.Project.last_activity_at.desc(), m.Project.id).limit(PROJECT_LIMIT))).scalars())
            ids = [p.id for p in projects]
            stmt = select(m.Campaign).where(m.Campaign.project_id.in_(ids)).order_by(m.Campaign.updated_at.desc(), m.Campaign.id)
            campaigns = list((await s.execute(stmt.limit(CAMPAIGN_LIMIT))).scalars()) if ids else []
        ctx = _Ctx(projects, campaigns)
        ctx.brands = {
            b.project_id: b.name
            for b in (await s.execute(select(m.BrandKit).where(m.BrandKit.project_id.in_([p.id for p in projects])))).scalars()
        }
        ctx.region = {r.id: (r.code, r.name) for r in (await s.execute(select(m.Region))).scalars()}
        return ctx


def _campaign_regions(campaign: m.Campaign, brief: m.CampaignBriefRow | None) -> list[str]:
    if brief is not None:
        regions = v.BriefContent.model_validate(brief.content).regions
        return regions.targets
    return [t["region_code"] for t in campaign.target_markets if isinstance(t, dict) and t.get("region_code") in REGION_NAME]


async def _conflicts(user_id: UUID, ctx: _Ctx, regions_of: dict[UUID, list[str]], *, attached_only: bool) -> list[v.TodayConflict]:
    pairs = {(p.workspace_id, p.mode) for p in ctx.projects.values() if p.workspace_id is not None}
    out: dict[UUID, v.TodayConflict] = {}
    for workspace_id, mode in sorted(pairs, key=str):
        views, _ = await claims.list_conflicts(user_id, workspace_id, region_code=None, status=None, mode=mode, limit=100, offset=0)
        for c in views:
            if c.status == "resolved":
                continue
            ids = [
                cid for cid, camp in ctx.campaigns.items()
                if ctx.projects[camp.project_id].workspace_id == workspace_id and ctx.projects[camp.project_id].mode == mode
                and c.region_code in regions_of.get(cid, [])
            ]
            if attached_only and not ids:
                continue  # a single-campaign view lists only conflicts that touch that campaign
            out[c.id] = v.TodayConflict(
                id=c.id, workspace_id=c.workspace_id, region_code=c.region_code, region_name=REGION_NAME.get(c.region_code or ""),
                status=c.status, reason=c.reason, claim_a=c.claim_a.value_text, claim_b=c.claim_b.value_text,  # type: ignore[arg-type]
                created_at=c.created_at, campaign_ids=ids,
            )
    return sorted(out.values(), key=lambda c: (c.status != "open", c.created_at))[:20]


async def _events(s: AsyncSession, ctx: _Ctx) -> list[v.TodayEvent]:
    cids, pids = list(ctx.campaigns), list(ctx.projects)
    if not cids:
        return []
    out: list[v.TodayEvent] = []
    ev = ctx.event

    def newest(model: Any, column: Any, *where: Any) -> Any:
        return select(model).where(*where).order_by(column.desc()).limit(SOURCE_LIMIT)

    for b in (await s.execute(newest(m.CampaignBriefRow, m.CampaignBriefRow.created_at, m.CampaignBriefRow.campaign_id.in_(cids)))).scalars():
        out.append(ev("brief", b.id, b.created_at, "desk", f"Brief version {b.version_number} saved", b.change_note, "user" if b.created_by else "system", b.project_id, b.campaign_id))
    for k in (await s.execute(newest(m.BrandKitDesignRow, m.BrandKitDesignRow.updated_at, m.BrandKitDesignRow.project_id.in_(pids)))).scalars():
        out.append(ev("brand_kit", k.id, k.updated_at, "desk", f"Brand Kit revision {k.revision} saved", None, "user" if k.updated_by else "system", k.project_id, None))
    for r in (await s.execute(newest(m.AgentRun, m.AgentRun.created_at, m.AgentRun.campaign_id.in_(cids)))).scalars():
        ws, label = _run_meta(r.run_type)
        out.append(ev("run", r.id, r.completed_at or r.started_at or r.created_at, ws, f"{label} {STATUS_WORD.get(r.status, r.status)}", _message(r.error) or _message(r.progress), "ai", r.project_id, r.campaign_id))
    for a in (await s.execute(newest(m.AudienceRun, m.AudienceRun.created_at, m.AudienceRun.campaign_id.in_(cids)))).scalars():
        label = AUDIENCE_LABEL.get(a.kind, a.kind)
        out.append(ev("audience_run", a.id, a.created_at, "lab", f"{label} {STATUS_WORD.get(a.status, a.status)}", _message(a.error), "ai", a.project_id, a.campaign_id))
    for o in (await s.execute(newest(m.Operation, m.Operation.created_at, m.Operation.campaign_id.in_(cids)))).scalars():
        label = OPERATION_LABEL.get(o.kind, o.kind)
        rejected = o.status == "rejected"
        out.append(ev("operation", o.id, o.created_at, "studio", f"{label} {'rejected' if rejected else 'applied'}", (_message(o.rejection) if rejected else None) or o.reason[:240], o.actor, o.project_id, o.campaign_id))
    for c in (await s.execute(newest(m.CreativeAsset, m.CreativeAsset.created_at, m.CreativeAsset.campaign_id.in_(cids)))).scalars():
        out.append(ev("creative", c.id, c.created_at, "studio", "Creative added", c.label, "user", c.project_id, c.campaign_id))
    for d in (await s.execute(newest(m.ReadinessVerdict, m.ReadinessVerdict.computed_at, m.ReadinessVerdict.campaign_id.in_(cids)))).scalars():
        region = ctx.region.get(d.region_id, ("", "a region"))[1]
        out.append(ev("verdict", d.id, d.computed_at, "launch", f"{region}: {VERDICT_WORD.get(d.verdict, d.verdict)}", d.main_reason[:240], "system", d.project_id, d.campaign_id))
    for ap in (await s.execute(newest(m.Approval, m.Approval.decided_at, m.Approval.campaign_id.in_(cids)))).scalars():
        region = ctx.region.get(ap.region_id, ("", "a region"))[1]
        out.append(ev("approval", ap.id, ap.decided_at, "launch", f"{region}: {DECISION_WORD.get(ap.decision, ap.decision)}", ap.reason[:240], "user", ap.project_id, ap.campaign_id))
    for pr in (await s.execute(newest(m.ProofReport, m.ProofReport.created_at, m.ProofReport.campaign_id.in_(cids)))).scalars():
        out.append(ev("proof_report", pr.id, pr.created_at, "proof", f"Proof Report v{pr.version_number} {pr.status}", pr.title[:240], "user" if pr.created_by else "system", pr.project_id, pr.campaign_id))
    return out


async def _facts(s: AsyncSession, cids: list[UUID]) -> dict[str, Any]:
    """Grouped counts and the latest rows the next-action rules read."""
    if not cids:
        return {"creatives": {}, "versions": defaultdict(set), "audience": defaultdict(set), "reports": {}, "verdicts": {}, "runs": {}, "briefs": {}}

    async def grouped(*cols: Any, where: Any) -> list[Any]:
        return list((await s.execute(select(*cols, func.count()).where(where).group_by(*cols))).all())

    creatives = {cid: n for cid, n in await grouped(m.CreativeAsset.campaign_id, where=m.CreativeAsset.campaign_id.in_(cids))}
    reports = {cid: n for cid, n in await grouped(m.ProofReport.campaign_id, where=m.ProofReport.campaign_id.in_(cids))}
    versions: dict[UUID, set[str]] = defaultdict(set)
    for cid, region, _ in await grouped(m.VersionNode.campaign_id, m.VersionNode.region_code, where=m.VersionNode.campaign_id.in_(cids)):
        if region:
            versions[cid].add(region)
    audience: dict[UUID, set[str]] = defaultdict(set)
    done = m.AudienceRun.campaign_id.in_(cids) & m.AudienceRun.status.in_(("completed", "partial"))
    for cid, kind, _ in await grouped(m.AudienceRun.campaign_id, m.AudienceRun.kind, where=done):
        audience[cid].add(kind)
    verdicts: dict[tuple[UUID, UUID], m.ReadinessVerdict] = {}
    stmt = select(m.ReadinessVerdict).where(m.ReadinessVerdict.campaign_id.in_(cids)).order_by(m.ReadinessVerdict.computed_at.desc())
    for d in (await s.execute(stmt)).scalars():
        verdicts.setdefault((d.campaign_id, d.region_id), d)  # newest first: the first row per region is the current one
    runs: dict[tuple[UUID, str], m.AgentRun] = {}
    for r in (await s.execute(select(m.AgentRun).where(m.AgentRun.campaign_id.in_(cids)).order_by(m.AgentRun.created_at.desc()))).scalars():
        runs.setdefault((r.campaign_id, r.run_type), r)  # type: ignore[arg-type]
    briefs: dict[UUID, m.CampaignBriefRow] = {}
    for b in (await s.execute(select(m.CampaignBriefRow).where(m.CampaignBriefRow.campaign_id.in_(cids)).order_by(m.CampaignBriefRow.version_number.desc()))).scalars():
        briefs.setdefault(b.campaign_id, b)
    return {"creatives": creatives, "versions": versions, "audience": audience, "reports": reports, "verdicts": verdicts, "runs": runs, "briefs": briefs}


def _actions(
    campaign: m.Campaign, regions: list[str], brief: m.CampaignBriefRow | None, facts: dict[str, Any], ctx: _Ctx,
    readiness: list[v.TodayReadiness], conflicts: list[v.TodayConflict],
) -> list[v.TodayNextAction]:
    cid = campaign.id
    acts: list[v.TodayNextAction] = []

    def add(key: str, workspace: str, title: str, reason: str, priority: int) -> None:
        acts.append(v.TodayNextAction(id=f"{cid}:{key}", workspace=workspace, title=title, reason=reason, priority=priority))  # type: ignore[arg-type]

    for (run_campaign, run_type), run in facts["runs"].items():
        if run_campaign == cid and run.status in ("failed", "partial"):
            ws, label = _run_meta(run_type)
            add(f"run-{run_type}", ws, f"Review the {label} run that {STATUS_WORD[run.status]}", _message(run.error) or "Open the workspace to retry or read the gaps.", 1)
    for d in readiness:
        if d.verdict != "go":
            add(f"verdict-{d.region_code}", "launch", f"{d.region_name}: {VERDICT_WORD[d.verdict]}", d.main_reason, 1)
    for c in conflicts:
        if cid in c.campaign_ids:
            add(f"conflict-{c.id}", "lens", f"Settle an evidence conflict in {c.region_name or 'a region'}", c.reason, 1)
    done = completeness(v.BriefContent.model_validate(brief.content) if brief else derived_content(campaign))
    if brief is None:
        add("brief", "desk", "Write the campaign brief", "No brief has been saved. Every workspace reads regions, languages and dates from it.", 2)
    elif not done.complete:
        names = ", ".join(REQUIRED_LABELS.get(k, k) for k in done.missing[:3])
        add("brief", "desk", "Complete the campaign brief", f"Still empty: {names}{'' if len(done.missing) <= 3 else ' and more'}.", 2)
    if not facts["creatives"].get(cid):
        add("creative", "studio", "Add the original creative", "Creative X-Ray needs an uploaded image, video or audio file.", 2)
    audience = facts["audience"].get(cid, set())
    if "quick_read" not in audience:
        add("quick-read", "lab", "Run a Quick Read", "No synthetic-panel read of this campaign has finished yet.", 2)
    if "risk_check" not in audience:
        add("risk-check", "lab", "Run a Risk Check", "No risk check has finished, so unsupported claims have not been looked for.", 2)
    for code in regions:
        if code not in facts["versions"].get(cid, set()):
            add(f"version-{code}", "studio", f"No {REGION_NAME[code]} version yet", "Transcreate the original for this region, then score it.", 3)
    scored = {d.region_code for d in readiness}
    for code in regions:
        if code in facts["versions"].get(cid, set()) and code not in scored:
            add(f"score-{code}", "launch", f"Score the {REGION_NAME[code]} version", "The region has a version but no readiness verdict.", 3)
    if readiness and not facts["reports"].get(cid):
        add("report", "proof", "Generate a Proof Report", "Verdicts exist but no report records the evidence behind them.", 3)
    return sorted(acts, key=lambda a: a.priority)[:8]


async def today(user_id: UUID, campaign_id: UUID | None, limit: int) -> v.TodayView:
    ctx = await _scope(user_id, campaign_id)
    async with read_session() as s:
        facts = await _facts(s, list(ctx.campaigns))
    regions_of = {cid: _campaign_regions(c, facts["briefs"].get(cid)) for cid, c in ctx.campaigns.items()}
    conflicts = await _conflicts(user_id, ctx, regions_of, attached_only=campaign_id is not None)
    async with read_session() as s:
        events = await _events(s, ctx)
    events = sorted(events, key=lambda e: e.at, reverse=True)
    if campaign_id is None:
        events = events[:limit]
    else:  # a single campaign also shows the brand-level events of its brand
        events = [e for e in events if e.campaign_id in (campaign_id, None)][:limit]

    last_event: dict[UUID, datetime] = {}
    for e in events:
        if e.campaign_id and e.campaign_id not in last_event:
            last_event[e.campaign_id] = e.at
    cards: list[v.TodayCampaign] = []
    for cid, campaign in ctx.campaigns.items():
        project = ctx.projects[campaign.project_id]
        brief = facts["briefs"].get(cid)
        done = completeness(v.BriefContent.model_validate(brief.content) if brief else derived_content(campaign))
        readiness = sorted(
            (
                v.TodayReadiness(
                    region_code=ctx.region[d.region_id][0], region_name=ctx.region[d.region_id][1], verdict=d.verdict,  # type: ignore[arg-type]
                    main_reason=d.main_reason, computed_at=d.computed_at, version_id=d.version_id, rule_version=d.rule_version,
                )
                for (vc, _), d in facts["verdicts"].items() if vc == cid and d.region_id in ctx.region
            ),
            key=lambda r: r.region_name,
        )
        cards.append(v.TodayCampaign(
            campaign_id=cid, project_id=project.id, name=campaign.name, brand_name=ctx.brands.get(project.id, project.name), mode=project.mode,  # type: ignore[arg-type]
            region_codes=regions_of[cid], brief_version=brief.version_number if brief else 0, brief_complete=done.complete,
            brief_missing=done.missing, readiness=readiness, next_actions=_actions(campaign, regions_of[cid], brief, facts, ctx, readiness, conflicts),
            last_activity_at=last_event.get(cid) or campaign.updated_at,
        ))
    return v.TodayView(generated_at=utcnow(), campaigns=cards, activity=events, conflicts=conflicts, limitations=LIMITATIONS)
