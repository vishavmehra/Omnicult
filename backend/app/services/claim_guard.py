"""Claim Guard (feature 27): claims in a version's copy, graded in code and held for a person's review.

A check always starts with the wording rules (`app.studio.claimguard`): no model, no cost. On request, and only through the
gateway, a model may add a second pass for implied claims; every proposal is verified against the element it quotes and is
tagged as a model interpretation. Each finding is checked against the Brand Kit claims policy, the evidence the campaign
holds (the Campaign Brief and the region's claims) and the ASCI ad-code index, and its severity comes from fixed rules.

A check is stored, so a review and a report can point at what was seen. A person's decision about a finding is stored apart,
keyed by version and finding, so running the check again never loses it. Nothing here is legal clearance: it is a warning
and review-support system, and `review_complete` only says that every finding has been looked at by a person.
"""

import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents import claim_guard as agent
from app.agents._common import norm
from app.analytics.risk_rules import AppliedRule, claim_features
from app.core.errors import ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.llm.gateway import LLMError
from app.reference.ad_codes import entries_by_id
from app.schemas import studio_t3 as t
from app.schemas.audience import AdCodeRef, AppliedRuleView
from app.schemas.common import ErrorDetail
from app.services import desk
from app.services import studio_context as ctx
from app.services.ai_guard import guarded_ai_call
from app.services.audit import record_audit
from app.services.common import not_found, paginate, touch
from app.services.studio_t3_common import anchor_of, scene_timings, text_of
from app.services.versions import campaign_for, node_in
from app.studio import claimguard as cg
from app.workflows.risk_check import locate

logger = logging.getLogger("omnicult.claim_guard")
LIMITATIONS = [
    "Claim Guard is a warning and review aid. It is not legal clearance, an ASCI ruling or a statement that any wording is allowed.",
    "Wording rules match words, so a person decides whether a match is really a claim. Rules cover English, Hindi, Marathi, Tamil, Malayalam and Bengali only.",
    "Evidence listed beside a claim is related evidence the campaign holds. A person decides whether it covers the exact wording.",
    cg.INDEX_NOTE,
]
MODEL_LIMITATION = "A model reading is an interpretation. Code verified its quote in the element; whether it is a claim is the model's reading."


# --- views --------------------------------------------------------------------------------------------------------


def _review_view(row: m.ClaimGuardReview) -> t.ClaimGuardReview:
    return t.ClaimGuardReview(finding_key=row.finding_key, decision=row.decision, note=row.note, reviewed_by=row.reviewed_by, reviewed_at=row.reviewed_at)  # type: ignore[arg-type]


def _counts(findings: list[t.ClaimGuardFinding]) -> t.ClaimGuardCounts:
    reviewed = sum(f.review is not None for f in findings)
    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    return t.ClaimGuardCounts(
        total=len(findings), high=sum(f.severity == "high" for f in findings), medium=sum(f.severity == "medium" for f in findings),
        low=sum(f.severity == "low" for f in findings), reviewed=reviewed, unreviewed=len(findings) - reviewed,
        blocks_go=sum(f.blocks_go and (f.review is None or f.review.decision == "revise") for f in findings), by_kind=by_kind,
        review_complete=reviewed == len(findings))


def _findings(row: m.ClaimGuardCheck, reviews: dict[str, m.ClaimGuardReview]) -> list[t.ClaimGuardFinding]:
    out = []
    for raw in row.result["findings"]:
        review = reviews.get(raw["key"])
        out.append(t.ClaimGuardFinding.model_validate({**raw, "review": _review_view(review).model_dump(mode="json") if review else None}))
    return out


def _summary(row: m.ClaimGuardCheck, findings: list[t.ClaimGuardFinding]) -> dict[str, Any]:
    return dict(
        id=row.id, campaign_id=row.campaign_id, version_id=row.version_id, region_code=row.region_code, language=row.language, mode=row.mode,
        rules_version=row.rules_version, counts=_counts(findings), created_by=row.created_by, created_at=row.created_at)


async def _reviews(s: Any, version_id: UUID) -> dict[str, m.ClaimGuardReview]:
    rows = (await s.execute(select(m.ClaimGuardReview).where(m.ClaimGuardReview.version_id == version_id))).scalars()
    return {r.finding_key: r for r in rows}


def to_check(row: m.ClaimGuardCheck, reviews: dict[str, m.ClaimGuardReview]) -> t.ClaimGuardCheck:
    findings = _findings(row, reviews)
    return t.ClaimGuardCheck(
        **_summary(row, findings), findings=findings, texts_checked=row.result["texts_checked"],
        policy=t.ClaimGuardPolicyView.model_validate(row.result["policy"]),
        model=t.ClaimGuardModelRun.model_validate(row.model) if row.model else None, limitations=row.result["limitations"])


def _finding(draft: cg.Draft, element: dict[str, Any], timings: dict[str, Any]) -> dict[str, Any]:
    index = entries_by_id()
    refs = [AdCodeRef(id=e.id, document=e.document, clause=e.clause, title=e.title, url=e.url, excerpt=e.excerpt) for i in draft.ad_code_ids if (e := index.get(i))]
    return t.ClaimGuardFinding(
        key=draft.key, element_id=draft.element_id, element_kind=element["kind"], kind=draft.kind, source=draft.source,  # type: ignore[arg-type]
        rule_id=draft.rule_id, quote=draft.quote, start=draft.start, end=draft.end, phrase=draft.phrase, anchor=anchor_of(element, timings),
        severity=draft.severity, blocks_go=draft.blocks_go, confidence=draft.confidence, severity_rules=[_rule_view(r) for r in draft.rules],
        policy=t.ClaimGuardPolicy.model_validate(draft.policy), evidence=t.ClaimGuardEvidence.model_validate(draft.evidence),
        basis=t.ClaimGuardBasis.model_validate(draft.basis), ad_codes=refs, explanation=draft.explanation,
        limitations=[*draft.limitations, *([MODEL_LIMITATION] if draft.source == "model" else [])], review=None,
    ).model_dump(mode="json")


def _rule_view(rule: AppliedRule) -> AppliedRuleView:
    return AppliedRuleView(rule=rule.rule, effect=rule.effect, reason=rule.reason)


# --- what a check reads ---------------------------------------------------------------------------------------------------


async def _policy(user_id: UUID, project_id: UUID) -> cg.PolicyInput:
    kit = await desk.get_brand_kit(user_id, project_id)
    return cg.PolicyInput(forbidden=kit.design.claims_policy.forbidden, allowed=kit.design.claims_policy.allowed, prohibited_terms=kit.prohibited_terms)


async def _price(user_id: UUID, campaign_id: UUID) -> tuple[float | None, str | None]:
    """The product price the Campaign Brief states, if it does."""
    content = (await desk.get_brief(user_id, campaign_id)).content
    price = content.product.price if content.product else None
    return (price.amount, price.currency) if price else (None, None)


# --- the check ------------------------------------------------------------------------------------------------------------


async def run_check(user_id: UUID, campaign_id: UUID, body: t.ClaimGuardRun) -> t.ClaimGuardCheck:
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        node = await node_in(s, campaign, body.version_id, "version_id")
        elements = [dict(e) for e in node.elements]
        region_claims: list[dict[str, Any]] = []
        region_name = None
        if node.region_code:
            try:
                region = await ctx.region_named(s, node.region_code)
                region_claims, region_name = await ctx.region_claims(s, project, region), region.name
            except ValidationFailed:
                pass  # a version whose region is not in the reference list is checked without region evidence
        timings = await scene_timings(s, campaign.id, elements)
        project_mode, project_id = project.mode, project.id
    policy = await _policy(user_id, project_id)
    price, currency = await _price(user_id, campaign_id)
    sample = project_mode == "demo"  # a demo project's brief is made of sample numbers
    texts = [(e, text) for e in elements if (text := text_of(e)) is not None]
    drafts = cg.extract(
        [cg.TextElement(e["id"], e["kind"], text, e.get("language")) for e, text in texts], policy=policy, region_claims=region_claims,
        brief_price=price, brief_currency=currency, brief_sample=sample)
    model_run: dict[str, Any] | None = None
    if body.include_model_pass:
        model_run = await _model_pass(user_id, project, campaign.id, texts, drafts, region_name, policy, region_claims, (price, currency, sample))
    by_id = {e["id"]: e for e in elements}
    order = {e["id"]: n for n, e in enumerate(elements)}
    drafts = cg.order(drafts, order)
    findings = [_finding(d, by_id[d.element_id], timings) for d in drafts]
    result = {
        "findings": findings, "texts_checked": len(texts), "limitations": LIMITATIONS,
        "policy": {"forbidden": list(policy.forbidden), "allowed": list(policy.allowed), "prohibited_terms": list(policy.prohibited_terms)},
    }
    ran_model = bool(model_run and not model_run.get("error"))
    row = m.ClaimGuardCheck(
        id=uuid4(), project_id=project_id, campaign_id=campaign.id, version_id=node.id, region_code=node.region_code, language=node.language,
        mode="rules_model" if ran_model else "rules", rules_version=cg.RULES_VERSION, result=result, model=model_run, created_by=user_id, created_at=utcnow())
    async with session() as s, s.begin():
        s.add(row)
        await s.flush()
        reviews = await _reviews(s, node.id)
        project_row = await s.get(m.Project, project_id)
        assert project_row is not None
        await record_audit(s, action="studio.claim_guard_check", target_type="claim_guard_check", target_id=str(row.id), workspace_id=project_row.workspace_id,
                           actor_user_id=user_id, detail={"version_id": str(node.id), "findings": len(findings), "mode": row.mode, "demo": project_mode == "demo"})
        touch(project_row)
    return to_check(row, reviews)


async def _model_pass(
    user_id: UUID, project: m.Project, campaign_id: UUID, texts: list[tuple[dict[str, Any], str]], drafts: list[cg.Draft], region: str | None,
    policy: cg.PolicyInput, region_claims: list[dict[str, Any]], price: tuple[float | None, str | None, bool],
) -> dict[str, Any]:
    """The second pass. A provider failure is reported on the check and leaves the rule findings in place; the drafts list grows in place."""
    handles = {f"E{n}": (e, text) for n, (e, text) in enumerate(texts, 1)}
    handle_of = {e["id"]: h for h, (e, _) in handles.items()}
    rows = [{"handle": h, "kind": e["kind"], "language": e.get("language"), "text": text[:1500]} for h, (e, text) in handles.items()]
    already = [{"element": handle_of[d.element_id], "quote": d.quote, "kind": d.kind} for d in drafts][:30]
    gateway = ctx.gateway_for(project.mode)
    try:
        async with guarded_ai_call(user_id, project, campaign_id):
            result = await agent.extract(gateway, stage="reading_claims", region=region, elements=rows, already=already)
    except LLMError as exc:
        logger.warning("claim guard model pass failed: %s", exc.code)
        return {"provider": None, "model_id": None, "prompt_version": agent.PROMPT_VERSION, "estimated_cost_usd": None, "proposed": 0, "kept": 0,
                "dropped": 0, "error": f"{exc.code}: {exc.message}"}
    kept = 0
    for out in result.value.claims:
        found = handles.get(norm(out.element))
        span = locate(found[1], out.quote) if found else None
        if found is None or span is None:
            continue
        element, text = found
        if any(d.element_id == element["id"] and span[0] < d.end and d.start < span[1] for d in drafts):
            continue  # repeats something the rules already found
        quote = text[span[0]:span[1]]
        drafts.append(cg.build(
            cg.TextElement(element["id"], element["kind"], text, element.get("language")), out.kind, "model", None, quote, span[0], span[1],
            cg.phrase_around(text, span[0], span[1]), absolute=bool(claim_features(quote)), certainty="low", policy=policy, region_claims=region_claims,
            brief_price=price[0], brief_currency=price[1], brief_sample=price[2], context=text, explanation=out.explanation))
        kept += 1
    trace = result.trace
    proposed = len(result.value.claims)
    return {"provider": trace.provider, "model_id": trace.model_id, "prompt_version": trace.prompt_version,
            "estimated_cost_usd": trace.usage.estimated_cost_usd if trace.usage else None, "proposed": proposed, "kept": kept,
            "dropped": proposed - kept, "error": None}


# --- reads and reviews -----------------------------------------------------------------------------------------------------


async def list_checks(user_id: UUID, campaign_id: UUID, limit: int, offset: int, version_id: UUID | None) -> t.ClaimGuardCheckPage:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        stmt = select(m.ClaimGuardCheck).where(m.ClaimGuardCheck.campaign_id == campaign.id)
        if version_id is not None:
            stmt = stmt.where(m.ClaimGuardCheck.version_id == version_id)
        rows, total = await paginate(s, stmt.order_by(m.ClaimGuardCheck.created_at.desc(), m.ClaimGuardCheck.id), limit, offset)
        reviews = {v: await _reviews(s, v) for v in {r.version_id for r in rows}}
    items = []
    for row in rows:
        findings = _findings(row, reviews[row.version_id])
        items.append(t.ClaimGuardCheckSummary(**_summary(row, findings)))
    return t.ClaimGuardCheckPage(items=items, limit=limit, offset=offset, total=total)


async def get_check(user_id: UUID, campaign_id: UUID, check_id: UUID) -> t.ClaimGuardCheck:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        row = await s.get(m.ClaimGuardCheck, check_id)
        if row is None or row.campaign_id != campaign.id:
            raise not_found("Claim Guard check")
        reviews = await _reviews(s, row.version_id)
    return to_check(row, reviews)


async def review_finding(user_id: UUID, campaign_id: UUID, body: t.ClaimGuardReviewRequest) -> t.ClaimGuardReview:
    """Record a person's decision about one finding of a version. The finding must appear in a stored check of that version."""
    async with session() as s, s.begin():
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        node = await node_in(s, campaign, body.version_id, "version_id")
        checks = (await s.execute(select(m.ClaimGuardCheck.result).where(m.ClaimGuardCheck.version_id == node.id))).scalars()
        if not any(f["key"] == body.finding_key for result in checks for f in result["findings"]):
            raise ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field="finding_key", message="No check of this version has a finding with this key.")])
        stmt = select(m.ClaimGuardReview).where(m.ClaimGuardReview.version_id == node.id, m.ClaimGuardReview.finding_key == body.finding_key)
        row = (await s.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = m.ClaimGuardReview(id=uuid4(), project_id=project.id, campaign_id=campaign.id, version_id=node.id, finding_key=body.finding_key,
                                     decision=body.decision, note=body.note, reviewed_by=user_id, reviewed_at=utcnow())
            try:
                async with s.begin_nested():
                    s.add(row)
                    await s.flush()
            except IntegrityError:  # a concurrent review of the same finding: this decision replaces theirs
                row = (await s.execute(stmt)).scalar_one()
                row.decision, row.note, row.reviewed_by, row.reviewed_at = body.decision, body.note, user_id, utcnow()
        else:
            row.decision, row.note, row.reviewed_by, row.reviewed_at = body.decision, body.note, user_id, utcnow()
        await record_audit(s, action="studio.claim_guard_review", target_type="claim_guard_review", target_id=str(row.id), workspace_id=project.workspace_id,
                           actor_user_id=user_id, detail={"version_id": str(node.id), "finding_key": body.finding_key, "decision": body.decision})
        touch(project)
        return _review_view(row)
