"""YouTube Data API client: video ids, paging, the failure states and what is sent. No network (httpx MockTransport)."""

import httpx
import pytest

from app.integrations.youtube import PAGE_SIZE, YoutubeClient, YoutubeError, parse_video_id
from tests.api.youtube_support import KEY, OTHER_VIDEO, VIDEO, FakeYoutube, comment, error

# --- the video the user pastes -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [
    VIDEO, f"  {VIDEO}  ", f"https://www.youtube.com/watch?v={VIDEO}", f"https://youtube.com/watch?v={VIDEO}&t=42s&list=PL1",
    f"youtube.com/watch?v={VIDEO}", f"https://m.youtube.com/watch?v={VIDEO}", f"https://youtu.be/{VIDEO}?si=abc",
    f"https://www.youtube.com/shorts/{VIDEO}", f"https://www.youtube.com/embed/{VIDEO}", f"https://www.youtube.com/live/{VIDEO}",
    f"https://music.youtube.com/watch?v={VIDEO}",
])
def test_a_video_link_or_id_resolves_to_the_eleven_character_id(raw: str) -> None:
    assert parse_video_id(raw) == VIDEO


@pytest.mark.parametrize("raw", [
    "", "short", "not a link at all", f"{VIDEO}x", "https://example.com/watch?v=" + VIDEO, f"https://evil.test/youtu.be/{VIDEO}",
    "https://www.youtube.com/watch", "https://www.youtube.com/watch?v=tooshort", "https://www.youtube.com/channel/UCabcdefghijklmnop",
    f"ftp://youtu.be/{VIDEO}", f"javascript:alert('{VIDEO}')", "https://www.youtube.com/playlist?list=PLabcdefghijk",
])
def test_anything_else_is_not_a_video(raw: str) -> None:
    assert parse_video_id(raw) is None


# --- what is sent -----------------------------------------------------------------------------------------------------


async def test_requests_carry_the_key_in_a_header_never_the_url_and_ask_for_no_author_fields() -> None:
    fake = FakeYoutube([[comment(1)]])
    client = fake.client()
    assert await client.video_title(VIDEO) == "Aamod Festive Tin | Diwali film"
    await client.comments(VIDEO, order="time", max_pages=3)
    for request in fake.requests:
        assert request.headers["X-Goog-Api-Key"] == KEY
        assert KEY not in str(request.url) and "key" not in request.url.params
        assert "author" not in request.url.params.get("fields", "").lower(), "no author field is ever requested"
    thread = fake.calls("commentThreads")[0].url.params
    assert thread["part"] == "snippet" and thread["textFormat"] == "plainText" and thread["maxResults"] == str(PAGE_SIZE) == "100"
    assert thread["order"] == "time" and thread["videoId"] == VIDEO
    assert fake.calls("videos")[0].url.params["id"] == VIDEO


# --- paging ---------------------------------------------------------------------------------------------------------


async def test_comments_are_paged_until_the_last_page_and_keep_only_the_comment() -> None:
    pages = [[comment(1, likes=5, replies=2), comment(2)], [comment(3, text="  third  ")], [comment(4)]]
    fake = FakeYoutube(pages)
    got = await fake.client().comments(VIDEO, order="relevance", max_pages=5)
    assert got.pages == 3 and got.truncated is False and [c.id for c in got.comments] == [f"Ugx000{i}TestCommentId" for i in (1, 2, 3, 4)]
    first = got.comments[0]
    assert (first.likes, first.replies, first.text) == (5, 2, "Comment number 1 about the film")
    assert got.comments[2].text == "third"
    assert not any(hasattr(first, name) for name in ("author", "author_name", "channel", "channel_id", "avatar"))
    assert [r.url.params.get("pageToken") for r in fake.calls("commentThreads")] == [None, "p2", "p3"]


async def test_the_page_cap_stops_the_fetch_and_says_more_existed() -> None:
    fake = FakeYoutube([[comment(i)] for i in range(1, 9)])
    got = await fake.client().comments(VIDEO, order="relevance", max_pages=5)
    assert got.pages == 5 and got.truncated is True and len(got.comments) == 5
    assert len(fake.calls("commentThreads")) == 5, "no request beyond the cap"
    exact = FakeYoutube([[comment(1)], [comment(2)]])
    ended = await exact.client().comments(VIDEO, order="relevance", max_pages=2)
    assert ended.pages == 2 and ended.truncated is False, "a last page inside the cap is not truncated"


async def test_a_comment_repeated_between_pages_and_an_unreadable_item_are_handled() -> None:
    broken = {"id": "x", "snippet": {"topLevelComment": {"snippet": {"textDisplay": "no time"}}}}
    empty = comment(7, text="   ")
    fake = FakeYoutube([[comment(1), broken, empty], [comment(1), comment(2)]])
    got = await fake.client().comments(VIDEO, order="time", max_pages=5)
    assert [c.id for c in got.comments] == ["Ugx0001TestCommentId", "Ugx0002TestCommentId"] and got.skipped == 2


# --- failure states --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("answer", "state"), [
    (error(403, "commentsDisabled"), "comments_disabled"),
    (error(403, "forbidden"), "comments_disabled"),
    (error(404, "videoNotFound"), "video_not_found"),
    (error(403, "quotaExceeded"), "quota_exceeded"),
    (error(403, "dailyLimitExceeded"), "quota_exceeded"),
    (error(400, "badRequest", "API_KEY_INVALID"), "key_rejected"),
    (error(403, "accessNotConfigured"), "key_rejected"),
    (httpx.Response(418, text="teapot"), "unavailable"),
    (httpx.Response(403, text="<html>not json</html>"), "unavailable"),
])
async def test_each_failure_is_its_own_state(answer: httpx.Response, state: str) -> None:
    client = FakeYoutube(threads=lambda r: answer).client()
    with pytest.raises(YoutubeError) as caught:
        await client.comments(VIDEO, order="relevance", max_pages=2)
    assert caught.value.state == state
    assert KEY not in str(caught.value) and "must not repeat" not in str(caught.value)


async def test_a_video_that_is_not_listed_is_not_found() -> None:
    with pytest.raises(YoutubeError) as caught:
        await FakeYoutube(title=None).client().video_title(OTHER_VIDEO)
    assert caught.value.state == "video_not_found"


@pytest.mark.parametrize(("raised", "state"), [
    (httpx.ConnectTimeout("slow"), "timeout"), (httpx.ConnectError("down"), "network"), (httpx.ReadError("cut"), "network"),
])
async def test_timeouts_and_network_errors_are_retried_a_bounded_number_of_times_then_reported(raised: Exception, state: str) -> None:
    fake = FakeYoutube(threads=lambda r: raised)
    with pytest.raises(YoutubeError) as caught:
        await fake.client().comments(VIDEO, order="relevance", max_pages=2)
    assert caught.value.state == state and len(fake.calls("commentThreads")) == 3  # the first try and two retries
    assert KEY not in str(caught.value)


async def test_a_429_is_retried_then_reported_as_the_quota_state_and_a_5xx_that_clears_succeeds() -> None:
    limited = FakeYoutube(threads=lambda r: httpx.Response(429))
    with pytest.raises(YoutubeError) as caught:
        await limited.client().comments(VIDEO, order="relevance", max_pages=1)
    assert caught.value.state == "quota_exceeded" and len(limited.calls("commentThreads")) == 3
    replies = [httpx.Response(503), httpx.Response(200, json={"items": [comment(1)]})]
    flaky = FakeYoutube(threads=lambda r: replies.pop(0))
    assert len((await flaky.client().comments(VIDEO, order="relevance", max_pages=1)).comments) == 1


async def test_a_body_that_is_not_a_json_object_is_unavailable() -> None:
    client = FakeYoutube(threads=lambda r: httpx.Response(200, json=["not", "an", "object"])).client()
    with pytest.raises(YoutubeError) as caught:
        await client.comments(VIDEO, order="relevance", max_pages=1)
    assert caught.value.state == "unavailable"


def test_the_client_is_built_without_touching_the_network() -> None:
    assert isinstance(YoutubeClient(KEY), YoutubeClient)
