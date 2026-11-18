"""Comment Pulse (feature 46): the labelled sample comments of a campaign, counted and trended by code, read by a model.

Access follows the campaign (another workspace's campaign is a 404; loading the sample and reading it need an owner or
editor). Code does every count, share, trend, language tally, watch-term match and quote pick. A model (the gateway in a
live project, labelled fixtures in a demo project) only labels sentiment and groups themes; that reading is stored with the
prompt version and model that made it, and a comment without a label counts as unread. No comment source can be connected
in this build (Connect Accounts is roadmap), so every row has `source_kind = 'sample'` and every response says so.
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import comment_read as agent
from app.core.errors import Conflict, ProviderFailed, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.fixtures import pulse_comments as sample
from app.llm.gateway import LLMError
from app.reference.india import REGIONS
from app.schemas import comment_pulse as v
from app.schemas.common import ErrorDetail
from app.services import studio_context as ctx
from app.services.ai_guard import guarded_ai_call
from app.services.audit import record_audit
from app.services.common import get_owned, require_writable
from app.services.pulse_sample import ADAPTED_A, ADAPTED_B, ORIGINAL

REGION_NAMES = {r.code: r.name for r in REGIONS}
STUDIO_KIND = {ORIGINAL: "original", ADAPTED_A: "adapted_a", ADAPTED_B: "adapted_b"}
MIN_READ_FOR_MODERATE = 8
CONFIDENCE_RULE = (
    f"Low with fewer than {MIN_READ_FOR_MODERATE} comments read, or no reading yet; otherwise Moderate. "
    "Sample comments never rate above Moderate."
)
NOT_LOADED = "The sample comments are not loaded for this campaign. Load them first with POST /campaigns/{id}/pulse/comments/sample."
NAMESPACE = UUID("6f0f1a54-2d7b-4a39-9c1e-0b6f7e3d5c11")  # comment ids are uuid5(campaign, ref): stable across reloads
MAX_QUOTES = 3
STORED_NOTE = "Generated, deterministic sample comments. " + sample.SAMPLE_LABEL + "."


# --- access and loading ----------------------------------------------------------------------------------------


async def _project(s: AsyncSession, user_id: UUID, campaign_id: UUID, *, writable: bool = False) -> m.Project:
    _, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
    if writable:
        require_writable(project)
    return project


async def load_rows(s: AsyncSession, campaign_id: UUID) -> list[m.PulseComment]:
    """The campaign's sample comments, oldest first. Empty when none were loaded."""
    stmt = select(m.PulseComment).where(m.PulseComment.campaign_id == campaign_id, m.PulseComment.source_kind == "sample")
    return list((await s.execute(stmt.order_by(m.PulseComment.ref))).scalars())


async def newest_analysis(s: AsyncSession, campaign_id: UUID) -> m.CommentAnalysis | None:
    stmt = select(m.CommentAnalysis).where(m.CommentAnalysis.campaign_id == campaign_id)
    return (await s.execute(stmt.order_by(m.CommentAnalysis.created_at.desc(), m.CommentAnalysis.id).limit(1))).scalar_one_or_none()


def analysis_info(row: m.CommentAnalysis | None) -> v.CommentAnalysisInfo | None:
    if row is None:
        return None
    return v.CommentAnalysisInfo(
        id=row.id, created_at=row.created_at, mode=row.mode, is_fixture=row.provider == "fixture",  # type: ignore[arg-type]
        status=row.status, prompt_version=row.prompt_version, provider=row.provider, model_id=row.model_id,  # type: ignore[arg-type]
        estimated_cost_usd=row.estimated_cost_usd, comment_count=row.comment_count, read_count=row.read_count,
        dropped={k: int(n) for k, n in (row.dropped or {}).items()}, notes=list(row.notes or []),
    )


def _stamp(rows: list[m.PulseComment]) -> dict:
    return {
        "label": sample.SAMPLE_LABEL, "dataset_version": rows[0].dataset_version,
        "last_updated_at": max(r.last_updated_at for r in rows), "limitations": list(sample.SAMPLE_LIMITATIONS),
    }


def _bad(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


async def _need_rows(s: AsyncSession, campaign_id: UUID) -> list[m.PulseComment]:
    rows = await load_rows(s, campaign_id)
    if not rows:
        raise Conflict(NOT_LOADED)
    return rows


# --- code-side reading of a comment: watch terms, version anchors, labels ------------------------------------------


def flags_of(text: str) -> list[v.CommentFlag]:
    """Watch-term matches in the comment text. One flag per watch item, naming the first term that matched."""
    haystack = sample.watch_text(text)
    found = []
    for item in sample.WATCH:
        term = next((t for t in item.terms if sample.watch_text(t) in haystack), None)
        if term is not None:
            found.append(v.CommentFlag(
                kind=item.kind, watch_id=item.id, label=item.label, matched_term=term, note=item.note))  # type: ignore[arg-type]
    return found


Resolver = Callable[[str, str], tuple[UUID | None, str | None]]


async def studio_resolver(s: AsyncSession, campaign_id: UUID) -> Resolver:
    """(pulse version label, region) -> the closest Creative Studio version. The original is the version tree's root; an
    adapted version is the region's first node (the transcreation) or its newest (after Tweak Chips and edits)."""
    nodes = list((await s.execute(
        select(m.VersionNode).where(m.VersionNode.campaign_id == campaign_id).order_by(m.VersionNode.created_at, m.VersionNode.id)
    )).scalars())
    root = next((n for n in nodes if n.parent_id is None), None)
    by_region: dict[str, list[m.VersionNode]] = defaultdict(list)
    for n in nodes:
        if n.region_code:
            by_region[n.region_code].append(n)

    def resolve(version_label: str, region: str) -> tuple[UUID | None, str | None]:
        kind = STUDIO_KIND.get(version_label)
        own = by_region.get(region, [])
        node = root if kind == "original" else (own[0] if kind == "adapted_a" and own else own[-1] if kind == "adapted_b" and own else None)
        return (node.id, node.label) if node is not None else (None, None)

    return resolve


def confidence(read: int) -> tuple[v.CommentConfidence, str]:
    return ("moderate" if read >= MIN_READ_FOR_MODERATE else "low"), CONFIDENCE_RULE


def counts_of(rows: Iterable[m.PulseComment], labels: dict[str, dict]) -> v.SentimentCounts:
    tally = Counter(labels[r.ref]["sentiment"] if r.ref in labels else "unread" for r in rows)
    return v.SentimentCounts(
        positive=tally["positive"], neutral=tally["neutral"], negative=tally["negative"], mixed=tally["mixed"], unread=tally["unread"])


def share(count: int, counts: v.SentimentCounts) -> float | None:
    read = counts.positive + counts.neutral + counts.negative + counts.mixed
    return round(count / read, 3) if read else None


# --- filters ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Filters:
    region: str | None = None
    version: str | None = None
    language: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    sentiment: str | None = None
    theme: str | None = None
    flag: str | None = None


def _validate(rows: list[m.PulseComment], f: Filters) -> None:
    for field, value, present in (
        ("region", f.region, {r.region_code for r in rows}), ("version", f.version, {r.version_label for r in rows}),
        ("language", f.language, {r.language for r in rows}),
    ):
        if value is not None and value not in present:
            raise _bad(field, f"Not in the sample comments. Available: {', '.join(sorted(present))}.")
    if f.date_from and f.date_to and f.date_from > f.date_to:
        raise _bad("date_from", "date_from must not be after date_to.")


def _in_view(rows: list[m.PulseComment], f: Filters, labels: dict[str, dict]) -> list[m.PulseComment]:
    out = []
    for r in rows:
        if (f.region and r.region_code != f.region) or (f.version and r.version_label != f.version) or (f.language and r.language != f.language):
            continue
        if (f.date_from and r.day < f.date_from) or (f.date_to and r.day > f.date_to):
            continue
        label = labels.get(r.ref)
        if f.sentiment and (label is None or label["sentiment"] != f.sentiment):
            continue
        if f.theme and (label is None or f.theme not in label["themes"]):
            continue
        if f.flag:
            kinds = {x.kind for x in flags_of(r.text)}
            if not (kinds if f.flag == "any" else {f.flag} & kinds):
                continue
        out.append(r)
    return out


def _filters_out(f: Filters) -> v.CommentFilters:
    return v.CommentFilters(region=f.region, version=f.version, language=f.language, date_from=f.date_from, date_to=f.date_to)


# --- status, sample load -----------------------------------------------------------------------------------------


def _status(rows: list[m.PulseComment], analysis: m.CommentAnalysis | None) -> v.CommentDatasetStatus:
    return v.CommentDatasetStatus(
        loaded=bool(rows), label=sample.SAMPLE_LABEL, dataset_version=rows[0].dataset_version if rows else sample.DATASET_VERSION,
        last_updated_at=max((r.last_updated_at for r in rows), default=None), comment_count=len(rows),
        date_from=min((r.day for r in rows), default=None), date_to=max((r.day for r in rows), default=None),
        regions=sorted({r.region_code for r in rows}), versions=sorted({r.version_label for r in rows}),
        languages=sorted({r.language for r in rows}), analysis=analysis_info(analysis),
        note=(STORED_NOTE if rows else "Not loaded. " + sample.SAMPLE_LABEL + "."),
    )


async def dataset_status(user_id: UUID, campaign_id: UUID) -> v.CommentDatasetStatus:
    async with read_session() as s:
        await _project(s, user_id, campaign_id)
        rows = await load_rows(s, campaign_id)
        analysis = await newest_analysis(s, campaign_id) if rows else None
    return _status(rows, analysis)


async def store_sample(s: AsyncSession, project: m.Project, campaign_id: UUID, user_id: UUID | None) -> int:
    """Replace the campaign's sample comments with the generated set (identical rows, identical refs and ids)."""
    comments = sample.generate_comments()
    await s.execute(m.PulseComment.__table__.delete().where(
        m.PulseComment.campaign_id == campaign_id, m.PulseComment.source_kind == "sample"))
    await s.execute(insert(m.PulseComment), [
        {
            "id": uuid5(NAMESPACE, f"{campaign_id}|{c.ref}"), "workspace_id": project.workspace_id, "project_id": project.id,
            "campaign_id": campaign_id, "ref": c.ref, "day": c.day, "platform": c.platform, "region_code": c.region_code,
            "version_label": c.version_label, "language": c.language, "script": c.script, "code_mixed": c.code_mixed,
            "text": c.text, "likes": c.likes, "source_kind": "sample", "dataset_version": sample.DATASET_VERSION,
            "last_updated_at": sample.LAST_UPDATED_AT,
        }
        for c in comments
    ])
    await record_audit(
        s, action="pulse.comments.sample.load", target_type="campaign", target_id=str(campaign_id),
        workspace_id=project.workspace_id, actor_user_id=user_id,
        detail={"dataset_version": sample.DATASET_VERSION, "comments": len(comments)},
    )
    return len(comments)


async def load_sample(user_id: UUID, campaign_id: UUID) -> v.CommentDatasetStatus:
    async with session() as s, s.begin():
        project = await _project(s, user_id, campaign_id, writable=True)
        await store_sample(s, project, campaign_id, user_id)
    return await dataset_status(user_id, campaign_id)


# --- summary: counts and trends by code ---------------------------------------------------------------------------


def _labels_of(analysis: m.CommentAnalysis | None) -> dict[str, dict]:
    return dict(analysis.labels) if analysis is not None else {}


def summarise(rows: list[m.PulseComment], analysis: m.CommentAnalysis | None, f: Filters) -> v.CommentSummary:
    """Pure: every number in the summary is computed here from the stored rows and labels."""
    labels = _labels_of(analysis)
    view = _in_view(rows, f, labels)
    origin = min(r.day for r in rows)
    flags = {r.ref: flags_of(r.text) for r in view}

    def claim(r: m.PulseComment) -> int:
        return sum(1 for x in flags[r.ref] if x.kind == "planted_claim")

    def cultural(r: m.PulseComment) -> int:
        return sum(1 for x in flags[r.ref] if x.kind == "cultural_misstep")

    slices = []
    by_slice: dict[tuple[str, str], list[m.PulseComment]] = defaultdict(list)
    for r in view:
        by_slice[(r.region_code, r.version_label)].append(r)
    for (region, version), items in sorted(by_slice.items()):
        counts = counts_of(items, labels) if analysis is not None else None
        read = 0 if counts is None else counts.positive + counts.neutral + counts.negative + counts.mixed
        level, rule = confidence(read)
        slices.append(v.CommentSlice(
            region_code=region, region_name=REGION_NAMES.get(region, region), version_label=version, comments=len(items),
            likes=sum(r.likes for r in items), claim_mentions=sum(claim(r) for r in items),
            cultural_mentions=sum(cultural(r) for r in items), sentiment=counts,
            positive_share=None if counts is None else share(counts.positive, counts),
            negative_share=None if counts is None else share(counts.negative, counts), confidence=level, confidence_rule=rule))

    languages = []
    for lang in sorted({r.language for r in view}):
        items = [r for r in view if r.language == lang]
        languages.append(v.LanguageCount(
            language=lang, language_name=sample.LANGUAGE_NAMES.get(lang, lang), script=Counter(r.script for r in items).most_common(1)[0][0],
            comments=len(items), code_mixed_comments=sum(1 for r in items if r.code_mixed)))
    languages.sort(key=lambda x: (-x.comments, x.language))

    per_day = Counter(r.day for r in view)
    last = max(r.day for r in rows)
    days = [origin + timedelta(days=i) for i in range((last - origin).days + 1)]
    daily = [v.DayCount(date=d, comments=per_day.get(d, 0)) for d in days if (not f.date_from or d >= f.date_from) and (not f.date_to or d <= f.date_to)]

    weekly = []
    for i in range(((last - origin).days // 7) + 1):
        start = origin + timedelta(days=7 * i)
        items = [r for r in view if start <= r.day <= start + timedelta(days=6)]
        counts = counts_of(items, labels)
        weekly.append(v.WeekTrend(
            week_start=start, week_end=start + timedelta(days=6), comments=len(items),
            claim_mentions=sum(claim(r) for r in items), cultural_mentions=sum(cultural(r) for r in items),
            read=len(items) - counts.unread, negative_share=share(counts.negative, counts) if analysis is not None else None))

    counts_all = counts_of(view, labels) if analysis is not None else None
    read_in_view = 0 if counts_all is None else len(view) - counts_all.unread
    return v.CommentSummary(
        **_stamp(rows), filters=_filters_out(f),
        coverage=v.CommentCoverage(
            comments_in_dataset=len(rows), comments_in_view=len(view), read_in_view=read_in_view,
            read_share=None if analysis is None or not view else round(read_in_view / len(view), 3),
            languages_in_view=len(languages)),
        totals=v.CommentTotals(
            comments=len(view), likes=sum(r.likes for r in view), claim_mentions=sum(claim(r) for r in view),
            cultural_mentions=sum(cultural(r) for r in view), flagged_comments=sum(1 for r in view if flags[r.ref])),
        sentiment=counts_all, analysis=analysis_info(analysis), slices=slices, languages=languages, daily=daily, weekly=weekly)


async def summary(user_id: UUID, campaign_id: UUID, f: Filters) -> v.CommentSummary:
    async with read_session() as s:
        await _project(s, user_id, campaign_id)
        rows = await _need_rows(s, campaign_id)
        analysis = await newest_analysis(s, campaign_id)
    _validate(rows, f)
    return summarise(rows, analysis, f)


# --- themes: the model's grouping, counted and quoted by code -------------------------------------------------------


def quote_of(r: m.PulseComment, labels: dict[str, dict]) -> v.CommentQuote:
    label = labels.get(r.ref)
    return v.CommentQuote(
        id=r.id, ref=r.ref, text=r.text, language=r.language, region_code=r.region_code, version_label=r.version_label,
        likes=r.likes, sentiment=label["sentiment"] if label else None)


def theme_views(rows: list[m.PulseComment], analysis: m.CommentAnalysis | None, f: Filters) -> tuple[list[v.CommentTheme], int]:
    if analysis is None:
        return [], 0
    labels = _labels_of(analysis)
    view = [r for r in _in_view(rows, f, labels) if r.ref in labels]
    read = len(view)
    out = []
    for theme in analysis.themes:
        items = [r for r in view if theme["id"] in labels[r.ref]["themes"]]
        if not items:
            continue
        ranked = sorted(items, key=lambda r: (-r.likes, r.ref))
        out.append(v.CommentTheme(
            id=theme["id"], label=theme["label"], summary=theme["summary"], comments=len(items),
            share_of_read=round(len(items) / read, 3), sentiment=counts_of(items, labels),
            regions=[v.ThemeBreakdown(key=k, comments=n) for k, n in sorted(Counter(r.region_code for r in items).items(), key=lambda kv: (-kv[1], kv[0]))],
            versions=[v.ThemeBreakdown(key=k, comments=n) for k, n in sorted(Counter(r.version_label for r in items).items(), key=lambda kv: (-kv[1], kv[0]))],
            quotes=[quote_of(r, labels) for r in ranked[:MAX_QUOTES]]))
    out.sort(key=lambda t: (-t.comments, t.id))
    unthemed = sum(1 for r in view if not labels[r.ref]["themes"])
    return out, unthemed


async def themes(user_id: UUID, campaign_id: UUID, f: Filters) -> v.CommentThemes:
    async with read_session() as s:
        await _project(s, user_id, campaign_id)
        rows = await _need_rows(s, campaign_id)
        analysis = await newest_analysis(s, campaign_id)
    _validate(rows, f)
    views, unthemed = theme_views(rows, analysis, f)
    return v.CommentThemes(**_stamp(rows), filters=_filters_out(f), analysis=analysis_info(analysis), themes=views, unthemed=unthemed)


# --- the comments themselves ------------------------------------------------------------------------------------


async def list_comments(user_id: UUID, campaign_id: UUID, f: Filters, *, sort: str, limit: int, offset: int) -> v.CommentPage:
    async with read_session() as s:
        await _project(s, user_id, campaign_id)
        rows = await _need_rows(s, campaign_id)
        analysis = await newest_analysis(s, campaign_id)
        resolve = await studio_resolver(s, campaign_id)
    _validate(rows, f)
    labels = _labels_of(analysis)
    names = {t["id"]: t["label"] for t in (analysis.themes if analysis is not None else [])}
    view = _in_view(rows, f, labels)
    if sort == "likes":
        view.sort(key=lambda r: (-r.likes, r.ref))
    else:
        view.sort(key=lambda r: (r.day, r.ref), reverse=True)
    page = view[offset : offset + limit]
    items = []
    for r in page:
        label = labels.get(r.ref)
        studio_id, studio_label = resolve(r.version_label, r.region_code)
        items.append(v.CommentItem(
            id=r.id, ref=r.ref, day=r.day, platform=r.platform, region_code=r.region_code,
            region_name=REGION_NAMES.get(r.region_code, r.region_code), language=r.language,
            language_name=sample.LANGUAGE_NAMES.get(r.language, r.language), script=r.script, code_mixed=r.code_mixed,
            version_label=r.version_label, text=r.text, likes=r.likes,
            anchor=v.VersionAnchor(
                version_label=r.version_label, region_code=r.region_code, region_name=REGION_NAMES.get(r.region_code, r.region_code),
                studio_version_id=studio_id, studio_version_label=studio_label),
            flags=flags_of(r.text),
            interpretation=None if label is None else v.CommentInterpretation(
                sentiment=label["sentiment"], themes=[v.CommentThemeRef(id=t, label=names.get(t, t)) for t in label["themes"]])))
    return v.CommentPage(**_stamp(rows), items=items, total=len(view), limit=limit, offset=offset)


# --- the model reading ------------------------------------------------------------------------------------------


async def read(user_id: UUID, campaign_id: UUID, force: bool) -> v.CommentReadResult:
    """Label sentiment and group themes: labelled fixtures in a demo project, the model gateway in a live one. The newest
    reading is reused unless `force` (a reading is one model call for the whole sample)."""
    async with read_session() as s:
        project = await _project(s, user_id, campaign_id, writable=True)
        rows = await _need_rows(s, campaign_id)
        newest = await newest_analysis(s, campaign_id)
    if (newest is not None and not force and newest.mode == project.mode and newest.prompt_version == agent.PROMPT_VERSION
            and newest.dataset_version == rows[0].dataset_version and newest.comment_count == len(rows)):
        return v.CommentReadResult(reused=True, analysis=analysis_info(newest))  # type: ignore[arg-type]
    sent = [
        {"ref": r.ref, "region": REGION_NAMES.get(r.region_code, r.region_code),
         "language": sample.LANGUAGE_NAMES.get(r.language, r.language), "text": r.text}
        for r in rows
    ]
    gateway = ctx.gateway_for(project.mode)
    try:
        async with guarded_ai_call(user_id, project, campaign_id):  # 429 over the per-user or per-workspace limit
            result = await agent.read_comments(gateway, stage="reading_comments", comments=sent)
    except LLMError as exc:
        raise ctx.llm_failure(exc) from exc
    checked = agent.validate_read(result.value, [r.ref for r in rows])
    if not checked.labels:
        raise ProviderFailed("The model returned no usable labels for these comments. Nothing was stored; try again.")
    trace = result.trace
    row = m.CommentAnalysis(
        id=uuid4(), workspace_id=project.workspace_id, project_id=project.id, campaign_id=campaign_id,
        dataset_version=rows[0].dataset_version, mode=project.mode, prompt_version=trace.prompt_version or agent.PROMPT_VERSION,
        provider=trace.provider or "unknown", model_id=trace.model_id,
        estimated_cost_usd=trace.usage.estimated_cost_usd if trace.usage else None,
        status="completed" if len(checked.labels) == len(rows) else "partial", comment_count=len(rows),
        read_count=len(checked.labels), dropped=checked.dropped, labels=checked.labels, themes=checked.themes,
        notes=checked.notes, created_by=user_id, created_at=utcnow())
    async with session() as s, s.begin():
        await _project(s, user_id, campaign_id, writable=True)  # access is checked again where the row is written
        s.add(row)
        await record_audit(
            s, action="pulse.comments.read", target_type="campaign", target_id=str(campaign_id),
            workspace_id=project.workspace_id, actor_user_id=user_id,
            detail={"analysis_id": str(row.id), "provider": row.provider, "comments": row.comment_count, "read": row.read_count})
    return v.CommentReadResult(reused=False, analysis=analysis_info(row))  # type: ignore[arg-type]
