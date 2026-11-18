"""A fake YouTube Data API for tests: an httpx MockTransport that answers videos.list and commentThreads.list.

No test using this reaches the network. The fake deliberately sends author fields (name, channel id, avatar) in every comment
even though the real request asks Google for none of them, so a test can prove the code keeps none of them.
"""

from collections.abc import Callable
from typing import Any

import httpx

from app.integrations.youtube import YoutubeClient

KEY = "test-youtube-api-key-not-real"
VIDEO = "dQw4w9WgXcQ"
OTHER_VIDEO = "9bZkp7q19f0"
AUTHOR = "Priya Subramaniam"
CHANNEL = "UCtestChannelId0123456789"
AVATAR = "https://yt3.ggpht.com/avatar-secret-path"


def comment(i: int, *, text: str | None = None, likes: int = 0, replies: int = 0, published: str = "2026-10-28T10:00:00Z") -> dict[str, Any]:
    cid = f"Ugx{i:04d}TestCommentId"
    return {
        "id": cid,
        "snippet": {
            "totalReplyCount": replies, "canReply": True, "videoId": VIDEO,
            "topLevelComment": {"id": cid, "snippet": {
                "textDisplay": text if text is not None else f"Comment number {i} about the film",
                "textOriginal": "never requested", "likeCount": likes, "publishedAt": published, "updatedAt": published,
                "authorDisplayName": AUTHOR, "authorChannelId": {"value": CHANNEL}, "authorProfileImageUrl": AVATAR,
                "authorChannelUrl": f"http://www.youtube.com/channel/{CHANNEL}",
            }},
        },
    }


def error_body(status: int, *reasons: str) -> dict[str, Any]:
    return {"error": {"code": status, "message": "A message the app must not repeat.", "errors": [{"reason": r, "domain": "youtube"} for r in reasons]}}


def error(status: int, *reasons: str) -> httpx.Response:
    return httpx.Response(status, json=error_body(status, *reasons))


class FakeYoutube:
    """Pages of comments by token (`p2`, `p3`, ...), a title, and optional canned replies per resource."""

    def __init__(
        self, pages: list[list[dict[str, Any]]] | None = None, *, title: str | None = "Aamod Festive Tin | Diwali film",
        videos: Callable[[httpx.Request], httpx.Response | Exception] | None = None,
        threads: Callable[[httpx.Request], httpx.Response | Exception] | None = None,
    ) -> None:
        self.pages = pages if pages is not None else [[comment(1)]]
        self.title, self.videos, self.threads = title, videos, threads
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        resource = request.url.path.rsplit("/", 1)[-1]
        override = self.videos if resource == "videos" else self.threads if resource == "commentThreads" else None
        if override is not None:
            answer = override(request)
            if isinstance(answer, Exception):
                raise answer
            return answer
        if resource == "videos":
            items = [] if self.title is None else [{"id": request.url.params["id"], "snippet": {"title": self.title}}]
            return httpx.Response(200, json={"items": items})
        if resource == "commentThreads":
            token = request.url.params.get("pageToken")
            index = int(token[1:]) - 1 if token else 0
            body: dict[str, Any] = {"items": self.pages[index]}
            if index + 1 < len(self.pages):
                body["nextPageToken"] = f"p{index + 2}"
            return httpx.Response(200, json=body)
        return httpx.Response(404, json=error_body(404, "notFound"))

    def calls(self, resource: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith("/" + resource)]

    def client(self) -> YoutubeClient:
        async def no_sleep(_: float) -> None:
            return None

        return YoutubeClient(KEY, client=httpx.AsyncClient(transport=httpx.MockTransport(self)), sleep=no_sleep)
