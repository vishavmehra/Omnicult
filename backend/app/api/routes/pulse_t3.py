"""Live Pulse Tier 3: Predicted vs Actual, saved Alerts and Fatigue Watch, plus the internal call Cloud Scheduler makes.

The campaign routes extend `/campaigns/{id}/pulse`; the sample dataset must be loaded first (409 otherwise), as for the rest
of Pulse. The internal route is for Cloud Scheduler, not the browser: it accepts only a Google OIDC ID token from the configured
service account (`app.core.scheduler_auth`) and is refused when that is not configured.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CurrentUser
from app.core.scheduler_auth import require_scheduler
from app.schemas import pulse_t3 as v
from app.services import pulse_t3, pulse_t3_alerts
from app.services.pulse_t3_fatigue import FatigueConfig

router = APIRouter(tags=["pulse"])
PULSE = "/campaigns/{campaign_id}/pulse"

Metric = Annotated[v.PvaMetric, Query(description="The Pulse metric the predictions are compared with.")]


# --- Predicted vs Actual -----------------------------------------------------------------------------------------------


@router.get(PULSE + "/predicted-actual", response_model=v.PvaResult)
async def get_predicted_actual(campaign_id: UUID, user: CurrentUser, metric: Metric = "ctr") -> v.PvaResult:
    """Stored predictions (Launch Room verdicts and the Quick Read they read) against settled Pulse results, as rankings."""
    return await pulse_t3.predicted_actual(user.id, campaign_id, metric)


@router.get(PULSE + "/predicted-actual/links", response_model=v.PvaLinkBoard)
async def get_version_links(campaign_id: UUID, user: CurrentUser) -> v.PvaLinkBoard:
    """Which Studio version each Pulse version ran as, per region, and the versions a slot can be linked to."""
    return await pulse_t3.link_board(user.id, campaign_id)


@router.put(PULSE + "/predicted-actual/links", response_model=v.PvaLinkBoard)
async def put_version_link(campaign_id: UUID, body: v.PvaLinkSet, user: CurrentUser) -> v.PvaLinkBoard:
    """Link, relink or (version_id null) unlink one Pulse version in one region (owner or editor)."""
    return await pulse_t3.set_link(user.id, campaign_id, body)


@router.get(PULSE + "/predicted-actual/snapshots", response_model=v.PvaSnapshotList)
async def list_comparison_snapshots(campaign_id: UUID, user: CurrentUser) -> v.PvaSnapshotList:
    return await pulse_t3.snapshots(user.id, campaign_id)


@router.post(PULSE + "/predicted-actual/snapshots", response_model=v.PvaSnapshot)
async def create_comparison_snapshot(campaign_id: UUID, body: v.PvaSnapshotCreate, user: CurrentUser) -> v.PvaSnapshot:
    """Store the comparison as it reads now. Identical inputs return the newest snapshot instead of adding one."""
    return await pulse_t3.save_snapshot(user.id, campaign_id, body)


# --- Alerts ------------------------------------------------------------------------------------------------------------------


@router.get(PULSE + "/alert-rules", response_model=v.AlertRuleList)
async def list_alert_rules(campaign_id: UUID, user: CurrentUser) -> v.AlertRuleList:
    return await pulse_t3_alerts.list_rules(user.id, campaign_id)


@router.post(PULSE + "/alert-rules", response_model=v.AlertRuleView, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(campaign_id: UUID, body: v.AlertRuleCreate, user: CurrentUser) -> v.AlertRuleView:
    """Save a rule (owner or editor). Thresholds have the bounds of the alert preview; missing ones take its defaults."""
    return await pulse_t3_alerts.create_rule(user.id, campaign_id, body)


@router.post(PULSE + "/alert-rules/defaults", response_model=v.AlertRuleList, status_code=status.HTTP_201_CREATED)
async def create_default_alert_rules(campaign_id: UUID, user: CurrentUser) -> v.AlertRuleList:
    """The four rules at their default thresholds, for a campaign with no rules (409 otherwise)."""
    return await pulse_t3_alerts.create_default_rules(user.id, campaign_id)


@router.patch(PULSE + "/alert-rules/{rule_id}", response_model=v.AlertRuleView)
async def update_alert_rule(campaign_id: UUID, rule_id: UUID, body: v.AlertRuleUpdate, user: CurrentUser) -> v.AlertRuleView:
    return await pulse_t3_alerts.update_rule(user.id, campaign_id, rule_id, body)


@router.delete(PULSE + "/alert-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(campaign_id: UUID, rule_id: UUID, user: CurrentUser) -> Response:
    """Delete a rule. Its alerts are resolved and stay in the history."""
    await pulse_t3_alerts.delete_rule(user.id, campaign_id, rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(PULSE + "/alert-inbox", response_model=v.AlertInbox)
async def get_alert_inbox(campaign_id: UUID, user: CurrentUser, status_filter: Annotated[v.AlertStatus | None, Query(alias="status")] = None) -> v.AlertInbox:
    """The campaign's alerts with their history, open first, and the latest evaluations."""
    return await pulse_t3_alerts.inbox(user.id, campaign_id, status_filter)


@router.post(PULSE + "/alert-inbox/evaluate", response_model=v.AlertEvaluateResult)
async def evaluate_alert_rules(campaign_id: UUID, user: CurrentUser) -> v.AlertEvaluateResult:
    """Evaluate the saved rules now over the Pulse series (owner or editor)."""
    return await pulse_t3_alerts.evaluate_now(user.id, campaign_id)


@router.post(PULSE + "/alert-inbox/{alert_id}/transition", response_model=v.AlertRecord)
async def transition_alert(campaign_id: UUID, alert_id: UUID, body: v.AlertTransition, user: CurrentUser) -> v.AlertRecord:
    """Acknowledge, resolve or reopen one alert, with an optional note (owner or editor)."""
    return await pulse_t3_alerts.transition(user.id, campaign_id, alert_id, body)


# --- Fatigue Watch ----------------------------------------------------------------------------------------------------------


@router.get(PULSE + "/fatigue", response_model=v.FatigueReport)
async def get_fatigue(
    campaign_id: UUID, user: CurrentUser,
    ctr_decline_pct: Annotated[float, Query(gt=0, le=1)] = 0.10,
    view_rate_decline_pct: Annotated[float, Query(gt=0, le=1)] = 0.10,
    frequency_threshold: Annotated[float, Query(gt=1, le=20)] = 2.5,
    region: Annotated[str | None, Query(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")] = None,
    version: Annotated[str | None, Query(max_length=120)] = None,
) -> v.FatigueReport:
    """Per version and region: CTR and view-rate decay, frequency and repeated exposure, with a computed reason and a suggested refresh."""
    return await pulse_t3.fatigue(
        user.id, campaign_id, FatigueConfig(ctr_decline_pct, view_rate_decline_pct, frequency_threshold),
        region=region, version=version)


# --- Cloud Scheduler --------------------------------------------------------------------------------------------------------


@router.post("/internal/pulse/evaluate-alerts", response_model=v.AlertScheduleSummary, tags=["internal"])
async def evaluate_alerts_for_scheduler(_caller: Annotated[str, Depends(require_scheduler)]) -> v.AlertScheduleSummary:
    """Evaluate every campaign's enabled alert rules, once per period. Idempotent: a second call in the same period changes nothing."""
    return await pulse_t3_alerts.evaluate_scheduled()

