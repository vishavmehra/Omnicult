"""Tweak Chips (feature 19): propose, store and apply contextual one-click changes to one element.

Generation is one structured model call over the region's claims; code then drops every proposal that cites a claim that
was not supplied, cannot be applied, breaks a glossary rule or leaves the element's script (app.agents.tweak). Applying a
chip is an `apply_chip` operation through the same engine as a hand edit, so locks hold and a new version is created.
"""

from uuid import UUID, uuid4

from sqlalchemy import select

from app.agents import brand as brand_agent
from app.agents import tweak
from app.agents._common import norm
from app.core.errors import ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.llm.gateway import LLMError
from app.schemas import versions as v
from app.services import studio_context as ctx
from app.services.ai_guard import guarded_ai_call
from app.services.common import conflict, not_found, paginate
from app.services.runs import brand_of, merge_terms
from app.services.versions import (
    active_locks,
    campaign_for,
    node_in,
    raise_if_rejected,
    record_operation,
    to_node,
    to_operation,
    verified_claim_ids,
)
from app.studio.engine import Edit, OpSpec
from app.workflows.types import BrandContext

NO_TWEAK_KINDS = frozenset({"logo", "packshot"})  # brand-protected assets: a model never proposes changes to them


def to_chip(row: m.Chip) -> v.Chip:
    return v.Chip(
        id=row.id, campaign_id=row.campaign_id, version_id=row.version_id, element_id=row.element_id, title=row.title,
        operation_type=row.operation_type,  # type: ignore[arg-type]
        change=v.ChipChange.model_validate(row.change), params=row.params, reason=row.reason,
        claim_ids=[UUID(c) for c in row.claim_ids], expected_effect=row.expected_effect, reversible=row.reversible,
        estimated_cost_usd=row.estimated_cost_usd, status=row.status,  # type: ignore[arg-type]
        applied_operation_id=row.applied_operation_id, applied_version_id=row.applied_version_id,
        prompt_version=row.prompt_version, provider=row.provider, model_id=row.model_id, created_at=row.created_at,
    )


async def generate_chips(user_id: UUID, campaign_id: UUID, body: v.ChipGenerate) -> v.ChipsGenerated:
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        source = await node_in(s, campaign, body.version_id, "version_id")
        element = next((e for e in source.elements if e["id"] == body.element_id), None)
        if element is None:
            raise not_found("Element", "element_id")
        if body.element_id in await active_locks(s, campaign.id):
            raise conflict("element_id", f"Element '{body.element_id}' is locked. Unlock it to get tweak chips for it.")
        if element["kind"] in NO_TWEAK_KINDS or not isinstance(element.get("value"), str) or not element["value"].strip():
            raise conflict("element_id", f"Tweak chips need an element with text; '{body.element_id}' is a {element['kind']}.")
        region = await ctx.region_named(s, body.region_code)
        claims = await ctx.region_claims(s, project, region)
        glossary = await ctx.glossary_entries(s, project.id, element.get("language"))
        brand = await brand_of(s, project.id)
        brand_context = BrandContext.model_validate({
            "name": brand.name, "description": brand.description, "positioning": brand.positioning, "voice": brand.voice,
            "communication_style": brand.communication_style, "target_audience": brand.target_audience,
            "audience_preferences": brand.audience_preferences, "preferred_terms": brand.preferred_terms,
            "prohibited_terms": brand.prohibited_terms, "protected_terms": brand.protected_terms, "constraints": brand.constraints,
        })
        others = [{k: e[k] for k in ("id", "kind", "value")} for e in source.elements
                  if e["id"] != body.element_id and isinstance(e.get("value"), str)][:12]
        protected = merge_terms(brand.protected_terms)
        prohibited = list(brand.prohibited_terms)
    handles = {norm(c["handle"]): UUID(c["id"]) for c in claims}
    digest = [{key: val for key, val in c.items() if key != "id"} for c in claims]  # the model sees handles, never database ids
    gateway = ctx.gateway_for(project.mode)
    try:
        async with guarded_ai_call(user_id, project, campaign.id):  # 429 over the per-user or per-workspace limit
            result = await tweak.propose_chips(
                gateway, stage="proposing_chips", element=element, context=others, region=f"{region.name} ({region.code})",
                claims=digest, glossary=glossary, brand=brand_agent.brand_block(brand_context)[0], count=body.max_chips,
            )
    except LLMError as exc:
        raise ctx.llm_failure(exc) from exc
    drafts, notes = tweak.validate_chips(
        result.value.chips, element=element, handles=handles, glossary=glossary, protected=protected, prohibited=prohibited,
        limit=body.max_chips,
    )
    if not claims:
        notes.append("No claims are recorded for this region, so no chip can cite evidence and none was kept.")
    trace = result.trace
    cost = trace.usage.estimated_cost_usd if trace.usage else None
    share = cost / len(drafts) if cost is not None and drafts else None
    async with session() as s, s.begin():
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        # The claims the chips cite must still exist when they are stored (a claim could have been rejected meanwhile).
        rows = []
        for draft in drafts:
            await verified_claim_ids(s, project, draft.claim_ids, "claims")
            rows.append(m.Chip(
                id=uuid4(), campaign_id=campaign.id, project_id=project.id, version_id=source.id, element_id=body.element_id,
                title=draft.title, operation_type=draft.operation_type, change={key: val for key, val in draft.change.items() if val is not None},
                params={"region_code": body.region_code, "language": element.get("language"), "claims_offered": len(claims)},
                reason=draft.reason, claim_ids=[str(c) for c in draft.claim_ids], expected_effect=draft.expected_effect,
                reversible=True,  # applying creates a new version, so restoring the previous one undoes it
                estimated_cost_usd=share, prompt_version=trace.prompt_version, provider=trace.provider, model_id=trace.model_id,
                status="proposed", created_by=user_id, created_at=utcnow(),
            ))
        s.add_all(rows)
    dropped = len(result.value.chips) - len(drafts)
    return v.ChipsGenerated(chips=[to_chip(r) for r in rows], dropped=max(0, dropped), notes=notes)


async def list_chips(
    user_id: UUID, campaign_id: UUID, limit: int, offset: int, version_id: UUID | None = None, element_id: str | None = None,
    status: str | None = None,
) -> v.ChipPage:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        stmt = select(m.Chip).where(m.Chip.campaign_id == campaign.id)
        for column, value in ((m.Chip.version_id, version_id), (m.Chip.element_id, element_id), (m.Chip.status, status)):
            if value is not None:
                stmt = stmt.where(column == value)
        rows, total = await paginate(s, stmt.order_by(m.Chip.created_at.desc(), m.Chip.id), limit, offset)
    return v.ChipPage(items=[to_chip(r) for r in rows], limit=limit, offset=offset, total=total)


async def apply_chip(user_id: UUID, campaign_id: UUID, chip_id: UUID, body: v.ChipApply) -> v.ChipApplied:
    """Apply a chip as an `apply_chip` operation (actor ai: the change was proposed by a model, applied by this user)."""
    async with session() as s, s.begin():
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        chip = await s.get(m.Chip, chip_id)
        if chip is None or chip.campaign_id != campaign.id:
            raise not_found("Chip")
        if chip.status == "applied":
            raise conflict("chip_id", "This chip was already applied. Restore an earlier version to undo it.")
        source = await node_in(s, campaign, body.version_id or chip.version_id, "version_id")
        try:
            claim_ids = await verified_claim_ids(s, project, [UUID(c) for c in chip.claim_ids])
        except ValidationFailed:
            raise conflict("chip_id", "A claim supporting this chip is no longer available. Generate new chips.") from None
        change = chip.change
        if chip.operation_type == "replace_text":
            spec = OpSpec("apply_chip", edits=[Edit(chip.element_id, {"value": change["value"]})])
        else:
            spec = OpSpec("apply_chip", swap=(chip.element_id, change["from_text"], change["to_text"]))
        op, node = await record_operation(
            s, project=project, campaign=campaign, source=source, spec=spec, actor="ai", actor_user_id=user_id,
            reason=chip.reason, claim_ids=claim_ids,
            params={"chip_id": str(chip.id), "element_id": chip.element_id, "operation_type": chip.operation_type, "change": change},
            label=chip.title[:80], prompt_version=chip.prompt_version, estimated_cost_usd=chip.estimated_cost_usd,
        )
        if node is not None:
            chip.status, chip.applied_operation_id, chip.applied_version_id = "applied", op.id, node.id
    raise_if_rejected(op)  # after the commit: a refused chip stays proposed and the refusal stays on record
    assert node is not None
    return v.ChipApplied(chip=to_chip(chip), operation=to_operation(op), version=to_node(node))
