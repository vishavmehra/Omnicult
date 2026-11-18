"""Limits for a synchronous AI call: an HTTP request that waits for a model (Tweak Chips), the counterpart of the run
engine's guards. Two limits, both refused with 429 and a message that names the setting:

- per user: at most MAX_ACTIVE_RUNS_PER_USER of the user's synchronous AI requests in flight at once (the run engine
  uses the same number for a user's active runs);
- per workspace: the workspace's estimated spend today, read from `ai_usage_events`, must be under AI_DAILY_BUDGET_USD
  (the gateway's own BudgetGuard enforces the same ceiling across all workspaces, and the run ceiling per run).

The call also runs inside a usage scope, so its model requests are stored with workspace, project, campaign and user.
Demo projects answer from fixtures and call no provider, so nothing is limited or recorded for them.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from app.core.config import get_settings
from app.core.errors import RateLimited
from app.db import models as m
from app.llm.budget import UsageContext, usage_scope
from app.services.metering import spend_usd

# ponytail: in-process, like the run engine's active-run lock, so exact for one instance; a shared counter (database or
# Redis) if the API ever runs on several instances.
_in_flight: dict[UUID, int] = {}


@asynccontextmanager
async def guarded_ai_call(user_id: UUID, project: m.Project, campaign_id: UUID | None = None) -> AsyncIterator[None]:
    if project.mode == "demo":
        yield
        return
    settings = get_settings()
    limit, active = settings.max_active_runs_per_user, _in_flight.get(user_id, 0)
    if active >= limit:  # checked and counted before any await, so concurrent requests cannot both slip through
        raise RateLimited(
            f"You already have {active} AI requests in progress (limit {limit}, MAX_ACTIVE_RUNS_PER_USER). "
            "Wait for one to finish, then try again."
        )
    _in_flight[user_id] = active + 1
    try:
        budget = settings.ai_daily_budget_usd
        if budget > 0:
            today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            spent = await spend_usd(workspace_id=project.workspace_id, since=today)
            if spent >= budget:
                raise RateLimited(
                    f"This workspace has reached its daily AI budget (${budget:.2f}, AI_DAILY_BUDGET_USD; about "
                    f"${spent:.2f} estimated spend so far today, UTC). Try again tomorrow or raise the limit."
                )
        with usage_scope(UsageContext(
            workspace_id=project.workspace_id, project_id=project.id, campaign_id=campaign_id, user_id=user_id
        )):
            yield
    finally:
        _in_flight[user_id] -= 1
        if not _in_flight[user_id]:
            del _in_flight[user_id]
