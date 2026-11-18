"""Comment Pulse source: the public comments of YouTube videos (feature 46).

A live project can attach one public YouTube video to each campaign version and region. The server asks the YouTube Data API
(integrations/youtube.py, API key from settings, never sent to the browser) for that video's top-level comments, at most
`youtube_max_pages` pages of 100, and stores each as a Comment Pulse row with `source_kind = 'youtube'`. Only the comment text,
the time it was published, its like count, its reply count and its YouTube comment id are kept; the request asks Google for no
author field, so a name, channel id or avatar is never received, let alone stored. Fetching again updates the rows that have the
same comment id and adds new ones. Language and script are decided by code (analytics/comment_lang.py).

Quota safety: a fetch costs at most `youtube_max_pages + 1` units of the key's 10,000 a day, and one video is not fetched again
before `youtube_min_fetch_interval_seconds` has passed (counted over every campaign, because the quota is the app's).
Demo projects never reach this module's network code: they keep the labelled sample.
"""

import hashlib
from datetime import datetime, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import comment_lang as lang
from app.core.config import get_settings
from app.core.errors import (
    AppError,
    Conflict,
    NotFound,
    ProviderFailed,
    ProviderNotConfigured,
    ProviderTimeout,
    RateLimited,
    ValidationFailed,
)
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.integrations import youtube as yt
from app.reference.india import REGIONS
from app.schemas import comment_pulse as v
from app.schemas.common import ErrorDetail
from app.services.audit import record_audit
from app.services.campaign_regions import campaign_region_codes
from app.services.common import get_owned, require_writable

SOURCE = "youtube"
DATASET_VERSION = "youtube-comments-1"
LABEL = "YouTube comments"
NOTE = "Public comments fetched from YouTube. Only the text, day, likes and reply count are kept, never who wrote them."
FALLBACK_VERSION = "Campaign video"  # a campaign with no Creative Studio versions yet can still attach a video
NAMESPACE = UUID("3c1d9d52-6b0e-4d52-9f0a-7a5e6a1f4b21")  # comment ids are uuid5(campaign, ref): stable across fetches
TEXT_LIMIT = 2000  # characters kept per comment (YouTube allows 10,000)
LINE_TITLE_CHARS = 80
REGION_NAMES = {r.code: r.name for r in REGIONS}
LIMITATIONS = (
    "These are public comments from people who chose to write one. They are not a sample of everyone who saw the video, "
    "and say nothing about people who did not comment.",
    "Counts describe the comments fetched (the most relevant or the newest, up to the page cap), not every comment on the video.",
    "Language and script are detected by code from the text and can be wrong on short or mixed comments. Latin-script text is "
    "read as English unless it carries Hindi words, so romanised Tamil, Marathi and similar show as English.",
    "Sentiment and themes are a model's interpretation of the comments it read, not a measurement.",
)

WATCH_NOTES = {
    "planted_claim": "The comment repeats a claim on the watch list. The code matched a watch term in the text; it did not check the claim.",
    "cultural_misstep": "The comment names a festival or reference on the watch list. The code matched a watch term in the text; "
    "it did not check whether the campaign names a different one.",
}


# --- small pure helpers -------------------------------------------------------------------------------------------------


def ref_of(video_id: str, comment_id: str) -> str:
    """A short stable ref for the model and the URLs: the same comment always gets the same one."""
    return "yt-" + hashlib.sha256(f"{video_id}|{comment_id}".encode()).hexdigest()[:10]


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _short(title: str) -> str:
    return title if len(title) <= LINE_TITLE_CHARS else title[: LINE_TITLE_CHARS - 1].rstrip() + "…"


def source_line(titles: list[str]) -> str:
    """The one quiet line shown over the comments: which videos they come from."""
    if not titles:
        return "Source: YouTube comments"
    more = len(titles) - 1
    return f"Source: YouTube comments on {_short(titles[0])}" + (f" and {more} more video{'s' if more > 1 else ''}" if more else "")


def app_error(exc: yt.YoutubeError) -> AppError:
    """Each YouTube failure state leaves as its own HTTP status and message (docs: backend/app/integrations/youtube.py)."""
    state = exc.state
    if state == "comments_disabled":
        return Conflict(str(exc))
    if state == "video_not_found":
        return ValidationFailed(str(exc), details=[ErrorDetail(field="video", message="No public video with that id.")])
    if state == "quota_exceeded":
        return RateLimited(str(exc))
    if state == "key_rejected":
        return ProviderNotConfigured(str(exc))
    return ProviderTimeout(str(exc)) if state == "timeout" else ProviderFailed(str(exc))


def make_client() -> yt.YoutubeClient | None:
    """The YouTube client of this server, or None when no API key is configured. Tests replace this."""
    settings = get_settings()
    key = settings.youtube_api_key
    return None if key is None else yt.YoutubeClient(key.get_secret_value(), timeout=settings.culture_http_timeout_seconds)


# --- what a campaign offers and has ---------------------------------------------------------------------------------


async def sources_of(s: AsyncSession, campaign_id: UUID) -> list[m.YoutubeSource]:
    stmt = select(m.YoutubeSource).where(m.YoutubeSource.campaign_id == campaign_id)
    return list((await s.execute(stmt.order_by(m.YoutubeSource.created_at, m.YoutubeSource.id))).scalars())


async def line_for(s: AsyncSession, campaign_id: UUID) -> str:
    return source_line([x.video_title or x.video_id for x in await sources_of(s, campaign_id)])


async def version_options(s: AsyncSession, campaign_id: UUID) -> list[str]:
    """The campaign's Creative Studio version labels (so a comment can be anchored to its version), then a general choice."""
    stmt = select(m.VersionNode.label).where(m.VersionNode.campaign_id == campaign_id).order_by(m.VersionNode.created_at, m.VersionNode.id)
    labels = [x for x in dict.fromkeys((await s.execute(stmt)).scalars()) if 0 < len(x) <= 120]
    return labels if FALLBACK_VERSION in labels else [*labels, FALLBACK_VERSION]


def region_options(campaign: m.Campaign) -> list[v.YoutubeRegionOption]:
    wanted, _ = campaign_region_codes(campaign.target_markets, None)
    options = [v.YoutubeRegionOption(code=r.code, name=r.name, in_campaign=r.code in wanted) for r in REGIONS]
    return sorted(options, key=lambda o: (not o.in_campaign, o.name))


def source_info(row: m.YoutubeSource, comments: int) -> v.YoutubeSourceInfo:
    interval = get_settings().youtube_min_fetch_interval_seconds
    next_at = row.fetched_at + timedelta(seconds=interval)
    return v.YoutubeSourceInfo(
        id=row.id, video_id=row.video_id, video_url=video_url(row.video_id), video_title=row.video_title,
        version_label=row.version_label, region_code=row.region_code, region_name=REGION_NAMES.get(row.region_code, row.region_code),
        order=row.comment_order, comments=comments, pages_fetched=row.pages_fetched, truncated=row.truncated,  # type: ignore[arg-type]
        fetched_at=row.fetched_at, next_fetch_at=next_at if next_at > utcnow() else None)


async def _counts(s: AsyncSession, campaign_id: UUID) -> dict[str, int]:
    stmt = (select(m.PulseComment.video_id, func.count()).where(
        m.PulseComment.campaign_id == campaign_id, m.PulseComment.source_kind == SOURCE).group_by(m.PulseComment.video_id))
    return {video: n for video, n in (await s.execute(stmt)).all()}


async def status_block(s: AsyncSession, project: m.Project, campaign: m.Campaign) -> v.YoutubeStatus | None:
    """What the status offers: nothing in a demo project (it never calls YouTube) or on a server with no key."""
    settings = get_settings()
    if project.mode != "live" or settings.youtube_api_key is None:
        return None
    counts = await _counts(s, campaign.id)
    return v.YoutubeStatus(
        max_pages=settings.youtube_max_pages, max_comments=settings.youtube_max_pages * yt.PAGE_SIZE,
        min_interval_seconds=settings.youtube_min_fetch_interval_seconds, versions=await version_options(s, campaign.id),
        regions=region_options(campaign), sources=[source_info(x, counts.get(x.video_id, 0)) for x in await sources_of(s, campaign.id)])


# --- fetch ------------------------------------------------------------------------------------------------------------


async def _access(s: AsyncSession, user_id: UUID, campaign_id: UUID) -> tuple[m.Campaign, m.Project]:
    campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
    require_writable(project)
    return campaign, project


def _bad(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


async def _plan(s: AsyncSession, user_id: UUID, campaign_id: UUID, req: v.YoutubeFetchRequest, video_id: str) -> str | None:
    """Every check that needs no network: access, live project, key, version, region, one video per campaign, interval.
    Returns the video this version and region held before, which a different video replaces."""
    _, project = await _access(s, user_id, campaign_id)
    if project.mode != "live":
        raise Conflict("Demo projects use the sample comments and never call YouTube. Create a live project to read real comments.")
    settings = get_settings()
    if settings.youtube_api_key is None:
        raise ProviderNotConfigured("YouTube comments are not set up on this server.")
    versions = await version_options(s, campaign_id)
    if req.version_label not in versions:
        raise _bad("version_label", f"Not a version of this campaign. Available: {', '.join(versions)}.")
    if req.region_code not in REGION_NAMES:
        raise _bad("region_code", "Not a region in the reference data.")
    sources = await sources_of(s, campaign_id)
    held = next((x for x in sources if x.video_id == video_id), None)
    if held is not None and (held.version_label, held.region_code) != (req.version_label, req.region_code):
        raise Conflict(
            f"That video is already attached to {held.version_label} in {REGION_NAMES.get(held.region_code, held.region_code)}. "
            "Remove it there first.")
    last = await s.scalar(select(func.max(m.YoutubeSource.fetched_at)).where(m.YoutubeSource.video_id == video_id))
    wait = settings.youtube_min_fetch_interval_seconds
    if last is not None and (due := last + timedelta(seconds=wait)) > utcnow():
        raise RateLimited(
            f"That video was fetched at {last:%H:%M} UTC. To protect YouTube's daily quota it can be fetched again after {due:%H:%M} UTC.")
    slot = next((x for x in sources if (x.version_label, x.region_code) == (req.version_label, req.region_code)), None)
    return slot.video_id if slot is not None and slot.video_id != video_id else None


async def fetch(user_id: UUID, campaign_id: UUID, req: v.YoutubeFetchRequest) -> v.YoutubeFetchResult:
    video_id = yt.parse_video_id(req.video)
    if video_id is None:
        raise _bad("video", "Paste a public YouTube video link (watch, youtu.be, shorts or embed) or its 11-character id.")
    async with read_session() as s:
        replaced = await _plan(s, user_id, campaign_id, req, video_id)
    client = make_client()
    if client is None:
        raise ProviderNotConfigured("YouTube comments are not set up on this server.")
    try:  # the network call holds no database session
        title = await client.video_title(video_id)
        got = await client.comments(video_id, order=req.order, max_pages=get_settings().youtube_max_pages)
    except yt.YoutubeError as exc:
        raise app_error(exc) from None
    now = utcnow()
    try:
        async with session() as s, s.begin():
            _, project = await _access(s, user_id, campaign_id)  # access is checked again where rows are written
            stored = await _store(s, project, campaign_id, req, video_id, title, got, replaced, now, user_id)
    except IntegrityError:
        raise Conflict("Another fetch of this campaign's comments finished first. Reload and check the source.") from None
    return stored


async def _store(
    s: AsyncSession, project: m.Project, campaign_id: UUID, req: v.YoutubeFetchRequest, video_id: str, title: str,
    got: yt.FetchedComments, replaced: str | None, now: datetime, user_id: UUID,
) -> v.YoutubeFetchResult:
    if replaced is not None:
        await _drop_video(s, campaign_id, replaced)
    held = {r.external_id: r for r in (await s.execute(select(m.PulseComment).where(
        m.PulseComment.campaign_id == campaign_id, m.PulseComment.source_kind == SOURCE, m.PulseComment.video_id == video_id))).scalars()}
    fresh, updated, seen = [], 0, set()
    for c in got.comments:
        ref = ref_of(video_id, c.id)
        if ref in seen:  # a ref collision of two different comments is astronomically unlikely; the second one is left out
            continue
        seen.add(ref)
        language, script, code_mixed = lang.analyse(c.text)
        values = {
            "text": c.text[:TEXT_LIMIT], "likes": c.likes, "reply_count": c.replies, "language": language, "script": script,
            "code_mixed": code_mixed, "last_updated_at": now, "region_code": req.region_code, "version_label": req.version_label}
        row = held.get(c.id)
        if row is not None:
            for key, value in values.items():
                setattr(row, key, value)
            updated += 1
            continue
        fresh.append({
            "id": uuid5(NAMESPACE, f"{campaign_id}|{ref}"), "workspace_id": project.workspace_id, "project_id": project.id,
            "campaign_id": campaign_id, "ref": ref, "day": c.published_at.date(), "platform": "youtube", "source_kind": SOURCE,
            "dataset_version": DATASET_VERSION, "video_id": video_id, "external_id": c.id, "published_at": c.published_at, **values})
    if fresh:
        await s.execute(insert(m.PulseComment), fresh)
    source = next((x for x in await sources_of(s, campaign_id) if x.video_id == video_id), None)
    fields = {
        "video_title": title or None, "version_label": req.version_label, "region_code": req.region_code, "comment_order": req.order,
        "pages_fetched": got.pages, "truncated": got.truncated, "fetched_at": now}
    if source is None:
        source = m.YoutubeSource(
            id=uuid4(), workspace_id=project.workspace_id, project_id=project.id, campaign_id=campaign_id, video_id=video_id,
            created_by=user_id, created_at=now, **fields)
        s.add(source)
    else:
        for key, value in fields.items():
            setattr(source, key, value)
    await s.flush()
    total = await s.scalar(select(func.count()).select_from(m.PulseComment).where(
        m.PulseComment.campaign_id == campaign_id, m.PulseComment.source_kind == SOURCE, m.PulseComment.video_id == video_id))
    await record_audit(
        s, action="pulse.comments.youtube.fetch", target_type="campaign", target_id=str(campaign_id), workspace_id=project.workspace_id,
        actor_user_id=user_id, detail={
            "video_id": video_id, "order": req.order, "pages": got.pages, "fetched": len(got.comments), "added": len(fresh),
            "updated": updated, "replaced_video_id": replaced, "version_label": req.version_label, "region_code": req.region_code})
    return v.YoutubeFetchResult(
        source=source_info(source, total or 0), fetched=len(got.comments), added=len(fresh), updated=updated, skipped=got.skipped,
        replaced_video_id=replaced)


async def _drop_video(s: AsyncSession, campaign_id: UUID, video_id: str) -> None:
    await s.execute(delete(m.PulseComment).where(
        m.PulseComment.campaign_id == campaign_id, m.PulseComment.source_kind == SOURCE, m.PulseComment.video_id == video_id))
    await s.execute(delete(m.YoutubeSource).where(m.YoutubeSource.campaign_id == campaign_id, m.YoutubeSource.video_id == video_id))
    await s.flush()


async def remove(user_id: UUID, campaign_id: UUID, source_id: UUID) -> None:
    """Disconnect one video: its stored comments and its source row go. With no video left, Comment Pulse shows the sample again."""
    async with session() as s, s.begin():
        _, project = await _access(s, user_id, campaign_id)
        row = await s.scalar(select(m.YoutubeSource).where(m.YoutubeSource.id == source_id, m.YoutubeSource.campaign_id == campaign_id))
        if row is None:
            raise NotFound("That YouTube source was not found for this campaign.")
        video_id = row.video_id
        await _drop_video(s, campaign_id, video_id)
        await record_audit(
            s, action="pulse.comments.youtube.remove", target_type="campaign", target_id=str(campaign_id),
            workspace_id=project.workspace_id, actor_user_id=user_id, detail={"video_id": video_id})
