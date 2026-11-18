"""Bounded HTTP for the live adapters: descriptive User-Agent, per-request timeout, capped retries, typed errors.

Retries only what can succeed later (timeouts, connection errors, 429, 5xx) with exponential backoff, honouring a
Retry-After header up to a cap. A 429 whose Retry-After is longer than we are willing to wait is not retried: the host
is put on a cool-down (per host, so the SPARQL endpoint cannot block the entity API) and later calls fail fast without
touching the network until it ends. Everything else raises immediately. Tests inject an httpx.AsyncClient with a
MockTransport and a zero backoff, so no test touches the network.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.integrations.culture.base import (
    CultureSourceError,
    SourceAuthError,
    SourceHttpError,
    SourceNetworkError,
    SourceRateLimited,
    SourceTimeout,
    SourceValidationError,
)

MAX_RETRY_AFTER_SECONDS = 10.0
MAX_COOLDOWN_SECONDS = 1800.0
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class HttpFetcher:
    def __init__(
        self, source: str, *, user_agent: str, timeout: float = 15.0, max_retries: int = 2, backoff_seconds: float = 0.5,
        client: httpx.AsyncClient | None = None, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_concurrent: int = 2, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source, self.user_agent, self.timeout = source, user_agent, timeout
        self.max_retries, self.backoff, self._client, self._sleep = max_retries, backoff_seconds, client, sleep
        self._slots = asyncio.Semaphore(max_concurrent)  # Wikimedia asks clients to stay serial or near it
        self._clock, self._cooldowns = clock, {}  # host -> monotonic time before which we do not ask again
        self.requests_made = 0  # attempts, including retries; tests and the smoke script read it

    async def get_json(self, url: str, params: dict[str, Any] | None = None, *, operation: str,
                       headers: dict[str, str] | None = None, timeout: float | None = None) -> Any:
        timeout = timeout or self.timeout
        headers = {"User-Agent": self.user_agent, "Accept": "application/json", **(headers or {})}
        host = httpx.URL(url).host
        remaining = self._cooldowns.get(host, 0.0) - self._clock()
        if remaining > 0:
            raise SourceRateLimited(self.source, operation, f"{host} asked us to wait; {remaining:.0f}s of cool-down left", status_code=429)
        last: CultureSourceError | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                await self._sleep(self._delay(attempt, last))
            self.requests_made += 1
            try:
                async with self._slots:
                    response = await self._send(url, params, headers, timeout)
            except httpx.TimeoutException:
                last = SourceTimeout(self.source, operation, f"timed out after {timeout:g}s")
                continue
            except httpx.TransportError as exc:
                last = SourceNetworkError(self.source, operation, f"network error ({type(exc).__name__})")
                continue
            if response.status_code in RETRY_STATUS:
                cls = SourceRateLimited if response.status_code == 429 else SourceHttpError
                hint = _retry_after(response)
                suffix = f" (server asks to retry after {hint:g}s)" if hint is not None else ""
                last = cls(self.source, operation, f"HTTP {response.status_code}{suffix}", status_code=response.status_code)
                last.retry_after = hint  # type: ignore[attr-defined]
                if response.status_code == 429 and hint is not None:
                    self._cooldowns[host] = self._clock() + min(hint, MAX_COOLDOWN_SECONDS)
                    if hint > MAX_RETRY_AFTER_SECONDS:
                        raise last  # waiting that long inside one request is not bounded; the caller sees a typed error
                continue
            if response.status_code in (401, 403):
                raise _with_payload(SourceAuthError(self.source, operation, f"HTTP {response.status_code}", status_code=response.status_code), response)
            if response.status_code >= 400:
                raise _with_payload(SourceHttpError(self.source, operation, f"HTTP {response.status_code}", status_code=response.status_code), response)
            try:
                return response.json()
            except ValueError as exc:
                raise SourceValidationError(self.source, operation, "response body is not JSON") from exc
        assert last is not None
        raise last

    async def _send(self, url: str, params: dict[str, Any] | None, headers: dict[str, str], timeout: float) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url, params=params, headers=headers, timeout=timeout)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            return await client.get(url, params=params, headers=headers)

    def _delay(self, attempt: int, last: CultureSourceError | None) -> float:
        hinted = getattr(last, "retry_after", None)
        if hinted is not None:
            return min(hinted, MAX_RETRY_AFTER_SECONDS)
        return self.backoff * (2 ** (attempt - 1))


def _with_payload(error: CultureSourceError, response: httpx.Response) -> CultureSourceError:
    """Keep the provider's error body (for example Google's `error.errors[].reason`) for callers that tell failures apart."""
    try:
        error.payload = response.json()
    except ValueError:
        error.payload = None
    return error


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    return float(value) if value.isdigit() else None
