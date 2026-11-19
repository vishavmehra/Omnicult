"""Region Plan (feature 39): one launch plan per region, assembled by code from records that already exist.

Inputs, all read fresh (nothing here is stored and no model is called):
- the Campaign Brief: regions, languages, channels, budget split, dates and key moments (Campaign Desk);
- the Moment Calendar: dated moments inside the campaign window and any disagreement between sources (Market Lens);
- the Readiness Board: the newest verdict for each version and its open issues (Launch Room);
- the human approvals: the newest decision on each version for the region (Launch Room);
- stakeholder responses left through Review Links (shown as feedback, never counted as approval);
- the rights-confirmed creative files of the region (the same rule the Asset Pack uses).

The version a plan shows is the one a person approved for the region; with no approval it is the newest version prepared for
the region (a candidate). A region is `ready` only with an approval on top of a Go recommendation; an approval given against a
recommendation other than Go is `ready_with_override` and says so, with the approver's reason. Checklist statuses are fixed
rules over those records: done, todo (nothing recorded yet), warning (recorded, needs a look) and blocked (recorded, stops the
launch). The same blocks feed the Markdown and PDF exports (`proof_render`, `proof_pdf`), so the exports cannot drift.
"""

import asyncio
from datetime import date
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select

from app.core.errors import AppError
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session
from app.schemas import delivery as d
from app.schemas import desk as desk_schema
from app.schemas.lens import LensWindow
from app.services import desk, launch, lens, lens_views, review_links
from app.services.asset_pack import approved_for, region_creatives, slug
from app.services.common import get_owned
from app.services.proof_pdf import to_pdf
from app.services.proof_render import Block, to_markdown

RULE_VERSION = "plan-1"
RULES = [
    "A region's version is the one a person approved for it; with no approval it is the newest version prepared for the region (a candidate).",
    "Ready needs an approval on top of a Go recommendation. An approval given against another recommendation (or none) is ready with override, and says so.",
    "Checklist: done is recorded and fine; todo is nothing recorded yet; warning is recorded and needs a look; blocked is recorded and stops the launch.",
    "Dates come from the brief (key moments, with the sources it cites) and from the Moment Calendar claims inside the campaign window. Sources that disagree stay visible.",
    "Stakeholder responses from Review Links are feedback for the approvers; they never count as an approval.",
]
MAX_CALENDAR_NOTES = 5
FORMATS = {"markdown": ("text/markdown; charset=utf-8", "md"), "pdf": ("application/pdf", "pdf")}


def _money(currency: str, amount: float) -> str:
    return f"{currency} {amount:,.0f}"


def _same_moment(a: str, b: str) -> bool:
    a, b = a.casefold(), b.casefold()
    return a in b or b in a


def _source_titles(content: desk_schema.BriefContent, ids: list[str]) -> str:
    by_id = {s.id: s for s in (content.dates.sources if content.dates else [])}
    names = [(by_id[i].publisher or by_id[i].title) for i in ids if i in by_id]
    return "Brief, source: " + "; ".join(names) if names else "Brief (no source cited)"


def timeline_for(
    region_code: str, content: desk_schema.BriefContent, calendar_moments: list[tuple[date, str, str]]
) -> tuple[list[d.PlanEvent], list[str]]:
    """The region's dated events in order, and the date problems found. `calendar_moments` are (date, name, source) inside the window."""
    dates = content.dates
    if dates is None:
        return [], []
    events = [d.PlanEvent(date=dates.start, kind="campaign_start", title="Campaign starts", source="Brief", warning=None)]
    warnings: list[str] = []
    mine = [km for km in dates.key_moments if not km.region_codes or region_code in km.region_codes]
    by_day: dict[date, list[str]] = {}
    for km in mine:
        by_day.setdefault(km.date, []).append(km.name)
    for km in mine:
        problems = []
        if km.date < dates.start or km.date > dates.end:
            problems.append("Falls outside the campaign dates.")
        if not km.source_ids:
            problems.append("No source is cited for this date.")
        others = [n for n in by_day[km.date] if n != km.name]
        if others:
            problems.append("Same day as " + ", ".join(others) + ".")
        warnings += [f"{km.name} ({km.date.isoformat()}): {p}" for p in problems]
        events.append(d.PlanEvent(date=km.date, kind="key_moment", title=km.name, source=_source_titles(content, km.source_ids),
                                  warning=" ".join(problems) or None))
    for day, name, source in calendar_moments:
        if not any(km.date == day and _same_moment(km.name, name) for km in mine):
            events.append(d.PlanEvent(date=day, kind="calendar_moment", title=name, source=source, warning=None))
    events.append(d.PlanEvent(date=dates.end, kind="campaign_end", title="Campaign ends", source="Brief", warning=None))
    order = {"campaign_start": 0, "key_moment": 1, "calendar_moment": 1, "campaign_end": 2}
    events.sort(key=lambda e: (e.date, order[e.kind], e.title))
    return events, warnings


def ready_state(approval: d.PlanApproval | None, readiness: d.PlanReadiness | None) -> d.PlanReady:
    if approval is None:
        return d.PlanReady(state="not_ready", reasons=["No person has approved a version for this region."])
    if approval.decision != "approve":
        return d.PlanReady(state="not_ready", reasons=[f"The latest decision on this version is {approval.decision.replace('_', ' ')}: {approval.reason}"])
    if readiness is not None and readiness.verdict == "go":
        return d.PlanReady(state="ready", reasons=["Approved on a Go recommendation."])
    recommendation = readiness.verdict.title() if readiness else "no recommendation"
    return d.PlanReady(state="ready_with_override", reasons=[f"Approved against {recommendation}. The approver's reason: {approval.reason}"])


def checklist_for(
    *, region_name: str, languages: list[str], budget: d.PlanBudget | None, has_total: bool, channels: int, has_dates: bool,
    calendar: tuple[str, str] | None, date_warnings: int, version: d.PlanVersion | None, readiness: d.PlanReadiness | None,
    approval: d.PlanApproval | None, creatives: tuple[int, int],
) -> list[d.PlanCheck]:
    """Fixed rules over the records. `calendar` is (state, detail) with state done, todo or none; `creatives` is (usable, registered)."""
    out: list[d.PlanCheck] = []

    def add(item: str, label: str, status: d.PlanStatus, detail: str) -> None:
        out.append(d.PlanCheck(id=item, label=label, status=status, detail=detail))

    add("languages", "Languages set in the brief", "done" if languages else "todo",
        ", ".join(languages) if languages else f"The brief names no languages for {region_name}.")
    if budget:
        add("budget", "Budget set in the brief", "done",
            _money(budget.currency, budget.amount) + (f" ({budget.share_of_total:.0%} of the total)" if budget.share_of_total is not None else "") )
    else:
        add("budget", "Budget set in the brief", "todo",
            "The brief's budget has no amount for this region." if has_total else "The brief has no budget.")
    add("channels", "Channels set in the brief", "done" if channels else "todo", f"{channels} channel{'s' if channels != 1 else ''}." if channels else "The brief names no channels.")
    add("dates", "Campaign dates set in the brief", "done" if has_dates else "todo", "Start and end dates are set." if has_dates else "The brief has no dates.")
    if calendar is None:
        add("moments", "Dates checked against the Moment Calendar", "todo", "Market Lens has no evidence for this brand to check against.")
    elif date_warnings:
        add("moments", "Dates checked against the Moment Calendar", "warning", f"{date_warnings} date point{'s' if date_warnings != 1 else ''} to look at (listed below).")
    else:
        add("moments", "Dates checked against the Moment Calendar", "done" if calendar[0] == "done" else "todo", calendar[1])
    add("version", "A version is prepared for the region", "done" if version else "todo",
        f"{version.label} ({version.state})." if version else f"No Creative Studio version is prepared for {region_name}.")
    if readiness is None:
        add("readiness", "Readiness verdict", "todo", "Not computed yet for this version." if version else "Needs a version first.")
        add("issues", "No open issues", "todo", "Not known until readiness is computed.")
    else:
        add("readiness", "Readiness verdict", {"go": "done", "fix": "warning", "rethink": "blocked"}[readiness.verdict], f"{readiness.verdict.title()}: {readiness.main_reason}")
        if readiness.issues:
            worst = "blocked" if any(i.effect == "rethink" for i in readiness.issues) else "warning"
            rest = f" (+{len(readiness.issues) - 1} more)" if len(readiness.issues) > 1 else ""
            add("issues", "No open issues", worst, readiness.issues[0].summary + rest)
        else:
            add("issues", "No open issues", "done", "The rules found no open issue.")
    if approval is None:
        add("approval", "Approved by a person", "todo", "No decision has been recorded.")
    elif approval.decision == "approve":
        add("approval", "Approved by a person", "warning" if approval.overrides_recommendation else "done",
            f"Approved by {approval.decided_by_name or 'a member'}" + (", against the recommendation." if approval.overrides_recommendation else "."))
    else:
        add("approval", "Approved by a person", "blocked", f"{approval.decision.replace('_', ' ').title()}: {approval.reason}")
    usable, registered = creatives
    if usable:
        add("creatives", "Rights-confirmed creative files", "done", f"{usable} file{'s' if usable != 1 else ''} can go in the pack.")
    elif registered:
        add("creatives", "Rights-confirmed creative files", "warning", "Files are registered, but none has rights confirmed or is made for this region.")
    else:
        add("creatives", "Rights-confirmed creative files", "todo", "No creative file is registered for this region.")
    return out


# --- gathering ----------------------------------------------------------------------------------------------------------------


async def _calendar(
    ctx: Any, region_code: str, window: LensWindow
) -> tuple[tuple[str, str] | None, list[tuple[date, str, str]], list[str], list[str]]:
    """(state, in-window dated moments, undated notes, disagreement warnings) from the Moment Calendar; the state is None when the
    calendar cannot be read for this brand."""
    moments: list[tuple[date, str, str]] = []
    undated: list[str] = []
    stored = False
    conflicts = 0
    try:
        for year in sorted({window.date_from.year, window.date_to.year}):
            cal = await lens_views.calendar(ctx, region_code, year, window)
            stored = stored or bool(cal.months or cal.timed or year in cal.years_available)
            for month in cal.months:
                for item in month.dated:
                    if item.in_window:
                        first = item.claim.sources[0] if item.claim.sources else None
                        moments.append((item.date, item.name, "Moment Calendar" + (f", source: {first.publisher or first.title or first.source_type}" if first else "")))
            conflicts += len(cal.conflicts)
            undated += [f"{t.name}: its sources place it in a month of the campaign but give no exact date." for t in cal.timed if t.may_overlap_window]
    except AppError:
        return None, [], [], []
    warnings = [f"Sources disagree on {conflicts} calendar claim{'s' if conflicts != 1 else ''} for this region; see Market Lens."] if conflicts else []
    detail = f"{len(moments)} dated moment{'s' if len(moments) != 1 else ''} inside the campaign window." if stored else "No festival or moment claims are stored for this region. Build it in Market Lens."
    return ("done" if stored else "todo", detail), sorted(set(moments)), list(dict.fromkeys(undated))[:MAX_CALENDAR_NOTES], warnings


def _readiness_view(entry: Any) -> d.PlanReadiness:
    v = entry.verdict
    return d.PlanReadiness(
        verdict=v.verdict, main_reason=v.main_reason, next_action=v.next_action, computed_at=v.computed_at, rule_version=v.rule_version,
        issues=[d.PlanIssue(rule_id=i.rule_id, priority=i.priority, effect=i.effect, summary=i.summary, action=i.action) for i in v.issues],
    )


def _approval_view(a: Any) -> d.PlanApproval:
    return d.PlanApproval(id=a.id, decision=a.decision, decided_by_name=a.decided_by_name, decided_at=a.decided_at, reason=a.reason,
                          verdict_at_decision=a.verdict_at_decision, overrides_recommendation=a.overrides_recommendation)


async def build_plan(user_id: UUID, campaign_id: UUID) -> d.RegionPlan:
    brief = await desk.get_brief(user_id, campaign_id)  # 404 for a campaign the caller cannot reach
    content = brief.content
    board = await launch.readiness_board(user_id, campaign_id)
    try:
        ctx: Any = await lens.lens_context(user_id, campaign_id)
    except AppError:
        ctx = None
    async with read_session() as s:
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        nodes = list((await s.execute(select(m.VersionNode).where(m.VersionNode.campaign_id == campaign.id).order_by(m.VersionNode.created_at, m.VersionNode.id))).scalars())
        latest = await launch._latest_approvals(s, campaign.id)  # noqa: SLF001
        feedback = await review_links.feedback_counts(s, campaign.id)
        regions = {r.code: r for r in (await s.execute(select(m.Region))).scalars()}
        on_board = {r.region_code: r for r in board.regions}
        codes = list(dict.fromkeys([*([content.regions.origin] if content.regions.origin else []), *content.regions.targets]))
        gaps: list[str] = []
        if not codes:  # no regions in the brief: use the regions that already have a verdict or a decision
            codes = list(dict.fromkeys([*on_board, *(a.region_code for a in latest.values())]))
            gaps.append("The brief names no regions, so the plan lists the regions that already have a verdict or a decision." if codes else "The brief names no regions and nothing has been decided yet.")
        per_region: dict[str, tuple[m.Region, list[Any], int, int]] = {}
        for code in codes:
            region = regions.get(code)
            if region is None:
                gaps.append(f"{code} is not in the region reference data and was left out.")
                continue
            usable, others = await region_creatives(s, campaign.id, code)
            per_region[code] = (region, await approved_for(s, campaign.id, region.id), len(usable), len(usable) + sum(1 for c, _ in others if c.region_code == code))
    budget = content.budget
    total = budget.total if budget else None
    entries = [
        await _entry(code=code, region=region, content=content, ctx=ctx, nodes=nodes, approved=approved, latest=latest, readiness=on_board.get(code),
                     feedback=feedback, usable=usable, registered=registered, total=total, origin=content.regions.origin)
        for code, (region, approved, usable, registered) in per_region.items()
    ]
    window = d.PlanWindow(start=content.dates.start, end=content.dates.end, timezone=content.dates.timezone) if content.dates else None
    if budget and budget.by_region:
        allocated = sum(budget.by_region.values())
        unallocated: float | None = round(budget.total - allocated, 2)
    else:
        unallocated = budget.total if budget else None
    if not brief.saved:
        gaps.append("No Campaign Brief has been saved yet. The plan reads what the campaign record already says.")
    elif not brief.completeness.complete:
        gaps.append("The brief is missing: " + ", ".join(x.replace("_", " ") for x in brief.completeness.missing) + ".")
    demo = project.mode == "demo"
    return d.RegionPlan(
        campaign_id=campaign.id, campaign_name=campaign.name, mode=project.mode, generated_at=utcnow(),  # type: ignore[arg-type]
        rule_version=RULE_VERSION, brief_version=brief.version, window=window, currency=budget.currency if budget else None,
        total_budget=total, budget_sample=bool(budget and budget.sample), unallocated_budget=unallocated, regions=entries, gaps=gaps, notes=RULES,
        source_line="" if demo else f"Source: campaign brief v{brief.version}, Moment Calendar, Readiness Board and recorded approvals.",
    )


async def _entry(
    *, code: str, region: m.Region, content: desk_schema.BriefContent, ctx: Any, nodes: list[m.VersionNode], approved: list[Any],
    latest: dict[tuple[UUID, UUID], Any], readiness: Any, feedback: dict[tuple[UUID, str], d.PlanFeedback], usable: int, registered: int,
    total: float | None, origin: str | None,
) -> d.RegionPlanEntry:
    by_id = {n.id: n for n in nodes}
    chosen_state: d.PlanVersionState = "approved"
    node: m.VersionNode | None = by_id.get(approved[0].version_id) if approved else None
    if node is None:
        chosen_state = "candidate"
        made = [n for n in nodes if n.region_code == code]
        node = made[-1] if made else None
        if node is None and readiness and readiness.versions:
            newest = max(readiness.versions, key=lambda v: v.verdict.computed_at)
            node = by_id.get(newest.verdict.version_id)
    version = d.PlanVersion(version_id=node.id, label=node.label, language=node.language, state=chosen_state) if node else None
    approval_row = latest.get((region.id, node.id)) if node else None
    approval = _approval_view(approval_row) if approval_row else None
    entry_readiness = next((v for v in (readiness.versions if readiness else []) if node and v.verdict.version_id == node.id), None)
    plan_readiness = _readiness_view(entry_readiness) if entry_readiness else None
    languages = list(content.languages.get(code, []))
    budget = None
    if content.budget and code in content.budget.by_region:
        amount = content.budget.by_region[code]
        budget = d.PlanBudget(currency=content.budget.currency, amount=amount, sample=content.budget.sample,
                              share_of_total=round(amount / total, 4) if total else None)
    channels = [d.PlanChannel(id=c.id, name=c.name, format=c.format) for c in content.channels]
    calendar: tuple[str, str] | None = None
    moments: list[tuple[date, str, str]] = []
    info: list[str] = []
    disagreements: list[str] = []
    if ctx is not None and content.dates is not None:
        calendar, moments, info, disagreements = await _calendar(ctx, code, LensWindow(date_from=content.dates.start, date_to=content.dates.end))
    timeline, date_warnings = timeline_for(code, content, moments)
    fb = feedback.get((node.id, code)) if node else None
    fb = fb or d.PlanFeedback(counts=d.ReviewDecisionCounts(approve=0, request_changes=0, reject=0, comment=0), latest_at=None)
    warnings = [*date_warnings, *disagreements]
    date_problems = len(warnings)
    if fb.counts.request_changes or fb.counts.reject:
        warnings.append(f"Stakeholders asked for changes or rejected this version ({fb.counts.request_changes} change requests, {fb.counts.reject} rejections).")
    checks = checklist_for(
        region_name=region.name, languages=languages, budget=budget, has_total=total is not None, channels=len(channels),
        has_dates=content.dates is not None, calendar=calendar if content.dates is not None else ("todo", "The brief has no dates to check."),
        date_warnings=date_problems, version=version, readiness=plan_readiness, approval=approval, creatives=(usable, registered))
    return d.RegionPlanEntry(
        region_code=code, region_name=region.name, role="origin" if code == origin else "target", languages=languages, budget=budget,
        channels=channels, version=version, approval=approval, readiness=plan_readiness, feedback=fb, timeline=timeline, checklist=checks,
        progress_done=sum(c.status == "done" for c in checks), progress_total=len(checks), warnings=warnings, info=info,
        ready=ready_state(approval, plan_readiness), pack_available=chosen_state == "approved" and bool(approved),
    )


# --- exports -----------------------------------------------------------------------------------------------------------------


def plan_blocks(plan: d.RegionPlan) -> list[Block]:
    blocks: list[Block] = [("h1", f"Region Plan: {plan.campaign_name}")]
    when = f"{plan.window.start.isoformat()} to {plan.window.end.isoformat()} ({plan.window.timezone})" if plan.window else "no campaign dates in the brief"
    total = _money(plan.currency, plan.total_budget) if plan.currency and plan.total_budget is not None else "no budget in the brief"
    blocks.append(("p", f"Generated {plan.generated_at.isoformat()[:10]} from campaign brief v{plan.brief_version}. Campaign window: {when}. Total budget: {total}."
                        f" Plan rules {plan.rule_version}. Assembled by code from stored records; no model was called."))
    blocks.append(("table", ["Region", "Role", "Version", "Readiness", "Approval", "Budget", "Ready", "Checklist"], [
        [f"{r.region_name} ({r.region_code})", r.role,
         f"{r.version.label} ({r.version.state})" if r.version else "none",
         r.readiness.verdict.title() if r.readiness else "not computed",
         (r.approval.decision.replace("_", " ") if r.approval else "none"),
         _money(r.budget.currency, r.budget.amount) if r.budget else "none",
         r.ready.state.replace("_", " "), f"{r.progress_done} of {r.progress_total}"] for r in plan.regions]))
    for r in plan.regions:
        blocks.append(("h2", f"{r.region_name} ({r.region_code})"))
        blocks.append(("ul", [
            f"Ready: {r.ready.state.replace('_', ' ')}. " + " ".join(r.ready.reasons),
            "Languages: " + (", ".join(r.languages) or "none set"),
            "Channels: " + (", ".join(c.name for c in r.channels) or "none set"),
            *( [f"Stakeholder responses: {r.feedback.counts.approve} approve, {r.feedback.counts.request_changes} request changes, {r.feedback.counts.reject} reject, {r.feedback.counts.comment} comment."]
               if r.feedback.latest_at else []),
        ]))
        blocks.append(("h3", "Checklist"))
        blocks.append(("table", ["Item", "Status", "Detail"], [[c.label, c.status, c.detail] for c in r.checklist]))
        blocks.append(("h3", "Timeline"))
        blocks.append(("table", ["Date", "Event", "Source", "Warning"], [[e.date.isoformat(), e.title, e.source or "", e.warning or ""] for e in r.timeline]))
        if r.readiness and r.readiness.issues:
            blocks.append(("h3", "Open issues"))
            blocks.append(("table", ["Rule", "Effect", "Issue", "Action"], [[i.rule_id, i.effect, i.summary, i.action] for i in r.readiness.issues]))
        if r.warnings:
            blocks.append(("h3", "Warnings"))
            blocks.append(("ul", r.warnings))
        if r.info:
            blocks.append(("h3", "Also worth knowing"))
            blocks.append(("ul", r.info))
    if plan.gaps:
        blocks += [("h2", "Gaps"), ("ul", plan.gaps)]
    blocks += [("h2", "How this plan is made"), ("ul", plan.notes), *([("p", plan.source_line)] if plan.source_line else [])]
    return blocks


def render(plan: d.RegionPlan, fmt: str) -> tuple[bytes, str, str, list[str]]:
    """(bytes, media type, file name, notices). The Markdown and PDF share one block list with the Proof exports."""
    blocks = plan_blocks(plan)
    media_type, extension = FORMATS[fmt]
    name = f"omnicult-region-plan-{slug(plan.campaign_name, 'campaign', 40)}.{extension}"
    if fmt == "markdown":
        return to_markdown(blocks).encode(), media_type, name, []
    stand_in = cast(Any, SimpleNamespace(title=f"Region Plan: {plan.campaign_name}", version_number=plan.brief_version))  # to_pdf reads only these two
    data, notices = to_pdf(stand_in, blocks)
    return data, media_type, name, notices


async def export(user_id: UUID, campaign_id: UUID, fmt: str) -> tuple[bytes, str, str, list[str]]:
    plan = await build_plan(user_id, campaign_id)
    return await asyncio.to_thread(render, plan, fmt)  # PDF layout is CPU work; keep the event loop free
