"""Run History (feature 52): what ran, with which model and prompt, how many tokens, what it cost (an estimate), and why it failed.

Reads `agent_runs` (status, errors, per-stage traces) and `ai_usage_events` (metered calls). Cost rules, in order:
a run with usage events is costed from them; otherwise from the `usage` of its recorded stages; otherwise it has no
cost. The two sources are never added together because the gateway records a call in both. Costs are estimates from
the price table, never invoices, and a total over runs with missing costs is a lower bound (`runs_without_cost`).
"""

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.db.session import read_session
from app.schemas.common import StepTrace
from app.schemas.proof import (
    RunHistoryDetail,
    RunHistoryItem,
    RunHistoryPage,
    RunHistoryTotals,
    RunInputRef,
    UsageEventView,
)
from app.schemas.runs import RunStatus, RunType
from app.services.common import get_owned
from app.services.runs import V3_RUNS, _has_checkpoint

OPERATIONS = {
    "market_discovery": "Market discovery",
    "campaign_rehearsal": "Audience rehearsal",
    "campaign_adaptation": "Campaign adaptation",
    "campaign_evaluation": "Campaign evaluation",
    "cultural_profile": "Cultural profile",
    "campaign_arena": "Campaign arena",
    "risk_scan": "Risk scan",
    "market_comparison": "Market comparison",
    "population_study": "Population study",
    "social_simulation": "Social simulation",
    "transcreate": "Transcreation",
    "creative_xray": "Creative X-Ray",
    "voice_direct": "Voice Director",
}


def _steps(run: m.AgentRun) -> list[StepTrace]:
    steps = []
    for raw in run.steps or []:
        try:
            steps.append(StepTrace.model_validate(raw))
        except ValidationError:  # a stage trace written by an older version; skip it, keep the rest
            continue
    return steps


def usage_totals(
    steps: list[StepTrace], events: list[m.AiUsageEvent]
) -> tuple[int, int, int, float | None, str]:
    """(input, output, thinking tokens, estimated cost, basis) for one run."""
    if events:
        return (
            sum(e.input_tokens for e in events), sum(e.output_tokens for e in events),
            sum(e.thinking_tokens for e in events), round(sum(e.estimated_cost_usd for e in events), 8), "usage_events",
        )
    used = [s.usage for s in steps if s.usage is not None]
    tokens_in = sum(u.input_tokens or 0 for u in used)
    tokens_out = sum(u.output_tokens or 0 for u in used)
    thinking = sum(max(0, (u.total_tokens or 0) - (u.input_tokens or 0) - (u.output_tokens or 0)) for u in used)
    costs = [u.estimated_cost_usd for u in used if u.estimated_cost_usd is not None]
    return tokens_in, tokens_out, thinking, round(sum(costs), 8) if costs else None, "run_steps" if costs else "none"


def _distinct(values: Iterable[str | None]) -> list[str]:
    return sorted({v for v in values if v})


def history_item(
    run: m.AgentRun, events: list[m.AiUsageEvent], workspace_id: UUID | None, *, resumable: bool
) -> RunHistoryItem:
    steps = _steps(run)
    tokens_in, tokens_out, thinking, cost, basis = usage_totals(steps, events)
    error = run.error or None
    failed = [s.stage for s in steps if s.status == "failed"]
    if error and error.get("stage") and error["stage"] not in failed:
        failed.append(error["stage"])
    duration = (
        int((run.completed_at - run.started_at).total_seconds() * 1000) if run.started_at and run.completed_at else None
    )
    return RunHistoryItem(
        run_id=run.id, workspace_id=workspace_id, project_id=run.project_id, campaign_id=run.campaign_id,
        study_id=run.study_id, run_type=run.run_type,  # type: ignore[arg-type]
        operation=OPERATIONS.get(run.run_type, run.run_type.replace("_", " ").capitalize()),
        status=run.status, mode=run.mode,  # type: ignore[arg-type]
        models=_distinct([e.model for e in events] + [s.model_id for s in steps]),
        providers=_distinct([e.provider for e in events] + [s.provider for s in steps]),
        prompt_versions=_distinct([e.prompt_version for e in events] + [s.prompt_version for s in steps]),
        created_at=run.created_at, started_at=run.started_at, completed_at=run.completed_at, duration_ms=duration,
        input_tokens=tokens_in, output_tokens=tokens_out, thinking_tokens=thinking,
        total_tokens=tokens_in + tokens_out + thinking, estimated_cost_usd=cost,
        cost_basis=basis,  # type: ignore[arg-type]
        cost_is_estimate=True, actual_cost_usd=None,
        ai_calls=len(events) if events else sum(1 for s in steps if s.usage is not None),
        failed_ai_calls=sum(1 for e in events if e.status != "ok"),
        error=error,  # type: ignore[arg-type]
        failed_stages=failed, resumable=resumable, attempt=run.attempt,
    )


def totals_of(items: list[RunHistoryItem], unattributed: tuple[int, float]) -> RunHistoryTotals:
    by_status: dict[str, int] = defaultdict(int)
    for item in items:
        by_status[item.status] += 1
    return RunHistoryTotals(
        runs=len(items), by_status=dict(by_status),
        input_tokens=sum(i.input_tokens for i in items), output_tokens=sum(i.output_tokens for i in items),
        thinking_tokens=sum(i.thinking_tokens for i in items),
        estimated_cost_usd=round(sum(i.estimated_cost_usd or 0.0 for i in items), 8),
        runs_without_cost=sum(1 for i in items if i.estimated_cost_usd is None),
        unattributed_events=unattributed[0], unattributed_cost_usd=round(unattributed[1], 8), cost_is_estimate=True,
    )


async def _events_by_run(s: AsyncSession, run_ids: list[UUID]) -> dict[UUID, list[m.AiUsageEvent]]:
    by_run: dict[UUID, list[m.AiUsageEvent]] = defaultdict(list)
    if run_ids:
        rows = await s.execute(
            select(m.AiUsageEvent).where(m.AiUsageEvent.run_id.in_(run_ids)).order_by(m.AiUsageEvent.created_at, m.AiUsageEvent.id)
        )
        for event in rows.scalars():
            by_run[event.run_id].append(event)  # type: ignore[index]
    return by_run


async def _resumable(s: AsyncSession, run: m.AgentRun) -> bool:
    return run.run_type in V3_RUNS and run.status in ("failed", "cancelled") and await _has_checkpoint(s, run)


async def load_history(
    s: AsyncSession, campaign_id: UUID, workspace_id: UUID | None, *, run_type: str | None = None,
    status: str | None = None,
) -> tuple[list[RunHistoryItem], RunHistoryTotals]:
    """Every matching run of the campaign, newest first, and the totals over all of them.
    # ponytail: loads each matching run's stage traces; fine to a few thousand runs per campaign, aggregate in SQL beyond that."""
    stmt = select(m.AgentRun).where(m.AgentRun.campaign_id == campaign_id)
    if run_type is not None:
        stmt = stmt.where(m.AgentRun.run_type == run_type)
    if status is not None:
        stmt = stmt.where(m.AgentRun.status == status)
    runs = list((await s.execute(stmt.order_by(m.AgentRun.created_at.desc(), m.AgentRun.id))).scalars())
    events = await _events_by_run(s, [r.id for r in runs])
    items = [history_item(r, events.get(r.id, []), workspace_id, resumable=await _resumable(s, r)) for r in runs]
    orphans = (await s.execute(
        select(func.count(m.AiUsageEvent.id), func.coalesce(func.sum(m.AiUsageEvent.estimated_cost_usd), 0.0))
        .where(m.AiUsageEvent.campaign_id == campaign_id, m.AiUsageEvent.run_id.is_(None))
    )).one()
    return items, totals_of(items, (int(orphans[0]), float(orphans[1])))


async def campaign_run_history(
    user_id: UUID, campaign_id: UUID, *, limit: int, offset: int, run_type: RunType | None, status: RunStatus | None
) -> RunHistoryPage:
    async with read_session() as s:
        _, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        items, totals = await load_history(s, campaign_id, project.workspace_id, run_type=run_type, status=status)
    return RunHistoryPage(items=items[offset : offset + limit], limit=limit, offset=offset, total=len(items), totals=totals)


async def run_history_detail(user_id: UUID, run_id: UUID) -> RunHistoryDetail:
    async with read_session() as s:
        run, project = await get_owned(s, m.AgentRun, run_id, user_id, "Run")
        events = (await _events_by_run(s, [run.id])).get(run.id, [])
        resumable = await _resumable(s, run)
    item = history_item(run, events, project.workspace_id, resumable=resumable)
    inputs = run.inputs or {}
    version_id = inputs.get("content_version_id")
    return RunHistoryDetail(
        **item.model_dump(), progress=run.progress, steps=_steps(run),  # type: ignore[arg-type]
        usage_events=[
            UsageEventView(
                id=e.id, capability=e.capability, provider=e.provider, model=e.model, prompt_version=e.prompt_version,
                input_tokens=e.input_tokens, output_tokens=e.output_tokens, thinking_tokens=e.thinking_tokens,
                estimated_cost_usd=e.estimated_cost_usd, latency_ms=e.latency_ms, status=e.status,
                error_code=e.error_code, created_at=e.created_at,
            )
            for e in events
        ],
        input_ref=RunInputRef(
            kind="stored_run_inputs", run_id=run.id, content_version_id=UUID(str(version_id)) if version_id else None,
            study_id=run.study_id, fields=sorted(inputs),
        ),
        output_ref=run.result_ref,  # type: ignore[arg-type]
    )
