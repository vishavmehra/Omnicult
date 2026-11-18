"""Usage and Credits (platform feature E): the full usage report of a workspace, built on the settings usage summary.

Every cost is an estimate from the gateway's price table (`app/llm/registry.py`). A call whose cost was not recorded is
counted in `calls_without_cost` and is never turned into 0. The Vertex trial credit balance is not read: there is no
billing API behind this report.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.teams import UsageBreakdownRow, WorkspaceUsage

BudgetStatus = Literal["ok", "near", "reached", "unlimited"]


class UsageSeriesPoint(ApiModel):
    day: date = Field(description="UTC calendar day.")
    calls: int
    failed_calls: int
    calls_without_cost: int
    fixture_calls: int
    estimated_cost_usd: float | None = Field(description="Recorded estimates for the day; null when the day has calls but none has a recorded cost.")


class UsageBudgetStatus(ApiModel):
    """Today (UTC) against the daily ceiling, from the same table and rule the budget guard uses."""

    scope: Literal["workspace", "own"]
    day: date
    resets_at: datetime
    daily_budget_usd: float | None = Field(description="AI_DAILY_BUDGET_USD; null when the ceiling is switched off.")
    run_budget_usd: float | None = Field(description="AI_RUN_BUDGET_USD, the ceiling for one run; null when switched off.")
    max_active_runs_per_user: int
    active_runs: int = Field(description="The caller's runs queued or running now.")
    spent_today_usd: float | None = Field(description="Recorded estimates since UTC midnight; null when today has calls but none has a recorded cost.")
    calls_today: int
    calls_today_without_cost: int
    remaining_usd: float | None = Field(description="Headroom under the daily ceiling for the whole workspace. Null for the `own` scope and when there is no ceiling.")
    used_share: float | None = Field(description="Spend today as a share of the ceiling, 0 to 1 and beyond. Null for the `own` scope and when there is no ceiling.")
    status: BudgetStatus = Field(description="`reached` at or over the ceiling, `near` from 80 percent, `unlimited` without a ceiling.")


class UsageFailureCount(ApiModel):
    error_code: str | None = Field(description="Null when the failed call recorded no code.")
    calls: int


class UsageFailedCall(ApiModel):
    id: str
    at: datetime
    capability: str
    provider: str
    model: str
    error_code: str | None
    project_name: str | None
    campaign_name: str | None
    run_id: str | None
    run_label: str | None


class UsageReport(WorkspaceUsage):
    """The usage summary plus time series, the project, campaign, user and run breakdowns, today against the budget, and failures."""

    series: list[UsageSeriesPoint] = Field(description="One point per UTC day in the window, empty days included.")
    by_project: list[UsageBreakdownRow]
    by_campaign: list[UsageBreakdownRow]
    by_user: list[UsageBreakdownRow]
    by_run: list[UsageBreakdownRow]
    omitted_rows: dict[str, int] = Field(description="Per breakdown, how many rows beyond the largest are not listed. Totals still include them.")
    budget: UsageBudgetStatus
    failure_codes: list[UsageFailureCount]
    failures: list[UsageFailedCall] = Field(description="The newest failed calls (at most 50).")
    truncated: bool = Field(description="True when the window held more calls than one report reads; the newest are shown and totals cover only those.")
