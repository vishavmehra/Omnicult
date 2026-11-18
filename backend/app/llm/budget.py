"""Usage metering and cost ceilings for every model call (MASTER_PROMPT 7.4).

`Meter.call(...)` wraps one provider request: it reserves the estimated cost against the per-run and per-day budgets
(raising `BudgetExceeded` before anything is sent), then records a `UsageEvent` with the real token counts and an
estimated cost. Events go to a `UsageSink`; the in-memory default keeps them for the process lifetime and the lead replaces
it with a database sink at startup via `set_default_usage_sink`. Costs are estimates from the price table in
`registry.py`, never billed amounts.
"""

import asyncio
import contextvars
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal, Protocol
from uuid import UUID

from app.llm.registry import PRICE_TABLE_VERSION, estimate_cost, price_for
from app.schemas.common import Usage

log = logging.getLogger(__name__)

_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("llm_run_id", default=None)


@contextmanager
def run_scope(run_id: str):
    """Attribute every model call made inside the block to `run_id` (per-run budget and usage rows)."""
    token = _run_id.set(run_id)
    try:
        yield
    finally:
        _run_id.reset(token)


def current_run_id() -> str | None:
    return _run_id.get()


@dataclass(frozen=True)
class UsageContext:
    """Who a model call is for, so its usage row can be attributed. Every field is optional: a call made outside any scope
    is still recorded, just unattributed."""

    workspace_id: UUID | None = None
    project_id: UUID | None = None
    campaign_id: UUID | None = None
    user_id: UUID | None = None
    run_id: UUID | None = None  # an agent_runs id; Audience Lab runs keep None (their table is not agent_runs) and the campaign


_usage_context: contextvars.ContextVar[UsageContext | None] = contextvars.ContextVar("llm_usage_context", default=None)


@contextmanager
def usage_scope(context: UsageContext):
    """Attribute every model call made inside the block to `context`; a `run_id` also counts against that run's budget."""
    token = _usage_context.set(context)
    run_token = _run_id.set(str(context.run_id)) if context.run_id else None
    try:
        yield
    finally:
        _usage_context.reset(token)
        if run_token is not None:
            _run_id.reset(run_token)


def current_usage_context() -> UsageContext:
    return _usage_context.get() or UsageContext()


def failure_code(exc: BaseException) -> str:
    """The error code a failed provider attempt is recorded with (the codes LLMError uses). A cancelled call is recorded
    as CANCELLED: the caller gave up (a user cancel or an expired deadline), the provider did not fail."""
    if isinstance(exc, asyncio.CancelledError):
        return "CANCELLED"
    from app.llm.google import map_exception  # lazy: google.py imports the gateway, which imports this module

    error = map_exception(exc)
    return "CONTENT_BLOCKED" if error.blocked else "PROVIDER_TIMEOUT" if error.timeout else "PROVIDER_ERROR"


@dataclass(frozen=True)
class UsageEvent:
    """One model request. The shape `ai_usage_events` will persist."""

    timestamp: datetime
    capability: str
    provider: str
    model: str
    status: Literal["ok", "error"]
    run_id: str | None = None
    stage: str | None = None
    agent: str | None = None
    prompt_version: str | None = None
    error_code: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    images: int = 0
    audio_seconds: float = 0.0
    grounded_requests: int = 0  # Google Search grounded requests; the fee is already inside estimated_cost_usd
    estimated_cost_usd: float | None = None  # a stand-in price when price_known is False, so budgets still hold
    price_known: bool = True
    price_table_version: str | None = None
    latency_ms: int | None = None
    workspace_id: UUID | None = None
    project_id: UUID | None = None
    campaign_id: UUID | None = None
    user_id: UUID | None = None


class UsageSink(Protocol):
    async def record(self, event: UsageEvent) -> None: ...

    async def spent_usd(self, *, run_id: str | None = None, day: date | None = None) -> float:
        """Estimated USD recorded for one run, or for one UTC day when `run_id` is None."""
        ...


class InMemoryUsageSink:
    """Process-lifetime default. ponytail: keeps the newest 50,000 events and sums them linearly; the database sink
    replaces it before that matters."""

    def __init__(self) -> None:
        self.events: deque[UsageEvent] = deque(maxlen=50_000)

    async def record(self, event: UsageEvent) -> None:
        self.events.append(event)

    async def spent_usd(self, *, run_id: str | None = None, day: date | None = None) -> float:
        if run_id is not None:
            return sum(e.estimated_cost_usd or 0.0 for e in self.events if e.run_id == run_id)
        today = day or datetime.now(UTC).date()
        return sum(e.estimated_cost_usd or 0.0 for e in self.events if e.timestamp.date() == today)


_default_sink: UsageSink = InMemoryUsageSink()


def get_default_usage_sink() -> UsageSink:
    return _default_sink


def set_default_usage_sink(sink: UsageSink) -> None:
    """Wire persistence (the lead's database sink) once at startup; gateways created afterwards use it."""
    global _default_sink
    _default_sink = sink


class BudgetExceeded(Exception):
    def __init__(self, scope: Literal["run", "day"], limit: float, spent: float, estimate: float) -> None:
        super().__init__(f"AI {scope} budget of ${limit:.2f} would be exceeded (spent ${spent:.4f}, this call ~${estimate:.4f}).")
        self.scope, self.limit, self.spent, self.estimate = scope, limit, spent, estimate


class BudgetGuard:
    """Refuses a call whose estimate would push a run or the UTC day past its ceiling. In-flight (reserved) estimates
    count, so parallel calls cannot jointly overshoot. A non-positive ceiling disables that check."""

    def __init__(self, sink: UsageSink, *, run_budget_usd: float, daily_budget_usd: float) -> None:
        self.sink, self.run_budget_usd, self.daily_budget_usd = sink, run_budget_usd, daily_budget_usd
        self._reserved_by_run: dict[str | None, float] = {}
        self._reserved_total = 0.0

    async def reserve(self, estimate: float, run_id: str | None) -> None:
        if run_id is not None and self.run_budget_usd > 0:
            spent = await self.sink.spent_usd(run_id=run_id) + self._reserved_by_run.get(run_id, 0.0)
            if spent + estimate > self.run_budget_usd:
                raise BudgetExceeded("run", self.run_budget_usd, spent, estimate)
        if self.daily_budget_usd > 0:
            spent = await self.sink.spent_usd() + self._reserved_total
            if spent + estimate > self.daily_budget_usd:
                raise BudgetExceeded("day", self.daily_budget_usd, spent, estimate)
        self._reserved_by_run[run_id] = self._reserved_by_run.get(run_id, 0.0) + estimate
        self._reserved_total += estimate

    def release(self, estimate: float, run_id: str | None) -> None:
        self._reserved_by_run[run_id] = max(0.0, self._reserved_by_run.get(run_id, 0.0) - estimate)
        self._reserved_total = max(0.0, self._reserved_total - estimate)


@dataclass
class CallRecord:
    """Filled in by the caller inside `Meter.call`; read when the block exits."""

    usage: Usage | None = None
    images: int = 0
    audio_seconds: float = 0.0
    grounded_requests: int = 0
    error_code: str | None = None
    cost_usd: float | None = field(default=None, init=False)


class Meter:
    def __init__(self, sink: UsageSink, guard: BudgetGuard | None = None, provider: str = "google") -> None:
        self.sink, self.guard, self.provider = sink, guard, provider

    @asynccontextmanager
    async def call(
        self, *, capability: str, model: str, estimate_usd: float = 0.0, stage: str | None = None,
        agent: str | None = None, prompt_version: str | None = None,
    ) -> AsyncIterator[CallRecord]:
        """Reserve `estimate_usd`, yield a record, then log the event with the cost computed from what the record holds.
        BudgetExceeded is raised before the body runs; exceptions from the body are recorded as status `error`."""
        run_id = current_run_id()
        if self.guard is not None:
            await self.guard.reserve(estimate_usd, run_id)
        record, started, failed = CallRecord(), time.perf_counter(), False
        try:
            yield record
        except BaseException as exc:
            failed = True
            record.error_code = record.error_code or failure_code(exc)
            raise
        finally:
            if self.guard is not None:
                self.guard.release(estimate_usd, run_id)
            usage = record.usage
            _, known = price_for(model)
            cost = record.cost_usd
            if cost is None and not failed:
                cost = estimate_cost(
                    model, input_tokens=usage.input_tokens if usage else None,
                    output_tokens=usage.output_tokens if usage else None, images=record.images,
                    audio_seconds=record.audio_seconds, grounded_requests=record.grounded_requests,
                ).usd
            where = current_usage_context()
            event = UsageEvent(
                timestamp=datetime.now(UTC), capability=capability, provider=self.provider, model=model,
                status="error" if failed or record.error_code else "ok", run_id=run_id, stage=stage, agent=agent,
                prompt_version=prompt_version, error_code=record.error_code,
                input_tokens=usage.input_tokens if usage else None, output_tokens=usage.output_tokens if usage else None,
                thinking_tokens=usage.thinking_tokens if usage else None, images=record.images,
                audio_seconds=record.audio_seconds, grounded_requests=record.grounded_requests, estimated_cost_usd=cost,
                price_known=known, price_table_version=PRICE_TABLE_VERSION, latency_ms=int((time.perf_counter() - started) * 1000),
                workspace_id=where.workspace_id, project_id=where.project_id, campaign_id=where.campaign_id, user_id=where.user_id,
            )
            try:
                await self.sink.record(event)
            except Exception:  # a metering failure must never fail the call it measured
                log.warning("usage sink failed", extra={"capability": capability, "model": model})



@asynccontextmanager
async def _unmetered() -> AsyncIterator[CallRecord]:
    yield CallRecord()


def metered(meter: Meter | None, **kwargs):
    """`meter.call(**kwargs)`, or a no-op context when an adapter runs without a meter (unit tests, scripts)."""
    return meter.call(**kwargs) if meter is not None else _unmetered()
