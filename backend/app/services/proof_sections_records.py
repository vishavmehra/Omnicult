"""Proof Report providers for the records other streams write: Creative Studio versions and transcreations, Creative
X-Ray scenes, Audience Lab runs and Risk Check findings, Launch Room verdicts and approvals, and Live Pulse metrics.

Every provider reads stored rows only (no model, no network) and reports what is missing as missing. Labels stay honest:
Audience Lab results are synthetic, model readings are interpretations, rule outputs are calculated, recorded decisions
are observed, and Pulse figures from the generated sample dataset are never presented as real performance.

Imported at the end of `proof_sections` (which owns the registry); importing this module registers the providers.
"""

from collections.abc import Iterable
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from app.db import models as m
from app.db.session import read_session
from app.schemas import audience as aud
from app.schemas.common import Anchor
from app.schemas.proof import (
    ApprovalItem,
    ApprovalsContent,
    AudienceResultItem,
    AudienceResultsContent,
    CreativeVersionItem,
    CreativeVersionsContent,
    KindLabel,
    LivePerformanceContent,
    LivePerformanceItem,
    ReadinessContent,
    ReadinessVerdictRef,
    RiskFindingItem,
    RiskFindingsContent,
    TranscreationContent,
    TranscreationItem,
    XRayContent,
    XRayFinding,
)
from app.services.proof_sections import Missing, Provided, SectionContext, provider
from app.services.pulse_metrics import BY_NAME, SeriesRow, values_of

MAX_VERSIONS = 200
MAX_XRAY_FINDINGS = 300
MAX_TRANSCREATION_LINES = 100
MAX_AUDIENCE_ITEMS = 30
MAX_RISK_FINDINGS = 300
MAX_VERDICTS = 200
MAX_APPROVALS = 100
USABLE = ("completed", "partial")
HEADLINE_METRICS = ("impressions", "spend", "ctr", "cpm", "cpa", "roas")
DECISIONS = {"approve": "approved", "reject": "rejected", "request_changes": "changes_requested"}
SOURCE_NAMES = {"sample": "Live Pulse dataset", "test_account": "connected test account", "live": "connected account"}


def _uuids(values: Iterable[Any]) -> list[UUID]:
    """The valid UUIDs among stored id strings (a stored list is JSON; one bad entry must not lose the section)."""
    found: list[UUID] = []
    for value in values or []:
        try:
            found.append(UUID(str(value)))
        except ValueError:
            continue
    return found


def _region_codes(ctx: SectionContext) -> list[str]:
    return [r.code for r in ctx.regions]


def _in_regions(ctx: SectionContext, codes: Iterable[str | None]) -> bool:
    """True when no target region is set, or one of `codes` is a target region."""
    targets = _region_codes(ctx)
    return not targets or bool(set(targets) & {c for c in codes if c})


# --- creative_versions --------------------------------------------------------------------------------------


def _compare_versions(root: m.VersionNode, newest: m.VersionNode) -> str | None:
    if root.id == newest.id:
        return None
    before = {e["id"]: e.get("value") for e in root.elements}
    after = {e["id"]: e.get("value") for e in newest.elements}
    changed = sorted(i for i in before.keys() & after.keys() if before[i] != after[i])
    added, removed = sorted(after.keys() - before.keys()), sorted(before.keys() - after.keys())
    detail = f" ({', '.join(changed[:8])}{', ...' if len(changed) > 8 else ''})" if changed else ""
    return (
        f"The newest version \"{newest.label}\" compared with the original \"{root.label}\": {len(changed)} element"
        f"{'s' if len(changed) != 1 else ''} changed{detail}, {len(added)} added, {len(removed)} removed. "
        "Computed by comparing the stored element values."
    )


@provider("creative_versions")
async def creative_versions(ctx: SectionContext) -> Provided | Missing:
    async with read_session() as s:
        where = m.VersionNode.campaign_id == ctx.campaign.id
        total = await s.scalar(select(func.count()).select_from(m.VersionNode).where(where)) or 0
        if not total:
            return Missing("No creative version is recorded for this campaign. Create one in Creative Studio.")
        newest_first = list((await s.execute(
            select(m.VersionNode).where(where).order_by(m.VersionNode.created_at.desc(), m.VersionNode.id.desc()).limit(MAX_VERSIONS)
        )).scalars())
        root = (await s.execute(
            select(m.VersionNode).where(where, m.VersionNode.parent_id.is_(None))
            .order_by(m.VersionNode.created_at, m.VersionNode.id).limit(1)
        )).scalar_one_or_none()
        op_ids = [n.operation_id for n in newest_first if n.operation_id]
        operations = {
            o.id: o for o in (await s.execute(select(m.Operation).where(m.Operation.id.in_(op_ids)))).scalars()
        } if op_ids else {}
    nodes = list(reversed(newest_first))
    items = []
    for node in nodes:
        op = operations.get(node.operation_id) if node.operation_id else None
        items.append(CreativeVersionItem(
            version_id=node.id, label=node.label, parent_version_id=node.parent_id, operation=op.kind if op else None,
            actor=node.actor, created_at=node.created_at,  # type: ignore[arg-type]
            summary=op.reason if op else f"Original with {len(node.elements)} element{'s' if len(node.elements) != 1 else ''}.",
            claim_ids=_uuids(op.claim_ids) if op else [], kind="interpretation" if node.actor == "ai" else "observed",
        ))
    labels = []
    if any(i.kind == "observed" for i in items):
        labels.append(KindLabel(kind="observed", applies_to=(
            "Versions made by people are recorded as entered: who made them, when, and the reason given. "
            "They are the team's own work, not verified facts.")))
    if any(i.kind == "interpretation" for i in items):
        labels.append(KindLabel(kind="interpretation", applies_to=(
            "Versions written by an AI operation (transcreation, Tweak Chips) are model-generated proposals for people "
            "to judge. Unless a person reviewed them they are not reviewed by a native speaker.")))
    newest = nodes[-1]
    return Provided(
        CreativeVersionsContent(
            versions=items, comparison_summary=_compare_versions(root, newest) if root is not None else None,
            truncated=total > len(nodes)),
        labels,
    )


# --- xray_findings ------------------------------------------------------------------------------------------


def _scene_findings(creative: m.CreativeAsset, scene: m.CreativeScene) -> list[XRayFinding]:
    p = scene.payload or {}
    anchor = Anchor(scene_id=str(scene.id), start_ms=scene.start_ms, end_ms=scene.end_ms)

    def finding(key: str, observation: str, kind: str, field: str, claim_ids: list[UUID] | None = None) -> XRayFinding:
        return XRayFinding(
            id=f"{scene.id}:{key}", observation=observation, anchor=anchor, claim_ids=claim_ids or [], confidence=None,
            kind=kind, field=field, creative_label=creative.label)  # type: ignore[arg-type]

    out = [finding(f"text:{i}", f"On-screen text: \"{t.get('text', '')}\"", "observed", "on_screen_text")
           for i, t in enumerate(p.get("on_screen_text", []))]
    out += [finding(f"claim:{i}", f"The creative states: \"{c.get('text', '')}\" (quoted from {str(c.get('source', 'the scene')).replace('_', ' ')}, found verbatim).",
                    "observed", "ad_claim") for i, c in enumerate(p.get("claims", []))]
    out += [finding(o.get("id", f"obs{i}"), o.get("text", ""), "interpretation", "cultural_observation", _uuids(o.get("claim_ids", [])))
            for i, o in enumerate(p.get("cultural_observations", []))]
    out += [finding(r.get("id", f"read{i}"), r.get("text", ""), "interpretation", "cultural_interpretation", _uuids(r.get("claim_ids", [])))
            for i, r in enumerate(p.get("cultural_interpretations", []))]
    return out


@provider("xray_findings")
async def xray_findings(ctx: SectionContext) -> Provided | Missing:
    async with read_session() as s:
        creatives = list((await s.execute(
            select(m.CreativeAsset).where(m.CreativeAsset.campaign_id == ctx.campaign.id)
            .order_by(m.CreativeAsset.created_at, m.CreativeAsset.id)
        )).scalars())
        if not creatives:
            return Missing("No creative has been uploaded and read with Creative X-Ray for this campaign.")
        analysed = [c for c in creatives if c.current_run_id is not None]
        if not analysed:
            return Missing("Creative X-Ray has not produced scenes for this campaign's creatives (the analysis may be running or may have failed).")
        in_scope = [c for c in analysed if _in_regions(ctx, [c.region_code]) or c.region_code is None]
        if not in_scope:
            return Missing("No analysed creative is read for the target regions.")
        scenes = list((await s.execute(
            select(m.CreativeScene).where(or_(*[
                and_(m.CreativeScene.creative_asset_id == c.id, m.CreativeScene.run_id == c.current_run_id) for c in in_scope
            ])).order_by(m.CreativeScene.creative_asset_id, m.CreativeScene.position, m.CreativeScene.id)
        )).scalars())
    by_id = {c.id: c for c in in_scope}
    findings: list[XRayFinding] = []
    for scene in scenes:
        findings += _scene_findings(by_id[scene.creative_asset_id], scene)
    if not findings:
        return Missing("The current X-Ray analysis recorded no on-screen text, claim or cultural reading.")
    labels = []
    if any(f.kind == "observed" for f in findings):
        labels.append(KindLabel(kind="observed", applies_to=(
            "On-screen text and quoted claims were kept only when code found them verbatim in the frame observations or "
            "the transcript. A vision or speech model produced those observations; they can still be wrong.")))
    if any(f.kind == "interpretation" for f in findings):
        labels.append(KindLabel(kind="interpretation", applies_to=(
            "Cultural observations and readings are model-generated. A reading is a hypothesis for people to judge, not a "
            "fact, and a claim link is shown only where one is stored.")))
    return Provided(
        XRayContent(
            findings=findings[:MAX_XRAY_FINDINGS], creatives=len(in_scope), scenes=len(scenes),
            truncated=len(findings) > MAX_XRAY_FINDINGS),
        labels,
    )


# --- transcreation ------------------------------------------------------------------------------------------


@provider("transcreation")
async def transcreation(ctx: SectionContext) -> Provided | Missing:
    async with read_session() as s:
        operations = list((await s.execute(
            select(m.Operation).where(m.Operation.campaign_id == ctx.campaign.id, m.Operation.kind == "transcreate")
            .order_by(m.Operation.created_at.desc(), m.Operation.id.desc())
        )).scalars())
    operations = [o for o in operations if _in_regions(ctx, [(o.params or {}).get("region_code")])]
    if not operations:
        return Missing("No transcreation has been run for this campaign" + (" in the target regions." if ctx.regions else "."))
    items: list[TranscreationItem] = []
    total = 0
    for op in operations:
        params = op.params or {}
        for index, line in enumerate(params.get("lines", [])):
            total += 1
            if len(items) >= MAX_TRANSCREATION_LINES:
                continue
            issues = [] if line.get("passed") else ["Not applied to a version: the line failed a code check."]
            items.append(TranscreationItem(
                id=f"{op.id}:{line.get('element_id', index)}", region_code=params.get("region_code") or "",
                language=params.get("language"), source_version_id=op.source_version_id, result_version_id=op.result_version_id,
                summary=f"\"{line.get('source_text', '')}\" became \"{line.get('regional_copy', '')}\". {line.get('explanation', '')}".strip(),
                back_translation=line.get("back_translation"), glossary_issues=issues + list(line.get("problems", [])),
                claim_ids=_uuids(line.get("claim_ids", [])), kind="interpretation"))
    if not items:
        return Missing("The transcreation operations of this campaign recorded no lines.")
    return Provided(
        TranscreationContent(items=items, truncated=total > len(items)),
        [
            KindLabel(kind="interpretation", applies_to=(
                "The regional copy, its English back-translation and the explanations were written by one model run. The back-"
                "translation is not an independent check. Not reviewed by a native speaker unless a person says so.")),
            KindLabel(kind="calculated", applies_to=(
                "Brand Glossary and script checks (protected terms kept, prohibited terms absent, expected script) are "
                "computed in code on the regional copy and on its back-translation.")),
        ],
    )


# --- risk_findings ------------------------------------------------------------------------------------------


@provider("risk_findings")
async def risk_findings(ctx: SectionContext) -> Provided | Missing:
    async with read_session() as s:
        runs = list((await s.execute(
            select(m.AudienceRun).where(
                m.AudienceRun.campaign_id == ctx.campaign.id, m.AudienceRun.kind == "risk_check", m.AudienceRun.status.in_(USABLE))
            .order_by(m.AudienceRun.created_at.desc(), m.AudienceRun.id.desc())
        )).scalars())
        newest: dict[str, m.AudienceRun] = {}
        for run in runs:  # the newest usable run of each region
            key = (run.region_codes or [""])[0]
            if key not in newest and _in_regions(ctx, run.region_codes or []):
                newest[key] = run
        if not newest:
            return Missing("No completed Risk Check exists for this campaign" + (" in the target regions." if ctx.regions else "."))
        chosen = sorted(newest.values(), key=lambda r: (r.created_at, str(r.id)))
        rows = list((await s.execute(
            select(m.RiskFindingRow).where(m.RiskFindingRow.run_id.in_([r.id for r in chosen]))
            .order_by(m.RiskFindingRow.run_id, m.RiskFindingRow.ordinal)
        )).scalars())
    region_of = {r.id: (r.region_codes or [None])[0] for r in chosen}
    created = {r.id: r.created_at for r in chosen}
    rows.sort(key=lambda f: (created[f.run_id], str(f.run_id), f.ordinal))
    items = [
        RiskFindingItem(
            id=str(f.id), severity=f.severity, category=f.category, description=f.observation,  # type: ignore[arg-type]
            anchor=Anchor.model_validate(f.anchor), status=f.status, region_code=region_of[f.run_id], run_id=f.run_id,
            ad_code_ref="; ".join(f"{a.get('document', '')} {a.get('clause', '')}".strip() for a in f.ad_codes) or None,
            kind="calculated" if f.source == "deterministic_check" else "interpretation", interpretation=f.interpretation,
            suggested_fix=f.suggested_fix, blocks_go=f.blocks_go, claim_ids=_uuids(f.claim_ids))
        for f in rows[:MAX_RISK_FINDINGS]
    ]
    labels = [KindLabel(kind="calculated", applies_to=(
        f"Severity and the blocks-Go flag are computed by {rows[0].rules_version if rows else 'risk-rules'} from fixed rules, "
        "never by the model. Findings from deterministic checks are calculated."))]
    if any(i.kind == "interpretation" for i in items):
        labels.append(KindLabel(kind="interpretation", applies_to=(
            "Why a finding may matter, and the suggested fix, are a model's interpretation. Quotes were verified in code.")))
    return Provided(
        RiskFindingsContent(findings=items, disclaimer=aud.NOT_LEGAL_REVIEW, run_ids=[r.id for r in chosen]), labels)


# --- audience_results ---------------------------------------------------------------------------------------


def _model_ids(run: m.AudienceRun) -> list[str]:
    return list(dict.fromkeys(
        st["model_id"] for st in run.steps or [] if st.get("model_id") and st.get("provider") not in (None, "omnicult", "fixture")))


def _tally(counts: dict[str, int]) -> str:
    return ", ".join(f"{n} {name}" for name, n in counts.items() if n) or "no reactions"


def _limits(run: m.AudienceRun, n: int, models: list[str]) -> list[str]:
    who = f"one model ({models[0]})" if len(models) == 1 else "the model"
    notes = [f"{n} respondent{'s' if n != 1 else ''} generated by {who}. They share its biases and are not independent human observations."]
    return list(dict.fromkeys(notes + list(run.limitations or [])))


def _run_item(run: m.AudienceRun) -> AudienceResultItem | None:
    summary = (run.result or {}).get("summary")
    if not summary:
        return None
    models, region = _model_ids(run), (run.region_codes[0] if len(run.region_codes or []) == 1 else None)
    if run.kind == "quick_read":
        s = aud.QuickReadSummary.model_validate(summary)
        n, survival = s.sentiment.denominator, s.message_survival
        text = (f"{survival.understood} of {survival.denominator} respondents restated the intended message "
                f"({survival.partial} partly, {survival.misunderstood} not). Reactions: {_tally(dict(s.sentiment.counts))}.")
        dims = [d for d in (s.dimension_results.clarity, s.dimension_results.brand_fidelity,
                            s.dimension_results.cultural_relevance, s.dimension_results.cultural_risk) if d and d.disagreement]
        disagreement = ("The respondents split on " + ", ".join(d.dimension.replace("_", " ") for d in dims) + ".") if dims else None
        method = "quick_read"
    else:
        study = aud.StudySummary.model_validate(summary)
        n = study.overall.denominator
        text = f"{n} interviews completed across {len(run.region_codes or [])} state(s). Reactions: {_tally(dict(study.overall.counts))}."
        disagreement = ("Model reading of group differences: " + " ".join(study.group_differences[:2])) if study.group_differences else None
        method = "audience_study"
    return AudienceResultItem(
        id=str(run.id), method=method, region_code=region, respondent_count=n, summary=text,  # type: ignore[arg-type]
        disagreement=disagreement, limitations=_limits(run, n, models), run_id=run.id, mode=run.mode,  # type: ignore[arg-type]
        model_ids=models, created_at=run.created_at)


def _question_item(q: m.PanelQuestion, run: m.AudienceRun) -> AudienceResultItem:
    counts = {k: int(v) for k, v in (q.stance or {}).get("counts", {}).items()}
    answered = int((q.stance or {}).get("denominator", 0))
    models = _model_ids(run)
    spread = sum(1 for n in counts.values() if n) > 1
    return AudienceResultItem(
        id=str(q.id), method="ask_the_panel", region_code=(run.region_codes[0] if len(run.region_codes or []) == 1 else None),
        respondent_count=answered, summary=f"Asked the {q.target_kind}: \"{q.question}\". Answers: {_tally(counts)}.",
        disagreement=("Model reading of how the answers differ: " + q.summaries[0]) if spread and q.summaries else None,
        limitations=list(dict.fromkeys(_limits(run, answered, models) + list(q.limitations or []))), run_id=run.id,
        mode=q.mode, model_ids=models, created_at=q.created_at)  # type: ignore[arg-type]


@provider("audience_results")
async def audience_results(ctx: SectionContext) -> Provided | Missing:
    async with read_session() as s:
        runs = list((await s.execute(
            select(m.AudienceRun).where(
                m.AudienceRun.campaign_id == ctx.campaign.id, m.AudienceRun.kind.in_(("quick_read", "audience_study")),
                m.AudienceRun.status.in_(USABLE)).order_by(m.AudienceRun.created_at.desc(), m.AudienceRun.id.desc())
        )).scalars())
        runs = [r for r in runs if _in_regions(ctx, r.region_codes or [])]
        by_id = {r.id: r for r in runs}
        questions = list((await s.execute(
            select(m.PanelQuestion).where(m.PanelQuestion.run_id.in_(list(by_id)))
            .order_by(m.PanelQuestion.created_at.desc(), m.PanelQuestion.id.desc())
        )).scalars()) if by_id else []
    items = [i for i in (_run_item(r) for r in runs) if i is not None] + [_question_item(q, by_id[q.run_id]) for q in questions]
    if not items:
        return Missing("No Quick Read, Audience Study or panel question has been completed for this campaign"
                       + (" in the target regions." if ctx.regions else "."))
    items.sort(key=lambda i: (i.created_at, i.id), reverse=True)
    return Provided(
        AudienceResultsContent(results=items[:MAX_AUDIENCE_ITEMS], truncated=len(items) > MAX_AUDIENCE_ITEMS),
        [KindLabel(kind="synthetic", applies_to=(
            "Counts are tallies over the panel's responses, and respondents that share one model do not confirm each other."))],
    )


# --- readiness ----------------------------------------------------------------------------------------------


@provider("readiness")
async def readiness(ctx: SectionContext) -> Provided | Missing:
    async with read_session() as s:
        rows = (await s.execute(
            select(m.ReadinessVerdict, m.Region.code).join(m.Region, m.Region.id == m.ReadinessVerdict.region_id)
            .where(m.ReadinessVerdict.campaign_id == ctx.campaign.id)
            .order_by(m.ReadinessVerdict.computed_at.desc(), m.ReadinessVerdict.id.desc()).limit(MAX_VERDICTS)
        )).all()
    newest: dict[tuple[str, UUID], tuple[m.ReadinessVerdict, str]] = {}
    for row, code in rows:  # the newest verdict of each region and version
        newest.setdefault((code, row.version_id), (row, code))
    ordered = list(newest.values())
    targets = [x for x in ordered if _in_regions(ctx, [x[1]])] if ctx.regions else ordered
    if not ordered:
        return Missing("No readiness verdict has been computed for this campaign.")
    if not targets:
        return Missing("No readiness verdict has been computed for the target regions.")
    head, code = targets[0]
    result = head.result or {}
    issue = result.get("highest_priority_issue") or {}
    others = [
        ReadinessVerdictRef(verdict_id=r.id, region_code=c, version_id=r.version_id, verdict=r.verdict,  # type: ignore[arg-type]
                            main_reason=r.main_reason, computed_at=r.computed_at)
        for r, c in ordered if r.id != head.id
    ]
    return Provided(
        ReadinessContent(
            verdict=head.verdict, main_reason=head.main_reason, highest_priority_issue=issue.get("summary"),  # type: ignore[arg-type]
            next_action=result.get("next_action", ""), open_conflicts=len(result.get("open_conflicts", [])),
            confidence_limitations=list(result.get("confidence_limitations", [])), rule_version=head.rule_version,
            verdict_id=head.id, region_code=code, version_id=head.version_id, computed_at=head.computed_at, other_verdicts=others),
        [KindLabel(kind="calculated", applies_to=(
            f"The verdict, reasons and issues are computed by fixed rules ({head.rule_version}) from stored observations; no "
            "model decides them. A verdict is a recommendation, not an approval."))],
    )


# --- approvals ----------------------------------------------------------------------------------------------


@provider("approvals")
async def approvals(ctx: SectionContext) -> Provided | Missing:
    async with read_session() as s:
        stmt = (
            select(m.Approval, m.Region.code, m.User.display_name)
            .join(m.Region, m.Region.id == m.Approval.region_id).join(m.User, m.User.id == m.Approval.decided_by)
            .where(m.Approval.campaign_id == ctx.campaign.id)
        )
        if ctx.regions:
            stmt = stmt.where(m.Region.code.in_(_region_codes(ctx)))
        rows = (await s.execute(stmt.order_by(m.Approval.decided_at.desc(), m.Approval.id.desc()).limit(MAX_APPROVALS))).all()
    if not rows:
        return Missing("No human approval or decision is recorded for this campaign" + (
            " in the target regions" if ctx.regions else "") + ". A readiness verdict is a recommendation, not an approval.")
    return Provided(
        ApprovalsContent(approvals=[
            ApprovalItem(
                id=str(a.id), version_id=a.version_id, approver_user_id=a.decided_by, role=None,
                decision=DECISIONS[a.decision], note=a.reason, decided_at=a.decided_at,  # type: ignore[arg-type]
                region_code=code, approver_name=name, verdict_at_decision=a.verdict_at_decision,  # type: ignore[arg-type]
                overrides_recommendation=a.overrides_recommendation)
            for a, code, name in rows]),
        [KindLabel(kind="observed", applies_to=(
            "Decisions are recorded actions by named people, with the reason they gave and the readiness recommendation in "
            "force. The role held at decision time is not recorded."))],
    )


# --- live_performance ---------------------------------------------------------------------------------------


@provider("live_performance")
async def live_performance(ctx: SectionContext) -> Provided | Missing:
    async with read_session() as s:
        stmt = select(
            m.MetricSeries.source_kind, m.MetricSeries.dataset_version, m.MetricSeries.day, m.MetricSeries.platform,
            m.MetricSeries.channel, m.MetricSeries.version_label, m.MetricSeries.region_code, m.MetricSeries.metric,
            m.MetricSeries.value, m.MetricSeries.provisional,
        ).where(m.MetricSeries.campaign_id == ctx.campaign.id)
        if ctx.regions:
            stmt = stmt.where(m.MetricSeries.region_code.in_(_region_codes(ctx)))
        found = (await s.execute(stmt.order_by(m.MetricSeries.day, m.MetricSeries.id))).all()
    if not found:
        return Missing(
            "No performance data is loaded for this campaign" + (" in the target regions" if ctx.regions else "")
            + ". Load the dataset in Live Pulse.")
    groups: dict[tuple[str, str, str], list[SeriesRow]] = {}
    versions: dict[str, str] = {}
    for kind, dataset, *row in found:  # one group per source, region and creative version: versions are never blended
        groups.setdefault((kind, row[4], row[3]), []).append(SeriesRow(*row))
        versions[kind] = dataset
    items: list[LivePerformanceItem] = []
    for (kind, region, version), rows in sorted(groups.items()):
        start, end = min(r.day for r in rows), max(r.day for r in rows)
        results = values_of(HEADLINE_METRICS, rows, start, end)
        for name in HEADLINE_METRICS:
            value, provisional = results[name]
            if value is None:
                continue  # a ratio with no denominator is left out, never shown as 0
            definition = BY_NAME[name]
            items.append(LivePerformanceItem(
                region_code=region, version_label=version, metric=f"{definition.label} [{definition.unit}]", value=round(value, 6),
                period=_period(start, end), provisional=provisional,
                source=f"{SOURCE_NAMES[kind]}, dataset {versions[kind]}",
                kind="synthetic" if kind == "sample" else "calculated" if definition.kind == "calculated" else "observed"))
    if not items:
        return Missing("The stored performance rows have no headline metric with a value.")
    sample = any(k == "sample" for k, _, _ in groups)
    labels = []
    if sample:
        labels.append(KindLabel(kind="synthetic", applies_to=(
            "Figures from the Live Pulse dataset, generated by code rather than a model.")))
    if any(i.kind == "observed" for i in items):
        labels.append(KindLabel(kind="observed", applies_to="Base metrics as reported by the connected account, with their period and provisional flag."))
    if any(i.kind == "calculated" for i in items):
        labels.append(KindLabel(kind="calculated", applies_to="Ratios (for example CTR) computed in code from summed base metrics of the connected account."))
    return Provided(
        LivePerformanceContent(
            items=items, sample_data=sample, dataset_version=versions.get("sample") if sample else None,
            note="Figures from the Live Pulse dataset." if sample else "Figures are as stored from the connected account."),
        labels,
    )


def _period(start: date, end: date) -> str:
    return f"{start.isoformat()} to {end.isoformat()}"
