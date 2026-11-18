"""Server-side gathering of Launch Room observations (Compare and Score `mvp-2`, Readiness `ready-1`).

When a request carries no observations, the server reads the latest relevant stored records for one campaign, region and
Creative Studio version and maps them onto `VersionObservations`:

- Quick Read: the newest completed run for the version and region; counts over its stored synthetic responses.
- Risk Check: the newest completed run for the version and region; its findings (accepted findings stay open).
- Transcreation: the newest `transcreate` operation that produced the version; its code-checked lines.
- References: Creative X-Ray cultural observations of the campaign's creatives and how many carry a claim link.
- Evidence Meter and open conflicts: the region's current evidence, read from the claims service.
- Objective checks: never gathered; no stored record judges a creative against an objective.

Every mapping is a deterministic count over stored records; no model is called and nothing is stored. What was read, and
what could not be found, is returned as `ObservationSources`, and a missing observation stays missing. Runs link to a
version through the opaque `version_ref` the client stored with the run, which Audience Lab sets to the version's id.
"""

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db import models as m
from app.db.session import read_session
from app.schemas import audience as aud
from app.schemas import launch as v
from app.schemas.common import Anchor
from app.services import claims as claims_service
from app.services.common import get_owned
from app.services.versions import node_in

USABLE = ("completed", "partial")
RELEVANT_RATING = 4  # a Quick Read respondent rating cultural relevance 4 or 5 (of 5) counts as finding it relevant
MAX_FINDINGS = 100
MAX_REFERENCES = 200
MAX_CONFLICTS = 50
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
FINDING_STATUS = {"open": "open", "accepted": "open", "fixed": "resolved", "dismissed": "dismissed"}  # accepted still counts
NO_OBJECTIVES = (
    "No stored record judges a creative against a campaign objective (the objective is free text), so objective checks "
    "are never gathered. Supply them in the request."
)


def _uuids(values: Any) -> list[UUID]:
    found = []
    for value in values or []:
        try:
            found.append(UUID(str(value)))
        except ValueError:
            continue
    return found


def _digest(prefix: str, payload: Any) -> str:
    return f"{prefix}-" + hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _joined(values: list[str]) -> str | None:
    return "+".join(sorted(set(values)))[:64] or None


class _Gather:
    """Collects the observations, what was read and what was missing for one version."""

    def __init__(self, version_id: UUID) -> None:
        self.version_id = version_id
        self.obs: dict[str, Any] = {}
        self.gathered: list[v.GatheredInput] = []
        self.missing: list[v.MissingInput] = []
        self.notes: list[str] = []

    def found(self, name: str, source: str, ids: list[UUID], detail: str, *, synthetic: bool = False) -> None:
        self.gathered.append(v.GatheredInput(observation=name, source=source, record_ids=ids, detail=detail, synthetic=synthetic))  # type: ignore[arg-type]

    def lacks(self, name: str, reason: str) -> None:
        self.missing.append(v.MissingInput(observation=name, reason=reason))  # type: ignore[arg-type]


def _is_region(run: m.AudienceRun, region_code: str) -> bool:
    return list(run.region_codes or []) == [region_code]


async def _newest_run(s: Any, campaign_id: UUID, kind: str, version_id: UUID, region_code: str) -> m.AudienceRun | None:
    runs = (await s.execute(
        select(m.AudienceRun).where(
            m.AudienceRun.campaign_id == campaign_id, m.AudienceRun.kind == kind, m.AudienceRun.status.in_(USABLE),
            m.AudienceRun.version_ref == str(version_id),
        ).order_by(m.AudienceRun.created_at.desc(), m.AudienceRun.id.desc())
    )).scalars()
    return next((r for r in runs if _is_region(r, region_code)), None)


def _run_provenance(run: m.AudienceRun) -> dict[str, Any]:
    steps = [st for st in run.steps or [] if st.get("provider") not in (None, "omnicult", "fixture")]
    inputs = run.inputs or {}
    panel = inputs.get("panel") or {}
    claims = sorted((c.get("id", ""), c.get("kind", ""), c.get("confidence", ""), c.get("value_text", "")) for c in inputs.get("claims", []))
    criteria = {k: panel.get(k) for k in (
        "requested_size", "states", "languages", "city_tiers", "age_bands", "weights", "sampling_version")} | {"seed": run.seed}
    return {
        "model_id": _joined([st["model_id"] for st in steps if st.get("model_id")]),
        "prompt_version": _joined([st["prompt_version"] for st in steps if st.get("prompt_version")]),
        "criteria_version": _digest("panel", criteria) if panel else None,
        "evidence_snapshot": _digest("claims", claims),
    }


async def _quick_read(s: Any, g: _Gather, campaign_id: UUID, region_code: str) -> m.AudienceRun | None:
    run = await _newest_run(s, campaign_id, "quick_read", g.version_id, region_code)
    if run is None:
        g.lacks("quick_read", "No completed Quick Read is stored for this version and region (run one from Audience Lab on this version).")
        return None
    rows = list((await s.execute(select(m.PanelParticipant).where(m.PanelParticipant.run_id == run.id))).scalars())
    responses = []
    for row in rows:
        try:
            if row.response:
                responses.append(aud.QuickReadResponse.model_validate(row.response))
        except ValueError:
            continue
    if not responses:
        g.lacks("quick_read", f"The newest Quick Read ({run.id}) has no readable synthetic response.")
        return None
    n = len(responses)
    understood = sum(r.message.survival == "understood" for r in responses)
    confused = sum(r.message.survival == "misunderstood" or (r.sentiment == "confused" and r.message.survival != "understood") for r in responses)
    cited = (run.result or {}).get("grounding", {}).get("cited_claim_ids", [])
    g.obs["quick_read"] = v.QuickReadObservation(
        respondents=n, understood=understood, confused=confused, positive=sum(r.sentiment == "positive" for r in responses),
        negative=sum(r.sentiment == "negative" for r in responses),
        relevant=sum(r.ratings.get("cultural_relevance", 0) >= RELEVANT_RATING for r in responses),
        concerned=sum(bool(r.regional_concerns) for r in responses), evidence_ids=_uuids(cited)[:20])
    g.found(
        "quick_read", "quick_read_run", [run.id],
        f"Counts over {n} stored synthetic responses of the newest completed Quick Read: understood = message restated "
        f"correctly; confused = message misunderstood or reaction confused; relevant = cultural relevance rated "
        f"{RELEVANT_RATING} or 5 of 5; concerned = at least one regional concern.", synthetic=True)
    if len(responses) < len(rows):
        g.notes.append(f"{len(rows) - len(responses)} of the Quick Read's {len(rows)} participants have no readable response and are not counted.")
    return run


async def _risk_check(s: Any, g: _Gather, campaign_id: UUID, region_code: str) -> m.AudienceRun | None:
    run = await _newest_run(s, campaign_id, "risk_check", g.version_id, region_code)
    if run is None:
        g.lacks("risk_check", "No completed Risk Check is stored for this version and region (run one from Audience Lab on this version).")
        return None
    rows = list((await s.execute(
        select(m.RiskFindingRow).where(m.RiskFindingRow.run_id == run.id).order_by(m.RiskFindingRow.ordinal)
    )).scalars())
    kept = sorted(rows, key=lambda f: (SEVERITY_ORDER[f.severity], f.ordinal))[:MAX_FINDINGS]
    g.obs["risk_check"] = v.RiskCheckObservation(run_id=run.id, findings=[
        v.RiskFindingInput(
            id=str(f.id), severity=f.severity, category=f.category[:40], status=FINDING_STATUS[f.status],  # type: ignore[arg-type]
            blocks_go=f.blocks_go, source=f.source, summary=f.observation[:300], claim_ids=_uuids(f.claim_ids)[:20],  # type: ignore[arg-type]
            anchor=Anchor.model_validate(f.anchor))
        for f in kept])
    g.found("risk_check", "risk_check_run", [run.id],
            f"{len(rows)} finding(s) of the newest completed Risk Check; accepted findings still count as open, fixed ones as resolved.")
    if len(rows) > len(kept):
        g.notes.append(f"The Risk Check has {len(rows)} findings; the {len(kept)} most severe are carried.")
    return run


async def _transcreation(s: Any, g: _Gather, campaign_id: UUID, region_code: str) -> None:
    operations = (await s.execute(
        select(m.Operation).where(
            m.Operation.campaign_id == campaign_id, m.Operation.kind == "transcreate", m.Operation.status == "applied",
            m.Operation.result_version_id == g.version_id,
        ).order_by(m.Operation.created_at.desc(), m.Operation.id.desc())
    )).scalars()
    op = next((o for o in operations if (o.params or {}).get("region_code") == region_code and (o.params or {}).get("lines")), None)
    if op is None:
        g.lacks("transcreation", "This version was not produced by a transcreation for this region, so no code-checked lines are stored for it.")
        return
    lines = op.params["lines"]
    violating = [x for x in lines if _violates(x)]
    g.obs["transcreation"] = v.TranscreationObservation(
        lines_checked=len(lines), glossary_violation_lines=len(violating),
        prohibited_term_lines=sum(bool(x["term_checks"].get("prohibited_in_copy") or x["term_checks"].get("prohibited_in_back_translation")) for x in violating),
        meaning_preserved_lines=None, script_error_lines=sum(not x["script_check"].get("ok", True) for x in lines))
    failed = sum(not x.get("passed", True) for x in lines)
    g.found("transcreation", "transcreate_operation", [op.id],
            f"Glossary and script checks computed in code over {len(lines)} line(s) of the transcreation that produced this version"
            + (f"; {failed} of them failed a check and were not applied, and still count here." if failed else "."))
    g.notes.append("Transcreation: back-translation meaning is not gathered (code does not judge it), so meaning_preserved_lines is null.")


def _violates(line: dict[str, Any]) -> bool:
    t = line.get("term_checks", {})
    return bool(
        not t.get("protected_preserved", True) or t.get("missing_in_copy") or t.get("missing_in_back_translation")
        or t.get("prohibited_in_copy") or t.get("prohibited_in_back_translation"))


async def _references(s: Any, g: _Gather, campaign_id: UUID, region_code: str) -> list[UUID]:
    creatives = [c for c in (await s.execute(
        select(m.CreativeAsset).where(m.CreativeAsset.campaign_id == campaign_id, m.CreativeAsset.current_run_id.is_not(None))
        .order_by(m.CreativeAsset.created_at, m.CreativeAsset.id)
    )).scalars() if c.region_code in (None, region_code)]
    scenes = []
    for creative in creatives:
        scenes += list((await s.execute(
            select(m.CreativeScene).where(m.CreativeScene.creative_asset_id == creative.id, m.CreativeScene.run_id == creative.current_run_id)
            .order_by(m.CreativeScene.position, m.CreativeScene.id)
        )).scalars())
    references = [o for sc in scenes for o in (sc.payload or {}).get("cultural_observations", [])][:MAX_REFERENCES]
    if not references:
        g.lacks("references", "No Creative X-Ray cultural observation is stored for this campaign and region, so no references were counted.")
        return []
    linked = [_uuids(o.get("claim_ids", [])) for o in references]
    g.obs["references"] = v.ReferenceObservation(references_checked=len(references), references_supported=sum(bool(x) for x in linked))
    g.found("references", "creative_scenes", [c.id for c in creatives],
            f"{len(references)} cultural observation(s) in the current X-Ray analysis of {len(creatives)} creative(s); "
            "supported = the observation carries a link to at least one evidence claim. X-Ray records belong to the campaign's "
            "creatives, not to one version, so every version of the campaign reads the same references.")
    if not any(linked):
        g.notes.append("None of the X-Ray observations is linked to an evidence claim yet, so reference grounding reads 0.")
    return [c for ids in linked for c in ids]


async def _relied_claims(s: Any, campaign_id: UUID, version_id: UUID) -> set[UUID]:
    """Claims cited by the operations that made this version or any version it descends from."""
    nodes = {n.id: n.parent_id for n in (await s.execute(
        select(m.VersionNode.id, m.VersionNode.parent_id).where(m.VersionNode.campaign_id == campaign_id))).all()}
    chain, current = [], version_id
    while current is not None and current not in chain:
        chain.append(current)
        current = nodes.get(current)
    ops = (await s.execute(
        select(m.Operation.claim_ids).where(m.Operation.result_version_id.in_(chain), m.Operation.status == "applied"))).scalars()
    return {c for ids in ops for c in _uuids(ids)}


async def _evidence(g: _Gather, user_id: UUID, project: m.Project, region_code: str, relied: set[UUID]) -> None:
    if project.workspace_id is None:
        for name in ("evidence_meter", "open_conflicts"):
            g.lacks(name, "The campaign's project has no workspace, so no claims can be read.")  # type: ignore[arg-type]
        return
    profile = await claims_service.build_region_profile(user_id, project.workspace_id, region_code, mode=project.mode)
    meter = profile.meter
    g.obs["evidence_meter"] = v.EvidenceMeterObservation(
        strength=meter.strength, claims=meter.claims, supported_claims=meter.supported_claims,  # type: ignore[arg-type]
        open_conflicts=meter.open_conflicts, stale_claims=meter.stale_claims)
    g.found("evidence_meter", "claims", [], f"The Evidence Meter of {meter.region_name} read now: {meter.strength}.")
    conflicts, total = await claims_service.list_conflicts(
        user_id, project.workspace_id, region_code=region_code, status=None, mode=project.mode, limit=MAX_CONFLICTS, offset=0)
    unresolved = [c for c in conflicts if c.status != "resolved"]
    g.obs["open_conflicts"] = [
        v.OpenConflictInput(
            conflict_id=c.id, claim_ids=[c.claim_a.id, c.claim_b.id], status=c.status,  # type: ignore[arg-type]
            relied_on=bool({c.claim_a.id, c.claim_b.id} & relied), summary=c.reason[:300])
        for c in unresolved]
    g.found("open_conflicts", "claims", [c.id for c in unresolved],
            f"{len(unresolved)} unresolved conflict(s) of the region read now; relied_on = the version's own operations "
            "(or the versions it descends from) cite one of the conflicting claims.")
    if total > len(conflicts):
        g.notes.append(f"The region has {total} conflicts; the first {len(conflicts)} were read.")


async def gather(user_id: UUID, campaign_id: UUID, region_code: str, version_id: UUID) -> tuple[v.VersionObservations, v.ObservationSources]:
    """The observations stored records give for this version in this region, and a report of what was and was not found.
    404 when the campaign is not reachable or the version is not a Creative Studio version of it."""
    g = _Gather(version_id)
    async with read_session() as s:
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        await node_in(s, campaign, version_id, "version_id")
        quick = await _quick_read(s, g, campaign.id, region_code)
        risk = await _risk_check(s, g, campaign.id, region_code)
        await _transcreation(s, g, campaign.id, region_code)
        linked_claims = await _references(s, g, campaign.id, region_code)
        relied = await _relied_claims(s, campaign.id, version_id) | set(linked_claims)
    await _evidence(g, user_id, project, region_code, relied)
    g.lacks("objective_checks", NO_OBJECTIVES)
    run = quick or risk
    runs = [r.id for r in (quick, risk) if r is not None]
    provenance = v.Provenance(**(_run_provenance(run) if run is not None else {}), run_ids=runs)
    observations = v.VersionObservations(provenance=provenance, **g.obs)
    sources = v.ObservationSources(version_id=version_id, origin="gathered", gathered=g.gathered, missing=g.missing, notes=g.notes)
    return observations, sources


def describe_supplied(version_id: UUID, observations: v.VersionObservations) -> v.ObservationSources:
    """The report for observations the request carried: nothing was read, and anything absent is listed as missing."""
    absent = {
        "quick_read": observations.quick_read is None, "risk_check": observations.risk_check is None,
        "transcreation": observations.transcreation is None, "references": observations.references is None,
        "objective_checks": not observations.objective_checks, "evidence_meter": observations.evidence_meter is None,
    }
    return v.ObservationSources(
        version_id=version_id, origin="supplied", gathered=[],
        missing=[v.MissingInput(observation=name, reason="Not supplied in the request.") for name, gone in absent.items() if gone],  # type: ignore[arg-type]
        notes=["The observations were supplied by the client; the server read no stored records."])
