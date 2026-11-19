"""State facts: official state-wise statistics (data.gov.in) for one state, with the all-India value where a dataset has one.

Every number is a published figure, passed through unchanged apart from units. A fact a dataset does not hold for the state is
absent. `mode` is the campaign's: demo campaigns read a recorded snapshot, live campaigns the stored pull.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.common import ApiModel, DataMode
from app.schemas.lens import RegionCodeStr

FactUnit = Literal["percent", "per100", "inr", "million"]
FactGroupKey = Literal["connectivity", "economy", "homes", "people", "visitors"]


class StateFactPoint(ApiModel):
    period: str
    value: float


class StateFactPart(ApiModel):
    label: str
    value: float
    national: float | None
    period: str


class StateFact(ApiModel):
    key: str
    label: str
    unit: FactUnit
    value: float | None  # None for a fact shown only as its parts (rural and urban spend)
    period: str  # the period of `value` (or of the parts)
    national: float | None  # the all-India figure for the same period, where the dataset has one
    series: list[StateFactPoint]  # this state's earlier and current periods, oldest first; one point when there is only one
    parts: list[StateFactPart]


class StateFactGroup(ApiModel):
    key: FactGroupKey
    title: str
    facts: list[StateFact]


class StateFacts(ApiModel):
    campaign_id: UUID
    region_code: RegionCodeStr
    region_name: str
    mode: DataMode
    groups: list[StateFactGroup]
    fetched_at: datetime | None
    can_refresh: bool


class StateFactsResourceResult(ApiModel):
    resource: str
    status: Literal["updated", "unchanged", "failed"]
    rows: int
    error_kind: str | None = None  # not_configured | auth | rate_limited | timeout | network | http | validation
    error: str | None = None


class StateFactsRefreshSummary(ApiModel):
    resources: list[StateFactsResourceResult]
    updated: int
    unchanged: int
    failed: int
