"""CultureService: fan out to the configured adapters, log every call, cache successful responses only.

Provider problems never raise: a failing adapter is logged (status "error", typed error) and the others still answer,
so the caller sees partial results plus the call log. Errors are never cached; an empty successful result is.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any, Literal, Protocol, TypeVar

from pydantic import TypeAdapter, ValidationError

from app.integrations.culture.base import (
    CallLogRecord,
    CultureSource,
    CultureSourceError,
    EntityCandidate,
    EntityResolution,
    Operation,
    TrendSeries,
    decide_resolution,
    now_utc,
    request_hash,
)
from app.schemas.claims import ClaimDraft

logger = logging.getLogger(__name__)
T = TypeVar("T")

# Used when an adapter's descriptor has no cache_policy entry for the operation. Static datasets change rarely;
# live feeds move faster. Both are bounded so a stale answer expires.
DEFAULT_TTL: dict[str, timedelta] = {
    "resolve_entity": timedelta(days=7),
    "related_signals": timedelta(hours=24),
    "audience_facts": timedelta(days=30),
    "trend_series": timedelta(hours=12),
    "moments": timedelta(days=7),
}
CACHE_VERSION = "1"  # bump when a result model changes shape so old entries are never replayed


class CacheStore(Protocol):
    async def get(self, key: str) -> Any | None: ...

    async def put(self, key: str, value: Any, *, ttl: timedelta) -> None: ...


class InMemoryCacheStore:
    """Process-local store with expiry. A database-backed store implements the same two methods."""

    def __init__(self, *, clock: Callable[[], datetime] = now_utc) -> None:
        self._clock = clock
        self.entries: dict[str, tuple[datetime, Any]] = {}

    async def get(self, key: str) -> Any | None:
        hit = self.entries.get(key)
        if hit is None:
            return None
        if hit[0] <= self._clock():
            del self.entries[key]  # expired entries are never served
            return None
        return hit[1]

    async def put(self, key: str, value: Any, *, ttl: timedelta) -> None:
        self.entries[key] = (self._clock() + ttl, value)


_CLAIMS = TypeAdapter(list[ClaimDraft])
_SERIES = TypeAdapter(list[TrendSeries])


class CultureService:
    def __init__(self, sources: list[CultureSource], *, cache: CacheStore | None = None,
                 mode: Literal["live", "fixture"] = "live") -> None:
        self.sources = sources
        self.cache = cache
        self.mode = mode
        self.call_log: list[CallLogRecord] = []

    # ---- introspection ----

    def is_configured(self) -> bool:
        """At least one adapter is usable."""
        return any(s.is_configured() for s in self.sources)

    def skipped_sources(self) -> list[str]:
        return [s.name for s in self.sources if not s.is_configured()]

    def _active(self, operation: Operation) -> list[CultureSource]:
        return [s for s in self.sources if s.is_configured() and operation in s.descriptor.supported_operations]

    # ---- operations ----

    async def resolve_entity(self, query: str, *, language: str | None = None, region_code: str | None = None,
                             log: list[CallLogRecord] | None = None) -> EntityResolution:
        """One merged resolution: candidates from every source, resolved only if exactly one matches exactly."""
        request = {"query": query, "language": language, "region_code": region_code}

        async def one(source: CultureSource) -> list[EntityCandidate]:
            result = await self._run(
                source, "resolve_entity", request,
                lambda: source.resolve_entity(query, language=language, region_code=region_code),
                dump=lambda r: r.model_dump(mode="json"), parse=EntityResolution.model_validate,
                count=lambda r: len(r.candidates), log=log)
            return result.candidates if result else []

        sources = self._active("resolve_entity")
        merged: dict[str, EntityCandidate] = {}
        for candidates in await asyncio.gather(*(one(s) for s in sources)):
            for c in candidates:
                merged.setdefault(f"{c.source}:{c.entity_id}", c)
        return decide_resolution(query, list(merged.values()), language=language, region_code=region_code,
                                 sources=[s.name for s in sources], retrieved_at=now_utc())

    async def related_signals(self, entity_id: str, *, region_code: str, limit: int = 10,
                              log: list[CallLogRecord] | None = None) -> list[ClaimDraft]:
        request = {"entity_id": entity_id, "region_code": region_code, "limit": limit}
        return await self._claims("related_signals", request, lambda s: s.related_signals(
            entity_id, region_code=region_code, limit=limit), log)

    async def audience_facts(self, region_code: str, *, log: list[CallLogRecord] | None = None) -> list[ClaimDraft]:
        return await self._claims("audience_facts", {"region_code": region_code},
                                  lambda s: s.audience_facts(region_code), log)

    async def moments(self, region_code: str, *, year: int, log: list[CallLogRecord] | None = None) -> list[ClaimDraft]:
        return await self._claims("moments", {"region_code": region_code, "year": year},
                                  lambda s: s.moments(region_code, year=year), log)

    async def trend_series(self, term: str, *, region_code: str, start: date, end: date,
                           log: list[CallLogRecord] | None = None) -> list[TrendSeries]:
        request = {"term": term, "region_code": region_code, "start": start.isoformat(), "end": end.isoformat()}

        async def one(source: CultureSource) -> list[TrendSeries]:
            result = await self._run(
                source, "trend_series", request,
                lambda: _wrap(source.trend_series(term, region_code=region_code, start=start, end=end)),
                dump=lambda r: _SERIES.dump_python(r, mode="json"), parse=_SERIES.validate_python,
                count=len, log=log)
            return result or []

        out: list[TrendSeries] = []
        for series in await asyncio.gather(*(one(s) for s in self._active("trend_series"))):
            out.extend(series)
        return out

    # ---- internals ----

    async def _claims(self, operation: Operation, request: dict[str, Any],
                      call: Callable[[CultureSource], Awaitable[list[ClaimDraft]]],
                      log: list[CallLogRecord] | None) -> list[ClaimDraft]:
        async def one(source: CultureSource) -> list[ClaimDraft]:
            result = await self._run(source, operation, request, lambda: call(source),
                                     dump=lambda r: _CLAIMS.dump_python(r, mode="json"),
                                     parse=_CLAIMS.validate_python, count=len, log=log)
            return result or []

        out: list[ClaimDraft] = []
        for claims in await asyncio.gather(*(one(s) for s in self._active(operation))):
            out.extend(claims)
        return out

    async def _run(self, source: CultureSource, operation: str, request: dict[str, Any],
                   call: Callable[[], Awaitable[T]], *, dump: Callable[[T], Any], parse: Callable[[Any], T],
                   count: Callable[[T], int], log: list[CallLogRecord] | None) -> T | None:
        digest = request_hash(source.name, operation, request)
        key = f"{CACHE_VERSION}:{digest}"
        started = time.perf_counter()

        def record(status: Literal["ok", "empty", "error"], *, cached: bool = False, n: int = 0,
                   error: CultureSourceError | Exception | None = None) -> None:
            entry = CallLogRecord(
                source=source.name, operation=operation, request_hash=digest, retrieved_at=now_utc(), status=status,
                cached=cached, result_count=n, duration_ms=int((time.perf_counter() - started) * 1000),
                error_type=getattr(error, "kind", type(error).__name__) if error else None,
                error=str(error)[:300] if error else None)
            self.call_log.append(entry)
            if log is not None:
                log.append(entry)

        if self.cache is not None:
            try:
                hit = await self.cache.get(key)
                result = parse(hit) if hit is not None else None
            except (ValidationError, ValueError, KeyError, TypeError):
                result = None  # a cache problem never fails a lookup
            if result is not None:
                n = count(result)
                record("ok" if n else "empty", cached=True, n=n)
                return result
        try:
            result = await call()
        except CultureSourceError as exc:
            record("error", error=exc)  # errors are logged, never cached
            return None
        except ValidationError as exc:
            record("error", error=exc)
            return None
        except Exception as exc:  # an adapter bug must not take the other sources down; it is still logged loudly
            logger.exception("culture source %s.%s failed unexpectedly", source.name, operation)
            record("error", error=exc)
            return None
        n = count(result)
        record("ok" if n else "empty", n=n)
        if self.cache is not None:
            ttl = source.descriptor.cache_policy.get(operation, DEFAULT_TTL[operation])
            try:
                await self.cache.put(key, dump(result), ttl=ttl)
            except Exception:  # noqa: BLE001 - cache failures are logged, not raised
                logger.warning("culture cache write failed for %s.%s", source.name, operation)
        return result


async def _wrap(awaitable: Awaitable[TrendSeries | None]) -> list[TrendSeries]:
    series = await awaitable
    return [series] if series is not None else []
