"""Weekly Digest content: everything in a digest is computed here, by code, from stored records.

A week is an ISO week in India Standard Time (Monday to Sunday). Four kinds of record feed it:
  * what changed: records created inside the week (creative versions, verdicts, approvals, runs, conflicts, findings);
  * Pulse movement: the 7 settled days of Live Pulse data ending on the last settled day on or before the week's end,
    against the 7 days before them. Provisional days never enter a comparison. Alerts come from the same fixed rules as
    the Pulse alert preview, run over the data up to that day;
  * comments: the comments Comment Pulse shows (the YouTube comments of a live campaign that has any, otherwise the sample).
    A YouTube comment counts for the week it was published in; sample comments count in that same data window. Sentiment and
    themes are the stored model reading of that source, where one exists;
  * open items and next actions: what is open when the digest is generated, and a short list produced by fixed rules.
No model is called here. The numbers a reader sees are the numbers computed below.
"""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.schemas import digest as d
from app.services import comment_pulse as comments_service
from app.services import comment_youtube as youtube
from app.services.campaign_regions import campaign_region_codes
from app.services.pulse_alerts import AlertConfig, evaluate
from app.services.pulse_metrics import BY_NAME, SeriesRow, values_of

IST = timezone(timedelta(hours=5, minutes=30), "IST")
HEADLINE = ("impressions", "spend", "ctr", "cpm", "cpa", "roas")
WINDOW_DAYS = 7
MAX_LISTED = 12
MAX_ACTIONS = 8
MAX_FLAGGED = 6
MAX_THEMES = 3
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
USABLE_RUNS = ("completed", "partial")
PULSE_SOURCE = ""
COMMENT_SOURCE = ""
LIMITATIONS = (
    "Open items are read when the digest is generated; they are not rebuilt as they stood on the last day of the week.",
    "A week uses India Standard Time. Pulse movement compares the last 7 settled days on or before the week's end with the "
    "7 days before them; provisional days (still being reported) are left out.",
    "Differences between periods are descriptive. They are not an experiment and say nothing about cause.",
    "Counts and deltas are computed by code from stored records. Anything marked Model interpretation was written by a "
    "model and is a hypothesis to judge, not a measurement.",
)


# --- weeks -----------------------------------------------------------------------------------------------------


def week_of(day: date) -> d.DigestWeek:
    monday = day - timedelta(days=day.weekday())
    iso = monday.isocalendar()
    return d.DigestWeek(
        iso_year=iso.year, iso_week=iso.week, label=f"{iso.year}-W{iso.week:02d}", start=monday, end=monday + timedelta(days=6))


def current_week(now: datetime) -> d.DigestWeek:
    return week_of(now.astimezone(IST).date())


def last_completed_week(now: datetime) -> d.DigestWeek:
    return week_of(current_week(now).start - timedelta(days=1))


def week_bounds(week: d.DigestWeek) -> tuple[datetime, datetime]:
    """[start, end) of the week as UTC instants: Monday 00:00 IST up to the next Monday 00:00 IST."""
    lo = datetime.combine(week.start, time.min, tzinfo=IST)
    return lo.astimezone(UTC), (lo + timedelta(days=7)).astimezone(UTC)


# --- formatting (shared by the facts a model may restate and the exports) ----------------------------------------


def fmt(unit: str, value: float | None) -> str:
    if value is None:
        return "n/a"
    if unit == "ratio":
        return f"{value * 100:.2f}%"
    if unit == "inr":
        return f"INR {value:,.2f}" if abs(value) < 1000 else f"INR {value:,.0f}"
    if unit == "multiple":
        return f"{value:.2f}x"
    return f"{value:,.0f}"


def fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.1f}%"


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


# --- shared context ----------------------------------------------------------------------------------------------


@dataclass
class Subject:
    project: m.Project
    campaign: m.Campaign
    regions: dict[str, tuple[UUID, str]]  # target region code -> (region id, name)

    def name(self, code: str | None) -> str | None:
        if code is None:
            return None
        return self.regions[code][1] if code in self.regions else comments_service.REGION_NAMES.get(code, code)


async def subject_of(s: AsyncSession, project: m.Project, campaign: m.Campaign) -> Subject:
    codes, _ = campaign_region_codes(campaign.target_markets, None)
    found = (await s.execute(select(m.Region.code, m.Region.id, m.Region.name).where(m.Region.code.in_(codes)))).all() if codes else []
    return Subject(project, campaign, {c: (rid, name) for c, rid, name in found})


# --- what changed ----------------------------------------------------------------------------------------------


async def _count(s: AsyncSession, stmt) -> int:  # noqa: ANN001
    return int(await s.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


async def what_changed(s: AsyncSession, sub: Subject, week: d.DigestWeek) -> d.DigestWhatChanged:
    lo, hi = week_bounds(week)
    cid = sub.campaign.id
    region_ids = [rid for rid, _ in sub.regions.values()]

    nodes = select(m.VersionNode).where(m.VersionNode.campaign_id == cid, m.VersionNode.created_at >= lo, m.VersionNode.created_at < hi)
    node_total = await _count(s, nodes)
    node_rows = list((await s.execute(nodes.order_by(m.VersionNode.created_at.desc(), m.VersionNode.id).limit(MAX_LISTED))).scalars())

    verdicts = (
        select(m.ReadinessVerdict, m.Region.code, m.Region.name, m.VersionNode.label)
        .join(m.Region, m.Region.id == m.ReadinessVerdict.region_id)
        .join(m.VersionNode, m.VersionNode.id == m.ReadinessVerdict.version_id)
        .where(m.ReadinessVerdict.campaign_id == cid, m.ReadinessVerdict.computed_at >= lo, m.ReadinessVerdict.computed_at < hi)
    )
    verdict_total = await _count(s, verdicts)
    verdict_rows = (await s.execute(verdicts.order_by(m.ReadinessVerdict.computed_at.desc(), m.ReadinessVerdict.id).limit(MAX_LISTED))).all()

    content_versions = await _count(s, select(m.CampaignVersion.id).where(
        m.CampaignVersion.campaign_id == cid, m.CampaignVersion.created_at >= lo, m.CampaignVersion.created_at < hi))
    approvals = await _count(s, select(m.Approval.id).where(
        m.Approval.campaign_id == cid, m.Approval.decided_at >= lo, m.Approval.decided_at < hi))
    agent_runs = (await s.execute(
        select(m.AgentRun.run_type, m.AgentRun.status, func.count()).where(
            m.AgentRun.campaign_id == cid, m.AgentRun.created_at >= lo, m.AgentRun.created_at < hi)
        .group_by(m.AgentRun.run_type, m.AgentRun.status))).all()
    audience_runs = (await s.execute(
        select(m.AudienceRun.kind, m.AudienceRun.status, func.count()).where(
            m.AudienceRun.campaign_id == cid, m.AudienceRun.created_at >= lo, m.AudienceRun.created_at < hi)
        .group_by(m.AudienceRun.kind, m.AudienceRun.status))).all()
    findings = await _count(s, select(m.RiskFindingRow.id).join(m.AudienceRun, m.AudienceRun.id == m.RiskFindingRow.run_id).where(
        m.AudienceRun.campaign_id == cid, m.RiskFindingRow.created_at >= lo, m.RiskFindingRow.created_at < hi))
    opened = resolved = 0
    if sub.project.workspace_id is not None and region_ids:
        mine = (m.Conflict.workspace_id == sub.project.workspace_id, m.Conflict.region_id.in_(region_ids))
        opened = await _count(s, select(m.Conflict.id).where(*mine, m.Conflict.created_at >= lo, m.Conflict.created_at < hi))
        resolved = await _count(s, select(m.ConflictResolution.id).join(m.Conflict, m.Conflict.id == m.ConflictResolution.conflict_id).where(
            *mine, m.ConflictResolution.decided_at >= lo, m.ConflictResolution.decided_at < hi))

    runs = [d.DigestRunLine(kind=k, status=st, count=n) for k, st, n in sorted(
        [*((str(a), str(b), int(n)) for a, b, n in agent_runs), *((f"audience:{a}", str(b), int(n)) for a, b, n in audience_runs)])]
    return d.DigestWhatChanged(
        counts=d.DigestChangeCounts(
            creative_versions=node_total, content_versions=content_versions, verdicts=verdict_total, approvals=approvals,
            agent_runs=sum(int(n) for *_, n in agent_runs), audience_runs=sum(int(n) for *_, n in audience_runs),
            conflicts_opened=opened, conflicts_resolved=resolved, risk_findings=findings),
        versions=[d.DigestVersionChange(
            id=n.id, label=n.label, region_code=n.region_code, actor=n.actor, created_at=n.created_at,  # type: ignore[arg-type]
            source=d.DigestSource(workspace="studio", view=None, ref=str(n.id))) for n in node_rows],
        verdicts=[d.DigestVerdictChange(
            region_code=code, region_name=name, version_label=label, verdict=v.verdict,  # type: ignore[arg-type]
            main_reason=v.main_reason, computed_at=v.computed_at,
            source=d.DigestSource(workspace="launch", view=None, ref=str(v.version_id))) for v, code, name, label in verdict_rows],
        runs=runs, truncated=node_total > len(node_rows) or verdict_total > len(verdict_rows))


# --- pulse movement and alerts ---------------------------------------------------------------------------------


async def pulse_rows(s: AsyncSession, campaign_id: UUID) -> list[SeriesRow]:
    cols = (m.MetricSeries.day, m.MetricSeries.platform, m.MetricSeries.channel, m.MetricSeries.version_label,
            m.MetricSeries.region_code, m.MetricSeries.metric, m.MetricSeries.value, m.MetricSeries.provisional)
    found = (await s.execute(select(*cols).where(m.MetricSeries.campaign_id == campaign_id, m.MetricSeries.source_kind == "sample"))).all()
    return [SeriesRow(*r) for r in found]


def _no_pulse(reason: str) -> d.DigestPulse:
    return d.DigestPulse(
        available=False, reason=reason, source=PULSE_SOURCE, window_from=None, window_to=None, previous_from=None,
        previous_to=None, settled_through=None, provisional_days_excluded=0, slices=[], alerts=[], alerts_evaluated=0, alerts_skipped=0)


def _headline(a) -> str:  # noqa: ANN001
    if a.alert_type == "ctr_drop":
        return f"CTR fell {abs(a.observed_value) * 100:.1f}% against the version's first week"
    if a.alert_type == "frequency_fatigue":
        return f"Frequency reached {a.observed_value:.1f} while CTR is down {abs(a.comparison_value) * 100:.1f}% against the first week"
    return f"{a.metric.upper()} is {a.observed_value * 100:.1f}% above the region's average"


def build_pulse(rows: list[SeriesRow], sub: Subject, week: d.DigestWeek) -> d.DigestPulse:
    if not rows:
        return _no_pulse("No Live Pulse data is loaded for this campaign.")
    upto = [r for r in rows if r.day <= week.end]
    settled_days = sorted({r.day for r in upto if not r.provisional})
    if not settled_days:
        return _no_pulse("No settled Live Pulse data exists on or before the end of this week.")
    through = settled_days[-1]
    first = min(r.day for r in rows)
    cur_to = through
    cur_from = max(first, cur_to - timedelta(days=WINDOW_DAYS - 1))
    prev_to = cur_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=WINDOW_DAYS - 1)
    has_previous = (cur_to - cur_from).days == WINDOW_DAYS - 1 and prev_from >= first
    settled = [r for r in upto if not r.provisional]
    by_slice: dict[tuple[str, str], list[SeriesRow]] = defaultdict(list)
    for r in settled:
        by_slice[(r.region_code, r.version_label)].append(r)
    slices = []
    for (region, version), items in sorted(by_slice.items()):
        now = values_of(HEADLINE, items, cur_from, cur_to)
        if not now["impressions"][0]:
            continue
        before = values_of(HEADLINE, items, prev_from, prev_to) if has_previous else {}
        moves = []
        for name in HEADLINE:
            cur, prev = now[name][0], before.get(name, (None, False))[0]
            delta = None if cur is None or prev is None else cur - prev
            moves.append(d.DigestMetricMove(
                metric=name, label=BY_NAME[name].label, unit=BY_NAME[name].unit, current=cur, previous=prev, delta=delta,
                delta_pct=None if delta is None or not prev else delta / prev))
        slices.append(d.DigestSliceMove(region_code=region, region_name=sub.name(region) or region, version_label=version, metrics=moves))
    result = evaluate(upto, AlertConfig())
    first_day = first.isoformat()

    def path(metric: str, region: str, version: str) -> str:
        query = urlencode({"metric": metric, "region": region, "version": version, "date_from": first_day, "date_to": through.isoformat()})
        return f"/api/v1/campaigns/{sub.campaign.id}/pulse/timeseries?{query}"

    return d.DigestPulse(
        available=True, reason=None, source=PULSE_SOURCE, window_from=cur_from, window_to=cur_to,
        previous_from=prev_from if has_previous else None, previous_to=prev_to if has_previous else None,
        settled_through=through, provisional_days_excluded=len({r.day for r in upto if r.provisional}), slices=slices,
        alerts=[d.DigestAlertLine(
            alert_type=a.alert_type, region_code=a.region_code, region_name=sub.name(a.region_code) or a.region_code,
            version_label=a.version_label, headline=_headline(a), suggested_action=a.suggested_action.strip(),
            source_path=path(a.metric, a.region_code, a.version_label)) for a in result.alerts],
        alerts_evaluated=result.evaluated, alerts_skipped=len(result.skipped))


# --- comments --------------------------------------------------------------------------------------------------


def build_comments(
    data: comments_service.Dataset, titles: list[str], week: d.DigestWeek, pulse: d.DigestPulse,
) -> tuple[d.DigestComments, Counter]:
    """The comments section, and the count of mentions by (watch id, label, region) for the action rules. `data` is the
    source Comment Pulse selected. Counts, sentiment and themes come from its stored reading; nothing is read here."""
    rows, analysis = data.rows, data.analysis
    if not rows:
        reason = "No comments are loaded for this campaign."
        return d.DigestComments(
            available=False, reason=reason, source=COMMENT_SOURCE, source_kind="sample", video_titles=[], window_from=None,
            window_to=None, comments_total=0, comments_in_window=0, claim_mentions_in_window=0, cultural_mentions_in_window=0,
            sentiment=None, themes=[], flagged=[]), Counter()
    labels = dict(analysis.labels) if analysis is not None else {}
    live = data.source == comments_service.YOUTUBE
    if live:  # real comments: the ISO week of their published time (India Standard Time), not the Pulse data window
        start, end = week.start, week.end
        lo, hi = week_bounds(week)
        f = comments_service.Filters()
        view = [r for r in rows if lo <= (r.published_at or datetime.combine(r.day, time.min, tzinfo=UTC)) < hi]
    else:
        start, end = (pulse.window_from, pulse.window_to) if pulse.available else (week.start, week.end)
        f = comments_service.Filters(date_from=start, date_to=end)
        view = comments_service._in_view(rows, f, labels)  # noqa: SLF001  (the same filter the Comment Pulse views use)
    flags = {r.ref: comments_service.flags_of(r.text, generic=live) for r in view}
    mentions: Counter = Counter()
    for r in view:
        for x in flags[r.ref]:
            mentions[(x.watch_id, x.label, x.kind, r.region_code)] += 1
    flagged = sorted((r for r in view if flags[r.ref]), key=lambda r: (-r.likes, r.ref))[:MAX_FLAGGED]
    themes, _ = comments_service.theme_views(view, analysis, f)
    return d.DigestComments(
        available=True, reason=None, source=data.line if live else COMMENT_SOURCE, source_kind="youtube" if live else "sample",
        video_titles=titles, window_from=start, window_to=end, comments_total=len(rows), comments_in_window=len(view),
        claim_mentions_in_window=sum(n for (_, _, kind, _), n in mentions.items() if kind == "planted_claim"),
        cultural_mentions_in_window=sum(n for (_, _, kind, _), n in mentions.items() if kind == "cultural_misstep"),
        sentiment=comments_service.counts_of(view, labels) if analysis is not None else None,
        themes=[d.DigestThemeLine(id=t.id, label=t.label, summary=t.summary, comments=t.comments, quote=t.quotes[0] if t.quotes else None)
                for t in themes[:MAX_THEMES]],
        flagged=[d.DigestFlagged(
            id=r.id, ref=r.ref, text=r.text, region_code=r.region_code, version_label=r.version_label, language=r.language,
            kind=flags[r.ref][0].kind,
            label=flags[r.ref][0].label, likes=r.likes, source=d.DigestSource(workspace="pulse", view="comments", ref=r.ref)) for r in flagged],
    ), mentions


# --- open items ----------------------------------------------------------------------------------------------


async def open_items(s: AsyncSession, sub: Subject, now: datetime) -> d.DigestOpenItems:
    cid = sub.campaign.id
    newest: dict[UUID, tuple] = {}
    rows = (await s.execute(
        select(m.ReadinessVerdict, m.Region.code, m.Region.name, m.VersionNode.label)
        .join(m.Region, m.Region.id == m.ReadinessVerdict.region_id)
        .join(m.VersionNode, m.VersionNode.id == m.ReadinessVerdict.version_id)
        .where(m.ReadinessVerdict.campaign_id == cid)
        .order_by(m.ReadinessVerdict.computed_at.desc(), m.ReadinessVerdict.id).limit(500))).all()
    for row in rows:
        newest.setdefault(row[0].region_id, row)
    not_ready = [
        d.DigestNotReady(
            region_code=code, region_name=name, version_label=label, verdict=v.verdict,  # type: ignore[arg-type]
            main_reason=v.main_reason, computed_at=v.computed_at, source=d.DigestSource(workspace="launch", view=None, ref=str(v.version_id)))
        for v, code, name, label in newest.values() if v.verdict != "go"
    ]
    not_ready.sort(key=lambda n: (n.verdict != "rethink", n.region_code))

    conflicts: list[d.DigestConflictItem] = []
    conflict_total = 0
    region_ids = {rid: code for code, (rid, _) in sub.regions.items()}
    if sub.project.workspace_id is not None and region_ids:
        stmt = select(m.Conflict).where(
            m.Conflict.workspace_id == sub.project.workspace_id, m.Conflict.region_id.in_(list(region_ids)), m.Conflict.status != "resolved")
        conflict_total = await _count(s, stmt)
        for c in (await s.execute(stmt.order_by(m.Conflict.created_at, m.Conflict.id).limit(MAX_LISTED))).scalars():
            code = region_ids.get(c.region_id)
            conflicts.append(d.DigestConflictItem(
                id=c.id, region_code=code, region_name=sub.name(code), reason=c.reason, status=c.status, created_at=c.created_at,
                source=d.DigestSource(workspace="lens", view=None, ref=str(c.id))))

    runs = (await s.execute(
        select(m.AudienceRun.id, m.AudienceRun.version_ref).where(
            m.AudienceRun.campaign_id == cid, m.AudienceRun.kind == "risk_check", m.AudienceRun.status.in_(USABLE_RUNS))
        .order_by(m.AudienceRun.created_at.desc(), m.AudienceRun.id))).all()
    latest_run_ids = list({ref: rid for rid, ref in reversed(runs)}.values())  # the newest run of each version
    findings: list[m.RiskFindingRow] = []
    if latest_run_ids:
        findings = list((await s.execute(select(m.RiskFindingRow).where(
            m.RiskFindingRow.run_id.in_(latest_run_ids), m.RiskFindingRow.status == "open"))).scalars())
    findings.sort(key=lambda f: (not f.blocks_go, SEVERITY_RANK.get(f.severity, 3), f.run_id.hex, f.ordinal))
    return d.DigestOpenItems(
        as_of=now, conflicts=conflicts, conflicts_total=conflict_total,
        risk_findings=[d.DigestRiskItem(
            id=f.id, severity=f.severity, category=f.category, element_id=f.element_id,  # type: ignore[arg-type]
            observation=f.observation, blocks_go=f.blocks_go, source=d.DigestSource(workspace="lab", view="risk", ref=str(f.run_id)))
            for f in findings[:MAX_LISTED]],
        risk_findings_total=len(findings), not_ready=not_ready)


# --- next actions --------------------------------------------------------------------------------------------


def build_actions(items: d.DigestOpenItems, pulse: d.DigestPulse, comments: d.DigestComments, mentions: Counter,
                  region_name: Callable[[str | None], str | None]) -> list[d.DigestAction]:
    """A short list from fixed rules, most urgent first. Every action says which rule produced it and what it rests on."""
    out: list[d.DigestAction] = []
    for n in items.not_ready:
        out.append(d.DigestAction(
            priority=1 if n.verdict == "rethink" else 2, rule="readiness_not_go", source=n.source, why=n.main_reason,
            text=f"{'Rethink' if n.verdict == 'rethink' else 'Fix'} the {n.region_name} version before launch."))
    for f in items.risk_findings:
        if f.blocks_go:
            out.append(d.DigestAction(
                priority=1, rule="risk_blocks_go", source=f.source, why=f.observation,
                text=f"Resolve the blocking {f.severity}-severity {f.category.replace('_', ' ')} finding on {f.element_id}."))
    for a in pulse.alerts:
        out.append(d.DigestAction(
            priority=2, rule="pulse_alert", source=d.DigestSource(workspace="pulse", view=None, ref=None), why=a.headline,
            text=f"{a.region_name}, {a.version_label}: {a.suggested_action}"))
    by_claim: Counter = Counter()
    by_festival: dict[tuple[str, str], int] = {}
    for (watch_id, label, kind, region), n in mentions.items():
        if kind == "planted_claim":
            by_claim[label] += n
        else:
            by_festival[(label, region)] = n
    for label, n in sorted(by_claim.items()):
        out.append(d.DigestAction(
            priority=2, rule="comment_claim_mentions", source=d.DigestSource(workspace="pulse", view="comments", ref=None),
            why=f"{_plural(n, 'comment')} in the data window match it.",
            text=f"Review the unsourced claim viewers question in the comments, {label.partition(': ')[2] or label}."))
    for (label, region), n in sorted(by_festival.items()):
        place = region_name(region) or region
        out.append(d.DigestAction(
            priority=2, rule="comment_festival_mentions", source=d.DigestSource(workspace="pulse", view="comments", ref=None),
            why=f"{_plural(n, 'comment')} in the data window name it.",
            text=f"Check the festival reference in {place}: viewers name {label.partition(': ')[2] or label}."))
    for c in items.conflicts:
        out.append(d.DigestAction(
            priority=3, rule="conflict_open", source=c.source, why=c.reason,
            text=f"Decide the evidence conflict{' in ' + c.region_name if c.region_name else ''}."))
    if not pulse.available:
        out.append(d.DigestAction(
            priority=3, rule="no_pulse_data", source=d.DigestSource(workspace="pulse", view=None, ref=None),
            why=pulse.reason or "", text="Load Live Pulse data so the digest can show movement."))
    ranked = sorted(enumerate(out), key=lambda t: (t[1].priority, t[0]))
    return [a for _, a in ranked][:MAX_ACTIONS]


# --- the whole digest ------------------------------------------------------------------------------------------


async def build_content(s: AsyncSession, sub: Subject, week: d.DigestWeek, now: datetime) -> d.DigestContent:
    changed = await what_changed(s, sub, week)
    pulse = build_pulse(await pulse_rows(s, sub.campaign.id), sub, week)
    data = await comments_service.read_dataset(s, sub.project, sub.campaign.id)  # the same selection Comment Pulse makes
    titles = [x.video_title or x.video_id for x in await youtube.sources_of(s, sub.campaign.id)] if data.source == comments_service.YOUTUBE else []
    comments, mentions = build_comments(data, titles, week, pulse)
    items = await open_items(s, sub, now)
    return d.DigestContent(
        campaign_name=sub.campaign.name, mode=sub.project.mode, as_of=now, week=week,  # type: ignore[arg-type]
        what_changed=changed, pulse=pulse, comments=comments, open_items=items,
        next_actions=build_actions(items, pulse, comments, mentions, sub.name), limitations=list(LIMITATIONS))


# --- facts for the optional model summary ------------------------------------------------------------------------


def facts_of(c: d.DigestContent) -> list[str]:
    """The digest as short factual lines. A model may restate these and nothing else."""
    w, ch = c.week, c.what_changed.counts
    out = [f"Week {w.label}, {w.start.isoformat()} to {w.end.isoformat()}, campaign {c.campaign_name}."]
    out.append(
        f"This week {_plural(ch.creative_versions, 'creative version')}, {_plural(ch.verdicts, 'readiness verdict')}, "
        f"{_plural(ch.approvals, 'approval')} and {_plural(ch.agent_runs + ch.audience_runs, 'run')} were recorded; "
        f"{_plural(ch.conflicts_opened, 'conflict')} opened and {ch.conflicts_resolved} resolved.")
    p = c.pulse
    if p.available:
        out.append(f"Pulse compares {p.window_from} to {p.window_to}" + (f" with {p.previous_from} to {p.previous_to}." if p.previous_from else "."))
        for sl in p.slices:
            m_ = {x.metric: x for x in sl.metrics}
            ctr, cpm = m_["ctr"], m_["cpm"]
            out.append(
                f"{sl.region_name}, {sl.version_label}: CTR {fmt('ratio', ctr.current)} (change {fmt_pct(ctr.delta_pct)}), "
                f"CPM {fmt('inr', cpm.current)} (change {fmt_pct(cpm.delta_pct)}).")
        out += [f"Alert: {a.region_name}, {a.version_label}: {a.headline}." for a in p.alerts]
        if not p.alerts:
            out.append("No Pulse alert fired.")
    else:
        out.append(f"No Pulse movement: {p.reason}")
    cm = c.comments
    if cm.available:
        scope = "YouTube comments posted this week" if cm.source_kind == "youtube" else "Comments in the data window"
        out.append(
            f"{scope}: {cm.comments_in_window}; {cm.claim_mentions_in_window} mention the unsourced claim and "
            f"{cm.cultural_mentions_in_window} name a different festival.")
    oi = c.open_items
    out.append(f"Open items: {oi.conflicts_total} evidence conflicts and {oi.risk_findings_total} open Risk Check findings.")
    out += [f"Not ready: {n.region_name} is {n.verdict}: {n.main_reason}" for n in oi.not_ready]
    out += [f"Next action {i}: {a.text}" for i, a in enumerate(c.next_actions, 1)]
    return out
