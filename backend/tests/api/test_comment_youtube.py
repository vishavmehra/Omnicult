"""Comment Pulse on public YouTube comments: attach a video, fetch, store, count, read, remove. No network: a fake YouTube API.

The fake sends a commenter's name, channel id and avatar with every comment, so these tests can prove none of it is kept.
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import models as m
from app.db.session import read_session
from app.fixtures import pulse_comments as sample
from app.llm.fixture import FixtureLLMProvider
from app.llm.gateway import LLMGateway
from app.services import comment_youtube, studio_context
from tests.api.omnicult_support import API, add_member, client_for, seeded, workspace_of  # noqa: F401
from tests.api.test_comment_pulse import COMMENTS, demo_campaign, live_campaign, scripted
from tests.api.youtube_support import AUTHOR, AVATAR, CHANNEL, KEY, OTHER_VIDEO, VIDEO, FakeYoutube, comment, error
from tests.conftest import BOB

TITLE = "Aamod Festive Tin | Diwali film"
CLAIM = "Is it really the best faral tin in Maharashtra?"
FESTIVAL = "We celebrate Onam here, not Diwali"
TAMIL = "வாழ்த்துக்கள் super ad"
ENGLISH = "Lovely film, the song is beautiful"
MARATHI = "मला हा खूप आवडला"
THREE = [comment(1, text=TAMIL, likes=9, replies=2, published="2026-10-28T10:00:00Z"),
         comment(2, text=CLAIM, likes=4, published="2026-11-04T09:30:00Z"),
         comment(3, text=FESTIVAL, likes=1, published="2026-11-11T20:15:00Z")]


@pytest.fixture
def youtube(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> FakeYoutube:
    """A server with a YouTube key (no wait between fetches) whose YouTube is the fake."""
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    monkeypatch.setenv("YOUTUBE_MIN_FETCH_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    fake = FakeYoutube([THREE], title=TITLE)
    monkeypatch.setattr(comment_youtube, "make_client", lambda: fake.client())
    return fake


async def attach(
    client: httpx.AsyncClient, base: str, *, video: str = VIDEO, version: str = "Campaign video", region: str = "IN-TN", order: str = "relevance",
) -> httpx.Response:
    return await client.post(f"{base}/youtube", json={"video": video, "version_label": version, "region_code": region, "order": order})


async def fetched(client: httpx.AsyncClient, youtube: FakeYoutube, pages: list[list[dict[str, Any]]] | None = None, **kw: Any) -> tuple[str, dict[str, Any]]:
    if pages is not None:
        youtube.pages = pages
    _, base = await live_campaign(client)
    response = await attach(client, base, **kw)
    assert response.status_code == 200, response.text
    return base, response.json()


def scripted_youtube(responder: Callable[[dict[str, Any]], Any], monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    class Provider(FixtureLLMProvider):
        name = "scripted"

    def answer(ctx: Any) -> Any:
        seen.append(dict(ctx))
        return responder(dict(ctx))

    provider = Provider({"comment-read-yt-v1": answer})
    monkeypatch.setattr(studio_context, "gateway_for", lambda mode: LLMGateway(get_settings(), provider=provider, backoff_seconds=0))
    return seen


def comment_ref(comment_id: str) -> str:
    return comment_youtube.ref_of(VIDEO, comment_id)


def label_all(ctx: dict[str, Any], sentiment: str = "positive") -> dict[str, Any]:
    return {"comments": [{"ref": c["ref"], "sentiment": sentiment, "themes": []} for c in ctx["comments"]], "themes": []}


# --- what is offered ----------------------------------------------------------------------------------------------------


async def test_youtube_is_offered_only_in_a_live_project_on_a_server_with_a_key(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, base = await live_campaign(client)
    assert (await client.get(f"{base}/status")).json()["youtube"] is None, "no key on this server: nothing is offered"
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    get_settings.cache_clear()
    offered = (await client.get(f"{base}/status")).json()["youtube"]
    assert offered["max_pages"] == 5 and offered["max_comments"] == 500 and offered["sources"] == []
    assert offered["versions"] == ["Campaign video"] and offered["min_interval_seconds"] == 900
    assert len(offered["regions"]) == 36 and {"code": "IN-TN", "name": "Tamil Nadu", "in_campaign": False} in offered["regions"]
    _, demo = await demo_campaign(client)
    assert (await client.get(f"{demo}/status")).json()["youtube"] is None, "a demo project never offers YouTube"
    assert KEY not in json.dumps(offered)


async def test_the_versions_on_offer_are_the_campaigns_studio_versions(client: httpx.AsyncClient, youtube: FakeYoutube) -> None:
    project, base = await live_campaign(client)
    cid = base.split("/campaigns/")[1].split("/")[0]
    root = (await client.post(f"{API}/campaigns/{cid}/versions", json={
        "label": "Original film", "region_code": "IN-MH", "language": "mr",
        "elements": [{"id": "headline", "kind": "headline", "value": "x", "language": "mr", "script": "Deva"}]})).json()
    assert (await client.get(f"{base}/status")).json()["youtube"]["versions"] == ["Original film", "Campaign video"]
    done = await attach(client, base, version="Original film", region="IN-MH")
    assert done.status_code == 200, done.text
    listing = await client.get(f"{base}?limit=100")
    assert listing.status_code == 200, listing.text
    item = listing.json()["items"][0]
    assert item["anchor"]["studio_version_id"] == root["id"] and item["anchor"]["studio_version_label"] == "Original film"
    assert project["mode"] == "live"


# --- fetch and store ----------------------------------------------------------------------------------------------------------


async def test_a_fetch_stores_the_comment_and_never_who_wrote_it(client: httpx.AsyncClient, youtube: FakeYoutube) -> None:
    base, result = await fetched(client, youtube)
    assert (result["fetched"], result["added"], result["updated"], result["skipped"]) == (3, 3, 0, 0)
    source = result["source"]
    assert source["video_id"] == VIDEO and source["video_title"] == TITLE and source["comments"] == 3 and source["order"] == "relevance"
    assert source["video_url"] == f"https://www.youtube.com/watch?v={VIDEO}" and source["region_name"] == "Tamil Nadu"
    assert source["pages_fetched"] == 1 and source["truncated"] is False and source["next_fetch_at"] is None
    async with read_session() as s:
        rows = list((await s.execute(select(m.PulseComment).order_by(m.PulseComment.ref))).scalars())
        assert len(rows) == 3 and {r.source_kind for r in rows} == {"youtube"} and {r.video_id for r in rows} == {VIDEO}
        by_text = {r.text: r for r in rows}
        tamil = by_text[TAMIL]
        assert (tamil.likes, tamil.reply_count, tamil.external_id, tamil.platform) == (9, 2, "Ugx0001TestCommentId", "youtube")
        assert tamil.published_at == datetime(2026, 10, 28, 10, 0, tzinfo=UTC) and tamil.day.isoformat() == "2026-10-28"
        assert (tamil.region_code, tamil.version_label, tamil.language, tamil.script, tamil.code_mixed) == ("IN-TN", "Campaign video", "ta", "Taml", True)
        assert tamil.ref.startswith("yt-") and len(tamil.ref) <= 16 and tamil.ref != tamil.external_id
        everything = json.dumps([{c.name: str(getattr(r, c.name)) for c in r.__table__.columns} for r in rows]) + json.dumps(
            [{c.name: str(getattr(x, c.name)) for c in x.__table__.columns} for x in (await s.execute(select(m.YoutubeSource))).scalars()])
        for personal in (AUTHOR, CHANNEL, AVATAR, "Priya", "never requested"):
            assert personal not in everything, f"{personal!r} was stored"
        audit = (await s.execute(select(m.AuditLog).where(m.AuditLog.action == "pulse.comments.youtube.fetch"))).scalar_one()
        assert audit.detail["video_id"] == VIDEO and audit.detail["added"] == 3 and KEY not in json.dumps(audit.detail)
    for url in (f"{base}/status", f"{base}/summary", f"{base}/themes", f"{base}?limit=10"):
        body = json.dumps((await client.get(url)).json())
        assert AUTHOR not in body and CHANNEL not in body and AVATAR not in body and KEY not in body


def test_no_column_could_hold_an_author() -> None:
    names = {c.name for c in m.PulseComment.__table__.columns} | {c.name for c in m.YoutubeSource.__table__.columns}
    assert not [n for n in names if any(word in n for word in ("author", "channel", "avatar", "profile", "user", "name"))], names
    assert names >= {"video_id", "external_id", "published_at", "reply_count", "text", "likes"}


async def test_the_request_is_a_get_with_the_key_in_a_header_and_no_author_field_asked_for(client: httpx.AsyncClient, youtube: FakeYoutube) -> None:
    await fetched(client, youtube, order="time")
    assert [r.method for r in youtube.requests] == ["GET", "GET"] and [r.url.path.rsplit("/", 1)[-1] for r in youtube.requests] == ["videos", "commentThreads"]
    for request in youtube.requests:
        assert request.headers["X-Goog-Api-Key"] == KEY and KEY not in str(request.url)
        assert "author" not in request.url.params.get("fields", "").lower()
    thread = youtube.calls("commentThreads")[0].url.params
    assert thread["order"] == "time" and thread["maxResults"] == "100" and thread["textFormat"] == "plainText"


async def test_comments_are_paged_up_to_the_cap_and_no_further(client: httpx.AsyncClient, youtube: FakeYoutube, monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [[comment(p * 10 + i, text=f"page {p} comment {i}") for i in range(3)] for p in range(1, 8)]
    base, two = await fetched(client, youtube, pages[:3])
    assert two["source"]["pages_fetched"] == 3 and two["source"]["truncated"] is False and two["fetched"] == 9
    assert len(youtube.calls("commentThreads")) == 3

    monkeypatch.setenv("YOUTUBE_MAX_PAGES", "2")
    get_settings.cache_clear()
    youtube.requests.clear()
    youtube.pages = pages
    _, capped = await fetched(client, youtube, order="time")
    assert capped["source"]["pages_fetched"] == 2 and capped["source"]["truncated"] is True and capped["fetched"] == 6
    assert len(youtube.calls("commentThreads")) == 2, "the page cap bounds the quota spent"
    offered = (await client.get(f"{base}/status")).json()["youtube"]
    assert offered["max_pages"] == 2 and offered["max_comments"] == 200 and offered["sources"][0]["comments"] == 9


async def test_fetching_again_updates_by_comment_id_and_never_duplicates(client: httpx.AsyncClient, youtube: FakeYoutube) -> None:
    base, first = await fetched(client, youtube)
    async with read_session() as s:
        ids = sorted(str(i) for i in await s.scalars(select(m.PulseComment.id)))
    youtube.pages = [[comment(1, text=TAMIL, likes=40, replies=7), comment(2, text=CLAIM, likes=5), comment(3, text=FESTIVAL, likes=1), comment(4, text=ENGLISH, likes=2)]]
    again = (await attach(client, base)).json()
    assert (again["fetched"], again["added"], again["updated"]) == (4, 1, 3) and again["source"]["comments"] == 4
    async with read_session() as s:
        rows = list((await s.execute(select(m.PulseComment))).scalars())
        assert len(rows) == 4 and len({r.external_id for r in rows}) == 4
        assert set(ids) <= {str(r.id) for r in rows}, "a comment keeps its id"
        tamil = next(r for r in rows if r.external_id == "Ugx0001TestCommentId")
        assert (tamil.likes, tamil.reply_count) == (40, 7)
        assert await s.scalar(select(func.count()).select_from(m.YoutubeSource)) == 1
    same = (await attach(client, base)).json()
    assert (same["added"], same["updated"], same["source"]["comments"]) == (0, 4, 4)
    assert first["source"]["id"] == again["source"]["id"] == same["source"]["id"]


# --- the numbers, by code ------------------------------------------------------------------------------------------------


async def test_counts_languages_scripts_and_watch_terms_are_computed_from_the_stored_comments(client: httpx.AsyncClient, youtube: FakeYoutube) -> None:
    pages = [[*THREE, comment(4, text=MARATHI, likes=3, published="2026-11-12T08:00:00Z"), comment(5, text="😍😍", likes=0, published="2026-11-12T09:00:00Z")]]
    base, _ = await fetched(client, youtube, pages)
    status = (await client.get(f"{base}/status")).json()
    assert status["loaded"] is True and status["is_sample"] is False and status["source_kind"] == "youtube" and status["label"] == "YouTube comments"
    assert status["source_line"] == f"Source: YouTube comments on {TITLE}"
    assert status["comment_count"] == 5 and status["regions"] == ["IN-TN"] and status["versions"] == ["Campaign video"]
    assert status["languages"] == ["en", "mr", "ta", "zxx"] and status["date_from"] == "2026-10-28" and status["date_to"] == "2026-11-12"
    summary = (await client.get(f"{base}/summary")).json()
    assert summary["is_sample"] is False and summary["source_kind"] == "youtube" and summary["label"] == "YouTube comments"
    assert summary["source_line"] == status["source_line"] and summary["dataset_version"].startswith("youtube-")
    assert any("chose to write one" in x for x in summary["limitations"]) and not any("demo" in x.lower() for x in summary["limitations"])
    t = summary["totals"]
    assert (t["comments"], t["likes"], t["claim_mentions"], t["cultural_mentions"], t["flagged_comments"]) == (5, 17, 1, 1, 2)
    langs = {x["language"]: x for x in summary["languages"]}
    assert {k: (v["comments"], v["script"], v["language_name"]) for k, v in langs.items()} == {
        "en": (2, "Latn", "English"), "ta": (1, "Taml", "Tamil"), "mr": (1, "Deva", "Marathi"), "zxx": (1, "Zyyy", "Emoji or symbols only")}
    assert langs["ta"]["code_mixed_comments"] == 1
    assert summary["sentiment"] is None and summary["analysis"] is None
    assert sum(d["comments"] for d in summary["daily"]) == 5 and sum(w["comments"] for w in summary["weekly"]) == 5
    assert [w["week_start"] for w in summary["weekly"]] == ["2026-10-28", "2026-11-04", "2026-11-11"]
    (slice_,) = summary["slices"]
    assert slice_["region_code"] == "IN-TN" and slice_["comments"] == 5 and slice_["confidence"] == "low"
    assert "Public comments" in slice_["confidence_rule"] and "Sample" not in slice_["confidence_rule"]
    flagged = (await client.get(f"{base}?flag=any&limit=100")).json()
    assert flagged["is_sample"] is False and {c["text"] for c in flagged["items"]} == {CLAIM, FESTIVAL}
    for c in flagged["items"]:
        assert c["flags"][0]["evidence"] == "observed" and "Diwali" not in c["flags"][0]["note"], "the sample's story is not told about real comments"
        assert c["platform"] == "youtube" and c["anchor"]["version_label"] == "Campaign video"
    assert (await client.get(f"{base}/summary?language=zxx")).json()["totals"]["comments"] == 1
    assert (await client.get(f"{base}/summary?language=und")).status_code == 422, "a language that no comment has is refused, like any unknown filter value"
    assert (await client.get(f"{base}/summary?language=fr")).status_code == 422


async def test_the_trend_of_a_years_old_video_is_bounded(client: httpx.AsyncClient, youtube: FakeYoutube) -> None:
    old = [comment(i, published=f"2019-0{1 + i % 9}-1{i % 9}T10:00:00Z") for i in range(1, 12)]
    recent = [comment(20 + i, published=(datetime(2026, 11, 17, tzinfo=UTC) - timedelta(days=9 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")) for i in range(6)]
    base, _ = await fetched(client, youtube, [[*old, *recent]])
    summary = (await client.get(f"{base}/summary")).json()
    assert summary["totals"]["comments"] == 17, "every comment is counted"
    assert len(summary["daily"]) == 60 and len(summary["weekly"]) == 26, "the trend shows the latest 60 days and 26 weeks"
    assert summary["daily"][-1]["date"] == "2026-11-17" and summary["weekly"][-1]["week_end"] >= "2026-11-17"
    assert sum(w["comments"] for w in summary["weekly"]) < 17


# --- the model reading ----------------------------------------------------------------------------------------------------


async def test_a_live_reading_of_youtube_comments_uses_the_youtube_prompt_and_labels_by_ref(client: httpx.AsyncClient, youtube: FakeYoutube, monkeypatch: pytest.MonkeyPatch) -> None:
    long = ("good " * 400).strip()
    base, _ = await fetched(client, youtube, [[*THREE, comment(4, text=long, likes=2)]])
    seen = scripted_youtube(lambda ctx: {
        "comments": [{"ref": c["ref"], "sentiment": "negative" if "faral" in c["text"] else "positive", "themes": ["film"]} for c in ctx["comments"]],
        "themes": [{"id": "film", "label": "The film", "summary": "People talk about the film."}]}, monkeypatch)
    done = await client.post(f"{base}/read")
    assert done.status_code == 200, done.text
    info = done.json()["analysis"]
    assert info["prompt_version"] == "comment-read-yt-v1" and info["provider"] == "scripted" and info["mode"] == "live" and info["is_fixture"] is False
    assert info["comment_count"] == info["read_count"] == 4 and info["status"] == "completed"
    (payload,) = seen
    assert all(set(c) == {"ref", "region", "language", "text"} and c["ref"].startswith("yt-") for c in payload["comments"])
    assert max(len(c["text"]) for c in payload["comments"]) == 600, "a long comment is cut in the prompt"
    assert any(c["language"] == "Tamil" for c in payload["comments"]) and not any(AUTHOR in json.dumps(c) for c in payload["comments"])
    async with read_session() as s:
        stored = (await s.execute(select(m.CommentAnalysis))).scalar_one()
        assert stored.source_kind == "youtube" and stored.dataset_version.startswith("youtube-") and len(stored.labels) == 4
        assert max(len(r.text) for r in await s.scalars(select(m.PulseComment))) == len(long), "the stored text is whole"
    summary = (await client.get(f"{base}/summary")).json()
    assert summary["sentiment"] == {"positive": 3, "neutral": 0, "negative": 1, "mixed": 0, "unread": 0} and summary["analysis"]["id"] == info["id"]
    themes = (await client.get(f"{base}/themes")).json()
    assert themes["is_sample"] is False and [t["id"] for t in themes["themes"]] == ["film"]
    assert {q["text"] for q in themes["themes"][0]["quotes"]} <= {c["text"] for c in (await client.get(f"{base}?limit=100")).json()["items"]}, "quotes are stored comments"
    assert (await client.post(f"{base}/read")).json()["reused"] is True
    youtube.pages = [[*THREE, comment(4, text=long, likes=2), comment(9, text="a new one", likes=1)]]
    await attach(client, base)
    assert (await client.post(f"{base}/read")).json()["reused"] is False, "a different set of comments is read again"


async def test_only_the_most_liked_comments_up_to_one_calls_worth_are_read(client: httpx.AsyncClient, youtube: FakeYoutube, monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [[comment(p * 100 + i, text=f"comment {p}-{i}", likes=(p * 100 + i) % 37) for i in range(100)] for p in range(1, 5)]
    base, result = await fetched(client, youtube, pages)
    assert result["fetched"] == 400
    seen = scripted_youtube(label_all, monkeypatch)
    info = (await client.post(f"{base}/read")).json()["analysis"]
    assert info["comment_count"] == info["read_count"] == 300 and any("300 most-liked of 400" in n for n in info["notes"])
    every = [(x["snippet"]["topLevelComment"]["snippet"]["likeCount"], comment_ref(x["id"]), x["snippet"]["topLevelComment"]["snippet"]["textDisplay"]) for p in pages for x in p]
    expected = {text for _, _, text in sorted(every, key=lambda e: (-e[0], e[1]))[:300]}
    assert {c["text"] for c in seen[0]["comments"]} == expected and len(expected) == 300, "the 300 most liked, ties broken by ref"
    summary = (await client.get(f"{base}/summary")).json()
    assert summary["sentiment"]["unread"] == 100 and summary["coverage"]["read_share"] == 0.75


async def test_the_sample_and_its_reading_stay_apart_from_the_youtube_ones(client: httpx.AsyncClient, youtube: FakeYoutube, monkeypatch: pytest.MonkeyPatch) -> None:
    _, base = await live_campaign(client)
    assert (await client.post(f"{base}/sample")).status_code == 200
    scripted(lambda ctx: {"comments": [{"ref": c["ref"], "sentiment": "neutral", "themes": []} for c in ctx["comments"]], "themes": []}, monkeypatch)
    assert (await client.post(f"{base}/read")).status_code == 200
    assert (await client.get(f"{base}/status")).json()["source_kind"] == "sample"

    done = await attach(client, base)
    assert done.status_code == 200
    status = (await client.get(f"{base}/status")).json()
    assert status["source_kind"] == "youtube" and status["comment_count"] == 3 and status["analysis"] is None, "the sample's reading is not shown for YouTube comments"
    assert (await client.get(f"{base}/summary")).json()["sentiment"] is None

    removed = await client.delete(f"{base}/youtube/{done.json()['source']['id']}")
    assert removed.status_code == 204
    back = (await client.get(f"{base}/status")).json()
    assert back["source_kind"] == "sample" and back["is_sample"] is True and back["comment_count"] == COMMENTS and back["analysis"] is not None
    assert back["source_line"] == "Source: sample comments, written for the demo, not from a connected channel"
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.PulseComment).where(m.PulseComment.source_kind == "youtube")) == 0
        assert await s.scalar(select(func.count()).select_from(m.YoutubeSource)) == 0
        assert (await s.execute(select(m.AuditLog).where(m.AuditLog.action == "pulse.comments.youtube.remove"))).scalar_one().detail == {"video_id": VIDEO}
    assert len(sample.generate_comments()) == COMMENTS


# --- slices: one video per version and region ----------------------------------------------------------------------------------


async def test_a_campaign_can_attach_a_video_per_region_and_a_new_video_replaces_the_old_one(client: httpx.AsyncClient, youtube: FakeYoutube) -> None:
    base, _ = await fetched(client, youtube)
    youtube.pages = [[comment(50, text="Kerala says hello", likes=3)]]
    kerala = (await attach(client, base, video=OTHER_VIDEO, region="IN-KL")).json()
    assert kerala["replaced_video_id"] is None
    assert (await client.get(f"{base}/status")).json()["source_line"] == f"Source: YouTube comments on {TITLE} and 1 more video"
    assert (await client.get(f"{base}/status")).json()["regions"] == ["IN-KL", "IN-TN"]

    taken = await attach(client, base, video=OTHER_VIDEO, region="IN-WB")
    assert taken.status_code == 409 and "already attached to Campaign video in Kerala" in taken.json()["error"]["message"]

    third = "aaaaaaaaaaa"
    youtube.pages = [[comment(60, text="a different film in Tamil Nadu")]]
    swapped = (await attach(client, base, video=third, region="IN-TN")).json()
    assert swapped["replaced_video_id"] == VIDEO and swapped["source"]["video_id"] == third
    async with read_session() as s:
        assert set(await s.scalars(select(m.PulseComment.video_id).distinct())) == {OTHER_VIDEO, third}
        assert await s.scalar(select(func.count()).select_from(m.YoutubeSource)) == 2


# --- failure states -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("fault", "status", "words"), [
    ("comments_disabled", 409, "Comments are turned off"),
    ("not_found", 422, "No public YouTube video"),
    ("quota", 429, "quota for this app is used up"),
    ("key", 503, "did not accept this server's API key"),
    ("network", 502, "could not be reached"),
    ("timeout", 504, "did not answer in time"),
    ("garbage", 502, "could not use"),
])
async def test_each_youtube_failure_is_its_own_clear_state_and_stores_nothing(
    client: httpx.AsyncClient, youtube: FakeYoutube, fault: str, status: int, words: str,
) -> None:
    if fault == "not_found":
        youtube.title = None
    youtube.threads = {
        "comments_disabled": lambda r: error(403, "commentsDisabled"), "not_found": None, "quota": lambda r: error(403, "quotaExceeded"),
        "key": lambda r: error(400, "badRequest", "API_KEY_INVALID"), "network": lambda r: httpx.ConnectError("down"),
        "timeout": lambda r: httpx.ReadTimeout("slow"), "garbage": lambda r: httpx.Response(200, json=[1, 2]),
    }[fault]
    _, base = await live_campaign(client)
    response = await attach(client, base)
    assert response.status_code == status, response.text
    error_body = response.json()["error"]
    assert words in error_body["message"]
    assert KEY not in response.text and "must not repeat" not in response.text, "neither the key nor Google's own text is echoed"
    if fault == "not_found":
        assert error_body["code"] == "VALIDATION_ERROR" and error_body["details"][0]["field"] == "video"
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.PulseComment)) == 0
        assert await s.scalar(select(func.count()).select_from(m.YoutubeSource)) == 0
    assert (await client.get(f"{base}/status")).json()["loaded"] is False


async def test_a_quota_that_runs_out_on_a_later_page_stores_nothing_from_that_fetch(client: httpx.AsyncClient, youtube: FakeYoutube) -> None:
    pages = [[comment(1)], [comment(2)]]
    youtube.pages = pages

    def threads(request: httpx.Request) -> httpx.Response | Exception:
        if request.url.params.get("pageToken"):
            return error(403, "quotaExceeded")
        return httpx.Response(200, json={"items": pages[0], "nextPageToken": "p2"})

    youtube.threads = threads
    _, base = await live_campaign(client)
    assert (await attach(client, base)).status_code == 429
    assert (await client.get(f"{base}/status")).json()["loaded"] is False


async def test_the_request_is_validated_before_anything_is_sent(client: httpx.AsyncClient, youtube: FakeYoutube) -> None:
    _, base = await live_campaign(client)
    cases = [
        (dict(video="https://example.com/watch?v=" + VIDEO), "video"), (dict(video="not a video"), "video"),
        (dict(version="Not a version"), "version_label"), (dict(region="IN-ZZ"), "region_code"),
    ]
    for kwargs, field in cases:
        response = await attach(client, base, **kwargs)
        assert response.status_code == 422 and response.json()["error"]["details"][0]["field"] == field, kwargs
    assert (await client.post(f"{base}/youtube", json={"video": VIDEO, "version_label": "Campaign video", "region_code": "tamil"})).status_code == 422
    assert (await client.post(f"{base}/youtube", json={"video": VIDEO, "version_label": "Campaign video", "region_code": "IN-TN", "order": "random"})).status_code == 422
    assert youtube.requests == [], "nothing reached YouTube"


async def test_a_server_with_no_key_says_so(client: httpx.AsyncClient) -> None:
    _, base = await live_campaign(client)
    response = await attach(client, base)
    assert response.status_code == 503 and response.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"
    assert "not set up" in response.json()["error"]["message"]


async def test_a_demo_project_never_calls_youtube(client: httpx.AsyncClient, youtube: FakeYoutube) -> None:
    _, base = await demo_campaign(client)
    response = await attach(client, base)
    assert response.status_code == 409 and "never call YouTube" in response.json()["error"]["message"]
    assert youtube.requests == []
    await client.post(f"{base}/sample")
    assert (await client.post(f"{base}/read")).status_code == 200
    status = (await client.get(f"{base}/status")).json()
    assert status["source_kind"] == "sample" and status["youtube"] is None and youtube.requests == []


# --- quota safety -----------------------------------------------------------------------------------------------------------


async def test_one_video_is_not_fetched_again_before_the_interval_in_any_campaign(client: httpx.AsyncClient, youtube: FakeYoutube, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_MIN_FETCH_INTERVAL_SECONDS", "900")
    get_settings.cache_clear()
    base, first = await fetched(client, youtube)
    assert first["source"]["next_fetch_at"] is not None
    sent = len(youtube.requests)
    again = await attach(client, base)
    assert again.status_code == 429 and "can be fetched again after" in again.json()["error"]["message"]
    _, elsewhere = await live_campaign(client)
    assert (await attach(client, elsewhere)).status_code == 429, "the quota is the app's: the interval counts every campaign"
    assert len(youtube.requests) == sent, "a refused fetch spends no quota"
    other = await attach(client, elsewhere, video=OTHER_VIDEO)
    assert other.status_code == 200, "another video is not held back"
    shown = (await client.get(f"{base}/status")).json()["youtube"]["sources"][0]
    assert shown["next_fetch_at"] is not None and shown["video_id"] == VIDEO


# --- access ---------------------------------------------------------------------------------------------------------------------


async def test_another_workspace_gets_404_and_a_viewer_reads_but_cannot_fetch(client: httpx.AsyncClient, youtube: FakeYoutube, client_for: Any) -> None:
    base, result = await fetched(client, youtube)
    source_id = result["source"]["id"]
    stranger = client_for(BOB)
    assert (await attach(stranger, base)).status_code == 404
    assert (await stranger.delete(f"{base}/youtube/{source_id}")).status_code == 404
    project = (await client.get(f"{API}/projects")).json()["items"][0]
    workspace = UUID(project["workspace_id"]) if project.get("workspace_id") else await workspace_of("alice")
    await add_member(workspace, "viewer-vic", "viewer")
    viewer = client_for({"Authorization": "Bearer dev-viewer-vic"})
    assert (await viewer.get(f"{base}/summary")).status_code == 200
    assert (await viewer.get(f"{base}/status")).json()["youtube"]["sources"][0]["id"] == source_id
    assert (await attach(viewer, base, video=OTHER_VIDEO, region="IN-KL")).status_code == 403
    assert (await viewer.delete(f"{base}/youtube/{source_id}")).status_code == 403
    assert (await client.delete(f"{base}/youtube/{UUID(int=5)}")).status_code == 404
    assert (await client.get(f"{base}/status")).json()["comment_count"] == 3


# --- the key -----------------------------------------------------------------------------------------------------------------


async def test_the_key_reaches_no_response_log_or_audit_record(client: httpx.AsyncClient, youtube: FakeYoutube, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    base, _ = await fetched(client, youtube)
    youtube.threads = lambda r: error(403, "quotaExceeded")
    await attach(client, base, video=OTHER_VIDEO, region="IN-KL")
    youtube.threads = lambda r: httpx.ConnectError(f"cannot reach {r.url}")
    await attach(client, base, video="bbbbbbbbbbb", region="IN-WB")
    assert KEY not in caplog.text, "no log record carries the key"
    async with read_session() as s:
        details = json.dumps([a.detail for a in await s.scalars(select(m.AuditLog))], default=str)
    assert KEY not in details


def test_the_json_log_formatter_redacts_the_key(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    get_settings.cache_clear()
    level = logging.getLogger().level
    try:
        configure_logging(get_settings())
        logging.getLogger("youtube-test").warning("GET https://www.googleapis.com/youtube/v3/videos?key=%s", KEY)
        out = capsys.readouterr().out
        assert "[REDACTED]" in out and KEY not in out
    finally:
        get_settings.cache_clear()
        logging.getLogger().handlers = [h for h in logging.getLogger().handlers if not getattr(h, "_nativeproof", False)]
        logging.getLogger().setLevel(level)
