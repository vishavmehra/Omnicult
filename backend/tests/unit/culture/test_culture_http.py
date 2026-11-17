"""HttpFetcher: bounded retries, Retry-After, typed errors. No network (httpx MockTransport)."""

import httpx
import pytest

from app.integrations.culture.base import (
    SourceAuthError,
    SourceHttpError,
    SourceNetworkError,
    SourceRateLimited,
    SourceTimeout,
    SourceValidationError,
)
from app.integrations.culture.http import HttpFetcher
from tests.unit.culture.culture_helpers import UA, no_sleep, scripted_client


def fetcher(client: httpx.AsyncClient, sleeps: list[float], **kw) -> HttpFetcher:
    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    return HttpFetcher("t", user_agent=UA, timeout=3, client=client, sleep=record, backoff_seconds=0.5, **kw)


async def test_retries_a_5xx_then_succeeds_and_sends_the_user_agent():
    seen: list[httpx.Request] = []
    sleeps: list[float] = []
    client = scripted_client([httpx.Response(503), httpx.Response(200, json={"ok": True})], seen)
    f = fetcher(client, sleeps)
    assert await f.get_json("https://example.test/x", {"a": "1"}, operation="op") == {"ok": True}
    assert f.requests_made == 2 and sleeps == [0.5]
    assert seen[0].headers["User-Agent"] == UA and seen[0].url.params["a"] == "1"


async def test_gives_up_after_the_bounded_retries_with_a_typed_error():
    sleeps: list[float] = []
    f = fetcher(scripted_client([httpx.ConnectTimeout("slow")] * 3), sleeps, max_retries=2)
    with pytest.raises(SourceTimeout) as err:
        await f.get_json("https://example.test/x", operation="op")
    assert f.requests_made == 3 and sleeps == [0.5, 1.0]  # exponential, bounded
    assert err.value.retryable and err.value.kind == "timeout"


async def test_connection_errors_are_network_errors():
    f = fetcher(scripted_client([httpx.ConnectError("down")] * 3), [])
    with pytest.raises(SourceNetworkError):
        await f.get_json("https://example.test/x", operation="op")


async def test_a_short_retry_after_is_honoured_then_the_request_succeeds():
    sleeps: list[float] = []
    f = fetcher(scripted_client([httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(200, json={"ok": 1})]), sleeps)
    assert await f.get_json("https://example.test/x", operation="op") == {"ok": 1} and sleeps == [3.0]


async def test_a_long_retry_after_is_not_retried_and_puts_only_that_host_on_cooldown():
    now = [1000.0]
    f = HttpFetcher("t", user_agent=UA, timeout=3, sleep=no_sleep, clock=lambda: now[0],
                    client=scripted_client([httpx.Response(429, headers={"Retry-After": "1000"}), httpx.Response(200, json={"ok": 1}),
                                            httpx.Response(200, json={"ok": 2})]))
    with pytest.raises(SourceRateLimited) as err:
        await f.get_json("https://sparql.example.test/q", operation="op")
    assert f.requests_made == 1 and "retry after 1000s" in str(err.value) and err.value.retryable
    with pytest.raises(SourceRateLimited, match="cool-down"):  # fails fast: no second request while the host asked us to wait
        await f.get_json("https://sparql.example.test/q", operation="op")
    assert f.requests_made == 1
    assert await f.get_json("https://api.example.test/x", operation="op") == {"ok": 1}  # another host is unaffected
    now[0] += 1001
    assert await f.get_json("https://sparql.example.test/q", operation="op") == {"ok": 2}  # cool-down over


async def test_the_cooldown_is_capped():
    now = [0.0]
    f = HttpFetcher("t", user_agent=UA, timeout=3, sleep=no_sleep, clock=lambda: now[0],
                    client=scripted_client([httpx.Response(429, headers={"Retry-After": "999999"})]))
    with pytest.raises(SourceRateLimited):
        await f.get_json("https://example.test/x", operation="op")
    assert f._cooldowns["example.test"] == 1800.0


@pytest.mark.parametrize(("status", "error"), [(404, SourceHttpError), (400, SourceHttpError), (401, SourceAuthError), (403, SourceAuthError)])
async def test_client_errors_are_not_retried(status, error):
    f = fetcher(scripted_client([httpx.Response(status)]), [])
    with pytest.raises(error) as err:
        await f.get_json("https://example.test/x", operation="op")
    assert f.requests_made == 1 and err.value.status_code == status and not err.value.retryable


async def test_a_non_json_body_is_a_validation_error():
    f = fetcher(scripted_client([httpx.Response(200, text="<html>not json</html>")]), [])
    with pytest.raises(SourceValidationError):
        await f.get_json("https://example.test/x", operation="op")
