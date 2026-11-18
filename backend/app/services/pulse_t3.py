"""Live Pulse Tier 3 service: Predicted vs Actual (44) with its version links and stored snapshots, and Fatigue Watch (47).

Predictions are read from stored readiness verdicts (they carry the Quick Read counts), results from the Pulse sample
series. Access follows the campaign, like the rest of Pulse: another workspace's campaign is a 404, writes need an owner or
editor. Nothing here calls a model.
"""

from collections import defaultdict
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas import pulse_t3 as v
from app.schemas.common import ErrorDetail
from app.services import pulse, pulse_t3_compare as cmp, pulse_t3_fatigue as fat
from app.services.audit import record_audit
from app.services.pulse import Loaded
from app.services.pulse_metrics import BY_NAME
from app.services.versions import node_in

VERDICT_RANK = {"go": 0, "fix": 1, "rethink": 2}
STUDIO_LINK = "/app/c/{campaign_id}/studio"


def _bad(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


# --- stored predictions --------------------------------------------------------------------------------------------------


async def latest_verdicts(s: AsyncSession, campaign_id: UUID) -> dict[tuple[str, UUID], tuple[m.ReadinessVerdict, str]]:
    """The newest verdict for every (region code, Studio version) of the campaign, with the version's label."""
    found = (await s.execute(
        select(m.ReadinessVerdict, m.Region.code).join(m.Region, m.Region.id == m.ReadinessVerdict.region_id)
        .where(m.ReadinessVerdict.campaign_id == campaign_id)
        .order_by(m.ReadinessVerdict.computed_at.desc(), m.ReadinessVerdict.id.desc()))).all()
    newest: dict[tuple[str, UUID], m.ReadinessVerdict] = {}
    for row, code in found:
        newest.setdefault((code, row.version_id), row)
    labels = dict((await s.execute(
        select(m.VersionNode.id, m.VersionNode.label).where(m.VersionNode.id.in_({k[1] for k in newest})))).all()) if newest else {}
    return {key: (row, labels.get(key[1], "Version")) for key, row in newest.items()}


def _quick_read(inputs: dict) -> cmp.QuickReadCounts | None:
    q = (inputs or {}).get("quick_read")
    if not q:
        return None
    return cmp.QuickReadCounts(
        respondents=int(q["respondents"]), positive=int(q["positive"]), negative=int(q["negative"]),
        understood=int(q["understood"]), relevant=int(q["relevant"]))


async def build_result(s: AsyncSession, campaign_id: UUID, loaded: Loaded, metric: str) -> v.PvaResult:
    """The comparison for one metric, from the stored links, verdicts and the loaded series."""
    links = (await s.execute(select(m.PulseVersionLink).where(m.PulseVersionLink.campaign_id == campaign_id))).scalars().all()
    verdicts = await latest_verdicts(s, campaign_id)
    predictions, extra = [], []
    for link in links:
        found = verdicts.get((link.region_code, link.version_id))
        if found is None:
            extra.append(v.PvaExcluded(region_code=link.region_code, pulse_version=link.pulse_version,
                                       reason="No Launch Room verdict is stored for the linked Studio version in this region."))
            continue
        row, label = found
        predictions.append(cmp.Prediction(
            region_code=link.region_code, pulse_version=link.pulse_version, version_id=link.version_id, studio_label=label,
            verdict_id=row.id, verdict=row.verdict, overall_score=row.overall_score, scoring_version=row.scoring_version,
            rule_version=row.rule_version, input_fingerprint=row.input_fingerprint, computed_at=row.computed_at,
            quick_read=_quick_read(row.inputs)))
    pairs, summaries, excluded = cmp.compare(predictions, loaded.rows, metric, pulse.REGION_NAMES)
    excluded = sorted([*excluded, *extra], key=lambda e: (e.region_code, e.pulse_version))
    slots = {(r.region_code, r.version_label) for r in loaded.rows}
    linked = {(link.region_code, link.pulse_version) for link in links}
    return v.PvaResult(
        **pulse._stamp(loaded), metric=metric, metric_label=cmp.metric_label(metric),  # type: ignore[arg-type]
        unit=BY_NAME[metric].unit, method=cmp.METHOD, pairs=pairs, summaries=summaries, excluded=excluded,
        unlinked=len(slots - linked), fingerprint=cmp.fingerprint(metric, loaded.dataset_version, pairs, excluded))


async def predicted_actual(user_id: UUID, campaign_id: UUID, metric: str) -> v.PvaResult:
    async with read_session() as s:
        await pulse._campaign(s, user_id, campaign_id)
        loaded = await pulse._load(s, campaign_id)
        return await build_result(s, campaign_id, loaded, metric)


# --- version links ------------------------------------------------------------------------------------------------------


def _region_order(code: str) -> tuple[int, str]:
    order = ["IN-MH", "IN-TN", "IN-KL", "IN-WB"]
    return (order.index(code) if code in order else len(order), code)


async def link_board(user_id: UUID, campaign_id: UUID) -> v.PvaLinkBoard:
    async with read_session() as s:
        await pulse._campaign(s, user_id, campaign_id)
        loaded = await pulse._load(s, campaign_id)
        links = {(r.region_code, r.pulse_version): r for r in (await s.execute(
            select(m.PulseVersionLink).where(m.PulseVersionLink.campaign_id == campaign_id))).scalars()}
        verdicts = await latest_verdicts(s, campaign_id)
        bare = {link.version_id for link in links.values()} - {k[1] for k in verdicts}  # linked, but no verdict stored yet
        labels = dict((await s.execute(select(m.VersionNode.id, m.VersionNode.label).where(m.VersionNode.id.in_(bare)))).all()) if bare else {}
    slots = []
    for region, version in sorted({(r.region_code, r.version_label) for r in loaded.rows}, key=lambda k: (_region_order(k[0]), k[1])):
        link = links.get((region, version))
        found = verdicts.get((region, link.version_id)) if link else None
        slots.append(v.PvaLinkSlot(
            region_code=region, region_name=pulse.REGION_NAMES.get(region, region), pulse_version=version,
            version_id=link.version_id if link else None, studio_label=found[1] if found else labels.get(link.version_id) if link else None,
            verdict=found[0].verdict if found else None, overall_score=found[0].overall_score if found else None))  # type: ignore[arg-type]
    candidates = [
        v.PvaCandidate(region_code=code, version_id=vid, studio_label=label, verdict=row.verdict,  # type: ignore[arg-type]
                       overall_score=row.overall_score, computed_at=row.computed_at)
        for (code, vid), (row, label) in sorted(verdicts.items(), key=lambda kv: (_region_order(kv[0][0]), kv[1][1]))
    ]
    return v.PvaLinkBoard(slots=slots, candidates=candidates)


async def set_link(user_id: UUID, campaign_id: UUID, body: v.PvaLinkSet) -> v.PvaLinkBoard:
    async with session() as s, s.begin():
        project = await pulse._campaign(s, user_id, campaign_id, writable=True)
        loaded = await pulse._load(s, campaign_id)
        if (body.region_code, body.pulse_version) not in {(r.region_code, r.version_label) for r in loaded.rows}:
            raise _bad("pulse_version", "That version did not run in that region in the Pulse series.")
        existing = (await s.execute(select(m.PulseVersionLink).where(
            m.PulseVersionLink.campaign_id == campaign_id, m.PulseVersionLink.region_code == body.region_code,
            m.PulseVersionLink.pulse_version == body.pulse_version))).scalar_one_or_none()
        if body.version_id is None:
            if existing is not None:
                await s.delete(existing)
        else:
            campaign = await s.get(m.Campaign, campaign_id)
            await node_in(s, campaign, body.version_id, "version_id")
            if existing is None:
                s.add(m.PulseVersionLink(
                    id=uuid4(), project_id=project.id, campaign_id=campaign_id, region_code=body.region_code,
                    pulse_version=body.pulse_version, version_id=body.version_id, created_by=user_id, updated_at=utcnow()))
            else:
                existing.version_id, existing.created_by, existing.updated_at = body.version_id, user_id, utcnow()
        await record_audit(
            s, action="pulse.version_link.set", target_type="campaign", target_id=str(campaign_id),
            workspace_id=project.workspace_id, actor_user_id=user_id,
            detail={"region": body.region_code, "pulse_version": body.pulse_version,
                    "version_id": str(body.version_id) if body.version_id else None})
    return await link_board(user_id, campaign_id)


# --- stored comparison snapshots ---------------------------------------------------------------------------------------


def _snapshot_view(row: m.PulseComparisonSnapshot, current: dict[str, str]) -> v.PvaSnapshot:
    return v.PvaSnapshot(
        id=row.id, metric=row.metric, method_version=row.method_version, fingerprint=row.fingerprint,  # type: ignore[arg-type]
        dataset_version=row.dataset_version, pair_count=row.pair_count, created_at=row.created_at,
        matches_current=current.get(row.metric) == row.fingerprint, result=v.PvaResult.model_validate(row.result))


async def save_snapshot(user_id: UUID, campaign_id: UUID, body: v.PvaSnapshotCreate) -> v.PvaSnapshot:
    """Store the comparison as it reads now. The same fingerprint as the newest snapshot of the metric returns that snapshot."""
    async with session() as s, s.begin():
        project = await pulse._campaign(s, user_id, campaign_id, writable=True)
        loaded = await pulse._load(s, campaign_id)
        result = await build_result(s, campaign_id, loaded, body.metric)
        latest = (await s.execute(select(m.PulseComparisonSnapshot).where(
            m.PulseComparisonSnapshot.campaign_id == campaign_id, m.PulseComparisonSnapshot.metric == body.metric)
            .order_by(m.PulseComparisonSnapshot.created_at.desc(), m.PulseComparisonSnapshot.id.desc()).limit(1))).scalar_one_or_none()
        if latest is not None and latest.fingerprint == result.fingerprint:
            return _snapshot_view(latest, {body.metric: result.fingerprint})
        row = m.PulseComparisonSnapshot(
            id=uuid4(), project_id=project.id, campaign_id=campaign_id, metric=body.metric, method_version=cmp.METHOD_VERSION,
            fingerprint=result.fingerprint, dataset_version=loaded.dataset_version, pair_count=len(result.pairs),
            inputs={
                "metric": body.metric, "method_version": cmp.METHOD_VERSION, "dataset_version": loaded.dataset_version,
                "pairs": [[p.region_code, p.pulse_version, str(p.version_id), str(p.predicted.verdict_id)] for p in result.pairs],
                "excluded": [e.model_dump(mode="json") for e in result.excluded]},
            result=result.model_dump(mode="json"), created_by=user_id, created_at=utcnow())
        s.add(row)
        await record_audit(
            s, action="pulse.comparison.snapshot", target_type="campaign", target_id=str(campaign_id),
            workspace_id=project.workspace_id, actor_user_id=user_id,
            detail={"metric": body.metric, "fingerprint": result.fingerprint, "pairs": len(result.pairs)})
        await s.flush()
        return _snapshot_view(row, {body.metric: result.fingerprint})


async def snapshots(user_id: UUID, campaign_id: UUID) -> v.PvaSnapshotList:
    async with read_session() as s:
        await pulse._campaign(s, user_id, campaign_id)
        rows = (await s.execute(select(m.PulseComparisonSnapshot).where(m.PulseComparisonSnapshot.campaign_id == campaign_id)
                                .order_by(m.PulseComparisonSnapshot.created_at.desc(), m.PulseComparisonSnapshot.id.desc()).limit(50))).scalars().all()
        current: dict[str, str] = {}
        if rows:
            try:
                loaded = await pulse._load(s, campaign_id)
                for metric in {r.metric for r in rows}:
                    current[metric] = (await build_result(s, campaign_id, loaded, metric)).fingerprint
            except Exception:  # the series is gone: nothing reproduces
                current = {}
    return v.PvaSnapshotList(items=[_snapshot_view(r, current) for r in rows])


# --- Fatigue Watch -------------------------------------------------------------------------------------------------------


async def _refresh_suggestions(
    s: AsyncSession, campaign_id: UUID, rows: list[tuple[str, str, v.FatigueRow, dict]],
) -> None:
    """Fill `refresh` for every row that is fatigued or wearing out: another running version, a Studio version, or a new variant."""
    verdicts = await latest_verdicts(s, campaign_id)
    links = {(r.region_code, r.pulse_version): r.version_id for r in (await s.execute(
        select(m.PulseVersionLink).where(m.PulseVersionLink.campaign_id == campaign_id))).scalars()}
    by_region: dict[str, list[tuple[str, v.FatigueRow, dict]]] = defaultdict(list)
    for region, version, row, ctx in rows:
        by_region[region].append((version, row, ctx))
    for region, version, row, ctx in rows:
        if not (row.status == "fatigued" or row.pattern == "wearing_out"):
            continue
        out: list[v.FatigueRefresh] = []
        own_ctr = ctx.get("recent_ctr")
        better = sorted(
            ((c["recent_ctr"], ver) for ver, other, c in by_region[region]
             if ver != version and other.status not in ("fatigued", "not_enough_data") and c.get("recent_ctr") is not None
             and own_ctr is not None and c["recent_ctr"] > own_ctr), reverse=True)
        if better:
            ctr, ver = better[0]
            out.append(v.FatigueRefresh(
                kind="pulse_version", label=ver, version_id=None, verdict=None, overall_score=None,
                detail=f"{ver} is running in {row.region_name} at a CTR of {ctr * 100:.2f}% in the same weeks, against {own_ctr * 100:.2f}% here. Rotate more of the spend to it."))
        own_link = links.get((region, version))
        studio = sorted(
            ((row_v.verdict, -(row_v.overall_score or 0.0), label, vid, row_v) for (code, vid), (row_v, label) in verdicts.items()
             if code == region and vid != own_link and row_v.verdict != "rethink"),
            key=lambda t: (VERDICT_RANK[t[0]], t[1]))
        for verdict, _, label, vid, row_v in studio[:2]:
            score = f", score {row_v.overall_score:.0f}" if row_v.overall_score is not None else ""
            out.append(v.FatigueRefresh(
                kind="studio_version", label=label, version_id=vid, verdict=verdict, overall_score=row_v.overall_score,  # type: ignore[arg-type]
                detail=f"Launch Room says {verdict.capitalize()}{score}. Run it in {row.region_name} in place of {version}."))
        if not out:
            out.append(v.FatigueRefresh(
                kind="new_variant", label=f"A new variant for {row.region_name}", version_id=None, verdict=None, overall_score=None,
                detail=f"No other version is ready for {row.region_name}. Make a new variant in Creative Studio (a Tweak Chip on the hook or a fresh transcreation), then run it through Quick Read and the Readiness Board."))
        row.refresh = out


async def fatigue(
    user_id: UUID, campaign_id: UUID, cfg: fat.FatigueConfig, *, region: str | None, version: str | None,
) -> v.FatigueReport:
    async with read_session() as s:
        await pulse._campaign(s, user_id, campaign_id)
        loaded = await pulse._load(s, campaign_id)
        pulse._filter(loaded.rows, region, version)  # an unknown region or version is a 422, like the rest of Pulse
        assessed = fat.assess(loaded.rows, cfg, pulse.REGION_NAMES)
        await _refresh_suggestions(s, campaign_id, assessed)
    regions: dict[str, list[v.FatigueRow]] = defaultdict(list)
    for code, ver, row, _ in assessed:
        if (region is None or code == region) and (version is None or ver == version):
            regions[code].append(row)
    out = []
    for code in sorted(regions, key=_region_order):
        rows = regions[code]
        count = lambda status: sum(r.status == status for r in rows)  # noqa: E731
        out.append(v.FatigueRegion(
            region_code=code, region_name=pulse.REGION_NAMES.get(code, code), fatigued=count("fatigued"), watch=count("watch"),
            healthy=count("healthy"), not_enough_data=count("not_enough_data"), rows=rows))
    return v.FatigueReport(
        **pulse._stamp(loaded),
        thresholds=v.FatigueThresholds(
            ctr_decline_pct=cfg.ctr_decline_pct, view_rate_decline_pct=cfg.view_rate_decline_pct,
            frequency_threshold=cfg.frequency_threshold),
        regions=out, method=FATIGUE_METHOD)


FATIGUE_METHOD = [
    "Each version is read in each region, platforms together, through four signals: CTR and view rate against the version's own first week, frequency, and how little new reach each impression buys in the last week.",
    "A fall in CTR or view rate counts only when it is at least twice the day-to-day noise of that series. Provisional days are never used.",
    "Fatigue needs a response signal and an exposure signal together. Response alone, or exposure alone, is Watch, with the reason it falls short.",
    "A version that was already far below its region's average in the first week and does not decay is static underperformance, not wear-out.",
]
