"""Live Pulse alerts (feature 45): saved rules per campaign, evaluated in code over the Pulse series.

The three series rules are the ones the alert preview already runs (`pulse_alerts.evaluate`), with the same thresholds and
bounds; `prediction_miss` reads the Predicted vs Actual ranking. Nothing here sends anything: an alert is a row in the app
with a status (open, acknowledged, resolved) and an event history.

An evaluation never turns missing data into "no alert". A rule that cannot read a version and region (too little settled
data, a ratio with no denominator) reports it, and an alert on that slice is left as it is rather than cleared. A condition
that stops holding where it can be read clears its alert; a condition that returns reopens the same alert, except that an
alert a person resolved stays resolved until newer data fires it again.

Evaluation runs on a sample refresh, on demand, and from Cloud Scheduler (`evaluate_scheduled`, once per campaign and period).
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas import pulse_t3 as v
from app.schemas.common import ErrorDetail
from app.services import pulse, pulse_t3
from app.services.audit import record_audit
from app.services.pulse import Loaded
from app.services.pulse_alerts import AlertConfig, Evaluation, evaluate
from app.services.pulse_t3_compare import MIN_PAIRS_FOR_TAU

logger = logging.getLogger("omnicult.pulse.alerts")

_DEFAULT_CFG = AlertConfig()
DEFAULTS: dict[str, dict] = {
    "ctr_drop": {"ctr_drop_pct": _DEFAULT_CFG.ctr_drop_pct},
    "frequency_fatigue": {
        "frequency_threshold": _DEFAULT_CFG.frequency_threshold,
        "frequency_min_ctr_decline_pct": _DEFAULT_CFG.frequency_min_ctr_decline_pct,
    },
    "cost_spike": {"cost_spike_pct": _DEFAULT_CFG.cost_spike_pct, "min_conversions": _DEFAULT_CFG.min_conversions, "cost_metric": "both"},
    "prediction_miss": {"min_rank_gap": 2},
}
DEFAULT_NAMES = {"ctr_drop": "CTR drop", "frequency_fatigue": "Frequency fatigue", "cost_spike": "Cost spike", "prediction_miss": "Prediction miss"}
PREDICTION_MISS_METRIC = "ctr"
PREDICTION_MISS_ACTION = (
    "Do not lean on Quick Read or the Launch Room score for this version in this region. Validate the creative with real "
    "people before spending more."
)
ALL = ("*", "*")  # a rule that could not read anything


def _bad(field_name: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field_name, message=message)])


def normalise_params(alert_type: str, supplied: v.AlertRuleParams) -> dict:
    """The thresholds the alert type reads, with defaults filled in. A threshold the type does not read is refused."""
    given = supplied.model_dump(exclude_none=True)
    unused = sorted(set(given) - set(DEFAULTS[alert_type]))
    if unused:
        raise _bad(f"params.{unused[0]}", f"{unused[0]} is not read by a {alert_type} rule.")
    return {**DEFAULTS[alert_type], **given}


def _rule_view(rule: m.PulseAlertRule, open_alerts: int) -> v.AlertRuleView:
    return v.AlertRuleView(
        id=rule.id, name=rule.name, alert_type=rule.alert_type, region_code=rule.region_code, version_label=rule.version_label,  # type: ignore[arg-type]
        enabled=rule.enabled, params=v.AlertRuleParams(**rule.params), open_alerts=open_alerts,
        created_at=rule.created_at, updated_at=rule.updated_at)


async def _rule(s: AsyncSession, campaign_id: UUID, rule_id: UUID) -> m.PulseAlertRule:
    rule = await s.get(m.PulseAlertRule, rule_id)
    if rule is None or rule.campaign_id != campaign_id:
        from app.services.common import not_found

        raise not_found("Alert rule")
    return rule


async def _open_counts(s: AsyncSession, campaign_id: UUID) -> dict[UUID | None, int]:
    found = await s.execute(select(m.PulseAlert.rule_id, func.count()).where(
        m.PulseAlert.campaign_id == campaign_id, m.PulseAlert.status != "resolved").group_by(m.PulseAlert.rule_id))
    return dict(found.all())


# --- rules ---------------------------------------------------------------------------------------------------------------


async def list_rules(user_id: UUID, campaign_id: UUID) -> v.AlertRuleList:
    async with read_session() as s:
        await pulse._campaign(s, user_id, campaign_id)
        rules = (await s.execute(select(m.PulseAlertRule).where(m.PulseAlertRule.campaign_id == campaign_id)
                                 .order_by(m.PulseAlertRule.created_at, m.PulseAlertRule.id))).scalars().all()
        counts = await _open_counts(s, campaign_id)
    return v.AlertRuleList(items=[_rule_view(r, counts.get(r.id, 0)) for r in rules])


def _scope_check(loaded: Loaded | None, region: str | None, version: str | None) -> None:
    if loaded is None:
        return
    if region is not None and region not in {r.region_code for r in loaded.rows}:
        raise _bad("region_code", "That region is not in the Pulse series.")
    if version is not None and version not in {r.version_label for r in loaded.rows}:
        raise _bad("version_label", "That version is not in the Pulse series.")


async def _loaded_or_none(s: AsyncSession, campaign_id: UUID) -> Loaded | None:
    try:
        return await pulse._load(s, campaign_id)
    except Conflict:
        return None


async def create_rule(user_id: UUID, campaign_id: UUID, body: v.AlertRuleCreate) -> v.AlertRuleView:
    params = normalise_params(body.alert_type, body.params)
    async with session() as s, s.begin():
        project = await pulse._campaign(s, user_id, campaign_id, writable=True)
        _scope_check(await _loaded_or_none(s, campaign_id), body.region_code, body.version_label)
        now = utcnow()
        rule = m.PulseAlertRule(
            id=uuid4(), project_id=project.id, campaign_id=campaign_id, name=body.name, alert_type=body.alert_type,
            region_code=body.region_code, version_label=body.version_label, params=params, enabled=body.enabled,
            created_by=user_id, created_at=now, updated_at=now)
        s.add(rule)
        await record_audit(
            s, action="pulse.alert_rule.create", target_type="pulse_alert_rule", target_id=str(rule.id),
            workspace_id=project.workspace_id, actor_user_id=user_id, detail={"alert_type": body.alert_type, "params": params})
        await s.flush()
        return _rule_view(rule, 0)


async def create_default_rules(user_id: UUID, campaign_id: UUID) -> v.AlertRuleList:
    """The four rules at the preview's defaults, for a campaign that has none yet."""
    async with session() as s, s.begin():
        project = await pulse._campaign(s, user_id, campaign_id, writable=True)
        if await s.scalar(select(func.count()).select_from(m.PulseAlertRule).where(m.PulseAlertRule.campaign_id == campaign_id)):
            raise Conflict("This campaign already has alert rules.")
        now = utcnow()
        for i, (alert_type, params) in enumerate(DEFAULTS.items()):  # a microsecond apart, so the list keeps this order
            s.add(m.PulseAlertRule(
                id=uuid4(), project_id=project.id, campaign_id=campaign_id, name=DEFAULT_NAMES[alert_type], alert_type=alert_type,
                region_code=None, version_label=None, params=dict(params), enabled=True, created_by=user_id,
                created_at=now + timedelta(microseconds=i), updated_at=now))
        await record_audit(s, action="pulse.alert_rule.defaults", target_type="campaign", target_id=str(campaign_id),
                           workspace_id=project.workspace_id, actor_user_id=user_id, detail={})
    return await list_rules(user_id, campaign_id)


async def update_rule(user_id: UUID, campaign_id: UUID, rule_id: UUID, body: v.AlertRuleUpdate) -> v.AlertRuleView:
    async with session() as s, s.begin():
        project = await pulse._campaign(s, user_id, campaign_id, writable=True)
        rule = await _rule(s, campaign_id, rule_id)
        region = None if body.clear_region else body.region_code or rule.region_code
        version = None if body.clear_version else body.version_label or rule.version_label
        _scope_check(await _loaded_or_none(s, campaign_id), region, version)
        if body.params is not None:
            normalise_params(rule.alert_type, body.params)  # refuses a threshold this alert type does not read
            rule.params = {**rule.params, **body.params.model_dump(exclude_none=True)}
        if body.name is not None:
            rule.name = body.name
        if body.enabled is not None:
            rule.enabled = body.enabled
        rule.region_code, rule.version_label, rule.updated_at = region, version, utcnow()
        await record_audit(
            s, action="pulse.alert_rule.update", target_type="pulse_alert_rule", target_id=str(rule.id),
            workspace_id=project.workspace_id, actor_user_id=user_id, detail={"enabled": rule.enabled, "params": rule.params})
        await s.flush()
        counts = await _open_counts(s, campaign_id)
        return _rule_view(rule, counts.get(rule.id, 0))


async def delete_rule(user_id: UUID, campaign_id: UUID, rule_id: UUID) -> None:
    """Delete the rule. Its alerts are resolved ("rule removed") and stay in the history."""
    async with session() as s, s.begin():
        project = await pulse._campaign(s, user_id, campaign_id, writable=True)
        rule = await _rule(s, campaign_id, rule_id)
        now = utcnow()
        for alert in (await s.execute(select(m.PulseAlert).where(m.PulseAlert.rule_id == rule.id))).scalars():
            if alert.status != "resolved":
                _resolve(s, alert, "rule_removed", "user", user_id, now, "The rule was deleted.")
            alert.rule_id = None
        await s.flush()
        await s.delete(rule)
        await record_audit(s, action="pulse.alert_rule.delete", target_type="pulse_alert_rule", target_id=str(rule_id),
                           workspace_id=project.workspace_id, actor_user_id=user_id, detail={"alert_type": rule.alert_type})


# --- evaluation ----------------------------------------------------------------------------------------------------------


@dataclass
class Candidate:
    key: str
    rule: m.PulseAlertRule
    alert_type: str
    region: str
    version: str
    metric: str
    threshold: float
    observed: float
    comparison_value: float
    comparison: str
    window_from: date
    window_to: date
    action: str
    source_path: str


@dataclass
class RuleOutcome:
    candidates: list[Candidate] = field(default_factory=list)
    not_read: list[v.AlertNotRead] = field(default_factory=list)
    unreadable: set[tuple[str, str]] = field(default_factory=set)


def _in_scope(rule: m.PulseAlertRule, region: str, version: str) -> bool:
    return (rule.region_code is None or rule.region_code == region) and (rule.version_label is None or rule.version_label == version)


def _series_path(campaign_id: UUID, metric: str, region: str, version: str, loaded: Loaded) -> str:
    first, last = min(r.day for r in loaded.rows), max(r.day for r in loaded.rows)
    query = urlencode({"metric": metric, "region": region, "version": version, "date_from": first.isoformat(), "date_to": last.isoformat()})
    return f"/api/v1/campaigns/{campaign_id}/pulse/timeseries?{query}"


def _series_rule(rule: m.PulseAlertRule, campaign_id: UUID, loaded: Loaded, cache: dict[AlertConfig, Evaluation]) -> RuleOutcome:
    p = rule.params
    cfg = AlertConfig(**{k: val for k, val in p.items() if k in AlertConfig.__dataclass_fields__})
    if cfg not in cache:
        cache[cfg] = evaluate(loaded.rows, cfg)
    result = cache[cfg]
    cost_metric = p.get("cost_metric", "both") if rule.alert_type == "cost_spike" else None
    out = RuleOutcome()
    for a in result.alerts:
        if a.alert_type != rule.alert_type or not _in_scope(rule, a.region_code, a.version_label):
            continue
        if cost_metric not in (None, "both") and a.metric != cost_metric:
            continue
        out.candidates.append(Candidate(
            key=f"{rule.id}|{a.region_code}|{a.version_label}|{a.metric}", rule=rule, alert_type=a.alert_type, region=a.region_code,
            version=a.version_label, metric=a.metric, threshold=a.threshold, observed=a.observed_value,
            comparison_value=a.comparison_value, comparison=a.comparison, window_from=a.window_from, window_to=a.window_to,
            action=a.suggested_action, source_path=_series_path(campaign_id, a.metric, a.region_code, a.version_label, loaded)))
    for sk in result.skipped:
        mine = sk.rule == "all" or sk.rule == rule.alert_type or (
            sk.rule.startswith(f"{rule.alert_type}:") and (cost_metric in (None, "both") or sk.rule.endswith(f":{cost_metric}")))
        if mine and _in_scope(rule, sk.region_code, sk.version_label):
            out.not_read.append(v.AlertNotRead(rule_name=rule.name, region_code=sk.region_code, version_label=sk.version_label, reason=sk.reason))
            out.unreadable.add((sk.region_code, sk.version_label))
    return out


async def _prediction_rule(s: AsyncSession, rule: m.PulseAlertRule, campaign_id: UUID, loaded: Loaded) -> RuleOutcome:
    result = await pulse_t3.build_result(s, campaign_id, loaded, PREDICTION_MISS_METRIC)
    out = RuleOutcome()
    scored = [p for p in result.pairs if p.launch_score is not None]
    if len(scored) < MIN_PAIRS_FOR_TAU:
        out.not_read.append(v.AlertNotRead(
            rule_name=rule.name, region_code="all", version_label="all",
            reason=f"Needs at least {MIN_PAIRS_FOR_TAU} pairs with a stored prediction and a settled result; {len(scored)} found."))
        out.unreadable.add(ALL)
        return out
    gap = rule.params.get("min_rank_gap", DEFAULTS["prediction_miss"]["min_rank_gap"])
    n = len(scored)
    for p in scored:
        check = p.launch_score
        if check is None or check.rank_gap < gap or not _in_scope(rule, p.region_code, p.pulse_version):
            continue
        score = f"{p.predicted.overall_score:.1f}" if p.predicted.overall_score is not None else "n/a"
        out.candidates.append(Candidate(
            key=f"{rule.id}|{p.region_code}|{p.pulse_version}|prediction_rank_gap", rule=rule, alert_type="prediction_miss",
            region=p.region_code, version=p.pulse_version, metric="prediction_rank_gap", threshold=float(gap), observed=check.rank_gap,
            comparison_value=check.predicted_rank,
            comparison=(f"Predicted rank {check.predicted_rank:g} of {n} on the Launch Room score ({score}, {p.predicted.verdict}); "
                        f"actual rank {check.actual_rank:g} of {n} on CTR ({p.actual.value * 100:.2f}%)."),
            window_from=p.actual.window_from, window_to=p.actual.window_to, action=PREDICTION_MISS_ACTION,
            source_path=f"/api/v1/campaigns/{campaign_id}/pulse/predicted-actual?metric={PREDICTION_MISS_METRIC}"))
    return out


def _event(s: AsyncSession, alert: m.PulseAlert, kind: str, trigger: str, actor: UUID | None, now: datetime,
           note: str | None = None) -> None:
    s.add(m.PulseAlertEvent(
        id=uuid4(), alert_id=alert.id, campaign_id=alert.campaign_id, at=now, kind=kind, trigger=trigger, actor_user_id=actor,
        note=note, observed_value=alert.observed_value))


def _resolve(s: AsyncSession, alert: m.PulseAlert, resolution: str, trigger: str, actor: UUID | None, now: datetime,
             note: str | None = None) -> None:
    alert.status, alert.resolution, alert.resolved_at, alert.resolved_by = "resolved", resolution, now, actor
    _event(s, alert, "resolved", trigger, actor, now, note)


def _fill(alert: m.PulseAlert, c: Candidate, dataset_version: str, now: datetime) -> None:
    alert.rule_name, alert.metric, alert.threshold, alert.observed_value = c.rule.name, c.metric, c.threshold, c.observed
    alert.comparison_value, alert.comparison, alert.window_from, alert.window_to = c.comparison_value, c.comparison, c.window_from, c.window_to
    alert.suggested_action, alert.source_path, alert.dataset_version, alert.last_seen_at = c.action, c.source_path, dataset_version, now


async def run_evaluation(
    s: AsyncSession, project: m.Project, campaign_id: UUID, loaded: Loaded, *, trigger: str, actor: UUID | None,
    period_key: str | None = None,
) -> tuple[m.PulseAlertEvaluation, list[v.AlertNotRead]]:
    """Evaluate every rule of the campaign over the loaded series and bring the stored alerts in line. Runs in the caller's transaction."""
    now = utcnow()
    rules = (await s.execute(select(m.PulseAlertRule).where(m.PulseAlertRule.campaign_id == campaign_id)
                             .order_by(m.PulseAlertRule.created_at, m.PulseAlertRule.id))).scalars().all()
    cache: dict[AlertConfig, Evaluation] = {}
    outcomes: dict[UUID, RuleOutcome] = {}
    for rule in rules:
        if not rule.enabled:
            continue
        outcomes[rule.id] = (await _prediction_rule(s, rule, campaign_id, loaded) if rule.alert_type == "prediction_miss"
                             else _series_rule(rule, campaign_id, loaded, cache))
    existing = {a.alert_key: a for a in (await s.execute(select(m.PulseAlert).where(m.PulseAlert.campaign_id == campaign_id))).scalars()}
    opened = reopened = resolved = 0
    seen: set[str] = set()
    for outcome in outcomes.values():
        for c in outcome.candidates:
            seen.add(c.key)
            alert = existing.get(c.key)
            if alert is None:
                alert = m.PulseAlert(
                    id=uuid4(), project_id=project.id, campaign_id=campaign_id, rule_id=c.rule.id, rule_name=c.rule.name, alert_key=c.key,
                    alert_type=c.alert_type, region_code=c.region, version_label=c.version, metric=c.metric, threshold=c.threshold,
                    observed_value=c.observed, comparison_value=c.comparison_value, comparison=c.comparison,
                    window_from=c.window_from, window_to=c.window_to, suggested_action=c.action, source_path=c.source_path,
                    dataset_version=loaded.dataset_version, status="open", opened_at=now, last_seen_at=now)
                s.add(alert)
                await s.flush()
                _event(s, alert, "opened", trigger, actor, now)
                existing[c.key] = alert
                opened += 1
            elif alert.status == "resolved":
                if alert.resolution == "manual" and c.window_to <= alert.window_to:  # a person's decision stands until newer data fires
                    alert.last_seen_at = now
                    continue
                _fill(alert, c, loaded.dataset_version, now)
                alert.rule_id = c.rule.id
                alert.status, alert.resolution, alert.resolved_at, alert.resolved_by = "open", None, None, None
                alert.acknowledged_at, alert.acknowledged_by = None, None
                _event(s, alert, "reopened", trigger, actor, now)
                reopened += 1
            else:
                _fill(alert, c, loaded.dataset_version, now)
    enabled = {r.id for r in rules if r.enabled}
    for key, alert in existing.items():
        if alert.status == "resolved" or key in seen:
            continue
        if alert.rule_id is None:
            _resolve(s, alert, "rule_removed", trigger, actor, now, "The rule no longer exists.")
        elif alert.rule_id not in enabled:
            _resolve(s, alert, "rule_disabled", trigger, actor, now, "The rule is switched off.")
        else:
            blind = outcomes[alert.rule_id].unreadable
            if ALL in blind or (alert.region_code, alert.version_label) in blind:
                continue  # the rule could not read this slice: unknown is not "cleared"
            _resolve(s, alert, "cleared", trigger, actor, now, "The condition no longer holds.")
        resolved += 1
    not_read = [n for o in outcomes.values() for n in o.not_read]
    evaluation = m.PulseAlertEvaluation(
        id=uuid4(), project_id=project.id, campaign_id=campaign_id, trigger=trigger, period_key=period_key,
        dataset_version=loaded.dataset_version, evaluated_at=now, rules_evaluated=len(outcomes),
        alerts_found=sum(len(o.candidates) for o in outcomes.values()), opened=opened, reopened=reopened, resolved=resolved,
        not_evaluated=len(not_read))
    s.add(evaluation)
    await s.flush()
    return evaluation, not_read


def _evaluation_view(e: m.PulseAlertEvaluation) -> v.AlertEvaluationView:
    return v.AlertEvaluationView(
        id=e.id, trigger=e.trigger, period_key=e.period_key, dataset_version=e.dataset_version, evaluated_at=e.evaluated_at,  # type: ignore[arg-type]
        rules_evaluated=e.rules_evaluated, alerts_found=e.alerts_found, opened=e.opened, reopened=e.reopened, resolved=e.resolved,
        not_evaluated=e.not_evaluated)


async def evaluate_now(user_id: UUID, campaign_id: UUID) -> v.AlertEvaluateResult:
    """On demand: owners and editors. A campaign whose sample is not loaded is a 409, like the rest of Pulse."""
    async with session() as s, s.begin():
        project = await pulse._campaign(s, user_id, campaign_id, writable=True)
        loaded = await pulse._load(s, campaign_id)
        evaluation, not_read = await run_evaluation(s, project, campaign_id, loaded, trigger="manual", actor=user_id)
        await record_audit(s, action="pulse.alerts.evaluate", target_type="campaign", target_id=str(campaign_id),
                           workspace_id=project.workspace_id, actor_user_id=user_id,
                           detail={"opened": evaluation.opened, "resolved": evaluation.resolved})
        return v.AlertEvaluateResult(evaluation=_evaluation_view(evaluation), not_read=not_read)


async def evaluate_after_refresh(user_id: UUID, campaign_id: UUID) -> None:
    """After the sample is (re)loaded: evaluate the rules the campaign already has. A failure here never fails the refresh."""
    try:
        async with session() as s, s.begin():
            project = await pulse._campaign(s, user_id, campaign_id, writable=True)
            if not await s.scalar(select(func.count()).select_from(m.PulseAlertRule).where(m.PulseAlertRule.campaign_id == campaign_id)):
                return
            loaded = await pulse._load(s, campaign_id)
            await run_evaluation(s, project, campaign_id, loaded, trigger="refresh", actor=None)
    except Exception:
        logger.warning("alert evaluation after a refresh failed for campaign %s", campaign_id, exc_info=True)


def period_key(now: datetime, hours: int) -> str:
    """The scheduler's period: the UTC day for 24 hours, otherwise the UTC day and the start hour of the bucket."""
    return f"{now:%Y-%m-%d}" if hours >= 24 else f"{now:%Y-%m-%d}T{now.hour // hours * hours:02d}"


async def evaluate_scheduled(now: datetime | None = None) -> v.AlertScheduleSummary:
    """Cloud Scheduler: every campaign with an enabled rule is evaluated once per period; a second call in the same period
    changes nothing. A campaign with no sample loaded is counted, not failed, and one campaign failing never stops the rest."""
    now = now or utcnow()
    key = period_key(now, get_settings().pulse_alert_period_hours)
    async with read_session() as s:
        campaigns = (await s.execute(
            select(m.PulseAlertRule.campaign_id).join(m.Project, m.Project.id == m.PulseAlertRule.project_id)
            .where(m.PulseAlertRule.enabled.is_(True), m.Project.status != "archived").distinct()
            .order_by(m.PulseAlertRule.campaign_id))).scalars().all()
    tally: dict[str, int] = defaultdict(int)
    for campaign_id in campaigns:
        try:
            done: tuple[int, int] | None = None
            async with session() as s, s.begin():
                if await s.scalar(select(m.PulseAlertEvaluation.id).where(
                        m.PulseAlertEvaluation.campaign_id == campaign_id, m.PulseAlertEvaluation.period_key == key)):
                    tally["already_evaluated"] += 1
                    continue
                campaign = await s.get(m.Campaign, campaign_id)
                project = await s.get(m.Project, campaign.project_id)
                try:
                    loaded = await pulse._load(s, campaign_id)
                except Conflict:
                    tally["no_data"] += 1
                    continue
                evaluation, _ = await run_evaluation(s, project, campaign_id, loaded, trigger="scheduler", actor=None, period_key=key)
                done = (evaluation.opened + evaluation.reopened, evaluation.resolved)
            if done is not None:  # counted only once the transaction has committed
                tally["evaluated"] += 1
                tally["alerts_opened"] += done[0]
                tally["alerts_resolved"] += done[1]
        except IntegrityError:  # a concurrent call took this period first
            tally["already_evaluated"] += 1
        except Exception:
            logger.warning("scheduled alert evaluation failed for campaign %s", campaign_id, exc_info=True)
            tally["failed"] += 1
    return v.AlertScheduleSummary(
        period_key=key, campaigns_with_rules=len(campaigns), evaluated=tally["evaluated"], already_evaluated=tally["already_evaluated"],
        no_data=tally["no_data"], failed=tally["failed"], alerts_opened=tally["alerts_opened"], alerts_resolved=tally["alerts_resolved"])


# --- the inbox ------------------------------------------------------------------------------------------------------------


def _record(a: m.PulseAlert, events: list[m.PulseAlertEvent]) -> v.AlertRecord:
    return v.AlertRecord(
        id=a.id, rule_id=a.rule_id, rule_name=a.rule_name, alert_type=a.alert_type, region_code=a.region_code,  # type: ignore[arg-type]
        region_name=pulse.REGION_NAMES.get(a.region_code, a.region_code), version_label=a.version_label, metric=a.metric,
        threshold=a.threshold, observed_value=a.observed_value, comparison_value=a.comparison_value, comparison=a.comparison,
        window_from=a.window_from, window_to=a.window_to, suggested_action=a.suggested_action, source_path=a.source_path,
        status=a.status, resolution=a.resolution, opened_at=a.opened_at, last_seen_at=a.last_seen_at,  # type: ignore[arg-type]
        acknowledged_at=a.acknowledged_at, resolved_at=a.resolved_at,
        events=[v.AlertRecordEvent(kind=e.kind, trigger=e.trigger, at=e.at, actor_user_id=e.actor_user_id, note=e.note,  # type: ignore[arg-type]
                                   observed_value=e.observed_value) for e in events])


STATUS_ORDER = {"open": 0, "acknowledged": 1, "resolved": 2}


async def inbox(user_id: UUID, campaign_id: UUID, status: str | None) -> v.AlertInbox:
    async with read_session() as s:
        await pulse._campaign(s, user_id, campaign_id)
        loaded = await pulse._load(s, campaign_id)
        stmt = select(m.PulseAlert).where(m.PulseAlert.campaign_id == campaign_id)
        if status is not None:
            stmt = stmt.where(m.PulseAlert.status == status)
        alerts = sorted((await s.execute(stmt.order_by(m.PulseAlert.opened_at.desc(), m.PulseAlert.id))).scalars().all(),
                        key=lambda a: STATUS_ORDER[a.status])[:200]
        events: dict[UUID, list[m.PulseAlertEvent]] = defaultdict(list)
        if alerts:
            for e in (await s.execute(select(m.PulseAlertEvent).where(m.PulseAlertEvent.alert_id.in_([a.id for a in alerts]))
                                      .order_by(m.PulseAlertEvent.at, m.PulseAlertEvent.id))).scalars():
                events[e.alert_id].append(e)
        counts = dict((await s.execute(select(m.PulseAlert.status, func.count()).where(m.PulseAlert.campaign_id == campaign_id)
                                       .group_by(m.PulseAlert.status))).all())
        evaluations = (await s.execute(select(m.PulseAlertEvaluation).where(m.PulseAlertEvaluation.campaign_id == campaign_id)
                                       .order_by(m.PulseAlertEvaluation.evaluated_at.desc(), m.PulseAlertEvaluation.id.desc()).limit(10))).scalars().all()
    return v.AlertInbox(
        **pulse._stamp(loaded), items=[_record(a, events[a.id]) for a in alerts], open=counts.get("open", 0),
        acknowledged=counts.get("acknowledged", 0), resolved=counts.get("resolved", 0),
        evaluations=[_evaluation_view(e) for e in evaluations])


TRANSITIONS = {"acknowledge": ("open",), "resolve": ("open", "acknowledged"), "reopen": ("resolved",)}
PAST = {"acknowledge": "acknowledged", "resolve": "resolved", "reopen": "reopened"}


async def transition(user_id: UUID, campaign_id: UUID, alert_id: UUID, body: v.AlertTransition) -> v.AlertRecord:
    async with session() as s, s.begin():
        project = await pulse._campaign(s, user_id, campaign_id, writable=True)
        alert = await s.get(m.PulseAlert, alert_id)
        if alert is None or alert.campaign_id != campaign_id:
            from app.services.common import not_found

            raise not_found("Alert")
        if alert.status not in TRANSITIONS[body.action]:
            raise Conflict(f"An alert that is {alert.status} cannot be {PAST[body.action]}.")
        now = utcnow()
        if body.action == "acknowledge":
            alert.status, alert.acknowledged_at, alert.acknowledged_by = "acknowledged", now, user_id
            _event(s, alert, "acknowledged", "user", user_id, now, body.note)
        elif body.action == "resolve":
            _resolve(s, alert, "manual", "user", user_id, now, body.note)
        else:
            alert.status, alert.resolution, alert.resolved_at, alert.resolved_by = "open", None, None, None
            alert.acknowledged_at, alert.acknowledged_by = None, None
            _event(s, alert, "reopened", "user", user_id, now, body.note)
        await record_audit(s, action=f"pulse.alert.{body.action}", target_type="pulse_alert", target_id=str(alert.id),
                           workspace_id=project.workspace_id, actor_user_id=user_id, detail={"alert_type": alert.alert_type})
        await s.flush()
        events = (await s.execute(select(m.PulseAlertEvent).where(m.PulseAlertEvent.alert_id == alert.id)
                                  .order_by(m.PulseAlertEvent.at, m.PulseAlertEvent.id))).scalars().all()
        return _record(alert, list(events))
