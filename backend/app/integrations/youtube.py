"""YouTube Data API v3, read only, for Comment Pulse: the public comments of one video, and its title.

Server side only. The API key comes from settings and is sent in the `X-Goog-Api-Key` header, never in the URL, so an HTTP
log line cannot carry it (the JSON log formatter also redacts it). Requests ask Google for only the fields used here
(`fields=`), so a commenter's name, channel id and avatar never reach this process. Costs: `commentThreads.list` and
`videos.list` are 1 quota unit a call, and the daily quota of the key is 10,000 units for the whole app.

HTTP goes through the culture layer's HttpFetcher (timeout, capped retries on 429 and 5xx, typed errors); a failure leaves
this module as a `YoutubeError` whose `state` and message are safe to show. Tests inject an httpx.AsyncClient with a
MockTransport, so no test touches the network.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import httpx

from app.integrations.culture.base import (
    CultureSourceError,
    SourceNetworkError,
    SourceRateLimited,
    SourceTimeout,
)
from app.integrations.culture.http import HttpFetcher

API_ROOT = "https://www.googleapis.com/youtube/v3"
USER_AGENT = "OmnicultCommentPulse/0.1 (public comments of a video the user names)"
PAGE_SIZE = 100  # the largest maxResults commentThreads.list accepts
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com", "youtu.be", "www.youtu.be"})
PATH_PREFIXES = ("shorts", "embed", "live", "v")
THREAD_FIELDS = "nextPageToken,items(id,snippet(totalReplyCount,topLevelComment(id,snippet(textDisplay,likeCount,publishedAt))))"
VIDEO_FIELDS = "items(id,snippet(title))"
QUOTA_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"})
KEY_REASONS = frozenset({"keyInvalid", "API_KEY_INVALID", "ipRefererBlocked", "accessNotConfigured", "keyExpired", "API_KEY_SERVICE_BLOCKED"})

YoutubeState = Literal["comments_disabled", "video_not_found", "quota_exceeded", "key_rejected", "timeout", "network", "unavailable"]
Order = Literal["relevance", "time"]

MESSAGES: dict[str, str] = {
    "comments_disabled": "Comments are turned off on that video, or YouTube does not let this app read them.",
    "video_not_found": "No public YouTube video was found for that link or id. It may be private, removed or mistyped.",
    "quota_exceeded": "YouTube's request quota for this app is used up for now. Try again later (the daily quota resets at midnight Pacific time).",
    "key_rejected": "YouTube did not accept this server's API key. The key needs to be checked by whoever runs the server.",
    "timeout": "YouTube did not answer in time. Try again in a moment.",
    "network": "YouTube could not be reached from the server. Try again in a moment.",
    "unavailable": "YouTube returned an answer this app could not use. Try again later.",
}


class YoutubeError(Exception):
    """A YouTube call failed. `state` names which way; the message is written for the user and never carries the key."""

    def __init__(self, state: YoutubeState) -> None:
        super().__init__(MESSAGES[state])
        self.state = state


# --- the video the user pastes ------------------------------------------------------------------------------------------


def parse_video_id(raw: str) -> str | None:
    """The 11-character video id from a watch, short, shorts, embed or live link, or from a bare id. None when it is neither."""
    text = raw.strip()
    if VIDEO_ID.fullmatch(text):
        return text
    parsed = urlparse(text if "//" in text else "https://" + text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in HOSTS:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if host.endswith("youtu.be"):
        candidate = parts[0] if parts else ""
    elif parts and parts[0] == "watch":
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    elif len(parts) >= 2 and parts[0] in PATH_PREFIXES:
        candidate = parts[1]
    else:
        return None
    return candidate if VIDEO_ID.fullmatch(candidate) else None


# --- results ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class YoutubeComment:
    """One top-level comment. Deliberately has no author field of any kind."""

    id: str
    text: str
    published_at: datetime
    likes: int
    replies: int


@dataclass
class FetchedComments:
    comments: list[YoutubeComment] = field(default_factory=list)
    pages: int = 0
    truncated: bool = False  # the page cap stopped the fetch while YouTube still had a next page
    skipped: int = 0  # items that were not a readable comment


# --- the client -------------------------------------------------------------------------------------------------------


def _reasons(error: CultureSourceError) -> set[str]:
    """Every reason Google named in the error body (`error.errors[].reason` and `error.details[].reason`)."""
    body = error.payload if isinstance(error.payload, dict) else {}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    found = {str(i["reason"]) for key in ("errors", "details") for i in (err.get(key) or []) if isinstance(i, dict) and i.get("reason")}
    return found


def failure_of(error: CultureSourceError) -> YoutubeError:
    """Map a typed fetch error onto the few states a user can act on."""
    reasons = _reasons(error)
    if isinstance(error, SourceTimeout):
        return YoutubeError("timeout")
    if isinstance(error, SourceNetworkError):
        return YoutubeError("network")
    if isinstance(error, SourceRateLimited) or reasons & QUOTA_REASONS:
        return YoutubeError("quota_exceeded")
    if reasons & KEY_REASONS:
        return YoutubeError("key_rejected")
    if reasons & {"commentsDisabled", "forbidden"}:
        return YoutubeError("comments_disabled")
    if error.status_code == 404 or reasons & {"videoNotFound", "notFound"}:
        return YoutubeError("video_not_found")
    return YoutubeError("unavailable")


class YoutubeClient:
    def __init__(
        self, api_key: str, *, timeout: float = 15.0, client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._key = api_key
        extra: dict[str, Any] = {"sleep": sleep} if sleep is not None else {}
        self._http = HttpFetcher("youtube", user_agent=USER_AGENT, timeout=timeout, client=client, **extra)

    async def _get(self, resource: str, params: dict[str, Any], operation: str) -> dict[str, Any]:
        try:
            body = await self._http.get_json(f"{API_ROOT}/{resource}", params, operation=operation, headers={"X-Goog-Api-Key": self._key})
        except CultureSourceError as exc:
            raise failure_of(exc) from None  # the original error holds no key, but a user-facing state is all a caller needs
        if not isinstance(body, dict):
            raise YoutubeError("unavailable")
        return body

    async def video_title(self, video_id: str) -> str:
        """The title of a public video (1 quota unit). A video that is private, removed or unknown is `video_not_found`."""
        body = await self._get("videos", {"part": "snippet", "id": video_id, "fields": VIDEO_FIELDS}, "video")
        items = body.get("items")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise YoutubeError("video_not_found")
        snippet = items[0].get("snippet")
        title = snippet.get("title") if isinstance(snippet, dict) else None
        return " ".join(str(title).split()) if title else ""

    async def comments(self, video_id: str, *, order: Order, max_pages: int) -> FetchedComments:
        """Top-level comments, newest page first by `order`, at most `max_pages` pages of 100 (1 quota unit a page)."""
        out = FetchedComments()
        seen: set[str] = set()
        token: str | None = None
        while out.pages < max_pages:
            params: dict[str, Any] = {
                "part": "snippet", "videoId": video_id, "maxResults": PAGE_SIZE, "order": order, "textFormat": "plainText",
                "fields": THREAD_FIELDS,
            }
            if token:
                params["pageToken"] = token
            body = await self._get("commentThreads", params, "comments")
            out.pages += 1
            for item in body.get("items") or []:
                parsed = _comment_of(item)
                if parsed is None:
                    out.skipped += 1
                elif parsed.id not in seen:  # a page can repeat a comment when new ones arrive between two requests
                    seen.add(parsed.id)
                    out.comments.append(parsed)
            token = body.get("nextPageToken") or None
            if not token:
                break
        out.truncated = token is not None
        return out


def _comment_of(item: Any) -> YoutubeComment | None:
    try:
        thread = item["snippet"]
        top = thread["topLevelComment"]
        snippet = top["snippet"]
        text = str(snippet["textDisplay"]).strip()
        published = datetime.fromisoformat(str(snippet["publishedAt"]).replace("Z", "+00:00"))
        comment_id = str(top.get("id") or item.get("id") or "")
        likes, replies = int(snippet.get("likeCount") or 0), int(thread.get("totalReplyCount") or 0)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if not comment_id or not text:
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    return YoutubeComment(comment_id, text, published.astimezone(UTC), max(likes, 0), max(replies, 0))
