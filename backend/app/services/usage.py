"""Usage and Credits (platform feature E): what a workspace's model calls cost, and how near it is to its ceilings.

Both reads, the settings panel's summary (`workspace_usage`) and the full page's report (`usage_report`), come from one
query over `ai_usage_events` and one pure aggregation (`Tally`, `breakdown`), so their numbers always agree.

Access: owners (and admins, a role this build does not have yet) see the whole workspace; every other member sees only
their own calls. A non-member gets 404 like everywhere else.

Cost honesty. Costs are estimates from the registry price table, never invoices, and the Vertex trial credit balance is not
read (there is no billing API). A call's cost is *recorded* when it is greater than zero, or when a successful call reported
token usage (so a priced-at-zero model is a real 0). A *fixture* call (provider `fixture`) ran no model: its cost is a true 0
and it is counted apart. Every other call is *without cost* (a failed call, or no usage reported): it is counted, kept out of
the sums, and a total with no recorded cost at all is null, never 0.

ponytail: one query reads the window's rows (newest MAX_CALLS) and Python aggregates them, which is fine for the volume a
workspace produces; push the grouping into SQL if a workspace passes ~100k calls in 90 days.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session
from app.llm.registry import PRICE_TABLE_VERSION, price_for
from app.schemas import teams as v
from app.schemas import usage as u
from app.schemas.common import DataMode
from app.services.identity import require_workspace_role
from app.services.run_history import OPERATIONS
from app.services.runs import ACTIVE

MAX_CALLS = 200_000
TOP_ROWS = 25
FAILURES_SHOWN = 50
NEAR_SHARE = 0.8
FIXTURE_PROVIDERS = frozenset({"fixture"})
WORKSPACE_VIEW_ROLES = frozenset({"owner", "admin"})
NO_KEY = "none"
USAGE_NOTES = [
    "Costs are estimates calculated from the gateway's price table, not provider invoices.",
    "Only calls the model gateway recorded for this workspace appear here. Calls made before recording began are not counted.",
    "A call with no recorded cost (a failed call, or one where the provider reported no usage) is counted but never priced as 0.",
]
NOT_TIED = {"project": "Not tied to a project", "campaign": "Not tied to a campaign", "user": "System or unattributed", "run": "Not tied to a run"}


@dataclass(frozen=True)
class Call:
    """One `ai_usage_events` row, with the mode of its project (`live` for a call outside any project)."""

    id: UUID
    at: datetime
    capability: str
    provider: str
    model: str
    status: str
    error_code: str | None
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    cost: float
    project_id: UUID | None
    campaign_id: UUID | None
    user_id: UUID | None
    run_id: UUID | None
    project_mode: str

    @property
    def failed(self) -> bool:
        return self.status != "ok"

    @property
    def fixture(self) -> bool:
        return self.provider in FIXTURE_PROVIDERS

    @property
    def cost_recorded(self) -> bool:
        if self.fixture:
            return False  # known to be 0 and counted as a fixture call instead
        return self.cost > 0 or (not self.failed and self.input_tokens + self.output_tokens + self.thinking_tokens > 0)


@dataclass
class Tally:
    calls: int = 0
    failed: int = 0
    recorded: int = 0
    fixture: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_thinking: int = 0
    cost: float = 0.0

    def add(self, c: Call) -> None:
        self.calls += 1
        self.failed += c.failed
        self.fixture += c.fixture
        self.tokens_in, self.tokens_out, self.tokens_thinking = (
            self.tokens_in + c.input_tokens, self.tokens_out + c.output_tokens, self.tokens_thinking + c.thinking_tokens)
        if c.cost_recorded:
            self.recorded += 1
            self.cost += c.cost

    @property
    def without_cost(self) -> int:
        return self.calls - self.recorded - self.fixture

    @property
    def estimated_cost_usd(self) -> float | None:
        """The recorded sum; null when calls exist but none has a recorded cost (and none is a fixture call)."""
        return round(self.cost, 6) if self.calls == 0 or self.recorded + self.fixture else None


def tally(calls: list[Call]) -> Tally:
    t = Tally()
    for c in calls:
        t.add(c)
    return t


def breakdown(calls: list[Call], key: Callable[[Call], str], *, with_price: bool = False) -> list[v.UsageBreakdownRow]:
    """One row per key, largest recorded cost first, then most calls."""
    groups: dict[str, list[Call]] = defaultdict(list)
    for c in calls:
        groups[key(c)].append(c)
    rows = []
    for k, group in groups.items():
        t = tally(group)
        rows.append(v.UsageBreakdownRow(
            key=k, calls=t.calls, failed_calls=t.failed, input_tokens=t.tokens_in, output_tokens=t.tokens_out,
            thinking_tokens=t.tokens_thinking, estimated_cost_usd=t.estimated_cost_usd, calls_without_cost=t.without_cost,
            fixture_calls=t.fixture, price_known=price_for(group[0].model)[1] if with_price else None))
    return sorted(rows, key=lambda r: (-(r.estimated_cost_usd or 0.0), -r.calls, r.key))


def by_model(c: Call) -> str:
    return f"{c.provider} / {c.model}"


def series(calls: list[Call], first: date, last: date) -> list[u.UsageSeriesPoint]:
    """One point per UTC day from `first` to `last`, quiet days included."""
    days: dict[date, Tally] = defaultdict(Tally)
    for c in calls:
        days[c.at.date()].add(c)
    points = []
    for n in range((last - first).days + 1):
        day = first + timedelta(days=n)
        t = days[day] if day in days else Tally()
        points.append(u.UsageSeriesPoint(day=day, calls=t.calls, failed_calls=t.failed, calls_without_cost=t.without_cost,
                                         fixture_calls=t.fixture, estimated_cost_usd=t.estimated_cost_usd))
    return points


def budget_status(
    today: list[Call], *, scope: Literal["workspace", "own"], day: date, active_runs: int, daily: float, per_run: float, max_active: int,
) -> u.UsageBudgetStatus:
    """Today (UTC) against the daily ceiling. The remaining headroom is the ceiling minus the recorded estimates, which is
    exactly what the budget guard checks; it is withheld from members who see only their own calls."""
    t = tally(today)
    ceiling = daily if daily > 0 else None
    share = t.cost / ceiling if ceiling and scope == "workspace" else None
    status: u.BudgetStatus = "unlimited" if ceiling is None else "ok" if share is None else "reached" if share >= 1 else "near" if share >= NEAR_SHARE else "ok"
    return u.UsageBudgetStatus(
        scope=scope, day=day, resets_at=datetime.combine(day + timedelta(days=1), time.min, tzinfo=UTC), daily_budget_usd=ceiling,
        run_budget_usd=per_run if per_run > 0 else None, max_active_runs_per_user=max_active, active_runs=active_runs,
        spent_today_usd=t.estimated_cost_usd, calls_today=t.calls, calls_today_without_cost=t.without_cost,
        remaining_usd=round(max(0.0, ceiling - t.cost), 6) if ceiling and scope == "workspace" else None,
        used_share=round(share, 4) if share is not None else None, status=status)


# --- reading ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    scope: Literal["workspace", "own"]
    since: datetime
    until: datetime
    calls: list[Call]  # newest first, every mode
    truncated: bool


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


async def _window(s: AsyncSession, user_id: UUID, workspace_id: UUID, days: int, now: datetime) -> Window:
    role = await require_workspace_role(s, user_id, workspace_id)
    scope: Literal["workspace", "own"] = "workspace" if role in WORKSPACE_VIEW_ROLES else "own"
    since = _midnight(now.date() - timedelta(days=days - 1))
    e = m.AiUsageEvent
    stmt = (
        select(e.id, e.created_at, e.capability, e.provider, e.model, e.status, e.error_code, e.input_tokens, e.output_tokens,
               e.thinking_tokens, e.estimated_cost_usd, e.project_id, e.campaign_id, e.user_id, e.run_id, m.Project.mode)
        .outerjoin(m.Project, m.Project.id == e.project_id)
        .where(e.workspace_id == workspace_id, e.created_at >= since)
        .order_by(e.created_at.desc(), e.id).limit(MAX_CALLS + 1)
    )
    if scope == "own":
        stmt = stmt.where(e.user_id == user_id)
    rows = (await s.execute(stmt)).all()
    calls = [Call(*r[:15], project_mode=r[15] or "live") for r in rows[:MAX_CALLS]]
    return Window(scope, since, now, calls, len(rows) > MAX_CALLS)


def _in_mode(calls: list[Call], mode: DataMode) -> list[Call]:
    return [c for c in calls if (c.project_mode == "demo") == (mode == "demo")]


def _summary(w: Window, calls: list[Call], days: int, mode: DataMode) -> dict:
    t = tally(calls)
    notes = list(USAGE_NOTES)
    if w.scope == "own":
        notes.append("You see your own calls only. Workspace owners see everyone's.")
    if w.truncated:
        notes.append(f"This window holds more than {MAX_CALLS:,} calls. The newest are shown and the totals cover only those.")
    return dict(
        days=days, since=w.since, until=w.until, scope=w.scope, mode=mode, calls=t.calls, failed_calls=t.failed,
        calls_without_cost=t.without_cost, fixture_calls=t.fixture, input_tokens=t.tokens_in, output_tokens=t.tokens_out,
        thinking_tokens=t.tokens_thinking, estimated_cost_usd=t.estimated_cost_usd, actual_cost_usd=None,
        price_table_version=PRICE_TABLE_VERSION, by_capability=breakdown(calls, lambda c: c.capability),
        by_model=breakdown(calls, by_model, with_price=True), notes=notes)


async def workspace_usage(user_id: UUID, workspace_id: UUID, days: int, mode: DataMode = "live") -> v.WorkspaceUsage:
    async with read_session() as s:
        w = await _window(s, user_id, workspace_id, days, utcnow())
    return v.WorkspaceUsage(**_summary(w, _in_mode(w.calls, mode), days, mode))


async def _labels(s: AsyncSession, rows: dict[str, list[v.UsageBreakdownRow]], failures: list[Call]) -> dict[str, dict[str, str]]:
    """Readable names for the ids that are about to be shown (a few dozen at most)."""
    ids: dict[str, set[UUID]] = {k: {UUID(r.key) for r in rs if r.key != NO_KEY} for k, rs in rows.items()}
    for c in failures:
        for kind, value in (("project", c.project_id), ("campaign", c.campaign_id), ("run", c.run_id)):
            if value:
                ids[kind].add(value)
    names: dict[str, dict[str, str]] = {k: {} for k in ids}
    if ids["project"]:
        names["project"] = {str(i): n for i, n in (await s.execute(select(m.Project.id, m.Project.name).where(m.Project.id.in_(ids["project"])))).all()}
    if ids["campaign"]:
        names["campaign"] = {str(i): n for i, n in (await s.execute(select(m.Campaign.id, m.Campaign.name).where(m.Campaign.id.in_(ids["campaign"])))).all()}
    if ids["user"]:
        names["user"] = {str(i): d or e or "A member" for i, d, e in (await s.execute(
            select(m.User.id, m.User.display_name, m.User.email).where(m.User.id.in_(ids["user"])))).all()}
    if ids["run"]:
        names["run"] = {str(i): f"{OPERATIONS.get(t, t.replace('_', ' ').capitalize())} {str(i)[:8]}" for i, t in (await s.execute(
            select(m.AgentRun.id, m.AgentRun.run_type).where(m.AgentRun.id.in_(ids["run"])))).all()}
    return names


async def usage_report(user_id: UUID, workspace_id: UUID, days: int, mode: DataMode = "live") -> u.UsageReport:
    now = utcnow()
    settings = get_settings()
    async with read_session() as s:
        w = await _window(s, user_id, workspace_id, days, now)
        active = int(await s.scalar(select(func.count(m.AgentRun.id)).where(m.AgentRun.created_by == user_id, m.AgentRun.status.in_(ACTIVE))) or 0)
        calls = _in_mode(w.calls, mode)
        keyed = {
            "project": breakdown(calls, lambda c: str(c.project_id or NO_KEY)),
            "campaign": breakdown(calls, lambda c: str(c.campaign_id or NO_KEY)),
            "user": breakdown(calls, lambda c: str(c.user_id or NO_KEY)),
            "run": breakdown(calls, lambda c: str(c.run_id or NO_KEY)),
        }
        shown = {k: rows[:TOP_ROWS] for k, rows in keyed.items()}
        failed = [c for c in calls if c.failed]
        names = await _labels(s, shown, failed[:FAILURES_SHOWN])

    def named(kind: str) -> list[v.UsageBreakdownRow]:
        return [r.model_copy(update={"label": NOT_TIED[kind] if r.key == NO_KEY else names[kind].get(r.key)}) for r in shown[kind]]

    codes: dict[str | None, int] = defaultdict(int)
    for c in failed:
        codes[c.error_code] += 1
    today = now.date()
    return u.UsageReport(
        **_summary(w, calls, days, mode), series=series(calls, w.since.date(), today),
        by_project=named("project"), by_campaign=named("campaign"), by_user=named("user"), by_run=named("run"),
        omitted_rows={k: len(rows) - TOP_ROWS for k, rows in keyed.items() if len(rows) > TOP_ROWS},
        budget=budget_status(
            [c for c in w.calls if c.at >= _midnight(today)], scope=w.scope, day=today, active_runs=active,
            daily=settings.ai_daily_budget_usd, per_run=settings.ai_run_budget_usd, max_active=settings.max_active_runs_per_user),
        failure_codes=[u.UsageFailureCount(error_code=k, calls=n) for k, n in sorted(codes.items(), key=lambda kv: (-kv[1], kv[0] or ""))],
        failures=[
            u.UsageFailedCall(
                id=str(c.id), at=c.at, capability=c.capability, provider=c.provider, model=c.model, error_code=c.error_code,
                project_name=names["project"].get(str(c.project_id)), campaign_name=names["campaign"].get(str(c.campaign_id)),
                run_id=str(c.run_id) if c.run_id else None, run_label=names["run"].get(str(c.run_id)))
            for c in failed[:FAILURES_SHOWN]],
        truncated=w.truncated)


# --- demo hook ----------------------------------------------------------------------------------------------------


async def seed_demo_usage(s: AsyncSession, project_id: UUID) -> int:
    """For `services/demo_journey.py`: record one fixture usage row per completed fixture stage of the demo project's runs,
    so the Usage page shows the demo's own (zero-cost) calls. Provider `fixture`, cost 0, no tokens. Idempotent; returns the
    number of rows added. Call it inside the journey's transaction, after the runs exist."""
    project = await s.get(m.Project, project_id)
    e = m.AiUsageEvent
    if project is None or project.mode != "demo" or await s.scalar(select(func.count(e.id)).where(e.project_id == project_id, e.provider == "fixture")):
        return 0
    runs = (await s.execute(select(m.AgentRun).where(m.AgentRun.project_id == project_id).order_by(m.AgentRun.created_at, m.AgentRun.id))).scalars().all()
    added = 0
    for run in runs:
        for i, step in enumerate(run.steps or []):
            if step.get("provider") != "fixture" or step.get("status") != "completed":
                continue
            stage, agent = step.get("stage") or "", step.get("agent") or ""
            capability = "transcribe" if "transcrib" in stage else "vision" if agent == "vision" else "chat"
            s.add(e(
                id=uuid5(NAMESPACE_URL, f"omnicult:demo-usage:{run.id}:{i}"),  # stable, so a reseeded demo gets the same rows
                workspace_id=project.workspace_id, project_id=project_id, campaign_id=run.campaign_id, run_id=run.id, user_id=run.created_by, capability=capability, provider="fixture", model=step.get("model_id") or "demo-fixture",
                prompt_version=step.get("prompt_version"), estimated_cost_usd=0.0, status="ok", created_at=run.created_at))
            added += 1
    await s.flush()
    return added

