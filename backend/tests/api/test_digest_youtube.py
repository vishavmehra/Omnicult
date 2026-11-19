"""The Weekly Digest reads the same comments Comment Pulse shows: a live campaign's YouTube comments, otherwise the sample.

Fakes and stored rows only: a fake YouTube API, a scripted reading, a fake scheduler verifier. No network, no real model.
"""

from datetime import datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.db import models as m
from app.db.session import read_session
from app.schemas import digest as dv
from app.services.comment_pulse import flags_of
from tests.api.omnicult_support import API, client_for  # noqa: F401
from tests.api.test_comment_youtube import FESTIVAL, TITLE, attach, comment, label_all, scripted_youtube, youtube  # noqa: F401
from tests.api.test_crud import make_campaign, make_project
from tests.api.test_digest import WEEK_OF, clock, generate, prepared  # noqa: F401
from tests.api.test_digest_scheduler import GOOD, TOKEN, URL, FakeVerifier, configured, use  # noqa: F401
from tests.api.youtube_support import OTHER_VIDEO, FakeYoutube

# Week 2026-W46 runs Monday 9 to Sunday 15 November, India Standard Time (UTC+5:30).
IN_WEEK_EARLY = comment(1, text="Lovely film, the song is beautiful", likes=5, published="2026-11-08T19:00:00Z")  # Mon 00:30 IST
IN_WEEK_LATE = comment(2, text="मला हा खूप आवडला", likes=2, published="2026-11-15T17:00:00Z")  # Sun 22:30 IST
IN_WEEK_FESTIVAL = comment(3, text=FESTIVAL, likes=1, published="2026-11-11T20:15:00Z")
BEFORE = comment(4, text="Posted the week before", likes=9, published="2026-11-04T09:30:00Z")
AFTER = comment(5, text="Posted after the week ended", likes=7, published="2026-11-15T19:00:00Z")  # Mon 00:30 IST, 16 November
PAGES = [[IN_WEEK_EARLY, IN_WEEK_LATE, IN_WEEK_FESTIVAL, BEFORE, AFTER]]
COMMENT_SOURCE_START = "Source: sample comments"


async def live_with_youtube(client: httpx.AsyncClient, fake: FakeYoutube, pages: list[list[dict[str, Any]]] = PAGES, **kw: Any) -> tuple[str, str]:
    """A live campaign (nothing else loaded) with a video attached. Returns (campaign id, the comments base path)."""
    fake.pages = pages
    project = await make_project(client)
    cid = (await make_campaign(client, project["id"]))["id"]
    base = f"{API}/campaigns/{cid}/pulse/comments"
    done = await attach(client, base, **kw)
    assert done.status_code == 200, done.text
    return cid, base


async def read_all(client: httpx.AsyncClient, base: str, monkeypatch: pytest.MonkeyPatch) -> None:
    scripted_youtube(label_all, monkeypatch)
    assert (await client.post(f"{base}/read")).status_code == 200


# --- a live campaign with stored YouTube comments ---------------------------------------------------------------------


async def test_a_live_campaigns_digest_counts_its_youtube_comments_in_the_week_and_names_the_source(
    client: httpx.AsyncClient, youtube: FakeYoutube, clock: datetime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cid, base = await live_with_youtube(client, youtube)
    await read_all(client, base, monkeypatch)
    line = (await client.get(f"{base}/status")).json()["source_line"]
    section = (await generate(client, cid))["digest"]["content"]["comments"]
    assert section["available"] is True and section["source_kind"] == "youtube" and section["video_titles"] == [TITLE]
    assert section["source"] == line and TITLE.split(" |")[0] in line, "the digest carries the line Comment Pulse shows"
    assert section["comments_total"] == 5 and section["comments_in_window"] == 3, "the two outside the IST week are not counted"
    assert (section["window_from"], section["window_to"]) == ("2026-11-09", "2026-11-15")
    assert section["sentiment"] == {"positive": 3, "neutral": 0, "negative": 0, "mixed": 0, "unread": 0}, "the stored reading, nothing invented"
    kinds = [{f.kind for f in flags_of(c["snippet"]["topLevelComment"]["snippet"]["textDisplay"])} for c in PAGES[0][:3]]
    assert section["cultural_mentions_in_window"] == sum("cultural_misstep" in k for k in kinds) == 1
    assert [f["text"] for f in section["flagged"]] == [FESTIVAL]
    assert not any(t["quote"] and t["quote"]["text"] in {"Posted the week before", "Posted after the week ended"} for t in section["themes"])


async def test_without_a_reading_the_youtube_digest_counts_the_comments_but_shows_no_sentiment(
    client: httpx.AsyncClient, youtube: FakeYoutube, clock: datetime,
) -> None:
    cid, _ = await live_with_youtube(client, youtube)
    section = (await generate(client, cid))["digest"]["content"]["comments"]
    assert section["comments_in_window"] == 3 and section["sentiment"] is None and section["themes"] == []


async def test_a_week_with_no_youtube_comments_in_it_says_zero_not_the_total(
    client: httpx.AsyncClient, youtube: FakeYoutube, clock: datetime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cid, base = await live_with_youtube(client, youtube, [[BEFORE, AFTER]])
    await read_all(client, base, monkeypatch)
    section = (await generate(client, cid))["digest"]["content"]["comments"]
    assert section["source_kind"] == "youtube" and section["comments_total"] == 2 and section["comments_in_window"] == 0
    assert section["sentiment"] == {"positive": 0, "neutral": 0, "negative": 0, "mixed": 0, "unread": 0} and section["flagged"] == []


# --- sample comments, as before -----------------------------------------------------------------------------------


async def test_a_campaign_with_only_sample_comments_keeps_the_sample_and_its_pulse_window(
    client: httpx.AsyncClient, youtube: FakeYoutube, clock: datetime,
) -> None:
    cid = await prepared(client, demo=False, read=False)
    section = (await generate(client, cid))["digest"]["content"]["comments"]
    assert section["source_kind"] == "sample" and section["video_titles"] == [] and section["source"].startswith(COMMENT_SOURCE_START)
    assert section["comments_total"] == 88 and (section["window_from"], section["window_to"]) == ("2026-11-08", "2026-11-14")
    assert youtube.requests == [], "no YouTube request was made"


async def test_a_demo_project_keeps_the_sample_and_touches_no_network(client: httpx.AsyncClient, youtube: FakeYoutube, clock: datetime) -> None:
    cid = await prepared(client, demo=True)
    section = (await generate(client, cid))["digest"]["content"]["comments"]
    assert section["source_kind"] == "sample" and section["video_titles"] == [] and section["comments_in_window"] > 0
    assert youtube.requests == []


async def test_a_digest_stored_before_the_source_was_named_still_opens() -> None:
    old = {
        "available": True, "reason": None, "source": "Source: sample comments", "window_from": None, "window_to": None,
        "comments_total": 1, "comments_in_window": 0, "claim_mentions_in_window": 0, "cultural_mentions_in_window": 0,
        "sentiment": None, "themes": [], "flagged": []}
    parsed = dv.DigestComments.model_validate(old)
    assert parsed.source_kind == "sample" and parsed.video_titles == []


# --- regenerating after YouTube comments arrive -----------------------------------------------------------------------------


async def test_regenerating_after_youtube_comments_arrive_changes_the_comments_section_and_the_source_line(
    client: httpx.AsyncClient, youtube: FakeYoutube, clock: datetime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cid = await prepared(client, demo=False, read=False)
    base = f"{API}/campaigns/{cid}/pulse/comments"
    first = (await generate(client, cid))["digest"]
    before = first["content"]["comments"]
    assert first["revision"] == 1 and before["source_kind"] == "sample"

    youtube.pages = PAGES
    assert (await attach(client, base)).status_code == 200
    await read_all(client, base, monkeypatch)
    same = await generate(client, cid)
    assert same["created"] is False and same["digest"]["revision"] == 1 and same["digest"]["content"]["comments"] == before, "asking again returns the stored week"

    again = await generate(client, cid, regenerate=True)
    after = again["digest"]["content"]["comments"]
    assert again["created"] is True and again["digest"]["revision"] == 2 and again["digest"]["id"] == first["id"]
    assert after["source_kind"] == "youtube" and after["video_titles"] == [TITLE] and after["source"] != before["source"]
    assert (after["comments_total"], after["comments_in_window"]) == (5, 3) and before["comments_total"] == 88
    assert after["sentiment"] is not None and again["digest"]["content_sha256"] != first["content_sha256"]
    listing = (await client.get(f"{API}/campaigns/{cid}/pulse/digests")).json()["items"]
    assert [i["revision"] for i in listing] == [2], "one digest per week"


# --- the scheduled job ------------------------------------------------------------------------------------------------------


async def test_the_scheduled_job_reads_youtube_comments_for_live_campaigns(
    app: FastAPI, client: httpx.AsyncClient, client_for: Any, configured: None, youtube: FakeYoutube, monkeypatch: pytest.MonkeyPatch,
) -> None:
    use(app, FakeVerifier(GOOD))
    sched = client_for({})
    full, base = await live_with_youtube(client, youtube)
    await read_all(client, base, monkeypatch)
    stale, _ = await live_with_youtube(client, youtube, [[BEFORE, AFTER]], video=OTHER_VIDEO)  # comments, none in the week

    async with read_session() as s:
        usage = await s.scalar(select(func.count()).select_from(m.AiUsageEvent))
    run = await sched.post(URL, headers=TOKEN)
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["week"]["label"] == "2026-W46"
    assert (body["campaigns"], body["generated"], body["skipped_no_data"], body["failed"]) == (2, 1, 1, 0)
    (item,) = (await client.get(f"{API}/campaigns/{full}/pulse/digests")).json()["items"]
    assert item["trigger"] == "scheduler"
    digest = (await client.get(f"{API}/campaigns/{full}/pulse/digests/{item['id']}")).json()
    section = digest["content"]["comments"]
    assert section["source_kind"] == "youtube" and section["video_titles"] == [TITLE] and section["comments_in_window"] == 3
    assert (await client.get(f"{API}/campaigns/{stale}/pulse/digests")).json()["items"] == [], "nothing posted that week: no digest"
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.AiUsageEvent)) == usage, "the scheduled run calls no model"

    again = (await sched.post(URL, headers=TOKEN)).json()
    assert (again["generated"], again["already_existed"]) == (0, 1), "safe to repeat"
    assert (await client.get(f"{API}/campaigns/{full}/pulse/digests/{item['id']}")).json() == digest
