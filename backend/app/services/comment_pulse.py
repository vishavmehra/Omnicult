"""Comment Pulse (feature 46): the comments of a campaign, counted and trended by code, read by a model.

The comments are the labelled sample, or, in a live project that attached a YouTube video (services/comment_youtube.py), the
public comments fetched from it. A demo project always has the sample. A live project shows YouTube comments while it has any
and the sample again once the videos are removed; every response says which, in `source_kind` and `source_line`.

Access follows the campaign (another workspace's campaign is a 404; loading the sample, fetching and reading need an owner or
editor). Code does every count, share, trend, language tally, watch-term match and quote pick. A model (the gateway in a
live project, labelled fixtures in a demo project) only labels sentiment and groups themes; that reading is stored with the
prompt version and model that made it, and a comment without a label counts as unread.
"""

import hashlib
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import comment_read as agent
from app.analytics.comment_lang import LANGUAGE_NAMES
from app.core.errors import Conflict, ProviderFailed, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.fixtures import pulse_comments as sample
from app.llm.gateway import LLMError
from app.reference.india import REGIONS
from app.schemas import comment_pulse as v
from app.schemas.common import ErrorDetail
from app.services import comment_youtube as yt
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
YOUTUBE_CONFIDENCE_RULE = (
    f"Low with fewer than {MIN_READ_FOR_MODERATE} comments read, or no reading yet; otherwise Moderate. "
    "Public comments come from people who chose to write one, so they never rate above Moderate."
)
SAMPLE, YOUTUBE = "sample", yt.SOURCE
SAMPLE_LINE = "Source: sample comments, written for the demo, not from a connected channel"
TREND_DAYS, TREND_WEEKS = 60, 26  # a long-running video would otherwise return years of daily points
MODEL_TEXT_CHARS = 600  # one comment is cut to this in the model prompt; the stored text is whole
NOT_LOADED = "The sample comments are not loaded for this campaign. Load them first with POST /campaigns/{id}/pulse/comments/sample."
NAMESPACE = UUID("6f0f1a54-2d7b-4a39-9c1e-0b6f7e3d5c11")  # comment ids are uuid5(campaign, ref): stable across reloads
MAX_QUOTES = 3
STORED_NOTE = "Generated, deterministic sample comments. " + sample.SAMPLE_LABEL + "."


# --- access and loading ----------------------------------------------------------------------------------------


async def _access(s: AsyncSession, user_id: UUID, campaign_id: UUID, *, writable: bool = False) -> tuple[m.Campaign, m.Project]:
    campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
    if writable:
        require_writable(project)
    return campaign, project


async def _project(s: AsyncSession, user_id: UUID, campaign_id: UUID, *, writable: bool = False) -> m.Project:
    return (await _access(s, user_id, campaign_id, writable=writable))[1]


async def load_rows(s: AsyncSession, campaign_id: UUID, source: str = SAMPLE) -> list[m.PulseComment]:
    """The campaign's comments of one source (the sample by default), by ref. Empty when none were loaded."""
    stmt = select(m.PulseComment).where(m.PulseComment.campaign_id == campaign_id, m.PulseComment.source_kind == source)
    return list((await s.execute(stmt.order_by(m.PulseComment.ref))).scalars())


async def newest_analysis(s: AsyncSession, campaign_id: UUID, source: str = SAMPLE) -> m.CommentAnalysis | None:
    stmt = select(m.CommentAnalysis).where(m.CommentAnalysis.campaign_id == campaign_id, m.CommentAnalysis.source_kind == source)
    return (await s.execute(stmt.order_by(m.CommentAnalysis.created_at.desc(), m.CommentAnalysis.id).limit(1))).scalar_one_or_none()


async def active_source(s: AsyncSession, project: m.Project, campaign_id: UUID) -> str:
    """Which comments the views show: YouTube comments while a live project has any, otherwise the sample. A demo project
    never has YouTube comments, and nothing here asks YouTube for any."""
    if project.mode == "live":
        stmt = select(m.PulseComment.id).where(m.PulseComment.campaign_id == campaign_id, m.PulseComment.source_kind == YOUTUBE).limit(1)
        if (await s.execute(stmt)).first() is not None:
            return YOUTUBE
    return SAMPLE


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def dataset_version(rows: list[m.PulseComment], source: str) -> str:
    """The sample has one fixed version. A YouTube set is as old as its refs: a different set is a different version, so a
    stored reading is only reused for the comments it read."""
    if source == SAMPLE:
        return rows[0].dataset_version
    return "youtube-" + hashlib.sha256(",".join(sorted(r.ref for r in rows)).encode()).hexdigest()[:10]


def read_set(rows: list[m.PulseComment], source: str) -> list[m.PulseComment]:
    """The comments a reading covers: all of the sample; the most liked YouTube comments up to what one model call reads."""
    if source == SAMPLE or len(rows) <= agent.MAX_COMMENTS:
        return rows
    return sorted(sorted(rows, key=lambda r: (-r.likes, r.ref))[: agent.MAX_COMMENTS], key=lambda r: r.ref)


@dataclass(frozen=True)
class Dataset:
    """The comments a view is built from: one source, its source line and its newest reading."""

    source: str
    rows: list[m.PulseComment]
    line: str
    analysis: m.CommentAnalysis | None


async def _dataset(s: AsyncSession, project: m.Project, campaign_id: UUID) -> Dataset:
    source = await active_source(s, project, campaign_id)
    rows = await load_rows(s, campaign_id, source)
    if not rows:
        raise Conflict(NOT_LOADED)
    analysis = await newest_analysis(s, campaign_id, source)
    if source == YOUTUBE and analysis is not None and not set(analysis.labels) & {r.ref for r in rows}:
        analysis = None  # a reading of comments that are no longer stored says nothing about these
    return Dataset(source, rows, await yt.line_for(s, campaign_id) if source == YOUTUBE else SAMPLE_LINE, analysis)


def analysis_info(row: m.CommentAnalysis | None) -> v.CommentAnalysisInfo | None:
    if row is None:
        return None
    return v.CommentAnalysisInfo(
        id=row.id, created_at=row.created_at, mode=row.mode, is_fixture=row.provider == "fixture",  # type: ignore[arg-type]
        status=row.status, prompt_version=row.prompt_version, provider=row.provider, model_id=row.model_id,  # type: ignore[arg-type]
        estimated_cost_usd=row.estimated_cost_usd, comment_count=row.comment_count, read_count=row.read_count,
        dropped={k: int(n) for k, n in (row.dropped or {}).items()}, notes=list(row.notes or []),
    )


def _stamp(d: Dataset) -> dict:
    youtube = d.source == YOUTUBE
    return {
        "is_sample": not youtube, "label": yt.LABEL if youtube else sample.SAMPLE_LABEL, "source_kind": d.source,
        "source_line": d.line, "dataset_version": dataset_version(d.rows, d.source),
        "last_updated_at": max(r.last_updated_at for r in d.rows),
        "limitations": list(yt.LIMITATIONS if youtube else sample.SAMPLE_LIMITATIONS),
    }


def _bad(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


# --- code-side reading of a comment: watch terms, version anchors, labels ------------------------------------------


def flags_of(text: str, *, generic: bool = False) -> list[v.CommentFlag]:
    """Watch-term matches in the comment text. One flag per watch item, naming the first term that matched. `generic` swaps the
    sample's story ("where the ad names Diwali") for a note that claims only what the code did, for comments of a real video."""
    haystack = sample.watch_text(text)
    found = []
    for item in sample.WATCH:
        term = next((t for t in item.terms if sample.watch_text(t) in haystack), None)
        if term is not None:
            found.append(v.CommentFlag(
                kind=item.kind, watch_id=item.id, label=item.label, matched_term=term,  # type: ignore[arg-type]
                note=yt.WATCH_NOTES[item.kind] if generic else item.note))
    return found


Resolver = Callable[[str, str], tuple[UUID | None, str | None]]


async def studio_resolver(s: AsyncSession, campaign_id: UUID) -> Resolver:
    """(pulse version label, region) -> the closest Creative Studio version. The original is the version tree's root; an
    adapted version is the region's first node (the transcreation) or its newest (after Tweak Chips and edits)."""
    nodes = list((await s.execute(
        select(m.VersionNode).where(m.VersionNode.campaign_id == campaign_id).order_by(m.VersionNode.created_at, m.VersionNode.id)
    )).scalars())
    root = next((n for n in nodes if n.parent_id is None), None)
    by_label: dict[str, m.VersionNode] = {}
    for n in nodes:
        by_label.setdefault(n.label, n)  # YouTube comments are attached to a Studio version by its label
    by_region: dict[str, list[m.VersionNode]] = defaultdict(list)
    for n in nodes:
        if n.region_code:
            by_region[n.region_code].append(n)

    def resolve(version_label: str, region: str) -> tuple[UUID | None, str | None]:
        kind = STUDIO_KIND.get(version_label)
        own = by_region.get(region, [])
        node = root if kind == "original" else (own[0] if kind == "adapted_a" and own else own[-1] if kind == "adapted_b" and own else None)
        node = node or (by_label.get(version_label) if kind is None else None)
        return (node.id, node.label) if node is not None else (None, None)

    return resolve


def confidence(read: int, source: str = SAMPLE) -> tuple[v.CommentConfidence, str]:
    return ("moderate" if read >= MIN_READ_FOR_MODERATE else "low"), (YOUTUBE_CONFIDENCE_RULE if source == YOUTUBE else CONFIDENCE_RULE)


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
            raise _bad(field, f"Not in these comments. Available: {', '.join(sorted(present))}.")
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


def _status(
    source: str, rows: list[m.PulseComment], analysis: m.CommentAnalysis | None, line: str, youtube: v.YoutubeStatus | None,
) -> v.CommentDatasetStatus:
    is_youtube = source == YOUTUBE
    return v.CommentDatasetStatus(
        loaded=bool(rows), is_sample=not is_youtube, label=yt.LABEL if is_youtube else sample.SAMPLE_LABEL, source_kind=source,  # type: ignore[arg-type]
        source_line=line, youtube=youtube, dataset_version=dataset_version(rows, source) if rows else sample.DATASET_VERSION,
        last_updated_at=max((r.last_updated_at for r in rows), default=None), comment_count=len(rows),
        date_from=min((r.day for r in rows), default=None), date_to=max((r.day for r in rows), default=None),
        regions=sorted({r.region_code for r in rows}), versions=sorted({r.version_label for r in rows}),
        languages=sorted({r.language for r in rows}), analysis=analysis_info(analysis),
        note=(yt.NOTE if is_youtube else STORED_NOTE) if rows else "Not loaded. " + sample.SAMPLE_LABEL + ".",
    )


async def dataset_status(user_id: UUID, campaign_id: UUID) -> v.CommentDatasetStatus:
    async with read_session() as s:
        campaign, project = await _access(s, user_id, campaign_id)
        source = await active_source(s, project, campaign_id)
        rows = await load_rows(s, campaign_id, source)
        analysis = await newest_analysis(s, campaign_id, source) if rows else None
        line = await yt.line_for(s, campaign_id) if source == YOUTUBE else SAMPLE_LINE
        youtube = await yt.status_block(s, project, campaign)
    return _status(source, rows, analysis, line, youtube)


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


def summarise(d: Dataset, f: Filters) -> v.CommentSummary:
    """Pure: every number in the summary is computed here from the stored rows and labels."""
    rows, analysis = d.rows, d.analysis
    labels = _labels_of(analysis)
    view = _in_view(rows, f, labels)
    origin = min(r.day for r in rows)
    flags = {r.ref: flags_of(r.text, generic=d.source == YOUTUBE) for r in view}

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
        level, rule = confidence(read, d.source)
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
            language=lang, language_name=language_name(lang), script=Counter(r.script for r in items).most_common(1)[0][0],
            comments=len(items), code_mixed_comments=sum(1 for r in items if r.code_mixed)))
    languages.sort(key=lambda x: (-x.comments, x.language))

    per_day = Counter(r.day for r in view)
    last = max(r.day for r in rows)
    days = [origin + timedelta(days=i) for i in range((last - origin).days + 1)]
    daily = [v.DayCount(date=day, comments=per_day.get(day, 0)) for day in days if (not f.date_from or day >= f.date_from) and (not f.date_to or day <= f.date_to)]
    daily = daily[-TREND_DAYS:]

    weekly = []
    for i in range(max(0, (last - origin).days // 7 + 1 - TREND_WEEKS), ((last - origin).days // 7) + 1):
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
        **_stamp(d), filters=_filters_out(f),
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
        project = await _project(s, user_id, campaign_id)
        d = await _dataset(s, project, campaign_id)
    _validate(d.rows, f)
    return summarise(d, f)


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
        project = await _project(s, user_id, campaign_id)
        d = await _dataset(s, project, campaign_id)
    _validate(d.rows, f)
    views, unthemed = theme_views(d.rows, d.analysis, f)
    return v.CommentThemes(**_stamp(d), filters=_filters_out(f), analysis=analysis_info(d.analysis), themes=views, unthemed=unthemed)


# --- the comments themselves ------------------------------------------------------------------------------------


async def list_comments(user_id: UUID, campaign_id: UUID, f: Filters, *, sort: str, limit: int, offset: int) -> v.CommentPage:
    async with read_session() as s:
        project = await _project(s, user_id, campaign_id)
        d = await _dataset(s, project, campaign_id)
        resolve = await studio_resolver(s, campaign_id)
    _validate(d.rows, f)
    labels = _labels_of(d.analysis)
    names = {t["id"]: t["label"] for t in (d.analysis.themes if d.analysis is not None else [])}
    view = _in_view(d.rows, f, labels)
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
            language_name=language_name(r.language), script=r.script, code_mixed=r.code_mixed,
            version_label=r.version_label, text=r.text, likes=r.likes,
            anchor=v.VersionAnchor(
                version_label=r.version_label, region_code=r.region_code, region_name=REGION_NAMES.get(r.region_code, r.region_code),
                studio_version_id=studio_id, studio_version_label=studio_label),
            flags=flags_of(r.text, generic=d.source == YOUTUBE),
            interpretation=None if label is None else v.CommentInterpretation(
                sentiment=label["sentiment"], themes=[v.CommentThemeRef(id=t, label=names.get(t, t)) for t in label["themes"]])))
    return v.CommentPage(**_stamp(d), items=items, total=len(view), limit=limit, offset=offset)


# --- the model reading ------------------------------------------------------------------------------------------


async def read(user_id: UUID, campaign_id: UUID, force: bool) -> v.CommentReadResult:
    """Label sentiment and group themes: labelled fixtures in a demo project, the model gateway in a live one. The newest
    reading is reused unless `force` (a reading is one model call: the whole sample, or the most-liked YouTube comments up to
    what one call reads, the rest staying unread)."""
    async with read_session() as s:
        project = await _project(s, user_id, campaign_id, writable=True)
        d = await _dataset(s, project, campaign_id)
    youtube = d.source == YOUTUBE
    rows = read_set(d.rows, d.source)
    version = dataset_version(rows, d.source)
    prompt = agent.PROMPT_VERSION_YOUTUBE if youtube else agent.PROMPT_VERSION
    newest = d.analysis
    if (newest is not None and not force and newest.mode == project.mode and newest.prompt_version == prompt
            and newest.dataset_version == version and newest.comment_count == len(rows)):
        return v.CommentReadResult(reused=True, analysis=analysis_info(newest))  # type: ignore[arg-type]
    sent = [
        {"ref": r.ref, "region": REGION_NAMES.get(r.region_code, r.region_code), "language": language_name(r.language),
         "text": r.text[:MODEL_TEXT_CHARS] if youtube else r.text}
        for r in rows
    ]
    gateway = ctx.gateway_for(project.mode)
    try:
        async with guarded_ai_call(user_id, project, campaign_id):  # 429 over the per-user or per-workspace limit
            result = await agent.read_comments(gateway, stage="reading_comments", comments=sent, youtube=youtube)
    except LLMError as exc:
        raise ctx.llm_failure(exc) from exc
    checked = agent.validate_read(result.value, [r.ref for r in rows])
    if not checked.labels:
        raise ProviderFailed("The model returned no usable labels for these comments. Nothing was stored; try again.")
    trace = result.trace
    notes = list(checked.notes)
    if len(rows) < len(d.rows):
        notes.append(f"The {len(rows)} most-liked of {len(d.rows)} comments were read; the rest stay unread.")
    row = m.CommentAnalysis(
        id=uuid4(), workspace_id=project.workspace_id, project_id=project.id, campaign_id=campaign_id,
        dataset_version=version, source_kind=d.source, mode=project.mode, prompt_version=trace.prompt_version or prompt,
        provider=trace.provider or "unknown", model_id=trace.model_id,
        estimated_cost_usd=trace.usage.estimated_cost_usd if trace.usage else None,
        status="completed" if len(checked.labels) == len(rows) else "partial", comment_count=len(rows),
        read_count=len(checked.labels), dropped=checked.dropped, labels=checked.labels, themes=checked.themes,
        notes=notes, created_by=user_id, created_at=utcnow())
    async with session() as s, s.begin():
        await _project(s, user_id, campaign_id, writable=True)  # access is checked again where the row is written
        s.add(row)
        await record_audit(
            s, action="pulse.comments.read", target_type="campaign", target_id=str(campaign_id),
            workspace_id=project.workspace_id, actor_user_id=user_id,
            detail={"analysis_id": str(row.id), "provider": row.provider, "comments": row.comment_count, "read": row.read_count,
                    "source": d.source})
    return v.CommentReadResult(reused=False, analysis=analysis_info(row))  # type: ignore[arg-type]
