"""Transcreate as a run (feature 17): start it, build the workflow input, and persist its outcome as an operation.

The run records everything it was given (the lines, the region's claims, the glossary entries, the tone dials), so the
result can be explained later even if the claims or the glossary change. The outcome becomes one `transcreate`
operation through the same engine as every other change: lines that passed the code checks are applied to a NEW version,
failed lines are kept on the operation for review, and a locked element refuses the whole operation.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.transcreate import PROMPT_VERSION
from app.db import models as m
from app.db.session import read_session
from app.schemas import versions as v
from app.schemas.runs import RunAccepted, RunError
from app.services import studio_context as ctx
from app.services.common import conflict
from app.services.results import API
from app.services.runs import _create_run
from app.services.versions import active_locks, campaign_for, newest_node, node_in, record_operation
from app.studio.engine import Edit, OpSpec
from app.workflows.transcreate import TranscreateInput, TranscreateOutcome


async def start_transcreate(user_id: UUID, campaign_id: UUID, body: v.TranscreateRequest, *, direct: dict[str, Any] | None = None) -> RunAccepted:
    """`direct` (the Voice Director's plan id, step id and instruction) is kept on the run and read back when the operation
    is recorded, so the person's instruction becomes the reason on the version."""
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        source = await node_in(s, campaign, body.version_id, "version_id") if body.version_id else await newest_node(s, campaign.id)
        if source is None:
            raise conflict("version_id", "This campaign has no version yet. Create one first (POST /campaigns/{id}/versions).")
        region = await ctx.region_named(s, body.region_code)
        language = await ctx.language_named(s, body.language)
        locks = await active_locks(s, campaign.id)
        elements = {e["id"]: e for e in source.elements}
        if body.element_ids is None:
            chosen = [e for e in source.elements if e["kind"] in v.TEXT_KINDS and isinstance(e.get("value"), str)
                      and e["value"].strip() and e["id"] not in locks]
            if not chosen:
                raise conflict("element_ids", "This version has no unlocked text element to transcreate.")
        else:
            chosen = []
            for index, element_id in enumerate(body.element_ids):
                element = elements.get(element_id)
                field = f"element_ids.{index}"
                if element is None:
                    raise conflict(field, f"Element '{element_id}' does not exist in this version.")
                if element["kind"] not in v.TEXT_KINDS or not isinstance(element.get("value"), str):
                    raise conflict(field, f"Only text elements can be transcreated; '{element_id}' is a {element['kind']}.")
                if element_id in locks:
                    raise conflict(field, f"Element '{element_id}' is locked. Unlock it to transcreate it.")
                chosen.append(element)
        claims = await ctx.region_claims(s, project, region)
        glossary = await ctx.glossary_entries(s, project.id, language.code)
    inputs: dict[str, Any] = {
        "request": body.model_dump(mode="json"), "source_version_id": str(source.id), "region_code": region.code,
        "region_name": region.name, "language": language.code, "language_name": language.name, "script": language.script,
        "tone": body.tone.model_dump(),
        "lines": [{"handle": f"L{i}", "element_id": e["id"], "kind": e["kind"], "text": e["value"]} for i, e in enumerate(chosen, 1)],
        "claims": claims, "glossary": glossary, **({"direct": direct} if direct else {}),
    }
    return await _create_run(user_id, project, "transcreate", inputs, campaign_id=campaign.id)


async def build_input(s: AsyncSession, run: m.AgentRun, types: Any, context: Any, grounding: Any) -> TranscreateInput:
    data = run.inputs
    return TranscreateInput(
        context=context, source_version_id=UUID(data["source_version_id"]), region_code=data["region_code"],
        region_name=data["region_name"], language=data["language"], language_name=data["language_name"],
        script=data["script"], tone=v.Tone.model_validate(data["tone"]), lines=data["lines"], claims=data["claims"],
        glossary=data["glossary"],
    )


def _generation(outcome: TranscreateOutcome, run: m.AgentRun) -> dict[str, Any]:
    step = next((t for t in outcome.steps if t.prompt_version == PROMPT_VERSION), None)
    return {"run_id": str(run.id), "provider": step.provider if step else None, "model_id": step.model_id if step else None,
            "prompt_version": PROMPT_VERSION, "mode": run.mode}


def _cost(outcome: TranscreateOutcome) -> float | None:
    costs = [t.usage.estimated_cost_usd for t in outcome.steps if t.usage and t.usage.estimated_cost_usd is not None]
    return sum(costs) if costs else None


async def persist(s: AsyncSession, run: m.AgentRun, outcome: TranscreateOutcome, new_ids: list[str], now: datetime) -> tuple[dict, tuple]:
    """Record the outcome as one `transcreate` operation. Returns the run payload and its result reference. A payload key
    `_status` overrides the run's status: a refused operation (a lock set meanwhile, or no line passed) is not a success."""
    data = run.inputs
    limitations = list(outcome.limitations)
    if outcome.status == "failed" or not outcome.lines:  # the model call failed: there is nothing to record
        return {"operation_id": None, "version_id": None, "lines": [], "limitations": limitations}, ("version", [], "")
    campaign, project = await s.get(m.Campaign, run.campaign_id), await s.get(m.Project, run.project_id)
    source = await s.get(m.VersionNode, UUID(data["source_version_id"]))
    assert campaign is not None and project is not None and source is not None
    passing = [x for x in outcome.lines if x.passed]
    language, region_code, script = data["language"], data["region_code"], data["script"]
    spec = OpSpec(
        "transcreate",
        edits=[Edit(x.element_id, {"value": x.regional_copy, "language": language, "script": script}) for x in passing],
        region_code=region_code, language=language, tone=data["tone"], generation=_generation(outcome, run),
    )
    claim_ids = list(dict.fromkeys(c for x in passing for c in x.claim_ids))
    params = {
        "run_id": str(run.id), "region_code": region_code, "language": language, "script": script, "tone": data["tone"],
        "source_version_id": data["source_version_id"], "lines": [x.model_dump(mode="json") for x in outcome.lines],
    }
    rejection = None
    if not passing:
        rejection = v.Rejection(code="CHECKS_FAILED", element_ids=[x.element_id for x in outcome.lines],
                                message="No line passed the script and glossary checks; nothing was applied.")
    reason = f"Transcreated {len(passing)} of {len(outcome.lines)} line(s) into {data['language_name']} for {data['region_name']}."
    if direct := data.get("direct"):  # started by the Voice Director: the instruction leads, the counts follow
        reason = f"{direct['instruction']} ({reason})"
        params |= {key: direct[key] for key in ("direct_plan_id", "direct_step_id", "direct_source")}
    op, node = await record_operation(
        s, project=project, campaign=campaign, source=source, spec=spec, actor="ai", actor_user_id=run.created_by,
        reason=reason, claim_ids=claim_ids, params=params, label=f"Transcreation: {data['language_name']} ({data['region_code']})"[:80],
        prompt_version=PROMPT_VERSION, estimated_cost_usd=_cost(outcome), rejection=rejection,
    )
    payload: dict[str, Any] = {
        "operation_id": str(op.id), "version_id": str(node.id) if node else None,
        "lines": [x.model_dump(mode="json") for x in outcome.lines], "limitations": limitations,
    }
    if node is None:
        refused = op.rejection or {}
        payload["_status"] = "failed"
        outcome.error = RunError(
            code="CONFLICT" if refused.get("code") == "LOCKED" else "RUN_FAILED", retryable=refused.get("code") == "CHECKS_FAILED",
            message=f"{refused.get('message', 'The operation was refused.')} The transcreated lines are on operation {op.id} for review.",
        )
        return payload, ("operation", [op.id], f"{API}/campaigns/{campaign.id}/operations/{op.id}")
    partial = outcome.status == "partial" or len(passing) < len(outcome.lines)
    payload["_status"] = "partial" if partial else "completed"
    return payload, ("version", [node.id], f"{API}/campaigns/{campaign.id}/versions/{node.id}")
